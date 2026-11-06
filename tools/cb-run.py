#!/usr/bin/env python3
"""cb-run.py — codebuddy deepseek-cb 档案 120 题常驻编排器（守护形态）。

复用 cb-dispatch.py 的 API/state/模板（state 文件互通：/tmp/cb-dispatch/<org>__<repo>.json），
在其上加常驻 run-loop：

  每轮（--poll 秒，默认 30）：
    1. quota 护栏：dev 已用+冻结 ≥ --quota-pause（默认 0.8）× 免费额度 → 暂停该 org 派发（日志明示）。
    2. 轮询两 org build logs → 刷新 sn/build_status；
       success → 收补丁分支（连续 10 轮拿不到 → 记 no_patch 结果行，按 SWE-bench 无补丁计未解决）；
       超 --timeout-min（默认 60）未终态 → state 记 timeout、释放槽位、留人工（不自动重派）；
       failed 同理留人工。
    3. 派发：维持每 org ≤ --target（默认 5）in-flight（在飞=沙箱未交卷：未判分、未收补丁、
       未 blocked、非 timeout/failed）；org 按剩余槽位动态均衡；任务按 120 名单顺序（D1→D3）
       取两 org state 并集里没有的题（全局去重，每题只派一次）；发行限速 3s/issue。
    4. 判分队列：收补丁的题排队，2 个 worker 线程跑 cb-judge.sh（本机判分并发 ≤2，
       全部 subprocess 带 stdin=DEVNULL——mingda 教训）；判完追加结果行到
       /tmp/bench-fix1-{tier}-deepseek-cb/results.jsonl（字段口径与首两行一致；tier 从
       计划/s1-swev-120.json 查）→ state 记 judged。镜像缺失先 fast-pull.py 按需补拉
       （盘 ≥88% 或拉取失败 → blocked_no_image 留人工，不占派发槽位）。

并发一致性：state 全部走 load-modify-save（RLock 内），多线程不互踩。
口径：profile=deepseek-cb（codebuddy NPC harness + deepseek-v4.1-flash），与 af-bench 不混算。
agent_wall_ms 取 build log 的 duration；逐题 token/model_calls 审计在 NPC 日志页（API 400 拿不到），
批量模式记 null 留人工汇总——不编数。

用法:
  cb-run.py run  [--target N] [--poll S] [--once]      # 常驻主循环（守护入口）
  cb-run.py summary                                    # 巡检读数（state+results 汇总）
  cb-run.py quota                                      # 两 org dev 池读数

启动（脱离会话常驻）:
  setsid nohup python3 tools/cb-run.py run >> /tmp/cb-run.log 2>&1 < /dev/null &
密钥纪律：token 走 cb-dispatch 的 bao_field 管道，不落盘、不打印。
"""
import argparse
import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
import traceback

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("cb_dispatch", os.path.join(_HERE, "cb-dispatch.py"))
cb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cb)

WS = "/home/pan-ding/workspace/agent黑灯工厂"
NAMELIST = f"{WS}/计划/s1-swev-120.json"
TASKS_DIR = "/tmp/swev-s1"
ORGS = ["zhuzhu-team", "cloudbird-software"]
REPO = "cb-npc-poc"
JUDGE_SH = os.path.join(_HERE, "cb-judge.sh")
FAST_PULL = os.path.join(_HERE, "fast-pull.py")

stop_flag = threading.Event()
judge_q = []                      # [(org, tid)]
judge_queued = set()              # 防重复入队
state_lock = threading.RLock()    # state 与结果行落盘共用（可重入：judge 线程写行不锁死主循环）
pull_lock = threading.Lock()      # 镜像补拉单并发
judge_running = set()             # 正在判分的 tid（展示用）

# CNB build 终态集合（2026-10-21 修理组实证补齐）：success 之外，failed 与 **error**
# 都是平台终态（django-16263 即卡 error 永不释放的实例），timeout 是本守护的记账终态。
TERMINAL_BS = ("success", "failed", "error", "timeout")


def log(msg):
    print(time.strftime("%m-%d %H:%M:%S"), msg, flush=True)


def sh(cmd, timeout=600):
    # stdin=DEVNULL：防子进程吞父进程 stdin 挂起（mingda 实测教训）
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                          stdin=subprocess.DEVNULL)


def update_state(org, mut):
    """state 唯一写入口：load → mut（闭包改 dict）→ save，锁内原子。"""
    with state_lock:
        st = cb.load_state(org, REPO)
        ret = mut(st)
        cb.save_state(org, REPO, st)
        return ret


def load_namelist():
    tasks = json.load(open(NAMELIST, encoding="utf-8"))
    return {t["instance_id"]: t["tier"].lower() for t in tasks}


def load_full_tasks():
    out = {}
    for fn in os.listdir(TASKS_DIR):
        if fn.endswith(".json"):
            t = json.load(open(os.path.join(TASKS_DIR, fn), encoding="utf-8"))
            out[t["instance_id"]] = t
    return out


def results_path(tier):
    return f"/tmp/bench-fix1-{tier}-deepseek-cb/results.jsonl"


def slot_free(v):
    """沙箱槽位是否已释放（交卷/终态/blocked 都算空槽）。"""
    return (v.get("judged") or v.get("collected") or v.get("judge_blocked")
            or v.get("build_status") in ("timeout", "failed", "error"))


def inflight_count(st):
    return sum(1 for v in st.values() if not slot_free(v))


def quota_snapshot(org):
    q = cb.api(org, "GET", f"/{org}/-/charge/quota")
    v = cb.api(org, "GET", f"/{org}/-/charge/volume")
    return (q.get("dev_in_sec", {}).get("free", 0),
            v.get("dev_in_sec", 0), v.get("freeze_dev_in_sec", 0))


def preseed_judged(tier_of):
    """历史已完成题（results.jsonl 已有 completed 行）补 judged 标记，防重判重派。"""
    for tier in ("d1", "d2", "d3"):
        p = results_path(tier)
        if not os.path.exists(p):
            continue
        for line in open(p, encoding="utf-8"):
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("status") != "completed":
                continue
            tid = r.get("task_id")
            org = next((o for o in ORGS if tid in cb.load_state(o, REPO)), None)
            if org is None:
                continue

            def mut(st, tid=tid):
                if not st[tid].get("judged"):
                    st[tid]["judged"] = True
                    st[tid].setdefault("tier", tier_of.get(tid, "?"))
                    return True
                return False
            if update_state(org, mut):
                log(f"preseed: {tid} 已在 results.jsonl（历史 PoC），记 judged")


def enqueue(org, tid):
    # 在判中的题不再入队（watch 每轮都会对 collected 重复 enqueue）
    if tid not in judge_queued and tid not in judge_running:
        judge_queued.add(tid)
        judge_q.append((org, tid))
        log(f"judge queued {tid}")


def write_result_line(tid, tier, reward, gate, status, agent_wall_ms, note):
    line = {"suite": "swe-v", "task_id": tid, "profile": "deepseek-cb",
            "trial": False, "reward": reward, "status": status,
            "scaffold": "codebuddy-npc", "gate": gate, "attempts": 1,
            "turns": None, "model_calls": None, "tokens": None,
            "agent_wall_ms": agent_wall_ms,
            "verifier_note": note}
    p = results_path(tier)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with state_lock:
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    log(f"RESULT {tid} tier={tier} reward={reward} gate={gate} -> {p}")


def refresh_sn_status(org, st):
    """按 sn 直查 build/status 权威刷新非终态任务（2026-10-21 修理组补）。

    根因：/-/build/logs 列表只回最近 30 条，在飞条目被后续构建滚出列表后，
    map_builds 永远看不见它 → build_status 冻结在旧值（matplotlib-20859 实为
    success 跑了 2.37h，账面停在 pending 四小时）。对仍在飞的任务按 sn 查
    权威状态 API 补齐，顺带把 wall 时长带回来。"""
    for tid, v in st.items():
        if v.get("judged") or v.get("collected") or v.get("judge_blocked"):
            continue
        bs = v.get("build_status")
        if not v.get("sn") or bs in TERMINAL_BS:
            continue
        d = cb.api(org, "GET", f"/{org}/{REPO}/-/build/status/{v['sn']}")
        s = d.get("status") if isinstance(d, dict) else None
        if not s or s == bs:
            continue
        v["build_status"] = s
        if s == "success":
            pls = d.get("pipelinesStatus") or {}
            # 管道键为 sn 或 sn-001（实测两种都有）
            pl = pls.get(v["sn"]) or pls.get(f"{v['sn']}-001") or {}
            v.setdefault("agent_wall_ms", pl.get("duration"))
        log(f"sn-refresh {org} {tid}: {bs} → {s}（权威 status API，"
            f"logs 列表 30 条窗已滚不出该条）")


def watch_phase(org, args, tier_of):
    """轮询单 org：刷新 build 状态 → 收补丁入队 / 超时 / 失败记账。"""
    def mut(st):
        cb.map_builds(org, REPO, st)
        refresh_sn_status(org, st)
        now = time.time()
        for tid, v in list(st.items()):
            if v.get("judged"):
                continue
            bs = v.get("build_status")
            if v.get("collected"):
                if not v.get("judge_blocked"):
                    enqueue(org, tid)
            elif bs == "success":
                collect_one(org, st, tid, v, tier_of)
            elif bs in ("failed", "error"):
                # 终态留人工（error 与 failed 同为平台终态，记账同桶）；只报一次
                if v.get("terminal_note") != bs:
                    v["terminal_note"] = bs
                    log(f"FAILED {tid} issue #{v.get('issue')} build={bs} → 终态留人工，释放槽位")
            elif (bs not in TERMINAL_BS and v.get("dispatched_at")
                  and now - v["dispatched_at"] > args.timeout_min * 60):
                # 超时判定覆盖一切非终态（旧实现只认 dispatched/running/None，
                # 漏 pending——排队 4h 的 matplotlib-20859 即此漏网）
                v["build_status"] = "timeout"
                if not v.get("timeout_marked"):
                    v["timeout_marked"] = True
                    log(f"TIMEOUT {tid}: 派发超 {args.timeout_min}min 未完成 → 释放槽位，"
                        f"不自动重派留人工（issue #{v.get('issue')} sn={v.get('sn')}）")
        return True
    update_state(org, mut)


def collect_one(org, st, tid, v, tier_of):
    """build success → 收补丁；连续 10 轮拿不到分支记 no_patch 结果行。"""
    p = cb.collect(org, REPO, tid, st)
    if p:
        try:
            logs = cb.api(org, "GET", f"/{org}/{REPO}/-/build/logs")
            items = logs.get("data") if isinstance(logs, dict) else logs
            for it in items or []:
                url = (it.get("eventUrl") or "").rstrip("/")
                if url.endswith(f"/issues/{v['issue']}"):
                    v["agent_wall_ms"] = it.get("duration")
        except Exception:
            pass
        log(f"collect {tid}: 补丁收讫 {p} wall_ms={v.get('agent_wall_ms')}")
        enqueue(org, tid)
        return
    v["no_patch_tries"] = v.get("no_patch_tries", 0) + 1
    if v["no_patch_tries"] >= 10:  # 10 轮 ×30s ≈ 5min 仍无分支
        log(f"collect {tid}: 连续 {v['no_patch_tries']} 轮无补丁分支 → 记 no_patch")
        write_result_line(tid, v.get("tier") or tier_of.get(tid, "?"),
                          reward=False, gate="no_patch", status="completed",
                          agent_wall_ms=v.get("agent_wall_ms"),
                          note=(f"build=success 但 results/{tid} 分支或补丁文件缺失"
                                f"（连续 {v['no_patch_tries']} 轮收不到），"
                                f"按 SWE-bench 无补丁计未解决；issue #{v.get('issue')} 留查"))
        v["judged"] = True
    # 未到 10 轮：留在 state（外层 update_state 统一落盘），下轮再收


def dispatch_phase(org, args, tier_of, full_tasks):
    if quota_snapshot_paused.get(org):
        return
    while not stop_flag.is_set():
        # 全局去重：待派 = 120 名单 − 两 org state 的并集（每题全局只跑一次）
        done_anywhere = set()
        for o in ORGS:
            done_anywhere.update(cb.load_state(o, REPO))
        if inflight_count(cb.load_state(org, REPO)) >= args.target:
            return
        nxt = next((t for t in tier_of if t not in done_anywhere), None)
        if not nxt:
            return  # 本 org 无剩余（120 题全入 state）
        if not dispatch_one(org, nxt, full_tasks[nxt], tier_of[nxt]):
            return  # 通道级失败，下轮再试
        time.sleep(3)  # 发行限速 3s/issue


def dispatch_one(org, tid, task, tier):
    slug = f"{org}/{REPO}"
    body = (f"[SWE 任务包 {tid}] 真实上游 issue（base="
            f"{task.get('base_commit','')}）：\n\n{task['problem_statement']}\n\n"
            f"（修复指令见评论。请先读本 issue 全文理解问题。）")
    issue = cb.api(org, "POST", f"/{slug}/-/issues",
                   {"title": f"[swev] {tid}", "body": body})
    num = issue.get("number")
    if not num:
        log(f"dispatch FAIL {tid}: 建 issue 失败 {str(issue)[:200]}")
        return False
    comment = cb.api(org, "POST", f"/{slug}/-/issues/{num}/comments",
                     {"body": cb.COMMENT_TMPL.format(
                         upstream=task.get("repo", ""),
                         base_commit=task.get("base_commit", ""),
                         task_id=tid), "work_mode": True})

    def mut(st):
        st[tid] = {"issue": num, "comment_id": comment.get("id"), "sn": None,
                   "build_status": "dispatched", "patch": None, "collected": False,
                   "tier": tier, "dispatched_at": time.time()}
    update_state(org, mut)
    log(f"dispatch {org} {tid}: issue #{num} comment {comment.get('id')} (tier {tier})")
    return True


def image_present(iid):
    img = "swebench/sweb.eval.x86_64." + iid.replace("__", "_1776_").lower()
    return img if sh(["docker", "image", "inspect", img], timeout=30).returncode == 0 else None


def pull_image(iid):
    """盘 <88% 时用 fast-pull 按需补拉（单并发）。成功返回镜像名（无 tag）。"""
    img = "swebench/sweb.eval.x86_64." + iid.replace("__", "_1776_").lower() + ":latest"
    df = sh(["df", "-P", "/", "--output=pcent"], timeout=30)
    pct = 100
    # 只取数据行（第 2 行起）；zh locale 表头是"已用%"，旧实现对表头 int() 直接炸
    # （pylint-4604/sympy-13091 等四题 2026-10-20 实证）
    lines = [l.strip() for l in df.stdout.splitlines() if l.strip()]
    if len(lines) > 1:
        try:
            pct = int(lines[-1].rstrip("%"))
        except ValueError:
            pass
    if pct >= 88:
        log(f"pull skip {iid}: 盘 {pct}% ≥88%，不自动拉镜像")
        return None
    with pull_lock:
        log(f"pull start {img}（fast-pull 单并发，盘 {pct}%）")
        try:
            tar = f"/tmp/fastpull-{iid.replace('/', '_')}.tar"
            r = sh([sys.executable, FAST_PULL, img, tar, "--jobs", "12"], timeout=3600)
            if r.returncode != 0:
                log(f"pull FAIL {img}: rc={r.returncode} {r.stderr[-200:]}")
                return None
            r2 = sh(["docker", "load", "-i", tar], timeout=900)
            if os.path.exists(tar):
                os.remove(tar)
            if r2.returncode != 0:
                log(f"pull load FAIL {img}: {r2.stderr[-200:]}")
                return None
            log(f"pull ok {img}")
            return img[:-7]
        except Exception as e:
            log(f"pull ERR {img}: {e}")
            return None


def judge_worker(wid, tier_of):
    while not stop_flag.is_set():
        if not judge_q:
            time.sleep(2)
            continue
        org, tid = judge_q.pop(0)
        if stop_flag.is_set():
            break
        snap = {}

        def snap_mut(st):
            v = st.get(tid)
            if not v or v.get("judged") or v.get("judge_blocked"):
                return False
            snap.update(patch=v.get("patch"), tier=v.get("tier") or tier_of.get(tid, "?"),
                        wall=v.get("agent_wall_ms"))
            return True
        if not update_state(org, snap_mut):
            continue
        tier = snap["tier"]
        judge_running.add(tid)
        try:
            patch = snap.get("patch")
            if not patch or not os.path.exists(patch):
                log(f"judge {tid}: state 无补丁文件 → no_patch")
                write_result_line(tid, tier, False, "no_patch", "completed",
                                  snap.get("wall"), "state 记了 collected 但补丁文件丢失")
                update_state(org, lambda st: st[tid].__setitem__("judged", True))
                continue
            img = image_present(tid) or pull_image(tid)
            if not img:
                log(f"judge {tid}: 镜像缺失且补拉失败 → blocked_no_image 留人工（不占槽位）")
                update_state(org, lambda st: st[tid].__setitem__("judge_blocked", "no_image"))
                continue  # 不算终态：镜像到位后人工清 blocked 标记即可重判
            task_json = os.path.join(TASKS_DIR, tid + ".json")
            outdir = f"/tmp/bench-fix1-{tier}-deepseek-cb/judge-{tid}"
            t0 = time.time()
            log(f"judge[{wid}] start {tid} (tier {tier}) img={img.split('/')[-1]}")
            r = sh(["bash", JUDGE_SH, task_json, patch, outdir], timeout=1500)
            jp = os.path.join(outdir, "judge.json")
            judge = None
            if os.path.exists(jp):
                try:
                    judge = json.load(open(jp))
                except json.JSONDecodeError:
                    judge = None
            if r.returncode == 2:
                tail = ""
                ap = os.path.join(outdir, "apply.log")
                if os.path.exists(ap):
                    tail = open(ap, errors="replace").read()[-300:].replace("\n", " | ")
                write_result_line(tid, tier, False, "apply_failed", "completed",
                                  snap.get("wall"),
                                  f"cb-judge rc=2（补丁应用失败）apply.log 尾部: {tail}")
            elif r.returncode == 0 and judge is not None:
                note = (f"judge: {json.dumps(judge, ensure_ascii=False)}; "
                        f"model=deepseek-v4.1-flash milli_credit=0; "
                        f"patch via results/{tid} 分支(cb-run.py 常驻守护), "
                        f"本地 sweb.eval+GNU patch fuzz 应用+官方 eval_script; "
                        f"audit=批量模式未抓取(NPC 日志页 API 400, 留人工), wall_ms 来自 build log")
                write_result_line(tid, tier, bool(judge.get("resolved")), "ok",
                                  "completed", snap.get("wall"), note)
            else:
                # 判分链基础设施错误（swev-judge 抛错/judge.json 空，rc 经 pipefail 透传）：
                # 不落结果行不计判——抛给重试账（3 次后 judge_blocked 留人工）
                raise RuntimeError(
                    f"cb-judge rc={r.returncode} judge.json={'缺失' if judge is None else '空'}"
                    f"（判分链错误，非补丁问题）")
            secs = round(time.time() - t0)

            def done_mut(st, secs=secs):
                st[tid]["judged"] = True
                st[tid]["judge_secs"] = secs
            update_state(org, done_mut)
            log(f"judge[{wid}] done {tid} ({secs}s)")
        except Exception as e:
            log(f"judge {tid} EXC: {e}\n{traceback.format_exc()[-400:]}")

            def fail_mut(st):
                st[tid]["judge_fails"] = st[tid].get("judge_fails", 0) + 1
                if st[tid]["judge_fails"] >= 3:
                    st[tid]["judge_blocked"] = "judge_error"
                    log(f"judge {tid}: 连续 {st[tid]['judge_fails']} 次判分链失败 "
                        f"→ judge_blocked=judge_error 留人工（不占槽位）")
            update_state(org, fail_mut)
        finally:
            # 出队解封：允许 watch 下轮对 collected 重判重入（旧实现崩后 tid 永卡
            # judge_queued，同进程内再不重试——8 道 xarray 即此账差来源）
            judge_queued.discard(tid)
            judge_running.discard(tid)


quota_snapshot_paused = {}


def run_loop(args):
    # 单实例守卫：pidfile 活进程即拒启（双实例会双重派发）
    pidfile = "/tmp/cb-run.pid"
    if os.path.exists(pidfile):
        old = open(pidfile).read().strip()
        if old and os.path.exists(f"/proc/{old}"):
            log(f"cb-run already running pid={old}，拒绝双实例")
            return
    with open(pidfile, "w") as f:
        f.write(str(os.getpid()))
    tier_of = load_namelist()
    full_tasks = load_full_tasks()
    preseed_judged(tier_of)
    workers = [threading.Thread(target=judge_worker, daemon=True, args=(i, tier_of))
               for i in range(2)]
    for w in workers:
        w.start()
    log(f"cb-run start pid={os.getpid()} target={args.target}/org poll={args.poll}s "
        f"timeout={args.timeout_min}min quota_pause={args.quota_pause}")
    while not stop_flag.is_set():
        try:
            t0 = time.time()
            # 1) quota 护栏
            for org in ORGS:
                free, used, freeze = quota_snapshot(org)
                over = free > 0 and (used + freeze) >= args.quota_pause * free
                if over and not quota_snapshot_paused.get(org):
                    log(f"QUOTA PAUSE {org}: 已用 {used/3600:.1f}+冻结 {freeze/3600:.1f} 核时 "
                        f"≥ {args.quota_pause:.0%} × 免费 {free/3600:.0f} 核时 → 暂停派发"
                        f"（watch/judge 继续）")
                elif not over and quota_snapshot_paused.get(org):
                    log(f"QUOTA RESUME {org}: 回落 {used/3600:.1f}+{freeze/3600:.1f}/"
                        f"{free/3600:.0f} 核时")
                quota_snapshot_paused[org] = over
            # 2) 轮询 + 收补丁
            for org in ORGS:
                watch_phase(org, args, tier_of)
            # 3) 派发（quota 暂停的 org 跳过）
            for org in ORGS:
                dispatch_phase(org, args, tier_of, full_tasks)
            # 4) 摘要一行
            infl = {o: inflight_count(cb.load_state(o, REPO)) for o in ORGS}
            judged = sum(1 for o in ORGS for v in cb.load_state(o, REPO).values()
                         if v.get("judged"))
            log(f"tick inflight={infl[ORGS[0]]}+{infl[ORGS[1]]} judged={judged} "
                f"q={len(judge_q)} running={len(judge_running)} "
                f"elapsed={time.time()-t0:.0f}s")
            if args.once:
                break
            stop_flag.wait(args.poll)
        except Exception as e:
            log(f"loop EXC: {e}\n{traceback.format_exc()[-500:]}")
            stop_flag.wait(args.poll)
    if os.path.exists(pidfile):
        try:
            if open(pidfile).read().strip() == str(os.getpid()):
                os.remove(pidfile)
        except OSError:
            pass
    log("cb-run stop")


def summary():
    tier_of = load_namelist()
    all_t = list(tier_of)
    in_state, judged_n, infl, timeout, failed, blocked, tojudge = set(), 0, 0, 0, 0, 0, 0
    per_tier = {"d1": [0, 0], "d2": [0, 0], "d3": [0, 0]}
    gates = {}
    for o in ORGS:
        st = cb.load_state(o, REPO)
        infl += inflight_count(st)
        for tid, v in st.items():
            in_state.add(tid)
            if v.get("judged"):
                judged_n += 1
            elif v.get("judge_blocked"):
                blocked += 1
            elif v.get("build_status") == "timeout":
                timeout += 1
            elif v.get("build_status") in ("failed", "error"):
                failed += 1
            elif v.get("collected"):
                tojudge += 1  # 补丁已收待判/判分排队（旧 summary 不显示此桶=账差来源）
    for tier in per_tier:
        p = results_path(tier)
        if not os.path.exists(p):
            continue
        for line in open(p, encoding="utf-8"):
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("profile") == "deepseek-cb":
                per_tier[tier][0] += 1
                per_tier[tier][1] += 1 if r.get("reward") else 0
                gates[r.get("gate")] = gates.get(r.get("gate"), 0) + 1
    pend = [t for t in all_t if t not in in_state]
    ok = per_tier["d1"][1] + per_tier["d2"][1] + per_tier["d3"][1]
    tot = per_tier["d1"][0] + per_tier["d2"][0] + per_tier["d3"][0]
    print(f"deepseek-cb 120题: 落行={tot} 通过={ok} "
          f"(D1 {per_tier['d1'][1]}/{per_tier['d1'][0]} D2 {per_tier['d2'][1]}/{per_tier['d2'][0]} "
          f"D3 {per_tier['d3'][1]}/{per_tier['d3'][0]}) gate={gates}")
    print(f"在飞={infl} (zhuzhu {inflight_count(cb.load_state(ORGS[0], REPO))} / "
          f"cloudbird {inflight_count(cb.load_state(ORGS[1], REPO))}) 待派={len(pend)} "
          f"已判={judged_n} 待判={tojudge} timeout={timeout} failed={failed} "
          f"blocked_no_image={blocked}")
    acct = judged_n + infl + tojudge + timeout + failed + blocked + len(pend)
    flag = "OK" if acct == len(all_t) else "!! 不自洽"
    print(f"账目: 已判{judged_n}+在飞{infl}+待判{tojudge}+timeout{timeout}"
          f"+failed{failed}+blocked{blocked}+待派{len(pend)} = {acct}/{len(all_t)} {flag}")
    for o in ORGS:
        free, used, freeze = quota_snapshot(o)
        print(f"quota {o}: dev 已用={used/3600:.2f} 冻结={freeze/3600:.2f} / 免费={free/3600:.0f} 核时")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run")
    p.add_argument("--target", type=int, default=5, help="每 org in-flight 上限")
    p.add_argument("--poll", type=int, default=30)
    p.add_argument("--timeout-min", type=int, default=60)
    p.add_argument("--quota-pause", type=float, default=0.8)
    p.add_argument("--once", action="store_true")
    sub.add_parser("summary")
    sub.add_parser("quota")
    a = ap.parse_args()
    if a.cmd == "run":
        run_loop(a)
    elif a.cmd == "summary":
        summary()
    elif a.cmd == "quota":
        for o in ORGS:
            free, used, freeze = quota_snapshot(o)
            print(f"{o}: dev 已用={used/3600:.2f} 冻结={freeze/3600:.2f} / 免费={free/3600:.0f} 核时")


if __name__ == "__main__":
    main()
