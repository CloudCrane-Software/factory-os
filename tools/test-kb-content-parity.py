#!/usr/bin/env python3
"""test-kb-content-parity.py — 冲刺批2 第一步的幂等回归：content 口径统一。

背景（工单）：kb/import_registry.py:94 `_build_content()` 把 text+body 等多字段拼平，而
tools/kb-ingest.py 只写 text——同一 atom id 两个入口混跑会让库内 content 形态来回翻
（冲刺批1b 复核发现；计划/沙箱知识抽取流水线-运行手册 §10-T4a 禁项）。
修法：kb-ingest 复用 kb.import_registry 的 content 构造句柄（不复制算法）。

判据（逐字）：同一 atom id 先经 import_registry 再经 kb-ingest 各导入一次，
content 字节级不变。

检查项：
  A. 合成夹具（多形态原文：text-only / text+body / 嵌套 dict+list / 重复串 /
     preconditions+influence_hints+notes+summary / content 别名 / 纯中文英文混排）：
     A1 import_registry 先导 → kb-ingest 后导：全 id content 逐字节不变；
     A2 反向（kb-ingest 先导 → import_registry 后导）：同样不变（不许只对单序成立）；
     A3 篡改探针：把某原子 content 改回旧 text-only 口径，再跑一次 kb-ingest
        → 必须被修复成统一口径（混跑不留翻形态残留）；
     A4 非空洞探针：旧口径与统一口径在夹具上确有差异（否则本回归对缺陷无牙齿）。
  B. 真 registry + 真收割件（除非 --fast）：
     B1 import_registry 先导 → kb-ingest --status verified 后导：全 id content 逐字节不变；
     B2 每个 verified id 的 content == kb.import_registry 独立重算值（不借任一侧导入路径）；
     B3 原子总数不变、kb-ingest new=0、unresolved=0、再跑一次全 unchanged（幂等）。

用法：
  python3 tools/test-kb-content-parity.py           # A + B
  python3 tools/test-kb-content-parity.py --fast    # 只跑 A（不依赖真台账）
  python3 tools/test-kb-content-parity.py --keep    # 保留临时库（排查用）
退出码：0 全过；1 断言失败；2 前置/环境不满足。
临时库建在 $HOME 下自建目录（本机 /tmp 配额有限，勿用），默认完工即删。
零密钥、零网络：只读真 registry（mode=ro），不 scp/ssh。
"""
from __future__ import annotations

import argparse
import glob
import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile

WS = os.path.expanduser("~/workspace/agent黑灯工厂")
HOME = os.path.expanduser("~")
# 2026-10-31 DEB-5：临时目录按 PID 隔离（原为固定路径 ~/kbcontent-parity-scratch）。
# 实测（两次 all-gates --fast 并发跑同一台机）：19:21:15 那次与 19:30:42 那次共享同一个
# 临时目录，各自在起跑时 rmtree 对方的 case 目录 → 双方 parity B 用例同时红，且两红互补：
#   一方「原子集合变了（+0 / -12281)」（自己的库被对方删掉后重建，读到对方半成品库），
#   另一方「OperationalError: unable to open database file」（自己的库被对方删掉）。
# 单独跑该门（19:40-19:54 复现：run_import 479.7s + kb-ingest 360.3s，before_rows=29434
# / after_rows=29434 / added=0 / removed=0 / content_changed=0，全绿）证明被测件无缺陷——
# 是临时目录命名缺陷。断言一字未动，只改临时目录命名 + 清理口径。
_SCRATCH_BASE = "kbcontent-parity-scratch"
SCRATCH = os.path.join(HOME, "%s-%d" % (_SCRATCH_BASE, os.getpid()))
KB_INGEST = os.path.join(WS, "tools", "kb-ingest.py")


def purge_stale_scratch(base):
    """清掉本机已退出进程遗留的同前缀临时目录（PID 不在了才删，不碰在跑的那份）。"""
    for d in glob.glob(os.path.join(HOME, "%s-*" % base)):
        try:
            pid = int(os.path.basename(d).rsplit("-", 1)[1])
        except (ValueError, IndexError):
            continue
        if pid == os.getpid():
            continue
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass  # 权限/其它异常一律不删，留给人工

EXIT_OK, EXIT_FAIL, EXIT_ENV = 0, 1, 2


# ---------- 基础设施 ----------

def _load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_import_registry():
    if WS not in sys.path:
        sys.path.insert(0, WS)
    import kb.import_registry as ir  # noqa: E402
    return ir


def load_kb_ingest():
    return _load_module(KB_INGEST, "kbingest_under_test")


class Fail(Exception):
    pass


def check(cond, msg):
    if not cond:
        raise Fail(msg)


def snapshot(db_path):
    """全库 content 快照：{atom_id: content}（字节级比较用，直接读 sqlite 不绕 store）。"""
    con = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True)
    try:
        return dict(con.execute("SELECT id, content FROM atoms").fetchall())
    finally:
        con.close()


def run_ingest(registry, db_path, sources, statuses="verified", extra=()):
    """子进程跑 tools/kb-ingest.py（与 event-router 的调用方式同构）。返回 (rc, summary)。
    注意：--sources 是 nargs="*"，多个目录必须跟在同一个 flag 后面；分多次传会互相覆盖
    （argparse 语义），本函数统一合并成一次。"""
    cmd = [sys.executable, KB_INGEST, "--registry", registry, "--db", db_path,
           "--status", statuses, "--quiet", "--sources"] + list(sources) + list(extra)
    # 2026-10-31 DEB-5：门内自超时按实测重标（原 300s）。
    # 真 registry 全量 verified（17986 条）导入实测：空载 140.5/142.9/143.4s（p95 143.4s），
    # 8 路并行池重载 165.1/182.7/243.9s（p95 243.9s）。原 300s 预算对重载 p95 只有 23%
    # 余量，一旦并行池里并发再高一点就会 TimeoutExpired → 门红（假红，非被测件缺陷）。
    # 在役重载再校准（晚间 load 10~20 的外来 sweep 并发下）：整门单跑 1015s，其中本
    # 子进程占几百秒；600s 预算在重载下已贴边（池内 20:13 那次跑门整体被 1440s 帽掐死，
    # 子进程是否先超时因 stdout 缓冲未留证——故本次同时把本门 print 改 flush=True 留证）。
    # 新预算 1200s = 重载 p95×2 以上余量，且远小于门级 2400s 帽（内层先于外层死，
    # 报错能落到门日志里而不是被 SIGTERM 吞掉）。
    # 只改超时预算，不改任何断言（check() 的条件与文案一律未动）。
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=1200)
    summary = None
    for line in reversed(p.stdout.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                summary = json.loads(line)
            except ValueError:
                summary = None
            break
    return p.returncode, summary, p.stdout, p.stderr


# ---------- A. 合成夹具 ----------

FIXTURE_ATOMS = [
    # (id, 原文 dict) —— 覆盖 _build_content 的每个分支与两种 id 键
    ("fix-a-text-only", {"candidate_id": "fix-a-text-only", "kind": "claim",
                         "text": "只有 text 的短陈述"}),
    ("fix-b-text-body", {"candidate_id": "fix-b-text-body", "kind": "claim",
                         "text": "带 body 的陈述",
                         "body": {"claim_zh": "body 里的中文主张",
                                  "detail": {"nested": "嵌套 dict 字符串"}}}),
    ("fix-c-extras", {"candidate_id": "fix-c-extras", "kind": "procedure",
                      "text": "带多个附加字段",
                      "preconditions": ["前置一", "前置二"],
                      "influence_hints": ["提示 A"],
                      "notes": "备注文字",
                      "summary": {"one": "摘要一", "two": "摘要二"}}),
    ("fix-d-dup", {"candidate_id": "fix-d-dup", "kind": "concept",
                   "text": "重复串去重",
                   "body": {"claim_zh": "重复串去重", "other": "重复串去重"}}),
    ("fix-e-content-alias", {"candidate_id": "fix-e-content-alias", "kind": "evidence_record",
                             "content": "用 content 别名而非 text"}),
    ("fix-f-mixed", {"candidate_id": "fix-f-mixed", "kind": "failure_pattern",
                     "text": "Mixed 中英文 atom about SBFL 可疑度",
                     "body": {"claim_zh": "失败模式：单点实验不得写成普适规律"}}),
    ("fix-g-empty-text", {"candidate_id": "fix-g-empty-text", "kind": "claim",
                          "text": "   ", "body": {"claim_zh": "text 是空白时靠 body"}}),
    ("fix-h-no-text-key", {"candidate_id": "fix-h-no-text-key", "kind": "concept",
                           "body": {"claim_zh": "完全没有 text 键，只靠 body"}}),
]


def build_fixture(root):
    """造最小 registry.db + 收割件目录；返回 (registry_path, seed_root, ids_by_status)。"""
    seed = os.path.join(root, "seed")
    os.makedirs(os.path.join(seed, "sandbox"), exist_ok=True)
    with open(os.path.join(seed, "sandbox", "kb-atoms-fixture.jsonl"), "w",
              encoding="utf-8") as fh:
        for _cid, rec in FIXTURE_ATOMS:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    reg = os.path.join(root, "registry.db")
    con = sqlite3.connect(reg)
    con.execute("CREATE TABLE candidates (id TEXT PRIMARY KEY, source_corpus TEXT, "
                "status TEXT CHECK (status IN ('candidate','verified','rejected')), "
                "created_at TEXT, note TEXT)")
    rows = []
    for i, (cid, _rec) in enumerate(FIXTURE_ATOMS):
        # 一半 verified 一半 candidate：两种状态都走一遍同一口径
        st = "verified" if i % 2 == 0 else "candidate"
        rows.append((cid, "sandbox", st, "2026-10-28 12:00:0%d" % i, "fixture"))
    con.executemany("INSERT INTO candidates VALUES (?,?,?,?,?)", rows)
    con.commit()
    con.close()
    return reg, seed, {r[0]: r[2] for r in rows}


def expected_content(ir, raw):
    """独立重算统一口径（直接调 kb/import_registry 的函数，不借任一侧导入路径）。"""
    return ir._build_content(raw)


def fixture_case(ir, kbi, root, reverse=False):
    """一次夹具对账：reverse=False 先 import_registry 后 kb-ingest；True 则反过来。"""
    reg, seed, _st = build_fixture(root)
    db = os.path.join(root, "kb.db")
    raw_by_id = {r["candidate_id"]: r for _c, r in FIXTURE_ATOMS}

    if not reverse:
        ir.run_import(db, reg, seed, "", statuses=("candidate", "verified"))
        before = snapshot(db)
        rc, summ, out, err = run_ingest(reg, db, [os.path.join(seed, "sandbox")],
                                        statuses="all")
        check(rc == 0, "夹具 kb-ingest exit=%d（stderr: %s）" % (rc, err[-300:]))
    else:
        rc, summ, out, err = run_ingest(reg, db, [os.path.join(seed, "sandbox")],
                                        statuses="all")
        check(rc == 0, "夹具 kb-ingest exit=%d（stderr: %s）" % (rc, err[-300:]))
        before = snapshot(db)
        ir.run_import(db, reg, seed, "", statuses=("candidate", "verified"))

    after = snapshot(db)
    order = "kb-ingest→import_registry" if reverse else "import_registry→kb-ingest"
    check(set(after) == set(before),
          "%s：原子集合变了（+%s / -%s）" % (order, set(after) - set(before),
                                        set(before) - set(after)))
    bad = [aid for aid in before if before[aid] != after[aid]]
    check(not bad, "%s：%d 条 content 字节级变化，例 %r -> %r"
          % (order, len(bad), bad[:3], [(before[b], after[b]) for b in bad[:2]]))
    # 口径正确性：等于独立重算值
    wrong = [aid for aid in after if after[aid] != expected_content(ir, raw_by_id[aid])]
    check(not wrong, "%s：%d 条 content != 独立重算值，例 %s"
          % (order, len(wrong), wrong[:3]))
    # 旧口径确有差异（非空洞：否则本回归对已修缺陷没有牙齿）
    old_diff = [aid for aid in after
                if after[aid] != (raw_by_id[aid].get("text") or "").strip()]
    check(old_diff, "夹具上两口径完全一致，探针失效（回归无牙齿）")
    return {"order": order, "atoms": len(after), "content_changed": 0,
            "old_caliber_differs_on": len(old_diff)}


def fixture_tamper_case(ir, root):
    """篡改探针：把 content 改回旧 text-only 口径，kb-ingest 再跑必须修复（不留翻形态残留）。"""
    reg, seed, _st = build_fixture(root)
    db = os.path.join(root, "kb.db")
    ir.run_import(db, reg, seed, "", statuses=("candidate", "verified"))
    target = "fix-b-text-body"
    raw = {r["candidate_id"]: r for _c, r in FIXTURE_ATOMS}[target]
    old_caliber = (raw.get("text") or "").strip()
    unified = expected_content(ir, raw)
    check(old_caliber != unified, "夹具 %s 两口径无差异，探针失效" % target)
    from kb.store import KBStore  # noqa: E402
    st = KBStore(db)
    try:
        st.put_atom({"id": target, "content": old_caliber})
    finally:
        st.close()
    rc, summ, _out, err = run_ingest(reg, db, [os.path.join(seed, "sandbox")], statuses="all")
    check(rc == 0, "篡改后 kb-ingest exit=%d" % rc)
    got = snapshot(db)[target]
    check(got == unified,
          "kb-ingest 未把翻过去的 content 修回统一口径：got %r want %r" % (got, unified))
    return {"tampered_to": old_caliber, "repaired_to": unified}


# ---------- B. 真 registry 对账 ----------

def real_case(ir, kbi, root):
    # 输入冻结（2026-11-01，DEB-5 复核遗留①的根治）：用例对同一 registry 读两次验幂等，
    # 在役 event-router 会在两次读之间 admit（实测窗口内 +24 条 → updated=24 假红）。
    # 用 sqlite backup API 取一致快照，两次 run_ingest 都打快照——断言不动，只封输入。
    reg_live = os.path.join(WS, "kb-seed", "registry.db")
    reg = os.path.join(root, "registry-snapshot.db")
    import sqlite3 as _sq
    _src = _sq.connect("file:%s?mode=ro" % reg_live, uri=True)
    _dst = _sq.connect(reg)
    with _dst:
        _src.backup(_dst)
    _dst.close()
    _src.close()
    seed_root = os.path.join(WS, "kb-seed")
    poc_dir = os.path.join(WS, "计划", "研究组", "三阶段POC-知识资产-20261027")
    check(os.path.isfile(reg), "真 registry 不存在：%s" % reg_live)
    db = os.path.join(root, "kb-real.db")

    s1 = ir.run_import(db, reg, seed_root, poc_dir, statuses=("candidate", "verified"))
    before = snapshot(db)
    # 独立重算期望值（不借任一侧导入路径）
    originals = ir.load_originals(seed_root, poc_dir)
    want = {oid: norm[1] for oid, norm in originals.items()}

    rc, summ, out, err = run_ingest(reg, db, kbi.DEFAULT_SOURCES, statuses="verified")
    check(rc == 0, "真 registry kb-ingest exit=%d（stderr: %s）" % (rc, err[-300:]))
    after = snapshot(db)
    check(set(after) == set(before),
          "原子集合变了（+%d / -%d）" % (len(set(after) - set(before)),
                                      len(set(before) - set(after))))
    changed = [aid for aid in before if before[aid] != after[aid]]
    check(not changed, "%d 条 content 在两入口间字节级变化，例 %s -> %r"
          % (len(changed), changed[:3],
             [(before[c], after[c]) for c in changed[:2]]))
    wrong = [aid for aid in after if aid in want and after[aid] != want[aid]]
    check(not wrong, "%d 条 content != 独立重算值，例 %s" % (len(wrong), wrong[:3]))
    check(summ.get("new") == 0, "kb-ingest 报了新增 %r（应全为已存在）" % summ.get("new"))
    check(summ.get("unresolved") == 0,
          "真 registry 有 %r 条 verified 找不到原文（入库会漏）" % summ.get("unresolved"))
    # 旧口径 vs 统一口径：证明本回归对已修缺陷有牙齿
    verified_ids = [r[0] for r in ir.load_ledger(reg) if r[2] == "verified"]
    idx, _dup, _bad = kbi.build_index(kbi.source_files(kbi.DEFAULT_SOURCES))
    old_diff = [cid for cid in verified_ids
                if cid in idx and (idx[cid].get("text") or "").strip() != want.get(cid)]
    # 幂等：再跑一次应全 unchanged、content 不变
    rc2, summ2, _o2, e2 = run_ingest(reg, db, kbi.DEFAULT_SOURCES, statuses="verified")
    check(rc2 == 0, "第二次 kb-ingest exit=%d（stderr: %s）" % (rc2, e2[-300:]))
    after2 = snapshot(db)
    changed2 = [aid for aid in after if after[aid] != after2[aid]]
    check(not changed2, "第二次跑有 %d 条 content 变化（幂等破）" % len(changed2))
    check(summ2.get("updated") == 0 and summ2.get("new") == 0,
          "第二次跑 new=%r updated=%r（应 new=0 updated=0 unchanged=N）"
          % (summ2.get("new"), summ2.get("updated")))
    return {"atoms": len(after), "verified_in_ledger": len(verified_ids),
            "content_changed": 0, "old_caliber_differs_on": len(old_diff),
            "second_run": {"new": summ2.get("new"), "updated": summ2.get("updated"),
                           "unchanged": summ2.get("unchanged")},
            "first_run": {"new": summ.get("new"), "updated": summ.get("updated"),
                          "unchanged": summ.get("unchanged")}}


def main(argv=None):
    ap = argparse.ArgumentParser(description="content 口径统一幂等回归（冲刺批2 第一步）")
    ap.add_argument("--fast", action="store_true", help="只跑合成夹具，不跑真 registry")
    ap.add_argument("--keep", action="store_true", help="保留临时库目录（排查用）")
    a = ap.parse_args(argv)

    ir = load_import_registry()
    kbi = load_kb_ingest()
    check(kbi.resolve_build_content() is not None,
          "tools/kb-ingest.py 取不到 kb.import_registry 的 content 句柄——口径未统一")

    purge_stale_scratch(_SCRATCH_BASE)
    os.makedirs(SCRATCH, exist_ok=True)
    results, failures = {}, []
    try:
        cases = [("A1 夹具 import_registry→kb-ingest",
                  lambda d: fixture_case(ir, kbi, d, reverse=False)),
                 ("A2 夹具 kb-ingest→import_registry",
                  lambda d: fixture_case(ir, kbi, d, reverse=True)),
                 ("A3 夹具 篡改探针（翻回去必须被修回）",
                  lambda d: fixture_tamper_case(ir, d))]
        if not a.fast:
            cases.append(("B 真 registry 全量对账", lambda d: real_case(ir, kbi, d)))
        for i, (name, fn) in enumerate(cases):
            d = os.path.join(SCRATCH, "case-%d" % i)
            # 先清后建：上一次运行被硬杀（超时/Ctrl-C）时 finally 的 rmtree 没跑到，
            # 残留 case 目录里已带 candidates 表，build_fixture 再 CREATE TABLE 会
            # OperationalError——那是残留状态不是被测件缺陷（2026-10-29 统一门禁取证：
            # 首跑 120s 超时被杀即复现，清场后 4/4 全过）。断言一字未动。
            shutil.rmtree(d, ignore_errors=True)
            os.makedirs(d, exist_ok=True)
            try:
                results[name] = fn(d)
                print("  [PASS] %s -> %s" % (name, json.dumps(results[name],
                                                              ensure_ascii=False)),
                      flush=True)
            except Fail as e:
                failures.append(name)
                print("  [FAIL] %s -> %s" % (name, e), flush=True)
            except Exception as e:  # noqa: BLE001 - 门把任何异常记为失败
                failures.append(name)
                print("  [FAIL] %s -> %s: %s" % (name, type(e).__name__, e), flush=True)
    finally:
        if not a.keep:
            shutil.rmtree(SCRATCH, ignore_errors=True)

    if failures:
        print("PARITY FAILED: %d 项未过 -> %s" % (len(failures), failures), flush=True)
        return EXIT_FAIL
    print("PARITY PASSED: %d 项（content 两入口字节级一致、篡改可修复、旧口径确有差异）"
          % len(results), flush=True)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
