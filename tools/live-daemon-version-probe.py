#!/usr/bin/env python3
"""live-daemon-version-probe — 在役进程版本对账门（all-gates.sh L3 常驻门本体）

发现（2026-11-03 RT 收尾批，红队终局轮确证发现「在役 event-router 守护载旧码」）：
本地三批修复（RT-E157 ARB_REJECT_RE 拒收回流腿、RT-E160「真上板才在飞」+88 条
skipped_newer 存量重武装、RT-E169 quote 契约三道机械门）全部只落本地副本，
**在役守护进程仍跑 17:58 旧码**（在役 11-02 17:54:51 起跑 / 盘面 18:45 已改，
漂移 30h+ 无人发现）：三批修复整批未在役；RT-E160 的 88 条冻结账被旧码的
poll_verify_rejects 防重放（`if card_id in seen: continue`）**永久冻结**，63 条原子
永远停在非 verified；而变更日志却按「已生效」记账（虚记生产生效）。

根因面（此前全仓零机检）：**没有任何一处把「在役进程跑的是哪一版」与「盘上是哪一版」
对账**。既有面只能看到「进程在 + state 新鲜」（keepalive 判活）与「文件已改」
（git/备份链）——两者之间那道缝（改了没重启＝修复不生效）无人对账：
  · 逃逸台账 RT-E103:848 自记「在役进程版本对账门」机制①②③「均未见施工」；
  · 目的-监测项映射.md 零行（grep 'lstart|在役进程' = 0）；
  · tools/ 全仓零探针（grep 'lstart|proc_start|code_version' 仅两处注释）；
  · all-gates.sh 零门项（grep add_item L* 'router|进程版本|在役' = 0）——
    gov 门户侧有 deploy-consistency-probe.sh（L5 部署一致性门）做同款对账，
    **本机在役守护侧零覆盖**。

本门＝那道缝的机检（只读、零副作用、不换码）：
  对账两端 —— ①在役守护**载入时**的判据源指纹（状态面登记 daemon_src.sha256，
  守护每次写盘登记：tools/event-router.py 起 2026-11-03 批、tools/self-improve-loop.py
  起 v1.3.11）；②盘上判据源此刻的 sha256。
  另有一道**启动时刻证明**：Python 在进程启动时加载源码，故「进程启动时刻 ≥ 盘面
  源码 mtime」即证明在役载入的正是盘面那一版（无须指纹登记亦可证）。

判定（任一受管守护不过 ⇒ 非零退出；不静默 SKIP、不猜绿）：
  · 指纹不等 → 红：在役载入版本 ≠ 盘上版本（修复未在役，两套真相并行）；
  · 进程启动早于盘面源码 mtime → 红：进程仍跑旧码（部署了≠生效）；
  · 进程启动早于**本地 import 闭包**落盘 → 红：依赖模块仍跑旧码（2026-11-03 依赖
    闭包批：此前只对账主脚本，对「主脚本之外的本地 import」结构性失明——实证
    emit-sidecar 10-31 在役、依赖 otel_emit 11-02 已修（DEFAULT_ENDPOINT），在役
    跑修前字节 2 天+ 而本门判 ALIGNED＝假绿。多模块守护的载入面＝主脚本+闭包：
    静态 import 随进程启动载入，同一启动时刻证明适用；运行时（函数体内）懒载
    import 载入时刻不可证 ⇒ 不可证，不猜绿也不误红）；
  · 状态面无指纹登记且启动时刻不可证 → 不可证（rc=2），不放过假绿；
  · 守护不在役且状态面陈旧 → 红（在册受管守护失联，判活归 keepalive，本门不放过）；
  · 守护不在役但状态面仍新鲜（刚重启/优雅停机窗口）→ 非红，记 INFO。

名册分两层+一道 N/A（边界如实，见下；2026-11-03 在役版本对账扩册批由 6 扩 8）：
  · 受管（硬判，参与红绿）：**已具备版本钉机制**的两个守护——router（本批主体）、
    self-improve-loop（v1.3.11 起有钉）。二者均有「精确指纹 + 启动时刻」双证。
  · 旁证（不判红，仅打印）：scheduler / status-push / emit-sidecar / quota-governor /
    factory-watch——这五个守护**尚无版本钉机制**（状态面不登记载入指纹），只有启动时刻
    一道证；本门对它们只做旁证报告，不据其判红（避免把「未覆盖」误判成「缺陷」），
    机制缺口已登记（给它们补 src_pin 是下一批的机制腿，不是本门能自证的）。
    watch 为 keepalive 在册首对象、DEB57-A0 错根修复本体，扩册批入册；其「源
    mtime>进程启动即自动重启」 enforcement 已落 keepalive watch 腿（RT-E194 拦截
    机制②同批落码在役）——旁证打印漂移 + keepalive 自动换码，两层合拢治「静默回归」。
  · N/A 道（不判红不猜绿，只证在场+启动时刻）：dash——看板 http.server 8790，
    判据源=CPython stdlib（无盘面工作区源码可对账），版本对账不适用；如实打印边界，
    判活归 keepalive dash 腿。keepalive 12 对象名册中不入本门的其余 4 个
    （af-execline/mes-ch=订单驱动/远程探针、otelcol=binary、portal=gov 远程主机）
    不在本机 python 在役对账域——残余如实，见映射 在役版本对账 行。

用法：
  python3 tools/live-daemon-version-probe.py             # 实查（在役 vs 盘上 版本对账）
  python3 tools/live-daemon-version-probe.py --selftest  # 判别力负向自测（夹具，零改动真树）
退出码：0=全绿；1=有红（版本漂移/在册守护失联）；2=不可证（读数缺失/坏，不猜绿）；
        3=用法错误。
"""
import ast
import hashlib
import json
import os
import sys
import time

WS = "/home/pan-ding/workspace/agent黑灯工厂"

# 在册守护名册（路径相对 WS）。covered=True → 参与红绿；covered=False → 旁证不判红。
DAEMONS = [
    {"name": "router", "script": "tools/event-router.py", "covered": True,
     "state": "kb-seed/sandbox/.router-state.json", "pin_key": "daemon_src",
     "stale_s": 3600,
     "note": "事件路由器（本批主体：RT-E157/RT-E160/RT-E169 三批修复的在役载体）"},
    {"name": "self-improve-loop", "script": "tools/self-improve-loop.py", "covered": True,
     "state": "状态观测/loop-state.json", "pin_key": "daemon_src",
     "stale_s": 300,
     "note": "自改进循环产线守护（v1.3.11 起自带版本钉，先例）"},
    {"name": "scheduler", "script": "tools/factory-scheduler.py", "covered": False,
     "state": "状态观测/factory-scheduler-state.json", "pin_key": None,
     "stale_s": 2400, "note": "调度中枢（无版本钉机制＝旁证）"},
    {"name": "status-push", "script": "tools/factory-status-push.py", "covered": False,
     "state": None, "pin_key": None,
     "stale_s": 300, "note": "工厂快况推送器（无版本钉机制＝旁证）"},
    {"name": "emit-sidecar", "script": "tools/otel/emit-sidecar.py", "covered": False,
     "state": "状态观测/otel-sidecar.json", "pin_key": None,
     "stale_s": 300,
     "note": "OTel sidecar（无版本钉机制＝旁证；多模块守护：本地 import 闭包 "
             "otel_emit＝熔断/端点/scrub 单一真源，2026-11-03 依赖闭包批入对账）"},
    {"name": "quota-governor", "script": "tools/quota-governor.py", "covered": False,
     "state": "状态观测/quota.json", "pin_key": None,
     "stale_s": 600, "note": "配额闸（无版本钉机制＝旁证）"},
    {"name": "factory-watch", "script": "tools/factory-watch.py", "covered": False,
     "state": "状态观测/watch-state.json", "pin_key": None,
     "stale_s": 300,
     "note": "巡检守护（keepalive 在册首对象、DEB57-A0 错根修复本体；无版本钉机制＝旁证——"
             "「源 mtime>进程启动」自动重启已落 keepalive watch 腿＝RT-E194 拦截机制②，"
             "2026-11-03 在役版本对账扩册批入册）"},
    {"name": "dash", "script": None, "covered": False,
     "state": None, "pin_key": None, "stale_s": None,
     "argv_tokens": ["http.server", "8790"],
     "note": "看板 http.server 8790（判据源=CPython stdlib，无盘面工作区源码可对账＝"
             "版本对账 N/A 道：只证在役在场+启动时刻，不判红不猜绿；判活归 keepalive dash 腿）"},
]


# ------------------------------------------------------------------ 读数件

def sha256_file(path):
    """盘上判据源此刻的 sha256；读不到返回 None（不可证，不猜）。"""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def file_mtime(path):
    try:
        return os.stat(path).st_mtime
    except OSError:
        return None


def file_age(path):
    m = file_mtime(path)
    return None if m is None else time.time() - m


def scan_pids(script_basename):
    """在役进程 pid 列表：argv0 是 python* 且任一后续参数 basename == 脚本名。

    口径与 tools/factory-keepalive.py 的 scan_pids 同款（禁 pgrep -f 防自匹配：
    本探针自己的命令行里就带着脚本名，pgrep -f 会把自身与 shell 包装算成在役）。
    """
    out = []
    me = os.getpid()
    for ent in os.listdir("/proc"):
        if not ent.isdigit() or int(ent) == me:
            continue
        try:
            with open(f"/proc/{ent}/cmdline", "rb") as f:
                argv = [a.decode("utf-8", "replace")
                        for a in f.read().split(b"\0") if a]
        except OSError:
            continue
        if not argv:
            continue
        if not os.path.basename(argv[0]).startswith("python"):
            continue
        if any(os.path.basename(a) == script_basename for a in argv[1:]):
            out.append(int(ent))
    return sorted(out)


def scan_pids_tokens(tokens):
    """argv token 匹配的在役 pid 列表：argv0 是 python* 且 tokens 全部作为后续参数在场。

    口径与 tools/factory-keepalive.py 的 dash_pids 同款（`"http.server" in argv and
    端口 in argv`＝元素精确成员，非子串），用于无独立脚本文件的对象（如 stdlib
    http.server 看板）。禁 pgrep -f 防自匹配，同 scan_pids。
    """
    out = []
    me = os.getpid()
    for ent in os.listdir("/proc"):
        if not ent.isdigit() or int(ent) == me:
            continue
        try:
            with open(f"/proc/{ent}/cmdline", "rb") as f:
                argv = [a.decode("utf-8", "replace")
                        for a in f.read().split(b"\0") if a]
        except OSError:
            continue
        if not argv:
            continue
        if not os.path.basename(argv[0]).startswith("python"):
            continue
        if all(t in argv[1:] for t in tokens):
            out.append(int(ent))
    return sorted(out)


def boot_time():
    try:
        with open("/proc/stat") as f:
            for line in f:
                if line.startswith("btime "):
                    return int(line.split()[1])
    except (OSError, ValueError):
        pass
    return None


def pid_start_epoch(pid, btime):
    """进程启动时刻（epoch 秒）：/proc/<pid>/stat 第 22 字段（clock tick）+ btime。"""
    try:
        with open(f"/proc/{pid}/stat") as f:
            fields = f.read().rsplit(")", 1)[1].split()
        ticks = int(fields[19])
    except (OSError, ValueError, IndexError):
        return None
    if btime is None:
        return None
    return btime + ticks / os.sysconf("SC_CLK_TCK")


def read_pin(state_path, key):
    """状态面登记的**载入时**源码指纹（daemon_src.sha256）。

    返回 (sha_or_None, err)：err 非空表示读数不可用（缺件/坏 JSON/键缺）。
    """
    if not state_path or not key:
        return None, "该守护无版本钉机制（状态面不登记载入指纹）"
    full = os.path.join(WS, state_path)
    try:
        with open(full, "rb") as f:
            st = json.loads(f.read().decode("utf-8", "replace"))
    except FileNotFoundError:
        return None, f"状态面缺件（{state_path}）"
    except (OSError, ValueError) as e:
        return None, f"状态面不可读/坏 JSON（{state_path}: {type(e).__name__}）"
    if not isinstance(st, dict):
        return None, f"状态面结构异常（{state_path} 顶层非 dict）"
    rec = st.get(key)
    if not isinstance(rec, dict):
        return None, f"状态面无 {key} 登记（在役码早于版本钉机制）"
    sha = rec.get("sha256")
    if not sha:
        return None, f"状态面 {key}.sha256 读数为空（在役码早于版本钉机制或登记失败）"
    return sha, None


# ------------------------------------------------------------------ 依赖闭包

def _resolve_local_module(name, script_dir):
    """import 模块名 → 工作区盘面文件列表（含所属包 __init__.py）；解析不到返回 []。

    只在守护运行时实际可用的模块根里找（与各守护 sys.path 注入同源：
    emit-sidecar.py:44-45 注入 tools/otel 与 WS、factory-scheduler.py:100 /
    factory-status-push.py:45 注入 tools/otel）——stdlib/三方不在工作区，自然
    解析不到＝不入闭包（本门只对账工作区判据源）。根次序即 sys.path 命中次序。
    """
    roots = [WS, os.path.join(WS, "tools"),
             os.path.join(WS, "tools", "otel"), script_dir]
    parts = [p for p in name.split(".") if p]
    for root in roots:
        base = os.path.join(root, *parts)
        hits = []
        for cand in (base + ".py", os.path.join(base, "__init__.py")):
            cand = os.path.realpath(cand)
            if os.path.isfile(cand) and cand not in hits:
                hits.append(cand)
        if hits:
            if not hits[0].endswith("__init__.py"):
                # import a.b 也会执行包 a 的 __init__.py（若 a 是包）
                pkg_init = os.path.realpath(
                    os.path.join(os.path.dirname(hits[0]), "__init__.py"))
                if pkg_init not in hits and os.path.isfile(pkg_init):
                    hits.append(pkg_init)
            return hits
    return []


def _iter_imports(tree):
    """ast 树里的 import 语句 → [(模块名, 是否随本模块载入即执行)]。

    「随载入执行」＝语句位于模块级直系执行流：Module 体本身及其中的
    try/except（模块载入时无条件尝试，如 factory-scheduler.py:101-104 的
    `try: import factory_otel`）；一旦嵌进 def/class/lambda（延迟到调用时）或
    if/for/while/with/match（条件体，载入时不必然执行）即运行时懒载
    （如 emit-sidecar.py:159 函数体内 `import kb.store`）。
    相对 import（level>0）顶层脚本不适用，跳过。
    """
    deferred = [ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda,
                ast.If, ast.For, ast.While, ast.With, ast.AsyncFor, ast.AsyncWith]
    if hasattr(ast, "Match"):
        deferred.append(ast.Match)
    deferred = tuple(deferred)
    out = []

    def walk(node, load_time):
        for n in ast.iter_child_nodes(node):
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                if isinstance(n, ast.ImportFrom) and (n.level != 0 or not n.module):
                    continue
                mods = ([a.name for a in n.names] if isinstance(n, ast.Import)
                        else [n.module])
                for m in mods:
                    out.append((m, load_time))
                continue
            walk(n, load_time and not isinstance(n, deferred))

    walk(tree, True)
    return out


def local_import_closure(script_path):
    """主脚本之外的本地 import 闭包 → [(abs_path, kind)]，kind ∈ {"static","lazy"}。

    多模块守护的「在役载入版本」由主脚本+闭包共同决定（Python 在 import 语句执行
    时读入模块源码）：本探针此前只对账主脚本，对闭包结构性失明——2026-11-03 实证
    emit-sidecar 10-31 在役、依赖 otel_emit 11-02 已修，在役跑修前字节 2 天+ 而本门
    判 ALIGNED＝假绿（即本函数所治）。
      static＝存在一条「全静态 import 边」可达路径 ⇒ 必在进程启动时随主脚本载入，
              其盘面 mtime 晚于进程启动＝在役跑旧码的**正面证据**；
      lazy  ＝仅经运行时 import 边可达 ⇒ 载入时刻不可证（mtime 晚于启动只能记
              不可证，不猜绿也不误红）。
    闭包递归展开（依赖的依赖同法，静态边传播「随启动载入」性质；静态路径一旦存在
    即升格 static）；环路用 visited 剪断；主脚本自身不入闭包。
    """
    start = os.path.realpath(script_path)
    kinds = {}
    seen = {start}
    queue = [(start, True)]                     # (文件, 是否随进程启动载入)
    while queue:
        path, start_loaded = queue.pop(0)
        try:
            with open(path, "rb") as f:
                tree = ast.parse(f.read().decode("utf-8", "replace"))
        except (OSError, SyntaxError, ValueError):
            continue
        for mod, edge_static in _iter_imports(tree):
            for dep in _resolve_local_module(mod, os.path.dirname(path)):
                kind = "static" if (start_loaded and edge_static) else "lazy"
                upgraded = kinds.get(dep) == "lazy" and kind == "static"
                if dep not in kinds or upgraded:
                    kinds[dep] = kind
                if dep not in seen or upgraded:
                    seen.add(dep)
                    queue.append((dep, kinds[dep] == "static"))
    return sorted(kinds.items())


# ------------------------------------------------------------------ 判定核

def judge(disk_sha, disk_mtime, proc_start, pin_sha, pin_err, deps=None):
    """版本对账判定核：(verdict, why)。

    verdict ∈ {"ALIGNED", "DRIFT", "UNPROVABLE"}
      · DRIFT      ——有**正面证据**表明在役跑的不是盘面这一版（指纹不等 / 启动早于
                     主脚本或依赖闭包落盘）
      · UNPROVABLE ——证不出来（无钉且启动时刻不可证 / 盘面读不到 / 懒载依赖落盘晚于
                     启动＝依赖载入时刻不可证）
      · ALIGNED    ——各证都对齐（指纹相等，或启动时刻证明主脚本+依赖闭包均在役即盘面）
    纯函数（无 IO）——selftest 直接喂夹具，钉住判别力。
    deps＝本地 import 闭包 [(相对路径, mtime, "static"|"lazy")]，主脚本之外的载入面
    （None/[]＝单文件守护，不引入新判据）。
    """
    if disk_sha is None:
        return "UNPROVABLE", "盘面判据源读不到（sha256 不可得）——在役版本不可证（不猜绿）"
    if proc_start is None:
        return "UNPROVABLE", "在役进程启动时刻读不到（/proc 读数异常）——在役版本不可证"
    deps = list(deps or [])
    fmt = lambda ts: time.strftime("%m-%d %H:%M:%S", time.localtime(ts))
    stale = [r for r, m, k in deps
             if k == "static" and m is not None and m > proc_start + 1]
    lazy_unknown = [r for r, m, k in deps
                    if k == "lazy" and (m is None or m > proc_start + 1)]

    def dep_why(names):
        mt = {r: m for r, m, _ in deps}
        return "、".join(f"{r}({fmt(mt[r]) if mt[r] is not None else 'mtime 读不到'})"
                         for r in names)

    if pin_sha:
        if pin_sha != disk_sha:
            return ("DRIFT",
                    f"在役载入指纹 {pin_sha[:12]}… ≠ 盘上指纹 {disk_sha[:12]}…"
                    f"（修复只落盘、未在役＝两套真相并行）")
        if stale:
            return ("DRIFT",
                    f"主脚本指纹对齐，但依赖闭包落盘晚于进程启动：{dep_why(stale)}"
                    f"——依赖模块仍跑旧码（指纹只钉主脚本，闭包无钉＝靠启动时刻证明）")
        if lazy_unknown:
            return ("UNPROVABLE",
                    f"主脚本指纹对齐，但懒载依赖落盘晚于进程启动/读不到"
                    f"（{dep_why(lazy_unknown)}）＝依赖载入时刻不可证（不猜绿）")
        tail = f"（含本地 import 闭包 {len(deps)} 件启动时刻证明）" if deps else ""
        return "ALIGNED", f"在役载入指纹 ≡ 盘上指纹（{disk_sha[:12]}…）{tail}"
    # 无指纹登记 → 主脚本+依赖闭包合起来只有启动时刻一道证
    if stale:
        return ("DRIFT",
                f"在役进程启动({fmt(proc_start)})早于依赖闭包落盘：{dep_why(stale)}"
                f"——依赖模块仍跑旧码（部署了≠生效；主脚本之外的本地 import 已入对账）")
    if lazy_unknown:
        return ("UNPROVABLE",
                f"懒载依赖落盘晚于进程启动/读不到（{dep_why(lazy_unknown)}）＝载入时刻"
                f"不可证（不猜绿）")
    if disk_mtime is None:
        return "UNPROVABLE", "盘面判据源 mtime 读不到——启动时刻证明不可用"
    if proc_start + 1 < disk_mtime:
        return ("DRIFT",
                f"在役进程启动({fmt(proc_start)})"
                f"早于盘面源码落盘({fmt(disk_mtime)})"
                f"——进程仍跑旧码（部署了≠生效）")
    closure = f"（含本地 import 闭包 {len(deps)} 件启动时刻证明）" if deps else ""
    if pin_err:
        return ("ALIGNED",
                f"无版本钉（{pin_err}）但启动时刻晚于盘面源码落盘"
                f"（{fmt(proc_start)} ≥ {fmt(disk_mtime)}）{closure}"
                f"⇒ 在役载入的即盘面这一版")
    return "ALIGNED", (f"无版本钉但启动时刻晚于盘面源码落盘{closure}"
                       f" ⇒ 在役载入的即盘面这一版")


def check_na_daemon(spec):
    """N/A 道实查（无盘面判据源的对象，如 stdlib http.server 看板）：

    版本对账不适用（无工作区源码可 sha256/mtime），只证在役在场 + 启动时刻，
    恒 INFO（不判红不猜绿——「不在场」也如实打印，判活归 keepalive 对应腿）。
    """
    pids = scan_pids_tokens(spec["argv_tokens"])
    if not pids:
        return ("INFO", "不在役（本对象无盘面判据源无状态面：版本对账 N/A、判活归 "
                        "keepalive——不在场如实打印，不判红不猜绿）", [])
    bt = boot_time()
    starts = [pid_start_epoch(p, bt) for p in pids]
    starts = [s for s in starts if s is not None]
    proc_start = min(starts) if starts else None
    st = proc_start and time.strftime("%m-%d %H:%M:%S", time.localtime(proc_start))
    lines = [f"    进程 pid={pids}（取最早起跑 {st}）"
             f" 判据源=CPython stdlib {spec['argv_tokens']}"
             f"（无盘面工作区源码，版本对账不适用）"]
    if proc_start is None:
        return ("INFO", "在役在场但启动时刻读不到（/proc 读数异常）——不猜，如实", lines)
    return ("INFO", f"在役在场（最早起跑 {st}）；判据源=stdlib＝无盘面源码可对账，"
                    f"版本对账 N/A（如实边界，非绿非红）", lines)


def check_daemon(spec):
    """单个守护的实查读数 → (verdict, why, extra_lines)。"""
    if spec.get("script") is None:
        return check_na_daemon(spec)
    script = os.path.join(WS, spec["script"])
    basename = os.path.basename(spec["script"])
    disk_sha = sha256_file(script)
    disk_mtime = file_mtime(script)
    closure = local_import_closure(script)
    deps = [(os.path.relpath(p, WS), file_mtime(p), k) for p, k in closure]
    pids = scan_pids(basename)
    state_path = spec.get("state")
    age = file_age(os.path.join(WS, state_path)) if state_path else None
    lines = []
    if not pids:
        # 不在役：状态面新鲜 → 非红（刚重启/优雅停机窗口）；状态面陈旧/缺件 → 红。
        fresh = age is not None and age < spec["stale_s"]
        if fresh:
            return ("INFO", f"不在役（状态面仍新鲜 age={int(age)}s<{spec['stale_s']}s，"
                            f"判活归 keepalive，本门不判红）", lines)
        return ("DRIFT", f"在册受管守护不在役且状态面陈旧"
                         f"（state_age={int(age) if age is not None else '缺失'}s"
                         f"，阈 {spec['stale_s']}s）——失联即红，不放过", lines)
    bt = boot_time()
    starts = [pid_start_epoch(p, bt) for p in pids]
    starts = [s for s in starts if s is not None]
    proc_start = min(starts) if starts else None
    pin_sha, pin_err = read_pin(state_path, spec.get("pin_key"))
    verdict, why = judge(disk_sha, disk_mtime, proc_start, pin_sha, pin_err, deps)
    lines.append(f"    进程 pid={pids}（取最早起跑 {proc_start and time.strftime('%m-%d %H:%M:%S', time.localtime(proc_start))}）"
                 f" 盘面源码 mtime={disk_mtime and time.strftime('%m-%d %H:%M:%S', time.localtime(disk_mtime))}"
                 f" 盘面 sha256={disk_sha and disk_sha[:12]}…"
                 f" 状态面指纹={pin_sha[:12] + '…' if pin_sha else '无'}")
    if deps:
        det = "、".join(
            f"{r}[{k}]（mtime={time.strftime('%m-%d %H:%M:%S', time.localtime(m)) if m is not None else '读不到'}）"
            for r, m, k in deps)
        lines.append(f"    本地 import 闭包={len(deps)} 件：{det}")
    return verdict, why, lines


# ------------------------------------------------------------------ 自测

def selftest():
    """判别力负向自测（零改动真树，纯夹具）：红路必红、绿路必绿、不可证不猜绿。"""
    now = time.time()
    cases = [
        # (名, disk_sha, disk_mtime, proc_start, pin_sha, pin_err, deps, 期望 verdict)
        ("红路1 指纹不等（在役跑旧码）", "a" * 64, now - 100, now - 50, "b" * 64, None, [], "DRIFT"),
        ("红路2 启动早于盘面落盘（改了没重启）", "a" * 64, now - 50, now - 500, None,
         "无版本钉机制", [], "DRIFT"),
        ("红路3 静态依赖晚于启动、主脚本无漂移（emit-sidecar 实证夹具：依赖闭包盲区）",
         "a" * 64, now - 3 * 86400, now - 2 * 86400, None, "无版本钉机制",
         [("tools/otel/otel_emit.py", now - 86400, "static")], "DRIFT"),
        ("红路4 主脚本钉对齐但静态依赖晚于启动（指纹只钉主脚本的残余盲区）",
         "a" * 64, now - 100, now - 50, "a" * 64, None,
         [("tools/otel/otel_emit.py", now - 10, "static")], "DRIFT"),
        ("绿路1 指纹相等", "a" * 64, now - 100, now - 50, "a" * 64, None, [], "ALIGNED"),
        ("绿路2 无钉但启动晚于落盘", "a" * 64, now - 100, now - 50, None,
         "无版本钉机制", [], "ALIGNED"),
        ("绿路3 依赖闭包均早于启动（静态+懒载，闭包证明成立）", "a" * 64, now - 100,
         now - 50, None, "无版本钉机制",
         [("tools/otel/otel_emit.py", now - 200, "static"),
          ("kb/store.py", now - 300, "lazy")], "ALIGNED"),
        ("不可证 懒载依赖晚于启动（载入时刻不可证，不猜绿不误红）", "a" * 64,
         now - 100, now - 50, "a" * 64, None,
         [("kb/store.py", now - 10, "lazy")], "UNPROVABLE"),
        ("不可证 盘面读不到", None, now - 100, now - 50, "a" * 64, None, [], "UNPROVABLE"),
        ("不可证 启动时刻读不到", "a" * 64, now - 100, None, "a" * 64, None, [], "UNPROVABLE"),
        ("不可证 无钉且盘面 mtime 读不到", "a" * 64, None, now - 50, None, "无钉", [], "UNPROVABLE"),
    ]
    fails = 0
    for name, ds, dm, ps, pin, perr, deps, want in cases:
        got, why = judge(ds, dm, ps, pin, perr, deps)
        ok = (got == want)
        if not ok:
            fails += 1
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} → 判定={got}（期望 {want}）"
              + ("" if ok else f"｜{why}"))
    print(f"  断言 {len(cases) - fails}/{len(cases)} 通过")
    return 0 if fails == 0 else 1


def main():
    args = sys.argv[1:]
    if args == ["--selftest"]:
        print("live-daemon-version-probe --selftest：判别力负向自测（纯夹具，零改动真树）")
        return selftest()
    if args:
        print(f"用法：{sys.argv[0]} [--selftest]", file=sys.stderr)
        return 3

    print("在役进程版本对账门（live-daemon-version-probe）"
          "——对账两端：在役载入指纹/启动时刻 vs 盘面判据源此刻 sha256")
    red, unprov, drifted, info = [], [], [], []
    for spec in DAEMONS:
        tag = "受管" if spec["covered"] else "旁证"
        verdict, why, lines = check_daemon(spec)
        print(f"  [{tag}] {spec['name']}（{spec['script']}）")
        for ln in lines:
            print(ln)
        print(f"    判定={verdict}：{why}")
        if not spec["covered"]:
            # 旁证不判红（该守护尚无版本钉机制＝机制缺口，非本门判据）
            if verdict == "DRIFT":
                drifted.append(f"{spec['name']}：{why}（旁证·不判红·机制缺口待补）")
            continue
        if verdict == "DRIFT":
            red.append(f"{spec['name']}：{why}")
        elif verdict == "UNPROVABLE":
            unprov.append(f"{spec['name']}：{why}")
        elif verdict == "INFO":
            info.append(f"{spec['name']}：{why}")
    if drifted:
        print("  [旁证·机制缺口] 以下守护无版本钉机制，仅以启动时刻一道证旁证，"
              "本门不据其判红（补 src_pin 机制后即可纳入硬判）：")
        for d in drifted:
            print(f"    - {d}")
    if red:
        print(f"RED：在役进程版本对账不过（{len(red)} 项）——修复落盘未在役＝两套真相并行")
        for r in red:
            print(f"  - {r}")
    if unprov:
        print(f"RED：在役版本不可证（{len(unprov)} 项）——不猜绿")
        for u in unprov:
            print(f"  - {u}")
    if info:
        for i in info:
            print(f"INFO：{i}")
    if red:
        return 1
    if unprov:
        return 2
    print("OK：受管在册守护的在役载入版本 ≡ 盘面判据源版本（指纹对齐或启动时刻证明）"
          "——修复落盘已在役")
    return 0


if __name__ == "__main__":
    sys.exit(main())
