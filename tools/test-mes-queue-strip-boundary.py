#!/usr/bin/env python3
"""test-mes-queue-strip-boundary.py — MES 队列消费边界字节精确 回归门（strip 撕裂环收口，2026-11-02）

背景（RT 发现「MES 队列消费边界 strip() 撕裂环」）：replay_mes_queue 拉回队列此前走
sh().strip()，消费边界=去白长度恒短于真实前缘 → tail -c +(consumed+1) 每轮留尾字节：
每笔门户事件漏一个尾部 "}" 入隔离件（203MB/22.5 万行的直接进料）、gov 队列残留 1B
"\n" 种子且空白轮 return 0 不截断=永不清零。修复：cat 改 shb() 字节精确读，
consumed=实读字节数，空白残渣轮也推进边界。

本门在 tempfile 沙箱实跑生产 replay_mes_queue/_mes_truncate_gov 全链路：
sh/shb 按 ssh 命令形重写到本地沙箱队列文件（_mes_truncate_gov 的 tail -c 算术
原样执行，非复刻件）；ch_client/_mes_insert 打桩为本地 MES 沉淀池（去重口径同产线）。
  A 边界精确：A1 干净单事件轮后队列清零（修复前漏 b"\\n"）；A2 孤立 "\\n" 种子轮清零
    （修复前 return 0 永挂 1B）；B 种子+事件轮（修复前漏 b"}\\n"）；
    C 孤立 "}" 残渣轮恰隔离一条且清零（修复前隔离后仍留 b"\\n" 复发）
  D 交替 8 轮仿真（奇数轮门户追加 1 事件/偶数轮空闲，种子残渣起局）：每轮终态
    队列恒空、事件各恰投一次、隔离件零写入（修复前 b"}\\n"/b"\\n" 振荡+轮轮隔离 "}"）
  E 半行对齐不回退：完整行+撕裂尾行，只消费完整行，尾行逐字节留盘
  F 非 ASCII 事件字节精确（ensure_ascii=False 口径）
可选 argv[1]=被测模块路径（默认 tools/factory-status-push.py；指 .bak 可复演修复前红）。
退出码 0=全过；断言失败非零退出并点名断言。"""
import importlib.util
from importlib.machinery import SourceFileLoader
import json
import os
import re
import subprocess
import sys
import tempfile
from types import SimpleNamespace

_TOOLS = os.path.dirname(os.path.abspath(__file__))
_UNDER = sys.argv[1] if len(sys.argv) > 1 else os.path.join(_TOOLS, "factory-status-push.py")
# SourceFileLoader 显式指定：argv[1] 可指 .bak 等非 .py 后缀件（复演修复前红）
_loader = SourceFileLoader("factory_status_push_under_test", _UNDER)
_spec = importlib.util.spec_from_file_location("factory_status_push_under_test", _UNDER,
                                               loader=_loader)
fsp = importlib.util.module_from_spec(_spec)
_loader.exec_module(fsp)


def fail(msg):
    print(f"FAIL {msg}", flush=True)
    sys.exit(1)


# ---- 沙箱：ssh 命令形重写到本地队列文件（gov 侧零触碰）----
Q = None   # 沙箱队列文件路径（main 里定）
_SSH_RE = re.compile(r"^ssh .*?'(.*)'\s*$", re.S)   # SSH_OPTS 带空格：取首尾单引号内整段


def _local(cmd):
    m = _SSH_RE.match(cmd)
    if not m:
        fail(f"沙箱收到非 ssh 形命令: {cmd[:100]!r}")
    return m.group(1).replace(fsp.MES_QUEUE_GOV, Q)


def fake_sh(cmd, timeout=30):
    r = subprocess.run(_local(cmd), shell=True, capture_output=True, text=True, timeout=timeout)
    return (r.stdout or "").strip()


def fake_shb(cmd, timeout=30):
    r = subprocess.run(_local(cmd), shell=True, capture_output=True, timeout=timeout)
    return r.stdout or b""


# ---- MES 沉淀池打桩（去重口径同产线：query_post 查已入池 id，insert 入池）----
SINK = set()


def fake_insert(events):
    for e in events:
        SINK.add(e["event_id"])


def fake_query_post(sql):
    return [{"event_id": eid} for eid in sorted(SINK) if ("'" + eid + "'") in sql]


def ev(i, sandbox="portal-line"):
    """门户 mes_event() 同构事件（af-jobs-portal.py 行格式 v1）"""
    return {"v": 1, "work_order_id": f"af-jobs-wo{i}", "occurred_at": "2026-11-02 07:10:00",
            "occurred_at_ms": 1793565000000 + i, "event_id": f"af-jobs-ev-{i:03d}",
            "line_id": "af-jobs", "station_id": "portal", "kind": "sandbox_report",
            "quantity": 1, "task_id": f"t{i}", "sandbox": sandbox,
            "ts": 1793565000 + i, "token_fp": "d820cbdc"}


def append(line_bytes):
    with open(Q, "ab") as f:
        f.write(line_bytes)


def disk():
    with open(Q, "rb") as f:
        return f.read()


def round_run():
    """跑一轮生产 replay_mes_queue；补投失败=红（产线语义：该轮不该失败）"""
    try:
        return fsp.replay_mes_queue()
    except Exception as e:  # noqa: BLE001
        fail(f"replay_mes_queue 抛异常（产线该轮应成功）: {type(e).__name__}: {e}")


def main():
    global Q
    with tempfile.TemporaryDirectory(prefix="mes-strip-boundary-test.") as td:
        Q = os.path.join(td, "mes-events.jsonl")
        fsp.sh = fake_sh
        fsp.shb = fake_shb
        fsp._mes_insert = fake_insert
        fsp.ch_client = SimpleNamespace(query_post=fake_query_post)
        fsp.MES_QUEUE_BAD = os.path.join(td, "mes-queue-bad.jsonl")
        fsp.ALARMS_LOG = os.path.join(td, "alarms.log")

        e1 = json.dumps(ev(1), ensure_ascii=False).encode() + b"\n"

        # A1 干净单事件：整行消费，队列清零（修复前 strip 漏算尾 \n → 留 b"\n"）
        append(e1)
        if round_run() != 1:
            fail("A1 干净单事件应投递 1 笔")
        if disk() != b"":
            fail(f"A1 消费后队列未清零，残留 {disk()!r}（strip 撕裂环未收口？）")

        # A2 孤立 "\n" 种子（现场 gov 实读签名）：清零且返回 0（修复前 return 0 永挂 1B）
        append(b"\n")
        if round_run() != 0:
            fail("A2 空白种子轮应返回 0（无可投事件）")
        if disk() != b"":
            fail(f"A2 空白种子未清零，残留 {disk()!r}（残渣永不清零路径未收口？）")

        # B 种子+事件（现场轮签名 \n{event}\n）：事件投递、无坏行、清零（修复前漏 b"}\n"）
        e2 = json.dumps(ev(2), ensure_ascii=False).encode() + b"\n"
        append(b"\n" + e2)
        if round_run() != 1:
            fail("B 种子+事件轮应投递 1 笔")
        if disk() != b"":
            fail(f"B 消费后队列未清零，残留 {disk()!r}")

        # C 孤立 "}" 残渣：恰隔离一条、清零、不复发（修复前隔离后仍留 b"\n"）
        append(b"}\n")
        if round_run() != 0:
            fail("C 纯残渣轮应返回 0")
        if disk() != b"":
            fail(f"C 残渣轮后未清零，残留 {disk()!r}")
        if not os.path.isfile(fsp.MES_QUEUE_BAD):
            fail("C 残渣 '}' 应入隔离件（不静默丢弃）")
        with open(fsp.MES_QUEUE_BAD, encoding="utf-8") as f:
            quarantined = [l.rstrip("\n") for l in f if l.strip()]
        if quarantined != ["}"]:
            fail(f"C 隔离内容应为恰一条 '}}'，实为 {quarantined!r}")
        os.remove(fsp.MES_QUEUE_BAD)

        # D 交替 8 轮仿真：种子残渣起局，奇数轮门户追加 1 事件/偶数轮空闲。
        # 断言：每轮终态队列恒空、4 笔各恰投一次、隔离件零写入。
        SINK.clear()
        append(b"\n")
        delivered = 0
        n = 0
        for r in range(1, 9):
            if r % 2 == 1:
                n += 1
                append(json.dumps(ev(100 + n), ensure_ascii=False).encode() + b"\n")
            delivered += round_run()
            if disk() != b"":
                fail(f"D round{r} 终态队列未清零，残留 {disk()[:60]!r}…（撕裂环复发？）")
        if delivered != 4:
            fail(f"D 应恰投 4 笔，实投 {delivered}")
        if SINK != {f"af-jobs-ev-{100 + i:03d}" for i in range(1, 5)}:
            fail(f"D 沉淀池内容异常: {sorted(SINK)}")
        if os.path.exists(fsp.MES_QUEUE_BAD) and os.path.getsize(fsp.MES_QUEUE_BAD):
            fail("D 正常事件流不应产生任何隔离写入（每事件漏 '}' 即撕裂环复发）")

        # E 半行对齐不回退：完整行+撕裂尾行，只消费完整行，尾行逐字节留盘
        append(e1 + b'{"par')
        if round_run() != 1:
            fail("E 完整行应投递 1 笔")
        if disk() != b'{"par':
            fail(f"E 撕裂尾行应逐字节留盘，实为 {disk()!r}（半行被拆/被吞？）")

        # F 非 ASCII 事件（ensure_ascii=False 口径）字节精确消费
        with open(Q, "wb"):
            pass
        append(json.dumps(ev(7, sandbox="铸锻一号线"), ensure_ascii=False).encode("utf-8") + b"\n")
        if round_run() != 1:
            fail("F 非 ASCII 事件应投递 1 笔")
        if disk() != b"":
            fail(f"F 非 ASCII 事件消费后未清零，残留 {disk()!r}")

    print("PASS A1干净单事件清零 A2空白种子清零 B种子+事件不漏'}' C残渣恰隔离一条 D交替8轮"
          "队列恒空+恰投一次+隔离零写入 E半行逐字节留盘 F非ASCII字节精确 — 全过"
          f"（沙箱实跑生产 replay/_mes_truncate_gov，被测件={os.path.basename(_UNDER)}）")
    sys.exit(0)


if __name__ == "__main__":
    main()
