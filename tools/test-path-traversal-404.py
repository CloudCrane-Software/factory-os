#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test-path-traversal-404.py — RT-E47 ② 回归：curl --path-as-is /task/../x.md 必须 404
                              （2026-11-02 施工，逃逸问题台账 RT-E47 拦截机制②原文）

台账原文（计划/研究组/红队终局轮-20261101/逃逸问题台账.md §十二 RT-E47 拦截机制②）：
    「回归测试进 all-gates：curl --path-as-is /task/../x.md 必须 404」
红队确证发现（RT-E47 证据）：修复前 af-jobs-portal.py /task/<id>/<file>.md 分支裸拼
os.path.join，curl --path-as-is /task/../AGENTS.md 公网 ai. 入口 200 读出
/data/AGENTS.md（GLOBAL_AGENTS_MD 常量逐字一致）；修复后该分支与 _static_path
同款双保险（af-jobs-portal.py _task_doc_path：段正则 + realpath 锚 DATA/tasks，
拒绝 ./.. 段），穿越一律 404。

被测面：af-jobs 门户三个公网在役入口（同一 portal 后端；覆盖发现里「两入口行为
不一致」的两侧——ai. 原漏洞入口 + jobs./factory. 对照）。入口册来源=登记册正本
tools/public_entry_registry.py 的 kind=portal 条目（2026-11-03 起本门不再内嵌手抄
入口清单——手抄清单与配置面五限速 zone 无对账=巡检盲区）；非门户公网口
（otlp./zhihui.）的穿越无泄露断言在 tools/rate-limit-symmetry-probe.py A 腿
（登记册全覆盖，五入口）。断言分层（2026-11-02
施工当日实盘取证修正，证据=门户在役日志）：
  jobs./factory.（caddy 不改写路径，点段原样到 portal）：
    /task/../AGENTS.md 与 /task/../x.md 必须 404（钉死台账口径；404=portal
    _task_doc_path 双保险在役拒绝）。
  ai.（caddy 在 strip_prefix 前先归一化点段——实测 /af-jobs/task/../AGENTS.md 到
    门户时已是 /AGENTS.md，即门户设计内公开的全局契约端点，portal 日志
    [18:34:23] "GET /AGENTS.md" 200 亲证）：该 URL 断言「404 或 200 且响应体逐字
    == 本入口 /af-jobs/AGENTS.md 公开契约体」——任何其他 .md 内容经此形态读出
    （=真穿越泄露）即红；/af-jobs/task/../x.md 仍钉死 404。
  判别力：caddy 归一化使 ai. 侧该形态在漏洞/修复两态都得到契约体（caddy 层已把
    点段摘掉，portal /task 分支根本收不到）——真判别腿是 jobs./factory. 裸点段
    （漏洞态 200 读出任意 DATA 根 .md，见 --selftest 本地旧版实证）与「非契约体
    即红」的内容级断言。

实现口径：subprocess curl --path-as-is（保留台账原文工具语义——curl 缺省会把 ../
归一化掉使穿越失真，--path-as-is 原样发送请求行，正是穿越成立的关键）。
断言 ==404（钉死台账口径）；000/超时/5xx=在役面异常也红并点名
「公网抖动/在役重载可复跑对账」（all-gates 同口径，不静默 SKIP）。

判别力自证（--selftest，零公网零生产扰动）：
  对 pre-RT 带洞副本 tools/af-jobs-portal.py.20261031-pre-RT.bak 起本地隔离实例
  （临时 AF_JOBS_DATA，DATA 根预置穿越目标件），同款 --path-as-is 请求必须得 200
  且读到预置内容——钉住「本探针的请求形态在漏洞态真实穿越」；若旧版测不出 200，
  说明探针失真（自证红）。

退出码：主测 0=三入口全 404；1=回归红；2=前置失败（curl 缺失/域解析失败）。
        --selftest 0=判别力成立；1=探针失真；2=旧版副本缺件。
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time
import socket
import urllib.request

TOOLS = os.path.dirname(os.path.abspath(__file__))
PORTAL = os.path.join(TOOLS, "af-jobs-portal.py")
OLD_PORTAL = os.path.join(TOOLS, "af-jobs-portal.py.20261031-pre-RT.bak")

if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)                       # 登记册正本同目录导入（-I 隔离模式也要显式加）
import public_entry_registry as _reg                # noqa: E402 —— 公网入口登记册正本

PROBE_FILES = ("AGENTS.md", "x.md")  # AGENTS.md=发现实证被读出的 DATA 根文件；x.md=台账原文口径


def die(code, msg):
    print(f"[RED rc={code}] {msg}", file=sys.stderr)
    sys.exit(code)


# 入口 → 任务文档 URL 前缀（ai. 走 /af-jobs/* 子路由 + strip_prefix；jobs./factory. 裸路径）
# 入口册来源=登记册正本 tools/public_entry_registry.py 的 kind=portal 条目（本门只管
# af-jobs 门户面：/task/../x.md 必须 404 是门户双保险口径；otlp./zhihui. 等非门户
# 公网口的穿越无泄露断言在 tools/rate-limit-symmetry-probe.py A 腿——登记册全覆盖）。
# 登记册坏件/不合规 → fail-closed（rc=2 不可证不猜绿），不得退回手抄清单。
try:
    ENTRANCES = [(e["slug"], e["base"]) for e in _reg.portal_entries()]
except _reg.RegistryError as _e:
    die(2, f"登记册不合规：{_e}——门户入口册取不到，fail-closed（不可证不猜绿）")


def curl_code(path_as_is_url, timeout=20):
    r = subprocess.run(["curl", "--path-as-is", "-s", "-o", "/dev/null",
                        "-w", "%{http_code}", "--max-time", str(timeout), path_as_is_url],
                       capture_output=True, text=True)
    return (r.stdout or "").strip() or "000"


def curl_body(path_as_is_url, timeout=20):
    r = subprocess.run(["curl", "--path-as-is", "-s", "--max-time", str(timeout), path_as_is_url],
                       capture_output=True, text=True)
    return r.stdout or ""


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def selftest():
    """判别力自证：旧版（pre-RT 带洞）必须能被本探针的请求形态真实读出 200。"""
    if not os.path.isfile(OLD_PORTAL):
        die(2, f"缺件：判别力自测旧版副本不在位 {OLD_PORTAL}（探针失真无从自证，按红点名）")
    marker = "selftest-traversal-marker-20261102"
    data = tempfile.mkdtemp(prefix="afjobs-gate-trav-")
    os.makedirs(os.path.join(data, "tasks", "t-selftest"), exist_ok=True)
    secret = os.path.join(data, f"{marker}.md")
    open(secret, "w").write("# TRAVERSAL-REACHED\n")
    port = free_port()
    env = dict(os.environ)
    env["AF_JOBS_DATA"] = data
    env["AF_JOBS_PORT"] = str(port)
    proc = subprocess.Popen([sys.executable, "-I", OLD_PORTAL], env=env, cwd=data,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            if proc.poll() is not None:
                die(2, f"旧版实例启动即退 rc={proc.returncode}")
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=3) as r:
                    if r.status == 200:
                        break
            except Exception:
                pass
            time.sleep(0.1)
        else:
            die(2, f"旧版实例 healthz 未就绪 port={port}")
        # 同款穿越形态打本地旧版（url-encoded 与否则保持原样——curl --path-as-is）
        code = curl_code(f"http://127.0.0.1:{port}/task/../{marker}.md", timeout=10)
        if code != "200":
            die(1, f"自证红：探针请求形态打旧版得 {code}（期望 200 真实穿越）——探针失真，主测 404 断言无判别力")
        body = ""
        r = subprocess.run(["curl", "--path-as-is", "-s", "--max-time", "10",
                            f"http://127.0.0.1:{port}/task/../{marker}.md"],
                           capture_output=True, text=True)
        body = (r.stdout or "")
        if "TRAVERSAL-REACHED" not in body:
            die(1, f"自证红：旧版 200 但内容非预置件（读到的是：{body[:80]!r}）——探针形态失真")
        print("OK（--selftest）：pre-RT 带洞版被本探针形态真实读出预置件（200+TRAVERSAL-REACHED）"
              "——主测的 404 断言具备判别力（漏洞态必 200、修复态必 404）")
        sys.exit(0)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        shutil.rmtree(data, ignore_errors=True)


def main():
    if "--selftest" in sys.argv[1:]:
        selftest()
    if shutil.which("curl") is None:
        die(2, "前置失败：本机无 curl（台账口径工具 --path-as-is 依赖 curl）")
    fail = []
    # ai. 基线：本入口公开契约体（/af-jobs/AGENTS.md → caddy 归一化 → 门户 /AGENTS.md
    # 设计内公开端点）。拉取失败/非契约内容即前置红（内容级断言无基准，不猜绿）。
    ai_base_url = next((b for n, b in ENTRANCES if n == "ai"), None)
    if not ai_base_url:
        die(2, "前置失败：登记册门户条目里无 slug=ai 入口（公开契约基线取不到，fail-closed）")
    ai_base = curl_body(f"{ai_base_url}/AGENTS.md", timeout=30)
    if not ai_base:
        die(2, "前置失败：ai. 入口 /af-jobs/AGENTS.md 公开契约体拉取为空——内容级断言无基准")
    if "沙箱执行契约" not in ai_base:
        die(2, f"前置失败：ai. 基线体不含契约标记「沙箱执行契约」（{len(ai_base)}B，疑截断/错误页）——内容级断言无可信基准")
    for name, base in ENTRANCES:
        for f in PROBE_FILES:
            url = f"{base}/task/../{f}"
            code = curl_code(url)
            if code == "404":
                print(f"  [ok] {name}  --path-as-is /task/../{f} → 404")
            elif name == "ai" and code == "200" and f == "AGENTS.md":
                body = curl_body(url)
                if body == ai_base:
                    print(f"  [ok] {name}  --path-as-is /task/../AGENTS.md → 200＝设计内公开契约体"
                          f"（caddy 归一化别名 /AGENTS.md，逐字 == 公开契约 {len(body)}B；非泄露）")
                else:
                    fail.append(f"{name} {url} → 200 但响应体 ≠ 公开契约体（{len(body)}B vs {len(ai_base)}B）"
                                f"——读出了非契约内容＝真穿越泄露")
            else:
                fail.append(f"{name} {url} → {code}（期望 404；200=穿越漏洞态复现，"
                            f"000/5xx=在役面异常或公网抖动，可复跑对账）")
    if fail:
        die(1, "红：路径穿越回归失守——\n  " + "\n  ".join(fail))
    print("OK：jobs./factory. 裸点段全 404（portal 双保险在役拒绝）；ai. 归一化形态 "
          "x.md=404、AGENTS.md=公开契约体逐字一致——RT-E47 ② 在役（curl --path-as-is 原样路径）")
    sys.exit(0)


if __name__ == "__main__":
    main()
