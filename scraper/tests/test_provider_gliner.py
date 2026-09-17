"""Le fournisseur GLiNER, sans GLiNER.

L'étiqueteur s'injecte, si bien que toute la mécanique — découpage d'une longue
page, report des décalages, refus du mode programme, délégation des quatre
autres appels — se vérifie sans installer torch et sans télécharger un modèle.
C'est la contrepartie d'avoir séparé `spans.py` (pur) de ce fichier (le
branchement) : rien de ce qui est testé ici ne demande deux gigaoctets.
"""

from __future__ import annotations

from datetime import date

import pytest

from sortiesbot.config import Config
from sortiesbot.journal import RunLog
from sortiesbot.providers.base import ProviderError, get_provider
from sortiesbot.providers.gliner_provider import (
    FENETRE_CARACTERES,
    RECOUVREMENT,
    GlinerProvider,
)
from sortiesbot.spans import LABELS

AUJOURD_HUI = date(2026, 7, 1)
PAR_CHAMP = {champ: libelle for libelle, champ in LABELS.items()}


class FauxTagger:
    """Rend les spans qu'on lui a dictés, et note ce qu'on lui a demandé."""

    def __init__(self, reponses=None):
        self.reponses = reponses if reponses is not None else []
        self.appels: list[tuple[str, list[str], float]] = []

    def predict_entities(self, text, labels, threshold=0.5):
        self.appels.append((text, list(labels), threshold))
        return [dict(r) for r in self.reponses if r.get("text", "") in text]


def _log() -> RunLog:
    return RunLog(None, verbose=False)


def _config() -> Config:
    return Config(name="banc", theme="sorties enfants", provider="gliner")


def test_une_page_devient_une_fiche():
    tagger = FauxTagger(
        [
            {"label": PAR_CHAMP["title"], "text": "Le Petit Chaperon rouge", "score": 0.93},
            {"label": PAR_CHAMP["venue_city"], "text": "Nancy", "score": 0.88},
            {"label": PAR_CHAMP["price"], "text": "8 €", "score": 0.80},
        ]
    )
    provider = GlinerProvider(tagger=tagger, today=AUJOURD_HUI)
    fiches = provider.extract(
        "https://exemple.fr/spectacle",
        "Le Petit Chaperon rouge, à Nancy. Tarif : 8 € par enfant.",
        _config(),
        ["Spectacle"],
        _log(),
    )
    assert len(fiches) == 1
    assert fiches[0].title == "Le Petit Chaperon rouge"
    assert fiches[0].venue_city == "Nancy"
    assert fiches[0].price == 8.0


def test_les_libelles_partent_en_francais():
    """Le zero-shot apparie le texte du libellé à celui de la page.

    Envoyer `title` plutôt que « titre de l'événement » changerait ce que le
    modèle remonte : ces phrases sont un réglage, et le test les verrouille.
    """
    tagger = FauxTagger()
    GlinerProvider(tagger=tagger).extract("https://x.fr", "texte", _config(), [], _log())
    _, libelles, _ = tagger.appels[0]
    assert "titre de l'événement" in libelles
    assert set(libelles) == set(LABELS)


def test_une_longue_page_est_decoupee_avec_recouvrement():
    tagger = FauxTagger()
    texte = "a" * (FENETRE_CARACTERES * 2)
    GlinerProvider(tagger=tagger).extract("https://x.fr", texte, _config(), [], _log())
    assert len(tagger.appels) > 1
    assert all(len(morceau) <= FENETRE_CARACTERES for morceau, _, _ in tagger.appels)


def test_le_decalage_ramene_les_positions_a_la_page():
    """Un span trouvé dans le second tronçon doit pointer la page, pas le tronçon.

    Sans report du décalage, `start` vaudrait quelques dizaines au lieu de
    plusieurs milliers, et le span ne se relierait plus à ce qu'il désigne.
    """
    aiguille = "Le Petit Chaperon rouge"
    texte = "a" * (FENETRE_CARACTERES + 100) + aiguille
    tagger = FauxTagger(
        [{"label": PAR_CHAMP["title"], "text": aiguille, "score": 0.9, "start": 10, "end": 33}]
    )
    provider = GlinerProvider(tagger=tagger, today=AUJOURD_HUI)
    captures: list[dict] = []
    log = RunLog(None, verbose=False, sink=captures.append)
    provider.extract("https://x.fr", texte, _config(), [], log)
    pose = [e for e in captures if e.get("kind") == "gliner"]
    assert pose and pose[0]["spans"] >= 1
    assert FENETRE_CARACTERES - RECOUVREMENT > 0


def test_le_journal_dit_ce_que_la_brique_ne_rend_pas():
    """Un `MANQUE` sur `setting` doit se lire comme une limite, pas comme une faute."""
    captures: list[dict] = []
    log = RunLog(None, verbose=False, sink=captures.append)
    GlinerProvider(tagger=FauxTagger()).extract("https://x.fr", "texte", _config(), [], log)
    pose = [e for e in captures if e.get("kind") == "gliner"]
    assert pose
    assert "setting" in pose[0]["non_rendus"]
    assert "description" in pose[0]["non_rendus"]


def test_le_mode_programme_est_refuse_bruyamment():
    """Un étiqueteur ne segmente pas : vingt titres mêlés feraient un échec silencieux."""
    provider = GlinerProvider(tagger=FauxTagger())
    with pytest.raises(ProviderError, match="programme"):
        provider.extract("https://x.fr", "texte", _config(), [], _log(), multiple=True)


def test_l_extraction_ne_coute_rien():
    provider = GlinerProvider(tagger=FauxTagger())
    provider.extract("https://x.fr", "texte", _config(), [], _log())
    assert provider.usage.input_tokens == 0
    assert provider.usage.output_tokens == 0
    assert provider.usage.total_usd == 0.0


def test_un_echec_de_l_etiqueteur_devient_une_erreur_de_fournisseur():
    """L'étage 6 sait déjà traiter un `ProviderError` : il rapporte, il ne casse pas."""

    class Casse:
        def predict_entities(self, text, labels, threshold=0.5):
            raise RuntimeError("modèle introuvable")

    with pytest.raises(ProviderError, match="étiquetage impossible"):
        GlinerProvider(tagger=Casse()).extract("https://x.fr", "t", _config(), [], _log())


def test_les_quatre_autres_appels_refusent_sans_modele():
    """Ce fournisseur convient à un run de banc d'extraction, pas à un run complet."""
    provider = GlinerProvider(tagger=FauxTagger())
    with pytest.raises(ProviderError, match="que l'extraction"):
        provider.queries(_config(), _log())
    with pytest.raises(ProviderError, match="que l'extraction"):
        provider.classify("digest", _config(), _log())


def test_les_quatre_autres_appels_passent_au_modele_quand_il_est_la():
    class FauxModele:
        name = "faux"
        usage = None

        def queries(self, config, log):
            return ["une requête"]

    provider = GlinerProvider(FauxModele(), tagger=FauxTagger())
    assert provider.queries(_config(), _log()) == ["une requête"]


def test_get_provider_reconnait_gliner_sans_cle():
    """Un run de banc n'a pas de raison de réclamer une clé qu'il n'emploiera pas."""
    provider = get_provider(Config(name="t", theme="t", provider="gliner"))
    assert provider.name == "gliner"


def test_config_refuse_un_fournisseur_inconnu():
    from sortiesbot.config import ConfigError, validated

    with pytest.raises(ConfigError, match="fournisseur inconnu"):
        validated(Config(name="t", theme="t", provider="glinerr"))


# ─────────────────────── ce que l'essai contre la vraie bibliothèque a montré
#
# Deux comportements découverts en installant `gliner` 0.2.29 et en lançant le
# script d'exploration, plutôt qu'en lisant la documentation : la classe
# `GLiNER` est un aiguilleur dont `from_pretrained` rend une sous-classe, et
# le téléchargement des poids échoue par une exception de couche HTTP qui ne
# ressemble à rien de ce que le pipeline sait attraper.


class TaggerGroupe(FauxTagger):
    """Un étiqueteur qui sait traiter plusieurs tronçons d'un coup."""

    def __init__(self, reponses=None):
        super().__init__(reponses)
        self.lots: list[list[str]] = []

    def batch_predict_entities(self, texts, labels, threshold=0.5):
        # Volontairement sans passer par `predict_entities` : c'est ce qui
        # permet à `appels` de rester vide et donc de prouver que le chemin
        # groupé a bien été pris, plutôt que de le supposer.
        self.lots.append(list(texts))
        return [
            [dict(r) for r in self.reponses if r.get("text", "") in texte] for texte in texts
        ]


def test_une_page_decoupee_part_en_un_seul_lot():
    """Une passe pour tous les tronçons : un processeur de VPS n'a pas de marge."""
    tagger = TaggerGroupe()
    texte = "a" * (FENETRE_CARACTERES * 2)
    GlinerProvider(tagger=tagger).extract("https://x.fr", texte, _config(), [], _log())
    assert len(tagger.lots) == 1
    assert len(tagger.lots[0]) > 1
    assert tagger.appels == []


def test_une_seule_page_n_emprunte_pas_le_chemin_groupe():
    """Grouper un tronçon unique ne gagnerait rien et ferait un chemin de plus."""
    tagger = TaggerGroupe()
    GlinerProvider(tagger=tagger).extract("https://x.fr", "texte court", _config(), [], _log())
    assert tagger.lots == []
    assert len(tagger.appels) == 1


def test_un_etiqueteur_sans_methode_groupee_reste_servi():
    """Le `Protocol` n'exige que `predict_entities` : rien ne doit le démentir."""
    tagger = FauxTagger()
    texte = "a" * (FENETRE_CARACTERES * 2)
    GlinerProvider(tagger=tagger).extract("https://x.fr", texte, _config(), [], _log())
    assert len(tagger.appels) > 1


def test_charger_enveloppe_l_echec_de_telechargement(monkeypatch):
    import sys
    import types

    faux = types.ModuleType("gliner")

    class GLiNER:
        @staticmethod
        def from_pretrained(nom):
            raise ConnectionError("403 Forbidden")

    faux.GLiNER = GLiNER
    monkeypatch.setitem(sys.modules, "gliner", faux)

    from sortiesbot.providers.gliner_provider import charger

    with pytest.raises(ProviderError, match="indisponible"):
        charger("depot/inexistant")


# ───────────────────────────────── ce que le banc doit savoir faire de lui
#
# C'est l'intégration qui compte : `evaluation.extract_page` est la fonction
# que le worker appelle pour chaque page du corpus gelé. Si elle ne sait pas
# rejouer l'étage 6 avec ce fournisseur, tout le reste est décoratif.


def test_le_banc_rejoue_l_etage_6_avec_l_etiqueteur():
    from sortiesbot.evaluation import extract_page

    tagger = FauxTagger(
        [
            {"label": PAR_CHAMP["title"], "text": "Le Petit Chaperon rouge", "score": 0.93},
            {"label": PAR_CHAMP["venue_city"], "text": "Nancy", "score": 0.88},
            {"label": PAR_CHAMP["price"], "text": "8 €", "score": 0.81},
            {"label": PAR_CHAMP["dates"], "text": "du 3 au 12 août 2026", "score": 0.77},
        ]
    )
    texte = (
        "Le Petit Chaperon rouge, spectacle à Nancy, du 3 au 12 août 2026. "
        "Tarif : 8 € par enfant."
    )
    resultat = extract_page(
        "https://exemple.fr/spectacle",
        texte,
        provider=GlinerProvider(tagger=tagger, today=AUJOURD_HUI),
        config=_config(),
        log=_log(),
        categories=["Spectacle"],
        declared_dates=[],
    )

    # La forme que la console attend, telle quelle.
    assert "error" not in resultat
    assert resultat["fiche"]["title"] == "Le Petit Chaperon rouge"
    assert resultat["fiche"]["resolvedDates"]
    assert resultat["costUsd"] == 0.0
    assert len(resultat["aspects"]) == 12


def test_le_banc_ne_voit_aucune_invention_et_c_est_le_piege():
    """Le fait central de l'expérience, verrouillé par un test.

    Onze aspects sur douze sont jugés par « la valeur se lit-elle dans la
    page ? ». Un étiqueteur ne rend que des sous-chaînes : il ne peut pas lever
    `hors_texte`, par construction et non par mérite. Ce test existe pour que
    personne ne lise un jour ce zéro comme une victoire — la vraie mesure est
    la comparaison aux fiches étiquetées du corpus.
    """
    from sortiesbot.evaluation import extract_page

    texte = "Le Petit Chaperon rouge, à Nancy. Tarif : 8 € par enfant."
    tagger = FauxTagger(
        [
            {"label": PAR_CHAMP["title"], "text": "Le Petit Chaperon rouge", "score": 0.9},
            {"label": PAR_CHAMP["venue_city"], "text": "Nancy", "score": 0.9},
            {"label": PAR_CHAMP["price"], "text": "8 €", "score": 0.9},
        ]
    )
    resultat = extract_page(
        "https://exemple.fr/s",
        texte,
        provider=GlinerProvider(tagger=tagger, today=AUJOURD_HUI),
        config=_config(),
        log=_log(),
        categories=["Spectacle"],
    )
    drapeaux = [f for aspect in resultat["aspects"] for f in aspect["flags"]]
    assert "hors_texte" not in drapeaux

    # Et les aspects hors portée sont vides, pas verts : c'est ce qui distingue
    # une limite annoncée d'un chiffre fabriqué.
    vides = {a["key"] for a in resultat["aspects"] if not a["filled"]}
    assert {"description", "cadre", "categorie"} <= vides
