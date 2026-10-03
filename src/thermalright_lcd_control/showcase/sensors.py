# SPDX-License-Identifier: Apache-2.0
"""Read-only hardware sensors for the showcase layout and OTLP export.

Sources:
  CPU package temp   hwmon coretemp "Package id N" (Intel) / k10temp Tctl|Tdie (AMD)
  CPU package watts  Intel RAPL energy_uj deltas (powercap intel-rapl:N, package-N)
  per-core load      psutil.cpu_percent(percpu=True), non-blocking
  GPU                NVML (nvidia-ml-py): temperature, power, utilisation, memory
  RAM                psutil.virtual_memory
  NVMe temp          hwmon "nvme" temp1_input (Composite)

energy_uj is root-only by default (CVE-2020-8694 mitigation). The packaged
systemd unit grants read to the service group only; without it cpu_power is None.
"""
import glob
import os
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

import psutil

RAPL_ROOT = "/sys/class/powercap"
HWMON_ROOT = "/sys/class/hwmon"


def _read(path: str) -> Optional[str]:
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def _read_int(path: str) -> Optional[int]:
    v = _read(path)
    try:
        return int(v) if v is not None else None
    except ValueError:
        return None


@dataclass
class GpuSample:
    index: int
    name: str
    temperature: Optional[float] = None
    power_watts: Optional[float] = None
    utilization: Optional[float] = None
    memory_used: Optional[int] = None
    memory_total: Optional[int] = None


@dataclass
class Sample:
    timestamp: float
    hostname: str
    cpu_temperature: Optional[float] = None
    cpu_power_watts: Optional[float] = None
    cpu_utilization: Optional[float] = None
    cpu_frequency_mhz: Optional[float] = None
    cpu_cores: list = field(default_factory=list)
    gpus: list = field(default_factory=list)
    memory_used: Optional[int] = None
    memory_total: Optional[int] = None
    memory_utilization: Optional[float] = None
    nvme: dict = field(default_factory=dict)

    def flat(self) -> dict:
        """Keys the upstream text-overlay themes can address by name."""
        g = self.gpus[0] if self.gpus else None
        nvme_max = max(self.nvme.values()) if self.nvme else None
        return {
            "cpu_temperature": _round(self.cpu_temperature),
            "cpu_usage": _round(self.cpu_utilization),
            "cpu_frequency": _round(self.cpu_frequency_mhz, 0),
            "cpu_power": _round(self.cpu_power_watts),
            "gpu_temperature": _round(g.temperature) if g else None,
            "gpu_usage": _round(g.utilization) if g else None,
            "gpu_power": _round(g.power_watts) if g else None,
            "gpu_vram_used_gb": _round(g.memory_used / 2**30) if g and g.memory_used is not None else None,
            "gpu_name": g.name if g else None,
            "ram_percent": _round(self.memory_utilization),
            "ram_used_gb": _round(self.memory_used / 2**30) if self.memory_used is not None else None,
            "nvme_temperature": _round(nvme_max),
        }


def _round(v, nd=1):
    return None if v is None else round(v, nd) if nd else int(round(v))


class _Rapl:
    """Package-domain RAPL counters, summed across sockets, wrap-safe."""

    def __init__(self):
        self.domains = []
        for d in sorted(glob.glob(os.path.join(RAPL_ROOT, "intel-rapl:*"))):
            if os.path.basename(d).count(":") != 1:
                continue  # sub-domains (core/uncore/dram) are not the package
            if not (_read(os.path.join(d, "name")) or "").startswith("package"):
                continue
            self.domains.append((d, _read_int(os.path.join(d, "max_energy_range_uj")) or 2**32))
        self.last = None
        self.readable = bool(self.domains) and all(
            _read_int(os.path.join(d, "energy_uj")) is not None for d, _ in self.domains)

    def watts(self) -> Optional[float]:
        if not self.readable:
            return None
        now = time.monotonic()
        vals = [_read_int(os.path.join(d, "energy_uj")) for d, _ in self.domains]
        if any(v is None for v in vals):
            return None
        prev, self.last = self.last, (now, vals)
        if prev is None or now - prev[0] <= 0:
            return None
        joules = 0.0
        for (d, rng), a, b in zip(self.domains, prev[1], vals):
            joules += ((b - a) if b >= a else (b + rng - a)) / 1e6
        return joules / (now - prev[0])


def _hwmon_by_name(name: str) -> list:
    return [h for h in sorted(glob.glob(os.path.join(HWMON_ROOT, "hwmon*")))
            if _read(os.path.join(h, "name")) == name]


def _labelled_temp(hwmon: str, wanted) -> Optional[str]:
    for lbl in sorted(glob.glob(os.path.join(hwmon, "temp*_label"))):
        if any(w in (_read(lbl) or "").lower() for w in wanted):
            return lbl.replace("_label", "_input")
    return None


class _CpuTemp:
    def __init__(self):
        self.paths = []
        for h in _hwmon_by_name("coretemp"):
            p = _labelled_temp(h, ("package id",))
            if p:
                self.paths.append(p)
        if not self.paths:
            for h in _hwmon_by_name("k10temp") + _hwmon_by_name("zenpower"):
                p = _labelled_temp(h, ("tdie",)) or _labelled_temp(h, ("tctl",))
                if p:
                    self.paths.append(p)

    def read(self) -> Optional[float]:
        vals = [v / 1000.0 for v in (_read_int(p) for p in self.paths) if v is not None]
        if vals:
            return max(vals)
        try:
            for key in ("coretemp", "k10temp", "cpu_thermal"):
                t = psutil.sensors_temperatures().get(key)
                if t:
                    return t[0].current
        except Exception:
            pass
        return None


class _Nvme:
    def __init__(self):
        self.paths = {}
        for h in _hwmon_by_name("nvme"):
            dev = os.path.basename(os.path.realpath(os.path.join(h, "device")))
            p = _labelled_temp(h, ("composite",)) or os.path.join(h, "temp1_input")
            self.paths[dev if dev.startswith("nvme") else os.path.basename(h)] = p

    def read(self) -> dict:
        out = {}
        for dev, p in self.paths.items():
            v = _read_int(p)
            if v is not None:
                out[dev] = v / 1000.0
        return out


class _Nvml:
    """NVML is used strictly for queries; no set* call is ever made."""

    def __init__(self):
        self.ok = False
        self.handles = []
        try:
            import pynvml
            self.nv = pynvml
            pynvml.nvmlInit()
            for i in range(pynvml.nvmlDeviceGetCount()):
                h = pynvml.nvmlDeviceGetHandleByIndex(i)
                name = pynvml.nvmlDeviceGetName(h)
                self.handles.append((i, name.decode() if isinstance(name, bytes) else name, h))
            self.ok = True
        except Exception:
            self.ok = False

    def _q(self, fn, *a):
        try:
            return fn(*a)
        except Exception:
            return None

    def read(self) -> list:
        if not self.ok:
            return []
        nv, out = self.nv, []
        for i, name, h in self.handles:
            s = GpuSample(index=i, name=name)
            s.temperature = self._q(nv.nvmlDeviceGetTemperature, h, nv.NVML_TEMPERATURE_GPU)
            mw = self._q(nv.nvmlDeviceGetPowerUsage, h)
            s.power_watts = mw / 1000.0 if mw is not None else None
            u = self._q(nv.nvmlDeviceGetUtilizationRates, h)
            s.utilization = float(u.gpu) if u is not None else None
            m = self._q(nv.nvmlDeviceGetMemoryInfo, h)
            if m is not None:
                s.memory_used, s.memory_total = int(m.used), int(m.total)
            out.append(s)
        return out


class HardwareSampler:
    def __init__(self):
        self.hostname = socket.gethostname()
        self.rapl = _Rapl()
        self.cpu_temp = _CpuTemp()
        self.nvme = _Nvme()
        self.nvml = _Nvml()
        psutil.cpu_percent(percpu=True)  # prime the non-blocking counters
        self.rapl.watts()

    def capabilities(self) -> dict:
        return {
            "cpu_temp_sources": self.cpu_temp.paths,
            "rapl_domains": [d for d, _ in self.rapl.domains],
            "rapl_readable": self.rapl.readable,
            "nvml": self.nvml.ok,
            "gpus": [n for _, n, _ in self.nvml.handles],
            "nvme": sorted(self.nvme.paths),
        }

    def sample(self) -> Sample:
        cores = psutil.cpu_percent(percpu=True)
        vm = psutil.virtual_memory()
        try:
            freq = psutil.cpu_freq()
        except Exception:
            freq = None
        return Sample(
            timestamp=time.time(),
            hostname=self.hostname,
            cpu_temperature=self.cpu_temp.read(),
            cpu_power_watts=self.rapl.watts(),
            cpu_utilization=sum(cores) / len(cores) if cores else None,
            cpu_frequency_mhz=freq.current if freq else None,
            cpu_cores=cores,
            gpus=self.nvml.read(),
            memory_used=int(vm.total - vm.available),
            memory_total=int(vm.total),
            memory_utilization=vm.percent,
            nvme=self.nvme.read(),
        )


class SamplerThread:
    """One background sampler per process; the LCD and OTLP read its latest Sample."""

    _instance = None
    _lock = threading.Lock()

    def __init__(self, interval: float):
        self.interval = max(0.5, interval)
        self.sampler = HardwareSampler()
        self.latest = self.sampler.sample()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="hw-sampler", daemon=True)
        self._thread.start()

    @classmethod
    def get(cls, interval: float = 1.0) -> "SamplerThread":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(interval)
            return cls._instance

    def _loop(self):
        while not self._stop.wait(self.interval):
            try:
                self.latest = self.sampler.sample()
            except Exception:
                pass  # a transient sysfs/NVML error keeps the previous sample
