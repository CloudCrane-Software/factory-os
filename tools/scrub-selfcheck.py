#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scrub-selfcheck.py — 工人侧出仓预检件（SR-026 / ESC-43 根治 · factory-os #270）

把 gates 出仓闸的扫描语义（十八模式族＋G-13 线性内核）做成 commit 前可跑的
预检 CLI。本件是消费面镜像：模式定义从 .github/workflows/gates.yml 内嵌段
与 tools/mirror-disclose.sh 只读提取（AST 切出 scan_text/scan_g13 闭包，
与 gates.yml bot-scrub 步同款），判据面本身零改动——工人提交前自查，
不读不抄 mirror-scan-allowlist.json（新码应净，豁免是判官面）。

用法：
  python3 -I tools/scrub-selfcheck.py --selftest
  python3 -I tools/scrub-selfcheck.py --check <文件或目录> [更多路径…]

出口：
  --selftest  0=夹具全过；1=有断言败
  --check     0=干净；1=命中（逐行 file:line [pattern] ＋建议修法）
              或未覆盖（二进制/非 UTF-8/超预算，fail-closed 同闸）
              2=不可证（缺件/内核抽不出/路径不在位）

建议修法（卡面三形，针对 ESC-43 工人码撞闸）：
  · 变量名加 _tag/_name 后缀断开（G-13 赋值对）
  · 长串拼接（前缀族/四段地址/PEM 头尾勿整段字面）
  · 夹具用 SENTINEL-XXX 形（禁真实前缀族假令牌字面）

纪律：零网络；selftest 只写临时目录用后即清；判据/判官/门禁件零触碰。
"""
import ast
import os
import re
import subprocess
import sys
import tempfile
import time

SCHEMA = "af.scrub-selfcheck.v1"
RC_OK, RC_HIT, RC_UNPROVABLE = 0, 1, 2

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(TOOLS_DIR)
MIRROR_REL = os.path.join("tools", "mirror-disclose.sh")
GATES_REL = os.path.join(".github", "workflows", "gates.yml")
MIRROR_PATH = os.path.join(TOOLS_DIR, "mirror-disclose.sh")
GATES_PATH = os.path.join(ROOT_DIR, ".github", "workflows", "gates.yml")

SKIP_DIRS = {".git", "__pycache__"}
MAX_FILE_BYTES = 64 * 1024 * 1024
PER_FILE_BUDGET_S = 30.0

# 修法词条：键是模式号，值不含「族词 + 6+ 非数值串」同现，避免本件自命中。
HINT_G13 = "修法：变量名加 _tag/_name 后缀断开"
HINT_JOIN = "修法：长串拼接，勿整段字面"
HINT_SENT = "修法：夹具用 SENTINEL-XXX 形，或前缀与体长串拼接"
HINT_ADDR = "修法：禁四段字面，改拼接构造"
HINT_PEM = "修法：PEM 头尾改拼接构造"
HINT_URL = "修法：URL 用户信息段改拼接，勿直写"
HINT_UNC = "修法：二进制/非 UTF-8 不进文本扫描，移出提交或改文本面"
HINT_BUDGET = "修法：单文件超预算，拆文件或降体积后再扫"

HINT_BY_PID = {
    "G-13": HINT_G13,
    "P-04": HINT_ADDR,
    "P-01": HINT_URL,
    "G-12": HINT_PEM,
}

# gates.yml bot-scrub 抽取闭包时注入的名字；与闸内联段同款。
_EXTRACT_BUILTINS = {
    "re", "bisect", "os", "sys", "json", "str", "len", "sorted",
    "set", "bytes", "int", "min", "max", "range", "sum", "open",
    "print", "enumerate", "isinstance", "dict", "list", "tuple",
    "any", "all", "zip", "map", "filter", "abs", "repr", "format",
    "True", "False", "None", "Exception", "ValueError", "TypeError",
}


class KernelError(Exception):
    """扫描内核不可证——fail-loud，不猜绿。"""


def err(msg):
    sys.stderr.write("[scrub-selfcheck] %s\n" % msg)


def hint_for(pid_tag):
    return HINT_BY_PID.get(pid_tag, HINT_SENT)


def format_hit(path, ln, pid_tag):
    line_s = "-" if ln is None else str(ln)
    return "HIT %s:%s [%s] %s" % (path, line_s, pid_tag, hint_for(pid_tag))


# ---- 只读提取：照抄 gates.yml bot-scrub 步 load_scan_text 语义 ----------------

def _load_names(node):
    return {x.id for x in ast.walk(node)
            if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Load)}


def load_scan_text(mirror_path=None):
    """从 mirror-disclose.sh 内嵌 PYEOF 段 AST 切出 scan_text/scan_g13 闭包。

    取法与 gates.yml bot-scrub 步逐项同款：只执行扫描纯函数及其依赖，
    不跑 git / argparse / main。缺件或切不出 ⇒ KernelError（rc=2）。
    """
    path = mirror_path or MIRROR_PATH
    if not os.path.isfile(path):
        raise KernelError("%s 不在位——扫描内核缺席（不可证不猜绿）" % path)
    lines = open(path, "r", encoding="utf-8").readlines()
    try:
        start = next(i for i, l in enumerate(lines) if "<<'PYEOF'" in l)
        end = next(i for i, l in enumerate(lines) if i > start and l.strip() == "PYEOF")
    except StopIteration:
        raise KernelError("%s 里找不到内嵌 python 段（PYEOF）" % path)
    src = "".join(lines[start + 1:end])
    tree = ast.parse(src, filename=path + "#embedded")

    wanted = {"scan_text", "scan_g13", "NAMES", "COMPILED", "PATTERNS"}
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

    selected, frontier = set(), set(wanted)
    while frontier:
        name = frontier.pop()
        if name in selected:
            continue
        selected.add(name)
        node = defs.get(name) or assigns.get(name)
        if node is None:
            continue
        for g in _load_names(node):
            if g not in selected and g not in _EXTRACT_BUILTINS and (
                    g in defs or g in assigns):
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
    body = [defs.get(n) or assigns.get(n)
            for n in sorted(selected, key=lambda n: order.get(n, 10 ** 6))]
    body = [b for b in body if b is not None]
    ns = {"re": re, "bisect": __import__("bisect"), "os": os, "sys": sys}
    exec(compile(ast.Module(body=body, type_ignores=[]), path, "exec"), ns)
    if "scan_text" not in ns:
        raise KernelError("%s 内嵌段里找不到 scan_text" % path)
    compiled = ns.get("COMPILED", [])
    patterns = ns.get("PATTERNS", [])
    return {
        "scan_text": ns["scan_text"],
        "scan_g13": ns.get("scan_g13"),
        "NAMES": ns.get("NAMES") or {},
        "n_compiled": len(compiled),
        "n_patterns": len(patterns),
        "pattern_ids": [p[0] for p in patterns] if patterns else [],
        "source": path,
    }


_KERNEL = None


def kernel():
    global _KERNEL
    if _KERNEL is None:
        _KERNEL = load_scan_text()
    return _KERNEL


def gates_contract_ok():
    """gates.yml 内嵌段仍声明「复用 mirror-disclose scan_text / 十八模式 / G-13」。"""
    if not os.path.isfile(GATES_PATH):
        return False, "gates.yml 不在位"
    text = open(GATES_PATH, encoding="utf-8").read()
    needles = ("scan_text", "scan_g13", "mirror-disclose.sh",
               "18 模式", "G-13 线性内核", "<<'PYEOF'")
    missing = [n for n in needles if n not in text]
    if missing:
        return False, "缺声明 %r" % missing
    return True, "ok"


# ---- 扫描面（文件/目录；语义对齐 gates.yml 树扫：未覆盖 fail-closed）--------

def iter_targets(paths):
    for p in paths:
        if os.path.isfile(p):
            yield p
        elif os.path.isdir(p):
            for dirpath, dirnames, filenames in os.walk(p):
                dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
                for fn in sorted(filenames):
                    yield os.path.join(dirpath, fn)
        else:
            yield p


def scan_one(path, scan_fn):
    """扫单文件。返回 dict: kind=hit|clean|uncovered|missing|error，hits 为 (pid, ln) 列表。"""
    if not os.path.isfile(path):
        return {"path": path, "kind": "missing", "hits": [], "reason": "missing"}
    try:
        size = os.path.getsize(path)
        if size > MAX_FILE_BYTES:
            return {"path": path, "kind": "uncovered", "hits": [], "reason": "oversize"}
        raw = open(path, "rb").read()
    except Exception as exc:
        return {"path": path, "kind": "error", "hits": [("READ-FAIL", None)],
                "reason": str(exc)[:120]}
    if b"\x00" in raw[:8192]:
        return {"path": path, "kind": "uncovered", "hits": [], "reason": "binary"}
    try:
        txt = raw.decode("utf-8")
    except Exception:
        return {"path": path, "kind": "uncovered", "hits": [], "reason": "non-utf8"}
    t0 = time.monotonic()
    try:
        recs = scan_fn(txt)
    except Exception as exc:
        return {"path": path, "kind": "error", "hits": [("SCAN-ERROR", None)],
                "reason": str(exc)[:120]}
    if time.monotonic() - t0 > PER_FILE_BUDGET_S:
        return {"path": path, "kind": "error", "hits": [("BUDGET-EXCEEDED", None)],
                "reason": "budget"}
    recs = list(recs)
    if recs:
        return {"path": path, "kind": "hit", "hits": recs, "reason": None}
    return {"path": path, "kind": "clean", "hits": [], "reason": None}


def run_check(paths, scan_fn=None):
    if not paths:
        err("用法：--check <文件或目录> [更多路径…]")
        return RC_UNPROVABLE
    try:
        kn = kernel() if scan_fn is None else None
    except KernelError as exc:
        err(str(exc))
        return RC_UNPROVABLE
    scan_fn = scan_fn or kn["scan_text"]
    scanned = 0
    hits_n = 0
    unc_n = 0
    missing = []
    verdict_block = False
    for path in iter_targets(paths):
        rec = scan_one(path, scan_fn)
        kind = rec["kind"]
        if kind == "missing":
            missing.append(path)
            continue
        scanned += 1
        if kind == "uncovered":
            unc_n += 1
            verdict_block = True
            print("UNCOVERED %s:- [%s] %s" % (path, rec["reason"], HINT_UNC))
            continue
        if kind == "error":
            verdict_block = True
            pid_tag = rec["hits"][0][0] if rec["hits"] else "SCAN-ERROR"
            hint = HINT_BUDGET if pid_tag == "BUDGET-EXCEEDED" else HINT_UNC
            print("HIT %s:- [%s] %s" % (path, pid_tag, hint))
            continue
        for pid_tag, ln in rec["hits"]:
            hits_n += 1
            verdict_block = True
            print(format_hit(path, ln, pid_tag))
    if missing:
        for p in missing:
            err("路径不在位：%s" % p)
        print("SCRUB: scanned=%d hits=%d uncovered=%d verdict=unprovable missing=%d"
              % (scanned, hits_n, unc_n, len(missing)))
        return RC_UNPROVABLE
    verdict = "block" if verdict_block else "clean"
    print("SCRUB: scanned=%d hits=%d uncovered=%d verdict=%s"
          % (scanned, hits_n, unc_n, verdict))
    return RC_HIT if verdict_block else RC_OK


# ---- 夹具构造：运行时拼接，源码不含真实前缀族假令牌字面 ----------------------

def _fx_payloads():
    """十八模式族各一条脏载荷（拼接构造；源码侧无连续假令牌字面）。"""
    a, b, c = "A" * 40, "B" * 40, "C" * 40
    hx = "a" * 32
    return (
        ("G-01", "eyJ" + a[:8] + "." + b[:4] + "." + c[:8]),
        ("G-02", "sk" + "-" + a[:12]),
        ("G-03", "ghp" + "_" + a[:20]),
        ("G-04", "AKIA" + "0" * 16),
        ("G-05", "xox" + "b" + "-" + a[:10]),
        ("G-06", "AIza" + a[:30]),
        ("G-07", "sk" + "_" + "test" + "_" + a[:16]),
        ("G-08", "SG" + "." + a[:16] + "." + b[:27]),
        ("G-09", "npm" + "_" + a[:36]),
        ("G-10", "pypi" + "-" + a[:40]),
        ("G-11", "Bearer" + " " + a[:8]),
        ("G-12", "-----" + "BEGIN " + "RSA PRIV" + "ATE KEY-----\nMII\n-----"
                 + "END " + "RSA PRIV" + "ATE KEY-----"),
        ("G-13", ("tok" + "en") + "=" + "abcdef123456"),
        ("P-01", "https" + "://" + "u" + ":" + "abcd" + "@" + "example.invalid"),
        ("P-02", "hvs" + "." + a[:10]),
        ("P-03", a[:23] + "." + b[:22] + "." + c[:11]),
        ("P-04", ".".join(("100", "64", "1", "2"))),
        ("P-05", "claim" + "_" + "tok" + "en" + "=" + hx),
    )


def _fx_g13_negatives():
    lhs = "tok" + "en"
    return (
        lhs + ": null",
        ("pas" + "sword") + ": 123456",
        lhs + "=" + "short",
        ("pas" + "sword") + " = 12.34, x",
        lhs + "=\"" + "abc" + "\"",
    )


def _fx_g13_suffix_clean():
    """卡面建议修法①：族词变量名加 _tag 后缀断开，应不命中 G-13。"""
    return ("tok" + "en") + "_tag = \"" + "abcdef123456" + "\""


def _write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
        if not text.endswith("\n"):
            f.write("\n")


def _cli(args, cwd=None):
    cmd = [sys.executable, "-I", os.path.abspath(__file__)] + list(args)
    return subprocess.run(cmd, cwd=cwd or ROOT_DIR,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def run_selftest():
    """夹具逐个真跑。每条独立断言，失败点名；全过才 rc=0。"""
    cases = []

    def chk(name, ok, detail=""):
        cases.append((name, bool(ok), detail))
        print("  自证·%s: %s%s" % (
            name, "OK" if ok else "FAIL",
            (" " + detail) if detail else ""))

    # ① 内核只读提取
    try:
        kn = load_scan_text()
        load_ok, load_detail = True, "compiled=%d patterns=%d" % (
            kn["n_compiled"], kn["n_patterns"])
    except KernelError as exc:
        kn = None
        load_ok, load_detail = False, str(exc)
    chk("内核加载 scan_text", load_ok and kn is not None
        and callable(kn.get("scan_text")), load_detail)
    if not load_ok:
        print("自证 内核不可证，后续夹具停跑")
        return RC_UNPROVABLE

    chk("十八模式族件数", kn["n_patterns"] == 18,
        "n_patterns=%s" % kn["n_patterns"])
    chk("COMPILED 17 条（G-13 走预筛）", kn["n_compiled"] == 17,
        "n_compiled=%s" % kn["n_compiled"])
    want_ids = ["G-%02d" % i for i in range(1, 14)] + ["P-0%d" % i for i in range(1, 6)]
    chk("模式号 G-01..G-13 + P-01..P-05", kn["pattern_ids"] == want_ids,
        "ids=%s" % kn["pattern_ids"])
    chk("scan_g13 在位", callable(kn.get("scan_g13")), "")

    # ② gates.yml 内嵌段契约（只读，零改动）
    g_ok, g_detail = gates_contract_ok()
    chk("gates.yml 内嵌段契约", g_ok, g_detail)

    scan_fn = kn["scan_text"]

    # ③ 十八模式族夹具：每条脏载荷必须命中对应 pid（真跑 scan_text）
    for pid_tag, payload in _fx_payloads():
        recs = scan_fn(payload + "\n")
        pids = sorted({p for p, _ in recs})
        chk("夹具·%s 命中" % pid_tag, pid_tag in {p for p, _ in recs},
            "pids=%s" % pids)

    # ④ G-13 负例（null / 纯数字 / 短值）不得命中 G-13
    for i, neg in enumerate(_fx_g13_negatives(), 1):
        recs = scan_fn(neg + "\n")
        pids = {p for p, _ in recs}
        chk("G-13 负例%d 不中" % i, "G-13" not in pids, "pids=%s" % sorted(pids))

    # ⑤ 后缀断开修法：token_tag = "…" 不中 G-13
    recs = scan_fn(_fx_g13_suffix_clean() + "\n")
    chk("G-13 后缀断开不中", "G-13" not in {p for p, _ in recs},
        "pids=%s" % sorted({p for p, _ in recs}))

    # ⑥ SENTINEL-XXX 形干净（卡面建议修法③）
    sent_txt = "x = \"SENTINEL-XXX-0001\"\n# placeholder only\n"
    recs = scan_fn(sent_txt)
    chk("SENTINEL 形干净", recs == [], "recs=%s" % recs)

    # ⑦ G-13 线性内核：长词串尾部真赋值，须秒级完成且命中
    soup = ("Z" * 200000) + "\n" + ("tok" + "en") + "=" + "abcdef123456" + "\n"
    t0 = time.monotonic()
    recs = scan_fn(soup)
    elapsed = time.monotonic() - t0
    pids = {p for p, _ in recs}
    chk("G-13 线性内核秒级", elapsed <= 5.0, "elapsed=%.3fs" % elapsed)
    chk("G-13 长串尾部仍命中", "G-13" in pids, "pids=%s" % sorted(pids))

    # ⑧ CLI 夹具真跑（subprocess -I 本件，实取 returncode）
    with tempfile.TemporaryDirectory(prefix="scrub-selfcheck-") as td:
        dirty_path = os.path.join(td, "dirty.txt")
        clean_path = os.path.join(td, "clean.txt")
        suffix_path = os.path.join(td, "suffix.txt")
        dir_a = os.path.join(td, "tree")
        os.mkdir(dir_a)
        _write(dirty_path, ("sk" + "-" + "A" * 12) + "\n")
        _write(clean_path, sent_txt)
        _write(suffix_path, _fx_g13_suffix_clean())
        _write(os.path.join(dir_a, "ok.txt"), "SENTINEL-XXX-DIR-0001\n")
        _write(os.path.join(dir_a, "bad.txt"),
               ("tok" + "en") + "=" + "abcdef123456" + "\n")

        r_dirty = _cli(("--check", dirty_path))
        out_d = r_dirty.stdout.decode("utf-8", "replace")
        chk("CLI 脏件 rc=1", r_dirty.returncode == RC_HIT,
            "rc=%s" % r_dirty.returncode)
        chk("CLI 脏件点名 file:line [G-02]",
            ("[G-02]" in out_d) and (os.path.basename(dirty_path) in out_d
                                     or dirty_path in out_d),
            "out=%s" % out_d.strip().replace("\n", " | ")[:200])
        chk("CLI 脏件含建议修法", "修法：" in out_d, "")

        r_clean = _cli(("--check", clean_path))
        out_c = r_clean.stdout.decode("utf-8", "replace")
        chk("CLI SENTINEL 净件 rc=0", r_clean.returncode == RC_OK,
            "rc=%s out=%s" % (r_clean.returncode, out_c.strip()[:120]))

        r_suf = _cli(("--check", suffix_path))
        chk("CLI 后缀断开 rc=0", r_suf.returncode == RC_OK,
            "rc=%s" % r_suf.returncode)

        r_dir = _cli(("--check", dir_a))
        out_dir = r_dir.stdout.decode("utf-8", "replace")
        chk("CLI 目录脏 rc=1", r_dir.returncode == RC_HIT,
            "rc=%s" % r_dir.returncode)
        chk("CLI 目录点名 bad.txt [G-13]",
            ("[G-13]" in out_dir) and "bad.txt" in out_dir,
            "out=%s" % out_dir.strip().replace("\n", " | ")[:200])

        r_miss = _cli(("--check", os.path.join(td, "no-such-file.txt")))
        chk("CLI 缺件 rc=2", r_miss.returncode == RC_UNPROVABLE,
            "rc=%s" % r_miss.returncode)

    # ⑨ 已修件应净（卡面验收命令）
    bao = os.path.join(TOOLS_DIR, "bao-shim.py")
    r_bao = _cli(("--check", bao))
    chk("CLI --check bao-shim.py rc=0", r_bao.returncode == RC_OK,
        "rc=%s out=%s" % (r_bao.returncode,
                          r_bao.stdout.decode("utf-8", "replace").strip()[:160]))

    # ⑩ 本件自身须净（ESC-43：预检件不得自己撞闸）
    r_self = _cli(("--check", os.path.abspath(__file__)))
    out_self = r_self.stdout.decode("utf-8", "replace")
    chk("本件自身 --check rc=0", r_self.returncode == RC_OK,
        "rc=%s out=%s" % (r_self.returncode, out_self.strip()[:200]))

    fails = [c for c in cases if not c[1]]
    n = len(cases)
    if fails:
        print("自证 %d/%d 例不符：%r" % (
            len(fails), n, [(f[0], f[2]) for f in fails]))
        return RC_HIT
    print("自证 %d/%d 例全过（十八模式族＋G-13 线性内核＋CLI 夹具真跑；零网络）"
          % (n, n))
    return RC_OK


def usage():
    sys.stdout.write(
        "用法:\n"
        "  python3 -I tools/scrub-selfcheck.py --selftest\n"
        "  python3 -I tools/scrub-selfcheck.py --check <文件或目录> [更多路径…]\n"
    )


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        usage()
        return RC_UNPROVABLE if not argv else RC_OK
    if argv[0] == "--selftest":
        return run_selftest()
    if argv[0] == "--check":
        return run_check(argv[1:])
    err("未知参数：%s" % argv[0])
    usage()
    return RC_UNPROVABLE


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
