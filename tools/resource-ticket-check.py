#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""resource-ticket-check.py — 资源票据发放机检器（五条机检，fail-closed）。

出处（factory-os#27 [wave-06][D-94] 卡面 + 波次清单/沙箱派发契约.md §7.5③
TICKET-REQUEST v1 + D-11 上限 v1 裁定（Q6 §3.1 起步值））：
  · 五条机检全过 ⇒ 自动批（rc=0，verdict=approve）；任一不过 ⇒ 转人工
    （rc=1，verdict=manual，票据不发）；账本/快照/请求面任一不可读或解析失败
    ⇒ 拒发不猜绿（rc=2，verdict=reject，fail-closed）。
  · 五条（卡面原文序，逐字）：
      ① task_ref 在飞且身份一致
      ② amount ≤ 单票上限（D-11 Q6 §3.1 起步值：单票 ≤200 req / 20M input tokens）
      ③ 名下在飞总额 ≤ 每沙箱上限（起步值 ≤500 req/日，UTC 日界）
      ④ 当日全局 ≤ 每日上限（起步值 ≤1000 req/日 = 2×每沙箱；v1 显式声明值，
         D-11 未另行裁定前的保守派生上界——本行即登记处，不许静默改值）
      ⑤ 无停用 hold（账本内 scope 命中 requester/task_ref 的在押 hold 行）
  · 三元绑定（task_ref × consumer × key 指纹）发放时一次写死；账本 append-only，
    key 值永不入账本——只入指纹 sha256[:12]（D-46 第四次同型事故纪律）。
  · 票据不携带密码学权力：回收=摘服务端登记行即断；本件只做发放侧判定，
    不做回收（回收由 gov 面摘消费者行 + 账本 revoke 行完成）。
  · 判官路径永不批票（协议显式不受理项）；GPU 直通永不（本件只受理
    llm-gw / video-gw 类；gpu-anolis 见即 reject——TICKET-REQUEST v1 枚举里有
    该字面值，但 D-94 卡面明文「GPU 直通永不（本卡只 LLM 票）」）。

共用骨架（同构-9：TICKET-REQUEST 与 af-perm-request 机检共用 fail-closed 骨架）：
  load_jsonl_strict / load_json_strict / require / Verdict / 退出码常量 /
  task-face 检查（在飞+身份一致）由本件定义，af-perm-request-check.py
  直接 import 复用（零拷贝派生）。骨架语义：
    · 任一输入面缺失/不可读/不可解析/字段缺失 ⇒ FailClosed ⇒ verdict=reject rc=2
    · 未知枚举值（ticket_type / task state / 资源族）⇒ FailClosed（不猜绿）

用法：
  python3 tools/resource-ticket-check.py --request REQ.json \
      --tasks TASKS.json [--ledger 账本/resource-ledger.jsonl] [--now ISO8601]
  python3 tools/resource-ticket-check.py --selftest

输入面（机器形，均 JSON）：
  --request  af.ticket-request.v1：
    {"schema":"af.ticket-request.v1","ticket_type":"llm-gw","task_ref":"factory-os#27",
     "resource":"llm:glm-plan","amount":{"max_req":N,"max_input_tokens":M},
     "ttl_ask":"6h","requester":"<在飞身份>","purpose":"<一句话，写进账本>"}
  --tasks    af.task-snapshot.v1（治理面在飞快照；本件零网络，快照由 harness
    经 GitHub API 生成后投喂；快照源与生成命令随读数登记）：
    {"schema":"af.task-snapshot.v1","generated_at":"...","source":"github-api",
     "tasks":[{"task_ref":"factory-os#27","state":"running","inflight_identity":"..."}]}
  --ledger   af.resource-ledger.v1（append-only jsonl；行族：ledger-open/issue/
    meter/revoke/hold/reject——字段见账本首行 schema 行）

退出码：0=approve（可自动发放）；1=manual（转人工，票据不发）；2=reject
（fail-closed 拒发不猜绿）。本件零网络、零凭据正文、只读两输入面。
"""
import argparse
import datetime as dt
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_LEDGER = os.path.join(ROOT, "账本", "resource-ledger.jsonl")

# ---- 共用骨架：退出码 / verdict 词表 --------------------------------------
RC_APPROVE = 0
RC_MANUAL = 1
RC_REJECT = 2  # fail-closed 拒发不猜绿

# ---- D-11 上限 v1 起步值（Q6 §3.1；改值须 D-11 裁定并同步登记本声明行） ----
# （20000000 故意不写下划线分隔：bot-scrub G-13 线性内核对「词干=非纯数字值」
#   命中，纯数字字面量在其数字值豁免前瞻内——写 20_000_000 会误红，见本行注）
PER_TICKET_MAX_REQ = 200
PER_TICKET_MAX_INPUT_TOKENS = 20000000
PER_SANDBOX_DAILY_REQ = 500
GLOBAL_DAILY_REQ = 1000          # v1 显式声明值（=2×每沙箱保守派生上界）
MAX_TTL_SECONDS = {"llm-gw": 6 * 3600, "video-gw": 6 * 3600, "gpu-anolis": 4 * 3600}
ALLOWED_TICKET_TYPES = ("llm-gw", "video-gw")   # gpu-anolis：GPU 直通永不，见即 reject

# ---- task_ref / ttl / 资源族形态（白名单正则；解析失败 ⇒ fail-closed） ----
TASK_REF_ISSUE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}#\d{1,7}$")   # owner/repo#N 或 repo#N
TASK_REF_RT_RE = re.compile(r"^RT-E\d{1,5}$")
TTL_RE = re.compile(r"^([0-9]{1,5})([smh])$")
RESOURCE_RE = re.compile(r"^(llm|video):[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600}

REQUEST_SCHEMA = "af.ticket-request.v1"
TASKS_SCHEMA = "af.task-snapshot.v1"
LEDGER_SCHEMA = "af.resource-ledger.v1"

# 在飞态词表（任务快照 state；词表外 ⇒ fail-closed，同 dispatch-occupancy-check 口径）
TASK_INFLIGHT_STATES = {"running"}
TASK_KNOWN_STATES = {"queued", "running", "merged", "rejected", "blocked"}

ISSUE_EVENT = "issue"
METER_EVENT = "meter"
REVOKE_EVENT = "revoke"
HOLD_EVENT = "hold"
KNOWN_LEDGER_EVENTS = {ISSUE_EVENT, METER_EVENT, REVOKE_EVENT, HOLD_EVENT, "reject", "ledger-open"}

# 账本行必需字段（缺 ⇒ 该行不可解析 ⇒ fail-closed）
LEDGER_REQUIRED = {
    "ledger-open": {"ts", "event", "schema"},
    ISSUE_EVENT: {"ts", "event", "ticket_id", "task_ref", "requester", "consumer",
                  "key_fp", "amount", "ttl_s", "expires_at"},
    METER_EVENT: {"ts", "event", "ticket_id", "req_delta", "input_tokens"},
    REVOKE_EVENT: {"ts", "event", "ticket_id", "reason"},
    HOLD_EVENT: {"ts", "event", "scope", "target", "reason"},
    "reject": {"ts", "event", "reasons"},
}


class FailClosed(Exception):
    """任一输入面不可证 ⇒ fail-closed 拒发不猜绿（rc=2）。"""


# ---------------------------------------------------------------- 共用骨架

def load_json_strict(path, what):
    """读单件 JSON；缺失/不可读/不可解析 ⇒ FailClosed（fail-closed）。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        raise FailClosed("%s 不可读: %s (%s)" % (what, path, e.__class__.__name__))
    try:
        obj = json.loads(text)
    except ValueError as e:
        raise FailClosed("%s 不可解析: %s (%s)" % (what, path, e.__class__.__name__))
    if not isinstance(obj, dict):
        raise FailClosed("%s 顶层非对象: %s" % (what, path))
    return obj


def load_jsonl_strict(path, what):
    """读 append-only jsonl；逐行必须 JSON 对象，空行忽略；任一行坏 ⇒ FailClosed。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError as e:
        raise FailClosed("%s 不可读: %s (%s)" % (what, path, e.__class__.__name__))
    rows = []
    for i, raw in enumerate(lines, 1):
        s = raw.strip()
        if not s:
            continue
        try:
            obj = json.loads(s)
        except ValueError as e:
            raise FailClosed("%s 第 %d 行不可解析 (%s)" % (what, i, e.__class__.__name__))
        if not isinstance(obj, dict):
            raise FailClosed("%s 第 %d 行非对象" % (what, i))
        rows.append(obj)
    return rows


def require(obj, field, what):
    """字段存在且非空；缺 ⇒ FailClosed（不猜绿）。"""
    v = obj.get(field)
    if v is None or (isinstance(v, str) and not v.strip()):
        raise FailClosed("%s 缺必填字段 %s" % (what, field))
    return v


def parse_iso_ts(s, what):
    try:
        return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    except (ValueError, TypeError):
        raise FailClosed("%s 时间戳非 %Y-%m-%dT%H:%M:%SZ 形: %r" % (what, s))


def parse_ttl_seconds(ttl, what):
    m = TTL_RE.match(ttl if isinstance(ttl, str) else "")
    if not m:
        raise FailClosed("%s ttl_ask 形态非法（如 6h/30m）: %r" % (what, ttl))
    n = int(m.group(1))
    sec = n * UNIT_SECONDS[m.group(2)]
    return sec


def parse_task_ref(task_ref, what):
    """task_ref 白名单形态；两形之外 ⇒ FailClosed（解析失败拒发，契约 §7.5③ 原文）。"""
    if not isinstance(task_ref, str):
        raise FailClosed("%s task_ref 非字符串" % what)
    if TASK_REF_ISSUE_RE.match(task_ref) or TASK_REF_RT_RE.match(task_ref):
        return task_ref
    raise FailClosed("%s task_ref 解析失败（不在 issue#/RT-E\\d+ 两形内）: %r" % (what, task_ref))


def utc_day(ts):
    return ts.astimezone(dt.timezone.utc).strftime("%Y-%m-%d")


class Verdict(object):
    """判定书：checks 明细 + reasons；issued 恒由 verdict 派生（approve 才发）。"""

    def __init__(self):
        self.checks = []
        self.fail_closed = None

    def add(self, name, passed, detail):
        self.checks.append({"name": name, "pass": bool(passed), "detail": detail})

    def reject(self, why):
        self.fail_closed = why

    def render(self):
        if self.fail_closed is not None:
            return {"verdict": "reject", "issued": False,
                    "fail_closed": self.fail_closed, "checks": self.checks}
        ok = all(c["pass"] for c in self.checks)
        return {"verdict": "approve" if ok else "manual", "issued": ok,
                "reasons": [c["detail"] for c in self.checks if not c["pass"]],
                "checks": self.checks}


def task_face_check(snapshot, task_ref, requester, verdict):
    """共用骨架·任务面检查：在飞 + 身份一致（两件机检共用）。"""
    tasks = snapshot.get("tasks")
    if not isinstance(tasks, list):
        raise FailClosed("任务快照 tasks 非数组")
    hit = None
    for t in tasks:
        if not isinstance(t, dict):
            raise FailClosed("任务快照存在非对象条目")
        if t.get("task_ref") == task_ref:
            hit = t
            break
    if hit is None:
        verdict.add("① task_ref 在飞且身份一致", False,
                    "task_ref %s 不在在飞快照内（无任务不发票据）" % task_ref)
        return
    state = hit.get("state")
    if state not in TASK_KNOWN_STATES:
        raise FailClosed("任务快照 state 词表外: %r（不可证 ⇒ fail-closed）" % (state,))
    ident = require(hit, "inflight_identity", "任务快照条目(%s)" % task_ref)
    if state not in TASK_INFLIGHT_STATES:
        verdict.add("① task_ref 在飞且身份一致", False,
                    "task_ref %s state=%s 非在飞（在飞词表 %s）" % (task_ref, state, sorted(TASK_INFLIGHT_STATES)))
    elif ident != requester:
        verdict.add("① task_ref 在飞且身份一致", False,
                    "requester %r 与卡在飞身份 %r 不一致" % (requester, ident))
    else:
        verdict.add("① task_ref 在飞且身份一致", True,
                    "task_ref %s state=running 身份一致 %s" % (task_ref, ident))


# ---------------------------------------------------------------- 账本面

def scan_ledger(rows, now_ts, requester, task_ref):
    """从账本行聚合：名下在飞票当日已批 req 总额 / 全局当日 / 在押 hold 面。

    任一 issue 行缺必需字段 ⇒ FailClosed（账本不可解析 ⇒ 拒发，卡面原文）。
    """
    sandbox_today = 0
    global_today = 0
    holds = []
    for i, r in enumerate(rows, 1):
        ev = r.get("event")
        if ev not in KNOWN_LEDGER_EVENTS:
            raise FailClosed("账本第 %d 行 event 词表外: %r" % (i, ev))
        missing = LEDGER_REQUIRED[ev] - set(r.keys())
        if missing:
            raise FailClosed("账本第 %d 行 %s 缺字段 %s" % (i, ev, sorted(missing)))
        ts = parse_iso_ts(r["ts"], "账本第 %d 行" % i)
        if ev == ISSUE_EVENT:
            am = r.get("amount") if isinstance(r.get("amount"), dict) else {}
            mr = am.get("max_req")
            if not isinstance(mr, int) or isinstance(mr, bool):
                raise FailClosed("账本第 %d 行 issue amount.max_req 非整数" % i)
            if utc_day(ts) == utc_day(now_ts):
                global_today += mr
                if r.get("requester") == requester:
                    sandbox_today += mr
        elif ev == HOLD_EVENT:
            holds.append(r)
    return {"sandbox_today": sandbox_today, "global_today": global_today, "holds": holds}


def hold_hit(holds, requester, task_ref):
    """⑤ 无停用 hold：scope=requester/task 命中即在押（hold 行无解除行 ⇒ 在押）。"""
    for h in holds:
        scope, target = h.get("scope"), h.get("target")
        if scope == "requester" and target == requester:
            return "%s（scope=requester）" % target
        if scope == "task" and target == task_ref:
            return "%s（scope=task）" % task_ref
    return None


# ---------------------------------------------------------------- 主判定

def check_request(request, snapshot, rows, now_ts):
    v = Verdict()
    if request.get("schema") != REQUEST_SCHEMA:
        raise FailClosed("请求 schema 非 %s: %r" % (REQUEST_SCHEMA, request.get("schema")))
    if snapshot.get("schema") != TASKS_SCHEMA:
        raise FailClosed("任务快照 schema 非 %s: %r" % (TASKS_SCHEMA, snapshot.get("schema")))

    ttype = require(request, "ticket_type", "请求面")
    if ttype == "gpu-anolis":
        # GPU 直通永不（卡面禁项原文）；TICKET-REQUEST v1 枚举里该字面值见即拒。
        v.reject("ticket_type=gpu-anolis：GPU 直通永不（D-94 卡面禁项；本件不受理）")
        return v
    if ttype not in ALLOWED_TICKET_TYPES:
        raise FailClosed("ticket_type 词表外: %r（可 %s）" % (ttype, sorted(ALLOWED_TICKET_TYPES)))

    task_ref = parse_task_ref(require(request, "task_ref", "请求面"), "请求面")
    requester = require(request, "requester", "请求面")
    purpose = require(request, "purpose", "请求面")
    if len(purpose) > 200:
        raise FailClosed("purpose 超长（≤200 字）")
    res = require(request, "resource", "请求面")
    if not RESOURCE_RE.match(res):
        raise FailClosed("resource 形态非法（族:名，如 llm:glm-plan）: %r" % (res,))
    fam = res.split(":", 1)[0]
    if fam == "gpu":
        v.reject("resource 族 gpu：GPU 直通永不（D-94 卡面禁项；本件不受理）")
        return v
    if (fam == "llm" and ttype != "llm-gw") or (fam == "video" and ttype != "video-gw"):
        raise FailClosed("resource 族 %s 与 ticket_type %s 不匹配" % (fam, ttype))

    am = request.get("amount")
    if not isinstance(am, dict):
        raise FailClosed("amount 非对象")
    max_req = am.get("max_req")
    max_in = am.get("max_input_tokens")
    if not isinstance(max_req, int) or isinstance(max_req, bool) or max_req <= 0:
        raise FailClosed("amount.max_req 非正整数")
    if not isinstance(max_in, int) or isinstance(max_in, bool) or max_in <= 0:
        raise FailClosed("amount.max_input_tokens 非正整数")
    ttl_s = parse_ttl_seconds(require(request, "ttl_ask", "请求面"), "请求面")
    cap_ttl = MAX_TTL_SECONDS[ttype]
    if ttl_s > cap_ttl:
        raise FailClosed("ttl_ask %ds 超票据类型上限 %ds" % (ttl_s, cap_ttl))

    # ① task_ref 在飞且身份一致（共用骨架·任务面）
    task_face_check(snapshot, task_ref, requester, v)

    # ② amount ≤ 单票上限（D-11 Q6 §3.1 起步值）
    v.add("② amount≤单票上限", max_req <= PER_TICKET_MAX_REQ and max_in <= PER_TICKET_MAX_INPUT_TOKENS,
          "max_req=%d/%d, max_input_tokens=%d/%d" % (max_req, PER_TICKET_MAX_REQ, max_in, PER_TICKET_MAX_INPUT_TOKENS))

    # ③④ 聚合账本面（解析失败 ⇒ FailClosed ⇒ fail-closed 拒发）
    agg = scan_ledger(rows, now_ts, requester, task_ref)
    v.add("③ 名下在飞总额≤每沙箱上限", agg["sandbox_today"] + max_req <= PER_SANDBOX_DAILY_REQ,
          "名下在飞当日已批 %d req + 本次 %d ≤ %d/日" % (agg["sandbox_today"], max_req, PER_SANDBOX_DAILY_REQ))
    v.add("④ 当日全局≤每日上限", agg["global_today"] + max_req <= GLOBAL_DAILY_REQ,
          "全局在飞当日已批 %d req + 本次 %d ≤ %d/日（v1 声明值）" % (agg["global_today"], max_req, GLOBAL_DAILY_REQ))

    # ⑤ 无停用 hold
    hit = hold_hit(agg["holds"], requester, task_ref)
    v.add("⑤ 无停用hold", hit is None,
          "无在押 hold" if hit is None else "在押 hold：%s" % hit)
    return v


def selftest():
    """内嵌夹具自测（零网络、零真账本读取）：判别力矩阵逐例断言。"""
    cases = []

    base_req = {
        "schema": REQUEST_SCHEMA, "ticket_type": "llm-gw",
        "task_ref": "factory-os#27", "resource": "llm:glm-plan",
        "amount": {"max_req": 10, "max_input_tokens": 100000},
        "ttl_ask": "1h", "requester": "worker-a", "purpose": "自测夹具",
    }
    base_tasks = {"schema": TASKS_SCHEMA, "generated_at": "2026-11-06T00:00:00Z",
                  "source": "fixture",
                  "tasks": [{"task_ref": "factory-os#27", "state": "running",
                             "inflight_identity": "worker-a"}]}
    now = dt.datetime(2026, 11, 6, 12, 0, 0, tzinfo=dt.timezone.utc)
    open_row = {"ts": "2026-11-06T00:00:00Z", "event": "ledger-open",
                "schema": LEDGER_SCHEMA, "note": "fixture"}
    fixture_ledger = [open_row]

    def run(req, tasks, ledger, nowts=now):
        try:
            return check_request(req, tasks, ledger, nowts).render()
        except FailClosed as e:
            v = Verdict()
            v.reject(str(e))
            return v.render()

    # 正例：五条全过 ⇒ approve
    r = run(base_req, base_tasks, fixture_ledger)
    cases.append(("approve-五条全过", r["verdict"] == "approve" and r["issued"] is True))
    # 负例族（必拒：verdict != approve 且 issued=False）
    r = run(dict(base_req, amount={"max_req": 201, "max_input_tokens": 100}), base_tasks, fixture_ledger)
    cases.append(("负例-超单票amount", r["verdict"] == "manual" and not r["issued"]))
    r = run(base_req, base_tasks,
            fixture_ledger + [{"ts": "2026-11-06T01:00:00Z", "event": "issue", "ticket_id": "t-0",
                               "task_ref": "factory-os#27", "requester": "worker-a", "consumer": "c0",
                               "key_fp": "fp0000000000", "amount": {"max_req": 495, "max_input_tokens": 1},
                               "ttl_s": 3600, "expires_at": "2026-11-06T02:00:00Z"}])
    cases.append(("负例-超每沙箱日限", r["verdict"] == "manual" and not r["issued"]))
    r = run(base_req, base_tasks,
            fixture_ledger + [{"ts": "2026-11-06T01:00:00Z", "event": "hold", "scope": "requester",
                               "target": "worker-a", "reason": "fixture 停用"}])
    cases.append(("负例-停用hold", r["verdict"] == "manual" and not r["issued"]))
    r = run(dict(base_req, task_ref="factory-os#999"), base_tasks, fixture_ledger)
    cases.append(("负例-task_ref不在飞", r["verdict"] == "manual" and not r["issued"]))
    r = run(dict(base_req, requester="worker-b"), base_tasks, fixture_ledger)
    cases.append(("负例-身份不一致", r["verdict"] == "manual" and not r["issued"]))
    # fail-closed 族（reject）
    r = run(dict(base_req, ticket_type="gpu-anolis"), base_tasks, fixture_ledger)
    cases.append(("failclosed-gpu直通永不", r["verdict"] == "reject" and not r["issued"]))
    r = run(dict(base_req, task_ref="not-a-ref"), base_tasks, fixture_ledger)
    cases.append(("failclosed-task_ref解析失败", r["verdict"] == "reject"))
    r = run(dict(base_req, amount={"max_req": 10}), base_tasks, fixture_ledger)
    cases.append(("failclosed-缺amount字段", r["verdict"] == "reject"))
    try:
        load_jsonl_strict("/nonexistent/ledger.jsonl", "夹具账本")
        cases.append(("failclosed-账本不可读", False))
    except FailClosed:
        cases.append(("failclosed-账本不可读", True))
    try:
        parse_jsonl_text('{"ts": "2026-11-06T00:00:00Z", "event": "issue"}\n{oops\n', "夹具账本")
        cases.append(("failclosed-账本坏行", False))
    except FailClosed:
        cases.append(("failclosed-账本坏行", True))
    # 全局日限：三张在飞票合计 >1000 ⇒ ④不过
    rows = [open_row]
    for k in range(3):
        rows.append({"ts": "2026-11-06T0%d:00:00Z" % (k + 1), "event": "issue", "ticket_id": "t-g%d" % k,
                     "task_ref": "factory-os#%d" % (k + 1), "requester": "worker-x", "consumer": "c-g%d" % k,
                     "key_fp": "fp%010d" % k, "amount": {"max_req": 400, "max_input_tokens": 1},
                     "ttl_s": 3600, "expires_at": "2026-11-06T23:00:00Z"})
    r = run(dict(base_req, requester="worker-a", task_ref="factory-os#27"), base_tasks, rows)
    cases.append(("负例-超全局日限", r["verdict"] == "manual" and not r["issued"]))

    bad = [(n, ok) for n, ok in cases if not ok]
    for n, ok in cases:
        print("  [%s] %s" % ("PASS" if ok else "FAIL", n))
    print("selftest %d/%d 过" % (len(cases) - len(bad), len(cases)))
    return 0 if not bad else 1


def parse_jsonl_text(text, what):
    """selftest 专用：对任意文本跑账本逐行严格解析（生产面走 load_jsonl_strict）。"""
    rows = []
    for i, raw in enumerate(text.splitlines(), 1):
        s = raw.strip()
        if not s:
            continue
        try:
            obj = json.loads(s)
        except ValueError as e:
            raise FailClosed("%s 第 %d 行不可解析 (%s)" % (what, i, e.__class__.__name__))
        if not isinstance(obj, dict):
            raise FailClosed("%s 第 %d 行非对象" % (what, i))
        rows.append(obj)
    return rows


def main():
    ap = argparse.ArgumentParser(description="资源票据发放机检器（五条机检 fail-closed，D-94）")
    ap.add_argument("--request", help="TICKET-REQUEST 机器形 JSON 文件（af.ticket-request.v1）")
    ap.add_argument("--tasks", help="在飞任务快照 JSON 文件（af.task-snapshot.v1；harness 经 API 生成）")
    ap.add_argument("--ledger", default=DEFAULT_LEDGER, help="账本 jsonl（默认 账本/resource-ledger.jsonl）")
    ap.add_argument("--now", help="ISO8601 现时刻覆盖（仅自测/复核用，形 2026-11-06T12:00:00Z）")
    ap.add_argument("--selftest", action="store_true", help="内嵌夹具自测（零网络零真账本）")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(selftest())
    if not a.request or not a.tasks:
        ap.error("实跑需 --request 与 --tasks（自测用 --selftest）")
    try:
        request = load_json_strict(a.request, "请求面")
        snapshot = load_json_strict(a.tasks, "任务快照")
        rows = load_jsonl_strict(a.ledger, "账本")
        now_ts = (parse_iso_ts(a.now, "--now") if a.now
                  else dt.datetime.now(dt.timezone.utc))
        v = check_request(request, snapshot, rows, now_ts)
    except FailClosed as e:
        v = Verdict()
        v.reject(str(e))
    out = v.render()
    print(json.dumps(out, ensure_ascii=False, indent=1))
    sys.exit(RC_APPROVE if out["verdict"] == "approve" else
             (RC_MANUAL if out["verdict"] == "manual" else RC_REJECT))


if __name__ == "__main__":
    main()
