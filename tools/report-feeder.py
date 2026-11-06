#!/usr/bin/env python3
"""report-feeder — arXiv 新论文自动选题器（report 道补给；本机跑，轻量 curl+ssh）

流程自动化以下既有手工步骤：
  ① 多源候选流（2026-11-05 RT-E70 根治批：源①现役口径不变，按序增补三路）：
     源① export.arxiv.org API 按六类 cat:cs.SE/cs.AI/cs.LG/cs.CL/cs.CR/cs.MA × 关键词
     (agent|harness|LLM|benchmark|eval|reasoning|tool) + submittedDate 近 180 天区间
     （2026-10-29 供给扩容，查询面与 tools/portal-seeder.py 源① 逐字对齐：原两科×三词
     「最新窗口」连续多轮 0 篇未见过的，已耗尽；2026-10-30 产线续能批把窗口 60→180 天、
     深翻上限 60→120 页，--window-days/--scan-pages 可配）拉最新 N 篇；
     源② 时间窗外推（FEEDER_WINDOW_LADDER，默认 365,730 天；基窗之外的非重叠旧层，
     UTC 日界同源①）——停摆根因实证（log 2026-11-02 09:52 轮）：基窗倒序深翻的扫描
     预算（120 页 × 8 篇/页 = 960 篇 ≈ 最新 3-4 天）全落在「门户已播种 + HTML 尚未
     生成」的新鲜边界上（48 页扫 384 篇仅 1 篇未见过的且摄取 404），而旧层论文实测
     HTML 齐全（html/2601.07338 → 200 362,925B 等三例）且不在门户 180 天播种窗内；
     源③ 类目/词表扩（FEEDER_EXTRA_CATS/FEEDER_EXTRA_TERMS，默认追加 cs.HC/IR/CY/NE
     与 agentic/RAG/code generation 等词）覆盖基窗与各旧层；
     源④ 备选 API（FEEDER_ALT_API，默认 semanticscholar）：arXiv API 限流/内部错误时
     的第二发现面（S2 bulk search 实测 2026 年 "LLM agent" total 18,238、单页 1000 条、
     595 条带 arXiv id；429 按响应 retryAfter 退避；2026-11-05 实测 arXiv API 双路
     持续内部错误时本路仍 200）；
     源切换护栏（不弱化既有）：非旧层源连续零「未见过的」页（FEEDER_SOURCE_DRY_PAGES
     默认 8）或摄取连续失败（FEEDER_SWITCH_AFTER_FAILS 默认 6，新鲜边界 404 连击）即切
     下一源，arXiv API 重试耗尽则跳过余下 arXiv 源直送源④——耗尽的源吃不光轮预算；
     候选流为**惰性**（边取边摄）：新鲜边界上的论文 HTML 尚未生成（404），摄取失败
     不再吃掉整轮额度（2026-10-30 16:57-17:02 连续 6 轮真跑实测「落 0 篇」的根因修复）；
  ② 过滤：id 以 26 开头（训练截止后）、未出现在 anolis submitted.jsonl / report-r0 /
     本机 kb-seed/sandbox/task-seeds/（门户已派的不重复做 report）/ 队列 pending；
  ③ curl 拉 https://export.arxiv.org/html/<id> 做字节级归一化算 sha256——口径与
     report_unit.rs 的 ArxivWebFetcher/html_to_text 逐字节一致（复刻件，见下）；
  ④ 生成任务包 anolis:/data/bench/report-r0/<slug>-<id>/{task.json,plan.json}
     （plan.json 自 harnessdiag-2610-35767 复用，md5 锚 68c27088…不符即拒）；
  ⑤ 队列条目（unit=report, data_root=/data/bench/report-r0, profile=step-5,
     max_turns=40, spend_cap=300, dedupe_key=rf-<id>）入 pending。

口径依据（复刻必须逐字节一致，否则判分 R3 paper.sha256==task.paper_sha256 必挂）：
  af-wt-phase2-execline/crates/af-execline/src/suite/report_unit.rs
    · html_to_text      :306-361（script/style 丢弃→标签换空格→五实体→空白折叠）
    · fetch_to_doc      :477-528（normalize_url→逐跳手跟→read_to_string→from_text）
    · normalize_url     :383-397 / check_hop:402-416 / resolve_redirect:420-441
    · FetchedDoc::from_text:209-223（sha=规范化文本指纹；title 由判分面摄取时
      extract_html_title:538-549 自取，不进 task.json——feeder 不移植该件）
护栏：STOP 文件熔断；--dry-run 只打印不落盘；--limit 控制选题数（默认 10）；
      --window-days N（默认 180 天，FEEDER_WINDOW_DAYS 同效）/ --scan-pages N（默认 120 页，
      FEEDER_SCAN_PAGES 同效）——命令行 > 环境变量 > 内置默认；
      扩源三件套（均 env 可调、默认开，撤 STOP 熔断后即生效、不改码）：
      FEEDER_WINDOW_LADDER（默认 "365,730"，空=关）/ FEEDER_EXTRA_CATS、FEEDER_EXTRA_TERMS
      （默认见下常量，空=关）/ FEEDER_ALT_API（默认 "semanticscholar"，off=关）
      + FEEDER_ALT_QUERIES（默认见下常量）/ FEEDER_SOURCE_DRY_PAGES（默认 8）
      / FEEDER_SWITCH_AFTER_FAILS（默认 6）/ FEEDER_MAX_API_CALLS（默认 400）
      / FEEDER_ALT_GRACE_S（默认 120：源④独立墙钟，arXiv 重试吃穿轮预算时韧性路仍可达）；
所有 curl/ssh 带超时；任何一步失败 fail-loud 记因跳过的论文，不静默放行。
回滚：停跑；删 anolis:/data/bench/report-r0/<task> 与队列 pending 条目即可。"""
import argparse
import base64
import glob
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime, timedelta, timezone

WS = "/home/pan-ding/workspace/agent黑灯工厂"
ANOLIS = "anolis"
SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", ANOLIS]
STOP = WS + "/tools/.report-feeder-STOP"
LOG = WS + "/tools/report-feeder.log"
TASK_SEEDS = WS + "/kb-seed/sandbox/task-seeds"
API_URL = "https://export.arxiv.org/api/query"
# 任务/数据面常量（对齐 burn-runner 队列 schema 与 report-r0 手工先例）
DATA_ROOT = "/data/bench/report-r0"
PLAN_SRC = DATA_ROOT + "/harnessdiag-2610-35767/plan.json"
PLAN_MD5 = "68c27088ca81b36ff2cc240d4e417c07"  # 7 个 report 任务包 plan.json 实测同 md5
REGISTRY_ROOT = "/data/af-factory/af-p3/af/packages"
QUEUE_PENDING = "/data/bench/queue/pending"
SUBMITTED = "/data/bench/queue/submitted.jsonl"
QUEUE_PREFIX = "50"  # 文件名序=优先级；排在 rr55(90-) 前、原 report 波(010-013) 后
# 判分子进程 curl 同款超时（report_unit.rs:301 WEB_FETCH_TIMEOUT_SECS=45）
WEB_TIMEOUT = 45
# arXiv API 出网探针重试（429/超时退避；arXiv 限流窗口可达数分钟）
API_RETRIES = 4
API_BACKOFF = 25
ARXIV_ID_RE = re.compile(r"^(\d{4})\.(\d{4,5})$")

# ---------------------------------------------------------------- 日志/熔断


def log(msg):
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG, "a") as f:
            f.write(line + "\n")
    except OSError as e:
        print(f"(日志落盘失败: {e})", flush=True)


# ------------------------------------------- html_to_text 字节级复刻（口径锚）


def html_to_text(html):
    """report_unit.rs:306-361 html_to_text 的逐字节复刻。

    已验证：对同一输入与真 ArxivWebFetcher 快照字节级一致
    （rivet html 2930b546…/abs 52b58c43…；三个在役 task.json 预登记 sha 全复现）。
    易错点：Rust `lower[start..].find(tag)` 的返回值相对 start，而 Python
    `str.find(tag, start)` 返回绝对下标——pos 推进只加 end+len(tag)。
    """
    # ASCII 小写镜像（Rust to_ascii_lowercase 只动 A-Z；Python str.lower() 会动
    # 非 ASCII 变长移位，故用 translate 精确对齐字节布局）
    lower = html.translate(str.maketrans(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"))
    # ① script/style 块整段丢弃（取先出现者，未闭合则尾部全丢）
    cleaned = []
    pos = 0
    n = len(html)
    while pos < n:
        script = lower.find("<script", pos)
        style = lower.find("<style", pos)
        cands = [i for i in (script, style) if i != -1]
        if not cands:
            cleaned.append(html[pos:])
            break
        start = min(cands)
        cleaned.append(html[pos:start])
        end_tag = "</script>" if lower.startswith("<script", start) else "</style>"
        end = lower.find(end_tag, start)  # 绝对下标（与 Rust 相对值语义差一个 start）
        pos = n if end == -1 else end + len(end_tag)
    # ② 标签 → 空格
    out = []
    in_tag = False
    for ch in "".join(cleaned):
        if ch == "<":
            in_tag = True
            out.append(" ")
        elif ch == ">":
            in_tag = False
            out.append(" ")
        elif not in_tag:
            out.append(ch)
    # ③ 实体解码（五个高频件，顺序替换）
    decoded = ("".join(out)
               .replace("&amp;", "&")
               .replace("&lt;", "<")
               .replace("&gt;", ">")
               .replace("&quot;", "\"")
               .replace("&#39;", "'"))
    # ④ 空白折叠（Rust char::is_whitespace = Unicode White_Space 集；
    #    Python str.split() 多含 \x1c-\x1f，故按 Rust 集正则切）
    return " ".join(t for t in WS_RE.split(decoded) if t)


# Rust White_Space 集（U+0009-000D/0020/0085/00A0/1680/2000-200A/2028/2029/202F/205F/3000）
WS_RE = re.compile("[\t\n\x0b\x0c\r \x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+")
RUST_WS = frozenset("\t\n\x0b\x0c\r \x85\xa0\u1680"
                    + "".join(chr(c) for c in range(0x2000, 0x200B))
                    + "\u2028\u2029\u202f\u205f\u3000")


def rust_trim(s):
    """Rust str::trim 语义（White_Space 集；逐字符集查询，避免逐字符正则）。"""
    i, j = 0, len(s)
    while i < j and s[i] in RUST_WS:
        i += 1
    while j > i and s[j - 1] in RUST_WS:
        j -= 1
    return s[i:j]


# ------------------------------------- ArxivWebFetcher 抓取面复刻（report_unit.rs）


ARXIV_HOSTS = ("arxiv.org", "www.arxiv.org", "export.arxiv.org")


def normalize_url(source):
    """report_unit.rs:383-397：仅 https + 域白名单，host 统一改写 export.arxiv.org。"""
    rest = source[len("https://"):] if source.startswith("https://") else None
    if rest is None:
        raise ValueError(f"web 摄取仅支持 https（{source}）")
    cut = rest.find("/")
    host, path = (rest, "/") if cut == -1 else (rest[:cut], rest[cut:])
    if host not in ARXIV_HOSTS:
        raise ValueError(f"域白名单拒绝 {host}——{source}")
    return f"https://export.arxiv.org{path}"


def check_hop(url):
    """report_unit.rs:402-416：每一跳都必须 https + 白名单 host。"""
    if not url.startswith("https://"):
        raise ValueError(f"重定向目标非 https：{url}")
    rest = url[len("https://"):]
    cut = rest.find("/")
    host, path = (rest, "/") if cut == -1 else (rest[:cut], rest[cut:])
    if host not in ARXIV_HOSTS:
        raise ValueError(f"白名单拒绝重定向落点 {host}——{url}")
    return host, path


def resolve_redirect(base, location):
    """report_unit.rs:420-441：绝对 https 直通；相对 Location 并入 base host。"""
    loc = location.strip()
    if loc.startswith("https://"):
        return loc
    if "://" in loc:
        raise ValueError(f"仅支持 https 重定向（Location={loc}）")
    host, base_path = check_hop(base)
    if loc.startswith("/"):
        return f"https://{host}{loc}"
    cut = base_path.rfind("/")
    directory = base_path[:cut] if cut != -1 else ""
    return f"https://{host}{directory}/{loc}"


def _curl_local(url, body_path):
    """本机 curl 单跳（report_unit.rs:445-473 同款 argv，绝不 -L）。返回 (code, redirect)。"""
    p = subprocess.run(
        ["curl", "-sS", "-m", str(WEB_TIMEOUT), "-o", body_path,
         "-w", "%{http_code} %{redirect_url}", url],
        capture_output=True, text=True, timeout=WEB_TIMEOUT + 15)
    if p.returncode != 0:
        raise RuntimeError(f"curl 退出 {p.returncode}: {p.stderr.strip()[:200]}")
    line = p.stdout.strip()
    code, _, redirect = line.partition(" ")
    if len(code) != 3 or not code.isascii() or not code.isdigit():
        raise RuntimeError(f"curl 未返回可解析 HTTP 状态（{url} → {line!r}）")
    return code, redirect.strip()


def _curl_anolis(url, remote_body):
    """anolis curl 单跳（report 单元同机同路径跑判分摄取；body 暂存 anolis）。

    本机到 export.arxiv.org 的出网实测间歇性超时；判分面在 anolis 抓取，
    走 anolis 面不仅更稳，且拿到的就是判分面将拿到的同一份字节。
    """
    cmd = (f"curl -sS -m {WEB_TIMEOUT} -o {remote_body} "
           f"-w '%{{http_code}} %{{redirect_url}}' {shlex.quote(url)}")
    line = sh_out(SSH + [cmd], timeout=WEB_TIMEOUT + 25).strip()
    code, _, redirect = line.partition(" ")
    if len(code) != 3 or not code.isascii() or not code.isdigit():
        raise RuntimeError(f"anolis curl 未返回可解析 HTTP 状态（{url} → {line!r}）")
    return code, redirect.strip()


def _fetch_paper_via(source, via):
    """report_unit.rs:477-528 fetch_to_doc 复刻（传输面可换：anolis/本机）。

    body 走 read_to_string 同款 UTF-8 严格解码（Rust 非法 UTF-8 即摄取失败）；
    空响应体（trim 后）即拒。
    """
    url = normalize_url(source)
    check_hop(url)
    hops = 0
    local_body = f"/tmp/report-feeder-body-{os.getpid()}-{int(time.time() * 1000)}.html"
    remote_body = f"/tmp/report-feeder-anolis-{os.getpid()}.body"
    try:
        while True:
            if via == "anolis":
                code, redirect = _curl_anolis(url, remote_body)
            else:
                code, redirect = _curl_local(url, local_body)
            if 300 <= int(code) < 400:
                hops += 1
                if hops > 5:
                    raise RuntimeError(f"重定向超过 5 跳（{source}）")
                if not redirect:
                    raise RuntimeError(f"收到 {code} 重定向但无 Location（{url}）")
                url = resolve_redirect(url, redirect)
                check_hop(url)
                continue
            if not code.startswith("2"):
                raise RuntimeError(f"HTTP {code}（{url}）")
            final_url = url
            break
        if via == "anolis":
            b64 = sh_out(SSH + [f"base64 {remote_body}"], timeout=180)
            raw = base64.b64decode(b64)
        else:
            raw = open(local_body, "rb").read()
        try:
            body = raw.decode("utf-8")  # Rust read_to_string 同款：非 UTF-8 即失败
        except UnicodeDecodeError as e:
            raise RuntimeError(f"抓取响应体非 UTF-8（{final_url}）: {e}")
        if not rust_trim(body):
            raise RuntimeError(f"抓取 {final_url} 空响应体")
        text = html_to_text(body)
        sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return final_url, text, sha
    finally:
        if via == "local":
            try:
                os.remove(local_body)
            except OSError:
                pass
        else:
            try:
                sh_out(SSH + [f"rm -f {remote_body}"], timeout=60)
            except Exception:
                pass


def fetch_paper(source):
    """anolis 面优先（与判分面同机同路径，字节同源）；本机 curl 兜底。"""
    try:
        return _fetch_paper_via(source, "anolis")
    except Exception as e1:
        log(f"anolis 面摄取失败（{e1}），本机 curl 兜底")
        return _fetch_paper_via(source, "local")


# ------------------------------------------------------------ arXiv API 选题面
# 2026-10-29 供给扩容：原「cat:cs.SE/cs.AI × agent|harness|LLM 最新窗口」连续多轮
# 0 篇未见过的（2026-10-29 11:39/11:41/11:42 三轮实证）→ 查询面与 tools/portal-seeder.py
# 源① 逐字对齐：六类 × 七词全 catalog + submittedDate 近 60 天区间，深翻 10→60 页。
QUERY_CATS = "cat:cs.SE OR cat:cs.AI OR cat:cs.LG OR cat:cs.CL OR cat:cs.CR OR cat:cs.MA"
QUERY_TERMS = ("all:agent OR all:harness OR all:LLM OR all:benchmark OR all:eval "
               "OR all:reasoning OR all:tool")
WINDOW_DAYS = 180          # submittedDate 区间过滤：近 180 天（UTC 日界，arXiv 按 v1 提交日）
                           # 2026-10-30 产线续能批：60→180（60 天窗实测已被吃穿：
                           # 可翻 totalResults 15,563 → 41,869）
SCAN_PAGES = 120           # 深翻页上限（2026-10-29：10→60；2026-10-30：60→120 全 catalog
                           # 深翻，防无界刷 API；--scan-pages/FEEDER_SCAN_PAGES 可配）
PAGE_PAUSE_S = 3           # arXiv 出网礼仪（≥1s/请求；翻页间隔，与条目间隔 3s 同口径）
CAND_FACTOR = 8            # 候选尝试预算 = limit × 8（摄取失败不占额度，但要给扫描器
                           # 封顶：防止整窗 HTML 皆缺时把 120 页全翻完拖死一轮）

# --------------------------------------------- 扩源参数（2026-11-05 RT-E70 根治批）
# 停摆根因实证（tools/report-feeder.log 2026-11-02 09:52 轮）：基窗 180 天 × 六类 × 七词
# 按 submittedDate 倒序深翻，扫描预算（120 页 × 8 篇/页 = 960 篇 ≈ 最新 3-4 天）全落在
# 「门户已播种（known 1038 id）+ HTML 未生成（export.arxiv.org/html/<id> → 404）」的
# 新鲜边界上——48 页扫 384 篇仅 1 篇未见过的且摄取 404；而基窗可翻总量 41,592 篇
# （2026-11-05 实测 totalResults）根本没被摸到。旧层论文实测 HTML 齐全
# （html/2601.07338 → 200 362,925B；2602.20770 → 200 101,271B；2603.00601 → 200 220,730B）
# 且不在门户 180 天播种窗内（portal-seeder SEEDER_WINDOW_DAYS 默认同为 180）。
# 三路扩源默认全开、env 可调（撤 STOP 熔断后即生效，不改码）：
WINDOW_LADDER = (365, 730)  # 源②时间窗外推：基窗之外的非重叠旧层（天；UTC 日界同 api_query）
                            # FEEDER_WINDOW_LADDER 覆盖（逗号分隔；空=关；≤基窗值忽略）
EXTRA_CATS = "cat:cs.HC OR cat:cs.IR OR cat:cs.CY OR cat:cs.NE"   # 源③类目扩（FEEDER_EXTRA_CATS 覆盖，空=关）
EXTRA_TERMS = ("all:agentic OR all:RAG OR all:\"code generation\" OR all:\"program repair\" "
               "OR all:\"test generation\" OR all:\"tool use\" OR all:\"multi-agent\" "
               "OR all:fuzzing OR all:\"static analysis\" OR all:\"code review\" "
               "OR all:\"software engineering\" OR all:\"retrieval-augmented\"")
                            # 源③词表扩（FEEDER_EXTRA_TERMS 覆盖，空=关）
ALT_API = "semanticscholar"  # 源④备选 API（FEEDER_ALT_API 覆盖：off|semanticscholar）
ALT_API_URL = "https://api.semanticscholar.org/graph/v1/paper/search/bulk"
ALT_QUERIES = ("LLM agent", "agent benchmark", "LLM benchmark", "agent harness",
               "code agent", "LLM evaluation")   # S2 bulk 查询词（多词 AND 语义；实测
                            # 不吃 OR 语法："agent OR harness OR …" total=0；FEEDER_ALT_QUERIES 覆盖）
ALT_PAGE = 1000              # S2 bulk 单页条数（实测上限 1000；单页 ~60% 带 arXiv id）
ALT_RETRIES = 3              # FEEDER_ALT_RETRIES 覆盖
ALT_BACKOFF_S = 20           # FEEDER_ALT_BACKOFF_S 覆盖（429 时按响应 retryAfter 优先）
ALT_PACE_S = 4               # S2 出网礼仪（匿名共享池 429 频发，实测 3 连查即 429）
ALT_GRACE_S = 120            # FEEDER_ALT_GRACE_S 覆盖：源④独立墙钟预算（进入源④时起算）。
                            # 轮级预算（默认 150s）保护的是 scheduler 600s 子调用超时；arXiv
                            # 重试最坏 ~158s（4 次退避 25/50/75s）会吃穿轮预算——若因此把
                            # 源④挡在门外， outage 韧性路永登不了台。源④最坏 120s+158s=278s
                            # ≪ 600s，故给独立宽限而非放宽轮预算。
SOURCE_DRY_PAGES = 8         # FEEDER_SOURCE_DRY_PAGES 覆盖：单源连续零「未见过的」页 → 切源
SWITCH_AFTER_FAILS = 6       # FEEDER_SWITCH_AFTER_FAILS 覆盖：摄取连续失败 N 次 → 切源
                            # （2026-11-02 实证：新鲜边界候选连击 404 是「落 0 篇」直接根因）
MAX_API_CALLS = 400          # FEEDER_MAX_API_CALLS 覆盖：单轮全源 API 调用硬顶
STRATUM_DRY_PAGES = 3        # FEEDER_STRATUM_DRY_PAGES 覆盖：旧层连续零「26 前缀」页早停；
                            # 旧层首页全前截止（如 730d 层摸到 25xx）即整层跳过，省配额
MIN_ID_PREFIX = "26"         # 训练截止后新文口径（与既判「id 以 26 开头」同值，抽为常量）


def api_query(days=None):
    """选题查询面：六类 × 七词 AND submittedDate 近 days 天闭区间（运行时按 UTC 现算）。
    本机时区 CST(UTC+8) 而 arXiv submittedDate 是 UTC——必须用 UTC 日界取区间，
    否则窗口整体偏移 8h。start=当天-days 的 00:00，end=当天 23:59（末日含当天，
    防时钟/入库时差漏掉最新篇；实质窗口 ≥days 天）。"""
    days = WINDOW_DAYS if days is None else max(1, int(days))
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=days)).strftime("%Y%m%d") + "0000"
    end = now.strftime("%Y%m%d") + "2359"
    return f"({QUERY_CATS}) AND ({QUERY_TERMS}) AND submittedDate:[{start} TO {end}]"


def _utc_ymd_bounds(older_days, younger_days=None):
    """UTC 日界区间（arXiv submittedDate 按 UTC；本机 CST(UTC+8) 会整体偏 8h，
    必须 UTC 现算——口径同 api_query）。older_days/younger_days=距今年数（越大越旧），
    younger_days=None → 当天 23:59；边界日取 [00:00, 23:59] 闭区间（末日含当天）。"""
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=older_days)).strftime("%Y%m%d") + "0000"
    end = (now.strftime("%Y%m%d") + "2359" if younger_days is None
           else (now - timedelta(days=younger_days)).strftime("%Y%m%d") + "2359")
    return start, end


def api_query_range(older_days, younger_days=None, cats=QUERY_CATS, terms=QUERY_TERMS):
    """显式 UTC 日界区间 + 查询面（类目/词表可换）的查询串——时间窗外推旧层（源②）
    与类目词表扩源（源③）共用。older_days > younger_days（越旧越大）；两者相等或
    younger_days=None 时同 api_query 的单边窗口。"""
    start, end = _utc_ymd_bounds(older_days, younger_days)
    return f"({cats}) AND ({terms}) AND submittedDate:[{start} TO {end}]"


def ladder_strata(base_days, ladder):
    """时间窗外推阶梯 → 非重叠旧层 [(older_days, younger_days)]（由新到旧）。
    与基窗边界相接（衔接日与基窗 start 日重叠一天，known 去重兜底，无害）；
    ladder 中 ≤ base_days 的值忽略（不翻出与基窗重叠的区间）。"""
    edges = [base_days] + sorted(d for d in ladder if d > base_days)
    return [(edges[i], edges[i - 1]) for i in range(1, len(edges))]


def _http_get_text(url, timeout=90):
    """API 文本取数：本机 curl 优先，失败走 anolis 面（同款 curl argv）。"""
    try:
        p = subprocess.run(["curl", "-sS", "-m", "60", url],
                           capture_output=True, text=True, timeout=timeout)
        if p.returncode != 0:
            raise RuntimeError(f"curl 退出 {p.returncode}: {p.stderr.strip()[:160]}")
        return p.stdout
    except Exception as e_local:
        log(f"本机 API 取数失败（{e_local}），走 anolis 面")
        return sh_out(SSH + [f"curl -sS -m 60 {shlex.quote(url)}"], timeout=timeout + 30)


def api_feed(limit, start=0, days=None, query=None, deadline=None):
    """export.arxiv.org API：submittedDate 倒序，start 起翻 limit 篇。
    query 显式给定（源②旧层区间/源③扩类词）时用之，否则按 api_query(days) 现算
    （源①基窗口径不变）。合法 Atom 空 feed（start 越过结果集末尾＝区间翻尽）返回 []
    终止深翻，与限流/拒服的裸文本响应（"Rate exceeded."，无 <feed>）及 arXiv 内部错误
    条目（含 <entry> 但 id=arxiv.org/api/errors、无 abs/ <id>——解析为空即抛，不会
    误判成「翻尽」）区分——后两者仍走退避重试（fail-loud 不静默）。
    deadline（轮级墙钟）给定则重试循环受其约束：到点即止，不把整轮预算睡穿
    （2026-11-05 试跑实测：4 次退避最坏 ~158s > 轮预算 150s，会让源④备选 API
    被「轮预算到位」挡在门外——outage 韧性路必须可达）。"""
    params = {"search_query": query if query is not None else api_query(days),
              "sortBy": "submittedDate",
              "sortOrder": "descending", "start": start, "max_results": limit}
    url = API_URL + "?" + urllib.parse.urlencode(params)
    last_err = ""
    for attempt in range(1, API_RETRIES + 1):
        if deadline is not None and time.monotonic() > deadline:
            raise RuntimeError(f"轮级预算到位，停止 arXiv API 重试（已试 {attempt - 1} 次）")
        try:
            x = _http_get_text(url)
            if "<entry>" not in x:
                if "<feed" in x:
                    return []   # 合法空 feed：翻到窗口尾部（非故障，不再重试浪费配额）
                raise RuntimeError(f"API 无 entry（响应 {len(x)}B：{x[:80]!r}，疑似限流/拒服）")
            out = []
            for m in re.finditer(r"<entry>(.*?)</entry>", x, re.S):
                e = m.group(1)
                aid = re.search(r"<id>http://arxiv\.org/abs/(.*?)</id>", e)
                title = re.search(r"<title>(.*?)</title>", e, re.S)
                pub = re.search(r"<published>(.*?)</published>", e)
                if not (aid and title):
                    continue
                out.append({"id": re.sub(r"v\d+$", "", aid.group(1).strip()),
                            "title": " ".join(title.group(1).split()),
                            "published": (pub.group(1)[:10] if pub else "")})
            if not out:
                raise RuntimeError(f"API entry 解析为空（响应 {len(x)}B）")
            return out
        except Exception as e:
            last_err = str(e)
            log(f"arXiv API 第 {attempt}/{API_RETRIES} 次失败：{last_err}")
            if attempt < API_RETRIES:
                if deadline is not None and time.monotonic() > deadline:
                    raise RuntimeError("轮级预算到位，停止 arXiv API 退避重试"
                                       f"（已试 {attempt} 次，未及睡 {API_BACKOFF * attempt}s）")
                time.sleep(API_BACKOFF * attempt)
    raise RuntimeError(f"arXiv API 连续 {API_RETRIES} 次失败：{last_err}")


def _alt_api_text(url, retries=ALT_RETRIES, backoff=ALT_BACKOFF_S):
    """备选 API（Semantic Scholar）文本取数：429/超时按退避重试，尊重响应 retryAfter。
    与 arXiv 面解耦——arXiv 限流/内部错误时（2026-11-05 实测双路持续 5xx）本面仍可用。"""
    last = ""
    for attempt in range(1, retries + 1):
        try:
            p = subprocess.run(["curl", "-sS", "-m", "90",
                                "-w", "\nHTTP:%{http_code}", url],
                               capture_output=True, text=True, timeout=120)
            body, _, code = p.stdout.rpartition("\nHTTP:")
            if code == "200":
                return body
            last = f"HTTP {code}: {body[:120]}"
            wait = backoff * attempt
            m = re.search(r'"retryAfter":(\d+)', body)
            if m:
                wait = max(wait, int(m.group(1)) + 2)   # 服务端指名等待，从其意
        except Exception as e:                          # noqa: BLE001 —— 退避重试需兜底
            last = f"{type(e).__name__}: {str(e)[:120]}"
            wait = backoff * attempt
        log(f"备选 API 第 {attempt}/{retries} 次失败：{last}")
        if attempt < retries:
            time.sleep(wait)
    raise RuntimeError(f"备选 API 连续 {retries} 次失败：{last}")


def s2_alt_feed(query, token=None, page=ALT_PAGE):
    """源④：Semantic Scholar bulk search 单页。query 多词（AND 语义，实测不吃 OR
    语法："agent OR harness" → total=0），year=当年（26 前缀同款过滤），单页 page 条
    （实测上限 1000）。抽出 externalIds.ArXiv 归并为与 arXiv 源同款的 item 口径
    {"id","title","published"}（id 非新式 YYMM.NNNNN 的丢弃）。返回 (items, next_token)。"""
    year = datetime.now(timezone.utc).year
    params = {"query": query, "fields": "title,externalIds,year,publicationDate",
              "year": str(year)}
    if token:
        params["token"] = token
    url = ALT_API_URL + "?" + urllib.parse.urlencode(params)
    body = _alt_api_text(url)
    j = json.loads(body)
    out = []
    for d in j.get("data", []):
        ax = (d.get("externalIds") or {}).get("ArXiv")
        if not ax:
            continue
        aid = re.sub(r"v\d+$", "", str(ax).strip())
        if not ARXIV_ID_RE.match(aid):
            continue
        out.append({"id": aid,
                    "title": " ".join((d.get("title") or "").split()),
                    "published": (d.get("publicationDate") or "")[:10]})
    return out, j.get("token")


def iter_candidates(limit, known, scan_pages, days, stats, deadline=None,
                    ladder=(), extra_cats="", extra_terms="", alt_api=ALT_API,
                    alt_queries=ALT_QUERIES, steer=None, alt_grace_s=ALT_GRACE_S):
    """多源候选流（2026-11-05 RT-E70 扩源根治）：源①现役基窗 → 源②时间窗外推旧层 →
    源③类目/词表扩（基窗+各旧层）→ 源④备选 API（S2 bulk）。逐条 yield 未做过/在途的
    候选（惰性：边取边摄）。

    2026-10-30 产线续能批口径不变：摄取失败的候选不占额度；候选尝试预算
    limit × CAND_FACTOR 全源共享；arXiv 翻页/条目间隔 PAGE_PAUSE_S 出网礼仪。
    本批新增的源切换/配额护栏（不弱化既有护栏，只为「耗尽的源吃不光轮预算」）：
      · 轮级墙钟预算入页循环（deadline，run() 传 round_t0+budget）：页间即查；
      · 单源连续 SOURCE_DRY_PAGES 页零「未见过的」→ 切下一源（仅非旧层源；旧层年轻
        边缘可能整段落在门户播种区内，误伤会够不到新鲜旧层——旧层靠「前截止早停 +
        轮预算 + API 硬顶」兜底）；
      · 摄取连续失败达 SWITCH_AFTER_FAILS（run() 经 steer 置位）→ 切下一源；
      · arXiv API 重试耗尽（限流/内部错误）→ 置 arxiv_down，跳过余下 arXiv 源直送源④；
        api_feed 重试循环受 deadline 约束（到点即止，不把轮预算睡穿）；
      · 源④备选 API 持独立墙钟 alt_grace_s（默认 120s，进入时起算）：arXiv 重试最坏
        ~158s 会吃穿轮级预算，outage 韧性路不能因此被挡（最坏 278s ≪ scheduler 600s）；
      · 旧层（源②/源③的 stratum）首页全「前截止 id」即整层跳过、连续 STRATUM_DRY_PAGES
        页零「26 前缀」即停层（730 天层摸到的全是 25xx，一篇都不能用，别烧配额）；
      · 单轮全源 API 调用硬顶 MAX_API_CALLS。
    stats 累计 pages/scanned/fresh 总量与 sources 分源计数，供日志汇总。"""
    budget = max(1, limit) * CAND_FACTOR
    tried = 0
    api_calls = 0
    state = {"arxiv_down": False}
    stats.setdefault("sources", {})

    def over_deadline():
        return deadline is not None and time.monotonic() > deadline

    def over_cap():
        return api_calls >= MAX_API_CALLS

    def src_stats(name):
        return stats["sources"].setdefault(
            name, {"pages": 0, "scanned": 0, "fresh": 0})

    def walk_arxiv(name, query, stratum):
        """单个 arXiv 查询源：按页深翻、惰性 yield 未见过的候选（源①/②/③ 同机制）。"""
        nonlocal api_calls, tried
        s = src_stats(name)
        dry_fresh = 0    # 连续零「未见过的」页（切源信号）
        dry_prefix = 0   # 连续零「26 前缀」页（旧层早停信号）
        for page in range(scan_pages):
            if over_deadline() or over_cap():
                log(f"源[{name}]：轮预算/API 调用顶到位（第 {page} 页未起），收源")
                return
            api_calls += 1
            try:
                batch = api_feed(limit * 2, start=page * limit * 2, query=query,
                                 deadline=deadline)
            except Exception as e:                      # noqa: BLE001 —— 切源须兜底
                log(f"源[{name}] arXiv API 失败（{e}）——置 arxiv_down，"
                    f"跳过余下 arXiv 源，直送源④备选 API")
                state["arxiv_down"] = True
                return
            s["pages"] = page + 1
            stats["pages"] += 1
            if not batch:
                log(f"源[{name}]：合法空 feed（该区间翻尽），共 {s['pages']} 页")
                return
            stats["scanned"] += len(batch)
            s["scanned"] += len(batch)
            usable = sum(1 for it in batch if it["id"].startswith(MIN_ID_PREFIX))
            if usable == 0:
                dry_prefix += 1
                if stratum and (page == 0 or dry_prefix >= STRATUM_DRY_PAGES):
                    why = "首页即无可用 id" if page == 0 else f"连续 {dry_prefix} 页无可用 id"
                    log(f"源[{name}]：旧层 {why}（整层前截止？），停层省配额")
                    return
            else:
                dry_prefix = 0
            page_fresh = 0
            for it in batch:
                if it["id"] in known:
                    continue
                page_fresh += 1
                stats["fresh"] += 1
                s["fresh"] += 1
                tried += 1
                yield it
                if steer is not None and steer.get("switch"):
                    log(f"源[{name}]：摄取连续失败切换信号到位，收源转下一源")
                    return
                if tried >= budget:
                    return
            if page_fresh == 0:
                dry_fresh += 1
                # 干页切源只作用于非旧层源：旧层的年轻边缘可能整段落在门户 180 天
                # 播种区内（基窗调小时必然如此），8 干页会把它掐在新鲜旧层之前——
                # 旧层改由「前截止早停 + 轮预算 deadline + API 硬顶」三道兜底。
                if not stratum and dry_fresh >= SOURCE_DRY_PAGES:
                    log(f"源[{name}]：连续 {dry_fresh} 页零未见过的（该区间已被 known "
                        f"吃穿），切下一源")
                    return
            else:
                dry_fresh = 0
            if len(batch) < limit * 2:
                log(f"源[{name}]：不满页（{len(batch)}<{limit * 2}），该区间翻尽")
                return
            if page + 1 < scan_pages:
                time.sleep(PAGE_PAUSE_S)   # arXiv 出网礼仪（≥1s/请求）

    def walk_alt(name, queries):
        """源④：备选 API 逐查询词取单页，惰性 yield 未见过的候选。
        独立墙钟预算 alt_grace_s（从进入本路起算，不经轮级预算）：arXiv 重试最坏
        ~158s 会吃穿轮级预算，但 outage 韧性路必须可达（最坏 278s ≪ scheduler 600s）；
        MAX_API_CALLS 硬顶与 steer 切源护栏照旧。"""
        nonlocal api_calls, tried
        s = src_stats(name)
        alt_deadline = time.monotonic() + max(1, alt_grace_s)
        for qi, q in enumerate(queries):
            if time.monotonic() > alt_deadline or over_cap():
                log(f"源[{name}]：源④独立墙钟 {max(1, alt_grace_s):.0f}s/API 调用顶到位"
                    f"（查询 {qi} 未起），收源")
                return
            api_calls += 1
            try:
                items, _tok = s2_alt_feed(q)
            except Exception as e:                      # noqa: BLE001 —— 换词续试
                log(f"源[{name}] 查询 {q!r} 失败（{e}），继续下一查询词")
                continue
            s["pages"] += 1
            stats["pages"] += 1
            stats["scanned"] += len(items)
            s["scanned"] += len(items)
            for it in items:
                if it["id"] in known:
                    continue
                stats["fresh"] += 1
                s["fresh"] += 1
                tried += 1
                yield it
                if steer is not None and steer.get("switch"):
                    log(f"源[{name}]：摄取连续失败切换信号到位，收源")
                    return
                if tried >= budget:
                    return
            if qi + 1 < len(queries):
                time.sleep(ALT_PACE_S)     # S2 出网礼仪（匿名共享池 429 频发）

    # 源清单（顺序即优先级）：现役 → 时间窗外推 → 类目词表扩 → 备选 API
    expand_cats = f"({QUERY_CATS}) OR ({extra_cats})" if extra_cats else QUERY_CATS
    expand_terms = f"({QUERY_TERMS}) OR ({extra_terms})" if extra_terms else QUERY_TERMS
    strata = ladder_strata(days, ladder)
    arxiv_sources = [("源①现役基窗", api_query(days), False)]
    for older, younger in strata:
        arxiv_sources.append((f"源②外推旧层{older}d-{younger}d",
                              api_query_range(older, younger), True))
    if extra_cats or extra_terms:
        arxiv_sources.append(("源③扩类词-基窗",
                              api_query_range(days, cats=expand_cats,
                                              terms=expand_terms), False))
        for older, younger in strata:
            arxiv_sources.append((f"源③扩类词-旧层{older}d-{younger}d",
                                  api_query_range(older, younger, cats=expand_cats,
                                                  terms=expand_terms), True))
    for name, query, is_stratum in arxiv_sources:
        if tried >= budget:
            return
        if over_deadline():
            if state["arxiv_down"]:
                log("轮预算到位且 arXiv 硬失败在位：跳过余下 arXiv 源，直送源④备选 API")
                break
            log(f"轮预算到位，余下 arXiv 源（{name} 起）留待下轮")
            return
        if state["arxiv_down"]:
            log(f"arXiv API 硬失败在位，跳过 {name}")
            continue
        if steer is not None:
            steer.pop("switch", None)
        log(f"{name} 起（query={query[:100]}{'…' if len(query) > 100 else ''}）")
        yield from walk_arxiv(name, query, is_stratum)
    if alt_api and alt_api.lower() != "off":
        if tried >= budget:
            log("候选预算已用满，源④备选 API 不触发")
        else:
            # 源④不预先查轮级预算：其独立墙钟 alt_grace_s 自管（arXiv 重试吃穿轮预算时
            # outage 韧性路仍须可达）；MAX_API_CALLS 与 steer 切源护栏照旧。
            if steer is not None:
                steer.pop("switch", None)
            log(f"源④备选 API（{alt_api}）起：{len(alt_queries)} 个查询词"
                f"（独立墙钟 {max(1, alt_grace_s):.0f}s）")
            yield from walk_alt(f"源④{alt_api}", alt_queries)


# --------------------------------------------------------------- 去重过滤面


def sh_out(argv, timeout=90):
    p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(f"{argv[0]} 退出 {p.returncode}: {p.stderr.strip()[:200]}")
    return p.stdout


def known_ids():
    """已做过/在做的 arXiv id 集合：submitted.jsonl + report-r0 目录 + pending 条目 + 本机门户种子。"""
    known = set()
    # ① anolis submitted.jsonl（burn-runner 落账的 dedupe_key/task；rpt-/rf- 两种史前口径都覆盖。
    #   只从这两个字段抽 id——ts 是 unix 时间戳，整行撒网会抽出 9319.16154 这类假 id）
    try:
        for line in sh_out(SSH + [f"cat {SUBMITTED}"], timeout=60).splitlines():
            try:
                j = json.loads(line)
            except Exception:
                continue
            for field in (j.get("dedupe_key"), j.get("task")):
                if not isinstance(field, str):
                    continue
                for m in re.finditer(r"(\d{4})[.-](\d{4,5})", field):
                    known.add(f"{m.group(1)}.{m.group(2)}")
    except Exception as e:
        raise RuntimeError(f"读 submitted.jsonl 失败: {e}")
    # ② anolis report-r0 已有任务包目录（<slug>-<4d>-<4~5d>）
    try:
        for name in sh_out(SSH + [f"ls {DATA_ROOT}"], timeout=60).split():
            m = re.search(r"(\d{4})-(\d{4,5})$", name)
            if m:
                known.add(f"{m.group(1)}.{m.group(2)}")
    except Exception as e:
        raise RuntimeError(f"列 report-r0 失败: {e}")
    # ③ anolis 队列 pending（防与 burn-runner/路由器竞态重复入队）
    try:
        for name in sh_out(SSH + [f"ls {QUEUE_PENDING}"], timeout=60).split():
            m = (re.search(r"(\d{4})\.(\d{4,5})", name)
                 or re.search(r"(\d{4})-(\d{4,5})(?:\.json)?$", name))
            if m:
                known.add(f"{m.group(1)}.{m.group(2)}")
    except Exception as e:
        raise RuntimeError(f"列 pending 失败: {e}")
    # ④ 本机门户种子目录（kb-atoms-<slug>-<id>；portal 已派的不重复做 report；兼容 -r2 后缀）
    for d in glob.glob(TASK_SEEDS + "/kb-atoms-*-*"):
        m = re.search(r"(\d{4})\.(\d{4,5})(?:-r\d+)?$", d)
        if m:
            known.add(f"{m.group(1)}.{m.group(2)}")
    return known


SLUG_STOPWORDS = {"the", "a", "an", "on", "in", "of", "for", "and", "or", "to",
                  "with", "from", "by", "at", "as", "is", "are", "we", "our",
                  "its", "it", "this", "that", "new", "via", "using", "based"}


def slugify(title):
    """确定性 slug：标题首个非停用词、≥4 字符的字母数字词（小写、≤16 字符）。

    ≥4 是照既有手工 slug 的最短件（rivet/v3ast 均 5+）——"Can LLMs…" 取 can
    不如取 llms 有信息量；任务名带全 id，slug 仅作人读前缀，不会撞名。
    """
    for tok in re.split(r"[^A-Za-z0-9]+", title):
        t = tok.lower()
        if not t or len(t) < 4 or t in SLUG_STOPWORDS or t.isdigit():
            continue
        s = re.sub(r"[^a-z0-9]", "", t)[:16]
        if s:
            return s
    return "paper"


FOCUS_TMPL = ("研究焦点：{title}——提取其核心方法、任务构造、实验设置与关键数字、"
              "失败模式与适用边界。纪律：reader 笔记中每条 anchor/quote 必须为摄取快照文本的"
              "连续子串（逐字符复制，不得改写/重构/凭记忆补写）；writer 引用必须逐字取自 "
              "reader 笔记锚点，每条引用编号 [n] 在正文恰好出现一次。")


# ------------------------------------------------------------------- 主流程


def run(limit, dry_run, stop_file, window_days=None, scan_pages=None,
        ladder=(), extra_cats="", extra_terms="", alt_api=ALT_API,
        alt_queries=ALT_QUERIES, switch_after_fails=SWITCH_AFTER_FAILS,
        alt_grace_s=ALT_GRACE_S):
    if os.path.exists(stop_file):
        log(f"STOP 熔断在位（{stop_file}），本轮不跑")
        return 2
    days = WINDOW_DAYS if window_days is None else max(1, int(window_days))
    pages = SCAN_PAGES if scan_pages is None else max(1, int(scan_pages))
    log(f"report-feeder 起：limit={limit} dry_run={dry_run} window_days={days} "
        f"scan_pages={pages} window_ladder={list(ladder)} "
        f"extra_cats={'on' if extra_cats else 'off'} "
        f"extra_terms={'on' if extra_terms else 'off'} alt_api={alt_api} "
        f"alt_grace_s={max(1, alt_grace_s):.0f}")
    known = known_ids()
    log(f"已知/在途 id {len(known)} 个（submitted+report-r0+pending+task-seeds）")

    # 窗口耗尽修复（2026-10-28）：最新一页全是已知 id 时逐页深翻；翻页间隔 ≥1s 礼貌
    # 间隔（与条目间隔同口径）。
    # 2026-10-30 产线续能批：候选流改**惰性**（边取边摄）——旧口径先把候选池截断在
    # limit 条再逐条摄取，而新鲜边界上的论文 HTML 尚未生成（export.arxiv.org/html/<id>
    # → 404），摄取失败即吃掉整轮额度（2026-10-30 16:57-17:02 连续 6 轮真跑实测
    # 「API 选题 4 篇 → 落 0 篇」）。现在摄取失败不占额度，扫描器继续往后翻页，
    # 「深翻页 120」才真正生效。候选尝试预算 = limit × CAND_FACTOR（给扫描器封顶）。
    # 2026-11-05 RT-E70 根治批：单源深翻仍摸不到旧层（见 iter_candidates 注释的 11-02
    # 实证），候选流改多源阶梯（现役基窗→时间窗外推旧层→类目词表扩→备选 API），
    # 并加切源护栏：单源连续零新鲜页 / 摄取连续失败 / arXiv 硬失败 均切下一源。
    stats = {"pages": 0, "scanned": 0, "fresh": 0}

    plan_bytes = None
    if not dry_run:
        plan_bytes = sh_out(SSH + [f"cat {PLAN_SRC}"], timeout=60).encode()
        md5 = hashlib.md5(plan_bytes).hexdigest()
        if md5 != PLAN_MD5:
            log(f"plan.json 模板 md5 {md5} ≠ 锚 {PLAN_MD5}（ harnessdiag 计划被换？），拒跑")
            return 4
        log(f"plan.json 模板 md5 核对 OK（{md5}）")

    landed = 0
    # 轮级墙钟预算（2026-10-31：arXiv 限流期单候选摄取可 ~70s，limit×8 候选全慢超时
    # 时整轮 15-20min，超 scheduler 子调用超时 → feeder:fail → burn 队列断供实测）。
    # 到预算即收本轮：已落地照常入队，未落地下轮再试（feeder 幂等）。
    # 2026-11-05：预算同时传入候选流页循环（deadline），多源阶梯下任一源都不能把
    # 一轮的墙钟吃光（旧实现只在 yield 后查，零新鲜源会白翻满 scan_pages）。
    round_budget_s = float(os.environ.get("FEEDER_ROUND_BUDGET_S") or "150")
    round_t0 = time.monotonic()
    steer = {"switch": False}     # 切源信号：摄取连续失败置位，候选流换源时清零
    fails = 0                     # 连续摄取失败计数（任一成功即清零）
    feed = iter_candidates(limit, known, pages, days, stats,
                           deadline=round_t0 + round_budget_s, ladder=ladder,
                           extra_cats=extra_cats, extra_terms=extra_terms,
                           alt_api=alt_api, alt_queries=alt_queries, steer=steer,
                           alt_grace_s=alt_grace_s)
    for i, item in enumerate(feed):
        if landed >= limit:
            break
        if time.monotonic() - round_t0 > round_budget_s:
            log(f"轮级预算 {round_budget_s:.0f}s 到点：已落地 {landed}/{limit}，"
                f"尝试 {i} 候选后收轮（arXiv 慢/限流期不恋战，下轮再补）")
            break
        aid = item["id"]
        if not ARXIV_ID_RE.match(aid):
            log(f"跳过 {aid}：非新式 arXiv id")
            continue
        if not aid.startswith(MIN_ID_PREFIX):
            log(f"跳过 {aid}：非训练截止后新文（id 不以 {MIN_ID_PREFIX} 开头）")
            continue
        if aid in known:
            log(f"跳过 {aid}：已做过/在途（submitted/report-r0/pending/门户种子）")
            continue
        source = f"https://arxiv.org/html/{aid}"
        try:
            final_url, text, sha = fetch_paper(source)
        except Exception as e:
            log(f"跳过 {aid}：摄取失败 {e}")
            fails += 1
            if fails >= switch_after_fails:
                steer["switch"] = True
                log(f"摄取连续失败 {fails} 次 ≥ {switch_after_fails}：置切源信号"
                    f"（新鲜边界 HTML 未生成？转时间窗外推旧层/备选 API）")
            continue
        fails = 0
        slug = slugify(item["title"])
        task = f"{slug}-{aid.replace('.', '-')}"
        task_json = {
            "paper_url": source,
            "focus": FOCUS_TMPL.format(title=item["title"]),
            "paper_sha256": sha,
            "rubric_params": {},
            "registry_root": REGISTRY_ROOT,
        }
        entry = {"unit": "report", "task": task, "data_root": DATA_ROOT,
                 "profile": "glm-cp", "max_turns": 40, "spend_cap": 300,
                 "note": f"report-feeder: {item['title'][:60]}",
                 "dedupe_key": f"rf-{aid}"}
        print(f"选题 {aid} | {item['published']} | {item['title']}")
        print(f"  slug={slug} task={task} sha256={sha} text_len={len(text)} final_url={final_url}")
        print(f"  focus=研究焦点：{item['title']}——…")
        if dry_run:
            landed += 1
            if landed < limit:
                time.sleep(PAGE_PAUSE_S)   # arXiv 出网礼仪（≥1s/请求，干跑同样守）
            continue
        # ④ 任务包落 anolis（task.json + 复用 plan.json）
        local_dir = f"/tmp/report-feeder-{task}-{os.getpid()}"
        os.makedirs(local_dir, exist_ok=True)
        tj_path = local_dir + "/task.json"
        with open(tj_path, "w") as f:
            f.write(json.dumps(task_json, ensure_ascii=False, indent=1))
        with open(local_dir + "/plan.json", "wb") as f:
            f.write(plan_bytes)
        try:
            # 远端先建任务目录再逐文件 scp（scp -r 会把本地目录名原样带上，
            # 本地临时目录名 ≠ 任务名，必须显式建 <task>/ 再传两件）
            sh_out(SSH + [f"mkdir -p {DATA_ROOT}/{task}"], timeout=60)
            sh_out(["scp", "-q", tj_path, f"{ANOLIS}:{DATA_ROOT}/{task}/task.json"], timeout=120)
            sh_out(["scp", "-q", local_dir + "/plan.json",
                    f"{ANOLIS}:{DATA_ROOT}/{task}/plan.json"], timeout=120)
            # 落盘核对：远端两件 sha 必须与本机一致（防传输静默损坏）
            remote_sha = sh_out(SSH + [f"sha256sum {DATA_ROOT}/{task}/task.json "
                                       f"{DATA_ROOT}/{task}/plan.json"], timeout=60).split()
            local_sha = hashlib.sha256(open(tj_path, "rb").read()).hexdigest()
            plan_sha = hashlib.sha256(plan_bytes).hexdigest()
            if not (remote_sha and remote_sha[0] == local_sha and remote_sha[2] == plan_sha):
                raise RuntimeError(f"远端核对不符: remote={remote_sha} local_task={local_sha}")
        except Exception as e:
            log(f"{aid} 任务包落盘失败: {e}")
            sh_out(SSH + [f"rm -rf {DATA_ROOT}/{task}"], timeout=60)
            continue
        finally:
            for p in (tj_path, local_dir + "/plan.json"):
                try:
                    os.remove(p)
                except OSError:
                    pass
            try:
                os.rmdir(local_dir)
            except OSError:
                pass
        # ⑤ 队列条目入 pending（文件名序=优先级；50-report- 对齐 010-013 手工先例）
        entry_path = f"/tmp/report-feeder-entry-{task}-{os.getpid()}.json"
        with open(entry_path, "w") as f:
            f.write(json.dumps(entry, ensure_ascii=False))
        try:
            sh_out(["scp", "-q", entry_path,
                    f"{ANOLIS}:{QUEUE_PENDING}/{QUEUE_PREFIX}-report-{task}.json"], timeout=60)
            ok = sh_out(SSH + [f"ls {QUEUE_PENDING}/{QUEUE_PREFIX}-report-{task}.json"], timeout=60).strip()
            if not ok:
                raise RuntimeError("pending 条目落盘核对失败")
        except Exception as e:
            log(f"{aid} 队列条目落盘失败: {e}")
            continue
        finally:
            try:
                os.remove(entry_path)
            except OSError:
                pass
        log(f"入队 {aid}: {DATA_ROOT}/{task}/{{task.json,plan.json}} + "
            f"{QUEUE_PENDING}/{QUEUE_PREFIX}-report-{task}.json（dedupe_key=rf-{aid}）")
        known.add(aid)
        landed += 1
        if landed < limit:
            time.sleep(3)  # arXiv 出网礼仪（API 3s/次的精神）
    src_desc = "、".join(f"{n} {s['fresh']} 篇"
                        for n, s in stats.get("sources", {}).items() if s.get("fresh"))
    log(f"多源候选流小结：{src_desc or '各源均零未见过的'}（现役基窗 {days} 天 + 外推旧层 "
        f"{'、'.join(str(d) for d in ladder) or '无'} 天 + 类目词表扩"
        f"{'开' if (extra_cats or extra_terms) else '关'} + 备选 API {alt_api}；"
        f"共翻 {stats['pages']} 页、扫 {stats['scanned']} 篇，已知 {len(known)} 个全跳过；"
        f"摄取失败不占额度，切源/续翻至凑满 limit）")
    log(f"report-feeder 完：落 {landed} 篇（dry_run={dry_run}）")
    return 0


def main():
    ap = argparse.ArgumentParser(description="arXiv 新论文 → report 任务包 → 入队（养 report 道）")
    ap.add_argument("--limit", type=int, default=10, help="拉取/入队论文数上限（默认 10）")
    ap.add_argument("--dry-run", action="store_true", help="只打印选题+sha，不落盘不 scp")
    ap.add_argument("--stop-file", default=STOP, help=f"STOP 熔断文件路径（默认 {STOP}）")
    ap.add_argument("--window-days", type=int, default=None,
                    help=f"submittedDate 区间天数（默认 {WINDOW_DAYS}；FEEDER_WINDOW_DAYS 同效）")
    ap.add_argument("--scan-pages", type=int, default=None,
                    help=f"深翻页上限（默认 {SCAN_PAGES}；FEEDER_SCAN_PAGES 同效）")
    args = ap.parse_args()
    if args.limit < 1:
        print("--limit 必须 ≥1", file=sys.stderr)
        return 2
    # 环境变量口径同 tools/portal-seeder.py 的 SEEDER_WINDOW_DAYS/SEEDER_SCAN_PAGES：
    # 命令行 > 环境变量 > 内置默认（180 天 / 120 页）。
    window_days = args.window_days
    if window_days is None:
        try:
            window_days = int(os.environ.get("FEEDER_WINDOW_DAYS") or "0") or None
        except ValueError:
            window_days = None
    scan_pages = args.scan_pages
    if scan_pages is None:
        try:
            scan_pages = int(os.environ.get("FEEDER_SCAN_PAGES") or "0") or None
        except ValueError:
            scan_pages = None
    # 扩源三件套（2026-11-05 RT-E70 根治批）：只走 env（不增 CLI 面），命令行 > 环境变量
    # > 内置默认；显式空串=关。撤 STOP 熔断后即生效，不改码。
    def _env_ladder(name, default):
        raw = os.environ.get(name)
        if raw is None:
            return default          # 未设置 → 内置默认（365,730）
        raw = raw.strip()
        if not raw or raw.lower() == "off":
            return ()               # 显式空串/off → 关
        out = []
        for tok in raw.split(","):
            tok = tok.strip()
            if not tok:
                continue
            try:
                out.append(int(tok))
            except ValueError:
                print(f"{name} 含非整数 {tok!r}，忽略", file=sys.stderr)
        return tuple(out) if out else default

    def _env_int_or(name, default):
        try:
            return int(os.environ.get(name) or "0") or default
        except ValueError:
            return default

    ladder = _env_ladder("FEEDER_WINDOW_LADDER", WINDOW_LADDER)
    extra_cats = os.environ.get("FEEDER_EXTRA_CATS")
    if extra_cats is None:
        extra_cats = EXTRA_CATS
    extra_terms = os.environ.get("FEEDER_EXTRA_TERMS")
    if extra_terms is None:
        extra_terms = EXTRA_TERMS
    alt_api = (os.environ.get("FEEDER_ALT_API") or "").strip() or ALT_API
    alt_raw = (os.environ.get("FEEDER_ALT_QUERIES") or "").strip()
    alt_queries = (tuple(q.strip() for q in alt_raw.split(",") if q.strip())
                   if alt_raw else ALT_QUERIES)
    alt_grace_s = _env_int_or("FEEDER_ALT_GRACE_S", ALT_GRACE_S)
    switch_after_fails = _env_int_or("FEEDER_SWITCH_AFTER_FAILS", SWITCH_AFTER_FAILS)
    try:
        return run(args.limit, args.dry_run, args.stop_file,
                   window_days=window_days, scan_pages=scan_pages, ladder=ladder,
                   extra_cats=extra_cats, extra_terms=extra_terms, alt_api=alt_api,
                   alt_queries=alt_queries, switch_after_fails=switch_after_fails,
                   alt_grace_s=alt_grace_s)
    except Exception as e:
        log(f"顶层失败（fail-loud，未落盘部分已清理）: {e}")
        return 3


if __name__ == "__main__":
    sys.exit(main())
