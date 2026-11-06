#!/usr/bin/env python3
"""test-minimax-dispatch-gate.py — minimax 双道**派发闸**判据门（2026-11-03）

背景（RT 确证发现，非推演）：tools/factory-scheduler.py 的 minimax 双道派发闸，
原判据是「step 道 8 槽满（pgrep -fc 'af-orde[r].*step-5'>=8）→ 溢出到 minimax」
——那是 step 套餐到期**前**的负载卸载语义。而：
  · step 套餐 2026-10-30 20:40 到期（tools/quota-governor.py 头注）；
  · 运营者令 step 不再使用（计划/方法论-持续改进-20261031.md:245；
    计划/系统目标台账.md:13 G7「step 拒单→按运营者令改道 minimax」）。
  → step 在途恒 0 → 「8/8 才放行」的闸**结构永闭** → 自 2026-10-28 13:58 起
    零派发（状态观测/factory-scheduler.log 实测 2634 轮「step 在途 0/8 未满，跳过」）。
  → 计划正本声明的「到期切换预案=minimax 双通道+GLM」（计划/第三阶段开发计划-20261027.md:106）
    从未落地；而摘要/状态文件仍写 mm=go，读者会得出「minimax 道已放行」的相反结论。

修法（最小，不弱化任何既有保护）：闸判据扩为「step 不可用（quota step.go=false）
**或** step 8 槽满」——step 在役时原溢出语义一字不变（step 优先、未满不派），
step 停用时 minimax 升为主通道承活。mm_go 闸/源过期闸/mm 封顶/候选池/去重全保留。

本门在沙箱内**实跑生产代码路径**（不联网、不 ssh、不落单、不改生产状态文件）：
  A 闸判据（12 组）：step 停用 → 放行派发；step 在役且未满 → 不派（原语义保留）；
    step 在役且满 → 派发；step 判据不可得（step_go=None）→ 不派（fail-closed）；
    以及既有保护四闸（mm_go/源过期/mm 封顶/候选去重）与快照失败、FS_MINIMAX=0 关闭。
  B 摘要/状态面诚实性：mm=go 只是配额裁决，不等于在派发——_mm_posture 必须显式
    区分「主通道(step停用)/溢出待step(n/8)」与「已派发/未派发」；摘要行须含 mm道= 段；
    状态文件 last_round.mm_dispatch 段须落闸判据与本轮 mm 动作。
  C 负控（判别力自证）：同一夹具喂**修前件**（tools/factory-scheduler.py.
    20261031-pre-RT-mmstepgate.bak）必须**不派发**（即修前件在本门必红），
    喂现役件必须派发——否则本门无判别力（夹具写错/断言写错）→ 红。

用法：python3 tools/test-minimax-dispatch-gate.py [被测调度件路径]
      被测件默认 tools/factory-scheduler.py；指 .bak 可复演修前红。
      负控件路径可用环境变量 MMGATE_PRE_FIX 覆盖（默认 tools/ 下修前快照）。
退出码 0=全过；任一断言红即非零退出并点名断言。"""
import contextlib
import importlib.util
import io
import json
import os
import sys
from importlib.machinery import SourceFileLoader

_TOOLS = os.path.dirname(os.path.abspath(__file__))
_SCHED_UNDER = sys.argv[1] if len(sys.argv) > 1 else os.path.join(_TOOLS, "factory-scheduler.py")
_PRE_FIX = (os.environ.get("MMGATE_PRE_FIX")
            or os.path.join(_TOOLS, "factory-scheduler.py.20261031-pre-RT-mmstepgate.bak"))

_RESULTS = []


def check(name, ok, detail=""):
    _RESULTS.append((name, bool(ok), detail))
    print(f"  {'PASS' if ok else 'FAIL'} {name}" + (f" — {detail}" if detail else ""), flush=True)


def _load(path, name):
    # SourceFileLoader 显式指定：argv 可指 .bak 等非 .py 后缀件（复演修前红）
    loader = SourceFileLoader(name, path)
    spec = importlib.util.spec_from_file_location(name, path, loader=loader)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _d(**kw):
    """造一轮探针结果（默认值＝现场实况：step 停用 + minimax 放行）。"""
    quota = {"stale": False, "mm_go": True, "mm_err": None, "mm_5h": 58, "mm_wk": 46,
             "note": "", "step_go": False, "step_used": None,
             "step_err": "step 配额读取失败：credit_buckets 为空（no_active_subscription）"}
    quota.update(kw.pop("quota", {}) or {})
    base = {"error": "", "quota": quota, "step_inflight": 0, "mm_count": 0,
            "pending_count": 0, "inflight": 0,
            "pool": ["t1"], "pending_tasks": ["t1"], "mm_tasks": [], "daemons": {}}
    base.update(kw)
    return base


def _run(mod, d):
    """跑一轮 minimax_round（DRY 态：不落单/不 scp/不写变更日志）。返回 (acts, 输出)。"""
    mod._DRY[0] = True
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        acts = mod.minimax_round({"minimax": {}}, d)
    return list(acts or []), buf.getvalue()


def _mm_acts(acts):
    return [a for a in acts if str(a).startswith("mm:")]


def main():
    print(f"被测调度件：{os.path.basename(_SCHED_UNDER)}", flush=True)
    try:
        fsched = _load(_SCHED_UNDER, "factory_scheduler_under_test")
    except Exception as e:  # noqa: BLE001
        print(f"FAIL 调度件加载失败 {_SCHED_UNDER}: {type(e).__name__}: {e}", flush=True)
        sys.exit(1)

    print("A 闸判据组：", flush=True)
    # A1 step 停用 → 闸不得永闭，必须放行派发（修前件此处无动作＝结构永闭）
    acts, out = _run(fsched, _d())
    check("A1 step 道停用（step_go=false）时闸放行派发（不永闭）",
          bool(_mm_acts(acts)), f"acts={acts}")
    check("A2 step 停用时日志须写明 minimax 承活且不再出现「未满，跳过」",
          ("minimax 承活" in out) and ("未满，跳过" not in out),
          out.strip().splitlines()[-1] if out.strip() else "")
    # A3 step 在役 + 未满 → 原溢出语义保留（step 优先，未满不派）
    acts, _ = _run(fsched, _d(quota={"step_go": True}, step_inflight=0))
    check("A3 step 在役且在途 0/8 未满 → 不派发（原溢出语义保留）",
          not _mm_acts(acts), f"acts={acts}")
    # A4 step 在役 + 满 → 原语义照旧放行
    acts, _ = _run(fsched, _d(quota={"step_go": True}, step_inflight=8))
    check("A4 step 在役且在途 8/8 满 → 派发（原语义保留）",
          bool(_mm_acts(acts)), f"acts={acts}")
    # A5 边界：7/8 仍不派
    acts, _ = _run(fsched, _d(quota={"step_go": True}, step_inflight=7))
    check("A5 step 在役且在途 7/8（边界）→ 不派发",
          not _mm_acts(acts), f"acts={acts}")
    # A6 判据不可得（quota.json 无 step 段 → step_go=None）→ fail-closed，仍须 8/8
    acts, _ = _run(fsched, _d(quota={"step_go": None}, step_inflight=0))
    check("A6 step 判据不可得（step_go=None）→ 不派发（fail-closed，不猜）",
          not _mm_acts(acts), f"acts={acts}")
    # A7 step 停用时在途探针失效（si=None）→ 与 step 无关，仍放行
    acts, _ = _run(fsched, _d(step_inflight=None))
    check("A7 step 停用且在途探针失效 → 仍派发（step 不可用在途读数无关）",
          bool(_mm_acts(acts)), f"acts={acts}")
    # A8/A9 既有保护：minimax 配额闸 / 源过期闸
    acts, _ = _run(fsched, _d(quota={"mm_go": False}))
    check("A8 minimax 不放行（mm_go=false）→ 不派发（配额闸保留）",
          not _mm_acts(acts), f"acts={acts}")
    acts, _ = _run(fsched, _d(quota={"stale": True}))
    check("A9 配额源读数过期（stale）→ 不派发（源过期闸保留）",
          not _mm_acts(acts), f"acts={acts}")
    # A10 mm 条目封顶保留
    acts, _ = _run(fsched, _d(mm_count=fsched.MM_CAP))
    check("A10 pending 中 mm 条目达封顶 → 不派发（封顶闸保留）",
          not _mm_acts(acts), f"acts={acts}")
    # A11/A12 候选池与去重保留
    acts, _ = _run(fsched, _d(pool=["tX"], pending_tasks=["t1"]))
    check("A11 无候选任务（池任务不在 pending）→ 不派发（候选池闸保留）",
          not _mm_acts(acts), f"acts={acts}")
    acts, _ = _run(fsched, _d(mm_tasks=["t1"]))
    check("A12 已有 mm 条目的任务 → 不派发（去重保留）",
          not _mm_acts(acts), f"acts={acts}")
    # A13 anolis 快照失败 → 不派发（fail-closed）
    acts, _ = _run(fsched, _d(error="anolis 不可达（快照失败）"))
    check("A13 anolis 快照失败 → 不派发（fail-closed）",
          not _mm_acts(acts), f"acts={acts}")
    # A14 FS_MINIMAX=0 关闭开关保留
    _old_on = fsched.MM_ON
    try:
        fsched.MM_ON = False
        acts, _ = _run(fsched, _d())
    finally:
        fsched.MM_ON = _old_on
    check("A14 FS_MINIMAX=0（双道关闭）→ 不派发（开关保留）",
          not _mm_acts(acts), f"acts={acts}")

    print("B 摘要/状态面诚实性组：", flush=True)
    if not hasattr(fsched, "_mm_posture"):
        # 修前件无姿态读数函数：摘要只写 mm=go（读者会误读「minimax 道已放行」）
        check("B1 被测件具备 mm 道姿态读数（_mm_posture）", False,
              "被测件无 _mm_posture——摘要/状态面仍只报 mm=go，读者会误读「minimax 道已放行」")
    else:
        # B1/B2 姿态读数
        p1 = fsched._mm_posture(_d(), [])
        check("B1 step 停用时姿态读数为「主通道(step停用)」",
              "主通道(step停用)" in p1, p1)
        p2 = fsched._mm_posture(_d(quota={"step_go": True}, step_inflight=0), [])
        check("B2 step 在役未满时姿态读数为「溢出待step(0/8)」",
              "溢出待step(0/8)" in p2, p2)
        # B3 已派发/未派发区分
        p3 = fsched._mm_posture(_d(), ["mm:+2"])
        p4 = fsched._mm_posture(_d(), [])
        check("B3 姿态读数区分已派发/未派发（mm=go ≠ 在派发）",
              ("已派发" in p3 and "未派发" in p4), f"{p3} / {p4}")
        # B4 摘要行含 mm道= 段
        line = fsched.summary(_d(), [])
        check("B4 摘要行含「mm道=」姿态段", "mm道=" in line, line)
    # B5 状态文件 last_round.mm_dispatch 段
    st = {"rounds": 0, "minimax": {"profile": "mavis-m3", "written_total": 0,
                                  "last_write_ts": 0, "last_tasks": []},
          "supply": {}, "health": {}}
    saved = {}
    d_live = _d()
    orig = (fsched.collect, fsched.supply_round, fsched._portal_supply,
            fsched.health_round, fsched.save_state)
    try:
        fsched.collect = lambda: d_live
        fsched.supply_round = lambda s, dd, force: []
        fsched._portal_supply = lambda s: []
        fsched.health_round = lambda s, dd: []
        fsched.save_state = lambda s: saved.update(s)
        fsched._DRY[0] = True
        with contextlib.redirect_stdout(io.StringIO()):
            fsched.round_once(st, False)
    finally:
        (fsched.collect, fsched.supply_round, fsched._portal_supply,
         fsched.health_round, fsched.save_state) = orig
    md = (saved.get("last_round") or {}).get("mm_dispatch")
    check("B5 状态文件 last_round.mm_dispatch 落闸判据与本轮 mm 动作",
          isinstance(md, dict) and md.get("step_dead") is True and bool(md.get("acts")),
          json.dumps(md, ensure_ascii=False))

    print("C 负控（判别力自证）组：", flush=True)
    if not os.path.exists(_PRE_FIX):
        check(f"C1 负控件在位（修前快照 {os.path.basename(_PRE_FIX)}）", False,
              "缺件——本门无法自证判别力（负控件须在位）")
    else:
        try:
            pre = _load(_PRE_FIX, "factory_scheduler_prefix_under_test")
        except Exception as e:  # noqa: BLE001
            check("C1 修前件可加载", False, f"{type(e).__name__}: {e}")
            pre = None
        if pre is not None:
            pacts, _ = _run(pre, _d())
            check("C1 修前件（8/8 闸永闭形态）同一夹具必不派发——修前件在本门必红",
                  not _mm_acts(pacts), f"修前 acts={pacts}")
            cacts, _ = _run(fsched, _d())
            check("C2 现役件同一夹具必派发——新门有牙齿",
                  bool(_mm_acts(cacts)), f"现役 acts={cacts}")

    passed = sum(1 for _n, ok, _d_ in _RESULTS if ok)
    total = len(_RESULTS)
    if passed != total:
        bad = [n for n, ok, _d_ in _RESULTS if not ok]
        print(f"FAIL 断言 {passed}/{total} 通过，红项：{'; '.join(bad)}", flush=True)
        sys.exit(1)
    print(f"PASS minimax 派发闸判据门 {passed}/{total} 组断言全过"
          f"（被测调度件={os.path.basename(_SCHED_UNDER)}；"
          f"负控件={os.path.basename(_PRE_FIX)}）", flush=True)
    sys.exit(0)


if __name__ == "__main__":
    main()
