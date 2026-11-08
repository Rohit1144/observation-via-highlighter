"""Highlighter tools layer: the API interface, a mock backend, and the MCP server.

interface.py    HighlighterAPI: the contract any backend meets
schema.py       allowed values, fields, limits (shared)
validation.py   HighlighterAPIError + input checks (shared)
mock_api.py     MockHighlighterAPI: the only mock part
mcp_server.py   MCP tools over any HighlighterAPI
"""

from .interface import HighlighterAPI
from .mock_api import MockHighlighterAPI
from .validation import HighlighterAPIError

__all__ = ["HighlighterAPI", "HighlighterAPIError", "MockHighlighterAPI"]
