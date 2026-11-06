#!/bin/bash
# mcode-once-wrapper.sh — mcode-dispatch once 补跑的硬闸包装（补丁① R2，2026-10-22）。
#
# 语义分工（与 once 本体的区别）：
#   · mcode-dispatch.py once 本体 = 人工知情动作：资源闸闭时不拦，只打横幅警告并写
#     /tmp/mcode-dispatch/deferred.log，照常补跑。
#   · 本 wrapper = 无人值守/脚本调用的硬闸：先跑 gate-check（同一套闸逻辑，只读），
#     闸开才 exec once；闸闭一律拒绝——fail-closed，exit 4，并留一行 deferred.log 审计。
# exit 码：
#   0  once 补跑完成（透传 once 本体结果）
#   3  mcode-dispatch run 的双实例守卫（mcode-dispatch.py single_instance，非本 wrapper）
#   4  资源闸闭或闸状态判不准（fail-closed），once 未执行
# 环境变量：同 mcode-dispatch.py 闸阈值组（MCODE_GATE_* / MCODE_DEFER_*）。
# 用法: mcode-once-wrapper.sh <tid> <m31f|m3>
set -uo pipefail
WS="/home/pan-ding/workspace/agent黑灯工厂"
# 2026-10-31（OBS-D6 文件归档批）：mcode-dispatch.py 已随旧 bench 链退役归档至
# 参考/legacy/bench-infra-retired-20261029/（runbook §三-1⑤；退役报告同目录）。
# 本 wrapper 的 once 补跑面对随之归档——路径指向归档件，避免悬空引用
# （闸闭仍 fail-closed exit 4，语义不变）。
DISPATCH="$WS/参考/legacy/bench-infra-retired-20261029/mcode-dispatch.py"
DEFERRED_LOG="/tmp/mcode-dispatch/deferred.log"

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ] || [ $# -eq 0 ]; then
  grep -E '^#( {2,}·| (语义分工|exit|环境变量|用法))' "$0" | sed 's/^# \{0,1\}//'
  [ $# -eq 0 ] && echo "缺参数：<tid> <m31f|m3>" >&2 && exit 2
  exit 0
fi

python3 "$DISPATCH" gate-check
rc=$?
if [ "$rc" -eq 0 ]; then
  exec python3 "$DISPATCH" once "$@"
fi
echo "[mcode-once-wrapper] $(date '+%F %T') 资源闸闭（gate-check rc=$rc），" \
     "拒绝补跑 $* —— exit 4（fail-closed；人工知情请直接跑 once 本体）" >&2
mkdir -p "$(dirname "$DEFERRED_LOG")" 2>/dev/null
echo "$(date '+%F %T') wrapper-refused 闸闭拒绝补跑 $* (gate-check rc=$rc)" \
  >> "$DEFERRED_LOG" 2>/dev/null
exit 4
