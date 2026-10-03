# rag-kb 后端镜像：适配层 + dsh 运行时（构建上下文 = 仓库根目录）
FROM node:24-slim

# SDK 会话日志使用多帧 Zstandard；历史消息读取需要 zstd CLI。
RUN apt-get update && apt-get install -y --no-install-recommends zstd && apt-get clean

WORKDIR /app/backend

# 先装依赖（锁文件含 overrides：@deepseek-ai/dsh 家族钉回 0.1.6-alpha.1，避免 alpha.2 漂移）
COPY backend/package.json backend/package-lock.json ./
RUN npm ci --omit=dev --no-fund --no-audit

# 适配层与 dsh 运行时（dsh/home 的 settings/profiles 与插件；.env 不进镜像，由 compose 注入）
COPY backend/index.js backend/integrations.js backend/artifacts.js ./
COPY backend/harness /app/backend/harness
COPY backend/dsh /app/backend/dsh

ENV NODE_ENV=production
EXPOSE 3088

CMD ["node", "index.js"]
