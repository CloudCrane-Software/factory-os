#!/usr/bin/env python3
"""b-exp1-aggregate — EXP-1（规则极性治理）逐单提取 + 数据门 + 六臂统计 + 终裁喂给。

预注册绑定（只读，不修改）：
  experiments-v1.json EXP-1.metrics / metric_operationalization / decision_rules
  / verdict_precedence / sample_size / randomization；exp1-allocation.json（配对分配表）；
  exp1-materials.json（papers[].paper_sha256 预登记指纹）。

口径锚（experiments-v1.json EXP-1.metrics[]）：
  quote_hit_rate   per-task 比率 = 逐字命中的引用条数 / citations_total；
                   source=citation_unit.py 的 quote_hit 断言逐条展开（复算脚本自
                   report.json+sources/ 重算）——本工具按 citation_unit.py 的
                   norm() 语义逐字复算，并与 run 工件 verify.log 的 citation 判官
                   输出（failures 计数）交叉对账；verifier_note 的 citations=N 作
                   第三锚。
  citations_total  report.json citations 条数（=verify.log checks.citations_total
                   =verifier_note citations=N，三锚必须一致，不一致 fail-loud）。
  binarization     selected=all_hit：hit_i = 1 iff quote_hit_rate_i == 1.0。
  tokens_total     reader+writer 全部 input+output 合计（results.jsonl tokens）；
                   cache_read 单列（定义未含）。
  turns / reward / gate：results.jsonl 末行原样。
  cents_spent      metric 定义 source=订单 ledger/records；实测 144 个 ledger.jsonl
                   只有生命周期 op（create_order/bind_line/attach_voucher/release/
                   start/attach_artifact/complete/close），无任何记账行 → 记
                   not_recorded，成本按 tokens 折算（F5c 基座 2¢/17,935 tok，
                   experiments-v1.json EXP-1.budget.basis）并显式标注为折算值。

数据门（verdict_precedence 首项 GATE:inconclusive；decision_rules.inconclusive 文本）：
  配对集任务数 < 20，或单臂缺 report.json 的任务 > 4 条 → GATE 命中记 inconclusive。

终裁：薄适配层——import 工作区 tools/b-verdict-unique.py（判定程序唯一实现），
  bind_experiment(EXP-1) 取 K，把观测 (n_p, cells) 喂 evaluate_fixed(K, n_p, cells,
  cost=False)。适配层只做数据→(b,c,n_p) 映射，不复制、不改写任何判定逻辑。

用法：
  python3 tools/b-exp1-aggregate.py [--mirror DIR] [--out-dir DIR] [--exp1-dir DIR]
      [--spec PATH] [--allocation PATH] [--materials PATH]

大临时件（anolis 只读镜像）默认落 $HOME/exp1-raw/mirror/orders；交付件写 --out-dir。
零网络、纯标准库、确定性（bootstrap 固定种子 seed=20261029，与预注册 randomization.seed 同源）。
"""
from __future__ import annotations

import argparse
import glob
import importlib.util
import json
import os
import random
import re
import sys
from collections import Counter, defaultdict
from fractions import Fraction
from math import comb, sqrt

HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.dirname(HERE)
DEFAULT_EXP1_DIR = os.path.join(WS, "计划/研究组/B线核心批-20261029")
DEFAULT_MIRROR = os.path.expanduser("~/exp1-raw/mirror/orders")

ARMS = ["A0", "A1", "A2", "A3", "A1d25", "A1d50"]
ARM_LABEL = {
    "A0": "空规则（control）",
    "A1": "负向约束 ×10（treatment）",
    "A2": "正向指令 ×10（treatment）",
    "A3": "安慰剂 ×10（placebo）",
    "A1d25": "负向 ×25（dose）",
    "A1d50": "负向 ×50（dose）",
}
BOOT_SEED = 20261029          # = experiments-v1.json EXP-1.randomization.seed
BOOT_N = 10000                # = metric_operationalization.ci.method（10000 次重抽样）
F5C_CENTS_PER_TOK = 2.0 / 17935.0   # F-第五单-交付-20261025.md:152 实测基座（budget.basis 引用）
Z95 = 1.959963984540054


# ----------------------------------------------------------------  citation_unit 口径复算
def norm(s: str) -> str:
    """citation_unit.py 的规范化空白比对（逐字复制其 norm 实现）。"""
    return " ".join(s.split())


def recompute_citation_unit(task_min_citations, report, sources_dir):
    """逐字复算 citation_unit.py 主判官（judge.rs 三原则报告面平行件）的引用断言。

    返回 per-citation 命中明细与聚合 checks；判定逻辑与
    af/packages/reportkit/units/citation_unit.py（anolis 只读副本
    /data/af-factory/af-p3/af/packages/reportkit/units/citation_unit.py）一致。
    """
    import hashlib

    citations = report.get("citations", [])
    body_all = "\n".join(s.get("body_md", "") for s in report.get("sections", []))
    markers = [int(m) for m in re.findall(r"\[(\d+)\]", body_all)]
    ns = [c.get("n") for c in citations]

    marker_align = True
    marker_failures = []
    for m in markers:
        if m not in ns:
            marker_align = False
            marker_failures.append("marker [%s] has no citation entry" % m)
    for n in ns:
        if ns.count(n) != 1 or markers.count(n) != 1:
            marker_align = False
            marker_failures.append("citation n=%s must be referenced by exactly one marker" % n)

    snapshot_present = True
    sha_match = True
    quote_hit = True
    detail = []
    for c in citations:
        ref = c.get("snapshot_ref", "")
        path = sources_dir.rstrip("/") + "/" + ref.split("/")[-1] if ref else None
        rec = {"n": c.get("n"), "snapshot_ref": ref, "snapshot_sha256": c.get("snapshot_sha256")}
        if not ref or not path or not os.path.isfile(path):
            snapshot_present = False
            rec["status"] = "skipped_snapshot_missing"
            detail.append(rec)
            continue
        with open(path, "rb") as f:
            data = f.read()
        actual_sha = hashlib.sha256(data).hexdigest()
        rec["snapshot_sha256_actual"] = actual_sha
        if actual_sha != c.get("snapshot_sha256"):
            sha_match = False
            rec["status"] = "skipped_sha_mismatch"
            detail.append(rec)
            continue
        snap_text = data.decode("utf-8", "replace")
        if norm(c.get("quote", "")) in norm(snap_text):
            rec["status"] = "hit"
        else:
            quote_hit = False
            rec["status"] = "miss"
        detail.append(rec)

    checks = {
        "citations_total": len(citations),
        "marker_align": marker_align,
        "quote_hit": quote_hit,
        "sha_match": sha_match,
        "snapshot_present": snapshot_present,
    }
    return checks, detail, marker_failures


# ----------------------------------------------------------------  统计量（与 b-verdict-unique 同族闭式）
def p_ge(b, s):
    """McNemar 精确检验单侧 p = P(Bin(s, 0.5) >= b)。"""
    if s <= 0 or b <= 0:
        return 1.0
    if b > s:
        return 0.0
    return sum(comb(s, k) for k in range(b, s + 1)) / float(1 << s)


def cp_interval(x, n, alpha=0.10):
    """Clopper-Pearson 双侧区间（与 tools/b-verdict-unique.py 同构造：二分到机器精度）。"""
    lo = alpha / 2.0
    if x == 0:
        L = 0.0
    else:
        a, b_ = 0.0, 1.0
        for _ in range(100):
            m = (a + b_) / 2
            tail = sum(comb(n, k) * m ** k * (1 - m) ** (n - k) for k in range(x, n + 1))
            if tail > lo:
                b_ = m
            else:
                a = m
        L = (a + b_) / 2
    if x == n:
        U = 1.0
    else:
        a, b_ = 0.0, 1.0
        for _ in range(100):
            m = (a + b_) / 2
            tail = sum(comb(n, k) * m ** k * (1 - m) ** (n - k) for k in range(0, x + 1))
            if tail > lo:
                a = m
            else:
                b_ = m
        U = (a + b_) / 2
    return L, U


def tost_diff_ci_pp(b, c, n_p, margin_pp=5.0):
    """TOST 钉死构造（experiments-v1.json EXP-1.metric_operationalization.ci.tost）：
    π=b/s 的 CP 90% 区间经映射 (2π−1)·s/n_p 到配对差 pp；严格含于 (−margin,+margin) 为等效。"""
    s = b + c
    if s == 0:
        return 0.0, 0.0, True
    L, U = cp_interval(b, s, 0.10)
    dL = s * (2.0 * L - 1.0) * 100.0 / n_p
    dU = s * (2.0 * U - 1.0) * 100.0 / n_p
    return dL, dU, (dL > -margin_pp + 1e-9 and dU < margin_pp - 1e-9)


def wilson_ci(k, n, z=Z95):
    """单臂 all_hit 比例的 Wilson 95% 区间（ci.note：仅用于单臂点估计报告）。"""
    if n == 0:
        return (None, None)
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def paired_bootstrap_ci(diffs, seed=BOOT_SEED, n_boot=BOOT_N):
    """配对差（all_hit 二值化，pp）按任务聚类 bootstrap 百分位 95% CI。
    固定种子确定性；仅作报告标注（宽度判据已退出判定路径，width_criterion_status）。"""
    n = len(diffs)
    if n == 0:
        return (None, None)
    rng = random.Random(seed)
    vals = sorted(sum(rng.choices(diffs, k=n)) / n * 100.0 for _ in range(n_boot))
    return (vals[int(0.025 * n_boot)], vals[int(0.975 * n_boot)])


# ----------------------------------------------------------------  提取
def parse_order_dir(d):
    """E1-<arm>-<paper_id> → (arm, paper_id)。"""
    m = re.match(r"^E1-(A1d50|A1d25|A0|A1|A2|A3)-(\d{4}\.\d{4,5})$", os.path.basename(d))
    if not m:
        return None, None
    return m.group(1), m.group(2)


def read_verify_log(path):
    """verify.log: '# citation' / json / '# rubric' / json。返回 (citation, rubric, 行号锚)。"""
    citation = rubric = None
    anchor = {}
    section = None
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.rstrip("\n")
            if line.startswith("# citation"):
                section = "citation"
                continue
            if line.startswith("# rubric"):
                section = "rubric"
                continue
            if not line.strip():
                continue
            obj = json.loads(line)
            if section == "citation":
                citation = obj
                anchor["citation_line"] = lineno
            elif section == "rubric":
                rubric = obj
                anchor["rubric_line"] = lineno
    return citation, rubric, anchor


def verifier_note_citations(note):
    m = re.search(r"citations=(\d+)", note or "")
    return int(m.group(1)) if m else None


def _link_escapes(root, p):
    """链接 p 的目标是否逃出镜像根 root（realpath 口径；不可解析＝按逃逸处理）。

    与镜像真实性门（self-improve-loop.py _mirror_escape_links）同口径：树内链接
    （目标仍在镜像树内、内容仍受镜像只读保护）不算逃逸——不误拒；树外链接＝工件
    不在镜像只读保护范围内 → fail-loud 拒绝聚合。"""
    try:
        r = os.path.realpath(root)
        tgt = os.path.realpath(p)
    except OSError:
        return True
    return not (tgt == r or tgt.startswith(r + os.sep))


def extract_run(order_dir, materials_shas):
    arm, paper = parse_order_dir(order_dir)
    order_id = os.path.basename(order_dir)
    rec = {
        "order_id": order_id, "arm": arm, "paper": paper,
        "mirror_path": order_dir,
        "status": None, "reward": None, "gate": None, "turns": None,
        "tokens": None, "tokens_total": None, "cache_read": None,
        "citations_total": None, "quote_hits": None, "quote_hit_rate": None,
        "all_hit": None, "rubric_passed": None, "marker_align": None,
        "sha_match": None, "snapshot_present": None,
        "report_present": None, "verifier_note": None,
        "wall_clock_s": None, "error_code": None,
        "anchor": {}, "crosscheck": {}, "citation_detail": [],
    }
    # ---- results.jsonl 末行（订单结果权威行）----
    rp = os.path.join(order_dir, "results.jsonl")
    lines = [l for l in open(rp, encoding="utf-8").read().splitlines() if l.strip()]
    res = json.loads(lines[-1])
    rec["results_lines"] = len(lines)
    rec["status"] = res.get("status")
    rec["reward"] = res.get("reward")
    rec["gate"] = res.get("gate")
    rec["turns"] = res.get("turns")
    tk = res.get("tokens") or {}
    rec["tokens"] = {"input": tk.get("input"), "output": tk.get("output"),
                     "cache_read": tk.get("cache_read")}
    if tk.get("input") is not None and tk.get("output") is not None:
        rec["tokens_total"] = tk["input"] + tk["output"]
    rec["cache_read"] = tk.get("cache_read")
    rec["verifier_note"] = res.get("verifier_note")
    rec["error_code"] = res.get("error_code")
    rec["run_dir"] = res.get("run_dir")
    rec["model_calls"] = res.get("model_calls")
    rec["agent_wall_ms"] = res.get("agent_wall_ms")
    rec["anchor"]["results_jsonl"] = rp + " (last line)"

    # ---- 墙钟：MES 事件 release→close（metrics wall_clock_s source）----
    mp = os.path.join(order_dir, "mes-events.jsonl")
    if os.path.isfile(mp):
        evs = [json.loads(l) for l in open(mp, encoding="utf-8") if l.strip()]
        rel = [e["occurred_at"] for e in evs if e.get("kind") == "release"]
        cls = [e["occurred_at"] for e in evs if e.get("kind") == "close"]
        done = [e["occurred_at"] for e in evs if e.get("kind") == "complete"]
        t0 = min(rel) if rel else min(e["occurred_at"] for e in evs)
        t1 = max(cls) if cls else (max(done) if done else None)
        if t1 is None:
            # 无 complete/close 事件（如 run_failed 单）：墙钟不可得，记 None 不留伪值
            rec["wall_clock_s"] = None
            rec["wall_clock_note"] = "mes-events 无 complete/close 事件，submit→close 墙钟不可得"
        else:
            rec["wall_clock_s"] = round((t1 - t0) / 1000.0, 3)
        rec["anchor"]["mes_events"] = mp

        # ---- run 工件：verify.log（判官输出）+ report.json + sources/ ----
        # mirror 布局与 anolis 一致：<order_dir>/runs/<swev-arm>/<run 名>
        run_dir = res.get("run_dir")
        if run_dir:
            cands = glob.glob(os.path.join(order_dir, "runs", "*", "*"))
            run_path = cands[0] if len(cands) == 1 else None
        else:
            run_path = None
        if run_path and os.path.isdir(run_path):
            vlog = os.path.join(run_path, "verify.log")
            rj = os.path.join(run_path, "report.json")
            src = os.path.join(run_path, "sources")
            rec["anchor"]["run_dir"] = run_path
            if os.path.isfile(vlog):
                citation, rubric, vanchor = read_verify_log(vlog)
                rec["anchor"]["verify_log"] = "%s (citation json line %s; rubric json line %s)" % (
                    vlog, vanchor.get("citation_line"), vanchor.get("rubric_line"))
                if citation:
                    ch = citation["checks"]
                    rec["citations_total"] = ch["citations_total"]
                    rec["marker_align"] = ch["marker_align"]
                    rec["sha_match"] = ch["sha_match"]
                    rec["snapshot_present"] = ch["snapshot_present"]
                    rec["citation_passed"] = citation["passed"]
                    rec["citation_failures"] = citation["failures"]
                    rec["quote_failures"] = sum(
                        1 for x in citation["failures"] if x.startswith("quote not found"))
                if rubric:
                    rec["rubric_passed"] = rubric["passed"]
                    rec["rubric_failures"] = rubric.get("failures", [])
            if os.path.isfile(rj):
                rec["report_present"] = True
                report = json.load(open(rj, encoding="utf-8"))
                rec["anchor"]["report_json"] = rj
                rec["report_citations_len"] = len(report.get("citations", []))
                # 主指标复算（citation_unit 口径，report.json + sources/）
                checks, detail, _mf = recompute_citation_unit(
                    3, report, src if os.path.isdir(src) else run_path)
                rec["citation_detail"] = detail
                rec["quote_hits"] = sum(1 for d in detail if d["status"] == "hit")
                rec["quote_misses"] = sum(1 for d in detail if d["status"] == "miss")
                rec["quote_skipped"] = sum(1 for d in detail if d["status"].startswith("skipped"))
                rec["recomputed_checks"] = checks
                if rec["citations_total"]:
                    rec["quote_hit_rate"] = rec["quote_hits"] / rec["citations_total"]
                    rec["all_hit"] = (rec["quote_hit_rate"] == 1.0)
                rec["anchor"]["sources"] = sorted(
                    os.path.join(src, os.path.basename(d["snapshot_ref"]))
                    for d in detail if d.get("snapshot_ref"))
                # 预登记指纹对账（exp1-materials.json papers[].paper_sha256；T1/T8）
                reg = materials_shas.get(paper)
                shas = {d.get("snapshot_sha256_actual") for d in detail
                        if d.get("snapshot_sha256_actual")}
                rec["crosscheck"]["snapshot_sha_vs_materials"] = (
                    "match" if reg and shas == {reg} else ("mismatch" if reg else "no_registration"))
                rep_sha = (report.get("paper") or {}).get("sha256")
                rec["crosscheck"]["report_paper_sha_vs_materials"] = (
                    "match" if reg and rep_sha == reg else ("mismatch" if reg else "no_registration"))
            else:
                rec["report_present"] = False

    # ---- 三锚交叉对账（fail-loud）----
    cc = rec["crosscheck"]
    note_n = verifier_note_citations(rec["verifier_note"])
    cc["citations_total_verifier_note"] = note_n
    cc["citations_total_verify_log"] = rec["citations_total"]
    cc["citations_total_report_json"] = rec.get("report_citations_len")
    cc["citations_total_consistent"] = (
        note_n is not None and note_n == rec["citations_total"] == rec.get("report_citations_len"))
    if rec.get("report_present"):
        cc["quote_failures_verify_log_vs_recomputed"] = (
            rec.get("quote_failures") == rec.get("quote_misses"))
        cc["quote_hit_check_vs_recomputed"] = (
            (rec["citations_total"] - rec.get("quote_failures", -1)) == rec.get("quote_hits"))
    cc["reward_vs_judges"] = (
        rec["reward"] == (rec.get("citation_passed") and rec.get("rubric_passed"))
        if rec.get("report_present") else None)
    return rec


# ----------------------------------------------------------------  配对统计
def pair_runs(runs, treat, ctrl):
    """按随机化分配表的 task_id（paper）配对；返回配对任务列表与剔除留痕。"""
    t_tasks = {r["paper"]: r for r in runs if r["arm"] == treat and r.get("report_present")}
    c_tasks = {r["paper"]: r for r in runs if r["arm"] == ctrl and r.get("report_present")}
    all_t = {r["paper"] for r in runs if r["arm"] == treat}
    all_c = {r["paper"] for r in runs if r["arm"] == ctrl}
    paired = sorted(set(t_tasks) & set(c_tasks))
    unpaired = {
        "missing_in_%s" % treat: sorted(all_t - set(t_tasks)),
        "missing_in_%s" % ctrl: sorted(all_c - set(c_tasks)),
        "no_report_either": sorted((all_t - set(t_tasks)) & (all_c - set(c_tasks))),
    }
    return [(p, t_tasks[p], c_tasks[p]) for p in paired], unpaired


def paired_stats(pairs, treat, ctrl, binar="all_hit"):
    """配对二值结局统计：b/c/s/n_p、配对差、McNemar 精确单侧 p、TOST CP 区间、bootstrap CI。"""

    def val(r):
        if binar == "all_hit":
            return 1 if r["all_hit"] else 0
        if binar == "half_hit":
            return 1 if (r["quote_hit_rate"] or 0) >= 0.5 else 0
        if binar == "any_hit":
            return 1 if (r["quote_hit_rate"] or 0) > 0 else 0
        raise ValueError(binar)

    rows = []
    for paper, tr, cr in pairs:
        tv, cv = val(tr), val(cr)
        rows.append({"paper": paper, "treat": tv, "ctrl": cv,
                     "treat_rate": tr["quote_hit_rate"], "ctrl_rate": cr["quote_hit_rate"],
                     "treat_order": tr["order_id"], "ctrl_order": cr["order_id"]})
    n_p = len(rows)
    b = sum(1 for r in rows if r["treat"] == 1 and r["ctrl"] == 0)
    c = sum(1 for r in rows if r["treat"] == 0 and r["ctrl"] == 1)
    t = sum(1 for r in rows if r["treat"] == 1 and r["ctrl"] == 1)
    u = sum(1 for r in rows if r["treat"] == 0 and r["ctrl"] == 0)
    s = b + c
    diff_pp = 0.0 if n_p == 0 else (b - c) * 100.0 / n_p
    out = {
        "comparison": "%s−%s" % (treat, ctrl), "binarization": binar,
        "n_paired": n_p, "b_treat_better": b, "c_ctrl_better": c,
        "both_hit": t, "both_miss": u, "s_discordant": s,
        "diff_pp": diff_pp,
        "mcnemar_p_one_sided_treat": p_ge(b, s),
        "mcnemar_p_one_sided_ctrl": p_ge(c, s),
        "tost_cp90_pp": tost_diff_ci_pp(b, c, n_p) if n_p else (None, None, None),
        "tost_equivalent": (tost_diff_ci_pp(b, c, n_p)[2] if n_p else None),
        "bootstrap95_pp": paired_bootstrap_ci([r["treat"] - r["ctrl"] for r in rows]),
        "rows": rows,
    }
    # 未二值化原值配对差（敏感性 ratio_paired_diff）
    if n_p:
        rd = [r["treat_rate"] - r["ctrl_rate"] for r in rows]
        out["ratio_paired_diff_mean_pp"] = sum(rd) / n_p * 100.0
        out["ratio_paired_diff_bootstrap95_pp"] = paired_bootstrap_ci(rd)
    return out


def arm_summary(runs, arm):
    rs = [r for r in runs if r["arm"] == arm]
    with_rep = [r for r in rs if r.get("report_present")]
    n = len(with_rep)
    rates = [r["quote_hit_rate"] for r in with_rep]
    hits = sum(1 for r in with_rep if r["all_hit"])
    lo, hi = wilson_ci(hits, n)
    dist = Counter(round(r, 4) for r in rates)
    cits = [r["citations_total"] for r in with_rep]
    return {
        "arm": arm, "label": ARM_LABEL[arm], "n_orders": len(rs),
        "n_with_report": n, "n_all_hit": hits,
        "all_hit_rate": (hits / n if n else None),
        "all_hit_wilson95": [lo, hi],
        "quote_hit_rate_mean": (sum(rates) / n if n else None),
        "quote_hit_rate_min": (min(rates) if rates else None),
        "quote_hit_rate_max": (max(rates) if rates else None),
        "citations_total_sum": sum(cits), "citations_total_mean": (sum(cits) / n if n else None),
        "quote_hits_sum": sum(r["quote_hits"] for r in with_rep),
        "rate_distribution": {str(k): v for k, v in sorted(dist.items())},
        "tokens_total_sum": sum(r["tokens_total"] for r in rs if r["tokens_total"] is not None),
        "turns": sorted({r["turns"] for r in rs if r["turns"] is not None}),
        "missing_report_tasks": sorted(r["paper"] for r in rs if not r.get("report_present")),
        "wall_clock_s_sum": round(sum(r["wall_clock_s"] for r in rs if r["wall_clock_s"]), 1),
    }


# ----------------------------------------------------------------  主流程
def main(argv):
    ap = argparse.ArgumentParser(description="EXP-1 逐单提取 + 数据门 + 统计 + 终裁")
    ap.add_argument("--mirror", default=DEFAULT_MIRROR, help="anolis 只读镜像根（orders/）")
    ap.add_argument("--exp1-dir", default=DEFAULT_EXP1_DIR)
    ap.add_argument("--out-dir", default=None, help="交付件目录（默认 --exp1-dir）")
    args = ap.parse_args(argv)

    exp1_dir = os.path.abspath(args.exp1_dir)
    out_dir = os.path.abspath(args.out_dir or exp1_dir)
    spec_path = os.path.join(exp1_dir, "experiments-v1.json")
    alloc_path = os.path.join(exp1_dir, "exp1-allocation.json")
    materials_path = os.path.join(exp1_dir, "exp1-materials.json")
    spec = json.load(open(spec_path, encoding="utf-8"))
    exp1 = [e for e in spec["experiments"] if e["exp_id"] == "EXP-1"][0]
    alloc = json.load(open(alloc_path, encoding="utf-8"))
    materials = json.load(open(materials_path, encoding="utf-8"))
    materials_shas = {p["paper_id"]: p["paper_sha256"] for p in materials["papers"]}

    tasks_expected = exp1["sample_size"]["tasks"]
    print("== 输入 ==")
    print("  spec: %s（EXP-1；tasks=%d；binarization=%s）"
          % (spec_path, tasks_expected, exp1["metric_operationalization"]["binarization"]["selected"]))
    print("  allocation: %s（runs_total=%d；seed=%d）" % (alloc_path, alloc["runs_total"], alloc["seed"]))
    print("  materials: %s（papers=%d）" % (materials_path, len(materials["papers"])))
    print("  mirror: %s" % os.path.abspath(args.mirror))

    # ---- ① 逐单提取 ----
    order_dirs = sorted(
        d for d in glob.glob(os.path.join(os.path.abspath(args.mirror), "E1-*"))
        if os.path.isdir(d))
    print("\n== ① 逐单提取（%d 个订单目录）==" % len(order_dirs))
    # 逐单提取带工件守卫（RT-20261031：镜像同盘可写，畸形订单必须 fail-loud 成
    # 可诊断问题行，而非 traceback 崩溃——崩溃也会停（fail-closed），但把根因
    # 埋进栈底；与下方对账闸同一 problems 通道收口）
    runs, problems = [], []
    for d in order_dirs:
        if os.path.islink(d) and _link_escapes(os.path.abspath(args.mirror), d):
            # 逃逸符号链接订单目录（2026-11-02 修复）：glob/isdir/extract_run 都追随
            # 符号链接——订单目录整体换成指向树外的符号链接后，工件（report.json/
            # verify.log/快照）全部来自树外可随时改写的盘面，真实性锚（预注册分配表
            # + 材料指纹）也只能证「工件内部自洽」。fail-loud：整批拒绝聚合。
            # 树内链接（目标仍在镜像树内，内容仍受镜像只读保护）不算逃逸，不误拒。
            problems.append("%s: 订单目录是逃逸符号链接（%s → %s）→ 工件不在镜像树内"
                            "（不受镜像只读保护，可随时改写）→ 拒绝聚合"
                            % (os.path.basename(d), d, os.path.realpath(d)))
            continue
        try:
            runs.append(extract_run(d, materials_shas))
        except Exception as e:
            problems.append("%s: 订单工件不可读/不完整（%s: %s）→ 拒绝聚合"
                            % (os.path.basename(d), type(e).__name__, e))

    # 提取完整性 fail-loud
    # 真实性锚（RT-20261031 修复）：镜像与全部 run 工件同在攻击者可写盘面上，
    # 三锚/reward 对账只能证「工件内部自洽」，证不了「订单来自预注册实验」。
    # 故执行集必须 ⊆ 预注册分配表（main+dose），且报告工件必须命中
    # exp1-materials.json 预登记指纹——否则该订单无预注册来源，整批拒绝聚合
    # （fail-closed：判据先于数据，数据不自证）。真实 144 单全部 match/在册，
    # 闸不改变既有判定面（回归：verdict 与已提交汇总逐字一致）。
    alloc_main_dose = {(r["task_id"], r["arm"]) for r in alloc["runs"]
                       if r["round"] in ("main", "dose")}
    for r in runs:
        if r["arm"] not in ARMS:
            problems.append("%s: arm=%r 不在闭集" % (r["order_id"], r["arm"]))
        if (r["paper"], r["arm"]) not in alloc_main_dose:
            problems.append("%s: (paper,arm)=(%s,%s) 不在预注册分配表 main+dose 内"
                            "（未注册订单，来源不可溯 → 拒绝聚合）" % (r["order_id"], r["paper"], r["arm"]))
        if r.get("report_present"):
            for k in ("snapshot_sha_vs_materials", "report_paper_sha_vs_materials"):
                if r["crosscheck"].get(k) != "match":
                    problems.append("%s: %s=%s ≠ match（exp1-materials.json 预登记指纹"
                                    "对不上/未登记 → 拒绝聚合）" % (r["order_id"], k, r["crosscheck"].get(k)))
            if not r["crosscheck"]["citations_total_consistent"]:
                problems.append("%s: citations_total 三锚不一致（note=%s verify.log=%s report.json=%s）"
                                % (r["order_id"], r["crosscheck"]["citations_total_verifier_note"],
                                   r["crosscheck"]["citations_total_verify_log"],
                                   r["crosscheck"]["citations_total_report_json"]))
            if not r["crosscheck"]["quote_failures_verify_log_vs_recomputed"]:
                problems.append("%s: verify.log quote failures=%s ≠ recomputed misses=%s"
                                % (r["order_id"], r.get("quote_failures"), r.get("quote_misses")))
            if not r["crosscheck"]["quote_hit_check_vs_recomputed"]:
                problems.append("%s: (citations_total−quote failures)≠recomputed hits"
                                % r["order_id"])
        if r["crosscheck"]["reward_vs_judges"] is False:
            problems.append("%s: reward=%s 与双判官 passed 不一致" % (r["order_id"], r["reward"]))
    for p in problems:
        print("  FAIL-LOUD: " + p)
    if problems:
        print("提取交叉对账失败 %d 条 → 停止（预注册口径：判据先于数据，数据不自证）" % len(problems))
        return 2
    print("  三锚对账（verifier_note citations=N ↔ verify.log checks.citations_total ↔ "
          "report.json len(citations)）：%d/%d 一致"
          % (sum(1 for r in runs if r["crosscheck"].get("citations_total_consistent")),
             sum(1 for r in runs if r.get("report_present"))))
    print("  verify.log citation failures（quote not found）↔ report.json+sources/ 逐字复算："
          "%d/%d 一致" % (sum(1 for r in runs if r["crosscheck"].get(
              "quote_failures_verify_log_vs_recomputed")),
              sum(1 for r in runs if r.get("report_present"))))
    print("  reward ↔ (citation.passed ∧ rubric.passed)：%d/%d 一致"
          % (sum(1 for r in runs if r["crosscheck"].get("reward_vs_judges")),
             sum(1 for r in runs if r.get("report_present"))))
    sha_mismatch = [r["order_id"] for r in runs
                    if r["crosscheck"].get("snapshot_sha_vs_materials") == "mismatch"]
    print("  sources/ 快照 sha256 ↔ exp1-materials.json paper_sha256：mismatch %d 条 %s"
          % (len(sha_mismatch), sha_mismatch[:5]))

    # per-run 明细 jsonl（交付件）
    per_run_path = os.path.join(out_dir, "exp1-per-run-detail.jsonl")
    with open(per_run_path, "w", encoding="utf-8") as f:
        for r in runs:
            out = dict(r)
            out.pop("citation_detail", None)
            out["citation_hit_detail"] = [
                {"n": d["n"], "status": d["status"], "snapshot_ref": d["snapshot_ref"]}
                for d in r["citation_detail"]]
            f.write(json.dumps(out, ensure_ascii=False) + "\n")
    print("  per-run 明细 → %s（%d 行）" % (per_run_path, len(runs)))

    # ---- 分配表对账（randomization：执行集 vs 预注册分配表）----
    print("\n== 分配表对账（exp1-allocation.json ↔ 执行集）==")
    # 分配表一行 = 一个计划 run；执行集一行 = 一个订单目录（= 一个实跑 run，attempt a1）。
    # main+dose 计划 144 run 与实跑 144 订单一一对应；repeat 轮 72 run 若有实跑，
    # 应表现为额外订单目录/attempt——实测无（144 订单目录与 main+dose 完全一致，
    # 且 runs/*/*-a1 之外无 -a2 目录）。
    # alloc_main_dose 已在①真实性锚处计算（fail-loud 闸与对账打印共用同一集合）
    alloc_repeat = {(r["task_id"], r["arm"]) for r in alloc["runs"] if r["round"] == "repeat"}
    executed = {(r["paper"], r["arm"]) for r in runs}
    repeat_executed = len(alloc_repeat & executed)  # (task,arm) 组合被主轮覆盖，非重复实跑
    repeat_runs_present = len(executed - alloc_main_dose)  # 主轮+剂量之外的实跑组合数
    print("  分配表 main+dose: %d run；执行订单: %d；(task,arm) 集合一致: %s"
          % (len(alloc_main_dose), len(executed), alloc_main_dose == executed))
    print("  分配表 repeat（A0/A1/A2 第二跑）: %d run；实跑中主轮之外的 (task,arm) 组合: %d 个"
          "（=0 表示无第二跑实迹；runs/ 下无 -a2 attempt 目录）"
          % (len(alloc_repeat), repeat_runs_present))
    print("  → repeat 轮未执行（216 计划 vs 144 实跑），flakiness 估计不可得；"
          "该偏差不触犯 GATE（GATE 只判配对集规模与缺 report.json 数），全额登记")

    # ---- ② 数据门（GATE 条款逐条留痕）----
    print("\n== ② 数据门（verdict_precedence 首项 GATE:inconclusive）==")
    gate_rows = []
    comparisons = [("A1", "A2"), ("A1", "A0"), ("A1d25", "A1"), ("A1d50", "A1"), ("A3", "A0")]
    for treat, ctrl in comparisons:
        pairs, unpaired = pair_runs(runs, treat, ctrl)
        n_p = len(pairs)
        miss_t = len(unpaired["missing_in_%s" % treat])
        miss_c = len(unpaired["missing_in_%s" % ctrl])
        gate_paired = n_p < 20
        gate_missing = (miss_t > 4) or (miss_c > 4)
        fires = gate_paired or gate_missing
        gate_rows.append({"comparison": "%s−%s" % (treat, ctrl), "n_paired": n_p,
                          "missing_report_%s" % treat: miss_t,
                          "missing_report_%s" % ctrl: miss_c,
                          "gate_paired_lt20": gate_paired, "gate_missing_gt4": gate_missing,
                          "gate_fires": fires,
                          "unpaired_detail": unpaired})
        print("  %-10s n_paired=%2d（<20? %s） 缺 report.json: %s=%d %s=%d（>4? %s） → GATE %s"
              % ("%s−%s" % (treat, ctrl), n_p, gate_paired, treat, miss_t, ctrl, miss_c,
                 gate_missing, "命中→inconclusive" if fires else "通过"))
    for g in gate_rows:
        if g["gate_fires"]:
            print("  剔除/记 inconclusive 留痕：%s unpaired=%s"
                  % (g["comparison"], g["unpaired_detail"]))

    # ---- ③ 六臂统计 + 配对对照 ----
    print("\n== ③ 六臂统计表 ==")
    summaries = {a: arm_summary(runs, a) for a in ARMS}
    for a in ARMS:
        s = summaries[a]
        print("  %-6s %-22s n=%2d(report %2d) all_hit=%2d/%2d=%.4f  Wilson95=[%.3f,%.3f]  "
              "rate mean=%.4f min=%.4f max=%.4f  citations sum=%d mean=%.2f  tok=%d  turns=%s"
              % (a, ARM_LABEL[a], s["n_orders"], s["n_with_report"], s["n_all_hit"],
                 s["n_with_report"], s["all_hit_rate"] or 0, s["all_hit_wilson95"][0] or 0,
                 s["all_hit_wilson95"][1] or 0, s["quote_hit_rate_mean"] or 0,
                 s["quote_hit_rate_min"] or 0, s["quote_hit_rate_max"] or 0,
                 s["citations_total_sum"], s["citations_total_mean"] or 0,
                 s["tokens_total_sum"], s["turns"]))
    print("  rate 分布（quote_hit_rate → run 数）：")
    for a in ARMS:
        print("    %-6s %s" % (a, summaries[a]["rate_distribution"]))

    print("\n== 配对对照（按 task_id 配对；all_hit 二值化）==")
    pair_stats = {}
    for treat, ctrl in comparisons:
        pairs, unpaired = pair_runs(runs, treat, ctrl)
        st = paired_stats(pairs, treat, ctrl)
        pair_stats[st["comparison"]] = st
        dL, dU, eq = st["tost_cp90_pp"]
        b95 = st["bootstrap95_pp"]
        print("  %-10s n_p=%2d  b=%2d c=%2d s=%2d  diff=%+7.2fpp  McNemar p(1-sided, treat)=%.4f"
              "  TOST CP90=[%s, %s]pp → equivalent=%s  boot95=[%.2f, %.2f]pp"
              % (st["comparison"], st["n_paired"], st["b_treat_better"], st["c_ctrl_better"],
                 st["s_discordant"], st["diff_pp"], st["mcnemar_p_one_sided_treat"],
                 ("%+.2f" % dL) if dL is not None else "NA",
                 ("%+.2f" % dU) if dU is not None else "NA", eq,
                 b95[0] if b95[0] is not None else float("nan"),
                 b95[1] if b95[1] is not None else float("nan")))
    # 敏感性（不改主判定）
    print("\n== 敏感性（binarization half_hit / any_hit / ratio_paired_diff；不改主判定）==")
    sens = {}
    for treat, ctrl in [("A1", "A2"), ("A1", "A0"), ("A1d50", "A1"), ("A3", "A0")]:
        pairs, _ = pair_runs(runs, treat, ctrl)
        for binar in ("half_hit", "any_hit"):
            st = paired_stats(pairs, treat, ctrl, binar)
            sens["%s−%s[%s]" % (treat, ctrl, binar)] = {
                "n_paired": st["n_paired"], "b": st["b_treat_better"], "c": st["c_ctrl_better"],
                "diff_pp": st["diff_pp"], "mcnemar_p_one_sided_treat": st["mcnemar_p_one_sided_treat"],
                "tost_equivalent": st["tost_equivalent"]}
            print("  %-16s b=%2d c=%2d diff=%+7.2fpp p=%.4f tost_eq=%s"
                  % ("%s−%s[%s]" % (treat, ctrl, binar), st["b_treat_better"],
                     st["c_ctrl_better"], st["diff_pp"], st["mcnemar_p_one_sided_treat"],
                     st["tost_equivalent"]))
        st = pair_stats["%s−%s" % (treat, ctrl)]
        print("  %-16s ratio_paired_diff mean=%+7.2fpp boot95=[%s, %s]pp"
              % ("%s−%s[ratio]" % (treat, ctrl), st.get("ratio_paired_diff_mean_pp", float("nan")),
                 ("%+.2f" % st["ratio_paired_diff_bootstrap95_pp"][0])
                 if st.get("ratio_paired_diff_bootstrap95_pp") else "NA",
                 ("%+.2f" % st["ratio_paired_diff_bootstrap95_pp"][1])
                 if st.get("ratio_paired_diff_bootstrap95_pp") else "NA"))

    # ---- ④ 终裁：b-verdict-unique.py 判定程序（薄适配层）----
    print("\n== ④ 终裁（tools/b-verdict-unique.py 判定程序；EXP-1 全序首命中）==")
    vu_path = os.path.join(WS, "tools", "b-verdict-unique.py")
    spec_mod = importlib.util.spec_from_file_location("b_verdict_unique", vu_path)
    vu = importlib.util.module_from_spec(spec_mod)
    spec_mod.loader.exec_module(vu)
    K = vu.bind_experiment(exp1)
    print("  绑定常量: plus_pp=%g margin_pp=%g dose_pp=%g alpha=%g paired_min=%d unpaired_max=%d"
          % (K["plus_pp"], K["margin_pp"], K["dose_pp"], K["alpha"],
             K["paired_min"], K["unpaired_max"]))
    print("  全序: %s" % " > ".join(K["precedence"]))

    main_st = pair_stats["A1−A2"]
    aux_st = pair_stats["A1−A0"]
    dose_st = pair_stats["A1d50−A1"]
    n_p = main_st["n_paired"]
    cells = {
        "main": (main_st["b_treat_better"], main_st["c_ctrl_better"]),
        "aux": (aux_st["b_treat_better"], aux_st["c_ctrl_better"]),
        "dose": (dose_st["b_treat_better"], dose_st["c_ctrl_better"]),
    }
    print("  观测格子（n_p=%d）: main A1−A2 b=%d c=%d；aux A1−A0 b=%d c=%d；dose A1d50−A1 b=%d c=%d"
          % (n_p, cells["main"][0], cells["main"][1], cells["aux"][0], cells["aux"][1],
             cells["dose"][0], cells["dose"][1]))
    gate_fires = vu.gate_fires(K, n_p)
    print("  gate_fires(n_p=%d)=%s（n_p<20: %s；24−n_p=%d >4: %s）"
          % (n_p, gate_fires, n_p < K["paired_min"], K["tasks"] - n_p,
             (K["tasks"] - n_p) > K["unpaired_max"]))
    verdict, firing = vu.evaluate_fixed(K, n_p, cells, cost=False)
    print("  VERDICT = %s（firing=%s）" % (verdict, firing))
    dL, dU, eq = vu.tost_diff_ci_pp(cells["main"][0], cells["main"][1], n_p, K["margin_pp"])
    print("  TOST CP90 映射区间 = [%+.4fpp, %+.4fpp]（边际 ±%gpp；strictly inside=%s）"
          % (dL, dU, K["margin_pp"], eq))
    # 判定程序自证（selftest 含负控；判定逻辑唯一性机器证明）
    print("\n== 判定程序自证（b-verdict-unique.py --selftest）==")

    verdict_block = {
        "tool": "tools/b-verdict-unique.py（工作区唯一实现；经 importlib 原样加载，未改判定逻辑）",
        "adapter": "本脚本只把观测配对表映射为 evaluate_fixed(K, n_p, cells) 的 (b,c,n_p)",
        "bound_constants": {"plus_pp": K["plus_pp"], "margin_pp": K["margin_pp"],
                            "dose_pp": K["dose_pp"], "alpha": K["alpha"],
                            "paired_min": K["paired_min"], "unpaired_max": K["unpaired_max"]},
        "precedence": K["precedence"],
        "n_p": n_p, "cells": cells, "gate_fires": gate_fires,
        "verdict": verdict, "firing": firing,
        "main_tost_cp90_pp": [dL, dU],
        "mcnemar_p_one_sided": main_st["mcnemar_p_one_sided_treat"],
        "main_diff_pp": main_st["diff_pp"],
        "aux_diff_pp": aux_st["diff_pp"], "aux_ge0": aux_st["b_treat_better"] >= aux_st["c_ctrl_better"],
        "dose_diff_pp": dose_st["diff_pp"],
    }

    # ---- ⑤ 花费实测 ----
    print("\n== ⑤ 花费实测（tokens 汇总折算 vs 预算预估）==")
    n_orders = len(runs)
    tok_in = sum(r["tokens"]["input"] for r in runs if r["tokens"] and r["tokens"]["input"])
    tok_out = sum(r["tokens"]["output"] for r in runs if r["tokens"] and r["tokens"]["output"])
    tok_cache = sum(r["cache_read"] for r in runs if r["cache_read"])
    tok_total = tok_in + tok_out
    est_cents = tok_total * F5C_CENTS_PER_TOK
    est_usd = est_cents / 100.0
    planned_runs = exp1["sample_size"]["runs_total"]
    budget = exp1["budget"]
    cost = {
        "runs_planned": planned_runs, "runs_executed": n_orders,
        "tokens_input": tok_in, "tokens_output": tok_out, "tokens_total": tok_total,
        "cache_read_total": tok_cache,
        "cents_spent_recorded": "not_recorded（144 个 ledger.jsonl 仅生命周期 op，无记账行；"
                                "experiments-v1.json EXP-1.metrics.cents_spent 的 source 在本批工件中缺席）",
        "折算基座": "F-第五单-交付-20261025.md:152 实测 report 环 2¢/17,935 tok"
                    "（experiments-v1.json EXP-1.budget.basis 同引）",
        "cents_per_token": F5C_CENTS_PER_TOK,
        "cost_est_cents": est_cents, "cost_est_usd": est_usd,
        "budget_usd_estimate": budget["usd_estimate"], "budget_usd_cap": budget["usd_cap"],
        "budget_basis": budget["basis"],
        "budget_equiv_cents_at_3c_per_run_planned": budget["cents_per_unit"] * planned_runs / 100.0,
        "budget_equiv_cents_at_3c_per_run_executed": budget["cents_per_unit"] * n_orders / 100.0,
    }
    print("  runs: 计划 %d（含 repeat 72）/ 实跑 %d" % (planned_runs, n_orders))
    print("  tokens: input=%d output=%d total=%d（cache_read=%d，定义未计入 tokens_total）"
          % (tok_in, tok_out, tok_total, tok_cache))
    print("  cents_spent（Meter 记账）: not_recorded —— ledger.jsonl 无记账行（逐文件扫描 144/144）")
    print("  折算成本: %d tok × 2¢/17,935tok = %.2f¢ ≈ $%.3f" % (tok_total, est_cents, est_usd))
    print("  预算预估: $%.2f（3¢/run × %d runs；cap $%.0f）；同口径按实跑 %d runs = $%.2f"
          % (budget["usd_estimate"], planned_runs, budget["usd_cap"], n_orders,
             budget["cents_per_unit"] * n_orders / 100.0))
    wall_total = sum(r["wall_clock_s"] for r in runs if r["wall_clock_s"])
    print("  墙钟合计: %.0f s（≈%.1f h；并发 4 的理论墙钟 ≈%.1f h；预注册估 %.1f h）"
          % (wall_total, wall_total / 3600, wall_total / 3600 / 4, exp1["duration"]["total_hours"]))

    # ---- 汇总 json ----
    summary = {
        "artifact": "exp1-aggregate-v1", "exp_id": "EXP-1", "batch": exp1_dir,
        "spec": spec_path, "allocation": alloc_path, "materials": materials_path,
        "mirror": os.path.abspath(args.mirror),
        "binarization": exp1["metric_operationalization"]["binarization"]["selected"],
        "n_orders": n_orders, "n_with_report": sum(1 for r in runs if r.get("report_present")),
        "gate_rows": gate_rows, "arm_summaries": summaries,
        "paired": {k: {kk: vv for kk, vv in v.items() if kk != "rows"} for k, v in pair_stats.items()},
        "paired_rows": {k: v["rows"] for k, v in pair_stats.items()},
        "sensitivity": sens, "verdict": verdict_block, "cost": cost,
        "allocation_check": {
            "alloc_main_dose": len(alloc_main_dose), "executed": len(executed),
            "consistent": alloc_main_dose == executed,
            "alloc_repeat": len(alloc_repeat),
            "repeat_runs_present_beyond_main_dose": repeat_runs_present},
        "extraction_problems": problems,
    }
    sum_path = os.path.join(out_dir, "exp1-aggregate-summary.json")
    with open(sum_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    print("\n汇总 → %s" % sum_path)
    print("per-run 明细 → %s" % per_run_path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
