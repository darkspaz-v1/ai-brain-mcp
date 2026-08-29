#!/usr/bin/env python3
"""
AI Brain Vault MCP Server.

A local, read-only MCP server over the Obsidian second-brain vault at
C:\\Users\\anshu\\Desktop\\AI Brain\\AI Brain, so any MCP client can answer
"what did I already decide/build/document about X" without hand-grepping.

It encodes the vault's own documented lookup convention as tools:

    1. vault_search      -> grep the flat manifest (vault-index.json) first;
                            it carries tags + a one-line summary per note, so
                            the right file is usually found in one call.
    2. vault_get_note    -> read the matched note under wiki/ for full context.
    3. vault_grep        -> only if the index came up short, full-text search
                            the note bodies themselves.

WRITE ACCESS IS DELIBERATELY OMITTED. The vault has a specific update
convention (frontmatter schema, `_master-index.md` table of contents, and the
vault-index.json manifest all have to move together). A write tool that got
that only half-right would corrupt the index quietly, which is worse than no
write tool. Notes are still authored the normal way — by hand or by an agent
following the convention in wiki/_master-index.md.

Tools:
    - vault_search       Search the note manifest by keyword.
    - vault_get_note     Read one note's full markdown.
    - vault_grep         Full-text search across note bodies.
    - vault_list_topics  Enumerate topics with note counts.
"""

from __future__ import annotations

import json
import os
import re
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Configuration & storage
# ---------------------------------------------------------------------------

mcp = FastMCP("aibrain_mcp")

# Vault root. Override with AI_BRAIN_VAULT.
VAULT_ROOT = os.environ.get(
    "AI_BRAIN_VAULT",
    r"C:\Users\anshu\Desktop\AI Brain\AI Brain",
)
INDEX_FILE = os.path.join(VAULT_ROOT, "vault-index.json")

# Cap on how much of a single note is returned, to keep responses manageable.
_MAX_NOTE_CHARS = 60_000


class ResponseFormat(str, Enum):
    """Output format for tool responses."""

    MARKDOWN = "markdown"
    JSON = "json"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _load_index() -> List[Dict[str, Any]]:
    """Read the note manifest. Returns an empty list if unreadable."""
    if not os.path.exists(INDEX_FILE):
        return []
    try:
        with open(INDEX_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return []
    notes = data.get("notes") if isinstance(data, dict) else data
    return notes if isinstance(notes, list) else []


def _safe_note_path(rel_path: str) -> Optional[str]:
    """Resolve a vault-relative path, refusing anything outside the vault.

    Guards against `../` traversal so this server can only ever read the vault.
    """
    candidate = os.path.abspath(os.path.join(VAULT_ROOT, rel_path))
    root = os.path.abspath(VAULT_ROOT)
    if os.path.commonpath([candidate, root]) != root:
        return None
    return candidate


def _iter_notes() -> List[str]:
    """List every markdown file under the vault, as vault-relative paths."""
    out: List[str] = []
    for dirpath, dirnames, filenames in os.walk(VAULT_ROOT):
        dirnames[:] = [d for d in dirnames if d not in (".git", ".obsidian", ".trash")]
        for fn in filenames:
            if fn.lower().endswith(".md"):
                full = os.path.join(dirpath, fn)
                out.append(os.path.relpath(full, VAULT_ROOT).replace("\\", "/"))
    return sorted(out)


def _score(note: Dict[str, Any], terms: List[str]) -> int:
    """Rank a manifest entry against search terms.

    Weighted so a topic or tag hit outranks an incidental summary mention.
    """
    topic = (note.get("topic") or "").lower()
    tags = " ".join(note.get("tags") or []).lower()
    summary = (note.get("summary") or "").lower()
    path = (note.get("path") or "").lower()

    total = 0
    for term in terms:
        if term in topic:
            total += 10
        if term in tags:
            total += 8
        if term in path:
            total += 5
        if term in summary:
            total += 3
    return total


def _format_hit_markdown(note: Dict[str, Any]) -> str:
    """Render one manifest entry as a markdown block."""
    lines = [f"### `{note.get('path', '?')}`"]
    if note.get("topic"):
        lines.append(f"- **Topic**: {note['topic']}")
    if note.get("tags"):
        lines.append(f"- **Tags**: {', '.join(note['tags'])}")
    if note.get("summary"):
        lines.append(f"- **Summary**: {note['summary']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Input models
# ---------------------------------------------------------------------------


class SearchInput(BaseModel):
    """Input for searching the note manifest."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    query: str = Field(
        ...,
        description=(
            "Keywords to match against note topic, tags, path, and summary. "
            "Space-separated terms are OR-ed and ranked, e.g. 'comfyui stable diffusion'."
        ),
        min_length=1,
        max_length=200,
    )
    limit: int = Field(default=10, description="Maximum results to return", ge=1, le=50)
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="Output format: 'markdown' or 'json'",
    )

    @field_validator("query")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Query cannot be empty or whitespace only")
        return v.strip()


class GetNoteInput(BaseModel):
    """Input for reading one note."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    path: str = Field(
        ...,
        description=(
            "Vault-relative path to the note, exactly as returned by "
            "vault_search (e.g. 'wiki/windows-utilities/launcher.md')."
        ),
        min_length=1,
        max_length=400,
    )


class GrepInput(BaseModel):
    """Input for full-text search across note bodies."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    query: str = Field(
        ...,
        description=(
            "Text or regular expression to find inside note bodies. Use this "
            "only when vault_search on the manifest came up short."
        ),
        min_length=1,
        max_length=200,
    )
    limit: int = Field(
        default=20, description="Maximum matching lines to return", ge=1, le=100
    )
    regex: bool = Field(
        default=False,
        description="Treat query as a regular expression instead of literal text.",
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="Output format: 'markdown' or 'json'",
    )


class ListTopicsInput(BaseModel):
    """Input for enumerating vault topics."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="Output format: 'markdown' or 'json'",
    )


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool(
    name="vault_search",
    annotations={
        "title": "Search AI Brain Vault",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def vault_search(params: SearchInput) -> str:
    """Search the vault's note manifest — START HERE for any vault question.

    Searches vault-index.json, a flat manifest carrying every note's topic,
    tags, and one-line summary. This is the fastest way to find the right note.
    Follow up with vault_get_note on the best path to read it in full.

    Args:
        params (SearchInput): Validated input containing:
            - query (str): Space-separated keywords.
            - limit (int): Max results (1-50, default 10).
            - response_format (ResponseFormat): 'markdown' or 'json'.

    Returns:
        str: In json, an object of the form:
            {
              "query": str, "count": int,
              "results": [ {"path", "topic", "tags", "summary", "score"}, ... ]
            }
            In markdown, the same matches ranked best-first.
    """
    notes = _load_index()
    if not notes:
        return (
            f"Error: Could not read the vault manifest at {INDEX_FILE}. "
            f"Check that the vault exists, or set AI_BRAIN_VAULT to its location."
        )

    terms = [t for t in params.query.lower().split() if t]
    scored = [(n, _score(n, terms)) for n in notes]
    hits = sorted(
        [(n, s) for n, s in scored if s > 0], key=lambda pair: pair[1], reverse=True
    )[: params.limit]

    if params.response_format == ResponseFormat.JSON:
        return json.dumps(
            {
                "query": params.query,
                "count": len(hits),
                "results": [{**n, "score": s} for n, s in hits],
            },
            indent=2,
            ensure_ascii=False,
        )

    if not hits:
        return (
            f"No notes in the manifest match '{params.query}' "
            f"({len(notes)} notes indexed).\n"
            f"Try vault_grep to search the note bodies directly, or "
            f"vault_list_topics to browse what the vault covers."
        )

    blocks = [f"# Vault search: '{params.query}' ({len(hits)} matches)", ""]
    for note, _ in hits:
        blocks.append(_format_hit_markdown(note))
        blocks.append("")
    blocks.append("_Read one in full with `vault_get_note` using its path._")
    return "\n".join(blocks)


@mcp.tool(
    name="vault_get_note",
    annotations={
        "title": "Read Vault Note",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def vault_get_note(params: GetNoteInput) -> str:
    """Read one vault note's full markdown content.

    Use the exact path returned by vault_search or vault_grep.

    Args:
        params (GetNoteInput): Validated input containing:
            - path (str): Vault-relative path to the note.

    Returns:
        str: The note's markdown, or an actionable error if the path is not a
             readable note inside the vault.
    """
    rel = params.path.strip().replace("\\", "/")
    if not rel.lower().endswith(".md"):
        rel += ".md"

    full = _safe_note_path(rel)
    if full is None:
        return (
            f"Error: '{params.path}' resolves outside the vault. "
            f"Pass a vault-relative path such as 'wiki/<topic>/<note>.md'."
        )
    if not os.path.isfile(full):
        return (
            f"Error: No note at '{rel}'. Use vault_search to find the correct "
            f"path — paths it returns can be passed here verbatim."
        )

    try:
        with open(full, "r", encoding="utf-8") as fh:
            content = fh.read()
    except OSError as exc:
        return f"Error reading '{rel}': {exc}"

    if len(content) > _MAX_NOTE_CHARS:
        content = (
            content[:_MAX_NOTE_CHARS]
            + f"\n\n_[truncated at {_MAX_NOTE_CHARS} characters]_"
        )
    return f"# {rel}\n\n{content}"


@mcp.tool(
    name="vault_grep",
    annotations={
        "title": "Full-Text Search Vault Notes",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def vault_grep(params: GrepInput) -> str:
    """Search inside note bodies, returning matching lines with their paths.

    Slower and noisier than vault_search — reach for it only when the manifest
    search misses, since the manifest holds summaries rather than full text.

    Args:
        params (GrepInput): Validated input containing:
            - query (str): Literal text or a regex.
            - limit (int): Max matching lines (1-100, default 20).
            - regex (bool): Treat query as a regular expression.
            - response_format (ResponseFormat): 'markdown' or 'json'.

    Returns:
        str: In json, an object of the form:
            {
              "query": str, "count": int,
              "matches": [ {"path", "line", "text"}, ... ]
            }
            In markdown, the same matches grouped by note.
    """
    if params.regex:
        try:
            pattern = re.compile(params.query, re.IGNORECASE)
        except re.error as exc:
            return (
                f"Error: '{params.query}' is not a valid regular expression ({exc}). "
                f"Fix the pattern, or set regex=false to search for it literally."
            )
    else:
        pattern = re.compile(re.escape(params.query), re.IGNORECASE)

    matches: List[Dict[str, Any]] = []
    for rel in _iter_notes():
        if len(matches) >= params.limit:
            break
        full = os.path.join(VAULT_ROOT, rel)
        try:
            with open(full, "r", encoding="utf-8", errors="replace") as fh:
                for lineno, line in enumerate(fh, start=1):
                    if pattern.search(line):
                        matches.append(
                            {"path": rel, "line": lineno, "text": line.strip()[:300]}
                        )
                        if len(matches) >= params.limit:
                            break
        except OSError:
            continue

    if params.response_format == ResponseFormat.JSON:
        return json.dumps(
            {"query": params.query, "count": len(matches), "matches": matches},
            indent=2,
            ensure_ascii=False,
        )

    if not matches:
        return (
            f"No note bodies contain '{params.query}'. "
            f"The vault may simply not cover this yet."
        )

    blocks = [f"# Vault grep: '{params.query}' ({len(matches)} lines)", ""]
    current = None
    for m in matches:
        if m["path"] != current:
            current = m["path"]
            blocks.append(f"### `{current}`")
        blocks.append(f"- L{m['line']}: {m['text']}")
    blocks.append("")
    blocks.append("_Read any of these in full with `vault_get_note`._")
    return "\n".join(blocks)


@mcp.tool(
    name="vault_list_topics",
    annotations={
        "title": "List Vault Topics",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def vault_list_topics(params: ListTopicsInput) -> str:
    """List every topic the vault covers, with note counts.

    Use this to orient before searching when you do not yet know what the
    vault calls something.

    Args:
        params (ListTopicsInput): Validated input containing:
            - response_format (ResponseFormat): 'markdown' or 'json'.

    Returns:
        str: In json, an object of the form:
            {"total_notes": int, "topics": {"<topic>": int, ...}}
            In markdown, the same counts sorted largest-first.
    """
    notes = _load_index()
    if not notes:
        return (
            f"Error: Could not read the vault manifest at {INDEX_FILE}. "
            f"Check that the vault exists, or set AI_BRAIN_VAULT to its location."
        )

    topics: Dict[str, int] = {}
    for note in notes:
        topic = note.get("topic") or "(untagged)"
        topics[topic] = topics.get(topic, 0) + 1

    ordered = dict(sorted(topics.items(), key=lambda kv: (-kv[1], kv[0])))

    if params.response_format == ResponseFormat.JSON:
        return json.dumps(
            {"total_notes": len(notes), "topics": ordered}, indent=2, ensure_ascii=False
        )

    lines = [f"# Vault topics ({len(notes)} notes across {len(ordered)} topics)", ""]
    for topic, count in ordered.items():
        lines.append(f"- **{topic}** — {count} note(s)")
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run()
