#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""factory-thresholds.py — 判活阈值共享模块（单源；D-140 / 债本体 D-129，卡面 factory-os#155）

【为什么建本模块】
  同一判活阈值两处硬编码：tools/factory-watch.py 的 SCHED_STALE_S（状态文件 mtime
  超此值 → A0）与 tools/factory-keepalive.py LOCAL_GUARDS scheduler 项的 stale_s
  （状态/日志双信号 OR 判活）——watch 原注释自认「两个监督面共用一套世界模型」，
  但值各自维护（债证 30-工件/技术债清册-20261107.md:158）。口径演变（DEB57-A0
  2026-11-02 由 300 改 2400）若只改一处，另一处静默失配 ⇒ 阈值偏小=假红抖动、
  阈值偏大=漏报，两个监督面对同一世界给出相反结论。本模块把该族阈值收为单源：
  两监督面 import 本模块取值；recon 闸实读对拍、禁再硬编码（铁律4·D-129）。

【值族（P1：只搬迁不改写——数值与语义=仓内两件现势实读，禁借收编之机调值）】
  SCHED_STALE_S        2400  ← tools/factory-watch.py:129（原字面硬编码；A0 判活线）
  LOCAL_GUARDS_STALE_S 2400  ← tools/factory-keepalive.py:365（scheduler 项 stale_s）
  LOCAL_GUARDS_GRACE_S 1800  ← tools/factory-keepalive.py:365（scheduler 项 grace_s）
  ARCHIVE_MATURITY_S   21600 ← tools/factory-watch.py:139（ARCHIVE_MATURITY_S = 6*3600）
  SCHED_STALE_S 与 LOCAL_GUARDS_STALE_S 必须同值（双消费面对等，selftest 断言）——
  它们是同一判活线（factory-scheduler 状态文件 mtime 新鲜度）在两个监督面上的投影。

【卡面值记述勘误（如实记录，2026-11-08 实读）】卡面 factory-os#155 与债证
  （30-工件/技术债清册-20261107.md:158）记述 ARCHIVE_MATURITY_S=7200；仓内现势实读
  为 6*3600=21600（tools/factory-watch.py:139，建仓即此值，git log -L 实证；工作区
  部署副本 :126 同值；watch.py:2199 自注「自然退役：>6h」——6h=21600s 语义自洽）。
  P1「值=仓内两件现势实读搬迁、禁借收编之机调任何阈值」⇒ 本模块登记现势实读值
  **21600**：登记 7200 要么使模块与仓内件失配（recon 假红、验收命令 5 必红），要么
  要求改 watch.py 数值（P1 禁项）。7200→21600 的口径疑归校准全文与运营者裁（本卡不裁）。

【校准演变注（随值单源搬迁，勿在两消费面各自维护）】
  DEB57-A0 2026-11-02 由 300 改 2400：现役 factory-scheduler 单轮含 anolis/gov
  多路 ssh，实测 round 间隔 p99=784s / max=1258s、7.4% 轮次 >300s（近 3 天 119
  轮）——300 阈必假红抖动；2400 与 keepalive scheduler 判活线同值。此后改阈值
  只改本模块一处，两监督面随之同改，recon 闸守对等。

【recon 闸判据（三态；rc 口径与仓内对账门同款）】
  实读相等 + 两件均模块取值（禁再硬编码）             ⇒ rc=0
  收编对（SCHED_STALE_S / scheduler stale_s+grace_s）再出现字面硬编码，
    或实读值 ≠ 模块值（静默失配）                     ⇒ rc=1，点名坐标
  不可证（消费件缺席 / 语法坏 / 装载失败 / 判活项不可定位 / 取值来源形态不可证）
                                                    ⇒ rc=2 fail-loud，逐条点名，
    不猜绿、不用 SKIP 冒充。rc=2 优先于 rc=1：读不出就没有比对可言。

  禁再硬编码的机检面（与卡面验收命令 2/4 同 patterns，recon 为其超集）：
    · tools/factory-watch.py      禁再现 `SCHED_STALE_S = 2400` 字面（注释亦计——
      旧值的文档化记述迁至本模块 docstring，消费面只留取值来源指针）；
    · tools/factory-keepalive.py  禁再现 `"stale_s": 2400` / `stale_s=2400` 字面。
  另 AST 判「取值来源」：收编对的赋值/字典值必须是模块溯源（Name/Attribute 经
  spec_from_file_location→module_from_spec 链解析到本模块常量），字面即红。

  未收编登记（透明对账，不判红）：仓内两件仍内联的判活语境族值字面（2400/3600/7200；
  口径=模块级常量赋值 + stale_s/grace_s 字典项，docstring/注释/其他算术位不计）
  列册供后续卡收敛——本卡只收编 2400 判活对（P3：
  diff 只许「换取值来源」）；新阈入模块须同批 recon 更新。

【纪律】零网络；只读被检件；唯一写面 = `--out` 显式指定的落盘件与 `--selftest`
  的临时目录（用后即清）；判据 / 判官件 / 在飞工作流零改动；厂内工作区 tools/
  部署副本不在本模块判据内（P2：禁改在役跑件，仓内件与部署副本已分叉）。

用法：
  python3 -I tools/factory-thresholds.py --recon [--watch PATH] [--keepalive PATH]
                                          [--out PATH]
  python3 -I tools/factory-thresholds.py --selftest
退出码：0 = 单源对等零漂移；1 = 再硬编码 / 失配（点名）；2 = 不可证（fail-loud）。
"""
import argparse
import ast
import importlib.util
import json
import os
import shutil
import sys
import tempfile

SCHEMA = "af.factory-thresholds.recon.v1"

MODULE_BASENAME = "factory-thresholds.py"
MODULE_STEM = "factory-thresholds"
MODULE_NAME = "factory_thresholds"

WATCH_BASENAME = "factory-watch.py"
KEEPALIVE_BASENAME = "factory-keepalive.py"

RC_OK = 0
RC_DRIFT = 1
RC_UNPROVABLE = 2

# 族值面（未收编登记扫描用；判活语境族值，非本模块导出全集）
FAMILY_LITERALS = (2400, 3600, 7200)

# ---- 值族（单源正本；值=仓内两件现势实读搬迁，P1 禁借收编调值）------------------
SCHED_STALE_S = 2400
LOCAL_GUARDS_STALE_S = 2400
LOCAL_GUARDS_GRACE_S = 1800
ARCHIVE_MATURITY_S = 6 * 3600        # 21600；仓内现势实读（factory-watch.py:139），
                                     # 卡面/债证 7200 记述为勘误项（见 docstring 勘误段）

# 机读族（校准全文余量推导用）：常量名 → (现势值, 仓内源坐标, 语义)
THRESHOLDS = {
    "SCHED_STALE_S": (SCHED_STALE_S, "tools/factory-watch.py:129",
                      "scheduler 状态文件 mtime 超此值 → A0（watch 判活线）"),
    "LOCAL_GUARDS_STALE_S": (LOCAL_GUARDS_STALE_S, "tools/factory-keepalive.py:365",
                             "LOCAL_GUARDS scheduler 项 stale_s（双信号 OR 判活）"),
    "LOCAL_GUARDS_GRACE_S": (LOCAL_GUARDS_GRACE_S, "tools/factory-keepalive.py:365",
                             "LOCAL_GUARDS scheduler 项 grace_s（拉起宽限）"),
    "ARCHIVE_MATURITY_S": (ARCHIVE_MATURITY_S, "tools/factory-watch.py:139",
                           "results.jsonl mtime 超此龄且无关联在跑进程 → 臂归档（A1/A2 免报）"),
}

CONST_NAMES = tuple(THRESHOLDS)

# 收编对（本卡唯一改动面：两处 2400 判活硬编码 → 模块取值；禁再硬编码的对象）
#   face → (文件 basename, 检查项, 期望常量名, 仓内源坐标)
COLLECTED = {
    "watch": (WATCH_BASENAME, "SCHED_STALE_S", "SCHED_STALE_S",
              "tools/factory-watch.py:129"),
    "keepalive": (KEEPALIVE_BASENAME, "scheduler.stale_s", "LOCAL_GUARDS_STALE_S",
                  "tools/factory-keepalive.py:365"),
    "keepalive_grace": (KEEPALIVE_BASENAME, "scheduler.grace_s", "LOCAL_GUARDS_GRACE_S",
                        "tools/factory-keepalive.py:365"),
}

# 对拍项（实读相等；不要求模块取值——ARCHIVE_MATURITY_S 本卡仅登记对拍，P3 范围外）
CROSSCHECK = (
    ("watch", "SCHED_STALE_S", "SCHED_STALE_S", True),
    ("keepalive", "scheduler.stale_s", "LOCAL_GUARDS_STALE_S", True),
    ("keepalive", "scheduler.grace_s", "LOCAL_GUARDS_GRACE_S", True),
    ("watch", "ARCHIVE_MATURITY_S", "ARCHIVE_MATURITY_S", False),
)


# ---------------------------------------------------------------------------
# 取值来源解析（AST）：模块溯源 / 字面 / 不可证
# ---------------------------------------------------------------------------
class SourceContext:
    """模块级语境：spec 名 → 模块对象名 → 常量别名名 的溯源链。"""

    def __init__(self, tree):
        self.spec_names = set()      # 由 spec_from_file_location(..., "factory-thresholds...") 赋值
        self.module_names = set()    # 由 module_from_spec(<spec 名>) 赋值
        self.alias = {}              # 别名 → 常量名（如 LOCAL_GUARDS_STALE_S = _ft.LOCAL_GUARDS_STALE_S）
        self._scan(tree)

    def _is_module_path_const(self, node):
        for sub in ast.walk(node):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                if MODULE_BASENAME in sub.value or MODULE_STEM in sub.value \
                        or MODULE_NAME in sub.value:
                    return True
        return False

    def _scan(self, tree):
        for node in tree.body:
            targets = []
            if isinstance(node, ast.Assign):
                targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
                value = node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) \
                    and node.value is not None:
                targets = [node.target.id]
                value = node.value
            else:
                continue
            if not isinstance(value, ast.Call):
                continue
            func = value.func
            fname = func.attr if isinstance(func, ast.Attribute) else (
                func.id if isinstance(func, ast.Name) else "")
            if fname == "spec_from_file_location" and self._is_module_path_const(value):
                for t in targets:
                    self.spec_names.add(t)
            elif fname == "module_from_spec":
                args = [a.id for a in value.args if isinstance(a, ast.Name)]
                if any(a in self.spec_names for a in args):
                    for t in targets:
                        self.module_names.add(t)
            elif fname in ("import_module",):
                for a in value.args:
                    if isinstance(a, ast.Constant) and isinstance(a.value, str) \
                            and MODULE_STEM in a.value:
                        for t in targets:
                            self.module_names.add(t)
        # 第二遍：常量别名（依赖 module_names 已齐）
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            for t in node.targets:
                if not isinstance(t, ast.Name):
                    continue
                res = self.resolve(node.value)
                if res[0] == "module":
                    self.alias[t.id] = res[1]

    def resolve(self, node):
        """解析取值节点 → (kind, detail)。
        kind: module（模块溯源，detail=常量名）/ literal（字面，detail=值）/
              unknown（形态不可证）。
        """
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
                and node.value.id in self.module_names:
            return ("module", node.attr)
        if isinstance(node, ast.Name) and node.id in self.alias:
            return ("module", self.alias[node.id])
        if isinstance(node, ast.Name) and node.id in self.module_names:
            return ("unknown", "模块对象本身非常量")
        ok, val = _int_literal(node)
        if ok:
            return ("literal", val)
        return ("unknown", "非字面且非模块溯源形态")


def _int_literal(node):
    """整数常量表达式求值（字面 / 一元 / 整型 BinOp 如 6*3600）。
    ast.literal_eval 不放行 Mult（只放行复数加减），故自备整数子集求值器；
    非整数子集 ⇒ (False, None)（交由调用方按 unknown 处理，fail-loud 不猜）。
    """
    if isinstance(node, ast.Constant):
        return (isinstance(node.value, int) and not isinstance(node.value, bool),
                node.value if isinstance(node.value, int)
                and not isinstance(node.value, bool) else None)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        ok, v = _int_literal(node.operand)
        if not ok:
            return False, None
        return True, (+v if isinstance(node.op, ast.UAdd) else -v)
    if isinstance(node, ast.BinOp) and isinstance(
            node.op, (ast.Add, ast.Sub, ast.Mult, ast.FloorDiv, ast.Mod)):
        okl, l = _int_literal(node.left)
        okr, r = _int_literal(node.right)
        if not (okl and okr):
            return False, None
        try:
            if isinstance(node.op, ast.Add):
                return True, l + r
            if isinstance(node.op, ast.Sub):
                return True, l - r
            if isinstance(node.op, ast.Mult):
                return True, l * r
            if isinstance(node.op, ast.FloorDiv):
                return True, l // r
            return True, l % r
        except ZeroDivisionError:
            return False, None
    return False, None


# ---------------------------------------------------------------------------
# 读取与对拍
# ---------------------------------------------------------------------------
def _default_path(basename):
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), basename)


def _parse(path):
    """读+解析被检件；失败抛 RuntimeError（调用方转 rc=2 点名）。"""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError as exc:
        raise RuntimeError("读取失败 %s: %s" % (path, exc))
    try:
        return text, ast.parse(text, filename=path)
    except SyntaxError as exc:
        raise RuntimeError("语法坏 %s:%s: %s" % (path, exc.lineno, exc.msg))


def _load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("装载 spec 失败 %s" % path)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as exc:               # 接线断裂（ImportError/AttributeError/...）
        raise RuntimeError("装载执行失败 %s: %s: %s" % (path, type(exc).__name__, exc))
    return mod


def _watch_assignment(tree, name):
    """watch 面模块级赋值节点（SCHED_STALE_S 等）；无则 None。"""
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    return node
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) \
                and node.target.id == name and node.value is not None:
            return node
    return None


def _keepalive_scheduler_item(mod, tree):
    """keepalive 面 LOCAL_GUARDS 中 name=scheduler 的字典项（AST 节点 + 运行时值）。"""
    guards = getattr(mod, "LOCAL_GUARDS", None)
    if not isinstance(guards, list):
        raise RuntimeError("factory-keepalive.py 无 LOCAL_GUARDS 列表——判活清单不可定位")
    rt = None
    for g in guards:
        if isinstance(g, dict) and g.get("name") == "scheduler":
            rt = g
            break
    if rt is None:
        raise RuntimeError("factory-keepalive.py LOCAL_GUARDS 无 name=scheduler 项——判活项不可定位")
    # AST 定位同项（行号对账用）：列表里第一个含 "name": "scheduler" 的 Dict
    ast_item, ast_line = None, None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        keys = [k.value for k in node.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)]
        if "name" not in keys or "stale_s" not in keys:
            continue
        name_val = None
        for k, v in zip(node.keys, node.values):
            if isinstance(k, ast.Constant) and k.value == "name":
                if isinstance(v, ast.Constant) and v.value == "scheduler":
                    name_val = v.value
        if name_val == "scheduler":
            ast_item, ast_line = node, node.lineno
            break
    if ast_item is None:
        raise RuntimeError("factory-keepalive.py scheduler 判活项 AST 不可定位（:365 同构项缺席）")
    return rt, ast_item, ast_line


def _dict_value_node(dict_node, key):
    for k, v in zip(dict_node.keys, dict_node.values):
        if isinstance(k, ast.Constant) and k.value == key:
            return v
    return None


def _display_path(path):
    """坐标展示规范化：仓内两消费件 → tools/<basename>；覆写路径照原样。"""
    base = os.path.basename(path)
    if base in (WATCH_BASENAME, KEEPALIVE_BASENAME):
        return "tools/%s" % base
    return path


def _family_literals(display, text, tree):
    """未收编登记：判活语境族值字面（2400/3600/7200）代码位。
    口径=两类真阈位——① 模块级常量赋值（NAME = <整型表达式>）；
    ② 字典 stale_s/grace_s 项（LOCAL_GUARDS 家族同构）。docstring/注释/其他
    算术位不计（非阈值语境，列入即噪声）。不判红，供后续卡收敛对账。
    """
    out = []
    lines = text.splitlines()

    def scan(value_node, ctx):
        for sub in ast.walk(value_node):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, int) \
                    and not isinstance(sub.value, bool) and sub.value in FAMILY_LITERALS:
                ln = sub.lineno
                src = lines[ln - 1].strip() if 0 < ln <= len(lines) else ""
                out.append({"file": display, "line": ln, "value": sub.value,
                            "ctx": ctx, "src": src[:80]})

    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if names:
                scan(node.value, " = ".join(names))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) \
                and node.value is not None:
            scan(node.value, node.target.id)
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value in ("stale_s", "grace_s"):
                    scan(v, "dict %s" % k.value)
    seen, uniq = set(), []
    for e in out:
        key = (e["file"], e["line"], e["value"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(e)
    uniq.sort(key=lambda e: (e["file"], e["line"]))
    return uniq


def check(watch_path=None, keepalive_path=None):
    """recon 主判：实读两件阈值 == 模块值 + 禁再硬编码。返回 (rc, reading)。"""
    watch_path = watch_path or _default_path(WATCH_BASENAME)
    keepalive_path = keepalive_path or _default_path(KEEPALIVE_BASENAME)
    reading = {
        "schema": SCHEMA,
        "module": {k: v[0] for k, v in THRESHOLDS.items()},
        "watch_path": watch_path,
        "keepalive_path": keepalive_path,
        "items": [],
        "raw_text_violations": [],
        "uncollected_literals": [],
        "reds": [],
    }
    rc = RC_OK

    def red(kind, coord, detail):
        reading["reds"].append({"kind": kind, "coord": coord, "detail": detail})

    # ---- 0. 原始字面负例（与卡面验收命令 2/4 同 patterns；注释亦计）--------------
    raw_patterns = (
        (watch_path, "watch 禁再现 SCHED_STALE_S = 2400 字面",
         "SCHED_STALE_S = 2400"),
        (keepalive_path, "keepalive 禁再现 \"stale_s\": 2400 字面",
         '"stale_s": 2400'),
        (keepalive_path, "keepalive 禁再现 stale_s=2400 字面",
         "stale_s=2400"),
    )
    try:
        watch_text, watch_tree = _parse(watch_path)
        keep_text, keep_tree = _parse(keepalive_path)
    except RuntimeError as exc:
        red("不可证", str(exc).split(":")[0], str(exc))
        reading["rc"] = RC_UNPROVABLE
        return RC_UNPROVABLE, reading
    for path, kind, needle in raw_patterns:
        text = watch_text if path == watch_path else keep_text
        for i, ln in enumerate(text.splitlines(), 1):
            if needle in ln:
                entry = {"coord": "%s:%d" % (_display_path(path), i), "kind": kind,
                         "src": ln.strip()[:80]}
                reading["raw_text_violations"].append(entry)
                red("再硬编码", entry["coord"],
                    "%s（原始字面负例，验收命令同 patterns）: %s" % (kind, entry["src"]))
                if rc != RC_UNPROVABLE:
                    rc = RC_DRIFT

    # ---- 1. 动态装载两消费面（实读；接线断裂即不可证）---------------------------
    try:
        watch_mod = _load_module(watch_path, "factory_watch_under_recon")
    except RuntimeError as exc:
        red("不可证", "tools/factory-watch.py", str(exc))
        reading["rc"] = RC_UNPROVABLE
        return RC_UNPROVABLE, reading
    try:
        keep_mod = _load_module(keepalive_path, "factory_keepalive_under_recon")
    except RuntimeError as exc:
        red("不可证", "tools/factory-keepalive.py", str(exc))
        reading["rc"] = RC_UNPROVABLE
        return RC_UNPROVABLE, reading

    watch_ctx = SourceContext(watch_tree)
    keep_ctx = SourceContext(keep_tree)

    # ---- 2. 逐项对拍 ------------------------------------------------------------
    values = {}

    # watch 面：SCHED_STALE_S（收编对，须模块取值）+ ARCHIVE_MATURITY_S（仅对拍）
    assign = _watch_assignment(watch_tree, "SCHED_STALE_S")
    if assign is None:
        red("不可证", "tools/factory-watch.py",
            "无 SCHED_STALE_S 模块级赋值——取值来源不可定位")
        rc = RC_UNPROVABLE
    else:
        kind, detail = watch_ctx.resolve(assign.value)
        rt_val = getattr(watch_mod, "SCHED_STALE_S", None)
        values["watch.SCHED_STALE_S"] = rt_val
        if kind == "literal":
            red("再硬编码", "tools/factory-watch.py:%d" % assign.lineno,
                "SCHED_STALE_S 仍为字面硬编码 %s——未走单源（D-140 收编对）" % detail)
            rc = RC_DRIFT if rc != RC_UNPROVABLE else rc
        elif kind == "unknown":
            red("不可证", "tools/factory-watch.py:%d" % assign.lineno,
                "SCHED_STALE_S 取值来源不可证：%s" % detail)
            rc = RC_UNPROVABLE
        if not isinstance(rt_val, int) or isinstance(rt_val, bool):
            red("不可证", "tools/factory-watch.py:%d" % assign.lineno,
                "SCHED_STALE_S 运行值非整数：%r" % (rt_val,))
            rc = RC_UNPROVABLE
        elif rt_val != SCHED_STALE_S:
            red("失配", "tools/factory-watch.py:%d" % assign.lineno,
                "SCHED_STALE_S 实读 %d ≠ 模块 %d——两监督面静默失配（假红/漏报形态）"
                % (rt_val, SCHED_STALE_S))
            rc = RC_DRIFT if rc != RC_UNPROVABLE else rc
        reading["items"].append({
            "face": "watch", "item": "SCHED_STALE_S", "value": rt_val,
            "source": kind, "const": detail if kind == "module" else None,
            "module_value": SCHED_STALE_S,
            "coord": "tools/factory-watch.py:%d" % assign.lineno,
            "src_coord": THRESHOLDS["SCHED_STALE_S"][1],
        })

    assign = _watch_assignment(watch_tree, "ARCHIVE_MATURITY_S")
    if assign is None:
        red("不可证", "tools/factory-watch.py",
            "无 ARCHIVE_MATURITY_S 模块级赋值——对拍项不可定位")
        rc = RC_UNPROVABLE
    else:
        rt_val = getattr(watch_mod, "ARCHIVE_MATURITY_S", None)
        values["watch.ARCHIVE_MATURITY_S"] = rt_val
        kind, detail = watch_ctx.resolve(assign.value)
        if not isinstance(rt_val, int) or isinstance(rt_val, bool):
            red("不可证", "tools/factory-watch.py:%d" % assign.lineno,
                "ARCHIVE_MATURITY_S 运行值非整数：%r" % (rt_val,))
            rc = RC_UNPROVABLE
        elif rt_val != ARCHIVE_MATURITY_S:
            red("失配", "tools/factory-watch.py:%d" % assign.lineno,
                "ARCHIVE_MATURITY_S 实读 %d ≠ 模块 %d——族值失配" % (rt_val, ARCHIVE_MATURITY_S))
            rc = RC_DRIFT if rc != RC_UNPROVABLE else rc
        reading["items"].append({
            "face": "watch", "item": "ARCHIVE_MATURITY_S", "value": rt_val,
            "source": kind, "const": detail if kind == "module" else None,
            "module_value": ARCHIVE_MATURITY_S,
            "coord": "tools/factory-watch.py:%d" % assign.lineno,
            "src_coord": THRESHOLDS["ARCHIVE_MATURITY_S"][1],
            "note": "本卡仅登记对拍（P3 不收编内联 6*3600）；取值来源=%s" % kind,
        })

    # keepalive 面：scheduler 项 stale_s/grace_s（收编对，须模块取值）
    try:
        sched_rt, sched_ast, sched_line = _keepalive_scheduler_item(keep_mod, keep_tree)
    except RuntimeError as exc:
        red("不可证", "tools/factory-keepalive.py:365", str(exc))
        reading["rc"] = RC_UNPROVABLE
        return RC_UNPROVABLE, reading
    for key, const, label in (("stale_s", "LOCAL_GUARDS_STALE_S", "scheduler.stale_s"),
                              ("grace_s", "LOCAL_GUARDS_GRACE_S", "scheduler.grace_s")):
        node = _dict_value_node(sched_ast, key)
        if node is None:
            red("不可证", "tools/factory-keepalive.py:%d" % sched_line,
                "scheduler 项无 %s 键——判活项结构变异" % key)
            rc = RC_UNPROVABLE
            continue
        kind, detail = keep_ctx.resolve(node)
        rt_val = sched_rt.get(key)
        values["keepalive." + label] = rt_val
        if kind == "literal":
            red("再硬编码", "tools/factory-keepalive.py:%d" % node.lineno,
                "%s 仍为字面硬编码 %s——未走单源（D-140 收编对）" % (label, detail))
            rc = RC_DRIFT if rc != RC_UNPROVABLE else rc
        elif kind == "unknown":
            red("不可证", "tools/factory-keepalive.py:%d" % node.lineno,
                "%s 取值来源不可证：%s" % (label, detail))
            rc = RC_UNPROVABLE
        if not isinstance(rt_val, int) or isinstance(rt_val, bool):
            red("不可证", "tools/factory-keepalive.py:%d" % node.lineno,
                "%s 运行值非整数：%r" % (label, rt_val))
            rc = RC_UNPROVABLE
        elif rt_val != THRESHOLDS[const][0]:
            red("失配", "tools/factory-keepalive.py:%d" % node.lineno,
                "%s 实读 %d ≠ 模块 %d（%s）——两监督面静默失配（假红/漏报形态）"
                % (label, rt_val, THRESHOLDS[const][0], const))
            rc = RC_DRIFT if rc != RC_UNPROVABLE else rc
        reading["items"].append({
            "face": "keepalive", "item": label, "value": rt_val,
            "source": kind, "const": detail if kind == "module" else None,
            "module_value": THRESHOLDS[const][0],
            "coord": "tools/factory-keepalive.py:%d" % node.lineno,
            "src_coord": THRESHOLDS[const][1],
        })

    # ---- 3. 双消费面对等（同一判活线两投影同值）---------------------------------
    a, b = values.get("watch.SCHED_STALE_S"), values.get("keepalive.scheduler.stale_s")
    reading["dual_face_equal"] = (a == b) if (a is not None and b is not None) else None
    if reading["dual_face_equal"] is False:
        red("失配", "tools/factory-watch.py ↔ tools/factory-keepalive.py:365",
            "双监督面判活线不等：watch SCHED_STALE_S=%r vs keepalive scheduler stale_s=%r"
            % (a, b))
        rc = RC_DRIFT if rc != RC_UNPROVABLE else rc

    # ---- 4. 未收编登记（透明对账，不判红）--------------------------------------
    reading["uncollected_literals"] = (
        _family_literals(_display_path(watch_path), watch_text, watch_tree)
        + _family_literals(_display_path(keepalive_path), keep_text, keep_tree))

    reading["rc"] = rc
    return rc, reading


def report(rc, reading):
    lines = ["[recon] 判活阈值单源对拍（D-140；模块 tools/factory-thresholds.py）"]
    for it in reading["items"]:
        flag = "OK" if (it["value"] == it["module_value"]
                        and it["source"] in ("module", "literal")) else "RED"
        src = "模块取值" if it["source"] == "module" else (
            "字面 %s" % it["value"] if it["source"] == "literal" else "来源不可证")
        lines.append("  [%s] %s %s = %s（%s；模块 %s；坐标 %s）"
                     % (flag, it["face"], it["item"], it["value"], src,
                        it["module_value"], it["coord"]))
        if it.get("note"):
            lines.append("       注：%s" % it["note"])
    if reading.get("dual_face_equal") is not None:
        lines.append("  [%s] 双消费面对等（watch SCHED_STALE_S == keepalive scheduler stale_s）：%s"
                     % ("OK" if reading["dual_face_equal"] else "RED",
                        reading["dual_face_equal"]))
    if reading["uncollected_literals"]:
        lines.append("  [INFO] 未收编登记（族值字面代码位，供后续卡收敛；不判红）：")
        for e in reading["uncollected_literals"]:
            lines.append("        %s:%d %s = %d ｜ %s"
                         % (e["file"], e["line"], e["ctx"], e["value"], e["src"]))
    for r in reading["reds"]:
        lines.append("  [RED·%s] %s：%s" % (r["kind"], r["coord"], r["detail"]))
    verdict = {RC_OK: "单源对等零漂移", RC_DRIFT: "再硬编码/失配", RC_UNPROVABLE: "不可证"}[rc]
    lines.append("verdict: rc=%d %s（对拍 %d 项；红项 %d；未收编登记 %d 处）"
                 % (rc, verdict, len(reading["items"]), len(reading["reds"]),
                    len(reading["uncollected_literals"])))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# selftest：内嵌夹具（值族自含 / 现势值钉 / 双面对等 / recon 判别力负控），
#   零网络、零仓内写入（临时目录用后即清）。
# ---------------------------------------------------------------------------
ST_FAILS = []


def expect(name, cond, detail=""):
    print("  [%s] %s%s" % ("PASS" if cond else "FAIL", name,
                           ("  " + detail) if detail else ""), flush=True)
    if not cond:
        ST_FAILS.append(name)


# 夹具：OK 态 watch（模块溯源 + ARCHIVE 内联 6*3600 对拍）
FIX_WATCH_OK = '''\
import importlib.util
import os

_spec = importlib.util.spec_from_file_location(
    "factory_thresholds",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "factory-thresholds.py"))
_ft = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ft)
SCHED_STALE_S = _ft.SCHED_STALE_S
ARCHIVE_MATURITY_S = 6 * 3600
'''

# 夹具：OK 态 keepalive（scheduler 项引模块常量；router 项留 3600 字面作未收编登记）
FIX_KEEPALIVE_OK = '''\
import importlib.util
import os

_spec = importlib.util.spec_from_file_location(
    "factory_thresholds",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "factory-thresholds.py"))
_ft = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ft)
LOCAL_GUARDS_STALE_S = _ft.LOCAL_GUARDS_STALE_S
LOCAL_GUARDS_GRACE_S = _ft.LOCAL_GUARDS_GRACE_S
LOCAL_GUARDS = [
    {"name": "router", "stale_s": 3600, "grace_s": 1800},
    {"name": "scheduler", "stale_s": LOCAL_GUARDS_STALE_S, "grace_s": LOCAL_GUARDS_GRACE_S},
]
'''

# 负控 A：watch 再硬编码（字面 2400）
FIX_WATCH_TAMPER_LITERAL = '''\
SCHED_STALE_S = 2400
ARCHIVE_MATURITY_S = 6 * 3600
'''

# 负控 B：watch 模块溯源但常量名错（接线断裂 → 装载失败 → 不可证）
FIX_WATCH_TAMPER_WIRING = '''\
import importlib.util
import os

_spec = importlib.util.spec_from_file_location(
    "factory_thresholds",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "factory-thresholds.py"))
_ft = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ft)
SCHED_STALE_S = _ft.SCHED_STALE_S_TYPO
ARCHIVE_MATURITY_S = 6 * 3600
'''

# 负控 C：watch 取值来源形态不可证（非字面非模块溯源）
FIX_WATCH_TAMPER_FORM = '''\
SCHED_STALE_S = int("2400")
ARCHIVE_MATURITY_S = 6 * 3600
'''

# 负控 D：keepalive scheduler 项值失配 + 再硬编码（字面 300）
FIX_KEEPALIVE_TAMPER_VALUE = '''\
LOCAL_GUARDS = [
    {"name": "scheduler", "stale_s": 300, "grace_s": 1800},
]
'''

# 负控 E：keepalive 无 scheduler 项（判活项不可定位）
FIX_KEEPALIVE_TAMPER_MISSING = '''\
LOCAL_GUARDS = [
    {"name": "router", "stale_s": 3600, "grace_s": 1800},
]
'''


def _write_fixture_dir(tmp, watch_src, keepalive_src, with_module=True):
    tools = os.path.join(tmp, "tools")
    os.makedirs(tools, exist_ok=True)
    if with_module:
        with open(os.path.join(tools, MODULE_BASENAME), "w", encoding="utf-8") as f:
            with open(os.path.abspath(__file__), encoding="utf-8") as me:
                f.write(me.read())
    if watch_src is not None:
        with open(os.path.join(tools, WATCH_BASENAME), "w", encoding="utf-8") as f:
            f.write(watch_src)
    if keepalive_src is not None:
        with open(os.path.join(tools, KEEPALIVE_BASENAME), "w", encoding="utf-8") as f:
            f.write(keepalive_src)
    return (os.path.join(tools, WATCH_BASENAME), os.path.join(tools, KEEPALIVE_BASENAME))


def selftest():
    print("factory-thresholds.py --selftest（D-140；零网络、零仓内写入）", flush=True)

    # ---- F1 值族自含 ----------------------------------------------------------
    expect("F1a 值族四常量齐备且为正整数",
           all(isinstance(getattr(sys.modules[__name__], n, None), int)
               and not isinstance(getattr(sys.modules[__name__], n, None), bool)
               and getattr(sys.modules[__name__], n, None) > 0 for n in CONST_NAMES),
           ",".join(CONST_NAMES))
    expect("F1b THRESHOLDS 机读族与模块属性逐项一致",
           all(THRESHOLDS[n][0] == globals()[n] for n in CONST_NAMES)
           and set(THRESHOLDS) == set(CONST_NAMES))
    expect("F1c 机读族每项带仓内源坐标与语义",
           all(len(v) == 3 and v[1].startswith("tools/") and v[2] for v in THRESHOLDS.values()))

    # ---- F2 现势值钉断言（P1：值=仓内两件现势实读，禁借收编调值）--------------
    expect("F2a SCHED_STALE_S 现势值 2400（factory-watch.py:129 实读搬迁）",
           SCHED_STALE_S == 2400)
    expect("F2b LOCAL_GUARDS_STALE_S 现势值 2400（factory-keepalive.py:365 实读搬迁）",
           LOCAL_GUARDS_STALE_S == 2400)
    expect("F2c LOCAL_GUARDS_GRACE_S 现势值 1800（factory-keepalive.py:365 实读搬迁）",
           LOCAL_GUARDS_GRACE_S == 1800)
    expect("F2d ARCHIVE_MATURITY_S 现势值 21600（factory-watch.py:139 6*3600 实读搬迁）",
           ARCHIVE_MATURITY_S == 6 * 3600 == 21600,
           "卡面/债证 7200 记述为勘误项——P1 现势实读优先（见 docstring 勘误段）")
    expect("F2e 现势值钉：2400 判活对两处同值、1800/21600 随沿",
           (SCHED_STALE_S, LOCAL_GUARDS_STALE_S, LOCAL_GUARDS_GRACE_S, ARCHIVE_MATURITY_S)
           == (2400, 2400, 1800, 21600))

    # ---- F3 双消费面对等 ------------------------------------------------------
    expect("F3a 双监督面判活线同值（watch SCHED_STALE_S == keepalive scheduler stale_s）",
           SCHED_STALE_S == LOCAL_GUARDS_STALE_S,
           "%d == %d" % (SCHED_STALE_S, LOCAL_GUARDS_STALE_S))
    expect("F3b 收编对三常量均在机读族内",
           all(COLLECTED[f][2] in THRESHOLDS for f in COLLECTED))

    # ---- F4 recon 判别力（内嵌夹具，负控逐态）----------------------------------
    tmp = tempfile.mkdtemp(prefix="factory-thresholds-selftest-")
    try:
        wp, kp = _write_fixture_dir(tmp, FIX_WATCH_OK, FIX_KEEPALIVE_OK)
        rc, rd = check(wp, kp)
        expect("F4a OK 态夹具 recon rc=0", rc == RC_OK, report(rc, rd).splitlines()[-1])
        expect("F4b OK 态双面对等读数 True", rd.get("dual_face_equal") is True)
        expect("F4c OK 态四项对拍全 module/literal 且值相等",
               len(rd["items"]) == 4 and all(
                   it["value"] == it["module_value"] and it["source"] in ("module", "literal")
                   for it in rd["items"]),
               "；".join("%s=%s/%s" % (it["item"], it["source"], it["value"])
                         for it in rd["items"]))
        expect("F4d OK 态未收编登记含 router 3600（透明对账在册）",
               any(e["value"] == 3600 for e in rd["uncollected_literals"]),
               "%d 处" % len(rd["uncollected_literals"]))

        wp, kp = _write_fixture_dir(tmp, FIX_WATCH_TAMPER_LITERAL, FIX_KEEPALIVE_OK)
        rc, rd = check(wp, kp)
        expect("F4e 负控·watch 再硬编码 2400 ⇒ rc=1", rc == RC_DRIFT)
        expect("F4f 负控·点名坐标在 watch SCHED_STALE_S 赋值行",
               any(r["kind"] == "再硬编码" and "SCHED_STALE_S" in r["detail"]
                   for r in rd["reds"]),
               "；".join(r["coord"] for r in rd["reds"]))

        wp, kp = _write_fixture_dir(tmp, FIX_WATCH_TAMPER_WIRING, FIX_KEEPALIVE_OK)
        rc, rd = check(wp, kp)
        expect("F4g 负控·watch 接线断裂（常量名错）⇒ rc=2 不可证", rc == RC_UNPROVABLE)
        expect("F4h 负控·不可证点名装载失败", any("装载" in r["detail"] for r in rd["reds"]))

        wp, kp = _write_fixture_dir(tmp, FIX_WATCH_TAMPER_FORM, FIX_KEEPALIVE_OK)
        rc, rd = check(wp, kp)
        expect("F4i 负控·watch 取值来源形态不可证 ⇒ rc=2", rc == RC_UNPROVABLE)

        wp, kp = _write_fixture_dir(tmp, FIX_WATCH_OK, FIX_KEEPALIVE_TAMPER_VALUE)
        rc, rd = check(wp, kp)
        expect("F4j 负控·keepalive scheduler stale_s 失配（300）⇒ rc=1", rc == RC_DRIFT)
        expect("F4k 负控·失配与再硬编码双点名（stale_s）",
               any(r["kind"] == "失配" for r in rd["reds"])
               and any(r["kind"] == "再硬编码" for r in rd["reds"]),
               "；".join(sorted({r["kind"] for r in rd["reds"]})))

        wp, kp = _write_fixture_dir(tmp, FIX_WATCH_OK, FIX_KEEPALIVE_TAMPER_MISSING)
        rc, rd = check(wp, kp)
        expect("F4l 负控·keepalive 无 scheduler 项 ⇒ rc=2 不可证", rc == RC_UNPROVABLE)

        wp, kp = _write_fixture_dir(tmp, None, None, with_module=False)
        rc, rd = check(wp, kp)
        expect("F4m 负控·消费件缺席 ⇒ rc=2 不可证", rc == RC_UNPROVABLE)

        # 负控 N：原始字面负例（与验收命令 2/4 同 patterns）单独成立
        #   （注释行追加形态——不动 AST 结构，专验「注释亦计」的原始字面负例）
        wp, kp = _write_fixture_dir(
            tmp,
            FIX_WATCH_OK + "# 曾为 SCHED_STALE_S = 2400（旧硬编码形态存档于注释）\n",
            FIX_KEEPALIVE_OK + '    # 曾为 "stale_s": 2400（旧硬编码形态存档于注释）\n')
        rc, rd = check(wp, kp)
        expect("F4n 负控·注释再现旧字面形态 ⇒ rc=1（原始字面负例，注释亦计）",
               rc == RC_DRIFT and len(rd["reds"]) >= 2,
               "%d 红：%s" % (len(rd["reds"]),
                              "；".join(r["coord"] for r in rd["reds"])))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if ST_FAILS:
        print("SELFTEST FAIL：%d 条断言未过：%s" % (len(ST_FAILS), "; ".join(ST_FAILS)))
        return 1
    print("SELFTEST OK：值族自含 + 双面对等 + recon 判别力负控全过")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="factory-thresholds.py",
        description="判活阈值共享模块单源 + recon 对拍闸（D-140 / 债 D-129）")
    ap.add_argument("--recon", action="store_true",
                    help="实读两件阈值与模块对拍 + 禁再硬编码（默认无参=打印值族）")
    ap.add_argument("--watch", default=None,
                    help="factory-watch.py 路径（默认=本模块同目录）")
    ap.add_argument("--keepalive", default=None,
                    help="factory-keepalive.py 路径（默认=本模块同目录）")
    ap.add_argument("--out", default=None, help="读数落盘 JSON 路径（可选）")
    ap.add_argument("--selftest", action="store_true",
                    help="内嵌夹具自测（零网络、零仓内写入）")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()
    if args.recon:
        rc, reading = check(args.watch, args.keepalive)
        print(report(rc, reading))
        if args.out:
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(json.dumps(reading, ensure_ascii=False, indent=2) + "\n")
            print("读数落盘：%s" % args.out)
        return rc
    # 无参：值族清单（单源正本机读面）
    for n in CONST_NAMES:
        v, coord, sem = THRESHOLDS[n]
        print("%s = %d  ← %s ｜ %s" % (n, v, coord, sem))
    return RC_OK


if __name__ == "__main__":
    sys.exit(main())
