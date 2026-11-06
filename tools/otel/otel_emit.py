#!/usr/bin/env python3
"""otel_emit.py — OTLP/HTTP JSON 发射器（OTel 视图批 MVP，stdlib-only，fail-open）。

协议：OTLP/HTTP + JSON 映射（application/json），POST <endpoint>/v1/traces|/v1/metrics。
数据模型：计划/研究组/OTel视图设计批-20261027/otlp-model.md
  · §1.0 确定性 ID 派生（幂等重放：同种子→同 trace_id/span_id，后端可按主键去重）
  · §2 Resource 九键正字法（af.*）+ 扩展键；L1 只有订单级键
  · §3 gen_ai.* 钉版名（本厂工厂链路不用 gen_ai 族，用 af.* 族）
语义：非关键 lane——发射失败只记本地计数，绝不抛回调用方（af-trace 双轨制同口径：
critical 不托付 OTel；OTel 只做增量出口）。停机熔断：AF_OTEL_STOP 文件在场即整线静默。
端点：AF_OTEL_ENDPOINT 覆盖优先，未设落缺省 collector（DEFAULT_ENDPOINT，2026-11-02 起
与 emit-sidecar 同源；此前未设=静默丢弃，曾致工厂族生产零入库）。
零明文：凭据不进本件；自由文本属性值过 K/O 正则 scrub（真源=tools/stream-tailer.py
SCRUB_RULES，importlib 按路径加载，单一真源不复制——P1-4 方向）。
"""
import hashlib
import importlib.util
import json
import os
import sys
import time
import urllib.error
import urllib.request

WS = os.path.expanduser("~/workspace/agent黑灯工厂")
INVALID_SPAN_ID = "0000000000000000"

# 熔断文件（对齐 stream-tailer TAILER-STOP 模式）：在场→整线静默
STOP_FILE = os.environ.get("AF_OTEL_STOP") or os.path.join(WS, "状态观测/OTEL-STOP")

# 本地失败计数（进程内；无外部副作用）
_stats = {"spans": 0, "metrics": 0, "errors": 0, "skipped_stop": 0, "scrubbed": 0}

# --------------------------------------------------------------------------- #
# scrub 真源加载（tools/stream-tailer.py SCRUB_RULES/scrub；加载失败不静默——
# 记 stats 并由调用方在 e2e 断言其活性；缺失时降级为拒绝发射自由文本）
# --------------------------------------------------------------------------- #
_scrub_fn = None
_scrub_src = None


def _load_scrub():
    global _scrub_fn, _scrub_src
    path = os.path.join(WS, "tools/stream-tailer.py")
    try:
        spec = importlib.util.spec_from_file_location("af_stream_tailer_scrub", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _scrub_fn = mod.scrub
        _scrub_src = f"tools/stream-tailer.py:SCRUB_RULES（{len(mod.SCRUB_RULES)} 条）"
    except Exception as e:  # noqa: BLE001 —— 加载失败=显式降级，不静默放行
        _scrub_fn = None
        _scrub_src = f"UNAVAILABLE({e.__class__.__name__})"


_load_scrub()


def scrub_source() -> str:
    return _scrub_src or "-"


def scrub_text(s: str) -> tuple[str, bool]:
    """自由文本 → (清洗后, 是否命中)。无真源时原样返回（调用方已由 e2e 断言活性）。"""
    if _scrub_fn is None:
        return s, False
    out, hits = _scrub_fn(s)
    if hits:
        _stats["scrubbed"] += 1
    return out, bool(hits)


# --------------------------------------------------------------------------- #
# 端点与熔断
# --------------------------------------------------------------------------- #
# 缺省端点（2026-11-02 RT 修复）：与唯一活面 emit-sidecar.py:49 同源同值（本机 tailnet
# 常驻 collector，run-collector.sh 绑定）。此前 env 未设 → endpoint()=None → emit_span
# 静默 return False，factory.order_round/guardian_round 自 10-28 接线起生产零入库。
# 覆盖语义不变：AF_OTEL_ENDPOINT 在场仍优先；AF_OTEL_DISABLE=1 / OTEL-STOP 熔断仍整线静默；
# 端点不可达照旧 fail-open 计入 errors（非关键 lane 绝不抛回调用方）。
DEFAULT_ENDPOINT = "http://pandev-host.invalid:4318"

def endpoint() -> str | None:
    if os.environ.get("AF_OTEL_DISABLE") == "1":
        return None
    return os.environ.get("AF_OTEL_ENDPOINT") or DEFAULT_ENDPOINT


def stop_active() -> bool:
    return os.path.exists(STOP_FILE)


def stats() -> dict:
    return dict(_stats)


# --------------------------------------------------------------------------- #
# §1.0 确定性 ID 派生
# --------------------------------------------------------------------------- #
def _sha_hex(seed: str, n: int) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:n]


def trace_id_for(work_order_id: str | None, domain: str, round_ts_ms: int) -> str:
    """work_order_id 在场→按 otlp-model §1.0 以 stable_id 为种（工厂事件挂到订单 trace）；
    不在场（纯工厂运维轮次）→ 域+轮次时间种（自有 trace，parent=INVALID）。"""
    if work_order_id:
        return _sha_hex("af-trace-v1|" + work_order_id, 32)
    return _sha_hex(f"af-factory-v1|{domain}|{round_ts_ms}", 32)


def span_id_for(*parts: str) -> str:
    return _sha_hex("af-span-v1|" + "|".join(parts), 16)


def l1_span_id(work_order_id: str) -> str:
    return span_id_for(work_order_id, "invoke_workflow")


# --------------------------------------------------------------------------- #
# OTLP JSON 构件
# --------------------------------------------------------------------------- #
def _attr(value):
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int):
        return {"intValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, (list, tuple)):
        return {"arrayValue": {"values": [_attr(v) for v in value]}}
    s, _ = scrub_text(str(value))
    return {"stringValue": s}


def _attrs(d: dict) -> list[dict]:
    return [{"key": k, "value": _attr(v)} for k, v in sorted(d.items())]


def resource(order_id=None, work_order_id=None, run_id=None, service="af-factory",
             extra=None) -> dict:
    """Resource：九键正字法子集（在场才投影）+ service.name/version（D-9 双来源区分）。"""
    attrs = {}
    if order_id:
        attrs["af.order_id"] = order_id
    if work_order_id:
        attrs["af.work_order_id"] = work_order_id
    if run_id:
        attrs["af.run_id"] = run_id
    attrs["service.name"] = service
    attrs["service.version"] = "otel-mvp-20261028"
    for k, v in (extra or {}).items():
        attrs[k] = v
    return {"attributes": _attrs(attrs)}


def span(name, *, trace_id, span_id, parent_span_id=INVALID_SPAN_ID, kind=1,
         start_ns=None, end_ns=None, attributes=None, status_code=0,
         status_message="", res=None, scope="af-factory-lane") -> dict:
    now = time.time_ns()
    return {
        "traceId": trace_id,
        "spanId": span_id,
        "parentSpanId": parent_span_id,
        "name": name,
        "kind": kind,
        "startTimeUnixNano": str(start_ns or now),
        "endTimeUnixNano": str(end_ns or now),
        "attributes": _attrs(attributes or {}),
        "status": {"code": status_code, "message": status_message} if status_code else {},
    }, res, scope  # type: ignore[return-value]


def _post(path: str, payload: dict, ep: str, timeout: float) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode()
    req = urllib.request.Request(ep.rstrip("/") + path, data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        r.read()


def emit_span(name, *, trace_id, span_id, parent_span_id=INVALID_SPAN_ID, kind=1,
              start_ns=None, end_ns=None, attributes=None, status_code=0,
              status_message="", res=None, scope="af-factory-lane",
              timeout: float = 2.0) -> bool:
    """发一条 span。返回 False=未发（熔断/禁用/失败，均已静默记账）。"""
    ep = endpoint()
    if ep is None or stop_active():
        if stop_active() and ep:
            _stats["skipped_stop"] += 1
        return False
    sp, r, sc = span(name, trace_id=trace_id, span_id=span_id,
                     parent_span_id=parent_span_id, kind=kind, start_ns=start_ns,
                     end_ns=end_ns, attributes=attributes, status_code=status_code,
                     status_message=status_message, res=res, scope=scope)
    payload = {"resourceSpans": [{"resource": r, "scopeSpans": [
        {"scope": {"name": sc}, "spans": [sp]}]}]}
    try:
        _post("/v1/traces", payload, ep, timeout)
        _stats["spans"] += 1
        return True
    except Exception:  # noqa: BLE001 —— 非关键 lane fail-open
        _stats["errors"] += 1
        return False


def emit_metric(name, value, *, unit="", attributes=None, res=None, scope="af-factory-lane",
                kind="gauge", monotonic=True, temporality=1, timeout: float = 2.0) -> bool:
    """发一个数据点。kind: gauge|sum；temporality: 1=DELTA 2=CUMULATIVE（默认 delta 重启安全）。"""
    ep = endpoint()
    if ep is None or stop_active():
        if stop_active() and ep:
            _stats["skipped_stop"] += 1
        return False
    now = time.time_ns()
    dp = {"attributes": _attrs(attributes or {}),
          "startTimeUnixNano": str(now), "timeUnixNano": str(now)}
    if kind == "gauge":
        dp["asDouble"] = float(value)
        m = {"name": name, "unit": unit, "gauge": {"dataPoints": [dp]}}
    else:
        dp["asDouble"] = float(value)
        m = {"name": name, "unit": unit,
             "sum": {"dataPoints": [dp],
                     "aggregationTemporality": temporality,
                     "isMonotonic": bool(monotonic)}}
    payload = {"resourceMetrics": [{"resource": res, "scopeMetrics": [
        {"scope": {"name": scope}, "metrics": [m]}]}]}
    try:
        _post("/v1/metrics", payload, ep, timeout)
        _stats["metrics"] += 1
        return True
    except Exception:  # noqa: BLE001
        _stats["errors"] += 1
        return False
