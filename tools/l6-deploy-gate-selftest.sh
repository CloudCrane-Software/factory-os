#!/usr/bin/env bash
# =============================================================================
# l6-deploy-gate-selftest.sh — L6 caddy 部署面完整性门的「判别力」负向自测
#                                （all-gates.sh L3 门常驻项）
#
# 缺口（2026-11-03 RT-CI门本体批，红队已确证发现）：
#   L5 部署一致性门有判别力负向自测（tools/l5-deploy-gate-selftest.sh：桩探针必红
#   → 门必记 FAIL + 绿路对照），而 L6（caddy 部署面完整性门，腿 A 版本面 / B 配置
#   钉桩 / D admin API 加载态 / E 公网入口登记对账）**全门无任何判别力自测**——
#   即「把 tools/caddy-deploy-integrity-probe.sh 改成恒 exit 0」在 L6 侧无人能红：
#   探针被 neuter 后 L6 记 PASS、all-gates exit=0，而 L6 的结论仍被当作 caddy
#   部署面完整性的机器证据。
#   （本自测只钉「门逻辑的判红绿」，探针本体的完整性由钉桩面对账承担：
#    tools/gate-pins-check.sh 校验探针实时摘要与钉桩面一致——探针被改即红。）
#
# 本自测的判据（不改任何既有断言，只钉住「探针必红 → L6 必须记 FAIL」）：
#   红路 A：探针 exit 1（腿红形态）              → L6 记 FAIL、all-gates exit=1
#   红路 B：探针 exit 2（探针不可达/环境错形态）  → L6 记 FAIL、all-gates exit=1
#   红路 C：探针本体缺件（删掉探针）             → L6 记 FAIL、all-gates exit=1
#   绿路 D：探针 exit 0（对照，绿路必须仍绿）    → L6 记 PASS、all-gates exit=0
#   绿路 D 是防空转：若把门改成「恒红」也能骗过红路三条。
#   E 腿（公网入口登记对账）在本沙箱里用桩件（exit 0）代替——它在真环境里只读
#   gov，不是本次判别力目标；桩化只为不让它把绿路 D 拉红。
#
# 隔离与零改动纪律（同 L5 自测先例）：
#   · 沙箱在 mktemp -d 临时目录（<50MB 短命件，AGENT.md 纪律 7 允许），退出即删；
#     真树（tools/ 与工作区在役件）零写入、零改动。
#   · 沙箱里跑的是「真 all-gates.sh 的副本」，只把探针本体换成桩——被测的是真门
#     的判红绿逻辑，不是替身。
#   · HOME 隔离：all-gates.sh 的单例锁 flock 落在 $HOME/all-gates-logs/，不隔离
#     会与在跑的 all-gates 实例抢锁 → 子进程 exit 2（本自测会假红）。
#   · 沙箱内点名模式跑 L6（ANY_NAMED=1 → 只跑 L6），故不会递归回本自测。
# =============================================================================
set -u

TOOLS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GATES="$TOOLS_DIR/all-gates.sh"

NF=0
ok()  { echo "  [OK]   $1"; }
bad() { echo "  [FAIL] $1"; NF=$(( NF + 1 )); }

if [ ! -f "$GATES" ]; then
  echo "FATAL: 门本体缺件：$GATES（自测无法进行）"
  exit 2
fi

SB="$(mktemp -d "${TMPDIR:-/tmp}/l6-selftest.XXXXXX")" || { echo "FATAL: mktemp 失败"; exit 2; }
trap 'rm -rf "$SB"' EXIT
mkdir -p "$SB/tools" "$SB/home" || { echo "FATAL: 沙箱目录创建失败"; exit 2; }
cp "$GATES" "$SB/tools/all-gates.sh" || { echo "FATAL: 门副本拷贝失败"; exit 2; }

# 桩探针：打印一行（门把最后一行写进 note）后按指定码退出
stub_probe() { # $1=退出码  $2=消息
  printf '#!/usr/bin/env bash\necho "%s"\nexit %s\n' "$2" "$1" \
    > "$SB/tools/caddy-deploy-integrity-probe.sh"
  chmod +x "$SB/tools/caddy-deploy-integrity-probe.sh"
}

# E 腿登记对账桩（真件只读 gov，沙箱里桩化为绿，使绿路 D 可判）
stub_registry_check() {
  printf '#!/usr/bin/env python3\nimport sys\nprint("OK：公网入口登记对账桩（沙箱绿路对照）")\nsys.exit(0)\n' \
    > "$SB/tools/public-entry-registry-check.py"
}
stub_registry_check

RUNDIR=""; GSTATUS=""; GNOTE=""; GRC=0
run_L6() {
  local st ms rest
  GOUT="$(HOME="$SB/home" bash "$SB/tools/all-gates.sh" L6 2>&1)"
  GRC=$?
  RUNDIR="$(printf '%s\n' "$GOUT" | grep -o '日志目录：[^ ]*' | tail -1 | sed 's/^日志目录：//')"
  GSTATUS=""; GNOTE=""
  if [ -n "$RUNDIR" ] && [ -f "$RUNDIR/item-0.result" ]; then
    IFS='|' read -r st ms rest < "$RUNDIR/item-0.result"
    GSTATUS="$st"; GNOTE="$rest"
  fi
}

# 断言：状态 / all-gates 退出码 / note 必含子串
expect() { # $1=用例名 $2=期望状态 $3=期望退出码 $4=note 必含子串（可空）
  local nm="$1" ws="$2" we="$3" sub="$4" e=""
  if [ "$GSTATUS" != "$ws" ]; then e="$e 状态期望=$ws 实测=${GSTATUS:-<无结果台账>}"; fi
  if [ "$GRC" != "$we" ]; then e="$e 退出码期望=$we 实测=$GRC"; fi
  if [ -n "$sub" ]; then
    case "$GNOTE" in
      *"$sub"*) ;;
      *) e="$e note 未含「$sub」（实测=${GNOTE:-<空>}）" ;;
    esac
  fi
  if [ -z "$e" ]; then ok "$nm"; else bad "$nm ——$e"; fi
}

echo "=== L6 caddy 部署面完整性门 · 判别力负向自测 ==="
echo "门副本：$SB/tools/all-gates.sh（源 $GATES）"
echo "沙箱 HOME：$SB/home（单例锁隔离）"

# ---- 红路 A：探针 exit 1（腿红形态）----
stub_probe 1 "A红：gov 工作树 ≠ HEAD——版本面外修复未提交"
run_L6
expect "红路A 探针rc=1（腿红）→ L6 必须记 FAIL" "FAIL" "1" "A红"

# ---- 红路 B：探针 exit 2（环境错/不可达形态）----
stub_probe 2 "D红：caddy admin API 不可达——加载态无法对账"
run_L6
expect "红路B 探针rc=2（环境错）→ L6 必须记 FAIL" "FAIL" "1" "D红"

# ---- 红路 C：探针本体缺件 ----
rm -f "$SB/tools/caddy-deploy-integrity-probe.sh"
run_L6
expect "红路C 探针本体缺件 → L6 必须记 FAIL" "FAIL" "1" "caddy-deploy-integrity-probe.sh"

# ---- 绿路 D：探针 exit 0（对照：绿路必须仍绿，防「恒红」空转）----
stub_probe 0 "OK：gov 工作树 ≡ HEAD，五 zone/体帽/事件上限齐备且已加载生效"
run_L6
expect "绿路D 探针rc=0（对照）→ L6 必须记 PASS" "PASS" "0" "OK：gov"

if [ "$NF" = "0" ]; then
  echo "SELFTEST_RESULT: PASS（4/4 用例通过：红路 A/B/C 记 FAIL，绿路 D 记 PASS）"
  exit 0
fi
echo "SELFTEST_RESULT: FAIL（$NF/4 用例未通过——L6 判别力有洞，须修 gate_L6 的 rc 捕获）"
exit 1
