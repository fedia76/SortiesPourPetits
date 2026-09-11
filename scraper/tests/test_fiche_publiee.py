"""Le format de la fiche, tel que deux langages doivent l'écrire pareil.

`audit_fiche` met en forme ce que la brique a rendu — « gratuit », « dès 3
ans », « du 2026-09-20 au 2026-10-05 ». Le site reconstitue les mêmes chaînes
depuis une sortie publiée, en TypeScript, pour s'en servir d'étiquette
(`server/src/lib/fichePubliee.ts`). Les deux se comparent : si les mises en
forme divergent, la mesure de l'étage 6 lit « faux » partout sans que la brique
ait fauté.

C'est une convention dupliquée entre deux langages. On ne fait pas semblant
qu'elle n'existe pas : ce fichier de cas est écrit une fois, et les deux côtés
le vérifient. Changer une mise en forme ici casse ce test — bruyamment, plutôt
qu'en silence dans une courbe.

Le fichier se régénère avec `tools/rendre_cas_fiche.py`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sortiesbot.evaluation import audit_fiche
from sortiesbot.models import ExtractedEvent

CAS = Path(__file__).resolve().parents[2] / "server" / "src" / "lib" / "fichePubliee.cas.json"

#: Les clés du site vers celles du modèle. Le site publie ce qu'il a reçu.
CHAMPS = {
    "title": "title", "description": "description", "isFree": "free", "price": "price",
    "ageMin": "age_min", "ageMax": "age_max", "isPermanent": "permanent",
    "dateStart": "date_start", "dateEnd": "date_end", "openTime": "open_time",
    "closeTime": "close_time", "setting": "setting", "category": "category",
    "venueName": "venue_name", "venueAddress": "venue_address",
    "venuePostalCode": "venue_postal_code", "venueCity": "venue_city",
}


def cas() -> list[dict]:
    return json.loads(CAS.read_text(encoding="utf-8"))


def test_le_fichier_de_cas_existe():
    """Sans lui, le côté TypeScript n'a rien à vérifier."""
    assert CAS.exists(), f"{CAS} manquant — régénérez-le"
    assert cas(), "aucun cas"


@pytest.mark.parametrize("exemple", cas(), ids=lambda e: e["nom"])
def test_audit_fiche_rend_bien_ce_que_le_site_attend(exemple):
    """La mise en forme de Python est celle que le site reconstitue."""
    champs = {
        motif: exemple["sortie"][site]
        for site, motif in CHAMPS.items()
        if exemple["sortie"].get(site) not in (None, "")
    }
    event = ExtractedEvent(relevant=True, **champs)
    rendu = {a["key"]: a["value"] for a in audit_fiche(event, "")}

    for cle, attendu in exemple["attendue"].items():
        assert rendu[cle] == attendu, (
            f"« {cle} » : Python rend {rendu[cle]!r}, le site attend {attendu!r}. "
            f"Si c'est Python qui a raison, régénérez les cas et adaptez "
            f"server/src/lib/fichePubliee.ts."
        )


def test_les_jours_restent_hors_jeu():
    """Le site ne peut pas les reconstituer : il ne les reçoit pas.

    La brique rend les jours lus dans la prose (« tous les dimanches ») suivis
    des dates annoncées. Le pipeline se sert des premiers pour fabriquer les
    secondes, et seuls les seconds partent au site. Une étiquette reconstituée
    serait donc amputée, et chaque sortie à récurrence compterait « faux ».
    """
    for exemple in cas():
        assert "jours" not in exemple["attendue"]
