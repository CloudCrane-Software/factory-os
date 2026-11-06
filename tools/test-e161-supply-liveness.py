#!/usr/bin/env python3
"""test-e161-supply-liveness.py — RT-E161 供给活性对账门回归（四态负正控，2026-11-06）

背景（判据源，逐字溯源）：
  · ask 判据（RT-E161 施工 ask，2026-11-06）：供给活性对账门=对 arbitrate/distill
    两腿判『轮预算在跑 ∧ 连续 N 轮零新产出』⇒ 活性红，区分「真无料」与「pipeline 死」
    ——**跳过计数增长=在干活=绿；产出与跳过双零=疑似死=红**（括号内为操作定义；
    ask 公式中「∧跳过>0」按括号文执行=红须双零，字面读法与括号文直接矛盾，不采，
    已在设计件 30-工件/RT-E161轨-20261106/ 记录待部署窗复核）。
  · 提案：30-工件/KB清偿轨-20261105/out/rt-e161-proposal.md §二（N=3 依据：
    约 6h 无消化即告警；台账拦截机制②「供给活性监测——存量在板不得替代」，
    红队终局轮-20261101/逃逸问题台账.md:1321）。
被测件：tools/factory-scheduler.py 的 _supply_activity_gate（RT-E161 门函数）。
  取件顺序：正本已含门（部署后）→ 测正本；否则测 .rt161wip shadow——部署窗两侧
  都有效，两侧都不含门即前置不满足（绝不静默跳过）。
  环境零写生产：FS_STATE/FS_LOG/FS_CHANGELOG/FS_SUPPLY_ACTIVITY 全改道 scratch；
  观测面缺省派生 dirname(STATE)，改 FS_STATE 即连带改道（双保险）。

四态（负正控，ask ④）：
  F1 健康产出（正控绿）：生成>0 → 绿、连击清零；观测面 supply-activity.json 双写
     且与 st["supply_activity"] 逐键一致；
  F2 健康跳过（正控绿）：生成0/跳过 175→176→177 连续 N 轮 → 恒绿（跳过计数增长=
     在干活；RT-E161 现势「arb 生成0/跳过175」即此合法形态，不得误红）；
  F3 双零疑似死（正控红）：生成0/跳过0 连续 N 轮 → 第 N 轮翻红+变更日志点名一次，
     第 N+1 轮仍红但**不重复告警**（一次性）；同轮另一腿跳过>0 独立判绿（两腿独立）；
  F4 N 轮窗口边界（负控）：双零连续 N-1 轮 → 不红（绿·观察中，连击=N-1）——
     红恰好落在第 N 轮，前一轮必须仍绿；另负控：无读数轮（JSON 不可判/顶层 ok=
     false）不计入窗口且连击清零（连击 2→清零→再 2 轮仍不红）；另正控：腿缺席
     （summary 无该 kind 键=kind 收缩嫌疑）按双零证据计入，第 N 轮红且 note 点名缺席。
  W  接线断言（防集成点被静默摘除）：cmd 含 --kind all（kind 全集，RT-E161 根因
     回归线）；_quality_cards_supply 内确有 _supply_activity_gate 调用；tamper 锚行
     「out, ok = _qc_leg_out(r2.stdout, r2.returncode)」逐字在位（test-qc-leg-truth-
     gate 源码锚）；观测面路径派生自 dirname(STATE)；DRY 轮不落观测面（只探不写）。

用法：python3 tools/test-e161-supply-liveness.py
退出码：0 全过；1 断言失败；2 前置不满足。
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
from importlib.machinery import SourceFileLoader

WS = os.path.expanduser("~/workspace/agent黑灯工厂")
TOOLS = os.path.join(WS, "tools")
CANON = os.path.join(TOOLS, "factory-scheduler.py")
WIP = os.path.join(TOOLS, "factory-scheduler.py.rt161wip")
GATE_SYM = "_supply_activity_gate"

EXIT_OK, EXIT_FAIL, EXIT_ENV = 0, 1, 2

N = 3  # 与门缺省 SA_GATE_N 同值（夹具环境不设 FS_SA_GATE_N，走缺省=判据钉值）


class Fail(Exception):
    pass


def check(cond, msg):
    if not cond:
        raise Fail(msg)


def pick_target():
    """正本优先（部署后自动换测正本），其次 shadow；都不含门=前置不满足。"""
    for path, how in ((CANON, "正本"), (WIP, "shadow.rt161wip")):
        try:
            if os.path.isfile(path) and GATE_SYM in open(path, encoding="utf-8").read():
                return path, how
        except OSError:
            continue
    print("前置不满足：%s 与 %s 均不含 %s（门未落码？）" % (CANON, WIP, GATE_SYM))
    return None, None


def load_sched(tmp, tag):
    """带夹具环境载入被测件（FS_STATE/LOG/CHANGELOG/SUPPLY_ACTIVITY 全改道 scratch）。"""
    env = {
        "FS_STATE": os.path.join(tmp, "state.json"),
        "FS_LOG": os.path.join(tmp, "fs.log"),
        "FS_CHANGELOG": os.path.join(tmp, "changelog.md"),
        "FS_SUPPLY_ACTIVITY": os.path.join(tmp, "supply-activity.json"),
        "FS_STOP": os.path.join(tmp, "stop-unused"),
        "FS_QUALITY_CARDS_LOCK": os.path.join(tmp, "qc.lock"),
    }
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    # .rt161wip 后缀 importlib 不识别 → 显式 SourceFileLoader（test-qc-leg-truth-gate 同款）
    loader = SourceFileLoader("e161_probe_%s_%d" % (tag, os.getpid()), TARGET[0])
    spec = importlib.util.spec_from_loader(loader.name, loader)
    m = importlib.util.module_from_spec(spec)
    loader.exec_module(m)
    return m, env, old


def restore_env(env, old):
    for k, v in old.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def qc_doc(arb=None, dist=None, omit=(), ok=True):
    """造一份与 quality-cards.py 打印形状同构的 stdout（indent=1 多行 JSON，
    顶层「{」独占一行——_qc_summary_doc 的扫描锚）。omit 里的 kind 不进 summary
    （腿缺席夹具）。verify 腿照现状带零计数（all 轮三腿齐是生产常态）。"""
    summ = {}
    if "verify" not in omit:
        summ["verify"] = {"generated": 0, "skipped_existing": 0, "failed": 0}
    if arb is not None and "arbitrate" not in omit:
        summ["arbitrate"] = {"generated": arb[0], "skipped_existing": arb[1],
                             "failed": arb[2]}
    if dist is not None and "distill" not in omit:
        summ["distill"] = {"generated": dist[0], "skipped_existing": dist[1],
                           "failed": dist[2]}
    return json.dumps({"ok": ok, "dry_run": False, "summary": summ},
                      ensure_ascii=False, indent=1)


def clog_lines(tmp):
    p = os.path.join(tmp, "changelog.md")
    if not os.path.exists(p):
        return []
    return [ln for ln in open(p, encoding="utf-8").read().splitlines() if ln.strip()]


def sa_file(tmp):
    p = os.path.join(tmp, "supply-activity.json")
    if not os.path.exists(p):
        return None
    return json.load(open(p, encoding="utf-8"))


# --------------------------------------------------------------- F1 健康产出（正控绿）
def f1_healthy_output(tmp):
    m, env, old = load_sched(tmp, "f1")
    try:
        st = {}
        v = m._supply_activity_gate(st, qc_doc(arb=(5, 0, 0), dist=(0, 21, 0)),
                                    ok=True, why="F1")
        check(v["arbitrate"]["verdict"] == "green" and v["arbitrate"]["streak"] == 0,
              "F1 生成>0 → 绿且连击清零（实测 %r）" % v["arbitrate"])
        check("健康产出" in v["arbitrate"]["note"],
              "F1 note 点名健康产出（实测 %r）" % v["arbitrate"]["note"])
        # 双零反例腿本轮跳过>0 → 在干活绿（F1 顺带覆盖腿独立性）
        check(v["distill"]["verdict"] == "green" and "在干活" in v["distill"]["note"],
              "F1 生成0/跳过21 → 绿·在干活（实测 %r）" % v["distill"])
        # 观测面双写：文件存在、形状齐、与内存 st 逐键一致
        doc = sa_file(tmp)
        check(doc is not None, "F1 观测面 supply-activity.json 已双写")
        check(doc.get("gate_n") == N and set(doc.get("kinds") or []) == {"arbitrate", "distill"},
              "F1 观测面带 gate_n=%d 与 kinds（实测 %r）" % (N, doc))
        check(doc.get("legs") == st.get("supply_activity"),
              "F1 观测面 legs 与 st['supply_activity'] 逐键一致（双写不漂移）")
        check(doc["legs"]["arbitrate"]["window"][0]["gen"] == 5,
              "F1 窗口记录生成计数（实测 %r）" % doc["legs"]["arbitrate"]["window"])
        return {"green_output": True, "dual_write": True}
    finally:
        restore_env(env, old)


# --------------------------------------------------------------- F2 健康跳过（正控绿）
def f2_healthy_skip(tmp):
    m, env, old = load_sched(tmp, "f2")
    try:
        st = {}
        for i, skip in enumerate((175, 176, 177), 1):
            v = m._supply_activity_gate(st, qc_doc(arb=(0, skip, 0), dist=(0, 21, 0)),
                                        ok=True, why="F2-r%d" % i)
            check(v["arbitrate"]["verdict"] == "green" and v["arbitrate"]["streak"] == 0,
                  "F2 第%d轮 生成0/跳过%d → 绿（跳过计数增长=在干活，不得误红；实测 %r）"
                  % (i, skip, v["arbitrate"]))
        check(len(st["supply_activity"]["arbitrate"]["window"]) == 3
              and [w["skip"] for w in st["supply_activity"]["arbitrate"]["window"]] == [175, 176, 177],
              "F2 窗口如实记录跳过计数增长轨迹（实测 %r）"
              % st["supply_activity"]["arbitrate"]["window"])
        check(v["distill"]["verdict"] == "green",
              "F2 distill 跳过21 照绿（实测 %r）" % v["distill"])
        return {"green_skip_window": True}
    finally:
        restore_env(env, old)


# --------------------------------------------------------------- F3 双零疑似死（正控红）
def f3_double_zero_red(tmp):
    m, env, old = load_sched(tmp, "f3")
    try:
        st = {}
        verdicts = []
        for i in range(1, N + 2):   # N+1 轮：前 N 轮翻红，第 N+1 轮验一次性
            v = m._supply_activity_gate(st, qc_doc(arb=(0, 175, 0), dist=(0, 0, 0)),
                                        ok=True, why="F3-r%d" % i)
            verdicts.append((v["distill"]["verdict"], v["distill"]["streak"]))
        check(verdicts[0] == ("green", 1) and verdicts[1] == ("green", 2),
              "F3 前两轮双零=观察中绿（实测 %r）" % verdicts[:2])
        check(verdicts[N - 1] == ("red", N),
              "F3 第%d轮双零 → 红（实测 %r）" % (N, verdicts[N - 1]))
        check(verdicts[N] == ("red", N + 1),
              "F3 第%d轮仍红、连击续记（实测 %r）" % (N + 1, verdicts[N]))
        check("疑似pipeline死" in st["supply_activity"]["distill"]["note"],
              "F3 红 note 点名疑似死（实测 %r）" % st["supply_activity"]["distill"]["note"])
        # 告警一次性：只第 N 轮写一条变更日志，第 N+1 轮不重复
        rows = [ln for ln in clog_lines(tmp) if "供给活性告警" in ln]
        check(len(rows) == 1 and "distill" in rows[0],
              "F3 供给活性告警恰 1 条且点名 distill（实测 %d 条：%r）" % (len(rows), rows))
        # 两腿独立：arb 同轮跳过175 → 恒绿
        check(st["supply_activity"]["arbitrate"]["verdict"] == "green",
              "F3 arb 同轮跳过>0 独立判绿（实测 %r）" % st["supply_activity"]["arbitrate"])
        return {"red_at_n": True, "alarm_once": True, "legs_independent": True}
    finally:
        restore_env(env, old)


# --------------------------------------------------------------- F4 窗口边界 + 无读数 + 腿缺席
def f4_boundary_and_unreadable(tmp):
    m, env, old = load_sched(tmp, "f4a")
    try:
        # (a) N-1 窗口边界负控：双零连续 N-1 轮 → 必须仍绿（红恰落在第 N 轮）
        st = {}
        for i in range(1, N):
            v = m._supply_activity_gate(st, qc_doc(arb=(0, 0, 0), dist=(0, 0, 0)),
                                        ok=True, why="F4a-r%d" % i)
            check(v["distill"]["verdict"] == "green" and v["distill"]["streak"] == i,
                  "F4a 第%d轮（<N=%d）双零 → 仍绿·观察中（实测 %r）" % (i, N, v["distill"]))
        check(clog_lines(tmp) == [],
              "F4a 未达 N 不写告警（实测 %r）" % clog_lines(tmp))
    finally:
        restore_env(env, old)
    # (b) 无读数负控：连击 2 → 无读数轮清零 → 再 2 轮仍不红；窗口不计入无读数轮
    m, env, old = load_sched(tmp, "f4b")
    try:
        st = {}
        m._supply_activity_gate(st, qc_doc(arb=(0, 0, 0), dist=(0, 0, 0)), ok=True, why="F4b-1")
        m._supply_activity_gate(st, qc_doc(arb=(0, 0, 0), dist=(0, 0, 0)), ok=True, why="F4b-2")
        v = m._supply_activity_gate(st, "boom\nnot json at all\n", ok=False, why="F4b-3")
        check(v["distill"]["streak"] == 0 and v["distill"]["verdict"] == "green"
              and "无读数" in v["distill"]["note"],
              "F4b JSON 不可判 → 连击清零不判红（实测 %r）" % v["distill"])
        check(len(st["supply_activity"]["distill"]["window"]) == 2,
              "F4b 无读数轮不计入窗口（实测 %d 条）"
              % len(st["supply_activity"]["distill"]["window"]))
        v = m._supply_activity_gate(st, qc_doc(arb=(0, 0, 0), dist=(0, 0, 0)), ok=True, why="F4b-4")
        v = m._supply_activity_gate(st, qc_doc(arb=(0, 0, 0), dist=(0, 0, 0)), ok=True, why="F4b-5")
        check(v["distill"]["verdict"] == "green" and v["distill"]["streak"] == 2,
              "F4b 清零后再 2 轮双零 → 仍不红（连击 %d/%d；实测 %r）"
              % (v["distill"]["streak"], N, v["distill"]))
        # (c) 顶层 ok=false（有计数也不背书）：无读数同款
        v = m._supply_activity_gate(st, qc_doc(arb=(0, 0, 0), dist=(0, 0, 0), ok=False),
                                    ok=False, why="F4b-6")
        check(v["distill"]["streak"] == 0,
              "F4b ok=false 轮按无读数处理（实测 %r）" % v["distill"])
    finally:
        restore_env(env, old)
    # (d) 腿缺席正控：summary 无 distill 键（kind 收缩嫌疑）按双零证据计入
    m, env, old = load_sched(tmp, "f4d")
    try:
        st = {}
        for i in range(1, N + 1):
            v = m._supply_activity_gate(st, qc_doc(arb=(0, 175, 0), omit=("distill",)),
                                        ok=True, why="F4d-r%d" % i)
        check(v["distill"]["verdict"] == "red" and v["distill"]["streak"] == N,
              "F4d 腿缺席连续 %d 轮 → 红（实测 %r）" % (N, v["distill"]))
        check("缺席" in v["distill"]["note"],
              "F4d 红 note 点名缺席（实测 %r）" % v["distill"]["note"])
        check(all(w["present"] is False for w in st["supply_activity"]["distill"]["window"]),
              "F4d 窗口如实记 present=false（实测 %r）"
              % st["supply_activity"]["distill"]["window"])
        return {"boundary_nm1_green": True, "unreadable_resets": True,
                "okfalse_unreadable": True, "absent_leg_red": True}
    finally:
        restore_env(env, old)


# --------------------------------------------------------------- W 接线断言（防摘除）
def w_wiring(tmp):
    src = open(TARGET[0], encoding="utf-8").read()
    check("--kind all" in src,
          "W1 cmd 含 --kind all（kind 全集；RT-E161 根因=收缩回 verify 单腿）")
    check(GATE_SYM + "(st, qc_out" in src,
          "W2 _quality_cards_supply 内确有供给活性门调用（集成点在位）")
    check("            out, ok = _qc_leg_out(r2.stdout, r2.returncode)\n" in src,
          "W3 腿取样锚行逐字在位（test-qc-leg-truth-gate tamper_fs 源码锚）")
    check('os.path.dirname(STATE), "supply-activity.json"' in src,
          "W4 观测面缺省派生 dirname(STATE)（夹具改道 FS_STATE 即连带改道，零写生产）")
    # DRY 不落盘（只探不写契约延及新观测面）
    m, env, old = load_sched(tmp, "wdry")
    try:
        m._DRY[0] = True
        st = {}
        v = m._supply_activity_gate(st, qc_doc(arb=(0, 0, 0), dist=(0, 0, 0)),
                                    ok=True, why="W-DRY")
        check(sa_file(tmp) is None,
              "W5 DRY 轮不落观测面（实测 %r）" % sa_file(tmp))
        check(v["distill"]["streak"] == 1, "W5 DRY 下判定逻辑照算（实测 %r）" % v["distill"])
    finally:
        m._DRY[0] = False
        restore_env(env, old)
    return {"kind_all": True, "gate_wired": True, "anchor_intact": True, "dry_nowrite": True}


def main(argv=None):
    global TARGET
    TARGET = pick_target()
    if TARGET[0] is None:
        return EXIT_ENV
    cases = (
        ("F1 健康产出（正控绿）+ 观测面双写一致", f1_healthy_output),
        ("F2 健康跳过（正控绿）：跳过计数增长恒绿不误红", f2_healthy_skip),
        ("F3 双零疑似死（正控红）：第N轮红+告警一次性+两腿独立", f3_double_zero_red),
        ("F4 窗口边界（负控 N-1 不红）+无读数清零+腿缺席红", f4_boundary_and_unreadable),
        ("W 接线断言：--kind all/门调用/锚行/路径派生/DRY不落盘", w_wiring),
    )
    results, failures = {}, []
    for name, fn in cases:
        try:
            with tempfile.TemporaryDirectory(prefix="e161-live-") as tmp:
                results[name] = fn(tmp)
            print("  [PASS] %s -> %s" % (name, json.dumps(results[name], ensure_ascii=False)))
        except Fail as e:
            failures.append(name)
            print("  [FAIL] %s -> %s" % (name, e))
        except Exception as e:  # noqa: BLE001
            failures.append(name)
            print("  [FAIL] %s: %s: %s" % (name, type(e).__name__, e))
    if failures:
        print("E161-SUPPLY-LIVENESS FAILED: %d 项未过（被测=%s %s）-> %s"
              % (len(failures), TARGET[1], TARGET[0], failures))
        return EXIT_FAIL
    print("E161-SUPPLY-LIVENESS PASSED: %d 项（被测=%s %s）" % (len(results), TARGET[1], TARGET[0]))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
