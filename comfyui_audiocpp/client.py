"""HTTP client for an audiocpp_server running on this computer (the default server runtime, loopback only).

Only 127.0.0.1 is reachable: a workflow chooses the port, never a host or URL, so a shared workflow cannot make ComfyUI connect
anywhere else. http.client does not follow redirects or read proxy settings, and nothing here starts, stops or downloads anything.
"""

from __future__ import annotations

import http.client
import json
import socket
import threading
from dataclasses import dataclass
from typing import Callable

HOST = "127.0.0.1"
# The server's limit for an inline base64 voice_ref (app/server/server_protocol.cpp).
MAX_VOICE_REF_BYTES = 5 * 1024 * 1024


class AudioCPPError(RuntimeError):
    """The request did not produce a result; the message says why and what to check."""


class ServerError(AudioCPPError):
    """The server answered with an error response."""

    def __init__(self, status: int, message: str, kind: str):
        super().__init__(f"audio.cpp server error {status} ({kind}): {message}")
        self.status = status
        self.message = message
        self.kind = kind


@dataclass(frozen=True)
class Server:
    port: int
    timeout: float

    def __post_init__(self):
        if not isinstance(self.port, int) or not 1 <= self.port <= 65535:
            raise ValueError(f"port must be an integer from 1 to 65535, not {self.port!r}")
        if not self.timeout > 0:
            raise ValueError(f"timeout must be positive, not {self.timeout!r}")

    @property
    def address(self) -> str:
        return f"http://{HOST}:{self.port}"


def _exchange(server: Server, method: str, path: str, body: bytes | None, conn_box: list) -> tuple[int, dict, bytes]:
    conn = http.client.HTTPConnection(HOST, server.port, timeout=server.timeout)
    conn_box.append(conn)
    try:
        headers = {"Content-Type": "application/json"} if body is not None else {}
        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        return response.status, {k.lower(): v for k, v in response.getheaders()}, response.read()
    finally:
        conn.close()


def _describe(server: Server, error: BaseException) -> str:
    if isinstance(error, ConnectionRefusedError):
        return (f"no audio.cpp server is listening on {server.address} (connection refused). Start audiocpp_server with "
                f"--port {server.port} on this computer, or set the port of the audio.cpp Server node to the one it uses.")
    if isinstance(error, (TimeoutError, socket.timeout)):
        return (f"the audio.cpp server on {server.address} did not answer within {server.timeout:g} s. A first request also loads "
                f"the model; raise the timeout of the audio.cpp Server node for long generations.")
    if isinstance(error, (ConnectionResetError, ConnectionAbortedError, http.client.RemoteDisconnected, http.client.IncompleteRead)):
        return f"the audio.cpp server on {server.address} closed the connection before answering; check that it is still running and read its log."
    return f"could not talk to the audio.cpp server on {server.address}: {error}"


def request(server: Server, method: str, path: str, payload: dict | None = None,
            check_interrupt: Callable[[], None] | None = None, poll: float = 0.1) -> tuple[int, dict, bytes]:
    """Send one request and return (status, lower-case headers, body); raise AudioCPPError for a failed exchange or an error status.

    The exchange runs on a worker thread so that `check_interrupt` (ComfyUI's interrupt check) can raise while the server works.
    The server finishes a generation it has started either way: its legacy runtime has no cancel request.
    """
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    result: dict = {}
    conn_box: list = []

    def work():
        try:
            result["value"] = _exchange(server, method, path, body, conn_box)
        except BaseException as error:  # noqa: BLE001 - handed to the caller's thread below
            result["error"] = error

    worker = threading.Thread(target=work, name="audiocpp-request", daemon=True)
    worker.start()
    try:
        while worker.is_alive():
            worker.join(poll)
            if check_interrupt is not None and worker.is_alive():
                check_interrupt()
    except BaseException:
        for conn in conn_box:
            conn.close()
        raise
    if "error" in result:
        raise AudioCPPError(_describe(server, result["error"])) from result["error"]
    status, headers, data = result["value"]
    if status != 200:
        raise _error(server, status, headers, data)
    return status, headers, data


def _error(server: Server, status: int, headers: dict, data: bytes) -> AudioCPPError:
    if 300 <= status < 400:
        return AudioCPPError(f"the audio.cpp server on {server.address} answered with a redirect ({status}), which is not followed.")
    try:
        error = json.loads(data.decode("utf-8"))["error"]
        return ServerError(status, str(error.get("message", "")), str(error.get("type", "")))
    except (ValueError, KeyError, TypeError, AttributeError):
        text = data[:500].decode("utf-8", "replace").strip()
        return ServerError(status, text or "(empty response)", "unknown")


def _json(server: Server, path: str, check_interrupt=None):
    _, headers, data = request(server, "GET", path, check_interrupt=check_interrupt)
    try:
        return json.loads(data.decode("utf-8"))
    except ValueError as error:
        raise AudioCPPError(f"the server on {server.address} did not answer {path} with JSON; is it an audiocpp_server?") from error


def health(server: Server, check_interrupt=None) -> dict:
    """GET /health: {"status", "backend", "models", "ui", "ui_management"}."""
    return _json(server, "/health", check_interrupt)


def models(server: Server, check_interrupt=None) -> list[dict]:
    """GET /v1/models: the configured entries (id, family, task, mode, device, loaded, configured, path)."""
    return list(_json(server, "/v1/models", check_interrupt).get("data", []))


def speech(server: Server, payload: dict, check_interrupt=None) -> tuple[bytes, dict]:
    """POST /v1/audio/speech: the WAV bytes and the response headers (X-AudioCPP-Wall-Ms, -Audio-Duration-Ms, -RTF)."""
    _, headers, data = request(server, "POST", "/v1/audio/speech", payload, check_interrupt)
    if not data.startswith(b"RIFF"):
        raise AudioCPPError(f"the server on {server.address} answered /v1/audio/speech with {headers.get('content-type')}, not a WAV file.")
    return data, headers
