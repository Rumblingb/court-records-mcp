#!/usr/bin/env python3
"""
Court Records MCP Server

Provides tools for searching and retrieving US court records via
the CourtListener REST v4 API (free tier, no auth required).

Usage:
    python server.py                    # Start MCP server (stdio protocol)
    python server.py --api-key TOKEN    # Start with premium API key
"""

import argparse
import json
import sys
from datetime import datetime, timedelta
from typing import Any, Optional

import httpx

# ---------------------------------------------------------------------------
# MCP imports  --  works with the `mcp` package from PyPI
# ---------------------------------------------------------------------------
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolRequest, CallToolResult, ListToolsResult, Tool

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BASE_URL = "https://www.courtlistener.com/api/rest/v4"
APP_NAME = "court-records-mcp"
APP_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Tool schemas (JSON Schema for each tool parameter)
# ---------------------------------------------------------------------------

TOOL_SEARCH_CASES = Tool(
    name="search_cases",
    description=(
        "Search US court opinions. Accepts a free-text query, an optional "
        "court filter (e.g. 'ca1', 'ca2', 'scotus'), and a result limit."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Free-text search query (supports Lucene syntax)",
            },
            "court_filter": {
                "type": "string",
                "description": "Court ID filter (e.g. 'ca1', 'scotus', 'cand'). Omit for all courts.",
                "default": "",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of results to return (1-100)",
                "default": 10,
                "minimum": 1,
                "maximum": 100,
            },
        },
        "required": ["query"],
    },
)

TOOL_GET_OPINION = Tool(
    name="get_opinion",
    description=(
        "Retrieve the full opinion cluster (including all associated opinions) "
        "by its CourtListener cluster ID."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "cluster_id": {
                "type": "integer",
                "description": "CourtListener cluster ID for the opinion",
            },
        },
        "required": ["cluster_id"],
    },
)

TOOL_GET_COURT = Tool(
    name="get_court",
    description="Retrieve metadata about a specific US court by its CourtListener court ID.",
    inputSchema={
        "type": "object",
        "properties": {
            "court_id": {
                "type": "string",
                "description": "Court ID (e.g. 'scotus', 'ca1', 'cand', 'nyed')",
            },
        },
        "required": ["court_id"],
    },
)

TOOL_GET_RECENT = Tool(
    name="get_recent_opinions",
    description="Retrieve opinions filed within the last N days.",
    inputSchema={
        "type": "object",
        "properties": {
            "days": {
                "type": "integer",
                "description": "How many days back to search (default: 7)",
                "default": 7,
                "minimum": 1,
                "maximum": 365,
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of results (1-100)",
                "default": 10,
                "minimum": 1,
                "maximum": 100,
            },
        },
        "required": [],
    },
)

ALL_TOOLS = [
    TOOL_SEARCH_CASES,
    TOOL_GET_OPINION,
    TOOL_GET_COURT,
    TOOL_GET_RECENT,
]


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

async def _api_get(
    client: httpx.AsyncClient,
    path: str,
    params: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Make a GET request to the CourtListener API and return parsed JSON."""
    try:
        resp = await client.get(path, params=params)
    except httpx.TimeoutException:
        return {"error": f"Request timed out for {path}"}
    except httpx.RequestError as exc:
        return {"error": f"Request failed for {path}: {exc}"}

    try:
        data = resp.json()
    except json.JSONDecodeError:
        return {"error": f"Non-JSON response ({resp.status_code}): {resp.text[:200]}"}

    if resp.status_code >= 400:
        detail = data.get("detail") or data.get("error") or resp.reason_phrase
        return {"error": f"API error {resp.status_code}: {detail}"}

    return data


def _format_search_results(data: dict[str, Any]) -> str:
    """Pretty-format search result list."""
    lines: list[str] = []
    count = data.get("count", 0)
    lines.append(f"Total results: {count}")
    lines.append("")

    results = data.get("results", []) or data.get("objects", [])
    if not results:
        lines.append("No results found.")
        return "\n".join(lines)

    for i, r in enumerate(results, 1):
        case_name = r.get("caseName", r.get("case_name", "Unknown"))
        court = r.get("court", court_name(r.get("court_id", "")))
        date_filed = r.get("dateFiled", r.get("date_filed", ""))
        cluster_id = r.get("cluster_id", r.get("id", "?"))
        docket = r.get("docketNumber", r.get("docket_number", ""))
        snippet = r.get("snippet", "") or ""
        absolute_url = r.get("absolute_url", "")

        lines.append(f"{i}. {case_name}")
        lines.append(f"   Court  : {court}")
        lines.append(f"   Filed  : {date_filed}")
        lines.append(f"   Docket : {docket}")
        lines.append(f"   Cluster: {cluster_id}")
        if snippet:
            lines.append(f"   Snippet: {snippet[:200]}")
        if absolute_url:
            lines.append(f"   URL    : https://www.courtlistener.com{absolute_url}")
        lines.append("")

    return "\n".join(lines)


def _format_cluster(data: dict[str, Any]) -> str:
    """Pretty-format a single opinion cluster."""
    lines: list[str] = []
    lines.append(f"Case Name: {data.get('caseName', data.get('case_name', 'Unknown'))}")
    lines.append(f"Court    : {court_name(data.get('court_id', ''))}")
    lines.append(f"Filed    : {data.get('dateFiled', data.get('date_filed', ''))}")
    docket = data.get("docketNumber", data.get("docket_number", ""))
    if docket:
        lines.append(f"Docket   : {docket}")
    lines.append(f"Cluster  : {data.get('id', '?')}")
    lines.append(f"Citation : {data.get('citation', data.get('caseNameShort', ''))}")
    lines.append("")

    # Sub-opinions
    opinions = data.get("sub_opinions", data.get("opinions", []))
    if opinions and isinstance(opinions, list):
        lines.append(f"Opinions ({len(opinions)}):")
        for j, op in enumerate(opinions, 1):
            op_data = op
            if isinstance(op, dict):
                author = op_data.get("author", "")
                author_str = f" by {author}" if author else ""
                op_type = op_data.get("type", "Unknown")
                plain_text = op_data.get("plain_text", "")
                lines.append(f"  {j}. [{op_type}]{author_str}")
                if plain_text:
                    # Show first 500 chars of plain text
                    preview = plain_text[:500]
                    if len(plain_text) > 500:
                        preview += "..."
                    lines.append(f"     {preview}")
                lines.append("")
            elif isinstance(op, str):
                lines.append(f"  {j}. {op[:500]}")

    return "\n".join(lines)


def _format_court(data: dict[str, Any]) -> str:
    """Pretty-format a court record."""
    lines: list[str] = []
    lines.append(f"ID            : {data.get('id', '')}")
    lines.append(f"Name          : {data.get('fullName', data.get('full_name', ''))}")
    lines.append(f"Short Name    : {data.get('shortName', data.get('short_name', ''))}")
    lines.append(f"Jurisdiction  : {data.get('jurisdiction', '')}")
    lines.append(f"Location      : {data.get('location', '')}")
    lines.append(f"Citation      : {data.get('citationString', data.get('citation_string', ''))}")
    lines.append(f"URL           : {data.get('url', '')}")
    return "\n".join(lines)


def court_name(court_id: str) -> str:
    """Return a human-readable name for common court IDs."""
    names = {
        "scotus": "Supreme Court of the United States",
        "ca1": "First Circuit",
        "ca2": "Second Circuit",
        "ca3": "Third Circuit",
        "ca4": "Fourth Circuit",
        "ca5": "Fifth Circuit",
        "ca6": "Sixth Circuit",
        "ca7": "Seventh Circuit",
        "ca8": "Eighth Circuit",
        "ca9": "Ninth Circuit",
        "ca10": "Tenth Circuit",
        "ca11": "Eleventh Circuit",
        "cadc": "D.C. Circuit",
        "cafc": "Federal Circuit",
    }
    return names.get(court_id, court_id or "Unknown")


# ---------------------------------------------------------------------------
# MCP Server logic
# ---------------------------------------------------------------------------

async def serve(api_key: Optional[str] = None) -> None:
    """Run the MCP stdio server with the given API configuration."""

    headers = {
        "User-Agent": f"{APP_NAME}/{APP_VERSION}",
    }
    if api_key:
        headers["Authorization"] = f"Token {api_key}"

    async with httpx.AsyncClient(base_url=BASE_URL, headers=headers, timeout=30.0) as client:
        server = Server(APP_NAME)

        # ---- list_tools --------------------------------------------------
        async def handle_list_tools() -> ListToolsResult:
            return ListToolsResult(tools=ALL_TOOLS)

        server.list_tools = handle_list_tools  # type: ignore[assignment]

        # ---- call_tool ---------------------------------------------------
        async def handle_call_tool(req: CallToolRequest) -> CallToolResult:
            name = req.name
            args = req.arguments or {}

            try:
                if name == "search_cases":
                    result = await _search_cases(client, args)
                elif name == "get_opinion":
                    result = await _get_opinion(client, args)
                elif name == "get_court":
                    result = await _get_court(client, args)
                elif name == "get_recent_opinions":
                    result = await _get_recent_opinions(client, args)
                else:
                    return CallToolResult(
                        content=[{"type": "text", "text": f"Unknown tool: {name}"}],
                        isError=True,
                    )

                return CallToolResult(
                    content=[{"type": "text", "text": result}],
                    isError=False,
                )
            except Exception as exc:
                return CallToolResult(
                    content=[{"type": "text", "text": f"Error: {exc}"}],
                    isError=True,
                )

        server.call_tool = handle_call_tool  # type: ignore[assignment]

        # ---- run stdio server --------------------------------------------
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

async def _search_cases(
    client: httpx.AsyncClient,
    args: dict[str, Any],
) -> str:
    query = args.get("query", "").strip()
    if not query:
        return "Error: 'query' parameter is required."

    court_filter = args.get("court_filter", "").strip()
    limit = min(args.get("limit", 10), 100)

    params: dict[str, Any] = {"q": query, "limit": limit, "type": "o"}
    if court_filter:
        params["court"] = court_filter

    data = await _api_get(client, "/search/", params=params)
    if "error" in data:
        return data["error"]

    return _format_search_results(data)


async def _get_opinion(
    client: httpx.AsyncClient,
    args: dict[str, Any],
) -> str:
    cluster_id = args.get("cluster_id")
    if cluster_id is None:
        return "Error: 'cluster_id' parameter is required."

    data = await _api_get(client, f"/clusters/{cluster_id}/")
    if "error" in data:
        return data["error"]

    return _format_cluster(data)


async def _get_court(
    client: httpx.AsyncClient,
    args: dict[str, Any],
) -> str:
    court_id = args.get("court_id", "").strip()
    if not court_id:
        return "Error: 'court_id' parameter is required."

    data = await _api_get(client, f"/courts/{court_id}/")
    if "error" in data:
        return data["error"]

    return _format_court(data)


async def _get_recent_opinions(
    client: httpx.AsyncClient,
    args: dict[str, Any],
) -> str:
    days = max(1, min(args.get("days", 7), 365))
    limit = min(args.get("limit", 10), 100)

    cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    params: dict[str, Any] = {
        "q": f"dateFiled:>={cutoff}",
        "limit": limit,
        "type": "o",
        "order_by": "dateFiled desc",
    }

    data = await _api_get(client, "/search/", params=params)
    if "error" in data:
        return data["error"]

    return _format_search_results(data)


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Court Records MCP Server — CourtListener REST v4",
    )
    parser.add_argument(
        "--api-key",
        help="CourtListener API token (optional, for premium/higher rate limits)",
        default=None,
    )
    args = parser.parse_args()

    try:
        asyncio.run(serve(api_key=args.api_key))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
