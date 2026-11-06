#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ci-crosstree-subgate-set-check.py — 跨树子门集合比较门（波次B · B4 链 · 债号 RT-E82）。

债（逃逸问题台账.md:700-705「RT-E82（medium）g0merge 合流主线 run.sh 零处
strategies_check —— 策略库全量校验+af-dsl 编译断言门只存在于 sil-writeback 一棵树，
钉键=3 以现状为基准自洽绿（基线手写/跨工作树假绿）」）：
  · 拦截机制①（**跨树集合比较门**）：合流/验收脚本断言「验收树子门集合 ⊇ 各来源活树
    子门集合」（`git show <tree>:ci/run.sh` 提取子门名做集合比较，缺件点名）。
  · 该笔的修复对账栏自记「策略库门已接双树；**跨树集合比较门（机制①）未见施工**」——
    即**机制① 至今没有机器实现**：RT-E81 的 `ci/subgates.list` 名册绑定
    （ci/step12_check.py 第四节 + ci/xcheck.py 子门级断言）是**逐树**的自洽判定，
    每棵树拿自己的名册比自己的 run.sh ⇒ 一棵树把名册与接线**一起**改小，仍自洽照绿
    （=RT-E82 的「基线手写」形态）；跨树集合比较（拿一棵树的集合比另一棵/比基线）
    才是治它的那道门。

本门做什么（只读、零改动、fail-closed）：
  leg-1 判据源在位：子门接线抽取正则与名册条目正则**单一源复用** af 仓
        `ci/step12_check.py`（取基线 ref 的提交面副本载入执行 ⇒ 与 af 仓判据逐字同源，
        本门不另写一份正则）；载不进来 ⇒ rc=2 不可证（不猜绿）。
  leg-2 基线正本自洽：基线 ref 自身的 `ci/run.sh` 接线集合 ≡ 基线 ref 自身
        `ci/subgates.list` 名册集合 ⇒ 不一致即红（「基线名册与基线接线分叉」＝
        RT-E82「基线手写」的源头形态）。
  leg-3 **跨树集合比较（机制① 本体）**：逐棵在役工作树，取**提交面**
        （`git show <tree>:ci/run.sh`）的 step14 接线子门集合，
        与基线正本集合 C 比：
          · 缺件（C − S(T)）⇒ 红，**点名缺哪个子门**（机制①「缺件点名」原文要求）；
          · 多件（S(T) − C）⇒ 记「在飞超前项」，不判红（该树领先基线是合流前的
            正常态；治「缺」不治「多」＝机制① 方向：验收树 ⊇ 各来源活树）。
  leg-4 范围口径：只在**带 G0 门族**（提交面含 `ci/xcheck.py`）的工作树上判；
        无门族的树（名册 archived 且「无 G0 门族」者，如 phase2-execline-p6）不在
        比较面内（它没有子门集合可比）⇒ 逐条记明跳过理由，不静默。
  leg-5 fail-closed：任一在册树提交面读不出（run.sh 不可解析/不可读）⇒ 红
        （不可判定 ≠ 一致）；工作树枚举失败 ⇒ rc=2。

退出码：0=绿 / 1=红（集合缺件或基线自洽破） / 2=不可证（判据源不在位/仓不可读）。
用法：python3 -I tools/ci-crosstree-subgate-set-check.py [--repo DIR] [--base-ref REF]
      [--json] [--selftest]
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

DEFAULT_BASE_REF = "phase2"
# af 仓判据源：子门接线抽取正则 + 名册条目正则（单一源，本门不另写一份）
SRC_REL = "ci/step12_check.py"
SRC_REPO_DIR = "ci"


def die(msg, code=2):
    sys.stderr.write("[FATAL] %s\n" % msg)
    sys.exit(code)


def git(repo, *args, check=True):
    p = subprocess.run(["git", "-C", repo] + list(args),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and p.returncode != 0:
        return None
    return p.stdout.decode("utf-8", "replace")


def git_show(repo, spec):
    """提交面 blob 文本；不存在 ⇒ None。"""
    p = subprocess.run(["git", "-C", repo, "show", spec],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        return None
    return p.stdout.decode("utf-8", "replace")


def load_criteria(repo, base_ref):
    """载入 af 仓判据源（基线 ref 提交面），复用其 SUBGATE_WIRE_RE / ROSTER_ENTRY_RE。

    载入失败 ⇒ (None, 原因)。理由必须带路径与 ref，便于归因。
    """
    text = git_show(repo, "%s:%s" % (base_ref, SRC_REL))
    if text is None:
        return None, "判据源 %s:%s 不可读（基线 ref 缺该提交面？）" % (base_ref, SRC_REL)
    tmp = tempfile.mkdtemp(prefix="ci-subgate-criteria-")
    try:
        path = os.path.join(tmp, "step12_check.py")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        import importlib.util
        spec = importlib.util.spec_from_file_location("af_step12_criteria", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as exc:                                      # noqa: BLE001
        return None, "判据源 %s:%s 不可导入（%s）" % (base_ref, SRC_REL, exc)
    wire = getattr(mod, "SUBGATE_WIRE_RE", None)
    entry = getattr(mod, "ROSTER_ENTRY_RE", None)
    if wire is None or entry is None:
        return None, ("判据源 %s:%s 缺 SUBGATE_WIRE_RE/ROSTER_ENTRY_RE（判据源被改写？）"
                      % (base_ref, SRC_REL))
    return {"wire": wire, "entry": entry, "path": "%s:%s" % (base_ref, SRC_REL)}, None


def wired_set(run_sh_text, wire_re):
    """从 run.sh 文本取 step14 接线子门集合（判据源同源正则）。"""
    names = set()
    for line in run_sh_text.splitlines():
        m = wire_re.match(line)
        if m:
            names.add(m.group("name"))
    return names


def roster_set(text, entry_re):
    """从 ci/subgates.list 文本取名册集合（判据源同源条目正则）。"""
    names = []
    for raw in text.splitlines():
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        if not entry_re.match(s):
            continue
        names.append(s)
    return set(names)


def list_worktrees(repo):
    """(path, head, branch|None) 列表；仓不可读 ⇒ None。"""
    out = git(repo, "worktree", "list", "--porcelain")
    if out is None:
        return None
    trees = []
    cur = {}
    for line in out.splitlines():
        if line.startswith("worktree "):
            if cur:
                trees.append(cur)
            cur = {"path": line[len("worktree "):].strip()}
        elif line.startswith("HEAD "):
            cur["head"] = line[len("HEAD "):].strip()
        elif line.startswith("branch "):
            cur["branch"] = line[len("branch "):].strip().replace("refs/heads/", "")
    if cur:
        trees.append(cur)
    return trees


def has_gate_family(repo, head):
    p = subprocess.run(["git", "-C", repo, "cat-file", "-e", "%s:%s/xcheck.py" % (head, SRC_REPO_DIR)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return p.returncode == 0


def cron_leg(marker):
    """门位在位断言：crontab 内须有本门巡检行（整表覆盖会把它抹掉⇒门位静默停摆）。

    crontab 不可读 ⇒ 不可证（记 WARN，不判红）；可读但无本门行 ⇒ 红。
    返回 (状态, 文案)，状态 ∈ ok/warn/red。
    """
    p = subprocess.run(["crontab", "-l"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        return "warn", ("门位在位不可证：crontab -l 不可读（rc=%d）——不判红，"
                        "请人工核门位" % p.returncode)
    if marker in p.stdout.decode("utf-8", "replace"):
        return "ok", "门位在位：crontab 内含本门巡检行（marker=%s）" % marker
    return "red", ("门位被抹：crontab 内无本门巡检行（marker=%s）——巡检停摆"
                   "（门位在位断言），红" % marker)


def check(repo, base_ref):
    rep = {"repo": repo, "base_ref": base_ref, "red": [], "lines": [], "trees": []}
    crit, err = load_criteria(repo, base_ref)
    if crit is None:
        rep["red"].append("判据源不可用：%s" % err)
        return rep
    rep["criteria_source"] = crit["path"]

    # leg-2 基线正本自洽
    base_run = git_show(repo, "%s:%s/run.sh" % (base_ref, SRC_REPO_DIR))
    base_roster = git_show(repo, "%s:%s/subgates.list" % (base_ref, SRC_REPO_DIR))
    if base_run is None:
        rep["red"].append("基线 %s:ci/run.sh 不可读——基线正本缺失，不可判定≠一致" % base_ref)
        return rep
    base_wired = wired_set(base_run, crit["wire"])
    if base_roster is None:
        rep["red"].append("基线 %s:ci/subgates.list 不可读——基线名册缺失，红" % base_ref)
        return rep
    base_names = roster_set(base_roster, crit["entry"])
    if base_wired != base_names:
        rep["red"].append("基线名册与基线接线分叉：名册−接线=%s 接线−名册=%s"
                          % (sorted(base_names - base_wired), sorted(base_wired - base_names)))
    else:
        rep["lines"].append("OK  基线 %s 自洽：名册 ≡ 接线（%d 件：%s）"
                            % (base_ref, len(base_wired), ",".join(sorted(base_wired))))

    trees = list_worktrees(repo)
    if trees is None:
        rep["red"].append("工作树枚举失败（git worktree list 不可读）")
        return rep
    C = base_wired
    for t in trees:
        path = t["path"]
        head = t.get("head")
        branch = t.get("branch")
        label = branch or "(detached)"
        if not head:
            rep["red"].append("工作树 %s 无 HEAD 记录——不可判定，红" % path)
            continue
        if not has_gate_family(repo, head):
            rep["trees"].append({"path": path, "branch": branch, "skipped": "无 G0 门族（不在比较面）"})
            rep["lines"].append("SKIP %s（%s）：无 G0 门族（提交面无 ci/xcheck.py）——不在比较面内"
                                % (path, label))
            continue
        run_text = git_show(repo, "%s:%s/run.sh" % (head, SRC_REPO_DIR))
        if run_text is None:
            rep["red"].append("工作树 %s（%s）提交面 ci/run.sh 不可读——不可判定，红" % (path, label))
            continue
        S = wired_set(run_text, crit["wire"])
        missing = sorted(C - S)
        extra = sorted(S - C)
        entry = {"path": path, "branch": branch, "wired": sorted(S),
                 "missing": missing, "extra": extra}
        rep["trees"].append(entry)
        if missing:
            rep["red"].append("跨树集合差：工作树 %s（%s）缺子门 %s——机制①「缺件点名」"
                              % (path, label, ",".join(missing)))
        if extra:
            rep["lines"].append("WARN 工作树 %s（%s）多子门 %s（在飞超前项，不判红）"
                                % (path, label, ",".join(extra)))
        else:
            rep["lines"].append("OK  工作树 %s（%s）子门集合 ≡ 基线（%d 件）"
                                % (path, label, len(S)))
    return rep


def selftest(real_repo, base_ref):
    """夹具自证：沙箱造「缺件树」，门必须红且点名缺件；不扰动则绿。

    判据源仍取真 af 仓基线提交面的 ci/step12_check.py（拷贝进夹具仓 ⇒ 夹具与生产
    同源正则，不另写一份）。
    """
    tmp = tempfile.mkdtemp(prefix="ci-subgate-selftest-")
    repo = os.path.join(tmp, "repo")
    os.makedirs(os.path.join(repo, "ci"), exist_ok=True)
    crit_text = git_show(real_repo, "%s:%s" % (base_ref, SRC_REL))
    if crit_text is None:
        print("[FAIL] selftest：真仓判据源 %s:%s 不可读，夹具无法同源" % (base_ref, SRC_REL))
        print("SELFTEST_RESULT: FAIL")
        return 1
    with open(os.path.join(repo, "ci", "step12_check.py"), "w", encoding="utf-8") as fh:
        fh.write(crit_text)

    def sh(*args, **kw):
        return subprocess.run(["git", "-C", repo] + list(args), stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, **kw).stdout.decode("utf-8", "replace")

    sh("init", "-q", "-b", "main")
    sh("config", "user.email", "selftest@example.invalid")
    sh("config", "user.name", "selftest")
    full = ("# hdr\n"
            "machine_batch() {\n"
            '  (cd "$AF_ROOT" && python3 ci/branches_check.py); rc_a=$?\n'
            '  (cd "$AF_ROOT" && python3 ci/xcheck.py); rc_b=$?\n'
            '  (cd "$AF_ROOT" && python3 ci/criteria_check.py); rc_c=$?\n'
            '  (cd "$AF_ROOT" && python3 -B ci/strategies_check.py); rc_d=$?\n'
            "}\n")
    roster = "# 名册\nbranches_check\nxcheck\ncriteria_check\nstrategies_check\n"
    with open(os.path.join(repo, "ci", "run.sh"), "w", encoding="utf-8") as fh:
        fh.write(full)
    with open(os.path.join(repo, "ci", "subgates.list"), "w", encoding="utf-8") as fh:
        fh.write(roster)
    with open(os.path.join(repo, "ci", "xcheck.py"), "w", encoding="utf-8") as fh:
        fh.write("# gate family\n")
    sh("add", "-A")
    sh("commit", "-qm", "base")
    # 缺件树：另开一棵树，只拿掉 strategies_check 接线（**名册保持 4 件**⇒
    # 该树名册与接线自己分叉，且**跨树**比基线少一件）＝RT-E82 原形态。
    lost_wt = os.path.join(tmp, "lost")
    sh("worktree", "add", "-q", "-b", "lostwt", lost_wt)
    with open(os.path.join(lost_wt, "ci", "run.sh"), "w", encoding="utf-8") as fh:
        fh.write(full.replace('  (cd "$AF_ROOT" && python3 -B ci/strategies_check.py); rc_d=$?\n', ""))
    subprocess.run(["git", "-C", lost_wt, "add", "-A"], stdout=subprocess.DEVNULL)
    subprocess.run(["git", "-C", lost_wt, "commit", "-qm", "drop strategies_check"],
                   stdout=subprocess.DEVNULL)

    ok = True
    # 红路：基线自洽（main 名册≡接线），但缺件树跨树少 strategies_check ⇒ 必红且点名
    rep_g = check(repo, "main")
    if not rep_g["red"]:
        print("[FAIL] selftest：缺件树未判红——门无判别力")
        ok = False
    else:
        hit = any("strategies_check" in m for m in rep_g["red"])
        print("%s selftest 缺件树判红且点名 strategies_check：%s"
              % ("OK  " if hit else "[FAIL]", "; ".join(rep_g["red"])[:200]))
        ok = ok and hit
    # 绿路对照：把缺件树修回 4 件 ⇒ 全绿
    with open(os.path.join(lost_wt, "ci", "run.sh"), "w", encoding="utf-8") as fh:
        fh.write(full)
    subprocess.run(["git", "-C", lost_wt, "add", "-A"], stdout=subprocess.DEVNULL)
    subprocess.run(["git", "-C", lost_wt, "commit", "-qm", "restore"], stdout=subprocess.DEVNULL)
    rep_ok = check(repo, "main")
    if rep_ok["red"]:
        print("[FAIL] selftest：未扰动树判红：%s" % "; ".join(rep_ok["red"])[:200])
        ok = False
    else:
        print("OK   selftest 未扰动树全绿（%d 树在比较面内）"
              % len([t for t in rep_ok["trees"] if "skipped" not in t]))
    print("SELFTEST_RESULT: %s（缺件必红且点名 / 未扰动必绿）" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description="跨树子门集合比较门（RT-E82 机制①）")
    here = os.path.dirname(os.path.abspath(__file__))
    ws = os.path.dirname(here)
    ap.add_argument("--repo", default=os.path.join(ws, "af"))
    ap.add_argument("--base-ref", default=DEFAULT_BASE_REF)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    repo = os.path.abspath(args.repo)
    if not os.path.isdir(repo):
        die("af 仓不在位：%s" % repo, 2)
    if args.selftest:
        return selftest(repo, args.base_ref)
    rep = check(repo, args.base_ref)
    st, msg = cron_leg("ci-crosstree-subgate-set-check")
    if st == "red":
        rep["red"].append(msg)
    elif st == "warn":
        rep["warn"].append(msg)
    else:
        rep["lines"].append("OK  %s" % msg)
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        for ln in rep["lines"]:
            print(ln)
        for wn in rep.get("warn", []):
            print("[WARN] %s" % wn)
    if rep["red"]:
        for m in rep["red"]:
            print("[FAIL] %s" % m)
        print("CI_CROSSTREE_SUBGATE_SET: FAIL（红 %d 项）" % len(rep["red"]))
        return 1
    print("CI_CROSSTREE_SUBGATE_SET: PASS（判据源=%s，基线=%s，在比较面树 %d 棵）"
          % (rep.get("criteria_source", "?"), args.base_ref,
             len([t for t in rep["trees"] if "skipped" not in t])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
