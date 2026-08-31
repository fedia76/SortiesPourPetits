"""Le pipeline rejoué sur de vraies pages, telles que le web les sert.

Les autres tests vérifient l'enchaînement avec du HTML réduit à ce qu'ils
veulent démontrer. Ce qui casse en production n'est pourtant presque jamais
l'enchaînement : c'est la **couche qui lit le HTML** — un lien dont le texte a
changé, un JSON-LD reformaté, une illustration remplacée par un logo. Ces
régressions-là ne se voient que sur des pages entières, avec leur bandeau de
cookies, leur navigation et leur pied de page.

D'où ce jeu de pages complètes dans `fixtures/pages/`, décrit par un
`pages.jsonl` — une ligne par page : son fichier, son URL, et sa nature quand
on l'a étiquetée.

**Ce format est celui qu'écrit `--save-pages`.** Pour élargir la couverture,
il n'y a rien à coder :

    python -m sortiesbot -c configs/spectacles-weekend.yaml --save-pages /tmp/pages

puis on recopie ce qui est intéressant dans `fixtures/pages/`, et on ajoute
`"kind": "agenda"` ou `"sortie"` aux lignes qu'on veut voir servir de vérité
au classifieur. Les pages livrées ici sont écrites à la main, à l'imitation de
ce qu'on rencontre : elles ont vocation à être remplacées par des captures.

Les assertions portent sur **l'essentiel** — quelles pages deviennent des
candidates, combien de sorties sortent, leurs titres et leurs dates. Jamais
sur le JSON octet par octet : un test qu'un changement cosmétique fait rougir
finit désactivé, et ne protège plus rien.

Une page capturée porte des dates figées, et un run se juge par rapport à
aujourd'hui : les deux ne se mélangent pas. Les assertions sur les dates
restent donc du côté de la lecture, où elles valent pour toujours ; le run de
bout en bout, lui, ne vérifie que ce qui ne dépend pas de l'horloge — quelles
pages sont lues, lesquelles sont soumises, avec quelle illustration.
"""

from __future__ import annotations

import io
import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from sortiesbot.classify import INCONNU, classify
from sortiesbot.config import Config
from sortiesbot.harvest import json_ld_dates, links_of, main_image, page_text
from sortiesbot.journal import RunLog
from sortiesbot.models import ExtractedEvent, FoundPage, Usage
from sortiesbot.orchestrator import run
from sortiesbot.store import SeenStore

from test_pipeline import FakeApi, FakeFetcher

PAGES = Path(__file__).parent / "fixtures" / "pages"

AGENDA = "https://agenda.exemple-departement.fr/agenda/"
SPECTACLE = "https://theatre-du-chapiteau.exemple.fr/saison/le-petit-prince"
ATELIER = "https://www.ville-exemple.fr/culture/atelier-cirque-en-famille"


def corpus() -> list[dict]:
    """Les pages du jeu, telles que `pages.jsonl` les décrit."""
    lines = (PAGES / "pages.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def html_of(entry: dict) -> str:
    return (PAGES / entry["file"]).read_text(encoding="utf-8")


def by_url() -> dict[str, str]:
    return {entry["url"]: html_of(entry) for entry in corpus()}


IDS = [entry["file"] for entry in corpus()]


# ═══════════════════════════════════ ce qui doit tenir sur n'importe quelle page


@pytest.mark.parametrize("entry", corpus(), ids=IDS)
def test_une_vraie_page_se_lit_sans_rien_faire_exploser(entry):
    """Le contrat minimal : aucune page réelle ne doit mettre la lecture en échec.

    C'est ce qui rend une capture utile dès qu'on la dépose, avant même de
    l'étiqueter.
    """
    html = html_of(entry)
    url = entry["url"]

    texte = page_text(html)
    assert len(texte) > 200, "une page réelle porte du texte exploitable"
    # `page_text` retire nav, en-tête, pied de page et formulaires : c'est ce
    # qui doit tenir sur toute page. (Un bandeau de cookies en `<div>`, lui,
    # passe au travers — voir la note en fin de fichier.)
    assert "Mentions légales" not in texte

    for link in links_of(html, url):
        assert link.url.startswith(("http://", "https://"))

    for iso in json_ld_dates(html):
        assert len(iso) >= 10 and iso[4] == "-", f"date JSON-LD illisible : {iso}"

    assert classify(html, url).kind in ("agenda", "sortie", INCONNU)


@pytest.mark.parametrize(
    "entry", [e for e in corpus() if e.get("kind")], ids=[e["file"] for e in corpus() if e.get("kind")]
)
def test_le_classifieur_retrouve_la_nature_etiquetee(entry):
    """La vérité terrain du classifieur, une ligne de `pages.jsonl` à la fois.

    Ajouter `"kind"` à une capture suffit à en faire un cas de non-régression :
    c'est le jeu étiqueté qui dira, plus tard, si on peut se passer du
    classement du modèle.
    """
    verdict = classify(html_of(entry), entry["url"])
    assert verdict.kind == entry["kind"], f"{entry['file']} : {verdict.detail}"


# ══════════════════════════════════════ ce que ces pages-ci doivent donner


def test_l_agenda_rend_ses_sorties_et_pas_sa_tuyauterie():
    html, url = by_url()[AGENDA], AGENDA
    links = links_of(html, url)
    cibles = {link.url for link in links}

    assert f"{url}le-petit-prince" in cibles
    assert f"{url}boucle-d-or-et-les-trois-ours" in cibles
    assert len(links) >= 10, "les cartes d'événements doivent toutes ressortir"

    # Navigation, pied de page, pagination, liens sortants : rien de tout ça.
    for indesirable in ("/mentions-legales", "/cgu", "/contact", "/agenda/page/2",
                        "/categorie/spectacles", "facebook.com"):
        assert not any(indesirable in c for c in cibles), f"{indesirable} aurait dû être écarté"

    # Le contexte est ce qui permet de trier sans ouvrir la page.
    chaperon = next(link for link in links if "le-petit-prince" in link.url)
    assert "Créteil" in chaperon.context and "septembre" in chaperon.context


def test_la_fiche_de_spectacle_livre_ses_seances_et_son_affiche():
    html, url = by_url()[SPECTACLE], SPECTACLE

    dates = json_ld_dates(html)
    assert len(dates) == 6, "six représentations déclarées, six dates"
    assert all(d.startswith("2026-09-") for d in dates)

    image = main_image(html, url)
    assert image.endswith("petit-prince-affiche.jpg")
    assert "logo" not in image, "un logo n'est pas une illustration"

    texte = page_text(html)
    assert "théâtre d'ombres" in texte
    assert "Mentions légales" not in texte, "le pied de page est retiré avant lecture"


def test_une_fiche_sans_donnees_structurees_reste_lisible():
    html, url = by_url()[ATELIER], ATELIER
    assert json_ld_dates(html) == []
    assert "94200 Ivry-sur-Seine" in page_text(html)
    assert main_image(html, url).endswith("atelier-cirque.jpg")
    # Aucun lien exploitable : sans le filet de l'orchestrateur, cette page
    # serait perdue. C'est exactement le cas que la branche A doit rattraper.
    assert links_of(html, url) == []


# ══════════════════════════════════════════════ le pipeline, de bout en bout


@pytest.fixture
def log():
    return RunLog(path=None, verbose=False, stream=io.StringIO())


@pytest.fixture(autouse=True)
def photo_hors_ligne(monkeypatch):
    """Les fiches annoncent une affiche : personne ne la télécharge ici."""
    monkeypatch.setattr(
        "sortiesbot.stages.publication.download",
        lambda url, session=None: ("affiche.jpg", b"\xff\xd8\xff-des-octets", "image/jpeg"),
    )


@pytest.fixture(autouse=True)
def geocodeur_simule(monkeypatch):
    from sortiesbot import geocode as geocoding

    monkeypatch.setattr(
        geocoding, "_search",
        lambda query: [{"properties": {"city": "Créteil", "postcode": "94000"},
                        "geometry": {"coordinates": [2.4530, 48.7900]}}],
    )


class ProviderScripte:
    """Le modèle, tel qu'il a répondu le jour de la capture.

    Il retient tous les liens qu'on lui soumet : ce qui est vérifié ici, c'est
    la lecture du HTML, pas le jugement du modèle — celui-là a ses propres
    tests.
    """

    name = "golden"

    def __init__(self, trouvees, fiches):
        self.trouvees = trouvees
        self.fiches = fiches
        self.usage = Usage(input_tokens=100, output_tokens=20)
        self.extracted: list[str] = []

    def search(self, config, log):
        return list(self.trouvees)

    def select(self, page, links, config, log):
        return list(links)

    def extract(self, url, content, config, categories, log, *, multiple=False):
        self.extracted.append(url)
        assert len(content) > 200, "l'extraction doit recevoir du texte, pas un squelette"
        return [self.fiches[url]]


def fiche(titre: str, **extra) -> ExtractedEvent:
    demain = (date.today() + timedelta(days=1)).isoformat()
    base = dict(
        relevant=True,
        title=titre,
        description="Un spectacle pour les enfants, raconté pour leurs parents.",
        free=True,
        date_start=demain,
        date_end=(date.today() + timedelta(days=20)).isoformat(),
        venue_name="Théâtre du Chapiteau",
        venue_address="14 rue des Écoles",
        venue_city="Créteil",
        venue_postal_code="94000",
        category="Spectacle",
    )
    base.update(extra)
    return ExtractedEvent(**base)


def test_un_run_sur_de_vraies_pages_rend_les_sorties_attendues(log):
    """Le run de référence : l'agenda est dépouillé, ses fiches sont soumises."""
    pages = by_url()
    provider = ProviderScripte(
        [FoundPage(url=AGENDA, title="Agenda du Département", kind="agenda")],
        {SPECTACLE: fiche("Le Petit Prince"), ATELIER: fiche("Atelier cirque en famille")},
    )
    # L'agenda mène à douze fiches ; seules deux ont été capturées, les autres
    # sont injoignables — c'est aussi ce que vaut un vrai run.
    fetcher = FakeFetcher(
        {AGENDA: pages[AGENDA],
         f"{AGENDA}le-petit-prince": pages[SPECTACLE],
         f"{AGENDA}atelier-cirque-en-famille": pages[ATELIER]}
    )
    provider.fiches = {
        f"{AGENDA}le-petit-prince": fiche("Le Petit Prince"),
        f"{AGENDA}atelier-cirque-en-famille": fiche("Atelier cirque en famille"),
    }
    api = FakeApi()

    with SeenStore() as store:
        result = run(config(), provider, store, api, log, submit=True, fetcher=fetcher)

    assert len(result.candidates) >= 10, "toutes les cartes de l'agenda deviennent candidates"
    titres = sorted(payload["title"] for payload in api.created)
    assert titres == ["Atelier cirque en famille", "Le Petit Prince"]

    # Les pages injoignables sont comptées, jamais fatales.
    assert result.summary.errors == 10


def test_une_fiche_trouvee_directement_est_lue_telle_quelle(log):
    """La recherche tombe sur la fiche elle-même : elle saute agenda et tri."""
    pages = by_url()
    provider = ProviderScripte(
        [FoundPage(url=SPECTACLE, title="Le Petit Prince", kind="sortie")],
        {SPECTACLE: fiche("Le Petit Prince")},
    )
    api = FakeApi()

    with SeenStore() as store:
        fetcher = FakeFetcher({SPECTACLE: pages[SPECTACLE]})
        result = run(config(), provider, store, api, log, submit=True, fetcher=fetcher)

    assert provider.extracted == [SPECTACLE]
    assert result.summary.submitted == 1
    # Ni dépouillement ni tri : une seule page téléchargée, la sienne.
    assert fetcher.asked == [SPECTACLE]
    # L'affiche vient du HTML, jamais du modèle : lui ne voit que du texte.
    assert result.events[0]["photo_url"].endswith("petit-prince-affiche.jpg")


def config(**overrides) -> Config:
    base = dict(
        name="golden",
        theme="spectacles jeune public",
        postal_prefixes=["94"],
        blocked_domains=["facebook.com"],
    )
    base.update(overrides)
    return Config(**base)
