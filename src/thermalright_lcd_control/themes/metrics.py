# SPDX-License-Identifier: Apache-2.0
"""Metric ids that theme widgets bind to, resolved from the live sampler.

Every id resolves to a number, a string, a list (cpu.cores) or None. None means
"not available on this node" and is drawn as an em dash. GPU ids are None on a
node without an NVML GPU; widgets marked `requires: gpu` are skipped there.

Extras (optional, configured in the service config `extras:` block):
  llm.tokens_s   tokens/s from a Prometheus counter (vLLM generation_tokens_total)
  svc.<name>     True/False health of a named endpoint (http(s) URL or tcp://host:port)
"""
import collections
import re
import socket
import threading
import time
import urllib.request
from typing import Any, Optional

from thermalright_lcd_control.showcase.sensors import HISTORY_SECONDS, Sample, SamplerThread

# id: (label, unit, default heat range or None, requires)
CATALOG = {
    "cpu.temp": ("CPU temperature", "°C", (35, 95), None),
    "cpu.power": ("CPU package power", "W", (15, 250), "rapl"),
    "cpu.load": ("CPU load", "%", (0, 100), None),
    "cpu.freq": ("CPU clock", "GHz", None, None),
    "cpu.count": ("CPU threads", "", None, None),
    "cpu.cores": ("Per-core load", "%", (0, 100), None),
    "gpu.temp": ("GPU temperature", "°C", (35, 90), "gpu"),
    "gpu.power": ("GPU power", "W", (20, 450), "gpu"),
    "gpu.util": ("GPU utilisation", "%", (0, 100), "gpu"),
    "gpu.vram_used": ("VRAM used", "GB", None, "gpu"),
    "gpu.vram_total": ("VRAM total", "GB", None, "gpu"),
    "gpu.vram_pct": ("VRAM used", "%", (0, 100), "gpu"),
    "gpu.clock": ("GPU clock", "GHz", None, "gpu"),
    "gpu.fan": ("GPU fan", "%", (0, 100), "gpu"),
    "gpu.name": ("GPU model", "", None, "gpu"),
    "gpu.short": ("GPU model (short)", "", None, "gpu"),
    "ram.used": ("RAM used", "GB", None, None),
    "ram.total": ("RAM total", "GB", None, None),
    "ram.pct": ("RAM used", "%", (0, 100), None),
    "nvme.temp": ("NVMe temperature", "°C", (30, 75), None),
    "sys.power": ("System draw (CPU + GPU)", "W", (30, 700), None),
    "llm.tokens_s": ("LLM tokens/s", "tok/s", None, "llm"),
    "node.name": ("Node name", "", None, None),
}

NUMERIC_HISTORY = ("cpu.temp", "cpu.power", "cpu.load", "gpu.temp", "gpu.power", "gpu.util",
                   "gpu.vram_pct", "ram.pct", "nvme.temp", "sys.power", "llm.tokens_s")


def _gb(v):
    return None if v is None else v / 2**30


def _short_gpu(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    n = re.sub(r"^(NVIDIA\s+)?(GeForce\s+)?", "", name)
    return n.replace(" Laptop GPU", "")


def from_sample(s: Sample) -> dict:
    g = s.gpus[0] if s.gpus else None
    vram_pct = (100.0 * g.memory_used / g.memory_total) if g and g.memory_used is not None and g.memory_total else None
    sys_power = None
    if s.cpu_power_watts is not None or (g and g.power_watts is not None):
        sys_power = (s.cpu_power_watts or 0.0) + ((g.power_watts or 0.0) if g else 0.0)
    return {
        "cpu.temp": s.cpu_temperature,
        "cpu.power": s.cpu_power_watts,
        "cpu.load": s.cpu_utilization,
        "cpu.freq": s.cpu_frequency_mhz / 1000.0 if s.cpu_frequency_mhz else None,
        "cpu.count": len(s.cpu_cores) or None,
        "cpu.cores": list(s.cpu_cores),
        "gpu.temp": g.temperature if g else None,
        "gpu.power": g.power_watts if g else None,
        "gpu.util": g.utilization if g else None,
        "gpu.vram_used": _gb(g.memory_used) if g else None,
        "gpu.vram_total": _gb(g.memory_total) if g else None,
        "gpu.vram_pct": vram_pct,
        "gpu.clock": g.clock_mhz / 1000.0 if g and g.clock_mhz else None,
        "gpu.fan": g.fan_percent if g else None,
        "gpu.name": g.name if g else None,
        "gpu.short": _short_gpu(g.name) if g else None,
        "ram.used": _gb(s.memory_used),
        "ram.total": _gb(s.memory_total),
        "ram.pct": s.memory_utilization,
        "nvme.temp": max(s.nvme.values()) if s.nvme else None,
        "sys.power": sys_power,
        "node.name": s.hostname,
    }


class Extras:
    """Polls the optional extras (tokens/s, service health) on its own thread."""

    def __init__(self, cfg: Optional[dict]):
        cfg = cfg or {}
        self.tokens = cfg.get("tokens") or {}
        self.services = cfg.get("services") or {}
        self.interval = float(cfg.get("interval_seconds", 2.0))
        self.values = {}
        self._last = None
        if self.tokens.get("url") or self.services:
            threading.Thread(target=self._loop, name="lcd-extras", daemon=True).start()

    @staticmethod
    def _get(url: str, timeout=1.5) -> Optional[str]:
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace") if r.status < 400 else None
        except Exception:
            return None

    @staticmethod
    def _tcp(target: str) -> bool:
        host, _, port = target.removeprefix("tcp://").rpartition(":")
        try:
            with socket.create_connection((host, int(port)), timeout=1.0):
                return True
        except (OSError, ValueError):
            return False

    def _poll_tokens(self):
        url = self.tokens.get("url")
        if not url:
            return
        name = self.tokens.get("metric", "vllm:generation_tokens_total")
        body = self._get(url)
        if body is None:
            self.values["llm.tokens_s"] = None
            self._last = None
            return
        total = 0.0
        for line in body.splitlines():
            if line.startswith(name + "{") or line.startswith(name + " "):
                try:
                    total += float(line.rsplit(" ", 1)[1])
                except ValueError:
                    pass
        now = time.monotonic()
        if self._last is not None and now > self._last[0] and total >= self._last[1]:
            self.values["llm.tokens_s"] = (total - self._last[1]) / (now - self._last[0])
        self._last = (now, total)

    def _loop(self):
        while True:
            self._poll_tokens()
            for name, target in self.services.items():
                ok = self._tcp(target) if str(target).startswith("tcp://") else self._get(target) is not None
                self.values[f"svc.{name}"] = ok
            time.sleep(self.interval)


class MetricBook:
    """Current values + rolling history for every metric id."""

    def __init__(self, sampler: SamplerThread, extras: Optional[Extras] = None):
        self.sampler = sampler
        self.extras = extras or Extras(None)
        self.history = {k: collections.deque(maxlen=int(HISTORY_SECONDS / sampler.interval) + 1)
                        for k in NUMERIC_HISTORY}
        self._record(sampler.latest)
        sampler.listeners.append(self._record)

    def _record(self, sample: Sample):
        cur = self.current(sample)
        for k, dq in self.history.items():
            v = cur.get(k)
            if isinstance(v, (int, float)):
                dq.append(v)

    def current(self, sample: Optional[Sample] = None) -> dict:
        vals = from_sample(sample or self.sampler.latest)
        vals.update(self.extras.values)
        vals.setdefault("llm.tokens_s", None)
        return vals

    def series(self, key: str, seconds: float) -> list:
        dq = self.history.get(key)
        if not dq:
            return []
        n = max(2, int(seconds / self.sampler.interval))
        return list(dq)[-n:]

    def capabilities(self) -> dict:
        cur = self.current()
        hs = self.sampler.sampler
        if not hs.rapl.domains:
            rapl_reason = "this CPU exposes no Intel RAPL package domain"
        elif not hs.rapl.readable:
            rapl_reason = ("energy_uj is root-only (CVE-2020-8694); the service unit must grant its "
                           "user read access at start (see README)")
        else:
            rapl_reason = None
        return {
            "gpu": cur["gpu.temp"] is not None or bool(hs.nvml.handles),
            "gpu_reason": None if hs.nvml.ok and hs.nvml.handles else "no NVIDIA GPU visible to NVML on this node",
            "rapl": cur["cpu.power"] is not None or hs.rapl.readable,
            "rapl_reason": rapl_reason,
            "llm": "llm.tokens_s" in self.extras.values or bool(self.extras.tokens.get("url")),
            "cores": cur["cpu.count"] or 0,
            "nvme": bool(hs.nvme.paths),
            "services": sorted(self.extras.services),
        }


def value(vals: dict, history: MetricBook, key: str) -> Any:
    """Resolve `key` or `key@peak|@avg|@min` (over the last 60 s of history)."""
    if "@" in key:
        base, agg = key.split("@", 1)
        s = history.series(base, 60)
        if not s:
            return None
        return {"peak": max, "max": max, "min": min}.get(agg, lambda x: sum(x) / len(x))(s)
    return vals.get(key)
