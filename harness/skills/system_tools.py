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
import re
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
# Verified against the live markup rather than assumed: the classes are result__a and
# result__snippet. My first cut guessed "result-link"/"result-snippet" and silently matched
# NOTHING — which would have shipped a search tool that returns "(nothing found)" for every
# query in the world, i.e. exactly the bug I was fixing, wearing a different hat. A scraper
# written against remembered HTML is a scraper written against no HTML.
_DDG_RESULT = re.compile(
    r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>'
    r'(?:.*?class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>)?', re.S | re.I)
_TAGS = re.compile(r"<[^>]+>")


def _clean(s: str) -> str:
    import html
    return html.unescape(_TAGS.sub("", s)).strip()


def search_web(query: str, n: int = 5) -> list:
    """THE HARNESS DOES THE SEARCHING. Returns [{title, url, snippet}] — actual results.

    WHAT THIS REPLACES, AND WHY THAT MATTERS. web_search() used to hit DuckDuckGo's INSTANT
    ANSWER api, which only ever returns something for entity and definition lookups — "who
    was Claude Shannon", "what is a GPU". Ask it the kind of thing a person actually wants
    ("is an RTX 3090 in stock under $1500") and it returns nothing, every single time, and
    hands back "(no instant answer; try a more specific query)" — which reads like the
    model's fault and is not.

    The operator: "asking the model to perform a websearch is kinda weak, we should be
    having the harness do a lot of the work, bringing back the result we need."

    He is right, and it was worse than he thought: the tool could not search AT ALL. A 12B
    asked to compensate for a search tool that returns nothing will do the only thing left to
    it — invent a plausible answer. Every hallucinated fact that comes out of a web tool
    starts as a tool that returned nothing and a model too polite to say so."""
    out = []
    try:
        data = urllib.parse.urlencode({"q": query}).encode()
        req = urllib.request.Request(
            "https://html.duckduckgo.com/html/", data=data,
            headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                                   "(KHTML, like Gecko) Chrome/120 Safari/537.36"})
        with urllib.request.urlopen(req, timeout=20) as r:
            html_text = r.read().decode("utf-8", "replace")
        for href, title, snip in _DDG_RESULT.findall(html_text)[:n]:
            url = urllib.parse.unquote(href)
            m = re.search(r"uddg=([^&]+)", url)          # DDG wraps the real url
            if m:
                url = urllib.parse.unquote(m.group(1))
            out.append({"title": _clean(title), "url": url, "snippet": _clean(snip)})
    except Exception as exc:
        out.append({"title": f"[search error: {exc}]", "url": "", "snippet": ""})
    return out


def web_search(query: str) -> str:
    """Search the web. Returns the top real results — titles, snippets and links.

    e.g. web_search("RTX 3090 price 2026")
    Answer him from what comes back. If it comes back empty, SAY SO — never fill the gap
    with something that sounds right."""
    hits = search_web(query, n=5)
    if not hits or (len(hits) == 1 and hits[0]["title"].startswith("[search error")):
        return (f"(the search for {query!r} returned nothing — say that plainly, "
                "do not invent an answer)")
    lines = []
    for h in hits:
        lines.append(f"- {h['title']}\n  {h['snippet'][:180]}\n  {h['url']}")
    return _cap("\n".join(lines))


FILESYSTEM_TOOLS = [list_dir, read_file, write_file]
SHELL_TOOLS = [run_shell, run_powershell]
CODE_TOOLS = [run_python]
WEB_TOOLS = [web_search, web_fetch]
TIME_TOOLS = [get_time]
SYSTEM_TOOLS = FILESYSTEM_TOOLS + SHELL_TOOLS + CODE_TOOLS + WEB_TOOLS + TIME_TOOLS
