# SPDX-License-Identifier: Apache-2.0
"""Showcase layout: CPU/GPU temperature, watts and load, per-core bars, RAM, NVMe.

Drawn from scratch each frame (no background asset), so a headless server needs
no theme pack. Sized for 320x240 and scaled for the other panels.

Config (config_<w><h>.yaml):

    showcase:
      enabled: true
      refresh_seconds: 1.0     # frame + sample interval
      title: "{hostname}"      # {hostname} is substituted
      temp_warn: 70            # amber from here
      temp_crit: 85            # red from here
      rotation: 0              # 0/90/180/270
"""
import os
import time
from typing import Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from thermalright_lcd_control.showcase.sensors import Sample, SamplerThread

BG = (8, 12, 18)
PANEL = (20, 27, 38)
TRACK = (34, 44, 60)
TEXT = (232, 238, 245)
MUTED = (128, 144, 165)
CPU_ACCENT = (64, 196, 255)
GPU_ACCENT = (118, 214, 92)
OK = (80, 210, 120)
WARN = (255, 184, 64)
CRIT = (255, 82, 82)

FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
)


class _Fonts:
    def __init__(self, scale: float):
        self.scale = scale
        self.path = next((p for p in FONT_CANDIDATES if os.path.exists(p)), None)
        self.cache = {}

    def __call__(self, size: int):
        size = max(8, int(round(size * self.scale)))
        if size not in self.cache:
            try:
                self.cache[size] = (ImageFont.truetype(self.path, size) if self.path
                                    else ImageFont.load_default(size))
            except Exception:
                self.cache[size] = ImageFont.load_default()
        return self.cache[size]


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def heat(v: Optional[float], warn: float, crit: float):
    if v is None:
        return MUTED
    if v < warn:
        return OK
    if v < crit:
        return _lerp(WARN, CRIT, (v - warn) / max(1e-6, crit - warn))
    return CRIT


def load_color(pct: float):
    return _lerp(OK, WARN, pct / 70) if pct < 70 else _lerp(WARN, CRIT, min(1.0, (pct - 70) / 30))


def _fmt(v, nd=0, unit=""):
    if v is None:
        return "--"
    return f"{v:.{nd}f}{unit}"


class ShowcaseRenderer:
    def __init__(self, width: int, height: int, cfg: dict):
        self.w, self.h = width, height
        self.cfg = cfg or {}
        self.warn = float(self.cfg.get("temp_warn", 70))
        self.crit = float(self.cfg.get("temp_crit", 85))
        self.rotation = int(self.cfg.get("rotation", 0))
        self.refresh = float(self.cfg.get("refresh_seconds", 1.0))
        self.title = str(self.cfg.get("title", "{hostname}"))
        # Layout is authored for 320x240; scale uniformly to the panel's short side.
        self.s = min(width / 320.0, height / 240.0)
        self.font = _Fonts(self.s)

    def S(self, v):
        return int(round(v * self.s))

    def _bar(self, d, box, frac, color, radius=3):
        x0, y0, x1, y1 = box
        d.rounded_rectangle(box, radius=self.S(radius), fill=TRACK)
        frac = max(0.0, min(1.0, frac or 0.0))
        fill_w = int((x1 - x0) * frac)
        if fill_w >= 2 * self.S(radius):  # narrower than the corner radius renders as a dot
            d.rounded_rectangle((x0, y0, x0 + fill_w, y1), radius=self.S(radius), fill=color)

    def _card(self, d, box, title, accent, temp, watts, util, extra: Optional[Tuple[str, float]]):
        S, f = self.S, self.font
        x0, y0, x1, y1 = box
        d.rounded_rectangle(box, radius=S(8), fill=PANEL)
        d.rectangle((x0, y0 + S(6), x0 + S(3), y0 + S(26)), fill=accent)
        d.text((x0 + S(9), y0 + S(5)), title, font=f(13), fill=accent)
        d.text((x1 - S(8), y0 + S(5)), _fmt(util, 0, "%"), font=f(13), fill=TEXT, anchor="ra")
        d.text((x0 + S(9), y0 + S(24)), _fmt(temp, 0), font=f(34), fill=heat(temp, self.warn, self.crit))
        tw = d.textlength(_fmt(temp, 0), font=f(34))
        d.text((x0 + S(11) + tw, y0 + S(28)), "°C", font=f(12), fill=MUTED)
        d.text((x1 - S(8), y0 + S(31)), _fmt(watts, 0), font=f(22), fill=TEXT, anchor="ra")
        d.text((x1 - S(8), y0 + S(55)), "watts", font=f(10), fill=MUTED, anchor="ra")
        self._bar(d, (x0 + S(9), y0 + S(70), x1 - S(9), y0 + S(76)), (util or 0) / 100.0, load_color(util or 0))
        if extra:
            label, frac = extra
            d.text((x0 + S(9), y0 + S(80)), label, font=f(10), fill=MUTED)
            if frac is not None:
                self._bar(d, (x0 + S(9), y0 + S(94), x1 - S(9), y0 + S(98)), frac, accent, radius=2)

    def render(self, s: Sample) -> Image.Image:
        S, f = self.S, self.font
        img = Image.new("RGB", (self.w, self.h), BG)
        d = ImageDraw.Draw(img)

        # header
        d.text((S(8), S(4)), self.title.format(hostname=s.hostname), font=f(12), fill=TEXT)
        d.text((self.w - S(8), S(4)), time.strftime("%H:%M"), font=f(12), fill=MUTED, anchor="ra")

        # CPU / GPU cards
        top, bot = S(22), S(126)
        mid = self.w // 2
        self._card(d, (S(4), top, mid - S(2), bot), "CPU", CPU_ACCENT,
                   s.cpu_temperature, s.cpu_power_watts, s.cpu_utilization,
                   (f"{_fmt(s.cpu_frequency_mhz / 1000 if s.cpu_frequency_mhz else None, 2)} GHz  "
                    f"{len(s.cpu_cores)} threads", None) if s.cpu_cores else None)
        g = s.gpus[0] if s.gpus else None
        if g:
            vram = (g.memory_used / g.memory_total) if g.memory_used is not None and g.memory_total else None
            label = (f"VRAM {g.memory_used / 2**30:.1f}/{g.memory_total / 2**30:.0f} GB"
                     if vram is not None else "VRAM --")
            self._card(d, (mid + S(2), top, self.w - S(4), bot), "GPU", GPU_ACCENT,
                       g.temperature, g.power_watts, g.utilization, (label, vram or 0))
        else:
            box = (mid + S(2), top, self.w - S(4), bot)
            d.rounded_rectangle(box, radius=S(8), fill=PANEL)
            d.text((mid + S(11), top + S(5)), "GPU", font=f(13), fill=MUTED)
            d.text((mid + S(11), top + S(40)), "no NVML GPU", font=f(12), fill=MUTED)

        # per-core load strip
        cores = s.cpu_cores or []
        y0, y1 = S(132), S(188)
        d.rounded_rectangle((S(4), y0, self.w - S(4), y1), radius=S(8), fill=PANEL)
        d.text((S(10), y0 + S(3)), "per-core load", font=f(9), fill=MUTED)
        if cores:
            gx0, gx1, gy0, gy1 = S(10), self.w - S(10), y0 + S(16), y1 - S(5)
            n = len(cores)
            gap = 1 if n > 32 else max(1, S(2))
            bw = max(1.0, (gx1 - gx0 - gap * (n - 1)) / n)
            for i, pct in enumerate(cores):
                bx = gx0 + i * (bw + gap)
                d.rectangle((bx, gy0, bx + bw - 1, gy1), fill=TRACK)
                hgt = int((gy1 - gy0) * min(100.0, pct) / 100.0)
                if hgt > 0:
                    d.rectangle((bx, gy1 - hgt, bx + bw - 1, gy1), fill=load_color(pct))

        # RAM + NVMe footer
        y0 = S(194)
        d.rounded_rectangle((S(4), y0, self.w - S(4), self.h - S(4)), radius=S(8), fill=PANEL)
        used_gb = s.memory_used / 2**30 if s.memory_used is not None else None
        tot_gb = s.memory_total / 2**30 if s.memory_total else None
        d.text((S(10), y0 + S(5)), f"RAM {_fmt(used_gb, 1)}/{_fmt(tot_gb, 0)} GB", font=f(11), fill=TEXT)
        self._bar(d, (S(10), y0 + S(23), mid + S(30), y0 + S(31)),
                  (s.memory_utilization or 0) / 100.0, load_color(s.memory_utilization or 0))
        nv = max(s.nvme.values()) if s.nvme else None
        d.text((self.w - S(10), y0 + S(5)), "NVMe", font=f(10), fill=MUTED, anchor="ra")
        d.text((self.w - S(10), y0 + S(18)), _fmt(nv, 0, "°C"), font=f(17),
               fill=heat(nv, self.warn - 10, self.crit - 10), anchor="ra")

        if self.rotation == 90:
            img = img.transpose(Image.ROTATE_270)
        elif self.rotation == 180:
            img = img.transpose(Image.ROTATE_180)
        elif self.rotation == 270:
            img = img.transpose(Image.ROTATE_90)
        return img


class ShowcaseGenerator:
    """Drop-in for DisplayGenerator: get_frame_with_duration() -> (image, seconds)."""

    def __init__(self, width: int, height: int, cfg: dict):
        self.renderer = ShowcaseRenderer(width, height, cfg)
        self.sampler = SamplerThread.get(self.renderer.refresh)

    def get_frame_with_duration(self, apply_rotation: bool = True):
        return self.renderer.render(self.sampler.latest), self.renderer.refresh

    def cleanup(self):
        pass
