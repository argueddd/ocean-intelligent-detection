#!/bin/bash

# 多Agent展示系统部署脚本
# 使用方法: ./deploy.sh [dev|prod]

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 打印带颜色的消息
print_message() {
    echo -e "${2}${1}${NC}"
}

# 检查命令是否存在
check_command() {
    if ! command -v $1 &> /dev/null; then
        print_message "错误: $1 命令未找到，请先安装 $1" $RED
        exit 1
    fi
}

# 开发环境部署
deploy_dev() {
    print_message "🚀 启动开发环境..." $BLUE
    
    cd homepage
    
    # 检查是否已安装依赖
    if [ ! -d "node_modules" ]; then
        print_message "📦 安装依赖..." $YELLOW
        npm install
    fi
    
    print_message "🔧 启动开发服务器..." $GREEN
    npm start
}

# 生产环境部署
deploy_prod() {
    print_message "🐳 部署生产环境..." $BLUE
    
    # 检查Docker
    check_command docker
    check_command docker-compose
    
    # 创建网络
    print_message "🌐 创建Docker网络..." $YELLOW
    docker network create proxy-tier 2>/dev/null || print_message "网络已存在" $GREEN
    
    # 停止现有服务
    print_message "🛑 停止现有服务..." $YELLOW
    docker-compose down 2>/dev/null || true
    
    # 构建并启动
    print_message "🔨 构建并启动服务..." $GREEN
    docker-compose up --build -d
    
    # 等待服务启动
    print_message "⏳ 等待服务启动..." $YELLOW
    sleep 10
    
    # 检查服务状态
    print_message "✅ 检查服务状态..." $GREEN
    docker-compose ps
    
    print_message "🎉 部署完成！" $GREEN
    print_message "访问地址: http://localhost" $BLUE
    print_message "查看日志: docker-compose logs -f" $BLUE
}

# 清理环境
clean() {
    print_message "🧹 清理环境..." $YELLOW
    
    # 停止服务
    docker-compose down 2>/dev/null || true
    
    # 清理Docker缓存
    docker system prune -f
    
    # 清理npm缓存
    if [ -d "homepage" ]; then
        cd homepage
        npm cache clean --force 2>/dev/null || true
        cd ..
    fi
    
    print_message "✅ 清理完成！" $GREEN
}

# 备份数据
backup() {
    print_message "💾 备份数据..." $YELLOW
    
    BACKUP_DIR="backup_$(date +%Y%m%d_%H%M%S)"
    mkdir -p $BACKUP_DIR
    
    # 备份配置文件
    cp -r homepage/src/data $BACKUP_DIR/
    cp -r homepage/public/data $BACKUP_DIR/
    cp docker-compose.yml $BACKUP_DIR/
    cp nginx.conf $BACKUP_DIR/
    
    print_message "✅ 备份完成: $BACKUP_DIR" $GREEN
}

# 恢复数据
restore() {
    if [ -z "$1" ]; then
        print_message "请指定备份目录: ./deploy.sh restore backup_20240101_120000" $RED
        exit 1
    fi
    
    BACKUP_DIR=$1
    if [ ! -d "$BACKUP_DIR" ]; then
        print_message "备份目录不存在: $BACKUP_DIR" $RED
        exit 1
    fi
    
    print_message "🔄 恢复数据从: $BACKUP_DIR" $YELLOW
    
    # 恢复配置文件
    cp -r $BACKUP_DIR/data/* homepage/src/data/
    cp -r $BACKUP_DIR/data/* homepage/public/data/
    cp $BACKUP_DIR/docker-compose.yml .
    cp $BACKUP_DIR/nginx.conf .
    
    print_message "✅ 恢复完成！" $GREEN
}

# 显示帮助
show_help() {
    echo "多Agent展示系统部署脚本"
    echo ""
    echo "使用方法:"
    echo "  ./deploy.sh dev          # 启动开发环境"
    echo "  ./deploy.sh prod         # 部署生产环境"
    echo "  ./deploy.sh clean        # 清理环境"
    echo "  ./deploy.sh backup       # 备份数据"
    echo "  ./deploy.sh restore <dir> # 恢复数据"
    echo "  ./deploy.sh help         # 显示帮助"
    echo ""
    echo "示例:"
    echo "  ./deploy.sh prod         # 部署到生产环境"
    echo "  ./deploy.sh backup       # 备份当前配置"
    echo "  ./deploy.sh restore backup_20240101_120000 # 恢复备份"
}

# 主函数
main() {
    case ${1:-help} in
        dev)
            deploy_dev
            ;;
        prod)
            deploy_prod
            ;;
        clean)
            clean
            ;;
        backup)
            backup
            ;;
        restore)
            restore $2
            ;;
        help|--help|-h)
            show_help
            ;;
        *)
            print_message "未知命令: $1" $RED
            show_help
            exit 1
            ;;
    esac
}

# 检查参数
if [ $# -eq 0 ]; then
    show_help
    exit 1
fi

# 执行主函数
main "$@"
