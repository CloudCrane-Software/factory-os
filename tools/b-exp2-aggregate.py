#!/usr/bin/env python3
"""b-exp2-aggregate — EXP-2（双模型 vs 单模型，通道对照）逐单提取 + 数据门 + 五臂统计 + 终裁喂给。

预注册绑定（只读，不修改）：
  experiments-v1.json EXP-2.metrics / metric_operationalization / decision_rules
  / verdict_precedence / sample_size / randomization；exp2-allocation.json（配对分配表）；
  exp2-materials.json（papers[].paper_sha256 预登记指纹）。

口径锚（experiments-v1.json EXP-2.metrics[]）：
  quote_hit_rate   per-task 比率 = 逐字命中的引用条数 / citations_total；
                   source=citation_unit.py 的 quote_hit 断言逐条展开（复算脚本自
                   report.json+sources/ 重算，与 citation_unit.py 的 norm() 语义逐字
                   一致）——与 run 工件判官输出（verify.log / judge-citation.json）
                   交叉对账；manifest/verifier_note 的 citations=N 作第三锚。
  binarization     selected=all_hit：hit_i = 1 iff quote_hit_rate_i == 1.0。
  tokens_total     report 臂=订单 records（results.jsonl tokens）；工作流臂 ask API
                   不暴露 usage → not_recorded（成本维度显式标注，不伪造）。
  wall_clock_s     report 臂=MES 事件 release→close；工作流臂=not_recorded。

数据门（verdict_precedence 首项 GATE:inconclusive；EXP-2 数据门=配对集任务数 < 20）：
  主对比 B2−B0 的配对集任务数不足 20 → GATE 命中记 inconclusive。
  （EXP-2 的 K.unpaired_max=None：预注册未设单臂缺失上限条，缺失任务只压缩 n_p。）

T8 输入核面（预注册 threats T8 的 verify 步骤：登记 sources/ 快照数与预登记 sha256 一致）：
  每 run 核 sources/ 文件数==1 且快照 sha256==材料预登记值。违反者=该 run 摄取输入
  非冻结快照（reader 绕过 local_path 抓了实时内容）→ 不计入臂统计与配对集，全额
  登记（t8_violations）。实测（2026-10-29）：B0 臂 0 例、B1 臂 1 例（E2-B1-2610.37161，
  sources=4）。与提取对账失败（三锚不一致等）区分：后者 fail-loud 停跑（数据不自证），
  前者是已登记的输入违约，按排除处理。实现按 sources/ 目录本身核（2026-10-31 修复：
  原经 citations.snapshot_ref 文件名解析取 sha 集合——writer 把引用写成非落盘文件名
  时解析失败→空集→输入干净的 run 被误判违约剔除；实测 WF-B4-2610.35767，其输入
  干净、真缺陷在 writer 引用元数据，归 quote 核面不影响 T8）。

预注册 gate 先筛（2026-11-02 红队确证修复项；EXP-2.metrics[] 四项 role="gate"）：
  预注册来源=experiments-v1.json EXP-2.metrics[] 中 role="gate" 的四项：
    marker_align / sha_match / snapshot_present（source=citation_unit.py）
    rubric_passed（source=rubric_unit.py，R1-R5 全过）
  威胁 T3 mitigation 原文：「合并提示词冻结 + 合并器档位登记 + marker_align/sha_match
  作 gate 指标先筛」——gate 指标先筛（不是事后补登记）。
  施加口径：
    · 引用侧三项（marker_align/sha_match/snapshot_present）→ 主分析集硬筛：gate 不通
      过的 run 不进臂统计与配对集，全额登记（prereg_gate.gate_excluded）。依据：
      ①T3 明文指定 marker_align/sha_match 先筛；②binarization.rationale 原文「选
      all_hit 是因为引用完整性是门禁型指标……且与 citation_unit 的 passed 语义一致」
      ——all_hit 只有在引用侧 gate 全过时才真等于 citation_unit.passed（实测 3 例
      marker_align=False 而 quote 全命中者曾被按 all_hit=True 计入五臂率与 McNemar
      格子，判官 passed=False，与该 rationale 直接冲突）。
    · rubric_passed → 不作主分析集硬筛，但必须显式登记敏感性：它判的是被测臂产出
      报告的 R1-R5 质量（结果侧量），按它筛=对结果变量取样；且实测若加筛，B2 臂
      eligible 归零（rubric R1「节 id 闭集」在工作流臂 70/72 结构性失败，通道差异
      所致，见 exp2-报告.md §9 效度限制 2）→ 主对比不可测。故按预注册 paired_set
      原文「citation/rubric 双判官都跑完」口径（判官须跑完）入集，rubric gate 作
      敏感性口径全额登记（prereg_gate.rubric_gate_sensitivity）。
  门未弱化：gate 判据取自预注册 metrics[] 原文（role=gate 项集），实现处逐项对账
  （tools/test-exp2-gate.py 回归门：聚合器施加集 + 已披露集 == 预注册 role=gate 集）。

预注册锁核销（2026-11-03 修复项）：exp2-lock.json 登记 exp2-materials.json 的 sha256
  预注册锁（锁件原文：材料任何改动须重算本锁并记新 generated_at，否则判为预注册漂移）。
  本聚合器是 EXP-2 账目的唯一生成者 → 锁核销落在这里（verify_materials_lock）：开跑先
  实算材料件 sha256 与锁登记值比对，失配/锁缺失/锁不可解析 → fail-loud 不出账（退出码
  2，不写汇总件/逐 run 明细/偏差登记件）；核销结果（锁登记值 + 实算值 + 结论）随汇总件
  落盘 → 事后可对账。修复前的缺口：材料件被改后聚合器照算另一套账目（B2−B0 +4.76pp
  → +5.00pp，跨预注册 +5pp 确认阈），全程零句提到锁/漂移，常驻门 test-exp2-gate.py 仍
  判全绿，交付汇总件自身也不记 materials 的 sha256（事后无从发现）。

终裁：薄适配层——import 工作区 tools/b-verdict-unique.py（判定程序唯一实现），
  bind_experiment(EXP-2) 取 K，把观测 (n_p, cells) 喂 evaluate_fixed(K, n_p, cells,
  cost)。适配层只做数据→(b,c,n_p) 映射，不复制、不改写任何判定逻辑。
  部分臂未到齐 → 不出终裁，如实记 pending（只有五臂（B0/B2/B3/B4 判据臂 + B1 描述臂）
  全部有数据才终裁；B1 是 model-tier-control 描述臂，不进 decision_rules）。

用法：
  python3 tools/b-exp2-aggregate.py [--mirror DIR] [--exp2-dir DIR] [--wf-dir DIR]
      [--out-dir DIR] [--spec PATH] [--allocation PATH] [--materials PATH]

数据源：
  report 臂（B0/B1）：anolis 只读镜像 <mirror>/E2-*/（orders/ 全套）
  工作流臂（B2/B3/B4）：<wf-dir>/{B2,B3,B4}/<paper_id>/{report.json,sources/,judge-*.json}
                        + <exp2-dir>/exp2-wf-manifest.jsonl
零网络、纯标准库、确定性（bootstrap 固定种子 seed=20261029，与预注册 randomization.seed 同源）。
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import importlib.util
import json
import os
import random
import re
import sys
import time
from collections import Counter, defaultdict
from fractions import Fraction
from math import comb, sqrt

HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.dirname(HERE)
DEFAULT_EXP2_DIR = os.path.join(WS, "计划/研究组/实验批-20261029")
DEFAULT_MIRROR = os.path.expanduser("~/exp2-raw/mirror/orders")
DEFAULT_WF_DIR = os.path.expanduser("~/exp2-wf-out")

ARMS = ["B0", "B1", "B2", "B3", "B4"]
# 臂文案与模型身份=实际执行（2026-10-30 通道失效偏差后；预注册原文 experiments-v1.json
# EXP-2.arms[].label 不改、sha 锁材料件不改）。偏差登记处：exp2-workflow.dwf.ts:129-134
# 与 exp2-报告.md §9 五臂表模型列。预注册 B2/B3/B4 基座 step-5 → 实际改走 minimax 家族：
# B2=m31f+m3、B3=2×m31f、B4=m31f。后果：B4−B0 不再是预注册语义「与 B0 同模型」的纯
# 通道对照（B4=m31f vs B0=step-5，通道+基座两因子混杂）；同模型跨通道对照相应移至
# B4−B1（均 m31f/mavis-m31f，dwf 注释登记）。
ARM_LABEL = {
    "B0": "单模型 step-5（reader+writer，report 环）",
    "B1": "单模型 minimax（mavis-m31f，report 环）",
    "B2": "双模型交叉（m31f + m3 reader，工作流；2026-10-30 通道偏差后实际执行）",
    "B3": "自洽对照（2× m31f reader，工作流；2026-10-30 通道偏差后实际执行）",
    "B4": "通道对照（工作流内单模型 m31f；同模型跨通道对照臂=B1，≠B0 基座 step-5）",
}
ARM_MODELS = {
    "B0": ["step-5（new-provider/step-5-preview，report 环 profile）"],
    "B1": ["mavis-m31f（minimax 家族，report 环 profile）"],
    "B2": ["minimax/Minimax-M3.1-Flash-Preview", "minimax/MiniMax-M3"],
    "B3": ["minimax/Minimax-M3.1-Flash-Preview", "minimax/Minimax-M3.1-Flash-Preview"],
    "B4": ["minimax/Minimax-M3.1-Flash-Preview"],
}
#: 臂→模型指派（机器可读）——见 ARM_MODEL_ASSIGNMENT；ARM_MODELS 的散文串保留
#: （人读面），机器面以 ARM_MODEL_ASSIGNMENT 逐臂 model_ids 为准（登记件真源）；
#: build_deviation_ledger 内做结构自检（readers/writer ⊆ model_ids；散文串逐臂在位），
#: 不一致即 fail-loud。
ARM_CHANNEL = {"B0": "report-unit", "B1": "report-unit",
               "B2": "workflow", "B3": "workflow", "B4": "workflow"}
# 臂→模型指派（机器可读；实际执行）。sha 锁材料件 exp2-materials.json 的
# spec.workflow_templates.models 只登记两个模型（step-5 / minimax）、**无「臂→模型」
# 指派字段** → 指派登记在机器可读偏差登记件 exp2-deviation-ledger.json（本件为唯一
# 真源；聚合摘要 arm_summaries[*].model_assignment 与工作流运行记录 manifest 行都引它）。
ARM_MODEL_ASSIGNMENT = {
    "B0": {"channel": "report-unit", "profile": "step-5",
           "endpoint_model": "step-5-preview",
           "readers": ["new-provider/step-5-preview"], "writer": "new-provider/step-5-preview",
           "model_ids": ["new-provider/step-5-preview"],
           "source": "af/crates/af-bench/src/main.rs:237-251（profile step-5 → model step-5-preview）"},
    "B1": {"channel": "report-unit", "profile": "mavis-m31f",
           "endpoint_model": "MiniMax-M3.1-Flash-Preview",
           "readers": ["minimax/Minimax-M3.1-Flash-Preview"],
           "writer": "minimax/Minimax-M3.1-Flash-Preview",
           "model_ids": ["minimax/Minimax-M3.1-Flash-Preview"],
           "source": "af/crates/af-bench/src/main.rs:174-186（profile mavis-m31f → model MiniMax-M3.1-Flash-Preview）"},
    "B2": {"channel": "workflow",
           "readers": ["minimax/Minimax-M3.1-Flash-Preview", "minimax/MiniMax-M3"],
           "writer": "minimax/Minimax-M3.1-Flash-Preview",
           "model_ids": ["minimax/Minimax-M3.1-Flash-Preview", "minimax/MiniMax-M3"],
           "source": "计划/研究组/实验批-20261029/exp2-workflow.dwf.ts:272-277（ARMS[].readers/writer_model）"},
    "B3": {"channel": "workflow",
           "readers": ["minimax/Minimax-M3.1-Flash-Preview", "minimax/Minimax-M3.1-Flash-Preview"],
           "writer": "minimax/Minimax-M3.1-Flash-Preview",
           "model_ids": ["minimax/Minimax-M3.1-Flash-Preview"],
           "source": "计划/研究组/实验批-20261029/exp2-workflow.dwf.ts:281-286（ARMS[].readers/writer_model）"},
    "B4": {"channel": "workflow",
           "readers": ["minimax/Minimax-M3.1-Flash-Preview"],
           "writer": "minimax/Minimax-M3.1-Flash-Preview",
           "model_ids": ["minimax/Minimax-M3.1-Flash-Preview"],
           "source": "计划/研究组/实验批-20261029/exp2-workflow.dwf.ts:290-292（ARMS[].readers/writer_model）"},
}
#: 偏差登记件（机器可读；本脚本生成）。正本 experiments-v1.json（只读）与 sha 锁材料件
#: exp2-materials.json 都不可改 → 已发生的通道/基座偏差登记于此；判定程序
#: tools/b-verdict-unique.py 从本件取通道对照绑定（不硬绑预注册的 B4−B0）。
DEV_LEDGER_NAME = "exp2-deviation-ledger.json"
DEV_ID = "EXP2-DEV-001"
BOOT_SEED = 20261029          # = experiments-v1.json EXP-2.randomization.seed
BOOT_N = 10000                # = metric_operationalization.ci.method（10000 次重抽样）
F5C_CENTS_PER_TOK = 2.0 / 17935.0   # F-第五单-交付-20261025.md:152 实测基座（budget.basis 引用）
Z95 = 1.959963984540054


# ----------------------------------------------------------------  exp2-lock 预注册锁核销
#: exp2-lock.json —— exp2-materials.json 的 sha256 预注册锁（锁件原文：「材料任何改动须
#: 重算本锁并记新 generated_at，否则判为预注册漂移」）。本聚合器是 EXP-2 账目的唯一
#: 生成者 → 锁核销必须落在这里：锁失配 = 不得出账（fail-loud）。修复前的缺口（实测）：
#: 材料件被改后聚合器照算另一套账目（B2−B0 +4.76pp → +5.00pp，跨预注册 +5pp 确认阈），
#: 全程零句提到锁/漂移，常驻门 tools/test-exp2-gate.py 仍判「全绿」；交付汇总件自身
#: 不记 materials 的 sha256 → 事后无从发现。核销结果随汇总件落盘 → 事后可对账。
LOCK_NAME = "exp2-lock.json"


class MaterialsLockDrift(Exception):
    """材料件 sha256 与 exp2-lock.json 登记值不符（预注册漂移）→ fail-loud，不出账。"""


def sha256_file(path):
    """文件字节流 sha256（分块读；材料件/快照件同口径）。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_materials_lock(exp2_dir, materials_path):
    """核销 exp2-lock.json 的 materials_sha256 预注册锁。

    返回核销信息 dict（lock_path / lock_sha256 / actual_sha256 / match /
    lock_generated_at / lock_materials_path）。失配（材料被改未重锁）、锁件缺失、
    锁件不可解析、锁件无有效 materials_sha256 → 抛 MaterialsLockDrift（fail-loud）：
    锁失守期间不得产出任何账目（汇总件/逐 run 明细一律不写）。
    """
    lock_path = os.path.join(exp2_dir, LOCK_NAME)
    if not os.path.isfile(lock_path):
        raise MaterialsLockDrift(
            "预注册锁缺失：%s 不存在——EXP-2 材料件 sha256 锁失守，不得出账" % lock_path)
    try:
        with open(lock_path, encoding="utf-8") as f:
            lock = json.load(f)
    except Exception as e:
        raise MaterialsLockDrift("预注册锁不可解析：%s（%s）——不得出账" % (lock_path, e))
    reg = lock.get("materials_sha256")
    if not isinstance(reg, str) or len(reg) != 64:
        raise MaterialsLockDrift(
            "预注册锁无有效 materials_sha256：%s（读到 %r）——不得出账" % (lock_path, reg))
    actual = sha256_file(materials_path)
    info = {"lock_path": lock_path, "lock_sha256": reg, "actual_sha256": actual,
            "match": actual == reg, "lock_generated_at": lock.get("generated_at"),
            "lock_materials_path": lock.get("materials_path")}
    if not info["match"]:
        raise MaterialsLockDrift(
            "预注册漂移：材料件 %s 的 sha256=%s ≠ %s 登记值 %s（锁 generated_at=%s）——"
            "材料任何改动须重算本锁并记新 generated_at；锁失守期间不得出账"
            % (materials_path, actual, LOCK_NAME, reg, lock.get("generated_at")))
    return info


# ----------------------------------------------------------------  citation_unit 口径复算
def norm(s: str) -> str:
    """citation_unit.py 的规范化空白比对（逐字复制其 norm 实现）。"""
    return " ".join(s.split())


def recompute_citation_unit(task_min_citations, report, sources_dir):
    """逐字复算 citation_unit.py 主判官的引用断言（与 b-exp1-aggregate.py 同族）。

    判定逻辑与 af/packages/reportkit/units/citation_unit.py 一致；sources_dir 缺
    sources/ 子目录时以 run 目录兜底（工作流臂布局 sources/ 在 run_dir 下）。
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
    """TOST 钉死构造（experiments-v1.json EXP-2.metric_operationalization.ci.tost）：
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


# ----------------------------------------------------------------  提取：report 臂（af-order 订单镜像）
def parse_order_dir(d):
    """E2-<arm>-<paper_id>（repeat 次跑形如 E2-<arm>-r2-<paper_id>）→ (arm, paper, repeat)。"""
    b = os.path.basename(d)
    m = re.match(r"^E2-(B0|B1|B2|B3|B4)-(\d{4}\.\d{4,5})$", b)
    if m:
        return m.group(1), m.group(2), 0
    m = re.match(r"^E2-(B0|B1|B2|B3|B4)-r(\d+)-(\d{4}\.\d{4,5})$", b)
    if m:
        return m.group(1), m.group(3), int(m.group(2))
    return None, None, None


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


def sources_dir_sha_check(sources_path, reg_sha):
    """预注册 T8 核面的实现：核 sources/ 目录本身，不经 citations.snapshot_ref 文件名解析。

    返回 (sources_count, sha_set|None, verdict)；目录缺失/不可读 → (None, None,
    "no_sources_dir")。2026-10-31 修复：t8_clean 原以 citations 解析出的 sha 集合判定
    （crosscheck.snapshot_sha_vs_materials），writer 把 snapshot_ref 写成落盘文件名之外
    的形式（实测 WF-B4-2610.35767：64 位全 sha vs 落盘 12 位截断 sha.txt）时解析失败
    →空集→输入干净的 run 被误判 T8 违约剔除。输入核面只认 sources/ 目录本身；writer
    引用元数据缺陷由 quote 核面（snapshot_present/quote_hit）与判官输出如实承担。
    """
    try:
        names = sorted(os.listdir(sources_path))
    except OSError:
        return None, None, "no_sources_dir"
    shas = set()
    for fn in names:
        with open(os.path.join(sources_path, fn), "rb") as f:
            shas.add(hashlib.sha256(f.read()).hexdigest())
    verdict = ("match" if reg_sha and shas == {reg_sha}
               else ("mismatch" if reg_sha else "no_registration"))
    return len(names), shas, verdict


def fill_run_record(rec, paper, arm, run_ref, report, src_dir, judge_citation, judge_rubric,
                    verifier_note, tokens_total, wall_clock_s, order_state, source):
    """两源共用的填表逻辑：主指标复算 + 判官对账 + 预登记指纹对账。"""
    checks, detail, _mf = recompute_citation_unit(3, report, src_dir)
    rec["citation_detail"] = detail
    rec["quote_hits"] = sum(1 for d in detail if d["status"] == "hit")
    rec["quote_misses"] = sum(1 for d in detail if d["status"] == "miss")
    rec["quote_skipped"] = sum(1 for d in detail if d["status"].startswith("skipped"))
    rec["recomputed_checks"] = checks
    # 顶层字段（exp1 同款锚位：judge/recomputed 一致后的单一值）
    rec["citations_total"] = checks["citations_total"]
    rec["marker_align"] = checks["marker_align"]
    rec["sha_match"] = checks["sha_match"]
    rec["snapshot_present"] = checks["snapshot_present"]
    if checks["citations_total"]:
        rec["quote_hit_rate"] = rec["quote_hits"] / checks["citations_total"]
        rec["all_hit"] = (rec["quote_hit_rate"] == 1.0)
    # 判官输出（report 臂=verify.log；工作流臂=judge-*.json）与复算对账
    if judge_citation:
        rec["judge_citation"] = judge_citation
        rec["citations_total_judge"] = judge_citation.get("checks", {}).get("citations_total")
        rec["judge_quote_failures"] = sum(
            1 for x in judge_citation.get("failures", []) if x.startswith("quote not found"))
        # citation_unit.py 对 snapshot missing / sha256 mismatch 的引用 failures.append
        # 后 continue（不进 quote 检查）——这两类失败与复算的 skipped_* 对应，
        # quote 对账恒等式必须同步扣除，否则凡含 skip 类引用即恒 False
        # （bugfix 2026-10-31/11-01：EXP-2 工作流臂 6 run 因此静默携带 False 核对字段）
        rec["judge_skip_failures"] = sum(
            1 for x in judge_citation.get("failures", [])
            if x.startswith("snapshot missing") or x.startswith("sha256 mismatch"))
    if judge_rubric:
        rec["judge_rubric"] = judge_rubric
        rec["rubric_passed"] = judge_rubric.get("passed")
    note_n = verifier_note_citations(verifier_note)
    cc = rec["crosscheck"]
    cc["citations_total_verifier_note"] = note_n
    cc["citations_total_judge"] = rec.get("citations_total_judge")
    cc["citations_total_recomputed"] = checks["citations_total"]
    # 三锚对账：report 臂有 verifier_note（note/judge/recomputed 三锚）；
    # 工作流臂无 note（ask API 不暴露）→ judge/recomputed 两锚，note 锚记 None 不判伪
    if note_n is not None:
        cc["citations_total_consistent"] = (
            note_n == checks["citations_total"]
            and rec.get("citations_total_judge") == checks["citations_total"])
    else:
        cc["citations_total_consistent"] = (
            rec.get("citations_total_judge") == checks["citations_total"]
            if rec.get("citations_total_judge") is not None else None)
    if judge_citation:
        cc["quote_failures_judge_vs_recomputed"] = (
            rec.get("judge_quote_failures") == rec["quote_misses"])
        cc["quote_hit_check_vs_recomputed"] = (
            (checks["citations_total"] - rec.get("judge_quote_failures", -1)
             - rec.get("judge_skip_failures", 0)) == rec["quote_hits"])
    return rec


def _link_escapes(root, p):
    """链接 p 的目标是否逃出镜像根 root（realpath 口径；不可解析＝按逃逸处理）。

    与镜像真实性门（self-improve-loop.py _mirror_escape_links）及
    b-exp1-aggregate.py 同口径：树内链接（目标仍在镜像树内、内容仍受镜像只读保护）
    不算逃逸——不误拒；树外链接＝工件不在镜像只读保护范围内 → fail-loud 拒绝聚合。"""
    try:
        r = os.path.realpath(root)
        tgt = os.path.realpath(p)
    except OSError:
        return True
    return not (tgt == r or tgt.startswith(r + os.sep))


def extract_report_arm(order_dir, materials_shas):
    """report 臂（B0/B1）：从 af-order 订单目录提取（b-exp1-aggregate.py 同族）。"""
    arm, paper, repeat = parse_order_dir(order_dir)
    order_id = os.path.basename(order_dir)
    rec = {
        "order_id": order_id, "arm": arm, "paper": paper, "repeat": repeat,
        "source": "af-order", "mirror_path": order_dir,
        "status": None, "reward": None, "gate": None, "turns": None,
        "tokens": None, "tokens_total": None, "cache_read": None,
        "citations_total": None, "quote_hits": None, "quote_hit_rate": None,
        "all_hit": None, "rubric_passed": None, "marker_align": None,
        "sha_match": None, "snapshot_present": None,
        "report_present": None, "verifier_note": None,
        "wall_clock_s": None, "error_code": None, "order_state": None,
        "anchor": {}, "crosscheck": {}, "citation_detail": [],
    }
    rp = os.path.join(order_dir, "results.jsonl")
    if not os.path.isfile(rp):
        rec["report_present"] = False
        rec["error_code"] = "no_results_jsonl"
        return rec
    lines = [l for l in open(rp, encoding="utf-8").read().splitlines() if l.strip()]
    if not lines:
        # 订单已建但尚无结果行（在跑/早期失败）：记无 report，不伪值
        rec["report_present"] = False
        rec["error_code"] = "results_jsonl_empty"
        return rec
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

    mp = os.path.join(order_dir, "mes-events.jsonl")
    if os.path.isfile(mp):
        evs = [json.loads(l) for l in open(mp, encoding="utf-8") if l.strip()]
        rel = [e["occurred_at"] for e in evs if e.get("kind") == "release"]
        cls = [e["occurred_at"] for e in evs if e.get("kind") == "close"]
        done = [e["occurred_at"] for e in evs if e.get("kind") == "complete"]
        t0 = min(rel) if rel else min(e["occurred_at"] for e in evs)
        t1 = max(cls) if cls else (max(done) if done else None)
        if t1 is None:
            rec["wall_clock_s"] = None
            rec["wall_clock_note"] = "mes-events 无 complete/close 事件，submit→close 墙钟不可得"
        else:
            rec["wall_clock_s"] = round((t1 - t0) / 1000.0, 3)
        rec["anchor"]["mes_events"] = mp
        # 订单终态（Closed=判官全过；Completed=verify 门拒绝 close 的失败单——仍是有效数据点）
        lj = os.path.join(order_dir, "ledger.jsonl")
        if os.path.isfile(lj):
            try:
                rec["order_state"] = json.loads(
                    [l for l in open(lj, encoding="utf-8") if l.strip()][-1]).get("state_after")
            except Exception:
                rec["order_state"] = None

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
        citation = rubric = None
        if os.path.isfile(vlog):
            citation, rubric, vanchor = read_verify_log(vlog)
            rec["anchor"]["verify_log"] = "%s (citation json line %s; rubric json line %s)" % (
                vlog, vanchor.get("citation_line"), vanchor.get("rubric_line"))
        if os.path.isfile(rj):
            rec["report_present"] = True
            rec["anchor"]["report_json"] = rj
            report = json.load(open(rj, encoding="utf-8"))
            fill_run_record(rec, paper, arm, run_path, report,
                            src if os.path.isdir(src) else run_path,
                            citation, rubric, rec["verifier_note"],
                            rec["tokens_total"], rec["wall_clock_s"],
                            rec["order_state"], "af-order")
            rec["anchor"]["sources"] = sorted(
                os.path.join(src, os.path.basename(d["snapshot_ref"]))
                for d in rec["citation_detail"] if d.get("snapshot_ref"))
            reg = materials_shas.get(paper)
            shas = {d.get("snapshot_sha256_actual") for d in rec["citation_detail"]
                    if d.get("snapshot_sha256_actual")}
            rec["crosscheck"]["snapshot_sha_vs_materials"] = (
                "match" if reg and shas == {reg} else ("mismatch" if reg else "no_registration"))
            rep_sha = (report.get("paper") or {}).get("sha256")
            rec["crosscheck"]["report_paper_sha_vs_materials"] = (
                "match" if reg and rep_sha == reg else ("mismatch" if reg else "no_registration"))
            # T8 输入核面：sources/ 恰一枚且=预登记快照（按 sources/ 目录本身核，
            # 见 sources_dir_sha_check；不随 citations 解析失败连坐）
            sources_path = src if os.path.isdir(src) else os.path.join(run_path, "sources")
            cnt, _sdir_shas, t8v = sources_dir_sha_check(sources_path, reg)
            rec["sources_count"] = cnt
            rec["crosscheck"]["sources_dir_sha_vs_materials"] = t8v
            rec["t8_clean"] = (
                rec["sources_count"] == 1
                and rec["crosscheck"]["sources_dir_sha_vs_materials"] == "match")
        else:
            rec["report_present"] = False
    else:
        rec["report_present"] = False
        if not rec.get("error_code"):
            rec["error_code"] = "no_run_dir"
    cc = rec["crosscheck"]
    if rec.get("report_present"):
        cc["reward_vs_judges"] = (
            rec["reward"] == (rec.get("judge_citation", {}).get("passed")
                              and rec.get("rubric_passed"))
            if rec.get("judge_citation") else None)
    return rec


def extract_workflow_arm(row, materials_shas):
    """工作流臂（B2/B3/B4）：从 exp2-wf-out/<arm>/<paper_id>/ 工件提取。"""
    arm, paper = row["arm"], row["paper_id"]
    run_dir = row["run_dir"]
    rec = {
        "order_id": "WF-%s-%s" % (arm, paper), "arm": arm, "paper": paper, "repeat": 0,
        "source": "workflow", "mirror_path": run_dir,
        "status": None, "reward": None, "gate": None, "turns": None,
        "tokens": None, "tokens_total": None, "cache_read": None,
        "citations_total": None, "quote_hits": None, "quote_hit_rate": None,
        "all_hit": None, "rubric_passed": None, "marker_align": None,
        "sha_match": None, "snapshot_present": None,
        "report_present": None, "verifier_note": None,
        "wall_clock_s": None, "error_code": None, "order_state": None,
        "reader_read_bytes": row.get("reader_read_bytes"),
        "snapshot_bytes": row.get("snapshot_bytes"),
        "anchor": {}, "crosscheck": {}, "citation_detail": [],
    }
    rj = os.path.join(run_dir, "report.json")
    jc = os.path.join(run_dir, "judge-citation.json")
    jr = os.path.join(run_dir, "judge-rubric.json")
    citation = rubric = None
    if os.path.isfile(jc):
        try:
            citation = json.load(open(jc, encoding="utf-8"))
            rec["anchor"]["judge_citation"] = jc
        except Exception:
            rec["error_code"] = "judge_citation_unparsable"
    if os.path.isfile(jr):
        try:
            rubric = json.load(open(jr, encoding="utf-8"))
            rec["anchor"]["judge_rubric"] = jr
        except Exception:
            rec["error_code"] = "judge_rubric_unparsable"
    if row.get("status") != "ok" or not os.path.isfile(rj):
        rec["report_present"] = False
        rec["error_code"] = row.get("error") or "no_report_json"
        return rec
    rec["report_present"] = True
    rec["anchor"]["report_json"] = rj
    report = json.load(open(rj, encoding="utf-8"))
    # sources/ 目录解析与报告单臂同构（bugfix 2026-10-31：原实现恒传 run_dir，
    # 导致 quote 回查全数 skipped_snapshot_missing、sha 对照空集、t8_clean 误 False、
    # 72 个工作流 run 被整体排除出 eligible——docstring 声明的兜底意图未落地）
    src_dir = os.path.join(run_dir, "sources")
    fill_run_record(rec, paper, arm, run_dir, report,
                    src_dir if os.path.isdir(src_dir) else run_dir,
                    citation, rubric, None, None, None, None, "workflow")
    src = os.path.join(run_dir, "sources")
    rec["anchor"]["sources"] = sorted(
        os.path.join(src, os.path.basename(d["snapshot_ref"]))
        for d in rec["citation_detail"] if d.get("snapshot_ref"))
    reg = materials_shas.get(paper)
    shas = {d.get("snapshot_sha256_actual") for d in rec["citation_detail"]
            if d.get("snapshot_sha256_actual")}
    rec["crosscheck"]["snapshot_sha_vs_materials"] = (
        "match" if reg and shas == {reg} else ("mismatch" if reg else "no_registration"))
    rep_sha = (report.get("paper") or {}).get("sha256")
    rec["crosscheck"]["report_paper_sha_vs_materials"] = (
        "match" if reg and rep_sha == reg else ("mismatch" if reg else "no_registration"))
    # T8 输入核面：sources/ 恰一枚且=预登记快照（工作流臂布局同构；按 sources/
    # 目录本身核，见 sources_dir_sha_check——writer 引用元数据缺陷不连坐输入核面）
    cnt, _sdir_shas, t8v = sources_dir_sha_check(os.path.join(run_dir, "sources"), reg)
    rec["sources_count"] = cnt
    rec["crosscheck"]["sources_dir_sha_vs_materials"] = t8v
    rec["t8_clean"] = (
        rec["sources_count"] == 1
        and rec["crosscheck"]["sources_dir_sha_vs_materials"] == "match")
    # manifest 与判官文件/复算的三方对账
    rec["crosscheck"]["manifest_status"] = row.get("status")
    rec["crosscheck"]["manifest_citation_passed"] = row.get("citation_passed")
    rec["crosscheck"]["manifest_rubric_passed"] = row.get("rubric_passed")
    rec["crosscheck"]["manifest_vs_judge_citation"] = (
        row.get("citation_passed") == (citation or {}).get("passed")
        if citation else None)
    rec["crosscheck"]["manifest_vs_judge_rubric"] = (
        row.get("rubric_passed") == (rubric or {}).get("passed") if rubric else None)
    rec["crosscheck"]["reader_bytes_match"] = (
        row.get("reader_read_bytes") == row.get("snapshot_bytes")
        if row.get("reader_read_bytes") is not None and row.get("snapshot_bytes") is not None
        else None)
    # 工作流臂无 tokens/墙钟（ask API 不暴露 usage）——显式 not_recorded，不留伪值
    rec["tokens_note"] = ("workflow 臂 tokens_total/cents_spent=not_recorded"
                          "（agent().ask API 不暴露 usage；zcode 日志 totalTokens 脱敏）")
    rec["wall_clock_note"] = "workflow 臂 wall_clock_s=not_recorded（工件无时间戳账本）"
    return rec


# ----------------------------------------------------------------  预注册 gate（EXP-2）
# 预注册来源：experiments-v1.json EXP-2.metrics[] 中 role="gate" 的四项——引用侧三项
# marker_align / sha_match / snapshot_present（source=citation_unit.py）与 rubric_passed
# （source=rubric_unit.py，R1-R5 全过）；威胁 T3 mitigation 原文「…+ marker_align/
# sha_match 作 gate 指标先筛」——gate 指标先筛。
GATE_CITATION_METRICS = ("marker_align", "sha_match", "snapshot_present")
GATE_RUBRIC_METRIC = "rubric_passed"
GATE_DECLARED_METRICS = list(GATE_CITATION_METRICS) + [GATE_RUBRIC_METRIC]


def gate_citation_pass(r):
    """预注册 gate（引用侧三项）是否全过；缺值（None）= 不过（fail-closed）。"""
    return all(r.get(k) is True for k in GATE_CITATION_METRICS)


def gate_rubric_pass(r):
    """预注册 gate（rubric_passed=R1-R5 全过）是否过；缺值=不过（fail-closed）。"""
    return r.get(GATE_RUBRIC_METRIC) is True


def gate_failed_metrics(r):
    """未通过的引用侧 gate 指标名列表（空=全过）。"""
    return [k for k in GATE_CITATION_METRICS if r.get(k) is not True]


# ----------------------------------------------------------------  配对统计
def analysis_eligible(r):
    """进臂统计/配对集的条件（预注册 gate 先筛口径，2026-11-02 修复）：

    ① 有 report；② T8 输入核面干净（sources 恰一枚=预登记快照）；
    ③ 预注册 gate 指标（引用侧 marker_align/sha_match/snapshot_present）全过。

    T8 违约 run（reader 绕过 local_path 抓实时内容）与 gate 违约 run（引用侧门禁
    不过：标记双向对齐/快照 sha/快照在场）均不计入分析，全额登记
    （t8_violations / prereg_gate.gate_excluded）；rubric_passed 不作主分析集硬筛
    （判结果侧量，按它筛=对结果变量取样；实测加筛则 B2 臂 eligible 归零），按敏感性
    口径全额登记（prereg_gate.rubric_gate_sensitivity）。
    """
    return (bool(r.get("report_present")) and bool(r.get("t8_clean", True))
            and gate_citation_pass(r))


def eligibility_reasons(r):
    """该 run 未进分析集的原因列表（空=进集）。T8 优先于 gate（先到先记）。"""
    if not r.get("report_present"):
        return ["no_report"]
    if not r.get("t8_clean", True):
        return ["t8_input_violation"]
    failed = gate_failed_metrics(r)
    if failed:
        return ["prereg_gate_failed:" + "+".join(failed)]
    return []


def split_by_round(runs):
    """把 run 集按轮次切成 (主轮 run 列表, repeat 轮 run 列表)。

    repeat 判定两条来源（合并）：
      ① report 臂：order_id 带 -rN（E2-B0-r2-<paper>）→ 提取期已解析进 r['repeat']>0；
      ② 同 (arm,paper) 的第 2 个及以后的 run——工作流臂第二轮 harvest 出的重复行
         即便不带 -r2 后缀也能识别（工作流臂无 order_id 后缀可依赖）。
    主轮 = 每个 (arm,paper) 的首个 run；与配对层 pick（repeat 号最小者优先）同口径。

    2026-11-02 修复：原分配表对账用 executed={(paper,arm)} 去重集合，丢失 repeat 维，
    而分配表 repeat 行复用主轮 (task_id,arm)（alloc_repeat ⊆ alloc_main），
    故 |executed∩alloc_repeat|−|executed∩alloc_repeat∩alloc_main| ≡ 0——与是否真跑
    repeat 无关，登记通道恒报 0。现按 run 身份计真值（见主流程分配表对账块）。
    """
    seen = set()
    main, rep = [], []
    for r in runs:
        key = (r["arm"], r["paper"])
        dup = key in seen
        seen.add(key)
        if (r.get("repeat") or 0) > 0 or dup:
            rep.append(r)
        else:
            main.append(r)
    return main, rep


def repeat_registration(runs, alloc_repeat):
    """repeat 轮实跑登记（按 run 身份计真值；2026-11-02 修复的核心函数）。

    返回 dict：
      runs_present  —— 实跑且 (paper,arm) 命中分配表 repeat 行的 run 数；
      pairs_present —— 命中的 (task,arm) 组合数；
      unmatched_runs / unmatched_order_ids —— 实跑了 repeat 但不在分配表内的 run（全额登记）。

    旧式口径 |executed∩alloc_repeat|−|executed∩alloc_repeat∩alloc_main| 已废：
    executed 是 (paper,arm) 去重集、无 repeat 维，而分配表 repeat 行复用主轮
    (task_id,arm)（alloc_repeat ⊆ alloc_main 恒成立），故该式 ≡ 0——
    与是否真跑过 repeat 无关，登记通道结构性失效。
    """
    _main, rep = split_by_round(runs)
    matched = [r for r in rep if (r["paper"], r["arm"]) in alloc_repeat]
    unmatched = [r for r in rep if (r["paper"], r["arm"]) not in alloc_repeat]
    return {
        "runs_present": len(matched),
        "pairs_present": len({(r["paper"], r["arm"]) for r in matched}),
        "unmatched_runs": len(unmatched),
        "unmatched_order_ids": sorted(str(r.get("order_id")) for r in unmatched)[:10],
    }


def pick_by_task(runs, arm, eligible_only=True, elig=None):
    """每任务取主轮 run（repeat 号最小者；同号取先到者）→ {paper: run}。

    口径单一来源：配对层（pair_runs）与五臂表（arm_summary）共用本函数，
    保证两层「每任务只算一次」的规则逐字一致——否则真跑 repeats 后五臂表分母会
    从任务数漂成 run 数（同一任务被数两次），与配对层分母分裂。

    elig：可选的入集谓词（默认 analysis_eligible）——rubric gate 敏感性口径用
    「主分析集 ∧ rubric_passed」的谓词复用同一套取 run 规则。
    """
    pred = elig if elig is not None else analysis_eligible
    best = {}
    for r in runs:
        if r["arm"] != arm:
            continue
        if eligible_only and not pred(r):
            continue
        cur = best.get(r["paper"])
        if cur is None or (r.get("repeat") or 0) < (cur.get("repeat") or 0):
            best[r["paper"]] = r
    return best


def pair_runs(runs, treat, ctrl, elig=None):
    """按 task_id（paper）配对；每 (臂,任务) 取首个合格的 run（repeat 单独登记）。"""
    def pick(arm):
        return pick_by_task(runs, arm, eligible_only=True, elig=elig)
    t_tasks, c_tasks = pick(treat), pick(ctrl)
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
                     "treat_ref": tr["order_id"], "ctrl_ref": cr["order_id"],
                     "treat_source": tr["source"], "ctrl_source": cr["source"]})
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
    if n_p:
        rd = [r["treat_rate"] - r["ctrl_rate"] for r in rows]
        out["ratio_paired_diff_mean_pp"] = sum(rd) / n_p * 100.0
        out["ratio_paired_diff_bootstrap95_pp"] = paired_bootstrap_ci(rd)
    return out


def arm_summary(runs, arm):
    """单臂统计。

    分母口径（2026-11-02 修复）：**任务数**，不是 run 数——每任务只取主轮 run
    （pick_by_task，与配对层 pair_runs 同一条规则）。修复前本函数直接吃全部
    eligible run，真跑 repeats 后分母会从任务数漂成 run 数（同一任务被数两次，
    Wilson 区间与均值随之失真），与配对层分母分裂。repeat 轮实跑数另行登记
    （repeat_runs / repeat_tasks），不进分母。
    """
    rs = [r for r in runs if r["arm"] == arm]
    rep_runs = split_by_round(rs)[1]
    rep_tasks = {r["paper"] for r in rep_runs}
    tasks = {r["paper"] for r in rs}
    with_rep_tasks = {r["paper"] for r in rs if r.get("report_present")}
    primary = pick_by_task(rs, arm, eligible_only=True)
    elig = list(primary.values())
    n = len(elig)
    rates = [r["quote_hit_rate"] for r in elig]
    hits = sum(1 for r in elig if r["all_hit"])
    lo, hi = wilson_ci(hits, n)
    dist = Counter(round(r, 4) for r in rates)
    cits = [r["citations_total"] for r in elig if r["citations_total"] is not None]
    qhits = [r["quote_hits"] for r in elig if r["quote_hits"] is not None]
    tok = [r["tokens_total"] for r in rs if r["tokens_total"] is not None]
    # 排除账目分层（2026-11-02 gate 修复）：T8 输入违约 与 预注册 gate 不通过
    # 分列，不混进同一个键（修复前 t8_excluded_tasks 实际含 gate 排除项）。
    t8_ok = set(pick_by_task(
        rs, arm,
        elig=lambda r: bool(r.get("report_present")) and bool(r.get("t8_clean", True))))
    t8_excluded = with_rep_tasks - t8_ok
    gate_excluded = t8_ok - set(primary)
    return {
        "arm": arm, "label": ARM_LABEL[arm], "channel": ARM_CHANNEL[arm],
        "models": ARM_MODELS[arm],
        "model_assignment": ARM_MODEL_ASSIGNMENT[arm],
        "n_orders": len(rs), "n_with_report": len(with_rep_tasks), "n_eligible": n,
        "n_tasks": len(tasks),
        "denominator": "任务数（每任务取主轮 run；repeat 轮单列登记，不进分母）",
        "n_all_hit": hits,
        "all_hit_rate": (hits / n if n else None),
        "all_hit_wilson95": [lo, hi],
        "quote_hit_rate_mean": (sum(rates) / n if n else None),
        "quote_hit_rate_min": (min(rates) if rates else None),
        "quote_hit_rate_max": (max(rates) if rates else None),
        "citations_total_sum": (sum(cits) if cits else None),
        "citations_total_mean": ((sum(cits) / len(cits)) if cits else None),
        "quote_hits_sum": (sum(qhits) if qhits else None),
        "rate_distribution": {str(k): v for k, v in sorted(dist.items())},
        "tokens_total_sum": (sum(tok) if tok else None),
        "tokens_note": (None if tok else "not_recorded（工作流臂 ask API 不暴露 usage）"),
        "tokens_scope": "全部 run（含 repeat 轮，repeats 也烧量）",
        "turns": sorted({r["turns"] for r in rs if r["turns"] is not None}),
        "missing_report_tasks": sorted(tasks - with_rep_tasks),
        "t8_excluded_tasks": sorted(t8_excluded),
        "gate_excluded_tasks": sorted(gate_excluded),
        "excluded_tasks": sorted(with_rep_tasks - set(primary)),
        "wall_clock_s_sum": (round(sum(r["wall_clock_s"] for r in rs if r["wall_clock_s"]), 1)
                             if any(r["wall_clock_s"] for r in rs) else None),
        "repeat_runs": len(rep_runs),
        "repeat_tasks": len(rep_tasks),
    }


# ----------------------------------------------------------------  偏差登记件（机器可读）
def build_deviation_ledger(exp2_dir, spec_path, materials_path, pair_stats,
                           paired_min, generated_at):
    """机器可读偏差登记件：通道/基座偏差 + 臂→模型指派 + 通道对照绑定与其可评估性。

    事实来源（全部可核）：
      · 偏差事实=2026-10-30 通道失效（step provider 拒单 invalid_request +
        运营者令「阶跃星辰 step 已过期，不再使用」）；工作流定义
        exp2-workflow.dwf.ts:129-138 逐字登记。
      · 臂→模型指派=report 臂 profile 端点档案（af/crates/af-bench/src/main.rs:
        174-186 / 237-251）+ 工作流臂 dwf.ts 的 readers/writer_model 指派。
      · 替代对照 B4−B1 的可评估性=本脚本实算的配对集大小 vs 预注册数据门
        （paired_min 条，来自 EXP-2 verdict_precedence 的 GATE:inconclusive）。
    正本（experiments-v1.json，只读）与 sha 锁材料件（exp2-materials.json）都不可改 →
    偏差不进二者，登记于本件；判定程序 tools/b-verdict-unique.py 从本件取通道对照绑定。
    """
    # 结构自检（fail-loud）：逐臂 readers/writer 必须落在 model_ids 内；ARM_MODELS
    # （人读散文串）逐臂在位——机器面以 model_ids 为准，二者不可各自漂移
    for _a, _v in ARM_MODEL_ASSIGNMENT.items():
        _ids = set(_v["model_ids"])
        if not _ids:
            raise AssertionError("臂 %s 的臂→模型指派为空" % _a)
        if not set(_v["readers"]) <= _ids or _v["writer"] not in _ids:
            raise AssertionError("臂 %s 的 readers/writer 不在 model_ids 内（%s）" % (_a, _v))
        if not ARM_MODELS.get(_a):
            raise AssertionError("臂 %s 缺 ARM_MODELS 人读散文串" % _a)
    # 同模型跨通道对照的「同模型」由指派实算（B4 工作流 vs B1 report 环须同一 model id），
    # 不是手写断言；不成立 → fail-loud（登记件不得宣称同模型对照）
    same_model = (set(ARM_MODEL_ASSIGNMENT["B4"]["model_ids"])
                  == set(ARM_MODEL_ASSIGNMENT["B1"]["model_ids"]))
    if not same_model:
        raise AssertionError("B4 与 B1 的 model id 不一致（%s vs %s）→ 同模型跨通道对照前提不成立"
                             % (ARM_MODEL_ASSIGNMENT["B4"]["model_ids"],
                                ARM_MODEL_ASSIGNMENT["B1"]["model_ids"]))
    b4b1 = pair_stats.get("B4−B1") or {}
    n_p = b4b1.get("n_paired")
    evaluable = bool(n_p is not None and n_p >= paired_min)
    if not evaluable:
        reason = ("替代对照 B4−B1 的配对集 n_p=%s < 预注册数据门 %d 条 → GATE:inconclusive "
                  "命中 → 同模型跨通道对照在本数据上永不可评估（channel_effect 既不可证"
                  "也不可否证）" % (n_p, paired_min))
    else:
        reason = ("替代对照 B4−B1 的配对集 n_p=%s ≥ 数据门 %d 条 → 可评估"
                  % (n_p, paired_min))
    ledger = {
        "artifact": "exp2-deviation-ledger-v1",
        "exp_id": "EXP-2",
        "batch": exp2_dir,
        "generated_at": generated_at,
        "preregistration": {
            "spec_path": spec_path,
            "spec_status": ("正本只读（exp2-lock.json 注：experiments-v1.json 同批独立成件、"
                            "只读）——偏差不改正本，登记于本件"),
            "materials_path": materials_path,
            "materials_status": ("sha256 预注册锁（exp2-lock.json）——材料件不可改，"
                                 "臂→模型指派与偏差不落材料件，登记于本件"),
            "why_ledger": ("材料件的 spec.workflow_templates.models 只登记两个模型"
                           "（step-5 / minimax）、无「臂→模型」指派字段；正本 EXP-2.arms[]"
                           "仍写偏差前的臂定义 → 臂级事实必须有独立的机器可读真源"),
        },
        "arm_model_assignment": ARM_MODEL_ASSIGNMENT,
        "deviations": [
            {
                "id": DEV_ID,
                "exp_id": "EXP-2",
                "occurred": "2026-10-30",
                "kind": "channel_and_base_model",
                "cause": ("step provider 拒单（invalid_request，dwfrun-26f505c8）且运营者令"
                          "「阶跃星辰 step 已过期，不再使用」→ 三工作流臂整体改走 minimax 家族"),
                "affected_arms": ["B2", "B3", "B4"],
                "pre_registered_models": {
                    "B2": ["new-provider/step-5-preview", "minimax/Minimax-M3.1-Flash-Preview"],
                    "B3": ["new-provider/step-5-preview"],
                    "B4": ["new-provider/step-5-preview"],
                    "source": ("experiments-v1.json EXP-2.arms[] 与 execution.workflow_spec"
                               "（reader_step5 / reader_minimax / writer「与臂一致」）"),
                },
                "executed_models": {a: ARM_MODEL_ASSIGNMENT[a]["model_ids"]
                                    for a in ("B2", "B3", "B4")},
                "channel_effect_binding": {
                    "preregistered_comparison": "B4−B0",
                    "preregistered_semantics": "与 B0 同模型同角色，唯一差别=走工作流而非 af-order 环（纯通道对照）",
                    "confounded": True,
                    "confounding_factors": ["channel", "base_model"],
                    "replacement_comparison": "B4−B1",
                    "replacement_note": "同模型跨通道对照（B4=minimax/Minimax-M3.1-Flash-Preview 工作流 vs B1=profile mavis-m31f→MiniMax-M3.1-Flash-Preview report 环）",
                    "replacement_same_model": same_model,
                    "replacement_same_model_basis": (
                        "B4 的读者/写者模型=minimax/Minimax-M3.1-Flash-Preview（dwf.ts:290-292）；"
                        "B1 的 profile mavis-m31f → model MiniMax-M3.1-Flash-Preview"
                        "（af/crates/af-bench/src/main.rs:174-186）→ 同基座模型、异通道"),
                    "replacement_evaluable": evaluable,
                    "replacement_n_paired": n_p,
                    "replacement_data_gate_min": paired_min,
                    "reason": reason,
                },
                "verdict_consequence": (
                    "通道问题不可解 → 判定程序 fail-closed：channel_effect 不可触发，且归因类"
                    "verdict（confirmed/refuted/equivalent/cost_conditional）一律封存 → "
                    "终裁只能 inconclusive（B2−B0 的差在偏差后是「通道+基座+跨模型」多因子"
                    "混杂，不得归因于跨模型设计；B2−B3 同为 minimax 家族内部对照，不受本偏差影响）"),
                "falsified_preregistration_claims": [
                    {"spec_pointer": "experiments-v1.json EXP-2.arms[B4].manipulation",
                     "claim": "与 B0 同模型同角色，唯一差别=走工作流而非 af-order 环",
                     "falsified_by": "B4 实际基座=m31f（minimax 家族）≠ B0 的 step-5-preview"},
                    {"spec_pointer": "experiments-v1.json EXP-2.arms[B2].label",
                     "claim": "双模型交叉（step-5 reader + m31f reader + 合并 writer）",
                     "falsified_by": "B2 实际读者=m31f+m3、writer=m31f（跨模型性成立但组合换了）"},
                    {"spec_pointer": "experiments-v1.json EXP-2.arms[B3].label",
                     "claim": "自洽对照（2× step-5 reader + 合并 writer）",
                     "falsified_by": "B3 实际读者=2×m31f、writer=m31f（自洽性成立但基座换了）"},
                    {"spec_pointer": "experiments-v1.json EXP-2.hypothesis.scope",
                     "claim": "结论只对『报告产线 + step-5×mavis-m31f 跨档组合 + 引用完整性指标』成立",
                     "falsified_by": "实际跨模型组合=m31f×m3（非 step-5×mavis-m31f）→ 结论作用域应改为『报告/工作流产线 + m31f×m3 组合 + 引用完整性指标』"},
                ],
                "evidence": [
                    "计划/研究组/实验批-20261029/exp2-workflow.dwf.ts:129-138（偏差注释 + MODELS 表 + 臂指派）",
                    "计划/研究组/实验批-20261029/exp2-报告.md §9（终局：通道失效偏差 + 五臂表模型列）",
                    "af/crates/af-bench/src/main.rs:174-186,237-251（report 环 profile → 端点模型档案）",
                    "计划/研究组/实验批-20261029/exp2-aggregate-summary.json（arm_summaries[*].model_assignment）",
                ],
                "registered_at": [
                    "计划/研究组/实验批-20261029/exp2-deviation-ledger.json（本件，机器可读真源）",
                    "计划/研究组/实验批-20261029/exp2-workflow.dwf.ts:129-134",
                    "计划/研究组/实验批-20261029/exp2-报告.md §9 五臂表模型列",
                    "计划/系统目标台账.md G7 行（台账）",
                ],
            },
        ],
        "surfaces": {
            "canonical_spec": {
                "path": spec_path,
                "status": "只读正本——本轮不改正本；正本 EXP-2.arms[]/hypothesis.scope 仍写偏差前臂定义，"
                          "其被推翻的事实登记于本件 deviations[].falsified_preregistration_claims",
            },
            "materials": {
                "path": materials_path,
                "status": "sha256 预注册锁——不可改；spec.workflow_templates.models 只有两个模型、无臂级指派",
            },
            "run_record": {
                "path": os.path.join(exp2_dir, "exp2-wf-manifest.jsonl"),
                "status": "逐 run 清单——每行补登 models/model_source（源=工作流定义 MODELS 指派）",
            },
        },
    }
    return ledger


# ----------------------------------------------------------------  主流程
def main(argv):
    ap = argparse.ArgumentParser(description="EXP-2 逐单提取 + 数据门 + 统计 + 终裁")
    ap.add_argument("--mirror", default=DEFAULT_MIRROR, help="anolis 只读镜像根（orders/E2-*）")
    ap.add_argument("--wf-dir", default=DEFAULT_WF_DIR, help="工作流臂工件根（exp2-wf-out）")
    ap.add_argument("--exp2-dir", default=DEFAULT_EXP2_DIR)
    ap.add_argument("--out-dir", default=None, help="交付件目录（默认 --exp2-dir）")
    args = ap.parse_args(argv)

    exp2_dir = os.path.abspath(args.exp2_dir)
    out_dir = os.path.abspath(args.out_dir or exp2_dir)
    spec_path = os.path.join(os.path.dirname(exp2_dir), "B线核心批-20261029", "experiments-v1.json")
    if not os.path.isfile(spec_path):
        spec_path = os.path.join(WS, "计划/研究组/B线核心批-20261029/experiments-v1.json")
    alloc_path = os.path.join(exp2_dir, "exp2-allocation.json")
    materials_path = os.path.join(exp2_dir, "exp2-materials.json")

    # ---- 预注册锁核销（先于任何提取/统计/落盘：锁失守 → 不出账，fail-loud）----
    # 锁失配 = 材料件被改未重锁（exp2-lock.json 原文：材料任何改动须重算本锁并记新
    # generated_at，否则判为预注册漂移）→ 此时出账等于在漂移材料上出一套新账目。
    try:
        lock_info = verify_materials_lock(exp2_dir, materials_path)
    except MaterialsLockDrift as e:
        sys.stderr.write("[FAIL-LOUD] 预注册锁失守：%s\n" % e)
        sys.stderr.write("  → 不出账（不生成汇总件/逐 run 明细/偏差登记件）。\n"
                         "  → 处置：材料改动须重算 %s（materials_sha256 + generated_at）"
                         " 后重跑；或材料回滚至锁登记的字节。\n" % LOCK_NAME)
        return 2

    spec = json.load(open(spec_path, encoding="utf-8"))
    exp2 = [e for e in spec["experiments"] if e["exp_id"] == "EXP-2"][0]
    alloc = json.load(open(alloc_path, encoding="utf-8"))
    materials = json.load(open(materials_path, encoding="utf-8"))
    materials_shas = {p["paper_id"]: p["paper_sha256"] for p in materials["papers"]}

    tasks_expected = exp2["sample_size"]["tasks"]
    print("== 输入 ==")
    print("  spec: %s（EXP-2；tasks=%d；binarization=%s）"
          % (spec_path, tasks_expected,
             exp2["metric_operationalization"]["binarization"]["selected"]))
    print("  allocation: %s（runs_total=%d；seed=%d）" % (alloc_path, alloc["runs_total"], alloc["seed"]))
    print("  materials: %s（papers=%d）" % (materials_path, len(materials["papers"])))
    print("  materials 锁核销: %s ✓ sha256=%s == 登记值（锁 generated_at=%s）"
          % (LOCK_NAME, lock_info["actual_sha256"], lock_info["lock_generated_at"]))
    print("  mirror(report 臂): %s" % os.path.abspath(args.mirror))
    print("  wf-dir(工作流臂): %s" % os.path.abspath(args.wf_dir))

    # ---- ① 逐单提取（两源）----
    order_dirs = sorted(
        d for d in glob.glob(os.path.join(os.path.abspath(args.mirror), "E2-*"))
        if os.path.isdir(d))
    runs, link_problems = [], []
    for d in order_dirs:
        if os.path.islink(d) and _link_escapes(os.path.abspath(args.mirror), d):
            # 逃逸符号链接订单目录（2026-11-02 修复，与 b-exp1-aggregate 同族）：glob/
            # isdir/extract_report_arm 都追随符号链接——订单目录整体换成指向树外的符
            # 号链接后，工件全部来自树外可随时改写的盘面。fail-loud：整批拒绝聚合。
            # 树内链接（目标仍在镜像树内，内容仍受镜像只读保护）不算逃逸，不误拒。
            link_problems.append("%s: 订单目录是逃逸符号链接（%s → %s）→ 工件不在镜像"
                                 "树内（不受镜像只读保护，可随时改写）→ 拒绝聚合"
                                 % (os.path.basename(d), d, os.path.realpath(d)))
            continue
        runs.append(extract_report_arm(d, materials_shas))
    n_report_src = len(runs)
    manifest_path = os.path.join(exp2_dir, "exp2-wf-manifest.jsonl")
    n_wf_src = 0
    manifest_rows = []
    if os.path.isfile(manifest_path):
        for line in open(manifest_path, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            manifest_rows.append(row)
            runs.append(extract_workflow_arm(row, materials_shas))
            n_wf_src += 1
    # 机读运行记录的模型字段核对（EXP2-DEV-001 补登面）：manifest 每行的 models 必须
    # 等于偏差登记件的臂→模型指派；缺字段或不一致 → fail-loud（运行记录不得再无模型字段）
    manifest_model_problems = []
    for row in manifest_rows:
        want = (ARM_MODEL_ASSIGNMENT.get(row.get("arm")) or {}).get("model_ids") or []
        got = row.get("models")
        tag = "%s/%s" % (row.get("arm"), row.get("paper_id"))
        if got is None:
            manifest_model_problems.append("%s: manifest 行缺 models 字段" % tag)
        elif sorted(got) != sorted(want):
            manifest_model_problems.append("%s: manifest models=%s ≠ 登记件指派 %s"
                                           % (tag, got, want))
    print("\n== ① 逐单提取 ==")
    print("  report 臂订单目录：%d（E2-*）；工作流臂 manifest 行：%d" % (n_report_src, n_wf_src))
    print("  manifest 模型字段核对：%d/%d 行与登记件臂→模型指派一致%s"
          % (len(manifest_rows) - len(manifest_model_problems), len(manifest_rows),
             ("；不一致 %d 条：%s" % (len(manifest_model_problems),
                                    manifest_model_problems[:5])) if manifest_model_problems else ""))
    for a in ARMS:
        n = sum(1 for r in runs if r["arm"] == a)
        wr = sum(1 for r in runs if r["arm"] == a and r.get("report_present"))
        print("  臂 %s：%d run（report 在场 %d）" % (a, n, wr))
    # 逐单标注入集资格与排除原因（per-run 明细自证面；T8 优先于 gate）
    for r in runs:
        r["excluded_reason"] = eligibility_reasons(r)
        r["analysis_eligible"] = not r["excluded_reason"]

    # 提取完整性 fail-loud（与 b-exp1 同族：三锚对账 + reward 对账）
    problems = []
    problems.extend(link_problems)             # 逃逸符号链接订单目录（见上）
    problems.extend(manifest_model_problems)
    for r in runs:
        if r["arm"] not in ARMS:
            problems.append("%s: arm=%r 不在闭集" % (r["order_id"], r["arm"]))
        if r.get("report_present"):
            if not r["crosscheck"].get("citations_total_consistent", False):
                problems.append("%s: citations_total 锚不一致（note=%s judge=%s recomputed=%s）"
                                % (r["order_id"],
                                   r["crosscheck"].get("citations_total_verifier_note"),
                                   r["crosscheck"].get("citations_total_judge"),
                                   r["crosscheck"].get("citations_total_recomputed")))
            # 判官↔复算 quote 核对面：两源同罚（bugfix 2026-10-31/11-01：原仅挂
            # af-order 臂，工作流臂 False 核对字段静默通过——数据不自证不分臂）
            if not r["crosscheck"].get("quote_failures_judge_vs_recomputed"):
                problems.append("%s: 判官 quote failures ≠ 复算 misses（%s）"
                                % (r["order_id"], r["source"]))
            if not r["crosscheck"].get("quote_hit_check_vs_recomputed"):
                problems.append("%s: (citations_total−判官 quote/skip failures)≠复算 hits（%s）"
                                % (r["order_id"], r["source"]))
            if r["crosscheck"].get("reward_vs_judges") is False:
                problems.append("%s: reward=%s 与双判官 passed 不一致" % (r["order_id"], r["reward"]))
        if r.get("report_present") and r["crosscheck"].get("snapshot_sha_vs_materials") == "mismatch":
            # citations 可解析快照 sha ≠ 预登记：writer/引用侧对照（≠T8 判定；T8 按
            # sources/ 目录本身核）。不 fail-loud，随 t8_violations/per-run 明细登记
            pass
        if r["source"] == "workflow" and r.get("report_present"):
            if r["crosscheck"].get("manifest_vs_judge_citation") is False:
                problems.append("%s: manifest citation_passed ≠ judge-citation.json" % r["order_id"])
            if r["crosscheck"].get("manifest_vs_judge_rubric") is False:
                problems.append("%s: manifest rubric_passed ≠ judge-rubric.json" % r["order_id"])
            if r["crosscheck"].get("reader_bytes_match") is False:
                problems.append("%s: reader 实读字节 ≠ 冻结字节（%s≠%s）"
                                % (r["order_id"], r.get("reader_read_bytes"), r.get("snapshot_bytes")))
    for p in problems:
        print("  FAIL-LOUD: " + p)
    if problems:
        print("提取交叉对账失败 %d 条 → 停止（预注册口径：判据先于数据，数据不自证）" % len(problems))
        return 2
    print("  判官锚对账：%d/%d 一致（note/judge/recomputed 三锚）"
          % (sum(1 for r in runs if r["crosscheck"].get("citations_total_consistent")),
             sum(1 for r in runs if r.get("report_present"))))
    sha_mismatch = [r["order_id"] for r in runs
                    if r["crosscheck"].get("snapshot_sha_vs_materials") == "mismatch"]
    print("  citations 可解析快照 sha256 ↔ 预登记：mismatch %d 条 %s"
          "（writer/引用侧对照，≠T8 判定；T8 按 sources/ 目录本身核，见下行）"
          % (len(sha_mismatch), sha_mismatch[:5]))
    t8_violations = [
        {"order_id": r["order_id"], "arm": r["arm"], "paper": r["paper"],
         "sources_count": r.get("sources_count"),
         "sources_dir_sha_vs_materials": r["crosscheck"].get("sources_dir_sha_vs_materials"),
         "snapshot_sha_vs_materials": r["crosscheck"].get("snapshot_sha_vs_materials"),
         "quote_hit_rate": r.get("quote_hit_rate"), "all_hit": r.get("all_hit"),
         "note": "reader 摄取输入非冻结快照（web_fetch 落额外快照）→ 不计入臂统计与配对集"}
        for r in runs
        if r.get("report_present") and not r.get("t8_clean", True)]
    print("  T8 输入核面违约（sources≠1 或 sha≠预登记）：%d 例 %s"
          % (len(t8_violations), [v["order_id"] for v in t8_violations]))
    # 预注册 gate 不通过（引用侧三项）→ 不进分析集，全额登记（2026-11-02 修复：
    # 修复前 gate 一项都没施加，gate 破口的 run 仍被计入五臂率与 McNemar 格子）
    gate_excluded = [
        {"order_id": r["order_id"], "arm": r["arm"], "paper": r["paper"],
         "failed_gate_metrics": gate_failed_metrics(r),
         "quote_hit_rate": r.get("quote_hit_rate"), "all_hit": r.get("all_hit"),
         "judge_citation_passed": (r.get("judge_citation") or {}).get("passed"),
         "rubric_passed": r.get(GATE_RUBRIC_METRIC),
         "note": ("预注册 gate 指标不通过（引用侧门禁）→ 不计入臂统计与配对集；"
                  "该 run 的 all_hit 若为 True 则与 citation_unit.passed 语义背离"
                  "（预注册 binarization.rationale 的『与 passed 语义一致』前提被破）")}
        for r in runs
        if r.get("report_present") and r.get("t8_clean", True) and not gate_citation_pass(r)]
    print("  预注册 gate（引用侧 marker_align/sha_match/snapshot_present）不通过：%d 例 %s"
          % (len(gate_excluded), [v["order_id"] for v in gate_excluded]))
    gate_break_all_hit = [v["order_id"] for v in gate_excluded if v["all_hit"]]
    if gate_break_all_hit:
        print("    其中 all_hit=True（判官 passed=False，破预注册 binarization.rationale）：%s"
              % gate_break_all_hit)
    print("  预注册 gate（rubric_passed=R1-R5 全过）不通过（不作主集硬筛，敏感性见下行）：%d 例"
          % sum(1 for r in runs if r.get("report_present") and r.get("t8_clean", True)
                and not gate_rubric_pass(r)))
    wf_bytes_bad = [r["order_id"] for r in runs
                    if r["source"] == "workflow" and r["crosscheck"].get("reader_bytes_match") is False]
    print("  reader 实读字节 ↔ 冻结字节：mismatch %d 条 %s" % (len(wf_bytes_bad), wf_bytes_bad[:5]))

    # per-run 明细 jsonl（交付件）
    per_run_path = os.path.join(out_dir, "exp2-per-run-detail.jsonl")
    with open(per_run_path, "w", encoding="utf-8") as f:
        for r in runs:
            out = dict(r)
            out.pop("citation_detail", None)
            out.pop("judge_citation", None)
            out.pop("judge_rubric", None)
            out["citation_hit_detail"] = [
                {"n": d["n"], "status": d["status"], "snapshot_ref": d["snapshot_ref"]}
                for d in r["citation_detail"]]
            f.write(json.dumps(out, ensure_ascii=False) + "\n")
    print("  per-run 明细 → %s（%d 行）" % (per_run_path, len(runs)))

    # ---- 分配表对账 ----
    print("\n== 分配表对账（exp2-allocation.json ↔ 执行集）==")
    alloc_main = {(r["task_id"], r["arm"]) for r in alloc["runs"] if r["round"] == "main"}
    alloc_repeat = {(r["task_id"], r["arm"]) for r in alloc["runs"] if r["round"] == "repeat"}
    executed = {(r["paper"], r["arm"]) for r in runs}
    # repeat 维度按 run 身份计真值（2026-11-02 修复）：
    #   原式 executed 无 repeat 维（(paper,arm) 去重），而分配表 repeat 行复用主轮
    #   (task_id,arm)（alloc_repeat ⊆ alloc_main 恒成立），
    #   故 |executed∩alloc_repeat|−|executed∩alloc_repeat∩alloc_main| ≡ 0——
    #   与是否真跑 repeat 无关，登记通道恒报 0。现按「实跑的 repeat run」计。
    main_runs, rep_runs = split_by_round(runs)
    executed_main = {(r["paper"], r["arm"]) for r in main_runs}
    reg = repeat_registration(runs, alloc_repeat)
    repeat_present = reg["runs_present"]
    repeat_pairs_present = reg["pairs_present"]
    extra = executed_main - alloc_main
    print("  分配表 main: %d run；执行 (task,arm) 组合: %d；main 覆盖: %d/%d"
          % (len(alloc_main), len(executed), len(executed_main & alloc_main), len(alloc_main)))
    print("  分配表 repeat（B0/B2 第二跑）: %d run；实跑 repeat run: %d 个（覆盖 repeat 组合 %d/%d）"
          % (len(alloc_repeat), repeat_present, repeat_pairs_present, len(alloc_repeat)))
    print("  执行集中不在 main 分配表内的 (task,arm) 组合: %d 个 %s"
          % (len(extra), sorted(extra)[:5]))
    print("  → repeat 轮实跑登记：%d 个（=0 表示未执行 repeats，flakiness 估计不可得，如实登记）"
          % repeat_present)
    if reg["unmatched_runs"]:
        print("  → 另：实跑 repeat 但不在分配表 repeat 行内的 run %d 个 %s（全额登记）"
              % (reg["unmatched_runs"], reg["unmatched_order_ids"]))

    # ---- ② 数据门 ----
    print("\n== ② 数据门（verdict_precedence 首项 GATE:inconclusive；EXP-2=配对集<20）==")
    # 判据对比（进 decision_rules 的三组）+ 偏差登记的替代对比（描述性，不改判定）：
    # B4−B1 = 同模型（m31f）跨通道对照，是通道对照规则在 2026-10-30 通道/基座偏差后
    # 的正确绑定对象（EXP2-DEV-001）。此前该对比**从未被计算**（只在散文里被登记），
    # 且其配对集远小于数据门 → 本轮实算并把门状态写进偏差登记件。
    comparisons = [("B2", "B0"), ("B2", "B3"), ("B4", "B0")]
    descriptive_comparisons = [("B4", "B1")]
    all_comparisons = comparisons + descriptive_comparisons
    gate_rows = []
    for treat, ctrl in all_comparisons:
        pairs, unpaired = pair_runs(runs, treat, ctrl)
        n_p = len(pairs)
        gate_fires = n_p < 20
        role = "judgement" if (treat, ctrl) in comparisons else "descriptive"
        gate_rows.append({"comparison": "%s−%s" % (treat, ctrl), "role": role,
                          "n_paired": n_p,
                          "gate_paired_lt20": gate_fires, "gate_fires": gate_fires,
                          "unpaired_detail": unpaired})
        print("  %-8s [%s] n_paired=%2d（<20? %s）→ GATE %s"
              % ("%s−%s" % (treat, ctrl), role, n_p, n_p < 20,
                 "命中→inconclusive" if gate_fires else "通过"))
        if unpaired["missing_in_%s" % treat] or unpaired["missing_in_%s" % ctrl]:
            print("    缺 report：%s=%d %s=%d"
                  % (treat, len(unpaired["missing_in_%s" % treat]),
                     ctrl, len(unpaired["missing_in_%s" % ctrl])))

    # ---- ③ 五臂统计 + 配对对照 ----
    print("\n== ③ 五臂统计表 ==")
    summaries = {a: arm_summary(runs, a) for a in ARMS}
    # 分母口径自检（fail-loud）：五臂表分母必须是任务数。真跑 repeats 后若分母漂成
    # run 数，同一任务被数两次 → 与配对层（任务级）分母分裂。此闸只可能因实现回退
    # 而触发；命中即停止出件（数据不自证）。
    for a in ARMS:
        s = summaries[a]
        if s["n_eligible"] > s["n_tasks"]:
            print("  FAIL-LOUD: 臂 %s 的 eligible(%d) > 任务数(%d)——五臂表分母口径漂移"
                  % (a, s["n_eligible"], s["n_tasks"]))
            print("  五臂表分母必须是任务数（每任务取主轮 run），与配对层 pick_by_task 同规则")
            return 2
    for a in ARMS:
        s = summaries[a]
        print("  %-3s %-34s orders=%2d 任务=%2d(report %2d/eligible %2d) all_hit=%2d/%2d=%s"
              " Wilson95=[%s,%s] rate mean=%s tok=%s repeat_run=%d"
              % (a, ARM_LABEL[a], s["n_orders"], s["n_tasks"], s["n_with_report"],
                 s["n_eligible"], s["n_all_hit"], s["n_eligible"],
                 ("%.4f" % s["all_hit_rate"]) if s["all_hit_rate"] is not None else "NA",
                 ("%.3f" % s["all_hit_wilson95"][0]) if s["all_hit_wilson95"][0] is not None else "NA",
                 ("%.3f" % s["all_hit_wilson95"][1]) if s["all_hit_wilson95"][1] is not None else "NA",
                 ("%.4f" % s["quote_hit_rate_mean"]) if s["quote_hit_rate_mean"] is not None else "NA",
                 s["tokens_total_sum"] if s["tokens_total_sum"] is not None else "not_recorded",
                 s["repeat_runs"]))
    print("  rate 分布（quote_hit_rate → 任务数；每任务取主轮 run）：")
    for a in ARMS:
        print("    %-3s %s" % (a, summaries[a]["rate_distribution"]))

    print("\n== 配对对照（按 task_id 配对；all_hit 二值化）==")
    pair_stats = {}
    for treat, ctrl in all_comparisons:
        pairs, _ = pair_runs(runs, treat, ctrl)
        st = paired_stats(pairs, treat, ctrl)
        pair_stats[st["comparison"]] = st
        dL, dU, eq = st["tost_cp90_pp"]
        b95 = st["bootstrap95_pp"]
        print("  %-8s n_p=%2d b=%2d c=%2d s=%2d diff=%+7.2fpp McNemar p(1-sided,treat)=%.4f"
              " TOST CP90=[%s,%s]pp eq=%s boot95=[%s,%s]pp"
              % (st["comparison"], st["n_paired"], st["b_treat_better"], st["c_ctrl_better"],
                 st["s_discordant"], st["diff_pp"], st["mcnemar_p_one_sided_treat"],
                 ("%+.2f" % dL) if dL is not None else "NA",
                 ("%+.2f" % dU) if dU is not None else "NA", eq,
                 ("%.2f" % b95[0]) if b95[0] is not None else "NA",
                 ("%.2f" % b95[1]) if b95[1] is not None else "NA"))

    # 敏感性（不改主判定）
    print("\n== 敏感性（binarization half_hit / any_hit / ratio_paired_diff；不改主判定）==")
    sens = {}
    for treat, ctrl in all_comparisons:
        pairs, _ = pair_runs(runs, treat, ctrl)
        for binar in ("half_hit", "any_hit"):
            st = paired_stats(pairs, treat, ctrl, binar)
            sens["%s−%s[%s]" % (treat, ctrl, binar)] = {
                "n_paired": st["n_paired"], "b": st["b_treat_better"], "c": st["c_ctrl_better"],
                "diff_pp": st["diff_pp"], "mcnemar_p_one_sided_treat": st["mcnemar_p_one_sided_treat"],
                "tost_equivalent": st["tost_equivalent"]}
            print("  %-14s b=%2d c=%2d diff=%+7.2fpp p=%.4f tost_eq=%s"
                  % ("%s−%s[%s]" % (treat, ctrl, binar), st["b_treat_better"],
                     st["c_ctrl_better"], st["diff_pp"], st["mcnemar_p_one_sided_treat"],
                     st["tost_equivalent"]))
        st = pair_stats["%s−%s" % (treat, ctrl)]
        print("  %-14s ratio_paired_diff mean=%+7.2fpp boot95=[%s,%s]pp"
              % ("%s−%s[ratio]" % (treat, ctrl), st.get("ratio_paired_diff_mean_pp", float("nan")),
                 ("%+.2f" % st["ratio_paired_diff_bootstrap95_pp"][0])
                 if st.get("ratio_paired_diff_bootstrap95_pp") else "NA",
                 ("%+.2f" % st["ratio_paired_diff_bootstrap95_pp"][1])
                 if st.get("ratio_paired_diff_bootstrap95_pp") else "NA"))

    # ---- ③b 预注册 rubric gate 敏感性（rubric_passed 亦为 role=gate 的第四项）----
    # rubric_passed 判的是被测臂产出报告的 R1-R5 质量（结果侧量），按它硬筛=对结果
    # 变量取样；且实测若加筛则处理臂 B2 eligible 归零（rubric R1「节 id 闭集」在工作
    # 流臂结构性失败，通道差异所致）→ 主对比不可测。故不作主集硬筛，在此把该口径
    # 的后果全额登记（不静默丢弃预注册 gate 项）。
    def elig_with_rubric(r):
        return analysis_eligible(r) and gate_rubric_pass(r)

    print("\n== ③b 预注册 rubric gate 敏感性（加筛 rubric_passed=R1-R5 全过；不改主判定）==")
    rubric_gate_sensitivity = {
        "note": ("预注册 EXP-2.metrics[] 四项 role=gate 中的 rubric_passed。主分析集不按它"
                 "硬筛（判结果侧量=对结果变量取样；且加筛则处理臂归零），此处全额登记后果。"),
        "arm_eligible": {}, "comparisons": {},
    }
    for a in ARMS:
        prim = pick_by_task([r for r in runs if r["arm"] == a], a, elig=elig_with_rubric)
        n_r = len(prim)
        h_r = sum(1 for r in prim.values() if r.get("all_hit"))
        rubric_gate_sensitivity["arm_eligible"][a] = {
            "n_eligible": n_r, "n_all_hit": h_r,
            "all_hit_rate": (h_r / n_r if n_r else None)}
        print("  %-3s rubric gate 后 eligible=%2d all_hit=%2d rate=%s"
              % (a, n_r, h_r, ("%.4f" % (h_r / n_r)) if n_r else "NA"))
    for treat, ctrl in all_comparisons:
        pairs_r, _ = pair_runs(runs, treat, ctrl, elig=elig_with_rubric)
        st_r = paired_stats(pairs_r, treat, ctrl)
        rubric_gate_sensitivity["comparisons"]["%s−%s" % (treat, ctrl)] = {
            "n_paired": st_r["n_paired"], "b": st_r["b_treat_better"], "c": st_r["c_ctrl_better"],
            "diff_pp": st_r["diff_pp"],
            "mcnemar_p_one_sided_treat": st_r["mcnemar_p_one_sided_treat"],
            "data_gate_paired_lt20": st_r["n_paired"] < 20,
            "data_gate_note": ("n_paired<20 → 数据门 GATE:inconclusive（配对集不可测）"
                               if st_r["n_paired"] < 20 else "n_paired≥20")}
        print("  %-8s n_p=%2d b=%d c=%d diff=%+.2fpp p=%.4f 数据门(<20)=%s"
              % ("%s−%s" % (treat, ctrl), st_r["n_paired"], st_r["b_treat_better"],
                 st_r["c_ctrl_better"], st_r["diff_pp"],
                 st_r["mcnemar_p_one_sided_treat"], st_r["n_paired"] < 20))
    if rubric_gate_sensitivity["arm_eligible"]["B2"]["n_eligible"] == 0:
        print("  → rubric gate 加筛后处理臂 B2 eligible=0：主对比配对集归零、不可测"
              "（通道结构性失败所致，非本批数据缺陷）")


    # ---- ④ 终裁（薄适配层；臂未到齐 → pending）----
    print("\n== ④ 终裁（tools/b-verdict-unique.py 判定程序；EXP-2 全序首命中）==")
    vu_path = os.path.join(WS, "tools", "b-verdict-unique.py")
    spec_mod = importlib.util.spec_from_file_location("b_verdict_unique", vu_path)
    vu = importlib.util.module_from_spec(spec_mod)
    spec_mod.loader.exec_module(vu)
    # 数据门阈值：从预注册 inconclusive 规则文本取（不硬编码）——偏差登记件用它判
    # 「替代对照是否可评估」
    paired_min = None
    for dr in exp2.get("decision_rules") or []:
        if dr.get("verdict") == "inconclusive":
            _m = re.search(r"配对集任务数不足\s*(\d+)\s*条", str(dr.get("rule", "")))
            if _m:
                paired_min = int(_m.group(1))
    if paired_min is None:
        print("  FAIL-LOUD: 预注册 inconclusive 规则里取不到数据门阈值（配对集任务数不足 N 条）")
        return 2
    # 偏差登记件（机器可读；本脚本生成）：臂→模型指派 + 通道对照绑定与其可评估性
    generated_at = time.strftime("%Y-%m-%d %H:%M:%S %z")
    ledger = build_deviation_ledger(exp2_dir, spec_path, materials_path,
                                    pair_stats, paired_min, generated_at)
    ledger_path = os.path.join(out_dir, DEV_LEDGER_NAME)
    with open(ledger_path, "w", encoding="utf-8") as f:
        json.dump(ledger, f, ensure_ascii=False, indent=1)
    _b = ledger["deviations"][0]["channel_effect_binding"]
    print("  偏差登记件 → %s（%s）" % (ledger_path, ledger["deviations"][0]["id"]))
    print("    臂→模型指派：%s" % "；".join(
        "%s=%s" % (a, "/".join(ARM_MODEL_ASSIGNMENT[a]["model_ids"])) for a in ARMS))
    print("    通道对照绑定：预注册 %s（混杂=%s）→ 绑定 %s（同模型=%s；可评估=%s；n_p=%s < 门 %s）"
          % (_b["preregistered_comparison"], _b["confounded"], _b["replacement_comparison"],
             _b["replacement_same_model"], _b["replacement_evaluable"],
             _b["replacement_n_paired"], _b["replacement_data_gate_min"]))
    # 绑定：通道对照绑定来自偏差登记件（判定程序不硬绑预注册的 B4−B0）
    K = vu.bind_experiment(exp2, deviations=ledger, deviations_path=ledger_path)
    if K["paired_min"] != paired_min:
        print("  FAIL-LOUD: 判定程序绑定的数据门 %s ≠ 预注册规则文本取到的 %s"
              % (K["paired_min"], paired_min))
        return 2
    print("  绑定常量: plus_pp=%g margin_pp=%g alpha=%g paired_min=%d cost_pct=%s"
          % (K["plus_pp"], K["margin_pp"], K["alpha"], K["paired_min"], K["cost_pct"]))
    print("  全序: %s" % " > ".join(K["precedence"]))
    if not K["channel_resolvable"]:
        print("  通道问题不可解（fail-closed）：channel_effect 不可触发；归因类 verdict"
              "（confirmed/refuted/equivalent/cost_conditional）封存 → 终裁只能 inconclusive")

    main_st = pair_stats.get("B2−B0")
    aux_st = pair_stats.get("B2−B3")
    b4_cmp = K["channel_binding"]["comparison"]
    b4_st = pair_stats.get(b4_cmp)
    if b4_st is None:
        print("  FAIL-LOUD: 绑定的通道对照 %s 没有配对统计（对比未计算）" % b4_cmp)
        return 2
    verdict_arms = ["B0", "B2", "B3", "B4"]  # B1=描述臂（model-tier-control），不进 decision_rules
    missing_arms = [a for a in verdict_arms
                    if sum(1 for r in runs if r["arm"] == a and analysis_eligible(r)) == 0]
    verdict_block = {
        "tool": "tools/b-verdict-unique.py（工作区唯一实现；经 importlib 原样加载，未改判定逻辑）",
        "adapter": "本脚本只把观测配对表映射为 evaluate_fixed(K, n_p, cells) 的 (b,c,n_p)",
        "bound_constants": {"plus_pp": K["plus_pp"], "margin_pp": K["margin_pp"],
                            "alpha": K["alpha"], "paired_min": K["paired_min"],
                            "cost_pct": K["cost_pct"]},
        "precedence": K["precedence"],
        "channel_effect_binding": {
            "preregistered_comparison": K["channel_binding"]["preregistered_comparison"],
            "bound_comparison": b4_cmp,
            "confounded": K["channel_binding"]["confounded"],
            "same_model": K["channel_binding"]["same_model"],
            "evaluable": K["channel_binding"]["evaluable"],
            "resolvable": K["channel_resolvable"],
            "n_paired": b4_st["n_paired"],
            "data_gate_min": paired_min,
            "source": K["channel_binding"]["source"],
            "reason": _b["reason"],
        },
        "attribution_blocked": not K["channel_resolvable"],
        "attribution_block_note": (
            "通道问题不可解 → 归因类 verdict 一律封存（封存只把结论推向 inconclusive，"
            "不反向制造阳性结论）" if not K["channel_resolvable"] else "通道对照可解析 → 无封存"),
        "role_semantics_note": (
            "cells.b4 的绑定=%s（源：偏差登记件 %s；预注册绑定=%s 在 2026-10-30 通道/基座"
            "偏差后是「通道+基座模型」两因子混杂：B4=m31f vs B0=step-5，不再是纯通道对照）"
            "；同模型跨通道对照=%s（B4=minimax/Minimax-M3.1-Flash-Preview 工作流 vs "
            "B1=profile mavis-m31f→MiniMax-M3.1-Flash-Preview report 环），其实算配对集 "
            "n_p=%s、数据门=%s 条 → 可评估=%s"
            % (b4_cmp, K["channel_binding"]["deviation_id"],
               K["channel_binding"]["preregistered_comparison"], b4_cmp,
               b4_st["n_paired"], paired_min, K["channel_binding"]["evaluable"])),
    }
    if missing_arms or main_st is None or main_st["n_paired"] == 0:
        verdict_block["verdict"] = "pending"
        verdict_block["pending_reason"] = (
            "臂未到齐（无 report 的判据臂：%s）或主对比无配对任务——按任务纪律不出终裁，"
            "部分结果如实标 pending" % (missing_arms or ["主对比配对集为空"]))
        print("  VERDICT = pending（%s）" % verdict_block["pending_reason"])
    else:
        n_p = main_st["n_paired"]
        cells = {
            "main": (main_st["b_treat_better"], main_st["c_ctrl_better"]),
            "aux": (aux_st["b_treat_better"], aux_st["c_ctrl_better"]),
            "b4": (b4_st["b_treat_better"], b4_st["c_ctrl_better"]),
        }
        # 逐角色配对集：偏差后各对比的配对集不再同长（通道对照绑定 B4−B1 的配对集
        # 远小于主对比）→ 配对差必须用各自配对集算（否则分母错）
        n_p_by_role = {"b4": b4_st["n_paired"]}
        # 成本维度：cents/task B2 vs B0（>50% → cost=True）。工作流臂 not_recorded →
        # 成本维不可判定 → cost=False（cost_conditional 降级不可触发；如实登记）
        cost, cost_note = False, "B2 cents/task not_recorded（工作流臂 ask API 不暴露 usage）→ cost=False"
        gate_fires = vu.gate_fires(K, n_p)
        verdict, firing = vu.evaluate_fixed(K, n_p, cells, cost=cost,
                                            n_p_by_role=n_p_by_role)
        dL, dU, eq = vu.tost_diff_ci_pp(cells["main"][0], cells["main"][1], n_p, K["margin_pp"])
        print("  观测格子（n_p=%d）: main B2−B0 b=%d c=%d；aux B2−B3 b=%d c=%d；%s b=%d c=%d（n_p=%d）"
              % (n_p, cells["main"][0], cells["main"][1],
                 cells["aux"][0], cells["aux"][1], b4_cmp, cells["b4"][0], cells["b4"][1],
                 b4_st["n_paired"]))
        print("  gate_fires(n_p=%d)=%s（n_p<20: %s）" % (n_p, gate_fires, n_p < K["paired_min"]))
        print("  VERDICT = %s（firing=%s）" % (verdict, firing))
        print("  TOST CP90 映射区间 = [%+.4fpp, %+.4fpp]（边际 ±%gpp；strictly inside=%s）"
              % (dL, dU, K["margin_pp"], eq))
        verdict_block.update({
            "n_p": n_p, "cells": cells, "gate_fires": gate_fires,
            "verdict": verdict, "firing": firing,
            "main_tost_cp90_pp": [dL, dU],
            "mcnemar_p_one_sided": main_st["mcnemar_p_one_sided_treat"],
            "main_diff_pp": main_st["diff_pp"],
            "aux_diff_pp": aux_st["diff_pp"], "aux_ge0": aux_st["b_treat_better"] >= aux_st["c_ctrl_better"],
            "b4_diff_pp": b4_st["diff_pp"],
            "b4_comparison": b4_cmp,
            "cost_flag": cost, "cost_note": cost_note,
        })

    # ---- ⑤ 花费实测 ----
    print("\n== ⑤ 花费实测（report 臂 tokens 折算 vs 预算预估；工作流臂 not_recorded）==")
    n_orders = len(runs)
    tok_in = sum(r["tokens"]["input"] for r in runs if r["tokens"] and r["tokens"]["input"])
    tok_out = sum(r["tokens"]["output"] for r in runs if r["tokens"] and r["tokens"]["output"])
    tok_cache = sum(r["cache_read"] for r in runs if r["cache_read"])
    tok_total = tok_in + tok_out
    est_cents = tok_total * F5C_CENTS_PER_TOK
    planned_runs = exp2["sample_size"]["runs_total"]
    budget = exp2["budget"]
    cost = {
        "runs_planned": planned_runs, "runs_extracted": n_orders,
        "runs_report_arm": sum(1 for r in runs if r["source"] == "af-order"),
        "runs_workflow_arm": sum(1 for r in runs if r["source"] == "workflow"),
        "tokens_input": tok_in, "tokens_output": tok_out, "tokens_total": tok_total,
        "cache_read_total": tok_cache,
        "cents_spent_recorded": "not_recorded（ledger.jsonl 无记账行；工作流臂 ask API 不暴露 usage）",
        "折算基座": "F-第五单-交付-20261025.md:152 实测 report 环 2¢/17,935 tok（EXP-2.budget.basis 同引）",
        "cents_per_token": F5C_CENTS_PER_TOK,
        "cost_est_cents": est_cents, "cost_est_usd": est_cents / 100.0,
        "budget_usd_estimate": budget["usd_estimate"], "budget_usd_cap": budget["usd_cap"],
        "budget_basis": budget["basis"],
        "workflow_arm_cost_note": ("B2/B3/B4 的 tokens_total/cents_spent=not_recorded"
                                   "（agent().ask 不返回 usage；zcode 日志 totalTokens 脱敏）"
                                   "→ cost_conditional 判据不可触发（evaluate_fixed cost=False）"),
    }
    print("  runs: 计划 %d（含 repeats 48）/ 实提取 %d（report 臂 %d + 工作流臂 %d）"
          % (planned_runs, n_orders, cost["runs_report_arm"], cost["runs_workflow_arm"]))
    print("  tokens（report 臂）: input=%d output=%d total=%d（cache_read=%d）"
          % (tok_in, tok_out, tok_total, tok_cache))
    print("  折算成本: %d tok × 2¢/17,935tok = %.2f¢ ≈ $%.3f" % (tok_total, est_cents, est_cents / 100.0))
    print("  预算预估: $%.2f（cap $%.0f）；工作流臂成本 not_recorded（见 cost_note）"
          % (budget["usd_estimate"], budget["usd_cap"]))
    wall_total = sum(r["wall_clock_s"] for r in runs if r["wall_clock_s"])
    if wall_total:
        print("  墙钟合计（report 臂）: %.0f s（≈%.1f h；并发 4 理论 ≈%.1f h；预注册估 %.1f h）"
              % (wall_total, wall_total / 3600, wall_total / 3600 / 4, exp2["duration"]["total_hours"]))

    # ---- 汇总 json ----
    summary = {
        "artifact": "exp2-aggregate-v1", "exp_id": "EXP-2", "batch": exp2_dir,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S %z"),
        "spec": spec_path, "allocation": alloc_path, "materials": materials_path,
        # 预注册锁核销记录（随汇总件落盘 → 事后可对账：本账目消费的是哪一份材料字节）。
        # 修复前汇总件不记 materials 的 sha256（materials 仅一条路径字符串）→ 材料件
        # 被改后重算的账目事后无从发现；现记 锁登记值 + 实算值 + 核销结论。
        "materials_lock": {
            "lock_path": lock_info["lock_path"],
            "lock_sha256": lock_info["lock_sha256"],
            "actual_sha256": lock_info["actual_sha256"],
            "match": lock_info["match"],
            "lock_generated_at": lock_info["lock_generated_at"],
            "verified_at": time.strftime("%Y-%m-%d %H:%M:%S %z"),
            "policy": ("材料件 sha256 必须 == exp2-lock.json 登记值；失配（材料被改未重锁）"
                       "= 预注册漂移 → 聚合器 fail-loud 不出账（汇总件/逐 run 明细/偏差"
                       "登记件一律不写）。核销记录随本件落盘，事后可与锁件对账。"),
        },
        "mirror": os.path.abspath(args.mirror), "wf_dir": os.path.abspath(args.wf_dir),
        "binarization": exp2["metric_operationalization"]["binarization"]["selected"],
        "channel_deviation": {
            "occurred": "2026-10-30",
            "status": ("已登记偏差（材料件 sha256 锁不可改、正本只读 → 偏差不进材料件/正本；"
                       "机器可读真源=exp2-deviation-ledger.json（本文件 deviation_ledger 字段"
                       "指向它），散文登记于工作流注释/报告 §9/实验台账）"),
            "pre_registered": "三工作流臂（B2/B3/B4）基座通道=step-5（new-provider/step-5-preview，材料钉死值）",
            "executed": ("step provider 拒单（invalid_request，dwfrun-26f505c8）且运营者令"
                         " step 已过期不再使用 → 三臂整体改走 minimax 家族：B2=m31f+m3、"
                         "B3=2×m31f、B4=m31f"),
            "affected_arms": ["B2", "B3", "B4"],
            "semantic_consequence": (
                "B4−B0 不再是预注册语义「与 B0 同模型」的纯通道对照（B4=m31f vs B0=step-5："
                "通道+基座模型两因子混杂）；同模型跨通道对照相应移至 B4−B1（报告单侧对照臂取"
                " B1=mavis-m31f=同一基座 MiniMax-M3.1-Flash-Preview，dwf 注释登记）。"
                "【本轮实算】B4−B1 此前从未被计算：现入 paired/sensitivity/gate_rows，实算配对集"
                " n_p=%s < 预注册数据门 %s 条 → 数据门命中 → 该替代对照在本数据上**永不可评估**"
                " → 通道效应既不可证也不可否证 → 判定程序 fail-closed：channel_effect 不可触发，"
                "归因类 verdict 封存，终裁只能 inconclusive"
                % (_b["replacement_n_paired"], _b["replacement_data_gate_min"])),
            "replacement_comparison_status": {
                "comparison": _b["replacement_comparison"],
                "n_paired": _b["replacement_n_paired"],
                "data_gate_min": _b["replacement_data_gate_min"],
                "evaluable": _b["replacement_evaluable"],
                "reason": _b["reason"],
            },
            "registered_at": [
                "计划/研究组/实验批-20261029/exp2-deviation-ledger.json（机器可读真源）",
                "计划/研究组/实验批-20261029/exp2-workflow.dwf.ts:129-134",
                "计划/研究组/实验批-20261029/exp2-报告.md §9 五臂表模型列",
                "本文件 arm_summaries[*].model_assignment（tools/b-exp2-aggregate.py ARM_MODEL_ASSIGNMENT）",
            ],
        },
        "deviation_ledger": {
            "path": ledger_path,
            "artifact": ledger["artifact"],
            "deviation_id": ledger["deviations"][0]["id"],
            "arm_model_assignment": ledger["arm_model_assignment"],
            "channel_effect_binding": ledger["deviations"][0]["channel_effect_binding"],
            "falsified_preregistration_claims":
                ledger["deviations"][0]["falsified_preregistration_claims"],
        },
        "n_runs": n_orders,
        "n_with_report": sum(1 for r in runs if r.get("report_present")),
        "n_analysis_eligible": sum(1 for r in runs if r.get("analysis_eligible")),
        "prereg_gate": {
            "source": ("experiments-v1.json EXP-2.metrics[] 中 role=\"gate\" 的四项；"
                       "threats T3 mitigation 原文「合并提示词冻结 + 合并器档位登记 + "
                       "marker_align/sha_match 作 gate 指标先筛」"),
            "declared_gate_metrics": GATE_DECLARED_METRICS,
            "applied_to_primary_analysis_set": list(GATE_CITATION_METRICS),
            "gate_applied_rule": ("引用侧三项全过方可入分析集（缺值=不过，fail-closed）；"
                                  "gate 不通过的 run 全额登记于 gate_excluded，"
                                  "不计入臂统计与配对集"),
            "rubric_gate_treatment": (
                "rubric_passed 同样在预注册 role=gate 项集内，但不作主分析集硬筛："
                "它判被测臂产出报告的 R1-R5 质量（结果侧量），按它筛=对结果变量取样；"
                "且实测加筛则处理臂 B2 eligible 归零（rubric R1「节 id 闭集」在工作流臂"
                "结构性失败=通道差异，见 exp2-报告.md §9 效度限制 2），主对比不可测。"
                "按预注册 paired_set 原文「citation/rubric 双判官都跑完」口径（判官须"
                "跑完）入集；该 gate 的后果以敏感性口径全额登记于 rubric_gate_sensitivity"),
            "gate_excluded_count": len(gate_excluded),
            "gate_excluded": gate_excluded,
            "gate_break_all_hit_count": len(gate_break_all_hit),
            "gate_break_all_hit": gate_break_all_hit,
            "gate_break_note": (
                "以上 run 引用侧 gate 不过但 quote 全命中（all_hit=True）——修复前它们被"
                "计入五臂率与 McNemar 格子，与预注册 binarization.rationale「all_hit 与 "
                "citation_unit 的 passed 语义一致」的前提冲突"),
            "rubric_gate_sensitivity": rubric_gate_sensitivity,
            "regression_probe": "tools/test-exp2-gate.py（施加集+披露集==预注册 role=gate 集；"
                                "入集 run 必过 gate；报告/汇总件须披露 gate）",
        },
        "gate_rows": gate_rows, "arm_summaries": summaries,
        "run_record_model_check": {
            "manifest_path": manifest_path,
            "rows": len(manifest_rows),
            "rows_matching_assignment": len(manifest_rows) - len(manifest_model_problems),
            "problems": manifest_model_problems,
            "note": ("工作流臂机读运行记录逐行补登 models（源=工作流定义 exp2-workflow.dwf.ts "
                     "的 readers/writer_model 指派）；聚合器逐行核对=models 与偏差登记件的"
                     "臂→模型指派，不一致即 fail-loud"),
        },
        "paired": {k: {kk: vv for kk, vv in v.items() if kk != "rows"} for k, v in pair_stats.items()},
        "paired_rows": {k: v["rows"] for k, v in pair_stats.items()},
        "sensitivity": sens, "verdict": verdict_block, "cost": cost,
        "t8_violations": t8_violations,
        "allocation_check": {
            "alloc_main": len(alloc_main), "executed": len(executed),
            "main_covered": len(executed_main & alloc_main),
            "alloc_repeat": len(alloc_repeat),
            "repeat_runs_present": repeat_present,
            "repeat_pairs_present": repeat_pairs_present,
            "repeat_unmatched_runs": reg["unmatched_runs"],
            "repeat_registration_note": (
                "repeat 实跑数按 run 身份计（report 臂 order_id 带 -rN；工作流臂同 "
                "(arm,paper) 重复行）；旧式 |executed∩alloc_repeat|−|executed∩alloc_repeat"
                "∩alloc_main| 因 alloc_repeat ⊆ alloc_main 恒为 0，已废"),
            "extra_combinations": sorted(extra)[:10],
        },
        "extraction_problems": problems,
    }
    sum_path = os.path.join(out_dir, "exp2-aggregate-summary.json")
    with open(sum_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    print("\n汇总 → %s" % sum_path)
    print("per-run 明细 → %s" % per_run_path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
