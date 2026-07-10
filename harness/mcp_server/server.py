"""Shannon-Prime FastMCP server — the system's capabilities over MCP.

Exposes the SAME battle-tested harness skills the served model uses
(harness/skills/system_tools.py + memory tools) as a standard MCP server.
Run:
    python -m harness.mcp_server              # stdio (for MCP clients / the bridge)
    python -m harness.mcp_server --http 8765  # streamable-HTTP on a port

Customizing: add plain functions to harness/mcp_server/custom_tools.py —
anything in its CUSTOM_TOOLS list (or any public function if the list is
absent) is auto-registered. No FastMCP knowledge needed.
"""
from __future__ import annotations

import inspect
import os
import sys

from fastmcp import FastMCP

mcp = FastMCP(
    "shannon-prime",
    instructions=(
        "Shannon-Prime system server: local filesystem, shell/PowerShell, Python, "
        "web search/fetch, clock, and the persistent fact memory of the local model."
    ),
)


def _register(fn, name: str | None = None) -> None:
    """Register a plain function as an MCP tool (docstring = description)."""
    mcp.tool(fn, name=name or fn.__name__)


def _register_defaults() -> None:
    from harness.skills.system_tools import SYSTEM_TOOLS

    for fn in SYSTEM_TOOLS:
        _register(fn)

    # Memory tools are optional: they need SP_RECALL_REGISTRY to point at the
    # daemon's production registry. Skipped silently when unset.
    if os.environ.get("SP_RECALL_REGISTRY"):
        try:
            from harness.skills.memory import MEMORY_TOOLS

            for fn in MEMORY_TOOLS:
                _register(fn)
        except Exception as exc:  # pragma: no cover
            print(f"[mcp_server] memory tools skipped: {exc}", file=sys.stderr)


def _register_custom() -> None:
    """Pull in operator-defined tools from custom_tools.py (easily customizable)."""
    try:
        from harness.mcp_server import custom_tools
    except ImportError:
        return
    fns = getattr(custom_tools, "CUSTOM_TOOLS", None)
    if fns is None:
        fns = [
            f for n, f in vars(custom_tools).items()
            if inspect.isfunction(f) and not n.startswith("_")
        ]
    for fn in fns:
        _register(fn)


_register_defaults()
_register_custom()


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--http" in args:
        i = args.index("--http")
        port = int(args[i + 1]) if len(args) > i + 1 and args[i + 1].isdigit() else 8765
        mcp.run(transport="http", host="127.0.0.1", port=port)
    else:
        mcp.run()  # stdio
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
