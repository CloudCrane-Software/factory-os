#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""账本止增门（增量门：逃逸问题台账新增条目 ↔ 欠账台账/豁免标记 对账；账本机制批 2026-11-04）。

背景：账本迁移对账门（tools/test-ledger-migration-recon.py，本门不改不引用）对**存量**95 红
逐条点名——那是迁移义务的存量清偿面。但逃逸台账在持续增生：新登记一条实修残余，只要
「修复对账」栏自认未完结且欠账台账无行，就又造出一笔对 G5/终-② 读数面隐身的实债——
存量的清偿被增量不断回填，两门若都点名全量还会互相打架（同一 id 两门重复点名）。

本门 = **增量口封堵**：以一份基线清单（生成时点的全部 RT-E id 快照，含生成时点与条目数）
为基准，**只对基线之后新增**的条目判红；存量条目（基线内 id）一概不由本门点名（由迁移门
管），避免两门重复点名。基线快照：30-工件/账本机制批-20261104/ledger-growth-baseline.json
（账本机制批 2026-11-04 生成；再生成用 --write-baseline，见下维护契约）。

判据（与迁移门同族的机读标记形态，单一源文档化）：
  · 新增判定：现读逃逸台账解析出的 RT-E id 集合 − 基线 id 集合 = 新增 id（id 词形
    `### RT-E<n>（`（HDR 同迁移门正则族）；基线内 id 一概不判（存量不点名）。
  · 红判定（对每条新增条目，三类依次判，任一命中即绿）：
      (a) 欠账台账覆盖：存在行满足其一——
            编号前缀 = 该行编号列前缀恰为本条 id（`^(RT-E\d+)`）；
            行文引用 = 该行**描述列**（编号/欠什么/暴露自前三格）含本条 id
            （词边界 RT-E<n>(?![0-9])，防 RT-E1 误配 RT-E116 类子串；
            验收门/状态列附注的顺带提及不算——欠账的描述面不带它=没迁它）。
      (b) 显式机读豁免标记（修复对账栏内，形态同迁移门 RT-E111 机制②）：
            `- **账本迁移对账**：豁免=<非空理由>`    → 豁免（理由须回显可审）；
            `- **账本迁移对账**：欠账行=<编号>`      → 该编号须实存于欠账台账，否则红。
      (c) 条目缺「修复对账」栏 → 视为未完结点名红（不可静默跳过，同迁移门口径）。
    无覆盖 ∧ 无豁免（或缺栏）→ 红，逐条点名 id+逃逸台账行号+触发说明。
  · 增量纪律：只点名新增；输出行明示「存量 N 条不判（迁移门管）」防读数误读。
  · 回退知情（非红面）：基线内 id 从台账消失（删条）→ 计数回显为 INFO 行（删条不属
    本门红面，但须可见——删逃逸条目而不留痕是另一条逃逸通道，由人工/巡检处置）。
  · fail-closed（rc=2 不可证不猜绿）：逃逸台账/欠账台账/基线清单缺件、基线坏 JSON、
    基线无 ids 字段、逃逸台账零条目可解析、条目 id 重复出现（解析面断）。
  · 本门只读：两本台账与基线是本门的被对账数据面，零改动；不消费项目部处置面
    （欠账处置-20261103.md）——处置面是迁移门的第三腿（存量销项签认面），新增条目
    在处置面无行，引入只会造成「处置面缺行=可豁免」的假豁免通道。

模式：
  （无参）        对真台账对账。exit 0=绿（新增条目全部有欠账行或带豁免，或零新增）；
                  1=红（点名清单）；2=不可证（环境错，fail-closed）。
  --selftest      内嵌夹具自测（零网络、零真台账读取），覆盖：新增未迁移→红 /
                  新增已迁移→绿 / 新增带豁免（理由非空）→绿 / 空理由豁免→红 /
                  欠账行= 指向实存→绿·指向不存在→红 / 基线缺件→rc=2 / 基线坏
                  JSON→rc=2 / 台账缺件→rc=2 / 零条目→rc=2 / 存量条目不被重复点名
                  （≥2 条存量带残余不进红面）/ 缺修复对账栏→红 / 描述列外顺带提及
                  不算覆盖→红 / id 词边界（RT-E1 不被 RT-E116 覆盖）→红 / 删条
                  INFO 回显。全过 exit 0。
  --write-baseline [--force]
                  把当刻真台账 RT-E id 快照写入基线 JSON（含生成时点/条目数/台账
                  sha256）；基线已存在时拒写（须 --force 显式覆盖——基线是止增口径
                  的锚，覆盖即重置增量口径，必须显式）。
维护契约：每次「存量红面清偿收卷」或经主代理裁决后，方可 --write-baseline --force
重置基线；基线只能前进（条目只增），回退基线=把已点名的实债重新藏回增量面。

命名纪律：本件**不带** test- 前缀——all-gates L2 以 tools/test-*.py glob 自动收编，
新 test- 前缀件会改动 L2 件数钉值（tools/gate-pins.list L2_MIN_ITEMS），污染另一批的
复核读数；本门若需进常驻判定面，由 all-gates 显式 add_item 接线（属主=主代理）。

自足性：只 Python3 标准库；零网络、零 sudo、零宿主改动（临时件只在 tempfile）。
"""
import json
import hashlib
import os
import re
import sys
import tempfile
import shutil
from datetime import datetime

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ESC_PATH = os.path.join(WS, "计划", "研究组", "红队终局轮-20261101", "逃逸问题台账.md")
DEBT_PATH = os.path.join(WS, "计划", "阶段欠账台账.md")
BASELINE_PATH = os.path.join(WS, "30-工件", "账本机制批-20261104", "ledger-growth-baseline.json")

HDR_RE = re.compile(r"^### (RT-E\d+)(?:-[A-Za-z0-9]+)?（")
REPAIR_RE = re.compile(r"- \*\*修复对账\*\*[:：]?(.*?)(?=\n### |\Z)", re.S)
MARKER_RE = re.compile(r"^- \*\*账本迁移对账\*\*[:：]\s*(.+)$", re.M)
BASELINE_KIND = "ledger-growth-baseline"


def parse_escape(path):
    """解析逃逸台账 → [(id, line_no, repair_text)]；重复 id = 解析面断（抛 ValueError）。"""
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
    seen = set()
    out = []
    for e in entries:
        if e["id"] in seen:
            raise ValueError("逃逸台账条目 id 重复：%s（解析面断）" % e["id"])
        seen.add(e["id"])
        txt = "\n".join(e["buf"])
        m = REPAIR_RE.search(txt)
        out.append((e["id"], e["line"], m.group(1).strip() if m else ""))
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


def exemption_marker(rep, rows):
    """豁免标记判定（形态同迁移门）。返回 (豁免?, 说明)。欠账行= 形态要求编号实存。"""
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


def load_baseline(path):
    """读基线 → (ids_set, meta) 或抛 ValueError（缺件/坏 JSON/无 ids 由调用方 rc=2）。"""
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, dict) or raw.get("kind") != BASELINE_KIND:
        raise ValueError("基线 kind 非 %s" % BASELINE_KIND)
    ids = raw.get("ids")
    if not isinstance(ids, list) or not ids:
        raise ValueError("基线 ids 缺失或为空")
    return set(ids), raw


def run_check(esc_path, debt_path, baseline_path, out):
    """主判定。exit 0 绿 / 1 红 / 2 不可证。"""
    for p, name in ((esc_path, "逃逸台账"), (debt_path, "欠账台账"), (baseline_path, "基线清单")):
        if not os.path.isfile(p):
            out.append("FAIL 账本止增门：%s缺件（%s）——不可证不猜绿（rc=2）" % (name, p))
            return 2
    try:
        baseline_ids, bmeta = load_baseline(baseline_path)
    except (ValueError, json.JSONDecodeError, OSError) as e:
        out.append("FAIL 账本止增门：基线清单不可读/不合法（%s：%s）——不可证不猜绿（rc=2）"
                   % (baseline_path, e))
        return 2
    try:
        entries = parse_escape(esc_path)
    except ValueError as e:
        out.append("FAIL 账本止增门：%s（rc=2）" % e)
        return 2
    if not entries:
        out.append("FAIL 账本止增门：逃逸台账零条目可解析——解析面断=不可证（rc=2）")
        return 2
    rows = parse_debt(debt_path)
    cur_ids = {eid for eid, _ln, _rep in entries}
    new_ids = sorted(cur_ids - baseline_ids, key=lambda x: int(re.sub(r"\D", "", x)))
    removed_ids = sorted(baseline_ids - cur_ids, key=lambda x: int(re.sub(r"\D", "", x)))
    out.append("账本止增门：基线 %s（生成 %s，%s 条）；现读逃逸台账 %d 条；新增 %d 条；存量 %d 条不判（迁移门管）；基线内已消失 %d 条（INFO：删条须留痕，不属本门红面）。"
               % (os.path.relpath(baseline_path, WS), bmeta.get("generated_at", "?"),
                  bmeta.get("entry_count", "?"), len(entries), len(new_ids),
                  len(cur_ids & baseline_ids), len(removed_ids)))
    for rid in removed_ids[:10]:
        out.append("INFO 基线内已消失：%s" % rid)
    if not new_ids:
        out.append("结论：绿（基线之后零新增条目）")
        return 0
    reds = []
    for eid, line, rep in new_entries(entries, new_ids):
        cov = covered_by(eid, rows)
        if cov:
            continue
        exp, expmsg = exemption_marker(rep, rows)
        if exp:
            continue
        if not rep:
            reds.append((eid, line, "缺「修复对账」栏——不可判即欠账面未对账；%s" % expmsg))
        else:
            reds.append((eid, line, "新增∧欠账台账零行∧未豁免；%s" % expmsg))
    if reds:
        out.append("FAIL 基线后新增 %d 条中 %d 条未迁欠账台账且未豁免（增生口未封——迁入欠账台账或带「账本迁移对账」豁免/欠账行标记）：" % (len(new_ids), len(reds)))
        for eid, line, msg in reds:
            out.append("  %s  逃逸台账:%d  %s" % (eid, line, msg))
        out.append("结论：红（止增口径：新增实债对 G5/终-② 读数面隐身）")
        return 1
    out.append("结论：绿（新增条目全部在欠账台账有行或带显式豁免标记）")
    return 0


def new_entries(entries, new_ids):
    ids = set(new_ids)
    return [(eid, ln, rep) for eid, ln, rep in entries if eid in ids]


def write_baseline(path, esc_path, force, out):
    """把当刻真台账 id 快照写基线。基线在盘且无 --force → 拒写。"""
    if not os.path.isfile(esc_path):
        out.append("FAIL 逃逸台账缺件（%s）——不写基线（rc=2）" % esc_path)
        return 2
    try:
        entries = parse_escape(esc_path)
    except ValueError as e:
        out.append("FAIL %s——不写基线（rc=2）" % e)
        return 2
    if not entries:
        out.append("FAIL 逃逸台账零条目可解析——不写基线（rc=2）")
        return 2
    if os.path.exists(path) and not force:
        out.append("FAIL 基线已在盘（%s）——重置增量口径须 --force 显式覆盖（维护契约见头部 docstring）" % path)
        return 2
    ids = sorted((eid for eid, _l, _r in entries), key=lambda x: int(re.sub(r"\D", "", x)))
    sha = hashlib.sha256(open(esc_path, "rb").read()).hexdigest()
    doc = {
        "kind": BASELINE_KIND,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "generator": "tools/ledger-growth-gate.py --write-baseline",
        "escape_ledger": os.path.relpath(esc_path, WS),
        "escape_sha256_at_generation": sha,
        "entry_count": len(ids),
        "ids": ids,
        "note": "账本机制批 2026-11-04 止增门基线：快照生成时点全部 RT-E id；此后新增条目"
                "须迁入欠账台账或带「账本迁移对账」豁免/欠账行标记，否则止增门点名红；"
                "基线只能前进（重置须主代理裁决 + --write-baseline --force）。",
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp-%d" % os.getpid()
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, path)
    out.append("账本止增门基线已写：%s（%d 条，生成 %s，台账 sha256=%s…）"
               % (os.path.relpath(path, WS), len(ids), doc["generated_at"], sha[:16]))
    return 0


# ---------------------------------------------------------------- selftest --
def _w(d, name, text):
    p = os.path.join(d, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return p


def _base(ids):
    return {"kind": BASELINE_KIND, "generated_at": "2026-11-04T00:00:00+08:00",
            "entry_count": len(ids), "ids": sorted(ids)}


def run_selftest(out):
    """夹具自测：零网络、零真台账。返回 0/1。"""
    d = tempfile.mkdtemp(prefix="ledger-growth-selftest-%d-" % os.getpid())
    fails = []
    buf = []
    try:
        E = "### RT-E{n}（low）夹具{n}\n- **修复对账**：%s\n"
        def esc(*specs):
            return "".join(E.format(n=n) % t for n, t in specs)
        D = "# 台账\n| 编号 | 欠什么 | 暴露自 | 验收门 | 批次 | 状态 |\n|---|---|---|---|---|---|\n"

        def write_case(name, esc_text, debt_text, ids):
            p = _w(d, name + "-e.md", esc_text)
            dp = _w(d, name + "-d.md", debt_text)
            bp = _w(d, name + "-b.json", json.dumps(_base(ids), ensure_ascii=False))
            return p, dp, bp

        # T1 新增未迁移 → 红（基线只含 RT-E1，台账多出 RT-E2 未修零行）
        p, dp, bp = write_case("t1", esc((1, "   **已修复可见**：全落。"),
                                         (2, "   **未修**：机制腿未见施工。")), D, ["RT-E1"])
        rc = run_check(p, dp, bp, buf)
        if rc != 1 or not any("  RT-E2 " in ln for ln in buf):
            fails.append("T1 新增未迁移应红且点名 RT-E2，得 rc=%d" % rc)

        # T2 新增已迁移 → 绿（欠账行编号前缀）
        buf2 = []
        p, dp, bp = write_case("t2", esc((1, "   **已修复可见**：全落。"),
                                         (2, "   **未修**：残余。")),
                               D + "| RT-E2 | 新增欠账 | 逃逸台账:9 | 门 | 账本机制批 | 未开始 |\n",
                               ["RT-E1"])
        rc = run_check(p, dp, bp, buf2)
        if rc != 0:
            fails.append("T2 新增已迁移应绿 rc=0，得 %d" % rc)

        # T2b 新增行文引用覆盖（描述列含 id）→ 绿
        buf2b = []
        p, dp, bp = write_case("t2b", esc((1, "   **已修复可见**：全落。"),
                                          (2, "   **未修**：残余。")),
                               D + "| RT-E9 | 逃逸台账 RT-E2 残余 | 逃逸台账:9 | 门 | 批 | 未开始 |\n",
                               ["RT-E1"])
        rc = run_check(p, dp, bp, buf2b)
        if rc != 0:
            fails.append("T2b 行文引用覆盖应绿 rc=0，得 %d" % rc)

        # T2c 描述列外（验收门列）顺带提及不算覆盖 → 红
        buf2c = []
        p, dp, bp = write_case("t2c", esc((1, "   **已修复可见**：全落。"),
                                          (2, "   **未修**：残余。")),
                               D + "| RT-E9 | 别的欠账 | 来源 | 顺带提及 RT-E2 | 批 | ✅ |\n",
                               ["RT-E1"])
        rc = run_check(p, dp, bp, buf2c)
        if rc != 1:
            fails.append("T2c 描述列外提及不算覆盖应红 rc=1，得 %d" % rc)

        # T2d 词边界：RT-E116 行文不得覆盖 RT-E1 → 红
        buf2d = []
        p, dp, bp = write_case("t2d", esc((1, "   **未修**：残余。"),
                                          (2, "   **已修复可见**：全落。")),
                               D + "| RT-E9 | 逃逸台账 RT-E116 欠账 | 来源 | 门 | 批 | 未开始 |\n",
                               ["RT-E2"])
        rc = run_check(p, dp, bp, buf2d)
        if rc != 1:
            fails.append("T2d RT-E1 不得被 RT-E116 子串覆盖应红 rc=1，得 %d" % rc)

        # T3 新增带豁免（理由非空）→ 绿
        buf3 = []
        p, dp, bp = write_case("t3", esc((1, "   **已修复可见**：全落。"),
                                         (2, "   **未修**：残余。\n- **账本迁移对账**：豁免=残余已在别册登记（x 台账 y 行）。")),
                               D, ["RT-E1"])
        rc = run_check(p, dp, bp, buf3)
        if rc != 0:
            fails.append("T3 豁免标记应绿 rc=0，得 %d" % rc)

        # T3b 空理由豁免 → 红
        buf3b = []
        p, dp, bp = write_case("t3b", esc((1, "   **已修复可见**：全落。"),
                                          (2, "   **未修**：残余。\n- **账本迁移对账**：豁免=")),
                               D, ["RT-E1"])
        rc = run_check(p, dp, bp, buf3b)
        if rc != 1:
            fails.append("T3b 空理由豁免应红 rc=1，得 %d" % rc)

        # T3c 欠账行= 指向实存 → 绿；指向不存在 → 红
        buf3c = []
        p, dp, bp = write_case("t3c", esc((1, "   **已修复可见**：全落。"),
                                          (2, "   **未修**：残余。\n- **账本迁移对账**：欠账行=DEB-9")),
                               D + "| DEB-9 | 在册欠账 | 来源 | 门 | 批 | 未开始 |\n",
                               ["RT-E1"])
        rc = run_check(p, dp, bp, buf3c)
        if rc != 0:
            fails.append("T3c 欠账行标记指向实存应绿 rc=0，得 %d" % rc)
        buf3d = []
        p, dp, bp = write_case("t3d", esc((1, "   **已修复可见**：全落。"),
                                          (2, "   **未修**：残余。\n- **账本迁移对账**：欠账行=DEB-999")),
                               D + "| DEB-9 | 在册欠账 | 来源 | 门 | 批 | 未开始 |\n",
                               ["RT-E1"])
        rc = run_check(p, dp, bp, buf3d)
        if rc != 1:
            fails.append("T3d 欠账行标记指向不存在应红 rc=1，得 %d" % rc)

        # T4 存量条目不被重复点名（≥2 条存量带残余，红面只含新增 RT-E5）
        buf4 = []
        p, dp, bp = write_case("t4", esc((1, "   **未修**：存量残余甲。"),
                                         (2, "   **未修**：存量残余乙。"),
                                         (3, "   **未修**：存量残余丙。"),
                                         (5, "   **未做**：新增残余。")),
                               D, ["RT-E1", "RT-E2", "RT-E3"])
        rc = run_check(p, dp, bp, buf4)
        reds4 = [ln for ln in buf4 if ln.strip().startswith("RT-E")]
        if rc != 1 or len(reds4) != 1 or not any("RT-E5" in ln for ln in reds4):
            fails.append("T4 应恰红 RT-E5 一条（存量 3 条不点名），得 rc=%d 红=%s" % (rc, reds4))
        if not any("存量 3 条不判" in ln for ln in buf4):
            fails.append("T4 输出应明示存量不判计数")

        # T5 基线缺件 → rc=2
        buf5 = []
        rc = run_check(_w(d, "t5-e.md", esc((1, "   **未修**：x。"))), _w(d, "t5-d.md", D),
                       os.path.join(d, "缺基线.json"), buf5)
        if rc != 2:
            fails.append("T5 基线缺件应 rc=2，得 %d" % rc)

        # T5b 基线坏 JSON → rc=2
        buf5b = []
        rc = run_check(_w(d, "t5b-e.md", esc((1, "   **未修**：x。"))), _w(d, "t5b-d.md", D),
                       _w(d, "t5b-b.json", "{not json"), buf5b)
        if rc != 2:
            fails.append("T5b 基线坏 JSON 应 rc=2，得 %d" % rc)

        # T5c 台账缺件 → rc=2
        buf5c = []
        rc = run_check(os.path.join(d, "缺件.md"), _w(d, "t5c-d.md", D),
                       _w(d, "t5c-b.json", json.dumps(_base(["RT-E1"]))), buf5c)
        if rc != 2:
            fails.append("T5c 台账缺件应 rc=2，得 %d" % rc)

        # T5d 零条目 → rc=2
        buf5d = []
        rc = run_check(_w(d, "t5d-e.md", "# 只有说明，没有条目\n"), _w(d, "t5d-d.md", D),
                       _w(d, "t5d-b.json", json.dumps(_base(["RT-E1"]))), buf5d)
        if rc != 2:
            fails.append("T5d 零条目应 rc=2，得 %d" % rc)

        # T6 缺修复对账栏 → 红（不可静默跳过）
        buf6 = []
        p6 = _w(d, "t6-e.md", "### RT-E7（low）夹具7\n- **发现**：无修复对账栏。\n")
        rc = run_check(p6, _w(d, "t6-d.md", D),
                       _w(d, "t6-b.json", json.dumps(_base(["RT-E1"]))), buf6)
        if rc != 1:
            fails.append("T6 缺修复对账栏应红 rc=1，得 %d" % rc)

        # T7 删条 INFO 回显（基线 3 条、现读 2 条）→ 绿 + INFO 行
        buf7 = []
        p, dp, bp = write_case("t7", esc((1, "   **未修**：还在。"),
                                         (2, "   **未修**：还在。")),
                               D, ["RT-E1", "RT-E2", "RT-E3"])
        rc = run_check(p, dp, bp, buf7)
        if rc != 0 or not any("INFO 基线内已消失：RT-E3" in ln for ln in buf7):
            fails.append("T7 删条应绿且 INFO 回显，得 rc=%d" % rc)

        # T8 零新增 → 绿
        buf8 = []
        p, dp, bp = write_case("t8", esc((1, "   **未修**：x。")), D, ["RT-E1"])
        rc = run_check(p, dp, bp, buf8)
        if rc != 0 or not any("零新增" in ln for ln in buf8):
            fails.append("T8 零新增应绿 rc=0，得 %d" % rc)

        # T9 条目 id 重复 → rc=2（解析面断）
        buf9 = []
        p9 = _w(d, "t9-e.md", esc((1, "   **未修**：x。")) + esc((1, "   **未修**：y。")))
        rc = run_check(p9, _w(d, "t9-d.md", D),
                       _w(d, "t9-b.json", json.dumps(_base([])) if False else json.dumps(_base(["RT-E9"]))), buf9)
        if rc != 2:
            fails.append("T9 条目 id 重复应 rc=2，得 %d" % rc)

        # T10 write_baseline：在盘拒写 / --force 重写
        buf10 = []
        p10e = _w(d, "t10-e.md", esc((1, "   **未修**：x。"), (2, "   **未修**：y。")))
        b10 = os.path.join(d, "t10-b.json")
        rc1 = write_baseline(b10, p10e, False, buf10)
        rc2 = write_baseline(b10, p10e, False, buf10)
        rc3 = write_baseline(b10, p10e, True, buf10)
        got = json.load(open(b10, encoding="utf-8"))
        if rc1 != 0 or rc2 != 2 or rc3 != 0 or got.get("entry_count") != 2:
            fails.append("T10 基线写入（首写/在盘拒写/force 重写）异常：rc=%d/%d/%d count=%s"
                         % (rc1, rc2, rc3, got.get("entry_count")))

        n_cases = 20
        if fails:
            out.append("FAIL selftest %d/%d 过：" % (n_cases - len(fails), n_cases))
            for f in fails:
                out.append("  " + f)
            return 1
        out.append("selftest %d/%d 过（新增未迁移红/编号前缀覆盖绿/行文引用覆盖绿/描述列限定红/"
                   "词边界红/豁免标记绿/空理由红/欠账行实存绿/欠账行不存在红/存量不重复点名≥3 条/"
                   "基线缺件 rc2/基线坏 JSON rc2/台账缺件 rc2/零条目 rc2/缺修复对账栏红/删条 INFO 绿/"
                   "零新增绿/id 重复 rc2/基线写入三态）" % (n_cases, n_cases))
        return 0
    finally:
        shutil.rmtree(d, ignore_errors=True)


def main(argv):
    out = []
    if "--selftest" in argv:
        rc = run_selftest(out)
    elif "--write-baseline" in argv:
        rc = write_baseline(BASELINE_PATH, ESC_PATH, "--force" in argv, out)
    else:
        rc = run_check(ESC_PATH, DEBT_PATH, BASELINE_PATH, out)
    for ln in out:
        print(ln)
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
