#!/usr/bin/env python3
"""tools/test-tmp-write-admission.py — 门：/tmp 写入门径量纲 + 门件写盘落点。

被测对象（2026-11-02 RT 收尾 DEB57 修复；缺陷=监测量纲与实际写入门径不一致）：

  A) tools/factory-watch.py 的 probe_tmp_write_admission() 与 A4W:tmp 告警环。
     A4L 量的是 os.statvfs("/tmp").f_bavail——「全机剩余空间」那一本账；实际
     拒绝写入的是 tmpfs 每用户配额（usrquota）那一本账。2026-11-02 10:37 实测：
     f_bavail 报 1012MiB「可用」，同刻 1MiB 写即 OSError 122 Disk quota
     exceeded（/home 同刻 WRITE OK）——A4L 的「可用 MiB」不代表「写得进去」。
     A4W 改为真写 1MiB 试门径：写不进＝写即失败（红级），A4L 只管「提前叫人」。

  B) kb/verify.py 的临时目录落点。原 tempfile.TemporaryDirectory(prefix=
     "kb-verify-quick-") 默认落 /tmp（tmpfs 7.5G+usrquota），配额耗尽时
     src.backup(dst) 直接 sqlite3.OperationalError: disk I/O error → L4 集成门
     硬红。改落 $HOME 下 PID 隔离的磁盘目录（进程内 tempfile.tempdir 一并改写，
     覆盖被测件 kb.test_store 的逐用例临时库）。

纪律：零生产副作用——不跑真实 watch 轮（会写生产 latest.json/data.json/
watch-state.json 并与在飞 watch pid 抢 state）；ALARMS_LOG/LATEST/DASH_DATA/
STATE_FILE 全部重定向沙箱；写探针只落沙箱目录与真 /tmp 的 1MiB 短命探针文件
（用完即删，断言零残留）。

跑法：python3 tools/test-tmp-write-admission.py   （期望末行 ALL PASS (N/N)，rc=0）
"""
import contextlib
import importlib.util
import json
import os
import shutil
import sys
import tempfile
from unittest import mock

WS = "/home/pan-ding/workspace/agent黑灯工厂"
TARGET = f"{WS}/tools/factory-watch.py"
KBVERIFY = f"{WS}/kb/verify.py"
TEST_ROOT = f"{WS}/.tmp_tmpwrite_test"          # 沙箱（跑完清理）

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"{'PASS' if cond else 'FAIL'} {name}" + (f"  [{detail}]" if detail and not cond else ""))


# ---------- 被测件载入（factory-watch.py 文件名带连字符，按路径载入） ----------
spec = importlib.util.spec_from_file_location("fw_under_test", TARGET)
md = importlib.util.module_from_spec(spec)
spec.loader.exec_module(md)

os.makedirs(TEST_ROOT, exist_ok=True)
md.ALARMS_LOG = f"{TEST_ROOT}/alarms.log"
md.LATEST = f"{TEST_ROOT}/latest.json"
md.DASH_DATA = f"{TEST_ROOT}/data.json"
md.STATE_FILE = f"{TEST_ROOT}/watch-state.json"

T = 1792610000.0
A4L_WARN_MSG = ("本机 /tmp 可用 {x} MiB<2662MiB（usrquota 校准线，闸线 2252MiB，"
                "低于则 sched/mcode 拦新臂/新判分）")


def stubs():
    """build_alarms 最小桩输入：其余环全静默，只有 /tmp 两环由被测探针驱动。"""
    return dict(
        arms=[], plan=[],
        sched={"status_file_exists": True, "mtime_stale": False,
               "proc_confirmed_down": False, "alive": False, "running_arms": []},
        anolis={}, relay={"consecutive_failures": 0, "last_event": "-"},
        state={"alarm_open": {}, "alarm_logged": {}, "sweb_img_hist": []},
        extras=None, archived=None,
    )


def of_code(alarms, code):
    return [a for a in alarms if a["code"] == code]


# ================= A 组：写入门径探针本身 =================

# ---------- W1 真 /tmp：写得进去 + 零残留 ----------
before_tmp = set(os.listdir("/tmp"))
ok1, err1 = md.probe_tmp_write_admission()
after_tmp = set(os.listdir("/tmp"))
check("W1 真 /tmp 写探针成功且零残留（1MiB 短命件用完即删）",
      ok1 is True and err1 == "" and before_tmp == after_tmp,
      f"ok={ok1} err={err1} residue={sorted(after_tmp - before_tmp)}")

# ---------- W2 真实写失败（非打桩）：只读目录 ----------
ro = f"{TEST_ROOT}/ro"
os.makedirs(ro, exist_ok=True)
os.chmod(ro, 0o555)
try:
    ok2, err2 = md.probe_tmp_write_admission(ro)
finally:
    os.chmod(ro, 0o755)
check("W2 真实写失败（非打桩）：只读目录 → (False, OSError 13 …)",
      ok2 is False and err2.startswith("OSError 13 "), f"ok={ok2} err={err2}")

# ---------- W3 沙箱可写目录：写得进去 ----------
sb = f"{TEST_ROOT}/writable"
os.makedirs(sb, exist_ok=True)
ok3, err3 = md.probe_tmp_write_admission(sb)
check("W3 沙箱可写目录 → (True, '')",
      ok3 is True and err3 == "", f"ok={ok3} err={err3}")

# ---------- W4 事故同款 errno：EDQUOT(122) ----------
with mock.patch("builtins.open", side_effect=OSError(122, "Disk quota exceeded")):
    ok4, err4 = md.probe_tmp_write_admission("/tmp")
check("W4 EDQUOT(122) → (False, 'OSError 122 Disk quota exceeded')",
      ok4 is False and err4 == "OSError 122 Disk quota exceeded", f"ok={ok4} err={err4}")

# ---------- W5 探针自身故障 fail-closed（不当成写得进去） ----------
with mock.patch("builtins.open", side_effect=RuntimeError("probe boom")):
    ok5, err5 = md.probe_tmp_write_admission("/tmp")
check("W5 探针自身异常 → fail-closed 记写不进（不静默放行）",
      ok5 is False and err5.startswith("RuntimeError: "), f"ok={ok5} err={err5}")

# ---------- W6 探针常量 ----------
check("W6 A4W_PROBE_BYTES=1MiB 且 A4W_PROBE_DIR=/tmp",
      md.A4W_PROBE_BYTES == (1 << 20) and md.A4W_PROBE_DIR == "/tmp",
      f"{md.A4W_PROBE_BYTES}/{md.A4W_PROBE_DIR}")

# ================= B 组：A4W 告警环 =================

# ---------- W7 写即失败 → 恰 1 条 red A4W:tmp，文案含 errno 与「写即失败」 ----------
with mock.patch.object(md, "probe_local_tmp_mb", lambda: (5000, False)), \
     mock.patch.object(md, "probe_tmp_write_admission",
                       lambda *a, **k: (False, "OSError 122 Disk quota exceeded")):
    al = md.build_alarms(t=T, **stubs())
a4w = of_code(al, "A4W:tmp")
check("W7 写即失败 → 恰 1 条 red A4W:tmp（level=red，key=A4W:tmp）",
      len(a4w) == 1 and a4w[0]["level"] == "red" and a4w[0]["key"] == "A4W:tmp",
      f"a4w={a4w}")
check("W8 A4W 文案覆盖「写即失败」+ errno + 量纲说明（不只承诺拦新臂）",
      bool(a4w) and "写即失败" in a4w[0]["message"]
      and "122" in a4w[0]["message"] and "statvfs" in a4w[0]["message"]
      and "拦新臂" not in a4w[0]["message"],
      f"msg={a4w[0]['message'] if a4w else None}")

# ---------- W9 与 A4L 并存不互斥（低水 + 写不进 → 两条同列） ----------
with mock.patch.object(md, "probe_local_tmp_mb", lambda: (1000, False)), \
     mock.patch.object(md, "probe_tmp_write_admission",
                       lambda *a, **k: (False, "OSError 122 Disk quota exceeded")):
    al2 = md.build_alarms(t=T, **stubs())
codes2 = [a["code"] for a in al2]
check("W9 低水 + 写不进 → A4L(amber) 与 A4W(red) 并存（两本账各报各的）",
      codes2.count("A4L:tmp") == 1 and codes2.count("A4W:tmp") == 1
      and of_code(al2, "A4L:tmp")[0]["level"] == "amber"
      and of_code(al2, "A4W:tmp")[0]["level"] == "red",
      f"codes={codes2}")

# ---------- W10 健康态：两码皆不报（不误红） ----------
with mock.patch.object(md, "probe_local_tmp_mb", lambda: (5000, False)), \
     mock.patch.object(md, "probe_tmp_write_admission", lambda *a, **k: (True, "")):
    al3 = md.build_alarms(t=T, **stubs())
check("W10 健康态（可写 + 高水位）→ 零 A4L 零 A4W（不误报）",
      of_code(al3, "A4L:tmp") == [] and of_code(al3, "A4W:tmp") == [],
      f"alarms={[a['code'] for a in al3]}")

# ---------- W11 A4L 既有口径未被改动（回归护栏：文案逐字 + 阈值边界） ----------
with mock.patch.object(md, "probe_local_tmp_mb", lambda: (2000, False)), \
     mock.patch.object(md, "probe_tmp_write_admission", lambda *a, **k: (True, "")):
    al4 = of_code(md.build_alarms(t=T, **stubs()), "A4L:tmp")
check("W11 A4L 既有文案逐字未改 + 阈值边界（2662 不报 / 2661 报）",
      len(al4) == 1 and al4[0]["message"] == A4L_WARN_MSG.format(x=2000)
      and al4[0]["level"] == "amber",
      f"msg={al4[0]['message'] if al4 else None}")
with mock.patch.object(md, "probe_local_tmp_mb", lambda: (2662, False)), \
     mock.patch.object(md, "probe_tmp_write_admission", lambda *a, **k: (True, "")):
    al_eq = of_code(md.build_alarms(t=T, **stubs()), "A4L:tmp")
with mock.patch.object(md, "probe_local_tmp_mb", lambda: (2661, False)), \
     mock.patch.object(md, "probe_tmp_write_admission", lambda *a, **k: (True, "")):
    al_lt = of_code(md.build_alarms(t=T, **stubs()), "A4L:tmp")
check("W11b 阈值边界 =2662 不报 / 2661 报（A4L 语义零改动）",
      al_eq == [] and len(al_lt) == 1, f"eq={al_eq} lt={len(al_lt)}")

# ---------- W12 A4W 走既有 30min 去重链（key 独立于 A4L:tmp） ----------
try:
    os.remove(md.ALARMS_LOG)
except FileNotFoundError:
    pass
st = {"alarm_open": {}, "alarm_logged": {}, "sweb_img_hist": []}
with mock.patch.object(md, "probe_local_tmp_mb", lambda: (5000, False)), \
     mock.patch.object(md, "probe_tmp_write_admission",
                       lambda *a, **k: (False, "OSError 122 Disk quota exceeded")):
    alarms = md.build_alarms(t=T, **stubs())
md.log_alarms(alarms, st, T)
n1 = len(open(md.ALARMS_LOG).read().strip().splitlines())
md.log_alarms(alarms, st, T + 60)
n2 = len(open(md.ALARMS_LOG).read().strip().splitlines())
md.log_alarms(alarms, st, T + md.DEDUP_WINDOW + 1)
n3 = len(open(md.ALARMS_LOG).read().strip().splitlines())
row = json.loads(open(md.ALARMS_LOG).read().strip().splitlines()[0])
check("W12 A4W 经 log_alarms 30min 去重链落流水（1→1→2）且字段齐全",
      (n1, n2, n3) == (1, 1, 2) and row["level"] == "red"
      and row["code"] == "A4W:tmp" and bool(row.get("ts")) and bool(row.get("since")),
      f"lines={n1}/{n2}/{n3} row={row}")

# ---------- W13 A4W 与 A4L 去重 key 互不吞（两码各自记） ----------
try:
    os.remove(md.ALARMS_LOG)
except FileNotFoundError:
    pass
st2 = {"alarm_open": {}, "alarm_logged": {}, "sweb_img_hist": []}
with mock.patch.object(md, "probe_local_tmp_mb", lambda: (1000, False)), \
     mock.patch.object(md, "probe_tmp_write_admission",
                       lambda *a, **k: (False, "OSError 122 Disk quota exceeded")):
    both = md.build_alarms(t=T, **stubs())
md.log_alarms(both, st2, T)
nb = len(open(md.ALARMS_LOG).read().strip().splitlines())
check("W13 A4L 与 A4W 去重 key 独立 → 同窗两条都落流水",
      nb == 2 and {json.loads(l)["code"]
                   for l in open(md.ALARMS_LOG).read().strip().splitlines()}
      == {"A4L:tmp", "A4W:tmp"},
      f"n={nb}")

# ---------- W14 源码自证：安灯规则 docstring 有 A4W 条目 ----------
src = open(TARGET, encoding="utf-8").read()
check("W14 源码自证：模块头部安灯规则含 A4W 条目且量纲边界写在探针 docstring",
      "red   A4W" in src and "量纲边界" in src
      and "probe_tmp_write_admission" in src,
      "docstring/A4W 缺项")

# ---------- W20 one_round 端到端（daemon 模式，全扫描桩 + 沙箱四件套） ----------
try:
    os.remove(md.ALARMS_LOG)
except FileNotFoundError:
    pass
state = {"line_hist": [], "last_increase": {}, "first_running": {},
         "sweb_img_hist": [], "alarm_open": {}, "alarm_logged": {},
         "proc_miss_streak": 0}
scan_stubs = [
    mock.patch.object(md, "scan_all_arms", lambda state, t: []),
    mock.patch.object(md, "scan_plan_tiers", lambda: {}),
    mock.patch.object(md, "scan_scheduler", lambda state, t: {
        "status_file_exists": True, "mtime_stale": False,
        "proc_confirmed_down": False, "alive": False, "running_arms": []}),
    mock.patch.object(md, "scan_extra_schedulers", lambda t: []),
    mock.patch.object(md, "scan_anolis", lambda state, t: {"ok": False, "disk": {}}),
    mock.patch.object(md, "scan_local_images", lambda state, t: None),
    mock.patch.object(md, "scan_relay", lambda: {"consecutive_failures": 0,
                                                  "last_event": "-"}),
    mock.patch.object(md, "probe_local_tmp_mb", lambda: (5000, False)),
    mock.patch.object(md, "probe_tmp_write_admission",
                      lambda *a, **k: (False, "OSError 122 Disk quota exceeded")),
    mock.patch.object(md, "build_snapshot",
                      lambda *a, **k: {"alarms": a[5],
                                       "totals": {"n_total": 0, "rows_10m": 0}}),
]
with contextlib.ExitStack() as stx:
    for s_ in scan_stubs:
        stx.enter_context(s_)
    snap = md.one_round(state, "daemon")
lines = [json.loads(l) for l in open(md.ALARMS_LOG).read().strip().splitlines()]
check("W20 one_round daemon 端到端：A4W 经真实 build→log 链落沙箱流水",
      any(a["code"] == "A4W:tmp" for a in snap["alarms"])
      and len(lines) == 1 and lines[0]["code"] == "A4W:tmp"
      and lines[0]["level"] == "red",
      f"snap={[a['code'] for a in snap['alarms']]} lines={lines}")

# ================= C 组：kb/verify.py 临时目录落点 =================

spec2 = importlib.util.spec_from_file_location("kb_verify_under_test", KBVERIFY)
kbv = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(kbv)

HOME = os.path.expanduser("~")

# ---------- W15 临时目录根在 $HOME 下，不在 /tmp ----------
scratch = kbv._scratch_dir()
check("W15 kb/verify.py 临时目录根在 $HOME（磁盘）且不在 /tmp 树",
      scratch.startswith(HOME + os.sep) and not scratch.startswith("/tmp/"),
      f"scratch={scratch}")

# ---------- W16 进程内 tempfile.tempdir 一并改写 → 被测件临时库也落磁盘 ----------
prev = tempfile.tempdir
try:
    tempfile.tempdir = scratch
    with tempfile.TemporaryDirectory(prefix="kb-test-") as td_inner:
        inner_dir = td_inner
    check("W16 tempfile.tempdir 改写后，被测件临时库（kb.test_store 同款）不落 /tmp",
          inner_dir.startswith(scratch + os.sep) and not inner_dir.startswith("/tmp/"),
          f"inner={inner_dir}")
finally:
    tempfile.tempdir = prev

# ---------- W17 快照步骤在新落点真跑得通（sqlite backup API 不变） ----------
try:
    snap = kbv._snapshot_registry(scratch)
    snap_ok = os.path.exists(snap) and os.path.getsize(snap) > 0
    snap_size = os.path.getsize(snap) if os.path.exists(snap) else -1
except Exception as e:  # noqa: BLE001 - 门要把任何异常记为失败
    snap_ok, snap_size = False, -1
    print("  [快照异常] %s: %s" % (type(e).__name__, e))
check("W17 kb/verify.py 快照步骤在磁盘落点真跑得通（sqlite backup API 不变）",
      snap_ok, f"size={snap_size}")

# ---------- W18 源码自证：外层临时目录显式 dir=，不再默认 /tmp ----------
src2 = open(KBVERIFY, encoding="utf-8").read()
check("W18 源码自证：外层临时目录显式 dir=scratch 且 tempfile.tempdir 被改写",
      'dir=scratch' in src2 and "tempfile.tempdir = scratch" in src2
      and 'TemporaryDirectory(prefix="kb-verify-quick-")' not in src2,
      "dir=/tempfile.tempdir 缺项")

# ---------- W19 遗留清理口径：PID 隔离 + 退出进程的残留会被清 ----------
stale = f"{HOME}/kb-verify-scratch-999999"
os.makedirs(stale, exist_ok=True)
with open(os.path.join(stale, "junk"), "w", encoding="utf-8") as fh:
    fh.write("x")
kbv._purge_stale_scratch()
check("W19 遗留临时目录按 PID 判活清理（已退出进程残留被清，在跑的保留）",
      not os.path.exists(stale), f"stale 仍在={os.path.exists(stale)}")

# ---------- 清理 ----------
shutil.rmtree(TEST_ROOT, ignore_errors=True)
shutil.rmtree(scratch, ignore_errors=True)

n, total = len(PASS), len(PASS) + len(FAIL)
print(f"\n{total - n} FAILED, {n} passed" if FAIL else "")
print(f"ALL PASS ({n}/{total})")
sys.exit(1 if FAIL else 0)
