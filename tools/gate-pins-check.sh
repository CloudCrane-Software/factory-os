#!/usr/bin/env bash
# =============================================================================
# gate-pins-check.sh — 门本体钉桩完整性对账（all-gates.sh L3 门常驻项）
#
# 缺口（2026-11-03 RT-CI门本体批，红队已确证发现）：
#   tools/ 与工作区根都不在任何 git 仓内（git -C tools rev-parse → fatal），
#   故「门面 diff 即见」不成立；而门本体与它调用的子探针既无 sha256 摘要钉桩、
#   也无任何机检消费其摘要——门内钉值（L2_MIN_ITEMS / L1_MIN_PY）与探针本体
#   都是「谁改都行、没人看得见」的无版本面资产。攻击链（结构推演）：
#   改门内钉值 + 删 test-*.py + 删清单行 + 下调清单声明 + 追加一行变更日志登记
#   → RT-E84②③ 两侧对账同时通过、exit=0；或把任一探针改成恒 exit 0 → 全门无
#   一处能红。
#
# 本对账门（只读、零改动、fail-closed）钉住五件事：
#   ① 钉桩文件自身摘要已登记在 计划/变更日志.md（登记串：gate-pins.list sha256=<64位hex>）
#      ——即 tools/ 唯一的版本面（RT-E84④ 同款口径：清单改动须登记留痕）；
#   ② 门本体 all-gates.sh 当前摘要已登记在变更日志（登记串：all-gates.sh sha256=<64位hex>）
#      ——给门本体补上版本面：改门必须留痕，不留痕即红；
#   ③ 钉桩文件里每个 sha256 行与被验件的**实时**摘要一致（探针被改、门本体被改、
#      钉桩被改而未同步 → 红）；
#   ④ 钉桩文件里的两个件数下限可解析为正整数（钉值不可读 ⇒ 门无从对账 ⇒ 红）；
#   ⑤ 钉桩文件摘要与**工作区之外**的外置锚一致（默认 $HOME/all-gates-logs/gate-pins.anchor，
#      可用 GATE_PINS_ANCHOR 覆盖）——登记面（变更日志）在工作区内，同权者可自签；
#      外置锚在工作区之外 ⇒ 「改钉值 + 删件 + 删清单行 + 下调声明 + 追加登记行」
#      这条**全工作区内**的攻击链到此为止（外置锚失配 ⇒ 红）。
#
# 失败一律 exit 1（红）；环境性错误（sha256sum 不可用等）exit 2（不可证不猜绿）。
# 本件是门本体**之外**的独立对账面：改门本体删掉本项调用也不会让「钉桩对账」变绿
# ——因为摘要/登记判据在另一个文件里。
#
# 用法：bash tools/gate-pins-check.sh
#   环境变量 GATE_PINS_WS=… 可指定被验工作区根（沙箱负控自测用；缺省=本脚本上级目录）。
#   环境变量 GATE_PINS_ANCHOR=… 可指定外置锚文件（缺省=$HOME/all-gates-logs/gate-pins.anchor）。
# 退出码：0=全绿；1=有红；2=用法/环境错误。
# =============================================================================
set -u

WS="${GATE_PINS_WS:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
TOOLS="$WS/tools"
PINS="$TOOLS/gate-pins.list"
CLOG="$WS/计划/变更日志.md"
ANCHOR="${GATE_PINS_ANCHOR:-${HOME:+$HOME/all-gates-logs/gate-pins.anchor}}"

NF=0
ok()  { echo "  [OK]   $1"; }
bad() { echo "  [FAIL] $1"; NF=$(( NF + 1 )); }
die() { echo "FATAL: $1" >&2; exit 2; }

command -v sha256sum >/dev/null 2>&1 || die "缺 sha256sum，本对账不可执行（不可证不猜绿）"

sha_of() { # $1=文件 → 打印 64 位摘要（失败则空）
  [ -f "$1" ] || return 1
  sha256sum "$1" 2>/dev/null | cut -d' ' -f1
}

pin_get() { # $1=键 → 打印值（读不到则空）
  [ -f "$PINS" ] || return 1
  sed -n "s/^$1=//p" "$PINS" 2>/dev/null | head -1
}

echo "=== 门本体钉桩完整性对账（gate-pins）==="
echo "工作区：$WS"
echo "钉桩文件：$PINS"

# --- 0 钉桩文件在位（fail-closed：缺件即红，不得回退到门内钉值）---
if [ ! -f "$PINS" ]; then
  bad "钉桩文件不在位（$PINS）——门内钉值与子探针摘要无权威面（RT-CI门本体）"
  echo "SELFTEST_RESULT: FAIL（钉桩文件缺失——钉桩对账不可证不猜绿）"
  exit 1
fi
ok "钉桩文件在位"

psha="$(sha_of "$PINS")"
[ -n "$psha" ] || die "无法计算钉桩文件摘要（sha256sum 失败）"

# --- 1 格式与钉值可解析性 ---
if [ "$(pin_get PINS_FORMAT)" = "1" ]; then
  ok "钉桩文件格式标记 PINS_FORMAT=1 在位"
else
  bad "钉桩文件缺 PINS_FORMAT=1 标记（读到 '$(pin_get PINS_FORMAT)'）——格式漂移不可证"
fi

l2min="$(pin_get L2_MIN_ITEMS)"
l1min="$(pin_get L1_MIN_PY)"
for kv in "L2_MIN_ITEMS=$l2min" "L1_MIN_PY=$l1min"; do
  k="${kv%%=*}"; v="${kv#*=}"
  case "$v" in
    ''|*[!0-9]*) bad "$k 不可解析为正整数（读到 '${v}'）——件数下限无从对账" ;;
    0)         bad "$k 为 0——件数下限形同虚设" ;;
    *)         ok "$k=$v（可解析）" ;;
  esac
done

# --- 2 变更日志在位（登记面）---
if [ ! -f "$CLOG" ]; then
  bad "变更日志不在位（$CLOG）——钉桩/门本体改动零留痕面可审计"
else
  ok "变更日志在位（登记面）"

  # --- 3 钉桩文件摘要须已登记（RT-E84④ 同款口径）---
  if grep -qF "gate-pins.list sha256=$psha" "$CLOG" 2>/dev/null; then
    ok "钉桩文件 sha256=${psha:0:12}… 已登记在变更日志（留痕在位）"
  else
    bad "钉桩文件 sha256=$psha 未登记在变更日志——钉桩被改动但未留痕（登记串：gate-pins.list sha256=$psha）"
  fi

  # --- 4 门本体摘要须已登记（门本体版本面：改门必须留痕）---
  gsha="$(sha_of "$TOOLS/all-gates.sh")"
  if [ -z "$gsha" ]; then
    bad "无法计算门本体 sha256（tools/all-gates.sh 不在位或不可读）——门本体零完整性绑定"
  elif grep -qF "all-gates.sh sha256=$gsha" "$CLOG" 2>/dev/null; then
    ok "门本体 sha256=${gsha:0:12}… 已登记在变更日志（改门留痕在位）"
  else
    bad "门本体 sha256=$gsha 未登记在变更日志——门本体被改动但未留痕（登记串：all-gates.sh sha256=$gsha）"
  fi
fi

# --- 4b 外置锚（工作区之外）须与钉桩摘要一致 ---
# 登记面（计划/变更日志.md）在工作区内 ⇒ 同权者可「改钉值 + 自签登记行」自洽；
# 外置锚在工作区之外（$HOME/all-gates-logs/），工作区内的攻击链改不到它。
if [ -z "$ANCHOR" ]; then
  bad "外置锚不可定位（GATE_PINS_ANCHOR 未设且 HOME 未设）——工作区内的自签登记无法被外部锚证伪（fail-closed）"
elif [ ! -f "$ANCHOR" ]; then
  bad "外置锚不在位（$ANCHOR）——钉桩面无工作区之外的锚（跑 bash tools/gate-pins-refresh.sh 重锚）"
elif grep -qF "gate-pins.list sha256=$psha" "$ANCHOR" 2>/dev/null; then
  ok "外置锚一致（$ANCHOR）：钉桩 sha256=${psha:0:12}…（工作区外锚证伪）"
else
  bad "外置锚失配（$ANCHOR）——钉桩面被改动但工作区之外的锚未更新：登记面在工作区内可自签，此锚不可（跑 bash tools/gate-pins-refresh.sh 重锚）"
fi

# --- 5 逐件摘要对账（钉桩里的每个 sha256 行 vs 实时摘要）---
nchk=0
while read -r kind rel want _rest; do
  [ "$kind" = "sha256" ] || continue
  [ -n "${rel:-}" ] || continue
  nchk=$(( nchk + 1 ))
  case "${want:-}" in
    ''|*[!0-9a-f]*)
      bad "钉桩行格式非法：sha256 $rel ${want:-<空>}（期望 64 位小写 hex）"
      continue ;;
  esac
  if [ ${#want} -ne 64 ]; then
    bad "钉桩行摘要长度异常：sha256 $rel $want（期望 64 位）"
    continue
  fi
  live="$(sha_of "$WS/$rel")"
  if [ -z "$live" ]; then
    bad "被验件不在位或不可读：$rel——摘要无从对账（不可证不猜绿）"
  elif [ "$live" = "$want" ]; then
    ok "摘要一致：$rel"
  else
    bad "摘要漂移：$rel 实时=${live:0:12}… 钉桩=${want:0:12}…——件被改过（改门/改探针须同步重锚：bash tools/gate-pins-refresh.sh）"
  fi
done <"$PINS"
if [ "$nchk" = "0" ]; then
  bad "钉桩文件内无任何 sha256 行——钉桩面形同虚设"
else
  ok "摘要对账 $nchk 件"
fi

if [ "$NF" = "0" ]; then
  echo "SELFTEST_RESULT: PASS（钉桩完整性对账全绿：登记在位 + 摘要一致 + 钉值可解析）"
  exit 0
fi
echo "SELFTEST_RESULT: FAIL（$NF 项红——钉桩/门本体/子探针的完整性绑定有洞）"
exit 1
