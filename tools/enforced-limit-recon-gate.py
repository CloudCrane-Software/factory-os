#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/enforced-limit-recon-gate.py — enforced-limit 断言门（D-156 · ESC-18 · 卡 #244）。

【锚号】D-156（账本/阶段欠账台账.md D-156 行）　【卡号】factory-os issue #244
  （wave-15 · w15-d156-enforced-limit-gate · 允许路径=本件单件）。
【判据锚】资源负载均衡与调度域-SOTA宪章-v1.md:136（R-05）与 :177-178②
  （SCH-4②：「降规格的规格必须是 enforced limit（cgroup/requests 形制）——
  .cnb.yml runner.cpus:2 对系统 NPC 不生效（实测 8 核档计费）⇒ 现降规格不可证」）。

【为什么建本门（D-156 债本体）】
  cnb 降规格不可证：.cnb.yml runner.cpus:2 声明对系统计费不生效（实测 8 核档计费），
  降规格声明自写自消费——任何 enforcement 面（cgroup/平台计费档/requests 形制）不读
  它；宪章 SCH-4② 明文「降规格的规格必须是 enforced limit」而无断言件（ESC-18 新门
  设计栏）。本门把该判据落成机器断言（派发前 dispatch 腿）：对限额/配额类读数件逐条
  断言 enforced 标志与限值在位，且声明值 ≡ enforcement 面实读值——声明 2 核而计费
  8 档即红禁派。与 D-131（派发前余量预检：还剩多少）分属两事不并吞——本门只问
  「降下来的规格是否真被执行面 enforce」。

【读数件契约（schema af.enforced-limit-reading/v1）】
  {"schema": "af.enforced-limit-reading/v1",
   "enforcement_face_readable": true,      # 必填布尔：计费档 API/cgroup/requests
                                           # 等 enforcement 面实读是否可得
   "readings": [
     {"name": "runner-cpus",
      "resource": "cpus",                  # 限额/配额口径判定域（口径词见
                                           # LIMIT_CALIBER_WORDS，子串不区分大小写）
      "declared": 2,                       # 卡面降规格声明值（≥0 有限数）
      "enforced": true,                    # enforcement 面生效标志（布尔）
      "enforced_value": 2,                 # enforcement 面实读限值（≥0 有限数）
      "face": "cb-npc-billing-tier"}, …]}  # face 来源溯源（可选，非空串）

【判定语义（对在域读数逐条四断言；缺/坏即红点名）】
  在域条目=resource 含限额/配额口径词（其余 resource ⇒ INFO 域外跳过；resource
  缺席/非串 ⇒ 口径不可判，红——fail-closed 不猜绿）。逐条断言：
  · 缺 enforced 标志 / 非布尔 ⇒ 红（声明是否被执行面读无从对账）；
  · enforced=false ⇒ 红（降规格声明自写自消费——D-156 本体形态）；
  · 缺限值 enforced_value / 非法（非 ≥0 有限数：负数/NaN/非数）⇒ 红；
  · 缺声明值 declared / 非法 ⇒ 红（声明↔enforced 对账无从做起）；
  · declared ≠ enforced_value（声明 2 核↔计费 8 档形态）⇒ 红禁派；
  · 全在位且一致（含 0≡0 足额封锁配额、2.0≡2 数值等价）⇒ 该条通过。
  文件级：非 JSON/顶层非对象/schema 不符/readings 空壳 ⇒ 红（不猜绿）；
  enforcement_face_readable 缺席/非布尔 ⇒ 红坏形；
  enforcement_face_readable=false ⇒ 不可证（face 实读不可得——不猜绿不猜红，
  fail-closed 禁派；读数面已不可证，条目面无从判起即整件短路）。
  「或降级为『无降规格』如实标注」是派发面的处置选项，不属本门判定——本门只断言
  enforced congruence，是否改派全档由 dispatch 决。

【退出码】0=绿（face 可读＋全部在域读数四断言通过）；
  1=红（缺 enforced/缺限值/缺声明值/enforced=false/声明≠enforced/坏形，逐条点名）；
  2=不可证（enforcement_face_readable=false face 实读不可得 ⇒ fail-closed 禁派；
    含 --check 读数件缺席/不可读——实读证据缺席即不可证；及 CLI 用法错）。

【用法】
  python3 -I tools/enforced-limit-recon-gate.py --selftest          # 内嵌夹具全跑（rc=0）
  python3 -I tools/enforced-limit-recon-gate.py --fixture <名>      # 单夹具（rc=该夹具裁决）
  python3 -I tools/enforced-limit-recon-gate.py --check <读数件路径>  # 真查读数件
  夹具名：congruent-ok / mismatch-2v8 / face-unreadable / enforced-false /
          missing-enforced / missing-limit / missing-declared / bad-shape-json /
          empty-readings / missing-face-flag / bad-enforced-type / negative-limit /
          zero-quota-ok / float-congruent / out-of-scope-resource
  （三验收语义夹具：一致=congruent-ok（rc=0）；失配=mismatch-2v8（声明 2 核↔
   计费 8 档，rc=1）；不可证=face-unreadable（rc=2 fail-closed 禁派）。）

纪律：判官/门禁/判据件零改动（本件为 tools/ 新增件，不碰 all-gates.sh/
  gate-pins.list/点选面；门本体未挂 all-gates 点选面，巡检接线属后续经批动作）；
  零网络、零凭据、零写入（--check 只读；--selftest 仅 tempfile/subprocess 沙箱）；
  红不猜绿（缺标注即红，不可证即禁派）；selftest 全部真跑不编造。
"""

import argparse
import json
import math
import os
import subprocess
import sys
import tempfile

SCHEMA = "af.enforced-limit-reading/v1"
GREEN, RED, UNPROV = 0, 1, 2
SEV_ORDER = {"RED": 0, "UNPROVABLE": 1, "INFO": 2}
# 限额/配额口径词（子串匹配、不区分大小写）：命中即在域须过四断言；未命中域外
# INFO 跳过。词表从严取宽（宁多判不漏判——限/配面域外跳过只留给明确非口径词）。
LIMIT_CALIBER_WORDS = ("cpu", "core", "mem", "gpu", "disk", "quota", "limit",
                       "budget", "concurr", "并发", "qps", "tps", "rate",
                       "bandwidth", "iops", "token", "slot")


def red(tag, msg):
    return {"sev": "RED", "tag": tag, "msg": "[RED] %s %s" % (tag, msg)}


def unprovable(tag, msg):
    return {"sev": "UNPROVABLE", "tag": tag,
            "msg": "[UNPROVABLE] %s %s" % (tag, msg)}


def info(tag, msg):
    return {"sev": "INFO", "tag": tag, "msg": "[INFO] %s %s" % (tag, msg)}


def is_in_scope(resource):
    """限额/配额口径判定：resource 含口径词 ⇒ True；其他非空串 ⇒ False；
    缺席/非串/空 ⇒ None（口径不可判，调用方按 fail-closed 处理）。"""
    if not isinstance(resource, str) or not resource.strip():
        return None
    low = resource.lower()
    return any(w in low for w in LIMIT_CALIBER_WORDS)


def is_valid_limit(x):
    """限值合法性：有限数（int/float，拒布尔）且 ≥0（0=足额封锁配额合法——
    本卡自身【mem_budget】0 G 形态；负数/NaN/Inf/非数坏形）。"""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return False
    return math.isfinite(x) and x >= 0


def judge_entry(entry, idx):
    """单条读数判定（enforced 标志＋限值＋声明值＋congruence 四断言）。

    返回 findings（sev ∈ RED/INFO；四断言相互独立，缺一各自点名；
    congruence 断言仅在两值均合法时做——避免对同一坏值双重点名噪音）。"""
    if not isinstance(entry, dict):
        return [red("#%d" % idx, "读数条目非对象（%r）——读数件结构损坏，不猜绿"
                    % (entry,))]
    name = entry.get("name")
    tag = name.strip() if isinstance(name, str) and name.strip() else "#%d" % idx
    scope = is_in_scope(entry.get("resource"))
    if scope is None:
        return [red(tag, "resource 缺席/非串（实得 %r）——是否限额/配额类读数无从"
                    "排除，fail-closed 红" % (entry.get("resource"),))]
    if not scope:
        return [info(tag, "resource=%s 非限额/配额口径——域外跳过不判"
                     % (entry.get("resource"),))]

    findings = []
    # 断言一：enforced 标志在位且为真
    if "enforced" not in entry:
        findings.append(red(tag, "缺 enforced 标志——声明是否被执行面读无从对账，"
                            "fail-closed 红（D-156）"))
    else:
        en = entry.get("enforced")
        if not isinstance(en, bool):
            findings.append(red(tag, "enforced 标志非法（实得 %r）——须为布尔" % (en,)))
        elif not en:
            findings.append(red(tag, "enforced=false——降规格声明未被执行面读"
                                "（自写自消费，D-156 本体形态）：声明对计费/cgroup "
                                "不生效即非 enforced limit"))
    # 断言二：限值（enforced_value）在位且合法
    if "enforced_value" not in entry:
        findings.append(red(tag, "缺限值 enforced_value——enforced limit 的数值面"
                            "缺席即断言不可成立，fail-closed 红"))
    else:
        ev = entry.get("enforced_value")
        if not is_valid_limit(ev):
            findings.append(red(tag, "限值非法（实得 %r）——须为 ≥0 有限数"
                                "（0=足额封锁配额合法；负数/NaN/非数坏形）" % (ev,)))
    # 断言三：声明值在位且合法（congruence 的一边）
    if "declared" not in entry:
        findings.append(red(tag, "缺声明值 declared——声明↔enforced 对账无从做起，"
                            "fail-closed 红"))
    else:
        d = entry.get("declared")
        if not is_valid_limit(d):
            findings.append(red(tag, "声明值非法（实得 %r）——须为 ≥0 有限数" % (d,)))
    # 断言四：congruence（仅在两值均合法时判）
    d, ev = entry.get("declared"), entry.get("enforced_value")
    if is_valid_limit(d) and is_valid_limit(ev) and d != ev:
        findings.append(red(tag, "声明值≠enforced 值（declared=%s ↔ enforced_value="
                            "%s）——红禁派：降规格的规格必须是 enforced limit"
                            "（宪章 SCH-4② :177-178；D-156 实例=声明 2 核↔计费"
                            " 8 档）" % (d, ev)))
    return findings


def judge_payload(text, origin):
    """读数件全文判定（文件级 fail-closed + face 可读性三态 + 逐条四断言）。"""
    try:
        data = json.loads(text)
    except ValueError as exc:
        return [red("<file>", "读数件 %s 非 JSON：%s——fail-closed 不猜绿"
                    % (origin, exc))]
    if not isinstance(data, dict):
        return [red("<file>", "读数件 %s 顶层非对象（实得 %s）——结构损坏"
                    % (origin, type(data).__name__))]
    if data.get("schema") != SCHEMA:
        return [red("<file>", "读数件 %s schema 缺席/不符（期望 %s，实得 %r）——"
                    "读数契约不可证，不猜绿" % (origin, SCHEMA, data.get("schema")))]
    if "enforcement_face_readable" not in data:
        return [red("<file>", "缺 enforcement_face_readable 标注（读数件契约必填"
                    "域）——face 实读来源不可证，坏形红不猜绿")]
    face = data.get("enforcement_face_readable")
    if not isinstance(face, bool):
        return [red("<file>", "enforcement_face_readable 非布尔（实得 %r）——坏形红"
                    % (face,))]
    if face is False:
        return [unprovable("<face>",
                           "enforcement 面实读不可得（enforcement_face_readable="
                           "false）——降规格是否 enforced limit 无从证明，不可证 "
                           "fail-closed 禁派（不猜绿不猜红，条目面无从判起）")]
    readings = data.get("readings")
    if not isinstance(readings, list) or not readings:
        return [red("<file>", "读数件 %s readings 缺席/空（空壳读数件）——face 可读"
                    "而零读数即零证明，不猜绿" % (origin,))]
    findings = []
    for idx, entry in enumerate(readings):
        findings.extend(judge_entry(entry, idx))
    return findings


def verdict_of(findings):
    """三态收敛：任一 RED ⇒ (red,1)；否则任一 UNPROVABLE ⇒ (unprovable,2)；
    绿 ⇒ (clean,0)。"""
    sevs = {f["sev"] for f in findings}
    if "RED" in sevs:
        return "red", RED
    if "UNPROVABLE" in sevs:
        return "unprovable", UNPROV
    return "clean", GREEN


# ---------------------------------------------------------------- 夹具与自测 --
def _entry(**kw):
    base = {"name": "runner-cpus", "resource": "cpus",
            "declared": 2, "enforced": True, "enforced_value": 2,
            "face": "cb-npc-billing-tier"}
    base.update(kw)
    return base


def _doc(readings, face=True):
    return json.dumps({"schema": SCHEMA, "enforcement_face_readable": face,
                       "readings": readings}, ensure_ascii=False)


def _doc_noface(readings):
    return json.dumps({"schema": SCHEMA, "readings": readings},
                      ensure_ascii=False)


# （名，描述，读数件文本，期望 rc，红/不可证行须含串）
FIXTURES = [
    ("congruent-ok", "一致→rc=0：face 可读，enforced=true 且 declared≡"
     "enforced_value（cpus 2≡2；mem 3.0≡3 数值等价）",
     _doc([_entry(),
           _entry(name="runner-mem", resource="mem_gb", declared=3.0,
                  enforced_value=3, face="cgroup-memory.max")]),
     GREEN, None),
    ("mismatch-2v8", "失配→rc=1：声明 2 核↔计费 8 档（D-156 本债实例形态）——"
     "红禁派",
     _doc([_entry(enforced_value=8)]),
     RED, "≠enforced 值"),
    ("face-unreadable", "不可证→rc=2 fail-closed 禁派：计费档/cgroup 实读不可得"
     "（enforcement_face_readable=false）——不猜绿不猜红",
     _doc([_entry()], face=False),
     UNPROV, "不可证"),
    ("enforced-false", "enforced=false→rc=1：降规格声明未被执行面读（自写自消费）",
     _doc([_entry(enforced=False)]),
     RED, "自写自消费"),
    ("missing-enforced", "缺 enforced 标志→rc=1（fail-closed）",
     _doc([{k: v for k, v in _entry().items() if k != "enforced"}]),
     RED, "缺 enforced"),
    ("missing-limit", "缺限值 enforced_value→rc=1（fail-closed）",
     _doc([{k: v for k, v in _entry().items() if k != "enforced_value"}]),
     RED, "缺限值"),
    ("missing-declared", "缺声明值 declared→rc=1（congruence 无从做起）",
     _doc([{k: v for k, v in _entry().items() if k != "declared"}]),
     RED, "缺声明值"),
    ("bad-shape-json", "坏形（非 JSON）→rc=1 fail-closed 红",
     "{not json",
     RED, "非 JSON"),
    ("empty-readings", "空壳读数件（readings 空）→rc=1 不猜绿",
     _doc([]),
     RED, "空壳"),
    ("missing-face-flag", "缺 enforcement_face_readable 标注（契约必填域）→rc=1 "
     "坏形红",
     _doc_noface([_entry()]),
     RED, "enforcement_face_readable"),
    ("bad-enforced-type", "enforced 非布尔（字符串）→rc=1 坏形红",
     _doc([_entry(enforced="yes")]),
     RED, "须为布尔"),
    ("negative-limit", "限值负数→rc=1 坏形红（限值须 ≥0：0=足额封锁配额合法）",
     _doc([_entry(declared=-1, enforced_value=-1)]),
     RED, "限值非法"),
    ("zero-quota-ok", "0≡0 足额封锁配额通过（卡面【mem_budget】0 G 形态）→rc=0",
     _doc([_entry(name="mem-budget", resource="mem_budget", declared=0,
                  enforced_value=0)]),
     GREEN, None),
    ("float-congruent", "declared=2.0 ↔ enforced_value=2 数值等价→rc=0",
     _doc([_entry(declared=2.0)]),
     GREEN, None),
    ("out-of-scope-resource", "resource=p50_latency_ms 非限额/配额口径域外 INFO "
     "跳过＋在域一条绿→rc=0",
     _doc([_entry(name="leg-p50", resource="p50_latency_ms"),
           _entry()]),
     GREEN, None),
]


def run_selftest():
    """内嵌夹具自测：三验收语义各夹具真跑 + 边界/形制单元断言 + CLI 退出码映射
    （subprocess 实取 returncode，同 -I 调用形制）。零网络零真实件读取。"""
    checks = []

    def check(name, cond, detail=""):
        checks.append((name, bool(cond), detail))

    for name, desc, text, expect_rc, contains in FIXTURES:
        findings = judge_payload(text, "fixture:" + name)
        verdict, rc = verdict_of(findings)
        check("fixture.%s" % name, rc == expect_rc,
              "desc=%s verdict=%s（期望 %d）findings=%s"
              % (desc, verdict, expect_rc, [f["msg"][:80] for f in findings]))
        if contains is not None:
            check("fixture.%s.msg" % name,
                  any(f["sev"] in ("RED", "UNPROVABLE")
                      and contains in f["msg"] for f in findings),
                  "红/不可证行未含 %r：%s" % (contains,
                                              [f["msg"][:80] for f in findings]))

    # —— 单元断言（judge_entry/judge_payload/is_valid_limit 纯函数面）——
    # 三态收敛：RED 压过 UNPROVABLE（两界皆禁派，红优先点名）
    check("verdict.tri-state",
          verdict_of([]) == ("clean", GREEN)
          and verdict_of([info("t", "")]) == ("clean", GREEN)
          and verdict_of([unprovable("t", "")]) == ("unprovable", UNPROV)
          and verdict_of([red("t", ""), unprovable("t", "")]) == ("red", RED))
    # 限值合法性面：0/2/2.5 收；布尔/串/负数/NaN/Inf 拒（NaN 由 json.loads
    # 对非标 JSON「NaN」宽容产生——本门不放过）
    for good in (0, 2, 2.5, 2.0, 1e9):
        check("unit.limit-good-%r" % (good,), is_valid_limit(good))
    for bad in (True, False, "2", -1, float("nan"), float("inf"), None, [2]):
        check("unit.limit-bad-%r" % (bad,), not is_valid_limit(bad))
    # 口径域：大小写同判；空/非串/缺席 ⇒ None（不可判红）
    check("unit.scope-case",
          is_in_scope("CPUS") is True and is_in_scope("Mem_GB") is True
          and is_in_scope("cargo_concurrency") is True
          and is_in_scope("p50_latency_ms") is False
          and is_in_scope("") is None and is_in_scope(7) is None)
    # resource 缺席 ⇒ 口径不可判红（fail-closed）
    check("unit.resource-absent-red",
          verdict_of(judge_entry({"name": "x", "declared": 2,
                                  "enforced": True, "enforced_value": 2}, 0))
          == ("red", RED))
    # 双缺（enforced 与 enforced_value 同时缺）⇒ 两条红各自点名
    e = _entry(); e.pop("enforced"); e.pop("enforced_value")
    fboth = judge_entry(e, 0)
    check("unit.both-missing-two-reds",
          len([x for x in fboth if x["sev"] == "RED"]) == 2, str(fboth))
    # 三缺（再加 declared）⇒ 三条红（四断言缺三各自点名，无 congruence 噪音）
    e = _entry(); e.pop("enforced"); e.pop("enforced_value"); e.pop("declared")
    check("unit.triple-missing-three-reds",
          len(judge_entry(e, 0)) == 3)
    # 非对象条目 ⇒ 红
    check("unit.non-dict-entry-red",
          verdict_of(judge_entry("nope", 0)) == ("red", RED))
    # mismatch 数值面：2↔8 红；2↔2.0 绿（数值等价非串比较）
    check("unit.mismatch-2v8-red",
          verdict_of(judge_entry(_entry(enforced_value=8), 0)) == ("red", RED))
    check("unit.float-eq-green",
          verdict_of(judge_entry(_entry(declared=2.0), 0)) == ("clean", GREEN))
    # enforced=false 即红（即使数值「一致」——未被面读的声明不构成证明）
    check("unit.enforced-false-red-even-if-congruent",
          verdict_of(judge_entry(_entry(enforced=False), 0)) == ("red", RED))
    # 文件级：schema 不符 / 顶层非对象 / face 非布尔 ⇒ 红
    check("unit.bad-schema-red",
          verdict_of(judge_payload(json.dumps(
              {"schema": "other/v9", "enforcement_face_readable": True,
               "readings": [_entry()]}), "<t>")) == ("red", RED))
    check("unit.top-list-red",
          verdict_of(judge_payload(json.dumps([_entry()]), "<t>"))
          == ("red", RED))
    check("unit.face-nonbool-red",
          verdict_of(judge_payload(_doc([_entry()], face="true"), "<t>"))
          == ("red", RED))
    # face=false 优先短路为不可证（不落入逐条缺-enforced 红雨）
    fface = judge_payload(_doc([], face=False), "<t>")
    check("unit.face-false-shortcircuit-unprovable",
          verdict_of(fface) == ("unprovable", UNPROV)
          and len(fface) == 1 and "禁派" in fface[0]["msg"], str(fface))
    # 点名可读面：红行必须带 tag（逐条点名语义）
    fmis = judge_entry(_entry(enforced_value=8), 0)
    check("naming.red-carries-tag",
          all(x["tag"] == "runner-cpus" for x in fmis) and len(fmis) == 1,
          str(fmis))

    # —— CLI 退出码映射（subprocess 实取 returncode，同 -I 调用形制）——
    cli = os.path.abspath(__file__)
    with tempfile.TemporaryDirectory(prefix="elg-selftest.") as td:
        for fname, expect in (("congruent-ok", 0), ("mismatch-2v8", 1),
                              ("face-unreadable", 2), ("no-such-fixture", 2)):
            r = subprocess.run([sys.executable, "-I", cli, "--fixture", fname],
                               capture_output=True, text=True, timeout=60)
            check("cli.fixture-%s-rc%d" % (fname, expect),
                  r.returncode == expect,
                  "rc=%d stderr=%s" % (r.returncode, r.stderr.strip()[:80]))
        r = subprocess.run([sys.executable, "-I", cli],
                           capture_output=True, text=True, timeout=60)
        check("cli.no-mode-rc2", r.returncode == 2)
        r = subprocess.run([sys.executable, "-I", cli, "--check",
                            os.path.join(td, "absent.json")],
                           capture_output=True, text=True, timeout=60)
        check("cli.check-absent-rc2-unprovable",
              r.returncode == 2 and "不可证" in r.stdout)
        p_ok = os.path.join(td, "ok.json")
        with open(p_ok, "w", encoding="utf-8") as fh:
            fh.write(_doc([_entry()]))
        r = subprocess.run([sys.executable, "-I", cli, "--check", p_ok],
                           capture_output=True, text=True, timeout=60)
        check("cli.check-green-rc0", r.returncode == 0
              and "verdict=clean" in r.stdout)
        p_red = os.path.join(td, "red.json")
        with open(p_red, "w", encoding="utf-8") as fh:
            fh.write(_doc([_entry(enforced_value=8)]))
        r = subprocess.run([sys.executable, "-I", cli, "--check", p_red],
                           capture_output=True, text=True, timeout=60)
        check("cli.check-red-rc1", r.returncode == 1
              and "verdict=red" in r.stdout)

    failed = [(n, d) for (n, ok, d) in checks if not ok]
    for (n, ok, d) in checks:
        print("  %s %s%s" % ("PASS" if ok else "FAIL", n,
                             (" — " + d[:120]) if (d and not ok) else ""))
    print("selftest %d/%d 过" % (len(checks) - len(failed), len(checks)))
    return 1 if failed else 0


# -------------------------------------------------------------------- main --
def print_findings(header, findings):
    print(header)
    for f in sorted(findings, key=lambda x: (SEV_ORDER.get(x["sev"], 9),
                                             x.get("tag", ""))):
        print("  " + f["msg"])
    verdict, rc = verdict_of(findings)
    print("verdict=%s rc=%d（%d 条：%d RED / %d UNPROVABLE / %d INFO）"
          % (verdict, rc, len(findings),
             sum(1 for x in findings if x["sev"] == "RED"),
             sum(1 for x in findings if x["sev"] == "UNPROVABLE"),
             sum(1 for x in findings if x["sev"] == "INFO")))
    return rc


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="enforced-limit 断言门（D-156/ESC-18 · 卡 #244）：限额/配额类"
                    "读数逐条断言 enforced 标志与限值在位且声明≡enforced"
                    "（宪章 SCH-4②「降规格的规格必须是 enforced limit」）；"
                    "一致⇒0／缺限失配坏形⇒1／face 实读不可得⇒2 fail-closed 禁派。")
    ap.add_argument("--selftest", action="store_true",
                    help="内嵌夹具全跑（三验收语义真跑；零网络零真实件读取）")
    ap.add_argument("--fixture", metavar="名",
                    help="单跑一个内嵌夹具（rc=该夹具裁决：congruent-ok→0，"
                         "mismatch-2v8/enforced-false/missing-*/bad-*/empty-*→1，"
                         "face-unreadable→2）")
    ap.add_argument("--check", metavar="读数件路径",
                    help="真查读数件 JSON（af.enforced-limit-reading/v1；"
                         "缺件/不可读 ⇒ 不可证 rc=2 fail-closed）")
    args = ap.parse_args(argv)

    modes = [bool(args.selftest), bool(args.fixture), bool(args.check)]
    if sum(modes) != 1:
        ap.print_usage()
        print("须且仅须选一模式：--selftest / --fixture 名 / --check 路径",
              file=sys.stderr)
        return 2
    if args.selftest:
        return run_selftest()
    if args.fixture:
        for name, desc, text, _rc, _c in FIXTURES:
            if name == args.fixture:
                print("夹具 %s：%s" % (name, desc))
                return print_findings("—— 裁决 ——",
                                      judge_payload(text,
                                                    "fixture:" + name))
        print("不识夹具名 %r（可用：%s）"
              % (args.fixture, " / ".join(f[0] for f in FIXTURES)),
              file=sys.stderr)
        return 2
    # --check（只读真查；件缺席/不可读 ⇒ 不可证 fail-closed 禁派）
    try:
        with open(args.check, "r", encoding="utf-8") as fh:
            text = fh.read()
    except (OSError, UnicodeDecodeError) as exc:
        return print_findings(
            "enforced-limit 断言门（D-156/#244）：读数件=%s" % args.check,
            [unprovable("<file>", "读数件不可读：%s（%s）——enforcement 读数证据"
                        "缺席即不可证，fail-closed 禁派不猜绿"
                        % (args.check, exc))])
    return print_findings(
        "enforced-limit 断言门（D-156/#244）：读数件=%s" % args.check,
        judge_payload(text, args.check))


if __name__ == "__main__":
    sys.exit(main())
