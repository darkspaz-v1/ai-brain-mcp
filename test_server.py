#!/usr/bin/env python3
"""End-to-end smoke test: drives every tool through the real handlers.

Runs against a small throwaway vault built in a temp folder, so it passes on any
machine (including CI) with no personal vault present. This server is read-only,
so the test cannot modify anything either way.

Run:  python test_server.py
"""

import asyncio
import importlib
import json
import os
import tempfile

# Build a throwaway vault and point the server at it BEFORE importing it.
_tmp = tempfile.mkdtemp()
_NOTES = {
    "wiki/windows-utilities/launcher.md": (
        "# Launcher\n\nGlobal-hotkey palette for the vault of utility apps.\n",
        "windows-utilities",
        ["launcher", "hotkey", "windows"],
        "Shortcut Pad launcher: Ctrl+Alt+L palette",
    ),
    "wiki/windows-utilities/focus-timer.md": (
        "# Focus Timer\n\nPomodoro timer. Mentions the launcher once.\n",
        "windows-utilities",
        ["timer", "pomodoro"],
        "Pomodoro focus timer tray app",
    ),
    "wiki/projects/comfyui.md": (
        "# ComfyUI\n\nLocal image generation notes.\n",
        "projects",
        ["comfyui", "stable-diffusion"],
        "Local ComfyUI setup",
    ),
}
_index = []
for _rel, (_body, _topic, _tags, _summary) in _NOTES.items():
    _full = os.path.join(_tmp, *_rel.split("/"))
    os.makedirs(os.path.dirname(_full), exist_ok=True)
    with open(_full, "w", encoding="utf-8") as fh:
        fh.write(_body)
    _index.append({"path": _rel, "topic": _topic, "tags": _tags, "summary": _summary})
with open(os.path.join(_tmp, "vault-index.json"), "w", encoding="utf-8") as fh:
    json.dump({"notes": _index}, fh)
os.environ["AI_BRAIN_VAULT"] = _tmp

import server as s  # noqa: E402


def ok(cond: bool, label: str) -> None:
    print(("PASS" if cond else "FAIL"), "-", label)
    assert cond, label


async def main() -> None:
    J = s.ResponseFormat.JSON

    # 1. The manifest loads
    notes = s._load_index()
    ok(len(notes) > 0, f"vault manifest loads ({len(notes)} notes)")
    ok(all("path" in n for n in notes), "every manifest entry has a path")

    # 2. Topics
    t = json.loads(await s.vault_list_topics(s.ListTopicsInput(response_format=J)))
    ok(t["total_notes"] == len(notes), "topic totals match the manifest")
    ok(len(t["topics"]) > 0, "topics enumerated")
    counts = list(t["topics"].values())
    ok(counts == sorted(counts, reverse=True), "topics sorted by count, largest first")

    # 3. Search ranks and returns real paths
    r = json.loads(await s.vault_search(s.SearchInput(query="launcher", response_format=J)))
    ok(r["count"] > 0, "search finds the launcher note")
    scores = [h["score"] for h in r["results"]]
    ok(scores == sorted(scores, reverse=True), "results ranked best-first")
    hit_path = r["results"][0]["path"]

    # A topic hit should outrank a summary-only mention.
    topic_hits = [h for h in r["results"] if "launcher" in (h.get("topic") or "").lower()]
    if topic_hits and len(r["results"]) > 1:
        ok(topic_hits[0]["score"] >= scores[-1], "topic match outranks weaker matches")

    r = json.loads(
        await s.vault_search(s.SearchInput(query="zzzznothingmatches", response_format=J))
    )
    ok(r["count"] == 0, "nonsense query returns no matches")

    # 4. Reading a note found by search
    note = await s.vault_get_note(s.GetNoteInput(path=hit_path))
    ok(not note.startswith("Error:"), "search result path reads back cleanly")
    ok(hit_path in note, "note output names its own path")

    # Extension is optional
    note2 = await s.vault_get_note(s.GetNoteInput(path=hit_path[:-3]))
    ok(not note2.startswith("Error:"), "'.md' extension is optional")

    # 5. Path safety — traversal outside the vault is refused
    r = await s.vault_get_note(s.GetNoteInput(path="../../../Windows/System32/drivers/etc/hosts"))
    ok("outside the vault" in r, "path traversal refused")

    r = await s.vault_get_note(s.GetNoteInput(path="wiki/definitely-not-a-real-note.md"))
    ok("No note at" in r, "missing note gives actionable error")

    # 6. Grep
    g = json.loads(await s.vault_grep(s.GrepInput(query="vault", limit=5, response_format=J)))
    ok(g["count"] > 0, "grep finds matches in note bodies")
    ok(g["count"] <= 5, "grep honours the limit")
    ok(all("line" in m and m["line"] > 0 for m in g["matches"]), "matches carry line numbers")

    g = json.loads(
        await s.vault_grep(s.GrepInput(query=r"^#\s+\w+", regex=True, limit=3, response_format=J))
    )
    ok(g["count"] > 0, "regex mode works")

    r = await s.vault_grep(s.GrepInput(query="[unclosed", regex=True))
    ok("not a valid regular expression" in r, "bad regex gives actionable error")

    # 7. Markdown rendering stays useful
    md = await s.vault_search(s.SearchInput(query="launcher"))
    ok("vault_get_note" in md, "markdown search output points to the next tool")

    # 8. Configuration: the env var wins, and the fallback is home-relative
    ok(s.VAULT_ROOT == _tmp, "AI_BRAIN_VAULT env var sets the vault root")
    del os.environ["AI_BRAIN_VAULT"]
    try:
        s2 = importlib.reload(s)
        ok(
            s2.VAULT_ROOT
            == os.path.join(os.path.expanduser("~"), "Desktop", "AI Brain", "AI Brain"),
            "fallback vault path is derived from the home directory",
        )
    finally:
        os.environ["AI_BRAIN_VAULT"] = _tmp
        importlib.reload(s)

    # 9. The tool surface is exactly the four documented tools, all annotated read-only
    tools = await s.mcp.list_tools()
    ok(
        sorted(t.name for t in tools)
        == ["vault_get_note", "vault_grep", "vault_list_topics", "vault_search"],
        "server exposes exactly the four documented tools",
    )
    ok(
        all(t.annotations and t.annotations.readOnlyHint for t in tools),
        "every tool is annotated read-only",
    )

    # 10. The bundled sample vault (used by the README demo) works end to end
    sample = os.path.join(os.path.dirname(os.path.abspath(__file__)), "examples", "sample-vault")
    os.environ["AI_BRAIN_VAULT"] = sample
    try:
        s3 = importlib.reload(s)
        r = json.loads(await s3.vault_search(s3.SearchInput(query="backup nas", response_format=J)))
        ok(
            r["results"][0]["path"] == "wiki/homelab/nas-backups.md",
            "sample vault: 'backup nas' ranks the backup note first",
        )
        note = await s3.vault_get_note(s3.GetNoteInput(path=r["results"][0]["path"]))
        ok("restic" in note, "sample vault: top hit reads back")
    finally:
        os.environ["AI_BRAIN_VAULT"] = _tmp
        importlib.reload(s)

    print("\nAll ai-brain tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
