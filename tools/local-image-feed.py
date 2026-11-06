#!/usr/bin/env python3
"""local-image-feed.py — 本机 sweb.eval 镜像补给循环（nohup 常驻）。

对照 计划/s1-swev-120.json 全量镜像名单与本机 docker images，缺的从
docker.cnb.cool 制品库（relay 生产现成件，两 org 交替找）fast-pull 拉 + load，
retag 成规范名。只动本机 docker——anolis 的补给仍归工厂调度器的 relay 节点。

闸：
  · 磁盘闸：每张拉完查本机 / 使用率，>85% 暂停等待（每 5 分钟复测），降到线下再续。
  · 空转闸：一轮没有任何新镜像就位（制品库还没有 relay 生产的现成件）则歇 10 分钟再试。
退出：名单内镜像全部就位时退出 0（使命完成）。

密钥纪律：CNB token 现取现用（openBao 管道），只进 fast-pull 子进程参数，不落日志。
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

WS = "/home/pan-ding/workspace/agent黑灯工厂"
SAMPLE = f"{WS}/计划/s1-swev-120.json"
FAST_PULL = f"{WS}/tools/fast-pull.py"
CACHE_DIR = os.path.expanduser("~/.cache/s1pull")
BAO_RT = os.path.expanduser("~/.local/share/openbao-escrow/.root-token")
BAO = "http://gov-host.invalid:8200"
DISK_PAUSE_PCT = 85
ROUND_REST_SEC = 600
DISK_RECHECK_SEC = 300
# 两 org 的 relay 制品仓（与 cnb-relay.py 的 ORGS 对应：org → openBao key 名）
ORG_KEYS = [
    ("zhuzhu-team", "CNB-2-all-privilege"),
    ("cloudbird-software", "CNB-1-all-privilege"),
]


def log(msg):
    print(f"[{time.strftime('%F %T')}] {msg}", flush=True)


def img_name(inst):
    repo = inst.split("__")[0]
    return f"swebench/sweb.eval.x86_64.{repo.replace('/', '_1776_')}_1776_{inst.split('__')[1]}:latest"


def tag_of(img):
    return img.rsplit(":", 1)[0].split("/")[-1].split("_1776_")[-1]


def local_images():
    out = subprocess.run(["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"],
                         capture_output=True, text=True, timeout=120).stdout
    return {l.strip() for l in out.splitlines() if l.strip()}


def disk_pct():
    st = os.statvfs("/")
    total = st.f_blocks * st.f_frsize
    free = st.f_bavail * st.f_frsize
    return round(100 * (total - free) / total, 1)


CNB_TOKEN_FILE = os.path.expanduser("~/.config/cnb/relay-tokens.json")


def bao_token(key_name):
    # 优先本地 0600 令牌文件（2026-10-20 迁移：工具不再依赖 escrow root 明文）
    try:
        with open(CNB_TOKEN_FILE) as f:
            t = json.load(f).get(key_name)
        if t:
            return t
    except FileNotFoundError:
        pass
    with open(BAO_RT) as f:
        rt = f.read().strip()
    req = urllib.request.Request(
        f"{BAO}/v1/kv/data/company/Git-Platform/CNB/{key_name}",
        headers={"X-Vault-Token": rt},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)["data"]["data"]["Token"]


def registry_has(token, ref):
    """制品库是否已有该 tag（HEAD manifest，basic→token 流，与 cnb-relay 同法）。"""
    repo, tag = ref.split(":")
    import base64
    basic = base64.b64encode(f"cnb:{token}".encode()).decode()
    treq = urllib.request.Request(
        f"https://docker.cnb.cool/service/token?service=cnb-registry&scope=repository:{repo}:pull",
        headers={"Authorization": f"Basic {basic}"},
    )
    with urllib.request.urlopen(treq, timeout=20) as r:
        tok = json.load(r).get("token")
    if not tok:
        return False
    req = urllib.request.Request(
        f"https://docker.cnb.cool/v2/{repo}/manifests/{tag}",
        method="HEAD",
        headers={"Authorization": f"Bearer {tok}",
                 "Accept": "application/vnd.oci.image.index.v1+json,"
                           "application/vnd.docker.distribution.manifest.list.v2+json,"
                           "application/vnd.docker.distribution.manifest.v2+json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status == 200
    except (urllib.error.HTTPError, urllib.error.URLError):
        return False


def wait_disk():
    """磁盘闸：>85% 就等，降到线下才放行下一张。"""
    while True:
        pct = disk_pct()
        if pct <= DISK_PAUSE_PCT:
            return pct
        log(f"磁盘闸：本机 / 使用率 {pct}% > {DISK_PAUSE_PCT}%，暂停补给（{DISK_RECHECK_SEC}s 后复测）")
        time.sleep(DISK_RECHECK_SEC)


def pull_and_load(img, org, token):
    """fast-pull 拉现成 relay 件 → docker load → retag 规范名 → 清 relay tag 与 tar。"""
    tag = tag_of(img)
    ref = f"{org}/swev-relay:{tag}"
    tar = f"{CACHE_DIR}/{tag}.tar"
    os.makedirs(CACHE_DIR, exist_ok=True)
    t0 = time.time()
    try:
        pull = subprocess.run(
            ["python3", FAST_PULL, ref, tar,
             "--registry", "docker.cnb.cool", "--token", token,
             "--jobs", "12", "--split", "8"],
            capture_output=True, text=True, timeout=3600,
            env={**os.environ, "TMPDIR": CACHE_DIR},
        )
        if pull.returncode != 0:
            log(f"[fail] {img} 拉取失败: {pull.stderr[-160:]}")
            return False
        with open(tar, "rb") as f:
            load = subprocess.run(["docker", "load"], stdin=f,
                                  capture_output=True, text=True, timeout=1800)
        if load.returncode != 0 or "Loaded image" not in (load.stdout + load.stderr):
            log(f"[fail] {img} load 失败: {(load.stdout + load.stderr)[-160:]}")
            return False
        loaded_name = ref.replace("/", "_")
        subprocess.run(["docker", "tag", loaded_name, img], capture_output=True)
        subprocess.run(["docker", "rmi", loaded_name], capture_output=True)
        try:
            os.remove(tar)
        except OSError:
            pass
        log(f"[ok] {img} ← {ref}（{int(time.time()-t0)}s）")
        return True
    finally:
        # 失败也不留残件：>30min 陈旧同名 tar 必然无人使用；新鲜残件交给 fast-pull 启动清扫
        try:
            if os.path.exists(tar) and time.time() - os.path.getmtime(tar) > 1800:
                os.remove(tar)
        except OSError:
            pass


def main():
    want = [img_name(t["instance_id"]) for t in json.load(open(SAMPLE))]
    log(f"补给循环启动（pid {os.getpid()}）：名单 {len(want)} 张，本机 / 使用率 {disk_pct()}%")
    while True:
        have = local_images()
        missing = [i for i in want if i not in have]
        log(f"盘点：已就位 {len(want) - len(missing)}/{len(want)}，缺 {len(missing)}")
        if not missing:
            log("全部就位，补给循环退出")
            return 0
        token_cache = {}
        fed = 0
        for img in missing:
            got = False
            for org, key in ORG_KEYS:
                if key not in token_cache:
                    token_cache[key] = bao_token(key)
                if not registry_has(token_cache[key], f"{org}/swev-relay:{tag_of(img)}"):
                    continue
                wait_disk()
                if pull_and_load(img, org, token_cache[key]):
                    fed += 1
                    got = True
                    break
            if not got:
                log(f"[缺货] {img} 两 org 制品库均无现成件（等 relay 生产）")
        if fed == 0:
            log(f"本轮零补给（制品库待产），歇 {ROUND_REST_SEC}s")
            time.sleep(ROUND_REST_SEC)


if __name__ == "__main__":
    sys.exit(main())
