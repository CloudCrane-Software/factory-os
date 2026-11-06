#!/usr/bin/env bash
# 外派执行器：把一批活送到 anolis 上跑，本机不占工作流槽位。
#
# 背景（2026-11-04）
# ------------------
# 昨夜 zcode 被内核 OOM 杀死 8 次（/var/log/syslog: app-zcode-*.scope
# Failed with result 'oom-kill'），本机 16 核 / 15.2G 内存 / 20.5G swap。
# 用户定规：并行度仍重要，但同一个时间只有三个工作流在本机跑，超出的
# 放到 anolis 或 tailnet 其他机器去跑。
#
# 本机三道并发闸：
#   1) tools/wf-gate.py —— 本机 ≤3 的机械门（fail-closed，满即拒）
#   2) 本脚本 —— 外派通道的落地执行面
#   3) anolis 侧的 zcode 无头 CLI —— 真正干活的那个
#
# 用法
# ----
#   bash tools/wf-offload.sh <brief.md> <remote-workdir> <label> [review-brief.md]
#
#   <brief.md>          任务书文件（自足：不含任何本会话上下文）
#   <remote-workdir>    anolis 上的工作目录（须已存在）
#   <label>             本次外派的标��（用于日志与台账登记）
#   [review-brief.md]   可选：第二份任务书（复核面），跑完施工后依次执行
#
# 行为
# ----
#   · 任务书 rsync 到 anolis 的 <remote-workdir>/.offload/
#   · 依次执行 zcode -p "<任务书全文>" --mode yolo --cwd <remote-workdir>
#     ——无头 CLI，输出全部落盘，不占本机工作流槽位
#   · 施工与复核之间**不自动判定**：复核任务书自己写清要看什么、怎么判
#   · 全部 stdout/stderr 落 <remote-workdir>/.offload/<label>.log 并 rsync 回本机
#   · 退出码：0 = 各段 zcode 进程都正常退出；非 0 = 有段失败或被中止
#
# 硬约束
# --------
#   · 禁 sudo（本脚本全程用当前用户身份，anolis 侧也是 pan-ding）
#   · 不碰本机工作流槽位计数（那是 wf-gate.py 的事，外派不占本机槽）
#   · 不删远端任何目录；只写 <remote-workdir>/.offload/ 与任务书指定的面
set -uo pipefail

# 工作区根：快照执行时 BASH_SOURCE 指向 /tmp，**必须靠环境变量把真 WS 带进来**，
# 否则相对路径会拼成 "/30-工件/..."（2026-11-04 自测当场逮到）。
if [ -n "${WF_OFFLOAD_WS:-}" ]; then
  WS="$WF_OFFLOAD_WS"
else
  WS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  export WF_OFFLOAD_WS="$WS"
fi

# --- 快照自执行（2026-11-04 两次实测教训，务必保留）--------------------------------
# bash 是**边执行边读脚本文件**的：本文件在运行期间被编辑 ⇒ 运行中的实例读取偏移错位 ⇒
# 报 "寻找匹配的 ' 时遇到了未预期的 EOF" / "未预期的记号 "(" 附近有语法错误" / "未找到命令"。
# **本项目已因此丢过两段外派**：11:20 compiler-diagnostics 的复核段、12:40 mainline-fmt-zero
# 的复核段（施工段都跑完了，复核段被这次编辑打断）。
#
# 修法（本块不可删）：先把自身拷成**快照**，再由快照执行后续逻辑——此后对
# tools/wf-offload.sh 的任何编辑都**影响不到在跑的实例**（跑的那个读的是稳定副本）。
# 关键点：必须**真的由快照执行**（下面这行 bash "$_snap" "$@"），光拷贝不切换是无效的。
if [ -z "${WF_OFFLOAD_SNAP:-}" ]; then
  export WF_OFFLOAD_SNAP=1
  _snap="$(mktemp -t wf-offload-XXXXXX.sh)"
  cp -- "${BASH_SOURCE[0]}" "$_snap" 2>/dev/null || { echo "FAIL 拷快照失败"; exit 3; }
  bash "$_snap" "$@"
  _rc=$?
  rm -f "$_snap"
  exit "$_rc"
fi
# -------------------------------------------------------------------------------------

REMOTE="${OFFLOAD_REMOTE:-anolis}"
SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=15)

# ============================================================================
# 2026-11-05 发布面接线批 ③：执行器 GC 口径扩展（回收时机 / 回收口径 / 收卷回收入口）
# ----------------------------------------------------------------------------
# ★ 现状缺陷（亲读实测）：原 gc_target() / gc_stale_targets() 是**本地** bash 函数，
#   却对**远端**路径 /data/bench/targets/* 做 stat/du/rm ⇒ 本机该路径不存在 ⇒
#   两个函数恒 return 0（**空转**）⇒ 自 2026-11-04 21:1x「顺带回收历史遗留盘」那次
#   改动起，「已回收…MB」**从未真正发生过**；7 批已完工批的 141G 独占构建盘一直
#   占着 /data（94%）⇒ 两次「满盘 → cargo 报 ld terminated with signal 7」假红。
#   **修法：回收动作必须在远端执行**（ssh 过去跑），本机只发令 + 传判据参数。
#
# 判据四件（全部**可证**，不含「看着像旧的」那种不可证判据）：
#   ① 目录必须落在目标根下（$ROOT/<label>）——绝不碰非 target 的东西；
#   ② 尺寸 > 8G（**既有门槛不动**；仅夹具自证档可下调，产线路径不可调）；
#   ③ **无进程持有该路径**——这是「没有批在用它」的可证判据：
#      /proc/*/environ 里 CARGO_TARGET_DIR 指向它，或进程 cwd / 打开的 fd 落在它里面
#      （执行器给每批设独占 CARGO_TARGET_DIR；远端实测同 uid 的 /proc/<pid>/environ
#      可读 ⇒ 判据在远端可用；禁 sudo ⇒ 别的 uid 的进程读不到，边界已登记）；
#   ④ 全树最近一次写入距今 > GC_AGE_S（默认 600s=10min）——比既有 3600s 更及时
#      （任务书 ③② 明示要覆盖「刚完工 <1h」那批）；**定向回收（收卷即回收）免本条**
#      ——收卷是人工的显式信号，安全由 ③ 兜底。
#   ★ 只让回收更及时，不删任何非 target 的东西；被回收的目录是**可再生缓存**。
# ============================================================================
GC_AGE_S=600           # 「最近写入距今」门槛（秒）
GC_MIN_MB=8192         # 尺寸门槛（MB；既有 8G 门槛）
GC_SELFTEST_MIN_MB=1   # 夹具自证专用尺寸门槛（**产线路径读不到这个值**）
# 远端独占构建盘根（2026-11-05 接线批 ③：可被环境变量改指——夹具自证/演练用；
# 缺省仍是产线值 /data/bench/targets）
export REMOTE_TARGET_ROOT="${WF_TARGET_ROOT:-/data/bench/targets}"

# 回收脚本体（同一份字节：远端 ssh 跑＝真回收；本地夹具跑＝自证）
GC_BODY=$(cat <<'GC_EOF'
set -u
ROOT="$1"; MODE="$2"; MIN_MB="$3"; AGE_S="$4"; ONLY="${5:-}"; EXCL="${6:-}"
[ -d "$ROOT" ] || { echo "GC_SKIP 目标根不在位：$ROOT"; exit 0; }
now=$(date +%s); cutoff=$(( now - AGE_S ))
held_tmp="$(mktemp "${TMPDIR:-/tmp}/wf-gc-held.XXXXXX")" || { echo "GC_FAIL mktemp 失败"; exit 3; }
trap 'rm -f "$held_tmp"' EXIT
# ---- 持有面快照（一次扫描 ⇒ 进程当前持有的路径全集）----
for pid in /proc/[0-9]*; do
  pid="${pid#/proc/}"
  # 别的 uid 的进程读不到（禁 sudo ⇒ 不追查；边界已登记）——静默跳过，不刷屏
  { tr '\0' '\n' < "/proc/$pid/environ" 2>/dev/null \
      | grep '^CARGO_TARGET_DIR=' 2>/dev/null | cut -d= -f2-; } 2>/dev/null >>"$held_tmp"
  readlink "/proc/$pid/cwd" 2>/dev/null >>"$held_tmp"
  for fd in "/proc/$pid/fd/"*; do readlink "$fd" 2>/dev/null >>"$held_tmp"; done
done
sort -u "$held_tmp" -o "$held_tmp"
is_held() { grep -qxF "$1" "$held_tmp" 2>/dev/null && return 0; grep -qF "$1/" "$held_tmp" 2>/dev/null; }
tree_fresh() { find "$1" -newermt "@$2" -print -quit 2>/dev/null | grep -q .; }
# 台账在跑判据（EXCL = 本机调度台账里 **active** 的条目 id/label，"|" 分隔）：
#   远端看不到本机台账（注册表在本机）⇒ 由本机发令时把「在跑的条目」带下去。
#   与「进程持有」判据是**两条独立的腿**：进程持有＝此刻真在构建；台账在跑＝
#   调度层还认它活着（实测：台账 active 但此刻无进程持盘的批 ⇒ 只有这条腿拦得住）。
declared_running() {
  local name="$1" item
  [ -n "$EXCL" ] || return 1
  local IFS='|'
  for item in $EXCL; do
    [ -n "$item" ] || continue
    case "$item" in *"$name"*) return 0;; esac
  done
  return 1
}
freed=0
for d in "$ROOT"/*; do
  [ -d "$d" ] || continue
  base="$(basename "$d")"
  [ -n "$ONLY" ] && [ "$ONLY" != "$base" ] && continue
  sz="$(du -sm "$d" 2>/dev/null | awk '{print $1}')"
  case "$sz" in ''|*[!0-9]*) continue;; esac
  if [ "$sz" -le "$MIN_MB" ]; then
    [ -n "$ONLY" ] && echo "GC_KEEP $base ${sz}MB（未过 ${MIN_MB}MB 尺寸门槛——小批留着更快）"
    continue
  fi
  if is_held "$d"; then
    echo "GC_KEEP $base ${sz}MB（有在跑进程持有该路径——不误删在跑的批）"
    continue
  fi
  if declared_running "$base"; then
    echo "GC_KEEP $base ${sz}MB（调度台账里该批仍 active——不误删在跑的批）"
    continue
  fi
  if [ "$MODE" = "apply" ] && [ -z "$ONLY" ] && tree_fresh "$d" "$cutoff"; then
    echo "GC_KEEP $base ${sz}MB（树内 ${AGE_S}s 内有写入——判据不满足）"
    continue
  fi
  if [ "$MODE" = "dry-run" ]; then
    echo "GC_WOULD_RECLAIM $base ${sz}MB"
    continue
  fi
  if rm -rf "$d" 2>/dev/null; then
    freed=$((freed + sz)); echo "GC_RECLAIM $base ${sz}MB（可再生缓存）"
  else
    echo "GC_FAIL $base（回收失败——不可证不猜绿）"
  fi
done
echo "GC_SUMMARY freed=${freed}MB root=$ROOT mode=$MODE only=${ONLY:-ALL}"
exit 0
GC_EOF
)

gc_body_file() {
  local f
  f="$(mktemp "${TMPDIR:-/tmp}/wf-gc-body.XXXXXX.sh")" || return 3
  printf '%s\n' "$GC_BODY" >"$f"
  printf '%s\n' "$f"
}

gc_run_local() {   # root mode min_mb age_s only excl
  local f rc
  f="$(gc_body_file)" || return 3
  bash "$f" "$1" "$2" "$3" "$4" "$5" "${6:-}"
  rc=$?
  rm -f "$f"
  return $rc
}

gc_run_remote() {  # root mode min_mb age_s only excl —— 回收动作在**远端**执行
  local f rc excl="${6:-}"
  excl="${excl//\'/\'\"\'\'}"
  f="$(gc_body_file)" || return 3
  ssh "${SSH_OPTS[@]}" "$REMOTE" "bash -s -- '$1' '$2' '$3' '$4' '$5' '$excl'" <"$f"
  rc=$?
  rm -f "$f"
  return $rc
}

# 台账在跑清单（**本机**读；远端拿不到本机注册表——2026-11-04 原注释即此意）：
#   读 状态/wf-gate/registry.json 里 state=active 的条目，把它们的 id 与 label
#   拼成 "|" 分隔串交给远端判据（远端据此判「台账在跑」⇒ 不回收那个 label 的盘）。
#   ★ fail-closed：台账**读不出/损坏** ⇒ 回收**整体拒绝**（不猜「没在跑」）。
gc_active_exclusions() {
  local reg="$WS/状态/wf-gate/registry.json"
  if [ ! -f "$reg" ]; then
    echo "GC_DENY 台账不在位：$reg——不可证不猜绿（不回收）" >&2
    return 2
  fi
  local out
  if ! out="$(python3 -I - "$reg" <<'PY' 2>/dev/null
import json, sys
try:
    with open(sys.argv[1], encoding="utf-8") as f:
        d = json.load(f)
except Exception:
    sys.exit(3)
if not isinstance(d, dict) or not isinstance(d.get("entries"), list):
    sys.exit(3)
parts = []
for e in d["entries"]:
    if isinstance(e, dict) and e.get("state") == "active":
        for k in ("id", "label"):
            v = e.get(k)
            if isinstance(v, str) and v:
                parts.append(v)
print("|".join(parts))
PY
)"; then
    echo "GC_DENY 台账读不出/损坏：$reg——不可证不猜绿（不回收）" >&2
    return 2
  fi
  printf '%s' "$out"
}

gc_selftest() {    # $1=夹具根（缺省=临时目录；自证结束自清）
  local root="${1:-}" made=0 fail=0 holder sentinel excl
  if [ -z "$root" ]; then
    root="$(mktemp -d "${TMPDIR:-/tmp}/wf-gc-selftest.XXXXXX")" || return 3
    made=1
  fi
  mkdir -p "$root/done-batch/sub" "$root/running-batch/sub" "$root/fresh-batch/sub" \
           "$root/declared-batch/sub"
  dd if=/dev/zero of="$root/done-batch/sub/blob" bs=1M count=2 status=none
  cp "$root/done-batch/sub/blob" "$root/running-batch/sub/blob"
  cp "$root/done-batch/sub/blob" "$root/fresh-batch/sub/blob"
  cp "$root/done-batch/sub/blob" "$root/declared-batch/sub/blob"
  touch -d '-2 hours' "$root/done-batch" "$root/done-batch/sub" "$root/done-batch/sub/blob"
  touch -d '-2 hours' "$root/running-batch" "$root/running-batch/sub" "$root/running-batch/sub/blob"
  touch -d '-2 hours' "$root/declared-batch" "$root/declared-batch/sub" "$root/declared-batch/sub/blob"
  sentinel="$(dirname "$root")/wf-gc-selftest-sentinel.$$"
  echo "sentinel-not-a-target" >"$sentinel"
  # 在跑批：起一个**真进程**持有 running-batch（CARGO_TARGET_DIR 指向它）
  env CARGO_TARGET_DIR="$root/running-batch" sleep 600 &
  holder=$!
  sleep 1
  # 台账在跑批：declared-batch 无进程持有，但**台账里 active**（第二条腿拦它）
  excl="offload-declared-batch|declared-batch 的台账条目"
  echo "== 回收判据夹具自证（尺寸门槛 ${GC_SELFTEST_MIN_MB}MB 自证档；树内写入龄 ${GC_AGE_S}s）=="
  echo "   夹具根：$root"
  echo "   已完工批 done-batch（陈旧 2h、无进程持有、台账不在跑）⇒ 应被回收"
  echo "   在跑批   running-batch（陈旧 2h、pid $holder 的 CARGO_TARGET_DIR 指向它）⇒ **必须还在**"
  echo "   台账在跑 declared-batch（陈旧 2h、无进程持有，但台账 active）⇒ **必须还在**"
  echo "   新鲜批   fresh-batch（刚写过）⇒ 必须还在"
  echo "   根外哨兵 $sentinel ⇒ 必须原封不动"
  gc_run_local "$root" apply "$GC_SELFTEST_MIN_MB" "$GC_AGE_S" "" "$excl"
  [ -d "$root/done-batch" ] && { echo "FAIL 已完工批的构建盘仍在（应被回收）"; fail=1; }
  if [ ! -d "$root/running-batch" ]; then
    echo "FAIL 在跑批的构建盘被误删（红线：不许误删在跑的批的盘）"; fail=1
  fi
  if [ ! -d "$root/declared-batch" ]; then
    echo "FAIL 台账在跑的批的构建盘被误删（红线）"; fail=1
  fi
  [ -d "$root/fresh-batch" ] || { echo "FAIL 新鲜批的构建盘被误删"; fail=1; }
  [ -f "$sentinel" ] || { echo "FAIL 目标根外的文件被删（越界）"; fail=1; }
  kill "$holder" 2>/dev/null
  wait "$holder" 2>/dev/null
  rm -f "$sentinel"
  [ "$made" = "1" ] && rm -rf "$root"
  if [ "$fail" = "0" ]; then
    echo "SELFTEST_VERDICT=PASS（已完工批的盘消失；在跑批的盘还在；台账在跑的盘还在；新鲜批的盘还在；根外文件未动）"
    return 0
  fi
  echo "SELFTEST_VERDICT=FAIL"
  return 1
}

# --- 回收类模式分派（与外派流程互斥：这几个模式不需要任务书）---
case "${1:-}" in
  --reclaim)
    LBL="${2:-}"
    EXCL="$(gc_active_exclusions)" || { echo "WARN 台账不可证 ⇒ 拒绝回收（fail-closed）"; exit 4; }
    echo "== 远端构建盘回收（收卷即回收入口）=="
    echo "   目标机：$REMOTE   目标根：$REMOTE_TARGET_ROOT   定向：${LBL:-（全部合格目录）}"
    echo "   台账在跑保护：${EXCL:-（台账无 active 条目）}"
    if [ -n "$LBL" ]; then
      gc_run_remote "$REMOTE_TARGET_ROOT" apply "$GC_MIN_MB" "$GC_AGE_S" "$LBL" "$EXCL"
    else
      gc_run_remote "$REMOTE_TARGET_ROOT" apply "$GC_MIN_MB" "$GC_AGE_S" "" "$EXCL"
    fi
    rc=$?
    [ "$rc" -eq 0 ] && echo "OK 回收完成（远端执行；只删目标根下的可再生 target 目录）" \
                    || echo "WARN 远端回收未成功（rc=$rc）"
    exit "$rc"
    ;;
  --gc-dry-run)
    EXCL="$(gc_active_exclusions)" || { echo "WARN 台账不可证 ⇒ 拒绝盘点（fail-closed）"; exit 4; }
    echo "== 远端构建盘回收盘点（只读，不删）=="
    echo "   台账在跑保护：${EXCL:-（台账无 active 条目）}"
    gc_run_remote "$REMOTE_TARGET_ROOT" dry-run "$GC_MIN_MB" "$GC_AGE_S" "" "$EXCL"
    exit $?
    ;;
  --gc-selftest)
    echo "== 回收判据夹具自证（本地夹具，不碰远端）=="
    gc_selftest "${2:-}"
    exit $?
    ;;
esac

usage() {
  sed -n '2,32p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  exit 2
}

[ $# -ge 3 ] || usage
BRIEF="$1"
REMOTE_DIR="$2"
LABEL="$3"
REVIEW_BRIEF="${4:-}"

[ -f "$BRIEF" ] || { echo "FAIL 任务书不存在：$BRIEF"; exit 2; }
case "$BRIEF" in /*) BRIEF_ABS="$BRIEF";; *) BRIEF_ABS="$WS/$BRIEF";; esac

OFFDIR_REL=".offload"
LOG_REL="$OFFDIR_REL/$LABEL.log"

echo "== 外派：$LABEL =="
echo "   任务书：$BRIEF_ABS"
echo "   目标机：$REMOTE   基准工作目录：$REMOTE_DIR"

# 远端目录自检：不存在就建（只建这一个，不动别的）
ssh "${SSH_OPTS[@]}" "$REMOTE" "mkdir -p '$REMOTE_DIR/$OFFDIR_REL'" || {
  echo "FAIL 连不上 $REMOTE 或建目录失败"; exit 3; }

# **每个外派用自己的一棵工作树**——2026-11-04 实测教训：
# 两个外派共用同一棵工作树时会互相踩（一方切分支把另一方的在飞改动带走、
# 在活工作树里跑门会撞上对方半成品的编译错误）。故这里按 label 开独立 worktree。
WT_REL="wt/$LABEL"
WT_ABS="$REMOTE_DIR/$WT_REL"
# 基线取 **origin/product/main**（不是共享树的 HEAD——那棵树正被另一批切着分支）：
# 外派批一律从当前主线起步，合并期冲突最小。
# **2026-11-04 踩到两个坑，此处一并根治**：
# ① **共享库的 fetch 竞态**：两个外派批**并发**在同一共享库里 `git fetch` ⇒ 同一 ref 的
#    锁互相抢，报 "cannot lock ref 'refs/remotes/origin/product/main': is at X but expected Y"
#    ⇒ **一个批直接建树失败**（本次 main-verify-g6 就是这么死的）。
#    修法：fetch **用 flock 串行化**，且 fetch 与建树**放在同一条命令**里（同一把锁内）。
# ② **工作树必须落在目标基线上**：原实现恒 `worktree add --detach ... origin/product/main`，
#    于是**复核批的分支不在树上**——复核员看到的是主线而非待复核的分支
#    （本次 G4 复核重跑就落在主线 2542929 上，而 G4 在 feature/g4-k5-derived）。
#    修法：新增可选环境变量 **WF_OFFLOAD_BASE**（默认 origin/product/main）；
#    复核批把它设成待复核分支/基线 ref，树就落在正确的面上。
WF_BASE="${WF_OFFLOAD_BASE:-origin/product/main}"
# **③ 远端库可能是"窄 refspec"克隆**（2026-11-04 当场踩到）：
#   anolis 的共享库 \`remote.origin.fetch\` 只有
#   \`+refs/heads/product/main:refs/remotes/origin/product/main\` 一条
#   ⇒ \`git fetch origin\` **只更新 origin/product/main**，
#   \`origin/feature/*\` 这类**远端跟踪 ref 根本不存在** ⇒
#   \`worktree add --detach ... origin/feature/g4-k5-derived\` 报
#   "fatal: invalid reference: origin/feature/g4-k5-derived" ⇒ **批直接死**。
#   （该分支在共享库里**有本地分支** feature/g4-k5-derived 且指向正确提交，
#     缺的只是 remote-tracking ref ⇒ 不该重建、也不该错。）
#   修法：按需**显式补抓**目标 ref：把 \`origin/<branch>\` 换成
#   \`refs/heads/<branch>\` 形式的**直接 refspec 抓取**（+ 该 ref 的远端跟踪 ref），
#   抓不到时**回落到同名本地分支**，再不行才报错。
#   注意：本地分支**可能是旧的**（远端已被别人推新提交）⇒
#   **优先用显式抓取**，抓到的才是最新的。
WF_BRANCH="${WF_BASE#origin/}"
# 显式抓取目标分支（窄 refspec 下也能建出远端跟踪 ref）；抓不到则回落到本地同名分支
ssh "${SSH_OPTS[@]}" "$REMOTE" "cd '$REMOTE_DIR' && \
  git fetch -q origin \"+refs/heads/$WF_BRANCH:refs/remotes/origin/$WF_BRANCH\" 2>/dev/null || true" || true
# fetch 与建树在**同一把 flock** 内完成 ⇒ 并发批排队，不会互抢 ref 锁
ssh "${SSH_OPTS[@]}" "$REMOTE" "cd '$REMOTE_DIR' && \
  flock '$REMOTE_DIR/.git/wf-offload-fetch.lock' -c \"
    git fetch -q origin && \
    ([ -e '$WT_REL/.git' ] || git worktree add --detach '$WT_REL' '$WF_BASE') && \
    mkdir -p '$WT_ABS/$OFFDIR_REL'\"" || { echo "FAIL 建独立工作树失败"; exit 3; }
echo "   独立工作树：$WT_ABS（基线：$WF_BASE）"
# ★ 2026-11-05 接线批 ③①：批次**启动前**也扫一次回收（在磁盘闸之前——先收盘再判闸）
gc_preflight
# **每批独占构建盘**（2026-11-04 实测教训）：并发批共用一个 CARGO_TARGET_DIR 会读到
# **陈旧 rlib**，表现为 E0599 "can_decide not found" 之类的**假错**（源码在、符号不在）。
# 两个批（admit_seal / compiler-diagnostics）各踩过一次。故每批一个独占 target 根。
# 构建盘必须落 **/data**（家目录在根分区上、只剩 17G 且复核员实测在家目录重建 target 会撞满盘：
# 2026-11-04 compiler-diagnostics 复核段读到"根分区 100% 满 307MB avail"、ENOSPC）。
export REMOTE_TARGET_ROOT="${WF_TARGET_ROOT:-/data/bench/targets}"
ssh "${SSH_OPTS[@]}" "$REMOTE" "mkdir -p '$REMOTE_TARGET_ROOT/$LABEL'" || {
  echo "WARN 建独占构建盘失败，批次须自行用独占 CARGO_TARGET_DIR"; }
# 任务书与证据目录落在**独立工作树**里
WORK_DIR="$WT_ABS"

# 任务书送过去
scp -q "${SSH_OPTS[@]}" "$BRIEF_ABS" "$REMOTE:$WORK_DIR/$OFFDIR_REL/$(basename "$BRIEF_ABS")" || {
  echo "FAIL 任务书投递失败"; exit 3; }

# 跑门前**磁盘前置检查**（2026-11-04 第三次踩同一个坑的根治）：
# 满盘时链接器写不出输出文件 ⇒ cargo 报 "ld terminated with signal 7 [Bus error]"，
# 这与代码错误**长得完全不一样**但同样致命（假红）。低于 25G 一律先报，别让批白跑。
df_check() {
  local free_kb avail_g
  avail_g="$(ssh "${SSH_OPTS[@]}" "$REMOTE" "df -BG /data | tail -1 | awk '{print \$4}'" 2>/dev/null | tr -dc '0-9')"
  if [ -n "$avail_g" ] && [ "$avail_g" -lt 25 ]; then
    echo "DENY 远端 /data 仅剩 ${avail_g}G —— 低于 25G 门槛，满盘会让 cargo 报 \"ld terminated with signal 7\" 假红。"
    echo "     先清已收卷批的独占构建盘（/data/bench/targets/<label>）再跑本段；本段已跳过。"
    return 1
  fi
  echo "   远端 /data 可用 ${avail_g}G（门槛 25G）"
  return 0
}

# 段结束回收独占构建盘（源码已提交推送 ⇒ target 是可再生缓存）。
# 2026-11-04 实测：一份 af 全量 target 实测 19–52G，而 /data 只有 42G 余量 —— 不回收必然满盘假红。
#
# ★ 2026-11-05 接线批 ③：**回收动作改到远端执行**（原实现是**本地**函数对**远端**路径
#   做 stat/du/rm ⇒ 本机无该路径 ⇒ 恒空转 ⇒ 「已回收…」从未真发生，见文件头 ③ 段）。
#   判据见文件头 ③ 段（尺寸 8G 不动 + **无进程持有** + 树内写入龄）。
#   收尾两跳：
#     ① 本批独占盘＝**定向**回收（收卷即回收；树内写入龄免判——收卷是显式信号）；
#     ② 其它 label ＝ 全量回收（含树内写入龄门槛）。
gc_target() {
  echo "-- 段结束回收独占构建盘（远端执行）--"
  local excl
  excl="$(gc_active_exclusions)" || { echo "   WARN 台账不可证 ⇒ 本跳跳过（fail-closed）"; return 0; }
  gc_run_remote "$REMOTE_TARGET_ROOT" apply "$GC_MIN_MB" "$GC_AGE_S" "$LABEL" "$excl" || true
  gc_run_remote "$REMOTE_TARGET_ROOT" apply "$GC_MIN_MB" "$GC_AGE_S" "" "$excl" || true
}

# 批次**启动前**也扫一次回收（2026-11-05 接线批 ③①）：
#   同窗内先后完工的批，其构建盘会活过既有 1 小时门槛 ⇒ 开工前先收掉「已完工且
#   无人持有」的盘，/data 才不会一路涨到满盘假红（实测已两次触发）。
gc_preflight() {
  echo "-- 批次启动前回收（远端执行；先收盘再过磁盘闸）--"
  local excl
  excl="$(gc_active_exclusions)" || { echo "   WARN 台账不可证 ⇒ 本跳跳过（fail-closed）"; return 0; }
  gc_run_remote "$REMOTE_TARGET_ROOT" apply "$GC_MIN_MB" "$GC_AGE_S" "" "$excl" || true
}

run_one() {
  local remote_brief="$1" tag="$2"
  echo "-- 执行段 $tag --"
  # **磁盘闸必须在清日志之前判**（2026-11-04 当场踩到）：
  # 原实现先 `: > $LOG_REL` 清零日志、再跑 df_check；闸拒时该段根本没执行，
  # 日志却已被清空 ⇒ 事后只看到 0 字节日志，"跑过了但没输出"与"从未跑过"无法区分，
  # **施工段的证据也被一并抹掉**（G4 复核段即因此静默丢失）。
  # 现在：闸先判 ⇒ 通过才清零并执行；被拒则**在日志里写明拒绝原因**并保留既有日志。
  if ! df_check; then
    ssh "${SSH_OPTS[@]}" "$REMOTE" \
      "printf '\n===== 段 $tag 未执行：磁盘闸拒绝（远端 /data 可用 < 25G）=====\n' >> '$WORK_DIR/$LOG_REL'" || true
    echo "   段 $tag **未执行**（磁盘闸拒绝）——日志已标注，非静默丢失"
    return 3
  fi
  # 通过闸后才清日志——但**只清一次**（首个真正执行的段）：后续段追加到同一日志，
  # 施工段的过程证据不得被复核段清掉。
  if [ "$LOG_TRUNCATED" -eq 0 ]; then
    ssh "${SSH_OPTS[@]}" "$REMOTE" ": > '$WORK_DIR/$LOG_REL'" || true
    LOG_TRUNCATED=1
  fi
  ssh "${SSH_OPTS[@]}" "$REMOTE" \
    "cd '$WORK_DIR' && export PATH=\$HOME/.npm-global/bin:\$HOME/.cargo/bin:\$PATH && \
     export CARGO_TARGET_DIR='$REMOTE_TARGET_ROOT/$LABEL' && \
     zcode -p \"\$(cat '$remote_brief')\" --mode yolo --cwd '$WORK_DIR' --surface terminal \
       >> '$WORK_DIR/$LOG_REL' 2>&1"
  local rc=$?
  echo "   段 $tag 退出码：$rc"
  return $rc
}

LOG_TRUNCATED=0
RC=0
run_one "$WORK_DIR/$OFFDIR_REL/$(basename "$BRIEF_ABS")" "施工" || RC=$?

gc_target

if [ -n "$REVIEW_BRIEF" ]; then
  [ -f "$REVIEW_BRIEF" ] || { echo "FAIL 复核任务书不存在：$REVIEW_BRIEF"; exit 2; }
  case "$REVIEW_BRIEF" in /*) RB_ABS="$REVIEW_BRIEF";; *) RB_ABS="$WS/$REVIEW_BRIEF";; esac
  scp -q "${SSH_OPTS[@]}" "$RB_ABS" "$REMOTE:$WORK_DIR/$OFFDIR_REL/$(basename "$RB_ABS")" || RC=3
  run_one "$WORK_DIR/$OFFDIR_REL/$(basename "$RB_ABS")" "复核" || RC=$?
fi

# 日志拉回本机
mkdir -p "$WS/30-工件/外派/$LABEL"
scp -q "${SSH_OPTS[@]}" "$REMOTE:$WORK_DIR/$LOG_REL" "$WS/30-工件/外派/$LABEL/$LABEL.log" 2>/dev/null || true
echo "   日志：30-工件/外派/$LABEL/$LABEL.log"

if [ "$RC" -eq 0 ]; then
  echo "OK 外派完成：$LABEL"
else
  echo "WARN 外派有段失败（rc=$RC）：$LABEL —— 见日志"
fi
exit "$RC"
