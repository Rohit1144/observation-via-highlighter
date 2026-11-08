"""Tests for the MCP layer: tools are listed with the right schemas, calls reach the
API, and API errors come back as MCP tool errors (not crashes). Uses the SDK's
in-memory client, so no subprocess or network is involved."""

import asyncio
import json

import pytest
from mcp import Client

from highlighter import MockHighlighterAPI
from highlighter.mcp_server import build_server


@pytest.fixture
def server(tmp_path):
    return build_server(MockHighlighterAPI(flags_path=tmp_path / "flags.jsonl"))


def run(server, coro_fn):
    async def go():
        async with Client(server) as client:
            return await coro_fn(client)
    return asyncio.run(go())


def payload(result) -> dict:
    """Tool result as a dict (structured output if present, else the JSON text)."""
    if result.structured_content is not None:
        return result.structured_content
    return json.loads(result.content[0].text)


def test_tools_listed_with_annotations(server):
    tools = {t.name: t for t in run(server, lambda c: c.list_tools()).tools}
    assert set(tools) == {"list_sites", "get_site", "query_observations", "flag_site", "list_flags"}
    assert tools["query_observations"].annotations.read_only_hint is True
    assert tools["flag_site"].annotations.read_only_hint is False


def test_enum_values_are_in_the_schema(server):
    tools = {t.name: t for t in run(server, lambda c: c.list_tools()).tools}
    schema = json.dumps(tools["query_observations"].input_schema)
    for value in ("hazard", "critical", "acknowledged", "dismissed"):
        assert value in schema


def test_query_matches_direct_api_call(server, tmp_path):
    args = {"site_ids": ["S01"], "categories": ["hazard"], "severities": ["high", "critical"],
            "statuses": ["open", "acknowledged"],
            "observed_from": "2026-10-01", "observed_to": "2026-11-01"}
    result = run(server, lambda c: c.call_tool("query_observations", args))
    direct = MockHighlighterAPI(flags_path=tmp_path / "x.jsonl").query_observations(**args)
    assert not result.is_error
    assert payload(result)["total_matching"] == direct["total_matching"] == 10


def test_api_error_becomes_tool_error(server):
    result = run(server, lambda c: c.call_tool("get_site", {"site_id": "S99"}))
    assert result.is_error
    assert "Unknown site_id" in result.content[0].text


def test_schema_rejects_bad_enum_before_api(server):
    result = run(server, lambda c: c.call_tool("query_observations", {"severities": ["severe"]}))
    assert result.is_error


def test_flag_site_round_trip(server):
    async def go(c):
        await c.call_tool("flag_site", {"site_id": "S01", "reason": "test", "priority": "high"})
        return await c.call_tool("list_flags", {"site_id": "S01"})
    flags = payload(run(server, go))["flags"]
    assert len(flags) == 1 and flags[0]["priority"] == "high"
