#!/usr/bin/env python3
"""swev-judge-v2-zero-scan.py — D-32/Q1 全库零状态普查（R4 清单穷尽性复核）。

R4 的 8 例零状态清单是否穷尽未裁定（红队裁决 Q1）——"待 log_parsed 修订后全量复扫"。
v2 的零状态判定式（markers + bad_codes + swebench status_map）使之可机械复算：

  Phase 1 预筛（零 spec、零网络、纯文本）：全部 eval.log 按
    bad_code 在场 → eval_error；标记缺失 → no_markers；
    否则若含强 pytest 状态信号（PASSED/FAILED/... 行或 "N passed" 摘要）→ parsed；
    其余 → zero_state 候选（候选集是零状态的超集，不漏）。
  Phase 2 确认（v2 离线判分，repo 感知解析器）：对候选逐个跑 swev-judge-v2.py
    取 log_state 权威值；缓存未命中的 task 先暖缓存（显式放行并留痕）。

扫描范围：/tmp/bench-fix1-d*/ 与 /tmp/bench-fix2-{ab,rerun}-*/（排除 *test*），
含 run 原始 eval.log 与 rejudge-clean/eval.log 两类判分事件。

产物: /tmp/swev-v2-zero-scan-<ts>/{scan.jsonl,census.md}
用法: python3 tools/swev-judge-v2-zero-scan.py [--cache DIR]
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path("/home/pan-ding/workspace/agent黑灯工厂")
V2 = ROOT / "tools" / "swev-judge-v2.py"
VENV_PY = "/home/pan-ding/swev-venv/bin/python"
TASK_DIR = Path("/tmp/swev-s1")
BAD = [">>>>> Patch Apply Failed", ">>>>> Reset Failed", ">>>>> Tests Errored",
       ">>>>> Tests Timed Out"]
START, END = ">>>>> Start Test Output", ">>>>> End Test Output"
STATUS_LINE = re.compile(r"^(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS|xfail)\b")
SUMMARY = re.compile(r"=+ .*(passed|failed|error|no tests ran).* =+", re.I)


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


_TASK_IDS = sorted(p.stem for p in TASK_DIR.glob("*.json")) if TASK_DIR.is_dir() else []


def task_id_of(run_name):
    stem = run_name[len("swev-"):] if run_name.startswith("swev-") else run_name
    best = None
    for tid in _TASK_IDS:
        if stem == tid or stem.startswith(tid + "-"):
            if best is None or len(tid) > len(best):
                best = tid
    return best


def prefilter(log_path):
    """返回 (bucket, evidence)。bucket ∈ eval_error/no_markers/parsed/candidate。"""
    try:
        text = open(log_path, encoding="utf-8", errors="replace").read()
    except OSError as e:
        return "unreadable", str(e)
    if any(b in text for b in BAD):
        return "eval_error", [b for b in BAD if b in text]
    if START not in text or END not in text:
        return "no_markers", {"start": START in text, "end": END in text}
    section = text.split(START, 1)[1].split(END, 1)[0]
    for line in section.split("\n"):
        if STATUS_LINE.match(line.strip()) or SUMMARY.search(line):
            return "parsed", line.strip()[:80]
    # 标记间无强信号：候选（含整节为空/仅 trace 的零状态形态）
    return "candidate", f"section_bytes={len(section)}"


def main():
    ts = time.strftime("%Y%m%d-%H%M%S")
    outdir = Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv else \
        Path(f"/tmp/swev-v2-zero-scan-{ts}")
    outdir.mkdir(parents=True, exist_ok=True)
    cache = sys.argv[sys.argv.index("--cache") + 1] if "--cache" in sys.argv else \
        str(outdir / "cache")

    roots = []
    for pat in ("/tmp/bench-fix1-d*", "/tmp/bench-fix2-ab-*", "/tmp/bench-fix2-rerun-*"):
        for d in sorted(Path("/tmp").glob(pat.removeprefix("/tmp/"))):
            if d.is_dir() and "test" not in d.name:
                roots.append(d)
    logs = []
    for root in roots:
        for run in sorted((root / "runs").glob("*")):
            if not run.is_dir():
                continue
            for kind, p in (("clean", run / "rejudge-clean" / "eval.log"),
                            ("orig", run / "eval.log")):
                if p.is_file() and p.stat().st_size > 0:
                    logs.append((root.name, run.name, kind, str(p)))
    print(f"扫描范围 {len(roots)} 臂目录，eval.log 事件 {len(logs)} 个", flush=True)

    buckets = {"eval_error": [], "no_markers": [], "parsed": [], "candidate": [],
               "unreadable": []}
    for arm, run, kind, p in logs:
        b, ev = prefilter(p)
        buckets[b].append({"arm": arm, "run": run, "kind": kind, "log": p, "ev": ev})
    print("预筛: " + " ".join(f"{k}={len(v)}" for k, v in buckets.items()), flush=True)

    # Phase 2：候选逐个 v2 确认（暖缓存按需）
    warmed = {}
    confirmed = []
    for i, c in enumerate(buckets["candidate"]):
        task_id = task_id_of(c["run"])
        tj = str(TASK_DIR / f"{task_id}.json") if task_id else None
        if not tj or not os.path.isfile(tj):
            c["v2"] = {"error": "no_task_json"}
            confirmed.append(c)
            continue
        if warmed.get(task_id) != "ok":
            r = sh([VENV_PY, str(V2), "--warm-cache", tj],
                   env={"SWEV_JUDGE_V2_ALLOW_LIVE": "1", "SWEV_JUDGE_V2_CACHE": cache})
            j = jlast(r.stdout)
            warmed[task_id] = "ok" if (j and j.get("warm")) else "fail"
        if warmed.get(task_id) != "ok":
            c["v2"] = {"error": "warm_failed"}
            confirmed.append(c)
            continue
        diff = str(Path(c["log"]).parent.parent / "agent.diff") if c["kind"] == "clean" \
            else str(Path(c["log"]).parent / "agent.diff")
        if not os.path.isfile(diff):
            diff = ""
        r = sh([VENV_PY, str(V2), tj, c["log"], diff],
               env={"SWEV_JUDGE_V2_CACHE": cache})
        c["v2"] = jlast(r.stdout) or {"error": f"rc={r.returncode}"}
        confirmed.append(c)
        if (i + 1) % 25 == 0:
            print(f"  确认进度 {i+1}/{len(buckets['candidate'])}", flush=True)

    states = {}
    for c in confirmed:
        st = (c.get("v2") or {}).get("log_state", "v2_error")
        states[st] = states.get(st, 0) + 1
    zero = [c for c in confirmed if (c.get("v2") or {}).get("log_state") == "zero_state"]
    blocked = [c for c in confirmed if (c.get("v2") or {}).get("verdict") == "hermeticity_blocked"]
    invalid = [c for c in confirmed if (c.get("v2") or {}).get("verdict") == "invalid_diff"]

    with open(outdir / "scan.jsonl", "w", encoding="utf-8") as f:
        for c in confirmed:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    lines = ["# D-32/Q1 全库零状态普查（v2 判定式，时点 " + ts + "）", "",
             f"- 扫描臂目录 {len(roots)} 个（fix1-d*/fix2-ab*/fix2-rerun*，排除 *test*）",
             f"- eval.log 判分事件 {len(logs)} 个（orig {sum(1 for l in logs if l[2]=='orig')}"
             f" / clean {sum(1 for l in logs if l[2]=='clean')}）",
             f"- 预筛分桶: " + " ".join(f"{k}={len(v)}" for k, v in buckets.items()),
             f"- 候选 v2 确认后 log_state 分布: {states}",
             f"- 确认零状态 run 事件数: {len(zero)}（去重 run 数 "
             f"{len({c['run'] for c in zero})}）", ""]
    r4_names = {"pallets__flask-5014", "psf__requests-5414", "pytest-dev__pytest-10356",
                "pylint-dev__pylint-8898", "pytest-dev__pytest-5840",
                "sphinx-doc__sphinx-10673", "sympy__sympy-16597"}
    lines += ["## 确认零状态清单（v2 log_state=zero_state，可复算）", "",
              "| run | kind | task | v2.verdict | tests_status_parsed | R4 八例名单 |",
              "|---|---|---|---|---|---|"]
    for c in sorted(zero, key=lambda x: x["run"]):
        v2 = c.get("v2") or {}
        tid = task_id_of(c["run"]) or ""
        lines.append(f"| {c['run']} | {c['kind']} | {tid} | {v2.get('verdict')} "
                     f"| {v2.get('tests_status_parsed')} "
                     f"| {'∈R4' if tid in r4_names else ''} |")
    lines += ["", "## 其它确认态（候选中被 v2 判为非零状态）", ""]
    for c in confirmed:
        st = (c.get("v2") or {}).get("log_state")
        if st and st != "zero_state":
            lines.append(f"- {c['run']} [{c['kind']}] → {st} ({(c.get('v2') or {}).get('verdict')})")
    if blocked:
        lines += ["", f"## hermeticity_blocked {len(blocked)} 例（缓存/网络问题，非零状态）", ""]
        for c in blocked:
            lines.append(f"- {c['run']} [{c['kind']}]")
    if invalid:
        lines += ["", f"## invalid_diff {len(invalid)} 例（diff 非补丁残片，R7 形态）", ""]
        for c in invalid:
            lines.append(f"- {c['run']} [{c['kind']}] reason={(c.get('v2') or {}).get('diff_reject_reason')}")
    (outdir / "census.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:14]), flush=True)
    print(f"\n普查产物: {outdir/'census.md'}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
