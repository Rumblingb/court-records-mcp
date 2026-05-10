     1|# # Court Records MCP Server
     2|
     3|**$19/month** — Search US court opinions, cases, and dockets via MCP protocol.
     4|▶ [Subscribe Now](https://buy.stripe.com/dRm6oJ4Hd2Jugek0wz1oI0m)
     5|
     6|An MCP (Model Context Protocol) server for searching and retrieving US federal and state court records via the [CourtListener REST v4 API](https://www.courtlistener.com/api/rest/v4/).
     7|
     8|## Features
     9|
    10|- **search_cases** — Full-text search of US court opinions with optional court filter
    11|- **get_opinion** — Retrieve a full opinion cluster (all opinions tied to a case) by cluster ID
    12|- **get_court** — Get metadata about a specific court (name, jurisdiction, location)
    13|- **get_recent_opinions** — Find opinions filed within the last N days
    14|
    15|## Requirements
    16|
    17|- Python 3.10+
    18|- `mcp` and `httpx` (installed automatically, see below)
    19|
    20|## Installation
    21|
    22|```bash
    23|pip install -r requirements.txt
    24|```
    25|
    26|## Usage
    27|
    28|### Start the server (stdio mode)
    29|
    30|```bash
    31|python server.py
    32|```
    33|
    34|With a CourtListener API token (higher rate limits):
    35|
    36|```bash
    37|python server.py --api-key YOUR_API_TOKEN
    38|```
    39|
    40|The server speaks the MCP JSON-RPC protocol over stdio. Connect it to any MCP-compatible client (Claude Desktop, Continue.dev, etc.).
    41|
    42|### Tool reference
    43|
    44|| Tool | Parameters | Description |
    45||------|-----------|-------------|
    46|| `search_cases` | `query` (str, required), `court_filter` (str, optional), `limit` (int, optional, 1-100) | Full-text search across opinions |
    47|| `get_opinion` | `cluster_id` (int, required) | Get full opinion cluster by ID |
    48|| `get_court` | `court_id` (str, required) | Get court metadata (e.g. `scotus`, `ca9`, `cand`) |
    49|| `get_recent_opinions` | `days` (int, optional, default 7), `limit` (int, optional, default 10) | Recently filed opinions |
    50|
    51|### Example (Python client)
    52|
    53|```python
    54|import json, sys
    55|# Connect to the stdio server and send a JSON-RPC request
    56|request = {
    57|    "jsonrpc": "2.0",
    58|    "id": 1,
    59|    "method": "tools/call",
    60|    "params": {
    61|        "name": "search_cases",
    62|        "arguments": {"query": "Fourth Amendment", "limit": 5}
    63|    }
    64|}
    65|sys.stdout.write(json.dumps(request) + "\n")
    66|sys.stdout.flush()
    67|response = sys.stdin.readline()
    68|print(json.loads(response))
    69|```
    70|
    71|## API Notes
    72|
    73|- **Base URL**: `https://www.courtlistener.com/api/rest/v4/`
    74|- **Rate limits**: ~1,000 requests/day without authentication; significantly higher with a free API token
    75|- **No auth required** for basic usage — the public API is freely accessible
    76|- Get a free API token at: https://www.courtlistener.com/api/rest/v4/register/
    77|
    78|## Deployment
    79|
    80|This server is ready for deployment on [Smithery](https://smithery.ai/). The `smithery.yaml` configures stdio transport with an optional `apiKey` parameter.
    81|
    82|## License
    83|
    84|MIT
    85|