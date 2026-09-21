"""Le fournisseur OpenRouter : un routeur pour les quatre appels du modèle.

Aucun appel réseau. Les réponses sont simulées à la forme **documentée** de
l'API — un objet portant `choices[].message.content` et un `usage` qui dit ce
que l'appel a coûté.

À la différence de Serper, cette forme n'a **pas encore été confrontée au
service** : personne, dans ce dépôt, ne l'a vérifiée. Ces tests verrouillent
donc ce que le code fait de cette forme, et rien de plus ; c'est
`tools/openrouter_shape.py`, lancé par le job `openrouter` de
`verifier.yml`, qui dira si elle est la bonne.

Ce qu'ils gardent surtout : que ce fournisseur pose **exactement la même
question** que celui d'Anthropic — mêmes schémas, même consigne système,
mêmes plafonds —, faute de quoi le banc mesurerait notre code en croyant
mesurer des modèles.
"""

from __future__ import annotations

import io
import json
import json as _json

import pytest

from sortiesbot.config import Config, ConfigError, config_from_api
from sortiesbot.harvest import Link
from sortiesbot.journal import RunLog
from sortiesbot.models import Usage
from sortiesbot.prompts import SYSTEM
from sortiesbot.providers.base import ProviderError, get_provider
from sortiesbot.providers.openrouter_provider import (
    ENDPOINT,
    MODELE_DEFAUT,
    TARIF_INCONNU,
    OpenRouterProvider,
    modele_openrouter,
)
from sortiesbot.providers.schemas import EXTRACTION_SCHEMA, SELECT_SCHEMA


class Reponse:
    def __init__(self, payload, status: int = 200, illisible: bool = False):
        self._payload = payload
        self.status_code = status
        self._illisible = illisible

    def json(self):
        if self._illisible:
            raise ValueError("pas du JSON")
        return self._payload


class RouteurSimule:
    """Enregistre les appels et sert des réponses scriptées."""

    def __init__(self, *reponses):
        self.reponses = list(reponses)
        self.appels: list[dict] = []

    def post(self, url, headers=None, json=None, data=None, timeout=None):
        # `data=` est la façon dont le client Serper poste : le même faux
        # sert aux deux, pour que le test de composition les branche ensemble.
        corps = json if json is not None else _json.loads(data or "{}")
        self.appels.append(
            {"url": url, "headers": headers or {}, "body": corps, "timeout": timeout}
        )
        return self.reponses.pop(0) if self.reponses else Reponse(reponse({}))


def reponse(contenu: dict, *, cout: float | None = 0.0012, fin: str = "stop") -> dict:
    """Une réponse du service, à la forme documentée."""
    usage = {"prompt_tokens": 1000, "completion_tokens": 100}
    if cout is not None:
        usage["cost"] = cout
    return {
        "id": "gen-1",
        "model": "z-ai/glm-5.3-flash",
        "choices": [
            {
                "index": 0,
                "finish_reason": fin,
                "message": {"role": "assistant", "content": json.dumps(contenu)},
            }
        ],
        "usage": usage,
    }


@pytest.fixture
def log():
    return RunLog(path=None, verbose=False, stream=io.StringIO())


def config(**extra) -> Config:
    return Config(name="essai", theme="spectacles enfants", provider="openrouter", **extra)


def provider_de(*reponses) -> tuple[OpenRouterProvider, RouteurSimule]:
    routeur = RouteurSimule(*reponses)
    return OpenRouterProvider(api_key="sk-or-x", session=routeur), routeur


FICHE = {
    "relevant": True, "skip_reason": "", "several": False,
    "title": "Concert de poche", "description": "Pour les 3-6 ans",
    "free": False, "price": 8.0, "age_min": 3, "age_max": 6,
    "permanent": False, "date_start": "2026-10-03", "date_end": "2026-10-03",
    "weekdays": ["samedi"], "dates": [], "open_time": "15:00", "close_time": "",
    "setting": "INDOOR", "category": "Spectacle", "venue_name": "Le Petit Théâtre",
    "venue_address": "1 rue des Lilas", "venue_city": "Paris",
    "venue_postal_code": "75011", "photo_url": "",
}


# ─────────────────────────────────────────────────── ce qu'on envoie vraiment


def test_lappel_porte_le_schema_la_consigne_et_la_facture(log):
    """Un appel dit tout ce qu'il demande : le schéma, le routage, le coût."""
    provider, routeur = provider_de(Reponse(reponse(FICHE)))
    provider.extract("https://x.fr/a", "le texte de la page", config(), ["Spectacle"], log)

    appel = routeur.appels[0]
    assert appel["url"] == ENDPOINT
    assert appel["headers"]["Authorization"] == "Bearer sk-or-x"

    corps = appel["body"]
    assert corps["model"] == MODELE_DEFAUT
    assert corps["messages"][0] == {"role": "system", "content": SYSTEM}
    assert "le texte de la page" in corps["messages"][1]["content"]
    # Le schéma est celui du pipeline, pas une copie : c'est ce qui garantit
    # que les deux fournisseurs rendent la même fiche.
    assert corps["response_format"]["json_schema"]["schema"] is EXTRACTION_SCHEMA
    assert corps["response_format"]["json_schema"]["strict"] is True
    # Ne router que vers un hébergeur qui sait contraindre la sortie…
    assert corps["provider"] == {"require_parameters": True}
    # …et qu'il dise ce que ça coûte.
    assert corps["usage"] == {"include": True}


def test_aucun_outil_nest_proposé(log):
    """Le modèle n'a pas d'outil, donc pas d'itération, donc pas de surprise."""
    provider, routeur = provider_de(Reponse(reponse({"queries": ["a", "b"]})))
    provider.queries(config(), log)
    assert "tools" not in routeur.appels[0]["body"]


# ──────────────────────────────────────────────────────── les noms de modèles


def test_un_slug_openrouter_passe_tel_quel():
    """Qui écrit un slug a choisi : le catalogue dira s'il existe, pas nous."""
    assert modele_openrouter("google/gemini-2.5-flash") == "google/gemini-2.5-flash"


def test_un_nom_du_pipeline_vaut_le_modele_par_defaut():
    """La console pré-remplit ses champs avec un nom qui n'existe pas là-bas.

    C'est le cas normal, et il ne veut pas dire « route-moi vers le même
    modèle » : on ne passe pas à un routeur pour payer Claude par un
    intermédiaire.
    """
    assert modele_openrouter("claude-haiku-4-5") == MODELE_DEFAUT
    assert modele_openrouter("claude-sonnet-5") == MODELE_DEFAUT


def test_le_modele_par_defaut_est_celui_quon_a_choisi():
    """Il se lit ici plutôt que dans quatre fichiers de configuration."""
    assert MODELE_DEFAUT == "z-ai/glm-5.3-flash:floor"


def test_le_defaut_se_remplace_sans_toucher_au_module():
    assert modele_openrouter("claude-haiku-4-5", "openai/gpt-5-mini") == "openai/gpt-5-mini"


def test_un_nom_qui_nest_ni_lun_ni_lautre_est_refuse():
    """Sinon une faute de frappe passerait pour « rien choisi ».

    Et le run entier tournerait sur un modèle qu'on n'a pas demandé, sans que
    rien ne le dise.
    """
    with pytest.raises(ProviderError) as err:
        modele_openrouter("gemini-2.5-flash")
    assert "éditeur/modèle" in str(err.value)


def test_une_configuration_refuse_un_modele_intraduisible_au_chargement():
    """Avant la première dépense, pas au milieu du run."""
    with pytest.raises(ConfigError) as err:
        config_from_api(
            {
                "name": "essai", "theme": "x",
                "provider": "openrouter", "extractionModel": "mistral-petit",
            }
        )
    assert "extractionModel" in str(err.value)


def test_une_configuration_openrouter_accepte_les_modeles_par_defaut():
    """La console écrit « claude-haiku-4-5 » partout : ça doit passer."""
    conf = config_from_api({"name": "essai", "theme": "x", "provider": "openrouter"})
    assert conf.provider == "openrouter"


def test_une_configuration_laissee_par_defaut_appelle_le_modele_par_defaut(log):
    """Le bout en bout : ce que la console écrit, et ce qui part vraiment."""
    conf = config_from_api({"name": "essai", "theme": "x", "provider": "openrouter"})
    provider, routeur = provider_de(Reponse(reponse(FICHE)))
    provider.extract("https://x.fr/a", "texte", conf, [], log)
    assert routeur.appels[0]["body"]["model"] == MODELE_DEFAUT


# ──────────────────────────────────────────────────────────────── la facture


def test_le_cout_est_celui_que_le_service_annonce(log):
    """On lit la facture, on ne la recalcule pas : lui seul connaît sa grille."""
    provider, _ = provider_de(Reponse(reponse(FICHE, cout=0.0042)))
    provider.extract("https://x.fr/a", "texte", config(), [], log)
    assert provider.usage.cost_usd == pytest.approx(0.0042)
    assert (provider.usage.input_tokens, provider.usage.output_tokens) == (1000, 100)


def test_un_cout_absent_ne_vaut_jamais_zero(log):
    """Sinon le plafond du run, qui se compare à un total, ne tomberait jamais."""
    provider, _ = provider_de(Reponse(reponse(FICHE, cout=None)))
    provider.extract("https://x.fr/a", "texte", config(), [], log)
    attendu = (1000 * TARIF_INCONNU[0] + 100 * TARIF_INCONNU[1]) / 1_000_000
    assert provider.usage.cost_usd == pytest.approx(attendu)
    assert attendu > 0


def test_un_cout_absent_est_signale_une_seule_fois():
    """Une estimation se dit ; se répéter à chaque page noierait le journal."""
    recus: list[dict] = []
    journal = RunLog(path=None, verbose=False)
    journal.sink = recus.append
    provider, _ = provider_de(
        Reponse(reponse(FICHE, cout=None)), Reponse(reponse(FICHE, cout=None))
    )
    provider.extract("https://x.fr/a", "texte", config(), [], journal)
    provider.extract("https://x.fr/b", "texte", config(), [], journal)
    avertissements = [r for r in recus if r.get("level") == "warn"]
    assert len(avertissements) == 1
    assert "n'a pas annoncé le coût" in avertissements[0]["message"]


# ────────────────────────────────────────────────────── ce qu'on lit en retour


def test_le_json_enrobe_reste_lisible(log):
    """Tous les modèles ne rendent pas du JSON nu, même sous schéma strict."""
    brut = reponse({})
    brut["choices"][0]["message"]["content"] = (
        "Voici la fiche :\n```json\n" + json.dumps(FICHE) + "\n```"
    )
    provider, _ = provider_de(Reponse(brut))
    fiches = provider.extract("https://x.fr/a", "texte", config(), [], log)
    assert fiches[0].title == "Concert de poche"


def test_une_reponse_tronquee_le_dit(log):
    """« Réponse illisible » enverrait chercher chez le modèle une faute à nous."""
    provider, _ = provider_de(Reponse(reponse(FICHE, fin="length")))
    with pytest.raises(ProviderError) as err:
        provider.extract("https://x.fr/a", "texte", config(), [], log)
    assert "tronquée" in str(err.value)


def test_la_selection_ne_rend_que_des_numeros(log):
    """Le modèle n'écrit aucune URL : il ne peut donc pas en inventer."""
    liens = [Link(url=f"https://x.fr/{i}", text=f"lien {i}", context="") for i in range(1, 4)]
    provider, routeur = provider_de(
        Reponse(reponse({"kept": [{"index": 2, "why": "un spectacle"}], "dropped_reason": "hors sujet"}))
    )
    gardes = provider.select("https://x.fr", liens, config(), log)
    assert [lien.url for lien in gardes] == ["https://x.fr/2"]
    assert routeur.appels[0]["body"]["response_format"]["json_schema"]["schema"] is SELECT_SCHEMA


def test_la_selection_ignore_les_numeros_hors_bornes(log):
    liens = [Link(url="https://x.fr/1", text="lien", context="")]
    provider, _ = provider_de(
        Reponse(reponse({"kept": [{"index": 9, "why": "?"}, {"index": 1, "why": "ok"}], "dropped_reason": ""}))
    )
    assert len(provider.select("https://x.fr", liens, config(), log)) == 1


def test_une_reconnaissance_inattendue_retombe_sur_inconnu(log):
    """Tous les hébergeurs n'honorent pas l'énumération aussi strictement."""
    provider, _ = provider_de(Reponse(reponse({"nature": "peut-être", "pourquoi": "bof"})))
    nature, motif = provider.classify("un condensé", config(), log)
    assert nature == "inconnu"
    assert "peut-être" in motif


def test_un_programme_rend_plusieurs_fiches(log):
    """Le mode « site » lit une page de programme d'un bloc."""
    item = {k: v for k, v in FICHE.items() if k not in ("relevant", "skip_reason", "several")}
    provider, _ = provider_de(
        Reponse(reponse({"events": [item, {**item, "title": "Autre"}], "skip_reason": ""}))
    )
    fiches = provider.extract("https://x.fr/p", "texte", config(), [], log, multiple=True)
    assert [f.title for f in fiches] == ["Concert de poche", "Autre"]


def test_un_programme_vide_rend_une_fiche_hors_sujet(log):
    provider, _ = provider_de(
        Reponse(reponse({"events": [], "skip_reason": "rien pour les enfants"}))
    )
    fiches = provider.extract("https://x.fr/p", "texte", config(), [], log, multiple=True)
    assert (fiches[0].relevant, fiches[0].skip_reason) == (False, "rien pour les enfants")


# ────────────────────────────────────────────────────────────── les échecs


@pytest.mark.parametrize(
    ("code", "attendu"),
    [
        (401, "clé OpenRouter refusée"),
        (402, "crédits OpenRouter épuisés"),
        (404, "modèle inconnu"),
        (500, "HTTP 500"),
    ],
)
def test_un_echec_dit_quoi_faire(code, attendu, log):
    provider, _ = provider_de(Reponse({"error": {"message": "détail du service"}}, status=code))
    with pytest.raises(ProviderError) as err:
        provider.classify("condensé", config(), log)
    assert attendu in str(err.value)
    # Le détail du service est repris : c'est lui qui nomme le modèle fautif.
    assert "détail du service" in str(err.value)


def test_un_echec_porte_dans_un_200_est_un_echec(log):
    """Le service rend parfois 200 en logeant la panne dans le corps."""
    provider, _ = provider_de(Reponse({"error": {"message": "modèle indisponible"}}))
    with pytest.raises(ProviderError) as err:
        provider.classify("condensé", config(), log)
    assert "modèle indisponible" in str(err.value)


def test_un_429_est_reessaye_puis_abandonne(monkeypatch, log):
    """Ce qui est passager se réessaie ; ce qui ne l'est pas, jamais."""
    from sortiesbot.providers import openrouter_provider

    dodos: list[float] = []
    monkeypatch.setattr(openrouter_provider.time, "sleep", dodos.append)
    provider, routeur = provider_de(
        Reponse({"error": {"message": "trop d'appels"}}, status=429),
        Reponse(reponse({"nature": "sortie", "pourquoi": "une fiche"})),
    )
    nature, _ = provider.classify("condensé", config(), log)
    assert nature == "sortie"
    assert len(routeur.appels) == 2
    assert dodos == [2.0]


def test_un_429_qui_dure_finit_par_lever(monkeypatch, log):
    from sortiesbot.providers import openrouter_provider

    monkeypatch.setattr(openrouter_provider.time, "sleep", lambda _: None)
    provider, routeur = provider_de(
        *[Reponse({"error": {"message": "trop d'appels"}}, status=429) for _ in range(3)]
    )
    with pytest.raises(ProviderError):
        provider.classify("condensé", config(), log)
    assert len(routeur.appels) == 3


def test_une_erreur_de_cle_ne_se_reessaie_pas(monkeypatch, log):
    provider, routeur = provider_de(Reponse({"error": {"message": "clé morte"}}, status=401))
    with pytest.raises(ProviderError):
        provider.classify("condensé", config(), log)
    assert len(routeur.appels) == 1


def test_sans_cle_le_fournisseur_ne_se_construit_pas():
    """Une configuration qui le nomme sans clé échoue tout de suite, pas au run."""
    with pytest.raises(ProviderError) as err:
        OpenRouterProvider(api_key=None)
    assert "OPENROUTER_API_KEY" in str(err.value)


def test_la_recherche_est_refusee_plutot_que_vide(log):
    """Une liste vide se lirait comme une recherche infructueuse."""
    provider, _ = provider_de()
    with pytest.raises(ProviderError) as err:
        provider.search(["spectacle enfant"], config(), log)
    assert "ne cherche pas" in str(err.value)


# ─────────────────────────────────────────────────────────── la composition


def test_le_fournisseur_compose_le_moteur_et_le_routeur(log):
    """« openrouter » : Serper cherche, OpenRouter fait les quatre autres appels."""
    moteur = RouteurSimule(
        Reponse({"credits": 1, "organic": [{"link": "https://x.fr/a", "title": "A"}]})
    )
    routeur = RouteurSimule(Reponse(reponse({"nature": "agenda", "pourquoi": "des dates"})))
    modele = OpenRouterProvider(api_key="sk-or-x", session=routeur)
    from sortiesbot.providers.serper_provider import SerperProvider

    provider = SerperProvider(modele, api_key="serper-x", session=moteur)

    pages = provider.search(["spectacle enfant"], config(), log)
    assert [p.url for p in pages] == ["https://x.fr/a"]
    assert len(moteur.appels) == 1 and len(routeur.appels) == 0

    assert provider.classify("condensé", config(), log)[0] == "agenda"
    assert len(routeur.appels) == 1


def test_get_provider_monte_bien_les_deux(log):
    provider = get_provider(
        config(), api_key=None, serper_key="serper-x", openrouter_key="sk-or-x"
    )
    assert isinstance(provider.usage, Usage)
    # Le moteur est devant, le routeur derrière : c'est ce que dit le tableau
    # de `get_provider`, et ce qu'aucune clé Anthropic n'est venue compléter.
    assert provider.name == "serper"
    assert isinstance(provider._model, OpenRouterProvider)


def test_get_provider_refuse_openrouter_sans_sa_cle(log):
    with pytest.raises(ProviderError) as err:
        get_provider(config(), serper_key="serper-x", openrouter_key=None)
    assert "OPENROUTER_API_KEY" in str(err.value)


def test_un_contenu_en_morceaux_est_recolle(log):
    """Certains modèles rendent des blocs là où l'API d'OpenAI rend une chaîne."""
    brut = reponse({})
    brut["choices"][0]["message"]["content"] = [
        {"type": "text", "text": json.dumps(FICHE)[:20]},
        {"type": "text", "text": json.dumps(FICHE)[20:]},
    ]
    provider, _ = provider_de(Reponse(brut))
    fiches = provider.extract("https://x.fr/a", "texte", config(), [], log)
    assert fiches[0].title == "Concert de poche"


def test_en_mode_site_le_moteur_nest_pas_monte():
    """Aucune recherche n'y est lancée : réclamer la clé du moteur serait absurde."""
    conf = config(mode="site", seed_urls=["https://festival.fr"])
    provider = get_provider(conf, openrouter_key="sk-or-x", serper_key=None)
    assert isinstance(provider, OpenRouterProvider)
