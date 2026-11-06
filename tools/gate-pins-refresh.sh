#!/usr/bin/env bash
# =============================================================================
# gate-pins-refresh.sh — 门本体钉桩重锚（改门 / 改探针 / 改钉值后的唯一合规动作）
#
# 契约（RT-CI门本体批）：钉桩面 tools/gate-pins.list 存三类权威值——
#   ① 门件件数下限（L2_MIN_ITEMS / L1_MIN_PY）：原先写在门本体里（tools/all-gates.sh
#      的硬编码常量），而 tools/ 与工作区根都不在任何 git 仓内 → 改它零版本面、
#      零完整性绑定（红队已确证发现）。现外置到钉桩文件。
#   ② 子探针/子自测件的 sha256（探针被改成恒 exit 0 即红）。
#   ③ 门本体自身的 sha256（改门即改钉值：改门后不重锚 → 钉桩对账红）。
# 本脚本做四件事（顺序不可换）：
#   ① 重算钉桩文件内每个 sha256 行的实时摘要并就地更新（就地改，不新增行）；
#   ② 重算钉桩文件自身摘要 + 门本体摘要 → 追加变更日志登记行
#      （登记串：tools/gate-pins.list sha256=<64hex>；tools/all-gates.sh sha256=<64hex>）
#      ——tools/ 唯一的版本面（RT-E84④ 同款口径：改动须登记留痕，不留痕即红）；
#   ③ 更新**工作区之外**的外置锚（默认 $HOME/all-gates-logs/gate-pins.anchor）：
#      登记面在工作区内、同权者可自签「改钉值 + 自签登记行」自洽；外置锚在工作区
#      之外 ⇒ 工作区内的攻击链改不到它，失配即红；
#   ④ 调 tools/gate-pins-check.sh 复验（红则本脚本 exit 1，不掩盖）。
#
# 用法：bash tools/gate-pins-refresh.sh [--reason "一句话理由"]
# 退出码：0=重锚完成且复验全绿；1=复验有红；2=用法/环境错误。
# =============================================================================
set -u

WS="${GATE_PINS_WS:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
TOOLS="$WS/tools"
PINS="$TOOLS/gate-pins.list"
CLOG="$WS/计划/变更日志.md"

REASON=""
while [ $# -gt 0 ]; do
  case "$1" in
    --reason) shift; REASON="${1:-}" ;;
    -h|--help) sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 2 ;;
    *) echo "未知参数：$1" >&2; exit 2 ;;
  esac
  shift
done

command -v sha256sum >/dev/null 2>&1 || { echo "FATAL: 缺 sha256sum" >&2; exit 2; }
[ -f "$PINS" ] || { echo "FATAL: 钉桩文件不在位：$PINS" >&2; exit 2; }
[ -f "$CLOG" ] || { echo "FATAL: 变更日志不在位：$CLOG" >&2; exit 2; }

echo "=== 门本体钉桩重锚 ==="
echo "工作区：$WS"
echo "钉桩文件：$PINS"

TMP="$(mktemp "${TMPDIR:-/tmp}/gate-pins-refresh.XXXXXX")" || { echo "FATAL: mktemp 失败" >&2; exit 2; }
trap 'rm -f "$TMP"' EXIT

n=0
while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in
    "sha256 "*)
      rel="$(printf '%s\n' "$line" | awk '{print $2}')"
      if [ ! -f "$WS/$rel" ]; then
        echo "FATAL: 被验件不在位：$rel——无法重锚（先确认该件是否下线；下线则从钉桩文件删行）" >&2
        exit 1
      fi
      new="$(sha256sum "$WS/$rel" | cut -d' ' -f1)"
      printf 'sha256 %s %s\n' "$rel" "$new" >>"$TMP"
      echo "  重锚：$rel → ${new:0:12}…"
      n=$(( n + 1 ))
      ;;
    *)
      printf '%s\n' "$line" >>"$TMP"
      ;;
  esac
done <"$PINS"

if [ "$n" = "0" ]; then
  echo "FATAL: 钉桩文件内无 sha256 行，无可重锚对象" >&2
  exit 1
fi

cat "$TMP" >"$PINS" || { echo "FATAL: 钉桩文件写回失败" >&2; exit 1; }
psha="$(sha256sum "$PINS" | cut -d' ' -f1)"
gsha="$(sha256sum "$TOOLS/all-gates.sh" 2>/dev/null | cut -d' ' -f1)"
l2min="$(sed -n 's/^L2_MIN_ITEMS=//p' "$PINS" | head -1)"
l1min="$(sed -n 's/^L1_MIN_PY=//p' "$PINS" | head -1)"

TS="$(date '+%Y-%m-%d %H:%M')"
{
  printf '| %s | CI门族修复员 | 门本体钉桩重锚 | ' "$TS"
  printf 'tools/gate-pins.list sha256=%s；tools/all-gates.sh sha256=%s' "$psha" "$gsha"
  printf '；钉桩面现势：L2_MIN_ITEMS=%s L1_MIN_PY=%s；重锚件 %s 件 | ' "$l2min" "$l1min" "$n"
  printf '钉桩登记串（RT-CI门本体批：门内钉值外置 + 子探针摘要绑定 + 门本体版本面留痕）'
  [ -n "$REASON" ] && printf '；重锚原因：%s' "$REASON"
  printf ' |\n'
} >>"$CLOG"
echo "  登记：变更日志已追加（tools/gate-pins.list sha256=${psha:0:12}… / tools/all-gates.sh sha256=${gsha:0:12}…）"

# --- 外置锚（工作区之外）：登记面在工作区内可自签，此锚不可 ---
ANCHOR="${GATE_PINS_ANCHOR:-${HOME:+$HOME/all-gates-logs/gate-pins.anchor}}"
if [ -z "$ANCHOR" ]; then
  echo "FATAL: 外置锚不可定位（GATE_PINS_ANCHOR 未设且 HOME 未设）——无法重锚" >&2
  exit 2
fi
mkdir -p "$(dirname "$ANCHOR")" || { echo "FATAL: 外置锚目录创建失败：$(dirname "$ANCHOR")" >&2; exit 2; }
{
  printf '# 门本体钉桩外置锚（工作区之外；工作区内的登记面可自签，此锚不可）\n'
  printf '# 生成：bash tools/gate-pins-refresh.sh（改钉值/改门/改探针后重锚的唯一合规动作）\n'
  printf 'gate-pins.list sha256=%s\n' "$psha"
  printf 'all-gates.sh sha256=%s\n' "$gsha"
  printf 'pinned_at=%s\n' "$(date -Iseconds)"
} >"$ANCHOR" || { echo "FATAL: 外置锚写入失败：$ANCHOR" >&2; exit 2; }
echo "  外置锚已更新：$ANCHOR"

echo "--- 复验 ---"
bash "$TOOLS/gate-pins-check.sh"
rc=$?
if [ "$rc" = "0" ]; then
  echo "REFRESH_RESULT: PASS（重锚 $n 件 + 登记留痕 + 复验全绿）"
  exit 0
fi
echo "REFRESH_RESULT: FAIL（重锚 $n 件但复验红 rc=$rc）"
exit 1
