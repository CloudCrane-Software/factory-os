#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""账本收卷草案生成器（逃逸台账收卷时机器生成欠账台账行草案；账本机制批 2026-11-04）。

背景（同族先例）：2026-11-02 账本迁移门批人工迁移 29 条、2026-11-03 账本一致批再迁数条
——迁移义务每次都靠人工逐条抄写，漏抄=实债继续隐身（迁移对账门 tools/
test-ledger-migration-recon.py 的红面就是这么积出来的）。本件把「收卷时生成欠账行草案」
机器化（对应 RT-E111 机制③「收卷时机器生成欠账行草案」的欠账台账行义务面）：给定逃逸
台账，凡「未完结 ∧ 欠账台账无覆盖 ∧ 无豁免标记」的条目各出一行表格行草案，人工只做
审定与粘贴，不再手抄——消灭人工迁移遗漏这一增生口。

草案立场（纪律）：**草案即欠账**——每行只承认「该条欠着」，不含任何「清偿完成」类措辞
（机器草案无权代答清偿；清偿须按验收门实测后由人工改行态）。故草案全文不出现「销项」
及其同义完成态词（selftest 钉住这一点）。

判据（与迁移门同族单一源；词表与解析口径照搬 tools/test-ledger-migration-recon.py
docstring，本件不 import 它——两件各自自足、词表同源文档化）：
  · 未完结判定（「修复对账」栏三类任一命中）：
      V 判决短语（栏内首个粗体 span；无粗体取首个冒号前段）含残余词：
        部分/未见/未修/未落/未开始/未复测/未提交/未达/待修复回报/仍为欠账/
        欠账本体未清/未回收/残项
      B 对账正文（判决短语之后）含自认未施工词：
        未见施工/仍未施工/仍为欠账/机制腿未落/欠账本体未清
      H 栏内自述残余（全栏扫描，剥「…」/`…`/“…”/『…』引用材料后）：
        未核/未复核/未逐行核/未逐行复核/未独立复核/未复跑/未施工/未收口/未动/
        未建/未接线/未做（∪V 词表）
      缺「修复对账」栏 → 未完结（不可静默跳过）。
  · 覆盖判定：欠账台账存在行满足其一——编号列前缀恰为本条 id，或行**描述列**
    （编号/欠什么/暴露自 前三格）含本条 id（词边界 RT-E<n>(?![0-9])；
    验收门/状态列附注顺带提及不算覆盖）。
  · 豁免判定（修复对账栏内机读标记行，形态同迁移门 RT-E111 机制②）：
      `- **账本迁移对账**：豁免=<非空理由>` → 有豁免，不出草案；
      `- **账本迁移对账**：欠账行=<编号>` → 编号实存于欠账台账即豁免，不出草案
      （指向不存在 → 不算豁免，照出草案）。
  · 草案行六格：
      编号   = 原 RT-Enn id；
      欠什么 = 「逃逸台账 RT-Enn（severity）残余迁移：<条目标题>（全文判据源=…逃逸问题
               台账.md:<行号> 修复对账+拦截机制栏）」——标题内竖线
               替换为「／」防破表；
               （2026-11-05 E92 噪声清理批：欠账格不再写「触发词=<命中词族>」索引片段——
                噪声词面清理，事实与坐标一字不减；触发词族由门在红面点名时现算）
      暴露自 = 「红队终局轮-20261101/逃逸问题台账.md:<行号> RT-Enn；账本机制批
               <生成日> 收卷草案生成器出稿（迁移入账，清偿另计）」；
      验收门 = 「逃逸台账 RT-Enn 拦截机制逐项落码/留证清偿；迁移对账门
               tools/test-ledger-migration-recon.py 覆盖本条后翻绿；止增门
               tools/ledger-growth-gate.py 守护新增口；清偿后本行状态改 ✅ 并附证据」；
      批次归属 = 账本机制批（--batch 可改）；
      状态   = 「未开始（草案生成——迁移入账，清偿另计）」（无时间戳：同输入重复
               调用逐字节幂等）。
  · fail-closed（rc=2，不产草案不猜绿）：逃逸台账/欠账台账缺件、零条目可解析、
    条目 id 重复（解析面断）。

模式：
  （无参）          读真逃逸台账+欠账台账 → 草案到 stdout。exit 0=零欠账项（空表草案）；
                    1=有草案行（便利 shell 判断；stdout 仍含完整草案）；
                    2=不可证（fail-closed，零草案）。
                    （2026-11-04 修补员勘正：原稿「exit 0=已出草案（可能为空表）或无欠账项」
                    与实际 run_cli 返回读数相反——实际 1=有草案行、0=仅当欠账项为零。）
  --out <path>      草案写文件而非 stdout（原子写）。
  --batch <名>      草案「批次归属」列值（缺省=账本机制批）。
  --selftest        内嵌夹具自测（零网络、零真台账读取），覆盖：能出草案行 /
                    已迁移（前缀+行文引用）不出 / 带豁免不出 / 欠账行= 实存不出·
                    不存在照出 / 缺件 fail-closed 零草案 / 草案行不含完成态措辞
                    （销项/已销/已收口/已修复/已闭合/已落地/已完成/已完结 族）/
                    重复调用逐字节幂等 / 缺修复对账栏照出 / 自认完结不出 / 零条目
                    rc=2 / id 重复 rc=2。全过 exit 0。

命名纪律：本件**不带** test- 前缀——all-gates L2 以 tools/test-*.py glob 自动收编，新
test- 前缀件会改动 L2 件数钉值（tools/gate-pins.list L2_MIN_ITEMS），污染另一批复核
读数；本件为收卷时人工调用的生成器，不进常驻判定面。

自足性：只 Python3 标准库；零网络、零 sudo、零宿主改动（--out 之外的写入只在 tempfile）。
"""
import json
import os
import re
import sys
import tempfile
import shutil
from datetime import date

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ESC_PATH = os.path.join(WS, "计划", "研究组", "红队终局轮-20261101", "逃逸问题台账.md")
DEBT_PATH = os.path.join(WS, "计划", "阶段欠账台账.md")
GEN_DATE = date.today().isoformat()

HDR_RE = re.compile(r"^### (RT-E\d+)(?:-[A-Za-z0-9]+)?（([^）]*)）")
REPAIR_RE = re.compile(r"- \*\*修复对账\*\*[:：]?(.*?)(?=\n### |\Z)", re.S)
TITLE_RE = re.compile(r"^### (.+)$", re.M)
MARKER_RE = re.compile(r"^- \*\*账本迁移对账\*\*[:：]\s*(.+)$", re.M)
QUOTE_RE = re.compile(r"「[^」]*」|`[^`]*`|“[^”]*”|『[^』]*』", re.S)

# 未完结判定词表（单一源=迁移门 docstring；词表只增不减纪律同源）
VERDICT_KW = ("部分", "未见", "未修", "未落", "未开始", "未复测", "未提交", "未达",
              "待修复回报", "仍为欠账", "欠账本体未清", "未回收", "残项")
BODY_KW = ("未见施工", "仍未施工", "仍为欠账", "机制腿未落", "欠账本体未清")
RESIDUAL_KW = VERDICT_KW + ("未核", "未复核", "未逐行核", "未逐行复核", "未独立复核",
                            "未复跑", "未施工", "未收口", "未动", "未建", "未接线", "未做")
BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
SEV_RE = re.compile(r"^### RT-E\d+(?:-[A-Za-z0-9]+)?（([^）]*)）")


def parse_escape(path):
    """解析逃逸台账 → [(id, line_no, severity, title, repair_text)]；id 重复抛 ValueError。"""
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    entries = []
    cur = None
    for i, ln in enumerate(lines, 1):
        m = HDR_RE.match(ln)
        if m:
            if cur:
                entries.append(cur)
            cur = {"id": m.group(1), "line": i, "sev": (m.group(2) or "").strip(),
                   "title": ln[4:].strip(), "buf": []}
        elif cur is not None:
            cur["buf"].append(ln)
    if cur:
        entries.append(cur)
    seen = set()
    out = []
    for e in entries:
        if e["id"] in seen:
            raise ValueError("逃逸台账条目 id 重复：%s（解析面断）" % e["id"])
        seen.add(e["id"])
        txt = "\n".join(e["buf"])
        m = REPAIR_RE.search(txt)
        out.append((e["id"], e["line"], e["sev"], e["title"], m.group(1).strip() if m else ""))
    return out


def parse_debt(path):
    """解析欠账台账 → [(编号, 描述列文本)]（| 表行；描述列=编号/欠什么/暴露自 前三格）。"""
    rows = []
    with open(path, encoding="utf-8") as f:
        for ln in f:
            if ln.startswith("| "):
                cells = ln.split("|")
                cid = cells[1].strip() if len(cells) > 1 else ""
                desc = "|".join(c.strip() for c in cells[1:4])
                rows.append((cid, desc))
    return rows


def covered_by(eid, rows):
    """覆盖判定：编号前缀 或 描述列行文引用（词边界）。命中返回说明，否则 None。"""
    for cid, _desc in rows:
        m = re.match(r"(RT-E\d+)", cid)
        if m and m.group(1) == eid:
            return "编号前缀:%s" % cid
    pat = re.compile(eid + r"(?![0-9])")
    for cid, desc in rows:
        if pat.search(desc):
            return "行文引用:%s" % cid
    return None


def exemption_marker(rep, rows):
    """豁免判定（形态同迁移门）。返回 (豁免?, 说明)。欠账行= 指向须实存。"""
    ok = None
    for m in MARKER_RE.finditer(rep):
        body = m.group(1)
        if body.startswith("豁免="):
            reason = body[len("豁免="):].strip()
            if reason:
                return (True, "豁免标记")
            ok = (False, "豁免理由为空")
        elif body.startswith("欠账行="):
            target = body[len("欠账行="):].strip()
            if any(cid == target for cid, _ in rows):
                return (True, "欠账行标记→%s（实存）" % target)
            ok = (False, "欠账行标记→%s 不存在" % target)
    if ok:
        return ok
    return (False, "无标记")


def unfinished_hits(rep):
    """未完结判定 → (未完结?, 触发词族说明)。缺栏=未完结（不可静默跳过）。"""
    if not rep:
        return (True, "缺「修复对账」栏")
    b = BOLD_RE.search(rep)
    own = QUOTE_RE.sub(" ", rep)
    body = QUOTE_RE.sub(" ", rep[len(b.group(0)):]) if b else own
    verdict = b.group(1) if b else rep.split("：")[0][:40]
    vh = [k for k in VERDICT_KW if k in verdict]
    bh = [k for k in BODY_KW if k in body]
    hh = [k for k in RESIDUAL_KW if k in own]
    if not vh and not bh and not hh:
        return (False, "自认完结")
    trig = []
    if vh:
        trig.append("V:%s" % ",".join(vh))
    if bh:
        trig.append("B:%s" % ",".join(bh))
    hnew = [k for k in hh if k not in vh]
    if hnew:
        trig.append("H:%s" % ",".join(hnew))
    return (True, "+".join(trig))


# 完成态词稿面替换表（草案立场纪律；2026-11-04 修补员复核扩族：原只替换「销项」二字，
# 源标题/引文材料中的「已销/已收口/已修复/已闭合/已落地/已完成/已完结」完成态变体漏网
# （实测草案 :71「已修复可见」、:82「已闭合并部署」、:95「✅ 已销」、:23「已落地」四族
# 全部带入稿面），破「草案全文无完成态措辞」不变量——统一替换为中性登记表述，只承认
# 「登记在案」、不代答清偿；替换仅在草案稿面，正本零改动。词表只增不减，新变体按族补入）。
_COMPLETION_SUBS = (
    ("已销", "清账登记"),
    ("已收口", "收口登记"),
    ("已修复", "修复登记"),
    ("已闭合", "闭合登记"),
    ("已落地", "落地登记"),
    ("已完成", "收尾登记"),
    ("已完结", "收尾登记"),
    ("销项", "清账登记"),
)


def _cell(s):
    """表格格安全化（竖线→全角斜杠，换行→空格；源文自带完成态词（销项/已销/已收口/
    已修复/已闭合/已落地/已完成/已完结 族）→中性登记表述——草案立场纪律：草案全文不得
    含完成态措辞；含它的是**源标题/引文原文**（如某条标题自记「✅ 已销的唯一机核依据已
    不复现」、引文材料「已修复可见」「已闭合并部署」「已落地」），照抄会破「草案即欠账」
    的立场不变量。替换仅在草案稿面、正本零改动，且本件头注+草案前言双处披露该替换
    纪律）。"""
    t = str(s).replace("|", "／").replace("\n", " ")
    for _old, _new in _COMPLETION_SUBS:
        t = t.replace(_old, _new)
    return t.strip()


def build_draft(esc_path, debt_path, batch):
    """生成草案文本。返回 (rc, text)：0=无欠账项；1=有草案行；2=不可证（零草案）。"""
    if not os.path.isfile(esc_path) or not os.path.isfile(debt_path):
        return 2, ""
    try:
        entries = parse_escape(esc_path)
    except ValueError as e:
        sys.stderr.write("FAIL %s\n" % e)
        return 2, ""
    if not entries:
        sys.stderr.write("FAIL 逃逸台账零条目可解析——解析面断（rc=2）\n")
        return 2, ""
    rows = parse_debt(debt_path)
    accept = ("逃逸台账 %s 拦截机制逐项落码/留证清偿；迁移对账门 tools/"
              "test-ledger-migration-recon.py 覆盖本条后翻绿；止增门 tools/"
              "ledger-growth-gate.py 守护新增口；清偿后本行状态改 ✅ 并附证据" % "%s")
    lines = [
        "# 逃逸台账收卷迁移草案（机器生成）",
        "",
        "生成器=tools/ledger-close-draft.py；判据源=tools/test-ledger-migration-recon.py docstring 同族口径。",
        "草案立场：草案即欠账（每行只承认欠着；清偿须按验收门实测后由人工改行态）。",
        "稿面替换纪律：源标题/引文原文含完成态措辞的（那二字及其「已」字头同族共八族词，"
        "稿面一律替换为中性登记表述），正本零改动，保持草案全文无完成态措辞不变量。",
        "",
        "| 编号 | 欠什么 | 暴露自 | 验收门 | 批次归属 | 状态 |",
        "|---|---|---|---|---|---|",
    ]
    n = 0
    for eid, line, sev, title, rep in entries:
        if covered_by(eid, rows):
            continue
        exp, _expmsg = exemption_marker(rep, rows)
        if exp:
            continue
        unfin, _trig = unfinished_hits(rep)
        if not unfin:
            continue
        # 2026-11-05 E92 噪声清理批：欠账格**不再写「触发词=<命中词族>」索引片段**——
        # 该片段是判据词面的噪声索引（同一残余词族在多行重复出现，且易被误读为行态声明）；
        # 触发词族仍由门在红面点名时现算（tools/test-ledger-migration-recon.py 红面逐条
        # 点名 id+行号+触发词），不因稿面删索引而失可判读性。
        owe = ("逃逸台账 %s（%s）残余迁移：%s（全文判据源=红队终局轮-20261101/逃逸问题台账.md:%d "
               "修复对账+拦截机制栏）" % (eid, sev or "?", title, line))
        expose = ("红队终局轮-20261101/逃逸问题台账.md:%d %s；账本机制批 %s 收卷草案生成器出稿"
                  "（迁移入账，清偿另计）" % (line, eid, GEN_DATE))
        accept_row = accept % eid
        state = "未开始（草案生成——迁移入账，清偿另计）"
        lines.append("| %s | %s | %s | %s | %s | %s |" % (
            _cell(eid), _cell(owe), _cell(expose), _cell(accept_row), _cell(batch), _cell(state)))
        n += 1
    lines.append("")
    lines.append("（草案行 %d 条；编号用原 id；批次归属=%s；状态一律未开始。）" % (n, batch))
    text = "\n".join(lines) + "\n"
    return (1 if n else 0), text


def run_cli(esc_path, debt_path, out_path, batch):
    rc, text = build_draft(esc_path, debt_path, batch)
    if rc == 2:
        print("FAIL 账本收卷草案生成器：台账缺件/解析面断——不可证不产草案（rc=2）")
        return 2
    # 草案行数从正文实数（表行以 "| " + 编号 开头），不拿退出码充数——
    # 2026-11-04 主代理修正：原实现印「1 行草案」而实物 95 行，报告与实物不符。
    n_rows = sum(1 for ln in text.splitlines() if ln.startswith("| RT-E"))
    if out_path:
        tmp = out_path + ".tmp-%d" % os.getpid()
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, out_path)
        print("草案已写：%s（%d 行草案）" % (out_path, n_rows))
    else:
        sys.stdout.write(text)
    return rc


# ---------------------------------------------------------------- selftest --
def _w(d, name, text):
    p = os.path.join(d, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return p


D = "# 台账\n| 编号 | 欠什么 | 暴露自 | 验收门 | 批次归属 | 状态 |\n|---|---|---|---|---|---|\n"


def run_selftest(out):
    """夹具自测：零网络、零真台账。返回 0/1。"""
    d = tempfile.mkdtemp(prefix="ledger-close-draft-selftest-%d-" % os.getpid())
    fails = []
    try:
        E = "### RT-E{n}（low）夹具{n}\n- **修复对账**：%s\n"
        def esc(*specs):
            return "".join(E.format(n=n) % t for n, t in specs)

        # T1 能出草案行
        rc, txt = build_draft(_w(d, "e1.md", esc((1, "   **未修**：机制腿未见施工。"))),
                              _w(d, "d1.md", D), "账本机制批")
        if rc != 1 or "| RT-E1 |" not in txt:
            fails.append("T1 应出 RT-E1 草案行，得 rc=%d" % rc)

        # T2 已迁移（编号前缀 + 行文引用）不出
        d2 = _w(d, "d2.md", D + "| RT-E1 | 甲欠账 | 来源 | 门 | 批 | 未开始 |\n"
                                "| RT-E9 | 逃逸台账 RT-E2 残余 | 来源 | 门 | 批 | 未开始 |\n")
        rc, txt2 = build_draft(_w(d, "e2.md", esc((1, "   **未修**：x。"), (2, "   **未修**：y。"),
                                                  (3, "   **未修**：z。"))), d2, "账本机制批")
        if rc != 1 or "| RT-E1 |" in txt2 or "| RT-E2 |" in txt2 or "| RT-E3 |" not in txt2:
            fails.append("T2 已迁移两条应不出、RT-E3 应出，得 rc=%d" % rc)

        # T3 带豁免不出（理由非空）；T3b 欠账行= 实存不出/不存在照出；T3c 空理由照出
        d3 = _w(d, "d3.md", D + "| DEB-9 | 在册欠账 | 来源 | 门 | 批 | 未开始 |\n")
        rc, txt3 = build_draft(_w(d, "e3.md",
                                  esc((1, "   **未修**：a。\n- **账本迁移对账**：豁免=已在别册。"),
                                      (2, "   **未修**：b。\n- **账本迁移对账**：欠账行=DEB-9"),
                                      (3, "   **未修**：c。\n- **账本迁移对账**：欠账行=DEB-999"),
                                      (4, "   **未修**：d。\n- **账本迁移对账**：豁免="))),
                               d3, "账本机制批")
        if rc != 1 or "| RT-E1 |" in txt3 or "| RT-E2 |" in txt3:
            fails.append("T3 豁免/欠账行实存应不出，得 rc=%d" % rc)
        if "| RT-E3 |" not in txt3 or "| RT-E4 |" not in txt3:
            fails.append("T3 欠账行不存在/空理由应照出草案")

        # T4 缺件 fail-closed：rc=2 且零草案
        rc4, txt4 = build_draft(os.path.join(d, "缺件.md"), _w(d, "d4.md", D), "批")
        rc4b, txt4b = build_draft(_w(d, "e4b.md", esc((1, "   **未修**：x。"))),
                                  os.path.join(d, "缺欠账.md"), "批")
        if rc4 != 2 or txt4 or rc4b != 2 or txt4b:
            fails.append("T4 缺件应 rc=2 零草案，得 %d/%d" % (rc4, rc4b))

        # T5 草案全文不含「销项」措辞（含完成态词纪律）
        rc5, txt5 = build_draft(_w(d, "e5.md", esc((1, "   **部分修复可见**：残。\n- **账本迁移对账**：豁免=理由含销项二字。"),
                                                    (2, "   **未修**：x。"))),
                                _w(d, "d5.md", D), "账本机制批")
        if "销项" in txt5:
            fails.append("T5 草案全文不得含「销项」（豁免理由引用文也不得带入草案）")
        # 豁免理由里含「销项」的条目本身应已豁免不出——T5 双重断言
        if "| RT-E1 |" in txt5:
            fails.append("T5 带豁免条目应不出草案")
        # T5b 源标题自带「销项」→ 稿面替换为「清账登记」，草案仍零「销项」
        rc5b, txt5b = build_draft(_w(d, "e5b.md",
                                     "### RT-E5（medium）OBS回头 某行**销项**段再欠账\n"
                                     "- **修复对账**：   **未修**：残余。\n"),
                                  _w(d, "d5b.md", D), "账本机制批")
        if rc5b != 1 or "销项" in txt5b or "清账登记" not in txt5b:
            fails.append("T5b 源标题含销项应稿面替换为零销项草案，得 rc=%d" % rc5b)
        # T5c 完成态词族负例（2026-11-04 修补员 P1 钉）：源标题/引文含「已销/已修复可见/
        #      已闭合并部署/已落地」完成态变体 → 稿面替换，草案零完成态词
        rc5c, txt5c = build_draft(_w(d, "e5c.md",
                                     "### RT-E6（high）账本一致 欠账台账某行 ✅ 已销的唯一机核依据已不复现\n"
                                     "- **修复对账**：   **部分**：残余。\n"
                                     "### RT-E7（medium）某行已修复可见且已闭合并部署、机制②已落地\n"
                                     "- **修复对账**：   **未修**：残余。\n"),
                                  _w(d, "d5c.md", D), "账本机制批")
        if rc5c != 1:
            fails.append("T5c 应出草案行，得 rc=%d" % rc5c)
        for w in ("销项", "已销", "已收口", "已修复", "已闭合", "已落地", "已完成", "已完结"):
            if w in txt5c:
                fails.append("T5c 草案不得含完成态词「%s」" % w)
        for w in ("清账登记", "修复登记", "闭合登记", "落地登记"):
            if w not in txt5c:
                fails.append("T5c 完成态词应稿面替换为中性登记表述（缺「%s」）" % w)

        # T6 重复调用逐字节幂等
        e6 = _w(d, "e6.md", esc((1, "   **未修**：x。"), (2, "   **未做**：y。")))
        rcA, txtA = build_draft(e6, _w(d, "d6.md", D), "账本机制批")
        rcB, txtB = build_draft(e6, _w(d, "d6.md", D), "账本机制批")
        if rcA != rcB or txtA != txtB:
            fails.append("T6 重复调用应逐字节幂等")

        # T7 自认完结不出
        rc7, txt7 = build_draft(_w(d, "e7.md", esc((1, "   **已修复可见**：全落。"),
                                                    (2, "   **未修**：x。"))),
                                _w(d, "d7.md", D), "账本机制批")
        if rc7 != 1 or "| RT-E1 |" in txt7 or "| RT-E2 |" not in txt7:
            fails.append("T7 自认完结应不出、未修应出，得 rc=%d" % rc7)

        # T8 缺修复对账栏照出（不可静默跳过）
        rc8, txt8 = build_draft(_w(d, "e8.md", "### RT-E9（low）夹具9\n- **发现**：无栏。\n"),
                                _w(d, "d8.md", D), "账本机制批")
        if rc8 != 1 or "| RT-E9 |" not in txt8:
            fails.append("T8 缺修复对账栏应照出草案，得 rc=%d" % rc8)

        # T9 零条目 → rc=2；T9b id 重复 → rc=2（stderr 静默收集，不污染自测输出）
        import io
        from contextlib import redirect_stderr
        with redirect_stderr(io.StringIO()):
            rc9, txt9 = build_draft(_w(d, "e9.md", "# 无条目\n"), _w(d, "d9.md", D), "批")
        with redirect_stderr(io.StringIO()) as err9b:
            rc9b, txt9b = build_draft(_w(d, "e9b.md", esc((1, "   **未修**：x。")) + esc((1, "   **未修**：y。"))),
                                      _w(d, "d9b.md", D), "批")
        if "id 重复" not in err9b.getvalue():
            fails.append("T9b id 重复应在 stderr 点名解析面断")
        if rc9 != 2 or txt9 or rc9b != 2 or txt9b:
            fails.append("T9 零条目/id 重复应 rc=2 零草案，得 %d/%d" % (rc9, rc9b))

        # T10 触发词族索引不入草案（2026-11-05 E92 噪声清理批：欠账格停写「触发词=…」，
        #     触发词族改由门在红面点名时现算）、竖线安全化、引用材料剥离（引自他件的「未…」不计）
        rc10, txt10 = build_draft(_w(d, "e10.md",
                                     "### RT-E11（high）甲\n- **修复对账**：**已落地**（亲读）：他件自述"
                                     "「本条未见施工（引自他件）」；本条自认已闭合。\n"
                                     "### RT-E12（low）标题含|竖线\n- **修复对账**：**未复跑**（如实）：探针复跑未做。\n"),
                                  _w(d, "d10.md", D), "账本机制批")
        if rc10 != 1 or "| RT-E12 |" not in txt10:
            fails.append("T10 应出 RT-E12 草案行，得 rc=%d" % rc10)
        if "触发词=" in txt10 or "H:未复跑,未做" in txt10:
            fails.append("T10 草案不得含触发词族索引（触发词面已清·E92 噪声清理批）")
        if "| RT-E11 |" in txt10:
            fails.append("T10 引用材料内残余词不算本条残余（RT-E11 应不出）")
        if "标题含|竖线" in txt10 or "标题含／竖线" not in txt10:
            fails.append("T10 草案内竖线应安全化为全角斜杠")

        n_cases = 14
        if fails:
            out.append("FAIL selftest %d/%d 过：" % (n_cases - len(fails), n_cases))
            for f in fails:
                out.append("  " + f)
            return 1
        out.append("selftest %d/%d 过（出草案行/前缀+行文引用已迁移不出/豁免不出/欠账行实存不出·不存在照出/"
                   "空理由照出/缺件 rc2 零草案/草案无完成态措辞/幂等/自认完结不出/缺栏照出/零条目·id重复 rc2/"
                   "触发词族索引不入稿+竖线安全化+引用材料剥离/源题销项稿面替换/源题完成态词族稿面替换）" % (n_cases, n_cases))
        return 0
    finally:
        shutil.rmtree(d, ignore_errors=True)


def main(argv):
    out = []
    if "--selftest" in argv:
        rc = run_selftest(out)
        for ln in out:
            print(ln)
        return rc
    out_path = None
    if "--out" in argv:
        i = argv.index("--out")
        out_path = argv[i + 1] if i + 1 < len(argv) else None
        if not out_path:
            print("FAIL --out 需要路径参数")
            return 2
    batch = "账本机制批"
    if "--batch" in argv:
        i = argv.index("--batch")
        if i + 1 < len(argv):
            batch = argv[i + 1]
    return run_cli(ESC_PATH, DEBT_PATH, out_path, batch)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
