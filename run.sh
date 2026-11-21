#!/usr/bin/env bash
# Start KubeTrail on macOS: ./run.sh
#
# Finds Python 3.11 or newer, makes .venv, installs the app, runs the doctor,
# starts the server on 127.0.0.1, and opens the browser.
#
#   PORT=8001 ./run.sh        use a different port
#   KT_NO_BROWSER=1 ./run.sh  do not open the browser
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8000}"
URL="http://127.0.0.1:${PORT}"
VENV=".venv"
STAMP="${VENV}/.kubetrail-installed"

say() { printf '==> %s\n' "$*"; }
die() { printf 'run.sh: %s\n' "$*" >&2; exit 1; }

is_new_enough() {
  "$1" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null
}

find_python() {
  local name dir
  for name in python3.13 python3.12 python3.11 python3; do
    for dir in "" /opt/homebrew/bin/ /usr/local/bin/; do
      if command -v "${dir}${name}" >/dev/null 2>&1 && is_new_enough "${dir}${name}"; then
        command -v "${dir}${name}"
        return 0
      fi
    done
  done
  return 1
}

if [[ "$(uname -s)" != "Darwin" ]]; then
  say "KubeTrail supports macOS only. This computer runs $(uname -s). See ROADMAP.md."
fi

if [[ ! -x "${VENV}/bin/python" ]] || ! is_new_enough "${VENV}/bin/python"; then
  PYTHON="$(find_python)" || die "Python 3.11 or newer is not installed. Run: brew install python@3.12"
  say "Making ${VENV} with $("${PYTHON}" --version)"
  rm -rf "${VENV}"
  "${PYTHON}" -m venv "${VENV}"
fi

WANT="$("${VENV}/bin/python" -c 'import hashlib; print(hashlib.sha256(open("pyproject.toml", "rb").read()).hexdigest())')"
if [[ ! -f "${STAMP}" ]] || [[ "$(cat "${STAMP}")" != "${WANT}" ]]; then
  say "Installing the app in ${VENV}"
  "${VENV}/bin/python" -m pip install --quiet --disable-pip-version-check -e ".[dev]"
  printf '%s\n' "${WANT}" > "${STAMP}"
fi

if ! "${VENV}/bin/python" scripts/doctor.py; then
  die "correct each FAIL line above, then run ./run.sh again."
fi
echo

if ! "${VENV}/bin/python" -c "import socket,sys; s=socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); s.bind(('127.0.0.1', ${PORT}))" 2>/dev/null; then
  die "port ${PORT} is in use. Stop the other server, or run: PORT=8001 ./run.sh"
fi

if [[ -z "${KT_NO_BROWSER:-}" ]] && command -v open >/dev/null 2>&1; then
  (
    for _ in $(seq 50); do
      if curl -fsS -o /dev/null "${URL}/api/content" 2>/dev/null; then open "${URL}"; exit 0; fi
      sleep 0.2
    done
  ) &
fi

say "KubeTrail runs at ${URL}. Push Ctrl+C to stop."
exec "${VENV}/bin/uvicorn" backend.main:app --host 127.0.0.1 --port "${PORT}"
