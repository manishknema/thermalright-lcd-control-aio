# SPDX-License-Identifier: Apache-2.0
"""Process-wide LCD counters: proof that frames reach the panel (logs + OTLP)."""
import threading
import time


class LcdStats:
    def __init__(self):
        self.lock = threading.Lock()
        self.frames_sent = 0
        self.frame_errors = 0
        self.last_frame_ms = 0.0
        self.started = time.time()

    def frame(self, ms: float):
        with self.lock:
            self.frames_sent += 1
            self.last_frame_ms = ms

    def error(self):
        with self.lock:
            self.frame_errors += 1


STATS = LcdStats()
