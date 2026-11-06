#!/usr/bin/env python3
"""gate-item-legacy-bridge.py（工作区侧）— 把 all-gates 的 item-N.result 管道行落成结构化产物 item-N.json。

反馈梯度批件①（2026-11-04，30-工件/反馈梯度-20261104）。解析口径同款复制自
af 仓 tools/gate-item-legacy-bridge.py（+ 其校验层 gate-item-emit.py，v0.3 T5⑤）：
all-gates.sh run_item/record_item 落的台账行是：

    STATUS|ms|note        # STATUS ∈ PASS|FAIL|SKIP，note 自由文本（可含 |）

与 af 侧同款的诚实规则（逐条保留，不放松）：
  * status 只从台账行直通。本桥不读退出码、更不造 exit_code —— record_item 行
    （SKIP 预检）根本没有对应进程，fabricate exit_code: 0 即是对不存在进程的捏造。
    PASS 永远只能来自台账行的 PASS 字面量，退出码不可单独判绿（v0.3 T5⑤）。
  * SKIP 保持 SKIP，且 skip_reason 映射 fail-loud：只认**已登记**的 SKIP 词表
    （见 SKIP_ENVIRONMENT_MARKERS / SKIP_EXCLUDED_MARKERS，词表来源全部是
    all-gates.sh 现网落盘的注记原文）；词表外的 SKIP 拒绝猜测，退出码 2、
    **不落任何 json** —— 三态汇总层按「未跑成」计，留人工/J5 分类。
  * FAIL 保持 FAIL（超时 rc=124 含在内）。status 词外（被篡改/异内容）→ 降格为
    skip 并在 detail 写明原文（同 af emit normalize 口径：降格件永不当绿）。
  * 拒覆盖：json-out 已存在且内容不同 → 拒写报错（异内容拒覆盖验证）；逐字节
    相同 → 静默幂等。产物一经落定不可被悄悄改写。

与 af 侧的三点差异（均为工作区适配，判据语义零改动）：
  1. 产物落 all-gates RUNDIR（与 item-N.result 同目录），**不写 /tmp** —— 产物要
     留证（RUNDIR 本身带时间戳，run 级 provenance 由目录名承载）。af 侧中间 json
     走 tempfile + 子进程调 emit；本件单文件直写，无 /tmp 中转、无子进程。
  2. 产物在 af GateCheckResult 形状（check_id/required/status/detail/skip_reason）
     之上加 provenance 字段（gate/name/ms/source/schema/generated_by）——全部为
     确定性字段（无墙钟），同输入重放逐字节一致，保住「同内容幂等、异内容拒覆盖」。
  3. SKIP 词表在 af 三词（anolis-only/全局时限/全局预算 → environment_unavailable）
     基础上按 all-gates.sh 现网注记补一词：--fast 跳过 → explicitly_excluded
     （all-gates.sh L4 register 段原文「--fast 跳过 L4」；emit 的 skip_reason 枚举
     三值之一，非新造）。词表外依旧拒判。

HANDOFF：本件不判门、不改门 —— 判据仍在 all-gates.sh；三态结论由件②的
summary_structured 汇总层据本件产物产出。af 仓主线件（af/tools/ 同名件）不动。
"""

import argparse
import json
import os
import sys
from typing import Any

# 已登记 SKIP 词表 → skip_reason（fail-loud：词表外拒判）。
# 词表来源 = all-gates.sh 现网落盘的 SKIP 注记原文（tools/all-gates.sh:473 anolis-only、
# :350 全局时限剩余、:1275-1277 全局时限已到、:949/1299 --fast 跳过 L4）。
SKIP_ENVIRONMENT_MARKERS = ("anolis-only", "全局时限", "全局预算")
SKIP_EXCLUDED_MARKERS = ("--fast 跳过",)

SCHEMA = "ws.gate-item-legacy-bridge/1"
GENERATED_BY = "tools/gate-item-legacy-bridge.py"

STATUSES = {"pass", "fail", "skip"}
SKIP_REASONS = {"not_applicable", "environment_unavailable", "explicitly_excluded"}


def fail(message: str) -> int:
    sys.stderr.write(f"gate-item-legacy-bridge: {message}\n")
    return 2


def parse_result_line(text: str) -> tuple[str, str, str | None]:
    """Split `STATUS|ms|note`；note 可自含管道符。ms 为纯数字则带出，否则 None。"""
    parts = text.rstrip("\n").split("|", 2)
    if len(parts) != 3:
        raise ValueError(f"legacy item result line must be STATUS|ms|note, got: {text!r}")
    status, milliseconds, note = parts
    ms: int | None = None
    if milliseconds.strip().isdigit():
        ms = int(milliseconds.strip())
    return status, note, ms


def skip_reason_for(note: str) -> str:
    """映射已登记 SKIP 词表；词表外拒绝猜测（不落产物，留人工分类）。"""
    for marker in SKIP_ENVIRONMENT_MARKERS:
        if marker in note:
            return "environment_unavailable"
    for marker in SKIP_EXCLUDED_MARKERS:
        if marker in note:
            return "explicitly_excluded"
    raise ValueError(
        "unrecognised legacy SKIP vocabulary (refusing to guess skip_reason): "
        f"{note!r} — classify as one of {sorted(SKIP_REASONS)} or extend "
        "SKIP_ENVIRONMENT_MARKERS/SKIP_EXCLUDED_MARKERS with a recorded marker"
    )


def normalize(item: dict[str, Any], check_id: str, required: bool) -> dict[str, Any]:
    """同款 af tools/gate-item-emit.py normalize：枚举校验 + 退出码永不造 PASS。"""
    status = item.get("status")
    if isinstance(status, str):
        status = status.lower()
    if status not in STATUSES:
        return {
            "check_id": check_id,
            "required": required,
            "status": "skip",
            "skip_reason": "not_applicable",
            "detail": f"legacy item has no explicit PASS/FAIL/SKIP: {item.get('status')!r}",
        }
    if item.get("check_id", check_id) != check_id:
        return {
            "check_id": check_id,
            "required": required,
            "status": "skip",
            "skip_reason": "not_applicable",
            "detail": "legacy item check_id differs from frozen check_id",
        }
    if bool(item.get("required", required)) != required:
        return {
            "check_id": check_id,
            "required": required,
            "status": "skip",
            "skip_reason": "not_applicable",
            "detail": "legacy item required differs from frozen definition",
        }
    detail = str(item.get("detail", ""))
    exit_code = item.get("exit_code")
    # 退出码只是冲突信号，永远造不出 PASS（af 同款注释，逐字保留口径）。
    if status == "pass" and isinstance(exit_code, int) and exit_code != 0:
        return {
            "check_id": check_id,
            "required": required,
            "status": "skip",
            "skip_reason": "not_applicable",
            "detail": f"nonzero exit_code={exit_code} conflicts with PASS",
        }
    result: dict[str, Any] = {
        "check_id": check_id,
        "required": required,
        "status": status,
        "detail": detail,
    }
    if status == "skip":
        reason = item.get("skip_reason")
        if reason not in SKIP_REASONS:
            return {
                "check_id": check_id,
                "required": required,
                "status": "skip",
                "skip_reason": "not_applicable",
                "detail": f"SKIP needs one of {sorted(SKIP_REASONS)}: {reason!r}",
            }
        result["skip_reason"] = reason
    return result


def persist_json(path: str, payload: dict[str, Any]) -> None:
    """同款 af emit persist_json：异内容拒覆盖，同内容幂等，落盘 fsync。"""
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", required=True,
                        help="legacy item-N.result 台账行文件（STATUS|ms|note）")
    parser.add_argument("--json-out", required=True,
                        help="结构化产物路径（工作区侧：all-gates RUNDIR 内 item-N.json，不写 /tmp）")
    parser.add_argument("--check-id", required=True)
    parser.add_argument("--gate", default="", help="provenance：所属门层（L1..L6）")
    parser.add_argument("--name", default="", help="provenance：门项名")
    parser.add_argument("--source", default="", help="provenance：来源台账行文件名（item-N.result）")
    required_group = parser.add_mutually_exclusive_group()
    required_group.add_argument("--required", dest="required", action="store_true", default=True)
    required_group.add_argument("--optional", dest="required", action="store_false")
    args = parser.parse_args()

    try:
        with open(args.result, "r", encoding="utf-8") as source:
            status, note, ms = parse_result_line(source.read())
        st = status.strip().upper()
        item: dict[str, Any] = {
            "check_id": args.check_id,
            "required": args.required,
            "status": st.lower(),
            "detail": note,
        }
        if st == "SKIP":
            item["skip_reason"] = skip_reason_for(note)
        # provenance（确定性字段：无墙钟，保「同内容幂等」）
        item["schema"] = SCHEMA
        item["gate"] = args.gate
        item["name"] = args.name
        item["source"] = args.source
        item["ms"] = ms
        item["generated_by"] = GENERATED_BY
    except OSError as error:
        return fail(f"legacy item result unreadable: {error}")
    except ValueError as error:
        return fail(str(error))

    result = normalize(item, args.check_id, args.required)
    # provenance 随 normalize 结果走（normalize 可能降格 status，字段照带）
    for key in ("schema", "gate", "name", "source", "ms", "generated_by"):
        result[key] = item[key]
    try:
        persist_json(args.json_out, result)
    except (OSError, RuntimeError) as error:
        return fail(f"persist failed: {error}")
    sys.stdout.write(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
