# Thermalright LCD Control — headless service + web dashboard

> **This is the `vigyan` branch** of a fork of
> [rejeb/thermalright-lcd-control](https://github.com/rejeb/thermalright-lcd-control).
> `master` mirrors upstream unchanged. Everything below the line "Upstream README" is the
> original project's documentation, kept for reference.

## What it is for

Thermalright AIO coolers with a built-in screen (USB `0416:5302`, `0418:5304`, `87AD:70DB`)
can show live system data. On Windows the vendor app does this; on Linux, this project does.

This branch turns it into something you **install once and forget, then control from a browser**:

- **Always-on background service.** Starts at boot and drives the cooler's screen
  continuously. It restarts itself on errors and waits for the display if it's unplugged.
  Runs as an unprivileged user; no desktop session or GUI is needed, so it suits headless servers.
- **Web dashboard** served by the service itself: see exactly what the screen is showing, pick a
  design, switch colour packs, edit layouts, upload backgrounds and set rotation. **Changes reach
  the screen within a second**, with no restart.
- **Real hardware data.** CPU package temperature and **watts** (Intel RAPL), per-core load,
  NVIDIA GPU temperature, power, utilisation and VRAM (read-only), RAM, NVMe temperature, clock.
  Widgets that need missing hardware (for example the GPU) hide themselves.
- **Seven built-in designs:** Core Gauge, Power Station, Thermal Strip, Core Grid, AI Node,
  Minimal Clock, GPU Focus. **Six colour packs:** Slate, Midnight, Solar, Terminal, Arctic,
  High Contrast. Any design works with any pack, and you can save your own.
- **Optional metrics export:** the same readings over OpenTelemetry (OTLP) to your own
  collector, if you run one.

## What changed from upstream

| | upstream | this branch |
|---|---|---|
| Interface | PySide6 desktop GUI | web dashboard (the PySide6 GUI was removed; every feature is mapped in [docs/GUI_FEATURE_INVENTORY.md](docs/GUI_FEATURE_INVENTORY.md)) |
| Themes | background image + text at fixed positions | widget themes (gauges, rings, bars, sparklines, core grid); upstream themes still load |
| Applying a theme | restart the service | live, within 1 s |
| Runs as | your user, with the GUI | system service, unprivileged user |
| Control | local GUI only | token-protected local API (`127.0.0.1:7431`) + web UI; LAN access off by default |
| Packaging | uv | conda (Python 3.13) + `uv sync --frozen` from `uv.lock`; GUI-free headless install |

## Quick start

```bash
sudo deploy/install.sh                  # asks where src, env, config and state go; service user; unit; udev
sudo deploy/install.sh --yes --start    # same with defaults, then start
deploy/install.sh --user --yes --start  # per-user install under $HOME (user systemd unit)
xdg-open http://127.0.0.1:7431/         # token: <config dir>/api.token
```

The installer keeps a source checkout (`--src`, optionally pinned with `--ref`). It
builds the venv from it with `uv sync --frozen`, using an interpreter from a conda
env (`--conda`) or a uv-managed CPython 3.13. Then it writes the config and,
optionally, the service user, udev rule and systemd unit. Each location is asked
for interactively or set with flags/env (`THERMALRIGHT_SRC`, `THERMALRIGHT_VENV`,
`THERMALRIGHT_CONFIG_DIR`, `THERMALRIGHT_STATE_DIR`). `--set KEY=VALUE` overrides
any config value. Run `deploy/install.sh --help` for the full list.

**Without the installer:** build a wheel (`uv build --wheel`; hatchling is pinned,
so the build is reproducible), install it into any venv, then run
`thermalright-lcd-control-init --config-dir DIR --state-dir DIR`. Its
`--print-udev` and `--print-unit system|user` options give you the udev rule and
a systemd unit.

**Deployment kit:**

- `deploy/nginx/install-nginx.sh` puts the UI and API behind any nginx. Reads stay
  open; writes need a login (htpasswd, or `auth_request` to your own auth
  service, such as a PAM checker), are rate limited, and must use HTTPS.
- `deploy/portal/node-card.html` is a read-only status card you can embed in any
  portal page.
- `thermalright-lcd-control-dev` runs everything against a fake panel for
  development.
- `skills/thermalright-lcd/SKILL.md` teaches a coding agent to install, test,
  extend and ship this project. It is linked from `.agents/skills`,
  `.claude/skills` and `.codex/skills`.

Check your sensors without touching the display: `thermalright-lcd-control-probe`.

## Configuration

Nothing is tied to a particular machine. Every path and name comes from the `service:` block of
the config file or an environment variable, with neutral defaults:

| Setting | Env var | Default |
|---|---|---|
| Node name / id / role | `THERMALRIGHT_NODE_NAME`, `THERMALRIGHT_NODE_ID`, `THERMALRIGHT_NODE_ROLE` | hostname |
| Source checkout / venv / conda | `THERMALRIGHT_SRC`, `THERMALRIGHT_VENV`, `THERMALRIGHT_CONDA` (deploy/install.sh) | `/opt/thermalright-lcd/{src,venv}`, no conda; `--user`: `~/.local/share/thermalright-lcd/…` |
| Config dir (defaults, token) | `THERMALRIGHT_CONFIG_DIR` (deploy/install.sh) | `/etc/thermalright-lcd`; `--user`: `~/.config/thermalright-lcd` |
| State (your themes, uploads) | `THERMALRIGHT_STATE_DIR` | `/var/lib/thermalright-lcd`; `--user`: `~/.local/state/thermalright-lcd` |
| API address / port / LAN | `THERMALRIGHT_API_BIND`, `THERMALRIGHT_API_PORT`, `THERMALRIGHT_API_LAN` | `127.0.0.1`, `7431`, off |
| API token file | `THERMALRIGHT_API_TOKEN_FILE` | `/etc/thermalright-lcd/api.token` |
| URL prefix behind a reverse proxy | `THERMALRIGHT_API_BASE_PATH` | none |
| Service name | `THERMALRIGHT_SERVICE_NAME` | `thermalright-lcd-control` |
| Metrics export | `OTEL_EXPORTER_OTLP_ENDPOINT` | off |

Deployment tooling can set all of these; one example deployment (systemd unit, udev rule,
reverse-proxy route, node discovery) is described under "Vigyan packaging" below.

## Security

The API needs a bearer token and listens on loopback only unless you turn LAN access on. The
service needs only the USB display (granted through a udev rule) and read access to RAPL
energy counters (granted when it starts). It never needs root while running.

**Behind a reverse proxy.** If a proxy adds the token on the server side, then
anyone who can reach the proxy can do whatever the token allows. The proxy
therefore has to protect writes itself. The supported model is:

- **Reads stay open:** `GET` and `HEAD` requests (status, metrics, frame PNG,
  lists) and `POST api/preview.png` (renders a draft without saving anything).
- **Writes need a login:** every other `POST`, `PUT` and `DELETE` (apply, theme,
  pack and rotation changes, media uploads and deletes) must pass HTTP Basic
  auth at the proxy, for example nginx `limit_except GET HEAD { auth_basic ...; }`.
- **Sign-in path:** the proxy serves `<prefix>/login` behind the same realm and
  redirects back to `<prefix>/`.

**Forward auth.** `--auth auth_request` (also called `auth: forward`) sends writes
through nginx `auth_request` to any forward-auth endpoint that answers 2xx
(allowed), 401 (no session) or 403 (not allowed). That can be oauth2-proxy,
Authelia, Authentik, or your own service. Set `--auth-url` to that endpoint, for
example `http://127.0.0.1:4180/oauth2/auth?allowed_groups=lcd-operators`. With
`--signin-url /oauth2/start`, the sign-in page sends a 401 to the proxy's sign-in
URL; writes keep returning plain 401/403. Any OIDC provider works behind
oauth2-proxy (Keycloak, Google, GitHub, Nextcloud with its OIDC app, …).
htpasswd stays the default.

When a write returns `401` with `WWW-Authenticate: Basic`, the web UI shows
**Sign in to edit**, which opens that `login` URL. After you sign in, the browser
sends the credentials with every later write under the same prefix. Viewing
never asks for a password.

---

# Upstream README


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

This fork packages the upstream project as a headless, governed service with a
web UI. Device support and the upstream v1 YAML themes still work. The PySide6
GUI has been removed; [docs/GUI_FEATURE_INVENTORY.md](docs/GUI_FEATURE_INVENTORY.md)
lists every GUI feature and its web UI equivalent.

### Install

conda supplies the interpreter (`python=3.13`, conda-forge). `uv.lock` supplies
the dependencies, exactly:

```bash
conda create -p <rt>/conda -c conda-forge --override-channels python=3.13
UV_PROJECT_ENVIRONMENT=<rt>/venv uv sync --frozen --no-dev --no-editable \
    --extra otel --extra video --python <rt>/conda/bin/python
```

| extra   | adds                                    | used for                                 |
|---------|-----------------------------------------|------------------------------------------|
| `otel`  | OpenTelemetry SDK + OTLP/HTTP exporter  | sending metrics to a local collector     |
| `video` | opencv-python-headless                  | video backgrounds and video thumbnails   |

The OS must provide `libhidapi-hidraw0` and `libusb-1.0-0`. The web UI is
prebuilt into `src/thermalright_lcd_control/web/`, so nodes need no Node
toolchain. To rebuild it, run `cd web && pnpm install && pnpm build`
(Vite + TypeScript + Preact).

### Service, API and web UI

If `config_<w><h>.yaml` has a `service:` block, the service runs the theme v2
runtime and a local HTTP API (stdlib). Templates are in
`src/thermalright_lcd_control/data/service_config/` (shipped in the wheel).

- **Address.** The API binds `127.0.0.1:7431` unless `service.api.lan: true`.
- **Token.** Every `/api/*` call except `/api/health` needs the token from
  `service.api.token_file`, sent as `X-Display-Token`. A gateway in front injects
  it, so the browser never holds it.
- **Web UI.** Served at `/`, with relative URLs, so it works under any prefix
  such as `/display/`.
- **State.** Everything a user changes (themes, packs, uploaded media, the
  active selection, rotation) is written by the service to `service.state_dir`.
  The `/etc` config holds defaults only.
- **Live apply.** Applying a theme swaps the renderer and wakes the frame loop.
  The panel shows the change on the next frame, without a restart or a USB
  reconnect. `GET /api/status` reports `apply_to_first_frame_s`.
- **Preview.** `/api/frame.png` is the exact last frame sent to the panel.
  `/api/preview.png` renders unsaved edits with the same renderer.

The full route list is in the docstring of `src/thermalright_lcd_control/api/server.py`.

**Configuration.** Nothing deployment-specific is built in. Every path, name and
address comes from the config file or an environment variable, and each has a
neutral default; `src/thermalright_lcd_control/settings.py` lists them all. The
main ones:

| What | Default |
|---|---|
| state dir | `/var/lib/thermalright-lcd`, or systemd `StateDirectory=` |
| token file | `/etc/thermalright-lcd/api.token` |
| API address | `127.0.0.1:7431` |
| node name and id | the hostname |
| node page URL template | none |
| peers files | none |
| OTLP endpoint | `OTEL_EXPORTER_OTLP_ENDPOINT` |

Each display also gets a readable **slug**, such as `display-aio` or
`display-cpu-cooler`. It defaults to `<slug_prefix>-aio` for an image panel and
`<slug_prefix>-cpu-cooler` for a digital panel. Override it with
`service.api.slug`, `service.api.slug_prefix`, `THERMALRIGHT_DISPLAY_SLUG` or
`THERMALRIGHT_DISPLAY_SLUG_PREFIX`. Reverse proxies and node lists use the slug in
URLs, for example `node_url_template: /display/{slug}/`. Each slug must be unique
behind one proxy. The node id stays internal: it appears in identity, metrics and
discovery.

`GET /api/status` returns an `identity` block with the node name, id and role,
the device kind, model, USB id and resolution, and the service name. The same
values become the OTLP resource attributes. Extra attributes can be added under
`telemetry.resource_attributes`.

Designs can require node capabilities, such as `"requires": ["gpu"]` or
`"requires_any": ["rapl", "gpu"]`. The gallery marks a design that the node
cannot show, and rotation skips it.

### Digital segment displays (0416:8001)

A digital display has LED segments instead of an image panel. It is driven by its
own controller (MathieuxHugo/digital_thermal_right_lcd), which re-reads a JSON
config every frame. With `--device 0416:8001`, `thermalright-lcd-control-init`
writes `config_digital.yaml` and the service runs in **digital mode**. In that
mode it does not touch USB itself; it owns the controller's config file
(`digital.controller_config`, which defaults to `<state>/digital/config.json`)
and themes the display by rewriting that file atomically. The same API, token
and web UI apply, and the UI switches to a digital page that shows:

- the live LED view;
- the presets;
- the display mode, the temperature range and the cycle time.

**Presets** live in `digital/builtin/presets/*.json`, or in
`<state>/digital/presets/` for your own. Each preset sets the display mode per
layout (`small`, `big`), the LED colours (a default plus colours per named LED
group) and the ranges.

**Colours** are the controller's own syntax:

- `rrggbb`
- `random`
- `aaaaaa-bbbbbb`: a pulse
- `aaaaaa-bbbbbb-cpu_temp` (or `gpu_temp`, `cpu_usage`, `gpu_usage`, `seconds`,
  `minutes`, `hours`): a gradient

**Nodes without a GPU:** presets and modes that need a GPU reading are hidden.
GPU-keyed gradients collapse to their start colour, so the controller never
clamps a missing reading.

Run `thermalright-lcd-control-dev --kind digital --digital-defaults <controller config>`
to try this without the hardware.

### Theme v2 (designs, widgets, packs)

A theme is a design (a list of widgets) plus a pack (palette, fonts and an
optional mark).

**Built-in designs.** There are seven: `core-gauge`, `power-station`,
`thermal-strip`, `core-grid`, `ai-node`, `minimal-clock` and `gpu-focus`.

- They are authored on a 320x240 base canvas and scaled uniformly to other panel
  sizes. A design can carry hand-tuned `layouts["480x480"]` instead.
- Widgets marked `"requires": "gpu"` are skipped on nodes without an NVML GPU.
  Any metric that is unavailable is drawn as an em dash.

**Reading hierarchy.** Every built-in design shows the CPU package temperature
in heat colours. On a CPU design it is the largest number. The order of size is
CPU temperature, then GPU temperature, then CPU watts; a wattage is never drawn
larger than a temperature on the same design. `"flash_at": 85` on a temperature
widget turns on the hot state: at or above 85 °C (high for an Intel Core Ultra
package) the reading shows inverted on the pack's `hot` colour on alternate
seconds.

**Widget types.** `text` (templates such as `{cpu.temp:.0f}` or
`{sys.power@peak:.0f}`), `number`, `arc`, `ring`, `bar`, `sparkline` (60 s
history buffer), `coregrid` (sized to the host's core count), `clock`, `dots`
(service health), `rect` and `image`.

**Metric ids.** The `CATALOG` in `themes/metrics.py` defines them: CPU package
temperature and watts (Intel RAPL), load, clock, per-core load; GPU temperature,
power, utilisation, VRAM, clock and fan (NVML, read-only); RAM; NVMe; system
draw; and optionally `llm.tokens_s` (from a Prometheus counter) and `svc.<name>`
health.

The theme schema is documented in the docstring of `themes/engine.py`.

**Pack schema** (`themes/builtin/packs/*.json`; user packs go in `<state>/packs/`):

```json
{
  "schema": 1, "id": "slate", "name": "Slate", "ground": "dark",
  "colors": {"ink": "#0c0e14", "panel": "#181c26", "line": "#2c3240", "text": "#eceef3",
             "muted": "#8a92a2", "accent1": "#f59e0b", "accent2": "#2dd4bf", "accent3": "#a78bfa",
             "ok": "#22c55e", "warn": "#f59e0b", "hot": "#ef4444"},
  "fonts": {"display": null, "bold": null, "body": null, "mono": null},
  "mark": null,
  "default_mark": "none"
}
```

- `ok`, `warn` and `hot` form the heat scale.
- Font paths are relative to the pack file. `null` means the DejaVu default.
- `mark` holds the `small` and `big` images per variant (`deep` and `ivory`).
- A theme's `mark: {mode: corner|background|none, opacity: 0.05-0.20, variant:
  auto|deep|ivory}` chooses one mark per frame. `corner` uses the small image
  (at most 32 px); `background` uses one centred large image at that opacity.
- The neutral packs on this branch are slate (the default), midnight, solar,
  terminal, arctic (light) and contrast. Brand packs are kept on a separate
  branch and never ship on main. More packs are just more files.

### Telemetry, probe and fleet install

**Telemetry.** With `telemetry.enabled`, the readings the panel shows are also
sent as OTLP gauges: `hw.cpu.*`, `hw.gpu.*`, `hw.memory.*`,
`hw.nvme.temperature`, `hw.lcd.frames_sent` and `hw.lcd.frame_errors`.

**Probe.** `thermalright-lcd-control-probe` prints what this machine can read.
`--png out.png --design ai-node --pack slate` renders a design with live
readings.

**Fleet install.** Vigyan-Virtual-Cloud
`scripts/a19-install-thermalright-aio.sh` (also run as `llm-cli hw-display`):

- detects the panel by USB VID:PID;
- runs the service as the unprivileged user `vigyan-lcd`, with root owning the
  unit, the `/etc` defaults and the token, and `StateDirectory=` for user state;
- grants RAPL read access to that user only;
- puts the web UI behind the node gateway at `/display/<node_id>/` (an example
  deployment; the fork itself assumes no URL layout).

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
