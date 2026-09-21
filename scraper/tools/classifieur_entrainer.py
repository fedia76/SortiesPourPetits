"""Entraîner le classifieur de catégories sur le corpus étiqueté, et le juger.

    pip install -e ".[classifieur]"
    python -m tools.classifieur_entrainer            # mesure et enregistre
    python -m tools.classifieur_entrainer --a-blanc  # mesure seulement
    python -m tools.classifieur_entrainer --grammes car

## Ce que ce script cherche à empêcher

Qu'on se réjouisse d'un score qui ne veut rien dire. Il y a deux façons
classiques de s'auto-féliciter en classification de texte, et il les mesure
toutes les deux plutôt que de les éviter en silence :

1. **noter le modèle sur ce qu'il a appris.** Un modèle interrogé sur ses
   propres exemples d'entraînement rend un score magnifique et sans valeur.
   Tout ce qui est rapporté ici est donc **hors échantillon** : chaque page
   est prédite par un modèle qui ne l'avait pas vue.

2. **découper au hasard un corpus qui vient de dix sites.** Les pages d'un
   même site partagent leur gabarit, leur pied de page, leur vocabulaire. Un
   découpage aveugle en met des deux côtés, et le modèle obtient un beau score
   en apprenant à reconnaître le *site* plutôt que la sortie — sur un
   onzième site, il s'effondre. Le script rapporte les deux découpages, au
   hasard et **par domaine**, et l'écart entre eux est le diagnostic.

Le seuil de confiance est mesuré de la même façon, sur les probabilités hors
échantillon : c'est la leçon des seuils choisis à l'œil, qui avaient coûté
treize aspects justes.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sortiesbot.api import SppApi  # noqa: E402
from sortiesbot.classifieur import (  # noqa: E402
    CHAMP,
    MINIMUM_PAR_CLASSE,
    ClassifieurIndisponible,
    Exemple,
    chemin_du_modele,
    domaine,
    entrainer,
    probas_hors_echantillon,
    retenir,
    seuil_mesure,
    traits,
)
from sortiesbot.config import Environment, load_dotenv  # noqa: E402
from sortiesbot.evaluation import read_from_html  # noqa: E402
from sortiesbot.harvest import Fetcher, FetchError  # noqa: E402

#: Par tranche : cent soixante pages gelées font des dizaines de mégaoctets.
TRANCHE = 10


class _SansReseau(Fetcher):
    """L'étage 5 rejoué **hors ligne**, sans échange de langue.

    `read_from_html` peut aller chercher une version française déclarée par la
    page. C'est juste en production ; ici ça ferait dépendre un jeu
    d'entraînement de la disponibilité de sites tiers, et deux entraînements
    lancés à un mois d'intervalle ne porteraient plus sur le même corpus.
    """

    def get_html(self, url: str, *args, **kwargs) -> str:
        raise FetchError(f"entraînement hors ligne : « {url} » non sollicitée")


def _recolter(client: SppApi, limite: int) -> list[tuple[str, dict, str]]:
    """Le corpus étiqueté, page par page : (url, étiquette, texte lu)."""
    fetcher = _SansReseau()
    recolte: list[tuple[str, dict, str]] = []
    curseur = 0
    while len(recolte) < limite:
        items, curseur = client.labelled_sorties(after=curseur, limit=TRANCHE)
        if not items:
            break
        for item in items:
            url = str(item.get("url") or "")
            html = str(item.get("html") or "")
            if not html:
                continue
            brut = item.get("expected")
            etiquette = json.loads(brut) if isinstance(brut, str) else dict(brut or {})
            lecture = read_from_html(html, url, fetcher=fetcher)
            recolte.append((url, etiquette, lecture))
            print(f"  {len(recolte):>4}  {url[:80]}", flush=True)
            if len(recolte) >= limite:
                break
        if not curseur:
            break
    return recolte


def _exemples(recolte: list[tuple[str, dict, str]]) -> tuple[list[Exemple], int]:
    """Les pages utilisables, et le nombre de celles qu'on a dû écarter.

    Une page dont la catégorie n'est pas étiquetée n'apprend rien : la clé
    absente veut dire « personne n'a regardé », pas « aucune catégorie ».
    """
    exemples: list[Exemple] = []
    ecartes = 0
    for url, etiquette, lecture in recolte:
        classe = str(etiquette.get(CHAMP) or "").strip()
        if not classe:
            ecartes += 1
            continue
        titre = str((lecture.get("facts") or {}).get("title") or "")
        exemples.append(
            Exemple(
                texte=traits(titre, str(lecture.get("text") or "")),
                etiquette=classe,
                groupe=domaine(url),
            )
        )
    return exemples, ecartes


def _bilan(predites: list[str], verites: list[str]) -> float:
    return sum(1 for p, v in zip(predites, verites) if p == v) / len(verites) if verites else 0.0


def _par_classe(predites: list[str], verites: list[str]) -> None:
    """Le tableau qui dit *où* ça casse, et non pas seulement combien.

    Une exactitude globale cache toujours la même chose : une classe majoritaire
    bien vue, et trois classes rares jamais proposées.
    """
    classes = sorted(set(verites) | set(predites))
    print(f"  {'classe':<28} {'exemples':>8} {'justes':>7} {'rappel':>7} {'proposée':>9}")
    for classe in classes:
        vrais = [i for i, v in enumerate(verites) if v == classe]
        justes = sum(1 for i in vrais if predites[i] == classe)
        proposee = sum(1 for p in predites if p == classe)
        rappel = justes / len(vrais) if vrais else 0.0
        print(
            f"  {classe[:28]:<28} {len(vrais):>8} {justes:>7} {rappel:>6.0%} {proposee:>9}"
        )


def _confusions(predites: list[str], verites: list[str], combien: int = 6) -> None:
    paires = Counter(
        (v, p) for v, p in zip(verites, predites) if v != p
    )
    if not paires:
        return
    print("\n── Les confusions les plus fréquentes ──")
    for (vrai, predit), n in paires.most_common(combien):
        print(f"  {n:>3} ×  {vrai[:24]:<24} pris pour  {predit[:24]}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limite", type=int, default=10000, help="plafonner le corpus lu")
    parser.add_argument(
        "--minimum",
        type=int,
        default=MINIMUM_PAR_CLASSE,
        help=f"exemples requis pour garder une classe (défaut : {MINIMUM_PAR_CLASSE}, plancher : 2)",
    )
    parser.add_argument("--grammes", choices=("mot", "car"), default="mot")
    parser.add_argument("--sortie", help=f"où écrire le modèle (défaut : {chemin_du_modele()})")
    parser.add_argument(
        "--a-blanc", action="store_true", help="mesurer sans rien enregistrer"
    )
    args = parser.parse_args(argv)

    load_dotenv(ROOT / ".env")
    env = Environment.from_env()
    client = SppApi(env.api_url, env.api_key)

    print("── Le corpus étiqueté ──")
    try:
        recolte = _recolter(client, args.limite)
    except Exception as err:  # noqa: BLE001 — l'API du site, et son message
        print(f"Corpus illisible : {err}", file=sys.stderr)
        return 2

    exemples, ecartes = _exemples(recolte)
    if not exemples:
        print("Aucune page n'a de catégorie étiquetée.", file=sys.stderr)
        return 2

    comptes = Counter(e.etiquette for e in exemples)
    sites = Counter(e.groupe for e in exemples)
    print(f"\n  {len(exemples)} page(s) utilisable(s), {ecartes} sans catégorie étiquetée")
    print(f"  {len(comptes)} classe(s), {len(sites)} site(s)")
    for classe, n in comptes.most_common():
        print(f"    {classe[:34]:<34} {n:>4}")
    # ── les classes trop rares, mises de côté et non pas subies
    #
    # Une classe vue une ou deux fois ne s'apprend pas : le modèle retient la
    # page, pas la catégorie. L'écarter n'est pas un aveu de faiblesse, c'est
    # le même arbitrage que le seuil de confiance — ses pages valent mieux
    # manquées que fausses — appliqué au référentiel.
    minimum = max(2, int(args.minimum))
    exemples, ecartees = retenir(exemples, minimum)
    if ecartees:
        perdues = sum(ecartees.values())
        print(f"\n  Mises de côté (moins de {minimum} exemples) — {perdues} page(s) :")
        for classe, n in sorted(ecartees.items(), key=lambda kv: -kv[1]):
            print(f"    {classe[:34]:<34} {n:>4}")
        print(
            "    Le modèle ne les proposera pas, et ces pages compteront\n"
            "    « manqué » sur le banc. Elles reviendront d'elles-mêmes au\n"
            "    prochain entraînement dès qu'elles seront assez nombreuses."
        )
    if not exemples:
        print(
            f"\nAucune classe n'atteint {minimum} exemples : rien à apprendre.",
            file=sys.stderr,
        )
        return 2

    # ── les deux découpages, et leur écart
    print("\n── Hors échantillon ──")
    try:
        p_groupe, s_groupe, verites = probas_hors_echantillon(
            exemples, grammes=args.grammes, groupe=True
        )
        p_hasard, _, _ = probas_hors_echantillon(exemples, grammes=args.grammes, groupe=False)
    except ClassifieurIndisponible as err:
        print(str(err), file=sys.stderr)
        return 2

    par_site = _bilan(p_groupe, verites)
    au_hasard = _bilan(p_hasard, verites)
    print(f"  découpage au hasard    {au_hasard:>6.0%}   ← optimiste : fuite par le site")
    print(f"  découpage par domaine  {par_site:>6.0%}   ← ce qu'il fera sur un site inconnu")
    ecart = au_hasard - par_site
    if ecart > 0.10:
        print(
            f"\n  L'écart est de {ecart:.0%}. Le modèle apprend en partie à reconnaître\n"
            "  les sites du corpus plutôt que les sorties. C'est le chiffre par\n"
            "  domaine qu'il faut croire."
        )

    print()
    _par_classe(p_groupe, verites)
    _confusions(p_groupe, verites)

    # ── le seuil, mesuré et non choisi
    seuil, courbe = seuil_mesure(p_groupe, s_groupe, verites)
    print("\n── Le seuil de confiance, mesuré hors échantillon ──")
    print(f"  {'seuil':>6} {'répond':>8} {'justes':>7} {'précision':>10} {'couverture':>11}")
    for point in courbe:
        marque = "  ← retenu" if point["seuil"] == seuil else ""
        print(
            f"  {point['seuil']:>6.2f} {point['repond']:>8} {point['justes']:>7} "
            f"{point['precision']:>9.0%} {point['couverture']:>10.0%}{marque}"
        )
    print(
        "\n  Règle : le seuil le plus permissif dont la précision atteint 70 %.\n"
        "  Au-dessous, le modèle se tait — un manqué se corrige, un faux se\n"
        "  publie."
    )

    if args.a_blanc:
        print("\nÀ blanc : rien n'a été enregistré.")
        return 0

    modele = entrainer(exemples, seuil=seuil, grammes=args.grammes)
    chemin = Path(args.sortie) if args.sortie else chemin_du_modele()
    modele.enregistrer(chemin)
    print(f"\nModèle enregistré : {chemin}")
    print(f"  {len(exemples)} exemples · {len(modele.classes)} classes · seuil {seuil:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
