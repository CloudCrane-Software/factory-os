#!/usr/bin/env python3
"""test-verify-qc-truth-gate.py — quote_check 机器真值链独立对账门（RT-E67 拦截机制 a）

背景（逃逸问题台账 RT-E67，计划/研究组/红队终局轮-20261101/逃逸问题台账.md:535-540）：
quote_check 是 router 聚合 admit 的唯一机械依据（event-router.py uphold 逐条消费 qc，
2026-11-01 RT 修复），但登记时对账腿未核得——`grep -c quote_check tools/all-gates.sh`=0、
test-kb-content-parity=0：全仓无任何门独立回查 qc 真值。E67 拦截机制若回退或执行方绕过
finalize-verify，无门可红。本门补上这条腿，四段钉住真值链的四个机械环节：

  Q1 消费侧（router）：uphold 逐条消费 qc——uphold∧qc=true 才 admit；uphold∧qc=false
     不入库（保留 candidate，changelog 带 skipnote）；全 false → 防摆烂作废（void）。
     admit 过滤回退（回到「uphold 整包入库」的旧口径）在本门必红。
  Q2 产侧（factory-kb-worker finalize-verify）：机器真值覆写契约——
     a) 自报 qc=false 而 quote 真在证据 → 覆写 true；自报 qc=true 而 quote 不在证据
        → 覆写 false（两个方向都证明自报值不得存活）；
     b) 未全量覆写（verdict 的 atom_id 不在卡面表解析集 unmatched / 非对象项）→
        ok:false + 退出码 2（RT-E67 对账腿 fail-closed，2026-11-02 同批修）；
     c) 机器行重算失败（problem.md 拉取崩）→ ok:false + 退出码 2，stdout 带 JSON
        （这正是工作流 helper「只在退出码≠0 且 stdout 空才抛错」当初漏掉的那条失败路径）。
  Q3 执行方消费腿（workflow-drafts/*.dwf.ts 文本钉）：凡定义 finalize-verify 调用的
     工作流，一律不得 `await finalizeVerify();` 裸调丢返回值——必须 `const fv = await
     finalizeVerify();` 且消费 `!fv.ok`。目录被清空/改名时本门红（对账面不许静默失明，
     E63 教训）。
  Q4 类型洞等价腿（2026-11-02 RT 修复）：quote_check 六型 payload（True/False/"true"/
     "false"/1/0）双实现对照——收割方 validate（isinstance 强制布尔）与路由器 admit
     （原 bool(v.get("quote_check"))，bool("false")=True 曾使字符串 "false" 被判真值
     通过、6 卡 51 原子两侧判定相反受害）。不变量：收割方拒收 ⇒ 路由器不得 admit 该
     原子；路由器 admit ⇒ 收割方 ok（等价性属性测试，RT-E31 机制④的钉子）。

范围（如实登记）：E67 残余 b)「存量清洗」（1,255 原子/578 miss/305 条，登记员未复跑
全库扫描）不在本门——存量已知坏、扫了即常红，会淹没新回归；存量清偿走台账独立对账。
本门全部 hermetic：零网络、零门户、零 ssh（problem.md/证据全打桩），可进 all-gates L2。

用法：python3 tools/test-verify-qc-truth-gate.py [--keep]
退出码：0 全过；1 断言失败；2 前置不满足。
临时目录建在 $HOME 下自建目录（/tmp 配额有限，硬纪律），pid 后缀互不踩踏，完工即删。
篡改探针（验门牙齿用）：环境变量 QCGATE_ROUTER / QCGATE_WORKER / QCGATE_WFDIR 可把
被测对象指到篡改副本——把缺陷注回去跑本门应红（见回归记录）。
"""
from __future__ import annotations

import argparse
import contextlib
import glob
import importlib.util
import io
import json
import os
import re
import shutil
import sys
import urllib.request

WS = os.path.expanduser("~/workspace/agent黑灯工厂")
HOME = os.path.expanduser("~")
ROUTER = os.environ.get("QCGATE_ROUTER") or os.path.join(WS, "tools", "event-router.py")
HARVESTER = os.environ.get("QCGATE_HARVESTER") or os.path.join(WS, "tools", "sandbox-harvester.py")
WORKER = os.environ.get("QCGATE_WORKER") or os.path.join(WS, "tools", "factory-kb-worker.py")
WFDIR = os.environ.get("QCGATE_WFDIR") or os.path.join(WS, ".zcode", "workflow-drafts")
NAMED_WF = "论文抽取改道批-验证线.dwf.ts"   # 发现点名的在役验证线
SCRATCH = os.path.join(HOME, "qc-truth-gate-scratch.%d" % os.getpid())

EXIT_OK, EXIT_FAIL, EXIT_ENV = 0, 1, 2

EV_TEXT = ("§1 Introduction. The quick brown fox jumps over the lazy dog. "
           "本段不含其它探针句。")
PROBLEM_MD = (
    "# kb-verify-qcgate-probe 待裁决表\n\n"
    "| # | atom_id | kind | locator | 视角 | 原文引文 |\n"
    "|---|---------|------|---------|------|----------|\n"
    "| 1 | `sbx-qcgate-1` | claim | §1 | 逐字核验 | `The quick brown fox` |\n"
    "| 2 | `sbx-qcgate-2` | claim | §1 | 逐字核验 | `slow green turtle` |\n")


class Fail(Exception):
    pass


def check(cond, msg):
    if not cond:
        raise Fail(msg)


def load_mod(name, path):
    check(os.path.isfile(path), "缺被测件：%s" % path)
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ---------- Q1 消费侧：router uphold 逐条消费 qc ----------

def case_router_admit_qc(d):
    r = load_mod("router_qcgate", ROUTER)
    r.CHANGELOG = os.path.join(d, "changelog.md")
    r.VERIFY_DIR = os.path.join(d, "verify")
    os.makedirs(r.VERIFY_DIR, exist_ok=True)
    r.STOP = os.path.join(d, ".router-STOP-not-there")
    admitted, rejected, ingested = [], [], []
    r.kb_ingest_verified = lambda ctx: (ingested.append(ctx) or {"new": 0})
    r.registry_admit = lambda ids, ev, cand: (admitted.extend(ids) or len(ids), 0)
    r.registry_reject = lambda ids, why: (rejected.extend(ids) or len(ids))
    r.make_rework_card = lambda *a, **kw: None

    def run(card_id, verdicts):
        open(r.CHANGELOG, "w").close()
        del admitted[:], rejected[:]
        st = r.load_state()
        st["verify_cards"][card_id] = {
            "card_id": card_id, "task_id": "kb-atoms-qcgate-probe",
            "arxiv": "2404.05427", "candidates": "",
            "atom_ids": [v["atom_id"] for v in verdicts],
            "sampled": len(verdicts), "status": "open"}
        name = card_id + ".json"
        path = os.path.join(r.VERIFY_DIR, name)
        r.handle_verify_report(st, name, path,
                               {"task_id": card_id,
                                "payload": {"verify": True, "card_id": card_id,
                                            "verdicts": verdicts}})
        return (list(admitted), list(rejected), st["verify_cards"][card_id]["status"],
                open(r.CHANGELOG, encoding="utf-8").read())

    def v(aid, verdict="uphold", qc=True):
        return {"atom_id": aid, "verdict": verdict, "quote_check": qc,
                "reason": "§1: 对账门探针"}

    # 主探针：4×(uphold∧qc=true) + 1×(uphold∧qc=false) → 率 4/5=0.8 达标走 passed 分支，
    # 唯 qc=false 的 r5 不得入库（旧口径「uphold 整包入库」会把它混进 admitted → 本门红）。
    ids = ["sbx-qcgate-r%d" % i for i in range(1, 6)]
    vs = [v(i) for i in ids[:4]] + [v(ids[4], qc=False)]
    adm, rej, status, chlog = run("kb-verify-qcgate-probe", vs)
    check(adm == ids[:4], "admit 侧 qc 消费回退：admitted=%r（应只含 qc=true 的 4 条）" % adm)
    check(ids[4] not in adm and ids[4] not in rej,
          "uphold∧qc=false 原子被入库/终拒（应保留 candidate 不入库）：%r" % (adm + rej))
    check(status == "passed", "卡状态=%r（4/5 达标应 passed）" % status)
    check("quote_check 非真" in chlog,
          "changelog 无 qc 非真不入库的 skipnote（对账不可读）：%r" % chlog[:200])
    check(len(ingested) == 1, "passed 卡未触发 kb 入库记账：%r" % ingested)
    # 机制在场（E63 护栏：功能断言之外，钉住生产判定机制本身，防换名绕过 grep 词表）。
    # 2026-11-02 类型洞修复：原钉 'bool(v.get("quote_check"))' 在场随缺陷一并撤换——
    # 现钉严格布尔判定 qc_true（isinstance 口径与收割方 validate 同源）在场，且全源
    # 禁止残留宽松 bool(qc) 判定（回注即红）。
    src = open(ROUTER, encoding="utf-8").read()
    check("def qc_true(" in src and "isinstance(qc, bool) and qc" in src,
          "router 源里 qc 严格布尔判定机制 qc_true 不见了（类型洞修复被改写/换名未对账）")
    check('bool(v.get("quote_check"))' not in src,
          "router 源里残留宽松 bool(qc) 判定（类型洞回归：字符串 \"false\" 会被判真值通过）")
    # 防摆烂：全 false → void，不 admit 不 reject
    vs_void = [v(i, qc=False) for i in ids]
    adm2, rej2, status2, chlog2 = run("kb-verify-qcgate-probe-void", vs_void)
    check(adm2 == [] and rej2 == [], "全 false 探针被 admit/reject（应作废）：%r %r" % (adm2, rej2))
    check(status2 == "void" and "防摆烂" in chlog2, "防摆烂作废分支回退：%r %r" % (status2, chlog2[:160]))
    return {"admitted": len(adm), "qc_false_kept_candidate": ids[4],
            "void_probe": status2, "router_source_pin": True}


# ---------- Q2 产侧：finalize-verify 机器真值覆写契约 ----------

class _FakeResp:
    def __init__(self, body):
        self._b = body

    def read(self):
        return self._b.encode("utf-8")


def _run_finalize(w, payload_obj, card_id, d, urlopen_stub):
    payload_path = os.path.join(d, "payload.json")
    with open(payload_path, "w", encoding="utf-8") as f:
        json.dump(payload_obj, f, ensure_ascii=False)
    saved_uro = urllib.request.urlopen
    saved_evf, saved_evt = w.evidence_for, w.evidence_texts
    urllib.request.urlopen = urlopen_stub
    w.evidence_for = lambda aid: {"aid": aid,
                                  "files": {"abs.md": {"path": os.path.join(d, "abs.md"),
                                                       "len": len(EV_TEXT),
                                                       "sha256": "0" * 64, "ok": True}}}
    w.evidence_texts = lambda ev: {"abs.md": EV_TEXT}
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            code = 0
            try:
                w.cmd_finalize_verify(payload_path, card_id)
            except SystemExit as e:
                code = int(e.code or 0)
    finally:
        urllib.request.urlopen = saved_uro
        w.evidence_for, w.evidence_texts = saved_evf, saved_evt
    try:
        res = json.loads(buf.getvalue())
    except ValueError:
        res = {}
    on_disk = None
    if os.path.isfile(payload_path):
        on_disk = json.load(open(payload_path, encoding="utf-8"))
    return code, res, on_disk


def case_finalize_verify_contract(d):
    os.makedirs(d, exist_ok=True)
    w = load_mod("worker_qcgate", WORKER)
    card = "kb-verify-kb-atoms-acr-2404.05427-qcgate"

    def vd(aid, qc, verdict="uphold"):
        return {"atom_id": aid, "verdict": verdict, "quote_check": qc, "reason": "探针"}

    # a) 全量覆写：自报 false+quote 真在证据 → true；自报 true+quote 不在 → false。
    #    两个方向都证明：模型自报 qc 不得在覆写后存活。
    ok_vs = [vd("sbx-qcgate-1", False), vd("sbx-qcgate-2", True)]
    code, res, disk = _run_finalize(w, {"verify": True, "card_id": card,
                                        "verdicts": list(ok_vs)}, card, d,
                                   lambda req, timeout=30: _FakeResp(PROBLEM_MD))
    check(code == 0, "全量覆写场景退出码=%d（应 0）：%r" % (code, res))
    check(res.get("ok") is True and res.get("patched") == 2 and res.get("unmatched") == [],
          "全量覆写返回形状不符：%r" % res)
    q = {v["atom_id"]: v["quote_check"] for v in (disk or {}).get("verdicts", [])}
    check(q.get("sbx-qcgate-1") is True,
          "自报 qc=false 而 quote 真在证据未被覆写为 true（机器真值被自报压住）：%r" % q)
    check(q.get("sbx-qcgate-2") is False,
          "自报 qc=true 而 quote 不在证据未被覆写为 false（坏引文带真 qc 上门户）：%r" % q)

    # b) 未全量覆写 → ok:false + exit 2：unmatched（atom_id 不在卡面表解析集）+
    #    非对象项，模型自报 qc 残留情形 fail-closed（RT-E67 对账腿，2026-11-02）。
    bad_vs = [vd("sbx-qcgate-1", False), vd("sbx-qcgate-2", True),
              vd("sbx-qcgate-99", True), "oops-非对象"]
    code2, res2, _disk2 = _run_finalize(w, {"verify": True, "card_id": card,
                                            "verdicts": bad_vs}, card, d,
                                        lambda req, timeout=30: _FakeResp(PROBLEM_MD))
    check(code2 == 2 and res2.get("ok") is False,
          "unmatched 残留未 fail-closed（exit=%d res=%r）——自报 qc 会照此上门户" % (code2, res2))
    check("sbx-qcgate-99" in (res2.get("unmatched") or []),
          "unmatched 未点名越表 atom：%r" % res2)
    check(len(res2.get("non_dict") or []) == 1, "非对象项未计数：%r" % res2)
    check("未全量覆写" in (res2.get("reason") or ""), "reason 未说明 fail-closed 原因：%r" % res2)

    # c) 机器行重算失败（problem.md 拉取崩）→ ok:false + exit 2，stdout 恒带 JSON。
    #    这条失败路径正是工作流 helper（只在退出码≠0 且 stdout 空才抛错）曾静默放行的口子。
    def boom(req, timeout=30):
        raise RuntimeError("portal down（对账门注入）")

    code3, res3, _d3 = _run_finalize(w, {"verify": True, "card_id": card,
                                         "verdicts": list(ok_vs)}, card, d, boom)
    check(code3 == 2 and res3.get("ok") is False,
          "重算失败未 fail-closed（exit=%d res=%r）" % (code3, res3))
    check("机器行重算失败" in (res3.get("reason") or ""), "重算失败原因未回传：%r" % res3)
    return {"overwrite_bidirectional": q, "unmatched_closed": True,
            "recompute_fail_closed": code3}


# ---------- Q3 执行方消费腿：workflow-drafts 文本钉 ----------

def case_workflow_consumption_pin():
    files = sorted(glob.glob(os.path.join(WFDIR, "*.dwf.ts")))
    check(len(files) >= 1,
          "workflow-drafts 下一个 .dwf.ts 都没有（目录被清空/迁移）——消费腿钉子全盲，拒判绿")
    check(NAMED_WF in [os.path.basename(f) for f in files],
          "发现点名的在役验证线 %s 不在 workflow-drafts（改名/挪目录未对账）" % NAMED_WF)
    pinned = []
    for f in files:
        src = open(f, encoding="utf-8").read()
        if "finalize-verify" not in src:
            continue
        base = os.path.basename(f)
        pinned.append(base)
        # 先剥 // 行注释再钉（注释里叙述旧缺陷写法不算裸调；URL 的 // 截行只影响该行，
        # 对本钉可接受）。裸调=丢弃返回值：调用点前跳过空白后不是「=」结尾才算裸
        # （`const fv = await finalizeVerify();` 是消费形态，不算裸）。
        code_only = re.sub(r"//[^\n]*", "", src)
        bare = sum(1 for m in re.finditer(r"await finalizeVerify\(\);", code_only)
                   if not code_only[:m.start()].rstrip().endswith("="))
        check(bare == 0,
              "%s：%d 处 `await finalizeVerify();` 裸调丢返回值（finalize-verify 失败路径"
              " stdout 恒有 JSON，helper 不抛错 → 模型自报 qc 残留直上门户）" % (base, bare))
        check("const fv = await finalizeVerify();" in code_only and "!fv.ok" in code_only,
              "%s：finalize-verify 返回值未被消费（缺 const fv = await finalizeVerify(); "
              "或 !fv.ok 检查）" % base)
    check(len(pinned) >= 1, "workflow-drafts 内已无任何 finalize-verify 调用工作流（钉子空转）")
    return {"pinned_files": pinned, "named_live_line": NAMED_WF}


# ---------- Q4 类型洞等价腿：收割方 validate 与路由器 admit 同向（2026-11-02） ----------

def case_qc_type_equivalence(d):
    """六型 qc payload 双实现对照（RT-E31 机制④等价性钉子）：
    字符串 "true"/"false"、1/0 收割方必拒收（sandbox-harvester.validate isinstance 强制
    布尔），路由器必不得 admit 同一原子——bool("false")=True 的类型洞曾使两侧对同一
    payload 判定相反（实测 6 卡 51 原子：收割方整份拒收而路由器照 admit 双库 verified）。"""
    r = load_mod("router_qceq", ROUTER)
    h = load_mod("harvester_qceq", HARVESTER)
    r.CHANGELOG = os.path.join(d, "changelog.md")
    r.VERIFY_DIR = os.path.join(d, "verify")
    os.makedirs(r.VERIFY_DIR, exist_ok=True)
    r.STOP = os.path.join(d, ".router-STOP-not-there")
    admitted, rejected = [], []
    r.kb_ingest_verified = lambda ctx: {"new": 0}
    r.registry_admit = lambda ids, ev, cand: (admitted.extend(ids) or len(ids), 0)
    r.registry_reject = lambda ids, why: (rejected.extend(ids) or len(ids))
    r.make_rework_card = lambda *a, **kw: None

    def vd(aid, qc, verdict="uphold"):
        return {"atom_id": aid, "verdict": verdict, "quote_check": qc, "reason": "§1: 探针"}

    def run_router(card_id, verdicts, atom_ids):
        del admitted[:], rejected[:]
        open(r.CHANGELOG, "w").close()
        st = r.load_state()
        st["verify_cards"][card_id] = {
            "card_id": card_id, "task_id": "kb-atoms-qceq-probe",
            "arxiv": "2404.05427", "candidates": "",
            "atom_ids": atom_ids, "sampled": len(verdicts), "status": "open"}
        name = card_id + ".json"
        r.handle_verify_report(st, name, os.path.join(r.VERIFY_DIR, name),
                               {"task_id": card_id,
                                "payload": {"verify": True, "card_id": card_id,
                                            "verdicts": verdicts}})
        return (list(admitted), list(rejected),
                st["verify_cards"][card_id]["status"],
                open(r.CHANGELOG, encoding="utf-8").read())

    # 六型逐一对照：收割方拒收 ⇏ 路由器 admit（等价性不变量，双向表述）
    variants = [True, False, "true", "false", 1, 0]
    table = {}
    for i, qc in enumerate(variants):
        aid = "sbx-qceq-%d" % i
        card_id = "kb-verify-qceq-probe-%d" % i
        rep = {"task_id": card_id,
               "payload": {"verify": True, "card_id": card_id,
                           "verdicts": [vd(aid, qc)]}}
        hv_verdict = h.validate(rep)[0]
        adm, rej, status, _ = run_router(card_id, [vd(aid, qc)], [aid])
        hv_ok = hv_verdict == "ok"
        check(not adm or hv_ok,
              "类型洞回归：qc=%r 收割方 %s 而路由器 admit %r（两侧判定相反）"
              % (qc, hv_verdict, adm))
        check(hv_ok or (not adm and not rej),
              "qc=%r 收割方拒收但路由器动了原子状态（admit=%r reject=%r，应保留不判）"
              % (qc, adm, rej))
        table[repr(qc)] = {"harvester": hv_verdict, "router_admitted": bool(adm),
                           "router_status": status}
    # 主形态定向钉（发现原文两行）：字符串 "false"/"true" 两侧同向——收割方拒收、路由器不放行
    check(table[repr("false")]["harvester"] == "rejected"
          and not table[repr("false")]["router_admitted"],
          "字符串 \"false\" 主形态回归：%r" % table[repr("false")])
    check(table[repr("true")]["harvester"] == "rejected"
          and not table[repr("true")]["router_admitted"],
          "字符串 \"true\" 主形态回归：%r" % table[repr("true")])
    # 正向对照：真布尔 true 两侧全绿（收割方 ok ∧ 路由器 admit）；真布尔 false 收割方
    # 结构 ok 但路由器防摆烂作废不放行（既有语义，Q1 已钉）——两侧行为如实登记进表。
    check(table[repr(True)] == {"harvester": "ok", "router_admitted": True,
                                "router_status": "passed"},
          "qc=True 正向对照回归：%r" % table[repr(True)])
    check(table[repr(False)]["router_admitted"] is False,
          "qc=False 被路由器放行（防摆烂作废条款回退）：%r" % table[repr(False)])

    # 混合卡：布尔 true 与字符串 "false" 同卡（率 2/2 达标走 passed 分支）→ 只 admit
    # 布尔真那条，字符串条保留 candidate 且 changelog 带「quote_check 非真」skipnote。
    ids = ["sbx-qceq-m1", "sbx-qceq-m2"]
    adm, rej, status, chlog = run_router("kb-verify-qceq-probe-mixed",
                                         [vd(ids[0], True), vd(ids[1], "false")], ids)
    check(adm == ids[:1] and not rej and status == "passed",
          "混合卡 admit 分割回归（应只 admit 布尔真条）：%r %r %r" % (adm, rej, status))
    check("quote_check 非真" in chlog,
          "混合卡 changelog 缺 qc 非真 skipnote（对账不可读）：%r" % chlog[:200])
    return {"six_variants": table, "mixed_admit": adm}


# ---------- main ----------

def main(argv=None):
    ap = argparse.ArgumentParser(description="quote_check 机器真值链独立对账门（RT-E67）")
    ap.add_argument("--keep", action="store_true", help="保留临时目录（排查用）")
    a = ap.parse_args(argv)

    os.makedirs(SCRATCH, exist_ok=True)
    results, failures = {}, []
    try:
        cases = [
            ("Q1 消费侧：router uphold 逐条消费 qc（qc=false 不入库+防摆烂作废）",
             lambda d: case_router_admit_qc(d)),
            ("Q2 产侧：finalize-verify 双向覆写 + 未全量覆写/重算失败 fail-closed",
             lambda d: case_finalize_verify_contract(os.path.join(d, "q2"))),
            ("Q3 执行方消费腿：*.dwf.ts 无裸调 finalizeVerify、返回值必消费",
             lambda d: case_workflow_consumption_pin()),
            ("Q4 类型洞等价腿：qc 六型 payload 收割方/路由器判定同向",
             lambda d: case_qc_type_equivalence(os.path.join(d, "q4"))),
        ]
        for i, (name, fn) in enumerate(cases):
            d = os.path.join(SCRATCH, "case-%d" % i)
            shutil.rmtree(d, ignore_errors=True)   # 先清后建（被硬杀的残留不背锅）
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
                print("  [FAIL] %s: %s: %s" % (name, type(e).__name__, e), flush=True)
    finally:
        if not a.keep:
            shutil.rmtree(SCRATCH, ignore_errors=True)

    if failures:
        print("QC-TRUTH GATE FAILED: %d 项未过 -> %s" % (len(failures), failures), flush=True)
        return EXIT_FAIL
    print("QC-TRUTH GATE PASSED: %d 项（router qc 消费 / finalize-verify 覆写契约 / "
          "工作流返回值消费 / qc 类型洞双实现等价 四环节全钉）" % len(results), flush=True)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
