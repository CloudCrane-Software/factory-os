#!/usr/bin/env python3
"""b-verdict-unique — 确证/反证判定程序唯一性机器验证（B线核心批-20261029 修复轮）。

背景（B线 cf 线复核员三项实证发现，修复工单）
--------------------------------------------
① 优先级不钉：decision_rules 之间无裁决优先级。穷举 n=24 全部 325 种配对结果，
  170 个可达 confirmed/refuted 格子里 168 个同时满足旧 inconclusive 首析取项
  「配对差 bootstrap 95% CI 宽度 >8pp」——同一数据两实现顺序给出相反 verdict；
  交付件自己的 rationale 样例 a=6,b=0（diff=25pp、McNemar 单侧 p=0.0156）同时命中
  confirmed 与 inconclusive。
② n=24 下宽度判据退化：任何可检出效应（20-25pp）的配对差 bootstrap 95% CI 宽度
  ≥33.3pp >8pp 恒真——该析取项在声明样本量下无判别力。
③ TOST 构造未钉：a=1,b=0 时按不一致对 Clopper-Pearson 90% CI 判「等效」、按配对差
  bootstrap 90% CI 判「不等效」——spec 未钉用哪个区间。

本工具对修复后的 spec（experiments-v1.json）做机器证明
------------------------------------------------------
* spec 绑定：从 decision_rules 文本正则抽取全部阈值（+5pp / ±5pp / −3pp / >50% /
  p<0.05 / 20 条 / 4 条），与 ci.tost 的钉死值交叉对账；verdict_precedence 必须是
  decision_rules verdict 集合的显式全序（排列，可选首个 GATE: 伪项）。
* 偏差感知（EXP-2 通道/基座偏差 EXP2-DEV-001，2026-10-30）：通道对照（channel_effect
  规则）**不得硬绑预注册的 B4−B0**——偏差后 B4=m31f ≠ B0=step-5，该差是「通道+基座模型」
  两因子混杂，不是纯通道效应。绑定改由机器可读偏差登记件
  （计划/研究组/实验批-20261029/exp2-deviation-ledger.json）声明：登记件给出替代对照
  （B4−B1，同模型跨通道）及其**可评估性**（该对照自身配对集是否过数据门）。判定程序据此
  分三种状态：
    ① 通道对照可解析（同模型 ∧ 可评估）→ 与预注册程序同语义；
    ② 通道对照不可解析（混杂未解 ∧ 替代对照不可评估）→ **fail-closed**：channel_effect
       不可触发，且归因类 verdict（confirmed/refuted/equivalent/cost_conditional）一律
       封存 → 终裁只能 inconclusive（预注册 precedence 注明的「B2 的任何结论都不可归因
       于跨模型」在通道问题未解时必须成立，封存只会把结论推向 inconclusive，不会反向
       制造任何阳性结论）；
    ③ 偏差登记件缺失/无本实验记录 → **BindingError 直接失败**（绑定不可验证不得裁决；
       不静默退回硬绑 B4−B0）。
  **声明面 vs 真值面（2026-11-03 RT 修复）**：偏差登记件只是**声明面**——改一个布尔
  （replacement_evaluable）即可解除归因类 verdict 全封存，而旧实现只核「登记件说的 ==
  绑定算出的」（自证闭环）、从不对账交付汇总件的真值 paired['B4−B1'].n_paired（实算 2），
  致封存断言静默消失（51→50 掉数而非转红）、门仍 exit=0。故本工具改以**交付汇总件
  exp2-aggregate-summary.json（实算面）**为真值来源：
    · 可评估性由真值 n_paired 与预注册数据门**重算**（不读登记件布尔）；
    · 「同模型」由 arm_summaries[B4/B1].model_assignment.model_ids 实算；
    · 登记件声明、真值面、汇总件内嵌的两份登记件副本三者任一不符 → BindingError
      （fail-closed；不得按声明裁决）；
    · 登记件与汇总件的 sha256 须在变更留痕面（计划/变更日志.md）登记（完整性锚：
      「在场但被改」面；RT-E84④ 同构）；
    · 封存面断言改为**无条件发射**（不随封存状态消失）+ 断言数下限（掉数即红）。
  预注册程序本身的唯一性证明不因封存而丢失：工具同时枚举「预注册通道绑定变体」
  （channel_resolvable=True）并照样要求覆盖率 100%/冲突数 0。
* 枚举：对每个实验枚举全部可达配对结果——n_p=0..tasks（tasks=sample_size.tasks，
  与规则对齐）上每个对比的 2×2 配对表 {(b,c): b+c ≤ n_p} 之积（跨臂对比的联合空间
  是逐任务向量真实可达空间的超集，在超集上证明唯一性 ⟹ 在可达子集上唯一性成立，
  保守论证）。空间过大时按「判定函数只依赖谓词向量」折叠为功能等价类（每类携带
  实现的格子组合数），另以固定种子随机抽 200,000 例联合格子组合走直接求值路径复核。
* 断言：每个可达结果恰有一个 verdict（首命中全序），输出覆盖率与冲突数（必须 0）；
  复核员样例 a=6,b=0 → confirmed、a=1,b=0 → equivalent，唯一且与修复后 spec 一致；
  v1 模式（无优先级 + 宽度析取项 + TOST 未钉）复现歧义计数，证明修复必要。
* --width-evidence：用精确 bootstrap（多项式重抽的精确分布，无 MC 噪声）复现①②的数字。

纯离线、仅标准库、零密钥、不写任何只读目录。退出码：0 全过；1 冲突/失败；2 用法错误。

用法
----
  python3 tools/b-verdict-unique.py                      # 验证真实 spec 并打印报告
  python3 tools/b-verdict-unique.py --spec PATH          # 指定 spec
  python3 tools/b-verdict-unique.py --deviations PATH    # 指定偏差登记件（声明面）
  python3 tools/b-verdict-unique.py --summary PATH        # 指定交付汇总件（实算面=真值来源）
  python3 tools/b-verdict-unique.py --width-evidence     # 宽度判据退化证据（发现①②）
  python3 tools/b-verdict-unique.py --selftest           # 自检（含负控；临时件落 $HOME）
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import random
import re
import sys
from fractions import Fraction
from math import comb

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SPEC = os.path.join(WS, "计划/研究组/B线核心批-20261029/experiments-v1.json")
#: 偏差登记件（机器可读）：正本（experiments-v1.json，只读）与 sha 锁材料件
#: （exp2-materials.json）都不可改 → 已发生的通道/基座偏差登记于此；判定程序据此绑定
#: 通道对照（channel_effect 规则），不硬绑预注册的 B4−B0。
DEFAULT_DEVIATIONS = os.path.join(
    WS, "计划/研究组/实验批-20261029/exp2-deviation-ledger.json")
#: 交付汇总件（实算面）：通道绑定可评估性的**真值面**——替代对照的配对集大小由聚合器
#: 实算写入 paired[*].n_paired、臂→模型指派写入 arm_summaries[*].model_assignment；
#: 偏差登记件只是**声明面**。两者必须对账（登记件不得自证；改一个布尔即解封是缺陷）。
DEFAULT_SUMMARY = os.path.join(
    WS, "计划/研究组/实验批-20261029/exp2-aggregate-summary.json")
#: 变更留痕面（sha256 登记的唯一留痕面，RT-E84④ 同构）：偏差登记件与交付汇总件的
#: sha256 须登记于此；登记值与实测值不符 → 红（「在场但被改」面的完整性锚）。
DEFAULT_CHANGELOG = os.path.join(WS, "计划/变更日志.md")
#: 自检断言数下限：断言被删或被条件分支跳过时「掉数而非转红」——下限钉死，掉数即红
#: （封存面断言不得随封存状态一起消失；见 _selftest 的封存面无条件断言）。
MIN_SELFTEST_CHECKS = 60
GATE = "GATE:"
VERDICT_CLOSED = {"confirmed", "refuted", "equivalent", "inconclusive",
                  "dose_unstable", "cost_conditional", "channel_effect"}
TOST_INTERVAL_CLOSED = {"clopper-pearson-conditional"}
SPOT_SAMPLES = 200000
SPOT_SEED = 20261029
#: TOST 端点与 ±5pp 边际的数值容差（pp）：端点与边际距离 ≤ 此值按「相等→域外」处理。
#: 数学上精确相等的格子只有 n_p∈{18,20} 上 s=1 的四个（CP 闭式端点 0/0.05/0.95/1 映射后恰为 ±5pp）；
#: 容差保证任何在 1e-9 pp 内一致的实现都给出同一 verdict（穷举证明的实现无关性）。
TIE_TOL_PP = 1e-9
MINUS = "[−-]"          # 规则文本里的减号是 U+2212（也容许 ASCII 连字符）
GE = "≥"


# ---------------------------------------------------------------- 精确统计量
def p_ge(b, s):
    """P(Bin(s, 0.5) >= b)——McNemar 精确检验单侧 p。分母 2^s，float 精确表示。"""
    if s <= 0 or b <= 0:
        return 1.0
    if b > s:
        return 0.0
    return sum(comb(s, k) for k in range(b, s + 1)) / float(1 << s)


def cp_interval(x, n, alpha=0.10):
    """Clopper-Pearson 双侧区间：L 解 P(Bin(n,L) >= x)=alpha/2；U 解 P(Bin(n,U) <= x)=alpha/2。
    二分求根（确定性；100 次迭代远超机器精度）。x=0 → L=0；x=n → U=1（精确）。"""
    lo = alpha / 2.0
    if x == 0:
        L = 0.0
    else:
        a, b_ = 0.0, 1.0
        for _ in range(100):
            m = (a + b_) / 2
            tail = sum(comb(n, k) * m ** k * (1 - m) ** (n - k) for k in range(x, n + 1))
            if tail > lo:      # upper_tail 随 p 递增：tail 偏大 → m 偏大
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
            if tail > lo:      # lower_tail 随 p 递减：tail 偏大 → m 偏小
                a = m
            else:
                b_ = m
        U = (a + b_) / 2
    return L, U


def tost_diff_ci_pp(b, c, n_p, margin_pp=5.0):
    """TOST 钉死构造：不一致对比例 π=b/s 的 CP 90% 区间，经映射 (2π−1)·s/n_p 到配对差（pp）。
    返回 (dL_pp, dU_pp, equivalent)。严格含于 (−margin, +margin)，端点与边际距离 ≤TIE_TOL_PP
    按相等→域外处理；s=0 按等效。"""
    s = b + c
    if s == 0:
        return 0.0, 0.0, True
    L, U = cp_interval(b, s, 0.10)
    dL = s * (2.0 * L - 1.0) * 100.0 / n_p
    dU = s * (2.0 * U - 1.0) * 100.0 / n_p
    return dL, dU, (dL > -margin_pp + TIE_TOL_PP and dU < margin_pp - TIE_TOL_PP)


def exact_bootstrap_pct_ci(b, c, n, q_lo, q_hi):
    """配对差均值的**精确** bootstrap 百分位 CI：多项式重抽的精确分布（Fraction，无 MC 噪声）。
    分位数约定：满足 CDF(v) >= q 的最小支撑值 v。q_lo/q_hi 为 Fraction。"""
    z = n - b - c
    dist = {}
    fact_n = 1
    for i in range(1, n + 1):
        fact_n *= i

    def fact(k):
        r = 1
        for i in range(1, k + 1):
            r *= i
        return r

    for bp in range(n + 1):
        pb = Fraction(b, n) ** bp if b else (Fraction(1) if bp == 0 else Fraction(0))
        for cp in range(n - bp + 1):
            pc = Fraction(c, n) ** cp if c else (Fraction(1) if cp == 0 else Fraction(0))
            zp = n - bp - cp
            pz = Fraction(z, n) ** zp if z else (Fraction(1) if zp == 0 else Fraction(0))
            mult = Fraction(fact_n, fact(bp) * fact(cp) * fact(zp))
            v = (bp - cp) / n
            dist[v] = dist.get(v, Fraction(0)) + mult * pb * pc * pz
    cdf = Fraction(0)
    lo_v = hi_v = None
    for v in sorted(dist):
        cdf += dist[v]
        if lo_v is None and cdf >= q_lo:
            lo_v = v
        if hi_v is None and cdf >= q_hi:
            hi_v = v
    return lo_v, hi_v


def bootstrap_width_pp_float(b, c, n):
    """配对差均值的 bootstrap 95% 宽度（pp，float 版）。仅用于 v1 模式复现：
    阈值 8pp 与真实宽度的裕度 ≥16pp，float 精度不影响布尔结论。"""
    if n == 0:
        return 0.0
    z = n - b - c
    dist = {}
    fact_n = 1.0
    for i in range(1, n + 1):
        fact_n *= i
    for bp in range(n + 1):
        pb = (b / n) ** bp
        for cp in range(n - bp + 1):
            zp = n - bp - cp
            pc = (c / n) ** cp
            pz = (z / n) ** zp
            f = 1.0
            for k in (bp, cp, zp):
                for i in range(1, k + 1):
                    f *= i
            dist[(bp - cp) / n] = dist.get((bp - cp) / n, 0.0) + fact_n / f * pb * pc * pz
    cdf = 0.0
    lo_v = hi_v = None
    for v in sorted(dist):
        cdf += dist[v]
        if lo_v is None and cdf >= 0.025:
            lo_v = v
        if hi_v is None and cdf >= 0.975:
            hi_v = v
    return (hi_v - lo_v) * 100.0


# ---------------------------------------------------------------- spec 绑定
class BindingError(Exception):
    pass


def _rx_one(pattern, text, what, cast=float):
    m = re.search(pattern, text)
    if not m:
        raise BindingError("规则文本中找不到 %s（pattern=%r，text=%r）" % (what, pattern, text[:80]))
    return cast(m.group(1))


def _no_width_in_condition(rule_text, verdict):
    cond = rule_text.split("→")[0]
    if "宽度" in cond:
        raise BindingError("规则 %s 的条件段以 CI 宽度作判据（n=24 下退化，修复轮已删除该析取项）" % verdict)


def load_deviations(path):
    """读机器可读偏差登记件。返回 (ledger|None, path)；文件不存在 → (None, path)。"""
    if not path or not os.path.isfile(path):
        return None, path
    with open(path, encoding="utf-8") as f:
        return json.load(f), path


def load_summary(path):
    """读交付汇总件（实算面）。返回 (summary|None, path)；文件不存在 → (None, path)。"""
    if not path or not os.path.isfile(path):
        return None, path
    with open(path, encoding="utf-8") as f:
        return json.load(f), path


def file_sha256(path):
    """文件字节流 sha256（完整性锚的实测值）。文件不可读 → None。"""
    if not path or not os.path.isfile(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def registered_sha256s(changelog_path, filename):
    """从变更留痕面读回该件登记过的 sha256 集合（登记串「<file> sha256=<64hex>」）。

    语义与 RT-E84④ 同构：登记值是「唯一留痕面」；当前实测 sha256 必须在登记集合内，
    否则「在场但被改」——红。重钉须留痕（登记串进变更日志），不得静默改值。
    """
    out = set()
    if not changelog_path or not os.path.isfile(changelog_path):
        return out
    pat = re.compile(re.escape(filename) + r"\s+sha256=([0-9a-f]{64})")
    with open(changelog_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            for m in pat.finditer(line):
                out.add(m.group(1))
    return out


def channel_truth(summary, comparison, gate_min, eid="EXP-2"):
    """通道绑定的**真值面**（交付汇总件实算产物），不取自偏差登记件的声明。

    · n_paired：汇总件 paired[comparison].n_paired（聚合器实算的配对集大小）；
    · evaluable：由 n_paired 与预注册数据门**重算**（n_paired ≥ gate_min），不读声明；
    · same_model：由汇总件 arm_summaries[B4/B1].model_assignment.model_ids 实算
      （B4 工作流臂 vs B1 report 环须同一基座模型），不读声明。

    真值面缺件/缺字段 → BindingError（真值不可验证不得裁决；不得退回「登记件自证」）。
    """
    if not summary:
        raise BindingError(
            "%s: 交付汇总件缺失或读不到（%s）——通道绑定真值面不可验证 → fail-closed"
            "（不得以偏差登记件的声明自证可评估性）" % (eid, getattr(summary, "path", "")))
    paired = summary.get("paired") or {}
    row = paired.get(comparison)
    if not isinstance(row, dict) or row.get("n_paired") is None:
        raise BindingError(
            "%s: 交付汇总件 paired 无对比 %s 的实算 n_paired——真值面缺项 → fail-closed"
            % (eid, comparison))
    n_p = int(row["n_paired"])
    arms = summary.get("arm_summaries") or {}
    b4 = ((arms.get("B4") or {}).get("model_assignment") or {})
    b1 = ((arms.get("B1") or {}).get("model_assignment") or {})
    ids4 = set(b4.get("model_ids") or [])
    ids1 = set(b1.get("model_ids") or [])
    if not ids4 or not ids1:
        raise BindingError(
            "%s: 交付汇总件 arm_summaries[B4/B1].model_assignment 缺 model_ids——"
            "同模型跨通道对照的「同模型」不可实算 → fail-closed" % eid)
    return {
        "n_paired": n_p,
        "evaluable": bool(n_p >= int(gate_min)),
        "same_model": bool(ids4 == ids1),
        "model_ids": {"B4": sorted(ids4), "B1": sorted(ids1)},
    }


def _summary_copy_problems(summary, comparison, truth, gate_min):
    """交付汇总件内嵌的两份登记件副本 vs 真值面：逐项列出不一致（空列表=一致）。

    副本①=summary["deviation_ledger"]["channel_effect_binding"]（登记件全文内嵌）；
    副本②=summary["channel_deviation"]["replacement_comparison_status"]（散文面结构化）。
    两副本与真值面/工作区登记件不一致 → 「三份登记件独立演化」→ BindingError。
    """
    problems = []
    emb = ((summary.get("deviation_ledger") or {}).get("channel_effect_binding")) or {}
    if emb:
        if emb.get("replacement_comparison") != comparison:
            problems.append("副本①替代对照=%r≠%r" % (emb.get("replacement_comparison"), comparison))
        if emb.get("replacement_n_paired") is not None \
                and int(emb["replacement_n_paired"]) != truth["n_paired"]:
            problems.append("副本①n_paired=%r≠真值%d" % (emb.get("replacement_n_paired"), truth["n_paired"]))
        if emb.get("replacement_evaluable") is not None \
                and bool(emb["replacement_evaluable"]) != truth["evaluable"]:
            problems.append("副本①evaluable=%r≠真值%s" % (emb.get("replacement_evaluable"), truth["evaluable"]))
        if emb.get("replacement_data_gate_min") is not None \
                and int(emb["replacement_data_gate_min"]) != int(gate_min):
            problems.append("副本①数据门=%r≠预注册%d" % (emb.get("replacement_data_gate_min"), gate_min))
        if emb.get("replacement_same_model") is not None \
                and bool(emb["replacement_same_model"]) != truth["same_model"]:
            problems.append("副本①same_model=%r≠真值%s" % (emb.get("replacement_same_model"), truth["same_model"]))
    st = ((summary.get("channel_deviation") or {}).get("replacement_comparison_status")) or {}
    if st:
        if st.get("comparison") != comparison:
            problems.append("副本②对比=%r≠%r" % (st.get("comparison"), comparison))
        if st.get("n_paired") is not None and int(st["n_paired"]) != truth["n_paired"]:
            problems.append("副本②n_paired=%r≠真值%d" % (st.get("n_paired"), truth["n_paired"]))
        if st.get("evaluable") is not None and bool(st["evaluable"]) != truth["evaluable"]:
            problems.append("副本②evaluable=%r≠真值%s" % (st.get("evaluable"), truth["evaluable"]))
        if st.get("data_gate_min") is not None and int(st["data_gate_min"]) != int(gate_min):
            problems.append("副本②数据门=%r≠预注册%d" % (st.get("data_gate_min"), gate_min))
    return problems


def bind_channel_contrast(eid, deviations, deviations_path, summary=None, gate_min=None):
    """通道对照（channel_effect 规则）的绑定——不得硬绑预注册的 B4−B0。

    EXP-2 已登记通道/基座偏差（EXP2-DEV-001，2026-10-30）：预注册的通道对照语义是
    「B4 与 B0 同模型同角色，唯一差别=通道」，偏差后 B4=m31f 而 B0=step-5 → 该差是
    「通道+基座模型」两因子混杂。绑定改由偏差登记件声明：
      * confounded=True → 绑定登记件的替代对照（替代对照=同模型跨通道对照 B4−B1）；
      * replacement_evaluable=False（替代对照自身配对集不过数据门）→ 通道问题不可解；
      * 登记件缺失/无本实验记录 → BindingError（绑定不可验证不得裁决，不静默退回硬绑）。

    **声明面 ≠ 真值面**（2026-11-03 RT 修复）：登记件的 replacement_evaluable /
    replacement_n_paired / replacement_same_model 是**声明**，改一个布尔即可解除归因类
    verdict 全封存而门不自知（自证闭环）。故 summary（交付汇总件，实算面）在位时：
      * 真值由汇总件实算（paired[*].n_paired、arm_summaries[*].model_assignment），
        evaluable 由真值 n_paired 与预注册数据门**重算**，不读登记件的布尔；
      * 登记件的声明与真值/副本不一致 → BindingError（fail-closed，不得按声明裁决）。
    返回 dict：comparison（实际绑定）、preregistered_comparison、same_model、evaluable、
    resolvable（=same_model ∧ evaluable）、evaluable_source（truth_derived|ledger_declared）。
    """
    prereg = "B4−B0"
    if not deviations:
        raise BindingError(
            "%s: 偏差登记件缺失或读不到（%s）——EXP-2 已登记通道/基座偏差，通道对照绑定"
            "不可验证 → fail-closed（不得按预注册硬绑 %s 判通道效应）"
            % (eid, deviations_path, prereg))
    recs = [d for d in (deviations.get("deviations") or [])
            if d.get("exp_id") == eid]
    if not recs:
        raise BindingError(
            "%s: 偏差登记件无本实验记录（%s）——通道对照绑定不可验证 → fail-closed"
            % (eid, deviations_path))
    rec = recs[0]
    b = rec.get("channel_effect_binding") or {}
    confounded = bool(b.get("confounded"))
    comparison = prereg
    same_model = True
    evaluable = True
    if confounded:
        comparison = b.get("replacement_comparison") or prereg
        same_model = bool(b.get("replacement_same_model", False))
        evaluable = bool(b.get("replacement_evaluable", False))
    # ---- 声明面 vs 真值面对账（summary 在位时；不在位 → 下方调用方必须 fail-loud）----
    declared_n = b.get("replacement_n_paired")
    declared_gate = b.get("replacement_data_gate_min")
    evaluable_source = "ledger_declared"
    truth = None
    if summary is not None:
        if gate_min is None:
            raise BindingError("%s: 真值对账缺预注册数据门（gate_min=None）" % eid)
        truth = channel_truth(summary, comparison, gate_min, eid)
        if declared_n is not None and int(declared_n) != truth["n_paired"]:
            raise BindingError(
                "%s: 偏差登记件声明的替代对照配对集 n_paired=%r ≠ 交付汇总件实算 n_paired=%d"
                "（声明面与真值面不符 → 不得按声明裁决；fail-closed）"
                % (eid, declared_n, truth["n_paired"]))
        if evaluable != truth["evaluable"]:
            raise BindingError(
                "%s: 偏差登记件声明的 replacement_evaluable=%r ≠ 真值推导（n_paired=%d vs "
                "预注册数据门 %d → evaluable=%s）——改一个布尔即解封是缺陷，不得按声明裁决"
                "（fail-closed）" % (eid, evaluable, truth["n_paired"], int(gate_min),
                                    truth["evaluable"]))
        if declared_gate is not None and int(declared_gate) != int(gate_min):
            raise BindingError(
                "%s: 偏差登记件声明的数据门=%r ≠ 预注册数据门 %d（预注册只读正本为准）"
                % (eid, declared_gate, int(gate_min)))
        if same_model != truth["same_model"]:
            raise BindingError(
                "%s: 偏差登记件声明的 replacement_same_model=%r ≠ 实算（B4 model_ids=%s vs "
                "B1 model_ids=%s）" % (eid, same_model, truth["model_ids"]["B4"],
                                       truth["model_ids"]["B1"]))
        problems = _summary_copy_problems(summary, comparison, truth, gate_min)
        if problems:
            raise BindingError(
                "%s: 交付汇总件内嵌登记件副本与真值面/工作区登记件不一致（三份登记件独立演化）"
                " → %s" % (eid, "；".join(problems)))
        # 真值面为准（声明已被证一致，取值即真值）
        evaluable = truth["evaluable"]
        same_model = truth["same_model"]
        evaluable_source = "truth_derived"
    return {
        "preregistered_comparison": prereg,
        "comparison": comparison,
        "source": "deviation_ledger:%s" % rec.get("id"),
        "ledger_path": deviations_path,
        "deviation_id": rec.get("id"),
        "confounded": confounded,
        "same_model": same_model,
        "evaluable": evaluable,
        "resolvable": bool(same_model and evaluable),
        "replacement_note": b.get("note"),
        "replacement_reason": b.get("reason"),
        "replacement_n_paired": b.get("replacement_n_paired"),
        "replacement_data_gate_min": b.get("replacement_data_gate_min"),
        "evaluable_source": evaluable_source,
        "truth_n_paired": (truth or {}).get("n_paired"),
        "truth_evaluable": (truth or {}).get("evaluable"),
        "truth_same_model": (truth or {}).get("same_model"),
        "declared_evaluable": bool(b.get("replacement_evaluable", False)) if confounded else True,
    }


def bind_experiment(exp, deviations=None, deviations_path=None, summary=None):
    """从 spec 文本抽取阈值并与 ci.tost / verdict_precedence 交叉对账。返回 model dict。

    deviations：机器可读偏差登记件（dict）；None → 走 fail-closed（见 bind_channel_contrast）。
    summary：交付汇总件（实算面）；EXP-2 通道绑定时提供 → 登记件声明必须与真值面一致，
             且封存状态取自真值（truth_derived），不取自登记件的自证布尔。
    """
    eid = exp.get("exp_id", "<无>")
    drs = exp.get("decision_rules") or []
    texts = {}
    for d in drs:
        v = d.get("verdict")
        if v in texts:
            raise BindingError("%s: verdict %r 在 decision_rules 里重复" % (eid, v))
        if v not in VERDICT_CLOSED:
            raise BindingError("%s: verdict=%r 不在闭集" % (eid, v))
        texts[v] = str(d.get("rule", ""))
        _no_width_in_condition(texts[v], v)
    op = exp.get("metric_operationalization") or {}
    ci = op.get("ci") or {}
    ss = exp.get("sample_size") or {}
    tasks = int(ss.get("tasks") or 0)
    if tasks != 24:
        raise BindingError("%s: sample_size.tasks=%r ≠24（数据门 20 条/4 条与枚举范围都按 24 推导）"
                           % (eid, ss.get("tasks")))

    K = {"exp_id": eid, "tasks": tasks, "texts": texts}
    if eid == "EXP-1":
        K["plus_pp"] = _rx_one(r"A1\s*%s\s*A2\s*≥\s*\+\s*([\d.]+)\s*pp" % MINUS, texts["confirmed"], "+5pp 阈值")
        K["dose_pp"] = _rx_one(r"A1d50\s*%s\s*A1\s*<\s*[−-]\s*([\d.]+)\s*pp" % MINUS, texts["dose_unstable"], "−3pp 剂量阈值")
        K["paired_min"] = int(_rx_one(r"配对集任务数不足\s*(\d+)\s*条", texts["inconclusive"], "配对集下限", int))
        K["unpaired_max"] = int(_rx_one(r"超过\s*(\d+)\s*条", texts["inconclusive"], "单臂缺失上限", int))
        K["cost_dim"] = False
        K["roles"] = ("main", "aux", "dose")
        K["kinds"] = {"main": "main", "aux": "aux_ge0", "dose": "dose"}
        K["labels"] = {"main": "A1−A2", "aux": "A1−A0", "dose": "A1d50−A1"}
        # EXP-1 无通道对照臂（decision_rules 无 channel_effect）→ 无通道封存
        K["channel_binding"] = {"applies": False,
                                "note": "EXP-1 无通道对照臂（无 channel_effect 规则）"}
        K["channel_resolvable"] = True
    elif eid == "EXP-2":
        K["plus_pp"] = _rx_one(r"B2\s*%s\s*B0\s*≥\s*\+\s*([\d.]+)\s*pp" % MINUS, texts["confirmed"], "+5pp 阈值")
        K["paired_min"] = int(_rx_one(r"配对集任务数不足\s*(\d+)\s*条", texts["inconclusive"], "配对集下限", int))
        K["unpaired_max"] = None
        K["cost_dim"] = True
        K["cost_pct"] = _rx_one(r"高出\s*>\s*(\d+)\s*%", texts["cost_conditional"], ">50% 成本阈值", int)
        K["roles"] = ("main", "aux", "b4")
        K["kinds"] = {"main": "main", "aux": "aux_ge0", "b4": "b4"}
        K["labels"] = {"main": "B2−B0", "aux": "B2−B3"}
        # 通道对照（b4）绑定：偏差感知——**此处不写死任何对照**，绑定一律由偏差登记件
        # 声明（预注册对照 B4−B0 只作为「登记在案的预注册绑定」被记录，见
        # bind_channel_contrast）；登记件缺失 → fail-closed 抛错。summary（实算面）在位
        # 时：登记件声明须与真值一致，封存状态取自真值（不得由声明自证）。
        K["channel_binding"] = bind_channel_contrast(
            eid, deviations, deviations_path, summary=summary, gate_min=K["paired_min"])
        K["labels"]["b4"] = K["channel_binding"]["comparison"]
        K["channel_resolvable"] = bool(K["channel_binding"]["resolvable"])
    else:
        raise BindingError("未知 exp_id=%r（本工具只覆盖 EXP-1/EXP-2）" % eid)
    K["alpha"] = _rx_one(r"单侧\s*p\s*<\s*([\d.]+)", texts["confirmed"], "alpha")
    K["margin_pp"] = _rx_one(r"±\s*([\d.]+)\s*pp", texts["equivalent"], "TOST 边际")

    # ---- ci.tost 钉死对账（发现③）----
    tost = ci.get("tost") or {}
    if tost.get("interval") not in TOST_INTERVAL_CLOSED:
        raise BindingError("%s: ci.tost.interval=%r 不在闭集 %s（TOST 区间方法未钉死）"
                           % (eid, tost.get("interval"), sorted(TOST_INTERVAL_CLOSED)))
    for k in ("level", "mapping", "equivalent_iff", "interval_construction", "margin_derivation"):
        if not str(tost.get(k, "")).strip():
            raise BindingError("%s: ci.tost 缺字段 %s（等效域推导未钉死）" % (eid, k))
    if abs(float(tost.get("alpha_per_side")) * 2 - (1.0 - float(str(tost.get("level")).rstrip("%")) / 100.0)) > 1e-12:
        raise BindingError("%s: ci.tost alpha_per_side 与 level 不一致" % eid)
    if float(tost.get("margin_pp")) != K["margin_pp"]:
        raise BindingError("%s: ci.tost.margin_pp=%r 与规则文本边际 ±%gpp 不一致"
                           % (eid, tost.get("margin_pp"), K["margin_pp"]))
    if not str(ci.get("width_criterion_status", "")).strip():
        raise BindingError("%s: ci.width_criterion_status 为空（宽度阈值是否在判定路径必须显式声明）" % eid)

    # ---- verdict_precedence 显式全序（发现①）----
    prec = op.get("verdict_precedence")
    if not isinstance(prec, list) or not prec:
        raise BindingError("%s: verdict_precedence 不是非空列表（必须是显式全序）" % eid)
    entries = [str(x) for x in prec]
    order = list(entries)
    if order and order[0].startswith(GATE):
        gate_v = order[0][len(GATE):]
        if gate_v not in texts:
            raise BindingError("%s: GATE 伪项指向不存在的 verdict %r" % (eid, gate_v))
        order = order[1:]
    if sorted(order) != sorted(texts):
        raise BindingError("%s: verdict_precedence=%r 不是 decision_rules verdict 集合 %r 的排列（全序未钉）"
                           % (eid, entries, sorted(texts)))
    if len(set(order)) != len(order):
        raise BindingError("%s: verdict_precedence 有重复项" % eid)
    if order[-1] != "inconclusive":
        raise BindingError("%s: 全序末位必须是兜底 inconclusive（实得 %r）" % (eid, order[-1]))
    K["precedence"] = entries
    K["order"] = order
    return K


# ---------------------------------------------------------------- 判定程序（参考实现）
_P_CACHE = {}
_CP_CACHE = {}
_WIDTH_CACHE = {}


def _p_ge_cached(b, s):
    key = (b, s)
    if key not in _P_CACHE:
        _P_CACHE[key] = p_ge(b, s)
    return _P_CACHE[key]


def _cp_cached(b, s):
    key = (b, s)
    if key not in _CP_CACHE:
        _CP_CACHE[key] = cp_interval(b, s, 0.10)
    return _CP_CACHE[key]


def _tost_cached(b, c, n_p, margin_pp):
    s = b + c
    if s == 0:
        return 0.0, 0.0, True
    L, U = _cp_cached(b, s)
    dL = s * (2.0 * L - 1.0) * 100.0 / n_p
    dU = s * (2.0 * U - 1.0) * 100.0 / n_p
    return dL, dU, (dL > -margin_pp + TIE_TOL_PP and dU < margin_pp - TIE_TOL_PP)


def _width_cached(b, c, n_p):
    key = (b, c, n_p)
    if key not in _WIDTH_CACHE:
        _WIDTH_CACHE[key] = bootstrap_width_pp_float(b, c, n_p)
    return _WIDTH_CACHE[key]


def cell_preds(K, role, b, c, n_p):
    """一个对比格子的谓词向量（键随角色而定）。"""
    kind = K["kinds"][role]
    s = b + c
    diff_pp = 0.0 if n_p == 0 else (b - c) * 100.0 / n_p
    out = {}
    if kind == "main":
        out["plus"] = diff_pp >= K["plus_pp"] and _p_ge_cached(b, s) < K["alpha"]
        out["minus"] = diff_pp <= -K["plus_pp"] and _p_ge_cached(c, s) < K["alpha"]
        out["tost"] = _tost_cached(b, c, n_p, K["margin_pp"])[2]
        out["eq_pt"] = abs(diff_pp) < K["margin_pp"]          # v1 文本的点估计部分（TOST 未钉）
        out["wide"] = _width_cached(b, c, n_p) > 8.0          # v1 的宽度析取项（8pp 硬编码于 v1 文本）
    elif kind == "aux_ge0":
        out["ge0"] = b >= c
    elif kind == "dose":
        out["fires"] = diff_pp < -K["dose_pp"]
    elif kind == "b4":
        out["plus"] = diff_pp >= K["plus_pp"] and _p_ge_cached(b, s) < K["alpha"]
    return out


def pred_key(K, role, b, c, n_p):
    p = cell_preds(K, role, b, c, n_p)
    return tuple(sorted(p.items()))


def gate_fires(K, n_p):
    if n_p < K["paired_min"]:
        return True
    if K["unpaired_max"] is not None and (K["tasks"] - n_p) > K["unpaired_max"]:
        return True
    return False


def rule_fires(K, verdict, P, cost):
    """规则是否命中。

    通道封存（fail-closed）：K["channel_resolvable"] 为 False 时，通道问题未解 →
    channel_effect 不可触发，且**归因类 verdict 一律封存**（预注册 precedence 注明的
    「通道本身移动指标时，B2 的任何结论（含『无差异』『净有害』）都不可归因于跨模型」
    在通道问题未解时必须成立）。封存只会把结论推向 inconclusive，不会反向制造阳性结论。
    """
    if verdict == "confirmed":
        return K["channel_resolvable"] and P["main"]["plus"] and P["aux"]["ge0"]
    if verdict == "refuted":
        return K["channel_resolvable"] and P["main"]["minus"]
    if verdict == "equivalent":
        return K["channel_resolvable"] and P["main"]["tost"]
    if verdict == "dose_unstable":
        return P["dose"]["fires"]
    if verdict == "channel_effect":
        return K["channel_resolvable"] and P["b4"]["plus"]
    if verdict == "cost_conditional":
        return K["channel_resolvable"] and P["main"]["plus"] and bool(cost)
    raise AssertionError("未实现的 verdict: %r" % verdict)


def evaluate_fixed(K, n_p, cells, cost, n_p_by_role=None):
    """修复后判定程序：数据门 → 全序首命中 → 兜底。返回 (verdict, firing)。

    n_p_by_role：可选的逐角色配对集大小（偏差后各对比的配对集不再同长时用；
    缺省 → 全部角色共用主对比的 n_p，与预注册程序同）。
    """
    if gate_fires(K, n_p):
        return "inconclusive", ["GATE:inconclusive"]
    P = {role: cell_preds(K, role, cells[role][0], cells[role][1],
                          (n_p_by_role or {}).get(role, n_p)) for role in K["roles"]}
    firing = [v for v in K["order"] if v != "inconclusive" and rule_fires(K, v, P, cost)]
    if not firing:
        return "inconclusive", ["inconclusive"]
    return firing[0], firing


def evaluate_v1(K, n_p, cells, cost):
    """v1 判定程序复现：**无优先级**（并列返回全部命中的规则，无仲裁）；inconclusive 含宽度析取项
    （宽度>8pp）与数据门析取项；equivalent 只按点估计 |diff|<5pp（TOST 构造未钉，本身就可两判）。
    注意 v1 的数据门只是 inconclusive 的一个析取项，不短路其他规则——这正是发现①的歧义来源之一。"""
    P = {role: cell_preds(K, role, cells[role][0], cells[role][1], n_p) for role in K["roles"]}
    firing = []
    if P["main"]["plus"] and P["aux"]["ge0"]:
        firing.append("confirmed")
    if P["main"]["minus"]:
        firing.append("refuted")
    if P["main"]["eq_pt"]:
        firing.append("equivalent")
    if P["main"]["wide"] or gate_fires(K, n_p):
        firing.append("inconclusive")
    if "dose" in P and P["dose"]["fires"]:
        firing.append("dose_unstable")
    if "b4" in P and P["b4"]["plus"]:
        firing.append("channel_effect")
    if P["main"]["plus"] and cost:
        firing.append("cost_conditional")
    return firing


# ---------------------------------------------------------------- 枚举
def enumerate_experiment(K, spot_samples=SPOT_SAMPLES, seed=SPOT_SEED, channel_resolvable=None):
    """枚举全部可达配对结果；返回统计 dict。空间过大 → 按谓词向量折叠为功能等价类
    （判定函数只读谓词向量，故类上判定=格子上判定），另加固定种子随机抽复核。

    channel_resolvable：覆盖通道封存状态（None=用 K 里的）。True → 预注册通道绑定
    变体（唯一性证明不被偏差封存弱化）；False → 封存变体（channel_effect 与归因类
    verdict 均不可达）。"""
    if channel_resolvable is not None:
        K = dict(K, channel_resolvable=channel_resolvable)
    tasks = K["tasks"]
    roles = K["roles"]
    total = 0
    by_verdict = {}
    conflicts = 0
    multi_fire = 0
    classes_total = 0
    v1_ambiguous = 0
    v1_total = 0
    min_margin_gap = None     # CP 端点与 ±5pp 边际的最小 |距离|（pp；0=精确相等）
    tie_cells = []
    spot_mismatch = 0
    rng = random.Random(seed)
    class_verdict = {}        # (n_p, keys, cost) -> verdict（供抽核对账）

    for n_p in range(0, tasks + 1):
        cell_lists = {r: [(b, c) for b in range(n_p + 1) for c in range(n_p + 1 - b)] for r in roles}
        groups = {}
        for r in roles:
            g = {}
            for cell in cell_lists[r]:
                key = pred_key(K, r, cell[0], cell[1], n_p)
                if key not in g:
                    g[key] = [0, cell]
                g[key][0] += 1
            if sum(cnt for cnt, _ in g.values()) != len(cell_lists[r]):
                raise AssertionError("%s n_p=%d 角色 %s 的谓词分组不覆盖全部格子" % (K["exp_id"], n_p, r))
            groups[r] = g
        cost_opts = [False, True] if K["cost_dim"] else [False]
        for combo in itertools.product(*[sorted(groups[r]) for r in roles], cost_opts):
            keys = combo[:len(roles)]
            cost = combo[-1]
            cells = {r: groups[r][k][1] for r, k in zip(roles, keys)}
            weight = 1
            for r, k in zip(roles, keys):
                weight *= groups[r][k][0]
            verdict, firing = evaluate_fixed(K, n_p, cells, cost)
            if not isinstance(verdict, str) or verdict not in VERDICT_CLOSED:
                conflicts += weight
            by_verdict[verdict] = by_verdict.get(verdict, 0) + weight
            total += weight
            classes_total += 1
            if len(firing) > 1:
                multi_fire += weight
            v1f = evaluate_v1(K, n_p, cells, cost)
            v1_total += weight
            if len(v1f) >= 2:
                v1_ambiguous += weight
            class_verdict[(n_p, keys, cost)] = verdict
        # 固定种子随机抽核：直接求值路径 vs 类路径
        for _ in range(max(1, spot_samples // (tasks + 1))):
            cells = {r: rng.choice(cell_lists[r]) for r in roles}
            cost = rng.random() < 0.5 if K["cost_dim"] else False
            verdict, _ = evaluate_fixed(K, n_p, cells, cost)
            keys = tuple(pred_key(K, r, cells[r][0], cells[r][1], n_p) for r in roles)
            if class_verdict.get((n_p, keys, cost)) != verdict:
                spot_mismatch += 1
        # CP 端点与边际的最小距离（数值稳健性证据）：≤容差按相等格子登记
        for b, c in cell_lists["main"]:
            if b + c == 0:
                continue
            dL, dU, _ = _tost_cached(b, c, max(n_p, 1), K["margin_pp"])
            for v in (abs(dL + K["margin_pp"]), abs(dU - K["margin_pp"])):
                if v <= TIE_TOL_PP:
                    if (n_p, b, c) not in tie_cells:
                        tie_cells.append((n_p, b, c))
                elif min_margin_gap is None or v < min_margin_gap:
                    min_margin_gap = v
    coverage = 100.0 if total == 0 else 100.0 * (total - conflicts) / total
    return {
        "exp_id": K["exp_id"], "total": total, "by_verdict": by_verdict,
        "conflicts": conflicts, "coverage": coverage, "multi_fire": multi_fire,
        "classes": classes_total, "v1_ambiguous": v1_ambiguous, "v1_total": v1_total,
        "spot_mismatch": spot_mismatch, "min_margin_gap": min_margin_gap, "tie_cells": tie_cells,
        "channel_resolvable": K["channel_resolvable"],
    }


def check_mutual_exclusivity(K):
    """equivalent 与 confirmed-stat/refuted-stat 不许共命中（全序之外的硬互斥）。"""
    bad = []
    for n_p in range(K["paired_min"], K["tasks"] + 1):
        for b in range(n_p + 1):
            for c in range(n_p + 1 - b):
                p = cell_preds(K, "main", b, c, n_p)
                if p["tost"] and (p["plus"] or p["minus"]):
                    bad.append((n_p, b, c))
    return bad


def reviewer_samples(K):
    """复核员两个历史样例：主对比格子 (6,0)/(1,0)，辅对比取中性格 (0,0)。"""
    out = {}
    for name, cell in (("a=6,b=0", (6, 0)), ("a=1,b=0", (1, 0))):
        cells = {"main": cell}
        for r in K["roles"]:
            if r != "main":
                cells[r] = (0, 0)
        verdict, firing = evaluate_fixed(K, K["tasks"], cells, False)
        v1f = evaluate_v1(K, K["tasks"], cells, False)
        out[name] = {"cell": cell, "verdict": verdict, "firing": firing, "v1_firing": v1f}
    return out


# ---------------------------------------------------------------- 宽度证据（发现①②）
def width_evidence(tasks=24, thr_pp=8.0):
    cells = [(b, c) for b in range(tasks + 1) for c in range(tasks + 1 - b)]
    reach = []
    for b, c in cells:
        s = b + c
        plus = (b - c) / tasks >= 0.05 and _p_ge_cached(b, s) < 0.05
        minus = (c - b) / tasks >= 0.05 and _p_ge_cached(c, s) < 0.05
        if plus or minus:
            reach.append((b, c))
    widths = {}
    for b, c in cells:
        lo, hi = exact_bootstrap_pct_ci(b, c, tasks, Fraction(1, 40), Fraction(39, 40))
        widths[(b, c)] = (hi - lo) * 100.0
    wide = [cell for cell in reach if widths[cell] > thr_pp]
    narrow = [(cell, widths[cell]) for cell in reach if widths[cell] <= thr_pp]
    det = []
    for b, c in cells:
        d = abs(b - c) / tasks * 100.0
        if 20.0 <= d <= 25.0:
            det.append(((b, c), widths[(b, c)]))
    det_w = [w for _, w in det]
    others = [widths[cell] for cell in cells if (cell[0] + cell[1]) >= 1
              and cell not in ((tasks, 0), (0, tasks))]
    return {
        "cells": len(cells), "reach": len(reach), "wide": len(wide), "narrow": narrow,
        "det_cells": len(det), "det_min": min(det_w), "det_max": max(det_w),
        "others_min": min(others), "thr_pp": thr_pp,
    }


# ---------------------------------------------------------------- 报告打印
def _fmt(n):
    return "{:,}".format(n)


def print_verification(models, results, samples_map, exclusivity, prereg_results=None):
    ok = True
    for idx, (K, R) in enumerate(zip(models, results)):
        print("=== %s（主对比 %s；枚举 n_p=0..%d） ===" % (R["exp_id"], K["labels"]["main"], K["tasks"]))
        cb = K.get("channel_binding") or {}
        if cb.get("applies") is False:
            print("  通道对照绑定: 不适用（%s）" % cb.get("note"))
        else:
            print("  通道对照绑定: %s（预注册 %s；源=%s；同模型=%s；可评估=%s）"
                  % (cb.get("comparison"), cb.get("preregistered_comparison"),
                     cb.get("source"), cb.get("same_model"), cb.get("evaluable")))
            if cb.get("evaluable_source") == "truth_derived":
                print("     可评估性来源=真值面（交付汇总件实算 n_paired=%s vs 预注册门 %s → "
                      "evaluable=%s；登记件声明已与之对账）"
                      % (cb.get("truth_n_paired"), cb.get("replacement_data_gate_min"),
                         cb.get("truth_evaluable")))
            if not K.get("channel_resolvable", True):
                print("  → 通道问题未解（fail-closed）：channel_effect 不可触发；"
                      "归因类 verdict（confirmed/refuted/equivalent/cost_conditional）封存 → 终裁只能 inconclusive")
                if cb.get("replacement_reason"):
                    print("     不可评估原因: %s" % cb.get("replacement_reason"))
        print("  枚举空间: n_p=0..%d × 对比 %s = %s 个格子组合（折叠为 %d 个功能等价类 + 固定种子抽核 %s 例）"
              % (K["tasks"], " × ".join(K["labels"][r] for r in K["roles"]),
                 _fmt(R["total"]), R["classes"], _fmt(SPOT_SAMPLES)))
        print("  verdict_precedence 全序: %s" % " > ".join(K["precedence"]))
        print("  覆盖率: %.4f%%（%s / %s 个可达结果各得一个 verdict）"
              % (R["coverage"], _fmt(R["total"] - R["conflicts"]), _fmt(R["total"])))
        print("  冲突数: %d（必须 0）" % R["conflicts"])
        print("  多规则共命中（由全序首命中仲裁）: %s 个结果" % _fmt(R["multi_fire"]))
        print("  抽核不一致: %d（必须 0）" % R["spot_mismatch"])
        print("  v1 模式（无优先级+宽度析取项+TOST 未钉）歧义结果: %s / %s"
              % (_fmt(R["v1_ambiguous"]), _fmt(R["v1_total"])))
        print("  CP 端点与 ±%gpp 边际: 相等格子（≤%gpp 容差）%s；其余最小距离 %.6g pp"
              % (K["margin_pp"], TIE_TOL_PP, R["tie_cells"] or "无",
                 R["min_margin_gap"] if R["min_margin_gap"] is not None else 0.0))
        dist = "，".join("%s=%s" % (k, _fmt(v)) for k, v in sorted(R["by_verdict"].items()))
        print("  各 verdict 可达结果数: %s" % dist)
        s = samples_map[R["exp_id"]]
        for name, d in s.items():
            print("  复核员样例 %s（n_p=%d，辅对比中性格）: 修复后 verdict=%s（唯一；firing=%s）；v1 模式 firing=%s → %s"
                  % (name, K["tasks"], d["verdict"], d["firing"], d["v1_firing"],
                     "歧义（无仲裁）" if len(d["v1_firing"]) >= 2 else "唯一"))
        if prereg_results is not None and idx < len(prereg_results) and prereg_results[idx]:
            RP = prereg_results[idx]
            distP = "，".join("%s=%s" % (k, _fmt(v)) for k, v in sorted(RP["by_verdict"].items()))
            print("  [预注册通道绑定变体（唯一性证明不被封存弱化）] 覆盖率 %.4f%%（%s / %s）；冲突数 %d；"
                  "各 verdict 可达结果数: %s"
                  % (RP["coverage"], _fmt(RP["total"] - RP["conflicts"]), _fmt(RP["total"]),
                     RP["conflicts"], distP))
            if RP["conflicts"] or RP["coverage"] < 100.0:
                ok = False
        if R["conflicts"] or R["spot_mismatch"] or R["coverage"] < 100.0:
            ok = False
    if exclusivity:
        print("硬互斥检查: equivalent 与 confirmed-stat/refuted-stat 共命中的格子数 = %d（必须 0）" % len(exclusivity))
        ok = ok and not exclusivity
    print("VERDICT-UNIQUE: %s" % ("PASS（覆盖率 100%%，冲突数 0）" if ok else "FAIL"))
    return ok


# ---------------------------------------------------------------- selftest
def _selftest():
    checks = []

    def check(name, cond):
        checks.append((name, bool(cond)))

    # ---- 1) 统计量单测 ----
    check("p_ge(6,6)=2^-6=0.015625", _p_ge_cached(6, 6) == 0.015625)
    check("p_ge(1,1)=0.5", _p_ge_cached(1, 1) == 0.5)
    check("p_ge(5,5)=0.03125<0.05（s=5 可达显著）", _p_ge_cached(5, 5) == 0.03125)
    check("p_ge(4,4)=0.0625>=0.05（s<=4 自动落灰区）", _p_ge_cached(4, 4) == 0.0625)
    check("p_ge(0,0)=1.0", _p_ge_cached(0, 0) == 1.0)
    L, U = cp_interval(1, 1, 0.10)
    check("CP90(1,1)=(0.05, 1.0)", abs(L - 0.05) < 1e-12 and U == 1.0)
    L, U = cp_interval(1, 2, 0.10)
    check("CP90(1,2)=(1−√0.95, √0.95)",
          abs(L - (1 - 0.95 ** 0.5)) < 1e-12 and abs(U - 0.95 ** 0.5) < 1e-12)
    L, U = cp_interval(6, 6, 0.10)
    check("CP90(6,6)=(0.05^(1/6), 1.0)", abs(L - 0.05 ** (1 / 6)) < 1e-12 and U == 1.0)
    L, U = cp_interval(0, 5, 0.10)
    check("CP90(0,5)=(0, 1−0.05^(1/5))", L == 0.0 and abs(U - (1 - 0.05 ** 0.2)) < 1e-12)
    dL, dU, eq = tost_diff_ci_pp(1, 0, 24, 5.0)
    check("TOST a=1,b=0,n_p=24 → (−3.75pp, +4.17pp) 含于 ±5pp → equivalent",
          abs(dL + 3.75) < 1e-9 and abs(dU - 4.1667) < 1e-3 and eq)
    dL, dU, eq = tost_diff_ci_pp(6, 0, 24, 5.0)
    check("TOST a=6,b=0 → 下界已出域（+5.35pp）→ 不等效", dL > 5.0 and not eq)
    # 端点精确相等格子：n_p=18/20 上 s=1 的四个 → 严格含于 + 容差 → 不等效（钉死的 tie 规则）
    _, _, eq1 = tost_diff_ci_pp(0, 1, 20, 5.0)
    _, _, eq2 = tost_diff_ci_pp(1, 0, 20, 5.0)
    _, _, eq3 = tost_diff_ci_pp(0, 1, 18, 5.0)
    _, _, eq4 = tost_diff_ci_pp(1, 0, 18, 5.0)
    check("端点相等格子 (n_p=20/18, s=1) 按域外处理 → 不等效", not (eq1 or eq2 or eq3 or eq4))
    # 精确 bootstrap vs 固定种子蒙特卡洛（100k 次重抽）对账
    rng = random.Random(SPOT_SEED)
    pop = [1] + [0] * 23                      # a=1,b=0 的 24 个配对差（一个 +1、23 个 0）
    mc = sorted(sum(rng.choices(pop, k=24)) / 24 for _ in range(100000))
    mc_lo, mc_hi = mc[int(0.05 * len(mc))], mc[int(0.95 * len(mc))]
    lo, hi = exact_bootstrap_pct_ci(1, 0, 24, Fraction(1, 20), Fraction(19, 20))
    check("精确 bootstrap 90% CI (0, 12.5pp) 与 100k 次重抽复算一致（±1 格点）",
          abs(float(lo) * 100 - mc_lo * 100) <= 100.0 / 24 + 1e-9
          and abs(float(hi) * 100 - mc_hi * 100) <= 100.0 / 24 + 1e-9)

    # ---- 2) 真实 spec 全量验证 ----
    try:
        with open(DEFAULT_SPEC, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError) as exc:
        print("SELFTEST FAIL: 读不到真实 spec: %s" % exc)
        return 1
    # 偏差登记件（机器可读）：EXP-2 通道对照绑定的事实源；缺失 → fail-closed（不静默硬绑）
    try:
        deviations, dev_path = load_deviations(DEFAULT_DEVIATIONS)
    except (OSError, ValueError) as exc:
        print("SELFTEST FAIL: 读不到偏差登记件 %s: %s" % (DEFAULT_DEVIATIONS, exc))
        return 1
    check("偏差登记件在位（机器可读，EXP-2 通道对照绑定的声明面）", deviations is not None)
    # 交付汇总件（实算面）：通道绑定真值的来源；缺失 → fail-closed（真值不可验证
    # 不得裁决；不得退回「登记件声明自证」——那正是本轮修复的缺陷面）。
    try:
        summary, sum_path = load_summary(DEFAULT_SUMMARY)
    except (OSError, ValueError) as exc:
        print("SELFTEST FAIL: 读不到交付汇总件 %s: %s" % (DEFAULT_SUMMARY, exc))
        return 1
    check("交付汇总件在位（实算面=EXP-2 通道绑定真值来源；登记件只作声明面）",
          summary is not None)
    if summary is None:
        print("SELFTEST FAIL: 交付汇总件缺失 → 通道绑定真值面不可验证 → fail-closed")
        return 1
    exps = doc.get("experiments") or []
    check("真实 spec 两个实验", len(exps) == 2)
    models, results, samples_map = [], [], {}
    prereg_results = []
    exclusivity = []
    try:
        for e in exps:
            K = bind_experiment(e, deviations=deviations, deviations_path=dev_path,
                                summary=summary)
            models.append(K)
            R = enumerate_experiment(K)
            results.append(R)
            # 预注册通道绑定变体（唯一性证明不被封存弱化）
            prereg_results.append(enumerate_experiment(K, channel_resolvable=True))
            samples_map[K["exp_id"]] = reviewer_samples(K)
            exclusivity += check_mutual_exclusivity(K)
    except (BindingError, AssertionError) as exc:
        print("SELFTEST FAIL: spec 绑定/枚举失败: %s" % exc)
        return 1
    ok = print_verification(models, results, samples_map, exclusivity, prereg_results)
    for R in results:
        check("%s 冲突数=0 且覆盖率=100%%" % R["exp_id"], R["conflicts"] == 0 and R["coverage"] == 100.0)
        check("%s 抽核不一致=0" % R["exp_id"], R["spot_mismatch"] == 0)
        check("%s 全枚举相等格子恰为 [(18,1,0),(18,0,1),(20,1,0),(20,0,1)]" % R["exp_id"],
              sorted(R["tie_cells"]) == [(18, 0, 1), (18, 1, 0), (20, 0, 1), (20, 1, 0)])
    check("equivalent 与显著差异不许共命中", not exclusivity)
    s1 = samples_map["EXP-1"]
    check("样例 a=6,b=0 → confirmed（唯一）", s1["a=6,b=0"]["verdict"] == "confirmed"
          and s1["a=6,b=0"]["firing"] == ["confirmed"])
    check("样例 a=6,b=0 在 v1 模式下同时命中 confirmed+inconclusive（复现发现①）",
          set(s1["a=6,b=0"]["v1_firing"]) == {"confirmed", "inconclusive"})
    check("样例 a=1,b=0 → equivalent（唯一，TOST 钉死）", s1["a=1,b=0"]["verdict"] == "equivalent"
          and s1["a=1,b=0"]["firing"] == ["equivalent"])
    check("样例 a=1,b=0 在 v1 模式下同时命中 equivalent+inconclusive（复现发现①③）",
          set(s1["a=1,b=0"]["v1_firing"]) == {"equivalent", "inconclusive"})
    for R in results:
        check("%s v1 模式歧义结果 >0（证明优先级修复必要）" % R["exp_id"], R["v1_ambiguous"] > 0)
    # 绑定常量等于预注册值（spec 漂移 → selftest fail-loud）
    K1 = models[0]
    check("EXP-1 绑定常量=预注册值（+5pp/±5pp/−3pp/0.05/20/4）",
          (K1["plus_pp"], K1["margin_pp"], K1["dose_pp"], K1["alpha"],
           K1["paired_min"], K1["unpaired_max"]) == (5.0, 5.0, 3.0, 0.05, 20, 4))
    K2 = models[1]
    check("EXP-2 绑定常量=预注册值（+5pp/±5pp/0.05/20/成本+50%）",
          (K2["plus_pp"], K2["margin_pp"], K2["alpha"], K2["paired_min"], K2["cost_pct"])
          == (5.0, 5.0, 0.05, 20, 50))

    # ---- 2b) 偏差感知（EXP-2 通道/基座偏差 EXP2-DEV-001）----
    cb = K2.get("channel_binding") or {}
    dev_recs = [d for d in (deviations.get("deviations") or []) if d.get("exp_id") == "EXP-2"]
    dev_binding = (dev_recs[0].get("channel_effect_binding") or {}) if dev_recs else {}
    check("EXP-2 通道对照绑定源=偏差登记件（不得硬绑预注册对照）",
          str(cb.get("source", "")).startswith("deviation_ledger:"))
    check("EXP-2 通道对照绑定≠预注册 B4−B0（偏差后 B4−B0 为通道+基座两因子混杂）",
          cb.get("preregistered_comparison") == "B4−B0"
          and cb.get("comparison") != "B4−B0")
    check("EXP-2 通道对照绑定=登记件声明的替代对照",
          bool(dev_recs) and cb.get("comparison") == dev_binding.get("replacement_comparison"))
    check("EXP-2 通道对照绑定的可解析状态=登记件声明（同模型 ∧ 可评估）",
          cb.get("same_model") == bool(dev_binding.get("replacement_same_model"))
          and cb.get("evaluable") == bool(dev_binding.get("replacement_evaluable"))
          and cb.get("resolvable") == K2["channel_resolvable"])
    # ---- 2c) 声明面 vs 真值面对账（2026-11-03 RT 修复：登记件不得自证）----
    # 真值面=交付汇总件实算（paired[*].n_paired / arm_summaries[*].model_assignment）；
    # 封存状态取自真值（truth_derived），登记件的布尔只作声明，须与真值一致。
    truth_n = cb.get("truth_n_paired")
    truth_eval = cb.get("truth_evaluable")
    truth_sm = cb.get("truth_same_model")
    check("EXP-2 通道绑定真值面在位（evaluable_source=truth_derived；不得由登记件声明自证）",
          cb.get("evaluable_source") == "truth_derived"
          and truth_n is not None and truth_eval is not None and truth_sm is not None)
    check("EXP-2 登记件声明的替代对照配对集 n_paired=%r=交付汇总件实算 n_paired=%r"
          % (cb.get("replacement_n_paired"), truth_n),
          cb.get("replacement_n_paired") == truth_n)
    check("EXP-2 登记件声明的 replacement_evaluable=%r=真值推导（n_paired=%r vs 预注册门 %d）"
          % (cb.get("declared_evaluable"), truth_n, K2["paired_min"]),
          cb.get("declared_evaluable") == truth_eval
          and truth_eval == bool(truth_n >= K2["paired_min"]))
    check("EXP-2 登记件声明的 replacement_same_model=%r=实算（B4/B1 model_ids 逐字同）"
          % (cb.get("truth_same_model"),),
          cb.get("truth_same_model") == cb.get("same_model"))
    check("EXP-2 登记件声明的数据门=%r=预注册数据门 %d（预注册只读正本为准）"
          % (cb.get("replacement_data_gate_min"), K2["paired_min"]),
          cb.get("replacement_data_gate_min") == K2["paired_min"])
    check("EXP-2 交付汇总件内嵌登记件副本=真值面（副本①deviation_ledger/副本②channel_deviation）",
          not _summary_copy_problems(summary, cb.get("comparison"),
                                     {"n_paired": truth_n, "evaluable": truth_eval,
                                      "same_model": truth_sm}, K2["paired_min"]))
    # 封存面断言：**无条件**（不随封存状态消失）——原实现用 if/else 分支，封存解除时
    # 断言整条消失（51→50 掉数而非转红）；此处改为按真值状态恒定发射 2 条断言。
    R2 = results[1]
    _sealed = not K2["channel_resolvable"]
    _ce = R2["by_verdict"].get("channel_effect", 0)
    _attr = {v: R2["by_verdict"].get(v, 0)
             for v in ("confirmed", "refuted", "equivalent", "cost_conditional")}
    check("EXP-2 通道封存面·channel_effect 可达数=%d（真值推导状态=%s → 封存须=0／可解析须>0）"
          % (_ce, "封存" if _sealed else "可解析"),
          (_ce == 0) if _sealed else (_ce > 0))
    check("EXP-2 通道封存面·归因类 verdict 可达数 confirmed=%d refuted=%d equivalent=%d "
          "cost_conditional=%d（真值推导状态=%s → 封存须全=0／可解析须>0）"
          % (_attr["confirmed"], _attr["refuted"], _attr["equivalent"],
             _attr["cost_conditional"], "封存" if _sealed else "可解析"),
          all(x == 0 for x in _attr.values()) if _sealed else all(x > 0 for x in _attr.values()))
    # 完整性锚：登记件与交付汇总件的 sha256 须在变更留痕面登记（RT-E84④ 同构）
    _led_sha = file_sha256(DEFAULT_DEVIATIONS)
    _sum_sha = file_sha256(DEFAULT_SUMMARY)
    _led_reg = registered_sha256s(DEFAULT_CHANGELOG, "exp2-deviation-ledger.json")
    _sum_reg = registered_sha256s(DEFAULT_CHANGELOG, "exp2-aggregate-summary.json")
    check("偏差登记件 sha256 已在变更留痕面登记（完整性锚：实测 %s；登记 %d 条）"
          % ((_led_sha or "<读不到>")[:12], len(_led_reg)),
          bool(_led_sha) and _led_sha in _led_reg)
    check("交付汇总件 sha256 已在变更留痕面登记（完整性锚：实测 %s；登记 %d 条）"
          % ((_sum_sha or "<读不到>")[:12], len(_sum_reg)),
          bool(_sum_sha) and _sum_sha in _sum_reg)
    R1 = results[0]
    check("EXP-1 无通道对照臂 → 不受封存影响（confirmed 仍可达）",
          R1["by_verdict"].get("confirmed", 0) > 0)
    P2 = prereg_results[1]
    check("EXP-2 预注册通道绑定变体仍 100%% 覆盖/0 冲突（唯一性证明未被封存弱化）",
          P2["coverage"] == 100.0 and P2["conflicts"] == 0)
    check("EXP-2 预注册通道绑定变体下 channel_effect 可达（封存非写死）",
          P2["by_verdict"].get("channel_effect", 0) > 0)

    # ---- 3) 负控：spec 变异必须被抓 ----
    import copy
    base = copy.deepcopy(doc)

    def mutated(fn):
        d = copy.deepcopy(base)
        fn(d)
        return d

    def first_exp(d):
        return d["experiments"][0]

    m = mutated(lambda d: first_exp(d)["metric_operationalization"]["verdict_precedence"].remove("equivalent"))
    try:
        bind_experiment(m["experiments"][0])
        check("verdict_precedence 缺 verdict → 被抓", False)
    except BindingError:
        check("verdict_precedence 缺 verdict → 被抓", True)

    m = mutated(lambda d: first_exp(d)["metric_operationalization"]["verdict_precedence"].append("confirmed"))
    try:
        bind_experiment(m["experiments"][0])
        check("verdict_precedence 重复项 → 被抓", False)
    except BindingError:
        check("verdict_precedence 重复项 → 被抓", True)

    m = mutated(lambda d: first_exp(d)["metric_operationalization"]["ci"].pop("tost"))
    try:
        bind_experiment(m["experiments"][0])
        check("ci.tost 未钉构造 → 被抓", False)
    except BindingError:
        check("ci.tost 未钉构造 → 被抓", True)

    m = mutated(lambda d: first_exp(d)["metric_operationalization"]["ci"]["tost"].update(interval="bootstrap-percentile"))
    try:
        bind_experiment(m["experiments"][0])
        check("ci.tost.interval 换成未钉死构造 → 被抓", False)
    except BindingError:
        check("ci.tost.interval 换成未钉死构造 → 被抓", True)

    def _width_rule(d):
        for r in first_exp(d)["decision_rules"]:
            if r["verdict"] == "inconclusive":
                r["rule"] = "配对差 CI 宽度 >8pp → 记未检出"

    m = mutated(_width_rule)
    try:
        bind_experiment(m["experiments"][0])
        check("规则条件段以 CI 宽度作判据 → 被抓", False)
    except BindingError:
        check("规则条件段以 CI 宽度作判据 → 被抓", True)

    def _margin_drift(d):
        for r in first_exp(d)["decision_rules"]:
            if r["verdict"] == "equivalent":
                r["rule"] = r["rule"].replace("±5pp", "±7pp")

    m = mutated(_margin_drift)
    try:
        bind_experiment(m["experiments"][0])
        check("规则文本边际与 ci.tost.margin_pp 漂移 → 被抓", False)
    except BindingError:
        check("规则文本边际与 ci.tost.margin_pp 漂移 → 被抓", True)

    m = mutated(lambda d: first_exp(d)["sample_size"].update(tasks=30))
    try:
        bind_experiment(m["experiments"][0])
        check("sample_size.tasks ≠24 → 被抓（枚举范围与数据门按 24 推导）", False)
    except BindingError:
        check("sample_size.tasks ≠24 → 被抓（枚举范围与数据门按 24 推导）", True)

    # ---- 3b) 负控：偏差登记件缺失/变异必须被抓 ----
    exp2 = [e for e in doc["experiments"] if e.get("exp_id") == "EXP-2"][0]
    try:
        bind_experiment(exp2, deviations=None, deviations_path=DEFAULT_DEVIATIONS)
        check("偏差登记件缺失 → EXP-2 绑定 fail-closed 抛错（不静默硬绑 B4−B0）", False)
    except BindingError:
        check("偏差登记件缺失 → EXP-2 绑定 fail-closed 抛错（不静默硬绑 B4−B0）", True)

    try:
        bind_experiment(exp2, deviations={"deviations": []}, deviations_path=DEFAULT_DEVIATIONS)
        check("偏差登记件无 EXP-2 记录 → EXP-2 绑定 fail-closed 抛错", False)
    except BindingError:
        check("偏差登记件无 EXP-2 记录 → EXP-2 绑定 fail-closed 抛错", True)

    # 变异登记件：把替代对照标为可评估 → **真值面仍判不可评估 → 必须被抓（封存不可由
    # 声明解除）**（2026-11-03 RT：原实现此处只核「登记件说的==绑定算出的」，改一个布尔
    # 即解封而门自证通过——缺陷本身；此处改为负控：声明与真值面不符 → BindingError）。
    dev_mut = copy.deepcopy(deviations)
    for d in dev_mut.get("deviations") or []:
        if d.get("exp_id") == "EXP-2":
            (d.get("channel_effect_binding") or {})["replacement_evaluable"] = True
    try:
        bind_experiment(exp2, deviations=dev_mut, deviations_path=DEFAULT_DEVIATIONS,
                        summary=summary)
        check("登记件标可评估（真值面判不可评估）→ 必须 BindingError（封存不可由声明解除）",
              False)
    except BindingError:
        check("登记件标可评估（真值面判不可评估）→ 必须 BindingError（封存不可由声明解除）",
              True)

    # 变异登记件：谎报替代对照配对集大小（2→25）→ 与交付汇总件实算不符 → 必须被抓
    dev_mut_n = copy.deepcopy(deviations)
    for d in dev_mut_n.get("deviations") or []:
        if d.get("exp_id") == "EXP-2":
            (d.get("channel_effect_binding") or {})["replacement_n_paired"] = 25
    try:
        bind_experiment(exp2, deviations=dev_mut_n, deviations_path=DEFAULT_DEVIATIONS,
                        summary=summary)
        check("登记件谎报 n_paired（2→25）→ 必须 BindingError（声明面≠实算面即红）", False)
    except BindingError:
        check("登记件谎报 n_paired（2→25）→ 必须 BindingError（声明面≠实算面即红）", True)

    # 变异登记件：把替代对照标为非同模型 → 与实算（B4/B1 同 model id）不符 → 必须被抓
    dev_mut2 = copy.deepcopy(deviations)
    for d in dev_mut2.get("deviations") or []:
        if d.get("exp_id") == "EXP-2":
            (d.get("channel_effect_binding") or {})["replacement_same_model"] = False
    try:
        bind_experiment(exp2, deviations=dev_mut2, deviations_path=DEFAULT_DEVIATIONS,
                        summary=summary)
        check("登记件标非同模型（实算判同模型）→ 必须 BindingError（声明面≠实算面即红）",
              False)
    except BindingError:
        check("登记件标非同模型（实算判同模型）→ 必须 BindingError（声明面≠实算面即红）",
              True)

    # ---- 3c) 真值驱动的合成面（负控）：封存由真值推导、非写死 ----
    def synth_summary(n_paired=None, b1_model_ids=None):
        """合成真值面（改实算值并同步两份内嵌副本）——证明封存随真值走、非写死。"""
        s = copy.deepcopy(summary)
        cmp_name = cb.get("comparison")
        emb = ((s.get("deviation_ledger") or {}).get("channel_effect_binding")) or {}
        st = ((s.get("channel_deviation") or {}).get("replacement_comparison_status")) or {}
        if n_paired is not None:
            ev = bool(n_paired >= K2["paired_min"])
            s["paired"][cmp_name]["n_paired"] = n_paired
            emb["replacement_n_paired"] = n_paired
            emb["replacement_evaluable"] = ev
            st["n_paired"] = n_paired
            st["evaluable"] = ev
        if b1_model_ids is not None:
            s["arm_summaries"]["B1"]["model_assignment"]["model_ids"] = list(b1_model_ids)
            emb["replacement_same_model"] = False
        return s

    # 真值判可评估（合成真值 n_p=25 ≥ 门 20）→ 通道可解析 → channel_effect 与归因类
    # 恢复可达（证「封存非写死」：封存由真值推导，不是把规则写死成永不可达）
    s_eval = synth_summary(n_paired=25)
    dev_eval = copy.deepcopy(deviations)
    for d in dev_eval.get("deviations") or []:
        if d.get("exp_id") == "EXP-2":
            _b = d.get("channel_effect_binding") or {}
            _b["replacement_evaluable"] = True
            _b["replacement_n_paired"] = 25
    try:
        K2m = bind_experiment(exp2, deviations=dev_eval, deviations_path=DEFAULT_DEVIATIONS,
                              summary=s_eval)
        R2m = enumerate_experiment(K2m)
        check("真值判可评估（合成真值 n_p=25≥门 20）→ 通道可解析 → channel_effect 与归因类"
              "恢复可达（封存非写死：由真值推导）",
              K2m["channel_resolvable"] is True
              and (K2m.get("channel_binding") or {}).get("evaluable_source") == "truth_derived"
              and R2m["by_verdict"].get("channel_effect", 0) > 0
              and R2m["by_verdict"].get("confirmed", 0) > 0)
    except (BindingError, AssertionError):
        check("真值判可评估（合成真值 n_p=25≥门 20）→ 通道可解析 → channel_effect 与归因类"
              "恢复可达（封存非写死：由真值推导）", False)

    # 真值判非同模型（合成真值：B1 换 model id）→ 通道不可解析 → 封存生效
    s_nsm = synth_summary(b1_model_ids=["synthetic/other-model"])
    dev_nsm = copy.deepcopy(deviations)
    for d in dev_nsm.get("deviations") or []:
        if d.get("exp_id") == "EXP-2":
            (d.get("channel_effect_binding") or {})["replacement_same_model"] = False
    try:
        K2n = bind_experiment(exp2, deviations=dev_nsm, deviations_path=DEFAULT_DEVIATIONS,
                              summary=s_nsm)
        R2n = enumerate_experiment(K2n)
        check("真值判非同模型（合成真值：B1 换 model id）→ 通道不可解析 → channel_effect 与"
              "归因类封存",
              K2n["channel_resolvable"] is False
              and R2n["by_verdict"].get("channel_effect", 0) == 0
              and R2n["by_verdict"].get("confirmed", 0) == 0)
    except (BindingError, AssertionError):
        check("真值判非同模型（合成真值：B1 换 model id）→ 通道不可解析 → channel_effect 与"
              "归因类封存", False)

    # ---- 4) 确定性：复跑结果逐字段一致 ----
    R_again = enumerate_experiment(models[0])
    check("枚举确定性（复跑逐字段一致）", R_again == results[0])

    # ---- 5) 断言数下限：断言被删/被条件分支跳过 → 「掉数而非转红」须转红 ----
    check("自检断言数 ≥ %d（下限：断言静默消失须转红，不得掉数蒙过）"
          % MIN_SELFTEST_CHECKS, len(checks) >= MIN_SELFTEST_CHECKS)

    failed = [n for n, c in checks if not c]
    for n, c in checks:
        print(("PASS" if c else "FAIL") + " - " + n)
    if failed or not ok:
        print("SELFTEST FAIL (%d/%d failed)" % (len(failed), len(checks)))
        for n in failed:
            print("  FAILED: " + n)
        return 1
    print("SELFTEST PASS (%d/%d)" % (len(checks), len(checks)))
    return 0


# ---------------------------------------------------------------- main
def main(argv):
    ap = argparse.ArgumentParser(description="确证/反证判定程序唯一性机器验证")
    ap.add_argument("--spec", default=DEFAULT_SPEC, help="experiments-v1.json 路径")
    ap.add_argument("--deviations", default=DEFAULT_DEVIATIONS,
                    help="偏差登记件路径（机器可读；EXP-2 通道对照绑定的声明面）")
    ap.add_argument("--summary", default=DEFAULT_SUMMARY,
                    help="交付汇总件路径（实算面；EXP-2 通道绑定真值来源）")
    ap.add_argument("--selftest", action="store_true", help="自检后退出")
    ap.add_argument("--width-evidence", dest="width_evidence", action="store_true",
                    help="宽度判据退化证据（精确 bootstrap，复现发现①②）")
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()

    if args.width_evidence:
        w = width_evidence()
        print("宽度判据退化证据（n=24，精确 bootstrap 95%% 百分位 CI，阈值 %gpp）:" % w["thr_pp"])
        print("  配对格子总数: %d" % w["cells"])
        print("  可达 confirmed/refuted 格子（两侧各自单侧 McNemar p<0.05 且 |diff|≥5pp）: %d" % w["reach"])
        print("  其中满足旧宽度析取项（宽度>%gpp）: %d" % (w["thr_pp"], w["wide"]))
        print("  例外（宽度≤%gpp）: %s" % (w["thr_pp"], w["narrow"]))
        print("  可检出效应 |diff|∈[20pp,25pp] 的 %d 个格子: 宽度 min=%.3fpp max=%.3fpp"
              % (w["det_cells"], w["det_min"], w["det_max"]))
        print("  全部 s≥1 格子（除两个全不一致极端格外）最小宽度: %.3fpp" % w["others_min"])
        bad = (w["wide"] != 168 or w["reach"] != 170 or w["det_min"] < 33.0)
        print("WIDTH-EVIDENCE: %s" % ("FAIL（与复核员数字不符）" if bad else "PASS（复现复核员 170/168 与 ≥33pp）"))
        return 1 if bad else 0

    if not os.path.isfile(args.spec):
        print("spec 不存在: %s" % args.spec, file=sys.stderr)
        return 2
    try:
        with open(args.spec, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError) as exc:
        print("spec 读不了: %s" % exc, file=sys.stderr)
        return 2
    try:
        deviations, dev_path = load_deviations(args.deviations)
    except (OSError, ValueError) as exc:
        print("偏差登记件读不了: %s" % exc, file=sys.stderr)
        return 2
    try:
        summary, sum_path = load_summary(args.summary)
    except (OSError, ValueError) as exc:
        print("交付汇总件读不了: %s" % exc, file=sys.stderr)
        return 2
    if summary is None:
        print("交付汇总件缺失（%s）——通道绑定真值面不可验证 → fail-closed（不得以登记件"
              "声明自证）" % args.summary, file=sys.stderr)
        return 2
    exps = doc.get("experiments") or []
    if len(exps) != 2:
        print("experiments 须为 2 个（实得 %d）" % len(exps), file=sys.stderr)
        return 2
    models, results, samples_map = [], [], {}
    prereg_results = []
    exclusivity = []
    try:
        for e in exps:
            K = bind_experiment(e, deviations=deviations, deviations_path=dev_path,
                                summary=summary)
            models.append(K)
            results.append(enumerate_experiment(K))
            prereg_results.append(enumerate_experiment(K, channel_resolvable=True))
            samples_map[K["exp_id"]] = reviewer_samples(K)
            exclusivity += check_mutual_exclusivity(K)
    except (BindingError, AssertionError) as exc:
        print("BINDING/ENUM FAIL: %s" % exc, file=sys.stderr)
        return 1
    ok = print_verification(models, results, samples_map, exclusivity, prereg_results)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
