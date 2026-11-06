#!/usr/bin/env python3
"""truth-aggregate.py —— 最终真相 · P3 确定性聚合（方法论：设计/最终真相方法论.md）。

纯确定性：无网络、无 LLM、只读输入文件；所有数字由本脚本从 L0 证据
（results.jsonl + run 目录 agent.diff）算出，每张表前打印重算命令（argv），
供异族代理盲跑逐字节复现（L2）。

输入
  清洁判分行（judge_mode=clean，P1 产物，schema: suite/task_id/profile/reward/
    status/judge_mode/run_dir/eval_sha256/verifier_note）：
      /tmp/truth-rejudge/*/results.jsonl          （truth-rejudge-launcher.py 在写）
      /tmp/bench-rejudge-d*/results.jsonl         （今日早些时候 78 行）
      /tmp/bench-rejudge-fix1*/results.jsonl、/tmp/bench-rejudge2*/results.jsonl
      /tmp/truth-smoke-out/results.jsonl          （P1 冒烟 2 行）
  原始（污染口径）行：各 arm 目录 <arm>/results.jsonl（早期行可能缺 run_dir）。
  arm 目录（默认 scope）：
      /tmp/bench-fix1-d*、/tmp/bench-fix2-ab-*、/tmp/bench-fix2-rerun-*（排除目录名含 test 的变体）
      /tmp/bench-s1-*（rejudge2 互补 scope：s1 选型矩阵代际，按主代理 2026-10-21 19:0x
        巡检决定"接纳并入最终真相范围，聚合时吸收 /tmp/bench-rejudge2-*/results.jsonl"纳入；
        s1 与 fix1 两代际有同名 profile 与同名 run 目录，故聚合表按 gen 代际分列不混口径）
  A/B 配对单：/tmp/bench-fix2-ab-{glm-cp,m31f}/pairing.json

配对规则（键 = (arm, task_id, profile, attempt)）
  - attempt 取自 run 目录名尾部 -a<N>；清洁行 run_dir 一律先取 basename 再解析
    （run_dir 可能指向 /tmp/truth-stage/<job>/runs/NAME 符号链接或 /tmp/rejudge-src-*/NAME）。
  - arm 解析按路径候选链：staging(/tmp/truth-stage/<job>/runs) → run_dir 直指 <arm>/runs →
    realpath 解符号链接；第一个落在 --arm-glob scope 内的候选胜出。解析出但不在 scope
    （如 rejudge2 互补 scope 的 /tmp/bench-s1-* 代际）列入 out-of-scope 清单不进矩阵；
    完全解析不了列入 unresolved。（刻意不做"按 basename 反查 arm"的回退：s1 与 fix1
    两代际存在同名 run 目录，反查会错配，宁可报未解析也不猜。）
  - 原行带 run_dir 且 attempt 与清洁行相同 → 直接配（run_dir-exact）。
  - 原行缺 run_dir：该 (arm,task,profile) 只有单 attempt（盘上 run 目录 ≤1 且原行 ≤1）→ 直接配；
    多 attempt → 取"最后一个非空 reward 行"（与判分污染复核口径一致），输出标 ambiguous=true；
    原行缺失（零行题）→ orig=None（N→*），不猜。
  - 同键多行（跨来源重复判分）：reward 必须一致，否则记 conflict 并不进矩阵（不猜）。

口径（三条并列，不单口径叙事）
  - "有 diff" 与判分器同语义：agent.diff 文件存在即算可判
    （af-bench b3e1f56 main.rs run_swev_rejudge：`if !diff_path.is_file() { continue }`；
    78 行样本即此口径，含 4 个 0 字节 diff 的 run；0 字节另计 empty_diff 列供审计）。
  - 通过率分母 = 有 diff 的已配对立；reward=null/缺失一律按 None 处理：
    绝不当 False 猜，也绝不从分母偷偷消失（None 计非过，并列报 None 行数）。
  - 第二口径：共同已判集（orig 与 clean 均 ∈ {T,F}），剔除 None 行后的配对内比较。

口径续（红队修订 2026-10-21，四项已确证修改）
  - T→F 警示：T→F 非零（清洁判分更严的少数真分歧），单向污染假设按'强主导非绝对'
    口径使用——清洁重判整体上修（F→T 为主），但存在少数 orig=True→clean=False
    的真分歧（经 token 指纹裁定为真分歧、非配对伪影），逐行清单见输出 [2c]。
  - A/B 三口径并排（[3]）：①可比集（双侧均有清洁行，现行为）；②含结构性缺失
    （任一侧 run_failed 且盘上无 agent.diff 的结构性缺口，按 null 计非过纳入）；
    ②b 全量纳入（全部配对题，在途缺口也按 null 计非过）；③在途标注（缺口题逐一
    列因：fix2_run_failed_no_diff / fix1_clean_pending / fix1_clean_null / 其他，
    并注明"数据在途，终值会漂移"）。
  - 任务级去重口径（[2b]）：[2] 表为 attempt 级（含同任务多 attempt 双计）；[2b]
    按 (arm,task_id,profile) 去重，首 attempt 与末 attempt 两种代表取法并列。
  - orig 约定敏感性（[2c]）：多行 orig 组统一取 last-non-null（与判分污染复核口径
    一致）；组内非 null 值不一致时（如 [None,None,True,False] 型），并列
    first-non-null 取法下的判值与 T→F 计数差异。

A/B 修正（任务 2c）
  - fix1 侧：pairing.json 的 fix1_result 替换为清洁重判值（取该 (fix1_arm,task,profile)
    最后一条清洁行；多 attempt 标 ambiguous）；fix2 侧同理取该 (fix2_arm,task,profile)
    最后一行清洁值（spec：/tmp/truth-rejudge/bench-fix2-ab-*/results.jsonl）。
  - 任一侧缺清洁行、或清洁值为 None → 该题跳过并列出原因（不猜、不拿旧值冒充）。
  - 旧口径（未修正，pairing.json fix1_result + fix2 原 results 末行，null 计非过）
    作为参考行一并打印，用于对照底账（glm-cp +13.3pp / m31f -13.3pp，n=15）。

用法
  python3 tools/truth-aggregate.py                     # 全量打表
  python3 tools/truth-aggregate.py --json /tmp/truth-agg.json
  python3 tools/truth-aggregate.py --pending           # 附未判 run 监控段
  python3 tools/truth-aggregate.py --clean-glob '/tmp/bench-rejudge-d*/results.jsonl'   # 只算 78 行核心
输出节: [1] 每 arm 矩阵；[2] profile×tier（attempt 级）；[2b] 任务级去重口径表；
        [2c] T→F 完整清单与 orig 约定敏感性；[3] A/B 三口径；[4] pending(--pending)。
"""
import argparse
import collections
import glob
import json
import os
import re
import shlex
import sys

DEFAULT_CLEAN_GLOBS = [
    "/tmp/truth-rejudge/*/results.jsonl",
    "/tmp/bench-rejudge-d*/results.jsonl",
    "/tmp/bench-rejudge-fix1*/results.jsonl",
    "/tmp/bench-rejudge2*/results.jsonl",
    "/tmp/truth-smoke-out/results.jsonl",
]
DEFAULT_ARM_GLOBS = [
    "/tmp/bench-fix1-d*",
    "/tmp/bench-fix2-ab-*",
    "/tmp/bench-fix2-rerun-*",
    # rejudge2 互补 scope（s1 选型矩阵代际）按主代理 2026-10-21 19:0x 巡检决定
    # "接纳并入最终真相范围，聚合时吸收 /tmp/bench-rejudge2-*/results.jsonl"——
    # 其清洁行经 /tmp/rejudge2-src/<tag>/runs 符号链接指向 /tmp/bench-s1-*，故纳入 scope。
    "/tmp/bench-s1-*",
]
DEFAULT_AB_PAIRINGS = [
    "/tmp/bench-fix2-ab-glm-cp/pairing.json",
    "/tmp/bench-fix2-ab-m31f/pairing.json",
]
ARM_EXCLUDE_TOKEN = "test"  # 与 truth-rejudge-launcher.py 的队列过滤一致
ATTEMPT_RE = re.compile(r"-a(\d+)$")
STAGE_RE = re.compile(r"^/tmp/truth-stage/([^/]+)/runs$")
CELLS = ["TT", "TF", "TN", "FT", "FF", "FN", "NT", "NF", "NN"]
# A/B 缺口分类：这些 status 且 reward=null 视为"运行失败"（结构性，非判分污染）
AB_FAILED_STATUSES = {"run_failed", "setup_failed"}
TF_NOTE = ("T→F 非零（清洁判分更严的少数真分歧），单向污染假设按'强主导非绝对'口径使用")


# ---------------------------------------------------------------- 基础工具

def norm_reward(value):
    """reward → True/False/None；任何非 bool 非 null 的值按 None 处理并原样回报（不猜）。"""
    if value is None:
        return None, None
    if isinstance(value, bool):
        return value, None
    return None, repr(value)


def rlabel(v):
    return {True: "T", False: "F", None: "N"}[v]


def pct(num, den):
    return "  -  " if den == 0 else "%5.1f%%" % (100.0 * num / den)


def delta_pp(before_num, before_den, after_num, after_den):
    if before_den == 0 or after_den == 0:
        return "  -  "
    return "%+0.1fpp" % (100.0 * after_num / after_den - 100.0 * before_num / before_den)


def tier_of(arm):
    m = re.search(r"(?:^|-)d(\d)(?:$|-)", os.path.basename(arm))
    return "d" + m.group(1) if m else "-"


def gen_of(arm):
    """代际（从 arm 目录名）：fix1 / fix2-ab / fix2-rerun / s1 / other。
    s1 与 fix1 两代际有同名 profile，分代并列避免混口径。"""
    b = os.path.basename(arm)
    for pre, gen in [("bench-fix1-", "fix1"), ("bench-fix2-ab-", "fix2-ab"),
                     ("bench-fix2-rerun-", "fix2-rerun"), ("bench-s1-", "s1")]:
        if b.startswith(pre):
            return gen
    return "other"


def run_name_on_disk(run_dir, arm):
    """清洁行 run_dir 的 basename 未必等于盘上 run 目录名：s1 代际的 run 目录无 -a<N>
    后缀，是 rejudge2-src 符号链接农场补的后缀。realpath 落在 arm/runs/ 内时以真实名为准。"""
    rd = os.path.abspath(str(run_dir))
    try:
        rp = os.path.realpath(rd)
    except OSError:
        rp = rd
    if os.path.basename(os.path.dirname(rp)) == "runs" and os.path.dirname(os.path.dirname(rp)) == arm:
        return os.path.basename(rp)
    return os.path.basename(rd)


def sh(cmd):
    return " ".join(shlex.quote(c) for c in cmd)


def rule(char="-", n=100):
    return char * n


# ---------------------------------------------------------------- 载入

def expand_dirs(globs):
    out = []
    for g in globs:
        for d in sorted(glob.glob(g)):
            if os.path.isdir(d) and ARM_EXCLUDE_TOKEN not in os.path.basename(d):
                out.append(d.rstrip("/"))
    return sorted(set(out))


def load_clean_rows(globs):
    """读清洁行；返回 (rows, source_stats, bad_lines)。行可按文件追加中（末行可能半行）。"""
    paths = sorted(set(p for g in globs for p in glob.glob(g) if os.path.isfile(p)))
    rows, stats, bad = [], [], []
    for p in paths:
        n = 0
        with open(p, encoding="utf-8") as f:
            for ln, line in enumerate(f, 1):
                if not line.strip():
                    continue
                try:
                    r = json.loads(line)
                except Exception:
                    bad.append({"source": p, "line": ln, "reason": "json 解析失败（可能写入中的半行）"})
                    continue
                if not isinstance(r, dict):
                    bad.append({"source": p, "line": ln, "reason": "非对象行"})
                    continue
                r["_source"] = p
                r["_line"] = ln
                rows.append(r)
                n += 1
        stats.append({"source": p, "rows": n})
    return rows, stats, bad


def resolve_arm_path(run_dir, arm_set=None):
    """run_dir → (arm 路径, 方法) 或 (None, 原因)。

    按路径候选链解析（staging → 直指 <arm>/runs → realpath 解符号链接），不做
    "按 basename 反查 arm"的回退（s1 与 fix1 两代际存在同名 run 目录，反查会错配，
    宁可报未解析也不猜）。给了 arm_set 时：第一个在 scope 内的候选胜出；候选都在
    scope 外则报最逼近真实 arm 的候选（realpath 优先）并标 -out-of-scope。
    """
    rd = os.path.abspath(str(run_dir))
    parent = os.path.dirname(rd)
    cands = []
    m = STAGE_RE.match(parent)
    if m:  # 1) staging：/tmp/truth-stage/<job>/runs/<name> → arm=/tmp/<job>
        cands.append((os.path.join("/tmp", m.group(1)), "staging"))
    if os.path.basename(parent) == "runs":  # 2) 直指 <arm>/runs/<name>
        cands.append((os.path.dirname(parent), "direct"))
    try:  # 3) realpath 解符号链接（rejudge-src-*/NAME、truth-smoke/runs/NAME 等）
        rp = os.path.realpath(rd)
        if os.path.basename(os.path.dirname(rp)) == "runs":
            cands.append((os.path.dirname(os.path.dirname(rp)), "realpath"))
    except OSError:
        pass
    seen, ordered = set(), []
    for c, meth in cands:  # 去重保序
        if c not in seen:
            seen.add(c)
            ordered.append((c, meth))
    if arm_set is not None:
        for c, meth in ordered:
            if c in arm_set:
                return c, meth
        if ordered:  # 有候选但均不在 scope：报最逼近的（realpath 优先）
            c, meth = ordered[-1]
            return c, meth + "-out-of-scope"
        return None, "无法从 run_dir 解析出 arm（%s）" % rd
    if ordered:
        return ordered[0]
    return None, "无法从 run_dir 解析出 arm（%s）" % rd


def load_orig(arm):
    """原行按 (task_id, profile) 分组；保留文件序。带 run_dir 的单列出来供 attempt 精确配。"""
    path = os.path.join(arm, "results.jsonl")
    groups = collections.OrderedDict()
    if not os.path.isfile(path):
        return groups, 0
    n = 0
    with open(path, encoding="utf-8") as f:
        for ln, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            if not isinstance(r, dict):
                continue
            rew, raw_bad = norm_reward(r.get("reward"))
            rec = {
                "reward": rew, "status": r.get("status"), "line": ln,
                "run_dir": r.get("run_dir"), "reward_raw_bad": raw_bad,
                "attempt": None,
            }
            if isinstance(r.get("run_dir"), str) and r["run_dir"]:
                m = ATTEMPT_RE.search(os.path.basename(r["run_dir"].rstrip("/")))
                if m:
                    rec["attempt"] = int(m.group(1))
            key = (r.get("task_id"), r.get("profile"))
            groups.setdefault(key, []).append(rec)
            n += 1
    return groups, n


def attempts_on_disk(arm, task_id, profile, extra=None):
    """盘上该 (arm,task,profile) 的 attempt 集合（glob runs/ 目录名）。"""
    found = set()
    pattern = os.path.join(arm, "runs", "swev-%s-%s-a*" % (task_id, profile))
    for p in glob.glob(pattern):
        m = ATTEMPT_RE.search(os.path.basename(p))
        if m:
            found.add(int(m.group(1)))
    if extra is not None:
        found.add(extra)
    return found


def diff_state(arm, name):
    """(has_diff_file, bytes, note)。has_diff 与判分器同语义：文件存在即 True。"""
    p = os.path.join(arm, "runs", name, "agent.diff")
    if not os.path.isfile(p):
        return False, None, "无 agent.diff 文件"
    try:
        size = os.path.getsize(p)
    except OSError:
        return True, None, "agent.diff 存在但读不到大小"
    return True, size, "" if size > 0 else "agent.diff 为 0 字节（空提交）"


# ---------------------------------------------------------------- 配对

def build_pairs(clean_rows, arm_orig, arm_scope):
    """清洁行 × 原行配对（clean_rows 已限定在 arm scope 内）。返回 (pairs, conflicts, dup_info)。"""
    for r in clean_rows:
        arm, method = resolve_arm_path(r.get("run_dir", ""), arm_scope)
        if arm is None:
            continue
        r["_arm"] = arm
        r["_arm_method"] = method

    pairs, conflicts = [], []
    for r in clean_rows:
        rew, _ = norm_reward(r.get("reward"))
        name = os.path.basename(str(r.get("run_dir", "")).rstrip("/"))
        arm = r["_arm"]
        task_id, profile = r.get("task_id"), r.get("profile")
        m = ATTEMPT_RE.search(name)
        attempt = int(m.group(1)) if m else None
        disk_name = run_name_on_disk(r.get("run_dir", ""), arm)
        orig_groups, _ = arm_orig.get(arm, (collections.OrderedDict(), 0))
        group = orig_groups.get((task_id, profile), [])

        exact = [o for o in group if o["run_dir"] and o["attempt"] == attempt]
        no_rd = [o for o in group if not o["run_dir"] or o["attempt"] is None]
        disk = attempts_on_disk(arm, task_id, profile, extra=attempt)

        if attempt is not None and len(exact) == 1:
            orig, amb, how, orow = exact[0]["reward"], False, "run_dir-exact", exact[0]
        elif attempt is not None and len(exact) > 1:
            orig, amb, how, orow = exact[-1]["reward"], True, "run_dir-exact-multi", exact[-1]
        elif len(no_rd) == 1 and len(disk) <= 1:
            orig, amb, how, orow = no_rd[0]["reward"], False, "single-row", no_rd[0]
        elif len(no_rd) == 0:
            orig, amb, how, orow = None, False, "no-orig-row", None
        else:
            nonnull = [o for o in no_rd if o["reward"] is not None]
            if nonnull:
                orig, orow = nonnull[-1]["reward"], nonnull[-1]
            else:
                orig, orow = None, (no_rd[-1] if no_rd else None)
            amb, how = True, "last-non-null"

        has_diff, dbytes, dnote = diff_state(arm, disk_name)
        pairs.append({
            "arm": arm, "task_id": task_id, "profile": profile, "attempt": attempt,
            "tier": tier_of(arm), "gen": gen_of(arm),
            "orig_reward": orig, "clean_reward": rew,
            "orig_status": orow["status"] if orow else None,
            "orig_line": orow["line"] if orow else None,
            "clean_status": r.get("status"),
            "orig_row_count": len(group), "attempts_on_disk": sorted(disk),
            "pair_method": how, "ambiguous": amb,
            "has_diff": has_diff, "diff_bytes": dbytes, "diff_note": dnote,
            "run_dir": r.get("run_dir"), "run_name": name,
            "run_name_disk": disk_name,
            "clean_source": r["_source"], "clean_line": r["_line"],
            "arm_method": r["_arm_method"],
        })

    # 同键（跨来源）重复：reward 必须一致
    keymap = collections.OrderedDict()
    for p in pairs:
        keymap.setdefault((p["arm"], p["task_id"], p["profile"], p["attempt"]), []).append(p)
    deduped, dup_info = [], []
    for key, ps in keymap.items():
        vals = {p["clean_reward"] for p in ps}
        if len(vals) > 1:
            conflicts.append({"key": list(key),
                              "values": [{"source": p["clean_source"], "line": p["clean_line"],
                                          "reward": rlabel(p["clean_reward"])} for p in ps]})
            continue
        keep = sorted(ps, key=lambda p: (p["clean_source"], p["clean_line"]))[0]
        if len(ps) > 1:
            dup_info.append({"key": list(key), "sources": sorted({p["clean_source"] for p in ps}),
                             "reward": rlabel(keep["clean_reward"])})
        deduped.append(keep)
    deduped.sort(key=lambda p: (p["arm"], str(p["task_id"]), str(p["profile"]),
                                p["attempt"] if p["attempt"] is not None else -1))
    return deduped, conflicts, dup_info


# ---------------------------------------------------------------- 统计

def cell_key(orig, clean):
    return rlabel(orig) + rlabel(clean)


def group_stats(pairs):
    st = {
        "n_pair": len(pairs),
        "n_diff": sum(1 for p in pairs if p["has_diff"]),
        "n_empty_diff": sum(1 for p in pairs if p["has_diff"] and p["diff_bytes"] == 0),
        "n_no_diff_file": sum(1 for p in pairs if not p["has_diff"]),
        "orig_true": sum(1 for p in pairs if p["has_diff"] and p["orig_reward"] is True),
        "clean_true": sum(1 for p in pairs if p["has_diff"] and p["clean_reward"] is True),
        "orig_none": sum(1 for p in pairs if p["has_diff"] and p["orig_reward"] is None),
        "clean_none": sum(1 for p in pairs if p["has_diff"] and p["clean_reward"] is None),
        "n_judged": sum(1 for p in pairs if p["has_diff"]
                        and p["orig_reward"] is not None and p["clean_reward"] is not None),
        "j_orig_true": sum(1 for p in pairs if p["has_diff"] and p["orig_reward"] is not None
                           and p["clean_reward"] is not None and p["orig_reward"] is True),
        "j_clean_true": sum(1 for p in pairs if p["has_diff"] and p["orig_reward"] is not None
                            and p["clean_reward"] is not None and p["clean_reward"] is True),
        "ambiguous": sum(1 for p in pairs if p["ambiguous"]),
        "matrix": {c: 0 for c in CELLS},
        "flips": collections.defaultdict(list),
    }
    for p in pairs:
        if not p["has_diff"]:
            continue
        st["matrix"][cell_key(p["orig_reward"], p["clean_reward"])] += 1
        if p["orig_reward"] != p["clean_reward"]:
            st["flips"][cell_key(p["orig_reward"], p["clean_reward"])].append(
                "%s%s(a%s)" % (p["task_id"], "!" if p["ambiguous"] else "",
                               p["attempt"] if p["attempt"] is not None else "?"))
    st["flips"] = dict(st["flips"])
    return st


def fmt_group_block(title, pairs, indent="  "):
    st = group_stats(pairs)
    m = st["matrix"]
    lines = ["%s%s" % (indent, title),
             "%s  matrix(orig×clean)   T    F    N   | ambiguous=%d empty_diff=%d no_diff_file=%d"
             % (indent, st["ambiguous"], st["n_empty_diff"], st["n_no_diff_file"]),
             "%s                 T  %4d  %4d  %4d" % (indent, m["TT"], m["TF"], m["TN"]),
             "%s                 F  %4d  %4d  %4d" % (indent, m["FT"], m["FF"], m["FN"]),
             "%s                 N  %4d  %4d  %4d" % (indent, m["NT"], m["NF"], m["NN"]),
             "%s  pass(分母=有diff已配对 n=%d, null计非过): before %d/%d=%s  after %d/%d=%s  Δ=%s"
             % (indent, st["n_diff"], st["orig_true"], st["n_diff"], pct(st["orig_true"], st["n_diff"]),
                st["clean_true"], st["n_diff"], pct(st["clean_true"], st["n_diff"]),
                delta_pp(st["orig_true"], st["n_diff"], st["clean_true"], st["n_diff"])),
             "%s  pass(共同已判集 n=%d): before %d/%d=%s  after %d/%d=%s  Δ=%s"
             % (indent, st["n_judged"], st["j_orig_true"], st["n_judged"],
                pct(st["j_orig_true"], st["n_judged"]), st["j_clean_true"], st["n_judged"],
                pct(st["j_clean_true"], st["n_judged"]),
                delta_pp(st["j_orig_true"], st["n_judged"], st["j_clean_true"], st["n_judged"]))]
    for c in CELLS:
        if st["flips"].get(c):
            lines.append("%s  flip %s→%s (%d): %s" % (indent, c[0], c[1],
                                                      len(st["flips"][c]), ", ".join(st["flips"][c])))
    return lines, st


# ---------------------------------------------------------------- A/B

def ab_side_value(pairs, arm, task_id, profile):
    """该 (arm,task,profile) 的任务级清洁值（红队修订版，带缺口元数据）。
    返回 (value, ambiguous, reason, n_clean_rows, null_status)：
    reason=None 表示可用；否则为缺口短句（"无清洁行" / "清洁值为 null（status）"，
    与旧版 skip 文案保持一致，供跳过清单逐字节复现）。"""
    ps = [p for p in pairs if p["arm"] == arm and p["task_id"] == task_id
          and p["profile"] == profile]
    if not ps:
        return None, False, "无清洁行", 0, None
    ps = sorted(ps, key=lambda p: (p["attempt"] if p["attempt"] is not None else -1,
                                   p["clean_source"], p["clean_line"]))
    last = ps[-1]
    amb = len({p["attempt"] for p in ps}) > 1
    if last["clean_reward"] is None:
        return None, amb, "清洁值为 null（%s）" % (last["clean_status"] or "judge_failed"), \
            len(ps), last["clean_status"]
    return last["clean_reward"], amb, None, len(ps), None


def ab_disk_diff_names(arm, task_id, profile):
    """盘上该 (arm,task,profile) 的 run 目录名。精确前缀匹配（b==prefix 或
    b startswith prefix+"-a"），避免 astropy-1323 / astropy-13236 之类前缀碰撞。"""
    prefix = "swev-%s-%s" % (task_id, profile)
    out = []
    for p in sorted(glob.glob(os.path.join(arm, "runs", prefix + "*"))):
        b = os.path.basename(p)
        if b == prefix or b.startswith(prefix + "-a"):
            out.append(b)
    return out


def ab_side_gap(arm_orig, arm, task_id, profile, side, why, n_clean_rows):
    """A/B 单侧缺口分类（红队修订：缺口非随机，须逐题列因）。
    返回 {"label":..., "detail":...}；label ∈
      {fix1,fix2}_run_failed_no_diff  结构性：运行失败且盘上无 agent.diff
      {fix1,fix2}_clean_pending       在途：有 diff/有原行但清洁行未落
      {fix1,fix2}_clean_null          清洁行存在但 reward=null
    判定只读盘面与原行，不猜。"""
    entry = arm_orig.get(arm)
    groups = entry[0] if entry else load_orig(arm)[0]
    group = groups.get((task_id, profile), [])
    disk = ab_disk_diff_names(arm, task_id, profile)
    n_diff = sum(1 for n in disk if diff_state(arm, n)[0])
    sts = sorted({o["status"] or "?" for o in group})
    all_failed = bool(group) and all(
        o["reward"] is None and o["status"] in AB_FAILED_STATUSES for o in group)
    if n_diff == 0 and (all_failed or not group):
        return {"label": "%s_run_failed_no_diff" % side,
                "detail": "原行 %d 条(%s)、盘上 %d 个 run 全无 agent.diff"
                          % (len(group), "/".join(sts) or "-", len(disk))}
    if why and why.startswith("清洁值为 null"):
        return {"label": "%s_clean_null" % side, "detail": why}
    if group:
        last = group[-1]
        return {"label": "%s_clean_pending" % side,
                "detail": "原行 %d 条(末行 reward=%s status=%s)、盘上有 diff 的 run %d 个、清洁行未落"
                          % (len(group), rlabel(last["reward"]), last["status"] or "?", n_diff)}
    return {"label": "%s_clean_pending" % side,
            "detail": "无原行、盘上有 diff 的 run %d 个、清洁行未落" % n_diff}


def ab_view_stats(rows):
    """A/B 单口径统计（行 = {fix1_clean, fix2_clean}；缺失侧为 None，计非过）。"""
    n = len(rows)
    f1t = sum(1 for r in rows if r["fix1_clean"] is True)
    f2t = sum(1 for r in rows if r["fix2_clean"] is True)
    return {
        "n": n, "fix1_true": f1t, "fix2_true": f2t,
        "fix1_pct": pct(f1t, n).strip(), "fix2_pct": pct(f2t, n).strip(),
        "delta": delta_pp(f1t, n, f2t, n).strip(),
        "flip_up": sum(1 for r in rows if r["fix1_clean"] is False and r["fix2_clean"] is True),
        "flip_down": sum(1 for r in rows if r["fix1_clean"] is True and r["fix2_clean"] is False),
    }


def legacy_fix2_value(arm, task_id, profile):
    """旧口径 fix2 值：原 results.jsonl 中该题最后一行（null 计非过）。"""
    groups, _ = load_orig(arm)
    rows = groups.get((task_id, profile), [])
    return rows[-1]["reward"] if rows else None


def run_ab(pairs, pairings, arm_orig):
    out = {"sections": []}
    lines = []
    for pj in pairings:
        if not os.path.isfile(pj):
            lines.append("  %s：配对单缺失，跳过" % pj)
            continue
        data = json.load(open(pj, encoding="utf-8"))
        meta = data.get("meta", {})
        prof = meta.get("profile")
        fix1_arm = os.path.dirname(meta.get("fix1_source") or "") or None
        fix2_arm = os.path.dirname(meta.get("fix2_out") or "") or os.path.dirname(pj)
        pairs_json = data.get("pairs", [])
        sec = {"pairing": pj, "profile": prof, "fix1_arm": fix1_arm, "fix2_arm": fix2_arm,
               "legacy": None, "corrected": None, "skipped": [], "views": None}

        # ---- 旧口径参考（未修正）：pairing.json fix1_result + fix2 原 results 末行，null 计非过
        lg_n = lg_f1 = lg_f2 = 0
        lg_flips = collections.Counter()
        for pr in pairs_json:
            t = pr.get("task_id") or pr.get("task")
            v1 = pr.get("fix1_result")
            v1 = v1.get("reward") if isinstance(v1, dict) else v1
            v1, _ = norm_reward(v1)
            v2 = legacy_fix2_value(fix2_arm, t, prof)
            lg_n += 1
            lg_f1 += v1 is True
            lg_f2 += v2 is True
            lg_flips[(v1, v2)] += 1
        sec["legacy"] = {
            "n": lg_n, "fix1_true": lg_f1, "fix2_true": lg_f2,
            "fix1_pct": pct(lg_f1, lg_n).strip(), "fix2_pct": pct(lg_f2, lg_n).strip(),
            "delta": delta_pp(lg_f1, lg_n, lg_f2, lg_n).strip(),
            "flip_up": lg_flips[(False, True)], "flip_down": lg_flips[(True, False)],
            "flip_to_null": lg_flips[(True, None)] + lg_flips[(False, None)],
            "null_side": lg_flips[(True, None)] + lg_flips[(False, None)] +
                         lg_flips[(None, True)] + lg_flips[(None, False)],
        }

        # ---- 修正口径：双侧清洁值（现行为=口径①）；缺口题逐题分类（红队修订）
        rows, skipped, gaps = [], [], []
        for pr in pairs_json:
            t = pr.get("task_id") or pr.get("task")
            v1o = pr.get("fix1_result")
            v1o = v1o.get("reward") if isinstance(v1o, dict) else v1o
            v1o, _ = norm_reward(v1o)
            c1, a1, why1, n1, _ = ab_side_value(pairs, fix1_arm, t, prof)
            c2, a2, why2, n2, _ = ab_side_value(pairs, fix2_arm, t, prof)
            if why1 or why2:
                skipped.append({"task_id": t, "reason": "；".join(x for x in (why1, why2) if x),
                                "legacy_fix1": rlabel(v1o)})
                g1 = ab_side_gap(arm_orig, fix1_arm, t, prof, "fix1", why1, n1) if why1 else None
                g2 = ab_side_gap(arm_orig, fix2_arm, t, prof, "fix2", why2, n2) if why2 else None
                gaps.append({"task_id": t, "fix1": c1, "fix2": c2,
                             "gap_fix1": g1, "gap_fix2": g2, "legacy_fix1": v1o})
                continue
            rows.append({"task_id": t, "fix1_clean": c1, "fix2_clean": c2,
                         "ambiguous": a1 or a2, "legacy_fix1": v1o})
        sec["corrected"] = dict(ab_view_stats(rows), skipped=skipped, rows=rows)
        sec["skipped"] = skipped

        # ---- 三口径（红队修订 2026-10-21）----
        # ②含结构性缺失：任一侧 run_failed 且盘上无 agent.diff 的结构性缺口按 null 计非过纳入
        # ②b全量纳入：全部配对题（在途缺口也按 null 计非过）
        structural = [r for r in rows]
        for g in gaps:
            labels = [x["label"] for x in (g["gap_fix1"], g["gap_fix2"]) if x]
            if any(l.endswith("run_failed_no_diff") for l in labels):
                structural.append({"task_id": g["task_id"], "fix1_clean": g["fix1"],
                                   "fix2_clean": g["fix2"], "ambiguous": False,
                                   "legacy_fix1": g["legacy_fix1"]})
        allv = ([dict(r) for r in rows]
                + [{"task_id": g["task_id"], "fix1_clean": g["fix1"], "fix2_clean": g["fix2"],
                    "ambiguous": False, "legacy_fix1": g["legacy_fix1"]} for g in gaps])
        v1 = ab_view_stats(rows)
        v2 = ab_view_stats(structural)
        v2b = ab_view_stats(allv)
        has_struct = any(l.endswith("run_failed_no_diff") for g in gaps
                         for l in [x["label"] for x in (g["gap_fix1"], g["gap_fix2"]) if x])
        sec["views"] = {"comparable": v1, "structural": v2, "all": v2b, "gaps": gaps}

        lines.append("  [%s] profile=%s fix1_arm=%s fix2_arm=%s"
                     % (os.path.basename(pj), prof, fix1_arm, fix2_arm))
        lg = sec["legacy"]
        lines.append("    旧口径参考(未修正, null计非过): n=%d fix1=%s fix2=%s Δ=%s 翻正=%d 翻负=%d(+%d 至null)"
                     % (lg["n"], lg["fix1_pct"], lg["fix2_pct"], lg["delta"],
                        lg["flip_up"], lg["flip_down"], lg["flip_to_null"]))
        co = sec["corrected"]
        lines.append("    修正口径(双侧清洁): n=%d fix1=%s fix2=%s Δ=%s 翻正=%d 翻负=%d"
                     % (co["n"], co["fix1_pct"], co["fix2_pct"], co["delta"],
                        co["flip_up"], co["flip_down"]))
        if skipped:
            lines.append("    跳过 %d 题:" % len(skipped))
            for s in skipped:
                lines.append("      - %s：%s" % (s["task_id"], s["reason"]))
        else:
            lines.append("    跳过 0 题")
        # ---- 三口径并排（红队修订）：①可比集 / ②含结构性缺失 / ②b全量 / ③在途标注
        lines.append("    ── 三口径并排（红队修订 2026-10-21；缺口原因逐题列于③）──")
        lines.append("    口径①可比集(双侧均有清洁行): n=%d fix1=%s fix2=%s Δ=%s 翻正=%d 翻负=%d"
                     % (v1["n"], v1["fix1_pct"], v1["fix2_pct"], v1["delta"],
                        v1["flip_up"], v1["flip_down"]))
        struct_note = "" if has_struct else "（=口径①，本期无结构性缺口题）"
        lines.append("    口径②含结构性缺失(任一侧 run_failed 无 agent.diff → 按 null 计非过纳入)%s: "
                     "n=%d fix1=%s fix2=%s Δ=%s 翻正=%d 翻负=%d"
                     % (struct_note, v2["n"], v2["fix1_pct"], v2["fix2_pct"], v2["delta"],
                        v2["flip_up"], v2["flip_down"]))
        lines.append("    口径②b 全量纳入(全部 %d 题, 在途缺口也按 null 计非过): n=%d fix1=%s fix2=%s Δ=%s 翻正=%d 翻负=%d"
                     % (len(pairs_json), v2b["n"], v2b["fix1_pct"], v2b["fix2_pct"],
                        v2b["delta"], v2b["flip_up"], v2b["flip_down"]))
        if gaps:
            lines.append("    口径③在途缺口 %d 题（数据在途，终值会漂移；原因枚举: "
                         "{fix1,fix2}_run_failed_no_diff=结构性无diff / {fix1,fix2}_clean_pending=清洁行在途 / "
                         "{fix1,fix2}_clean_null=清洁值null / 其他）:" % len(gaps))
            for g in gaps:
                parts = []
                for side, x in (("fix1", g["gap_fix1"]), ("fix2", g["gap_fix2"])):
                    if x:
                        parts.append("%s=%s（%s）" % (side, x["label"], x["detail"]))
                lines.append("      - %s: %s | fix1=%s fix2=%s"
                             % (g["task_id"], "；".join(parts),
                                rlabel(g["fix1"]), rlabel(g["fix2"])))
        else:
            lines.append("    口径③在途缺口 0 题")
        out["sections"].append(sec)
    return lines, out


# ---------------------------------------------------------------- pending

def run_pending(arms, pairs):
    done = collections.defaultdict(set)
    for p in pairs:
        done[p["arm"]].add(p.get("run_name_disk") or p["run_name"])
    rows, tot = [], collections.Counter()
    for arm in arms:
        runs = sorted(os.path.basename(x) for x in glob.glob(os.path.join(arm, "runs", "*")))
        c = collections.Counter()
        for name in runs:
            has, size, _ = diff_state(arm, name)
            if not has:
                c["no_diff_file"] += 1
            elif size == 0:
                c["empty_diff_done" if name in done[arm] else "empty_diff_pending"] += 1
            elif name in done[arm]:
                c["done"] += 1
            else:
                c["pending"] += 1
            jp = os.path.join(arm, "runs", name, "rejudge-clean", "judge.json")
            if os.path.isfile(jp) and name not in done[arm]:
                c["judge_json_only"] += 1
        c["runs"] = len(runs)
        tot.update(c)
        rows.append((arm, c))
    return rows, tot


# ---------------------------------------------------------------- 任务级去重 / T→F / 约定敏感性

def task_dedup(pairs, representative):
    """按 (arm,task_id,profile) 去重（消除 [2] attempt 级同任务多 attempt 双计）。
    representative='first' 取 attempt 最小行、'last' 取 attempt 最大行作为任务代表
    （None attempt 视为最前，与配对引擎排序一致）。返回代表 pair 列表（带任务元数据）。"""
    groups = collections.OrderedDict()
    for p in pairs:
        groups.setdefault((p["arm"], p["task_id"], p["profile"]), []).append(p)
    out = []
    for ps in groups.values():
        ps = sorted(ps, key=lambda p: (p["attempt"] if p["attempt"] is not None else -1,
                                       p["clean_source"], p["clean_line"]))
        rep = dict(ps[0] if representative == "first" else ps[-1])
        rep["task_n_pairs"] = len(ps)
        rep["task_attempts"] = [p["attempt"] for p in ps]
        out.append(rep)
    out.sort(key=lambda p: (p["arm"], str(p["task_id"]), str(p["profile"])))
    return out


def pt_groups(pairs):
    by_pt = collections.OrderedDict()
    for p in pairs:
        by_pt.setdefault((str(p["profile"]), p["tier"], p["gen"]), []).append(p)
    return by_pt


def pt_row(prof, tier, gen, st):
    """[2] attempt 级表行（列宽与历史输出一致，供冻结快照逐字节复现）。"""
    return "%-14s %-5s %-10s %6d %6d %8s %8s %8s %8s %8s %6d" % (
        prof, tier, gen, st["n_pair"], st["n_diff"],
        pct(st["orig_true"], st["n_diff"]), pct(st["clean_true"], st["n_diff"]),
        delta_pp(st["orig_true"], st["n_diff"], st["clean_true"], st["n_diff"]),
        pct(st["j_orig_true"], st["n_judged"]), pct(st["j_clean_true"], st["n_judged"]),
        st["ambiguous"])


def pt_row_tf(prof, tier, gen, st):
    """[2b] 任务级表行：比 [2] 多一列 T→F（让去重对 T→F 计数的影响可见）。"""
    return "%-14s %-5s %-10s %6d %6d %8s %8s %8s %8s %8s %6d %6d" % (
        prof, tier, gen, st["n_pair"], st["n_diff"],
        pct(st["orig_true"], st["n_diff"]), pct(st["clean_true"], st["n_diff"]),
        delta_pp(st["orig_true"], st["n_diff"], st["clean_true"], st["n_diff"]),
        pct(st["j_orig_true"], st["n_judged"]), pct(st["j_clean_true"], st["n_judged"]),
        st["ambiguous"], st["matrix"]["TF"])


def collect_tf(pairs):
    """全部 T→F（orig=True → clean=False 且有 diff），按 arm/task/profile/attempt 排序。"""
    out = [p for p in pairs if p["has_diff"] and p["orig_reward"] is True
           and p["clean_reward"] is False]
    out.sort(key=lambda p: (p["arm"], str(p["task_id"]), str(p["profile"]),
                            p["attempt"] if p["attempt"] is not None else -1))
    return out


def convention_scan(arm_orig, pairs):
    """orig 多行组约定敏感性：组内非 null 值不一致（如 [None,None,True,False]）时，
    并列 last-non-null 与 first-non-null 两种取法下的判值与 T→F 计数差异。
    只读 arm_orig 原行组与已配对清洁行，不猜。"""
    pairs_by_group = collections.OrderedDict()
    for p in pairs:
        pairs_by_group.setdefault((p["arm"], p["task_id"], p["profile"]), []).append(p)
    n_multi = n_bad = 0
    items = []
    for arm, (groups, _) in arm_orig.items():
        for (task_id, profile), group in groups.items():
            if len(group) < 2:
                continue
            n_multi += 1
            nonnull = [o["reward"] for o in group if o["reward"] is not None]
            if len(set(nonnull)) < 2:
                continue
            n_bad += 1
            side = sorted(pairs_by_group.get((arm, task_id, profile), []),
                          key=lambda p: (p["attempt"] if p["attempt"] is not None else -1,
                                         p["clean_source"], p["clean_line"]))
            items.append({
                "arm": arm, "task_id": task_id, "profile": profile,
                "orig_values": [rlabel(o["reward"]) for o in group],
                "last": nonnull[-1], "first": nonnull[0],
                "pairs": [{"attempt": p["attempt"], "clean": p["clean_reward"],
                           "has_diff": p["has_diff"],
                           "cell_last": cell_key(nonnull[-1], p["clean_reward"]) if p["has_diff"] else None,
                           "cell_first": cell_key(nonnull[0], p["clean_reward"]) if p["has_diff"] else None}
                          for p in side]})
    items.sort(key=lambda x: (x["arm"], str(x["task_id"]), str(x["profile"])))
    return {"n_arms": len(arm_orig), "n_multi_groups": n_multi,
            "n_inconsistent": n_bad, "items": items}


# ---------------------------------------------------------------- 主流程

def main():
    ap = argparse.ArgumentParser(description="最终真相 P3 确定性聚合（只读，无网络无 LLM）")
    ap.add_argument("--json", metavar="PATH", help="把全量结构化结果写到 PATH（不打印到 stdout 的细节也在此）")
    ap.add_argument("--pending", action="store_true", help="附'尚未有清洁行的 run'监控段")
    ap.add_argument("--clean-glob", action="append", default=[],
                    help="清洁行来源 glob（可重复；默认见模块 docstring）")
    ap.add_argument("--arm-glob", action="append", default=[],
                    help="arm 目录 glob（可重复；默认 /tmp/bench-fix1-d* 等）")
    ap.add_argument("--ab-pairing", action="append", default=[],
                    help="A/B 配对单路径（可重复；默认两个 fix2-ab pairing.json）")
    args = ap.parse_args()
    argv = [sys.executable if sys.executable else "python3", os.path.abspath(__file__)] + sys.argv[1:]
    cmd = sh(argv)

    clean_globs = args.clean_glob or DEFAULT_CLEAN_GLOBS
    arm_globs = args.arm_glob or DEFAULT_ARM_GLOBS
    pairings = args.ab_pairing or DEFAULT_AB_PAIRINGS

    arms = expand_dirs(arm_globs)
    clean_rows, src_stats, bad_lines = load_clean_rows(clean_globs)

    print(rule("="))
    print("truth-aggregate.py · 最终真相 P3 确定性聚合（纯确定性：无网络/无 LLM/只读输入）")
    print("重算命令: %s" % cmd)
    print("清洁行来源 %d 个文件共 %d 行：" % (len(src_stats), sum(s["rows"] for s in src_stats)))
    for s in src_stats:
        print("  - %s (%d 行)" % (s["source"], s["rows"]))
    if bad_lines:
        print("  跳过坏行 %d 条（%s）" % (len(bad_lines), "; ".join(
            "%s:%d" % (b["source"], b["line"]) for b in bad_lines)))
    print("arm 目录 %d 个：" % len(arms))
    for a in arms:
        print("  - %s" % a)
    print("口径: 有diff=agent.diff文件存在（判分器 b3e1f56 同语义；0字节另计）; "
          "分母=有diff的已配对立; reward=null/缺失按None，计非过、不猜、不消失")
    print("注记: %s（本run实测 T→F 条数见 [2c] 清单与 TOTAL 行后注记）" % TF_NOTE)
    print(rule("="))

    # 配对：先按 scope 分流（in-scope / out-of-scope / unresolved），只把 in-scope 行喂配对引擎
    arm_scope = set(arms)
    in_rows, out_rows, unresolved = [], [], []
    for r in clean_rows:
        arm, method = resolve_arm_path(r.get("run_dir", ""), arm_scope)
        if arm is None:
            unresolved.append({"run_dir": r.get("run_dir"), "task_id": r.get("task_id"),
                               "profile": r.get("profile"), "reason": method})
        elif arm not in arm_scope:
            out_rows.append({"run_dir": r.get("run_dir"), "task_id": r.get("task_id"),
                             "profile": r.get("profile"), "resolved_arm": arm,
                             "method": method, "source": r["_source"]})
        else:
            in_rows.append(r)
    arm_orig = {a: load_orig(a) for a in arms}
    pairs, conflicts, dup_info = build_pairs(in_rows, arm_orig, arm_scope)

    # ---------------- [1] per-arm 转移矩阵
    print()
    print(rule("="))
    print("[1] 每 arm 转移矩阵（orig×clean）与修正前后通过率")
    print("重算命令: %s" % cmd)
    print(rule("="))
    arm_blocks = {}
    for arm in arms:
        ps = [p for p in pairs if p["arm"] == arm]
        groups, n_orig = arm_orig.get(arm, (collections.OrderedDict(), 0))
        n_orig_judged = sum(1 for g in groups.values() for o in g if o["reward"] is not None)
        n_orig_none = n_orig - n_orig_judged
        runs = sorted(os.path.basename(x) for x in glob.glob(os.path.join(arm, "runs", "*")))
        n_diff_file = sum(1 for n in runs if diff_state(arm, n)[0])
        title = "arm %s  (profile=%s tier=%s)" % (
            arm, sorted({str(p["profile"]) for p in ps}) or "-", tier_of(arm))
        block, st = fmt_group_block(title, ps)
        print()
        for ln in block:
            print(ln)
        print("    coverage: orig_rows=%d (T/F=%d N=%d) | clean_rows_paired=%d | paired=%d | "
              "runs=%d (diff_file=%d)" % (n_orig, n_orig_judged, n_orig_none,
                                          len(ps), len(ps), len(runs), n_diff_file))
        arm_blocks[arm] = st

    if conflicts:
        print()
        print("!! 同键跨来源 reward 冲突 %d 组（不进矩阵，不猜）:" % len(conflicts))
        for c in conflicts:
            print("   %s -> %s" % (c["key"], c["values"]))
    if dup_info:
        print()
        print("同键重复判分 %d 组（reward 一致，保留排序首行）:" % len(dup_info))
        for d in dup_info:
            print("   %s reward=%s sources=%s" % (d["key"], d["reward"], d["sources"]))
    if out_rows:
        print()
        print("out-of-scope 清洁行 %d 行（解析出的 arm 不在 --arm-glob 范围，不进矩阵；"
              "要纳入请相应加宽 --arm-glob）:" % len(out_rows))
        for u in out_rows:
            print("   %s -> %s (%s) %s" % (u["run_dir"], u["resolved_arm"], u["method"], u["task_id"]))
    if unresolved:
        print()
        print("无法确定 arm 的清洁行 %d 行（不进矩阵）:" % len(unresolved))
        for u in unresolved:
            print("   %s (%s) %s" % (u["run_dir"], u["reason"], u["task_id"]))

    # ---------------- [2] profile × tier（× 代际）—— attempt 级（含同任务多 attempt 双计）
    print()
    print(rule("="))
    print("[2] profile × tier 修正后通过率（tier 从 arm 目录名 d1/d2/d3 提取；"
          "gen=代际，s1 与 fix1 同名 profile 分代并列不混口径）")
    print("重算命令: %s" % cmd)
    print(rule("="))
    by_pt = pt_groups(pairs)
    header = "%-14s %-5s %-10s %6s %6s %8s %8s %8s %8s %8s %6s" % (
        "profile", "tier", "gen", "n_pair", "n_diff", "before%", "after%", "Δ",
        "j_before%", "j_after%", "amb")
    print(header)
    print(rule("-", len(header)))
    pt_out = []
    for (prof, tier, gen) in sorted(by_pt):
        st = group_stats(by_pt[(prof, tier, gen)])
        print(pt_row(prof, tier, gen, st))
        pt_out.append({"profile": prof, "tier": tier, "gen": gen, "stats": st})
    # profile 小计 + 总计
    for prof in sorted({str(p["profile"]) for p in pairs}):
        ps = [p for p in pairs if str(p["profile"]) == prof]
        st = group_stats(ps)
        print(pt_row(prof, "ALL", "ALL", st))
        pt_out.append({"profile": prof, "tier": "ALL", "gen": "ALL", "stats": st})
    st = group_stats(pairs)
    print(pt_row("TOTAL", "-", "-", st))
    print("注记: %s（本run实测 T→F=%d，逐行见 [2c]）" % (TF_NOTE, st["matrix"]["TF"]))
    print("attempt 级（含同任务多 attempt 双计）说明: before/after 分母=n_diff（有 diff 的已配对立，"
          "null 计非过）；j_before/j_after 分母=n_judged（共同已判集，双侧均 T/F）。"
          "任务级去重口径见 [2b]。")

    # ---------------- [2b] 任务级去重口径表（红队修订：attempt 级双计的对冲口径）
    print()
    print(rule("="))
    print("[2b] 任务级去重口径表（按 (arm,task_id,profile) 去重，消除 [2] attempt 级"
          "同任务多 attempt 双计；首/末 attempt 两种代表取法并列）")
    print("重算命令: %s" % cmd)
    print(rule("="))
    task_out = {}
    for rep, label in (("first", "首 attempt（attempt 最小者代表该任务；None attempt 视为最前）"),
                       ("last", "末 attempt（attempt 最大者代表该任务）")):
        tp = task_dedup(pairs, rep)
        print()
        print("  代表取法=%s: %s" % (rep, label))
        header = "%-14s %-5s %-10s %6s %6s %8s %8s %8s %8s %8s %6s %6s" % (
            "profile", "tier", "gen", "n_task", "n_diff", "before%", "after%", "Δ",
            "j_before%", "j_after%", "amb", "T→F")
        print(header)
        print(rule("-", len(header)))
        groups_out = []
        tp_by_pt = pt_groups(tp)
        for (prof, tier, gen) in sorted(tp_by_pt):
            st = group_stats(tp_by_pt[(prof, tier, gen)])
            print(pt_row_tf(prof, tier, gen, st))
            groups_out.append({"profile": prof, "tier": tier, "gen": gen, "stats": st})
        for prof in sorted({str(p["profile"]) for p in tp}):
            ps = [p for p in tp if str(p["profile"]) == prof]
            st = group_stats(ps)
            print(pt_row_tf(prof, "ALL", "ALL", st))
            groups_out.append({"profile": prof, "tier": "ALL", "gen": "ALL", "stats": st})
        st = group_stats(tp)
        print(pt_row_tf("TOTAL", "-", "-", st))
        print("  说明: n_task=去重后任务键数（与 [2] attempt 级 n_pair 的差额=双计键数）；"
              "分母=n_diff（代表对有 diff 的任务，null 计非过）。")
        print("  注记: %s（本取法下 T→F=%d）" % (TF_NOTE, st["matrix"]["TF"]))
        task_out[rep] = {"groups": groups_out, "total": st, "n_task": len(tp)}
    print()
    print("attempt 级 TOTAL 与任务级 TOTAL 并列即双计效应。红队验证点（19:12 快照 /tmp/truth-agg2.json，"
          "已归档、当前数据不可重跑）: 278→258 任务键, TOTAL Δ +8.9pp(首代表)/+8.5pp(末代表), "
          "m31f +14.0pp, step-5 +9.4pp——方向: 去重后修正幅度更大, 对结论偏保守。")

    # ---------------- [2c] T→F 完整清单与 orig 约定敏感性
    print()
    print(rule("="))
    print("[2c] T→F 完整清单与 orig 约定敏感性（last-non-null vs first-non-null）")
    print("重算命令: %s" % cmd)
    print(rule("="))
    tf = collect_tf(pairs)
    print("T→F 共 %d 条（orig=True → clean=False，均有 agent.diff）:" % len(tf))
    for i, p in enumerate(tf, 1):
        print("  %d. arm=%s task=%s profile=%s attempt=%s"
              % (i, p["arm"], p["task_id"], p["profile"],
                 "a%s" % p["attempt"] if p["attempt"] is not None else "?"))
        print("     pair_method=%s ambiguous=%s orig_row_count=%d attempts_on_disk=%s"
              % (p["pair_method"], p["ambiguous"], p["orig_row_count"], p["attempts_on_disk"]))
        print("     orig=True(%s) clean=False(%s) run=%s agent.diff=%sB"
              % (p["orig_status"] or "?", p["clean_status"] or "?",
                 p["run_name_disk"], p["diff_bytes"]))
    if not tf:
        print("  （无）")
    conv = convention_scan(arm_orig, pairs)
    print()
    print("orig 多行组约定敏感性: 扫描 %d 个 arm 的 orig 多行组共 %d 个，其中组内非 null 值不一致 %d 个"
          % (conv["n_arms"], conv["n_multi_groups"], conv["n_inconsistent"]))
    for it in conv["items"]:
        print("  - arm=%s task=%s profile=%s" % (it["arm"], it["task_id"], it["profile"]))
        print("    orig 行值=[%s]（%d 行）: last-non-null=%s / first-non-null=%s"
              % (",".join(it["orig_values"]), len(it["orig_values"]),
                 rlabel(it["last"]), rlabel(it["first"])))
        if it["pairs"]:
            segs = []
            for pp in it["pairs"]:
                a = "a%s" % pp["attempt"] if pp["attempt"] is not None else "?"
                if pp["has_diff"]:
                    segs.append("%s(clean=%s): last→%s / first→%s"
                                % (a, rlabel(pp["clean"]), pp["cell_last"], pp["cell_first"]))
                else:
                    segs.append("%s(clean=%s, 无diff不计翻转)" % (a, rlabel(pp["clean"])))
            print("    清洁对 %d 个: %s" % (len(it["pairs"]), " ; ".join(segs)))
            tf_last = sum(1 for pp in it["pairs"] if pp["cell_last"] == "TF")
            tf_first = sum(1 for pp in it["pairs"] if pp["cell_first"] == "TF")
            print("    净效应: last-non-null 下 T→F=%d；first-non-null 下 T→F=%d（差异 %+d）"
                  % (tf_last, tf_first, tf_first - tf_last))
        else:
            print("    暂无清洁对（无当期影响；数据在途，终值会漂移）")
    print("  注: 当前配对引擎对多行 orig 组统一取 last-non-null（与判分污染复核口径一致）；"
          "上表为若改用 first-non-null 的判值与 T→F 差异。数据在途，终值会漂移。")

    # ---------------- [3] A/B 修正
    print()
    print(rule("="))
    print("[3] A/B 修正（fix1/fix2 双侧换清洁重判值后重算 Δ）")
    print("重算命令: %s" % cmd)
    print(rule("="))
    ab_lines, ab_out = run_ab(pairs, pairings, arm_orig)
    for ln in ab_lines:
        print(ln)

    # ---------------- [4] pending
    pend_out = None
    if args.pending:
        print()
        print(rule("="))
        print("[4] 未判 run 监控（--pending）")
        print("重算命令: %s" % cmd)
        print(rule("="))
        rows, tot = run_pending(arms, pairs)
        print("%-38s %-10s %6s %8s %8s %8s %8s %9s" % (
            "arm", "gen", "runs", "done", "pending", "empty_df", "no_diff", "jj_only"))
        print(rule("-", 100))
        for arm, c in rows:
            print("%-38s %-10s %6d %8d %8d %8d %8d %9d" % (
                os.path.basename(arm), gen_of(arm), c["runs"], c["done"], c["pending"],
                c["empty_diff_pending"], c["no_diff_file"], c["judge_json_only"]))
        print(rule("-", 100))
        print("%-38s %-10s %6d %8d %8d %8d %8d %9d" % (
            "TOTAL", "", tot["runs"], tot["done"], tot["pending"],
            tot["empty_diff_pending"], tot["no_diff_file"], tot["judge_json_only"]))
        print("done=已有清洁行; pending=agent.diff>0 且无清洁行; empty_df=agent.diff 存在但 0 字节且无清洁行")
        print("  （launcher staging 过滤为 size>0，empty_df 这些 run 不会被 launcher 判——判分器")
        print("   b3e1f56 的门是 is_file()，两者口径不同，特此并列报出）; no_diff=无 agent.diff 文件;")
        print("   jj_only=已有 rejudge-clean/judge.json 但清洁行未落任何 results.jsonl。")
        pend_out = {"arms": [{"arm": a, **{k: v for k, v in c.items()}} for a, c in rows],
                    "total": dict(tot)}

    # ---------------- JSON 落盘
    if args.json:
        doc = {
            "tool": "truth-aggregate.py",
            "recompute": cmd,
            "clean_sources": src_stats,
            "bad_lines": bad_lines,
            "arms": arms,
            "arm_orig_rows": {a: arm_orig[a][1] for a in arms},
            "pairs": pairs,
            "out_of_scope": out_rows,
            "unresolved": unresolved,
            "conflicts": conflicts,
            "duplicates": dup_info,
            "arm_stats": arm_blocks,
            "profile_tier": pt_out,
            "task_level": task_out,
            "tf_list": tf,
            "convention": conv,
            "total": group_stats(pairs),
            "ab": ab_out,
            "pending": pend_out,
        }
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1, sort_keys=False)
            f.write("\n")
        print()
        print("JSON 已写: %s" % args.json)

    print()
    print(rule("="))
    print("本脚本只读输入文件；reward=null/缺失一律按 None 处理（计非过、不猜、不消失）。")
    print("重算命令: %s" % cmd)
    print(rule("="))


if __name__ == "__main__":
    main()
