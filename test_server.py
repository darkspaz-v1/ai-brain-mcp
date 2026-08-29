#!/usr/bin/env python3
"""End-to-end smoke test: drives every tool through the real handlers.

This server is read-only, so the test runs against the real vault and cannot
modify it. It asserts on structure and invariants rather than on specific note
contents, so it keeps passing as the vault grows.

Run:  python test_server.py
"""

import asyncio
import json

import server as s


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

    print("\nAll ai-brain tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
