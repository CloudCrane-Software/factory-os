#!/usr/bin/env python3
"""tools/test-gate-source-freshness.py — 门：派生闸「源读数新鲜度」三消费点齐活。

被测缺陷（2026-11-03 OBS 回头·派生闸，确证发现）：
  全链唯一的源读数新鲜度检查只在**派发侧**（tools/factory-scheduler.py:read_quota()
  —— ts=st.get("ts") or 0; age_ms=time.time()*1000-ts; q["stale"]=age_ms>QUOTA_STALE*1000，
  QUOTA_STALE=600）。派生闸（tools/factory-status-push.py 下发到 anolis 的
  /data/bench/queue/gate.json）此前只带「自身写入时刻」(updated)、**不携带源读数 ts**：
  ①生产者侧读 quota.json 无任何 age/ts 检查；②执行侧 burn-runner 的 10min 新鲜度门
  只看闸文件自身 mtime（burn-runner.py:58-60），而推送器每 60s 覆写闸文件 → 源
  quota.json 停写时闸恒新鲜、mm_ok/step_ok 恒为停写前的旧裁决 → 照旧按旧配额下单
  （撞限流形态），且与派发侧（源陈旧即停派）对同一源读数给出**相反行为**；
  ③第三个消费点 tools/factory-kb-worker.py:cmd_quota_ok 同样只透出 go、无 age/ts 判定。

本门覆盖（修后必须全绿）：
  A组 生产者（status-push:derive_gate）——派生闸携带 src_ts/src_age_s/src_stale；
    源读数陈旧（或无 ts）即闸自身 fail-closed（step_ok=mm_ok=false）。
  B组 执行者（burn-runner:gate_ok / gate_any_ok）——执行侧**独立**判源读数年龄：
    不可判（老闸无 src_ts）或超阈 → 拒单（既有断言一字未弱化：闸文件自身过期、
    老闸无 mm_ok 键、逐通道判据、glm 道语义全部保留）。
  C组 消费点（factory-kb-worker:cmd_quota_ok）——源陈旧即 go=false。
  D组 判别力负向对照——同一夹具喂**修前** burn-runner（.20261031-pre-RT.bak 真件）
    必须仍放行（绿）＝修前失明实证；修前 status-push 真件内不得含任何源新鲜度痕迹。
  E组 阈值一致性——四处阈（派发 600 / 生产 600 / 执行 600 / 消费 600）同值。

纪律：零生产副作用——不连 anolis、不改在役闸文件、不读真 状态观测/quota.json；
全部夹具落沙箱（$WS/.tmp_gate_srcfresh_test，跑完清理）；burn-runner 的 GATE 与
kb-worker 的 WS 均重定向到沙箱。

跑法：python3 tools/test-gate-source-freshness.py   （期望末行 ALL PASS (N/N)，rc=0）
"""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import sys
import time

WS = "/home/pan-ding/workspace/agent黑灯工厂"
TOOLS = f"{WS}/tools"
SANDBOX = f"{WS}/.tmp_gate_srcfresh_test"
PUSH = f"{TOOLS}/factory-status-push.py"
BURN = f"{TOOLS}/burn-runner.py"
KBW = f"{TOOLS}/factory-kb-worker.py"
PUSH_BAK = f"{TOOLS}/factory-status-push.py.20261031-pre-RT.bak"
BURN_BAK = f"{TOOLS}/burn-runner.py.20261031-pre-RT.bak"
SCHED = f"{TOOLS}/factory-scheduler.py"

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"{'PASS' if cond else 'FAIL'} {name}" + (f"  [{detail}]" if detail and not cond else ""))


def load(name, path):
    # .bak 后缀的修前件无法由 spec_from_file_location 推断 loader（返回 None）→
    # 显式 SourceFileLoader 按源码载入（仍是真件逐字执行）。
    if path.endswith(".bak"):
        from importlib.machinery import SourceFileLoader
        loader = SourceFileLoader(name, path)
        spec = importlib.util.spec_from_loader(name, loader)
        mod = importlib.util.module_from_spec(spec)
        loader.exec_module(mod)
        return mod
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------- 载入被测件（文件名带连字符，按路径载入） ----------
push = load("push_under_test", PUSH)
burn = load("burn_under_test", BURN)
kbw = load("kbw_under_test", KBW)
burn_bak = load("burn_pre_fix", BURN_BAK)          # 修前真件（负向对照）
sched = load("sched_under_test", SCHED)            # 派发侧（阈值一致性对照）

GATE_PATH = f"{SANDBOX}/gate.json"
burn.GATE = GATE_PATH
burn_bak.GATE = GATE_PATH

NOW_MS = int(time.time() * 1000)
STALE_MS = 700_000          # 源读数陈旧 700s > 600s 阈
NOW_S = NOW_MS // 1000


def write_gate(gate, mtime=None):
    """写沙箱闸文件（mtime 默认=now=闸自身新鲜）。"""
    with open(GATE_PATH, "w", encoding="utf-8") as f:
        json.dump(gate, f, ensure_ascii=False)
    if mtime is not None:
        os.utime(GATE_PATH, (mtime, mtime))
    return GATE_PATH


def quota_src(ts=None, age_s=0, healthy=True):
    """构造 quota.json 源读数夹具（healthy=两通道读数皆健康）。"""
    q = {"ts": (NOW_MS - age_s * 1000) if ts is None else ts,
         "step": ({"go": True, "remaining": 900_000_000, "seconds_to_expiry": 7200,
                   "used_percent": 12.0} if healthy else
                  {"go": False, "error": "step 配额读取失败：no_active_subscription"}),
         "minimax": ({"go": True, "five_hour_remaining_pct": 80, "weekly_remaining_pct": 49}
                     if healthy else
                     {"go": False, "error": "minimax 配额读取失败：x"})}
    return q


shutil.rmtree(SANDBOX, ignore_errors=True)
os.makedirs(SANDBOX, exist_ok=True)

# ================= A 组：生产者（派生闸携带源读数 + 源陈旧即落闸） =================
g_fresh = push.derive_gate(quota_src(age_s=5), now_ms=NOW_MS)
check("A1 新鲜源：闸两通道放行（step_ok/mm_ok 判据一字未改）", g_fresh["step_ok"] and g_fresh["mm_ok"],
      json.dumps(g_fresh, ensure_ascii=False))
check("A2 新鲜源：闸携带源读数 ts（缺陷核心：此前闸无此字段）", g_fresh.get("src_ts") == NOW_MS - 5000,
      str(g_fresh.get("src_ts")))
check("A3 新鲜源：闸自报源年龄与陈旧标记（src_age_s/src_stale）",
      g_fresh.get("src_age_s") == 5 and g_fresh.get("src_stale") is False,
      f"src_age_s={g_fresh.get('src_age_s')} src_stale={g_fresh.get('src_stale')}")

g_stale = push.derive_gate(quota_src(age_s=700), now_ms=NOW_MS)
check("A4 源停写 700s：闸自身 fail-closed（step_ok=mm_ok=false，不再下发旧裁决）",
      g_stale["step_ok"] is False and g_stale["mm_ok"] is False, json.dumps(g_stale, ensure_ascii=False))
check("A5 源停写：闸标记 src_stale=true 并记真因", g_stale.get("src_stale") is True
      and "源读数过期" in (g_stale.get("reason") or ""), str(g_stale.get("reason")))
check("A6 源停写：闸仍携带源 ts/年龄（消费侧据此独立判断）",
      g_stale.get("src_ts") == NOW_MS - 700_000 and g_stale.get("src_age_s") == 700,
      f"src_ts={g_stale.get('src_ts')} src_age_s={g_stale.get('src_age_s')}")

g_nots = push.derive_gate(quota_src(ts=0), now_ms=NOW_MS)
check("A7 源读数无 ts：闸 fail-closed（不可判新鲜度 → 宁可不烧）",
      g_nots["step_ok"] is False and g_nots["mm_ok"] is False and g_nots.get("src_stale") is True,
      json.dumps(g_nots, ensure_ascii=False))

g_edge = push.derive_gate(quota_src(age_s=600), now_ms=NOW_MS)
g_edge2 = push.derive_gate(quota_src(age_s=601), now_ms=NOW_MS)
check("A8 阈边界：age=600s 不算陈旧、601s 算陈旧（与派发侧 >600 同语义）",
      g_edge.get("src_stale") is False and g_edge2.get("src_stale") is True,
      f"600→{g_edge.get('src_stale')} 601→{g_edge2.get('src_stale')}")

g_dead = push.derive_gate(quota_src(age_s=700, healthy=False), now_ms=NOW_MS)
check("A9 源读数本身死态（go=false）：闸仍落闸（既有判据保留）",
      g_dead["step_ok"] is False and g_dead["mm_ok"] is False and g_dead.get("src_stale") is True)

# ================= B 组：执行者（burn-runner 独立判源读数年龄） =================
write_gate(g_fresh)
ok_step, why_step = burn.gate_ok("step-5")
ok_mm, why_mm = burn.gate_ok("mavis-m31f")
ok_any, why_any = burn.gate_any_ok()
check("B1 新鲜源闸：step 道放行", ok_step, why_step)
check("B2 新鲜源闸：mavis 道放行", ok_mm, why_mm)
check("B3 新鲜源闸：粗闸放行", ok_any, why_any)

write_gate(g_stale)
ok, why = burn.gate_ok("step-5")
check("B4 源停写（闸自身新鲜）：执行侧拒单（缺陷核心——修前此处放行）", ok is False, why)
check("B5 源停写：拒单理由点名源读数年龄", "源读数过期" in why, why)
ok, why = burn.gate_ok("mavis-m31f")
check("B6 源停写：mavis 道同样拒单（不按旧 mm_ok 裁决下单）", ok is False, why)
ok, why = burn.gate_any_ok()
check("B7 源停写：粗闸亦拒（不把停写前的旧裁决当活闸）", ok is False and "源读数过期" in why, why)

write_gate({"step_ok": True, "mm_ok": True, "updated": "2026-11-03 00:00:00"})   # 老闸格式：无 src_ts
ok, why = burn.gate_ok("step-5")
check("B8 老闸格式（无 src_ts）：拒单（不可判新鲜度 → fail-closed）", ok is False, why)
check("B9 老闸格式：理由点名「无源读数 ts」", "无源读数 ts" in why, why)
ok, why = burn.gate_any_ok()
check("B10 老闸格式：粗闸亦拒", ok is False, why)

write_gate(g_fresh, mtime=time.time() - 700)      # 闸文件自身也过期（既有断言）
ok, why = burn.gate_ok("step-5")
check("B11 闸文件自身过期>10min：仍拒（既有断言未弱化）", ok is False and "过期" in why, why)
ok, why = burn.gate_any_ok()
check("B12 闸文件自身过期：粗闸仍拒（既有断言未弱化）", ok is False, why)

write_gate({"step_ok": False, "mm_ok": True, "src_ts": NOW_MS, "src_age_s": 0, "src_stale": False})
ok_step, why_step = burn.gate_ok("step-5")
ok_mm, why_mm = burn.gate_ok("mavis-m31f")
ok_glm, why_glm = burn.gate_ok("glm-cp")
check("B13 通道判据保留：step_ok=false 时 step 道拒、mavis 道仍放行",
      ok_step is False and ok_mm is True, f"step={why_step} mavis={why_mm}")
check("B14 glm 道语义保留（无窗位语义、源新鲜即放行）", ok_glm is True, why_glm)

write_gate({"step_ok": True, "mm_ok": False, "src_ts": NOW_MS, "src_age_s": 0, "src_stale": False})
ok_mm, why_mm = burn.gate_ok("mavis-m31f")
check("B15 通道判据保留：mm_ok=false 时 mavis 道拒（老闸无 mm_ok 键仍拒）",
      ok_mm is False and "mm_ok" in why_mm, why_mm)
write_gate({"step_ok": True, "src_ts": NOW_MS})
ok_mm, why_mm = burn.gate_ok("mavis-m31f")
check("B16 老闸无 mm_ok 键：mavis 道仍拒（等新闸，既有断言保留）",
      ok_mm is False and "无 mm_ok 键" in why_mm, why_mm)

os.remove(GATE_PATH)
ok, why = burn.gate_ok("step-5")
check("B17 闸文件缺失：拒（既有 fail-closed 保留）", ok is False and "缺失" in why, why)

# ================= C 组：消费点（factory-kb-worker cmd_quota_ok） =================
KBWS = f"{SANDBOX}/ws"
os.makedirs(f"{KBWS}/状态观测", exist_ok=True)
kbw.WS = KBWS


def kb_quota_ok(q):
    with open(f"{KBWS}/状态观测/quota.json", "w", encoding="utf-8") as f:
        json.dump(q, f, ensure_ascii=False)
    buf = io.StringIO()
    code = 0
    with contextlib.redirect_stdout(buf):
        try:
            kbw.cmd_quota_ok()
        except SystemExit as e:
            code = e.code or 0
    return json.loads(buf.getvalue().strip().splitlines()[-1]), code


r, code = kb_quota_ok(quota_src(age_s=5))
check("C1 新鲜源：kb 消费点 go=true（既有语义保留）",
      r.get("go") is True and r.get("stale") is False, json.dumps(r, ensure_ascii=False))
r, code = kb_quota_ok(quota_src(age_s=700))
check("C2 源停写 700s：kb 消费点 go=false（修前此处透出 go=true）", r.get("go") is False,
      json.dumps(r, ensure_ascii=False))
check("C3 源停写：kb 消费点自报 stale/age_s（证据可读）",
      r.get("stale") is True and isinstance(r.get("age_s"), int) and r["age_s"] >= 700,
      json.dumps(r, ensure_ascii=False))
r, code = kb_quota_ok(quota_src(ts=0))
check("C4 源读数无 ts：kb 消费点 go=false（不可判新鲜度 → fail-closed）",
      r.get("go") is False and r.get("stale") is True, json.dumps(r, ensure_ascii=False))

# ================= D 组：判别力负向对照（修前真件必须仍放行＝失明实证） =================
# 夹具 X：闸携带**陈旧的源 ts**、但通道裁决仍是停写前的真值（step_ok/mm_ok=true）——
# 这正是修前生产者在源停写时的行为（旧闸只带自身写入时刻、照抄停写前的读数）。
# 修前执行者对该闸必须放行（它只看闸文件 mtime，源 ts 在场也不看）＝失明实证。
stale_but_open = {"step_ok": True, "mm_ok": True, "src_ts": NOW_MS - STALE_MS,
                  "src_age_s": 700, "src_stale": True, "updated": "2026-11-03 00:00:00"}
write_gate(stale_but_open)
ok_bak, why_bak = burn_bak.gate_ok("step-5")
check("D1 负向对照：修前 burn-runner 对「源 ts 陈旧但通道判开」的闸仍放行（失明实证）",
      ok_bak is True, f"修前返回 ok={ok_bak} why={why_bak}")
ok_bak2, why_bak2 = burn_bak.gate_any_ok()
check("D2 负向对照：修前粗闸对同一闸仍放行（闸自身新鲜即过）", ok_bak2 is True,
      f"修前返回 ok={ok_bak2} why={why_bak2}")
ok_new, why_new = burn.gate_ok("step-5")
check("D3 同一夹具喂修后执行者=拒单（源读数年龄判别力生效）",
      ok_new is False and "源读数过期" in why_new, why_new)

# 夹具 Y：修前生产者的闸字面量逐字重放（取自 tools/factory-status-push.py.20261031-pre-RT.bak
# 的 gate 构造块）——源停写时旧闸仍判两通道开、且不带任何源 ts（老闸格式）。
sq_bak = quota_src(age_s=700)["step"]
mq_bak = quota_src(age_s=700)["minimax"]
old_gate = {"step_ok": (sq_bak.get("seconds_to_expiry") or 0) > 3600 and (sq_bak.get("remaining") or 0) > 200_000_000,
            "mm_ok": (mq_bak.get("five_hour_remaining_pct") or 0) > 15
            and (mq_bak.get("weekly_remaining_pct") or 0) > 20 and bool(mq_bak.get("go")),
            "remaining": sq_bak.get("remaining"), "seconds_to_expiry": sq_bak.get("seconds_to_expiry"),
            "updated": "2026-11-03 00:00:00"}
write_gate(old_gate)
ok_bak3, why_bak3 = burn_bak.gate_ok("step-5")
ok_new3, why_new3 = burn.gate_ok("step-5")
check("D4 修前链：旧闸字面量（源停写仍判开、无 src_ts）喂修前执行者=放行（缺陷全链绿）",
      ok_bak3 is True, f"修前 ok={ok_bak3}")
check("D5 修后链：同一旧闸喂修后执行者=拒单（修后补上的闸拒生效）",
      ok_new3 is False and ("无源读数 ts" in why_new3 or "源读数过期" in why_new3), why_new3)

with open(BURN_BAK, encoding="utf-8") as f:
    burn_bak_src = f.read()
check("D6 修前 burn-runner 全文无「源读数」新鲜度判定痕迹（src_ts 零命中）",
      "src_ts" not in burn_bak_src, "修前件含 src_ts")
with open(PUSH_BAK, encoding="utf-8") as f:
    push_bak_src = f.read()
check("D7 修前 status-push 全文无源新鲜度痕迹（src_ts/derive_gate 零命中）",
      "src_ts" not in push_bak_src and "derive_gate" not in push_bak_src, "修前件含源新鲜度痕迹")

# ================= E 组：阈值一致性（四处同值 600s） =================
check("E1 生产/执行/消费三处阈同值 600（与派发侧 QUOTA_STALE 同值）",
      push.QUOTA_SRC_STALE_S == burn.SRC_STALE_S == kbw.QUOTA_STALE_S == sched.QUOTA_STALE == 600,
      f"push={push.QUOTA_SRC_STALE_S} burn={burn.SRC_STALE_S} kb={kbw.QUOTA_STALE_S} "
      f"sched={sched.QUOTA_STALE}")

# ================= 收尾：清沙箱 =================
shutil.rmtree(SANDBOX, ignore_errors=True)
check("E2 沙箱清理（零残留）", not os.path.exists(SANDBOX))

print(f"\nALL PASS ({len(PASS)}/{len(PASS) + len(FAIL)})" if not FAIL else
      f"\nSOME FAIL ({len(FAIL)}/{len(PASS) + len(FAIL)})")
for f in FAIL:
    print(f"  FAIL: {f}")
sys.exit(1 if FAIL else 0)
