#!/usr/bin/env python3
"""test-e32-crosscard-divergence-consume.py — RT-E32 跨卡裁决时序消费腿机制自证
（2026-11-02 接入）。

工单判据（逃逸问题台账 RT-E32）：跨卡分歧不得只观测不消费——被更晚的独立验证卡判
refute/unverifiable 的原子，不得以 verified 滞留 registry+kb 双库。

缺陷形态（修复前实测）：tools/event-router.py 旧 26-29 行自述「分歧检测……纯观测，
不阻塞 admit（各卡仍按 uphold 率阈值与 registry 幂等规则独立裁决）」——更晚到的独立
验证卡把原子判 refute，事件路由器只登记一行 changelog，原子仍以 verified 滞留双库
（RT-E32 对账门 tools/test-e32-verified-uphold-recon.py 红 22 例；净化批清完存量 2.5h
即复现本类）。

本测自证的是**机制**（事件路由器的消费腿），不是对账门（对账门是独立实现的旁证面，
两者互不借实现路径——防「对账面自身失明」同源病，见对账门文件头同款声明）。

判据（与对账门逐字同判据）：
  不变量：registry status=verified 的原子，其 note 依据卡（received_at）必须晚于该原子
          在任何验证卡上的全部非 uphold（refute/unverifiable）裁决的 received_at。
  豁免：依据卡对本原子 verdict=uphold ∧ quote_check=true ∧ 依据卡 received_at 晚于该
        原子全部非 uphold 裁决（他卡独立复核翻案，合法产物，不得误降级）。

检查项（合成夹具，全链自证有牙）：
  T1 索引口径：全扫留档卡建「裁决史上最新非 uphold 裁决」账（多卡取最新 ts）。
  T2 admit 闸：更晚的卡已判 refute → 本卡（更早 ts）不得 admit 该原子；更晚的 uphold 卡
     可以 admit；只被更早的卡判 refute → 不阻塞 admit（时序最新者为准）。
  T3 豁免不误红：依据卡晚于全部非 uphold 裁决（翻案形态）→ 不降级、不得误判违规。
  T4 消费腿（增量）：本卡非 uphold 裁决到达 → 已 verified 且依据卡更早的原子双库降级
     （registry verified→candidate、kb verified→retired）。
  T5 存量回灌腿：修复前遗留的 verified 违规原子 → 启动回灌一并降级。
  T6 幂等：已降级原子再跑消费腿不动（不重复降级、不误伤已 candidate 的原子）。
  T7 活链（handle_verify_report 真调用）：更晚的 refute 卡到达 → 原子双库降级；
     反向时序（refute 卡更早）→ 原子保持 verified。

用法：
  python3 tools/test-e32-crosscard-divergence-consume.py
退出码：0 全过；1 断言失败；2 前置不满足。零网络、零密钥；只碰 $HOME 下自建临时目录
（/tmp 配额有限），完工即删；不写生产库（生产库路径在夹具里被换掉）。
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sqlite3
import sys
import time

WS = os.path.expanduser("~/workspace/agent黑灯工厂")
ROUTER = os.path.join(WS, "tools", "event-router.py")
REGISTRY_CLI_SRC = os.path.join(WS, "kb-seed", "registry.py")
SCRATCH = os.path.join(os.path.expanduser("~"), "e32xcard-selftest-%d" % os.getpid())

EXIT_OK, EXIT_FAIL, EXIT_ENV = 0, 1, 2


class Fail(Exception):
    pass


def check(cond, msg):
    if not cond:
        raise Fail(msg)


def load_router():
    """加载事件路由器模块（只 import，不跑 main()）。"""
    spec = importlib.util.spec_from_file_location("router_xcard", ROUTER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def build_fixture(root):
    """搭夹具：tmp/kb-seed/registry.{py,db} + tmp/kb/kb.db + tmp/verify/*.json。"""
    os.makedirs(os.path.join(root, "kb-seed"), exist_ok=True)
    os.makedirs(os.path.join(root, "kb"), exist_ok=True)
    os.makedirs(os.path.join(root, "verify"), exist_ok=True)
    os.makedirs(os.path.join(root, "tools"), exist_ok=True)
    os.makedirs(os.path.join(root, "计划"), exist_ok=True)
    shutil.copyfile(REGISTRY_CLI_SRC, os.path.join(root, "kb-seed", "registry.py"))
    # 路由器按 WS+"/kb/store.py" 直载 KBStore（importlib），夹具必须自带一份 store.py
    shutil.copyfile(os.path.join(WS, "kb", "store.py"), os.path.join(root, "kb", "store.py"))
    # registry 库（与生产同 schema）：A 已 verified 且依据卡更早（铁证形态）；B 已 verified
    # 且依据卡更晚（翻案形态，豁免）；C 已 verified 但依据卡就是最新（干净形态）
    con = sqlite3.connect(os.path.join(root, "kb-seed", "registry.db"))
    with con:
        con.execute("CREATE TABLE candidates(id TEXT PRIMARY KEY, source_corpus TEXT, "
                    "status TEXT NOT NULL CHECK(status IN ('candidate','verified','rejected')), "
                    "created_at TEXT, note TEXT)")
        con.executemany("INSERT INTO candidates VALUES(?,?,?,?,?)", [
            ("A", "corpus", "verified", "2026-11-02 09:00:00",
             "依据:%s" % os.path.join(root, "verify", "cA_up.json")),
            ("B", "corpus", "verified", "2026-11-02 09:00:00",
             "依据:%s" % os.path.join(root, "verify", "cB_up2.json")),
            ("C", "corpus", "verified", "2026-11-02 09:00:00",
             "依据:%s" % os.path.join(root, "verify", "cC_up.json")),
        ])
    con.close()
    return root


def card(root, name, ts, entries, card_id=None):
    p = os.path.join(root, "verify", name)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump({"task_id": card_id or name[:-5], "received_at": ts,
                   "payload": {"verify": True, "card_id": card_id or name[:-5],
                               "verdicts": entries}}, fh, ensure_ascii=False)
    return p


def kb_seed(root, ids):
    """kb 库：把给定原子置 verified（KBStore 自建表）。"""
    sys.path.insert(0, WS)
    from kb.store import KBStore
    store = KBStore(os.path.join(root, "kb", "kb.db"))
    for aid in ids:
        store.put_atom({"id": aid, "content": "x", "source_corpus": "corpus",
                        "paper": "", "status": "verified", "attrs": {}})
    return store


def kb_status(root, aid):
    con = sqlite3.connect("file:%s?mode=ro" % os.path.join(root, "kb", "kb.db"), uri=True)
    try:
        row = con.execute("SELECT status FROM atoms WHERE id=?", (aid,)).fetchone()
    finally:
        con.close()
    return row[0] if row else None


def reg_status(root, aid):
    con = sqlite3.connect("file:%s?mode=ro" % os.path.join(root, "kb-seed", "registry.db"),
                          uri=True)
    try:
        row = con.execute("SELECT status FROM candidates WHERE id=?", (aid,)).fetchone()
    finally:
        con.close()
    return row[0] if row else None


def bind(mod, root):
    """把模块的库/目录路径绑到夹具（生产库零触碰）。"""
    mod.WS = root
    mod.REGISTRY = os.path.join(root, "kb-seed", "registry.db")
    mod.REGISTRY_CLI = os.path.join(root, "kb-seed", "registry.py")
    mod.KB_DB = os.path.join(root, "kb", "kb.db")
    mod.VERIFY_DIR = os.path.join(root, "verify")
    mod.CHANGELOG = os.path.join(root, "计划", "变更日志.md")
    mod.KB_INGEST = os.path.join(root, "tools", "kb-ingest.py")
    mod._KBSTORE = None
    mod._CROSSCARD_INDEX.clear()


def selftest():
    shutil.rmtree(SCRATCH, ignore_errors=True)
    root = build_fixture(SCRATCH)
    mod = load_router()
    bind(mod, root)
    # 夹具卡（裁决史）：A：uphold(1000) → refute(2000)  【铁证：依据卡更早】
    #                     B：refute(500) → uphold(1000) → uphold(3000) 【翻案：依据卡最新】
    #                     C：uphold(4000) 唯一裁决                    【干净】
    card(root, "cA_up.json", 1000.0, [{"atom_id": "A", "verdict": "uphold", "quote_check": True}])
    card(root, "cA_ref.json", 2000.0, [{"atom_id": "A", "verdict": "refute", "quote_check": True}])
    card(root, "cB_oldref.json", 500.0, [{"atom_id": "B", "verdict": "refute", "quote_check": True}])
    card(root, "cB_up.json", 1000.0, [{"atom_id": "B", "verdict": "uphold", "quote_check": True}])
    card(root, "cB_up2.json", 3000.0, [{"atom_id": "B", "verdict": "uphold", "quote_check": True}])
    card(root, "cC_up.json", 4000.0, [{"atom_id": "C", "verdict": "uphold", "quote_check": True}])
    kb_seed(root, ["A", "B", "C"])

    # T1 索引口径：多卡取最新 ts
    idx, n_bad = mod.crosscard_index(os.path.join(root, "verify"))
    check(n_bad == 0, "坏卡计数应 0（实 %d）" % n_bad)
    check(idx.get("A", (None,))[0] == 2000.0 and idx["A"][2] == "refute",
          "A 的最新非 uphold 裁决应 ts=2000/refute（实 %r）" % (idx.get("A"),))
    check(idx.get("B", (None,))[0] == 500.0,
          "B 的最新非 uphold 裁决应 ts=500（实 %r）" % (idx.get("B"),))
    check("C" not in idx, "C 无非 uphold 裁决，不应入索引（实 %r）" % (idx.get("C"),))
    mod._CROSSCARD_INDEX.update(idx)

    # T2 admit 闸：更晚的卡已判 refute → 更早的卡不得 admit
    check(not mod.crosscard_admit_ok("A", 1000.0),
          "A：更晚卡(2000)已判 refute，本卡(1000)不得 admit")
    check(mod.crosscard_admit_ok("A", 3000.0),
          "A：更晚的 uphold 卡(3000)可 admit（裁决时序最新者为准）")
    check(mod.crosscard_admit_ok("C", 1000.0), "C：无 refute 裁决，不应被 admit 闸拦")
    check(mod.crosscard_admit_ok("B", 1000.0),
          "B：refute(500)更早，本卡(1000)可 admit（时序最新者为准）")

    # T3 豁免不误红：B 的依据卡(3000)晚于全部非 uphold 裁决(500) → 豁免
    _st, note_b = mod.registry_row_ro("B")
    check(mod.crosscard_exempt("B", note_b), "B 应豁免（依据卡最新且 uphold∧qc）")
    _st, note_a = mod.registry_row_ro("A")
    check(not mod.crosscard_exempt("A", note_a), "A 不应豁免（依据卡早于 refute 裁决）")
    _st, note_c = mod.registry_row_ro("C")
    check(mod.crosscard_exempt("C", note_c), "C 应豁免（无 refute 裁决）")

    # T5 存量回灌腿：修复前遗留的 A（verified + 依据卡更早）→ 双库降级；B/C 不动
    detail = mod.consume_crosscard_divergence()
    a_detail = [d for d in detail if d[0] == "A"]
    check(len(a_detail) == 2, "A 应双库各一条降级明细（实 %r）" % (a_detail,))
    check(reg_status(root, "A") == "candidate",
          "A registry 应降级为 candidate（实 %r）" % reg_status(root, "A"))
    check(kb_status(root, "A") == "retired",
          "A kb 应降级为 retired（实 %r）" % kb_status(root, "A"))
    check(reg_status(root, "B") == "verified" and kb_status(root, "B") == "verified",
          "B 豁免形态不得被降级")
    check(reg_status(root, "C") == "verified" and kb_status(root, "C") == "verified",
          "C 干净形态不得被降级")

    # T6 幂等：已降级原子再跑不动
    detail2 = mod.consume_crosscard_divergence()
    check(not [d for d in detail2 if d[0] == "A"],
          "A 已降级，再跑消费腿不应重复降级（实 %r）" % (detail2,))
    check(reg_status(root, "A") == "candidate" and kb_status(root, "A") == "retired",
          "A 幂等：降级后状态不得被改动")

    # T4 消费腿（增量）：新卡判 refute 打到已 verified 的 C → 双库降级
    card(root, "cC_ref.json", 5000.0, [{"atom_id": "C", "verdict": "refute", "quote_check": True}])
    idx2, _ = mod.crosscard_index(os.path.join(root, "verify"))
    mod._CROSSCARD_INDEX.update(idx2)
    d3 = mod.consume_crosscard_divergence(["C"])
    check(len(d3) == 2, "C 消费腿应双库各一条（实 %r）" % (d3,))
    check(reg_status(root, "C") == "candidate" and kb_status(root, "C") == "retired",
          "C 应被消费腿双库降级（reg=%r kb=%r）" % (reg_status(root, "C"), kb_status(root, "C")))

    # T7 活链：真调 handle_verify_report——更晚的 refute 卡到达 → 双库降级；
    #            反向时序（refute 卡更早）→ 保持 verified
    # D：uphold(6000) 已 admit（干净），随后 refute(7000) 卡到达 → 必须降级
    con = sqlite3.connect(os.path.join(root, "kb-seed", "registry.db"))
    with con:
        con.execute("INSERT INTO candidates VALUES(?,?,?,?,?)",
                    ("D", "corpus", "verified", "2026-11-02 09:00:00",
                     "依据:%s" % os.path.join(root, "verify", "cD_up.json")))
    con.close()
    store = kb_seed(root, ["D"])
    card(root, "cD_up.json", 6000.0, [{"atom_id": "D", "verdict": "uphold", "quote_check": True}])
    idx3, _ = mod.crosscard_index(os.path.join(root, "verify"))
    mod._CROSSCARD_INDEX.update(idx3)
    rep_ref = {"task_id": "kb-verify-t-1r1", "received_at": 7000.0,
               "payload": {"verify": True, "card_id": "kb-verify-t-1r1",
                           "verdicts": [{"atom_id": "D", "verdict": "refute",
                                         "quote_check": True}]}}
    mod.handle_verify_report({}, "cD_ref_live.json", "/dev/null", rep_ref)
    check(reg_status(root, "D") == "candidate",
          "D：更晚 refute 卡到达后 registry 应降级（实 %r）" % reg_status(root, "D"))
    check(kb_status(root, "D") == "retired",
          "D：更晚 refute 卡到达后 kb 应降级（实 %r）" % kb_status(root, "D"))
    # E：uphold(9000) admit，随后更早的 refute(8000) 卡到达 → 不得降级（时序最新者为准）
    con = sqlite3.connect(os.path.join(root, "kb-seed", "registry.db"))
    with con:
        con.execute("INSERT INTO candidates VALUES(?,?,?,?,?)",
                    ("E", "corpus", "verified", "2026-11-02 09:00:00",
                     "依据:%s" % os.path.join(root, "verify", "cE_up.json")))
    con.close()
    kb_seed(root, ["E"])
    card(root, "cE_up.json", 9000.0, [{"atom_id": "E", "verdict": "uphold", "quote_check": True}])
    idx4, _ = mod.crosscard_index(os.path.join(root, "verify"))
    mod._CROSSCARD_INDEX.update(idx4)
    rep_stale = {"task_id": "kb-verify-t-1r2", "received_at": 8000.0,
                 "payload": {"verify": True, "card_id": "kb-verify-t-1r2",
                             "verdicts": [{"atom_id": "E", "verdict": "refute",
                                           "quote_check": True}]}}
    mod.handle_verify_report({}, "cE_ref_stale.json", "/dev/null", rep_stale)
    check(reg_status(root, "E") == "verified",
          "E：更早的 refute 卡不得降级更晚 uphold 卡的裁决（实 %r）" % reg_status(root, "E"))
    check(kb_status(root, "E") == "verified",
          "E：kb 同理不得降级（实 %r）" % kb_status(root, "E"))

    shutil.rmtree(SCRATCH, ignore_errors=True)
    print("E32-XCARD-CONSUME PASSED: 7/7 断言全过"
          "（索引口径/admit闸/豁免不误红/消费腿/存量回灌/幂等/活链）")
    return EXIT_OK


def main(argv=None):
    for f in (ROUTER, REGISTRY_CLI_SRC):
        if not os.path.exists(f):
            print("前置缺失: %s" % f)
            return EXIT_ENV
    t0 = time.time()
    try:
        rc = selftest()
    except Fail as e:
        print("E32-XCARD-CONSUME FAILED: %s" % e)
        shutil.rmtree(SCRATCH, ignore_errors=True)
        return EXIT_FAIL
    except Exception as e:  # noqa: BLE001 - 夹具异常如实报（不吞）
        print("E32-XCARD-CONSUME ERROR: %s: %s" % (type(e).__name__, e))
        shutil.rmtree(SCRATCH, ignore_errors=True)
        return EXIT_FAIL
    print("（耗时 %.1fs）" % (time.time() - t0))
    return rc


if __name__ == "__main__":
    sys.exit(main())
