"""ComfyUI nodes for audio.cpp (https://github.com/0xShug0/audio.cpp)."""

import logging

try:
    from .comfyui_audiocpp.nodes import comfy_entrypoint  # noqa: F401
except ImportError as e:  # a ComfyUI without the V3 node API (comfy_api.latest)
    logging.error("[audio.cpp] nodes not loaded: %s", e)
    NODE_CLASS_MAPPINGS = {}
    NODE_DISPLAY_NAME_MAPPINGS = {}
