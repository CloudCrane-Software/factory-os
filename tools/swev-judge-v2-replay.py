#!/usr/bin/env python3
"""swev-judge-v2-replay.py — D-32 交付回放：v1↔v2 对判既有 run，产出逐条差异清单。

样本（全部只读，零容器、零改写）:
  A /tmp/bench-fix1-d1-m31f      清洁判分日志（rejudge-clean/eval.log）
  B /tmp/bench-fix1-d2-glm-cp    清洁判分日志（含 R4 零状态候选 pylint-8898/
                                  pytest-5840/sphinx-10673 与 R7 ssh 残片 sphinx-8120-a2）
  C /tmp/bench-fix1-d2-glm-max   清洁判分日志（含 R7 ssh 残片 sympy-19783-a1）
  另加反事实对：同一好日志 × ssh 残片 diff（证明 v1 判定与 diff 内容无关的假阳性面）

流程: 每个唯一 task 先暖 v2 离线缓存（SWEV_JUDGE_V2_ALLOW_LIVE=1，留痕）→ v2 默认
离线判分 → v1 实呼判分（R5：网络抖动即崩，重试 3 次仍崩如实记 v1_crash）。
对历史 v1 读数（truth-rejudge/*/results.jsonl verifier_note）做确定性锚点校验。

产物: /tmp/swev-v2-replay-<ts>/{replay.jsonl,diff.md}
用法: python3 tools/swev-judge-v2-replay.py [--out DIR]
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path("/home/pan-ding/workspace/agent黑灯工厂")
V2 = ROOT / "tools" / "swev-judge-v2.py"
V1 = ROOT / "tools" / "swev-judge.py"
VENV_PY = "/home/pan-ding/swev-venv/bin/python"
TASK_DIR = Path("/tmp/swev-s1")
ARMS = [
    ("A-m31f", "/tmp/bench-fix1-d1-m31f"),
    ("B-d2-glm-cp", "/tmp/bench-fix1-d2-glm-cp"),
    ("C-d2-glm-max", "/tmp/bench-fix1-d2-glm-max"),
]
HIST_DIR = {"A-m31f": "/tmp/truth-rejudge/bench-fix1-d1-m31f/results.jsonl",
            "B-d2-glm-cp": "/tmp/truth-rejudge/bench-fix1-d2-glm-cp/results.jsonl",
            "C-d2-glm-max": "/tmp/truth-rejudge/bench-fix1-d2-glm-max/results.jsonl"}


def sh(cmd, env=None, timeout=300):
    e = dict(os.environ)
    e.pop("SWEV_JUDGE_V2_ALLOW_LIVE", None)
    if env:
        e.update(env)
    return subprocess.run(cmd, capture_output=True, text=True, env=e, timeout=timeout)


def jlast(text):
    try:
        return json.loads(text.strip().splitlines()[-1])
    except Exception:
        return None


def task_json_for(task_id):
    p = TASK_DIR / f"{task_id}.json"
    return str(p) if p.is_file() else None


_TASK_IDS = sorted(p.stem for p in TASK_DIR.glob("*.json")) if TASK_DIR.is_dir() else []


def task_id_of(run_name):
    """swev-<repo>__<repo>-<number>-<profile 可含横线>-a<N> → task_id。
    profile 形如 mavis-m31f/glm-cp-max/qwen30b-local 含横线，故按 task.json
    文件名清单做前缀锚定（最长匹配）。"""
    stem = run_name[len("swev-"):] if run_name.startswith("swev-") else run_name
    best = None
    for tid in _TASK_IDS:
        if stem == tid or stem.startswith(tid + "-"):
            if best is None or len(tid) > len(best):
                best = tid
    return best


def load_hist(arm):
    """历史 v1 读数锚点：run 目录名 → judge JSON（从 verifier_note 解析）。"""
    out = {}
    p = HIST_DIR.get(arm)
    if not p or not os.path.isfile(p):
        return out
    for line in open(p, encoding="utf-8"):
        try:
            row = json.loads(line)
        except Exception:
            continue
        note = row.get("verifier_note") or ""
        if note.startswith("judge: "):
            j = jlast(note[len("judge: "):])
            if j:
                run = os.path.basename(row.get("run_dir", ""))
                out[run] = j
    return out


def main():
    ts = time.strftime("%Y%m%d-%H%M%S")
    outdir = Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv else \
        Path(f"/tmp/swev-v2-replay-{ts}")
    outdir.mkdir(parents=True, exist_ok=True)
    cache = str(outdir / "cache")
    print(f"回放输出: {outdir}  cache: {cache}", flush=True)

    # -- 枚举样本 ----------------------------------------------------------
    runs = []  # (arm, run_name, task_id, attempt, log_path, log_kind, diff_path, note)
    for arm, root in ARMS:
        for run in sorted((Path(root) / "runs").glob("*")):
            if not run.is_dir():
                continue
            name = run.name
            task_id = task_id_of(name)
            attempt = name.rsplit("-", 1)[-1]
            clean = run / "rejudge-clean" / "eval.log"
            orig = run / "eval.log"
            if clean.is_file() and clean.stat().st_size > 0:
                log_path, kind = str(clean), "clean"
            elif orig.is_file():
                log_path, kind = str(orig), "orig"
            else:
                continue
            diff = run / "agent.diff"
            if not diff.is_file():
                continue
            runs.append((arm, name, task_id, attempt, log_path, kind, str(diff), ""))
    print(f"样本 run 数: {len(runs)}", flush=True)

    # -- 暖缓存（每唯一 task 一次） ---------------------------------------
    warmed = {}
    for arm, name, task_id, *_rest in runs:
        if not task_id or task_id in warmed:
            continue
        tj = task_json_for(task_id)
        if not tj:
            warmed[task_id] = "no_task_json"
            continue
        r = sh([VENV_PY, str(V2), "--warm-cache", tj],
               env={"SWEV_JUDGE_V2_ALLOW_LIVE": "1", "SWEV_JUDGE_V2_CACHE": cache})
        j = jlast(r.stdout)
        ok = bool(j and j.get("warm"))
        warmed[task_id] = "ok" if ok else f"warm_failed rc={r.returncode}"
        if not ok:
            print(f"  warm FAIL {task_id}: {r.stderr[-160:]}", flush=True)
    n_warm_ok = sum(1 for v in warmed.values() if v == "ok")
    print(f"暖缓存: {n_warm_ok}/{len(warmed)} task ok", flush=True)

    # -- 对判 --------------------------------------------------------------
    rows, v1_crash, diffs = [], 0, []
    for i, (arm, name, task_id, attempt, log_path, kind, diff, _n) in enumerate(runs):
        tj = task_json_for(task_id)
        rec = {"arm": arm, "run": name, "task_id": task_id, "attempt": attempt,
               "log": log_path, "log_kind": kind, "diff": diff}
        if not tj or warmed.get(task_id) != "ok":
            rec["skip"] = f"task_json/warm: {tj} {warmed.get(task_id)}"
            rows.append(rec)
            continue
        v1j, v1crash = None, False
        for _ in range(3):  # R5：v1 实呼，网络抖动即崩
            r1 = sh([VENV_PY, str(V1), tj, log_path, diff])
            v1j = jlast(r1.stdout)
            if v1j:
                break
            v1crash = True
        if not v1j:
            v1_crash += 1
        r2 = sh([VENV_PY, str(V2), tj, log_path, diff],
                env={"SWEV_JUDGE_V2_CACHE": cache})
        v2j = jlast(r2.stdout)
        rec["v1"] = v1j
        rec["v2"] = v2j
        rec["v1_crash"] = v1crash and not v1j
        d = {}
        if v1j and v2j:
            if v1j.get("resolved") != v2j.get("resolved"):
                d["resolved"] = {"v1": v1j.get("resolved"), "v2": v2j.get("resolved")}
            if v1j.get("log_parsed") != v2j.get("log_parsed"):
                d["log_parsed"] = {"v1": v1j.get("log_parsed"), "v2": v2j.get("log_parsed")}
        rec["diff"] = d
        if d:
            diffs.append(rec)
        rows.append(rec)
        if (i + 1) % 20 == 0:
            print(f"  {i+1}/{len(runs)}", flush=True)

    # -- 反事实对：好日志 × ssh 残片 diff ----------------------------------
    ssh_residue = outdir / "ssh-residue.diff"
    ssh_residue.write_bytes(b"ssh: connect to host anolis-host.invalid port 22: Connection timed out\r\n")
    cf = []
    for arm, name, task_id, attempt, log_path, kind, diff, _n in runs:
        if kind != "clean" or not task_id or task_id not in ("pallets__flask-5014",):
            continue
        tj = task_json_for(task_id)
        r1 = sh([VENV_PY, str(V1), tj, log_path, str(ssh_residue)])
        r2 = sh([VENV_PY, str(V2), tj, log_path, str(ssh_residue)],
                env={"SWEV_JUDGE_V2_CACHE": cache})
        cf.append({"arm": arm, "run": name, "task_id": task_id, "log": log_path,
                   "v1": jlast(r1.stdout), "v2": jlast(r2.stdout)})
        break
    # flask 清洁日志取不到时用样本内任一 clean 日志
    if not cf:
        for arm, name, task_id, attempt, log_path, kind, diff, _n in runs:
            if kind == "clean" and task_id and warmed.get(task_id) == "ok":
                tj = task_json_for(task_id)
                r1 = sh([VENV_PY, str(V1), tj, log_path, str(ssh_residue)])
                r2 = sh([VENV_PY, str(V2), tj, log_path, str(ssh_residue)],
                        env={"SWEV_JUDGE_V2_CACHE": cache})
                cf.append({"arm": arm, "run": name, "task_id": task_id, "log": log_path,
                           "v1": jlast(r1.stdout), "v2": jlast(r2.stdout)})
                break

    # -- 历史锚点校验 -------------------------------------------------------
    anchor = {"checked": 0, "mismatch": []}
    for arm, _root in ARMS:
        hist = load_hist(arm)
        for rec in rows:
            if rec["arm"] != arm or rec.get("v1") is None:
                continue
            h = hist.get(rec["run"])
            if not h:
                continue
            anchor["checked"] += 1
            if (h.get("resolved") != rec["v1"].get("resolved")
                    or h.get("log_parsed") != rec["v1"].get("log_parsed")):
                anchor["mismatch"].append({"run": rec["run"], "hist": h, "fresh": rec["v1"]})

    # -- 落盘 --------------------------------------------------------------
    with open(outdir / "replay.jsonl", "w", encoding="utf-8") as f:
        for rec in rows:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    n_judged = sum(1 for r in rows if r.get("v1") and r.get("v2"))
    summary = {
        "ts": ts, "runs_total": len(runs), "runs_judged_both": n_judged,
        "v1_crash_after_retry": v1_crash, "diff_runs": len(diffs),
        "diff_resolved": sum(1 for r in diffs if "resolved" in r["diff"]),
        "diff_log_parsed_only": sum(1 for r in diffs if "log_parsed" in r["diff"] and "resolved" not in r["diff"]),
        "warm": {"ok": n_warm_ok, "total": len(warmed),
                 "failed": {k: v for k, v in warmed.items() if v != "ok"}},
        "hist_anchor": anchor, "counterfactual": cf,
    }
    (outdir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1),
                                         encoding="utf-8")

    lines = ["# D-32 判分器 v2 回放差异清单（v1↔v2 对判）", "",
             f"- 时点: {ts}｜样本 run: {len(runs)}（双臂清洁日志 + ssh 残片反事实对）",
             f"- 双判成功: {n_judged}｜v1 重试后仍崩: {v1_crash}（R5 网络抖动实证）",
             f"- 差异 run 数: {len(diffs)}（resolved 变 {summary['diff_resolved']} / "
             f"仅 log_parsed 变 {summary['diff_log_parsed_only']}）",
             f"- 历史锚点校验: {anchor['checked']} 例 v1-fresh vs v1-historical，"
             f"不一致 {len(anchor['mismatch'])} 例", ""]
    if diffs:
        lines += ["## 逐条差异", "",
                  "| run | log_kind | v1.resolved | v2.resolved | v1.log_parsed | v2.log_parsed | v2.verdict | v2.log_state | v2.diff_reject_reason |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for r in diffs:
            v1, v2 = r.get("v1") or {}, r.get("v2") or {}
            lines.append(
                f"| {r['run']} | {r['log_kind']} | {v1.get('resolved')} | {v2.get('resolved')} "
                f"| {v1.get('log_parsed')} | {v2.get('log_parsed')} | {v2.get('verdict')} "
                f"| {v2.get('log_state')} | {v2.get('diff_reject_reason') or ''} |")
        lines.append("")
    if cf:
        lines += ["## 反事实对：好日志 × ssh 残片 diff（v1 判定与 diff 内容无关的假阳性面）", ""]
        for c in cf:
            lines.append(f"- {c['run']}（{c['task_id']}，日志 {os.path.basename(c['log'])}）")
            lines.append(f"  - v1: {json.dumps(c['v1'], ensure_ascii=False)}")
            lines.append(f"  - v2: {json.dumps(c['v2'], ensure_ascii=False)}")
        lines.append("")
    if anchor["mismatch"]:
        lines += ["## 历史锚点不一致（v1-fresh ≠ v1-historical）", ""]
        for m in anchor["mismatch"]:
            lines.append(f"- {m['run']}: hist={json.dumps(m['hist'], ensure_ascii=False)} "
                         f"fresh={json.dumps(m['fresh'], ensure_ascii=False)}")
        lines.append("")
    (outdir / "diff.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:20]), flush=True)
    print(f"\n差异清单: {outdir/'diff.md'}｜原始: {outdir/'replay.jsonl'}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
