#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cb-bench-dispatch.py — bench 卡型卡面转发段 → CNB @CodeBuddy 派发封装件（D-130 · factory-os#145）。

定位（夜轨A2 建议 S1）：把 D-117 实证可行的 cnb 评论派发（cb-npc-poc#58 全环
43m25s、人工现身 0 次）固化为可复用 CLI——派发从「运营者人工逐条转述」变为
「一个 CLI 渲染载荷 + 落地侧按计划执行并留痕」。

链路：读卡面转发段文件（--body-file，bench 卡型禁项置顶+自包含范式）→ 解析
债号/task_id/依赖（af-card/1.0 机读块优先，回落【债号】/task_id 双形制；认不出
如实 None，禁猜）→ 渲染 CNB 派发载荷：
    cnb_issue_title = 标题带债号（[<debt>] <标题核心段>）
    cnb_issue_body  = 转发段整段（自包含卡面——沙箱读得到任务本体）
    cnb_comment     = 首词 @CodeBuddy + 转发段整段 + 派发契约段
                      （work_mode 语义/径 B 产出取回/卡面即边界/触发契约三件套）
    work_mode       = True（API 字段；不开则只读+评论，开了才写代码/推分支）
→ 真派发落派发留痕件（issue 号+评论 id+UTC 时间戳+sha256[:12] 指纹链）。

失败腿（D-134 · factory-os#149）：派发器失败路径诚实闭环——四形制（沙箱未复现/
部分交卷/verdict=not_resolved/超静默窗零 diff 块未交卷）各自走完「收卷核+判分+
回卡」三段并落留痕件（形制+读数+指纹链），判词如实、禁人工抢救判分、禁放宽
判据迁就失败；入口 --failure-form（计划态，零 POST），夹具 tools/fixtures/
cb-bench-dispatch/failpaths/（四形制各一）。派发主路径零改动（P5）。

模式：
  --plan（默认；零 POST 干跑）  渲染全部载荷+前置闸清单，写 dispatch-plan.ndjson
                                + dispatch-plan-summary.md；不发任何 POST。
  --execute（本版恒拒 exit 3）  真执行腿四门未齐（占用闸/审卡闸/CNB token 经
                                openBao 现取纪律就绪/运营者授权环境量）——照
                                tools/cnb-card-dispatch.py:258 同款 fail-closed
                                形制：恒拒发+拒发记录落档+零 POST。真派发由落地侧
                                按 --plan 产物执行（D-130 验收命令集第 7 条）。
  --failure-form <四形制之一>   失败腿计划态（D-134）：沙箱未复现/部分交卷/
                                verdict=not_resolved/超静默窗未交卷 ⇒ 链路照走完
                                （收卷核+判分+回卡如实判）+ 留痕件（形制+读数+
                                指纹链），判词如实零人工抢救；必配 --failure-evidence
                                （落地侧读数 JSON）。零 POST。
  --selftest（零网络零凭据）    夹具驱动断言（tools/fixtures/cb-bench-dispatch/，
                                含 failpaths/ 失败腿四形制夹具）。

触发契约三件套（D-117 实证；载荷构造时逐条内置，禁稀释）：
  ① 新开 issue（评论数 <100，一次卡一个 NPC 会话）② @CodeBuddy 落普通段落首词
  （非代码块/引用/列表/表格内）③ 全程不编辑已发评论（编辑不重触发）。

凭据纪律（零打印零落盘）：CNB token 只经 openBao 现取
（company/Git-Platform/CNB/CNB-{1,2}-all-privilege；org→secret 映射见
ORG_BAO_SECRET，KV 路径由 bao_kv_path() 纯字符串给出，本件自身零凭据读取路径
——--execute 恒拒 ⇒ 结构上不存在任何密钥读取动作）；落地侧现取只进 0600 临时件/
内存：禁 argv、禁 URL、禁日志、禁留痕件；留痕只记 issue 号+评论 id+UTC 时间戳+
指纹（sha256[:12]）。bao-agent get ... --reveal 的 stdout 直入 0600 件、用后
shred，与 ~/.local/bin/af-github-askpass 同源纪律。

同族参考件（禁改）：tools/cb-dispatch.py（bench 派发族，dispatch() 入口 :138）、
tools/cnb-card-dispatch.py（GitHub 板 → CNB 派发计划器，DEFAULT_CNB_REPO :72、
COMMENT_TMPL :77、--execute 恒拒 :258）。
"""
import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone

TZ8 = timezone(timedelta(hours=8))
CNB_API = "https://api.cnb.cool"
# CNB 侧承载仓（NPC 流水线所在仓；D-117 实证 cb-npc-poc#58）
DEFAULT_CNB_REPO = "Cloudbird-Software/cb-npc-poc"
# openBao KV 前缀（company/Git-Platform/CNB/<secret>；纯字符串常量，零 I/O）
BAO_KV_PREFIX = "company/Git-Platform/CNB/"
# org → openBao secret 名（CNB-1/CNB-2 双账号池，各 1600 核时/月；夜轨A2 实证）
ORG_BAO_SECRET = {
    "cloudbird-software": "CNB-1-all-privilege",
    "zhuzhu-team": "CNB-2-all-privilege",
}
EXECUTE_ENV = "CNB_DISPATCH_EXECUTE"
FIXTURE_DIR = os.path.join("tools", "fixtures", "cb-bench-dispatch")
# 机读行块首行机器标记（af-card/1.0 契约；与板卡机读块同源）
MACHINE_BLOCK_MARKER = "af-card/1.0"

COMMENT_TMPL = """@CodeBuddy 请按以下自包含 bench 卡面施工（工厂派发卡 {task_id}，债号 {debt}）：

{forward_seg}

---
派发契约（照 波次清单/沙箱派发契约.md 与 D-117 实证链路）：
- 本评论走 work_mode（替我上班）语义：可推分支/发 PR；不开则只读+评论。
- 产出取回走径 B：完整交卷内容放在你的最终回复里（交付块 + report 五节），厂内侧按评论回收；git push / 开 PR 在沙箱不可用（无 token 无厂内网）是环境事实，不属失败，无需尝试。
- 卡面即边界：allowed_paths 外零改动；禁项置顶段逐条有效；验收口径以环上（harness 侧）重跑为准，你的自报读数只作参考。
- 触发契约三件套：本评论落新开 issue 普通段落首词；一次操作一个 NPC 会话；全程不编辑已发评论（编辑不重触发）。"""


def sha12(text):
    """sha256[:12] 指纹（留痕件只记指纹，不记内容）。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def org_of(cnb_repo):
    """CNB 承载仓 → org（openBao secret 映射键）。"""
    return cnb_repo.split("/")[0].strip().lower()


def bao_kv_path(org):
    """org → openBao KV 全路径（company/Git-Platform/CNB/<secret>）。

    纯字符串函数、零 I/O 零凭据：给前置闸清单与落地侧现取用同一路径源，
    防两处各写一份漂移。org 未映射 ⇒ None（调用方 fail-closed 禁派）。
    """
    secret_name = ORG_BAO_SECRET.get(org)
    if not secret_name:
        return None
    return BAO_KV_PREFIX + secret_name


def parse_machine_block(body):
    """形制 C 机读行块：块首行恰为 `af-card/1.0`，其后连续 `key=value` 行。

    契约（板卡机读行块同款）：块止于首个空行/非 key=value 行/注释行；未知键
    容忍忽略；键统一小写；值内禁换行。无块返回 None（落回双形制逻辑）。
    """
    lines = body.splitlines()
    for i, ln in enumerate(lines):
        if ln.strip() != MACHINE_BLOCK_MARKER:
            continue
        kv = {}
        for raw in lines[i + 1:]:
            s = raw.strip()
            if not s or s.startswith("#") or "=" not in s:
                break
            k, _, v = s.partition("=")
            kv[k.strip().lower()] = v.strip()
        return kv
    return None


def parse_forward_seg(text):
    """从转发段文本抽 task_id/债号/标题/依赖行（三形制，认不出如实 None 禁猜）。

      A. 机读块形（af-card/1.0）：块内 debt=/task_id=/title=/depends_on= 优先；
      B. 板卡形（【任务】`x`／【债号】`x`／【依赖】…）；
      C. 排期员形（task_id: `x` ｜ 债号建议: **D-xxx**）。
    """
    kv = parse_machine_block(text)
    if kv is not None:
        return {"task_id": kv.get("task_id") or None,
                "debt": kv.get("debt") or None,
                "title": kv.get("title") or None,
                "depends_on_raw": kv.get("depends_on") or None,
                "format": "machine-block"}
    tid = re.search(r"【任务】`([^`]+)`", text) or re.search(
        r"task_id[:：]\s*`([a-z0-9][a-z0-9._-]{2,63})`", text)
    debt = re.search(r"【债号】`([^`]+)`", text) or re.search(
        r"债号(?:建议)?[:：]\s*(?:\*\*)?([A-Za-z]{1,5}-[A-Za-z0-9-]+)", text)
    title = re.search(r"^#\s+(.+)$", text, re.M)
    dep = re.search(r"【依赖】(.+)", text) or re.search(r"^[-*]\s*依赖[:：]\s*(.+)$", text, re.M)
    return {"task_id": tid.group(1) if tid else None,
            "debt": debt.group(1).strip() if debt else None,
            "title": title.group(1).strip() if title else None,
            "depends_on_raw": dep.group(1).strip() if dep else None,
            "format": "board" if "【任务】" in text else
                      ("scheduler" if re.search(r"task_id[:：]", text) else "unknown")}


def first_heading(text):
    """首个 markdown H1（标题核心段兜底源）。"""
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith("# ") and len(s) > 2:
            return s[2:].strip()
    return None


def preflight_lines(meta, org):
    """派发前置闸清单（列明判据与缺场事实；本版只渲染不代跑——真闸在真派发前置）。"""
    kv = bao_kv_path(org) or ("<org=%s 未映射：CNB-{1,2}-all-privilege 二选一，禁派>" % org)
    lines = [
        "占用闸 dispatch-occupancy-check.py %s —— 真派发前必跑（fail-closed，三面机检）"
        % (meta.get("debt") or "<债号缺场：占用闸无从判重，禁派>"),
        "审卡闸 card-selfcontainment-check.py（D-97 六要件）—— 真派发前必跑（无逃生口）",
        "CNB token 经 openBao 现取（%s；0600/内存，禁打印禁落盘禁 argv；留痕只记指纹）" % kv,
        "触发契约三件套：新开 issue（评论数 <100）+ @CodeBuddy 普通段落首词 + 一次卡一个会话；全程不编辑已发评论",
        "本版 --execute 恒拒（exit 3）：真执行腿四门未齐——真派发由落地侧按本计划载荷执行并留痕",
    ]
    if not meta.get("debt"):
        lines.insert(0, "WARN: 转发段缺债号——标题无从带债号、占用闸无从判重，禁派发")
    dep = meta.get("depends_on_raw")
    if dep and dep not in ("无", ""):
        lines.insert(0, "WARN: 转发段依赖=%r——依赖前置未解前禁派（派发侧依赖阻断）" % dep)
    return lines


def render_payload(seg_text, meta, issue_no, cnb_repo, overrides=None):
    """渲染 CNB 派发载荷（纯函数，零网络零凭据；夹具与 --plan 都走这里）。"""
    overrides = overrides or {}
    org = org_of(cnb_repo)
    tid = overrides.get("task_id") or meta.get("task_id") or ("seg-" + sha12(seg_text))
    debt = overrides.get("debt") or meta.get("debt")
    title = (overrides.get("title") or meta.get("title")
             or first_heading(seg_text) or "bench 派发卡")
    comment = COMMENT_TMPL.format(task_id=tid, debt=debt or "缺场",
                                  forward_seg=seg_text.rstrip("\n"))
    return {
        "schema": "af.cb-bench-dispatch.plan.v1",
        "github_issue": issue_no,
        "task_id": tid,
        "debt": debt,
        "depends_on_raw": meta.get("depends_on_raw"),
        "card_format": meta.get("format"),
        "cnb_repo": cnb_repo,
        "cnb_org": org,
        "cnb_kv_path": bao_kv_path(org),
        "cnb_issue_title": "[%s] %s" % (debt or "debt-缺场", title),
        "cnb_issue_body": seg_text,
        "cnb_comment": comment,
        "work_mode": True,
        "trigger_contract": {
            "new_issue_comments_lt_100": True,
            "codebuddy_first_word_plain_paragraph": comment.startswith("@CodeBuddy "),
            "one_npc_session_per_card": True,
            "never_edit_sent_comment": True,
        },
        "fingerprints": {
            "forward_seg": sha12(seg_text),
            "cnb_issue_body": sha12(seg_text),
            "cnb_comment": sha12(comment),
        },
        "preflight": preflight_lines(meta, org),
        "plan_generated_at": datetime.now(TZ8).isoformat(timespec="seconds"),
    }


def cmd_plan(args):
    """计划态：渲染载荷+前置闸清单，写 ndjson/summary，零 POST。"""
    with open(args.body_file, encoding="utf-8") as f:
        seg_text = f.read()
    meta = parse_forward_seg(seg_text)
    overrides = {"debt": args.debt, "task_id": args.task_id, "title": args.title}
    payload = render_payload(seg_text, meta, args.issue or 0, args.cnb_repo, overrides)
    os.makedirs(args.out_dir, exist_ok=True)
    out_nd = os.path.join(args.out_dir, "dispatch-plan.ndjson")
    out_md = os.path.join(args.out_dir, "dispatch-plan-summary.md")
    with open(out_nd, "w", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    with open(out_md, "w", encoding="utf-8") as f:
        f.write("# CNB bench 派发计划（计划态·零 POST） %s\n\n"
                % payload["plan_generated_at"])
        f.write("- 源：转发段文件 %s（卡号盖 %s）\n- 目标 CNB 仓：%s（org=%s）\n"
                "- 债号：%s ｜ task_id：%s ｜ 形制：%s\n\n"
                % (args.body_file, args.issue or 0, args.cnb_repo, payload["cnb_org"],
                   payload["debt"] or "缺", payload["task_id"], payload["card_format"]))
        f.write("- CNB issue 标题：`%s`\n- work_mode：%s\n- 指纹链：%s\n\n"
                % (payload["cnb_issue_title"], payload["work_mode"],
                   json.dumps(payload["fingerprints"], ensure_ascii=False)))
        for ln in payload["preflight"]:
            f.write("- %s\n" % ln)
        f.write("\n> 本件 --plan 零 POST；--execute 本版恒拒（exit 3）——四门齐备后由后续裁件解锁。\n")
    print("plan: body-file=%s issue=%s cnb_repo=%s -> %s / %s（零 POST）"
          % (args.body_file, args.issue or 0, args.cnb_repo, out_nd, out_md))
    return 0


def cmd_execute(args):
    """执行腿：本版恒拒（fail-closed）。授权四门未齐前不解锁——照
    tools/cnb-card-dispatch.py:258 同款形制：拒发+留档+零 POST。"""
    print("EXECUTE 拒发（exit 3）：本版为计划态——真执行腿四门（占用闸/审卡闸/"
          "CNB token 经 openBao 现取纪律就绪/运营者授权环境量 %s=YES）未齐，"
          "真派发由落地侧按 --plan 产物执行并留痕（D-130 验收第 7 条）。"
          "本次零 POST，拒发事实已留档。" % EXECUTE_ENV)
    with open(args.refused_log, "a", encoding="utf-8") as f:
        f.write("%s\texecute-refused\tcnb_repo=%s\tissue=%s\n"
                % (datetime.now(TZ8).isoformat(timespec="seconds"),
                   args.cnb_repo, args.issue if args.issue is not None else "*"))
    return 3


# =============================================================================
# 失败腿如实短路（D-134 · factory-os#149）：派发器失败路径诚实闭环
# =============================================================================
# 卡面 S9 原文（30-工件/夜轨A2-20261107/cnb真沙箱bench环-读数-20261107.md:199）：
#   「失败腿如实短路：诚实纪律写进派发器——沙箱未复现/部分交卷/判分任一 false 时，
#     链路照走完（收卷核+判分+回卡如实判），verdict=not_resolved 也闭环（D-107/
#     D-117 同口径：跑得通≠做对题）；沙箱回复不含 diff 块且超静默窗 ⇒ 如实记
#     「未交卷」并回卡留痕，禁人工抢救判分。」
#
# 四形制与处置（卡面「本卡交付」第 1 条逐字对应；每分支落留痕件，禁分支静默 return）：
#   ① not_reproduced     沙箱未复现（回卷自报 not_run/复现失败）
#                        ⇒ 收卷核照走 + 判分照跑 + 回卡如实判
#   ② partial_submission 部分交卷（diff 不完整/report 缺节）
#                        ⇒ 收件判据三条不过 ⇒ 记未收卷 + 回卡
#   ③ not_resolved       verdict=not_resolved/false
#                        ⇒ 链路照走完 + 如实回卡（D-133 未合线 ⇒ 内联同形制渲染）
#   ④ no_submission      超静默窗零 diff 块
#                        ⇒ 记「未交卷」+ 回卡留痕
#
# 纪律映射（卡面禁项逐条落地为结构，非口头约定）：
#   P1 判据/判官件零改动——本段只读 evidence 里的判分读数，禁碰 swev-judge-v2.py；
#   P2 禁改判据迁就失败——verdict 只从证据原样取用（judge_verdict_of 零改写）；
#   P3 禁假绿/禁静默——判分没跑=写没跑（judge.ran=false 如实记）；失败卷禁静默
#      丢弃（②④ 也落全卷指纹链留痕，禁只收成功卷）；
#   P4 禁编辑已发评论/禁 force push——本段零 POST（计划态渲染，落地侧照计划执行）；
#   P5 只增失败路径段——派发主路径（parse/render/cmd_plan/cmd_execute）零改动。
#
# 与 D-133（回卡渲染 tools/cnb-verdict-reply.py，factory-os#148）关系：调用关系非
# 依赖——D-133 未合线（在飞）⇒ 本段内联同形制渲染，禁互相阻塞；D-133 合线后可由
# 落地侧改调渲染件（改调用点不动本段闭环结构）。

# 四形制规范码（卡面四形制逐字对应；判词如实禁改）
FORM_NOT_REPRODUCED = "not_reproduced"      # ① 沙箱未复现
FORM_PARTIAL = "partial_submission"        # ② 部分交卷
FORM_NOT_RESOLVED = "not_resolved"         # ③ verdict=not_resolved
FORM_NO_SUBMISSION = "no_submission"       # ④ 超静默窗零 diff 块（未交卷）

FAIL_FORMS = (FORM_NOT_REPRODUCED, FORM_PARTIAL, FORM_NOT_RESOLVED, FORM_NO_SUBMISSION)

FAIL_FORM_LABELS = {
    FORM_NOT_REPRODUCED: "① 沙箱未复现（回卷自报 not_run/复现失败）",
    FORM_PARTIAL: "② 部分交卷（diff 不完整/report 缺节）",
    FORM_NOT_RESOLVED: "③ verdict=not_resolved（判分如实判负）",
    FORM_NO_SUBMISSION: "④ 超静默窗零 diff 块（未交卷）",
}

# 收件判据三条（D-117 实证口径：30-工件/夜轨A2-20261107/cnb-dispatch-trace.md §三
# 「收件判据 = patch.diff 完整 unified diff + report 五节 + git apply --check rc=0」）
COLLECT_CRITERIA = ("unified_diff_complete", "report_five_sections", "pristine_apply_check_rc0")
COLLECT_CRITERIA_LABELS = {
    "unified_diff_complete": "patch.diff 完整 unified diff",
    "report_five_sections": "report 五节（①②③④⑤）齐",
    "pristine_apply_check_rc0": "pristine 基线 git apply --check rc=0",
}
# 收卷核结论词（如实：收到/未收卷/未交卷；禁改判据迁就失败）
COLLECT_COLLECTED = "collected"            # 判据三条全过
COLLECT_NOT_COLLECTED = "not_collected"    # ② 未收卷
COLLECT_NOT_SUBMITTED = "not_submitted"    # ④ 未交卷
# 失败形制回卡标签建议（四形制皆诚实失败格；D-117 先例 not_resolved ⇒ state:rejected）
FAIL_STATE_LABEL = "state:rejected"
# 静默窗参数（bot 侧 tools/cb-dispatch.py bench-watch 同源口径：首候选后静默
# ≥300s 关窗、90min 硬顶、取末卷、全卷指纹链先落盘；本段只接其输出）
SILENCE_THRESHOLD_SECONDS = 300
SILENCE_HARD_CAP_SECONDS = 5400
# 闭环记录 schema
FAILURE_CLOSURE_SCHEMA = "af.cb-bench-dispatch.failure-closure.v1"
# 禁抢救形态命名 token（selftest 结构断言用：模块内禁出现此类命名——禁人工抢救）
RESCUE_NAME_TOKENS = ("rescue", "salvage", "抢救", "relax", "放宽", "downgrade",
                      "override_verdict", "force_pass", "auto_pass", "promote_verdict")


def judge_verdict_of(evidence):
    """判分 verdict 原样取回（P2：一字不改，禁任何放宽/改写/抢救）。

    evidence 无判分读数 ⇒ None（调用方如实记「判分未跑」——禁猜 verdict）。
    """
    j = evidence.get("judge") if isinstance(evidence, dict) else None
    if not isinstance(j, dict):
        return None
    v = j.get("verdict")
    return v if isinstance(v, str) and v else None


def collect_check(form, evidence):
    """收卷核：按收件判据三条逐条核（D-117 实证口径），如实给读数。

    返回 dict：criteria（三条逐条 True/False/not_evaluable）+ result + note。
      result ∈ {collected, not_collected, not_submitted}
    判据三条全过 ⇒ collected；任一条不过 ⇒ not_collected（② 未收卷）；
    ④ 形制无卷可核 ⇒ not_submitted（未交卷，判据逐条 not_evaluable）。
    """
    if form == FORM_NO_SUBMISSION:
        return {"criteria": {c: "not_evaluable" for c in COLLECT_CRITERIA},
                "result": COLLECT_NOT_SUBMITTED,
                "note": "超静默窗零 diff 块：无卷可核（未交卷，判据逐条 not_evaluable）"}
    reply = evidence.get("sandbox_reply") if isinstance(evidence, dict) else None
    reply = reply if isinstance(reply, dict) else {}
    crit = {
        "unified_diff_complete": bool(reply.get("unified_diff_complete")),
        "report_five_sections": bool(reply.get("report_five_sections")),
        "pristine_apply_check_rc0": reply.get("apply_check_rc") == 0,
    }
    failed = [c for c in COLLECT_CRITERIA if not crit[c]]
    if failed:
        return {"criteria": crit,
                "result": COLLECT_NOT_COLLECTED,
                "failed_criteria": failed,
                "note": "收件判据未过：%s ⇒ 记未收卷（禁放宽判据迁就失败）"
                        % "、".join(COLLECT_CRITERIA_LABELS[c] for c in failed)}
    return {"criteria": crit,
            "result": COLLECT_COLLECTED,
            "note": "收件判据三条全过（unified diff 完整 + report 五节 + apply --check rc=0）"}


def judge_segment(form, evidence, cc):
    """判分段：照跑/不跑都如实记（P3：没跑=写没跑，红的=写红的）。

    ① 收卷核过 ⇒ 判分照跑，verdict 原样取用（P2 禁改一字）；
    ③ verdict=not_resolved ⇒ 判分已跑过，verdict 原样透传（D-117 先例口径）；
    ② 未收卷 ⇒ 无有效判分输入，判分腿不接（如实记未跑+原因，禁假绿）；
    ④ 未交卷 ⇒ 无判分输入，判分腿不接（如实记未跑+原因）。
    """
    verdict = judge_verdict_of(evidence)
    if cc["result"] != COLLECT_COLLECTED:
        return {"ran": False, "verdict": None,
                "note": "%s ⇒ 无有效判分输入，判分腿不接（如实记未跑，禁假绿）" % cc["note"]}
    if verdict is None:
        return {"ran": False, "verdict": None,
                "note": "收卷核过但判分读数缺场：落地侧未跑判分——如实记未跑，禁猜 verdict"}
    return {"ran": True, "verdict": verdict,
            "note": "判分照跑/已跑：verdict 原样取用（零改写、零人工抢救）"}


def verdict_words(closure):
    """判词（如实）：①③=判分 verdict 原样；②=未收卷；④=未交卷。

    禁改判据迁就失败（P2）：本函数只做如实转录，禁任何升级/放宽语义。
    """
    j = closure["judge"]
    if j["ran"] and j["verdict"]:
        return j["verdict"]
    if closure["form"] == FORM_PARTIAL:
        return "%s（未收卷）" % COLLECT_NOT_COLLECTED
    if closure["form"] == FORM_NO_SUBMISSION:
        return "%s（未交卷）" % COLLECT_NOT_SUBMITTED
    return "judge_not_run（判分未跑，如实记）"


def render_failure_comment(closure):
    """回卡渲染（内联同形制）：D-133（cnb-verdict-reply.py）未合线 ⇒ 内联渲染，
    禁互相阻塞。公开面纪律（S8/D-117 实证口径）：测试只给计数、零凭据形态、
    失配归因结构级（逐字 ID 不复制，留内档坐标引用）。
    """
    cc, js = closure["collect_check"], closure["judge"]
    crit = "；".join("%s=%s" % (COLLECT_CRITERIA_LABELS[c],
                                "过" if cc["criteria"][c] is True else
                                ("未过" if cc["criteria"][c] is False else "不可核"))
                     for c in COLLECT_CRITERIA)
    if js["ran"]:
        judge_line = "判分照跑 verdict=%s（%s）" % (js["verdict"], js["note"])
    else:
        judge_line = "判分未跑（%s）" % js["note"]
    reply_chain = closure["fingerprints"].get("reply_chain") or []
    chain_line = ("全卷指纹链（先落盘，禁静默丢弃）：%s" % " → ".join(reply_chain)
                  if reply_chain else "全卷指纹链：空（无回卷可记）")
    return (
        "@运营者 派发失败腿闭环（{label}）· 债号 {debt} · factory-os#{issue}\n\n"
        "verdict={verdict}（如实判，零人工抢救）\n"
        "- 收卷核：{result}（判据三条：{crit}）\n"
        "- 判分：{judge_line}\n"
        "- {chain}\n"
        "- 留痕件：{trace}（形制+读数+指纹链）\n\n"
        "失败卷禁静默丢弃、禁只收成功卷；禁以任何形态放宽判分或收件判据（P2）。\n"
        "标签建议：翻 {label_state}（诚实失败格）。"
    ).format(label=closure["form_label"], debt=closure["debt"] or "缺场",
             issue=closure["github_issue"] if closure["github_issue"] is not None else "?",
             verdict=closure["verdict_words"], result=cc["result"], crit=crit,
             judge_line=judge_line, chain=chain_line,
             trace=closure.get("trace_file") or "<留痕件路径见闭环记录>",
             label_state=FAIL_STATE_LABEL)


def close_failure_path(form, evidence, out_dir=".", github_issue=None, debt=None):
    """失败腿如实短路主入口：四形制之一 ⇒ 链路照走完 + 留痕件。

    链路三段（每形制都在，禁分支静默 return）：
      收卷核 collect_check（判据三条逐条核）→ 判分 judge（照跑/不跑都如实记）
      → 回卡 card_back（内联同形制渲染）。
    留痕件：形制+读数+指纹链，落 <out_dir>/failure-closure-<form>-<指纹>.json。
    返回闭环记录 dict（禁 None：任何形制都闭环留痕）。
    form 不在四形制 ⇒ ValueError（fail-closed 禁猜，禁静默吞）。
    """
    if form not in FAIL_FORMS:
        raise ValueError("失败形制不在四形制内（fail-closed 禁猜）: %r" % (form,))
    evidence = evidence if isinstance(evidence, dict) else {}
    cc = collect_check(form, evidence)
    js = judge_segment(form, evidence, cc)
    reply = evidence.get("sandbox_reply") if isinstance(evidence.get("sandbox_reply"), dict) else {}
    chain = reply.get("reply_fingerprints")
    closure = {
        "schema": FAILURE_CLOSURE_SCHEMA,
        "form": form,
        "form_label": FAIL_FORM_LABELS[form],
        "debt": debt if debt is not None else evidence.get("debt"),
        "github_issue": github_issue if github_issue is not None else evidence.get("github_issue"),
        "link_segments": ["collect_check", "judge", "card_back"],
        "collect_check": cc,
        "judge": js,
        "honesty": {
            "rescue_attempted": False,    # 禁人工抢救：结构上无抢救分支
            "criteria_relaxed": False,    # P2：判据零放宽
            "silent_drop": False,         # P3：失败卷禁静默丢弃
            "verdict_modified": False,    # P2：verdict 零改写
        },
        "fingerprints": {
            "evidence": sha12(json.dumps(evidence, ensure_ascii=False, sort_keys=True)),
            "reply_chain": list(chain) if isinstance(chain, list) else [],
        },
        "closed_at": datetime.now(TZ8).isoformat(timespec="seconds"),
    }
    closure["verdict_words"] = verdict_words(closure)
    closure["fingerprints"]["closure_readings"] = sha12(json.dumps(
        {"form": form, "collect_check": cc, "judge": js, "verdict_words": closure["verdict_words"]},
        ensure_ascii=False, sort_keys=True))
    closure["card_back"] = {
        "rendered_by": "inline（D-133 cnb-verdict-reply.py 未合线：内联同形制渲染，禁互相阻塞）",
        "suggested_label": FAIL_STATE_LABEL,
        "comment": None,
    }
    closure["card_back"]["comment"] = render_failure_comment(closure)
    closure["fingerprints"]["card_back_comment"] = sha12(closure["card_back"]["comment"])
    # 留痕件（形制+读数+指纹链）——每分支必落，禁分支静默 return
    os.makedirs(out_dir, exist_ok=True)
    trace = os.path.join(out_dir, "failure-closure-%s-%s.json"
                         % (form, closure["fingerprints"]["closure_readings"]))
    with open(trace, "w", encoding="utf-8") as f:
        f.write(json.dumps(closure, ensure_ascii=False, indent=1) + "\n")
    closure["trace_file"] = trace
    return closure


def cmd_failure_plan(args):
    """失败腿计划态（--failure-form）：四形制之一 ⇒ 闭环记录+留痕件，零 POST。

    --failure-evidence 接受两形制读数件：夹具形（含 "evidence" 键，如
    tools/fixtures/cb-bench-dispatch/failpaths/*.json——形制须与 --failure-form
    一致，fail-closed 禁猜）或裸读数形（顶层即 sandbox_reply/judge/silent_window）。
    """
    if not args.failure_evidence:
        print("FATAL: --failure-form 需 --failure-evidence（落地侧读数 JSON；无读数禁闭环）",
              file=sys.stderr)
        return 2
    with open(args.failure_evidence, encoding="utf-8") as f:
        doc = json.load(f)
    fx_debt = fx_issue = None
    if isinstance(doc.get("evidence"), dict):
        ev = doc["evidence"]
        fx_form = doc.get("form")
        if fx_form and fx_form != args.failure_form:
            print("FATAL: 读数件形制 %r 与 --failure-form %r 不一致（fail-closed 禁猜）"
                  % (fx_form, args.failure_form), file=sys.stderr)
            return 2
        fx_debt, fx_issue = doc.get("debt"), doc.get("github_issue")
    else:
        ev = doc
    try:
        closure = close_failure_path(
            args.failure_form, ev, out_dir=args.out_dir,
            github_issue=args.issue if args.issue is not None else fx_issue,
            debt=args.debt if args.debt is not None else fx_debt)
    except ValueError as e:
        print("FATAL: %s" % e, file=sys.stderr)
        return 2
    print("failure-closure: form=%s（%s）verdict=%s trace=%s（零 POST）"
          % (closure["form"], closure["form_label"], closure["verdict_words"],
             closure["trace_file"]))
    return 0


def selftest():
    """夹具断言：零网络、零凭据。机读块解析/载荷形制/触发契约三件套/零 POST
    结构断言/前置闸负例×2/--execute 恒拒/--plan 零 POST 产物。"""
    n = [0]

    def ck(cond, msg):
        n[0] += 1
        assert cond, msg

    fixture = os.path.join(FIXTURE_DIR, "forward-seg.md")
    ck(os.path.isfile(fixture), "夹具缺场: %s" % fixture)
    with open(fixture, encoding="utf-8") as f:
        seg_text = f.read()
    with open(os.path.join(FIXTURE_DIR, "expected-plan.json"), encoding="utf-8") as f:
        exp = json.load(f)["expect"]

    # ── 解析面：af-card/1.0 机读块 ──
    meta = parse_forward_seg(seg_text)
    ck(meta["format"] == exp["card_format"], meta)
    ck(meta["debt"] == exp["debt"], meta)
    ck(meta["task_id"] == exp["task_id"], meta)
    ck(meta["depends_on_raw"] == "无", meta)

    # ── org→openBao secret 映射（纯字符串）──
    org = org_of(exp["cnb_repo"])
    ck(bao_kv_path(org) == exp["cnb_kv_path"], bao_kv_path(org))
    ck(bao_kv_path("unknown-org") is None, "未映射 org 须 None（fail-closed）")

    # ── 载荷形制：四键 + 期望断言件逐项 ──
    p = render_payload(seg_text, meta, 0, exp["cnb_repo"])
    for k in exp["required_keys"]:
        ck(k in p, "载荷缺键: %s" % k)
    ck(p["cnb_issue_title"].startswith(exp["cnb_issue_title_prefix"]), p["cnb_issue_title"])
    ck(p["work_mode"] is exp["work_mode"], p["work_mode"])
    ck(p["cnb_comment"].startswith(exp["cnb_comment_first_word"] + " "), "评论首词须 @CodeBuddy")

    # ── 触发契约三件套形制 ──
    ck(p["cnb_comment"].startswith("@CodeBuddy"), "评论须以 @CodeBuddy 起头（普通段落首词）")
    for bad in ("```", ">", "-", "|", " ", "\t", "\n"):
        ck(not p["cnb_comment"].startswith(bad), "评论首词前禁前导形态: %r" % bad)
    tc = p["trigger_contract"]
    for k, v in exp["trigger_contract"].items():
        ck(tc[k] is v, "trigger_contract.%s=%r" % (k, tc[k]))
    ck(len(p["fingerprints"]["cnb_comment"]) == exp["fingerprint_len"], "指纹须 12 位")

    # ── 零 POST 结构断言：本件不引入任何网络栈（--plan 零 POST 是结构事实，
    #      非"约定不发"——AST 级核导入面，防将来误接网络调用）──
    import ast
    tree = ast.parse(open(__file__, encoding="utf-8").read())
    netmods = {"urllib", "requests", "http", "socket"}
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    ck(not (imported & netmods), "本件禁引入网络栈: %s" % sorted(imported & netmods))

    # ── 前置闸清单 + 负例 ──
    pl = p["preflight"]
    ck(any("占用闸" in x for x in pl), pl)
    ck(any("openBao" in x for x in pl), pl)
    neg = dict(meta, debt=None)
    ck(any("缺债号" in x for x in preflight_lines(neg, org)), "缺债号 ⇒ 禁派 WARN 在列")
    dep_meta = dict(meta, depends_on_raw="D-129 前置卡在板")
    ck(any("依赖" in x for x in preflight_lines(dep_meta, org)), "有依赖 ⇒ 依赖 WARN 在列")

    # ── --execute 恒拒：exit 3 + 拒发记录 + 零 POST ──
    with tempfile.TemporaryDirectory() as td:
        ns = argparse.Namespace(cnb_repo=exp["cnb_repo"], issue=0,
                                refused_log=os.path.join(td, "refused.log"))
        ck(cmd_execute(ns) == 3, "--execute 须恒拒 exit 3")
        with open(ns.refused_log, encoding="utf-8") as f:
            log_txt = f.read()
        ck("execute-refused" in log_txt, "拒发事实须留档")

        # ── --plan 零 POST 产物：ndjson 一行 + summary 在场 + 载荷键齐 ──
        ns2 = argparse.Namespace(body_file=fixture, issue=0, cnb_repo=exp["cnb_repo"],
                                 out_dir=td, debt=None, task_id=None, title=None)
        ck(cmd_plan(ns2) == 0, "--plan 须 rc=0")
        nd = os.path.join(td, "dispatch-plan.ndjson")
        ck(os.path.isfile(nd) and os.path.isfile(os.path.join(td, "dispatch-plan-summary.md")),
           "--plan 产物缺场")
        with open(nd, encoding="utf-8") as f:
            rows = [json.loads(x) for x in f if x.strip()]
        ck(len(rows) == 1, "ndjson 须恰一行")
        row = rows[0]
        ck(row["cnb_issue_title"].startswith(exp["cnb_issue_title_prefix"]), row["cnb_issue_title"])
        ck(row["cnb_comment"].startswith("@CodeBuddy "), "ndjson 评论首词 @CodeBuddy")
        ck(row["work_mode"] is True, "ndjson work_mode=true")

    # ── 失败腿四形制夹具（D-134 · factory-os#149）：每形制断言「收卷核+判分+回卡」
    #    三段都在链路内 + 判词如实 + 禁抢救分支不存在 + 留痕件在场（零网络零凭据）──
    import ast
    fp_dir = os.path.join(FIXTURE_DIR, "failpaths")
    fp_files = sorted(f for f in os.listdir(fp_dir) if f.endswith(".json")) \
        if os.path.isdir(fp_dir) else []
    ck(len(fp_files) == 4, "失败腿夹具须恰四件（四形制各一）: %s" % fp_files)
    seen_forms = []
    with tempfile.TemporaryDirectory() as td:
        for fn in fp_files:
            with open(os.path.join(fp_dir, fn), encoding="utf-8") as f:
                fx = json.load(f)
            form = fx["form"]
            seen_forms.append(form)
            closure = close_failure_path(form, fx["evidence"], out_dir=td,
                                         github_issue=fx.get("github_issue"),
                                         debt=fx.get("debt"))
            ex = fx["expect"]
            # ① 链路三段都在链路内（禁分支静默 return）
            ck(closure["link_segments"] == ex["link_segments"], (fn, closure["link_segments"]))
            for seg in ex["link_segments"]:
                ck(isinstance(closure.get(seg), dict) and closure[seg],
                   "%s 段缺场/空: %s" % (fn, seg))
            ck(closure["schema"] == FAILURE_CLOSURE_SCHEMA, fn)
            # ② 判词如实（收卷核结论/判分跑否/判词逐字）
            ck(closure["verdict_words"] == ex["verdict"], (fn, closure["verdict_words"], ex["verdict"]))
            ck(closure["collect_check"]["result"] == ex["collect_result"], (fn, closure["collect_check"]))
            ck(closure["judge"]["ran"] is ex["judge_ran"], (fn, closure["judge"]))
            if ex.get("collect_failed_criteria"):
                ck(closure["collect_check"].get("failed_criteria") == ex["collect_failed_criteria"], fn)
            # ①③ verdict 原样透传（P2 禁改一字）
            if ex.get("verdict_verbatim"):
                ev_verdict = (fx["evidence"].get("judge") or {}).get("verdict")
                ck(closure["judge"]["verdict"] == ev_verdict,
                   (fn, closure["judge"]["verdict"], ev_verdict))
            # ③ 禁人工抢救：honesty 四旗全 False（禁放宽/禁静默/禁改判）
            for k, v in closure["honesty"].items():
                ck(v is False, (fn, k, v))
            # ④ 留痕件在场：形制+读数+指纹链
            trace = closure.get("trace_file")
            ck(bool(trace) and os.path.isfile(trace), (fn, trace))
            with open(trace, encoding="utf-8") as f:
                tj = json.load(f)
            ck(tj["form"] == form and tj["form_label"], fn)
            ck(tj["collect_check"] and tj["judge"] and tj["card_back"]["comment"], fn)
            ck(tj["fingerprints"].get("evidence") and tj["fingerprints"].get("closure_readings")
               and tj["fingerprints"].get("card_back_comment"), fn)
            # 回卡渲染：形制判词在文内 + 标签建议 + 纪律句
            ck(closure["verdict_words"] in closure["card_back"]["comment"], fn)
            ck(closure["card_back"]["suggested_label"] == ex["card_back_suggested_label"], fn)
            ck(ex["card_back_must_contain"] in closure["card_back"]["comment"], fn)
            # ②④ 全卷指纹链在场（禁静默丢弃、禁只收成功卷）
            if ex.get("reply_chain_preserved"):
                ck(closure["fingerprints"]["reply_chain"] ==
                   fx["evidence"]["sandbox_reply"]["reply_fingerprints"], fn)
        ck(sorted(seen_forms) == sorted(FAIL_FORMS), seen_forms)
        # fail-closed：形制不在四形制 ⇒ ValueError（禁静默吞）
        raised = False
        try:
            close_failure_path("bogus_form", {"judge": {"verdict": "not_resolved"}}, out_dir=td)
        except ValueError:
            raised = True
        ck(raised, "未知失败形制须 fail-closed 抛错（禁静默吞）")
        # 禁抢救分支不存在（结构断言）：模块内禁 rescue/抢救/relax/放宽 等命名的
        # 函数/类；禁 except 体仅 pass（禁静默吞异常——P3）
        tree = ast.parse(open(__file__, encoding="utf-8").read())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                low = node.name.lower()
                for t in RESCUE_NAME_TOKENS:
                    ck(t.lower() not in low, "禁抢救形态命名: %s（token=%s）" % (node.name, t))
            if isinstance(node, ast.ExceptHandler):
                only_pass = len(node.body) == 1 and isinstance(node.body[0], ast.Pass)
                ck(not only_pass, "禁 except 体仅 pass（静默吞异常）: line %s" % node.lineno)

    print("selftest: %d/%d 断言全过（机读块解析/org→secret 映射/载荷四键+断言件/"
          "触发契约三件套形制/零 POST 结构断言/前置闸负例×2/--execute 恒拒 exit 3/"
          "--plan 零 POST 产物/失败腿四形制夹具：三段链路+判词如实+禁抢救+留痕）"
          % (n[0], n[0]))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cnb-repo", default=DEFAULT_CNB_REPO,
                    help="CNB 承载仓（owner/name；NPC 流水线所在仓，缺省 %s）" % DEFAULT_CNB_REPO)
    ap.add_argument("--body-file", default=None,
                    help="卡面转发段文件（bench 卡型禁项置顶+自包含范式）")
    ap.add_argument("--issue", type=int, default=None, help="源卡 issue 号（留痕记账用；缺=0）")
    ap.add_argument("--debt", default=None, help="盖转发段解析的债号（缺省按转发段机读）")
    ap.add_argument("--task-id", dest="task_id", default=None,
                    help="盖转发段解析的 task_id（缺省按转发段机读）")
    ap.add_argument("--title", default=None,
                    help="盖 CNB issue 标题核心段（缺省按转发段 title=/首个 H1）")
    ap.add_argument("--out-dir", default=".", help="--plan 产物目录（缺省运行目录）")
    ap.add_argument("--refused-log", default="dispatch-execute-refused.log",
                    help="--execute 拒发记录路径")
    ap.add_argument("--failure-form", dest="failure_form", default=None,
                    choices=list(FAIL_FORMS),
                    help="失败腿形制（D-134 四形制：%s）" % "/".join(FAIL_FORMS))
    ap.add_argument("--failure-evidence", dest="failure_evidence", default=None,
                    help="失败腿落地侧读数 JSON（--failure-form 必配；无读数禁闭环）")
    sub = ap.add_mutually_exclusive_group()
    sub.add_argument("--plan", action="store_true",
                     help="计划态（默认）：渲染派发载荷+前置闸清单，零 POST")
    sub.add_argument("--execute", action="store_true",
                     help="执行态：本版恒拒（exit 3，四门未齐）")
    ap.add_argument("--selftest", action="store_true", help="夹具自测（零网络零凭据）")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if args.execute:
        return cmd_execute(args)
    if args.failure_form:
        return cmd_failure_plan(args)
    if not args.body_file:
        print("FATAL: --plan 需 --body-file（卡面转发段文件；bench 卡型禁项置顶+自包含范式）",
              file=sys.stderr)
        return 2
    return cmd_plan(args)


if __name__ == "__main__":
    sys.exit(main())
