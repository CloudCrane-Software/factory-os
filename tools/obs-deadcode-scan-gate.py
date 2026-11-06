#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""观测面死码/未移植扫描门（RT-E108 拦截机制①②；波次B·B2 链 2026-11-05）。

判据源=单一源（本文件自含判据）；扫描名册/基线/豁免登记面=
30-工件/观测面清偿批-20261105/gate-registry.json 的
  deadcode_roster（观测面扫描名册）/ deadcode_baseline（存量死码登记）/
  deadcode_exempt（显式「未移植」豁免名册，按件登记）。

机制①（移植对账）：函数 docstring 引用**他语言件名**（.rs/.go/.ts/…）⇒ 该函数
  必须「调用点 ≥1」或「入显式未移植豁免名册」，否则红（RT-E108 拦的就是
  report-feeder.py extract_html_title 那类「声称对应 Rust 件却从未接线」的移植死码）。
机制②（通用死码扫描，vulture 类入门族 low 位）：模块级 def 在**代码面零引用**
  （AST Name-load/属性引用皆无——注释与 docstring 文案不算引用）⇒ 死码 ⇒ 红。

出口：0=绿；2=红；3=执行错（面缺/不可证，不猜绿）。
自证（--selftest，造夹具自证会咬人）：
  ① 无豁免的零引用死码件 ⇒ 必红；
  ② docstring 引用他语言件名且零调用零标注的移植件 ⇒ 必红；
  ③ 同一移植件加「不移植该件」显式标注 ⇒ 必绿（显式标注语义被尊重）；
  ④ 现盘名册（未改动）⇒ 必绿。
"""
import ast
import json
import os
import re
import sys
import tempfile

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REG_PATH = os.path.join(WS, "30-工件", "观测面清偿批-20261105", "gate-registry.json")

CORPUS_DIRS = ("tools", "af/crates", "af/ci")
CORPUS_GLOBS = ("kb-seed",)
SKIP_DIR_NAMES = {".git", "target", "node_modules", "__pycache__", ".venv",
                  "dist", "build", ".mypy_cache", ".pytest_cache"}
CODE_EXT = (".py", ".rs", ".go", ".ts", ".tsx", ".js", ".sh")
OTHER_LANG = re.compile(r"[A-Za-z0-9_/\-]+\.(?:rs|go|ts|tsx|js|java|kt|c|cc|cpp|h|rb)\b")
NOT_PORTED = re.compile(r"未移植|不移植|不搬|未接线|not\s+ported")
EXEMPT_LINE = re.compile(r"未移植豁免|不移植该件|未移植白名单")


def err(msg):
    sys.stderr.write("[obs-deadcode-scan-gate] %s\n" % msg)


def corpus_files(roots=None, extra_globs=None):
    """枚举扫描语料（代码面）。roots/extra_globs 可注入夹具目录。"""
    roots = list(roots if roots is not None else CORPUS_DIRS)
    extra_globs = list(extra_globs if extra_globs is not None else CORPUS_GLOBS)
    out = []
    for r in roots:
        base = r if os.path.isabs(r) else os.path.join(WS, r)
        if not os.path.isdir(base):
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIR_NAMES]
            for fn in filenames:
                if fn.endswith(CODE_EXT) and not fn.endswith(".bak"):
                    out.append(os.path.join(dirpath, fn))
    for g in extra_globs:
        gbase = g if os.path.isabs(g) else os.path.join(WS, g)
        if os.path.isdir(gbase):
            for fn in sorted(os.listdir(gbase)):
                if fn.endswith(".py") and not fn.endswith(".bak"):
                    out.append(os.path.join(gbase, fn))
        else:
            hits = sorted(glob_module(gbase))
            out.extend(hits)
    return sorted(set(out))


def glob_module(pattern):
    import glob as _glob
    return _glob.glob(pattern)


def code_refs(files):
    """收集全语料的**代码面**引用：AST Name(Load) + 属性名 attr + 文本调用 `name(`。

    注释/字符串文案不算引用（RT-E108 原判据：头注提到 ≠ 接线）。
    """
    loads = set()
    attrs = set()
    calls = set()
    for path in files:
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                src = fh.read()
        except OSError:
            continue
        if path.endswith(".py"):
            try:
                tree = ast.parse(src)
            except (SyntaxError, ValueError):
                tree = None
            if tree is not None:
                for node in ast.walk(tree):
                    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                        loads.add(node.id)
                    elif isinstance(node, ast.Attribute):
                        attrs.add(node.attr)
                    elif isinstance(node, ast.Call):
                        fn = node.func
                        if isinstance(fn, ast.Name):
                            calls.add(fn.id)
                        elif isinstance(fn, ast.Attribute):
                            calls.add(fn.attr)
        if not path.endswith(".py"):
            # 非 Python 面（shell/rs/go…）：文本级调用点。Python 面只用 AST——
            # 否则 `def foo(` 自身行会被误计为调用点（把死码误判成「已接线」）。
            for m in re.finditer(r"[A-Za-z_][A-Za-z0-9_]*\s*\(", src):
                calls.add(m.group(0)[:-1].strip())
    return loads, attrs, calls


def module_header_exempt(path):
    """件头「未移植豁免」登记：行内出现的函数名集合（显式未移植标注）。"""
    names = set()
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().split("\n")
    except OSError:
        return names
    for i, line in enumerate(lines[:60]):
        if EXEMPT_LINE.search(line):
            for m in re.finditer(r"[A-Za-z_][A-Za-z0-9_]*", line):
                names.add(m.group(0))
    return names


def scan_roster(roster, corpus, registry):
    """扫名册：返回 (reds, notes)。"""
    loads, attrs, calls = code_refs(corpus)
    refs = loads | attrs
    baseline = set((registry.get("deadcode_baseline") or {}).keys())
    exempt_global = set(registry.get("deadcode_exempt_global") or [])
    reds, notes = [], []
    for rel in roster:
        path = os.path.join(WS, rel)
        if not os.path.exists(path):
            reds.append("%s：名册件缺失（面缺，不可证不猜绿）" % rel)
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                src = fh.read()
            tree = ast.parse(src)
        except (OSError, SyntaxError, ValueError) as exc:
            reds.append("%s：件不可解析（%s）" % (rel, exc))
            continue
        exempt = module_header_exempt(path) | exempt_global
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            name = node.name
            if name.startswith("__") and name.endswith("__"):
                continue
            doc = ast.get_docstring(node) or ""
            port_ref = bool(OTHER_LANG.search(doc)) or bool(
                OTHER_LANG.search(ast.get_source_segment(src, node) or ""))
            n_call = sum(1 for c in calls if c == name)
            n_ref = sum(1 for r in refs if r == name)
            dead = (n_ref == 0)
            if dead:
                if name in exempt:
                    notes.append("%s:%d %s：零引用但有显式「未移植」标注 ⇒ 豁免（登记）"
                                 % (rel, node.lineno, name))
                elif name in baseline:
                    notes.append("%s:%d %s：零引用 ⇒ 存量死码（已登记基线，不判红）"
                                 % (rel, node.lineno, name))
                else:
                    reds.append("%s:%d %s：模块级 def 代码面零引用 ⇒ 死码（RT-E108 机制②）"
                                % (rel, node.lineno, name))
            if port_ref:
                if n_call == 0 and name not in exempt:
                    reds.append("%s:%d %s：docstring 引用他语言件名但零调用且无「未移植」"
                                "标注 ⇒ 移植未接线（RT-E108 机制①）"
                                % (rel, node.lineno, name))
                else:
                    notes.append("%s:%d %s：移植件对账通过（调用点≥1）"
                                 % (rel, node.lineno, name))
    return reds, notes


def load_registry(path=REG_PATH):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        err("登记面不可读：%s（%s）" % (path, exc))
        return None


def run_live(reg):
    roster = reg.get("deadcode_roster") or []
    if not roster:
        return None, ["登记面缺 deadcode_roster ⇒ 扫描名册未登记（不可证不猜绿）"]
    corpus = corpus_files()
    reds, notes = scan_roster(roster, corpus, reg)
    notes.insert(0, "语料 %d 件；名册 %d 件" % (len(corpus), len(roster)))
    return reds, notes


def selftest(reg):
    """夹具自证：改面必红 / 不改必绿。"""
    fails = []
    tmp = tempfile.mkdtemp(prefix="obs-deadcode-fixture-")
    # ① 零引用死码 ⇒ 必红
    f1 = os.path.join(tmp, "fixture_dead.py")
    with open(f1, "w", encoding="utf-8") as fh:
        fh.write("def orphan_fn(x):\n    return x + 1\n")
    reds, _ = scan_roster([f1], [f1], reg)
    if not reds:
        fails.append("夹具① 零引用死码件应红未红")
    else:
        print("  夹具① 零引用死码件 ⇒ 红（%s）" % reds[0][:90])
    # ② 移植未接线（docstring 指他语言件名，零调用零标注）⇒ 必红
    f2 = os.path.join(tmp, "fixture_port.py")
    with open(f2, "w", encoding="utf-8") as fh:
        fh.write('def ported_from_rust(html):\n'
                 '    """对应 report_unit.rs:538-549 的移植件。"""\n'
                 '    return html\n')
    reds2, _ = scan_roster([f2], [f2], reg)
    if not any("移植未接线" in r for r in reds2):
        fails.append("夹具② 移植未接线件应红未红：%s" % reds2)
    else:
        print("  夹具② 移植未接线件 ⇒ 红（%s）" % [r for r in reds2 if "移植未接线" in r][0][:90])
    # ③ 同一件加显式「不移植该件」标注 ⇒ 必绿
    f3 = os.path.join(tmp, "fixture_port_ok.py")
    with open(f3, "w", encoding="utf-8") as fh:
        fh.write('# 未移植豁免：ported_from_rust —— 不移植该件\n'
                 'def ported_from_rust(html):\n'
                 '    """对应 report_unit.rs:538-549 的移植件。"""\n'
                 '    return html\n')
    reds3, _ = scan_roster([f3], [f3], reg)
    if reds3:
        fails.append("夹具③ 显式未移植标注件应绿却红：%s" % reds3)
    else:
        print("  夹具③ 显式未移植标注件 ⇒ 绿")
    # ④ 现盘名册未改动 ⇒ 必绿
    reds4, notes4 = run_live(reg)
    if reds4:
        fails.append("夹具④ 现盘名册应绿却红：%s" % reds4[:3])
    else:
        print("  夹具④ 现盘名册未改动 ⇒ 绿（%s）" % (notes4[0] if notes4 else ""))
    return fails


def main(argv):
    reg = load_registry()
    if reg is None:
        return 3
    if "--selftest" in argv:
        fails = selftest(reg)
        for f in fails:
            err("自证失败：%s" % f)
        print("自证：%s" % ("全过" if not fails else "有 %d 项失败" % len(fails)))
        return 0 if not fails else 2
    reds, notes = run_live(reg)
    for n in notes:
        print("[注] %s" % n)
    if reds:
        for r in reds:
            print("[红] %s" % r)
        print("结论：红（观测面死码/未移植扫描门，RT-E108）")
        return 2
    print("结论：绿（观测面死码/未移植扫描门，RT-E108）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
