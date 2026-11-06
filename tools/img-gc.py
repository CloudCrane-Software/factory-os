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
  img-gc.py recover --host anolis  # D-113 分级恢复腿：只读评估 L1/L2/L3 + 候选清单+预估回收量报告件（零删）
  img-gc.py recover --host anolis --selftest  # 内置正/负例夹具自检（零 ssh、零删）
"""
import argparse
import fcntl
import json
import os
import re
import shlex
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


# ---------- D-113：/data 高水位分级恢复腿（夜轨C2 红队分诊 H3 · factory-os#81） ----------
# 病灶（卡面复核留证，2026-11-07 夜轨C2 分诊，全部命令重跑留证）：
#   img-gc-evidence.jsonl 354 行、峰值 use_pct=100（2026-11-04 13:30:57，reason=HALT
#   哨兵在场拒绝执行）；11-06 gc-alarm-sent 红 ×17，末条 message「删 0 张/rmi-fail 0，
#   /data 93%→None%，reason=use_pct 93% ≥ 停手线 88%，只 plan 停手回报」——停手线触顶后
#   **零自动恢复动作**；现值 /data 69%（anolis `df -P /data` 实测）而 93%→69% 回落无任何
#   img-gc/安灯留痕。/data=订单生产真值根（/data/bench/af-p3-state/orders 末条
#   A0897-report-glm-cp mtime 2026-11-05 23:17:03 实测）。
# 收口（卡面验收门）：停手线触顶后产出「可 GC 候选清单+预估回收量」**只读报告件**；
#   /data 回落（非 img-gc 路径）留痕安灯（factory-watch.py 专码腿，见该件 A10/A11）。
#   **不自动删**——≥88% 停手只回报的既有语义一字不动（凌晨纪律：只增不改、禁删既有行为）。
# 分级（三类，全部只增；既有 plan/apply 判定路径零改动）：
#   L1 白名单清理腿——硬编码白名单内的可删候选清单 + 预估回收量（只读报告件）
#   L2 腾挪建议报告——白名单外 / 人工裁定项，**不自动执行**
#   L3 只报警      ——L1/L2 无可安全回收项，或读数判不准（fail-closed 不猜绿）
RECOVERY_START_PCT = STOP_PCT       # 恢复腿启动线=停手线 88（双线同源，不另设闸）
RECOVERY_REPORT_DIR = f"{WS}/状态观测/img-gc-recovery"   # 只读报告件落点（耐久）
RECOVERY_ALARM_CODE = "gc-recovery"  # 安灯专码（落 alarms.log 的写入方=factory-watch.py）
RECOVERY_SCHEMA = "af.fos.img-gc.recovery.v1"
# L1 白名单（**硬编码，禁动态判定**）——三类：
#   ① dangling 镜像层：docker images -f dangling=true 的 <none> 层
#   ② 过期 warm-cache 超阈值副本：WARM_CACHE_ROOT 内 mtime 超 WARM_CACHE_TTL_S 的件
#   ③ 显式标记临时件：TEMP_MARKER_ROOT 内带 TEMP_MARKER_NAME 标记文件的目录
# 三类均以「白名单根 + 硬编码条件」双闸限定；根外路径一律排除（负例防线，见 --selftest）。
DANGLING_FMT = "{{.ID}}|{{.Repository}}:{{.Tag}}|{{.Size}}"
WARM_CACHE_ROOT = "/data/cache/warm"
WARM_CACHE_TTL_S = 7 * 86400
WARM_CACHE_TTL_DAYS = WARM_CACHE_TTL_S // 86400
TEMP_MARKER_ROOT = "/data/cache"
TEMP_MARKER_NAME = ".af-tmp-deletable"
RECOVERY_SCAN_MAXDEPTH = 3           # 白名单根扫描深度上限（禁递归全盘）
RECOVERY_SHELL_TIMEOUT = 120
AF_NO_ROOT = "__AF_NO_ROOT__"        # 白名单根不在盘的哨兵（如实空集，非 fail-closed）
_SIZE_UNIT_BYTES = {"B": 1, "KB": 10 ** 3, "MB": 10 ** 6, "GB": 10 ** 9, "TB": 10 ** 12,
                    "KIB": 2 ** 10, "MIB": 2 ** 20, "GIB": 2 ** 30, "TIB": 2 ** 40}
_SIZE_RE = re.compile(r"^([0-9]+(?:\.[0-9]+)?)\s*([A-Za-z]+)$")


def parse_size(text):
    """人读尺寸（docker images / df）→ 字节。判不准返回 None（不猜、不补默认值）。

    用 round 不用 int 截断：2.11GB 的 float 表示是 2109999999.9999998，int() 会
    少 1B（D-113 selftest T1 夹具实证）——预估回收量须逐 B 可对账。
    """
    m = _SIZE_RE.match((text or "").strip())
    if not m:
        return None
    unit = m.group(2).upper()
    if unit not in _SIZE_UNIT_BYTES:
        return None
    return int(round(float(m.group(1)) * _SIZE_UNIT_BYTES[unit]))


def ssh_shell(cmd, timeout=RECOVERY_SHELL_TIMEOUT):
    """ssh anolis <cmd>（白名单根只读盘点）。返回 (rc|None, stdout, err)。

    rc=远程命令退出码；rc=None=ssh 层失败（调用方按判不准 fail-closed）。
    远程 rc≠0 但**有 stdout 时判「部分可读」**（如 `du -s /data/*` 撞不可读条目
    即 rc=1 却吐得出一半清单——D-113 真跑实测）：由调用方决定采信哪些行，
    并把 rc≠0 记进 read_note，不吞、不假装全量。

    ★ cmd 必须作为**单个 argv 元素**下发：ssh 把远端命令按空格拼接后交远程
    `sh -c` 解析，包一层 `bash -lc` 会让 `if …; then …; fi` 被拆成多个词
    （D-113 真跑实测 rc=2 "error near unexpected token `then'"）。单元素下发
    则原样到达远程 sh，引号/管道/`\\t` 全部按本意生效。
    """
    try:
        r = ssh_run([cmd], timeout=timeout)
    except Exception as e:
        return None, "", f"{type(e).__name__}: {e}"     # ssh 层失败（判不准）
    return r.returncode, r.stdout or "", (r.stderr or "").strip()[-200:]


def qfmt(fmt):
    """docker --format 模板过远程 sh 引号（`|` 分隔符否则被远程 shell 当管道——
    D-113 真跑实测 rc=127 "{{.Size}}: command not found"）。"""
    return shlex.quote(fmt)


def scan_dangling_layers():
    """L1-① dangling 镜像层。返回 (items|None, err)——判不准 None（该项不进 L1）。"""
    ok, out, err = ssh_docker(["images", "-f", "dangling=true",
                               "--format", qfmt(DANGLING_FMT)], retries=SSH_RETRIES)
    if not ok:
        return None, err
    items = []
    for ln in out.splitlines():
        p = [x.strip() for x in ln.split("|")]
        if len(p) != 3:
            continue
        items.append({"class": "dangling-image-layer", "id": p[0], "name": p[1],
                      "size_bytes": parse_size(p[2]), "size_raw": p[2]})
    return items, None


def scan_expired_warm_cache(now):
    """L1-② 过期 warm-cache 副本（白名单根内、mtime 超阈）。返回 (items|None, err)。"""
    cmd = (f"if [ -d {WARM_CACHE_ROOT} ]; then "
           f"find {WARM_CACHE_ROOT} -mindepth 1 -maxdepth {RECOVERY_SCAN_MAXDEPTH} "
           f"-type f -mtime +{WARM_CACHE_TTL_DAYS} -printf '%s\\t%T@\\t%p\\n'; "
           f"else echo {AF_NO_ROOT}; fi")
    rc, out, err = ssh_shell(cmd)
    if rc is None:
        return None, err                     # ssh 层失败 = 判不准（该项不进 L1）
    if out.strip() == AF_NO_ROOT:
        return [], None                      # 白名单根不在盘 = 如实空集（非 fail-closed）
    note = None if rc == 0 else f"rc={rc}（部分可读，已按实际输出行采信）"
    items = []
    for ln in out.splitlines():
        p = ln.split("\t")
        if len(p) != 3:
            continue
        try:
            size, mtime = int(p[0]), float(p[1])
        except ValueError:
            continue
        ent = {"class": "expired-warm-cache", "path": p[2], "size_bytes": size,
               "age_s": int(now - mtime), "ttl_s": WARM_CACHE_TTL_S}
        if note:
            ent["read_note"] = note
        items.append(ent)
    return items, None


def scan_marked_temp_items():
    """L1-③ 显式标记临时件（TEMP_MARKER_ROOT 内带 TEMP_MARKER_NAME 标记的目录）。

    返回 (items|None, err)。**根外路径一律排除**（白名单外零删的负例防线）。
    """
    cmd = (f"if [ -d {TEMP_MARKER_ROOT} ]; then "
           f"find {TEMP_MARKER_ROOT} -maxdepth {RECOVERY_SCAN_MAXDEPTH} "
           f"-name {TEMP_MARKER_NAME} -printf '%h\\n' | sort -u; "
           f"else echo {AF_NO_ROOT}; fi")
    rc, out, err = ssh_shell(cmd)
    if rc is None:
        return None, err
    if out.strip() == AF_NO_ROOT:
        return [], None
    note = None if rc == 0 else f"rc={rc}（部分可读）"
    items, excluded = [], []
    for d in sorted({l.strip() for l in out.splitlines() if l.strip()}):
        if not d.startswith(TEMP_MARKER_ROOT + "/"):
            excluded.append(d)                # 白名单根外：只记录，永不进候选
            continue
        rc2, out2, err2 = ssh_shell(f"du -sb {d} 2>/dev/null | cut -f1")
        size = int(out2.strip()) if rc2 == 0 and out2.strip().isdigit() else None
        ent = {"class": "marked-temp-item", "path": d,
               "marker": f"{d}/{TEMP_MARKER_NAME}", "size_bytes": size,
               "size_err": None if size is not None else (err2 or f"rc={rc2}")}
        if note:
            ent["read_note"] = note
        items.append(ent)
    if excluded:
        print(f"[img-gc] L1-③ 标记件白名单外排除 {len(excluded)} 项（永不删）: {excluded}",
              file=sys.stderr)
    return items, None


def image_size_table():
    """docker images 尺寸表（name → size_bytes）。判不准返回 ({}, err)。"""
    ok, out, err = ssh_docker(["images", "--format",
                               qfmt("{{.Repository}}:{{.Tag}}|{{.Size}}")],
                              retries=SSH_RETRIES)
    if not ok:
        return {}, err
    sizes = {}
    for ln in out.splitlines():
        p = [x.strip() for x in ln.split("|")]
        if len(p) == 2 and parse_size(p[1]) is not None:
            sizes[p[0]] = parse_size(p[1])
    return sizes, None


def scan_data_topdirs():
    """/data 顶层条目尺寸（L2 腾挪建议的枚举面；只读）。返回 (items|None, err)。

    `du -s /data/*` 撞不可读条目（如 /data/lost+found）即 rc=1 却吐得出一半清单
    ——判「部分可读」：按实际输出行采信，rc≠0 记 read_note，不假装全量。
    """
    rc, out, err = ssh_shell("du -s --block-size=1 /data/* 2>/dev/null")
    if rc is None:
        return None, err
    note = None if rc == 0 else f"rc={rc}（部分可读，已按实际输出行采信）"
    items = []
    for ln in out.splitlines():
        p = ln.split("\t")
        if len(p) == 2 and p[0].strip().isdigit():
            ent = {"path": p[1].strip(), "size_bytes": int(p[0])}
            if note:
                ent["read_note"] = note
            items.append(ent)
    return sorted(items, key=lambda x: -x["size_bytes"]), None


def classify_recovery_tiers(use_pct, l1_n, l1_unknown, l2_n):
    """三级判定。返回 (tier|None, reason)。

    fail-closed：use_pct 判不准 ⇒ L3 只报警（不猜绿、不猜水位）；常水位 ⇒ None（不启动）。
    """
    if use_pct is None:
        return "L3", ("use_pct 判不准——L1/L2 均不可证，降级 L3 只报警（fail-closed）")
    if use_pct < RECOVERY_START_PCT:
        return None, (f"use_pct {use_pct}% < 恢复腿启动线 {RECOVERY_START_PCT}%"
                      f"——常水位读数，不启动恢复腿")
    if l1_n > 0:
        note = "（部分类判不准，已按不可证剔除，见 L1.partial_unknown）" if l1_unknown else ""
        return "L1", f"L1 白名单候选 {l1_n} 项{note}"
    if l2_n > 0:
        return "L2", "L1 无可安全回收项——升 L2 腾挪建议报告（不自动执行）"
    return "L3", "L1/L2 皆空——L3 只报警"


def assess_recovery(use_pct, now, delete=None, foreign=None):
    """分级恢复腿评估（**只读，零删**）。返回 assessment dict（含 L1/L2/L3 三段）。"""
    delete, foreign = list(delete or []), list(foreign or [])
    sizes, err_sizes = image_size_table()
    l1_images = [{"class": "whitelisted-image", "name": n, "size_bytes": sizes.get(n),
                  "size_err": None if sizes.get(n) is not None else err_sizes,
                  "note": "镜像白名单内候选；≥停手线不自动删，仍走既有 apply 通道"
                          "（HALT 解除且 use_pct<停手线）"}
                 for n in delete]
    dangling, err_d = scan_dangling_layers()
    warm, err_w = scan_expired_warm_cache(now)
    marks, err_m = scan_marked_temp_items()
    topdirs, err_t = scan_data_topdirs()
    l1_items = l1_images + (dangling or []) + (warm or []) + (marks or [])
    l1_unknown = [e for e in (err_sizes, err_d, err_w, err_m) if e]
    l1_est = sum(x["size_bytes"] for x in l1_items if x.get("size_bytes") is not None)
    l2_items = ([{"class": "foreign-image", "target": f,
                  "suggestion": "白名单外镜像——img-gc 永不 rmi；人工核定后另行走账"}
                 for f in foreign]
                + [{"class": "data-subtree", "path": d["path"],
                    "size_bytes": d["size_bytes"],
                    "suggestion": "非 img-gc 白名单面——腾挪/清理须人工裁定，本腿不执行"}
                   for d in (topdirs or [])])
    l2_unknown = [e for e in (err_t,) if e]
    tier, tier_reason = classify_recovery_tiers(use_pct, len(l1_items), l1_unknown,
                                                len(l2_items))
    return {"schema": RECOVERY_SCHEMA, "card": "D-113", "kind": "recovery",
            "ts": now_s(), "epoch": int(now), "host": HOST, "use_pct": use_pct,
            "lines": {"trigger_pct": TRIGGER_PCT, "stop_pct": STOP_PCT,
                      "recovery_start_pct": RECOVERY_START_PCT},
            "alarm_code": RECOVERY_ALARM_CODE, "tier": tier, "tier_reason": tier_reason,
            "auto_delete": False,
            "note": "本腿零删：≥停手线只产只读报告件；删除仍走既有 apply 通道"
                    "（HALT 解除且 use_pct<停手线）",
            "tiers": {
                "L1": {"title": "白名单清理（硬编码白名单；只读报告件，停手线内不自动删）",
                       "n": len(l1_items), "est_reclaim_bytes": l1_est,
                       "unsized_n": sum(1 for x in l1_items
                                        if x.get("size_bytes") is None),
                       "partial_unknown": l1_unknown, "candidates": l1_items},
                "L2": {"title": "腾挪建议报告（不自动执行）", "n": len(l2_items),
                       "items": l2_items, "unknown": l2_unknown},
                "L3": {"title": "只报警", "alarm": tier == "L3",
                       "reason": tier_reason if tier == "L3" else None},
            }}


def write_recovery_report(a):
    """只读报告件落专码目录（JSON；含候选清单+预估回收量）。失败返回 None。"""
    try:
        os.makedirs(RECOVERY_REPORT_DIR, exist_ok=True)
        path = os.path.join(RECOVERY_REPORT_DIR, f"recovery-{a['epoch']}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(a, f, ensure_ascii=False, indent=2)
        return path
    except Exception as e:
        print(f"[img-gc] 恢复报告件写失败: {e}", file=sys.stderr)
        return None


def write_recovery_evidence(a, report_path):
    """恢复腿证据行（img-gc-evidence.jsonl 双写；每动作留痕）。"""
    t = a["tiers"]
    rec = {"kind": "recovery", "card": "D-113", "ts": a["ts"], "epoch": a["epoch"],
           "host": HOST, "use_pct": a["use_pct"], "tier": a["tier"],
           "tier_reason": a["tier_reason"], "alarm_code": a["alarm_code"],
           "L1_n": t["L1"]["n"], "L1_est_reclaim_bytes": t["L1"]["est_reclaim_bytes"],
           "L1_partial_unknown": t["L1"]["partial_unknown"],
           "L1_candidates": [{"class": c["class"],
                              "target": c.get("name") or c.get("path") or c.get("id"),
                              "size_bytes": c.get("size_bytes")}
                             for c in t["L1"]["candidates"]],
           "L2_n": t["L2"]["n"], "L2_unknown": t["L2"]["unknown"],
           "report_path": report_path, "auto_delete": False, "ok": True}
    write_evidence(rec)
    return rec


def print_recovery_report(a, report_path):
    """人读候选清单+预估回收量（stdout）。"""
    t = a["tiers"]
    print(f"== img-gc 恢复腿 D-113 (host={HOST}) {a['ts']} ==")
    print(f"/data use_pct: {a['use_pct'] if a['use_pct'] is not None else '判不准'}"
          f"（停手线 {STOP_PCT} / 恢复腿启动线 {RECOVERY_START_PCT}）")
    print(f"有效档位: {a['tier'] or '不启动（常水位）'} —— {a['tier_reason']}")
    print(f"L1 白名单候选 {t['L1']['n']} 项，预估回收 "
          f"{t['L1']['est_reclaim_bytes']} B（未测尺寸 {t['L1']['unsized_n']} 项）:")
    for c in t["L1"]["candidates"]:
        tgt = c.get("name") or c.get("path") or c.get("id")
        print(f"  [{c['class']}] {tgt} → {c.get('size_bytes')} B")
    if t["L1"]["partial_unknown"]:
        print(f"  L1 判不准类（已按不可证剔除）: {t['L1']['partial_unknown']}")
    print(f"L2 腾挪建议 {t['L2']['n']} 项（不自动执行）:")
    for it in t["L2"]["items"][:20]:
        print(f"  [{it['class']}] {it.get('target') or it.get('path')} "
              f"→ {it.get('size_bytes')} B")
    if t["L2"]["n"] > 20:
        print(f"  …另 {t['L2']['n'] - 20} 项见报告件")
    print(f"L3 只报警: {t['L3']['alarm']}"
          + (f"（{t['L3']['reason']}）" if t["L3"]["reason"] else ""))
    print(f"报告件: {report_path}（只读；本腿零删，auto_delete={a['auto_delete']}）")


def run_recovery_leg(use_pct, delete=None, foreign=None):
    """D-113 分级恢复腿（只读；零删）。停手线触顶即产候选清单+预估回收量报告件。"""
    now = time.time()
    a = assess_recovery(use_pct, now, delete=delete, foreign=foreign)
    report_path = write_recovery_report(a)
    write_recovery_evidence(a, report_path)
    print_recovery_report(a, report_path)
    return a


# ---------- D-113 恢复腿内置正/负例夹具（--selftest；零 ssh、零网络、零删） ----------
# 夹具面（形态照抄 anolis 实盘 + 故意植入的白名单外负例）：
#   · 镜像 5 张：白名单内 2（sphinx-doc 仓段含连字符——派单正则勘误案同款）、
#     foreign 3（registry 前缀 docker.1ms.run/、ollama/、af-factory/）
#   · dangling 2 层；warm-cache 根不在盘（如实空集）；标记临时件 3 条，其中 2 条
#     **故意落在白名单根外**（/data/bench/…、/data/af-factory/…）——负例防线
#   · /data 顶层 3 条（L2 腾挪建议枚举面）
_FIX_DF = ("Filesystem     1024-blocks    Used Available Capacity Mounted on\n"
           "/dev/vdb1        308519744 214000000  94519744     100% /data\n")
_FIX_IMAGES_SIZED = "\n".join([
    "swebench/sweb.eval.x86_64.sphinx-doc_1776_sphinx-7462:latest|3.42GB",
    "swebench/sweb.eval.x86_64.pylint-dev_1776_pylint-1:latest|2.11GB",
    "docker.1ms.run/swebench/sweb.eval.x86_64.sphinx-doc_1776_sphinx-7462:latest|3.42GB",
    "ollama/llama3:latest|4.7GB",
    "af-factory/portal:1|122MB",
]) + "\n"
_FIX_IMAGES = "".join(l.split("|")[0] + "\n" for l in _FIX_IMAGES_SIZED.splitlines())
_FIX_DANGLING = ("sha256:deadbeef01|<none>:<none>|128MB\n"
                 "sha256:deadbeef02|<none>:<none>|64MB\n")
_FIX_MARKERS = ("/data/cache/tmp-run-42\n"                       # 白名单根内 → L1 候选
                "/data/bench/af-p3-state/orders/A0897\n"         # 白名单根外 → 必须排除
                "/data/af-factory/target-p3\n")                  # 白名单根外 → 必须排除
_FIX_TOPDIRS = ("64859934720\t/data/bench\n"
                "34359750656\t/data/swapfile\n"
                "22480719872\t/data/gh-runner-work\n")
_FIX_EST_L1 = 3420000000 + 2110000000 + 128000000 + 64000000 + 4096   # 5721644096


class _SSHMock:
    """selftest ssh 夹具：按 (谓词, stdout, rc) 回放，并记录全部调用（写操作断言用）。"""

    def __init__(self, script):
        self.script = script
        self.calls = []

    def __call__(self, args, timeout=SSH_TIMEOUT):
        self.calls.append(list(args))
        joined = " ".join(args)
        for pred, out, rc in self.script:
            if pred(joined, args):
                return subprocess.CompletedProcess(args, rc, out, "")
        return subprocess.CompletedProcess(args, 0, "", "")


def _mock_script(df=None):
    """夹具回放表（顺序即优先级：dangling / 带尺寸 images 先于裸 images）。"""
    df = _FIX_DF if df is None else df
    return [
        (lambda j, a: a[:1] == ["df"], df, 0),
        (lambda j, a: a[:1] == ["test"], "", 1),          # HALT 哨兵不在场
        (lambda j, a: "dangling=true" in j, _FIX_DANGLING, 0),
        (lambda j, a: "{{.Repository}}:{{.Tag}}|{{.Size}}" in j, _FIX_IMAGES_SIZED, 0),
        (lambda j, a: a[:2] == ["docker", "images"], _FIX_IMAGES, 0),
        (lambda j, a: a[:2] == ["docker", "ps"], "", 0),
        # 白名单根盘点经 ssh_shell 单元素下发（无 bash -lc 包装），谓词改按命令串匹配
        (lambda j, a: "-mtime" in j, AF_NO_ROOT, 0),
        (lambda j, a: TEMP_MARKER_NAME in j, _FIX_MARKERS, 0),
        (lambda j, a: "du -sb" in j, "4096\n", 0),
        (lambda j, a: "du -s --block-size=1" in j, _FIX_TOPDIRS, 0),
    ]


def recovery_selftest():
    """D-113 恢复腿内置正/负例夹具自检。rc=0 全绿；rc=1 有断言红；rc=2 夹具自身坏。"""
    import tempfile
    fails, passes = [], []

    def check(name, cond, detail=""):
        (passes if cond else fails).append((name, detail))

    # ---- T1 parse_size（正例 + 判不准不猜） ----------------------------------
    for text, want in (("3.42GB", 3420000000), ("122MB", 122000000),
                       ("64MB", 64000000), ("1.5TiB", 1649267441664),
                       ("512B", 512), ("2GiB", 2147483648)):
        check(f"T1 parse_size({text!r})", parse_size(text) == want,
              f"got {parse_size(text)} want {want}")
    for text in ("N/A", "", "12XB", None, "1.2.3GB"):
        check(f"T1 parse_size({text!r})→None（判不准不猜）", parse_size(text) is None,
              f"got {parse_size(text)!r}")

    # ---- T2 镜像白名单负例：foreign 永不进删集 -------------------------------
    inv = [l.strip() for l in _FIX_IMAGES.splitlines() if l.strip()]
    delete, foreign = split_inventory(inv, [])
    want_del = sorted(["swebench/sweb.eval.x86_64.sphinx-doc_1776_sphinx-7462:latest",
                       "swebench/sweb.eval.x86_64.pylint-dev_1776_pylint-1:latest"])
    check("T2 白名单内恰 2 张", delete == want_del, f"got {delete}")
    check("T2 foreign 恰 3 张", len(foreign) == 3, f"got {foreign}")
    check("T2 负例：foreign ∩ 删集 = ∅（白名单外零删）",
          not (set(foreign) & set(delete)), f"foreign={foreign}")

    # ---- T3 分级判定（含停手线边界与判不准降级） -----------------------------
    for pct, l1n, l2n, want in ((None, 0, 0, "L3"), (69, 0, 5, None),
                                (88, 1, 0, "L1"), (93, 2, 5, "L1"),
                                (93, 0, 5, "L2"), (93, 0, 0, "L3"), (100, 3, 9, "L1")):
        got, why = classify_recovery_tiers(pct, l1n, [], l2n)
        check(f"T3 classify(use_pct={pct},L1={l1n},L2={l2n})→{want}",
              got == want, f"got {got} ({why})")

    # ---- T4/T5/T6：mock ssh 全链（恢复腿只读 + apply 停手零删 + 常水位回归） --
    mock = _SSHMock(_mock_script())
    recs = []
    saved = {k: globals()[k] for k in ("ssh_run", "write_evidence", "LOCK_FILE",
                                       "RECOVERY_REPORT_DIR")}
    tmpdir = tempfile.mkdtemp(prefix="img-gc-selftest-")
    try:
        globals()["ssh_run"] = mock
        globals()["write_evidence"] = lambda rec: recs.append(rec)
        globals()["LOCK_FILE"] = os.path.join(tmpdir, "img-gc.lock")
        globals()["RECOVERY_REPORT_DIR"] = os.path.join(tmpdir, "recovery")

        # T4：停手线（100%）评估——L1 白名单内三类齐、白名单外零入选
        a = assess_recovery(100, 1000000.0, delete=delete, foreign=foreign)
        t = a["tiers"]
        classes = sorted({c["class"] for c in t["L1"]["candidates"]})
        check("T4 停手线有效档位=L1", a["tier"] == "L1", f"got {a['tier']} {a['tier_reason']}")
        check("T4 L1 三类齐（镜像/dangling/标记件）",
              classes == ["dangling-image-layer", "marked-temp-item",
                          "whitelisted-image"], f"got {classes}")
        targets = [c.get("name") or c.get("path") or c.get("id")
                   for c in t["L1"]["candidates"]]
        check("T4 负例：白名单外镜像零入选",
              not any(x in targets for x in foreign), f"targets={targets}")
        check("T4 负例：标记根外路径零入选（/data/bench、/data/af-factory）",
              not any(x.startswith("/data/bench") or x.startswith("/data/af-factory")
                      for x in targets), f"targets={targets}")
        check("T4 预估回收量=5721644096B（三件可测+标记件 4096B）",
              t["L1"]["est_reclaim_bytes"] == _FIX_EST_L1,
              f"got {t['L1']['est_reclaim_bytes']}")
        check("T4 L2 含 foreign 3 + /data 顶层 3（不自动执行）", t["L2"]["n"] == 6,
              f"got {t['L2']['n']}")
        check("T4 本腿零删（auto_delete=False）", a["auto_delete"] is False)

        # T5：停手线 apply —— 停手回报照旧，且**零 rmi / 零 builder prune**
        recs.clear()
        try:
            signal.alarm(0)
            cmd_apply(None)
        finally:
            signal.alarm(0)
        writes = [" ".join(c) for c in mock.calls]
        check("T5 负例：停手线 apply 零 rmi", not any("rmi" in w for w in writes),
              f"calls={writes}")
        check("T5 负例：停手线 apply 零 builder prune",
              not any("builder" in w or "prune" in w for w in writes), f"calls={writes}")
        stop = [r for r in recs if r.get("kind") == "apply"
                and "停手线" in str(r.get("reason"))]
        check("T5 停手回报证据照旧（ok=False）", len(stop) == 1, f"recs={recs}")
        recov = [r for r in recs if r.get("kind") == "recovery"]
        check("T5 停手线恢复腿证据已留痕", len(recov) == 1, f"recs={recs}")
        check("T5 恢复腿证据 auto_delete=False",
              bool(recov) and recov[0].get("auto_delete") is False)
        rp = os.path.join(tmpdir, "recovery")
        check("T5 只读报告件已落盘",
              bool(recov) and os.path.isfile(str(recov[0].get("report_path") or ""))
              and os.path.isdir(rp), f"report_path={recov and recov[0].get('report_path')}")

        # T6：常水位（69%）apply —— 既有行为零改动（白名单内照删、恢复腿不启动）
        mock = _SSHMock(_mock_script(df=_FIX_DF.replace("100% /data", "69% /data")))
        mock.calls.clear()
        recs.clear()
        globals()["ssh_run"] = mock
        try:
            signal.alarm(0)
            cmd_apply(None)
        finally:
            signal.alarm(0)
        writes = [" ".join(c) for c in mock.calls]
        rmis = [w for w in writes if " rmi " in f" {w} "]
        check("T6 常水位 apply 白名单内照删 2 张（既有行为零改动）", len(rmis) == 2,
              f"rmis={rmis}")
        check("T6 负例：常水位 rmi 仅限白名单内（零 foreign）",
              all(WHITELIST.match(w.split(" rmi ")[-1]) for w in rmis), f"rmis={rmis}")
        check("T6 负例：常水位零删白名单外路径",
              not any("/data/bench" in w or "/data/af-factory" in w or "prune" in w
                      for w in rmis), f"rmis={rmis}")
        check("T6 常水位恢复腿不启动（零 recovery 证据）",
              not any(r.get("kind") == "recovery" for r in recs), f"recs={recs}")
        check("T6 常水位 apply 成功证据照旧",
              any(r.get("kind") == "apply" and r.get("ok") for r in recs), f"recs={recs}")
    except Exception as e:  # 夹具自身坏 ⇒ rc=2（不可证不猜绿）
        import traceback
        traceback.print_exc()
        print(f"[img-gc] selftest 夹具异常（rc=2）：{type(e).__name__}: {e}", file=sys.stderr)
        return 2
    finally:
        globals().update(saved)
        try:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass

    for name, detail in fails:
        print(f"[RED] {name} ｜ {detail}", file=sys.stderr)
    print(f"=== D-113 恢复腿 selftest：{len(passes)} 过 / {len(fails)} 红"
          f"（负例=白名单外零删：foreign 镜像/标记根外路径/停手线零 rmi）===")
    return 1 if fails else 0


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
        # D-113（只增）：停手线触顶即启动分级恢复腿——产「可 GC 候选清单+预估回收量」
        # 只读报告件 + 证据行。**零删**：不自动删纪律与停手语义一字不动。
        run_recovery_leg(use_pct, delete=delete, foreign=foreign)
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
    # D-113（只增）：plan 触顶时同样产恢复腿只读报告件（人工演练/复跑面）
    if use_pct is not None and use_pct >= RECOVERY_START_PCT:
        run_recovery_leg(use_pct, delete=delete, foreign=foreign)


def cmd_recover(args):
    """D-113 分级恢复腿（只读盘点；零删）。--selftest 跑内置正/负例夹具。"""
    if args.selftest:
        return recovery_selftest()
    use_pct, err_pct = data_use_pct()
    inv_ok, inv_out, err_inv = ssh_docker(["images", "--format", "{{.Repository}}:{{.Tag}}"],
                                          retries=SSH_RETRIES)
    inv = parse_inv(inv_out) if inv_ok else []
    keep, parts, meta, err_keep = gather_keep()
    delete, foreign = ([], []) if keep is None else split_inventory(inv, keep)
    if err_pct or not inv_ok or err_keep:
        print("[img-gc] recover 读数不全（判不准类已按不可证剔除）: "
              f"{'; '.join(e for e in (err_pct, err_inv, err_keep) if e)}", file=sys.stderr)
    print(f"== img-gc recover 预检 {now_s()} == 保留集并集 "
          f"{len(set(parts['A']) | set(parts['B']) | set(parts['C']))}；"
          f"镜像白名单候选 {len(delete)}；foreign {len(foreign)}")
    return run_recovery_leg(use_pct, delete=delete, foreign=foreign)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "apply", "recover"):
        p = sub.add_parser(name)
        p.add_argument("--host", required=True, help=f"仅支持 {HOST}")
        if name == "recover":
            p.add_argument("--selftest", action="store_true",
                           help="内置正/负例夹具自检（零 ssh、零删）后退出")
    a = ap.parse_args()
    if a.host != HOST:
        # 红线：绝不落本机 docker——本机 120/120 sweb.eval 是本地臂判分依赖且 D-30 未还
        sys.exit(f"img-gc 仅支持 --host {HOST}（收到 --host {a.host}；本机 docker 绝不触碰）")
    rc = {"plan": cmd_plan, "apply": cmd_apply, "recover": cmd_recover}[a.cmd](a)
    if isinstance(rc, int) and rc != 0:
        sys.exit(rc)      # 仅 selftest 非零码上抛（plan/apply 返回 None，退出码不变）


if __name__ == "__main__":
    main()
