#!/usr/bin/env python3
"""kb-e67-qc-stock-clean.py — RT-E67 拦截机制②/④「quote_check 存量清洗」执行器
（一次性，幂等，可重跑；干跑默认，--apply 才写）。

背景（2026-11-02 确证发现）：quote_check 真值链的存量腿——「registry verified ∧ 入库
依据卡（note 依据:<file>）对该原子 verdict=uphold ∧ quote_check=false」原子在双库
verified 滞留（2026-11-02 实测 495 条；红队审计时点 491 条，live 漂移）。增量侧
（event-router admit 逐条消费 qc，2026-11-01 RT 修复）已堵住新流入（11-02 起新增 0），
存量无消费者；欠账台账:39 RT-E67 行按「门 test-kb-quote-integrity.py 入 all-gates」
标 ✅ 销项系张冠李戴（该门测引文逐字回查，非 qc 字段计数）。本脚本执行机制④存量清洗，
常驻对账门 tools/test-e67-qc-stock-recon.py（机制②）堵回归——同判据、独立实现。

清洗口径（与巡检门 test-e67-qc-stock-recon.py 同判据）：
  违规 = registry status=verified（或 kb/kb.db atoms status=verified）
         ∧ note 依据卡在 kb-seed/sandbox/verify/ 对该原子 verdict=uphold
         ∧ quote_check 非真（false/缺字段同罪，router 消费口径一致）。
分型处置（清洗不留冤案）：
  A 翻案改据（repoint）：该原子在裁决史上存在更晚的权威仲裁——最新（received_at 最大）
    裁决=uphold ∧ quote_check=true 且晚于现依据卡——verified 状态实际已站在新卡上，
    仅 note 依据滞留旧卡（registry.py admit 只在 candidate→verified 时写 note，无
    verified 改据通道）。处置：registry note 改写为「依据:<新卡绝对路径>」
    （与 registry.py admit 写入格式逐字同构＝demote+admit 组合的免降级等价式，
    免去 198 条无谓的 verified↔candidate 翻转抖动）；status 不动、kb 不动。
    逐原子新旧依据入 manifest 留痕。实测 198 条。
  B 降级待复核（demote）：不满足 A（最新裁决仍 qc 非真/为非 uphold 裁决/无后续裁决）。
    处置与 E32 存量清洗同构：registry verified→candidate（note 改写清洗记录，保留
    原依据可溯）＋ kb verified→retired（经 kb.store.update_status 追加 provenance
    status_change 事件）；他卡再以 uphold∧quote_check=true 独立复核后可走 R10/R11
    新码通道回场（registry.py admit candidate→verified、kb-ingest 幂等 upsert）。
    实测 297 条（全部「最新裁决仍 uphold∧qc=false」形态，与 E32 refute 族零交集）。
  不动：依据卡不可解析（verify 目录外/文件已失）与依据卡无该原子裁决行的 verified
    原子如实计数入 manifest，不判违规不清洗（provenance 另族问题，非本谓词）。

改前备份（sqlite backup API 一致性快照，已存在不覆盖）：
  kb-seed/registry.db.20261102-pre-E67qcclean.bak / kb/kb.db.20261102-pre-E67qcclean.bak
登记欠账：--apply 写
  计划/研究组/红队终局轮-20261101/RT-E67-存量清洗-20261102/cleanup-manifest.json
  （逐原子处置证据 + 前后状态计数 + 洗后复扫残留；正本不覆盖，重跑写带时刻旁证件）。

用法：
  python3 tools/kb-e67-qc-stock-clean.py            # 干跑：只算处置清单，零写
  python3 tools/kb-e67-qc-stock-clean.py --apply    # 真清洗（先备份→写→洗后复扫）
退出码：0 成功；1 --apply 后复扫仍有残留/有未预期失败；2 前置不满足。
零网络、零密钥。
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
                            "RT-E67-存量清洗-20261102")
BAK_SUFFIX = ".20261102-pre-E67qcclean.bak"
VERDICTS = ("uphold", "refute", "unverifiable")
DEMOTE_REASON = ("E67存量清洗2026-11-02: 入库依据卡uphold∧quote_check=false滞留verified"
                 "降级待复核（他卡uphold∧qc=true可翻案回场）")


def log(msg):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


def scan_judgments(verify_dir):
    """全扫验证卡 → judgments: atom_id -> [{ts, card, verdict, qc}]；坏卡如实计数。"""
    files = sorted(glob.glob(os.path.join(verify_dir, "*.json")))
    judgments, unparseable = {}, []
    for p in files:
        try:
            with open(p, encoding="utf-8") as fh:
                d = json.load(fh)
        except Exception as e:  # noqa: BLE001 - 坏卡如实登记（对账盲区）
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
                    {"ts": ts, "card": os.path.basename(p),
                     "verdict": v["verdict"], "qc": bool(v.get("quote_check"))})
    return judgments, unparseable, files


def classify(judgments, reg_rows, kb_verified):
    """reg_rows: {id: (status, note)} → (repoint, demote, unresolvable, entry_missing)。
    repoint: [{id, new_card, new_path, old_note, healed_ts}]；
    demote: [{id, basis_card, old_note}]。kb-only verified（registry 无行）如实计数。"""
    repoint, demote, unresolvable, entry_missing = [], [], [], []
    kb_no_registry = 0
    for aid, (status, note) in sorted(reg_rows.items()):
        if status != "verified":
            continue
        js = judgments.get(aid)
        if not js:
            entry_missing.append(aid)
            continue
        fn = os.path.basename(note[3:]) if note and note.startswith("依据:") else ""
        basis = next((j for j in js if j["card"] == fn), None) if fn else None
        if basis is None:
            unresolvable.append({"id": aid, "note": (note or "")[:120]})
            continue
        if basis["verdict"] == "uphold" and basis["qc"]:
            continue                                   # 干净原子
        # 违规成立（依据卡 uphold∧qc 非真）→ 分型
        latest = max(js, key=lambda x: x["ts"])
        if latest["verdict"] == "uphold" and latest["qc"] and latest["ts"] > basis["ts"]:
            repoint.append({"id": aid, "new_card": latest["card"],
                            "new_path": os.path.join(VERIFY_DIR, latest["card"]),
                            "old_note": note, "healed_ts": latest["ts"]})
        else:
            demote.append({"id": aid, "basis_card": fn, "old_note": note})
    for aid in kb_verified:
        if aid not in reg_rows:
            kb_no_registry += 1
    return repoint, demote, unresolvable, entry_missing, kb_no_registry


def predicate_residual():
    """洗后复扫（独立轻实现，只数仍违规数）：返回 (reg_residual, kb_residual)。"""
    judgments, unparseable, _files = scan_judgments(VERIFY_DIR)
    con = sqlite3.connect("file:%s?mode=ro" % REGISTRY, uri=True)
    try:
        rows = con.execute("SELECT id, status, note FROM candidates WHERE status='verified'").fetchall()
    finally:
        con.close()
    kcon = sqlite3.connect("file:%s?mode=ro" % KB_DB, uri=True)
    try:
        kbv = {r[0] for r in kcon.execute("SELECT id FROM atoms WHERE status='verified'")}
    finally:
        kcon.close()
    reg_res, kb_res = [], []
    for aid, _status, note in rows:
        fn = os.path.basename(note[3:]) if note and note.startswith("依据:") else ""
        js = judgments.get(aid) or []
        j = next((x for x in js if x["card"] == fn), None) if fn else None
        if j and j["verdict"] == "uphold" and not j["qc"]:
            reg_res.append(aid)
            if aid in kbv:
                kb_res.append(aid)
    return reg_res, kb_res, len(unparseable)


def backup_once(src, dst):
    """sqlite backup API 一致性快照；dst 已存在则不覆盖。"""
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
    ap = argparse.ArgumentParser(
        description="RT-E67 quote_check 存量清洗：翻案改据+降级待复核（干跑默认）")
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
        reg_before = dict(con.execute(
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

    repoint, demote, unresolvable, entry_missing, kb_no_registry = classify(
        judgments, reg_rows, set(kb_status))
    # 幂等：repoint 只处理 note 仍指向旧依据的；demote 只处理仍 verified 的（classify 已按
    # status='verified' 过滤，重跑自然为空）
    print(json.dumps({
        "mode": "apply" if a.apply else "dry-run",
        "verify_files": len(files), "unparseable": len(unparseable),
        "registry_status_before": reg_before, "kb_status_before": kb_before,
        "violations_total": len(repoint) + len(demote),
        "plan_repoint": len(repoint), "plan_demote": len(demote),
        "plan_demote_in_kb_verified": sum(1 for v in demote
                                          if kb_status.get(v["id"]) == "verified"),
        "basis_unresolvable": len(unresolvable),
        "basis_entry_missing": len(entry_missing),
        "kb_verified_no_registry_row": kb_no_registry,
    }, ensure_ascii=False))
    for v in repoint[:5]:
        old_fn = os.path.basename(v["old_note"][3:]) if (
            v["old_note"] and v["old_note"].startswith("依据:")) else "-"
        print("  repoint: %s | 原依据:%s → 新依据:%s" % (v["id"], old_fn, v["new_card"]))
    for v in demote[:5]:
        print("  demote: %s | 原依据:%s" % (v["id"], v["basis_card"]))
    if unparseable:
        log("注意：%d 份验证卡不可解析（对账盲区，已入 manifest；巡检门会红）" % len(unparseable))

    if not a.apply:
        log("干跑完成，零写。加 --apply 执行清洗。")
        return 0

    # ---- --apply：备份 → registry（repoint+demote 单事务）→ kb retired → 复扫 → manifest ----
    os.makedirs(MANIFEST_DIR, exist_ok=True)
    bak_reg = REGISTRY + BAK_SUFFIX
    bak_kb = KB_DB + BAK_SUFFIX
    backup_once(REGISTRY, bak_reg)
    backup_once(KB_DB, bak_kb)

    repointed, demoted, repoint_skip, demote_skip = [], [], [], []
    con = sqlite3.connect(REGISTRY, timeout=60)
    try:
        with con:
            for v in repoint:
                new_note = "依据:%s" % v["new_path"]
                cur = con.execute(
                    "UPDATE candidates SET note=? WHERE id=? AND status='verified' AND note=?",
                    (new_note, v["id"], v["old_note"]))
                (repointed if cur.rowcount else repoint_skip).append(
                    dict(v, new_note=new_note))
            for v in demote:
                cur = con.execute(
                    "UPDATE candidates SET status='candidate', note=? "
                    "WHERE id=? AND status='verified'",
                    ("E67清洗2026-11-02:%s; 原依据:%s; 清洗依据:依据卡uphold∧quote_check=false"
                     "（RT-E67机制②④，对账门 test-e67-qc-stock-recon.py 常驻）"
                     % (DEMOTE_REASON, v["basis_card"]),
                     v["id"]))
                (demoted if cur.rowcount else demote_skip).append(v["id"])
    finally:
        con.close()

    if WS not in sys.path:
        sys.path.insert(0, WS)
    from kb.store import KBStore  # noqa: E402
    store = KBStore(KB_DB)
    kb_retired, kb_skip = [], []
    for aid in demoted:
        if kb_status.get(aid) == "verified":
            ok = store.update_status(aid, "retired", reason=DEMOTE_REASON)
            (kb_retired if ok else kb_skip).append(aid)
        else:
            kb_skip.append(aid)

    reg_res, kb_res, unparse_res = predicate_residual()
    reg_after = dict(sqlite3.connect("file:%s?mode=ro" % REGISTRY, uri=True)
                     .execute("SELECT status, COUNT(*) FROM candidates GROUP BY status")
                     .fetchall())
    kb_after = dict(sqlite3.connect("file:%s?mode=ro" % KB_DB, uri=True)
                    .execute("SELECT status, COUNT(*) FROM atoms GROUP BY status")
                    .fetchall())
    manifest = {
        "run_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "tool": "tools/kb-e67-qc-stock-clean.py",
        "criterion": ("违规 = registry/kb verified ∧ note依据卡 verdict=uphold ∧ "
                      "quote_check 非真；A 翻案改据（最新裁决 uphold∧qc=true 且晚于现依据"
                      "→note 改指新卡）；B 降级（registry→candidate + kb→retired 待复核）"),
        "companion_gate": "tools/test-e67-qc-stock-recon.py（机制②，同判据独立实现）",
        "backups": {"registry": bak_reg, "kb": bak_kb},
        "registry_status_before": reg_before, "registry_status_after": reg_after,
        "kb_status_before": kb_before, "kb_status_after": kb_after,
        "repointed": repointed, "repoint_skip_state_changed": repoint_skip,
        "demoted": demoted, "demote_skip_state_changed": demote_skip,
        "kb_retired": kb_retired, "kb_skip": kb_skip,
        "basis_unresolvable": unresolvable,
        "basis_entry_missing": entry_missing,
        "kb_verified_no_registry_row": kb_no_registry,
        "unparseable_cards": unparseable,
        "rescan": {"registry_residual": reg_res, "kb_residual": kb_res,
                   "unparseable": unparse_res},
    }
    mpath = os.path.join(MANIFEST_DIR, "cleanup-manifest.json")
    if os.path.exists(mpath):
        mpath = os.path.join(MANIFEST_DIR,
                             "cleanup-manifest-%s.json" % time.strftime("%H%M%S"))
    with open(mpath, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=1)
    summary = {"mode": "apply", "repointed": len(repointed), "demoted": len(demoted),
               "kb_retired": len(kb_retired), "kb_skip": len(kb_skip),
               "rescan_registry_residual": len(reg_res),
               "rescan_kb_residual": len(kb_res),
               "manifest": os.path.relpath(mpath, WS)}
    print(json.dumps(summary, ensure_ascii=False))
    if reg_res or kb_res or unparse_res:
        log("洗后复扫仍有残留（registry=%d kb=%d unparseable=%d），如实报失败，人工复查"
            % (len(reg_res), len(kb_res), unparse_res))
        return 1
    if kb_skip:
        log("kb 侧 %d 条未 retired（详见 manifest），人工复查" % len(kb_skip))
        return 1
    log("清洗完成：%d 条翻案改据、%d 条 registry verified→candidate、%d 条 kb "
        "verified→retired；洗后复扫残留=0；manifest=%s"
        % (len(repointed), len(demoted), len(kb_retired), os.path.relpath(mpath, WS)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
