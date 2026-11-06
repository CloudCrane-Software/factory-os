#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""G3 声明面机算审计（红队 W3-C-14 无关——本件为 W3-C-42 修复件，2026-10-27）。

背景：G3-全链闸门-L1L4-v2-20261024.md:78-83 原书 effect_class 拆分
「external_once 12 / persist 8 / pure 8」，与 aff4f1a 五份 components.json
机算（external_once 14 / persist 8 / pure 6）不符，且自带枚举与表头互不
一致（external_once 枚 13 项漏 pkg.autogen.tool.search、pure 枚 6 项对表头
8）。裁判 fixHint 要求「在 registry_decl_test 中增加三类 effect_class 数量
断言」——registry_decl_test.rs 在 af 仓内（本域不动 af 仓），本脚本为工作区
侧等价防线：对指定 rev 的声明快照做总量/类拆分/effect_class 三类数量断言，
防「只校验字段存在和总数」缺口回归。

用法：python3 tools/registry-effect-class-audit.py [--rev aff4f1a] [--repo PATH]
退出码：0=全断言过；1=有断言败（errors 列明细）；2=采样失败（rev/文件不存在）。
机算真值锚：aff4f1a（G3-v2 门证据基线）。
"""
import argparse
import json
import subprocess
import sys
from collections import Counter

REPO_DEFAULT = "/home/pan-ding/workspace/agent黑灯工厂/af"
REV_DEFAULT = "aff4f1a"
# aff4f1a 内声明清单五件（路径相对仓根，含 af/ 前缀目录）。
COMPONENT_FILES = (
    "af/packages/components.json",
    "af/packages/adaskit/components.json",
    "af/packages/autogen/components.json",
    "af/packages/swarmkit/components.json",
    "af/packages/sweng/components.json",
)
# P2-L11 首批 7 件（G3 扩容前在册；W3-C-42 裁判口径，57-7=50 名新声明）。
FIRST_BATCH_P2L11 = frozenset({
    "route.main", "route.cheap",
    "pkg.sweng.locate", "pkg.sweng.view", "pkg.sweng.edit", "pkg.sweng.test_unit",
    "pkg.swarmkit.tools",
})
EXPECT = {
    "all": 57,
    "new": 50,
    "new_class_counts": {"model_route": 5, "tool": 28, "unit": 13, "memory": 4},
    "tool_effect_counts": {"external_once": 14, "persist": 8, "pure": 6},
}


def _git_show(repo, rev, path):
    r = subprocess.run(["git", "-C", repo, "show", f"{rev}:{path}"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git show {rev}:{path} rc={r.returncode}: {r.stderr.strip()}")
    return r.stdout


def load_decls(repo=REPO_DEFAULT, rev=REV_DEFAULT):
    """五份 components.json 全量声明合并（git show 快照，只读）。"""
    decls = []
    for rel in COMPONENT_FILES:
        data = json.loads(_git_show(repo, rev, rel))
        items = data.get("components", data) if isinstance(data, dict) else data
        if isinstance(items, dict):
            items = list(items.values())
        decls.extend(items)
    return decls


def audit(decls, first_batch=FIRST_BATCH_P2L11, expect=EXPECT):
    """纯机算断言：返回 {all, new, new_class_counts, tool_effect_counts, errors}。"""
    errors = []
    new = [d for d in decls if d.get("name") not in first_batch]
    class_counts = dict(Counter(d.get("class") for d in new))
    tools = [d for d in new if d.get("class") == "tool"]
    missing = [d["name"] for d in tools if not d.get("effect_class")]
    effect_counts = dict(Counter(d.get("effect_class") for d in tools
                                 if d.get("effect_class")))
    report = {
        "all": len(decls), "new": len(new),
        "new_class_counts": class_counts,
        "tool_effect_counts": effect_counts,
        "errors": errors,
    }
    if report["all"] != expect["all"]:
        errors.append(f"总量 {report['all']}≠{expect['all']}")
    if report["new"] != expect["new"]:
        errors.append(f"新声明 new {report['new']}≠{expect['new']}")
    for k, v in expect["new_class_counts"].items():
        if class_counts.get(k) != v:
            errors.append(f"class {k} {class_counts.get(k)}≠{v}")
    for k, v in expect["tool_effect_counts"].items():
        if effect_counts.get(k) != v:
            errors.append(f"effect_class {k} {effect_counts.get(k)}≠{v}")
    if missing:
        errors.append(f"{len(missing)} 件 tool 缺 effect_class 字段：{missing[:3]}…")
    return report


def audit_snapshot(repo=REPO_DEFAULT, rev=REV_DEFAULT, expect=EXPECT):
    return audit(load_decls(repo, rev), FIRST_BATCH_P2L11, expect)


def main() -> int:
    ap = argparse.ArgumentParser(description="G3 声明面机算审计（W3-C-42）")
    ap.add_argument("--repo", default=REPO_DEFAULT)
    ap.add_argument("--rev", default=REV_DEFAULT)
    args = ap.parse_args()
    try:
        report = audit_snapshot(args.repo, args.rev)
    except (RuntimeError, OSError) as e:
        print(f"SAMPLE-FAILED: {e}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["errors"]:
        print(f"AUDIT-FAILED: {len(report['errors'])} 项断言败", file=sys.stderr)
        return 1
    print(f"AUDIT-OK: {args.rev} 总量/类拆分/effect_class 三类数量断言全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
