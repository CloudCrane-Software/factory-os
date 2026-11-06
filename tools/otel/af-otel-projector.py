#!/usr/bin/env python3
"""af-otel-projector.py — af 执行链四层语义树 → OTLP span 离线投影器（打样件，P1-1）

规范正本：计划/研究组/OTel视图设计批-20261027/otlp-model.md
  - §1.0 trace_id/span_id 确定性派生（同输入重投影 → 逐字节一致）
  - §1.1-§1.4 四层 span（invoke_workflow/invoke_agent/chat/execute_tool）kind/命名/时间/属性
  - §1.5 树形状规则复刻（records 挂载、run_id 脱链、旁路 run 不入树）
  - §2   Resource 九键正字法（照抄，不另起名；af.arm 永远省略）
  - §3   gen_ai.* 语义约定（content 字段永不投影）
  - §6.2 U-6 双来源去重（(TraceId,SpanId) 后端主键去重，mock exporter 复刻）

四层读取器：ledger.jsonl（L1）/ records.jsonl（L1→L2 边）/ harness.db run_row（L2，
transcript_json 读取但正文按 §1.3 永不投影）/ normal.jsonl（L3/L4）/ effects.db（L4
收口，可 stub）。

A1 语义层全链（2026-11-05）：
  - 名册正本 = af 仓 otel/semantic-roster.json（唯一源）。本件运行时读正本
    （AF_SEMANTIC_ROSTER 覆盖；缺省 <工厂工作区>/af/otel/ 检出位）做
    roster_findings 对账（名 ⊆ 名册 ∧ Resource/span 订单级键）；selftest D 腿
    绿/红（红=篡改正本必炸）；正本缺席 ⇒ SKIP 不猜绿。project 命令遇
    ROSTER-VIOLATION 退出 1。
  - 生产者语义化：L1 带 §2.2 L1 载体键 af.unit（records.unit_id 归一，
    swev/report/graph 词表）+ af.order.stage（ledger 末行 final_state→词表）；
    不可归一/在途 ⇒ 省略+finding（不猜）。

双轨红线：critical 事件流不进 OTel（本投影器不读 critical.jsonl；L2 终态取 run_row
.terminal_json，与 critical harness.stop 三面一致已由 tracetree 断言过）。

mock exporter：JSONL 落盘（OTLP proto JSON 字段名，属性为纯 JSON 值——打样替代
OTLP/HTTP protobuf 线格式）。service.name="af-otel-projector"（§2，与在线 lane 区分）。

用法：
  python3 -I af-otel-projector.py project <order_dir> --out spans.jsonl
  python3 -I af-otel-projector.py selftest [--orders-dir DIR]
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

PROJECTOR_VERSION = "0.1.0"  # af 包版本（af-harness/Cargo.toml version）
INVALID_SPAN_ID = ""
KIND_INTERNAL = 1  # OTLP SpanKind
KIND_CLIENT = 3    # OTLP SpanKind

# --------------------------------------------------------------------------- #
# §1.0 确定性 ID 派生（与 tools/otel/otel_emit.py 同源同式）
# --------------------------------------------------------------------------- #

def _sha_hex(seed: str, n: int) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:n]


def trace_id_for(work_order_id: str, id_salt: str | None = None) -> str:
    """§1.0：trace_id = hex(SHA-256("af-trace-v1|" + work_order_id))[0..32]。
    id_salt 仅供 selftest 红例模拟旧随机 ID 行为，生产恒为 None。"""
    seed = "af-trace-v1|" + work_order_id
    if id_salt:
        seed += "|" + id_salt
    return _sha_hex(seed, 32)


def span_id_for(*parts: str) -> str:
    return _sha_hex("af-span-v1|" + "|".join(parts), 16)


# --------------------------------------------------------------------------- #
# 四层读取器
# --------------------------------------------------------------------------- #

def read_ledger(order_dir: Path, findings: list[str]) -> dict | None:
    """L1 载体：ledger.jsonl。返回订单级事实；缺文件返回 None 并记 finding。"""
    path = order_dir / "ledger.jsonl"
    if not path.exists():
        findings.append(f"L1: {order_dir.name} 缺 ledger.jsonl，无法投影 invoke_workflow")
        return None
    lines = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    if not lines:
        findings.append(f"L1: {order_dir.name} ledger.jsonl 为空")
        return None
    order_id = lines[0].get("order_id", order_dir.name)
    stable_id = lines[0].get("stable_id", "")
    ops_ok: list[str] = []
    for row in lines:
        op = row.get("op")
        if row.get("ok") and op and op not in ops_ok:
            ops_ok.append(op)  # §1.1 ok=true 的集合（词表内，保序去重）
    line_id = None
    budget_cents = None
    for row in reversed(lines):
        after = row.get("order_after") or {}
        if line_id is None and after.get("line"):
            line_id = after["line"].get("line_id")
        if budget_cents is None and after.get("budget_voucher"):
            budget_cents = after["budget_voucher"].get("amount")
    return {
        "order_id": order_id,
        "stable_id": stable_id,
        "first_ts_ms": lines[0]["ts_ms"],
        "last_ts_ms": lines[-1]["ts_ms"],
        "final_state": lines[-1].get("state_after", ""),
        "ledger_entries": len(lines),
        "ops_ok": ops_ok,
        "line_id": line_id,
        "budget_cents": budget_cents,
    }


def read_records(order_dir: Path) -> list[dict]:
    """L1→L2 边载体：records.jsonl（0 行/缺文件 → 空表，调用方记 finding）。"""
    path = order_dir / "records.jsonl"
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def read_mes_kinds(order_dir: Path) -> list[str]:
    path = order_dir / "mes-events.jsonl"
    if not path.exists():
        return []
    kinds: list[str] = []
    for l in path.read_text().splitlines():
        if not l.strip():
            continue
        kind = json.loads(l).get("kind")
        if kind and kind not in kinds:
            kinds.append(kind)
    return kinds


def read_run_row(harness_db: Path) -> dict | None:
    """L2 载体：harness.db run_row（恰 1 行）。
    transcript_json 一并读出但按 §1.3 内容纪律永不投影（正文不经 OTel 通道）。"""
    uri = f"file:{harness_db}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    try:
        cur = con.execute(
            "SELECT run_id, order_id, namespace, spec_json, terminal_json, "
            "       updated_at_ms, model_calls, transcript_json FROM run_row"
        )
        rows = cur.fetchall()
    finally:
        con.close()
    if len(rows) != 1:
        return None  # 恰 1 行是 tracetree 断言（:596-600），不成立即不入树
    (run_id, order_id, namespace, spec_json, terminal_json,
     updated_at_ms, model_calls, transcript_json) = rows[0]
    spec = json.loads(spec_json) if spec_json else {}
    terminal = json.loads(terminal_json) if terminal_json else None
    return {
        "run_id": run_id,
        "order_id": order_id,
        "namespace": namespace,
        "endpoint": spec.get("endpoint") or {},
        "terminal": terminal,
        "updated_at_ms": updated_at_ms,
        "model_calls": model_calls,
        # §1.3：transcript_json（对话正文）只读出不投影——content 类字段红线。
        "_transcript_json": transcript_json,
    }


def read_normal_events(normal_jsonl: Path) -> list[dict]:
    if not normal_jsonl.exists():
        return []
    return [json.loads(l) for l in normal_jsonl.read_text().splitlines() if l.strip()]


def read_effect_rows(effects_db: Path) -> list[dict]:
    """L4 收口载体：effects.db effect_intent。缺文件 → stub（空表，调用方记 finding）。"""
    if not effects_db.exists():
        return []
    uri = f"file:{effects_db}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    try:
        cur = con.execute(
            "SELECT order_id, seq, payload_sha256, state, declared_at_ms, executed_at_ms "
            "FROM effect_intent"
        )
        rows = [
            {
                "order_id": r[0], "seq": r[1], "payload_sha256": r[2], "state": r[3],
                "declared_at_ms": r[4], "executed_at_ms": r[5],
            }
            for r in cur.fetchall()
        ]
    finally:
        con.close()
    return rows


# --------------------------------------------------------------------------- #
# 布局甄别（tracetree.rs:26-29 三布局）
# --------------------------------------------------------------------------- #

def discover_runs(order_dir: Path, findings: list[str]) -> list[dict]:
    """返回 run 候选：{run_dir_name, rel, layout, member, harness_db, normal_jsonl, effects_db}。
    三种布局：swev 扁平 / graph nodes/ / ring ring/。同一 L1 下多个 L2 是兄弟。"""
    runs_root = order_dir / "runs"
    if not runs_root.exists():
        findings.append(f"{order_dir.name}: 无 runs/ 目录，只投影 L1")
        return []
    out = []
    for attempt_dir in sorted(p for p in runs_root.iterdir() if p.is_dir()):
        flat_db = attempt_dir / "harness.db"
        if flat_db.exists():
            out.append(_run_candidate(attempt_dir, "flat", None))
            continue
        nodes = attempt_dir / "nodes"
        if nodes.exists():
            for node_dir in sorted(p for p in nodes.iterdir() if p.is_dir()):
                if (node_dir / "harness.db").exists():
                    out.append(_run_candidate(node_dir, "graph", node_dir.name))
            continue
        ring = attempt_dir / "ring"
        if ring.exists():
            for member_dir in sorted(p for p in ring.iterdir() if p.is_dir()):
                if (member_dir / "harness.db").exists():
                    out.append(_run_candidate(member_dir, "ring", member_dir.name))
            continue
        findings.append(f"{order_dir.name}: {attempt_dir.name} 下未找到 harness.db")
    return out


def _run_candidate(run_path: Path, layout: str, member: str | None) -> dict:
    # attempt 目录：flat=run 目录本身；graph/ring=上上级（runs/<attempt>/{nodes,ring}/<member>）
    attempt_dir_name = (run_path.parent.parent.name
                        if layout in ("graph", "ring") else run_path.name)
    return {
        "run_dir_name": run_path.name,
        "attempt_dir_name": attempt_dir_name,
        "path": run_path,
        "layout": layout,
        "member": member,
        "harness_db": run_path / "harness.db",
        "normal_jsonl": run_path / "normal.jsonl",
        "effects_db": run_path / "effects.db",
    }


# --------------------------------------------------------------------------- #
# A1 生产者语义化：L1 订单轴键（span-conventions.md §2.2 的 L1 载体键）
# --------------------------------------------------------------------------- #

# §1.2 词表映射（真源=ledger 末行 state_after；在途单无词表值 ⇒ 省略不猜）。
STAGE_BY_FINAL_STATE = {"Closed": "closed", "Completed": "completed", "Failed": "failed"}


def stage_of_final(final_state: str | None, order_id: str,
                   findings: list[str]) -> str | None:
    stage = STAGE_BY_FINAL_STATE.get(final_state or "")
    if stage is None:
        findings.append(f"{order_id}: final_state={final_state!r} 无 stage 词表映射"
                        f"（在途单），af.order.stage 省略（不猜）")
    return stage


def norm_unit(records: list[dict], order_id: str,
              findings: list[str]) -> str | None:
    """§1.1 归一：records.unit_id 去 `-unit` 后缀 → {swev,report,graph}。

    与 order-stages.py _norm_unit 同口径的第一步（unit_id 维）；归一不进
    三值词表 ⇒ 省略+finding（目录名兜底是看板维的次源，投影器不采用——
    打样件只认 records 真源，不猜）。
    """
    raw = next((r.get("unit_id") for r in records if r.get("unit_id")), None)
    if not raw:
        findings.append(f"{order_id}: records 无 unit_id，af.unit 省略（不猜）")
        return None
    val = raw[:-len("-unit")] if raw.endswith("-unit") else raw
    if val in ("swev", "report", "graph"):
        return val
    findings.append(f"{order_id}: unit_id={raw!r} 归一={val!r} 不在词表"
                    f" {{swev,report,graph}}，af.unit 省略（不猜）")
    return None


def parse_profile(attempt_dir_name: str, item_id: str | None,
                  findings: list[str], run_label: str) -> str | None:
    """§2 键 6：swev/report 从 run 目录名解析 profile（swev-{task_id}-{profile}-a{n}）。
    解析失败则省略并记 finding，不得猜。graph 形取自 records.profile 顶层字段。"""
    if not item_id:
        findings.append(f"{run_label}: records 无 item_id，af.profile 省略（解析失败不猜）")
        return None
    body = attempt_dir_name
    for pre in ("swev-", "graph-"):
        if body.startswith(pre):
            body = body[len(pre):]
            break
    tail = body.rsplit("-a", 1)
    if len(tail) == 2 and tail[1].isdigit() and tail[0].startswith(item_id + "-"):
        return tail[0][len(item_id) + 1:]
    findings.append(f"{run_label}: 目录名 {attempt_dir_name} 解析不出 profile，af.profile 省略")
    return None


def parse_attempt(attempt_dir_name: str, records_attempt) -> int | None:
    if records_attempt is not None:
        return int(records_attempt)
    tail = attempt_dir_name.rsplit("-a", 1)
    if len(tail) == 2 and tail[1].isdigit():
        return int(tail[1])
    return None


def registry_digest(plan_id: str | None) -> str | None:
    """§2 键 9：report/graph 取 plan_id 的 + 段（前 12 位 dsl_digest）；swev 无 + 段 → 省略。"""
    if plan_id and "+" in plan_id:
        return plan_id.split("+", 1)[1]
    return None


# --------------------------------------------------------------------------- #
# A1 语义层名册正本（三面消费之一：投影器侧）
# --------------------------------------------------------------------------- #

class SkipCheck(Exception):
    """对账腿前置缺席（名册正本不在位）⇒ 跳过该腿：不猜绿、不计通过。"""


def load_roster() -> dict | None:
    """语义层名册正本（af 仓 otel/semantic-roster.json，全链单一源）。

    解析序：AF_SEMANTIC_ROSTER 环境覆盖 → <工厂工作区>/af/otel/ 检出位。
    缺席/坏 JSON/无 semantic_layers ⇒ None（调用方按 skip 或关门处置，不猜）。
    """
    p = os.environ.get("AF_SEMANTIC_ROSTER") or (
        Path(__file__).resolve().parent.parent.parent
        / "af" / "otel" / "semantic-roster.json")
    try:
        with open(p, encoding="utf-8") as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict) or not isinstance(d.get("semantic_layers"), dict):
        return None
    return d


def roster_findings(spans: list[dict], roster: dict) -> list[str]:
    """投影输出 vs 正本：① 名 ⊆ 正本名册；② Resource 带正本 resource_order_keys；
    ③ 各层 span attrs 带正本 span_order_keys（L1 三键）。只增判据，不改投影数据。"""
    problems: list[str] = []
    layers = roster.get("semantic_layers") or {}
    res_keys = list(roster.get("resource_order_keys") or [])
    span_keys = {n: list((spec or {}).get("span_order_keys") or [])
                 for n, spec in layers.items()}
    for s in spans:
        name = s.get("name")
        if name not in layers:
            problems.append(f"span 名 {name!r} 不在正本名册（semantic_layers 键集）")
            continue
        res = set((s.get("resource") or {}).keys())
        miss = [k for k in res_keys if k not in res]
        if miss:
            problems.append(f"{name}: Resource 缺订单级键 {miss}")
        attrs = set((s.get("attributes") or {}).keys())
        miss = [k for k in span_keys.get(name, []) if k not in attrs]
        if miss:
            problems.append(f"{name}: span attrs 缺订单级键 {miss}")
    return problems


# --------------------------------------------------------------------------- #
# 投影
# --------------------------------------------------------------------------- #

def _ms_to_ns(ts_ms: int) -> int:
    return int(ts_ms) * 1_000_000


def _attrs(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None}


def project_order(order_dir: Path, id_salt: str | None = None) -> tuple[list[dict], list[str]]:
    """把一单投影为 OTLP span 列表（打样形态，mock 导出前的内存态）。"""
    findings: list[str] = []
    order_dir = Path(order_dir)
    ledger = read_ledger(order_dir, findings)
    if ledger is None:
        return [], findings
    records = read_records(order_dir)
    if not records:
        findings.append(f"{ledger['order_id']}: records.jsonl 0 行（失败单或未记账），"
                        f"L2 改按 on-disk run 挂载，af.strategy_id 省略")
    mes_kinds = read_mes_kinds(order_dir)
    unit = norm_unit(records, ledger["order_id"], findings)
    stage = stage_of_final(ledger["final_state"], ledger["order_id"], findings)

    stable_id = ledger["stable_id"]
    trace_id = trace_id_for(stable_id, id_salt=id_salt)
    l1_span_id = span_id_for(stable_id, "invoke_workflow")

    # 订单级 Resource（§2：L1 只有订单级键）
    order_resource = _attrs({
        "service.name": "af-otel-projector",
        "service.version": PROJECTOR_VERSION,
        "af.order_id": ledger["order_id"],
        "af.work_order_id": stable_id,
        "af.line": ledger["line_id"],
        "af.strategy_id": records[0].get("plan_id") if records else None,
        "af.dsl_digest": registry_digest(records[0].get("plan_id")) if records else None,
    })

    spans: list[dict] = []
    by_span_id: dict[str, dict] = {}

    def add(span: dict) -> None:
        sid = span["spanId"]
        if sid in by_span_id:  # 双来源同事件去重（U-6 投影器内侧）：保先到的
            findings.append(f"dup span_id {sid}（{span['name']}）已存在，丢弃后到的")
            return
        by_span_id[sid] = span
        spans.append(span)

    # ---- L1 invoke_workflow（§1.1）----
    add({
        "traceId": trace_id,
        "spanId": l1_span_id,
        "parentSpanId": INVALID_SPAN_ID,
        "name": "invoke_workflow",
        "kind": KIND_INTERNAL,
        "startTimeUnixNano": str(_ms_to_ns(ledger["first_ts_ms"])),
        "endTimeUnixNano": str(_ms_to_ns(ledger["last_ts_ms"])),
        "attributes": _attrs({
            "af.span.layer": "invoke_workflow",
            "af.order_id": ledger["order_id"],
            "af.work_order_id": stable_id,
            "af.workflow.final_state": ledger["final_state"],
            "af.workflow.ledger_entries": ledger["ledger_entries"],
            "af.workflow.ops_ok": ",".join(ledger["ops_ok"]),
            "af.workflow.mes_kinds": ",".join(mes_kinds) if mes_kinds else None,
            "af.line": ledger["line_id"],
            "af.budget.cents": ledger["budget_cents"],
            # A1 §2.2 L1 载体键（订单轴；C-1 L1 专属）。真源：records.unit_id
            # 归一 + ledger final_state→词表；不可归一/在途 ⇒ 省略+finding（不猜）。
            "af.unit": unit,
            "af.order.stage": stage,
        }),
        "resource": dict(order_resource),
    })

    # ---- L2 invoke_agent（§1.2）：records evidence 挂载 + on-disk 回退 ----
    candidates = discover_runs(order_dir, findings)
    # records evidence 的尾段既可能指 run 目录（swev 扁平），也可能指 attempt 目录
    # （ring/report：evidence 写 runs/<attempt>，真正的 run 在其 ring/<成员> 下）
    edges: dict[str, dict] = {}
    for row in records:
        ev = (row.get("evidence") or {}).get("run_dir")
        if ev:
            edges[Path(ev).name] = row
    on_disk_names = {c["run_dir_name"] for c in candidates} \
        | {c["attempt_dir_name"] for c in candidates}
    for row in records:
        ev = (row.get("evidence") or {}).get("run_dir")
        if ev and Path(ev).name not in on_disk_names:
            findings.append(f"{ledger['order_id']}: records evidence.run_dir={Path(ev).name} "
                            f"不存在（§1.5 规则 1 断链）")
    # graph 形 records 无 evidence，profile/task_id 在顶层（F4D 实测）：订单级兜底
    order_profile = next((r.get("profile") for r in records if r.get("profile")), None)
    order_item_id = next((r.get("item_id") or r.get("task_id")
                          for r in records if r.get("item_id") or r.get("task_id")), None)

    for cand in candidates:
        run_row = read_run_row(cand["harness_db"])
        if run_row is None:
            findings.append(f"{ledger['order_id']}: {cand['path']} run_row 非恰 1 行，跳过")
            continue
        run_id = run_row["run_id"]
        if run_row["terminal"] is None:
            # §1.5 规则 4：旁路 run 不入树，其 L3/L4 也不投影（先判旁路，
            # 旁路 run 无 evidence 不属断链，不再告警）
            findings.append(f"{ledger['order_id']}: {run_id} 旁路 run（terminal=None），不投影")
            continue
        rec = edges.get(cand["run_dir_name"]) or edges.get(cand["attempt_dir_name"])
        if rec is None and cand["layout"] == "flat" and records:
            # 布局差异：graph 形 records 无 evidence（注册表形态，token 闭合承担）；
            # flat 应总有 evidence，缺了要登记
            findings.append(f"{ledger['order_id']}: {cand['run_dir_name']} 无 records evidence 行"
                            f"（flat 布局），仍按 on-disk run 投影")

        events = read_normal_events(cand["normal_jsonl"])
        run_events = [e for e in events
                      if (e.get("payload") or {}).get("run_id") == run_id]
        start_ms = min((e["ts_ms"] for e in run_events), default=run_row["updated_at_ms"])

        endpoint = run_row["endpoint"]
        model = endpoint.get("model")
        protocol = endpoint.get("protocol", "")
        gen_ai_system = {"anthropic-messages": "anthropic",
                         "openai-chat-completions": "openai"}.get(protocol)
        if cand["layout"] == "flat":
            node_id = (rec or {}).get("node_id")
            if not node_id:
                findings.append(f"{ledger['order_id']}: {run_id} flat 布局无 records node_id，"
                                f"af.node_id 省略")
        else:
            node_id = cand["member"]
        attempt = parse_attempt(cand["attempt_dir_name"], (rec or {}).get("attempt"))
        item_id = (rec or {}).get("item_id") or order_item_id
        if (rec or {}).get("profile") or order_profile:
            profile = (rec or {}).get("profile") or order_profile
        else:
            profile = parse_profile(cand["attempt_dir_name"], item_id,
                                    findings, f"{ledger['order_id']}/{run_id}")

        terminal = run_row["terminal"] or {}
        run_resource = dict(order_resource)
        run_resource.update(_attrs({
            "af.run_id": run_id,
            "af.profile": profile,
            "af.model": model,
        }))

        l2_span_id = span_id_for(stable_id, run_id)
        add({
            "traceId": trace_id,
            "spanId": l2_span_id,
            "parentSpanId": l1_span_id,
            "name": "invoke_agent",
            "kind": KIND_INTERNAL,
            "startTimeUnixNano": str(_ms_to_ns(start_ms)),
            "endTimeUnixNano": str(_ms_to_ns(run_row["updated_at_ms"])),
            "attributes": _attrs({
                "af.span.layer": "invoke_agent",
                "af.run_id": run_id,
                "af.run_dir": cand["run_dir_name"],
                "af.node_id": node_id,
                "af.attempt": attempt,
                "af.terminal.kind": terminal.get("kind"),
                "af.terminal.signal": terminal.get("signal"),
                "af.model": model,
                "af.namespace": run_row["namespace"] or None,
                "gen_ai.operation.name": "invoke_agent",
                "gen_ai.agent.name": node_id,
                "gen_ai.request.model": model,
            }),
            "resource": run_resource,
        })

        # ---- L3 chat / L4 execute_tool（normal.jsonl；§1.3/§1.4）----
        effect_rows = read_effect_rows(cand["effects_db"])
        if not effect_rows and cand["effects_db"].exists() is False:
            findings.append(f"{ledger['order_id']}: {run_id} 无 effects.db，L4 保点跨度（stub）")
        by_executed = {}
        for r in effect_rows:
            if r["order_id"] == run_id and r["executed_at_ms"] is not None:
                by_executed.setdefault(r["executed_at_ms"], r)
        consumed: set[int] = set()  # 已被工具事件占用的 effect 行（id() 记号）

        for env in run_events:
            kind = env.get("kind")
            payload = env.get("payload") or {}
            ts_ms = env["ts_ms"]
            seq = env.get("seq")
            if kind == "harness.model":
                usage = payload.get("usage") or {}
                add({
                    "traceId": trace_id,
                    "spanId": span_id_for(run_id, "chat", str(payload.get("turn"))),
                    "parentSpanId": l2_span_id,
                    "name": "chat",
                    "kind": KIND_CLIENT,
                    "startTimeUnixNano": str(_ms_to_ns(ts_ms)),
                    "endTimeUnixNano": str(_ms_to_ns(ts_ms)),  # §1.3 点跨度，不造 duration
                    "attributes": _attrs({
                        "af.span.layer": "chat",
                        "af.run_id": run_id,
                        "af.turn": payload.get("turn"),
                        "af.seq": seq,
                        "af.ts_ms": ts_ms,
                        "gen_ai.operation.name": "chat",
                        "gen_ai.request.model": payload.get("model"),
                        "gen_ai.usage.input_tokens": usage.get("input_tokens"),
                        "gen_ai.usage.output_tokens": usage.get("output_tokens"),
                        "gen_ai.usage.cache_read_tokens": usage.get("cache_read_tokens"),
                        "gen_ai.response.finish_reasons": [payload.get("finish")],
                        "gen_ai.system": gen_ai_system,
                    }),
                    "resource": dict(run_resource),
                })
            elif kind == "harness.tool":
                effect = payload.get("effect")
                span_kind = KIND_INTERNAL if effect == "pure" else KIND_CLIENT
                effect_row = None
                if effect != "pure":
                    candidate = by_executed.get(ts_ms)
                    effect_row = (candidate if candidate is not None
                                  and id(candidate) not in consumed else None)
                    if effect_row is not None:
                        consumed.add(id(effect_row))
                    if effect_row is None:
                        # 时钟修约容差：executed 与事件 ts 偶有 1-2ms 修约差（F1 实测 1ms），
                        # ±5ms 窗口内唯一未占用候选即采纳；仍 deterministic。
                        window = [r for r in effect_rows
                                  if r["order_id"] == run_id
                                  and r["executed_at_ms"] is not None
                                  and abs(r["executed_at_ms"] - ts_ms) <= 5
                                  and id(r) not in consumed]
                        if len(window) == 1:
                            effect_row = window[0]
                            consumed.add(id(effect_row))
                    if effect_row is None:
                        # 位置回退：按 declared 序对应该 run 剩余未占用的 effect 行
                        pool = [r for r in effect_rows
                                if r["order_id"] == run_id and r["state"] == "executed"
                                and id(r) not in consumed]
                        pool.sort(key=lambda r: (r["declared_at_ms"] is None, r["declared_at_ms"]))
                        if pool:
                            effect_row = pool[0]
                            consumed.add(id(effect_row))
                            findings.append(f"{ledger['order_id']}/{run_id}: L4 seq={seq} "
                                            f"executed_at_ms 匹配失败，按 declared 序回退")
                        else:
                            findings.append(f"{ledger['order_id']}/{run_id}: L4 seq={seq} "
                                            f"无 effect 行可匹配")
                is_error = payload.get("is_error")
                err_code = payload.get("error_code") or "unknown"
                add({
                    "traceId": trace_id,
                    "spanId": span_id_for(run_id, "tool", str(seq)),
                    "parentSpanId": l2_span_id,  # §1.4：与 chat 同父兄弟，不挂 chat
                    "name": "execute_tool",
                    "kind": span_kind,
                    "startTimeUnixNano": str(_ms_to_ns(ts_ms)),
                    "endTimeUnixNano": str(_ms_to_ns(
                        effect_row["executed_at_ms"] if effect_row else ts_ms)),
                    "attributes": _attrs({
                        "af.span.layer": "execute_tool",
                        "af.run_id": run_id,
                        "af.turn": payload.get("turn"),
                        "af.seq": seq,
                        "af.ts_ms": ts_ms,
                        "af.tool.effect": effect,
                        "gen_ai.operation.name": "execute_tool",
                        "gen_ai.tool.name": payload.get("tool"),
                        "error.type": err_code if is_error else None,
                        "af.effect.intent_state": (effect_row or {}).get("state"),
                        "af.effect.sha256": (effect_row or {}).get("payload_sha256"),
                    }),
                    "resource": dict(run_resource),
                })
    return spans, findings


# --------------------------------------------------------------------------- #
# mock exporter（JSONL；U-6 去重 = 后端按 (traceId, spanId) 主键，§1.0 幂等 ID 支撑）
# --------------------------------------------------------------------------- #

def canonical(span: dict) -> str:
    return json.dumps(span, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


class MockExporter:
    """打样替代 OTLP/HTTP exporter：span 追加写 JSONL。"""

    def __init__(self, path: Path):
        self.path = Path(path)

    def emit(self, spans: list[dict]) -> None:
        with self.path.open("a", encoding="utf-8") as fh:
            for s in spans:
                fh.write(canonical(s) + "\n")

    def spans(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(l) for l in self.path.read_text().splitlines() if l.strip()]


def backend_dedup(spans: list[dict]) -> tuple[list[dict], int]:
    """模拟后端主键去重（U-6 依赖 §1.0 幂等 ID）：(traceId, spanId) 保留先到。
    返回 (唯一 span 列表, 被去重的条数)。"""
    seen: dict[tuple[str, str], dict] = {}
    suppressed = 0
    for s in spans:
        key = (s["traceId"], s["spanId"])
        if key in seen:
            suppressed += 1
        else:
            seen[key] = s
    return list(seen.values()), suppressed


def online_lane_replay(order_dir: Path, runs: list[dict]) -> list[dict]:
    """模拟在线 lane（af-trace otel.rs）对 normal.jsonl 事件的 L3/L4 导出：
    与投影器同 §1.0 派生式 → 同 (traceId, spanId)。双来源混流的第二来源。"""
    order_dir = Path(order_dir)
    ledger = read_ledger(order_dir, [])
    if ledger is None:
        return []
    stable_id = ledger["stable_id"]
    trace_id = trace_id_for(stable_id)
    spans = []
    for cand in runs:
        run_row = read_run_row(cand["harness_db"])
        if run_row is None or run_row["terminal"] is None:
            continue  # 在线 lane 同样只挂入树 run（旁路不投影）
        run_id = run_row["run_id"]
        l2_span_id = span_id_for(stable_id, run_id)
        for env in read_normal_events(cand["normal_jsonl"]):
            payload = env.get("payload") or {}
            if payload.get("run_id") != run_id:
                continue
            ts = str(_ms_to_ns(env["ts_ms"]))
            if env.get("kind") == "harness.model":
                spans.append({
                    "traceId": trace_id,
                    "spanId": span_id_for(run_id, "chat", str(payload.get("turn"))),
                    "parentSpanId": l2_span_id,
                    "name": "chat", "kind": KIND_CLIENT,
                    "startTimeUnixNano": ts, "endTimeUnixNano": ts,
                    "attributes": {"af.seq": env.get("seq")}, "resource": {},
                })
            elif env.get("kind") == "harness.tool":
                spans.append({
                    "traceId": trace_id,
                    "spanId": span_id_for(run_id, "tool", str(env.get("seq"))),
                    "parentSpanId": l2_span_id,
                    "name": "execute_tool",
                    "kind": KIND_INTERNAL if payload.get("effect") == "pure" else KIND_CLIENT,
                    "startTimeUnixNano": ts, "endTimeUnixNano": ts,
                    "attributes": {"af.seq": env.get("seq")}, "resource": {},
                })
    return spans


# --------------------------------------------------------------------------- #
# 三验（A §1.0 幂等 / B U-6 去重 / C §1.5 树形状）
# --------------------------------------------------------------------------- #

class CheckFailure(AssertionError):
    pass


def _assert_idempotent(out1: Path, out2: Path) -> None:
    """§1.0 真断言：两次导出的 (traceId, spanId) 与字节全同。"""
    b1, b2 = out1.read_bytes(), out2.read_bytes()
    if not b1 or b1 != b2:
        raise CheckFailure("同输入两次投影字节不一致（TraceId/SpanId 非确定性派生）")
    s1 = {(s["traceId"], s["spanId"]) for s in MockExporter(out1).spans()}
    s2 = {(s["traceId"], s["spanId"]) for s in MockExporter(out2).spans()}
    if s1 != s2:
        raise CheckFailure("(traceId, spanId) 集合不一致")


def check_A_idempotency(orders_dir: Path, workdir: Path) -> None:
    """绿：同输入两次投影，逐字节一致。"""
    f1 = orders_dir / "F1-swev-django-11099-glm-cp"
    out1, out2 = workdir / "a1.jsonl", workdir / "a2.jsonl"
    for p in (out1, out2):
        p.unlink(missing_ok=True)
    MockExporter(out1).emit(project_order(f1)[0])
    MockExporter(out2).emit(project_order(f1)[0])
    _assert_idempotent(out1, out2)


def check_A_idempotency_red(orders_dir: Path, workdir: Path) -> None:
    """红：第二次投影模拟旧 otel.rs 每 worker 随机 trace（id_salt）——
    同一 §1.0 断言必须炸。"""
    f1 = orders_dir / "F1-swev-django-11099-glm-cp"
    out1, out2 = workdir / "ar1.jsonl", workdir / "ar2.jsonl"
    for p in (out1, out2):
        p.unlink(missing_ok=True)
    MockExporter(out1).emit(project_order(f1)[0])
    MockExporter(out2).emit(project_order(f1, id_salt="random-per-worker")[0])
    _assert_idempotent(out1, out2)  # 预期抛 CheckFailure


def _assert_dual_source_merged(spans_full: list[dict], lane: list[dict],
                               merged: list[dict], suppressed: int) -> None:
    """U-6 真断言：双来源混流经 (traceId, spanId) 主键去重后，同事件只一条。"""
    if not lane:
        raise CheckFailure("在线 lane 重放为空，双来源设定失效")
    if suppressed <= 0:
        raise CheckFailure("后端主键去重未收敛任何重复")
    keys_merged = [(s["traceId"], s["spanId"]) for s in merged]
    if len(keys_merged) != len(set(keys_merged)):
        raise CheckFailure("去重后仍有重复 (traceId, spanId)——同事件多于一条")
    keys_full = {(s["traceId"], s["spanId"]) for s in spans_full}
    if set(keys_merged) != keys_full:
        raise CheckFailure("去重后键集相对投影器全量有增减——同事件未收敛为一条")


def check_B_dedup(orders_dir: Path, workdir: Path) -> None:
    """绿：投影器全量（ledger+records+harness.db+normal.jsonl）与在线 lane 重放
    （normal.jsonl 第二来源）混流，后端主键去重收敛。"""
    f1 = orders_dir / "F1-swev-django-11099-glm-cp"
    spans_full, _ = project_order(f1)
    ids = [s["spanId"] for s in spans_full]
    if len(ids) != len(set(ids)):
        raise CheckFailure("投影器联合读取出现重复 span_id")
    lane = online_lane_replay(f1, discover_runs(f1, []))
    merged, suppressed = backend_dedup(spans_full + lane)
    _assert_dual_source_merged(spans_full, lane, merged, suppressed)


def check_B_dedup_red(orders_dir: Path, workdir: Path) -> None:
    """红：naive concat 不走去重——同一 U-6 断言必须检出同事件多条。"""
    f1 = orders_dir / "F1-swev-django-11099-glm-cp"
    spans_full, _ = project_order(f1)
    lane = online_lane_replay(f1, discover_runs(f1, []))
    naive = spans_full + lane  # 未做 backend_dedup
    _assert_dual_source_merged(spans_full, lane, naive, suppressed=0)  # 预期抛 CheckFailure


def _assert_tree_shape(spans: list[dict], findings: list[str]) -> None:
    """§1.5 真断言：invoke_workflow→invoke_agent→chat→execute_tool 四层父子齐全。"""
    by_id = {s["spanId"]: s for s in spans}
    l1 = [s for s in spans if s["name"] == "invoke_workflow"]
    if len(l1) != 1:
        raise CheckFailure(f"L1 应恰 1 个，实得 {len(l1)}")
    l1 = l1[0]
    if l1["parentSpanId"] != INVALID_SPAN_ID:
        raise CheckFailure("L1 parent 应为 INVALID")
    l2s = [s for s in spans if s["name"] == "invoke_agent"]
    chats = [s for s in spans if s["name"] == "chat"]
    tools = [s for s in spans if s["name"] == "execute_tool"]
    if not l2s or not chats or not tools:
        raise CheckFailure("四层未齐全（L2/L3/L4 有空层）")
    for l2 in l2s:
        if l2["parentSpanId"] != l1["spanId"]:
            raise CheckFailure(f"L2 {l2['spanId']} 未挂到 L1")
        if l2["kind"] != KIND_INTERNAL:
            raise CheckFailure("L2 kind 应为 INTERNAL")
    run_of = {l2["spanId"]: l2["attributes"].get("af.run_id") for l2 in l2s}
    chat_ids = {c["spanId"] for c in chats}
    for s in chats + tools:
        parent = by_id.get(s["parentSpanId"])
        if parent is None or parent["name"] != "invoke_agent":
            raise CheckFailure(f"{s['name']} 未挂到 invoke_agent（脱链）")
        if s["attributes"].get("af.run_id") != run_of.get(s["parentSpanId"]):
            raise CheckFailure(f"{s['name']} run_id 与父 L2 不一致（§1.5 规则 2）")
        if s["name"] == "chat" and s["kind"] != KIND_CLIENT:
            raise CheckFailure("L3 kind 应为 CLIENT")
        if s["name"] == "execute_tool" and s["parentSpanId"] in chat_ids:
            raise CheckFailure("L4 错挂到 chat（§1.4 同父兄弟）")
    # 四层链：存在 L1→L2→chat 与 L1→L2→execute_tool 同 run 同轮兄弟
    chat_keys = {(c["parentSpanId"], c["attributes"].get("af.turn")) for c in chats}
    if not any((t["parentSpanId"], t["attributes"].get("af.turn")) in chat_keys
               for t in tools):
        raise CheckFailure("未找到同轮 chat↔execute_tool 兄弟序（§1.5 兄弟序约束）")
    # 旁路 run 不入树（§1.5 规则 4）：F1 a1 terminal=None
    all_runs = {s["attributes"].get("af.run_id") for s in spans if "af.run_id" in s["attributes"]}
    if "django__django-11099-a1" in all_runs:
        raise CheckFailure("旁路 run a1 混入树（terminal=None 应排除）")
    if not any("旁路 run" in f for f in findings):
        raise CheckFailure("未登记旁路 run finding")


def check_C_tree_shape(orders_dir: Path, workdir: Path) -> None:
    """绿：F1 四层父子齐全。"""
    f1 = orders_dir / "F1-swev-django-11099-glm-cp"
    spans, findings = project_order(f1)
    _assert_tree_shape(spans, findings)


def check_C_tree_shape_red(orders_dir: Path, workdir: Path) -> None:
    """红：records evidence 断链 + runs 目录缺失 → 同一 §1.5 断言必须炸。"""
    broken = workdir / "BROKEN-F1"
    if broken.exists():
        shutil.rmtree(broken)
    shutil.copytree(orders_dir / "F1-swev-django-11099-glm-cp", broken)
    shutil.rmtree(broken / "runs", ignore_errors=True)
    rec = broken / "records.jsonl"
    row = json.loads(rec.read_text().splitlines()[0])
    row["evidence"]["run_dir"] = "runs/不存在的目录-a9"
    rec.write_text(json.dumps(row, ensure_ascii=False) + "\n")
    spans, findings = project_order(broken)
    if not any("断链" in f for f in findings):
        raise CheckFailure("红例前提失效：未登记断链 finding")
    _assert_tree_shape(spans, findings)  # 预期抛 CheckFailure（四层不全）


# --------------------------------------------------------------------------- #
# selftest：三验各红绿一例 + A1 D 腿（名册正本对账，绿/红；正本缺席 ⇒ SKIP 不猜绿）
# --------------------------------------------------------------------------- #

def check_D_roster_green(orders_dir: Path, _workdir: Path) -> None:
    """绿：F1 真投影满足正本（名 ⊆ 名册 ∧ Resource/span 订单级键齐）。"""
    roster = load_roster()
    if roster is None:
        raise SkipCheck("名册正本不在位（af/otel/semantic-roster.json）")
    f1 = orders_dir / "F1-swev-django-11099-glm-cp"
    spans, _ = project_order(f1)
    problems = roster_findings(spans, roster)
    if problems:
        raise CheckFailure(f"真投影违反正本: {problems[:3]}")


def check_D_roster_red(orders_dir: Path, _workdir: Path) -> None:
    """红：篡改正本（L1 除名）⇒ 同一对账必须检出（三面夹具的投影器面）。"""
    roster = load_roster()
    if roster is None:
        raise SkipCheck("名册正本不在位（af/otel/semantic-roster.json）")
    tampered = copy.deepcopy(roster)
    tampered["semantic_layers"].pop("invoke_workflow", None)   # 篡改①：L1 除名
    tampered["resource_order_keys"] = ["af.order_id"]          # 篡改②：Resource 键缩
    f1 = orders_dir / "F1-swev-django-11099-glm-cp"
    spans, _ = project_order(f1)
    problems = roster_findings(spans, tampered)
    if problems:
        # 惯例同 A/B/C 红腿：「对账检出篡改」以 CheckFailure 表达 = 期望红形。
        raise CheckFailure(f"篡改正本被对账检出: {problems[:2]}")


def selftest(orders_dir: Path) -> int:
    orders_dir = Path(orders_dir)
    checks = [
        ("A 绿 §1.0 幂等（两次投影字节一致）", lambda w: check_A_idempotency(orders_dir, w), True),
        ("A 红 随机 ID（幂等断言应失败）", lambda w: check_A_idempotency_red(orders_dir, w), False),
        ("B 绿 U-6 去重（双来源混流主键收敛）", lambda w: check_B_dedup(orders_dir, w), True),
        ("B 红 naive concat（重复应存在）", lambda w: check_B_dedup_red(orders_dir, w), False),
        ("C 绿 §1.5 树形状（F1 四层父子齐全）", lambda w: check_C_tree_shape(orders_dir, w), True),
        ("C 红 断链单（四层断言应失败）", lambda w: check_C_tree_shape_red(orders_dir, w), False),
        ("D 绿 roster 对账（真投影 ⊆ 正本）", lambda w: check_D_roster_green(orders_dir, w), True),
        ("D 红 篡改正本（对账必炸）", lambda w: check_D_roster_red(orders_dir, w), False),
    ]
    failures = 0
    skipped = 0
    with tempfile.TemporaryDirectory(prefix="af-otel-projector-selftest-") as td:
        workdir = Path(td)
        for label, fn, expect_pass in checks:
            try:
                fn(workdir)
                ok = True
                detail = "通过"
            except SkipCheck as exc:
                skipped += 1
                print(f"[SKIP] {label}: {exc}")
                continue
            except CheckFailure as exc:
                ok = False
                detail = f"违反断言: {exc}"
            except Exception as exc:  # noqa: BLE001 — selftest 要如实暴露任何异常
                ok = False
                detail = f"异常 {type(exc).__name__}: {exc}"
            verdict = "OK" if ok == expect_pass else "UNEXPECTED"
            if ok != expect_pass:
                failures += 1
            print(f"[{verdict}] {label}: {detail}")
    print(f"selftest: {len(checks) - failures - skipped}/{len(checks)} 符合预期"
          f"（skip {skipped}：正本缺席，不猜绿）")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="af 四层语义树 OTLP 离线投影器（打样）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_proj = sub.add_parser("project", help="投影一单到 JSONL")
    p_proj.add_argument("order_dir", type=Path)
    p_proj.add_argument("--out", type=Path, required=True)
    p_proj.add_argument("--id-salt", default=None, help="selftest 专用，模拟非确定性 ID")
    p_self = sub.add_parser("selftest", help="三验各红绿一例")
    p_self.add_argument("--orders-dir", type=Path,
                        default=Path(__file__).resolve().parent.parent.parent / "af-state" / "orders")
    args = ap.parse_args(argv)
    if args.cmd == "selftest":
        return selftest(args.orders_dir)
    spans, findings = project_order(args.order_dir, id_salt=args.id_salt)
    roster = load_roster()
    roster_violations = roster_findings(spans, roster) if roster else []
    if roster is None:
        print("roster: 正本缺席（af/otel/semantic-roster.json 不在位）——跳过对账",
              file=sys.stderr)
    args.out.unlink(missing_ok=True)
    MockExporter(args.out).emit(spans)
    for f in findings:
        print(f"finding: {f}", file=sys.stderr)
    for v in roster_violations:
        print(f"ROSTER-VIOLATION: {v}", file=sys.stderr)
    print(f"{len(spans)} spans -> {args.out}")
    return 1 if roster_violations else 0


if __name__ == "__main__":
    sys.exit(main())
