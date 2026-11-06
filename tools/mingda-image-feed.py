#!/usr/bin/env python3
"""mingda-image-feed.py — mingda-website 执行面的镜像补给与任务接线。

职责（常驻循环）：
  1. 选题：m31f 与 m3 两档案都未判分（跨主机 done 并集）的题，D1>D2>D3 优先，
     且本机 docker 已有该镜像、mingda 尚无。
  2. 推送：docker save | gzip | ssh mingda-bench docker load（实测 ~20MB/s）。
     每张前查 mingda / 使用率 >85% 即暂停等待；mingda 已有 ≥16 张即止（磁盘预算）。
  3. 接线：镜像确认在 mingda 后，把题 append 进 /tmp/factory-graph.json 中
     mingda 臂节点（arm-d{1,2,3}-mavis-{m31f,m3}-mingda）的 params.tasks；
     该档 m31f 臂不存在且已有就绪题时创建之（m3 臂由主代理预置）。
     图为原子写（tmp+rename），调度器 5s 热加载。
纪律：只派镜像已确认到位的题（防 setup_failed 被算作已结论）；密钥零明文。
"""
import glob
import json
import os
import subprocess
import sys
import time

WS = "/home/pan-ding/workspace/agent黑灯工厂"
SAMPLE = f"{WS}/计划/s1-swev-120.json"
GRAPH = "/tmp/factory-graph.json"
HOST = "mingda-bench"
MAX_IMAGES = 16
DF_LIMIT = 85

def sh(cmd, timeout=1800):
    # stdin=DEVNULL：防 ssh/子进程吞掉父进程 stdin 挂起（实测教训）
    return subprocess.run(cmd, shell=True, capture_output=True, text=True,
                          timeout=timeout, stdin=subprocess.DEVNULL)

def done_union(prof):
    s = set()
    for f in glob.glob(f"/tmp/bench-fix1-d*-{prof}*/results.jsonl"):
        for l in open(f, encoding="utf-8"):
            try:
                r = json.loads(l)
            except json.JSONDecodeError:
                continue
            if r.get("status") and r["status"] != "run_failed":
                s.add(r.get("task_id"))
    return s

def docker_names(where):
    out = sh(f"docker images --format '{{{{.Repository}}}}'" if where == "local"
             else f"ssh {HOST} 'docker images --format \"{{{{.Repository}}}}\"'").stdout
    return {l.strip().split("/")[-1] for l in out.splitlines() if "sweb.eval" in l}

def img_short(inst):
    repo = inst.split("__")[0]
    return f"sweb.eval.x86_64.{repo.replace('/', '_1776_')}_1776_{inst.split('__')[1]}"

def img_full(inst):
    return f"swebench/{img_short(inst)}:latest"

def mingda_df_pct():
    out = sh(f"ssh {HOST} 'df /'", timeout=60).stdout
    for l in out.splitlines():
        for fld in l.split():
            if fld.endswith("%"):
                try:
                    return int(fld[:-1])
                except ValueError:
                    pass
    return 100

def update_graph(task, tier):
    for _ in range(5):  # 与调度器读竞争，重试
        try:
            g = json.load(open(GRAPH))
        except Exception:
            time.sleep(1); continue
        m31f_id = f"arm-{tier.lower()}-mavis-m31f-mingda"
        m3_id = f"arm-{tier.lower()}-mavis-m3-mingda"
        by = {n["id"]: n for n in g["nodes"]}
        for nid, prof in ((m31f_id, "mavis-m31f"), (m3_id, "mavis-m3")):
            if nid not in by:
                g["nodes"].append({"id": nid, "kind": "bench-arm",
                    "params": {"profile": prof, "tasks": [task], "tier": tier,
                               "host": HOST, "out": f"/tmp/bench-fix1-{tier.lower()}-{'m31f' if 'm31f' in nid else 'm3'}-mingda"},
                    "deps": []})
            elif task not in by[nid]["params"]["tasks"]:
                by[nid]["params"]["tasks"].append(task)
        g.setdefault("limits", {}).setdefault("host", {})[HOST] = 2
        tmp = GRAPH + ".tmp"
        with open(tmp, "w") as f:
            json.dump(g, f, ensure_ascii=False, indent=1)
        os.replace(tmp, GRAPH)
        return True
    return False

def main():
    print("main入口", flush=True)
    sample = json.load(open(SAMPLE))
    tiers = {"D1": [], "D2": [], "D3": []}
    for t in sample:
        tiers[t["tier"]].append(t["instance_id"])
    while True:
        m31f, m3 = done_union("m31f"), done_union("m3")
        local, remote = docker_names("local"), docker_names(HOST)
        if len(remote & {n for n in local}) >= MAX_IMAGES:
            print("mingda 镜像预算已满，退出", flush=True); return
        pick = None
        for tier in ("D1", "D2", "D3"):
            for inst in tiers[tier]:
                if inst in m31f or inst in m3:
                    continue
                short = img_short(inst)
                if short in local and short not in remote:
                    pick = (inst, tier); break
            if pick: break
        if not pick:
            print("无可补给题（本机镜像未到或全部已判），10 分钟后重试", flush=True)
            time.sleep(600); continue
        inst, tier = pick
        pct = mingda_df_pct()
        if pct > DF_LIMIT:
            print(f"mingda 磁盘 {pct}%，暂停补给", flush=True); time.sleep(600); continue
        full = img_full(inst)
        print(f"推送 {inst} -> {HOST} ...", flush=True)
        r = sh(f"docker save {full} | gzip | ssh {HOST} 'gzip -d | docker load'", timeout=1800)
        ok = img_short(inst) in docker_names(HOST)
        print(f"  {'OK' if ok else 'FAIL'}: {r.stdout.strip()[-80:]}{r.stderr.strip()[-80:]}", flush=True)
        if ok and update_graph(inst, tier):
            print(f"  已接入图: {tier} {inst}", flush=True)
        elif not ok:
            time.sleep(60)

if __name__ == "__main__":
    main()
