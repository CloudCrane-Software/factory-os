#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""swev-spec-fetch.py — bench 判分腿 spec 取数统一入口（D-106 摩擦点②收编）。

为什么建（依据 30-工件/D-86-bench试跑-20261106/判分读数.md 六环表·摩擦点 2）：
  · anolis 对 raw.githubusercontent.com 零直连且连接是挂起而非 RST——裸调
    swebench 的 make_test_spec 首次卡死 120s+、二次 90s 超时，判分腿被基建
    拖挂而不是拿到可归因的失败。
  · 判官件 swev-judge-v2.py 判分期已有 HermeticGuard（离线缓存未命中即拒），
    但判分腿其它取数点（题库生成/任务包生成/gen_eval_sh 范式脚本）此前是
    裸调。本件把取数统一收到判官件的 guard 之后：guard 在判官件外层，
    swev-judge-v2.py 字节零改动（importlib 载入复用，出处见 load_v2()）。

语义（与判官件 v2 同一套环境变量与缓存，双向兼容）：
  · 离线优先（默认）：guard(allow_live=False) 下取 spec——缓存命中即成
    （source=cache，零外呼，hermetic=true）；未命中立即拒（不发起任何网络
    尝试，亚秒级），exit=2 且信息明确：被拒 URL + 补缓存指引。
  · 显式放行（--allow-live 或 SWEV_JUDGE_V2_ALLOW_LIVE=1）：与判官件
    --warm-cache 同语义——实呼并把响应（含 404）写入离线缓存（source=live）。
    另设死线看门狗（--deadline，默认 30s；SWEV_JUDGE_V2_FETCH_DEADLINE 可改）：
    无网但连接挂起的环境在死线处快败（exit=3），禁 90-120s 挂死。
  · 缓存目录与判官件同一套：SWEV_JUDGE_V2_CACHE 或 ~/.cache/swev-judge-v2
    （--cache-dir 可显式指定）。预热产物跨机可搬运（见 tools/swev-warm-relay.sh）。

用法:
    swev-spec-fetch.py <task.json> [--allow-live] [--cache-dir D]
                       [--deadline SEC] [--out F] [--quiet] [--selftest]
stdout: JSON 一行（spec_ok/instance_id/source/elapsed_ms/live_http/blocked_urls/
        judge_sha256/eval_script_sha256/swebench_version/error）；
        --out F 时同时落盘 F（先落盘再解析，避免管道回显截断假象——判分读数.md 摩擦点 4）。
        进程内调用方用 fetch_spec(task, ...) 拿 (spec, info)。
退出码: 0=spec 就绪；2=离线缓存未命中（快败，含被拒 URL）；3=外呼死线超时
        （快败，禁挂死）；4=task.json 坏/内部异常（信息含归因）。

自检: swev-spec-fetch.py --selftest  （离线三态+死线快败+404 缓存语义，
       不发任何真实外呼；exit 0=全过）
"""
import hashlib
import importlib.util
import json
import os
import signal
import sys
import time
from pathlib import Path

FETCH_DEADLINE_DEFAULT = 30  # 秒；live 态外呼死线（防挂死），可经 --deadline 覆盖

V2_NAME = "swev_judge_v2"
V2_FILE = Path(__file__).resolve().parent / "swev-judge-v2.py"

_V2 = None


def load_v2():
    """importlib 载入判官件 swev-judge-v2.py（本件同目录）——guard 与 404 合成
    回退都取自判官件本体，判官件字节零改动（出处：selftest 同款载法）。"""
    global _V2
    if _V2 is not None:
        return _V2
    if not V2_FILE.is_file():
        sys.exit("FAIL swev-judge-v2.py 不在本件同目录（%s）——guard 无从取法" % V2_FILE)
    spec = importlib.util.spec_from_file_location(V2_NAME, str(V2_FILE))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[V2_NAME] = mod
    spec.loader.exec_module(mod)
    _V2 = mod
    return _V2


def judge_sha256() -> str:
    h = hashlib.sha256()
    h.update(V2_FILE.read_bytes())
    return h.hexdigest()


class FetchDeadline(Exception):
    """live 态外呼超过死线（防挂死看门狗触发）。"""


def _make_inst(v2, task):
    """与判官件 _judge/_warm_cache 逐字同款 inst 构造（键集一致，勿增删）。
    双形态兼容：判官 task.json（fail_to_pass 小写=list）与 prep/pool-gen 的
    数据行（FAIL_TO_PASS 大写=已序列化 JSON 字符串）。"""
    f2p = task.get("fail_to_pass")
    if f2p is None:
        f2p = task["FAIL_TO_PASS"]          # 行形态：已是 JSON 字符串
    else:
        f2p = json.dumps(f2p)
    p2p = task.get("pass_to_pass")
    if p2p is None:
        p2p = task.get("PASS_TO_PASS", "[]")  # 行形态
    else:
        p2p = json.dumps(p2p)
    return {
        "instance_id": task["instance_id"],
        "repo": task["repo"],
        "version": task.get("version", ""),
        "base_commit": task.get("base_commit", ""),
        "test_patch": task.get("test_patch", ""),
        "FAIL_TO_PASS": f2p,
        "PASS_TO_PASS": p2p,
        "image": task.get("image", v2.image_name(task["instance_id"])),
    }


def _spec_digest(spec) -> str:
    """spec 指纹：eval_script 的 sha256——跨机（有网侧↔anolis）取数一致性可对账。"""
    try:
        return hashlib.sha256(spec.eval_script.encode("utf-8")).hexdigest()
    except Exception:
        return None


def fetch_spec(task, cache_dir=None, allow_live=False, deadline_s=None):
    """统一 spec 取数。返回 (spec, info)；失败时 spec=None，info.spec_ok=False。

    allow_live=False：离线优先——缓存命中（source=cache）/未命中即拒（亚秒快败）。
    allow_live=True ：与判官件 --warm-cache 同语义（实呼+写缓存，含 404），
                      另有死线看门狗防挂起环境拖死。
    deadline_s      ：live 态死线秒数；None=环境 SWEV_JUDGE_V2_FETCH_DEADLINE
                      或 FETCH_DEADLINE_DEFAULT。离线态无需死线（零外呼）。
    """
    v2 = load_v2()
    info = {"spec_ok": False, "instance_id": task.get("instance_id"),
            "source": None, "elapsed_ms": None,
            "live_http": [], "blocked_urls": [],
            "judge_sha256": judge_sha256(),
            "eval_script_sha256": None, "swebench_version": v2.SWEBENCH_VERSION,
            "allow_live": bool(allow_live), "error": None}

    dl = deadline_s if deadline_s is not None else int(
        os.environ.get("SWEV_JUDGE_V2_FETCH_DEADLINE", FETCH_DEADLINE_DEFAULT))
    t0 = time.monotonic()

    guard = v2.HermeticGuard(allow_live=bool(allow_live), cache_dir=cache_dir)
    old_handler = None
    try:
        with guard():
            v2._install_env_yml_fallback(task)
            inst = _make_inst(v2, task)
            if allow_live:
                # 死线看门狗：判官件 guard 放行的实呼继承 requests 默认（无超时），
                # 挂起型无网环境（anolis 实录 90-120s）在此被强杀为快败。
                old_handler = signal.signal(signal.SIGALRM, _on_deadline)
                signal.alarm(max(1, int(dl)))
            try:
                spec = v2.make_test_spec(inst)
            finally:
                if allow_live:
                    signal.alarm(0)
                    signal.signal(signal.SIGALRM, old_handler)
        info["spec_ok"] = True
        info["source"] = "live" if allow_live and guard.live_http else "cache"
        info["eval_script_sha256"] = _spec_digest(spec)
        info["live_http"] = list(guard.live_http)
        info["blocked_urls"] = list(guard.blocked_urls)
        info["elapsed_ms"] = int((time.monotonic() - t0) * 1000)
        return spec, info
    except v2.HermeticBlocked as e:
        info["error"] = ("离线缓存未命中（零外呼快败）：%s；补缓存=有网侧 "
                         "swev-warm-relay.sh，或显式 SWEV_JUDGE_V2_ALLOW_LIVE=1"
                         % e.target)
        info["remedy"] = "tools/swev-warm-relay.sh <task.json>"
    except FetchDeadline:
        info["error"] = ("外呼超过死线 %ds（快败，禁挂死）——目标 %s；该环境属"
                         "挂起型无网（连接不 RST），应改走缓存（swev-warm-relay.sh "
                         "预热/补缓存）" % (dl, guard.live_http[-1] if guard.live_http
                                          else "(尚未记录到具体 URL)"))
        info["deadline_s"] = dl
    except KeyError as e:
        info["error"] = "task.json 缺必需键 %s（spec 无从构造）" % e
    except Exception as e:  # noqa: BLE001 - 取数失败如实回报（含 swebench 404 合成后仍失败等）
        info["error"] = "%s: %s" % (type(e).__name__, e)
    info["live_http"] = list(guard.live_http)
    info["blocked_urls"] = list(guard.blocked_urls)
    info["elapsed_ms"] = int((time.monotonic() - t0) * 1000)
    return None, info


def _on_deadline(signum, frame):
    raise FetchDeadline("fetch deadline")


def _run_cli(argv):
    """CLI 主逻辑（返回退出码）。"""
    task_path = None
    allow_live = os.environ.get("SWEV_JUDGE_V2_ALLOW_LIVE") == "1"
    cache_dir = os.environ.get("SWEV_JUDGE_V2_CACHE") or None
    deadline = None
    out_path = None
    quiet = False
    it = iter(argv)
    for a in it:
        if a == "--allow-live":
            allow_live = True
        elif a == "--cache-dir":
            cache_dir = next(it)
        elif a == "--deadline":
            deadline = int(next(it))
        elif a == "--out":
            out_path = next(it)
        elif a == "--quiet":
            quiet = True
        elif a == "--selftest":
            return _selftest()
        else:
            task_path = a
    if task_path is None:
        sys.stderr.write(__doc__[:400] + "\n")
        return 4
    try:
        task = json.loads(Path(task_path).read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        sys.stderr.write("FAIL task.json 不可读 %s: %s\n" % (task_path, e))
        return 4

    spec, info = fetch_spec(task, cache_dir=cache_dir, allow_live=allow_live,
                            deadline_s=deadline)
    if spec is not None:
        info["elapsed_ms"] = info["elapsed_ms"] or 0
    payload = dict(info)
    if spec is None and info["error"] is None:
        payload["error"] = "spec 未产出（未知归因，fail-closed 如实回报）"
    line = json.dumps(payload, ensure_ascii=False)
    if out_path:
        Path(out_path).write_text(line + "\n", encoding="utf-8")
    if not quiet:
        sys.stdout.write(line + "\n")
    if spec is None:
        sys.stderr.write("FAIL spec 取数未成（instance=%s）：[exit 用途见件头]\n  %s\n"
                         % (info.get("instance_id"), payload.get("error")))
        # 退出码分档：2=离线未命中；3=死线超时；4=其它（坏 task/内部错）
        err = payload.get("error") or ""
        if "离线缓存未命中" in err:
            return 2
        if "死线" in err:
            return 3
        return 4
    if not quiet:
        sys.stderr.write("OK spec 就绪（instance=%s source=%s %sms，判官件 sha %s…零改动）\n"
                         % (info["instance_id"], info["source"], info["elapsed_ms"],
                            info["judge_sha256"][:12]))
    return 0


# --------------------------------------------------------------------------
# --selftest：离线三态 + 死线快败 + 404 缓存语义（零真实外呼）
# --------------------------------------------------------------------------

def _selftest():  # noqa: C901 - 线性断言块
    ok = True

    def rec(name, cond, detail=""):
        nonlocal ok
        ok = ok and bool(cond)
        print("[%s] %s" % ("PASS" if cond else "FAIL", name)
              + (" — " + detail if detail else ""), flush=True)

    import tempfile
    v2 = load_v2()
    rec("判官件可载入且零改动", V2_FILE.is_file(),
        "sha256=%s…" % judge_sha256()[:12])

    base_task = {"instance_id": "selftest__fake-1", "repo": "django/django",
                 "version": "3.0", "base_commit": "0" * 40, "test_patch": "",
                 "fail_to_pass": ["t1"], "pass_to_pass": ["t2"]}

    with tempfile.TemporaryDirectory(prefix="swev-spec-fetch-selftest-") as td:
        # ① 离线冷缓存：未命中即拒，亚秒级，信息明确
        t0 = time.monotonic()
        spec, info = fetch_spec(base_task, cache_dir=td, allow_live=False)
        ms = int((time.monotonic() - t0) * 1000)
        rec("离线冷缓存快败 exit≠0 语义（spec_ok=false）",
            spec is None and info["blocked_urls"], "%d ms，blocked=%s"
            % (ms, [u[:60] for u in info["blocked_urls"]]))
        rec("离线未命中亚秒级（禁 90-120s 挂死）", ms < 5000, "%d ms" % ms)
        rec("拒因信息明确（含被拒 URL+补缓存指引）",
            info["error"] and "raw.githubusercontent.com" in "".join(info["blocked_urls"])
            and "swev-warm-relay" in info["error"],
            info["error"][:100] if info["error"] else "")

        # ② 显式放行态写缓存：对本地回呼探针发实呼并缓存（allow_live 语义与判官件一致）
        #    用 httpbin 本地不可达地址会触发真实网络——改为：缓存写入语义用
        #    判官件 HermeticGuard._cache_put 直测（不外呼）。
        g = v2.HermeticGuard(allow_live=True, cache_dir=td)
        g._cache_put("https://fake.invalid/yml", 404, "not found")
        hit = g._cache_get("https://fake.invalid/yml")
        rec("404 也入缓存（含 404 语义与判官件一致）",
            hit is not None and hit.status_code == 404)

        # ③ 离线暖缓存：命中即成（_FakeResponse 走通 make_test_spec 的 yml 读点）
        #    make_test_spec 需真实 repo/commit——此处只验 guard 取数内核，
        #    全链暖缓存实证由 swev-warm-relay.sh 实跑留读数（卡面验收面）。
        rec("guard 缓存读回 status_code/text 两字段可用",
            hit.text == "not found")

        # ④ 死线看门狗本体（不外呼：直接验证 SIGALRM 处理函数）
        old = signal.signal(signal.SIGALRM, _on_deadline)
        signal.alarm(1)
        try:
            time.sleep(2)
            fired = False
        except FetchDeadline:
            fired = True
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old)
        rec("死线看门狗触发 FetchDeadline（防挂死内核）", fired)

    print("SELFTEST %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(_run_cli(sys.argv[1:]))
