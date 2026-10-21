import base64
import json

import pytest
import torch
from conftest import free_port, make_wav, result

from comfyui_audiocpp import audio, client


def tts(nodes, server, model="tts-a", text="Hello.", seed=0, voice="", language="", speed=1.0, max_tokens=0, options="", **optional):
    return result(nodes.AudioCPPTextToSpeech.execute(server, model, text, seed, voice, language, speed, max_tokens, options, **optional))[0]


def test_schema_ids(nodes):
    for cls, node_id in [(nodes.AudioCPPServer, "AudioCPPServer"), (nodes.AudioCPPDoctor, "AudioCPPDoctor"),
                         (nodes.AudioCPPTextToSpeech, "AudioCPPTextToSpeech")]:
        assert cls.define_schema().node_id == node_id


def test_payload_sends_only_what_is_set(nodes):
    assert nodes.speech_payload("m", "Hi", 5) == {"model": "m", "input": "Hi", "seed": "5"}
    payload = nodes.speech_payload("m", "Hi", 2**64 - 1, voice=" alba ", language="en", speed=1.25, max_tokens=300,
                                   options='{"temperature": 0.7, "x_vector_only_mode": true}', reference_text=" ref ")
    assert payload == {"model": "m", "input": "Hi", "seed": "18446744073709551615", "voice": "alba", "language": "en", "speed": 1.25,
                       "max_tokens": 300, "options": {"temperature": 0.7, "x_vector_only_mode": True}, "reference_text": "ref"}


@pytest.mark.parametrize("options", ["[1]", "{bad", '{"a": {"b": 1}}', '{"a": null}'])
def test_options_must_be_an_object_of_scalars(nodes, options):
    with pytest.raises(ValueError):
        nodes.speech_payload("m", "Hi", 0, options=options)


def test_empty_text_is_rejected_before_any_request(nodes, fake):
    with pytest.raises(ValueError, match="text is empty"):
        tts(nodes, client.Server(fake.port, 5), text=" \n ")
    assert fake.requests == []


def test_reference_audio_is_sent_as_base64_wav(nodes):
    clip = audio.wav_to_audio(make_wav(seconds=1.0, rate=16000))
    payload = nodes.speech_payload("m", "Hi", 0, reference_audio=clip, reference_text="hello")
    assert payload["voice_ref"]["type"] == "base64"
    back = audio.wav_to_audio(base64.b64decode(payload["voice_ref"]["data"]))
    assert back["sample_rate"] == 16000 and torch.equal(back["waveform"], clip["waveform"])


def test_reference_audio_over_the_server_limit(nodes):
    clip = {"waveform": torch.zeros(1, 2, 48000 * 30), "sample_rate": 48000}
    with pytest.raises(ValueError, match="at most 5 MiB"):
        nodes.speech_payload("m", "Hi", 0, reference_audio=clip)


def test_text_to_speech_returns_audio(nodes, fake):
    out = tts(nodes, client.Server(fake.port, 10), seed=42)
    assert out["sample_rate"] == 24000 and out["waveform"].shape == (1, 1, 12000)
    assert fake.requests[-1][2] == {"model": "tts-a", "input": "Hello.", "seed": "42"}


def test_empty_model_picks_the_only_speech_model(nodes, fake):
    tts(nodes, client.Server(fake.port, 10), model="")
    assert fake.requests[-1][2]["model"] == "tts-a"
    fake.models.append(dict(fake.models[0], id="tts-c"))
    with pytest.raises(ValueError, match="tts-a.*tts-c"):
        tts(nodes, client.Server(fake.port, 10), model="")


def test_unknown_model_lists_the_server_models(nodes, fake):
    with pytest.raises(client.AudioCPPError, match="unknown model id: nope.*tts-a \\(pocket_tts, task tts\\), asr-b"):
        tts(nodes, client.Server(fake.port, 10), model="nope")


def test_server_error_reaches_the_user(nodes, fake):
    fake.speech_status, fake.speech_body = 500, json.dumps({"error": {"message": "PocketTTS text prompt is required", "type": "server_error"}}).encode()
    with pytest.raises(client.ServerError, match="PocketTTS text prompt is required"):
        tts(nodes, client.Server(fake.port, 10))


def test_doctor_reports_models_and_tasks(nodes, fake):
    report, = result(nodes.AudioCPPDoctor.execute(client.Server(fake.port, 10)))
    assert "ok, backend cpu, 2 model(s)" in report
    assert "- tts-a: family pocket_tts, task tts, mode offline, not loaded, device 0 (speech)" in report
    assert "- asr-b: family qwen3_asr, task asr, mode offline, loaded, device 0 (not for Text to Speech)" in report
    assert nodes.AudioCPPDoctor.fingerprint_inputs(server=None) != nodes.AudioCPPDoctor.fingerprint_inputs(server=None)


def test_doctor_reports_a_stopped_server(nodes):
    port = free_port()
    report, = result(nodes.AudioCPPDoctor.execute(client.Server(port, 5)))
    assert report.startswith(f"audio.cpp server on http://127.0.0.1:{port}: not reachable.")


def test_doctor_without_speech_models(nodes, fake):
    fake.models = [fake.models[1]]
    report, = result(nodes.AudioCPPDoctor.execute(client.Server(fake.port, 10)))
    assert "No model with a speech task" in report


def test_server_node_validates(nodes):
    server, = result(nodes.AudioCPPServer.execute(8080, 600.0))
    assert server == client.Server(8080, 600.0)
    with pytest.raises(ValueError):
        nodes.AudioCPPServer.execute(0, 600.0)
