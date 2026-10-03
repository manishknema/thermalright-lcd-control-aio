# SPDX-License-Identifier: Apache-2.0
"""thermalright-lcd-control-init: write a config dir for the attached panel.

Everything ships inside the wheel (config templates, udev rule), so an install
needs no source checkout:

  thermalright-lcd-control-init --config-dir /etc/thermalright-lcd \\
      [--state-dir /var/lib/thermalright-lcd] [--device auto|VID:PID] [--panel WxH] [--force]
  thermalright-lcd-control-init --print-udev [--group thermalright]
  thermalright-lcd-control-init --print-unit system|user --venv DIR --config-dir DIR \\
      [--state-dir DIR] [--user-name NAME] [--unit-description TEXT] [--after UNIT ...]
      [--requires-mounts PATH ...] [--working-dir DIR] [--no-rapl-grant]

Config values can be set on the command line, dotted path = YAML value:

  --set service.identity.node_name=desk-1 --set service.api.port=7432 \\
  --set 'service.extras.services={"brain": "http://127.0.0.1:8002/health"}' 

The config dir gets device_info.yaml and config_<w><h>.yaml (kept if present,
unless --force) plus api.token (0600) when service.api.token_file points there
and the file is missing. Paths default to the neutral locations in settings.py.
"""
import argparse
import os
import secrets
import sys
from importlib import resources
from pathlib import Path

import yaml

from thermalright_lcd_control.common.supported_devices import SUPPORTED_DEVICES

DATA = resources.files("thermalright_lcd_control") / "data"


def detect() -> str:
    import usb.core
    for vid, pid, _ in SUPPORTED_DEVICES:
        try:
            if usb.core.find(idVendor=vid, idProduct=pid) is not None:
                return f"{vid:04x}:{pid:04x}"
        except Exception:
            continue
    raise SystemExit("no supported panel attached (lsusb); pass --device VID:PID")


def panel_info(vid_pid: str, panel: str) -> dict:
    vid, pid = (int(x, 16) for x in vid_pid.split(":"))
    for v, p, infos in SUPPORTED_DEVICES:
        if (v, p) == (vid, pid):
            return next((i for i in infos if f"{i['width']}x{i['height']}" == panel), infos[0])
    raise SystemExit(f"{vid_pid} is not a supported image panel")


def template(size: str) -> str:
    return (DATA / "service_config" / f"config_{size}.yaml").read_text()


def apply_sets(doc: dict, sets) -> None:
    for item in sets or []:
        key, _, raw = item.partition("=")
        if not key or not _:
            raise SystemExit(f"--set needs key=value, got {item!r}")
        node = doc
        parts = key.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = yaml.safe_load(raw) if raw != "" else ""


def write_config(cfg_dir: Path, state_dir: str, vid_pid: str, panel: str, force: bool, sets=None) -> Path:
    info = panel_info(vid_pid, panel)
    size = f"{info['width']}{info['height']}"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "device_info.yaml").write_text(yaml.safe_dump(info))
    cfg = cfg_dir / f"config_{size}.yaml"
    if cfg.exists() and not force:
        print(f"kept {cfg}")
    else:
        text = template(size)
        doc = yaml.safe_load(text)
        head = "".join(line for line in text.splitlines(True) if line.startswith("#"))
        svc = doc["service"]
        if state_dir:
            svc["state_dir"] = state_dir
        svc["model"] = f"Thermalright {vid_pid}"
        tok = Path(svc["api"]["token_file"])
        if not tok.is_absolute() or str(tok).startswith("/etc/thermalright-lcd/"):
            svc["api"]["token_file"] = str(cfg_dir / "api.token")
        apply_sets(doc, sets)
        svc = doc["service"]
        cfg.write_text(head + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
        print(f"wrote {cfg}")
        tok = Path(svc["api"]["token_file"])
        if not tok.exists():
            old = os.umask(0o077)
            try:
                tok.write_text(secrets.token_hex(24) + "\n")
            finally:
                os.umask(old)
            print(f"wrote {tok} (0600)")
    return cfg


def unit(kind: str, venv: str, cfg_dir: str, state_dir: str, user_name: str, description: str = "",
         after=(), mounts=(), working_dir: str = "", rapl_grant: bool = True) -> str:
    venv = venv.rstrip("/")
    lines = ["[Unit]", f"Description={description or 'Thermalright LCD service (renderer, API and web UI)'}"]
    lines.append("After=" + " ".join(["systemd-udev-settle.service" if kind == "system" else "default.target", *after]))
    if mounts:
        lines.append("RequiresMountsFor=" + " ".join(mounts))
    lines += ["StartLimitIntervalSec=0", "", "[Service]", "Type=simple"]
    if kind == "system":
        lines += [f"User={user_name}", f"Group={user_name}"]
        if rapl_grant:
            lines += ["# root ('+'): let this group read Intel RAPL energy counters (CPU package watts);",
                      "# energy_uj is root-only by default (CVE-2020-8694). $$ escapes systemd expansion.",
                      "ExecStartPre=+/bin/sh -c 'for f in /sys/class/powercap/intel-rapl:*/energy_uj; do "
                      f"[ -e \"$$f\" ] && chgrp {user_name} \"$$f\" && chmod 0440 \"$$f\"; done; true'"]
    if working_dir:
        lines.append(f"WorkingDirectory={working_dir}")
    lines += [
        "Environment=PYTHONUNBUFFERED=1",
        f"Environment=THERMALRIGHT_STATE_DIR={state_dir}",
        f"ExecStart={venv}/bin/thermalright-lcd-control-service --config {cfg_dir}",
        "Restart=always",
        "RestartSec=5",
        "Nice=10",
    ]
    if kind == "system":
        lines += ["MemoryMax=512M", "NoNewPrivileges=yes", "ProtectSystem=strict", "ProtectHome=yes",
                  "PrivateTmp=yes", "ProtectKernelTunables=yes", "ProtectKernelModules=yes",
                  "ProtectControlGroups=yes", "RestrictRealtime=yes", "LockPersonality=yes",
                  f"ReadWritePaths={state_dir}"]
    lines += ["", "[Install]", "WantedBy=" + ("multi-user.target" if kind == "system" else "default.target"), ""]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Write config for the Thermalright LCD service")
    ap.add_argument("--config-dir")
    ap.add_argument("--state-dir", default="")
    ap.add_argument("--device", default="auto", help="VID:PID or auto")
    ap.add_argument("--panel", default="480x480", help="87ad:70db only: 320x320 or 480x480")
    ap.add_argument("--force", action="store_true", help="overwrite an existing config_<w><h>.yaml")
    ap.add_argument("--print-udev", action="store_true")
    ap.add_argument("--group", default="thermalright")
    ap.add_argument("--print-unit", choices=["system", "user"])
    ap.add_argument("--venv", default="/opt/thermalright-lcd/venv")
    ap.add_argument("--user-name", default="thermalright")
    ap.add_argument("--unit-description", default="")
    ap.add_argument("--after", action="append", default=[])
    ap.add_argument("--requires-mounts", action="append", default=[])
    ap.add_argument("--working-dir", default="")
    ap.add_argument("--no-rapl-grant", action="store_true")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    a = ap.parse_args()

    if a.print_udev:
        sys.stdout.write((DATA / "udev" / "60-thermalright-lcd.rules").read_text().replace("@GROUP@", a.group))
        return 0
    if not a.config_dir:
        ap.error("--config-dir is required")
    if a.print_unit:
        sys.stdout.write(unit(a.print_unit, a.venv, a.config_dir, a.state_dir or "/var/lib/thermalright-lcd", a.user_name,
                              a.unit_description, a.after, a.requires_mounts, a.working_dir, not a.no_rapl_grant))
        return 0
    vid_pid = detect() if a.device == "auto" else a.device.lower()
    write_config(Path(a.config_dir), a.state_dir, vid_pid, a.panel, a.force, a.set)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
