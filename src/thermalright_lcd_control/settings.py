# SPDX-License-Identifier: Apache-2.0
"""Deployment settings: config file values, overridden by environment variables.

Nothing deployment-specific is hardcoded in the package. Every path, name and
address below has a neutral default and can be set by the `service:` /
`telemetry:` blocks of config_<w><h>.yaml or by an environment variable (the
environment wins). A deployment's installer is what fills in its own values.

  setting             env var                          config key                         default
  state dir           THERMALRIGHT_STATE_DIR,          service.state_dir                  /var/lib/thermalright-lcd
                      STATE_DIRECTORY (systemd)
  API bind / port     THERMALRIGHT_API_BIND / _PORT    service.api.bind / .port           127.0.0.1 / 7431
  API token file      THERMALRIGHT_API_TOKEN_FILE      service.api.token_file             /etc/thermalright-lcd/api.token
  API LAN listen      THERMALRIGHT_API_LAN             service.api.lan                    false
  URL prefix to strip THERMALRIGHT_API_BASE_PATH       service.api.base_path              ""
  node page URL       THERMALRIGHT_NODE_URL_TEMPLATE   service.api.node_url_template      "" (e.g. "/display/{slug}/")
  display slug        THERMALRIGHT_DISPLAY_SLUG        service.api.slug                   <slug_prefix>-aio | <slug_prefix>-cpu-cooler
  slug prefix         THERMALRIGHT_DISPLAY_SLUG_PREFIX service.api.slug_prefix            display
  peers files         -                                service.api.nodes_files            []
  node name           THERMALRIGHT_NODE_NAME           service.identity.node_name         hostname
  node id             THERMALRIGHT_NODE_ID             service.identity.node_id           hostname
  node role           THERMALRIGHT_NODE_ROLE           service.identity.role              ""
  service unit name   THERMALRIGHT_SERVICE_NAME        service.identity.service           thermalright-lcd-control
  OTLP endpoint       OTEL_EXPORTER_OTLP_ENDPOINT      telemetry.otlp_endpoint            http://127.0.0.1:4318
  extra resource      -                                telemetry.resource_attributes      {}
  attributes
"""
import os
import socket


def _env(name, default=None):
    v = os.environ.get(name)
    return v if v not in (None, "") else default


def _bool(v) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def state_dir(cfg: dict) -> str:
    systemd = (_env("STATE_DIRECTORY") or "").split(":")[0]
    return _env("THERMALRIGHT_STATE_DIR") or systemd or cfg.get("state_dir") or "/var/lib/thermalright-lcd"


def api(cfg: dict) -> dict:
    a = dict(cfg.get("api") or {})
    return {
        "enabled": _bool(a.get("enabled", True)),
        "bind": _env("THERMALRIGHT_API_BIND", a.get("bind", "127.0.0.1")),
        "port": int(_env("THERMALRIGHT_API_PORT", a.get("port", 7431))),
        "lan": _bool(_env("THERMALRIGHT_API_LAN", a.get("lan", False))),
        "token_file": _env("THERMALRIGHT_API_TOKEN_FILE", a.get("token_file", "/etc/thermalright-lcd/api.token")),
        "base_path": (_env("THERMALRIGHT_API_BASE_PATH", a.get("base_path", "")) or "").rstrip("/"),
        "node_url_template": _env("THERMALRIGHT_NODE_URL_TEMPLATE", a.get("node_url_template", "")) or "",
        "nodes_files": list(a.get("nodes_files") or []),
        "slug": _env("THERMALRIGHT_DISPLAY_SLUG", a.get("slug", "")) or "",
        "slug_prefix": _env("THERMALRIGHT_DISPLAY_SLUG_PREFIX", a.get("slug_prefix", "display")) or "display",
    }


def display_slug(cfg: dict, device_kind: str) -> str:
    """Readable, URL-safe name for this display (e.g. "display-aio"); unique per proxy."""
    import re
    a = api(cfg)
    slug = a["slug"] or f"{a['slug_prefix']}-{'cpu-cooler' if device_kind == 'digital' else 'aio'}"
    slug = re.sub(r"[^a-z0-9-]+", "-", slug.lower()).strip("-")
    return slug or "display"


def identity(cfg: dict, device: dict, width: int, height: int) -> dict:
    """Who and what this display is; returned by /api/status and used as OTLP resource."""
    ident = dict(cfg.get("identity") or {})
    host = socket.gethostname()
    vid_pid = device.get("vid_pid", "")
    return {
        "node_name": _env("THERMALRIGHT_NODE_NAME", ident.get("node_name") or host),
        "node_id": _env("THERMALRIGHT_NODE_ID", ident.get("node_id") or host),
        "role": _env("THERMALRIGHT_NODE_ROLE", ident.get("role", "")),
        "device_kind": ident.get("device_kind", "aio"),
        "model": device.get("model") or f"Thermalright {vid_pid}",
        "vid_pid": vid_pid,
        "resolution": f"{width}x{height}",
        "service": _env("THERMALRIGHT_SERVICE_NAME", ident.get("service", "thermalright-lcd-control")),
        "slug": display_slug(cfg, ident.get("device_kind", "aio")),
    }


def otlp_endpoint(cfg: dict) -> str:
    return _env("OTEL_EXPORTER_OTLP_ENDPOINT", (cfg or {}).get("otlp_endpoint", "http://127.0.0.1:4318"))
