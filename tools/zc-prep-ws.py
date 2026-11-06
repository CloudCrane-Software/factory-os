#!/usr/bin/env python3
"""zc-prep-ws.py — zcode 官方 harness 对照线（step-5）工作区预置。

对 S1 全部 120 题逐题建 /tmp/zc-ws/<instance_id>/：
  repo/       git 浅克隆检出 base_commit（agent 只需基线源码写补丁；判分在 eval 镜像容器做，
              不用这个 clone——故 depth=1 单 commit 足够）
  problem.md  题目原文（自 /tmp/swev-s1/<iid>.json 的 problem_statement 原样落盘；
              刻意不带 test_patch / fail_to_pass / hints_text，防 agent 作弊）
  meta.json   instance_id / repo / base_commit / tier / image（供 agent 与判分脚本查）
  .ready      就位标记（幂等断点续跑：有 .ready 且 HEAD==base_commit 即跳过）

磁盘裁决（2026-10-21 df 实测）：/tmp 是 tmpfs（7.5G，余 3.2G），120 仓放不下且吃内存——
真实数据落 /home/pan-ding/zc-ws（/ 分区余 112G），/tmp/zc-ws 做符号链接维持路径约定。

用法:
  zc-prep-ws.py --tier D1            # 先备 D1 60 题
  zc-prep-ws.py --tier all --workers 6
  zc-prep-ws.py --status             # 只看进度
"""
import argparse
import concurrent.futures
import json
import os
import subprocess
import sys
import time

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAMELIST = os.path.join(WS, "计划", "s1-swev-120.json")
TASKS_DIR = "/tmp/swev-s1"
REAL_ROOT = "/home/pan-ding/zc-ws"
LINK_ROOT = "/tmp/zc-ws"
MIN_FREE_GB = 8  # 磁盘闸：真实根可用空间低于此值拒绝开工


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def ensure_roots():
    os.makedirs(REAL_ROOT, exist_ok=True)
    if os.path.islink(LINK_ROOT):
        dst = os.readlink(LINK_ROOT)
        if dst != REAL_ROOT:
            log(f"符号链接 {LINK_ROOT} → {dst} 与预期 {REAL_ROOT} 不符，拒绝动它")
            sys.exit(2)
    elif os.path.exists(LINK_ROOT):
        log(f"{LINK_ROOT} 已存在且不是符号链接——请人工确认后移走再跑")
        sys.exit(2)
    else:
        os.symlink(REAL_ROOT, LINK_ROOT)
        log(f"建符号链接 {LINK_ROOT} → {REAL_ROOT}")


def load_tasks(tier):
    tasks = json.load(open(NAMELIST, encoding="utf-8"))
    if tier != "all":
        tasks = [t for t in tasks if t["tier"] == tier]
    return tasks


def disk_guard():
    import shutil
    free = shutil.disk_usage(REAL_ROOT).free
    gb = free / 1024**3
    if gb < MIN_FREE_GB:
        log(f"磁盘闸触发：{REAL_ROOT} 仅余 {gb:.1f}G < {MIN_FREE_GB}G，拒绝开工")
        sys.exit(3)
    return gb


def task_ready(work, base_commit):
    ready = os.path.join(work, ".ready")
    if not os.path.exists(ready):
        return False
    repo = os.path.join(work, "repo", ".git")
    if not os.path.isdir(repo):
        return False
    try:
        head = subprocess.run(
            ["git", "-C", os.path.join(work, "repo"), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=30).stdout.strip()
        return head == base_commit
    except Exception:
        return False


def build_one(t):
    """单题预置；返回 (iid, ok, msg)。"""
    iid, base = t["instance_id"], None
    tj_path = os.path.join(TASKS_DIR, iid + ".json")
    tj = json.load(open(tj_path, encoding="utf-8"))
    base = tj["base_commit"]
    work = os.path.join(LINK_ROOT, iid)
    if task_ready(work, base):
        return (iid, True, "ready(缓存命中)")
    os.makedirs(work, exist_ok=True)
    # 1) problem.md / meta.json（每次重写，保证与 swev-s1 源一致）
    with open(os.path.join(work, "problem.md"), "w", encoding="utf-8") as f:
        f.write(tj["problem_statement"])
    meta = {k: tj.get(k) for k in ("instance_id", "repo", "base_commit", "image")}
    meta["tier"] = t["tier"]
    with open(os.path.join(work, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    # 2) 浅克隆到 base_commit（GitHub 支持 fetch-by-sha；三振重试）
    repo_dir = os.path.join(work, "repo")
    last_err = ""
    for attempt in range(1, 4):
        if os.path.isdir(repo_dir):
            subprocess.run(["rm", "-rf", repo_dir], check=True)
        try:
            subprocess.run(["git", "init", "-q", repo_dir], check=True, timeout=60)
            subprocess.run(["git", "-C", repo_dir, "remote", "add", "origin",
                            f"https://github.com/{tj['repo']}.git"], check=True, timeout=30)
            subprocess.run(["git", "-C", repo_dir, "-c", "advice.detachedHead=false",
                            "fetch", "-q", "--depth", "1", "origin", base],
                           check=True, timeout=600, capture_output=True, text=True)
            subprocess.run(["git", "-C", repo_dir, "checkout", "-q", "-f", "FETCH_HEAD"],
                           check=True, timeout=120)
            head = subprocess.run(["git", "-C", repo_dir, "rev-parse", "HEAD"],
                                  capture_output=True, text=True, timeout=30).stdout.strip()
            if head != base:
                raise RuntimeError(f"HEAD {head} != base {base}")
            with open(os.path.join(work, ".ready"), "w") as f:
                f.write(base + "\n")
            return (iid, True, "cloned")
        except Exception as e:  # noqa: BLE001 — 三振后如实上报
            last_err = f"attempt{attempt}: {str(e)[:200]}"
            time.sleep(3 * attempt)
    return (iid, False, last_err)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", default="D1", choices=["D1", "D2", "D3", "all"])
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()

    tasks = load_tasks(args.tier)
    done = sum(1 for t in tasks
               if task_ready(os.path.join(LINK_ROOT, t["instance_id"]),
                             json.load(open(os.path.join(TASKS_DIR, t["instance_id"] + ".json"),
                                            encoding="utf-8"))["base_commit"]))
    if args.status:
        print(f"{args.tier}: {done}/{len(tasks)} 就位（根 {REAL_ROOT}）")
        return

    ensure_roots()
    gb = disk_guard()
    log(f"预置 {args.tier}：{len(tasks)} 题（已有 {done} 就位），workers={args.workers}，"
        f"磁盘余 {gb:.0f}G")
    ok = failed = 0
    fails = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(build_one, t): t for t in tasks}
        for i, fu in enumerate(concurrent.futures.as_completed(futs), 1):
            iid, good, msg = fu.result()
            if good:
                ok += 1
            else:
                failed += 1
                fails.append((iid, msg))
                log(f"FAIL {iid}: {msg}")
            if i % 10 == 0:
                log(f"进度 {i}/{len(tasks)}（成 {ok} 败 {failed}）")
    log(f"收工：{args.tier} 共 {len(tasks)}，成 {ok}，败 {failed}")
    if fails:
        print("失败清单（重跑本脚本即自动重试）：")
        for iid, msg in fails:
            print(f"  {iid}: {msg}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
