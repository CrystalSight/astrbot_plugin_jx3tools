"""Provide minimal AstrBot API stubs only when AstrBot is unavailable."""

from __future__ import annotations

import importlib.util
import logging
import os
import sys
import tempfile
import types
from pathlib import Path

PLUGIN_PARENT = Path(__file__).resolve().parents[2]
os.environ.setdefault(
    "ASTRBOT_ROOT",
    str(Path(tempfile.gettempdir()) / "astrbot-jx3tools-tests"),
)
if str(PLUGIN_PARENT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_PARENT))


if importlib.util.find_spec("astrbot") is None:
    astrbot = types.ModuleType("astrbot")
    api = types.ModuleType("astrbot.api")
    event = types.ModuleType("astrbot.api.event")
    star = types.ModuleType("astrbot.api.star")

    class AstrBotConfig(dict):
        """Test double for AstrBotConfig."""

    class Context:
        """Test double for Context."""

    class MessageChain:
        """Test double for proactive text messages."""

        def __init__(self) -> None:
            self.text = ""

        def message(self, text: str):
            self.text = text
            return self

        def get_plain_text(self) -> str:
            return self.text

    class Star:
        """Test double for the AstrBot plugin base class."""

        def __init__(self, context, config=None) -> None:
            self.context = context

    class Filter:
        """Keep decorated handlers callable in unit tests."""

        @staticmethod
        def command(*_args, **_kwargs):
            def decorator(function):
                return function

            return decorator

        @staticmethod
        def regex(*_args, **_kwargs):
            def decorator(function):
                return function

            return decorator

    def get_astrbot_data_path() -> str:
        """Return a writable test data root."""
        return tempfile.gettempdir()

    setattr(api, "AstrBotConfig", AstrBotConfig)
    setattr(api, "logger", logging.getLogger("astrbot-test"))
    setattr(event, "AstrMessageEvent", object)
    setattr(event, "MessageChain", MessageChain)
    setattr(event, "filter", Filter())
    setattr(star, "Context", Context)
    setattr(star, "Star", Star)
    setattr(star, "get_astrbot_data_path", get_astrbot_data_path)
    setattr(astrbot, "api", api)

    sys.modules["astrbot"] = astrbot
    sys.modules["astrbot.api"] = api
    sys.modules["astrbot.api.event"] = event
    sys.modules["astrbot.api.star"] = star
