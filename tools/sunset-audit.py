#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sunset-audit.py — 板面 sunset 报告器：扫描 state:merged 超 N 天卡并生成归档报告（D-116）。

出处注（卡面 factory-os#84，af-card/1.0 · task_id=sunset-audit-tool · 债号 D-116）：
  指令源 = D-115 入口卡（CloudCrane-Software/.github#29）指令正文逐字——
  「给 factory-os 加一个 tools/sunset-audit.py：扫描板上 state:merged 超 14 天的卡
  并生成归档报告」。本卡为夜轨C2 自编排演练合成指令拆解件（wave-08 残卡收编）。

功能（卡面验收命令集逐条对应）：
  · --days N        阈值天数，缺省 14（「超 N 天」按整数天取整：卡龄整天数 − N > 0）。
  · --out FILE      报告落点，缺省 stdout。
  · --selftest      内置夹具自测：合成 2 张 state:merged 卡（一超期一未超），断言
                    报告行数/字段/天数计算；零网络、零真板面、零凭据。
  · 单文件零第三方依赖（纯标准库）。
  · 报告逐卡含：卡号 / 债号（卡面 title→body 可抽到时，形如 D-116）/ 合线时刻 /
    超期天数；空扫时报告含口径行「扫描 N 张 state:merged 卡，0 张超 14 天」。

扫描口径（卡面证据面回读定标）：
  · 「板上」= GET /repos/{repo}/issues?state=open&labels=state:merged 分页拉全——
    开着且带 state:merged 标签的卡（合了线却还挂在板上的卡＝本器要抓的归档对象；
    已关卡不在板面，不属「板上」）。2026-11-08 板面实查：54 张 state:merged 卡全部
    已关，开着 0 张 ⇒ 真跑 0 行属预期（卡面证据段同款口径），非故障。
  · 合线时刻 = 该卡 timeline 最新「labeled: state:merged」事件时刻；缺事件时回退
    closed_at、再回退 updated_at（来源列注明 timeline:labeled / closed_at /
    updated_at，禁猜绿）。
  · 退出码：0=扫描成功（含 0 行）；3=API 传输/HTTP/解析失败（fail-closed——
    不可证不猜绿，禁把拉不到板面当「0 张」放行）；2=参数错误；selftest 失败=1。

凭据纪律（卡面禁项 P1）：
  · 令牌只从环境变量 GH_TOKEN / GITHUB_TOKEN 现读（可缺省=匿名读公开板面），
    禁 argv、禁落盘、禁日志、禁回显；本件零写入凭据面。

用法：
  python3 -I tools/sunset-audit.py --selftest
  python3 -I tools/sunset-audit.py --days 14 --out /tmp/sunset-audit-14d.md
  python3 -I tools/sunset-audit.py --repo CloudCrane-Software/factory-os

本件只读板面生成报告，不改任何板面状态（不开关卡、不动标签）——归档动作由
人/后续卡按报告执行，报告器本身只出证据面。
"""
import argparse
import json
import os
import re
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone

DEFAULT_REPO = "CloudCrane-Software/factory-os"
MERGE_LABEL = "state:merged"
DEFAULT_DAYS = 14
PER_PAGE = 100

# 债号抽取：D-<数字>（前后不得紧邻字母数字，防 D-116 命中 D-1160 之类）
DEBT_RX = re.compile(r"(?<![A-Za-z0-9])(D-[0-9]{1,4})(?![A-Za-z0-9])", re.IGNORECASE)

EXIT_OK = 0
EXIT_ARGS = 2
EXIT_TRANSPORT = 3


# ---------------------------------------------------------------- 时间小工具

def parse_ts(text):
    """GitHub ISO8601（Z 结尾）→ aware UTC datetime；坏值返回 None（禁猜）。"""
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def whole_days_between(later, earlier):
    """整天天数 = 向下取整（(later-earlier)//86400）；任一刻度为 None ⇒ None。"""
    if later is None or earlier is None:
        return None
    delta = later - earlier
    return int(delta.total_seconds()) // 86400


# ---------------------------------------------------------------- 纯判定面

def extract_debt(title, body):
    """卡面抽债号：先 title 后 body，形如 D-116；抽不到 ⇒ None（报告列「未抽到」）。"""
    for text in (title, body):
        if text:
            m = DEBT_RX.search(text)
            if m:
                return m.group(1).upper()
    return None


def card_age_and_overdue(merged_at, now, threshold_days):
    """→ (卡龄整天数, 超期天数)；未超 ⇒ 超期天数 None。合线时刻缺 ⇒ (None, None)。"""
    age = whole_days_between(now, merged_at)
    if age is None:
        return None, None
    over = age - threshold_days
    if over > 0:
        return age, over
    return age, None


def pick_merge_moment(card, events, now_unused=None):
    """合线时刻三分定标：timeline 最新 labeled:state:merged → closed_at → updated_at。

    card/events 为已解析的 dict/list（纯函数，selftest 直喂夹具）；网络拉取见
    fetch_timeline。返回 (datetime|None, 来源串)。
    """
    latest = None
    for ev in events or []:
        if ev.get("event") != "labeled":
            continue
        lab = ev.get("label") or {}
        if lab.get("name") != MERGE_LABEL:
            continue
        ts = parse_ts(ev.get("created_at"))
        if ts is not None and (latest is None or ts > latest):
            latest = ts
    if latest is not None:
        return latest, "timeline:labeled"
    ts = parse_ts(card.get("closed_at"))
    if ts is not None:
        return ts, "closed_at"
    return parse_ts(card.get("updated_at")), "updated_at"


def build_report(cards, now, threshold_days, repo):
    """纯函数：夹具卡列表 → (报告 markdown, 超期行列表)。

    cards 元素形如 {"number":int,"title":str,"body":str,"merged_at":datetime|None,
    "moment_source":str}（由 fetch_board+fetch_timeline 组装；selftest 直喂合成夹具）。
    """
    overdue_rows = []
    for c in sorted(cards, key=lambda x: x.get("number") or 0):
        age, over = card_age_and_overdue(c.get("merged_at"), now, threshold_days)
        if over is None:
            continue
        debt = extract_debt(c.get("title") or "", c.get("body") or "")
        overdue_rows.append({
            "number": c.get("number"),
            "debt": debt or "未抽到",
            "merged_at": c.get("merged_at").strftime("%Y-%m-%dT%H:%M:%SZ"),
            "moment_source": c.get("moment_source") or "-",
            "age_days": age,
            "overdue_days": over,
            "title": (c.get("title") or "").strip(),
        })

    lines = []
    lines.append("# sunset-audit 归档报告（state:merged 超 %d 天卡）" % threshold_days)
    lines.append("")
    lines.append("- 板：%s" % repo)
    lines.append("- 口径：板上 = 开着（state=open）且带 %s 标签的卡（合线未归档＝归档对象）；"
                 "合线时刻 = timeline 最新 labeled:%s 事件（缺则回退 closed_at / updated_at，"
                 "来源列注明）" % (MERGE_LABEL, MERGE_LABEL))
    lines.append("- 阈值：超 %d 天（--days，缺省 %d；超期天数 = 卡龄整天数 − 阈值）"
                 % (threshold_days, DEFAULT_DAYS))
    lines.append("- 生成时刻：%s（UTC）" % now.strftime("%Y-%m-%dT%H:%M:%SZ"))
    lines.append("- 扫描 %d 张 %s 卡，%d 张超 %d 天"
                 % (len(cards), MERGE_LABEL, len(overdue_rows), threshold_days))
    lines.append("")
    if not overdue_rows:
        lines.append("结论：无超期卡，无需归档动作（0 行属预期态，非故障）。")
    else:
        lines.append("## 超期卡清单（%d 张）" % len(overdue_rows))
        lines.append("")
        lines.append("| 卡号 | 债号 | 合线时刻 | 时刻来源 | 卡龄(天) | 超期(天) | 标题 |")
        lines.append("|---|---|---|---|---|---|---|")
        for r in overdue_rows:
            lines.append("| #%s | %s | %s | %s | %s | %s | %s |" % (
                r["number"], r["debt"], r["merged_at"], r["moment_source"],
                r["age_days"], r["overdue_days"], r["title"].replace("|", "\\|")))
        lines.append("")
        lines.append("处置提示：本器只出报告不改板面；逐卡归档动作（关卡/移板）由运营者按"
                     "报告执行。")
    lines.append("")
    return "\n".join(lines), overdue_rows


# ---------------------------------------------------------------- 板面拉取

def http_get_json(url, bearer, timeout):
    """GET → (解析体)；传输/HTTP/解析失败抛 FetchError（fail-closed，禁空值下传）。"""
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "factory-os-sunset-audit/1.0",
    }
    if bearer:
        headers["Authorization"] = "Bearer " + bearer
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise FetchError("GET 失败：%s（%s）" % (url, exc.__class__.__name__)) from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FetchError("响应非 JSON：%s" % url) from exc


class FetchError(Exception):
    pass


def fetch_board(api_base, repo, bearer, timeout):
    """分页拉开着且带 state:merged 标签的卡；任何一页失败即抛 FetchError。"""
    cards = []
    page = 1
    while True:
        url = ("%s/repos/%s/issues?state=open&labels=%s&per_page=%d&page=%d"
               % (api_base.rstrip("/"), repo, MERGE_LABEL, PER_PAGE, page))
        batch = http_get_json(url, bearer, timeout)
        if not isinstance(batch, list):
            raise FetchError("板面响应非列表（page=%d）" % page)
        cards.extend(batch)
        if len(batch) < PER_PAGE:
            return cards
        page += 1


def fetch_timeline(api_base, repo, number, bearer, timeout):
    url = ("%s/repos/%s/issues/%s/events?per_page=%d"
           % (api_base.rstrip("/"), repo, number, PER_PAGE))
    events = http_get_json(url, bearer, timeout)
    if not isinstance(events, list):
        raise FetchError("timeline 响应非列表（#%s）" % number)
    return events


def run_scan(api_base, repo, threshold_days, now, timeout=30, fetcher=None):
    """扫描编排：fetcher 可注入（selftest 全桩零网络）。→ (报告, 超期行)。"""
    if fetcher is None:
        bearer = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
        def fetcher(page_kind, number=None):
            if page_kind == "board":
                return fetch_board(api_base, repo, bearer, timeout)
            return fetch_timeline(api_base, repo, number, bearer, timeout)
    cards = []
    for raw in fetcher("board"):
        labels = {l.get("name") for l in raw.get("labels") or []}
        if MERGE_LABEL not in labels:
            continue
        events = fetcher("timeline", raw.get("number"))
        merged_at, source = pick_merge_moment(raw, events)
        cards.append({"number": raw.get("number"), "title": raw.get("title") or "",
                      "body": raw.get("body") or "", "merged_at": merged_at,
                      "moment_source": source})
    return build_report(cards, now, threshold_days, repo)


# ---------------------------------------------------------------- selftest

def run_selftest():
    """夹具自测：合成 2 张 state:merged 卡（一超期一未超），断言行数/字段/天数计算。

    零网络、零真板面、零凭据（卡面验收①口径）。
    """
    now = datetime(2026, 11, 8, 0, 0, 0, tzinfo=timezone.utc)
    over_card = {  # 合线 20 天前 ⇒ 卡龄 20，超期 6（阈值 14）
        "number": 1001, "title": "[wave-X][D-9001] 夹具超期卡", "body": "夹具",
        "merged_at": datetime(2026, 10, 19, 0, 0, 0, tzinfo=timezone.utc),
        "moment_source": "timeline:labeled"}
    fresh_card = {  # 合线 3 天前 ⇒ 未超
        "number": 1002, "title": "[wave-X] 夹具未超期卡（无债号）", "body": "夹具",
        "merged_at": datetime(2026, 11, 5, 0, 0, 0, tzinfo=timezone.utc),
        "moment_source": "updated_at"}

    fails = []
    n = 0

    def check(name, cond, detail=""):
        nonlocal n
        n += 1
        if not cond:
            fails.append("%s%s" % (name, ("（%s）" % detail) if detail else ""))

    # T1 行数：恰 1 行超期；未超卡不出现
    rep, rows = build_report([over_card, fresh_card], now, DEFAULT_DAYS, DEFAULT_REPO)
    check("T1a 超期行数=1", len(rows) == 1, "实得 %d" % len(rows))
    check("T1b 未超卡不入行", all(r["number"] != fresh_card["number"] for r in rows))
    check("T1c 口径行=扫描 2 张 state:merged 卡，1 张超 14 天",
          "扫描 2 张 %s 卡，1 张超 %d 天" % (MERGE_LABEL, DEFAULT_DAYS) in rep)

    # T2 字段：卡号/债号/合线时刻/时刻来源/卡龄/超期天数全列
    r = rows[0]
    check("T2a 卡号", r["number"] == 1001)
    check("T2b 债号抽到 D-9001", r["debt"] == "D-9001", "实得 %r" % r["debt"])
    check("T2c 合线时刻", r["merged_at"] == "2026-10-19T00:00:00Z")
    check("T2d 时刻来源", r["moment_source"] == "timeline:labeled")
    check("T2e 卡龄=20 天", r["age_days"] == 20, "实得 %r" % r["age_days"])
    check("T2f 超期=6 天", r["overdue_days"] == 6, "实得 %r" % r["overdue_days"])
    check("T2g 报告表行含卡号与债号",
          "| #1001 | D-9001 | 2026-10-19T00:00:00Z | timeline:labeled | 20 | 6 |" in rep)

    # T3 天数计算：阈值边界（14 天整=未超；15 天=超期 1）
    _, rows14 = build_report([dict(over_card, merged_at=datetime(
        2026, 10, 25, 0, 0, 0, tzinfo=timezone.utc))], now, 14, DEFAULT_REPO)
    check("T3a 恰 14 天不算超期", len(rows14) == 0)
    _, rows15 = build_report([dict(over_card, merged_at=datetime(
        2026, 10, 24, 0, 0, 0, tzinfo=timezone.utc))], now, 14, DEFAULT_REPO)
    check("T3b 15 天=超期 1 天", len(rows15) == 1 and rows15[0]["overdue_days"] == 1)

    # T4 空板面：0 行 + 口径行「扫描 0 张 … 0 张超 14 天」+ 结论行
    rep0, rows0 = build_report([], now, DEFAULT_DAYS, DEFAULT_REPO)
    check("T4a 空扫 0 行", len(rows0) == 0)
    check("T4b 空扫口径行", "扫描 0 张 %s 卡，0 张超 %d 天" % (MERGE_LABEL, DEFAULT_DAYS) in rep0)
    check("T4c 空扫结论行", "无需归档动作" in rep0)

    # T5 债号抽取：body 回退 + 抽不到=未抽到
    _, rows_b = build_report([dict(over_card, title="无债号标题", body="见 D-9002 约定")],
                             now, DEFAULT_DAYS, DEFAULT_REPO)
    check("T5a 债号 body 回退", rows_b[0]["debt"] == "D-9002")
    _, rows_c = build_report([dict(over_card, title="无债号", body="也没有")],
                             now, DEFAULT_DAYS, DEFAULT_REPO)
    check("T5b 抽不到=未抽到（仍出报告行）", rows_c[0]["debt"] == "未抽到")

    # T6 合线时刻回退链：无 labeled 事件 → closed_at → updated_at
    ts, src = pick_merge_moment({"closed_at": "2026-11-01T00:00:00Z",
                                 "updated_at": "2026-11-02T00:00:00Z"}, [])
    check("T6a 无事件回退 closed_at", ts == datetime(2026, 11, 1, tzinfo=timezone.utc)
          and src == "closed_at")
    ts2, src2 = pick_merge_moment({"closed_at": None,
                                   "updated_at": "2026-11-02T00:00:00Z"}, [])
    check("T6b 无事件无 closed_at 回退 updated_at",
          ts2 == datetime(2026, 11, 2, tzinfo=timezone.utc) and src2 == "updated_at")

    # T7 传输失败 fail-closed：桩 fetcher 抛 FetchError ⇒ run_scan 传抛（CLI 映射 rc=3）
    def bad_fetcher(kind, number=None):
        raise FetchError("桩传输失败")
    try:
        run_scan("https://api.github.com", DEFAULT_REPO, DEFAULT_DAYS, now,
                 fetcher=bad_fetcher)
        check("T7 传输失败必须传抛 FetchError", False)
    except FetchError:
        check("T7 传输失败传抛 FetchError", True)

    # T8 run_scan 全桩注入：板面+timeline 走桩，产报告与真函数同构
    def stub_fetcher(kind, number=None):
        if kind == "board":
            return [{"number": 1001, "title": "[D-9001] 夹具", "body": "",
                     "labels": [{"name": MERGE_LABEL}], "closed_at": None,
                     "updated_at": "2026-11-05T00:00:00Z"},
                    {"number": 1002, "title": "未超", "body": "",
                     "labels": [{"name": MERGE_LABEL}], "closed_at": None,
                     "updated_at": "2026-11-05T00:00:00Z"}]
        if number == 1001:
            return [{"event": "labeled", "label": {"name": MERGE_LABEL},
                     "created_at": "2026-10-19T00:00:00Z"}]
        return [{"event": "labeled", "label": {"name": MERGE_LABEL},
                 "created_at": "2026-11-05T00:00:00Z"}]
    rep_s, rows_s = run_scan("https://api.github.com", DEFAULT_REPO, DEFAULT_DAYS,
                             now, fetcher=stub_fetcher)
    check("T8a 全桩扫描=1 行超期", len(rows_s) == 1 and rows_s[0]["number"] == 1001)
    check("T8b 全桩口径行", "扫描 2 张 %s 卡，1 张超 %d 天"
          % (MERGE_LABEL, DEFAULT_DAYS) in rep_s)

    if fails:
        sys.stderr.write("SELFTEST FAIL %d/%d：\n" % (n - len(fails), n))
        for f in fails:
            sys.stderr.write("  " + f + "\n")
        return 1
    sys.stderr.write("SELFTEST OK %d/%d（行数/字段/天数计算/口径行/空扫/债号抽取/"
                     "时刻回退链/传输 fail-closed/全桩注入）\n" % (n, n))
    return 0


# ---------------------------------------------------------------- CLI

def main(argv):
    p = argparse.ArgumentParser(
        prog="sunset-audit.py",
        description="扫描板上 state:merged 超阈卡并生成归档报告（D-116；只读板面）")
    p.add_argument("--days", type=int, default=DEFAULT_DAYS,
                   help="阈值天数（缺省 14；超期天数 = 卡龄整天数 − 阈值）")
    p.add_argument("--out", default=None, help="报告落点（缺省 stdout）")
    p.add_argument("--repo", default=DEFAULT_REPO, help="板面仓（缺省 %s）" % DEFAULT_REPO)
    p.add_argument("--api-base", default="https://api.github.com",
                   help="API 根（缺省 https://api.github.com）")
    p.add_argument("--timeout", type=int, default=30, help="单请求超时秒（缺省 30）")
    p.add_argument("--selftest", action="store_true",
                   help="夹具自测（零网络零真板面，卡面验收①）")
    args = p.parse_args(argv)

    if args.selftest:
        return run_selftest()
    if args.days < 1:
        sys.stderr.write("--days 须 ≥1\n")
        return EXIT_ARGS

    now = datetime.now(timezone.utc)
    try:
        report, rows = run_scan(args.api_base, args.repo, args.days, now,
                                timeout=args.timeout)
    except FetchError as exc:
        sys.stderr.write("板面拉取失败（fail-closed，禁当 0 行放行）：%s\n" % exc)
        return EXIT_TRANSPORT

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(report)
        sys.stderr.write("报告已落 %s（扫描 %d 张，超期 %d 张）\n"
                         % (args.out, _scan_count(report, args.days),
                            len(rows)))
    else:
        sys.stdout.write(report)
    return EXIT_OK


def _scan_count(report, threshold_days):
    """从报告口径行回读扫描总数（仅供 --out 落盘时 stderr 提示，避免重复返回值）。"""
    m = re.search(r"扫描 (\d+) 张 %s 卡" % re.escape(MERGE_LABEL), report)
    return int(m.group(1)) if m else -1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
