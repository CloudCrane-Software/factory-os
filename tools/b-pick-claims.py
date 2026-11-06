#!/usr/bin/env python3
"""b-pick-claims — B 线「可工厂实测」断言筛选器（阶段三确证/反证专项，批次 B线核心批-20261029）。

定位
----
从 kb-v1 候选卡里筛出**能被本厂真实执行**的断言，给出可复算的排序与逐条不可测风险。
它是**分诊器（triage）不是裁决器**：闸门与排序全部是确定性规则，可独立复算；
最终选哪两条做专项实验由人/编排者在报告里裁定并留痕（工具输出=候选清单+理由素材）。

判据（硬闸，全部机器可判；任一不过 = 不可测，进不了候选清单）
-----------------------------------------------------------
G1 卡自评可测性：body.可测性 ∈ {4,5}（int 化后 ≥4）
G2 有可执行测试设计：body.测试设计 非空，且同时含
   (a) 对照标记：对照|对照组|A/B|臂|vs|配对
   (b) 量化指标标记：率|token|成本|美分|解决|resolved|pass|时延|墙钟|轮次|召回|准确|F1|IoU|偏差
G3 来源链路在场：link_dead != True 且 body.链接有效 == "有效"
G4 主张与证据一致：body.claim一致 == "一致"
G5 证据强度够用：body.证据强度 ≥ 3 或 body.等级 == "A"
G6 非基建型：大类不在 INFRA_ONLY（沙箱/容器/自托管缓存类改动本批预算外）
   ——不过 G6 不淘汰，只把通道降级为 infra-gap 并在风险里点名（宁缺毋滥：
     基建件仍值得做，但不是「数十美分级」能兑现的）。

通道推断（确定性关键词表，逐条给出命中词，可审计）
------------------------------------------------
先按**主张本身**（body.策略）匹配规则表；主张未命中任何组时再退到
body.测试设计 文本匹配（闭集，顺序即优先级）：
  prompt     提示/规则/技能/上下文/注入/AGENTS/CLAUDE/记忆/渐进/负面|负向/正向
  model      模型/档位/explorer/fixer/强弱/升级/路由/角色/便宜|低成本/小模型
  tool       工具/接口/ACI/edit/view/bash/检索/lint/命令行/shell
  orch       并行/并发/子代理/多 ?agent/辩论/投票/采样/委派/编排/合并
  metrology  评测/判分/统计/检验/CI/基准/污染/置信/功效/配对/ bootstrap
  infra      沙箱/容器/缓存/镜像/API/自托管/半价/Batch
未命中任何组 → channel="unclassified"（风险里点名「无通道可落」，不硬猜）。

**ASCII 关键词按词边界匹配**（`_kw_hit`）："CI" 不会命中 "ACI" 内部的 CI、
"batch" 不会命中 "batches"；含 CJK 的词按子串匹配。S060 的主张含 "ACI" 曾被
裸子串匹配误判为 metrology（已由词边界规则修正 → tool 通道）。

分数（可复算）
--------------
score = 可测性 × 证据强度 × 等级权重(A=1.0 / B=0.7 / C=0.4)
      + 0.5 × (证据等级 ∈ {benchmark, ablation} 或以其为前缀)
      + 0.1 × min(len(influence_hints), 10)
      - 0.2 × len(preconditions)
排序：score 降序，同分按 candidate_id 升序（确定性）。

**分数的性质（重要边界）**：全部输入都是**卡内自评字段**（可测性/证据强度/等级/证据等级）
与卡内登记的影响面/前置条件条数——它不是独立复算的效应量，也不是共识强度。
因此 score 只用于**分诊排序**（把卡排出队来人工裁断），不得当作「这条断言更真」的证据；
一把自评全满分的合成卡会排到 rank 1。终选由人在报告里按
「可测性 × 工厂当期决策价值」裁定并留痕。

实验文档校验（--check-experiments）额外覆盖
------------------------------------------
除字段在场性与闭集词表外，还做四类**交叉一致性**断言（三类校验路径共用）：
  A 操作化口径：比率型主指标必须钉 binarization.selected（闭集 all_hit/half_hit/any_hit）
    + rule + paired_set + ci.method + ci.width_threshold_pp（与规则文本数值一致）
    + sensitivity + verdict_precedence；用 McNemar 的规则必须落在有二值化口径的实验上。
  B 输入完整性：inputs.cards_sha256 必须等于**卡文件本体**重算 sha256（不是语料哈希）；
    source_corpus_sha256 必须等于卡内 source.corpus_sha256；两者不得相同。
  C 计数对齐：inputs.candidates_emitted/rejected 必须等于候选清单 stats。
  D 同文档算术：budget.model_calls_total 与 sample_size.model_calls_total 必须一致，
    且（per_model_call 时）等于 units。
  E 判定程序唯一性（第三轮复核「判定程序不唯一可机判」修复轮新增）：
    E1 verdict_precedence 是 decision_rules verdict 的**显式全序**（非空列表；排列且无重复；
       可选首个 GATE:<verdict> 数据门伪项；末位必须是兜底 inconclusive）；
    E2 TOST 构造钉死：ci.tost 五要素（level/mapping/equivalent_iff/interval_construction/
       margin_derivation）在场，interval ∈ {clopper-pearson-conditional}，margin_pp 与
       equivalent 规则文本的 ±Npp 一致；
    E3 宽度阈值退出判定路径：规则条件段（首个 → 之前）不得含「宽度」（n=24 下该析取项退化：
       可检出效应 20-25pp 的 bootstrap 95% CI 宽度 ≥33.3pp>8pp 恒真），ci.width_criterion_status
       必填（显式声明宽度阈值只作报告标注口径）。
  唯一性的**机器证明**（枚举全部可达配对结果、冲突数=0）在 tools/b-verdict-unique.py。

用法
----
  python3 tools/b-pick-claims.py                     # 打印候选清单（默认输入）
  python3 tools/b-pick-claims.py --input PATH        # 指定卡文件
  python3 tools/b-pick-claims.py --emit PATH         # 写 JSON 候选清单（幂等）
  python3 tools/b-pick-claims.py --exec workflow     # 只留能落到该执行面的候选
  python3 tools/b-pick-claims.py --top N             # 只列前 N 条
  python3 tools/b-pick-claims.py --check-experiments PATH   # 校验 experiments-v1.json 自洽性
                                                          # （含 inputs 哈希/计数与卡文件、候选清单对账）
  python3 tools/b-pick-claims.py --selftest          # 自检（临时件落 $HOME，跑完清理）

纯离线、仅标准库、零密钥、不写任何只读目录。退出码：0 正常/自检全过；1 自检失败；2 用法错误。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CARDS = os.path.join(
    WS, "kb-seed/candidates-batch1/b线-20261028/cards-v1.jsonl"
)

CHANNELS = ("prompt", "model", "tool", "orch", "metrology", "infra", "unclassified")
GRADE_WEIGHT = {"A": 1.0, "B": 0.7, "C": 0.4}
INFRA_ONLY = {"执行与沙箱", "成本与推理效率"}

CTRL_RE = re.compile(r"对照|对照组|A/B|臂|\bvs\b|配对")
METRIC_RE = re.compile(
    r"率|token|成本|¢|\$|解决|resolved|pass|时延|墙钟|轮次|召回|准确|F1|IoU|偏差|花费|成本价"
)

# 通道规则表：顺序即优先级（先命中先定），每条给出可审计的命中词
CHANNEL_RULES = [
    ("metrology", ["评测", "判分", "统计", "检验", "CI", "基准", "污染", "置信", "功效", "配对", "bootstrap", "榜单", "排名"]),
    ("prompt", ["提示", "规则", "技能", "上下文", "注入", "AGENTS", "CLAUDE", "记忆", "渐进", "负向", "正向", "skill"]),
    ("model", ["模型", "档位", "explorer", "fixer", "强弱", "升级", "路由", "角色", "便宜", "低成本", "小模型"]),
    ("tool", ["工具", "接口", "ACI", "edit", "view", "bash", "检索", "lint", "命令行", "shell"]),
    ("orch", ["并行", "并发", "子代理", "多 agent", "多agent", "辩论", "投票", "采样", "委派", "编排", "合并", "子任务"]),
    ("infra", ["沙箱", "容器", "缓存", "镜像", "API", "自托管", "半价", "Batch", "batch"]),
]

#: 通道 → 可兑现它的工厂执行面（闭集）。用来回答「这条断言本批到底跑不跑得起来」。
#: report-unit = af-order --unit report（任务包只改 task.json 的 focus/paper_sha256，零码动）；
#: workflow   = 动态工作流子代理（多模型/多角色扇出）；
#: swev/graph-unit = 代码任务单（需工具面/多节点，改包或改计划）；
#: infra-gap  = 需沙箱/容器/缓存/计费面基建，先立项后见效。
EXEC_MAP = {
    "prompt": ("report-unit", "workflow"),
    "model": ("report-unit", "swev-unit", "graph-unit", "workflow"),
    "tool": ("swev-unit", "graph-unit"),
    "orch": ("graph-unit", "workflow"),
    "metrology": ("workflow",),
    "infra": ("infra-gap",),
    "unclassified": (),
}

# 每条规则的触发条件与产出的不可测风险（确定性；空列表=无额外风险）
RISK_RULES = [    (lambda c, b: str(b.get("可测性", "")).strip() != "5",
     "卡自评可测性<5：判据可能依赖 harness 尚未实现的机制，需先确认执行面在场"),
    (lambda c, b: str(b.get("证据等级", "")).startswith("anecdotal"),
     "证据等级=anecdotal（轶事级）：效应量与方向都可能不成立，先小样本探针再扩量"),
    (lambda c, b: (_as_int(b.get("证据强度")) or 0) < 3,
     "证据强度<3（仅因等级 A 被 G5 放行）：效应量证据薄，必须先小样本探针再扩量"),
    (lambda c, b: "撤稿" in str(b.get("证据等级", "")),
     "原论文已撤稿：证据效力近零，只能当反面线索不能当正面假设"),
    (lambda c, b: len(c.get("preconditions") or []) >= 3,
     "前置条件≥3 条：实验须逐条满足并在报告登记，否则结论不可外推"),
    (lambda c, b: len(c.get("preconditions") or []) == 0,
     "无前置条件登记：适用边界未知，外推风险由实验设计自行兜底（固定任务域/模型档）"),
    (lambda c, b: b.get("大类") in INFRA_ONLY,
     "大类属基建族（沙箱/容器/成本设施）：改动面大，超出数十美分级预算，须单独立项"),
    (lambda c, b: "自研" in str(b.get("测试设计", "")) or "自建" in str(b.get("测试设计", "")),
     "测试设计依赖自研/自建组件：须先核组件在场（仓库/镜像/工具），否则执行面缺位"),
    (lambda c, b: "不适用" in str(b.get("测试设计", "")),
     "卡自述不适用于 A/B（方法论采纳件）：走工作流/离线分析通道，不走对照订单"),
    (lambda c, b: len(str(b.get("测试设计", ""))) < 40,
     "测试设计描述过短：实验参数（臂/样本/指标）需设计者补齐后才能预注册"),
]

#: 常驻威胁（每一条候选都成立，不因卡而异——不是凑数，是每个受控实验共同面对的有效性威胁）
UNIVERSAL_RISKS = [
    "效应量外推：卡内数字来自原论文的任务域/模型档/预算，迁到本厂任务域与档位须以本厂探针复算，不得照抄 pp 值",
    "判分链依赖：结论只对冻结判分链有效（判分器/镜像/venv 指纹须登记 sha256），指纹一变结论作废重跑",
    "单变量隔离：臂间只能差一个变量（模型档/提示词/工具集/预算四选一），其余固定，否则结论不可归因",
]


# ---------------------------------------------------------------- experiments 校验
#: 判定词表（闭集）：四态结论 + 两类条件结论
VERDICTS = {"confirmed", "refuted", "equivalent", "inconclusive",
            "dose_unstable", "cost_conditional", "channel_effect"}
#: 判定规则必须钉的检验名（闭集；防「且显著」这种机读不了的默认值）
TESTS = {"McNemar", "TOST", "Wilson", "bootstrap", "Fisher", "精确检验"}
#: TOST 区间方法闭集（第三轮复核修复轮钉死：唯一构造=不一致对比例的 Clopper-Pearson 条件区间；
#: 配对差 bootstrap 区间因依赖 RNG/种子/重抽次数且 n=24 小 s 时粗细由噪声决定，退出判定路径）
TOST_INTERVAL_CLOSED = {"clopper-pearson-conditional"}
#: 二值化口径闭集（比率型主指标进 McNemar 前必须钉死，否则判定不可复现）
BINARIZATIONS = {"all_hit", "half_hit", "any_hit"}
#: 每个实验必有的固定字段（工单六要素 + 溯源 + 操作化口径）
EXP_REQUIRED = [
    "exp_id", "title", "primary_claim", "hypothesis", "arms", "randomization",
    "sample_size", "execution", "metrics", "metric_operationalization",
    "decision_rules", "budget", "duration", "threats", "preregistration", "status",
]
#: 文档级 inputs 必填（输入完整性必须钉对对象：卡文件哈希 ≠ 语料哈希）
INPUTS_REQUIRED = ["cards", "cards_total", "cards_sha256", "source_corpus",
                   "source_corpus_sha256", "candidate_list", "candidates_emitted",
                   "candidates_rejected", "picker"]
USD_CAP = 30  # 「预算 ≤ 数十美分级」的硬顶


def check_experiments(doc, card_ids, cards_path=None, candidates_path=None):
    """校验 experiments-v1.json 的自洽性。返回 findings 列表（空=全过）。

    cards_path / candidates_path 给出时额外做「输入完整性」对账：
      - inputs.cards_sha256 必须等于 cards 文件**本身**的重算 sha256（不是语料哈希）；
      - inputs.source_corpus_sha256 必须等于卡内 source.corpus_sha256；
      - inputs.candidates_emitted/rejected 必须等于候选清单的 stats。
    """
    f = []
    if not isinstance(doc, dict):
        return ["experiments 文档不是 JSON object"]
    if doc.get("schema_ver") != "bline-exp-v1":
        f.append("schema_ver=%r（要求 bline-exp-v1）" % doc.get("schema_ver"))
    # ---- inputs：字段齐 + 哈希钉对对象 + 计数对齐 ----
    inp = doc.get("inputs") or {}
    for k in INPUTS_REQUIRED:
        if k not in inp:
            f.append("inputs 缺字段 %s" % k)
    hex64 = re.compile(r"^[0-9a-f]{64}$")
    if not hex64.match(str(inp.get("cards_sha256", ""))):
        f.append("inputs.cards_sha256=%r 不是 64 位十六进制（应为 cards 文件本体哈希）" % inp.get("cards_sha256"))
    if not hex64.match(str(inp.get("source_corpus_sha256", ""))):
        f.append("inputs.source_corpus_sha256=%r 不是 64 位十六进制" % inp.get("source_corpus_sha256"))
    if str(inp.get("cards_sha256", "")) == str(inp.get("source_corpus_sha256", "")) and inp.get("cards_sha256"):
        f.append("inputs.cards_sha256 与 source_corpus_sha256 相同（两类不同对象的哈希被钉成同一个值）")
    if cards_path and os.path.isfile(cards_path):
        import hashlib
        actual = hashlib.sha256(open(cards_path, "rb").read()).hexdigest()
        if inp.get("cards_sha256") != actual:
            f.append("inputs.cards_sha256=%s… ≠ 文件重算 %s…（钉错对象/已漂移）"
                     % (str(inp.get("cards_sha256"))[:12], actual[:12]))
        # 语料哈希：卡内记的是 16 字符前缀（schema-v1.md §5），inputs 记全值 → 前缀对账
        try:
            first = json.loads(open(cards_path, encoding="utf-8").readline())
            inner = str((first.get("source") or {}).get("corpus_sha256") or "")
            if inner and not str(inp.get("source_corpus_sha256", "")).startswith(inner):
                f.append("inputs.source_corpus_sha256=%s… 不以卡内记录前缀 %s… 开头"
                         % (str(inp.get("source_corpus_sha256"))[:12], inner[:12]))
        except (OSError, ValueError, json.JSONDecodeError):
            f.append("读卡文件首行失败，无法对账语料哈希")
        # 语料文件本体在场时重算全值（最强口径）
        corpus_rel = str(inp.get("source_corpus") or "")
        if corpus_rel:
            cand = corpus_rel if os.path.isabs(corpus_rel) else os.path.join(WS, corpus_rel)
            if os.path.isfile(cand):
                import hashlib
                actual_c = hashlib.sha256(open(cand, "rb").read()).hexdigest()
                if inp.get("source_corpus_sha256") != actual_c:
                    f.append("inputs.source_corpus_sha256=%s… ≠ 语料文件重算 %s…"
                             % (str(inp.get("source_corpus_sha256"))[:12], actual_c[:12]))
            else:
                f.append("语料文件不在场，无法重算对账: %s" % cand)
    if candidates_path and os.path.isfile(candidates_path):
        try:
            cl = json.load(open(candidates_path, encoding="utf-8"))
            st = cl.get("stats") or {}
            if int(inp.get("candidates_emitted", -1)) != int(st.get("candidates", -2)):
                f.append("inputs.candidates_emitted=%r ≠ 候选清单 stats.candidates=%r"
                         % (inp.get("candidates_emitted"), st.get("candidates")))
            if int(inp.get("candidates_rejected", -1)) != int(st.get("rejected", -2)):
                f.append("inputs.candidates_rejected=%r ≠ 候选清单 stats.rejected=%r"
                         % (inp.get("candidates_rejected"), st.get("rejected")))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            f.append("读候选清单失败: %s" % exc)
    exps = doc.get("experiments")
    if not isinstance(exps, list) or len(exps) < 2:
        f.append("experiments 须为长度 ≥2 的列表（实得 %r）" % (len(exps) if isinstance(exps, list) else type(exps).__name__,))
        return f
    seen_ids = set()
    for e in exps:
        eid = e.get("exp_id", "<无 exp_id>")
        if eid in seen_ids:
            f.append("%s: exp_id 重复" % eid)
        seen_ids.add(eid)
        for k in EXP_REQUIRED:
            if k not in e:
                f.append("%s: 缺必填字段 %s" % (eid, k))
        # ① 假设可证伪
        h = e.get("hypothesis") or {}
        for k in ("main", "falsifiable_if"):
            if not str(h.get(k, "")).strip():
                f.append("%s: hypothesis.%s 为空（假设必须可证伪）" % (eid, k))
        # ② 断言可回溯
        cid = (e.get("primary_claim") or {}).get("card_id")
        if cid not in card_ids:
            f.append("%s: primary_claim.card_id=%r 不在输入卡集合" % (eid, cid))
        # ③ 臂结构
        arms = e.get("arms") or []
        if len(arms) < 2:
            f.append("%s: 臂数 %d <2（无对照不成实验）" % (eid, len(arms)))
        controls = [a for a in arms if a.get("role") == "control"]
        if len(controls) != 1:
            f.append("%s: control 臂数=%d（要求恰 1）" % (eid, len(controls)))
        for a in arms:
            if not a.get("manipulation"):
                f.append("%s/%s: 缺 manipulation（无法确认单变量）" % (eid, a.get("arm_id")))
            if int(a.get("n_tasks") or 0) <= 0:
                f.append("%s/%s: n_tasks 非正" % (eid, a.get("arm_id")))
        # ④ 随机化
        r = e.get("randomization") or {}
        if not r.get("seed"):
            f.append("%s: randomization 缺 seed（不可复现）" % eid)
        if not r.get("allocation_rule"):
            f.append("%s: randomization 缺 allocation_rule" % eid)
        # ⑤ 样本量
        ss = e.get("sample_size") or {}
        if int(ss.get("tasks") or 0) < 24:
            f.append("%s: tasks=%r <24（配对检验功效不足）" % (eid, ss.get("tasks")))
        if not str(ss.get("power_note", "")).strip():
            f.append("%s: sample_size 缺 power_note（功效声明强制）" % eid)
        # ⑥ 执行通道
        ex = e.get("execution") or {}
        if not str(ex.get("channel", "")).strip():
            f.append("%s: execution.channel 为空" % eid)
        if not (ex.get("judges") or []):
            f.append("%s: execution.judges 为空（判据无可执行判分器）" % eid)
        # ⑦ 指标全部可机判
        ms = e.get("metrics") or []
        if len(ms) < 4:
            f.append("%s: 指标数 %d <4" % (eid, len(ms)))
        for m in ms:
            if m.get("machine_judge") is not True:
                f.append("%s: 指标 %s 非 machine_judge（判据必须可机判）" % (eid, m.get("name")))
            if not str(m.get("definition", "")).strip():
                f.append("%s: 指标 %s 缺 definition" % (eid, m.get("name")))
        if not any(m.get("role") == "primary" for m in ms):
            f.append("%s: 无 primary 指标" % eid)
        # ⑧ 判定规则全部量化 + 钉检验名 + 只引用真实存在的臂
        drs = e.get("decision_rules") or []
        if len(drs) < 4:
            f.append("%s: 判定规则 %d <4（四态结论最小集）" % (eid, len(drs)))
        arm_ids = {a.get("arm_id") for a in arms}
        for d in drs:
            if d.get("quantified") is not True:
                f.append("%s: 判定规则 %s 未标 quantified" % (eid, d.get("verdict")))
            if d.get("verdict") not in VERDICTS:
                f.append("%s: verdict=%r 不在闭集词表" % (eid, d.get("verdict")))
            if not str(d.get("rule", "")).strip():
                f.append("%s: 规则 %s 文本为空" % (eid, d.get("verdict")))
            test = str(d.get("test", "") or "")
            if not any(t in test for t in TESTS):
                f.append("%s: 规则 %s 的 test=%r 未钉检验名（禁「且显著」式默认值）"
                         % (eid, d.get("verdict"), test))
            for aid in (d.get("applies_to_arms") or []):
                if aid not in arm_ids:
                    f.append("%s: 规则 %s 引用不存在的臂 %r（机读不可执行）"
                             % (eid, d.get("verdict"), aid))
            if not (d.get("applies_to_arms") or []):
                f.append("%s: 规则 %s 缺 applies_to_arms（无法机读定位到臂）" % (eid, d.get("verdict")))
        # ⑧b 比率型主指标的操作化口径（二值化/配对集/CI 口径必须钉死，否则 McNemar 判定不可复现）
        op = e.get("metric_operationalization") or {}
        bz = op.get("binarization") or {}
        if bz.get("selected") not in BINARIZATIONS:
            f.append("%s: binarization.selected=%r 不在闭集 %s（比率→二值口径未钉）"
                     % (eid, bz.get("selected"), sorted(BINARIZATIONS)))
        if not str(bz.get("rule", "")).strip():
            f.append("%s: binarization.rule 为空" % eid)
        if not str(op.get("paired_set", "")).strip():
            f.append("%s: metric_operationalization.paired_set 为空（配对集构造未定义）" % eid)
        if not str(op.get("primary_test", "")).strip():
            f.append("%s: metric_operationalization.primary_test 为空" % eid)
        ci = op.get("ci") or {}
        if not str(ci.get("method", "")).strip():
            f.append("%s: ci.method 为空（CI 口径未钉）" % eid)
        try:
            thr = float(ci.get("width_threshold_pp"))
        except (TypeError, ValueError):
            f.append("%s: ci.width_threshold_pp 非数值" % eid)
        else:
            for r in (e.get("decision_rules") or []):
                txt = str(r.get("rule", ""))
                if "CI 宽度" in txt and str(int(thr)) not in txt:
                    f.append("%s: 规则 %s 提 CI 宽度但数值与 ci.width_threshold_pp=%g 不一致"
                             % (eid, r.get("verdict"), thr))
        if not (op.get("sensitivity") or []):
            f.append("%s: metric_operationalization.sensitivity 为空（无稳健性口径）" % eid)
        if not str(op.get("verdict_precedence", "")).strip():
            f.append("%s: verdict_precedence 为空（主判定与敏感性口径的优先级未钉）" % eid)
        for r in (e.get("decision_rules") or []):
            if "McNemar" in str(r.get("test", "")) and bz.get("selected") not in BINARIZATIONS:
                f.append("%s: 规则 %s 用 McNemar 但缺二值化口径" % (eid, r.get("verdict")))
            if "CI" in str(r.get("test", "")) and not str(ci.get("method", "")).strip():
                f.append("%s: 规则 %s 引 CI 但 ci.method 为空" % (eid, r.get("verdict")))
        if not any(m.get("operationalization") for m in (e.get("metrics") or [])
                   if m.get("role") == "primary"):
            f.append("%s: primary 指标缺 operationalization 说明" % eid)
        # ⑧e 判定程序唯一性不变量（第三轮复核「判定程序不唯一可机判」修复轮新增；三条校验路径共用）
        #   E1 verdict_precedence 必须是 decision_rules verdict 的显式全序（排列；可选首个 GATE: 伪项）
        #   E2 TOST 构造钉死：ci.tost 五要素在场、interval ∈ 闭集、margin 与规则文本一致
        #   E3 宽度阈值退出判定路径：规则条件段（首个 → 之前）不得含「宽度」；width_criterion_status 必填
        prec = op.get("verdict_precedence")
        dr_verdicts = [d.get("verdict") for d in drs]
        if not isinstance(prec, list) or not prec:
            f.append("%s: verdict_precedence 不是非空列表（修复轮要求：decision_rules 的显式全序）" % eid)
        else:
            entries = [str(x) for x in prec]
            order = list(entries)
            if order and order[0].startswith("GATE:"):
                if order[0][5:] not in dr_verdicts:
                    f.append("%s: verdict_precedence 的 GATE 伪项指向不存在的 verdict %r"
                             % (eid, order[0][5:]))
                order = order[1:]
            if sorted(map(str, order)) != sorted(map(str, dr_verdicts)):
                f.append("%s: verdict_precedence=%r 不是 decision_rules verdict 集合的排列（全序未钉/缺项/重复）"
                         % (eid, entries))
            if len(set(map(str, order))) != len(order):
                f.append("%s: verdict_precedence 有重复项" % eid)
            if order and order[-1] != "inconclusive":
                f.append("%s: 全序末位必须是兜底 inconclusive（实得 %r）" % (eid, order[-1]))
        tost = ci.get("tost") or {}
        if tost.get("interval") not in TOST_INTERVAL_CLOSED:
            f.append("%s: ci.tost.interval=%r 不在闭集 %s（TOST 区间方法未钉死）"
                     % (eid, tost.get("interval"), sorted(TOST_INTERVAL_CLOSED)))
        for k in ("level", "mapping", "equivalent_iff", "interval_construction", "margin_derivation"):
            if not str(tost.get(k, "")).strip():
                f.append("%s: ci.tost 缺字段 %s（等效域推导未钉死）" % (eid, k))
        try:
            m_pp = float(tost.get("margin_pp"))
        except (TypeError, ValueError):
            f.append("%s: ci.tost.margin_pp 非数值" % eid)
        else:
            for r in drs:
                if r.get("verdict") == "equivalent":
                    mm = re.search(r"±\s*([\d.]+)\s*pp", str(r.get("rule", "")))
                    if not mm:
                        f.append("%s: equivalent 规则文本缺 ±Npp 边际（等效域未钉）" % eid)
                    elif float(mm.group(1)) != m_pp:
                        f.append("%s: equivalent 规则文本边际 ±%spp ≠ ci.tost.margin_pp=%g"
                                 % (eid, mm.group(1), m_pp))
        if not str(ci.get("width_criterion_status", "")).strip():
            f.append("%s: ci.width_criterion_status 为空（宽度阈值是否在判定路径必须显式声明）" % eid)
        for r in drs:
            if "宽度" in str(r.get("rule", "")).split("→")[0]:
                f.append("%s: 规则 %s 的条件段以 CI 宽度作判据（n=24 下退化，修复轮已删除该析取项）"
                         % (eid, r.get("verdict")))
        # ⑧b 样本量与预算算术自洽（防 runs_total≠breakdown 合计、预算漏算重复）
        ss = e.get("sample_size") or {}
        bd = ss.get("runs_breakdown") or {}
        try:
            rt = int(ss.get("runs_total"))
            bsum = int(sum(bd.values()))
        except (TypeError, ValueError):
            f.append("%s: sample_size.runs_total/runs_breakdown 非整数" % eid)
        else:
            if rt != bsum:
                f.append("%s: runs_total=%d ≠ runs_breakdown 合计 %d（%s）"
                         % (eid, rt, bsum, bd))
        b = e.get("budget") or {}
        try:
            units = int(b.get("units"))
            cpu = float(b.get("cents_per_unit"))
            est = float(b.get("usd_estimate"))
            cap = float(b.get("usd_cap"))
        except (TypeError, ValueError):
            f.append("%s: budget.units/cents_per_unit/usd_estimate/usd_cap 非数值" % eid)
        else:
            want = round(units * cpu / 100.0, 2)
            if abs(est - want) > 0.011:
                f.append("%s: usd_estimate=%.2f ≠ units(%d)×cents_per_unit(%s)/100=%.2f"
                         % (eid, est, units, cpu, want))
            if cap > USD_CAP:
                f.append("%s: usd_cap=%.1f > %d（超出数十美分级）" % (eid, cap, USD_CAP))
            if est > cap:
                f.append("%s: usd_estimate=%.1f > usd_cap=%.1f" % (eid, est, cap))
            basis = b.get("cost_basis")
            if basis not in ("per_run", "per_model_call"):
                f.append("%s: budget.cost_basis=%r 不在 {per_run,per_model_call}" % (eid, basis))
            if basis == "per_run" and units != int(ss.get("runs_total") or -1):
                f.append("%s: cost_basis=per_run 但 units(%d) ≠ runs_total(%s)"
                         % (eid, units, ss.get("runs_total")))
            if basis == "per_model_call":
                try:
                    main = int(b.get("model_calls_main"))
                    reps = int(b.get("model_calls_repeats"))
                except (TypeError, ValueError):
                    f.append("%s: per_model_call 预算缺 model_calls_main/model_calls_repeats" % eid)
                else:
                    if units != main + reps:
                        f.append("%s: units(%d) ≠ model_calls_main(%d)+model_calls_repeats(%d)"
                                 % (eid, units, main, reps))
                    has_reps = int(ss.get("repeats_runs") or 0) > 0
                    if has_reps and reps <= 0:
                        f.append("%s: 有强制重复（repeats_runs=%s）但 model_calls_repeats=%d，预算漏算"
                                 % (eid, ss.get("repeats_runs"), reps))
                    if (not has_reps) and reps != 0:
                        f.append("%s: 无强制重复但 model_calls_repeats=%d" % (eid, reps))
        if not str(b.get("basis", "")).strip():
            f.append("%s: budget 缺 basis（估算无出处）" % eid)
        # ⑧c 跨字段一致性：同一对象内的计数/调用数不许互相矛盾
        for key in ("model_calls_total",):
            if key in b and key in ss and int(b[key]) != int(ss[key]):
                f.append("%s: budget.%s=%r ≠ sample_size.%s=%r（同文档两处计数矛盾）"
                         % (eid, key, b[key], key, ss[key]))
        if "model_calls_total" in b and b.get("cost_basis") == "per_model_call" \
                and int(b["model_calls_total"]) != int(b.get("units", -1)):
            f.append("%s: budget.model_calls_total=%r ≠ units=%r（预算算术对不上）"
                     % (eid, b["model_calls_total"], b.get("units")))
        # ⑩ 威胁与缓解
        ths = e.get("threats") or []
        if len(ths) < 5:
            f.append("%s: 威胁条目 %d <5" % (eid, len(ths)))
        for t in ths:
            if not str(t.get("threat", "")).strip() or not str(t.get("mitigation", "")).strip():
                f.append("%s/%s: 威胁缺 threat 或 mitigation" % (eid, t.get("id")))
        # ⑪ 预注册
        p = e.get("preregistration") or {}
        if p.get("locked_before_run") is not True:
            f.append("%s: preregistration.locked_before_run 非 true（先定判据后跑）" % eid)
        if e.get("status") != "designed-not-executed":
            f.append("%s: status=%r（本批只设计不执行）" % (eid, e.get("status")))
    if doc.get("status") != "designed-not-executed":
        f.append("文档 status=%r（本批只设计不执行）" % doc.get("status"))
    return f


def _synth_experiments():
    """构造一份自洽的实验文档（供 --check-experiments 的正/负控自检）。"""
    return {
        "schema_ver": "bline-exp-v1",
        "inputs": {
            "cards": "kb-seed/candidates-batch1/b线-20261028/cards-v1.jsonl",
            "cards_total": 212,
            "cards_sha256": "0" * 64,
            "source_corpus": "harness策略调研/strategies.csv",
            "source_corpus_sha256": "1" * 64,
            "candidate_list": "候选清单-v1.json",
            "candidates_emitted": 66,
            "candidates_rejected": 146,
            "picker": "tools/b-pick-claims.py",
        },
        "experiments": [
            {
                "exp_id": "X1", "title": "t",
                "primary_claim": {"card_id": "S161"},
                "hypothesis": {"main": "m", "falsifiable_if": "f"},
                "arms": [
                    {"arm_id": "c", "role": "control", "manipulation": "none", "n_tasks": 24},
                    {"arm_id": "t", "role": "treatment", "manipulation": "x", "n_tasks": 24},
                ],
                "randomization": {"seed": 1, "allocation_rule": "r", "repeats": "none"},
                "sample_size": {"tasks": 24, "runs_total": 2, "repeats_runs": 0,
                                "runs_breakdown": {"main": 2}, "power_note": "p"},
                "execution": {"channel": "report-unit", "judges": ["citation_unit.py"]},
                "metrics": [
                    {"name": "quote_hit_rate", "definition": "d", "machine_judge": True, "role": "primary",
                     "operationalization": "per-task 比率；进 McNemar 前按 all_hit 二值化"},
                    {"name": "m2", "definition": "d", "machine_judge": True, "role": "gate"},
                    {"name": "m3", "definition": "d", "machine_judge": True, "role": "cost"},
                    {"name": "m4", "definition": "d", "machine_judge": True, "role": "cost"},
                ],
                "metric_operationalization": {
                    "primary_metric": "quote_hit_rate",
                    "binarization": {
                        "closed_vocabulary": {"all_hit": "rate==1.0", "half_hit": "rate>=0.5",
                                              "any_hit": "rate>0"},
                        "selected": "all_hit",
                        "rule": "hit_i = 1 iff rate_i == 1.0",
                    },
                    "paired_set": "两臂都有 report.json 的任务",
                    "primary_test": "McNemar 精确检验（单侧 p<0.05）",
                    "ci": {"quantity": "配对差（百分点）",
                           "method": "按任务聚类 bootstrap 95% percentile",
                           "width_threshold_pp": 8,
                           "width_criterion_status": "宽度阈值已退出判定路径（n=24 下退化）；仅作报告标注口径",
                           "tost": {"interval": "clopper-pearson-conditional",
                                    "level": "90%",
                                    "alpha_per_side": 0.05,
                                    "margin_pp": 5,
                                    "quantity": "不一致对比例 π=b/s",
                                    "interval_construction": "π 的 CP 90% 区间（精确二项尾倒置）",
                                    "mapping": "配对差=(2π−1)·s/n_p",
                                    "margin_derivation": "±5pp 与 confirmed/refuted 阈值同源",
                                    "equivalent_iff": "映射后区间严格含于 (−5pp,+5pp)",
                                    "worked_example_a1b0": "a=1,b=0 → (−3.75pp,+4.17pp) → equivalent"}},
                    "sensitivity": [{"binarization": "half_hit", "role": "敏感性：不改主判定"}],
                    "verdict_precedence": ["GATE:inconclusive", "confirmed", "refuted", "equivalent",
                                           "inconclusive"],
                    "verdict_precedence_note": "显式全序 + 首命中即终判；GATE=数据门；末位 inconclusive 兜底",
                },
                "decision_rules": [
                    {"verdict": "confirmed", "rule": "t−c ≥ +5pp 且 McNemar 精确检验单侧 p<0.05",
                     "test": "McNemar 精确检验（单侧 p<0.05）",
                     "applies_to_arms": ["c", "t"], "quantified": True},
                    {"verdict": "refuted", "rule": "c−t ≥ +5pp 且 McNemar 精确检验单侧 p<0.05",
                     "test": "McNemar 精确检验（单侧 p<0.05）",
                     "applies_to_arms": ["c", "t"], "quantified": True},
                    {"verdict": "equivalent",
                     "rule": "|t−c| < 5pp 且 TOST 等价检验（边际 ±5pp）落在等效域",
                     "test": "TOST 等价检验（边际 ±5pp）",
                     "applies_to_arms": ["c", "t"], "quantified": True},
                    {"verdict": "inconclusive",
                     "rule": "未被以上任一规则命中 → 记未检出（含配对集任务数不足 20 条的数据门与 McNemar 单侧 p ≥ 0.05 的灰区）",
                     "test": "McNemar 精确检验（单侧 p ≥ 0.05 灰区）+ 数据门",
                     "applies_to_arms": ["c", "t"], "quantified": True},
                ],
                "budget": {"cost_basis": "per_run", "units": 2, "cents_per_unit": 3,
                           "usd_estimate": 0.06, "usd_cap": 30, "basis": "b"},
                "duration": {"total_hours": 5},
                "threats": [{"id": "T%d" % i, "threat": "t", "mitigation": "m"} for i in range(1, 6)],
                "preregistration": {"locked_before_run": True},
                "status": "designed-not-executed",
            },
        ],
        "status": "designed-not-executed",
    }


def load_cards(path):
    cards = []
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                cards.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise SystemExit("input %s:%d 不是合法 JSON: %s" % (path, lineno, exc))
    return cards


def _as_int(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _kw_hit(text, kw):
    """关键词命中判定：ASCII 词按**词边界**匹配（防 'CI' 命中 'ACI'、'batch' 命中
    'batches'）；含 CJK 的词按子串匹配（中文无词边界可言）。"""
    if not text or not kw:
        return False
    if kw.isascii():
        return re.search(r"(?<![A-Za-z0-9])%s(?![A-Za-z0-9])" % re.escape(kw), text) is not None
    return kw in text


def gate(card):
    """返回 (passed: bool, reasons: list[str])——硬闸 G1-G5。"""
    body = card.get("body") or {}
    reasons = []
    testability = _as_int(body.get("可测性"))
    if testability is None or testability < 4:
        reasons.append("G1 可测性=%r（要求 ≥4）" % (body.get("可测性"),))
    design = str(body.get("测试设计", "") or "")
    if not design.strip():
        reasons.append("G2 测试设计为空")
    else:
        if not CTRL_RE.search(design):
            reasons.append("G2 测试设计缺对照标记（对照/对照组/A/B/臂/vs/配对）")
        if not METRIC_RE.search(design):
            reasons.append("G2 测试设计缺量化指标标记（率/token/成本/解决/时延/轮次…）")
    if card.get("link_dead") is True:
        reasons.append("G3 link_dead=true（来源链路已死）")
    if str(body.get("链接有效", "")).strip() != "有效":
        reasons.append("G3 链接有效=%r（要求 有效）" % (body.get("链接有效"),))
    if str(body.get("claim一致", "")).strip() != "一致":
        reasons.append("G4 claim一致=%r（要求 一致）" % (body.get("claim一致"),))
    strength = _as_int(body.get("证据强度"))
    grade = str(body.get("等级", "")).strip()
    if not ((strength is not None and strength >= 3) or grade == "A"):
        reasons.append("G5 证据强度=%r 且等级=%r（要求 强度≥3 或 等级=A）" % (body.get("证据强度"), grade))
    return (not reasons), reasons


def classify_channel(card):
    """返回 (channel, hits: dict[channel->[kw]])。

    先匹配主张本身（body.策略），未命中再退到测试设计文本；规则顺序即优先级。
    两条文本分别记录命中词，便于复核员审计「为什么进了这个通道」。
    """
    body = card.get("body") or {}
    claim = str(body.get("策略", "") or "")
    design = str(body.get("测试设计", "") or "")
    for text in (claim, design):
        hits = {}
        for name, keywords in CHANNEL_RULES:
            found = [kw for kw in keywords if _kw_hit(text, kw)]
            if found:
                hits[name] = found
        for name, _ in CHANNEL_RULES:
            if name in hits:
                return name, hits
    return "unclassified", {}


def risks(card, channel):
    body = card.get("body") or {}
    out = []
    for pred, text in RISK_RULES:
        try:
            if pred(card, body):
                out.append(text)
        except Exception:  # 规则自身异常不得中断筛选
            out.append("风险规则异常（已降级登记）")
    out.extend(UNIVERSAL_RISKS)
    if channel == "unclassified":
        out.append("通道未归类：主张与测试设计文本均未命中任何通道关键词，需人工判读后手动指定")
    if channel == "infra":
        out.append("通道=infra：需沙箱/容器/缓存/计费面改动，先做基建单再做效果单")
    if channel == "metrology":
        out.append("通道=metrology：结论形态是『评测口径/统计口径』而非策略效应，A/B 订单只能间接检验")
    return out


def score(card):
    body = card.get("body") or {}
    t = _as_int(body.get("可测性")) or 0
    s = _as_int(body.get("证据强度")) or 0
    w = GRADE_WEIGHT.get(str(body.get("等级", "")).strip(), 0.0)
    ev = str(body.get("证据等级", "") or "")
    ev_bonus = 0.5 if (ev.startswith("benchmark") or ev.startswith("ablation")) else 0.0
    hints = len(card.get("influence_hints") or [])
    pre = len(card.get("preconditions") or [])
    return round(t * s * w + ev_bonus + 0.1 * min(hints, 10) - 0.2 * pre, 4)


#: CLI --exec 取值 → EXEC_MAP 里的执行面名（别名表；any=不过滤）
EXEC_ALIAS = {
    "any": None,
    "report": "report-unit",
    "workflow": "workflow",
    "swev": "swev-unit",
    "graph": "graph-unit",
    "infra": "infra-gap",
}


def pick(cards, exec_filter="any"):
    """筛+排序。exec_filter ∈ {any,report,workflow,swev,graph,infra}（别名见 EXEC_ALIAS）：
    只留能落到该执行面的候选。返回 (candidates, rejected, stats)。"""
    want = EXEC_ALIAS.get(exec_filter, None)
    if exec_filter != "any" and want is None:
        raise ValueError("未知 exec_filter: %r" % exec_filter)
    candidates, rejected = [], []
    for card in cards:
        cid = card.get("candidate_id", "")
        ok, reasons = gate(card)
        if not ok:
            rejected.append({"candidate_id": cid, "reasons": reasons})
            continue
        channel, hits = classify_channel(card)
        execs = list(EXEC_MAP.get(channel, ()))
        if want is not None and want not in execs:
            rejected.append({"candidate_id": cid,
                             "reasons": ["exec-filter=%s：通道 %s 只能落到 %s，本批不走该执行面"
                                         % (exec_filter, channel, execs or ["无"])]})
            continue
        candidates.append({
            "candidate_id": cid,
            "kind": card.get("kind"),
            "text": card.get("text", ""),
            "大类": (card.get("body") or {}).get("大类"),
            "等级": (card.get("body") or {}).get("等级"),
            "可测性": (card.get("body") or {}).get("可测性"),
            "证据强度": (card.get("body") or {}).get("证据强度"),
            "证据等级": (card.get("body") or {}).get("证据等级"),
            "score": score(card),
            "channel": channel,
            "channel_hits": hits,
            "exec_surfaces": execs,
            "测试设计": (card.get("body") or {}).get("测试设计", ""),
            "preconditions": card.get("preconditions") or [],
            "risks": risks(card, channel),
            "source": card.get("source") or {},
        })
    candidates.sort(key=lambda c: (-c["score"], c["candidate_id"]))
    for i, c in enumerate(candidates, 1):
        c["rank"] = i
    stats = {
        "input_total": len(cards),
        "candidates": len(candidates),
        "rejected": len(rejected),
        "exec_filter": exec_filter,
        "by_channel": {ch: sum(1 for c in candidates if c["channel"] == ch) for ch in CHANNELS},
        "by_grade": {g: sum(1 for c in candidates if c["等级"] == g) for g in ("A", "B", "C")},
    }
    return candidates, rejected, stats


def render(candidates, stats):
    lines = [
        "B 线可工厂实测候选清单（筛选器 tools/b-pick-claims.py，规则见模块 docstring）",
        "输入 %(input_total)d 卡 → 过闸 %(candidates)d / 淘汰 %(rejected)d；通道分布 %(by_channel)s" % stats,
        "",
        "%-4s %-8s %-4s %-4s %-5s %-6s %-7s %s" % ("rank", "id", "可测", "强度", "等级", "score", "channel", "断言"),
        "-" * 118,
    ]
    for c in candidates:
        lines.append("%-4d %-8s %-4s %-4s %-5s %-6s %-7s %s" % (
            c["rank"], c["candidate_id"], str(c["可测性"]), str(c["证据强度"]),
            str(c["等级"]), ("%.2f" % c["score"]), c["channel"], c["text"][:56]))
    lines.append("")
    lines.append("不可测风险逐条（前 %d 名）：" % min(len(candidates), 12))
    for c in candidates[:12]:
        lines.append("  %s(%s,ch=%s):" % (c["candidate_id"], c["大类"], c["channel"]))
        for r in c["risks"]:
            lines.append("    - %s" % r)
    return "\n".join(lines)


# ---------------------------------------------------------------- selftest
def _synth(cid, **over):
    """构造一张合规合成卡（字段形状与 kb-v1 strategies 系一致）。"""
    card = {
        "schema_ver": "kb-v1",
        "candidate_id": cid,
        "kind": "claim+procedure",
        "text": "合成卡 " + cid,
        "body": {
            "id": cid, "策略": "合成策略", "大类": "工具与接口", "来源": "synth",
            "链接": "https://example.invalid/x", "承诺改进": "synth", "证据": "synth",
            "证据等级": "benchmark", "链接有效": "有效", "claim一致": "一致",
            "证据强度": "4", "大型仓库价值": "4", "可测性": "5", "等级": "A",
            "验证意见": "synth", "备注": "",
            "测试设计": "对照组=现有 harness；实验组=换工具接口；固定任务集比较 resolved 率与 token 成本",
        },
        "preconditions": [], "influence_hints": ["a", "b"], "relations": [],
        "link_dead": False, "status": "candidate",
        "source": {"corpus": "harness策略调研/strategies.csv", "locator": "line:2", "corpus_sha256": "0" * 64},
        "extractor": {"batch": "synth", "schema_ver": "kb-v1"},
    }
    for k, v in over.items():
        if k in ("preconditions", "influence_hints", "relations", "link_dead", "status"):
            card[k] = v
        else:
            card["body"][k] = v
    return card


def _selftest():
    home = os.path.expanduser("~")
    tmp = tempfile.mkdtemp(prefix="b-pick-claims-selftest-", dir=home)
    checks = []

    def check(name, cond):
        checks.append((name, bool(cond)))

    try:
        # ---- 合成卡行为 ----
        good = _synth("S900")
        ok, reasons = gate(good)
        check("合规合成卡过全闸", ok and not reasons)

        bad = [
            ("可测性=3 被 G1 拦", _synth("S901", 可测性="3")),
            ("测试设计缺对照标记被 G2 拦", _synth("S902", 测试设计="固定任务集比较 resolved 率")),
            ("测试设计缺量化指标被 G2 拦", _synth("S903", 测试设计="对照组=现有；实验组=新工具")),
            ("link_dead 被 G3 拦", _synth("S904", link_dead=True)),
            ("链接有效=无效 被 G3 拦", _synth("S905", 链接有效="无效")),
            ("claim一致=部分一致 被 G4 拦", _synth("S906", claim一致="部分一致")),
            ("强度 2 + 等级 B 被 G5 拦", _synth("S907", 证据强度="2", 等级="B")),
            ("强度 2 + 等级 A 过 G5", _synth("S908", 证据强度="2", 等级="A")),
        ]
        for name, card in bad:
            passed, _ = gate(card)
            expect_pass = name.endswith("过 G5")
            check(name, passed == expect_pass)

        # 通道推断：关键词命中可审计（主张优先，测试设计兜底）
        ch, hits = classify_channel(_synth("S910", 策略="只写负向约束不写正向指令", 测试设计="三组 A/B 比较 pass rate 与 token"))
        check("prompt 通道命中负向/正向关键词", ch == "prompt" and set(hits["prompt"]) >= {"负向", "正向"})
        ch, _ = classify_channel(_synth("S911", 策略="按角色分配不同模型", 测试设计="对照组单模型全角色；实验组分档路由；比较一次通过率与成本"))
        check("model 通道命中模型/角色关键词", ch == "model")
        ch, _ = classify_channel(_synth("S912", 策略="工具接口选型 CLI vs MCP", 测试设计="统计每任务成本与失败成本"))
        check("tool 通道命中工具/接口关键词（主张优先，不被测试设计里的『统计』带跑）", ch == "tool")
        ch, _ = classify_channel(_synth("S913", 策略="并行子代理动态并发策略", 测试设计="同题配对 McNemar 检验 pass rate"))
        check("orch 通道命中并行/子代理关键词", ch == "orch")
        ch, _ = classify_channel(_synth("S913b", 策略="无任何关键词的主张", 测试设计="对照组与实验组比通过率"))
        check("主张未命中时退到测试设计文本", ch == "unclassified")
        ch, _ = classify_channel(_synth("S913c", 策略="无任何关键词的主张", 测试设计="同一批并行子代理任务比较通过率"))
        check("测试设计兜底可命中 orch", ch == "orch")
        ch, _ = classify_channel(_synth("S914", 策略="无任何关键词的策略", 测试设计="对照组与实验组比通过率"))
        check("两处都未命中 → unclassified", ch == "unclassified")

        # 风险规则：基建族 + 前置条件过多 + 轶事证据
        r = risks(_synth("S915", 大类="执行与沙箱"), "infra")
        check("基建族点名基础设施风险", any("基建" in x for x in r))
        r = risks(_synth("S916", preconditions=["p1", "p2", "p3"]), "prompt")
        check("前置条件≥3 触发外推风险", any("前置条件≥3" in x for x in r))
        r = risks(_synth("S917", 证据等级="anecdotal"), "prompt")
        check("轶事证据触发效应量风险", any("anecdotal" in x for x in r))
        r = risks(_synth("S917b", 证据强度="2", 等级="A"), "prompt")
        check("强度<3 但等级 A 放行的卡也标注证据薄风险", any("证据强度<3" in x for x in r))
        r = risks(_synth("S918"), "unclassified")
        check("unclassified 通道点名无通道可落", any("通道未归类" in x for x in r))
        r = risks(_synth("S919"), "prompt")
        check("每条候选都有常驻有效性威胁（≥3 条）", len(r) >= 3)

        # 分数可复算 + 排序确定性
        a = _synth("S920", 可测性="5", 证据强度="5", 等级="A")
        b = _synth("S921", 可测性="4", 证据强度="3", 等级="B", influence_hints=[])
        check("score 与手算一致（5*5*1.0 + 0.5 + 0.1*2 = 25.7）", abs(score(a) - 25.7) < 1e-9)
        check("score 降序：高强度卡高于低强度卡", score(a) > score(b))
        cands, rej, st = pick([a, b, _synth("S922", 可测性="2")])
        check("pick 淘汰可测性 2 的卡", st["rejected"] == 1 and st["candidates"] == 2)
        pa = _synth("S920", 策略="规则极性治理：只写负向约束", 测试设计="三组 A/B 比较 pass rate 与 token")
        pb = _synth("S921", 策略="按角色分配不同模型", 测试设计="对照组单模型全角色；实验组分档路由；比较一次通过率与成本")
        cands, rej, st = pick([pa, pb], exec_filter="report")
        check("--exec report 只留 prompt/model 通道", st["candidates"] == 2
              and {c["channel"] for c in cands} == {"prompt", "model"})
        cands, rej, st = pick([_synth("S912", 策略="工具接口选型 CLI vs MCP",
                                     测试设计="对照组强制 CLI；实验组强制 MCP；比较每任务成本与失败率")],
                              exec_filter="report")
        check("--exec report 把 tool 通道卡挡掉并给理由", st["candidates"] == 0
              and any("exec-filter=report" in r for r in rej[0]["reasons"]))
        cands, rej, st = pick([_synth("S913", 策略="并行子代理动态并发策略",
                                     测试设计="同题配对 McNemar 检验 pass rate")],
                              exec_filter="workflow")
        check("--exec workflow 放行 orch 通道", st["candidates"] == 1 and cands[0]["channel"] == "orch")
        cands, rej, st = pick([a, b])
        check("rank 从 1 起连续且按 score 降序", [c["rank"] for c in cands] == [1, 2] and cands[0]["score"] >= cands[1]["score"])
        cands2, _, st2 = pick([b, a, _synth("S922", 可测性="2")])
        check("输入顺序不影响输出（确定性）", [c["candidate_id"] for c in cands2] == [c["candidate_id"] for c in cands])

        # ---- 真实 212 卡行为 ----
        if os.path.isfile(DEFAULT_CARDS):
            cards = load_cards(DEFAULT_CARDS)
            ids = {c.get("candidate_id") for c in cards}
            by_id = {c.get("candidate_id"): c for c in cards}
            cands, rej, st = pick(cards)
            check("真实输入 212 卡全部读入", st["input_total"] == 212)
            # 复核缺陷A 复现位：S060 的主张含 "ACI"——裸子串会被 metrology 的 "CI" 误吞
            ch, hits = classify_channel(by_id["S060"])
            check("ACI 不被 CI 误命中（词边界匹配）: ch=%s hits=%s" % (ch, hits),
                  ch == "tool" and "metrology" not in hits)
            check("候选清单 ≥8 条（工单判据①）", st["candidates"] >= 8)
            ids = {c.get("candidate_id") for c in cards}
            check("候选 id 全部真实存在于输入", all(c["candidate_id"] in ids for c in cands))
            check("每条候选至少一条不可测风险", all(len(c["risks"]) >= 1 for c in cands))
            check("通道全部落在闭集词表", all(c["channel"] in CHANNELS for c in cands))
            check("排序单调不增", all(cands[i]["score"] >= cands[i + 1]["score"] for i in range(len(cands) - 1)))
            check("排序稳定性（复跑一致）", [c["candidate_id"] for c in pick(cards)[0]] == [c["candidate_id"] for c in cands])
            # 淘汰理由可解释
            check("淘汰项均带理由", all(r["reasons"] for r in rej))

            # --emit 幂等（落 $HOME，不碰只读目录）
            p1 = os.path.join(tmp, "emit-a.json")
            p2 = os.path.join(tmp, "emit-b.json")
            for p in (p1, p2):
                with open(p, "w", encoding="utf-8") as f:
                    json.dump({"stats": st, "candidates": cands, "rejected": rej}, f,
                              ensure_ascii=False, indent=1, sort_keys=True)
            check("--emit 两次输出逐字节一致（幂等）",
                  open(p1, "rb").read() == open(p2, "rb").read())
            # emit 出来的候选 id 与输入对齐（防清单引用不存在的卡）
            emitted = json.load(open(p1, encoding="utf-8"))
            check("emit JSON 可回读且候选 id 对齐",
                  all(c["candidate_id"] in ids for c in emitted["candidates"]))

            # ---- experiments 文档校验：正例 + 负控（变异必须被抓） ----
            good = _synth_experiments()
            good["experiments"].append(json.loads(json.dumps(good["experiments"][0])))
            good["experiments"][1]["exp_id"] = "X2"
            check("自洽实验文档零 findings", check_experiments(good, ids) == [])
            mut = json.loads(json.dumps(good))
            mut["experiments"][0]["budget"]["usd_cap"] = 999
            mut["experiments"][0]["decision_rules"][0]["quantified"] = False
            mut["experiments"][0]["metrics"][1]["machine_judge"] = False
            mut["experiments"][0]["arms"] = [mut["experiments"][0]["arms"][0]]  # 去掉处理臂
            mut["experiments"][0]["primary_claim"]["card_id"] = "S-NOPE"
            mut["experiments"][0]["preregistration"]["locked_before_run"] = False
            findings = check_experiments(mut, ids)
            check("变异实验文档被抓出（预算/非机判/缺臂/假卡 id/未预注册 五类齐）", len(findings) >= 5)
            check("变异里假卡 id 被点名", any("S-NOPE" in x for x in findings))
            # 复核缺陷复现位：三类新变异必须各被抓
            m2 = json.loads(json.dumps(good))
            m2["experiments"][0]["decision_rules"][0]["applies_to_arms"] = ["c", "GHOST"]
            check("决策规则引用不存在的臂 → 被抓", any("GHOST" in x for x in check_experiments(m2, ids)))
            m3 = json.loads(json.dumps(good))
            m3["experiments"][0]["sample_size"]["runs_breakdown"] = {"main": 99}
            check("runs_breakdown 合计 ≠ runs_total → 被抓", any("runs_total" in x for x in check_experiments(m3, ids)))
            m4 = json.loads(json.dumps(good))
            m4["experiments"][0]["budget"]["usd_estimate"] = 99.0
            check("usd_estimate 与 units×单价不符 → 被抓", any("usd_estimate" in x for x in check_experiments(m4, ids)))
            m5 = json.loads(json.dumps(good))
            m5["experiments"][0]["decision_rules"][1]["test"] = "且显著"
            check("判定规则未钉检验名 → 被抓", any("test=" in x for x in check_experiments(m5, ids)))
            m6 = json.loads(json.dumps(good))
            m6["experiments"][0]["sample_size"]["repeats_runs"] = 24
            m6["experiments"][0]["budget"]["cost_basis"] = "per_model_call"
            m6["experiments"][0]["budget"]["units"] = 48
            m6["experiments"][0]["budget"]["model_calls_main"] = 48
            m6["experiments"][0]["budget"]["model_calls_repeats"] = 0
            check("有强制重复但预算漏算重复调用 → 被抓", any("漏算" in x for x in check_experiments(m6, ids)))
            # ---- 第二轮复核返工新增负控 ----
            m7 = json.loads(json.dumps(good))
            m7["experiments"][0]["metric_operationalization"]["binarization"]["selected"] = "median_split"
            m7["experiments"][0]["decision_rules"][3]["rule"] = "CI 宽度 >12pp"
            f7 = check_experiments(m7, ids)
            check("二值化口径越界 + CI 阈值与规则文本不符 → 被抓",
                  any("binarization.selected" in x for x in f7) and any("width_threshold_pp" in x for x in f7))
            m8 = json.loads(json.dumps(good))
            m8["experiments"][0]["metric_operationalization"]["binarization"]["rule"] = ""
            check("二值化规则文本为空 → 被抓", any("binarization.rule" in x for x in check_experiments(m8, ids)))
            m9 = json.loads(json.dumps(good))
            m9["experiments"][0]["budget"]["model_calls_total"] = 999
            m9["experiments"][0]["sample_size"]["model_calls_total"] = 888
            check("budget 与 sample_size 的调用数互相矛盾 → 被抓",
                  any("同文档两处计数矛盾" in x for x in check_experiments(m9, ids)))
            m10 = json.loads(json.dumps(good))
            m10["inputs"]["cards_sha256"] = "e6d8bd8ad13325a2"
            f10 = check_experiments(m10, ids, cards_path=DEFAULT_CARDS)
            check("inputs.cards_sha256 钉成语料哈希/与文件重算不符 → 被抓",
                  any("cards_sha256" in x for x in f10))
            m11 = json.loads(json.dumps(good))
            m11["inputs"]["candidates_emitted"] = 67
            f11 = check_experiments(m11, ids, cards_path=DEFAULT_CARDS,
                                    candidates_path=os.path.join(WS, "计划/研究组/B线核心批-20261029/候选清单-v1.json"))
            check("inputs.candidates_emitted 与候选清单 stats 不符 → 被抓",
                  any("candidates_emitted" in x for x in f11))
            # ---- 第三轮复核（判定程序不唯一可机判）修复轮新增负控 ----
            m12 = json.loads(json.dumps(good))
            m12["experiments"][0]["metric_operationalization"]["verdict_precedence"].remove("equivalent")
            check("verdict_precedence 缺 verdict（全序未钉）→ 被抓",
                  any("verdict_precedence" in x for x in check_experiments(m12, ids)))
            m13 = json.loads(json.dumps(good))
            m13["experiments"][0]["metric_operationalization"]["verdict_precedence"].append("confirmed")
            check("verdict_precedence 重复项 → 被抓",
                  any("verdict_precedence" in x for x in check_experiments(m13, ids)))
            m14 = json.loads(json.dumps(good))
            m14["experiments"][0]["metric_operationalization"]["ci"].pop("tost")
            check("ci.tost 未钉构造 → 被抓",
                  any("ci.tost" in x for x in check_experiments(m14, ids)))
            m15 = json.loads(json.dumps(good))
            m15["experiments"][0]["metric_operationalization"]["ci"]["tost"]["interval"] = "bootstrap-percentile"
            check("ci.tost.interval 不在闭集 → 被抓",
                  any("ci.tost.interval" in x for x in check_experiments(m15, ids)))
            m16 = json.loads(json.dumps(good))
            for r in m16["experiments"][0]["decision_rules"]:
                if r["verdict"] == "inconclusive":
                    r["rule"] = "配对差 CI 宽度 >8pp → 记未检出"
            check("规则条件段以 CI 宽度作判据（退化析取项复活）→ 被抓",
                  any("CI 宽度作判据" in x for x in check_experiments(m16, ids)))
            m17 = json.loads(json.dumps(good))
            m17["experiments"][0]["metric_operationalization"]["ci"]["tost"]["margin_pp"] = 7
            check("规则文本边际与 ci.tost.margin_pp 漂移 → 被抓",
                  any("margin_pp" in x for x in check_experiments(m17, ids)))
            m18 = json.loads(json.dumps(good))
            m18["experiments"][0]["metric_operationalization"]["ci"].pop("width_criterion_status")
            check("ci.width_criterion_status 缺失 → 被抓",
                  any("width_criterion_status" in x for x in check_experiments(m18, ids)))
            # 满分自评卡可刷 rank 1（score 全由卡内自评驱动——「分诊器非裁决器」的边界记录）
            perfect = _synth("S999", 可测性="5", 证据强度="5", 等级="A",
                             influence_hints=["a"] * 10, preconditions=[])
            real_top = max(c["score"] for c in cands)
            check("满分自评合成卡 score=%.2f 超过真实榜首 %.2f（可刷 rank 1，故 score 只能当分诊用）"
                  % (score(perfect), real_top), score(perfect) > real_top)
            # 若真实交付件在场，必须零 findings（ fail-loud ）
            real = os.path.join(WS, "计划/研究组/B线核心批-20261029/experiments-v1.json")
            if os.path.isfile(real):
                doc = json.load(open(real, encoding="utf-8"))
                check("真实 experiments-v1.json 零 findings", check_experiments(doc, ids) == [])
        else:
            check("真实输入在场（%s）" % DEFAULT_CARDS, False)
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    failed = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(("PASS" if ok else "FAIL") + " - " + n)
    if failed:
        print("SELFTEST FAIL (%d/%d failed)" % (len(failed), len(checks)))
        for n in failed:
            print("  FAILED: " + n)
        return 1
    print("SELFTEST PASS (%d/%d)" % (len(checks), len(checks)))
    return 0


def main(argv):
    ap = argparse.ArgumentParser(description="B 线可工厂实测断言筛选器")
    ap.add_argument("--input", default=DEFAULT_CARDS, help="卡文件（jsonl）")
    ap.add_argument("--emit", default=None, help="把候选清单写成 JSON 到该路径")
    ap.add_argument("--top", type=int, default=0, help="只列前 N 条（0=全部）")
    ap.add_argument("--exec", dest="exec_filter", default="any",
                    choices=["any", "report", "workflow", "swev", "graph"],
                    help="只留能落到该执行面的候选（report=report 单；workflow=动态工作流）")
    ap.add_argument("--check-experiments", dest="check_exp", default=None,
                    help="校验 experiments-v1.json 自洽性（零 findings 才 exit 0）")
    ap.add_argument("--selftest", action="store_true", help="自检后退出")
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()

    if not os.path.isfile(args.input):
        print("输入不存在: %s" % args.input, file=sys.stderr)
        return 2

    if args.check_exp:
        if not os.path.isfile(args.check_exp):
            print("实验文档不存在: %s" % args.check_exp, file=sys.stderr)
            return 2
        ids = {c.get("candidate_id") for c in load_cards(args.input)}
        try:
            doc = json.load(open(args.check_exp, encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print("实验文档不是合法 JSON: %s" % exc, file=sys.stderr)
            return 2
        cand_path = os.path.join(WS, "计划/研究组/B线核心批-20261029/候选清单-v1.json")
        findings = check_experiments(doc, ids, cards_path=args.input, candidates_path=cand_path)
        for x in findings:
            print("FINDING: " + x)
        print("check-experiments: %d finding(s)，卡集合 %d 张" % (len(findings), len(ids)))
        return 1 if findings else 0
    cards = load_cards(args.input)
    cands, rej, st = pick(cards, exec_filter=args.exec_filter)
    if args.emit:
        parent = os.path.dirname(os.path.abspath(args.emit))
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        with open(args.emit, "w", encoding="utf-8") as f:
            json.dump({"stats": st, "candidates": cands, "rejected": rej}, f,
                      ensure_ascii=False, indent=1, sort_keys=True)
        print("wrote %s（候选 %d / 淘汰 %d，exec=%s）" % (args.emit, st["candidates"], st["rejected"], st["exec_filter"]))
        return 0
    shown = cands[: args.top] if args.top > 0 else cands
    print(render(shown, st))
    if args.top and args.top < len(cands):
        print("…（仅列前 %d / %d；--top 0 看全部）" % (args.top, len(cands)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
