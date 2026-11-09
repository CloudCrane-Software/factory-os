#!/usr/bin/env python3
"""test-quota-gate-criteria-parity.py — 配额闸派发侧↔执行侧判据对账门（2026-11-03）

背景（RT 确证发现，非推演）：同一份 状态观测/quota.json 在两侧得出相反裁决——
  ① 派发侧：tools/quota-governor.py 的 HOLD_FLOOR_PCT/WEEKLY_HOLD_FLOOR_PCT（修复前
     8.0/8.0）→ minimax.go；调度器 tools/factory-scheduler.py 按 go 写 mm 条目。
  ② 执行侧：tools/factory-status-push.py 下发 gate.json 的 mm_ok（修复前就地硬编码
     15%/20%）；执行方 tools/burn-runner.py 按 mm_ok 逐条收/拒（拒收者留队待闸开）。
  两套阈值各判各的 → 分歧带 5h∈(8,15] ∪ wk∈(8,20] 内派发侧 go=true（写单）而执行侧
  mm_ok=false（拒单留队）→ 队列积压不可执行条目。映射盲区：全仓无一处对账两侧口径。

本门在沙箱内**实跑生产代码路径**对账（不联网、不触在役件）：
  A 单一事实源：执行侧用的闸阈常量 == 派发侧 quota-governor.py 的同名常量（两侧不得
    各立一套阈值；执行侧就地硬编码 → 红）。
  B 判据同源 + 全网格恒等：桩掉网络后跑**真实** quota-governor.poll()（产出真实
    quota.json），把该文件的 minimax 段分别喂给「派发侧裁决」（= 文件里的 go，调度器
    read_quota 取的就是它）与「执行侧裁决」（= mm_gate_ok(同段)）→ 全网格必须恒等，
    分歧点数必须为 0。
  C 旧分歧带清零：修复前分歧带内的网格点，两侧裁决恒等（带内不再有「派发说行、执行说
    不行」的点）。
  D 负控（判别力自证）：把修复前两套口径（派发 8/8、执行 15/20）写成夹具跑同一网格
    → 必须**确实分歧**（分歧点数 > 0，且见证点 5h=10%/wk=62% 在其中）。否则本门无判别
    力（夹具写错/网格写错）→ 红。这条保证「绿灯」不是因为门瞎了。
  E 执行侧 fail-closed：{无 go 键 / go=false / 缺 pct / pct 非法 / 闸阈取不到} 五种
    情形恒不放行。
  F 派发侧确为「按 go 派发」：加载真实 factory-scheduler.py，read_quota() 取到的 mm_go
    == quota.json 的 go；且 minimax_round 在 go=true 时产出 mm 动作（干跑态，不触网/
    不落单）、在 go=false 时不产出任何动作。
  G 闸面唯一性（死码防复生，2026-11-03 RT 确证发现加段）：治理器 tools/quota-governor.py
    此前另有两道**输出面**——/tmp/quota-gate/mavis-hold 闸文件与 /tmp/quota-gate/step-slots/
    的 8 个 flock 咨询槽位：全仓零消费者（无任何执行面代码读取闸文件或持槽锁），8 槽自
    2026-10-29 建槽起从未被任何进程 acquire/release（逐槽 flock -n 探针 8/8 FREE），
    且真实 step 生产者跑在 anolis（flock 不跨机）→ 本地槽位结构上也不可能被真实生产者
    持锁。故治理器 docstring 承诺的「配额闸」与「8 槽占用态」实际不生效。本段钉住：
    G1 在役治理器不得再暴露死面属性（GATE_DIR/STEP_SLOT_DIR/STEP_SLOTS/slots/apply_gates）；
    G2 在役治理器可执行码不得含任何死面路径字面量（含 /tmp；docstring 记载下线史不算
       产出死面的码）；
    G3 真闸面未弱化：真跑在役治理器的 poll()（桩网络 + 沙箱 STATE）仍产出唯一落盘面
       quota.json（step+minimax 段齐、minimax.go 随闸阈翻转）；
    G4 CLI 面：slots 子命令已下线（未知命令 → exit 2）、gates 子命令仍在且输出不再带
       死面字段 mavis_hold_file；
    G5 「8 槽占用态」真相归属调度器的 anolis 进程计数探针（scheduler 源码含该探针、
       且不引用死面路径）；
    G6 负控（判别力自证）：修前快照（tools/quota-governor.py.20261031-pre-RT-quotagate-dead.bak）
       必须**违反** G1/G2/G4 的判据（死面属性在、可执行码含死面字面量、slots 子命令活着）
       ——否则本段无判别力（判据写错/夹具写错）→ 红。

可选参数：argv[1]=执行侧被测件路径（默认 tools/factory-status-push.py）、
          argv[2]=派发侧被测件路径（默认 tools/quota-governor.py）。
          指 .bak 可复演修复前红（修复前执行侧无 mm_gate_ok → 本门即红）。
          G 段固定测**在役件**（tools/quota-governor.py）与修前快照（负控），不随 argv 变。
退出码 0=全过；任一断言红即非零退出并点名断言。"""
import ast
import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
from importlib.machinery import SourceFileLoader

_TOOLS = os.path.dirname(os.path.abspath(__file__))
_EXEC_UNDER = sys.argv[1] if len(sys.argv) > 1 else os.path.join(_TOOLS, "factory-status-push.py")
_GOV_UNDER = sys.argv[2] if len(sys.argv) > 2 else os.path.join(_TOOLS, "quota-governor.py")
_SCHED_UNDER = os.path.join(_TOOLS, "factory-scheduler.py")
# G 段固定件：在役治理器（闸面唯一性正控）+ 修前快照（负控，见 G6）
_GOV_SHIPPED = os.path.join(_TOOLS, "quota-governor.py")
_GOV_PRE_FIX = os.path.join(_TOOLS, "quota-governor.py.20261031-pre-RT-quotagate-dead.bak")
# 死面属性/标记：闸文件与 8 槽 flock 面已下线，治理器不得再写 /tmp 任何位置
_DEAD_ATTRS = ("GATE_DIR", "STEP_SLOT_DIR", "STEP_SLOTS", "slots", "apply_gates")
_DEAD_MARKERS = ("mavis-hold", "step-slots", "quota-gate", "/tmp")

# 网格：5h/周池读数（%）。含阈下/阈上/阈位/阈邻/实测常见读数。
_P5 = [0, 1, 7, 8, 8.1, 9, 10, 12, 14, 14.9, 15, 15.1, 16, 20, 30, 49, 62, 83, 99, 100]
_PWK = [0, 1, 5, 8, 8.1, 9, 10, 15, 19, 19.9, 20, 20.1, 21, 30, 49, 62, 83, 99, 100]


def fail(msg):
    print(f"FAIL {msg}", flush=True)
    sys.exit(1)


def _load(path, name):
    # SourceFileLoader 显式指定：argv 可指 .bak 等非 .py 后缀件（复演修复前红）
    loader = SourceFileLoader(name, path)
    spec = importlib.util.spec_from_file_location(name, path, loader=loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def _pre_fix_dispatch_go(p5, pwk):
    """修复前派发侧口径（夹具）：quota-governor 8.0/8.0。"""
    return p5 > 8.0 and pwk > 8.0


def _pre_fix_exec_ok(mq):
    """修复前执行侧口径（夹具）：status-push 就地硬编码 15/20 且并 go。"""
    return ((mq.get("five_hour_remaining_pct") or 0) > 15
            and (mq.get("weekly_remaining_pct") or 0) > 20
            and bool(mq.get("go")))


# ---- G 段判据（G1/G2/G4 共用；G6 负控复用同一判据，证明其有判别力）----

def _dead_surface_attrs(mod):
    """在役治理器上仍暴露的死面属性名（闸目录/槽目录常量 + 死写者/死读出器）。"""
    return [a for a in _DEAD_ATTRS if hasattr(mod, a)]


def _dead_surface_literals(path):
    """源码里（**排除 docstring**）出现死面路径字面量的位置：[(行号, 标记), ...]。

    docstring 是文档——记载「某面已下线」的说明不算产出死面的码；注释不是 AST 节点、
    本就不计。故只扫可执行码里的字符串常量。
    """
    with open(path, encoding="utf-8") as f:
        src = f.read()
    tree = ast.parse(src)
    doc_ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", None)
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                doc_ids.add(id(body[0].value))
    hits = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in doc_ids):
            for m in _DEAD_MARKERS:
                if m in node.value:
                    hits.append((node.lineno, m))
    return hits


def _run_cli(mod, cmd, argv_state=None):
    """跑在役治理件的 main() 子命令，返回 (rc, stdout 文本)。

    真实调用 main()（不是文本匹配）——子命令是否还在、退出码多少，均由实跑得出。
    argv_state：临时把 sys.argv 换掉；返回后原样恢复。
    """
    old_argv = sys.argv
    buf = io.StringIO()
    rc = 0
    try:
        sys.argv = ["quota-governor.py", cmd]
        with contextlib.redirect_stdout(buf):
            try:
                mod.main()
            except SystemExit as e:
                rc = int(e.code or 0)
    finally:
        sys.argv = old_argv
    return rc, buf.getvalue()


def main():
    # ---- 加载被测件 ----
    try:
        gov = _load(_GOV_UNDER, "quota_governor_under_test")
    except Exception as e:  # noqa: BLE001
        fail(f"派发侧件加载失败 {_GOV_UNDER}: {type(e).__name__}: {e}")
    try:
        fsp = _load(_EXEC_UNDER, "factory_status_push_under_test")
    except Exception as e:  # noqa: BLE001
        fail(f"执行侧件加载失败 {_EXEC_UNDER}: {type(e).__name__}: {e}")
    for attr in ("HOLD_FLOOR_PCT", "WEEKLY_HOLD_FLOOR_PCT", "poll"):
        if not hasattr(gov, attr):
            fail(f"派发侧件缺 {attr}（{_GOV_UNDER}）——判据不可测")
    if not hasattr(fsp, "mm_gate_ok"):
        fail(f"执行侧件缺 mm_gate_ok（{_EXEC_UNDER}）——执行侧判据不可测"
             "（修复前版本把 15/20 就地硬编码在 main() 里，无法与派发侧对账）")
    if not hasattr(fsp, "MM_HOLD_FLOOR_PCT") or not hasattr(fsp, "MM_WEEKLY_HOLD_FLOOR_PCT"):
        fail(f"执行侧件缺 MM_HOLD_FLOOR_PCT/MM_WEEKLY_HOLD_FLOOR_PCT（{_EXEC_UNDER}）"
             "——执行侧闸阈须从派发侧取，不得就地硬编码")

    # ---- A 单一事实源：两侧闸阈常量必须同一 ----
    if float(fsp.MM_HOLD_FLOOR_PCT) != float(gov.HOLD_FLOOR_PCT):
        fail(f"A1 执行侧 5h 闸阈 {fsp.MM_HOLD_FLOOR_PCT} ≠ 派发侧 {gov.HOLD_FLOOR_PCT}"
             "（两侧各立一套阈值 → 同一份 quota.json 可能得出相反裁决）")
    if float(fsp.MM_WEEKLY_HOLD_FLOOR_PCT) != float(gov.WEEKLY_HOLD_FLOOR_PCT):
        fail(f"A2 执行侧周池闸阈 {fsp.MM_WEEKLY_HOLD_FLOOR_PCT} ≠ 派发侧 {gov.WEEKLY_HOLD_FLOOR_PCT}"
             "（两侧各立一套阈值 → 同一份 quota.json 可能得出相反裁决）")

    with tempfile.TemporaryDirectory(prefix="quotagate-parity.") as td:
        state_path = os.path.join(td, "quota.json")
        gov.STATE = state_path
        # 2026-11-03：闸文件面/8 槽 flock 面已下线（零消费者死码，G 段有门钉住），
        # GATE_DIR/STEP_SLOT_DIR 在在役件上已不存在——此处两行保留为**兜底重定向**：
        # 若有人日后把死面加回来，被测件写的是沙箱路径而非真 /tmp，G 段仍能红。
        gov.GATE_DIR = os.path.join(td, "quota-gate")
        gov.STEP_SLOT_DIR = os.path.join(td, "quota-gate", "step-slots")

        def stub_curl(url, bearer):
            if url == gov.STEP_USAGE_URL:
                return {"plan": {"subscription": {"expires_at_ms": 1}},
                        "quota": {"credit_buckets": [{"remaining": 1, "total": 2, "used_percent": 50}]}}
            return {"model_remains": [{"model_name": "general", "end_time": int(time_ms()) + 3600_000,
                                       "current_interval_remaining_percent": _CUR[0],
                                       "current_weekly_remaining_percent": _CUR[1]}]}

        def time_ms():
            import time
            return int(time.time() * 1000)

        gov._curl_json = stub_curl
        gov.minimax_token = lambda: "mmoat-stub"
        gov.step_key = lambda: "step-stub"

        # ---- B 全网格：真实 poll() 产出的 quota.json，两侧裁决必须恒等 ----
        _CUR = [0, 0]
        divergent, old_band_divergent, samples = [], [], []
        for p5 in _P5:
            for pwk in _PWK:
                _CUR[0], _CUR[1] = p5, pwk
                gov.poll()
                qj = json.load(open(state_path, encoding="utf-8"))
                mm = qj.get("minimax") or {}
                dispatch_go = bool(mm.get("go"))          # 派发侧裁决（调度器 read_quota 取的就是它）
                exec_ok = bool(fsp.mm_gate_ok(mm))        # 执行侧裁决（burn-runner 按 mm_ok 收/拒）
                if dispatch_go != exec_ok:
                    divergent.append((p5, pwk, dispatch_go, exec_ok))
                # 旧分歧带（修复前 8/8 vs 15/20 的差集）：此刻必须已清零
                if _pre_fix_dispatch_go(p5, pwk) != _pre_fix_exec_ok(mm):
                    if dispatch_go != exec_ok:
                        old_band_divergent.append((p5, pwk))
                samples.append((p5, pwk, dispatch_go, exec_ok))
        if divergent:
            fail(f"B 全网格两侧裁决分歧 {len(divergent)} 点（示例 {divergent[:3]}）"
                 "——同一份 quota.json 在派发侧与执行侧得出相反裁决（队列积压不可执行条目）")
        if old_band_divergent:
            fail(f"C 旧分歧带（5h∈(8,15] ∪ wk∈(8,20]）内仍有分歧点 {old_band_divergent[:3]}")
        if len(samples) != len(_P5) * len(_PWK):
            fail(f"B 网格点数异常 {len(samples)}")

        # ---- D 负控：修复前口径在同一网格上必须确实分歧（本门有判别力）----
        pre_div = []
        for p5 in _P5:
            for pwk in _PWK:
                mm = {"five_hour_remaining_pct": p5, "weekly_remaining_pct": pwk,
                      "go": _pre_fix_dispatch_go(p5, pwk)}
                if _pre_fix_dispatch_go(p5, pwk) != _pre_fix_exec_ok(mm):
                    pre_div.append((p5, pwk))
        if not pre_div:
            fail("D 负控失效：修复前口径（派发 8/8 vs 执行 15/20）在本网格上竟无分歧点"
                 "——网格/夹具写错，本门当前绿灯无判别力")
        witness = (10, 62)   # 现场见证点：2026-11-02 23:52 实况（5h=10%、wk=62%）
        if witness not in [d[:2] for d in pre_div]:
            fail(f"D 负控失效：现场见证点 {witness} 不在修复前分歧点集内"
                 f"（实际分歧点集前 5：{pre_div[:5]}）")

        # ---- E 执行侧 fail-closed ----
        good = {"go": True, "five_hour_remaining_pct": 99, "weekly_remaining_pct": 99}
        if not fsp.mm_gate_ok(good):
            fail("E0 健康读数（go=true, 5h=99%, wk=99%）应放行")
        if fsp.mm_gate_ok({}):
            fail("E1 空段（无 go 无 pct）应 fail-closed 拒放行")
        if fsp.mm_gate_ok({"go": False, "five_hour_remaining_pct": 99, "weekly_remaining_pct": 99}):
            fail("E2 go=false 应 fail-closed 拒放行")
        if fsp.mm_gate_ok({"go": True}):
            fail("E3 缺 pct 应 fail-closed 拒放行")
        if fsp.mm_gate_ok({"go": True, "five_hour_remaining_pct": "abc", "weekly_remaining_pct": 99}):
            fail("E4 非法 pct 应 fail-closed 拒放行")
        _saved = (fsp.MM_HOLD_FLOOR_PCT, fsp.MM_WEEKLY_HOLD_FLOOR_PCT)
        try:
            fsp.MM_HOLD_FLOOR_PCT, fsp.MM_WEEKLY_HOLD_FLOOR_PCT = None, None
            if fsp.mm_gate_ok(good):
                fail("E5 闸阈取不到（闸阈缺失）应 fail-closed 拒放行")
        finally:
            fsp.MM_HOLD_FLOOR_PCT, fsp.MM_WEEKLY_HOLD_FLOOR_PCT = _saved

        # ---- F 派发侧确为「按 quota.json 的 go 派发」 ----
        try:
            fsched = _load(_SCHED_UNDER, "factory_scheduler_under_test")
        except Exception as e:  # noqa: BLE001
            fail(f"调度件加载失败 {_SCHED_UNDER}: {type(e).__name__}: {e}")
        fsched.QUOTA = state_path
        fsched.LOG = os.path.join(td, "scheduler.log")
        fsched.CHANGELOG = os.path.join(td, "changelog.md")
        fsched._DRY[0] = True
        _CUR[0], _CUR[1] = 83, 49
        gov.poll()
        q = fsched.read_quota()
        qj = json.load(open(state_path, encoding="utf-8"))
        if bool(q.get("mm_go")) != bool((qj.get("minimax") or {}).get("go")):
            fail(f"F1 调度侧 mm_go={q.get('mm_go')} ≠ quota.json 的 go="
                 f"{(qj.get('minimax') or {}).get('go')}（派发侧裁决取的不是同一个键）")
        if q.get("stale"):
            fail("F2 刚产出的 quota.json 不应被判过期")
        d_true = {"error": "", "quota": {"stale": False, "mm_go": True, "mm_err": None,
                                         "mm_5h": 83, "mm_wk": 49, "note": ""},
                  "step_inflight": 8, "mm_count": 0, "pool": ["t-parity"],
                  "pending_tasks": ["t-parity"], "mm_tasks": []}
        d_false = dict(d_true, quota=dict(d_true["quota"], mm_go=False))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            acts_true = fsched.minimax_round({"minimax": {}}, d_true)
            acts_false = fsched.minimax_round({"minimax": {}}, d_false)
        if not acts_true:
            fail("F3 go=true 时调度侧应产出 mm 动作（派发口径未按 go 走）")
        if acts_false:
            fail(f"F4 go=false 时调度侧不应产出 mm 动作，实产 {acts_false}")

        # ---- G 闸面唯一性（死码防复生）：真闸只有一个面，死面不得复生 ----
        # 背景见文首 G 段：治理器此前的 mavis 闸文件面与 8 槽 flock 面全仓零消费者、
        # 8 槽从未被任何进程持锁 → docstring 承诺的「配额闸」「8 槽占用态」不生效。
        # 本段钉住：①死面不再存在；②真闸面（quota.json 布尔位）未弱化；③「8 槽占用态」
        # 的真实现归属调度器的 anolis 进程计数探针；④负控证明判据有判别力。
        try:
            ship = _load(_GOV_SHIPPED, "quota_governor_shipped")
        except Exception as e:  # noqa: BLE001
            fail(f"G0 在役治理器加载失败 {_GOV_SHIPPED}: {type(e).__name__}: {e}")

        # G1 在役治理器不得再暴露死面属性
        dead_attrs = _dead_surface_attrs(ship)
        if dead_attrs:
            fail(f"G1 在役治理器仍暴露死面属性 {dead_attrs}（mavis 闸文件面与 8 槽 flock 面"
                 "已下线——零消费者死码不得复生；真闸 = 状态观测/quota.json 的 minimax.go，"
                 "8 槽占用态 = 调度器 anolis 进程计数探针）")

        # G2 在役治理器可执行码不得含死面路径字面量（含 /tmp：不得再写 /tmp 任何位置）
        hits = _dead_surface_literals(_GOV_SHIPPED)
        if hits:
            fail(f"G2 在役治理器可执行码仍含死面路径字面量 {hits[:3]}（mavis 闸文件面/"
                 "8 槽 flock 面不得复生；docstring 记载下线史不算，可执行码算）")

        # G3 真闸面未弱化：真跑在役治理器的 poll()（桩网络 + 沙箱 STATE）→ 唯一落盘面
        #    quota.json 仍产出、段齐、minimax.go 随闸阈翻转（真闸面活着而非被删）。
        g_state = os.path.join(td, "g_ship_quota.json")
        ship.STATE = g_state
        ship._curl_json = stub_curl
        ship.minimax_token = lambda: "mmoat-stub"
        ship.step_key = lambda: "step-stub"
        _CUR[0], _CUR[1] = 7, 3          # 闸阈下 → minimax.go 必须 false
        ship.poll()
        if not os.path.exists(g_state):
            fail("G3a 在役治理器 poll() 未产出状态面 quota.json（唯一落盘面被删）")
        gj = json.load(open(g_state, encoding="utf-8"))
        if "step" not in gj or "minimax" not in gj:
            fail(f"G3b 在役治理器产出的 quota.json 缺段（实得键 {sorted(gj)}）")
        if gj["minimax"].get("go") is not False:
            fail(f"G3c 闸阈下（5h=7%/周=3%）minimax.go 应为 false，实得 "
                 f"{gj['minimax'].get('go')}（闸面被弱化）")
        _CUR[0], _CUR[1] = 83, 49        # 闸阈上 → minimax.go 必须 true
        ship.poll()
        gj2 = json.load(open(g_state, encoding="utf-8"))
        if gj2["minimax"].get("go") is not True:
            fail(f"G3d 闸阈上（5h=83%/周=49%）minimax.go 应为 true，实得 "
                 f"{gj2['minimax'].get('go')}（闸面被弱化）")

        # G4 CLI 面：slots 子命令已下线（未知命令 → exit 2）；gates 子命令仍在、输出不再
        #    带死面字段 mavis_hold_file，且仍给出真闸姿态键。
        rc_slots, out_slots = _run_cli(ship, "slots")
        if rc_slots == 0:
            fail(f"G4a 在役治理器仍接受 slots 子命令（死面未下线）——实跑输出 {out_slots[:120]}")
        rc_gates, out_gates = _run_cli(ship, "gates")
        if rc_gates != 0:
            fail(f"G4b gates 子命令实跑退出码 {rc_gates}（应 0）")
        try:
            gj_out = json.loads(out_gates)
        except Exception as e:  # noqa: BLE001
            fail(f"G4c gates 子命令输出非 JSON（{type(e).__name__}: {e}）：{out_gates[:120]}")
        if "mavis_hold_file" in gj_out:
            fail("G4d gates 输出仍带死面字段 mavis_hold_file（闸文件面不得复生）")
        for k in ("step_go", "minimax_go"):
            if k not in gj_out:
                fail(f"G4e gates 输出缺真闸姿态键 {k}（实得键 {sorted(gj_out)}）")

        # G5 「8 槽占用态」真相归属调度器的 anolis 进程计数探针（真实 step 生产者在
        #    anolis，本地 flock 槽位结构上不可能被其持锁）。
        with open(_SCHED_UNDER, encoding="utf-8") as f:
            sched_src = f.read()
        if 'pgrep -fc "af-orde[r].*step-5"' not in sched_src:
            fail("G5a 调度器缺 anolis step 在途探针（pgrep -fc 'af-orde[r].*step-5'）——"
                 "「8 槽占用态」的真实现归此探针，缺了则闸无判据")
        for m in ("mavis-hold", "step-slots", "quota-gate"):
            if m in sched_src:
                fail(f"G5b 调度器源码仍引用死面 {m}（调度侧不得依赖零消费者的本地闸/槽面）")

        # G6 负控（判别力自证）：修前快照必须违反 G1/G2/G4 的判据——否则本段是瞎的。
        # 件位解析改读登记册（D-157/ESC-19；登记册全文头注与解析门 docstring 为
        # 权威说明：tools/negative-controls.list + tools/negative-control-recon-gate.py。
        # 形制注记：本块以上区域对 2026-11-06 脱敏裁决钉桩（mirror-scan-allowlist
        # 行钉 L210/L335）零行移——改动全部收在本块内，判官面行钉不漂）。
        # 只许变严：旧判据=tools/ 具名件缺席即红；新增红面=册缺失/册不可解析/册无
        # 该条目/任一现势位 sha256 失配；唯一新增绿面=在役位缺席而登记归档位在场且
        # sha256 对账一致（ESC-19 正解：负控件被归档≠判别力丢失）。
        ncrg = _load(os.path.join(_TOOLS, "negative-control-recon-gate.py"),
                     "negative_control_recon_gate")
        neg_list = os.path.join(_TOOLS, "negative-controls.list")
        neg_name = "quota-governor.py.20261031-pre-RT-quotagate-dead.bak"
        try:
            neg_reg = ncrg.load_register(neg_list)
        except ncrg.RegisterError as e:
            fail(f"G6 负控件登记册不可证：{e}（fail-closed——判据只许变严，不因册缺而放行）")
        neg_entry = next((e for e in neg_reg if e["name"] == neg_name), None)
        if neg_entry is None:
            fail(f"G6 负控件 {neg_name} 不在登记册 {neg_list}（册内 {len(neg_reg)} 条"
                 "皆非本夹具依赖件——归档改名须同批更册，ESC-19 归档面规矩）")
        neg_res = ncrg.resolve_entry(neg_entry, os.path.dirname(_TOOLS),
                                     ncrg.ws_root_candidates(os.path.dirname(_TOOLS)))
        if neg_res["verdict"] == "FOUND":
            _GOV_PRE_FIX = neg_res["path"]
        else:
            fail(f"G6 负控件缺席点名：{neg_res['detail']}（闸面唯一性段失去判别力自证）")
        try:
            pre = _load(_GOV_PRE_FIX, "quota_governor_pre_fix")
        except Exception as e:  # noqa: BLE001
            fail(f"G6 负控件加载失败 {_GOV_PRE_FIX}: {type(e).__name__}: {e}")
        pre_attrs = _dead_surface_attrs(pre)
        pre_hits = _dead_surface_literals(_GOV_PRE_FIX)
        # 负控件的 slots 子命令必须「活着」（rc=0）——实跑，不读源码。
        # 槽目录重定向到沙箱不存在路径：glob 空集，不会在真 /tmp 重建死面。
        pre.STEP_SLOT_DIR = os.path.join(td, "pre_fix_absent_slots")
        rc_pre_slots, _ = _run_cli(pre, "slots")
        if not pre_attrs:
            fail("G6a 负控失效：修前快照竟无死面属性（G1 判据写错/夹具写错）")
        if not pre_hits:
            fail("G6b 负控失效：修前快照可执行码竟无死面字面量（G2 判据写错/夹具写错）")
        if rc_pre_slots != 0:
            fail(f"G6c 负控失效：修前快照的 slots 子命令实跑退出码 {rc_pre_slots}"
                 "（应 0＝修前该子命令活着，G4 判据无判别力）")

    # ---- S step 腿（D-145 / ESC-20；判据=宪章 SCH-3 R-10②③④）判定同源化对账 ----
    # 背景（红队双镜头 verified，与 11-03 minimax「8/8 vs 15/20」同型复发换到 step 道）：
    #   派发侧吃 quota.json 的 step.go（quota-governor.py:250，expires>now ∧ remaining>0
    #   即真）；执行侧自算 step_ok（修前 factory-status-push.py:134 就地硬编码
    #   到期>3600s ∧ remaining>2e8）——分歧带（0<remaining≤2e8 或到期≤3600s）内派发
    #   照写 step 条目、执行逐条拒收留队 → 队列积压不可执行条目；且 2e8/3600 是
    #   REG-3 数字清单之外的无登记正本配额数（第十、十一个）。
    # 修法（D-145，只许变严）：step 双阈唯一机读正本=账本/resource-rules.jsonl 的
    #   step 规则声明行（af.resource-rule.v1；REG-3 step pair 全归属）；执行侧
    #   step_gate_ok 只引不持（禁自持 2e8/3600）；两侧同取注册表值（R-10② 等价
    #   形态：「import 同一定价函数或同取注册表值」）；派发侧方向=升阈对齐注册表
    #   双阈（禁反向放宽，宪章 :172——「统一到 remaining>0」属放宽，禁走）。
    # 形制注记：本段整体插在 G 段之后（全部行号>L335）——上方 L1-335 与钉桩基线
    #   逐字节一致，mirror-scan-allowlist 行钉 L210/L335 零移（D-157 同形制）。
    # S0 执行侧件形制：step_gate_ok 与注册表双阈常量必须在场（修前快照指为本门
    #     argv[1] 即在此红——修前内联硬编码无从对账，防死码复生）。
    if not hasattr(fsp, "step_gate_ok"):
        fail(f"S0 执行侧件缺 step_gate_ok（{_EXEC_UNDER}）——step 腿判据不可测"
             "（修前版本把 2e8/3600 内联硬编码在 derive_gate 里，无从与派发侧对账；"
             "D-145：执行侧禁自持双阈，改从注册表取）")
    if (not hasattr(fsp, "STEP_REMAINING_FLOOR")
            or not hasattr(fsp, "STEP_SECONDS_TO_EXPIRY_FLOOR_S")):
        fail("S0 执行侧件缺 STEP_REMAINING_FLOOR/STEP_SECONDS_TO_EXPIRY_FLOOR_S"
             f"（{_EXEC_UNDER}）——step 双阈须从注册表声明行取，不得就地自持")

    # S1 单一事实源（同取注册表值）：本门自读注册表与执行侧所持双阈对账；
    #     只许变严：注册表取值禁低于修前执行侧自持值（禁反向放宽，宪章 :172）。
    try:
        _step_rule = _load_step_rule(_REGISTRY)
    except _RuleError as e:
        fail(f"S1 注册表不可证：{e}（step 双阈唯一机读正本=账本/resource-rules.jsonl"
             " 声明行——R-10④ 登记；缺席/坏行/歧义即红，不猜绿）")
    _reg_rem, _reg_exp = _step_rule
    if fsp.STEP_REMAINING_FLOOR is None or fsp.STEP_SECONDS_TO_EXPIRY_FLOOR_S is None:
        fail(f"S1 执行侧双阈取不到 ({fsp.STEP_REMAINING_FLOOR}, "
             f"{fsp.STEP_SECONDS_TO_EXPIRY_FLOOR_S})——注册表在而执行侧没取到"
             "（loader 破缺或被指到别处；fail-closed 不猜绿）")
    if (float(fsp.STEP_REMAINING_FLOOR), float(fsp.STEP_SECONDS_TO_EXPIRY_FLOOR_S)) \
            != (_reg_rem, _reg_exp):
        fail(f"S1 执行侧所持双阈 ({fsp.STEP_REMAINING_FLOOR}, "
             f"{fsp.STEP_SECONDS_TO_EXPIRY_FLOOR_S}) ≠ 注册表声明值 "
             f"({_reg_rem}, {_reg_exp})——两侧未同取注册表值（同源破缺：同一份读数"
             "可能再次得出相反裁决）")
    if _reg_rem < _PRE_STEP_REM_FLOOR or _reg_exp < _PRE_STEP_EXP_FLOOR:
        fail(f"S1 注册表双阈 ({_reg_rem}, {_reg_exp}) 低于修前执行侧自持值 "
             f"({_PRE_STEP_REM_FLOOR}, {_PRE_STEP_EXP_FLOOR})——只许变严护栏"
             "（宪章 :172：无「旧判据曾拦住什么」反例实证的放宽一律驳回）")

    # S2 全网格恒等（同取注册表值）：派发侧腿与执行侧腿分别按注册表双阈裁决同一
    #     读数网格，必须逐点恒等；且统一阈恒紧于修前派发侧口径（rem>0∧exp>0）——
    #     派发侧升阈是收紧不是放宽。
    _s_div, _s_loosen, _s_n = [], [], 0
    for _rem in _S_REM:
        for _exp in _S_EXP:
            _disp = _rem > _reg_rem and _exp > _reg_exp
            _exec = bool(fsp.step_gate_ok({"remaining": _rem, "seconds_to_expiry": _exp}))
            if _disp != _exec:
                _s_div.append((_rem, _exp, _disp, _exec))
            if _disp and not _pre_fix_step_dispatch_go(_rem, _exp):
                _s_loosen.append((_rem, _exp))
            _s_n += 1
    if _s_div:
        fail(f"S2 step 腿全网格两侧裁决分歧 {len(_s_div)} 点（示例 {_s_div[:3]}）——"
             "同一份读数在派发侧与执行侧得出相反裁决（D-145 复发）")
    if _s_loosen:
        fail(f"S2 统一阈在 {len(_s_loosen)} 点上竟宽于修前派发侧口径(rem>0∧未到期)"
             f"（示例 {_s_loosen[:3]}）——只许变严被破")
    if _s_n != len(_S_REM) * len(_S_EXP):
        fail(f"S2 网格点数异常 {_s_n}")

    # S3 分歧带负例（R-10③）：修前分歧带见证点（含卡面点名 remaining=1e8/到期
    #     1800s）统一阈下两侧必须同判（同为 false；活读见证点同判 true）。
    for _rem, _exp, _want in _S_WITNESSES:
        _disp = _rem > _reg_rem and _exp > _reg_exp
        _exec = bool(fsp.step_gate_ok({"remaining": _rem, "seconds_to_expiry": _exp}))
        if _disp != _exec or _exec != _want:
            fail(f"S3 分歧带负例（remaining={_rem:g}/到期={_exp:g}s）两侧必须同判且"
                 f"统一阈下应为 {_want}，实得 派发={_disp}/执行={_exec}"
                 "（分歧带内不得再有「派发照写/执行拒收」）")

    # S4 负控（判别力自证，R-10③「修前快照在本夹具必红」）：把修前两套口径写成
    #     夹具跑同一网格——必须确实分歧且分歧向=派发 true/执行 false（D-145 病理
    #     本体）。否则本段无判别力（夹具/网格写错，当前绿灯是瞎的）→ 红。
    _s_pre_div = [(_rem, _exp) for _rem in _S_REM for _exp in _S_EXP
                  if _pre_fix_step_dispatch_go(_rem, _exp) != _pre_fix_step_exec_ok(_rem, _exp)]
    if not _s_pre_div:
        fail("S4 负控失效：修前口径（派发 rem>0∧未到期 vs 执行 >3600s∧>2e8）在本网格"
             "上竟无分歧点——网格/夹具写错，本段当前绿灯无判别力")
    for _rem, _exp, _want in _S_WITNESSES[:3]:
        if _want or (_rem, _exp) not in _s_pre_div:
            fail(f"S4 负控失效：分歧带见证点 ({_rem:g}, {_exp:g}) 不在修前分歧点集内"
                 f"（修前分歧 {len(_s_pre_div)} 点，前 5：{_s_pre_div[:5]}）")

    # S5 执行侧 fail-closed＋禁自持（REG-3：数字清单在消费方码内零硬编码）＋接线完好。
    _healthy = {"remaining": 5_670_000_000, "seconds_to_expiry": 100_400}
    if not fsp.step_gate_ok(_healthy):
        fail("S5a 健康读数（remaining=5.67e9/到期100400s）应放行")
    if fsp.step_gate_ok({}):
        fail("S5b 空段（无 remaining/无到期）应 fail-closed 拒放行")
    if fsp.step_gate_ok({"remaining": 5_670_000_000}):
        fail("S5c 缺到期读数应 fail-closed 拒放行")
    if fsp.step_gate_ok({"remaining": 5_670_000_000, "seconds_to_expiry": "abc"}):
        fail("S5d 非数值读数应 fail-closed 拒放行（修前此形态抛异常=不裁决；"
             "数值字符串宽松化属新增放行面，只许变严禁走）")
    if fsp.step_gate_ok({"remaining": True, "seconds_to_expiry": 100_400}):
        fail("S5e 布尔读数应 fail-closed 拒放行（bool 非 quota 数值）")
    _s_saved = (fsp.STEP_REMAINING_FLOOR, fsp.STEP_SECONDS_TO_EXPIRY_FLOOR_S)
    try:
        fsp.STEP_REMAINING_FLOOR, fsp.STEP_SECONDS_TO_EXPIRY_FLOOR_S = None, None
        if fsp.step_gate_ok(_healthy):
            fail("S5f 注册表取不到阈（双阈缺失）应 fail-closed 拒放行"
                 "（宁可不烧，绝不静默回落到任何就地阈值）")
    finally:
        fsp.STEP_REMAINING_FLOOR, fsp.STEP_SECONDS_TO_EXPIRY_FLOOR_S = _s_saved
    _self_held = _self_held_step_literals(_EXEC_UNDER)
    if _self_held:
        fail(f"S5g 执行侧可执行码仍自持 step 双阈字面量 {_self_held[:3]}（REG-3："
             "数字清单在消费方码内零硬编码——2e8/3600 唯一正本=注册表声明行；"
             "注释/docstring 记载修前史不算，可执行码算）")
    _now_ms = 1_794_000_000_000
    _g_ok = fsp.derive_gate({"ts": _now_ms, "step": dict(_healthy)}, now_ms=_now_ms + 5_000)
    if _g_ok.get("step_ok") is not True:
        fail(f"S5h derive_gate 接线破缺：新鲜源+健康 step 读数应 step_ok=true，实得 {_g_ok}")
    _g_no = fsp.derive_gate({"ts": _now_ms, "step": {"remaining": 100_000_000,
                                                     "seconds_to_expiry": 1800}},
                            now_ms=_now_ms + 5_000)
    if _g_no.get("step_ok") is not False:
        fail(f"S5i derive_gate 接线破缺：分歧带读数（1e8/1800s）应 step_ok=false，实得 {_g_no}")

    print(f"PASS A单一事实源(执行侧闸阈==派发侧闸阈 5h={fsp.MM_HOLD_FLOOR_PCT}%"
          f"/周={fsp.MM_WEEKLY_HOLD_FLOOR_PCT}%) "
          f"B全网格{len(_P5)}×{len(_PWK)}={len(_P5) * len(_PWK)}点两侧裁决恒等(分歧0) "
          f"C旧分歧带清零 D负控判别力({len(pre_div)}点分歧/见证点10-62在内) "
          f"E执行侧fail-closed五态 F调度侧按go派发 "
          f"G闸面唯一性(死面属性0/死面字面量0/真闸面随阈翻转/slots子命令下线/gates无死字段/"
          f"8槽真面=anolis探针/G6负控判别力) "
          f"S step 腿同源(双阈同取注册表 账本/resource-rules.jsonl={_reg_rem:g}/{_reg_exp:g}s "
          f"全网格{len(_S_REM)}×{len(_S_EXP)}={_s_n}点恒等/分歧带负例1e8-1800两侧同false且活读同true/"
          f"修前负控{len(_s_pre_div)}点分歧/执行侧fail-closed六态+零自持字面量+derive_gate接线) — 全过"
          f"（被测：执行侧={os.path.basename(_EXEC_UNDER)} 派发侧={os.path.basename(_GOV_UNDER)}）",
          flush=True)
    sys.exit(0)


# ---- S 段件（step 腿；D-145/ESC-20）——定义在 main() 之后、调用发生在 main() 运行时，
# 全部行号>L335：上方 L1-335 与钉桩基线逐字节一致（mirror-scan-allowlist 行钉零移）。----

# 注册表（step 双阈唯一机读正本；REG-1 schema / REG-3 单源 / REG-5 变更纪律）
_REGISTRY = os.path.join(os.path.dirname(_TOOLS), "账本", "resource-rules.jsonl")

# 修前口径夹具（负控/变严下界锚；**非在役判据**——在役双阈唯一正本=注册表声明行）：
#   派发侧=quota-governor.py:250（expires>now ∧ remaining>0；1s 粒度同构为 exp>0）；
#   执行侧=factory-status-push.py:134 修前内联（到期>3600s ∧ remaining>2e8 自持）。
_PRE_STEP_REM_FLOOR = 200_000_000.0
_PRE_STEP_EXP_FLOOR = 3_600.0


def _pre_fix_step_dispatch_go(rem, exp):
    """修复前派发侧口径（夹具）：step.go=未到期且剩余>0。"""
    return rem > 0 and exp > 0


def _pre_fix_step_exec_ok(rem, exp):
    """修复前执行侧口径（夹具）：step_ok=到期>3600s 且 remaining>2e8（就地自持）。"""
    return exp > _PRE_STEP_EXP_FLOOR and rem > _PRE_STEP_REM_FLOOR


# step 腿网格（阈下/阈上/阈位/阈邻/修前分歧带边界/活读常见读数）
_S_REM = [0, 1, 99_999_999, 100_000_000, 100_000_001, 199_999_999, 200_000_000,
          200_000_001, 5_670_000_000, 8_000_000_000]
_S_EXP = [0, 1, 1799, 1800, 1801, 3599, 3600, 3601, 86_400, 100_400]

# 分歧带/活读见证点：(remaining, seconds_to_expiry, 统一阈下两侧应有的同判值)
_S_WITNESSES = [(100_000_000, 1800, False),      # 卡面点名负例：双维皆在分歧带
                (100_000_000, 86_400, False),    # 剩余维在分歧带（卡面「或」形态）
                (5_670_000_000, 1800, False),    # 到期维在分歧带（卡面「或」形态）
                (5_670_000_000, 100_400, True)]  # 活读见证（宪章 :171 实读 5.67e9/100400）


class _RuleError(Exception):
    """注册表不可证（缺席/坏行/无 step 规则行/歧义/双阈缺一或非数值）。"""


def _load_step_rule(path):
    """本门自读注册表（与执行侧 loader 同构的独立第二双眼睛）。

    返回 (remaining_floor, seconds_to_expiry_floor_s)；任一不可证形态抛 _RuleError
    （fail-closed：门不猜绿）。执行侧 loader 若被改成返回常量，本读数即与之失配
    → S1 红。"""
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError as e:
        raise _RuleError(f"注册表读不到 {path}: {e}") from e
    rules, step_rules = [], []
    for ln, line in enumerate(lines, 1):
        s = line.strip()
        if not s:
            continue
        try:
            obj = json.loads(s)
        except ValueError as e:
            raise _RuleError(f"坏行 L{ln}: {e}") from e
        if not isinstance(obj, dict):
            raise _RuleError(f"非对象行 L{ln}")
        if obj.get("event"):
            continue
        if obj.get("schema") != "af.resource-rule.v1":
            raise _RuleError(f"未认 schema 行 L{ln}: {obj.get('schema')!r}")
        rules.append(obj)
        if obj.get("account") == "step" and obj.get("resource") == "llm:step-plan":
            step_rules.append(obj)
    if not rules:
        raise _RuleError("注册表无任何规则行")
    if len(step_rules) != 1:
        raise _RuleError(f"step 规则行 {len(step_rules)} 条（应恰 1 条，多行=歧义）")
    r = step_rules[0]
    floors = [w.get("limit", {}).get("floor") for w in (r.get("windows") or [])
              if (w.get("limit") or {}).get("unit") == "credits"
              and "floor" in (w.get("limit") or {})]
    if len(floors) != 1:
        raise _RuleError(f"credits+floor 窗口 {len(floors)} 个（应恰 1 个）")
    rem_floor = floors[0]
    exp_floor = (r.get("renewal") or {}).get("seconds_to_expiry_floor_s")
    for v in (rem_floor, exp_floor):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise _RuleError(f"双阈非数值 ({rem_floor!r}, {exp_floor!r})")
    return float(rem_floor), float(exp_floor)


def _self_held_step_literals(path):
    """执行侧可执行码里自持 step 双阈字面量的位置：[(行号, 值), ...]（REG-3 零硬编码）。

    只扫**比较运算**（ast.Compare 子树）里的数值常量——任一书写形（200_000_000/2e8/
    200000000.0）解析同值即命中；单位换算（如 //3600 的 BinOp）不是闸阈不计；
    docstring 排除同 _dead_surface_literals 形制（文档记载修前史不算码）。"""
    thresh = {200_000_000.0, 3_600.0}
    with open(path, encoding="utf-8") as f:
        src = f.read()
    tree = ast.parse(src)
    doc_ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", None)
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                doc_ids.add(id(body[0].value))
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        for sub in ast.walk(node):
            if (isinstance(sub, ast.Constant) and isinstance(sub.value, (int, float))
                    and not isinstance(sub.value, bool) and id(sub) not in doc_ids
                    and float(sub.value) in thresh):
                hits.append((sub.lineno, sub.value))
    return hits


if __name__ == "__main__":
    main()
