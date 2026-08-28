"""Dates réelles d'une sortie : JSON-LD, dates annoncées, récurrence.

Le cas qui motive tout : un spectacle joué tous les dimanches de juillet et
août ne doit pas ressortir un jeudi d'août.
"""

from __future__ import annotations

from sortiesbot.harvest import json_ld_dates
from sortiesbot.schedule import (
    SOURCE_ANNOUNCED,
    SOURCE_JSON_LD,
    SOURCE_RANGE,
    SOURCE_WEEKDAYS,
    resolve,
)


# ------------------------------------------------------------------ JSON-LD


def bloc(contenu: str) -> str:
    return f'<html><head><script type="application/ld+json">{contenu}</script></head><body>x</body></html>'


def test_json_ld_simple():
    html = bloc('{"@type": "Event", "name": "Chaperon", "startDate": "2026-07-05"}')
    assert json_ld_dates(html) == ["2026-07-05"]


def test_json_ld_graph_et_representations_imbriquees():
    """Les sites emboîtent : `@graph` à la racine, `subEvent` par représentation."""
    html = bloc("""{"@context": "https://schema.org", "@graph": [
      {"@type": "TheaterEvent", "startDate": "2026-07-05T15:00:00+02:00",
       "subEvent": [{"@type": "Event", "startDate": "2026-07-12"}]},
      {"@type": "Organization", "name": "Théâtre de Vanves"}]}""")
    assert json_ld_dates(html) == ["2026-07-05T15:00:00+02:00", "2026-07-12"]


def test_json_ld_illisible_est_ignore():
    """Un JSON-LD mal formé est fréquent : la page reste lisible par le modèle."""
    assert json_ld_dates(bloc("{ ceci n'est pas du json }")) == []


def test_page_sans_json_ld():
    assert json_ld_dates("<html><body><h1>Spectacle</h1></body></html>") == []


# ----------------------------------------------------------------- calendrier


def test_recurrence_ne_retient_que_les_dimanches():
    schedule = resolve("2026-07-01", "2026-08-31", weekdays=["dimanche"])
    assert schedule.source == SOURCE_WEEKDAYS
    assert "2026-08-13" not in schedule.dates  # un jeudi
    assert "2026-08-16" in schedule.dates  # un dimanche
    assert len(schedule.dates) == 9


def test_jours_reconnus_tries_et_dedoublonnes():
    schedule = resolve("2026-07-01", "2026-07-31", weekdays=["Samedi", "mercredi", "samedi", "xx"])
    assert schedule.weekdays == ("mercredi", "samedi")


def test_sept_jours_sur_sept_reste_une_plage():
    """Sept jours, c'est la plage elle-même : rien à matérialiser."""
    tous = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    assert resolve("2026-07-01", "2026-07-31", weekdays=tous).source == SOURCE_RANGE


def test_un_json_ld_de_periode_nest_pas_une_seance():
    """Un `Event` dont la fin tombe un autre jour décrit l'affiche, pas une
    représentation : sa `startDate` n'est que le premier jour."""
    html = bloc('{"@type": "Event", "startDate": "2026-08-26", "endDate": "2026-08-31"}')
    assert json_ld_dates(html) == []


def test_une_date_isolee_ne_fait_pas_un_calendrier():
    """Le cas le plus fréquent en production : le site ne publie qu'une entrée
    pour toute l'affiche. La récurrence, elle, est exacte — elle doit gagner."""
    schedule = resolve(
        "2026-08-01", "2026-08-31",
        weekdays=["mercredi", "samedi"],
        json_ld=["2026-08-26"],
    )
    assert schedule.source == SOURCE_WEEKDAYS
    assert "2026-08-26" in schedule.dates  # un mercredi, retrouvé autrement
    assert len(schedule.dates) == 9


def test_une_date_isolee_suffit_pour_une_sortie_dun_jour():
    schedule = resolve("2026-08-30", "2026-08-30", json_ld=["2026-08-30"])
    assert schedule.source == SOURCE_JSON_LD
    assert schedule.dates == ("2026-08-30",)


def test_le_json_ld_prime_quand_il_liste_les_seances():
    schedule = resolve(
        "2026-07-01", "2026-08-31",
        weekdays=["dimanche"],
        json_ld=["2026-07-05T15:00:00+02:00", "2026-07-12"],
    )
    assert schedule.source == SOURCE_JSON_LD
    assert schedule.dates == ("2026-07-05", "2026-07-12")
    # Les jours restent notés : ils disent la même chose autrement.
    assert schedule.weekdays == ("dimanche",)


def test_dates_annoncees_quand_le_json_ld_manque():
    schedule = resolve("2026-08-01", "2026-08-31", announced=["2026-08-12", "2026-08-03"])
    assert schedule.source == SOURCE_ANNOUNCED
    assert schedule.dates == ("2026-08-03", "2026-08-12")  # triées


def test_dates_hors_plage_sont_ecartees():
    """Une page de spectacle liste souvent d'autres salles ou d'autres saisons."""
    schedule = resolve(
        "2026-07-01", "2026-07-31",
        json_ld=["2026-07-05", "2026-07-19", "2027-01-10", "2026-06-30", "pas une date"],
    )
    assert schedule.dates == ("2026-07-05", "2026-07-19")


def test_sans_rien_on_garde_le_comportement_actuel():
    schedule = resolve("2026-07-01", "2026-08-31")
    assert schedule.source == SOURCE_RANGE
    assert schedule.dates == ()
    assert not schedule.precise


def test_sortie_permanente_sans_dates():
    assert resolve("", "", weekdays=["mercredi"]).source == SOURCE_RANGE


def test_deroulement_borne():
    """Dérouler dix ans de dates n'apprendrait rien de plus."""
    schedule = resolve("2020-01-01", "2030-01-01", weekdays=["lundi", "mardi"])
    assert len(schedule.dates) == 400
