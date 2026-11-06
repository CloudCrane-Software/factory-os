#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""stream-tailer — OTel 视图设计批 S3：run 流尾随器（可跑原型）

对 af-state/orders/ 下全部订单的 harness run 做"流式状态抽取"，为看板 S4 页面
生产 <run键>.json 快照。三种 run 目录布局统一处理：
  swev   扁平：runs/<item>-a<n>/harness.db
  report 环： runs/<item>-a<n>/ring/<成员>/harness.db
  graph  图： runs/<item>-a<n>/nodes/<节点>/harness.db
发现方式 = 递归找所有直接含 harness.db 的叶子目录（顶层 run 目录没有 normal.jsonl
的 graph/report 布局也能覆盖）。

设计要点：
  增量读   normal.jsonl 按字节偏移只读新增部分（状态文件 .tailer-state.json），
           尾部无换行的残行留在下轮；文件静置>QUIESCE_MS 视为写完，残行收编；
           inode/设备号变化即整体重置（tail -F 语义，防 log rotate 混账）。
  WAL安全  harness.db 一律 sqlite URI 只读连接；静置库（无 -wal/-wal 空）加
           immutable=1 零副作用（不创建 -shm/-wal），活跃 WAL 库退避重试；
           结构性损坏不重试，错误隔离到单 run。
  原子覆写 同目录带 pid 的临时文件 + fsync + os.replace；并发双跑不互抢；
           状态文件 ensure_ascii 落盘且写失败只降级警告。
  脱敏     preview/payload_head 剔除不可编码字符；tool 轮输出按 publish-gate §1.4
           裁决屏蔽（不入 preview）。
  降级路径 voucher/ledger/mes-events/records/results 缺失或空均为合法状态，
           对应 identity 键置 null；单 run 解析失败只记 error，不影响其余 run。
           run_key 冲突（目录名 '__' 歧义）显式报 error 跳过不合并。

用法：
  python3 tools/stream-tailer.py --once                     # 全量扫一遍并覆写全部 stream json
  python3 tools/stream-tailer.py --daemon --interval 10     # 守护轮询（默认 10s）
  python3 tools/stream-tailer.py --once --orders 'F4B*'     # 订单目录名 glob 过滤
  python3 tools/stream-tailer.py --once --limit-turns 20 --limit-events 50

退出码：全部 run 成功=0；任一 run error=1；用法错误=2。
仅用 python3 标准库。
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import sqlite3
import sys
import time
import urllib.parse
from pathlib import Path

WS_ROOT = Path(__file__).resolve().parent.parent
ORDERS_DIR = WS_ROOT / "af-state" / "orders"
DEFAULT_OUT_ROOT = WS_ROOT / "状态" / "看板" / "stream"
STATE_FILENAME = ".tailer-state.json"

STATE_VERSION = 1
QUIESCE_MS = 30_000          # normal.jsonl 静置超过该时长，尾部残行按完行收编
SQLITE_RETRIES = 3           # WAL/锁冲突重试次数
SQLITE_BACKOFF_S = 0.2
MODEL_EVENTS_CAP = 400       # 每个_run_缓存的 harness.model 事件条数上限（按 turn 裁剪）

PLAN_ID_RE = re.compile(r"^plan\.(?P<name>[A-Za-z0-9_]+)@(?P<ver>\d+\.\d+)\+(?P<digest>[0-9a-f]+)$")
ARM_RE = re.compile(r"-a(?P<arm>\d+)$")

USAGE_KEYS = ("input_tokens", "output_tokens", "cache_read_tokens")

# --------------------------------------------------------------------------- #
# 生成侧脱敏（publish-gate.md §1.1/§1.2 模式族的移植实现，2026-10-28 主代理补齐）
#
# 发布链闭环要求：gate（tools/publish-gate.py，未落盘）之外，生成侧对进产物的自由
# 文本做正则命中段替换 ▉▉▉。真源=计划/研究组/密钥终扫-20261024.md §0 十三模式 + 观测
# 面 O 族（tailnet/公网 IP/home 路径/回环端口）。值侧负向：`<none>`/`null`/`""` 不算值
# （K-08 误报勘误）；表格移植的 `\|` 转义已去除。
# 作用面：preview / payload_head / kind / model / finish（结构化身份字段不含自由文本）。
# --------------------------------------------------------------------------- #
SCRUB_RULES: list[tuple[str, re.Pattern[str]]] = [
    # —— K 族：密钥形状 ——
    ("K-01 JWT", re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{8,}")),
    ("K-02 sk-前缀", re.compile(r"\bsk-[A-Za-z0-9_-]{8,}")),
    ("K-03 GitHub PAT", re.compile(r"\b(ghp|gho|ghu|ghs)_[A-Za-z0-9]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}")),
    ("K-04 AWS AK", re.compile(r"\bAKIA[0-9A-Z]{14,22}\b")),
    # K-05：整段 PEM（头到 END）；无 END（截断件）时至少遮头行（红队R4-P1-5）
    ("K-05 PEM 私钥", re.compile(
        r"-----BEGIN [A-Za-z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Za-z ]*PRIVATE KEY-----"
        r"|-----BEGIN [A-Za-z ]*PRIVATE KEY-----", re.IGNORECASE)),
    # K-06/07/08/11 赋值对（红队R4-P1-1/3/4 重写）：
    #   - 键两侧容忍引号（JSON 形态="payload_head 主战场"）
    #   - 键前容忍 [A-Za-z0-9_-]* 前缀（OPENAI_API_KEY / access_token 等后缀族）
    #   - 值容忍一个前导引号；值侧负向：null/<none>/纯数字（"tokens": 1234567 计数不误报）
    ("K-06/07/08/11 赋值对", re.compile(
        r"['\"]?[A-Za-z0-9_-]*(?:api[-_]?key|access[-_]?token|token|password|passwd|secret|credential)s?['\"]?\s*[:=]\s*['\"]?"
        r"(?P<v>(?!null\b|<none>)(?![\d.]+(?:[,}\]\s]|$))[^\s\"',;}]{6,})",
        re.IGNORECASE)),
    ("K-09 Bearer", re.compile(r"\b[Bb]earer\s+[A-Za-z0-9._~+/-]{8,}")),
    ("K-10 SSH 公钥", re.compile(r"\b(?:ssh-(?:rsa|ed25519)|ecdsa-sha2-[a-z0-9-]+)\s+AAAA[A-Za-z0-9+/]{20,}")),
    ("K-12 openBao hvs.", re.compile(r"\bhvs\.[A-Za-z0-9_-]{10,}")),
    # K-13：全部交替项带值长度（红队R4-P1-2：原 xoxb-/glpat- 只遮前缀漏值）
    ("K-13 其余厂商前缀", re.compile(
        r"\bxox[baprs]-[A-Za-z0-9-]{10,}|\bglpat-[A-Za-z0-9_-]{15,}|\bhf_[A-Za-z0-9]{20,}"
        r"|\bAIza[0-9A-Za-z_-]{30,}|\bxai-[A-Za-z0-9]{20,}")),
    # —— O 族：观测面内部拓扑 ——
    # O-01：CGNAT 100.64-100.127，八位组容忍前导零（红队R4：100.064 形态）
    ("O-01 tailnet CGNAT", re.compile(
        r"\b100\.0*(?:6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\.(\d{1,3})\.(\d{1,3})\b")),
    ("O-02 公网入口 IP", re.compile(r"\b(159\.75\.21\.149|42\.194\.143\.17)\b")),
    # O-03：容忍双斜杠与非 ASCII 用户名（红队R4-P2）
    ("O-03 home 路径", re.compile(r"/home/+[^\s\"',;}/]{1,40}")),
    # O-05：补 localhost:port 形态（红队R4-P2）
    ("O-05 回环端口", re.compile(r"\b(?:127\.0\.0\.1|localhost):(\d{2,5})\b")),
    ("O-06 内网用户@主机", re.compile(r"\b[A-Za-z0-9._-]+@(gov|pandev[0-9-]*|anolis|mingda[a-z-]*)(?:\.[a-z]+)?\b", re.IGNORECASE)),
]
_REDACT = "▉▉▉"


def scrub(text) -> tuple[str, set[str]]:
    """对自由文本做 K/O 模式族命中段替换。

    返回 (清洗后文本, 命中规则集)。命中段整体替换为 ▉▉▉；值侧负向排除
    null/<none>/纯数字（防观测计数误报）。截断（[:120]/[:200]）在 scrub 之后做，
    跨边界密钥不会漏半截（红队R4 实证）。
    """
    s = _sanitize_text(text)
    hits: set[str] = set()
    for name, pat in SCRUB_RULES:
        def _sub(m, _n=name):
            hits.add(_n)
            return _REDACT
        s = pat.sub(_sub, s)
    return s, hits


SCRUB_STATS: dict[str, int] = {}  # 规则名 -> 清洗动作累计次数（含输出层重洗，报告用）


# --------------------------------------------------------------------------- #
# 发现：订单 -> run 叶子
# --------------------------------------------------------------------------- #
class Leaf:
    """一个含 harness.db 的叶子 run 目录。"""

    def __init__(self, order_dir: Path, run_dir: Path, leaf_dir: Path):
        self.order_dir = order_dir          # 订单目录（F2-swev-...）
        self.order_name = order_dir.name
        self.run_dir = run_dir              # 顶层 run 目录（runs/<item>-a<n>）
        self.run_dirname = run_dir.name
        self.leaf_dir = leaf_dir            # 直接含 harness.db 的目录
        rel = leaf_dir.relative_to(run_dir)
        parts = rel.parts                   # () | ('ring','reader') | ('nodes','planner')
        if "nodes" in parts:
            self.layout = "graph"
            self.node = leaf_dir.name
        elif "ring" in parts:
            self.layout = "report"
            self.node = leaf_dir.name
        else:
            self.layout = "swev"
            self.node = None
        sub = ".".join(parts) if parts else ""
        self.run_key = f"{self.order_name}__{self.run_dirname}" + (f"__{sub}" if sub else "")
        self.normal_jsonl = leaf_dir / "normal.jsonl"
        self.harness_db = leaf_dir / "harness.db"


def discover_leaves(orders_glob: str, orders_dir: Path | None = None) -> list[Leaf]:
    leaves: list[Leaf] = []
    root = orders_dir if orders_dir is not None else ORDERS_DIR
    if not root.is_dir():
        return leaves
    for order_dir in sorted(root.iterdir()):
        if not order_dir.is_dir() or not fnmatch.fnmatch(order_dir.name, orders_glob):
            continue
        runs_dir = order_dir / "runs"
        if not runs_dir.is_dir():
            continue
        for run_dir in sorted(p for p in runs_dir.iterdir() if p.is_dir()):
            for dirpath, dirnames, filenames in os.walk(run_dir):
                if "harness.db" in filenames:
                    leaves.append(Leaf(order_dir, run_dir, Path(dirpath)))
                for d in dirnames:
                    if d == "harness.db":
                        print(f"[stream-tailer] 警告: {Path(dirpath)/d} 是目录而非数据库，"
                              f"该 run 将从发现面消失", file=sys.stderr)
    return leaves


# --------------------------------------------------------------------------- #
# 订单级上下文（voucher/ledger/mes/records/results -> identity 取值）
# --------------------------------------------------------------------------- #
def _load_jsonl(path: Path) -> list[dict]:
    out = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if isinstance(obj, dict):
                    out.append(obj)
    except OSError:
        pass
    return out


def _load_json(path: Path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


class OrderContext:
    """一个订单的台账/MES 概况，一次扫描中缓存复用。"""

    def __init__(self, order_dir: Path):
        self.order_dir = order_dir
        voucher = _load_json(order_dir / "voucher.json") or {}
        self.work_order_id_voucher = voucher.get("stable_id")

        self.line_id = None
        for ev in _load_jsonl(order_dir / "ledger.jsonl"):
            if ev.get("op") == "bind_line":
                line = (ev.get("order_after") or {}).get("line") or {}
                if line.get("line_id"):
                    self.line_id = line["line_id"]
                    break

        self.work_order_id = self.work_order_id_voucher
        self.line_id_fallback = None
        mes = _load_jsonl(order_dir / "mes-events.jsonl")
        if mes:
            if not self.work_order_id:
                self.work_order_id = mes[0].get("work_order_id")
            self.line_id_fallback = mes[0].get("line_id")
        if not self.line_id:
            self.line_id = self.line_id_fallback

        self.records = _load_jsonl(order_dir / "records.jsonl")
        self.results = _load_jsonl(order_dir / "results.jsonl")

        # strategy_id / dsl_digest：records.plan_id 形如 plan.<名>@<版本>+<hex摘要>
        self.strategy_id = None
        self.dsl_digest = None
        for rec in self.records:
            plan_id = rec.get("plan_id")
            if isinstance(plan_id, str):
                m = PLAN_ID_RE.match(plan_id)
                if m:
                    self.strategy_id = plan_id
                    self.dsl_digest = m.group("digest")
                    break

    def profile_for(self, run_dirname: str):
        """profile 解析链：results(按 run_dir 匹配) -> records(按 run_dir) -> 单行聚合 -> 目录名尾段。"""
        for res in self.results:
            if os.path.basename(str(res.get("run_dir") or "")) == run_dirname and res.get("profile"):
                return res["profile"]
        for rec in self.records:
            rd = ((rec.get("evidence") or {}).get("run_dir")) or ""
            if os.path.basename(str(rd)) == run_dirname and rec.get("profile"):
                return rec["profile"]
        profiles = [r["profile"] for r in self.results + self.records if r.get("profile")]
        if len(profiles) == 1:
            return profiles[0]
        # 兜底：订单目录名约定 <F单>-<套件>-<任务>-<profile>，取最后两个 '-' 段
        segs = self.order_dir.name.split("-")
        if len(segs) >= 2:
            return "-".join(segs[-2:])
        return None


# --------------------------------------------------------------------------- #
# harness.db 只读读取（WAL 安全）
# --------------------------------------------------------------------------- #
def _sanitize_text(s) -> str:
    """清洗进 JSON 产物的自由文本：剔除孤立代理对等不可编码字符（防 UnicodeEncodeError
    crash-loop，红队 R1-P0）与控制字符。"""
    if not isinstance(s, str):
        s = str(s)
    return s.encode("utf-8", "replace").decode("utf-8")


def read_run_row(db_path: Path) -> dict | None:
    # 静置库（无 -wal 或 -wal 为空）加 immutable=1：sqlite 不再创建/触碰 -shm/-wal，
    # 真正零副作用只读（红队 R1-P1：mode=ro 仍会新建 -shm/-wal 惰性附件）。
    # 活跃 WAL 库不能 immutable（会读不到未 checkpoint 数据），维持 mode=ro。
    uri = "file:" + urllib.parse.quote(str(db_path)) + "?mode=ro"
    try:
        wal = db_path.with_name(db_path.name + "-wal")
        if not wal.exists() or wal.stat().st_size == 0:
            uri += "&immutable=1"
    except OSError:
        pass
    last_err = None
    for attempt in range(SQLITE_RETRIES):
        try:
            con = sqlite3.connect(uri, uri=True, timeout=1.0)
            try:
                row = con.execute(
                    "select run_id, spec_json, order_id, turn_index, transcript_json,"
                    " stop_state_json, model_calls, terminal_json from run_row"
                ).fetchone()
            finally:
                con.close()
            if row is None:
                return None
            return {
                "run_id": row[0],
                "spec_json": row[1],
                "order_id": row[2],
                "turn_index": row[3],
                "transcript_json": row[4],
                "stop_state_json": row[5],
                "model_calls": row[6],
                "terminal_json": row[7],
            }
        except sqlite3.DatabaseError as exc:
            # 结构性损坏（file is not a database 等）重试无意义，立即失败隔离到单 run
            # （红队 R1-P2：损坏库白耗 3 次退避拖慢 daemon）。
            if isinstance(exc, sqlite3.OperationalError) and "locked" not in str(exc).lower():
                raise RuntimeError(f"harness.db 不可读({db_path}): {exc}")
            if not isinstance(exc, sqlite3.OperationalError):
                raise RuntimeError(f"harness.db 损坏({db_path}): {exc}")
            last_err = exc  # 锁/WAL 恢复：退避重试
            time.sleep(SQLITE_BACKOFF_S * (attempt + 1))
    raise RuntimeError(f"harness.db 读取失败({db_path}): {last_err}")


# --------------------------------------------------------------------------- #
# normal.jsonl 增量尾读
# --------------------------------------------------------------------------- #
def tail_events(leaf: Leaf, state_entry: dict, limit_events: int):
    """只读新增字节，返回 (tail 窗口 list, events_total, model_events 映射, model_latest)。

    state_entry 就地更新：offset / events_total / skipped / tail / model_events。
    """
    path = leaf.normal_jsonl
    entry = state_entry
    entry.setdefault("offset", 0)
    entry.setdefault("events_total", 0)
    entry.setdefault("skipped", 0)
    entry.setdefault("tail", [])
    entry.setdefault("model_events", {})
    entry.setdefault("ino", None)
    entry.setdefault("dev", None)
    try:
        entry["offset"] = int(entry["offset"])
    except (TypeError, ValueError):
        entry["offset"] = None  # 触发下方整体重置
    # 毒状态条目自愈（红队 R1-P2 + R2-N4/N5 扩展）：offset 非法、tail/model_events
    # 类型错、events_total/skipped 非 int——任一非法即整条目重置重读，绝不带着坏值
    # 静默产出畸形数据或让 print_report 崩 daemon。
    if (not isinstance(entry["offset"], int)
            or not isinstance(entry.get("tail"), list)
            or not isinstance(entry.get("model_events"), dict)
            or not isinstance(entry.get("events_total"), int)
            or not isinstance(entry.get("skipped"), int)):
        entry.update({"offset": 0, "events_total": 0, "skipped": 0,
                      "tail": [], "model_events": {}})

    if not path.exists():
        # 布局中本就没有 normal.jsonl：合法状态，保留旧窗口与计数
        return list(entry["tail"])[-limit_events:], entry["events_total"], entry["model_events"], None

    try:
        st = path.stat()
    except OSError:
        return list(entry["tail"])[-limit_events:], entry["events_total"], entry["model_events"], None

    # log rotate / 换 inode 检测（红队 R1-P1：同尺寸替换或 offset 落新文件行中间时
    # 静默混账）。inode 或设备号变化即整体重置，等价 tail -F 语义。
    if entry["ino"] is not None and (st.st_ino, st.st_dev) != (entry["ino"], entry["dev"]):
        entry.update({"offset": 0, "events_total": 0, "skipped": 0,
                      "tail": [], "model_events": {}})
    entry["ino"], entry["dev"] = st.st_ino, st.st_dev

    offset = int(entry["offset"])
    if st.st_size < offset:  # 文件被截断重写：从头再读
        offset = 0
        entry["events_total"] = 0
        entry["skipped"] = 0
        entry["tail"] = []
        entry["model_events"] = {}

    if st.st_size > offset:
        with open(path, "rb") as fh:
            fh.seek(offset)
            data = fh.read()
        complete = data.endswith(b"\n")
        if complete:
            chunk, rest, new_offset = data, b"", offset + len(data)
        else:
            cut = data.rfind(b"\n")
            if cut == -1:
                chunk, rest, new_offset = b"", data, offset  # 没有任何完整行，全部留待下轮
            else:
                chunk = data[: cut + 1]
                rest = data[cut + 1 :]
                new_offset = offset + cut + 1
        if rest and not complete:
            # 残行静置超时则视为写完收编（写进程已结束但末行无换行的场景）
            quiet_ms = time.time() * 1000 - st.st_mtime * 1000
            if quiet_ms >= QUIESCE_MS:
                chunk += rest
                new_offset = offset + len(data)
        offset = new_offset
        entry["offset"] = offset

        for raw in chunk.splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                ev = json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                entry["skipped"] += 1
                continue
            if not isinstance(ev, dict):
                entry["skipped"] += 1
                continue
            seq = ev.get("seq")
            kind = ev.get("kind")
            ts_ms = ev.get("ts_ms")
            payload = ev.get("payload")
            entry["events_total"] += 1
            ph, ph_hits = scrub(json.dumps(payload, ensure_ascii=False)) if payload is not None else ("", set())
            k2, k_hits = scrub(kind) if isinstance(kind, str) else (kind, set())
            for rn in ph_hits | k_hits:
                SCRUB_STATS[rn] = SCRUB_STATS.get(rn, 0) + 1
            entry["tail"].append(
                {
                    "seq": seq,
                    "kind": k2 if kind is not None else None,
                    "ts_ms": ts_ms,
                    "payload_head": ph[:120],
                }
            )
            if kind == "harness.model" and isinstance(payload, dict):
                turn = payload.get("turn")
                if isinstance(turn, int):
                    m2, _ = scrub(payload.get("model")) if isinstance(payload.get("model"), str) else (payload.get("model"), set())
                    f2, _ = scrub(payload.get("finish")) if isinstance(payload.get("finish"), str) else (payload.get("finish"), set())
                    entry["model_events"][str(turn)] = {
                        # model/finish 同样过 sanitize+scrub：孤立代理对进产物会被 jq 类
                        # 严格解析器拒收（红队 R2-N1）；自由文本一律过 K/O 脱敏
                        "model": m2,
                        "finish": f2,
                        "ts_ms": ts_ms,
                    }

    # 有界裁剪
    entry["tail"] = entry["tail"][-limit_events:]
    me = entry["model_events"]
    if len(me) > MODEL_EVENTS_CAP:
        keep = sorted(me.keys(), key=lambda k: int(k) if k.isdigit() else -1)[-MODEL_EVENTS_CAP:]
        entry["model_events"] = {k: me[k] for k in keep}
        me = entry["model_events"]

    model_latest = None
    if me:
        last_turn = max(int(k) for k in me if k.isdigit()) if any(k.isdigit() for k in me) else None
        if last_turn is not None:
            model_latest = me[str(last_turn)].get("model")
    return list(entry["tail"]), entry["events_total"], me, model_latest


# --------------------------------------------------------------------------- #
# stream json 组装
# --------------------------------------------------------------------------- #
def _usage_or_zero(u) -> dict:
    if isinstance(u, dict):
        return {k: int(u.get(k) or 0) for k in USAGE_KEYS}
    return {k: 0 for k in USAGE_KEYS}


def build_stream(leaf: Leaf, ctx: OrderContext, row: dict | None, tail, events_total, model_events, model_latest,
                 spec, limit_turns: int) -> dict:
    # ---- identity ----
    spec = spec if isinstance(spec, dict) else {}
    run_id = row.get("run_id") if row else None
    order_id = row.get("order_id") if row else None
    m = ARM_RE.search(leaf.run_dirname)
    arm = "a" + m.group("arm") if m else None
    # model 输出时再过一次 scrub：model_events 缓存在 state 里，摄入时清洗覆盖不了
    # 历史缓存（2026-10-28 主代理：脱敏必须在输出层闭环）
    model = model_latest or (spec.get("endpoint") or {}).get("model")
    if isinstance(model, str):
        model, _ = scrub(model)
    identity = {
        "order_id": order_id,
        "work_order_id": ctx.work_order_id,
        "run_id": run_id,
        "line": ctx.line_id,
        "arm": arm,
        "profile": ctx.profile_for(leaf.run_dirname),
        "model": model,
        "strategy_id": ctx.strategy_id,
        "dsl_digest": ctx.dsl_digest,
        "layout": leaf.layout,
        "node": leaf.node,
    }

    # ---- terminal（键名按规格钉死：stop_state/turn_index/model_calls）----
    stop_state = None
    if row and row.get("stop_state_json"):
        try:
            stop_state = json.loads(row["stop_state_json"])
        except (ValueError, TypeError):
            stop_state = None
    terminal = {
        "stop_state": stop_state,
        "turn_index": row.get("turn_index") if row else None,
        "model_calls": row.get("model_calls") if row else None,
    }

    # ---- turns（transcript_json 逐轮解析）----
    transcript = []
    if row and row.get("transcript_json"):
        try:
            parsed = json.loads(row["transcript_json"])
            if isinstance(parsed, list):
                transcript = [e for e in parsed if isinstance(e, dict)]
        except (ValueError, TypeError):
            transcript = []

    usage_sum = {k: 0 for k in USAGE_KEYS}
    turns_out = []
    assistant_idx = 0
    start = max(0, len(transcript) - limit_turns)
    for i, entry in enumerate(transcript):
        role = entry.get("role")
        usage = _usage_or_zero(entry.get("usage"))
        if role == "assistant":
            for k in USAGE_KEYS:
                usage_sum[k] += usage[k]
        if i < start:
            if role == "assistant":
                assistant_idx += 1
            continue
        mev = None
        if role == "assistant":
            mev = model_events.get(str(assistant_idx))
            assistant_idx += 1
        text = entry.get("text")
        if not text and role == "tool":
            # publish-gate.md §1.4 裁决：tool 输出是路径/内网信息主要载体，不入 preview
            # （红队 R1-P1：原实现取 output 违反该裁决，F5 reader preview 实测带 curl stderr）。
            text = "▉tool 输出已按 publish-gate §1.4 裁决屏蔽"
        pv, pv_hits = scrub(str(text or ""))
        for rn in pv_hits:
            SCRUB_STATS[rn] = SCRUB_STATS.get(rn, 0) + 1
        preview = pv[:200]
        turns_out.append(
            {
                "turn": i,
                "role": role,
                # model/finish 输出时过 scrub（state 缓存的历史值未经过摄入时清洗）
                "model": (scrub((mev or {}).get("model"))[0] if isinstance((mev or {}).get("model"), str) else None) if role == "assistant" else None,
                "finish": (scrub((mev or {}).get("finish"))[0] if isinstance((mev or {}).get("finish"), str) else None) if role == "assistant" else None,
                "usage": usage,
                "preview": preview,
                "ts_ms": (mev or {}).get("ts_ms") if role == "assistant" else None,
            }
        )

    return {
        "identity": identity,
        "updated_ms": int(time.time() * 1000),
        "terminal": terminal,
        "turns": turns_out,
        # events 输出时再过 scrub：tail 缓存在 state 里的历史条目，摄入时清洗覆盖不了
        "events": [
            {
                "seq": e.get("seq"),
                "kind": scrub(e.get("kind"))[0] if isinstance(e.get("kind"), str) else e.get("kind"),
                "ts_ms": e.get("ts_ms"),
                "payload_head": (scrub(e.get("payload_head") or "")[0])[:120],
            }
            for e in tail
        ],
        "counts": {
            "events_total": events_total,
            "turns_total": len(transcript),
            "usage_sum": usage_sum,
        },
    }


# --------------------------------------------------------------------------- #
# 原子写 + 状态文件
# --------------------------------------------------------------------------- #
def atomic_write_json(path: Path, obj, ensure_ascii: bool = False) -> None:
    """原子覆写：同目录带 pid 的临时文件 + fsync + os.replace。

    - tmp 名含 pid：并发双跑不互抢固定名 tmp（红队 R1-P1：败者 FileNotFoundError）。
    - UnicodeEncodeError 兜底改 ensure_ascii=True 重写：孤立代理对等脏字符进产物时
      不再让整个进程崩溃（红队 R1-P0 crash-loop 根因之一）。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=ensure_ascii, indent=1)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
    except UnicodeEncodeError:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=True, indent=1)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
    os.replace(tmp, path)


def load_state(path: Path) -> dict:
    state = _load_json(path)
    if not isinstance(state, dict) or state.get("version") != STATE_VERSION:
        state = {"version": STATE_VERSION, "runs": {}}
    state.setdefault("runs", {})
    return state


# --------------------------------------------------------------------------- #
# 扫描一遍
# --------------------------------------------------------------------------- #
def scan_once(leaves: list[Leaf], out_root: Path, state_path: Path,
              limit_turns: int, limit_events: int, gc_stale: bool = False
              ) -> tuple[list[dict], dict]:
    """返回 (每 run 结果, 每 run_key 的 stream dict 供调用方抽查)。"""
    state = load_state(state_path)
    ctx_cache: dict[str, OrderContext] = {}
    run_results: list[dict] = []
    streams: dict[str, dict] = {}

    # run_key 冲突检测（红队 R1-P1：run 目录名含 '__' 时叶子键可能与另一扁平 run 同键，
    # 静默合并成错误数据）。冲突者保留首个，其余显式报 error 跳过。
    seen_keys: dict[str, str] = {}
    for leaf in leaves:
        first = seen_keys.get(leaf.run_key)
        if first is None:
            seen_keys[leaf.run_key] = leaf.leaf_dir.as_posix()
            continue
        run_results.append({
            "run_key": leaf.run_key, "order": leaf.order_name, "layout": leaf.layout,
            "node": leaf.node, "events": 0, "turns": 0, "terminal_kind": None,
            "error": f"run_key 冲突：与 {first} 同键（目录名含 '__' 歧义），跳过",
        })
    dropped = {r["run_key"] for r in run_results if r["error"]}

    for leaf in leaves:
        if leaf.run_key in dropped and seen_keys[leaf.run_key] != leaf.leaf_dir.as_posix():
            continue
        res = {"run_key": leaf.run_key, "order": leaf.order_name, "layout": leaf.layout,
               "node": leaf.node, "events": 0, "turns": 0, "terminal_kind": None,
               "skipped": 0, "error": None}
        try:
            ctx = ctx_cache.get(leaf.order_name)
            if ctx is None:
                ctx = ctx_cache[leaf.order_name] = OrderContext(leaf.order_dir)

            entry = state["runs"].setdefault(leaf.run_key, {})
            tail, events_total, model_events, model_latest = tail_events(leaf, entry, limit_events)

            row = None
            spec = None
            if leaf.harness_db.exists():
                row = read_run_row(leaf.harness_db)
                if row and row.get("spec_json"):
                    try:
                        spec = json.loads(row["spec_json"])
                    except (ValueError, TypeError):
                        spec = None
            stream = build_stream(leaf, ctx, row, tail, events_total, model_events, model_latest,
                                  spec, limit_turns)
            atomic_write_json(out_root / f"{leaf.run_key}.json", stream)
            res["events"] = events_total
            res["turns"] = stream["counts"]["turns_total"]
            res["skipped"] = entry.get("skipped", 0)
            res["terminal_kind"] = _terminal_kind_of(row)
            streams[leaf.run_key] = stream
        except Exception as exc:  # 单 run 失败不中断全批
            res["error"] = f"{type(exc).__name__}: {exc}"
        run_results.append(res)

    # 陈旧产物 GC（红队 R1-P2：run 消失后旧 json 永久滞留供脏数据）。仅在未过滤全量
    # 扫描时执行，防 --orders 过滤场景误删其他订单产物。
    # 红队 R2-N3 勘误：live 集合取**发现的** run 键（seen_keys）而非成功产出的 streams——
    # 瞬时错误（锁超时/临时权限）的 run 不能被 GC 掉其上一轮好快照。
    if gc_stale:
        live = {f"{k}.json" for k in seen_keys} | {STATE_FILENAME}
        try:
            for f in out_root.glob("*.json"):
                if f.name not in live and not f.name.startswith("."):
                    f.unlink(missing_ok=True)
        except OSError as exc:
            print(f"[stream-tailer] GC 警告: {exc}", file=sys.stderr)

    state["updated_ms"] = int(time.time() * 1000)
    try:
        atomic_write_json(state_path, state, ensure_ascii=True)
    except OSError as exc:
        # 状态文件路径是目录/权限不足等：降级为警告，不让整扫崩溃
        # （红队 R1-P1：IsADirectoryError 全局崩溃、daemon 死）。
        print(f"[stream-tailer] 状态文件写入失败（本轮进度不持久化）: {exc}", file=sys.stderr)
    return run_results, streams


def _terminal_kind_of(row: dict | None):
    """终态 kind：run_row.terminal_json 的 kind 字段（结果表用，不进 stream json）。"""
    if row and row.get("terminal_json"):
        try:
            tj = json.loads(row["terminal_json"])
            if isinstance(tj, dict):
                return tj.get("kind")
        except (ValueError, TypeError):
            return None
    return None


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def print_report(run_results: list[dict]) -> None:
    orders: dict[str, dict] = {}
    for r in run_results:
        o = orders.setdefault(r["order"], {"runs": 0, "layouts": set(), "events": 0,
                                           "turns": 0, "terminals": [], "errors": 0,
                                           "skipped": 0})
        o["runs"] += 1
        o["layouts"].add(r["layout"])
        o["events"] += r["events"]
        o["turns"] += r["turns"]
        o["skipped"] += r.get("skipped") or 0
        if r["terminal_kind"]:
            o["terminals"].append(str(r["terminal_kind"]))
        if r["error"]:
            o["errors"] += 1

    print(f"{'订单':<44} {'run数':>4} {'布局':<14} {'事件':>6} {'轮数':>6} {'终态':<24} {'跳过':>4} error")
    total_skipped = 0
    for name in sorted(orders):
        o = orders[name]
        layouts = "+".join(sorted(o["layouts"]))
        terminals = ",".join(sorted(set(o["terminals"]))) or "-"
        err = "无" if o["errors"] == 0 else f"有({o['errors']})"
        total_skipped += o["skipped"]
        print(f"{name:<44} {o['runs']:>4} {layouts:<14} {o['events']:>6} {o['turns']:>6} "
              f"{terminals:<24} {o['skipped']:>4} {err}")
    if total_skipped:
        print(f"[stream-tailer] 注意：共 {total_skipped} 行坏事件被跳过（详见状态文件 skipped 字段）",
              file=sys.stderr)


def _positive_int(v: str) -> int:
    iv = int(v)
    if iv < 1:
        raise argparse.ArgumentTypeError("必须为正整数（0 会让尾窗取全量/负值乱窗）")
    return iv


def _materialize_quota(out_root: Path) -> None:
    """把 状态观测/quota.json 物化到 看板/（页面 fetch ../quota.json 的消费位；
    DESIGN-SUMMARY §六.3 遗留项收口，publish 五类白名单之一）。源缺失/相同则跳过。"""
    src = WS_ROOT / "状态观测" / "quota.json"
    dst = out_root.parent / "quota.json"
    try:
        if not src.is_file():
            return
        data = src.read_bytes()
        if dst.is_file() and dst.read_bytes() == data:
            return
        tmp = dst.with_name(f"quota.json.{os.getpid()}.tmp")
        tmp.write_bytes(data)
        os.replace(tmp, dst)
    except OSError as exc:
        print(f"[stream-tailer] quota 物化跳过: {exc}", file=sys.stderr)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="run 流尾随器：把 harness run 状态抽成看板 stream json")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true", help="全量扫一遍并覆写所有 run 的 stream json 后退出")
    mode.add_argument("--daemon", action="store_true", help="守护模式：循环轮询")
    ap.add_argument("--interval", type=float, default=10.0, help="daemon 轮询间隔秒数（默认 10）")
    ap.add_argument("--orders", default="*", help="订单目录名 glob 过滤（默认 * 全部）")
    ap.add_argument("--limit-turns", type=_positive_int, default=20, help="turns 窗口大小（默认 20）")
    ap.add_argument("--limit-events", type=_positive_int, default=50, help="events 尾窗大小（默认 50）")
    ap.add_argument("--no-gc", action="store_true",
                    help="全量扫描时不清理已消失 run 的陈旧 stream json（默认清理）")
    ap.add_argument("--out-root", default=str(DEFAULT_OUT_ROOT),
                    help=f"stream json 输出目录（默认 {DEFAULT_OUT_ROOT}）")
    ap.add_argument("--orders-dir", default=str(ORDERS_DIR),
                    help=f"订单状态根目录（默认 {ORDERS_DIR}；anolis 部署指向 af-p3-state/orders）")
    args = ap.parse_args(argv)

    if args.interval <= 0:
        ap.error("--interval 必须为正数（红队 R2-N7：负值会让 daemon 在 sleep 崩溃）")
    out_root = Path(args.out_root)
    state_path = out_root / STATE_FILENAME

    def one_pass() -> int:
        stop_file = out_root.parent / "TAILER-STOP"
        if stop_file.exists():
            print("[stream-tailer] TAILER-STOP 熔断在位，本轮跳过", flush=True)
            return 0
        leaves = discover_leaves(args.orders, Path(args.orders_dir))
        if not leaves:
            # 目录打错/glob 零命中必须响亮失败（红队 R1-P2：原实现 runs=0 静默 exit 0）
            print(f"[stream-tailer] 零 run 命中：orders_dir={args.orders_dir} glob={args.orders}，"
                  f"请核对路径与过滤串", file=sys.stderr)
            return 2
        gc_stale = (args.orders == "*") and not args.no_gc
        run_results, _ = scan_once(leaves, out_root, state_path, args.limit_turns,
                                   args.limit_events, gc_stale=gc_stale)
        _materialize_quota(out_root)
        err_lines = [f"  [{r['layout']}/{r['node'] or '-'}] {r['run_key']}: {r['error']}"
                     for r in run_results if r["error"]]
        print(f"[stream-tailer] runs={len(run_results)} orders={args.orders} "
              f"errors={len(err_lines)} out={out_root}")
        print_report(run_results)
        for line in err_lines:
            print(line, file=sys.stderr)
        if SCRUB_STATS:
            print(f"[stream-tailer] 脱敏命中（K/O 规则，进程累计）："
                  f"{dict(sorted(SCRUB_STATS.items()))}", file=sys.stderr)
        return 1 if err_lines else 0

    if args.once:
        return one_pass()

    # daemon
    print(f"[stream-tailer] daemon 启动：interval={args.interval}s orders={args.orders} out={out_root}",
          flush=True)
    try:
        while True:
            rc = one_pass()
            print(f"[stream-tailer] 本轮退出码={rc}，{args.interval}s 后下一轮", flush=True)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("[stream-tailer] 收到中断，退出", flush=True)
        return 0


if __name__ == "__main__":
    sys.exit(main())
