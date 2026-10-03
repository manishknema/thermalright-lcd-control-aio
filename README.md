# Thermalright LCD Control

A Linux application for controlling Thermalright LCD displays with an intuitive graphical interface.

![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)
![Platform](https://img.shields.io/badge/platform-Linux-lightgrey.svg)
![version](https://img.shields.io/badge/version-1.3.1-green.svg)

## Overview

Thermalright LCD Control provides an easy-to-use interface for managing your Thermalright LCD display on Linux systems.

The application features both a desktop GUI and a background service for seamless device control.

I performed reverse engineering on the Thermalright Windows application to understand its internal mechanisms.

During my analysis, I identified four different USB VID:PID combinations handled by the Windows application, all sharing
the same interaction logic.

Since I have access only to the Frozen Warframe 420 BLACK ARGB, my testing was limited exclusively to this specific
device.

Also, this application implements reading metrics from Amd, Nvidia, and Intel GPU. My testing was limited to Nvidia GPU.

Feel free to contribute to this project and let me know if the application is working with other devices.

For backgrounds, i have included all media formats supported by the Windows application
and added the option to select a collection of images to cycle through on the display.

## Features

- 🖥️ **User-friendly GUI** - Modern interface for device configuration
- ⚙️ **Background service** - Automatic device management
- 🎨 **Theme support** - Customizable display themes and backgrounds
- 📋 **System integration** - Native Linux desktop integration

## Supported devices

| VID:PID   | SCREEN RESOLUTION |
|-----------|-------------------|
| 0416:5302 | 320x240           |
| 0418:5304 | 480x480           |
| 87AD:70DB | 320x320,480x480   |

## Installation

### Download Packages

Download the appropriate package for your Linux distribution from
the [Releases](https://www.github.com/rejeb/thermalright-lcd-control/releases) page:

- **`.targ.gz`** - For any distribution

### Installation

1. **Check** for required dependencies:
   /!\ Make sure you have these required dependencies installed:
    - python3
    - python3-pip
    - python3-venv
    - libhidapi-* or hidapi depending on your distribution

2. **Download** the `.tar.gz` package:
   ```bash
   wget https://github.com/rejeb/thermalright-lcd-control/releases/download/1.3.1/thermalright-lcd-control-1.3.1.tar.gz -P /tmp/
   ```

3. **Untar** the archive file:
   ```bash
   cd /tmp
   
   tar -xvf thermalright-lcd-control-1.3.1.tar.gz
   ```

4. **Install** application:
   ```bash
   cd /thermalright-lcd-control
   
   sudo bash install.sh
   ```

That's it! The application is now installed. You can see the default theme displayed on your Thermalright LCD device.

## Troubleshooting

If your device is 0416:5302 and nothing is displayed:
- Check service status to see if it is running
- Try restart service
- Check service logs located in /var/log/thermalright-lcd-control.log

If your device is one of the other devices, contributions are welcome.
Here some tips to help you:
- Check service status to see if it is running
- Check service logs located in /var/log/thermalright-lcd-control.log
- If the device is not working then this possibly mean that header value is not correct.
See [Add new device](#add-new-device) section to fix header generation.
- If the device is working but image is not good, this means that the image is not encoded correctly.
See [Add new device](#add-new-device) section to fix image encoding by overriding method _`_encode_image`.

## Usage

### Launch the Application

- **From Applications Menu**: Search for "Thermalright LCD Control" in your application launcher
- **From Terminal**: Run `thermalright-lcd-control`

### System Service

The background service starts automatically after installation. You can manage it using:

# Check service status

sudo systemctl status thermalright-lcd-control.service

# Restart service

sudo systemctl restart thermalright-lcd-control.service

# Stop service

sudo systemctl stop thermalright-lcd-control.service

## System Requirements

- **Operating System**: Ubuntu 20.04+ / Debian 11+ / Other modern Linux distributions
- **Python**: 3.8 or higher (automatically managed)
- **Desktop Environment**: Any modern Linux desktop (GNOME, KDE, XFCE, etc.)
- **Hardware**: Compatible Thermalright LCD device

## Vigyan packaging

This fork packages the upstream project as a governed, headless-first service for
the Vigyan fleet. Upstream behaviour (themes, GUI, device support) is unchanged;
everything below is additive.

**Packaging.** The interpreter comes from conda (`python=3.13`, conda-forge) and
the dependencies come from `uv.lock`, exactly:

```bash
conda create -p <rt>/conda -c conda-forge --override-channels python=3.13
UV_PROJECT_ENVIRONMENT=<rt>/venv uv sync --frozen --no-dev --no-editable \
    --extra otel --python <rt>/conda/bin/python
```

The core install is headless. Optional extras:

| extra   | adds                                    | for                         |
|---------|-----------------------------------------|-----------------------------|
| `otel`  | OpenTelemetry SDK + OTLP/HTTP exporter  | metrics to a local collector |
| `gui`   | PySide6 + opencv-python                 | dev nodes with a display     |
| `video` | opencv-python-headless                  | video backgrounds, headless  |

`gui` and `video` are declared as conflicting (both provide `cv2`). The OS still
has to provide `libhidapi-hidraw0` and `libusb-1.0-0`.

**Showcase layout.** If `showcase.enabled: true` is set in `config_<w><h>.yaml`,
the service draws a hardware dashboard instead of a theme. It shows CPU package
temperature and watts (from Intel RAPL energy counters), per-core load bars, NVML
GPU temperature, power, utilisation and VRAM, RAM, and NVMe temperature. All
reads are read-only: sysfs, RAPL and NVML queries. Templates for each panel size
are in `resources/config/showcase/`. With `showcase.enabled: false` the upstream
theme in the same file's `display:` block is used.

**Telemetry.** With the `otel` extra and `telemetry.enabled: true`, the service
exports the same readings as OTLP gauges (`hw.cpu.temperature`, `hw.cpu.power`,
`hw.cpu.core.utilization`, `hw.gpu.*`, `hw.memory.*`, `hw.nvme.temperature`). It
also exports the counters `hw.lcd.frames_sent` and `hw.lcd.frame_errors`. The
default endpoint is `http://127.0.0.1:4318`.

**Service behaviour.** The service:

- waits for a hot-plugged panel instead of exiting;
- writes a `frames_sent=N` line every 60 s, so you can confirm frames are reaching
  the device;
- exits on a USB write error so that systemd (`Restart=always`) reopens the device;
- logs to journald when it runs under systemd.

The RGB565 encoder uses numpy and produces byte-identical output to the upstream
per-pixel loop.

**Probe.** `thermalright-lcd-control-probe` prints what this machine can read.
`--png out.png` renders the showcase frame to a file, and `--usb` lists the
attached panels.

**Fleet install.** The installer is in the Vigyan-Virtual-Cloud repo:
`scripts/a19-install-thermalright-aio.sh`. It is also available as the llm-cli
feature `hw-display` (`llm-cli hw-display ...`). The installer:

- detects the panel by USB VID:PID;
- installs a group-scoped udev rule;
- installs `vigyan-thermalright-aio.service`, which runs as the unprivileged user
  `vigyan-hwdisplay`;
- grants that group read access to RAPL `energy_uj` at each start (the file is
  root-only by default, CVE-2020-8694);
- keeps config in `/etc/vigyan/thermalright/aio/`.

Components: `service` (default), `gui`, `themes` and `dashboard`. The `dashboard`
component installs the OpenObserve "Hardware showcase" dashboard. If `themes` is
not chosen, the 60 MB theme pack is left out by sparse checkout.

## Add new device

In [HOWTO.md](doc/HOWTO.md) I detail all the steps I gone through to find out how myy device works and all steps to add
a new device.

## License

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.

## Author

**REJEB BEN REJEB** - [benrejebrejeb@gmail.com](mailto:benrejebrejeb@gmail.com)

## 🤝 Contributing

Contributions are welcome! To contribute:

1. Fork the project
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Commit your changes (`git commit -am 'Add my feature'`)
4. Push to your branch (`git push origin feature/my-feature`)
5. Create a Pull Request
