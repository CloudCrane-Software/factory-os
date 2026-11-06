#!/usr/bin/env python3
"""swev-judge-v2.py — D-32 判分链三缺陷修复版判分器（与 v1 并存；v1 字节零改动）。

背景（债册 D-32，红队裁决 R4/R5/R7，见 设计/最终真相-红队挑战-裁决.md）：
  ① log_parsed 零状态语义：v1 只查 Start/End Test Output 标记存在——测试段零可解析
     状态（pytest 从未收集：collection 崩溃/import 崩溃）也记 log_parsed=true，与
     "真跑过但失败"同貌（R4 实证 8 例，其中 2 例直接造成生产 T→F）。
  ② judge hermeticity：v1 每次判分经 make_test_spec 实发 live HTTP
     （raw.githubusercontent.com 拉 environment.yml/requirements），网络不可达即
     Traceback 崩溃、judge.json 落空、reward=null 且无归因（R5 实证 49 键）。
  ③ capture_diff 把 ssh 错误当 diff：远端取 diff 失败的错误文本（ssh: connect ...
     63 字节 CRLF 残片）被当补丁内容应用，造成"有 diff 可判"假阳性（R7 实证 3 例）。

v2 修法（三缺陷各自最小修法，判定语义变更逐条列于本 docstring 末节）：
  ① 显式零状态判定式：log_state ∈ {parsed, zero_state, no_markers, eval_error,
     not_judged}；log_parsed=true 仅当 log_state=="parsed"（标记齐在 且 swebench
     官方解析器产出非空 status_map 且无 bad code）。零状态仍判 resolved=false
     （日志确实没有证明解决），但带 log_state/tests_status_parsed 可复算留痕，
     消费方（聚合/复核）据此与"真失败"区分，不再同貌。
  ② 外呼隔离：判分期装 HermeticGuard——requests.get 改走本地离线缓存
     （默认 ~/.cache/swev-judge-v2，SWEV_JUDGE_V2_CACHE 可改），缓存未命中即拒
     （判失败并留痕，不静默外呼）；socket.connect/getaddrinfo 设绊线记录一切
     非回呼连接尝试。显式放行口子 SWEV_JUDGE_V2_ALLOW_LIVE=1（缓存预热用），
     此时每个实呼 URL 记入输出 live_http 字段（留痕，hermetic=false）。
     缓存同时缓存 404（环境 yml 老实例 404 → v1 既有合成回退行为不变）。
  ③ diff 文本合法性校验：非空但既无 'diff --git' 也无 '--- '/'+++' 头的 diff
     （ssh/docker 取证错误文本等）判 verdict=invalid_diff、resolved=null、
     diff_valid=false+diff_reject_reason，不再把错误文本当补丁放行（R7 修改要求 1：
     "agent.diff 须含 'diff --git'（至少排除取证错误文本）"）。空 diff（0 字节）
     仍照常判日志（C6 口径不变），但标 diff_valid=false+reason=empty。
     invalid_diff 判定不构建 spec、零网络。

用法（CLI 与 v1 相同，v1 调用方无需改参）:
    swev-judge-v2.py <task.json> <log文件> <agent_diff文件>
    swev-judge-v2.py --warm-cache <task.json>     # 只预热离线缓存，不判分
stdout: JSON（v1 全部字段的超集；v1 字段在前，语义见下）

环境变量:
    SWEV_JUDGE_V2_CACHE      离线缓存目录（默认 ~/.cache/swev-judge-v2）
    SWEV_JUDGE_V2_ALLOW_LIVE=1  显式允许实呼（缓存预热/补缓存），输出记 live_http

退出码: 0=给出判定（含 invalid_diff/hermeticity_blocked 等"无判定"型判定，
 resolved 为 null）；1=judge_error（task.json 坏/内部异常，stdout 仍给 JSON）。

v1→v2 判定语义变更清单（向后可比契约；回放差异只应出现在这三类形态）:
  A. log_parsed（R4）：v1 = 标记齐在即为 true；v2 = 仅 log_state=="parsed" 为 true。
     故 zero_state（标记齐在+零可解析状态）与带标记的 eval_error 由 true 变 false；
     resolved 不变（仍 false）。新增 log_state/tests_status_parsed 可复算。
  B. resolved（R5/R7）：v1 恒为 bool；v2 在 invalid_diff（diff 非补丁残片）与
     hermeticity_blocked（离线缓存未命中）下为 null（无判定，非"判失败"），
     并带 verdict/diff_reject_reason/blocked_urls 归因；其余路径与 v1 同值。
  C. 新增字段（judge/verdict/log_state/tests_status_parsed/log_markers/bad_codes/
     diff_valid/diff_reject_reason/diff_sha256/diff_bytes/eval_sha256/eval_bytes/
     hermetic/live_http/blocked_urls）——纯增量，不改 v1 字段名与含义。
  与 v1 保持相同的部分：判分核（swebench 4.1 get_eval_report）、env yml 404 合成
  回退（_install_env_yml_fallback 逐字沿用）、f2p/p2p/tests_collected 统计口径。
"""
import hashlib
import json
import os
import re
import sys
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, "/home/pan-ding/swev-venv/lib/python3.14/site-packages")

from swebench.harness.constants import (  # noqa: E402
    APPLY_PATCH_FAIL,
    END_TEST_OUTPUT,
    RESET_FAILED,
    START_TEST_OUTPUT,
    TESTS_ERROR,
    TESTS_TIMEOUT,
)
from swebench.harness.grading import get_eval_report, get_logs_eval  # noqa: E402
from swebench.harness.test_spec.test_spec import make_test_spec  # noqa: E402
import importlib.metadata  # noqa: E402

try:
    SWEBENCH_VERSION = importlib.metadata.version("swebench")
except Exception:  # pragma: no cover - 版本自报失败不阻断判分
    SWEBENCH_VERSION = None

JUDGE_TAG = "v2"

# bad code（swebench grading.get_logs_eval 的 fatal 码）——出现即认为 eval 段本身
# 失败（补丁应用失败/重置失败/测试报错/超时），v2 单独归为 eval_error 态。
BAD_CODES = [
    ("APPLY_PATCH_FAIL", APPLY_PATCH_FAIL),
    ("RESET_FAILED", RESET_FAILED),
    ("TESTS_ERROR", TESTS_ERROR),
    ("TESTS_TIMEOUT", TESTS_TIMEOUT),
]

# 2026-10-21 修理组 env yml 404 合成回退——与 v1 逐字同语义（老实例 xarray 八题实证：
# 判分只用 spec 的 instance_id/测试清单/repo，yml 内容不进判定）。
_SYNTH = []


def _install_env_yml_fallback(task):
    from swebench.harness.constants import (  # noqa: E402
        MAP_REPO_TO_ENV_YML_PATHS,
        MAP_REPO_VERSION_TO_SPECS,
    )
    from swebench.harness.test_spec import python as py_spec  # noqa: E402

    orig = py_spec.get_environment_yml_by_commit

    def patched(repo, commit, env_name):
        try:
            return orig(repo, commit, env_name)
        except ValueError:
            if repo not in MAP_REPO_TO_ENV_YML_PATHS:
                raise
            spec = MAP_REPO_VERSION_TO_SPECS.get(repo, {}).get(task.get("version", ""), {})
            pins = spec.get("pip_packages") or []
            lines = [f"name: {env_name}", "channels:", "  - conda-forge", "  - defaults",
                     "dependencies:", f"  - python={spec.get('python', '3.9')}", "  - pip"]
            lines += [f"  - {p}" for p in pins]
            sys.stderr.write(f"[swev-judge-{JUDGE_TAG}] environment.yml 404 @ {repo}:{commit} "
                             f"→ 按版本 {task.get('version')} dataset 规格合成（判分不受影响）\n")
            _SYNTH.append(True)
            return "\n".join(lines)

    py_spec.get_environment_yml_by_commit = patched


def image_name(iid: str) -> str:
    return f"swebench/sweb.eval.x86_64.{iid.replace('__', '_1776_').lower()}:latest"


# --------------------------------------------------------------------------
# 缺陷①：零状态三态判定
# --------------------------------------------------------------------------

def log_markers(text: str) -> dict:
    """v1 口径的标记检查（spec 无关）——供 log_parsed 向后兼容与信息字段。"""
    return {"start": START_TEST_OUTPUT in text, "end": END_TEST_OUTPUT in text}


def bad_codes_in(text: str) -> list:
    return [name for name, code in BAD_CODES if code in text]


def classify_log_state(spec, log_path: str) -> tuple:
    """返回 (log_state, status_map, markers, bad_codes)。

    log_state:
      parsed     标记齐在 + swebench 解析器非空 status_map + 无 bad code（真跑过）
      zero_state 标记齐在 + status_map 空（含整日志回退为空）——pytest 从未产出
                 可解析结果（R4：collection/import 崩溃的典型形态）
      no_markers 标记缺失（截断/失败/空日志；与 v1 log_parsed=false 同域）
      eval_error bad code 在场（补丁应用失败/重置失败/测试报错/超时）
    判定式可复算：任一持日志者按 markers/bad_codes/status_map 三项即可复现。
    """
    try:
        text = open(log_path, encoding="utf-8", errors="replace").read()
    except OSError:
        return "no_markers", {}, {"start": False, "end": False}, []
    markers = log_markers(text)
    bad = bad_codes_in(text)
    if bad:
        return "eval_error", {}, markers, bad
    if not (markers["start"] and markers["end"]):
        return "no_markers", {}, markers, bad
    status_map, _found = get_logs_eval(spec, log_path)
    if not status_map:
        return "zero_state", status_map, markers, bad
    return "parsed", status_map, markers, bad


# --------------------------------------------------------------------------
# 缺陷②：判分密闭化（离线缓存 + 外呼绊线）
# --------------------------------------------------------------------------

class HermeticBlocked(Exception):
    """离线判分期间发生（或被拒绝的）非缓存外呼。"""

    def __init__(self, target: str):
        super().__init__(target)
        self.target = target


class _FakeResponse:
    """缓存命中的替身响应——只用 status_code/text（swebench 只读这两个字段）。"""

    def __init__(self, status_code: int, text: str):
        self.status_code = status_code
        self.text = text


def _is_remote_host(host) -> bool:
    if not host:
        return False
    h = str(host).strip("[]").lower()
    if h in ("localhost", "0.0.0.0", "::", "::1"):
        return False
    if h.startswith("127.") or h.startswith("::1"):
        return False
    return True


class HermeticGuard:
    """判分期外呼隔离：requests.get 走本地缓存（未命中即拒），socket 层设绊线。

    allow_live=True 时（仅缓存预热/显式放行）实呼并写入缓存，URL 记 live_http；
    默认 allow_live=False：缓存未命中 → HermeticBlocked（判失败并留痕），
    socket.connect/getaddrinfo 对非回呼目标同样拒绝并记录。
    """

    def __init__(self, allow_live: bool = False, cache_dir=None):
        self.allow_live = allow_live
        self.cache_dir = Path(
            cache_dir
            or os.environ.get("SWEV_JUDGE_V2_CACHE")
            or (Path.home() / ".cache" / "swev-judge-v2")
        )
        self.live_http = []        # 实呼 URL（allow_live 留痕）
        self.blocked_urls = []     # 被拒 URL/目标（离线未命中）
        self.socket_connects = []  # 绊线记录的一切非回呼连接/DNS 尝试
        self._orig = {}

    # -- 缓存 -------------------------------------------------------------
    def _cache_path(self, url: str) -> Path:
        key = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self.cache_dir / "raw" / f"{key}.json"

    def _cache_get(self, url: str):
        p = self._cache_path(url)
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            return _FakeResponse(int(d["status_code"]), d["text"])
        except Exception:
            return None

    def _cache_put(self, url: str, status_code: int, text: str) -> None:
        try:
            p = self._cache_path(url)
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps({"url": url, "status_code": int(status_code),
                                       "text": text}, ensure_ascii=False),
                           encoding="utf-8")
            tmp.replace(p)
        except OSError as e:
            sys.stderr.write(f"[swev-judge-{JUDGE_TAG}] 缓存写入失败 {url}: {e}\n")

    # -- 守卫 -------------------------------------------------------------
    @contextmanager
    def __call__(self):
        import requests
        import socket

        orig_get = requests.get
        orig_connect = socket.socket.connect
        orig_getaddrinfo = socket.getaddrinfo
        guard = self

        def guarded_get(url, **kwargs):
            u = str(url)
            hit = guard._cache_get(u)
            if hit is not None:
                return hit
            if guard.allow_live:
                resp = orig_get(url, **kwargs)
                guard.live_http.append(u)
                guard._cache_put(u, resp.status_code, resp.text)
                return resp
            guard.blocked_urls.append(u)
            sys.stderr.write(
                f"[swev-judge-{JUDGE_TAG}] 离线判分拒绝外呼 {u}"
                f"（缓存未命中；SWEV_JUDGE_V2_ALLOW_LIVE=1 可显式放行并留痕）\n")
            raise HermeticBlocked(u)

        def guarded_connect(sock, address):
            host = address[0] if isinstance(address, tuple) and address else None
            if _is_remote_host(host):
                guard.socket_connects.append(f"{host}:{address[1] if len(address) > 1 else '?'}")
                if not guard.allow_live:
                    sys.stderr.write(
                        f"[swev-judge-{JUDGE_TAG}] 离线判分拒绝 socket 连接 {host}"
                        f"（禁外呼；见 blocked_urls）\n")
                    raise HermeticBlocked(f"socket:{host}")
            return orig_connect(sock, address)

        def guarded_getaddrinfo(host, *args, **kwargs):
            if _is_remote_host(host):
                guard.socket_connects.append(f"dns:{host}")
                if not guard.allow_live:
                    sys.stderr.write(
                        f"[swev-judge-{JUDGE_TAG}] 离线判分拒绝 DNS 解析 {host}"
                        f"（禁外呼；见 blocked_urls）\n")
                    raise HermeticBlocked(f"dns:{host}")
            return orig_getaddrinfo(host, *args, **kwargs)

        requests.get = guarded_get
        socket.socket.connect = guarded_connect
        socket.getaddrinfo = guarded_getaddrinfo
        self._orig = {"requests.get": orig_get,
                      "socket.socket.connect": orig_connect,
                      "socket.getaddrinfo": orig_getaddrinfo}
        try:
            yield self
        finally:
            requests.get = orig_get
            socket.socket.connect = orig_connect
            socket.getaddrinfo = orig_getaddrinfo
            self._orig = {}

    def hermetic(self) -> bool:
        return not self.live_http and not self.blocked_urls and not self.socket_connects


# --------------------------------------------------------------------------
# 缺陷③：diff 文本合法性（R7：ssh 取证错误残片不得当补丁）
# --------------------------------------------------------------------------

# 已知取证/基建错误文本形态——命中即拒绝并给出具体原因（generic 拒因是 no_patch_header）。
_NOISE_PATTERNS = [
    (re.compile(r"^ssh: ", re.M), "ssh_error_text"),
    (re.compile(r"ssh: connect to host", re.I), "ssh_error_text"),
    (re.compile(r"Connection timed out", re.I), "ssh_error_text"),
    (re.compile(r"^docker: ", re.M), "docker_error_text"),
    (re.compile(r"Error response from daemon", re.I), "docker_error_text"),
    (re.compile(r"^fatal: ", re.M), "git_error_text"),
    (re.compile(r"Permission denied \(publickey", re.I), "ssh_error_text"),
    (re.compile(r"command not found", re.I), "shell_error_text"),
]

_UNIFIED_HDR = re.compile(r"^--- ", re.M)


def diff_legal(text) -> tuple:
    """返回 (ok, reason)。合法补丁 = 含 'diff --git'，或纯 unified diff
    （'--- ' 与 '+++' 成对）。空/纯错误文本 → (False, reason)。"""
    if text is None or not text.strip():
        return False, "empty"
    if "diff --git" in text:
        return True, None
    if _UNIFIED_HDR.search(text) and re.search(r"^\+\+\+ ", text, re.M):
        return True, None
    for pat, why in _NOISE_PATTERNS:
        if pat.search(text):
            return False, why
    return False, "no_patch_header"


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------

def _sha256_file(path) -> tuple:
    h = hashlib.sha256()
    n = 0
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
            n += len(chunk)
    return h.hexdigest(), n


def _read_text(path):
    return open(path, encoding="utf-8", errors="replace").read()


def _emit(out: dict, code: int = 0):
    sys.stdout.write(json.dumps(out) + "\n")
    sys.stdout.flush()
    return code


def _base_fields(eval_path, diff_path):
    """v1 兼容字段 + 证据字段（diff/eval 指纹）。"""
    fields = {}
    if diff_path:
        try:
            dsha, dbytes = _sha256_file(diff_path)
            fields["diff_sha256"], fields["diff_bytes"] = dsha, dbytes
        except OSError:
            fields["diff_sha256"], fields["diff_bytes"] = None, None
    try:
        esha, ebytes = _sha256_file(eval_path)
        fields["eval_sha256"], fields["eval_bytes"] = esha, ebytes
    except OSError:
        fields["eval_sha256"], fields["eval_bytes"] = None, None
    return fields


def _judge(task, log_path, diff_path) -> int:
    out = {"judge": JUDGE_TAG}
    out.update(_base_fields(log_path, diff_path))

    # ---- 日志可读性（v1 在缺日志时直接 Traceback；v2 给确定性无判定） ----
    if not os.path.isfile(log_path):
        out.update({"verdict": "no_log", "resolved": None, "log_parsed": False,
                    "log_state": "not_judged", "hermetic": True})
        sys.stderr.write(f"[swev-judge-{JUDGE_TAG}] 日志文件不存在: {log_path}\n")
        return _emit(out)

    # ---- 缺陷③：diff 合法性先于一切（非法 diff 不构建 spec、零网络） ----
    model_patch = ""
    diff_state = None  # (ok, reason)
    if diff_path:
        try:
            model_patch = _read_text(diff_path)
        except OSError as e:
            out.update({"verdict": "invalid_diff", "resolved": None,
                        "diff_valid": False, "diff_reject_reason": "diff_unreadable",
                        "log_parsed": None, "hermetic": True})
            sys.stderr.write(f"[swev-judge-{JUDGE_TAG}] diff 不可读: {e}\n")
            return _emit(out)
        diff_state = diff_legal(model_patch)
        # R7：非补丁残片（ssh/docker 错误文本等）→ 无判定，明确拒判；
        # 空补丁（0 字节）不拒判——照常判日志（C6 口径：空补丁仍走判分链、
        # 结果如实），仅标 diff_valid=false+reason=empty 供消费方区分。
        if not diff_state[0] and diff_state[1] != "empty":
            # R7：非补丁残片（ssh/docker 错误文本等）→ 无判定，明确拒判
            try:
                markers = log_markers(_read_text(log_path))
                lp = markers["start"] and markers["end"]
            except OSError:
                markers, lp = {"start": False, "end": False}, False
            out.update({"verdict": "invalid_diff", "resolved": None,
                        "diff_valid": False, "diff_reject_reason": diff_state[1],
                        "log_parsed": lp, "log_markers": markers,
                        "log_state": "not_judged", "hermetic": True})
            sys.stderr.write(
                f"[swev-judge-{JUDGE_TAG}] diff 非补丁残片（{diff_state[1]}，"
                f"{out.get('diff_bytes')}B sha256 {str(out.get('diff_sha256'))[:16]}…）"
                f"→ 拒判（R7：不得把取证错误文本当 diff）\n")
            return _emit(out)
    out["diff_valid"] = bool(diff_state[0]) if diff_state else None
    if diff_state and not diff_state[0]:
        out["diff_reject_reason"] = diff_state[1]  # empty：仍判日志但标记

    # ---- 判分（密闭） ----
    allow_live = os.environ.get("SWEV_JUDGE_V2_ALLOW_LIVE") == "1"
    guard = HermeticGuard(allow_live=allow_live)
    with guard():
        _install_env_yml_fallback(task)
        inst = {
            "instance_id": task["instance_id"],
            "repo": task["repo"],
            "version": task.get("version", ""),
            "base_commit": task.get("base_commit", ""),
            "test_patch": task.get("test_patch", ""),
            "FAIL_TO_PASS": json.dumps(task["fail_to_pass"]),
            "PASS_TO_PASS": json.dumps(task.get("pass_to_pass", [])),
            "image": task.get("image", image_name(task["instance_id"])),
        }
        try:
            spec = make_test_spec(inst)
        except HermeticBlocked as e:
            try:
                markers = log_markers(_read_text(log_path))
                lp = markers["start"] and markers["end"]
            except OSError:
                markers, lp = {"start": False, "end": False}, False
            out.update({"verdict": "hermeticity_blocked", "resolved": None,
                        "log_parsed": lp, "log_markers": markers,
                        "log_state": "not_judged", "hermetic": guard.hermetic(),
                        "live_http": guard.live_http, "blocked_urls": guard.blocked_urls,
                        "blocked_target": e.target})
            sys.stderr.write(
                f"[swev-judge-{JUDGE_TAG}] 离线缓存未命中，判分拒跑（R5：外呼失败即判失败并留痕）："
                f"{e.target}\n")
            return _emit(out)

        # 缺陷①：三态分类（可复算：markers + bad_codes + status_map）
        state, status_map, markers, bad = classify_log_state(spec, log_path)
        out["log_state"] = state
        out["tests_status_parsed"] = len(status_map)
        out["log_markers"] = markers
        if bad:
            out["bad_codes"] = bad
        out["log_parsed"] = state == "parsed"

        prediction = {
            "instance_id": task["instance_id"],
            "model_patch": model_patch,
            "model_name_or_path": "af-bench",
        }
        report = get_eval_report(spec, prediction, log_path, include_tests_status=True)
        inner = report.get(task["instance_id"], report)
        resolved = bool(inner.get("resolved"))

    out["resolved"] = resolved
    out["verdict"] = ("resolved" if resolved
                      else {"parsed": "not_resolved", "zero_state": "zero_state",
                            "no_markers": "no_markers", "eval_error": "eval_error"}[state])
    if _SYNTH:
        out["env_yml_synthesized"] = True
    status = inner.get("tests_status") or {}
    f2p = status.get("FAIL_TO_PASS") or {}
    if f2p:
        out["f2p_success"] = len(f2p.get("success", []))
        out["f2p_failure"] = len(f2p.get("failure", []))
    p2p = status.get("PASS_TO_PASS") or {}
    if p2p:
        out["p2p_success"] = len(p2p.get("success", []))
        out["p2p_failure"] = len(p2p.get("failure", []))
    collected = (len(f2p.get("success", [])) + len(f2p.get("failure", []))
                 + len(p2p.get("success", [])) + len(p2p.get("failure", [])))
    out["tests_collected"] = collected
    if SWEBENCH_VERSION:
        out["swebench_version"] = SWEBENCH_VERSION
    out["hermetic"] = guard.hermetic()
    out["live_http"] = guard.live_http
    out["blocked_urls"] = guard.blocked_urls
    out["socket_connects"] = guard.socket_connects
    return _emit(out)


def _warm_cache(task) -> int:
    """缓存预热：显式放行外呼并把全部响应（含 404）写入离线缓存。"""
    guard = HermeticGuard(allow_live=True)
    with guard():
        _install_env_yml_fallback(task)
        inst = {
            "instance_id": task["instance_id"],
            "repo": task["repo"],
            "version": task.get("version", ""),
            "base_commit": task.get("base_commit", ""),
            "test_patch": task.get("test_patch", ""),
            "FAIL_TO_PASS": json.dumps(task["fail_to_pass"]),
            "PASS_TO_PASS": json.dumps(task.get("pass_to_pass", [])),
            "image": task.get("image", image_name(task["instance_id"])),
        }
        try:
            make_test_spec(inst)
            ok = True
            err = None
        except Exception as e:  # noqa: BLE001 - 预热失败如实回报
            ok, err = False, f"{type(e).__name__}: {e}"
    return _emit({"warm": ok, "instance_id": task.get("instance_id"),
                  "urls_fetched": guard.live_http, "urls_cached": len(guard.live_http),
                  "error": err, "hermetic": False})


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        if argv and argv[0] == "--warm-cache":
            if len(argv) != 2:
                sys.stderr.write("用法: swev-judge-v2.py --warm-cache <task.json>\n")
                return 1
            task = json.load(open(argv[1], encoding="utf-8"))
            return _warm_cache(task)
        if len(argv) < 2:
            sys.stderr.write("用法: swev-judge-v2.py <task.json> <log文件> <agent_diff文件>\n")
            return 1
        task = json.load(open(argv[0], encoding="utf-8"))
        return _judge(task, argv[1], argv[2] if len(argv) > 2 else None)
    except Exception as e:  # noqa: BLE001 - judge_error：stdout 仍给 JSON，可归因
        import traceback
        sys.stderr.write(traceback.format_exc())
        return _emit({"judge": JUDGE_TAG, "verdict": "judge_error", "resolved": None,
                      "error": f"{type(e).__name__}: {e}"}, code=1)


if __name__ == "__main__":
    sys.exit(main())
