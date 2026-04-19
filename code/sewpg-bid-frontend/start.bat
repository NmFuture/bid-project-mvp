@echo off
chcp 65001 >nul 2>&1
REM ============================================================
REM SEWPG 风电投标智能平台 - 一键启动脚本 (Windows)
REM ============================================================
REM 使用方法: 双击此文件 或在项目根目录执行  start.bat
REM 前提条件: 已安装 Node.js >= 18, Python >= 3.9
REM ============================================================

echo.
echo ========================================
echo   SEWPG 风电投标智能平台 - 启动中...
echo ========================================
echo.

REM 检查 Node.js
where node >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ 未检测到 Node.js，请先安装 Node.js ^>= 18
    echo    下载地址: https://nodejs.org/
    pause
    exit /b 1
)

echo ✅ Node.js 已检测到

REM 检查 Python
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ 未检测到 Python，请先安装 Python ^>= 3.9
    pause
    exit /b 1
)

echo ✅ Python 已检测到

REM 切换到脚本所在目录
cd /d "%~dp0"

REM 安装前端依赖
if not exist "node_modules" (
    echo 📦 正在安装前端依赖...
    call npm install
) else (
    echo ✅ 前端依赖已就绪
)

REM 检查正式后端虚拟环境
set "BACKEND_DIR=..\sewpg-bid-backend"
set "BACKEND_PY=%BACKEND_DIR%\.venv\Scripts\python.exe"

if not exist "%BACKEND_PY%" (
    echo ❌ 未检测到正式后端虚拟环境。请先执行：
    echo    cd ..\sewpg-bid-backend
    echo    python -m venv .venv
    echo    .venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

REM 启动正式 FastAPI 后端（开发态自动重载）
echo 🚀 启动正式 FastAPI 后端 (端口 8000，自动重载)...
start "SEWPG FastAPI" /min cmd /c "cd /d \"%~dp0%BACKEND_DIR%\" && set ONLYOFFICE_BACKEND_BASE_URL=http://host.docker.internal:8000 && \"%BACKEND_PY%\" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload --reload-dir app"

REM 等待服务启动
timeout /t 2 /nobreak >nul

echo.
echo ========================================
echo   ✅ 启动完成！
echo   🌐 浏览器访问: http://localhost:5173
echo   📡 FastAPI API: http://127.0.0.1:8000 ^(已开启自动重载^)
echo   📝 当前为正式 backend 入口；OnlyOffice 请额外保证 8080 已启动
echo   ⏹  关闭此窗口停止前端服务
echo   ⏹  同时关闭 "SEWPG FastAPI" 窗口
echo ========================================
echo.

REM 前台运行前端
npx vite --host
