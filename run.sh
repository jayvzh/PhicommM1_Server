#!/bin/bash

# Phicomm M1 Server 启动脚本
# 启动 TCP 数据接收服务(端口9000) 和 Flask Web 前端(端口5000)

set -e

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting Phicomm M1 Server..."

# 确保日志目录存在
mkdir -p logs

# 后台启动 TCP 服务(数据采集)
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting TCP data service on port 9000..."
python PhicommM1Server.py &
TCP_PID=$!

# 启动 Flask Web 前端
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting Flask web service on port 5000..."
python app.py &
WEB_PID=$!

echo "[$(date '+%Y-%m-%d %H:%M:%S')] All services started."
echo "  - TCP Service (M1 data): PID $TCP_PID, port 9000"
echo "  - Web Frontend: PID $WEB_PID, port 5000"

# 优雅退出处理
cleanup() {
    echo ""
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Shutting down services..."
    kill $TCP_PID 2>/dev/null || true
    kill $WEB_PID 2>/dev/null || true
    wait $TCP_PID 2>/dev/null || true
    wait $WEB_PID 2>/dev/null || true
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Services stopped."
    exit 0
}

trap cleanup SIGTERM SIGINT

# 等待所有后台进程
wait