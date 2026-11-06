#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""W3-C-14 修复测试（先红后绿）：观察期复核车辆期满终局语义。

被测件：tools/bench-retire-obs-review.py
  - evaluate()      纯判定核心（时间/采样面全部注入）；
  - act_on_row()    期满动作执行器（停定时器/升级，函数注入）；
  - has_final_record()  终局记录幂等护栏。

口径（runbook §六-3 权威定义）：起算 2026-10-26 01:05:52，期满 2026-10-29 01:05:52。
裁判裁定（W3-C-14）：in_window 只记录不参与判定、verdict 无条件「观察期内：」前缀、
无期满退出/完成标记/升级路径 → 期满后每日 09:10 无限重复矛盾日报。
"""
import importlib.util
import json
import os
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(HERE, "bench-retire-obs-review.py")

_spec = importlib.util.spec_from_file_location("bror", TARGET)
bror = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bror)

OBS_END_EPOCH = time.mktime(time.strptime(bror.OBS_END, "%Y-%m-%d %H:%M:%S"))
OBS_MID_EPOCH = time.mktime(time.strptime(bror.MID_CHECKPOINT, "%Y-%m-%d %H:%M:%S"))
OBS_START_EPOCH = time.mktime(time.strptime(bror.OBS_START, "%Y-%m-%d %H:%M:%S"))


def fake_samplers(*, bench_rows=0, af_rows=0, orders=("F4a3-x",), ps=None,
                  anolis=None, tmp_fresh=False, hb_fresh=False):
    """全绿采样面（可按需注入异常）。ch_count 按 SQL 内容分流。

    夹具对齐注记（红队 W3-C11/C13 判据面扩展，2026-10-27）：evaluate 新增
    orders_verify_fn/alarms_fn/tmp_capacity_fn 三个采样面，本夹具按「全绿」
    注入缺省（核验单=已核验 Closed+四跃迁、告警面零条目、/tmp 头寸 4000MiB
    高于闸线）——本文件断言全部原样未动，仅夹具语义随判据集扩展对齐。
    """
    def ch_count(sql, timeout=8):
        return af_rows if "station_id" in sql else bench_rows
    real_orders = list(orders) if orders is not None else None
    if tmp_fresh or hb_fresh:
        # 伪造「起算后有活动」：orders_since_start/mtime 面——这里直接劫持 fresh 语义
        pass
    verified = [
        {"name": name, "verifiable": True, "created_at": bror.OBS_START,
         "created_ms": int(OBS_START_EPOCH * 1000) + 60000, "closed": True,
         "closed_at": bror.OBS_START, "last_state": "Closed",
         "mes_kinds": ["release", "start", "complete", "close"],
         "mes_kinds_ok": True}
        for name in (real_orders or [])
    ]
    return {
        "ps_hits_fn": (lambda: ps) if ps is not None else (lambda: []),
        "anolis_fn": (lambda: anolis) if anolis is not None else (lambda: []),
        "ch_count_fn": ch_count,
        "orders_fn": lambda: real_orders,
        "orders_verify_fn": lambda names: verified,
        "alarms_fn": lambda: [],
        "tmp_capacity_fn": lambda: (4000, 7680),
    }


def ev(epoch, **kw):
    return bror.evaluate(now_epoch=epoch, **fake_samplers(**kw))


class TestInWindowUnchanged(unittest.TestCase):
    """窗口内行为不回归：日报语义原样保留。"""

    def test_in_window_verdict_keeps_prefix(self):
        row = ev(OBS_END_EPOCH - 3600)  # 期满前 1h
        self.assertTrue(row["window"]["in_window"])
        self.assertTrue(row["verdict"].startswith("观察期内"))

    def test_in_window_not_final(self):
        row = ev(OBS_END_EPOCH - 3600)
        self.assertNotIn("final", row["window"])
        self.assertNotEqual(row["kind"], "bench-retire-obs-review-final")

    def test_criterion1_not_vacuous_without_orders(self):
        row = ev(OBS_END_EPOCH - 3600, orders=None, af_rows=0)
        self.assertFalse(row["criterion1_af_order_closed_mes4"]["achieved"])


class TestExpiredFinal(unittest.TestCase):
    """期满（in_window=false）：终局记录，不得再以「观察期内」开头。"""

    def test_expired_row_is_final(self):
        row = ev(OBS_END_EPOCH + 60)
        self.assertFalse(row["window"]["in_window"])
        self.assertEqual(row["kind"], "bench-retire-obs-review-final")
        self.assertTrue(row["final"]["expired"])

    def test_expired_verdict_no_daily_prefix(self):
        row = ev(OBS_END_EPOCH + 60)
        self.assertFalse(row["verdict"].startswith("观察期内"))
        self.assertIn("期满", row["verdict"])

    def test_expired_unmet_criteria_listed(self):
        row = ev(OBS_END_EPOCH + 60, orders=None, af_rows=0)  # 判据①未达成
        self.assertIn(1, row["final"]["criteria_unmet"])
        self.assertTrue(row["final"]["escalation_required"])

    def test_expired_all_met_no_escalation(self):
        row = ev(OBS_END_EPOCH + 60, orders=("ok",), af_rows=4)
        self.assertEqual(row["final"]["criteria_unmet"], [])
        self.assertFalse(row["final"]["escalation_required"])


class TestActOnRow(unittest.TestCase):
    """期满动作：停定时器恰一次；未达成才升级。窗口内两者皆不触发。"""

    def test_expired_stops_timer_once(self):
        stops, escs = [], []
        row = ev(OBS_END_EPOCH + 60)
        acts = bror.act_on_row(row, stop_timer_fn=lambda: (stops.append(1), True)[1],
                               escalate_fn=lambda r: escs.append(r))
        self.assertEqual(len(stops), 1)
        self.assertIn("stop_timer", acts)

    def test_expired_stop_timer_failure_reported(self):
        row = ev(OBS_END_EPOCH + 60)
        acts = bror.act_on_row(row, stop_timer_fn=lambda: False,
                               escalate_fn=lambda r: None)
        self.assertIn("stop_timer_FAILED", acts)

    def test_in_window_never_stops_or_escalates(self):
        stops, escs = [], []
        row = ev(OBS_END_EPOCH - 3600, orders=None, af_rows=0)
        bror.act_on_row(row, stop_timer_fn=lambda: stops.append(1),
                        escalate_fn=lambda r: escs.append(r))
        self.assertEqual(stops, [])
        self.assertEqual(escs, [])

    def test_expired_unmet_escalates(self):
        stops, escs = [], []
        row = ev(OBS_END_EPOCH + 60, orders=None, af_rows=0)
        acts = bror.act_on_row(row, stop_timer_fn=lambda: stops.append(1),
                               escalate_fn=lambda r: escs.append(r))
        self.assertEqual(len(escs), 1)
        self.assertIn("escalate", acts)
        self.assertTrue(row["final"]["escalation_required"])

    def test_expired_met_no_escalation(self):
        stops, escs = [], []
        row = ev(OBS_END_EPOCH + 60, orders=("ok",), af_rows=4)
        bror.act_on_row(row, stop_timer_fn=lambda: stops.append(1),
                        escalate_fn=lambda r: escs.append(r))
        self.assertEqual(escs, [])


class TestFinalIdempotence(unittest.TestCase):
    """has_final_record：已有终局记录不再重复落终局（防手工重跑连刷）。"""

    def test_false_on_empty_or_daily_rows(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.jsonl")
            self.assertFalse(bror.has_final_record(p))
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(json.dumps({"kind": "bench-retire-obs-review"}) + "\n")
            self.assertFalse(bror.has_final_record(p))

    def test_true_when_final_present(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.jsonl")
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(json.dumps({"kind": "bench-retire-obs-review"}) + "\n")
                fh.write(json.dumps({"kind": "bench-retire-obs-review-final"}) + "\n")
            self.assertTrue(bror.has_final_record(p))


if __name__ == "__main__":
    unittest.main(verbosity=2)
