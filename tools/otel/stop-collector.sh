#!/usr/bin/env bash
# stop-collector.sh — OTel 非关键 lane collector 常驻停止器（run-collector.sh 的对件）
#
# 纪律：
#   · PID 文件 + /proc/<pid>/cmdline 双重校验——PID 回收误杀防护（进程在但非 otelcol 即拒杀）；
#   · SIGTERM 先行（collector 优雅关：flush sending_queue/file_storage 持久队列），
#     15s 宽限后 SIGKILL 兜底；
#   · 幂等：未运行时退出 0（清陈旧 pidfile），不报错不重复杀；
#   · 只停本件起的 otelcol，不碰五守护本体、不碰 e2e 的临时 collector（那批自带 finally 关停）。
# 用法：tools/otel/stop-collector.sh
# 环境变量：OTEL_RUNTIME（缺省 ~/otelcol-runtime）
set -euo pipefail

RUNTIME="${OTEL_RUNTIME:-$HOME/otelcol-runtime}"
PIDFILE="$RUNTIME/otelcol.pid"
LOG="$RUNTIME/logs/collector.log"

log() { echo "[$(date '+%F %T')] stop-collector: $*"; }

if [ ! -f "$PIDFILE" ]; then
  log "未运行（pidfile 缺失: $PIDFILE）"
  exit 0
fi

pid=$(cat "$PIDFILE" 2>/dev/null || true)
if [ -z "$pid" ] || ! kill -0 "$pid" 2>/dev/null; then
  log "进程不在（pid=$pid，陈旧 pidfile 已清理）"
  rm -f "$PIDFILE"
  exit 0
fi

if ! tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | grep -q "otelcol"; then
  log "拒杀：pid=$pid 存活但 cmdline 非 otelcol（PID 回收误配？）——pidfile 保留待人工核对"
  exit 1
fi

log "SIGTERM → pid=$pid（优雅关：flush 持久发送队列 file_storage）"
kill -TERM "$pid" 2>/dev/null || true
for _ in $(seq 1 75); do     # 15s 宽限
  kill -0 "$pid" 2>/dev/null || break
  sleep 0.2
done

if kill -0 "$pid" 2>/dev/null; then
  log "15s 未退出，SIGKILL 兜底 → pid=$pid"
  kill -KILL "$pid" 2>/dev/null || true
  sleep 0.5
fi

if kill -0 "$pid" 2>/dev/null; then
  log "FAIL: pid=$pid 仍在"
  exit 1
fi
rm -f "$PIDFILE"
log "已停止（pid=$pid；pidfile 已清理；日志保留 $LOG）"
exit 0
