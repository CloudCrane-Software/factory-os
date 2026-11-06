#!/usr/bin/env python3
"""portal-seeder — 门户任务种子自动供给器（实战改进 #2 + 冲刺批2 双新源 + 规划源③ 2026-10-29）

三源补种（--limit 为三源合计上限，默认 8；被 factory-scheduler 周期调用，水位制 open<15 才触发）：
  源① arXiv 扩类深翻页（2026-10-29 供给扩容：原四类×五词「最新窗口」三源合计耗尽 →
    六类×七词全 catalog + submittedDate 近 180 天区间）：cat:cs.SE/cs.AI/cs.LG/cs.CL/
    cs.CR/cs.MA ×（agent|harness|LLM|benchmark|eval|reasoning|tool），submittedDate
    倒序；最新页全是已知 id 时逐页深翻（SCAN_PAGES 120 页封顶、--scan-pages/SEEDER_SCAN_PAGES
    可配，防无界刷 API；口径同 tools/report-feeder.py 2026-10-28 窗口耗尽修法）；
    只种 26 开头的新篇。
  源② 经典回灌（存量精读）：读 kb/kb.db（只读连接）verified 原子的 paper 字段得存量精读
    语料，统计语料证据（evidence-cache abs/full，即原子 quote 的出处）中被引经典论文
    （ReAct/Reflexion/ToT 类，CLASSIC_PAPERS 名录，id 均经 arXiv API 2026-10-28 实测核对），
    按被引语料论文数排序生成候选，滤掉三重去重命中后构造 kb-atoms-cls-<id> 卡回灌门户
    （骨架/奖励口径照抄现有 kb-atoms 卡）。经典是老文，不经源①的「26 开头」过滤——
    这正是存量回灌的设计意图。
  源③ 规划驱动（2026-10-29 工单②）：读 计划/研究组/沙箱战役备战-20261028/规划-v1.json 的
    波次 targets（G1 未覆盖经典 / G3 断档论文），按波次优先级（P0>P1>P2，波次内保原序）
    出候选，过同一套三重去重 + card-lint 后构造 kb-atoms-pln-<id> 卡。规划文件缺失/不可
    解析时该源自动跳过并记日志，不阻塞其他源；规划 dedupe R4 标注「不重复立项」的目标
    （已在 kb-seed/paper-batch2/manifest.json，随批2走）按规划自身纪律剔除。
  三源配额：--classic-quota（默认 2，SEEDER_CLASSIC_QUOTA）给源② 预留额度；
    --planner-quota（默认 2，SEEDER_PLANNER_QUOTA）给源③ 预留额度（源①候选池远大，
    无预留则源②/源③永远排不上；单选 --source planner 时配额让回 limit）；候选为空的源
    配额自动让回源①，三源合计始终 ≤limit；--classic-quota 0 即退回纯源① 先到先得。

生卡（三源同骨架）：证据缓存 → problem.md（w4 模板换 id + 真标题 + 全文缺失降级声明）→
  AGENTS.md（_AGENTS_template.md 副本）→ meta.json（reward 口径照抄 kb-atoms 卡）→
  card-lint 八条硬指标全绿才 scp gov（fail-closed：不过即撤本地卡不发布）。

护栏与语义（保持既有）：
  STOP 文件熔断（SB/.seeder-STOP，先于一切取数，打印「STOP 熔断在位」并返回）；
  幂等：evidence-cache 目录名 + task-seeds 目录名内嵌 arXiv id + gov data/tasks 目录名
  三重并集去重，已种不重种；证据缓存复用（abs.md <5KB 重抓，full.md <2KB 改名降级）；
  --limit 默认 8；scp 目标 GOV:/opt/company/af-jobs/data/tasks/；无 w4 模板即退出。
  新增（既有调用面零变化）：--dry-run 只算候选、不建卡不抓证据不 scp（日志仍留痕，
  与 report-feeder 的 dry-run 同款）；--no-scp 只落本地；--source arxiv|classic|planner|all
  选源（默认 all）；--classic-quota N 调源② 配额；--planner-quota N 调源③ 配额。
  2026-10-29 供给扩容：--scan-pages N 调源① 深翻页上限（默认 120，SEEDER_SCAN_PAGES 同效）；
  --window-days N 调 submittedDate 区间天数（默认 180，SEEDER_WINDOW_DAYS 同效）。
  2026-10-30 产线续能批（窗口加深）：默认窗口 60→180 天、深翻上限 60→120 页（可配不变）——
  60 天窗在 2026-10-30 实测已被吃穿（feeder 每轮落 0 篇），180 天窗把可翻供给从
  15,563 篇（60 天实测 totalResults）扩到 41,869 篇（180 天实测）。
  规划文件可用 SEEDER_PLANNER_JSON 改道（副本/DRY 验证用）。SB/GOV 可用 SEEDER_SB/SEEDER_GOV
  覆盖（副本/DRY 验证用，不动生产面）。日志追加落 SB/portal-seeder.log。
回滚：停跑；删 task-seeds/kb-atoms-{w4,cls,pln}-<id> 与 gov 同名任务目录即可。"""
import importlib.util
import json
import os
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime, timedelta, timezone

WS = "/home/pan-ding/workspace/agent黑灯工厂"
SB = os.environ.get("SEEDER_SB") or WS + "/kb-seed/sandbox"
GOV = os.environ.get("SEEDER_GOV") or "root@gov-host.invalid"
STOP = SB + "/.seeder-STOP"
LOG = SB + "/portal-seeder.log"

# ---- 源① arXiv 扩类（2026-10-29 供给扩容：四类×五词最新窗口 → 六类×七词全 catalog
#      + submittedDate 近 60 天区间；查询面与 tools/report-feeder.py 逐字对齐）----
API_URL = "https://export.arxiv.org/api/query"
QUERY_CATS = "cat:cs.SE OR cat:cs.AI OR cat:cs.LG OR cat:cs.CL OR cat:cs.CR OR cat:cs.MA"
QUERY_TERMS = ("all:agent OR all:harness OR all:LLM OR all:benchmark OR all:eval "
               "OR all:reasoning OR all:tool")
WINDOW_DAYS = 180          # submittedDate 区间过滤：近 180 天（UTC 日界，arXiv 按 v1 提交日）
                           # 2026-10-30 产线续能批：60→180（60 天窗已被吃穿，实测可翻
                           # totalResults 15,563 → 41,869）
SCAN_PAGES = 120           # 深翻页上限（2026-10-29：10→60；2026-10-30：60→120 全 catalog
                           # 深翻；--scan-pages/SEEDER_SCAN_PAGES 可配，防无界刷 API）
API_RETRIES = 3            # arXiv API 限流退避重试
API_BACKOFF = 20
PAGE_PAUSE_S = 3           # arXiv 出网礼仪（≥1s/请求；沿用 3s/次既有口径）
FETCH_PAUSE_S = 2          # 证据抓取礼仪（≥1s/请求：abs→full 不连发，防 burst 触发限流）


def build_query(days=None):
    """源① 查询面：六类 × 七词 AND submittedDate 近 days 天闭区间（运行时按 UTC 现算）。

    本机时区 CST(UTC+8)，arXiv submittedDate 是 UTC——必须用 UTC 日界取区间，
    否则窗口整体偏移 8h。start=当天-days 的 00:00，end=当天 23:59（末日含当天，
    防时钟/入库时差漏掉最新篇；实质窗口 ≥days 天）。默认 WINDOW_DAYS=180（可配）。"""
    days = WINDOW_DAYS if days is None else max(1, int(days))
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=days)).strftime("%Y%m%d") + "0000"
    end = now.strftime("%Y%m%d") + "2359"
    return f"({QUERY_CATS}) AND ({QUERY_TERMS}) AND submittedDate:[{start} TO {end}]"

# ---- 源② 经典回灌（存量精读）----
KB_DB = WS + "/kb/kb.db"   # 只读（mode=ro）；kb/ 包已过全量门，本脚本绝不写
# 被引经典名 → 规范 arXiv id。id 均于 2026-10-28 经 arXiv API id_list 实测核对
# （如 2307.16789=ToolLLM/ToolBench 论文）；AutoGPT 无规范 arXiv 论文故不入名录。
CLASSIC_PAPERS = {
    "ReAct": "2210.03629",
    "Reflexion": "2303.11366",
    "Tree-of-Thoughts": "2305.10601",
    "Tree of Thoughts": "2305.10601",
    "Chain-of-Thought": "2201.11903",
    "Chain of Thought": "2201.11903",
    "Self-Consistency": "2203.11171",
    "Least-to-Most": "2205.10625",
    "MRKL": "2205.00445",
    "Voyager": "2305.16291",
    "Toolformer": "2302.04761",
    "ToolLLM": "2307.16789",
    "HuggingGPT": "2303.17580",
    "Generative Agents": "2304.03442",
    "MetaGPT": "2308.00352",
    "CAMEL": "2303.17760",
    "ChatDev": "2307.07924",
    "AgentVerse": "2308.10848",
    "WebArena": "2307.13854",
    "AgentBench": "2308.03688",
    "GAIA": "2311.12983",
    "OSWorld": "2404.07972",
    "Graph of Thoughts": "2308.09687",
    "Program of Thoughts": "2211.12588",
    "Program-aided Language Models": "2211.10435",
    "SWE-bench": "2310.06770",
    "SWE-agent": "2405.15793",
    "AutoGen": "2308.08155",
    "OpenHands": "2407.16741",
}
ARXIV_ID_RE = re.compile(r"^\d{4}\.\d{4,5}$")


def sh(cmd, timeout=90):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout).stdout


def log(msg):
    """stdout + 追加落盘（调度面 sh() 只捕获不回显，日志是唯一可查轨迹）。"""
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError as e:
        print(f"(seeder 日志落盘失败: {e})", flush=True)


# --------------------------------------------------------------- 三重去重（既有口径）


def used_ids():
    """三重去重集：evidence-cache 目录名 + task-seeds 目录名内嵌 arXiv id + gov data/tasks 目录名。
    返回 {腿名: id 集合}（并集即 used）。"""
    legs = {"evidence-cache": set(), "task-seeds": set(), "gov": set()}
    ev = SB + "/evidence-cache"
    if os.path.isdir(ev):
        legs["evidence-cache"] |= {d for d in os.listdir(ev)}
    ts = SB + "/task-seeds"
    if os.path.isdir(ts):
        for d in os.listdir(ts):
            m = re.search(r"(\d{4}\.\d{4,5})", d)
            if m:
                legs["task-seeds"].add(m.group(1))
    gov = sh(f"ssh -o BatchMode=yes -o ConnectTimeout=10 {GOV} 'ls /opt/company/af-jobs/data/tasks/'", 60)
    if not gov.strip():
        log("gov tasks 列表为空（ssh 失败或目录空）：三重去重退化为本机两源")
    for d in gov.split():
        # 2026-10-28 修：原正则 r"(\d{4})-(\d{{4,5}})" 双残——非 f-string 里字面双花括号
        # 永失配，且分隔符写 "-" 而 gov 卡目录用的是 "."（与 task-seeds 同形，scp 副本），
        # gov 这条腿实为死代码。修为 [.-] 兼容 + 锚定卡名尾部（防把时间戳目录误抽成假 id）。
        m = re.search(r"(\d{4})[.-](\d{4,5})(?:-r\d+)*(?:-\d+)*$", d)
        if m:
            legs["gov"].add(f"{m.group(1)}.{m.group(2)}")
    return legs


# ------------------------------------------------- 源① arXiv 扩类 + 深翻页跳过已知 id


def api_feed(start, page_size, query):
    """export.arxiv.org API：扩类查询 submittedDate 倒序，start 起翻 page_size 篇。
    query 由 build_query() 现算（六类×七词 AND submittedDate 近 180 天区间，默认值）。
    合法 Atom 空 feed（start 越过结果集末尾＝窗口翻尽）返回 [] 终止深翻，与限流/拒服的
    裸文本响应（"Rate exceeded."，无 <feed>）区分——后者仍走退避重试（fail-loud 不静默）。"""
    params = {"search_query": query, "sortBy": "submittedDate",
              "sortOrder": "descending", "start": start, "max_results": page_size}
    url = API_URL + "?" + urllib.parse.urlencode(params)
    last = ""
    for attempt in range(1, API_RETRIES + 1):
        try:
            x = sh(f"curl -s --max-time 60 {shlex.quote(url)}", 90)
            if "<entry>" not in x:
                if "<feed" in x:
                    return []   # 合法空 feed：翻到窗口尾部（非故障，不再重试浪费配额）
                raise RuntimeError(f"API 无 entry（响应 {len(x)}B：{x[:60]!r}，疑似限流/拒服）")
            out = []
            for m in re.finditer(r"<entry>(.*?)</entry>", x, re.S):
                e = m.group(1)
                aid = re.search(r"<id>http://arxiv\.org/abs/(.*?)</id>", e)
                title = re.search(r"<title>(.*?)</title>", e, re.S)
                if not (aid and title):
                    continue
                out.append({"id": re.sub(r"v\d+$", "", aid.group(1).strip()),
                            "title": " ".join(title.group(1).split())})
            if not out:
                raise RuntimeError(f"API entry 解析为空（响应 {len(x)}B）")
            return out
        except Exception as e:
            last = str(e)
            log(f"arXiv API 第 {attempt}/{API_RETRIES} 次失败：{last}")
            if attempt < API_RETRIES:
                time.sleep(API_BACKOFF * attempt)
    log(f"arXiv API 连续 {API_RETRIES} 次失败，源①本轮为空（fail-loud，不静默放行）：{last}")
    return []


def arxiv_fresh(used, limit, query=None, scan_pages=None):
    """源①：扩类查询 + 深翻页跳过已知 id（report-feeder 2026-10-28 修法同款）。
    query=None 按 build_query() 现算（六类×七词 + submittedDate 近 180 天区间）；
    scan_pages=None 用 SCAN_PAGES（默认 120，全 catalog 深翻上限）。
    返回 (fresh, stats)：fresh 至多 limit 篇 26 开头未见过的 {id,title}。"""
    query = query or build_query()
    scan_pages = SCAN_PAGES if scan_pages is None else max(1, int(scan_pages))
    page = max(limit * 2, 20)
    fresh, seen = [], set()
    stats = {"scanned": 0, "hit_used": 0, "hit_old": 0, "pages": 0}
    for p in range(scan_pages):
        batch = api_feed(p * page, page, query)
        stats["pages"] = p + 1
        if not batch:
            break
        stats["scanned"] += len(batch)
        for it in batch:
            if it["id"] in seen:
                continue
            seen.add(it["id"])
            if not it["id"].startswith("26"):
                stats["hit_old"] += 1
                continue
            if it["id"] in used:
                stats["hit_used"] += 1
                continue
            fresh.append(it)
            if len(fresh) >= limit:
                break
        if len(fresh) >= limit or len(batch) < page:
            break
        time.sleep(PAGE_PAUSE_S)
    return fresh[:limit], stats


# --------------------------------------- 源② 经典回灌：kb verified 语料被引统计（kb 只读）


def corpus_papers():
    """kb/kb.db verified 原子的 paper 字段统计（只读连接；kb/ 包不得写）。
    返回 {paper: verified 原子数}。"""
    out = {}
    try:
        con = sqlite3.connect(f"file:{KB_DB}?mode=ro", uri=True)
        try:
            for paper, n in con.execute(
                    "SELECT paper, COUNT(*) FROM atoms WHERE status='verified' "
                    "AND paper IS NOT NULL AND paper != '' GROUP BY paper"):
                out[str(paper).strip()] = int(n)
        finally:
            con.close()
    except Exception as e:
        log(f"kb 库读取失败（源② 经典回灌降级为空，源① 不受影响）：{e}")
    return out


def classic_candidates(used):
    """源②：存量精读语料中被引经典统计 → 候选清单（按被引语料论文数降序，滤三重去重命中）。
    语料 = verified 原子的 paper 字段 ∩ evidence-cache（原子 quote 的出处证据）。
    返回 (cands, stats)：cands=[{id,name,mentions,papers}]。"""
    corpus = corpus_papers()
    stats = {"corpus_papers": 0, "corpus_atoms": 0, "classics_detected": 0, "hit_used": 0}
    canon = {}
    for name, arx in CLASSIC_PAPERS.items():
        canon.setdefault(arx, name)
    cites = {}
    for paper in sorted(corpus):
        d = SB + f"/evidence-cache/{paper}"
        if not os.path.isdir(d):
            continue
        stats["corpus_papers"] += 1
        stats["corpus_atoms"] += corpus[paper]
        text = ""
        for f in ("abs.md", "full.md"):
            p = os.path.join(d, f)
            if os.path.isfile(p):
                try:
                    text += open(p, encoding="utf-8", errors="replace").read()
                except OSError:
                    pass
        for name, arx in CLASSIC_PAPERS.items():
            n = len(re.findall(r"\b" + re.escape(name) + r"\b", text, re.I))
            if n:
                c = cites.setdefault(arx, {"id": arx, "name": canon[arx],
                                           "mentions": 0, "papers": set()})
                c["mentions"] += n
                c["papers"].add(paper)
    stats["classics_detected"] = len(cites)
    ranked = sorted(cites.values(), key=lambda c: (-len(c["papers"]), -c["mentions"], c["id"]))
    fresh = []
    for c in ranked:
        if c["id"] in used or not ARXIV_ID_RE.match(c["id"]):
            stats["hit_used"] += 1
            continue
        c = dict(c)
        c["papers"] = len(c["papers"])
        fresh.append(c)
    return fresh, stats


# ---- 源③ 规划驱动（2026-10-29 工单②：规划-v1.json 波次 targets）----
PLANNER_JSON = (os.environ.get("SEEDER_PLANNER_JSON")
                or WS + "/计划/研究组/沙箱战役备战-20261028/规划-v1.json")
PLANNER_WAVES = ("G1", "G3")                      # 工单指定：G1 未覆盖经典 / G3 断档论文
PLANNER_PRIORITY = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}   # 波次优先级（波次内既有序=稳定排序保序）


def planner_candidates(used):
    """源③：读规划-v1.json 波次 targets（G1 未覆盖经典/G3 断档论文），按波次优先级出候选，
    过三重去重（used 并集，口径同源②）。规划文件缺失/不可解析 → 该源自动跳过并记日志
    （不阻塞其他源，fail-open 于本源、fail-closed 于卡片质量闸）。
    arXiv id 抽取：G1 item 形如 "WebArena 2307.13854"（尾 token）；G3 item 形如
    "2610.36254"（本体）。规划 dedupe R4：action 含「不重复立项」的目标（已在
    paper-batch2 清单、随批2走）按规划自身纪律剔除，不计候选。
    返回 (cands, stats)：cands=[{id,name,wave,priority,pri_rank,gap,action}]（按波次优先级排序）。"""
    stats = {"waves": 0, "targets": 0, "skip_batch2": 0, "bad_id": 0, "hit_used": 0}
    if not os.path.isfile(PLANNER_JSON):
        log(f"源③ 规划驱动：规划文件缺失（{PLANNER_JSON}），该源自动跳过（不影响其他源）")
        return [], stats
    try:
        plan = json.load(open(PLANNER_JSON, encoding="utf-8"))
    except Exception as e:
        log(f"源③ 规划驱动：规划文件解析失败（{str(e)[:80]}），该源自动跳过（不影响其他源）")
        return [], stats
    picked = []
    for w in plan.get("waves") or []:
        if str(w.get("gap_class") or "") not in PLANNER_WAVES:
            continue
        stats["waves"] += 1
        pri = str(w.get("priority") or "P9")
        rank = PLANNER_PRIORITY.get(pri.split("（")[0], 9)
        for t in w.get("targets") or []:
            stats["targets"] += 1
            item = str(t.get("item") or "")
            m = re.search(r"(\d{4}\.\d{4,5})", item)
            if not m or not ARXIV_ID_RE.match(m.group(1)):
                stats["bad_id"] += 1
                continue
            action = str(t.get("action") or "")
            if "不重复立项" in action:
                stats["skip_batch2"] += 1
                continue
            picked.append({"id": m.group(1), "name": item, "wave": str(w.get("wave_id") or ""),
                           "priority": pri, "pri_rank": rank, "gap": str(w.get("gap_class") or ""),
                           "action": action})
    picked.sort(key=lambda c: (c["pri_rank"], c["wave"]))   # 波次优先级；稳定排序保波次内原序
    fresh = []
    for c in picked:
        if c["id"] in used:
            stats["hit_used"] += 1
            continue
        fresh.append(c)
    return fresh, stats


# ---------------------------------------------------------------------- 生卡 + 过闸 + scp


def _full_page_ok(path):
    """full.md 是否为真全文页：<2KB 视为抓失败（既有口径），空 <title> 视为 arXiv 404
    空壳页（/html/ 对无 HTML 老文返回 6397B 的通用 404 页，光看大小会漏判——
    空壳页会让沙箱 quote 全 miss，必须降级为仅摘要页）。"""
    try:
        if os.path.getsize(path) < 2000:
            return False
        head = open(path, encoding="utf-8", errors="replace").read(20000)
        m = re.search(r"<title>(.*?)</title>", head, re.S | re.I)
        return bool(m and m.group(1).strip())
    except OSError:
        return False


def ensure_cache(arx):
    """证据缓存：abs.md（card-lint L4 要 >5KB，<5KB 视为抓失败重抓一次）；
    full.md 非真全文页 → 改名 full.unavailable.html 并判仅摘要页（降级声明由生卡方补，
    口径同 cross-verify.py:107-126 / event-router.py:150-163，另加 404 空壳页识别）；
    已有 full.unavailable.html 且无 full.md → 不再重抓（arXiv 确无 HTML 全文的老文）。"""
    d = SB + f"/evidence-cache/{arx}"
    os.makedirs(d, exist_ok=True)
    abs_f, full_f = d + "/abs.md", d + "/full.md"
    if not os.path.isfile(abs_f) or os.path.getsize(abs_f) < 5000:
        sh(f"curl -sL --max-time 40 https://arxiv.org/abs/{arx} -o {abs_f}", 90)
    if not os.path.isfile(full_f) and not os.path.isfile(d + "/full.unavailable.html"):
        time.sleep(FETCH_PAUSE_S)   # arXiv 出网礼仪（≥1s/请求：abs→full 不连发）
        sh(f"curl -sL --max-time 60 https://arxiv.org/html/{arx} -o {full_f}", 90)
    only_abs = False
    try:
        if not os.path.isfile(full_f) or not _full_page_ok(full_f):
            only_abs = True
            if os.path.isfile(full_f):
                os.rename(full_f, d + "/full.unavailable.html")
    except OSError:
        only_abs = True
    return abs_f, full_f, only_abs


def lint_gate(card_dir):
    """card-lint 八条硬指标（fail-closed：闸自身异常也视为不过；口径同 cross-verify.py:129-139）。"""
    try:
        spec = importlib.util.spec_from_file_location("cardlint", WS + "/tools/card-lint.py")
        cl = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cl)
        errs, _ = cl.lint_card(card_dir, cache=SB + "/evidence-cache")
        return errs
    except Exception as e:
        return [f"质量闸自身异常（fail-closed）: {e}"]


def seed_card(arx, tpl, tpl_id, ag, dry_run, no_scp, tag):
    """生卡并（过闸后）scp。tag：w4=源① 新文 / cls=源② 经典回灌。
    返回 seeded 描述串；None=跳过（原因已打印，fail-loud）。"""
    if dry_run:
        return f"[dry-run] kb-atoms-{tag}-{arx}"
    ev = SB + f"/evidence-cache/{arx}"
    os.makedirs(ev, exist_ok=True)
    abs_f, _, only_abs = ensure_cache(arx)
    if not os.path.isfile(abs_f) or os.path.getsize(abs_f) < 5000:
        log(f"跳过 {arx}：摘要页证据不可用（abs.md 缺失或 <5KB，card-lint L4 必挂）")
        return None
    html = open(abs_f, encoding="utf-8", errors="replace").read()
    m = re.search(r"<title>\[[^\]]*\] ([^<|]*)", html)
    title = (m.group(1).strip() if m else arx)[:60]
    d = SB + f"/task-seeds/kb-atoms-{tag}-{arx}"
    os.makedirs(d, exist_ok=True)
    prob = tpl.replace(tpl_id, arx)
    lines = prob.split("\n")
    if lines and lines[0].startswith("# "):
        # 模板标题行换成本篇真标题（旧版只换 id，problem.md 标题停留模板论文、与 meta.json 不一致）
        lines[0] = f"# {title} 论文知识原子抽取"
    prob = "\n".join(lines)
    if only_abs:
        prob = re.sub(r"^2\. 全文 HTML.*$",
                      "2. **该文 arXiv 未提供 HTML 全文**，全部 quote 只能取自摘要页原文",
                      prob, count=1, flags=re.M)
    open(d + "/problem.md", "w", encoding="utf-8").write(prob)
    open(d + "/AGENTS.md", "w", encoding="utf-8").write(ag)
    json.dump({"title": f"{title} 论文知识原子抽取", "type": "kb-atom-extraction",
               "est_load": "~30-60min CPU+web", "reward": "工厂积分记账（sandbox_report 入 MES）"},
              open(d + "/meta.json", "w", encoding="utf-8"), ensure_ascii=False)
    errs = lint_gate(d)
    if errs:
        log(f"卡片未过质量闸，不发布并撤本地卡：kb-atoms-{tag}-{arx} -> {'; '.join(errs)}")
        shutil.rmtree(d, ignore_errors=True)
        return None
    if not no_scp:
        sh(f"scp -q -r {d} {GOV}:/opt/company/af-jobs/data/tasks/", 90)
    log(f"seeded: kb-atoms-{tag}-{arx} {title[:50]}" + ("（--no-scp：未推 gov）" if no_scp else ""))
    return f"{arx} {title[:36]}"


# ------------------------------------------------------------------------------ 主流程


def main():
    args = sys.argv[1:]
    limit = 8
    if "--limit" in args:
        try:
            limit = int(args[args.index("--limit") + 1])
        except (IndexError, ValueError):
            print("--limit 需要整数参数", file=sys.stderr)
            return 2
    dry_run = "--dry-run" in args
    no_scp = dry_run or "--no-scp" in args
    scan_pages = None
    if "--scan-pages" in args:
        try:
            scan_pages = int(args[args.index("--scan-pages") + 1])
        except (IndexError, ValueError):
            print("--scan-pages 需要整数参数", file=sys.stderr)
            return 2
    else:
        try:
            scan_pages = int(os.environ.get("SEEDER_SCAN_PAGES") or "0") or None
        except ValueError:
            scan_pages = None
    window_days = None
    if "--window-days" in args:
        try:
            window_days = int(args[args.index("--window-days") + 1])
        except (IndexError, ValueError):
            print("--window-days 需要整数参数", file=sys.stderr)
            return 2
    else:
        try:
            window_days = int(os.environ.get("SEEDER_WINDOW_DAYS") or "0") or None
        except ValueError:
            window_days = None
    source = "all"
    if "--source" in args:
        i = args.index("--source")
        source = args[i + 1] if i + 1 < len(args) else "all"
        if source not in ("arxiv", "classic", "planner", "all"):
            print("--source 仅接受 arxiv|classic|planner|all", file=sys.stderr)
            return 2
    quota = 2
    if "--classic-quota" in args:
        i = args.index("--classic-quota")
        try:
            quota = int(args[i + 1])
        except (IndexError, ValueError):
            print("--classic-quota 需要整数参数", file=sys.stderr)
            return 2
    else:
        try:
            quota = int(os.environ.get("SEEDER_CLASSIC_QUOTA") or "2")
        except ValueError:
            quota = 2
    pquota = 2
    if "--planner-quota" in args:
        i = args.index("--planner-quota")
        try:
            pquota = int(args[i + 1])
        except (IndexError, ValueError):
            print("--planner-quota 需要整数参数", file=sys.stderr)
            return 2
    else:
        try:
            pquota = int(os.environ.get("SEEDER_PLANNER_QUOTA") or "2")
        except ValueError:
            pquota = 2
    quota = max(0, min(quota, limit))
    pquota = max(0, min(pquota, limit))
    if os.path.exists(STOP):
        print("STOP 熔断在位", flush=True)
        return
    ag = open(SB + "/task-seeds/_AGENTS_template.md", encoding="utf-8").read() \
        if os.path.exists(SB + "/task-seeds/_AGENTS_template.md") else ""
    if not ag:
        log("缺 _AGENTS_template.md：生卡必挂 L1/L5/L6，本轮不种")
    tpl = None
    for cand in sorted(os.listdir(SB + "/task-seeds")):
        if cand.startswith("kb-atoms-w4-"):
            tpl = open(SB + "/task-seeds/" + cand + "/problem.md", encoding="utf-8").read()
            break
    if not tpl:
        print("无 w4 模板可用，退出", flush=True)
        return
    m0 = re.search(r"(\d{4}\.\d{4,5})",
                   sorted([d for d in os.listdir(SB + "/task-seeds") if d.startswith("kb-atoms-w4-")])[0])
    tpl_id = m0.group(1)
    legs = used_ids()
    used = legs["evidence-cache"] | legs["task-seeds"] | legs["gov"]
    log(f"portal-seeder 起：limit={limit} dry_run={dry_run} source={source} "
        f"no_scp={no_scp} classic_quota={quota} planner_quota={pquota} "
        f"scan_pages={scan_pages or SCAN_PAGES} window_days={window_days or WINDOW_DAYS}"
        f"（模板 {tpl_id}）")
    log(f"三重去重集 {len(used)} 个 id：evidence-cache {len(legs['evidence-cache'])} + "
        f"task-seeds {len(legs['task-seeds'])} + gov {len(legs['gov'])}（腿间重叠不计）")

    # 先算源②/源③ 候选（均纯本地读，不触网）：经典/规划配额预留——源① 候选池远大（副本实测
    # 连跑 3 轮 ×8 篇未见底），若纯按 limit 先到先得，源②/源③ 永远排不上；配额制保证
    # 三源都实际供血。候选为空的源配额自动让回源①（不浪费供给额度），
    # 三源合计仍 ≤limit；单选 --source planner 时配额让回 limit。
    classics, st2 = [], {"corpus_papers": 0, "corpus_atoms": 0, "classics_detected": 0, "hit_used": 0}
    if source in ("classic", "all"):
        classics, st2 = classic_candidates(used)
    planner, st3 = [], {"waves": 0, "targets": 0, "skip_batch2": 0, "bad_id": 0, "hit_used": 0}
    if source in ("planner", "all"):
        planner, st3 = planner_candidates(used)
    classic_budget = min(quota, len(classics))
    planner_budget = min(pquota if source == "all" else limit, len(planner))
    arxiv_budget = max(0, limit - classic_budget - planner_budget)
    feed, st1 = [], {"scanned": 0, "hit_used": 0, "hit_old": 0, "pages": 0}
    if source in ("arxiv", "all"):
        feed, st1 = arxiv_fresh(used, arxiv_budget, query=build_query(window_days),
                                scan_pages=scan_pages)
    log(f"源① arXiv 扩类：扫 {st1['scanned']} 篇（{st1['pages']} 页，六类 cs.SE/AI/LG/CL/CR/MA "
        f"× 七词 agent|harness|LLM|benchmark|eval|reasoning|tool + submittedDate 近 "
        f"{window_days or WINDOW_DAYS} 天），26 前缀外 {st1['hit_old']}、去重命中 "
        f"{st1['hit_used']}，可种 {len(feed)} 篇（本轮预算 {arxiv_budget}）")
    log(f"arXiv 新 {len(feed)} 篇，去重后可种 {len(feed)} 篇")
    log(f"源② 经典回灌：语料 {st2['corpus_papers']} 篇 / {st2['corpus_atoms']} 个 verified 原子，"
        f"检出被引经典 {st2['classics_detected']} 种，去重命中 {st2['hit_used']}，"
        f"可种 {len(classics)} 篇（本轮配额 {classic_budget}）")
    for c in classics[:8]:
        log(f"  经典候选 {c['id']} {c['name']}：被 {c['papers']} 篇语料论文引用"
            f"（提及 {c['mentions']} 次）")
    log(f"源③ 规划驱动：{st3['waves']} 个波次 / {st3['targets']} 个 targets（G1 未覆盖经典 / "
        f"G3 断档论文），批2 不重复立项剔除 {st3['skip_batch2']}、三重去重命中 {st3['hit_used']}，"
        f"可种 {len(planner)} 个（本轮配额 {planner_budget}）")
    for c in planner[:8]:
        log(f"  规划候选 {c['id']} {c['name']}：{c['wave']}({c['priority']},{c['gap']}) "
            f"{c['action'][:36]}")
    # 本run层再去重：used 集不含本轮新种，跨源同 id（如源②检出与源③规划同列一篇）
    # 只按 源①>源②>源③ 先到先得种一次（tag 不同会各建一张卡，必须防）。
    seeded, seen = [], set()
    for it in feed:
        if len(seeded) >= limit or it["id"] in seen:
            continue
        seen.add(it["id"])
        r = seed_card(it["id"], tpl, tpl_id, ag, dry_run, no_scp, "w4")
        if r:
            seeded.append(r)
    for c in classics:
        if len(seeded) >= limit or c["id"] in seen:
            continue
        seen.add(c["id"])
        r = seed_card(c["id"], tpl, tpl_id, ag, dry_run, no_scp, "cls")
        if r:
            seeded.append(r)
    for c in planner:
        if len(seeded) >= limit or c["id"] in seen:
            continue
        seen.add(c["id"])
        r = seed_card(c["id"], tpl, tpl_id, ag, dry_run, no_scp, "pln")
        if r:
            seeded.append(r)
    log(f"[{time.strftime('%H:%M:%S')}] 补种 {len(seeded)} 张"
        + ("（dry-run：未落盘未 scp）" if dry_run else ""))
    return 0


if __name__ == "__main__":
    main()
