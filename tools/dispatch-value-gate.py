#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""G5 价值闸粗阈值器（tools/dispatch-value-gate.py）—— P1 新建面。

判据来源（30-工件/外派-bot-试点/长效机制方案-draft.md §4.1 G5 + D-决议 D6/D7）：
  · §4.1 G5「收益 > 重审成本」：不达标 ⇒ 降级为只读批，或不派。
  · D-决议 D6：价值闸 =「**判绿且增量非空**」⇒ 判绿是必要条件。
  · D-决议 D7：粗阈值「**≥2 条真增量**」开局，首三笔真实机时校准。

本件做什么：
  输入一张收益记录（receipt，schema=af.bot.receipt.v1）⇒ 读「判绿」与「真增量条数」⇒
    判绿 且 真增量 ≥ 阈值(默认 2) ⇒ **CONTINUE**（rc=0）
    否则                                 ⇒ **PAUSE**（rc=1，须人工裁决/校准）
  并把每次决策**记账**到注册表 `meta.calibration.g5`（决策流水 + 计数），
  同时回写该任务在注册表里的 `value.increments`（价值读数随事实长）。

「真增量」怎么数（机读、可复算、只看机器面）：
  增量面按优先级取第一个**非空**的：
    1. receipt["increments"]                      （显式机器面列表；未来收割机写这个）
    2. receipt["value"]["increments"]             （列表或整数）
    3. receipt["changed_files"]                   （收割机本地重跑后**实际改动**的文件清单）
    4. receipt["factory_verification"]            （审计型 receipt 的核验条目）
  每条计入须「非平凡」：去空白后长度 ≥3，且不在占位词表
  （- / — / n/a / na / none / null / 无 / 暂无 / 待补 / 待定 / 待核 / tbd / todo / 空 …），
  且不以 TODO/FIXME/待 开头。
  **不数的面**：receipt["bot_self_reported"]["findings"] 等 bot 自报字段
  （I4「自报不作证据」——那是自报读数，不是厂内可核增量）。

退出码：0=CONTINUE；1=PAUSE；2=不可证（receipt 读不出/记账写不进 ⇒ fail-closed，不猜绿）。
本件零网络、零凭据正文；只写 af-state/dispatch/registry.json 与被点名的 receipt 读面。
"""
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")
REGISTRY_PATH = os.path.join(ROOT, "af-state", "dispatch", "registry.json")
REGISTRY_TOOL = os.path.join(TOOLS, "dispatch-registry.py")

DEFAULT_MIN_INCREMENTS = 2          # D-决议 D7：粗阈值 ≥2 条真增量开局
GREEN_VERDICTS = ("GREEN", "GREEN-CONTENT")

PLACEHOLDER_TOKENS = {
    "-", "--", "---", "—", "——", "n/a", "na", "none", "null", "nil", "no", "x",
    "无", "暂无", "空", "待补", "待定", "待核", "待查", "无变化", "无增量",
    "tbd", "todo", "?", "？", "(无输出)", "（无输出）", "[]", "{}",
}


# ---------------------------------------------------------------- 注册表模块加载

def load_registry_tool():
    """按路径加载 tools/dispatch-registry.py（文件名带连字符 ⇒ 走 importlib）。"""
    if not os.path.exists(REGISTRY_TOOL):
        return None, "注册表工具不存在：%s" % REGISTRY_TOOL
    spec = importlib.util.spec_from_file_location("dispatch_registry", REGISTRY_TOOL)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as exc:                       # noqa: BLE001
        return None, "注册表工具不可加载：%s" % exc
    return mod, None


# ---------------------------------------------------------------- 真增量计数

def _is_trivial(entry):
    if isinstance(entry, dict):
        for k in ("summary", "point", "text", "note", "detail", "title"):
            if k in entry:
                entry = entry.get(k)
                break
        else:
            entry = json.dumps(entry, ensure_ascii=False, sort_keys=True)
    if not isinstance(entry, str):
        return True
    s = entry.strip()
    if len(s) < 3:
        return True
    if s.lower() in PLACEHOLDER_TOKENS:
        return True
    low = s.lower()
    for pre in ("todo", "fixme", "tbd", "待补", "待定", "待核", "待查"):
        if low.startswith(pre):
            return True
    return False


def _count_list(seq):
    if not isinstance(seq, list):
        return 0
    return sum(0 if _is_trivial(e) else 1 for e in seq)


def count_increments(receipt):
    """返回 (真增量条数, 增量面来源, 候选条数, 候选明细摘要)。"""
    if not isinstance(receipt, dict):
        return 0, "none", 0, []
    cand = None
    src = "none"
    if isinstance(receipt.get("increments"), list):
        cand, src = receipt.get("increments"), "increments"
    else:
        val = receipt.get("value")
        if isinstance(val, dict):
            if isinstance(val.get("increments"), list):
                cand, src = val.get("increments"), "value.increments"
            elif isinstance(val.get("increments"), int) and not isinstance(val.get("increments"), bool):
                n = val.get("increments")
                return n, "value.increments(int)", n, []
    if cand is None and isinstance(receipt.get("changed_files"), list) and receipt.get("changed_files"):
        cand, src = receipt.get("changed_files"), "changed_files"
    if cand is None and isinstance(receipt.get("factory_verification"), list) \
            and receipt.get("factory_verification"):
        cand, src = receipt.get("factory_verification"), "factory_verification"
    if cand is None:
        return 0, "none", 0, []
    n = _count_list(cand)
    detail = []
    for e in cand:
        if isinstance(e, str):
            detail.append(e.strip()[:60])
        elif isinstance(e, dict):
            detail.append(json.dumps(e, ensure_ascii=False)[:60])
        else:
            detail.append(str(e)[:60])
    return n, src, len(cand), detail


def read_verdict(receipt):
    """读判绿结论。返回 (verdict, green)。"""
    if not isinstance(receipt, dict):
        return "", False
    v = receipt.get("gate_verdict") or receipt.get("verdict") or ""
    if not isinstance(v, str):
        v = str(v)
    v = v.strip()
    green = v.upper() in GREEN_VERDICTS or v.upper().startswith("GREEN")
    return v, green


# ---------------------------------------------------------------- 记账

def record_decision(registry_path, decision):
    """把一次决策写进注册表 meta.calibration.g5；并回写任务 value.increments。"""
    mod, err = load_registry_tool()
    if err:
        return None, err
    data, err = mod.load_registry(registry_path)
    if err:
        return None, err
    try:
        with mod.WriteLock(registry_path):
            data, err = mod.load_registry(registry_path)
            if err:
                return None, err
            meta = data.setdefault("meta", {})
            cal = meta.setdefault("calibration", {})
            g5 = cal.get("g5")
            if not isinstance(g5, dict):
                g5 = {"threshold": DEFAULT_MIN_INCREMENTS, "continue_count": 0,
                      "pause_count": 0, "decisions": []}
            g5.setdefault("threshold", DEFAULT_MIN_INCREMENTS)
            g5.setdefault("continue_count", 0)
            g5.setdefault("pause_count", 0)
            g5.setdefault("decisions", [])
            entry = dict(decision)
            entry.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%S%z"))
            # 同一张 receipt 重跑 ⇒ 覆盖旧行（校准样本按**不同 receipt**计数，不因重跑而膨胀）
            key = (entry.get("receipt_path"), entry.get("task_id"))
            kept = []
            for old in g5["decisions"]:
                if not isinstance(old, dict) or \
                        (old.get("receipt_path"), old.get("task_id")) != key:
                    kept.append(old)
                    continue
                if old.get("decision") == "CONTINUE":
                    g5["continue_count"] = max(0, int(g5.get("continue_count", 0)) - 1)
                else:
                    g5["pause_count"] = max(0, int(g5.get("pause_count", 0)) - 1)
            g5["decisions"] = kept
            g5["decisions"].append(entry)
            if len(g5["decisions"]) > 500:
                g5["decisions"] = g5["decisions"][-500:]
            if entry.get("decision") == "CONTINUE":
                g5["continue_count"] = int(g5.get("continue_count", 0)) + 1
            else:
                g5["pause_count"] = int(g5.get("pause_count", 0)) + 1
            cal["g5"] = g5
            tasks = data.get("tasks", {})
            tid = entry.get("task_id")
            updated_task = None
            if tid and tid in tasks:
                t = tasks[tid]
                val = t.get("value")
                if not isinstance(val, dict):
                    val = {"increments": 0, "review_min": 0}
                val["increments"] = int(entry.get("increments", 0))
                t["value"] = val
                updated_task = tid
            mod.write_atomic(registry_path, data)
    except RuntimeError as exc:
        return None, str(exc)
    except OSError as exc:
        return None, "写盘失败 %s" % exc
    return {"g5": g5, "task_updated": updated_task}, None


# ---------------------------------------------------------------- 主流程

def run_gate(receipt_path, min_increments=DEFAULT_MIN_INCREMENTS, registry_path=REGISTRY_PATH,
             do_record=True, out=None):
    out = out if out is not None else []
    if not os.path.exists(receipt_path):
        out.append("RED G5：receipt 不存在 %s（不可证 ⇒ fail-closed）" % receipt_path)
        return {"decision": "PAUSE", "reason": "receipt-missing",
                "verdict": "", "green": False, "increments": 0,
                "min_increments": min_increments, "receipt_path": receipt_path}, 2
    try:
        with open(receipt_path, "r", encoding="utf-8") as f:
            receipt = json.load(f)
    except Exception as exc:                       # noqa: BLE001
        out.append("RED G5：receipt 不可解析 %s（%s）（不可证 ⇒ fail-closed）" % (receipt_path, exc))
        return {"decision": "PAUSE", "reason": "receipt-unreadable",
                "verdict": "", "green": False, "increments": 0,
                "min_increments": min_increments, "receipt_path": receipt_path}, 2

    verdict, green = read_verdict(receipt)
    n, src, cand_n, detail = count_increments(receipt)
    task_id = receipt.get("task_id") if isinstance(receipt, dict) else None

    reasons = []
    if not green:
        reasons.append("判绿不成立（gate_verdict=%r）" % verdict)
    if src == "none":
        reasons.append("receipt 无可机读增量面（increments/changed_files/factory_verification 全无）")
    elif n < min_increments:
        reasons.append("真增量 %d 条 < 阈值 %d 条" % (n, min_increments))

    decision = "CONTINUE" if (green and src != "none" and n >= min_increments) else "PAUSE"

    out.append("G5-VALUE-GATE · receipt=%s" % receipt_path)
    out.append("  判绿：%s（%s）" % (verdict or "(无)", "✓ 判绿" if green else "✗ 不判绿"))
    out.append("  增量面：%s（候选 %d 条）" % (src, cand_n))
    out.append("  真增量：%d 条（阈值 ≥%d）" % (n, min_increments))
    if detail:
        for d in detail[:6]:
            out.append("    · %s" % d)
        if len(detail) > 6:
            out.append("    · …（其余 %d 条略）" % (len(detail) - 6))
    for r in reasons:
        out.append("  判红理由：%s" % r)

    result = {"decision": decision, "reason": "; ".join(reasons), "verdict": verdict,
              "green": green, "increments": n, "increment_source": src,
              "candidate_count": cand_n, "min_increments": min_increments,
              "receipt_path": receipt_path, "task_id": task_id}

    if do_record:
        rec, err = record_decision(registry_path, {
            "receipt_path": receipt_path,
            "task_id": task_id,
            "verdict": verdict,
            "green": green,
            "increments": n,
            "increment_source": src,
            "threshold": min_increments,
            "decision": decision,
            "reason": "; ".join(reasons),
        })
        if err:
            out.append("  记账：失败（%s）⇒ fail-closed，决策降为 PAUSE" % err)
            result["decision"] = "PAUSE"
            result["reason"] = (result["reason"] + "; " if result["reason"] else "") \
                + "记账失败（fail-closed）"
            result["recorded"] = False
            return result, 2
        result["recorded"] = True
        out.append("  记账：注册表 %s → meta.calibration.g5（continue=%d pause=%d decisions=%d）"
                   % (registry_path, rec["g5"]["continue_count"], rec["g5"]["pause_count"],
                      len(rec["g5"]["decisions"])))
        if rec["task_updated"]:
            out.append("  回写：tasks[%s].value.increments=%d" % (rec["task_updated"], n))
        else:
            out.append("  回写：注册表无 tasks[%s]（增量只进校准账，未回写任务）"
                       % (task_id if task_id else "(无 task_id)"))
    else:
        result["recorded"] = False
        out.append("  记账：已跳过（--no-record；本结果不可作正式裁决依据）")

    out.append("  决策：%s" % decision)
    return result, (0 if decision == "CONTINUE" else 1)


# ---------------------------------------------------------------- selftest

def _mk_receipt(d, name, obj):
    p = os.path.join(d, name)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    return p


def run_selftest(out):
    d = tempfile.mkdtemp(prefix="dispatch-value-gate-selftest-")
    fails = []
    n = 0
    try:
        # 夹具：一张绿+3 条真增量的 receipt，一张绿+1 条的，一张红的
        good = _mk_receipt(d, "good.json", {
            "schema": "af.bot.receipt.v1",
            "task_id": "rt-e900-valuegate",
            "gate_verdict": "GREEN",
            "changed_files": ["ci/strategies_check.py", "ci/tests/strategies_check_test.rs",
                              "ci/strategies_check.md"],
            "bot_self_reported": {"findings": ["自报一", "自报二", "自报三"]},
        })
        thin = _mk_receipt(d, "thin.json", {
            "schema": "af.bot.receipt.v1",
            "task_id": "rt-e901-valuegate",
            "gate_verdict": "GREEN",
            "changed_files": ["ci/only_one.py"],
            "bot_self_reported": {"findings": ["自报一", "自报二"]},
        })
        red = _mk_receipt(d, "red.json", {
            "schema": "af.bot.receipt.v1",
            "task_id": "rt-e902-valuegate",
            "gate_verdict": "RED",
            "changed_files": ["a.py", "b.py", "c.py", "d.py"],
        })

        # 夹具注册表
        reg = os.path.join(d, "registry.json")
        with open(reg, "w", encoding="utf-8") as f:
            json.dump({"schema_version": 1, "tasks": {
                "rt-e900-valuegate": {"debt_id": "RT-E900", "channel": "bot", "state": "submitted",
                                      "base_sha": "aaa", "claimed_by": "bot", "claimed_at": None,
                                      "verdict": None, "receipt_path": "receipts/x.json",
                                      "value": {"increments": 0, "review_min": 15}},
            }, "meta": {"calibration": {}}}, f, ensure_ascii=False, indent=1)

        # T1 绿+3 增量 ⇒ CONTINUE
        n += 1
        r, rc = run_gate(good, registry_path=reg, out=out)
        if rc != 0 or r["decision"] != "CONTINUE":
            fails.append("T1 绿+3 增量应 CONTINUE rc=0，得 %s rc=%d" % (r["decision"], rc))
        if r["increments"] != 3:
            fails.append("T1 真增量应计 3 条，得 %d" % r["increments"])

        # T2 绿+1 增量 ⇒ PAUSE
        n += 1
        r, rc = run_gate(thin, registry_path=reg, out=out)
        if rc != 1 or r["decision"] != "PAUSE":
            fails.append("T2 绿+1 增量应 PAUSE rc=1，得 %s rc=%d" % (r["decision"], rc))

        # T3 红+4 增量 ⇒ PAUSE（判绿是必要条件，D6）
        n += 1
        r, rc = run_gate(red, registry_path=reg, out=out)
        if rc != 1 or r["decision"] != "PAUSE":
            fails.append("T3 红 receipt 应 PAUSE rc=1，得 %s rc=%d" % (r["decision"], rc))
        if r["green"]:
            fails.append("T3 RED 不得判绿")

        # T4 自报 findings 不计入真增量（I4）
        n += 1
        only_self = _mk_receipt(d, "self.json", {
            "schema": "af.bot.receipt.v1", "task_id": "rt-e903-valuegate",
            "gate_verdict": "GREEN",
            "bot_self_reported": {"findings": ["自报一", "自报二", "自报三"]},
        })
        r, rc = run_gate(only_self, registry_path=reg, out=out)
        if r["increments"] != 0 or r["decision"] != "PAUSE":
            fails.append("T4 只有 bot 自报时真增量应 0 且 PAUSE，得 %d/%s"
                         % (r["increments"], r["decision"]))

        # T5 占位条目不算增量
        n += 1
        ph = _mk_receipt(d, "ph.json", {
            "schema": "af.bot.receipt.v1", "task_id": "rt-e904-valuegate",
            "gate_verdict": "GREEN",
            "changed_files": ["-", "无", "", "   "],
        })
        r, rc = run_gate(ph, registry_path=reg, out=out)
        if r["increments"] != 0:
            fails.append("T5 占位条目不应计入增量，得 %d" % r["increments"])

        # T6 记账落进 registry.meta.calibration.g5
        n += 1
        with open(reg, "r", encoding="utf-8") as f:
            data = json.load(f)
        g5 = data.get("meta", {}).get("calibration", {}).get("g5")
        if not isinstance(g5, dict):
            fails.append("T6 注册表缺 meta.calibration.g5")
        else:
            if g5.get("continue_count") != 1:
                fails.append("T6 continue_count 应为 1（此刻只有 T1 一张绿票），得 %r"
                             % g5.get("continue_count"))
            if g5.get("pause_count") != 4:
                fails.append("T6 pause_count 应为 4（thin/red/自报/占位），得 %r"
                             % g5.get("pause_count"))
            if len(g5.get("decisions", [])) != 5:
                fails.append("T6 decisions 应为 5 条（T1–T5），得 %d" % len(g5.get("decisions", [])))
        if data["tasks"]["rt-e900-valuegate"]["value"]["increments"] != 3:
            fails.append("T6 应回写 tasks[rt-e900-valuegate].value.increments=3")

        # T7 receipt 缺件 ⇒ 不可证 fail-closed
        n += 1
        r, rc = run_gate(os.path.join(d, "nope.json"), registry_path=reg, out=out)
        if rc != 2 or r["decision"] != "PAUSE":
            fails.append("T7 receipt 缺件应 rc=2 + PAUSE，得 %s rc=%d" % (r["decision"], rc))

        # T8 阈值可配：--min-increments 1 ⇒ 绿+1 变 CONTINUE
        n += 1
        r, rc = run_gate(thin, min_increments=1, registry_path=reg, out=out)
        if rc != 0 or r["decision"] != "CONTINUE":
            fails.append("T8 阈值=1 时绿+1 应 CONTINUE，得 %s rc=%d" % (r["decision"], rc))

        # T9 同一张 receipt 重跑 ⇒ 覆盖旧行（校准样本按不同 receipt 计，不因重跑而膨胀）
        n += 1
        r9, rc9 = run_gate(good, registry_path=reg, out=out)
        with open(reg, "r", encoding="utf-8") as f:
            data9 = json.load(f)
        g59 = data9["meta"]["calibration"]["g5"]
        same = [x for x in g59["decisions"] if x.get("receipt_path", "").endswith("good.json")]
        if len(same) != 1:
            fails.append("T9 同一 receipt 重跑后只应留 1 行，得 %d 行" % len(same))
        if g59["continue_count"] != 2:
            fails.append("T9 continue_count 应为 2（T1 的 good + T8 的 thin 翻绿），得 %r"
                         % g59["continue_count"])

        if fails:
            out.append("FAIL selftest %d/%d 过：" % (n - len(fails), n))
            for f in fails:
                out.append("  " + f)
            return 1
        out.append("selftest %d/%d 过（绿+3⇒CONTINUE/绿+1⇒PAUSE/红⇒PAUSE/自报不计增量×2/"
                   "占位不计增量/记账进 meta.calibration.g5+回写 value.increments/"
                   "receipt 缺件 fail-closed/阈值可配/同 receipt 重跑覆盖旧行不膨胀样本）" % (n, n))
        return 0
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---------------------------------------------------------------- CLI

def main(argv):
    out = []
    if "--selftest" in argv:
        rc = run_selftest(out)
        for ln in out:
            print(ln)
        return rc

    import argparse
    p = argparse.ArgumentParser(
        prog="dispatch-value-gate.py",
        description="G5 价值闸粗阈值器：读 receipt ⇒ 判绿 + 真增量条数 ⇒ CONTINUE / PAUSE，"
                    "并记账到注册表 meta.calibration")
    p.add_argument("receipt", nargs="?", help="收益记录路径（receipt JSON）")
    p.add_argument("--min-increments", type=int, default=DEFAULT_MIN_INCREMENTS,
                   help="粗阈值（默认 %d；D-决议 D7）" % DEFAULT_MIN_INCREMENTS)
    p.add_argument("--registry", default=REGISTRY_PATH, help="注册表路径")
    p.add_argument("--no-record", action="store_true", help="不记账（干跑；结果不作正式裁决依据）")
    p.add_argument("--json", action="store_true", help="输出 JSON")
    args = p.parse_args(argv)

    if not args.receipt:
        p.print_help()
        return 2
    result, rc = run_gate(args.receipt, min_increments=args.min_increments,
                           registry_path=args.registry, do_record=not args.no_record, out=out)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
    else:
        for ln in out:
            print(ln)
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
