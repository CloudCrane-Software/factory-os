#!/usr/bin/env python3
"""exam-aggregate — 工厂终考 EXAM-E2：Feature A JSONL 的聚合统计器。

输入：Feature A（tools/exam-parse-manifest.py）输出的 JSONL 文件路径（argv[1]），
每行一个 JSON 卡对象（含 task_id/state/channel/mem_budget 等字段）。

输出（stdout）：单行 JSON（separators=(",",":") compact，sort_keys=True），键：
  waves                task_id 首段（首个 "-" 前）去重后升序列表
  cards_per_wave       每波卡数计数 dict（键升序）
  state_distribution   状态计数 dict（键升序）
  channel_distribution 通道计数 dict（键升序）
  total_cards          总行数
  total_mem_budget     mem_budget 字段求和

非法输入（文件缺/不可读/坏 JSON/缺卡字段/字段类型不符）：stderr 一行 "E: <原因>"，exit 2。
确定性：零网络、纯标准库、无时间戳/随机/环境依赖——同输入两次运行 stdout 逐字节相同。
"""
from __future__ import annotations

import json
import sys

REQUIRED_FIELDS = ("task_id", "state", "channel", "mem_budget")


def fail(reason: str) -> None:
    print("E: %s" % reason, file=sys.stderr)
    raise SystemExit(2)


def main(argv):
    if len(argv) != 1:
        fail("需要恰好一个参数：Feature A 的 JSONL 文件路径（argv[1]），实得 %d 个" % len(argv))
    path = argv[0]
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError as e:
        fail("输入文件不可读：%s（%s）" % (path, e.strerror or e))
    except UnicodeDecodeError as e:
        fail("输入不是合法 UTF-8：%s（%s）" % (path, e))

    cards_per_wave = {}
    state_distribution = {}
    channel_distribution = {}
    waves = set()
    total_cards = 0
    total_mem_budget = 0

    for lineno, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line:
            continue  # 行尾换行/空白行不构成一张卡
        try:
            card = json.loads(line)
        except json.JSONDecodeError as e:
            fail("第 %d 行坏 JSON：%s" % (lineno, e.msg))
        if not isinstance(card, dict):
            fail("第 %d 行不是 JSON 对象：%s" % (lineno, type(card).__name__))
        missing = [k for k in REQUIRED_FIELDS if k not in card]
        if missing:
            fail("第 %d 行缺卡字段：%s" % (lineno, ",".join(missing)))

        task_id = card["task_id"]
        state = card["state"]
        channel = card["channel"]
        mem_budget = card["mem_budget"]
        if not isinstance(task_id, str):
            fail("第 %d 行 task_id 不是字符串：%r" % (lineno, task_id))
        if not isinstance(state, str):
            fail("第 %d 行 state 不是字符串：%r" % (lineno, state))
        if not isinstance(channel, str):
            fail("第 %d 行 channel 不是字符串：%r" % (lineno, channel))
        if isinstance(mem_budget, bool) or not isinstance(mem_budget, (int, float)):
            fail("第 %d 行 mem_budget 不是数值：%r" % (lineno, mem_budget))

        wave = task_id.split("-", 1)[0]
        waves.add(wave)
        cards_per_wave[wave] = cards_per_wave.get(wave, 0) + 1
        state_distribution[state] = state_distribution.get(state, 0) + 1
        channel_distribution[channel] = channel_distribution.get(channel, 0) + 1
        total_cards += 1
        total_mem_budget += mem_budget

    stats = {
        "waves": sorted(waves),
        "cards_per_wave": cards_per_wave,
        "state_distribution": state_distribution,
        "channel_distribution": channel_distribution,
        "total_cards": total_cards,
        "total_mem_budget": total_mem_budget,
    }
    sys.stdout.write(json.dumps(stats, separators=(",", ":"), sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
