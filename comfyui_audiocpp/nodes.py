"""ComfyUI nodes for audio.cpp: speech from an audiocpp_server that you start yourself on this computer."""

from __future__ import annotations

import base64
import json
import logging

from comfy_api.latest import ComfyExtension, io, ui

from . import audio, client

# Tasks whose models take text on POST /v1/audio/speech (task names as GET /v1/models reports them).
SPEECH_TASKS = ("tts", "clon", "vdes")

AudioCPPServerType = io.Custom("AUDIOCPP_SERVER")


def _check_interrupt():
    import comfy.model_management

    comfy.model_management.throw_exception_if_processing_interrupted()


def _speech_models(models: list[dict]) -> list[dict]:
    return [m for m in models if m.get("task") in SPEECH_TASKS]


def _model_list(models: list[dict]) -> str:
    return ", ".join(f"{m.get('id')} ({m.get('family')}, task {m.get('task')})" for m in models) or "none"


def _options(text: str) -> dict:
    """The options input: a JSON object of strings, numbers or booleans (the server's request options are scalars)."""
    if not text.strip():
        return {}
    try:
        value = json.loads(text)
    except ValueError as error:
        raise ValueError(f"options must be a JSON object, e.g. {{\"temperature\": 0.7}}: {error}") from error
    if not isinstance(value, dict):
        raise ValueError("options must be a JSON object, e.g. {\"temperature\": 0.7}")
    for key, item in value.items():
        if isinstance(item, (dict, list)) or item is None:
            raise ValueError(f"option {key!r} must be a string, number or boolean")
    return value


def speech_payload(model, text, seed, voice="", language="", speed=1.0, max_tokens=0, options="", reference_audio=None, reference_text=""):
    """The JSON body of POST /v1/audio/speech for the Text to Speech node's inputs."""
    if not text.strip():
        raise ValueError("text is empty")
    payload = {"model": model, "input": text}
    extra = _options(options)
    if extra:
        payload["options"] = extra
    # A string keeps all 64 bits of the seed (the server parses request options from strings either way).
    payload["seed"] = str(seed)
    if voice.strip():
        payload["voice"] = voice.strip()
    if language.strip():
        payload["language"] = language.strip()
    if speed != 1.0:
        payload["speed"] = speed
    if max_tokens > 0:
        payload["max_tokens"] = max_tokens
    if reference_audio is not None:
        wav = audio.audio_to_wav(reference_audio)
        if len(wav) > client.MAX_VOICE_REF_BYTES:
            seconds = reference_audio["waveform"].shape[-1] / reference_audio["sample_rate"]
            raise ValueError(f"reference_audio is {seconds:.1f} s ({len(wav) / 2**20:.1f} MiB as 16-bit WAV); the server takes at most "
                             f"{client.MAX_VOICE_REF_BYTES // 2**20} MiB, so trim it")
        payload["voice_ref"] = {"type": "base64", "data": base64.b64encode(wav).decode("ascii")}
    if reference_text.strip():
        payload["reference_text"] = reference_text.strip()
    return payload


class AudioCPPServer(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="AudioCPPServer",
            display_name="audio.cpp Server",
            category="audio/audio.cpp",
            description=("Connects the audio.cpp nodes to an audiocpp_server that you started on this computer (127.0.0.1). The nodes never "
                         "start, stop or download anything; the server's config decides which models are available."),
            inputs=[
                io.Int.Input("port", default=8080, min=1, max=65535, tooltip="the server's --port (or \"port\" in its config)"),
                io.Float.Input("timeout", default=600.0, min=1.0, max=86400.0, step=1.0,
                               tooltip="seconds to wait for one answer; a first request also loads the model"),
            ],
            outputs=[AudioCPPServerType.Output(display_name="server")],
        )

    @classmethod
    def execute(cls, port, timeout) -> io.NodeOutput:
        return io.NodeOutput(client.Server(port, float(timeout)))


class AudioCPPDoctor(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="AudioCPPDoctor",
            display_name="audio.cpp Doctor",
            category="audio/audio.cpp",
            description="Checks the server (GET /health) and lists its models (GET /v1/models): the ids to use and which of them speak.",
            inputs=[AudioCPPServerType.Input("server")],
            outputs=[io.String.Output(display_name="report")],
            is_output_node=True,
        )

    @classmethod
    def fingerprint_inputs(cls, server):
        return float("nan")  # the server can change between runs

    @classmethod
    def execute(cls, server) -> io.NodeOutput:
        report = doctor_report(server)
        return io.NodeOutput(report, ui=ui.PreviewText(report))


def doctor_report(server: client.Server) -> str:
    try:
        status = client.health(server, _check_interrupt)
        models = client.models(server, _check_interrupt)
    except client.AudioCPPError as error:
        return f"audio.cpp server on {server.address}: not reachable.\n{error}"
    lines = [f"audio.cpp server on {server.address}: {status.get('status')}, backend {status.get('backend')}, {len(models)} model(s)"]
    for m in models:
        speaks = "speech" if m.get("task") in SPEECH_TASKS else "not for Text to Speech"
        lines.append(f"- {m.get('id')}: family {m.get('family')}, task {m.get('task')}, mode {m.get('mode')}, "
                     f"{'loaded' if m.get('loaded') else 'not loaded'}, device {m.get('device')} ({speaks})")
    if not _speech_models(models):
        lines.append(f"No model with a speech task ({', '.join(SPEECH_TASKS)}); add one to the server's config.")
    return "\n".join(lines)


class AudioCPPTextToSpeech(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="AudioCPPTextToSpeech",
            display_name="audio.cpp Text to Speech",
            category="audio/audio.cpp",
            description=("Speech from text through POST /v1/audio/speech. Which voices, languages and options work depends on the model; "
                         "see its page in the audio.cpp docs."),
            inputs=[
                AudioCPPServerType.Input("server"),
                io.String.Input("model", default="", tooltip="a model id from the server's config (audio.cpp Doctor lists them); empty: the only speech model"),
                io.String.Input("text", multiline=True, default="Hello from audio.cpp."),
                io.Int.Input("seed", default=0, min=0, max=0xffffffffffffffff, control_after_generate=True),
                io.String.Input("voice", default="",
                                tooltip="a configured voice preset, a voice_dir reference name or the model's own voice id; empty: the default"),
                io.String.Input("language", default="", tooltip="the model's language code, e.g. en; empty: the model's default"),
                io.Float.Input("speed", default=1.0, min=0.25, max=4.0, step=0.01,
                               tooltip="1: unchanged; other values need a model that supports speed"),
                io.Int.Input("max_tokens", default=0, min=0, max=1000000, tooltip="0: the model's default; caps the length of autoregressive models"),
                io.String.Input("options", multiline=True, default="", tooltip='model request options as a JSON object, e.g. {"temperature": 0.7}'),
                io.Audio.Input("reference_audio", optional=True,
                               tooltip="a voice to clone, for models that take reference audio (sent as a WAV of up to 5 MiB)"),
                io.String.Input("reference_text", default="", optional=True, tooltip="the transcript of reference_audio, for models that need it"),
            ],
            outputs=[io.Audio.Output(display_name="audio")],
        )

    @classmethod
    def execute(cls, server, model, text, seed, voice, language, speed, max_tokens, options, reference_audio=None, reference_text="") -> io.NodeOutput:
        model = model.strip() or _only_speech_model(server)
        payload = speech_payload(model, text, seed, voice, language, speed, max_tokens, options, reference_audio, reference_text)
        try:
            wav, headers = client.speech(server, payload, _check_interrupt)
        except client.ServerError as error:
            if "unknown model id" in error.message:
                raise client.AudioCPPError(f"{error}. The server has: {_model_list(client.models(server))}") from error
            raise
        result = audio.wav_to_audio(wav)
        logging.info("audio.cpp %s: %.2f s of audio in %s ms (RTF %s)", model, result["waveform"].shape[-1] / result["sample_rate"],
                     headers.get("x-audiocpp-wall-ms"), headers.get("x-audiocpp-rtf"))
        return io.NodeOutput(result)


def _only_speech_model(server: client.Server) -> str:
    models = client.models(server, _check_interrupt)
    speaking = _speech_models(models)
    if len(speaking) != 1:
        raise ValueError(f"set the model input to one of the server's speech models: {_model_list(speaking or models)}")
    return speaking[0]["id"]


class AudioCPPExtension(ComfyExtension):
    async def get_node_list(self):
        return [AudioCPPServer, AudioCPPDoctor, AudioCPPTextToSpeech]


async def comfy_entrypoint() -> AudioCPPExtension:
    return AudioCPPExtension()
