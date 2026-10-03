#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HARNESS_NODE="${NODE_BIN:-$(command -v node || true)}"
if ! "$HARNESS_NODE" -e 'const [a,b]=process.versions.node.split(".").map(Number);process.exit(a>22||(a===22&&b>=19)?0:1)' 2>/dev/null; then
  if [ -x /opt/homebrew/bin/node ]; then HARNESS_NODE=/opt/homebrew/bin/node; fi
fi
if [ -z "$HARNESS_NODE" ] || [ ! -x "$HARNESS_NODE" ]; then
  echo 'Harness 需要 Node >=22.19，请安装 Node 或设置 NODE_BIN。' >&2
  exit 1
fi
"$HARNESS_NODE" -e 'const [a,b]=process.versions.node.split(".").map(Number);if(!(a>22||(a===22&&b>=19)))throw new Error("Harness 需要 Node >=22.19")'
export PATH="$(dirname "$HARNESS_NODE"):$PATH"
if [ ! -d "$PROJECT_DIR/backend/node_modules/@deepseek-ai/dsh-sdk-client" ]; then
  (cd "$PROJECT_DIR/backend" && npm ci --no-fund --no-audit)
fi
case "${1:-}" in
  --skills|--help|-h|'') ;;
  *) "$PROJECT_DIR/setup-python.sh" --ensure >&2 ;;
esac
cd "$PROJECT_DIR"
exec "$HARNESS_NODE" "$PROJECT_DIR/backend/harness/run.mjs" "$@"
