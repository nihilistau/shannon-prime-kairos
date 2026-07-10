# Shannon-Prime MCP layer (FastMCP)

Added by the 2026-07-10 audit. Two directions, one config.

## 1. The server — Shannon-Prime's hands over MCP

```
python -m harness.mcp_server              # stdio transport
python -m harness.mcp_server --http 8765  # streamable-HTTP on 127.0.0.1:8765
```

Exposes the harness's real skills as MCP tools: `list_dir`, `read_file`,
`write_file`, `run_shell`, `run_powershell`, `run_python`, `web_search`,
`web_fetch`, `get_time`, plus the memory tools (`remember`/`forget`/
`list_memories`/…) when `SP_RECALL_REGISTRY` is set, plus everything in
`harness/mcp_server/custom_tools.py`.

Any MCP client (Claude Desktop, Cowork, another agent) can connect and drive
the system. Example Claude Desktop entry:

```json
"shannon-prime": {
  "command": "python",
  "args": ["-m", "harness.mcp_server"],
  "cwd": "D:/F/shannon-prime-repos/shannon-prime-harness"
}
```

### Customizing
Edit `harness/mcp_server/custom_tools.py` — every plain function there becomes
a tool (docstring = description, type hints = schema). No FastMCP knowledge
needed. Restart the server to pick up changes.

## 2. The bridge — the world's MCP tools for the served model

`mcp_servers.json` (harness root, override with `SP_MCP_CONFIG`) lists servers;
with `SP_MCP_TOOLS=1` the gateway mounts every listed server's tools into the
model's tool loop (they land in the load-on-demand index tier, so the ≤6-tool
rule holds). Native harness tool names win on collisions.

```json
{
  "servers": {
    "shannon":  {"command": "python", "args": ["-m", "harness.mcp_server"]},
    "somehttp": {"url": "http://127.0.0.1:9000/mcp"}
  }
}
```

`run_gateway_system.bat` (engine root) sets `SP_MCP_TOOLS=1` along with the
rest of the agentic stack (`SP_SPINE_TOOLSET`, `SP_SPINE_RECALL`,
`SP_PERSONALITY`).

## Gate

`python tests/h_mcp_server.py` — G-MCP-SERVER: (A) in-process server lists +
calls tools, (B) stdio bridge round-trips, (C) `SP_MCP_TOOLS=1` wiring joins
`all_tools()` without duplicates.
