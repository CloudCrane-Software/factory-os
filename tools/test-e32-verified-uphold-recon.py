#!/usr/bin/env python3
"""test-e32-verified-uphold-recon.py — RT-E32 拦截机制④「对账巡检门」（2026-11-02 接入）。

工单判据（逃逸问题台账 RT-E32 机制④）：全扫 kb-seed/sandbox/verify/*.json，
`registry status=verified ∧ 卡内 verdict≠uphold` 计数必须=0（巡检一条命令可跑）。
背景：2026-10-31 RT 审计修复（event-router admit 只过滤 uphold 子集，R10/R11）只挡
增量——存量 refute/unverifiable 搭车入库原子（铁证 sbx-kb-atoms-cls-2303.17760-r2-19：
裁决原文明写「数字 25000 在证据文本中不存在」仍双库 verified）无任何门消费，「代码修
数据未清」持续。2026-11-02 存量清洗腿（tools/kb-e32-legacy-clean.py --apply）降级
353 条后，本门常驻堵回归：任何 refute/unverifiable 原子再以 verified 状态出现在双库，
门即红。

判据（与 kb-e32-legacy-clean.py 同判据、独立实现——对账门不借清洗脚本的实现路径，
防「对账面自身失明」同源病，逃逸台账模式⑩）：
  违规 = 原子 registry status=verified（或 kb/kb.db atoms status=verified）
         ∧ 该原子在任一验证卡被裁 verdict∈{refute,unverifiable}
         ∧ 非「翻案豁免」。
  翻案豁免 = registry note 依据卡对该原子 verdict=uphold ∧ quote_check=true ∧
             该卡 received_at 晚于该原子全部非 uphold 裁决——入库所据卡是裁决史上
             最新权威仲裁（R10/R11「他卡可独立复核翻案」合法产物，不得误红）。
  不可解析验证卡 > 0 即红（对账盲区 fail-closed：解析不了的卡=看不见的裁决）。

检查项：
  P1 生产对账（默认模式）：unparseable=0 ∧ registry 违规=0 ∧ kb 违规=0；
     附报 exempt（翻案豁免）与违规分类计数（note-cited refute / latest non-uphold）。
  S1 --selftest：合成夹具全链自证有牙——①refute 后无仲裁仍 verified=违规（铁证形态）
     ②refute 后他卡 uphold∧qc 翻案且依据卡最新=豁免（不误红）③清洗后（candidate/retired）
     不再计违规 ④坏卡计 unparseable ⑤uphold-only 原子零违规。

用法：
  python3 tools/test-e32-verified-uphold-recon.py            # 生产对账（all-gates L2）
  python3 tools/test-e32-verified-uphold-recon.py --selftest # 夹具自证（不碰生产库）
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
NONUP = ("refute", "unverifiable")
SCRATCH = os.path.join(os.path.expanduser("~"), "e32recon-selftest-%d" % os.getpid())

EXIT_OK, EXIT_FAIL, EXIT_ENV = 0, 1, 2


class Fail(Exception):
    pass


def check(cond, msg):
    if not cond:
        raise Fail(msg)


def scan_judgments(verify_dir):
    """atom_id -> [{ts, card, verdict, qc}]；返回 (judgments, unparseable, n_files)。"""
    files = sorted(glob.glob(os.path.join(verify_dir, "*.json")))
    judgments, unparseable = {}, []
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
        ts = float(d.get("received_at") or 0.0)
        for v in (pay.get("verdicts") or pay.get("verifications") or []):
            if isinstance(v, dict) and v.get("atom_id") and v.get("verdict") in VERDICTS:
                judgments.setdefault(v["atom_id"], []).append(
                    {"ts": ts, "card": os.path.basename(p), "verdict": v["verdict"],
                     # qc 真值口径与 event-router.qc_true 逐字同判据（2026-11-02 类型洞
                     # 修复）：仅 JSON 布尔 true 算真，字符串 "true"/"false"、1/0 一律非真
                     # （bool("false")=True 曾使豁免侧与路由器判定相反）。
                     "qc": isinstance(v.get("quote_check"), bool) and v.get("quote_check")})
    return judgments, unparseable, len(files)


def reconcile(judgments, reg_rows, kb_verified):
    """独立对账实现：→ dict(violations_reg, violations_kb, exempt, note_refute, latest_nonup)。
    reg_rows: {id: (status, note)}；kb_verified: set(kb atoms status=verified)。
    分类计数只对违规原子做（豁免/干净/已消费的原子不进分母，防空口径虚数）。"""
    violations_reg, violations_kb, exempt = [], [], []
    note_refute = note_missing = latest_nonup = 0
    for aid, js in judgments.items():
        reg_status, note = reg_rows.get(aid, (None, ""))
        kb_v = aid in kb_verified
        nonup = [j for j in js if j["verdict"] in NONUP]
        if not nonup:
            continue
        note_fn = os.path.basename(note[3:]) if note and note.startswith("依据:") else ""
        note_j = next((j for j in js if j["card"] == note_fn), None)
        is_exempt = bool(
            note_j and note_j["verdict"] == "uphold" and note_j["qc"]
            and note_j["ts"] > max(j["ts"] for j in nonup))
        if is_exempt:
            exempt.append(aid)
            continue
        in_reg = reg_status == "verified"
        in_kb = kb_v
        if not (in_reg or in_kb):
            continue  # 已消费（candidate/rejected/retired）——不违规也不进分类分母
        violations_reg.append(aid) if in_reg else None
        violations_kb.append(aid) if in_kb else None
        if note_j and note_j["verdict"] in NONUP:
            note_refute += 1          # 入库依据卡自身判非（E32 搭车主形态）
        elif not note_j:
            note_missing += 1         # verified 无可解析依据卡（非豁免路径）
        else:
            latest_nonup += 1         # 依据卡 uphold 但其后有非 uphold 裁决未消费（铁证原子形态）
    return {"violations_reg": violations_reg, "violations_kb": violations_kb,
            "exempt": exempt, "note_refute": note_refute,
            "note_missing": note_missing, "latest_nonup": latest_nonup}


def selftest():
    """S1 合成夹具全链自证（不碰生产库）。"""
    shutil.rmtree(SCRATCH, ignore_errors=True)
    os.makedirs(os.path.join(SCRATCH, "verify"), exist_ok=True)
    vd = os.path.join(SCRATCH, "verify")

    def card(name, ts, entries):
        with open(os.path.join(vd, name), "w", encoding="utf-8") as fh:
            json.dump({"task_id": "t", "received_at": ts,
                       "payload": {"verify": True, "card_id": name,
                                   "verdicts": entries}}, fh, ensure_ascii=False)

    # 铁证形态 V1：卡A uphold（入库依据）→ 卡B refute（无后续仲裁）→ 违规
    card("cA.json", 1000.0, [{"atom_id": "V1", "verdict": "uphold", "quote_check": True}])
    card("cB.json", 2000.0, [{"atom_id": "V1", "verdict": "refute", "quote_check": True}])
    # 翻案形态 V2：卡C refute → 卡D uphold∧qc（入库依据、最新）→ 豁免，不得误红
    card("cC.json", 1000.0, [{"atom_id": "V2", "verdict": "refute", "quote_check": True}])
    card("cD.json", 2000.0, [{"atom_id": "V2", "verdict": "uphold", "quote_check": True}])
    # 干净原子 V3：全 uphold
    card("cE.json", 1000.0, [{"atom_id": "V3", "verdict": "uphold", "quote_check": True}])
    # 清洗后形态 V4：同 V1 但已降级 candidate / kb retired → 不计违规
    card("cF.json", 1000.0, [{"atom_id": "V4", "verdict": "uphold", "quote_check": True}])
    card("cG.json", 2000.0, [{"atom_id": "V4", "verdict": "unverifiable", "quote_check": True}])
    # 坏卡：不可解析 → unparseable
    with open(os.path.join(vd, "cbad.json"), "w", encoding="utf-8") as fh:
        fh.write("{not json")

    reg = os.path.join(SCRATCH, "registry.db")
    con = sqlite3.connect(reg)
    with con:
        con.execute("CREATE TABLE candidates(id TEXT PRIMARY KEY, status TEXT, note TEXT)")
        con.executemany("INSERT INTO candidates VALUES(?,?,?)", [
            ("V1", "verified", "依据:%s" % os.path.join(vd, "cA.json")),
            ("V2", "verified", "依据:%s" % os.path.join(vd, "cD.json")),
            ("V3", "verified", "依据:%s" % os.path.join(vd, "cE.json")),
            ("V4", "candidate", "E32清洗:降级待复核"),
        ])
    con.close()
    kb = os.path.join(SCRATCH, "kb.db")
    kcon = sqlite3.connect(kb)
    with kcon:
        kcon.execute("CREATE TABLE atoms(id TEXT PRIMARY KEY, status TEXT)")
        kcon.executemany("INSERT INTO atoms VALUES(?,?)",
                         [("V1", "verified"), ("V2", "verified"), ("V3", "verified"),
                          ("V4", "retired")])
    kcon.close()

    try:
        judgments, unparseable, n_files = scan_judgments(vd)
        con = sqlite3.connect("file:%s?mode=ro" % reg, uri=True)
        reg_rows = {r[0]: (r[1], r[2])
                    for r in con.execute("SELECT id, status, note FROM candidates")}
        con.close()
        kcon = sqlite3.connect("file:%s?mode=ro" % kb, uri=True)
        kb_verified = {r[0] for r in kcon.execute(
            "SELECT id FROM atoms WHERE status='verified'")}
        kcon.close()
        r = reconcile(judgments, reg_rows, kb_verified)
        check(len(unparseable) == 1 and unparseable[0]["file"] == "cbad.json",
              "坏卡未被计 unparseable: %r" % unparseable)
        check(n_files == 8, "夹具卡数 %d != 8（7 有效卡+1 坏卡）" % n_files)
        check(r["violations_reg"] == ["V1"] and r["violations_kb"] == ["V1"],
              "铁证形态应恰 V1 违规（reg=%r kb=%r）" % (r["violations_reg"], r["violations_kb"]))
        check(r["exempt"] == ["V2"], "翻案形态应豁免 V2（实 %r）" % r["exempt"])
        check("V3" not in r["violations_reg"] and "V4" not in r["violations_reg"],
              "干净/已清洗原子被误计违规")
        check(r["note_refute"] == 0 and r["latest_nonup"] == 1 and r["note_missing"] == 0,
              "违规分类计数不符: %r" % {k: r[k] for k in
                                       ("note_refute", "latest_nonup", "note_missing")})

        # 清洗后：V1 registry→candidate、kb→retired → 违规归零（门绿）
        con = sqlite3.connect(reg)
        with con:
            con.execute("UPDATE candidates SET status='candidate', note='E32清洗' "
                        "WHERE id='V1'")
        con.close()
        kcon = sqlite3.connect(kb)
        with kcon:
            kcon.execute("UPDATE atoms SET status='retired' WHERE id='V1'")
        kcon.close()
        con = sqlite3.connect("file:%s?mode=ro" % reg, uri=True)
        reg_rows = {r2[0]: (r2[1], r2[2])
                    for r2 in con.execute("SELECT id, status, note FROM candidates")}
        con.close()
        kcon = sqlite3.connect("file:%s?mode=ro" % kb, uri=True)
        kb_verified = {r2[0] for r2 in kcon.execute(
            "SELECT id FROM atoms WHERE status='verified'")}
        kcon.close()
        r2 = reconcile(judgments, reg_rows, kb_verified)
        check(not r2["violations_reg"] and not r2["violations_kb"],
              "清洗后违规应归零（reg=%r kb=%r）" % (r2["violations_reg"], r2["violations_kb"]))
    finally:
        shutil.rmtree(SCRATCH, ignore_errors=True)
    print("E32-RECON SELFTEST PASSED: 5/5 断言全过（铁证违规/翻案豁免/已清洗不计/坏卡计数/分类）")
    return EXIT_OK


def main(argv=None):
    ap = argparse.ArgumentParser(description="RT-E32 对账巡检门：verified ∧ 卡内 verdict≠uphold 计数必须=0")
    ap.add_argument("--selftest", action="store_true", help="合成夹具自证（不碰生产库）")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    for f in (VERIFY_DIR, REGISTRY, KB_DB):
        if not os.path.exists(f):
            print("前置缺失: %s" % f)
            return EXIT_ENV
    t0 = time.time()
    judgments, unparseable, n_files = scan_judgments(VERIFY_DIR)
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
    r = reconcile(judgments, reg_rows, kb_verified)
    summary = {
        "gate": "RT-E32 对账巡检门（verified ∧ 卡内 verdict≠uphold 计数必须=0）",
        "verify_files": n_files, "unparseable": len(unparseable),
        "judged_atoms": len(judgments), "registry_verified": reg_verified,
        "kb_verified": len(kb_verified),
        "violations_registry": len(r["violations_reg"]),
        "violations_kb": len(r["violations_kb"]),
        "exempt_re_adjudication": len(r["exempt"]),
        "breakdown_note_card_refute": r["note_refute"],
        "breakdown_note_missing": r["note_missing"],
        "breakdown_post_admit_nonuphold": r["latest_nonup"],
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
        fail.append("kb 违规=%d 例:%s" % (len(r["violations_kb"]), r["violations_kb"][:5]))
    if fail:
        print("E32-RECON FAILED: %s" % "；".join(fail))
        return EXIT_FAIL
    print("E32-RECON PASSED: registry/kb 双库 verified 集合对卡内 refute/unverifiable "
          "裁决零违规（exempt 翻案豁免 %d 条）" % len(r["exempt"]))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
