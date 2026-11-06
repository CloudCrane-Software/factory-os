#!/usr/bin/env python3
"""cb-dispatch.py — CNB CodeBuddy NPC SWE-V 派发器（最小可用版）。

链路：本机建 issue + 评论 @CodeBuddy（work_mode=true，API 字段）→ 平台拉起
      deepseek-v4.1-flash agent 沙箱（默认 8 核/16G，计 dev 池 1600 核时/月免费，
      AI token 计 NPC 口径实测 0 扣费）→ agent 克隆上游仓库写补丁 →
      推 results/<task-id> 分支（分支内 results/<task-id>.patch）→
      本机用 /-/git/raw API 收补丁 → 交 swev-judge 本地判分。

口径声明（勿混算）：codebuddy 自家 harness（NPC agent）+ DeepSeek V4.1 免费，
新档案 profile="deepseek-cb"；与 af-harness 口径（af-bench）不混算。

防重与断点续跑：state 文件（默认 /tmp/cb-dispatch/<org>__<repo>.json）记录
task_id → {issue, comment_id, sn, build_status, patch, collected}；
dispatch 只处理 state 里没有的 task；watch 幂等，可反复跑。

用法:
  cb-dispatch.py dispatch <org> <repo> <tasks_dir> [--limit N]   # 批量建 issue+评论
  cb-dispatch.py watch   <org> <repo> [--once]                   # 轮询观测+自动收补丁
  cb-dispatch.py status  <org> <repo>                            # 任务状态表
  cb-dispatch.py collect <org> <repo> <task_id>                  # 手工收单个补丁
  cb-dispatch.py quota   <org>                                   # dev 池免费/已用

密钥纪律：CNB token 从 openBao 按字段管道取（bao_field），不落盘、不打印。
"""
import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error

CNB_API = "https://api.cnb.cool"
BAO = "http://gov-host.invalid:8200"
BAO_RT = os.path.expanduser("~/.local/share/openbao-escrow/.root-token")
STATE_ROOT = "/tmp/cb-dispatch"
# 两个 org 各自独立 dev 池（各 1600 核时/月免费），铺量时各铺一半。
ORG_TOKEN = {
    "zhuzhu-team": "CNB-2-all-privilege",
    "cloudbird-software": "CNB-1-all-privilege",
}
# NPC 沙箱实测默认规格（labels cpus=8 memory=16），.cnb.yml 覆盖无效（2026-10-20 实证）。
NPC_CPUS, NPC_MEM = 8, 16

# 任务投喂模板：issue 正文=problem_statement；评论=操作指令。
# 约束来自实测：沙箱无 docker（走纯写补丁路线）；commit.gpgsign=true 需 -c 关掉；
# github.com 出网通；/workspace 即本仓 checkout，origin 凭据已注入。
COMMENT_TMPL = """@CodeBuddy 请修复上述 issue 描述的 bug，按以下流程执行：

1. 克隆上游源码并切到指定提交：
   git clone https://github.com/{upstream} /tmp/work
   cd /tmp/work && git checkout {base_commit}
2. 定位并修复 bug。只改必要的非测试源码文件；严禁改动任何测试文件（tests/ 目录、test_*.py、conftest.py 等）。
3. 尽量自验（能装环境就装；装不上就静态推理保证正确性），不要在自验上耗尽时间。
4. 产出补丁文件：在 /tmp/work 里执行 mkdir -p /workspace/results && git diff > /workspace/results/{task_id}.patch
5. 推送结果分支：
   cd /workspace
   git checkout -b results/{task_id}
   git add results/{task_id}.patch
   git -c commit.gpgsign=false commit -m "swev: {task_id} model patch"
   git push origin results/{task_id}
6. 回复本评论，说明：改了哪些文件、每处改动为什么、自验结果。

补丁格式要求：git diff 标准格式，能被 git apply 直接应用；补丁里不得出现测试文件的改动。"""


CNB_TOKEN_FILE = os.path.expanduser("~/.config/cnb/relay-tokens.json")


def bao_field(path, field):
    # 优先本地 0600 令牌文件（2026-10-20 迁移：工具不再依赖 escrow root 明文）
    if field == "Token":
        try:
            with open(CNB_TOKEN_FILE) as f:
                t = json.load(f).get(path)
            if t:
                return t
        except FileNotFoundError:
            pass
    with open(BAO_RT) as f:
        rt = f.read().strip()
    req = urllib.request.Request(
        f"{BAO}/v1/kv/data/company/Git-Platform/CNB/{path}",
        headers={"X-Vault-Token": rt},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)["data"]["data"][field]


_tokens = {}


def token(org):
    if org not in _tokens:
        _tokens[org] = bao_field(ORG_TOKEN[org], "Token")
    return _tokens[org]


def api(org, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        CNB_API + path, data=data, method=method,
        headers={"Authorization": "Bearer " + token(org),
                 "Content-Type": "application/json",
                 "Accept": "application/vnd.cnb.api+json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            b = r.read().decode()
            if not b:
                return {}
            try:
                return json.loads(b)
            except json.JSONDecodeError:
                return b  # /-/git/raw 原样返回文件内容
    except urllib.error.HTTPError as e:
        return {"__http_error": e.code, "body": e.read().decode()[:300]}


def state_path(org, repo):
    return f"{STATE_ROOT}/{org}__{repo}.json"


def load_state(org, repo):
    p = state_path(org, repo)
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    return {}


def save_state(org, repo, st):
    os.makedirs(STATE_ROOT, exist_ok=True)
    with open(state_path(org, repo), "w") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)


def dispatch(org, repo, tasks_dir, limit):
    st = load_state(org, repo)
    tasks = sorted(f for f in os.listdir(tasks_dir) if f.endswith(".json"))
    done = 0
    slug = f"{org}/{repo}"
    for fn in tasks:
        if limit and done >= limit:
            break
        task = json.load(open(os.path.join(tasks_dir, fn)))
        tid = task["instance_id"]
        if tid in st:
            continue  # 防重：已派发过（无论状态）一律跳过
        upstream = task.get("repo", "")
        body = (f"[SWE 任务包 {tid}] 真实上游 issue（base="
                f"{task.get('base_commit','')}）：\n\n{task['problem_statement']}\n\n"
                f"（修复指令见评论。请先读本 issue 全文理解问题。）")
        issue = api(org, "POST", f"/{slug}/-/issues",
                    {"title": f"[swev] {tid}", "body": body})
        num = issue.get("number")
        if not num:
            print(f"{tid}: 建 issue 失败 {issue}", file=sys.stderr)
            break  # 通道级失败（404/403）继续无益，直接停
        comment = api(org, "POST", f"/{slug}/-/issues/{num}/comments",
                      {"body": COMMENT_TMPL.format(
                          upstream=upstream, base_commit=task.get("base_commit", ""),
                          task_id=tid), "work_mode": True})
        st[tid] = {"issue": num, "comment_id": comment.get("id"),
                   "sn": None, "build_status": "dispatched",
                   "patch": None, "collected": False}
        save_state(org, repo, st)
        print(f"{tid}: issue #{num} comment {comment.get('id')}")
        done += 1
        time.sleep(3)  # 温和限速，避免评论接口限流


def map_builds(org, repo, st):
    """build/logs 的 eventUrl 含 issue 号 → task；刷新 sn 与 build_status。"""
    logs = api(org, "GET", f"/{org}/{repo}/-/build/logs")
    items = logs.get("data") if isinstance(logs, dict) else logs
    by_issue = {v.get("issue"): k for k, v in st.items()}
    for it in items or []:
        url = it.get("eventUrl") or ""
        sn = it.get("sn")
        for tid, v in st.items():
            if v.get("issue") and url.rstrip("/").endswith(f"/issues/{v['issue']}"):
                if v.get("sn") != sn:
                    v["sn"] = sn
                if it.get("status") != v.get("build_status"):
                    v["build_status"] = it.get("status")


def collect(org, repo, tid, st):
    v = st[tid]
    raw = api(org, "GET", f"/{org}/{repo}/-/git/raw/results/{tid}/results/{tid}.patch")
    if not isinstance(raw, str) or "diff --git" not in raw:
        return None
    out_dir = f"{STATE_ROOT}/patches"
    os.makedirs(out_dir, exist_ok=True)
    path = f"{out_dir}/{tid}.patch"
    with open(path, "w") as f:
        f.write(raw)
    v["patch"] = path
    v["collected"] = True
    return path


def watch(org, repo, once):
    st = load_state(org, repo)
    while True:
        map_builds(org, repo, st)
        changed = False
        for tid, v in st.items():
            if v.get("collected"):
                continue
            if v.get("build_status") == "success":
                p = collect(org, repo, tid, st)
                changed = True
                print(f"{tid}: 补丁收讫 {p}" if p else f"{tid}: 分支未就绪/无补丁")
        save_state(org, repo, st)
        if once:
            for tid, v in st.items():
                print(tid, v.get("build_status"), "collected" if v.get("collected") else "-")
            return
        time.sleep(30)


def status(org, repo):
    st = load_state(org, repo)
    map_builds(org, repo, st)
    save_state(org, repo, st)
    for tid, v in sorted(st.items()):
        print(f"{tid:45s} issue=#{v.get('issue')} {v.get('build_status'):10s} "
              f"patch={'Y' if v.get('collected') else '-'} sn={v.get('sn')}")


def quota(org):
    q = api(org, "GET", f"/{org}/-/charge/quota")
    v = api(org, "GET", f"/{org}/-/charge/volume")
    dev, ci = q.get("dev_in_sec", {}), q.get("ci_in_sec", {})
    print(f"{org}: dev 免费={dev.get('free',0)/3600:.0f}核时 总={dev.get('total',0)/3600:.0f}核时 "
          f"已用={v.get('dev_in_sec',0)/3600:.2f}核时 冻结={v.get('freeze_dev_in_sec',0)/3600:.2f}核时 | "
          f"ci 已用={v.get('ci_in_sec',0)/3600:.2f}核时")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, extra in [("dispatch", [("tasks_dir",), ("--limit", int, 0)]),
                        ("watch", [("--once", None, False)]),
                        ("status", []), ("quota", [])]:
        p = sub.add_parser(name)
        p.add_argument("org")
        if name != "quota":
            p.add_argument("repo")
        for e in extra:
            if e[0].startswith("--"):
                p.add_argument(e[0], type=e[1], default=e[2])
            else:
                p.add_argument(e[0])
    p = sub.add_parser("collect")
    p.add_argument("org")
    p.add_argument("repo")
    p.add_argument("task_id")
    a = ap.parse_args()

    if a.cmd == "dispatch":
        dispatch(a.org, a.repo, a.tasks_dir, a.limit)
    elif a.cmd == "watch":
        watch(a.org, a.repo, a.once)
    elif a.cmd == "status":
        status(a.org, a.repo)
    elif a.cmd == "quota":
        quota(a.org)
    elif a.cmd == "collect":
        st = load_state(a.org, a.repo)
        print(collect(a.org, a.repo, a.task_id, st))


if __name__ == "__main__":
    main()
