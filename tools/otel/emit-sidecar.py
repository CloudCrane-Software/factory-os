#!/usr/bin/env python3
"""emit-sidecar.py — 产线可观测边车（OTel 非关键 lane 常驻采集+发射）。

每 30s 一个周期（OTEL_SIDECAR_INTERVAL 可调），五个只读采集源：
  ① scheduler 日志尾解析：状态观测/factory-scheduler.log 末条
     `queue pending=N unrun=M step=X/Y | daemons …` 行（正则锚定，日志重复行不敏感）
  ② 路由器日志计数：状态观测/event-router.log 时间戳行增量（跨周期字节游标，
     文件截断/换轨自动重置游标）
  ③ kb stats 只读：kb/store.py 的 stats() 逻辑在 mode=ro 连接上跑
     （KBStore.__new__ 绕过 __init__ 的 WAL/schema 写面——kb/ 包只读纪律）
  ④ anolis 只读 ssh 通道：/data/bench/queue/pending 条数 + pgrep -c af-order 在途
     （BatchMode+ConnectTimeout，与 factory-scheduler.py:75 同通道同口径）
  ⑤ 语义层腿（2026-11-05 A1 波次）：对 af-state/orders 最新可投影订单跑
     tools/otel/af-otel-projector.py（只读），把四层语义树（正本四名）缓存进
     状态观测/otel-sidecar-semantic.json（tmp+rename 原子写）。
     这是 --sidecar 断言面对语义层的覆盖补腿（此前语义层 0/4 → VACUOUS=10）：
       · 快照/回放语义：emit_round 被断言器以四实参复演时，语义树**恒**经发射器
         路径复原（otel_emit._post 被本地截获、零网络）→ --sidecar 每轮可见全树；
       · 真库中继语义：活体周期显式传 relay_semantic=<当轮是否中继>，非中继轮
         不呼语义 emit_span（零 CH 增生）；中继轮时间戳改写为当轮 ts（点跨度，
         RT-E138 emit-semantic-otlp.py 同款）使其落入 --production 近窗判据；
         中继节流 = 树变或距上次 ≥45min（SEMANTIC_RELAY_MIN_MS）；
       · 快照 emit.semantic_spans 记当轮**实发**条数（真库面真值，回放面恒为
         复原条数）——两侧语义在 docstring 与本处明示，不产生「复原=已入库」误导。

出口：经既有发射器 tools/otel/otel_emit.py 发 gauge/span 进常驻 collector
（AF_OTEL_ENDPOINT，缺省 http://pandev-host.invalid:4318=本机 tailnet，与 run-collector.sh 绑定一致）；
本轮快照原子落 状态观测/otel-sidecar.json（status-push 接入点见 otelp-report.md ③）。

熔断与容错（硬性）：
  · STOP 熔断：状态观测/OTEL-STOP 在场（otel_emit.stop_active()）→ 不发射、不刷快照，只记日志；
  · AF_OTEL_DISABLE=1 → 发射禁用（otel_emit 既有开关），采集与快照照常；
  · 任一采集源异常只记该源 error 字段与日志，绝不影响其他源、绝不崩出循环；
  · SIGTERM/SIGINT：当前周期跑完后清 PID 文件退出（不半途写快照）。

用法：
  tools/otel/emit-sidecar.py                # 常驻循环（30s/周期）
  tools/otel/emit-sidecar.py --once         # 单周期（验证用）
  tools/otel/emit-sidecar.py --interval 10  # 改周期
零明文：本件不接触任何凭据（发射器 otel_emit 同纪律：凭据不进本件）。
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
import urllib.request

WS = os.path.expanduser("~/workspace/agent黑灯工厂")
OTEL_DIR = os.path.join(WS, "tools", "otel")
sys.path.insert(0, OTEL_DIR)
sys.path.insert(0, WS)
import otel_emit  # noqa: E402  既有发射器（熔断/端点/scrub 单一真源）

# ---- 常量（环境可调） ------------------------------------------------------- #
DEFAULT_ENDPOINT = os.environ.get("AF_OTEL_ENDPOINT") or "http://pandev-host.invalid:4318"
os.environ.setdefault("AF_OTEL_ENDPOINT", DEFAULT_ENDPOINT)   # 发射器动态读 env
SCHED_LOG = os.path.join(WS, "状态观测/factory-scheduler.log")
ROUTER_LOG = os.path.join(WS, "状态观测/event-router.log")
KB_DB = os.path.join(WS, "kb/kb.db")
SNAPSHOT = os.path.join(WS, "状态观测/otel-sidecar.json")
RUNTIME = os.path.expanduser(os.environ.get("OTEL_RUNTIME") or "~/otelcol-runtime")
SIDECAR_LOG = os.path.join(RUNTIME, "logs/sidecar.log")
PIDFILE = os.path.join(RUNTIME, "sidecar.pid")
COLLECTOR_PIDFILE = os.path.join(RUNTIME, "otelcol.pid")   # run-collector.sh 的 PID 文件
COLLECTOR_LOG = os.path.join(RUNTIME, "logs/collector.log")
MAX_LOG_BYTES = int(os.environ.get("OTEL_MAX_LOG_BYTES") or 8 * 1024 * 1024)
LOG_KEEP = int(os.environ.get("OTEL_LOG_KEEP") or 3)
SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]

SERVICE = "otel-sidecar"
# ---- 语义层腿（A1）：投影器中继 -------------------------------------------- #
ORDERS_DIR = os.path.join(WS, "af-state/orders")
PROJECTOR = os.path.join(OTEL_DIR, "af-otel-projector.py")
SEMANTIC_CACHE = os.path.join(WS, "状态观测/otel-sidecar-semantic.json")
SEMANTIC_RELAY_MIN_MS = int(os.environ.get("OTEL_SEMANTIC_RELAY_MIN_MS") or 45 * 60 * 1000)
SEMANTIC_CACHE_MAX_AGE_MS = int(os.environ.get("OTEL_SEMANTIC_CACHE_MAX_AGE_MS")
                                or 60 * 60 * 1000)
SEMANTIC_CANDIDATES = 3          # 每轮最多试投影的订单数（新→旧）
SEMANTIC_PROJECT_TIMEOUT = 30    # 单子投影子进程超时（秒）
ROSTER_NAMES = ("invoke_workflow", "invoke_agent", "chat", "execute_tool")

# scheduler 日志尾行锚（与 factory-scheduler.py 写出口径逐字对齐）
SCHED_RE = re.compile(
    r"^\[([\d\-: ]+)\]\s+queue\s+pending=(\d+)\s+unrun=(\d+)\s+step=(\d+)/(\d+)"
    r"\s*\|\s*daemons\s+burn=(\w+)\s+tailer=(\w+)\s+router=(\w+)\s+push=(\w+)")
ROUTER_TS_RE = re.compile(r"^\[\d{2}:\d{2}:\d{2}\]")

_stop = False           # SIGTERM 置位；当前周期收尾后退出
_router_offset = 0      # 跨周期字节游标（模块级，单进程语义）
_router_reset_logged = False


def log(msg: str) -> None:
    line = f"[{time.strftime('%F %T')}] emit-sidecar: {msg}"
    print(line, flush=True)
    try:
        os.makedirs(os.path.dirname(SIDECAR_LOG), exist_ok=True)
        with open(SIDECAR_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def rotate_log(path: str, max_bytes: int = MAX_LOG_BYTES, keep: int = LOG_KEEP) -> None:
    """copytruncate 轮转（常驻进程持 fd 追加写；与 run-collector.sh 同逻辑同参数）。"""
    try:
        if os.path.getsize(path) < max_bytes:
            return
        for i in range(keep - 1, 0, -1):
            src = f"{path}.{i}"
            if os.path.exists(src):
                os.replace(src, f"{path}.{i + 1}")
        shutil.copy2(path, f"{path}.1")
        with open(path, "w", encoding="utf-8"):
            pass
        log(f"日志轮转: {os.path.basename(path)} ≥{max_bytes}B → .1（保留 {keep} 代）")
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# 采集源（每个独立 try；异常只记该源 error，绝不外抛）
# --------------------------------------------------------------------------- #
def collect_scheduler() -> dict:
    """末条 queue/daemons 行 → pending/unrun/step 在途/容量/daemons up 数。"""
    with open(SCHED_LOG, "rb") as f:
        f.seek(0, os.SEEK_END)
        f.seek(max(0, f.tell() - 65536))
        tail = f.read().decode(errors="replace").splitlines()
    for line in reversed(tail):
        m = SCHED_RE.match(line.strip())
        if m:
            ts_s, pending, unrun, step_i, step_c, burn, tailer, router, push = m.groups()
            daemons = {"burn": burn, "tailer": tailer, "router": router, "push": push}
            up = sum(1 for v in daemons.values() if v == "up")
            try:
                age = max(0.0, time.time() - time.mktime(
                    time.strptime(ts_s, "%Y-%m-%d %H:%M:%S")))
            except ValueError:
                age = -1.0
            return {"ok": True, "log_ts": ts_s, "age_s": round(age, 1),
                    "pending": int(pending), "unrun": int(unrun),
                    "step_inflight": int(step_i), "step_capacity": int(step_c),
                    "daemons": daemons, "daemons_up": up}
    raise ValueError("scheduler 日志尾 64KB 内无 queue/daemons 行")


def _seed_offset() -> None:
    """router 增量游标种子=当前文件大小（main 启动时调一次；失败由调用方按缺失处理）。"""
    global _router_offset
    _router_offset = os.path.getsize(ROUTER_LOG)


def collect_router() -> dict:
    """时间戳行增量计数（跨周期游标；启动时游标种子=当前文件大小，只数边车存活期新增；
    文件变短=截断/换轨→游标归零重计）。"""
    global _router_offset, _router_reset_logged
    size = os.path.getsize(ROUTER_LOG)
    if size < _router_offset:      # 截断/轮换
        _router_offset = 0
        if not _router_reset_logged:
            log("router 日志变短（截断/换轨），游标归零重计")
            _router_reset_logged = True
    else:
        _router_reset_logged = False
    with open(ROUTER_LOG, "rb") as f:
        f.seek(_router_offset)
        chunk = f.read().decode(errors="replace")
        _router_offset = f.tell()
    n = sum(1 for ln in chunk.splitlines() if ROUTER_TS_RE.match(ln))
    return {"ok": True, "events_delta": n, "offset": _router_offset, "size": size}


def collect_kb() -> dict:
    """kb/store.py stats() 只读跑（mode=ro 连接；绕过 KBStore.__init__ 写面）。"""
    import kb.store as kb_store  # noqa: PLC0415  运行时导入，WS 已在 sys.path
    store = kb_store.KBStore.__new__(kb_store.KBStore)   # 不跑 __init__（WAL/schema 写面）
    store.path = str(KB_DB)
    uri = "file:" + urllib.request.pathname2url(os.path.abspath(KB_DB)) + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=10)
    try:
        store._conn = conn
        st = store.stats()          # kb/store.py:330 原逻辑，单一真源
    finally:
        conn.close()
    return {"ok": True, "total": st["total"], "by_status": st["by_status"],
            "provenance_events": st["provenance_events"], "db_size_bytes": st["db_size_bytes"]}


def collect_anolis() -> dict:
    """anolis 只读 ssh：pending 条数 + af-order 在途进程数（与 scheduler 同口径）。"""
    cmd = ("ls /data/bench/queue/pending/*.json 2>/dev/null | wc -l; "
           "pgrep -c af-order 2>/dev/null; true")
    r = subprocess.run(["ssh", *SSH_OPTS, "anolis", cmd],
                       capture_output=True, text=True, timeout=45)
    nums = [int(x) for x in re.findall(r"\d+", r.stdout)]
    if r.returncode != 0 or len(nums) < 2:
        raise RuntimeError(f"anolis 探针异常 rc={r.returncode} "
                           f"out={(r.stdout or '').strip()[:60]!r} err={(r.stderr or '').strip()[:60]!r}")
    return {"ok": True, "queue_depth": nums[0], "inflight": nums[1]}


def collector_alive() -> bool:
    """collector PID 文件 + cmdline 双校验（与 run/stop-collector 同口径，防 PID 回收误判）。"""
    try:
        pid = int(open(COLLECTOR_PIDFILE).read().strip())
    except (OSError, ValueError):
        return False
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            return b"otelcol" in f.read()
    except OSError:
        return False


# --------------------------------------------------------------------------- #
# 语义层腿（A1）：投影器中继。只读订单产物 → 正本四名四层树 → 原子缓存。
# 真源与投影器/断言器同一套（af-otel-projector.py），本件只做中继不改数据。
# --------------------------------------------------------------------------- #

def _project_order_spans(order_dir: str) -> tuple[list, list]:
    """对一单跑投影器（子进程，只读）。返回 (spans, findings)。"""
    import tempfile  # noqa: PLC0415
    fd, tmp_out = tempfile.mkstemp(prefix="af-sidecar-proj-", suffix=".jsonl")
    os.close(fd)
    try:
        r = subprocess.run(
            ["python3", "-I", PROJECTOR, "project", order_dir, "--out", tmp_out],
            capture_output=True, text=True, timeout=SEMANTIC_PROJECT_TIMEOUT, cwd=WS)
        if r.returncode != 0:
            raise RuntimeError(f"投影器 rc={r.returncode}: "
                               f"{(r.stderr or '').strip()[:160]!r}")
        spans = [json.loads(l) for l in open(tmp_out, encoding="utf-8")
                 if l.strip()]
        findings = [l[len("finding: "):] for l in (r.stderr or "").splitlines()
                    if l.startswith("finding: ")]
        return spans, findings
    finally:
        try:
            os.unlink(tmp_out)
        except OSError:
            pass


def _canonical_spans(spans: list) -> str:
    return json.dumps(spans, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))


def load_semantic_cache() -> dict | None:
    """读语义缓存；缺席/坏 JSON/超龄 ⇒ None（发射与回放统一走 fail-closed）。"""
    try:
        st = os.stat(SEMANTIC_CACHE)
        if int(time.time() * 1000) - int(st.st_mtime * 1000) > SEMANTIC_CACHE_MAX_AGE_MS:
            return None
        with open(SEMANTIC_CACHE, encoding="utf-8") as fh:
            cache = json.load(fh)
        if not isinstance(cache, dict) or not isinstance(cache.get("spans"), list):
            return None
        return cache
    except (OSError, ValueError, TypeError):
        return None


def collect_semantic_leg() -> dict:
    """选最新可投影出全四层（正本四名各 ≥1）的订单 → 投影 → 原子刷缓存。

    中继节流：树内容变（relay_key 变）或距上次中继 ≥ SEMANTIC_RELAY_MIN_MS
    ⇒ relay=True（当轮允许真库中继）。缓存内容每轮刷到最新投影；缓存写失败
    只记该源 error（绝不外抛），旧缓存继续服役直至超龄。
    """
    if not os.path.isdir(ORDERS_DIR):
        raise RuntimeError(f"订单目录不在位：{ORDERS_DIR}")
    cands = []
    for name in sorted(os.listdir(ORDERS_DIR)):
        d = os.path.join(ORDERS_DIR, name)
        ledger = os.path.join(d, "ledger.jsonl")
        if os.path.isdir(d) and os.path.isfile(ledger):
            try:
                cands.append((os.stat(ledger).st_mtime, name, d))
            except OSError:
                continue
    cands.sort(reverse=True)
    now_ms = int(time.time() * 1000)
    for _mtime, name, d in cands[:SEMANTIC_CANDIDATES]:
        spans, findings = _project_order_spans(d)
        names = {s.get("name") for s in spans}
        if not all(n in names for n in ROSTER_NAMES):
            continue  # 半树不中继（C1 需要四层齐全才可断言 S 族）
        relay_key = hashlib.sha256(_canonical_spans(spans).encode("utf-8")).hexdigest()
        try:
            with open(SEMANTIC_CACHE, encoding="utf-8") as fh:
                prev = json.load(fh)
        except (OSError, ValueError, TypeError):
            prev = {}
        relay = (prev.get("relay_key") != relay_key
                 or now_ms - int(prev.get("relayed_at_ms") or 0) >= SEMANTIC_RELAY_MIN_MS)
        cache = {"ts_ms": now_ms, "order_id": name, "relay_key": relay_key,
                 "relayed_at_ms": now_ms if relay else prev.get("relayed_at_ms"),
                 "spans": spans,
                 "findings_count": len(findings)}
        tmp = SEMANTIC_CACHE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(cache, fh, ensure_ascii=False, indent=1)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, SEMANTIC_CACHE)
        out = {"ok": True, "order_id": name, "spans": len(spans),
               "findings_count": len(findings), "relay": relay}
        if findings:
            out["note"] = f"findings={len(findings)}"
        return out
    return {"ok": False, "error": "候选订单均无全四层树（正本四名未齐全）"}


# --------------------------------------------------------------------------- #
# 发射（经既有发射器；熔断/禁用语义全在 otel_emit 内，本件只组 payload）
# --------------------------------------------------------------------------- #
def emit_round(round_no: int, ts_ms: int, metrics: dict, src_ok: dict,
               *, relay_semantic: bool = True) -> dict:
    """1 span（本轮汇总）+ N gauge；每点带 af.sidecar.round 供 CH 精确查回。

    语义层腿（A1）：`relay_semantic` 缺省 True —— 断言器 --sidecar 以四实参
    复演本函数时，语义树**恒**经发射器路径复原（otel_emit._post 被本地截获、
    零网络），补齐语义层覆盖（此前 0/4 → S/N/R 断言族 VACUOUS）。活体周期
    显式传 relay_semantic=当轮中继判定：False 的轮次不呼语义 emit_span
    （零 CH 增生）；True 的轮次把时间戳改写为当轮 ts（点跨度，RT-E138 同款）
    以落入 --production 近窗。快照 emit.semantic_spans 记当轮**实发**条数。
    """
    res = otel_emit.resource(service=SERVICE)
    rnd = str(round_no)
    tid = otel_emit.trace_id_for(None, "sidecar", ts_ms)
    sid = otel_emit.span_id_for("sidecar-round", str(ts_ms))
    attrs = {"af.factory.domain": "sidecar", "af.factory.mode": "daemon",
             "af.sidecar.round": round_no, "af.sidecar.cycle_ts_ms": ts_ms,
             "af.sidecar.sources_ok": f"{sum(src_ok.values())}/{len(src_ok)}"}
    for k, v in metrics.items():
        attrs[f"af.sidecar.{k}"] = v
    ok = otel_emit.emit_span("factory.sidecar_round", trace_id=tid, span_id=sid,
                             kind=1, start_ns=ts_ms * 1_000_000, end_ns=ts_ms * 1_000_000,
                             attributes=attrs, res=res)
    gauges = [
        ("factory.sidecar_queue_pending", "scheduler-log"),
        ("factory.sidecar_queue_unrun", "scheduler-log"),
        ("factory.sidecar_step_inflight", "scheduler-log"),
        ("factory.sidecar_step_capacity", "scheduler-log"),
        ("factory.sidecar_daemons_up", "scheduler-log"),
        ("factory.sidecar_router_events", "router-log"),
        ("factory.sidecar_kb_atoms_total", "kb-store"),
        ("factory.sidecar_kb_atoms_verified", "kb-store"),
        ("factory.sidecar_kb_atoms_candidate", "kb-store"),
        ("factory.sidecar_kb_provenance_events", "kb-store"),
        ("factory.sidecar_anolis_queue_depth", "anolis-ssh"),
        ("factory.sidecar_anolis_inflight", "anolis-ssh"),
        ("factory.sidecar_collector_alive", "sidecar-meta"),
    ]
    n_metrics = 0
    for name, src in gauges:
        val = metrics.get(name.rsplit("factory.sidecar_", 1)[1])
        if val is None:
            continue                      # 该源失败→不发射该点（快照里留 null+error）
        kind = "sum" if name == "factory.sidecar_router_events" else "gauge"
        if otel_emit.emit_metric(name, float(val), unit="1", kind=kind,
                                 attributes={"af.sidecar.round": rnd,
                                             "af.factory.source": src},
                                 res=res):
            n_metrics += 1
    n_semantic = 0
    if relay_semantic:
        cache = load_semantic_cache()
        if cache:
            ns = ts_ms * 1_000_000       # 中继/复原统一点跨度（发射时刻）
            for sp in cache["spans"]:
                plain_res = sp.get("resource") or {}
                res_otlp = {"attributes": otel_emit._attrs(plain_res)}
                if otel_emit.emit_span(
                        sp.get("name"), trace_id=sp.get("traceId"),
                        span_id=sp.get("spanId"),
                        parent_span_id=sp.get("parentSpanId")
                        or otel_emit.INVALID_SPAN_ID,
                        kind=sp.get("kind", 1), start_ns=ns, end_ns=ns,
                        attributes=sp.get("attributes") or {}, res=res_otlp,
                        scope="af-otel-projector"):
                    n_semantic += 1
    st = otel_emit.stats()
    return {"span_sent": ok, "metrics_sent": n_metrics,
            "semantic_spans": n_semantic,
            "spans": st["spans"], "metrics": st["metrics"], "errors": st["errors"],
            "skipped_stop": st["skipped_stop"]}


# --------------------------------------------------------------------------- #
# 周期
# --------------------------------------------------------------------------- #
def cycle(round_no: int) -> None:
    rotate_log(SIDECAR_LOG)          # 边车自身日志轮转
    rotate_log(COLLECTOR_LOG)        # 常驻期兼驱 collector 日志轮转（同逻辑同阈值）

    if otel_emit.stop_active():
        log(f"round={round_no} STOP 熔断在位（状态观测/OTEL-STOP）——不发射、不刷快照")
        return

    ts_ms = int(time.time() * 1000)
    sources: dict[str, dict] = {}
    errors: dict[str, str] = {}

    def run(name, fn):
        try:
            sources[name] = fn()
        except Exception as e:  # noqa: BLE001 —— 异常只记该源，绝不外抛
            sources[name] = {"ok": False}
            errors[name] = f"{type(e).__name__}: {str(e)[:160]}"
            log(f"round={round_no} 源 {name} 失败（不影响其他源）: {errors[name]}")

    run("scheduler_log", collect_scheduler)
    run("router_log", collect_router)
    run("kb_store", collect_kb)
    run("anolis_ssh", collect_anolis)
    run("semantic_leg", collect_semantic_leg)

    s, r, k, a = (sources["scheduler_log"], sources["router_log"],
                  sources["kb_store"], sources["anolis_ssh"])
    sem = sources["semantic_leg"]
    metrics = {
        "queue_pending": s.get("pending"),
        "queue_unrun": s.get("unrun"),
        "step_inflight": s.get("step_inflight"),
        "step_capacity": s.get("step_capacity"),
        "daemons_up": s.get("daemons_up"),
        "router_events": r.get("events_delta"),
        "kb_atoms_total": k.get("total"),
        "kb_atoms_verified": (k.get("by_status") or {}).get("verified"),
        "kb_atoms_candidate": (k.get("by_status") or {}).get("candidate"),
        "kb_provenance_events": k.get("provenance_events"),
        "anolis_queue_depth": a.get("queue_depth"),
        "anolis_inflight": a.get("inflight"),
        "collector_alive": 1 if collector_alive() else 0,
    }
    src_ok = {n: bool(v.get("ok")) for n, v in sources.items()}
    emit = emit_round(round_no, ts_ms, metrics, src_ok,
                      relay_semantic=bool(sem.get("relay")))

    snap = {"ts": ts_ms, "generated_at": time.strftime("%F %T"),
            "source": "tools/otel/emit-sidecar.py", "round": round_no,
            "interval_s": int(os.environ.get("OTEL_SIDECAR_INTERVAL") or 30),
            "stop_active": False, "collector_endpoint": DEFAULT_ENDPOINT,
            "metrics": metrics, "sources": sources, "emit": emit, "errors": errors}
    tmp = SNAPSHOT + ".tmp"
    os.makedirs(os.path.dirname(SNAPSHOT), exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=1)
    os.replace(tmp, SNAPSHOT)         # 原子落盘（读方不看半截）

    sem_txt = (f"semantic(order={sem.get('order_id')},spans={sem.get('spans')},"
               f"relay={sem.get('relay')}) " if sem.get("ok")
               else "semantic(err) ")
    log(f"round={round_no} 源 {sum(src_ok.values())}/{len(src_ok)} "
        f"emit(span={emit['span_sent']} metrics={emit['metrics_sent']} "
        f"semantic={emit['semantic_spans']} errors={emit['errors']}) "
        f"queue(pending={metrics['queue_pending']},unrun={metrics['queue_unrun']},"
        f"step={metrics['step_inflight']}/{metrics['step_capacity']}) "
        f"kb(total={metrics['kb_atoms_total']}) "
        f"anolis(depth={metrics['anolis_queue_depth']},inflight={metrics['anolis_inflight']}) "
        f"{sem_txt}"
        f"snapshot={os.path.relpath(SNAPSHOT, WS)}")


def _sig(_signum, _frame):
    global _stop
    _stop = True


def main() -> int:
    global _stop
    ap = argparse.ArgumentParser(description="产线可观测边车（30s 周期 gauge/span 发射）")
    ap.add_argument("--once", action="store_true", help="单周期后退出（验证用）")
    ap.add_argument("--interval", type=float,
                    default=float(os.environ.get("OTEL_SIDECAR_INTERVAL") or 30),
                    help="周期秒数（缺省 30）")
    a = ap.parse_args()
    os.environ["OTEL_SIDECAR_INTERVAL"] = str(int(a.interval))

    signal.signal(signal.SIGTERM, _sig)
    signal.signal(signal.SIGINT, _sig)

    # router 增量游标种子=当前文件大小（边车只数自己存活期的新增行，重启不重复计历史）
    try:
        _seed_offset()
    except OSError:
        pass

    os.makedirs(os.path.dirname(PIDFILE), exist_ok=True)
    with open(PIDFILE, "w") as f:
        f.write(str(os.getpid()))
    log(f"起（pid={os.getpid()} interval={a.interval}s once={a.once} "
        f"endpoint={otel_emit.endpoint() or 'None(AF_OTEL_DISABLE?)'} "
        f"stop_file={otel_emit.STOP_FILE} scrub={otel_emit.scrub_source()} "
        f"snapshot={os.path.relpath(SNAPSHOT, WS)} pidfile={PIDFILE})")
    try:
        round_no = 0
        while not _stop:
            round_no += 1
            try:
                cycle(round_no)
            except Exception as e:  # noqa: BLE001 —— 周期级兜底：只记日志不崩
                log(f"round={round_no} 周期异常（不崩，下轮继续）: {type(e).__name__}: {e}")
            if a.once:
                break
            slept = 0.0
            while slept < a.interval and not _stop:   # 分片睡，SIGTERM 灵敏收尾
                time.sleep(min(1.0, a.interval - slept))
                slept += 1.0
    finally:
        try:
            if int(open(PIDFILE).read().strip()) == os.getpid():
                os.remove(PIDFILE)
        except (OSError, ValueError):
            pass
        log(f"停（pid={os.getpid()} rounds={round_no} pidfile 已清理）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
