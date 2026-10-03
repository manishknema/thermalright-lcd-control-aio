# SPDX-License-Identifier: Apache-2.0
"""thermalright-lcd-control-dev: the full service without a USB panel.

Runs the real runtime (renderer, rotation, hot apply), the API and the web UI
against a fake device that "sends" each frame to memory, so designs, packs, the
editor and API changes can be developed and tested on any machine.

  thermalright-lcd-control-dev --size 320x240 --port 7499 --token devtoken \\
      [--state-dir /tmp/tlcd-dev] [--frames-dir /tmp/tlcd-frames] [--config FILE]

  curl -H 'X-Display-Token: devtoken' http://127.0.0.1:7499/api/status
  open http://127.0.0.1:7499/   (use the key button to enter the dev token)

--kind digital runs the segment-display service instead: presets are applied to
--controller-config (default <state>/digital/config.json, seeded from
--digital-defaults); point a controller at that file to watch it live.

--frames-dir writes the latest frame as frame.png about once a second.
--config takes a service config (the `service:` block of config_<w><h>.yaml);
without it the packaged template for --size is used.
"""
import argparse
import logging
import os
import tempfile
import threading
import time
from importlib import resources
from pathlib import Path

import yaml


def main():
    ap = argparse.ArgumentParser(description="Run the display service against a fake panel")
    ap.add_argument("--size", default="320x240", help="320x240, 320x320 or 480x480")
    ap.add_argument("--port", type=int, default=7499)
    ap.add_argument("--token", default="devtoken", help="API token ('' disables the check)")
    ap.add_argument("--state-dir", default="")
    ap.add_argument("--frames-dir", default="")
    ap.add_argument("--config", default="")
    ap.add_argument("--seconds", type=float, default=0, help="stop after N seconds (0 = run until Ctrl-C)")
    ap.add_argument("--kind", choices=["aio", "digital"], default="aio")
    ap.add_argument("--controller-config", default="")
    ap.add_argument("--digital-defaults", default="")
    a = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log = logging.getLogger("thermalright.dev")
    w, h = (int(x) for x in a.size.lower().split("x"))
    src = Path(a.config) if a.config else \
        resources.files("thermalright_lcd_control") / "data" / "service_config" / f"config_{w}{h}.yaml"
    cfg = (yaml.safe_load(src.read_text()) or {}).get("service") or {}

    from thermalright_lcd_control import settings
    from thermalright_lcd_control.api.server import DisplayApi
    from thermalright_lcd_control.showcase.stats import STATS
    from thermalright_lcd_control.themes.runtime import Runtime

    state = a.state_dir or tempfile.mkdtemp(prefix="tlcd-dev-")
    tok_file = Path(state) / "dev.token"
    Path(state).mkdir(parents=True, exist_ok=True)
    tok_file.write_text(a.token)
    api_cfg = settings.api(cfg)
    api_cfg.update(port=a.port, bind="127.0.0.1", lan=False, token_file=str(tok_file) if a.token else "")
    if a.kind == "digital":
        from thermalright_lcd_control.api.server import DigitalApi
        from thermalright_lcd_control.digital.runtime import DigitalRuntime
        dcfg = dict(cfg)
        dcfg["digital"] = {"controller_config": a.controller_config, "defaults": a.digital_defaults}
        dev = {"vid_pid": "0416:8001", "model": "Fake digital panel", "connected": True, "kind": "digital"}
        ident = settings.identity(dcfg, dev, 0, 0)
        ident.update(device_kind="digital", resolution="segment")
        drt = DigitalRuntime(dcfg, dev, state, log, identity=ident)
        DigitalApi(drt, api_cfg, log).serve()
        log.info(f"fake digital panel; controller config {drt.controller_config}; UI http://127.0.0.1:{a.port}/")
        time.sleep(a.seconds or 10 ** 9)
        return 0
    device = {"vid_pid": "0000:0000", "model": f"Fake panel {w}x{h}", "connected": True, "class": "FakeDevice"}
    ident = settings.identity(cfg, device, w, h)
    rt = Runtime(w, h, device, cfg, state, log, identity=ident)
    DisplayApi(rt, api_cfg, log).serve()
    log.info(f"fake {w}x{h} panel; state {state}; UI http://127.0.0.1:{a.port}/ token '{a.token}'")

    frames = Path(a.frames_dir) if a.frames_dir else None
    if frames:
        frames.mkdir(parents=True, exist_ok=True)

    def loop():
        last_png = 0.0
        while True:
            t0 = time.monotonic()
            img, delay = rt.get_frame_with_duration()
            STATS.frame((time.monotonic() - t0) * 1000.0)
            rt.frame_sent()
            if frames and time.monotonic() - last_png >= 1.0:
                tmp = frames / ".frame.png"
                img.save(tmp)
                os.replace(tmp, frames / "frame.png")
                last_png = time.monotonic()
            if rt.wake.wait(max(0.0, delay - (time.monotonic() - t0))):
                rt.wake.clear()

    threading.Thread(target=loop, name="fake-panel", daemon=True).start()
    try:
        if a.seconds:
            time.sleep(a.seconds)
        else:
            while True:
                time.sleep(3600)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
