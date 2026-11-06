#!/usr/bin/env python3
# =============================================================================
# 旧 bench 退役观察期 · 跨天复核（红队 W2-C-14 修复件，2026-10-27）
#
# 背景：runbook §六-3 判据③「跨天中间复核（≥2026-10-27 01:05:52 同时点）」原无
# 属主、无排期、无记录——在役巡检面（obs-patrol cron）结构上只扫 af-bench 观测
# 事件流、主代理每小时巡检 10-24 已转事件驱动，两本台账在观察期 25h 内零条目，
# 检查点空过。本脚本即该复核的**自动属主载体**（systemd --user 定时器
# bench-retire-obs-review.timer 每日 09:10 触发、Persistent 补跑；本文件为
# 2026-10-27 补做件——空过的 01:05:52 检查点由本脚本立即补做并留痕）。
#
# 口径（runbook §六-3 权威定义；红队 W2-C-17 统一 2026-10-27）：
#   起算 = 2026-10-26 01:05:52；期满 = 2026-10-29 01:05:52（72h）
#   ① af 线订单照常 Closed+MES 4 行（经 af-order 正常下单核对）——未执行核验单
#     不得记达成、不得据「无订单=无事」空过（vacuously pass，红队 W2-C13 勘误）；
#   ② 旧链零复活（ps 无 factory-sched/cb-run/mcode-dispatch/d36p-proxy；
#     /tmp/factory{,2}.log、cb-run.log、mcode-dispatch heartbeat 持续静默；
#     MES line_id='bench' 持续 0 新行）；
#   ③ 跨天中间复核（≥2026-10-27 01:05:52 同时点）——本脚本。
#
# 本脚本零写业务状态、零删除——只读 + 追加一行 JSONL 到
# 状态观测/bench-retire-obs-review.jsonl（不存在则创建）。归档批（文件移
# 参考/legacy/）必须等本复核记录落地后执行（fixHint）。
#
# 期满终局（红队 W3-C-14 修复，2026-10-27）：now ≥ 期满（2026-10-29 01:05:52）
# 时本脚本不再产出「观察期内」日报，改为一次性终局记录（kind=…-final）：
#   ①systemctl --user stop+disable bench-retire-obs-review.timer（每日 09:10
#     定时器就此终止，不再无限重复）；
#   ②判据有未达成 → 升级人工处置（状态观测/alarms.log 追加 red 级
#     OBS-EXPIRE 记录），不得静默收场；
#   ③终局记录幂等：jsonl 已有终局行时重跑不重复落行/不重复停表。
# 判定核心 evaluate() 纯函数化（时间与采样面注入），测试见
# tools/test-bench-retire-obs-review.py。
#
# 判据面扩展（红队 W3-C11/C13 修复，2026-10-27）：
#   W3-C13——判据①订单核验按订单记录：候选单经 ledger.jsonl 核
#   create_order 时间（判定核验单）与 close op + state_after=Closed 终态，
#   经 mes-events.jsonl 核四类跃迁 kind 集合恰含 release/start/complete/close；
#   目录 mtime 口径废除（订单目录在 MES 事件后仍被写——F5c 实证 mtime
#   22:03 晚于末条事件 14:08，起算后任何触碰即把旧单误计「新订单」）。
#   W3-C11——复核面增采 状态观测/alarms.log 与 /tmp 头寸：未知 red/amber
#   码一律判负（20:34:03 red 级 ch-mes-timeout 实发前复核面零感知）、A4L:tmp
#   低于闸线 2252MiB 判负（W2-C18 勘误：/tmp 头寸自登记起为观察期硬判据，
#   不再是「既有环境灯」）、A0/A7 为登记预期灯（退役执行记录 §三-2 +
#   W2-C19 勘误）只入台账不判负；采样失败一律 fail-closed（不明不谎报）。
#   判据面扩展测试见 tools/test-bench-retire-obs-review-criteria.py。
# =============================================================================
import base64
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

WS = "/home/pan-ding/workspace/agent黑灯工厂"
OUT = os.path.join(WS, "状态观测", "bench-retire-obs-review.jsonl")
ORDERS_DIR = os.path.join(WS, "af-state", "orders")
ALARMS_PATH = os.path.join(WS, "状态观测", "alarms.log")

# OBS-D4（2026-10-31）：判据①扫描根对齐生产真值根。旧根=本地 af-state/orders
# （15 单 F 系，2026-10-25 22:03 后冻结），与生产 ledger 根脱节（收口 20261029
# §附-1：采集面不见生产真值）。生产真值根=anolis /data/bench/af-p3-state/orders
# （2026-10-31 实测 1032 单、当日 A0889-report-glm-cp 在飞落账 10:50:01 +0800）。
# ssh 别名 anolis=pan-ding@anolis-host.invalid（~/.ssh/config；收口所记「anolis=root@
# gov-host.invalid」与本环境不符，见 OBS-D4 判据件登记）。缺省扫描面改读真值根（ssh
# 只读）；显式传本地目录仍走本地（测试/历史复核兼容，不改旧签名语义）。
PROD_ORDERS_HOST = "anolis"
PROD_ORDERS_DIR = "/data/bench/af-p3-state/orders"
SSH_PROD = ["ssh", "-o", "ConnectTimeout=8", "-o", "BatchMode=yes", PROD_ORDERS_HOST]
# OBS-D4 整改二轮（2026-10-31 复核后）：收口 §附-1 所述脱节含**两个**真值根——
#   ①生产根 anolis:/data/bench/af-p3-state/orders（现行在跑产线）；
#   ②窗内实质单根 ~/af-f6-order/state/orders/（本机，F6 10:47 失败 / F6b 10:57→12:02
#     Closed，收口 §八 取证面列其为「判据①实质证据」）。
# 首轮整改只对齐了 ①，②这 1 张窗内 Closed+四跃迁单仍不在扫描面（复核 issue 1）。
# 本地根实测在盘：2 单（F6-graph-sympy-20438-glm-cp、F6b-graph-matplotlib-25122-glm-cp，
# 目录 mtime 2026-10-27 11:57:53）。扫描面改为**多根**：远程生产根 ∪ 本地 f6 根。
LOCAL_F6_ORDERS_DIR = os.path.expanduser("~/af-f6-order/state/orders")

OBS_START = "2026-10-26 01:05:52"      # runbook §六-3 权威起算
OBS_END = "2026-10-29 01:05:52"        # 期满（72h）
MID_CHECKPOINT = "2026-10-27 01:05:52"  # 判据③跨天中间复核同时点

# 判据②旧链进程名（ps -o args= 扫描，排除本脚本与 grep 自身）。
OLD_CHAIN = ("factory-sched", "cb-run", "mcode-dispatch", "d36p-proxy")
# 判据②静默面：/tmp 日志与 mcode-dispatch 心跳。
TMP_LOGS = ("/tmp/factory.log", "/tmp/factory2.log", "/tmp/cb-run.log",
            "/tmp/mcode-dispatch.log")
MCODE_HEARTBEAT = "/tmp/mcode-dispatch/heartbeat"
# 判据②远端残留进程枚举（红队 W2-C-18）：anolis 侧退役判分批诊断包装失明面。
ANOLIS = "anolis"
ANOLIS_RESIDUE_PAT = "ctw3|mcode-ct-w3"

# 判据 2b 安灯/头寸面（红队 W3-C11）：闸线/校准线取 A4L 告警文案自述值
# （「可用 N MiB<2662MiB（usrquota 校准线，闸线 2252MiB，低于则 sched/mcode
# 拦新臂/新判分）」）——硬判据线 = 闸线 2252MiB。
TMP_GATE_MIB = 2252
TMP_CALIBRATED_MIB = 2662
# 登记预期灯（退役必然结果，只入台账不判负）：A7=已退役 image-feed 镜像停滞
# （永不自清，W2-C19 勘误登记）。A4L:* 不在预期灯列（W2-C18 勘误：观察期硬判据）。
# af-execline-idle 入列（OBS-D2 分治④，2026-10-31，授权=观察期收口-20261029.md:67）：
# 订单驱动面按设计「空闲≠故障、只报警不拉起」（factory-keepalive.py check_af_execline/
# fix_af_execline 注释原文），无 af-order/af-execline 进程且订单 ledger 心跳超 72h
# 即报 amber——恢复=经 af-order 正常下单，属预期状态登记非异常。
# A0 摘除（DEB57-A0，2026-11-02）：原「已退役调度器状态停更预期灯（§三-2 登记）」
# 的登记前提是假的——现役调度器 tools/factory-scheduler.py 从未退役，停更的是退役
# 链根 /tmp/factory-status.json；watch 判活面读退役根打 A0 假红 267 条，全被本灯
# 吞为预期、永不复核。watch 判活面已同日改读现役状态根（factory-watch.py
# SCHED_STATUS=状态观测/factory-scheduler-state.json），A0 回归真实判据灯：
# alarms.log 再现 A0 即调度器真死/真停更，必须判负。
EXPECTED_LAMPS = {
    "A7": "已退役 image-feed 镜像停滞预期灯（永不自清，W2-C19 勘误登记）",
    "af-execline-idle": "af 执行面空闲预期灯（订单驱动型按设计不自动拉起、空闲≠故障，"
                        "恢复=经 af-order 正常下单；OBS-D2 分治④ 2026-10-31 登记）",
}

# RT-E28 机制③（2026-11-05 波次B·B2 链落地）：预期灯**到期复核**——记账增「首见时间/
# 连续时长」；连续命中超阈（默认 24h）强制**升级出预期集**（命中条目改入 unexpected，
# 带 escalated_from 标记）⇒ 人工复核，失实成因不得被预期灯无限期吞没。
EXPECTED_LAMP_ESCALATE_S = 24 * 3600     # 到期升级阈（24h）
EXPECTED_LAMP_GAP_S = 3600               # 连续时长判定：相邻命中间隔容差（60min）
EXPECTED_LAMP_ESCALATE_EXEMPT = {
    # 豁免只登记既有勘误，不得新增豁免吸收真实缺口（登记面=30-工件/观测面清偿批-
    # 20261105/gate-registry.json 的 expected_lamp_aging.exempt）。
    "A7": "已退役 image-feed 镜像停滞预期灯（永不自清，W2-C19 勘误登记）——到期升级不适用",
}


def _ts_epoch(ts):
    """ts（'YYYY-MM-DD HH:MM:SS'）→ epoch；不可解析返回 None。"""
    if not isinstance(ts, str):
        return None
    try:
        return time.mktime(time.strptime(ts, "%Y-%m-%d %H:%M:%S"))
    except ValueError:
        return None


def lamp_aging(ts_list):
    """预期灯到期记账：首见时间 + 最长连续时长（相邻命中间隔 ≤ 容差视为连续）。"""
    stamps = [e for e in (_ts_epoch(t) for t in ts_list) if e is not None]
    if not stamps:
        return {"first_seen": None, "last_seen": None, "continuous_s": 0}
    stamps.sort()
    best_start = best_end = stamps[0]
    cur_start = cur_end = stamps[0]
    for s in stamps[1:]:
        if s - cur_end <= EXPECTED_LAMP_GAP_S:
            cur_end = s
        else:
            cur_start = cur_end = s
        if cur_end - cur_start > best_end - best_start:
            best_start, best_end = cur_start, cur_end
    fmt = "%Y-%m-%d %H:%M:%S"
    return {"first_seen": time.strftime(fmt, time.localtime(stamps[0])),
            "last_seen": time.strftime(fmt, time.localtime(stamps[-1])),
            "span_s": int(stamps[-1] - stamps[0]),
            "continuous_s": int(best_end - best_start)}
# 判据①四类跃迁 kind（W3-C13：mes-events kind 集合恰含四类）。
MES_KINDS_REQUIRED = ("release", "start", "complete", "close")


def mes_conn(url=None):
    """MES ClickHouse 连接 → (base_url, auth_header)。与 factory-keepalive/
    bench-mes 同款解析：0600 凭据文件 ~/.config/mes-ch/url（口令不落明文）。"""
    if url is None:
        url = os.environ.get("MES_CH_URL")
    if not url:
        try:
            with open(os.path.expanduser("~/.config/mes-ch/url"), encoding="utf-8") as f:
                url = f.read().strip()
        except OSError:
            url = "http://mes-host.invalid:15221"
    auth = None
    if "@" in url:
        scheme, rest = url.split("://", 1)
        userinfo, hostpart = rest.split("@", 1)
        url = f"{scheme}://{hostpart}"
        auth = "Basic " + base64.b64encode(userinfo.encode()).decode()
    return url, auth


def ch_count(sql, timeout=8):
    """GET {url}/?query=<SELECT count() …> → int；失败返回 None（不明即不谎报）。"""
    url, auth = mes_conn()
    req = urllib.request.Request(f"{url}/?query={urllib.parse.quote(sql)}")
    if auth:
        req.add_header("Authorization", auth)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode().strip()
    except (urllib.error.URLError, OSError, ValueError):
        return None
    try:
        return int(body)
    except ValueError:
        return None


def ps_hits():
    """旧链进程扫描：ps -o pid=,args= 全表，命中 OLD_CHAIN 任一名即列（去自重）。
    排除本脚本自身命令行（含工具名，防自咬）。"""
    try:
        out = subprocess.run(["ps", "-o", "pid=,args=", "-ww"],
                             capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None  # 扫描失败=不明，不谎报零复活
    me = os.path.abspath(__file__)
    hits = []
    for line in out.splitlines():
        line = line.strip()
        if not line or "bench-retire-obs-review" in line:
            continue
        for name in OLD_CHAIN:
            if re.search(rf"(^|/|\s){re.escape(name)}(\.py)?(\s|$)", line):
                hits.append(line)
                break
    return hits


def anolis_residue_hits():
    """anolis 侧退役判分批残留进程枚举（W2-C18）：ssh pgrep -af。None=ssh 失败
    （不明即不谎报零残留）；[]=零残留。"""
    try:
        out = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=8", "-o", "BatchMode=yes", ANOLIS,
             f"pgrep -af '{ANOLIS_RESIDUE_PAT}' || true"],
            capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    return [l for l in out.splitlines() if l.strip() and "pgrep -af" not in l]


def mtime_iso(path):
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S",
                             time.localtime(os.path.getmtime(path)))
    except OSError:
        return None


def since_start_epoch():
    return time.mktime(time.strptime(OBS_START, "%Y-%m-%d %H:%M:%S"))


def ms_iso(ms):
    """epoch 毫秒 → 本地「YYYY-MM-DD HH:MM:SS」；None/坏值原样 None。"""
    if not isinstance(ms, int) or ms <= 0:
        return None
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ms / 1000))


def list_order_candidates(orders_dir=None):
    """判据①候选面：订单目录名全集（**多根**）。
    None=不可读（不明即不谎报；核验单判定交 verify_orders_records* 逐单核记录）。
    OBS-D4（2026-10-31 首轮）：orders_dir=None 缺省改读生产真值根
    anolis:/data/bench/af-p3-state/orders（ssh 只读 find，超时 20s）。
    OBS-D4（2026-10-31 整改二轮·复核 issue 1）：扫描面须覆盖收口 §附-1 所述**两个**
    真值根 —— ①生产根（ssh）+ ②窗内实质单根 ~/af-f6-order/state/orders（本机）。
    缺省=①∪②（两根皆不可读 → None fail-closed；其一不可读 → 用其余可读根并在
    row 记来源，来源缺失不谎报「无单」）；显式传目录则只读该本地目录（测试/历史
    复核兼容，原 os.listdir 语义逐字不变）。"""
    if orders_dir is not None:
        try:
            return sorted(
                name for name in os.listdir(orders_dir)
                if os.path.isdir(os.path.join(orders_dir, name)))
        except OSError:
            return None
    names = set()
    any_root_ok = False
    cmd = (f"find {shlex.quote(PROD_ORDERS_DIR)} -mindepth 1 -maxdepth 1 "
           f"-type d -printf '%f\\n'")
    try:
        r = subprocess.run(SSH_PROD + [cmd], capture_output=True, text=True,
                           timeout=20, stdin=subprocess.DEVNULL)
        if r.returncode == 0:
            any_root_ok = True
            names.update(l for l in r.stdout.splitlines() if l.strip())
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        for name in os.listdir(LOCAL_F6_ORDERS_DIR):
            if os.path.isdir(os.path.join(LOCAL_F6_ORDERS_DIR, name)):
                any_root_ok = True
                names.add(name)
    except OSError:
        pass
    if not any_root_ok:
        return None
    return sorted(names)


def _order_entry_parse(name, ledger_text, mes_text):
    """逐单判定核心（OBS-D4 20261031 从 verify_orders_records 原样拆出，语义
    逐字不变）：ledger_text/mes_text 为两文件全文，None=不可读（fail-closed）。
    - ledger.jsonl：首条 op=create_order 的 ts_ms = 订单创建时间（核验单判定
      依据——目录 mtime 在 MES 事件后仍被写，已废除）；存在 op=close 且
      ok=true 且 state_after=Closed ⇒ Closed 终态；
    - mes-events.jsonl：kind 集合恰含 release/start/complete/close 四类跃迁。
    ledger 不可读/空 ⇒ verifiable=False（不可凭目录存在记达成——fail-closed）。"""
    entry = {"name": name, "verifiable": False, "created_at": None,
             "created_ms": None, "closed": False, "closed_at": None,
             "last_state": None, "mes_kinds": [], "mes_kinds_ok": False}
    ops = None
    if ledger_text is not None:
        try:
            ops = [json.loads(line)
                   for line in ledger_text.splitlines() if line.strip()]
        except ValueError:
            ops = None
    if not ops:
        return entry
    entry["verifiable"] = True
    for op in ops:
        if op.get("op") == "create_order" and entry["created_ms"] is None:
            entry["created_ms"] = op.get("ts_ms")
            entry["created_at"] = ms_iso(op.get("ts_ms"))
        if op.get("op") == "close":
            entry["closed"] = (op.get("ok") is True
                               and op.get("state_after") == "Closed")
            entry["closed_at"] = ms_iso(op.get("ts_ms"))
        if op.get("state_after") is not None:
            entry["last_state"] = op.get("state_after")
    kinds = []
    if mes_text is not None:
        for line in mes_text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                kind = json.loads(line).get("kind")
            except ValueError:
                continue
            if kind is not None:
                kinds.append(kind)
    entry["mes_kinds"] = kinds
    entry["mes_kinds_ok"] = set(kinds) == set(MES_KINDS_REQUIRED)
    return entry


def verify_orders_records(names, orders_dir=None):
    """逐候选单核订单记录。
    OBS-D4 整改二轮（复核 issue 3）：orders_dir 缺省（None）→ 走**多根**真值核验
    （远程生产根 ∪ 本地 f6 根），与默认候选面同根——旧版缺省=本地 ORDERS_DIR，
    故判据件 J1.5 写的 `verify_orders_records(['A0889-report-glm-cp'])` 返回
    verifiable=false（判据文本与实测命令不一致）。显式传目录则只读该本地目录
    （测试与历史复核走此入口，语义不变）。
    本地目录版判据（红队 W3-C13）：ledger.jsonl 首条 op=create_order 的 ts_ms
    = 创建时间；存在 op=close 且 ok=true 且 state_after=Closed ⇒ Closed 终态；
    mes-events.jsonl kind 集合恰含 release/start/complete/close 四类跃迁；
    ledger 不可读/空 ⇒ verifiable=False（fail-closed）。"""
    if orders_dir is None:
        return verify_orders_records_anywhere(names)
    rows = []
    for name in names:
        d = os.path.join(orders_dir, name)
        ledger_text = None
        mes_text = None
        try:
            with open(os.path.join(d, "ledger.jsonl"), encoding="utf-8") as fh:
                ledger_text = fh.read()
        except OSError:
            ledger_text = None
        if ledger_text is not None:
            try:
                with open(os.path.join(d, "mes-events.jsonl"),
                          encoding="utf-8") as fh:
                    mes_text = fh.read()
            except OSError:
                mes_text = None
        rows.append(_order_entry_parse(name, ledger_text, mes_text))
    return rows


def _ssh_cat_orders_file(names, rel):
    """ssh 单次往返批量读生产真值根候选单的指定文件（OBS-D4）：
    `cd <真值根> && for 循环`，`==NAME` 行分隔，目录存在性以 `__DIR_YES__`/
    `__DIR_NO__` 标记（整改二轮：须区分「远程无此单」与「远程有此单但该文件空」
    ——前者才回退本地 f6 根）。→ dict name→(exists: bool, text|None)；
    ssh 整体失败 → None。超时 90s（候选单 1000+ 量级一次往返；DEB-1 超时纪律）。"""
    script = (f"cd {shlex.quote(PROD_ORDERS_DIR)} || exit 9\n"
              f"for n in {' '.join(shlex.quote(n) for n in names)}; do\n"
              f"  echo \"==$n\"\n"
              f"  if [ -d \"$n\" ]; then\n"
              f"    echo \"__DIR_YES__\"\n"
              f"    cat \"$n/{rel}\" 2>/dev/null || true\n"
              f"  else\n"
              f"    echo \"__DIR_NO__\"\n"
              f"  fi\n"
              f"done")
    try:
        r = subprocess.run(SSH_PROD + [script], capture_output=True, text=True,
                           timeout=90, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    out = {n: (False, None) for n in names}
    cur = None
    buf = []
    exists = False
    for line in r.stdout.splitlines(keepends=True):
        head = line.rstrip("\n")
        if head.startswith("==") and head[2:] in out:
            if cur is not None:
                out[cur] = (exists, "".join(buf))
            cur = head[2:]
            buf = []
            exists = False
        elif head == "__DIR_YES__":
            exists = True
        elif head == "__DIR_NO__":
            exists = False
        elif cur is not None:
            buf.append(line)
    if cur is not None:
        out[cur] = (exists, "".join(buf))
    return out


def verify_orders_records_remote(names):
    """生产真值根（远程）逐单核记录（OBS-D4 首轮生产接线版）：判定核心与本地版
    同函数（_order_entry_parse），仅读根= anolis:/data/bench/af-p3-state/orders。
    ssh 整体失败 → 全单 verifiable=False（保守列入，fail-closed 同本地
    ledger 不可读路径；不明即不谎报达成）。"""
    led = _ssh_cat_orders_file(names, "ledger.jsonl")
    if led is None:
        return [_order_entry_parse(n, None, None) for n in names]
    mes = _ssh_cat_orders_file(names, "mes-events.jsonl")
    if mes is None:
        mes = {n: (False, None) for n in names}
    return [_order_entry_parse(n, led[n][1], mes[n][1]) for n in names]


def verify_orders_records_anywhere(names):
    """**多根**逐单核记录（OBS-D4 整改二轮·复核 issue 1/2 的扫描面完整实现）：
    判据①候选面所覆盖的每个根都参与核验——①远程生产根（anolis:
    /data/bench/af-p3-state/orders）+ ②本机窗内实质单根（~/af-f6-order/state/
    orders，含 F6b 这 1 张窗内 Closed+四跃迁单）。
    逐单归属判定：远程根有此单 → 取远程；远程无此单 → 查本地 f6 根；
    两根皆无 → 该单不可核（verifiable=False，fail-closed）。
    判定核心与本地版同函数（_order_entry_parse），严格语义零改动。"""
    led = _ssh_cat_orders_file(names, "ledger.jsonl")
    mes = _ssh_cat_orders_file(names, "mes-events.jsonl")
    if led is None:                      # ssh 整体失败 → 仍可只用本地根
        led = {n: (False, None) for n in names}
    if mes is None:
        mes = {n: (False, None) for n in names}
    rows = []
    for n in names:
        if led[n][0]:
            rows.append(_order_entry_parse(n, led[n][1], mes[n][1]))
            continue
        d = os.path.join(LOCAL_F6_ORDERS_DIR, n)
        ledger_text = mes_text = None
        if os.path.isdir(d):
            try:
                with open(os.path.join(d, "ledger.jsonl"), encoding="utf-8") as fh:
                    ledger_text = fh.read()
            except OSError:
                ledger_text = None
            try:
                with open(os.path.join(d, "mes-events.jsonl"),
                          encoding="utf-8") as fh:
                    mes_text = fh.read()
            except OSError:
                mes_text = None
        rows.append(_order_entry_parse(n, ledger_text, mes_text))
    return rows


def read_alarms(path=ALARMS_PATH, start_epoch=None):
    """状态观测/alarms.log JSONL 采样，取 ts ≥ start_epoch 的行（红队 W3-C11）。
    返回 list[dict]；坏行跳过（容忍）；文件不可读 = None（不明即不谎报）。"""
    if start_epoch is None:
        start_epoch = since_start_epoch()
    rows = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                ts = row.get("ts")
                if not isinstance(ts, str):
                    continue
                try:
                    epoch = time.mktime(
                        time.strptime(ts, "%Y-%m-%d %H:%M:%S"))
                except ValueError:
                    continue
                if epoch >= start_epoch:
                    rows.append(row)
    except OSError:
        return None
    return rows


def tmp_capacity_mib(path="/tmp"):
    """/tmp 容量采样（红队 W3-C11）：→ (free_mib, total_mib)；失败 None。"""
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return None
    return (usage.free // (1024 * 1024), usage.total // (1024 * 1024))


def classify_alarms(entries):
    """告警面分拣（红队 W3-C11）：预期灯（A0/A7）计数入台账；A4L:* 提取
    「可用 N MiB」并标出低于闸线者；其余码（red/amber 皆然）一律异常。"""
    expected = {code: {"count": 0, "last_ts": None, "note": note,
                       "first_seen": None, "continuous_s": 0,
                       "escalated": False, "escalate_reason": None,
                       "escalated_hits": 0}
                for code, note in EXPECTED_LAMPS.items()}
    a4l, a4l_below_gate, unexpected = [], [], []
    escalated = []
    exp_rows = {}
    for row in entries:
        code = str(row.get("code", ""))
        if code in EXPECTED_LAMPS:
            expected[code]["count"] += 1
            expected[code]["last_ts"] = row.get("ts")
            exp_rows.setdefault(code, []).append(row)
        elif code.startswith("A4L"):
            match = re.search(r"可用 (\d+) MiB", str(row.get("message", "")))
            avail = int(match.group(1)) if match else None
            item = {"ts": row.get("ts"), "code": code, "avail_mib": avail}
            a4l.append(item)
            if avail is not None and avail < TMP_GATE_MIB:
                a4l_below_gate.append(item)
        else:
            unexpected.append({k: row.get(k)
                               for k in ("ts", "level", "code", "message")})
    # 到期复核（RT-E28 机制③）：首见/连续时长记账 + 超阈升级出预期集人工复核。
    for code, rows in exp_rows.items():
        aging = lamp_aging([r.get("ts") for r in rows])
        expected[code]["first_seen"] = aging["first_seen"]
        expected[code]["continuous_s"] = aging["continuous_s"]
        over_span = aging["span_s"] >= EXPECTED_LAMP_ESCALATE_S
        over_cont = aging["continuous_s"] >= EXPECTED_LAMP_ESCALATE_S
        if (over_span or over_cont) and code not in EXPECTED_LAMP_ESCALATE_EXEMPT:
            expected[code]["escalated"] = True
            expected[code]["escalated_hits"] = len(rows)
            expected[code]["escalate_reason"] = (
                "到期：首见 %s 跨度 %ds／最长连续 %ds，阈 %ds ⇒ 升级出预期集人工复核"
                "（失实成因不得被预期灯无限期吞没）"
                % (aging["first_seen"], aging["span_s"], aging["continuous_s"],
                   EXPECTED_LAMP_ESCALATE_S))
            escalated.append({"code": code, "first_seen": aging["first_seen"],
                              "last_seen": aging["last_seen"],
                              "span_s": aging["span_s"],
                              "continuous_s": aging["continuous_s"],
                              "hits": len(rows),
                              "reason": expected[code]["escalate_reason"]})
            for r in rows:
                item = {k: r.get(k) for k in ("ts", "level", "code", "message")}
                item["escalated_from"] = code
                unexpected.append(item)
    return {"expected": expected, "a4l_entries": a4l,
            "a4l_below_gate_since_start": a4l_below_gate,
            "unexpected": unexpected, "escalated": escalated}


def _default_orders_verify(names):
    """默认订单核验器（OBS-D4 整改二轮·复核 issue 2）：必须与默认候选面
    `list_order_candidates` **同根**——旧版此处读本地 ORDERS_DIR，而默认候选面
    已改读生产真值根，不注入核验器直接调 evaluate() 会「候选=生产根 1032 单
    却按本地根核验 → 全单 verifiable=False → 判据① False」的 fail-closed 假阴性。
    现走多根核验（远程生产根 ∪ 本地 f6 根），与候选面同根。"""
    return verify_orders_records_anywhere(names)


def _default_alarms():
    return read_alarms(ALARMS_PATH, since_start_epoch())


def evaluate(now_epoch=None, *, ps_hits_fn=ps_hits, anolis_fn=anolis_residue_hits,
             ch_count_fn=ch_count, orders_fn=list_order_candidates,
             orders_verify_fn=_default_orders_verify, alarms_fn=_default_alarms,
             tmp_capacity_fn=tmp_capacity_mib):
    """纯判定核心：采样 → 判据 → row。时间与全部采样面可注入（TDD）。

    窗口内：row 语义同 W2-C-14 初版（verdict「观察期内：」前缀日报）。
    期满（now ≥ OBS_END，红队 W3-C-14）：kind=…-final 终局记录，verdict 去日报
    前缀、逐判据给出达成/未达成终局结论，final.criteria_unmet 列未达成判据、
    escalation_required=有未达成（须升级人工处置，不静默收场）。
    判据面（红队 W3-C11/C13 扩展）：①按订单记录核验（create_order 时间 +
    Closed 终态 + 四类跃迁 kind 恰集合）；2b=安灯/头寸面（alarms.log 未知
    red/amber、A4L 低于闸线、/tmp 现值低于闸线任一在场即未达成；A0/A7 预期灯
    只入台账）。采样失败面汇总在 row["sampling_failed_faces"]（fail-closed）。
    """
    now_epoch = time.time() if now_epoch is None else now_epoch
    now = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now_epoch))
    mid_epoch = time.mktime(time.strptime(MID_CHECKPOINT, "%Y-%m-%d %H:%M:%S"))
    end_epoch = time.mktime(time.strptime(OBS_END, "%Y-%m-%d %H:%M:%S"))

    # 判据③：检查点算术（现在必须 ≥ 中间复核点；in_window=false=已期满）。
    checkpoint_ok = now_epoch >= mid_epoch
    in_window = now_epoch < end_epoch
    expired = not in_window

    # 判据②：旧链零复活。
    old_chain_hits = ps_hits_fn()
    tmp_logs = {p: mtime_iso(p) for p in TMP_LOGS}
    heartbeat_mtime = mtime_iso(MCODE_HEARTBEAT)
    # 起算后 /tmp 日志或心跳有变动 = 旧链活动信号（None=不在盘=持续静默）。
    base = time.mktime(time.strptime(OBS_START, "%Y-%m-%d %H:%M:%S"))
    base_ms = base * 1000
    def fresh(path):
        try:
            return os.path.getmtime(path) >= base
        except OSError:
            return False
    tmp_fresh = {p: fresh(p) for p in TMP_LOGS}
    hb_fresh = fresh(MCODE_HEARTBEAT)
    # OBS-D4（2026-10-31）时区口径显式化：occurred_at 列为 DateTime64(3,'UTC')，
    # 裸字符串字面量按列时区（UTC）解析 → CST 窗口首 8h 事件不可见（收口 §附-0）。
    # 窗口字面量显式声明 Asia/Shanghai（三参形式 toDateTime64(str, scale, tz)——
    # CH 26.7 实测：两参形式把 tz 当 scale 会 HTTP 500，实测窗界 epoch=
    # 1792947952=2026-10-25 17:05:52 UTC，即 CST 窗界正确换算为真值即时）；
    # 窗口收全=加严方向（判据② bench 行只可能多计不少计），断言强度不降。
    bench_rows = ch_count_fn(
        "SELECT count() FROM af_mes.mes_event "
        f"WHERE line_id = 'bench' AND occurred_at >= "
        f"toDateTime64('{OBS_START}', 3, 'Asia/Shanghai')")
    anolis_hits = anolis_fn()
    criterion2 = (
        old_chain_hits == []
        and not any(tmp_fresh.values())
        and not hb_fresh
        and bench_rows == 0
        and anolis_hits == []
    )

    # 判据①：af 线订单 Closed+MES 4 行（核验单未执行即未达成，不空过）。
    # 红队 W3-C13：候选单逐单核记录——create_order 时间判定核验单、Closed
    # 终态、四类跃迁 kind 恰集合；目录 mtime 口径废除。
    candidates = orders_fn()
    verified = None
    if candidates is not None:
        verified = orders_verify_fn(candidates)
    in_scope = []
    if verified is not None:
        for entry in verified:
            if not entry["verifiable"] or entry["created_ms"] is None:
                in_scope.append(entry)  # 创建时间不可证 = 可能起算后，保守列入
            elif entry["created_ms"] >= base_ms:
                in_scope.append(entry)
    af_rows = ch_count_fn(
        "SELECT count() FROM af_mes.mes_event "
        f"WHERE station_id = 'af-order-cli' AND occurred_at >= "
        f"toDateTime64('{OBS_START}', 3, 'Asia/Shanghai')")
    criterion1_orders = bool(in_scope) and any(
        e["closed"] and e["mes_kinds_ok"] for e in in_scope)
    criterion1_mes = (af_rows or 0) >= 4  # release/start/complete/close 四跃迁
    criterion1 = criterion1_orders and criterion1_mes

    # 判据 2b（红队 W3-C11）：安灯/头寸面——未知 red/amber 码、观察期内 A4L
    # 低于闸线、/tmp 现值低于闸线，任一在场即未达成；A0/A7 预期灯只入台账。
    alarms_entries = alarms_fn()
    capacity = tmp_capacity_fn()
    tmp_free_mib = capacity[0] if capacity else None
    tmp_total_mib = capacity[1] if capacity else None
    classification = (classify_alarms(alarms_entries)
                      if alarms_entries is not None else None)
    tmp_gate_breach_now = (tmp_free_mib is not None
                           and tmp_free_mib < TMP_GATE_MIB)
    criterion2b = (
        alarms_entries is not None
        and capacity is not None
        and not classification["unexpected"]
        and not classification["a4l_below_gate_since_start"]
        and not tmp_gate_breach_now
    )

    # 采样失败面汇总（fail-closed：面缺 = 不明，判据不得记达成）。
    sampling_failed = []
    for face, value in (("ps", old_chain_hits), ("anolis", anolis_hits),
                        ("mes_bench", bench_rows), ("mes_af", af_rows),
                        ("orders", candidates), ("alarms", alarms_entries),
                        ("tmp_capacity", capacity)):
        if value is None:
            sampling_failed.append(face)

    row = {
        "ts": now,
        "kind": "bench-retire-obs-review",
        "window": {"start": OBS_START, "end": OBS_END,
                   "mid_checkpoint": MID_CHECKPOINT,
                   "checkpoint_reached": checkpoint_ok, "in_window": in_window},
        "criterion1_af_order_closed_mes4": {
            "achieved": criterion1,
            "new_orders_since_start": [e["name"] for e in in_scope],
            "orders_created_since_start": in_scope,
            "verified_orders": sum(1 for e in in_scope
                                   if e["closed"] and e["mes_kinds_ok"]),
            "af_order_cli_mes_rows_since_start": af_rows,
            "note": ("核验单按订单记录核验：create_order 时间判定 + Closed 终态 "
                     "+ MES 四类跃迁 kind 恰集合（红队 W3-C13，mtime 口径废除）；"
                     "未执行 af-order 正常下单核验单不得记达成（W2-C13 勘误）"),
        },
        "criterion2_old_chain_zero_revival": {
            "achieved": criterion2,
            "ps_hits": old_chain_hits,
            "tmp_logs_mtime": tmp_logs,
            "tmp_logs_fresh_since_start": tmp_fresh,
            "mcode_heartbeat_mtime": heartbeat_mtime,
            "mcode_heartbeat_fresh": hb_fresh,
            "mes_line_bench_rows_since_start": bench_rows,
            "anolis_residue_hits": anolis_hits,
        },
        "criterion2b_watch_lamps_and_tmp_headroom": {
            "achieved": criterion2b,
            "alarms_sampled_since_start": (len(alarms_entries)
                                           if alarms_entries is not None else None),
            "expected_lamp_hits": classification["expected"] if classification else None,
            "a4l_entries_since_start": (len(classification["a4l_entries"])
                                        if classification else None),
            "a4l_below_gate_since_start": (classification["a4l_below_gate_since_start"]
                                           if classification else None),
            "unexpected_alarms": (classification["unexpected"]
                                  if classification else None),
            "tmp_free_mib_now": tmp_free_mib,
            "tmp_total_mib": tmp_total_mib,
            "tmp_gate_mib": TMP_GATE_MIB,
            "tmp_calibrated_mib": TMP_CALIBRATED_MIB,
            "tmp_gate_breach_now": tmp_gate_breach_now,
            "note": ("A4L 为观察期硬判据（W2-C18 勘误，非既有环境灯）：低于闸线 "
                     f"{TMP_GATE_MIB}MiB 判负；A0/A7 为登记预期灯只入台账；未知 "
                     "red/amber 码一律异常（红队 W3-C11）"),
        },
        "sampling_failed_faces": sampling_failed,
        "verdict": (
            "观察期内：判据①{0}；判据②旧链零复活{1}；安灯与/tmp头寸{2}".format(
                "达成（核验单 Closed+四跃迁入账）" if criterion1
                else "未达成（核验单待执行，≤2026-10-29 01:05:52 前须下单核对）",
                "维持" if criterion2 else "异常——旧链活动信号在场，详看 criterion2 各面",
                "正常" if criterion2b else
                "异常——未知red/amber或A4L低于闸线2252MiB，详看 criterion2b 各面")
        ),
    }

    if expired:
        # 期满终局（W3-C-14）：终局记录替代日报，verdict 禁「观察期内」前缀。
        criteria_unmet = [label for label, ok in
                          ((1, criterion1), (2, criterion2), ("2b", criterion2b))
                          if not ok]
        row["kind"] = "bench-retire-obs-review-final"
        row["final"] = {"expired": True, "criteria_unmet": criteria_unmet,
                        "escalation_required": bool(criteria_unmet)}
        row["verdict"] = (
            f"观察期已期满（{OBS_END}）——终局复核："
            f"判据①af 线订单 Closed+MES 4 行{'达成' if criterion1 else '未达成'}；"
            f"判据②旧链零复活{'达成' if criterion2 else '未达成（旧链活动信号在场，详看 criterion2 各面）'}；"
            f"判据2b安灯与/tmp头寸{'正常' if criterion2b else '异常（未知red/amber或A4L低于闸线，详看 criterion2b 各面）'}。"
            + ("全部判据达成，可进入期满后动作序列（runbook §六-3：文件归档批→af-bench CLI 仓内退役→watch 判据更新→5 张遗留表裁决）。"
               if not criteria_unmet else
               "判据存在未达成项——升级人工处置（alarms.log OBS-EXPIRE），未达成面不得由本脚本代答，定时器已停、不再日报。")
        )
    return row


def stop_obs_timer():
    """期满停表：stop+disable bench-retire-obs-review.timer（systemd --user）。
    任一步失败返回 False（stderr 注记），由调用方如实上报不谎报停表。"""
    ok = True
    for action in ("stop", "disable"):
        try:
            r = subprocess.run(
                ["systemctl", "--user", action, "bench-retire-obs-review.timer"],
                capture_output=True, text=True, timeout=15)
            if r.returncode != 0:
                ok = False
                print(f"NOTICE: systemctl --user {action} rc={r.returncode} "
                      f"{r.stderr.strip()}", file=sys.stderr)
        except (OSError, subprocess.TimeoutExpired) as e:
            ok = False
            print(f"NOTICE: systemctl --user {action} 失败：{e}", file=sys.stderr)
    return ok


def escalate_andon(row):
    """期满且有判据未达成 → 升级人工处置：状态观测/alarms.log 追加 red 级
    OBS-EXPIRE 记录（JSONL，与 factory-watch/keepalive 告警同格式）。"""
    entry = {
        "ts": row["ts"],
        "level": "red",
        "code": "OBS-EXPIRE",
        "message": (f"旧 bench 退役观察期已期满（{OBS_END}）且判据 "
                    f"{row['final']['criteria_unmet']} 未达成——升级人工处置，"
                    "不得空过收场；复核定时器已停，详见 "
                    "状态观测/bench-retire-obs-review.jsonl 终局行"),
        "since": OBS_END,
    }
    path = os.path.join(WS, "状态观测", "alarms.log")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def act_on_row(row, stop_timer_fn=stop_obs_timer, escalate_fn=escalate_andon):
    """期满动作执行器：in_window=false → 停定时器；有未达成判据 → 升级。
    窗口内行两个动作都不触发（返回 acts 便于测试与留痕）。"""
    acts = []
    if not row["window"]["in_window"]:
        if stop_timer_fn():
            acts.append("stop_timer")
        else:
            acts.append("stop_timer_FAILED")
        if row.get("final", {}).get("escalation_required"):
            escalate_fn(row)
            acts.append("escalate")
    return acts


def has_final_record(path=OUT):
    """jsonl 中是否已有终局行（幂等护栏：重跑不重复落终局/不停表）。"""
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    if json.loads(line).get("kind") == "bench-retire-obs-review-final":
                        return True
                except ValueError:
                    continue
    except OSError:
        return False
    return False


def main() -> int:
    # 生产接线（红队 W3-C11/C13）：三个扩展采样面显式注入严格核验器——订单
    # 记录核验、alarms.log 采样、/tmp 头寸采样（源文本钉死见
    # test-bench-retire-obs-review-criteria.py::test_production_main_wires_strict_verifier）。
    # OBS-D4（2026-10-31）：订单核验器改生产真值根版（ssh 只读
    # anolis:/data/bench/af-p3-state/orders；候选面 list_order_candidates 缺省
    # 同根）；判定核心与本地版同函数，严格语义零改动。
    row = evaluate(
        orders_verify_fn=verify_orders_records_anywhere,
        alarms_fn=lambda: read_alarms(ALARMS_PATH, since_start_epoch()),
        tmp_capacity_fn=tmp_capacity_mib)

    # 幂等：终局已落账则不再重复（W3-C-14——防手工重跑连刷终局/反复停表）。
    if row["kind"] == "bench-retire-obs-review-final" and has_final_record():
        print("NOTICE: 终局记录已在档（bench-retire-obs-review.jsonl 存在 "
              "…-final 行），本次重跑不重复落行、不重复停表", file=sys.stderr)
        print(json.dumps({"ts": row["ts"], "kind": row["kind"],
                          "deduplicated": True}, ensure_ascii=False))
        return 0

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    acts = act_on_row(row)
    print(json.dumps(row, ensure_ascii=False, indent=2))
    if acts:
        print(f"ACTIONS: {acts}", file=sys.stderr)
    if row["sampling_failed_faces"]:
        print(f"NOTICE: 有采样面失败（{', '.join(row['sampling_failed_faces'])}）"
              "——结论以不明计，不谎报达成", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
