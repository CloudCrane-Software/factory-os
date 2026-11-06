#!/usr/bin/env bash
# =============================================================================
# anolis-deploy-consistency-probe.sh — anolis 侧部署面一致性探针
#                              （all-gates.sh L5 部署一致性门 anolis 腿本体）
#
# 发现（2026-11-03 RT 确证，亲测）：anolis 侧部署面零常态版本对账机检——
#   ① all-gates.sh L1c 四件 anolis-only（burn-runner/image-pool-retire/swev-pool-gen/
#      setup-8b-anolis）每轮 SKIP「本机无」；live-daemon-version-probe 名册 6 件全是
#      本机守护；deploy-consistency-probe.sh 自述只对账 gov——六个门面（L1 SKIP/L2/
#      L3/L5/L6/在役版本对账门）无一覆盖 anolis 部署面。
#   ② 现势三件 sha256 对齐（burn-runner/swev-pool-gen/stream-tailer ≡ 本地 tools/）
#      系修复批一次性手工换码重启所致，非任何机检所系。
#   ③ 复发缝：调度器自愈拉起只执行**远端件**、不先 scp 本地件（tools/factory-scheduler.py
#      头注释 :43 与 DAEMONS start——「cd /data/bench && nohup python3 burn-runner.py」）
#      ⇒ 本地 tools/burn-runner.py 再改而 anolis 未同步、或 anolis 件换了未重启，
#      「修复落盘≠anolis 在役」复发无任何门能红——与 gov 侧 2026-11-02 收口前形态
#      同构（deploy-consistency-probe.sh 头注释：本地全绿与在役带洞并存）。
#
# 本探针＝那道缝的机检（只读：ssh 远端 sha256sum/stat/pgrep/readlink，零写入、
# 零换码、零重启）：
#
# 名册（判据源=本地 tools/ 正本 ↔ anolis 在位件；2026-11-03 实勘在位）：
#   burn-runner        tools/burn-runner.py        ↔ /data/bench/burn-runner.py          （常驻守护）
#   image-pool-retire  tools/image-pool-retire.py  ↔ /data/bench/image-pool-retire.py    （部署件）
#   swev-pool-gen      tools/swev-pool-gen.py      ↔ /data/bench/swev-pool-gen.py        （调度器 ssh 远端执行件）
#   stream-tailer      tools/stream-tailer.py      ↔ /data/bench/af-board/stream-tailer.py（常驻守护）
#
# 判定（collect-不短路，末了合并打印；**末行=结论行**，all-gates L5 取末行作 note）：
#   A 本地基准：四件本地正本在位（缺件=对账无基准，rc=2）
#   B 内容对账：在役件 sha256 ≡ 本地正本 sha256（附两侧 mtime 作漂移方向证据）；
#     在役缺件=红（rc=2）；sha 漂移=红（rc=1）——「本地改了没部署／在役被回退」都红
#   C 加载态：两常驻守护 pid 在位（pgrep 口径与 factory-scheduler 同款 + /proc/<pid>/exe
#     必须 *python*——探针远端命令行自带守护名，禁裸 pgrep 判在役，
#     live-daemon-version-probe.py:109「禁 pgrep -f 防自匹配」同款教训）；
#     不在役=红（rc=1；全局熔断 STOP 在位除外——见下）；启动时刻 < 在役件 mtime=红
#     （rc=1，换码未重启＝跑旧码）
#   全局熔断（tools/.factory-scheduler.STOP 在位）期间守护不在役=INFO 不判红
#     （熔断语义下「守护停」是预期态，恒红会训练人无视本门；熔断在位但守护在役
#     照常对账 B/C 的 sha 与加载态——停不停是熔断的事，跑哪版是对账的事）
#   ssh 不可达/回读缺行/坏数字=红（rc=2，在役面失去可对账性本身就是异常，不猜绿不静默）
#
# --selftest（判别力负向自测，**零触达真 anolis**）：沙箱注入桩 ssh 按夹具回放读数，
#   红路（sha 漂移／换码未重启／在役缺件／守护失联／不可达／读数坏）必红、
#   绿路对照必绿——钉住「本门能测出 anolis 部署面漂移」，防退化成恒绿真空门。
# =============================================================================
set -u
ANOLIS_SSH="anolis"
_HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WS="$(cd "$_HERE/.." && pwd)"
STOP_FILE="$WS/tools/.factory-scheduler.STOP"

# 名册：key|本地正本（相对 WS）|在役路径|类型（daemon=参与 C 腿加载态硬判）
ROSTER=(
  "burn-runner|tools/burn-runner.py|/data/bench/burn-runner.py|daemon"
  "image-pool-retire|tools/image-pool-retire.py|/data/bench/image-pool-retire.py|deployed"
  "swev-pool-gen|tools/swev-pool-gen.py|/data/bench/swev-pool-gen.py|deployed"
  "stream-tailer|tools/stream-tailer.py|/data/bench/af-board/stream-tailer.py|daemon"
)

REDS=()
DRIFT=""
drift_add() { if [ -z "$DRIFT" ]; then DRIFT="$1"; else DRIFT="$DRIFT；$1"; fi; }
is_num() { case "${1:-}" in ''|*[!0-9]*) return 1 ;; *) return 0 ;; esac; }
ts() { is_num "$1" && date -d @"$1" '+%m-%d %H:%M:%S' || echo "?"; }

main() {
  # ---- A 本地基准在位 ----
  local e key lrel rpath typ
  local -A LSHA=() LMT=() RPATH=() RTYP=()
  for e in "${ROSTER[@]}"; do
    IFS='|' read -r key lrel rpath typ <<<"$e"
    RPATH[$key]="$rpath"; RTYP[$key]="$typ"
    if [ ! -f "$WS/$lrel" ]; then
      echo "A红：本地基准缺件 $lrel——anolis 部署对账无基准（先恢复本地正本再对账，不猜绿）"
      exit 2
    fi
    LSHA[$key]="$(sha256sum "$WS/$lrel" | cut -d' ' -f1)"
    LMT[$key]="$(stat -c %Y "$WS/$lrel")"
  done

  # ---- 一次 ssh 拉回在役读数：四件 {sha256,mtime} + 两守护 {pid,启动时刻} ----
  local rem
  rem="$(ssh -o ConnectTimeout=10 -o BatchMode=yes "$ANOLIS_SSH" '
    for spec in "burn-runner:/data/bench/burn-runner.py" \
                "image-pool-retire:/data/bench/image-pool-retire.py" \
                "swev-pool-gen:/data/bench/swev-pool-gen.py" \
                "stream-tailer:/data/bench/af-board/stream-tailer.py"; do
      k="${spec%%:*}"; f="${spec#*:}"
      s="$(sha256sum "$f" 2>/dev/null | cut -d" " -f1)"
      m="$(stat -c %Y "$f" 2>/dev/null)"
      if [ -f "$f" ] && [ -n "$s" ] && [ -n "$m" ]; then
        echo "FILE|$k|$s|$m"
      else
        echo "FILE|$k|MISSING|-"
      fi
    done
    for spec in "burn-runne[r]:burn-runner" "stream-taile[r]:stream-tailer"; do
      pat="${spec%%:*}"; k="${spec#*:}"
      pid=""
      for c in $(pgrep -f "$pat"); do
        exe="$(readlink "/proc/$c/exe" 2>/dev/null)" || continue
        case "$exe" in *python*) pid="$c"; break ;; esac
      done
      st=""
      [ -n "$pid" ] && st="$(stat -c %Y "/proc/$pid" 2>/dev/null)"
      if [ -n "$pid" ] && [ -n "$st" ]; then
        echo "PROC|$k|$pid|$st"
      else
        echo "PROC|$k|NOPROC|-"
      fi
    done
  ')" || { echo "B红：ssh $ANOLIS_SSH 不可达——anolis 在役面无法对账（按红点名，不静默）"; exit 2; }

  local kind k a b
  local -A RSHA=() RMT=() RPID=() RPST=()
  while IFS='|' read -r kind k a b; do
    case "$kind" in
      FILE) RSHA[$k]="${a:-}"; RMT[$k]="${b:-}" ;;
      PROC) RPID[$k]="${a:-}"; RPST[$k]="${b:-}" ;;
    esac
  done <<<"$rem"

  UNPROV=0
  unprov() { UNPROV=1; echo "不可证：$1（不猜绿）"; }

  # ---- B 内容对账（四件） ----
  for e in "${ROSTER[@]}"; do
    IFS='|' read -r key lrel rpath typ <<<"$e"
    rsha="${RSHA[$key]:-}"
    if [ -z "$rsha" ]; then
      unprov "$key 在役读数缺行（回读不完整）"; continue
    fi
    if [ "$rsha" = "MISSING" ]; then
      # gov 探针同款口径（deploy-consistency-probe.sh D2 MISSING_FILE → 红 + rc=2）：
      # 在役面不完整＝对账不可证，红但归不可证码（部署一致性无法证明，不猜绿）
      REDS+=("B红：在役副本缺件 $rpath——在役面缺件须部署本地正本（tools/$lrel sha=${LSHA[$key]:0:8}…）并按类型重启")
      unprov "$key 在役副本缺件（对账面不完整）"
      drift_add "$key 在役缺件"
    elif [ "$rsha" != "${LSHA[$key]}" ]; then
      REDS+=("B红：$key sha256 不一致 本地=${LSHA[$key]:0:8}…(mtime $(ts "${LMT[$key]}")) 在役=${rsha:0:8}…(mtime $(ts "${RMT[$key]:-}"))——本地改了没部署／在役被回退，「修复落盘≠anolis 在役」复发；须同步部署$([ "$typ" = daemon ] && echo "并重启守护加载")")
      drift_add "$key 在役≠本地(sha 失配)"
    fi
  done

  # ---- C 加载态（两常驻守护） ----
  STOPPED=0
  [ -f "$STOP_FILE" ] && STOPPED=1
  for e in "${ROSTER[@]}"; do
    IFS='|' read -r key lrel rpath typ <<<"$e"
    [ "$typ" = "daemon" ] || continue
    rpid="${RPID[$key]:-}"
    if [ -z "$rpid" ]; then
      unprov "$key 守护读数缺行（回读不完整）"; continue
    fi
    if [ "$rpid" = "NOPROC" ]; then
      if [ "$STOPPED" = "1" ]; then
        echo "INFO：守护 $key 不在役，但全局熔断在位（$STOP_FILE）——停役属熔断预期态，判活面让位熔断，本门不判红（撤熔断后调度器自愈拉起即恢复硬判）"
      else
        REDS+=("C红：常驻守护 $key 不在役（远端 pgrep 候选经 /proc/<pid>/exe python 过滤后空）——在役面失联即红不放过；自愈拉起归调度器（factory-scheduler DAEMONS.start），须查拉起失败根因")
        drift_add "$key 守护失联"
      fi
      continue
    fi
    rpst="${RPST[$key]:-}"; rmt="${RMT[$key]:-}"
    if ! is_num "$rpst" || ! is_num "$rmt"; then
      unprov "$key 加载态读数坏（proc=$rpst mtime=$rmt 非纯数字）"; continue
    fi
    if [ "$rpst" -lt "$rmt" ]; then
      REDS+=("C红：$key 在役件已更新(mtime $(ts "$rmt"))但守护进程(pid=$rpid 启动 $(ts "$rpst"))早于落盘——换码未重启＝守护仍跑旧码，须重启加载")
      drift_add "$key 换码未重启"
    fi
  done

  # ---- 合并结论（末行=结论行，all-gates L5 取末行作 note） ----
  if [ "$UNPROV" = "1" ]; then
    if [ "${#REDS[@]}" -gt 0 ]; then printf '%s\n' "${REDS[@]}"; fi
    echo "结论：对账不可证（在役缺件/读数缺失/坏${DRIFT:+；}$DRIFT）——anolis 部署一致性无法证明，按红处置不猜绿"
    exit 2
  fi
  if [ "${#REDS[@]}" -gt 0 ]; then
    printf '%s\n' "${REDS[@]}"
    echo "结论：门红 ${#REDS[@]} 项——${DRIFT:-在对账中}；上列逐条为判据与实测"
    exit 1
  fi
  echo "OK：anolis 部署面一致——四件在役 sha256 ≡ 本地正本（burn-runner=${LSHA[burn-runner]:0:8}…/image-pool-retire=${LSHA[image-pool-retire]:0:8}…/swev-pool-gen=${LSHA[swev-pool-gen]:0:8}…/stream-tailer=${LSHA[stream-tailer]:0:8}…），两守护在役且启动≥在役件 mtime（burn-runner pid=${RPID[burn-runner]} stream-tailer pid=${RPID[stream-tailer]}）＝已加载生效$([ "$STOPPED" = 1 ] && echo "；全局熔断在位（守护在役照常对账）")"
  exit 0
}

# ---------------------------------------------------------------- 自测
selftest() {
  local SELF="$_HERE/anolis-deploy-consistency-probe.sh"
  # SB 不用 local：EXIT trap（rm -rf）在函数返回后触发，local 变量已出作用域（set -u 即炸）
  SB="$(mktemp -d "${TMPDIR:-/tmp}/anolis-deploy-selftest.XXXXXX")" || { echo "FATAL: mktemp 失败"; exit 2; }
  trap 'rm -rf "$SB"' EXIT

  # 桩 ssh：按 ANOLIS_PROBE_FIXTURE 回放夹具读数（UNREACHABLE → exit 255）
  cat > "$SB/ssh" <<'STUB'
#!/usr/bin/env bash
case "${ANOLIS_PROBE_FIXTURE:-}" in
  UNREACHABLE) exit 255 ;;
  "") echo "selftest 桩：ANOLIS_PROBE_FIXTURE 未设" >&2; exit 255 ;;
  *) cat "$ANOLIS_PROBE_FIXTURE" ;;
esac
STUB
  chmod +x "$SB/ssh"

  # 夹具生成器：基准值取自本地正本实时摘要/mtime（对账基准不抄死值）
  local e key lrel rpath typ
  local -A MT=() SHA=()
  for e in "${ROSTER[@]}"; do
    IFS='|' read -r key lrel rpath typ <<<"$e"
    MT[$key]="$(stat -c %Y "$WS/$lrel")"
    SHA[$key]="$(sha256sum "$WS/$lrel" | cut -d' ' -f1)"
  done
  mk_fx() { # $1=out $2=burn_sha $3=image_sha $4=swev_sha(MISSING=缺件) $5=tailer_sha
            # $6=burn_mtime $7=burn_proc $8=tailer_mtime $9=tailer_proc
    { printf 'FILE|burn-runner|%s|%s\n'        "$2" "$6"
      printf 'FILE|image-pool-retire|%s|%s\n'  "$3" "${MT[image-pool-retire]}"
      printf 'FILE|swev-pool-gen|%s|%s\n'      "$4" "${MT[swev-pool-gen]}"
      printf 'FILE|stream-tailer|%s|%s\n'      "$5" "$8"
      printf 'PROC|burn-runner|%s|%s\n'      "$([ "$7" = NOPROC ] && echo NOPROC || echo 101001)" "$7"
      printf 'PROC|stream-tailer|%s|%s\n'    "$([ "$9" = NOPROC ] && echo NOPROC || echo 202002)" "$9"
    } >"$1"
  }
  Z64="$(printf '%064d' 0)"
  mk_fx "$SB/green.txt"      "${SHA[burn-runner]}"  "${SHA[image-pool-retire]}" "${SHA[swev-pool-gen]}"  "${SHA[stream-tailer]}"  "${MT[burn-runner]}"  "$(( ${MT[burn-runner]} + 100 ))"  "${MT[stream-tailer]}"  "$(( ${MT[stream-tailer]} + 100 ))"
  mk_fx "$SB/shadrift.txt"   "$Z64"                 "${SHA[image-pool-retire]}" "${SHA[swev-pool-gen]}"  "${SHA[stream-tailer]}"  "${MT[burn-runner]}"  "$(( ${MT[burn-runner]} + 100 ))"  "${MT[stream-tailer]}"  "$(( ${MT[stream-tailer]} + 100 ))"
  mk_fx "$SB/staleproc.txt"  "${SHA[burn-runner]}"  "${SHA[image-pool-retire]}" "${SHA[swev-pool-gen]}"  "${SHA[stream-tailer]}"  "${MT[burn-runner]}"  "$(( ${MT[burn-runner]} + 100 ))"  "${MT[stream-tailer]}"  "$(( ${MT[stream-tailer]} - 100 ))"
  mk_fx "$SB/missing.txt"    "${SHA[burn-runner]}"  "${SHA[image-pool-retire]}"  "MISSING"               "${SHA[stream-tailer]}"  "${MT[burn-runner]}"  "$(( ${MT[burn-runner]} + 100 ))"  "${MT[stream-tailer]}"  "$(( ${MT[stream-tailer]} + 100 ))"
  mk_fx "$SB/noproc.txt"     "${SHA[burn-runner]}"  "${SHA[image-pool-retire]}" "${SHA[swev-pool-gen]}"  "${SHA[stream-tailer]}"  "${MT[burn-runner]}"  "NOPROC"                           "${MT[stream-tailer]}"  "$(( ${MT[stream-tailer]} + 100 ))"
  mk_fx "$SB/badread.txt"    "${SHA[burn-runner]}"  "${SHA[image-pool-retire]}" "${SHA[swev-pool-gen]}"  "${SHA[stream-tailer]}"  "not-a-number"        "$(( ${MT[burn-runner]} + 100 ))"  "${MT[stream-tailer]}"  "$(( ${MT[stream-tailer]} + 100 ))"

  ST_N=0; ST_OK=0
  st_case() { # $1=用例名 $2=期望rc $3=末行必含子串 $4=夹具（UNREACHABLE=不可达）
    local nm="$1" wantrc="$2" sub="$3" fx="$4" out rc note
    out="$(PATH="$SB:$PATH" ANOLIS_PROBE_FIXTURE="$fx" bash "$SELF" 2>&1)"; rc=$?
    note="$(printf '%s\n' "$out" | tail -1)"
    ST_N=$(( ST_N + 1 ))
    if [ "$rc" = "$wantrc" ] && case "$note" in *"$sub"*) true ;; *) false ;; esac; then
      echo "  [PASS] $nm → rc=$rc｜$note"
      ST_OK=$(( ST_OK + 1 ))
    else
      echo "  [FAIL] $nm → rc=$rc（期望 $wantrc）｜末行=$note（期望含「$sub」）"
      printf '%s\n' "$out" | head -6 | sed 's/^/       | /'
    fi
  }

  echo "=== anolis 部署一致性探针 · 判别力负向自测（桩 ssh 夹具，零触达真 anolis）==="
  st_case "绿路对照（四件≡本地+两守护已加载）→ 必绿 rc=0"   0 "OK：anolis 部署面一致"  "$SB/green.txt"
  st_case "红路1 在役 sha 漂移（本地新/在役旧）→ 必红 rc=1" 1 "在役≠本地"              "$SB/shadrift.txt"
  st_case "红路2 换码未重启（进程早于在役件）→ 必红 rc=1"   1 "换码未重启"              "$SB/staleproc.txt"
  st_case "红路3 在役副本缺件（gov D2 同款 rc=2）→ 必红"    2 "对账不可证"              "$SB/missing.txt"
  st_case "红路4 常驻守护失联 → 必红 rc=1"                  1 "守护失联"                "$SB/noproc.txt"
  st_case "红路5 ssh 不可达 → 必红 rc=2"                    2 "不可达"                  "UNREACHABLE"
  st_case "红路6 读数坏（mtime 非数字）→ 必红 rc=2"         2 "对账不可证"              "$SB/badread.txt"
  echo "SELFTEST_RESULT: $([ "$ST_OK" = "$ST_N" ] && echo PASS || echo FAIL)（$ST_OK/$ST_N 用例通过：红路必红、绿路必绿、不可证不猜绿）"
  [ "$ST_OK" = "$ST_N" ] || return 1
  return 0
}

case "${1:-}" in
  --selftest) selftest ;;
  "") main ;;
  -h|--help) sed -n '2,45p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 2 ;;
  *) echo "用法：$0 [--selftest]" >&2; exit 3 ;;
esac
