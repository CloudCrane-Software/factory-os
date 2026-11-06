#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""planner-quality-score.py — 规划质量回评评分器（D-92 · factory-os#25 · advisory 面）。

机制正本：沙箱一等公民体系研究-20261106 Q1 §3.4（卡的回评机制）——
  收卷腿在收卷裁决落定（merge 或 parked/rejected）时跑本评分器：
  六项机检评分 → `planner-quality:` 评论 + quality:A|B|C|D 叠加 label
  → 波次清单/wave-NN.quality.json 追加（append-only 审计面）。
六项评分构成（Q1 §3.4.2，全机器可导，零人评、零模型调用）：
  派发期：六要件机检通过数/6（Q1 §3.1 检查单）；干跑预检 pass 率（Q1 §3.3；
          读既有 step 08b/D-91 证据面，本评分器自身**不执行**任何 acceptance 命令
          ——命令执行面归 step 08b 干跑腿，评分器只读数，advisory 边界）；
  施工期：沙箱异议评论数按类计（/blocked /need-context /need-env；Q1 §四前缀协议）；
  验收期：gates 首过与否、追加 push 轮数（PR commits 数 − 1）、交卷清单未勾项数
          （PR 正文/交卷评论未勾 `- [ ]` 计数）。

三模式：
  replay — 对历史 wave manifest 跑评分 → wave-NN.quality.json 追加（本卡验收①）；
  trial  — 对板面单卡试评（API 实读 issue/PR/comments）→ planner-quality: 评论
           + quality:A|B|C|D 叠加 label（--post 才写板）→ quality 件追加（验收③）；
  selftest — 内嵌夹具自测（零网络零板写；判别力自证）。

advisory 边界（禁项置顶，D7=C-5 禁区铁律）：
  - quality 评级/失败模式**只作 planner 回流输入**：永不改 invalid/valid 机检判定
    （step 08/08b 与其 verdict 落盘件零接触——本文件源代码零引用该件名，
    写入集只有 wave-NN.quality.json，selftest 有写入集断言）、
    永不进 required_status_checks、永不作合线门；
  - wave-NN.quality.json 只追加禁改写（append-only；本评分器只有 open("a") 一条写路径，
    主写路径 --post 板面写只动 issue comment 与 label 两面）；
  - 评分公式落码出处注：grade_formula = af.planner-quality.v1（本文件 grade() 段，
    判据=Q1 §3.4.2 六项构成；A/B/C/D 档界为本器确定性落码，na 项跳过不折算）。
  - S1 供给约束注记（排期补漏员 2026-11-06 补注·查漏清单落档）：本评分器零模型调用
    （纯确定性文本/数字机检）；回评/判分 advisory 面未来若接入模型调用，必须守 S1
    三路一适配器 decide(state, questions[])、短超时 1–2s、429 退避、主→备自动切换、
    三路阈值各自标定禁共用（主=百炼 decision-model-preview，备1=StartLux，
    备1'=TypeSafe 原厂，备2=anolis 2×V100S POC）。
  - token 纪律：--post 板面写凭据只从环境变量 PLANNER_QUALITY_TOKEN 读，
    禁 argv/禁文件/禁打印/禁进日志。

quality 件格式：波次清单/wave-NN.quality.json = JSONL（每行一条独立自描述记录，
  各带 schema=af.wave-quality.v1；追加语义 = 新行尾插，既有行零改写零删除）。
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

TS_FMT = "%Y-%m-%dT%H:%M:%S%z"
TZ8 = timezone(timedelta(hours=8))
SCHEMA = "af.wave-quality.v1"
FORMULA = "af.planner-quality.v1"

# advisory 边界取证常量（验收④）：本评分器全部允许的写入目标形态——
# 只有 wave-NN.quality.json（append）；板面写（comment/label）走 HTTP 不落本仓文件。
WRITE_PATH_RX = re.compile(r"wave-\d+\.quality\.json$")
# invalid 判定面（step 08 verdict 落盘件）——零接触断言用（只在本 selftest 引用文件名
# 作字符串断言，任何模式路径都不得读写该件；advisory 禁项的机器可查形态）。
FORBIDDEN_SURFACE_TOKEN = "manifest" + "-validation.json"

TERMINAL_STATES = {"ledgered", "merged"}

# 六要件机检（Q1 §3.1 检查单）——两种卡面形的确定性映射：
#   board 卡（trial）：检查对象 = issue 正文（§3.1 判据原样适用）；
#   manifest 卡（replay）：卡面字段即 manifest 条目，逐条映射（各带 basis 注）。
FILELINE_RX = re.compile(r"\S+\.\w{1,8}:\d+")
ACC_MARKER_RX = re.compile(r"(→\s*rc\s*=\s*\d+)|(rc\s*=\s*\d+)|(#\s*exit\s*\d+)|(exit\s+\d+)|(退出码)")
ENV_CMD_TOKENS = ("cargo", "docker", "nvidia-smi", "gpu")


def now_ts():
    return datetime.now(TZ8).strftime("%Y-%m-%dT%H:%M:%S%z")


def check_six_board(body):
    """board 卡六要件机检（Q1 §3.1，对 issue 正文）。返回 detail 列表。"""
    detail = []
    # C1 验收命令可执行前提：验收/命令段每条可解析出期望退出码/期望串形态
    acc_lines = [ln for ln in (body or "").splitlines()
                 if re.match(r"^\s*\d+[.、)]\s+", ln.strip())
                 for _ in [0] if any(k in ln for k in ("验收", "rc=", "exit", "命令", "回读", "实测", "核验", "读数"))]
    acc_block = re.search(r"##?\s*验收[^\n]*\n(.*?)(?=\n##? |\Z)", body or "", re.S)
    seg = acc_block.group(1) if acc_block else (body or "")
    items = [ln for ln in seg.splitlines() if re.match(r"^\s*\d+[.、)]\s+", ln)]
    if items:
        bad = [ln.strip()[:60] for ln in items if not ACC_MARKER_RX.search(ln)]
        detail.append({"check": "C1_acceptance_expected_outcome", "pass": not bad,
                       "basis": "Q1 §3.1 #1：每条验收须可解析期望退出码/期望串",
                       "unparsed": bad})
    else:
        detail.append({"check": "C1_acceptance_expected_outcome", "pass": False,
                       "basis": "Q1 §3.1 #1：未检出编号验收条目", "unparsed": []})
    # C2 钉桩基线可取：卡面点名 base SHA/分支钉
    pin = re.search(r"base\s*=\s*(main|[0-9a-f]{6,40})", body or "")
    detail.append({"check": "C2_base_pin_present", "pass": bool(pin),
                   "basis": "Q1 §3.1 #2：卡面带钉桩基线（SHA 或显式 base=分支）",
                   "reading": pin.group(0) if pin else None})
    # C3 证据线索带 file:line
    fl = FILELINE_RX.findall(body or "")
    detail.append({"check": "C3_evidence_fileline", "pass": len(fl) >= 1,
                   "basis": "Q1 §3.1 #3：卡面证据段命中 path:line ≥1", "hits": len(fl)})
    # C4 依赖清单：依赖/边界节非空（显式「不做/不碰/禁」或依赖段）
    dep = re.search(r"(依赖|depends_on)[:：]", body or "")
    bound = re.search(r"(本卡不做|不做|不碰|禁改|边界)", body or "")
    detail.append({"check": "C4_deps_and_boundary", "pass": bool(dep) and bool(bound),
                   "basis": "Q1 §3.1 #4：depends_on 可解析＋「本卡不做什么」节非空",
                   "dep": bool(dep), "boundary": bool(bound)})
    # C5 allowed_paths 白名单纪律：非空且逐条点名
    ap = re.search(r"allowed_paths[:：]\s*([^\n]+)", body or "")
    detail.append({"check": "C5_allowed_paths_nonempty", "pass": bool(ap and ap.group(1).strip()),
                   "basis": "Q1 §3.1 #5：allowed_paths 非空逐条点名（不写泛指）",
                   "reading": ap.group(1).strip()[:80] if ap else None})
    # C6 环境前置段与命令族一致：命令族涉 cargo/docker/gpu 须有环境前置声明
    needs_env = any(t in (body or "") for t in ENV_CMD_TOKENS)
    declares = bool(re.search(r"(环境前置|env_precondition|mem_budget)", body or ""))
    detail.append({"check": "C6_env_precondition_consistent", "pass": (not needs_env) or declares,
                   "basis": "Q1 §3.1 #6：命令族所需环境 ⊆ 卡面环境前置声明",
                   "needs_env": needs_env, "declared": declares})
    return detail


def check_six_manifest(card, manifest, wave_task_ids):
    """manifest 卡六要件机检（Q1 §3.1 对 manifest 卡面字段的确定性映射；
    逐条 basis 注写明映射——replay 只读 manifest 可导证据，不臆造）。"""
    detail = []
    acc = card.get("acceptance") or []
    if acc:
        bad = [str(a)[:60] for a in acc if not ACC_MARKER_RX.search(str(a))]
        detail.append({"check": "C1_acceptance_expected_outcome", "pass": not bad,
                       "basis": "§3.1 #1×manifest 映射：逐条 acceptance 须带期望退出码/期望串（rc=/exit/退出码）",
                       "unparsed": bad})
    else:
        detail.append({"check": "C1_acceptance_expected_outcome", "pass": False,
                       "basis": "§3.1 #1×manifest 映射：卡面 acceptance 字段缺席", "unparsed": []})
    base = (manifest or {}).get("base_sha") or card.get("base_sha")
    detail.append({"check": "C2_base_pin_present", "pass": bool(base),
                   "basis": "§3.1 #2×manifest 映射：manifest/卡面任一级带钉桩基线",
                   "reading": base})
    text = " ".join(str(card.get(k) or "") for k in ("title", "acceptance", "ledger", "note", "preflight_note"))
    text += " " + json.dumps(card.get("ledger") or "", ensure_ascii=False)
    fl = FILELINE_RX.findall(text)
    detail.append({"check": "C3_evidence_fileline", "pass": len(fl) >= 1,
                   "basis": "§3.1 #3×manifest 映射：卡面证据字段命中 path:line ≥1", "hits": len(fl)})
    dangling = [d for d in (card.get("depends_on") or [])
                if not any(d and (d in wave_task_ids) for _ in [0])]
    mp = bool(str(card.get("merge_policy") or "").strip())
    detail.append({"check": "C4_deps_and_boundary", "pass": (not dangling) and mp,
                   "basis": "§3.1 #4×manifest 映射：depends_on 波内可解析（空=通过）＋merge_policy 非空（收卷边界）",
                   "dangling": dangling, "merge_policy_present": mp})
    ap = card.get("allowed_paths") or []
    detail.append({"check": "C5_allowed_paths_nonempty", "pass": bool(ap),
                   "basis": "§3.1 #5×manifest 映射：allowed_paths 非空数组",
                   "count": len(ap)})
    acc_text = json.dumps(acc, ensure_ascii=False)
    needs_env = any(t in acc_text for t in ENV_CMD_TOKENS)
    declares = bool(str(card.get("env_precondition") or "").strip())
    detail.append({"check": "C6_env_precondition_consistent", "pass": (not needs_env) or declares,
                   "basis": "§3.1 #6×manifest 映射：acceptance 命令族涉 cargo/docker/gpu 须带 env_precondition（v1.1）",
                   "needs_env": needs_env, "declared": declares})
    return detail


def grade(six_pass, gates_final_green, objections, unchecked, push_rounds, dry_rate):
    """评分公式 af.planner-quality.v1（确定性落码；出处注：构成=Q1 §3.4.2 六项；
    档界语义：D=真红/诚实缺口（收卷门未绿、交卷未勾、异议高频、六要件大面积缺）；
    C=过程成本显性（追加推送/异议/缺项）；B=全绿低成本（na 项跳过不折算——
    na 不得换 A）；A=全绿零成本且六项全可证（零 na）。na 政策：na 项只放行
    更低档位，禁止把「无证据」当「已达标」换 A。gates_ok 取收卷终态
    （final_green）——首过与否经 push_rounds 计成本，首推红而收卷绿属 C/B
    过程成本，不判 D（真红停车语义只落在收卷未绿）。"""
    # D 档（任一即 D）
    if gates_final_green is False:
        return "D", "gates 收卷未绿（真红）"
    if (unchecked is not None and unchecked > 0):
        return "D", "交卷清单未勾项>0（诚实性缺口）"
    if (objections is not None and objections >= 3):
        return "D", "异议评论≥3（高频受阻）"
    if (six_pass is not None and six_pass <= 3):
        return "D", "六要件机检≤3/6（卡面自包含大面积缺）"
    # C 档（任一即 C）
    if (objections is not None and objections >= 1):
        return "C", "异议评论 1-2（施工期受阻留痕）"
    if (six_pass is not None and six_pass <= 5):
        return "C", "六要件机检 4-5/6"
    if (push_rounds is not None and push_rounds >= 3):
        return "C", "追加 push≥3 轮"
    if (dry_rate is not None and dry_rate < 1.0):
        return "C", "干跑 pass 率<1.0"
    # A/B 分界：A 需六项全可证且零成本（na 不得换 A）
    if (push_rounds == 0 and dry_rate == 1.0
            and push_rounds is not None and dry_rate is not None):
        return "A", "全绿零成本：gates 首过+零异议+零未勾+单推+干跑 100%"
    return "B", "全绿低成本（na 项存在或追加 push≤2——na 不折 A）"


MODE_LABEL_RX = {
    "/blocked": re.compile(r"^\s*/blocked\b"),
    "/need-context": re.compile(r"^\s*/need-context\b"),
    "/need-env": re.compile(r"^\s*/need-env\b"),
}
FAILURE_MODE_BY_CHECK = {
    "C1_acceptance_expected_outcome": "acceptance 缺期望退出码/期望串形制",
    "C2_base_pin_present": "卡面无钉桩基线",
    "C3_evidence_fileline": "卡面无 file:line 证据锚",
    "C4_deps_and_boundary": "depends_on 悬引用/收卷边界缺",
    "C5_allowed_paths_nonempty": "allowed_paths 缺席",
    "C6_env_precondition_consistent": "环境前置声明缺（命令族需 cargo/docker）",
}


def build_record(wave, mode, card_ref, scored, six_detail, gates, push, objections,
                 unchecked, dry_rate, evidence, scored_reason=None):
    """组装一条 quality 记录（键集固定完整——scored:false 行同键集，grade=null）。
    评分面读数取值纪律：na 段不计入公式（None 传入），非 na 段取 value。"""
    six_pass = sum(1 for d in six_detail if d.get("pass")) if six_detail else 0
    failure_modes = []
    for d in six_detail or []:
        if not d.get("pass"):
            m = FAILURE_MODE_BY_CHECK.get(d.get("check"))
            if m and m not in failure_modes:
                failure_modes.append(m)
    gates_rec = gates if isinstance(gates, dict) else {
        "first_pass": {"value": None, "na": True, "reason": "无 PR 面"},
        "final_green": {"value": None, "na": True, "reason": "无收卷门证据"}}
    fg = gates_rec.get("final_green") or {}
    fp = gates_rec.get("first_pass") or {}
    push_rec = push if isinstance(push, dict) else {"value": None, "na": True, "reason": "无 PR 面不可导"}
    obj_rec = objections if isinstance(objections, dict) else {"value": 0, "na": False, "basis": str(objections)}
    unc_rec = unchecked if isinstance(unchecked, dict) else {"value": None, "na": True, "reason": "无交卷清单面"}
    dry_rec = dry_rate if isinstance(dry_rate, dict) else {"value": None, "na": True, "reason": "未提供干跑证据面"}

    if fg.get("value") is False:
        failure_modes.append("gates 收卷未绿")
    if push_rec.get("value") is not None and push_rec["value"] >= 3:
        failure_modes.append("追加 push≥3 轮")
    for k, v in (obj_rec.get("by_kind") or {}).items():
        if v:
            failure_modes.append("异议:%s×%d" % (k, v))
    if unc_rec.get("value"):
        failure_modes.append("交卷清单未勾×%d" % unc_rec["value"])

    if not scored:
        g, basis = None, None
    else:
        # gates_ok = 收卷终态（final_green 非 na 取 value，na=None 跳过该判据）
        gates_ok = fg.get("value") if not fg.get("na", True) else None
        g, basis = grade(
            six_pass, gates_ok,
            None if obj_rec.get("na") else obj_rec.get("value"),
            None if unc_rec.get("na") else unc_rec.get("value"),
            None if push_rec.get("na") else push_rec.get("value"),
            None if dry_rec.get("na") else dry_rec.get("value"))
    rec = {
        "schema": SCHEMA,
        "record_type": "card_quality",
        "ts": now_ts(),
        "wave": wave,
        "mode": mode,
        "card": card_ref,
        "scored": bool(scored),
        "grade": g,
        "items": {
            "six_essential": {"pass": six_pass, "total": 6, "detail": six_detail or []},
            "dry_run_pass_rate": dry_rec,
            "objection_comments": obj_rec,
            "gates": gates_rec,
            "push_rounds": push_rec,
            "submission_unchecked": unc_rec,
        },
        "failure_modes": failure_modes,
        "grade_formula": FORMULA,
        "grade_basis": (None if not scored else "%s（%s）" % (g, basis)),
        "scored_reason": None if scored else scored_reason,
        "evidence": evidence or {},
        "advisory": {
            "gate_exempt": True,
            "note": "quality 只作 planner 回流输入（advisory）：永不改 invalid/valid 机检判定面，"
                    "永不进 required checks，永不作合线门（D7=C-5 禁区）；"
                    "本评分器零模型调用，未来扩面接模型须守 S1 三路一适配器约束。",
        },
        "writes": ["wave-%s.quality.json" % wave.split("-")[-1].zfill(2)],
    }
    return rec


def append_quality(wave_dir, wave, records):
    """append-only 落盘：wave-NN.quality.json 行尾追加（既有行零改写零删除）。"""
    os.makedirs(wave_dir, exist_ok=True)
    path = os.path.join(wave_dir, "wave-%s.quality.json" % wave.split("-")[-1].zfill(2))
    existed = os.path.exists(path)
    size_before = os.path.getsize(path) if existed else 0
    with open(path, "a", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    assert WRITE_PATH_RX.search(path), "写入集越界：%s" % path
    return path, existed, size_before


# ─────────────────────────── replay 模式 ───────────────────────────

def mode_replay(manifest_path, wave_dir):
    man = json.load(open(manifest_path, encoding="utf-8"))
    wave = man.get("wave") or "wave-00"
    wave_task_ids = {c.get("task_id") for c in (man.get("cards") or []) if isinstance(c, dict)}
    records = []
    for c in man.get("cards") or []:
        if not isinstance(c, dict):
            continue
        state = c.get("state")
        closed = state in TERMINAL_STATES
        six_detail = check_six_manifest(c, man, wave_task_ids)
        if not closed:
            records.append(build_record(
                wave, "replay",
                {"task_id": c.get("task_id"), "debt": c.get("debt"), "channel": c.get("channel"),
                 "issue": None, "pr": None, "state_at_score": state},
                scored=False, six_detail=six_detail, gates=None, push=None,
                objections={"value": 0, "na": False, "basis": "无板面 issue 通道，异议面结构性零"},
                unchecked=None, dry_rate={"value": None, "na": True, "reason": "未收卷卡无干跑证据面"},
                evidence={"manifest": os.path.basename(manifest_path)},
                scored_reason="未收卷（state=%s）——评分事件在收卷裁决落定时（Q1 §3.4.1）" % state))
            continue
        merge_text = json.dumps({"m": c.get("merge_result"), "l": c.get("ledger_result"),
                                 "a": c.get("accept_note")}, ensure_ascii=False)
        final_green = ("门绿" in merge_text) or ("全绿" in merge_text) or ("rc=0" in merge_text)
        gates = {
            "first_pass": {"value": None, "na": True,
                           "reason": "收卷文本只证终绿，首过性不可导（首过=首推 commit gates 绿，须 PR 面实读）"},
            "final_green": {"value": bool(final_green), "na": False,
                            "basis": ("收卷文本命中门绿证据：%s" % (
                                (c.get("merge_result") or c.get("ledger_result") or "")[:80]))
                            if final_green else "收卷文本无门绿证据（merge_result/ledger_result 均缺）"},
        }
        unchecked = {"value": 0, "na": False,
                     "basis": "收卷闭环（state=%s，收卷裁决落定=交卷清单闭环）" % state}
        push = {"value": None, "na": True, "reason": "manifest 收卷文本不可导追加轮数（须 PR commits 实读）"}
        dry = {"value": None, "na": True,
               "reason": "pre-D-91 波次无 step 08b 干跑证据（wave manifest 收卷面无 dry_run 段）"}
        records.append(build_record(
            wave, "replay",
            {"task_id": c.get("task_id"), "debt": c.get("debt"), "channel": c.get("channel"),
             "issue": c.get("issue"), "pr": None, "state_at_score": state},
            scored=True, six_detail=six_detail, gates=gates, push=push,
            objections={"value": 0, "na": False, "basis": "无板面 issue 通道（workspace 卡），异议面结构性零"},
            unchecked=unchecked, dry_rate=dry,
            evidence={"manifest": os.path.basename(manifest_path),
                      "fields": [k for k in ("merge_result", "ledger_result", "accept_note") if c.get(k)]}))
    path, existed, size_before = append_quality(wave_dir, wave, records)
    scored_n = sum(1 for r in records if r["scored"])
    print("REPLAY %s：%d 卡（评分 %d / 未收卷留证 %d）→ %s 追加 %d 行（append-only，%s）"
          % (wave, len(records), scored_n, len(records) - scored_n, path, len(records),
             "新建" if not existed else "既有 %d 字节上追加" % size_before))
    return path, records


# ─────────────────────────── trial 模式 ───────────────────────────

def gh_api(path, token, method="GET", payload=None, attempts=5):
    """api.github.com 实读/写（5 次重试+递增退避——直连抖动不静默降级证据面；
    429/5xx/传输层残读均重试，4xx 语义错不重试直接抛）。"""
    import time
    import urllib.request
    import urllib.error
    last = None
    for i in range(attempts):
        req = urllib.request.Request("https://api.github.com" + path, method=method,
                                     headers={"Authorization": "Bearer " + token,
                                              "Accept": "application/vnd.github+json",
                                              "X-GitHub-Api-Version": "2022-11-28"},
                                     data=json.dumps(payload).encode() if payload else None)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code < 500 and e.code != 429:
                raise
            last = e
        except Exception as e:   # 传输层残读/超时（直连抖动窗）
            last = e
        time.sleep(3 * (i + 1))
    raise last


def mode_trial(repo, issue_no, wave, wave_dir, token, post):
    issue = gh_api("/repos/%s/issues/%d" % (repo, issue_no), token)
    body = issue.get("body") or ""
    labels = [l["name"] for l in issue.get("labels") or []]
    comments = gh_api("/repos/%s/issues/%d/comments?per_page=100" % (repo, issue_no), token)
    by_kind = {}
    for cm in comments:
        for kind, rx in MODE_LABEL_RX.items():
            if rx.search(cm.get("body") or ""):
                by_kind[kind] = by_kind.get(kind, 0) + 1
    objections = {"value": sum(by_kind.values()), "na": False,
                  "basis": "API 实读 issue comments ×%d，四前缀异议协议计数（/progress 不属异议）" % len(comments),
                  "by_kind": by_kind}
    # PR 探测：卡号在 PR 正文/标题被点名（「Closes #N」与「卡面：factory-os#N」两形
    # 同覆盖——token 匹配 #N 词边界；merged 优先，创建序取最早；可用
    # PLANNER_QUALITY_PR 显式覆盖）。探测失败=停车（禁降级证据面落盘/落板——
    # gates/push 读数缺失的评分记录不诚实，宁停不降）。
    pr_no = None
    try:
        pulls = gh_api("/repos/%s/pulls?state=all&per_page=100&sort=created&direction=asc" % repo, token)
        pat = re.compile(r"#%d(?!\d)" % issue_no)
        cands = [p for p in pulls
                 if pat.search(((p.get("body") or "") + " " + (p.get("title") or "")))]
        if cands:
            merged_c = [p for p in cands if p.get("merged_at")]
            pr_no = (merged_c or cands)[0]["number"]
    except Exception as e:
        print("PR 探测实读失败（%s:%s）——trial 停车，不落降级记录" % (type(e).__name__, e), file=sys.stderr)
        raise
    pr_no = int(os.environ.get("PLANNER_QUALITY_PR") or 0) or pr_no
    push = {"value": None, "na": True, "reason": "无关联 PR"}
    gates = {"first_pass": {"value": None, "na": True, "reason": "无关联 PR（无首推 gates 面）"},
             "final_green": {"value": None, "na": True, "reason": "无关联 PR（无收卷门证据）"}}
    unchecked = {"value": 0, "na": False, "basis": "PR 正文/交卷面未勾 `- [ ]` 计数（无 PR=0）"}
    if pr_no:
        pr = gh_api("/repos/%s/pulls/%d" % (repo, pr_no), token)
        commits = gh_api("/repos/%s/pulls/%d/commits?per_page=100" % (repo, pr_no), token)
        push = {"value": max(0, len(commits) - 1), "na": False,
                "basis": "PR #%d commits=%d（追加轮=commits−1，Q1 §3.4.2 验收期口径）" % (pr_no, len(commits))}
        first_sha = commits[0]["sha"] if commits else None
        first_green = None
        if first_sha:
            cr = gh_api("/repos/%s/commits/%s/check-runs?per_page=100" % (repo, first_sha), token)
            for run in cr.get("check_runs") or []:
                if run.get("name") == "gates":
                    first_green = (run.get("conclusion") == "success")
                    break
        merged = bool(pr.get("merged_at"))
        gates = {
            "first_pass": {"value": first_green, "na": first_green is None,
                           "reason": None if first_green is not None else "首推 commit 无 gates check-run",
                           "basis": "首推 commit %s 的 gates check-run API 实读" % (first_sha[:12] if first_sha else "?")},
            "final_green": {"value": merged, "na": False, "basis": "PR #%d merged=%s（合线=收卷门终绿）" % (pr_no, merged)},
        }
        pr_body = pr.get("body") or ""
        unchecked = {"value": pr_body.count("- [ ]") + sum(
            (cm.get("body") or "").count("- [ ]") for cm in comments if "交卷" in (cm.get("body") or "")),
            "na": False, "basis": "PR #%d 正文＋交卷评论 `- [ ]` 未勾计数" % pr_no}
    six_detail = check_six_board(body)
    dry = {"value": None, "na": True,
           "reason": "评分器不执行命令（执行面归 step 08b/D-91）；本卡收卷面无干跑读数证据"}
    task_m = re.search(r"task_id:\s*`([a-z0-9][a-z0-9._-]{2,63})`", body)
    debt_m = re.search(r"债号[^:：]*[:：]\s*\*?\*?([A-Za-z]{1,5}-[A-Za-z0-9-]+)", body)
    rec = build_record(
        wave, "trial",
        {"task_id": task_m.group(1) if task_m else None, "debt": debt_m.group(1) if debt_m else None,
         "channel": ("bot-lane" if "bot-lane" in body else "?"), "issue": issue_no, "pr": pr_no,
         "state_at_score": issue.get("state")},
        scored=True, six_detail=six_detail, gates=gates, push=push,
        objections=objections, unchecked=unchecked, dry_rate=dry,
        evidence={"repo": repo, "issue": issue_no, "pr": pr_no,
                  "api_reads": ["/issues/%d" % issue_no,
                                "/issues/%d/comments" % issue_no,
                                "/pulls?state=all（卡号点名探测）"] + (["/pulls/%d" % pr_no,
                                "/pulls/%d/commits" % pr_no,
                                "/commits/{首推}/check-runs"] if pr_no else []),
                  "board_labels_at_read": labels})
    path, existed, size_before = append_quality(wave_dir, wave, [rec])
    print("TRIAL issue #%d → grade=%s（%s）→ %s 追加 1 行（append-only，%s）"
          % (issue_no, rec["grade"], rec["grade_basis"], path,
             "新建" if not existed else "既有 %d 字节上追加" % size_before))
    if post:
        tok_guard = token
        assert tok_guard and not tok_guard.startswith("argv"), "token 须走环境变量"
        def _disp(seg):
            return "na" if (seg.get("na") or seg.get("value") is None) else seg["value"]
        grade = rec["grade"]
        lines = ["planner-quality: **%s** 档（%s 评分 · advisory 观测面，非门）" % (grade, FORMULA)]
        lines.append("")
        lines.append("- 六要件机检：%d/6（%s）" % (
            rec["items"]["six_essential"]["pass"],
            "；".join("%s=%s" % (d["check"], "pass" if d["pass"] else "FAIL") for d in six_detail)))
        gates_rec = rec["items"]["gates"]
        lines.append("- gates：首过=%s · 终绿=%s" % (_disp(gates_rec["first_pass"]),
                                                   _disp(gates_rec["final_green"])))
        lines.append("- 追加 push：%s ｜ 异议评论：%s ｜ 交卷未勾：%s ｜ 干跑：%s" % (
            "na" if rec["items"]["push_rounds"].get("na") else rec["items"]["push_rounds"]["value"],
            rec["items"]["objection_comments"]["value"],
            rec["items"]["submission_unchecked"]["value"],
            "na（评分器不执行命令）" if rec["items"]["dry_run_pass_rate"].get("na") else rec["items"]["dry_run_pass_rate"]["value"]))
        if rec["failure_modes"]:
            lines.append("- 失败模式：%s" % "；".join(rec["failure_modes"]))
        lines.append("")
        lines.append("依据件：波次清单/wave-%s.quality.json（append-only）｜ 判据：沙箱研究 Q1 §3.4"
                     "（六项构成全机器可导）｜ 边界：quality 评级只作 planner 回流输入——永不改"
                     " invalid/valid 机检判定、永不进 required checks（D7=C-5 禁区）。" % wave.split("-")[-1].zfill(2))
        gh_api("/repos/%s/issues/%d/comments" % (repo, issue_no), token, method="POST",
               payload={"body": "\n".join(lines)})
        # 叠加 label：先摘既有 quality:*（叠加位语义：同时至多一档），再挂新档
        for l in labels:
            if l.startswith("quality:"):
                gh_api("/repos/%s/issues/%d/labels/%s" % (repo, issue_no, l), token, method="DELETE")
        gh_api("/repos/%s/issues/%d/labels" % (repo, issue_no), token, method="POST",
               payload={"labels": ["quality:%s" % grade]})
        print("POSTED：planner-quality: 评论 + quality:%s label → issue #%d" % (grade, issue_no))
    return rec


# ─────────────────────────── selftest ───────────────────────────

def mode_selftest():
    """内嵌夹具自测（零网络、零板写；判别力自证 + advisory 写入集断言）。"""
    mk = lambda wave, cards: {"schema": "af.wave-manifest.v1", "wave": wave, "cards": cards}
    # 夹具 1：六要件全过卡 → A 档全可证形态（push=0 dry=1.0）
    good = {"task_id": "t-good", "debt": "D-1", "channel": "local-api", "state": "merged",
            "acceptance": ["python3 -I tools/x.py → rc=0"], "allowed_paths": ["tools/x.py"],
            "merge_policy": "单件直推", "ledger": "台账 D-1 行（tools/x.py:12 读数）",
            "merge_result": "合线；全量门绿"}
    man1 = mk("wave-01", [good])
    man1["base_sha"] = "a" * 40
    # 直接调内部纯函数（零文件面）：先验 check/grade
    d1 = check_six_manifest(good, man1, {"t-good"})
    p1 = sum(1 for x in d1 if x["pass"])
    assert p1 == 6, "夹具1 六要件应 6/6，实得 %d：%s" % (p1, d1)
    g1, b1 = grade(6, True, 0, 0, 0, 1.0)
    assert g1 == "A", "夹具1 应 A，实得 %s（%s）" % (g1, b1)
    # 夹具 2：acceptance 缺期望形制 + 证据无 file:line → 6 缺 2 → C
    mid = dict(good, acceptance=["py_compile"], title="某修复", ledger="台账 D-1 行")
    d2 = check_six_manifest(mid, man1, {"t-good"})
    p2 = sum(1 for x in d2 if x["pass"])
    assert p2 == 4, "夹具2 六要件应 4/6，实得 %d" % p2
    g2, _ = grade(p2, True, 0, 0, None, None)
    assert g2 == "C", "夹具2 应 C，实得 %s" % g2
    # 夹具 3：门未绿（真红）→ D（真实门红停车不弱化——评分面如实 D，且永不为门）
    g3, _ = grade(6, False, 0, 0, None, None)
    assert g3 == "D", "夹具3 应 D，实得 %s" % g3
    # 夹具 4：交卷未勾 → D
    g4, _ = grade(6, True, 0, 2, None, None)
    assert g4 == "D"
    # 夹具 5：异议≥3 → D；1-2 → C
    assert grade(6, True, 3, 0, None, None)[0] == "D"
    assert grade(6, True, 2, 0, None, None)[0] == "C"
    # 夹具 6：na 不得换 A（na push/na dry → 顶 B）
    g6, _ = grade(6, True, 0, 0, None, None)
    assert g6 == "B", "na 不得换 A：实得 %s" % g6
    # 夹具 7：追加 push 3 → C；1 → B
    assert grade(6, True, 0, 0, 3, None)[0] == "C"
    assert grade(6, True, 0, 0, 1, 1.0)[0] == "B"
    # 夹具 8（advisory 写入集断言）：写入路径正则只认 wave-NN.quality.json；
    # invalid 判定面件名经常量拼接构造（源码零字面量，夹具 9 才可全量取证）
    assert WRITE_PATH_RX.search("波次清单/wave-01.quality.json")
    assert not WRITE_PATH_RX.search(FORBIDDEN_SURFACE_TOKEN)
    assert not WRITE_PATH_RX.search("planner-inputs.json")
    # 夹具 9：源代码零引用 invalid 判定面件名（advisory 边界取证——常量行用拼接避开
    # 字面量，故任何真读写该件的代码行都会被本断言点名；断言行自身不含字面量）
    src = open(os.path.abspath(__file__), encoding="utf-8").read()
    hits = [i + 1 for i, ln in enumerate(src.splitlines())
            if FORBIDDEN_SURFACE_TOKEN in ln and "FORBIDDEN_SURFACE_TOKEN" not in ln]
    assert not hits, "评分器源码出现 invalid 判定面件名字面量引用（行 %s）——advisory 边界违约" % hits
    # 夹具 10：board 卡 C1 对回读形卡面（编号条目缺 rc 形 → fail）
    body_c1 = "## 验收命令集\n1. 三态夹具各一实测（回读）。\n"
    d10 = check_six_board(body_c1)
    c1 = [x for x in d10 if x["check"] == "C1_acceptance_expected_outcome"][0]
    assert c1["pass"] is False, "回读形无 rc 应 fail"
    print("SELFTEST OK：10 组夹具全过（六要件机检/评分档界/na 政策/advisory 写入集断言）")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="D-92 规划质量回评评分器（advisory 面）")
    ap.add_argument("mode", choices=["replay", "trial", "selftest"])
    ap.add_argument("--manifest", help="replay：wave-NN.json 路径")
    ap.add_argument("--wave-dir", default=os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "波次清单"))
    ap.add_argument("--repo", default="CloudCrane-Software/factory-os", help="trial：板面仓")
    ap.add_argument("--issue", type=int, help="trial：卡 issue 号")
    ap.add_argument("--wave", help="trial：卡所属波次（如 wave-06）")
    ap.add_argument("--post", action="store_true", help="trial：真写板（评论+label）；缺省只算分落盘")
    args = ap.parse_args(argv)
    if args.mode == "selftest":
        return mode_selftest()
    if args.mode == "replay":
        if not args.manifest:
            ap.error("replay 需 --manifest")
        mode_replay(args.manifest, args.wave_dir)
        return 0
    if args.mode == "trial":
        if not (args.issue and args.wave):
            ap.error("trial 需 --issue N --wave wave-NN")
        token = os.environ.get("PLANNER_QUALITY_TOKEN") or ""
        if not token:
            print("trial 需环境变量 PLANNER_QUALITY_TOKEN（API 实读+--post 板面写同源；"
                  "禁 argv/禁文件/禁打印）", file=sys.stderr)
            return 3
        rec = mode_trial(args.repo, args.issue, args.wave, args.wave_dir, token, args.post)
        if not args.post:
            print("（--post 未给：只算分+落盘，板面零写）")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
