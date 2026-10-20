"""Test setup: ComfyUI on the import path (for comfy_api), a fake audiocpp_server, and the optional real one.

AUDIOCPP_COMFYUI_DIR: a ComfyUI checkout (required for the node tests).
AUDIOCPP_TEST_PORT: the port of a running audiocpp_server with the models of tests/test_real_server.py (optional).
"""

import io
import json
import os
import sys
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
COMFYUI = os.environ.get("AUDIOCPP_COMFYUI_DIR")
if COMFYUI:
    sys.path.insert(0, COMFYUI)
    import comfy.options

    comfy.options.enable_args_parsing(False)


def make_wav(seconds=0.5, rate=24000, channels=1):
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = int(seconds * rate)
        w.writeframes(b"".join(int(8000 * ((i % 48) / 24 - 1)).to_bytes(2, "little", signed=True) * channels for i in range(frames)))
    return out.getvalue()


MODELS = [
    {"id": "tts-a", "object": "model", "family": "pocket_tts", "task": "tts", "mode": "offline", "device": 0, "loaded": False, "configured": True},
    {"id": "asr-b", "object": "model", "family": "qwen3_asr", "task": "asr", "mode": "offline", "device": 0, "loaded": True, "configured": True},
]


class FakeServer:
    """A stand-in for audiocpp_server with the legacy runtime's response shapes; records the requests it gets."""

    def __init__(self):
        self.requests = []
        self.models = list(MODELS)
        self.delay = 0.0
        self.speech_status = 200
        self.speech_body = None
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, status, body, content_type="application/json", headers=None):
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                fake.requests.append(("GET", self.path, None))
                if self.path == "/health":
                    self.reply(200, json.dumps({"status": "ok", "backend": "cpu", "models": len(fake.models), "ui": False, "ui_management": False}).encode())
                elif self.path == "/v1/models":
                    self.reply(200, json.dumps({"object": "list", "data": fake.models}).encode())
                else:
                    self.reply(404, json.dumps({"error": {"message": f"unknown endpoint: {self.path}", "type": "not_found"}}).encode())

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.requests.append(("POST", self.path, body))
                time.sleep(fake.delay)
                if self.path != "/v1/audio/speech":
                    self.reply(404, b'{"error":{"message":"unknown endpoint","type":"not_found"}}')
                elif fake.speech_body is not None:
                    self.reply(fake.speech_status, fake.speech_body, headers={"Location": "http://127.0.0.1:1/"} if 300 <= fake.speech_status < 400 else None)
                elif body["model"] not in {m["id"] for m in fake.models}:
                    self.reply(500, json.dumps({"error": {"message": f"unknown model id: {body['model']}", "type": "server_error"}}).encode())
                else:
                    self.reply(200, make_wav(), "audio/wav", {"X-AudioCPP-Wall-Ms": "12.5", "X-AudioCPP-RTF": "0.025"})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def fake():
    server = FakeServer()
    yield server
    server.close()


@pytest.fixture
def nodes():
    if not COMFYUI:
        pytest.skip("set AUDIOCPP_COMFYUI_DIR to a ComfyUI checkout")
    from comfyui_audiocpp import nodes

    return nodes


def free_port():
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def result(output):
    return output.result if hasattr(output, "result") else output
