#!/usr/bin/env python3
"""kb-e32-legacy-clean.py — RT-E32 拦截机制③「存量清洗」执行器（一次性，幂等，可重跑）。

背景（逃逸问题台账 RT-E32，计划/研究组/红队终局轮-20261101/逃逸问题台账.md）：
  2026-10-31 修复前，验证聚合 admit 把 judged 全量（含 refute/unverifiable）整包送
  registry_admit——验证者明确判非的原子以卡内他原子 uphold 率搭车入库转 verified
  （铁证：sbx-kb-atoms-cls-2303.17760-r2-19，裁决原文明写「数字 25000 在证据文本中
  不存在」仍双库 verified）。新码侧 admit 过滤（event-router.py R10/R11）只挡增量，
  存量污染无任何清洗/对账腿消费——本脚本执行 E32 机制③「降级并登记欠账」。

清洗口径（与巡检门 tools/test-e32-verified-uphold-recon.py 同判据，双实现互为对账）：
  违规 = registry status=verified ∧ 该原子在 kb-seed/sandbox/verify/*.json 任一卡内
         被裁 verdict∈{refute,unverifiable} ∧ 非「翻案豁免」。
  翻案豁免 = registry note 依据卡对该原子 verdict=uphold ∧ quote_check=true ∧
             该卡 received_at 晚于该原子全部非 uphold 裁决的 received_at——
             即入库所据卡在裁决史上是最新的权威仲裁（R10/R11「他卡可独立复核翻案」
             的合法产物，不得回滚；实测 27 条豁免，其中 sbx-kb-atoms-w4-2610.40186-22
             为新码落地后的真实翻案 admit）。
  铁证原子不豁免：其 note 依据卡（uphold 12/12）早于 6 次 refute 裁决，verified 状态
  从未消费后续 refute → 违规，降级。
动作：
  registry.db   verified → candidate（registry 状态机唯一可回行的层；note 改写为
                清洗记录并保留原依据与清洗依据，欠账=待独立复核翻案后方可再 admit）
  kb/kb.db      verified → retired（kb 状态机 verified→{merged,retired}，retired 为
                正本消费面合法退场态，经 kb.store.update_status 追加 provenance
                status_change 事件，历史可追溯；后续若他卡翻案再 admit，kb-ingest
                幂等 upsert 会带 status=verified 回场）
登记欠账：
  --apply 时写 计划/研究组/红队终局轮-20261101/RT-E32-存量清洗-20261102/cleanup-manifest.json
  （逐原子 refute 证据卡 + 原依据 + 豁免清单 + 前后状态计数）。

用法：
  python3 tools/kb-e32-legacy-clean.py            # 干跑：只算清洗清单，零写
  python3 tools/kb-e32-legacy-clean.py --apply    # 真清洗（先做一致性快照备份）
退出码：0 成功；1 --apply 有未预期失败；2 参数/前置不满足。
零网络、零密钥。改前备份（sqlite backup API 一致性快照，已存在不覆盖）：
  kb-seed/registry.db.20261102-pre-E32clean.bak / kb/kb.db.20261102-pre-E32clean.bak
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sqlite3
import sys
import time

WS = os.path.expanduser("~/workspace/agent黑灯工厂")
VERIFY_DIR = os.path.join(WS, "kb-seed", "sandbox", "verify")
REGISTRY = os.path.join(WS, "kb-seed", "registry.db")
KB_DB = os.path.join(WS, "kb", "kb.db")
MANIFEST_DIR = os.path.join(WS, "计划", "研究组", "红队终局轮-20261101",
                            "RT-E32-存量清洗-20261102")
BAK_SUFFIX = ".20261102-pre-E32clean.bak"
VERDICTS = ("uphold", "refute", "unverifiable")
NONUP = ("refute", "unverifiable")
CLEAN_REASON = "E32存量清洗2026-11-02: refute/unverifiable裁决搭车入库降级，待独立复核翻案"


def log(msg):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


def scan_judgments(verify_dir):
    """全扫验证回报卡 → (judgments, unparseable, files)。
    judgments: atom_id -> [{ts, card, verdict, qc}]（received_at 升序不保证，由消费方排序）。"""
    files = sorted(glob.glob(os.path.join(verify_dir, "*.json")))
    judgments, unparseable = {}, []
    for p in files:
        try:
            with open(p, encoding="utf-8") as fh:
                d = json.load(fh)
        except Exception as e:  # noqa: BLE001 - 坏卡如实登记（对账盲区），不静默跳过
            unparseable.append({"file": os.path.basename(p), "error": str(e)[:120]})
            continue
        pay = d.get("payload") or {}
        if not isinstance(pay, dict):
            unparseable.append({"file": os.path.basename(p), "error": "payload-not-dict"})
            continue
        ts = float(d.get("received_at") or 0.0)
        vsrc = pay.get("verdicts") or pay.get("verifications") or []
        for v in vsrc:
            if not isinstance(v, dict):
                continue
            aid, vd = v.get("atom_id"), v.get("verdict")
            if aid and vd in VERDICTS:
                judgments.setdefault(aid, []).append(
                    {"ts": ts, "card": os.path.basename(p), "verdict": vd,
                     # qc 真值口径与 event-router.qc_true 逐字同判据（2026-11-02 类型洞
                     # 修复）：仅 JSON 布尔 true 算真，非布尔值一律非豁免依据。
                     "qc": isinstance(v.get("quote_check"), bool) and v.get("quote_check")})
    return judgments, unparseable, files


def classify(judgments, reg_rows):
    """reg_rows: {id: (status, note)} → (violations, exempt)。
    violations: [{id, refute_cards, note_card, old_note}]；exempt: [id]。"""
    violations, exempt = [], []
    for aid, (status, note) in sorted(reg_rows.items()):
        if status != "verified":
            continue
        js = judgments.get(aid)
        if not js:
            continue
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
        violations.append({"id": aid, "note_card": note_fn or None,
                           "old_note": note or "",
                           "refute_cards": [{"card": j["card"], "ts": j["ts"],
                                             "verdict": j["verdict"]}
                                            for j in sorted(nonup, key=lambda x: x["ts"])]})
    return violations, exempt


def backup_once(src, dst):
    """sqlite backup API 一致性快照；dst 已存在则不覆盖（改前留证只做一次）。"""
    if os.path.exists(dst):
        log("备份已存在，不覆盖: %s" % dst)
        return False
    con = sqlite3.connect("file:%s?mode=ro" % src, uri=True)
    try:
        out = sqlite3.connect(dst)
        try:
            with out:
                con.backup(out)
        finally:
            out.close()
    finally:
        con.close()
    log("备份完成: %s" % dst)
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description="RT-E32 存量清洗：refute 搭车原子降级+登记（干跑默认）")
    ap.add_argument("--apply", action="store_true", help="真清洗（默认干跑零写）")
    a = ap.parse_args(argv)
    for f in (VERIFY_DIR, REGISTRY, KB_DB):
        if not os.path.exists(f):
            print("前置缺失: %s" % f)
            return 2

    judgments, unparseable, files = scan_judgments(VERIFY_DIR)
    con = sqlite3.connect("file:%s?mode=ro" % REGISTRY, uri=True)
    try:
        reg_rows = {r[0]: (r[1], r[2])
                    for r in con.execute("SELECT id, status, note FROM candidates")}
        before = dict(con.execute(
            "SELECT status, COUNT(*) FROM candidates GROUP BY status").fetchall())
    finally:
        con.close()
    kcon = sqlite3.connect("file:%s?mode=ro" % KB_DB, uri=True)
    try:
        kb_status = {r[0]: r[1] for r in kcon.execute("SELECT id, status FROM atoms")}
        kb_before = dict(kcon.execute(
            "SELECT status, COUNT(*) FROM atoms GROUP BY status").fetchall())
    finally:
        kcon.close()

    violations, exempt = classify(judgments, reg_rows)
    plan = [v for v in violations
            if reg_rows[v["id"]][0] == "verified"]      # 幂等：再跑只清仍 verified 的
    print(json.dumps({
        "mode": "apply" if a.apply else "dry-run",
        "verify_files": len(files), "unparseable": len(unparseable),
        "judged_atoms": len(judgments),
        "registry_status_before": before, "kb_status_before": kb_before,
        "violations_total": len(violations), "exempt_total": len(exempt),
        "plan_demote": len(plan),
        "plan_in_kb_verified": sum(1 for v in plan if kb_status.get(v["id"]) == "verified"),
        "iron_atom_in_plan": any(v["id"] == "sbx-kb-atoms-cls-2303.17760-r2-19"
                                 for v in plan),
    }, ensure_ascii=False))
    for v in plan[:10]:
        print("  plan: %s | refute×%d | 原依据:%s" %
              (v["id"], len(v["refute_cards"]),
               os.path.basename(v["note_card"]) if v["note_card"] else "-"))
    if unparseable:
        log("注意：%d 份验证卡不可解析（对账盲区，已列入 manifest；巡检门会红）" % len(unparseable))

    if not a.apply:
        log("干跑完成，零写。加 --apply 执行清洗。")
        return 0

    # ---- --apply：备份 → registry 降级 → kb retired → manifest ----
    os.makedirs(MANIFEST_DIR, exist_ok=True)
    bak_reg = REGISTRY + BAK_SUFFIX
    bak_kb = KB_DB + BAK_SUFFIX
    backup_once(REGISTRY, bak_reg)
    backup_once(KB_DB, bak_kb)

    demoted, kb_retired, kb_missing, reg_skip = [], [], [], []
    con = sqlite3.connect(REGISTRY)
    try:
        with con:
            for v in plan:
                cur = con.execute(
                    "UPDATE candidates SET status='candidate', note=? "
                    "WHERE id=? AND status='verified'",
                    ("E32清洗2026-11-02:%s; 原依据:%s; 清洗依据:%s"
                     % (CLEAN_REASON,
                        os.path.basename(v["note_card"]) if v["note_card"] else "-",
                        "、".join(c["card"] for c in v["refute_cards"][:2])),
                     v["id"]))
                (demoted if cur.rowcount else reg_skip).append(v["id"])
    finally:
        con.close()

    if WS not in sys.path:
        sys.path.insert(0, WS)
    from kb.store import KBStore  # noqa: E402
    store = KBStore(KB_DB)
    for aid in demoted:
        if kb_status.get(aid) == "verified":
            ok = store.update_status(aid, "retired", reason=CLEAN_REASON)
            (kb_retired if ok else kb_missing).append(aid)
        else:
            kb_missing.append(aid)

    manifest = {
        "run_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "tool": "tools/kb-e32-legacy-clean.py",
        "criterion": __doc__.split("清洗口径（")[1].split("动作：")[0].strip(),
        "backups": {"registry": bak_reg, "kb": bak_kb},
        "registry_status_before": before, "registry_status_after": dict(
            sqlite3.connect("file:%s?mode=ro" % REGISTRY, uri=True)
            .execute("SELECT status, COUNT(*) FROM candidates GROUP BY status")
            .fetchall()),
        "kb_status_before": kb_before, "kb_status_after": dict(
            sqlite3.connect("file:%s?mode=ro" % KB_DB, uri=True)
            .execute("SELECT status, COUNT(*) FROM atoms GROUP BY status").fetchall()),
        "demoted": demoted, "registry_skip_already_clean": reg_skip,
        "kb_retired": kb_retired, "kb_skip": kb_missing,
        "exempt_re_adjudication": exempt,
        "unparseable_cards": unparseable,
        "violations": violations,
    }
    mpath = os.path.join(MANIFEST_DIR, "cleanup-manifest.json")
    if os.path.exists(mpath):
        # 首跑正本 manifest 不覆盖（幂等重跑 demoted=[] 会抹掉真实清洗清单——
        # 2026-11-02 实测复跑即发生，已修）：后续运行写带时刻的旁证文件。
        mpath = os.path.join(MANIFEST_DIR,
                             "cleanup-manifest-%s.json" % time.strftime("%H%M%S"))
    with open(mpath, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=1)
    summary = {"mode": "apply", "demoted": len(demoted), "kb_retired": len(kb_retired),
               "kb_skip": len(kb_missing), "exempt": len(exempt),
               "manifest": os.path.relpath(mpath, WS)}
    print(json.dumps(summary, ensure_ascii=False))
    if kb_missing:
        log("kb 侧 %d 条未 retired（详见 manifest），人工复查" % len(kb_missing))
        return 1
    log("清洗完成：%d 条 registry verified→candidate、%d 条 kb verified→retired；欠账已登记 %s"
        % (len(demoted), len(kb_retired), os.path.relpath(mpath, WS)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
