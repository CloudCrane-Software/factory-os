#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""af-perm-request-check.py — 消费端白名单机检器（af-perm-request 围栏，两层审批 fail-closed）。

出处（factory-os#27 卡面补漏补面评论 2026-11-06 排期补漏员落档；沙箱研究 §二 B-8
后半夜消费端 harness 白名单机检 + §三 同构-9；R-3 两层审批 fail-closed；
协议文本半边 = factory-os#18 → 波次清单/沙箱派发契约.md §7.5② af-perm-request）：
  · 白名单内自动批（rc=0，verdict=approve）；白名单外一律转人工（rc=1，
    verdict=manual，不批）；判官路径目标永远不批（rc=2，verdict=reject——协议
    「不受理项」面原文：判官面/门禁件/判据件的改权永远不在受理项内）。
  · 与 tools/resource-ticket-check.py 共用 fail-closed 骨架（同构-9 明示；
    import 复用零拷贝）：任一输入面不可读/不可解析/字段缺失/词表外 ⇒ reject
    fail-closed 不猜绿。任务面检查（在飞+身份一致）同款共用。
  · 板面纪律（R-5）：token/口令值永不上板面，板面只承载批准事实（指纹
    sha256[:12]＋时窗）；本件零网络零凭据正文，只做申请面判定。

白名单 v1（本文件即登记处，改面须同批登记依据）：
  · scope_ask 逐项枚举（R-2：禁「更多权限」式泛求），每项形
      <动词面>:<读|写>=<owner>/<repo>
    动词面 ∈ {repo, contents, issues, pull_requests, actions, workflows}
  · 自动批面 = 全部项均为读且目标仓属 CloudCrane-Software（跨仓只读白名单）
  · 转人工面 = 白名单外（写类/词表外动词面/目标仓不属本 org/泛求不可解析）
  · 永不批面 = 判官路径目标：任何 workflows 面（门禁件改权），或目标仓为
    CloudCrane-Software/factory-os 的任何写类（factory-os tools/账本/门面
    全族判官锁，CODEOWNERS §1/§2），或任何 scope 项锚定判官路径段
    （:path 锚定 .github/workflows、tools/、账本/、CODEOWNERS、门/判据件名）
  · ttl_ask ≤ 1h/次（协议原文）；超上限 ⇒ 转人工
  · request_id 形 <卡号>-p<序号>（^\\d+-p\\d+$）；泛求/形态外 ⇒ 转人工
  · task_ref 必须在飞 + requester 与卡在飞身份一致（共用骨架·任务面检查）

用法：
  python3 tools/af-perm-request-check.py --request REQ.json \
      --tasks TASKS.json
  python3 tools/af-perm-request-check.py --selftest

输入面（机器形 JSON）：
  --request af.perm-request.v1：
    {"schema":"af.perm-request.v1","request_id":"27-p1",
     "scope_ask":["repo:read=CloudCrane-Software/af"],
     "why":"<卡面哪一条挡住了我>","ttl_ask":"1h",
     "artifact_needed":"<批准后第一个可判定动作>",
     "task_ref":"factory-os#27","requester":"<在飞身份>"}
  --tasks  af.task-snapshot.v1（同 resource-ticket-check 的快照形）

退出码：0=approve（白名单内自动批）；1=manual（转人工，不批）；
2=reject（判官路径永不批 / fail-closed 不猜绿）。
"""
import argparse
import importlib.util
import json
import os
import re
import sys

# 共用 fail-closed 骨架（同构-9）：从 tools/resource-ticket-check.py（文件名含连
# 字符，不能按名 import）以 importlib 载入——仓内既有同形先例见
# tools/portal-seeder.py:416（spec_from_file_location 载 card-lint.py）。
_SKELETON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resource-ticket-check.py")
_spec = importlib.util.spec_from_file_location("resource_ticket_check", _SKELETON)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
RC_APPROVE = _mod.RC_APPROVE
RC_MANUAL = _mod.RC_MANUAL
RC_REJECT = _mod.RC_REJECT
REQUEST_SCHEMA = _mod.REQUEST_SCHEMA
TASKS_SCHEMA = _mod.TASKS_SCHEMA
FailClosed = _mod.FailClosed
Verdict = _mod.Verdict
load_json_strict = _mod.load_json_strict
require = _mod.require
parse_ttl_seconds = _mod.parse_ttl_seconds
parse_task_ref = _mod.parse_task_ref
task_face_check = _mod.task_face_check

PERM_SCHEMA = "af.perm-request.v1"
MAX_TTL_S = 3600  # 协议原文：上限仍 1h/次
ORG = "CloudCrane-Software"
JUDGE_REPO = ORG + "/factory-os"

VERB_FACES = ("repo", "contents", "issues", "pull_requests", "actions", "workflows")
# 判官路径段锚（scope 项锚定到这些段 ⇒ 永不批；对应 CODEOWNERS §1/§2 判官锁面）
JUDGE_PATH_MARKERS = (".github/workflows", "tools/", "账本/", "codeowners",
                      "gates.yml", "planner.yml", "redteam-scan.yml", "波次清单/沙箱派发契约.md")

# scope 项形态：<face>:<rw>=<owner>/<repo>[:path=<seg>]
# 逐项枚举；「更多权限」式泛求（all/admin/*、成句文本、缺仓段）⇒ 解析不过 ⇒ 转人工
SCOPE_RE = re.compile(
    r"^([a-z_]+):(read|write)=([A-Za-z0-9][A-Za-z0-9._-]{0,62})/([A-Za-z0-9][A-Za-z0-9._-]{0,62})"
    r"(:path=[A-Za-z0-9._/-]{1,120})?$"
)


def parse_scope_item(item, what):
    """单 scope 项解析 ⇒ (face, rw, owner, repo, path)；泛求/形态外 ⇒ FailClosed？

    不：泛求按 R-2 是「转人工」面不是 fail-closed 面——逐项枚举缺失 ⇒ 转人工；
    只有非字符串/空列表这类结构面崩坏才 fail-closed。这里用返回 None 表泛求。
    """
    if not isinstance(item, str) or len(item) > 200:
        return None
    m = SCOPE_RE.match(item)
    if not m:
        return None
    face, rw, owner, repo, path = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5) or ""
    return {"face": face, "rw": rw, "target": "%s/%s" % (owner, repo),
            "path": path[6:] if path else ""}  # 剥 ":path=" 前缀


def judge_path_target(parsed):
    """判官路径目标判定（协议不受理项面）：命中 ⇒ 永不批。"""
    if parsed["face"] == "workflows":
        return "workflows 面=门禁件改权（.github/workflows/** 判官锁）"
    if parsed["target"] == JUDGE_REPO and parsed["rw"] == "write":
        return "%s 写类=判官/账本/门面全族锁（CODEOWNERS §1/§2）" % JUDGE_REPO
    if parsed["path"]:
        low = parsed["path"].lower()
        for mk in JUDGE_PATH_MARKERS:
            if mk.lower() in low:
                return "scope 锚定判官路径段: %s" % parsed["path"]
    return None


def check_perm_request(request, snapshot):
    v = Verdict()
    if request.get("schema") != PERM_SCHEMA:
        raise FailClosed("请求 schema 非 %s: %r" % (PERM_SCHEMA, request.get("schema")))
    if snapshot.get("schema") != TASKS_SCHEMA:
        raise FailClosed("任务快照 schema 非 %s: %r" % (TASKS_SCHEMA, snapshot.get("schema")))

    rid = require(request, "request_id", "申请面")
    if not re.match(r"^\d{1,7}-p\d{1,4}$", rid):
        v.add("request_id 形 <卡号>-p<序号>", False, "形态外: %r（转人工）" % rid)
    else:
        v.add("request_id 形 <卡号>-p<序号>", True, rid)

    task_ref = parse_task_ref(require(request, "task_ref", "申请面"), "申请面")
    requester = require(request, "requester", "申请面")
    require(request, "why", "申请面")
    require(request, "artifact_needed", "申请面")
    ttl_s = parse_ttl_seconds(require(request, "ttl_ask", "申请面"), "申请面")
    v.add("ttl_ask≤1h/次", ttl_s <= MAX_TTL_S,
          "ttl_ask=%ds（上限 %ds，协议原文）" % (ttl_s, MAX_TTL_S))

    # 任务面：在飞 + 身份一致（共用骨架；无在飞 task_ref ⇒ 转人工）
    task_face_check(snapshot, task_ref, requester, v)

    scope = request.get("scope_ask")
    if not isinstance(scope, list) or not scope:
        raise FailClosed("scope_ask 缺失或非非空数组（逐项枚举面崩坏）")

    parsed_items = []
    for i, item in enumerate(scope, 1):
        p = parse_scope_item(item, "申请面")
        if p is None:
            v.add("scope逐项枚举(第%d项)" % i, False,
                  "泛求/形态外不可解析: %r（R-2 禁「更多权限」式泛求 ⇒ 转人工）" % (item,))
            parsed_items.append(None)
            continue
        parsed_items.append(p)

    hard_judge = None
    whitelist_all = True
    for i, p in enumerate(parsed_items, 1):
        if p is None:
            whitelist_all = False
            continue
        if p["face"] not in VERB_FACES:
            v.add("scope动词面词表(第%d项)" % i, False,
                  "face %r 词表外（可 %s）⇒ 转人工" % (p["face"], list(VERB_FACES)))
            whitelist_all = False
            continue
        jp = judge_path_target(p)
        if jp:
            hard_judge = jp
        if p["rw"] != "read" or not p["target"].startswith(ORG + "/"):
            v.add("白名单面(第%d项)" % i, False,
                  "%s:%s=%s 白名单外（v1 白名单=读类×本 org 跨仓）⇒ 转人工" % (p["face"], p["rw"], p["target"]))
            whitelist_all = False
        else:
            v.add("白名单面(第%d项)" % i, True,
                  "%s:%s=%s 在白名单内" % (p["face"], p["rw"], p["target"]))

    if hard_judge:
        # 判官路径目标 ⇒ 永不批（协议不受理项面原文；不走转人工，直接 reject）
        v.reject("判官路径目标永不批：%s（不受理项；改权走判据变更正路）" % hard_judge)
    return v


def selftest():
    """内嵌夹具自测（零网络）：判别力矩阵逐例断言。"""
    cases = []
    base_req = {
        "schema": PERM_SCHEMA, "request_id": "27-p1",
        "scope_ask": ["repo:read=CloudCrane-Software/af"],
        "why": "fixture", "ttl_ask": "1h", "artifact_needed": "fixture",
        "task_ref": "factory-os#27", "requester": "worker-a",
    }
    base_tasks = {"schema": TASKS_SCHEMA, "generated_at": "2026-11-06T00:00:00Z",
                  "source": "fixture",
                  "tasks": [{"task_ref": "factory-os#27", "state": "running",
                             "inflight_identity": "worker-a"}]}

    def run(req, tasks=base_tasks):
        try:
            return check_perm_request(req, tasks).render()
        except FailClosed as e:
            v = Verdict()
            v.reject(str(e))
            return v.render()

    r = run(base_req)
    cases.append(("approve-白名单内只读", r["verdict"] == "approve" and r["issued"] is True))
    # 负例族（转人工 ⇒ 必不批）
    r = run(dict(base_req, scope_ask=["更多权限全部仓库管理"]))
    cases.append(("负例-泛求非逐项枚举", r["verdict"] == "manual" and not r["issued"]))
    r = run(dict(base_req, scope_ask=["repo:write=CloudCrane-Software/af"]))
    cases.append(("负例-白名单外写类", r["verdict"] == "manual" and not r["issued"]))
    r = run(dict(base_req, requester="worker-b"))
    cases.append(("负例-requester与卡在飞身份不一致", r["verdict"] == "manual" and not r["issued"]))
    r = run(dict(base_req, task_ref="factory-os#999"))
    cases.append(("负例-无在飞task_ref", r["verdict"] == "manual" and not r["issued"]))
    r = run(dict(base_req, ttl_ask="8h"))
    cases.append(("负例-ttl超1h上限", r["verdict"] == "manual" and not r["issued"]))
    # 永不批族（判官路径 ⇒ reject）
    r = run(dict(base_req, scope_ask=["workflows:write=CloudCrane-Software/af"]))
    cases.append(("永不批-判官路径workflows面", r["verdict"] == "reject" and not r["issued"]))
    r = run(dict(base_req, scope_ask=["repo:write=CloudCrane-Software/factory-os"]))
    cases.append(("永不批-factory-os写类", r["verdict"] == "reject" and not r["issued"]))
    r = run(dict(base_req, scope_ask=["repo:read=CloudCrane-Software/af:path=tools/gates.yml"]))
    cases.append(("永不批-判官路径段锚定", r["verdict"] == "reject" and not r["issued"]))
    # fail-closed 族
    r = run(dict(base_req, schema="af.perm-request.v0"))
    cases.append(("failclosed-schema面外", r["verdict"] == "reject"))
    r = run({k: v for k, v in base_req.items() if k != "scope_ask"})
    cases.append(("failclosed-缺scope_ask", r["verdict"] == "reject"))
    r = run(dict(base_req, task_ref="garbage ref"))
    cases.append(("failclosed-task_ref解析失败", r["verdict"] == "reject"))

    bad = [(n, ok) for n, ok in cases if not ok]
    for n, ok in cases:
        print("  [%s] %s" % ("PASS" if ok else "FAIL", n))
    print("selftest %d/%d 过" % (len(cases) - len(bad), len(cases)))
    return 0 if not bad else 1


def main():
    ap = argparse.ArgumentParser(description="af-perm-request 消费端白名单机检器（fail-closed，D-94 补录）")
    ap.add_argument("--request", help="af-perm-request 机器形 JSON 文件（af.perm-request.v1）")
    ap.add_argument("--tasks", help="在飞任务快照 JSON 文件（af.task-snapshot.v1）")
    ap.add_argument("--now", help="ISO8601 现时刻覆盖（仅自测/复核用）")
    ap.add_argument("--selftest", action="store_true", help="内嵌夹具自测（零网络）")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(selftest())
    if not a.request or not a.tasks:
        ap.error("实跑需 --request 与 --tasks（自测用 --selftest）")
    try:
        request = load_json_strict(a.request, "申请面")
        snapshot = load_json_strict(a.tasks, "任务快照")
        v = check_perm_request(request, snapshot)
    except FailClosed as e:
        v = Verdict()
        v.reject(str(e))
    out = v.render()
    print(json.dumps(out, ensure_ascii=False, indent=1))
    sys.exit(RC_APPROVE if out["verdict"] == "approve" else
             (RC_MANUAL if out["verdict"] == "manual" else RC_REJECT))


if __name__ == "__main__":
    main()
