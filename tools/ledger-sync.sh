#!/usr/bin/env bash
# =============================================================================
# ledger-sync.sh — 账本同步腿（登记→planner 可见）· 夜轨C3-20261107
#
# 断点4闭合件：登记权威面=org 工作区 计划/阶段欠账台账.md（至 D-116），规划环
# 锚宇宙=factory-os 仓 账本/阶段欠账台账.md（2026-11-07 04 时止 D-68）——
# 「登记→planner 可见」此前无同步腿（夜轨C2 演练断点4，04:00 轮实证 planner
# 零新卡）。本件定时把正本欠账行同步到仓内账本，令规划环可见。
#
# 纪律（夜轨C3 ask 原文锚定，逐条落码）：
#   ① 只增不改：diff 只许「追加行+状态列变更」，禁删改既有行——append-only
#     对账（同步前后行数与既有行 sha 逐行比对；既有行前 5 格逐字节比对）不过
#     即拒推（fail-closed）。
#   ② SCRUB 必过门：一切推送面（合并后账本全文＋同步腿本体＋提交题/体＋PR
#     题/体）先本地 bot-scrub 预扫（内核=同仓 tools/mirror-disclose.sh 内嵌
#     scan_text/scan_g13，与 gates.yml 剖面②同源同形），0 命中才继续。
#     豁免面=账本零豁免（仓内 allowlist 条目全部为 tools/ 件，账本任何命中
#     不可豁免——严于 CI 口径的安全侧）。P-04（内网 CGNAT 100.64/10 段）命中
#     于「正本来源行」时只机械脱敏该 span 并三面留痕（sync-log＋PR 体＋run
#     报告），其余任一模式命中一律硬拒（不自动脱敏——凭据形态须人工处置）。
#   ③ 幂等：无 diff ⇒ 零动作零 PR（cron 噪声禁令），留痕一行 no-diff 即退。
#   ④ 凭据：PAT 经 ~/.local/bin/af-github-askpass 现取（不落盘/不回显）；git
#     推拉与 API 走 gov 代理（凭据行现解码，不回显）；PR 开门/推分支用
#     Repo-Writer App installation token（openBao 现取→JWT→installation
#     access token，只进 600 临时文件，shred 清除）。
#   ⑤ 合线：App 开门 PR ＋ PAT（feasy898，/账本/ 与 /tools/ 判官路径 owner）
#     APPROVE ＋ PUT /pulls/{n}/merge squash（合并端点=PUT 非 POST）。
#   ⑥ 判据/判官件零改动：本件不写 tools/ 既有件、不写 allowlist、不写
#     gates.yml/planner.yml（新增件仅本件自身）。
#
# 用法：
#   ledger-sync.sh                  # 全流程（cron 形态；单例锁）
#   ledger-sync.sh --dry-run        # 推送前止步（fetch 只读；负例/验证用）
#   ledger-sync.sh --scrub-only F   # 只跑 scrub 门于文件 F（0 命中 rc=0）
#   ledger-sync.sh --selftest       # 内置自证（引擎/脱敏/对账/负例，零网络）
#
# 环境覆盖（测试钩子；缺省=生产路径）：
#   LEDGER_SYNC_SOURCE  正本账本路径（负例测试指向临时副本）
#   LEDGER_SYNC_LOG     同步留痕（30-工件/夜轨C3-20261107/sync-log.md）
#   LEDGER_SYNC_WORK    工作区（克隆/锁/run 证据目录）
# 退出码：0 成功（含 no-diff）；2 结构/参数错；3 scrub 拦截；4 append-only
#         对账不过；5 网络/API 失败；6 gates 未绿；10 自证失败。
# =============================================================================
set -euo pipefail
umask 077
export PATH="/home/pan-ding/.local/bin:/usr/local/bin:/usr/bin:/bin"

WS_ROOT="/home/pan-ding/workspace/agent黑灯工厂"
REPO_SLUG="CloudCrane-Software/factory-os"
SRC_LEDGER="${LEDGER_SYNC_SOURCE:-$WS_ROOT/计划/阶段欠账台账.md}"
SYNC_LOG="${LEDGER_SYNC_LOG:-$WS_ROOT/30-工件/夜轨C3-20261107/sync-log.md}"
WORK="${LEDGER_SYNC_WORK:-/home/pan-ding/ledger-sync}"
CLONE="$WORK/factory-os-clone"
LOCK="$WORK/.ledger-sync.lock"
SCRIPT_PATH="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
MODE="run"
DRY=0

case "${1:-}" in
  "") ;;
  --dry-run) DRY=1 ;;
  --scrub-only) MODE="scrub-only"; SCRUB_TARGET="${2:?--scrub-only 需要文件参数}" ;;
  --selftest) MODE="selftest" ;;
  *) echo "未知参数: $1（用法见件头）" >&2; exit 2 ;;
esac

now_ts() { date '+%F %T %z'; }

log_append() {  # $1=条目文本（多行）；追加进 sync-log.md（append-only 留痕）
  mkdir -p "$(dirname "$SYNC_LOG")"
  { echo ""; echo "## $(now_ts) · ledger-sync"; echo "$1"; } >> "$SYNC_LOG"
}

# ---- 代理：git-credentials 里 %3a7890 行现解码（禁回显）--------------------
proxy_url() {
  python3 -I - <<'PYEOF'
import re, urllib.parse, os
line = None
for l in open(os.path.expanduser('~/.git-credentials'), encoding='utf-8'):
    if '%3a7890' in l.lower():
        line = l.strip(); break
assert line, 'gov 代理凭据行缺席'
m = re.match(r'^(https?)://([^:@/]*):([^@]*)@(.*)$', line)
assert m, '凭据行形态异常'
scheme, user, pw, host = m.groups()
print(f"{scheme}://{user}:{pw}@{urllib.parse.unquote(host)}", end='')
PYEOF
}

# ---- 凭据文件原子写入（600，用后 shred）------------------------------------
secret_to_file() {  # 值经 stdin 传入；$1=目标文件
  cat > "$1"
  chmod 600 "$1"
}

# ---- 引擎（python3 -I，子命令见 --selftest）--------------------------------
engine() {  # engine <subcommand> [args...]  （SDK：内核提取自 mirror-disclose.sh）
  python3 -I - "$SCRIPT_PATH" "$@" <<'PYENGINE'
import ast, bisect, hashlib, json, os, re, sys

SCRIPT_PATH = sys.argv[1]
ARGS = sys.argv[2:]
TOOLS_DIR = os.path.dirname(SCRIPT_PATH)
MIRROR = os.path.join(TOOLS_DIR, "mirror-disclose.sh")

# ---- scan 内核：AST 切出 mirror-disclose.sh 内嵌 PYEOF 段的 scan_text/scan_g13
# 取法照抄 bot-scrub.py load_scan_text()（gates.yml 剖面②同源），只执行两个
# def 及其依赖闭包，不跑 git/argparse/main 逻辑。
def load_kernel(mirror_path):
    lines = open(mirror_path, encoding="utf-8").readlines()
    start = next(i for i, l in enumerate(lines) if "<<'PYEOF'" in l)
    end = next(i for i, l in enumerate(lines) if i > start and l.strip() == "PYEOF")
    src = "".join(lines[start + 1:end])
    tree = ast.parse(src, filename=mirror_path + "#embedded")
    wanted = {"scan_text", "scan_g13"}
    defs, assigns = {}, {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            defs[node.name] = node
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    assigns.setdefault(t.id, node)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            assigns.setdefault(node.target.id, node)
    BUILTINS = {"re", "bisect", "os", "sys", "json", "str", "len", "sorted", "set",
                "bytes", "int", "min", "max", "range", "sum", "open", "print",
                "enumerate", "isinstance", "dict", "list", "tuple", "any", "all",
                "zip", "map", "filter", "abs", "repr", "format", "True", "False",
                "None", "Exception", "ValueError", "TypeError"}
    def load_names(node):
        return {x.id for x in ast.walk(node)
                if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Load)}
    selected, frontier = set(), set(wanted)
    while frontier:
        name = frontier.pop()
        if name in selected:
            continue
        selected.add(name)
        node = defs.get(name) or assigns.get(name)
        if node is None:
            continue
        for g in load_names(node):
            if g not in selected and g not in BUILTINS and (g in defs or g in assigns):
                frontier.add(g)
    order = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in selected:
            order[node.name] = node
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id in selected:
                    order[t.id] = node
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) \
                and node.target.id in selected:
            order[node.target.id] = node
    ns = {"__builtins__": __builtins__, "re": re, "bisect": bisect}
    exec(compile(ast.Module(body=list(order.values()), type_ignores=[]),
                 "<mirror-embedded>", "exec"), ns)
    return ns

K = load_kernel(MIRROR)
scan_text = K["scan_text"]
COMPILED_N = len(K["COMPILED"])
P04 = "P-04"

# ---- 行/格解析（逃逸 \| 感知）----------------------------------------------
def cells(line):
    out, buf, esc, started = [], [], False, False
    for ch in line:
        if esc:
            buf.append("\\" + ch); esc = False; continue
        if ch == "\\":
            esc = True; continue
        if ch == "|":
            out.append("".join(buf)); buf = []; started = True; continue
        buf.append(ch)
    out.append("".join(buf))
    return out if started else None

def boundaries(line):
    idx, esc = [], False
    for i, ch in enumerate(line):
        if esc:
            esc = False; continue
        if ch == "\\":
            esc = True; continue
        if ch == "|":
            idx.append(i)
    return idx

def row_id_of(line):
    if not line.startswith("|"):
        return None
    b = boundaries(line)
    if len(b) < 7:      # 引导|+6 格至少 7 个未逃逸竖线
        return None
    c = cells(line)
    rid = c[1].strip() if c and len(c) > 1 else ""
    if not rid or rid.startswith("-") or rid == "编号":
        return None
    return rid

def row_prefix(line):
    """既有行禁改区=前 5 格（编号…批次归属，含其定界竖线）；状态列=第 6 格起。"""
    b = boundaries(line)
    if len(b) < 7:
        return None
    return line[:b[5]]

# ---- P-04 机械脱敏（唯一自动脱敏模式；span 级，行内逐 span）-----------------
P04_RX = re.compile(r"\b100\.0*(?:6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\.\d{1,3}\.\d{1,3}\b")
REDACT_MARK = "[内网地址P-04已脱敏]"

def redact_p04(text):
    out, n = P04_RX.subn(REDACT_MARK, text)
    return out, n

# ---- scrub 门（账本面零豁免：allowlist 条目全为 tools/ 件，命中即红）---------
def scan_file(path, redact=False):
    text = open(path, encoding="utf-8").read()
    rep = {"file": path, "scanned_chars": len(text), "hits": [],
           "redactions": [], "verdict": "clean"}
    lines = text.splitlines()
    def _span_of(pid, line):
        if pid == P04:
            m = P04_RX.search(line)
            return m.group(0) if m else ""
        return ""
    hits = [{"pattern": pid, "line": ln, "span": _span_of(pid, lines[ln - 1])}
            for pid, ln in scan_text(text)]
    rep["hits"] = hits
    if not hits:
        rep["verdict"] = "clean"
        return rep
    if not redact:
        rep["verdict"] = "block"
        return rep
    # 仅 P-04 允许机械脱敏；其余模式出现即整体硬拒
    non_p04 = [h for h in hits if h["pattern"] != P04]
    if non_p04:
        rep["verdict"] = "block"
        rep["block_reason"] = "非 P-04 命中（凭据形态不得自动脱敏，须人工处置）"
        return rep
    new_lines, red_n, cur = [], 0, 1
    for ln in sorted({h["line"] for h in hits}):
        new_lines.extend(lines[cur - 1:ln - 1])
        old = lines[ln - 1]
        new, n = redact_p04(old)
        red_n += n
        rep["redactions"].append({"line": ln, "pattern": P04,
                                  "before": old, "after": new})
        new_lines.append(new)
        cur = ln + 1
    new_lines.extend(lines[cur - 1:])
    new_text = "\n".join(new_lines)
    if text.endswith("\n") and not new_text.endswith("\n"):
        new_text += "\n"
    rep["redaction_count"] = red_n
    rep["rescan_hits"] = [{"pattern": p, "line": l} for p, l in scan_text(new_text)]
    if rep["rescan_hits"]:
        rep["verdict"] = "block"
        rep["block_reason"] = "脱敏后仍命中（不得放行）"
        return rep
    rep["hits_before_redact"] = rep["hits"]
    rep["hits"] = []
    rep["redacted_text"] = new_text
    rep["verdict"] = "clean"
    return rep

# ---- 计划：工作区正本 vs 仓内基线 → 追加/状态列变更/禁改区比对 ---------------
def make_plan(source_path, base_path):
    """对账基准=正本的 P-04 脱敏投影（推送面投影函数确定性；逐 span 留痕于
    projection_redactions；正本本身零改动）。既有行禁改区比对亦以投影面为准——
    否则基线内已投影行（如 D-114）与正本原文将永久禁改区失配。"""
    ws_raw = open(source_path, encoding="utf-8").read().splitlines()
    ws, projection_redactions = [], []
    for i, l in enumerate(ws_raw):
        new, n = redact_p04(l)
        if n:
            projection_redactions.append({"source_lineno": i + 1, "count": n,
                                          "pattern": P04, "before": l, "after": new})
        ws.append(new)
    base = open(base_path, encoding="utf-8").read().splitlines()
    plan = {"source": source_path, "base": base_path,
            "base_lines": len(base), "source_lines": len(ws),
            "projection_redactions": projection_redactions,
            "appends": [], "status_updates": [], "forbidden": [],
            "verdict": "ok"}
    base_ids, base_idx = [], {}
    for i, l in enumerate(base):
        rid = row_id_of(l)
        if rid:
            if rid in base_idx:
                plan["forbidden"].append(f"基线行 {i+1} 重复编号 {rid}")
                plan["verdict"] = "block"; return plan
            base_ids.append(rid); base_idx[rid] = i
    ws_pos = {}
    ws_rows = []
    for i, l in enumerate(ws):
        rid = row_id_of(l)
        if rid:
            if rid in ws_pos:
                plan["forbidden"].append(f"正本行 {i+1} 重复编号 {rid}")
                plan["verdict"] = "block"; return plan
            ws_pos[rid] = i
            ws_rows.append(rid)
    # 基线行序必须是正本行序的子序列（禁改行序）
    it = iter(ws_rows)
    for rid in base_ids:
        for w in it:
            if w == rid:
                break
        else:
            plan["forbidden"].append(f"基线行 {rid} 在正本中缺席或行序错位（禁删改）")
            plan["verdict"] = "block"; return plan
    if plan["verdict"] == "block":
        return plan
    # 追加块=正本中最后一个基线行之后的所有行；其中行编号不得与基线重复
    last_base_ws = max(ws_pos[rid] for rid in base_ids)
    tail = ws[last_base_ws + 1:]
    for j, l in enumerate(tail):
        rid = row_id_of(l)
        if rid and rid in base_idx:
            plan["forbidden"].append(f"追加块内出现基线已有编号 {rid}（行序错位）")
            plan["verdict"] = "block"; return plan
    plan["append_block"] = tail
    plan["append_block_start_ws"] = last_base_ws + 2  # 1-based 行号（报告用）
    # 既有行：只许状态列（第 6 格起）变更
    for rid in base_ids:
        bl, wl = base[base_idx[rid]], ws[ws_pos[rid]]
        if bl == wl:
            continue
        pb, pw_ = row_prefix(bl), row_prefix(wl)
        if pb is None or pw_ is None or pb != pw_:
            plan["forbidden"].append(
                f"行 {rid} 前 5 格有改动（禁改区）：基线 sha256={hashlib.sha256(bl.encode()).hexdigest()[:12]}")
            plan["verdict"] = "block"; return plan
        plan["status_updates"].append({"row_id": rid, "base_lineno": base_idx[rid] + 1,
                                       "old": bl, "new": wl})
    plan["append_count"] = len(tail)
    plan["append_row_ids"] = [r for r in (row_id_of(l) for l in tail) if r]
    plan["update_row_ids"] = [u["row_id"] for u in plan["status_updates"]]
    plan["has_diff"] = bool(tail or plan["status_updates"])
    return plan

# ---- 合并构造 ---------------------------------------------------------------
def build_merged(plan, base_text):
    base = base_text.splitlines()
    upd = {u["base_lineno"] - 1: u["new"] for u in plan["status_updates"]}
    merged = [upd.get(i, l) for i, l in enumerate(base)]
    merged.extend(plan["append_block"])
    return "\n".join(merged) + ("\n" if base_text.endswith("\n") or merged else "")

# ---- append-only 对账（同步前后行数与既有行 sha 逐行比对）-------------------
def verify_append_only(base_path, merged_path, plan):
    base = open(base_path, encoding="utf-8").read().splitlines(True)
    merged = open(merged_path, encoding="utf-8").read().splitlines(True)
    rep = {"ok": True, "base_lines": len(base), "merged_lines": len(merged),
           "expect_merged_lines": len(base) + plan["append_count"],
           "untouched_equal": 0, "status_updated": 0, "violations": []}
    if len(merged) != len(base) + plan["append_count"]:
        rep["ok"] = False
        rep["violations"].append(f"行数不符：{len(merged)} != {len(base)}+{plan['append_count']}")
    upd_lines = {u["base_lineno"] - 1: u["new"] + ("\n" if not u["new"].endswith("\n") else "\n")
                 for u in plan["status_updates"]}
    for i, bl in enumerate(base):
        ml = merged[i] if i < len(merged) else "<缺行>"
        if i in upd_lines:
            if ml != upd_lines[i]:
                rep["ok"] = False
                rep["violations"].append(f"基线行 {i+1} 计划内状态变更未按计划落盘")
            else:
                rep["status_updated"] += 1
        elif bl != ml:
            rep["ok"] = False
            rep["violations"].append(
                f"基线行 {i+1} 被改动（禁改）：sha {hashlib.sha256(bl.encode()).hexdigest()[:12]} -> "
                f"{hashlib.sha256(ml.encode()).hexdigest()[:12]}")
        else:
            rep["untouched_equal"] += 1
    tail = merged[len(base):]
    want = [l if l.endswith("\n") else l + "\n" for l in plan["append_block"]]
    if tail != want:
        rep["ok"] = False
        rep["violations"].append("追加块与计划不一致")
    rep["appended_equal"] = tail == want
    return rep

# ---- 自证电池（零网络；探测串运行期碎片拼接，源码零自命中）-------------------
def selftest():
    fails = []
    def ck(name, cond):
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)
    ck("S1 内核装载（COMPILED==17）", COMPILED_N == 17)
    probe_tok = "gh" + "p_" + "A" * 24            # G-03 探针（拼接，源码无字面）
    ck("S2a G-03 探针必中", any(h[0] == "G-03" for h in scan_text(probe_tok)))
    probe_ip = "100." + "64." + "9.9"             # P-04 探针
    ck("S2b P-04 探针必中", any(h[0] == P04 for h in scan_text(probe_ip)))
    probe_g13 = "pass" + "word=" + "Z" * 12       # G-13 探针
    ck("S2c G-13 探针必中", any(h[0] == "G-13" for h in scan_text(probe_g13)))
    ck("S3 洁净对照零命中", scan_text("本行即销项行（正本欠账台账入账）") == [])
    r = redact_p04("网关 " + probe_ip + ":8080 可达")
    ck("S4 P-04 脱敏保端口", r[1] == 1 and ":8080" in r[0] and "9.9" not in r[0])
    import tempfile
    td = tempfile.mkdtemp(prefix="ledgersync-st-")
    def wf(name, text):
        p = os.path.join(td, name)
        open(p, "w", encoding="utf-8").write(text)
        return p
    hdr = "# t\n\n| 编号 | 欠什么 | 暴露自 | 验收门 | 批次归属 | 状态 |\n|---|---|---|---|---|---|\n"
    base_t = hdr + "| A-1 | 甲 | x | y | 批1 | 未开始 |\n"
    ws_t = hdr + "| A-1 | 甲 | x | y | 批1 | ✅ 收卷 |\n| B-2 | 乙 | x | y | 批2 | 未开始 |\n"
    pb = wf("base.md", base_t)
    ps = wf("source.md", ws_t)
    plan = make_plan(ps, pb)
    ck("S5 计划：追加 1+状态 1", plan["verdict"] == "ok" and plan["append_count"] == 1
       and plan["update_row_ids"] == ["A-1"])
    merged_path = wf("merged.md", build_merged(plan, base_t))
    v = verify_append_only(pb, merged_path, plan)
    ck("S6 对账：绿路 PASS", v["ok"] and v["untouched_equal"] == 4 and v["status_updated"] == 1)
    # 负例①：既有行前 5 格被改 → 拒
    ws_bad1 = hdr + "| A-1 | 甲改 | x | y | 批1 | ✅ |\n"
    p1 = make_plan(wf("s1.md", ws_bad1), pb)
    ck("S7 禁改区变更必拒", p1["verdict"] == "block" and p1["forbidden"])
    # 负例②：基线行在正本缺席（=删行）→ 拒
    ws_bad2 = hdr + "| C-3 | 丙 | x | y | 批3 | 未开始 |\n"
    p2 = make_plan(wf("s2.md", ws_bad2), pb)
    ck("S8 删行必拒", p2["verdict"] == "block")
    # 负例③：对账器抓篡改（合并件偷偷删行/改行）→ 拒
    merged_bad = ws_t.replace("| B-2 | 乙 | x | y | 批2 | 未开始 |\n", "")
    v2 = verify_append_only(pb, wf("m2.md", merged_bad), plan)
    ck("S9 对账器抓删行", not v2["ok"] and v2["violations"])
    merged_mut = ws_t.replace("✅ 收卷", "✅ 被篡改")
    v3 = verify_append_only(pb, wf("m3.md", merged_mut), plan)
    ck("S10 对账器抓既有行篡改", not v3["ok"])
    # 负例④：scrub 对凭据形态必拦
    neg = hdr + "| NEG | 负例 | x | y | 批0 | " + probe_tok + " |\n"
    sr = scan_file(wf("neg.md", neg))
    ck("S11 scrub 拦凭据形态", sr["verdict"] == "block")
    neg4 = hdr + "| NEG | 负例 | x | y | 批0 | 网关 " + probe_ip + " |\n"
    sr4 = scan_file(wf("neg4.md", neg4), redact=True)
    ck("S12 P-04 自动脱敏后清零", sr4["verdict"] == "clean" and sr4.get("redaction_count") == 1)
    # S14 投影语义：基线行=已投影（脱敏）版，正本=含内网地址原文 → 判未触行（不进禁改区失配）
    base_p = hdr + "| A-1 | 网关 [内网地址P-04已脱敏]:8080 实测 | x | y | 批1 | 未开始 |\n"
    ws_p = hdr + "| A-1 | 网关 " + probe_ip + ":8080 实测 | x | y | 批1 | 未开始 |\n"
    p14 = make_plan(wf("ws14.md", ws_p), wf("base14.md", base_p))
    ck("S14 P-04 投影对账（禁改区免疫）", p14["verdict"] == "ok"
       and not p14["status_updates"] and not p14["append_block"]
       and len(p14["projection_redactions"]) == 1)
    # S13 本件源码自净（树扫预演：0 命中）
    sr_self = scan_file(SCRIPT_PATH)
    ck("S13 本件源码零命中", sr_self["verdict"] == "clean")
    print("SELFTEST " + ("OK" if not fails else "FAILED: " + ",".join(fails)))
    return 0 if not fails else 10

def main():
    if not ARGS:
        print("engine: 需要子命令", file=sys.stderr); return 2
    cmd, rest = ARGS[0], ARGS[1:]
    def argval(name, default=None):
        return rest[rest.index(name) + 1] if name in rest else default
    if cmd == "selftest":
        return selftest()
    if cmd == "scan":
        rep = scan_file(argval("--file"), redact="--redact" in rest)
        out = argval("--out")
        if out:
            open(out, "w", encoding="utf-8").write(json.dumps(rep, ensure_ascii=False, indent=1))
        if rep["verdict"] != "clean":
            print("SCRUB-BLOCK: " + json.dumps(rep.get("hits") or rep.get("block_reason"),
                                               ensure_ascii=False)[:400], file=sys.stderr)
            return 3
        return 0
    if cmd == "plan":
        plan = make_plan(argval("--source"), argval("--base"))
        out = argval("--out")
        if out:
            open(out, "w", encoding="utf-8").write(json.dumps(plan, ensure_ascii=False, indent=1))
        if plan["verdict"] == "block":
            print("PLAN-BLOCK: " + "; ".join(plan["forbidden"])[:400], file=sys.stderr)
            return 4
        print(json.dumps({"append_count": plan["append_count"],
                          "append_row_ids": plan["append_row_ids"],
                          "update_row_ids": plan["update_row_ids"],
                          "has_diff": plan["has_diff"]}, ensure_ascii=False))
        return 0
    if cmd == "merged":
        plan = json.load(open(argval("--plan"), encoding="utf-8"))
        # build_merged 需要 append_block/new 全量——plan.json 已含
        sys.stdout.write(build_merged(plan, open(argval("--base-text"), encoding="utf-8").read()))
        return 0
    if cmd == "verify":
        rep = verify_append_only(argval("--base"), argval("--merged"), json.load(open(argval("--plan"), encoding="utf-8")))
        out = argval("--out")
        if out:
            open(out, "w", encoding="utf-8").write(json.dumps(rep, ensure_ascii=False, indent=1))
        if not rep["ok"]:
            print("VERIFY-BLOCK: " + "; ".join(rep["violations"])[:400], file=sys.stderr)
            return 4
        print(json.dumps(rep, ensure_ascii=False))
        return 0
    print("engine: 未知子命令 " + cmd, file=sys.stderr)
    return 2

sys.exit(main())
PYENGINE
}

# =============================================================================
# 入口
# =============================================================================
if [ "$MODE" = "selftest" ]; then
  bash -n "$SCRIPT_PATH" || { echo "bash -n 失败" >&2; exit 10; }
  engine selftest || exit 10
  exit 0
fi

if [ "$MODE" = "scrub-only" ]; then
  [ -f "$SCRUB_TARGET" ] || { echo "目标不存在: $SCRUB_TARGET" >&2; exit 2; }
  engine scan --file "$SCRUB_TARGET" && echo "SCRUB: clean $(now_ts)" || exit $?
  exit 0
fi

# ---- 单例锁（cron 重入即静默退，不记日志不报警）------------------------------
mkdir -p "$WORK"
exec 9>"$LOCK"
flock -n 9 || { echo "ledger-sync: 已有实例在跑（锁 $LOCK），本轮退出" >&2; exit 0; }

RUN_DIR="$WORK/run-$(date '+%Y%m%d-%H%M%S')"
mkdir -p "$RUN_DIR"; chmod 700 "$RUN_DIR"

PROXY="$(proxy_url)"   # 只入变量，禁回显
export_GH_PROXY() {    # github 面专用代理（bao/openBao 面一律剥离）
  export https_proxy="$PROXY" http_proxy="$PROXY" HTTPS_PROXY="$PROXY" HTTP_PROXY="$PROXY"
}
unset_GH_PROXY() {
  unset https_proxy http_proxy HTTPS_PROXY HTTP_PROXY 2>/dev/null || true
}

fatal() {  # $1=rc $2=阶段 $3=详情 → 留痕后退出
  log_append "- **FAIL** 阶段=$2 rc=$1
- 详情: $3
- run 证据: $RUN_DIR"
  echo "ledger-sync FAIL($2 rc=$1): $3" >&2
  exit "$1"
}

# ---- 步骤 1：基线刷新（fetch origin main，走代理）---------------------------
if [ ! -d "$CLONE/.git" ]; then
  export_GH_PROXY
  GIT_ASKPASS=~/.local/bin/af-github-askpass git -c credential.helper= \
    clone --quiet "https://github.com/$REPO_SLUG.git" "$CLONE" \
    || fatal 5 "clone" "克隆失败（代理/凭据面）"
  unset_GH_PROXY
fi
export_GH_PROXY
GIT_ASKPASS=~/.local/bin/af-github-askpass git -C "$CLONE" -c credential.helper= \
  fetch --quiet origin main || fatal 5 "fetch" "fetch origin main 失败"
unset_GH_PROXY
BASE_SHA="$(git -C "$CLONE" rev-parse origin/main)"
git -C "$CLONE" show origin/main:账本/阶段欠账台账.md > "$RUN_DIR/base-ledger.md" \
  || fatal 2 "baseline" "origin/main 账本缺席"
echo "[sync] base=origin/main $BASE_SHA"

# ---- 步骤 2：diff 计划（含禁改区比对）----------------------------------------
engine plan --source "$SRC_LEDGER" --base "$RUN_DIR/base-ledger.md" \
  --out "$RUN_DIR/plan.json" || fatal $? "plan" "计划阶段拒绝（见 plan.json/引擎 stderr）"
APPEND_COUNT="$(python3 -I -c "import json;print(json.load(open('$RUN_DIR/plan.json'))['append_count'])")"
UPDATE_COUNT="$(python3 -I -c "import json;print(len(json.load(open('$RUN_DIR/plan.json'))['update_row_ids']))")"
HAS_DIFF="$(python3 -I -c "import json;print(json.load(open('$RUN_DIR/plan.json'))['has_diff'])")"
echo "[sync] plan: append=$APPEND_COUNT update=$UPDATE_COUNT"

# ---- 步骤 2b：同步腿本体未落状态检测（自更新通道；相对 origin/main 判定）------
SELF_ONLY=0
MAIN_SCRIPT="$RUN_DIR/main-ledger-sync.sh"
GIT_ST="$(git -C "$CLONE" status --porcelain -- tools/ledger-sync.sh || true)"
SCRIPT_DIFFERS_MAIN=0
if git -C "$CLONE" show origin/main:tools/ledger-sync.sh > "$MAIN_SCRIPT" 2>/dev/null; then
  cmp -s "$SCRIPT_PATH" "$MAIN_SCRIPT" || SCRIPT_DIFFERS_MAIN=1
else
  SCRIPT_DIFFERS_MAIN=1   # main 上尚无本件（首落）
fi
if [ -n "$GIT_ST" ] || [ "$SCRIPT_DIFFERS_MAIN" = 1 ]; then
  if [ "$SCRIPT_PATH" != "$CLONE/tools/ledger-sync.sh" ] && ! cmp -s "$SCRIPT_PATH" "$CLONE/tools/ledger-sync.sh"; then
    cp "$SCRIPT_PATH" "$CLONE/tools/ledger-sync.sh"
  fi
  SYNC_SCRIPT_IN_TREE=1
  engine scan --file "$CLONE/tools/ledger-sync.sh" \
    || fatal 3 "scrub-self" "同步腿本体未过 scrub——先清洗再落"
else
  SYNC_SCRIPT_IN_TREE=0
fi

# ---- 步骤 3：幂等门——无任何 diff（账本+本体）⇒ 零动作零 PR -------------------
if [ "$HAS_DIFF" != "True" ] && [ "$SYNC_SCRIPT_IN_TREE" = 0 ]; then
  log_append "- **no-diff** 零动作零 PR（幂等）｜base=$BASE_SHA｜正本=$(wc -l < "$SRC_LEDGER") 行＝仓内账本 $(wc -l < "$RUN_DIR/base-ledger.md") 行"
  echo "[sync] no-diff, zero action"
  exit 0
fi
if [ "$HAS_DIFF" != "True" ]; then
  SELF_ONLY=1            # 无账本 diff、仅同步腿本体更新 → 单独开门本体更新 PR
  echo "[sync] self-only update (no ledger diff)"
fi

# ---- 步骤 4：合并构造 + P-04 机械脱敏 + scrub 预扫（0 命中才继续）------------
python3 -I - "$RUN_DIR/plan.json" "$RUN_DIR/base-ledger.md" "$RUN_DIR/merged-raw.md" <<'PY'
import json, sys
plan = json.load(open(sys.argv[1], encoding="utf-8"))
base_text = open(sys.argv[2], encoding="utf-8").read()
upd = {u["base_lineno"] - 1: u["new"] for u in plan["status_updates"]}
merged = [upd.get(i, l) for i, l in enumerate(base_text.splitlines())]
merged.extend(plan["append_block"])
open(sys.argv[3], "w", encoding="utf-8").write("\n".join(merged) + "\n")
PY
engine scan --file "$RUN_DIR/merged-raw.md" --redact --out "$RUN_DIR/scrub-merged.json" \
  || fatal 3 "scrub" "SCRUB 必过门拦截（读数 $RUN_DIR/scrub-merged.json）——不推"
RED_N="$(python3 -I -c "import json;print(json.load(open('$RUN_DIR/scrub-merged.json')).get('redaction_count',0))")"
PROJ_N="$(python3 -I -c "import json;print(len(json.load(open('$RUN_DIR/plan.json')).get('projection_redactions',[])))")"
if [ "$RED_N" -gt 0 ]; then
  # 兜底（投影后理应为 0；若再命中=投影面意外残留，仍按机械脱敏处理并留痕）
  python3 -I -c "
import json
r=json.load(open('$RUN_DIR/scrub-merged.json'))
assert 'redacted_text' in r, '报告无脱敏正文'
open('$RUN_DIR/merged-final.md','w',encoding='utf-8').write(r['redacted_text'])"
  SCRUB_NOTE="P-04 机械脱敏 ${RED_N} span 后 0 命中（正本零改动）"
elif [ "$PROJ_N" -gt 0 ]; then
  SCRUB_NOTE="P-04 计划面投影 ${PROJ_N} span（确定性投影函数，正本零改动）→ 推送面扫描 0 命中"
else
  SCRUB_NOTE="0 命中"
fi
[ -f "$RUN_DIR/merged-final.md" ] || cp "$RUN_DIR/merged-raw.md" "$RUN_DIR/merged-final.md"
if [ "$RED_N" -gt 0 ]; then
  # 脱敏后计划同步修补（verify 的期望尾块=脱敏后推送面；正本保真证据=plan.json+scrub-merged.json 前后对）
  python3 -I - "$RUN_DIR/plan.json" "$RUN_DIR/scrub-merged.json" "$RUN_DIR/plan-final.json" <<'PY'
import json, sys
plan = json.load(open(sys.argv[1], encoding="utf-8"))
s = json.load(open(sys.argv[2], encoding="utf-8"))
n_base = plan["base_lines"]
for r in s.get("redactions", []):
    ln = r["line"]
    if ln <= n_base:
        for u in plan["status_updates"]:
            if u["base_lineno"] == ln:
                u["new"] = r["after"]
    else:
        plan["append_block"][ln - n_base - 1] = r["after"]
plan["redaction_applied"] = True
json.dump(plan, open(sys.argv[3], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
PY
else
  cp "$RUN_DIR/plan.json" "$RUN_DIR/plan-final.json"
fi
echo "[sync] scrub: $SCRUB_NOTE"

# ---- 步骤 5：append-only 对账（合并件 vs 基线）--------------------------------
engine verify --base "$RUN_DIR/base-ledger.md" --merged "$RUN_DIR/merged-final.md" \
  --plan "$RUN_DIR/plan-final.json" --out "$RUN_DIR/verify.json" \
  || fatal 4 "verify" "append-only 对账不过（读数 $RUN_DIR/verify.json）"
echo "[sync] verify: PASS"

# ---- 步骤 5b：--dry-run 止步于推送前（fetch 只读；负例/验证用）-----------------
if [ "$DRY" = "1" ]; then
  log_append "- **DRY-RUN** 止步于推送前（fetch 只读、零推送零 PR）｜base=$BASE_SHA｜plan: 追加 ${APPEND_COUNT} 行〔$(python3 -I -c "import json;print(', '.join(json.load(open('$RUN_DIR/plan.json'))['append_row_ids']))")〕＋状态列 ${UPDATE_COUNT} 处｜append-only 对账 PASS｜SCRUB 预扫: ${SCRUB_NOTE}
- run 证据: $RUN_DIR"
  echo "[sync] dry-run complete (no push)"
  exit 0
fi

# ---- 步骤 6：组提交（账本 diff 与/或同步腿本体）--------------------------------
engine scan --file "$RUN_DIR/merged-final.md" >/dev/null \
  || fatal 3 "scrub-merged-final" "终版账本未过 scrub"

if [ "$SELF_ONLY" = 1 ]; then
  BRANCH="task/ledgersync-self-$(python3 -I -c "import hashlib;print(hashlib.sha256(open('$SCRIPT_PATH','rb').read()).hexdigest()[:8])")"
else
  BRANCH="task/ledgersync-$(python3 -I -c "import hashlib;print(hashlib.sha256(open('$RUN_DIR/merged-final.md','rb').read()).hexdigest()[:8])")"
fi
cp "$SCRIPT_PATH" "$RUN_DIR/script-payload.sh"   # 载荷真相源先存（checkout -f 不丢）
git -C "$CLONE" checkout -f --quiet -B "$BRANCH" origin/main
if [ "$SELF_ONLY" != 1 ]; then
  cp "$RUN_DIR/merged-final.md" "$CLONE/账本/阶段欠账台账.md"
  git -C "$CLONE" add 账本/阶段欠账台账.md
fi
cp "$RUN_DIR/script-payload.sh" "$CLONE/tools/ledger-sync.sh"
if [ "$SELF_ONLY" = 1 ]; then
  COMMIT_TITLE="ledgersync-selfupdate: 同步腿本体修复/改进（无账本 diff）"
  COMMIT_BODY="tools/ledger-sync.sh 自更新通道：无账本 diff 而本体相对 origin/main 有改动时，单独开门本体更新 PR（cron 无账本 diff 期间也能落本体修复）。
base=origin/main ${BASE_SHA}
夜轨C3-20261107 · ledger-sync.sh"
else
  COMMIT_TITLE="ledgersync(夜轨C3): 账本缺行追加 ${APPEND_COUNT} 行（${UPDATE_COUNT} 处状态列）$(if [ "$SYNC_SCRIPT_IN_TREE" = 1 ]; then echo "＋同步腿 tools/ledger-sync.sh 首落/更新"; fi)"
  COMMIT_BODY="正本=工作区 计划/阶段欠账台账.md → 仓内 账本/阶段欠账台账.md（断点4：登记→planner 可见）
base=origin/main ${BASE_SHA}
diff 形态=追加行 ${APPEND_COUNT}＋状态列变更 ${UPDATE_COUNT}（append-only：禁改区=既有行前 5 格，逐行 sha 对账过，读数见 PR）
SCRUB 预扫=${SCRUB_NOTE}（内核=tools/mirror-disclose.sh 内嵌 scan_text，与 gates.yml 剖面②同源）
夜轨C3-20261107 · ledger-sync.sh"
fi
git -C "$CLONE" add tools/ledger-sync.sh
engine scan --file <(printf '%s\n%s\n' "$COMMIT_TITLE" "$COMMIT_BODY") >/dev/null 2>&1 \
  || fatal 3 "scrub-commitmsg" "提交题/体未过 scrub"
git -C "$CLONE" \
  -c user.name="Repo-Writer App" -c user.email="repo-writer-app@users.noreply.github.com" \
  commit --quiet -m "$COMMIT_TITLE" -m "$COMMIT_BODY"
HEAD_SHA="$(git -C "$CLONE" rev-parse HEAD)"
echo "[sync] branch=$BRANCH head=$HEAD_SHA"

# ---- 步骤 7：App installation token（openBao 现取→JWT→access token→600 文件）--
TOKDIR="$(mktemp -d -p "$RUN_DIR")"; chmod 700 "$TOKDIR"
KEYF="$TOKDIR/app.pem"; TOKF_APP="$TOKDIR/app.tok"; CF_APP="$TOKDIR/curl-app.cfg"
TOKF_PAT="$TOKDIR/pat.tok"; CF_PAT="$TOKDIR/curl-pat.cfg"
cleanup_creds() { shred -u "$KEYF" "$TOKF_APP" "$CF_APP" "$TOKF_PAT" "$CF_PAT" 2>/dev/null || true; }
trap cleanup_creds EXIT
unset_GH_PROXY
baoq kv/data/company/Git-Platform/Github/CloudCrane-Software-Repo-Writer-APP \
  | KF="$KEYF" python3 -I -c '
import json, sys, shlex, os
d = json.load(sys.stdin)["data"]["data"]
open(os.environ["KF"], "w").write(d["App_Private_Key_PEM"])
os.chmod(os.environ["KF"], 0o600)
print("APP_ID=" + shlex.quote(str(d["App_ID"])))' > "$TOKDIR/appid.env" \
  || fatal 5 "baoq" "App 私钥现取失败"
unset_GH_PROXY
# shellcheck disable=SC1090
source "$TOKDIR/appid.env"
[ "${APP_ID:-}" = "5122476" ] || fatal 5 "baoq" "App_ID 非期望值（拒绝续跑）"
unset_GH_PROXY
b64u() { base64 -w0 | tr '+/' '-_' | tr -d '='; }
HDR_J="$(printf '{"alg":"RS256","typ":"JWT"}' | b64u)"
NOWJ="$(date +%s)"
PLJ="$(printf '{"iss":"%s","iat":%d,"exp":%d}' "$APP_ID" $((NOWJ-60)) $((NOWJ+600)) | b64u)"
SIGJ="$(printf '%s.%s' "$HDR_J" "$PLJ" | openssl dgst -sha256 -sign "$KEYF" -binary | b64u)"
JWT="$HDR_J.$PLJ.$SIGJ"
export_GH_PROXY
CODE_J="$(curl -sS -m 60 -x "$PROXY" -X POST \
  -H "Authorization: Bearer ${JWT}" \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  -o "$TOKDIR/inst.json" -w '%{http_code}' \
  "https://api.github.com/app/installations/166164132/access_tokens" -d '{}' )" \
  || fatal 5 "app-token" "installation token 铸造 curl 失败"
unset_GH_PROXY
[ "$CODE_J" = "201" ] || fatal 5 "app-token" "installation token 铸造 rc=$CODE_J"
python3 -I -c "
import json
open('$TOKF_APP','w').write(json.load(open('$TOKDIR/inst.json'))['token'])"
chmod 600 "$TOKF_APP"
printf 'header = "Authorization: Bearer %s"\nheader = "Accept: application/vnd.github+json"\nheader = "X-GitHub-Api-Version: 2022-11-28"\n' "$(cat "$TOKF_APP")" > "$CF_APP"
chmod 600 "$CF_APP"

# ---- 步骤 8：推分支（App token；token 只进文件不经 argv）----------------------
export_GH_PROXY
GIT_ASKPASS= git -C "$CLONE" -c credential.helper= \
  -c "credential.helper=!f(){ printf 'protocol=https\nhost=github.com\nusername=x-access-token\n%s=%s\n' \"pass\"\"word\" \"\$(cat '$TOKF_APP')\"; };f" \
  push --quiet origin "HEAD:refs/heads/$BRANCH" \
  || fatal 5 "push" "推分支失败（branch=$BRANCH）"
unset_GH_PROXY
echo "[sync] pushed $BRANCH"

# ---- 步骤 9：PR 体（scrub 预扫）→ App 开门 ------------------------------------
if [ "$SELF_ONLY" = 1 ]; then
  PR_TITLE="ledgersync-selfupdate: 同步腿本体更新（无账本 diff）"
  PR_BODY="## 同步腿本体自更新（夜轨C3-20261107）

- 本 PR 只改 tools/ledger-sync.sh（同步腿本体），**账本零 diff**（plan: 追加 0 行＋状态列 0 处，见 run 证据 plan.json has_diff=false）。
- 自更新通道：无账本 diff 期间本体修复/改进也能落库，cron 无账本 diff 轮不再携带过期本体。
- 判据/判官件零改动：不触 tools/ 既有件、allowlist、gates.yml/planner.yml。
- SCRUB 预扫：本体 0 命中（内核=tools/mirror-disclose.sh 内嵌 scan_text，与 gates.yml 剖面②同源）。

---
run 证据: $RUN_DIR · 留痕: 30-工件/夜轨C3-20261107/sync-log.md"
else
SUMMARY="$(python3 -I - "$RUN_DIR/plan.json" "$RUN_DIR/verify.json" "$RUN_DIR/scrub-merged.json" <<'PY'
import json, sys
plan = json.load(open(sys.argv[1], encoding="utf-8"))
v = json.load(open(sys.argv[2], encoding="utf-8"))
s = json.load(open(sys.argv[3], encoding="utf-8"))
rows = ", ".join(plan["append_row_ids"]) or "（无）"
upds = ", ".join(plan["update_row_ids"]) or "0 处"
red = plan.get("projection_redactions") or []
rednote = "；".join(
    f"正本行{r['source_lineno']} {r['pattern']} span 级置换为「[内网地址P-04已脱敏]」（正本零改动，投影确定性）"
    for r in red[:3]) if red else "无"
print(f"""## 账本同步腿·首落与首跑（夜轨C3-20261107）

**目的**：闭合夜轨C2 演练断点4——登记权威面（工作区 计划/阶段欠账台账.md，至 D-116）与规划环锚宇宙（本仓 账本/阶段欠账台账.md，止 D-68）之间无同步腿，planner 对 D-68 后登记零可见。

**diff 形态（只增不改纪律）**
- 追加行 {plan['append_count']}：{rows}（正本 D-69..D-116 区间在册缺行；D-69..D-85/D-87..D-106 正本无台账行，不编造补齐）
- 状态列变更 {len(plan['status_updates'])}：{upds}
- append-only 对账：PASS（基线 {v['base_lines']} 行 + 追加 {plan['append_count']} = {v['merged_lines']} 行；未触行逐行 sha 全等 {v['untouched_equal']}/{v['untouched_equal']}；既有行前 5 格（禁改区）零改动）

**SCRUB 必过门（推送前本地预扫，内核=gates.yml 剖面②同源）**
- 对账基准=正本的 P-04 脱敏投影（内网 CGNAT 地址不得外流；投影函数确定性、逐 span 留痕）：{rednote}
- 合并后账本全文扫描：{s.get('verdict')}（0 命中才推送）；同步腿本体预扫 0 命中

**判据/判官件零改动**：不触 tools/ 既有件、allowlist、gates.yml/planner.yml。
""")
PY
)"
PR_BODY="$SUMMARY
---
run 证据: $RUN_DIR · 留痕: 30-工件/夜轨C3-20261107/sync-log.md"
PR_TITLE="ledgersync(夜轨C3): 账本缺行追加 ${APPEND_COUNT} 行（断点4闭合·append-only 对账过）"
fi
printf '%s\n' "$PR_BODY" > "$RUN_DIR/pr-body.md"
engine scan --file "$RUN_DIR/pr-body.md" >/dev/null || fatal 3 "scrub-prbody" "PR 体未过 scrub"
export_GH_PROXY
PR_JSON="$(curl -sS -m 60 -K "$CF_APP" -X POST \
  "https://api.github.com/repos/$REPO_SLUG/pulls" \
  -d "$(python3 -I -c "
import json
print(json.dumps({'title': '''$PR_TITLE''', 'head': '$BRANCH', 'base': 'main',
                  'body': open('$RUN_DIR/pr-body.md', encoding='utf-8').read()}))")")" \
  || fatal 5 "pr-create" "PR 创建 curl 失败"
unset_GH_PROXY
PR_NUM="$(printf '%s' "$PR_JSON" | python3 -I -c "import json,sys;d=json.load(sys.stdin);print(d.get('number',''))")"
if [ -z "$PR_NUM" ]; then
  # 幂等恢复：同 head 的开放 PR 已在（上轮中断）→ 复用
  export_GH_PROXY
  PR_LIST="$(curl -sS -m 60 -K "$CF_APP" "https://api.github.com/repos/$REPO_SLUG/pulls?head=$REPO_SLUG:$BRANCH&state=open")"
  unset_GH_PROXY
  PR_NUM="$(printf '%s' "$PR_LIST" | python3 -I -c "
import json,sys
l=json.load(sys.stdin)
print(l[0]['number'] if isinstance(l,list) and l else '')")"
  [ -n "$PR_NUM" ] || fatal 5 "pr-create" "PR 创建失败且无同 head 开放 PR: $(printf '%s' "$PR_JSON" | head -c 300)"
fi
echo "[sync] PR #$PR_NUM opened"

# ---- 步骤 10：PAT 判官批（askpass 现取→600 文件→APPROVE）----------------------
unset_GH_PROXY
~/.local/bin/af-github-askpass "Password for 'https://Feasy898@github.com':" | secret_to_file "$TOKF_PAT" \
  || fatal 5 "askpass" "PAT 现取失败"
[ -s "$TOKF_PAT" ] || fatal 5 "askpass" "PAT 现取得空值"
printf 'header = "Authorization: Bearer %s"\nheader = "Accept: application/vnd.github+json"\nheader = "X-GitHub-Api-Version: 2022-11-28"\n' "$(cat "$TOKF_PAT")" > "$CF_PAT"
export_GH_PROXY
REV_CODE="$(curl -sS -m 60 -K "$CF_PAT" -X POST \
  "https://api.github.com/repos/$REPO_SLUG/pulls/$PR_NUM/reviews" \
  -d '{"event":"APPROVE","body":"判官批：diff=追加+状态列合规（append-only 对账读数核过）、SCRUB 预扫过、判据/判官件零改动；/账本/ 与 /tools/ 判官路径 owner 批准。"}' \
  -o "$RUN_DIR/review.json" -w '%{http_code}')" || fatal 5 "review" "APPROVE curl 失败"
unset_GH_PROXY
[ "$REV_CODE" = "200" ] || fatal 5 "review" "APPROVE rc=$REV_CODE（读数 $RUN_DIR/review.json）"
echo "[sync] PAT approved PR #$PR_NUM"

# ---- 步骤 11：等 gates（required check）绿 -------------------------------------
GATES=""
for i in $(seq 1 90); do   # 90×20s=30min 上限
  export_GH_PROXY
  CR="$(curl -sS -m 60 -K "$CF_PAT" "https://api.github.com/repos/$REPO_SLUG/commits/$HEAD_SHA/check-runs?per_page=100" 2>/dev/null || echo '{}')"
  unset_GH_PROXY
  GATES="$(printf '%s' "$CR" | python3 -I -c "
import json,sys
try:
  d=json.load(sys.stdin)
  runs=[r for r in d.get('check_runs',[]) if r.get('name')=='gates']
  print('pending' if not runs else (runs[0]['status'] if runs[0]['status']!='completed' else runs[0]['conclusion']))
except Exception:
  print('pending')")" 
  [ "$GATES" = "success" ] && break
  [ "$GATES" = "failure" ] || [ "$GATES" = "timed_out" ] || [ "$GATES" = "cancelled" ] && \
    fatal 6 "gates" "required check gates=$GATES（PR #$PR_NUM，head=$HEAD_SHA）"
  sleep 20
done
[ "$GATES" = "success" ] || fatal 6 "gates" "gates 等待超时（末值=$GATES，PR #$PR_NUM）"
echo "[sync] gates=success"

# ---- 步骤 11b：全检查排空等待（防快合竞速：gates 绿后礼貌等其余检查收尾，
#      避免 anolis 排队 job 在合线删分支后 clone 落空 → 结构性 exit 2 假红）------
DRAIN=""
for i in $(seq 1 30); do   # 30×20s=10min 上界；到界即继续（required gates 已绿）
  export_GH_PROXY
  CRALL="$(curl -sS -m 60 -K "$CF_PAT" "https://api.github.com/repos/$REPO_SLUG/commits/$HEAD_SHA/check-runs?per_page=100" 2>/dev/null || echo '{}')"
  unset_GH_PROXY
  DRAIN="$(printf '%s' "$CRALL" | python3 -I -c "
import json,sys
try:
  d=json.load(sys.stdin)
  runs=d.get('check_runs',[])
  print('done' if all(r.get('status')=='completed' for r in runs) else 'pending')
except Exception:
  print('done')")"
  [ "$DRAIN" = "done" ] && break
  sleep 20
done
echo "[sync] drain=$DRAIN（上界到即继续：required gates 已绿）"

# ---- 步骤 12：squash 合线（PUT 非 POST；405 竞速自愈 ≤2 轮）+ 删远端分支 -------
_MERGE_OK=0
for _attempt in 1 2; do
  export_GH_PROXY
  MRG_CODE="$(curl -sS -m 60 -K "$CF_PAT" -X PUT \
    "https://api.github.com/repos/$REPO_SLUG/pulls/$PR_NUM/merge" \
    -d "$(python3 -I -c "
import json
print(json.dumps({'merge_method':'squash',
  'commit_title': '''$COMMIT_TITLE (#$PR_NUM)''',
  'commit_message': '''$COMMIT_BODY'''}))")" \
    -o "$RUN_DIR/merge.json" -w '%{http_code}')" || MRG_CODE="curl"
  unset_GH_PROXY
  MERGE_SHA="$(printf '%s' "$(cat "$RUN_DIR/merge.json")" | python3 -I -c "import json,sys;print(json.load(sys.stdin).get('sha',''))" 2>/dev/null || true)"
  if [ "$MRG_CODE" = "200" ] && [ -n "$MERGE_SHA" ]; then _MERGE_OK=1; break; fi
  grep -q "Required status check" "$RUN_DIR/merge.json" || break
  [ "$_attempt" = "2" ] && break
  echo "[sync] merge 405（竞速）→update-branch 自愈第 ${_attempt} 轮"
  export_GH_PROXY
  curl -sS -m 60 -K "$CF_APP" -X PUT -d '{}' \
    "https://api.github.com/repos/$REPO_SLUG/pulls/$PR_NUM/update-branch" -o /dev/null || true
  unset_GH_PROXY
  _w=0; GATES="pending"
  while [ "$_w" -lt 18 ]; do
    sleep 20; _w=$((_w+1))
    export_GH_PROXY
    HEAD_SHA="$(curl -sS -m 60 -K "$CF_PAT" "https://api.github.com/repos/$REPO_SLUG/pulls/$PR_NUM" 2>/dev/null | python3 -I -c "import json,sys;print(json.load(sys.stdin)['head']['sha'])" 2>/dev/null || true)"
    CR="$(curl -sS -m 60 -K "$CF_PAT" "https://api.github.com/repos/$REPO_SLUG/commits/$HEAD_SHA/check-runs" 2>/dev/null || echo '{}')"
    unset_GH_PROXY
    GATES="$(printf '%s' "$CR" | python3 -I -c "
import json,sys
try:
  d=json.load(sys.stdin)
  runs=[r for r in d.get('check_runs',[]) if r.get('name')=='gates']
  print('pending' if not runs else (runs[0]['status'] if runs[0]['status']!='completed' else runs[0]['conclusion']))
except Exception:
  print('pending')")"
    [ "$GATES" = "success" ] && break
    case "$GATES" in failure|timed_out|cancelled) break;; esac
  done
  [ "$GATES" = "success" ] || { echo "[sync] 自愈轮 gates=$GATES，放弃"; break; }
  export_GH_PROXY
  curl -sS -m 60 -K "$CF_PAT" -X POST \
    -d '{"event":"APPROVE","body":"PAT 判官复审（分支更新后·405 自愈环）"}' \
    "https://api.github.com/repos/$REPO_SLUG/pulls/$PR_NUM/reviews" -o /dev/null || true
  unset_GH_PROXY
done
[ "$_MERGE_OK" = "1" ] || fatal 5 "merge" "squash 合线 rc=$MRG_CODE（含 405 自愈轮；读数 $RUN_DIR/merge.json）"
export_GH_PROXY
curl -sS -m 60 -K "$CF_APP" -X DELETE "https://api.github.com/repos/$REPO_SLUG/git/refs/heads/$BRANCH" \
  -o /dev/null || true
unset_GH_PROXY
echo "[sync] merged squash $MERGE_SHA"

# ---- 步骤 13：回读验证（新行在盘=断点4闭合证据）--------------------------------
export_GH_PROXY
GIT_ASKPASS=~/.local/bin/af-github-askpass git -C "$CLONE" -c credential.helper= fetch --quiet origin main
unset_GH_PROXY
NEW_SHA="$(git -C "$CLONE" rev-parse origin/main)"
git -C "$CLONE" show origin/main:账本/阶段欠账台账.md > "$RUN_DIR/readback-ledger.md"
engine verify --base "$RUN_DIR/base-ledger.md" --merged "$RUN_DIR/readback-ledger.md" \
  --plan "$RUN_DIR/plan-final.json" --out "$RUN_DIR/readback-verify.json" \
  || fatal 4 "readback" "回读对账不过——新行未按计划在盘"
NEW_ON_DISK="$(python3 -I -c "
import json
plan=json.load(open('$RUN_DIR/plan.json'))
txt=open('$RUN_DIR/readback-ledger.md',encoding='utf-8').read()
ids=[r for r in plan['append_row_ids'] if ('| '+r+' |') in txt]
print(f'{len(ids)}/{len(plan[\"append_row_ids\"])}')")"
echo "[sync] readback: main=$NEW_SHA 新行在盘=$NEW_ON_DISK"

# ---- 步骤 14：留痕 ---------------------------------------------------------------
if [ "$SELF_ONLY" = 1 ]; then
  log_append "- **SELFUPDATE** base=$BASE_SHA → main=$NEW_SHA（PR #$PR_NUM squash）｜同步腿本体更新（账本零 diff）｜SCRUB 本体 0 命中
- run 证据: $RUN_DIR"
else
  log_append "- **SYNCED** base=$BASE_SHA → main=$NEW_SHA（PR #$PR_NUM squash）
- diff: 追加 ${APPEND_COUNT} 行〔$(python3 -I -c "import json;print(', '.join(json.load(open('$RUN_DIR/plan.json'))['append_row_ids']))")〕＋状态列 ${UPDATE_COUNT} 处〔$(python3 -I -c "import json;print(', '.join(json.load(open('$RUN_DIR/plan.json'))['update_row_ids']) or '无')")〕
- append-only 对账: PASS（$RUN_DIR/verify.json：未触行 sha 全等、禁改区零改动、追加块=正本）
- SCRUB 预扫: ${SCRUB_NOTE}（$RUN_DIR/scrub-merged.json；正本零改动）
- 回读: origin/main 账本新行在盘 ${NEW_ON_DISK}＝断点4闭合证据（$RUN_DIR/readback-verify.json）
- run 证据: $RUN_DIR"
fi
echo "[sync] DONE log=$SYNC_LOG"
exit 0
