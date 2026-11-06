#!/usr/bin/env python3
# =============================================================================
# bench-retire-obs-review.py 判据面扩展测试（红队 W3-C11/C13 修复件，2026-10-27）
#
# 与 test-bench-retire-obs-review.py（W3-C-14 期满终局面）互补，覆盖两条裁判缺陷：
#   W3-C13：判据①订单核验按订单记录——ledger create_order 时间判定核验单、
#           close op + state_after=Closed 终态、mes-events 四类 kind 恰集合
#           （release/start/complete/close）；目录 mtime 口径废除（事件后触碰
#           即把旧单误计新单——F5c 实证路径）。
#   W3-C11：复核面采 alarms.log + /tmp 头寸——未知 red/amber 码判负、A4L 观察
#           期内低于闸线 2252MiB 判负（W2-C18 勘误硬判据）、A7 登记预期灯不判负；
#           A0 已摘除预期灯（DEB57-A0 2026-11-02：原「已退役调度器」登记前提为假——
#           现役 factory-scheduler.py 从未退役，A0 假红系 watch 读退役根所致，判活面
#           已修复；A0 回归真实判据灯，在场即判负）；采样失败 fail-closed（不明不谎报）。
#
# 运行：python3 tools/test-bench-retire-obs-review-criteria.py（stdlib 零依赖）
# =============================================================================
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "bench-retire-obs-review.py")

spec = importlib.util.spec_from_file_location("bror", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

START_EPOCH = time.mktime(time.strptime(mod.OBS_START, "%Y-%m-%d %H:%M:%S"))
NOW = START_EPOCH + 100000
KINDS_ALL = ["release", "start", "complete", "close"]


# ---------- fixture 工厂（形态照抄 af-state/orders 实盘） ----------

def write_ledger(path, entries):
    with open(path, "w", encoding="utf-8") as fh:
        for seq, entry in enumerate(entries, 1):
            row = {"seq": seq, "ok": True}
            row.update(entry)
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def make_order(base, name, created_ms, *, closed=True, kinds=None):
    d = os.path.join(base, name)
    os.makedirs(d, exist_ok=True)
    kinds = KINDS_ALL if kinds is None else kinds
    ops = [
        {"ts_ms": created_ms, "op": "create_order", "state_after": "Created"},
        {"ts_ms": created_ms + 20, "op": "bind_line", "state_after": "Created"},
        {"ts_ms": created_ms + 40, "op": "attach_voucher", "state_after": "Created"},
        {"ts_ms": created_ms + 60, "op": "release", "state_after": "Released"},
        {"ts_ms": created_ms + 80, "op": "start", "state_after": "InProgress"},
    ]
    if "complete" in kinds:
        ops.append({"ts_ms": created_ms + 200, "op": "attach_artifact",
                    "state_after": "InProgress"})
        ops.append({"ts_ms": created_ms + 220, "op": "complete",
                    "state_after": "Completed"})
    if closed:
        ops.append({"ts_ms": created_ms + 240, "op": "close",
                    "state_after": "Closed"})
    write_ledger(os.path.join(d, "ledger.jsonl"), ops)
    with open(os.path.join(d, "mes-events.jsonl"), "w", encoding="utf-8") as fh:
        for offset, kind in enumerate(kinds):
            fh.write(json.dumps({
                "work_order_id": f"sid-{name}",
                "occurred_at": created_ms + 100 + offset,
                "event_id": f"sid-{name}:{kind}:4", "line_id": "line-A",
                "station_id": "af-order-cli", "kind": kind, "quantity": 1,
            }, ensure_ascii=False) + "\n")
    return d


def make_alarms(path, rows):
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def alarm(ts, level, code, message):
    return {"ts": ts, "level": level, "code": code, "message": message,
            "since": ts}


def iso_after(seconds):
    return time.strftime("%Y-%m-%d %H:%M:%S",
                         time.localtime(START_EPOCH + seconds))


class Sandbox:
    """沙箱：orders 目录 + alarms.log，采样面全注入（不触真实机况）。"""

    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="obsreview-crit-")
        self.orders = os.path.join(self.root, "orders")
        self.alarms = os.path.join(self.root, "alarms.log")
        os.makedirs(self.orders)

    def close(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def samplers(self, *, ch_af=4, ch_bench=0, free_mib=4000, ps=None):
        ch = {"station_id": ch_af}
        ch["line_id"] = ch_bench

        def ch_count(sql, timeout=8):
            return ch_af if "station_id" in sql else ch_bench

        return {
            "ps_hits_fn": (lambda: ps) if ps is not None else (lambda: []),
            "anolis_fn": lambda: [],
            "ch_count_fn": ch_count,
            "orders_fn": lambda: sorted(os.listdir(self.orders)),
            "orders_verify_fn": lambda names: mod.verify_orders_records(
                names, self.orders),
            "alarms_fn": lambda: mod.read_alarms(self.alarms, START_EPOCH),
            "tmp_capacity_fn": lambda: (free_mib, 7680),
        }

    def run(self, **kw):
        sampler_keys = ("ch_af", "ch_bench", "free_mib", "ps")
        sampler_kw = {k: kw.pop(k) for k in list(kw) if k in sampler_keys}
        return mod.evaluate(now_epoch=NOW,
                            **{**self.samplers(**sampler_kw), **kw})


# ---------- W3-C13：判据①按订单记录核验 ----------

def test_created_time_not_mtime_gates_verification_order():
    """起算前创建的旧单即便目录 mtime 被事后触碰刷新，也不得计入核验单。"""
    sb = Sandbox()
    try:
        old = make_order(sb.orders, "wo-old-touched",
                         int((START_EPOCH - 172800) * 1000))
        os.utime(old, (time.time(), time.time()))  # mtime 刷到当下（毒化路径）
        good = make_order(sb.orders, "wo-good", int((START_EPOCH + 60) * 1000))
        os.utime(good, (time.time(), time.time()))
        row = sb.run()
        c1 = row["criterion1_af_order_closed_mes4"]
        names = [o["name"] for o in c1["orders_created_since_start"]]
        assert names == ["wo-good"], f"核验单只认 create_order 在起算后的订单，实得 {names}"
        assert c1["achieved"] is True, json.dumps(c1, ensure_ascii=False)
        assert c1["verified_orders"] == 1
        entry = c1["orders_created_since_start"][0]
        assert entry["closed"] is True and entry["mes_kinds_ok"] is True
    finally:
        sb.close()


def test_unclosed_order_does_not_achieve():
    sb = Sandbox()
    try:
        make_order(sb.orders, "wo-new-unclosed", int((START_EPOCH + 60) * 1000),
                   closed=False)
        row = sb.run()
        c1 = row["criterion1_af_order_closed_mes4"]
        assert c1["achieved"] is False, "未到 Closed 终态不得记达成（禁止空过）"
        assert c1["orders_created_since_start"][0]["closed"] is False
    finally:
        sb.close()


def test_incomplete_mes_kinds_do_not_achieve():
    sb = Sandbox()
    try:
        make_order(sb.orders, "wo-partial-kinds",
                   int((START_EPOCH + 60) * 1000),
                   closed=True, kinds=["release", "start"])
        row = sb.run()
        c1 = row["criterion1_af_order_closed_mes4"]
        assert c1["achieved"] is False, "四类跃迁不齐不得记达成"
        assert c1["orders_created_since_start"][0]["mes_kinds_ok"] is False
    finally:
        sb.close()


def test_zero_orders_still_not_achieved():
    sb = Sandbox()
    try:
        row = sb.run()
        c1 = row["criterion1_af_order_closed_mes4"]
        assert c1["achieved"] is False, "零订单不得空过（vacuously pass 禁令）"
        assert c1["orders_created_since_start"] == []
    finally:
        sb.close()


def test_unverifiable_ledger_is_fail_closed():
    """ledger 缺失/不可读的候选单按不可核验计（不得凭目录存在记达成）。"""
    sb = Sandbox()
    try:
        os.makedirs(os.path.join(sb.orders, "wo-bare"))
        row = sb.run()
        c1 = row["criterion1_af_order_closed_mes4"]
        assert c1["achieved"] is False, "无 ledger 记录不得记达成"
        entry = c1["orders_created_since_start"][0]
        assert entry["verifiable"] is False
    finally:
        sb.close()


# ---------- W3-C11：alarms.log + /tmp 头寸入判定 ----------

def test_unexpected_red_alarm_fails_criterion():
    """red 级码在场必须判负并入台账。DEB57-A0（2026-11-02）起 A0 已摘除预期灯
    （原「已退役调度器」登记前提为假，watch 判活面已修）——A0 行回归真实判据灯，
    与未知 red 码 ch-mes-timeout 同样判负。"""
    sb = Sandbox()
    try:
        make_alarms(sb.alarms, [
            alarm(iso_after(60), "red", "A0", "调度器状态停更"),
            alarm(iso_after(3600), "red", "ch-mes-timeout",
                  "MES 查询探针失联（类别=timeout）：3s 超时"),
            alarm(iso_after(7200), "amber", "A7", "sweb.eval 镜像停滞（预期灯）"),
        ])
        row = sb.run()
        c2b = row["criterion2b_watch_lamps_and_tmp_headroom"]
        assert c2b["achieved"] is False, "未知 red 码/A0（已摘预期灯）在场必须判负"
        codes = [e["code"] for e in c2b["unexpected_alarms"]]
        assert codes == ["A0", "ch-mes-timeout"], f"异常灯点名: {codes}"
        assert "A0" not in c2b["expected_lamp_hits"], "A0 不得再登记预期灯"
        assert c2b["expected_lamp_hits"]["A7"]["count"] == 1
    finally:
        sb.close()


def test_a4l_below_gate_fails_criterion():
    """A4L 是观察期硬判据（W2-C18 勘误），低于闸线 2252MiB 的记录必须判负。"""
    sb = Sandbox()
    try:
        make_alarms(sb.alarms, [
            alarm(iso_after(3600), "amber", "A4L:tmp",
                  "本机 /tmp 可用 1522 MiB<2662MiB（usrquota 校准线，闸线 2252MiB）"),
            alarm(iso_after(7200), "amber", "A4L:tmp",
                  "本机 /tmp 可用 1812 MiB<2662MiB（usrquota 校准线，闸线 2252MiB）"),
        ])
        row = sb.run(free_mib=1794)
        c2b = row["criterion2b_watch_lamps_and_tmp_headroom"]
        assert c2b["achieved"] is False, "观察期内 A4L 低于闸线必须判负"
        assert len(c2b["a4l_below_gate_since_start"]) == 2
        assert c2b["tmp_free_mib_now"] == 1794
        assert c2b["tmp_gate_breach_now"] is True
        assert c2b["tmp_gate_mib"] == 2252
    finally:
        sb.close()


def test_clean_lamps_and_headroom_pass():
    sb = Sandbox()
    try:
        # A0 不入 clean 灯具（DEB57-A0 2026-11-02 摘除预期灯：A0 在场即判负，
        # 见 test_unexpected_red_alarm_fails_criterion）
        make_alarms(sb.alarms, [
            alarm(iso_after(3600), "amber", "A7", "sweb.eval 镜像停滞（预期灯）"),
            alarm(iso_after(7200), "amber", "A4L:tmp",
                  "本机 /tmp 可用 2400 MiB<2662MiB（usrquota 校准线，闸线 2252MiB）"),
        ])
        row = sb.run(free_mib=2400)
        c2b = row["criterion2b_watch_lamps_and_tmp_headroom"]
        assert c2b["achieved"] is True, json.dumps(c2b, ensure_ascii=False)
        assert c2b["unexpected_alarms"] == []
        assert c2b["a4l_below_gate_since_start"] == []
        assert c2b["tmp_gate_breach_now"] is False
        # 预期灯（校准线内 amber）只入台账不判负
        assert c2b["expected_lamp_hits"]["A7"]["count"] == 1
        assert "A0" not in c2b["expected_lamp_hits"], "A0 不得再登记预期灯"
    finally:
        sb.close()


def test_alarms_unreadable_is_fail_closed():
    sb = Sandbox()
    try:
        row = sb.run()  # alarms.log 不存在 → 采样面 None
        c2b = row["criterion2b_watch_lamps_and_tmp_headroom"]
        assert c2b["achieved"] is False, "告警面采样失败=不明，不得谎报达成"
        assert c2b["alarms_sampled_since_start"] is None
        assert "alarms" in row["sampling_failed_faces"]
    finally:
        sb.close()


def test_capacity_probe_failure_is_fail_closed():
    sb = Sandbox()
    try:
        make_alarms(sb.alarms, [alarm(iso_after(3600), "amber", "A7", "（预期灯）")])
        row = sb.run(tmp_capacity_fn=lambda: None)
        c2b = row["criterion2b_watch_lamps_and_tmp_headroom"]
        assert c2b["achieved"] is False, "头寸采样失败=不明，不得谎报达成"
        assert c2b["tmp_free_mib_now"] is None
        assert "tmp_capacity" in row["sampling_failed_faces"]
    finally:
        sb.close()


# ---------- 台账行契约与生产接线 ----------

def test_row_carries_verdict_and_final_contract():
    sb = Sandbox()
    try:
        make_alarms(sb.alarms, [alarm(iso_after(3600), "red", "x-new", "未知异常")])
        row = sb.run(ch_af=None)  # CH 也不可达
        assert "criterion2b_watch_lamps_and_tmp_headroom" in row
        assert row["criterion1_af_order_closed_mes4"]["achieved"] is False
        assert row["verdict"], "verdict 文案不得为空"
        assert "mes_af" in row["sampling_failed_faces"]
        # 窗口内日报前缀契约（W3-C14）不被破坏
        assert row["verdict"].startswith("观察期内")
    finally:
        sb.close()


def test_expired_final_counts_criterion2b():
    """期满终局的未达成清单必须包含 2b（异常安灯/头寸也是硬判据）。"""
    sb = Sandbox()
    try:
        make_alarms(sb.alarms, [alarm(iso_after(3600), "red", "x-new", "未知异常")])
        end = time.mktime(time.strptime(mod.OBS_END, "%Y-%m-%d %H:%M:%S"))
        row = mod.evaluate(now_epoch=end + 60, **sb.samplers())
        assert row["kind"] == "bench-retire-obs-review-final"
        assert "2b" in row["final"]["criteria_unmet"], row["final"]
        assert row["final"]["escalation_required"] is True
        assert not row["verdict"].startswith("观察期内")
    finally:
        sb.close()


def test_production_main_wires_strict_verifier():
    """生产接线钉死（源文本比对，p3_judge 手法）：main() 的 evaluate 调用必须
    显式传入严格核验器/告警/头寸采样——防注入面缺省退回弱语义。"""
    src = open(SCRIPT, encoding="utf-8").read()
    main_src = src.split("def main()", 1)[1]
    for needle in ("orders_verify_fn=", "alarms_fn=", "tmp_capacity_fn="):
        assert needle in main_src, f"main() 未接线 {needle}——生产面必须显式严格采样"
    assert "verify_orders_records" in src and "read_alarms" in src


# ---------- OBS-D4（2026-10-31）：判据面与生产真值源对齐的钉死 ----------

def test_orders_face_defaults_to_production_truth_root():
    """判据①扫描面缺省根必须是**多根**：生产真值根（anolis:/data/bench/af-p3-state/
    orders）+ 窗内实质单根（~/af-f6-order/state/orders）——收口 §附-1 所述脱节含
    两个根；只对齐一个仍留窗内实质单（复核 issue 1）。防回退到本地 af-state/orders。"""
    assert mod.PROD_ORDERS_DIR == "/data/bench/af-p3-state/orders", mod.PROD_ORDERS_DIR
    assert mod.PROD_ORDERS_HOST == "anolis", mod.PROD_ORDERS_HOST
    assert mod.LOCAL_F6_ORDERS_DIR.endswith("/af-f6-order/state/orders"), \
        mod.LOCAL_F6_ORDERS_DIR
    src = open(SCRIPT, encoding="utf-8").read()
    fn_src = src.split("def list_order_candidates", 1)[1].split("\ndef ", 1)[0]
    assert "PROD_ORDERS_DIR" in fn_src, "list_order_candidates 缺省未走生产真值根"
    assert "LOCAL_F6_ORDERS_DIR" in fn_src, "list_order_candidates 缺省未并入窗内实质单根"
    # 本地目录版仍可用（显式传目录），但缺省必须是多根
    assert "def verify_orders_records(names, orders_dir=None)" in src, \
        "verify_orders_records 缺省未改为多根"


def test_default_orders_verify_matches_default_orders_fn():
    """默认核验器必须与默认候选面**同根**（复核 issue 2：默认候选面读生产根而
    默认核验器读本地根 → 不注入核验器直接调 evaluate() 会「候选=1032 却全单
    verifiable=False → 判据① False」的 fail-closed 假阴性）。"""
    src = open(SCRIPT, encoding="utf-8").read()
    dv_src = src.split("def _default_orders_verify", 1)[1].split("\ndef ", 1)[0]
    assert "verify_orders_records_anywhere" in dv_src, \
        "默认核验器未走多根版（与默认候选面不同根）"
    # 只看代码行（剔除 docstring/注释）判「是否仍读本地 ORDERS_DIR」
    code_lines = [ln for ln in dv_src.splitlines()
                  if not ln.strip().startswith("#")
                  and "ORDERS_DIR" in ln and "旧版" not in ln and "本地" not in ln]
    assert not code_lines, f"默认核验器仍读本地 ORDERS_DIR（根错配）: {code_lines}"
    # 多根核验必须含本地 f6 根回退
    any_src = src.split("def verify_orders_records_anywhere", 1)[1].split("\ndef ", 1)[0]
    assert "LOCAL_F6_ORDERS_DIR" in any_src, "多根核验未回退本地 f6 根"


def test_production_main_wires_remote_verifier():
    """生产接线必须指向多根真值核验器（远程生产根 ∪ 本地 f6 根），且判定核心与
    本地版同源——防「只改候选面、核验仍读本地根」的半对齐。"""
    src = open(SCRIPT, encoding="utf-8").read()
    main_src = src.split("def main()", 1)[1]
    assert "orders_verify_fn=verify_orders_records_anywhere" in main_src, \
        "main() 未接线多根真值核验器"
    assert "_order_entry_parse" in src, "判定核心缺失（本地/远端须同源）"


def test_ch_window_literals_are_timezone_explicit():
    """CH 时间窗字面量必须显式声明时区（occurred_at 列为 DateTime64(3,'UTC')）——
    裸串按 UTC 解析会让 CST 窗口首 8h 事件不可见（收口 §附-0）。
    同时钉死三参形式 toDateTime64(str, scale, tz)（两参形式把 tz 当 scale 会 500）。"""
    src = open(SCRIPT, encoding="utf-8").read()
    assert "toDateTime64('{OBS_START}', 3, 'Asia/Shanghai')" in src, \
        "CH 窗口未用显式时区三参形式"
    assert "toDateTime64('{OBS_START}', 'Asia/Shanghai')" not in src, \
        "CH 窗口仍在用把 tz 当 scale 的两参形式（CH 会 HTTP 500 → 采样面 None）"


def test_remote_verifier_fail_closed_on_ssh_failure():
    """ssh 读生产根失败 → 该单 verifiable=False（fail-closed），不得记达成。"""
    row = mod._order_entry_parse("X-1", None, None)
    assert row["verifiable"] is False and row["mes_kinds_ok"] is False
    # 判定核心与本地版同源：本地版不可读 ledger → 同样 fail-closed
    d = tempfile.mkdtemp(prefix="obsd4-")
    try:
        os.makedirs(os.path.join(d, "X-1"))
        got = mod.verify_orders_records(["X-1"], d)
        assert got[0]["verifiable"] is False
    finally:
        shutil.rmtree(d, ignore_errors=True)


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {t.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001 —— 测试具任何意外都算红
            failed += 1
            print(f"ERROR {t.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
