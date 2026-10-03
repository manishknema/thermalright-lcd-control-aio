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


def _start_runtime(device, logger):
    """Theme v2 runtime + local API when the config has a `service:` block.

    Without it the device keeps the upstream behaviour (config_<w><h>.yaml
    `display:` block, reloaded on mtime)."""
    cfg = _service_cfg(device).get("service")
    if not cfg:
        logger.info("No service: block in config; upstream theme mode")
        return
    from thermalright_lcd_control.themes.runtime import Runtime
    state_dir = os.environ.get("STATE_DIRECTORY", "").split(":")[0] or cfg.get("state_dir", "/var/lib/vigyan/thermalright")
    vid_pid = f"{device.vid:04x}:{device.pid:04x}"
    info = {"vid_pid": vid_pid, "model": cfg.get("model") or f"Thermalright {vid_pid} {device.width}x{device.height}",
            "connected": True, "class": type(device).__name__}
    rt = Runtime(device.width, device.height, info, cfg, state_dir, logger)
    device.frame_source = rt
    api_cfg = cfg.get("api") or {}
    if api_cfg.get("enabled", True):
        from thermalright_lcd_control.api.server import DisplayApi
        try:
            DisplayApi(rt, api_cfg, logger).serve()
        except OSError as e:
            logger.error(f"display API not started: {e}")


def _start_telemetry(device, logger):
    try:
        with open(device.config_file, "r", encoding="utf-8") as f:
            cfg = (yaml.safe_load(f) or {}).get("telemetry")
        from thermalright_lcd_control.showcase import telemetry
        telemetry.start(cfg, logger, device=f"{device.vid:04x}:{device.pid:04x}")
    except Exception as e:
        logger.warning(f"OTLP telemetry not started: {e}")
