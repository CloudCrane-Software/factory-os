#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""外派注册表 v1（权威面 af-state/dispatch/registry.json）—— P1 新建面。

为什么建（依据 30-工件/外派-bot-试点/长效机制方案-draft.md §3.1/§3.4/§3.5 + D-决议 D1/D11）：
  · §3.1：注册表是**单一权威面**（任务登记 + 占用真源）；人读面
    （30-工件/外派-bot-试点/外派登记.json）由它导出，**文件名与字段名不变**（D11）⇒ 主会话读法不动。
  · §3.4：统一态消除「三套在役词汇」洞⑥。本件实现 D-决议点名的链式子集：
    queued → packaged → published → claimed → submitted → adjudicated → merged|rejected。
  · §3.5：单一写者（flock）+ 原子落盘（tmp + os.replace）+ 幂等（同态重放 = 同结果，不产生第二份）。
  · I5 fail-closed：注册表读不出/写不进 ⇒ rc=2，不猜绿。
  · 复用优先（复用-first 口径）：注册表 = 台账（债号权威）× 外派登记.json（人读投影），
    本件不新造第三套词汇，只做「权威面 + 导出」薄层。

schema（v1；字段名即 P1 决议点名，**不得改名、不得加字段**）：
  {
    "schema_version": 1,
    "tasks": {
      "<task_id>": {
        "debt_id":      "RT-E82",     # 债号（无债号的活不许外派：§3.1）
        "channel":      "bot",        # 通道（bot / factory / anolis-grok …）
        "state":        "published",  # 统一态（见 STATES）
        "base_sha":     "04f4d99…",   # 基线；未切片时允许空串
        "claimed_by":   null,         # 领取者（无主 = null）
        "claimed_at":   null,         # 领取时刻（ISO8601 字符串）
        "verdict":      null,         # 裁决结论（非流转态的审计结论也落这里，如 audited-green-content）
        "receipt_path": null,         # 收益记录路径（收割机产物）
        "value": {"increments": 0, "review_min": 0}   # 价值读数（G5 记账面；由 dispatch-value-gate.py 写）
      }
    },
    "meta": {"calibration": {}}         # 校准账（G5 决策流水；由 tools/dispatch-value-gate.py 写）
  }

命令：
  add           登记一笔新外派（幂等：同 task_id 同内容重放 = 同结果，不产生第二份）
  transition    状态机推进（**非法转移必红 rc=1**；同态重放 = 幂等 rc=0）
  verify        结构 + 状态机合法性体检（红逐条点名）
  export        从注册表重新生成人读面 30-工件/外派-bot-试点/外派登记.json（字段名不变、不丢字段）
  import-ledger bootstrap：把人读面导入注册表（seed 用，一次性；默认不覆盖既有注册表）
  show          打印注册表
  --selftest    内嵌夹具自测（零真文件读取；非法转移必红必被断言；导出兼容三笔必被断言）

退出码：0=绿/成功；1=红（非法转移/结构错/导出冲突）；2=不可证（缺件/写不进，fail-closed）。
本件零网络、零凭据正文；**不改** bot-reclaim / bot-scrub / bot-slice（止血批在飞）。
"""
import errno
import fcntl
import json
import os
import re
import shutil
import sys
import tempfile
import time

# ---------------------------------------------------------------- 常量

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGISTRY_PATH = os.path.join(ROOT, "af-state", "dispatch", "registry.json")
LEDGER_JSON = os.path.join(ROOT, "30-工件", "外派-bot-试点", "外派登记.json")

SCHEMA_VERSION = 1

# §3.4 统一态（链式子集）+ 终态
STATES = ["queued", "packaged", "published", "claimed", "submitted",
          "adjudicated", "merged", "rejected"]

# 合法转移（§3.4 链 + 裁决后可合线/驳回）。同态重放不在此表 ⇒ 走幂等分支（不算非法）。
LEGAL_TRANSITIONS = {
    "queued":      ["packaged"],
    "packaged":    ["published"],
    "published":   ["claimed"],
    "claimed":     ["submitted"],
    "submitted":   ["adjudicated"],
    "adjudicated": ["merged", "rejected"],
    "merged":      [],
    "rejected":    [],
}

TASK_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")   # 收紧到 bot-slice.sh 的形状闸（§3.5）
TASK_KEYS = ["debt_id", "channel", "state", "base_sha", "claimed_by",
             "claimed_at", "verdict", "receipt_path", "value"]
VALUE_KEYS = ["increments", "review_min"]

# 「无债号的活不许外派」占位词（§3.1）
EMPTY_DEBT_TOKENS = {"", "-", "—", "无", "none", "null", "nil", "n/a", "na",
                      "待定", "tbd", "todo", "?", "？"}

# 人读面老词 → 统一态（§3.4 映射表；老词里非流转态的进 verdict 字段）
LEGACY_TO_UNIFIED = {
    "brief-ready-awaiting-hang": "queued",
    "queued": "queued",
    "packaged": "packaged",
    "published-awaiting-bot": "published",
    "published": "published",
    "claimed": "claimed",
    "submitted": "submitted",
    "reclaimed": "adjudicated",
    "adjudicated": "adjudicated",
    "audited-green-content": "adjudicated",   # §3.4：审计结论落在 reviewing→adjudicated 的结果字段
    "merged": "merged",
    "rejected": "rejected",
}
# 非流转态（审计结论/改道/待发）⇒ 落 verdict，导出时原样回写（不丢信息）
NON_FLOW_LEGACY = {"audited-green-content", "folded-factory", "brief-ready-awaiting-hang"}

# 统一态 → 人读面老词（导出用；§3.4 + 外派登记.json 的 state_machine 词表）
UNIFIED_TO_LEGACY = {
    "queued": "brief-ready-awaiting-hang",
    "packaged": "packaged-awaiting-publish",
    "published": "published-awaiting-bot",
    "claimed": "claimed",
    "submitted": "submitted",
    "adjudicated": "reclaimed",
    "merged": "merged",
    "rejected": "rejected",
}


# ---------------------------------------------------------------- 基础工具

def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def empty_registry():
    return {"schema_version": SCHEMA_VERSION, "tasks": {}, "meta": {"calibration": {}}}


def load_registry(path):
    """读注册表。返回 (data, err)。err 非空 ⇒ 不可证（fail-closed）。"""
    if not os.path.exists(path):
        return None, "注册表不存在：%s" % path
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:                      # noqa: BLE001 —— 读不动就是不可证
        return None, "注册表不可解析：%s（%s）" % (path, exc)
    if not isinstance(data, dict):
        return None, "注册表根不是对象：%s" % path
    return data, None


def write_atomic(path, data, indent=1, trailing_newline=False):
    """原子落盘：同目录 tmp + os.replace（§3.5 写面纪律）。"""
    d = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".registry-", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)
            if trailing_newline:
                f.write("\n")
        os.chmod(tmp, 0o644)          # mkstemp 默认 600；工作区面按 0644（与 af-state 其它件同）
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


class WriteLock(object):
    """单一写者锁（§3.5）：同目录 registry.lock + flock（无锁则失败，不静默降级）。"""

    def __init__(self, path):
        self.path = os.path.join(os.path.dirname(os.path.abspath(path)), "registry.lock")
        self.fh = None

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.fh = open(self.path, "a+")
        try:
            fcntl.flock(self.fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.fh.close()
            self.fh = None
            if exc.errno in (errno.EACCES, errno.EAGAIN):
                raise RuntimeError("写锁被占（另一写者在飞）：%s" % self.path)
            raise
        return self

    def __exit__(self, *exc):
        if self.fh:
            try:
                fcntl.flock(self.fh.fileno(), fcntl.LOCK_UN)
            finally:
                self.fh.close()
                self.fh = None
        return False


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_opt_str(v):
    return v is None or isinstance(v, str)


# ---------------------------------------------------------------- 体检（verify）

def verify_registry(data):
    """结构 + 状态机合法性体检。返回 (errors, warnings)，errors 非空 ⇒ 红。"""
    errors = []
    warns = []

    if not isinstance(data, dict):
        return ["注册表根不是对象"], warns
    top = sorted(data.keys())
    if top != sorted(["schema_version", "tasks", "meta"]):
        errors.append("顶层键集错：%s（应为 schema_version/tasks/meta）" % top)
    if data.get("schema_version") != SCHEMA_VERSION:
        errors.append("schema_version 错：%r（应为 %d）" % (data.get("schema_version"), SCHEMA_VERSION))
    tasks = data.get("tasks")
    if not isinstance(tasks, dict):
        errors.append("tasks 不是对象：%r" % type(tasks).__name__)
        tasks = {}
    meta = data.get("meta")
    if not isinstance(meta, dict):
        errors.append("meta 不是对象：%r" % type(meta).__name__)
    else:
        cal = meta.get("calibration")
        if not isinstance(cal, dict):
            errors.append("meta.calibration 不是对象：%r" % type(cal).__name__)
        elif "g5" in cal:
            g5 = cal.get("g5")
            if not isinstance(g5, dict):
                errors.append("meta.calibration.g5 不是对象")
            else:
                for k in ("threshold", "continue_count", "pause_count"):
                    if not is_int(g5.get(k)):
                        errors.append("meta.calibration.g5.%s 不是整数：%r" % (k, g5.get(k)))
                if not isinstance(g5.get("decisions"), list):
                    errors.append("meta.calibration.g5.decisions 不是列表")

    for tid, t in sorted(tasks.items()):
        tag = "tasks[%s]" % tid
        if not isinstance(tid, str) or not TASK_ID_RE.match(tid):
            errors.append("%s：task_id 形状不合闸 %r（应 %s）" % (tag, tid, TASK_ID_RE.pattern))
        if not isinstance(t, dict):
            errors.append("%s：任务体不是对象" % tag)
            continue
        keys = sorted(t.keys())
        if keys != sorted(TASK_KEYS):
            errors.append("%s：字段集错：%s（应为 %s）" % (tag, keys, sorted(TASK_KEYS)))
        # 逐字段类型
        debt = t.get("debt_id")
        if not isinstance(debt, str):
            errors.append("%s.debt_id 不是字符串：%r" % (tag, debt))
        elif debt.strip().lower() in EMPTY_DEBT_TOKENS:
            errors.append("%s.debt_id 空债号（无债号的活不许外派：§3.1）" % tag)
        if not isinstance(t.get("channel"), str) or not t.get("channel").strip():
            errors.append("%s.channel 空或非字符串：%r" % (tag, t.get("channel")))
        state = t.get("state")
        if state not in STATES:
            errors.append("%s.state 非法态：%r（合法：%s）" % (tag, state, STATES))
        if not isinstance(t.get("base_sha"), str):
            errors.append("%s.base_sha 不是字符串：%r" % (tag, t.get("base_sha")))
        for k in ("claimed_by", "claimed_at", "verdict", "receipt_path"):
            if not is_opt_str(t.get(k)):
                errors.append("%s.%s 既非字符串也非 null：%r" % (tag, k, t.get(k)))
        val = t.get("value")
        if not isinstance(val, dict):
            errors.append("%s.value 不是对象：%r" % (tag, val))
        else:
            if sorted(val.keys()) != sorted(VALUE_KEYS):
                errors.append("%s.value 字段集错：%s（应为 %s）"
                              % (tag, sorted(val.keys()), sorted(VALUE_KEYS)))
            for k in VALUE_KEYS:
                if not is_int(val.get(k)) or val.get(k) < 0:
                    errors.append("%s.value.%s 非非负整数：%r" % (tag, k, val.get(k)))
        # 状态机一致性（字段存在性 ⇔ 流转位置的必要条件）
        if state in ("claimed", "submitted", "adjudicated", "merged", "rejected"):
            if not (t.get("claimed_by") or "").strip():
                errors.append("%s：state=%s 但 claimed_by 空（无人认领的流转态）" % (tag, state))
        if state in ("queued", "packaged", "published"):
            if (t.get("claimed_by") or "").strip():
                errors.append("%s：state=%s 但 claimed_by 非空（未领取态不得有主）" % (tag, state))
        if state in ("submitted", "adjudicated", "merged", "rejected"):
            if not (t.get("receipt_path") or "").strip():
                errors.append("%s：state=%s 但 receipt_path 空（交卷后必留收益记录）" % (tag, state))
        if state in ("adjudicated", "merged", "rejected"):
            if not (t.get("verdict") or "").strip():
                errors.append("%s：state=%s 但 verdict 空（裁决态必留结论）" % (tag, state))
        # 软提示（不判红）
        if (t.get("claimed_by") or "").strip() and not (t.get("claimed_at") or "").strip():
            warns.append("%s：claimed_by 有但 claimed_at 空（领取时刻未知）" % tag)
        if state in ("packaged", "published") and not (t.get("base_sha") or "").strip():
            warns.append("%s：state=%s 但 base_sha 空（发布前基线应已钉）" % (tag, state))
        if (val or {}).get("increments") and not (t.get("receipt_path") or "").strip():
            warns.append("%s：value.increments>0 但 receipt_path 空（增量无来源指针）" % tag)
    return errors, warns


# ---------------------------------------------------------------- 命令：add

def cmd_add(args, out):
    path = args.registry
    tid = args.task_id
    if not tid:
        out.append("RED add：--task-id 必填")
        return 1
    if not TASK_ID_RE.match(tid):
        out.append("RED add：task_id 形状不合闸 %r（应 %s；§3.5 收紧到 bot-slice 形状）"
                   % (tid, TASK_ID_RE.pattern))
        return 1
    if not (args.debt_id or "").strip():
        out.append("RED add：--debt-id 必填且不得为空（无债号的活不许外派：§3.1）")
        return 1
    if args.debt_id.strip().lower() in EMPTY_DEBT_TOKENS:
        out.append("RED add：--debt-id 是占位词 %r（无债号的活不许外派：§3.1）" % args.debt_id)
        return 1
    if not (args.channel or "").strip():
        out.append("RED add：--channel 必填")
        return 1
    state = args.state or "queued"
    if state not in STATES:
        out.append("RED add：--state 非法态 %r（合法：%s）" % (state, STATES))
        return 1
    if state != "queued" and not (args.base_sha or "").strip():
        out.append("RED add：--state=%s 需要 --base-sha（发布/切片态必须有基线）" % state)
        return 1
    if state in ("claimed", "submitted", "adjudicated", "merged", "rejected") \
            and not (args.claimed_by or "").strip():
        out.append("RED add：--state=%s 需要 --claimed-by（流转态必须有主）" % state)
        return 1
    if state in ("submitted", "adjudicated", "merged", "rejected") \
            and not (args.receipt_path or "").strip():
        out.append("RED add：--state=%s 需要 --receipt-path（交卷态必留收益记录）" % state)
        return 1
    if state in ("adjudicated", "merged", "rejected") and not (args.verdict or "").strip():
        out.append("RED add：--state=%s 需要 --verdict（裁决态必留结论）" % state)
        return 1

    task = {
        "debt_id": args.debt_id.strip(),
        "channel": args.channel.strip(),
        "state": state,
        "base_sha": (args.base_sha or "").strip(),
        "claimed_by": (args.claimed_by or "").strip() or None,
        "claimed_at": (args.claimed_at or "").strip() or None,
        "verdict": (args.verdict or "").strip() or None,
        "receipt_path": (args.receipt_path or "").strip() or None,
        "value": {
            "increments": int(args.increments or 0),
            "review_min": int(args.review_min or 0),
        },
    }
    try:
        with WriteLock(path):
            data, err = load_registry(path)
            if err:
                if args.init_missing and "不存在" in err:
                    data = empty_registry()
                else:
                    out.append("RED add：%s（fail-closed，不新建覆盖）" % err)
                    return 2
            tasks = data.setdefault("tasks", {})
            if tid in tasks:
                if tasks[tid] == task:
                    out.append("IDEMPOTENT add：tasks[%s] 已存在且内容一致 ⇒ 同结果，不产生第二份" % tid)
                    return 0
                out.append("RED add：tasks[%s] 已存在且内容不同 ⇒ 拒绝覆盖（改内容请走 transition）" % tid)
                out.append("  既有：%s" % json.dumps(tasks[tid], ensure_ascii=False, sort_keys=True))
                out.append("  拟写：%s" % json.dumps(task, ensure_ascii=False, sort_keys=True))
                return 1
            tasks[tid] = task
            write_atomic(path, data)
    except RuntimeError as exc:
        out.append("RED add：%s" % exc)
        return 2
    except OSError as exc:
        out.append("RED add：写盘失败 %s（fail-closed）" % exc)
        return 2
    out.append("OK add：tasks[%s] 登记（state=%s debt=%s channel=%s）"
               % (tid, state, task["debt_id"], task["channel"]))
    out.append("  注册表：%s" % path)
    return 0


# ---------------------------------------------------------------- 命令：transition

def cmd_transition(args, out):
    path = args.registry
    tid = args.task_id
    target = args.to
    if not tid:
        out.append("RED transition：--task-id 必填")
        return 1
    if target not in STATES:
        out.append("RED transition：--to 非法态 %r（合法：%s）" % (target, STATES))
        return 1
    try:
        with WriteLock(path):
            data, err = load_registry(path)
            if err:
                out.append("RED transition：%s（fail-closed）" % err)
                return 2
            tasks = data.get("tasks", {})
            if tid not in tasks:
                out.append("RED transition：tasks[%s] 不存在（不可证 ⇒ 拒派/拒转，fail-closed）" % tid)
                return 2
            t = tasks[tid]
            cur = t.get("state")
            if cur == target:
                out.append("IDEMPOTENT transition：tasks[%s] 已是 %s ⇒ 同结果，不产生第二份" % (tid, target))
                return 0
            legal = LEGAL_TRANSITIONS.get(cur, [])
            if target not in legal:
                out.append("RED transition：非法转移 %s → %s（tasks[%s] 现行态 %s）"
                           % (cur, target, tid, cur))
                out.append("  合法后继：%s" % (legal if legal else "（终态，无后继）"))
                out.append("  判据：§3.4 统一态链 queued→packaged→published→claimed→submitted"
                           "→adjudicated→merged|rejected（跳步即红）")
                return 1
            # 目标态的必要字段
            if target == "claimed" and not (args.claimed_by or t.get("claimed_by") or "").strip():
                out.append("RED transition：→ claimed 需要 --claimed-by（无主＝无人领）")
                return 1
            if target == "adjudicated" and not (args.verdict or t.get("verdict") or "").strip():
                out.append("RED transition：→ adjudicated 需要 --verdict（裁决必留结论）")
                return 1
            if target in ("submitted", "adjudicated", "merged", "rejected") \
                    and not (args.receipt_path or t.get("receipt_path") or "").strip():
                out.append("RED transition：→ %s 需要 --receipt-path（交卷态必留收益记录）" % target)
                return 1
            if target in ("packaged", "published") and not (args.base_sha or t.get("base_sha") or "").strip():
                out.append("RED transition：→ %s 需要 --base-sha（发布/切片态必须有基线）" % target)
                return 1

            t["state"] = target
            if args.claimed_by:
                t["claimed_by"] = args.claimed_by.strip()
            if target == "claimed":
                t["claimed_at"] = (args.claimed_at or now_iso()).strip()
            if args.claimed_at and target != "claimed":
                t["claimed_at"] = args.claimed_at.strip()
            if args.verdict:
                t["verdict"] = args.verdict.strip()
            if args.receipt_path:
                t["receipt_path"] = args.receipt_path.strip()
            if args.base_sha:
                t["base_sha"] = args.base_sha.strip()
            write_atomic(path, data)
    except RuntimeError as exc:
        out.append("RED transition：%s" % exc)
        return 2
    except OSError as exc:
        out.append("RED transition：写盘失败 %s（fail-closed）" % exc)
        return 2
    out.append("OK transition：tasks[%s] %s → %s" % (tid, cur, target))
    return 0


# ---------------------------------------------------------------- 命令：verify

def cmd_verify(args, out):
    data, err = load_registry(args.registry)
    if err:
        out.append("RED verify：%s（fail-closed）" % err)
        return 2
    errors, warns = verify_registry(data)
    for w in warns:
        out.append("WARN %s" % w)
    if errors:
        for e in errors:
            out.append("RED %s" % e)
        out.append("RED verify：%d 项红（结构/状态机不合法）" % len(errors))
        return 1
    out.append("GREEN verify：注册表 %s 结构与状态机全绿（tasks=%d）"
               % (args.registry, len(data.get("tasks", {}))))
    return 0


# ---------------------------------------------------------------- 命令：show

def cmd_show(args, out):
    data, err = load_registry(args.registry)
    if err:
        out.append("RED show：%s" % err)
        return 2
    out.append(json.dumps(data, ensure_ascii=False, indent=1))
    return 0


# ---------------------------------------------------------------- 命令：export

def merge_item(item, task, with_registry_fields):
    """把注册表权威字段并进人读面条目（字段名不变：debt/lane/state/base_sha…）。"""
    merged = dict(item)
    # debt：既有值若以同一债号开头 ⇒ 保留富文本（不丢信息）；否则取注册表债号
    old_debt = (item.get("debt") or "").strip()
    new_debt = (task.get("debt_id") or "").strip()
    if not old_debt or not old_debt.startswith(new_debt):
        merged["debt"] = new_debt
    if task.get("channel"):
        merged["lane"] = task.get("channel")
    verdict = (task.get("verdict") or "").strip()
    merged["state"] = verdict if verdict else UNIFIED_TO_LEGACY.get(task.get("state"),
                                                                    task.get("state"))
    if (task.get("base_sha") or "").strip():
        merged["base_sha"] = task.get("base_sha")
    if with_registry_fields:
        merged["registry_state"] = task.get("state")
        merged["claimed_by"] = task.get("claimed_by")
        merged["claimed_at"] = task.get("claimed_at")
        merged["verdict"] = task.get("verdict")
        merged["receipt_path"] = task.get("receipt_path")
        merged["value"] = task.get("value")
    return merged


def cmd_export(args, out):
    data, err = load_registry(args.registry)
    if err:
        out.append("RED export：%s（fail-closed，不产出投影）" % err)
        return 2
    errors, warns = verify_registry(data)
    if errors:
        for e in errors:
            out.append("RED export（注册表自身红，不导出）：%s" % e)
        return 1
    for w in warns:
        out.append("WARN export：%s" % w)

    out_path = args.out or LEDGER_JSON
    proj = None
    if os.path.exists(out_path):
        try:
            with open(out_path, "r", encoding="utf-8") as f:
                proj = json.load(f)
        except Exception as exc:                  # noqa: BLE001
            out.append("RED export：人读面不可解析 %s（%s）⇒ fail-closed，不覆盖" % (out_path, exc))
            return 2
    if proj is None:
        proj = {
            "schema": "af.bot.dispatch-registry.v1",
            "updated_at": now_iso(),
            "purpose": "外派任务登记（人读投影；权威面 = af-state/dispatch/registry.json）",
            "items": [],
        }
    if not isinstance(proj.get("items"), list):
        out.append("RED export：人读面 items 不是列表 ⇒ fail-closed，不覆盖")
        return 2

    tasks = data.get("tasks", {})
    by_id = {}
    for it in proj["items"]:
        if isinstance(it, dict) and it.get("task_id"):
            by_id[it["task_id"]] = it

    new_items = []
    used = set()
    for it in proj["items"]:
        tid = it.get("task_id") if isinstance(it, dict) else None
        if tid and tid in tasks:
            new_items.append(merge_item(it, tasks[tid], args.with_registry_fields))
            used.add(tid)
        else:
            new_items.append(it)
    added = []
    for tid in sorted(tasks):
        if tid in used:
            continue
        t = tasks[tid]
        item = {
            "task_id": tid,
            "debt": t.get("debt_id"),
            "lane": t.get("channel"),
            "state": (t.get("verdict") or UNIFIED_TO_LEGACY.get(t.get("state"), t.get("state"))),
        }
        if (t.get("base_sha") or "").strip():
            item["base_sha"] = t.get("base_sha")
        if args.with_registry_fields:
            item["registry_state"] = t.get("state")
            item["claimed_by"] = t.get("claimed_by")
            item["claimed_at"] = t.get("claimed_at")
            item["verdict"] = t.get("verdict")
            item["receipt_path"] = t.get("receipt_path")
            item["value"] = t.get("value")
        new_items.append(item)
        added.append(tid)

    orphans = [it.get("task_id") for it in proj["items"]
               if isinstance(it, dict) and it.get("task_id") and it.get("task_id") not in tasks]
    if added and not os.path.exists(out_path):
        out.append("WARN export：导出到**新文件** ⇒ 注册表 v1 不含描述性字段"
                   "（title/objective/bundle_sha256/file_count/…），新投影条目比旧投影字段少；"
                   "正式使用请导出到既有投影路径（%s）" % LEDGER_JSON)
    proj["items"] = new_items

    before = None
    body = json.dumps(proj, ensure_ascii=False, indent=1)
    prev_body = None
    if os.path.exists(out_path):
        with open(out_path, "r", encoding="utf-8") as f:
            prev_body = f.read()
    if prev_body is not None and prev_body.rstrip("\n") == body:
        out.append("IDEMPOTENT export：%s 内容与注册表一致 ⇒ 不重写（字节不变）" % out_path)
        out.append("  条目 %d 条；注册表新增 %d 条；孤儿条目（登记面有、注册表无）%d 条"
                   % (len(new_items), len(added), len(orphans)))
        return 0
    if orphans:
        out.append("WARN export：孤儿条目 %d 条（登记面有、注册表无）已原样保留（导出面不丢历史条目）"
                   % len(orphans))
        for o in orphans:
            out.append("  孤儿：%s" % o)
    proj["updated_at"] = now_iso()
    try:
        write_atomic(out_path, proj, indent=1, trailing_newline=False)
    except OSError as exc:
        out.append("RED export：写盘失败 %s（fail-closed）" % exc)
        return 2
    out.append("OK export：%s 已由注册表重新生成（条目 %d 条；注册表新增 %d 条）"
               % (out_path, len(new_items), len(added)))
    for tid in added:
        out.append("  新增条目：%s" % tid)
    return 0


# ---------------------------------------------------------------- 命令：import-ledger

def extract_debt_id(text):
    """从人读面 debt 字段抽债号（'P3-A1（同题双解·只读复核）' → 'P3-A1'）。"""
    s = (text or "").strip()
    m = re.match(r"^\s*([A-Za-z]{1,5}\d+(?:-[A-Za-z]{0,5}\d+)?)", s)
    if m:
        return m.group(1).upper()
    m = re.match(r"^\s*([A-Za-z]{1,5}-\d+)", s)
    if m:
        return m.group(1).upper()
    return s.upper()


def cmd_import(args, out):
    """bootstrap：把人读面导入注册表（seed 用）。默认不覆盖既有注册表。"""
    src = args.from_json or LEDGER_JSON
    try:
        with open(src, "r", encoding="utf-8") as f:
            proj = json.load(f)
    except Exception as exc:                      # noqa: BLE001
        out.append("RED import：人读面不可解析 %s（%s）" % (src, exc))
        return 2
    items = proj.get("items")
    if not isinstance(items, list):
        out.append("RED import：人读面无 items 列表")
        return 2
    try:
        with WriteLock(args.registry):
            data, err = load_registry(args.registry)
            if err and "不存在" in err:
                data = empty_registry()
            elif err:
                out.append("RED import：%s" % err)
                return 2
            else:
                if data.get("tasks") and not args.force:
                    out.append("RED import：注册表已有 %d 条任务（默认不覆盖；--force 才覆盖）"
                               % len(data["tasks"]))
                    return 1
                if args.force:
                    data = empty_registry()
            for it in items:
                tid = (it.get("task_id") or "").strip()
                if not tid:
                    continue
                legacy = (it.get("state") or "").strip()
                unified = LEGACY_TO_UNIFIED.get(legacy, "queued")
                verdict = legacy if legacy in NON_FLOW_LEGACY else None
                receipt = None
                cand = os.path.join(ROOT, "30-工件", "外派-bot-试点", "receipts", "%s.json" % tid)
                if os.path.exists(cand):
                    receipt = os.path.relpath(cand, ROOT)
                claimed_by = "bot" if unified in ("claimed", "submitted", "adjudicated",
                                                  "merged", "rejected") else None
                data["tasks"][tid] = {
                    "debt_id": extract_debt_id(it.get("debt")),
                    "channel": (it.get("lane") or "bot").strip(),
                    "state": unified,
                    "base_sha": (it.get("base_sha") or "").strip(),
                    "claimed_by": claimed_by,
                    "claimed_at": None,
                    "verdict": verdict,
                    "receipt_path": receipt,
                    "value": {"increments": 0, "review_min": 0},
                }
            write_atomic(args.registry, data)
    except RuntimeError as exc:
        out.append("RED import：%s" % exc)
        return 2
    except OSError as exc:
        out.append("RED import：写盘失败 %s（fail-closed）" % exc)
        return 2
    out.append("OK import：%d 条任务导入注册表 %s" % (len(data["tasks"]), args.registry))
    for tid in sorted(data["tasks"]):
        t = data["tasks"][tid]
        out.append("  %-34s debt=%-8s state=%-12s verdict=%s"
                   % (tid, t["debt_id"], t["state"], t["verdict"] or "-"))
    return 0


# ---------------------------------------------------------------- selftest

def _w(d, name, text):
    p = os.path.join(d, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return p


def run_selftest(out):
    import tempfile as _tf
    d = _tf.mkdtemp(prefix="dispatch-registry-selftest-")
    fails = []
    n = 0
    try:
        reg = os.path.join(d, "registry.json")
        # T1 add：新任务登记 + verify 绿
        n += 1
        rc = cmd_add(_Args(registry=reg, task_id="rt-e900-selftest", debt_id="RT-E900",
                           channel="bot", state="queued", base_sha="", claimed_by=None,
                           claimed_at=None, verdict=None, receipt_path=None,
                           increments=0, review_min=0, init_missing=True), out)
        if rc != 0:
            fails.append("T1 add 应绿 rc=0，得 %d" % rc)
        data, err = load_registry(reg)
        if err or "rt-e900-selftest" not in data.get("tasks", {}):
            fails.append("T1 add 后注册表应有该任务（err=%s）" % err)

        # T2 非法转移必红：queued → adjudicated（跳三步；字段齐备 ⇒ 红因只能是「非法转移」）
        n += 1
        buf = []
        rc = cmd_transition(_Args(registry=reg, task_id="rt-e900-selftest", to="adjudicated",
                                  claimed_by="bot-lane-rt-e900-selftest", claimed_at=None,
                                  verdict="merged-ok",
                                  receipt_path="receipts/rt-e900-selftest.json",
                                  base_sha=None), buf)
        if rc != 1:
            fails.append("T2 非法转移 queued→adjudicated 必红 rc=1，得 %d" % rc)
        if not any("非法转移" in ln for ln in buf):
            fails.append("T2 红因必须是「非法转移」（不得被字段闸掩盖）：%s" % buf)
        data, _ = load_registry(reg)
        if data["tasks"]["rt-e900-selftest"]["state"] != "queued":
            fails.append("T2 非法转移后状态必须不变（仍 queued）")

        # T2b 非法转移必红：queued → published（跳一步；基线齐备）
        n += 1
        buf = []
        rc = cmd_transition(_Args(registry=reg, task_id="rt-e900-selftest", to="published",
                                  claimed_by=None, claimed_at=None, verdict=None,
                                  receipt_path=None, base_sha="deadbeef"), buf)
        if rc != 1:
            fails.append("T2b 非法转移 queued→published 必红 rc=1，得 %d" % rc)
        if not any("非法转移" in ln for ln in buf):
            fails.append("T2b 红因必须是「非法转移」：%s" % buf)

        # T3 非法转移必红：published → merged（跨两段）
        n += 1
        cmd_add(_Args(registry=reg, task_id="rt-e901-selftest", debt_id="RT-E901",
                      channel="bot", state="queued", base_sha="", claimed_by=None,
                      claimed_at=None, verdict=None, receipt_path=None,
                      increments=0, review_min=0, init_missing=True), out)
        cmd_transition(_Args(registry=reg, task_id="rt-e901-selftest", to="packaged",
                             claimed_by=None, claimed_at=None, verdict=None,
                             receipt_path=None, base_sha="abc123"), out)
        cmd_transition(_Args(registry=reg, task_id="rt-e901-selftest", to="published",
                             claimed_by=None, claimed_at=None, verdict=None,
                             receipt_path=None, base_sha=None), out)
        rc = cmd_transition(_Args(registry=reg, task_id="rt-e901-selftest", to="merged",
                                  claimed_by=None, claimed_at=None, verdict=None,
                                  receipt_path=None, base_sha=None), out)
        if rc != 1:
            fails.append("T3 非法转移 published→merged 必红 rc=1，得 %d" % rc)
        if not any("非法转移" in ln for ln in out):
            fails.append("T3 红因必须是「非法转移」")

        # T4 全链合法转移 + 幂等（同态重放）
        n += 1
        seq = [("claimed", dict(claimed_by="bot-lane-rt-e901-selftest")),
               ("submitted", dict(receipt_path="receipts/rt-e901-selftest.json")),
               ("adjudicated", dict(verdict="merged-ok")),
               ("merged", {})]
        for to, kw in seq:
            a = _Args(registry=reg, task_id="rt-e901-selftest", to=to, claimed_by=None,
                      claimed_at=None, verdict=None, receipt_path=None, base_sha=None)
            for k, v in kw.items():
                setattr(a, k, v)
            rc = cmd_transition(a, out)
            if rc != 0:
                fails.append("T4 合法转移 → %s 应绿 rc=0，得 %d" % (to, rc))
        a = _Args(registry=reg, task_id="rt-e901-selftest", to="merged", claimed_by=None,
                  claimed_at=None, verdict=None, receipt_path=None, base_sha=None)
        rc = cmd_transition(a, out)
        if rc != 0:
            fails.append("T4 同态重放应幂等 rc=0，得 %d" % rc)
        data, _ = load_registry(reg)
        if len(data["tasks"]) != 2:
            fails.append("T4 幂等重放不得产生第二份（tasks=%d）" % len(data["tasks"]))

        # T5 add 幂等：同内容重放绿；不同内容红
        n += 1
        a1 = _Args(registry=reg, task_id="rt-e900-selftest", debt_id="RT-E900",
                   channel="bot", state="queued", base_sha="", claimed_by=None,
                   claimed_at=None, verdict=None, receipt_path=None,
                   increments=0, review_min=0, init_missing=True)
        rc = cmd_add(a1, out)
        if rc != 0:
            fails.append("T5 同内容重放 add 应幂等 rc=0，得 %d" % rc)
        a2 = _Args(registry=reg, task_id="rt-e900-selftest", debt_id="RT-E900",
                   channel="bot", state="queued", base_sha="", claimed_by=None,
                   claimed_at=None, verdict=None, receipt_path=None,
                   increments=0, review_min=0, init_missing=True)
        rc = cmd_add(a2, out)
        if rc != 0:
            fails.append("T5 同内容重放 add 应幂等 rc=0，得 %d" % rc)
        a3 = _Args(registry=reg, task_id="rt-e900-selftest", debt_id="RT-E900-X",
                   channel="bot", state="queued", base_sha="", claimed_by=None,
                   claimed_at=None, verdict=None, receipt_path=None,
                   increments=0, review_min=0, init_missing=True)
        rc = cmd_add(a3, out)
        if rc != 1:
            fails.append("T5 异内容重放 add 必红 rc=1，得 %d" % rc)

        # T6 verify：结构红（缺字段 / 非法态 / 类型错）
        n += 1
        bad = {"schema_version": 1,
               "tasks": {"rt-e900-selftest": {"debt_id": "RT-E900", "channel": "bot",
                                              "state": "not-a-state", "base_sha": "",
                                              "claimed_by": None, "claimed_at": None,
                                              "verdict": None, "receipt_path": None,
                                              "value": {"increments": 0, "review_min": 0}}},
               "meta": {"calibration": {}}}
        errs, _ = verify_registry(bad)
        if not any("state 非法态" in e for e in errs):
            fails.append("T6 verify 应点名非法态")
        bad2 = {"schema_version": 1, "tasks": {"x-y": {"debt_id": "RT-E900"}}, "meta": {}}
        errs2, _ = verify_registry(bad2)
        if not errs2:
            fails.append("T6 verify 残缺任务体应红")

        # T7 verify：状态机一致性红（state=claimed 但 claimed_by 空）
        n += 1
        bad3 = {"schema_version": 1,
                "tasks": {"rt-e902-selftest": {"debt_id": "RT-E902", "channel": "bot",
                                               "state": "claimed", "base_sha": "x",
                                               "claimed_by": None, "claimed_at": None,
                                               "verdict": None, "receipt_path": None,
                                               "value": {"increments": 0, "review_min": 0}}},
                "meta": {"calibration": {}}}
        errs3, _ = verify_registry(bad3)
        if not any("claimed_by 空" in e for e in errs3):
            fails.append("T7 verify 应点名 claimed_by 空")

        # T8 export：人读面三笔兼容（字段名不变、不丢字段）+ 二次导出字节不变
        n += 1
        proj = {
            "schema": "af.bot.dispatch-registry.v1",
            "updated_at": "2026-11-05T19:20:00+0800",
            "purpose": "测试用",
            "items": [
                {"task_id": "t-1", "debt": "RT-E82", "title": "笔一", "lane": "bot",
                 "state": "published-awaiting-bot", "base_sha": "aaa", "objective": "x",
                 "bundle_sha256": "b1", "file_count": 3},
                {"task_id": "t-2", "debt": "P3-A1（同题双解·只读复核）", "title": "笔二",
                 "lane": "bot", "state": "audited-green-content", "base_sha": "bbb",
                 "objective": "y", "bundle_sha256": "b2", "file_count": 4},
                {"task_id": "t-3", "debt": "RT-E83", "title": "笔三", "lane": "bot",
                 "state": "published-awaiting-bot", "base_sha": "ccc", "objective": "z",
                 "bundle_sha256": "b3", "file_count": 5},
            ],
        }
        outp = os.path.join(d, "外派登记.json")
        with open(outp, "w", encoding="utf-8") as f:
            json.dump(proj, f, ensure_ascii=False, indent=1)
        # 注册表：t-1 published；t-2 adjudicated+verdict；t-3 published
        reg2 = os.path.join(d, "registry2.json")
        write_atomic(reg2, {
            "schema_version": 1,
            "tasks": {
                "t-1": {"debt_id": "RT-E82", "channel": "bot", "state": "published",
                        "base_sha": "aaa", "claimed_by": None, "claimed_at": None,
                        "verdict": None, "receipt_path": None,
                        "value": {"increments": 0, "review_min": 0}},
                "t-2": {"debt_id": "P3-A1", "channel": "bot", "state": "adjudicated",
                        "base_sha": "bbb", "claimed_by": "bot", "claimed_at": None,
                        "verdict": "audited-green-content",
                        "receipt_path": "receipts/t-2.json",
                        "value": {"increments": 3, "review_min": 20}},
                "t-3": {"debt_id": "RT-E83", "channel": "bot", "state": "published",
                        "base_sha": "ccc", "claimed_by": None, "claimed_at": None,
                        "verdict": None, "receipt_path": None,
                        "value": {"increments": 0, "review_min": 0}},
            },
            "meta": {"calibration": {}},
        })
        rc = cmd_export(_Args(registry=reg2, out=outp, with_registry_fields=False), out)
        if rc != 0:
            fails.append("T8 export 应绿 rc=0，得 %d" % rc)
        with open(outp, "r", encoding="utf-8") as f:
            got = json.load(f)
        if len(got.get("items", [])) != 3:
            fails.append("T8 export 后条目数必须仍为 3，得 %d" % len(got.get("items", [])))
        for old, new in zip(proj["items"], got.get("items", [])):
            for k, v in old.items():
                if k == "state":
                    continue
                if new.get(k) != v:
                    fails.append("T8 export 丢了字段 %s：%r → %r" % (k, v, new.get(k)))
        if got["items"][0].get("state") != "published-awaiting-bot":
            fails.append("T8 export 改了 published 笔的 state：%r" % got["items"][0].get("state"))
        if got["items"][1].get("state") != "audited-green-content":
            fails.append("T8 export 把审计结论态改成 %r" % got["items"][1].get("state"))
        if got["items"][1].get("debt") != "P3-A1（同题双解·只读复核）":
            fails.append("T8 export 覆盖了富文本 debt：%r" % got["items"][1].get("debt"))
        with open(outp, "r", encoding="utf-8") as f:
            body1 = f.read()
        rc = cmd_export(_Args(registry=reg2, out=outp, with_registry_fields=False), out)
        if rc != 0:
            fails.append("T8 二次 export 应绿 rc=0，得 %d" % rc)
        with open(outp, "r", encoding="utf-8") as f:
            body2 = f.read()
        if body1 != body2:
            fails.append("T8 二次 export 必须字节不变（幂等）")

        # T9 export：注册表缺件 ⇒ fail-closed rc=2，不产出
        n += 1
        rc = cmd_export(_Args(registry=os.path.join(d, "nope.json"), out=outp,
                              with_registry_fields=False), out)
        if rc != 2:
            fails.append("T9 export 注册表缺件应 rc=2（fail-closed），得 %d" % rc)

        # T10 状态机全链定义自检（每个态都有条目，终态无后继）
        n += 1
        if set(LEGAL_TRANSITIONS.keys()) != set(STATES):
            fails.append("T10 LEGAL_TRANSITIONS 与 STATES 不同集")
        for st, nxt in LEGAL_TRANSITIONS.items():
            for x in nxt:
                if x not in LEGAL_TRANSITIONS:
                    fails.append("T10 非法后继态 %s（来自 %s）" % (x, st))

        if fails:
            out.append("FAIL selftest %d/%d 过：" % (n - len(fails), n))
            for f in fails:
                out.append("  " + f)
            return 1
        out.append("selftest %d/%d 过（add/幂等/非法转移必红×3+红因必为「非法转移」/合法全链/同态幂等/"
                   "verify 结构红×3/verify 状态机一致性红/export 三笔兼容+字段不丢+富文本 debt 保留/"
                   "二次导出字节不变/export 缺件 fail-closed/状态机表自检）" % (n, n))
        return 0
    finally:
        shutil.rmtree(d, ignore_errors=True)


class _Args(object):
    """极简命名空间（selftest 用；避免依赖 argparse）。"""

    def __init__(self, **kw):
        self.__dict__.update(kw)

    def __getattr__(self, name):
        return None


# ---------------------------------------------------------------- CLI

def build_parser():
    import argparse
    p = argparse.ArgumentParser(
        prog="dispatch-registry.py",
        description="外派注册表 v1（权威面 af-state/dispatch/registry.json）："
                    "add/transition/verify/export/import-ledger/show + --selftest")
    p.add_argument("--selftest", action="store_true", help="内嵌夹具自测（零真文件读取）")
    sub = p.add_subparsers(dest="cmd")

    def common(sp):
        sp.add_argument("--registry", default=REGISTRY_PATH, help="注册表路径")

    sp = sub.add_parser("add", help="登记一笔新外派")
    common(sp)
    sp.add_argument("--task-id", required=True)
    sp.add_argument("--debt-id", required=True)
    sp.add_argument("--channel", required=True)
    sp.add_argument("--state", default="queued")
    sp.add_argument("--base-sha", default="")
    sp.add_argument("--claimed-by", default=None)
    sp.add_argument("--claimed-at", default=None)
    sp.add_argument("--verdict", default=None)
    sp.add_argument("--receipt-path", default=None)
    sp.add_argument("--increments", type=int, default=0)
    sp.add_argument("--review-min", type=int, default=0)
    sp.add_argument("--init-missing", action="store_true",
                    help="注册表不存在时新建空表（默认缺件即拒）")

    sp = sub.add_parser("transition", help="状态机推进（非法转移必红）")
    common(sp)
    sp.add_argument("--task-id", required=True)
    sp.add_argument("--to", required=True)
    sp.add_argument("--claimed-by", default=None)
    sp.add_argument("--claimed-at", default=None)
    sp.add_argument("--verdict", default=None)
    sp.add_argument("--receipt-path", default=None)
    sp.add_argument("--base-sha", default=None)

    sp = sub.add_parser("verify", help="结构 + 状态机合法性体检")
    common(sp)

    sp = sub.add_parser("export", help="重新生成人读面 外派登记.json（字段名不变）")
    common(sp)
    sp.add_argument("--out", default=None)
    sp.add_argument("--with-registry-fields", action="store_true",
                    help="额外写入 registry_state/claimed_by/… 字段（默认不改变条目形状）")

    sp = sub.add_parser("import-ledger", help="bootstrap：人读面 → 注册表")
    common(sp)
    sp.add_argument("--from-json", default=None)
    sp.add_argument("--force", action="store_true")

    sp = sub.add_parser("show", help="打印注册表")
    common(sp)
    return p


def main(argv):
    out = []
    if not argv:
        out.append(__doc__.strip())
        out.append("")
        out.append("用法：python3 tools/dispatch-registry.py <add|transition|verify|export|"
                   "import-ledger|show> …；或 --selftest")
        for ln in out:
            print(ln)
        return 0
    if "--selftest" in argv:
        rc = run_selftest(out)
        for ln in out:
            print(ln)
        return rc
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.cmd is None:
        parser.print_help()
        return 0
    if args.cmd == "add":
        rc = cmd_add(args, out)
    elif args.cmd == "transition":
        rc = cmd_transition(args, out)
    elif args.cmd == "verify":
        rc = cmd_verify(args, out)
    elif args.cmd == "export":
        rc = cmd_export(args, out)
    elif args.cmd == "import-ledger":
        rc = cmd_import(args, out)
    elif args.cmd == "show":
        rc = cmd_show(args, out)
    else:
        rc = 2
    for ln in out:
        print(ln)
    return rc


def _print(out):
    for ln in out:
        print(ln)
    return False


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
