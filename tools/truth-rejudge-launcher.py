#!/usr/bin/env python3
"""最终真相 · P1 清洁重判队列守护（方法论见 设计/最终真相方法论.md）。

- 队列源：/tmp/bench-fix1-d*/ 与 /tmp/bench-fix2-{ab,rerun}-*/（排除 *test* 目录）。
- 每个 job 建 staging 目录（/tmp/truth-stage/<job>/runs/ → 符号链接到原始 run 目录），
  只链接 有 agent.diff(>0) 且尚无 rejudge-clean/judge.json 的 run —— 幂等且不重复今天已判的 78 行。
- 判分产物经符号链接写回原始 run 目录（rejudge-clean/ 子目录），证据链原地保全。
- 并发上限 8 个 poc 进程；启动新进程前 MemAvailable < 2500MB 则等待（内存安全，D-16/D-26）。
- P0 清单：/tmp/truth-manifest.jsonl（run_dir/task/profile/agent.diff sha256/字节数/staging 路径）。
- 优先级：step5 > m31f > m3 > glm-cp+fix2 > 其余（kimi/glm-max/30b/变体）。
- 日志：/tmp/truth-launcher.log；pid：/tmp/truth-launcher.pid。
"""
import glob, hashlib, json, os, shutil, subprocess, sys, time

POC = "/home/pan-ding/workspace/agent黑灯工厂/af/target/debug/af-bench-poc"
DATA_ROOT = "/tmp/swev-s1"
STAGE_ROOT = "/tmp/truth-stage"
OUT_ROOT = "/tmp/truth-rejudge"
MANIFEST = "/tmp/truth-manifest.jsonl"
LOG = "/tmp/truth-launcher.log"
MAX_PAR = 6
MIN_AVAIL_MB = 3000

def log(msg):
    with open(LOG, "a") as f:
        f.write(f"[{time.strftime('%F %T')}] {msg}\n")

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def mem_avail_mb():
    with open("/proc/meminfo") as f:
        for line in f:
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 1024
    return 0

def priority(job_dir):
    b = os.path.basename(job_dir)
    for i, key in enumerate(["step5", "m31f", "-m3", "glm-cp", "fix2-ab", "fix2-rerun"]):
        if key in b:
            return i
    return 9

def build_stage(job_dir):
    """链接 eligible run 目录到 staging，返回 (job, staged_count)。"""
    job = os.path.basename(job_dir)
    stage = os.path.join(STAGE_ROOT, job, "runs")
    os.makedirs(stage, exist_ok=True)
    n = 0
    for run in sorted(glob.glob(os.path.join(job_dir, "runs", "*"))):
        if not os.path.isdir(run):
            continue
        diff = os.path.join(run, "agent.diff")
        if not (os.path.isfile(diff) and os.path.getsize(diff) > 0):
            continue
        if os.path.exists(os.path.join(run, "rejudge-clean", "judge.json")):
            continue  # 已清洁判过（含今日 78 行），不重复
        link = os.path.join(stage, os.path.basename(run))
        if os.path.islink(link) or os.path.exists(link):
            os.remove(link)
        os.symlink(run, link)
        with open(MANIFEST, "a") as f:
            f.write(json.dumps({
                "job": job, "run": os.path.basename(run), "orig": run,
                "agent_diff_sha256": sha256(diff), "agent_diff_bytes": os.path.getsize(diff),
            }, ensure_ascii=False) + "\n")
        n += 1
    return job, n

def main():
    if os.path.exists("/tmp/truth-launcher.pid"):
        try:
            old = int(open("/tmp/truth-launcher.pid").read())
            os.kill(old, 0)
            print("launcher 已在运行", old); return
        except Exception:
            pass
    open("/tmp/truth-launcher.pid", "w").write(str(os.getpid()))
    log(f"launcher 启动 pid={os.getpid()} POC={POC} poc_sha={sha256(POC)}")

    jobs = sorted(
        [d for d in glob.glob("/tmp/bench-fix1-d*") + glob.glob("/tmp/bench-fix2-ab-*") + glob.glob("/tmp/bench-fix2-rerun-*")
         if os.path.isdir(d) and "test" not in os.path.basename(d)],
        key=priority,
    )
    queue = []
    for d in jobs:
        job, n = build_stage(d)
        if n:
            queue.append((job, n))
    log("队列: " + ", ".join(f"{j}:{n}" for j, n in queue))

    running = {}  # job -> (proc, outdir)
    while queue or running:
        for job in [j for j, p in running.items() if p.poll() is not None]:
            rc = running.pop(job).returncode
            log(f"job 完成 {job} rc={rc}")
        while queue and len(running) < MAX_PAR:
            if mem_avail_mb() < MIN_AVAIL_MB:
                log(f"内存闸等待 avail={mem_avail_mb()}MB"); break
            job, n = queue.pop(0)
            out = os.path.join(OUT_ROOT, job)
            os.makedirs(out, exist_ok=True)
            cmd = [POC, "--suite", "swev-rejudge", "--data-root", DATA_ROOT,
                   "--from", os.path.join(STAGE_ROOT, job), "--out", out]
            with open(os.path.join(out, "launcher.log"), "w") as lf:
                running[job] = subprocess.Popen(cmd, stdout=lf, stderr=subprocess.STDOUT,
                                                stdin=subprocess.DEVNULL, cwd=os.path.dirname(POC))
            log(f"job 启动 {job} rows={n} pid={running[job].pid}")
        time.sleep(20)
    log("全部 job 完成")

if __name__ == "__main__":
    main()
