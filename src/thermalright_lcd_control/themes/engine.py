# SPDX-License-Identifier: Apache-2.0
"""Theme v2 renderer: widgets bound to metric ids, drawn with a pack's palette.

One renderer serves the LCD and the web preview, so preview == panel.

Theme document (schema 2). Coordinates are in the theme's `base` canvas
(default 320x240) and scale uniformly to the panel; a design may carry
hand-tuned `layouts["480x480"]` widget lists instead.

    {
      "schema": 2, "id": "my-theme", "name": "My theme",
      "design": "core-gauge",           # design it was derived from (informational)
      "pack": "slate",
      "base": [320, 240],
      "mark": {"mode": "none", "opacity": 0.10, "variant": "auto", "corner": "br"},
      "background": {"type": "color"}   # color | image | gif | video | collection
                                        #   + "path", "interval" (collection seconds)
      "foreground": null | {"path": "...", "alpha": 1.0, "x": 0, "y": 0},
      "device": {"rotation": 0, "brightness": 100, "refresh": 1.0},
      "widgets": [ {...}, ... ],
      "layouts": {"480x480": [ {...} ]} # optional per-resolution widget lists
    }

Widget keys common to all types: "type", "requires" ("gpu" | "rapl" | "llm",
prefix "!" to negate), "hidden".
Colours: a palette role (ink, panel, line, text, muted, accent1..3, ok, warn,
hot), "#rrggbb", or "heat" (needs "metric" and optional "heat": [lo, hi]).
Fonts: display | bold | body | mono.

  text       x y text size font color anchor upper metric heat
             text may embed {metric.id} / {metric.id:.0f} / {metric.id@peak:.0f}
  number     x y metric format size font color unit unit_size unit_font unit_color unit_dy gap
  arc        cx cy r width metric min max start sweep color track heat
  ring       arc with start -90, sweep 360
  bar        x y w h metric min max color track radius heat
  sparkline  x y w h metric seconds color fill dot
  coregrid   x y w h cols gap values label_size
  clock      x y format size font color anchor upper
  dots       x y services size     (service health: ok / hot dot + name)
  rect       x y w h radius color
  image      x y w h path opacity

v1 (upstream YAML) themes are not handled here; see runtime.LegacyTheme.
"""
import copy
import math
import os
import re
import time
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from thermalright_lcd_control.themes import metrics as M
from thermalright_lcd_control.themes.packs import Pack

DASH = "—"
DEJAVU = ("/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/TTF", "/usr/share/fonts/dejavu")
DEFAULT_FONTS = {"display": "DejaVuSansCondensed-Bold.ttf", "bold": "DejaVuSans-Bold.ttf",
                 "body": "DejaVuSans.ttf", "mono": "DejaVuSansMono-Bold.ttf"}
TOKEN_RE = re.compile(r"\{([a-z]+\.[a-z0-9_]+(?:@[a-z]+)?)(?::([^{}]*))?\}")
MARK_SMALL_PX = 32
MARK_BIG_FRAC = 220 / 240


def _default_font(role: str) -> Optional[str]:
    name = DEFAULT_FONTS[role]
    for d in DEJAVU:
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return None


class Fonts:
    def __init__(self, pack: Pack, scale: float):
        self.pack, self.scale, self.cache = pack, scale, {}

    def __call__(self, role: str, size: float):
        role = role if role in DEFAULT_FONTS else "bold"
        px = max(6, int(round(size * self.scale)))
        key = (role, px)
        if key not in self.cache:
            path = self.pack.font_path(role) or _default_font(role)
            try:
                self.cache[key] = ImageFont.truetype(path, px) if path else ImageFont.load_default(px)
            except Exception:
                self.cache[key] = ImageFont.load_default(px)
        return self.cache[key]


def heat_rgb(pack: Pack, v, lo, hi):
    if v is None:
        return pack.rgb["muted"]
    t = max(0.0, min(1.0, (v - lo) / ((hi - lo) or 1)))
    a, b, u = (pack.rgb["ok"], pack.rgb["warn"], t / 0.5) if t < 0.5 else (pack.rgb["warn"], pack.rgb["hot"], (t - 0.5) / 0.5)
    return tuple(int(a[i] + (b[i] - a[i]) * u) for i in range(3))


def fmt_value(v, spec: Optional[str]) -> str:
    if v is None:
        return DASH
    if isinstance(v, bool):
        return "up" if v else "down"
    if isinstance(v, (int, float)):
        try:
            return format(v, spec) if spec else (f"{v:.0f}" if isinstance(v, float) else str(v))
        except ValueError:
            return str(v)
    return str(v)


def expand(text: str, vals: dict, book) -> str:
    return TOKEN_RE.sub(lambda m: fmt_value(M.value(vals, book, m.group(1)), m.group(2)), text)


class Renderer:
    """Renders one theme on one panel size. Cheap to build; rebuilt on apply."""

    def __init__(self, theme: dict, pack: Pack, width: int, height: int, book, background=None,
                 caps: Optional[dict] = None):
        self.theme, self.pack, self.w, self.h = theme, pack, width, height
        self.book = book
        self.caps = caps if caps is not None else (book.capabilities() if book else {})
        bw, bh = theme.get("base") or (320, 240)
        layouts = theme.get("layouts") or {}
        tuned = layouts.get(f"{width}x{height}")
        if tuned:
            bw, bh, self.widgets = width, height, tuned
        else:
            self.widgets = theme.get("widgets") or []
        self.s = min(width / bw, height / bh)
        self.ox, self.oy = (width - bw * self.s) / 2, (height - bh * self.s) / 2
        self.base = (bw, bh)
        self.font = Fonts(pack, self.s)
        self.background = background  # runtime.Background (image/gif/video/collection) or None
        dev = theme.get("device") or {}
        self.rotation = int(dev.get("rotation", 0)) % 360
        self.brightness = max(5, min(100, int(dev.get("brightness", 100))))
        self.refresh = max(0.1, min(10.0, float(dev.get("refresh", 1.0))))
        self.mark = self._mark()
        self.fg = self._foreground()

    # ── geometry ──────────────────────────────────────────────────────────
    def X(self, x):
        return self.ox + x * self.s

    def Y(self, y):
        return self.oy + y * self.s

    def L(self, v):
        return v * self.s

    def color(self, spec, wd=None, v=None):
        spec = spec or "text"
        if spec == "heat":
            lo, hi = (wd or {}).get("heat") or (M.CATALOG.get((wd or {}).get("metric", ""), (0, 0, (0, 100)))[2] or (0, 100))
            return heat_rgb(self.pack, v, lo, hi)
        if isinstance(spec, str) and spec.startswith("#") and len(spec) == 7:
            return tuple(int(spec[i:i + 2], 16) for i in (1, 3, 5))
        return self.pack.rgb.get(spec, self.pack.rgb["text"])

    def visible(self, wd) -> bool:
        if wd.get("hidden"):
            return False
        req = wd.get("requires")
        if not req:
            return True
        neg = req.startswith("!")
        have = bool(self.caps.get(req.lstrip("!")))
        return have != neg

    # ── mark (one per frame) ──────────────────────────────────────────────
    def _mark_cfg(self):
        m = dict(self.theme.get("mark") or {})
        m.setdefault("mode", self.pack.doc.get("default_mark", "none"))
        return m

    def _mark(self):
        m = self._mark_cfg()
        mode = m.get("mode", "none")
        if mode not in ("corner", "background"):
            return None
        variant = m.get("variant", "auto")
        if variant == "auto":
            variant = "ivory" if self.pack.doc.get("ground") == "light" else "deep"
        path = self.pack.mark_path("small" if mode == "corner" else "big", variant)
        if not path:
            return None
        img = Image.open(path).convert("RGBA")
        if mode == "corner":
            px = max(8, min(MARK_SMALL_PX, int(round(MARK_SMALL_PX * self.s))))
        else:
            px = int(round(min(self.w, self.h) * MARK_BIG_FRAC))
        img = img.resize((px, int(round(img.height * px / img.width))), Image.Resampling.LANCZOS)
        if mode == "background":
            op = max(0.05, min(0.20, float(m.get("opacity", 0.10))))
            img.putalpha(img.getchannel("A").point(lambda a: int(a * op)))
        return mode, m.get("corner") or self.theme.get("mark_corner") or "br", img

    def mark_inset(self, corner: str) -> float:
        """Base-canvas px a widget with avoid_mark shifts by when the mark sits in `corner`."""
        if not self.mark or self.mark[0] != "corner" or self.mark[1] != corner:
            return 0.0
        return (self.mark[2].width + 8) / self.s

    def _foreground(self):
        fg = self.theme.get("foreground")
        if not fg or not fg.get("path") or not os.path.exists(fg["path"]):
            return None
        try:
            img = Image.open(fg["path"]).convert("RGBA")
        except OSError:
            return None
        alpha = max(0.0, min(1.0, float(fg.get("alpha", 1.0))))
        if alpha < 1.0:
            img.putalpha(img.getchannel("A").point(lambda a: int(a * alpha)))
        return img, (int(fg.get("x", 0)), int(fg.get("y", 0)))

    # ── frame ─────────────────────────────────────────────────────────────
    def render(self, vals: Optional[dict] = None) -> Image.Image:
        vals = vals if vals is not None else (self.book.current() if self.book else {})
        ink = self.pack.rgb["ink"]
        if self.background is not None:
            im = self.background.frame((self.w, self.h)).convert("RGB")
        else:
            im = Image.new("RGB", (self.w, self.h), ink)
        if self.mark and self.mark[0] == "background":
            mk = self.mark[2]
            im.paste(mk, ((self.w - mk.width) // 2, (self.h - mk.height) // 2), mk)
        overlay = Image.new("RGBA", (self.w, self.h), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        for wd in self.widgets:
            if not self.visible(wd):
                continue
            fn = getattr(self, "w_" + str(wd.get("type", "")), None)
            if fn is None:
                continue
            try:
                fn(d, wd, vals, overlay)
            except Exception:
                continue  # one bad widget never blanks the panel
        if overlay.getbbox():
            im = Image.alpha_composite(im.convert("RGBA"), overlay).convert("RGB")
        if self.fg:
            im = im.convert("RGBA")
            im.paste(self.fg[0], self.fg[1], self.fg[0])
            im = im.convert("RGB")
        if self.mark and self.mark[0] == "corner":
            _, at, mk = self.mark
            x = int(self.X(8)) if at in ("bl", "tl") else int(self.X(self.base[0] - 8)) - mk.width
            y = int(self.Y(4)) if at in ("tr", "tl") else int(self.Y(self.base[1] - 6)) - mk.height
            im.paste(mk, (x, y), mk)
        if self.brightness < 100:
            f = self.brightness / 100.0
            im = im.point(lambda p: int(p * f))
        if self.rotation == 90:
            im = im.transpose(Image.ROTATE_270)
        elif self.rotation == 180:
            im = im.transpose(Image.ROTATE_180)
        elif self.rotation == 270:
            im = im.transpose(Image.ROTATE_90)
        return im

    # ── widgets ───────────────────────────────────────────────────────────
    def _num(self, vals, wd):
        v = M.value(vals, self.book, wd.get("metric", "")) if wd.get("metric") else None
        return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    def _frac(self, v, wd):
        lo, hi = float(wd.get("min", 0)), float(wd.get("max", 100))
        return 0.0 if v is None else max(0.0, min(1.0, (v - lo) / ((hi - lo) or 1)))

    def _x(self, wd, key="x"):
        x = float(wd.get(key, 0))
        if wd.get("avoid_mark"):
            anchor = wd.get("anchor", "la")
            if anchor[0] == "r":
                x -= self.mark_inset("tr") if float(wd.get("y", 0)) < self.base[1] / 2 else self.mark_inset("br")
            else:
                x += self.mark_inset("tl") if float(wd.get("y", 0)) < self.base[1] / 2 else self.mark_inset("bl")
        return self.X(x)

    def w_text(self, d, wd, vals, _):
        s = expand(str(wd.get("text", "")), vals, self.book)
        if wd.get("upper"):
            s = s.upper()
        v = self._num(vals, wd)
        d.text((self._x(wd), self.Y(wd.get("y", 0))), s, font=self.font(wd.get("font", "bold"), wd.get("size", 12)),
               fill=self.color(wd.get("color", "text"), wd, v), anchor=wd.get("anchor", "la"))

    def w_number(self, d, wd, vals, _):
        v = M.value(vals, self.book, wd.get("metric", ""))
        s = fmt_value(v, wd.get("format", ".0f"))
        num = v if isinstance(v, (int, float)) and not isinstance(v, bool) else None
        f = self.font(wd.get("font", "display"), wd.get("size", 40))
        x, y = self._x(wd), self.Y(wd.get("y", 0))
        col = self.color(wd.get("color", "text"), wd, num)
        d.text((x, y), s, font=f, fill=col, anchor="la")
        unit = wd.get("unit")
        if unit and num is not None:
            ux = x + d.textlength(s, font=f) + self.L(wd.get("gap", 4))
            d.text((ux, y + self.L(wd.get("unit_dy", 0))), unit,
                   font=self.font(wd.get("unit_font", "bold"), wd.get("unit_size", 16)),
                   fill=self.color(wd.get("unit_color") or wd.get("color", "text"), wd, num), anchor="la")

    def w_arc(self, d, wd, vals, _, start=135.0, sweep=270.0):
        v = self._num(vals, wd)
        cx, cy, r = self.X(wd.get("cx", 0)), self.Y(wd.get("cy", 0)), self.L(wd.get("r", 40))
        width = max(1, int(round(self.L(wd.get("width", 12)))))
        start, sweep = float(wd.get("start", start)), float(wd.get("sweep", sweep))
        box = [cx - r, cy - r, cx + r, cy + r]
        d.arc(box, start, start + sweep, fill=self.color(wd.get("track", "line")), width=width)
        frac = self._frac(v, wd)
        if frac > 0:
            d.arc(box, start, start + sweep * frac, fill=self.color(wd.get("color", "accent1"), wd, v), width=width)

    def w_ring(self, d, wd, vals, ov):
        self.w_arc(d, wd, vals, ov, start=-90.0, sweep=360.0)

    def _bar(self, d, x, y, w, h, frac, col, track, radius):
        r = max(0, int(round(self.L(radius))))
        d.rounded_rectangle([x, y, x + w, y + h], r, fill=track)
        if frac > 0:
            d.rounded_rectangle([x, y, x + max(h, w * frac), y + h], r, fill=col)

    def w_bar(self, d, wd, vals, _):
        v = self._num(vals, wd)
        self._bar(d, self._x(wd), self.Y(wd.get("y", 0)), self.L(wd.get("w", 100)), self.L(wd.get("h", 6)),
                  self._frac(v, wd), self.color(wd.get("color", "accent1"), wd, v),
                  self.color(wd.get("track", "line")), wd.get("radius", 3))

    def w_rect(self, d, wd, vals, _):
        x, y = self._x(wd), self.Y(wd.get("y", 0))
        d.rounded_rectangle([x, y, x + self.L(wd.get("w", 10)), y + self.L(wd.get("h", 10))],
                            int(self.L(wd.get("radius", 6))), fill=self.color(wd.get("color", "panel")))

    def w_sparkline(self, d, wd, vals, overlay):
        series = self.book.series(wd.get("metric", ""), float(wd.get("seconds", 60))) if self.book else []
        if len(series) < 2:
            return
        x, y, w, h = self._x(wd), self.Y(wd.get("y", 0)), self.L(wd.get("w", 100)), self.L(wd.get("h", 40))
        lo, hi = min(series), max(series)
        if "min" in wd:
            lo = min(lo, float(wd["min"]))
        n = len(series)
        pts = [(x + i * w / (n - 1), y + h - (v - lo) / ((hi - lo) or 1) * h) for i, v in enumerate(series)]
        col = self.color(wd.get("color", "accent1"), wd, series[-1])
        if wd.get("fill", True):
            ImageDraw.Draw(overlay).polygon(pts + [(x + w, y + h), (x, y + h)], fill=col + (60,))
        d.line(pts, fill=col, width=max(1, int(round(self.L(2)))))
        if wd.get("dot", True):
            ex, ey = pts[-1]
            r = self.L(3)
            d.ellipse([ex - r, ey - r, ex + r, ey + r], fill=col)

    @staticmethod
    def grid_cols(n: int, w: float, h: float, gap: float, label_h: float) -> int:
        best, best_cols = -1.0, 1
        for cols in range(1, n + 1):
            rows = math.ceil(n / cols)
            cw = (w - (cols - 1) * gap) / cols
            ch = (h - rows * label_h - (rows - 1) * gap) / rows
            size = min(cw * 1.25, ch)  # cells a little taller than wide read best
            if size > best:
                best, best_cols = size, cols
        return best_cols

    def w_coregrid(self, d, wd, vals, _):
        cores = vals.get("cpu.cores") or []
        if not cores:
            return
        n = len(cores)
        x0, y0, w, h = float(wd.get("x", 0)), float(wd.get("y", 0)), float(wd.get("w", 288)), float(wd.get("h", 160))
        gap = float(wd.get("gap", 4))
        show = wd.get("values", True)
        lab = float(wd.get("label_size", 9)) + 5 if show else 0
        cols = int(wd["cols"]) if str(wd.get("cols", "auto")).isdigit() else self.grid_cols(n, w, h, gap, lab)
        rows = math.ceil(n / cols)
        cw = (w - (cols - 1) * gap) / cols
        ch = min((h - rows * lab - (rows - 1) * gap) / rows, cw * 1.6)
        gx = x0 + (w - (cols * cw + (cols - 1) * gap)) / 2
        for i, v in enumerate(cores):
            cx, cy = gx + (i % cols) * (cw + gap), y0 + (i // cols) * (ch + lab + gap)
            X, Y, CW, CH = self.X(cx), self.Y(cy), self.L(cw), self.L(ch)
            d.rounded_rectangle([X, Y, X + CW, Y + CH], int(self.L(4)), fill=self.pack.rgb["panel"])
            hh = (CH - self.L(4)) * min(100.0, v) / 100.0
            if hh >= 1:
                d.rounded_rectangle([X + self.L(2), Y + CH - self.L(2) - hh, X + CW - self.L(2), Y + CH - self.L(2)],
                                    int(self.L(3)), fill=heat_rgb(self.pack, v, 0, 100))
            if show:
                d.text((X + CW / 2, Y + CH + self.L(lab / 2 + 1)), f"{v:.0f}",
                       font=self.font("body", wd.get("label_size", 9)), fill=self.pack.rgb["muted"], anchor="mm")

    def w_clock(self, d, wd, vals, _):
        s = time.strftime(wd.get("format", "%H:%M"))
        if wd.get("upper"):
            s = s.upper()
        d.text((self._x(wd), self.Y(wd.get("y", 0))), s, font=self.font(wd.get("font", "mono"), wd.get("size", 13)),
               fill=self.color(wd.get("color", "text")), anchor=wd.get("anchor", "la"))

    def w_dots(self, d, wd, vals, _):
        x, y = self._x(wd), self.Y(wd.get("y", 0))
        size = wd.get("size", 10)
        f = self.font("bold", size)
        r = self.L(size * 0.4)
        for name in wd.get("services") or []:
            ok = vals.get(f"svc.{name}")
            col = self.pack.rgb["muted"] if ok is None else self.pack.rgb["ok"] if ok else self.pack.rgb["hot"]
            cy = y + self.L(size * 0.6)
            d.ellipse([x, cy - r, x + 2 * r, cy + r], fill=col)
            x += 2 * r + self.L(4)
            d.text((x, y), name, font=f, fill=col, anchor="la")
            x += d.textlength(name, font=f) + self.L(10)

    def w_image(self, d, wd, vals, overlay):
        p = wd.get("path")
        if not p or not os.path.exists(p):
            return
        img = Image.open(p).convert("RGBA")
        w, h = int(self.L(wd.get("w", img.width))), int(self.L(wd.get("h", img.height)))
        img = img.resize((max(1, w), max(1, h)), Image.Resampling.LANCZOS)
        op = float(wd.get("opacity", 1.0))
        if op < 1.0:
            img.putalpha(img.getchannel("A").point(lambda a: int(a * op)))
        overlay.alpha_composite(img, (int(self._x(wd)), int(self.Y(wd.get("y", 0)))))


def with_pack(design: dict, pack_id: str, **overrides) -> dict:
    """A theme = a design (widgets) + a pack + overrides (mark, device, background)."""
    t = copy.deepcopy(design)
    t["schema"] = 2
    t["pack"] = pack_id
    t.update(overrides)
    return t
