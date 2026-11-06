#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""wave-runner.py — af 波次自转执行器（制度 v1 §一，2026-11-06 施工；v4=D-64 三件收编）。

职责：对波次清单每笔卡**推进一步**（状态机：queued→dispatched→running→verifying→
merge-check→merged→ledgered；任一步红→parked+异常队列）。验收/合线/落账全确定性，
零 LLM 判断；local-api 卡只标 dispatch-pending（由主会话/巡检发工作流）。

硬约束（OOM 准入账本 §五）：anolis Σmem_budget≤45G（free -g available 实测）、cargo≤4；
本机 available>3G 才放 local-api。flock 单写、幂等（同卡同态不重派）。

通道：
  anolis-build：admission→生成 run 脚本（card.steps+accept_cmds+done marker）→scp
    nohup→state=running；下轮见 marker→跑 accept_cmds（ssh）→全绿→merge-check。
  bot-lane：tasks/<id>/meta.json 在盘→add --state queued→export→occupancy ALLOW→
    bridge --task 发布；收割由 bot-harvest-sweep.py（*/20）推进，本件不重复。
  local-api：state=dispatch-pending（打标走人；主会话工作流施工完跑 accept_cmds 推进）。

──────────────── v4 三件（D-64·2026-11-06·运营者①②③收编）────────────────
① merge-policy 批量步（根治多树并行门自造 ENOSPC——今晨 wave-02 手工程序收编）：
   同波次 merge 就绪卡（state=verifying ∧ merge.branches 非空）按 merge.group
   （缺省=波次名）归组；组内 ≥2 卡 ⇒ 单树 /data/bench/wt-mc-<group> + 分支
   merge-check/<group>，组内分支按卡序 --no-ff 顺序合（显式 refspec 取回）→ 单轮
   快手（step0 mutations 注册校验+fmt+strategies_check）→ 全量门走监督轨（接口不变）→ FF push 一次
   （remote 已含 mc_ref 的同组卡跳过，幂等）→ 逐卡落账。组内 <2 卡或无 group
   ⇒ 既有单卡路径（wt-mc-<task_id>）不回归。targets 按组共享
   （CARGO_TARGET_DIR=/data/bench/targets/mc-<group>，ENOSPC 纪律）。

② env-check 全面收编（tools/anolis-env-check.sh·fail-closed 结构化 JSON）：
   所有 ssh compound 前缀 `bash /data/bench/anolis-env-check.sh || exit 2;`
   （cargo PATH + df /data≥10G 预检；失败 ⇒ 该 compound 整体中止、异常队列见
   JSON 理由）。dispatch_anolis 生成脚本同前置（失败写 FAILED marker，verify 转红）。
   说明：部署件 env-check.sh 以 exit 0 收尾，字面 `source` 会截断 compound——
   故采子壳执行 `bash … || exit 2` 语义（草稿 C3 验收同款）；PATH 由各脚本/compound
   自带 `export PATH=$HOME/.cargo/bin:$PATH` 保证。探针解析一律取**末行**（免疫前缀）。

③ 监督轨统一文档化（单一监督面，见下方「监督轨」段）：
   全量门（全量 test+clippy）不走 anolis 后台（EXP1 双实证静默死）——统一
   「主代理本地后台终端任务监督」范式；runner 本态只记树/分支（mc_wt/mc_ref/
   mc_group），主代理验门后置 mc_done；同树任卡 mc_done ⇒ 全组认证（监督按组一轮）。

合线范式（三分支今夜范式·制度§六.1）：显式 refspec 取 feature → --no-ff 合入 merge-check
树 → fmt+strat+全量 test+clippy → 全 0 → FF push product/main。
落账范式（核销批 difflib 证明）：只翻 ✅+行尾 append 依据句、wc -l 不变、整文件先备。

红件：append af-state/dispatch/exceptions.jsonl {ts,task_id,stage,evidence} + state=parked。

──────────────── 监督轨（v4③ 文档化·制度§四 + 计划/变更日志.md:48417/48422/48605）────────
单一监督面 = **主代理本地后台终端任务**（完成通知驱动），四段式文件运输：
  ① 本地生成 gate 脚本（四门：cargo fmt --check --all + ci/strategies_check.py
     + 全量 cargo test + clippy；flock 单写 + ENOSPC 预检内嵌，禁裸 set -e 分段守卫）；
  ② 本地脚本文件 → scp → anolis nohup（禁内联长 ssh 命令：exec 第三波抖动根因
     = 桌面应用本体 OOM，:48611 焦点4——文件运输免疫）；
  ③ 本地后台等待器盯结果文件（出结果即通知；11:00 巡检起统一此形态）；
  ④ 绿 ⇒ 对该组全部 merge-testing 卡置 mc_done=true（runner 亦认「同树任卡
     mc_done」为全组认证）；红 ⇒ append 异常队列（格式同 exc()）。
批量组语义：监督按**组**一轮（单树单轮全量门），不按卡重复；runner 不跑全量门
（本机永禁 cargo），只验标推送+落账。干跑/自测：`--selftest`（内嵌夹具+桩传输，
零生产触达）。
"""
import fcntl
import json
import os
import re
import subprocess
import sys
import time

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WAVES = os.path.join(WS, "30-工件", "波次自转器-20261106")
EXC = os.path.join(WS, "af-state", "dispatch", "exceptions.jsonl")
ANOLIS = os.environ.get("WAVE_SSH", "anolis")
ANOLIS_MEM_CAP_G = 45
LOCAL_MEM_FLOOR_G = 3
LOCK = os.path.join(WS, "af-state", "dispatch", "wave-runner.lock")
TS = "%Y-%m-%dT%H:%M:%S+0800"
# env-check 全面收编（D-64②）：部署件 tools/anolis-env-check.sh → anolis /data/bench/。
# 子壳执行语义：失败 exit 2 中止整个 compound（fail-closed）；成功 exit 0 后续执行。
ENV_CHECK = "/data/bench/anolis-env-check.sh"
ENV_CHECK_PREFIX = "bash %s || exit 2; " % ENV_CHECK
# --selftest 干跑桩（DRY["on"]=True 时 sh/ssh_anolis 全走桩，零生产触达）
DRY = {"on": False, "ssh_fn": None, "sh_fn": None}


def sh(cmd, timeout=120):
    if DRY["on"] and DRY["sh_fn"]:
        return DRY["sh_fn"](cmd, timeout=timeout)
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)


def ssh_anolis(cmd, timeout=180):
    # base64 运输层（2026-11-06 首航实证：-m '…' 单引号经 replace 转义后会截断 ssh 外层引号
    # 致合线命令流失真——b64 后远端解码执行，引号/中文/换行全免疫）。
    # v4②：所有 compound 前置 env-check（fail-closed）；DRY 模式下同样带前缀过桩，
    # 使自测能断言「每个 ssh compound 都被 env-check 前置」。
    if DRY["on"] and DRY["ssh_fn"]:
        return DRY["ssh_fn"](ENV_CHECK_PREFIX + cmd, timeout=timeout)
    import base64
    b = base64.b64encode((ENV_CHECK_PREFIX + cmd).encode("utf-8")).decode("ascii")
    return sh("ssh -o BatchMode=yes -o ConnectTimeout=10 %s 'echo %s | base64 -d | bash'" % (ANOLIS, b), timeout)


def log(msg):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), msg))


def exc(task_id, stage, evidence):
    os.makedirs(os.path.dirname(EXC), exist_ok=True)
    with open(EXC, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": time.strftime(TS), "task_id": task_id,
                            "stage": stage, "evidence": evidence[:400]}, ensure_ascii=False) + "\n")
    log("PARK %s @%s：%s" % (task_id, stage, evidence[:120]))


def env_check_fail(out):
    """env-check 前缀 FAIL 的结构化理由行（供异常队列人读；None=未现 FAIL）。"""
    for line in (out or "").splitlines():
        if '"env_check"' in line and '"FAIL"' in line:
            return line.strip()[:200]
    return None


def last_line(out):
    """ssh 输出末行（env-check 前缀后探针值的稳健解析）。"""
    ls = [l.strip() for l in (out or "").splitlines() if l.strip()]
    return ls[-1] if ls else ""


def anolis_avail_g():
    r = ssh_anolis("free -g | awk 'NR==2{print $7}'")
    try:
        return int(last_line(r.stdout))
    except Exception:
        return None


def local_avail_g():
    r = sh("free -g | awk 'NR==2{print $7}'")
    try:
        return int((r.stdout or "").strip())
    except Exception:
        return None


def running_mem_sum(waves):
    total = 0.0
    for w in waves:
        for c in w.get("cards", []):
            if c.get("state") in ("running", "verifying"):
                total += float(c.get("mem_budget_g") or 0)
    return total


# ─────────────────────────────────────────── 批量合线分组（D-64①）
def _san(tag):
    """组名→文件/分支安全名（保留 [A-Za-z0-9._-]，其余归一为 -）。"""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", tag).strip("-") or "group"


def wave_of(c, waves):
    for w in waves:
        if any(x is c for x in w.get("cards", [])):
            return w
    return None


def card_group(c, wave_name):
    """卡所属合线组：merge.group 显式声明优先，缺省=波次名（wave-02 六卡即同组单树）。"""
    return (c.get("merge") or {}).get("group") or wave_name


def group_members(c, waves):
    """同组全体卡（不论状态）——用于在飞树判定与全组认证推导。"""
    w = wave_of(c, waves)
    if w is None:
        return [c]
    g = card_group(c, w.get("wave", "wave"))
    ms = [x for x in w.get("cards", []) if card_group(x, w.get("wave", "wave")) == g]
    return ms or [c]


def group_ready(c, waves):
    """同组合并就绪卡（含 c）：state=verifying ∧ merge.branches 非空。"""
    w = wave_of(c, waves)
    if w is None:
        return [c] if (c.get("state") == "verifying" and (c.get("merge") or {}).get("branches")) else []
    g = card_group(c, w.get("wave", "wave"))
    return [x for x in w.get("cards", [])
            if x.get("state") == "verifying" and (x.get("merge") or {}).get("branches")
            and card_group(x, w.get("wave", "wave")) == g]


def group_inflight(members):
    """组内是否有在飞合线树（任一员 mc_wt 已置且 state=merge-testing）。"""
    return any(x.get("mc_wt") and x.get("state") == "merge-testing" for x in members)


def tree_certified(c, waves):
    """同树（mc_wt 相同）任一员 mc_done=true ⇒ 该树全量门已认证（监督轨按组一轮）。"""
    wt = c.get("mc_wt")
    if not wt:
        return False
    for w in waves:
        for x in w.get("cards", []):
            if x is not c and x.get("mc_wt") == wt and x.get("mc_done"):
                return True
    return False


def merge_tree_commands(wt, mref, branches, tdir, tag):
    """合线树命令串（单卡/批量共用）：清旧→建树→逐支显式 refspec + --no-ff → 快手三门。
    targets 目录由调用方给（批量=按组共享，单卡=按 task_id，ENOSPC 纪律）。"""
    cmds = ["export PATH=$HOME/.cargo/bin:$PATH",
            "cd ~/af-dev/af && git fetch origin -q",
            "git worktree remove --force %s 2>/dev/null; git branch -D %s 2>/dev/null; true" % (wt, mref),
            "git worktree add %s -b %s origin/product/main" % (wt, mref)]
    for br in branches:
        ref = br["ref"]
        msg = br.get("msg", "merge: %s" % ref)
        cmds.append("git fetch origin +refs/heads/%s:refs/remotes/origin/%s" % (ref, ref))
        cmds.append("cd %s && git merge --no-ff origin/%s -m '%s' -q && echo M_OK || echo M_FAIL" % (wt, ref, msg))
    # step0 等价快门（v5 补合线门面缺口；复盘 C3-②「mutation 不过不得合流」）：ci/run.sh
    # step0 的 mutations 注册校验独立可跑形式（af/ci/run.sh:134
    # `bash ci/mutation_runner.sh check-registry --root $AF_ROOT`）——注册表 sha256+探针数
    # vs 基线钉 ci/baselines/mutations-registry.sha256，漂移/基线缺席一律 fail-closed 红；
    # fmt/strat/test/clippy 均不覆盖之（2026-11-06 实证：product/main=5ee16ec 即潜伏
    # step0 红 188e157a≠881781d9，快手无 STEP0 时照放行）。日志尾同 strat 落
    # /tmp/mc-<tag>-step0.log，判据只认 compound 回显 STEP0_OK。
    cmds.append("cd %s && bash ci/mutation_runner.sh check-registry --root %s >/tmp/mc-%s-step0.log 2>&1 && echo STEP0_OK || echo STEP0_FAIL"
                % (wt, wt, tag))
    envp = ("env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u all_proxy -u ALL_PROXY "
            "LC_CTYPE=C.UTF-8 CARGO_TARGET_DIR=%s" % tdir)
    cmds.append("cd %s && %s cargo fmt --check --all && echo FMT_OK || echo FMT_FAIL" % (wt, envp))
    cmds.append("cd %s && python3 -B ci/strategies_check.py >/tmp/mc-%s-strat.log 2>&1 && echo STRAT_OK || echo STRAT_FAIL"
                % (wt, tag))
    return cmds


def shutter_missing(out, n_branches):
    """快手缺失项（计数判据，v4① 修正）：M_OK 出现次数须 == 合入支数且零 M_FAIL
    （v3 子串判据 `"M_OK" in out` 在多支场景会假绿——1/3 支失败也判过）；fmt/strat/
    step0 mutations 注册校验各就位（v5 补：ci/run.sh step0 等价项——此前合线门面只有
    M/FMT/STRAT，漏 step0；复盘 C3-②「mutation 不过不得合流」）。"""
    miss = []
    n_ok = out.count("M_OK")
    if n_ok < n_branches:
        miss.append("M_OK(%d/%d)" % (n_ok, n_branches))
    if "M_FAIL" in out:
        miss.append("M_FAIL")
    if "FMT_OK" not in out:
        miss.append("FMT_OK")
    if "STRAT_OK" not in out:
        miss.append("STRAT_OK")
    if "STEP0_OK" not in out:
        miss.append("STEP0_OK")
    return miss


def batch_merge(ready, waves):
    """批量组 ≥2 卡 ⇒ 单树顺序合（运营者①收编）：同 mc_wt/mc_ref/tdir，逐卡置
    merge-testing；快门缺 ⇒ 全组 parked+逐卡异常（树共享，不部分放行）。"""
    w = wave_of(ready[0], waves) or {}
    group = card_group(ready[0], w.get("wave", "wave"))
    tag = _san(group)
    wt, mref, tdir = "/data/bench/wt-mc-" + tag, "merge-check/" + tag, "/data/bench/targets/mc-" + tag
    all_branches = [br for x in ready for br in (x.get("merge") or {}).get("branches", [])]
    if not all_branches:
        return False, "批量组 %s 无 branches" % group
    cmds = merge_tree_commands(wt, mref, all_branches, tdir, tag)
    r = ssh_anolis("; ".join(cmds), timeout=600)
    out = r.stdout or ""
    missing = shutter_missing(out, len(all_branches))
    if missing:
        ef = env_check_fail(out)
        ev = ("批量组 %s 快门缺 %s｜%s" % (group, missing, out[-240:])) if not ef else \
             ("批量组 %s env-check FAIL：%s" % (group, ef))
        for x in ready:
            x["state"] = "parked"
            exc(x["task_id"], "merge-check", ev)
        return "parked", ev
    for x in ready:
        x["mc_wt"] = wt
        x["mc_ref"] = mref
        x["mc_group"] = group
        x["state"] = "merge-testing"
        x["merge_result"] = ("单树批量组 %s：%d 卡 %d 支 --no-ff 全 M_OK、step0 注册校验过；"
                             "全量门待本地监督轨（gate 完置 mc_done）" % (group, len(ready), len(all_branches)))
    if w:
        w["_batch_dirty"] = True
    return "testing", ("单树 %s 合 %d 支（%d 卡：%s）；全量门待主代理本地监督轨"
                       % (wt, len(all_branches), len(ready), ",".join(x["task_id"] for x in ready)))


def merge_check_batch(c, waves):
    """批量合线决策（D-64①）：无 branches⇒旧路径报错；同组在飞⇒等；组内 ≥2⇒单树批量；
    否则⇒既有单卡路径（wt-mc-<task_id>，不回归）。"""
    if not (c.get("merge") or {}).get("branches"):
        return merge_check_and_push(c)
    members = group_members(c, waves)
    if group_inflight(members):
        return "wait", "同组在飞树未收卷（%s），等 mc_done 后下轮并入" % (members[0].get("mc_wt") or "?")
    ready = group_ready(c, waves)
    if len(ready) >= 2:
        return batch_merge(ready, waves)
    return merge_check_and_push(c)


def dispatch_anolis(c):
    """生成 run 脚本 → scp → nohup。脚本内分段守卫（制度§六.2 禁裸 set -e）。
    v4②：env-check 前置（失败写 FAILED marker ⇒ verify 转红，不挂起）。"""
    tid = c["task_id"]
    wt = "/data/bench/wt-" + tid
    mdir = "/data/bench/wave-markers"
    marker = mdir + "/" + tid + ".done"
    lines = ["#!/bin/bash", "export PATH=$HOME/.cargo/bin:$PATH",
             "exec 9>/data/bench/wave-%s.lock; flock -n 9 || { echo LOCK_BUSY; exit 9; }" % tid,
             "mkdir -p " + mdir,
             "rm -f " + marker,
             # env-check 前置（D-64②）：cargo PATH + df /data≥10G；失败⇒FAILED marker+exit 2
             "bash %s || { echo ENV_CHECK_FAIL; echo FAILED > %s; exit 2; }" % (ENV_CHECK, marker),
             "cd ~/af-dev/af && git fetch origin -q --filter=blob:none || true"]
    for i, br in enumerate(c.get("merge", {}).get("branches", [])):
        ref = br["ref"]
        lines.append("git fetch origin +refs/heads/%s:refs/remotes/origin/%s || { echo STEP_FAIL_fetch_%d; echo FAILED > %s; exit 1; }"
                     % (ref, ref, i, marker))
    for st in c.get("steps", []):
        lines.append("{ %s; } || { echo STEP_FAIL_run; echo FAILED > %s; exit 1; }" % (st, marker))
    for ac in c.get("accept_cmds", []):
        lines.append("{ %s; } || { echo ACCEPT_FAIL; echo FAILED > %s; exit 1; }" % (ac, marker))
    lines.append("echo OK > " + marker)
    script = "\n".join(lines) + "\n"
    lp = "/tmp/wave-%s.sh" % tid
    open(lp, "w").write(script)
    r = sh("scp -q -o BatchMode=yes %s %s:/data/bench/wave-%s.sh" % (lp, ANOLIS, tid))
    if r.returncode != 0:
        return False, "scp 失败：%s" % r.stderr[:120]
    r = ssh_anolis("nohup bash /data/bench/wave-%s.sh > /data/bench/wave-%s.log 2>&1 & echo STARTED $!" % (tid, tid))
    if "STARTED" not in (r.stdout or ""):
        ef = env_check_fail(r.stdout + (r.stderr or ""))
        return False, ("env-check FAIL：%s" % ef) if ef else ("nohup 未起：%s" % (r.stdout + r.stderr)[:120])
    return True, (r.stdout or "").strip()


def verify_anolis(c):
    tid = c["task_id"]
    marker = "/data/bench/wave-markers/" + tid + ".done"
    r = ssh_anolis("cat %s 2>/dev/null; echo; tail -3 /data/bench/wave-%s.log 2>/dev/null" % (marker, tid))
    out = r.stdout or ""
    ef = env_check_fail(out)
    if ef:
        return "red", "env-check FAIL：%s" % ef
    if "\nOK" in out or out.startswith("OK"):
        return "green", out.strip()[:200]
    if "FAILED" in out:
        return "red", out.strip()[-260:]
    return "wait", out.strip()[-120:]


def merge_check_and_push(c):
    """制度§三 合线路（单卡旧路径，v4① 保留不回归）：显式 refspec → --no-ff → 快手三门
    （fmt/strategies_check/step0 mutations 注册校验）→ 全量门待本地监督轨（本态只记
    树/分支；见模块 docstring「监督轨」段）。"""
    m = c.get("merge") or {}
    branches = m.get("branches") or []
    if not branches:
        return False, "卡无 merge.branches"
    wt = m.get("wt", "/data/bench/wt-mc-" + c["task_id"])
    mref = m.get("merge_ref", "merge-check/" + c["task_id"])
    tdir = m.get("target_dir", "/data/bench/targets/mc-" + c["task_id"])
    cmds = merge_tree_commands(wt, mref, branches, tdir, c["task_id"])
    r = ssh_anolis("; ".join(cmds), timeout=600)
    out = r.stdout or ""
    missing = shutter_missing(out, len(branches))
    if missing:
        ef = env_check_fail(out)
        if ef:
            return False, "env-check FAIL：%s" % ef
        return False, "合线快门缺 %s｜%s" % (missing, out[-240:])
    # 长杆拆分 v3（2026-11-06 双实证：nohup-over-ssh 后台门连续静默死）——全量门不走 anolis
    # 后台，统一「主代理本地后台终端任务监督」范式（完成通知驱动，v4③ 已文档化于
    # 模块 docstring）；本态只记树/分支，主代理验门后置卡 mc_done=true，下轮 tick
    # 验标推送+落账。批量组下同树任卡 mc_done ⇒ 全组认证（tree_certified）。
    c["mc_wt"] = wt
    c["mc_ref"] = mref
    return "testing", "快门全过（M/FMT/STRAT/STEP0）；全量门待主代理本地监督轨（gate 完置 mc_done）"


def push_once_if_needed(c, waves):
    """merge-testing 且门已认证后的推送步（D-64①「FF push 一次」）：remote product/main
    已含本地 mc_ref ⇒ 同组已推，跳过（幂等）；否则执行 FF push 并验标。"""
    if not c.get("mc_wt") or not c.get("mc_ref"):
        return False, "缺 mc_wt/mc_ref（merge-testing 态异常）"
    # 幂等探测：本地 mc_ref sha vs 远端 product/main（末两行解析免疫 env-check 前缀）
    chk = ssh_anolis("cd %s && git rev-parse %s 2>/dev/null; git ls-remote origin product/main"
                     % (c["mc_wt"], c["mc_ref"]))
    ls = [l.strip() for l in (chk.stdout or "").splitlines() if l.strip()]
    if len(ls) >= 2 and re.fullmatch(r"[0-9a-f]{40}", ls[-2]) and ls[-2] in ls[-1]:
        c["merge_result"] = "FF push 一次（同组已推，remote product/main=%s）" % ls[-2][:12]
        return True, c["merge_result"]
    r = ssh_anolis("cd %s && git push origin %s:product/main 2>&1 | tail -1 && git ls-remote origin product/main"
                   % (c["mc_wt"], c["mc_ref"]))
    if r.returncode != 0 or "product/main" not in (r.stdout or ""):
        ef = env_check_fail(r.stdout + (r.stderr or ""))
        return False, ("env-check FAIL：%s" % ef) if ef else ((r.stdout + r.stderr)[-200:])
    c["merge_result"] = (r.stdout or "").strip()[-120:]
    return True, c["merge_result"]


def ledger_write(c):
    """落账范式：点名行翻 ✅+append 依据句、wc -l 不变、先备。"""
    rows = (c.get("ledger") or {}).get("rows") or []
    if not rows:
        return True, "无 ledger.rows（跳过）"
    done = []
    for row in rows:
        p = os.path.join(WS, row["file"])
        if not os.path.isfile(p):
            return False, "缺件 %s" % row["file"]
        sh("cp -p %s %s/%s.$(date +%%Y%%m%%d-%%H%%M%%S)-pre-wave-ledger.bak 2>/dev/null; true" % (p, os.path.join(WS, "工具状态备份"), os.path.basename(p)))
        before = sh("wc -l < %s" % p).stdout.strip()
        lines = open(p, encoding="utf-8").read().splitlines()
        out, hit = [], False
        for l in lines:
            if re.match(row["row_key"], l) and ("✅" not in l.split("|")[3] if len(l.split("|")) > 3 else True):
                cells = l.split("|")
                if len(cells) > 3:
                    cells[3] = " ✅ " + cells[3].strip()
                    l = "|".join(cells) + "｜" + row["evidence"]
                hit = True
            out.append(l)
        if not hit:
            return False, "row_key 未命中 %s" % row["row_key"]
        open(p, "w", encoding="utf-8").write("\n".join(out) + "\n")
        after = sh("wc -l < %s" % p).stdout.strip()
        if before != after:
            return False, "wc -l 变化 %s→%s（回滚纪律违）" % (before, after)
        done.append(row["file"])
    return True, "落账 %d 行：%s" % (len(rows), ";".join(done))


def bot_publish(c):
    tid = c["task_id"]
    if not os.path.isfile(os.path.join(WS, "30-工件", "外派-bot-试点", "tasks", tid, "meta.json")):
        return False, "卡三件套未落盘（待组卡）"
    r = sh("cd %s && python3 -I tools/dispatch-registry.py add --task-id %s --debt-id %s --channel bot --state queued --base-sha %s"
           % (WS, tid, c.get("debt", "?"), c.get("base_sha", "478e988fec1bf93187921c7369491cec8b34d31d")))
    sh("cd %s && python3 -I tools/dispatch-registry.py export" % WS)
    r = sh("cd %s && python3 -I tools/dispatch-occupancy-check.py %s --json" % (WS, c.get("debt", "?")))
    try:
        v = json.loads(r.stdout or "{}").get("verdict")
    except Exception:
        v = None
    if v != "ALLOW":
        return False, "占用闸 %s≠ALLOW（按卡 preflight_note 换锚或 HOLD）" % v
    r = sh("cd %s && python3 -I 30-工件/外派-bot-试点/tool/bot-bridge.py --task %s" % (WS, tid), timeout=180)
    if r.returncode != 0:
        return False, "bridge：%s" % (r.stderr or r.stdout)[-160:]
    sh("cd %s && python3 -I tools/dispatch-registry.py transition --task-id %s --to packaged >/dev/null 2>&1; "
       "python3 -I tools/dispatch-registry.py transition --task-id %s --to published >/dev/null 2>&1; "
       "python3 -I tools/dispatch-registry.py export >/dev/null 2>&1" % (WS, tid, tid))
    return True, "published"


def advance(c, waves):
    st = c.get("state", "queued")
    ch = c.get("channel")
    if st == "queued":
        if ch == "anolis-build":
            avail = anolis_avail_g()
            if avail is None:
                exc(c["task_id"], "admission", "anolis free 读不到（fail-closed 不派）")
                c["state"] = "parked"; return
            if running_mem_sum(waves) + float(c.get("mem_budget_g") or 8) > ANOLIS_MEM_CAP_G:
                return  # 排队等下轮
            ok, ev = dispatch_anolis(c)
            c["state"] = "running" if ok else "parked"
            if not ok: exc(c["task_id"], "dispatch", ev)
        elif ch == "bot-lane":
            ok, ev = bot_publish(c)
            c["state"] = "dispatched" if ok else "parked"
            if not ok: exc(c["task_id"], "publish", ev)
        elif ch == "local-api":
            if (local_avail_g() or 0) > LOCAL_MEM_FLOOR_G:
                c["state"] = "dispatch-pending"   # 主会话/巡检发工作流后调 verify_local
        return
    if st == "running" and c.get("channel") == "anolis-build":
        v, ev = verify_anolis(c)
        if v == "wait":
            return
        if v == "red":
            c["state"] = "parked"; exc(c["task_id"], "verify", ev); return
        c["state"] = "verifying"
        # verifying 同轮直进 merge-check
    if st == "verifying":
        ok, ev = merge_check_batch(c, waves)
        if ok == "wait":
            return  # 同组在飞树未收卷
        if ok == "testing":
            c["state"] = "merge-testing"; return
        if ok == "parked":
            return  # 批量组已逐卡 parked+exc（树共享不部分放行）
        if not ok:
            c["state"] = "parked"; exc(c["task_id"], "merge-check", ev); return
        c["merge_result"] = ev
        c["state"] = "merged"
        return
    if st == "merge-testing":
        # 全量门认证：本卡 mc_done 或同树任卡 mc_done（监督轨按组一轮，v4③）
        if not (c.get("mc_done") or tree_certified(c, waves)):
            return  # 等主代理本地监督轨验门后置 mc_done=true
        ok, ev = push_once_if_needed(c, waves)
        if not ok:
            c["state"] = "parked"; exc(c["task_id"], "push", ev); return
        c["state"] = "merged"
        return
    if st == "merged":
        ok, ev = ledger_write(c)
        if not ok:
            c["state"] = "parked"; exc(c["task_id"], "ledger", ev); return
        c["ledger_result"] = ev
        c["state"] = "ledgered"
        log("DONE %s：%s" % (c["task_id"], ev))
        return
    if st == "dispatch-pending":
        return  # 等外部（主会话工作流）施工后由 verify_local 推进


def main():
    os.makedirs(os.path.dirname(LOCK), exist_ok=True)
    lf = open(LOCK, "w")
    try:
        fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("LOCK_BUSY"); return 0
    waves = []
    for fn in sorted(os.listdir(WAVES)):
        if fn.startswith("wave-") and fn.endswith(".json"):
            w = json.load(open(os.path.join(WAVES, fn)))
            w["_file"] = fn
            waves.append(w)
    if not waves:
        print("NO_WAVES"); return 0
    for w in waves:
        dirty = False
        for c in w.get("cards", []):
            c.setdefault("state", "queued")
            if c.get("state") in ("queued", "running", "verifying", "merge-testing", "merged", "dispatch-pending"):
                before = c.get("state")
                advance(c, waves)
                if c.get("state") != before:
                    dirty = True
                    log("%s %s→%s" % (c["task_id"], before, c.get("state")))
        if dirty or w.get("_batch_dirty"):
            w.pop("_batch_dirty", None)
            w["runner_touched_at"] = time.strftime(TS)
            # 落盘剥离内部键（_file/_batch_dirty 等不持久化，防 JSON 污染）
            out = {k: v for k, v in w.items() if not k.startswith("_")}
            json.dump(out, open(os.path.join(WAVES, os.path.basename(w.get("_file", fn))), "w"), ensure_ascii=False, indent=1)
    return 0


# ─────────────────────────────────────────── --selftest（D-64 干跑·零生产触达）
def _cp(stdout="", stderr="", rc=0):
    return subprocess.CompletedProcess(args=[], returncode=rc, stdout=stdout, stderr=stderr)


class MockAnolis:
    """anolis 桩：录 compound（含 env-check 前缀）+ 脚本化回放；零 ssh/scp 真连。

    回放规则与生产语义对齐：env-check FAIL ⇒ 只回 FAIL JSON（compound 中止）；
    git merge --no-ff ⇒ 逐支 M_OK/M_FAIL（fail_branches 注入红）；fmt/strat/step0 ⇒ OK
    （step0_drift=True 注入 STEP0_FAIL——注册校验漂移语义）；
    rev-parse+ls-remote ⇒ 本地/远端 sha；push ⇒ 记录事件并把远端推到本地 sha；
    nohup ⇒ STARTED；marker cat ⇒ self.marker。
    """

    def __init__(self):
        self.cmds = []
        self.outs = []
        self.pushes = []
        self.remote_main = None
        self.fail_branches = set()
        self.env_ok = True
        self.step0_drift = False
        self.marker = "OK"

    def __call__(self, cmd, timeout=180):
        self.cmds.append(cmd)
        out = []
        if not self.env_ok:
            r = _cp(stdout='{"env_check":"FAIL","reason":"data_lt_10G","avail_g":"9"}', rc=2)
            self.outs.append(r.stdout)
            return r
        out.append('{"env_check":"OK","cargo":"/root/.cargo/bin/cargo","data_avail_g":127}')
        if "git merge --no-ff" in cmd:
            for m in re.finditer(r"git merge --no-ff origin/(\S+)", cmd):
                out.append("M_FAIL" if m.group(1) in self.fail_branches else "M_OK")
        if "cargo fmt --check" in cmd:
            out.append("FMT_OK")
        if "strategies_check" in cmd:
            out.append("STRAT_OK")
        if "mutation_runner.sh check-registry" in cmd:
            out.append("STEP0_FAIL" if self.step0_drift else "STEP0_OK")
        if "git rev-parse" in cmd:
            out.append("a" * 40)
        if "git push origin" in cmd:
            self.pushes.append(cmd)
            self.remote_main = "a" * 40
            out.append("To anolis:af\n\tproduct/main -> product/main")
        if "git ls-remote" in cmd:
            out.append((self.remote_main or "0" * 40) + "\trefs/heads/product/main")
        if "free -g" in cmd:
            out.append("40")
        if "echo STARTED" in cmd:
            out.append("STARTED 12345")
        if "wave-markers" in cmd and self.marker:
            out.append(self.marker)
        r = _cp(stdout="\n".join(out))
        self.outs.append(r.stdout)
        return r


def _mkcard(tid, refs, state="verifying", **kw):
    c = {"task_id": tid, "debt": "D-T", "channel": "local-api", "mem_budget_g": 0,
         "merge": {"branches": [{"ref": r, "msg": "merge: %s" % r} for r in refs]},
         "state": state}
    c.update(kw)
    return c


def selftest():
    """--selftest：构造 3 卡同组 JSON + 单卡/在飞/负例/推一次 全干跑（桩传输、沙箱树名，
    不触生产 wt/targets/anolis）。全过 rc=0，任一不过 rc=1。"""
    global EXC
    import tempfile
    import shutil
    results = []

    def check(name, cond, detail=""):
        results.append((name, bool(cond), detail))
        print("%s %s%s" % ("PASS" if cond else "FAIL", name, ("｜" + detail) if detail and not cond else ""))

    tmp = tempfile.mkdtemp(prefix="wave-runner-selftest-")
    old_exc = EXC
    EXC = os.path.join(tmp, "exceptions.jsonl")
    mock = MockAnolis()
    DRY["on"], DRY["ssh_fn"] = True, mock
    DRY["sh_fn"] = lambda cmd, timeout=120: _cp(rc=0)
    try:
        # ① 3 卡同组（缺省 group=波次名）⇒ 单树+三支 M_OK+targets 按组共享
        cards = [_mkcard("selftest-t%d" % i, ["feature/selftest-t%d" % i]) for i in (1, 2, 3)]
        for i, c in enumerate(cards):
            c["ledger"] = {"rows": [{"file": "计划/阶段欠账台账.md", "row_key": "\\|\\s*D-T%d\\s*\\|" % i,
                                     "evidence": "〔selftest〕"}]}
        wave = {"schema": "af.wave/1", "wave": "wave-selftest", "cards": cards}
        waves = [wave]
        ok, ev = merge_check_batch(cards[0], waves)
        check("batch:3卡同组返回testing", ok == "testing", ev)
        check("batch:三卡同树mc_wt", len({c.get("mc_wt") for c in cards}) == 1
              and cards[0]["mc_wt"] == "/data/bench/wt-mc-wave-selftest", str([c.get("mc_wt") for c in cards]))
        check("batch:三卡同mc_ref", cards[0]["mc_ref"] == "merge-check/wave-selftest")
        check("batch:三卡入merge-testing", all(c["state"] == "merge-testing" for c in cards))
        check("batch:波次脏标记", wave.get("_batch_dirty") is True)
        comp = mock.cmds[-1]
        check("batch:compound三支--no-ff", comp.count("git merge --no-ff origin/") == 3)
        check("batch:compound三显式refspec", comp.count("git fetch origin +refs/heads/") == 3)
        check("batch:targets按组共享", "CARGO_TARGET_DIR=/data/bench/targets/mc-wave-selftest" in comp
              and "mc-selftest-t1" not in comp)
        check("batch:快手三门在位（fmt+strat+step0）", "cargo fmt --check --all" in comp
              and "ci/strategies_check.py" in comp and "ci/mutation_runner.sh check-registry" in comp)
        check("batch:回放三M_OK+快手三门OK", mock.outs[-1].count("M_OK") == 3
              and "FMT_OK" in mock.outs[-1] and "STRAT_OK" in mock.outs[-1]
              and "STEP0_OK" in mock.outs[-1])
        # 逐卡落账字段保留（批量步只动合线面，ledger.rows 原样交给 merged 态逐卡落账）
        check("batch:逐卡ledger字段保留", all(c.get("ledger", {}).get("rows") for c in cards))

        # ② env-check 前缀进所有 ssh compound（含探针）
        mock.cmds.clear()
        anolis_avail_g()
        check("env:探针compound带前缀", mock.cmds and mock.cmds[0].startswith(ENV_CHECK_PREFIX))
        check("env:探针末行解析=40", anolis_avail_g() == 40)
        mock.cmds.clear()
        # dispatch 生成脚本 env-check 前置
        dcard = _mkcard("selftest-dispatch", ["feature/selftest-dispatch"], state="queued")
        dcard["channel"] = "anolis-build"
        ok, ev = dispatch_anolis(dcard)
        lp = "/tmp/wave-selftest-dispatch.sh"
        script = open(lp).read() if os.path.isfile(lp) else ""
        check("env:dispatch返回STARTED", ok is True, ev)
        check("env:dispatch脚本env-check前置", ("bash %s || { echo ENV_CHECK_FAIL; echo FAILED >" % ENV_CHECK) in script)
        check("env:dispatch脚本flock在env-check前", script.index("flock -n 9") < script.index("ENV_CHECK_FAIL"))
        os.path.exists(lp) and os.remove(lp)

        # verify_anolis：env-check 前缀不误判 marker（OK⇒green；env FAIL⇒red）
        v, ev = verify_anolis({"task_id": "selftest-verify"})
        check("env:verify前缀下marker判绿", v == "green", "%s｜%s" % (v, ev))
        mock.env_ok = False
        v, ev = verify_anolis({"task_id": "selftest-verify"})
        check("env:verify遇env-check FAIL判红", v == "red" and "env-check FAIL" in ev, "%s｜%s" % (v, ev))
        mock.env_ok = True

        # ③ 监督轨接口：mc_done 置位 ⇒ 推一次；同树任卡 mc_done ⇒ 全组认证
        for c in cards:
            c["mc_done"] = True
        mock.pushes.clear()
        for c in cards:
            before = c["state"]
            advance(c, waves)
            check("supervise:%s merged" % c["task_id"], c["state"] == "merged" and before == "merge-testing",
                  str(c.get("merge_result")))
        check("supervise:FF push 一次", len(mock.pushes) == 1, "pushes=%d" % len(mock.pushes))
        check("supervise:同组跳过推送证据", "同组已推" in (cards[-1].get("merge_result") or ""))

        # 同树任卡 mc_done ⇒ 未置位卡也可推（认证推导）
        cards2 = [_mkcard("selftest-c%d" % i, ["feature/selftest-c%d" % i]) for i in (1, 2)]
        wave2 = {"wave": "wave-selftest2", "cards": cards2}
        ok, ev = merge_check_batch(cards2[0], [wave2])
        cards2[0]["mc_done"] = True  # 只首卡置位
        mock.pushes.clear()
        advance(cards2[1], [wave2])
        check("supervise:同树任卡mc_done全组认证", cards2[1]["state"] == "merged", cards2[1].get("merge_result", ""))

        # 单卡旧路径不回归（无 group 多卡就绪时独卡⇒wt-mc-<task_id>）
        solo = _mkcard("selftest-solo", ["feature/selftest-solo"])
        wave3 = {"wave": "wave-solo", "cards": [solo]}
        ok, ev = merge_check_batch(solo, [wave3])
        check("solo:独卡走旧路径testing", ok == "testing")
        check("solo:旧树名wt-mc-<task_id>", solo.get("mc_wt") == "/data/bench/wt-mc-selftest-solo"
              and solo.get("mc_ref") == "merge-check/selftest-solo", str(solo.get("mc_wt")))
        check("solo:旧路径compound含step0注册校验", "ci/mutation_runner.sh check-registry" in mock.cmds[-1]
              and "STEP0_OK" in mock.outs[-1], mock.cmds[-1][-200:])

        # merge.group 显式声明优先
        g1 = _mkcard("selftest-g1", ["feature/selftest-g1"], merge={"group": "custom-grp", "branches": [{"ref": "feature/selftest-g1"}]})
        g2 = _mkcard("selftest-g2", ["feature/selftest-g2"], merge={"group": "custom-grp", "branches": [{"ref": "feature/selftest-g2"}]})
        wave4 = {"wave": "wave-grp", "cards": [g1, g2]}
        ok, ev = merge_check_batch(g1, [wave4])
        check("group:显式group优先", ok == "testing" and g1.get("mc_wt") == "/data/bench/wt-mc-custom-grp",
              str(g1.get("mc_wt")))

        # 在飞树 ⇒ 就绪卡等待（不重复建树）
        w5cards = [_mkcard("selftest-w%d" % i, ["feature/selftest-w%d" % i]) for i in (1, 2)]
        wave5 = {"wave": "wave-inflight", "cards": w5cards}
        merge_check_batch(w5cards[0], [wave5])  # 建树，两卡 merge-testing
        late = _mkcard("selftest-late", ["feature/selftest-late"])
        wave5["cards"].append(late)
        ok, ev = merge_check_batch(late, [wave5])
        check("inflight:在飞树就绪卡等待", ok == "wait" and late["state"] == "verifying", ev)

        # 负例1：一支 M_FAIL ⇒ 全组 parked+逐卡异常
        mock.fail_branches = {"feature/selftest-n2"}
        ncards = [_mkcard("selftest-n%d" % i, ["feature/selftest-n%d" % i]) for i in (1, 2, 3)]
        waven = {"wave": "wave-neg", "cards": ncards}
        ok, ev = merge_check_batch(ncards[0], [waven])
        check("neg:合线失败返回parked", ok == "parked")
        check("neg:全组parked", all(c["state"] == "parked" for c in ncards))
        nexc = [json.loads(l) for l in open(EXC)] if os.path.exists(EXC) else []
        check("neg:逐卡异常入队", len(nexc) == 3 and {e["task_id"] for e in nexc} == {c["task_id"] for c in ncards})
        mock.fail_branches = set()

        # 负例2：env-check FAIL ⇒ compound 中止、无 M_OK ⇒ parked（fail-closed）
        mock.env_ok = False
        ecards = [_mkcard("selftest-e%d" % i, ["feature/selftest-e%d" % i]) for i in (1, 2)]
        wavee = {"wave": "wave-envneg", "cards": ecards}
        ok, ev = merge_check_batch(ecards[0], [wavee])
        check("neg:env-check FAIL⇒parked", ok == "parked" and "env-check FAIL" in ev, ev)
        check("neg:env FAIL 不进树", all(c["state"] == "parked" for c in ecards))
        mock.env_ok = True

        # 负例3：verifying 卡无 branches ⇒ 旧路径报错（不静默）
        nob = _mkcard("selftest-nob", [])
        ok, ev = merge_check_batch(nob, [{"wave": "wave-nob", "cards": [nob]}])
        check("neg:无branches报错", ok is False and "branches" in ev, ev)

        # 负例4：step0 mutations 注册校验 FAIL（注册表 sha256 漂移/基线缺席）⇒ 全组
        # parked+逐卡异常（v5 补合线门面缺口；复盘 C3-②「mutation 不过不得合流」）
        mock.step0_drift = True
        scards = [_mkcard("selftest-s%d" % i, ["feature/selftest-s%d" % i]) for i in (1, 2)]
        wavestep0 = {"wave": "wave-step0neg", "cards": scards}
        n_exc0 = len(open(EXC).readlines()) if os.path.exists(EXC) else 0
        ok, ev = merge_check_batch(scards[0], [wavestep0])
        check("neg:step0漂移返回parked", ok == "parked" and "STEP0_OK" in ev, ev)
        check("neg:step0漂移全组parked", all(c["state"] == "parked" for c in scards))
        check("neg:step0漂移compound含check-registry", "ci/mutation_runner.sh check-registry" in mock.cmds[-1])
        nexc4 = [json.loads(l) for l in open(EXC)] if os.path.exists(EXC) else []
        check("neg:step0漂移逐卡异常入队", len(nexc4) == n_exc0 + 2
              and {e["task_id"] for e in nexc4[n_exc0:]} == {c["task_id"] for c in scards})
        mock.step0_drift = False

        # 波次 JSON 落盘剥离内部键
        out = {k: v for k, v in wave.items() if not k.startswith("_")}
        check("persist:内部键不落盘", "_file" not in out and "_batch_dirty" not in out and "runner_touched_at" not in out)
    finally:
        DRY["on"], DRY["ssh_fn"], DRY["sh_fn"] = False, None, None
        EXC = old_exc
        shutil.rmtree(tmp, ignore_errors=True)
    bad = [n for n, c, _ in results if not c]
    print("SELFTEST %d/%d PASS%s" % (len(results) - len(bad), len(results),
                                     ("｜FAIL:" + ",".join(bad)) if bad else ""))
    return 0 if not bad else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    sys.exit(main())
