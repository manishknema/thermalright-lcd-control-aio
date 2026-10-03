# SPDX-License-Identifier: Apache-2.0
"""Digital display service: themes the segment display by writing its controller config.

The controller (a separate process) owns the USB device and re-reads its config every
frame. This runtime owns that config file (in its state dir), applies presets to it
atomically, keeps the chosen preset in <state>/digital/state.json and renders an LED
preview of what the panel shows now. Same API/token/web UI shell as the image
displays (api/server.py), with digital routes.
"""
import json
import os
import shutil
import time
from pathlib import Path
from typing import Optional

from thermalright_lcd_control.digital import engine as E
from thermalright_lcd_control.digital import layout as L
from thermalright_lcd_control.showcase.sensors import SamplerThread
from thermalright_lcd_control.themes import metrics as M


class DigitalRuntime:
    kind = "digital"

    def __init__(self, cfg: dict, device: dict, state_dir: str, logger, identity: Optional[dict] = None):
        self.log, self.device, self.identity = logger, device, identity or {}
        self.cfg = cfg or {}
        dcfg = self.cfg.get("digital") or {}
        self.state_dir = Path(state_dir)
        self.dir = self.state_dir / "digital"
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "presets").mkdir(exist_ok=True)
        self.controller_config = Path(dcfg.get("controller_config") or self.dir / "config.json")
        self.defaults = Path(dcfg["defaults"]) if dcfg.get("defaults") else None
        self.book = M.MetricBook(SamplerThread.get(1.0), M.Extras(None))
        self.book.node_name = self.identity.get("node_name")
        self.w, self.h = 320, 120
        self._seed_config()
        self.applied_at = 0.0
        self.last_frame = None
        self.last_frame_at = 0.0

    # ── config file ─────────────────────────────────────────────────────
    def _seed_config(self):
        if self.controller_config.exists():
            return
        if self.defaults and self.defaults.exists():
            self.controller_config.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.defaults, self.controller_config)
            os.chmod(self.controller_config, 0o644)
            self.log.info(f"digital: seeded {self.controller_config} from {self.defaults}")

    def read_config(self) -> dict:
        try:
            return json.loads(self.controller_config.read_text())
        except (OSError, ValueError):
            return {"layout_mode": "small", "display_mode": "cpu_temp"}

    def write_config(self, cfg: dict):
        tmp = self.controller_config.with_name("." + self.controller_config.name + ".tmp")
        tmp.write_text(json.dumps(cfg, indent=2))
        os.chmod(tmp, 0o644)
        os.replace(tmp, self.controller_config)  # the controller never sees a half-written file

    def _state(self) -> dict:
        try:
            return json.loads((self.dir / "state.json").read_text())
        except (OSError, ValueError):
            return {}

    def _save_state(self, st: dict):
        tmp = self.dir / ".state.json.tmp"
        tmp.write_text(json.dumps(st, indent=2))
        os.replace(tmp, self.dir / "state.json")

    # ── presets ─────────────────────────────────────────────────────────
    def presets(self) -> dict:
        return E.load_presets(self.dir / "presets")

    def caps(self) -> dict:
        return self.book.capabilities()

    def layout(self) -> str:
        lay = self.read_config().get("layout_mode", "small")
        return lay if lay in L.LAYOUTS else "small"

    def preset_view(self, p: dict) -> dict:
        lay, gpu = self.layout(), bool(self.caps().get("gpu"))
        reason = None
        if lay not in p["layouts"]:
            reason = f"no {lay} layout"
        elif any(not self.caps().get(r) for r in p.get("requires") or []):
            reason = "needs " + ", ".join(p.get("requires"))
        elif not gpu and p["layouts"][lay]["display_mode"] in L.GPU_MODES:
            reason = "needs a GPU"
        return {**p, "available": reason is None, "unavailable_reason": reason}

    def modes(self) -> list:
        lay, gpu = self.layout(), bool(self.caps().get("gpu"))
        return [{"id": m, "label": L.MODE_LABELS.get(m, m), "available": gpu or m not in L.GPU_MODES}
                for m in L.LAYOUTS[lay]["modes"]]

    def apply(self, sel: dict) -> dict:
        p = self.presets().get(sel.get("preset", ""))
        if not p:
            raise ValueError(f"unknown preset {sel.get('preset')}")
        view = self.preset_view(p)
        if not view["available"] and not sel.get("display_mode"):
            raise ValueError(f"preset {p['id']} is not available here: {view['unavailable_reason']}")
        cfg = E.build_config(self.read_config(), p, self.layout(), bool(self.caps().get("gpu")), sel.get("display_mode"))
        for k, v in (sel.get("ranges") or {}).items():
            if k not in E.RANGE_KEYS:
                raise ValueError(f"unknown range {k}")
            cfg[k] = float(v)
        if sel.get("cycle_duration"):
            cfg["cycle_duration"] = max(1.0, min(60.0, float(sel["cycle_duration"])))
        self.write_config(cfg)
        self.applied_at = time.time()
        self._save_state({"preset": p["id"], "display_mode": cfg["display_mode"], "applied_at": self.applied_at})
        self.log.info(f"digital: applied preset {p['id']} ({cfg['display_mode']}, {cfg['layout_mode']})")
        return self.status()

    def preview(self, sel: Optional[dict] = None, scale: float = 1.0):
        cfg = self.read_config()
        if sel and sel.get("preset"):
            p = self.presets().get(sel["preset"])
            if not p:
                raise ValueError(f"unknown preset {sel['preset']}")
            gpu = bool(self.caps().get("gpu"))
            mode = sel.get("display_mode")
            if mode is None and not gpu and p["layouts"].get(self.layout(), {}).get("display_mode") in L.GPU_MODES:
                mode = "cpu_temp" if self.layout() == "small" else "time_cpu"  # show what it would look like
            cfg = E.build_config(cfg, p, self.layout(), gpu or bool(mode), mode)
        img = E.render(cfg, self.book.current(), scale=scale)
        if not sel:
            self.last_frame, self.last_frame_at = img, time.time()
        return img

    def frame_sent(self):
        pass

    def status(self) -> dict:
        cfg = self.read_config()
        st = self._state()
        try:
            mtime = self.controller_config.stat().st_mtime
        except OSError:
            mtime = None
        return {
            "identity": self.identity,
            "device": {**self.device, "width": self.w, "height": self.h, "frames_sent": 0, "frame_errors": 0,
                       "last_frame_ms": 0, "last_frame_at": self.last_frame_at, "uptime_s": 0},
            "digital": {"controller_config": str(self.controller_config), "config_mtime": mtime,
                        "layout_mode": cfg.get("layout_mode"), "display_mode": cfg.get("display_mode"),
                        "preset": st.get("preset"), "cycle_duration": cfg.get("cycle_duration"),
                        "ranges": {k: cfg[k] for k in sorted(E.RANGE_KEYS) if k in cfg}},
            "active": {"kind": "digital", "preset": st.get("preset")},
            "theme": {"id": st.get("preset"), "name": (self.presets().get(st.get("preset") or "") or {}).get("name"),
                      "pack": cfg.get("display_mode")},
            "rotate": {"enabled": False, "seconds": 0, "items": []},
            "applied_at": st.get("applied_at", 0),
            "apply_to_first_frame_s": None,
            "capabilities": self.caps(),
        }
