#!/usr/bin/env bash
# deploy/nginx/install-nginx.sh — put the display UI/API behind any nginx.
#
# Model: reads are open, writes need a login.
#   GET/HEAD (status, metrics, frame PNG, UI) and POST api/preview.png (renders a
#   draft, saves nothing) pass straight through. Every other method is rewritten to
#   an internal location that requires authentication, is rate limited and (by
#   default) HTTPS-only. <base>/login is the sign-in URL the web UI opens.
#   nginx adds the service token server-side, so browsers never hold it.
#
# Two auth options:
#   --auth htpasswd      nginx auth_basic against an htpasswd file (simple; default).
#                        --create-user NAME adds/updates NAME (password prompted, apr1).
#   --auth auth_request  ("forward") nginx auth_request to any forward-auth endpoint that
#                        answers 2xx (allowed), 401 (no session) or 403 (not allowed):
#                        oauth2-proxy, Authelia, Authentik, or your own. Set --auth-url,
#                        e.g. http://127.0.0.1:4180/oauth2/auth?allowed_groups=lcd-operators.
#                        --signin-url (e.g. /oauth2/start) makes <base>/login redirect a 401
#                        there (?rd=<base>/login); writes keep plain 401/403. Any OIDC
#                        provider works behind oauth2-proxy (Keycloak, Google, GitHub,
#                        Nextcloud with its OIDC app, ...).
#   --auth none          no auth (only for a trusted, loopback-only proxy).
#
# Output (include the first inside a server {} block, the second at http {} level):
#   <out-dir>/thermalright-display.conf        locations
#   <http-conf>                                limit_req zone (default /etc/nginx/conf.d/thermalright-display-zone.conf)
#   <out-dir>/thermalright-display-login.html  page served after a successful sign-in
#
#   sudo deploy/nginx/install-nginx.sh --base-path /display/ --token-file /etc/thermalright-lcd/api.token \
#        --auth htpasswd --htpasswd /etc/nginx/thermalright.htpasswd --create-user alice --reload
#   sudo deploy/nginx/install-nginx.sh --auth auth_request --auth-url http://127.0.0.1:9180/check ...
#
# Options: --base-path P (default /display/) --upstream URL (default http://127.0.0.1:7431)
#   --token-file F (required) --out-dir D (default /etc/nginx/snippets) --http-conf F
#   --realm TEXT --rate N/m (default 20r/m) --signin-url URL --allow-http-writes --reload --dry-run
set -euo pipefail

BASE="/display/"; UP="http://127.0.0.1:7431"; TOKEN_FILE=""; AUTH="htpasswd"; HTPASSWD="/etc/nginx/thermalright-display.htpasswd"
AUTH_URL=""; SIGNIN_URL=""; CREATE_USER=""; OUT="/etc/nginx/snippets"; HTTP_CONF="/etc/nginx/conf.d/thermalright-display-zone.conf"
REALM="Display editor"; RATE="20r/m"; HTTPS_ONLY=1; RELOAD=0; DRY=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --base-path) BASE="$2"; shift ;; --upstream) UP="$2"; shift ;; --token-file) TOKEN_FILE="$2"; shift ;;
    --auth) AUTH="$2"; shift ;; --htpasswd) HTPASSWD="$2"; shift ;; --auth-url) AUTH_URL="$2"; shift ;; --signin-url) SIGNIN_URL="$2"; shift ;;
    --create-user) CREATE_USER="$2"; shift ;; --out-dir) OUT="$2"; shift ;; --http-conf) HTTP_CONF="$2"; shift ;;
    --realm) REALM="$2"; shift ;; --rate) RATE="$2"; shift ;; --allow-http-writes) HTTPS_ONLY=0 ;;
    --reload) RELOAD=1 ;; --dry-run) DRY=1 ;;
    -h|--help) sed -n '2,36p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done
[[ "${BASE}" =~ ^/[A-Za-z0-9/_.@-]*/$ ]] || { echo "--base-path must start and end with / and use [A-Za-z0-9/_.@-]" >&2; exit 2; }
[[ -r "${TOKEN_FILE}" ]] || { echo "--token-file is required and must be readable" >&2; exit 2; }
token="$(tr -d '[:space:]' <"${TOKEN_FILE}")"
[[ "${token}" =~ ^[A-Za-z0-9._-]{8,128}$ ]] || { echo "token has an unexpected format" >&2; exit 2; }
case "${AUTH}" in htpasswd|auth_request|none) ;; *) echo "--auth htpasswd|auth_request|none" >&2; exit 2 ;; esac
[[ "${AUTH}" != auth_request || -n "${AUTH_URL}" ]] || { echo "--auth auth_request needs --auth-url" >&2; exit 2; }

slug="$(printf '%s' "${BASE}" | tr -c 'A-Za-z0-9' '_' | sed 's/^_*//; s/_*$//')"; slug="${slug:-root}"
WRITE="/_tlcd_write_${slug}${BASE}"
ZONE="tlcd_${slug}"
LOGIN_HTML="${OUT}/thermalright-display-login.html"

auth_block() {  # $1 = login|write
  case "${AUTH}" in
    htpasswd) printf '    auth_basic "%s";\n    auth_basic_user_file %s;\n' "${REALM}" "${HTPASSWD}" ;;
    auth_request) printf '    auth_request /_tlcd_auth_%s;\n' "${slug}"
                  [[ "${1:-write}" == login && -n "${SIGNIN_URL}" ]] && printf '    error_page 401 = @tlcd_signin_%s;\n' "${slug}"
                  return 0 ;;
    none) printf '    # auth: none\n' ;;
  esac
}
https_block() {
  [[ ${HTTPS_ONLY} == 1 ]] && printf '    if ($scheme != "https") { return 403; }  # never send credentials over plain HTTP\n'
  return 0
}
proxy_block() {  # rewrite-from upstream
  cat <<EOF
    rewrite ^$1(.*)\$ /\$1 break;
    proxy_pass ${UP};
    proxy_read_timeout 60s;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-Proto \$scheme;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Display-Token "${token}";
EOF
}

render() {
  cat <<EOF
# Generated by thermalright-lcd-control deploy/nginx/install-nginx.sh — re-run it to change.
# Reads open, writes need sign-in (${AUTH}). Include inside a server {} block.

location = ${BASE%/} {
    return 302 ${BASE};
}

location = ${BASE}login {
$(https_block)
    limit_req zone=${ZONE} burst=5 nodelay;
$(auth_block login)
    default_type text/html;
    alias ${LOGIN_HTML};
}

location = ${BASE}api/preview.png {
    # read-only render of a draft theme: as open as the other reads
    client_max_body_size 1m;
$(proxy_block "${BASE}")
}

location ${BASE} {
    if (\$request_method !~ ^(GET|HEAD)\$) {
        rewrite ^${BASE}(.*)\$ ${WRITE}\$1 last;
    }
$(proxy_block "${BASE}")
}

location ${WRITE} {
    internal;
$(https_block)
    limit_req zone=${ZONE} burst=10 nodelay;
$(auth_block write)
    client_max_body_size 64m;
$(proxy_block "${WRITE}")
}
EOF
  if [[ "${AUTH}" == auth_request ]]; then
    cat <<EOF

location = /_tlcd_auth_${slug} {
    internal;
    proxy_pass ${AUTH_URL};
    proxy_pass_request_body off;
    proxy_set_header Content-Length "";
    proxy_set_header Authorization \$http_authorization;
    proxy_set_header X-Original-URI \$request_uri;
    proxy_set_header X-Original-Method \$request_method;
}
EOF
    if [[ -n "${SIGNIN_URL}" ]]; then
      cat <<EOF

location @tlcd_signin_${slug} {
    return 302 ${SIGNIN_URL}?rd=\$request_uri;
}
EOF
    fi
  fi
}

if [[ ${DRY} == 1 ]]; then render; exit 0; fi
mkdir -p "${OUT}" "$(dirname "${HTTP_CONF}")"
printf 'limit_req_zone $binary_remote_addr zone=%s:1m rate=%s;\n' "${ZONE}" "${RATE}" >"${HTTP_CONF}"
printf '%s\n' '<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0; url=./"><title>Signed in</title><a href="./">Back to the display</a>' >"${LOGIN_HTML}"
(umask 027; render >"${OUT}/thermalright-display.conf")
chmod 0640 "${OUT}/thermalright-display.conf"
getent group www-data >/dev/null && chgrp www-data "${OUT}/thermalright-display.conf" || true
if [[ "${AUTH}" == htpasswd && -n "${CREATE_USER}" ]]; then
  read -r -s -p "Password for ${CREATE_USER}: " pw </dev/tty; echo
  [[ ${#pw} -ge 10 ]] || { echo "use at least 10 characters" >&2; exit 1; }
  touch "${HTPASSWD}"; grep -v "^${CREATE_USER}:" "${HTPASSWD}" >"${HTPASSWD}.new" || true
  printf '%s:%s\n' "${CREATE_USER}" "$(printf '%s' "${pw}" | openssl passwd -apr1 -stdin)" >>"${HTPASSWD}.new"
  mv "${HTPASSWD}.new" "${HTPASSWD}"; chmod 0640 "${HTPASSWD}"
  getent group www-data >/dev/null && chgrp www-data "${HTPASSWD}" || true
fi
echo "wrote ${OUT}/thermalright-display.conf (include it in your server {} block) and ${HTTP_CONF}"
if [[ ${RELOAD} == 1 ]]; then nginx -t && systemctl reload nginx; fi
