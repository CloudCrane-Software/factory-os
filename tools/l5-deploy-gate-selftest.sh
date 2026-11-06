#!/usr/bin/env bash
# =============================================================================
# l5-deploy-gate-selftest.sh — L5 部署一致性门的「判别力」负向自测
#                                （all-gates.sh L3 门常驻项）
#
# 缺口（2026-11-02 RT 收口，红队终局轮逃逸问题台账 RT-E105/RT-E113 的未复跑项）：
#   all-gates.sh 的 L5 门原先这样捕获探针退出码——
#       note="$(bash probe 2>&1 | tail -1)"
#       rc=${PIPESTATUS[0]}
#   bash 里两处独立失效叠加：
#     ① 命令替换**赋值**会重置 PIPESTATUS → 第 2 行读到的是「赋值语句」自身的
#        退出码（恒 0），不是探针的；
#     ② 即使赋值不重置，命令替换内含管道时其退出码取管道**末段**（tail，恒 0）。
#   叠加后果：探针无论红（D2 md5 漂移 rc=1 / gov 不可达 rc=2 / 探针本体缺件
#   rc=127）都被门记成 PASS，all-gates exit=0，红名单为空——L5 在结构上不可能红，
#   是「真空门」；而映射 G3 行拿「L5 PASS」当部署稳定性的机器证据。
#
# 本自测的判据（不改任何既有断言，只钉住「探针必红 → 门必须记 FAIL」）：
#   红路 A：探针 exit 1（D2 md5 漂移形态）    → 门记 FAIL、all-gates exit=1
#   红路 B：探针 exit 2（gov 不可达形态）      → 门记 FAIL、all-gates exit=1
#   红路 C：探针本体缺件（删掉探针）           → 门记 FAIL、all-gates exit=1
#   绿路 D：探针 exit 0（对照，绿路必须仍绿）  → 门记 PASS、all-gates exit=0
#   绿路 D 是防空转：若把门改成「恒红」也能骗过红路三条。
#
# 隔离与零改动纪律：
#   · 沙箱在 mktemp -d 临时目录（<50MB 短命件，AGENT.md 纪律 7 允许），
#     退出即删；真树（tools/ 与工作区在役件）零写入、零改动。
#   · 沙箱里跑的是「真 all-gates.sh 的副本」，只把探针本体换成桩——被测的是真门
#     的判红绿逻辑，不是替身。
#   · HOME 隔离：all-gates.sh 的单例锁 flock 落在 $HOME/all-gates-logs/，
#     不隔离会与在跑的 all-gates 实例抢锁 → 子进程 exit 2（本自测会假红）。
#   · 沙箱内点名模式跑 L5（ANY_NAMED=1 → 只跑 L5），故不会递归回本自测。
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

SB="$(mktemp -d "${TMPDIR:-/tmp}/l5-selftest.XXXXXX")" || { echo "FATAL: mktemp 失败"; exit 2; }
trap 'rm -rf "$SB"' EXIT
mkdir -p "$SB/tools" "$SB/home" || { echo "FATAL: 沙箱目录创建失败"; exit 2; }
cp "$GATES" "$SB/tools/all-gates.sh" || { echo "FATAL: 门副本拷贝失败"; exit 2; }

# 桩探针：打印一行（门把最后一行写进 note）后按指定码退出
stub_probe() { # $1=退出码  $2=消息
  printf '#!/usr/bin/env bash\necho "%s"\nexit %s\n' "$2" "$1" \
    > "$SB/tools/deploy-consistency-probe.sh"
  chmod +x "$SB/tools/deploy-consistency-probe.sh"
}

# 第二腿桩（2026-11-03 RT-45 修复批后 gate_L5 新增「公网静态面实况」腿，调
# tools/publish-live-surface-probe.py；沙箱里无此件 → 绿路会被它拉红——
# 与 L6 自测桩化 public-entry-registry-check.py 同理：桩成绿，使绿路 D 可判）。
stub_live_surface() {
  printf '#!/usr/bin/env python3\nimport sys\nprint("OK：公网静态面实况桩（沙箱绿路对照）")\nsys.exit(0)\n' \
    > "$SB/tools/publish-live-surface-probe.py"
}
stub_live_surface

# 第三腿桩（2026-11-03 11:51 anolis 部署面批后 gate_L5 新增「anolis-deploy-consistency」
# 腿，调 tools/anolis-deploy-consistency-probe.sh；该批晚于本自测（06:50）成文，沙箱
# 无此件 → 绿路 D 被缺件拉红（2026-11-03 J5 修复：all-gates L5 自测项 FAIL 的根因
# ——红路 A/B/C 不受影响〔deploy-consistency 腿已先红〕，仅绿路对照被误伤）。
# 桩成绿同理；该腿 rc 捕获与另两腿同款直接捕获（A/B/C 已钉红路），不另立红路用例。
stub_anolis_deploy() {
  printf '#!/usr/bin/env bash\necho "OK：anolis 部署面桩（沙箱绿路对照）——四件在役 sha256 ≡ 本地正本，两守护已加载生效"\nexit 0\n' \
    > "$SB/tools/anolis-deploy-consistency-probe.sh"
  chmod +x "$SB/tools/anolis-deploy-consistency-probe.sh"
}
stub_anolis_deploy

RUNDIR=""; GSTATUS=""; GNOTE=""; GRC=0
run_L5() {
  local st ms rest
  GOUT="$(HOME="$SB/home" bash "$SB/tools/all-gates.sh" L5 2>&1)"
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

echo "=== L5 部署一致性门 · 判别力负向自测 ==="
echo "门副本：$SB/tools/all-gates.sh（源 $GATES）"
echo "沙箱 HOME：$SB/home（单例锁隔离）"

# ---- 红路 A：探针 exit 1（D2 md5 漂移形态）----
stub_probe 1 "D2红：md5 不一致 local=aaa remote=bbb——在役不是本地已修版"
run_L5
expect "红路A 探针rc=1（D2 md5漂移）→ 门必须记 FAIL" "FAIL" "1" "D2红"

# ---- 红路 B：探针 exit 2（gov 不可达形态）----
stub_probe 2 "D2红：ssh root@gov-host.invalid 不可达——在役面无法对账"
run_L5
expect "红路B 探针rc=2（gov不可达）→ 门必须记 FAIL" "FAIL" "1" "不可达"

# ---- 红路 C：探针本体缺件 ----
rm -f "$SB/tools/deploy-consistency-probe.sh"
run_L5
expect "红路C 探针本体缺件 → 门必须记 FAIL" "FAIL" "1" "deploy-consistency-probe.sh"

# ---- 绿路 D：探针 exit 0（对照：绿路必须仍绿，防「恒红」空转）----
stub_probe 0 "OK：在役=本地已修版 md5=abcdef12……，部署一致且已加载生效"
run_L5
expect "绿路D 探针rc=0（对照）→ 门必须记 PASS" "PASS" "0" "OK：在役"

if [ "$NF" = "0" ]; then
  echo "SELFTEST_RESULT: PASS（4/4 用例通过：红路 A/B/C 记 FAIL，绿路 D 记 PASS）"
  exit 0
fi
echo "SELFTEST_RESULT: FAIL（$NF/4 用例未通过——L5 判别力有洞，须修 gate_L5 的 rc 捕获）"
exit 1
