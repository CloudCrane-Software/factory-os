#!/usr/bin/env python3
"""swev-judge.py — 用 swebench 4.1 官方判分管线判定 eval 日志。

用法: swev-judge.py <task.json> <log文件> <agent_diff文件>
stdout: JSON {"resolved": true|false, "log_parsed": bool, ...}

log_parsed（D-20 项 3，2026-10-20）：日志缺 Start/End Test Output 标记（截断/失败日志，
swebench found=False 的典型形态）时为 false——判 false 与"测试真跑过但失败"在证据上不同貌，
消费方（af-bench verifier_note / 离线复核）应如实透传。
"""
import json
import sys

sys.path.insert(0, "/home/pan-ding/swev-venv/lib/python3.14/site-packages")

from swebench.harness.grading import get_eval_report  # noqa: E402
from swebench.harness.test_spec.test_spec import make_test_spec  # noqa: E402
import importlib.metadata  # noqa: E402

# fix4-observability（2026-10-22）：stdout JSON 增量补 p2p_success/p2p_failure、
# tests_collected、swebench_version 三个字段——判分语义零变化，只把已经在内存里的
# tests_status 与库版本如实上报（观测侧 judge.detail.p2p_*/tests_collected 的源头）。
try:
    SWEBENCH_VERSION = importlib.metadata.version("swebench")
except Exception:  # pragma: no cover - 版本自报失败不阻断判分
    SWEBENCH_VERSION = None

# 2026-10-21 修理组：swebench 取 environment.yml 只认 commit 原文（raw.githubusercontent），
# 老实例（xarray 0.12 八题实证）的 commit 上游根本没有该文件 → make_test_spec 抛 ValueError、
# judge.json 落空、判分链断。而判分（get_eval_report）只用 spec 的 instance_id/测试清单/repo，
# env yml 内容不进判定——故 404 时按该版本 dataset 规格合成等价 yml，判分语义零变化；
# 合成与否在输出 JSON 里如实标注（env_yml_synthesized），进 verifier_note 留审计。
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
            sys.stderr.write(f"[swev-judge] environment.yml 404 @ {repo}:{commit} "
                             f"→ 按版本 {task.get('version')} dataset 规格合成（判分不受影响）\n")
            _SYNTH.append(True)
            return "\n".join(lines)

    py_spec.get_environment_yml_by_commit = patched


# 三测试修理组（2026-10-21，厂长授权）：pylint 三题同型阻塞——base_commit 是镜像内注入/
# 中性提交（上游 404/422），而 pylint 所有 version 桶 packages='requirements.txt' →
# get_requirements_by_commit 向 raw.githubusercontent 拉 requirements_test.txt@base_commit
# 抛 ValueError、make_test_spec 崩。requirements 内容只进 env 脚本（判分不执行），
# 判定只吃 f2p/p2p 清单与日志——404 时按该 version dataset 规格合成等价 requirements
# （判分语义零变化），合成与否如实上报（reqs_synthesized 留审计）。
_REQS_SYNTH = []


def _install_requirements_fallback(task):
    from swebench.harness.constants import MAP_REPO_VERSION_TO_SPECS  # noqa: E402
    from swebench.harness.test_spec import python as py_spec  # noqa: E402

    orig = py_spec.get_requirements_by_commit

    def patched(repo, commit):
        try:
            return orig(repo, commit)
        except ValueError:
            pins = (MAP_REPO_VERSION_TO_SPECS.get(repo, {})
                    .get(task.get("version", ""), {}).get("pip_packages") or [])
            sys.stderr.write(f"[swev-judge] requirements 404 @ {repo}:{commit} "
                             f"→ 按版本 {task.get('version')} dataset 规格合成 {len(pins)} 条 pin"
                             f"（判分不受影响）\n")
            _REQS_SYNTH.append(True)
            return "\n".join(pins)

    py_spec.get_requirements_by_commit = patched


def image_name(iid: str) -> str:
    return f"swebench/sweb.eval.x86_64.{iid.replace('__', '_1776_').lower()}:latest"


def log_parsed(log_path) -> bool:
    """官方 eval_script 的测试段由 Start/End Test Output 一对标记包住（set -x 轨迹里
    形如 `+ : '>>>>> Start Test Output'`）；两标记齐在才算完整解析。"""
    try:
        text = open(log_path, encoding="utf-8", errors="replace").read()
    except OSError:
        return False
    return "Start Test Output" in text and "End Test Output" in text


def main():
    task = json.load(open(sys.argv[1], encoding="utf-8"))
    log_path = sys.argv[2]
    diff_path = sys.argv[3] if len(sys.argv) > 3 else None
    parsed = log_parsed(log_path)
    model_patch = ""
    if diff_path:
        model_patch = open(diff_path, encoding="utf-8", errors="replace").read()
    _install_env_yml_fallback(task)
    _install_requirements_fallback(task)
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
    spec = make_test_spec(inst)
    prediction = {
        "instance_id": task["instance_id"],
        "model_patch": model_patch,
        "model_name_or_path": "af-bench",
    }
    report = get_eval_report(spec, prediction, log_path, include_tests_status=True)
    inner = report.get(task["instance_id"], report)
    resolved = bool(inner.get("resolved"))
    out = {"resolved": resolved, "log_parsed": parsed}
    if _SYNTH:
        out["env_yml_synthesized"] = True
    if _REQS_SYNTH:
        out["reqs_synthesized"] = True
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
    print(json.dumps(out))


if __name__ == "__main__":
    main()
