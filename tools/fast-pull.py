#!/usr/bin/env python3
"""fast-pull.py — OCI 镜像多连接速拉（绕过 docker 单连接限速），产出 docker load 可载 tar。

用法: fast-pull.py <repo:tag> <out.tar> [--registry docker.1panel.live] [--jobs 12] [--split 8]
流程: token（可省，镜像不鉴权时自动跳过）→ index(amd64) → manifest → config+blobs
      并发下载（大层按 --split 分 range 片，摊平单连接限速）→ docker tar 组装。

2026-10-20 复活记录：mihomo 死后本机 docker 守护进程仍挂着 7890 死代理导致拉取全挂；
改走"镜像加速器直连 + range 分片"——docker.1panel.live 对 swebench 镜像可用，
每连接 ~400-800KB/s 限速、总带宽随连接数扩展（8 连接实测 4.2MB/s）。

2026-10-20 泄漏根修：临时目录（fastpull-*）此前只在正常路径外全部遗留（成功也不删）；
现在结束后 finally 必删，启动时顺带清扫 ~/.cache/s1pull（与 TMPDIR）里 mtime>60min
的陈旧分片/tar——被 SIGKILL 的历史进程残件由后续任一次启动兜底回收（幂等）。
"""
import argparse
import base64
import concurrent.futures as cf
import glob
import json
import math
import os
import re
import shutil
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

PROXY = None
SPLIT_MIN = 32 * 1024 * 1024  # 小于 32MB 的层不分片
CACHE_DIR = os.path.expanduser("~/.cache/s1pull")
STALE_MIN = 60  # 超过此年龄（分钟）的缓存残件视为陈旧，可安全清除
UA = {"User-Agent": "curl/8.5.0"}  # 部分加速器屏蔽 python-urllib UA（403）
ACCEPT = (
    "application/vnd.oci.image.index.v1+json,"
    "application/vnd.docker.distribution.manifest.list.v2+json,"
    "application/vnd.docker.distribution.manifest.v2+json,"
    "application/vnd.oci.image.manifest.v1+json"
)


def token_flow(registry, repo, token, user="cnb"):
    """标准 registry token 流：/v2/ 挑战 → realm 换 token。
    制品库（docker.cnb.cool）用 basic(user:token) 换；docker.io 匿名公开换。"""
    req = urllib.request.Request(f"https://{registry}/v2/")
    for k, v in UA.items():
        req.add_header(k, v)
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=15):
            return {}  # 免鉴权
    except urllib.error.HTTPError as e:
        chal = e.headers.get("WWW-Authenticate", "")
    except urllib.error.URLError:
        return {}
    realm = re.search(r'realm="([^"]+)"', chal or "")
    if not realm:
        return {}
    svc = re.search(r'service="([^"]+)"', chal)
    params = {"scope": f"repository:{repo}:pull"}
    if svc:
        params["service"] = svc.group(1)
    tok_req = urllib.request.Request(realm.group(1) + "?" + urllib.parse.urlencode(params))
    for k, v in UA.items():
        tok_req.add_header(k, v)
    if token:
        basic = base64.b64encode(f"{user}:{token}".encode()).decode()
        tok_req.add_header("Authorization", f"Basic {basic}")
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(tok_req, timeout=20) as r:
        d = json.load(r)
    t = d.get("token") or d.get("access_token")
    return {"Authorization": f"Bearer {t}"} if t else {}


def http(url, headers=None, accept=None):
    req = urllib.request.Request(url)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    for k, v in UA.items():
        req.add_header(k, v)
    if accept:
        req.add_header("Accept", accept)
    ctx = (
        urllib.request.build_opener(urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))
        if PROXY
        else urllib.request.build_opener()
    )
    with ctx.open(req, timeout=60) as resp:
        return resp.read(), dict(resp.headers)


def fetch_file(url, headers, dest):
    req = urllib.request.Request(url)
    for k, v in headers.items():
        req.add_header(k, v)
    for k, v in UA.items():
        req.add_header(k, v)
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": PROXY, "https": PROXY})
        if PROXY
        else urllib.request.ProxyHandler({})
    )
    with opener.open(req, timeout=300) as resp, open(dest, "wb") as f:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
    return dest


def fetch_range(url, headers, dest, start, end):
    req = urllib.request.Request(url)
    for k, v in headers.items():
        req.add_header(k, v)
    for k, v in UA.items():
        req.add_header(k, v)
    req.add_header("Range", f"bytes={start}-{end}")
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": PROXY, "https": PROXY})
        if PROXY
        else urllib.request.ProxyHandler({})
    )
    with opener.open(req, timeout=300) as resp, open(dest, "wb") as f:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
    return dest


def sweep_stale(extra_dirs=(), age_min=STALE_MIN):
    """清扫陈旧拉取残件：fastpull-* 临时目录与 *.tar / *.part* 文件，mtime 超龄才删。
    mtime 闸保证绝不碰正在写入的活文件（同目录并发的另一拉取进程不受影响）；幂等。"""
    cutoff = time.time() - age_min * 60
    bases = {CACHE_DIR, *(d for d in extra_dirs if d)}
    removed = 0
    for base in bases:
        try:
            entries = os.listdir(base)
        except OSError:
            continue
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
        print(f"[sweep] 清理 >{age_min}min 陈旧残件 {removed} 个（{sorted(bases)}）", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ref")
    ap.add_argument("out")
    ap.add_argument("--proxy", default=None)
    ap.add_argument("--jobs", type=int, default=12)
    ap.add_argument("--arch", default="amd64")
    ap.add_argument("--registry", default="registry-1.docker.io")
    ap.add_argument("--token", default=None, help="制品库 access token（走挑战→token 流，跳过 auth.docker.io）")
    ap.add_argument("--token-user", default="cnb")
    ap.add_argument("--split", type=int, default=8, help="大层 range 分片数（0=不分片）")
    args = ap.parse_args()
    global PROXY
    PROXY = args.proxy
    # 启动顺带清扫：本缓存目录 + 本次实际使用的 TMPDIR（幂等，只动超龄残件）
    sweep_stale([tempfile.gettempdir()])

    repo, tag = args.ref.rsplit(":", 1)
    base = f"https://{args.registry}/v2/{repo}"

    # token：--token 制品库直连（挑战→token 流）；否则先试免鉴权，401 再走 auth.docker.io
    auth = {}
    if args.token:
        auth = token_flow(args.registry, repo, args.token, args.token_user)
        idx_raw, _ = http(f"{base}/manifests/{tag}", auth, accept=ACCEPT)
    else:
        try:
            idx_raw, _ = http(f"{base}/manifests/{tag}", accept=ACCEPT)
        except urllib.error.HTTPError as e:
            if e.code != 401:
                raise
            token, _ = http(
                f"https://auth.docker.io/token?service=registry.docker.io&scope=repository:{repo}:pull"
            )
            token = json.loads(token)["token"]
            auth = {"Authorization": f"Bearer {token}"}
            idx_raw, _ = http(f"{base}/manifests/{tag}", auth, accept=ACCEPT)

    idx = json.loads(idx_raw)
    if "manifests" in idx:
        digest = next(
            m["digest"]
            for m in idx["manifests"]
            if m.get("platform", {}).get("architecture") == args.arch
            and m.get("platform", {}).get("os") == "linux"
        )
        man_raw, _ = http(
            f"{base}/manifests/{digest}",
            auth,
            accept="application/vnd.oci.image.manifest.v1+json",
        )
        manifest = json.loads(man_raw)
    else:
        manifest = idx

    tmp = tempfile.mkdtemp(prefix="fastpull-")
    try:
        _assemble(args, tmp, base, auth, manifest, repo, tag)
    finally:
        # 泄漏根修：无论成功、异常都必删；被 SIGKILL 时 finally 不执行，由启动清扫兜底。
        shutil.rmtree(tmp, ignore_errors=True)


def _assemble(args, tmp, base, auth, manifest, repo, tag):
    layers = manifest["layers"]
    config = manifest["config"]
    total_mb = sum(l["size"] for l in layers) / 1e6
    print(f"{len(layers)} 层共 {total_mb:.0f}MB，并发 {args.jobs}，大层分片 {args.split}", flush=True)

    cfg_name = config["digest"].replace("sha256:", "") + ".json"
    fetch_file(f"{base}/blobs/{config['digest']}", auth, os.path.join(tmp, cfg_name))

    # 工作队列：每层整图一个 job，大层拆成多个 range job（扁平并发，避免嵌套池打爆连接数）
    work = []  # (layer_index, dest, start, end|None)
    for i, layer in enumerate(layers):
        d = layer["digest"].replace("sha256:", "")
        size = layer["size"]
        if args.split > 1 and size > SPLIT_MIN:
            chunk = math.ceil(size / args.split)
            s = 0
            while s < size:
                e = min(s + chunk, size) - 1
                work.append((i, os.path.join(tmp, f"{d}.part{s:012d}"), s, e))
                s = e + 1
        else:
            work.append((i, os.path.join(tmp, d + ".tar"), None, None))

    def job(item):
        i, dest, start, end = item
        url = f"{base}/blobs/{layers[i]['digest']}"
        if start is None:
            fetch_file(url, auth, dest)
        else:
            fetch_range(url, auth, dest, start, end)
        return i

    with cf.ThreadPoolExecutor(max_workers=args.jobs) as ex:
        list(ex.map(job, work))

    # 组装：分片按序号拼接回 <digest>.tar（拼接即删分片，分片不落地过夜）
    for i, layer in enumerate(layers):
        d = layer["digest"].replace("sha256:", "")
        dest = os.path.join(tmp, d + ".tar")
        parts = sorted(glob.glob(os.path.join(tmp, d + ".part*")))
        if parts:
            with open(dest, "wb") as out:
                for p in parts:
                    with open(p, "rb") as f:
                        shutil.copyfileobj(f, out, 1 << 20)
                    os.remove(p)
        print(f"  ok {d[:19]} {layer['size']/1e6:.0f}MB", flush=True)

    # docker load 格式：manifest.json + config + 每层一个目录 <digest>/layer.tar
    with tarfile.open(args.out, "w") as tar:
        tar.add(os.path.join(tmp, cfg_name), arcname=cfg_name)
        repo_tag = f"{repo.replace('/', '_')}:{tag}"
        mani = [{
            "Config": cfg_name,
            "RepoTags": [repo_tag],
            "Layers": [],
        }]
        for layer in layers:
            d = layer["digest"].replace("sha256:", "")
            tar.add(os.path.join(tmp, d + ".tar"), arcname=f"{d}/layer.tar")
            mani[0]["Layers"].append(f"{d}/layer.tar")
        mani_path = os.path.join(tmp, "manifest.json")
        with open(mani_path, "w") as f:
            json.dump(mani, f)
        tar.add(mani_path, arcname="manifest.json")
    print(f"→ {args.out}（docker load -i 可载，RepoTag={repo_tag}）")


if __name__ == "__main__":
    main()
