"""Mock Highlighter API: the data layer the agent's tools are built on."""

from .api import HighlighterAPI, HighlighterAPIError, MockHighlighterAPI

__all__ = ["HighlighterAPI", "HighlighterAPIError", "MockHighlighterAPI"]
