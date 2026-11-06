#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""anchor-uncheck-zero-gate.py — E92「未核=0」门（处置正本口径）

背景（逃逸台账 RT-E92 拦截机制②：「未核=0」门：未核锚计数>0 即 FAIL——
未核不是通过，是未检查）
--------------------------------------------------------------------------
方法论文档《持续改进方法论》的锚点面由 `anchor-check.py` 机检。该机检把「零内容
核验」的锚（行在、非空，但 doc 侧无逐字声称/散文令牌/符号令牌可命中目标行）记为
`未核(无声称)` / `未核(散文元语言)` 并**按存在性计入 PASS** ⇒ 断链可长期存活
（RT-E92 逃逸本体：M-2 锚指向非空但内容错的行，机检仍全绿放行）。

本门做什么（只读，不改任何判据件、不改 anchor-check.py、不改 criteria.yaml）：
  leg-1 判据源在位：anchor-check.py + 处置正本 e92-disposition.json 在位且可解析
        （缺件/坏 JSON ⇒ rc=2 不可证，不猜绿）。
  leg-2 机检面：亲跑 `anchor-check.py --sample 0`（**全量口径**，门内禁抽样），
        要求 rc=0 且末行 ALL_ANCHORS_OK；任一 FAIL ⇒ 红。
  leg-3 未核面：解析机检输出的未核两类计数与**逐条未核锚坐标**。
  leg-4 处置正本对账：每条未核锚必须在处置正本 e92-disposition.json 在册，且
        · kind 合法 ∈ {backfilled, exempt, upgraded_red}；
        · evidence 非空（逐字证据）；
        · by/ts 在册；
        · kind=backfilled ⇒ 该锚**必须已不在未核集**（回填未生效 ⇒ 红，防「登记即绿」）；
        · kind=exempt ⇒ 带 expiry 且未过期（过期豁免 ⇒ 红）；
        · kind=upgraded_red ⇒ 须在台账真红清单在册（按 red_registration 指到的
          登记面逐字点名该锚坐标；未登记 ⇒ 红）。
  leg-5 净未处置未核数 = 0：未核锚减去「有效豁免 + 已登记真红」后的余额 > 0 ⇒ 红。

红条件（任一成立即红，rc=1）：
  ① anchor-check 全量跑 rc≠0 或 verdict≠ALL_ANCHORS_OK；
  ② 处置正本缺锚（未核锚不在册）/ 过期豁免 / 证据空 / kind 非法 / 必填字段缺；
  ③ 回填未生效（在册 kind=backfilled 但该锚仍在未核集内）；
  ④ 真红未登记台账（kind=upgraded_red 但登记面未逐字点名该锚坐标）；
  ⑤ 净未处置未核数 > 0。

口径说明（与外派任务书「未核计数>0」的措辞对齐）：本门同时打印**未核毛计数**
（机检原样计数）与**净未处置未核数**（毛计数中未被有效豁免/已登记真红覆盖的部分）。
门红判据取后者——豁免与已登记真红是**在册且可见**的缺口（逃逸台账 RT-E92 的
「登记腿」口径：未登记的缺口即红，已登记的缺口可见且被点名），若把毛计数直接
当门红判据，则任何一条合法豁免都会让门恒红，登记面形同虚设。
本门与同批既有门 `tools/e92-unverified-zero-gate.py`（白名单口径）**共存**：
前者按豁免白名单三重钉（文件+mtime+行内容指纹）判未核锚在册性，本门按
**处置正本**（逐条 kind + 证据 + expiry + 真红登记）判未核锚已处置性。

退出码：0=绿 / 1=红 / 2=不可证（缺件或环境错误）。
用法：python3 -I tools/anchor-uncheck-zero-gate.py [--selftest] [--registry PATH]
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

WS = Path(__file__).resolve().parents[1]
P_ANCHOR_REL = "计划/研究组/方法论批-20261031/anchor-check.py"
P_DISP_REL = "30-工件/门红面批-20261105/e92-disposition.json"
TIMEOUT_S = 600

RE_SUMMARY = re.compile(r"未核\(无声称\)=(\d+)\s+未核\(散文元语言\)=(\d+)")
RE_ROW = re.compile(r"^\[(?:OK|FAIL)\s*\]\s+(?P<path>[^ \t|]+?):(?P<line>\d+)\s+\|")
TAG_SILENT = "未核(无声称)"
TAG_META = "未核(散文元语言)"
KINDS = ("backfilled", "exempt", "upgraded_red")


class GateError(Exception):
    """不可证（缺件/坏件/环境错）——不猜绿。"""


def parse_anchor_output(out):
    """解析 anchor-check 全量输出 → (未核锚坐标表, 毛计数, 机检 rc, verdict)。"""
    rows = []
    for line in (out or "").splitlines():
        m = RE_ROW.match(line)
        if not m:
            continue
        key = "%s:%s" % (m.group("path"), m.group("line"))
        tag = ""
        if "◈" in line:
            tag = line.split("◈")[-1].strip()
        rows.append((key, line.startswith("[OK"), tag))
    unv = [(k, tag) for k, ok, tag in rows if ok and (TAG_SILENT in tag or TAG_META in tag)]
    fails = [k for k, ok, tag in rows if not ok]
    mv = RE_SUMMARY.search(out or "")
    gross = (int(mv.group(1)) + int(mv.group(2))) if mv else None
    verdict = ""
    for line in (out or "").strip().splitlines():
        if line.strip():
            verdict = line.strip()
    return unv, gross, fails, verdict


def run_anchor_check(anchor_check):
    try:
        pr = subprocess.run([sys.executable, "-I", str(anchor_check), "--sample", "0"],
                            capture_output=True, text=True, timeout=TIMEOUT_S, cwd=str(WS))
    except Exception as e:                                    # noqa: BLE001
        raise GateError("anchor-check 执行错：%s" % e)
    return pr.stdout or "", pr.returncode


def load_disposition(path):
    if not path.is_file():
        raise GateError("处置正本缺件：%s" % path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:                                    # noqa: BLE001
        raise GateError("处置正本坏 JSON：%s" % e)
    if not isinstance(data, dict):
        raise GateError("处置正本结构非法：顶层须为对象")
    entries = data.get("entries")
    if not isinstance(entries, list) or not entries:
        raise GateError("处置正本结构非法：entries 须为非空数组")
    for i, e in enumerate(entries):
        if not isinstance(e, dict):
            raise GateError("处置正本条目 #%d 不是对象" % i)
        for k in ("anchor", "file", "line", "kind", "evidence", "by", "ts"):
            if k not in e or not str(e.get(k)).strip():
                raise GateError("处置正本条目 #%d 缺字段 %s" % (i, k))
        if e.get("kind") not in KINDS:
            raise GateError("处置正本条目 #%d kind 非法：%r" % (i, e.get("kind")))
        if not isinstance(e.get("line"), int) or e["line"] < 1:
            raise GateError("处置正本条目 #%d line 非法：%r" % (i, e.get("line")))
    return data


def red_registry_lookup(ws, entry):
    """kind=upgraded_red：核台账真红登记面是否逐字点名该锚坐标。
    返回 (ok, msg)。"""
    ref = (entry.get("red_registration") or "").strip()
    if not ref:
        return False, "真红条目缺 red_registration 字段（未指向台账登记面）"
    m = re.match(r"^(?P<file>.+?):(?P<line>\d+)$", ref)
    if not m:
        return False, "red_registration 格式非法（应为 文件:行）：%r" % ref
    p = ws / m.group("file")
    if not p.is_file():
        return False, "red_registration 登记面不在位：%s" % m.group("file")
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    ln = int(m.group("line"))
    if not (0 < ln <= len(lines)):
        return False, "red_registration 行号越界：%s（文件共 %d 行）" % (ref, len(lines))
    text = lines[ln - 1]
    needle = entry["anchor"]
    rid = str(entry.get("red_id") or "").strip()
    if rid:
        needle = rid
    if needle not in text:
        return False, "台账真红登记面 %s 未逐字点名该锚登记名 %s" % (ref, needle)
    return True, text.strip()[:160]


def check(ws, unv, gross, anchor_rc, verdict, disp, today):
    """核心判定（纯函数，便于 --selftest 构造夹具）。返回 (ok, reds, notes)。"""
    reds, notes = [], []
    if anchor_rc != 0:
        reds.append("机检面：anchor-check 全量跑 rc=%d（要求 0）" % anchor_rc)
    if verdict != "ALL_ANCHORS_OK":
        reds.append("机检面：anchor-check 末行 verdict=%r（要求 ALL_ANCHORS_OK）" % verdict)
    if gross is None:
        reds.append("机检面：输出无「未核(无声称)/未核(散文元语言)」计数行 ⇒ 口径漂移不可判")
    by_anchor = {}
    for e in disp.get("entries", []):
        by_anchor.setdefault(e["anchor"], []).append(e)
    covered = 0
    for key, tag in unv:
        ents = by_anchor.get(key)
        if not ents:
            reds.append("处置正本缺锚：未核锚 %s（%s）不在 %s 在册 ⇒ 新增未处置未核锚"
                        % (key, tag, disp.get("_path", "e92-disposition.json")))
            continue
        e = ents[0]
        kind = e.get("kind")
        if not str(e.get("evidence", "")).strip():
            reds.append("处置正本证据空：未核锚 %s 的登记条目证据为空" % key)
            continue
        if kind == "backfilled":
            reds.append("回填未生效：%s 在册 kind=backfilled，但该锚仍出现在未核集（%s）"
                        % (key, tag))
            continue
        if kind == "exempt":
            exp = str(e.get("expiry") or "").strip()
            if not exp:
                reds.append("豁免缺 expiry：未核锚 %s 的豁免条目未带 expiry" % key)
                continue
            try:
                exp_d = datetime.strptime(exp, "%Y-%m-%d")
            except ValueError:
                reds.append("豁免 expiry 格式非法：%s（%r，应为 YYYY-MM-DD）" % (key, exp))
                continue
            if exp_d < today:
                reds.append("豁免已过期：未核锚 %s 的豁免 expiry=%s < 当日 %s"
                            % (key, exp, today.strftime("%Y-%m-%d")))
                continue
            covered += 1
            notes.append("豁免在册（expiry=%s）：%s" % (exp, key))
            continue
        if kind == "upgraded_red":
            ok, msg = red_registry_lookup(ws, e)
            if not ok:
                reds.append("真红未登记台账：%s —— %s" % (key, msg))
                continue
            covered += 1
            notes.append("真红已登记台账：%s ⇒ %s" % (key, msg))
            continue
        reds.append("kind 非法：未核锚 %s 的 kind=%r" % (key, kind))
    net = len(unv) - covered
    if net > 0:
        reds.append("净未处置未核数=%d（未核毛计数=%s）> 0 ⇒ 未核锚未全部在处置正本在册"
                    % (net, gross))
    return (not reds), reds, notes


def selftest(out):
    """判别力自测（负控）：构造夹具 ⇒ 必须报红；正控：全部在册 ⇒ 必须绿。"""
    ws = WS
    today = datetime(2026, 11, 5)
    import tempfile
    tf = tempfile.NamedTemporaryFile("w", suffix=".red-ledger", delete=False, encoding="utf-8")
    tf.write("SELFTEST-RED-ID 真红登记行（夹具）：锚 c.py:3\n")
    tf.close()
    disp = {"_path": "e92-disposition.json", "entries": [
        {"anchor": "a.py:1", "file": "a.py", "line": 1, "kind": "exempt",
         "evidence": "逐字证据", "by": "t", "ts": "2026-11-05T00:00:00+0800",
         "expiry": "2026-12-05"},
        {"anchor": "b.py:2", "file": "b.py", "line": 2, "kind": "backfilled",
         "evidence": "逐字证据", "by": "t", "ts": "2026-11-05T00:00:00+0800"},
        {"anchor": "c.py:3", "file": "c.py", "line": 3, "kind": "upgraded_red",
         "evidence": "逐字证据", "by": "t", "ts": "2026-11-05T00:00:00+0800",
         "red_id": "SELFTEST-RED-ID",
         "red_registration": "%s:1" % tf.name},
    ]}
    cases = []
    # 正控：未核集内两条均已合规登记（豁免 + 真红）⇒ 绿
    ok, reds, notes = check(ws, [("a.py:1", TAG_SILENT), ("c.py:3", TAG_META)],
                             2, 0, "ALL_ANCHORS_OK", disp, today)
    cases.append(("正控：豁免+真红在册⇒绿", ok, reds))
    # 负控①：未核锚不在处置正本 ⇒ 红
    ok, reds, notes = check(ws, [("z.py:9", TAG_SILENT)], 1, 0, "ALL_ANCHORS_OK", disp, today)
    cases.append(("负控①：未核锚缺登记⇒红", (not ok) and any("缺锚" in r for r in reds), reds))
    # 负控②：证据空 ⇒ 红
    d2 = json.loads(json.dumps(disp))
    d2["entries"][0]["evidence"] = "   "
    ok, reds, notes = check(ws, [("a.py:1", TAG_SILENT)], 1, 0, "ALL_ANCHORS_OK", d2, today)
    cases.append(("负控②：证据空⇒红", (not ok) and any("证据空" in r for r in reds), reds))
    # 负控③：豁免过期 ⇒ 红
    d3 = json.loads(json.dumps(disp))
    d3["entries"][0]["expiry"] = "2026-10-01"
    ok, reds, notes = check(ws, [("a.py:1", TAG_SILENT)], 1, 0, "ALL_ANCHORS_OK", d3, today)
    cases.append(("负控③：豁免过期⇒红", (not ok) and any("过期" in r for r in reds), reds))
    # 负控④：回填未生效（backfilled 仍在未核集）⇒ 红
    ok, reds, notes = check(ws, [("b.py:2", TAG_SILENT)], 1, 0, "ALL_ANCHORS_OK", disp, today)
    cases.append(("负控④：回填未生效⇒红", (not ok) and any("回填未生效" in r for r in reds), reds))
    # 负控⑤：真红未登记台账（red_registration 指向不存在的行内容）⇒ 红
    d5 = json.loads(json.dumps(disp))
    d5["entries"][2]["red_registration"] = "%s:99999" % tf.name
    ok, reds, notes = check(ws, [("c.py:3", TAG_META)], 1, 0, "ALL_ANCHORS_OK", d5, today)
    cases.append(("负控⑤：真红未登记台账⇒红", (not ok) and any("真红未登记" in r for r in reds), reds))
    # 负控⑥：机检面红（rc≠0）⇒ 红
    ok, reds, notes = check(ws, [], 0, 1, "SOME_ANCHORS_FAILED", disp, today)
    cases.append(("负控⑥：机检面红⇒红", (not ok) and any("机检面" in r for r in reds), reds))
    # 负控⑦：解析面——假未核输出能被判出
    fake = ("== 锚点机检：文档 X\n"
            "[OK  ] 计划/研究组/方法论批-20261031/anchor-check.py:1 | x  ◈未核(无声称)\n"
            "   内容核验口径：锚定行逐字=0 梯度命中=0 标注值=0 活写内容在=0 散文=0 "
            "未核(无声称)=1 未核(散文元语言)=0\n"
            "ALL_ANCHORS_OK\n")
    unv, gross, fails, verdict = parse_anchor_output(fake)
    cases.append(("负控⑦：解析面认得出假未核锚", (len(unv) == 1 and gross == 1
                                                 and unv[0][0].endswith("anchor-check.py:1")), unv))
    try:
        os.unlink(tf.name)
    except OSError:
        pass
    allok = True
    for name, good, detail in cases:
        mark = "PASS" if good else "FAIL"
        if not good:
            allok = False
        print("   [%s] %s%s" % (mark, name, "" if good else "  ⇒ %s" % (detail,)))
    print("SELFTEST_%s" % ("OK" if allok else "FAILED"))
    return 0 if allok else 1


def main():
    ap = argparse.ArgumentParser(description="E92「未核=0」门（处置正本口径）")
    ap.add_argument("--registry", default=P_DISP_REL)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        print("== anchor-uncheck-zero-gate --selftest（判别力自测）")
        return selftest(None)
    anchor_check = WS / P_ANCHOR_REL
    disp_path = WS / args.registry
    if not anchor_check.is_file():
        print("[FATAL] 判据源不在位：%s" % anchor_check)
        return 2
    try:
        disp = load_disposition(disp_path)
    except GateError as e:
        print("[FATAL] %s" % e)
        return 2
    disp["_path"] = args.registry
    try:
        out, rc = run_anchor_check(anchor_check)
    except GateError as e:
        print("[FATAL] %s" % e)
        return 2
    unv, gross, fails, verdict = parse_anchor_output(out)
    today = datetime.now()
    ok, reds, notes = check(WS, unv, gross, rc, verdict, disp, today)
    print("== E92「未核=0」门（处置正本口径）")
    print("   判据源：%s" % P_ANCHOR_REL)
    print("   处置正本：%s（entries=%d）" % (args.registry, len(disp.get("entries", []))))
    print("   机检：rc=%d verdict=%s 未核毛计数=%s（未核锚 %d 条）"
          % (rc, verdict, gross, len(unv)))
    if unv:
        for k, tag in unv:
            print("     · 未核锚 %s（%s）" % (k, tag))
    for n in notes:
        print("   [在册] %s" % n)
    if reds:
        print("[红] %d 项：" % len(reds))
        for r in reds:
            print("   · %s" % r)
        print("ANCHOR_UNCHECK_ZERO_RED")
        return 1
    print("[绿] 未核锚 %d 条全部在处置正本在册（豁免/真红口径），净未处置未核数=0；机检全绿" % len(unv))
    print("ANCHOR_UNCHECK_ZERO_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
