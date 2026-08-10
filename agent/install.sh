#!/bin/bash
# CICD Agent 安装脚本
# 用法: ./install.sh <MASTER_URL> <TOKEN> [AGENT_NAME]
set -e

MASTER_URL="${1:?用法: ./install.sh <MASTER_URL> <TOKEN> [AGENT_NAME]}"
TOKEN="${2:?缺少 TOKEN 参数}"
AGENT_NAME="${3:-$(hostname)}"

INSTALL_DIR="/usr/local/bin"
CONFIG_DIR="/etc/cicd-agent"
WORK_DIR="/var/lib/cicd-agent"
SERVICE_FILE="/etc/systemd/system/cicd-agent.service"

echo "=== CICD Agent 安装 ==="
echo "Master: $MASTER_URL"
echo "Name:   $AGENT_NAME"

# 检测架构
ARCH=$(uname -m)
case "$ARCH" in
  x86_64)  GOARCH="amd64" ;;
  aarch64) GOARCH="arm64" ;;
  *)       echo "不支持的架构: $ARCH"; exit 1 ;;
esac

# 编译（如果本地有 Go 环境）或从 Master 下载二进制
BINARY="$INSTALL_DIR/cicd-agent"
if command -v go &>/dev/null; then
  echo "[1/4] 编译 Agent..."
  cd "$(dirname "$0")"
  CGO_ENABLED=0 GOOS=linux GOARCH=$GOARCH go build -ldflags="-s -w" -o "$BINARY" .
else
  echo "[1/4] 未检测到 Go 环境，请手动编译后放置到 $BINARY"
  echo "  编译命令: CGO_ENABLED=0 GOOS=linux GOARCH=$GOARCH go build -ldflags=\"-s -w\" -o cicd-agent ."
  if [ ! -f "$BINARY" ]; then
    exit 1
  fi
fi
chmod +x "$BINARY"

# 配置
echo "[2/4] 写入配置..."
mkdir -p "$CONFIG_DIR" "$WORK_DIR"
cat > "$CONFIG_DIR/agent.env" <<EOF
CICD_MASTER_URL=$MASTER_URL
CICD_TOKEN=$TOKEN
CICD_AGENT_NAME=$AGENT_NAME
CICD_POLL_INTERVAL=3
CICD_HEARTBEAT_SEC=30
CICD_MAX_CONCURRENT=2
CICD_WORK_DIR=$WORK_DIR
EOF

# systemd
echo "[3/4] 注册 systemd 服务..."
cp "$(dirname "$0")/cicd-agent.service" "$SERVICE_FILE"
systemctl daemon-reload
systemctl enable cicd-agent

# 启动
echo "[4/4] 启动服务..."
systemctl restart cicd-agent
sleep 1
systemctl status cicd-agent --no-pager

echo ""
echo "=== 安装完成 ==="
echo "查看日志: journalctl -u cicd-agent -f"
