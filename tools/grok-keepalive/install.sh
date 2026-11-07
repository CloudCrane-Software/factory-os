#!/usr/bin/env bash
# grok-keepalive 安装 runbook（D-135 · factory-os#150）
#
# 形制：anolis systemd --user unit+timer（卡面 P2 选型 (b)）——定时跑保活工人
#   tools/grok-auth-probe.py --renew，使 ~/.grok/auth.json 保持新鲜。
# 安装面（全新件，零改既有配置）：
#   ~/.local/opt/grok-keepalive/grok-auth-probe.py   工人脚本（自本仓 tools/ 复制）
#   ~/.config/systemd/user/grok-keepalive.service    oneshot 服务
#   ~/.config/systemd/user/grok-keepalive.timer      30 分钟节拍定时器
#   ~/.local/state/grok-keepalive/                   读数/告警/新鲜度（0700）
# 用法：
#   bash tools/grok-keepalive/install.sh [factory-os 检出根]     安装并启用
#   bash tools/grok-keepalive/install.sh --uninstall             停用并移除安装面
# 凭据纪律：全程零凭据读写；工人对 auth.json 只在续期成功时原子回写（先备份）。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODE="install"
if [ "${1:-}" = "--uninstall" ]; then
  MODE="uninstall"
  shift || true
fi
REPO_ROOT="${1:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
PROBE_SRC="$REPO_ROOT/tools/grok-auth-probe.py"

INSTALL_DIR="${HOME}/.local/opt/grok-keepalive"
UNIT_DIR="${HOME}/.config/systemd/user"
STATE_DIR="${HOME}/.local/state/grok-keepalive"
SERVICE_NAME="grok-keepalive"

log() { printf '[grok-keepalive install] %s\n' "$*"; }

if [ "$MODE" = "uninstall" ]; then
  systemctl --user disable --now "${SERVICE_NAME}.timer" >/dev/null 2>&1 || true
  systemctl --user stop "${SERVICE_NAME}.service" >/dev/null 2>&1 || true
  rm -f "$UNIT_DIR/${SERVICE_NAME}.service" "$UNIT_DIR/${SERVICE_NAME}.timer"
  rm -rf "$INSTALL_DIR"
  systemctl --user daemon-reload || true
  log "已停用并移除 unit/timer 与安装目录（state 目录保留：$STATE_DIR）"
  exit 0
fi

[ -f "$PROBE_SRC" ] || { log "缺工人脚本：$PROBE_SRC（请在 factory-os 检出树上运行）" >&2; exit 2; }

mkdir -p "$INSTALL_DIR" "$UNIT_DIR" "$STATE_DIR"
chmod 700 "$STATE_DIR"
install -m 0755 "$PROBE_SRC" "$INSTALL_DIR/grok-auth-probe.py"
install -m 0644 "$SCRIPT_DIR/${SERVICE_NAME}.service" "$UNIT_DIR/${SERVICE_NAME}.service"
install -m 0644 "$SCRIPT_DIR/${SERVICE_NAME}.timer" "$UNIT_DIR/${SERVICE_NAME}.timer"

systemctl --user daemon-reload
systemctl --user enable --now "${SERVICE_NAME}.timer"

log "安装完成：$INSTALL_DIR ＋ $UNIT_DIR/{service,timer}"
log "timer 状态：$(systemctl --user is-active "${SERVICE_NAME}.timer" 2>&1)"
systemctl --user list-timers "${SERVICE_NAME}.timer" --no-pager 2>&1 | sed 's/^/  /' || true
log "工人首跑（--renew，失败即 fail-closed 属预期：端点不可达时告警落一条）："
python3 -I "$INSTALL_DIR/grok-auth-probe.py" --renew \
  --auth-json "${HOME}/.grok/auth.json" \
  --state-dir "$STATE_DIR" || log "工人退出码=$?（fail-closed；读数见 $STATE_DIR/freshness.json，告警见 $STATE_DIR/alerts.jsonl）"
log "完成"
