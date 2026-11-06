#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test-exp2-gate — EXP-2 预注册 gate 先筛口径回归门（2026-11-02 红队确证修复配套）。

红队确证（缺陷原文）：预注册 EXP-2.metrics[] 四项 role="gate"
（marker_align/sha_match/snapshot_present/rubric_passed）一个都没施加——
聚合器 analysis_eligible 只判 report_present 与 t8_clean；主对比 +8.70pp 只在把
未过 gate 的 run 计入时成立，按预注册 gate 先筛后为 +4.76pp（跌破预注册 +5pp 确认阈）；
报告与汇总件 0 处披露该 gate 及其破口。

本门（不弱化任何断言，逐条锁死修复后的不变量）：
  A1 预注册 role=gate 项集 == {marker_align, sha_match, snapshot_present, rubric_passed}
     （判据取自 experiments-v1.json 原文，不写死实现）
  A2 聚合器施加集（引用侧三项）∪ 已披露敏感性集（rubric_passed）== A1 项集
     ——预注册 gate 指标无一声明式丢弃
  A3 analysis_eligible 语义：有 report ∧ T8 干净 ∧ 引用侧三项 gate 全过；
     逐条反例（缺 report / T8 违约 / 三项 gate 任一不过或缺值）必须被拒
  A4 入集 run 必过 gate：逐 run 明细中 analysis_eligible=True 的 run，
     marker_align/sha_match/snapshot_present 必全为 True（不得有 gate 破口进集）
  A5 汇总件数字 == 由逐 run 明细按 gate 先筛口径独立复算的数字
     （五臂 eligible/all_hit + 配对 b/c/n_p/diff/p）——口径漂移即红
  A6 gate 破口（gate 不过但 all_hit=True）必须全额登记进汇总件
     prereg_gate.gate_break_all_hit，且与独立复算集合全等
  A7 披露面：汇总件与报告（exp2-报告.md）必须披露该 gate（命中四项 gate 指标名）
     ——修复前二者对 gate 指标名 0 命中
  A8 预注册锁核销（exp2-lock.json 的 materials_sha256，2026-11-03 修复项）：
     A8a 实算 exp2-materials.json 的 sha256 == exp2-lock.json 登记值（独立复算）
     A8b 汇总件登记的 materials_lock.actual_sha256 == 锁登记值（汇总件自证消费的是
          锁定材料件；修复前汇总件 materials 仅一条路径字符串、不记 sha256 → 材料被改
          后重算的账目事后无从发现）
     A8c 汇总件登记值 == 实算值（汇总件与盘面一致 → 事后无从发现被改）
     A8d 负控：材料件副本改 1 篇 paper_sha256 → 聚合器的锁核销必须抛漂移（不得放行）；
          未改副本必须放行（核销函数不得恒红）
     A8e 负控：锁件缺失 → 同样必须抛漂移（fail-closed，不得静默放行）
  A9 策略库正本 ↔ 交付汇总件 数值链对账（2026-11-03 红队终局轮确证修复配套）：
     背景——策略库正本（守护读/写面 tools/self-improve-loop.py
     resolve_strategies_dir() 首候选 wb_wt/strategies）的 st-C103.yaml 机读
     experiment.note 载的是报告 §9 已明文作废的 v3 旧账（n_p=23、主对比
     +8.70pp、p=0.34），与现役交付汇总件 exp2-aggregate-summary.json
     （n_p=21、主对比 +4.76pp、p=0.50）矛盾；此前无门比对（映射 G7 监测项
     只读 experiment 字段、不与交付汇总件比数值）→ 漂移长期不可见、亦不自愈。
     本段把「库内机读终裁链 ≡ 交付汇总件现役账」变成常驻断言，并禁入作废旧账：
     A9a 正本面可定位且含 EXP-2 条目（否则对账无对象=红，不许空转绿）
     A9b 每条机读终裁链（n_p/main_diff_pp/mcnemar_p_one_sided/main_tost_cp90_pp/
         gate_fires/终裁词/来源汇总件名）逐项等于对应交付汇总件 .verdict
     A9c experiment.status 等于交付 verdict 经守护 VERDICT_STATUS_MAP 的映射值
     A9d 作废的 v3 旧账禁入（指纹取报告 §9 原文声明值 + 舍入容差）
     A9e 负控：把正本副本 note 换成作废旧账 → 对账必须判红；未篡改副本必须判绿
         （证明本门有判别力，而非恒绿/恒红）
     判据单一源：正本面定位取守护 resolve_strategies_dir()；status 映射取守护
     VERDICT_STATUS_MAP/VERDICT_FALLBACK；数值链取交付汇总件 .verdict 原文；
     作废旧账指纹取 exp2-报告.md:179 原文声明的舍入值。

用法：python3 tools/test-exp2-gate.py [--exp2-dir DIR] [--strategies-dir DIR]
                                                  （退出码 0=全绿，1=有红）
  --exp2-dir：交付件目录（默认工作区实验批目录）；供探针指向副本用，断言不变。
  --strategies-dir：策略库正本面（缺省=守护 resolve_strategies_dir() 的读/写面）；
     供探针指向副本（负控用）用，断言不变。
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.dirname(HERE)
EXP2_DIR = os.path.join(WS, "计划/研究组/实验批-20261029")
SPEC_PATH = os.path.join(WS, "计划/研究组/B线核心批-20261029/experiments-v1.json")
AGG_PATH = os.path.join(HERE, "b-exp2-aggregate.py")
SUMMARY_PATH = os.path.join(EXP2_DIR, "exp2-aggregate-summary.json")
DETAIL_PATH = os.path.join(EXP2_DIR, "exp2-per-run-detail.jsonl")
REPORT_PATH = os.path.join(EXP2_DIR, "exp2-报告.md")
MATERIALS_PATH = os.path.join(EXP2_DIR, "exp2-materials.json")
LOCK_PATH = os.path.join(EXP2_DIR, "exp2-lock.json")

GATE_METRIC_NAMES = ("marker_align", "sha_match", "snapshot_present", "rubric_passed")

FAILED = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print("[%s] %s%s" % (status, name, ("  —— " + detail) if detail else ""))
    if not cond:
        FAILED.append(name)
    return cond


def load_aggregator():
    spec = importlib.util.spec_from_file_location("b_exp2_aggregate_under_test", AGG_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def prereg_gate_metrics():
    spec = json.load(open(SPEC_PATH, encoding="utf-8"))
    exp2 = [e for e in spec["experiments"] if e["exp_id"] == "EXP-2"][0]
    return sorted(m["name"] for m in exp2["metrics"] if m.get("role") == "gate")


def load_detail(path=None):
    runs = []
    with open(path or DETAIL_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                runs.append(json.loads(line))
    return runs


def sha256_file(path):
    """文件字节流 sha256（独立复算，不复用聚合器实现，防同源漂移）。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_lock_probe_dir(tmp_root, materials_path, lock_path, tamper):
    """复制材料件+锁件到临时目录；tamper=True 时改 1 篇 paper_sha256（仍为合法 JSON）。"""
    d = os.path.join(tmp_root, "tampered" if tamper else "clean")
    os.makedirs(d, exist_ok=True)
    shutil.copyfile(materials_path, os.path.join(d, "exp2-materials.json"))
    shutil.copyfile(lock_path, os.path.join(d, "exp2-lock.json"))
    mp = os.path.join(d, "exp2-materials.json")
    if tamper:
        m = json.load(open(mp, encoding="utf-8"))
        p0 = m["papers"][0]
        p0["paper_sha256"] = hashlib.sha256(
            ("exp2-lock-probe-tamper:" + str(p0["paper_id"])).encode()).hexdigest()
        with open(mp, "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False, indent=1)
    return d, mp


def p_ge(b, s):
    from math import comb
    if s <= 0 or b <= 0:
        return 1.0
    if b > s:
        return 0.0
    return sum(comb(s, k) for k in range(b, s + 1)) / float(1 << s)


def pick_by_task(runs, arm, elig):
    best = {}
    for r in runs:
        if r["arm"] != arm or not elig(r):
            continue
        cur = best.get(r["paper"])
        if cur is None or (r.get("repeat") or 0) < (cur.get("repeat") or 0):
            best[r["paper"]] = r
    return best


def gate_first_eligible(r):
    """按预注册 gate 先筛口径独立复算（不复用聚合器实现，防同源漂移）。"""
    return (bool(r.get("report_present")) and bool(r.get("t8_clean", True))
            and r.get("marker_align") is True
            and r.get("sha_match") is True
            and r.get("snapshot_present") is True)


# ---------------------------------------------------------------- A9 常量/解析
# 作废旧账指纹：exp2-报告.md:179 原文「v3 旧账（n_p=23、主对比 +8.70pp、p=0.34、
# 辅助 +4.17pp）作废」——取报告声明的两位舍入值 + 容差（覆盖 8.6956…/0.34375 的
# 全精度形态，也覆盖报告原文的舍入形态）。
VOIDED_EXP2_V3 = {"n_p": 23, "main_diff_pp": 8.70, "mcnemar_p_one_sided": 0.34}
VOIDED_TOL = 0.01
NOTE_NUM_TOL = 1e-9

_NOTE_PATTERNS = (
    ("verdict", re.compile(r"终裁\s+([A-Za-z_]+)")),
    ("n_p", re.compile(r"n_p=(\d+)")),
    ("main_diff_pp", re.compile(r"main_diff_pp=(-?\d+(?:\.\d+)?)pp")),
    ("mcnemar_p_one_sided", re.compile(r"mcnemar_p_one_sided=(-?\d+(?:\.\d+)?)")),
    ("main_tost_cp90_pp",
     re.compile(r"main_tost_cp90_pp=\[(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)\]pp")),
    ("gate_fires", re.compile(r"gate_fires=(True|False)")),
    ("source", re.compile(r"来源\s+([^\s（(]+?)-aggregate-summary\.json")),
)


def parse_note_chain(note):
    """解析守护正本渲染器（_verdict_note）机读终裁链；缺任一字段=非机读形态 → None。

    返回 {verdict,n_p,main_diff_pp,mcnemar_p_one_sided,main_tost_cp90_pp,gate_fires,source}
    （source=「exp1」/「exp2」前缀）。散文注记（如 st-C007 的人工 tier A 注记）
    不在此形态内，返回 None。"""
    if not note:
        return None
    out = {}
    for key, pat in _NOTE_PATTERNS:
        m = pat.search(note)
        if not m:
            return None
        if key in ("verdict", "source"):
            out[key] = m.group(1)
        elif key == "n_p":
            out[key] = int(m.group(1))
        elif key == "main_tost_cp90_pp":
            out[key] = [float(m.group(1)), float(m.group(2))]
        elif key == "gate_fires":
            out[key] = (m.group(1) == "True")
        else:
            out[key] = float(m.group(1))
    return out


def is_voided_exp2_v3(chain):
    """机读终裁链是否命中报告已作废的 v3 旧账指纹（n_p=23 ∧ +8.70pp ∧ p=0.34）。"""
    return (chain.get("n_p") == VOIDED_EXP2_V3["n_p"]
            and abs(chain.get("main_diff_pp", 0.0) - VOIDED_EXP2_V3["main_diff_pp"]) <= VOIDED_TOL
            and abs(chain.get("mcnemar_p_one_sided", 1.0)
                    - VOIDED_EXP2_V3["mcnemar_p_one_sided"]) <= VOIDED_TOL)


def load_guardian():
    """守护模块经 importlib 原样加载（判据单一源：resolve_strategies_dir /
    VERDICT_STATUS_MAP / VERDICT_FALLBACK——本门不复制这些判据）。

    返回 (module, None) 或 (None, 错误串)。模块顶层无副作用（无文件写）。"""
    src = os.path.join(HERE, "self-improve-loop.py")
    try:
        spec = importlib.util.spec_from_file_location("sil_guardian_under_test", src)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod, None
    except Exception as e:  # noqa: BLE001 —— 判据源不可载=本门全体不可信
        return None, "%s: %s" % (src, e)


def strategy_parity_violations(strat_dir, exp_summaries, status_map, status_fallback):
    """库内机读终裁链 ↔ 交付汇总件 .verdict 数值链对账。返回违规串列表（空=全等）。

    每条违规带类型前缀：CHAIN:/SRC:/FORM:/STATUS:/VOIDED:/MISSING:/YAML:。
    EXP-2 条目必须机读形态（FORM 护栏，防以散文 note 逃避数值对账）；EXP-1 机读
    条目同样对账（st-C122），EXP-1 散文条目（st-C007 人工注记）不参与。"""
    try:
        import yaml
    except ImportError as e:
        return ["YAML: A9 依赖 PyYAML 不可用：%s（缺件=红）" % e]
    if not strat_dir or not os.path.isdir(strat_dir):
        return ["MISSING: 策略库正本目录不可定位：%r" % (strat_dir,)]
    viol = []
    exp2_seen = 0
    for path in sorted(glob.glob(os.path.join(strat_dir, "st-*.yaml"))):
        name = os.path.basename(path)
        try:
            doc = yaml.safe_load(open(path, encoding="utf-8").read())
        except Exception as e:  # noqa: BLE001
            viol.append("YAML: %s 解析失败：%s" % (name, e))
            continue
        exp = (doc or {}).get("experiment") or {}
        eid = exp.get("exp_id")
        if eid not in exp_summaries:
            continue
        if eid == "EXP-2":
            exp2_seen += 1
        note = exp.get("note") or ""
        chain = parse_note_chain(note)
        if chain is None:
            if eid == "EXP-2":
                viol.append("FORM: %s exp_id=EXP-2 但 note 非守护机读终裁形态"
                            "（缺数值链字段，无法与交付汇总件对账）" % name)
            continue
        v = (exp_summaries[eid].get("verdict") or {})
        want_src = eid.replace("-", "").lower()          # EXP-2 → exp2
        if chain["source"] != want_src:
            viol.append("SRC: %s note 来源=%s-aggregate-summary.json ≠ 该实验交付汇总件名 %s"
                        % (name, chain["source"], want_src))
        pairs = (
            ("终裁词", chain["verdict"], v.get("verdict")),
            ("n_p", chain["n_p"], v.get("n_p")),
            ("main_diff_pp", chain["main_diff_pp"], v.get("main_diff_pp")),
            ("mcnemar_p_one_sided", chain["mcnemar_p_one_sided"], v.get("mcnemar_p_one_sided")),
            ("gate_fires", chain["gate_fires"], bool(v.get("gate_fires"))),
        )
        for label, got, want in pairs:
            if isinstance(got, float) and isinstance(want, (int, float)) and not isinstance(want, bool):
                ok = abs(got - float(want)) <= NOTE_NUM_TOL
            else:
                ok = (got == want)
            if not ok:
                viol.append("CHAIN: %s %s：库内=%r ≠ 交付汇总件=%r" % (name, label, got, want))
        want_tost = v.get("main_tost_cp90_pp")
        got_tost = chain["main_tost_cp90_pp"]
        if (not isinstance(want_tost, list)
                or [float(x) for x in got_tost] != [float(x) for x in want_tost]):
            viol.append("CHAIN: %s main_tost_cp90_pp：库内=%r ≠ 交付汇总件=%r"
                        % (name, got_tost, want_tost))
        want_status = status_map.get(v.get("verdict"), status_fallback)
        if exp.get("status") != want_status:
            viol.append("STATUS: %s experiment.status=%r ≠ VERDICT_STATUS_MAP[%r]=%r"
                        % (name, exp.get("status"), v.get("verdict"), want_status))
        if eid == "EXP-2" and is_voided_exp2_v3(chain):
            viol.append("VOIDED: %s 机读终裁链=报告已作废的 v3 旧账（n_p=23、主对比 +8.70pp、"
                        "p=0.34；exp2-报告.md:179 明文作废）——不得作为现役账入库" % name)
    if exp2_seen == 0:
        viol.append("MISSING: 库内无 exp_id=EXP-2 条目（本门对账对象缺席=红，不许空转绿）")
    return viol


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="EXP-2 预注册 gate 先筛口径 + 材料锁核销 + 策略库正本对账 回归门")
    ap.add_argument("--exp2-dir", default=EXP2_DIR,
                    help="交付件目录（默认工作区实验批目录；探针可指向副本，断言不变）")
    ap.add_argument("--strategies-dir", default="",
                    help="策略库正本面（缺省=守护 resolve_strategies_dir() 的读/写面；"
                         "探针指向副本用，断言不变）")
    args = ap.parse_args(argv)
    exp2_dir = os.path.abspath(args.exp2_dir)
    summary_path = os.path.join(exp2_dir, "exp2-aggregate-summary.json")
    detail_path = os.path.join(exp2_dir, "exp2-per-run-detail.jsonl")
    report_path = os.path.join(exp2_dir, "exp2-报告.md")
    materials_path = os.path.join(exp2_dir, "exp2-materials.json")
    lock_path = os.path.join(exp2_dir, "exp2-lock.json")

    print("== test-exp2-gate：EXP-2 预注册 gate 先筛口径 + 材料锁核销 回归 ==")
    print("  spec   : %s" % SPEC_PATH)
    print("  聚合器 : %s" % AGG_PATH)
    print("  交付件 : %s" % exp2_dir)

    # ---- A1 预注册 role=gate 项集 ----
    declared = prereg_gate_metrics()
    check("A1 预注册 EXP-2 metrics[] role=gate 项集 == 四项 gate 指标",
          declared == sorted(GATE_METRIC_NAMES),
          "declared=%s" % declared)

    mod = load_aggregator()
    applied = list(getattr(mod, "GATE_CITATION_METRICS", ()))
    disclosed_rubric = getattr(mod, "GATE_RUBRIC_METRIC", None)

    # ---- A2 施加集 + 已披露集 == 预注册项集（无一声明式丢弃）----
    covered = sorted(set(applied) | ({disclosed_rubric} if disclosed_rubric else set()))
    check("A2 聚合器施加集 ∪ 已披露敏感性集 == 预注册 role=gate 项集",
          covered == declared,
          "applied=%s disclosed_rubric=%r covered=%s" % (applied, disclosed_rubric, covered))

    # ---- A3 analysis_eligible 语义（正例 + 逐条反例）----
    good = {"report_present": True, "t8_clean": True,
            "marker_align": True, "sha_match": True, "snapshot_present": True}
    check("A3a analysis_eligible 接受三项 gate 全过的 run",
          mod.analysis_eligible(dict(good)) is True)
    bad_cases = [
        ("缺 report", dict(good, report_present=False)),
        ("T8 违约", dict(good, t8_clean=False)),
        ("marker_align=False", dict(good, marker_align=False)),
        ("sha_match=False", dict(good, sha_match=False)),
        ("snapshot_present=False", dict(good, snapshot_present=False)),
        ("marker_align 缺值(None)", dict(good, marker_align=None)),
        ("sha_match 缺值(None)", dict(good, sha_match=None)),
        ("snapshot_present 缺值(None)", dict(good, snapshot_present=None)),
    ]
    for label, rec in bad_cases:
        check("A3b analysis_eligible 拒绝：%s" % label,
              mod.analysis_eligible(rec) is False)

    # ---- 交付件 ----
    if not os.path.isfile(summary_path) or not os.path.isfile(detail_path):
        check("A4/A5/A6 交付件在位（summary + per-run 明细）", False,
              "缺 %s 或 %s" % (summary_path, detail_path))
        return 1
    summary = json.load(open(summary_path, encoding="utf-8"))
    runs = load_detail(detail_path)

    # ---- A4 入集 run 必过 gate ----
    bad_in = [r["order_id"] for r in runs
              if r.get("analysis_eligible") is True and not gate_first_eligible(r)]
    check("A4 入集 run 必过预注册 gate（无 gate 破口进分析集）",
          not bad_in, "破口进集 %d 例 %s" % (len(bad_in), bad_in[:5]))
    # 明细自身须带入集资格字段（否则「入集」不可自证）
    check("A4b 逐 run 明细带 analysis_eligible/excluded_reason 字段",
          all(("analysis_eligible" in r and "excluded_reason" in r) for r in runs))

    # ---- A5 汇总件数字 == 独立复算数字 ----
    for arm in ("B0", "B1", "B2", "B3", "B4"):
        prim = pick_by_task([r for r in runs if r["arm"] == arm], arm, gate_first_eligible)
        n_exp = len(prim)
        h_exp = sum(1 for r in prim.values() if r.get("all_hit"))
        s = (summary.get("arm_summaries") or {}).get(arm) or {}
        check("A5a 五臂 %s eligible/all_hit 与独立复算全等" % arm,
              s.get("n_eligible") == n_exp and s.get("n_all_hit") == h_exp,
              "summary=(%s,%s) recomputed=(%d,%d)"
              % (s.get("n_eligible"), s.get("n_all_hit"), n_exp, h_exp))
    for treat, ctrl in (("B2", "B0"), ("B2", "B3"), ("B4", "B0")):
        t = pick_by_task(runs, treat, gate_first_eligible)
        c = pick_by_task(runs, ctrl, gate_first_eligible)
        papers = sorted(set(t) & set(c))
        b = sum(1 for p in papers if t[p].get("all_hit") and not c[p].get("all_hit"))
        cc = sum(1 for p in papers if not t[p].get("all_hit") and c[p].get("all_hit"))
        n = len(papers)
        diff = 0.0 if n == 0 else (b - cc) * 100.0 / n
        st = (summary.get("paired") or {}).get("%s−%s" % (treat, ctrl)) or {}
        ok = (st.get("n_paired") == n and st.get("b_treat_better") == b
              and st.get("c_ctrl_better") == cc
              and abs((st.get("diff_pp") or 0.0) - diff) < 1e-9
              and abs((st.get("mcnemar_p_one_sided_treat") or 0.0) - p_ge(b, b + cc)) < 1e-12)
        check("A5b 配对 %s−%s 与独立复算全等（gate 先筛口径）" % (treat, ctrl), ok,
              "summary=(n_p=%s,b=%s,c=%s,diff=%s,p=%s) recomputed=(%d,%d,%d,%.4f,%.4f)"
              % (st.get("n_paired"), st.get("b_treat_better"), st.get("c_ctrl_better"),
                 st.get("diff_pp"), st.get("mcnemar_p_one_sided_treat"),
                 n, b, cc, diff, p_ge(b, b + cc)))

    # ---- A6 gate 破口全额登记 ----
    pg = summary.get("prereg_gate") or {}
    check("A6a 汇总件含 prereg_gate 披露块", bool(pg),
          "keys=%s" % sorted(pg.keys()))
    exp_break = sorted(r["order_id"] for r in runs
                       if r.get("report_present") and r.get("t8_clean", True)
                       and not gate_first_eligible(r) and r.get("all_hit"))
    got_break = sorted(pg.get("gate_break_all_hit") or [])
    check("A6b gate 破口（gate 不过但 all_hit=True）已全额登记且与独立复算全等",
          got_break == exp_break,
          "summary=%s recomputed=%s" % (got_break, exp_break))
    exp_excluded = sorted(r["order_id"] for r in runs
                          if r.get("report_present") and r.get("t8_clean", True)
                          and not gate_first_eligible(r))
    got_excluded = sorted(v.get("order_id") for v in (pg.get("gate_excluded") or []))
    check("A6c gate 排除清单（全部 gate 不过者）与独立复算全等",
          got_excluded == exp_excluded,
          "summary=%s recomputed=%s" % (got_excluded, exp_excluded))
    check("A6d 汇总件披露 rubric gate 敏感性（预注册第四项 gate 不被静默丢弃）",
          bool((pg.get("rubric_gate_sensitivity") or {}).get("comparisons")),
          "comparisons=%s" % sorted((pg.get("rubric_gate_sensitivity") or {})
                                    .get("comparisons", {}).keys()))

    # ---- A7 披露面（报告 + 汇总件须披露 gate）----
    report_text = open(report_path, encoding="utf-8").read() if os.path.isfile(report_path) else ""
    summary_text = open(summary_path, encoding="utf-8").read()
    miss_r = [m for m in GATE_METRIC_NAMES if m not in report_text]
    miss_s = [m for m in GATE_METRIC_NAMES if m not in summary_text]
    check("A7a 报告（exp2-报告.md）披露四项 gate 指标名", not miss_r, "缺 %s" % miss_r)
    check("A7b 汇总件披露四项 gate 指标名", not miss_s, "缺 %s" % miss_s)

    # ---- A8 预注册锁核销（exp2-lock.json 的 materials_sha256）----
    lock = json.load(open(lock_path, encoding="utf-8")) if os.path.isfile(lock_path) else {}
    reg = lock.get("materials_sha256")
    actual = sha256_file(materials_path) if os.path.isfile(materials_path) else None
    check("A8a 实算材料件 sha256 == exp2-lock.json 登记值（锁失守即红）",
          bool(reg) and actual == reg,
          "actual=%s… lock=%s…" % (str(actual)[:16], str(reg)[:16]))
    ml = summary.get("materials_lock") or {}
    check("A8b 汇总件登记 materials_lock.actual_sha256 == 锁登记值"
          "（汇总件自证消费的是锁定材料件；无该字段即红——事后无从发现被改）",
          ml.get("actual_sha256") == reg and ml.get("lock_sha256") == reg,
          "summary actual=%s lock=%s vs 登记 %s"
          % (str(ml.get("actual_sha256"))[:16], str(ml.get("lock_sha256"))[:16], str(reg)[:16]))
    check("A8c 汇总件登记值 == 实算值（汇总件与盘面一致 → 事后无从发现被改）",
          ml.get("actual_sha256") == actual,
          "summary actual=%s vs 实算 %s"
          % (str(ml.get("actual_sha256"))[:16], str(actual)[:16]))

    # 负控：聚合器的锁核销函数必须「被改材料→漂移 / 缺锁→漂移 / 未改→放行」
    if not (os.path.isfile(materials_path) and os.path.isfile(lock_path)):
        check("A8d/A8e 负控可执行（材料件与锁件在位）", False,
              "缺 %s 或 %s" % (materials_path, lock_path))
    else:
        tmp_root = tempfile.mkdtemp(prefix="exp2-lock-probe-")
        try:
            clean_dir, clean_mp = build_lock_probe_dir(tmp_root, materials_path, lock_path,
                                                       tamper=False)
            tam_dir, tam_mp = build_lock_probe_dir(tmp_root, materials_path, lock_path, tamper=True)
            drift_msg = ""
            try:
                mod.verify_materials_lock(tam_dir, tam_mp)
            except mod.MaterialsLockDrift as e:
                drift_msg = str(e)
            check("A8d 负控：材料件被改（1 篇 paper_sha256）→ 聚合器锁核销必须判漂移（不得放行）",
                  bool(drift_msg) and sha256_file(tam_mp) != reg,
                  "sha(改后)=%s… vs 登记 %s…；漂移消息=%s"
                  % (sha256_file(tam_mp)[:16] if os.path.isfile(tam_mp) else "?",
                     str(reg)[:16], drift_msg[:110] or "无"))
            clean_ok, clean_msg = None, ""
            try:
                info = mod.verify_materials_lock(clean_dir, clean_mp)
                clean_ok = bool(info.get("match"))
            except Exception as e:  # noqa: BLE001 —— 误拒也是红
                clean_ok, clean_msg = False, "clean 副本被误拒：%s" % e
            check("A8d2 未改材料件副本 → 聚合器锁核销必须放行（核销函数不得恒红）",
                  clean_ok is True, clean_msg or "match=%s" % clean_ok)
            nolock_dir = os.path.join(tmp_root, "nolock")
            os.makedirs(nolock_dir, exist_ok=True)
            shutil.copyfile(materials_path, os.path.join(nolock_dir, "exp2-materials.json"))
            nolock_msg = ""
            try:
                mod.verify_materials_lock(nolock_dir,
                                          os.path.join(nolock_dir, "exp2-materials.json"))
            except mod.MaterialsLockDrift as e:
                nolock_msg = str(e)
            check("A8e 负控：锁件缺失 → 聚合器锁核销必须判漂移（fail-closed，不得静默放行）",
                  bool(nolock_msg), "漂移消息=%s" % (nolock_msg[:110] or "无"))
        finally:
            shutil.rmtree(tmp_root, ignore_errors=True)

    # ---- A9 策略库正本 ↔ 交付汇总件 数值链对账（库内机读终裁链 ≡ 现役账）----
    guardian, gerr = load_guardian()
    check("A9a 判据单一源守护模块可载入（resolve_strategies_dir/VERDICT_STATUS_MAP）",
          guardian is not None, gerr or "")
    strat_dir = args.strategies_dir
    if not strat_dir and guardian is not None:
        strat_dir = guardian.resolve_strategies_dir()
    if not strat_dir:
        strat_dir = os.environ.get("SIL_STRATEGIES_DIR", "")
    check("A9a2 策略库正本面可定位（守护读/写面在位）",
          bool(strat_dir) and os.path.isdir(strat_dir or "."),
          "strat_dir=%r" % strat_dir)

    exp_summaries = {}
    if os.path.isfile(summary_path):
        exp_summaries["EXP-2"] = summary
    exp1_summary_path = os.path.join(os.path.dirname(SPEC_PATH), "exp1-aggregate-summary.json")
    if os.path.isfile(exp1_summary_path):
        exp_summaries["EXP-1"] = json.load(open(exp1_summary_path, encoding="utf-8"))
    if guardian is not None:
        status_map, status_fallback = guardian.VERDICT_STATUS_MAP, guardian.VERDICT_FALLBACK
    else:
        status_map, status_fallback = {"confirmed": "confirmed", "refuted": "refuted",
                                       "pending": "pending"}, "inconclusive"

    if not (bool(strat_dir) and os.path.isdir(strat_dir or ".")):
        check("A9b-e 对账可执行（正本面在场）", False,
              "正本面不可定位，A9b/A9c/A9d/A9e 无法执行（缺件=红）")
    else:
        viol = strategy_parity_violations(strat_dir, exp_summaries, status_map, status_fallback)
        chain_bad = [x for x in viol if x.startswith(("CHAIN:", "SRC:", "FORM:", "YAML:", "MISSING:"))]
        status_bad = [x for x in viol if x.startswith("STATUS:")]
        voided_bad = [x for x in viol if x.startswith("VOIDED:")]
        check("A9b 库内机读终裁链（n_p/main_diff_pp/mcnemar/tost/gate_fires/终裁词/来源汇总件）"
              " ≡ 交付汇总件 .verdict（EXP-2 对象在场且非空转）",
              not chain_bad,
              ("违规 %d 条：%s" % (len(chain_bad), chain_bad[:3])) if chain_bad else "全等")
        check("A9c experiment.status == 交付 verdict 经守护 VERDICT_STATUS_MAP 的映射值",
              not status_bad,
              ("违规 %d 条：%s" % (len(status_bad), status_bad[:3])) if status_bad else "全等")
        check("A9d 作废 v3 旧账（n_p=23/+8.70pp/p=0.34）不得作为现役账入库（exp2-报告.md:179 已作废）",
              not voided_bad,
              ("违规 %d 条：%s" % (len(voided_bad), voided_bad[:3])) if voided_bad else "未命中作废旧账")

        # A9e 负控：把正本副本的数值链换成作废旧账 → 同一对账函数必须判红（判别力）；
        #      未篡改副本（=A9b 全等）即「不得恒红」的对照臂。
        tmp_strat = tempfile.mkdtemp(prefix="exp2-strat-parity-probe-")
        try:
            lib_copy = os.path.join(tmp_strat, "lib")
            shutil.copytree(strat_dir, lib_copy)
            tampered = []
            for p in glob.glob(os.path.join(lib_copy, "st-*.yaml")):
                txt = open(p, encoding="utf-8").read()
                if "n_p=" not in txt:
                    continue
                new = re.sub(r"n_p=\d+", "n_p=23", txt, count=1)
                new = re.sub(r"main_diff_pp=[\d.]+pp", "main_diff_pp=8.695652173913043pp", new, count=1)
                new = re.sub(r"mcnemar_p_one_sided=[\d.]+", "mcnemar_p_one_sided=0.34375", new, count=1)
                if new != txt:
                    open(p, "w", encoding="utf-8").write(new)
                    tampered.append(os.path.basename(p))
            tv = strategy_parity_violations(lib_copy, exp_summaries, status_map, status_fallback)
            check("A9e 负控：正本副本数值链换成作废旧账 → 对账必须判红，且判红数 > 未篡改正本"
                  "（本门有判别力：非恒绿、非恒红）",
                  bool(tv) and len(tv) > len(viol),
                  "未篡改正本违规 %d 条；篡改 %d 件（%s…）后判红 %d 条：%s"
                  % (len(viol), len(tampered), tampered[:3], len(tv), tv[:2]))
        finally:
            shutil.rmtree(tmp_strat, ignore_errors=True)

    print("\n== 结果 ==")
    if FAILED:
        print("FAIL %d 项：%s" % (len(FAILED), FAILED))
        return 1
    print("全绿（gate 先筛口径已施加且已披露；材料锁已核销；策略库正本机读终裁链 ≡ 交付汇总件现役账）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
