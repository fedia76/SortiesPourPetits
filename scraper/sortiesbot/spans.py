"""Des spans à une fiche : ce qu'un étiqueteur rend, et ce qu'il ne rendra jamais.

Un étiqueteur de spans ne sait faire qu'une chose : désigner des **morceaux du
texte**. Il ne rédige pas, ne normalise pas, ne juge pas. Tout ce qui sépare
« le morceau `3 août` se trouve ici » de `date_start: "2026-08-03"` est du
Python, et c'est ce module.

Le partage est volontairement net, parce qu'il est la raison d'être de toute
l'approche : le modèle trouve, le Python normalise. Un modèle qui écrirait
`2026-08-03` pourrait écrire `2026-08-30` ; celui-ci ne le peut pas, il ne
sait que pointer. En échange, il ne sait pas non plus compter les jours — d'où
tout ce qui suit.

## Ce que ce module ne remplit pas, et pourquoi il ne triche pas

Quatre champs de la fiche ne sont **pas** des morceaux de page, et aucun
étiquetage ne les produira :

* `relevant` et `several` — un jugement sur la page entière ;
* `setting` — la page ne l'écrit presque jamais, elle dit « au parc de la
  Villette » et c'est le lecteur qui conclut. `ancrage.audit_fiche` le note
  déjà : instrument « aucun » ;
* `category` — un choix dans un référentiel, pas une citation ;
* `description` — une rédaction.

Ils restent **vides**, et le banc comptera `MANQUE`. C'est la mesure juste. Les
remplir par une heuristique — `setting` déduit du mot « salle », `description`
recopiée du premier paragraphe — fabriquerait un chiffre vert sans rien
apprendre à personne : `evalMetrics.pareil` rend `true` sans condition sur le
genre `prose`, et `ancrage._overlap` est trivialement satisfait par une
recopie. Un aspect qu'on ne sait pas mesurer ne doit pas être rempli au
hasard ; il doit rester visiblement vide.

## L'année absente

Une page française écrit « du 3 au 12 août » sans l'année, et c'est le cas le
plus fréquent. La règle retenue : l'année courante, sauf si la date tombe plus
de `_PASSE_TOLERE` jours avant aujourd'hui — auquel cas c'est l'année
suivante. Une affiche parle de ce qui vient, pas de ce qui est fini ; et la
tolérance évite de projeter en 2027 un festival commencé la semaine dernière.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from .models import ExtractedEvent
from .schedule import WEEKDAYS
from .text import flatten

#: Les libellés soumis à l'étiqueteur, et le champ de la fiche qu'ils nourrissent.
#:
#: Ce sont des **mots français**, pas des identifiants : un modèle zero-shot
#: apparie le texte du libellé à celui de la page, si bien que « tarif » et
#: « prix d'entrée » ne remontent pas les mêmes spans. Ce dictionnaire est donc
#: un réglage à part entière, et le premier à toucher quand un champ se rate —
#: bien avant de changer de modèle.
#:
#: **Courts, et c'est délibéré.** Ils l'étaient d'abord descriptifs — « adresse
#: postale (numéro et rue) », « jour de la semaine où l'événement a lieu » —,
#: ce qui coûtait deux fois : GLiNER a été entraîné sur des **noms de types
#: d'entités**, pas sur des phrases, et ses libellés partagent la fenêtre du
#: modèle avec le texte de la page. Une parenthèse dans un libellé, ce sont
#: des jetons pris à la page.
#:
#: `tools/gliner_essai.py --libelles` permet d'en essayer d'autres sans
#: toucher au code : c'est le premier réglage à mesurer, pas à deviner.
LABELS: dict[str, str] = {
    "titre de l'événement": "title",
    "lieu": "venue_name",
    "adresse": "venue_address",
    "ville": "venue_city",
    "code postal": "venue_postal_code",
    "tarif": "price",
    "âge minimum": "age_min",
    "âge maximum": "age_max",
    "date": "dates",
    "heure": "times",
    "jour de la semaine": "weekdays",
}

#: En deçà, on ne retient pas le span. GLiNER rend un score par span ; le
#: laisser passer sans seuil remplit la fiche de bruit, et un champ faux coûte
#: plus cher qu'un champ vide — c'est toute la logique de la modération.
SEUIL_DEFAUT = 0.5

#: Les seuils qui s'écartent du défaut, et pourquoi. Mesuré sur 140 pages.
#:
#: Un seuil unique suppose que se tromper coûte pareil partout. C'est faux :
#: un lieu faux se voit et se corrige en modération, un **tarif** faux part en
#: ligne et trompe un parent. Et les aspects ne ratent pas de la même façon —
#: le banc l'a montré aspect par aspect :
#:
#: * `times` rendait 29 valeurs que le corpus ne porte pas (des heures, une
#:   page en affiche partout : horaires d'ouverture, dernière séance, horaires
#:   de la billetterie). On monte la barre ;
#: * `weekdays` en inventait 15, pour la même raison ;
#: * `age` en manquait 73 sur 140 — il est trop timide, on la baisse ;
#: * `price` se trompait 105 fois sur 140. Monter le seuil ne rend pas un
#:   tarif juste, mais un tarif absent vaut mieux qu'un tarif faux : la
#:   modération complète un vide, elle ne repère pas une erreur plausible.
SEUILS: dict[str, float] = {
    # `age` manquait 73 valeurs sur 140 : trop timide. Baissé, et le run
    # suivant l'a confirmé — 33 justes devenus 49.
    "age_min": 0.35,
    "age_max": 0.35,
    # `weekdays` en inventait 15. Monté d'un cran, sans effet mesurable :
    # gardé faute de mieux, mais ce n'est pas un réglage éprouvé.
    "weekdays": 0.55,
}

#: Ce que deux seuils devinés ont coûté, et pourquoi ils ne sont plus là.
#:
#: `price` et `times` avaient été montés à 0,6 sur un raisonnement qui se
#: tenait — un tarif faux part en ligne, une page affiche des heures partout.
#: Le banc a dit non : le tarif est passé de 35 justes à 29, les horaires de
#: 50 à 43. Monter une barre n'améliore pas un choix, ça retire des candidats,
#: et retirer le mauvais candidat ne laisse pas le bon — ça laisse le suivant.
#:
#: La leçon vaut plus que le réglage : sur cette brique, **un seuil ne se
#: raisonne pas, il se mesure**. Un aspect n'a le sien que quand un run l'a
#: confirmé.

#: En deçà de quoi on ne demande même pas au modèle de répondre. C'est le seuil
#: passé à l'étiqueteur ; les seuils par champ se posent ensuite, dessus.
SEUIL_PLANCHER = min([SEUIL_DEFAUT, *SEUILS.values()])


def seuil_de(champ: str, defaut: float = SEUIL_DEFAUT) -> float:
    """Le seuil de ce champ. Le défaut vaut pour tous ceux qui n'en ont pas."""
    return SEUILS.get(champ, defaut)

#: Au-delà de cette ancienneté, une date sans année est tenue pour l'an prochain.
_PASSE_TOLERE = 45

_MOIS: dict[str, int] = {
    "janvier": 1, "janv": 1, "fevrier": 2, "fev": 2, "mars": 3, "avril": 4,
    "avr": 4, "mai": 5, "juin": 6, "juillet": 7, "juil": 7, "aout": 8,
    "septembre": 9, "sept": 9, "octobre": 10, "oct": 10, "novembre": 11,
    "nov": 11, "decembre": 12, "dec": 12,
}

_MOIS_ALT = "|".join(sorted(_MOIS, key=len, reverse=True))

#: « du 3 au 12 août 2026 », « du 3 juillet au 12 août ». Le premier jour peut
#: n'avoir pas de mois : il emprunte alors celui du second.
_PLAGE = re.compile(
    rf"\bdu\s+(\d{{1,2}})(?:er)?\s*(?:({_MOIS_ALT})\.?)?\s+au\s+"
    rf"(\d{{1,2}})(?:er)?\s+({_MOIS_ALT})\.?\s*(\d{{4}})?",
)
_EN_LETTRES = re.compile(rf"\b(\d{{1,2}})(?:er)?\s+({_MOIS_ALT})\.?\s*(\d{{4}})?")
_NUMERIQUE = re.compile(r"\b(\d{1,2})[/.](\d{1,2})(?:[/.](\d{2,4}))?")
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_HEURE = re.compile(r"\b(\d{1,2})\s*[h:]\s*(\d{2})?")
_GRATUIT = re.compile(r"\bgratui|entree libre|acces libre|offert|sans reservation payante")


@dataclass(frozen=True)
class Span:
    """Un morceau de page désigné par l'étiqueteur.

    Volontairement indépendant de la forme de dictionnaire que rend GLiNER :
    la couche pure ne doit pas connaître la bibliothèque, sans quoi elle ne se
    teste qu'en l'installant — donc en installant torch.
    """

    label: str
    text: str
    start: int = 0
    end: int = 0
    score: float = 1.0


def _annee(jour: int, mois: int, annee: int | None, today: date) -> date | None:
    """La date complète, l'année devinée quand la page ne la donne pas."""
    if annee is not None:
        if annee < 100:
            annee += 2000
        try:
            return date(annee, mois, jour)
        except ValueError:
            return None
    for candidate in (today.year, today.year + 1):
        try:
            essai = date(candidate, mois, jour)
        except ValueError:
            return None
        if essai >= today - timedelta(days=_PASSE_TOLERE):
            return essai
    return None


def parse_dates(value: str, today: date | None = None) -> list[date]:
    """Les dates lues dans un morceau de texte français, dans l'ordre.

    Quatre écritures, parce qu'une page d'événement les emploie toutes : la
    plage (« du 3 au 12 août »), les lettres (« 3 août 2026 »), le numérique
    (« 03/08/2026 ») et l'ISO. La plage passe en premier et **consomme** son
    texte : sans ça, « du 3 au 12 août » ne rendrait que le 12, le « 3 » étant
    orphelin de mois.
    """
    today = today or date.today()
    plat = flatten(value)
    trouvees: list[date] = []

    def garde(jour: int, mois: int, annee: int | None) -> None:
        if not 1 <= mois <= 12:
            return
        jourdate = _annee(jour, mois, annee, today)
        if jourdate and jourdate not in trouvees:
            trouvees.append(jourdate)

    for m in _PLAGE.finditer(plat):
        fin_mois = _MOIS[m.group(4)]
        annee = int(m.group(5)) if m.group(5) else None
        debut_mois = _MOIS[m.group(2)] if m.group(2) else fin_mois
        garde(int(m.group(1)), debut_mois, annee)
        garde(int(m.group(3)), fin_mois, annee)
    reste = _PLAGE.sub(" ", plat)

    for m in _ISO.finditer(reste):
        garde(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    reste = _ISO.sub(" ", reste)

    for m in _EN_LETTRES.finditer(reste):
        garde(int(m.group(1)), _MOIS[m.group(2)], int(m.group(3)) if m.group(3) else None)
    reste = _EN_LETTRES.sub(" ", reste)

    for m in _NUMERIQUE.finditer(reste):
        garde(int(m.group(1)), int(m.group(2)), int(m.group(3)) if m.group(3) else None)

    return sorted(trouvees)


def parse_heure(value: str) -> str:
    """« 14h30 », « 14 h », « 14:30 » → `14:30`. Vide si rien de lisible."""
    m = _HEURE.search(flatten(value))
    if not m:
        return ""
    heure = int(m.group(1))
    minute = int(m.group(2) or 0)
    if not (0 <= heure <= 23 and 0 <= minute <= 59):
        return ""
    return f"{heure:02d}:{minute:02d}"


def parse_tarif(value: str) -> tuple[bool, float | None]:
    """Rend `(gratuit, prix)`.

    La gratuité se dit en toutes lettres et jamais par un zéro : c'est pourquoi
    elle se cherche par mots plutôt que par nombre. Et un nombre nu ne suffit
    pas — « 8 » traîne dans n'importe quel texte —, il lui faut le voisinage
    d'une monnaie, exactement comme `ancrage._price_in` l'exige pour juger.
    """
    plat = flatten(value)
    if _GRATUIT.search(plat):
        return True, None
    m = re.search(r"(\d{1,4})(?:[.,](\d{1,2}))?\s*(?:€|eur\b|euros?\b)", plat)
    if not m:
        return False, None
    montant = float(f"{m.group(1)}.{(m.group(2) or '0').ljust(2, '0')}")
    return False, montant


def parse_age(value: str) -> int | None:
    """L'âge lu dans un morceau, en années. Les mois sont ramenés à 0 an.

    « dès 18 mois » vaut 1 an et demi : le site ne stocke que des années, et
    arrondir vers le bas est le seul sens qui ne ferme la sortie à personne.
    """
    plat = flatten(value)
    m = re.search(r"\b(\d{1,2})\s*mois\b", plat)
    if m:
        return int(m.group(1)) // 12
    m = re.search(r"\b(\d{1,2})\b", plat)
    return int(m.group(1)) if m else None


def parse_jours(value: str) -> list[str]:
    """Les jours de la semaine nommés dans un morceau, dans l'ordre de la semaine."""
    plat = flatten(value)
    return [jour for jour in WEEKDAYS if jour in plat]


#: Ce qui suit un code postal dans une adresse : le code, puis la ville.
_DEPUIS_CODE_POSTAL = re.compile(r"[,\s]*\b\d{5}\b.*$")


def _rue_seule(adresse: str) -> str:
    """Le numéro et la rue, sans le code postal ni la ville qui suivraient.

    C'est le contrat du champ — le prompt de production le dit déjà au modèle —
    et le corpus est étiqueté ainsi. Un span qui ramène « 14 rue des Écoles,
    94000 Créteil » n'est pas faux, il est trop long ; le comparer tel quel
    comptait « faux » une adresse correctement lue.
    """
    return _DEPUIS_CODE_POSTAL.sub("", adresse).strip(" ,;-")


def _jour_iso(value: Any) -> str:
    """Une date `AAAA-MM-JJ` qui existe vraiment, ou rien.

    Ce qui vient d'un JSON-LD vient d'un générateur tiers : on vérifie plutôt
    que de faire confiance, sans quoi une fiche partirait avec un 30 février.
    """
    text = str(value or "").strip()[:10]
    try:
        date.fromisoformat(text)
    except ValueError:
        return ""
    return text


def _meilleur(spans: list[Span]) -> str:
    """Le texte du span le mieux noté, ou vide."""
    return max(spans, key=lambda s: s.score).text.strip() if spans else ""


def to_event(
    spans: list[Span],
    *,
    today: date | None = None,
    seuil: float = SEUIL_DEFAUT,
    hints: dict[str, Any] | None = None,
) -> ExtractedEvent:
    """La fiche que ces spans permettent de remplir. Rien de plus.

    Les champs qu'aucun span ne peut porter restent vides — voir l'en-tête du
    module. `relevant` suit la seule chose qu'on sache honnêtement en dire :
    a-t-on trouvé un titre. Ce n'est pas un jugement de pertinence, et
    `skip_reason` le dit en clair plutôt que de laisser croire à un verdict.

    ## `hints` l'emporte, et ce n'est pas un réglage de confort

    Ce que la page **déclare d'elle-même** — son `h1`, son `schema.org/Event` —
    n'est pas une opinion de plus à arbitrer : c'est la valeur exacte, écrite
    par celui qui organise la sortie. Un span bien noté ne vaut pas contre
    elle. Le modèle ne sert donc qu'à ce que la page ne déclare pas, ce qui est
    le cas le plus fréquent — mais plus le seul.
    """
    today = today or date.today()
    hints = dict(hints or {})
    par_champ: dict[str, list[Span]] = {}
    for span in spans:
        champ = LABELS.get(span.label)
        # Le seuil est celui du champ : la même note ne vaut pas la même
        # confiance sur un lieu et sur un tarif.
        if champ and span.text.strip() and span.score >= seuil_de(champ, seuil):
            par_champ.setdefault(champ, []).append(span)

    def declare(champ: str, sinon: str = "") -> str:
        valeur = hints.get(champ)
        return str(valeur).strip() if isinstance(valeur, str) and valeur.strip() else sinon

    title = declare("title", _meilleur(par_champ.get("title", [])))

    # `None` tant qu'on n'a rien lu : ne pas affirmer « ce n'est pas gratuit »
    # sur une page dont on n'a pas su lire le tarif. Le banc comptait ce
    # silence comme une erreur, et 111 « tarifs faux » cachaient surtout des
    # tarifs jamais trouvés.
    gratuit: bool | None = None
    prix: float | None = None
    if "free" in hints or "price" in hints:
        gratuit = bool(hints.get("free", False))
        brut = hints.get("price")
        prix = float(brut) if isinstance(brut, (int, float)) else None
    else:
        for span in sorted(par_champ.get("price", []), key=lambda s: -s.score):
            lu_gratuit, lu_prix = parse_tarif(span.text)
            if lu_gratuit or lu_prix is not None:
                gratuit, prix = lu_gratuit, lu_prix
                break

    jours: list[str] = []
    for span in par_champ.get("weekdays", []):
        for jour in parse_jours(span.text):
            if jour not in jours:
                jours.append(jour)

    # Toutes les dates de tous les spans : les bornes sont le minimum et le
    # maximum, et la liste complète part dans `dates`. C'est `schedule.resolve`
    # qui décidera ensuite si elle vaut mieux que la plage — ce module ne
    # tranche pas un calendrier, il rend ce qu'il a lu.
    dates: list[date] = []
    for span in par_champ.get("dates", []):
        for jour in parse_dates(span.text, today):
            if jour not in dates:
                dates.append(jour)
    dates.sort()

    # Les bornes déclarées par la page l'emportent sur ce que la prose a
    # donné, pour la même raison que le titre : ce sont celles de
    # l'organisateur. Les dates relevées dans le texte restent le calendrier —
    # `schedule.resolve` en fera ce qu'il doit.
    borne_debut = _jour_iso(hints.get("date_start"))
    borne_fin = _jour_iso(hints.get("date_end"))
    if borne_debut:
        debut_iso, fin_iso = borne_debut, borne_fin or ""
    else:
        debut_iso = dates[0].isoformat() if dates else ""
        fin_iso = dates[-1].isoformat() if len(dates) > 1 else ""
    if fin_iso and debut_iso and fin_iso < debut_iso:
        fin_iso = ""
    # Une sortie d'un seul jour **a** une date de fin, et c'est le même jour.
    #
    # Le site la stocke ainsi (`payload._clean_dates` : `end = end or start`),
    # donc le corpus la porte ainsi, et rendre une fin vide comptait faux
    # toute sortie d'un jour. C'est `ancrage._date_range` qui avait raison
    # depuis le début : `(start, end or start)`.
    if debut_iso and not fin_iso:
        fin_iso = debut_iso

    horaires = sorted({h for s in par_champ.get("times", []) if (h := parse_heure(s.text))})

    code_postal = declare("venue_postal_code")
    if not code_postal:
        for span in sorted(par_champ.get("venue_postal_code", []), key=lambda s: -s.score):
            m = re.search(r"\b(\d{5})\b", span.text)
            if m:
                code_postal = m.group(1)
                break
    m = re.search(r"\b(\d{5})\b", code_postal)
    code_postal = m.group(1) if m else ""

    return ExtractedEvent(
        relevant=bool(title),
        skip_reason="" if title else "aucun titre repéré dans la page",
        # Un étiqueteur ne sait pas qu'une page porte plusieurs sorties : il
        # étiquetterait les vingt titres d'un programme sans s'en émouvoir.
        several=False,
        title=title,
        description="",
        free=gratuit,
        price=prix,
        age_min=parse_age(_meilleur(par_champ.get("age_min", []))) if par_champ.get("age_min") else None,
        age_max=parse_age(_meilleur(par_champ.get("age_max", []))) if par_champ.get("age_max") else None,
        # Inconnu tant qu'on n'a **rien** — mais connaître une plage, c'est
        # savoir que la sortie n'est pas permanente.
        #
        # Le dire inconnu dans tous les cas a coûté cher, et la leçon vaut
        # d'être gardée : le corpus porte toujours un booléen (`isPermanent`
        # est une colonne du site), et la comparaison d'un aspect exige que
        # **tous** ses champs concordent. Un `null` en face d'un `false`
        # suffisait donc à faire échouer l'aspect entier, dates justes
        # comprises — vingt fiches justes devenues zéro, d'un run à l'autre.
        permanent=False if debut_iso else None,
        date_start=debut_iso,
        date_end=fin_iso,
        weekdays=tuple(jours),
        # Une seule date n'est pas une liste de représentations : c'est la
        # date de la sortie, déjà portée par `date_start`. La répéter ici
        # ferait croire à un calendrier relevé.
        dates=tuple(d.isoformat() for d in dates) if len(dates) > 1 else (),
        open_time=horaires[0] if horaires else "",
        close_time=horaires[-1] if len(horaires) > 1 else "",
        setting="",
        category="",
        venue_name=declare("venue_name", _meilleur(par_champ.get("venue_name", []))),
        venue_address=_rue_seule(
            declare("venue_address", _meilleur(par_champ.get("venue_address", [])))
        ),
        venue_city=declare("venue_city", _meilleur(par_champ.get("venue_city", []))),
        venue_postal_code=code_postal,
        photo_url="",
    )


def unfilled_fields() -> tuple[str, ...]:
    """Les champs qu'aucun étiquetage ne remplit, pour que la console le dise.

    Rendu à l'appelant plutôt que commenté quelque part : un banc qui compte
    `MANQUE` sur `setting` doit pouvoir distinguer « le modèle a raté » de
    « cette brique ne prétend pas le rendre ».
    """
    return ("description", "setting", "category", "several", "permanent", "photo_url")


__all__ = [
    "LABELS",
    "SEUIL_DEFAUT",
    "Span",
    "parse_age",
    "parse_dates",
    "parse_heure",
    "parse_jours",
    "parse_tarif",
    "to_event",
    "unfilled_fields",
]
