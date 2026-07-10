"""System tools — the model's hands on the machine: filesystem, shell, PowerShell, web.

Exposed as ephemeral tools (ToolSpec.from_callable). These give the served model REAL
local access — read/write files, run shell + PowerShell commands, and search the web.
That is the agentic intent of the harness; treat it like any local automation (the model
runs on, and acts on, the operator's own machine). Every action has a timeout and a capped
output. Pair with harness.skills.memory.MEMORY_TOOLS + harness.mcp.run_python.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request

_OUT_CAP = 2000


def _cap(s: str) -> str:
    s = (s or "").strip()
    return s if len(s) <= _OUT_CAP else s[:_OUT_CAP] + "\n…(truncated)"


# ──── Filesystem ───────────────────────────────────────────────────────────
def list_dir(path: str = ".") -> str:
    """List the entries in a directory."""
    try:
        items = sorted(os.listdir(path))
        return _cap("\n".join(items)) or "(empty)"
    except Exception as exc:
        return f"[list_dir error: {exc}]"


def read_file(path: str) -> str:
    """Read and return the text contents of a file."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return _cap(f.read())
    except Exception as exc:
        return f"[read_file error: {exc}]"


def write_file(path: str, content: str) -> str:
    """Write text content to a file (overwrites)."""
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"wrote {len(content)} chars to {path}"
    except Exception as exc:
        return f"[write_file error: {exc}]"


# ──── Shell / PowerShell ─────────────────────────────────────────────────────
def run_shell(command: str) -> str:
    """Run a shell command and return its output (30s timeout)."""
    try:
        p = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
        return _cap(p.stdout + p.stderr) or "(no output)"
    except Exception as exc:
        return f"[run_shell error: {exc}]"


def run_powershell(command: str) -> str:
    """Run a Windows PowerShell command and return its output (30s timeout)."""
    try:
        p = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True, text=True, timeout=30)
        return _cap(p.stdout + p.stderr) or "(no output)"
    except Exception as exc:
        return f"[run_powershell error: {exc}]"


# ──── Code ───────────────────────────────────────────────────────────────────
def run_python(code: str) -> str:
    """Execute Python code and return its output; a final bare expression is auto-printed (REPL-style, 15s timeout)."""
    wrapper = (
        "import ast\n"
        "src=" + repr(code) + "\n"
        "try:\n"
        "    t=ast.parse(src)\n"
        "    if t.body and isinstance(t.body[-1], ast.Expr):\n"
        "        last=ast.Expression(t.body.pop().value)\n"
        "        exec(compile(t,'<t>','exec'), globals())\n"
        "        v=eval(compile(last,'<t>','eval'), globals())\n"
        "        (print(v) if v is not None else None)\n"
        "    else:\n"
        "        exec(compile(t,'<t>','exec'), globals())\n"
        "except Exception as e:\n"
        "    print('Error:', repr(e))\n"
    )
    try:
        p = subprocess.run([sys.executable, "-c", wrapper], capture_output=True, text=True, timeout=15)
        return _cap(p.stdout + p.stderr) or "(no output)"
    except Exception as exc:
        return f"[run_python error: {exc}]"


# ──── Time ───────────────────────────────────────────────────────────────────
def get_time() -> str:
    """Return the current local date, time, and timezone."""
    import datetime
    now = datetime.datetime.now().astimezone()
    return now.strftime("%A %Y-%m-%d %H:%M:%S %Z (UTC%z)")


def web_fetch(url: str) -> str:
    """Fetch a URL and return its text content (HTML tags stripped, 15s timeout)."""
    import re as _re
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Shannon-Prime)"})
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read(400_000).decode("utf-8", "replace")
        text = _re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw, flags=_re.DOTALL | _re.IGNORECASE)
        text = _re.sub(r"<[^>]+>", " ", text)
        text = _re.sub(r"\s+", " ", text).strip()
        return _cap(text) or "(empty page)"
    except Exception as exc:
        return f"[web_fetch error: {exc}]"


# ──── Web ────────────────────────────────────────────────────────────────────
def web_search(query: str) -> str:
    """Search the web and return a short text summary of the top results."""
    try:
        url = "https://api.duckduckgo.com/?" + urllib.parse.urlencode(
            {"q": query, "format": "json", "no_html": 1, "skip_disambig": 1})
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Shannon-Prime)"})
        with urllib.request.urlopen(req, timeout=15) as r:
            j = json.loads(r.read().decode("utf-8", "replace"))
        parts = []
        if j.get("AbstractText"):
            parts.append(j["AbstractText"])
        if j.get("Answer"):
            parts.append(str(j["Answer"]))
        for t in j.get("RelatedTopics", [])[:5]:
            if isinstance(t, dict) and t.get("Text"):
                parts.append("- " + t["Text"])
        out = "\n".join(parts)
        return _cap(out) or "(no instant answer; try a more specific/entity query)"
    except Exception as exc:
        return f"[web_search error: {exc}]"


FILESYSTEM_TOOLS = [list_dir, read_file, write_file]
SHELL_TOOLS = [run_shell, run_powershell]
CODE_TOOLS = [run_python]
WEB_TOOLS = [web_search, web_fetch]
TIME_TOOLS = [get_time]
SYSTEM_TOOLS = FILESYSTEM_TOOLS + SHELL_TOOLS + CODE_TOOLS + WEB_TOOLS + TIME_TOOLS
