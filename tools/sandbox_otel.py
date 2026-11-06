#!/usr/bin/env python3
"""sandbox_otel.py — 沙箱观测信标发射器（L3；OTLP/HTTP JSON，stdlib-only，fail-open）。

契约：波次清单/沙箱派发契约.md §8（2026-11-06 D-82 批增补；D-96 落地件）。
  · §8.1 窄豁免=唯一端点 https://otlp.hkmingdajiaoyu.com 的 POST /v1/traces 与 /v1/metrics
    （Bearer $AF_OTLP_INGEST_TOKEN，120rpm/4MB）；禁扩大出网白名单。
  · §8.3 三类信标：sandbox.milestone span / sandbox.heartbeat gauge / sandbox.retries_total counter。
  · §8.4 身份键 + D-96 卡禁项：af.work_order_id/order_id/run_id + af.sandbox.label 落 **span 属性面**、
    **不落 Resource**。依据 otlp-assert.py:945-951——订单域总体只看 ResourceAttributes 订单键 ∪
    语义层 span 名；sandbox.* 非语义名且 Resource 无订单键 ⇒ 不计入订单域总体，不触发 P2~P5 判红。
  · §8.5 熔断：连续 3 次失败**或**任一次 401 ⇒ 停发 + 回报登记「L3 未遂」；fail-open 绝不抛回调用方。
母本 tools/otel/otel_emit.py（stdlib-only / fail-open / 熔断 / 确定性 trace_id 派生式照抄；本件为
  ~信标专用精简件，自包含可作 <BEACON_SNIPPET> 内联，不依赖仓内其他模块）。
零明文：token 只经 env AF_OTLP_INGEST_TOKEN 进 Authorization header，不进本件/argv/日志/diff；
  属性面只收枚举值与命令退出码（禁自由文本——故不需 scrub 真源，调用契约即保证）。
"""
import hashlib
import json
import os
import time
import urllib.error
import urllib.request

WS = os.path.expanduser("~/workspace/agent黑灯工厂")
INVALID_SPAN_ID = "0" * 16
DEFAULT_ENDPOINT = "https://otlp.hkmingdajiaoyu.com"   # §8.1 窄豁免唯一端点
STOP_FILE = os.environ.get("AF_OTEL_STOP") or os.path.join(WS, "状态观测/OTEL-STOP")
STOP_AFTER = 3                                          # §8.5 连续失败熔断阈值

# 进程内记账（fail-open：只计数，无外部副作用，绝不抛回调用方）
_state = {"sent": 0, "errors": 0, "consecutive": 0, "tripped": False, "last_error": ""}


def endpoint():
    """§8.1 端点。AF_OTEL_DISABLE=1 整线静默；AF_OTEL_ENDPOINT 覆盖优先（本地演练用）。"""
    if os.environ.get("AF_OTEL_DISABLE") == "1":
        return None
    return os.environ.get("AF_OTEL_ENDPOINT") or DEFAULT_ENDPOINT


def stop_active():
    """停机熔断：STOP 文件在场或进程内已 tripped ⇒ 停发。"""
    return os.path.exists(STOP_FILE) or _state["tripped"]


def stats():
    return dict(_state)


def l3_note():
    """§8.5 交卷回报登记行：熔断时才非空——「L3 未遂：<末次错误形态>，共尝试 N 次」。"""
    if _state["tripped"]:
        return "L3 未遂：%s，共尝试 %d 次" % (_state["last_error"] or "-", _state["errors"])
    return ""


def reset():
    """演练复位（仅测试用）：清空进程内记账与熔断。"""
    _state.update({"sent": 0, "errors": 0, "consecutive": 0, "tripped": False, "last_error": ""})


# --------------------------------------------------------------------------- #
# §1.0 确定性 ID 派生（照 otel_emit.py / otlp-model §1.0：同种子→同 ID，后端按主键去重）
# --------------------------------------------------------------------------- #
def _sha(seed, n):
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:n]


def trace_id_for(work_order_id):
    """§8.4：信标挂到订单 trace —— SHA-256("af-trace-v1|"+work_order_id)。"""
    return _sha("af-trace-v1|" + (work_order_id or ""), 32)


def span_id_for(*parts):
    return _sha("af-span-v1|" + "|".join(str(p) for p in parts), 16)


# --------------------------------------------------------------------------- #
# OTLP JSON 构件（属性面只收枚举与退出码；身份键落 span 属性面，不落 Resource）
# --------------------------------------------------------------------------- #
def _attr(v):
    if isinstance(v, bool):
        return {"boolValue": v}
    if isinstance(v, int):
        return {"intValue": str(v)}
    return {"stringValue": str(v)}   # 只由枚举/退出码喂入，禁自由文本（调用契约）


def _attrs(d):
    return [{"key": k, "value": _attr(v)} for k, v in sorted(d.items())]


def _resource():
    # 身份键不落 Resource（避免判据面判红）；Resource 只放 service 名/版本
    return {"attributes": _attrs({"service.name": "af-sandbox",
                                  "service.version": "sandbox-otel-20261107"})}


def _identity(work_order_id, order_id, run_id, label):
    a = {}
    if work_order_id:
        a["af.work_order_id"] = work_order_id
    if order_id:
        a["af.order_id"] = order_id
    if run_id:
        a["af.run_id"] = run_id
    if label:
        a["af.sandbox.label"] = label
    return a


def _post(path, payload, timeout):
    ep = endpoint()
    tok = os.environ.get("AF_OTLP_INGEST_TOKEN", "")
    headers = {"Content-Type": "application/json"}
    if tok:
        headers["Authorization"] = "Bearer " + tok   # §8.2：token 只在此处经 env 进 header
    req = urllib.request.Request(ep.rstrip("/") + path,
                                 data=json.dumps(payload, ensure_ascii=False).encode(),
                                 headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        r.read()


def _emit(path, payload, timeout):
    """fail-open 发射 + §8.5 熔断。返回 True=已发；False=未发（熔断/禁用/失败，均已静默记账）。"""
    if endpoint() is None or stop_active():
        return False
    try:
        _post(path, payload, timeout)
        _state["sent"] += 1
        _state["consecutive"] = 0
        return True
    except urllib.error.HTTPError as e:
        _state["errors"] += 1
        _state["consecutive"] += 1
        _state["last_error"] = "HTTP %s" % e.code
        if e.code == 401 or _state["consecutive"] >= STOP_AFTER:   # §8.5：401 或连 3 失败
            _state["tripped"] = True
        return False
    except Exception as e:  # noqa: BLE001 —— 非关键 lane fail-open，绝不抛回调用方
        _state["errors"] += 1
        _state["consecutive"] += 1
        _state["last_error"] = type(e).__name__
        if _state["consecutive"] >= STOP_AFTER:
            _state["tripped"] = True
        return False


# --------------------------------------------------------------------------- #
# §8.3 三类信标
# --------------------------------------------------------------------------- #
def milestone(event, *, work_order_id=None, order_id=None, run_id=None, label=None,
              exit_code=0, timeout=3.0):
    """§8.3a 里程碑 span。event=枚举（clone_done/precheck/push_branch/pr_open/gates_change/
    handoff/e2e_probe…）；exit_code=命令退出码；每 (order,event) 一个确定性 span（幂等重放）。"""
    attrs = _identity(work_order_id, order_id, run_id, label)
    attrs["af.sandbox.event"] = event
    attrs["af.sandbox.exit_code"] = int(exit_code)
    now = time.time_ns()
    sp = {"traceId": trace_id_for(work_order_id),
          "spanId": span_id_for(work_order_id or "", event),
          "parentSpanId": INVALID_SPAN_ID,
          "name": "sandbox.milestone", "kind": 1,
          "startTimeUnixNano": str(now), "endTimeUnixNano": str(now),
          "attributes": _attrs(attrs),
          "status": {"code": int(exit_code)} if exit_code else {}}
    payload = {"resourceSpans": [{"resource": _resource(), "scopeSpans": [
        {"scope": {"name": "af-sandbox-lane"}, "spans": [sp]}]}]}
    return _emit("/v1/traces", payload, timeout)


def heartbeat(minutes, *, phase, work_order_id=None, order_id=None, run_id=None,
              label=None, timeout=3.0):
    """§8.3b 心跳 gauge：value=会话起始分钟数；phase=枚举
    （cloning/precheck/coding/pushing/await-gates/fixing/done/stopped）。"""
    attrs = _identity(work_order_id, order_id, run_id, label)
    attrs["af.sandbox.phase"] = phase
    now = time.time_ns()
    dp = {"attributes": _attrs(attrs), "startTimeUnixNano": str(now),
          "timeUnixNano": str(now), "asDouble": float(minutes)}
    m = {"name": "sandbox.heartbeat", "unit": "min", "gauge": {"dataPoints": [dp]}}
    payload = {"resourceMetrics": [{"resource": _resource(), "scopeMetrics": [
        {"scope": {"name": "af-sandbox-lane"}, "metrics": [m]}]}]}
    return _emit("/v1/metrics", payload, timeout)


def retry(kind, *, work_order_id=None, order_id=None, run_id=None, label=None, timeout=3.0):
    """§8.3c 重试 counter：每次 +1；kind=枚举（gate-red/token-expired/push-failed/scrub-hit）。"""
    attrs = _identity(work_order_id, order_id, run_id, label)
    attrs["af.sandbox.kind"] = kind
    now = time.time_ns()
    dp = {"attributes": _attrs(attrs), "startTimeUnixNano": str(now),
          "timeUnixNano": str(now), "asDouble": 1.0}
    m = {"name": "sandbox.retries_total", "unit": "1",
         "sum": {"dataPoints": [dp], "aggregationTemporality": 2, "isMonotonic": True}}
    payload = {"resourceMetrics": [{"resource": _resource(), "scopeMetrics": [
        {"scope": {"name": "af-sandbox-lane"}, "metrics": [m]}]}]}
    return _emit("/v1/metrics", payload, timeout)
