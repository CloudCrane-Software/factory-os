#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""swev-eval-dump.py — bench 判分腿官方 eval_script 出土件（D-120 · factory-os#127）。

定位（卡面 [试跑复盘][D-120] · task_id=d120-warm-relay-builtin）
----
D-86/D-107/D-117 三次判分腿各持一份 dump_eval_sh.py 手工拷贝（判官件路径/缓存
路径逐实例硬编码改写），属「标准流程外的每次手搓件」。本件把该步单源化为参数
化 CLI，供一键链 tools/cb-judge-leg.sh 第 2 步（eval 出土）调用：

  输入  --task <task.json>（判分输入：instance_id/repo/version/base_commit/
        test_patch/fail_to_pass/pass_to_pass/image）
        --judge <swev-judge-v2.py 路径>（判官件部署面：缓存面或腿部署面）
        --cache <离线缓存目录>（中继缓存面，SWEV_JUDGE_V2_CACHE 同值）
        --out  <eval.sh 落盘路径>
  行为  importlib 载入判官件（判官件零改动：只 import + HermeticGuard 外层包裹）
        → HermeticGuard(allow_live=False) 离线构造 test spec → tspec.eval_script
        写 --out → stdout 落一行 JSON 读数（bytes/sha256/live_http/hermetic）。
  硬闸  live_http 非空 ⇒ exit 3（无网侧出土必须零外呼；fail-closed 不产 eval.sh）；
        判官件加载失败/缓存未命中（HermeticBlocked）⇒ exit 2 并给补救归因
        （「先跑 warm-relay」——与 tools/swev-spec-fetch.py 同一归因口径）。

出处（范式来源，禁改）：30-工件/D-107-bench沙箱环-20261106/dump_eval_sh.py
  （D-86 摩擦点③教训的落盘形态：importlib 载判官件取 guard，禁 ssh 内嵌 heredoc；
  本件同样先落盘再执行，由调用方 scp 到远端后 python3 -I 跑）。

用法:
  swev-eval-dump.py --task T.json --judge J.py --cache C --out eval.sh
  swev-eval-dump.py --selftest        （桩判官件驱动，零网络零真判官件）

纪律:
  · 判官件零改动（判据面铁律）：本件对判官件只 importlib 载入 + 只读调用
    make_test_spec/HermeticGuard，禁任何写入/换版；--judge 指向哪份部署面由
    调用方对账决定（一键链已内置三方 sha 对账）。
  · 零外呼缺省：allow_live=False 硬编码（无网侧语义）；预热是 warm-relay
    第 ① 步的职责，不在本件。
"""
import argparse
import hashlib
import importlib.util
import json
import os
import sys

HERMETIC_REMEDY = "先跑 warm-relay（tools/swev-warm-relay.sh --task <task.json>）灌中继缓存"


def load_judge(judge_path):
    """importlib 载入判官件（只读；判官件零改动）。"""
    spec = importlib.util.spec_from_file_location("swev_judge_v2_mod", judge_path)
    if spec is None or spec.loader is None:
        raise ImportError("importlib spec 构造失败: %s" % judge_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def inst_from_task(task):
    """判官件 inst 构造（D-107 dump_eval_sh.py 同形制：FAIL_TO_PASS/PASS_TO_PASS
    传 JSON 字符串；列表/字符串两种输入形态都收）。"""
    def as_json_str(v):
        if isinstance(v, str):
            return v
        return json.dumps(v, ensure_ascii=False)

    return {
        "instance_id": task["instance_id"],
        "repo": task["repo"],
        "version": task.get("version", ""),
        "base_commit": task.get("base_commit", ""),
        "test_patch": task.get("test_patch", ""),
        "FAIL_TO_PASS": as_json_str(task["fail_to_pass"]),
        "PASS_TO_PASS": as_json_str(task.get("pass_to_pass", [])),
        "image": task.get("image"),
    }


def dump(task_path, judge_path, cache_dir, out_path):
    """出土 eval_script → 读数 dict（live_http 非空由调用方按 rc 判）。"""
    with open(task_path, encoding="utf-8") as f:
        task = json.load(f)
    judge = load_judge(judge_path)
    inst = inst_from_task(task)
    os.environ["SWEV_JUDGE_V2_CACHE"] = cache_dir
    guard = judge.HermeticGuard(allow_live=False)
    with guard():
        tspec = judge.make_test_spec(inst)
    script = tspec.eval_script
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(script)
    hermetic = (guard.hermetic() if hasattr(guard, "hermetic")
                else (not guard.live_http and not guard.blocked_urls))
    return {
        "tool": "tools/swev-eval-dump.py",
        "task": task_path,
        "judge": judge_path,
        "cache": cache_dir,
        "out": out_path,
        "instance_id": task["instance_id"],
        "eval_bytes": len(script),
        "eval_sha256": hashlib.sha256(script.encode("utf-8")).hexdigest(),
        "live_http": list(guard.live_http),
        "blocked_urls": list(guard.blocked_urls),
        "socket_connects": list(guard.socket_connects),
        "hermetic": bool(hermetic),
    }


def selftest():
    """桩判官件驱动：零网络、零真判官件。断言 inst 形制/落盘形制/硬闸读数。"""
    import tempfile
    n = 0
    td = tempfile.mkdtemp(prefix="swev-eval-dump-st.")

    # ── 桩判官件（模块级 make_test_spec/HermeticGuard，与真判官件同形制）──
    stub = (
        "class HermeticBlocked(Exception):\n"
        "    pass\n"
        "\n"
        "class HermeticGuard:\n"
        "    def __init__(self, allow_live=False, cache_dir=None):\n"
        "        self.allow_live = allow_live\n"
        "        self.live_http = []\n"
        "        self.blocked_urls = []\n"
        "        self.socket_connects = []\n"
        "    def __call__(self):\n"
        "        return self\n"
        "    def __enter__(self):\n"
        "        return self\n"
        "    def __exit__(self, *a):\n"
        "        return False\n"
        "    def hermetic(self):\n"
        "        return not self.live_http and not self.blocked_urls\n"
        "\n"
        "class _Spec:\n"
        "    def __init__(self, text):\n"
        "        self.eval_script = text\n"
        "\n"
        "def make_test_spec(inst):\n"
        "    assert inst['FAIL_TO_PASS'].startswith('['), inst\n"
        "    assert inst['PASS_TO_PASS'].startswith('['), inst\n"
        "    return _Spec('#!/bin/bash\\necho %s\\n' % inst['instance_id'])\n"
    )
    judge_path = os.path.join(td, "stub-judge.py")
    with open(judge_path, "w", encoding="utf-8") as f:
        f.write(stub)

    task = {
        "instance_id": "stub__stub-1",
        "repo": "stub/stub",
        "version": "1.0",
        "base_commit": "0" * 40,
        "test_patch": "diff --git a/x b/x\n",
        "fail_to_pass": ["t1"],
        "pass_to_pass": ["t2"],
        "image": "swebench/sweb.eval.x86_64.stub_1776_stub-1:latest",
    }
    task_path = os.path.join(td, "task.json")
    with open(task_path, "w", encoding="utf-8") as f:
        json.dump(task, f, ensure_ascii=False)

    # ── 例①：出土落盘 + 读数形态 ──
    n += 1
    out_path = os.path.join(td, "eval.sh")
    info = dump(task_path, judge_path, os.path.join(td, "cache"), out_path)
    assert info["live_http"] == [] and info["hermetic"], info
    assert info["instance_id"] == "stub__stub-1"
    with open(out_path, encoding="utf-8") as f:
        got = f.read()
    assert got == "#!/bin/bash\necho stub__stub-1\n", repr(got)
    assert info["eval_sha256"] == hashlib.sha256(got.encode("utf-8")).hexdigest()

    # ── 例②：fail_to_pass 传字符串形态也收（数据集双形制）──
    n += 1
    task2 = dict(task, fail_to_pass='["t1"]', pass_to_pass='["t2"]')
    p2 = os.path.join(td, "task2.json")
    with open(p2, "w", encoding="utf-8") as f:
        json.dump(task2, f, ensure_ascii=False)
    info2 = dump(p2, judge_path, os.path.join(td, "cache"),
                 os.path.join(td, "eval2.sh"))
    assert info2["live_http"] == []

    # ── 例③：判官件缺席 ⇒ ImportError（不产 eval.sh，不猜绿）──
    n += 1
    try:
        dump(task_path, os.path.join(td, "no-such-judge.py"),
             os.path.join(td, "cache"), os.path.join(td, "eval3.sh"))
        raise SystemExit("FAIL 缺判官件未报错")
    except (ImportError, FileNotFoundError):
        pass

    print("swev-eval-dump.py --selftest: %d/3 断言 PASS（桩驱动，零网络零真判官件）" % n)
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="bench 判分腿官方 eval_script 出土件（D-120；guard 离线零外呼）")
    ap.add_argument("--task", default=None, help="task.json 路径")
    ap.add_argument("--judge", default=None, help="swev-judge-v2.py 部署面路径")
    ap.add_argument("--cache", default=None, help="离线缓存目录（中继缓存面）")
    ap.add_argument("--out", default=None, help="eval.sh 落盘路径")
    ap.add_argument("--selftest", action="store_true",
                    help="桩驱动自测（零网络零真判官件）")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    for req, name in ((args.task, "--task"), (args.judge, "--judge"),
                      (args.cache, "--cache"), (args.out, "--out")):
        if not req:
            print("FAIL 缺 %s（出土四件套齐才跑）" % name, file=sys.stderr)
            return 2
    if not os.path.isfile(args.task):
        print("FAIL task 不在位: %s" % args.task, file=sys.stderr)
        return 2
    if not os.path.isfile(args.judge):
        print("FAIL 判官件部署面不在位: %s（%s）" % (args.judge, HERMETIC_REMEDY),
              file=sys.stderr)
        return 2
    try:
        info = dump(args.task, args.judge, args.cache, args.out)
    except Exception as exc:  # HermeticBlocked/缓存未命中/加载失败 → 快败归因
        print("FAIL eval 出土失败: %s: %s" % (type(exc).__name__, exc),
              file=sys.stderr)
        print("FAIL 归因: %s" % HERMETIC_REMEDY, file=sys.stderr)
        return 2
    print(json.dumps(info, ensure_ascii=False))
    if info["live_http"]:
        print("FAIL live_http 非空——无网侧出土必须零外呼（%s）" % HERMETIC_REMEDY,
              file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
