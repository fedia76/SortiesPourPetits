"""Forme des requêtes envoyées à l'API Claude, vérifiée hors ligne.

Le SDK est branché sur un serveur HTTP local qui enregistre les corps reçus et
rejoue des réponses préparées, en SSE puisque le fournisseur travaille en
streaming. Ça verrouille ce que le fournisseur envoie réellement (outils
serveur, format structuré, raisonnement), sa façon de reprendre un tour mis en
pause, et surtout qu'aucun des trois appels ne dépasse ce qu'il doit faire :
la recherche est le seul à recevoir un outil, la sélection ne rend que des
numéros, l'extraction reçoit sa page en clair. Sans dépenser un jeton ni
dépendre du réseau.
"""

from __future__ import annotations

import io
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

anthropic = pytest.importorskip("anthropic")

from sortiesbot.config import Config
from sortiesbot.harvest import Link
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


AGENDAS = {"pages": [{"url": "https://agenda.fr/jeune-public/", "title": "Agenda 92",
                      "kind": "agenda", "reason": "liste des spectacles"}]}


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
                    outer.responses.pop(0) if outer.responses else message([text_block(AGENDAS)])
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


def test_la_recherche_ne_recoit_que_web_search(log):
    server = FakeApiServer(
        [message(search_for("https://agenda.fr/jeune-public/") + [text_block(AGENDAS)])]
    )
    try:
        agendas = provider_for(server).search(Config(name="t", theme="spectacles"), log)
    finally:
        server.close()

    assert [a.url for a in agendas] == ["https://agenda.fr/jeune-public/"]
    assert agendas[0].is_agenda
    body = server.requests[0]
    # Un seul outil, et la variante de base : on ne fait plus lire de pages au
    # modèle, le filtrage dynamique n'a plus d'objet.
    assert [t["type"] for t in body["tools"]] == ["web_search_20250305"]
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["stream"] is True


def test_une_sortie_trouvee_directement_est_classee_comme_telle(log):
    page = {"pages": [{"url": "https://agenda.fr/jeune-public/", "title": "Un spectacle",
                       "kind": "sortie", "reason": "page d'événement"}]}
    server = FakeApiServer(
        [message(search_for("https://agenda.fr/jeune-public/") + [text_block(page)])]
    )
    try:
        pages = provider_for(server).search(Config(name="t", theme="x"), log)
    finally:
        server.close()

    assert pages[0].kind == "sortie"
    assert not pages[0].is_agenda


def test_agenda_invente_est_rejete():
    """Le modèle propose une page qu'aucune recherche n'a remontée."""
    stream = io.StringIO()
    log = RunLog(path=None, verbose=True, stream=stream)
    invente = {"pages": [
        {"url": "https://agenda.fr/jeune-public/", "title": "vu", "kind": "agenda", "reason": ""},
        {"url": "https://paris.fr/listing/9475", "title": "inventé", "kind": "agenda", "reason": ""},
    ]}
    server = FakeApiServer(
        [message(search_for("https://agenda.fr/jeune-public/") + [text_block(invente)])]
    )
    try:
        agendas = provider_for(server).search(Config(name="t", theme="x"), log)
    finally:
        server.close()

    assert [a.url for a in agendas] == ["https://agenda.fr/jeune-public/"]
    assert "absente des résultats" in stream.getvalue()


def test_reponse_de_memoire_sans_aucune_recherche_est_rejetee():
    stream = io.StringIO()
    log = RunLog(path=None, verbose=True, stream=stream)
    server = FakeApiServer([message([text_block(AGENDAS)])])
    try:
        agendas = provider_for(server).search(Config(name="t", theme="x"), log)
    finally:
        server.close()

    assert agendas == []
    assert "aucune recherche lancée" in stream.getvalue()


def test_la_selection_ne_rend_que_des_numeros(log):
    """Le modèle choisit par index : il ne peut pas inventer d'URL, et sa
    réponse tient en quelques jetons."""
    liens = [
        Link(text="Le Petit Chaperon", url="https://agenda.fr/a.html", context="le 30 août"),
        Link(text="Newsletter", url="https://agenda.fr/b.html", context=""),
        Link(text="Simon le saumon", url="https://agenda.fr/c.html", context="jusqu'au 23 oct."),
    ]
    server = FakeApiServer([message([text_block({"kept": [1, 3]})])])
    try:
        gardes = provider_for(server).select(
            "https://agenda.fr/jeune-public/", liens, Config(name="t", theme="x"), log
        )
    finally:
        server.close()

    assert [l.url for l in gardes] == ["https://agenda.fr/a.html", "https://agenda.fr/c.html"]
    body = server.requests[0]
    assert "tools" not in body  # aucun outil : aucune boucle serveur possible
    # Les liens partent avec leur contexte, numérotés.
    assert "1. Le Petit Chaperon | le 30 août" in body["messages"][0]["content"]


def test_la_selection_ignore_les_numeros_hors_bornes(log):
    liens = [Link(text="Un spectacle", url="https://agenda.fr/a.html", context="")]
    server = FakeApiServer([message([text_block({"kept": [1, 7, -2]})])])
    try:
        gardes = provider_for(server).select("https://agenda.fr/x", liens,
                                             Config(name="t", theme="x"), log)
    finally:
        server.close()
    assert [l.url for l in gardes] == ["https://agenda.fr/a.html"]


def test_extraction_recoit_la_page_en_clair(log):
    fiche = {
        "relevant": True, "skip_reason": "", "title": "Spectacle",
        "description": "Une belle description de spectacle pour enfants.",
        "free": True, "price": None, "age_min": 3, "age_max": 8,
        "permanent": False, "date_start": "2026-09-01", "date_end": "2026-09-02",
        "open_time": "10:00", "close_time": "12:00", "setting": "INDOOR",
        "category": "Spectacle", "venue_name": "Théâtre", "venue_address": "1 rue A",
        "venue_city": "Paris", "venue_postal_code": "75001",
        "photo_url": "https://exemple.fr/p.jpg",
    }
    server = FakeApiServer([message([text_block(fiche)])])
    try:
        event = provider_for(server).extract(
            "https://exemple.fr/a", "Le contenu réel de la page.",
            Config(name="t", theme="x"), ["Spectacle"], log
        )
    finally:
        server.close()

    assert event.relevant and event.age_min == 3 and event.setting == "INDOOR"
    body = server.requests[0]
    assert "tools" not in body
    contenu = body["messages"][0]["content"]
    assert "Le contenu réel de la page." in contenu
    assert "https://exemple.fr/a" in contenu


def test_reprise_apres_pause_turn(log):
    paused = message(
        [{"type": "server_tool_use", "id": "srv_1", "name": "web_search",
          "input": {"query": "spectacle enfant"}}],
        stop_reason="pause_turn",
    )
    server = FakeApiServer(
        [paused, message(search_for("https://agenda.fr/jeune-public/") + [text_block(AGENDAS)])]
    )
    try:
        agendas = provider_for(server).search(Config(name="t", theme="spectacles"), log)
    finally:
        server.close()

    assert len(agendas) == 1
    assert len(server.requests) == 2
    assert [m["role"] for m in server.requests[1]["messages"]] == ["user", "assistant"]


def test_journal_des_recherches():
    stream = io.StringIO()
    log = RunLog(path=None, verbose=True, stream=stream)
    server = FakeApiServer(
        [message(search_for("https://agenda.fr/jeune-public/") + [text_block(AGENDAS)])]
    )
    try:
        provider = provider_for(server)
        provider.search(Config(name="t", theme="spectacles"), log)
    finally:
        server.close()

    console = stream.getvalue()
    assert "spectacle enfant" in console
    assert "https://agenda.fr/jeune-public/" in console
    assert provider.usage.web_searches == 1
    assert provider.usage.search_cost_usd == pytest.approx(0.01)
    # Tarif Haiku 4.5 (1 $ / 5 $ le million) sur 1000 entrée et 100 sortie.
    assert provider.usage.cost_usd == pytest.approx(1000 * 1 / 1e6 + 100 * 5 / 1e6)


def test_erreur_de_recherche_est_journalisee():
    stream = io.StringIO()
    log = RunLog(path=None, verbose=True, stream=stream)
    response = message([
        {"type": "web_search_tool_result", "tool_use_id": "s1",
         "content": {"type": "web_search_tool_result_error", "error_code": "max_uses_exceeded"}},
        text_block(AGENDAS),
    ])
    server = FakeApiServer([response])
    try:
        provider_for(server).search(Config(name="t", theme="x"), log)
    finally:
        server.close()

    assert "max_uses_exceeded" in stream.getvalue()
