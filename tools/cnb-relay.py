#!/usr/bin/env python3
"""cnb-relay.py — 经 CNB.cool 构建沙箱中继拉取镜像到 anolis。

链路：CNB 沙箱（crane，docker.io 出网 ~8.5MB/s）copy → docker.cnb.cool 制品库
      → anolis docker pull（国内 Tencent Cloud）→ tag 成规范名。
为什么：本机 docker 守护进程挂在失活的 mihomo 代理上；hk-socks 总带宽 250KB/s；
      docker.1panel.live 加速器单连接 ~800KB/s 且实测聚合只有 0.6MB/s——都不够用。
CNB 沙箱凭证由平台每次构建自动注入（CNB_TOKEN/CNB_TOKEN_USER_NAME），本脚本只需
OpenAPI 的 Bearer 令牌（从 openBao 现取现用，只进管道不进转录）。

用法:
  cnb-relay.py once <repo:tag>             # 中继单张（幂等：anolis 已有则跳过）
  cnb-relay.py loop <file> [--jobs 3]      # 按文件循环，每行一个 repo:tag
  cnb-relay.py mkrepo <org> <name>         # 建中继制品仓

2026-10-20 泄漏根修：~/.cache/s1pull 的泄漏惯性（装载后不删 + 分片不清理）——
  ①成功删 tar 原已有，补上失败路径的 finally 清理（>30min 陈旧同名 tar 才删，防误删
  并发同镜像进程的活文件）；②fast-pull 的 fastpull-* 分片目录由其自身 finally + 本脚本
  启动清扫双保险；③本脚本每次启动顺带清扫缓存目录 mtime>60min 的陈旧件（幂等）。

2026-10-20 22:21 波根修（ssh 闪断 22 连败）：①传输前 anolis docker 预检，不可达立即
  失败不白拉；②所有 return False 路径改为 deliver_or_fail——镜像已在 anolis 精确名
  在场即按成功返回（到场就是成功）；③docker tag 收尾检查返回码，rmi 失败降级为警告。
"""
import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

CNB_API = "https://api.cnb.cool"
BAO = "http://gov-host.invalid:8200"
BAO_RT = os.path.expanduser("~/.local/share/openbao-escrow/.root-token")
CACHE_DIR = os.path.expanduser("~/.cache/s1pull")
STALE_MIN = 60       # 启动清扫年龄线（分钟）
FAIL_STALE_SEC = 1800  # 失败路径 finally 只清超过此年龄（秒）的同名 tar
# 两个 org 各自独立配额（160 核时/月免费），交替使用摊薄并发。
# Cloudbird-Software 必须写小写 cloudbird-software：docker reference 禁大写，
# 而 CNB 注册表/API 实测大小写不敏感（2026-10-20 probe sn=cnb-hos-1k5c5na5h 验证
# lowercase 路径 crane copy 与外部 manifest 拉取均通），小写别名即该 org。
ORGS = [
    ("zhuzhu-team", "CNB-2-all-privilege"),
    ("cloudbird-software", "CNB-1-all-privilege"),
]
RELAY_REPO = "swev-relay"
CRANE_URL = (
    "https://github.com/google/go-containerregistry/releases/download/"
    "v0.22.1/go-containerregistry_Linux_x86_64.tar.gz"
)

PIPELINE = """main:
  api_trigger:
    - name: relay
      runner:
        tags: cnb:arch:amd64
        cpus: 2
      stages:
        - name: crane-relay
          script: |
            set -e
            curl -sL -o /tmp/gcr.tgz "{crane}"
            tar -xzf /tmp/gcr.tgz -C /tmp crane && chmod +x /tmp/crane
            /tmp/crane auth login -u "$CNB_TOKEN_USER_NAME" -p "$CNB_TOKEN" docker.cnb.cool
            time /tmp/crane copy --platform linux/amd64 "{img}" "{dest}"
            echo RELAY_OK "{dest}"
"""


CNB_TOKEN_FILE = os.path.expanduser("~/.config/cnb/relay-tokens.json")


def bao_field(path, field):
    # 优先本地 0600 令牌文件（2026-10-20 迁移：工具不再依赖 escrow root 明文）
    if field == "Token":
        try:
            with open(CNB_TOKEN_FILE) as f:
                t = json.load(f).get(path)
            if t:
                return t
        except FileNotFoundError:
            pass
    with open(BAO_RT) as f:
        rt = f.read().strip()
    req = urllib.request.Request(
        f"{BAO}/v1/kv/data/company/Git-Platform/CNB/{path}",
        headers={"X-Vault-Token": rt},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)["data"]["data"][field]


def cnb(token, method, path, body=None):
    req = urllib.request.Request(
        f"{CNB_API}{path}",
        method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        data=json.dumps(body).encode() if body is not None else None,
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read().decode("utf-8", "replace").strip()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"CNB {method} {path} -> {e.code}: {detail}") from e


def tag_of(img):
    """swebench/sweb.eval.x86_64.astropy_1776_astropy-13579:latest -> astropy-13579"""
    name = img.rsplit(":", 1)[0].split("/")[-1]
    return name.split("_1776_")[-1] if "_1776_" in name else name


def anolis(*cmd):
    return subprocess.run(
        ["ssh", "-o", "ConnectTimeout=10", "anolis", *cmd],
        capture_output=True, text=True, timeout=1800,
    )


def on_anolis(img):
    return anolis("docker", "image", "inspect", img).returncode == 0


def anolis_alive():
    """anolis docker 可达性预检（不拉任何东西，秒级）。"""
    r = anolis("docker", "version", "--format", "{{.Server.Version}}")
    return r.returncode == 0 and r.stdout.strip() != ""


def deliver_or_fail(img, msg):
    """收尾失败 ≠ 未送到：anolis 精确名在场即算成功，不在场才 False。
    2026-10-20 22:21 波教训：ssh 闪断窗口把 22 张已到场镜像判成 FAILED
    （on_anolis 假阴性 → 白拉 1-1.5GB → ssh load 假失败 → return False）。"""
    if on_anolis(img):
        print(f"[warn] {img} {msg}；但镜像已在 anolis——按成功处理", flush=True)
        return True
    print(f"[fail] {img} {msg}", flush=True)
    return False


def build_status(st):
    """顶层 status 字段会瞬态抖动（见过 pending/error 误报），以流水线级状态合成为准。"""
    pips = st.get("pipelinesStatus") or {}
    if not pips:
        return st.get("status")
    states = [p.get("status") for p in pips.values()]
    if any(s in ("failed", "canceled", "error") for s in states):
        return "failed"
    if all(s == "success" for s in states):
        return "success"
    return "running"


def registry_has(token, ref):
    """制品库是否已有该 tag（HEAD manifest，走 basic→token 流）。"""
    repo, tag = ref.split(":")
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
                 "Accept": "application/vnd.oci.image.index.v1+json,application/vnd.docker.distribution.manifest.list.v2+json,application/vnd.docker.distribution.manifest.v2+json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status == 200
    except urllib.error.HTTPError:
        return False
    except urllib.error.URLError:
        return False


def sweep_stale(base=CACHE_DIR, age_min=STALE_MIN):
    """启动顺带清扫缓存目录：fastpull-* 临时目录与 *.tar / *.part* 文件，mtime 超龄才删。
    mtime 闸不碰活文件；幂等，多进程并发启动各自跑一遍也安全。"""
    cutoff = time.time() - age_min * 60
    removed = 0
    try:
        entries = os.listdir(base)
    except OSError:
        return
    for name in entries:
        if not (name.startswith("fastpull-") or name.endswith(".tar") or ".part" in name):
            continue
        path = os.path.join(base, name)
        try:
            if os.path.getmtime(path) > cutoff:
                continue
            if os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path, ignore_errors=True)
            else:
                os.remove(path)
            removed += 1
        except OSError:
            continue
    if removed:
        print(f"[sweep] 清理 >{age_min}min 陈旧残件 {removed} 个（{base}）", flush=True)


def relay_once(img, org, key_path, timeout=2400):
    t0 = time.time()
    token = bao_field(key_path, "Token")
    dest = f"docker.cnb.cool/{org}/{RELAY_REPO}:{tag_of(img)}"
    if on_anolis(img):
        print(f"[skip] {img} 已在 anolis", flush=True)
        return True
    ref = f"{org}/{RELAY_REPO}:{tag_of(img)}"
    if not registry_has(token, ref):
        cfg = PIPELINE.format(crane=CRANE_URL, img=img, dest=dest)
        resp = cnb(token, "POST", f"/{org}/{RELAY_REPO}/-/build/start", {
            "event": "api_trigger", "branch": "main", "sync": False,
            "title": f"relay {tag_of(img)}", "config": cfg,
        })
        sn = resp.get("sn")
        if not sn:
            print(f"[fail] {img} 触发被拒: {resp}", flush=True)
            return False
        print(f"[build] {img} -> {dest} sn={sn}", flush=True)
        status = None
        while time.time() - t0 < timeout:
            st = cnb(token, "GET", f"/{org}/{RELAY_REPO}/-/build/status/{sn}")
            status = build_status(st)
            if status in ("success", "failed"):
                break
            time.sleep(10)
        if status != "success":
            print(f"[fail] {img} 构建 {status}", flush=True)
            return False
    else:
        print(f"[cached] {img} 制品库已有，跳过构建", flush=True)
    # 传输：本机 fast-pull（docker.cnb.cool 单流 4.3MB/s、并发 18MB/s）→ ssh docker load。
    # anolis 直拉制品库实测 <300KB/s（1.13GB 超 15 分钟），不走那条路。
    token_local = bao_field(key_path, "Token")
    ref = f"{org}/{RELAY_REPO}:{tag_of(img)}"
    loaded_name = ref.replace("/", "_")
    tar = f"{CACHE_DIR}/{tag_of(img)}.tar"
    try:
        os.makedirs(os.path.dirname(tar), exist_ok=True)
        # ssh 预检：anolis 不可达时后面 load 必败——立即失败，不白拉 1-1.5GB、不空转 200s。
        # （构建仍会在上一步正常触发/命中，制品入库不浪费；只有本地拉取这腿值得省。）
        if not anolis_alive():
            print(f"[fail] {img} anolis docker 不可达（ssh 闪断?），中继中止不白拉", flush=True)
            return False
        pull = subprocess.run(
            ["python3", f"{os.path.dirname(os.path.abspath(__file__))}/fast-pull.py",
             ref, tar, "--registry", "docker.cnb.cool", "--token", token_local,
             "--jobs", "12", "--split", "8"],
            capture_output=True, text=True, timeout=3600,
            env={**os.environ, "TMPDIR": CACHE_DIR},
        )
        if pull.returncode != 0:
            return deliver_or_fail(img, f"本机拉取失败: {pull.stderr[-200:]}")
        with open(tar, "rb") as f:
            load = subprocess.run(
                ["ssh", "-o", "ConnectTimeout=10", "anolis", "docker", "load"],
                stdin=f, capture_output=True, text=True, timeout=3600,
            )
        if load.returncode != 0 or "Loaded image" not in (load.stdout + load.stderr):
            return deliver_or_fail(img, f"anolis load 失败: {(load.stdout + load.stderr)[-200:]}")
        tag = anolis("docker", "tag", loaded_name, img)
        if tag.returncode != 0:
            # 若规范名此前已被并发/上轮进程 tag 成功则此处按在场记成功，否则真失败
            return deliver_or_fail(
                img, f"docker tag {loaded_name} 失败: {tag.stderr[-200:]}")
        rmi = anolis("docker", "rmi", loaded_name)
        if rmi.returncode != 0:
            print(f"[warn] {img} 清理中间名 {loaded_name} 失败（不影响交付，残留留待覆盖）",
                  flush=True)
        os.remove(tar)
        print(f"[ok] {img} 中继完成（{int(time.time()-t0)}s）", flush=True)
        return True
    finally:
        # 泄漏根修：失败路径也要清。只删 >30min 的陈旧同名 tar——活进程（并发同镜像）
        # 的 tar mtime 新鲜不会被误删；当次失败留下的新鲜残件由启动清扫（>60min）兜底。
        try:
            if os.path.exists(tar) and time.time() - os.path.getmtime(tar) > FAIL_STALE_SEC:
                os.remove(tar)
        except OSError:
            pass


def mkrepo(org, key_path):
    token = bao_field(key_path, "Token")
    try:
        cnb(token, "POST", f"/{org}/-/repos", {"name": RELAY_REPO, "visibility": "private"})
        print(f"已建 {org}/{RELAY_REPO}")
    except RuntimeError as e:
        if "exist" in str(e).lower() or "409" in str(e):
            print(f"{org}/{RELAY_REPO} 已存在")
        else:
            raise


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["once", "loop", "mkrepo"])
    ap.add_argument("target", nargs="?", default="")
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--org", default=None, help="固定 org（默认交替）")
    args = ap.parse_args()

    sweep_stale()  # 启动顺带清扫 ~/.cache/s1pull 陈旧件（幂等）

    if args.cmd == "mkrepo":
        org, key = (args.org, None) if args.org else ORGS[0]
        for o, k in ORGS:
            mkrepo(o, k)
        return

    if args.cmd == "once":
        img = args.target
        org, key = (args.org, dict(ORGS)[args.org]) if args.org else ORGS[0]
        ok = relay_once(img, org, key)
        sys.exit(0 if ok else 1)

    # loop：逐行读镜像列表，交替 org，串行（CNB 构建内部已并行拉层）
    imgs = [l.strip() for l in open(args.target) if l.strip() and not l.startswith("#")]
    ok_n = 0
    for i, img in enumerate(imgs):
        org, key = ORGS[i % len(ORGS)] if not args.org else (args.org, dict(ORGS)[args.org])
        if relay_once(img, org, key):
            ok_n += 1
    print(f"loop 完成: {ok_n}/{len(imgs)}")


if __name__ == "__main__":
    main()
