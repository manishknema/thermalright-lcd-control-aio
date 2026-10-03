# SPDX-License-Identifier: Apache-2.0
"""Local HTTP API + web UI for the running display (stdlib only).

Binds 127.0.0.1 by default; a gateway (nginx) in front injects the token, so a
browser never sees it. Every /api/* route except /api/health requires the
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
  GET  /api/nodes                         display-capable nodes (mDNS peers file, nodes.json fallback)
  GET  /, /assets/*                       the web UI (static)
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
        self.nodes_files = cfg.get("nodes_files") or ["/etc/vigyan/cluster-peers.json"]
        if not self.token:
            logger.warning("display API: no token file; API is open to local callers on the loopback")

    @staticmethod
    def _read_token(path):
        try:
            return Path(path).read_text().strip() if path else ""
        except OSError:
            return ""

    # ── capability doc (mDNS consumers read this) ───────────────────────────
    def capability(self) -> dict:
        st = self.rt.status()
        dev = st["device"]
        return {"hw_display": {
            "model": dev.get("model"), "vid_pid": dev.get("vid_pid"),
            "resolution": f"{dev['width']}x{dev['height']}", "driver": "thermalright-lcd-control-aio",
            "connected": dev.get("connected", True), "api_port": self.port, "api_lan": self.lan,
            "api_path": "/display/", "theme": st["theme"], "updated": int(time.time()),
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
            return {"designs": list(rt.designs.values())}
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
        """Nodes advertising hw-display. Peers come from the a17 mDNS announcer's
        peers file; nodes.json (llm-cli inventory) is the fallback list. The full
        capability doc is fetched from each peer's caps_url."""
        import socket
        import urllib.request
        me = socket.gethostname()
        peers = []
        for f in self.nodes_files:
            try:
                data = json.loads(Path(f).read_text())
            except (OSError, ValueError):
                continue
            rows = data if isinstance(data, list) else data.get("nodes", [])
            for r in rows:
                host = r.get("hostname") or r.get("name")
                if host and all(p["hostname"] != host for p in peers):
                    peers.append({"hostname": host, "ip": r.get("ip") or r.get("host") or host,
                                  "caps_url": r.get("caps_url") or f"http://{r.get('ip') or host}:8765/api/capabilities",
                                  "hw_display_txt": r.get("hw_display")})
        out = [{"hostname": me, "self": True, "hw_display": self.capability()["hw_display"], "display_url": "./"}]
        for p in peers:
            if p["hostname"] == me:
                continue
            hw = None
            try:
                with urllib.request.urlopen(p["caps_url"], timeout=1.5) as r:
                    hw = (json.loads(r.read()) or {}).get("hw_display")
            except Exception:
                hw = {"model": p["hw_display_txt"]} if p.get("hw_display_txt") else None
            if not hw:
                continue
            url = f"/display/@{p['hostname']}/" if hw.get("api_port") and hw.get("api_lan") else None
            out.append({"hostname": p["hostname"], "self": False, "hw_display": hw, "display_url": url})
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
                path = re.sub(r"^/display(?=/|$)", "", u.path) or "/"  # tolerate an unstripped gateway prefix
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
