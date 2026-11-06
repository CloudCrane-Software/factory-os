#!/usr/bin/env bash
# mem-readings.sh — J2 内存防线三读数联防采集器（计划/产品化工作方案-v0.3 §二 J2）
# 口径（T4 终裁 #3）：tmpfs 多数已换出到 swap，防线=df /tmp + MemAvailable + SwapUsed 三线；
#   清 /tmp 的即时收益主要是 swap 空间不是磁盘，故三读数必须联防着看。
# 采集内容：
#   1) df -B1 -P /tmp        → tmpfs total/used/avail（字节）
#   2) /proc/meminfo          → MemAvailable / SwapTotal / SwapFree / Shmem（KB）
#      SwapUsed = SwapTotal - SwapFree（meminfo 无直读键）
#   3) 在役守护 RSS 快照      → pgrep 解析各守护主实例 pid（-o 取最老），ps -o rss=（KB）
# 输出：追加一行 JSONL 到 状态观测/memory-readings.jsonl（同时回显到 stdout）
# 依赖：bash + procps（df/ps/pgrep）+ awk —— 无新依赖。
# 纪律（宪法9 计量先行）：本脚本只读不处置——不动进程、不改限额、不删任何文件。
# 与 factory-keepalive.py 的关系：keepalive 每轮另追加 mem 三值摘要行（src=factory-keepalive），
#   本脚本是其全量版（多 Shmem 与守护 RSS 面），人工/巡检手动跑，两者 JSONL 同文件同字段口径。
set -euo pipefail

WS="/home/pan-ding/workspace/agent黑灯工厂"
OUT="$WS/状态观测/memory-readings.jsonl"

# --- 1) tmpfs /tmp（-B1 字节；-P POSIX 单行保 awk 列稳） ---
read -r TMP_TOTAL TMP_USED TMP_AVAIL < <(df -B1 -P /tmp | awk 'NR==2{print $2, $3, $4}')

# --- 2) /proc/meminfo（MemAvailable/SwapFree/SwapTotal/Shmem） ---
mem_kb() { awk -v k="$1:" '$1==k{print $2}' /proc/meminfo; }
MEM_AVAIL=$(mem_kb MemAvailable)
SWAP_TOTAL=$(mem_kb SwapTotal)
SWAP_FREE=$(mem_kb SwapFree)
SHMEM=$(mem_kb Shmem)
SWAP_USED=$(( SWAP_TOTAL - SWAP_FREE ))

# --- 3) 在役守护 RSS（名:pgrep 模式；-f 全 cmdline、-o 最老主实例=单实例收敛保留者） ---
daemon_pid_rss() {  # $1=模式 → "pid:rss_kb" 或空串（守护不在役=如实记 null）
  local pid rss
  pid=$(pgrep -f -o -- "$1" 2>/dev/null || true)
  [ -n "$pid" ] || return 0
  rss=$(ps -o rss= -p "$pid" 2>/dev/null | tr -d '[:space:]')
  [ -n "$rss" ] || return 0
  printf '%s:%s' "$pid" "$rss"
}

DAEMON_SPECS="keepalive:tools/factory-keepalive.py
router:tools/event-router.py
scheduler:tools/factory-scheduler.py
status-push:tools/factory-status-push.py
emit-sidecar:tools/otel/emit-sidecar.py
self-improve-loop:tools/self-improve-loop.py
quota-governor:tools/quota-governor.py daemon
otelcol:otelcol-build/build/otelcol
watch:tools/factory-watch.py
dash-8790:http.server 8790
dash-18790:http.server 18790"

DAEMONS_JSON=""
first=1
while IFS= read -r spec; do
  [ -n "$spec" ] || continue
  name=${spec%%:*}; pat=${spec#*:}
  pr=$(daemon_pid_rss "$pat")
  if [ -n "$pr" ]; then
    pid=${pr%%:*}; rss=${pr##*:}
    frag="\"${name}\":{\"pid\":${pid},\"rss_kb\":${rss}}"
  else
    frag="\"${name}\":null"   # 不在役：如实记 null，不猜
  fi
  if [ $first -eq 1 ]; then first=0; else DAEMONS_JSON+=","; fi
  DAEMONS_JSON+="$frag"
done <<<"$DAEMON_SPECS"

TS=$(date +%Y-%m-%dT%H:%M:%S%:z)
EPOCH=$(date +%s)
LINE="{\"ts\":\"${TS}\",\"epoch\":${EPOCH},\"src\":\"mem-readings.sh\",\"tmpfs_total_b\":${TMP_TOTAL},\"tmpfs_used_b\":${TMP_USED},\"tmpfs_avail_b\":${TMP_AVAIL},\"mem_available_kb\":${MEM_AVAIL},\"swap_total_kb\":${SWAP_TOTAL},\"swap_free_kb\":${SWAP_FREE},\"swap_used_kb\":${SWAP_USED},\"shmem_kb\":${SHMEM},\"daemons\":{${DAEMONS_JSON}}}"

mkdir -p "$(dirname "$OUT")"
printf '%s\n' "$LINE" >> "$OUT"
printf '%s\n' "$LINE"
