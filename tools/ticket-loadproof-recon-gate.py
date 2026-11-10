#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/ticket-loadproof-recon-gate.py — GPU 票据链第 5 腿（跑批演练读数）验收门（D-159 · ESC-22 · 卡 #277）。

【锚号】D-159（账本/阶段欠账台账.md 第 190 行）　【卡号】factory-os issue #277
  （wave-14 · w14-d159-ticket-loadproof-gate · 允许路径=本件单件）。

【为什么建本门（D-159 债本体）】
  GPU 票据链验收止于门口四腿（可达/无票拒/负向/查询），「票买到的东西真的被
  产出」腿缺失——完整负载卡执行（真实 start 需 catalog 完整 package spec：
  systemd 瞬时单元+cosh 用户+nft 规则）未演练（fg-readings.md:218 遗留项3；
  判据面=宪章资源域 v1 R-19 票据链）。本门把第 5 腿做成机器断言：对跑批演练
  读数件断言演练腿完整——一次真实负载完成读数（launcher start→unit 真启→
  产物指纹→收权）四腿齐且读数在档才算「负载级已证」；缺腿/读数缺失 ⇒ rc=1
  逐条点名；读数件缺席 ⇒ 票据面判「门口级在役、负载级未证」并明记（锚行原文）。

【判定语义（演练腿完整性断言；对读数件 JSON 的 legs 逐腿判）】
  在域腿=四条演练腿字面（launcher-start / unit-active / artifact-fingerprint /
  rights-revoked 之外的键 ⇒ INFO 域外跳过）。逐腿断言：
  · 缺腿（legs 内无该键）⇒ 红 rc=1 点名腿名（缺腿即演练不完整，fail-closed）；
  · 缺 ts 读数（缺席/非串/非 ISO8601 形）⇒ 红 rc=1 点名腿名+字段（读数缺失）；
  · launcher-start：缺 evidence（起跑读数，非空串）⇒ 红点名；
  · unit-active：state 实读非 'active'（systemd 词表字面，大小写敏感）⇒ 红
    点名——unit 真启不可证即未真启（fail-closed 不猜绿）；
  · artifact-fingerprint：缺 name（产物件名/路径）或缺 sha256（64 位小写十六
    进制产物指纹）⇒ 红点名——「票买到的东西」无指纹即无产出证明；
  · rights-revoked：缺 evidence（收权读数，非空串）⇒ 红点名；
  · 时序断言：四腿 ts 按演练箭头序非降（launcher-start ≤ unit-active ≤
    artifact-fingerprint ≤ rights-revoked）——倒序即读数不可信，红点名两腿。
  文件级：非 JSON/顶层非对象/schema 不符/ticket_id 缺席或空/legs 缺席非对象或
  空壳 ⇒ 红 rc=1（不猜绿）；读数件缺席/不可读 ⇒ 红 rc=1 并明记
  「门口级在役、负载级未证」（真实 start 前置=catalog 完整 package spec：
  systemd 瞬时单元+cosh 用户+nft 规则就绪——锚行原文，本门只判读数不代跑）。

【读数件契约（schema af.ticket-loadproof-reading/v1）】
  {"schema": "af.ticket-loadproof-reading/v1",
   "ticket_id": "w14-gpu-drill-01",
   "legs": {
     "launcher-start": {"ts": "2026-11-09T02:00:01Z",
                        "evidence": "launcher 起跑读数（start 行/受理实读引用）"},
     "unit-active": {"ts": "2026-11-09T02:00:03Z", "state": "active",
                     "evidence": "unit 真启实读（is-active 探针=active）"},
     "artifact-fingerprint": {"ts": "2026-11-09T02:00:20Z", "name": "out/result.bin",
                              "sha256": "（64 位小写十六进制产物指纹）"},
     "rights-revoked": {"ts": "2026-11-09T02:00:25Z",
                        "evidence": "收权实读（revoke 行引用/收权后再动作被拒实读）"}}}
  ts=ISO8601（Z/偏移/裸形均可，裸形按 UTC）；evidence/name=非空串；
  state='active' 字面；sha256=64 位小写十六进制。

【退出码】0=绿（四腿齐、读数在档、时序正 ⇒ 负载级已证）；1=红（读数件缺席/
  缺腿/读数缺失/时序倒序/文件坏形，逐条点名；红面恒附「门口级在役、负载级
  未证」明记行）；2=CLI 用法错（未选模式/夹具名不识——非数据裁决面）。

【用法】
  python3 -I tools/ticket-loadproof-recon-gate.py --selftest       # 内嵌夹具全跑（rc=0）
  python3 -I tools/ticket-loadproof-recon-gate.py --fixture <名>   # 单夹具（rc=该夹具裁决）
  python3 -I tools/ticket-loadproof-recon-gate.py --check [读数件路径]
                                                      # 真查跑批演练读数件
                                                      # （缺省 状态观测/gpu-ticket-drill-reading.json）
  夹具名：drill-complete-ok / missing-leg-unit-active / missing-reading-sha256 /
          unit-not-active / bad-order / empty-legs / bad-json / bad-schema /
          extra-leg-info / absent-file
  （三验收语义夹具：读数件缺席⇒rc=1 明记=absent-file；四腿齐⇒rc=0=drill-complete-ok；
   缺腿⇒rc=1 点名=missing-leg-unit-active；读数缺失⇒rc=1 点名=missing-reading-sha256。）

纪律：判官/门禁/判据件零改动（本件为 tools/ 新增件，不碰 all-gates.sh/
  gate-pins.list/点选面）；零网络、零凭据、零写入（--check 只读）；
  红不猜绿（读数件缺席/缺腿/读数缺失即红）；selftest 全部真跑不编造。
"""

import argparse
import datetime as dt
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_READING = os.path.join(ROOT, "状态观测", "gpu-ticket-drill-reading.json")
DEFAULT_READING_DISP = "状态观测/gpu-ticket-drill-reading.json"

SCHEMA = "af.ticket-loadproof-reading/v1"
GREEN, RED = 0, 1
SEV_ORDER = {"RED": 0, "INFO": 1}
UNPROVEN = "门口级在役、负载级未证"
PRECONDITION = ("真实 start 前置=catalog 完整 package spec"
                "（systemd 瞬时单元+cosh 用户+nft 规则）就绪")

# 演练腿全集（锚行箭头序=canonical 时序序；腿名即点名用字面）
DRILL_LEGS = ("launcher-start", "unit-active", "artifact-fingerprint", "rights-revoked")
LEG_CN = {"launcher-start": "launcher start（起跑）", "unit-active": "unit 真启",
          "artifact-fingerprint": "产物指纹", "rights-revoked": "收权"}

# 每腿 ts 之外的必需读数（字段, 形制）；形制 ∈ nonempty_str / active_literal / sha256_hex
LEG_REQUIRED = {
    "launcher-start": (("evidence", "nonempty_str"),),
    "unit-active": (("state", "active_literal"), ("evidence", "nonempty_str")),
    "artifact-fingerprint": (("name", "nonempty_str"), ("sha256", "sha256_hex")),
    "rights-revoked": (("evidence", "nonempty_str"),),
}

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def red(tag, msg):
    return {"sev": "RED", "tag": tag, "msg": "[RED] %s %s" % (tag, msg)}


def info(tag, msg):
    return {"sev": "INFO", "tag": tag, "msg": "[INFO] %s %s" % (tag, msg)}


def parse_ts(value):
    """ts 读数解析：ISO8601（Z/偏移/裸形，裸形按 UTC）⇒ tz-aware datetime；
    缺席/非串/不可解析 ⇒ None（调用方按读数缺失红，fail-closed）。"""
    if not isinstance(value, str) or not value.strip():
        return None
    s = value.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        t = dt.datetime.fromisoformat(s)
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return t


def judge_leg(leg, entry):
    """单腿判定（读数完整性）。返回 (findings, parsed_ts)。"""
    if not isinstance(entry, dict):
        return [red(leg, "腿读数非对象（%r）——读数件结构损坏，不猜绿" % (entry,))], None
    findings = []
    ts = parse_ts(entry.get("ts"))
    if ts is None:
        findings.append(red(leg, "缺时间戳读数 ts（实得 %r，须 ISO8601 形）——%s 腿"
                            "读数缺失，fail-closed" % (entry.get("ts"), LEG_CN[leg])))
    for field, kind in LEG_REQUIRED[leg]:
        v = entry.get(field)
        if kind == "nonempty_str":
            if not isinstance(v, str) or not v.strip():
                findings.append(red(leg, "读数缺失：%s（实得 %r，须非空串）——%s 腿"
                                    "读数不在档" % (field, v, LEG_CN[leg])))
        elif kind == "active_literal":
            if v != "active":
                findings.append(red(leg, "unit 真启读数 state 实得 %r 非 'active'——"
                                    "真启不可证即未真启，不猜绿（systemd 词表字面，"
                                    "大小写敏感）" % (v,)))
        elif kind == "sha256_hex":
            if not isinstance(v, str) or not SHA256_RE.match(v):
                findings.append(red(leg, "读数缺失/非法：sha256（实得 %r，须 64 位"
                                    "小写十六进制）——%s 无指纹即无产出证明"
                                    % (v, LEG_CN[leg])))
    return findings, ts


def judge_payload(text, origin):
    """读数件全文判定（文件级 fail-closed + 逐腿读数断言 + 时序断言）。返回 findings。"""
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
    findings = []
    ticket_id = data.get("ticket_id")
    if not isinstance(ticket_id, str) or not ticket_id.strip():
        findings.append(red("<file>", "ticket_id 缺席/空（实得 %r）——演练读数无票据"
                            "绑定即不可对账，不猜绿" % (ticket_id,)))
    legs = data.get("legs")
    if not isinstance(legs, dict):
        findings.append(red("<file>", "legs 缺席/非对象（实得 %s）——无演练腿可断言"
                            % (type(legs).__name__,)))
        return findings
    if not legs:
        findings.extend(red(leg, "缺腿：%s（%s）——演练腿完整四缺四，不猜绿"
                            % (leg, LEG_CN[leg])) for leg in DRILL_LEGS)
        return findings

    parsed = {}
    for leg in DRILL_LEGS:
        if leg not in legs:
            findings.append(red(leg, "缺腿：%s（%s）——演练腿不完整，fail-closed"
                                % (leg, LEG_CN[leg])))
            continue
        leg_findings, ts = judge_leg(leg, legs[leg])
        findings.extend(leg_findings)
        parsed[leg] = ts
    for key in legs:
        if key not in DRILL_LEGS:
            findings.append(info(key, "域外演练腿（非四腿字面）——跳过不判"))

    # 时序断言：演练箭头序非降（相邻两腿均可解析才比；不可解析已各自红）
    for prev, nxt in zip(DRILL_LEGS, DRILL_LEGS[1:]):
        if parsed.get(prev) is not None and parsed.get(nxt) is not None:
            if parsed[nxt] < parsed[prev]:
                findings.append(red(nxt, "时序倒序：%s 腿 ts 早于 %s 腿——与演练箭头"
                                    "序（launcher start→unit 真启→产物指纹→收权）"
                                    "不符，读数不可信" % (nxt, prev)))
    return findings


def judge_path(path, disp):
    """--check 面：读数件缺席/不可读 ⇒ 红并明记「门口级在役、负载级未证」（锚行原文）。"""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except (OSError, UnicodeDecodeError) as exc:
        return [red("<file>", "跑批演练读数件缺席/不可读：%s（%s）——票据面判："
                    "%s；%s" % (disp, exc.__class__.__name__, UNPROVEN,
                                PRECONDITION))]
    return judge_payload(text, disp)


def verdict_of(findings):
    """二值收敛：任一 RED ⇒ (red, 1)；否则绿 ⇒ (clean, 0)。"""
    if any(f["sev"] == "RED" for f in findings):
        return "red", RED
    return "clean", GREEN


# ---------------------------------------------------------------- 夹具与自测 --
def _leg(leg, **kw):
    base = {
        "launcher-start": {"ts": "2026-11-09T02:00:01Z",
                           "evidence": "fixture：start 行受理实读（rc=0，句柄起跑）"},
        "unit-active": {"ts": "2026-11-09T02:00:03Z", "state": "active",
                        "evidence": "fixture：is-active 探针实读=active"},
        "artifact-fingerprint": {"ts": "2026-11-09T02:00:20Z",
                                 "name": "out/gpu-readback.txt",
                                 "sha256": "a" * 64},
        "rights-revoked": {"ts": "2026-11-09T02:00:25Z",
                           "evidence": "fixture：revoke 行在档+收权后再动作被拒实读"},
    }[leg]
    base.update(kw)
    return base


def _doc(legs, **kw):
    body = {"schema": SCHEMA, "ticket_id": "w14-gpu-drill-fixture-01", "legs": legs}
    body.update(kw)
    return json.dumps(body, ensure_ascii=False)


def _legs():
    """四腿齐、读数在档、时序正的基准读数（正例基座）。"""
    return {leg: _leg(leg) for leg in DRILL_LEGS}


_ABSENT_PATH = os.path.join(os.sep, "nonexistent-fixture-277",
                            "gpu-ticket-drill-reading.json")

def _legs_drop(leg_to_drop):
    """四腿齐读数摘除一整腿（缺腿负例用）。"""
    return {leg: _leg(leg) for leg in DRILL_LEGS if leg != leg_to_drop}


# （名，描述，读数件文本（None=缺席面：走 judge_path 真开不存在路径），
#   期望 rc，红行须含串）
FIXTURES = [
    ("drill-complete-ok", "四腿齐、读数在档、时序正 ⇒ 负载级已证（rc=0）",
     _doc(_legs()), GREEN, None),
    ("missing-leg-unit-active", "缺腿负例：unit-active 整腿缺席 ⇒ rc=1 点名腿名",
     _doc(_legs_drop("unit-active")), RED, "缺腿：unit-active"),
    ("missing-reading-sha256", "读数缺失负例：产物指纹腿缺 sha256 ⇒ rc=1 点名腿+字段",
     _doc({**_legs(), "artifact-fingerprint":
           {k: v for k, v in _leg("artifact-fingerprint").items()
            if k != "sha256"}}),
     RED, "读数缺失/非法：sha256"),
    ("unit-not-active", "unit 未真启负例：state=failed ⇒ rc=1（真启不可证即未真启）",
     _doc({**_legs(), "unit-active": _leg("unit-active", state="failed")}),
     RED, "非 'active'"),
    ("bad-order", "时序倒序负例：收权 ts 早于起跑 ⇒ rc=1 点名两腿",
     _doc({**_legs(), "rights-revoked":
           _leg("rights-revoked", ts="2026-11-09T01:59:59Z")}),
     RED, "时序倒序"),
    ("empty-legs", "空壳负例：legs={} 四缺四 ⇒ rc=1 四腿逐条点名",
     _doc({}), RED, "缺腿：launcher-start"),
    ("bad-json", "坏形（非 JSON）⇒ fail-closed 红",
     "{not json", RED, "非 JSON"),
    ("bad-schema", "schema 不符 ⇒ 红",
     json.dumps({"schema": "af.other/v9", "ticket_id": "x",
                 "legs": _legs()}), RED, "schema"),
    ("extra-leg-info", "域外腿（非四腿字面）INFO 跳过 + 四腿齐 ⇒ rc=0",
     _doc({**_legs(), "telemetry-extra": {"ts": "2026-11-09T02:00:26Z"}}),
     GREEN, None),
    ("absent-file", "读数件缺席面：真开不存在路径 ⇒ rc=1 明记「%s」" % UNPROVEN,
     None, RED, UNPROVEN),
]


def _run_fixture(name):
    """单夹具真跑（text=None ⇒ 走缺席面 judge_path）。返回 findings。"""
    for fname, _desc, text, _rc, _c in FIXTURES:
        if fname != name:
            continue
        if text is None:
            return judge_path(_ABSENT_PATH, "fixture:absent-file")
        return judge_payload(text, "fixture:" + name)
    return None


def run_selftest():
    """内嵌夹具自测：三验收语义各至少一夹具真跑 + 边界/形制单元断言，
    零网络零仓读（缺席面走不存在路径真开分支）。"""
    checks = []

    def check(name, cond, detail=""):
        checks.append((name, bool(cond), detail))

    for name, desc, text, expect_rc, contains in FIXTURES:
        findings = (_run_fixture(name))
        verdict, rc = verdict_of(findings)
        check("fixture.%s" % name, rc == expect_rc,
              "desc=%s verdict=%s（期望 %d）findings=%s"
              % (desc, verdict, expect_rc, [f["msg"][:80] for f in findings]))
        if contains is not None:
            check("fixture.%s.msg" % name,
                  any(f["sev"] == "RED" and contains in f["msg"] for f in findings),
                  "红行未含 %r：%s" % (contains, [f["msg"][:80] for f in findings]))

    # —— 单元断言（judge_leg / judge_payload / parse_ts 纯函数面）——
    # ts 形制：Z/偏移/裸形/小数秒可析；非串/垃圾串/缺席 ⇒ None（读数缺失）
    check("unit.ts-z-form", parse_ts("2026-11-09T02:00:01Z") is not None)
    check("unit.ts-offset-form", parse_ts("2026-11-09T10:00:01+08:00") is not None)
    check("unit.ts-naive-form", parse_ts("2026-11-09T02:00:01") is not None)
    check("unit.ts-frac-form", parse_ts("2026-11-09T02:00:01.512Z") is not None)
    for bad in ("not-a-ts", "", "  ", 123, None):
        check("unit.ts-bad-%r" % (bad,), parse_ts(bad) is None)
    # sha256 形制：64 小写十六进制过；大写/短长/非串红
    check("unit.sha256-ok", SHA256_RE.match("f" * 64) is not None)
    for bad in ("F" * 64, "a" * 63, "a" * 65, "z" * 64, 42, None):
        check("unit.sha256-bad-%r" % (bad,), not isinstance(bad, str)
              or SHA256_RE.match(bad) is None)
    # state 词表：字面 'active' 过；大小写/近义词/缺席红
    f_ok, _ = judge_leg("unit-active", _leg("unit-active"))
    check("unit.state-active-green", verdict_of(f_ok) == ("clean", GREEN), str(f_ok))
    for bad_state in ("Active", "ACTIVE", "inactive", "failed", "activating", ""):
        f_bad, _ = judge_leg("unit-active", _leg("unit-active", state=bad_state))
        check("unit.state-bad-%r" % (bad_state,),
              verdict_of(f_bad) == ("red", RED), str(f_bad))
    # 各腿读数缺失族：evidence/name/ts 摘除 ⇒ 各自红点名
    for leg in DRILL_LEGS:
        for field, _kind in (("ts", None),) + LEG_REQUIRED[leg]:
            entry = {k: v for k, v in _leg(leg).items() if k != field}
            fl, _ = judge_leg(leg, entry)
            check("unit.leg-%s-missing-%s" % (leg, field),
                  verdict_of(fl) == ("red", RED)
                  and any(field in x["msg"] for x in fl if x["sev"] == "RED"),
                  str(fl))
    # evidence/name 空串与非串同红（非空串形制）
    fl, _ = judge_leg("launcher-start", _leg("launcher-start", evidence="  "))
    check("unit.evidence-blank-red", verdict_of(fl) == ("red", RED))
    fl, _ = judge_leg("artifact-fingerprint", _leg("artifact-fingerprint", name=7))
    check("unit.name-nonstr-red", verdict_of(fl) == ("red", RED))
    # 腿读数非对象 ⇒ 红
    fl, _ = judge_leg("rights-revoked", "nope")
    check("unit.leg-nondict-red", verdict_of(fl) == ("red", RED))
    # 时序：相等 ts 非降过；倒序红（相邻对逐对判）
    eq = _doc({"launcher-start": _leg("launcher-start", ts="2026-11-09T02:00:01Z"),
               "unit-active": _leg("unit-active", ts="2026-11-09T02:00:01Z"),
               "artifact-fingerprint": _leg("artifact-fingerprint",
                                            ts="2026-11-09T02:00:02Z"),
               "rights-revoked": _leg("rights-revoked", ts="2026-11-09T02:00:02Z")})
    check("unit.order-equal-green", verdict_of(judge_payload(eq, "<t>"))
          == ("clean", GREEN))
    rev = _doc({"launcher-start": _leg("launcher-start", ts="2026-11-09T02:00:05Z"),
                "unit-active": _leg("unit-active", ts="2026-11-09T02:00:03Z"),
                "artifact-fingerprint": _leg("artifact-fingerprint"),
                "rights-revoked": _leg("rights-revoked")})
    check("unit.order-reversed-red",
          verdict_of(judge_payload(rev, "<t>")) == ("red", RED))
    # 双缺（两腿同缺）⇒ 两条红各自点名
    two_drop = {leg: _leg(leg) for leg in DRILL_LEGS
                if leg not in ("unit-active", "rights-revoked")}
    two = judge_payload(_doc(two_drop), "<t>")
    check("unit.two-missing-legs-named",
          len([x for x in two if x["sev"] == "RED"]) == 2
          and any("unit-active" in x["msg"] for x in two if x["sev"] == "RED")
          and any("rights-revoked" in x["msg"] for x in two if x["sev"] == "RED"),
          str(two))
    # ticket_id 缺席/空 ⇒ 红
    check("unit.ticket-id-missing-red",
          verdict_of(judge_payload(_doc(_legs(), ticket_id=""), "<t>"))
          == ("red", RED))
    # legs 缺席（键不在）⇒ 红；顶层非对象 ⇒ 红
    check("unit.legs-absent-red",
          verdict_of(judge_payload(json.dumps(
              {"schema": SCHEMA, "ticket_id": "x"}), "<t>")) == ("red", RED))
    check("unit.top-list-red",
          verdict_of(judge_payload(json.dumps([_leg("launcher-start")]), "<t>"))
          == ("red", RED))
    # 域外腿仅 INFO 不红（绿裁决）
    fout = judge_payload(_doc({**_legs(), "warmup-poll": {"ts": "x"}}), "<t>")
    check("unit.extra-leg-info-only",
          verdict_of(fout) == ("clean", GREEN)
          and any(x["sev"] == "INFO" and "域外演练腿" in x["msg"] for x in fout),
          str(fout))

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
    print("verdict=%s rc=%d（%d 条：%d RED / %d INFO）"
          % (verdict, rc, len(findings),
             sum(1 for x in findings if x["sev"] == "RED"),
             sum(1 for x in findings if x["sev"] == "INFO")))
    if rc == RED:
        print("票据面判：%s（第 5 腿（跑批演练）不完整——逐条点名见上）" % UNPROVEN)
    else:
        print("负载级已证：第 5 腿（跑批演练）四腿读数完整"
              "（launcher start→unit 真启→产物指纹→收权）")
    return rc


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="GPU 票据链第 5 腿（跑批演练读数）验收门：对跑批演练读数件断言"
                    "演练腿完整（launcher start→unit 真启→产物指纹→收权），"
                    "缺腿/读数缺失⇒rc=1 点名；读数件缺席⇒明记"
                    "「门口级在役、负载级未证」（D-159 · ESC-22 · 卡 #277）。")
    ap.add_argument("--selftest", action="store_true",
                    help="内嵌夹具全跑（三验收语义真跑；零网络零仓读）")
    ap.add_argument("--fixture", metavar="名",
                    help="单跑一个内嵌夹具（rc=该夹具裁决：drill-complete-ok→0，"
                         "missing-leg-unit-active/missing-reading-sha256/"
                         "absent-file→1）")
    ap.add_argument("--check", metavar="读数件路径", nargs="?",
                    const=DEFAULT_READING, default=None,
                    help="真查跑批演练读数件 JSON（af.ticket-loadproof-reading/v1；"
                         "缺省 %s）" % DEFAULT_READING_DISP)
    args = ap.parse_args(argv)

    modes = [bool(args.selftest), bool(args.fixture), args.check is not None]
    if sum(modes) != 1:
        ap.print_usage()
        print("须且仅须选一模式：--selftest / --fixture 名 / --check [路径]",
              file=sys.stderr)
        return 2
    if args.selftest:
        return run_selftest()
    if args.fixture:
        findings = _run_fixture(args.fixture)
        if findings is None:
            print("不识夹具名 %r（可用：%s）"
                  % (args.fixture, " / ".join(f[0] for f in FIXTURES)),
                  file=sys.stderr)
            return 2
        print("夹具 %s：%s" % (args.fixture,
                              dict((f[0], f[1]) for f in FIXTURES)[args.fixture]))
        return print_findings("—— 裁决 ——", findings)
    # --check（只读真查；缺席/不可读 ⇒ 红并明记，不猜绿）
    disp = (DEFAULT_READING_DISP + "（默认）"
            if args.check == DEFAULT_READING else args.check)
    return print_findings(
        "GPU 票据链跑批演练验收门（D-159/#277）：读数件=%s" % disp,
        judge_path(args.check, disp))


if __name__ == "__main__":
    sys.exit(main())
