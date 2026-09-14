"""Ce que toute la suite tient pour acquis.

Les délais de politesse sont indispensables en production et n'ont aucun sens
ici : ils ne font que rallonger la suite d'une seconde par appel simulé. On les
désarme donc partout, et les deux tests qui mesurent la cadence les réarment
eux-mêmes — un `monkeypatch` de test l'emporte sur celui d'une fixture.
"""

from __future__ import annotations

import pytest

from sortiesbot import geocode as geocoding


@pytest.fixture(autouse=True)
def sans_delai_de_politesse(monkeypatch):
    monkeypatch.setattr("sortiesbot.harvest.CRAWL_DELAY", 0)
    monkeypatch.setattr(geocoding, "CALL_DELAY", 0)
    # La mise en sourdine de Photon vit dans le module : sans ce réarmement,
    # un test qui la déclenche déciderait du sort des suivants.
    geocoding.reset()
    yield
    geocoding.reset()
