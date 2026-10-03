# SPDX-License-Identifier: Apache-2.0
"""Hardware showcase: one sampler feeding the LCD layout and OTLP metrics.

Added by the Vigyan packaging (see README "Vigyan packaging"). Everything here
is read-only with respect to the hardware: sysfs reads, Intel RAPL energy
counters and NVML queries. Nothing changes clocks, power limits or GPU state.
"""
