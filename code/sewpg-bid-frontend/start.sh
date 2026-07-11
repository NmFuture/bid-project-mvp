#!/bin/bash
# ============================================================
# SEWPG 风电投标智能平台 - 一键启动脚本 (macOS / Linux)
# ============================================================
# 使用方法: 在项目根目录执行  ./start.sh
# 前提条件: 已安装 Node.js >= 18, Python >= 3.9
# ============================================================

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  SEWPG 风电投标智能平台 - 启动中...  ${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# 检查 Node.js
if ! command -v node &> /dev/null; then
    echo -e "${RED}❌ 未检测到 Node.js，请先安装 Node.js >= 18${NC}"
    echo "   下载地址: https://nodejs.org/"
    exit 1
fi

NODE_VERSION=$(node -v | sed 's/v//' | cut -d. -f1)
if [ "$NODE_VERSION" -lt 18 ]; then
    echo -e "${RED}❌ Node.js 版本过低 (当前: $(node -v))，请升级到 >= 18${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Node.js 版本: $(node -v)${NC}"

# 检查 Python3
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ 未检测到 python3，请先安装 Python >= 3.9${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Python 版本: $(python3 --version)${NC}"

# 获取脚本所在目录（支持从任意位置执行）
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 安装前端依赖
if [ ! -d "node_modules" ]; then
    echo -e "${YELLOW}📦 正在安装前端依赖...${NC}"
    npm install
else
    echo -e "${GREEN}✅ 前端依赖已就绪${NC}"
fi

# 检查正式后端虚拟环境
BACKEND_DIR="../sewpg-bid-backend"
BACKEND_PY="$BACKEND_DIR/.venv/bin/python"

if [ ! -x "$BACKEND_PY" ]; then
    echo -e "${RED}❌ 未检测到正式后端虚拟环境。请先执行：${NC}"
    echo "   cd ../sewpg-bid-backend"
    echo "   python3 -m venv .venv"
    echo "   ./.venv/bin/pip install -r requirements.txt"
    exit 1
fi

# 启动正式 FastAPI 后端（开发态自动重载）
echo -e "${YELLOW}🚀 启动正式 FastAPI 后端 (端口 8000，自动重载)...${NC}"
cd "$BACKEND_DIR"
export ONLYOFFICE_BACKEND_BASE_URL="${ONLYOFFICE_BACKEND_BASE_URL:-http://host.docker.internal:8000}"
"$BACKEND_PY" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload --reload-dir app &
FASTAPI_PID=$!
cd "$SCRIPT_DIR"

# 等待服务启动
sleep 2

# 启动前端开发服务器
echo -e "${YELLOW}🚀 启动前端开发服务器 (端口 5173)...${NC}"
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  ✅ 启动完成！${NC}"
echo -e "${GREEN}  🌐 浏览器访问: http://localhost:5173${NC}"
echo -e "${GREEN}  📡 FastAPI API: http://127.0.0.1:8000 (已开启自动重载)${NC}"
echo -e "${GREEN}  📝 当前为正式 backend 入口；OnlyOffice 通过本机 80 端口的 /ds 代理访问${NC}"
echo -e "${GREEN}  ⏹  按 Ctrl+C 停止所有服务${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# 捕获退出信号，同时关闭后端
cleanup() {
    echo ""
    echo -e "${YELLOW}🛑 正在停止服务...${NC}"
    kill "$FASTAPI_PID" 2>/dev/null || true
    echo -e "${GREEN}✅ 所有服务已停止${NC}"
    exit 0
}
trap cleanup INT TERM

# 前台运行前端
npx vite --host
