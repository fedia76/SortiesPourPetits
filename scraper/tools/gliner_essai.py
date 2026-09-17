"""Voir ce que l'étiqueteur tire d'une page, sans console, sans banc, sans worker.

Le chemin normal de l'expérience passe par la console d'évaluation : on lance
un run d'étage 6 avec `SPP_BENCH_PROVIDER=gliner`, et le banc mesure. Mais
entre « j'installe la bibliothèque » et « je lance un run sur cent soixante
pages », il manque la boucle de trente secondes — celle où l'on regarde une
seule page, où l'on voit quel libellé remonte du bruit, et où l'on récrit
`spans.LABELS` avant de mesurer quoi que ce soit.

C'est ce que fait ce script. Il n'a rien à faire dans la suite de tests : il
charge un modèle de plusieurs centaines de mégaoctets, et la première
exécution le télécharge.

    pip install -e ".[gliner]"
    python -m tools.gliner_essai tests/fixtures/pages/spectacle-avec-json-ld.html
    python -m tools.gliner_essai https://exemple.fr/spectacle

Il affiche trois choses, et la troisième est la seule qui compte : les spans
bruts avec leur score, la fiche assemblée, puis **l'audit d'ancrage**, celui-là
même que le banc appliquera. Les champs que la brique ne prétend pas remplir y
sont annoncés, pour qu'un aspect vide ne se lise pas comme un échec.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sortiesbot.ancrage import audit_fiche, fiche_payload  # noqa: E402
from sortiesbot.config import Config  # noqa: E402
from sortiesbot.evaluation import read_from_html  # noqa: E402
from sortiesbot.harvest import Fetcher, FetchError  # noqa: E402
from sortiesbot.journal import RunLog  # noqa: E402
from sortiesbot.providers.base import ProviderError  # noqa: E402
from sortiesbot.providers.gliner_provider import MODELE_DEFAUT, GlinerProvider  # noqa: E402
from sortiesbot.spans import LABELS, SEUIL_DEFAUT, unfilled_fields  # noqa: E402


def _page(source: str) -> tuple[str, str]:
    """Le HTML et l'URL, que la source soit un fichier gelé ou une adresse.

    Le fichier gelé est le cas normal : c'est celui du corpus, donc celui que
    le banc rejouera. L'URL est là pour l'essai à chaud sur une page qu'on
    vient de voir passer.
    """
    if source.startswith(("http://", "https://")):
        try:
            return Fetcher().get_html(source), source
        except FetchError as err:
            print(f"Téléchargement impossible : {err}", file=sys.stderr)
            return "", source
    chemin = Path(source)
    return chemin.read_text(encoding="utf-8", errors="replace"), chemin.resolve().as_uri()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", help="un fichier HTML gelé, ou une URL")
    parser.add_argument("--modele", default=MODELE_DEFAUT, help=f"défaut : {MODELE_DEFAUT}")
    parser.add_argument("--seuil", type=float, default=SEUIL_DEFAUT)
    parser.add_argument("--spans", action="store_true", help="afficher les spans bruts")
    args = parser.parse_args(argv)

    html, url = _page(args.source)
    if not html:
        print(f"Rien à lire depuis « {args.source} ».", file=sys.stderr)
        return 2

    # L'étage 5 d'abord : le texte que l'étiqueteur reçoit doit être celui que
    # le banc lui donnera, sinon ce qu'on regarde ici ne dit rien de ce qu'on
    # mesurera là-bas.
    lecture = read_from_html(html, url)
    texte = lecture.get("text", "")
    print(f"Page  : {url}")
    print(f"Texte : {len(texte)} caractères (étage 5)")
    print(f"Modèle: {args.modele} · seuil {args.seuil}\n")

    provider = GlinerProvider(gliner_model=args.modele, seuil=args.seuil)
    try:
        tagger = provider._charger()
    except ProviderError as err:
        # Le cas de loin le plus fréquent au premier lancement : la
        # bibliothèque n'est pas là. Une trace de vingt lignes cacherait la
        # seule chose à lire, qui est la commande à taper.
        print(str(err), file=sys.stderr)
        return 2

    if args.spans:
        bruts = tagger.predict_entities(texte[:6000], list(LABELS), threshold=args.seuil)
        print("── Spans bruts ──")
        for brut in sorted(bruts, key=lambda b: -float(b.get("score", 0))):
            champ = LABELS.get(str(brut.get("label", "")), "?")
            print(f"  {float(brut.get('score', 0)):.2f}  {champ:<20} {brut.get('text', '')!r}")
        print()

    fiches = provider.extract(url, texte, Config(name="essai", theme="essai"), [], RunLog(None, verbose=False))
    event = fiches[0]

    print("── Fiche ──")
    print(json.dumps(fiche_payload(event), ensure_ascii=False, indent=2, sort_keys=True))

    print("\n── Ancrage (les instruments du banc) ──")
    hors_portee = set(unfilled_fields())
    for aspect in audit_fiche(event, texte, list(lecture.get("dates", []))):
        drapeaux = ", ".join(aspect["flags"]) or "—"
        note = ""
        if not aspect["filled"] and aspect["key"] in {"description", "cadre", "categorie"}:
            note = "  (hors portée d'un étiqueteur)"
        print(f"  {aspect['label']:<22} {aspect['value'] or '∅':<40} {drapeaux}{note}")

    print(f"\nChamps qu'un étiqueteur ne rend pas : {', '.join(sorted(hors_portee))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
