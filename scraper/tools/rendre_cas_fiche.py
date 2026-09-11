#!/usr/bin/env python3
"""Écrit les cas de mise en forme de la fiche, depuis `audit_fiche`.

    python3 tools/rendre_cas_fiche.py

C'est Python qui fait foi : le site reconstitue ces chaînes en TypeScript pour
s'en servir d'étiquette, et `tests/test_fiche_publiee.py` vérifie des deux
côtés qu'elles n'ont pas divergé. Régénérer ce fichier est donc la bonne façon
de changer une mise en forme — et ça obligera à adapter
`server/src/lib/fichePubliee.ts`, ce qui est exactement le but.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sortiesbot.evaluation import audit_fiche  # noqa: E402
from sortiesbot.models import ExtractedEvent  # noqa: E402

CAS = [
    ("gratuite, une seule date, en intérieur", dict(
        title="Atelier modelage", description="Un atelier de terre pour les petites mains.",
        free=True, age_min=3, age_max=10, date_start="2026-09-20", date_end="",
        open_time="10:00", close_time="12:00", setting="INDOOR", category="Ateliers",
        venue_name="Musée Rodin", venue_address="77 rue de Varenne",
        venue_postal_code="75007", venue_city="Paris")),
    ("payante à prix rond, sur une plage, en extérieur", dict(
        title="Chasse au trésor", description="Une chasse au trésor dans le parc.",
        free=False, price=8.0, age_min=6, date_start="2026-09-20", date_end="2026-10-05",
        setting="OUTDOOR", category="Jeux", venue_name="Parc de Sceaux",
        venue_address="", venue_postal_code="92330", venue_city="Sceaux")),
    ("prix à décimale, âge maximum seul, permanente", dict(
        title="Expo permanente", description="Une exposition à demeure.",
        free=False, price=8.5, age_max=12, permanent=True, setting="BOTH",
        category="Expositions", venue_name="Cité des sciences",
        venue_address="30 avenue Corentin-Cariou", venue_postal_code="75019",
        venue_city="Paris")),
    ("tout muet : les vides sont des étiquettes", dict(
        title="Sans rien", description="", free=False, venue_name="",
        venue_address="", venue_postal_code="", venue_city="")),
]


def main() -> int:
    out = []
    for nom, champs in CAS:
        event = ExtractedEvent(relevant=True, **champs)
        aspects = {a["key"]: a["value"] for a in audit_fiche(event, "")}
        # Hors jeu : le site ne reçoit pas les jours de représentation.
        aspects.pop("jours", None)
        out.append({
            "nom": nom,
            "sortie": {
                "title": event.title, "description": event.description,
                "isFree": event.free, "price": event.price,
                "ageMin": event.age_min, "ageMax": event.age_max,
                "isPermanent": event.permanent,
                "dateStart": event.date_start, "dateEnd": event.date_end,
                "openTime": event.open_time, "closeTime": event.close_time,
                "setting": event.setting, "category": event.category,
                "venueName": event.venue_name, "venueAddress": event.venue_address,
                "venuePostalCode": event.venue_postal_code, "venueCity": event.venue_city,
            },
            "attendue": aspects,
        })

    cible = Path(__file__).resolve().parents[2] / "server" / "src" / "lib" / "fichePubliee.cas.json"
    cible.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(out)} cas écrits dans {cible}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
