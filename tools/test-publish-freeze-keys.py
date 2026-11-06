#!/usr/bin/env python3
"""test-publish-freeze-keys.py — 键集冻结在役可达性门（L2 单测件，2026-11-03 publish-sc 批）

确证缺陷（本门由来）：publish-scrub-gate 的「键集冻结」是结构上不可达的**死开关**——
发布路径 tools/factory-status-push.py:_gate_ok 调闸时只带 --json（不带 --freeze-keys），
all-gates 唯一门项是 --selftest（夹具自测，非对实树跑冻结检查）⇒ 治理器
quota-governor 新加字段（如 per-key 明细）直上公网 quota.json，无人拦。
台账 DEB-7 行「键集冻结未受影响」的结论做在一个从未运行过的控制上。

本门三腿（fail-closed，任一腿红即红；无豁免分支）：
  腿1 机制——未审新键必须被 --freeze-keys 拦下（负向夹具）；已审两形（成功态 /
        死态 {"go": false, "error": …}）必须绿（正向夹具）。机制不红=冻结控制失效。
  腿2 可达性——发布路径的闸调用 argv 必须含 --freeze-keys（AST 解析发布脚本的
        subprocess.run 实参列表，不靠注释/字符串匹配）。此腿直接钉住「死开关」不复发。
  腿3 实树——在役发布源 状态观测/quota.json + 状态/看板/data.json 的键集须在冻结集内
        （治理器加字段即红）。这正是映射件 G2 行「闸 hits=[] 且 exit=0」测不出的一面。

退出码：0=三腿全绿；1=有腿红（逐腿点名）。
"""
import ast
import json
import os
import shutil
import subprocess
import sys

WS = os.path.expanduser("~/workspace/agent黑灯工厂")
GATE = os.path.join(WS, "tools/publish-scrub-gate.py")
PUSH = os.path.join(WS, "tools/factory-status-push.py")
QUOTA_SRC = os.path.join(WS, "状态观测/quota.json")
DATA_SRC = os.path.join(WS, "状态/看板/data.json")
WORK = os.path.join(os.path.expanduser("~"), "vgate-work",
                    "freeze-test-%d" % os.getpid())

SUCC_QUOTA = {"ts": 1,
              "step": {"remaining": 1, "total": 2, "used_percent": 50,
                       "expires_at_ms": 1, "seconds_to_expiry": 99, "go": True},
              "minimax": {"go": True}}
ERR_QUOTA = {"ts": 1,
             "step": {"go": False, "error": "读取失败：占位"},
             "minimax": {"go": False, "error": "读取失败：占位"}}
DRIFT_QUOTA = {"ts": 1,
               "step": {"remaining": 1, "total": 2, "used_percent": 50,
                        "expires_at_ms": 1, "seconds_to_expiry": 99, "go": True,
                        "per_key_detail": {"k": 1}},
               "minimax": {"go": True}}
DATA_OK = {"ts": 1, "plan": {"file": "占位/路径.json"}, "alarms": []}
DATA_DRIFT = {"ts": 1, "plan": {"file": "占位/路径.json"}, "alarms": [],
              "extra_unreviewed_key": 1}


def run_gate(tree):
    """跑闸（--freeze-keys --json）→ (rc, 裁决 dict)。"""
    p = subprocess.run([sys.executable, "-I", GATE, tree, "--json", "--freeze-keys"],
                       capture_output=True, text=True, timeout=120)
    try:
        return p.returncode, json.loads(p.stdout)
    except Exception:
        return p.returncode, {"verdict": "unparsable", "stdout": p.stdout[:400],
                              "stderr": p.stderr[-400:]}


def write_tree(dirname, files):
    os.makedirs(dirname, exist_ok=True)
    for name, obj in files.items():
        with open(os.path.join(dirname, name), "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)


def drifts(verdict):
    return [e for e in verdict.get("errors", []) if "键集漂移" in e]


def leg1_mechanism(fails):
    """机制腿：负向夹具（未审新键）必须红；正向两形必须绿。"""
    d = os.path.join(WORK, "mech")
    # 负向①：quota.json 多一个未审键
    write_tree(d, {"quota.json": DRIFT_QUOTA, "data.json": DATA_OK})
    rc, v = run_gate(d)
    if rc == 0 or not drifts(v):
        fails.append(f"腿1 负向夹具失灵：quota.json 未审键未被 --freeze-keys 拦"
                     f"（rc={rc} errors={v.get('errors')}）")
    # 负向②：data.json 多一个未审顶层键
    write_tree(d, {"quota.json": SUCC_QUOTA, "data.json": DATA_DRIFT})
    rc, v = run_gate(d)
    if rc == 0 or not drifts(v):
        fails.append(f"腿1 负向夹具失灵：data.json 未审顶层键未被 --freeze-keys 拦"
                     f"（rc={rc} errors={v.get('errors')}）")
    # 正向①：成功态形状
    write_tree(d, {"quota.json": SUCC_QUOTA, "data.json": DATA_OK})
    rc, v = run_gate(d)
    if rc != 0:
        fails.append(f"腿1 正向夹具误红：成功态形状被 --freeze-keys 拦"
                     f"（rc={rc} errors={v.get('errors')}）")
    # 正向②：死态 error 键形状（quota-governor DEB-7② 已审形状）
    write_tree(d, {"quota.json": ERR_QUOTA, "data.json": DATA_OK})
    rc, v = run_gate(d)
    if rc != 0:
        fails.append(f"腿1 正向夹具误红：死态 error 键形状被 --freeze-keys 拦"
                     f"（rc={rc} errors={v.get('errors')}）")


def leg2_reachability(fails):
    """可达性腿：发布路径的闸调用 argv 必须带 --freeze-keys（AST 解析）。"""
    if not os.path.isfile(PUSH):
        fails.append(f"腿2 不可判：发布脚本不在位 {PUSH}")
        return
    src = open(PUSH, encoding="utf-8").read()
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        fails.append(f"腿2 不可判：发布脚本语法错误 {e}")
        return
    calls = []

    def _val(node):
        """argv 元素值：字符串常量取 .value（源码段会带引号），其余取源码段。"""
        if isinstance(node, ast.Constant):
            return node.value
        return ast.get_source_segment(src, node)

    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "run" and node.args):
            continue
        a0 = node.args[0]
        if not isinstance(a0, ast.List):
            continue
        elts = [_val(e) for e in a0.elts]
        if any(isinstance(e, str) and "GATE" in e for e in elts):
            calls.append(elts)
    if not calls:
        fails.append("腿2 红：发布脚本内找不到对闸（GATE）的 subprocess.run 调用"
                     "——键集冻结接线面消失")
        return
    for elts in calls:
        if "--freeze-keys" not in elts:
            fails.append(f"腿2 红：发布路径的闸调用未带 --freeze-keys（死开关复现）"
                         f"：argv={elts}")


def leg3_live(fails):
    """实树腿：在役发布源的键集须在冻结集内（且整树过闸须绿＝发布路径不会拒发）。"""
    for p in (QUOTA_SRC, DATA_SRC):
        if not os.path.isfile(p):
            fails.append(f"腿3 不可判：在役发布源不在位 {p}")
            return
    d = os.path.join(WORK, "live")
    os.makedirs(d, exist_ok=True)
    for src in (QUOTA_SRC, DATA_SRC):
        shutil.copy2(src, os.path.join(d, os.path.basename(src)))
    rc, v = run_gate(d)
    dl = drifts(v)
    if dl:
        fails.append(f"腿3 红：在役发布源键集漂移（治理器加了未审字段？）{dl}")
    if rc != 0:
        fails.append(f"腿3 红：在役发布源整树过闸非零（发布路径会拒发）"
                     f"（rc={rc} hits={v.get('hits')} errors={v.get('errors')}）")
    if v.get("scanned", 0) < 2:
        fails.append(f"腿3 红：实树扫描件数不足（scanned={v.get('scanned')}）——真空绿")


def main():
    fails = []
    shutil.rmtree(WORK, ignore_errors=True)
    try:
        leg1_mechanism(fails)
        leg2_reachability(fails)
        leg3_live(fails)
    finally:
        shutil.rmtree(WORK, ignore_errors=True)
    if fails:
        print("TEST FAIL（publish-freeze-keys）:")
        for f in fails:
            print(f"  {f}")
        return 1
    print("TEST PASS（publish-freeze-keys）：腿1 机制正反例 / 腿2 发布路径挂 "
          "--freeze-keys（死开关已消除）/ 腿3 在役发布源键集无漂移")
    return 0


if __name__ == "__main__":
    sys.exit(main())
