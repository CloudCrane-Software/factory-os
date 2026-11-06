#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""账本迁移对账门（欠账台账 ← 逃逸问题台账 迁移义务机器化；RT-E111 机制②最小落地）。

背景（确证发现 2026-11-02，账本一致，severity=medium）：终局轮 115 条确证发现中
逃逸台账自认未完结 30 条、其中 25 条在 阶段欠账台账.md 零行 → G5「欠账台账
RT-*/DEB-* 段清零留证」与终-② 的读数面只读一本账：欠账台账清零即可达标，而实债
（含 high 级 RT-E12 真实性链洞、RT-E94 根部冻结副本歧义）在另一本账里隐身。
两账间零迁移对账（grep "逃逸问题台账" tools/ 仅 3 处 docstring 背景引用），
迁移义务纯靠人工自觉——RT-E111 修复对账栏自认「对账门（机制①②③）未见施工」。

本门 = 机制②「迁移义务机器化」最小落地：逃逸台账每条按其「修复对账」栏自认状态
判定未完结者，必须 (a) 在欠账台账有行（编号前缀或行文引用），或 (b) 带显式机读
豁免标记；否则点名红。登记/修复写入逃逸台账的残余不再能对 G5 读数面隐身。

判据（单一源，本文档化；口径与确证发现亲跑对照一致——其点名 25 条零行未完结全部命中）：
  · 未完结判定（「修复对账」栏三类任一命中）：
      V 判决短语（栏内首个粗体 span；无粗体取首个冒号前段）含残余词：
        部分/未见/未修/未落/未开始/未复测/未提交/未达/待修复回报/仍为欠账/
        欠账本体未清/未回收/残项
      B 对账正文（判决短语之后）含自认未施工词：
        未见施工/仍未施工/仍为欠账/机制腿未落/欠账本体未清
      H 栏内自述残余（**全栏扫描**——2026-11-03 口径修正，见下「口径修正」段）：
        残余词表 = V 词表 ∪ 未核验族 ∪ 未落地族
          未核验族：未核/未复核/未逐行核/未逐行复核/未独立复核/未复跑
          未落地族：未施工/未收口/未动/未建/未接线/未做
        扫描面 = 「修复对账」栏全文（剥引用材料后）；命中即未完结。
      引用材料归属：栏内 「… 」/`…`/“…”/『…』 引自他件的材料（他件自述、被引
        代码注释、他人台账原文）不算本条自认残余——扫描前剥离（否则他件的
        「未…」被记到本条头上）。
  · 口径修正（2026-11-03，确证发现：账本一致，severity=high）：
      原口径把 13 个残余词**只匹配到「首个粗体 span」**（+ 正文 5 词），而多条
      逃逸条目的首个粗体是**行内强调或引文**而非判决短语——RT-E164「**全部裁决
      行**」、RT-E157「（登记员 2026-11-02 20:2x 亲读/亲测）」、RT-E166
      「**86eb3258**」、RT-E150「**任一在役树**」——判决短语落在栏内正文被无视：
      逃逸台账自认「部分落地/未修」且欠账台账零行的条目被判「自认完结」，实债对
      G5/终-② 读数面隐身（与本门自述目的直接冲突）。
      现口径 = 全栏扫描（H 层）＋ 词表扩至本台账实际残余用语。新增词逐条依据
      （逃逸台账登记员原话）：未逐行复核=RT-E104:851「（机制③）未逐行复核」、
      未核=RT-E114:922「**未核**：CH 历史重复记账清洗与对账门（机制②）」、
      未收口=RT-E150:1224「口径未收口（如实）」、未动/未建=RT-E166:1353
      「宿主 systemd 单元未建——宿主面未动」、未复跑=RT-E104:851「门实跑未复跑」、
      未做=RT-E89:745「探针复跑未做」、未接线=RT-E151:1238「消费腿未接线」。
      词表只增不减：V/B 旧口径原样保留（为其子集），无任何断言被弱化。
  · 覆盖判定：阶段欠账台账.md 存在行满足其一：
      编号前缀 = 该行编号列前缀恰为本条 id；或
      行文引用 = 行的**描述列**（编号/欠什么/暴露自 前三格）内含本条 id
      （词边界 RT-E<n>(?![0-9])——防 RT-E1 误配 RT-E116 类子串；
      验收门/状态列附注里的顺带提及不算迁移——欠账的描述面不带它=没迁它）。
  · 豁免判定：条目「修复对账」栏内含机读标记行（RT-E111 机制②的标记形态）：
      - **账本迁移对账**：豁免=<非空理由>        → 豁免（理由须回显可审）
      - **账本迁移对账**：欠账行=<欠账台账编号>  → 该编号须实存于欠账台账，否则红
  · 红 = 未完结 ∧ 无覆盖 ∧ 无豁免（逐条点名 id+逃逸台账行号+触发词）。
  · fail-closed：台账缺件/逃逸台账零条目可解析 → rc=2 不可证不猜绿；
    条目缺「修复对账」栏 → 视为未完结点名红（不许静默跳过）。

模式：
  （无参）    对真台账对账。exit 0=绿；1=红（点名清单）；2=不可证（环境错）。
  --selftest  内嵌夹具自测（零网络、零真台账读取），覆盖：解析/V 判/B 判/前缀覆盖/
              行文引用覆盖（含 RT-E1 vs RT-E116 子串陷阱）/豁免标记/欠账行标记/
              缺修复对账栏红/缺件 rc=2/绿路/全栏扫描（首个粗体非判决短语）/
              扩词表命中/引用材料归属/B 层不回归/处置面豁免族（豁免源表头定位处置
              列·多值歧义行按处置列取值·descope 不豁免·表头缺列 fail-closed 必红·
              字段数不足必红）。全过 exit 0。
  · 豁免源列绑定（2026-11-03 独立复核整改，severity=high）：旧豁免解析从行内
    **任意单元格**取首个处置值——复核负例：处置表行「备注列=销项、处置列=
    descope」被误取备注列的「销项」计豁免 → 本应红的 descope 行假绿（亲跑复现
    parsed={'RT-E94':'销项'}、rc=0）。现口径=先解析表头定位「编号」「处置」两列
    列号，行值只从定位列取；表头缺列/列号越界/行字段数不足 → fail-closed（回退
    无豁免源严判并 WARN 点名，不回退任意单元格猜测）；descope 属待人类签认不计
    豁免（只有 销项/迁移 计豁免，原样收紧不变）。回归负例并入 selftest
    （21→25 例）。

被修对象零改动：两本台账是本门的被对账数据面，本门只读；all-gates.sh 零改动
（L2 以 tools/test-*.py glob 自动收编本件，test-manifest.list 增行+声明同步）。
改前留档：本批 .20261102-pre-账本迁移门.bak 四件（两台账+清单+变更日志）。
"""
import os
import re
import sys
import tempfile
import shutil

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ESC_PATH = os.path.join(WS, "计划", "研究组", "红队终局轮-20261101", "逃逸问题台账.md")
DEBT_PATH = os.path.join(WS, "计划", "阶段欠账台账.md")
# 豁免源（2026-11-03 J5 判据源变更·主代理裁决）：项目部处置面——欠账正本 73 行的四值
# 处置层（销项/descope/迁移/在飞）。'销项/迁移'计豁免（销项=行内存收卷证据、迁移=建设期
# 批承接，均不再要求逃逸侧另行标记）；'descope/在飞'不豁免（descope 待人类签认、在飞
# 仍属现役欠账——门不替运营者签认）。该面只覆盖欠账正本 73 行（对逃逸侧未迁移行无效，
# 后者仍红=真实迁移义务缺口，红名单基线登记·归属账本机制批 RT-E111/E119 簇）。
# 解析纪律（2026-11-03 独立复核整改·J5-修复员）：处置值只从**表头定位的「处置」列**
# 取——旧实现从任意单元格取首个处置值，复核负例（备注列=销项、处置列=descope）被
# 误判豁免假绿；现表头缺「编号+处置」列/列号越界/行字段数不足一律 fail-closed 严判，
# 不回退到任意单元格猜测。
DISP_PATH = os.path.join(WS, "00-项目部", "欠账处置-20261103.md")
DISP_EXEMPT_VALUES = ("销项", "迁移")
# 处置面四值全集（解析层入库用；豁免判定只认 DISP_EXEMPT_VALUES——descope 待人类
# 签认、在飞属现役欠账，均不计豁免）。
DISP_ALL_VALUES = ("销项", "迁移", "descope", "在飞")
# markdown 表分隔行（|---|---|）——表头行识别用（2026-11-03 复核整改：处置列按表头绑定）
DISP_SEP_RE = re.compile(r"^\|[-: |]+$")
ID_CELL_RE = re.compile(r"^(RT-E\d+(?:-[A-Za-z0-9]+)?|D2-\d|P3-[A-Z]\d|OPS-\d|OBS-D\d|"
                        r"DEB-\d+[ab]?|RT-C\d+?|RT-C\d+-[A-Z0-9]+|RT-PP\d)$")

HDR_RE = re.compile(r"^### (RT-E\d+)(?:-[A-Za-z0-9]+)?（")
REPAIR_RE = re.compile(r"- \*\*修复对账\*\*[:：]?(.*?)(?=\n### |\Z)", re.S)
BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
MARKER_RE = re.compile(r"^- \*\*账本迁移对账\*\*[:：]\s*(.+)$", re.M)

# 未完结判定词表（文档化；与确证发现判定口径对照亲跑一致）
VERDICT_KW = ("部分", "未见", "未修", "未落", "未开始", "未复测", "未提交", "未达",
              "待修复回报", "仍为欠账", "欠账本体未清", "未回收", "残项")
BODY_KW = ("未见施工", "仍未施工", "仍为欠账", "机制腿未落", "欠账本体未清")
# 栏内自述残余词表（2026-11-03 增补，词表只增不减）：V 词表 ∪ 未核验族 ∪ 未落地族。
# 增补依据＝逃逸台账登记员自认未完结的原话（逐条依据见 docstring「口径修正」段）：
#   未核验族：未核/未复核/未逐行核/未逐行复核/未独立复核/未复跑
#   未落地族：未施工/未收口/未动/未建/未接线/未做
RESIDUAL_KW = VERDICT_KW + ("未核", "未复核", "未逐行核", "未逐行复核", "未独立复核",
                             "未复跑", "未施工", "未收口", "未动", "未建", "未接线", "未做")
# 引用材料（引自他件的文字：他件自述、被引代码注释、他人台账原文）——不算本条
# 自认残余；扫描前剥离（否则他件的「未…」被记到本条头上）。
QUOTE_RE = re.compile(r"「[^」]*」|`[^`]*`|“[^”]*”|『[^』]*』", re.S)


def parse_escape(path):
    """解析逃逸台账：[(id, line_no, repair_text)]。"""
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    entries = []
    cur = None
    for i, ln in enumerate(lines, 1):
        m = HDR_RE.match(ln)
        if m:
            if cur:
                entries.append(cur)
            cur = {"id": m.group(1), "line": i, "buf": []}
        elif cur is not None:
            cur["buf"].append(ln)
    if cur:
        entries.append(cur)
    out = []
    for e in entries:
        txt = "\n".join(e["buf"])
        m = REPAIR_RE.search(txt)
        rep = m.group(1).strip() if m else ""
        out.append((e["id"], e["line"], rep))
    return out


def parse_debt(path):
    """解析欠账台账：[(编号, 描述列文本)]（仅 | 开头的表行；描述列=编号/欠什么/暴露自）。"""
    rows = []
    with open(path, encoding="utf-8") as f:
        for ln in f:
            if ln.startswith("| "):
                cells = ln.split("|")
                cid = cells[1].strip() if len(cells) > 1 else ""
                # 描述列=编号/欠什么/暴露自（前三格）；验收门/状态列附注不计入覆盖面
                desc = "|".join(c.strip() for c in cells[1:4])
                rows.append((cid, desc))
    return rows


def parse_disposition(path):
    """解析项目部处置面（00-项目部/欠账处置-20261103.md）→ ({编号: 处置值}, [WARN串])。

    2026-11-03 独立复核整改（J5-修复员）：**先解析表头定位列号，只取定位列**。
    旧实现从行内**任意单元格**取首个处置值——复核负例：表 `|编号|备注|处置|`
    行「备注列=销项、处置列=descope」被误取 备注 的「销项」计豁免 → 假绿。
    现口径（逐表绑定，不猜测）：
      · 表头行 = 「| 」行且次行为分隔行（|---|…）；表头须**同时**含「编号」格与
        「处置」格（整格相等）方为处置表，两格列号即该表的绑定列；
      · 行取值只从绑定列：编号列整格 ID_CELL_RE=编号；处置列整格 ∈ DISP_ALL_VALUES
        =处置值（descope/在飞 照实入库，**豁免与否由 judge() 按 DISP_EXEMPT_VALUES
        只认 销项/迁移**——descope 待人类签认不计豁免）；
      · 行字段数不足/列号越界 → 该行**不取值不猜测**（fail-closed，计数入 WARN）；
      · 全文件无「编号+处置」表头（表头缺该列/结构面被改）→ **整体 fail-closed**：
        disp={} 回退无豁免源严判 + WARN 点名——绝不回退到任意单元格取值。
    缺件/不可读 → (None, [])，由调用方在输出面点名（豁免源缺件不静默降级，但也不因
    缺件拒跑：欠账台账覆盖与显式标记两条既有判定腿不受影响——豁免源是第三条
    **加严方向的可选腿**，其失效只回退到「无豁免源」的严判，不产生假绿）。
    """
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return None, []
    disp = {}
    warns = []
    n_short = 0
    bound_any = False
    n = len(lines)
    i = 0
    while i < n:
        ln = lines[i]
        if ln.startswith("| ") and i + 1 < n and DISP_SEP_RE.match(lines[i + 1].strip()):
            cells = [c.strip() for c in ln.split("|")]
            id_idx = next((k for k, c in enumerate(cells) if c == "编号"), None)
            val_idx = next((k for k, c in enumerate(cells) if c == "处置"), None)
            if id_idx is not None and val_idx is not None:
                bound_any = True
                need = max(id_idx, val_idx)
                j = i + 2
                while j < n and lines[j].startswith("| "):
                    rcells = [c.strip() for c in lines[j].split("|")]
                    if len(rcells) <= need:
                        n_short += 1  # 字段数不足/列号越界：该行不取值不猜测
                    elif ID_CELL_RE.fullmatch(rcells[id_idx]):
                        val = rcells[val_idx]
                        if val in DISP_ALL_VALUES:
                            disp[rcells[id_idx]] = val
                    j += 1
                i = j
                continue
        i += 1
    if not bound_any:
        warns.append("豁免源表头无「编号+处置」列（处置列定位失败）——第三腿整体回退为"
                     "无豁免源严判（不取任意单元格，fail-closed）")
    if n_short:
        warns.append("豁免源 %d 行字段数不足（处置列列号越界）——该批行不取值不猜测"
                     "（fail-closed）" % n_short)
    return disp, warns


def covered_by(eid, rows):
    """覆盖判定：编号前缀 或 描述列行文引用（词边界）。返回命中说明，无则 None。"""
    for cid, _desc in rows:
        m = re.match(r"(RT-E\d+)", cid)
        if m and m.group(1) == eid:
            return "编号前缀:%s" % cid
    pat = re.compile(eid + r"(?![0-9])")
    for cid, desc in rows:
        if pat.search(desc):
            return "行文引用:%s" % cid
    return None


def exemption_marker(eid, rep, rows):
    """豁免标记判定。返回 (豁免?, 说明)。欠账行= 形态要求编号实存。"""
    ok = None
    for m in MARKER_RE.finditer(rep):
        body = m.group(1)
        if body.startswith("豁免="):
            reason = body[len("豁免="):].strip()
            if reason:
                return (True, "豁免标记（理由：%s）" % reason[:60])
            ok = (False, "豁免标记理由为空——不算豁免")
        elif body.startswith("欠账行="):
            target = body[len("欠账行="):].strip()
            if any(cid == target for cid, _ in rows):
                return (True, "欠账行标记→%s（实存）" % target)
            ok = (False, "欠账行标记→%s 在欠账台账不存在——不算豁免" % target)
    if ok:
        return ok
    return (False, "无标记")


def judge(entries, rows, disp=None):
    """主判定：返回 (reds, stats)。reds=[(id, line, 触发说明, 类别)]。

    disp=项目部处置面 {编号: 处置值}（None/空=无豁免源，判据不回退只少一条豁免腿）。
    """
    disp = disp or {}
    reds = []
    n_unfin = n_cov = n_exp = n_dexp = 0
    for eid, line, rep in entries:
        cov = covered_by(eid, rows)
        if not rep:
            if cov:
                n_unfin += 1
                n_cov += 1
                continue
            if disp.get(eid) in DISP_EXEMPT_VALUES:
                n_dexp += 1
                continue
            reds.append((eid, line, "缺「修复对账」栏——不可判即欠账面未对账", "无栏"))
            continue
        b = BOLD_RE.search(rep)
        verdict = b.group(1) if b else rep.split("：")[0][:40]
        # 剥引用材料（引自他件的文字不算本条自认残余）——B/H 两层同口径
        own = QUOTE_RE.sub(" ", rep)
        body = QUOTE_RE.sub(" ", rep[len(b.group(0)):]) if b else own
        vh = [k for k in VERDICT_KW if k in verdict]
        bh = [k for k in BODY_KW if k in body]
        # H 层（2026-11-03 口径修正）：全栏扫描，不再只认「首个粗体 span」
        hh = [k for k in RESIDUAL_KW if k in own]
        if not vh and not bh and not hh:
            continue  # 修复对账自认完结，不要求迁移
        n_unfin += 1
        if cov:
            n_cov += 1
            continue
        exp, expmsg = exemption_marker(eid, rep, rows)
        if exp:
            n_exp += 1
            continue
        if disp.get(eid) in DISP_EXEMPT_VALUES:
            n_dexp += 1
            continue
        trig = []
        if vh:
            trig.append("V判决:%s" % ",".join(vh))
        if bh:
            trig.append("B正文:%s" % ",".join(bh))
        hnew = [k for k in hh if k not in vh]
        if hnew:
            trig.append("H栏内:%s" % ",".join(hnew))
        reds.append((eid, line, "触发=%s；%s" % ("+".join(trig), expmsg), "未完结"))
    return reds, {"entries": len(entries), "unfinished": n_unfin,
                  "covered": n_cov, "exempt": n_exp, "disp_exempt": n_dexp,
                  "rows": len(rows)}


def run_check(esc_path, debt_path, out, disp_path=None):
    if not os.path.isfile(esc_path) or not os.path.isfile(debt_path):
        out.append("FAIL 账本迁移对账门：台账缺件（逃逸=%s 欠账=%s）——不可证不猜绿（rc=2）"
                   % (os.path.isfile(esc_path), os.path.isfile(debt_path)))
        return 2
    entries = parse_escape(esc_path)
    if not entries:
        out.append("FAIL 账本迁移对账门：逃逸台账零条目可解析（### RT-E 头零命中）——解析面断=不可证（rc=2）")
        return 2
    rows = parse_debt(debt_path)
    disp, dwarns = parse_disposition(disp_path) if disp_path else ({}, [])
    for w in dwarns:
        out.append("WARN " + w)
    if disp_path and disp is None:
        out.append("WARN 豁免源不可读（%s）——第三腿回退为无豁免源严判（不产生假绿）" % disp_path)
        disp = {}
    reds, st = judge(entries, rows, disp)
    out.append("账本迁移对账门：逃逸台账 %d 条；修复对账自认未完结 %d（有欠账行 %d + 显式豁免 %d + 处置面豁免 %d）；欠账台账 %d 行；豁免源 %s。"
               % (st["entries"], st["unfinished"], st["covered"], st["exempt"],
                  st["disp_exempt"], st["rows"],
                  ("%d 行（表头定位处置列；销项/迁移计豁免）" % len(disp)) if disp_path else "未接"))
    if reds:
        out.append("FAIL 未完结∧欠账台账零行∧未豁免 = %d 条（对 G5/终-② 读数面隐身的实债，须迁移入账或带标记豁免）：" % len(reds))
        for eid, line, msg, _cat in reds:
            out.append("  %s  逃逸台账:%d  %s" % (eid, line, msg))
        out.append("结论：红（迁移义务未履行）")
        return 1
    out.append("结论：绿（未完结条目全部在欠账台账有行、带显式豁免标记或处置面销项/迁移）")
    return 0


# ---------------------------------------------------------------- selftest --
def _w(d, name, text):
    p = os.path.join(d, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return p


def run_selftest(out):
    """夹具自测：零网络、零真台账。返回 0/1。"""
    d = tempfile.mkdtemp(prefix="ledger-recon-selftest-%d-" % os.getpid())
    fails = []
    buf = []  # 夹具逐项输出收局部缓冲，不污染门日志
    try:
        E = "### RT-E1（low）夹具条目甲\n- **修复对账**：%s\n"
        def esc(*items):
            return "".join(E % t for t in items)

        # T1 V 判决词红：无欠账行 → 红
        p1 = _w(d, "e1.md", esc("   **部分修复可见**（亲读）：机制腿未见施工。"))
        d1 = _w(d, "d1.md", "# 台账\n| 编号 | 欠什么 |\n|---|---|\n| DEB-9 | x |\n")
        rc = run_check(p1, d1, buf)
        if rc != 1:
            fails.append("T1 未完结零行应红 rc=1，得 %d" % rc)

        # T2 B 正文词红：判决已落但正文自认未施工 → 红
        p2 = _w(d, "e2.md", esc("   **已落地**（亲读）：收口完毕；机制①②③未见施工。"))
        rc = run_check(p2, d1, buf)
        if rc != 1:
            fails.append("T2 正文自认未施工应红 rc=1，得 %d" % rc)

        # T3 绿路：修复对账自认完结（无残余词）且无行 → 不要求迁移，绿
        p3 = _w(d, "e3.md", esc("   **已修复可见**（亲读）：全落。"))
        rc = run_check(p3, d1, buf)
        if rc != 0:
            fails.append("T3 自认完结零行应绿 rc=0，得 %d" % rc)

        # T4 编号前缀覆盖：未修 + 有行 → 绿
        p4 = _w(d, "e4.md", "### RT-E94（low）夹具条目乙\n- **修复对账**：   **未修**（亲读）：未见。\n")
        d4 = _w(d, "d4.md", "# 台账\n| RT-E94 | 逃逸台账 RT-E94 残余 |\n")
        rc = run_check(p4, d4, buf)
        if rc != 0:
            fails.append("T4 前缀覆盖应绿 rc=0，得 %d" % rc)

        # T5 行文引用覆盖 + 子串陷阱：RT-E118 被 RT-E32-XCARD 行文覆盖；
        #    RT-E1 不得被「RT-E116」子串误覆盖
        p5 = _w(d, "e5.md",
                "### RT-E118（high）甲\n- **修复对账**：   **部分收敛**：残余待清。\n"
                "### RT-E1（low）乙\n- **修复对账**：   **未见修复痕迹**：未修。\n")
        d5 = _w(d, "d5.md", "# 台账\n| RT-E32-XCARD | 逃逸台账 RT-E118 新类欠账 |\n| RT-E116 | otel |\n")
        rc = run_check(p5, d5, buf)
        if rc != 1:
            fails.append("T5 应恰红 RT-E1 一条 rc=1，得 %d" % rc)

        # T5b 描述列限定：id 只在验收门/状态列附注提及 → 不算覆盖 → 红
        p5b = _w(d, "e5b.md", "### RT-E98（low）夹具条目丁\n- **修复对账**：   **已落**：机制①未见施工。\n")
        d5b = _w(d, "d5b.md", "# 台账\n| OBS-D4 | 判据面缺口 | 观察期收口 | 顺带提及 RT-E98 的勘正注 | ✅ |\n")
        rc = run_check(p5b, d5b, buf)
        if rc != 1:
            fails.append("T5b 描述列外顺带提及不算覆盖应红 rc=1，得 %d" % rc)

        # T6 豁免标记（理由非空）→ 绿
        p6 = _w(d, "e6.md", esc("   **部分修复可见**：残余边界。\n- **账本迁移对账**：豁免=残余已在别册登记（见 x 台账 y 行）。"))
        rc = run_check(p6, d1, buf)
        if rc != 0:
            fails.append("T6 豁免标记应绿 rc=0，得 %d" % rc)

        # T7 欠账行=标记：指向实存编号绿；指向不存在红
        p7 = _w(d, "e7.md", esc("   **部分修复可见**：残。\n- **账本迁移对账**：欠账行=DEB-9"))
        rc = run_check(p7, d1, buf)
        if rc != 0:
            fails.append("T7 欠账行标记指向实存编号应绿 rc=0，得 %d" % rc)
        p7b = _w(d, "e7b.md", esc("   **部分修复可见**：残。\n- **账本迁移对账**：欠账行=RT-E999"))
        rc = run_check(p7b, d1, buf)
        if rc != 1:
            fails.append("T7b 欠账行标记指向不存在应红 rc=1，得 %d" % rc)

        # T8 缺「修复对账」栏 → 红（不可静默跳过）
        p8 = _w(d, "e8.md", "### RT-E42（low）夹具条目丙\n- **发现**：无修复对账栏的条目。\n")
        rc = run_check(p8, d1, buf)
        if rc != 1:
            fails.append("T8 缺修复对账栏应红 rc=1，得 %d" % rc)

        # T9 fail-closed：逃逸件缺 / 零条目 → rc=2
        rc = run_check(os.path.join(d, "缺件.md"), d1, buf)
        if rc != 2:
            fails.append("T9a 台账缺件应 rc=2，得 %d" % rc)
        p9 = _w(d, "e9.md", "# 只有说明，没有条目\n")
        rc = run_check(p9, d1, buf)
        if rc != 2:
            fails.append("T9b 零条目应 rc=2，得 %d" % rc)

        # T10 空理由豁免不算豁免 → 红
        p10 = _w(d, "e10.md", esc("   **未修**：x。\n- **账本迁移对账**：豁免="))
        rc = run_check(p10, d1, buf)
        if rc != 1:
            fails.append("T10 空理由豁免应红 rc=1，得 %d" % rc)

        # T11 全栏扫描（2026-11-03 口径修正）：首个粗体 span 是行内强调/引文而
        #     非判决短语时，栏内自认残余仍须红（改前只匹配首个粗体 span → 漏检，
        #     即逃逸台账自认「部分落地」且欠账台账零行的条目被判「自认完结」）
        p11 = _w(d, "e11.md",
                 "### RT-E7（medium）甲\n- **修复对账**：**全部裁决行**（亲读）："
                 "消费腿未施工——门本体在、无调度无门位（部分修复，如实）。\n")
        rc = run_check(p11, d1, buf)
        if rc != 1:
            fails.append("T11 首个粗体非判决短语时栏内残余应红 rc=1，得 %d" % rc)

        # T11b 扩词表命中（未核/未收口族——原 13 词覆盖不到的自认残余）→ 红
        p11b = _w(d, "e11b.md",
                  "### RT-E9（high）乙\n- **修复对账**：（登记员亲读）：CH 历史重复记账"
                  "清洗与对账门**未核**（如实）；口径未收口（如实）。\n")
        rc = run_check(p11b, d1, buf)
        if rc != 1:
            fails.append("T11b 扩词表残余词应红 rc=1，得 %d" % rc)

        # T12 引用材料（引自他件）内的残余词不算本条自认残余 → 绿
        p12 = _w(d, "e12.md",
                 "### RT-E11（low）丙\n- **修复对账**：**已落地**（亲读）：他件自述"
                 "「本条未见施工（引自他件原文）」；本条自认已闭合。\n")
        rc = run_check(p12, d1, buf)
        if rc != 0:
            fails.append("T12 引用材料内残余词不算本条残余应绿 rc=0，得 %d" % rc)

        # T13 B 正文层不回归：「仍未施工」不在扩词表，仍须红（B 层原样保留）
        p13 = _w(d, "e13.md",
                 "### RT-E12（low）丁\n- **修复对账**：**已落地**（亲读）："
                 "机制①仍未施工。\n")
        rc = run_check(p13, d1, buf)
        if rc != 1:
            fails.append("T13 B正文层「仍未施工」应红 rc=1，得 %d" % rc)

        # T14 处置面豁免（2026-11-03 J5 判据源变更·主代理裁决）：项目部处置面
        #     处置列=销项/迁移 → 豁免；descope/在飞 不豁免（descope 待人类签认、
        #     在飞仍属现役欠账）；行文提及不算（编号格整格匹配）
        d14 = _w(d, "disp14.md",
                 "# 处置面\n| # | 编号 | 正本:行 | 现状态 | 处置 | 去向 |\n"
                 "|---|---|---|---|---|---|\n"
                 "| 1 | RT-E90 | :5 | 部分 | 销项 | 行内存收卷证据 |\n"
                 "| 2 | RT-E91 | :6 | 未开始 | 迁移 | 建设期·逃逸拦截批 |\n"
                 "| 3 | RT-E92 | :7 | 部分 | descope | 待人类签认 |\n"
                 "| 4 | RT-E93 | :8 | 未开始 | 在飞 | J0 承接 |\n")
        p14 = _w(d, "e14.md",
                 "### RT-E90（low）甲\n- **修复对账**：   **未修**：残余。\n"
                 "### RT-E91（low）乙\n- **修复对账**：   **未修**：残余。\n"
                 "### RT-E92（low）丙\n- **修复对账**：   **未修**：残余。\n"
                 "### RT-E93（low）丁\n- **修复对账**：   **未修**：残余。\n")
        rc = run_check(p14, d1, buf, disp_path=d14)
        if rc != 1:
            fails.append("T14 处置面仅销项/迁移计豁免应恰红 descope/在飞 2 条 rc=1，得 %d" % rc)
        # T14b 无处置面（disp_path=None）时全部红——豁免源缺席=回退严判，不产生假绿
        b14b = []
        rc = run_check(p14, d1, b14b)
        n_red = sum(1 for ln in b14b if ln.startswith("  RT-E9"))
        if rc != 1 or n_red != 4:
            fails.append("T14b 无豁免源应红 4 条 rc=1，得 rc=%d 红=%d" % (rc, n_red))
        # T14c 处置面缺件 → 回退严判 + WARN 点名（不 rc=2：豁免源是加严方向可选腿）
        rc = run_check(p14, d1, buf, disp_path=os.path.join(d, "缺件-处置面.md"))
        if rc != 1:
            fails.append("T14c 豁免源缺件应回退严判红 rc=1，得 %d" % rc)
        # T14d 行文提及不算豁免：正文提「RT-E94」但无编号格 → 仍红
        d14d = _w(d, "disp14d.md",
                  "# 处置面\n| # | 编号 | 处置 |\n|---|---|---|\n"
                  "| 1 | 别的行 | 正文提及 RT-E94 已处置（行文不算） |\n")
        p14d = _w(d, "e14d.md", "### RT-E94（low）戊\n- **修复对账**：   **未修**：残余。\n")
        rc = run_check(p14d, d1, buf, disp_path=d14d)
        if rc != 1:
            fails.append("T14d 行文提及不算处置豁免应红 rc=1，得 %d" % rc)

        # T15 处置列表头绑定·多值歧义行按处置列取值（2026-11-03 独立复核整改·复核
        #     负例回归）：备注列=销项、处置列=descope 的行——旧实现任意单元格取值
        #     误取备注列「销项」计豁免假绿（亲跑复现 parsed={'RT-E94':'销项'} rc=0）；
        #     现按表头定位的处置列取「descope」→ 不豁免（descope 待人类签认）→ 红
        d15 = _w(d, "disp15.md",
                 "# 处置面\n| # | 编号 | 正本:行 | 备注 | 处置 | 去向 |\n"
                 "|---|---|---|---|---|---|\n"
                 "| 1 | RT-E94 | :5 | 销项 | descope | 待人类签认 |\n")
        p15 = _w(d, "e15.md", "### RT-E94（high）己\n- **修复对账**：   **未修**：残余。\n")
        b15 = []
        rc = run_check(p15, d1, b15, disp_path=d15)
        if rc != 1:
            fails.append("T15 多值歧义行应按处置列取值（descope 不豁免）应红 rc=1，得 %d" % rc)
        if not any("处置面豁免 0" in ln for ln in b15):
            fails.append("T15 歧义行不得计处置面豁免（读数应=0）")

        # T15b 表头绑定反例：非处置列含「descope」、处置列=销项 → 豁免绿
        #     （证明取值只认处置列，两个方向都钉死）
        d15b = _w(d, "disp15b.md",
                  "# 处置面\n| # | 编号 | 正本:行 | 备注 | 处置 | 去向 |\n"
                  "|---|---|---|---|---|---|\n"
                  "| 1 | RT-E94 | :5 | descope（备注面提法） | 销项 | 行内收卷 |\n")
        rc = run_check(p15, d1, buf, disp_path=d15b)
        if rc != 0:
            fails.append("T15b 处置列=销项应豁免绿 rc=0，得 %d" % rc)

        # T15c 表头缺「处置」列 → fail-closed 必红（回退无豁免源严判+WARN，
        #     绝不回退任意单元格猜测——即使行里摆着「销项」也不取）
        d15c = _w(d, "disp15c.md",
                  "# 处置面（表头被改坏：处置列更名）\n| # | 编号 | 状态 |\n|---|---|---|\n"
                  "| 1 | RT-E94 | 销项 |\n")
        b15c = []
        rc = run_check(p15, d1, b15c, disp_path=d15c)
        if rc != 1:
            fails.append("T15c 表头缺处置列应 fail-closed 红 rc=1，得 %d" % rc)
        if not any("处置列定位失败" in ln for ln in b15c):
            fails.append("T15c 表头缺处置列应 WARN 点名定位失败")

        # T15d 行字段数不足/处置列列号越界 → 该行 fail-closed 不取值 → 必红+WARN
        d15d = _w(d, "disp15d.md",
                  "# 处置面\n| # | 编号 | 正本:行 | 现状态 | 处置 |\n"
                  "|---|---|---|---|---|\n"
                  "| 1 | RT-E94 | :5 |\n")
        b15d = []
        rc = run_check(p15, d1, b15d, disp_path=d15d)
        if rc != 1:
            fails.append("T15d 行字段数不足应不取值红 rc=1，得 %d" % rc)
        if not any("字段数不足" in ln for ln in b15d):
            fails.append("T15d 行字段数不足应 WARN 计数点名")

        n_cases = 25
        if fails:
            out.append("FAIL selftest %d/%d 过：" % (n_cases - len(fails), n_cases))
            for f in fails:
                out.append("  " + f)
            return 1
        out.append("selftest %d/%d 过（解析/V判/B判/前缀覆盖/行文引用+子串陷阱/描述列限定/豁免标记/"
                   "欠账行标记/缺栏红/fail-closed×2/空理由红/全栏扫描/扩词表/引用材料归属/B层不回归/"
                   "处置面豁免·销项迁移/无豁免源回退严判/豁免源缺件回退/行文提及不算豁免/"
                   "表头定位处置列·歧义行按处置列取值/处置列销项豁免反例/表头缺列fail-closed红/"
                   "字段数不足fail-closed红）"
                   % (n_cases, n_cases))
        return 0
    finally:
        shutil.rmtree(d, ignore_errors=True)


def main(argv):
    out = []
    if "--selftest" in argv:
        rc = run_selftest(out)
    else:
        rc = run_check(ESC_PATH, DEBT_PATH, out, disp_path=DISP_PATH)
    for ln in out:
        print(ln)
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
