#!/usr/bin/env python3
r"""img-gc.py — anolis sweb.eval 镜像池 GC（补丁③ R2，2026-10-22）。

定位：单点止血（10-22 01:1x 人工 GC 的自动化复刻，巡检日志:157-158 台账：85% 先回收 /
88% 停手回报、保留三源并集 39 张、实时 ps 避让）；D-26 统一资源治理（技术债登记:33）
落地后降级为其执行器或退役。

执行通道（红线①）：所有 docker 读写一律经 ["ssh","-o","ConnectTimeout=10","anolis",
"docker",…]（先例 factory-sched.py:509-521 relay 盘点、factory-watch.py:406-411
ANOLIS_CMD）。plan/apply 必须 --host anolis，代码断言其他值直接 SystemExit——绝不落
本机 docker：本机 120/120 sweb.eval 是本地臂判分依赖（cb-judge.sh 本机 docker run），
且本机 pull 通道坏（D-30 未还）误删不可恢复。

保留集（三源并集；任一源读取失败/非法 JSON/盘点 ssh 2 次重试仍败 → fail-closed：
只出 plan 不 apply——删除不可逆，宁可不收）：
  A 在飞容器   ssh docker ps --format {{.Image}}。TOCTOU 三重重算：apply 开局重取并入、
               逐删候选 ancestor 过滤（docker ps -q --filter ancestor=）、rmi 循环内
               逐张再查后立即 rmi（单张窗口毫秒级）——10-22 人工实时避让换题容器的自动化。
  B mcode 在途 （DEB57-A0 2026-11-02 摘除：原根 /tmp/mcode-dispatch/state.json 属已退役
               链——factory-keepalive.py:81 退役登记含 mcode-dispatch（2026-10-26），
               此后 state.json 不再落盘（现盘上仅 deferred.log），B 源恒 FileNotFoundError
               → gather_keep fail-closed，img-gc-evidence.jsonl 2026-11-02 07:00:02 行
               实证：C 源摘除后仅剩此源仍令 plan/apply 永久拒走。MSTATE 置 None=如实
               空集（mcode 线已退役、在途集恒空）；对仍在册源的真缺失/坏 JSON 依旧
               fail-closed，语义不放宽；未来 mcode 线复役时重登记根即可）
               （原口径：本机 /tmp/mcode-dispatch/state.json 相位≠judged 的任务（在途
               口径同 10-22 人工 GC『28 任务中在盘 22 张』）→ /tmp/swev-s1/<tid>.json
               的 image 字段（cb-judge.sh:13 同款取法）；task json 缺失时 fallback
               keepalive 同款 _1776_ 拼法（factory-keepalive.py img_name）并记告警。
               禁止用 <tid> 字符串替换直接当镜像名——仓段含连字符（sphinx-doc/
               pylint-dev/pytest-dev/scikit-learn），替换名零匹配→必误删）
  C running 臂 （DEB57-A0 2026-11-02 摘除：原两对退役链根 /tmp/factory-status.json +
               /tmp/factory2-status.json 自 2026-10-29 起不在盘，C 源恒 fail-closed，
               img-gc-evidence.jsonl「保留集源失败」实证；现役调度器
               factory-scheduler.py 为 round 制、状态面无 running 臂/relay-image
               节点，C 源如实为空集——真实在跑保护由 A 源（anolis docker ps 在飞
               容器）承担。STATUS_FILES 保留为空表位，未来若有新 status/graph 对
               再登记）（原口径：两 status 文件 state=="running" 节点，relay-image
               取图 params.image 全名；bench-arm 取图 params.tasks → 任务镜像同 B
               解析；只保留 running，pending 臂由 relay 再供给——随退役链一并退役）

删集 = (ssh docker images 全量 − 保留集) ∩ 白名单。
白名单（硬编码）^swebench/sweb\.eval\.x86_64\.[a-z0-9_-]+_1776_.+:latest$
  【与派单正则的差异，实测勘误】派单版 [a-z0-9_]+ 不含连字符，对 2026-10-22 03:xx 现池
  仅 22/56 命中（sphinx-doc 等仓段含 '-' 的整族漏掉）；加 '-' 后 56/56 全命中，且
  `_1776_` 厂标（本机 feed 与 relay 同款构名）使其依旧排除 ollama/af-factory/<none> 等
  一切非本厂镜像（实测 foreign=0，规则不依赖『当前宿主干净』兜底未来）。
白名单外镜像只计数记证据行（foreign:<name>），永不 rmi。
build cache：仅 docker builder prune -f（10-22 实跑清 3.938GB 同款）。该命令是 Host 级
全量——接受理由=anolis build cache 全部源自本厂 af-bench 构建（--network host 固化在
af-bench）；不做 image prune -a、不碰 volume、不碰 /data/bench/{tb,vol}。
触发迟滞：/data use_pct ≥85 触发（keepalive gc_watch 本地读 latest.json 判断）；
apply 开局 ssh 现场复核 use_pct ≥88 → 停手只回报（第二道）。
人工停手：anolis:~/img-gc-HALT 哨兵存在即 apply 拒绝退出（test 判不准也拒绝——
fail-closed）；哨兵创建/移除须提前在巡检日志宣传。
rmi 失败不重试不 -f，逐张记 RMI-FAIL 进证据。
子进程纪律（被 keepalive gc_watch spawn 时）：flock 单飞锁（状态观测/img-gc.lock，
NB 拿不到即静默一行退出）+ 1200s 硬超时 SIGALRM 自杀留证据。

证据：JSONL 双写 /tmp/img-gc-evidence.jsonl（现场）+ 状态观测/img-gc-evidence.jsonl
（耐久，回滚与审计以此为准；两机 /tmp 均 tmpfs——D-24/D-25）。行带 ts(人读)+epoch
(机器)。keepalive 迟滞（上次成功 GC）与 A9 去重（last-alarm-ts）都读耐久件。

用法:
  img-gc.py plan  --host anolis    # 只读盘点：保留集 A/B/C 分源 + 删集 + foreign，不删
  img-gc.py apply --host anolis    # 三重重算后 rmi + builder prune；HALT/≥88/源失败/锁占用均拒绝路径
"""
import argparse
import fcntl
import json
import os
import re
import signal
import subprocess
import sys
import time

WS = "/home/pan-ding/workspace/agent黑灯工厂"
HOST = "anolis"                     # 唯一合法目标（本机 docker 绝不触碰）
SSH_PREFIX = ["ssh", "-o", "ConnectTimeout=10", HOST]
# DEB57-A0（2026-11-02）：原两对 status/graph 全是已退役链根（factory-sched.py 代与
# factory2 代），status 文件不在盘 → src_running_arms 恒 FileNotFoundError → C=None →
# gather_keep fail-closed、plan/apply 永久拒走（证据见 状态观测/img-gc-evidence.jsonl
# 2026-11-02 行）。置空 = C 源如实反映现役世界（无 running 臂），不再读退役根。
STATUS_FILES = []
TASKS_DIR = "/tmp/swev-s1"
# DEB57-A0（2026-11-02）：置 None=退役链根摘除（见头注 B 段）。src_mcode_intransit 见
# None 即如实返回空集；若指路径则缺失/坏 JSON 仍 fail-closed（原语义不变）。
MSTATE = None
EVIDENCE_TMP = "/tmp/img-gc-evidence.jsonl"
EVIDENCE_DURABLE = f"{WS}/状态观测/img-gc-evidence.jsonl"
LOCK_FILE = f"{WS}/状态观测/img-gc.lock"
HALT_SENTINEL = "~/img-gc-HALT"     # anolis $HOME 下（远程 shell 展开）
TRIGGER_PCT = 85                    # 触发线（keepalive 侧判；apply 内仅作记录）
STOP_PCT = 88                       # apply 停手线（现场复核）
SSH_RETRIES = 2                     # 盘点类读重试（sched :508-518 先例）
SSH_RETRY_WAIT = 15
SSH_TIMEOUT = 60
HARD_TIMEOUT_S = 1200               # 子进程硬超时自杀
BUILDER_PRUNE = True                # 仅 docker builder prune -f（Host 级全量，理由见头注）

WHITELIST = re.compile(r"^swebench/sweb\.eval\.x86_64\.[a-z0-9_-]+_1776_.+:latest$")


def now_s():
    return time.strftime("%F %T")


def ssh_run(args, timeout=SSH_TIMEOUT):
    """ssh anolis <args>。返回 CompletedProcess（不抛，除非本机 ssh 自身异常）。"""
    return subprocess.run(SSH_PREFIX + args, capture_output=True, text=True,
                          timeout=timeout, stdin=subprocess.DEVNULL)


def ssh_docker(args, retries=1, wait=SSH_RETRY_WAIT, timeout=SSH_TIMEOUT):
    """ssh anolis docker <args>，盘点类读可重试（间隔 15s，sched :508-518 先例）。
    返回 (ok, stdout, err)。rmi 等写操作调用方必须 retries=1（失败不重试）。"""
    err = ""
    for attempt in range(1, retries + 1):
        try:
            r = ssh_run(["docker"] + args, timeout=timeout)
            if r.returncode == 0:
                return True, r.stdout, ""
            err = f"rc={r.returncode} {(r.stderr or '').strip()[-200:]}"
        except Exception as e:  # ssh 超时/连接失败
            err = f"{type(e).__name__}: {e}"
        if attempt < retries:
            time.sleep(wait)
    return False, "", err


def data_use_pct():
    """anolis /data 使用率。返回 (pct|int|None, err)。"""
    try:
        r = ssh_run(["df", "-P", "/data"])
        for line in r.stdout.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 5 and parts[-1] == "/data":
                return int(parts[4].rstrip("%")), None
        return None, f"df 输出无 /data 行: {r.stdout[:120]!r}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def halt_present():
    """anolis:~/img-gc-HALT 哨兵。True=拒；False=放行；None=判不准（拒，fail-closed）。"""
    try:
        r = ssh_run(["test", "-f", HALT_SENTINEL], timeout=30)
    except Exception:
        return None
    if r.returncode == 0:
        return True
    if r.returncode == 1:
        return False
    return None


# ---------- 保留集三源 ----------

def src_inflight():
    """A：在飞容器镜像。"""
    ok, out, err = ssh_docker(["ps", "--format", "{{.Image}}"], retries=SSH_RETRIES)
    if not ok:
        return None, err
    return sorted({l.strip() for l in out.splitlines() if l.strip()}), None


def task_image(tid):
    """任务→镜像名：/tmp/swev-s1/<tid>.json 的 image 字段（cb-judge.sh:13 同款）；
    缺失 fallback keepalive _1776_ 拼法。返回 (image, fallback:bool)。"""
    try:
        with open(f"{TASKS_DIR}/{tid}.json") as f:
            img = json.load(f).get("image")
        if img:
            return img, False
    except Exception:
        pass
    repo = tid.split("__")[0]
    return (f"swebench/sweb.eval.x86_64.{repo.replace('/', '_1776_')}_1776_"
            f"{tid.split('__')[1]}:latest"), True


def src_mcode_intransit():
    """B：mcode 在途任务镜像（state 相位≠judged）。返回 (imgs|None, tids, fallbacks|None, err)。
    DEB57-A0（2026-11-02）：MSTATE=None（mcode 线已退役）→ 如实空集，不再读退役根。"""
    if MSTATE is None:
        return [], [], None, None
    try:
        with open(MSTATE) as f:
            st = json.load(f)
        if not isinstance(st, dict):
            raise ValueError("state 非字典")
    except Exception as e:
        return None, None, None, f"{MSTATE}: {e}"
    imgs, tids, fbs = set(), [], []
    for k, e in st.items():
        if isinstance(e, dict) and e.get("phase") != "judged":
            tid = k.split("|")[0]
            img, is_fb = task_image(tid)
            imgs.add(img)
            tids.append(tid)
            if is_fb:
                fbs.append(tid)
    return sorted(imgs), sorted(set(tids)), (sorted(fbs) or None), None


def src_running_arms():
    """C：两 status 文件 state=="running" 节点 → relay params.image / bench params.tasks
    →任务镜像。图只取 params（其 state 全 None，绝不读图运行态）。
    返回 (imgs|None, fallbacks|None, notes, err)。"""
    imgs, fbs, notes = set(), [], []
    for sf, gf in STATUS_FILES:
        try:
            with open(sf) as f:
                st = json.load(f)
            if not isinstance(st, dict):
                raise ValueError("status 非字典")
        except Exception as e:
            return None, None, notes, f"{sf}: {e}"
        try:
            with open(gf) as f:
                g = json.load(f)
            gparams = {n.get("id"): (n.get("params") or {})
                       for n in g.get("nodes", []) if isinstance(n, dict)}
        except Exception as e:
            return None, None, notes, f"{gf}: {e}"
        for nid, n in st.items():
            if nid == "_summary" or not isinstance(n, dict):
                continue
            if n.get("state") != "running":
                continue
            p = gparams.get(nid) or {}
            if n.get("kind") == "relay-image":
                img = p.get("image")
                if not img:
                    return None, None, notes, f"{sf}:{nid} relay running 但图缺 params.image"
                imgs.add(img)
            elif n.get("kind") == "bench-arm":
                tasks = p.get("tasks") or []
                for tid in tasks:
                    img, is_fb = task_image(tid)
                    imgs.add(img)
                    if is_fb:
                        fbs.append(tid)
                if not tasks:
                    notes.append(f"empty-tasks:{nid}")
            else:
                notes.append(f"unknown-running:{nid}:{n.get('kind')}")
    return sorted(imgs), (sorted(set(fbs)) or None), notes, None


def gather_keep():
    """三源并集。返回 (keep|None, parts{A,B,C}, meta, err)——任一硬源失败 keep=None。"""
    a, err_a = src_inflight()
    b, b_tids, b_fb, err_b = src_mcode_intransit()
    c, c_fb, c_notes, err_c = src_running_arms()
    meta = {"B_tids": b_tids, "B_fallback": b_fb, "C_fallback": c_fb, "C_notes": c_notes,
            "errors": [e for e in (err_a, err_b, err_c) if e]}
    if a is None or b is None or c is None:
        return None, {"A": a or [], "B": b or [], "C": c or []}, meta, \
            "; ".join(e for e in (err_a, err_b, err_c) if e)
    return sorted(set(a) | set(b) | set(c)), {"A": a, "B": b, "C": c}, meta, None


def split_inventory(inv, keep):
    """删集=(全量−保留)∩白名单；白名单外=foreign 只计数永不 rmi。inv 必须是镜像名列表。"""
    inv_set = set(inv)
    delete = sorted(i for i in inv_set - set(keep) if WHITELIST.match(i))
    foreign = sorted(i for i in inv_set - set(keep) if not WHITELIST.match(i))
    return delete, foreign


def parse_inv(stdout):
    """docker images --format 输出 → 镜像名列表（防 raw 字符串被 set() 拆成字符）。"""
    return sorted({l.strip() for l in (stdout or "").splitlines() if l.strip()})


def write_evidence(rec):
    """JSONL 双写（tmp 现场 + 耐久审计）。"""
    for path in (EVIDENCE_TMP, EVIDENCE_DURABLE):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "a") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"[img-gc] 证据写失败 {path}: {e}", file=sys.stderr)


def print_report(title, use_pct, parts, meta, delete, foreign, fail_closed):
    print(f"== img-gc {title} (host={HOST}) {now_s()} ==")
    print(f"/data use_pct: {use_pct if use_pct is not None else '判不准'}"
          f"（触发线 {TRIGGER_PCT} / 停手线 {STOP_PCT}）")
    print(f"保留集（并集 {len(set(parts['A']) | set(parts['B']) | set(parts['C']))}）:")
    print(f"  A 在飞容器 ({len(parts['A'])}): {parts['A']}")
    print(f"  B mcode在途 ({len(parts['B'])}): 任务={meta.get('B_tids')}")
    print(f"      镜像={parts['B']}")
    print(f"  C running臂 ({len(parts['C'])}): {parts['C']}")
    if meta.get("B_fallback") or meta.get("C_fallback"):
        print(f"  fallback(拼名告警): B={meta.get('B_fallback')} C={meta.get('C_fallback')}")
    if meta.get("C_notes"):
        print(f"  C备注: {meta['C_notes']}")
    print(f"删集 ({len(delete)}，100% 白名单内): {delete}")
    print(f"foreign 白名单外-永不rmi ({len(foreign)}): "
          f"{['foreign:' + x for x in foreign]}")
    print(f"fail-closed: {fail_closed or '无'}")


def _selfkill(signum, _frame):
    write_evidence({"kind": "apply", "ts": now_s(), "epoch": int(time.time()), "host": HOST,
                    "ok": False, "reason": f"hard-timeout-selfkill {HARD_TIMEOUT_S}s"})
    print(f"[img-gc] 硬超时 {HARD_TIMEOUT_S}s 自杀（证据已留）", file=sys.stderr)
    os._exit(9)


def acquire_lock():
    """flock 单飞（NB）。返回 fd 或 None（被占）。"""
    fd = open(LOCK_FILE, "w")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except OSError:
        fd.close()
        return None


def ancestor_busy(img):
    """TOCTOU(b)：删候选是否被在飞容器引用。判不准（ssh 失败）按 busy=拒删 fail-closed。"""
    ok, out, _err = ssh_docker(["ps", "-q", "--filter", f"ancestor={img}"], retries=1)
    if not ok:
        return True
    return bool(out.strip())


def cmd_apply(_args):
    # 硬超时自杀（先装，任何阶段卡死都留证据退出）
    signal.signal(signal.SIGALRM, _selfkill)
    signal.alarm(HARD_TIMEOUT_S)
    lock = acquire_lock()
    if lock is None:
        print("[img-gc] 单飞锁被占（已有 GC 在跑），本轮静默退出")
        return
    use_pct, err_pct = data_use_pct()
    inv_ok, inv_out, err_inv = ssh_docker(["images", "--format", "{{.Repository}}:{{.Tag}}"],
                                          retries=SSH_RETRIES)
    inv = parse_inv(inv_out) if inv_ok else []
    keep, parts, meta, err_keep = gather_keep()
    fail_closed = "; ".join(e for e in
                            ([f"/data use_pct 判不准: {err_pct}"] if err_pct else [])
                            + ([f"docker images 盘点失败: {err_inv}"] if not inv_ok else [])
                            + ([f"保留集源失败: {err_keep}"] if err_keep else []))
    delete, foreign = ([], []) if (fail_closed or keep is None) else split_inventory(inv, keep)
    halt = halt_present()
    print_report("apply(预检)", use_pct, parts, meta, delete, foreign, fail_closed)
    if halt is True:
        write_evidence({"kind": "apply", "ts": now_s(), "epoch": int(time.time()),
                        "host": HOST, "use_pct": use_pct, "ok": False,
                        "reason": "HALT 哨兵在场，拒绝执行（人工停手）",
                        "keep_counts": {k: len(v) for k, v in parts.items()},
                        "delete": delete, "foreign": foreign, "fail_closed": fail_closed})
        print("[img-gc] HALT 哨兵在场——apply 拒绝（不删任何镜像）")
        return
    if halt is None:
        write_evidence({"kind": "apply", "ts": now_s(), "epoch": int(time.time()),
                        "host": HOST, "use_pct": use_pct, "ok": False,
                        "reason": "HALT 哨兵判不准（fail-closed），拒绝执行",
                        "keep_counts": {k: len(v) for k, v in parts.items()},
                        "delete": delete, "foreign": foreign, "fail_closed": fail_closed})
        print("[img-gc] HALT 哨兵判不准——apply 拒绝（fail-closed）")
        return
    if fail_closed:
        write_evidence({"kind": "apply", "ts": now_s(), "epoch": int(time.time()),
                        "host": HOST, "use_pct": use_pct, "ok": False,
                        "reason": f"fail-closed 只出 plan 不 apply: {fail_closed}",
                        "keep_counts": {k: len(v) for k, v in parts.items()},
                        "delete": [], "foreign": foreign, "fail_closed": fail_closed})
        print("[img-gc] fail-closed——只出 plan 不 apply（删除不可逆，宁可不收）")
        return
    if use_pct is not None and use_pct >= STOP_PCT:
        write_evidence({"kind": "apply", "ts": now_s(), "epoch": int(time.time()),
                        "host": HOST, "use_pct": use_pct, "ok": False,
                        "reason": f"use_pct {use_pct}% ≥ 停手线 {STOP_PCT}%，只 plan 停手回报",
                        "keep_counts": {k: len(v) for k, v in parts.items()},
                        "delete": delete, "foreign": foreign})
        print(f"[img-gc] /data {use_pct}% ≥ {STOP_PCT}%——停手回报，不 apply")
        return
    # ---- TOCTOU(a)：重取在飞并入保留集，重算删集 ----
    a2, err_a2 = src_inflight()
    if a2 is None:
        write_evidence({"kind": "apply", "ts": now_s(), "epoch": int(time.time()),
                        "host": HOST, "use_pct": use_pct, "ok": False,
                        "reason": f"TOCTOU(a) 在飞重取失败: {err_a2}",
                        "keep_counts": {k: len(v) for k, v in parts.items()},
                        "delete": [], "foreign": foreign})
        print("[img-gc] TOCTOU(a) 在飞重取失败——放弃 apply（fail-closed）")
        return
    parts["A"] = sorted(set(parts["A"]) | set(a2))
    keep = sorted(set(parts["A"]) | set(parts["B"]) | set(parts["C"]))
    delete = sorted(i for i in set(delete) - set(keep) if WHITELIST.match(i))
    assert not (set(delete) & set(keep)), "删集与保留集相交（内部不变量破坏）"
    # ---- TOCTOU(b)：逐候选 ancestor 过滤 ----
    stage = []
    for img in delete:
        if ancestor_busy(img):
            stage.append({"image": img, "status": "skipped-ancestor-busy"})
        else:
            stage.append({"image": img, "status": "candidate"})
    # ---- TOCTOU(c)：逐张再查后立即 rmi（失败不重试不 -f） ----
    results, deleted = [], 0
    for ent in stage:
        img = ent["image"]
        if ent["status"] != "candidate":
            results.append(ent)
            continue
        if ancestor_busy(img):
            results.append({"image": img, "status": "skipped-ancestor-busy"})
            continue
        ok, _out, err = ssh_docker(["rmi", img], retries=1)
        st = "deleted" if ok else "rmi-fail"
        deleted += 1 if ok else 0
        results.append({"image": img, "status": st, "err": None if ok else err})
    # ---- build cache（Host 级全量，理由见头注）----
    ok_p, out_p, err_p = ssh_docker(["builder", "prune", "-f"], retries=1, timeout=600)
    use_pct2, _ = data_use_pct()
    rec = {"kind": "apply", "ts": now_s(), "epoch": int(time.time()), "host": HOST,
           "use_pct": use_pct, "use_pct_after": use_pct2,
           "keep_counts": {k: len(v) for k, v in parts.items()},
           "delete": [e["image"] for e in stage],
           "results": results, "deleted": deleted,
           "rmi_fail": sum(1 for r in results if r["status"] == "rmi-fail"),
           "skipped_ancestor": sum(1 for r in results if r["status"].startswith("skipped")),
           "builder_prune": "ok" if ok_p else f"fail: {err_p}",
           "foreign": foreign, "ok": True}
    write_evidence(rec)
    print(f"[img-gc] apply 完成：删 {deleted} / rmi-fail {rec['rmi_fail']} / "
          f"ancestor避让 {rec['skipped_ancestor']}；/data {use_pct}%→{use_pct2}%；"
          f"builder prune {rec['builder_prune']}（证据已双写）")


def cmd_plan(_args):
    use_pct, err_pct = data_use_pct()
    inv_ok, inv_out, err_inv = ssh_docker(["images", "--format", "{{.Repository}}:{{.Tag}}"],
                                          retries=SSH_RETRIES)
    inv = parse_inv(inv_out) if inv_ok else []
    keep, parts, meta, err_keep = gather_keep()
    fail_closed = "; ".join(e for e in
                            ([f"/data use_pct 判不准: {err_pct}"] if err_pct else [])
                            + ([f"docker images 盘点失败: {err_inv}"] if not inv_ok else [])
                            + ([f"保留集源失败: {err_keep}"] if err_keep else []))
    delete, foreign = ([], []) if (fail_closed or keep is None) else split_inventory(inv, keep)
    print_report("plan", use_pct, parts, meta, delete, foreign, fail_closed)
    write_evidence({"kind": "plan", "ts": now_s(), "epoch": int(time.time()), "host": HOST,
                    "use_pct": use_pct, "trigger": (use_pct or 0) >= TRIGGER_PCT,
                    "keep_counts": {k: len(v) for k, v in parts.items()},
                    "keep": parts, "B_tids": meta.get("B_tids"),
                    "delete": delete, "foreign": foreign, "fail_closed": fail_closed or None})
    if fail_closed:
        print("[img-gc] 存在 fail-closed 源失败——apply 将被拒绝（本轮仅盘点）")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "apply"):
        p = sub.add_parser(name)
        p.add_argument("--host", required=True, help=f"仅支持 {HOST}")
    a = ap.parse_args()
    if a.host != HOST:
        # 红线：绝不落本机 docker——本机 120/120 sweb.eval 是本地臂判分依赖且 D-30 未还
        sys.exit(f"img-gc 仅支持 --host {HOST}（收到 --host {a.host}；本机 docker 绝不触碰）")
    {"plan": cmd_plan, "apply": cmd_apply}[a.cmd](a)


if __name__ == "__main__":
    main()
