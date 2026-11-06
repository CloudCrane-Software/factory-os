#!/usr/bin/env python3
"""image-pool-retire — 判分镜像池退役（运营者令：判题已毕、可随时重拉，没必要占空间）

策略：保队列所需、其余即删；队列排空（无 swev 在途+无 swev 待办）后清尾全删并落
SWEV-POOL-RETIRED 标记。镜像↔任务映射：swebench/sweb.eval.x86_64.<repo>_1776_<inst>
对应任务 <repo>__<inst>。回滚：重拉即可（fast-pull.py 加速器路线，代价=带宽+时间）。"""
import json
import glob
import re
import subprocess
import time

PENDING = "/data/bench/queue/pending"
MARKER = "/data/bench/queue/SWEV-POOL-RETIRED"


def sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout


def task_to_image(task):
    # astropy__astropy-12907 → swebench/sweb.eval.x86_64.astropy_1776_astropy-12907
    repo, inst = task.split("__", 1)
    return f"swebench/sweb.eval.x86_64.{repo}_1776_{inst}"


def needed_tasks():
    need = set()
    for f in glob.glob(PENDING + "/*.json"):
        try:
            e = json.load(open(f))
            if e.get("unit") == "swev" and e.get("task"):
                need.add(e["task"])
        except Exception:
            pass
    for line in sh("pgrep -af 'af-order submit' | grep -- '--unit swev'").splitlines():
        m = re.search(r"--task (\S+)", line)
        if m:
            need.add(m.group(1))
    return need


def all_sweb_images():
    return [r for r in sh("docker images --format '{{.Repository}}'").splitlines()
            if r.startswith("swebench/sweb.eval.")]


def sweep(final=False):
    imgs = all_sweb_images()
    need = needed_tasks()
    keep = {task_to_image(t) for t in need}
    victims = imgs if final else [i for i in imgs if i not in keep]
    if victims:
        r = sh("docker rmi " + " ".join(victims) + " 2>&1 | tail -1")
        print(f"[{time.strftime('%H:%M:%S')}] rmi {len(victims)} 张：{r[:80]}", flush=True)
    return len(imgs) - len(victims), len(need)


def main():
    for rnd in range(720):  # 上限 30 小时
        kept, need = sweep()
        print(f"[{time.strftime('%H:%M:%S')}] 轮 {rnd}：保留 {kept} 张（队列需 {need} 题）", flush=True)
        if need == 0 and kept <= 104 and kept > 0:
            sweep(final=True)
            open(MARKER, "w").write(time.strftime("%Y-%m-%d %H:%M:%S") + " 队列排空，镜像池清尾退役\n")
            print("队列已排空，镜像池全删退役完成", flush=True)
            return
        if need == 0 and kept == 0:
            open(MARKER, "w").write(time.strftime("%Y-%m-%d %H:%M:%S") + " 镜像池已空\n")
            print("镜像池已空", flush=True)
            return
        time.sleep(300)
    print("30 小时上限到，仍在值守（未清尾）", flush=True)


if __name__ == "__main__":
    main()
