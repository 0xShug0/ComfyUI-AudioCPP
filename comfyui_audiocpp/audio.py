"""Conversion between the server's 16-bit PCM WAV files and ComfyUI's AUDIO ({"waveform": [batch, channels, samples], "sample_rate"})."""

from __future__ import annotations

import io
import wave

import numpy as np
import torch


def wav_to_audio(data: bytes) -> dict:
    """A 16-bit PCM WAV (what the server sends) as a one-clip AUDIO in float32, -1..1."""
    with wave.open(io.BytesIO(data), "rb") as w:
        if w.getsampwidth() != 2:
            raise ValueError(f"expected 16-bit PCM from the server, got {8 * w.getsampwidth()}-bit samples")
        channels, rate, frames = w.getnchannels(), w.getframerate(), w.getnframes()
        pcm = np.frombuffer(w.readframes(frames), dtype="<i2")
    waveform = torch.from_numpy(pcm.reshape(-1, channels).T.astype(np.float32) / 32768.0)
    return {"waveform": waveform.unsqueeze(0).contiguous(), "sample_rate": rate}


def audio_to_wav(audio: dict) -> bytes:
    """The first clip of an AUDIO as a 16-bit PCM WAV, at its own sample rate and channel count.

    The scale is the inverse of wav_to_audio's, so audio that came from a 16-bit file (LoadAudio) gets its own samples back.
    """
    waveform = audio["waveform"]
    if waveform.ndim != 3 or waveform.shape[-1] == 0:
        raise ValueError(f"expected an AUDIO waveform of shape [batch, channels, samples], got {tuple(waveform.shape)}")
    clip = waveform[0].detach().to(torch.float32).cpu().numpy()
    pcm = np.clip(np.round(clip.T * 32768.0), -32768, 32767).astype("<i2")
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(clip.shape[0])
        w.setsampwidth(2)
        w.setframerate(int(audio["sample_rate"]))
        w.writeframes(pcm.tobytes())
    return out.getvalue()
