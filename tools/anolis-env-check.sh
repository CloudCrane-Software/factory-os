#!/bin/bash
# anolis-env-check.sh — 环境基准卡（运营者② 2026-11-06）：anolis 执行前统一预检。
# 根治复发 ≥4 次的环境坑：cargo PATH（nohup 新壳）/ENOSPC 误诊（编译错包装真盘满）。
# 用法：source 或前置执行；fail-closed：任一不过 ⇒ 结构化 JSON 报错 + exit 2（不许继续）。
export PATH="$HOME/.cargo/bin:$PATH"
if ! command -v cargo >/dev/null 2>&1; then
  echo '{"env_check":"FAIL","reason":"cargo_not_on_path","hint":"source ~/.cargo/env 或 export PATH=$HOME/.cargo/bin:$PATH"}'
  exit 2
fi
AVAIL_G=$(df -BG /data 2>/dev/null | awk 'NR==2{gsub(/G/,"",$4);print $4}')
if [ -z "$AVAIL_G" ] || [ "$AVAIL_G" -lt 10 ]; then
  echo "{\"env_check\":\"FAIL\",\"reason\":\"data_lt_10G\",\"avail_g\":\"$AVAIL_G\",\"df\":\"$(df -h /data | tail -1 | tr -s ' ')\"}"
  exit 2
fi
echo "{\"env_check\":\"OK\",\"cargo\":\"$(command -v cargo)\",\"data_avail_g\":$AVAIL_G}"
exit 0
