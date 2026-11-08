#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/failure-rate-recon-gate.py — 失败率/重试率聚合口径门（D-161 · ESC-23 · 卡 #234）。

【锚号】D-161（账本/阶段欠账台账.md 第 191 行）　【卡号】factory-os issue #234
  （wave-13 · w13-d161-failure-rate-gate · 允许路径=本件单件）。

【为什么建本门（D-161 债本体）】
  跨平台腿判过（往返耗时实测+兜底路径实测）但失败率统计多为单跑读数——损耗量化
  判据「有量化机制且已实跑」n=1 即可满足，单跑与 n≥20 聚合在判据上不可分辨，
  平台失败率/重试率长期无分母（ESC-23 新门设计栏）。本门把聚合口径做成机器断言：
  失败率/重试率读数必须标注样本量 n 与统计窗口，n 不足阈值即「单跑级」，禁当
  聚合结论/容量规划输入。

【判定语义（n 与窗口断言；对读数件 JSON 的 failure/retry 计数逐条判）】
  在域条目=metric 含 failure/retry 口径词的读数（其余 metric ⇒ INFO 域外跳过；
  metric 缺席 ⇒ 口径不可判，红——fail-closed 不猜绿）。逐条断言：
  · 缺样本量 n 标注（或 n 非 ≥1 整数）⇒ 红 rc=1（分母无从对账，fail-closed）；
  · 缺统计窗口标注（window 缺席/空/非串）⇒ 红 rc=1（口径不可证，fail-closed）；
  · n=1（一般化：n < AGG_MIN_N=20）⇒ 红点名「单跑级读数」——禁当聚合结论/
    容量规划输入（D-161 判据明文：n<20 ⇒ 标「单跑级」不得作容量规划输入）；
  · n≥20 且窗口齐 ⇒ 该条聚合口径通过。
  文件级：非 JSON/顶层非对象/schema 不符/readings 空壳 ⇒ 红 rc=1（不猜绿）。

【读数件契约（schema af.failure-rate-reading/v1）】
  {"schema": "af.failure-rate-reading/v1",
   "readings": [{"name": "...", "metric": "failure_rate|retry_rate|…",
                 "value": 0.02, "n": 42,
                 "window": "2026-11-01T00:00Z/2026-11-07T24:00Z"}, …]}
  n=样本量（int ≥1）；window=统计窗口标注（非空串，形制自由但不得缺席）。

【退出码】0=绿（全部在域读数 n≥20 且窗口齐）；1=红（单跑级/缺 n/缺窗口/
  文件坏形，逐条点名——本门按卡面验收口径二值出红：三语义负例均 rc=1）；
  2=CLI 用法错（未选模式/夹具名不识——非数据裁决面）。

【用法】
  python3 -I tools/failure-rate-recon-gate.py --selftest        # 内嵌夹具全跑（rc=0）
  python3 -I tools/failure-rate-recon-gate.py --fixture <名>    # 单夹具（rc=该夹具裁决）
  python3 -I tools/failure-rate-recon-gate.py --check <读数件路径>   # 真查现役读数件
  夹具名：agg-n20-ok / single-run-n1 / single-run-n19 / missing-n /
          missing-window / empty-readings / bad-json / out-of-scope-metric
  （三验收语义夹具：n=1 单跑级负例=single-run-n1（rc=1）；n≥20 通过=agg-n20-ok
   （rc=0，含阈值含 20 边界）；缺 n/缺窗口⇒rc=1=missing-n / missing-window。）

纪律：判官/门禁/判据件零改动（本件为 tools/ 新增件，不碰 all-gates.sh/
  gate-pins.list/点选面）；零网络、零凭据、零写入（--check 只读）；
  红不猜绿（缺标注即红）；selftest 全部真跑不编造。
"""

import argparse
import json
import sys

SCHEMA = "af.failure-rate-reading/v1"
AGG_MIN_N = 20            # 聚合口径样本量阈值（D-161 判据：n<20 ⇒ 单跑级）
GREEN, RED = 0, 1
SEV_ORDER = {"RED": 0, "INFO": 1}


def red(tag, msg):
    return {"sev": "RED", "tag": tag, "msg": "[RED] %s %s" % (tag, msg)}


def info(tag, msg):
    return {"sev": "INFO", "tag": tag, "msg": "[INFO] %s %s" % (tag, msg)}


def is_in_scope(metric):
    """失败/重试口径判定：metric 含 failure/retry ⇒ True；其他非空串 ⇒ False；
    缺席/非串/空 ⇒ None（口径不可判，调用方按 fail-closed 处理）。"""
    if not isinstance(metric, str) or not metric.strip():
        return None
    low = metric.lower()
    return ("failure" in low) or ("retry" in low)


def judge_entry(entry, idx):
    """单条读数判定（n 与窗口双断言）。返回 findings（sev ∈ RED/INFO）。"""
    if not isinstance(entry, dict):
        return [red("#%d" % idx, "读数条目非对象（%r）——读数件结构损坏，不猜绿"
                    % (entry,))]
    name = entry.get("name")
    tag = name.strip() if isinstance(name, str) and name.strip() else "#%d" % idx
    scope = is_in_scope(entry.get("metric"))
    if scope is None:
        return [red(tag, "metric 缺席/非串（实得 %r）——是否失败/重试口径读数无从"
                    "排除，fail-closed 红" % (entry.get("metric"),))]
    if not scope:
        return [info(tag, "metric=%s 非失败/重试口径——域外跳过不判"
                     % (entry.get("metric"),))]

    findings = []
    # 断言一：样本量 n 标注
    if "n" not in entry:
        findings.append(red(tag, "缺样本量 n 标注（fail-closed）——失败率/重试率"
                            "无分母即无口径，D-161 判据不可证"))
    else:
        n = entry.get("n")
        if isinstance(n, bool) or not isinstance(n, int) or n < 1:
            findings.append(red(tag, "样本量 n 标注非法（实得 %r）——须为 ≥1 整数"
                                % (n,)))
        elif n < AGG_MIN_N:
            findings.append(red(tag, "单跑级读数（n=%d < %d）——样本量不足聚合"
                                "阈值，禁当聚合结论/容量规划输入（D-161：n<20 ⇒ "
                                "标「单跑级」）" % (n, AGG_MIN_N)))
    # 断言二：统计窗口标注（与断言一独立，缺一各自点名）
    w = entry.get("window")
    if not isinstance(w, str) or not w.strip():
        findings.append(red(tag, "缺统计窗口标注（实得 %r）——窗口缺席即读数口径"
                            "不可证，fail-closed" % (w,)))
    return findings


def judge_payload(text, origin):
    """读数件全文判定（文件级 fail-closed + 逐条 n/窗口断言）。返回 findings。"""
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
                    "口径契约不可证，不猜绿" % (origin, SCHEMA, data.get("schema")))]
    readings = data.get("readings")
    if not isinstance(readings, list) or not readings:
        return [red("<file>", "读数件 %s readings 缺席/空（空壳读数件）——无任何"
                    "读数可对账即无聚合口径证明，不猜绿" % (origin,))]
    findings = []
    for idx, entry in enumerate(readings):
        findings.extend(judge_entry(entry, idx))
    return findings


def verdict_of(findings):
    """二值收敛：任一 RED ⇒ (red, 1)；否则绿 ⇒ (clean, 0)。"""
    if any(f["sev"] == "RED" for f in findings):
        return "red", RED
    return "clean", GREEN


# ---------------------------------------------------------------- 夹具与自测 --
def _reading(**kw):
    base = {"name": "platform-leg-failure-rate", "metric": "failure_rate",
            "value": 0.03, "n": 137,
            "window": "2026-11-01T00:00Z/2026-11-07T24:00Z"}
    base.update(kw)
    return base


def _doc(readings):
    return json.dumps({"schema": SCHEMA, "readings": readings},
                      ensure_ascii=False)


# （名，描述，读数件文本，期望 rc，红行须含串）
FIXTURES = [
    ("agg-n20-ok", "n≥20 聚合通过（含阈值含 20 边界：n=137 与 n=20，窗口齐）",
     _doc([_reading(n=137),
           _reading(name="platform-retry-rate", metric="retry_rate",
                    value=0.09, n=20)]),
     GREEN, None),
    ("single-run-n1", "n=1 单跑级负例——禁当聚合结论（D-161 本债实例形态）",
     _doc([_reading(n=1, value=1.0,
                    window="2026-11-08T09:00Z/2026-11-08T09:05Z")]),
     RED, "单跑级"),
    ("single-run-n19", "n=19<20 边界负例——阈值判 <20 非 ≤1（一般化单跑级）",
     _doc([_reading(n=19)]),
     RED, "单跑级"),
    ("missing-n", "缺样本量 n ⇒ fail-closed 红",
     _doc([{"name": "platform-leg-failure-rate", "metric": "failure_rate",
            "value": 0.04,
            "window": "2026-11-01T00:00Z/2026-11-07T24:00Z"}]),
     RED, "样本量"),
    ("missing-window", "缺统计窗口标注 ⇒ fail-closed 红",
     _doc([{k: v for k, v in _reading(n=42).items() if k != "window"}]),
     RED, "窗口"),
    ("empty-readings", "空壳读数件（readings 空）⇒ 不猜绿",
     json.dumps({"schema": SCHEMA, "readings": []}),
     RED, "空壳"),
    ("bad-json", "坏形（非 JSON）⇒ fail-closed 红",
     "{not json",
     RED, "非 JSON"),
    ("out-of-scope-metric", "非失败/重试口径（p50_latency）域外 INFO 跳过 + 在域绿",
     _doc([{"name": "leg-p50-latency", "metric": "p50_latency_ms",
            "value": 812.0, "n": 3, "window": "adhoc"},
           _reading(n=64)]),
     GREEN, None),
]


def run_selftest():
    """内嵌夹具自测：三验收语义各至少一夹具真跑 + 边界/形制单元断言，
    零网络零盘读（夹具全内联）。"""
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
                  any(f["sev"] == "RED" and contains in f["msg"] for f in findings),
                  "红行未含 %r：%s" % (contains, [f["msg"][:80] for f in findings]))

    # —— 单元断言（judge_entry/judge_payload 纯函数面）——
    w = "2026-11-01T00:00Z/2026-11-07T24:00Z"
    # n 阈值边界：n=20 恰过、n=19 恰红（已在夹具，此处直调钉函数面）
    check("unit.n20-exact-green",
          verdict_of(judge_entry(_reading(n=20), 0)) == ("clean", GREEN))
    check("unit.n19-red",
          verdict_of(judge_entry(_reading(n=19), 0)) == ("red", RED))
    # n=1 单跑级语义串在位（卡面验收：n=1→rc=1 单跑级标注）
    f1 = judge_entry(_reading(n=1), 0)
    check("unit.n1-single-run-msg",
          any("单跑级" in x["msg"] and "n=1" in x["msg"] for x in f1), str(f1))
    # n 标注非法族：字符串/布尔/0/负数
    for bad_n in ("20", True, 0, -3):
        check("unit.bad-n-%r" % (bad_n,),
              verdict_of(judge_entry(_reading(n=bad_n), 0)) == ("red", RED))
    # window 形制：空串/非串/缺席 ⇒ 红
    for bad_w in ("", "   ", 123, None):
        check("unit.bad-window-%r" % (bad_w,),
              verdict_of(judge_entry(_reading(window=bad_w), 0)) == ("red", RED))
    e = _reading(); e.pop("window")
    check("unit.window-absent-red",
          verdict_of(judge_entry(e, 0)) == ("red", RED))
    # 双缺（n 与 window 同时缺）⇒ 两条红各自点名
    e = _reading(); e.pop("n"); e.pop("window")
    fboth = judge_entry(e, 0)
    check("unit.both-missing-two-reds",
          len([x for x in fboth if x["sev"] == "RED"]) == 2, str(fboth))
    # metric 缺席 ⇒ 口径不可判红（fail-closed）；域外 metric ⇒ 仅 INFO 不红
    check("unit.metric-absent-red",
          verdict_of(judge_entry({"name": "x", "n": 40, "window": w}, 0))
          == ("red", RED))
    fout = judge_entry(_reading(metric="p99_latency_ms"), 0)
    check("unit.out-of-scope-info",
          verdict_of(fout) == ("clean", GREEN)
          and any(x["sev"] == "INFO" and "域外跳过" in x["msg"] for x in fout),
          str(fout))
    # 非对象条目 ⇒ 红
    check("unit.non-dict-entry-red",
          verdict_of(judge_entry("nope", 0)) == ("red", RED))
    # 文件级：schema 不符 / 顶层非对象 ⇒ 红（bad-json/空壳已在夹具面）
    check("unit.bad-schema-red",
          verdict_of(judge_payload(json.dumps({"schema": "other/v9",
                                               "readings": [_reading()]}),
                                   "<t>")) == ("red", RED))
    check("unit.top-list-red",
          verdict_of(judge_payload(json.dumps([_reading()]), "<t>"))
          == ("red", RED))
    # 大小写口径：FailureRate/RETRY_RATE 同判在域
    check("unit.caliber-case",
          is_in_scope("FailureRate") is True
          and is_in_scope("RETRY_RATE") is True
          and is_in_scope("rtt_ms") is False
          and is_in_scope("") is None and is_in_scope(7) is None)

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
    return rc


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="失败率/重试率聚合口径门：读数件 failure/retry 计数的样本量 n"
                    " 与统计窗口标注断言（D-161 · ESC-23 · 卡 #234）；"
                    "n<20⇒单跑级红，缺 n/缺窗口⇒fail-closed 红。")
    ap.add_argument("--selftest", action="store_true",
                    help="内嵌夹具全跑（三验收语义真跑；零网络零盘读）")
    ap.add_argument("--fixture", metavar="名",
                    help="单跑一个内嵌夹具（rc=该夹具裁决：agg-n20-ok→0，"
                         "single-run-n1/missing-n/missing-window→1）")
    ap.add_argument("--check", metavar="读数件路径",
                    help="真查读数件 JSON（af.failure-rate-reading/v1）")
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
    # --check（只读真查；缺件/不可读 ⇒ fail-closed 红）
    try:
        with open(args.check, "r", encoding="utf-8") as fh:
            text = fh.read()
    except (OSError, UnicodeDecodeError) as exc:
        return print_findings(
            "失败率/重试率聚合口径门（D-161/#234）：读数件=%s" % args.check,
            [red("<file>", "读数件不可读：%s（%s）——fail-closed 不猜绿"
                 % (args.check, exc))])
    return print_findings(
        "失败率/重试率聚合口径门（D-161/#234）：读数件=%s" % args.check,
        judge_payload(text, args.check))


if __name__ == "__main__":
    sys.exit(main())
