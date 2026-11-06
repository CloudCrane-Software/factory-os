#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bot-lane SLA 执行器（2026-11-05 运营者定规落地）：

定规原文：「一小时没回报，或者半小时没有发心跳，就直接取消重派。」
判定面（claims.json，gov 侧 /opt/company/af-bot-lane/data/claims.json）：
  · 心跳 SLA：state==claimed ∧ now-last_seen > 1800s ⇒ 取消重派（last_seen 由
    POST /bot/heartbeat 刷新；bot-lane.py 已有 _reclaim_stalled 同型逻辑，
    本件是工厂侧消费面+重派动作，与在役回收互补）。
  · 回报 SLA：state==claimed ∧ now-claimed_at > 3600s ∧ reported!=True ⇒ 取消重派。
  · 已 reported 的 claim 永不触规（交卷后等收割，不属本件）。
动作：ssh gov 改 claims.json（该 task claim 删除=释回 published 可再领）＋
     工厂侧注册表（state=published 回退，verdict 注 sla-cancelled；占用机检自然转 ALLOW）
     ＋判定落 状态观测/bot-lane-sla.jsonl（审计）。
纪律：只动点名 task；禁 sudo；幂等（同 task 同 ts 窗不重复记）；fail-closed
     （ssh 不可达 ⇒ exit 2 只报不动）。cron 建议 */10。
"""
import json, os, subprocess, sys, time

GOV = os.environ.get("BOT_GOV", "root@gov-host.invalid")
CLAIMS = "/opt/company/af-bot-lane/data/claims.json"
WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REG = os.path.join(WS, "af-state/dispatch/registry.json")
LOG = os.path.join(WS, "状态观测/bot-lane-sla.jsonl")
HB_SLA_S = 1800      # 30min 无心跳
RPT_SLA_S = 3600     # 1h 无回报
TS = "%Y-%m-%dT%H:%M:%S+0800"


def sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)


def main():
    r = sh("ssh -o BatchMode=yes -o ConnectTimeout=10 %s 'cat %s'" % (GOV, CLAIMS))
    if r.returncode != 0:
        print("FAIL ssh 不可达：%s" % r.stderr.strip()[:120])
        return 2
    try:
        claims = json.loads(r.stdout)
    except Exception as e:
        print("FAIL claims.json 不可解析：%s" % e)
        return 2
    now = time.time()
    due = []
    for tid, c in claims.items():
        if c.get("state") != "claimed" or c.get("reported"):
            continue
        last = float(c.get("last_seen") or c.get("claimed_at") or 0)
        age_claim = now - float(c.get("claimed_at") or 0)
        silent = now - last
        if silent > HB_SLA_S or age_claim > RPT_SLA_S:
            due.append({"task_id": tid, "silent_s": int(silent),
                        "age_claim_s": int(age_claim),
                        "rule": "heartbeat>1800" if silent > HB_SLA_S else "report>3600",
                        "claimed_by": c.get("sandbox", "?")})
    if not due:
        print("OK 无触规 claim（%d 条 scanned）" % len(claims))
        return 0
    reg = json.load(open(REG))
    changed = False
    for d in due:
        tid = d["task_id"]
        # 1) gov 侧释回（删 claim 行 → 任务回到可领取）
        rr = sh("ssh -o BatchMode=yes %s \"python3 -c 'import json;p=\\\\\"%s\\\\\";c=json.load(open(p));c.pop(\\\\\"%s\\\\\",None);json.dump(c,open(p,\\\\\"w\\\\\"),indent=1)'\""
                % (GOV, CLAIMS, tid))
        if rr.returncode != 0:
            print("FAIL 释回 %s：%s" % (tid, rr.stderr.strip()[:120]))
            continue
        # 2) 注册表回退 published + 注 verdict
        t = reg["tasks"].get(tid)
        if t and t.get("state") in ("claimed", "submitted"):
            t["state"] = "published"
            t["claimed_by"] = None
            t["verdict"] = "sla-cancelled"
            t["sla"] = d
            changed = True
        # 3) 审计行
        line = {"ts": time.strftime(TS), **d, "action": "cancel-republish"}
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
        print("CANCEL-REPUBLISH %s（%s silent=%ds age=%ds by=%s）"
              % (tid, d["rule"], d["silent_s"], d["age_claim_s"], d["claimed_by"]))
    if changed:
        json.dump(reg, open(REG, "w"), ensure_ascii=False, indent=1)
        sh("python3 -I %s export" % os.path.join(WS, "tools/dispatch-registry.py"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
