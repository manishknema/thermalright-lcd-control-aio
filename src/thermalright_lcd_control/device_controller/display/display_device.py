# SPDX-License-Identifier: Apache-2.0
# Copyright © 2025 Rejeb Ben Rejeb
import pathlib
import time
from abc import abstractmethod, ABC

import numpy as np
import usb
import yaml
from PIL import Image

from thermalright_lcd_control.device_controller.display.config_loader import ConfigLoader
from thermalright_lcd_control.device_controller.display.generator import DisplayGenerator
from thermalright_lcd_control.common.logging_config import LoggerConfig
from thermalright_lcd_control.showcase.stats import STATS

STATS_LOG_INTERVAL = 60.0


class DisplayDevice(ABC):
    _generator: DisplayGenerator = None
    dev = None
    report_id = bytes([0x00])
    vid = None
    pid = None
    width = None
    height = None
    mode = None

    def __init__(self, vid, pid, chunk_size, width, height, config_dir: str, *args, **kwargs):
        self.vid = vid
        self.pid = pid
        self.height = height
        self.width = width
        self.chunk_size = chunk_size
        self.header = self.get_header()
        self.config_file = f"{config_dir}/config_{width}{height}.yaml"
        self.last_modified = pathlib.Path(self.config_file).stat().st_mtime_ns
        self.logger = self.logger = LoggerConfig.setup_service_logger()
        self._generator = self._build_generator()
        self.logger.debug(f"DisplayDevice initialized with header: {self.header}")

    def __getitem__(self, __name):
        return self.__getattribute__(__name)

    def __str__(self):
        return f"VID: {self.vid}, PID: {self.pid} ({self.width}x{self.height})"

    def _build_generator(self) -> DisplayGenerator:
        with open(self.config_file, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        showcase = raw.get("showcase") or {}
        if showcase.get("enabled"):
            from thermalright_lcd_control.showcase.renderer import ShowcaseGenerator
            self.logger.info(f"Showcase layout enabled ({self.width}x{self.height})")
            return ShowcaseGenerator(self.width, self.height, showcase)
        config_loader = ConfigLoader()
        config = config_loader.load_config(self.config_file, self.width, self.height)
        return DisplayGenerator(config)

    def _get_generator(self) -> DisplayGenerator:
        if self._generator is None:
            self.logger.info(f"No generator found, reloading from {self.config_file}")
            self._generator = self._build_generator()
            return self._generator
        elif pathlib.Path(self.config_file).stat().st_mtime_ns > self.last_modified:
            self.logger.info(f"Config file updated: {self.config_file}")
            self.last_modified = pathlib.Path(self.config_file).stat().st_mtime_ns
            self._generator = self._build_generator()
            self.logger.info(f"Display device generator reloaded from {self.config_file}")
            return self._generator
        else:
            return self._generator

    def _encode_image(self, img: Image) -> bytes:
        """RGB565 little-endian, column-major, bottom-to-top; the last pixel of
        every column is sent as 0x0000 (device framing quirk kept from upstream)."""
        a = np.asarray(img.convert("RGB"), dtype=np.uint16)
        v = ((a[..., 0] & 0xF8) << 8) | ((a[..., 1] & 0xFC) << 3) | (a[..., 2] >> 3)
        cols = v[::-1, :].T.copy()  # (width, height): x-major, y from bottom to top
        cols[:, -1] = 0
        return cols.astype("<u2").tobytes()

    @abstractmethod
    def get_header(self, *args, **kwargs):
        pass

    def reset(self):
        # Find device (ex. Winbond 0416:5302)
        dev = usb.core.find(idVendor=self.vid, idProduct=self.pid)
        if dev is None:
            raise ValueError("Display device not found")

        # Reset USB device
        dev.reset()
        self.logger.info("Display device reinitialised via USB reset")

    def _prepare_frame_packets(self, img_bytes: bytes):
        frame_packets = []
        for i in range(0, len(img_bytes), self.chunk_size):
            chunk = img_bytes[i:i + self.chunk_size]
            if len(chunk) < self.chunk_size:
                chunk += b"\x00" * (self.chunk_size - len(chunk))
            frame_packets.append(self.report_id + chunk)
        return frame_packets

    def start(self):
        self.logger.info(f"Display device ({self.vid}:{self.pid}-{self.width}x{self.height}) running ({self.mode} mode)")
        self._run()

    def _run(self):
        """Frame loop. A write error is fatal on purpose: the unit's Restart=always
        re-opens the device after a replug instead of spinning on a dead handle."""
        next_log = time.monotonic() + STATS_LOG_INTERVAL
        while True:
            t0 = time.monotonic()
            img, delay_time = self._get_generator().get_frame_with_duration()
            img_bytes = self.get_header() + self._encode_image(img)
            try:
                for packet in self._prepare_frame_packets(img_bytes):
                    self.send_packet(packet)
            except Exception:
                STATS.error()
                self.logger.error(f"LCD write failed after frames_sent={STATS.frames_sent}", exc_info=True)
                raise
            STATS.frame((time.monotonic() - t0) * 1000.0)
            if time.monotonic() >= next_log:
                next_log += STATS_LOG_INTERVAL
                self.logger.info(f"lcd frames_sent={STATS.frames_sent} frame_errors={STATS.frame_errors} "
                                 f"last_frame_ms={STATS.last_frame_ms:.1f}")
            time.sleep(max(0.0, delay_time - (time.monotonic() - t0)))

    @abstractmethod
    def send_packet(self, packet: bytes):
        pass

    def get(self, __name, default=None):
        return self.__dict__.get(__name, default)

    @staticmethod
    def info() -> dict:
        pass
