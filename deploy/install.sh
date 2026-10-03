#!/usr/bin/env bash
# deploy/install.sh — install the Thermalright LCD service from a source checkout.
#
# Asks where everything goes (or takes flags; --yes accepts the defaults), then:
#   source  clone/fetch the repo at --ref into --src (or use the checkout this script is in)
#   python  a conda env at --conda (optional) or a uv-managed CPython 3.13
#   venv    uv sync --frozen (exactly uv.lock) into --venv, extras otel+video
#   web     prebuilt bundle by default; --rebuild-web runs pnpm in <src>/web
#   config  thermalright-lcd-control-init -> --config-dir (+ --set overrides), token
#   system  service user, state dir, udev rule, systemd unit (each optional)
# Re-running is safe: unchanged steps are skipped or rewritten identically.
#
#   sudo deploy/install.sh                     # interactive, system service
#   sudo deploy/install.sh --yes --start       # defaults, then enable + start
#   deploy/install.sh --user --yes --start     # everything under $HOME, user unit
#
# Locations (flag / env / default; --user defaults in brackets)
#   --src DIR         THERMALRIGHT_SRC     this checkout, else /opt/thermalright-lcd/src [~/.local/share/thermalright-lcd/src]
#   --conda DIR       THERMALRIGHT_CONDA   none (uv-managed python)
#   --venv DIR        THERMALRIGHT_VENV    /opt/thermalright-lcd/venv [~/.local/share/thermalright-lcd/venv]
#   --config-dir DIR  THERMALRIGHT_CONFIG_DIR  /etc/thermalright-lcd [~/.config/thermalright-lcd]
#   --state-dir DIR   THERMALRIGHT_STATE_DIR   /var/lib/thermalright-lcd [~/.local/state/thermalright-lcd]
# Source
#   --repo URL        default https://github.com/manishknema/thermalright-lcd-control-aio.git
#   --ref REF         branch, tag or commit to check out (default: keep the checkout as is)
# Build
#   --extras LIST     default otel,video        --rebuild-web   rebuild the web UI with pnpm
# Service
#   --service-user U  default thermalright (system installs; created if missing)
#   --unit-name N     default thermalright-lcd-control
#   --unit-description TEXT, --after UNIT (repeat), --requires-mounts PATH (repeat), --working-dir DIR
#   --no-unit         skip the systemd unit      --no-udev   skip the udev rule
#   --udev-rule PATH  default /etc/udev/rules.d/60-thermalright-lcd.rules
#   --start           enable and (re)start the unit at the end
# Config
#   --device VID:PID  skip USB detection         --panel WxH (87ad:70db only)
#   --set KEY=VALUE   config override, repeatable (e.g. service.identity.node_name=desk-1)
#   --keep-config     keep an existing config_<w><h>.yaml (default: re-render from the template)
# Other
#   --user            per-user install (no root)  --yes   no questions   --dry-run   print only
set -euo pipefail

REPO="https://github.com/manishknema/thermalright-lcd-control-aio.git"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USER_MODE=0; YES=0; DRY=0; START=0; UNIT=1; UDEV=1; WEB=0; KEEP=0
SRC="${THERMALRIGHT_SRC:-}"; CONDA="${THERMALRIGHT_CONDA:-}"; VENV="${THERMALRIGHT_VENV:-}"
CONFIG_DIR="${THERMALRIGHT_CONFIG_DIR:-}"; STATE_DIR="${THERMALRIGHT_STATE_DIR:-}"
REF=""; EXTRAS="otel,video"; SVC_USER="thermalright"; UNIT_NAME="thermalright-lcd-control"
UNIT_DESC=""; WORKDIR=""; UDEV_RULE="/etc/udev/rules.d/60-thermalright-lcd.rules"
DEVICE="auto"; PANEL="480x480"; AFTER=(); MOUNTS=(); SETS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --user) USER_MODE=1 ;; --yes) YES=1 ;; --dry-run) DRY=1 ;; --start) START=1 ;;
    --no-unit) UNIT=0 ;; --no-udev) UDEV=0 ;; --rebuild-web) WEB=1 ;; --keep-config) KEEP=1 ;;
    --src) SRC="$2"; shift ;; --conda) CONDA="$2"; shift ;; --venv) VENV="$2"; shift ;;
    --config-dir) CONFIG_DIR="$2"; shift ;; --state-dir) STATE_DIR="$2"; shift ;;
    --repo) REPO="$2"; shift ;; --ref) REF="$2"; shift ;; --extras) EXTRAS="$2"; shift ;;
    --service-user) SVC_USER="$2"; shift ;; --unit-name) UNIT_NAME="$2"; shift ;;
    --unit-description) UNIT_DESC="$2"; shift ;; --after) AFTER+=("$2"); shift ;;
    --requires-mounts) MOUNTS+=("$2"); shift ;; --working-dir) WORKDIR="$2"; shift ;;
    --udev-rule) UDEV_RULE="$2"; shift ;; --device) DEVICE="$2"; shift ;; --panel) PANEL="$2"; shift ;;
    --set) SETS+=("$2"); shift ;;
    -h|--help) sed -n '2,46p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1 (--help)" >&2; exit 2 ;;
  esac
  shift
done

say() { printf '%s\n' "$*"; }
run() { if [[ ${DRY} == 1 ]]; then say "DRY-RUN: $*"; else "$@"; fi; }
ask() {  # var prompt default
  local __v="$1" p="$2" d="$3" r=""
  if [[ ${YES} == 0 && -t 0 ]]; then read -r -p "${p} [${d}]: " r </dev/tty || true; fi
  printf -v "${__v}" '%s' "${r:-$d}"
}
yesno() {  # var prompt default(1|0)
  local __v="$1" p="$2" d="$3" r=""
  if [[ ${YES} == 0 && -t 0 ]]; then read -r -p "${p} [$([[ $d == 1 ]] && echo Y/n || echo y/N)]: " r </dev/tty || true; fi
  case "${r}" in y|Y|yes) printf -v "${__v}" 1 ;; n|N|no) printf -v "${__v}" 0 ;; *) printf -v "${__v}" '%s' "$d" ;; esac
}

if [[ ${USER_MODE} == 1 ]]; then
  base="${XDG_DATA_HOME:-$HOME/.local/share}/thermalright-lcd"
  d_cfg="${XDG_CONFIG_HOME:-$HOME/.config}/thermalright-lcd"; d_state="${XDG_STATE_HOME:-$HOME/.local/state}/thermalright-lcd"
else
  [[ $(id -u) -eq 0 || ${DRY} == 1 ]] || { echo "a system install needs root (or use --user)" >&2; exit 1; }
  base="/opt/thermalright-lcd"; d_cfg="/etc/thermalright-lcd"; d_state="/var/lib/thermalright-lcd"
fi
d_src="${base}/src"; [[ -f "${HERE}/pyproject.toml" && -d "${HERE}/.git" ]] && d_src="${HERE}"
ask SRC "Source checkout" "${SRC:-${d_src}}"
ask CONDA "Conda env for the interpreter (empty = uv-managed python)" "${CONDA:-}"
ask VENV "Virtualenv" "${VENV:-${base}/venv}"
ask CONFIG_DIR "Config dir (defaults + token)" "${CONFIG_DIR:-${d_cfg}}"
ask STATE_DIR "State dir (your themes, packs, uploads)" "${STATE_DIR:-${d_state}}"
if [[ ${USER_MODE} == 0 ]]; then
  ask SVC_USER "Service user" "${SVC_USER}"
  yesno UDEV "Install the udev rule (panel access for ${SVC_USER} and the desktop user)" "${UDEV}"
fi
yesno UNIT "Install a systemd unit" "${UNIT}"
yesno WEB "Rebuild the web UI with pnpm (the prebuilt bundle is in the checkout)" "${WEB}"
command -v uv >/dev/null || { echo "uv is required: https://docs.astral.sh/uv/" >&2; exit 1; }
command -v git >/dev/null || { echo "git is required" >&2; exit 1; }

# ── source ─────────────────────────────────────────────────────────────────
if [[ ! -d "${SRC}/.git" ]]; then
  run git clone -q "${REPO}" "${SRC}"
fi
if [[ -n "${REF}" ]]; then
  run git -C "${SRC}" fetch -q origin
  target="${REF}"; git -C "${SRC}" rev-parse -q --verify "origin/${REF}^{commit}" >/dev/null 2>&1 && target="origin/${REF}"
  run git -C "${SRC}" -c advice.detachedHead=false checkout -q --force "${target}"
fi
[[ ${DRY} == 1 ]] || say "source: ${SRC} @ $(git -C "${SRC}" rev-parse --short HEAD)"

# ── python + venv ──────────────────────────────────────────────────────────
PY="3.13"
if [[ -n "${CONDA}" ]]; then
  conda_bin="$(command -v conda || echo /opt/miniconda3/bin/conda)"
  if [[ ! -x "${CONDA}/bin/python" ]]; then
    run "${conda_bin}" create -y -q -p "${CONDA}" -c conda-forge --override-channels python=3.13
  fi
  PY="${CONDA}/bin/python"
fi
ex=(); IFS=',' read -r -a _e <<<"${EXTRAS}"; for e in "${_e[@]}"; do [[ -n "$e" ]] && ex+=(--extra "$e"); done
run env UV_PROJECT_ENVIRONMENT="${VENV}" UV_LINK_MODE=copy uv sync -q --project "${SRC}" --frozen --no-dev \
  --no-editable "${ex[@]}" --python "${PY}"
if [[ ${WEB} == 1 ]]; then
  command -v pnpm >/dev/null || { echo "--rebuild-web needs pnpm" >&2; exit 1; }
  run bash -c "cd '${SRC}/web' && pnpm install --frozen-lockfile && pnpm build"
  run env UV_PROJECT_ENVIRONMENT="${VENV}" UV_LINK_MODE=copy uv sync -q --project "${SRC}" --frozen --no-dev \
    --no-editable --reinstall-package thermalright-lcd-control "${ex[@]}" --python "${PY}"
fi
init="${VENV}/bin/thermalright-lcd-control-init"

# ── config ─────────────────────────────────────────────────────────────────
run mkdir -p "${CONFIG_DIR}" "${STATE_DIR}"
iargs=(--config-dir "${CONFIG_DIR}" --state-dir "${STATE_DIR}" --device "${DEVICE}" --panel "${PANEL}")
[[ ${KEEP} == 1 ]] || iargs+=(--force)
for s in "${SETS[@]}"; do iargs+=(--set "$s"); done
run "${init}" "${iargs[@]}"

# ── system integration ─────────────────────────────────────────────────────
uargs=(--venv "${VENV}" --config-dir "${CONFIG_DIR}" --state-dir "${STATE_DIR}")
[[ -n "${UNIT_DESC}" ]] && uargs+=(--unit-description "${UNIT_DESC}")
[[ -n "${WORKDIR}" ]] && uargs+=(--working-dir "${WORKDIR}")
for a in "${AFTER[@]}"; do uargs+=(--after "$a"); done
for m in "${MOUNTS[@]}"; do uargs+=(--requires-mounts "$m"); done
if [[ ${USER_MODE} == 1 ]]; then
  if [[ ${UNIT} == 1 ]]; then
    ud="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"; run mkdir -p "${ud}"
    if [[ ${DRY} == 0 ]]; then "${init}" --print-unit user "${uargs[@]}" >"${ud}/${UNIT_NAME}.service"; fi
    run systemctl --user daemon-reload
    [[ ${START} == 1 ]] && { run systemctl --user enable "${UNIT_NAME}"; run systemctl --user restart "${UNIT_NAME}"; }
  fi
  say "panel access for your desktop login comes from the udev rule (uaccess); install it once as root:"
  say "  ${init} --print-udev | sudo tee ${UDEV_RULE} && sudo udevadm control --reload-rules && sudo udevadm trigger"
else
  getent group "${SVC_USER}" >/dev/null || run groupadd --system "${SVC_USER}"
  id -u "${SVC_USER}" >/dev/null 2>&1 || run useradd --system --gid "${SVC_USER}" --no-create-home \
    --home-dir /nonexistent --shell /usr/sbin/nologin "${SVC_USER}"
  run chown "${SVC_USER}:${SVC_USER}" "${STATE_DIR}"; run chmod 0750 "${STATE_DIR}"
  # runtime: root-owned, world-readable, never group/world-writable
  for d in "${SRC}" "${VENV}" ${CONDA:+"${CONDA}"}; do
    if [[ "${d}" == "${HERE}" && "$(stat -c %U "${d}")" != root ]]; then
      say "note: ${d} is your own checkout; left as is (the service only needs to read it)"; continue
    fi
    run chown -R root:root "${d}"; run chmod -R u=rwX,go=rX "${d}"
  done
  tok="$(sed -n 's/^ *token_file: *//p' "${CONFIG_DIR}"/config_*.yaml 2>/dev/null | head -n1)"
  if [[ -n "${tok}" && -f "${tok}" ]]; then run chgrp "${SVC_USER}" "${tok}"; run chmod 0640 "${tok}"; fi
  if [[ ${UDEV} == 1 ]]; then
    if [[ ${DRY} == 0 ]]; then "${init}" --print-udev --group "${SVC_USER}" >"${UDEV_RULE}"; fi
    run udevadm control --reload-rules
    run udevadm trigger --action=change --subsystem-match=usb --subsystem-match=hidraw
  fi
  if [[ ${UNIT} == 1 ]]; then
    if [[ ${DRY} == 0 ]]; then
      "${init}" --print-unit system --user-name "${SVC_USER}" "${uargs[@]}" >"/etc/systemd/system/${UNIT_NAME}.service.new"
      if cmp -s "/etc/systemd/system/${UNIT_NAME}.service.new" "/etc/systemd/system/${UNIT_NAME}.service"; then
        rm -f "/etc/systemd/system/${UNIT_NAME}.service.new"
      else
        mv "/etc/systemd/system/${UNIT_NAME}.service.new" "/etc/systemd/system/${UNIT_NAME}.service"
      fi
    fi
    run systemctl daemon-reload
    [[ ${START} == 1 ]] && { run systemctl enable "${UNIT_NAME}"; run systemctl restart "${UNIT_NAME}"; }
  fi
fi
say "installed: src ${SRC} · venv ${VENV}${CONDA:+ (python from ${CONDA})} · config ${CONFIG_DIR} · state ${STATE_DIR}"
say "web UI: http://127.0.0.1:7431/ (token: the file named by service.api.token_file)"
