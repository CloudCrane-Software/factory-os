#!/usr/bin/env python3
"""test-mes-queue-bad-cap.py — MES 坏行隔离件大小上限+轮转+告警 回归门（DEB57 收尾批，2026-11-02）

背景（RT-E33 拦截③收口）：状态观测/mes-queue-bad.jsonl 曾因 62h+ 补投死循环把同一批
73 条粘连坏行每轮重写（原「解析即隔离」在失败轮也落盘），隔离件无大小上限、无告警钩子，
涨到 ~203MB/22.5 万行（99.9%+ 为同一批行重复）。2026-11-02 修复（factory-status-push.py
_mes_quarantine/_mes_quarantine_rotate）：写入前上限检查，超限把活件改名时间戳 .rot 归档
+ amber 告警（alarms.log），归档保 MES_QUEUE_BAD_MAX_ARCHIVES 份（超份删最旧=告警在案的
容量策略，非静默丢弃）。

本门全部在 tempfile 沙箱目录实跑 _mes_quarantine，生产文件/告警面零触碰
（monkeypatch MES_QUEUE_BAD/ALARMS_LOG/上限常量后按字节预算灌入）：
  A 保留期内（归档份数上限设大，不触发清理）：
    A1 常态小写入：不轮转、不告警、原样追加（修复不扰动正常路径）
    A2 上限闸：活件恒 ≤ 上限+单笔；超限必轮转（.rot 出现、amber 逐次落盘）
    A3 不静默丢弃：活件+全部归档行数合计 == 写入行数（内容原样保全）
    A4 命名序：归档名字典序==时间序（定宽 ms 尾）
  B 容量策略（份数上限=2）：第 3 次轮转必删最旧归档——份数恒 ≤ 上限（不无限堆）
退出码 0=全过；断言失败非零退出并点名断言。"""
import glob
import importlib.util
import json
import os
import sys
import tempfile

_TOOLS = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "factory_status_push_under_test", os.path.join(_TOOLS, "factory-status-push.py"))
fsp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fsp)


def fail(msg):
    print(f"FAIL {msg}", flush=True)
    sys.exit(1)


def rot_files(bad):
    return sorted(glob.glob(bad + ".*.rot"))


def alarms(path, code):
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip() and json.loads(l).get("code") == code]


def count_lines(path):
    with open(path, encoding="utf-8") as f:
        return sum(1 for l in f if l.strip())


def main():
    with tempfile.TemporaryDirectory(prefix="mes-bad-cap-test.") as td:
        bad = os.path.join(td, "mes-queue-bad.jsonl")
        alm = os.path.join(td, "alarms.log")
        fsp.MES_QUEUE_BAD = bad
        fsp.ALARMS_LOG = alm
        fsp.MES_QUEUE_BAD_MAX_BYTES = 4096
        fsp.MES_QUEUE_BAD_MAX_ARCHIVES = 10   # A 段：份数上限不触发，专验不丢弃

        # A1 常态小写入：不轮转、不告警
        small = ['{"bad":%d}' % i for i in range(5)]
        fsp._mes_quarantine(small)
        live0 = os.path.getsize(bad)
        if live0 != sum(len(s) + 1 for s in small):
            fail(f"A1 常态追加字节数不符 live={live0}")
        if rot_files(bad):
            fail(f"A1 常态小写入不应轮转，却有 {rot_files(bad)}")
        if alarms(alm, "mes-quarantine"):
            fail("A1 常态小写入不应告警")

        # A2/A3 超限灌入：125 行 ≈ 12.2KB ≫ 4KB 上限 → 必轮转
        line = '{"glued":"' + "x" * 86 + '"}'   # 单行 97B
        written = len(small)
        for _ in range(125):
            fsp._mes_quarantine([line])
            written += 1
            live = os.path.getsize(bad)
            if live > fsp.MES_QUEUE_BAD_MAX_BYTES + len(line) + 1:
                fail(f"A2 活件 {live}B 超出上限 {fsp.MES_QUEUE_BAD_MAX_BYTES}+单笔")
        rots = rot_files(bad)
        if not rots:
            fail("A2 超限灌入后无 .rot 归档——上限闸未生效")
        am = alarms(alm, "mes-quarantine")
        if len(am) != len(rots):
            fail(f"A2 轮转 {len(rots)} 次但告警 {len(am)} 条（每次轮转应恰一条 amber）")
        for a in am:
            if a.get("level") != "amber":
                fail(f"A2 告警级别应为 amber，实为 {a.get('level')}")

        # A3 不静默丢弃：保留期内行数守恒（A 段 MAX_ARCHIVES=10，无清理发生）
        on_disk = count_lines(bad) + sum(count_lines(p) for p in rots)
        if on_disk != written:
            fail(f"A3 行数守恒破：写入 {written}，活件+归档 {on_disk}（静默丢弃？）")

        # A4 命名序：字典序==时间序
        mtimes = [os.path.getmtime(p) for p in rots]
        if mtimes != sorted(mtimes):
            fail(f"A4 归档名序与时间序不一致：{list(zip(rots, mtimes))}")

        # B 容量策略：份数上限收到 2，继续灌到下一次轮转 → 最旧归档必被删
        fsp.MES_QUEUE_BAD_MAX_ARCHIVES = 2
        before = set(rots)
        n_alarms = len(am)
        extra = 0
        while len(alarms(alm, "mes-quarantine")) == n_alarms and extra < 200:
            fsp._mes_quarantine([line])
            extra += 1
            if os.path.getsize(bad) > fsp.MES_QUEUE_BAD_MAX_BYTES + len(line) + 1:
                fail(f"B 活件 {os.path.getsize(bad)}B 超上限（轮转未触发？）")
        am2 = alarms(alm, "mes-quarantine")
        rots2 = rot_files(bad)
        if len(am2) != n_alarms + 1:
            fail(f"B 灌入 {extra} 行未触发新轮转（告警 {len(am2)}≠{n_alarms + 1}）")
        if len(rots2) != 2:
            fail(f"B 归档 {len(rots2)} 份 ≠ 保留上限 2（最旧未删=无界堆积）")
        purged = before - set(rots2)
        if not purged:
            fail("B 未见最旧归档被删（容量策略未生效）")
        mtimes2 = [os.path.getmtime(p) for p in rots2]
        if mtimes2 != sorted(mtimes2):
            fail(f"B 归档名序与时间序不一致：{list(zip(rots2, mtimes2))}")

    print("PASS A1常态不扰动 A2上限+轮转+amber告警 A3行数守恒(不静默丢弃) "
          "A4命名序==时间序 B归档硬上限(超份删最旧) — 全过（沙箱实跑，生产零触碰）")
    sys.exit(0)


if __name__ == "__main__":
    main()
