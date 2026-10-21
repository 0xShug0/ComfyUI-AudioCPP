import io
import wave

import pytest
import torch
from conftest import make_wav

from comfyui_audiocpp import audio


def test_wav_to_audio_shape_and_scale():
    a = audio.wav_to_audio(make_wav(seconds=0.25, rate=24000, channels=2))
    assert a["sample_rate"] == 24000
    assert a["waveform"].shape == (1, 2, 6000)
    assert a["waveform"].dtype == torch.float32
    assert a["waveform"].abs().max() <= 1.0


def test_round_trip_is_within_half_a_step():
    torch.manual_seed(0)
    clip = {"waveform": torch.rand(2, 2, 4800) * 2 - 1, "sample_rate": 48000}
    back = audio.wav_to_audio(audio.audio_to_wav(clip))
    assert back["sample_rate"] == 48000 and back["waveform"].shape == (1, 2, 4800)
    assert torch.allclose(back["waveform"][0], clip["waveform"][0], atol=0.5 / 32768 + 1e-7)


def test_16_bit_samples_come_back_unchanged():
    data = make_wav(seconds=0.1, rate=22050, channels=2)
    assert audio.audio_to_wav(audio.wav_to_audio(data)) == data


def test_audio_to_wav_takes_the_first_clip_and_clamps():
    clip = {"waveform": torch.stack([torch.tensor([[2.0, -2.0]]), torch.zeros(1, 2)]), "sample_rate": 16000}
    with wave.open(io.BytesIO(audio.audio_to_wav(clip))) as w:
        assert (w.getnchannels(), w.getframerate(), w.getnframes(), w.getsampwidth()) == (1, 16000, 2, 2)
        assert w.readframes(2) == (32767).to_bytes(2, "little", signed=True) + (-32768).to_bytes(2, "little", signed=True)


def test_rejects_other_sample_widths_and_shapes():
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(1)
        w.setframerate(8000)
        w.writeframes(b"\x80" * 8)
    with pytest.raises(ValueError, match="16-bit"):
        audio.wav_to_audio(out.getvalue())
    with pytest.raises(ValueError, match="batch, channels, samples"):
        audio.audio_to_wav({"waveform": torch.zeros(1, 100), "sample_rate": 16000})
