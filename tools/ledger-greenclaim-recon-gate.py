#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""台账绿声明对账门（RT-E117 拦截机制①②③；波次B·B2 链 2026-11-05）。

判据源=单一源（本文件自含判据）；绑定/名册登记面=
30-工件/观测面清偿批-20261105/gate-registry.json 的 greenclaim_bindings /
greenclaim_summary_surfaces / greenclaim_known_weak_hits。

机制①【全表同型横扫名单机器化】：横扫名单**由表机器派生**（解析
  计划/系统目标台账.md 全部行，取状态列=✅ 者），不硬编码——改判任一行后，
  其余 ✅ 行自动进入双检（漏一行即红）。
机制②【行态-自注矛盾门】：行态=✅ ∧ 该行**自认未达措辞**出现在验收门/状态列
  ⇒ 红。强标记（确证策略数=0 / 条款3未达 / 未达（…））直接红；弱标记
  （未达/缺口/待补）命中且**未在登记面登记**⇒ 红（存量弱命中已登记，见
  greenclaim_known_weak_hits——只增不减，不得新增豁免吸收真缺口）。
机制③【汇总引用对账门】：判定件/台账/映射件引用「G1-G10 全绿」时，机器逐行
  复算被引 10 行状态列；若实读非全 ✅，引用面必须带勘误/否定标记，否则红
  （汇总面冻结于成文时点而不同步传播＝假绿）。
机制④【验收门第三条字面核对·绑定腿】：登记面声明了机读绑定的行（如 G10 的
  「≥1 确证策略在库可测回撤」），机器复算绑定值，行态须与绑定结论一致⇒
  绑定未达而行态=✅ 即红（这正是 G10 假绿面）。

出口：0=绿；2=红；3=执行错（面缺/不可证，不猜绿）。
自证（--selftest，造夹具自证会咬人）：
  ① 把 G10 行态翻成 ✅（绑定 confirmed=0）⇒ 必红；
  ② 给某个 ✅ 行注入「确证策略数=0」自认未达措辞 ⇒ 必红；
  ③ 删掉汇总引用面的勘误/否定标记 ⇒ 必红；
  ④ 现盘未改动 ⇒ 必绿。
"""
import glob
import json
import os
import re
import sys
import tempfile

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REG_PATH = os.path.join(WS, "30-工件", "观测面清偿批-20261105", "gate-registry.json")
LEDGER_REL = os.path.join("计划", "系统目标台账.md")

STRONG_MARKERS = ("确证策略数=0", "确证策略数 = 0", "确证策略数＝0",
                  "条款3未达", "条款③未达", "未达（", "未达(")
WEAK_MARKERS = ("未达", "缺口", "待补")
NEG_MARKERS = ("勘误", "勘正", "未达", "不得再作引用面", "❌", "六 ✅ 四 ❌")
SUMMARY_PHRASES = ("G1-G10 全绿", "G1-G10全绿", "G1–G10 全绿", "G1-G10 全 ✅",
                   "G1-G10+ G-SIL 全绿", "G1-G10 + G-SIL 全绿")
ROW_ID = re.compile(r"^(G\d+|G-SIL)$")


def err(msg):
    sys.stderr.write("[ledger-greenclaim-recon-gate] %s\n" % msg)


def parse_rows(path):
    """解析台账表行 ⇒ [{id, goal, accept, status, batch, line}]。

    G7 行状态列内含字面 '|'（'24|17=70.8%…'）——直接按 | 切列会把状态列劈成两半，
    故状态列 = cells[3:-1] 重新拼接，末格为批次列。
    """
    rows = []
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().split("\n")
    except OSError as exc:
        return None, "台账不可读：%s（%s）" % (path, exc)
    for i, line in enumerate(lines, 1):
        s = line.strip()
        if not s.startswith("|"):
            continue
        if s.startswith("|---") or set(s) <= set("|-: "):
            continue
        body = s[1:] if s.endswith("|") else s
        cells = [c.strip() for c in body.split("|")]
        if not cells or not ROW_ID.match(cells[0]):
            continue
        if len(cells) < 4:
            continue
        status = "|".join(cells[3:-1]) if len(cells) > 4 else cells[3]
        rows.append({"id": cells[0], "goal": cells[1], "accept": cells[2],
                     "status": status, "batch": cells[-1] if len(cells) > 4 else "",
                     "line": i})
    return rows, None


def is_green(status):
    return status.lstrip().startswith("✅")


def confirmed_strategy_count(pattern):
    """复算「确证策略数」：扫 strategies/*.yaml 里 status: confirmed 的件数。"""
    files = sorted(glob.glob(pattern))
    if not files:
        return None, 0
    hit = 0
    for p in files:
        try:
            with open(p, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        if re.search(r"^\s*status:\s*['\"]?confirmed['\"]?\s*$", text, re.M):
            hit += 1
    return hit, len(files)


def check(ledger_path, surfaces, reg):
    """主判定：返回 (reds, notes)。"""
    reds, notes = [], []
    rows, e = parse_rows(ledger_path)
    if rows is None:
        return None, [e]
    by_id = {r["id"]: r for r in rows}
    g_rows = [r for r in rows if re.match(r"^G\d+$", r["id"])]

    # ---- 机制①：横扫名单机器化（名单由表派生，不硬编码）
    green_roster = [r["id"] for r in rows if is_green(r["status"])]
    notes.append("机制① 全表同型横扫名单（机器派生，%d 行中 ✅ %d 行）：%s"
                 % (len(rows), len(green_roster), "、".join(green_roster) or "无"))

    # ---- 机制②：行态-自注矛盾门
    known = reg.get("greenclaim_known_weak_hits") or {}
    for r in rows:
        if not is_green(r["status"]):
            continue
        claim = "%s %s" % (r["accept"], r["status"])
        strong = [m for m in STRONG_MARKERS if m in claim]
        if strong:
            reds.append("%s:%d 行态=✅ 而自认未达（强标记 %s）⇒ 假绿面（RT-E117 机制②）"
                        % (os.path.basename(ledger_path), r["line"], "/".join(strong)))
            continue
        weak = [m for m in WEAK_MARKERS if m in claim]
        if weak:
            key = "%s:%d" % (r["id"], r["line"])
            if key in known:
                notes.append("机制② %s 弱标记 %s ⇒ 存量已登记（不判红）"
                             % (key, "/".join(weak)))
            else:
                reds.append("%s:%d 行态=✅ 而行内含自认未达措辞 %s ⇒ 假绿面"
                            "（RT-E117 机制②，未在登记面登记）"
                            % (os.path.basename(ledger_path), r["line"],
                               "/".join(weak)))

    # ---- 机制③：汇总引用对账门
    referenced = ["G%d" % i for i in range(1, 11)]
    all_green = all(is_green(by_id[i]["status"]) for i in referenced if i in by_id)
    for rel in surfaces:
        p = rel if os.path.isabs(rel) else os.path.join(WS, rel)
        if not os.path.exists(p):
            reds.append("汇总引用面缺失：%s（面缺，不可证不猜绿）" % rel)
            continue
        try:
            with open(p, encoding="utf-8") as fh:
                lines = fh.read().split("\n")
        except OSError as exc:
            reds.append("汇总引用面不可读：%s（%s）" % (rel, exc))
            continue
        for i, line in enumerate(lines, 1):
            if not any(ph in line for ph in SUMMARY_PHRASES):
                continue
            if all_green:
                notes.append("机制③ %s:%d 汇总引用成立（被引 10 行实读全 ✅）"
                             % (os.path.basename(p), i))
                continue
            window = "\n".join(lines[max(0, i - 3):i + 2])
            if any(m in window for m in NEG_MARKERS):
                notes.append("机制③ %s:%d 汇总引用面带勘误/否定标记 ⇒ 非假绿"
                             % (os.path.basename(p), i))
            else:
                reds.append("%s:%d 引用「G1-G10 全绿」而被引行实读非全 ✅（现读 "
                            "%s）且引用面无勘误/否定标记 ⇒ 汇总面假绿（RT-E117 机制③）"
                            % (os.path.basename(p), i,
                               "/".join("%s=%s" % (k, "✅" if is_green(by_id[k]["status"])
                                                  else "❌")
                                        for k in referenced if k in by_id)))

    # ---- 机制④：验收门第三条字面核对·绑定腿
    for rid, b in (reg.get("greenclaim_bindings") or {}).items():
        row = by_id.get(rid)
        if row is None:
            reds.append("绑定腿：台账无 %s 行（面缺，不可证不猜绿）" % rid)
            continue
        kind = b.get("kind")
        if kind != "confirmed_strategy_count":
            notes.append("绑定腿 %s：未知绑定类型 %s ⇒ 登记不判（登记缺口）" % (rid, kind))
            continue
        cnt, total = confirmed_strategy_count(b.get("strategies_glob") or "")
        if cnt is None:
            reds.append("绑定腿 %s：策略库面不可读（%s）⇒ 不可证不猜绿"
                        % (rid, b.get("strategies_glob")))
            continue
        need = int(b.get("min", 1))
        ok = cnt >= need
        green = is_green(row["status"])
        notes.append("绑定腿 %s：确证策略数=%d（扫描 %d 件，条款③要求 ≥%d）"
                     % (rid, cnt, total, need))
        if ok and not green:
            reds.append("%s:%d %s 绑定已达标（确证策略数=%d）但行态=❌ ⇒ 台账滞后"
                        "（RT-E117 机制④·台账面失真）"
                        % (os.path.basename(ledger_path), row["line"], rid, cnt))
        elif (not ok) and green:
            reds.append("%s:%d %s 行态=✅ 但验收门第三条「%s」未达（确证策略数=%d < %d）"
                        "⇒ 假绿面（RT-E117 机制④·G10 假绿复发）"
                        % (os.path.basename(ledger_path), row["line"], rid,
                           b.get("clause3", ""), cnt, need))
    return reds, notes


def load_registry(path=REG_PATH):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        err("登记面不可读：%s（%s）" % (path, exc))
        return None


def selftest(reg):
    fails = []
    tmp = tempfile.mkdtemp(prefix="greenclaim-fixture-")
    ledger = os.path.join(WS, LEDGER_REL)
    surfaces = reg.get("greenclaim_summary_surfaces") or []
    with open(ledger, encoding="utf-8") as fh:
        ledger_text = fh.read()

    # ① G10 行态翻成 ✅ ⇒ 必红（绑定腿）
    p1 = os.path.join(tmp, "ledger_g10_green.md")
    out = []
    for line in ledger_text.split("\n"):
        if line.strip().startswith("| G10 |"):
            cells = line.strip().split("|")
            cells[4] = " ✅ 2026-11-05（夹具伪造：G10 回翻 ✅） "
            line = "|".join(cells)
        out.append(line)
    with open(p1, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out))
    reds, _ = check(p1, surfaces, reg)
    if not any("G10 假绿复发" in r for r in (reds or [])):
        fails.append("夹具① G10 翻 ✅ 应红未红：%s" % (reds or [])[:2])
    else:
        print("  夹具① G10 行态翻 ✅ ⇒ 红（%s）"
              % [r for r in reds if "G10 假绿复发" in r][0][:100])

    # ② 给某个 ✅ 行注入「确证策略数=0」⇒ 必红（机制②强标记）
    p2 = os.path.join(tmp, "ledger_selfclaim.md")
    out = []
    for line in ledger_text.split("\n"):
        if line.strip().startswith("| G4 |"):
            cells = line.strip().split("|")
            cells[3] = cells[3] + "（确证策略数=0）"
            line = "|".join(cells)
        out.append(line)
    with open(p2, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out))
    reds2, _ = check(p2, surfaces, reg)
    if not any("强标记" in r for r in (reds2 or [])):
        fails.append("夹具② 行内注入确证策略数=0 应红未红：%s" % (reds2 or [])[:2])
    else:
        print("  夹具② ✅ 行注入「确证策略数=0」⇒ 红（%s）"
              % [r for r in reds2 if "强标记" in r][0][:100])

    # ③ 汇总引用面去掉勘误标记 ⇒ 必红（机制③）
    p3 = os.path.join(tmp, "surface_nomarker.md")
    with open(p3, "w", encoding="utf-8") as fh:
        fh.write("阶段三开发本体：完成（G1-G10 全绿）。\n")
    reds3, _ = check(ledger, [p3], reg)
    if not any("汇总面假绿" in r for r in (reds3 or [])):
        fails.append("夹具③ 无标记汇总引用面应红未红：%s" % (reds3 or [])[:2])
    else:
        print("  夹具③ 汇总引用面无勘误标记 ⇒ 红（%s）"
              % [r for r in reds3 if "汇总面假绿" in r][0][:100])

    # ④ 现盘未改动 ⇒ 必绿
    reds4, notes4 = check(ledger, surfaces, reg)
    if reds4:
        fails.append("夹具④ 现盘应绿却红：%s" % reds4[:3])
    else:
        print("  夹具④ 现盘未改动 ⇒ 绿（%s）" % (notes4[0] if notes4 else ""))
    return fails


def main(argv):
    reg = load_registry()
    if reg is None:
        return 3
    ledger = os.path.join(WS, LEDGER_REL)
    surfaces = reg.get("greenclaim_summary_surfaces") or []
    if "--ledger" in argv:
        ledger = argv[argv.index("--ledger") + 1]
    if "--surfaces" in argv:
        surfaces = argv[argv.index("--surfaces") + 1].split(",")
    if "--selftest" in argv:
        fails = selftest(reg)
        for f in fails:
            err("自证失败：%s" % f)
        print("自证：%s" % ("全过" if not fails else "有 %d 项失败" % len(fails)))
        return 0 if not fails else 2
    reds, notes = check(ledger, surfaces, reg)
    if reds is None:
        for n in notes:
            err(n)
        return 3
    for n in notes:
        print("[注] %s" % n)
    if reds:
        for r in reds:
            print("[红] %s" % r)
        print("结论：红（台账绿声明对账门，RT-E117）")
        return 2
    print("结论：绿（台账绿声明对账门，RT-E117）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
