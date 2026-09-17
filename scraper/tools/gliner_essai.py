"""Voir ce que l'étiqueteur regarde, et ce qu'il a failli trouver.

Le banc dit *combien* de champs sont justes. Il ne dit pas **pourquoi** un
champ est vide, et c'est la seule question qui fasse avancer un réglage. Trois
causes donnent le même zéro au tableau, et elles demandent trois corrections
opposées :

1. **le modèle n'a pas vu le texte** — la fenêtre d'un encodeur se compte en
   jetons, pas en pages, et ce qui dépasse est ignoré *en silence* ;
2. **il a vu, il a trouvé, et le seuil l'a écarté** — le span est là, à 0,31,
   sous une barre posée à 0,50 ;
3. **il a vu et n'a rien trouvé** — le libellé ne lui parle pas.

Ce script les distingue. Il montre, pour chaque passe, la tranche de page
réellement soumise et jusqu'où le modèle a posé des spans ; puis, champ par
champ, **tout** ce qu'il a proposé jusqu'à un plancher bien plus bas que le
seuil de production, en marquant ce que la production aurait gardé.

    pip install -e ".[gliner]"
    python -m tools.gliner_essai tests/fixtures/pages/spectacle-avec-json-ld.html
    python -m tools.gliner_essai <page> --seuil 0.3
    python -m tools.gliner_essai <page> --libelles "tarif=price,prix d'entrée=price"

La dernière forme est celle qui sert le plus : les libellés sont un réglage à
part entière, et le premier à mesurer plutôt qu'à deviner.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sortiesbot.ancrage import audit_fiche, fiche_payload  # noqa: E402
from sortiesbot.evaluation import read_from_html  # noqa: E402
from sortiesbot.harvest import Fetcher, FetchError  # noqa: E402
from sortiesbot.providers.base import ProviderError  # noqa: E402
from sortiesbot.providers.gliner_provider import (  # noqa: E402
    MODELE_DEFAUT,
    GlinerProvider,
    _decouper,
    fenetre_caracteres,
)
from sortiesbot.spans import LABELS, SEUIL_DEFAUT, Span, to_event, unfilled_fields  # noqa: E402

#: Jusqu'où descendre pour montrer ce que le modèle a *failli* rendre. Bien
#: sous le seuil de production : c'est tout l'intérêt.
PLANCHER = 0.05


def _page(source: str) -> tuple[str, str]:
    """Le HTML et l'URL, que la source soit une archive du corpus, un fichier ou une adresse.

    Les pages du banc sont **gzippées** — `<32 hexa>.html.gz` sous
    `$UPLOADS_DIR/eval/`, voir `server/src/lib/evalPages.ts`. C'est le cas qui
    sert le plus, puisque ce sont elles que le banc rejoue : ne pas savoir les
    ouvrir obligeait à les déballer à la main avant chaque essai.
    """
    if source.startswith(("http://", "https://")):
        try:
            return Fetcher().get_html(source), source
        except FetchError as err:
            print(f"Téléchargement impossible : {err}", file=sys.stderr)
            return "", source
    chemin = Path(source)
    if chemin.suffix == ".gz":
        import gzip

        with gzip.open(chemin, "rt", encoding="utf-8", errors="replace") as f:
            return f.read(), chemin.resolve().as_uri()
    return chemin.read_text(encoding="utf-8", errors="replace"), chemin.resolve().as_uri()


def _libelles(brut: str | None) -> dict[str, str]:
    """Un jeu de libellés donné en ligne de commande, ou celui de production.

    Forme : `libellé=champ,libellé=champ`. Le champ doit être l'un de ceux que
    `spans.LABELS` nourrit, sans quoi la fiche ne saurait qu'en faire.
    """
    if not brut:
        return dict(LABELS)
    champs = set(LABELS.values())
    out: dict[str, str] = {}
    for paire in brut.split(","):
        libelle, _, champ = paire.partition("=")
        libelle, champ = libelle.strip(), champ.strip()
        if not libelle or champ not in champs:
            raise SystemExit(f"Libellé « {paire.strip()} » : champ attendu parmi {sorted(champs)}")
        out[libelle] = champ
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", help="un fichier HTML gelé, ou une URL")
    parser.add_argument("--modele", default=MODELE_DEFAUT, help=f"défaut : {MODELE_DEFAUT}")
    parser.add_argument("--seuil", type=float, default=SEUIL_DEFAUT)
    parser.add_argument("--plancher", type=float, default=PLANCHER)
    parser.add_argument("--libelles", help="« libellé=champ,libellé=champ » à la place des nôtres")
    parser.add_argument("--texte", action="store_true", help="afficher le texte de chaque passe")
    args = parser.parse_args(argv)

    html, url = _page(args.source)
    if not html:
        print(f"Rien à lire depuis « {args.source} ».", file=sys.stderr)
        return 2

    # L'étage 5 d'abord : le texte soumis ici doit être celui que le banc
    # donnera, sinon ce qu'on regarde ne dit rien de ce qu'on mesurera.
    lecture = read_from_html(html, url)
    texte = lecture.get("text", "")

    provider = GlinerProvider(gliner_model=args.modele, seuil=args.plancher)
    try:
        tagger = provider._charger()
    except ProviderError as err:
        print(str(err), file=sys.stderr)
        return 2

    libelles = _libelles(args.libelles)
    budget, recouvrement = fenetre_caracteres(tagger, list(libelles))
    morceaux = _decouper(texte, budget, recouvrement)

    print(f"Page   : {url}")
    print(f"Texte  : {len(texte)} caractères (étage 5)")
    print(f"Modèle : {args.modele}")
    print(
        f"Fenêtre: {budget} car. par passe · {len(morceaux)} passe(s) · "
        f"seuil {args.seuil} · plancher {args.plancher}"
    )
    print(f"Champs : {len(libelles)} libellé(s)\n")

    # ── 1. ce que le modèle a eu sous les yeux, passe par passe
    print("── Ce qu'il a regardé ──")
    spans: list[Span] = []
    for numero, (decalage, morceau) in enumerate(morceaux, start=1):
        bruts = tagger.predict_entities(morceau, list(libelles), threshold=args.plancher)
        for b in bruts:
            spans.append(
                Span(
                    label=str(b.get("label", "")),
                    text=str(b.get("text", "")),
                    start=int(b.get("start", 0)) + decalage,
                    end=int(b.get("end", 0)) + decalage,
                    score=float(b.get("score", 0.0)),
                )
            )
        # Jusqu'où, dans CE tronçon, le modèle a-t-il posé quelque chose ? Si
        # tout s'arrête bien avant la fin, c'est qu'il n'a pas lu jusque-là —
        # la fenêtre est trop large, et le reste part à la poubelle en silence.
        loin = max((int(b.get("end", 0)) for b in bruts), default=0)
        fin = decalage + len(morceau)
        marque = ""
        if bruts and loin < len(morceau) * 0.6:
            marque = "  ⚠ rien au-delà de ce point : fenêtre probablement trop large"
        print(
            f"  passe {numero:>2}  car. {decalage:>5} → {fin:<5}  "
            f"{len(bruts):>3} span(s)  dernier à {decalage + loin if bruts else '—'}{marque}"
        )
        if args.texte:
            print(f"        « {morceau[:160]}… »")
    print()

    # ── 2. ce qu'il a proposé, champ par champ, seuil compris
    print(f"── Ce qu'il a proposé, par champ (plancher {args.plancher}) ──")
    par_champ: dict[str, list[Span]] = defaultdict(list)
    for span in spans:
        par_champ[libelles.get(span.label, "?")].append(span)

    for champ in sorted(set(libelles.values())):
        propositions = sorted(par_champ.get(champ, []), key=lambda s: -s.score)
        if not propositions:
            print(f"  {champ:<20} rien, pas même sous le seuil")
            continue
        for rang, span in enumerate(propositions[:4]):
            retenu = "  ← retenu" if span.score >= args.seuil else ""
            sous = "  ← SOUS LE SEUIL" if rang == 0 and span.score < args.seuil else ""
            nom = champ if rang == 0 else ""
            print(f"  {nom:<20} {span.score:.2f}  « {span.text[:60]} »{retenu}{sous}")
    print()

    # ── 3. la fiche que la production en tirerait, et l'audit du banc
    event = to_event([s for s in spans if s.score >= args.seuil], seuil=args.seuil)
    print("── La fiche, au seuil de production ──")
    print(json.dumps(fiche_payload(event), ensure_ascii=False, indent=2, sort_keys=True))

    print("\n── Ancrage (les instruments du banc) ──")
    for aspect in audit_fiche(event, texte, list(lecture.get("dates", []))):
        drapeaux = ", ".join(aspect["flags"]) or "—"
        note = ""
        if not aspect["filled"] and aspect["key"] in {"description", "cadre", "categorie"}:
            note = "  (hors portée d'un étiqueteur)"
        print(f"  {aspect['label']:<22} {aspect['value'] or '∅':<40} {drapeaux}{note}")

    print(f"\nChamps qu'un étiqueteur ne rend pas : {', '.join(sorted(unfilled_fields()))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
