"""MCP server exposing the Highlighter API as tools.

A thin layer: each tool validates nothing itself and just calls the API, turning
HighlighterAPIError into an MCP tool error the model can read and act on. The
allowed values in the tool schemas come from schema.py, the same source the API
validates against.

Run locally (stdio, how the agent relay launches it):
    python -m highlighter.mcp_server
Run as an HTTP server (how it would run on AgentCore Runtime: 0.0.0.0:8000/mcp):
    python -m highlighter.mcp_server --http
"""

from __future__ import annotations

import argparse
from typing import Annotated, Any, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from .interface import HighlighterAPI
from .mock_api import MockHighlighterAPI
from .schema import (
    CATEGORIES, DEFAULT_FIELDS, DEFAULT_LIMIT, FLAG_PRIORITIES, MAX_LIMIT, SEVERITIES, STATUSES,
)
from .validation import HighlighterAPIError

# Literal[...] with the shared tuples puts the allowed values into each tool's JSON
# schema, so the model sees them before it calls the tool.
Category = Literal[CATEGORIES]  # type: ignore[valid-type]
Severity = Literal[SEVERITIES]  # type: ignore[valid-type]
Status = Literal[STATUSES]  # type: ignore[valid-type]
Priority = Literal[FLAG_PRIORITIES]  # type: ignore[valid-type]

INSTRUCTIONS = """\
Mock Highlighter API: observations detected in imagery (CCTV, fixed cameras, drones)
at industrial sites. Each observation has a site, a time, a category
(hazard / issue / asset), a severity and a status.

Status meanings: open = detected, not actioned; acknowledged = seen, not fixed;
resolved = fixed (resolved_at set); dismissed = rejected by a human as a false
detection (resolved_at set); n/a = asset detections, which are not work items.

Every response includes data_as_of: treat that as "now" for relative dates such as
"last month". Times are UTC.
"""

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False,
                        idempotent_hint=False, open_world_hint=False)


def _call(fn, *args, **kwargs) -> dict[str, Any]:
    try:
        return fn(*args, **kwargs)
    except HighlighterAPIError as e:
        raise ToolError(str(e)) from None


def build_server(api: HighlighterAPI | None = None) -> MCPServer:
    """Create the MCP server around an API backend (the mock by default)."""
    api = api or MockHighlighterAPI()
    mcp = MCPServer(name="highlighter", instructions=INSTRUCTIONS)

    @mcp.tool(annotations=READ_ONLY)
    def list_sites() -> dict[str, Any]:
        """List all sites with id, name, type, region, onboarded_at (date monitoring
        started; no observations exist before it) and the camera/drone source types.
        Also returns data_as_of and data_start for the dataset."""
        return _call(api.list_sites)

    @mcp.tool(annotations=READ_ONLY)
    def get_site(site_id: Annotated[str, Field(description="Site id, e.g. 'S01'.")]) -> dict[str, Any]:
        """Full details for one site, including each individual camera/drone source."""
        return _call(api.get_site, site_id)

    @mcp.tool(annotations=READ_ONLY)
    def query_observations(
        site_ids: Annotated[list[str] | None, Field(description="Only these sites, e.g. ['S01','S02']. Omit for all sites.")] = None,
        categories: Annotated[list[Category] | None, Field(description="Only these categories.")] = None,
        severities: Annotated[list[Severity] | None, Field(description="Only these severities. Assets are always 'info'.")] = None,
        statuses: Annotated[list[Status] | None, Field(description="Only these statuses. Currently unresolved = ['open','acknowledged'].")] = None,
        types: Annotated[list[str] | None, Field(description="Only these observation types, e.g. ['oil_spill']. An unknown type returns an error listing valid ones.")] = None,
        observed_from: Annotated[str | None, Field(description="Inclusive start, 'YYYY-MM-DD' or ISO 8601 (UTC).")] = None,
        observed_to: Annotated[str | None, Field(description="EXCLUSIVE end. October 2026 = observed_from '2026-10-01', observed_to '2026-11-01'.")] = None,
        min_confidence: Annotated[float | None, Field(description="Minimum detector confidence, 0-1.")] = None,
        fields: Annotated[list[str] | None, Field(description=f"Fields to return. Default: {list(DEFAULT_FIELDS)}. Others: source_id, acknowledged_at, image_ref.")] = None,
        limit: Annotated[int, Field(description=f"Rows per page, 1-{MAX_LIMIT}.")] = DEFAULT_LIMIT,
        offset: Annotated[int, Field(description="Row offset for paging; use next_offset from the previous page.")] = 0,
    ) -> dict[str, Any]:
        """Filter observations; returns matching rows, not aggregates. Check
        total_matching against returned: if next_offset is not null there are more
        rows, so page through them (or narrow the filters) before computing counts."""
        return _call(
            api.query_observations,
            site_ids=site_ids, categories=categories, severities=severities,
            statuses=statuses, types=types, observed_from=observed_from,
            observed_to=observed_to, min_confidence=min_confidence, fields=fields,
            limit=limit, offset=offset,
        )

    @mcp.tool(annotations=WRITE)
    def flag_site(
        site_id: Annotated[str, Field(description="Site id to flag, e.g. 'S01'.")],
        reason: Annotated[str, Field(description="Why the site needs attention, citing the evidence (max 500 chars).")],
        priority: Annotated[Priority, Field(description="Flag priority.")] = "medium",
    ) -> dict[str, Any]:
        """WRITE ACTION: flag a site in Highlighter for follow-up. Requires human
        confirmation; the call may be declined. Only use when the user asks for it."""
        return _call(api.flag_site, site_id, reason, priority)

    @mcp.tool(annotations=READ_ONLY)
    def list_flags(
        site_id: Annotated[str | None, Field(description="Only flags for this site. Omit for all.")] = None,
    ) -> dict[str, Any]:
        """List flags previously raised on sites."""
        return _call(api.list_flags, site_id)

    @mcp.custom_route("/ping", methods=["GET"])
    async def ping(request):  # health check used by AgentCore Runtime
        from starlette.responses import JSONResponse
        return JSONResponse({"status": "Healthy"})

    return mcp


def main() -> None:
    parser = argparse.ArgumentParser(description="Highlighter mock MCP server")
    parser.add_argument("--http", action="store_true",
                        help="Serve Streamable HTTP on 0.0.0.0:8000/mcp instead of stdio")
    args = parser.parse_args()
    server = build_server()
    if args.http:
        server.run(transport="streamable-http", host="0.0.0.0", port=8000, stateless_http=True)
    else:
        server.run()  # stdio


if __name__ == "__main__":
    main()
