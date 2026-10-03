# SPDX-License-Identifier: Apache-2.0
"""Theme packs: palette + fonts + optional mark, independent of the layout.

A pack is one JSON file (builtin/packs/<id>.json, or <state>/packs/<id>.json for
user packs). Schema (version 1):

    {
      "schema": 1,
      "id": "slate",
      "name": "Slate",
      "ground": "dark",                 # dark | light (mark variant "auto" uses this)
      "colors": {                       # all "#rrggbb"
        "ink": ..., "panel": ..., "line": ..., "text": ..., "muted": ...,
        "accent1": ..., "accent2": ..., "accent3": ...,
        "ok": ..., "warn": ..., "hot": ...           # heat scale: ok -> warn -> hot
      },
      "fonts": {                        # optional; paths relative to the pack file,
        "display": "fonts/x.ttf",       # absolute, or null for the built-in default
        "bold": null, "body": null, "mono": null
      },
      "mark": {                         # optional brand mark images (PNG, RGBA)
        "small": {"deep": "marks/mark-small-deep.png", "ivory": "..."},
        "big":   {"deep": "marks/mark-big-deep.png",   "ivory": "..."}
      },
      "default_mark": "none"            # corner | background | none
    }

Font roles: display = big numerals, bold = labels/values, body = small text,
mono = clocks. More packs are just more files.
"""
import json
import os
import re
from pathlib import Path
from typing import Optional

BUILTIN = Path(__file__).parent / "builtin" / "packs"
COLOR_KEYS = ("ink", "panel", "line", "text", "muted", "accent1", "accent2", "accent3", "ok", "warn", "hot")
FONT_ROLES = ("display", "bold", "body", "mono")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")
HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def hex_rgb(h: str) -> tuple:
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def validate(doc: dict) -> dict:
    """Raise ValueError on a malformed pack; returns the normalised doc."""
    if not isinstance(doc, dict):
        raise ValueError("pack must be an object")
    if not ID_RE.match(str(doc.get("id", ""))):
        raise ValueError("pack id must be lowercase letters, digits and hyphens")
    colors = doc.get("colors") or {}
    for k in COLOR_KEYS:
        if not HEX_RE.match(str(colors.get(k, ""))):
            raise ValueError(f"pack colour '{k}' must be #rrggbb")
    out = {
        "schema": 1, "id": doc["id"], "name": str(doc.get("name") or doc["id"])[:60],
        "ground": "light" if doc.get("ground") == "light" else "dark",
        "colors": {k: colors[k].lower() for k in COLOR_KEYS},
        "fonts": {r: (doc.get("fonts") or {}).get(r) for r in FONT_ROLES},
        "mark": doc.get("mark") or None,
        "default_mark": doc.get("default_mark") if doc.get("default_mark") in ("corner", "background", "none") else "none",
    }
    if doc.get("license"):
        out["license"] = str(doc["license"])[:200]
    return out


class Pack:
    def __init__(self, doc: dict, base: Path, builtin: bool):
        self.doc = doc
        self.base = base
        self.builtin = builtin
        self.id = doc["id"]
        self.rgb = {k: hex_rgb(v) for k, v in doc["colors"].items()}

    def path(self, rel: Optional[str]) -> Optional[str]:
        if not rel:
            return None
        p = Path(rel)
        p = p if p.is_absolute() else self.base / p
        return str(p) if p.exists() else None

    def font_path(self, role: str) -> Optional[str]:
        return self.path((self.doc.get("fonts") or {}).get(role))

    def mark_path(self, size: str, variant: str) -> Optional[str]:
        m = (self.doc.get("mark") or {}).get(size) or {}
        return self.path(m.get(variant))


class PackStore:
    def __init__(self, user_dir: Optional[str], extra_dirs=()):
        self.user_dir = Path(user_dir) if user_dir else None
        self.dirs = [BUILTIN, *[Path(d) for d in extra_dirs]]

    def _load_dir(self, d: Path, builtin: bool) -> dict:
        out = {}
        if not d or not d.is_dir():
            return out
        for f in sorted(d.glob("*.json")):
            try:
                doc = validate(json.loads(f.read_text()))
                out[doc["id"]] = Pack(doc, f.parent, builtin)
            except (ValueError, OSError, json.JSONDecodeError):
                continue
        return out

    def all(self) -> dict:
        packs = {}
        for d in self.dirs:
            packs.update(self._load_dir(d, True))
        packs.update(self._load_dir(self.user_dir, False))
        return packs

    def get(self, pid: str) -> Pack:
        packs = self.all()
        return packs.get(pid) or packs.get("slate") or next(iter(packs.values()))

    def save(self, doc: dict) -> dict:
        doc = validate(doc)
        if (BUILTIN / f"{doc['id']}.json").exists() or any((d / f"{doc['id']}.json").exists() for d in self.dirs):
            raise ValueError(f"'{doc['id']}' is a built-in pack; save under a new id")
        if not self.user_dir:
            raise ValueError("no state directory for user packs")
        self.user_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.user_dir / f".{doc['id']}.json.tmp"
        tmp.write_text(json.dumps(doc, indent=2))
        os.replace(tmp, self.user_dir / f"{doc['id']}.json")
        return doc

    def delete(self, pid: str) -> bool:
        if not self.user_dir:
            return False
        f = self.user_dir / f"{pid}.json"
        if ID_RE.match(pid) and f.exists():
            f.unlink()
            return True
        return False
