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
        if not os.path.exists(_GOV_PRE_FIX):
            fail(f"G6 负控件缺失 {_GOV_PRE_FIX}（闸面唯一性段失去判别力自证）")
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

    print(f"PASS A单一事实源(执行侧闸阈==派发侧闸阈 5h={fsp.MM_HOLD_FLOOR_PCT}%"
          f"/周={fsp.MM_WEEKLY_HOLD_FLOOR_PCT}%) "
          f"B全网格{len(_P5)}×{len(_PWK)}={len(_P5) * len(_PWK)}点两侧裁决恒等(分歧0) "
          f"C旧分歧带清零 D负控判别力({len(pre_div)}点分歧/见证点10-62在内) "
          f"E执行侧fail-closed五态 F调度侧按go派发 "
          f"G闸面唯一性(死面属性0/死面字面量0/真闸面随阈翻转/slots子命令下线/gates无死字段/"
          f"8槽真面=anolis探针/G6负控判别力) — 全过"
          f"（被测：执行侧={os.path.basename(_EXEC_UNDER)} 派发侧={os.path.basename(_GOV_UNDER)}）",
          flush=True)
    sys.exit(0)


if __name__ == "__main__":
    main()
