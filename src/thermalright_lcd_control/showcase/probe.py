# SPDX-License-Identifier: Apache-2.0
"""thermalright-lcd-control-probe: what the showcase can read on this machine.

  thermalright-lcd-control-probe                 # sensor capabilities + one sample (JSON)
  thermalright-lcd-control-probe --png out.png   # also render the showcase frame to a file
  thermalright-lcd-control-probe --usb           # list attached supported LCDs (VID:PID)
"""
import argparse
import dataclasses
import json
import time


def main():
    ap = argparse.ArgumentParser(description="Probe showcase sensors (read-only)")
    ap.add_argument("--png", help="render the showcase layout to this PNG")
    ap.add_argument("--size", default="320x240", help="panel size for --png (WxH)")
    ap.add_argument("--usb", action="store_true", help="list supported LCDs that are attached")
    args = ap.parse_args()

    if args.usb:
        import usb.core
        from thermalright_lcd_control.common.supported_devices import SUPPORTED_DEVICES
        found = []
        for vid, pid, infos in SUPPORTED_DEVICES:
            if usb.core.find(idVendor=vid, idProduct=pid) is not None:
                found.append({"vid": f"{vid:04x}", "pid": f"{pid:04x}",
                              "panels": [f"{i['width']}x{i['height']}" for i in infos]})
        print(json.dumps({"devices": found}, indent=2))
        return 0 if found else 1

    from thermalright_lcd_control.showcase.sensors import HardwareSampler
    hs = HardwareSampler()
    time.sleep(1.0)  # RAPL watts and per-core load are deltas
    s = hs.sample()
    print(json.dumps({"capabilities": hs.capabilities(), "flat": s.flat(),
                      "sample": dataclasses.asdict(s)}, indent=2, default=str))
    if args.png:
        from thermalright_lcd_control.showcase.renderer import ShowcaseRenderer
        w, h = (int(x) for x in args.size.lower().split("x"))
        ShowcaseRenderer(w, h, {}).render(s).save(args.png)
        print(f"wrote {args.png}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
