# SPDX-License-Identifier: Apache-2.0
"""The running display: active theme, hot apply, rotation, persisted state.

The device frame loop calls `get_frame_with_duration()`; the HTTP API calls
`apply()` / `save_theme()` / `set_rotation()`. An apply swaps the renderer under
a lock and wakes the frame loop, so the panel shows the change on the next frame
(well under a second) without reopening the USB device.

State directory (default /var/lib/vigyan/thermalright, owned by the service
user; systemd StateDirectory=):
  state.json            active selection, rotation, last apply time
  themes/<id>.json      user themes (schema 2)
  packs/<id>.json       user packs
  media/                uploaded backgrounds (files and collection_* dirs), fonts
/etc holds defaults only; this module never writes there.
"""
import copy
import glob
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Optional

from PIL import Image

from thermalright_lcd_control.showcase.sensors import SamplerThread
from thermalright_lcd_control.themes import metrics as M
from thermalright_lcd_control.themes.engine import Renderer, with_pack
from thermalright_lcd_control.themes.packs import ID_RE, PackStore

DESIGNS_DIR = Path(__file__).parent / "builtin" / "designs"
WIDGET_TYPES = {"text", "number", "arc", "ring", "bar", "sparkline", "coregrid", "clock", "dots", "rect", "image"}
BG_TYPES = {"color", "image", "gif", "video", "collection"}
MAX_WIDGETS = 200


def load_designs() -> dict:
    out = {}
    for f in sorted(DESIGNS_DIR.glob("*.json")):
        try:
            d = json.loads(f.read_text())
            out[d["id"]] = d
        except (OSError, ValueError, KeyError):
            continue
    return dict(sorted(out.items(), key=lambda kv: kv[1].get("order", 99)))


def _atomic_write(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    os.replace(tmp, path)


class Background:
    """image | gif | video | collection backgrounds via the upstream FrameManager."""

    def __init__(self, spec: dict, size, media_root: Path):
        from thermalright_lcd_control.device_controller.display.config import BackgroundType, DisplayConfig
        from thermalright_lcd_control.device_controller.display.frame_manager import FrameManager
        path = Path(spec["path"])
        if not path.is_absolute():
            path = media_root / path
        btype = {"image": BackgroundType.IMAGE, "gif": BackgroundType.GIF, "video": BackgroundType.VIDEO,
                 "collection": BackgroundType.IMAGE_COLLECTION}[spec["type"]]
        cfg = DisplayConfig(background_path=str(path), background_type=btype,
                            output_width=size[0], output_height=size[1], metrics_configs=[])
        self.fm = FrameManager(cfg)
        if spec["type"] == "collection" and spec.get("interval"):
            self.fm.frame_duration = max(0.5, float(spec["interval"]))
        self.animated = spec["type"] in ("gif", "video") or len(self.fm.background_frames) > 1

    def frame(self, size) -> Image.Image:
        return self.fm.get_current_frame()

    @property
    def duration(self) -> float:
        return self.fm.frame_duration


class LegacyRenderer:
    """Upstream v1 YAML themes (background + foreground + text metrics)."""

    def __init__(self, yaml_path: str, width: int, height: int, book):
        from thermalright_lcd_control.device_controller.display.config_loader import ConfigLoader
        from thermalright_lcd_control.device_controller.display.generator import DisplayGenerator
        self.gen = DisplayGenerator(ConfigLoader().load_config(yaml_path, width, height))
        self.book = book
        self.refresh = 1.0
        self.background = None

    def render(self, vals=None) -> Image.Image:
        img, self.refresh = self.gen.get_frame_with_duration()
        return img


def validate_theme(doc: dict) -> dict:
    if not isinstance(doc, dict):
        raise ValueError("theme must be an object")
    if not ID_RE.match(str(doc.get("id", ""))):
        raise ValueError("theme id must be lowercase letters, digits and hyphens (max 48)")
    widgets = doc.get("widgets")
    if not isinstance(widgets, list) or len(widgets) > MAX_WIDGETS:
        raise ValueError(f"widgets must be a list of at most {MAX_WIDGETS}")
    for w in widgets:
        if not isinstance(w, dict) or w.get("type") not in WIDGET_TYPES:
            raise ValueError(f"unknown widget type: {w.get('type') if isinstance(w, dict) else w!r}")
    bg = doc.get("background") or {"type": "color"}
    if bg.get("type") not in BG_TYPES:
        raise ValueError("background.type must be one of " + ", ".join(sorted(BG_TYPES)))
    if bg["type"] != "color" and not bg.get("path"):
        raise ValueError("background.path is required for " + bg["type"])
    if bg.get("path") and (".." in Path(bg["path"]).parts):
        raise ValueError("background.path may not contain '..'")
    dev = doc.get("device") or {}
    if int(dev.get("rotation", 0)) not in (0, 90, 180, 270):
        raise ValueError("device.rotation must be 0, 90, 180 or 270")
    mark = doc.get("mark") or {}
    if mark.get("mode", "none") not in ("corner", "background", "none"):
        raise ValueError("mark.mode must be corner, background or none")
    out = copy.deepcopy(doc)
    out["schema"] = 2
    out["name"] = str(doc.get("name") or doc["id"])[:60]
    out["background"] = bg
    return out


class Runtime:
    def __init__(self, width: int, height: int, device: dict, cfg: Optional[dict], state_dir: str, logger):
        self.w, self.h, self.device, self.log = width, height, device, logger
        self.cfg = cfg or {}
        self.state_dir = Path(state_dir)
        self.media = self.state_dir / "media"
        for sub in ("themes", "packs", "media"):
            try:
                (self.state_dir / sub).mkdir(parents=True, exist_ok=True)
            except OSError as e:
                logger.warning(f"state dir {self.state_dir / sub} not writable: {e}")
        self.packs = PackStore(str(self.state_dir / "packs"), extra_dirs=self.cfg.get("pack_dirs") or [])
        self.designs = load_designs()
        self.book = M.MetricBook(SamplerThread.get(1.0), M.Extras(self.cfg.get("extras")))
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.last_frame: Optional[Image.Image] = None
        self.last_frame_at = 0.0
        self.applied_at = 0.0
        self.first_frame_after_apply = None
        self.state = self._load_state()
        self._rot_idx, self._rot_next = 0, 0.0
        self.renderer = None
        self._activate(self.state["active"], persist=False)

    # ── state ────────────────────────────────────────────────────────────
    def _defaults(self) -> dict:
        d = self.cfg.get("defaults") or {}
        design = d.get("design") if d.get("design") in self.designs else next(iter(self.designs))
        return {"active": {"kind": "design", "design": design, "pack": d.get("pack", "slate"),
                           "mark": d.get("mark") or {}, "device": d.get("device") or {}},
                "rotate": {"enabled": False, "seconds": 15, "items": d.get("rotate") or []}}

    def _load_state(self) -> dict:
        st = self._defaults()
        try:
            saved = json.loads((self.state_dir / "state.json").read_text())
            st.update({k: saved[k] for k in ("active", "rotate") if k in saved})
        except (OSError, ValueError):
            pass
        return st

    def _save_state(self):
        try:
            _atomic_write(self.state_dir / "state.json", {**self.state, "saved_at": time.time()})
        except OSError as e:
            self.log.warning(f"state not persisted: {e}")

    # ── themes ───────────────────────────────────────────────────────────
    def user_themes(self) -> dict:
        out = {}
        for f in sorted((self.state_dir / "themes").glob("*.json")):
            try:
                t = json.loads(f.read_text())
                out[t["id"]] = t
            except (OSError, ValueError, KeyError):
                continue
        return out

    def legacy_themes(self) -> dict:
        out = {}
        for d in self.cfg.get("legacy_theme_dirs") or []:
            for f in sorted(glob.glob(os.path.join(d, f"{self.w}{self.h}", "*.y*ml"))):
                tid = "legacy-" + re.sub(r"[^a-z0-9-]", "-", Path(f).stem.lower())[:40]
                out[tid] = {"id": tid, "name": Path(f).stem.replace("_", " ").replace("-", " ").title(), "path": f}
        return out

    def resolve(self, sel: dict) -> dict:
        """Selection -> concrete theme doc (or legacy marker)."""
        kind = sel.get("kind", "design")
        if kind == "legacy":
            lt = self.legacy_themes().get(sel.get("theme", ""))
            if not lt:
                raise ValueError(f"unknown legacy theme {sel.get('theme')}")
            return {"legacy": lt["path"], "id": lt["id"], "name": lt["name"]}
        if kind == "theme":
            t = self.user_themes().get(sel.get("theme", ""))
            if not t:
                raise ValueError(f"unknown theme {sel.get('theme')}")
            t = copy.deepcopy(t)
            if sel.get("pack"):
                t["pack"] = sel["pack"]
        else:
            ds = self.designs.get(sel.get("design", ""))
            if not ds:
                raise ValueError(f"unknown design {sel.get('design')}")
            t = with_pack(ds, sel.get("pack") or "slate")
        if sel.get("mark"):
            t["mark"] = {**(t.get("mark") or {}), **sel["mark"]}
        if sel.get("device"):
            t["device"] = {**(t.get("device") or {}), **sel["device"]}
        return t

    def build(self, theme: dict, size=None, for_preview=False):
        w, h = size or (self.w, self.h)
        if theme.get("legacy"):
            return LegacyRenderer(theme["legacy"], w, h, self.book)
        bg = theme.get("background") or {}
        background = Background(bg, (w, h), self.media) if bg.get("type", "color") != "color" else None
        r = Renderer(theme, self.packs.get(theme.get("pack", "slate")), w, h, self.book, background)
        if theme.get("foreground", {}) and r.fg is None and (theme.get("foreground") or {}).get("path"):
            fp = Path(theme["foreground"]["path"])
            if not fp.is_absolute():
                theme = copy.deepcopy(theme)
                theme["foreground"]["path"] = str(self.media / fp)
                r = Renderer(theme, r.pack, w, h, self.book, background)
        return r

    def _activate(self, sel: dict, persist=True):
        try:
            theme = self.resolve(sel)
            r = self.build(theme)
        except Exception as e:
            self.log.error(f"theme {sel} failed ({e}); falling back to defaults")
            sel = self._defaults()["active"]
            theme = self.resolve(sel)
            r = self.build(theme)
        with self.lock:
            self.renderer, self.theme, self.state["active"] = r, theme, sel
            self.applied_at = time.time()
            self.first_frame_after_apply = None
        if persist:
            self._save_state()
        self.wake.set()
        self.log.info(f"applied {sel.get('kind')}:{sel.get('design') or sel.get('theme')} pack={theme.get('pack', '-')}")

    def apply(self, sel: dict) -> dict:
        self.resolve(sel)  # raises ValueError before anything changes
        self._activate(sel)
        return self.status()

    def save_theme(self, doc: dict) -> dict:
        doc = validate_theme(doc)
        if doc["id"] in self.designs:
            raise ValueError(f"'{doc['id']}' is a built-in design; save under a new id")
        self.build(doc)  # must render before it is stored
        _atomic_write(self.state_dir / "themes" / f"{doc['id']}.json", doc)
        active = self.state["active"]
        if active.get("kind") == "theme" and active.get("theme") == doc["id"]:
            self._activate(active)  # editing the live theme updates the panel
        return doc

    def delete_theme(self, tid: str) -> bool:
        f = self.state_dir / "themes" / f"{tid}.json"
        if not ID_RE.match(tid) or not f.exists():
            return False
        if self.state["active"].get("theme") == tid:
            raise ValueError("theme is active; apply another one first")
        f.unlink()
        return True

    def set_rotation(self, rot: dict) -> dict:
        items = rot.get("items") or []
        for it in items:
            self.resolve(it)
        with self.lock:
            self.state["rotate"] = {"enabled": bool(rot.get("enabled")) and len(items) > 1,
                                    "seconds": max(5, min(3600, int(rot.get("seconds", 15)))), "items": items}
            self._rot_idx, self._rot_next = 0, 0.0
        self._save_state()
        return self.state["rotate"]

    # ── frames ───────────────────────────────────────────────────────────
    def _rotate_tick(self):
        rot = self.state.get("rotate") or {}
        if not rot.get("enabled") or len(rot.get("items") or []) < 2:
            return
        now = time.monotonic()
        if now < self._rot_next:
            return
        self._rot_next = now + rot["seconds"]
        sel = rot["items"][self._rot_idx % len(rot["items"])]
        self._rot_idx += 1
        try:
            r = self.build(self.resolve(sel))
            with self.lock:
                self.renderer = r
        except Exception as e:
            self.log.warning(f"rotation item {sel} skipped: {e}")

    def get_frame_with_duration(self, apply_rotation: bool = True):
        self._rotate_tick()
        with self.lock:
            r = self.renderer
        img = r.render(self.book.current())
        now = time.time()
        with self.lock:
            self.last_frame, self.last_frame_at = img, now
            self._rendered_for = self.applied_at if r is self.renderer else None
        delay = r.refresh
        bg = getattr(r, "background", None)
        if bg is not None and bg.animated:
            delay = min(delay, max(0.033, bg.duration))
        return img, delay

    def frame_sent(self):
        """Called by the device loop after a frame reached the panel."""
        with self.lock:
            if self.first_frame_after_apply is None and getattr(self, "_rendered_for", None) == self.applied_at:
                self.first_frame_after_apply = time.time()

    def preview(self, theme_or_sel: dict, size=None) -> Image.Image:
        theme = theme_or_sel if "widgets" in theme_or_sel or "legacy" in theme_or_sel else self.resolve(theme_or_sel)
        if "widgets" in theme:
            theme = validate_theme({"id": "preview", **theme, "id": "preview"})
        return self.build(theme, size, for_preview=True).render(self.book.current())

    def status(self) -> dict:
        from thermalright_lcd_control.showcase.stats import STATS
        with self.lock:
            lat = (self.first_frame_after_apply - self.applied_at) if self.first_frame_after_apply else None
            return {
                "device": {**self.device, "width": self.w, "height": self.h,
                           "frames_sent": STATS.frames_sent, "frame_errors": STATS.frame_errors,
                           "last_frame_ms": round(STATS.last_frame_ms, 1), "last_frame_at": self.last_frame_at,
                           "uptime_s": round(time.time() - STATS.started)},
                "active": self.state["active"],
                "theme": {"id": self.theme.get("id"), "name": self.theme.get("name"), "pack": self.theme.get("pack")},
                "rotate": self.state["rotate"],
                "applied_at": self.applied_at,
                "apply_to_first_frame_s": round(lat, 3) if lat is not None else None,
                "capabilities": self.book.capabilities(),
            }
