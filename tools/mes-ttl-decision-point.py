#!/usr/bin/env python3
# =============================================================================
# MES 5221 遗留表处置决策点 · 只读取证（红队 W1-C14 修复件，2026-10-26）
#
# 背景：mes-ttl-sweep 机制的目标端点 127.0.0.1:5221 已随回滚锚死亡、其对象集
# （mes.* 五表，合计 3,042,489 行）只存在于死锚点——授权处置链断裂。运营者
# 处置决策（30-遗产处置.md 批1：只读拉起导出归档 / 正式放弃整目录归档，二选一）
# 须在观察期满（2026-10-29 01:05:52；runbook §六-3 权威定义——红队 W2-C17
# 统一 2026-10-27，原「2026-10-28」与执行记录/keepalive 参数日期不一）后的
# 2026-10-29 09:00 决策点作出；本脚本由
# mes-ttl-decision-point.timer 单次触发，为该决策点落一份**只读取证**：
#   ① 锚点活性（5221 监听 / ch-mes-local 进程 / 数据目录在场性）；
#   ② mes-ttl-sweep 观测证据止点（state/evidence 文件 mtime 与末条内容）；
#   ③ 决策提示（两条处置路径原文，防决策点无数据可依）。
# 本脚本零写业务状态、零连 CH、零删除——只读 + 追加一行 JSONL 到
# 状态观测/mes-ttl-decision-point.jsonl（不存在则创建）。
# =============================================================================
import json
import os
import shutil
import socket
import subprocess
import sys
import time

WS = "/home/pan-ding/workspace/agent黑灯工厂"
OUT = os.path.join(WS, "状态观测", "mes-ttl-decision-point.jsonl")
ANCHOR = ("127.0.0.1", 5221)
ANCHOR_PID = 207700
DATA_DIR = "/home/pan-ding/ch-mes/data/data/mes"
SWEEP_LOG = os.path.join(WS, "状态观测", "mes-ttl-sweep.log")
STATE_FILE = os.path.join(WS, "工具状态备份", "mes-ttl-state.json")
EVIDENCE_FILE = os.path.join(WS, "工具状态备份", "mes-ttl-sweep-evidence.jsonl")

DECISION_PATHS = (
    "30-遗产处置.md 批1（红队 W1-C14 登记）：(a) 只读拉起 5221 锚点导出归档 5 表后按 "
    "mes-ttl-自删机制纪律处置归档件；或 (b) 运营者裁决放弃——数据目录整目录归档_mv + "
    "删除记录登记。裁决前 30-遗产处置 该条为唯一登记面。",
)


def port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


def file_mtime_iso(path: str):
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(path)))
    except OSError:
        return None


def last_line(path: str):
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - 4096))
            tail = fh.read().decode("utf-8", errors="replace").strip().splitlines()
        return tail[-1] if tail else None
    except OSError:
        return None


def main() -> int:
    proc_alive = False
    try:
        os.kill(ANCHOR_PID, 0)
        proc_alive = True
    except (ProcessLookupError, PermissionError):
        proc_alive = False

    row = {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "kind": "mes-5221-decision-point",
        "anchor": {
            "port_5221_listening": port_open(*ANCHOR),
            "pid_207700_alive": proc_alive,
            "data_dir_present": os.path.isdir(DATA_DIR),
        },
        "sweep_evidence": {
            "log_mtime": file_mtime_iso(SWEEP_LOG),
            "state_mtime": file_mtime_iso(STATE_FILE),
            "evidence_mtime": file_mtime_iso(EVIDENCE_FILE),
            "log_last_line": last_line(SWEEP_LOG),
        },
        "decision_paths": DECISION_PATHS,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(json.dumps(row, ensure_ascii=False, indent=2))
    if row["anchor"]["port_5221_listening"] or row["anchor"]["pid_207700_alive"]:
        print("NOTICE: 5221 锚点在场——按 30-遗产处置 路径 (a) 只读导出归档", file=sys.stderr)
    else:
        print(
            "NOTICE: 5221 锚点仍不在场——处置路径二选一（只读拉起导出 / 正式放弃整目录归档），"
            "裁决记录回 30-遗产处置.md 批1 该条",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
