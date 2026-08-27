"""Forme des requêtes envoyées à l'API Claude, vérifiée hors ligne.

Le SDK est branché sur un serveur HTTP local qui enregistre les corps reçus et
rejoue des réponses préparées, en SSE puisque le fournisseur travaille en
streaming. Ça verrouille ce que le fournisseur envoie réellement (outils
serveur, format structuré, raisonnement), sa façon de reprendre un tour mis en
pause, et surtout le fait que les recherches sont journalisées **pendant**
l'appel et non à la fin — sans dépenser un jeton ni dépendre du réseau.
"""

from __future__ import annotations

import io
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

anthropic = pytest.importorskip("anthropic")

from sortiesbot.config import Config
from sortiesbot.journal import RunLog
from sortiesbot.providers.anthropic_provider import AnthropicProvider


def message(content: list[dict], stop_reason: str = "end_turn") -> dict:
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5",
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 1000, "output_tokens": 100},
    }


def text_block(payload: dict) -> dict:
    return {"type": "text", "text": json.dumps(payload)}


CANDIDATES = {"candidates": [{"url": "https://exemple.fr/a", "title": "A", "city": "Paris", "reason": "ok"}]}


def search_for(*urls: str, tool_use_id: str = "s1") -> list[dict]:
    """Une recherche et ses résultats : le modèle a vraiment vu ces URL."""
    return [
        {"type": "server_tool_use", "id": tool_use_id, "name": "web_search",
         "input": {"query": "spectacle enfant"}},
        {"type": "web_search_tool_result", "tool_use_id": tool_use_id,
         "content": [
             {"type": "web_search_result", "url": u, "title": u,
              "encrypted_content": "x", "page_age": None}
             for u in urls
         ]},
    ]


def sse(message: dict) -> bytes:
    """Sérialise un message en flux d'événements, comme le fait l'API."""
    lines: list[str] = []

    def emit(payload: dict) -> None:
        lines.append(f"event: {payload['type']}\ndata: {json.dumps(payload)}\n\n")

    opening = {**message, "content": [], "stop_reason": None}
    emit({"type": "message_start", "message": opening})

    for index, block in enumerate(message["content"]):
        kind = block["type"]
        if kind == "text":
            emit({"type": "content_block_start", "index": index,
                  "content_block": {"type": "text", "text": ""}})
            emit({"type": "content_block_delta", "index": index,
                  "delta": {"type": "text_delta", "text": block["text"]}})
        elif kind == "thinking":
            emit({"type": "content_block_start", "index": index,
                  "content_block": {"type": "thinking", "thinking": "", "signature": ""}})
            emit({"type": "content_block_delta", "index": index,
                  "delta": {"type": "thinking_delta", "thinking": block["thinking"]}})
            emit({"type": "content_block_delta", "index": index,
                  "delta": {"type": "signature_delta", "signature": "sig"}})
        elif kind == "server_tool_use":
            emit({"type": "content_block_start", "index": index,
                  "content_block": {**block, "input": {}}})
            emit({"type": "content_block_delta", "index": index,
                  "delta": {"type": "input_json_delta",
                            "partial_json": json.dumps(block["input"])}})
        else:
            # Les résultats d'outils serveur arrivent d'un bloc.
            emit({"type": "content_block_start", "index": index, "content_block": block})
        emit({"type": "content_block_stop", "index": index})

    emit({"type": "message_delta",
          "delta": {"stop_reason": message["stop_reason"], "stop_sequence": None},
          "usage": {"output_tokens": message["usage"]["output_tokens"]}})
    emit({"type": "message_stop"})
    return "".join(lines).encode()


class FakeApiServer:
    """Sert les réponses dans l'ordre et garde une trace des requêtes."""

    def __init__(self, responses: list[dict]):
        self.responses = list(responses)
        self.requests: list[dict] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 - imposé par BaseHTTPRequestHandler
                length = int(self.headers.get("Content-Length", 0))
                outer.requests.append(json.loads(self.rfile.read(length)))
                body = sse(
                    outer.responses.pop(0) if outer.responses else message([text_block(CANDIDATES)])
                )
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture
def log():
    return RunLog(path=None, verbose=False, stream=io.StringIO())


def provider_for(server: FakeApiServer) -> AnthropicProvider:
    client = anthropic.Anthropic(api_key="test", base_url=server.url, max_retries=0)
    return AnthropicProvider(client=client)


def test_forme_de_la_requete_de_decouverte(log):
    server = FakeApiServer(
        [message(search_for("https://exemple.fr/a") + [text_block(CANDIDATES)])]
    )
    config = Config(name="t", theme="spectacles", discovery_model="claude-opus-5")
    try:
        candidates = provider_for(server).discover(config, log)
    finally:
        server.close()

    assert [c.url for c in candidates] == ["https://exemple.fr/a"]
    body = server.requests[0]
    assert [t["type"] for t in body["tools"]] == ["web_search_20260209", "web_fetch_20260209"]
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["tools"][0]["blocked_domains"]  # les domaines bloqués sont transmis
    assert body["system"]
    # Streaming obligatoire : un tour de découverte dure plusieurs minutes.
    assert body["stream"] is True
    assert body["thinking"] == {"type": "adaptive", "display": "summarized"}


def test_reprise_apres_pause_turn(log):
    paused = message(
        [{"type": "server_tool_use", "id": "srv_1", "name": "web_search", "input": {"query": "spectacle enfant"}}],
        stop_reason="pause_turn",
    )
    server = FakeApiServer(
        [paused, message(search_for("https://exemple.fr/a") + [text_block(CANDIDATES)])]
    )
    try:
        candidates = provider_for(server).discover(Config(name="t", theme="spectacles"), log)
    finally:
        server.close()

    assert len(candidates) == 1
    assert len(server.requests) == 2
    # La reprise renvoie le tour en cours, sans message utilisateur ajouté.
    roles = [m["role"] for m in server.requests[1]["messages"]]
    assert roles == ["user", "assistant"]


def test_journal_des_recherches_et_des_pages(log):
    stream = io.StringIO()
    log = RunLog(path=None, verbose=True, stream=stream)
    response = message(
        [
            {"type": "server_tool_use", "id": "s1", "name": "web_search", "input": {"query": "spectacle enfant Paris"}},
            {
                "type": "web_search_tool_result",
                "tool_use_id": "s1",
                "content": [
                    {
                        "type": "web_search_result",
                        "url": "https://exemple.fr/agenda",
                        "title": "Agenda",
                        "encrypted_content": "x",
                        "page_age": None,
                    }
                ],
            },
            {"type": "server_tool_use", "id": "f1", "name": "web_fetch", "input": {"url": "https://exemple.fr/agenda"}},
            text_block(CANDIDATES),
        ]
    )
    server = FakeApiServer([response])
    try:
        provider = provider_for(server)
        provider.discover(Config(name="t", theme="spectacles"), log)
    finally:
        server.close()

    console = stream.getvalue()
    assert "spectacle enfant Paris" in console
    assert "https://exemple.fr/agenda" in console
    assert provider.usage.web_searches == 1
    assert provider.usage.web_fetches == 1
    # Tarif du modèle de découverte par défaut (Sonnet 5, 2 $ / 10 $ le
    # million) sur 1000 jetons d'entrée et 100 de sortie…
    assert provider.usage.cost_usd == pytest.approx(1000 * 2 / 1e6 + 100 * 10 / 1e6)
    # …plus la recherche web, facturée à part (0,01 $ pièce).
    assert provider.usage.search_cost_usd == pytest.approx(0.01)
    assert provider.usage.total_usd == pytest.approx(provider.usage.cost_usd + 0.01)


def test_page_refusee_est_nommee_et_ne_compte_pas_comme_lue():
    """Une page bloquée par robots.txt consomme le quota sans rien rapporter :
    le journal doit dire laquelle, et ne pas la compter comme lue."""
    stream = io.StringIO()
    log = RunLog(path=None, verbose=True, stream=stream)
    response = message(
        [
            {"type": "server_tool_use", "id": "f1", "name": "web_fetch",
             "input": {"url": "https://interdit.fr/agenda"}},
            {"type": "web_fetch_tool_result", "tool_use_id": "f1",
             "content": {"type": "web_fetch_tool_result_error", "error_code": "url_not_allowed"}},
            {"type": "server_tool_use", "id": "f2", "name": "web_fetch",
             "input": {"url": "https://ouvert.fr/agenda"}},
            {"type": "web_fetch_tool_result", "tool_use_id": "f2",
             "content": {"type": "web_fetch_result", "url": "https://ouvert.fr/agenda",
                         "content": {"type": "document",
                                     "source": {"type": "text", "media_type": "text/plain",
                                                "data": "des liens"}},
                         "retrieved_at": "2026-08-27T10:00:00Z"}},
            text_block(CANDIDATES),
        ]
    )
    server = FakeApiServer([response])
    try:
        provider = provider_for(server)
        provider.discover(Config(name="t", theme="x"), log)
    finally:
        server.close()

    console = stream.getvalue()
    assert "url_not_allowed" in console
    assert "https://interdit.fr/agenda" in console  # la page fautive est nommée
    assert provider.usage.web_fetches == 2  # deux tentatives, deux quotas consommés
    assert provider.usage.pages_read == 1  # mais une seule page réellement lue


def test_url_inventee_est_rejetee():
    """Le modèle renvoie une URL qu'aucune recherche n'a remontée : c'est un
    souvenir, presque toujours mort. On ne paiera pas une extraction dessus."""
    stream = io.StringIO()
    log = RunLog(path=None, verbose=True, stream=stream)
    inventee = {"candidates": [
        {"url": "https://exemple.fr/a", "title": "vue", "city": "", "reason": ""},
        {"url": "https://paris.fr/listing/9475", "title": "inventée", "city": "", "reason": ""},
    ]}
    server = FakeApiServer(
        [message(search_for("https://exemple.fr/a") + [text_block(inventee)])]
    )
    try:
        candidates = provider_for(server).discover(Config(name="t", theme="x"), log)
    finally:
        server.close()

    assert [c.url for c in candidates] == ["https://exemple.fr/a"]
    assert "inventée par le modèle" in stream.getvalue()


def test_reponse_de_memoire_sans_aucune_recherche_est_rejetee():
    """Zéro recherche, zéro page : tout ce que le modèle propose vient de sa
    mémoire. On jette le lot plutôt que de payer des extractions."""
    stream = io.StringIO()
    log = RunLog(path=None, verbose=True, stream=stream)
    server = FakeApiServer([message([text_block(CANDIDATES)])])
    try:
        candidates = provider_for(server).discover(Config(name="t", theme="x"), log)
    finally:
        server.close()

    assert candidates == []
    assert "aucune recherche lancée" in stream.getvalue()


def test_lien_trouve_dans_une_page_ouverte_est_accepte():
    """Une page d'événement repérée DANS un agenda ouvert est exactement ce
    qu'on cherche : le filtre ne doit pas la confondre avec une invention."""
    stream = io.StringIO()
    log = RunLog(path=None, verbose=True, stream=stream)
    dans_la_page = {"candidates": [
        {"url": "https://theatre.fr/le-petit-chaperon", "title": "Spectacle", "city": "", "reason": ""},
    ]}
    server = FakeApiServer([message(
        search_for("https://agenda.fr/week-end")
        + [
            {"type": "server_tool_use", "id": "f1", "name": "web_fetch",
             "input": {"url": "https://agenda.fr/week-end"}},
            {"type": "web_fetch_tool_result", "tool_use_id": "f1",
             "content": {"type": "web_fetch_result", "url": "https://agenda.fr/week-end",
                         "content": {"type": "document",
                                     "source": {"type": "text", "media_type": "text/plain",
                                                "data": "Au programme : "
                                                        "https://theatre.fr/le-petit-chaperon"}},
                         "retrieved_at": "2026-08-27T10:00:00Z"}},
            text_block(dans_la_page),
        ]
    )])
    try:
        candidates = provider_for(server).discover(Config(name="t", theme="x"), log)
    finally:
        server.close()

    assert [c.url for c in candidates] == ["https://theatre.fr/le-petit-chaperon"]


def test_erreur_doutil_serveur_est_journalisee():
    stream = io.StringIO()
    log = RunLog(path=None, verbose=True, stream=stream)
    response = message(
        [
            {
                "type": "web_search_tool_result",
                "tool_use_id": "s1",
                "content": {"type": "web_search_tool_result_error", "error_code": "max_uses_exceeded"},
            },
            text_block(CANDIDATES),
        ]
    )
    server = FakeApiServer([response])
    try:
        provider_for(server).discover(Config(name="t", theme="spectacles"), log)
    finally:
        server.close()

    assert "max_uses_exceeded" in stream.getvalue()


def test_raisonnement_journalise_pendant_lappel():
    """Le résumé du raisonnement est écrit au fil de l'eau : c'est ce qui
    montre que le run avance pendant les minutes d'attente."""
    stream = io.StringIO()
    log = RunLog(path=None, verbose=True, stream=stream)
    response = message(
        [
            {
                "type": "thinking",
                "thinking": "Je vais couvrir les huit départements franciliens.\n"
                "Puis j'ouvrirai les agendas trouvés pour en tirer des liens.\n",
                "signature": "sig",
            },
            text_block(CANDIDATES),
        ]
    )
    server = FakeApiServer([response])
    try:
        provider_for(server).discover(Config(name="t", theme="spectacles"), log)
    finally:
        server.close()

    console = stream.getvalue()
    assert "huit départements franciliens" in console
    # Et le raisonnement précède le décompte de jetons de fin de tour.
    assert console.index("départements") < console.index("jetons")


def test_outils_et_thinking_suivent_le_modele(log):
    """Le filtrage dynamique et `thinking: adaptive` réclament un modèle 4.6+ :
    sur Haiku, il faut les variantes de base et pas de `thinking`, sinon
    l'API répond 400."""
    server = FakeApiServer([message([text_block(CANDIDATES)])])
    config = Config(name="t", theme="x", discovery_model="claude-haiku-4-5")
    try:
        provider_for(server).discover(config, log)
    finally:
        server.close()

    body = server.requests[0]
    assert [t["type"] for t in body["tools"]] == ["web_search_20250305", "web_fetch_20250910"]
    assert "thinking" not in body


def test_extraction_lit_une_url_precise(log):
    extraction = {
        "relevant": True,
        "skip_reason": "",
        "title": "Spectacle",
        "description": "Une belle description de spectacle pour enfants.",
        "free": True,
        "price": None,
        "age_min": 3,
        "age_max": 8,
        "permanent": False,
        "date_start": "2026-09-01",
        "date_end": "2026-09-02",
        "open_time": "10:00",
        "close_time": "12:00",
        "setting": "INDOOR",
        "category": "Spectacle",
        "venue_name": "Théâtre",
        "venue_address": "1 rue A",
        "venue_city": "Paris",
        "venue_postal_code": "75001",
        "photo_url": "https://exemple.fr/p.jpg",
    }
    server = FakeApiServer([message([text_block(extraction)])])
    try:
        event = provider_for(server).extract(
            "https://exemple.fr/a", Config(name="t", theme="x"), ["Spectacle"], log
        )
    finally:
        server.close()

    assert event.relevant and event.age_min == 3 and event.setting == "INDOOR"
    body = server.requests[0]
    # L'extraction tourne sur Haiku par défaut : variante de base obligatoire.
    assert [t["type"] for t in body["tools"]] == ["web_fetch_20250910"]
    assert "https://exemple.fr/a" in body["messages"][0]["content"]
