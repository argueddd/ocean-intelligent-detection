# 开发环境Dockerfile
FROM node:20-bullseye

WORKDIR /app

# 复制package文件
COPY package*.json ./

# 安装依赖
RUN npm install

# 暴露开发服务器端口
EXPOSE 3000

# 启动开发服务器
CMD ["npm", "start"]
