#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ci-gatecode-trace-check.py — 门码入库可追溯门（波次B · B4 链 · 债号 RT-E83）。

债（逃逸问题台账.md:707-712「RT-E83（medium）轮2 修复批再次全部未落 git」）：
  · 拦截机制①（**修复收口门**）：修复轮判定前 `git status --porcelain` 对涉案树
    必须为空（或仅白名单），修复新增件 `git ls-files` 必须可解析。
  · 拦截机制②（**修复回放必须在 HEAD 干净 checkout 上跑**）：工作树绿不算落地。
  · 拦截机制③（**修复台账（树+件清单）与 `git ls-tree <tree> HEAD` 机器对账**）。
  · 该笔「修复对账」栏自记「『修复收口门』机制①②③仍未见施工，同型复发条件未
    根除」——RT-E83 的两个前两轮复发（轮1「未提交即灭失」、轮2「门码零 git 可
    追溯」）之所以能同型复发，正是因为**没有任何机器断言在门码面落地前叫停**。

本门做什么（只读、零改动、fail-closed）：
  leg-1 判据源单一源：门码面定义（ci/ 门码面 + 判据/证据正本 + 策略正本数据面）
        与排除面（运行证据面 ci/out/ + 历史快照面 *.bak）**单一源复用** af 仓
        `ci/fix_verify.py`（载基线 ref 的提交面副本执行 ⇒ 与 af 仓判据逐字同源，
        本门不另写一份清单；清单手写会随门族增删而陈年化＝RT-E6/E51 同型漏钉）。
        载不进来 ⇒ rc=2 不可证（不猜绿）。
  leg-2 **机制①（工作树面收口）**：逐棵在册工作树跑 `git status --porcelain -z`，
        门码面命中即红并点名（树 / XY 态 / 路径）：
          · 新增件「??」且 `git ls-files -- <路径>` 解析不到 ⇒ 红「未入库
            （git ls-files 不可解析）」；
          · 新增件「??」但 `git ls-files` 解析得到（已 git add 未提交）⇒ 仍红
            「已入库未提交」（机制②：HEAD 干净 checkout 上跑不到这份件）。
        排除面命中 ⇒ 白名单计数（不判红）；非门码面路径 ⇒ 计数不判红（本门
        判定对象是**门码**的入库可追溯性；证据面/构建产物非门码，见边界登记）。
  leg-3 **机制②（HEAD 干净 checkout 等价）**：门码面逐件双核——工作树面 sha256
        vs HEAD 提交面 blob sha256。分叉＝「工作树绿但 HEAD 不绿」（未提交改动）
        ⇒ 红；HEAD 有而盘上无 ⇒ 红（工作树不是干净 checkout）；盘上有而 HEAD 无
        ⇒ 红（新增件未入库）。
  leg-4 **机制③（台账 ⇄ `git ls-tree <tree> HEAD` 机器对账）**：以索引面
        （`git ls-files`＝机器台账）与该树 HEAD 提交面（`git ls-tree -r <tree> HEAD`）
        逐键对账：台账有而提交面无（已入库未提交）⇒ 红；提交面有而台账无（件掉出
        索引）⇒ 红；两行数差 ⇒ 红并记数。
  leg-5 **入库可追溯性（可达性对账）**：每棵树的 HEAD 提交必须被仓内至少一个本地
        分支包含（`git branch --contains <HEAD>`）——否则「入库但不可追溯到任何
        分支」（悬空提交）⇒ 红。
  leg-6 fail-closed：仓不可读 / 工作树枚举失败 ⇒ rc=2；树无 HEAD ⇒ 红。

退出码：0=绿 / 1=红（门码面有未提交改动、未入库件、提交面分叉、不可追溯）/ 2=不可证。
用法：python3 -I tools/ci-gatecode-trace-check.py [--repo DIR] [--base-ref REF]
      [--json] [--selftest]
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

DEFAULT_BASE_REF = "phase2"
# af 仓判据源（门码面 + 排除面定义 + ls-tree/oid 取件器）：单一源，本门不另写
SRC_REL = "ci/fix_verify.py"


def die(msg, code=2):
    sys.stderr.write("[FATAL] %s\n" % msg)
    sys.exit(code)


def git(repo, *args, check=True):
    p = subprocess.run(["git", "-C", repo] + list(args),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and p.returncode != 0:
        return None
    return p.stdout.decode("utf-8", "replace")


def git_bytes(repo, *args):
    p = subprocess.run(["git", "-C", repo] + list(args),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        return None
    return p.stdout


def git_show_bytes(repo, spec):
    return git_bytes(repo, "show", spec)


def load_criteria(repo, base_ref):
    """载入 af 仓判据源（基线 ref 提交面），复用其门码面/排除面定义与取件器。

    载入失败 ⇒ (None, 原因)。理由必须带路径与 ref，便于归因。
    """
    raw = git_show_bytes(repo, "%s:%s" % (base_ref, SRC_REL))
    if raw is None:
        return None, "判据源 %s:%s 不可读（基线 ref 缺该提交面？）" % (base_ref, SRC_REL)
    tmp = tempfile.mkdtemp(prefix="ci-gatecode-criteria-")
    try:
        path = os.path.join(tmp, "fix_verify.py")
        with open(path, "wb") as fh:
            fh.write(raw)
        import importlib.util
        spec = importlib.util.spec_from_file_location("af_fixverify_criteria", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as exc:                                      # noqa: BLE001
        return None, "判据源 %s:%s 不可导入（%s）" % (base_ref, SRC_REL, exc)
    need = ("GATE_DIR", "GATE_EXCLUDE_PREFIXES", "GATE_EXCLUDE_SUFFIXES",
            "CRITERIA_FILES", "DATA_DIRS", "DATA_FILES")
    miss = [n for n in need if not hasattr(mod, n)]
    if miss:
        return None, ("判据源 %s:%s 缺 %s（判据源被改写？）"
                      % (base_ref, SRC_REL, ",".join(miss)))
    return {"mod": mod, "path": "%s:%s" % (base_ref, SRC_REL)}, None


def in_gate_surface(mod, path):
    """该路径是否属门码面（ci/ 门码面 + 判据/证据正本 + 策略正本数据面），
    且不在排除面（运行证据面 ci/out/ + 历史快照面 *.bak）。判据同源。"""
    if mod.surface_excluded(path):
        return False
    if path.startswith(mod.GATE_DIR + "/"):
        return True
    if path in mod.CRITERIA_FILES:
        return True
    if any(path.startswith(d.rstrip("/") + "/") for d in mod.DATA_DIRS):
        return True
    if path in mod.DATA_FILES:
        return True
    return False


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


def porcelain_entries(tree_path):
    """`git status --porcelain -z` 解析 → [(XY, path)]；读不出 ⇒ None。"""
    raw = git_bytes(tree_path, "status", "--porcelain", "-z",
                    "--untracked-files=normal")
    if raw is None:
        return None
    parts = raw.decode("utf-8", "replace").split("\0")
    out = []
    i = 0
    while i < len(parts):
        e = parts[i]
        i += 1
        if not e:
            continue
        if len(e) < 3:
            continue
        xy = e[:2]
        path = e[3:]
        if xy[0] in ("R", "C") and i < len(parts):
            path = parts[i]      # rename/copy：-z 形态下原路径在后一段
            i += 1
        out.append((xy, path))
    return out


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
    rep = {"repo": repo, "base_ref": base_ref, "red": [], "lines": [], "trees": [],
           "warn": []}
    crit, err = load_criteria(repo, base_ref)
    if crit is None:
        rep["red"].append("判据源不可用：%s" % err)
        return rep
    mod = crit["mod"]
    rep["criteria_source"] = crit["path"]

    trees = list_worktrees(repo)
    if trees is None:
        rep["red"].append("工作树枚举失败（git worktree list 不可读）")
        return rep

    for t in trees:
        path = t["path"]
        head = t.get("head")
        branch = t.get("branch")
        label = branch or "(detached)"
        entry = {"path": path, "branch": branch, "dirty_gate": [],
                 "dirty_gate_paths": [], "white": 0, "outside": 0, "missing": [],
                 "extra": [], "diverged": [], "ledger_extra": [],
                 "ledger_missing": [], "ignored": []}
        rep["trees"].append(entry)
        if not head:
            rep["red"].append("工作树 %s（%s）无 HEAD 记录——不可判定，红" % (path, label))
            continue

        # ---- leg-2 机制①：工作树面收口（porcelain 必须为空/仅白名单） ----
        entries = porcelain_entries(path)
        if entries is None:
            rep["red"].append("工作树 %s（%s）git status --porcelain 不可读——不可判定，红"
                              % (path, label))
            continue
        for xy, rel in entries:
            if mod.surface_excluded(rel):
                entry["white"] += 1
                continue
            if not in_gate_surface(mod, rel):
                entry["outside"] += 1
                continue
            entry["dirty_gate"].append(xy + " " + rel)
            entry["dirty_gate_paths"].append(rel)
            tracked = git(path, "ls-files", "-z", "--", rel)
            if xy == "??" and not (tracked or "").strip():
                rep["red"].append("[%s] 门码面新增件未入库：%s（git status 态 ??，"
                                  "git ls-files 不可解析）——修复新增件未落 git，红"
                                  % (label, rel))
            else:
                rep["red"].append("[%s] 门码面有未提交工作树改动：%s（git status 态 %s）"
                                  "——未提交≠已落地（机制②：工作树绿不算落地），红"
                                  % (label, rel, xy))

        # ---- 盘面（git 可见盘面＝索引面 + 未跟踪未忽略件；被 .gitignore 排除的件
        #      不进版本面、不判红，另记 WARN 计数并点名） ----
        ledger_raw = git(path, "ls-files", "-z")
        if ledger_raw is None:
            rep["red"].append("[%s] 索引台账不可读（git ls-files）——无法对账，红" % label)
            continue
        ledger_set = {r for r in ledger_raw.split("\0")
                      if r and in_gate_surface(mod, r)}
        untracked_raw = git(path, "ls-files", "-z", "--others", "--exclude-standard")
        untracked_set = {r for r in (untracked_raw or "").split("\0")
                         if r and in_gate_surface(mod, r)}
        disk_set = ledger_set | untracked_set
        ignored_raw = git(path, "ls-files", "-z", "--others", "--ignored",
                          "--exclude-standard")
        ignored_set = [r for r in (ignored_raw or "").split("\0")
                       if r and in_gate_surface(mod, r)]
        if ignored_set:
            entry["ignored"] = ignored_set
            rep["warn"].append("[%s] 门码面内有被 .gitignore 排除的件 %d 件（不进版本面、"
                                "不判红）：%s" % (label, len(ignored_set),
                                                ",".join(ignored_set[:5])))

        # ---- leg-3 机制②：盘面 ⇄ 提交面 逐件内容双核 ----
        maps = mod.surface_maps(repo, head)
        if maps is None:
            rep["red"].append("[%s] 该树 HEAD(%s) 提交树不可读——无法对账，红"
                              % (label, head[:12]))
            continue
        ci, crit_map, data = maps
        head_surf = mod.collect_surface(ci, crit_map, data)      # {path: oid}
        head_set = set(head_surf)
        reported = set(entry["dirty_gate_paths"])

        for rel in sorted(disk_set - head_set):
            if rel in reported:
                continue
            entry["extra"].append(rel)
            rep["red"].append("[%s] 门码面工作树面多件：%s（不在该树 HEAD 提交面内）"
                              "——新增件未入库，红" % (label, rel))
        for rel in sorted(head_set & disk_set):
            full = os.path.join(path, rel)
            if not os.path.isfile(full):
                entry["missing"].append(rel)
                rep["red"].append("[%s] 门码面提交面件在工作树面缺失：%s——该树不是 "
                                  "HEAD 干净 checkout（机制②），红" % (label, rel))
                continue
            wt_sha = mod.sha256_file(full)
            head_sha = mod.blob_sha256(repo, "%s:%s" % (head, rel), {})
            if head_sha is None:
                rep["red"].append("[%s] 门码面提交面件不可读：%s——不可判定，红"
                                  % (label, rel))
                continue
            if wt_sha != head_sha:
                entry["diverged"].append(rel)
                rep["red"].append("[%s] 门码面分叉（工作树面 ≠ HEAD 提交面）：%s "
                                  "sha256=%s… ≠ %s…——未提交改动，红"
                                  % (label, rel, (wt_sha or "?")[:12], head_sha[:12]))

        # ---- leg-4 机制③：台账（索引面）⇄ git ls-tree <tree> HEAD 机器对账 ----
        for rel in sorted(ledger_set - head_set):
            entry["ledger_extra"].append(rel)
            rep["red"].append("[%s] 台账多键：%s 在 git ls-files 台账内但不在 "
                              "git ls-tree %s HEAD 内——已入库未提交，红"
                              % (label, rel, head[:12]))
        for rel in sorted(head_set - ledger_set):
            entry["ledger_missing"].append(rel)
            rep["red"].append("[%s] 台账缺键：%s 在 git ls-tree %s HEAD 内但不在 "
                              "git ls-files 台账内——件掉出索引，红"
                              % (label, rel, head[:12]))
        if len(ledger_set) != len(head_set):
            rep["red"].append("[%s] 台账与提交面行数不符：ls-files %d 件 vs "
                              "ls-tree HEAD %d 件——件清单对账不平，红"
                              % (label, len(ledger_set), len(head_set)))

        # ---- leg-5 入库可追溯性：HEAD 须被至少一个本地分支包含 ----
        contained = (git(repo, "branch", "--contains", head) or "").split()
        if not [c for c in contained if not c.startswith("*") and not c.startswith("+")]:
            rep["red"].append("[%s] 该树 HEAD(%s) 不被仓内任何本地分支包含——"
                              "入库但不可追溯（悬空提交），红" % (label, head[:12]))

        if not entry["dirty_gate"] and not entry["missing"] and not entry["extra"] \
                and not entry["diverged"] and not entry["ledger_extra"] \
                and not entry["ledger_missing"]:
            rep["lines"].append("OK  %s（%s）：门码面 %d 件已入库可追溯"
                                "（盘面 ≡ HEAD 提交面 ≡ 索引台账；白名单 %d 件、"
                                "非门码面 %d 件不判）"
                                % (label, path, len(head_surf), entry["white"],
                                   entry["outside"]))
        else:
            rep["lines"].append("门码面异常 %s（%s）：脏 %d / 缺 %d / 多 %d / 分叉 %d / "
                                "台账多 %d / 台账缺 %d"
                                % (label, path, len(entry["dirty_gate"]),
                                   len(entry["missing"]), len(entry["extra"]),
                                   len(entry["diverged"]), len(entry["ledger_extra"]),
                                   len(entry["ledger_missing"])))
    return rep


def selftest(real_repo, base_ref):
    """夹具自证：沙箱造「未提交改动 / 未入库新增件 / 已入库未提交 / 删件 /
    悬空提交」五种形态，门必须红且点名；不扰动则绿。"""
    tmp = tempfile.mkdtemp(prefix="ci-gatecode-selftest-")
    repo = os.path.join(tmp, "repo")
    os.makedirs(os.path.join(repo, "ci"), exist_ok=True)
    crit_raw = git_show_bytes(real_repo, "%s:%s" % (base_ref, SRC_REL))
    if crit_raw is None:
        print("[FAIL] selftest：真仓判据源 %s:%s 不可读，夹具无法同源"
              % (base_ref, SRC_REL))
        print("SELFTEST_RESULT: FAIL")
        return 1
    with open(os.path.join(repo, "ci", "fix_verify.py"), "wb") as fh:
        fh.write(crit_raw)

    def sh(*args):
        return subprocess.run(["git", "-C", repo] + list(args), stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE).stdout.decode("utf-8", "replace")

    def write(rel, text):
        full = os.path.join(repo, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(text)

    sh("init", "-q", "-b", "main")
    sh("config", "user.email", "selftest@example.invalid")
    sh("config", "user.name", "selftest")
    write("ci/run.sh", "# gate runner\n")
    write("ci/xcheck.py", "# gate family\n")
    write("ci/subgates.list", "# roster\nxcheck\n")
    write("numbers.json", '{"numbers": {}}\n')
    write("strategies/a.yaml", "id: a\n")
    sh("add", "-A")
    sh("commit", "-qm", "base")
    write("ci/fix_verify.py", crit_raw.decode("utf-8", "replace"))

    ok = True

    def expect_red(tag, needle):
        nonlocal ok
        rep = check(repo, "main")
        if not rep["red"]:
            print("[FAIL] selftest：%s 未判红——门无判别力" % tag)
            ok = False
            return
        hit = any(needle in m for m in rep["red"])
        print("%s selftest %s 判红%s：%s"
              % ("OK  " if hit else "[FAIL]", tag, "且点名" if hit else "但未点名",
                 "; ".join(rep["red"])[:180]))
        ok = ok and hit

    def expect_green(tag):
        nonlocal ok
        rep = check(repo, "main")
        if rep["red"]:
            print("[FAIL] selftest：%s 判红：%s" % (tag, "; ".join(rep["red"])[:200]))
            ok = False
        else:
            print("OK   selftest %s 全绿" % tag)

    # 臂1：门码面未提交改动 ⇒ 红（点名）
    write("ci/xcheck.py", "# gate family\n# tampered\n")
    expect_red("未提交改动臂", "ci/xcheck.py")
    write("ci/xcheck.py", "# gate family\n")

    # 臂2：新增件未入库（未 git add）⇒ 红（点名 + git ls-files 不可解析）
    write("ci/newgate.py", "# new gate\n")
    expect_red("未入库新增件臂", "ci/newgate.py")
    os.remove(os.path.join(repo, "ci", "newgate.py"))

    # 臂3：新增件已 git add 未提交 ⇒ 仍红（机制②：工作树绿≠落地）
    write("ci/newgate.py", "# new gate\n")
    sh("add", "ci/newgate.py")
    expect_red("已入库未提交臂", "ci/newgate.py")
    sh("reset", "-q", "HEAD", "--", "ci/newgate.py")
    os.remove(os.path.join(repo, "ci", "newgate.py"))

    # 臂4：门码面件被删（未提交）⇒ 红（点名）
    os.remove(os.path.join(repo, "ci", "xcheck.py"))
    expect_red("删件臂", "ci/xcheck.py")
    write("ci/xcheck.py", "# gate family\n")

    # 臂5：悬空提交（HEAD 不被任何本地分支包含）⇒ 红（可追溯性）
    #      用第二棵工作树造，基线分支 main 不动（基线 ref 必须始终可读）。
    wt2 = os.path.join(tmp, "wt2")
    sh("worktree", "add", "-q", "-b", "tmpb", wt2)
    with open(os.path.join(wt2, "ci", "dangling.py"), "w", encoding="utf-8") as fh:
        fh.write("# dangling\n")
    subprocess.run(["git", "-C", wt2, "add", "-A"], stdout=subprocess.DEVNULL)
    subprocess.run(["git", "-C", wt2, "commit", "-qm", "d2"], stdout=subprocess.DEVNULL)
    subprocess.run(["git", "-C", wt2, "checkout", "-q", "--detach", "HEAD"],
                   stdout=subprocess.DEVNULL)
    subprocess.run(["git", "-C", wt2, "branch", "-q", "-D", "tmpb"], stdout=subprocess.DEVNULL)
    expect_red("悬空提交臂", "不可追溯")
    subprocess.run(["git", "-C", repo, "worktree", "remove", "--force", wt2],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # 对照臂：全部落库 + HEAD 在分支上 ⇒ 绿
    sh("add", "-A")
    sh("commit", "-qm", "landed")
    expect_green("全落库对照臂")
    print("SELFTEST_RESULT: %s（改面必红点名 / 不改必绿）" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description="门码入库可追溯门（RT-E83 机制①②③）")
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
    st, msg = cron_leg("ci-gatecode-trace-check")
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
        print("CI_GATECODE_TRACE: FAIL（红 %d 项）" % len(rep["red"]))
        return 1
    print("CI_GATECODE_TRACE: PASS（判据源=%s，基线=%s，在册树 %d 棵）"
          % (rep.get("criteria_source", "?"), args.base_ref, len(rep["trees"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
