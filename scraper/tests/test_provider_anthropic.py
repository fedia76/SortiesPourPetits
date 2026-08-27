"""Forme des requêtes envoyées à l'API Claude, vérifiée hors ligne.

Le SDK est branché sur un serveur HTTP local qui enregistre les corps reçus et
renvoie des réponses préparées. Ça verrouille ce que le fournisseur envoie
réellement (outils serveur, format structuré) et sa façon de reprendre un tour
mis en pause, sans dépenser un jeton ni dépendre du réseau.
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
                body = json.dumps(
                    outer.responses.pop(0) if outer.responses else message([text_block(CANDIDATES)])
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
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
    server = FakeApiServer([message([text_block(CANDIDATES)])])
    try:
        candidates = provider_for(server).discover(Config(name="t", theme="spectacles"), log)
    finally:
        server.close()

    assert [c.url for c in candidates] == ["https://exemple.fr/a"]
    body = server.requests[0]
    assert [t["type"] for t in body["tools"]] == ["web_search_20260209", "web_fetch_20260209"]
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["tools"][0]["blocked_domains"]  # les domaines bloqués sont transmis
    assert body["system"]


def test_reprise_apres_pause_turn(log):
    paused = message(
        [{"type": "server_tool_use", "id": "srv_1", "name": "web_search", "input": {"query": "spectacle enfant"}}],
        stop_reason="pause_turn",
    )
    server = FakeApiServer([paused, message([text_block(CANDIDATES)])])
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
    # Tarif Opus 5 : 1000 jetons d'entrée et 100 de sortie.
    assert provider.usage.cost_usd == pytest.approx(1000 * 5 / 1e6 + 100 * 25 / 1e6)


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
    assert [t["type"] for t in body["tools"]] == ["web_fetch_20260209"]
    assert "https://exemple.fr/a" in body["messages"][0]["content"]
