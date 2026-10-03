#!/usr/bin/env bash
# install-service.sh — install the Thermalright LCD service from a wheel.
#
# Primary path: a release wheel (local file or URL). Secondary: build the wheel
# from this source tree (needs the repo). Nothing outside the chosen prefix,
# config dir and state dir is touched, except the optional systemd unit and udev
# rule when run as root.
#
#   System (root):  sudo scripts/install-service.sh --wheel thermalright_lcd_control-*.whl
#   User ($HOME):   scripts/install-service.sh --user --wheel <url-or-file>
#
# Options (each also settable via the env var in brackets):
#   --prefix DIR      [THERMALRIGHT_PREFIX]      venv lives in DIR/venv
#                     default /opt/thermalright-lcd, --user: ~/.local/share/thermalright-lcd
#   --config-dir DIR  [THERMALRIGHT_CONFIG_DIR]  default /etc/thermalright-lcd, --user: ~/.config/thermalright-lcd
#   --state-dir DIR   [THERMALRIGHT_STATE_DIR]   default /var/lib/thermalright-lcd, --user: ~/.local/state/thermalright-lcd
#   --wheel FILE|URL  install this wheel (default: build one from this source tree)
#   --python VER      interpreter for uv (default 3.13; uv may download it)
#   --extras LIST     comma list of extras (default otel,video)
#   --device VID:PID  skip USB detection; --panel WxH for 87ad:70db
#   --service-user U  system installs: run as U (created if missing; default thermalright)
#   --no-systemd      do not install a unit
#   --user            install for the current user (user systemd unit, no root)
set -euo pipefail

USER_MODE=0; PREFIX="${THERMALRIGHT_PREFIX:-}"; CONFIG_DIR="${THERMALRIGHT_CONFIG_DIR:-}"
STATE_DIR="${THERMALRIGHT_STATE_DIR:-}"; WHEEL=""; PY="3.13"; EXTRAS="otel,video"
DEVICE="auto"; PANEL="480x480"; SVC_USER="thermalright"; SYSTEMD=1
while [[ $# -gt 0 ]]; do
  case "$1" in
    --user) USER_MODE=1 ;;
    --prefix) PREFIX="$2"; shift ;;
    --config-dir) CONFIG_DIR="$2"; shift ;;
    --state-dir) STATE_DIR="$2"; shift ;;
    --wheel) WHEEL="$2"; shift ;;
    --python) PY="$2"; shift ;;
    --extras) EXTRAS="$2"; shift ;;
    --device) DEVICE="$2"; shift ;;
    --panel) PANEL="$2"; shift ;;
    --service-user) SVC_USER="$2"; shift ;;
    --no-systemd) SYSTEMD=0 ;;
    -h|--help) sed -n '2,26p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

if [[ ${USER_MODE} == 1 ]]; then
  PREFIX="${PREFIX:-${XDG_DATA_HOME:-$HOME/.local/share}/thermalright-lcd}"
  CONFIG_DIR="${CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/thermalright-lcd}"
  STATE_DIR="${STATE_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/thermalright-lcd}"
else
  [[ $(id -u) -eq 0 ]] || { echo "system install needs root (or use --user)" >&2; exit 1; }
  PREFIX="${PREFIX:-/opt/thermalright-lcd}"; CONFIG_DIR="${CONFIG_DIR:-/etc/thermalright-lcd}"
  STATE_DIR="${STATE_DIR:-/var/lib/thermalright-lcd}"
fi
command -v uv >/dev/null || { echo "uv is required (https://docs.astral.sh/uv/)" >&2; exit 1; }

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "${tmp}"' EXIT
if [[ -z "${WHEEL}" ]]; then
  [[ -f "${here}/pyproject.toml" ]] || { echo "no --wheel and no source tree next to this script" >&2; exit 1; }
  uv build -q --wheel -o "${tmp}" "${here}"
  WHEEL="$(ls "${tmp}"/*.whl)"
elif [[ "${WHEEL}" == http* ]]; then
  curl -fsSL -o "${tmp}/$(basename "${WHEEL}")" "${WHEEL}"
  WHEEL="${tmp}/$(basename "${WHEEL}")"
fi

mkdir -p "${PREFIX}" "${CONFIG_DIR}" "${STATE_DIR}"
uv venv -q --allow-existing --python "${PY}" "${PREFIX}/venv"
uv pip install -q --python "${PREFIX}/venv/bin/python" "${WHEEL}[${EXTRAS}]"
"${PREFIX}/venv/bin/thermalright-lcd-control-init" --config-dir "${CONFIG_DIR}" --state-dir "${STATE_DIR}" \
  --device "${DEVICE}" --panel "${PANEL}"

if [[ ${SYSTEMD} == 1 ]]; then
  init="${PREFIX}/venv/bin/thermalright-lcd-control-init"
  if [[ ${USER_MODE} == 1 ]]; then
    mkdir -p "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
    "${init}" --print-unit user --prefix "${PREFIX}" --config-dir "${CONFIG_DIR}" --state-dir "${STATE_DIR}" \
      >"${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/thermalright-lcd-control.service"
    systemctl --user daemon-reload
    echo "user unit installed: systemctl --user enable --now thermalright-lcd-control"
    echo "panel access for your login comes from the udev rule (uaccess); ask root once:"
    echo "  ${init} --print-udev | sudo tee /etc/udev/rules.d/60-thermalright-lcd.rules && sudo udevadm control --reload-rules && sudo udevadm trigger"
  else
    getent group "${SVC_USER}" >/dev/null || groupadd --system "${SVC_USER}"
    id -u "${SVC_USER}" >/dev/null 2>&1 || useradd --system --gid "${SVC_USER}" --no-create-home \
      --home-dir /nonexistent --shell /usr/sbin/nologin "${SVC_USER}"
    chown -R "${SVC_USER}:${SVC_USER}" "${STATE_DIR}"; chmod 0750 "${STATE_DIR}"
    tok="$(sed -n 's/^ *token_file: *//p' "${CONFIG_DIR}"/config_*.yaml | head -n1)"
    [[ -n "${tok}" && -f "${tok}" ]] && { chgrp "${SVC_USER}" "${tok}"; chmod 0640 "${tok}"; }
    "${init}" --print-udev --group "${SVC_USER}" >/etc/udev/rules.d/60-thermalright-lcd.rules
    udevadm control --reload-rules && udevadm trigger --subsystem-match=usb --subsystem-match=hidraw || true
    "${init}" --print-unit system --prefix "${PREFIX}" --config-dir "${CONFIG_DIR}" --state-dir "${STATE_DIR}" \
      --user-name "${SVC_USER}" >/etc/systemd/system/thermalright-lcd-control.service
    systemctl daemon-reload
    echo "system unit installed: systemctl enable --now thermalright-lcd-control"
  fi
fi
echo "installed: venv ${PREFIX}/venv · config ${CONFIG_DIR} · state ${STATE_DIR}"
echo "web UI: http://127.0.0.1:7431/ (token in the file named by service.api.token_file)"
