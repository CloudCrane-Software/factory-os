#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bot-harvest-sweep.py — bot 通道收割 sweep（制度 v1 §三·路2，cron */20）。

确定性：扫 gov submissions 新件（本地 receipts 无同 stem）→ bot-reclaim.sh 全链
→ 读 receipt 门裁决：GREEN→registry 自动推进 submitted→adjudicated→(audited-green-content)
；RED/STALE_RED→af-state/dispatch/exceptions.jsonl 落异常队列（主代理/巡检裁决）。
absorb-into-repo 型卡在 wave 清单里声明 absorb 命令则代跑（默认仅登记）。
幂等：同 stem 已见即跳。fail-closed：ssh 不可达只报不动。
"""
import json
import os
import subprocess
import sys
import time

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRIAL = os.path.join(WS, "30-工件", "外派-bot-试点")
RECEIPTS = os.path.join(TRIAL, "receipts")
EXC = os.path.join(WS, "af-state", "dispatch", "exceptions.jsonl")
GOV = os.environ.get("BOT_GOV", "root@gov-host.invalid")
REMOTE_SUB = "/opt/company/af-bot-lane/data/submissions"
TS = "%Y-%m-%dT%H:%M:%S+0800"


def sh(cmd, timeout=600):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)


def exc(tid, stage, evidence):
    # D-88 伴生改造（factory-os#23）：红件落队 20 分钟窗同因去重＋计数。
    # 同 (task_id, stage, evidence) 在 20 分钟窗内重复落队：不追加第二条整行，
    # 只追加一行 dedup 计数行（count=窗内同因累计次数）；既有行零删除零改写
    # （append-only 审计面，C-4 邻接；基线 411 行/17 task/单件 ×56）。
    # 窗界比较用行内 ts（与 TS 同构），无时钟外泄面；损坏行跳过不参与判定。
    os.makedirs(os.path.dirname(EXC), exist_ok=True)
    ev = evidence[:400]
    cutoff = time.time() - 20 * 60
    prior = 0
    try:
        with open(EXC, "r", encoding="utf-8") as f:
            for ln in f:
                try:
                    r = json.loads(ln)
                except Exception:
                    continue
                if not (r.get("task_id") == tid and r.get("stage") == stage
                        and r.get("evidence") == ev):
                    continue
                try:
                    t = time.mktime(time.strptime(str(r.get("ts", ""))[:19],
                                                  "%Y-%m-%dT%H:%M:%S"))
                except Exception:
                    continue
                if t >= cutoff:
                    prior += 1
    except OSError:
        prior = 0
    row = {"ts": time.strftime(TS), "task_id": tid, "stage": stage, "evidence": ev}
    if prior:
        row["dedup"] = True
        row["count"] = prior
    with open(EXC, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def task_of(stem):
    parts = stem.rsplit("-", 1)
    return parts[0] if len(parts) == 2 else stem


def seen_stems():
    out = set()
    if os.path.isdir(RECEIPTS):
        for f in os.listdir(RECEIPTS):
            if f.endswith(".json"):
                out.add(f[:-5])
    return out


def _reg(*a):
    return sh("cd %s && python3 -I tools/dispatch-registry.py %s" % (WS, " ".join(a)))


def registry_walk(tid, verdict):
    cur = None
    try:
        reg = json.load(open(os.path.join(WS, "af-state", "dispatch", "registry.json")))
        cur = (reg.get("tasks", {}).get(tid) or {}).get("state")
    except Exception:
        cur = None
    if cur in ("merged", "rejected"):
        return  # 幂等：已终态
    if cur == "published":
        _reg("transition", "--task-id", tid, "--to", "claimed", "--claimed-by", "grok-bot")
    if cur in ("queued", "packaged", "published", "claimed"):
        _reg("transition", "--task-id", tid, "--to", "submitted", "--receipt-path",
             "30-工件/外派-bot-试点/receipts/%s.json" % tid)
    _reg("transition", "--task-id", tid, "--to", "adjudicated", "--verdict", verdict)
    _reg("transition", "--task-id", tid, "--to", "rejected" if "red" in verdict else "merged", "--verdict", verdict)
    _reg("export")


def main():
    r = sh("ssh -o BatchMode=yes -o ConnectTimeout=10 %s 'ls %s/*.json 2>/dev/null'" % (GOV, REMOTE_SUB), timeout=60)
    if r.returncode != 0:
        print("FAIL ssh 不可达：%s" % r.stderr.strip()[:120]); return 2
    stems = set()
    for line in (r.stdout or "").splitlines():
        b = os.path.basename(line.strip())
        if b.endswith(".json"):
            stems.add(b[:-5])
    new = sorted(stems - seen_stems())
    if not new:
        print("OK 无新交卷（%d 件在册）" % len(stems)); return 0
    print("NEW %d 件：%s" % (len(new), ",".join(new)))
    for stem in new:
        tid = task_of(stem)
        if not tid or "/" in tid:
            exc(tid or "?", "shape", "stem 非法：%s" % stem); continue
        r = sh("cd %s && bash 30-工件/外派-bot-试点/tool/bot-reclaim.sh %s" % (WS, tid), timeout=900)
        rp = os.path.join(RECEIPTS, tid + ".json")
        verdict = None
        if os.path.isfile(rp):
            try:
                verdict = json.load(open(rp)).get("gate_verdict")
            except Exception:
                verdict = None
        if verdict == "GREEN":
            registry_walk(tid, "audited-green-content")
            print("GREEN %s → absorb 登记讫" % tid)
        else:
            exc(tid, "harvest", "门裁决=%s（reclaim rc=%d）" % (verdict, r.returncode))
            registry_walk(tid, ("stale-red" if verdict == "STALE_RED" else "g-judge-red"))
            print("RED %s → 异常队列" % tid)
    return 0


if __name__ == "__main__":
    sys.exit(main())
