---
name: thermalright-lcd
description: Install, configure, build, test and extend the Thermalright LCD service (thermalright-lcd-control) — headless renderer for Thermalright USB LCD coolers with a local API and web dashboard. Use when deploying it to a machine, adding a design, theme pack, widget type or API route, testing without hardware (fake panel), putting it behind nginx, or shipping a change (branch → test → push → deploy).
---

# Thermalright LCD service

A Python service drives a Thermalright USB LCD (0416:5302 320x240, 0418:5304 480x480,
87ad:70db 320x320/480x480). It renders designs (widgets bound to metric ids) with
theme packs (palette + fonts + optional mark), serves a token-protected local API
and a web UI (Vite + Preact, prebuilt), and can export readings as OTLP.

Repo map:

| Path | What |
|---|---|
| `src/thermalright_lcd_control/themes/engine.py` | renderer; its docstring is the theme/widget spec |
| `src/thermalright_lcd_control/themes/runtime.py` | active theme, hot apply, rotation, state dir |
| `src/thermalright_lcd_control/themes/metrics.py` | metric ids (`CATALOG`), history, extras |
| `src/thermalright_lcd_control/themes/builtin/designs/*.json` | built-in designs |
| `src/thermalright_lcd_control/themes/builtin/packs/*.json` | built-in packs |
| `src/thermalright_lcd_control/api/server.py` | HTTP API (docstring lists every route) |
| `src/thermalright_lcd_control/settings.py` | every path/name/port: config key + env var + default |
| `src/thermalright_lcd_control/data/` | config templates, udev rule (shipped in the wheel) |
| `web/` | web UI source; build output goes to `src/thermalright_lcd_control/web/` |
| `deploy/install.sh` | generic installer (asks, or flags) |
| `deploy/nginx/install-nginx.sh` | reverse proxy: reads open, writes need login |
| `deploy/portal/node-card.html` | embeddable read-only status card |

## Install

```bash
sudo deploy/install.sh                       # interactive: src, conda/venv, config, state, user, unit, udev
sudo deploy/install.sh --yes --start         # defaults (/opt/thermalright-lcd, /etc/thermalright-lcd, /var/lib/thermalright-lcd)
deploy/install.sh --user --yes --start       # everything under $HOME, user systemd unit
```

Useful flags: `--src DIR --ref REF` (checkout to build from), `--conda DIR` (interpreter
from a conda env), `--venv DIR`, `--config-dir DIR`, `--state-dir DIR`,
`--service-user U`, `--unit-name N`, `--requires-mounts PATH`, `--no-udev`,
`--rebuild-web`, `--device VID:PID` (skip USB detection), `--set KEY=VALUE` (config
override, repeatable), `--dry-run`. Re-running is safe.

Check: `systemctl status <unit>`; the journal logs `lcd frames_sent=N` every 60 s;
`curl -H "X-Display-Token: $(cat <token file>)" http://127.0.0.1:7431/api/status`.

## Configure

`<config-dir>/config_<w><h>.yaml` holds defaults; users' changes live in the state
dir. Override at install time with `--set`, e.g.

```bash
--set service.identity.node_name=desk-1 --set service.api.port=7432 \
--set 'service.extras.tokens.url=http://127.0.0.1:8000/metrics' \
--set 'service.extras.services={"db": "tcp://127.0.0.1:5432"}' \
--set telemetry.enabled=false
```

or at run time with env vars (`THERMALRIGHT_STATE_DIR`, `THERMALRIGHT_API_PORT`,
`THERMALRIGHT_NODE_NAME`, `OTEL_EXPORTER_OTLP_ENDPOINT`, … — see `settings.py`).

## Build

```bash
uv sync --frozen --no-dev --extra otel --extra video     # exactly uv.lock
cd web && pnpm install --frozen-lockfile && pnpm build  # only when web/ changed; commit the built bundle
uv build --wheel                                         # reproducible (hatchling pinned)
```

## Test without hardware

```bash
uv run thermalright-lcd-control-dev --port 7499 --token devtoken --frames-dir /tmp/tlcd-frames
# UI: http://127.0.0.1:7499/ (key button -> devtoken); last panel frame: /tmp/tlcd-frames/frame.png
T='X-Display-Token: devtoken'; B=http://127.0.0.1:7499
curl -s -H "$T" $B/api/status
curl -s -H "$T" -X POST $B/api/apply -d '{"kind":"design","design":"core-gauge","pack":"slate"}'
curl -s -H "$T" -X POST $B/api/preview.png -d '{"selection":{"kind":"design","design":"ai-node","pack":"midnight"}}' -o /tmp/p.png
uv run thermalright-lcd-control-probe --png /tmp/live.png --design core-grid    # real sensors, no panel
```

`status.apply_to_first_frame_s` shows the apply latency (expect well under 1 s).
Web UI dev server: `cd web && DISPLAY_TOKEN=devtoken pnpm dev` (proxies to :7499).

## Add a design

1. Copy a file in `themes/builtin/designs/`, change `id` (lowercase-hyphen), `name`,
   `description`, `order`. Coordinates are on `base` (320x240) and scale to other panels;
   add `layouts["480x480"]` only for a hand-tuned layout.
2. Widgets: `text` (templates `{cpu.temp:.0f}`, `{sys.power@peak:.0f}`), `number`, `arc`,
   `ring`, `bar`, `sparkline`, `coregrid`, `clock`, `dots`, `rect`, `image` — keys in
   the `engine.py` docstring. Metric ids: `themes/metrics.py` `CATALOG`.
3. Rules the built-ins follow: CPU package temperature is shown and is the largest
   reading (then GPU temperature, then watts; watts never larger than a temperature);
   temperatures use `"color": "heat"` with `heat: [lo, hi]` and `"flash_at": 85` on CPU
   temperature; GPU widgets carry `"requires": "gpu"` (and `"!gpu"` fallbacks); a design
   that only makes sense with a GPU or RAPL declares `"requires"` / `"requires_any"`.
   Leave room for a 32 px corner mark (`mark_corner`).
4. Preview every pack and both GPU/no-GPU cases through `/api/preview.png`, then
   `/api/apply` on the dev server and look at `frame.png`.

## Add a theme pack

One JSON in `themes/builtin/packs/` (schema in `themes/packs.py`): `id`, `name`,
`ground` (dark|light), 11 colours (`ink panel line text muted accent1 accent2 accent3
ok warn hot`, `#rrggbb`), optional `fonts` (display/bold/body/mono paths relative to the
pack file; ship the font licence), optional `mark` images, `default_mark`. Users can
also save packs at runtime (`PUT /api/packs/<id>`) into the state dir.

## Digital segment displays

`--device 0416:8001` gives a digital-mode service, which themes the external
controller by writing its config (`digital/engine.py`, `digital/runtime.py`).
Presets are JSON in `digital/builtin/presets/`. Each one sets `layouts.<small|big>`
with a `display_mode` and `colors {default, groups}`, plus `ranges`,
`cycle_duration` and `requires`. LED groups are listed in `digital/layout.py`.

Try it without hardware:

```bash
thermalright-lcd-control-dev --kind digital --digital-defaults <controller config.json>
curl -H "$T" -X POST $B/api/apply -d '{"preset":"heat"}'
```

To watch the real effect, point the controller at
`<state>/digital/config.json`.

## Add a widget type

1. `engine.py`: add `def w_<type>(self, d, wd, vals, overlay)`; use `self.X/Y/L` for
   scaling, `self.color(...)`, `self.font(role, size)`; document keys in the docstring.
2. `runtime.py`: add the type to `WIDGET_TYPES` (validation).
3. Web editor: `web/src/views/Editor.tsx` — add it to the "Add" presets, the per-type
   field list and the drag geometry; rebuild the bundle.
4. Use it in a design and test as above.

## Add an API route

`api/server.py` `DisplayApi.handle`: every `/api/*` route is token-checked already;
validate input, raise `ApiError(code, msg)` or `ValueError`, write only through the
runtime (state dir). Document the route in the module docstring; add the client call in
`web/src/api.ts`.

## Reverse proxy

```bash
sudo deploy/nginx/install-nginx.sh --base-path /display/ --token-file <token file> \
     --auth htpasswd --htpasswd /etc/nginx/thermalright.htpasswd --create-user alice --reload
# or --auth auth_request --auth-url http://127.0.0.1:<port>/check  (your auth service: 2xx/401/403)
```

Include `<out-dir>/thermalright-display.conf` in a `server {}` and the zone file at
`http {}` level. Reads stay open; writes are auth + rate limited + HTTPS-only.

## Ship a change

```bash
git switch -c feature/<name>            # from the branch you deploy
# edit, then: uv sync --frozen …; run the dev server; preview/apply; pnpm build if web/ changed
git commit -am "<what and why>"
git push origin feature/<name>          # review/merge into the deploy branch
sudo deploy/install.sh --yes --src <node checkout> --ref <merged commit> --start   # on each node
```

Pin deploys to a commit, not a moving branch. After deploying: frames_sent rising,
`apply_to_first_frame_s` < 1, the process runs as the service user (`ps -o user= -p
$(systemctl show -p MainPID --value <unit>)`).

## Troubleshooting

- `PermissionError` importing the package: runtime files must be world-readable
  (`chmod -R u=rwX,go=rX <src> <venv>`).
- No panel access: udev rule missing/not triggered (`--print-udev`), or wrong group.
- CPU watts `—`: RAPL `energy_uj` is root-only; the system unit's `ExecStartPre=+`
  grant fixes it (`/api/metrics` → `capabilities.rapl_reason`).
- Write returns 401 behind nginx: sign in at `<base>/login` (the UI offers it).
