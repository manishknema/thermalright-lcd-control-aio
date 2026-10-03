# SPDX-License-Identifier: Apache-2.0
"""OTLP/HTTP metrics for the same readings the LCD shows.

Needs the `otel` extra. Targets the node-local collector (default
http://127.0.0.1:4318); the collector adds host/node identity and ships them on.

Config (config_<w><h>.yaml):

    telemetry:
      enabled: true
      otlp_endpoint: http://127.0.0.1:4318   # or OTEL_EXPORTER_OTLP_ENDPOINT
      interval_seconds: 15
      resource_attributes: {}                # extra resource attributes, e.g. a fleet node id

Resource: service.name, host.name, device.kind, device.model, hw.lcd.device,
hw.lcd.resolution (from the service identity) + resource_attributes. Export runs
on the SDK's own thread; a collector outage never affects the panel or the API.

Metric names (OpenObserve stream = name with dots as underscores):
  hw.cpu.temperature  hw.cpu.power  hw.cpu.utilization  hw.cpu.frequency
  hw.cpu.core.utilization{cpu.core}
  hw.gpu.temperature  hw.gpu.power  hw.gpu.utilization
  hw.gpu.memory.used  hw.gpu.memory.total            {gpu.index, gpu.name}
  hw.memory.used  hw.memory.total  hw.memory.utilization
  hw.nvme.temperature{nvme.device}
  hw.lcd.frames_sent  hw.lcd.frame_errors             (cumulative counters)
"""
from typing import Optional

from thermalright_lcd_control.showcase.sensors import SamplerThread
from thermalright_lcd_control.showcase.stats import STATS

SERVICE_NAME = "thermalright-lcd"


def start(cfg: Optional[dict], logger, identity: Optional[dict] = None) -> bool:
    cfg = cfg or {}
    if not cfg.get("enabled", False):
        logger.info("OTLP telemetry disabled (telemetry.enabled is false)")
        return False
    try:
        from opentelemetry import metrics
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
        from opentelemetry.metrics import CallbackOptions, Observation
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource
    except ImportError:
        logger.warning("OTLP telemetry requested but the 'otel' extra is not installed")
        return False

    try:
        from importlib.metadata import version
        svc_version = version("thermalright-lcd-control")
    except Exception:
        svc_version = "unknown"

    from thermalright_lcd_control import settings
    endpoint = str(settings.otlp_endpoint(cfg)).rstrip("/") + "/v1/metrics"
    interval_ms = int(float(cfg.get("interval_seconds", 15)) * 1000)
    sampler = SamplerThread.get()

    reader = PeriodicExportingMetricReader(OTLPMetricExporter(endpoint=endpoint, timeout=5),
                                           export_interval_millis=interval_ms)
    ident = identity or {}
    attrs = {"service.name": SERVICE_NAME, "service.version": svc_version,
             "host.name": ident.get("node_name", ""), "device.kind": ident.get("device_kind", ""),
             "device.model": ident.get("model", ""), "hw.lcd.device": ident.get("vid_pid", ""),
             "hw.lcd.resolution": ident.get("resolution", "")}
    # Deployment-specific identity (e.g. a fleet node id) comes from config, never code.
    attrs.update({str(k): str(v) for k, v in (cfg.get("resource_attributes") or {}).items()})
    resource = Resource.create({k: v for k, v in attrs.items() if v})
    provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(provider)
    meter = metrics.get_meter("thermalright_lcd_control.showcase")

    def scalar(attr):
        def cb(_: CallbackOptions):
            v = getattr(sampler.latest, attr)
            return [Observation(v)] if v is not None else []
        return cb

    def cores(_: CallbackOptions):
        return [Observation(p, {"cpu.core": i}) for i, p in enumerate(sampler.latest.cpu_cores)]

    def gpu(attr, scale=1.0):
        def cb(_: CallbackOptions):
            out = []
            for g in sampler.latest.gpus:
                v = getattr(g, attr)
                if v is not None:
                    out.append(Observation(v * scale, {"gpu.index": g.index, "gpu.name": g.name}))
            return out
        return cb

    def nvme(_: CallbackOptions):
        return [Observation(t, {"nvme.device": d}) for d, t in sampler.latest.nvme.items()]

    g = meter.create_observable_gauge
    g("hw.cpu.temperature", [scalar("cpu_temperature")], unit="Cel", description="CPU package temperature")
    g("hw.cpu.power", [scalar("cpu_power_watts")], unit="W", description="CPU package power (Intel RAPL)")
    g("hw.cpu.utilization", [scalar("cpu_utilization")], unit="%", description="CPU load, all threads")
    g("hw.cpu.frequency", [scalar("cpu_frequency_mhz")], unit="MHz", description="Average CPU clock")
    g("hw.cpu.core.utilization", [cores], unit="%", description="Per logical CPU load")
    g("hw.gpu.temperature", [gpu("temperature")], unit="Cel", description="GPU core temperature (NVML)")
    g("hw.gpu.power", [gpu("power_watts")], unit="W", description="GPU board power (NVML)")
    g("hw.gpu.utilization", [gpu("utilization")], unit="%", description="GPU utilisation (NVML)")
    g("hw.gpu.memory.used", [gpu("memory_used")], unit="By", description="GPU memory used (NVML)")
    g("hw.gpu.memory.total", [gpu("memory_total")], unit="By", description="GPU memory total (NVML)")
    g("hw.memory.used", [scalar("memory_used")], unit="By", description="RAM used (total - available)")
    g("hw.memory.total", [scalar("memory_total")], unit="By", description="RAM total")
    g("hw.memory.utilization", [scalar("memory_utilization")], unit="%", description="RAM used percent")
    g("hw.nvme.temperature", [nvme], unit="Cel", description="NVMe composite temperature")
    meter.create_observable_counter("hw.lcd.frames_sent", [lambda _: [Observation(STATS.frames_sent)]],
                                    unit="{frame}", description="Frames written to the LCD")
    meter.create_observable_counter("hw.lcd.frame_errors", [lambda _: [Observation(STATS.frame_errors)]],
                                    unit="{frame}", description="Frame writes that failed")
    logger.info(f"OTLP telemetry -> {endpoint} every {interval_ms // 1000}s")
    return True
