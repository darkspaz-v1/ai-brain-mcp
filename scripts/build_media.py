#!/usr/bin/env python3
"""Rebuild docs/media/*.png for the README.

Starts the real server over stdio against examples/sample-vault (invented notes, never a real
vault), drives it with the MCP client, saves the raw responses to docs/media/demo-capture.txt and
renders them into a terminal-style image. Needs Pillow (`pip install pillow`) on top of
requirements.txt. Run from the repo root:  python scripts/build_media.py
"""

import asyncio
import os
import sys

from PIL import Image, ImageDraw, ImageFont
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MEDIA = os.path.join(ROOT, "docs", "media")
VAULT = os.path.join(ROOT, "examples", "sample-vault")

# ---- rendering helpers (Pillow) --------------------------------------------

FONTS = "C:/Windows/Fonts/"
BG, PANEL, BAR = (13, 17, 23), (22, 27, 34), (33, 38, 45)
FG, DIM, ACCENT = (201, 209, 217), (125, 133, 144), (88, 166, 255)
GREEN, AMBER, PINK = (86, 211, 100), (227, 179, 65), (255, 123, 114)


def _font(name, size):
    try:
        return ImageFont.truetype(FONTS + name, size)
    except OSError:
        return ImageFont.load_default()


def terminal_png(path, caption, title, lines, width=1200, size=17, pad=28):
    """Render styled lines to a dark terminal-style PNG.

    lines: list of lines; each line is a list of (text, colour) segments, or None for a blank line.
    """
    mono = _font("consola.ttf", size)
    ui = _font("segoeui.ttf", 18)
    ui_b = _font("segoeuib.ttf", 20)
    lh = int(size * 1.5)
    cap_h, bar_h = 58, 40
    height = cap_h + bar_h + pad + lh * len(lines) + pad
    img = Image.new("RGB", (width, height), BG)
    d = ImageDraw.Draw(img)
    d.text((pad, 16), caption, font=ui_b, fill=(240, 246, 252))
    top = cap_h
    d.rounded_rectangle((12, top, width - 12, height - 12), radius=10, fill=PANEL, outline=BAR)
    d.rounded_rectangle((12, top, width - 12, top + bar_h), radius=10, fill=BAR)
    d.rectangle((12, top + 20, width - 12, top + bar_h), fill=BAR)
    for i, col in enumerate(((255, 95, 86), (255, 189, 46), (39, 201, 63))):
        d.ellipse((30 + i * 24, top + 13, 44 + i * 24, top + 27), fill=col)
    d.text((120, top + 8), title, font=ui, fill=DIM)
    y = top + bar_h + pad // 2
    for segs in lines:
        x = pad + 8
        for text, col in segs or []:
            d.text((x, y), text, font=mono, fill=col)
            x += mono.getlength(text)
        y += lh
    img = img.quantize(colors=64, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    img.save(path, optimize=True)


def social_png(path, title, outcome, chips, footer):
    """1280x640 social preview: title, outcome sentence, tool chips, footer."""
    w, h = 1280, 640
    img = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, 14, h), fill=ACCENT)
    d.text((80, 90), title, font=_font("segoeuib.ttf", 84), fill=(240, 246, 252))
    y = 215
    for line in outcome:
        d.text((80, y), line, font=_font("segoeui.ttf", 38), fill=FG)
        y += 54
    mono = _font("consola.ttf", 26)
    x, y = 80, max(y + 40, 380)
    for chip in chips:
        tw = mono.getlength(chip)
        if x + tw + 40 > w - 60:
            x, y = 80, y + 64
        d.rounded_rectangle((x, y, x + tw + 32, y + 48), radius=10, fill=PANEL, outline=(48, 54, 61), width=2)
        d.text((x + 16, y + 8), chip, font=mono, fill=ACCENT)
        x += tw + 32 + 16
    d.text((80, h - 80), footer, font=_font("segoeui.ttf", 28), fill=DIM)
    img.quantize(colors=48, dither=Image.Dither.NONE).save(path, optimize=True)


def wrap_out(text, max_chars=104, max_lines=None):
    """Split captured tool output into display lines (no rewriting, only wrapping/truncation)."""
    out = []
    for raw in text.splitlines():
        while len(raw) > max_chars:
            cut = raw.rfind(" ", 0, max_chars)
            cut = cut if cut > 40 else max_chars
            out.append(raw[:cut])
            raw = "    " + raw[cut:].lstrip()
        out.append(raw)
    if max_lines and len(out) > max_lines:
        hidden = len(out) - max_lines
        out = out[:max_lines] + [f"[... {hidden} more line(s) not shown in this image]"]
    return out


async def capture():
    params = StdioServerParameters(
        command=sys.executable,
        args=[os.path.join(ROOT, "server.py")],
        env={**os.environ, "AI_BRAIN_VAULT": VAULT},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = [t.name for t in (await session.list_tools()).tools]
            q = {"query": "backup nas", "limit": 3}
            search = await session.call_tool("vault_search", {"params": q})
            path = "wiki/homelab/nas-backups.md"
            note = await session.call_tool("vault_get_note", {"params": {"path": path}})
            return tools, q, path, search.content[0].text, note.content[0].text


def main():
    os.makedirs(MEDIA, exist_ok=True)
    tools, q, path, search_out, note_out = asyncio.run(capture())
    with open(os.path.join(MEDIA, "demo-capture.txt"), "w", encoding="utf-8") as fh:
        fh.write("# Raw responses from server.py against examples/sample-vault\n")
        fh.write(f"# tools/list -> {', '.join(tools)}\n\n")
        fh.write(f"## vault_search {q}\n{search_out}\n\n## vault_get_note {path}\n{note_out}\n")

    L = []
    L.append([("You: ", ACCENT), ("Have I already set up nightly backups anywhere?", FG)])
    L.append(None)
    L.append([("assistant> ", GREEN), ('vault_search {"query": "backup nas"}', AMBER)])
    for ln in wrap_out(search_out, max_lines=16):
        L.append([(ln, DIM if ln.startswith("_") or ln.startswith("[") else FG)])
    L.append(None)
    L.append([("assistant> ", GREEN), (f'vault_get_note {{"path": "{path}"}}', AMBER)])
    for ln in wrap_out(note_out, max_lines=26):
        L.append([(ln, DIM if ln.startswith("[") else FG)])
    L.append(None)
    L.append([("Assistant: ", ACCENT), ("Yes. Restic to the NAS at 02:30 nightly, kept 7 daily / 4 weekly / 6 monthly,", FG)])
    L.append([("           with a monthly restore drill. Use the UNC path, not a mapped drive.", FG)])
    L.append([("           ", FG), ("Source: wiki/homelab/nas-backups.md", GREEN)])
    L.append([("           (reply text written by hand for this image; the tool output above is real)", DIM)])
    terminal_png(
        os.path.join(MEDIA, "demo.png"),
        "Example session against a sample vault (invented notes, real server output)",
        "ai-brain-mcp  |  vault_search -> vault_get_note -> cited answer",
        L,
    )
    social_png(
        os.path.join(MEDIA, "social-preview.png"),
        "ai-brain-mcp",
        ["Let an AI assistant search and read your Obsidian", "vault. Read-only by construction."],
        ["vault_search", "vault_get_note", "vault_grep", "vault_list_topics"],
        "MCP server  |  Python  |  no write tools exist",
    )
    for f in ("demo.png", "social-preview.png"):
        print(f, os.path.getsize(os.path.join(MEDIA, f)) // 1024, "KB")


if __name__ == "__main__":
    main()
