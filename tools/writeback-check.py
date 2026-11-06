#!/usr/bin/env python3
"""writeback-check.py — 裁决回写核对门（红队 PP3，2026-10-29 义务收口批）

PP3 教训（计划/研究组/红队复盘-逃逸分析与防再发-20261027.md §PP3）：裁决只落在裁决书里、
"✅" 无新鲜度校验——正本与执行记录相反仍可并存。本门把回写变成机对账：

  扫描 计划/补丁台账-第三阶段.md 与 计划/变更日志.md 的**全部裁决行**（任一单元格
  恰为「裁决」）：带「回写清单」标记的，按行内登记的 (正本文件, 锚) 逐项核对正本**已改**；
  裁决而未登记回写清单的=红（无登记=无核对对象不得放行；RT-PP3 修订，此前只扫标记行、
  全未登记时 exit 0 绿——门对其声称的目的结构上失明）：
    ① 文件存在（workspace 相对路径；缺失=红）
    ② 锚文本在文件中逐字存在（缺失=红：回写没落地）
    ③ 文件 mtime ≥ 裁决日（早于裁决=不可能已回写；红）
    ④ 行内登记 @sha256:<hex> 时逐字节比对（漂移=红；适用于冻结件，
       在役正本只登记锚+mtime，避免每次正常改动误红）
  未回写=红；裁决行未登记=红。全绿 exit 0；解析错误 exit 2。

行内标记语法（markdown 表格行任意单元格）：
  回写清单: `[裁决日=YYYY-MM-DD;] <路径>#<锚>[; <路径>#<锚>[@sha256:<hex>]]…`
  · 规格段建议用反引号包裹（行文尾注 prose 不会被误当登记项；无反引号时取冒号后全段）
  · 路径相对 workspace 根；锚为文件中逐字存在的连续子串（不得含 ;/；/#）
  · 裁决日缺省取行内首个 YYYY-MM-DD（变更日志首列即日期）；再缺省=该行红（登记不全）
  · 一行可登记多个正本（多面回写逐面核对）

与 PP3 升级修订的关系：回写清单从裁决行机读（非 ADR frontmatter——本批不改全库
文书模板，只在两条台账内以标记登记，样例见 计划/变更日志.md RT-PP3 补登记三条）；
"✅/待裁决"状态句的 claim-id/哈希新鲜度由 doc-claims 机制另行收口，本门只管回写落地。

用法：
  tools/writeback-check.py                 # 实扫两条台账（exit 0=全绿 1=有红 2=解析错）
  tools/writeback-check.py --ledgers 计划/变更日志.md   # 指定台账（可多次）
  tools/writeback-check.py --json
  tools/writeback-check.py --selftest      # 夹具自证（$HOME 临时件，不碰真台账）
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import sys

WS = os.path.expanduser("~/workspace/agent黑灯工厂")
DEFAULT_LEDGERS = ["计划/补丁台账-第三阶段.md", "计划/变更日志.md"]
MARKER = "回写清单"
FULL_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def _row_date(cells, spec):
    """裁决日：spec 内 裁决日= 优先，否则行内首个 YYYY-MM-DD；再缺省 None。"""
    m = re.search(r"裁决日=(\d{4}-\d{2}-\d{2})", spec)
    if m:
        return m.group(1)
    for c in cells:
        m = FULL_DATE_RE.search(c)
        if m:
            return m.group(0)
    return None


def _is_verdict_row(cells):
    """裁决型行判定：任一单元格恰为「裁决」（变更日志类型列；对单元格漂移鲁棒）。
    表头「类型（计划/状态/裁决/分工）」与分隔行不恰等，天然排除。"""
    return any(c == "裁决" for c in cells)


def _parse_entries(spec):
    """'路径#锚[@sha256:hex]; …' → [(path, anchor, sha_or_None)]；畸形项抛 ValueError。
    分隔符同时认 ASCII ';' 与全角 '；'（中文台账行文习惯）。"""
    out = []
    for part in re.split(r"[;；]", spec):
        part = part.strip()
        if not part or part.startswith("裁决日="):
            continue
        if "#" not in part:
            raise ValueError(f"登记项缺 '#'（路径#锚）: {part!r}")
        path, rest = part.split("#", 1)
        path, rest = path.strip(), rest.strip()
        sha = None
        if "@sha256:" in rest:
            rest, sha = rest.split("@sha256:", 1)
            rest, sha = rest.strip(), sha.strip().lower()
            if not re.fullmatch(r"[0-9a-f]{64}", sha):
                raise ValueError(f"sha256 形态不对: {sha[:20]}…")
        if not path or not rest:
            raise ValueError(f"登记项空路径或空锚: {part!r}")
        if ";" in rest or "；" in rest or "#" in rest:
            raise ValueError(f"锚不得含 ';'/'；' 或 '#': {rest!r}")
        out.append((path, rest, sha))
    if not out:
        raise ValueError("回写清单无有效登记项")
    return out


def _check_entry(path, anchor, sha, verdict_day):
    """核对单个 (文件, 锚)：存在/锚在/mtime≥裁决日/sha 比对。返回 (ok, reasons[])。"""
    reasons = []
    fp = os.path.join(WS, path)
    if not os.path.isfile(fp):
        return False, [f"正本缺失: {path}"]
    try:
        with open(fp, encoding="utf-8") as f:
            text = f.read()
    except Exception as e:  # noqa: BLE001
        return False, [f"正本不可读: {path}: {e}"]
    if anchor not in text:
        reasons.append(f"锚未命中（回写未落地）: {path}#{anchor[:40]}")
    if verdict_day:
        vd = datetime.date.fromisoformat(verdict_day)
        mt = datetime.date.fromtimestamp(os.path.getmtime(fp))
        if mt < vd:
            reasons.append(f"正本 mtime {mt} 早于裁决日 {vd}（不可能已回写）")
    if sha:
        digest = hashlib.sha256(open(fp, "rb").read()).hexdigest()
        if digest != sha:
            reasons.append(f"sha256 漂移: {path}（登记 {sha[:12]}… 实际 {digest[:12]}…）")
    return (not reasons), reasons


def scan_ledgers(ledgers):
    """扫台账 → 每裁决行一条记录（带标记=核对登记项；未登记裁决行=红）。
    红=未登记、登记不全或该行任一登记项未过。"""
    rows = []
    for rel in ledgers:
        fp = os.path.join(WS, rel)
        if not os.path.isfile(fp):
            rows.append({"ledger": rel, "row": "-", "status": "red",
                         "detail": [f"台账不在位: {rel}"], "entries": []})
            continue
        with open(fp, encoding="utf-8") as f:
            for ln, line in enumerate(f, 1):
                if not line.lstrip().startswith("|"):
                    continue
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                if MARKER not in line:
                    # 裁决行未登记「回写清单」=红（无登记=无核对对象不得放行；
                    # 非裁决的无标记行仍忽略）
                    if _is_verdict_row(cells):
                        rows.append({"ledger": rel,
                                     "row": cells[0] if cells and cells[0] else f"{rel}:{ln}",
                                     "line": ln, "status": "red", "registered": False,
                                     "verdict_day": _row_date(cells, ""), "entries": [],
                                     "detail": ["裁决行未登记「回写清单」——无核对对象=红（须补登记或裁决明示豁免）"]})
                    continue
                row_id = cells[0] if cells and cells[0] else f"{rel}:{ln}"
                spec_cell = next((c for c in cells if MARKER in c), "")
                spec = spec_cell.split(MARKER, 1)[1].lstrip(":：").strip()
                # 规格段优先取反引号包裹内容（行文可带尾注 prose 不被误当登记项）
                mq = re.search(r"`([^`]+)`", spec)
                if mq:
                    spec = mq.group(1).strip()
                rec = {"ledger": rel, "row": row_id, "line": ln, "registered": True,
                       "entries": [], "detail": []}
                try:
                    verdict_day = _row_date(cells, spec)
                    entries = _parse_entries(spec)
                except ValueError as e:
                    rec["status"] = "red"
                    rec["detail"].append(f"登记格式错: {e}")
                    rows.append(rec)
                    continue
                rec["verdict_day"] = verdict_day
                if not verdict_day:
                    rec["status"] = "red"
                    rec["detail"].append("缺裁决日（行内无 YYYY-MM-DD 且未写 裁决日=）——登记不全")
                    rows.append(rec)
                    continue
                all_ok = True
                for path, anchor, sha in entries:
                    ok, reasons = _check_entry(path, anchor, sha, verdict_day)
                    rec["entries"].append({"file": path, "anchor": anchor[:60],
                                           "sha256": bool(sha), "ok": ok, "reasons": reasons})
                    if not ok:
                        all_ok = False
                        rec["detail"].extend(reasons)
                rec["status"] = "pass" if all_ok else "red"
                rows.append(rec)
    return rows


def report(rows, as_json=False):
    red = [r for r in rows if r["status"] == "red"]
    reg = sum(1 for r in rows if r.get("registered"))
    if as_json:
        print(json.dumps({"ledgers_scanned": len({r["ledger"] for r in rows}),
                          "verdict_rows": len(rows), "registered": reg,
                          "unregistered": len(rows) - reg, "red": len(red), "rows": rows},
                         ensure_ascii=False, indent=1))
    else:
        print(f"writeback-check: 裁决行 {len(rows)} 条（登记回写 {reg}，未登记 {len(rows) - reg}），"
              f"红 {len(red)} 条")
        for r in rows:
            mark = "PASS" if r["status"] == "pass" else "RED "
            vd = r.get("verdict_day") or "?"
            print(f"  [{mark}] {r['ledger']}:{r.get('line', '?')} 裁决={r['row']} 裁决日={vd}")
            for e in r["entries"]:
                print(f"         {'✓' if e['ok'] else '✗'} {e['file']}#{e['anchor']}"
                      f"{' @sha256' if e['sha256'] else ''}")
            for d in r["detail"]:
                print(f"         ! {d}")
    return 1 if red else 0


def selftest():
    """夹具自证：$HOME 临时台账+正本，覆盖绿/红各通路；不碰真台账、零网络。"""
    import tempfile
    base = tempfile.mkdtemp(prefix="writeback-check-", dir=os.path.expanduser("~"))
    global WS
    old_ws = WS
    try:
        # 夹具正本
        def w(rel, text, mtime=None):
            fp = os.path.join(base, rel)
            os.makedirs(os.path.dirname(fp), exist_ok=True)
            with open(fp, "w", encoding="utf-8") as f:
                f.write(text)
            if mtime:
                os.utime(fp, (mtime, mtime))
            return fp
        import time as _t
        now = _t.time()
        w("正本A.md", "# A\n锚甲在案\n", now)                      # 绿：锚在、mtime 新
        w("正本B.md", "# B\n没有那个锚\n", now)                    # 红：锚缺失
        # 正本C 不建 → 红：文件缺失
        w("正本D.md", "# D\n锚丁在案\n", now)                      # 红：mtime 早于裁决日
        os.utime(os.path.join(base, "正本D.md"), (now - 40 * 86400, now - 40 * 86400))
        frozen = w("冻结件.md", "# F\n锚戊在案\n", now)
        sha_ok = hashlib.sha256(open(frozen, "rb").read()).hexdigest()
        w("漂移件.md", "# G\n锚己在案\n", now)
        sha_bad = "0" * 64
        ledger = os.path.join(base, "台账.md")
        with open(ledger, "w", encoding="utf-8") as f:
            f.write("| # | 日 | 内容 |\n|---|---|---|\n")
            f.write("| X-0 | 2026-10-01 | 无标记行——必须被忽略 |\n")
            f.write(f"| X-1 | 2026-10-20 | 绿例 回写清单: 正本A.md#锚甲在案 |\n")
            f.write(f"| X-2 | 2026-10-20 | 红例锚缺 回写清单: 正本B.md#锚甲在案 |\n")
            f.write(f"| X-3 | 2026-10-20 | 红例件缺 回写清单: 正本C.md#whatever |\n")
            f.write(f"| X-4 | 2026-10-20 | 红例时逆 回写清单: 裁决日=2026-10-25; 正本D.md#锚丁在案 |\n")
            f.write(f"| X-5 | 2026-10-20 | 绿例哈希 回写清单: 冻结件.md#锚戊在案@sha256:{sha_ok} |\n")
            f.write(f"| X-6 | 2026-10-20 | 红例哈希漂移 回写清单: 漂移件.md#锚己在案@sha256:{sha_bad} |\n")
            f.write(f"| X-7 | 2026-10-20 | 红例格式错 回写清单: 没有井号 |\n")
            f.write(f"| X-8 | 2026-10-21 | 绿例反引号规格+全角分隔 回写清单: `裁决日=2026-10-21；正本A.md#锚甲在案`（尾注 prose 不得被误读） |\n")
            f.write("| X-8b | 无日期 | 红例缺裁决日 回写清单: 正本A.md#锚甲在案 |\n")
            f.write("| X-9 | 2026-10-20 | 裁决 | 红例未登记——裁决行无回写登记标记，必须红 |\n")
        WS = base
        rows = scan_ledgers(["台账.md"])
        by_row = {r["row"]: r for r in rows}
        expect = {"X-1": "pass", "X-2": "red", "X-3": "red", "X-4": "red",
                  "X-5": "pass", "X-6": "red", "X-7": "red", "X-8": "pass", "X-8b": "red",
                  "X-9": "red"}
        fails = []
        if "X-0" in by_row:
            fails.append("无标记行被误扫")
        for rid, st in expect.items():
            got = by_row.get(rid, {}).get("status")
            ok = got == st
            print(f"  {rid}: {got}（期望 {st}）{'PASS' if ok else 'FAIL'}")
            if not ok:
                fails.append(rid)
        # X-4 的红色原因必须含"早于裁决日"；X-2 含"锚未命中"；X-6 含"sha256 漂移"
        for rid, kw in (("X-4", "早于裁决日"), ("X-2", "锚未命中"),
                        ("X-6", "sha256 漂移"), ("X-3", "正本缺失"), ("X-7", "登记格式错"),
                        ("X-9", "未登记")):
            detail = " ".join(by_row.get(rid, {}).get("detail", []))
            ok = kw in detail
            print(f"  {rid} 原因含[{kw}]: {'PASS' if ok else 'FAIL'}")
            if not ok:
                fails.append(rid + ":" + kw)
        rc = report(rows)
        ok_rc = rc == 1
        print(f"  有红时 exit=1: {'PASS' if ok_rc else 'FAIL'}")
        if not ok_rc:
            fails.append("exit-code")
        if fails:
            print(f"SELFTEST FAIL: {fails}")
            return 1
        npass = sum(1 for r in rows if r["status"] == "pass")
        print(f"SELFTEST PASS: {len(rows)} 夹具行（{npass} 绿 {len(rows) - npass} 红）"
              f"+ 无标记非裁决行忽略 + 未登记裁决行=红 + 红色原因逐条对上")
        return 0
    finally:
        WS = old_ws
        import shutil
        shutil.rmtree(base, ignore_errors=True)


def main(argv=None):
    p = argparse.ArgumentParser(description="裁决回写核对门（台账「回写清单」标记行 → 正本已改机对账）")
    p.add_argument("--ledgers", action="append", default=None,
                   help="台账文件（workspace 相对路径，可多次；缺省两条总台账）")
    p.add_argument("--json", action="store_true", help="JSON 输出")
    p.add_argument("--selftest", action="store_true", help="夹具自证（$HOME 临时件，不碰真台账）")
    args = p.parse_args(argv)
    if args.selftest:
        return selftest()
    ledgers = args.ledgers or DEFAULT_LEDGERS
    try:
        rows = scan_ledgers(ledgers)
    except Exception as e:  # noqa: BLE001
        print(f"writeback-check 执行错: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    if not rows:
        print("writeback-check: 台账内未发现任何裁决行（无核对对象；有裁决必有登记或红）")
        return 0
    return report(rows, as_json=args.json)


if __name__ == "__main__":
    sys.exit(main())
