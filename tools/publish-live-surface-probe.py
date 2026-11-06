#!/usr/bin/env python3
"""publish-live-surface-probe.py — 在役公网静态面「实况过闸 + 白名单双真源对账」探针

背景（2026-11-03 RT-45 修复批，已确证发现）：
  发布面脱敏闸（tools/publish-scrub-gate.py）的扫描对象是**本地待发布暂存树**
  （tools/factory-status-push.py:STAGE 物化 → _gate_ok(stage) 过闸 → 推 gov），
  读数形如 {"verdict":"ok","scanned":1807,"hits":[]} 覆盖的是那 1807 件本地件；
  而公网直出面是 gov 在役 static/ 树（2026-11-03 实测 1814 件），两者差集 6 件
  从未过闸：
    · v2/index.html.2026xxxx-pre-*.bak ×3（历史快照；**仅因文件名含中文**被服务端
      字符集正则 _STATIC_NAME_RE 侥幸挡下，非受控拦截；ASCII 命名即公网直出）
    · 根 index.html、v2/stream-demo/*.json ×2（ASCII 名 ⇒ 当时公网直出）
  根因＝「哪些文件可发布」的白名单（publish-scrub-gate.PATH_OK）**只在发布端执行**，
  服务端（tools/af-jobs-portal.py:_static_path）此前只有字符集正则 ⇒ 服务端零形状
  约束：任何 ASCII 名文件落在 static/ 下即公网直出且不经脱敏。
  本探针把「闸的读数」与「公网面实况」绑在一起：
    腿A 实况过闸：在役 static/ 树只读拉回本地，用**同一份闸规则**（PATH_OK + K/O/X
         族模式 + 同一份 allowlist）扫一遍——任一「白名单外文件」/ 内容命中 / 扫描
         覆盖不全（scanned ≠ 在册件数）即红。
    腿B 双真源对账：发布端 PATH_OK ≡ 本地门户 _STATIC_PATH_OK ≡ **在役**门户
         _STATIC_PATH_OK（从在役件取回真源比对）——三面任一漂移即红（防两表分叉
         致服务端放行未审形状，或服务端拦掉已审形状）。
    腿C 在役已加载：在役门户件 mtime ≤ 在役进程启动时刻（文件新于进程＝进程仍跑旧码，
         与 tools/deploy-consistency-probe.sh D3 同口径），否则红。
  fail-closed：gov 不可达 / 拉取失败 / 缺件 / 规则对不上 ⇒ 一律红并点名，不静默放行。

用法：
  python3 tools/publish-live-surface-probe.py            # 人读摘要（末行=结论行）
  python3 tools/publish-live-surface-probe.py --json     # 机器可读
退出码：0=全绿；1=有红因（公网面实况与闸读数不一致 / 双真源漂移 / 在役未加载）；
        2=环境错误（gov 不可达、闸件或门户件缺件、rsync 失败）。
"""
import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(WS, "tools")
GATE = os.path.join(TOOLS, "publish-scrub-gate.py")
PORTAL = os.path.join(TOOLS, "af-jobs-portal.py")
ALLOWLIST = os.path.join(TOOLS, "publish-allowlist.json")
GOV_SSH = os.environ.get("GOV_SSH", "root@gov-host.invalid")
GOV_STATIC = os.environ.get("GOV_STATIC", "/opt/company/af-jobs/data/static")
GOV_PORTAL = os.environ.get("GOV_PORTAL", "/opt/company/af-jobs/af-jobs-portal.py")
# 拉回落点：$HOME/vgate-work（/tmp 配额有限，硬纪律见 publish-scrub-gate.py:selftest）
WORK = os.path.join(os.path.expanduser("~"), "vgate-work")


def _load(path, name):
    """按文件路径载入模块（本仓件名带连字符，不能直接 import）。"""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _patterns(compiled):
    return [p.pattern for p in compiled]


def run_pull(dest):
    """只读拉回在役 static/ 树（rsync over ssh；不写远端）。返回 (文件数, 错误或 None)。"""
    cmd = ["rsync", "-a", "--timeout=60", "-e",
           "ssh -o BatchMode=yes -o ConnectTimeout=10",
           f"{GOV_SSH}:{GOV_STATIC}/", f"{dest}/"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 0, f"rsync 异常: {e}"
    if r.returncode != 0:
        return 0, f"rsync rc={r.returncode}: {(r.stderr or '').strip()[:200]}"
    n = sum(len(fs) for _r, _d, fs in os.walk(dest))
    return n, None


def run_live_readings():
    """一次 ssh 取回三读数：在役门户件全文 / 该件 mtime / 在役进程启动时刻。"""
    script = (
        'f="' + GOV_PORTAL + '"\n'
        '[ -f "$f" ] || { echo MISSING_FILE; exit 0; }\n'
        'echo "---FILE---"; cat "$f"\n'
        'echo "---MTIME---"; stat -c %Y "$f"\n'
        'pid="$(pgrep -f "[p]ython3 af-jobs-portal.py" | head -1)"\n'
        'if [ -n "$pid" ]; then echo "---PROC---"; stat -c %Y "/proc/$pid";'
        ' else echo "---PROC---"; echo NOPROC; fi\n'
    )
    try:
        r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
                            GOV_SSH, script], capture_output=True, text=True, timeout=90)
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, f"ssh 异常: {e}"
    if r.returncode != 0:
        return None, f"ssh rc={r.returncode}: {(r.stderr or '').strip()[:200]}"
    out = r.stdout
    if "MISSING_FILE" in out:
        return None, f"在役门户件缺件 {GOV_PORTAL}"
    try:
        body = out.split("---FILE---", 1)[1].split("---MTIME---", 1)
        live_src = body[0]
        mtime = int(body[1].split("---PROC---", 1)[0].strip())
        proc = body[1].split("---PROC---", 1)[1].strip()
    except (IndexError, ValueError) as e:
        return None, f"在役读数解析失败: {e}"
    if proc == "NOPROC" or not proc.isdigit():
        return {"src": live_src, "mtime": mtime, "proc": None}, None
    return {"src": live_src, "mtime": mtime, "proc": int(proc)}, None


def main(argv=None):
    ap = argparse.ArgumentParser(description="在役公网静态面实况过闸 + 白名单双真源对账探针")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    args = ap.parse_args(argv)

    reds = []
    for p in (GATE, PORTAL):
        if not os.path.isfile(p):
            print(f"FATAL: 缺件 {p}", file=sys.stderr)
            return 2

    gate = _load(GATE, "publish_scrub_gate")
    portal = _load(PORTAL, "af_jobs_portal")
    gate_pat = _patterns(gate.PATH_OK)
    local_pat = _patterns(portal._STATIC_PATH_OK)

    # —— 腿B：发布端 ↔ 本地门户 白名单对账 ——
    if gate_pat != local_pat:
        reds.append("腿B红：发布端 PATH_OK ≠ 本地门户 _STATIC_PATH_OK（双真源漂移）"
                    f"\n  发布端={gate_pat}\n  本地={local_pat}")

    # —— 腿C/腿B续：在役门户件取回 ——
    live, err = run_live_readings()
    if err:
        print(f"FATAL: {err}", file=sys.stderr)
        return 2
    live_pat = None
    tmpdir = tempfile.mkdtemp(prefix="live-portal-", dir=WORK if os.path.isdir(WORK) else None)
    try:
        lp = os.path.join(tmpdir, "live-portal.py")
        with open(lp, "w", encoding="utf-8") as f:
            f.write(live["src"])
        try:
            live_mod = _load(lp, "live_af_jobs_portal")
            live_pat = _patterns(live_mod._STATIC_PATH_OK)
        except AttributeError:
            reds.append("腿B红：在役门户件无 _STATIC_PATH_OK（服务端形状白名单未在役生效）")
        except Exception as e:  # 在役件语法坏 → 对账不可做 = 红
            reds.append(f"腿B红：在役门户件取回后无法载入（{e}）")
        if live_pat is not None and live_pat != local_pat:
            reds.append("腿B红：在役门户 _STATIC_PATH_OK ≠ 本地门户 _STATIC_PATH_OK"
                        "（在役未加载修复／真源漂移）")
        if live["proc"] is None:
            reds.append("腿C红：在役门户进程不在位（公网门户宕机）")
        elif live["proc"] < live["mtime"]:
            reds.append(f"腿C红：在役门户件 mtime={live['mtime']} 晚于进程启动="
                        f"{live['proc']}——进程仍跑旧码（未加载修复）")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    # —— 腿A：在役 static/ 树只读拉回 + 同规则实况扫描 ——
    os.makedirs(WORK, exist_ok=True)
    dest = tempfile.mkdtemp(prefix="live-static-%d-" % os.getpid(), dir=WORK)
    try:
        n_files, err = run_pull(dest)
        if err:
            print(f"FATAL: {err}", file=sys.stderr)
            return 2
        al = gate.load_allowlist(ALLOWLIST)
        hits, errs, scanned, allowed_n = gate.scan_tree(dest, al, False)
        if errs:
            reds.append(f"腿A红：在役静态树 {len(errs)} 项结构问题（白名单外文件/读失败）"
                        f"：{errs[:5]}")
        if hits:
            reds.append(f"腿A红：在役静态树 {len(hits)} 项内容命中（未经脱敏件已在公网面）"
                        f"：{hits[:3]}")
        if scanned != n_files:
            reds.append(f"腿A红：扫描覆盖不全 scanned={scanned} ≠ 在册件数={n_files}"
                        "（有在役件未被闸覆盖）")
        info = {"live_files": n_files, "scanned": scanned, "hits": len(hits),
                "errors": len(errs), "allowlisted": allowed_n}
    finally:
        shutil.rmtree(dest, ignore_errors=True)

    verdict = "red" if reds else "ok"
    if args.json:
        print(json.dumps({"verdict": verdict, "at": time.strftime("%Y-%m-%d %H:%M:%S"),
                          **info, "reds": reds}, ensure_ascii=False, indent=1))
    else:
        for r in reds:
            print(r, file=sys.stderr)
        print(f"在役静态树：{info['live_files']} 件 / 闸实扫 {info['scanned']} 件 / "
              f"内容命中 {info['hits']} / 结构问题 {info['errors']} / "
              f"allowlist 豁免 {info['allowlisted']}；"
              f"白名单对账：发布端 {len(gate_pat)} 条 ≡ 本地门户 {len(local_pat)} 条 ≡ "
              f"在役门户 {len(live_pat) if live_pat else 0} 条")
    if reds:
        if not args.json:
            print(f"结论：红 {len(reds)} 项——公网面实况与脱敏闸读数不一致 / 双真源漂移 / 在役未加载")
        return 1
    if not args.json:
        print("结论：绿——在役公网静态树全部件过闸（形状白名单 + 内容模式），"
              "且发布端/本地门户/在役门户三面白名单一致、在役进程已加载")
    return 0


if __name__ == "__main__":
    sys.exit(main())
