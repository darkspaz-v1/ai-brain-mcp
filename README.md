# AI Brain Vault — MCP Server

A local, **read-only** [Model Context Protocol](https://modelcontextprotocol.io) server
over the Obsidian second-brain vault at `Desktop\AI Brain\AI Brain`, so any MCP client can
answer *"what did I already decide about X?"* without hand-grepping the vault.

Built in Python with the official MCP SDK (`FastMCP`). **No external API, no API keys,
works offline.**

## What this replaces

The global `CLAUDE.md` instruction — *grep `vault-index.json` first, then read the matched
note under `wiki/`, then fall back to a wider search* — is a workflow that had to be
followed by hand every session. This server turns each of those three steps into a tool,
so the convention is encoded rather than remembered:

| Step | Tool |
|------|------|
| 1. Grep the flat manifest | `vault_search` |
| 2. Read the matched note in full | `vault_get_note` |
| 3. Fall back to full-text search | `vault_grep` |

It also works where the `obsidian` MCP server doesn't: that one needs the Obsidian app
running with its local REST plugin listening on a port (it currently fails with
`ConnectionRefused`). This server reads the vault files straight off disk, so it works
whether or not Obsidian is open.

## Tools

| Tool | Purpose |
|------|---------|
| `vault_search` | Search the manifest by topic, tags, path, and summary |
| `vault_get_note` | Read one note's full markdown |
| `vault_grep` | Full-text search across note bodies (literal or regex) |
| `vault_list_topics` | Enumerate topics with note counts |

### Ranking

`vault_search` splits the query into terms and scores each note, weighted so a structural
hit beats an incidental mention:

| Field | Weight |
|-------|--------|
| topic | 10 |
| tags | 8 |
| path | 5 |
| summary | 3 |

Results come back best-first. If the manifest misses — it holds one-line summaries, not
full text — `vault_grep` searches the note bodies directly.

## Why it's read-only

The vault has a specific update convention: frontmatter schema, the `_master-index.md`
table of contents, and the `vault-index.json` manifest all have to move together (see
`wiki/_master-index.md`). A write tool that got that only partly right would desync the
index quietly, which is worse than having no write tool — you'd stop trusting search
results without knowing why.

Notes stay authored the normal way: by hand, or by an agent following the documented
convention. If you later want writes, the right shape is a single
`vault_add_note` that updates the note, the master index, and the manifest in one atomic
operation — not a bare file-write tool.

## Path safety

`vault_get_note` resolves every path against the vault root and refuses anything that
escapes it, so `../../../Windows/System32/...` returns an error rather than file contents.
This server can only ever read inside the vault.

## Setup

Requires Python 3.10+ and the MCP SDK:

```bash
pip install "mcp[cli]"
```

## Register with Claude Code

```bash
claude mcp add ai-brain -- python "C:\Users\anshu\Desktop\Claude\ai-brain-mcp\server.py"
```

## Register with Claude Desktop

Add to `%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "ai-brain": {
      "command": "python",
      "args": ["C:\\Users\\anshu\\Desktop\\Claude\\ai-brain-mcp\\server.py"]
    }
  }
}
```

Restart Claude Desktop afterwards.

## Test

```bash
python test_server.py
```

19 assertions covering manifest loading, ranking order, note reading, path-traversal
refusal, grep (literal + regex), and error paths. The server is read-only, so the test
runs against the real vault and cannot modify it.

## Config

Reads `C:\Users\anshu\Desktop\AI Brain\AI Brain` by default. Override with the
`AI_BRAIN_VAULT` environment variable.

## Tech

Python · MCP Python SDK (FastMCP) · Pydantic v2 · asyncio
