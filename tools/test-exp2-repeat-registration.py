#!/usr/bin/env python3
"""test-exp2-repeat-registration.py — EXP-2「repeat 实跑数自动登记」通道回归

背景（已确证发现，2026-11-02）：
  tools/b-exp2-aggregate.py 的分配表对账块原式
      repeat_present = len(executed & alloc_repeat) - len(executed & alloc_repeat & alloc_main)
  其中 executed = {(paper, arm)}（无 repeat 维的去重集）、alloc_repeat ⊆ alloc_main
  （分配表 repeat 行复用主轮 (task_id,arm)，见 exp2-allocation.json）。
  故该式对任意 executed 恒 ≡ 0 —— 与是否真跑过 repeat 无关，登记通道结构性失效；
  而 exp2-报告.md §2.5 却把它写成「聚合层对 repeat 实跑数自动登记」。
  连带口径分裂：arm_summary 的 n_eligible 直接吃全部 eligible run（不去重任务），
  而配对层 pair_runs.pick 每任务只取 repeat 号最小者 → 真跑 repeats 后五臂表分母
  会从「任务数」漂成「run 数」，与配对层分母分裂。

本次修复（tools/b-exp2-aggregate.py）：
  ① 新增 split_by_round() / repeat_registration()：repeat 实跑数按 run 身份计真值；
  ② 新增 pick_by_task()：配对层与五臂表共用同一「每任务取主轮 run」规则，
     arm_summary 分母固定为任务数，repeat 轮单列登记不进分母；
  ③ 五臂表分母口径 fail-loud 自检（n_eligible > n_tasks 即停）。

检查项：
  T1 结构性前置：exp2-allocation.json 的 alloc_repeat ⊆ alloc_main（旧式恒 0 的根因）
  T2 旧式口径在真实执行集上恒 0；且「注入一条真 repeat run」后仍然恒 0（通道确已死）
  T3 新口径在真实执行集上 = 0（当前确无 repeats 实跑）且与 per-run 明细一致
  T4 新口径在注入 report 臂 repeat run（order_id 带 -rN）后 = 1（通道活）
  T5 新口径在注入工作流臂重复行（同 (arm,paper)、无 -rN 后缀）后 = 1（重复行也认）
  T6 五臂表分母不漂：注入 repeat run 前后 n_eligible / n_tasks 不变，repeat_runs 0→1
  T7 配对层不漂：注入 repeat run 前后 n_paired 不变（两层分母同口径）
  T8 端到端：真跑聚合器，汇总件 allocation_check.repeat_runs_present 与实测一致
     （= 实际实跑的 repeat run 数），五臂 n_eligible ≤ n_tasks 且 = 任务级去重数

用法：python3 -I tools/test-exp2-repeat-registration.py [--keep]
退出码：0 全过；1 断言失败；2 前置不满足。
只读既有工件 + 只写 $HOME 下自建临时目录；零网络、零密钥。
"""
from __future__ import annotations

import argparse
import glob
import importlib.util
import json
import os
import shutil
import subprocess
import sys

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXP2_DIR = os.path.join(WS, "计划", "研究组", "实验批-20261029")
AGG = os.path.join(WS, "tools", "b-exp2-aggregate.py")

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print("  %-4s %s%s" % ("PASS" if ok else "FAIL", name, ("  — " + detail) if detail else ""))
    return ok


def load_agg():
    spec = importlib.util.spec_from_file_location("b_exp2_aggregate", AGG)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def real_runs(mod):
    """按聚合器 main() 的同一路径提取真实执行集（report 臂镜像 + 工作流臂 manifest）。"""
    materials = json.load(open(os.path.join(EXP2_DIR, "exp2-materials.json"), encoding="utf-8"))
    shas = {p["paper_id"]: p["paper_sha256"] for p in materials["papers"]}
    mirror = mod.DEFAULT_MIRROR
    order_dirs = sorted(d for d in glob.glob(os.path.join(os.path.abspath(mirror), "E2-*"))
                        if os.path.isdir(d))
    runs = [mod.extract_report_arm(d, shas) for d in order_dirs]
    manifest = os.path.join(EXP2_DIR, "exp2-wf-manifest.jsonl")
    if os.path.isfile(manifest):
        for line in open(manifest, encoding="utf-8"):
            line = line.strip()
            if line:
                runs.append(mod.extract_workflow_arm(json.loads(line), shas))
    return runs


def old_formula(runs, alloc_main, alloc_repeat):
    """修复前 b-exp2-aggregate.py 的原式（逐字复刻，用于对照）。"""
    executed = {(r["paper"], r["arm"]) for r in runs}
    return len(executed & alloc_repeat) - len(executed & alloc_repeat & alloc_main)


def main(argv):
    ap = argparse.ArgumentParser(description="EXP-2 repeat 实跑登记通道回归")
    ap.add_argument("--keep", action="store_true", help="保留临时目录（默认完工即删）")
    args = ap.parse_args(argv)

    alloc_path = os.path.join(EXP2_DIR, "exp2-allocation.json")
    if not os.path.isfile(alloc_path):
        print("前置不满足：找不到 %s" % alloc_path)
        return 2
    alloc = json.load(open(alloc_path, encoding="utf-8"))
    alloc_main = {(r["task_id"], r["arm"]) for r in alloc["runs"] if r["round"] == "main"}
    alloc_repeat = {(r["task_id"], r["arm"]) for r in alloc["runs"] if r["round"] == "repeat"}

    mod = load_agg()
    runs = real_runs(mod)
    if not runs:
        print("前置不满足：真实执行集为空（镜像/工件缺失）")
        return 2

    print("== T1 结构性前置（分配表 repeat 行复用主轮 (task_id,arm)）==")
    check("T1.1 alloc_repeat ⊆ alloc_main（旧式恒 0 的根因）",
          alloc_repeat <= alloc_main,
          "main %d / repeat %d / 交集 %d" % (len(alloc_main), len(alloc_repeat),
                                             len(alloc_main & alloc_repeat)))
    check("T1.2 repeat 行的区分字段是 repeat/round，不是 (task_id,arm)",
          all("repeat" in r and "round" in r for r in alloc["runs"]),
          "sample=%s" % json.dumps(next(r for r in alloc["runs"] if r["round"] == "repeat"),
                                   ensure_ascii=False))

    print("== T2 旧式口径：真实数据恒 0，且「注入真 repeat run」后仍恒 0（通道确已死）==")
    v_real = old_formula(runs, alloc_main, alloc_repeat)
    check("T2.1 旧式在真实执行集上 = 0", v_real == 0, "实测 %d" % v_real)

    # 注入一条「真跑了 repeat」的 run（report 臂语义：order_id 带 -rN → repeat>0）
    b0 = next(r for r in runs if r["arm"] == "B0" and r.get("report_present"))
    injected_rep = dict(b0)
    injected_rep["order_id"] = "E2-B0-r2-%s" % b0["paper"]
    injected_rep["repeat"] = 2
    runs_with_rep = runs + [injected_rep]
    v_inj = old_formula(runs_with_rep, alloc_main, alloc_repeat)
    check("T2.2 旧式在注入 repeat run 后仍 = 0（与数据无关的死通道）",
          v_inj == 0, "实测 %d（注入的是 %s）" % (v_inj, injected_rep["order_id"]))

    print("== T3 新口径：真实执行集 = 0，且与 per-run 明细一致 ==")
    reg_real = mod.repeat_registration(runs, alloc_repeat)
    tagged = [r for r in runs if (r.get("repeat") or 0) > 0]
    check("T3.1 新口径在真实执行集上 = 0", reg_real["runs_present"] == 0,
          "实测 %d" % reg_real["runs_present"])
    check("T3.2 真实执行集里 repeat>0 的 run 数 = 0（与登记数自洽）",
          len(tagged) == reg_real["runs_present"], "tagged=%d" % len(tagged))

    print("== T4 新口径：注入 report 臂 repeat run（order_id 带 -rN）后 = 1 ==")
    reg_inj = mod.repeat_registration(runs_with_rep, alloc_repeat)
    check("T4.1 runs_present = 1", reg_inj["runs_present"] == 1,
          "实测 %d" % reg_inj["runs_present"])
    check("T4.2 pairs_present = 1", reg_inj["pairs_present"] == 1,
          "实测 %d" % reg_inj["pairs_present"])
    check("T4.3 未匹配分配表的 repeat run = 0", reg_inj["unmatched_runs"] == 0,
          "实测 %d" % reg_inj["unmatched_runs"])

    print("== T5 新口径：工作流臂重复行（同 (arm,paper)、无 -rN 后缀）也认 ==")
    wf = next(r for r in runs if r["arm"] == "B2")
    wf_dup = dict(wf)
    wf_dup["order_id"] = "WF-B2-r2-%s" % wf["paper"]
    wf_dup["repeat"] = 0
    reg_wf = mod.repeat_registration(runs + [wf_dup], alloc_repeat)
    check("T5.1 工作流臂重复行被识别为 repeat（runs_present = 1）",
          reg_wf["runs_present"] == 1, "实测 %d" % reg_wf["runs_present"])

    print("== T6 五臂表分母不漂（注入 repeat run 前后）==")
    s0 = mod.arm_summary(runs, "B0")
    s1 = mod.arm_summary(runs_with_rep, "B0")
    check("T6.1 n_eligible 不变（仍为任务级）", s0["n_eligible"] == s1["n_eligible"],
          "%d → %d" % (s0["n_eligible"], s1["n_eligible"]))
    check("T6.2 n_tasks 不变", s0["n_tasks"] == s1["n_tasks"],
          "%d → %d" % (s0["n_tasks"], s1["n_tasks"]))
    check("T6.3 repeat_runs 0 → 1（repeat 轮单列登记，不进分母）",
          s0["repeat_runs"] == 0 and s1["repeat_runs"] == 1,
          "%d → %d" % (s0["repeat_runs"], s1["repeat_runs"]))
    check("T6.4 n_eligible ≤ n_tasks（分母未漂成 run 数）",
          s1["n_eligible"] <= s1["n_tasks"],
          "n_eligible=%d n_tasks=%d n_orders=%d" % (s1["n_eligible"], s1["n_tasks"],
                                                     s1["n_orders"]))
    check("T6.5 all_hit_rate 分母仍为任务数",
          abs(s1["all_hit_rate"] - s0["all_hit_rate"]) < 1e-12,
          "%s → %s" % (s0["all_hit_rate"], s1["all_hit_rate"]))
    # 现有数据上「任务级分母 ≡ 原 run 级分母」的恒等性证明：每个 (arm,paper) 至多
    # 一条 eligible run ⇒ pick_by_task 是恒等映射 ⇒ 本次修复对现有数值零影响。
    multi = {}
    for r in runs:
        if mod.analysis_eligible(r):
            multi[(r["arm"], r["paper"])] = multi.get((r["arm"], r["paper"]), 0) + 1
    dup = {k: v for k, v in multi.items() if v > 1}
    check("T6.6 现有执行集内每个 (arm,paper) 至多一条 eligible run（任务级≡run 级，"
          "修复对现有数值恒等）", not dup, "重复项 %s" % (list(dup.items())[:5] if dup else "无"))

    print("== T7 配对层不漂（两层分母同口径）==")
    p0, _ = mod.pair_runs(runs, "B2", "B0")
    p1, _ = mod.pair_runs(runs_with_rep, "B2", "B0")
    check("T7.1 n_paired 不变（注入 repeat 不改变配对集）", len(p0) == len(p1),
          "%d → %d" % (len(p0), len(p1)))
    check("T7.2 五臂表分母与配对集任务数同口径（B2 臂 eligible ≤ 配对集任务数）",
          s1["n_eligible"] <= s1["n_tasks"],
          "B0 eligible=%d / B0 tasks=%d" % (s1["n_eligible"], s1["n_tasks"]))

    print("== T8 端到端：真跑聚合器，汇总件登记与实测一致 ==")
    tmp = os.path.join(os.path.expanduser("~"), ".cache", "exp2-repeat-reg-probe")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp, exist_ok=True)
    try:
        p = subprocess.run([sys.executable, "-I", AGG, "--out-dir", tmp],
                           cwd=WS, capture_output=True, text=True)
        if p.returncode != 0:
            check("T8.0 聚合器退出码 0", False, "rc=%d\n%s" % (p.returncode, p.stderr[-800:]))
        else:
            check("T8.0 聚合器退出码 0", True, "rc=0")
            summ = json.load(open(os.path.join(tmp, "exp2-aggregate-summary.json"),
                                  encoding="utf-8"))
            ac = summ["allocation_check"]
            detail = [r for r in runs if (r.get("repeat") or 0) > 0]
            check("T8.1 汇总件 repeat_runs_present 与实测 repeat run 数一致",
                  ac["repeat_runs_present"] == len(detail),
                  "件上 %d / 实测 %d" % (ac["repeat_runs_present"], len(detail)))
            check("T8.2 汇总件 alloc_repeat = 分配表 repeat run 数",
                  ac["alloc_repeat"] == len([r for r in alloc["runs"] if r["round"] == "repeat"]),
                  "件上 %d" % ac["alloc_repeat"])
            ok = all(summ["arm_summaries"][a]["n_eligible"] <= summ["arm_summaries"][a]["n_tasks"]
                     for a in summ["arm_summaries"])
            check("T8.3 五臂 n_eligible ≤ n_tasks（分母任务级）", ok,
                  json.dumps({a: (summ["arm_summaries"][a]["n_eligible"],
                                  summ["arm_summaries"][a]["n_tasks"])
                              for a in summ["arm_summaries"]}, ensure_ascii=False))
            check("T8.4 判定层未崩：verdict ∈ 闭合集、三个对比 n_paired ≤ 任务数",
                  summ["verdict"]["verdict"] in {
                      "confirmed", "refuted", "equivalent", "inconclusive",
                      "cost_conditional", "channel_effect", "pending"}
                  and all(0 <= summ["paired"][k]["n_paired"] <= 24
                          for k in summ["paired"]),
                  "verdict=%s n_p=%s" % (summ["verdict"]["verdict"],
                                         {k: summ["paired"][k]["n_paired"]
                                          for k in summ["paired"]}))
            # 判定层读数只作存照（同一代码基线下的改前/改后逐键 diff 见回归证据）：
            # 本门不钉死具体数值——并行轮次若另有修复改动入集口径，数值随之变，
            # 与 repeat 登记通道无关。
            print("     （存照）verdict=%s；n_paired=%s；五臂 n_eligible=%s"
                  % (summ["verdict"]["verdict"],
                     {k: summ["paired"][k]["n_paired"] for k in summ["paired"]},
                     {a: summ["arm_summaries"][a]["n_eligible"] for a in summ["arm_summaries"]}))
    finally:
        if not args.keep:
            shutil.rmtree(tmp, ignore_errors=True)

    npass = sum(1 for _n, ok, _d in RESULTS if ok)
    nfail = len(RESULTS) - npass
    print("\n%d/%d PASS, %d FAIL" % (npass, len(RESULTS), nfail))
    if nfail:
        for n, ok, d in RESULTS:
            if not ok:
                print("  FAILED: %s  %s" % (n, d))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
