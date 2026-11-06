#!/usr/bin/env python3
"""portal-quote-contract-probe.py — AGENTS quote 契约**服务端强制**功能实测件

为什么要有这件（2026-11-03 RT-E169 部署面对账批）：
  RT-E169 修的是「安全面 AGENTS 契约 quote 条款服务端零强制」——/report 原样落任意
  payload，quote ≤120 字全链无强制。修复形态＝门户服务端在落盘前过一道回报准入门
  （`REPORT_SHAPE_KEYS` 五字段 + `QUOTE_MAX_CHARS` 上限 + `_report_admission_error`）。

  只 `grep` 标记只能证明「代码在文件里」，**证明不了「契约被强制」**；而对账面
  （tools/deploy-consistency-probe.sh）盯的又是在役那一份——两件事必须分开验：
    · 内容面（grep）：在役件含三标记 → 该版本带门
    · 功能面（本件）：**跑在役件自己的门**，正负例实跑 → 该版本真的在拒收

  本件用 ast 只抽取该件自己的 `_report_admission_error` 函数与
  `REPORT_SHAPE_KEYS` / `QUOTE_MAX_CHARS` 两个常量，在隔离命名空间里 exec
  ——**不 import、不启动门户、不触碰在役数据**（exec 的只有那一个函数体与两个
  常量赋值，模块级其它代码一概不跑）。

用法：
    python3 -I tools/portal-quote-contract-probe.py <门户文件路径>
    ssh root@gov-host.invalid 'cat /opt/company/af-jobs/af-jobs-portal.py' \
      | python3 -I tools/portal-quote-contract-probe.py -      # 在役件取回实测

退出码：0=该件**真的强制** AGENTS quote 契约（正负例全过）；
        1=不强制（缺门/门形不对/负例放过/正例误拦）；
        2=前置不满足（件不可读/不可解析）——按红点名，不静默放行。
"""
import ast
import sys

FUNCNAME = "_report_admission_error"
CONSTNAMES = ("REPORT_SHAPE_KEYS", "QUOTE_MAX_CHARS")
MARKERS = ("REPORT_SHAPE_KEYS", "QUOTE_MAX_CHARS", "_report_admission_error")
# AGENTS 契约硬条款值：quote ≤120 字（与门户 REPORT/quote 契约、收割方口径同源）。
# 取值被改宽＝契约被改弱（须红），改严＝偏离契约（同样须人工确认，故一并红）。
CONTRACT_MAX = 120


def fail(msg):
    print("FAIL：" + msg)
    sys.exit(1)


def load_gate(src, name):
    """抽出 FUNCNAME 函数 + CONSTNAMES 常量，隔离 exec；返回 (fn, ns)。"""
    try:
        tree = ast.parse(src, filename=name)
    except SyntaxError as e:
        print("FAIL：门户件不可解析（%s: %s）" % (name, e))
        sys.exit(2)
    picked = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == FUNCNAME:
            picked.append(node)
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id in CONSTNAMES:
                    picked.append(node)
    fn_nodes = [n for n in picked if isinstance(n, ast.FunctionDef)]
    if not fn_nodes:
        fail("该件无 %s()——AGENTS quote 契约服务端零强制（/report 原样落任意 payload）"
             % FUNCNAME)
    ns = {}
    mod = ast.Module(body=picked, type_ignores=[])
    try:
        code = compile(mod, name, "exec")
        exec(code, ns)  # noqa: S102 —— 只 exec 该件自己的那一个函数体与两个常量
    except Exception as e:  # pragma: no cover — 形态异常即不强制
        fail("该件 %s/_report_admission_error 形态异常无法执行（%s: %s）"
             % (name, type(e).__name__, e))
    fn = ns.get(FUNCNAME)
    if not callable(fn):
        fail("该件 %s 取不到可调用对象" % FUNCNAME)
    for c in CONSTNAMES:
        if c not in ns:
            fail("该件缺常量 %s——quote 契约门形态不完整" % c)
    return fn, ns


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 2
    target = argv[1]
    if target == "-":
        src = sys.stdin.buffer.read().decode("utf-8", "replace")
        name = "<stdin>"
    else:
        try:
            with open(target, "r", encoding="utf-8") as f:
                src = f.read()
        except OSError as e:
            print("FAIL：门户件不可读 %s（%s）" % (target, e))
            return 2
        name = target

    missing = [m for m in MARKERS if m not in src]
    if missing:
        fail("该件缺内容标记%s——AGENTS quote 契约门不在位（RT-E169 服务端零强制形态）"
             % "".join("「%s」" % m for m in missing))

    fn, ns = load_gate(src, name)
    limit = ns["QUOTE_MAX_CHARS"]
    keys = tuple(ns["REPORT_SHAPE_KEYS"])
    if not isinstance(limit, int) or limit <= 0:
        fail("QUOTE_MAX_CHARS 取值异常：%r" % (limit,))
    if limit != CONTRACT_MAX:
        fail("QUOTE_MAX_CHARS=%r ≠ AGENTS 契约值 %d 字（契约硬条款被改宽/改严，须人工确认）"
             % (limit, CONTRACT_MAX))
    if not keys:
        fail("REPORT_SHAPE_KEYS 取值异常：%r" % (keys,))

    over = "超" * (limit + 1)          # 比上限多 1 字 → 必须拒
    exact = "恰" * limit                # 恰好上限 → 必须放行
    ok_payload = {"atoms": [{"quote": "短引文"}]}

    # 负例1：payload 非对象 → 必须拒
    if fn("not-a-dict") is None:
        fail("负例放过：payload 非对象未被拒（契约门形不对）")
    # 负例2：quote 超上限 → 必须拒
    e = fn({"atoms": [{"quote": over}]})
    if e is None:
        fail("负例放过：quote %d 字 > %d 上限未被拒（AGENTS quote 契约服务端零强制）"
             % (len(over), limit))
    # 负例3：嵌套深处的 quote 超上限 → 必须拒（递归全树）
    e = fn({"atoms": [{"note": {"quote": over}}]})
    if e is None:
        fail("负例放过：嵌套 quote 超上限未被拒（门未递归全树）")
    # 负例4：不含任何已知 schema 键 → 必须拒
    e = fn({"whatever": [1, 2, 3]})
    if e is None:
        fail("负例放过：无已知回报 schema 键的 payload 未被拒（形不对仍落盘）")
    # 正例1：合规件 → 必须放行（不得误拦正常回报）
    e = fn(ok_payload)
    if e is not None:
        fail("正例误拦：合规 payload 被拒（%s）" % e)
    # 正例2：恰好上限 → 必须放行（边界不多拦）
    e = fn({"atoms": [{"quote": exact}]})
    if e is not None:
        fail("正例误拦：quote 恰好 %d 字被拒（%s）" % (limit, e))
    # 正例3：非字符串 quote（数字）不得误拦
    e = fn({"atoms": [{"quote": 12345}]})
    if e is not None:
        fail("正例误拦：非字符串 quote 被拒（%s）" % e)

    print("PASS：该件强制 AGENTS quote 契约（上限 %d 字，schema 键 %s）——"
          "正例3/负例4 全过，%s() 落盘前准入门实测生效" % (limit, "/".join(keys), FUNCNAME))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
