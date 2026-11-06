#!/usr/bin/env python3
"""gate-item-three-state-summary.py — all-gates 三态汇总层（反馈梯度批件②，2026-11-04）。

消费件①（tools/gate-item-legacy-bridge.py 落 RUNDIR 的 item-N.json）+ 回读
item-N.result 台账行交叉对账，产出三态结论并留证 RUNDIR/summary.json：

    真绿   产物在、status=pass、且能从台账行逐字复算（status/detail/ms/check_id/required 全对上）
    真红   产物在、status=fail、且同上交叉一致
    SKIP   产物在、status=skip + skip_reason（在案原因：环境不可跑/显式排除）——SKIP 绝不当绿，
           但与「没跑成」**可区分**（v0.3 T5 终裁⑤：退出码不可单独判绿的正面堵法）
    未跑成 其余一切：无产物 / 产物坏 JSON / 台账缺席或损坏 / 产物≠台账（字段对不上，
           含「产物被改得比台账好看」的伪造态）——此件无可判产物，退出码对其不可作绿证

判据源分层：台账行是门本体 run_item/record_item 落盘的事实面；产物必须能被台账
复算才算数——汇总层不信任产物自身，堵「改发射器造假绿」。本件是只读报告面：
不进门级 FAIL 计数、不改 all-gates 退出码（门怎么判未动）；异常一律显名。

用法：printf '%s\\n' "${ITEMS[@]}" 的前三段（idx|gate|name）走 stdin；
     python3 tools/gate-item-three-state-summary.py --rundir "$RUNDIR"
退出码：0=三态汇总已产出（含 未跑成>0 的场合——那是报告内容，不是本件故障）；
       2=用法/环境错误（名册行非法、summary.json 落盘失败等，此时无结构化证据，
       调用方须显名警告）。
"""

import argparse
import json
import os
import sys
import tempfile
from typing import Any

SCHEMA = "all-gates.three-state-summary/1"
GENERATED_BY = "tools/gate-item-three-state-summary.py"

STATUSES = {"pass", "fail", "skip"}
SKIP_REASONS = {"not_applicable", "environment_unavailable", "explicitly_excluded"}
STATE_BY_STATUS = {"pass": "true_green", "fail": "true_red", "skip": "skip"}


def parse_result_line(text: str) -> tuple[str, str, int | None]:
    """同款 tools/gate-item-legacy-bridge.py parse_result_line（本件自含同口径副本：
    tools/ 件名带连字符不可 import；两侧判据一致由本件 docstring 与交叉对账互证）。
    ms 非纯数字（含门内联腿实测出现的负数/空段，如 L6「PASS|-123|…」）→ None——
    与件①的容差逐字一致：件①记 ms=None，本件交叉核对期望也须是 None，否则会把
    产物诚实记录的 null 误判成「产物≠台账」（假「未跑成」）。"""
    parts = text.rstrip("\n").split("|", 2)
    if len(parts) != 3:
        raise ValueError(f"legacy item result line must be STATUS|ms|note, got: {text!r}")
    status, milliseconds, note = parts
    ms: int | None = None
    if milliseconds.strip().isdigit():
        ms = int(milliseconds.strip())
    return status, note, ms


def persist_json(path: str, payload: dict[str, Any]) -> None:
    """同款件① persist_json：异内容拒覆盖，同内容幂等，落盘 fsync。"""
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if os.path.exists(path):
        with open(path, "rb") as existing:
            if existing.read() == data:
                return
        raise RuntimeError(f"refusing to overwrite different JSON output: {path}")
    with open(path, "xb") as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())


def rollup(rundir: str, roster_lines: list[str]) -> tuple[int, str]:
    items: list[dict[str, Any]] = []
    totals = {"true_green": 0, "true_red": 0, "skip": 0, "not_run": 0}
    seen_idx: set[str] = set()
    for line in roster_lines:
        if not line.strip():
            continue
        parts = line.split("|", 2)
        if len(parts) != 3:
            raise ValueError(f"roster line must be idx|gate|name, got: {line!r}")
        idx, gate, name = parts[0].strip(), parts[1], parts[2]
        seen_idx.add(idx)
        row: dict[str, Any] = {
            "item": int(idx), "gate": gate, "name": name,
            "state": "not_run", "status": None, "skip_reason": None,
            "detail": None, "ledger_consistent": False, "anomaly": None,
        }
        payload: Any = None
        json_path = os.path.join(rundir, f"item-{idx}.json")
        ledger_path = os.path.join(rundir, f"item-{idx}.result")
        if not os.path.isfile(json_path):
            row["anomaly"] = "无 item-N.json（结构化产物缺席——此件无可判产物，退出码对其不可作绿证）"
        else:
            try:
                with open(json_path, "r", encoding="utf-8") as handle:
                    payload = json.load(handle)
            except (OSError, ValueError) as error:
                row["anomaly"] = f"产物不可读/坏 JSON：{error}"
        if payload is not None:
            if not isinstance(payload, dict) or payload.get("status") not in STATUSES:
                shown = payload.get("status") if isinstance(payload, dict) else type(payload).__name__
                row["anomaly"] = f"产物 status 非三态枚举：{shown!r}"
            else:
                cross = ""
                try:
                    with open(ledger_path, "r", encoding="utf-8") as handle:
                        lstatus, lnote, lms = parse_result_line(handle.read())
                except (OSError, ValueError) as error:
                    cross = f"台账缺席或损坏：{error}"
                if not cross:
                    want_id = f"all-gates:{gate}:{name}"
                    if payload.get("status") != lstatus.lower():
                        cross = f"产物 status={payload.get('status')!r} ≠ 台账 {lstatus!r}"
                    elif payload.get("detail") != lnote:
                        cross = "产物 detail ≠ 台账 note"
                    elif payload.get("ms") != lms:
                        cross = f"产物 ms={payload.get('ms')!r} ≠ 台账 {lms}"
                    elif payload.get("check_id") != want_id:
                        cross = f"产物 check_id={payload.get('check_id')!r} ≠ 期望 {want_id!r}"
                    elif bool(payload.get("required", True)) is not True:
                        cross = "产物 required ≠ true（门内项一律 required）"
                    elif payload.get("status") == "skip" and payload.get("skip_reason") not in SKIP_REASONS:
                        cross = f"SKIP 产物缺合法 skip_reason：{payload.get('skip_reason')!r}"
                if cross:
                    row["anomaly"] = f"产物≠台账（{cross}）——不信任该产物"
                else:
                    row["ledger_consistent"] = True
                    row["status"] = payload["status"]
                    row["skip_reason"] = payload.get("skip_reason")
                    row["detail"] = payload.get("detail")
                    row["state"] = STATE_BY_STATUS[payload["status"]]
        totals[row["state"]] += 1
        items.append(row)

    orphans = []
    for entry in sorted(os.listdir(rundir)):
        if entry.startswith("item-") and entry.endswith(".json"):
            if entry[len("item-"):-len(".json")] not in seen_idx:
                orphans.append(entry)

    summary: dict[str, Any] = {
        "schema": SCHEMA,
        "rundir": rundir,
        "roster_count": len(items),
        "totals": dict(totals, orphan_artifacts=len(orphans)),
        "items": items,
        "orphan_artifacts": orphans,
        "generated_by": GENERATED_BY,
        "verdict_note": (
            "三态口径（v0.3 T5⑤）：true_green=产物在且与台账逐字一致且 pass；true_red=fail；"
            "skip=SKIP 带在案原因（environment_unavailable/explicitly_excluded，绝不当绿）；"
            "not_run=无产物/产物损坏/产物≠台账——退出码不可单独判绿。本文件为只读证据，"
            "不进门级 FAIL 计数、不改 all-gates 退出码。"
        ),
    }
    out_path = os.path.join(rundir, "summary.json")
    try:
        persist_json(out_path, summary)
    except (OSError, RuntimeError) as error:
        raise RuntimeError(f"summary.json 落盘失败：{error}") from error

    lines: list[str] = []
    lines.append(
        f"结构化产物对账（在册 {len(items)} 件）：真绿={totals['true_green']}  "
        f"真红={totals['true_red']}  SKIP={totals['skip']}（原因已录 item-N.json）  "
        f"未跑成={totals['not_run']}  多余产物={len(orphans)}"
    )
    for row in items:
        if row["state"] == "true_red":
            lines.append(f"  - 真红 item-{row['item']} {row['gate']} {row['name']}：{(row['detail'] or '')[:120]}")
    for row in items:
        if row["state"] == "skip":
            lines.append(
                f"  - SKIP item-{row['item']} {row['gate']} {row['name']} → {row['skip_reason']}"
                f"（{(row['detail'] or '')[:90]}）"
            )
    if totals["not_run"]:
        lines.append(
            f"  - 未跑成 {totals['not_run']} 件（无产物/产物损坏/产物≠台账——此件无可判产物，"
            "退出码对其不可作绿证）："
        )
        for row in items:
            if row["state"] == "not_run":
                lines.append(f"    · item-{row['item']} {row['gate']} {row['name']}：{row['anomaly']}")
    for orphan in orphans:
        lines.append(f"  - 多余产物（名册外）：{orphan}")
    lines.append(
        f"结构化留证：{out_path}（逐件三态+台账一致性）；过程面 structured-emit.out/.err、"
        "structured-rollup.out/.err 同目录"
    )
    lines.append(
        "[口径] 本段为只读产物对账：不进门级 FAIL 计数、不改退出码（门怎么判未动）；"
        "SKIP 与「未跑成」已区分——退出码不可单独判绿（v0.3 T5⑤）。"
    )
    return 0, "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rundir", required=True, help="all-gates RUNDIR（读 item-N.json/.result，写 summary.json）")
    args = parser.parse_args()
    if not os.path.isdir(args.rundir):
        sys.stderr.write(f"gate-item-three-state-summary: RUNDIR 不在位：{args.rundir}\n")
        return 2
    try:
        rc, report = rollup(args.rundir, sys.stdin.read().splitlines())
    except (ValueError, RuntimeError) as error:
        sys.stderr.write(f"gate-item-three-state-summary: {error}\n")
        return 2
    sys.stdout.write(report + "\n")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
