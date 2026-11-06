#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工作流调度门（fail-closed）——本机并发上限与外派机台账。

为什么有这个件
--------------
2026-11-03 20:26 ~ 2026-11-04 05:49，本机 zcode 被内核 OOM 杀死 8 次
（/var/log/syslog: "app-zcode-*.scope: Failed with result 'oom-kill'"）。
本机 16 核 / 15.2G 内存 / 20.5G swap，多个工作流并发时子代理进程与
cargo 构建同时抢内存，触发 OOM。用户 2026-11-04 定规矩：

    接下来仍然大量并行，但是同一个时间只有三个工作流在本机跑。
    超出的，放在 anolis 或者 tailnet 其他机器去跑。

于是本件把"本机 ≤3"变成可机械执行、可查账的门：
  * 本机槽位满（3/3）时 claim 一律拒绝（exit 3），拒绝是默认，不是例外；
  * 外派机槽位单独计（anolis 另有 128G 内存，容量不受本门限制）；
  * 台账落 状态/wf-gate/registry.json，追加式登记 claim/release 时间戳；
  * 台账损坏/读不出 ⇒ 一律拒绝放行（fail-closed），不许"读不出来就当空"。

用法
----
    python3 -I tools/wf-gate.py status
    python3 -I tools/wf-gate.py claim --id dwfrun-xxxx --label "夜间·某批" --host local
    python3 -I tools/wf-gate.py claim --id poce-r2 --label "PoC-E 复核" --host anolis
    python3 -I tools/wf-gate.py release --id dwfrun-xxxx
    python3 -I tools/wf-gate.py list [--host local]

★ 2026-11-05 发布面接线批 ③「收卷即回收」：释放**外派机**槽位后，顺手触发一次
  **远端定向回收**（tools/wf-offload.sh --reclaim <label>）——把该批的独占构建盘
  （可再生缓存目录）收掉。能不能删由**工具侧判据**说了算（尺寸 > 8G 的既有门槛
  **且无进程持有该路径**）⇒ 即使 release 早了，**在跑的批的盘也不会被删**。
  回收是**尽力而为**的一跳：失败只告警，不改 release 的结论与退出码。

退出码
------
    0  放行/成功
    2  台账损坏或参数非法（fail-closed 拒绝）
    3  本机槽位已满（local claim 被拒）
"""

import argparse
import fcntl
import json
import os
import subprocess
import sys
import time

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REG_DIR = os.path.join(WS, "状态", "wf-gate")
REG_PATH = os.path.join(REG_DIR, "registry.json")
LOCK_PATH = os.path.join(REG_DIR, "registry.lock")

# 本机并发上限——用户 2026-11-04 明定：同一个时间只有三个工作流在本机跑。
LOCAL_LIMIT = 3

# 外派机台位；anolis 是 af 的未来部署机（16 核 / 128G 内存 / /data 尚余 159G）。
# **2026-11-04 运营者明定：anolis 不设工作流数量上限（内存足够大），可加大并行**。
# 本机仍是 <=3（15.2G 内存，昨夜 OOM 8 次）⇒ 远端只有"软提醒"，没有硬拒。
REMOTE_HOSTS = ("anolis",)
REMOTE_SOFT_LIMIT = 6      # 超过只提醒不拒绝（16 核的吞吐参考线）


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _read_registry():
    """读台账；读不出或损坏 ⇒ 返回 None（调用方据此 fail-closed）。"""
    try:
        with open(REG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {"schema": 1, "local_limit": LOCAL_LIMIT, "entries": []}
    except Exception:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        return None
    data.setdefault("local_limit", LOCAL_LIMIT)
    return data


def _write_registry(data):
    os.makedirs(REG_DIR, exist_ok=True)
    tmp = REG_PATH + ".tmp-%d" % os.getpid()
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, REG_PATH)


def _lock():
    os.makedirs(REG_DIR, exist_ok=True)
    fd = os.open(LOCK_PATH, os.O_RDWR | os.O_CREAT, 0o664)
    fcntl.flock(fd, fcntl.LOCK_EX)
    return fd


def _active(data, host=None):
    out = []
    for e in data["entries"]:
        if e.get("state") != "active":
            continue
        if host and e.get("host") != host:
            continue
        out.append(e)
    return out


def _model_holds():
    """列出模型配额停用清单（$WS/状态/模型配额停用-*.json）。

    背景（2026-11-05 运营者定规）：GLM-5.3-Flash 周限即将耗尽（明天下午恢复），
    此期间不再使用，统一用 kimi-for-coding 替代。清单是主代理增删的闸面，
    文件 diff 即评审面。
    """
    out = []
    d = os.path.join(WS, "状态")
    try:
        for name in sorted(os.listdir(d)):
            if name.startswith("模型配额停用-") and name.endswith(".json"):
                out.append(os.path.join(d, name))
    except OSError:
        pass
    return out


def cmd_status(args):
    data = _read_registry()
    if data is None:
        print("FAIL 台账损坏（%s 读不出）——fail-closed，本机视为槽位已满" % REG_PATH)
        return 2
    local = _active(data, "local")
    print("本机上限：%d（用户 2026-11-04 明定）" % data.get("local_limit", LOCAL_LIMIT))
    print("本机在跑：%d" % len(local))
    for e in local:
        print("  - %s  %s  自 %s" % (e.get("id"), e.get("label"), e.get("claimed_at")))
    for h in REMOTE_HOSTS:
        rem = _active(data, h)
        print("外派 %s 在跑：%d（anolis 无硬上限；软提醒线 %d）" % (h, len(rem), REMOTE_SOFT_LIMIT))
        for e in rem:
            print("  - %s  %s  自 %s" % (e.get("id"), e.get("label"), e.get("claimed_at")))
    if len(local) > data.get("local_limit", LOCAL_LIMIT):
        print("WARN 本机在跑数已超上限（%d>%d）——请立即把超出的外派或释放"
              % (len(local), data.get("local_limit", LOCAL_LIMIT)))
        return 3
    return 0


def cmd_claim(args):
    fd = _lock()
    try:
        data = _read_registry()
        if data is None:
            print("FAIL 台账损坏——fail-closed 拒绝放行")
            return 2
        limit = data.get("local_limit", LOCAL_LIMIT)
        for e in data["entries"]:
            if e.get("id") == args.id and e.get("state") == "active":
                print("SKIP 已登记且在跑：%s（%s）" % (args.id, e.get("host")))
                return 0
        if args.host == "local":
            local = _active(data, "local")
            if len(local) >= limit:
                print("DENY 本机槽位已满（%d/%d）——超出的请外派到 %s"
                      % (len(local), limit, "/".join(REMOTE_HOSTS)))
                return 3
        if args.host in REMOTE_HOSTS:
            # ---- 模型配额停用闸（2026-11-05）----
            # 远端机上的代理通道用的是被停用模型（实测：anolis 的 zcode 无头 CLI
            # 只有 glm 一个 provider 通道，provider_config.json 无 kimi 条目、
            # credentials.json 无 kimi 凭据、`/model` 指令在 -p 形态下不换实际用模）
            # ⇒ 停用期间**不许在远端起代理**；算力仍可用（代理跑本机、编译跑远端）。
            holds = _model_holds()
            # ★2026-11-05 增补：--agent grok 时远端代理走 grok build CLI（xAI，不在
            # 停用清单内，且实测必须经 http://pandev-host.invalid:7890 代理出网）⇒ 放行。
            if holds and not args.compute_only and getattr(args, "agent", "zcode") != "grok":
                try:
                    with open(holds[0], "r", encoding="utf-8") as fh:
                        hold = json.load(fh)
                    stmt = hold.get("statement", "")
                except Exception:
                    stmt = ""
                print("DENY 模型配额停用闸：%s" % os.path.basename(holds[0]))
                if stmt:
                    print("     运营者定规：%s" % stmt)
                print("     目标机 %s 的 zcode 代理通道当前只有被停用模型 ⇒ 此期间不得用 zcode 在远端起代理。" % args.host)
                print("     替代路径（按运营者给的优先级）：① 代理跑在本机（minimax 主 / kimi-for-coding 余量），"
                      "算力与构建盘仍落 %s ⇒ 重派时加 --compute-only；"
                      "② 或在 %s 上用 ~/.local/bin/grok（-m grok-4.6，须走 pandev-host.invalid:7890 代理）起代理"
                      " ⇒ 重派时加 --agent grok。"
                      % (args.host, args.host))
                print("     仍不够 ⇒ 必须明确对运营者说出来（运营者 2026-11-05 明令，不得默默降级）。")
                return 3
            n_rem = len(_active(data, args.host))
            if n_rem >= REMOTE_SOFT_LIMIT:
                print("WARN 外派 %s 已在跑 %d 个（软提醒线 %d）——anolis 内存足够，继续放行"
                      % (args.host, n_rem, REMOTE_SOFT_LIMIT))
        data["entries"].append({
            "id": args.id,
            "label": args.label or "",
            "host": args.host,
            "state": "active",
            "claimed_at": _now(),
            "note": (args.note or "") + (
                " [compute-only：代理不在远端起（模型配额停用闸）]" if args.compute_only else ""
            ) + (
                " [grok 通道：xAI 非停用模型]" if getattr(args, "agent", "zcode") == "grok" else ""
            ),
        })
        _write_registry(data)
        n = len(_active(data, "local"))
        print("OK 放行：%s（%s / %s） 本机在跑 %d/%d" % (args.id, args.host, args.label or "-", n, limit))
        return 0
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _reclaim_after_release(host, label):
    """收卷即回收（2026-11-05 发布面接线批 ③）：release 成功后触发一次**远端定向回收**。

    回收动作在远端执行（tools/wf-offload.sh --reclaim <label>），回收对象**只有**该批的
    独占构建盘（可再生缓存目录）；能不能删由工具侧判据说了算：尺寸 > 8G（既有门槛）
    **且无进程持有该路径**（/proc/*/environ 的 CARGO_TARGET_DIR 指向它，或进程 cwd /
    打开的 fd 落在它里面）⇒ **即使 release 早了，在跑的批的盘也不会被删**。
    回收失败**不影响 release 本身**（槽位已释放是事实；回收是尽力而为的一跳）。
    返回一句话读数（None=未触发）。
    """
    if not label or host not in REMOTE_HOSTS:
        return None
    script = os.path.join(WS, "tools", "wf-offload.sh")
    if not os.path.isfile(script):
        return "回收未执行（缺件：%s）" % script
    env = dict(os.environ)
    env["OFFLOAD_REMOTE"] = host
    try:
        p = subprocess.run(["bash", script, "--reclaim", label],
                           capture_output=True, text=True, timeout=300, env=env)
    except Exception as e:
        return "回收未执行（%s: %s）" % (type(e).__name__, str(e)[:80])
    lines = [l.strip() for l in (p.stdout or "").strip().splitlines() if l.strip()]
    tail = " / ".join(lines[-2:]) if lines else ""
    return "rc=%d %s" % (p.returncode, tail)


def cmd_release(args):
    fd = _lock()
    try:
        data = _read_registry()
        if data is None:
            print("FAIL 台账损坏——fail-closed")
            return 2
        hit = 0
        released = []
        for e in data["entries"]:
            if e.get("id") == args.id and e.get("state") == "active":
                e["state"] = "released"
                e["released_at"] = _now()
                released.append(e)
                hit += 1
        if not hit:
            print("WARN 未找到在跑记录：%s" % args.id)
            return 2
        _write_registry(data)
        n = len(_active(data, "local"))
        print("OK 释放：%s  本机在跑 %d/%d" % (args.id, n, data.get("local_limit", LOCAL_LIMIT)))
        # ★ 收卷即回收（2026-11-05 接线批 ③）：释放外派机槽位 ⇒ 顺手把该批的独占
        #   构建盘收掉（远端定向回收）。回收是**尽力而为**：失败只告警，不改 release 结论。
        for e in released:
            rc = _reclaim_after_release(e.get("host"), e.get("label"))
            if rc is not None:
                print("     收卷回收（%s / %s）：%s" % (e.get("host"), e.get("label"), rc))
        return 0
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def cmd_list(args):
    data = _read_registry()
    if data is None:
        print("FAIL 台账损坏")
        return 2
    for e in data["entries"]:
        if args.host and e.get("host") != args.host:
            continue
        print("%s  %-10s %-9s %s  %s" % (e.get("id"), e.get("host"), e.get("state"),
                                         e.get("claimed_at"), e.get("label")))
    return 0


def main(argv):
    p = argparse.ArgumentParser(description="工作流调度门：本机并发上限 + 外派台账")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("status", help="看本机/外派机在跑数")
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("claim", help="占一个槽位")
    sp.add_argument("--id", required=True)
    sp.add_argument("--label", default="")
    sp.add_argument("--host", default="local", choices=("local",) + REMOTE_HOSTS)
    sp.add_argument("--note", default="")
    sp.add_argument("--compute-only", dest="compute_only", action="store_true",
                    help="外派槽位仅用于算力（代理跑本机、编译跑远端）——模型配额停用闸下"
                         "远端不得起代理时必须显式声明")
    sp.add_argument("--agent", dest="agent", default="zcode", choices=("zcode", "grok"),
                    help="远端代理通道：zcode（默认）/ grok（grok 不在停用清单内，停用期可用）")
    sp.set_defaults(func=cmd_claim)

    sp = sub.add_parser("release", help="释放槽位")
    sp.add_argument("--id", required=True)
    sp.set_defaults(func=cmd_release)

    sp = sub.add_parser("list", help="列台账")
    sp.add_argument("--host", default=None)
    sp.set_defaults(func=cmd_list)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
