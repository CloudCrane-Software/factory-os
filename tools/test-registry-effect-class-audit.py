#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""W3-C-42 修复测试（先红后绿）：G3 声明面机算审计件。

被测件：tools/registry-effect-class-audit.py
  - audit(decls, first_batch)  纯机算：剔除首批 → 总量/类拆分/effect_class
    三类数量逐一断言（补裁判裁定的「原 registry_decl_test 只校验字段存在
    和总数、无数量断言」缺口的工作区侧等价防线——registry_decl_test.rs 在
    af 仓内，本域不动 af 仓）。

机算真值（aff4f1a，红队 W3-C-42 裁判复算+本批复算一致）：
  all=57、new=50、class={model_route:5, tool:28, unit:13, memory:4}、
  28 tool 的 effect_class={external_once:14, persist:8, pure:6}。
"""
import importlib.util
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(HERE, "registry-effect-class-audit.py")

_spec = importlib.util.spec_from_file_location("reca", TARGET)
reca = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(reca)


def mk(name, cls, effect=None):
    d = {"name": name, "class": cls}
    if effect is not None:
        d["effect_class"] = effect
    return d


def truth_decls():
    """57 条：首批 7 + 新 50（5 route / 28 tool[14/8/6] / 13 unit / 4 memory）。"""
    decls = [
        mk("route.main", "tool", "pure"),          # 首批
        mk("route.cheap", "tool", "pure"),         # 首批
        mk("pkg.sweng.locate", "tool", "pure"),    # 首批
        mk("pkg.sweng.view", "tool", "pure"),      # 首批
        mk("pkg.sweng.edit", "tool", "persist"),   # 首批
        mk("pkg.sweng.test_unit", "unit"),         # 首批
        mk("pkg.swarmkit.tools", "tool", "pure"),  # 首批
    ]
    for i in range(5):
        decls.append(mk(f"route.new{i}", "model_route"))
    ecs = ["external_once"] * 14 + ["persist"] * 8 + ["pure"] * 6
    for i, ec in enumerate(ecs):
        decls.append(mk(f"tool.new{i}", "tool", ec))
    for i in range(13):
        decls.append(mk(f"unit.new{i}", "unit"))
    for i in range(4):
        decls.append(mk(f"mem.new{i}", "memory"))
    return decls


class TestAuditOnTruth(unittest.TestCase):
    def test_truth_passes(self):
        report = reca.audit(truth_decls(), reca.FIRST_BATCH_P2L11)
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["all"], 57)
        self.assertEqual(report["new"], 50)
        self.assertEqual(report["new_class_counts"],
                         {"model_route": 5, "tool": 28, "unit": 13, "memory": 4})
        self.assertEqual(report["tool_effect_counts"],
                         {"external_once": 14, "persist": 8, "pure": 6})

    def test_truth_load_from_af_repo(self):
        """集成：真仓 aff4f1a 快照机算=真值（裁判口径复现）。"""
        report = reca.audit_snapshot()
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["tool_effect_counts"],
                         {"external_once": 14, "persist": 8, "pure": 6})


class TestAuditCatchesDrift(unittest.TestCase):
    def test_wrong_effect_split_flagged(self):
        """裁判裁定之误（12/8/8 或纯 8）必须被拦下。"""
        decls = truth_decls()
        # 复刻原文书错误：两件 external_once 误标 pure → 12/8/8
        flipped = 0
        for d in decls:
            if d.get("effect_class") == "external_once" and flipped < 2:
                d["effect_class"] = "pure"
                flipped += 1
        report = reca.audit(decls, reca.FIRST_BATCH_P2L11)
        self.assertNotEqual(report["errors"], [])
        self.assertTrue(any("external_once" in e for e in report["errors"]))

    def test_wrong_total_flagged(self):
        decls = truth_decls()[:-1]  # 少 1 条
        report = reca.audit(decls, reca.FIRST_BATCH_P2L11)
        self.assertTrue(any("总量" in e or "new" in e for e in report["errors"]))

    def test_tool_without_effect_class_flagged(self):
        decls = truth_decls()
        next(d for d in decls if d["class"] == "tool" and d["name"] == "tool.new0")\
            .pop("effect_class")
        report = reca.audit(decls, reca.FIRST_BATCH_P2L11)
        self.assertTrue(any("effect_class" in e for e in report["errors"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
