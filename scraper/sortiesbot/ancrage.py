"""L'étage 6 mesuré : ce qu'une fiche affirme se lit-il dans la page ?

## Pourquoi cet étage se mesure autrement que les deux précédents

Les étages 3 et 5 sont du Python : ils rendent toujours la même chose sur la
même page, et ce qu'on mesure est une **fonction**. L'étage 6 est un appel de
modèle : il rend une **fiche**, il coûte de l'argent, et il peut inventer.

D'où trois différences de méthode :

1. **Champ par champ, jamais fiche par fiche.** Une fiche « fausse » ne dit pas
   quel champ a lâché, donc ne dit pas quoi réparer. Douze aspects, chacun jugé
   séparément, disent « le tarif se rate une fois sur trois » — et c'est une
   ligne de prompt à réécrire.

2. **Trois instruments gratuits avant le premier clic.** L'ancrage (toute
   valeur doit se retrouver dans le texte), la cohérence interne (un âge
   minimum au-dessus du maximum), l'accord avec les dates JSON-LD relevées par
   l'étage 5. Aucun des trois ne demande d'étiquette humaine, et à eux trois
   ils désignent la plupart des fautes.

3. **Le corpus est le texte de l'étage 5, pas la page.** L'extraction est
   rejouée sur le texte exact que le banc de lecture a archivé. C'est ce qui
   fait qu'une mauvaise fiche accuse bien l'étage 6 : si le texte était amputé,
   c'est l'étage 5 qui est en cause, et le banc de lecture l'a déjà dit.

## Ce que les instruments ne peuvent pas faire

`setting` — intérieur ou extérieur — n'a **aucun** instrument gratuit. Une page
ne l'écrit presque jamais : elle dit « au parc de la Villette » ou « salle
Jean-Vilar », et c'est le lecteur qui conclut. C'est donc l'aspect qui coûtera
toujours une étiquette humaine, et il faut le savoir plutôt que d'imaginer une
heuristique qui donnerait l'illusion d'une mesure.
"""

from __future__ import annotations

import re
from typing import Any

from .models import ExtractedEvent
from .text import flatten

#: L'énuméré du cadre, en français. Le schéma impose l'anglais au modèle ; la
#: console parle la langue du site.
_SETTINGS = {"INDOOR": "intérieur", "OUTDOOR": "extérieur", "BOTH": "les deux"}

#: Les mois en toutes lettres, pour reconnaître « 3 août » dans une page quand
#: le modèle a rendu « 2026-08-03 ».
_MONTHS = (
    "janvier", "fevrier", "mars", "avril", "mai", "juin",
    "juillet", "aout", "septembre", "octobre", "novembre", "decembre",
)

#: Part des mots d'un titre qu'il faut retrouver dans la page pour le tenir pour
#: ancré. La moitié : un titre est souvent reformulé — un article retiré, une
#: majuscule changée — mais un titre dont la moitié des mots sont absents de la
#: page n'a pas été lu, il a été composé.
_OVERLAP_MIN = 0.5


#: L'ancrage compare ce qu'un modèle a écrit à ce qu'une page dit, et les deux
#: ne s'accordent jamais sur les accents ni sur les espaces insécables —
#: comparer à la lettre ferait crier à l'invention sur « Théâtre » contre
#: « theatre ». C'est exactement ce que `text.flatten` fait, et il le fait pour
#: tout le monde : cette fonction-ci était la cinquième de son espèce, et la
#: seule en `NFD`, donc la seule que « 8 € » avec une espace insécable étroite
#: prenait en défaut.
_flat = flatten


def _price_in(price: float, hay: str) -> bool:
    """Ce tarif se lit-il dans la page ?

    Un nombre nu ne prouve rien : « 8 » se trouve dans n'importe quel texte
    assez long. On exige donc le voisinage d'une monnaie — c'est ce qui fait la
    différence entre un tarif lu et un tarif plausible.
    """
    money = r"(?:€|eur\b|euros?\b)"
    if price == int(price):
        whole = int(price)
        return bool(
            re.search(rf"\b{whole}\s*(?:[.,]\s*0{{1,2}})?\s*{money}", hay)
            or re.search(rf"{money}\s*{whole}\b", hay)
            or re.search(rf"\b{whole}\s*(?:[.,]\s*0{{1,2}})?\s*(?:e\b)", hay)
        )
    whole, cents = f"{price:.2f}".split(".")
    return bool(re.search(rf"\b{whole}\s*[.,]\s*{cents}\b", hay))


def _age_in(age: int, hay: str) -> bool:
    """Cet âge se lit-il dans la page ?

    Même précaution que pour le tarif, avec deux tournures : « 3 ans », et
    « à partir de 3 » — les pages écrivent volontiers l'une ou l'autre.
    """
    return bool(
        re.search(rf"\b{age}\s*(?:ans?|mois)\b", hay)
        or re.search(
            rf"(?:des|a partir de|partir de|plus de|moins de|jusqu a|des l age de)"
            rf"\s*(?:l age de\s*)?{age}\b",
            hay,
        )
    )


def _time_in(hhmm: str, hay: str) -> bool:
    """Cet horaire se lit-il dans la page ? « 14:30 », « 14h30 », « 14 h 30 »."""
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", hhmm.strip())
    if not match:
        return False
    hour, minute = match.group(1).lstrip("0") or "0", match.group(2)
    if minute == "00":
        return bool(re.search(rf"\b{hour}\s*[h:]\s*(?:00)?\b", hay))
    return bool(re.search(rf"\b{hour}\s*[h:]\s*{minute}\b", hay))


def _date_in(iso: str, hay: str) -> bool:
    """Cette date se lit-elle dans la page, sous l'une de ses écritures ?

    Une page française écrit « 3 août », « 03/08/2026 » ou « 2026-08-03 ». Ne
    chercher que la forme ISO ferait déclarer inventée toute date correctement
    lue, ce qui est le contraire de ce qu'on veut mesurer.
    """
    match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", iso.strip()[:10])
    if not match:
        return False
    year, month, day = match.group(1), int(match.group(2)), int(match.group(3))
    if not 1 <= month <= 12:
        return False
    forms = [
        f"{year}-{month:02d}-{day:02d}",
        f"{day:02d}/{month:02d}/{year}",
        f"{day}/{month}/{year}",
        f"{day:02d}/{month:02d}",
        f"{day}/{month}",
        f"{day} {_MONTHS[month - 1]}",
        f"{day:02d} {_MONTHS[month - 1]}",
    ]
    # Le 1er du mois s'écrit « 1er août » et jamais « 1 août ».
    if day == 1:
        forms.append(f"1er {_MONTHS[month - 1]}")
    return any(form in hay for form in forms)


def _overlap(value: str, hay: str) -> float:
    """Part des mots significatifs de `value` qui se retrouvent dans la page.

    Les mots de moins de quatre lettres sont ignorés : « de », « la », « les »
    se trouvent partout et gonfleraient le score de n'importe quelle invention.
    Une valeur qui n'a aucun mot long est tenue pour ancrée — il n'y a rien à
    vérifier, et crier à l'invention sur « Noël » serait faux.
    """
    words = re.findall(r"[a-z0-9]{4,}", _flat(value))
    if not words:
        return 1.0
    return sum(1 for word in words if word in hay) / len(words)


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(word.capitalize() for word in rest)


def fiche_payload(event: ExtractedEvent) -> dict[str, Any]:
    """La fiche telle que la console la reçoit : les champs du modèle, en camelCase.

    Gardée entière, y compris les champs qu'aucun aspect ne juge : c'est la
    pièce à conviction, et une mesure dont on ne peut plus relire l'objet n'est
    pas vérifiable.
    """
    return {
        _camel(key): (list(value) if isinstance(value, tuple) else value)
        for key, value in vars(event).items()
    }


def resolved_days(event: ExtractedEvent, json_ld: list[str]) -> list[str]:
    """Les jours que le **pipeline** retiendrait de cette fiche.

    C'est ce qui se compare au calendrier d'une sortie publiée, et c'est tout
    l'objet de cette fonction : le site ne stocke pas des « mercredis », il
    stocke des dates. Sans cette conversion, le banc reprochait à l'étage 6 de
    rendre `weekdays: ["dimanche"]` là où la sortie approuvée portait six
    dimanches — une faute qui n'était pas la sienne, mais l'absence d'un calcul
    qui a lieu plus loin.

    `schedule.resolve` est la fonction de **production** : une relecture de ses
    règles ici comparerait deux implémentations plutôt qu'un rendu à une vérité.
    Liste vide des deux côtés vaut « tous les jours de la plage », ce qui est un
    accord.
    """
    from .schedule import resolve

    plan = resolve(event.date_start, event.date_end, event.weekdays, event.dates, json_ld)
    return list(plan.dates)


def _date_range(start: str, end: str) -> tuple[str, str]:
    """Les deux bornes réduites à leur jour, pour comparer sans se soucier des heures."""
    return start.strip()[:10], (end.strip()[:10] or start.strip()[:10])


def audit_fiche(
    event: ExtractedEvent,
    text: str,
    declared_dates: list[str] | tuple[str, ...] = (),
    categories: list[str] | tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    """Les douze aspects d'une fiche, chacun avec ce que les instruments en disent.

    Rend, pour chaque aspect : son libellé, la valeur rendue par le modèle en
    clair, si elle est renseignée, quel instrument l'a examinée, et les défauts
    relevés.

    **Ce ne sont pas des verdicts.** Comme les motifs de rejet de l'étage 3 et
    les signaux de l'étage 5, ce sont des libellés : le modèle a rendu ce qu'il
    a rendu, et c'est ce rendu qu'on mesure. Un drapeau dit à l'humain *où
    regarder d'abord* — et c'est beaucoup, parce que douze aspects sur trente
    fiches font trois cent soixante décisions dont l'écrasante majorité est
    « juste ».

    Trois instruments, aucun ne coûtant d'étiquette :

    * **ancrage** — la valeur se retrouve-t-elle dans le texte ? C'est le seul
      qui attrape une invention, et il l'attrape sans savoir ce qui est vrai ;
    * **cohérence** — la fiche se contredit-elle toute seule ? Un âge minimum
      au-dessus du maximum est faux sans qu'on ait lu la page ;
    * **accord** — les dates rendues rencontrent-elles celles que l'étage 5 a
      relevées en JSON-LD ? Deux lectures indépendantes de la même page qui se
      contredisent : l'une des deux se trompe, et il faut un humain pour dire
      laquelle.
    """
    hay = _flat(text)
    known = {_flat(c) for c in categories}
    out: list[dict[str, Any]] = []

    def add(
        key: str,
        label: str,
        value: str,
        filled: bool,
        instrument: str,
        flags: list[str],
    ) -> None:
        out.append(
            {
                "key": key,
                "label": label,
                "value": value,
                "filled": filled,
                "instrument": instrument,
                # Un champ vide n'a rien à ancrer : les drapeaux ne valent que
                # pour ce que le modèle a osé écrire.
                "flags": flags if filled else [],
            }
        )

    # ── 1. le verdict sur la page elle-même. Le plus lourd de conséquences :
    #    une page écartée à tort ne coûte rien et ne se voit nulle part.
    if not event.relevant:
        verdict = f"écartée — {event.skip_reason}" if event.skip_reason else "écartée, sans motif"
    elif event.several:
        verdict = "programme : plusieurs sorties, à relire d'un bloc"
    else:
        verdict = "une sortie"
    add(
        "verdict",
        "La page",
        verdict,
        True,
        "aucun",
        ["incoherent"] if not event.relevant and not event.skip_reason.strip() else [],
    )

    # ── 2. le titre
    add(
        "titre",
        "Le titre",
        event.title,
        bool(event.title),
        "ancrage",
        ["hors_texte"] if _overlap(event.title, hay) < _OVERLAP_MIN else [],
    )

    # ── 3. la description. Une reformulation, donc jugée sur le vocabulaire :
    #    une description dont la moitié des mots longs sont absents de la page
    #    n'a pas été tirée d'elle.
    add(
        "description",
        "La description",
        event.description,
        bool(event.description),
        "ancrage",
        ["hors_texte"] if _overlap(event.description, hay) < _OVERLAP_MIN else [],
    )

    # ── 4. le tarif. Deux colonnes pour un seul fait : les juger séparément
    #    compterait deux fois la même erreur.
    tarif_flags: list[str] = []
    if event.free and event.price:
        tarif_flags.append("incoherent")
    if event.price is not None and not _price_in(event.price, hay):
        tarif_flags.append("hors_texte")
    if event.free and not re.search(r"\bgratui|entree libre|acces libre|offert", hay):
        tarif_flags.append("hors_texte")
    if event.free:
        tarif = "gratuit"
    elif event.price is not None:
        tarif = f"{event.price:g} €"
    else:
        tarif = ""
    add("tarif", "Le tarif", tarif, bool(tarif), "ancrage + cohérence", sorted(set(tarif_flags)))

    # ── 5. l'âge
    age_flags: list[str] = []
    if event.age_min is not None and event.age_max is not None and event.age_min > event.age_max:
        age_flags.append("incoherent")
    if any(age is not None and not _age_in(age, hay) for age in (event.age_min, event.age_max)):
        age_flags.append("hors_texte")
    if event.age_min is not None and event.age_max is not None:
        age = f"{event.age_min} à {event.age_max} ans"
    elif event.age_min is not None:
        age = f"dès {event.age_min} ans"
    elif event.age_max is not None:
        age = f"jusqu'à {event.age_max} ans"
    else:
        age = ""
    add("age", "L'âge", age, bool(age), "ancrage + cohérence", sorted(set(age_flags)))

    # ── 6. les dates
    start, end = _date_range(event.date_start, event.date_end)
    dates_flags: list[str] = []
    if event.permanent and (start or end):
        dates_flags.append("incoherent")
    if start and end and end < start:
        dates_flags.append("incoherent")
    absentes = [d for d in (start, end) if d and not _date_in(d, hay)]
    # Une page qui n'annonce qu'une fin — « jusqu'au 23 octobre » — vaut au
    # prompt de mettre *aujourd'hui* en date de début. Cette date-là n'est donc
    # pas dans la page, et c'est réglementaire : ne pas l'excepter ferait crier
    # à l'invention sur le cas même que le prompt décrit noir sur blanc.
    regle_du_jusqu_au = absentes == [start] and bool(end) and end != start
    if absentes and not regle_du_jusqu_au:
        dates_flags.append("hors_texte")
    if declared_dates and start:
        jours = {d.strip()[:10] for d in declared_dates}
        if not any(start <= jour <= (end or start) for jour in jours):
            dates_flags.append("divergent")
    if event.permanent:
        plage = "toute l'année"
    elif start and end and end != start:
        plage = f"du {start} au {end}"
    elif start:
        plage = f"le {start}"
    else:
        plage = ""
    add(
        "dates",
        "Les dates",
        plage,
        bool(plage),
        "ancrage + cohérence + accord",
        sorted(set(dates_flags)),
    )

    # ── 7. les jours. Sans eux, un spectacle du dimanche devient une plage
    #    continue, donc proposé un jeudi.
    jours_flags: list[str] = []
    if any(_flat(day) not in hay for day in event.weekdays):
        jours_flags.append("hors_texte")
    if any(not _date_in(d, hay) for d in event.dates):
        jours_flags.append("hors_texte")
    morceaux = list(event.weekdays) + list(event.dates)
    add(
        "jours",
        "Les jours",
        ", ".join(morceaux),
        bool(morceaux),
        "ancrage",
        sorted(set(jours_flags)),
    )

    # ── 8. les horaires
    horaires = " – ".join(t for t in (event.open_time, event.close_time) if t)
    add(
        "horaires",
        "Les horaires",
        horaires,
        bool(horaires),
        "ancrage",
        (
            ["hors_texte"]
            if any(t and not _time_in(t, hay) for t in (event.open_time, event.close_time))
            else []
        ),
    )

    # ── 9. intérieur ou extérieur. **Aucun instrument**, et c'est le sujet :
    #    une page ne l'écrit presque jamais, elle dit « au parc de la Villette »
    #    et c'est le lecteur qui conclut.
    add(
        "cadre",
        "Intérieur / extérieur",
        _SETTINGS.get(event.setting, event.setting),
        bool(event.setting),
        "aucun",
        [],
    )

    # ── 10. la catégorie : un référentiel, donc vérifiable sans humain.
    add(
        "categorie",
        "La catégorie",
        event.category,
        bool(event.category),
        "référentiel",
        ["hors_liste"] if known and _flat(event.category) not in known else [],
    )

    # ── 11. le lieu
    add(
        "lieu",
        "Le lieu",
        event.venue_name,
        bool(event.venue_name),
        "ancrage",
        ["hors_texte"] if _overlap(event.venue_name, hay) < _OVERLAP_MIN else [],
    )

    # ── 12. l'adresse
    adresse_flags: list[str] = []
    if event.venue_postal_code and not re.fullmatch(r"\d{5}", event.venue_postal_code.strip()):
        adresse_flags.append("incoherent")
    if event.venue_postal_code and _flat(event.venue_postal_code) not in hay:
        adresse_flags.append("hors_texte")
    if event.venue_city and _overlap(event.venue_city, hay) < _OVERLAP_MIN:
        adresse_flags.append("hors_texte")
    if event.venue_address and _overlap(event.venue_address, hay) < _OVERLAP_MIN:
        adresse_flags.append("hors_texte")
    adresse = ", ".join(
        p for p in (event.venue_address, event.venue_postal_code, event.venue_city) if p
    )
    add(
        "adresse",
        "L'adresse",
        adresse,
        bool(adresse),
        "ancrage + cohérence",
        sorted(set(adresse_flags)),
    )

    return out
