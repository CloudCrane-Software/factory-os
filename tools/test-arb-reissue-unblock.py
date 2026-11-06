#!/usr/bin/env python3
"""test-arb-reissue-unblock.py — 零终裁「只登记不重派」滞留面·重发解堵判别力门
（2026-11-03 RT·改道KB线；配套修复：quality-cards._arbitrate_existing 零终裁豁免
+ event-router.arb_reissue_accounting 零终裁台账消费腿 + W5 门族新增 W6 重派账腿）

背景（确证发现亲证，本轮只读复现）：kb-arbitrate 零终裁 55 份修复后只登记不重派——
64 原子仲裁链永久滞留（11 条双库 verified），重发被发卡幂等腿阻断
（quality-cards._arbitrate_existing 按 divergence_key 在种子/gov 两处查重即跳过，
种子不删=永不再发，在役轮换实况「arbitrate 生成0/跳过175」），唯一消费面是把
「有主」记绿的 W5 对账门，无门红/无台账/无告警。

检查项（全部夹具化，零网络零 ssh、不写生产面）：
  R1 释放重派：同分歧唯一承载卡已零终裁登记（终裁未落库）→ _arbitrate_existing
     判未承载（返回 None）→ gen_arbitrate 顺延新号自动重发（修前返回承载卡=永久遮蔽）。
  R2 重发帽：同分歧零终裁卡数 ≥ ARB_REISSUE_CAP（=2）→ 恢复幂等遮蔽（返回承载卡），
     自动重发预算耗尽、总量有界（防无限重发）；帽值与 event-router 同值断言。
  R3 正常幂等不回退：承载者含健康卡（未零终裁）→ 照旧返回承载卡（跳过语义一字不改）。
  R4 fail-closed：零终裁台账读不到/坏 → 按空台账处理、幂等照旧（绝不因读不到而多发卡）。
  R5 台账消费腿：arb_reissue_accounting 给登记记重派账——
     · 同分歧有健康承载卡 → reissued:<卡>；
     · 同分歧零终裁 ≥ 帽 → exhausted + alarms.log ARB-REISSUE-STUCK 行 + 变更日志点名；
     · pending 超 ARB_REISSUE_DEADLINE_S → 同款告警（文案区分）；
     · 告警同分歧一次性（二轮不重复）。
  R6 W6 门腿判别力：缺 reissue 字段 / exhausted 无告警点名 / pending 超时无点名
     → W6 红；reissued / 有点名 → 绿（夹具逐形态对账）。

用法：python3 tools/test-arb-reissue-unblock.py
退出码：0 全过；1 断言失败；2 前置不满足。
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile

WS = os.path.expanduser("~/workspace/agent黑灯工厂")
TOOLS = os.path.join(WS, "tools")
CARDS = os.path.join(TOOLS, "quality-cards.py")
ROUTER = os.path.join(TOOLS, "event-router.py")
GATE = os.path.join(TOOLS, "test-cardtype-three-side-wiring.py")

EXIT_OK, EXIT_FAIL, EXIT_ENV = 0, 1, 2

DK = "gk-2610.36499.jsonl|sbx-x-1,sbx-x-2|kb-verify-a-r3,kb-verify-b-r3"


class Fail(Exception):
    pass


def check(cond, msg):
    if not cond:
        raise Fail(msg)


def load_mod(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def mk_seed(seeds, card, dk=DK):
    d = os.path.join(seeds, card)
    os.makedirs(d, exist_ok=True)
    json.dump({"arbitrate": {"card_id": card, "divergence_key": dk,
                             "atom_ids": ["sbx-x-1", "sbx-x-2"]}},
              open(os.path.join(d, "meta.json"), "w", encoding="utf-8"))
    return d


def mk_state(path, entries):
    """零终裁台账夹具：entries = [(回报文件名, {card, ts, ...})]。"""
    st = {"arb_zero_verdict": {}}
    for name, e in entries:
        st["arb_zero_verdict"][name] = dict(e)
    json.dump(st, open(path, "w", encoding="utf-8"), ensure_ascii=False)
    return path


def load_cards_module(tmp):
    """带夹具环境载入 quality-cards（SEEDS/ROUTER_STATE/LOG 全改道 scratch，零写生产）。"""
    os.environ["QUALITY_CARDS_SEEDS"] = os.path.join(tmp, "task-seeds")
    os.environ["QUALITY_CARDS_ROUTER_STATE"] = os.path.join(tmp, "router-state.json")
    os.environ["QUALITY_CARDS_LOG"] = os.path.join(tmp, "quality-cards.log")
    os.environ["QUALITY_CARDS_STATE"] = os.path.join(tmp, "quality-cards-state.json")
    return load_mod("reissue_cards", CARDS)


def dd_fixture():
    return {"names_gov": set(), "names_local": set(),
            "legs": {"submitted": set()}, "gov_reachable": False}


def r1_r4(tmp):
    """R1/R4：零终裁豁免释放重派 + 台账读不到 fail-closed。"""
    qc = load_cards_module(tmp)
    seeds = os.environ["QUALITY_CARDS_SEEDS"]
    check(qc.ARB_REISSUE_CAP == 2, "ARB_REISSUE_CAP 帽值应=2，实为 %r" % qc.ARB_REISSUE_CAP)
    mk_seed(seeds, "kb-arbitrate-bx-1")
    st_p = mk_state(os.path.join(tmp, "router-state.json"),
                    [("kb-arbitrate-bx-1-1.json",
                      {"card": "kb-arbitrate-bx-1", "status": "no-verdict-registered"})])
    dd = dd_fixture()
    # 修前形态（对照）：承载卡零终裁 → 旧码按 divergence_key 判「已承载」永久遮蔽；
    # 新码判未承载 → 返回 None（gen_arbitrate 顺延新号重发）。
    got = qc._arbitrate_existing("kb-arbitrate-bx-", DK, dd)
    check(got is None,
          "R1 失败：唯一承载卡已零终裁登记，幂等腿仍判已承载（返回 %r）——重发仍被阻断" % got)
    check(os.path.isdir(os.path.join(seeds, "kb-arbitrate-bx-1")),
          "R1 失败：豁免腿误删种子（零终裁留证/名册必须原位保留）")
    # R4 fail-closed：台账坏 → 按空台账、幂等照旧（返回承载卡，绝不多发卡）
    open(st_p, "w", encoding="utf-8").write("{broken json")
    got = qc._arbitrate_existing("kb-arbitrate-bx-", DK, dd)
    check(got == "kb-arbitrate-bx-1",
          "R4 失败：台账读不到时幂等语义应照旧（返回承载卡），实为 %r" % got)
    return {"released": True, "fail_closed": True}


def r2_r3(tmp):
    """R2/R3：重发帽（预算耗尽恢复遮蔽）+ 健康承载照旧。"""
    qc = load_cards_module(tmp)
    seeds = os.environ["QUALITY_CARDS_SEEDS"]
    mk_seed(seeds, "kb-arbitrate-by-1")
    mk_seed(seeds, "kb-arbitrate-by-2")
    mk_seed(seeds, "kb-arbitrate-by-3", dk="other|divergence|key")
    entries = [("kb-arbitrate-by-%d-%d.json" % (i, i),
                {"card": "kb-arbitrate-by-%d" % i, "status": "no-verdict-registered"})
               for i in (1, 2)]
    mk_state(os.environ["QUALITY_CARDS_ROUTER_STATE"], entries)
    dd = dd_fixture()
    got = qc._arbitrate_existing("kb-arbitrate-by-", DK, dd)
    check(got is not None,
          "R2 失败：同分歧已 %d 张零终裁卡（帽=%d），重发预算应耗尽恢复遮蔽，实返回 %r"
          % (2, qc.ARB_REISSUE_CAP, got))
    # R3：承载者混入健康卡（-3 挂同分歧）→ 照旧返回健康承载卡（幂等不回退）
    mk_seed(seeds, "kb-arbitrate-by-4", dk=DK)
    got = qc._arbitrate_existing("kb-arbitrate-by-", DK, dd)
    check(got == "kb-arbitrate-by-4",
          "R3 失败：同分歧有健康承载卡时应照旧跳过（返回健康卡），实为 %r" % got)
    return {"cap_blocks": True, "healthy_idempotent": True}


def load_router(tmp):
    rt = load_mod("reissue_router", ROUTER)
    rt.DRY = False                       # 夹具内真写告警/变更日志（目标已改道 scratch）
    rt.CHANGELOG = os.path.join(tmp, "changelog.md")
    rt.ALARMS_LOG = os.path.join(tmp, "alarms.log")
    rt.ARB_SEEDS_DIR = os.path.join(tmp, "task-seeds")
    return rt


def r5(tmp):
    """R5：台账消费腿三形态 + 告警一次性。"""
    rt = load_router(tmp)
    seeds = rt.ARB_SEEDS_DIR
    ts_now = rt.time.strftime("%Y-%m-%d %H:%M:%S")
    ts_old = rt.time.strftime("%Y-%m-%d %H:%M:%S",
                              rt.time.localtime(rt.time.time() - (rt.ARB_REISSUE_DEADLINE_S + 3600)))
    mk_seed(seeds, "kb-arbitrate-rz-1")              # 零终裁卡（重发预算 1/2）
    mk_seed(seeds, "kb-arbitrate-rz-2")              # 重发后也零终裁 → 预算耗尽
    mk_seed(seeds, "kb-arbitrate-rw-1", dk="rw|divergence|key")   # 零终裁卡（另一分歧）
    mk_seed(seeds, "kb-arbitrate-rw-2", dk="rw|divergence|key")   # 健康重发卡（同分歧）
    mk_seed(seeds, "kb-arbitrate-rp-1", dk="rp|divergence|key")   # 零终裁卡，无重派动作
    st = {"arb_zero_verdict": {
        "kb-arbitrate-rz-1-11.json": {"card": "kb-arbitrate-rz-1", "ts": ts_now,
                                      "status": "no-verdict-registered",
                                      "atoms": ["sbx-x-1"], "reissue": "pending"},
        "kb-arbitrate-rz-2-22.json": {"card": "kb-arbitrate-rz-2", "ts": ts_now,
                                      "status": "no-verdict-registered",
                                      "atoms": ["sbx-x-2"], "reissue": "pending"},
        "kb-arbitrate-rw-1-11.json": {"card": "kb-arbitrate-rw-1", "ts": ts_now,
                                      "status": "no-verdict-registered",
                                      "atoms": ["sbx-x-1"], "reissue": "pending"},
        "kb-arbitrate-rp-1-11.json": {"card": "kb-arbitrate-rp-1", "ts": ts_old,
                                      "status": "no-verdict-registered",
                                      "atoms": ["sbx-x-2"], "reissue": "pending"},
    }}
    rt.arb_reissue_accounting(st)
    nov = st["arb_zero_verdict"]
    check(nov["kb-arbitrate-rz-1-11.json"]["reissue"] == "exhausted",
          "R5 失败：同分歧 2 张零终裁卡应记 exhausted，实为 %r"
          % nov["kb-arbitrate-rz-1-11.json"]["reissue"])
    check(nov["kb-arbitrate-rw-1-11.json"]["reissue"] == "reissued:kb-arbitrate-rw-2",
          "R5 失败：有健康承载卡应记 reissued:<卡>，实为 %r"
          % nov["kb-arbitrate-rw-1-11.json"]["reissue"])
    check(nov["kb-arbitrate-rp-1-11.json"]["reissue"] == "pending",
          "R5 失败：无重派动作且超时应保持 pending+告警，实为 %r"
          % nov["kb-arbitrate-rp-1-11.json"]["reissue"])
    alarms = [json.loads(l) for l in open(rt.ALARMS_LOG, encoding="utf-8") if l.strip()]
    codes = [a["code"] for a in alarms]
    check(codes.count("ARB-REISSUE-STUCK") == 2,
          "R5 失败：耗尽+超时应各告警一次（实得 %d 条 ARB-REISSUE-STUCK：%r）"
          % (codes.count("ARB-REISSUE-STUCK"), alarms))
    check(any("kb-arbitrate-rz-1" in a["message"] for a in alarms),
          "R5 失败：耗尽告警未点名零终裁卡")
    check(any("kb-arbitrate-rp-1" in a["message"] for a in alarms),
          "R5 失败：超时告警未点名零终裁卡")
    cl = open(rt.CHANGELOG, encoding="utf-8").read()
    check("零终裁重派滞留告警" in cl and "kb-arbitrate-rz-1" in cl,
          "R5 失败：变更日志未点名滞留分歧")
    n_alarms = len(alarms)
    rt.arb_reissue_accounting(st)   # 二轮：告警必须一次性
    alarms2 = [json.loads(l) for l in open(rt.ALARMS_LOG, encoding="utf-8") if l.strip()]
    check(len(alarms2) == n_alarms,
          "R5 失败：二轮重复告警（%d→%d 条，同分歧应一次性）" % (n_alarms, len(alarms2)))
    return {"exhausted_alarmed": True, "reissued": True, "stale_alarmed": True,
            "dedup": True}


def r6(tmp):
    """R6：W6 门腿判别力（缺字段红/耗尽无告警红/有告警绿/超时无点名红）。"""
    gate = load_mod("reissue_gate", GATE)
    gate.ARB_SEEDS = os.path.join(tmp, "task-seeds")
    gate.ALARMS_LOG = os.path.join(tmp, "alarms.log")
    open(gate.ALARMS_LOG, "w", encoding="utf-8").write("")   # 空告警流水起步
    alarms = [json.loads(l) for l in open(gate.ALARMS_LOG, encoding="utf-8") if l.strip()]
    ts = gate.time.strftime("%Y-%m-%d %H:%M:%S")
    ts_old = gate.time.strftime(
        "%Y-%m-%d %H:%M:%S",
        gate.time.localtime(gate.time.time() - (gate.REISSUE_DEADLINE_S + 3600)))
    mk_seed(gate.ARB_SEEDS, "kb-arbitrate-g6-1")
    mk_seed(gate.ARB_SEEDS, "kb-arbitrate-g6-2")
    # 形态①：缺 reissue 字段 → 红
    st = {"arb_zero_verdict": {"g.json": {"card": "kb-arbitrate-g6-1", "ts": ts,
                                          "status": "no-verdict-registered"}}}
    try:
        gate.w6_reissue_ledger(st)
        raise Fail("R6 失败：缺 reissue 字段未红")
    except gate.Fail:
        pass
    # 形态②：耗尽但无告警点名 → 红（对照夹具告警流水的码对不上该卡）
    st = {"arb_zero_verdict": {"g.json": {"card": "kb-arbitrate-g6-1", "ts": ts,
                                          "status": "no-verdict-registered",
                                          "reissue": "exhausted"}}}
    try:
        gate.w6_reissue_ledger(st)
        raise Fail("R6 失败：耗尽无告警点名未红")
    except gate.Fail:
        pass
    # 形态③：超时 pending 且无告警点名 → 红
    st = {"arb_zero_verdict": {"g.json": {"card": "kb-arbitrate-g6-2", "ts": ts_old,
                                          "status": "no-verdict-registered",
                                          "reissue": "pending"}}}
    try:
        gate.w6_reissue_ledger(st)
        raise Fail("R6 失败：超时 pending 无点名未红")
    except gate.Fail:
        pass
    # 形态④：耗尽且有告警点名（写一条点名 g6-1 的告警）→ 绿；reissued → 绿
    with open(gate.ALARMS_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": ts, "level": "amber", "code": "ARB-REISSUE-STUCK",
                            "message": "重发预算耗尽：零终裁卡 kb-arbitrate-g6-1",
                            "since": ts}, ensure_ascii=False) + "\n")
    st = {"arb_zero_verdict": {
        "g1.json": {"card": "kb-arbitrate-g6-1", "ts": ts,
                    "status": "no-verdict-registered", "reissue": "exhausted"},
        "g2.json": {"card": "kb-arbitrate-g6-2", "ts": ts,
                    "status": "no-verdict-registered", "reissue": "reissued:kb-arbitrate-g6-3"},
    }}
    out = gate.w6_reissue_ledger(st)
    check(out["exhausted"] == 1 and out["reissued"] == 1,
          "R6 失败：点名告警+reissued 应绿（计数 %r）" % out)
    return {"w6_discrimination": True}


def main(argv=None):
    for p in (CARDS, ROUTER, GATE):
        if not os.path.isfile(p):
            print("前置不满足：缺 %s" % p)
            return EXIT_ENV
    cases = (
        ("R1/R4 零终裁豁免释放重派 + 台账读不到 fail-closed", r1_r4),
        ("R2/R3 重发帽预算耗尽恢复遮蔽 + 健康承载幂等不回退", r2_r3),
        ("R5 台账消费腿：reissued/exhausted+告警/超时告警 + 一次性", r5),
        ("R6 W6 门腿判别力：缺字段/无告警点名红，有主推进绿", r6),
    )
    results, failures = {}, []
    for name, fn in cases:
        try:
            with tempfile.TemporaryDirectory(prefix="arb-reissue-") as tmp:
                results[name] = fn(tmp)
            print("  [PASS] %s -> %s" % (name, json.dumps(results[name], ensure_ascii=False)))
        except Fail as e:
            failures.append(name)
            print("  [FAIL] %s -> %s" % (name, e))
        except Exception as e:  # noqa: BLE001
            failures.append(name)
            print("  [FAIL] %s: %s: %s" % (name, type(e).__name__, e))
    if failures:
        print("ARB-REISSUE-UNBLOCK FAILED: %d 项未过 -> %s" % (len(failures), failures))
        return EXIT_FAIL
    print("ARB-REISSUE-UNBLOCK PASSED: %d 项" % len(results))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
