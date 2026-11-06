#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""redteam_scan.py — 红队腿 A：确定性红队扫描（零 token · factory-os · D-88）

为什么是这个件
--------------
CI L-16（Q3 §五.2，30-工件/CI流水线研究-20261106/Q3-自有红队review体系.md）：
af 判据面实证不可落（gh_workflow_check 三形态 fail=7/4 实跑），落 factory-os。
本件 = 出包闸（bot-scrub 18 模式）之上另立一道**确定性红队扫描面**：
  · 扫描内核 = 直接复用 tools/mirror-disclose.sh 内嵌 python 段的
    scan_text()/scan_g13() 纯函数（18 模式 + G-13 线性内核），取法照抄
    30-工件/外派-bot-试点/tool/bot-scrub.py:91-182 的 load_scan_text()：
    AST 切出 <<'PYEOF'…PYEOF 段 → 只执行两 def 及其依赖闭包，隔离命名空间，
    不跑它的 git/argparse/main 逻辑。单点真源，改一处两处同步。
  · 红队 playbook 规则集：每条三元组 (pattern, severity, rationale_ref)，
    rationale_ref 必填台账 RT-E 编号（账本/逃逸问题台账.md 在役副本 235 条/
    23 横切模式，从既有条目抽机检形态，不新写规则）；内嵌规则集形态经
    factory-os#23 补漏批裁定（独立 playbook 件不在本卡 allowed_paths）。
  · 输出 schema 照 af.bot.scrub.v1（bot-scrub.py 2026-11-05 止血批口径）；
    fail-closed：命中、未覆盖面（uncovered）非空、自证电池不过 ⇒ 一律
    verdict=block 且 rc=1。C-8 铁律：本件全部产出均为确定性机检，
    LLM 自报不作证据（本件自身即 RT-P-07 的执法面）。

自证（照 G1 批纪律，缺此不可收卷；Q3 §五.2 原文）
--------------------------------------------------
造「删跳过规则 / 把 uncovered 判绿 / 去凭据形态 / 收紧 playbook」四个被削弱
的变体 ⇒ 每个都必须红（rc=1），逐条给读数；不许为让变体绿而放宽。
本件内置自证电池（selftest，每次运行首步执行）：
  S1  内核钉值：COMPILED==17 + G-13 探针必中（18 模式在役，少一即红）
  S2  凭据六形态探针必中（sk- 前缀 / ghp_ / github_pat_ / AKIA /
      PEM 私钥块 / eyJ 三段式，探测串一律分行碎片拼接构造）
  S2b G-13 赋值对探针必中
  S3  洁净对照串零命中（负控）
  S4  未覆盖登记在位：二进制/非 UTF-8 夹具必须进 uncovered（删跳过规则
      变体在此必红——静默跳过 = 假绿，fail-closed 禁之）
  S5  verdict fail-closed：uncovered 非空 + 零命中 ⇒ 必须 block
      （把 uncovered 判绿变体在此必红；本检查调用与主流程同一个
      verdict_of()，不走旁路副本）
  S6  playbook 完整性：规则数钉值、三元组字段齐全、severity 合法、
      rationale_ref 逐条 RT-E 编号（收紧 playbook 变体在此必红）
  S7  每规则必红探针：逐条被其自身规则命中（规则被删/被弱化即红）
  S8  自净控制：本件全文过全管线（18 模式 + 全部规则）必须零命中——
      探测串/规则源码面零自命中，判据件 mirror-scan-allowlist.json
      零改动、零新增豁免条目（判据面零接触）

退出码：0 = 自证过且零命中且覆盖完整（可放行）；1 = 命中或覆盖不全或
自证不过（block）；2 = 结构失败（同样拒）。

用法：
  python3 -I tools/redteam_scan.py <tree> --out <report.json> [--json]
"""
import argparse
import ast
import hashlib
import json
import os
import re
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
MIRROR = os.path.join(HERE, "mirror-disclose.sh")

PER_FILE_BUDGET_S = 30.0
MAX_FILE_BYTES = 64 * 1024 * 1024

# 内核钉值：mirror-disclose.sh PATTERNS 表 13 通用 + 5 项目自有 = 18 条，
# 其中 G-13 走预筛机制不进 COMPILED ⇒ COMPILED 钉 17。少一即自证红。
KERNEL_COMPILED_PIN = 17

# ============================================================================
# 红队 playbook 规则集（三元组 + 作用域后缀；从台账既有条目抽机检形态）
# 严重度 = 所引 RT-E 条目的台账严重度（不另造标度）。
# ============================================================================
# PLAYBOOK-BEGIN（变体自证锚：收紧 playbook 变体在此列表内截断到首条）
PLAYBOOK = [
    ("RT-P-01", "赋值捕获管道吞 rc（PIPESTATUS 静默废除形态）",
     r"[A-Za-z_][A-Za-z0-9_]{0,63}=(?:[\"'])?\$\([^\n()|]{0,200}\|[^\n()]{0,200}\)",
     "high", "RT-E120", (".sh", ".py")),
    ("RT-P-02", "计数式匹配充当门证据（正则计数与消费名册脱钩形态）",
     r"\bgrep\s+-c\b|\bgrep\s[^;\n|&]{1,120}\s-c\b",
     "high", "RT-E121", (".sh", ".py", ".md")),
    ("RT-P-03", "存在性核验冒充内容核验（锚行非空形态）",
     r"\bgrep\s+-q\b|\bgrep\s[^;\n|&]{1,120}\s-q\b",
     "medium", "RT-E60", (".sh", ".py")),
    ("RT-P-04", "活性探针冒充产出断言（活性信号不等于产出信号形态）",
     r"\bpgrep\b|\bsystemctl\s+is-active\b",
     "medium", "RT-E88", (".sh", ".py")),
    ("RT-P-05", "mtime 冒充 birth 见证（测量面误读形态）",
     r"\bstat\s+(?:-c\s+|--format=)[\"']?%y",
     "low", "RT-E129", (".sh", ".py", ".md")),
    ("RT-P-06", "推送类子进程不校验退出码（失败判据永不触发形态）",
     r"\bscp\s",
     "medium", "RT-E36", (".py",)),
    ("RT-P-07", "自报字段被当证据消费（修复自报全修而零痕迹形态；C-8 执法面）",
     r"[\"'](?:self_report|llm_verdict|model_verdict|agent_verdict)[\"']\s*[:=]",
     "high", "RT-E54", (".py", ".md", ".json")),
    ("RT-P-08", "路径拼接进开启调用（穿越/失配形态）",
     r"\bopen\([^()\n]{0,120}\+[^()\n]{0,120}\)",
     "low", "RT-E47", (".py",)),
    ("RT-P-09", "rc=2 记 SKIP 不计红（退出语义自相矛盾形态）",
     r"(?:rc\s*==\s*2|rc\s*-eq\s*2)[^\n]{0,80}\bSKIP\b"
     r"|\bSKIP\b[^\n]{0,80}(?:rc\s*==\s*2|rc\s*-eq\s*2)",
     "medium", "RT-E5", (".sh", ".py")),
    ("RT-P-10", "对账只数文本登记行（数文本不数执行形态）",
     r"\bgrep\b[^\n]{0,120}\brun\.sh\b",
     "high", "RT-E1", (".sh", ".py", ".md")),
]  # PLAYBOOK-END

RULE_COUNT_PIN = 10          # 钉值：本批自台账抽取 10 条；调小即自证红
RULE_SEVERITIES = ("high", "medium", "low")
RULE_REF_RX = re.compile(r"RT-E\d+\Z")

# ============================================================================
# 自证探针（分行碎片拼接：源码面零凭据形态、零规则形态字面量 ⇒ S8 自净。
# 每个碎片行单独存在时不构成任何被检形态，运行时拼接后才构成完整形态。）
# ============================================================================
_CRED_SK_A = "sk-"
_CRED_SK_B = "ab" * 12
_CRED_GHP_A = "ghp"
_CRED_GHP_B = "_" + "f" * 30
_CRED_GPAT_A = "github"
_CRED_GPAT_B = "_pat_" + "5" * 24
_CRED_AKIA_A = "AKIA"
_CRED_AKIA_B = "Q7" * 8
_CRED_PEM_A = "-----BEGIN "
_CRED_PEM_B = "RSA " + "PRIVATE " + "KEY-----\n" + "b" * 64
_CRED_PEM_C = "\n-----END " + "RSA " + "PRIVATE " + "KEY-----"
_CRED_JWT_A = "ey" + "J"
_CRED_JWT_B = "A" * 12 + "." + "B" * 8 + "." + "C" * 16
_G13_A = "password"
_G13_B = " = " + "h" * 12

# 探针名册（六形态 + G-13）：条目=（形态名, 拼接式, 期望命中 pid）。
# 钉值 6：去凭据形态变体删任一条目即在此必红（名册完整性自证）。
CRED_PROBES = [
    ("sk- 前缀", lambda: _CRED_SK_A + _CRED_SK_B, "G-02"),
    ("ghp_ 前缀", lambda: _CRED_GHP_A + _CRED_GHP_B, "G-03"),
    ("github_pat_ 前缀", lambda: _CRED_GPAT_A + _CRED_GPAT_B, "G-03"),
    ("AKIA 访问键", lambda: _CRED_AKIA_A + _CRED_AKIA_B, "G-04"),
    ("PEM 私钥块", lambda: _CRED_PEM_A + _CRED_PEM_B + _CRED_PEM_C, "G-12"),
    ("eyJ 三段式", lambda: _CRED_JWT_A + _CRED_JWT_B, "G-01"),
]
CRED_PROBES_PIN = 6
_G13_PROBE = ("赋值对", lambda: _G13_A + _G13_B, "G-13")

# 每规则必红探针（同样分行碎片拼接；运行时拼接后逐条必须被自身规则命中）
_RP01_A = "note=$("
_RP01_B = "probe 2>&1"
_RP01_C = " | tail -1)"
_RP02_A = "grep"
_RP02_B = " -c protocol x"
_RP03_A = "grep"
_RP03_B = " -q lockfile"
_RP04_A = "pgre"
_RP04_B = "p -f workerd"
_RP05_A = "stat"
_RP05_B = " -c '%y' birth.txt"
_RP06_A = "sc"
_RP06_B = "p -3 src backup/"
_RP07_A = '"self_rep'
_RP07_B = 'ort": 1'
_RP08_A = "open(dir "
_RP08_B = "+ name)"
_RP09_A = "rc == 2 "
_RP09_B = "then SKIP close"
_RP10_A = "grep"
_RP10_B = " step13 run.sh"

RULE_PROBES = {
    "RT-P-01": lambda: _RP01_A + _RP01_B + _RP01_C,
    "RT-P-02": lambda: _RP02_A + _RP02_B,
    "RT-P-03": lambda: _RP03_A + _RP03_B,
    "RT-P-04": lambda: _RP04_A + _RP04_B,
    "RT-P-05": lambda: _RP05_A + _RP05_B,
    "RT-P-06": lambda: _RP06_A + _RP06_B,
    "RT-P-07": lambda: _RP07_A + _RP07_B,
    "RT-P-08": lambda: _RP08_A + _RP08_B,
    "RT-P-09": lambda: _RP09_A + _RP09_B,
    "RT-P-10": lambda: _RP10_A + _RP10_B,
}

# 洁净负控串（S3：零命中；不含任何 18 模式或规则形态）
_CLEAN_CONTROL = (
    "hello world\nplain text line for negative control\n"
    "another ordinary line 42\nfinal line\n"
)


def load_scan_text(path):
    """从 mirror-disclose.sh 的内嵌 python 段里取出 scan_text（纯函数）。

    取法照抄 bot-scrub.py:91-182（AST 依赖闭包：只执行 scan_text/scan_g13
    两个 def 与它们依赖的常量，隔离命名空间，无副作用）。"""
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    try:
        start = next(i for i, l in enumerate(lines) if "<<'PYEOF'" in l)
        end = next(i for i, l in enumerate(lines) if i > start and l.strip() == "PYEOF")
    except StopIteration:
        raise SystemExit("FAIL mirror-disclose.sh 里找不到内嵌 python 段（PYEOF）")
    src = "".join(lines[start + 1:end])

    tree = ast.parse(src, filename=path + "#embedded")

    wanted_funcs = {"scan_text", "scan_g13"}
    defs, assigns = {}, {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            defs[node.name] = node
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    assigns.setdefault(t.id, node)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            assigns.setdefault(node.target.id, node)

    def global_names(node):
        out = set()
        for x in ast.walk(node):
            if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Load):
                out.add(x.id)
        return out

    BUILTINS = {"re", "bisect", "os", "sys", "json", "str", "len", "sorted",
                "set", "bytes", "int", "min", "max", "range", "sum", "open",
                "print", "enumerate", "isinstance", "dict", "list", "tuple",
                "any", "all", "zip", "map", "filter", "abs", "repr", "format",
                "True", "False", "None", "Exception", "ValueError", "TypeError"}

    selected, frontier = set(), set(wanted_funcs)
    while frontier:
        name = frontier.pop()
        if name in selected:
            continue
        selected.add(name)
        node = defs.get(name) or assigns.get(name)
        if node is None:
            continue
        for g in global_names(node):
            if g in selected or g in BUILTINS:
                continue
            if g in defs or g in assigns:
                frontier.add(g)

    order = {}
    for i, node in enumerate(tree.body):
        if isinstance(node, ast.FunctionDef):
            order.setdefault(node.name, i)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    order.setdefault(t.id, i)
                    break
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            order.setdefault(node.target.id, i)

    body = []
    for name in sorted(selected, key=lambda n: order.get(n, 10 ** 6)):
        node = defs.get(name) or assigns.get(name)
        if node is not None:
            body.append(node)

    ns = {"re": re, "bisect": __import__("bisect"), "os": os, "sys": sys}
    exec(compile(ast.Module(body=body, type_ignores=[]), path, "exec"), ns)
    if "scan_text" not in ns:
        raise SystemExit("FAIL mirror-disclose.sh 内嵌段里找不到 scan_text")
    return ns["scan_text"], len(ns.get("COMPILED", []))


def scan_playbook_text(txt, rules):
    """对一段文本跑全部规则（按规则作用域过滤由调用方完成）。
    返回 [(rid, 行号)]（去重）。"""
    out, seen = [], set()
    for rid, name, rx, sev, ref, exts in rules:
        for m in rx.finditer(txt):
            ln = txt.count("\n", 0, m.start()) + 1
            key = (rid, ln)
            if key not in seen:
                seen.add(key)
                out.append(key)
    return out


def scan_tree(root, scan_text, rules):
    """扫一棵树：18 模式内核（全文本文件）+ playbook 规则（按后缀作用域）。
    fail-closed 面照抄 bot-scrub.py scan()：超预算判红、二进制/非 UTF-8
    登记进 uncovered（不静默跳过、不装作扫过）。"""
    hits, scanned, uncovered = [], 0, []
    for rdir, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
        for fn in sorted(files):
            p = os.path.join(rdir, fn)
            rel = os.path.relpath(p, root)
            try:
                size = os.path.getsize(p)
                if size > MAX_FILE_BYTES:
                    uncovered.append({"file": rel, "reason": "oversize",
                                      "detail": "%d B > %d B" % (size, MAX_FILE_BYTES)})
                    continue
                raw = open(p, "rb").read()
            except Exception as e:
                hits.append({"file": rel, "pattern": "READ-FAIL", "ctx": str(e)[:120]})
                continue
            scanned += 1
            if b"\x00" in raw[:8192]:
                uncovered.append({"file": rel, "reason": "binary",
                                  "detail": "二进制件未扫（明文探针不适用）"})
                continue
            try:
                txt = raw.decode("utf-8")
            except Exception:
                uncovered.append({"file": rel, "reason": "non-utf8",
                                  "detail": "非 UTF-8 文本未扫"})
                continue
            t0 = time.time()
            try:
                recs = scan_text(txt)
                pb = scan_playbook_text(txt, [r for r in rules
                                              if rel.endswith(tuple(r[5]))])
            except Exception as e:
                hits.append({"file": rel, "pattern": "SCAN-ERROR", "ctx": str(e)[:120]})
                continue
            dt = time.time() - t0
            if dt > PER_FILE_BUDGET_S:
                hits.append({"file": rel, "pattern": "BUDGET-EXCEEDED",
                             "ctx": "单文件扫描超 %.0fs 预算（覆盖不完整 ⇒ 判红）"
                                    % PER_FILE_BUDGET_S})
                continue
            for pid, ln in recs:
                hits.append({"file": rel, "pattern": pid, "line": ln,
                             "source": "kernel"})
            rule_meta = {r[0]: r for r in rules}
            for rid, ln in pb:
                m = rule_meta.get(rid)
                hits.append({"file": rel, "pattern": rid, "line": ln,
                             "source": "playbook",
                             "severity": m[3], "rationale_ref": m[4]})
    return hits, scanned, uncovered


def verdict_of(hits, uncovered, selftest_fails):
    """唯一裁决函数（S5 与主流程共用本体，无旁路副本）。
    fail-closed：自证不过、命中、未覆盖面非空 ⇒ block。"""
    reasons = []
    if selftest_fails:
        reasons.append("selftest")
    if hits:
        reasons.append("hits")
    if uncovered:
        reasons.append("uncovered")
    return ("block", reasons) if reasons else ("clean", [])


def fingerprint_of(hits, uncovered):
    """发现面指纹（workflow 板评论去重用；确定性，无时钟成分）。"""
    feed = sorted((h.get("file", ""), h.get("pattern", ""), str(h.get("line", "")))
                  for h in hits)
    feed += sorted((u.get("file", ""), u.get("reason", "")) for u in uncovered)
    blob = json.dumps(feed, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def selftest(scan_text, npat, rules):
    """自证电池 S1-S8。返回 (fails:list[str], readings:list[str])。
    任何一项不过 ⇒ rc=1（fail-closed）；四变体逐一在对应检查位必红。
    rules = 已编译规则集（与主流程同一份本体，无旁路副本）。"""
    fails, readings = [], []

    def check(name, cond, detail=""):
        if cond:
            readings.append("SELFTEST-OK %s" % name)
        else:
            fails.append("%s: %s" % (name, detail or "check failed"))
            readings.append("SELFTEST-FAIL %s: %s" % (name, detail or "check failed"))

    # S1 内核钉值
    check("S1.kernel-compiled-pin", npat == KERNEL_COMPILED_PIN,
          "COMPILED=%d 钉值=%d（内核模式表被增删）" % (npat, KERNEL_COMPILED_PIN))

    # S2 凭据六形态探针必中（名册钉值 6；逐条给出 pid 回读）
    check("S2.cred-probe-roster", len(CRED_PROBES) == CRED_PROBES_PIN,
          "名册 %d 条钉值 %d（去凭据形态变体在此必红）"
          % (len(CRED_PROBES), CRED_PROBES_PIN))
    for form, mk, want in CRED_PROBES:
        probe = mk()
        pids = {pid for pid, _ in scan_text(probe)}
        readings.append("CRED-PROBE %s -> %s [%s]"
                        % ("ok" if want in pids else "MISS", want, form))
        check("S2.cred-probe:%s" % form, want in pids,
              "期望 %s 实得 %s" % (want, sorted(pids) or "无命中"))

    # S2b G-13 赋值对探针
    form, mk, want = _G13_PROBE
    pids = {pid for pid, _ in scan_text(mk())}
    readings.append("CRED-PROBE %s -> %s [%s]"
                    % ("ok" if want in pids else "MISS", want, form))
    check("S2b.g13-probe", want in pids, "期望 G-13 实得 %s" % sorted(pids) or "无命中")

    # S3 洁净负控
    hits0, _, unc0 = full_scan_text(_CLEAN_CONTROL, scan_text, rules)
    check("S3.clean-control", not hits0 and not unc0,
          "洁净对照串得命中 %s 未覆盖 %s" % (hits0, unc0))

    # S4 未覆盖登记在位（删跳过规则变体在此必红）
    td = tempfile.mkdtemp(prefix="redteam-selftest-")
    try:
        with open(os.path.join(td, "probe.bin"), "wb") as f:
            f.write(b"plain\x00binary-mixed-content")
        with open(os.path.join(td, "probe.txt"), "wb") as f:
            f.write(b"\xff\xfe not-utf8-bytes")
        h4, s4, u4 = scan_tree(td, scan_text, PLAYBOOK)
        reasons4 = {u.get("reason") for u in u4}
        check("S4.uncovered-registration", {"binary", "non-utf8"} <= reasons4,
              "夹具应登记 binary+non-utf8，实得 %s（静默跳过=假绿）" % sorted(reasons4))
        # S5 verdict fail-closed（同一 verdict_of 本体；uncovered 判绿变体在此必红）
        v5, r5 = verdict_of(h4, u4, [])
        check("S5.verdict-fail-closed", v5 == "block" and "uncovered" in r5,
              "uncovered 非空应 block(uncovered)，实得 %s/%s" % (v5, r5))
    finally:
        import shutil
        shutil.rmtree(td, ignore_errors=True)

    # S6 playbook 完整性（收紧 playbook 变体在此必红）
    check("S6.rule-count-pin", len(PLAYBOOK) == RULE_COUNT_PIN
          and len(rules) == RULE_COUNT_PIN,
          "规则 PLAYBOOK=%d compiled=%d 钉值 %d（收紧 playbook 变体在此必红）"
          % (len(PLAYBOOK), len(rules), RULE_COUNT_PIN))
    for rid, name, rx, sev, ref, exts in rules:
        ok = (isinstance(rx, re.Pattern) and sev in RULE_SEVERITIES
              and RULE_REF_RX.fullmatch(str(ref)) is not None
              and isinstance(exts, tuple) and len(exts) > 0
              and all(e.startswith(".") for e in exts))
        check("S6.rule-schema:%s" % rid, bool(ok),
              "severity=%s rationale_ref=%s rx=%s exts=%s"
              % (sev, ref, type(rx).__name__, exts))
        readings.append("RULE %s sev=%s ref=%s" % (rid, sev, ref))

    # S7 每规则必红探针
    for rid, name, rx, sev, ref, exts in rules:
        probe = RULE_PROBES.get(rid, lambda: "")()
        found = {r for r, _ in scan_playbook_text(probe, [r for r in rules
                                                          if r[0] == rid])}
        readings.append("PLAYBOOK-PROBE %s -> %s ref=%s"
                        % ("ok" if rid in found else "MISS", ref, ref))
        check("S7.rule-probe:%s" % rid, rid in found,
              "规则自身探针未被命中（规则被删/弱化）")

    # S8 自净控制：本件全文过全管线必须零命中（判据面零接触的机器证明）
    try:
        with open(os.path.abspath(__file__), "rb") as f:
            src = f.read().decode("utf-8")
        h8, _, u8 = full_scan_text(src, scan_text, rules)
        check("S8.self-clean", not h8 and not u8,
              "本件源码面自命中：内核 %s 规则 %s"
              % ([x["pattern"] for x in h8], u8))
    except Exception as e:
        check("S8.self-clean", False, "读自身失败 %s" % e)

    return fails, readings


def full_scan_text(txt, scan_text, rules):
    """单文本全管线便捷口（S3/S8 负控与自净用）。返回 (hits, 0, uncovered)。"""
    hits, uncovered = [], []
    for pid, ln in scan_text(txt):
        hits.append({"file": "<self>", "pattern": pid, "line": ln,
                     "source": "kernel"})
    for rid, ln in scan_playbook_text(txt, rules):
        meta = {r[0]: r for r in rules}.get(rid)
        hits.append({"file": "<self>", "pattern": rid, "line": ln,
                     "source": "playbook",
                     "severity": meta[3], "rationale_ref": meta[4]})
    return hits, 0, uncovered


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tree", nargs="?", default=".",
                    help="扫描目标树（默认当前目录）")
    ap.add_argument("--out", default=None, help="报告 JSON 落盘路径")
    ap.add_argument("--json", action="store_true", help="stdout 输出 JSON 报告")
    args = ap.parse_args()

    if not os.path.isdir(args.tree):
        print("FAIL 树不在位：%s" % args.tree, file=sys.stderr)
        return 2
    if not os.path.isfile(MIRROR):
        print("FAIL 内核缺席：%s" % MIRROR, file=sys.stderr)
        return 2
    try:
        scan_text, npat = load_scan_text(MIRROR)
    except SystemExit as e:
        print(str(e), file=sys.stderr)
        return 2

    rules = [(rid, name, re.compile(rx), sev, ref, exts)
             for rid, name, rx, sev, ref, exts in PLAYBOOK]

    st_fails, st_readings = selftest(scan_text, npat, rules)

    hits, scanned, uncovered = scan_tree(args.tree, scan_text, rules)
    verdict, reasons = verdict_of(hits, uncovered, st_fails)
    fp = fingerprint_of(hits, uncovered)

    rep = {
        "schema": "af.bot.scrub.v1",
        "tool": "tools/redteam_scan.py",
        "card": "factory-os#23 [wave-06][D-88] 红队腿 A（确定性扫描 · 零 token）",
        "tree": os.path.abspath(args.tree),
        "scanner": MIRROR,
        "scanner_mode": "scan_text()/scan_g13() 复用（18 模式 + G-13 线性内核）",
        "pattern_count": npat,
        "scanned_files": scanned,
        "playbook": {
            "rule_count": len(rules),
            "rule_count_pin": RULE_COUNT_PIN,
            "rules": [{"id": rid, "name": name, "severity": sev,
                       "rationale_ref": ref, "scope_exts": list(exts)}
                      for rid, name, rx, sev, ref, exts in rules],
            "rationale_ref_required": "RT-E\\d+",
            "source": "账本/逃逸问题台账.md 在役副本（235 条/23 横切模式）",
        },
        "hits": hits,
        "uncovered": uncovered,
        "selftest": {"status": "pass" if not st_fails else "fail",
                     "fails": st_fails,
                     "readings": st_readings},
        "fingerprint": fp,
        "verdict": verdict,
        "block_reasons": reasons,
    }
    txt = json.dumps(rep, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(txt)
    if args.json:
        sys.stdout.write(txt)
    else:
        refs = ",".join(r[4] for r in rules)
        print("RULESET rules=%d refs=%s" % (len(rules), refs))
        for ln in st_readings:
            print("  " + ln)
        cred_hits = [h for h in hits if h.get("source") == "kernel"]
        pb_hits = [h for h in hits if h.get("source") == "playbook"]
        print("REDTEAM-SCAN scanned=%d kernel_hits=%d playbook_hits=%d "
              "uncovered=%d selftest=%s verdict=%s fingerprint=%s"
              % (scanned, len(cred_hits), len(pb_hits), len(uncovered),
                 "pass" if not st_fails else "fail:" + ",".join(st_fails)[:120],
                 verdict, fp))
        for h in hits[:40]:
            extra = " sev=%s ref=%s" % (h["severity"], h["rationale_ref"]) \
                if h.get("source") == "playbook" else ""
            print("  HIT %s:%s [%s]%s" % (h.get("file"), h.get("line", "?"),
                                          h.get("pattern"), extra))
        if len(hits) > 40:
            print("  ...（另有 %d 条命中，全文见 --out 报告）" % (len(hits) - 40))
        for u in uncovered[:25]:
            print("  UNCOVERED %s (%s) %s" % (u["file"], u["reason"], u["detail"]))
        if verdict == "block":
            print("FAIL verdict=block（%s）⇒ rc=1（fail-closed）"
                  % ",".join(reasons))
    return 1 if reasons else 0


if __name__ == "__main__":
    sys.exit(main())
