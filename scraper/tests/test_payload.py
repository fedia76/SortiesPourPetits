"""Le payload doit satisfaire les règles de server/src/lib/validators.ts."""

from datetime import date

import pytest

from sortiesbot.models import UNLOCATED, ExtractedEvent, Location
from sortiesbot.payload import POSTAL_PLACEHOLDER, UNKNOWN_PRICE, Rejected, build_payload

TODAY = date(2026, 8, 27)
PARIS = Location(lat=48.8566, lng=2.3522, city="Paris", postal_code="75001")


def make(**overrides) -> ExtractedEvent:
    base = dict(
        relevant=True,
        title="Spectacle de marionnettes",
        description="Un spectacle de marionnettes pour les tout-petits, tous les mercredis.",
        free=True,
        permanent=False,
        date_start="2026-09-01",
        date_end="2026-09-30",
        venue_name="Théâtre du Parc",
        venue_address="12 rue des Lilas",
        venue_city="Paris",
        category="Spectacle",
    )
    base.update(overrides)
    return ExtractedEvent(**base)


def test_payload_complet():
    payload = build_payload(make(), PARIS, 3, "https://exemple.fr/spectacle", today=TODAY)
    assert payload["title"] == "Spectacle de marionnettes"
    assert payload["isFree"] is True
    assert payload["price"] is None
    assert payload["categoryId"] == 3
    assert payload["sourceUrl"] == "https://exemple.fr/spectacle"
    assert payload["venue"]["postalCode"] == "75001"
    assert payload["venue"]["lat"] == pytest.approx(48.8566)


def test_sans_geocodage_les_champs_obligatoires_sont_remplis():
    payload = build_payload(make(), UNLOCATED, 1, "https://exemple.fr/x", today=TODAY)
    assert payload["venue"]["lat"] == 0
    assert payload["venue"]["lng"] == 0
    # La ville et le code postal restent exigés par l'API : le modérateur
    # corrigera, mais la sortie n'est pas perdue.
    assert payload["venue"]["city"] == "Paris"
    assert payload["venue"]["postalCode"] == POSTAL_PLACEHOLDER


def test_tarif_inconnu_part_avec_la_valeur_convenue():
    # La sortie n'est pas perdue : elle arrive avec un tarif que la modération
    # sait reconnaître, et que le serveur refuse d'approuver tel quel.
    payload = build_payload(make(free=False, price=None), PARIS, 1, "https://x.fr", today=TODAY)
    assert payload["isFree"] is False
    assert payload["price"] == UNKNOWN_PRICE


def test_prix_aberrant_bascule_sur_la_valeur_convenue():
    payload = build_payload(
        make(free=False, price=999_999), PARIS, 1, "https://x.fr", today=TODAY
    )
    assert payload["price"] == UNKNOWN_PRICE


def test_sortie_terminee_est_ecartee():
    with pytest.raises(Rejected, match="terminée"):
        build_payload(
            make(date_start="2026-08-01", date_end="2026-08-10"),
            PARIS,
            1,
            "https://x.fr",
            today=TODAY,
        )


def test_dates_inversees_sont_remises_dans_lordre():
    payload = build_payload(
        make(date_start="2026-09-30", date_end="2026-09-01"), PARIS, 1, "https://x.fr", today=TODAY
    )
    assert payload["dateStart"] == "2026-09-01"
    assert payload["dateEnd"] == "2026-09-30"


def test_permanent_sans_dates():
    payload = build_payload(
        make(permanent=True, date_start="", date_end=""), PARIS, 1, "https://x.fr", today=TODAY
    )
    assert payload["isPermanent"] is True
    assert payload["dateStart"] is None and payload["dateEnd"] is None


def test_horaires_incoherents_sont_abandonnes():
    payload = build_payload(
        make(open_time="18:00", close_time="10:00"), PARIS, 1, "https://x.fr", today=TODAY
    )
    assert payload["openTime"] is None and payload["closeTime"] is None


def test_ages_inverses_et_bornes():
    payload = build_payload(make(age_min=12, age_max=3), PARIS, 1, "https://x.fr", today=TODAY)
    assert payload["ageMin"] == 3 and payload["ageMax"] == 12
    payload = build_payload(make(age_min=0, age_max=99), PARIS, 1, "https://x.fr", today=TODAY)
    assert payload["ageMax"] == 18


def test_description_trop_courte_est_ecartee():
    with pytest.raises(Rejected, match="description"):
        build_payload(make(description="Court"), PARIS, 1, "https://x.fr", today=TODAY)


def test_titre_et_description_sont_tronques():
    payload = build_payload(
        make(title="Spectacle " * 40, description="Un très beau spectacle. " * 1000),
        PARIS,
        1,
        "https://x.fr",
        today=TODAY,
    )
    assert len(payload["title"]) <= 150
    assert len(payload["description"]) <= 10_000


def test_setting_inconnu_devient_nul():
    payload = build_payload(make(setting="DEHORS"), PARIS, 1, "https://x.fr", today=TODAY)
    assert payload["setting"] is None
