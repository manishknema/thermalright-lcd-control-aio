# SPDX-License-Identifier: Apache-2.0
"""Digital display themes: presets -> controller config, and a rendered LED preview.

The digital display (0416:8001) is driven by its own controller process, which
re-reads its JSON config every frame. Applying a theme therefore means writing
that file (atomically); the panel changes on the controller's next frame.

Preset schema (builtin/presets/<id>.json, or <state>/digital/presets/<id>.json):

    {
      "schema": 1, "id": "heat", "name": "Heat", "description": "...",
      "requires": [],                     # e.g. ["gpu"]
      "ranges": {"cpu_min_temp": 40, "cpu_max_temp": 90},   # any *_min_*/*_max_* key
      "cycle_duration": 5,                # seconds per phase for cycling modes / pulses
      "layouts": {
        "small": {"display_mode": "cpu_temp",
                  "colors": {"default": "ffffff", "groups": {"digits": "22c55e-ef4444-cpu_temp"}},
                  "time_colors": {...optional, same shape...}},
        "big":   {...}
      }
    }

A colour is "rrggbb", "random", "aaaaaa-bbbbbb" (pulse) or "aaaaaa-bbbbbb-<key>"
(key: cpu_temp, gpu_temp, cpu_usage, gpu_usage, seconds, minutes, hours). Groups
are the layout's LED groups (layout.py). On a node without a GPU, presets that
require one are unavailable and gpu-keyed gradients collapse to their start colour.
"""
import copy
import json
import math
import random
import re
import time
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from thermalright_lcd_control.digital import layout as L

BUILTIN = Path(__file__).parent / "builtin" / "presets"
HEX = re.compile(r"^[0-9a-fA-F]{6}$")
COLOR = re.compile(r"^(random|[0-9a-fA-F]{6}(-[0-9a-fA-F]{6}(-(cpu_temp|gpu_temp|cpu_usage|gpu_usage|seconds|minutes|hours))?)?)$")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")
RANGE_KEYS = {"cpu_min_temp", "cpu_max_temp", "gpu_min_temp", "gpu_max_temp",
              "cpu_min_usage", "cpu_max_usage", "gpu_min_usage", "gpu_max_usage"}


def validate_preset(doc: dict) -> dict:
    if not isinstance(doc, dict) or not ID_RE.match(str(doc.get("id", ""))):
        raise ValueError("preset id must be lowercase letters, digits and hyphens")
    lays = doc.get("layouts") or {}
    if not lays or any(k not in L.LAYOUTS for k in lays):
        raise ValueError("preset layouts must be among: " + ", ".join(L.LAYOUTS))
    for name, lay in lays.items():
        if lay.get("display_mode") not in L.LAYOUTS[name]["modes"]:
            raise ValueError(f"{name}: display_mode must be one of {L.LAYOUTS[name]['modes']}")
        for key in ("colors", "time_colors"):
            spec = lay.get(key)
            if spec is None:
                continue
            for c in [spec.get("default", "ffffff"), *(spec.get("groups") or {}).values()]:
                if not COLOR.match(str(c)):
                    raise ValueError(f"{name}.{key}: bad colour {c!r}")
            bad = set(spec.get("groups") or {}) - set(L.LAYOUTS[name]["groups"])
            if bad:
                raise ValueError(f"{name}.{key}: unknown LED groups {sorted(bad)}")
    for k in doc.get("ranges") or {}:
        if k not in RANGE_KEYS:
            raise ValueError(f"unknown range {k}")
    return doc


def load_presets(user_dir: Optional[Path]) -> dict:
    out = {}
    for d in (BUILTIN, user_dir):
        if not d or not Path(d).is_dir():
            continue
        for f in sorted(Path(d).glob("*.json")):
            try:
                p = validate_preset(json.loads(f.read_text()))
                out[p["id"]] = p
            except (OSError, ValueError, json.JSONDecodeError):
                continue
    return dict(sorted(out.items(), key=lambda kv: kv[1].get("order", 99)))


def _expand(spec: dict, groups: dict, gpu: bool) -> list:
    colors = [spec.get("default", "ffffff")] * L.NUMBER_OF_LEDS
    for g, c in (spec.get("groups") or {}).items():
        for i in groups[g]:
            colors[i] = c
    if not gpu:  # a gpu-keyed gradient on a GPU-less node only produces clamp warnings
        colors = [c.split("-")[0] if c.endswith(("-gpu_temp", "-gpu_usage")) else c for c in colors]
    return colors


def build_config(base: dict, preset: dict, layout_mode: str, gpu: bool, mode: Optional[str] = None) -> dict:
    """The controller config after applying `preset` (optionally another display_mode)."""
    lay = preset["layouts"].get(layout_mode)
    if lay is None:
        raise ValueError(f"preset {preset['id']} has no {layout_mode} layout")
    display_mode = mode or lay["display_mode"]
    if display_mode not in L.LAYOUTS[layout_mode]["modes"]:
        raise ValueError(f"{display_mode} is not a {layout_mode}-layout mode")
    if not gpu and display_mode in L.GPU_MODES:
        raise ValueError(f"{display_mode} needs a GPU reading; this node has none")
    cfg = copy.deepcopy(base)
    groups = L.LAYOUTS[layout_mode]["groups"]
    cfg["layout_mode"] = layout_mode
    cfg["display_mode"] = display_mode
    cfg.setdefault("metrics", {})["colors"] = _expand(lay["colors"], groups, gpu)
    cfg.setdefault("time", {})["colors"] = _expand(lay.get("time_colors") or lay["colors"], groups, gpu)
    cfg.update(preset.get("ranges") or {})
    if preset.get("cycle_duration"):
        cfg["cycle_duration"] = float(preset["cycle_duration"])
    return cfg


# ── preview ─────────────────────────────────────────────────────────────────
OFF = (26, 31, 40)
BG = (8, 10, 14)


def _hex(c):
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def resolve_color(c: str, cfg: dict, vals: dict, now: float, seed: int) -> tuple:
    if c == "random":
        return _hex("%06x" % random.Random(seed).randint(0, 0xFFFFFF))
    parts = c.split("-")
    if len(parts) == 1:
        return _hex(parts[0])
    a, b = _hex(parts[0]), _hex(parts[1])
    if len(parts) == 3:
        key = parts[2]
        t = time.localtime(now)
        if key == "seconds":
            f = t.tm_sec / 59
        elif key == "minutes":
            f = t.tm_min / 59
        elif key == "hours":
            f = t.tm_hour / 23
        else:
            dev, kind = key.split("_")
            v = vals.get(f"{dev}.{'temp' if kind == 'temp' else 'load' if dev == 'cpu' else 'util'}")
            lo = float(cfg.get(f"{dev}_min_{kind}", 30 if kind == "temp" else 0))
            hi = float(cfg.get(f"{dev}_max_{kind}", 90 if kind == "temp" else 100))
            f = 0.0 if v is None or hi == lo else (v - lo) / (hi - lo)
    else:
        cd = max(0.1, float(cfg.get("cycle_duration", 5)))
        f = 1 - abs((now % (2 * cd)) - cd) / cd
    f = max(0.0, min(1.0, f))
    return tuple(int(a[i] * (1 - f) + b[i] * f) for i in range(3))


def lit_leds(cfg: dict, vals: dict, now: float):
    """(set of lit LED indexes, palette key per LED: 'metrics'|'time') like the controller."""
    lay = cfg.get("layout_mode", "big")
    G = L.LAYOUTS[lay if lay in L.LAYOUTS else "big"]["groups"]
    mode = cfg.get("display_mode", "metrics")
    cd = max(0.1, float(cfg.get("cycle_duration", 5)))
    phase = (now % (2 * cd)) / cd  # 0..2, like the controller's cpt counter
    lit, pal = set(), {}
    unit = {d: cfg.get(f"{d}_temperature_unit", "celsius") for d in ("cpu", "gpu")}

    def num(v):
        return 0 if v is None else int(round(v))

    def setg(group, mask, key="metrics"):
        for i, on in zip(G[group], mask):
            pal[i] = key
            if on:
                lit.add(i)

    if lay == "small":
        def temp(dev):
            setg("celsius" if unit[dev] == "celsius" else "fahrenheit", [1]); setg(f"{dev}_led", [1, 1])
            setg("digits", L.digits_mask(num(vals.get(f"{dev}.temp"))))

        def usage(dev):
            setg("percent", [1]); setg(f"{dev}_led", [1, 1])
            setg("digits", L.digits_mask(num(vals.get("cpu.load" if dev == "cpu" else "gpu.util"))))
        if mode == "debug_ui":
            lit.update(range(31))
        elif mode == "alternate_metrics":
            (temp("cpu") if phase < .5 else temp("gpu") if phase < 1 else usage("cpu") if phase < 1.5 else usage("gpu"))
        elif mode in ("cpu_temp", "gpu_temp"):
            temp(mode[:3])
        elif mode in ("cpu_usage", "gpu_usage"):
            usage(mode[:3])
        return lit, pal

    H = [1, 0, 1, 1, 1, 0, 1]
    t = time.localtime(now)

    def metrics(dev):
        setg(f"{dev}_led", [1, 1]); setg(f"{dev}_{unit[dev]}", [1])
        setg(f"{dev}_temp", L.digits_mask(num(vals.get(f"{dev}.temp"))))
        u = num(vals.get("cpu.load" if dev == "cpu" else "gpu.util"))
        setg(f"{dev}_usage", [int(u >= 100)] * 2 + L.digits_mask(u % 100, 2)); setg(f"{dev}_percent_led", [1])

    def clock(dev, seconds=False):
        setg(f"{dev}_temp", L.digits_mask(t.tm_hour, 2) + H, "time")
        setg(f"{dev}_usage", [0, 0] + L.digits_mask(t.tm_min, 2), "time")
        if seconds:
            setg("gpu_usage", [0, 0] + L.digits_mask(t.tm_sec, 2), "time")
    if mode == "debug_ui":
        lit.update(range(L.NUMBER_OF_LEDS))
    elif mode == "metrics":
        metrics("cpu"); metrics("gpu")
    elif mode == "time":
        clock("cpu", seconds=True)
    elif mode == "time_cpu":
        clock("gpu"); metrics("cpu")
    elif mode == "time_gpu":
        clock("cpu"); metrics("gpu")
    elif mode == "alternate_time":
        (clock("cpu"), metrics("gpu")) if phase < 1 else (clock("gpu"), metrics("cpu"))
    elif mode == "alternate_time_with_seconds":
        clock("cpu", seconds=True) if phase < 1 else (metrics("cpu"), metrics("gpu"))
    return lit, pal


def _segment_boxes(x, y, w, h, t):
    """7 segment rectangles (tl, top, tr, mid, bl, bottom, br) for a digit at x,y."""
    hh = h / 2
    return [
        (x, y + t, x + t, y + hh - t / 2), (x + t, y, x + w - t, y + t), (x + w - t, y + t, x + w, y + hh - t / 2),
        (x + t, y + hh - t / 2, x + w - t, y + hh + t / 2), (x, y + hh + t / 2, x + t, y + h - t),
        (x + t, y + h - t, x + w - t, y + h), (x + w - t, y + hh + t / 2, x + w, y + h - t),
    ]


def render(cfg: dict, vals: dict, now: Optional[float] = None, scale: float = 1.0) -> Image.Image:
    now = time.time() if now is None else now
    lit, pal = lit_leds(cfg, vals, now)
    m_colors = (cfg.get("metrics") or {}).get("colors") or ["ffffff"] * L.NUMBER_OF_LEDS
    t_colors = (cfg.get("time") or {}).get("colors") or m_colors

    def col(i):
        if i not in lit:
            return OFF
        c = (t_colors if pal.get(i) == "time" else m_colors)[i] if i < len(m_colors) else "ffffff"
        return resolve_color(str(c), cfg, vals, now, i)
    S = lambda v: int(round(v * scale))
    lay = cfg.get("layout_mode", "big")
    G = L.LAYOUTS[lay if lay in L.LAYOUTS else "big"]["groups"]
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", S(13))
    except OSError:
        font = ImageFont.load_default(S(13))

    def digit_row(d, leds, x, y, n, w=34, h=62, t=7, gap=12):
        for k in range(n):
            for seg, box in enumerate(_segment_boxes(x + k * (w + gap), y, w, h, t)):
                idx = leds[k * 7 + seg]
                d.rounded_rectangle([S(v) for v in box], S(2), fill=col(idx))

    def dot(d, idx, x, y, label):
        d.ellipse([S(x), S(y), S(x + 10), S(y + 10)], fill=col(idx))
        d.text((S(x + 15), S(y - 2)), label, font=font, fill=col(idx) if idx in lit else (70, 78, 92))

    if lay == "small":
        im = Image.new("RGB", (S(320), S(120)), BG)
        d = ImageDraw.Draw(im)
        dot(d, G["cpu_led"][0], 14, 26, "CPU"); dot(d, G["gpu_led"][0], 14, 50, "GPU")
        digit_row(d, G["digits"], 90, 22, 3)
        dot(d, G["celsius"][0], 250, 22, "°C"); dot(d, G["fahrenheit"][0], 250, 46, "°F"); dot(d, G["percent"][0], 250, 70, "%")
        return im
    im = Image.new("RGB", (S(360), S(190)), BG)
    d = ImageDraw.Draw(im)
    for row, dev in enumerate(("cpu", "gpu")):
        y = 14 + row * 90
        dot(d, G[f"{dev}_led"][0], 10, y + 4, dev.upper())
        digit_row(d, G[f"{dev}_temp"], 70, y, 3, w=26, h=50, t=6, gap=8)
        dot(d, G[f"{dev}_celsius"][0], 180, y + 4, "°C"); dot(d, G[f"{dev}_fahrenheit"][0], 180, y + 24, "°F")
        u = G[f"{dev}_usage"]
        for k, idx in enumerate(u[:2]):  # the leading "1" of 100 %
            d.rounded_rectangle([S(228), S(y + 2 + k * 24), S(234), S(y + 24 + k * 24)], S(2), fill=col(idx))
        digit_row(d, u[2:], 242, y, 2, w=26, h=50, t=6, gap=8)
        dot(d, G[f"{dev}_percent_led"][0], 316, y + 4, "%")
    return im
