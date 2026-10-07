#!/usr/bin/env bash
# 启动适配层 + 前端 dev(5173)；--harness 使用本机独立 Harness(3089)。
# backend/.env 配置模型；日志 .run/，停止用 ./stop.sh。

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_DIR="$HERE/.run"
mkdir -p "$RUN_DIR"

MODE="${1:-}"
case "$MODE" in
  --harness)
    SERVER_NAME=harness-server
    WEB_NAME=harness-web
    API_URL=http://127.0.0.1:3089/api/health
    EXPECTED_PROFILE=harness
    ;;
  "")
    SERVER_NAME=server
    WEB_NAME=web
    API_URL=http://127.0.0.1:3088/api/health
    EXPECTED_PROFILE=rag-kb
    ;;
  *) echo "用法: ./start.sh [--harness]"; exit 1 ;;
esac
WEB_URL=http://127.0.0.1:5173
# 本机健康检查、前端代理和取消桥始终直连；外部模型保留现有代理设置。
export NO_PROXY="${NO_PROXY:+$NO_PROXY,}localhost,127.0.0.1,::1"
export no_proxy="${no_proxy:+$no_proxy,}localhost,127.0.0.1,::1"

NODE_BIN="${NODE_BIN:-$(command -v node)}"
if ! "$NODE_BIN" -e 'const [a,b]=process.versions.node.split(".").map(Number);process.exit(a>22||(a===22&&b>=19)?0:1)' 2>/dev/null; then
  if [ -x /opt/homebrew/bin/node ]; then NODE_BIN=/opt/homebrew/bin/node; fi
fi
if ! "$NODE_BIN" -e 'const [a,b]=process.versions.node.split(".").map(Number);process.exit(a>22||(a===22&&b>=19)?0:1)' 2>/dev/null; then
  echo "❌ 需要 Node >=22.19；可设置 NODE_BIN 或使用 Docker Compose"; exit 1
fi
export PATH="$(dirname "$NODE_BIN"):$PATH"

[ -f "$HERE/backend/.env" ] || { echo "❌ 缺少 backend/.env，请先执行: cp backend/.env.example backend/.env"; exit 1; }

if [ "$MODE" = --harness ]; then
  if ! "$NODE_BIN" - "$HERE/backend/.env" <<'NODE'
const file = process.argv[2]
try { process.loadEnvFile(file) } catch { process.exit(2) }
const invalid = (name) => {
  const value = String(process.env[name] || '').trim()
  return !value || /^(replace-with|your-)/i.test(value) || /your-workspace|你的/i.test(value)
}
const missing = ['LLM_BASE_URL', 'LLM_API_KEY', 'LLM_MODEL'].filter(invalid)
if (missing.length) {
  console.error(`❌ backend/.env 仍需填写: ${missing.join(', ')}`)
  process.exit(1)
}
NODE
  then
    exit 1
  fi
fi

# 首次运行准备：适配层依赖 + profile 插件链接（幂等）
if [ ! -d "$HERE/backend/node_modules/@deepseek-ai/dsh-sdk-client" ]; then
  echo "▶️  安装适配层依赖 (npm ci) ..."
  (cd "$HERE/backend" && npm ci --no-fund --no-audit) || exit 1
fi
if [ ! -d "$HERE/frontend/node_modules/vite" ]; then
  (cd "$HERE/frontend" && npm ci --no-fund --no-audit) || exit 1
fi
if [ "$MODE" = --harness ]; then
  "$HERE/setup-python.sh" --ensure || exit 1
fi

wait_ready() { # wait_ready <名称> <url> <pid> <超时秒>
  local name="$1" url="$2" pid="$3" timeout="${4:-60}" i=0
  while [ "$i" -lt "$timeout" ]; do
    curl -s -m 2 -o /dev/null "$url" && { echo "✅ $name 就绪 ($url)"; return 0; }
    [ -n "$pid" ] && ! kill -0 "$pid" 2>/dev/null && { echo "❌ $name 进程退出，日志: $RUN_DIR/$name.log"; return 1; }
    sleep 1; i=$((i + 1))
  done
  echo "⚠️  $name ${timeout}s 内未就绪，请看日志: $RUN_DIR/$name.log"; return 1
}

start_one() { # start_one <名称> <探测URL> <工作目录> <启动命令...>
  local name="$1" url="$2" dir="$3"; shift 3
  local pidfile="$RUN_DIR/$name.pid"
  if [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
    echo "⏭️  $name 已在运行 (pid $(cat "$pidfile"))，跳过"; return 0
  fi
  if curl -s -m 2 -o /dev/null "$url"; then
    echo "⏭️  $name 端口已被占用（可能是手动启动的进程），跳过启动"; rm -f "$pidfile"; return 0
  fi
  echo "▶️  启动 $name ..."
  (cd "$dir" || exit 1; nohup "$@" >"$RUN_DIR/$name.log" 2>&1 & echo $! >"$pidfile")
}

if [ "$MODE" = --harness ]; then
  start_one "$SERVER_NAME" "$API_URL" "$HERE/backend" env DSH_PROFILE=harness PORT=3089 DSH_HOME_DIR=.runtime/web-harness-home "$NODE_BIN" index.js
  start_one "$WEB_NAME" "$WEB_URL" "$HERE/frontend" env VITE_AGENT_MODE=harness VITE_RAG_SERVER_TARGET=http://127.0.0.1:3089 "$NODE_BIN" "$HERE/frontend/node_modules/vite/bin/vite.js" --host 127.0.0.1 --port 5173 --strictPort
else
  start_one "$SERVER_NAME" "$API_URL" "$HERE/backend" env DSH_PROFILE=rag-kb PORT=3088 DSH_HOME_DIR=.runtime/dsh-home "$NODE_BIN" index.js
  start_one "$WEB_NAME" "$WEB_URL" "$HERE/frontend" "$NODE_BIN" "$HERE/frontend/node_modules/vite/bin/vite.js" --host 127.0.0.1 --port 5173 --strictPort
fi

ok=0
wait_ready "$SERVER_NAME" "$API_URL" "$(cat "$RUN_DIR/$SERVER_NAME.pid" 2>/dev/null)" 90 || ok=1
wait_ready "$WEB_NAME" "$WEB_URL" "$(cat "$RUN_DIR/$WEB_NAME.pid" 2>/dev/null)" 60 || ok=1

if [ "$MODE" = --harness ] && [ "$ok" -eq 0 ]; then
  for url in "$API_URL" "$WEB_URL/api/health"; do
    if ! curl -fsS -m 5 "$url" | "$NODE_BIN" -e 'let s="";process.stdin.on("data",c=>s+=c);process.stdin.on("end",()=>{try{process.exit(JSON.parse(s).profile===process.argv[1]?0:1)}catch{process.exit(1)}})' "$EXPECTED_PROFILE"; then
      echo "❌ $url 没有连接到 $EXPECTED_PROFILE；请检查占用端口的服务。"; ok=1
    fi
  done
fi

if [ "$ok" -eq 0 ]; then
  echo "🎉 全部就绪，浏览器打开 $WEB_URL/chat"
else
  echo "部分服务未就绪，查看 $RUN_DIR/ 下日志"; exit 1
fi
