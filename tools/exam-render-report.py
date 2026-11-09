#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""exam-render-report.py — 终考 Feature C（EXAM-E3 · #297）：考试聚合报告 markdown 渲染器

输入：Feature B（tools/exam-aggregate.py）输出的 stats JSON 文件路径（argv[1]）。
输出（stdout）：模板逐行固定的 markdown 报告——

  # 考试聚合报告
  （空行）
  - 总卡数: <total_cards>
  - 总内存预算: <total_mem_budget>G
  - 每波卡数:
  每波一行：  - <wave>: <n>（cards_per_wave 键升序）
  - 状态分布:
  每态一行：  - <state>: <n>（state_distribution 键升序）
  - 通道分布:
  每通道一行：  - <channel>: <n>（channel_distribution 键升序）

条目行两空格缩进；三组内键均按码点升序；末尾恰一个换行；
三 dict 为空时只剩标题行、空行、两总计行与三节标题行（零条目行）。

非法输入（文件缺／不可读／非 UTF-8／坏 JSON／根非对象／缺字段／字段类型错）：
stderr 一行 `E: <原因>`，exit 2；stdout 不出半份报告（先整份拼好再写）。
确定性：零时间戳／零随机／零环境依赖，同输入两次运行 stdout 逐字节相同；
stdout/stderr 强制 UTF-8，不随 locale 漂移。

只消费模板所需五字段（total_cards／total_mem_budget／cards_per_wave／
state_distribution／channel_distribution）；多余键（如 waves）忽略不计。

用法：
  python3 -I tools/exam-render-report.py stats.json
"""

import json
import sys

REQUIRED = (
    "total_cards",
    "total_mem_budget",
    "cards_per_wave",
    "state_distribution",
    "channel_distribution",
)

SECTIONS = (
    ("cards_per_wave", "每波卡数"),
    ("state_distribution", "状态分布"),
    ("channel_distribution", "通道分布"),
)

_TYPE_NAMES = {
    dict: "object",
    list: "array",
    str: "string",
    bool: "boolean",
    int: "number",
    float: "number",
    type(None): "null",
}


def fail(reason):
    """非法输入统一出口：stderr 一行 `E: <原因>`，exit 2。"""
    sys.stderr.write("E: %s\n" % reason)
    sys.stderr.flush()
    raise SystemExit(2)


def json_type_name(value):
    return _TYPE_NAMES.get(type(value), type(value).__name__)


def as_int(value, field):
    """计数字段必须为整数（bool 虽是 int 子类，不算数）。"""
    if isinstance(value, bool) or not isinstance(value, int):
        fail("字段 %s 应为整数，实得 %s" % (field, json_type_name(value)))
    return str(value)


def as_count_dict(value, field):
    """计数 dict：JSON 对象，值全为整数。逐值校验后再交调用方排序。"""
    if not isinstance(value, dict):
        fail("字段 %s 应为对象，实得 %s" % (field, json_type_name(value)))
    counts = {}
    for key in value:
        counts[key] = as_int(value[key], "%s[%s]" % (field, key))
    return counts


def render(stats):
    """stats（已通过 json.loads 的 dict）→ 整份报告文本（末尾恰一个换行）。"""
    if not isinstance(stats, dict):
        fail("stats 根应为 JSON 对象，实得 %s" % json_type_name(stats))
    for field in REQUIRED:
        if field not in stats:
            fail("缺字段：%s" % field)
    lines = ["# 考试聚合报告", ""]
    lines.append("- 总卡数: %s" % as_int(stats["total_cards"], "total_cards"))
    lines.append(
        "- 总内存预算: %sG"
        % as_int(stats["total_mem_budget"], "total_mem_budget")
    )
    for field, label in SECTIONS:
        lines.append("- %s:" % label)
        counts = as_count_dict(stats[field], field)
        for key in sorted(counts):
            lines.append("  - %s: %s" % (key, counts[key]))
    return "\n".join(lines) + "\n"


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    if len(argv) < 2:
        fail("用法：exam-render-report.py <stats.json>（argv[1] 缺）")
    path = argv[1]
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = handle.read()
    except OSError:
        fail("文件缺或不可读：%s" % path)
    except UnicodeDecodeError:
        fail("文件非 UTF-8：%s" % path)
    try:
        stats = json.loads(raw)
    except ValueError as exc:
        fail("坏 JSON：%s" % exc)
    sys.stdout.write(render(stats))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
