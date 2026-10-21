# ComfyUI-AudioCPP

ComfyUI nodes for [audio.cpp](https://github.com/0xShug0/audio.cpp): they send text to an `audiocpp_server` running on the same
computer and return the speech as ComfyUI `AUDIO`, ready for Save Audio, Preview Audio or any other audio node.

The nodes only talk to the server over HTTP on `127.0.0.1`. They do not start, stop or install anything, need no Python packages
beyond ComfyUI's, and never download models: the server's config decides which models are available.

## Nodes

| Node | What it does |
| --- | --- |
| **audio.cpp Server** | The connection: the server's port on this computer and how long to wait for one answer. |
| **audio.cpp Doctor** | Checks `GET /health` and lists `GET /v1/models`: each model's id, family, task, mode and whether it is loaded. Use it to find the model ids. |
| **audio.cpp Text to Speech** | `POST /v1/audio/speech`: model id, text, seed, voice, language, speed, `max_tokens` and model options, plus optional reference audio and its transcript for voice cloning. Returns `AUDIO`. |

## Install

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/0xShug0/ComfyUI-AudioCPP
```

There is nothing to install with pip. Restart ComfyUI; the nodes are under `audio/audio.cpp`, and an example workflow is in
`example_workflows/`.

## Start a server

Use a [release](https://github.com/0xShug0/audio.cpp/releases) build or [build](https://github.com/0xShug0/audio.cpp/blob/main/app/server/README.md#build)
`audiocpp_server`, install a model package (see [docs/tts.md](https://github.com/0xShug0/audio.cpp/blob/main/docs/tts.md) and
[docs/models](https://github.com/0xShug0/audio.cpp/tree/main/docs/models)) and register it in a config. For example, with
[PocketTTS](https://github.com/0xShug0/audio.cpp/blob/main/docs/tts.md#pockettts) and its built-in voice `alba` (as in
[examples/server/pocket-tts.json](https://github.com/0xShug0/audio.cpp/blob/main/examples/server/pocket-tts.json)):

```json
{
  "host": "127.0.0.1",
  "port": 8080,
  "backend": "cuda",
  "lazy_load": true,
  "models": [
    {
      "id": "pocket-tts",
      "family": "pocket_tts",
      "path": "C:/models/PocketTTS-GGUF/english/pocket-tts-english-q8_0.gguf",
      "task": "tts",
      "mode": "offline",
      "load_options": { "language": "english" },
      "default_voice_preset": { "voice_id": "alba" }
    }
  ]
}
```

```bash
audiocpp_server --config server.json --no-ui --log
```

Set **audio.cpp Server**'s port to the server's, and **Text to Speech**'s `model` to the config's `id` (or leave it empty when the
server has only one speech model). The [server guide](https://github.com/0xShug0/audio.cpp/blob/main/app/server/README.md) explains
configs, voice presets, `voice_dir` reference libraries and memory settings.

## Voices, languages and options

What works depends on the model; check its section in the audio.cpp docs.

- `voice` is a configured preset name, a `voice_dir` reference name or the model's own voice id.
- `language` is the model's language code or name (for example `en`).
- `options` takes the model's request options as a JSON object, for example `{"temperature": 0.7}` or
  `{"x_vector_only_mode": true}` for Qwen3-TTS Base.
- `seed` is sent with every request, so the same inputs give the same audio with the models that sample from a seed.
- **Voice cloning**: connect `reference_audio` (for example from Load Audio) and fill `reference_text` with its transcript for
  models that need one, such as Qwen3-TTS Base. The audio goes to the server as an inline 16-bit WAV, which the server limits to 5 MiB.

## Notes

- Only `127.0.0.1` is used: a workflow chooses a port, never a host or URL. Redirects are not followed and proxy settings are not
  used.
- **Cancel** stops ComfyUI from waiting, but the server finishes the generation it has started (its default runtime has no cancel
  request), and the next request to that model waits until it is done.
- `timeout` covers one answer, including model loading on the first request; raise it for long texts and slow models.
- Errors from the server are shown as it sends them, for example `unknown model id: ...` (together with the ids it has) or
  `PocketTTS text prompt is required`.

## Tests

```bash
AUDIOCPP_COMFYUI_DIR=/path/to/ComfyUI python -m pytest
```

The tests use a stand-in HTTP server with the server's response shapes. With `AUDIOCPP_TEST_PORT` set to the port of a running
`audiocpp_server` that has a PocketTTS entry `pocket-tts`, they also run against it.

## License

Apache-2.0, like audio.cpp. The models keep their own licenses; see
[docs/model_licenses.md](https://github.com/0xShug0/audio.cpp/blob/main/docs/model_licenses.md).
