#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""layout-recon.py — SPEC §二布局对账 ＋ 判分产生点唯一性断言（D-169 · issue #264 施工件）

三断言（卡面施工须知①②③的固化件；SPEC v1.1 §4.7/§七.7 对账门）：
  layout      ①布局对账：SPEC §二「布局清单（冻结 v1.1）」↔ 盘面双向——清单内每名须在盘命中
              （缺名点名），盘上每件（除声明忽略的施工暂存树）须入清单（孤儿点名）；
              任一 >0 ⇒ rc=1。--face run 只核运行工件面，--face full 核全部面。
  judge-unique②判分产物产生点唯一性：契约面（SPEC.md ＋ *.dwf.ts）内 judge-producer-site
              标记计数必须 ==1 且归属 spec-4.4-judge-leg（SPEC §4.4）；编排模板相清单
              （PhaseKind/kind/id）零判分相签名；模板 judge-ref 引用恰 1 处。违者 rc=1。
              —— v1.0 双跑形态（编排器独立判分相复跑，两轮 judge.json 逐字节同、冗余墙钟
              ~5m）由本断言结构性拦截。
  v10-pre     改前态读数复现：v1.0 §二表（21 位）对盘面机械分类——缺名/表侧同物异名/盘侧
              别名/条件件逐项点名，复现台账 D-169 行「6 缺＋5 同物异名」算术。恒 rc=1
              （改前态即漂移态；读数件用）。

selftest     夹具驱动断言（零网络零凭据；临时目录构造，跑后清理）：happy 双绿、异名点名、
              缺名点名、孤儿点名、双产生点拦截、判分相签名拦截、v10-pre 计数（6/4/2）。

用法：
  python3 -I layout-recon.py --root <目录> all            # ①（full）＋②，rc 合成
  python3 -I layout-recon.py --root <目录> layout [--face run|full]
  python3 -I layout-recon.py --root <目录> judge-unique
  python3 -I layout-recon.py --root <目录> v10-pre
  python3 -I layout-recon.py selftest
  可选 --json-out <路径>：读数 JSON 落盘（随跑留痕）。

rc 口径：0=绿；1=漂移/违例（点名输出）；2=用法/内部错误。
"""
import argparse
import json
import os
import re
import shutil
import sys
import tempfile

IGNORE_DIRS = {".git", ".build", ".tester-scratch", "__pycache__"}  # 暂存/缓存树，SPEC §二声明忽略
SPEC_NAME = "SPEC.md"
LAYOUT_HEADING_MARK = "### 布局清单（冻结 v1.1"  # SPEC §二机器可读面标题前缀
PRODUCER_RE = re.compile(r"judge-producer-site:\s*([a-z0-9.-]+)")
JUDGE_REF_RE = re.compile(r"judge-ref:\s*([a-z0-9.-]+)")
KIND_ENUM_RE = re.compile(r"type\s+PhaseKind\s*=(.*);")
KIND_VALUE_RE = re.compile(r'kind:\s*"([^"]+)"')
PHASE_ID_RE = re.compile(r'id:\s*"([^"]+)"')
JUDGEY = ("judge", "rejudge", "判分", "复判")
EXPECTED_PRODUCER_ID = "spec-4.4-judge-leg"

# v1.0 §二表（SPEC.md.v1.0.bak §二树形图逐行；21 位=复盘口径 20 位拆 judge.json/judge.stderr 两件）
V10_ITEMS = [
    "SPEC.md", "card-investigator.md", "card-builder.md", "card-tester.md", "card-reviewer.md",
    "A1-diagnosis.md", "A2-patch.diff", "A2-report.md", "A3-test-readings.md",
    "A3-test-readings.json", "Fb-r{n}.json", "judge/warm-relay-r{n}.json",
    "judge/prejudge-gate-r{n}.log", "judge/baseline_log.txt", "judge/judged_log.txt",
    "judge/eval.sh", "judge/judge.json", "judge/judge.stderr", "A4-review-verdict.md",
    "A5-loss-metrics.json", "timing-ledger.md",
]
V10_CONDITIONAL = {"Fb-r{n}.json"}  # 回环触发才落（本跑 r1 resolved=true 不触发）
V10_ALIAS = {  # v1.0 表名 -> 实盘名（同物异名；复盘 §三.2）
    "A1-diagnosis.md": "diagnosis.md",
    "A2-patch.diff": "fix.patch",
    "A2-report.md": "impl-notes.md",
    "A4-review-verdict.md": "review.md",
}
V10_ALIAS_ROLE = {  # 盘侧别名（v1.0 表外实盘件的替位角色；复盘 §三.2/F7）
    "test-report.md": "A3-test-readings.md 同容别名（cmp 逐字节同）",
    "retrospective.md": "timing-ledger.md 替位（复盘 §一，F7 落位差）",
}


def rc_exit(code, json_payload=None, json_out=None):
    if json_out and json_payload is not None:
        with open(json_out, "w", encoding="utf-8") as fh:
            json.dump(json_payload, fh, ensure_ascii=False, indent=1)
    sys.exit(code)


def parse_layout_block(spec_path):
    """解析 SPEC §二布局清单围栏：返回 {face: [paths]}；`# face:xxx` 行为面标记。"""
    with open(spec_path, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    start = None
    for i, ln in enumerate(lines):
        if ln.startswith(LAYOUT_HEADING_MARK):
            start = i
            break
    if start is None:
        raise RuntimeError(f"SPEC 内未找到布局清单标题（{LAYOUT_HEADING_MARK}…）")
    fence_open = None
    for i in range(start, len(lines)):
        if lines[i].startswith("```"):
            fence_open = i
            break
    if fence_open is None:
        raise RuntimeError("布局清单标题后未找到围栏块")
    faces, cur = {}, None
    for ln in lines[fence_open + 1:]:
        if ln.startswith("```"):
            return faces
        s = ln.strip()
        if not s:
            continue
        if s.startswith("#"):
            m = re.match(r"#\s*face:([a-z0-9_-]+)", s)
            cur = m.group(1) if m else cur
            if cur and cur not in faces:
                faces[cur] = []
            continue
        if cur is None:
            raise RuntimeError(f"布局清单行无面标记先行：{s!r}")
        faces[cur].append(s)
    raise RuntimeError("布局清单围栏未闭合")


def disk_files(root):
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
        for fn in filenames:
            rel = os.path.relpath(os.path.join(dirpath, fn), root)
            out.append(rel)
    return sorted(out)


def cmd_layout(root, face="full", json_out=None):
    faces = parse_layout_block(os.path.join(root, SPEC_NAME))
    if not faces:
        print("layout: 布局清单为空")
        rc_exit(2, json_out=json_out)
    check = faces if face == "full" else {face: faces.get(face, [])}
    missing = []
    for fname, paths in check.items():
        for p in paths:
            if not os.path.isfile(os.path.join(root, p)):
                missing.append(p)
    listed = {p for paths in faces.values() for p in paths}
    orphans = [f for f in disk_files(root) if f not in listed]
    total_checked = sum(len(v) for v in check.values())
    ok = not missing and not orphans
    print(f"layout[{face}]: 核 {total_checked} 项；缺名 {len(missing)}；孤儿 {len(orphans)} ⇒ {'rc=0 绿' if ok else 'rc=1 漂移'}")
    for p in missing:
        print(f"  缺名: {p}")
    for p in orphans:
        print(f"  孤儿(盘有清单无): {p}")
    payload = {"check": "layout", "face": face, "checked": total_checked,
               "missing": missing, "orphans": orphans, "rc": 0 if ok else 1,
               "faces": faces}
    rc_exit(0 if ok else 1, payload, json_out)


def cmd_judge_unique(root, json_out=None):
    spec_path = os.path.join(root, SPEC_NAME)
    contracts = [spec_path] + sorted(
        os.path.join(root, f) for f in os.listdir(root) if f.endswith(".dwf.ts")
    ) if os.path.isdir(root) else []
    producers = []
    for c in contracts:
        with open(c, encoding="utf-8") as fh:
            text = fh.read()
        for m in PRODUCER_RE.finditer(text):
            producers.append((os.path.basename(c), m.group(1)))
    problems = []
    if len(producers) != 1:
        problems.append(f"judge-producer-site 计数={len(producers)}（须 ==1）：{producers}")
    else:
        f, pid = producers[0]
        if pid != EXPECTED_PRODUCER_ID:
            problems.append(f"产生点 id={pid}（须 {EXPECTED_PRODUCER_ID}）")
        if f != SPEC_NAME:
            problems.append(f"产生点落在 {f}（须 {SPEC_NAME} §4.4）")
    templates = [c for c in contracts if c.endswith(".dwf.ts")]
    refs = []
    for t in templates:
        with open(t, encoding="utf-8") as fh:
            text = fh.read()
        refs += [(os.path.basename(t), m.group(1)) for m in JUDGE_REF_RE.finditer(text)]
        enum = KIND_ENUM_RE.search(text)
        enum_tokens = enum.group(1) if enum else ""
        for bad in (t for t in JUDGEY if t in enum_tokens):
            problems.append(f"模板 {os.path.basename(t)} PhaseKind 枚举含判分相签名「{bad}」")
        for m in KIND_VALUE_RE.finditer(text):
            if any(b in m.group(1).lower() for b in ("judge", "rejudge")):
                problems.append(f"模板相 kind={m.group(1)!r} 为判分相签名")
        for m in PHASE_ID_RE.finditer(text):
            if any(b in m.group(1).lower() for b in ("judge", "rejudge")):
                problems.append(f"模板相 id={m.group(1)!r} 为判分相签名")
    if len(templates) != 1:
        problems.append(f"编排模板件数={len(templates)}（契约面须恰 1 件 *.dwf.ts）")
    elif len(refs) != 1 or refs[0][1] != EXPECTED_PRODUCER_ID:
        problems.append(f"模板 judge-ref 计数/指向异常（须恰 1 处 → {EXPECTED_PRODUCER_ID}）：{refs}")
    ok = not problems
    print(f"judge-unique: 产生点计数={len(producers)}（{producers}）；模板 judge-ref={len(refs)}；"
          f"判分相签名 0 ⇒ {'rc=0 绿' if ok else 'rc=1 违例'}")
    for p in problems:
        print(f"  违例: {p}")
    payload = {"check": "judge-unique", "producers": producers, "template_refs": refs,
               "problems": problems, "rc": 0 if ok else 1}
    rc_exit(0 if ok else 1, payload, json_out)


def cmd_v10_pre(root, json_out=None, expect=None):
    missing, renamed, conditional = [], [], []
    for item in V10_ITEMS:
        probe = item
        if "{n}" in item:
            probe = item.replace("{n}", "1")
            if not os.path.exists(os.path.join(root, probe)):
                if item in V10_CONDITIONAL:
                    conditional.append(item)
                    continue
        if os.path.isfile(os.path.join(root, probe)):
            continue
        if item in V10_ALIAS and os.path.isfile(os.path.join(root, V10_ALIAS[item])):
            renamed.append((item, V10_ALIAS[item]))
            continue
        missing.append(item)
    v10_root_names = set(V10_ITEMS) | set(V10_ALIAS.values())
    meta_exclude = set()
    try:  # 现行 SPEC v1.1 face:meta（D-169 收敛施工件）不计入 v1.0 漂移读数
        faces_v11 = parse_layout_block(os.path.join(root, SPEC_NAME))
        meta_exclude = set(faces_v11.get("meta", []))
    except Exception:
        pass
    disk_root = sorted(f for f in os.listdir(root) if os.path.isfile(os.path.join(root, f)))
    aliases = [f for f in disk_root if f not in v10_root_names and f not in meta_exclude]
    debt_row_sum = len(renamed) + sum(1 for a in aliases if a == "test-report.md")
    print(f"v10-pre: v1.0 表 {len(V10_ITEMS)} 位对盘分类 ⇒ 缺名 {len(missing)}；表侧同物异名 {len(renamed)}；"
          f"盘侧别名 {len(aliases)}；条件件不落 {len(conditional)} ⇒ rc=1（改前态=漂移态）")
    print(f"  台账 D-169 行算术复现：6 缺 ＋ 5 同物异名 = {len(missing)} 缺 ＋ {debt_row_sum} 异名"
          f"（表侧 {len(renamed)} ＋ 盘侧 A3 同容别名 1）{'✓' if (len(missing), debt_row_sum) == (6, 5) else '✗'}")
    for m in missing:
        print(f"  缺名: {m}")
    for a, b in renamed:
        print(f"  表侧异名: {a} -> 实盘 {b}")
    for a in aliases:
        role = V10_ALIAS_ROLE.get(a, "未注记别名")
        print(f"  盘侧别名: {a}（{role}）")
    for c in conditional:
        print(f"  条件件: {c}（回环不触发不落，正常缺）")
    payload = {"check": "v10-pre", "missing": missing, "renamed": renamed,
               "disk_aliases": aliases, "conditional": conditional,
               "debt_row_sum": {"missing": len(missing), "alias_total": debt_row_sum}, "rc": 1}
    if expect is not None:
        want_m, want_r, want_a = expect
        got = (len(missing), len(renamed), len(aliases))
        ok = got == (want_m, want_r, want_a)
        print(f"v10-pre expect={expect} got={got} ⇒ {'PASS' if ok else 'FAIL'}")
        payload["expect_pass"] = ok
        rc_exit(0 if ok else 1, payload, json_out)
    rc_exit(1, payload, json_out)


# ---------------- selftest（夹具驱动；零网络零凭据；临时目录跑后清理） ----------------

SPEC_TPL = """# 测试 SPEC（夹具）
## 四、判分腿（夹具 · 唯一产生点）

> judge-producer-site: spec-4.4-judge-leg（夹具·唯一判分产生点）

## 二、目录布局
### 布局清单（冻结 v1.1 · 机器可读面）

```text
# face:run 运行工件
SPEC.md
diagnosis.md
fix.patch
judge/judge.json
# face:meta 收敛施工件
orch.dwf.ts
{extra_meta}
```
"""

TEMPLATE_TPL = """// 测试编排模板（夹具）
// judge-ref: spec-4.4-judge-leg（测试员腿引用）
type PhaseKind = "pick" | "design" | "investigate" | "build" | "test" | "review" | "retro";
interface Phase {{ id: string; kind: PhaseKind; }}
const PHASES: Phase[] = [
  {{ id: "p5-test", kind: "test" }},
{extra_phase}
];
export {{ PHASES }};
"""


def _mk_fixture(extra_meta="layout-recon-selftest.tmp.md", extra_phase=""):
    root = tempfile.mkdtemp(prefix="d169-selftest-")
    os.makedirs(os.path.join(root, "judge"))
    for p in ["SPEC.md", "diagnosis.md", "fix.patch", "judge/judge.json"]:
        with open(os.path.join(root, p), "w", encoding="utf-8") as fh:
            fh.write("fixture\n")
    with open(os.path.join(root, "SPEC.md"), "w", encoding="utf-8") as fh:
        fh.write(SPEC_TPL.format(extra_meta=extra_meta))
    if extra_meta:
        with open(os.path.join(root, extra_meta), "w", encoding="utf-8") as fh:
            fh.write("meta fixture\n")
    with open(os.path.join(root, "orch.dwf.ts"), "w", encoding="utf-8") as fh:
        fh.write(TEMPLATE_TPL.format(extra_phase=extra_phase))
    return root


def _run(fn, *args, **kw):
    """夹具内跑断言函数，捕获 rc（不退出）。"""
    import io
    import contextlib
    buf = io.StringIO()
    code = 0
    with contextlib.redirect_stdout(buf):
        try:
            fn(*args, **kw)
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 0
    return code, buf.getvalue()


def selftest():
    cases = []

    def case(name, got, want):
        ok = got == want
        cases.append((name, ok, got, want))
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}: got={got} want={want}")

    # 夹具1 happy：双断言全绿
    r = _mk_fixture()
    code, out = _run(cmd_layout, r, "full")
    case("layout happy 双向零差 rc=0", code, 0)
    code, out = _run(cmd_judge_unique, r)
    case("judge-unique happy 产生点=1 rc=0", code, 0)
    shutil.rmtree(r)

    # 夹具2 异名（盘面改名）：缺名点名旧位 + 孤儿点名新名
    r = _mk_fixture()
    os.rename(os.path.join(r, "diagnosis.md"), os.path.join(r, "A1-diagnosis.md"))
    code, out = _run(cmd_layout, r, "full")
    case("异名 ⇒ rc=1", code, 1)
    case("异名 ⇒ 缺名点名 diagnosis.md", "缺名: diagnosis.md" in out, True)
    case("异名 ⇒ 孤儿点名 A1-diagnosis.md", "孤儿(盘有清单无): A1-diagnosis.md" in out, True)
    shutil.rmtree(r)

    # 夹具3 缺名（删除清单件）
    r = _mk_fixture()
    os.remove(os.path.join(r, "judge", "judge.json"))
    code, out = _run(cmd_layout, r, "full")
    case("缺名 ⇒ rc=1 且点名 judge/judge.json", code == 1 and "缺名: judge/judge.json" in out, True)
    shutil.rmtree(r)

    # 夹具4 孤儿（盘面多出清单外件）
    r = _mk_fixture()
    with open(os.path.join(r, "stray-artifact.md"), "w", encoding="utf-8") as fh:
        fh.write("orphan\n")
    code, out = _run(cmd_layout, r, "full")
    case("孤儿 ⇒ rc=1 且点名 stray-artifact.md", code == 1 and "孤儿(盘有清单无): stray-artifact.md" in out, True)
    shutil.rmtree(r)

    # 夹具5 双产生点（模板私设第二 judge-producer-site）
    r = _mk_fixture()
    with open(os.path.join(r, "orch.dwf.ts"), "a", encoding="utf-8") as fh:
        fh.write("// judge-producer-site: template-own-judge-leg\n")
    code, out = _run(cmd_judge_unique, r)
    case("双产生点 ⇒ rc=1 拦截", code == 1 and "计数=2" in out, True)
    shutil.rmtree(r)

    # 夹具6 判分相签名（模板相清单混入 judge 相）
    r = _mk_fixture(extra_phase='  { id: "p8-judge-exec", kind: "test" },')
    with open(os.path.join(r, "orch.dwf.ts"), "a", encoding="utf-8") as fh:
        fh.write("// 相 p8-judge-exec 为 v1.0 判分执行员复判相\n")
    code, out = _run(cmd_judge_unique, r)
    case("判分相 id 签名 ⇒ rc=1 拦截", code == 1 and "p8-judge-exec" in out, True)
    shutil.rmtree(r)

    # 夹具7 v10-pre：对实跑镜像树计数复现（6 缺 / 4 表侧异名 / 2 盘侧别名）
    here = os.path.dirname(os.path.abspath(__file__))
    if os.path.isfile(os.path.join(here, "SPEC.md.v1.0.bak")):
        code, out = _run(cmd_v10_pre, here, expect=(6, 4, 2))
        case("v10-pre 台账算术复现（6/4/2）rc=0", code, 0)
    else:
        print("  [SKIP] v10-pre：实跑镜像树不在本夹具环境")

    failed = [c for c in cases if not c[1]]
    print(f"selftest: {len(cases) - len(failed)}/{len(cases)} PASS ⇒ {'rc=0' if not failed else 'rc=1'}")
    sys.exit(0 if not failed else 1)


def main():
    ap = argparse.ArgumentParser(description="D-169 布局对账＋判分产生点唯一性断言")
    ap.add_argument("--root", default=".", help="工件根目录（默认当前目录）")
    ap.add_argument("--json-out", default=None, help="读数 JSON 落盘路径")
    ap.add_argument("check", nargs="?", default="all",
                    choices=["all", "layout", "judge-unique", "v10-pre", "selftest"])
    ap.add_argument("--face", default="full", choices=["run", "full"], help="layout 核对面")
    ap.add_argument("--expect", default=None, help="selftest/断言期望值（v10-pre 用 m,r,a 三数）")
    args = ap.parse_args()
    if args.check == "selftest":
        selftest()
    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        print(f"root 不存在: {root}")
        sys.exit(2)
    if args.check == "layout":
        cmd_layout(root, args.face, args.json_out)
    elif args.check == "judge-unique":
        cmd_judge_unique(root, args.json_out)
    elif args.check == "v10-pre":
        expect = None
        if args.expect:
            parts = tuple(int(x) for x in args.expect.split(","))
            expect = parts
        cmd_v10_pre(root, args.json_out, expect)
    else:  # all = ①(full) ＋ ②；逐条 rc 合成留读数
        import io
        import contextlib
        results = {}
        for name, fn in (("layout", lambda: cmd_layout(root, "full", args.json_out + ".layout.json" if args.json_out else None)),
                         ("judge-unique", lambda: cmd_judge_unique(root, args.json_out + ".judge-unique.json" if args.json_out else None))):
            buf = io.StringIO()
            code = 0
            with contextlib.redirect_stdout(buf):
                try:
                    fn()
                except SystemExit as e:
                    code = e.code if isinstance(e.code, int) else 0
            results[name] = code
            print(buf.getvalue(), end="")
        print(f"all: layout rc={results['layout']} judge-unique rc={results['judge-unique']} ⇒ "
              f"{'rc=0 绿' if all(v == 0 for v in results.values()) else 'rc=1'}")
        sys.exit(0 if all(v == 0 for v in results.values()) else 1)


if __name__ == "__main__":
    main()
