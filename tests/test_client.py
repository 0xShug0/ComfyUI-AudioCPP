import time

import pytest
from conftest import free_port

from comfyui_audiocpp import client


def test_server_accepts_only_a_port_and_a_positive_timeout():
    assert client.Server(8080, 1.0).address == "http://127.0.0.1:8080"
    for port in (0, 65536, "8080", 80.5):
        with pytest.raises(ValueError):
            client.Server(port, 1.0)
    with pytest.raises(ValueError):
        client.Server(8080, 0)


def test_health_models_and_speech(fake):
    server = client.Server(fake.port, 10)
    assert client.health(server)["status"] == "ok"
    assert [m["id"] for m in client.models(server)] == ["tts-a", "asr-b"]
    wav, headers = client.speech(server, {"model": "tts-a", "input": "hi"})
    assert wav.startswith(b"RIFF")
    assert headers["x-audiocpp-rtf"] == "0.025"
    assert fake.requests[-1] == ("POST", "/v1/audio/speech", {"model": "tts-a", "input": "hi"})


def test_error_response_carries_the_server_message(fake):
    server = client.Server(fake.port, 10)
    with pytest.raises(client.ServerError) as error:
        client.speech(server, {"model": "nope", "input": "hi"})
    assert (error.value.status, error.value.kind, error.value.message) == (500, "server_error", "unknown model id: nope")


def test_error_without_json(fake):
    fake.speech_status, fake.speech_body = 503, b"busy"
    with pytest.raises(client.ServerError, match="503.*busy"):
        client.speech(client.Server(fake.port, 10), {"model": "tts-a", "input": "hi"})


def test_redirect_is_not_followed(fake):
    fake.speech_status, fake.speech_body = 302, b""
    with pytest.raises(client.AudioCPPError, match="redirect"):
        client.speech(client.Server(fake.port, 10), {"model": "tts-a", "input": "hi"})
    assert len(fake.requests) == 1


def test_connection_refused_says_how_to_fix_it():
    port = free_port()
    with pytest.raises(client.AudioCPPError, match=f"no audio.cpp server is listening on http://127.0.0.1:{port}.*--port {port}"):
        client.health(client.Server(port, 5))


def test_timeout(fake):
    fake.delay = 2.0
    with pytest.raises(client.AudioCPPError, match="did not answer within 0.5 s"):
        client.speech(client.Server(fake.port, 0.5), {"model": "tts-a", "input": "hi"})


def test_interrupt_stops_waiting(fake):
    fake.delay = 5.0
    calls = []

    class Interrupted(Exception):
        pass

    def check():
        calls.append(time.monotonic())
        if len(calls) >= 3:
            raise Interrupted

    started = time.monotonic()
    with pytest.raises(Interrupted):
        client.speech(client.Server(fake.port, 30), {"model": "tts-a", "input": "hi"}, check_interrupt=check)
    assert time.monotonic() - started < 2.0


def test_non_wav_answer_is_an_error(fake):
    fake.speech_status, fake.speech_body = 200, b"{}"
    with pytest.raises(client.AudioCPPError, match="with application/json, not a WAV"):
        client.speech(client.Server(fake.port, 10), {"model": "tts-a", "input": "hi"})


def test_unknown_endpoint_is_reported(fake):
    with pytest.raises(client.ServerError, match="404 \\(not_found\\)"):
        client.request(client.Server(fake.port, 10), "GET", "/nope")
