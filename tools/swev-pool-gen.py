#!/usr/bin/env python3
"""swev-pool-gen.py — swev 题库扩池生成器（anolis 侧运行；P3 补货面，一次性工具）

解决 121 题池耗尽：从 SWE-bench 数据集机械生成新 swev 任务 JSON 并入补货队列。

在 anolis 上运行（重活在 anolis，本机只写代码与轻探针）：
  ssh anolis /home/pan-ding/swev-venv/bin/python /data/bench/swev-pool-gen.py --limit 60
  ssh anolis /home/pan-ding/swev-venv/bin/python /data/bench/swev-pool-gen.py --limit 5 --pull   # 扩池（拉镜像）
  # 扩源参数化（D-67 扩池三案·扩源案三轴；不传=旧行为逐字节等价）：
  #   类目  --repos astropy,django        扩池选择集只取指定仓库类目（严格模式候选不受影响）
  #   词表  --wordlist /path/ids.txt      扩池选择集只取词表内 instance_id（一行一个，# 注释；
  #                                       未命中词表条数透明上报，不静默吞）
  #   时间窗外推 --dataset-url URL --dataset-cache PATH --source-tag TAG
  #                                       指向更新/更宽的数据集快照（默认=既有 Verified 快照件）

流程（全机械，无 LLM）：
  0. STOP 熔断：/data/bench/queue/STOP 或 /data/bench/swev-pool-gen.STOP 存在即退出(2)，fail-closed；
  1. 读 SWE-bench Verified parquet（hf-mirror 缓存，fallback huggingface.co），列出全部 instance_id（全量落日志）；
  2. docker images → 现有实例镜像集合（容忍 docker.1ms.run/ 等 registry 前缀）；
  3. 严格模式候选 = 数据集 ∩ 有镜像 − 题库已有 JSON − submitted.jsonl 已出现 task − pending 已排队 task；
  4. --pull 扩池：候选 = 数据集 − 有镜像 − 上述排除（可扩题）；逐题拉镜像后再回到 3：
     · 扩源过滤（可选，默认无=全量可扩题）：--repos 类目 / --wordlist 词表 只作用于
       扩池选择集（拉哪些可扩题），严格模式候选（已有镜像的题）恒不受影响；
     · 磁盘护栏优先：每次拉取前 df /data 可用 ≥80GiB，低于即停并如实记录（拉取全程保持）；
     · 总量帽 40 个/次（--max-pull）；凑够 --limit 即提前收工；
     · 加速器路线：docker pull 走 /etc/docker/daemon.json 的 registry-mirrors（含 docker.1ms.run），
       失败回退 fast-pull.py（/data/bench/fast-pull.py，range 分片直连加速器）→ docker load → docker tag 归名；
     · 加速器不可用或磁盘不足 → 回退严格模式，如实记录，不伪造；
  5. 为最终候选（≤limit）生成题库 JSON（swebench make_test_spec，schema 与 /data/bench/swev-s1-r0/*.json 一致）
     与补货队列条目 {unit=swev, data_root=/data/bench/swev-s1-r0, profile=step-5, max_turns=40,
     spend_cap=300, dedupe_key=gen1-<task>}，条目落 /data/bench/queue/pending/0300-gen1-<task>.json
     （0300 前缀 = 排在 rr55(90)/普通(117+)/rr80(0200) 之后的兜底优先级）；
  6. 汇总（镜像数/可扩题数/磁盘代价/拉取数/生成数）打屏并落日志 /data/bench/swev-pool-gen.log。
7. 机器可读面（DEB-8「原因盲」修复，2026-11-05）：出口双写 state json——
   在役侧 /data/bench/swev-pool-gen-state.json（--state 可改）+ 工作区观测面
   状态观测/swev-pool-gen-state.json（anolis 与本机 /home 同源，2026-11-05 实测互通），
   字段 ts/stop_why/rc/detail：stop_why 为**机器码**，与人读日志同源不同形——
     ""=本次有产出；no_candidates=无"缺 JSON 的镜像题"（严格模式候选 0，且本次未请求 --pull）；
     no_expand_candidates=请求了 --pull 但过滤/排除后可扩题为 0（与未请求拉取的 no_candidates 分码）；
     disk_floor_precheck=拉取前 /data 可用已低于 80GiB 下限；disk_floor_during_pull=拉取中跌破下限；
     accelerator_unavailable=加速器连续 2 次拉取失败；target_met=已凑够 --limit 目标提前收工；
     pull_cap_reached=拉取数先够到 --max-pull 帽而 --limit 目标未凑够（D-67 与 target_met 分码，
                       旧码把帽满混记 target_met，观测面分不出「凑够目标」与「帽满收工」）；
     stop_file=STOP 熔断在位（rc=2）。
   detail 增补（D-67 观测细化；**全部为附加键，旧键一律不变**）：
     expand_attempted 本次是否走了扩池；pull_cap 单次拉取帽；expandable_by_repo 可扩题类目
     分布（top，降序——运营者据此看哪类还有货）；disk_headroom_gib 距磁盘下限的余量；
     repos_filter/wordlist_n 扩源过滤参数留痕；source_tag 数据集快照标签（时间窗外推对账面）。
   调度中枢/观测面直接机读该件，不必再从人读日志的"或磁盘护栏/加速器阻断"里猜停因。

幂等：题库已有 JSON 不重写；pending 已有同名条目不重写；断点重跑安全。
护栏：STOP 熔断；--dry-run 全流程只读不落盘（题库/队列/state 概不写）；密钥零明文（无任何凭据参与）。
回滚：停进程（一次性工具无需常驻）；删 /data/bench/queue/pending/0300-gen1-*.json 与本次新增题库 JSON。
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request

POOL = "/data/bench/swev-s1-r0"                    # swev 题库（队列条目 data_root 同此）
QUEUE = "/data/bench/queue"
PENDING = QUEUE + "/pending"
SUBMITTED = QUEUE + "/submitted.jsonl"
STOP_SCRIPT = "/data/bench/swev-pool-gen.STOP"   # 脚本级熔断（绝对路径，与队列目录无关）
LOG_F = "/data/bench/swev-pool-gen.log"
STATE_F = "/data/bench/swev-pool-gen-state.json"   # 在役侧机器可读面（anolis；与日志同目录同生命周期）
STATE_WS = os.environ.get("SWEV_POOL_STATE_WS") or \
    "/home/pan-ding/workspace/agent黑灯工厂/状态观测/swev-pool-gen-state.json"  # 工作区观测面（双写第二址）
FAST_PULL = "/data/bench/fast-pull.py"             # anolis 在役的加速器 range 分片速拉
DATASET_CACHE = "/data/bench/swev-pool-cache/swe-bench-verified-test-00000-of-00001.parquet"
DATASET_URLS = (
    "https://hf-mirror.com/datasets/princeton-nlp/SWE-bench_Verified/resolve/main/data/test-00000-of-00001.parquet",
    "https://huggingface.co/datasets/princeton-nlp/SWE-bench_Verified/resolve/main/data/test-00000-of-00001.parquet",
)
SOURCE_TAG_DEFAULT = "swe-bench-verified@cached-snapshot"  # 时间窗外推对账标签（state detail.source_tag 缺省）
DISK_FLOOR_GIB = 80.0          # /data 剩余下限（运营者裁决的磁盘护栏）
PULL_CAP = 40                  # 单次扩池最多拉取的新镜像数
ENTRY_PREFIX = "0300"          # pending 文件名前缀（兜底优先级）
DEDUPE_PREFIX = "gen1"
UNIT, PROFILE, MAX_TURNS, SPEND_CAP = "swev", "step-5", 40, 300
PULL_TIMEOUT_S = 3600
VENV_PY = "/home/pan-ding/swev-venv/bin/python"


def log(msg):
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_F, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError as e:
        print(f"（日志落盘失败，仅打屏: {e}）", file=sys.stderr, flush=True)


def stop_present(queue_dir):
    """STOP 熔断：队列级 STOP（随 --queue-dir，默认 /data/bench/queue/STOP，burn-runner 同款）
    与脚本级 STOP（/data/bench/swev-pool-gen.STOP）任一在位即 fail-closed。"""
    return [p for p in (os.path.join(queue_dir, "STOP"), STOP_SCRIPT) if os.path.exists(p)]


def write_state(state, paths):
    """机器可读面双写（DEB-8）：state dict → 各路径原子落盘（tmp+replace，防半写件被读）。
    观测面是附加回传、不是主流程：单址写失败只记日志不阻断（生成器本职是补货）；
    但绝不伪造——写没写出去以本函数日志为准。"""
    payload = json.dumps(state, ensure_ascii=False, indent=1)
    for p in paths:
        if not p:
            continue
        try:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            tmp = p + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(payload + "\n")
            os.replace(tmp, p)
            log(f"state 落盘：{p}")
        except OSError as e:
            log(f"（state 落盘失败 {p}，仅打屏: {e}）")


def ensure_deps():
    """pandas/swebench 只在 swev-venv；解释器缺依赖时自动改签 venv python 重跑。"""
    try:
        import pandas  # noqa: F401
        import swebench.harness.test_spec.test_spec  # noqa: F401
        return
    except ImportError:
        pass
    if os.path.exists(VENV_PY) and os.path.realpath(VENV_PY) != os.path.realpath(sys.executable):
        log(f"当前解释器缺 pandas/swebench，改签 {VENV_PY} 重跑")
        os.execv(VENV_PY, [VENV_PY] + sys.argv)
    sys.exit("缺依赖：请用 /home/pan-ding/swev-venv/bin/python 运行本脚本（pandas + swebench 4.1）")


# ---------- ① 数据集 ----------

def load_dataset(urls=None, cache=None):
    """读数据集 parquet（hf-mirror 优先，缓存到 /data）。返回 pandas.DataFrame。
    时间窗外推轴（D-67）：urls/cache 可指向更新或更宽的快照；缺省=既有 Verified 快照件
    （旧行为逐字节等价）。快照不可得时 sys.exit（不伪造、不静默换旧件顶数）。"""
    import pandas as pd
    urls = tuple(urls) if urls else DATASET_URLS
    cache = cache or DATASET_CACHE
    if not os.path.exists(cache):
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        tmp = cache + ".part"
        ok = False
        for url in urls:
            try:
                log(f"下载数据集: {url}")
                urllib.request.urlretrieve(url, tmp)
                ok = True
                break
            except Exception as e:
                log(f"数据集源失败（试下一个）: {url} -> {e}")
        if not ok:
            sys.exit(f"数据集不可得（所给源均失败）: {list(urls)}")
        os.replace(tmp, cache)
        log(f"数据集已缓存: {cache} ({os.path.getsize(cache)/1e6:.1f}MB)")
    df = pd.read_parquet(cache)
    return df


# ---------- ② 现状集合 ----------

def image_name(iid):
    """实例 → 镜像名（与 tools/swev-prep.py:15 实证一致）。"""
    return "swebench/sweb.eval.x86_64." + iid.replace("__", "_1776_").lower() + ":latest"


def docker_images():
    """现有实例镜像 → instance_id 集合（容忍 registry 前缀与大小写）。"""
    r = subprocess.run("docker images --format {{.Repository}}:{{.Tag}}",
                       shell=True, capture_output=True, text=True, timeout=120)
    out = set()
    for ref in r.stdout.split():
        marker = "swebench/sweb.eval.x86_64."
        pos = ref.rfind(marker)
        if pos < 0 or not ref.endswith(":latest"):
            continue
        mid = ref[pos + len(marker):-len(":latest")]
        parts = mid.split("_1776_")
        if len(parts) >= 2:
            out.add(parts[0] + "__" + "_1776_".join(parts[1:]))
    return out


def pool_tasks(pool_dir):
    return {os.path.basename(f)[:-5] for f in glob.glob(os.path.join(pool_dir, "*.json"))}


def submitted_tasks(submitted_f):
    """submitted.jsonl 已出现的一切 task（任务⑤：一律排除）。"""
    out = set()
    try:
        for ln in open(submitted_f, encoding="utf-8"):
            ln = ln.strip()
            if not ln:
                continue
            try:
                t = json.loads(ln).get("task")
                if t:
                    out.add(t)
            except Exception:
                continue
    except FileNotFoundError:
        pass
    return out


def pending_tasks(pending_dir):
    """pending/ 已排队的 swev task（文件名去 序号-/rr55|rr80|gen1- 前缀；只认含 __ 的 swev id）。"""
    out = set()
    for f in glob.glob(os.path.join(pending_dir, "*.json")):
        b = os.path.basename(f)[:-5]
        b = re.sub(r"^\d+-", "", b)
        b = re.sub(r"^(rr55|rr80|gen1)-", "", b)
        if "__" in b:
            out.add(b)
    return out


# ---------- ④ 拉镜像扩池 ----------

def parse_repos(s):
    """类目轴（D-67）：--repos 'astropy,flask' → set；空/None=不过滤（全量可扩题）。
    单个 token 可按属主前缀（pytest-dev）/repo 全名（pytest-dev/pytest）/仓库名
    （flask）三种写法命中，见 repo_match。"""
    if not s:
        return None
    return {t.strip() for t in s.split(",") if t.strip()} or None


def load_wordlist(path):
    """词表轴（D-67）：--wordlist 文件 → instance_id 集合。一行一个；空行与 # 注释行忽略。
    文件不可得=调用方 fail-closed（扩源参数写错不许静默升级为全量）。"""
    out = set()
    with open(path, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if ln and not ln.startswith("#"):
                out.add(ln)
    return out


def repo_of(iid):
    """instance_id → 仓库类目名（'astropy__astropy-7166' → 'astropy'；'pallets__flask-5014' → 'pallets'）。"""
    return iid.split("__", 1)[0]


def repo_match(token, iid, repo):
    """类目轴匹配（D-67）：token 命中三种写法之一即算同类目——
    ① 属主前缀（repo_of(iid)，如 pytest-dev/scikit-learn/sphinx-doc）；
    ② 数据集 repo 列全名（pytest-dev/pytest）；
    ③ repo 列末段（flask/requests/xarray 等仓库名，属主与仓库名不同名时用）。
    精确相等匹配（不用子串，防 'py' 之类过宽命中）。"""
    return token == repo_of(iid) or token == repo or token == repo.split("/")[-1]


def disk_free_gib(path="/data"):
    return shutil.disk_usage(path).free / 2 ** 30


def pull_image(iid):
    """拉一个实例镜像。先 docker pull（daemon registry-mirrors 含 docker.1ms.run），
    失败回退 fast-pull.py range 分片直连 → docker load → docker tag 归名。返回 (ok, 途径, 字节数)。"""
    img = image_name(iid)
    r = subprocess.run(["docker", "pull", img], capture_output=True, text=True, timeout=PULL_TIMEOUT_S)
    if r.returncode == 0:
        return True, "docker-pull(mirror)", 0
    log(f"docker pull 失败（{iid}）: {(r.stderr or r.stdout).strip()[-200:]}；回退 fast-pull")
    tar = f"/tmp/swevpool-{iid.replace('/', '_')}.tar"
    try:
        r2 = subprocess.run([sys.executable if "swev-venv" in sys.executable else "python3",
                             FAST_PULL, img, tar, "--registry", "docker.1ms.run"],
                            capture_output=True, text=True, timeout=PULL_TIMEOUT_S)
        if r2.returncode != 0:
            log(f"fast-pull 失败（{iid}）: {(r2.stderr or r2.stdout).strip()[-200:]}")
            return False, "fast-pull", 0
        r3 = subprocess.run(["docker", "load", "-i", tar], capture_output=True, text=True, timeout=600)
        if r3.returncode != 0:
            log(f"docker load 失败（{iid}）: {(r3.stderr or r3.stdout).strip()[-200:]}")
            return False, "docker-load", 0
        loaded = img.split("/", 1)[1].replace("/", "_")  # fast-pull 的 RepoTags: repo 内 / → _
        r4 = subprocess.run(["docker", "tag", loaded + ":latest", img],
                            capture_output=True, text=True, timeout=120)
        if r4.returncode != 0:
            log(f"docker tag 失败（{loaded} -> {img}）: {(r4.stderr or r4.stdout).strip()[-200:]}")
            return False, "docker-tag", 0
        return True, "fast-pull", os.path.getsize(tar) if os.path.exists(tar) else 0
    finally:
        try:
            os.remove(tar)
        except OSError:
            pass


def expand(df, have_img, pool, subm, pend, need, max_pull, dry, repos=None, wordlist=None):
    """扩池：为缺镜像的可扩题拉镜像。返回 (新拉取 iid 列表, 停因人读, 停因机器码)。
    机器码取值见模块头 ⑦（""=无停因/no_expand_candidates/disk_floor_precheck/
    disk_floor_during_pull/accelerator_unavailable/target_met/pull_cap_reached）
    ——与人读串同源，机读面不再猜。
    扩源过滤轴（D-67，默认 None=旧行为）：repos 类目集 / wordlist 词表集只作用于
    扩池选择集；被过滤排除的条数透明记日志，不静默吞。"""
    pulled, stop_why, stop_code = [], "", ""
    free0 = disk_free_gib()
    log(f"扩池磁盘护栏：/data 可用 {free0:.1f}GiB，下限 {DISK_FLOOR_GIB:.0f}GiB，"
        f"单次帽 {max_pull}，目标 {need} 个")
    if free0 < DISK_FLOOR_GIB:
        return pulled, (f"磁盘护栏未过：/data 可用 {free0:.1f}GiB < {DISK_FLOOR_GIB:.0f}GiB 下限，"
                        f"按运营者裁决回退严格模式（0 个镜像可拉）"), "disk_floor_precheck"
    # 扩池选择集：可扩题（无镜像且三排除）→ 类目/词表过滤（只记数不改变语义外的行为）
    sel = [r for r in df.itertuples()
           if r.instance_id not in have_img and r.instance_id not in pool
           and r.instance_id not in subm and r.instance_id not in pend]
    n_before = len(sel)
    if repos:
        sel = [r for r in sel if any(repo_match(t, r.instance_id, r.repo) for t in repos)]
    if wordlist:
        hit = {r.instance_id for r in sel} & wordlist
        miss = len(wordlist) - len(hit)
        sel = [r for r in sel if r.instance_id in wordlist]
        if miss:
            log(f"词表 {len(wordlist)} 条中 {miss} 条不在可扩集（已拉/已入册/已排除或不在数据集），按可扩集实拉")
    if repos:
        log(f"类目过滤 --repos {sorted(repos)}：可扩题 {n_before} → {len(sel)}")
    if not sel:
        stop_why = (f"扩池无可拉题：过滤后可扩题 0（过滤前 {n_before}"
                    f"{'；--repos ' + ','.join(sorted(repos)) if repos else ''}"
                    f"{'；--wordlist ' + str(len(wordlist)) + ' 条' if wordlist else ''}）")
        stop_code = "no_expand_candidates"
        log(stop_why)
        return pulled, stop_why, stop_code
    fails = 0
    for row in sel:
        if len(pulled) >= need:
            stop_why = stop_why or f"已凑够目标（{len(pulled)} 个，帽 {max_pull}）"
            stop_code = stop_code or "target_met"
            break
        if len(pulled) >= max_pull:
            stop_why = stop_why or (f"拉取数先够到单次帽 {max_pull} 个而目标 {need} 未凑够"
                                    f"（帽满收工，非目标达成）")
            stop_code = stop_code or "pull_cap_reached"
            break
        iid = row.instance_id
        free = disk_free_gib()
        if free < DISK_FLOOR_GIB:
            stop_why = f"磁盘护栏触发：拉取中 /data 可用降至 {free:.1f}GiB < {DISK_FLOOR_GIB:.0f}GiB，停止拉取"
            stop_code = "disk_floor_during_pull"
            log(stop_why)
            break
        if dry:
            log(f"[dry-run] 将拉取 {image_name(iid)}（当前可用 {free:.1f}GiB）")
            pulled.append(iid)
            continue
        log(f"拉取 {image_name(iid)}（拉前可用 {free:.1f}GiB，第 {len(pulled)+1}/{max_pull} 个）")
        t0 = time.time()
        ok, how, nbytes = pull_image(iid)
        if not ok:
            fails += 1
            if fails >= 2:
                stop_why = "加速器不可用（连续 2 次拉取失败），回退严格模式"
                stop_code = "accelerator_unavailable"
                log(stop_why)
                break
            continue
        fails = 0
        pulled.append(iid)
        if image_name(iid) not in docker_images():
            log(f"告警：{iid} 拉取回报成功但镜像不在位，仍计生成候选（judge 时会再发现）")
        log(f"  拉成 {iid}（{how}，{time.time()-t0:.0f}s，拉后可用 {disk_free_gib():.1f}GiB）")
    return pulled, stop_why, stop_code


# ---------- ③ 生成 ----------

def build_payload(row):
    """与 tools/swev-prep.py 同 schema：make_test_spec 产 eval_script，字段集/顺序一致。"""
    from swebench.harness.test_spec.test_spec import make_test_spec
    inst = row.to_dict() if hasattr(row, "to_dict") else dict(row._asdict())
    inst["image"] = image_name(inst["instance_id"])
    spec = make_test_spec(inst)
    return {
        "instance_id": inst["instance_id"],
        "repo": inst["repo"],
        "version": inst["version"],
        "base_commit": inst["base_commit"],
        "problem_statement": inst["problem_statement"],
        "hints_text": inst.get("hints_text") or "",
        "image": image_name(inst["instance_id"]),
        "test_patch": inst["test_patch"],
        "eval_script": spec.eval_script,
        "fail_to_pass": json.loads(inst["FAIL_TO_PASS"]),
        "pass_to_pass": json.loads(inst["PASS_TO_PASS"]),
    }


def gen_one(row, pool_dir, pending_dir, dry):
    iid = row.instance_id
    jpath = os.path.join(pool_dir, iid + ".json")
    epath = os.path.join(pending_dir, f"{ENTRY_PREFIX}-{DEDUPE_PREFIX}-{iid}.json")
    entry = {"unit": UNIT, "task": iid, "data_root": POOL, "profile": PROFILE,
             "max_turns": MAX_TURNS, "spend_cap": SPEND_CAP,
             "note": f"{DEDUPE_PREFIX} 扩池：SWE-bench Verified × 镜像交集（burn-runner 补货）",
             "dedupe_key": f"{DEDUPE_PREFIX}-{iid}"}
    if dry:
        log(f"[dry-run] 将写题库 {jpath} 与队列 {epath}")
        return jpath, epath, False, False
    wj = wp = False
    if not os.path.exists(jpath):
        payload = build_payload(row)
        tmp = jpath + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
        os.replace(tmp, jpath)
        wj = True
    else:
        log(f"题库已有 JSON，跳过: {jpath}")
    if not os.path.exists(epath):
        tmp = epath + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(entry, f, ensure_ascii=False, indent=1)
        os.replace(tmp, epath)
        wp = True
    else:
        log(f"队列已有同名条目，跳过: {epath}")
    return jpath, epath, wj, wp


def main():
    ap = argparse.ArgumentParser(description="swev 题库扩池生成器（anolis 侧，机械，无 LLM）")
    ap.add_argument("--limit", type=int, default=60, help="本次最多生成的新任务数（默认 60）")
    ap.add_argument("--pull", action="store_true",
                    help="扩池模式：对缺镜像的可扩题先拉镜像（磁盘护栏 /data≥80GiB，帽 40）再生成")
    ap.add_argument("--max-pull", type=int, default=PULL_CAP, help=f"单次最多拉取镜像数（默认 {PULL_CAP}）")
    ap.add_argument("--repos", default=None, metavar="R1,R2",
                    help="扩源·类目轴：扩池选择集只取这些仓库类目（逗号分隔；如 astropy,django）。"
                         "只过滤拉取对象，严格模式候选不受影响；缺省=全量可扩题")
    ap.add_argument("--wordlist", default=None, metavar="PATH",
                    help="扩源·词表轴：扩池选择集只取词表内 instance_id（一行一个，# 注释）。"
                         "文件不可得即退出（fail-closed，不静默升级全量）")
    ap.add_argument("--dataset-url", action="append", default=None, metavar="URL",
                    help="扩源·时间窗外推轴：替代数据集 parquet 下载源（可重复给多个，按序回退）；"
                         "缺省=既有 Verified 快照源")
    ap.add_argument("--dataset-cache", default=None, metavar="PATH",
                    help="扩源·时间窗外推轴：替代数据集缓存路径（与 --dataset-url 配对）；"
                         "缺省=既有 Verified 缓存件")
    ap.add_argument("--source-tag", default=SOURCE_TAG_DEFAULT, metavar="TAG",
                    help=f"数据集快照对账标签（写入 state detail.source_tag；缺省 {SOURCE_TAG_DEFAULT}）")
    ap.add_argument("--dry-run", action="store_true", help="只读演练：不写题库/队列、不拉镜像")
    ap.add_argument("--pool-dir", default=POOL, help="题库目录（测试可指向空目录）")
    ap.add_argument("--queue-dir", default=QUEUE, help="队列目录（测试可指向空目录）")
    ap.add_argument("--submitted", default=SUBMITTED, help="submitted.jsonl 路径")
    ap.add_argument("--state", default=STATE_F,
                    help="机器可读 state json 路径（在役侧；另双写工作区观测面，测试可指沙箱）")
    args = ap.parse_args()
    if args.limit < 0:
        sys.exit("--limit 不能为负")
    if args.max_pull < 0:
        sys.exit("--max-pull 不能为负")

    repos = parse_repos(args.repos)
    wordlist = None
    if args.wordlist:
        try:
            wordlist = load_wordlist(args.wordlist)
        except OSError as e:
            sys.exit(f"--wordlist 不可读（fail-closed，不静默升级为全量）: {args.wordlist} -> {e}")
        if not wordlist:
            sys.exit(f"--wordlist 为空（无可拉条目，fail-closed）: {args.wordlist}")
    dataset_urls = list(args.dataset_url) if args.dataset_url else None
    dataset_cache = args.dataset_cache or None

    pending_dir = os.path.join(args.queue_dir, "pending")
    stops = stop_present(args.queue_dir)
    if stops:
        log(f"STOP 熔断在位（{stops}），退出不动作")
        write_state({
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"), "ts_epoch": int(time.time()),
            "stop_why": "stop_file",
            "stop_why_text": f"STOP 熔断在位（{stops}），退出不动作",
            "rc": 2, "generated": 0,
            "detail": {"stops": stops, "limit": args.limit, "pull": args.pull,
                       "dry_run": args.dry_run,
                       "repos_filter": sorted(repos) if repos else None,
                       "wordlist_n": len(wordlist) if wordlist else None,
                       "source_tag": args.source_tag},
        }, [args.state, STATE_WS])
        sys.exit(2)
    ensure_deps()

    log(f"=== swev-pool-gen 起：limit={args.limit} pull={args.pull} dry_run={args.dry_run} "
        f"pool={args.pool_dir} queue={args.queue_dir} "
        f"repos={sorted(repos) if repos else '-'} wordlist_n={len(wordlist) if wordlist else 0} "
        f"source_tag={args.source_tag} ===")

    df = load_dataset(dataset_urls, dataset_cache)
    all_ids = list(df.instance_id)
    log(f"① 数据集全部 instance_id：{len(all_ids)} 个（首 {all_ids[:3]} … 末 {all_ids[-3:]}；"
        f"全量清单见日志尾部）")

    have_img = docker_images()
    pool = pool_tasks(args.pool_dir)
    subm = submitted_tasks(args.submitted)
    pend = pending_tasks(pending_dir)
    log(f"② 现状：镜像题 {len(have_img)}，题库 JSON {len(pool)}，submitted task {len(subm)}，"
        f"pending task {len(pend)}")

    def candidates():
        return [r for r in df.itertuples()
                if r.instance_id in have_img and r.instance_id not in pool
                and r.instance_id not in subm and r.instance_id not in pend]

    cands = candidates()
    log(f"③ 严格模式候选（有镜像且缺 JSON 且未 submitted/pending）：{len(cands)} 个")

    pulled, stop_why, stop_code = [], "", ""
    if args.pull and len(cands) < args.limit:
        pulled, stop_why, stop_code = expand(df, have_img, pool, subm, pend,
                                             need=args.limit - len(cands), max_pull=args.max_pull,
                                             dry=args.dry_run, repos=repos, wordlist=wordlist)
        if not args.dry_run:
            have_img = docker_images()
        cands = candidates()
        log(f"扩池后候选：{len(cands)} 个（本次实拉 {len(pulled)} 个镜像）")
    elif args.pull:
        log("严格模式候选已够 --limit，无需拉镜像")

    sel = cands[:args.limit]
    exp_rows = [r for r in df.itertuples()
                if r.instance_id not in have_img and r.instance_id not in pool
                and r.instance_id not in subm and r.instance_id not in pend]
    expandable = len(exp_rows)
    by_repo = {}
    for r in exp_rows:
        by_repo[repo_of(r.instance_id)] = by_repo.get(repo_of(r.instance_id), 0) + 1
    top_repos = dict(sorted(by_repo.items(), key=lambda kv: (-kv[1], kv[0]))[:12])
    log(f"可扩题类目分布（top）：{top_repos}")
    n_json = n_entry = 0
    for row in sel:
        _, _, wj, wp = gen_one(row, args.pool_dir, pending_dir, args.dry_run)
        n_json += int(wj)
        n_entry += int(wp)
        log(f"生成 {row.instance_id}：题库={'写' if wj else '跳'} 队列={'写' if wp else '跳'}")

    free = disk_free_gib()
    log(f"=== 汇总：数据集 {len(df)} | 镜像题 {len(have_img)} | 题库 {len(pool)} | "
        f"严格候选 {len(cands)} | 可扩题(无镜像) {expandable} | 实拉镜像 {len(pulled)} | "
        f"新增题库 JSON {n_json} | 新增队列条目 {n_entry} | /data 可用 {free:.1f}GiB(下限{DISK_FLOOR_GIB:.0f}) ===")
    if stop_why:
        log(f"扩池停因：{stop_why}")
    log(f"全部 instance_id（{len(all_ids)}）：{' '.join(all_ids)}")
    if args.dry_run:
        log("dry-run：未落盘")
    else:
        # 机器可读面（DEB-8「原因盲」）：停因码化 + 双写（在役侧 --state + 工作区观测面 STATE_WS）。
        # ""=有产出；stop_code=拉镜像路停因（磁盘护栏/加速器/凑够目标/帽满收工/无可拉题）；
        # no_candidates=严格模式候选 0 且未请求 --pull——调度中枢不再从人读日志猜"或"。
        # D-67 细化：no_expand_candidates（请求了 --pull 但可扩题 0）与 no_candidates 分码；
        # pull_cap_reached 与 target_met 分码；detail 增补全部为附加键（旧键不变）。
        code = "" if (n_json or n_entry) else (stop_code or "no_candidates")
        if code == "no_candidates":
            code_text = "严格模式候选 0（无'缺 JSON 的镜像题'；本次未请求 --pull）"
        elif code == "no_expand_candidates":
            code_text = stop_why
        else:
            code_text = stop_why or ""
        write_state({
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "ts_epoch": int(time.time()),
            "stop_why": code,
            "stop_why_text": code_text,
            "rc": 0,
            "generated": n_json + n_entry,
            "detail": {
                "limit": args.limit, "pull": args.pull, "dry_run": args.dry_run,
                "dataset": len(df), "have_img": len(have_img), "pool": len(pool),
                "subm": len(subm), "pend": len(pend), "cands": len(cands),
                "expandable": expandable, "pulled": len(pulled),
                "n_json": n_json, "n_entry": n_entry,
                "disk_free_gib": round(free, 1), "disk_floor_gib": DISK_FLOOR_GIB,
                # ---- D-67 观测细化（附加键，旧键一律不变） ----
                "expand_attempted": bool(args.pull),
                "pull_cap": args.max_pull,
                "expandable_by_repo": top_repos,
                "disk_headroom_gib": round(free - DISK_FLOOR_GIB, 1),
                "repos_filter": sorted(repos) if repos else None,
                "wordlist_n": len(wordlist) if wordlist else None,
                "source_tag": args.source_tag,
            },
        }, [args.state, STATE_WS])
    if n_json == 0 and n_entry == 0 and not args.dry_run:
        log("结果：0 个新任务生成（现状无'缺 JSON 的镜像题'，或磁盘护栏/加速器阻断扩池）")


if __name__ == "__main__":
    main()
