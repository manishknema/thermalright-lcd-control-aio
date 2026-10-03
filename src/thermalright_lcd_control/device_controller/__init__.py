# SPDX-License-Identifier: Apache-2.0
# Copyright © 2025 Rejeb Ben Rejeb
import os
import time

import yaml

from thermalright_lcd_control.device_controller.display.device_loader import DeviceLoader
from thermalright_lcd_control.common.logging_config import get_service_logger

DEVICE_WAIT_SECONDS = 10


def run_service(config_dir: str):
    logger = get_service_logger()
    logger.info("Device controller service started")

    info_file = os.path.join(config_dir, "device_info.yaml")
    try:
        with open(info_file, encoding="utf-8") as f:
            kind = (yaml.safe_load(f) or {}).get("kind", "aio")
    except OSError:
        kind = "aio"
    if kind == "digital":
        return run_digital(config_dir, logger)

    try:
        loader = DeviceLoader(config_dir)
        device = loader.load_device()
        waited = False
        while device is None:
            # Unplugged or not yet enumerated: wait here rather than crash-loop the unit.
            if not waited:
                logger.warning(f"No device found; polling every {DEVICE_WAIT_SECONDS}s")
                waited = True
            time.sleep(DEVICE_WAIT_SECONDS)
            device = loader.load_device()
        _start_telemetry(device, logger)
        _start_runtime(device, logger)
        device.reset()
        device.start()
    except KeyboardInterrupt:
        logger.info("Device controller service stopped by user")
    except Exception as e:
        logger.error(f"Device controller service error: {e}", exc_info=True)
        raise


def _service_cfg(device) -> dict:
    with open(device.config_file, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _identity(device, svc: dict) -> dict:
    from thermalright_lcd_control import settings
    vid_pid = f"{device.vid:04x}:{device.pid:04x}"
    info = {"vid_pid": vid_pid, "model": svc.get("model") or f"Thermalright {vid_pid}"}
    return settings.identity(svc, info, device.width, device.height)


def _start_runtime(device, logger):
    """Theme v2 runtime + local API when the config has a `service:` block.

    Without it the device keeps the upstream behaviour (config_<w><h>.yaml
    `display:` block, reloaded on mtime)."""
    from thermalright_lcd_control import settings
    cfg = _service_cfg(device).get("service")
    if not cfg:
        logger.info("No service: block in config; upstream theme mode")
        return
    from thermalright_lcd_control.themes.runtime import Runtime
    ident = _identity(device, cfg)
    info = {"vid_pid": ident["vid_pid"], "model": ident["model"], "connected": True, "class": type(device).__name__}
    rt = Runtime(device.width, device.height, info, cfg, settings.state_dir(cfg), logger, identity=ident)
    device.frame_source = rt
    api_cfg = settings.api(cfg)
    if api_cfg["enabled"]:
        from thermalright_lcd_control.api.server import DisplayApi
        try:
            DisplayApi(rt, api_cfg, logger).serve()
        except OSError as e:
            logger.error(f"display API not started: {e}")


def _start_telemetry(device, logger):
    """OTLP is a side channel: any failure here is logged, never fatal."""
    try:
        full = _service_cfg(device)
        from thermalright_lcd_control.showcase import telemetry
        telemetry.start(full.get("telemetry"), logger, identity=_identity(device, full.get("service") or {}))
    except Exception as e:
        logger.warning(f"OTLP telemetry not started: {e}")


def run_digital(config_dir: str, logger, block: bool = True):
    """Digital segment display: theme its controller's config through the API (no USB here)."""
    from thermalright_lcd_control import settings
    from thermalright_lcd_control.api.server import DigitalApi
    from thermalright_lcd_control.digital.runtime import DigitalRuntime
    with open(os.path.join(config_dir, "config_digital.yaml"), encoding="utf-8") as f:
        full = yaml.safe_load(f) or {}
    svc = dict(full.get("service") or {})
    svc["digital"] = full.get("digital") or {}
    device = {"vid_pid": "0416:8001", "model": svc.get("model") or "Thermalright digital 0416:8001",
              "connected": True, "kind": "digital"}
    ident = settings.identity(svc, device, 0, 0)
    ident.update(device_kind="digital", resolution="segment")
    rt = DigitalRuntime(svc, device, settings.state_dir(svc), logger, identity=ident)
    try:
        from thermalright_lcd_control.showcase import telemetry
        telemetry.start(full.get("telemetry"), logger, identity=ident)
    except Exception as e:
        logger.warning(f"OTLP telemetry not started: {e}")
    api_cfg = settings.api(svc)
    DigitalApi(rt, api_cfg, logger).serve()
    logger.info(f"digital display service: controller config {rt.controller_config}")
    while block:
        time.sleep(3600)
    return rt
