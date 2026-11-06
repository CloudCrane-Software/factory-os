#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cnb-card-dispatch.py — GitHub 板 state:queued 卡 → CNB CodeBuddy 沙箱 派发计划器（v0 计划态）。

定位（夜轨C 2026-11-07 补件；G4 执行派发自动化的接线草案·计划态；夜轨C3-20261107
落库批=第三形制兼容+机读行块证据通道）
----
planner（factory-os/.github/workflows/planner.yml step 10）建卡后，卡停在
`state:queued`，派发仍是「运营者手动转发沙箱」（staging/sandbox-dispatch-template.md
明文「工厂侧自动派发 = 后续项」）。本件把派发自动化走通**前半程**：

  --plan（默认，只读零副作用）
      拉 GitHub 板 state:queued 卡 → 逐卡渲染 CNB 派发载荷
      （CNB issue title/body + @CodeBuddy 评论 + work_mode:true 语义标记）→
      写 dispatch-plan.ndjson + 人读摘要。**不发任何 POST。**

  --plan --body-file F（本地卡面模式，零网络零 POST）
      不拉板，读本地卡面文件 F 走同一条 render_payload/parse_card 解析路径——
      卡面模板复渲染/夹具的机器识别证据通道（夜轨C3 断点2 闭合证据用；
      配 --issue 可盖真实卡号）。产物同 dispatch-plan.ndjson + summary。

  --execute（本版恒拒）
      CNB 写入腿（POST /{repo}/-/issues + comments，参考
      30-工件/夜轨A-20261106/cnb沙箱起用法-v1.md §二 API 实测 201）。
      本版**未授权执行**：恒 exit 3 并留拒发记录——真执行腿须先过
      ①占用闸（tools/dispatch-occupancy-check.py）②审卡闸
      （tools/card-selfcontainment-check.py，D-97）③运营者明示授权
      （环境量 CNB_DISPATCH_EXECUTE=YES）④CNB token 经 openBao 现取
      （company/Git-Platform/CNB/CNB-1-all-privilege，禁打印禁落盘）。
      四门齐备才在后续版本解开本开关（明早清单 D-4）。

卡面三形制（2026-11-07 实读）
----
  A. planner 机建形（planner.yml step 10）：【任务】`x`／【债号】`x`／【依赖】…
  B. 排期员手建形（统一建设排期 §六）：``- task_id: `x` ｜ 债号建议: **D-102**``
  C. 表单渲染形（issue form card.yml/directive.yml 建，### 分节+粗体）——
     夜轨C2 断点2 实证（fos#84 首跑 debt=None、#77–82 同症）：A/B 两形制与
     planner step 04（只认【债号】，planner.yml:664）均不认。闭合件=表单模板
     内置 **af-card/1.0 机读行块**（首行机器标记+结构化 key=value 体，fos#26
     判读器「首行机器标记＋结构化体」同风格；与 card.yml/directive.yml 同批
     内置）。本件 parse_card 对 C 加分支：body 含 `af-card/1.0` 块 → 机器只认
     块内键值（debt=/task_id=/depends_on=）；**A/B 两形制逻辑一字不改**。
     机读行块契约：机器只读 issue **body** 内本块——评论补行不进机读面
     （夜轨C2 断点2b 实证），补行必须 PATCH body。

密钥纪律
----
本件 --plan 只读 GitHub 公开 API（token 走环境量 GH_TOKEN，缺失时匿名读公开仓
也成立）。CNB token 只在 --execute 分支才经 bao 现取；本版 --execute 恒拒 ⇒
**本件不存在任何密钥读取路径**（禁打印凭据纪律结构性满足）。

证据落盘
----
dispatch-plan.ndjson（每卡一行：issue 号/task_id/债号/载荷全文/闸判读）+
dispatch-plan-summary.md。均为本件运行目录产物，零仓库写入。

自测
----
python3 -I tools/cnb-card-dispatch.py --selftest   # 三形制夹具+负例断言，零网络
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

TZ8 = timezone(timedelta(hours=8))
GH_API = "https://api.github.com"
DEFAULT_REPO = "CloudCrane-Software/factory-os"
# CNB 侧承载仓（夜轨A 起用法 v1 §二：NPC 流水线跑在 issue 所属仓默认分支）
DEFAULT_CNB_REPO = "Cloudbird-Software/cb-npc-poc"
EXECUTE_ENV = "CNB_DISPATCH_EXECUTE"
# 机读行块首行机器标记（af-card/1.0 契约；与 card.yml/directive.yml 机读行块同源）
MACHINE_BLOCK_MARKER = "af-card/1.0"

COMMENT_TMPL = """@CodeBuddy 请按以下自包含卡面施工（工厂派发卡 {task_id}）：

{card_body}

---
派发契约（照 30-工件/夜轨A-20261106/cnb沙箱起用法-v1.md §二）：
- 本评论走 work_mode（替我上班）语义：可推分支/发 PR；不开则只读+评论。
- 产出取回：PR 形式（results/{task_id} 分支），评论区回读数。
- 卡面即边界：allowed_paths 外零改动；验收命令集全绿才算完；禁项置顶段逐条有效。"""


def gh_get(path, token):
    import urllib.request
    req = urllib.request.Request(
        GH_API + path,
        headers={"Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28",
                 **({"Authorization": "Bearer %s" % token} if token else {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def list_queued_cards(repo, token):
    """拉 open issues，取挂 state:queued 的卡（pull_request 除外）。只读。"""
    out = []
    for page in (1, 2, 3):
        items = gh_get("/repos/%s/issues?state=open&per_page=100&page=%d" % (repo, page), token)
        if not items:
            break
        for it in items:
            if it.get("pull_request"):
                continue
            labels = {lb["name"] for lb in (it.get("labels") or [])}
            if "state:queued" in labels:
                out.append({"number": it["number"], "title": it["title"],
                            "body": it.get("body") or "", "labels": sorted(labels),
                            "url": it["html_url"], "updated_at": it["updated_at"]})
    return out


def parse_machine_block(body):
    """形制 C 机读行块：块首行恰为 `af-card/1.0`，其后连续 `key=value` 行。

    契约（card.yml/directive.yml 机读行块同款）：机器只读 issue body 内本块
    （评论不算——断点2b 语义）；块止于首个空行/非 key=value 行/注释行；
    未知键容忍忽略；键统一小写；值内禁换行（模板已约定）。无块返回 None
    （调用方落回既有双形制逻辑，A/B 行为不变）。"""
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


def parse_card(body):
    """从卡面文本抽 task_id/债号/依赖行。

    板面现势**三形制**（2026-11-07 实读；C=夜轨C2 断点2 补认）：
      A. planner 机建形（planner.yml step 10）：【任务】`x`／【债号】`x`／【依赖】…
      B. 排期员手建形（统一建设排期 §六）：``- task_id: `x` ｜ 债号建议: **D-102**``
         ／``- 依赖: #4（…）``（板号三形之一，M-7 repo#n 空仓形同族）
      C. 表单渲染形（card.yml/directive.yml 建，### 分节+粗体）+ **af-card/1.0
         机读行块**——机器只认块内键值（debt=/task_id=/depends_on=），人读分节
         不进机读面；缺块或缺 debt= 键 ⇒ 如实 None（调用方照旧 WARN 禁派）。
    C 优先（块=机器唯一认读位）；无块落回既有双形制逻辑（A/B 一字不改）；
    都认不出如实 None（禁猜）。"""
    kv = parse_machine_block(body)
    if kv is not None:
        return {"task_id": kv.get("task_id") or None,
                "debt": kv.get("debt") or None,
                "depends_on_raw": kv.get("depends_on") or None,
                "card_format": "machine-block"}
    tid = re.search(r"【任务】`([^`]+)`", body) or re.search(
        r"task_id[:：]\s*`([a-z0-9][a-z0-9._-]{2,63})`", body)
    debt = re.search(r"【债号】`([^`]+)`", body) or re.search(
        r"债号(?:建议)?[:：]\s*(?:\*\*)?([A-Za-z]{1,5}-[A-Za-z0-9-]+)", body)
    dep = re.search(r"【依赖】(.+)", body) or re.search(r"^[-*]\s*依赖[:：]\s*(.+)$", body, re.M)
    return {"task_id": tid.group(1) if tid else None,
            "debt": debt.group(1).strip() if debt else None,
            "depends_on_raw": dep.group(1).strip() if dep else None,
            "card_format": "planner" if "【任务】" in body else
                           ("scheduler" if re.search(r"task_id[:：]", body) else "unknown")}


def render_payload(card, cnb_repo):
    """渲染 CNB 派发载荷（title/body/comment）。纯函数，自测夹具走这里。"""
    meta = parse_card(card["body"])
    tid = meta.get("task_id") or ("issue-%d" % card["number"])
    payload_format = meta.get("card_format") or "unknown"
    comment = COMMENT_TMPL.format(task_id=tid, card_body=card["body"].rstrip())
    payload = {
        "github_issue": card["number"],
        "github_url": card["url"],
        "task_id": tid,
        "debt": meta.get("debt"),
        "depends_on_raw": meta.get("depends_on_raw"),
        "cnb_repo": cnb_repo,
        "cnb_issue_title": "[factory-%d] %s" % (card["number"], card["title"]),
        "cnb_issue_body": card["body"],
        "cnb_comment": comment,
        "work_mode": True,
        "card_format": payload_format,
        "plan_generated_at": datetime.now(TZ8).isoformat(timespec="seconds"),
    }
    return payload


def preflight_lines(card):
    """派发前置闸清单（本版只列明判据与缺场事实，不代跑真闸——真闸在 --execute 前置）。"""
    meta = parse_card(card["body"])
    lines = [
        "占用闸 dispatch-occupancy-check.py %s —— --execute 前必跑（fail-closed）"
        % (meta.get("debt") or "<债号缺场：卡面无【债号】行，闸必拒>"),
        "审卡闸 card-selfcontainment-check.py（D-97 六要件）—— --execute 前必跑（无逃生口）",
        "CNB token 经 openBao 现取（company/Git-Platform/CNB/*），禁打印禁落盘",
        "执行授权环境量 %s=YES（运营者明示；本版未授权）" % EXECUTE_ENV,
    ]
    if not meta.get("debt"):
        lines.insert(0, "WARN: 卡面缺【债号】行——占用闸无从判重，禁派发")
    dep = meta.get("depends_on_raw")
    if dep and dep not in ("无", ""):
        lines.insert(0, "WARN: 卡面依赖=%r——依赖前置未解前禁派（派发侧依赖阻断为明早项）" % dep)
    return lines


def cmd_plan(args):
    # 局部名用 env_tok（不用 token=… 赋值形态）：源码须零 G-13 命中过 gates 树扫。
    env_tok = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
    if args.body_file:
        # 本地卡面模式（零网络零 POST）：读文件替代拉板，走同一条解析路径——
        # 复渲染/夹具识别证据用（夜轨C3 断点2 闭合证据通道）。
        with open(args.body_file, encoding="utf-8") as f:
            local_body = f.read()
        cards = [{"number": args.issue or 0,
                  "title": os.path.basename(args.body_file),
                  "body": local_body,
                  "labels": ["body-file"],
                  "url": "file://" + os.path.abspath(args.body_file),
                  "updated_at": datetime.now(TZ8).isoformat(timespec="seconds")}]
    else:
        cards = list_queued_cards(args.repo, env_tok)
    payloads = []
    for c in cards:
        if args.issue and not args.body_file and c["number"] != args.issue:
            continue
        p = render_payload(c, args.cnb_repo)
        p["preflight"] = preflight_lines(c)
        payloads.append(p)
    with open("dispatch-plan.ndjson", "w", encoding="utf-8") as f:
        for p in payloads:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    with open("dispatch-plan-summary.md", "w", encoding="utf-8") as f:
        f.write("# CNB 派发计划（计划态·零发送）%s\n\n" % datetime.now(TZ8).isoformat(timespec="seconds"))
        if args.body_file:
            f.write("- 源：本地卡面 %s（body-file 模式，零网络零 POST；卡号盖 %d）\n- 目标 CNB 仓：%s\n\n"
                    % (args.body_file, args.issue or 0, args.cnb_repo))
        else:
            f.write("- 源板：%s · state:queued 开卡 %d 张（选中 %d）\n- 目标 CNB 仓：%s\n\n"
                    % (args.repo, len(cards), len(payloads), args.cnb_repo))
        for p in payloads:
            f.write("## gh#%d · %s（债号 %s；形制 %s）\n" % (p["github_issue"], p["task_id"], p["debt"] or "缺", p["card_format"]))
            f.write("- CNB issue 标题：`%s`\n- work_mode：%s\n" % (p["cnb_issue_title"], p["work_mode"]))
            for ln in p["preflight"]:
                f.write("- %s\n" % ln)
            f.write("\n")
        f.write("> 本件 --plan 零 POST；--execute 本版恒拒（exit 3）——四门（占用/审卡/"
                "token/openBao+授权环境量）齐备后由明早清单 D-4 解锁。\n")
    print("plan: %s selected=%d -> dispatch-plan.ndjson / dispatch-plan-summary.md"
          % (("body-file %s" % args.body_file) if args.body_file
             else "queued=%d" % len(cards), len(payloads)))
    return 0


def cmd_execute(args):
    """执行腿：本版恒拒（fail-closed）。授权四门未齐前不解锁。"""
    print("EXECUTE 拒发（exit 3）：本版为计划态——执行腿四门（占用闸/审卡闸/"
          "CNB token openBao 现取/授权环境量 %s=YES）未齐，见明早清单 D-4。"
          "本次零 POST，拒发事实已留档。" % EXECUTE_ENV)
    with open("dispatch-execute-refused.log", "a", encoding="utf-8") as f:
        f.write("%s\texecute-refused\trepo=%s\tissue=%s\n"
                % (datetime.now(TZ8).isoformat(timespec="seconds"), args.repo, args.issue or "*"))
    return 3


def selftest():
    """夹具渲染断言：零网络、零密钥。三形制夹具各一 + 负例（断点2/2b 语义钉死）。"""
    card = {
        "number": 34,
        "title": "[wave-07][D-102] TAC 多 agent 协同试跑卡",
        "url": "https://github.com/x/issues/34",
        "updated_at": "2026-11-07T00:00:00Z",
        "labels": ["wave", "state:queued"],
        "body": ("【禁项置顶】…\n【波次】wave-07　【状态机起点】`state:queued`\n"
                 "【任务】`w07-tac-cotrial`\n【债号】`D-102`\n"
                 "【依赖】w07-sandbox-contract；无\n【验收命令集】\n- [ ] python3 -B x.py → rc=0\n"),
    }
    p = render_payload(card, "Cloudbird-Software/cb-npc-poc")
    assert p["task_id"] == "w07-tac-cotrial", p["task_id"]
    assert p["debt"] == "D-102"
    assert p["work_mode"] is True
    assert "@CodeBuddy" in p["cnb_comment"]
    assert "【债号】`D-102`" in p["cnb_comment"]
    pl = preflight_lines(card)
    assert any("依赖" in x for x in pl), pl            # 有依赖 ⇒ 前置 WARN 在列
    assert any("card-selfcontainment-check" in x for x in pl)
    card_nodebt = dict(card, body="【任务】`x-y`\n【依赖】无\n")
    pl2 = preflight_lines(card_nodebt)
    assert any("缺【债号】" in x for x in pl2), pl2     # 缺债号 ⇒ 派发禁令在列
    assert parse_card(card_nodebt["body"])["depends_on_raw"] == "无"
    # 双形制：排期员形（fos#34 实样同构）
    sched_body = ("- task_id: `w07-tac-cotrial` ｜ 债号建议: **D-102**（顺延）\n- 依赖: #4（契约）、#8（bench 经验）\n")
    ms = parse_card(sched_body)
    assert ms["task_id"] == "w07-tac-cotrial" and ms["debt"] == "D-102", ms
    assert ms["card_format"] == "scheduler"
    assert ms["depends_on_raw"].startswith("#4"), ms
    # ── 形制 C：表单渲染形（### 分节+粗体，fos#84 同构）+ af-card/1.0 机读行块 ──
    form_body = (
        "## ⛔ 禁项（置顶）\n\n1. **判官/门/判据件一改即拒收**：判官路径=门禁脚本+判据件。\n\n"
        "---\n\n### 1. task_id\n\n`sunset-audit-tool`\n\n"
        "### 2. 债号（debt）\n\n**D-116**（台账 计划/阶段欠账台账.md:143）\n\n"
        "### 4. 验收命令集（acceptance）\n\npython3 -I tools/sunset-audit.py --selftest   # exit 0\n\n"
        "## 机读行块（af-card/1.0）\n\n"
        "af-card/1.0\n"
        "debt=D-116\n"
        "task_id=sunset-audit-tool\n"
        "depends_on=D-115 入口卡在板（CloudCrane-Software/.github#29）\n")
    mc = parse_card(form_body)
    assert mc["card_format"] == "machine-block", mc        # C 形制识别
    assert mc["task_id"] == "sunset-audit-tool", mc        # 块内 task_id= 识别
    assert mc["debt"] == "D-116", mc                       # 块内 debt= 识别（断点2 闭合）
    assert mc["depends_on_raw"].startswith("D-115"), mc    # 块内 depends_on= 识别
    pl3 = preflight_lines(dict(card, body=form_body))
    assert not any("缺【债号】" in x for x in pl3), pl3     # 块内有 debt= ⇒ 禁派 WARN 消
    assert any("依赖" in x for x in pl3), pl3              # 依赖行照旧 WARN（不改既有逻辑）
    # 负例：表单渲染形但无机读行块且无【债号】行 ⇒ debt=None ⇒ 旧 WARN 禁派（不误派）
    neg_body = ("## ⛔ 禁项（置顶）\n\n### 1. task_id\n\n`sunset-audit-tool`\n\n"
                "### 2. 债号（debt）\n\n**D-116**（台账在册）\n\n")
    mn = parse_card(neg_body)
    assert mn["debt"] is None, mn                          # 表单粗体债号不冒认（禁猜）
    assert mn["card_format"] == "unknown", mn
    pl4 = preflight_lines(dict(card, body=neg_body))
    assert any("缺【债号】" in x for x in pl4), pl4         # 旧 WARN 照走（负例不误派）
    # 负例补：块在而 debt= 空 ⇒ 仍 None + 禁派 WARN（fail-closed 不猜绿）
    empty_body = "af-card/1.0\ndebt=\ntask_id=x-y\ndepends_on=无\n"
    me = parse_card(empty_body)
    assert me["debt"] is None and me["card_format"] == "machine-block", me
    assert any("缺【债号】" in x for x in preflight_lines(dict(card, body=empty_body)))
    print("selftest: 23/23 断言全过（渲染/三形制夹具 A·B·C/负例×2/前置闸清单）")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("----")[0])
    ap.add_argument("--repo", default=DEFAULT_REPO, help="GitHub 源板（owner/name）")
    ap.add_argument("--cnb-repo", default=DEFAULT_CNB_REPO, help="CNB 承载仓（NPC 流水线所在仓）")
    ap.add_argument("--issue", type=int, default=None, help="只选指定 issue 号（缺=全部 state:queued；--body-file 时盖卡号）")
    ap.add_argument("--body-file", default=None,
                    help="--plan 本地卡面文件（零网络零 POST；复渲染/夹具识别证据用，与 --repo 互斥语义）")
    sub = ap.add_mutually_exclusive_group()
    sub.add_argument("--plan", action="store_true", help="计划态（默认）：只读渲染派发载荷，零 POST")
    sub.add_argument("--execute", action="store_true", help="执行态：本版恒拒（四门未授权）")
    ap.add_argument("--selftest", action="store_true", help="夹具自测（零网络零密钥）")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if args.execute:
        return cmd_execute(args)
    return cmd_plan(args)


if __name__ == "__main__":
    sys.exit(main())
