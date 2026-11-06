#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""改锚入批纪律门（波次B · B5 链 · 债号 C5 · 机械坐标勘正的补位面）。

问题（本次债的根因，C5 亲历）：方法论文档 计划/方法论-持续改进-20261031.md 以
`文件:行` 锚钉住被引件的坐标，而被引件（tools/all-gates.sh 等）是热改写件——别的批
改写被引件 ⇒ 坐标漂移 ⇒ anchor-check 断链。本次亲历：2026-11-03 J5 批刚勘正过的
12 处坐标（all-gates.sh 284→381 / 391→497 / 521→683 / 658→946 / 71→80 / 568→713 等）
在 2026-11-05 被并发批改写后**再次全断**（本批实测 9 处 FAIL）。检测面（anchor-check
在 all-gates L3）一直都在，但**「谁改的、何时改的、该批有没有同批回填」无人判**——
doc §8 M-6 只写了「漂移须注明并回填」这句文书，无机器绑定 ⇒ 同型漂移 48 小时内复发。

本门做什么（只读，不改任何判据件）：
  leg-1 判据源在位：方法论文档 + 计划/研究组/方法论批-20261031/anchor-check.py 可导入
        （判据解析器单一源，不另写一份正则）→ 缺件/不可导入 ⇒ rc=2 不可证。
  leg-2 锚面逐面复验（**复用 anchor-check 的 check_anchor，逐出现面另核**，与
        `anchor-check.py --sample 0` 同语义）：断链数 > 登记基线 ⇒ 红，并逐条归因：
          · 被锚文件 mtime > 文档 mtime ⇒「该批改写了被锚文件却未同批回填坐标」
            （同批纪律违反——mtime 为机械证据，非推测）；
          · 否则 ⇒「文档坐标陈旧/错（文档末次回填晚于该文件，但锚已失配）」；
          · 附「现位候选」：在目标件里按该面的声称/期望串逐字找现位行号（可操作）。
  leg-3 待复核提示（**不判红**，避免对无害编辑刷红）：被锚文件 mtime > 文档 mtime 但其
        锚仍有效 ⇒ 提示「坐标暂未失效，下次漂移即红，建议同批回填」。

退出码：0=绿 / 1=红（断链锚数超登记基线）/ 2=不可证（缺件或判据源不可导入）。
用法：python3 -I tools/anchor-inbatch-gate.py [--registry PATH] [--doc PATH] [--selftest]
"""
import argparse
import hashlib
import importlib.util
import json
import os
import sys
from datetime import datetime
from pathlib import Path

WS = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = "30-工件/门红面批-20261105/gate-registry.json"
DEFAULT_DOC = "计划/方法论-持续改进-20261031.md"
DEFAULT_CHECKER = "计划/研究组/方法论批-20261031/anchor-check.py"


def sha256_file(p: Path):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def load_checker(checker: Path):
    if not checker.is_file():
        return None, "[缺件] 判据源不存在：%s" % checker
    spec = importlib.util.spec_from_file_location("anchor_check_b5", str(checker))
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as e:                                   # noqa: BLE001
        return None, "[坏件] 判据源不可导入：%s（%s）" % (checker, e)
    return mod, None


def candidate_lines(ac, path, expected, claims, limit=3):
    """现位候选：在目标件里按该面的声称/期望串逐字找现位行号。"""
    p = ac.resolve(path)
    if p is None or not p.is_file():
        return []
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    needles = []
    if expected:
        n = ac.norm(expected[:24])
        if len(n) >= 6:
            needles.append(n)
    for span in (claims or []):
        for part in ac.claim_parts(span):
            n = ac.norm(part)
            if len(n) >= 6:
                needles.append(n)
    needles = sorted(set(needles), key=len, reverse=True)
    # 择「最稀有」的那条声称作定位指针（同名 token 在文件里出现越少越具判别力）：
    # 例：M-2 锚的三个声称里 'all-gates.sh'/'tools/all-gates.sh' 命中头注用法段多处，
    # 而 'anchor-check.py' 全文件仅一处 ⇒ 现位候选应指后者。
    scored = []
    for n in needles:
        cnt = sum(1 for txt in lines if n in ac.norm(txt))
        if cnt:
            scored.append((cnt, -len(n), n))
    if not scored:
        return []
    scored.sort()
    best_n = scored[0][2]
    return [(ln, txt.strip()[:70]) for ln, txt in enumerate(lines, 1)
            if best_n in ac.norm(txt)][:limit]


def check_all_faces(ac):
    """逐锚逐面复验（与 anchor-check --sample 0 同语义）。返回 (broken[], pending[])。"""
    anchors, _commits = ac.collect()
    broken, pending = [], []
    for a in anchors:
        faces = a["faces"] or [{"claims": a["claims"], "prose": a["prose"],
                                "reqv": a["reqv"], "sym": a["sym"],
                                "is_live": a["is_live"], "paired": a["paired"],
                                "docline": 0}]
        for fi, f in enumerate(faces):
            ok, detail, tag = ac.check_anchor(
                a["path"], a["line"], a["expected"] if fi == 0 else None,
                f["claims"], f["prose"], f["is_live"], a["rng"], f["paired"],
                f["reqv"], f["sym"])
            if not ok:
                broken.append({"anchor": "%s:%d" % (a["path"], a["line"]),
                               "docline": f.get("docline"), "detail": detail,
                               "tag": tag, "claims": f["claims"], "expected": a["expected"],
                               "is_live": f["is_live"]})
            elif f["is_live"]:
                continue
            else:
                p = ac.resolve(a["path"])
                if p is not None and p.is_file():
                    pending.append((a["path"], p.stat().st_mtime))
    return anchors, broken, pending


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry", default=DEFAULT_REGISTRY)
    ap.add_argument("--doc", default=DEFAULT_DOC)
    ap.add_argument("--checker", default=DEFAULT_CHECKER)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    reg_path = WS / args.registry
    reg = None
    if reg_path.is_file():
        try:
            reg = json.loads(reg_path.read_text(encoding="utf-8"))
        except Exception:                                      # noqa: BLE001
            reg = None
    cfg = ((reg or {}).get("anchor_inbatch") or {})
    baseline = int((cfg.get("registered_gaps") or {}).get("broken_anchors", 0))

    doc_path = WS / args.doc
    checker_path = WS / args.checker
    if not doc_path.is_file():
        print("[FATAL] 方法论文档不在位：%s" % doc_path)
        return 2
    ac, err = load_checker(checker_path)
    if ac is None:
        print(err)
        return 2

    # 判据源以自身为准（--doc 可换文档；换档时解析器的 DOC 常量同步切换）
    ac.DOC = doc_path

    print("== 改锚入批纪律门（债号 C5 · 波次B·B5）")
    print("工作区：%s" % WS)
    print("  文档：%s（mtime %s）" % (doc_path, datetime.fromtimestamp(doc_path.stat().st_mtime)))
    print("  判据源：%s（sha256 %s）" % (checker_path, sha256_file(checker_path)[:16]))
    if reg:
        print("  登记面：%s（断链锚基线=%d，只增不减）" % (args.registry, baseline))

    anchors, broken, pending = check_all_faces(ac)
    doc_mtime = doc_path.stat().st_mtime

    # 待复核：被锚文件晚于文档末次回填（mtime 证据），但其锚仍有效
    later = {}
    for path, mt in pending:
        if mt > doc_mtime:
            later[path] = mt
    if later:
        print("[提示] 待复核（不判红）：以下被锚文件在文档末次回填之后被改写，"
              "坐标暂未失效，但下次漂移即红，建议该批同批回填：")
        for path, mt in sorted(later.items()):
            print("           · %s（mtime %s > 文档 %s）" % (
                path, datetime.fromtimestamp(mt).strftime("%Y-%m-%d %H:%M:%S"),
                datetime.fromtimestamp(doc_mtime).strftime("%Y-%m-%d %H:%M:%S")))

    if not broken:
        print("[绿] leg-2 锚面逐面复验：%d 锚全部可解析（断链 0，登记基线 %d）"
              % (len(anchors), baseline))
        print("结论：绿（无断链锚；同批纪律面未见违反）")
        return 0

    print("[红] leg-2 锚面逐面复验：断链 %d 处（登记基线 %d）" % (len(broken), baseline))
    for b in broken:
        p = ac.resolve(b["anchor"].rsplit(":", 1)[0])
        mt = p.stat().st_mtime if (p is not None and p.is_file()) else None
        if mt is not None and mt > doc_mtime:
            why = ("被锚文件 mtime %s 晚于文档末次回填 mtime %s ⇒ **该批改写了被锚文件却未同批"
                   "回填坐标**（同批纪律违反，mtime 为机械证据）" % (
                       datetime.fromtimestamp(mt).strftime("%Y-%m-%d %H:%M:%S"),
                       datetime.fromtimestamp(doc_mtime).strftime("%Y-%m-%d %H:%M:%S")))
        else:
            why = "文档末次回填不晚于被锚文件，但锚已失配 ⇒ 文档坐标陈旧/错（回填遗漏或写错）"
        print("           · %s（doc 行 %s）：%s" % (b["anchor"], b["docline"], b["detail"][:120]))
        print("             归因：%s" % why)
        cands = candidate_lines(ac, b["anchor"].rsplit(":", 1)[0], b["expected"], b["claims"])
        if cands:
            print("             现位候选：" + "；".join(":%d「%s」" % (ln, t) for ln, t in cands))
        else:
            print("             现位候选：未按该面声称在目标件中寻得（可能该面已失效，须人工定夺）")
    print("结论：红（断链锚 %d 处 > 登记基线 %d）" % (len(broken), baseline))
    return 1


if __name__ == "__main__":
    sys.exit(main())
