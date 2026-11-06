#!/usr/bin/env python3
"""test-e67-qc-stock-recon.py — RT-E67 拦截机制②「全仓对账门」本尊（2026-11-02 施工）。

工单判据（逃逸问题台账 RT-E67 拦截机制②原文）：全仓对账门——
  verified ∧ 源卡 verdict=uphold ∧ quote_check=false 计数必须=0（巡检 SQL/全扫）。
背景（本次确证发现，2026-11-02 亲测）：该谓词的存量腿此前无任何门消费——
  · test-kb-quote-integrity.py 判的是引文逐字回查（A1/A2/A3=quote 是否在证据缓存），
    与 qc 字段无关（191 条仅空白排版差异豁免仍 pass=true 实证）；
  · test-e32-verified-uphold-recon.py 的 reconcile() 在原子无 refute/unverifiable
    裁决时整条 continue（源码 :100-101 `nonup=[...]; if not nonup: continue`），
    「uphold∧qc=false 但无人判非」的原子恰好被跳过；
  · test-verify-qc-truth-gate.py 自述 hermetic（:23-25），只验机制不验存量。
  三门叠加＝机制②谓词在门族里零覆盖，而欠账台账:39 RT-E67 行却按
  「门 test-kb-quote-integrity.py 入 all-gates」标 ✅ 销项——销项张冠李戴，本门补上真门。
存量侧：2026-11-02 实测 495 条双库 verified 违规（491 为审计时点数，此后 live 漂移），
已由 tools/kb-e67-qc-stock-clean.py --apply 清偿（198 条翻案改依据 + 297 条降级，
manifest 见 计划/研究组/红队终局轮-20261101/RT-E67-存量清洗-20261102/）；本门常驻堵回归：
任何 verified 原子的入库依据卡再出现 uphold∧quote_check 非真，本门即红。

判据（与 kb-e67-qc-stock-clean.py 同判据、独立实现——对账门不借清洗脚本的实现路径，
防「对账面自身失明」同源病，逃逸台账模式⑩；亦不借 test-e32 门之实现）：
  违规 = 原子 registry status=verified（或 kb/kb.db atoms status=verified）
         ∧ registry note 依据卡（"依据:<file>" 的 basename）在 kb-seed/sandbox/verify/
         对该原子的裁决 verdict=uphold ∧ quote_check 非真（false/缺字段同罪——
         机器真值链上「未证真」即视同假，与 event-router admit 侧
         `bool(v.get("quote_check"))` 消费口径逐字一致）。
  不豁免：本谓词不设翻案豁免分支——机制②判据是判据原文，不加宽不加窄；
  「依据卡已过时、他卡有更晚 uphold∧qc=true 翻案」的原子由清洗件改写依据（翻案改据）
  后本门自然绿，门本身不替账本做赦免（弱化判据＝对账面失明，E67 同根）。
  盲区 fail-closed：kb-seed/sandbox/verify/ 内不可解析验证卡 >0 即红（解析不了=看不见
  的裁决，与 E32 门同纪律）；依据卡指向 verify 目录外/文件已失（现势 6 条，provenance
  另族问题 RT-E63 面）如实计数上报、不判红不判绿——该 6 条不构成本谓词违规，
  但计数必须在汇总面可见，不许静默吞。

检查项：
  P1 生产对账（默认模式）：unparseable=0 ∧ registry 违规=0 ∧ kb 违规=0；
     附报 basis_unresolvable（依据卡不可解析路径）与 basis_entry_missing（依据卡无该原子
     裁决行）计数。
  S1 --selftest：合成夹具自证有牙——①uphold∧qc=false 双库 verified=双违规（铁证形态）
     ②uphold∧qc=true 干净不误红 ③qc 字段缺失同罪 ④状态位按库独立口径（registry
     candidate 不计 reg 侧、kb retired 不计 kb 侧；另一半照计）⑤kb-only verified 计入
     violations_kb ⑥坏卡 unparseable 红 ⑦依据卡缺该原子裁决行/文件已失 上报不红
     ⑧清洗后（candidate+retired）不再计违规。

用法：
  python3 tools/test-e67-qc-stock-recon.py            # 生产对账（all-gates L2，glob 自动注册）
  python3 tools/test-e67-qc-stock-recon.py --selftest # 夹具自证（不碰生产库）
退出码：0 全过；1 断言失败；2 前置不满足。零网络、零密钥、只读生产库（mode=ro）。
临时夹具建在 $HOME 下自建目录（/tmp 配额有限），完工即删。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import sqlite3
import sys
import time

WS = os.path.expanduser("~/workspace/agent黑灯工厂")
VERIFY_DIR = os.path.join(WS, "kb-seed", "sandbox", "verify")
REGISTRY = os.path.join(WS, "kb-seed", "registry.db")
KB_DB = os.path.join(WS, "kb", "kb.db")
VERDICTS = ("uphold", "refute", "unverifiable")
SCRATCH = os.path.join(os.path.expanduser("~"), "e67qcrecon-selftest-%d" % os.getpid())

EXIT_OK, EXIT_FAIL, EXIT_ENV = 0, 1, 2


class Fail(Exception):
    pass


def check(cond, msg):
    if not cond:
        raise Fail(msg)


def scan_cards(verify_dir):
    """全扫验证卡 → (entries, unparseable, n_files)。
    entries: {(card_basename, atom_id): {"verdict","qc"}}（同卡同原子重复行取末条，
    与「卡面最终裁决」口径一致；生产数据实测无重复）。"""
    files = sorted(glob.glob(os.path.join(verify_dir, "*.json")))
    entries, unparseable = {}, []
    for p in files:
        try:
            with open(p, encoding="utf-8") as fh:
                d = json.load(fh)
        except Exception as e:  # noqa: BLE001 - 坏卡如实计数（盲区 fail-closed）
            unparseable.append({"file": os.path.basename(p), "error": str(e)[:120]})
            continue
        pay = d.get("payload") or {}
        if not isinstance(pay, dict):
            unparseable.append({"file": os.path.basename(p), "error": "payload-not-dict"})
            continue
        base = os.path.basename(p)
        for v in (pay.get("verdicts") or pay.get("verifications") or []):
            if isinstance(v, dict) and v.get("atom_id") and v.get("verdict") in VERDICTS:
                entries[(base, v["atom_id"])] = {
                    "verdict": v["verdict"],
                    "qc": bool(v.get("quote_check")),  # 缺字段=非真=同罪（router 消费口径）
                }
    return entries, unparseable, len(files)


def basis_fn(note):
    """registry note → 依据卡 basename；非「依据:」前缀返回 None。"""
    if note and note.startswith("依据:"):
        return os.path.basename(note[3:])
    return None


def reconcile(entries, reg_rows, kb_verified):
    """独立对账实现 → dict(violations_reg, violations_kb, basis_unresolvable,
    basis_entry_missing)。
    reg_rows: {id: (status, note)}；kb_verified: set(kb atoms status=verified)。
    violations_*: 命中「verified ∧ 依据卡 uphold ∧ qc 非真」的原子 id 列表。"""
    violations_reg, violations_kb = [], []
    basis_unresolvable = basis_entry_missing = 0
    for aid, (status, note) in sorted(reg_rows.items()):
        fn = basis_fn(note)
        if fn is None:
            if status == "verified":
                basis_unresolvable += 1
            continue
        ent = entries.get((fn, aid))
        if ent is None:
            if status == "verified":
                # 依据卡在 verify 目录内但无该原子裁决行（或卡文件已失）——
                # 本谓词不可判定，如实上报不判红（provenance 另族问题）
                basis_entry_missing += 1
            continue
        if status == "verified" and ent["verdict"] == "uphold" and not ent["qc"]:
            violations_reg.append(aid)
        # kb 侧独立口径：kb verified ∧ 依据卡 uphold ∧ qc 非真（registry 状态不预判）
        if aid in kb_verified and ent["verdict"] == "uphold" and not ent["qc"]:
            violations_kb.append(aid)
    return {"violations_reg": violations_reg, "violations_kb": violations_kb,
            "basis_unresolvable": basis_unresolvable,
            "basis_entry_missing": basis_entry_missing}


def load_prod():
    entries, unparseable, n_files = scan_cards(VERIFY_DIR)
    con = sqlite3.connect("file:%s?mode=ro" % REGISTRY, uri=True)
    try:
        reg_rows = {r[0]: (r[1], r[2])
                    for r in con.execute("SELECT id, status, note FROM candidates")}
        reg_verified = sum(1 for s, _ in reg_rows.values() if s == "verified")
    finally:
        con.close()
    kcon = sqlite3.connect("file:%s?mode=ro" % KB_DB, uri=True)
    try:
        kb_verified = {r[0] for r in kcon.execute(
            "SELECT id FROM atoms WHERE status='verified'")}
    finally:
        kcon.close()
    return entries, unparseable, n_files, reg_rows, reg_verified, kb_verified


def selftest():
    """S1 合成夹具全链自证（不碰生产库）。"""
    shutil.rmtree(SCRATCH, ignore_errors=True)
    os.makedirs(os.path.join(SCRATCH, "verify"), exist_ok=True)
    vd = os.path.join(SCRATCH, "verify")

    def card(name, entries):
        with open(os.path.join(vd, name), "w", encoding="utf-8") as fh:
            json.dump({"task_id": "t", "received_at": 1000.0,
                       "payload": {"verify": True, "card_id": name,
                                   "verdicts": entries}}, fh, ensure_ascii=False)

    # ①铁证形态 V1：依据卡 uphold∧qc=false、双库 verified → 双违规
    card("cA.json", [{"atom_id": "V1", "verdict": "uphold", "quote_check": False}])
    # ②干净原子 V2：依据卡 uphold∧qc=true → 不误红
    card("cB.json", [{"atom_id": "V2", "verdict": "uphold", "quote_check": True}])
    # ③qc 字段缺失=非真同罪 V3 → 违规（router 消费口径 bool(v.get("quote_check"))）
    card("cC.json", [{"atom_id": "V3", "verdict": "uphold"}])
    # ④状态位保护（按库独立口径）V4/V5：同款 qc=false——V4 registry=candidate（reg 不计，
    # 但 kb=verified 须计 kb 违规）；V5 kb=retired（kb 不计，但 registry=verified 须计）
    card("cD.json", [{"atom_id": "V4", "verdict": "uphold", "quote_check": False},
                     {"atom_id": "V5", "verdict": "uphold", "quote_check": False}])
    # ⑥坏卡 → unparseable
    with open(os.path.join(vd, "cbad.json"), "w", encoding="utf-8") as fh:
        fh.write("{not json")
    # ⑦依据卡无该原子裁决行 V7（卡存在、无行）→ 上报不红
    card("cE.json", [{"atom_id": "someone-else", "verdict": "uphold", "quote_check": True}])

    reg = os.path.join(SCRATCH, "registry.db")
    con = sqlite3.connect(reg)
    with con:
        con.execute("CREATE TABLE candidates(id TEXT PRIMARY KEY, status TEXT, note TEXT)")
        con.executemany("INSERT INTO candidates VALUES(?,?,?)", [
            ("V1", "verified", "依据:%s" % os.path.join(vd, "cA.json")),
            ("V2", "verified", "依据:%s" % os.path.join(vd, "cB.json")),
            ("V3", "verified", "依据:%s" % os.path.join(vd, "cC.json")),
            ("V4", "candidate", "依据:%s" % os.path.join(vd, "cD.json")),
            ("V5", "verified", "依据:%s" % os.path.join(vd, "cD.json")),
            ("V7", "verified", "依据:%s" % os.path.join(vd, "cE.json")),
        ])
    con.close()
    kb = os.path.join(SCRATCH, "kb.db")
    kcon = sqlite3.connect(kb)
    with kcon:
        kcon.execute("CREATE TABLE atoms(id TEXT PRIMARY KEY, status TEXT)")
        kcon.executemany("INSERT INTO atoms VALUES(?,?)",
                         [("V1", "verified"), ("V2", "verified"), ("V3", "verified"),
                          ("V4", "verified"), ("V5", "retired"), ("V7", "verified")])
    kcon.close()

    try:
        entries, unparseable, n_files = scan_cards(vd)
        con = sqlite3.connect("file:%s?mode=ro" % reg, uri=True)
        reg_rows = {r[0]: (r[1], r[2])
                    for r in con.execute("SELECT id, status, note FROM candidates")}
        con.close()
        kcon = sqlite3.connect("file:%s?mode=ro" % kb, uri=True)
        kb_verified = {r[0] for r in kcon.execute(
            "SELECT id FROM atoms WHERE status='verified'")}
        kcon.close()
        r = reconcile(entries, reg_rows, kb_verified)
        check(len(unparseable) == 1 and unparseable[0]["file"] == "cbad.json",
              "坏卡未被计 unparseable: %r" % unparseable)
        check(n_files == 6, "夹具卡数 %d != 6（5 有效卡+1 坏卡）" % n_files)
        check(r["violations_reg"] == ["V1", "V3", "V5"],
              "registry 侧应恰 V1+V3（qc 缺失同罪）+V5（reg verified∧kb retired）"
              "违规（实 %r）" % r["violations_reg"])
        check(r["violations_kb"] == ["V1", "V3", "V4"],
              "kb 侧应恰 V1+V3+V4（kb-only V4 须计入；retired V5 不计）（实 %r）"
              % r["violations_kb"])
        check("V2" not in r["violations_reg"] and "V2" not in r["violations_kb"],
              "uphold∧qc=true 干净原子被误红")
        check(r["basis_entry_missing"] == 1 and r["basis_unresolvable"] == 0,
              "依据卡缺行应上报 1（实 %r）" % r)
        # ⑤依据卡指向 verify 目录外的卡文件（本夹具 cwd 下不存在）→ unresolvable 上报
        reg_rows2 = dict(reg_rows)
        reg_rows2["V9"] = ("verified", "依据:%s" % os.path.join(vd, "gone.json"))
        r2 = reconcile(entries, reg_rows2, kb_verified | {"V9"})
        check(r2["basis_entry_missing"] == 2,  # V7 + V9（卡文件不存在→entries 无行）
              "依据卡不可解析（缺行/缺文件）应合并上报 2（实 %r）" % r2)
        # 清洗后形态：V1 降级 candidate + kb retired → 违规归零（门绿）
        con = sqlite3.connect(reg)
        with con:
            con.execute("UPDATE candidates SET status='candidate' WHERE id='V1'")
        con.close()
        kcon = sqlite3.connect(kb)
        with kcon:
            kcon.execute("UPDATE atoms SET status='retired' WHERE id='V1'")
        kcon.close()
        kcon = sqlite3.connect("file:%s?mode=ro" % kb, uri=True)
        kb_verified = {x[0] for x in kcon.execute(
            "SELECT id FROM atoms WHERE status='verified'")}
        kcon.close()
        con = sqlite3.connect("file:%s?mode=ro" % reg, uri=True)
        reg_rows3 = {x[0]: (x[1], x[2])
                     for x in con.execute("SELECT id, status, note FROM candidates")}
        con.close()
        r3 = reconcile(entries, reg_rows3, kb_verified)
        check("V1" not in r3["violations_reg"] and "V1" not in r3["violations_kb"],
              "清洗后 V1 仍被计违规（幂等回归腿失明）: %r" % r3)
    finally:
        shutil.rmtree(SCRATCH, ignore_errors=True)
    print("E67-QC-STOCK-RECON SELFTEST PASSED: 8/8 断言全过（铁证双违规/干净不误红/"
          "qc缺失同罪/状态位按库口径/kb-only 计入/坏卡红/缺行上报/清洗后归零）")
    return EXIT_OK


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="RT-E67 机制②全仓对账门：verified ∧ 依据卡 uphold ∧ quote_check=false 计数必须=0")
    ap.add_argument("--selftest", action="store_true", help="合成夹具自证（不碰生产库）")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    for f in (VERIFY_DIR, REGISTRY, KB_DB):
        if not os.path.exists(f):
            print("前置缺失: %s" % f)
            return EXIT_ENV
    t0 = time.time()
    entries, unparseable, n_files, reg_rows, reg_verified, kb_verified = load_prod()
    r = reconcile(entries, reg_rows, kb_verified)
    summary = {
        "gate": "RT-E67 机制②全仓对账门（verified ∧ 依据卡 verdict=uphold ∧ "
                "quote_check=false 计数必须=0）",
        "verify_files": n_files, "unparseable": len(unparseable),
        "card_entries": len(entries),
        "registry_verified": reg_verified, "kb_verified": len(kb_verified),
        "violations_registry": len(r["violations_reg"]),
        "violations_kb": len(r["violations_kb"]),
        "basis_unresolvable": r["basis_unresolvable"],
        "basis_entry_missing": r["basis_entry_missing"],
        "took_s": round(time.time() - t0, 1),
    }
    print(json.dumps(summary, ensure_ascii=False))
    fail = []
    if unparseable:
        fail.append("unparseable=%d（对账盲区 fail-closed）: %s"
                    % (len(unparseable), [u["file"] for u in unparseable[:5]]))
    if r["violations_reg"]:
        fail.append("registry 违规=%d 例:%s" % (len(r["violations_reg"]),
                                               r["violations_reg"][:5]))
    if r["violations_kb"]:
        fail.append("kb 违规=%d 例:%s" % (len(r["violations_kb"]),
                                         r["violations_kb"][:5]))
    if fail:
        print("E67-QC-STOCK-RECON FAILED: %s" % "；".join(fail))
        return EXIT_FAIL
    print("E67-QC-STOCK-RECON PASSED: 双库 verified 原子的入库依据卡零 "
          "uphold∧quote_check=false（依据卡不可解析路径 %d 条如实上报不判红）"
          % r["basis_unresolvable"])
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
