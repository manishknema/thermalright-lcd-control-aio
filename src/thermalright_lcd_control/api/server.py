# SPDX-License-Identifier: Apache-2.0
"""Local HTTP API + web UI for the running display (stdlib only).

Binds 127.0.0.1 by default (settings.api: bind, port, lan, token file, base path,
node URL template, peers files — config or env, see settings.py). A reverse
proxy in front injects the token, so a browser never sees it. Every /api/* route except /api/health requires the
token in `X-Display-Token` or `Authorization: Bearer`. The service validates
every write and stores it in its own state directory; it never writes /etc.

  GET  /api/health                        liveness (no token)
  GET  /api/status                        device, frames, active theme, rotation, capabilities
  GET  /api/capabilities                  the capability doc (also mirrored to <state>/capability.json)
  GET  /api/metrics                       live values + metric catalog
  GET  /api/frame.png[?scale=N]           the last frame sent to the panel (exactly)
  POST /api/preview.png                   {"theme": {...}} | {"selection": {...}}, optional "size": [w,h]
  GET  /api/designs                       built-in designs (7)
  GET  /api/packs                         built-in + user packs
  PUT  /api/packs/<id>  DELETE /api/packs/<id>
  GET  /api/themes                        user themes + legacy (upstream v1) themes
  GET  /api/themes/<id>  PUT /api/themes/<id>  DELETE /api/themes/<id>
  POST /api/apply                         {"kind": "design"|"theme"|"legacy", "design"|"theme": id, "pack", "mark", "device"}
  PUT  /api/rotation                      {"enabled", "seconds", "items": [selection, ...]}
  GET  /api/media                         uploaded backgrounds/fonts
  POST /api/media?name=<file>[&dir=<collection>]   raw body upload
  POST /api/media/collection              -> {"dir": "collection_<hex>"}
  GET  /api/media/file?path=<rel>[&thumb=1]
  DELETE /api/media?path=<rel>
  GET  /api/devices                       supported USB LCDs attached to this node
  GET  /api/nodes                         display-capable nodes (this one + peers files)
  GET  /, /assets/*                       the web UI (static)

Digital (segment) displays use DigitalApi below: status, capabilities, metrics, nodes,
devices as above, plus
  GET  /api/digital/presets               presets with `available` for this node
  GET  /api/digital/modes                 display modes of the panel's layout
  POST /api/apply                         {"preset", "display_mode"?, "ranges"?, "cycle_duration"?}
  GET  /api/frame.png  POST /api/preview.png {"preset", "display_mode"?}   rendered LED view
"""
import hmac
import io
import json
import mimetypes
import os
import re
import secrets
import shutil
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

from PIL import Image

from thermalright_lcd_control.themes import metrics as M
from thermalright_lcd_control.themes.packs import ID_RE

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
MAX_BODY = 64 * 2**20
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
MEDIA_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tiff", ".gif",
             ".mp4", ".avi", ".mkv", ".mov", ".webm", ".flv", ".wmv", ".m4v", ".ttf", ".otf"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tiff"}
VIDEO_EXT = {".mp4", ".avi", ".mkv", ".mov", ".webm", ".flv", ".wmv", ".m4v"}


class ApiError(Exception):
    def __init__(self, code: int, msg: str):
        super().__init__(msg)
        self.code = code


def _png(img: Image.Image, scale: int = 1) -> bytes:
    if scale > 1:
        img = img.resize((img.width * scale, img.height * scale), Image.Resampling.NEAREST)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=False)
    return buf.getvalue()


def media_kind(p: Path) -> str:
    if p.is_dir():
        return "collection"
    ext = p.suffix.lower()
    return ("gif" if ext == ".gif" else "video" if ext in VIDEO_EXT else
            "font" if ext in (".ttf", ".otf") else "image")


class DisplayApi:
    def __init__(self, runtime, cfg: dict, logger):
        self.rt, self.log = runtime, logger
        self.bind = cfg.get("bind", "127.0.0.1")
        self.port = int(cfg.get("port", 7431))
        self.lan = bool(cfg.get("lan", False))
        self.token = self._read_token(cfg.get("token_file"))
        self.nodes_files = cfg.get("nodes_files") or []
        self.base_path = cfg.get("base_path", "")
        self.node_url_template = cfg.get("node_url_template", "")
        if not self.token:
            logger.warning("display API: no token file; API is open to local callers on the loopback")

    @staticmethod
    def _read_token(path):
        try:
            return Path(path).read_text().strip() if path else ""
        except OSError:
            return ""

    # ── capability doc (mDNS consumers read this) ───────────────────────────
    def node_url(self, node_id: str, hostname: str = "", slug: str = "") -> Optional[str]:
        t = self.node_url_template
        return t.format(node_id=node_id, hostname=hostname, slug=slug or node_id) if t else None

    def capability(self) -> dict:
        st = self.rt.status()
        dev, ident = st["device"], st.get("identity") or {}
        return {"hw_display": {
            "node_id": ident.get("node_id"), "node_name": ident.get("node_name"), "slug": ident.get("slug"),
            "device_kind": ident.get("device_kind", "aio"),
            "model": dev.get("model"), "vid_pid": dev.get("vid_pid"),
            "resolution": f"{dev['width']}x{dev['height']}", "driver": "thermalright-lcd-control-aio",
            "connected": dev.get("connected", True), "api_port": self.port, "api_lan": self.lan,
            "url": self.node_url(ident.get("node_id", ""), ident.get("node_name", ""), ident.get("slug", "")),
            "theme": st["theme"], "updated": int(time.time()),
        }}

    def write_capability(self):
        try:
            p = self.rt.state_dir / "capability.json"
            tmp = p.with_name(".capability.json.tmp")
            tmp.write_text(json.dumps(self.capability(), indent=2))
            os.replace(tmp, p)
            p.chmod(0o644)
        except OSError as e:
            self.log.warning(f"capability.json not written: {e}")

    # ── routes ───────────────────────────────────────────────────────────
    def handle(self, method: str, path: str, query: dict, body: bytes):
        rt = self.rt
        parts = [p for p in path.split("/") if p][1:]  # drop "api"
        head = parts[0] if parts else ""
        J = lambda: self._json(body)

        if head == "status" and method == "GET":
            return rt.status()
        if head == "capabilities" and method == "GET":
            return self.capability()
        if head == "metrics" and method == "GET":
            vals = rt.book.current()
            return {"values": vals, "catalog": {k: {"label": v[0], "unit": v[1], "heat": v[2], "requires": v[3]}
                                                for k, v in M.CATALOG.items()},
                    "capabilities": rt.book.capabilities()}
        if head == "frame.png" and method == "GET":
            img = rt.last_frame
            if img is None:
                raise ApiError(503, "no frame rendered yet")
            return ("image/png", _png(img, max(1, min(4, int(query.get("scale", ["1"])[0])))))
        if head == "preview.png" and method == "POST":
            req = J()
            size = tuple(req.get("size") or (rt.w, rt.h))
            if not (16 <= size[0] <= 1024 and 16 <= size[1] <= 1024):
                raise ApiError(400, "size out of range")
            src = req.get("theme") or req.get("selection")
            if not isinstance(src, dict):
                raise ApiError(400, "theme or selection required")
            return ("image/png", _png(rt.preview(src, size), max(1, min(4, int(req.get("scale", 1))))))
        if head == "designs" and method == "GET":
            caps = rt.book.capabilities()
            return {"designs": [{**d, "available": rt.available(d, caps)} for d in rt.designs.values()],
                    "capabilities": caps}
        if head == "packs":
            if method == "GET" and len(parts) == 1:
                return {"packs": [{**p.doc, "builtin": p.builtin} for p in rt.packs.all().values()]}
            if len(parts) == 2 and method == "PUT":
                doc = {**J(), "id": parts[1]}
                # The web UI uploads fonts to the media dir and refers to them as
                # "media/<rel>"; pack font paths resolve against the pack dir, so
                # store them as absolute paths under the media root.
                fonts = doc.get("fonts") if isinstance(doc.get("fonts"), dict) else {}
                for role, val in list(fonts.items()):
                    if isinstance(val, str) and val.startswith("media/"):
                        fonts[role] = str(self._safe(val[len("media/"):]))
                saved = rt.packs.save(doc)
                if rt.theme.get("pack") == saved["id"]:
                    rt.apply(rt.state["active"])
                return saved
            if len(parts) == 2 and method == "DELETE":
                if rt.theme.get("pack") == parts[1]:
                    raise ApiError(409, "pack is active; apply another one first")
                return {"deleted": rt.packs.delete(parts[1])}
        if head == "themes":
            if method == "GET" and len(parts) == 1:
                return {"themes": list(rt.user_themes().values()),
                        "legacy": list(rt.legacy_themes().values())}
            if len(parts) == 2:
                tid = parts[1]
                if method == "GET":
                    t = rt.user_themes().get(tid) or rt.designs.get(tid)
                    if not t:
                        raise ApiError(404, "no such theme")
                    return t
                if method == "PUT":
                    return rt.save_theme({**J(), "id": tid})
                if method == "DELETE":
                    return {"deleted": rt.delete_theme(tid)}
        if head == "apply" and method == "POST":
            out = rt.apply(J())
            self.write_capability()
            return out
        if head == "rotation" and method == "PUT":
            return rt.set_rotation(J())
        if head == "media":
            return self._media(method, parts[1:], query, body)
        if head == "devices" and method == "GET":
            return {"devices": self._devices()}
        if head == "nodes" and method == "GET":
            return {"nodes": self._nodes()}
        raise ApiError(404, f"no route {method} {path}")

    @staticmethod
    def _json(body: bytes) -> dict:
        try:
            v = json.loads(body or b"{}")
        except ValueError:
            raise ApiError(400, "body is not JSON")
        if not isinstance(v, dict):
            raise ApiError(400, "body must be a JSON object")
        return v

    def _safe(self, rel: str) -> Path:
        root = self.rt.media.resolve()
        p = (root / rel).resolve()
        if root not in p.parents and p != root:
            raise ApiError(400, "path escapes the media directory")
        return p

    def _media(self, method, rest, query, body):
        root = self.rt.media
        if method == "GET" and not rest:
            items = []
            for p in sorted(root.iterdir(), key=lambda x: -x.stat().st_mtime) if root.exists() else []:
                if p.name.startswith("."):
                    continue
                n = len([c for c in p.iterdir() if c.suffix.lower() in IMAGE_EXT]) if p.is_dir() else None
                items.append({"path": p.name, "kind": media_kind(p), "count": n,
                              "bytes": None if p.is_dir() else p.stat().st_size})
            return {"media": items}
        if method == "POST" and rest == ["collection"]:
            d = f"collection_{secrets.token_hex(4)}"
            (root / d).mkdir(parents=True)
            return {"dir": d}
        if method == "POST" and not rest:
            name = (query.get("name") or [""])[0]
            if not NAME_RE.match(name) or Path(name).suffix.lower() not in MEDIA_EXT:
                raise ApiError(400, "name must be a plain file name with a supported extension: "
                               + " ".join(sorted(MEDIA_EXT)))
            sub = (query.get("dir") or [""])[0]
            if sub and not re.match(r"^collection_[0-9a-f]{8}$", sub):
                raise ApiError(400, "dir must be a collection created by POST /api/media/collection")
            if sub and Path(name).suffix.lower() not in IMAGE_EXT:
                raise ApiError(400, "collections hold images only")
            if not body:
                raise ApiError(400, "empty upload")
            target = self._safe(f"{sub}/{name}" if sub else name)
            stem, ext, n = target.stem, target.suffix, 1
            while target.exists():
                target = target.with_name(f"{stem}_{n}{ext}")
                n += 1
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name("." + target.name + ".part")
            tmp.write_bytes(body)
            if target.suffix.lower() in IMAGE_EXT | {".gif"}:
                try:
                    with Image.open(tmp) as im:
                        im.verify()
                except Exception:
                    tmp.unlink(missing_ok=True)
                    raise ApiError(400, "not a readable image")
            os.replace(tmp, target)
            return {"path": str(target.relative_to(root)), "kind": media_kind(target)}
        if method == "GET" and rest == ["file"]:
            p = self._safe((query.get("path") or [""])[0])
            if not p.exists():
                raise ApiError(404, "no such media")
            if query.get("thumb"):
                return ("image/png", _png(self._thumb(p)))
            if p.is_dir():
                raise ApiError(400, "collection: use thumb=1")
            return (mimetypes.guess_type(p.name)[0] or "application/octet-stream", p.read_bytes())
        if method == "DELETE" and not rest:
            p = self._safe((query.get("path") or [""])[0])
            if p == root.resolve() or not p.exists():
                raise ApiError(404, "no such media")
            shutil.rmtree(p) if p.is_dir() else p.unlink()
            return {"deleted": True}
        raise ApiError(404, "no such media route")

    @staticmethod
    def _thumb(p: Path) -> Image.Image:
        size = (160, 120)
        try:
            if p.is_dir():
                first = next((c for c in sorted(p.iterdir()) if c.suffix.lower() in IMAGE_EXT), None)
                img = Image.open(first) if first else Image.new("RGB", size, (40, 40, 40))
            elif p.suffix.lower() in VIDEO_EXT:
                import cv2
                cap = cv2.VideoCapture(str(p))
                n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
                cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, n // 10))
                ok, fr = cap.read()
                cap.release()
                img = Image.fromarray(cv2.cvtColor(fr, cv2.COLOR_BGR2RGB)) if ok else Image.new("RGB", size, (40, 40, 40))
            elif p.suffix.lower() in (".ttf", ".otf"):
                from PIL import ImageDraw, ImageFont
                img = Image.new("RGB", size, (24, 28, 38))
                ImageDraw.Draw(img).text((8, 40), "Aa 123", font=ImageFont.truetype(str(p), 36), fill=(236, 238, 243))
            else:
                img = Image.open(p)
            img = img.convert("RGB")
        except Exception:
            img = Image.new("RGB", size, (40, 40, 40))
        img.thumbnail(size)
        return img

    def _nodes(self) -> list:
        """This display plus display-capable peers.

        Peers files (service.api.nodes_files) are JSON lists of
        {hostname, ip, node_id?, caps_url?, hw_display?}; caps_url must return a JSON
        object with a `hw_display` object (this service's /api/capabilities shape).
        A peer gets a URL (service.api.node_url_template) only when its display API
        listens on the LAN; otherwise it is listed for information."""
        import urllib.request
        me = self.capability()["hw_display"]
        out = [{"hostname": me.get("node_name"), "node_id": me.get("node_id"), "self": True,
                "hw_display": me, "display_url": "./"}]
        seen = {me.get("node_id"), me.get("node_name")}
        for f in self.nodes_files:
            try:
                data = json.loads(Path(f).read_text())
            except (OSError, ValueError):
                continue
            for r in data if isinstance(data, list) else data.get("nodes", []):
                host = r.get("hostname") or r.get("name")
                nid = r.get("node_id") or host
                if not host or host in seen or nid in seen:
                    continue
                seen.update((host, nid))
                hw = None
                if r.get("caps_url"):
                    try:
                        with urllib.request.urlopen(r["caps_url"], timeout=1.5) as resp:
                            hw = (json.loads(resp.read()) or {}).get("hw_display")
                    except Exception:
                        hw = None
                if not hw and r.get("hw_display"):
                    hw = r["hw_display"] if isinstance(r["hw_display"], dict) else {"model": str(r["hw_display"])}
                if not hw:
                    continue
                nid = hw.get("node_id") or nid
                url = self.node_url(nid, host, hw.get("slug") or r.get("display_slug") or "") \
                    if hw.get("api_port") and hw.get("api_lan") else None
                out.append({"hostname": hw.get("node_name") or host, "node_id": nid, "self": False,
                            "hw_display": hw, "display_url": url})
        return out

    def _devices(self) -> list:
        import usb.core
        from thermalright_lcd_control.common.supported_devices import SUPPORTED_DEVICES
        out = []
        cur = self.rt.device.get("vid_pid")
        for vid, pid, infos in SUPPORTED_DEVICES:
            try:
                present = usb.core.find(idVendor=vid, idProduct=pid) is not None
            except Exception:
                present = None
            vp = f"{vid:04x}:{pid:04x}"
            out.append({"vid_pid": vp, "panels": [f"{i['width']}x{i['height']}" for i in infos],
                        "attached": present, "active": vp == cur})
        return out

    # ── server ───────────────────────────────────────────────────────────
    def authorised(self, headers) -> bool:
        if not self.token:
            return True
        got = headers.get("X-Display-Token") or ""
        auth = headers.get("Authorization") or ""
        if auth.startswith("Bearer "):
            got = got or auth[7:]
        return hmac.compare_digest(got.strip(), self.token)

    def serve(self):
        api = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "thermalright-display/2"

            def log_message(self, fmt, *args):
                pass

            def _send(self, code, ctype, data: bytes):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(data)

            def _route(self, method):
                u = urlparse(self.path)
                path = u.path
                if api.base_path and (path == api.base_path or path.startswith(api.base_path + "/")):
                    path = path[len(api.base_path):] or "/"  # proxy forwarded the prefix unstripped
                try:
                    if path == "/api/health":
                        return self._send(200, "application/json", b'{"ok": true}')
                    if path.startswith("/api/"):
                        if not api.authorised(self.headers):
                            raise ApiError(401, "missing or wrong display token")
                        n = int(self.headers.get("Content-Length") or 0)
                        if n > MAX_BODY:
                            raise ApiError(413, "body too large")
                        body = self.rfile.read(n) if n else b""
                        out = api.handle(method, path, parse_qs(u.query), body)
                        if isinstance(out, tuple):
                            return self._send(200, out[0], out[1])
                        return self._send(200, "application/json", json.dumps(out, default=str).encode())
                    if method != "GET":
                        raise ApiError(405, "method not allowed")
                    return self._static(path)
                except ApiError as e:
                    self._send(e.code, "application/json", json.dumps({"error": str(e)}).encode())
                except ValueError as e:
                    self._send(400, "application/json", json.dumps({"error": str(e)}).encode())
                except Exception as e:  # never kill the server thread
                    api.log.error(f"display API {method} {path}: {e}", exc_info=True)
                    self._send(500, "application/json", json.dumps({"error": "internal error"}).encode())

            def _static(self, path):
                rel = path.lstrip("/") or "index.html"
                p = (WEB_DIR / rel).resolve()
                if WEB_DIR.resolve() not in p.parents or not p.is_file():
                    p = WEB_DIR / "index.html"  # SPA fallback
                if not p.is_file():
                    raise ApiError(404, "web UI not bundled")
                self._send(200, mimetypes.guess_type(p.name)[0] or "application/octet-stream", p.read_bytes())

            def do_GET(self):
                self._route("GET")

            def do_HEAD(self):
                self._route("GET")

            def do_POST(self):
                self._route("POST")

            def do_PUT(self):
                self._route("PUT")

            def do_DELETE(self):
                self._route("DELETE")

        bind = self.bind if self.lan else "127.0.0.1"
        httpd = ThreadingHTTPServer((bind, self.port), Handler)
        httpd.daemon_threads = True
        threading.Thread(target=httpd.serve_forever, name="display-api", daemon=True).start()
        self.write_capability()
        self.log.info(f"display API on http://{bind}:{self.port}/ (token {'set' if self.token else 'NOT set'})")
        return httpd


class DigitalApi(DisplayApi):
    """API for a digital display (runtime = digital.runtime.DigitalRuntime)."""

    def capability(self) -> dict:
        doc = super().capability()
        doc["hw_display"].update(device_kind="digital", driver="digital_thermal_right_lcd", resolution="segment")
        return doc

    def handle(self, method: str, path: str, query: dict, body: bytes):
        rt = self.rt
        parts = [p for p in path.split("/") if p][1:]
        head = parts[0] if parts else ""
        scale = lambda q: max(1, min(4, int((q.get("scale") or ["1"])[0])))
        if head in ("status", "capabilities", "metrics", "nodes", "devices") and method == "GET":
            return super().handle(method, path, query, body)
        if head == "frame.png" and method == "GET":
            return ("image/png", _png(rt.preview(None, scale=scale(query))))
        if head == "preview.png" and method == "POST":
            req = self._json(body)
            return ("image/png", _png(rt.preview(req.get("selection") or req, scale=max(1, min(4, int(req.get("scale", 1)))))))
        if head == "apply" and method == "POST":
            out = rt.apply(self._json(body))
            self.write_capability()
            return out
        if method == "GET" and len(parts) == 1 and head in ("packs", "designs", "themes", "media"):
            return {head: [], **({"legacy": []} if head == "themes" else {})}  # image-display lists: none here
        if head == "digital" and method == "GET" and parts[1:] == ["presets"]:
            return {"presets": [rt.preset_view(p) for p in rt.presets().values()], "layout": rt.layout()}
        if head == "digital" and method == "GET" and parts[1:] == ["modes"]:
            return {"modes": rt.modes(), "layout": rt.layout()}
        raise ApiError(404, f"{method} {path} is not available for digital displays")
