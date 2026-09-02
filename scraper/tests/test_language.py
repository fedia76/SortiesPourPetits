"""La version française d'une page, quand le site en publie une.

Un moteur remonte volontiers l'adresse anglaise d'un site francophone. La
sortie est la même, mais elle arriverait sur le site avec une description en
anglais et un lien que les parents n'attendaient pas.

Deux choses se vérifient ici :

* la reconnaissance de la langue — ce que la page déclare, et à défaut ce que
  son texte trahit ;
* la retenue — on ne bouge que si la page se dit anglaise ou si son adresse
  l'annonce, et seulement vers une page qui répond **et** qui est française.
  Le reste du temps, pas une requête n'est lancée.
"""

from __future__ import annotations

import io

import pytest

from sortiesbot.harvest import FetchError
from sortiesbot.journal import RunLog
from sortiesbot.language import (
    candidates,
    declared_language,
    english_url,
    french_alternates,
    french_version,
    language_of,
    text_language,
)
from sortiesbot.models import FoundPage
from sortiesbot.orchestrator import run
from sortiesbot.store import SeenStore

from test_pipeline import FakeApi, FakeFetcher, FakeProvider, config, sortie

EN_URL = "https://www.musee-exemple.fr/en/whats-on/dinosaur-workshop"
FR_URL = "https://www.musee-exemple.fr/fr/agenda/atelier-dinosaures"

CORPS_FR = """
<h1>Atelier dinosaures</h1>
<p>Le musée propose aux enfants de six à dix ans un atelier pour découvrir les
dinosaures et le travail des paléontologues. Les enfants moulent une empreinte
de fossile et repartent avec, et les parents sont invités à rester avec eux
pendant toute la séance. L'atelier a lieu tous les mercredis à quinze heures
dans la salle pédagogique du musée, au premier étage.</p>
"""

CORPS_EN = """
<h1>Dinosaur workshop</h1>
<p>The museum invites children from six to ten years old to a workshop about
dinosaurs and the work of palaeontologists. The children make a cast of a
fossil footprint and take it home with them, and parents are welcome to stay
with them for the whole session. The workshop is held every Wednesday at three
in the afternoon in the museum's teaching room, on the first floor.</p>
"""


def page(corps: str, lang: str = "", head: str = "") -> str:
    attribut = f' lang="{lang}"' if lang else ""
    return f"<html{attribut}><head>{head}</head><body>{corps}</body></html>"


@pytest.fixture
def log():
    return RunLog(path=None, verbose=False, stream=io.StringIO())


# ------------------------------------------------------- reconnaître la langue


def test_la_langue_declaree_par_la_page():
    assert declared_language(page(CORPS_EN, lang="en-US")) == "en"
    assert declared_language(page(CORPS_FR, lang="fr")) == "fr"
    assert declared_language(page(CORPS_FR)) == ""


def test_la_langue_declaree_en_opengraph_a_defaut_de_balise_html():
    head = '<meta property="og:locale" content="en_GB">'
    assert declared_language(page(CORPS_EN, head=head)) == "en"


def test_la_langue_du_texte_quand_la_page_ne_declare_rien():
    assert text_language(page(CORPS_FR)) == "fr"
    assert text_language(page(CORPS_EN)) == "en"


def test_un_texte_trop_court_ne_dit_rien():
    """Trois mots ne prouvent pas une langue : mieux vaut ne rien conclure."""
    assert text_language(page("<p>Atelier</p>")) == ""


def test_la_declaration_prime_sur_le_texte():
    """Un site traduit son gabarit et oublie le corps : c'est la déclaration
    qui fait foi, elle est du site et non d'un décompte de mots."""
    assert language_of(page(CORPS_EN, lang="fr")) == "fr"


# ----------------------------------------------------- reconnaître une adresse


@pytest.mark.parametrize(
    "url",
    [
        "https://exemple.fr/en/agenda",
        "https://exemple.fr/EN/agenda",
        "https://exemple.fr/english/whats-on",
        "https://en.exemple.fr/agenda",
        "https://exemple.fr/agenda?lang=en",
        "https://exemple.fr/agenda?id=3&hl=en-GB",
    ],
)
def test_les_adresses_qui_annoncent_de_l_anglais(url):
    assert english_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://exemple.fr/agenda",
        "https://exemple.fr/fr/agenda",
        # « en » est ici un mot français, pas un code de langue : il n'est pas
        # un segment à lui seul.
        "https://exemple.fr/sortie-en-famille",
        "https://exemple.fr/agenda?enfant=oui",
    ],
)
def test_les_adresses_qui_nannoncent_rien(url):
    assert not english_url(url)


def test_les_adresses_candidates_dans_l_ordre():
    """La traduction déclarée d'abord, la transposition d'adresse ensuite :
    on ne devine que si le site n'a pas répondu."""
    head = f'<link rel="alternate" hreflang="fr-FR" href="{FR_URL}">'
    trouvees = candidates(EN_URL, page(CORPS_EN, lang="en", head=head))
    assert trouvees[0] == FR_URL
    assert "https://www.musee-exemple.fr/fr/whats-on/dinosaur-workshop" in trouvees


def test_l_adresse_relative_d_une_traduction_est_absolue():
    head = '<link rel="alternate" hreflang="fr" href="/fr/agenda">'
    assert french_alternates(page(CORPS_EN, head=head), EN_URL) == [
        "https://www.musee-exemple.fr/fr/agenda"
    ]


def test_la_page_elle_meme_nest_jamais_son_propre_candidat():
    """Beaucoup de sites déclarent aussi la langue de la page courante."""
    head = f'<link rel="alternate" hreflang="fr" href="{FR_URL}/">'
    assert candidates(FR_URL, page(CORPS_FR, lang="fr", head=head)) == []


# ------------------------------------------------------------- le remplacement


def test_une_page_francaise_nest_pas_touchee():
    """Et surtout : pas une requête de plus. C'est le cas de figure normal."""
    fetcher = FakeFetcher({})
    url, html = french_version(FR_URL, page(CORPS_FR, lang="fr"), fetcher)
    assert url == FR_URL
    assert fetcher.asked == []


def test_une_page_qui_ne_declare_rien_et_dont_l_adresse_ne_dit_rien_est_laissee():
    """On ne devine pas : sans signal, il n'y a pas de question posée."""
    url = "https://exemple.fr/agenda/atelier"
    fetcher = FakeFetcher({})
    rendue, _ = french_version(url, page("<p>Atelier</p>"), fetcher)
    assert rendue == url
    assert fetcher.asked == []


def test_la_traduction_declaree_est_suivie(log):
    head = f'<link rel="alternate" hreflang="fr" href="{FR_URL}">'
    anglaise = page(CORPS_EN, lang="en", head=head)
    fetcher = FakeFetcher({EN_URL: anglaise, FR_URL: page(CORPS_FR, lang="fr")})

    url, html = french_version(EN_URL, anglaise, fetcher, log)

    assert url == FR_URL
    assert "Atelier dinosaures" in html


def test_l_adresse_est_transposee_quand_le_site_ne_declare_rien():
    """`/en/` → `/fr/` : la seule invention permise, et elle est vérifiée."""
    anglaise = page(CORPS_EN, lang="en")
    francaise = page(CORPS_FR, lang="fr")
    fetcher = FakeFetcher(
        {
            EN_URL: anglaise,
            "https://www.musee-exemple.fr/fr/whats-on/dinosaur-workshop": francaise,
        }
    )

    url, _ = french_version(EN_URL, anglaise, fetcher)

    assert url == "https://www.musee-exemple.fr/fr/whats-on/dinosaur-workshop"


def test_une_transposition_qui_ne_repond_pas_ne_change_rien():
    anglaise = page(CORPS_EN, lang="en")
    fetcher = FakeFetcher({EN_URL: anglaise})

    url, html = french_version(EN_URL, anglaise, fetcher)

    assert url == EN_URL
    assert html == anglaise


def test_une_transposition_qui_rend_de_l_anglais_ne_change_rien():
    """Beaucoup de sites répondent à `/fr/` en servant l'anglais quand la
    traduction n'existe pas. Changer d'adresse pour le même contenu ne
    tromperait que nous."""
    anglaise = page(CORPS_EN, lang="en")
    fetcher = FakeFetcher(
        {
            EN_URL: anglaise,
            "https://www.musee-exemple.fr/fr/whats-on/dinosaur-workshop": anglaise,
        }
    )

    url, _ = french_version(EN_URL, anglaise, fetcher)

    assert url == EN_URL


def test_une_page_anglaise_sans_jumelle_est_signalee():
    """Elle reste lue — mieux vaut une sortie en anglais que pas de sortie —
    mais la console doit pouvoir dire pourquoi le lien est anglais."""
    evenements: list[dict] = []
    log = RunLog(path=None, verbose=False, stream=io.StringIO(), sink=evenements.append)
    anglaise = page(CORPS_EN, lang="en")

    french_version(EN_URL, anglaise, FakeFetcher({EN_URL: anglaise}), log)

    assert [e for e in evenements if e["kind"] == "no_french"]


def test_une_page_injoignable_ne_fait_pas_echouer_la_recherche():
    """`FetchError` sur un candidat est une réponse comme une autre."""

    class Cassé:
        def get_html(self, url):
            raise FetchError("page inaccessible")

    anglaise = page(CORPS_EN, lang="en")
    url, html = french_version(EN_URL, anglaise, Cassé())
    assert (url, html) == (EN_URL, anglaise)


# ------------------------------------------------------------ dans le pipeline


def test_la_sortie_est_proposee_avec_son_lien_francais(log):
    """Bout en bout : le moteur remonte l'anglais, le site propose le français.

    C'est le motif que la production montrait — des sorties correctes, mais
    dont le lien menait à une page anglaise alors que la version française
    existait juste à côté.
    """
    head = f'<link rel="alternate" hreflang="fr" href="{FR_URL}">'
    provider = FakeProvider([FoundPage(url=EN_URL, title="Dinosaur workshop")],
                            {FR_URL: sortie()})
    fetcher = FakeFetcher(
        {
            EN_URL: page(CORPS_EN, lang="en", head=head),
            FR_URL: page(CORPS_FR, lang="fr"),
        }
    )
    api = FakeApi()

    with SeenStore() as store:
        result = run(config(), provider, store, api, log, submit=True, fetcher=fetcher)

    assert provider.extracted == [FR_URL]
    assert result.summary.submitted == 1
    assert api.created[0]["sourceUrl"] == FR_URL


def test_la_page_francaise_nest_pas_relue_par_sa_porte_anglaise(log):
    """La mémoire retient l'adresse française — celle qu'on a lue et proposée.

    Sans le second passage des filtres à la lecture, le run suivant repartirait
    de l'adresse anglaise, ne la reconnaîtrait pas, et proposerait la sortie
    une seconde fois.
    """
    head = f'<link rel="alternate" hreflang="fr" href="{FR_URL}">'
    pages = {EN_URL: page(CORPS_EN, lang="en", head=head), FR_URL: page(CORPS_FR, lang="fr")}

    with SeenStore() as store:
        run(
            config(),
            FakeProvider([FoundPage(url=EN_URL)], {FR_URL: sortie()}),
            store,
            FakeApi(),
            log,
            submit=True,
            fetcher=FakeFetcher(dict(pages)),
        )
        assert store.seen(FR_URL)

        second = FakeProvider([FoundPage(url=EN_URL)], {FR_URL: sortie()})
        result = run(
            config(), second, store, FakeApi(), log, submit=True,
            fetcher=FakeFetcher(dict(pages)),
        )

    assert second.extracted == []
    assert result.summary.skipped_seen == 1
