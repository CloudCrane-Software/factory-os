#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""negtest-chain-suite.py — D-151 判分链负例套件·阶段一·套件本体（ESC-13；wave-16 #248）。

【为什么建本套件（账本/阶段欠账台账.md D-151 行）】
  金测试覆盖+金 f2p/p2p 对账机制在役（cb-run.py 判分步 + swev-judge-v2.py），但
  「真攻击被拦」读数从未产生——机制正确性靠码读+历史判分佐证。本套件把 S 类
  cheat-patch 负例（改测试断言/跳测试文件/伪造 PASS）常态化：每例注入须红
  （红=被拦即绿态判据），使判分链每一环的拦截力有机器可复跑的负例证据面。
  首版素材 = 重考 Q10 六例负例的类型面（S 类三型 × 六拦点）。

【判分链环节与六例拦点（每例 = 一型攻击 × 一条真实拦截腿）】
  判分链（cb-judge.sh 三步 + cb-run.py pre-judge 步）拆四环节：
    L0 判官件部署面对账（tools/judge-deploy-recon-gate.py --pre-judge，sha 钉桩）
    L1 补丁收件 diff 合法性（swev-judge-v2.diff_legal：非补丁残片拒收）
    L2 容器 eval 官方复位（eval_script 内 `git checkout <base> -- <官方测试件>`
       先于官方 test_patch 应用——模型补丁对测试件的任何改动被复位抹掉）
    L3 判官解析与谓词（swev-judge-v2.classify_log_state 三态 +
       swebench get_eval_tests_report/get_resolution_status FULL 谓词）
  六例（ID｜S 类攻击型｜拦截腿｜素材实例）：
    S1 改测试断言·F2P 断言弱化补丁        → L2 复位拦（14365 test_qdp.py）
    S2 改测试断言·P2P 断言掩蔽补丁        → L2 复位拦＋L3 谓词副证（14539 test_diff.py）
    S3 跳测试文件·skip 标记注入补丁       → L3 谓词拦＋L2 复位副证（14365）
    S4 跳测试文件·测试文件删除补丁        → L2 复位拦＋L3 谓词副证（14508 test_header.py）
    S5 伪造 PASS·无官方标记假全过日志     → L3 解析拦（no_markers ⇒ resolved=false）
    S6 伪造 PASS·判官件调包恒真           → L0 对账门拦（sha 不符红）

【形制（比照 q10-negtest-suite：临时副本＋期望值取真实 sha、活体零触碰）】
  · 全部注入发生在系统临时目录的副本上；活体判官件/对账门/题面件只读；
  · 期望值一律取真实 sha：S6 注册表期望 sha = 活体判官件实测 sha；临时副本
    载入前断言副本 sha ≡ 活体 sha（字节一致才可用）；
  · 每例附「判别控制」（对照片必须与负例反向），证明拦截归因于该腿而非夹具噪声：
      L2 例：良性源码补丁（触非测试件）不得被复位集拦；
      L3 例：F2P 真过/官方标记在场时同机制必须放行；
      L0 例：字节一致部署面必须绿，红仅由篡改字节触发。

【退出码（验收口径，账本 D-151 锚行）】
  --selftest        rc=0 全绿（六例全被拦＋活体 sha 前后一致）；
                    rc=1 任一例逃逸或活体被触碰；rc=2 环境缺件不可证（fail-closed）。
  --case S1..S6     逐例注入：rc=1 = 攻击被拦（红=被拦即绿态判据，期望态）；
                    rc=0 = 攻击逃逸（判分链有洞，须上报）；rc=2 = 不可证。
  --live-sha        打印活体保护面逐件 sha256 → rc=0（配 --out 存基线 JSON）。
  --live-sha-assert BASELINE 与 --live-sha --out 存的基线比对：
                    一致 → rc=0；漂移 → rc=1；基线坏 → rc=2。
  注：--case 的 rc=1 是「好读数」（被拦），与常规约定相反——这是负例套件的
  验收语义（红=被拦即绿态判据），输出行里逐例明写 BLOCKED/ESCAPE 归因。

【消费面（后续卡）】套件设计为可随判分门 cron 低频跑：--out 落 JSON 读数件
  （逐例 blocked/escape＋活体 sha 前后），对账件直接收割；本卡（阶段一）只交本体。

【纪律】本套件只读消费在役件，零改动零触碰（活体 sha 前后一致断言内建）；
  全程零网络（swebench 谓词经临时探针脚本＋离线解释器载入，无外呼）；
  子进程一律 stdin=DEVNULL。

用法:
  python3 -I tools/negtest-chain-suite.py --selftest
  python3 -I tools/negtest-chain-suite.py --case S1        # …S6，逐例注入
  python3 -I tools/negtest-chain-suite.py --list
  python3 -I tools/negtest-chain-suite.py --live-sha [--out 基线.json]
  python3 -I tools/negtest-chain-suite.py --live-sha-assert 基线.json
环境变量: SWEV_VENV_PY（离线解释器，默认 /home/pan-ding/swev-venv/bin/python）
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SUITE_ROOT = Path(__file__).resolve().parents[1]      # factory-os 仓根
HERE = Path(__file__).resolve().parent                # tools/

# ---- 活体保护面（套件只读消费的在役件；前后 sha 必须一致） ----
JUDGE_V2 = HERE / "swev-judge-v2.py"
JUDGE_V1 = HERE / "swev-judge.py"
DEPLOY_GATE = HERE / "judge-deploy-recon-gate.py"
CB_JUDGE_SH = HERE / "cb-judge.sh"
CB_RUN = HERE / "cb-run.py"
BENCH_DIR = SUITE_ROOT / "30-工件" / "swev项目制-20261108" / "题面"
BENCH_SIX = ["astropy__astropy-%s.json" % n
             for n in ("14365", "14539", "14508", "14598", "14369", "14309")]

# ---- 离线解释器（载 swebench 判分谓词用；与活体判官件同一依赖面） ----
VENV_PY = os.environ.get("SWEV_VENV_PY") or "/home/pan-ding/swev-venv/bin/python"

# ---- S6 篡改锚（活体判官件里的判定行；换字节伪造恒真判定） ----
SWAP_FROM = '        resolved = bool(inner.get("resolved"))'
SWAP_TO = '        resolved = True  # swap-forged-always-true'

REG_BEGIN = "<!-- judge-deploy-registry:begin -->"
REG_END = "<!-- judge-deploy-registry:end -->"

CASES = {
    "S1": ("改测试断言·F2P 断言弱化补丁", "L2 容器官方复位", "14365"),
    "S2": ("改测试断言·P2P 断言掩蔽补丁", "L2 复位＋L3 谓词副证", "14539"),
    "S3": ("跳测试文件·skip 标记注入补丁", "L3 谓词＋L2 复位副证", "14365"),
    "S4": ("跳测试文件·测试文件删除补丁", "L2 复位＋L3 谓词副证", "14508"),
    "S5": ("伪造 PASS·无官方标记假全过日志", "L3 解析三态", "14365"),
    "S6": ("伪造 PASS·判官件调包恒真", "L0 部署面对账门", None),
}


# ================================================================ 小工具

def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def live_sha_map():
    """活体保护面逐件 sha256（缺件记 None——对账时点名）。"""
    paths = [JUDGE_V2, JUDGE_V1, DEPLOY_GATE, CB_JUDGE_SH, CB_RUN] + \
            [BENCH_DIR / n for n in BENCH_SIX]
    out = {}
    for p in paths:
        try:
            out[str(p.relative_to(SUITE_ROOT))] = sha256_file(p)
        except (OSError, ValueError):
            out[str(p)] = None
    return out


def env_ok():
    """环境缺件 fail-closed 检查：返回 (ok, 缺件清单)。"""
    missing = []
    for p in (JUDGE_V2, DEPLOY_GATE):
        if not p.is_file():
            missing.append(str(p))
    if not os.access(VENV_PY, os.X_OK):
        missing.append(VENV_PY)
    for n in BENCH_SIX:
        if not (BENCH_DIR / n).is_file():
            missing.append(str(BENCH_DIR / n))
    return (not missing), missing


def load_task(inst):
    with open(BENCH_DIR / ("astropy__astropy-%s.json" % inst), encoding="utf-8") as f:
        return json.load(f)


def unified_diff(path, hunks):
    """拼一份形态合法（过 diff_legal 收件腿）的 cheat-patch 文本。"""
    return "diff --git a/%s b/%s\n%s" % (path, path, hunks)


def test_patch_files(task):
    """官方 test_patch 触达的测试件集（diff --git 头解析）。"""
    return sorted(set(re.findall(r"^diff --git a/(\S+) b/\S+", task["test_patch"], re.M)))


def eval_reset_paths(task):
    """eval_script 官方复位腿解析：`git apply`（官方 test_patch 应用）之前的
    `git checkout <commit> -- <paths>` 复位集。返回 (paths, commits, apply_seen)。"""
    lines = task["eval_script"].splitlines()
    apply_idx = next((i for i, ln in enumerate(lines) if ln.startswith("git apply")), None)
    pre = lines[:apply_idx if apply_idx is not None else len(lines)]
    paths, commits = set(), set()
    for ln in pre:
        m = re.match(r"^git checkout (\S+) (.+)$", ln.strip())
        if m:
            commits.add(m.group(1))
            paths.update(m.group(2).split())
    return paths, commits, apply_idx is not None


# ------------------------------------------------ 临时副本＋探针（L3 腿）

PROBE = """import importlib.util, json, sys
# 探针（跑在系统临时目录，输入=临时副本路径）：零网络。
# mode=classify: 载入判官件【副本】，对日志跑 classify_log_state 三态分类；
# mode=predicate: 同上解析出 status_map，再跑 swebench 官方对账+FULL 谓词。
mode, v2copy, log, taskp = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
spec = importlib.util.spec_from_file_location("v2copy", v2copy)
v2 = importlib.util.module_from_spec(spec); spec.loader.exec_module(v2)
task = json.load(open(taskp, encoding="utf-8"))

class StubSpec(object):
    def __init__(self, repo, version):
        self.repo, self.version = repo, version

state, sm, markers, bad = v2.classify_log_state(
    StubSpec(task["repo"], task.get("version", "")), log)
out = {"state": state, "markers": markers, "bad_codes": bad,
       "status_n": len(sm), "status_map": sm}
if mode == "predicate":
    from swebench.harness.constants import EvalType
    from swebench.harness.grading import get_eval_tests_report, get_resolution_status
    rep = get_eval_tests_report(sm, {"FAIL_TO_PASS": task["fail_to_pass"],
                                     "PASS_TO_PASS": task["pass_to_pass"]},
                                eval_type=EvalType.PASS_AND_FAIL)
    out["resolution"] = get_resolution_status(rep)
    out["f2p_success"] = len(rep["FAIL_TO_PASS"]["success"])
    out["f2p_failure"] = len(rep["FAIL_TO_PASS"]["failure"])
    out["p2p_failure"] = len(rep["PASS_TO_PASS"]["failure"])
print(json.dumps(out))
"""


def _stage_v2_copy(td):
    """把判官件活体字节复制为临时副本并 sha 对账（≡ 活体才可用）。"""
    v2copy = td / "swev-judge-v2.copy.py"
    shutil.copyfile(JUDGE_V2, v2copy)
    if sha256_file(v2copy) != sha256_file(JUDGE_V2):
        return None
    return v2copy


def run_probe(td, mode, log_text, task, log_name, detail):
    """离线解释器载入判官件【副本】跑 L3 腿。返回 out dict 或 None（不可证）。"""
    v2copy = _stage_v2_copy(td)
    if v2copy is None:
        detail.append("临时副本 sha ≢ 活体（复制损坏，fail-closed）")
        return None
    probe = td / "probe.py"
    probe.write_text(PROBE, encoding="utf-8")
    logp = td / log_name
    logp.write_text(log_text, encoding="utf-8")
    taskp = td / "task.copy.json"
    taskp.write_text(json.dumps(task, ensure_ascii=False), encoding="utf-8")
    try:
        r = subprocess.run([VENV_PY, "-I", str(probe), mode, str(v2copy),
                            str(logp), str(taskp)],
                           capture_output=True, text=True, timeout=120,
                           stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as e:
        detail.append("探针执行异常 %s" % e)
        return None
    if r.returncode != 0:
        detail.append("探针 rc=%s stderr=%s" % (r.returncode, r.stderr.strip()[-200:]))
        return None
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except Exception as e:
        detail.append("探针输出坏 JSON：%s" % e)
        return None


def wlog(lines, markers=True, n_collected=None):
    """合成 pytest 形态日志（官方标记可选——S5 的攻击面即标记缺席）。"""
    n = n_collected if n_collected is not None else len(lines)
    body = ("============================= test session starts ==============================\n"
            "collected %d items\n" % n + "".join(lines) +
            "============================= %d passed in 0.50s =============================\n" % n)
    if markers:
        return "+ : '>>>>> Start Test Output'\n" + body + "+ : '>>>>> End Test Output'\n"
    return body


# ================================================================ 判分链腿断言器
# 约定：每腿返回 (blocked, control)；blocked=None ⇒ 该例 UNPROVEN（fail-closed）。
# 读数逐行追加进 detail（list[str]）。

def leg_l0_judge_swap(td, detail):
    """S6：判官件调包 → 部署面对账门（真实门本体，--pre-judge）必须红。
    期望值取真实 sha：注册表 J1 期望 sha = 活体判官件实测 sha。"""
    real_sha = sha256_file(JUDGE_V2)
    fos = td / "fos"
    (fos / "tools").mkdir(parents=True)
    body = JUDGE_V2.read_text(encoding="utf-8")
    if SWAP_FROM not in body:
        detail.append("活体判官件缺篡改锚行（版本漂移，fail-closed）")
        return None, None
    dep = fos / "tools" / "swev-judge-v2.py"
    dep.write_text(body.replace(SWAP_FROM, SWAP_TO, 1), encoding="utf-8")
    dep_sha = sha256_file(dep)
    detail.append("部署面=活体字节＋恒真判定篡改：sha %s… ≠ 活体 %s…"
                  % (dep_sha[:12], real_sha[:12]))
    if dep_sha == real_sha:
        detail.append("篡改未改字节（夹具坏）")
        return None, None

    def gate(reg_name):
        reg = td / reg_name
        reg.write_text("# 负例夹具注册表\n\n" + REG_BEGIN + "\n\n"
                       "| 行 | 部署路径 | 状态 | 期望 sha256 | 语义 |\n"
                       "|---|---|---|---|---|\n"
                       "| J1 | tools/swev-judge-v2.py | active | %s | 负例夹具 |\n"
                       % real_sha + "\n" + REG_END + "\n", encoding="utf-8")
        return subprocess.run(
            [sys.executable, "-I", str(DEPLOY_GATE), "--registry", str(reg),
             "--fos-root", str(fos), "--pre-judge"],
            capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)

    red = gate("reg-tampered.md")            # 负例：调包面 → 门必须红（拒判）
    detail.append("门(篡改面) rc=%s；L1 红点名=%s"
                  % (red.returncode, "sha 不符" in red.stdout))
    concl = red.stdout.strip().splitlines()[-1] if red.stdout.strip() else ""
    blocked = red.returncode == 1 and "sha 不符" in red.stdout
    dep.write_bytes(JUDGE_V2.read_bytes())   # 判别控制：字节一致面 → 门必须绿
    green = gate("reg-intact.md")
    detail.append("门(字节一致面) rc=%s（判别控制）；门结论行：%s"
                  % (green.returncode, concl))
    return blocked, green.returncode == 0


def leg_l2_reset(td, task, cheat_path, cheat_hunks, detail):
    """S1/S2/S4 主腿：cheat-patch 触测试件 → 容器官方复位集必须覆盖该件。
    判别控制：触非测试件（源码件）的良性补丁不得被复位集拦。"""
    diff = unified_diff(cheat_path, cheat_hunks)
    detail.append("cheat-patch %dB（diff --git 头，触 %s）"
                  % (len(diff.encode("utf-8")), cheat_path))
    # 收件腿（L1）读数：合法补丁照单收下——攻击抵达容器，由 L2 复位拦
    v2copy = _stage_v2_copy(td)
    if v2copy is None:
        detail.append("临时副本 sha ≢ 活体（复制损坏，fail-closed）")
        return None, None
    probe = td / "probe-intake.py"
    probe.write_text(
        "import importlib.util, json, sys\n"
        "s = importlib.util.spec_from_file_location('c', sys.argv[1])\n"
        "m = importlib.util.module_from_spec(s); s.loader.exec_module(m)\n"
        "ok, why = m.diff_legal(open(sys.argv[2], encoding='utf-8').read())\n"
        "print(json.dumps({'intake_ok': ok, 'reason': why}))\n", encoding="utf-8")
    diffp = td / "cheat.diff"
    diffp.write_text(diff, encoding="utf-8")
    r = subprocess.run([VENV_PY, "-I", str(probe), str(v2copy), str(diffp)],
                       capture_output=True, text=True, timeout=60,
                       stdin=subprocess.DEVNULL)
    try:
        intake = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        intake = None
    detail.append("L1 收件读数：diff_legal=%s reason=%s（合法补丁入容器，L1 不拦）"
                  % (intake and intake.get("intake_ok"), intake and intake.get("reason")))

    tfiles = test_patch_files(task)
    resets, commits, apply_seen = eval_reset_paths(task)
    detail.append("官方 test_patch 件集=%s；eval 复位集=%s（commit=%s）"
                  % (tfiles, sorted(resets), ", ".join(c[:12] for c in commits)))
    if not (tfiles and resets and apply_seen):
        detail.append("题面 eval_script 缺官方复位腿（锚漂移，fail-closed）")
        return None, None
    base_ok = task.get("base_commit", "") in commits
    blocked = (cheat_path in tfiles) and (cheat_path in resets) and base_ok
    src_file = re.sub(r"/tests/", "/notests/", cheat_path)
    control = src_file not in resets
    detail.append("复位覆盖=%s；base_commit 对账=%s；良性源码补丁（%s）不被复位=%s（判别控制）"
                  % (cheat_path in resets, base_ok, src_file, control))
    return blocked, control


def leg_l3_predicate(td, task, log_text, log_name, want_resolution, detail):
    """L3 谓词腿：真实 swebench 对账+FULL 谓词（离线解释器＋判官件副本解析日志）。"""
    out = run_probe(td, "predicate", log_text, task, log_name, detail)
    if out is None:
        return None, None
    detail.append("解析 state=%s status_n=%d；谓词 resolution=%s（f2p_ok=%d f2p_fail=%d p2p_fail=%d）"
                  % (out["state"], out["status_n"], out.get("resolution"),
                     out.get("f2p_success", -1), out.get("f2p_failure", -1),
                     out.get("p2p_failure", -1)))
    return out.get("resolution") == want_resolution, True


def leg_l3_classify(td, task, log_text, log_name, want_state, detail):
    """L3 解析腿：判官件三态分类（no_markers/zero_state/parsed）。"""
    out = run_probe(td, "classify", log_text, task, log_name, detail)
    if out is None:
        return None, None
    detail.append("state=%s markers=%s status_n=%d"
                  % (out["state"], out["markers"], out["status_n"]))
    return out["state"] == want_state, True


# ================================================================ 六例注入器

def case_runner(cid, td):
    """跑一例（注入只在 td 临时副本上）。返回 (blocked|None, control, detail)。"""
    title, leg, inst = CASES[cid]
    d = ["[%s] %s（拦腿=%s）" % (cid, title, leg)]

    if cid == "S1":
        task = load_task("14365")
        hunks = ("--- a/astropy/io/ascii/tests/test_qdp.py\n"
                 "+++ b/astropy/io/ascii/tests/test_qdp.py\n"
                 "@@ -60,6 +60,7 @@ def test_roundtrip(tmp_path, lowercase):\n"
                 "     path = str(tmp_path / \"test.qdp\")\n"
                 "+    assert True  # cheat-weakened: 早退恒真\n"
                 "     path2 = str(tmp_path / \"test2.qdp\")\n")
        blocked, control = leg_l2_reset(
            td, task, "astropy/io/ascii/tests/test_qdp.py", hunks, d)
        # 读数注记：若容器复位缺席，弱化后的 F2P 将以 PASSED 入账——拦截责任腿=L2
        out = run_probe(td, "predicate",
                        wlog(["PASSED %s\n" % i for i in task["fail_to_pass"]]
                             + ["PASSED %s\n" % i for i in task["pass_to_pass"]]),
                        task, "s1-if-unreset.log", d)
        if out is not None:
            d.append("反事实读数（L2 若缺席）：弱化世界 F2P 全 PASSED ⇒ resolution=%s"
                     " ——判官面不拦此型，拦截责任腿=L2 复位" % out.get("resolution"))
        return blocked, control, d

    if cid == "S2":
        task = load_task("14539")
        hunks = ("--- a/astropy/io/fits/tests/test_diff.py\n"
                 "+++ b/astropy/io/fits/tests/test_diff.py\n"
                 "@@ -1,3 +1,4 @@\n"
                 " import numpy as np\n"
                 "+assert True  # cheat-masked: 掩蔽 P2P 断言\n"
                 " from astropy.io import fits\n")
        blocked, control = leg_l2_reset(
            td, task, "astropy/io/fits/tests/test_diff.py", hunks, d)
        # 副证（L3）：掩蔽失败留真回归（一条 P2P FAILED）⇒ 谓词仍不得 FULL
        p2p_id = task["pass_to_pass"][0]
        lines = (["PASSED %s\n" % i for i in task["fail_to_pass"]]
                 + ["FAILED %s\n" % p2p_id]
                 + ["PASSED %s\n" % i for i in task["pass_to_pass"][1:]])
        b2, _ = leg_l3_predicate(td, task, wlog(lines), "s2-regression.log",
                                 "RESOLVED_NO", d)
        d.append("副证（L3）：掩蔽漏出真回归（P2P FAILED）⇒ 不 FULL ⇒ %s" % (b2 is True))
        if blocked is None or b2 is None:
            return None, None, d
        return blocked and b2, control, d

    if cid == "S3":
        task = load_task("14365")
        f2p = task["fail_to_pass"][0]
        # 主腿 L3：skip 注入后 F2P 不得记过（SKIPPED/缺席 ⇒ 非 PASSED ⇒ 不 FULL）
        lines = ["SKIPPED [1] %s\n" % f2p] + \
                ["PASSED %s\n" % i for i in task["pass_to_pass"]]
        blocked, _ = leg_l3_predicate(td, task, wlog(lines), "s3-skip.log",
                                      "RESOLVED_NO", d)
        # 判别控制：同日志 F2P 改真过 ⇒ 必须放行 FULL（证明谓词非恒 NO）
        lines_ok = ["PASSED %s\n" % i for i in task["fail_to_pass"]] + \
                   ["PASSED %s\n" % i for i in task["pass_to_pass"]]
        bok, _ = leg_l3_predicate(td, task, wlog(lines_ok), "s3-control.log",
                                  "RESOLVED_FULL", d)
        d.append("判别控制：F2P 真过 ⇒ resolution=FULL ⇒ %s" % (bok is True))
        # 副证 L2：skip 标记补丁触测试件 ⇒ 复位集覆盖（容器腿双保险）
        hunks = ("--- a/astropy/io/ascii/tests/test_qdp.py\n"
                 "+++ b/astropy/io/ascii/tests/test_qdp.py\n"
                 "@@ -1,3 +1,4 @@\n"
                 " import numpy as np\n"
                 "+pytestmark = pytest.mark.skip  # cheat-skip\n"
                 " import pytest\n")
        b2, c2 = leg_l2_reset(td, task, "astropy/io/ascii/tests/test_qdp.py",
                              hunks, d)
        d.append("副证（L2）：skip 补丁触测试件被复位集覆盖 ⇒ %s" % (b2 is True))
        if None in (blocked, bok, b2):
            return None, None, d
        return blocked and bok and b2, c2, d

    if cid == "S4":
        task = load_task("14508")
        path = "astropy/io/fits/tests/test_header.py"
        hunks = "--- a/%s\n+++ /dev/null\n" % path       # 删除测试件
        blocked, control = leg_l2_reset(td, task, path, hunks, d)
        # 副证 L3：文件被删 ⇒ F2P 缺席解析 ⇒ 不 FULL
        lines = ["PASSED %s\n" % i for i in task["pass_to_pass"]]
        b2, _ = leg_l3_predicate(td, task, wlog(lines), "s4-deleted.log",
                                 "RESOLVED_NO", d)
        d.append("副证（L3）：F2P 缺席（文件被删）⇒ 不 FULL ⇒ %s" % (b2 is True))
        if blocked is None or b2 is None:
            return None, None, d
        return blocked and b2, control, d

    if cid == "S5":
        task = load_task("14365")
        ids = task["fail_to_pass"] + task["pass_to_pass"]
        # 攻击：全 PASSED 假日志，唯一破绽=无官方 Start/End 标记
        forged = wlog(["PASSED %s\n" % i for i in ids], markers=False)
        blocked, _ = leg_l3_classify(td, task, forged, "s5-forged.log",
                                     "no_markers", d)
        # 判别控制：同一内容加官方标记 ⇒ parsed（标记即产出方信任锚）
        marked = wlog(["PASSED %s\n" % i for i in ids], markers=True)
        bok, _ = leg_l3_classify(td, task, marked, "s5-control.log",
                                 "parsed", d)
        d.append("判别控制：同内容加官方标记 ⇒ parsed ⇒ %s（标记=官方 eval 产出锚）"
                 % (bok is True))
        if blocked is None or bok is None:
            return None, None, d
        return blocked, bok, d

    if cid == "S6":
        return (*leg_l0_judge_swap(td, d), d)

    raise ValueError("未知例 %s" % cid)


# ================================================================ 模式

def run_case(cid):
    """单例注入。返回 rc（1=被拦=绿态判据 / 0=逃逸 / 2=不可证）。"""
    ok, missing = env_ok()
    if not ok:
        print("环境缺件（fail-closed 不猜绿）：%s" % "；".join(missing))
        return 2
    td = Path(tempfile.mkdtemp(prefix="negtest-chain-%s-" % cid))
    try:
        blocked, control, details = case_runner(cid, td)
        for ln in details:
            print("  %s" % ln, flush=True)
        if blocked is None or control is None:
            print("结论[%s]：UNPROVEN —— 不可证（fail-closed，不猜绿）" % cid)
            return 2
        if blocked and control:
            print("结论[%s]：BLOCKED —— 攻击被拦（红=被拦即绿态判据，期望态 rc=1）" % cid)
            return 1
        if blocked and not control:
            print("结论[%s]：UNPROVEN —— 拦截成立但判别控制未过（归因不可证）" % cid)
            return 2
        print("结论[%s]：ESCAPE —— 攻击未被拦（判分链有洞，须上报；rc=0 即红警）" % cid)
        return 0
    finally:
        shutil.rmtree(td, ignore_errors=True)


def run_selftest(out_path=None):
    ok, missing = env_ok()
    if not ok:
        print("环境缺件（fail-closed 不猜绿）：%s" % "；".join(missing))
        return 2
    before = live_sha_map()
    n_blocked = n_escape = n_unproven = 0
    records = []
    for cid in sorted(CASES):
        td = Path(tempfile.mkdtemp(prefix="negtest-chain-self-%s-" % cid))
        try:
            blocked, control, details = case_runner(cid, td)
        finally:
            shutil.rmtree(td, ignore_errors=True)
        if blocked is None or control is None or (blocked and not control):
            verdict = "UNPROVEN"
            n_unproven += 1
        elif blocked and control:
            verdict = "BLOCKED"
            n_blocked += 1
        else:
            verdict = "ESCAPE"
            n_escape += 1
        for ln in details:
            print("  %s" % ln, flush=True)
        print("[%s] %s → %s" % (verdict, cid, CASES[cid][0]), flush=True)
        records.append({"id": cid, "attack_class": CASES[cid][0], "leg": CASES[cid][1],
                        "verdict": verdict, "detail": details})
    after = live_sha_map()
    drift = [k for k in sorted(set(before) | set(after))
             if before.get(k) != after.get(k)]
    zero_touch = (not drift) and all(v is not None for v in before.values())
    print("活体保护面 %d 件 sha256 前后一致：%s"
          % (len(before), "是" if zero_touch else "否 drift=%s" % drift))
    if out_path:
        Path(out_path).write_text(json.dumps({
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "mode": "selftest", "suite": "negtest-chain-suite",
            "debt": "D-151", "wave": "wave-16", "issue": 248,
            "cases": records, "blocked": n_blocked, "escape": n_escape,
            "unproven": n_unproven, "zero_touch": zero_touch,
            "live_sha_before": before, "live_sha_after": after,
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        print("读数件：%s" % out_path)
    print("== 汇总: %d 例, BLOCKED=%d, ESCAPE=%d, UNPROVEN=%d, 零触碰=%s =="
          % (len(records), n_blocked, n_escape, n_unproven, zero_touch), flush=True)
    if n_escape or n_unproven or not zero_touch:
        return 1
    return 0


def cmd_live_sha(out_path=None):
    m = live_sha_map()
    for k in sorted(m):
        print("%s  %s" % (m[k] or "MISSING".ljust(64), k))
    if out_path:
        Path(out_path).write_text(json.dumps(
            {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "live_sha": m},
            ensure_ascii=False, indent=1), encoding="utf-8")
        print("基线件：%s" % out_path)
    return 0


def cmd_live_sha_assert(baseline):
    try:
        base = json.loads(Path(baseline).read_text(encoding="utf-8"))["live_sha"]
    except Exception as e:
        print("基线坏（不可证）：%s" % e)
        return 2
    cur = live_sha_map()
    drift = [k for k in sorted(set(base) | set(cur))
             if base.get(k) != cur.get(k)]
    for k in sorted(cur):
        print("%s %s  %s" % ("≡" if base.get(k) == cur.get(k) else "≠",
                             cur[k] or "MISSING".ljust(64), k))
    if drift:
        print("结论：漂移 %d 件：%s（活体被动过）" % (len(drift), drift))
        return 1
    print("结论：活体保护面 %d 件 sha256 前后一致（rc=0）" % len(cur))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--selftest", action="store_true", help="全套六例＋零触碰断言")
    ap.add_argument("--case", choices=sorted(CASES), default=None,
                    help="逐例注入（rc=1=被拦=绿态判据；rc=0=逃逸红警）")
    ap.add_argument("--list", action="store_true", help="列六例")
    ap.add_argument("--live-sha", action="store_true",
                    help="打印活体保护面逐件 sha256（配 --out 存基线）")
    ap.add_argument("--live-sha-assert", default=None, metavar="BASELINE",
                    help="与 --live-sha --out 存的基线比对（一致 rc=0）")
    ap.add_argument("--out", default=None, help="读数件/基线件输出路径（JSON）")
    a = ap.parse_args(argv)
    if a.list:
        for cid in sorted(CASES):
            print("%s  %-24s 拦腿=%-24s 素材=%s"
                  % (cid, CASES[cid][0], CASES[cid][1], CASES[cid][2] or "判官件本体"))
        return 0
    if a.live_sha:
        return cmd_live_sha(a.out)
    if a.live_sha_assert:
        return cmd_live_sha_assert(a.live_sha_assert)
    if a.case:
        return run_case(a.case)
    if a.selftest:
        return run_selftest(a.out)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
