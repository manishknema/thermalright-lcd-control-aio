# SPDX-License-Identifier: Apache-2.0
"""LED layout of the Thermalright digital segment display (0416:8001).

Mirrors the controller this package themes (MathieuxHugo/digital_thermal_right_lcd,
src/config.py and controller.py), so presets and previews address the same LEDs:
84 LEDs, colours given per LED as "rrggbb", "random", "aaaaaa-bbbbbb" (pulse over
cycle_duration) or "aaaaaa-bbbbbb-<key>" (gradient by a metric or by the clock:
cpu_temp, gpu_temp, cpu_usage, gpu_usage, seconds, minutes, hours).

Segment order inside a digit (7 LEDs): top-left, top, top-right, middle,
bottom-left, bottom, bottom-right.
"""
NUMBER_OF_LEDS = 84

LAYOUTS = {
    "big": {
        "modes": ["metrics", "alternate_time", "time", "time_cpu", "time_gpu", "alternate_time_with_seconds", "debug_ui"],
        "groups": {
            "cpu": list(range(0, 42)), "gpu": list(range(42, 84)),
            "cpu_led": [0, 1], "cpu_temp": list(range(2, 23)), "cpu_celsius": [23], "cpu_fahrenheit": [24],
            "cpu_usage": list(range(25, 41)), "cpu_percent_led": [41],
            "gpu_led": [82, 83], "gpu_temp": list(range(81, 60, -1)), "gpu_celsius": [59], "gpu_fahrenheit": [60],
            "gpu_usage": list(range(58, 42, -1)), "gpu_percent_led": [42],
        },
    },
    "small": {
        "modes": ["cpu_temp", "cpu_usage", "gpu_temp", "gpu_usage", "alternate_metrics", "debug_ui"],
        "groups": {
            "digits": [14, 9, 10, 15, 13, 12, 11, 21, 16, 17, 22, 20, 19, 18, 28, 23, 24, 29, 27, 26, 25],
            "celsius": [6], "fahrenheit": [7], "percent": [8], "gpu_led": [4, 5], "cpu_led": [2, 3],
        },
    },
}

# Modes that need a GPU reading; hidden on nodes without one (otherwise the controller
# shows 0 and logs a clamp warning every frame).
GPU_MODES = {"gpu_temp", "gpu_usage", "alternate_metrics", "metrics", "alternate_time", "time_gpu"}
MODE_LABELS = {
    "cpu_temp": "CPU temperature", "cpu_usage": "CPU load", "gpu_temp": "GPU temperature",
    "gpu_usage": "GPU load", "alternate_metrics": "Cycle CPU/GPU temperature and load",
    "metrics": "CPU and GPU metrics", "alternate_time": "Clock and metrics, alternating",
    "time": "Clock (h:m:s)", "time_cpu": "Clock + CPU", "time_gpu": "Clock + GPU",
    "alternate_time_with_seconds": "Clock with seconds, then metrics", "debug_ui": "All LEDs on (test)",
}

DIGITS = [
    [1, 1, 1, 0, 1, 1, 1], [0, 0, 1, 0, 0, 0, 1], [0, 1, 1, 1, 1, 1, 0], [0, 1, 1, 1, 0, 1, 1],
    [1, 0, 1, 1, 0, 0, 1], [1, 1, 0, 1, 0, 1, 1], [1, 1, 0, 1, 1, 1, 1], [0, 1, 1, 0, 0, 0, 1],
    [1, 1, 1, 1, 1, 1, 1], [1, 1, 1, 1, 0, 1, 1], [0, 0, 0, 0, 0, 0, 0],
]


def digits_mask(value: int, n: int = 3, fill: str = "0") -> list:
    """Segment states for `value` right-aligned in n digits; the controller pads small
    readings with zeros ("058")."""
    s = str(max(0, int(value)))[-n:].rjust(n, fill)
    out = []
    for ch in s:
        out += DIGITS[int(ch)] if ch.isdigit() else DIGITS[10]
    return out
