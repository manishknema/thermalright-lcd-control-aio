#!/usr/bin/env python3
"""Build the VigyanBytes brand packs from the brand source (branch vigyan-brand only).

    uv run --with cairosvg python brand/build_brand_packs.py --brand-dir <vigyanbytes-web>/docs/brand

Rules from the brand skill (docs/brand/SKILL.md, revision 4), all enforced here:
  - colours are read from tokens.css at build time, never retyped;
  - two variants: vigyan-ivory (default ground) and vigyan-deep (the LCD sits in
    a dark case frame, rule 1's allowed exception);
  - fonts: Newsreader 600 (display numerals), Public Sans 700/400, JetBrains Mono
    500 (labels/clock); the OFL licence ships next to them;
  - mark: mark-small-* only at <= 32 px for the corner mark (rule 3), the full
    mandala (mark-*.svg) only for the per-theme background mode; one mark per
    frame either way (the renderer suppresses the corner mark in background mode);
  - no emoji or forbidden words in any on-screen text of the built-in designs;
  - text contrast >= 4.5:1 for text/muted on the ground (warned, not silenced).

Outputs (committed on the brand branch; main never carries them):
  src/thermalright_lcd_control/themes/builtin/packs/vigyan-ivory.json
  src/thermalright_lcd_control/themes/builtin/packs/vigyan-deep.json
  src/thermalright_lcd_control/themes/builtin/packs/vigyan/{fonts,marks}/...
"""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PACKS = REPO / "src" / "thermalright_lcd_control" / "themes" / "builtin" / "packs"
DESIGNS = PACKS.parent / "designs"
ASSET_DIR = PACKS / "vigyan"
FONTS = {"display": "newsreader-600-normal.ttf", "bold": "public-sans-700-normal.ttf",
         "body": "public-sans-400-normal.ttf", "mono": "jetbrains-mono-500-normal.ttf"}
# role -> token, per variant (the prototype's mapping, lead design 2026-10-03)
ROLES = {
    "vigyan-deep": {"ink": "vb-deep", "panel": "vb-deep-surface", "line": "vb-deep-line", "text": "vb-paper",
                    "muted": "vb-mist-300", "accent1": "vb-saffron-500", "accent2": "vb-green-500",
                    "accent3": "vb-saffron-300", "ok": "vb-green-500", "warn": "vb-saffron-500", "hot": "vb-saffron-700"},
    "vigyan-ivory": {"ink": "vb-paper", "panel": "vb-paper-2", "line": "vb-paper-3", "text": "vb-ink-900",
                     "muted": "vb-ink-500", "accent1": "vb-saffron-500", "accent2": "vb-green-700",
                     "accent3": "vb-saffron-700", "ok": "vb-green-700", "warn": "vb-saffron-500", "hot": "vb-saffron-700"},
}
FORBIDDEN = re.compile(r"sovereign|revolutionary|game-changing|ai magic|zero risk|!", re.I)
EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿]")


def tokens(brand: Path) -> dict:
    css = (brand / "tokens.css").read_text()
    return {k: v.lower() for k, v in re.findall(r"--(vb-[a-z0-9-]+):\s*(#[0-9a-fA-F]{6})", css)}


def luminance(h: str) -> float:
    def ch(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (int(h[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def check_designs() -> list:
    bad = []
    for f in sorted(DESIGNS.glob("*.json")):
        for w in json.loads(f.read_text()).get("widgets", []):
            for key in ("text", "format"):
                s = str(w.get(key, ""))
                if FORBIDDEN.search(s) or EMOJI.search(s):
                    bad.append(f"{f.name}: {key}={s!r}")
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--brand-dir", required=True, help="vigyanbytes-web/docs/brand")
    a = ap.parse_args()
    brand = Path(a.brand_dir)
    t = tokens(brand)
    import cairosvg

    (ASSET_DIR / "fonts").mkdir(parents=True, exist_ok=True)
    (ASSET_DIR / "marks").mkdir(parents=True, exist_ok=True)
    for f in FONTS.values():
        shutil.copy2(brand / "fonts" / f, ASSET_DIR / "fonts" / f)
    shutil.copy2(brand / "fonts" / "OFL.txt", ASSET_DIR / "fonts" / "OFL.txt")
    for v in ("deep", "ivory"):
        # Small mark rasterised at 2x of its 32 px ceiling; the renderer scales it to <= 32 px.
        cairosvg.svg2png(url=str(brand / "web" / f"mark-small-{v}.svg"),
                         write_to=str(ASSET_DIR / "marks" / f"mark-small-{v}.png"), output_width=64)
        cairosvg.svg2png(url=str(brand / "web" / f"mark-{v}.svg"),
                         write_to=str(ASSET_DIR / "marks" / f"mark-{v}.png"), output_width=512)

    warnings = []
    for pid, roles in ROLES.items():
        colors = {role: t[tok] for role, tok in roles.items()}
        for role in ("text", "muted"):
            c = contrast(colors[role], colors["ink"])
            if c < 4.5:
                warnings.append(f"{pid}: {role} on ink contrast {c:.2f} < 4.5")
        doc = {
            "schema": 1, "id": pid,
            "name": "VigyanBytes " + ("Deep" if pid.endswith("deep") else "Ivory"),
            "ground": "dark" if pid.endswith("deep") else "light",
            "colors": colors,
            "fonts": {role: f"vigyan/fonts/{f}" for role, f in FONTS.items()},
            "mark": {"small": {"deep": "vigyan/marks/mark-small-deep.png", "ivory": "vigyan/marks/mark-small-ivory.png"},
                     "big": {"deep": "vigyan/marks/mark-deep.png", "ivory": "vigyan/marks/mark-ivory.png"}},
            "default_mark": "corner",
            "license": "VigyanBytes brand; fonts SIL OFL 1.1 (vigyan/fonts/OFL.txt). Generated from tokens.css; do not edit.",
        }
        (PACKS / f"{pid}.json").write_text(json.dumps(doc, indent=2) + "\n")
        print(f"wrote {pid}.json")
    bad = check_designs()
    for w in warnings:
        print("WARN", w)
    if bad:
        print("ERROR forbidden text in designs:", *bad, sep="\n  ")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
