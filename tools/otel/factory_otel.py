#!/usr/bin/env python3
"""factory_otel.py — 工厂链路（订单/守护/收割）关键事件的 OTel 埋点助手。

调用方（常驻脚本，各自保留既有 STOP 熔断与幂等语义，本助手只增量、不改行为）：
  · 订单   tools/factory-scheduler.py   → order_round()    队列守恒轮次
  · 守护   tools/factory-keepalive.py    → guardian_round() 看护探活轮次
  · 收割   tools/sandbox-harvester.py    → harvest_report() 单报告校验

纪律：
  · 端点缺省——AF_OTEL_ENDPOINT 未设时落 otel_emit.DEFAULT_ENDPOINT（与 emit-sidecar
    同源，2026-11-02 起；此前未设=静默丢弃、工厂族生产零入库）；AF_OTEL_DISABLE=1
    或 OTEL-STOP 熔断在场才空转（立即返回 False、零网络）；
  · fail-open——发射失败只进进程内计数（otel_emit.stats()），绝不抛回调用方；
  · 熔断——状态观测/OTEL-STOP 在场即整线静默（对齐 stream-tailer TAILER-STOP 模式）；
  · 自由文本属性值全部过 scrub 真源（stream-tailer.py SCRUB_RULES）。
span/metric 形状：otlp-model.md §1.0 派生 ID + §2 Resource 键名 + af.factory.* 属性族。
"""
import sys
import time

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import otel_emit  # noqa: E402


def enabled() -> bool:
    return otel_emit.endpoint() is not None and not otel_emit.stop_active()


def _now_ms() -> int:
    return int(time.time() * 1000)


def order_round(*, pending, in_flight, triggered=(), mode="daemon", ts_ms=None,
                order_id=None, work_order_id=None, service="factory-scheduler") -> bool:
    """订单面一轮队列守恒观测 → 1 span + 2 gauge + N delta counter。"""
    ts = ts_ms or _now_ms()
    tid = otel_emit.trace_id_for(work_order_id, "order", ts)
    sid = otel_emit.span_id_for("order-round", str(ts))
    parent = otel_emit.l1_span_id(work_order_id) if work_order_id else otel_emit.INVALID_SPAN_ID
    res = otel_emit.resource(order_id=order_id, work_order_id=work_order_id,
                             service=service)
    attrs = {"af.factory.domain": "order", "af.factory.mode": mode,
             "af.factory.queue.pending": int(pending),
             "af.factory.queue.in_flight": int(in_flight),
             "af.factory.replenish.triggered": list(triggered) or []}
    ok = otel_emit.emit_span("factory.order_round", trace_id=tid, span_id=sid,
                             parent_span_id=parent, kind=1, start_ns=ts * 1_000_000,
                             end_ns=ts * 1_000_000, attributes=attrs, res=res)
    ok &= otel_emit.emit_metric("factory.orders_queue_pending", float(pending),
                                unit="1", res=res, kind="gauge")
    ok &= otel_emit.emit_metric("factory.orders_in_flight", float(in_flight),
                                unit="1", res=res, kind="gauge")
    for action in triggered:
        ok &= otel_emit.emit_metric("factory.replenish_triggered_total", 1.0,
                                    unit="1", attributes={"af.factory.action": action},
                                    res=res, kind="sum")
    return ok


def guardian_round(*, up, down, restarts=0, alarms=(), mode="daemon", ts_ms=None,
                   service="factory-keepalive") -> bool:
    """守护面一轮看护探活观测 → 1 span + 2 gauge + N delta counter（alarms 按级计数）。"""
    ts = ts_ms or _now_ms()
    tid = otel_emit.trace_id_for(None, "guardian", ts)
    sid = otel_emit.span_id_for("guardian-round", str(ts))
    res = otel_emit.resource(service=service)
    attrs = {"af.factory.domain": "guardian", "af.factory.mode": mode,
             "af.factory.guardian.objects_up": int(up),
             "af.factory.guardian.objects_down": int(down),
             "af.factory.guardian.restarts": int(restarts),
             "af.factory.guardian.alarms": list(alarms) or []}
    ok = otel_emit.emit_span("factory.guardian_round", trace_id=tid, span_id=sid,
                             kind=1, start_ns=ts * 1_000_000, end_ns=ts * 1_000_000,
                             attributes=attrs, res=res)
    ok &= otel_emit.emit_metric("factory.guardian_objects_up", float(up),
                                unit="1", res=res, kind="gauge")
    ok &= otel_emit.emit_metric("factory.guardian_objects_down", float(down),
                                unit="1", res=res, kind="gauge")
    for level in alarms:
        ok &= otel_emit.emit_metric("factory.guardian_alarms_total", 1.0, unit="1",
                                    attributes={"af.factory.level": level},
                                    res=res, kind="sum")
    if restarts:
        ok &= otel_emit.emit_metric("factory.guardian_restarts_total", float(restarts),
                                    unit="1", res=res, kind="sum")
    return ok


def harvest_report(*, task_id, verdict, atoms=0, quote_hit=None, quote_miss=None,
                   mode="harvest", order_id=None, work_order_id=None, run_id=None,
                   service="sandbox-harvester") -> bool:
    """收割面单报告校验观测 → 1 span + 1 delta counter（verdict 维度）。"""
    ts = _now_ms()
    tid = otel_emit.trace_id_for(work_order_id, "harvest", ts)
    sid = otel_emit.span_id_for("harvest", task_id, str(ts))
    parent = otel_emit.l1_span_id(work_order_id) if work_order_id else otel_emit.INVALID_SPAN_ID
    res = otel_emit.resource(order_id=order_id, work_order_id=work_order_id,
                             run_id=run_id, service=service)
    attrs = {"af.factory.domain": "harvest", "af.factory.mode": mode,
             "af.factory.harvest.task_id": task_id,
             "af.factory.harvest.verdict": verdict,
             "af.factory.harvest.atoms": int(atoms)}
    if quote_hit is not None:
        attrs["af.factory.harvest.quote_hit"] = int(quote_hit)
    if quote_miss is not None:
        attrs["af.factory.harvest.quote_miss"] = int(quote_miss)
    ok = otel_emit.emit_span("factory.harvest", trace_id=tid, span_id=sid,
                             parent_span_id=parent, kind=1,
                             start_ns=ts * 1_000_000, end_ns=ts * 1_000_000,
                             attributes=attrs,
                             status_code=1 if verdict == "ok" else 2, res=res)
    ok &= otel_emit.emit_metric("factory.harvest_verdicts_total", 1.0, unit="1",
                                attributes={"af.factory.verdict": verdict},
                                res=res, kind="sum")
    return ok


def describe() -> dict:
    return {"endpoint": otel_emit.endpoint(), "stop_file": otel_emit.STOP_FILE,
            "stop_active": otel_emit.stop_active(), "scrub_source": otel_emit.scrub_source(),
            "stats": otel_emit.stats()}


# --------------------------------------------------------------------------- #
# 发射失败可见性（2026-11-02 RT 修复批）
#
# 洞（红队确证）：order_round/guardian_round/harvest_report 都返回 ok（发射是否
# 全成功），但两个守护调用点此前 `except Exception: pass` 且**丢弃 ok**——发射面
# 坏了（collector 不可达）进程内 errors 计数在涨，无人读、无人比对、无人告警；
# 且守护面此前 grep stats/describe/errors 零命中＝无 stats 上报面。
#
# 修法（增量、不改既有 fail-open 语义）：本段给调用面三个抓手——
#   emit_stats()      进程内发射记账（stats 上报面的数据源）
#   guard()           fail-open 包装：返回 {ok, errors, skipped, exc}，绝不抛回调用方
#   visible_failure() 把记账转成一行可见文本（无真失败→None，即不该出声）
#
# 「真失败」口径：otel_emit.errors 增量（HTTP 发射失败）。熔断（OTEL-STOP 在场）
# 与禁用（AF_OTEL_DISABLE=1）是**有意静默**，只进 skipped 增量，不算失败、不刷屏。
# --------------------------------------------------------------------------- #

def emit_stats() -> dict:
    """进程内发射记账（spans/metrics/errors/skipped_stop/scrubbed）——调用面可见性用。"""
    try:
        return dict(otel_emit.stats())
    except Exception:  # noqa: BLE001 —— 记账读不出来也不拖主职
        return {"spans": 0, "metrics": 0, "errors": 0, "skipped_stop": 0, "scrubbed": 0}


def guard(fn, **kwargs) -> dict:
    """埋点调用的 fail-open 包装（守护/收割面共用）：绝不抛回调用方，且必带可见性数据。

    返回 {"ok", "errors", "skipped", "exc"}：
      · ok      —— fn 的返回值（发射是否全成功；熔断/禁用时也是 False）
      · errors  —— 本次调用期间 otel_emit 失败计数增量（collector 不可达等**真失败**）
      · skipped —— 熔断/禁用导致的静默跳过增量（有意静默，不算失败）
      · exc     —— fn 抛异常时的描述（签名漂移/属性错型等调用面问题）
    """
    before = emit_stats()
    exc = None
    ok = False
    try:
        ok = bool(fn(**kwargs))
    except Exception as e:  # noqa: BLE001 —— fail-open：埋点坏不拖主职
        exc = f"{type(e).__name__}: {e}"
    after = emit_stats()
    return {"ok": ok,
            "errors": int(after.get("errors", 0)) - int(before.get("errors", 0)),
            "skipped": int(after.get("skipped_stop", 0)) - int(before.get("skipped_stop", 0)),
            "exc": exc}


def visible_failure(rep: dict, domain: str) -> str | None:
    """把 guard() 的记账转成一行可见文本（无真失败且无调用异常 → None，即不该出声）。

    只有 errors>0（collector 不可达等真失败）与 exc（调用面异常）出文本；
    熔断/禁用的静默跳过不报（有意为之，见 guard() 说明）。
    文本**不含** '[otel] ' 前缀——前缀由调用面自己的日志通道加（调度器 log('[otel] …')
    / 守护 klog('otel', …)），避免同一行出现两个前缀。
    """
    rep = rep or {}
    errs = int(rep.get("errors") or 0)
    exc = rep.get("exc")
    if not errs and not exc:
        return None
    parts = []
    if errs:
        parts.append(f"发射失败 {errs} 次（collector 不可达等）")
    if exc:
        parts.append(f"调用异常 {exc}")
    return f"{domain}埋点" + "；".join(parts) + "（已记账，不影响主职）"
