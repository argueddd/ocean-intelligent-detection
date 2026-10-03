#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -n "${PYTHON_BOOTSTRAP:-}" ]; then
  HARNESS_BOOTSTRAP_PYTHON="$PYTHON_BOOTSTRAP"
elif [ -x "$PROJECT_DIR/.venv/bin/python" ] && [ -f "$PROJECT_DIR/.venv/pyvenv.cfg" ]; then
  HARNESS_BOOTSTRAP_PYTHON="$PROJECT_DIR/.venv/bin/python"
else
  HARNESS_BOOTSTRAP_PYTHON="$(command -v python3 || true)"
fi
if [ -z "$HARNESS_BOOTSTRAP_PYTHON" ] && [ -x /opt/homebrew/bin/python3 ]; then
  HARNESS_BOOTSTRAP_PYTHON=/opt/homebrew/bin/python3
fi
if [ -z "$HARNESS_BOOTSTRAP_PYTHON" ]; then echo '需要 Python >=3.11，请安装 Python 或设置 PYTHON_BOOTSTRAP。' >&2; exit 1; fi
if [ "${1:-}" = '--ensure' ]; then set --; else set -- --force; fi
exec env -u PYTHONHOME -u PYTHONPATH "$HARNESS_BOOTSTRAP_PYTHON" -I \
  "$PROJECT_DIR/backend/harness/bootstrap.py" "$@"
