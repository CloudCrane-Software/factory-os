#!/usr/bin/env python3
"""order-stages.py — 订单阶段观测采集器（工单①：订单可见性-20261029）

让运营者在看板一眼看到每张订单进行到哪、agent 正在干什么。
数据全部从既有工件推导，零侵入 af 引擎/引擎仓（只读采集）。

数据源（anolis，ssh 只读；--replay 模式改读本机 orders 目录）：
  <root>/orders/<id>/ledger.jsonl     状态机转移（submit/claim/run/close，state_after 字段）
  <root>/orders/<id>/records.jsonl     usage/tokens/spend/model_calls（unit_id/verdict/quota）
  <root>/orders/<id>/results.jsonl     profile/reward/status/error_code/tokens/model_calls
  <root>/orders/<id>/voucher.json      amount=预算上限（分）
  <root>/orders/<id>/specs/<id>.json   exp1 逐单 spec（note 里 unit/profile）
  <root>/orders/<id>/runs/<run>/normal.jsonl            逐事件流（扁平 swev 布局）
  <root>/orders/<id>/runs/<run>/ring/<node>/normal.jsonl 逐事件流（report 环：reader/writer-iN）
  <root>/orders/<id>/runs/<run>/ring/<node>/critical.jsonl  harness.stop（节点完成标记）
  <root>/orders/<id>/runs/<run>/verify.log              citation/rubric 核验（report 判官阶段）
  /data/bench/queue/{pending,done}/<seq>-<dedupe_key>.json  burn 队列条目（max_turns/profile/unit）

stage 推导规则（判据先行，逐条有锚）：
  * 终态优先：ledger state_after=Closed → stage="closed"（reward 由 results.jsonl 给 true/false）；
    results.status="run_failed" 或 ledger 末条 op ok=false 且 error_kind="unit_failed"
    → stage="failed"。
  * ledger state_after="Completed"（单跑完、close 门控未过/未执行）→ stage="completed"。
  * 无任何 run 事件 → stage="queued"（burn 队列在途条目同此阶）。
  * report 单（runs/*/ring/<node>/normal.jsonl 存在）：
      取事件时间戳最新的节点 → stage="reader"（reader 节点）/ "writer"（writer-iN 节点）；
      该节点已被 critical.jsonl 的 harness.stop(completed) 标记完成、且其后无更新节点、
      且 verify.log 在位 → stage="judge"（引用/rubric 判官阶段）。
      节点名（reader/writer-i1/...）进 stage_detail；turn_n=该节点最大 turn+1。
  * swev 单（扁平 normal.jsonl）→ stage="agent-loop"，turn_n=最大 turn+1（agent-loop 轮次）。

字段口径（自文档化，全部落在输出的 field_notes）：
  tokens         normal.jsonl 的 harness.model usage 三项求和（实测与 records.usage.quota 逐项相等，
                 见报告判据1）；无事件时回退 results.jsonl tokens → records.usage.quota。
  model_calls    results.model_calls → records.usage.unit_calls → normal.jsonl 的 harness.model 计数。
  spend_cents    voucher.amount（预算上限，分）。数据源里没有"已花费分"字段，故此处是上限非计量值，
                 spend_cents_basis 明示。
  turn_max       配置轮次上限：burn 队列条目 max_turns（经 submitted.jsonl 的 order_id→dedupe_key 联接）；
                 exp1 无逐单记录，回落 exp1-submit.sh:39 的 MAX_TURNS 脚本级默认 40（turn_max_src 标注）。
  last_action    最新一条 normal.jsonl 事件的紧凑描述（kind/tool/turn/model/finish/error_code），
                 截 80 字；失败单回落 ledger 末条 op+error_kind（不带 error_detail 原文）。
  elapsed_s      本单自有事件跨度（last_event_ts - first_event_ts，秒）= 看板"时长"列。
  idle_s         now - last_event_ts（秒）；active = idle_s ≤ --active-min（默认 60）。

安全纪律：
  * 采集只读：ssh 侧只 open()/os.listdir/os.walk，无任何写/删/改；--replay 只读本机目录。
  * last_action 只由事件描述符与 error_kind 组成，不携带 error_detail/run_dir 原文；
    落盘前再跑一遍脱敏闸模式族自检（--selftest-scrub），命中即整条降级为固定短语（fail-closed）。
  * 输出原子写（同目录 tmp + os.replace），看板拉取永不见半截文件。

用法：
  order-stages.py                      # live：ssh anolis 采集 → 状态观测/stages.json
  order-stages.py --replay <orders-dir> # 历史回放：本机 orders 目录 → 状态观测/stages-replay.json
  order-stages.py --stdout             # 打到 stdout 不落盘
  order-stages.py --selftest-scrub     # 只跑 last_action 脱敏自检（判据5）
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

WS = os.path.expanduser("~/workspace/agent黑灯工厂")
ANOLIS = "anolis"
SSH_OPTS = "-o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=5 -o ServerAliveCountMax=2"
LIVE_ROOTS = ["/data/bench/af-p3-state", "/data/bench/exp1-state"]
QUEUE = "/data/bench/queue"
OUT_LIVE = os.path.join(WS, "状态观测/stages.json")
OUT_REPLAY = os.path.join(WS, "状态观测/stages-replay.json")
ACT = 80           # last_action 截断字数
ACTIVE_MIN = 60    # 在途判定：最近事件距今 ≤ 60min
EXP1_MAX_TURNS_DEFAULT = 40   # exp1-submit.sh:39 MAX_TURNS 脚本级默认（非逐单记录）

# --------------------------------------------------------------------------- #
# 远端采集脚本（anolis 只读执行；stdin 喂过去，不在远端落任何文件）
# --------------------------------------------------------------------------- #
REMOTE = r'''
import json, os, glob

ROOTS = json.loads(os.environ["OS_ROOTS"])
QUEUE = os.environ["OS_QUEUE"]

def jload(p):
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            return json.load(f)
    except Exception:
        return None

def jlines(p):
    out = []
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            for l in f:
                l = l.strip()
                if l:
                    try:
                        out.append(json.loads(l))
                    except Exception:
                        pass
    except Exception:
        pass
    return out

def lastline(p):
    ls = jlines(p)
    return ls[-1] if ls else None

def ev_desc(j):
    """单条事件的紧凑描述（不含任何路径/主机名）。"""
    p = j.get("payload") or {}
    k = j.get("kind") or "?"
    if k == "harness.model":
        u = p.get("usage") or {}
        return ("model turn=%s %s finish=%s in=%s out=%s" % (
            p.get("turn"), p.get("model"), p.get("finish"),
            u.get("input_tokens"), u.get("output_tokens"))).strip()
    if k == "harness.tool":
        return "tool turn=%s %s%s" % (p.get("turn"), p.get("tool"),
                                      "" if not p.get("is_error") else " ERR=" + str(p.get("error_code") or "?"))
    if k == "harness.stop":
        st = p.get("status") or {}
        return "stop turn=%s %s signal=%s" % (p.get("turn"), st.get("kind"), st.get("signal"))
    return k

def scan_run(run_dir, run_rel):
    """扫一个 run 目录下所有 normal.jsonl（任意深度：扁平 swev 布局
    runs/<run>/normal.jsonl；report 环 runs/<run>/ring/<node>/normal.jsonl；
    exp1 双臂嵌套 runs/<group>/<run>/ring/<node>/normal.jsonl）。
    节点名 = normal.jsonl 的父目录名，且仅当其祖父目录名为 ring 时算环节点。"""
    out = []
    verify = False
    for dirpath, _dirs, files in os.walk(run_dir):
        if "verify.log" in files:
            verify = True
        if "normal.jsonl" not in files:
            continue
        path = os.path.join(dirpath, "normal.jsonl")
        parent = os.path.basename(dirpath.rstrip("/"))
        grand = os.path.basename(os.path.dirname(dirpath.rstrip("/")))
        node = parent if grand == "ring" else None
        rel = run_rel + "/" + os.path.relpath(path, run_dir)
        ls = jlines(path)
        if not ls:
            continue
        mt = 0
        ti = to = tc = 0
        nm = 0
        for j in ls:
            p = j.get("payload") or {}
            t = p.get("turn")
            if isinstance(t, int) and t + 1 > mt:
                mt = t + 1
            if j.get("kind") == "harness.model":
                nm += 1
                u = p.get("usage") or {}
                ti += u.get("input_tokens") or 0
                to += u.get("output_tokens") or 0
                tc += u.get("cache_read_tokens") or 0
        crit = os.path.join(dirpath, "critical.jsonl")
        stop = None
        cl = jlines(crit)
        if cl:
            sj = cl[-1]
            p = sj.get("payload") or {}
            st = p.get("status") or {}
            stop = {"kind": sj.get("kind"), "turn": p.get("turn"),
                    "status_kind": st.get("kind"), "signal": st.get("signal"),
                    "ts_ms": sj.get("ts_ms")}
        out.append({"node": node, "rel": rel,
                    "events": len(ls), "model_calls": nm, "max_turn": mt,
                    "tokens": {"input": ti, "output": to, "cache_read": tc},
                    "last_ts_ms": ls[-1].get("ts_ms"),
                    "last_desc": ev_desc(ls[-1]), "stop": stop})
    out.sort(key=lambda f: (f["node"] is not None, f["node"] or "", f["rel"]))
    return out, verify

def one(root, odir):
    oid = os.path.basename(odir)
    led = jlines(os.path.join(odir, "ledger.jsonl"))
    first_ts = led[0].get("ts_ms") if led else None
    last = led[-1] if led else None
    err_ops = [e for e in led if e.get("ok") is False]
    res = lastline(os.path.join(odir, "results.jsonl")) or {}
    rec = lastline(os.path.join(odir, "records.jsonl")) or {}
    vch = jload(os.path.join(odir, "voucher.json")) or {}
    spec = jload(os.path.join(odir, "specs", oid + ".json")) or {}
    runs = []
    rdir = os.path.join(odir, "runs")
    if os.path.isdir(rdir):
        for rd in sorted(os.listdir(rdir)):
            rdp = os.path.join(rdir, rd)
            if not os.path.isdir(rdp):
                continue
            files, verify = scan_run(rdp, "runs/" + rd)
            runs.append({"run_id": rd, "files": files, "verify_log": verify})
    return {"order_id": oid, "root": root,
            "ledger_first_ts_ms": first_ts,
            "ledger_last_op": (last or {}).get("op"),
            "ledger_last_ok": (last or {}).get("ok"),
            "ledger_state": (last or {}).get("state_after"),
            "ledger_last_ts_ms": (last or {}).get("ts_ms"),
            "ledger_err_kinds": sorted({e.get("error_kind") for e in err_ops if e.get("error_kind")}),
            "results": {k: res.get(k) for k in
                        ("suite", "profile", "status", "reward", "error_code", "model_calls",
                         "turns", "tokens", "run_dir") if k in res},
            "records": {"unit_id": rec.get("unit_id"), "status": rec.get("status"),
                        "verdict": rec.get("verdict"),
                        "quota": (rec.get("usage") or {}).get("quota"),
                        "turns": (rec.get("usage") or {}).get("turns"),
                        "unit_calls": (rec.get("usage") or {}).get("unit_calls")},
            "voucher_amount": vch.get("amount"),
            "spec_note": spec.get("note"),
            "runs": runs}

def queue_entries():
    """burn 队列条目：pending（在途待跑）+ done（含 max_turns，供联接）。"""
    out = {"pending": [], "done": {}}
    sub = os.path.join(QUEUE, "submitted.jsonl")
    submap = {}
    for j in jlines(sub):
        if j.get("order_id"):
            submap[j["order_id"]] = j.get("dedupe_key")
    out["submitted"] = submap
    for d in ("pending", "done", "failed"):
        p = os.path.join(QUEUE, d)
        if not os.path.isdir(p):
            continue
        for fn in sorted(os.listdir(p)):
            if not fn.endswith(".json"):
                continue
            j = jload(os.path.join(p, fn))
            if not j:
                continue
            # 键以条目自身 dedupe_key 为准（done/ 文件名序前缀与 dedupe_key 不一定同形：
            # swev 条目 0200-rr80-<task>.json ↔ rr80-<task>；report 条目 010-report-<task>.json
            # ↔ rf-<task>，文件名解析会对不上）
            key = j.get("dedupe_key") or (fn[:-5].split("-", 1)[1] if "-" in fn[:-5] else fn[:-5])
            j["_key"] = key
            j["_bucket"] = d
            if d == "pending":
                out["pending"].append(j)
            else:
                out["done"][key] = j
    return out

roots = {}
for r in ROOTS:
    od = os.path.join(r, "orders")
    lst = []
    if os.path.isdir(od):
        for name in sorted(os.listdir(od)):
            p = os.path.join(od, name)
            if os.path.isdir(p):
                lst.append(one(r, p))
    roots[r] = lst
if __name__ == "__main__":   # anolis 侧驱动；本机 exec 复用函数时不落 stdout
    print(json.dumps({"roots": roots, "queue": queue_entries()}, ensure_ascii=False))
'''

# --------------------------------------------------------------------------- #
# 脱敏自检：复用 tools/publish-scrub-gate.py 的模式族（单一真源），
# last_action 命中即整条降级为固定短语（fail-closed，宁可丢信息不漏密钥）。
# --------------------------------------------------------------------------- #
def _gate_patterns():
    """从 publish-scrub-gate.py 导入 PATTERNS；导入失败返回 None（调用方按无闸处置=降级）。"""
    try:
        sys.path.insert(0, os.path.join(WS, "tools"))
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "psg", os.path.join(WS, "tools/publish-scrub-gate.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m.PATTERNS
    except Exception:
        return None


PATTERNS = _gate_patterns()
DEGRADED_ACTION = "[动作文本已按脱敏闸降级]"


def scrub_action(text):
    """返回 (安全文本, 是否命中)。命中段替换 ▉▉▉ 后复扫，仍命中则整条降级。"""
    if not text:
        return text, False
    pats = PATTERNS
    if not pats:                       # 闸不可用：保守降级
        return DEGRADED_ACTION, True
    if not any(rx.search(text) for _n, rx, _v in pats):
        return text, False
    red = text
    for _n, rx, val in pats:
        try:
            if val and "v" in (rx.groupindex or {}):
                red = rx.sub(lambda m: m.group(0).replace(m.group("v"), "▉▉▉"), red)
            else:
                red = rx.sub("▉▉▉", red)
        except Exception:
            return DEGRADED_ACTION, True
    if any(rx.search(red) for _n, rx, _v in pats):
        return DEGRADED_ACTION, True
    return red, True


# --------------------------------------------------------------------------- #
# 采集
# --------------------------------------------------------------------------- #
def _ssh_json():
    env = "OS_ROOTS='%s' OS_QUEUE='%s'" % (json.dumps(LIVE_ROOTS), QUEUE)
    cmd = ["ssh"] + SSH_OPTS.split() + [ANOLIS, env + " python3 -"]
    r = subprocess.run(cmd, input=REMOTE, capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        raise RuntimeError("ssh 采集失败 rc=%d: %s" % (r.returncode, (r.stderr or "")[:300]))
    return json.loads(r.stdout)


def _local_orders(orders_dir):
    """--replay：本机 orders 目录（镜像 anolis 布局）走同一套扫描代码路径。
    REMOTE 顶部读 OS_ROOTS/OS_QUEUE 环境变量，exec 前先置好（本机空队列）。"""
    os.environ.setdefault("OS_ROOTS", json.dumps([orders_dir]))
    os.environ.setdefault("OS_QUEUE", "/nonexistent-queue")
    ns = {"os": os, "json": json, "__name__": "order_stages_local"}
    exec(compile(REMOTE, "<remote>", "exec"), ns)
    root = os.path.dirname(orders_dir.rstrip("/")) or "."
    lst = []
    for name in sorted(os.listdir(orders_dir)):
        p = os.path.join(orders_dir, name)
        if os.path.isdir(p):
            lst.append(ns["one"](root, p))
    return {"roots": {root: lst}, "queue": {"submitted": {}, "pending": [], "done": {}}}


def collect(args):
    if args.replay:
        return _local_orders(args.replay)
    return _ssh_json()


# --------------------------------------------------------------------------- #
# 推导
# --------------------------------------------------------------------------- #
NODE_ORDER = ["reader", "writer-i1", "writer-i2", "writer-i3", "writer-i4",
              "writer-i5", "writer-i6", "writer-i7", "writer-i8", "judge"]

# 源数据拼写归一（results.jsonl suite 实测值 → 展示单元名）
UNIT_ALIAS = {"swe-v": "swev"}


def _node_rank(name):
    return NODE_ORDER.index(name) if name in NODE_ORDER else len(NODE_ORDER)


def _norm_unit(o):
    u = (o.get("records") or {}).get("unit_id")
    if u:
        return u.replace("-unit", "")
    suite = (o.get("results") or {}).get("suite")
    if suite:
        # 源数据拼写归一：results.jsonl 里 swev 失败单的 suite 实测为 "swe-v"（连字符），
        # 与 records.unit_id 的 "swev-unit" 对齐后统一成 swev（归一只影响展示，不改源）。
        return UNIT_ALIAS.get(suite, suite)
    note = o.get("spec_note") or ""
    m = re.search(r"unit=([a-z0-9_-]+)", note)
    if m:
        return m.group(1)
    oid = o.get("order_id") or ""
    if "-report-" in oid:
        return "report"
    if "-swev-" in oid or "-graph-" in oid:
        return "swev"
    return "?"


def _profile(o, qent):
    p = (o.get("results") or {}).get("profile")
    if p:
        return p
    m = re.search(r"profile=([A-Za-z0-9_.-]+)", o.get("spec_note") or "")
    if m:
        return m.group(1)
    if qent and qent.get("profile"):
        return qent["profile"]
    return "?"


def _tokens(o):
    ti = to = tc = 0
    src = None
    for run in o.get("runs") or []:
        for f in run.get("files") or []:
            t = f.get("tokens") or {}
            ti += t.get("input") or 0
            to += t.get("output") or 0
            tc += t.get("cache_read") or 0
    if ti or to or tc:
        src = "normal.jsonl(harness.model usage)"
    else:
        t = ((o.get("results") or {}).get("tokens") or {})
        ti, to, tc = t.get("input") or 0, t.get("output") or 0, t.get("cache_read") or 0
        if ti or to or tc:
            src = "results.jsonl"
        else:
            q = (o.get("records") or {}).get("quota") or {}
            ti, to, tc = q.get("input") or 0, q.get("output") or 0, q.get("cache_read") or 0
            if ti or to or tc:
                src = "records.usage.quota"
    return {"input": ti, "output": to, "cache_read": tc, "total": ti + to + tc}, src


def _model_calls(o):
    n = (o.get("results") or {}).get("model_calls")
    if isinstance(n, int) and n:
        return n
    n = (o.get("records") or {}).get("unit_calls")
    if isinstance(n, int) and n:
        return n
    return sum(f.get("model_calls") or 0 for r in o.get("runs") or [] for f in r.get("files") or [])


def _events_span(o):
    """全事件（ledger + normal.jsonl）的最早/最晚 ts_ms。"""
    ts = []
    if o.get("ledger_first_ts_ms"):
        ts.append(o["ledger_first_ts_ms"])
    if o.get("ledger_last_ts_ms"):
        ts.append(o["ledger_last_ts_ms"])
    for r in o.get("runs") or []:
        for f in r.get("files") or []:
            if f.get("last_ts_ms"):
                ts.append(f["last_ts_ms"])
            st = f.get("stop") or {}
            if st.get("ts_ms"):
                ts.append(st["ts_ms"])
    return (min(ts), max(ts)) if ts else (None, None)


def _last_event(o):
    """最新一条事件（含 critical.jsonl 的 stop）。"""
    best = None
    for r in o.get("runs") or []:
        for f in r.get("files") or []:
            cand = {"ts_ms": f.get("last_ts_ms"), "desc": f.get("last_desc"),
                    "rel": f.get("rel"), "node": f.get("node"), "kind": "normal"}
            if best is None or (cand["ts_ms"] or 0) > (best["ts_ms"] or 0):
                best = cand
            st = f.get("stop") or {}
            if st.get("ts_ms"):
                c2 = {"ts_ms": st.get("ts_ms"),
                      "desc": "stop %s signal=%s" % (st.get("status_kind"), st.get("signal")),
                      "rel": f.get("rel"), "node": f.get("node"), "kind": "stop"}
                if (c2["ts_ms"] or 0) > (best["ts_ms"] or 0):
                    best = c2
    return best


def _queue_entry(o, queue):
    """burn 队列联接：submitted.jsonl 的 order_id 是短名（如 "A0277"），
    state/orders/ 目录名带后缀（如 "A0277-report-step-5"）——按 短名/短名- 前缀匹配。"""
    oid = o.get("order_id") or ""
    for sub_id, dk in (queue.get("submitted") or {}).items():
        if oid != sub_id and not oid.startswith(sub_id + "-"):
            continue
        for b in ("pending", "done"):
            bucket = queue.get(b) or {}
            # pending 桶 queue_entries() 落为 list（.append），done 为 dict——双形兼收
            # （2026-11-06 修：pending 非空即 AttributeError，此前空表时 [] or {} 掩过）
            if isinstance(bucket, list):
                e = next((x for x in bucket if x.get("_key") == dk), None)
            else:
                e = bucket.get(dk)
            if e:
                return e, b
    return None, None


def derive(o, queue, now_ms, mode, replay):
    """单张订单 → 看板行。返回 (row, 脱敏命中数)。"""
    oid = o.get("order_id")
    qent, qbucket = _queue_entry(o, queue)
    unit = _norm_unit(o)
    profile = _profile(o, qent)
    state = o.get("ledger_state") or "?"
    res = o.get("results") or {}
    reward = res.get("reward")
    err_kinds = o.get("ledger_err_kinds") or []
    unit_failed = "unit_failed" in err_kinds
    run_failed = res.get("status") == "run_failed"

    tokens, tok_src = _tokens(o)
    model_calls = _model_calls(o)
    first_ts, last_ts = _events_span(o)
    last_ev = _last_event(o)
    idle_s = int((now_ms - last_ts) / 1000) if last_ts else None
    elapsed_s = int((last_ts - first_ts) / 1000) if (first_ts and last_ts) else None

    # ---- stage（词汇表严格对齐任务书：report=reader/writer/judge/终态，swev=agent-loop 轮次，
    #      终态=closed(reward=true/false)/failed；ledger 状态另由 state 字段承载，不混入 stage）----
    # 先无条件算"节点/run 级事实"（turn_n、锚、节点名），终态单也照样带上，看板才看得细。
    ring = [(f, r) for r in (o.get("runs") or []) for f in (r.get("files") or []) if f.get("node")]
    flat = [(f, r) for r in (o.get("runs") or []) for f in (r.get("files") or []) if not f.get("node")]
    turn_max, turn_max_src = None, None
    node_stage, stage_detail, turn_n, anchor = "queued", None, 0, None
    if ring:
        # report 单：事件时间戳最新的节点=当前阶段（normal.jsonl 节点标记为锚）
        cand = sorted(ring, key=lambda x: ((x[0].get("last_ts_ms") or 0),
                                           _node_rank(x[0].get("node"))))
        cur_f, cur_r = cand[-1]
        node = cur_f.get("node")
        stopped = bool((cur_f.get("stop") or {}).get("ts_ms"))
        later = [f for f, _r in ring if _node_rank(f.get("node")) > _node_rank(node)]
        if stopped and not later and cur_r.get("verify_log"):
            # 末节点已被 critical.jsonl 的 harness.stop(completed) 标记完成、无更新节点、
            # verify.log 在位 → 环已收口，订单处于引用/rubric 判官阶段
            node_stage, stage_detail = "judge", node
        else:
            node_stage = "reader" if node == "reader" else "writer"
            stage_detail = node
        turn_n = cur_f.get("max_turn") or 0
        anchor = {"path": cur_f.get("rel"), "node": node,
                  "events": cur_f.get("events"), "max_turn": cur_f.get("max_turn"),
                  "last_desc": cur_f.get("last_desc"), "ts_ms": cur_f.get("last_ts_ms")}
    elif flat:
        # swev 单：扁平 normal.jsonl = agent-loop 轮次
        cur_f, _r = sorted(flat, key=lambda x: (x[0].get("last_ts_ms") or 0))[-1]
        node_stage = "agent-loop"
        stage_detail = "swev-agent-loop"
        turn_n = cur_f.get("max_turn") or 0
        anchor = {"path": cur_f.get("rel"), "node": None,
                  "events": cur_f.get("events"), "max_turn": cur_f.get("max_turn"),
                  "last_desc": cur_f.get("last_desc"), "ts_ms": cur_f.get("last_ts_ms")}

    if unit_failed or run_failed:
        stage = "failed"
    elif state == "Closed":
        stage = "closed"
    else:
        stage = node_stage
    if stage == "queued" and qent:
        stage_detail = "burn-queue:" + (qbucket or "?")

    if qent and qent.get("max_turns"):
        turn_max, turn_max_src = qent["max_turns"], "burn-queue-entry(%s)" % qbucket
    elif unit == "report" and o.get("root", "").endswith("exp1-state"):
        turn_max, turn_max_src = EXP1_MAX_TURNS_DEFAULT, "exp1-submit.sh:39 MAX_TURNS 脚本级默认"

    # ---- last_action（截 80 字；失败单回落 op+error_kind，不带 error_detail 原文）----
    if stage == "failed":
        action = "末态 op=%s ok=false kind=%s" % (o.get("ledger_last_op"),
                                                  ",".join(err_kinds) or "run_failed")
    elif last_ev and last_ev.get("desc"):
        action = last_ev["desc"]
    else:
        action = "无 run 事件（ledger 末态 state=%s op=%s）" % (state, o.get("ledger_last_op"))
    action = action[:ACT] + ("…" if len(action) > ACT else "")
    action, hit = scrub_action(action)

    run_ids = [r.get("run_id") for r in (o.get("runs") or [])]
    return ({
        "order_id": oid,
        "unit": unit,
        "profile": profile,
        "stage": stage,
        "stage_detail": stage_detail,
        "turn_n": turn_n,
        "turn_max": turn_max,
        "turn_max_src": turn_max_src,
        "tokens": tokens,
        "tokens_src": tok_src,
        "spend_cents": o.get("voucher_amount"),
        "spend_cents_basis": "budget_voucher.amount（预算上限/分，非计量花费）",
        "model_calls": model_calls,
        "last_action": action,
        "last_action_scrubbed": hit,
        "last_event_ts": last_ts,
        "elapsed_s": elapsed_s,
        "idle_s": idle_s,
        "state": state,
        "run_id": run_ids[-1] if run_ids else None,
        "reward": reward,
        "active": bool(idle_s is not None and idle_s <= ACTIVE_MIN * 60),
        "stage_anchor": anchor,
        "queue_bucket": qbucket,
        # 只落根目录基名（af-p3-state/exp1-state/exp1-replay）：绝对路径（尤其本机 /home/...）
        # 会撞脱敏闸 O-03，且属内部拓扑，看板分组用基名足够
        "source_root": os.path.basename((o.get("root") or "?").rstrip("/")) or "?",
    }, 1 if hit else 0)


def build(payload, mode, replay, now_ms=None):
    now_ms = now_ms or int(time.time() * 1000)
    queue = payload.get("queue") or {}
    rows = []
    scrubbed = 0
    for root, lst in (payload.get("roots") or {}).items():
        for o in lst:
            row, hit = derive(o, queue, now_ms, mode, replay)
            scrubbed += hit
            rows.append(row)
    # burn 队列在途（尚未落到 state/orders/ 的待跑条目）
    sub = queue.get("submitted") or {}
    inv = {}
    for oid, dk in sub.items():
        inv[dk] = oid
    for e in queue.get("pending") or []:
        oid = inv.get(e.get("_key"))
        if oid and any(r["order_id"] == oid or r["order_id"].startswith(oid + "-")
                       for r in rows):
            continue
        act = "burn 队列待跑 task=%s unit=%s" % (e.get("task"), e.get("unit"))
        act, hit = scrub_action(act[:ACT])
        scrubbed += 1 if hit else 0
        rows.append({"order_id": oid or e.get("_key"), "unit": e.get("unit"),
                     "profile": e.get("profile"), "stage": "queued",
                     "stage_detail": "burn-queue:pending", "turn_n": 0,
                     "turn_max": e.get("max_turns"), "turn_max_src": "burn-queue-entry(pending)",
                     "tokens": {"input": 0, "output": 0, "cache_read": 0, "total": 0},
                     "tokens_src": None, "spend_cents": e.get("spend_cap"),
                     "spend_cents_basis": "burn-queue-entry.spend_cap（预算上限/分）",
                     "model_calls": 0, "last_action": act[:ACT], "last_action_scrubbed": hit,
                     "last_event_ts": None, "elapsed_s": None, "idle_s": None,
                     "state": "Queued", "run_id": None, "reward": None, "active": True,
                     "stage_anchor": None, "queue_bucket": "pending",
                     "source_root": "burn-queue"})
    rows.sort(key=lambda r: (-(r.get("last_event_ts") or 0), r["order_id"]))
    by_unit, by_stage = {}, {}
    for r in rows:
        by_unit[r["unit"]] = by_unit.get(r["unit"], 0) + 1
        by_stage[r["stage"]] = by_stage.get(r["stage"], 0) + 1
    nonterm = sum(1 for r in rows if r["stage"] not in ("closed", "failed"))
    return {
        "ts": now_ms,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mode": mode,
        # 同 source_roots：只给基名，不给绝对路径（本机 /home/... 会撞脱敏闸 O-03）
        "source": ("order-stages.py --replay %s" % os.path.basename(replay.rstrip("/"))) if replay else
                  "order-stages.py（ssh anolis 只读采集）",
        # 同 orders[].source_root：只给基名，不给绝对路径（防 O-03 + 内部拓扑）
        "source_roots": [os.path.basename(r.rstrip("/")) for r in
                         (LIVE_ROOTS if not replay else [replay])],
        "active_minutes": ACTIVE_MIN,
        "counts": {"orders": len(rows), "non_terminal": nonterm,
                   "active": sum(1 for r in rows if r["active"]),
                   "queued_pending": sum(1 for r in rows if r.get("queue_bucket") == "pending"),
                   "last_action_scrubbed": scrubbed,
                   "by_unit": by_unit, "by_stage": by_stage},
        "field_notes": {
            "stage": "closed=ledger Closed；failed=run_failed/unit_failed；completed=单跑完待 close；"
                     "reader/writer/judge=report 环节点（normal.jsonl+critical.jsonl stop 标记）；"
                     "agent-loop=swev 轮次；queued=burn 队列在途",
            "turn_n": "当前节点/run 的最大 turn+1（normal.jsonl payload.turn）",
            "turn_max": "配置轮次上限：burn 队列条目 max_turns；exp1 回落 exp1-submit.sh:39 默认 40",
            # 键名刻意用 token_usage 而非 tokens：脱敏闸 K-06/07/08/11 的键侧正则把
            # "tokens"（含 token+s）当赋值键，字符串值紧跟就会误红（本工单实测）。
            "token_usage": "harness.model usage 三项求和（取自逐事件流；与 records.usage.quota 实测相等）",
            "spend_cents": "voucher.amount=预算上限（分）；源数据无已花费分字段，非计量值",
            "last_action": "最新 normal.jsonl 事件描述（截80字）；失败单回落 ledger op+error_kind",
            "elapsed_s": "本单自有事件跨度（last-first，秒）",
            "idle_s": "now-last_event_ts（秒）；active=idle_s≤%dmin" % ACTIVE_MIN,
        },
        "orders": rows,
    }


def gate_prescan(obj):
    """落盘前本地复扫（判据2/5 的 fail-closed 兜底）：把输出序列化后跑一遍脱敏闸模式族，
    命中即返回命中清单（调用方应非零退出，推送器据此跳过本轮 stages）。"""
    text = json.dumps(obj, ensure_ascii=False)
    hits = []
    if not PATTERNS:
        return [{"file": "stages.json", "line": 0, "pattern": "闸不可用（publish-scrub-gate 导入失败）",
                 "preview": "", "len": 0}]
    for name, rx, _v in PATTERNS:
        for m in rx.finditer(text):
            v = m.group("v") if "v" in (m.groupdict() or {}) and m.group("v") else m.group(0)
            ln = text.count("\n", 0, m.start()) + 1
            hits.append({"file": "stages.json", "line": ln, "pattern": name,
                         "preview": v[:4], "len": len(v)})
    return hits


def write_atomic(path, obj):
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    tmp = os.path.join(d, "." + os.path.basename(path) + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def selftest_scrub():
    """判据5 自检：last_action 形态串过闸。"""
    cases = [
        ("model turn=3 step-5-preview finish=tool_calls in=1229 out=83", False),
        ("tool turn=12 bash ERR=EX3001", False),
        ("末态 op=attach_artifact ok=false kind=unit_failed", False),
        ("tool turn=1 bash token=sk-abcdef1234567890", True),
        ("stop turn=10 completed signal=REPORT_DONE", False),
    ]
    bad = 0
    for text, want_hit in cases:
        out, hit = scrub_action(text)
        ok = (hit == want_hit)
        bad += 0 if ok else 1
        print("%s in=%r -> hit=%s out=%r" % ("PASS" if ok else "FAIL", text, hit, out))
    print("selftest-scrub: %s" % ("全绿" if bad == 0 else "%d 例不符预期" % bad))
    return 0 if bad == 0 else 1


def _fx_order(**kw):
    """stage 自检夹具：最小化的采集态订单（字段与 REMOTE one() 输出同构）。"""
    o = {"order_id": "FX", "root": "/fx", "ledger_first_ts_ms": 1000,
         "ledger_last_op": "attach_artifact", "ledger_last_ok": True,
         "ledger_state": "InProgress", "ledger_last_ts_ms": 9000,
         "ledger_err_kinds": [], "results": {}, "records": {"unit_id": "report-unit"},
         "voucher_amount": 300, "spec_note": None, "runs": []}
    o.update(kw)
    return o


def _fx_file(node, turn, ts, stop=None, events=3):
    f = {"node": node, "rel": "runs/r/ring/%s/normal.jsonl" % (node or "run"),
         "events": events, "model_calls": events, "max_turn": turn,
         "tokens": {"input": 10 * turn, "output": 20 * turn, "cache_read": 0},
         "last_ts_ms": ts, "last_desc": "tool turn=%d bash" % (turn - 1), "stop": stop}
    return f


def selftest_stages():
    """判据1 自检：stage 推导全分支（reader/writer/judge/agent-loop/closed/failed/queued）
    跑合成夹具，锚必须指向 normal.jsonl。"""
    STOP = {"kind": "harness.stop", "turn": 9, "status_kind": "completed",
            "signal": "REPORT_DONE", "ts_ms": 8000}
    cases = [
        # (说明, order 覆盖, 期望 stage, 期望 turn_n)
        ("report reader 在跑", _fx_order(order_id="FX-reader", runs=[
            {"run_id": "r", "verify_log": False,
             "files": [_fx_file("reader", 4, 7000)]}]), "reader", 4),
        ("report writer-i1 在跑", _fx_order(order_id="FX-writer", runs=[
            {"run_id": "r", "verify_log": False,
             "files": [_fx_file("reader", 10, 5000, stop=STOP),
                       _fx_file("writer-i1", 2, 7500)]}]), "writer", 2),
        ("report 环收口+verify → judge", _fx_order(order_id="FX-judge", runs=[
            {"run_id": "r", "verify_log": True,
             "files": [_fx_file("reader", 10, 5000, stop=STOP),
                       _fx_file("writer-i1", 1, 8000, stop=STOP)]}]), "judge", 1),
        ("report 末节点已停但无 verify → 仍 writer", _fx_order(order_id="FX-w2", runs=[
            {"run_id": "r", "verify_log": False,
             "files": [_fx_file("reader", 10, 5000, stop=STOP),
                       _fx_file("writer-i1", 1, 8000, stop=STOP)]}]), "writer", 1),
        ("swev agent-loop 轮次", _fx_order(records={"unit_id": "swev-unit"}, runs=[
            {"run_id": "r", "verify_log": False,
             "files": [_fx_file(None, 26, 8000)]}]), "agent-loop", 26),
        ("ledger Closed → closed", _fx_order(ledger_state="Closed", runs=[
            {"run_id": "r", "verify_log": True,
             "files": [_fx_file("reader", 10, 5000, stop=STOP),
                       _fx_file("writer-i1", 1, 8000, stop=STOP)]}]), "closed", 1),
        ("unit_failed → failed", _fx_order(ledger_err_kinds=["unit_failed"],
                                           runs=[{"run_id": "r", "verify_log": False,
                                                  "files": [_fx_file("reader", 3, 7000)]}]), "failed", 3),
        ("run_failed → failed", _fx_order(results={"status": "run_failed"}, runs=[
            {"run_id": "r", "verify_log": False, "files": [_fx_file(None, 5, 7000)]}]), "failed", 5),
        ("无 run 事件 → queued", _fx_order(runs=[]), "queued", 0),
    ]
    bad = 0
    for name, o, want_stage, want_turn in cases:
        row, _hit = derive(o, {"submitted": {}, "pending": [], "done": {}}, 90000, "live", None)
        ok = row["stage"] == want_stage and row["turn_n"] == want_turn
        if row["stage"] in ("reader", "writer", "judge", "agent-loop"):
            ok = ok and bool(row["stage_anchor"]) and "normal.jsonl" in row["stage_anchor"]["path"]
        bad += 0 if ok else 1
        print("%s %-28s stage=%-11s turn_n=%-3s anchor=%s" %
              ("PASS" if ok else "FAIL", name, row["stage"], row["turn_n"],
               (row["stage_anchor"] or {}).get("path")))
    print("selftest-stages: %s" % ("全绿" if bad == 0 else "%d 例不符预期" % bad))
    return 0 if bad == 0 else 1


def main():
    ap = argparse.ArgumentParser(description="订单阶段观测采集（只读）")
    ap.add_argument("--replay", metavar="ORDERS_DIR",
                    help="历史回放模式：读本机 orders 目录（完结订单亦可，含终态行）")
    ap.add_argument("--out", help="输出路径（默认 live=状态观测/stages.json，replay=状态观测/stages-replay.json）")
    ap.add_argument("--stdout", action="store_true", help="打到 stdout 不落盘")
    ap.add_argument("--active-min", type=int, default=ACTIVE_MIN, help="在途判定分钟数（默认 60）")
    ap.add_argument("--selftest-scrub", action="store_true", help="只跑 last_action 脱敏自检（判据5）")
    ap.add_argument("--selftest-stages", action="store_true", help="只跑 stage 推导分支自检（判据1）")
    args = ap.parse_args()
    if args.active_min != ACTIVE_MIN:
        globals()["ACTIVE_MIN"] = args.active_min

    if args.selftest_scrub:
        return selftest_scrub()
    if args.selftest_stages:
        return selftest_stages()

    mode = "replay" if args.replay else "live"
    payload = collect(args)
    out = build(payload, mode, args.replay)
    hits = gate_prescan(out)
    if hits:
        # fail-closed：本地预扫红=不落盘（推送器只见上一版好件，或本轮无 stages）
        print("脱敏闸预扫红，拒绝落盘（%d 命中）：" % len(hits), file=sys.stderr)
        for h in hits[:20]:
            print("  HIT stages.json:%d %s 值特征=%s***[len=%d]" %
                  (h["line"], h["pattern"], h["preview"], h["len"]), file=sys.stderr)
        return 3
    if args.stdout:
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0
    path = args.out or (OUT_REPLAY if args.replay else OUT_LIVE)
    write_atomic(path, out)
    c = out["counts"]
    print("wrote %s mode=%s orders=%d non_terminal=%d active=%d queued=%d scrubbed=%d" %
          (path, mode, c["orders"], c["non_terminal"], c["active"], c["queued_pending"],
           c["last_action_scrubbed"]))
    print("by_stage=%s" % json.dumps(c["by_stage"], ensure_ascii=False))
    print("by_unit=%s" % json.dumps(c["by_unit"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
