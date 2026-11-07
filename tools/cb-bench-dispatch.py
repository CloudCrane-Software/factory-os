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

模式：
  --plan（默认；零 POST 干跑）  渲染全部载荷+前置闸清单，写 dispatch-plan.ndjson
                                + dispatch-plan-summary.md；不发任何 POST。
  --execute（本版恒拒 exit 3）  真执行腿四门未齐（占用闸/审卡闸/CNB token 经
                                openBao 现取纪律就绪/运营者授权环境量）——照
                                tools/cnb-card-dispatch.py:258 同款 fail-closed
                                形制：恒拒发+拒发记录落档+零 POST。真派发由落地侧
                                按 --plan 产物执行（D-130 验收命令集第 7 条）。
  --selftest（零网络零凭据）    夹具驱动断言（tools/fixtures/cb-bench-dispatch/）。

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

    print("selftest: %d/%d 断言全过（机读块解析/org→secret 映射/载荷四键+断言件/"
          "触发契约三件套形制/零 POST 结构断言/前置闸负例×2/--execute 恒拒 exit 3/"
          "--plan 零 POST 产物）" % (n[0], n[0]))
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
    if not args.body_file:
        print("FATAL: --plan 需 --body-file（卡面转发段文件；bench 卡型禁项置顶+自包含范式）",
              file=sys.stderr)
        return 2
    return cmd_plan(args)


if __name__ == "__main__":
    sys.exit(main())
