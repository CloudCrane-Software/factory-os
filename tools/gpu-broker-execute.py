#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gpu-broker-execute.py — GPU broker 执行器最小件（D-100·factory-os#32·GPUbroker P2）。

职责（卡面施工步2）：负载卡（repo+commit/命令/mem/gpu 数/disk/timeout/产物声明）
→ 排队（45G/并发4 准入）→ anolis 代跑 → 三行 start/end/artifacts 回报 → 产物回传。

禁项（卡面置顶，逐条落实现）：
  · GPU 必须 broker 代跑绝不直通（Q6 §1.2 铁律）：沙箱永不拿 anolis shell——本件
    是唯一执行面（ssh 只认 alias anolis，禁 IP 直连）；执行句柄=一次性+TTL 内
    只可心跳/查状态/交产物三动作（bot-lane claim_token 同形，Q6 §2.4）。句柄
    能力面 = HANDLE_ACTIONS 三元组，分发器外一律拒（fail-closed）；shell/exec/
    任意命令永不在句柄词表（验收#4 直通自查回读位）。
  · 票据审批永不交 LLM 全权（D9 收窄）：本件零 LLM 调用、零网络判定（ssh 仅限
    anolis 代跑与读数），五条准入全确定性机检；auto-approve 集=机检全过
    （⊆ 机检白名单保守交集），fail-closed 原样不改 fail-open；判官路径永不批票。
  · 账本不可读宁停不猜：账本/任务快照/负载卡任一不可证 ⇒ verdict=reject rc=2。
  · 沙箱自报只是参考值：三行回报以 anolis 侧执行器读数（markers.jsonl）为准；
    anolis 实测（nvidia-smi/free/df）低于申报预算 ⇒ 不执行（拒发或排队）。

五条准入机检（GPU 票；与 D-94 LLM 五条同构-9 骨架，数值=Q6 §3.1 GPU 类起步值）：
  ① task_ref 在飞且身份一致（共用骨架，importlib 载入 resource-ticket-check）
  ② 单票上限：卡·时=gpu_cards×timeout_min/60 ≤2；mem≤16G；disk≤20G；
     timeout≤120min；gpu_cards≤2（anolis 双卡物理）；repo/commit/command/产物形态
  ③ 每沙箱 ≤1 张在飞 GPU 票（账本在飞 gpu-anolis 票按 requester 计）
  ④ 全局日限 ≤8 卡·时/日（当日 issue 行卡·时合计）；anolis Σmem≤45G/并发≤4
     硬顶复用不新设（制度-v1.md:39）——超 ⇒ 排队不并发（verdict=queue rc=1）
  ⑤ 无停用 hold（账本 hold 行 scope 命中 requester/task_ref）
  另：anolis 预检（空闲窗实测）——gpu_cards>物理卡数 ⇒ reject（结构性不足）；
     GPU 忙/mem/data 实测紧张 ⇒ queue（容量性，不硬闯）。

账本（append-only，flock 单写；行族沿用 v1 词表，GPU 列=v2 加列不加表）：
  issue（发放：三元绑定 task_ref×consumer×handle_fp 一次写死；amount 带 GPU 维
    + max_req/max_input_tokens 恒 0——GPU 票不走 LLM 网关计量维，D-94 机检③④
    日限聚合天然零贡献，登记接缝见账本 v2 schema 行）；meter×3（start/end/
    artifacts 执行器读数）；revoke（执行完释放在飞位）；reject（拒发审计）。

句柄（af.gpu-handle.v1，运行时状态件 0600，不入库不进水）：
  发放时一次写死 token（secrets.token_urlsafe；值只入状态件与运营者交付面，
  永不入账本/issue/PR/argv/转录——账本只带指纹 sha256[:12]）；TTL 内三动作：
  heartbeat（心跳/STALL 判定）/ status（查任务态+三行进度）/ artifacts（产物
  清单+回传）；一次性=发放一次不续期，到期/吊销即拒（Q6 §2.6 fail-closed）。
  token 经 env（--token-env，缺省 GPU_HANDLE_TOKEN）或 --token-file 传入，禁 argv。

用法：
  python3 tools/gpu-broker-execute.py --card CARD.json --tasks TASKS.json \
      [--ledger 账本/resource-ledger.jsonl] [--now ISO8601] [--state-dir DIR] \
      [--max-transfer-mb N]
  GPU_HANDLE_TOKEN=… python3 tools/gpu-broker-execute.py --handle <ticket_id> \
      --action heartbeat|status|artifacts
  python3 tools/gpu-broker-execute.py --selftest

退出码：0=approve（已发放并代跑完，三行回报+产物回传读数）；1=queue（Σmem/并发/
anolis 容量顶满，排队未执行，零账本行）；2=reject（fail-closed 拒发不猜绿）。
"""
import argparse
import datetime as dt
import fcntl
import hashlib
import hmac
import importlib.util
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---- 共用 fail-closed 骨架（同构-9）：resource-ticket-check.py 文件名含连字符，
#      不能按名 import——importlib 载入（仓内先例 tools/af-perm-request-check.py:58）。
#      dont_write_bytecode：骨架载入不在 tools/ 留 __pycache__（仓纪：零 .pyc 入库）。
sys.dont_write_bytecode = True
_SKELETON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resource-ticket-check.py")
_spec = importlib.util.spec_from_file_location("resource_ticket_check", _SKELETON)
rtc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rtc)
FailClosed = rtc.FailClosed

# ---- 退出码 / 判定词表 ------------------------------------------------------
RC_APPROVE = 0
RC_QUEUE = 1
RC_REJECT = 2

CARD_SCHEMA = "af.gpu-load-card.v1"
GPU_TICKET_TYPE = "gpu-anolis"
GPU_RESOURCE = "gpu:1xV100S-32G"     # Q6 §2.2 表字面值（anolis 2×V100S-32G 实测）
HANDLE_ACTIONS = ("heartbeat", "status", "artifacts")   # 句柄能力面全集（三动作）

# ---- Q6 §3.1 GPU 类起步值（改值须 D-11 裁定并同步登记本声明行，同 D-94 纪律）--
GPU_PER_TICKET_MAX_CARD_HOURS = 2.0    # 单票 ≤2 卡·时
GPU_PER_TICKET_MAX_MEM_G = 16          # mem ≤16G
GPU_PER_TICKET_MAX_DISK_G = 20         # disk ≤20G
GPU_PER_TICKET_MAX_TIMEOUT_MIN = 120   # timeout ≤120min
GPU_MAX_CARDS_PER_TICKET = 2           # anolis 双卡（物理上限）
GPU_PER_SANDBOX_MAX_INFLIGHT = 1       # 每沙箱 ≤1 张在飞（2 卡全占=他人饿死）
GPU_GLOBAL_DAILY_CARD_HOURS = 8        # GPU 段合计 ≤8 卡·时/日
ANOLIS_MEM_CAP_G = 45                  # 硬顶复用不新设（制度-v1.md:39）
ANOLIS_CONCURRENCY_CAP = 4             # 同上
GPU_HANDLE_TTL_DEFAULT_S = 2 * 3600    # 句柄默认 2h
GPU_HANDLE_TTL_MAX_S = 4 * 3600        # 上限 4h（Q6 §2.2「GPU 单卡段 ≤4h」，
                                       # 与 D-94 登记行 MAX_TTL_SECONDS 同值取保守者）

ANOLIS_RUN_ROOT = "/data/bench/gpu-broker"   # anolis 侧执行根（broker 专用，不占 wave wt）
DATA_FLOOR_G = 10                            # env-check 同族磁盘底（D-64②）

# ---- 形态白名单（解析失败 ⇒ FailClosed，契约 §7.5③ 同族）-------------------
TICKET_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
COMMIT_RE = re.compile(r"^(HEAD|[0-9a-f]{7,40})$")
REPO_RE = re.compile(r"^https?://[A-Za-z0-9][A-Za-z0-9._-]*(?::\d+)?/[A-Za-z0-9._/-]+?$")
ART_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
ART_PATH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,200}$")
COMMAND_MAX_LEN = 4000

# ---- 传输层（ssh 只认 alias；DRY 桩供 selftest 零生产触达）-----------------
ANOLIS = os.environ.get("GPU_BROKER_SSH", "anolis")
DRY = {"on": False, "ssh_fn": None, "scp_to_fn": None, "scp_from_fn": None}


def sh(cmd, timeout=120):
    if DRY["on"] and DRY.get("sh_fn"):
        return DRY["sh_fn"](cmd, timeout=timeout)
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)


def ssh_anolis(cmd, timeout=180):
    """base64 运输层（引号/中文/换行全免疫；口径同 wave-runner.ssh_anolis）。
    GPU 执行窗预检件内自含（nvidia-smi/free/df），不复用 anolis-env-check.sh 的
    cargo 前置（D-64② 面向 cargo 合线窗；GPU 票无 cargo 语义）。"""
    if DRY["on"] and DRY["ssh_fn"]:
        return DRY["ssh_fn"](cmd, timeout=timeout)
    import base64
    b = base64.b64encode(cmd.encode("utf-8")).decode("ascii")
    return sh("ssh -o BatchMode=yes -o ConnectTimeout=10 %s 'echo %s | base64 -d | bash'"
              % (ANOLIS, b), timeout)


def scp_to_anolis(local_path, remote_path, timeout=180):
    if DRY["on"] and DRY["scp_to_fn"]:
        return DRY["scp_to_fn"](local_path, remote_path, timeout=timeout)
    return sh("scp -q -o BatchMode=yes %s %s:%s" % (local_path, ANOLIS, remote_path), timeout)


def scp_from_anolis(remote_path, local_path, timeout=300):
    if DRY["on"] and DRY["scp_from_fn"]:
        return DRY["scp_from_fn"](remote_path, local_path, timeout=timeout)
    os.makedirs(os.path.dirname(local_path) or ".", exist_ok=True)
    return sh("scp -q -o BatchMode=yes %s:%s %s" % (ANOLIS, remote_path, local_path), timeout)


def iso(ts):
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def now_utc():
    return dt.datetime.now(dt.timezone.utc)


# ---- 判定书（硬超限 ⇒ reject；容量顶 ⇒ queue；fail-closed ⇒ reject）---------
class GpuVerdict(object):
    """checks 明细 + 分层结论：fail_closed（不可证）> 硬超限（单票/每沙箱/日限/
    hold/任务面/形态）> 容量顶（Σmem/并发/anolis 实测紧张 ⇒ 排队不并发）。"""

    def __init__(self):
        self.checks = []
        self.fail_closed = None

    def add(self, name, passed, detail, capacity=False):
        self.checks.append({"name": name, "pass": bool(passed),
                            "detail": detail, "capacity": bool(capacity)})

    def reject(self, why):
        self.fail_closed = why

    def render(self):
        if self.fail_closed is not None:
            return {"verdict": "reject", "issued": False,
                    "fail_closed": self.fail_closed, "checks": self.checks}
        bad = [c for c in self.checks if not c["pass"]]
        if not bad:
            return {"verdict": "approve", "issued": True, "checks": self.checks}
        hard = [c for c in bad if not c["capacity"]]
        if hard:
            return {"verdict": "reject", "issued": False,
                    "reasons": [c["detail"] for c in hard], "checks": self.checks}
        return {"verdict": "queue", "issued": False,
                "queue_reason": bad[0]["detail"], "checks": self.checks}


# ---- 账本面 ----------------------------------------------------------------
def ledger_append(rows, ledger_path):
    """append-only 追加（flock 单写；行只追加不改不删——git 历史即证明面）。"""
    d = os.path.dirname(ledger_path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(ledger_path, "a", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def gpu_inflight_rows(rows):
    """GPU 科目在飞票：event=issue ∧ ticket_type=gpu-anolis ∧ 无匹配 revoke 行
    （revoke 行 = 执行完/句柄到期释放在飞位；两遍扫描免疫行序）。"""
    revoked = {r.get("ticket_id") for r in rows
               if r.get("event") == "revoke" and r.get("ticket_id")}
    return [r for r in rows
            if r.get("event") == "issue" and r.get("ticket_type") == GPU_TICKET_TYPE
            and r.get("ticket_id") not in revoked]


# ---- 负载卡解析（af.gpu-load-card.v1）--------------------------------------
def parse_card(obj, what="负载卡"):
    if obj.get("schema") != CARD_SCHEMA:
        raise FailClosed("%s schema 非 %s: %r" % (what, CARD_SCHEMA, obj.get("schema")))
    tid = rtc.require(obj, "ticket_id", what)
    if not TICKET_ID_RE.match(tid):
        raise FailClosed("%s ticket_id 形态非法: %r" % (what, tid))
    task_ref = rtc.parse_task_ref(rtc.require(obj, "task_ref", what), what)
    requester = rtc.require(obj, "requester", what)
    purpose = rtc.require(obj, "purpose", what)
    if len(purpose) > 200:
        raise FailClosed("%s purpose 超长（≤200 字）" % what)
    command = rtc.require(obj, "command", what)
    if not isinstance(command, str) or len(command) > COMMAND_MAX_LEN:
        raise FailClosed("%s command 非字符串或超长（≤%d）" % (what, COMMAND_MAX_LEN))
    repo = obj.get("repo")
    if repo is not None and (not isinstance(repo, str) or not REPO_RE.match(repo)):
        raise FailClosed("%s repo 形态非法（https URL，禁直嵌凭据）: %r" % (what, repo))
    commit = obj.get("commit")
    if commit is not None and (not isinstance(commit, str) or not COMMIT_RE.match(commit)):
        raise FailClosed("%s commit 形态非法（HEAD 或 7-40 hex）: %r" % (what, commit))
    nums = {}
    for fld, lo in (("mem_budget_g", 1), ("gpu_cards", 1), ("disk_budget_g", 1), ("timeout_min", 1)):
        v = obj.get(fld)
        if not isinstance(v, int) or isinstance(v, bool) or v < lo:
            raise FailClosed("%s %s 非 ≥%d 整数: %r" % (what, fld, lo, v))
        nums[fld] = v
    ttl_s = rtc.parse_ttl_seconds(rtc.require(obj, "ttl_ask", what), what)
    if ttl_s > GPU_HANDLE_TTL_MAX_S:
        raise FailClosed("%s ttl_ask %ds 超 GPU 句柄上限 %ds" % (what, ttl_s, GPU_HANDLE_TTL_MAX_S))
    arts = obj.get("artifacts", [])
    if not isinstance(arts, list):
        raise FailClosed("%s artifacts 非数组" % what)
    out_arts = []
    for a in arts:
        if not isinstance(a, dict):
            raise FailClosed("%s artifacts 存在非对象条目" % what)
        name, path = a.get("name"), a.get("path")
        if not (isinstance(name, str) and ART_NAME_RE.match(name)):
            raise FailClosed("%s 产物名形态非法: %r" % (what, name))
        if not (isinstance(path, str) and ART_PATH_RE.match(path)) or ".." in path.split("/"):
            raise FailClosed("%s 产物路径形态非法（禁绝对/上级逃逸）: %r" % (what, path))
        out_arts.append({"name": name, "path": path})
    mode = obj.get("artifact_transfer", "auto")
    if mode not in ("auto", "declare-only"):
        raise FailClosed("%s artifact_transfer 词表外: %r" % (what, mode))
    return {"ticket_id": tid, "task_ref": task_ref, "requester": requester,
            "purpose": purpose, "command": command, "repo": repo, "commit": commit,
            "artifacts": out_arts, "artifact_transfer": mode, "ttl_s": ttl_s, **nums}


# ---- 五条准入机检 -----------------------------------------------------------
def check_admission(card, snapshot, rows, now_ts):
    v = GpuVerdict()
    if snapshot.get("schema") != rtc.TASKS_SCHEMA:
        raise FailClosed("任务快照 schema 非 %s: %r" % (rtc.TASKS_SCHEMA, snapshot.get("schema")))

    # ① task_ref 在飞且身份一致（共用骨架·任务面）
    rtc.task_face_check(snapshot, card["task_ref"], card["requester"], v)

    # ② 单票上限（Q6 §3.1 GPU 类起步值）
    card_hours = card["gpu_cards"] * card["timeout_min"] / 60.0
    v.add("② 单票上限（卡·时/mem/disk/timeout/卡数）",
          card_hours <= GPU_PER_TICKET_MAX_CARD_HOURS
          and card["mem_budget_g"] <= GPU_PER_TICKET_MAX_MEM_G
          and card["disk_budget_g"] <= GPU_PER_TICKET_MAX_DISK_G
          and card["timeout_min"] <= GPU_PER_TICKET_MAX_TIMEOUT_MIN
          and card["gpu_cards"] <= GPU_MAX_CARDS_PER_TICKET,
          "卡·时=%.2f/≤%g, mem=%dG/≤%dG, disk=%dG/≤%dG, timeout=%dmin/≤%dmin, "
          "gpu_cards=%d/≤%d（物理双卡）"
          % (card_hours, GPU_PER_TICKET_MAX_CARD_HOURS, card["mem_budget_g"],
             GPU_PER_TICKET_MAX_MEM_G, card["disk_budget_g"], GPU_PER_TICKET_MAX_DISK_G,
             card["timeout_min"], GPU_PER_TICKET_MAX_TIMEOUT_MIN, card["gpu_cards"],
             GPU_MAX_CARDS_PER_TICKET))

    # ③④ 账本面（scan_ledger 顺带全行严格校验：坏行/词表外 ⇒ FailClosed 拒发）
    agg = rtc.scan_ledger(rows, now_ts, card["requester"], card["task_ref"])
    inflight = gpu_inflight_rows(rows)
    mine = [r for r in inflight if r.get("requester") == card["requester"]]
    v.add("③ 每沙箱≤1张在飞", len(mine) + 1 <= GPU_PER_SANDBOX_MAX_INFLIGHT,
          "名下在飞 GPU 票 %d 张 + 本次 1 ≤ %d 张（2 卡全占=他人饿死）"
          % (len(mine), GPU_PER_SANDBOX_MAX_INFLIGHT))

    today = rtc.utc_day(now_ts)
    issued_today = 0.0
    for r in rows:
        if r.get("event") == "issue" and r.get("ticket_type") == GPU_TICKET_TYPE:
            if rtc.utc_day(rtc.parse_iso_ts(r["ts"], "账本 issue 行")) == today:
                am = r.get("amount") if isinstance(r.get("amount"), dict) else {}
                try:
                    issued_today += float(am.get("card_hours") or 0)
                except (TypeError, ValueError):
                    raise FailClosed("账本 issue 行 card_hours 非数值（ticket_id=%r）"
                                     % r.get("ticket_id"))
    v.add("④ 全局日限≤8卡·时/日", issued_today + card_hours <= GPU_GLOBAL_DAILY_CARD_HOURS,
          "当日 GPU 段已批 %.2f 卡·时 + 本次 %.2f ≤ %g 卡·时/日"
          % (issued_today, card_hours, GPU_GLOBAL_DAILY_CARD_HOURS))

    mem_sum = 0.0
    for r in inflight:
        am = r.get("amount") if isinstance(r.get("amount"), dict) else {}
        try:
            mem_sum += float(am.get("mem_budget_g") or 0)
        except (TypeError, ValueError):
            raise FailClosed("账本 issue 行 mem_budget_g 非数值（ticket_id=%r）"
                             % r.get("ticket_id"))
    v.add("④ anolis Σmem≤45G（在飞 GPU 票+本次）",
          mem_sum + card["mem_budget_g"] <= ANOLIS_MEM_CAP_G,
          "在飞 GPU mem %.0fG + 本次 %dG ≤ %dG（硬顶复用不新设）"
          % (mem_sum, card["mem_budget_g"], ANOLIS_MEM_CAP_G), capacity=True)
    v.add("④ anolis 并发≤4（在飞 GPU 票+本次）",
          len(inflight) + 1 <= ANOLIS_CONCURRENCY_CAP,
          "在飞 GPU 票 %d 张 + 本次 1 ≤ %d（硬顶复用不新设）"
          % (len(inflight), ANOLIS_CONCURRENCY_CAP), capacity=True)

    # ⑤ 无停用 hold（账本 hold 行 scope 命中即在押；hold 是账本之上的否决层）
    hit = rtc.hold_hit(agg["holds"], card["requester"], card["task_ref"])
    v.add("⑤ 无停用hold", hit is None,
          "无在押 hold" if hit is None else "在押 hold：%s" % hit)
    return v, card_hours


# ---- anolis 预检（空闲窗实测；执行器读数，沙箱自报只是参考值）---------------
def anolis_probe():
    """anolis 实测：GPU 物理卡数/占用、mem available、/data 余量。
    ssh 不可证 ⇒ None（调用方 fail-closed）。"""
    r = ssh_anolis("nvidia-smi --query-gpu=memory.total,memory.used --format=csv,noheader,nounits; "
                   "free -g | awk 'NR==2{print $7}'; "
                   "df -BG /data | awk 'NR==2{gsub(/G/,\"\",$4);print $4}'", timeout=60)
    if r.returncode != 0:
        return None
    gpu_total, gpu_busy, mem_g, data_g = 0, 0, None, None
    tail = []
    for ln in (r.stdout or "").splitlines():
        s = ln.strip()
        if not s:
            continue
        if "," in s:
            gpu_total += 1
            try:
                if int(s.split(",")[1].strip()) > 512:   # 显存占用 >512MiB 记忙
                    gpu_busy += 1
            except ValueError:
                return None
        else:
            tail.append(s)
    try:
        mem_g = int(tail[-2])
        data_g = int(tail[-1])
    except (ValueError, IndexError):
        return None
    return {"gpu_total": gpu_total, "gpu_busy": gpu_busy,
            "mem_avail_g": mem_g, "data_avail_g": data_g}


def check_preflight(card, probe):
    """预检判定：结构性不足（卡数>物理）⇒ reject；容量紧张 ⇒ queue。"""
    v = GpuVerdict()
    v.add("预检·GPU 卡数≤物理", card["gpu_cards"] <= probe["gpu_total"],
          "申报 %d 卡 ≤ anolis 物理 %d 卡" % (card["gpu_cards"], probe["gpu_total"]))
    v.add("预检·GPU 空闲", probe["gpu_busy"] + card["gpu_cards"] <= probe["gpu_total"],
          "anolis 显存占用中 GPU %d 张 + 申报 %d 张 ≤ 物理 %d 张（忙 ⇒ 排队不硬闯）"
          % (probe["gpu_busy"], card["gpu_cards"], probe["gpu_total"]), capacity=True)
    v.add("预检·mem available≥申报", probe["mem_avail_g"] >= card["mem_budget_g"],
          "anolis available %dG ≥ 申报 %dG" % (probe["mem_avail_g"], card["mem_budget_g"]),
          capacity=True)
    v.add("预检·/data 余量≥申报+%dG" % DATA_FLOOR_G,
          probe["data_avail_g"] >= card["disk_budget_g"] + DATA_FLOOR_G,
          "/data 余 %dG ≥ 申报 %dG + 底 %dG" % (probe["data_avail_g"], card["disk_budget_g"], DATA_FLOOR_G),
          capacity=True)
    return v


# ---- anolis 侧 runner（自含 timeout 强杀 + 树峰值采样 + markers 三行）------
RUNNER_TEMPLATE = r'''#!/usr/bin/env python3
# anolis 侧 GPU broker runner（tools/gpu-broker-execute.py 生成；自含 timeout 强杀）
import hashlib, json, os, subprocess, threading, time

JOB = __JOB_JSON__
RUN = os.path.join(JOB["run_root"], JOB["ticket_id"])
MARKERS = os.path.join(RUN, "markers.jsonl")


def emit(obj):
    obj["ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open(MARKERS, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def tree_rss_kib(root_pid):
    """进程树 RSS 合计（bash -c 子壳 + 真实负载全覆盖，KiB）。"""
    try:
        out = subprocess.run(["ps", "-eo", "pid=,ppid=,rss="],
                             capture_output=True, text=True, timeout=5).stdout or ""
    except Exception:
        return 0
    kids, rss = {}, {}
    for ln in out.splitlines():
        parts = ln.split()
        if len(parts) != 3:
            continue
        try:
            pid, ppid, rk = int(parts[0]), int(parts[1]), int(parts[2])
        except ValueError:
            continue
        kids.setdefault(ppid, []).append(pid)
        rss[pid] = rk
    total, stack, seen = 0, [root_pid], set()
    while stack:
        pid = stack.pop()
        if pid in seen:
            continue
        seen.add(pid)
        total += rss.get(pid, 0)
        stack.extend(kids.get(pid, []))
    return total


def gpu_peaks():
    """nvidia-smi 采样（显存 MiB / 利用率 %）；不可用 ⇒ 零值（不猜）。"""
    try:
        o = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,utilization.gpu",
                            "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=5)
        mem, util = 0, 0
        for ln in (o.stdout or "").strip().splitlines():
            parts = [x.strip() for x in ln.split(",")]
            if len(parts) == 2:
                mem = max(mem, int(parts[0]))
                util = max(util, int(parts[1]))
        return mem, util
    except Exception:
        return 0, 0


def main():
    os.makedirs(os.path.join(RUN, "out"), exist_ok=True)
    os.chdir(RUN)
    os.environ["CUDA_VISIBLE_DEVICES"] = JOB["cuda_visible_devices"]
    emit({"phase": "start", "ticket_id": JOB["ticket_id"],
          "gpu_cards": JOB["gpu_cards"], "mem_budget_g": JOB["mem_budget_g"],
          "disk_budget_g": JOB["disk_budget_g"], "timeout_min": JOB["timeout_min"],
          "cuda_visible_devices": JOB["cuda_visible_devices"]})
    peak = {"rss_kib": 0, "gpu_mem_mib": 0, "gpu_util_pct": 0}
    p = subprocess.Popen(["bash", "-c", JOB["command"]], cwd=RUN,
                         stdout=open(os.path.join(RUN, "stdout.log"), "w"),
                         stderr=open(os.path.join(RUN, "stderr.log"), "w"))

    def sampler():
        while p.poll() is None:
            peak["rss_kib"] = max(peak["rss_kib"], tree_rss_kib(p.pid))
            gm, gu = gpu_peaks()
            peak["gpu_mem_mib"] = max(peak["gpu_mem_mib"], gm)
            peak["gpu_util_pct"] = max(peak["gpu_util_pct"], gu)
            time.sleep(1)

    th = threading.Thread(target=sampler, daemon=True)
    th.start()
    t0 = time.time()
    timed_out = False
    try:
        rc = p.wait(timeout=JOB["timeout_s"])
    except subprocess.TimeoutExpired:
        p.kill()
        rc = 124
        timed_out = True
    th.join(timeout=2)
    emit({"phase": "end", "exit_code": rc, "timed_out": timed_out,
          "duration_s": round(time.time() - t0, 2),
          "peak_rss_g": round(peak["rss_kib"] / 1048576.0, 3),
          "gpu_peak_mem_mib": peak["gpu_mem_mib"], "gpu_peak_util_pct": peak["gpu_util_pct"]})
    arts = []
    for a in JOB["artifacts"]:
        fp = os.path.join(RUN, a["path"])
        if os.path.isfile(fp):
            h = hashlib.sha256()
            with open(fp, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            arts.append({"name": a["name"], "path": a["path"],
                         "size_bytes": os.path.getsize(fp), "sha256": h.hexdigest()})
    emit({"phase": "artifacts", "artifacts": arts})
    print("RUNNER_DONE rc=%d" % rc)


if __name__ == "__main__":
    main()
'''


def execute_on_anolis(card):
    """anolis 代跑（broker 唯一执行面）：清旧建目录 → 传 runner+job → 同步跑
    （ssh 超时 = timeout 秒 + 120s 余量；runner 自含 timeout 强杀 rc=124）→
    回读 markers 三行。返回 (ok, markers, evidence)。"""
    tid = card["ticket_id"]
    run_dir = os.path.join(ANOLIS_RUN_ROOT, tid)
    job = {"run_root": ANOLIS_RUN_ROOT, "ticket_id": tid, "command": card["command"],
           "gpu_cards": card["gpu_cards"], "mem_budget_g": card["mem_budget_g"],
           "disk_budget_g": card["disk_budget_g"], "timeout_min": card["timeout_min"],
           "timeout_s": card["timeout_min"] * 60,
           "cuda_visible_devices": ",".join(str(i) for i in range(card["gpu_cards"])),
           "artifacts": card["artifacts"]}
    r = ssh_anolis("rm -rf %s && mkdir -p %s/out" % (run_dir, run_dir), timeout=120)
    if r.returncode != 0:
        return False, None, "建目录失败：%s" % (r.stdout + (r.stderr or ""))[-200:]
    lp_runner = os.path.join(tempfile.mkdtemp(prefix="gpu-broker-"), "runner.py")
    lp_job = os.path.join(os.path.dirname(lp_runner), "job.json")
    with open(lp_runner, "w", encoding="utf-8") as f:
        f.write(RUNNER_TEMPLATE.replace("__JOB_JSON__", json.dumps(job, ensure_ascii=False)))
    with open(lp_job, "w", encoding="utf-8") as f:
        f.write(json.dumps(job, ensure_ascii=False))
    r = scp_to_anolis(lp_runner, run_dir + "/runner.py")
    if r.returncode != 0:
        return False, None, "scp runner 失败：%s" % (r.stderr or "")[-160:]
    r = scp_to_anolis(lp_job, run_dir + "/job.json")
    if r.returncode != 0:
        return False, None, "scp job 失败：%s" % (r.stderr or "")[-160:]
    r = ssh_anolis("cd %s && python3 runner.py" % run_dir,
                   timeout=card["timeout_min"] * 60 + 120)
    if r.returncode != 0 and "RUNNER_DONE" not in (r.stdout or ""):
        return False, None, "代跑失败：%s" % (r.stdout + (r.stderr or ""))[-240:]
    r2 = ssh_anolis("cat %s/markers.jsonl 2>/dev/null" % run_dir, timeout=60)
    markers = []
    for ln in (r2.stdout or "").splitlines():
        s = ln.strip()
        if not s.startswith("{"):
            continue
        try:
            obj = json.loads(s)
        except ValueError:
            continue
        if isinstance(obj, dict) and obj.get("phase") in ("start", "end", "artifacts"):
            markers.append(obj)
    phases = [m.get("phase") for m in markers]
    if phases != ["start", "end", "artifacts"]:
        return False, markers, "markers 三行不齐（实读 %s）" % phases
    return True, markers, "anolis 代跑完成（markers 三行齐）"


# ---- 产物回传（scp ≤max_mb；超限 declare-only；双读 sha256 对账）------------
def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def transfer_artifacts(card, artifacts, max_mb, state_dir):
    """产物回传：auto=总量 ≤max_mb ⇒ scp 回传 + 本地复算 sha256 对账；
    超限 ⇒ declare-only（回清单+anolis 存放位置声明，按单取用，Q6 §2.4）。"""
    tid = card["ticket_id"]
    if not artifacts:
        return {"mode": "none", "artifacts": []}
    total = sum(a.get("size_bytes") or 0 for a in artifacts)
    if card.get("artifact_transfer") == "declare-only":
        return {"mode": "declare-only",
                "location": os.path.join(ANOLIS_RUN_ROOT, tid),
                "reason": "负载卡声明 declare-only（大产物不传，按单取用）",
                "artifacts": artifacts}
    if total > max_mb * 1048576:
        return {"mode": "declare-only",
                "location": os.path.join(ANOLIS_RUN_ROOT, tid),
                "reason": "产物总量 %d B > 回传上限 %d MB（不传，回清单+存放位置声明）"
                          % (total, max_mb),
                "artifacts": artifacts}
    dest = os.path.join(state_dir, "artifacts", tid)
    os.makedirs(dest, exist_ok=True)
    out = []
    for a in artifacts:
        lp = os.path.join(dest, os.path.basename(a["name"]))
        r = scp_from_anolis(os.path.join(ANOLIS_RUN_ROOT, tid, a["path"]), lp)
        if r.returncode != 0 or not os.path.isfile(lp):
            out.append(dict(a, transferred=False,
                            error="scp 回传失败：%s" % (r.stderr or "")[-160:]))
            continue
        local_sha = sha256_file(lp)
        out.append(dict(a, transferred=True, local_path=lp, sha256_local=local_sha,
                        sha256_match=(local_sha == a.get("sha256"))))
    return {"mode": "transferred", "artifacts": out}


# ---- 句柄（af.gpu-handle.v1；运行时状态件 0600；能力面=三动作）-------------
def handle_path(state_dir, ticket_id):
    return os.path.join(state_dir, "handles", ticket_id + ".json")


def handle_save(state_dir, rec):
    p = handle_path(state_dir, rec["ticket_id"])
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)
    os.chmod(p, 0o600)


def handle_load(state_dir, ticket_id):
    p = handle_path(state_dir, ticket_id)
    if not os.path.isfile(p):
        return None
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def issue_handle(state_dir, card, ttl_s, now_ts):
    """发放句柄：token 一次生成（值只入 0600 状态件+运营者交付面）；账本只带指纹。"""
    tok = secrets.token_urlsafe(32)
    fp = hashlib.sha256(tok.encode("utf-8")).hexdigest()[:12]
    rec = {"handle_id": "gh-" + card["ticket_id"], "ticket_id": card["ticket_id"],
           "task_ref": card["task_ref"], "requester": card["requester"],
           "token": tok, "token_fp": fp, "ttl_s": ttl_s,
           "issued_at": iso(now_ts), "expires_at": iso(now_ts + dt.timedelta(seconds=ttl_s)),
           "state": "open", "last_beat_at": None, "actions": [],
           "job": {"state": "queued", "markers": [], "report_lines": [],
                   "artifacts": None},
           "note": "句柄=一次性+TTL；能力面仅 heartbeat/status/artifacts 三动作"
                   "（Q6 §2.4 bot-lane claim_token 同形）；shell/exec/任意命令永不受理"}
    handle_save(state_dir, rec)
    return rec


def handle_action(state_dir, ticket_id, action, token, now_ts=None):
    """句柄分发器：词表外/state 非 open/token 不匹配/TTL 到期 ⇒ 一律拒
    （fail-closed）；三动作各司其职，动作日志入状态件（审计面）。"""
    now_ts = now_ts or now_utc()
    if action not in HANDLE_ACTIONS:
        return {"verdict": "reject", "issued": False,
                "reason": "action %r 不在句柄能力面 %s（GPU 直通/exec 永不受理，"
                          "Q6 §1.2 铁律）" % (action, list(HANDLE_ACTIONS))}
    rec = handle_load(state_dir, ticket_id)
    if rec is None:
        return {"verdict": "reject", "issued": False,
                "reason": "句柄不存在（ticket_id=%r）" % ticket_id}
    if rec.get("state") != "open":
        return {"verdict": "reject", "issued": False,
                "reason": "句柄 state=%s（已吊销/失效）" % rec.get("state")}
    if not hmac.compare_digest(str(token or ""), str(rec.get("token") or "")):
        return {"verdict": "reject", "issued": False, "reason": "token 不匹配（拒）"}
    exp = rtc.parse_iso_ts(rec["expires_at"], "句柄 expires_at")
    if now_ts >= exp:
        rec["state"] = "expired"
        handle_save(state_dir, rec)
        return {"verdict": "reject", "issued": False,
                "reason": "句柄 TTL 到期失效（%s；fail-closed，不续期）" % rec["expires_at"]}
    rec["actions"].append({"action": action, "ts": iso(now_ts)})
    rec["last_beat_at"] = iso(now_ts)
    if action == "heartbeat":
        handle_save(state_dir, rec)
        return {"verdict": "ok", "issued": True, "action": "heartbeat",
                "job_state": rec["job"]["state"], "expires_at": rec["expires_at"],
                "remaining_s": int((exp - now_ts).total_seconds())}
    if action == "status":
        handle_save(state_dir, rec)
        return {"verdict": "ok", "issued": True, "action": "status",
                "job": rec["job"], "expires_at": rec["expires_at"]}
    if action == "artifacts":
        man = rec["job"].get("artifacts")
        if man is None:
            return {"verdict": "reject", "issued": False,
                    "reason": "任务未结（artifacts 不可交；STALL 走心跳面判定）"}
        rec["job"]["artifacts"] = man
        handle_save(state_dir, rec)
        return {"verdict": "ok", "issued": True, "action": "artifacts",
                "artifacts": man}
    raise FailClosed("句柄分发不可达分支（词表外应在入口已拒）")


# ---- 主流程：负载卡全链 -----------------------------------------------------
def run_card(card_path, tasks_path, ledger_path, now_s, state_dir, max_mb):
    # 输入面加载：任一不可证 ⇒ fail-closed 拒发不猜绿（账本不可读宁停不猜）
    try:
        card = parse_card(rtc.load_json_strict(card_path, "负载卡"))
        snapshot = rtc.load_json_strict(tasks_path, "任务快照")
        rows = rtc.load_jsonl_strict(ledger_path, "账本")
        now_ts = rtc.parse_iso_ts(now_s, "--now") if now_s else now_utc()
    except FailClosed as e:
        print(json.dumps({"verdict": "reject", "issued": False, "stage": "load",
                          "fail_closed": str(e),
                          "note": "输入面不可证 ⇒ fail-closed 拒发（账本不可读宁停不猜）"},
                         ensure_ascii=False, indent=1))
        return RC_REJECT

    try:
        v, card_hours = check_admission(card, snapshot, rows, now_ts)
    except FailClosed as e:
        v = GpuVerdict()
        v.reject(str(e))
    out = v.render()
    out["ticket_id"] = card["ticket_id"]
    out["stage"] = "admission"
    if out["verdict"] == "reject":
        ledger_append([{"ts": iso(now_ts), "event": "reject",
                        "ticket_id": card["ticket_id"], "ticket_type": GPU_TICKET_TYPE,
                        "task_ref": card["task_ref"], "requester": card["requester"],
                        "reasons": [out.get("fail_closed")] if out.get("fail_closed")
                                   else out.get("reasons", []),
                        "note": "D-100 GPU 准入拒发（fail-closed 不猜绿；零发放零执行）"}],
                      ledger_path)
        out["ledger_reject_row"] = True
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return RC_REJECT
    if out["verdict"] == "queue":
        out["note"] = "准入硬顶/容量顶满：排队不并发，零账本行（Q6 §3.3）；容量释放后重跑本命令"
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return RC_QUEUE

    # approve ⇒ anolis 预检（空闲窗实测）
    probe = anolis_probe()
    if probe is None:
        v2 = GpuVerdict()
        v2.reject("anolis 预检不可证（ssh/读数失败 ⇒ fail-closed 不执行）")
        out2 = v2.render()
        out2.update({"ticket_id": card["ticket_id"], "stage": "preflight"})
        ledger_append([{"ts": iso(now_ts), "event": "reject",
                        "ticket_id": card["ticket_id"], "ticket_type": GPU_TICKET_TYPE,
                        "task_ref": card["task_ref"], "requester": card["requester"],
                        "reasons": [out2["fail_closed"]],
                        "note": "D-100 GPU 预检不可证拒发（fail-closed）"}], ledger_path)
        print(json.dumps(out2, ensure_ascii=False, indent=1))
        return RC_REJECT
    out["anolis_probe"] = probe
    v2 = check_preflight(card, probe)
    out2 = v2.render()
    out["preflight"] = out2
    if out2["verdict"] == "reject":
        ledger_append([{"ts": iso(now_ts), "event": "reject",
                        "ticket_id": card["ticket_id"], "ticket_type": GPU_TICKET_TYPE,
                        "task_ref": card["task_ref"], "requester": card["requester"],
                        "reasons": out2["reasons"],
                        "note": "D-100 GPU 预检结构性不足拒发（fail-closed）"}], ledger_path)
        out["verdict"] = "reject"
        out["issued"] = False
        out["stage"] = "preflight"
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return RC_REJECT
    if out2["verdict"] == "queue":
        out["verdict"] = "queue"
        out["issued"] = False
        out["queue_reason"] = out2["queue_reason"]
        out["stage"] = "preflight"
        out["note"] = "anolis 容量紧张：排队不硬闯，零账本行；空闲窗重跑本命令"
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return RC_QUEUE

    # 发放：三元绑定一次写死（task_ref × consumer × handle_fp）
    handle = issue_handle(state_dir, card, card["ttl_s"], now_ts)
    issue_row = {"ts": iso(now_ts), "event": "issue", "ticket_id": card["ticket_id"],
                 "task_ref": card["task_ref"], "requester": card["requester"],
                 "consumer": "gpu-exec-" + handle["token_fp"],
                 "key_fp": handle["token_fp"], "ticket_type": GPU_TICKET_TYPE,
                 "resource": GPU_RESOURCE,
                 "amount": {"max_req": 0, "max_input_tokens": 0,
                            "gpu_cards": card["gpu_cards"],
                            "card_hours": round(card_hours, 4),
                            "mem_budget_g": card["mem_budget_g"],
                            "disk_budget_g": card["disk_budget_g"],
                            "timeout_min": card["timeout_min"]},
                 "ttl_s": card["ttl_s"], "expires_at": handle["expires_at"],
                 "handle_id": handle["handle_id"],
                 "approved_by": "tools/gpu-broker-execute.py 五条准入机检+anolis 预检全过"
                                "（D-100；零 LLM——D9 接缝：auto-approve 集=机检全过，"
                                "fail-closed 原样）",
                 "purpose": card["purpose"],
                 "note": "GPU 票：句柄即票据（一次性+TTL，能力面仅三动作）；"
                         "amount.max_req/max_input_tokens 恒 0——GPU 票不走 LLM 网关"
                         "计量维，D-94 机检③④日限聚合天然零贡献（登记接缝）"}
    ledger_append([issue_row], ledger_path)

    ok, markers, ev = execute_on_anolis(card)
    if not ok:
        # 执行不可证：账本落 reject + revoke 行（在飞位释放，防准入账本卡死）+ 句柄置 failed
        ledger_append([{"ts": iso(now_utc()), "event": "reject",
                        "ticket_id": card["ticket_id"], "ticket_type": GPU_TICKET_TYPE,
                        "task_ref": card["task_ref"], "requester": card["requester"],
                        "reasons": [ev],
                        "note": "D-100 GPU 代跑不可证（fail-closed；票据已发放但执行未证）"},
                       {"ts": iso(now_utc()), "event": "revoke",
                        "ticket_id": card["ticket_id"], "ticket_type": GPU_TICKET_TYPE,
                        "task_ref": card["task_ref"], "reason": "execute-unproven（在飞位释放）",
                        "revoked_by": "tools/gpu-broker-execute.py（执行不可证即释放，防准入卡死）"}],
                      ledger_path)
        handle["job"]["state"] = "failed"
        handle["job"]["markers"] = markers or []
        handle_save(state_dir, handle)
        out.update({"verdict": "reject", "issued": False, "stage": "execute",
                    "fail_closed": ev})
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return RC_REJECT

    # 三行回报（执行器读数）+ 产物回传
    start, end, arts = markers[0], markers[1], markers[2]
    transfer = transfer_artifacts(card, arts.get("artifacts") or [], max_mb, state_dir)
    report_lines = [
        {"phase": "start", "ts": start.get("ts"), "gpu_cards": start.get("gpu_cards"),
         "mem_budget_g": start.get("mem_budget_g"), "disk_budget_g": start.get("disk_budget_g"),
         "timeout_min": start.get("timeout_min"),
         "cuda_visible_devices": start.get("cuda_visible_devices")},
        {"phase": "end", "ts": end.get("ts"), "exit_code": end.get("exit_code"),
         "timed_out": end.get("timed_out"), "duration_s": end.get("duration_s"),
         "peak_rss_g": end.get("peak_rss_g"), "gpu_peak_mem_mib": end.get("gpu_peak_mem_mib"),
         "gpu_peak_util_pct": end.get("gpu_peak_util_pct")},
        {"phase": "artifacts", "ts": arts.get("ts"), "artifacts": arts.get("artifacts")}]
    meter_rows = []
    for i, ln in enumerate(report_lines):
        row = {"ts": ln.get("ts") or iso(now_utc()), "event": "meter",
               "ticket_id": card["ticket_id"], "req_delta": 0, "input_tokens": 0,
               "source": "gpu-broker-execute（anolis 执行器读数；沙箱自报只是参考值）"}
        row.update({k: v2 for k, v2 in ln.items() if k != "ts"})
        meter_rows.append(row)
    revoke_row = {"ts": iso(now_utc()), "event": "revoke",
                  "ticket_id": card["ticket_id"], "ticket_type": GPU_TICKET_TYPE,
                  "task_ref": card["task_ref"],
                  "reason": "gpu-executed-complete（exit_code=%s；在飞位释放，"
                            "句柄 TTL 内仍可三动作查询）" % end.get("exit_code"),
                  "revoked_by": "tools/gpu-broker-execute.py（执行器三行回报后）",
                  "note": "摘行即断同 D-94 语义：票据不携带密码学权力，回收不依赖沙箱配合"}
    ledger_append(meter_rows + [revoke_row], ledger_path)

    handle["job"].update({"state": "done" if end.get("exit_code") == 0 else "failed",
                          "markers": markers, "report_lines": report_lines,
                          "artifacts": transfer})
    handle_save(state_dir, handle)

    out.update({"verdict": "approve", "issued": True, "stage": "done",
                "card_hours": round(card_hours, 4),
                "handle": {"handle_id": handle["handle_id"],
                           "token_fp": handle["token_fp"],
                           "expires_at": handle["expires_at"],
                           "state_file": handle_path(state_dir, card["ticket_id"]),
                           "delivery": "token 值只在 0600 状态件内；运营者现取一次性注入"
                                       "沙箱会话首条消息（禁入账本/issue/PR/argv）"},
                "report_lines": report_lines, "artifacts_transfer": transfer,
                "ledger_rows": 1 + len(meter_rows) + 1})
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return RC_APPROVE


# ---- selftest（内嵌夹具；DRY 桩零生产触达）----------------------------------
def _cp(stdout="", stderr="", rc=0):
    return subprocess.CompletedProcess(args=[], returncode=rc, stdout=stdout, stderr=stderr)


class MockAnolis(object):
    """anolis 桩：录调用 + 脚本化回放（预检值/markers）；零 ssh/scp 真连。"""

    def __init__(self, markers=None, probe_rc=0):
        self.cmds = []
        self.scp_to, self.scp_from = [], []
        self.markers = markers or []
        self.probe_rc = probe_rc
        self.fake_remote = tempfile.mkdtemp(prefix="gpu-broker-fake-anolis-")

    def __call__(self, cmd, timeout=180):
        self.cmds.append(cmd)
        if "nvidia-smi --query-gpu=memory.total" in cmd:
            if self.probe_rc != 0:
                return _cp(stdout="", rc=self.probe_rc)
            return _cp(stdout="32768, 0\n32768, 0\n112\n107\n")
        if cmd.startswith("cat ") and "markers.jsonl" in cmd:
            return _cp(stdout="\n".join(json.dumps(m, ensure_ascii=False)
                                         for m in self.markers))
        return _cp(stdout="OK\n")

    def scp_to_fn(self, lp, rp, timeout=180):
        self.scp_to.append((lp, rp))
        return _cp(rc=0)

    def scp_from_fn(self, rp, lp, timeout=300):
        self.scp_from.append((rp, lp))
        # 从假 anolis 目录取（桩预置产物）
        src = os.path.join(self.fake_remote, os.path.basename(rp))
        if os.path.isfile(src):
            os.makedirs(os.path.dirname(lp) or ".", exist_ok=True)
            with open(src, "rb") as f:
                data = f.read()
            with open(lp, "wb") as f:
                f.write(data)
        return _cp(rc=0)


def selftest():
    global DRY
    results = []

    def check(name, cond, detail=""):
        results.append((name, bool(cond), detail))
        print("%s %s%s" % ("PASS" if cond else "FAIL", name,
                           ("｜" + detail) if detail and not cond else ""))

    tmp = tempfile.mkdtemp(prefix="gpu-broker-selftest-")
    ledger = os.path.join(tmp, "resource-ledger.jsonl")
    state = os.path.join(tmp, "state")
    open(ledger, "w", encoding="utf-8").write(json.dumps(
        {"ts": "2026-11-07T00:00:00Z", "event": "ledger-open",
         "schema": "af.resource-ledger.v2", "note": "fixture"}) + "\n")
    base_card = {"schema": CARD_SCHEMA, "ticket_id": "selftest-gpu-01",
                 "task_ref": "factory-os#32", "requester": "worker-a",
                 "purpose": "自测夹具", "repo": "https://github.com/CloudCrane-Software/factory-os.git",
                 "commit": "HEAD", "command": "echo hi",
                 "mem_budget_g": 8, "gpu_cards": 1, "disk_budget_g": 5,
                 "timeout_min": 10, "ttl_ask": "2h",
                 "artifacts": [{"name": "a.txt", "path": "out/a.txt"}]}
    base_tasks = {"schema": rtc.TASKS_SCHEMA, "generated_at": "2026-11-07T00:00:00Z",
                  "source": "fixture",
                  "tasks": [{"task_ref": "factory-os#32", "state": "running",
                             "inflight_identity": "worker-a"}]}
    now = dt.datetime(2026, 11, 7, 12, 0, 0, tzinfo=dt.timezone.utc)

    def admit(card=None, tasks=None, rows=None):
        # 先过 parse_card 形态面（schema/必填/路径逃逸/凭据直嵌/TTL），再跑五条准入
        try:
            parsed = parse_card(dict(base_card, **(card or {})))
            v, _ = check_admission(parsed, tasks or base_tasks,
                                   rows if rows is not None else [], now)
            return v.render()
        except FailClosed as e:
            v = GpuVerdict()
            v.reject(str(e))
            return v.render()

    # ①-⑤ 正例
    r = admit()
    check("admission:五条全过approve", r["verdict"] == "approve" and r["issued"] is True,
          json.dumps(r, ensure_ascii=False))
    # ② 单票上限负例族
    for name, over in (("mem", dict(mem_budget_g=32)), ("disk", dict(disk_budget_g=25)),
                       ("timeout", dict(timeout_min=180)), ("cards", dict(gpu_cards=3)),
                       ("card_hours", dict(gpu_cards=2, timeout_min=120))):
        r = admit(card=dict(base_card, **over))
        check("neg:单票超限-%s⇒reject" % name,
              r["verdict"] == "reject" and not r["issued"], json.dumps(r, ensure_ascii=False))
    # ① 任务面负例
    r = admit(card=dict(base_card, task_ref="factory-os#999"))
    check("neg:task_ref不在飞⇒reject", r["verdict"] == "reject")
    r = admit(card=dict(base_card, requester="worker-b"))
    check("neg:身份不一致⇒reject", r["verdict"] == "reject")
    # ③ 每沙箱在飞负例
    rows = [{"ts": "2026-11-07T01:00:00Z", "event": "issue",
             "ticket_id": "gpu-x", "task_ref": "factory-os#32", "requester": "worker-a",
             "consumer": "gpu-exec-fp", "key_fp": "fp0000000000",
             "ticket_type": GPU_TICKET_TYPE,
             "amount": {"max_req": 0, "max_input_tokens": 0, "gpu_cards": 1,
                        "card_hours": 0.2, "mem_budget_g": 8, "disk_budget_g": 5,
                        "timeout_min": 10},
             "ttl_s": 7200, "expires_at": "2026-11-07T03:00:00Z"}]
    r = admit(rows=rows)
    check("neg:每沙箱1张在飞⇒reject", r["verdict"] == "reject" and not r["issued"])
    # ④ 全局日限负例（当日已 7.9 卡·时 + 本次 0.17 ⇒ 超 8）
    rows2 = [{"ts": "2026-11-07T01:00:00Z", "event": "issue", "ticket_id": "gpu-y",
              "task_ref": "factory-os#33", "requester": "worker-z",
              "consumer": "gpu-exec-fp2", "key_fp": "fp0000000001",
              "ticket_type": GPU_TICKET_TYPE,
              "amount": {"max_req": 0, "max_input_tokens": 0, "gpu_cards": 2,
                         "card_hours": 7.9, "mem_budget_g": 8, "disk_budget_g": 5,
                         "timeout_min": 10},
              "ttl_s": 7200, "expires_at": "2026-11-07T03:00:00Z"}]
    r = admit(rows=rows2)
    check("neg:全局日限超⇒reject", r["verdict"] == "reject" and not r["issued"])
    # ④ Σmem 顶 ⇒ queue（在飞 40G + 本次 8G > 45G）
    rows3 = [{"ts": "2026-11-07T01:00:00Z", "event": "issue", "ticket_id": "gpu-m",
              "task_ref": "factory-os#34", "requester": "worker-m",
              "consumer": "gpu-exec-fp3", "key_fp": "fp0000000002",
              "ticket_type": GPU_TICKET_TYPE,
              "amount": {"max_req": 0, "max_input_tokens": 0, "gpu_cards": 1,
                         "card_hours": 0.2, "mem_budget_g": 40, "disk_budget_g": 5,
                         "timeout_min": 10},
              "ttl_s": 7200, "expires_at": "2026-11-07T03:00:00Z"}]
    r = admit(rows=rows3)
    check("queue:Σmem超45⇒排队不并发", r["verdict"] == "queue" and not r["issued"],
          json.dumps(r, ensure_ascii=False))
    # ④ 并发顶 ⇒ queue（4 张在飞 + 本次）
    rows4 = []
    for k in range(4):
        rows4.append({"ts": "2026-11-07T01:00:00Z", "event": "issue",
                      "ticket_id": "gpu-c%d" % k, "task_ref": "factory-os#3%d" % k,
                      "requester": "worker-c%d" % k, "consumer": "gpu-exec-fpc%d" % k,
                      "key_fp": "fp000000000%d" % (3 + k), "ticket_type": GPU_TICKET_TYPE,
                      "amount": {"max_req": 0, "max_input_tokens": 0, "gpu_cards": 1,
                                 "card_hours": 0.1, "mem_budget_g": 4, "disk_budget_g": 5,
                                 "timeout_min": 10},
                      "ttl_s": 7200, "expires_at": "2026-11-07T03:00:00Z"})
    r = admit(rows=rows4)
    check("queue:并发超4⇒排队不并发", r["verdict"] == "queue" and not r["issued"])
    # ⑤ hold 负例
    rows5 = [{"ts": "2026-11-07T01:00:00Z", "event": "hold", "scope": "requester",
              "target": "worker-a", "reason": "fixture 停用"}]
    r = admit(rows=rows5)
    check("neg:停用hold⇒reject", r["verdict"] == "reject" and not r["issued"])
    # fail-closed 族
    r = admit(card=dict(base_card, schema="af.gpu-load-card.v0"))
    check("failclosed:card schema 词表外⇒reject", r["verdict"] == "reject")
    r = admit(card=dict(base_card, command=""))
    check("failclosed:command 空⇒reject", r["verdict"] == "reject")
    r = admit(card=dict(base_card, artifacts=[{"name": "a", "path": "../escape"}]))
    check("failclosed:产物路径逃逸⇒reject", r["verdict"] == "reject")
    r = admit(card=dict(base_card, repo="https://u:p@evil.example/x.git"))
    check("failclosed:repo 直嵌凭据⇒reject", r["verdict"] == "reject")
    bad_rows = [{"ts": "2026-11-07T01:00:00Z", "event": "issue", "ticket_id": "gpu-b"}]  # 缺字段
    r = admit(rows=bad_rows)
    check("failclosed:账本坏行⇒reject（宁停不猜）", r["verdict"] == "reject")
    r = admit(card=dict(base_card, ttl_ask="6h"))
    check("failclosed:句柄 TTL 超 4h⇒reject", r["verdict"] == "reject")

    # 句柄三动作 + 能力面负例
    tok_env = "GPU_HANDLE_TOKEN"
    os.environ[tok_env] = ""
    card_path = os.path.join(tmp, "card.json")
    tasks_path = os.path.join(tmp, "tasks.json")
    json.dump(base_card, open(card_path, "w", encoding="utf-8"))
    json.dump(base_tasks, open(tasks_path, "w", encoding="utf-8"))
    markers = [{"phase": "start", "ts": "2026-11-07T04:00:00Z", "ticket_id": "selftest-gpu-01",
                "gpu_cards": 1, "mem_budget_g": 8, "disk_budget_g": 5, "timeout_min": 10,
                "cuda_visible_devices": "0"},
               {"phase": "end", "ts": "2026-11-07T04:00:05Z", "exit_code": 0,
                "timed_out": False, "duration_s": 5.0, "peak_rss_g": 0.05,
                "gpu_peak_mem_mib": 512, "gpu_peak_util_pct": 7},
               {"phase": "artifacts", "ts": "2026-11-07T04:00:06Z",
                "artifacts": [{"name": "a.txt", "path": "out/a.txt", "size_bytes": 3,
                               "sha256": hashlib.sha256(b"hi\n").hexdigest()}]}]
    mock = MockAnolis(markers=markers)
    DRY["on"], DRY["ssh_fn"] = True, mock
    DRY["scp_to_fn"], DRY["scp_from_fn"] = mock.scp_to_fn, mock.scp_from_fn
    DRY["sh_fn"] = lambda cmd, timeout=120: _cp(rc=0)
    # 预置假 anolis 产物（桩 scp_from 取源）
    os.makedirs(os.path.join(mock.fake_remote, "out"), exist_ok=True)
    with open(os.path.join(mock.fake_remote, "a.txt"), "wb") as f:
        f.write(b"hi\n")
    try:
        rc = run_card(card_path, tasks_path, ledger, "2026-11-07T12:00:00Z", state, 64)
        check("chain:全链 rc=0", rc == RC_APPROVE)
        rows_after = rtc.load_jsonl_strict(ledger, "夹具账本")
        evs = [r.get("event") for r in rows_after]
        check("chain:账本 issue+meter×3+revoke", evs == ["ledger-open", "issue", "meter",
                                                          "meter", "meter", "revoke"], str(evs))
        issue_row = rows_after[1]
        check("chain:三元绑定一次写死",
              issue_row.get("consumer") == "gpu-exec-" + issue_row["key_fp"]
              and issue_row["amount"]["max_req"] == 0
              and issue_row["ticket_type"] == GPU_TICKET_TYPE)
        meter_rows = [r for r in rows_after if r.get("event") == "meter"]
        check("chain:meter 三行 phase 齐",
              [r.get("phase") for r in meter_rows] == ["start", "end", "artifacts"])
        end_row = [r for r in meter_rows if r.get("phase") == "end"][0]
        check("chain:end 行执行器读数（退出码+峰值）",
              end_row.get("exit_code") == 0 and end_row.get("peak_rss_g") == 0.05
              and end_row.get("gpu_peak_mem_mib") == 512)
        arts_row = [r for r in meter_rows if r.get("phase") == "artifacts"][0]
        check("chain:artifacts 行带 sha256",
              arts_row["artifacts"][0]["sha256"] == hashlib.sha256(b"hi\n").hexdigest())
        lp = os.path.join(state, "artifacts", "selftest-gpu-01", "a.txt")
        check("chain:产物回传+双读一致",
              os.path.isfile(lp) and sha256_file(lp) == hashlib.sha256(b"hi\n").hexdigest())
        check("chain:代跑只认 alias（零 IP 直连）",
              all("100.64" not in c for c in mock.cmds))
        check("chain:runner 经 scp 运输（禁内联长命令）", len(mock.scp_to) == 2)
        # 句柄动作（token 经 env，禁 argv）
        rec = handle_load(state, "selftest-gpu-01")
        os.environ[tok_env] = rec["token"]
        a = handle_action(state, "selftest-gpu-01", "status", rec["token"], now)
        check("handle:status ok", a["verdict"] == "ok" and a["job"]["state"] == "done")
        a = handle_action(state, "selftest-gpu-01", "heartbeat", rec["token"], now)
        check("handle:heartbeat ok", a["verdict"] == "ok" and a["remaining_s"] > 0)
        a = handle_action(state, "selftest-gpu-01", "artifacts", rec["token"], now)
        check("handle:artifacts ok", a["verdict"] == "ok" and a["artifacts"]["mode"] == "transferred")
        for bad_act in ("shell", "exec", "run", "shell:exec"):
            a = handle_action(state, "selftest-gpu-01", bad_act, rec["token"], now)
            check("handle:能力面负例-%s⇒拒" % bad_act,
                  a["verdict"] == "reject" and not a["issued"], json.dumps(a, ensure_ascii=False))
        a = handle_action(state, "selftest-gpu-01", "status", "wrong-token-value", now)
        check("handle:token 不匹配⇒拒", a["verdict"] == "reject")
        a = handle_action(state, "no-such-ticket", "status", rec["token"], now)
        check("handle:句柄不存在⇒拒", a["verdict"] == "reject")
        # TTL 到期 ⇒ 拒（不续期；句柄 ttl_ask=2h，此刻 +7201s）
        later = now + dt.timedelta(seconds=2 * 3600 + 1)
        a = handle_action(state, "selftest-gpu-01", "status", rec["token"], later)
        check("handle:TTL 到期⇒拒（fail-closed 不续期）", a["verdict"] == "reject")
        # 拒发负例实跑（超单票 mem ⇒ reject 行落账）
        over_path = os.path.join(tmp, "card-over.json")
        json.dump(dict(base_card, ticket_id="selftest-gpu-over", mem_budget_g=32),
                  open(over_path, "w", encoding="utf-8"))
        rc2 = run_card(over_path, tasks_path, ledger, "2026-11-07T12:00:00Z", state, 64)
        check("neg:超限拒发实跑 rc=2", rc2 == RC_REJECT)
        rows_neg = rtc.load_jsonl_strict(ledger, "夹具账本")
        check("neg:拒发落 reject 行（审计面）",
              any(r.get("event") == "reject" and r.get("ticket_id") == "selftest-gpu-over"
                  for r in rows_neg))
    finally:
        DRY["on"], DRY["ssh_fn"], DRY["scp_to_fn"] = False, None, None
        DRY["scp_from_fn"], DRY["sh_fn"] = None, None
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(mock.fake_remote, ignore_errors=True)
    bad = [n for n, c, _ in results if not c]
    print("selftest %d/%d 过%s" % (len(results) - len(bad), len(results),
                                   ("｜FAIL:" + ",".join(bad)) if bad else ""))
    return 0 if not bad else 1


def main():
    ap = argparse.ArgumentParser(description="GPU broker 执行器最小件（D-100；五条准入 fail-closed）")
    ap.add_argument("--card", help="负载卡 JSON（af.gpu-load-card.v1）")
    ap.add_argument("--tasks", help="在飞任务快照 JSON（af.task-snapshot.v1；harness 经 API 生成）")
    ap.add_argument("--ledger", default=rtc.DEFAULT_LEDGER, help="账本 jsonl（默认 账本/resource-ledger.jsonl）")
    ap.add_argument("--now", help="ISO8601 现时刻覆盖（仅自测/复核用，形 2026-11-07T12:00:00Z）")
    ap.add_argument("--state-dir", default=os.path.join(os.path.expanduser("~"), ".gpu-broker-state"),
                    help="句柄/产物运行时状态目录（0600；默认 ~/.gpu-broker-state）")
    ap.add_argument("--max-transfer-mb", type=int, default=64, help="产物回传总量上限 MB（超 ⇒ declare-only）")
    ap.add_argument("--handle", help="句柄 ticket_id（三动作入口）")
    ap.add_argument("--action", choices=list(HANDLE_ACTIONS), help="句柄动作（能力面全集）")
    ap.add_argument("--token-env", default="GPU_HANDLE_TOKEN", help="句柄 token 环境变量名（禁 argv）")
    ap.add_argument("--token-file", help="句柄 token 文件路径（替代 env）")
    ap.add_argument("--selftest", action="store_true", help="内嵌夹具自测（DRY 桩零生产触达）")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(selftest())
    if a.handle:
        if not a.action:
            ap.error("--handle 需配 --action（能力面：%s）" % "/".join(HANDLE_ACTIONS))
        if a.token_file:
            with open(a.token_file, "r", encoding="utf-8") as f:
                handle_val = f.read().strip()
        else:
            handle_val = os.environ.get(a.token_env, "")
        if not handle_val:
            print(json.dumps({"verdict": "reject", "issued": False,
                              "reason": "句柄口令未提供（经 --token-env/--token-file；禁 argv）"},
                             ensure_ascii=False))
            sys.exit(RC_REJECT)
        out = handle_action(a.state_dir, a.handle, a.action, handle_val)
        print(json.dumps(out, ensure_ascii=False, indent=1))
        sys.exit(RC_APPROVE if out.get("verdict") == "ok" else RC_REJECT)
    if not a.card or not a.tasks:
        ap.error("实跑需 --card 与 --tasks（句柄动作用 --handle/--action；自测用 --selftest）")
    rc = run_card(a.card, a.tasks, a.ledger, a.now, a.state_dir, a.max_transfer_mb)
    sys.exit(rc)


if __name__ == "__main__":
    main()
