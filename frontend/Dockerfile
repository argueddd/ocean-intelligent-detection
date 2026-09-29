# 构建 Vite 前端
FROM node:20-alpine AS build

# 设置工作目录
WORKDIR /app

# 复制 package.json 和 package-lock.json
COPY package*.json ./

# 使用锁文件安装完整构建依赖
RUN npm ci

# 复制应用代码
COPY . .

# 构建应用
RUN npm run build

# 使用 nginx 提供静态首页
FROM nginx:alpine

# 复制构建后的文件到 nginx 目录
COPY --from=build /app/dist /usr/share/nginx/html

# 复制 nginx 配置文件（可选）
COPY nginx.conf /etc/nginx/nginx.conf

# 暴露 nginx 监听端口
EXPOSE 80

# 启动 nginx
CMD ["nginx", "-g", "daemon off;"]
