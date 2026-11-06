#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mes-ttl-sweep.py — MES 遗留数据"连续 7 天无人调用即自动删除"清扫器（本机旧锚点 CH）。

设计文档（判定式/arming 语义/回滚方法以此为准）：
    计划/研究组/mes-ttl-自删机制.md

对象（默认清单；--objects-file 可覆盖；EXEMPT 硬编码不可覆盖）：
  A. mes 库第一代遗留表 ×5：events_mt / bench_events / events_repl / agg_hourly / hourly_agg
     （整表粒度：归档→DROP TABLE）
  B. af_mes.mes_line_hour 的第一代陈旧行（行集粒度：仅当整表连续 7 天无查询时，
     才删除"与现役 af_mes.mes_event 对不上"的行；表仍在用就一行不删）
  永久豁免：af_mes.mes_event（现役活账本）、af_mes.mes_line_hour_mv（现役 MV）

调用探测：system.query_log，两路匹配都覆盖——
  ① tables 数组含 "<db>.<table>"（解析级，覆盖 SELECT/INSERT/DROP/ALTER 等）；
  ② query 文本含 "<db>.<table>"（限定名）或 current_database=<db> 时含裸表名，
     或 "SHOW TABLES FROM <db>" / "USE <db>"（数据库级内省，保守计为访问）。
  本工具自身查询一律带 User-Agent=mes-ttl-sweep/1.0，探测时整体排除（不自我续命）；
  CH 对 HTTP INSERT 的服务端重写条目（空 UA）按"同秒+工具身份 INSERT 原查询+
  tables 子集"归属排除（MV 场景下重写条目是原查询的超集，且第三方写入的 MV 目标
  信号只在重写条目里，故不用集合相等匹配）。

保守自 arming（双观测）：对象须连续两次巡检观测（间隔≥24h）都判定"7 天无调用"才可删；
  且 query_log 必须覆盖最近 min_history_days（默认 7）天——首上线前 7 天必然
  coverage 不足 → 只观测不删（dry-run 语义内置）。

安全阀：--dry-run（默认干跑）/ --enforce；--enforce 还须 arming 文件
  （工具状态备份/mes-ttl-arming.json，由主代理在观察期结束后手动放置）存在才真删。
  视图依赖闸：删表前若存在把它当源/目标的 MV/视图，且该视图不在本运行可删集合内，
  拒绝删除并留证（CH 允许留下悬空 MV；是否把依赖视图纳入对象清单归运营者裁决）。

留证：状态观测/mes-ttl-sweep.log（人类可读，每次执行一个块）
      + 工具状态备份/mes-ttl-sweep-evidence.jsonl（逐对象一行结构化：对象/行数/
        last_accessed/判定/动作）。
otel 库只读审计行（G8 施工员-B 2026-10-31 增补；collector-storage §2.6 建议的
  "每日 04:30 节奏上加一条只读审计行"落地）：
  · 对象=mingda CH 的 otel 库（与本 sweep 的主 CH 5221 旧锚不同机不同实例）；
  · 产出=逐表行数/字节水位 + 真库 TTL 回读与钉死值（30d/30d/90d）比对，漂移即记账；
  · 红牌（2026-11-03 补施工，RT 新项「表在位但 TTL 值漂移」形态）：
    TTL 值漂移 / 钉死表缩水 / 审计查询失败 → evidence 行 action=audit-ttl-drift |
    audit-shrink | audit-error + extra.otel_red_reasons，且退出码上抛（4/5）——
    旧码漂移只打一行「DRIFT」文字、action 仍 observe、退出码与不漂移不可区分
    （主锚死态下恒占 rc=1），机器消费面按 action 分流/按 rc 判红都看不见漂移。
  · 语义=审计**只读**，零 DDL/DML、零删除；otel 库绝不进自动删除对象集
    （--objects-file 里出现 db=otel 的条目直接拒绝执行）——sweep 的"连续 7 天
    无人调用即删"判定式会误删天然多冷访问的观测数据；
  · 位置=先于主 CH 取证跑，故主锚 5221 死锚状态下审计仍独立成立。
      删除前归档到 工具状态备份/mes-ttl-archive-<日期>/（DDL + Native 全量 + meta，
      表可整表恢复；行集存 TSV + 精确 DELETE 语句 + meta）。

用法：
  mes-ttl-sweep.py [--dry-run|--enforce] [--ch-url URL] [--objects-file PATH]
                   [--state-file PATH] [--arming-file PATH] [--archive-root DIR]
                   [--evidence-file PATH] [--log-file PATH] [--selftest]
退出码（机器可消费；2026-11-03 补齐「漂移 vs 不漂移」可区分性）：
  0 正常（含干跑观测）；
  1 主 CH 不可达/取证失败或运行错误（且 otel 只读审计无红牌）；
  2 用法错误；3 锁被占用；
  4 otel 只读审计红牌（TTL 值漂移 / 钉死表缩水 / 审计查询失败），其余正常；
  5 otel 只读审计红牌 + 主 CH 不可达/运行错误（双红）。
  ——旧码 otel 红牌与主锚不可达同占 rc=1，漂移与否在主锚死态下不可区分（已修）。
--selftest：内存桩自测（全桩，零网络、零真库、零生产副作用）——TTL 值漂移负例必红牌，
  且退出码在「主锚活/死」两种现势下均可与非漂移区分；见 selftest()。
"""
import argparse
import base64
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

WS = "/home/pan-ding/workspace/agent黑灯工厂"
BACKUP_DIR = os.path.join(WS, "工具状态备份")
OBS_DIR = os.path.join(WS, "状态观测")

DEFAULT_CH_URL = "http://127.0.0.1:5221"
UA = "mes-ttl-sweep/1.0"
IDLE_WINDOW_DAYS = 7          # "7 天无调用"窗口
MIN_OBS_GAP_HOURS = 24        # 双观测最小间隔
DEFAULT_MIN_HISTORY_DAYS = 7  # query_log 须覆盖的天数（首上线前 7 天必然不足）
HISTORY_FETCH_DAYS = 30       # 探测取证窗口（query_log TTL 14 天，30 天是宽松上界）
MAX_OBS_HISTORY = 40          # 状态文件每对象最多保留多少条观测
MAX_STALE_KEYS = 5000         # 行集删除键数上限（防 SQL 爆炸）
CH_RETRY = 3                  # MES 500（code 241）历史教训：有限重试
CH_BACKOFF = (2, 8)

DEFAULT_STATE_FILE = os.path.join(BACKUP_DIR, "mes-ttl-state.json")
DEFAULT_ARMING_FILE = os.path.join(BACKUP_DIR, "mes-ttl-arming.json")
DEFAULT_EVIDENCE_FILE = os.path.join(BACKUP_DIR, "mes-ttl-sweep-evidence.jsonl")
DEFAULT_LOG_FILE = os.path.join(OBS_DIR, "mes-ttl-sweep.log")
DEFAULT_ARCHIVE_ROOT = BACKUP_DIR  # 归档落 <root>/mes-ttl-archive-<YYYYMMDD>/

# 永久豁免（硬编码；--objects-file 里出现这些 id 直接报错退出）
EXEMPT = {
    "af_mes.mes_event": "现役活账本（MES 事件账本），永久豁免——任何模式/arming 下均零动作",
    "af_mes.mes_line_hour_mv": "现役物化视图（mes_event→mes_line_hour 聚合链），删除即断现役管道",
}

# otel 库保留策略钉死值（collector-storage.md §2.6 表；DDL 是唯一事实源——
#   collector 侧 create_schema=false，DDL 的 TTL 写死 30d/30d/90d）。
# 本常量是 sweep 侧的【对账口径】：每跑读回真库 TTL 与此表比对，漂移即记账。
OTEL_TTL_POLICY_DAYS = {
    "otel_traces": 30,
    "otel_logs": 30,
    "otel_traces_trace_id_ts": 30,
    "otel_metrics_gauge": 90,
    "otel_metrics_sum": 90,
    "otel_metrics_histogram": 90,
    "otel_metrics_summary": 90,
    "otel_metrics_exponential_histogram": 90,
}
OTEL_DB = "otel"          # mingda CH 上的 OTel 观测库（与 sweep 主 CH 不同机）
# otel 库=可再生观测视图（上游 af-trace 自有落盘兜底），保留机制=DDL 原生 TTL。
# sweep 的判定式是"连续 7 天无人调用即自动删除"——观测数据天然多冷访问，
# 会被误删。故 otel 库【绝不】纳入 sweep 的自动删除对象；sweep 侧只做只读
# 审计行（行数/字节水位 + TTL 对账），任何模式/arming 下均零删除动作。
OTEL_NEVER_DELETE = "otel 库=可再生观测视图（上游 af-trace 自有落盘兜底）→ 保留机制=DDL 原生 TTL；" \
                   "绝不纳入 sweep 自动删除（7 天冷访问判定式会误删观测数据）"

DEFAULT_OBJECTS = [
    {"id": "mes.events_mt", "kind": "table", "db": "mes", "table": "events_mt",
     "note": "第一代遗留表（S0 账本，现无写入方）"},
    {"id": "mes.bench_events", "kind": "table", "db": "mes", "table": "bench_events",
     "note": "第一代遗留表（S0 账本，现无写入方）"},
    {"id": "mes.events_repl", "kind": "table", "db": "mes", "table": "events_repl",
     "note": "第一代遗留表（S0 账本，现无写入方）"},
    {"id": "mes.agg_hourly", "kind": "table", "db": "mes", "table": "agg_hourly",
     "note": "第一代遗留表（S0 账本，现无写入方）"},
    {"id": "mes.hourly_agg", "kind": "table", "db": "mes", "table": "hourly_agg",
     "note": "第一代遗留表（S0 账本，现无写入方）"},
    {"id": "af_mes.mes_line_hour@stale-rows", "kind": "rowset", "db": "af_mes",
     "table": "mes_line_hour", "raw_db": "af_mes", "raw_table": "mes_event",
     "note": "mes_line_hour 第一代陈旧行（行集粒度；整表 7 天无查询才删其中陈旧行）"},
]

STALE_SQL = """
SELECT l.line_id AS line_id, toString(l.hour) AS hour,
       sum(l.event_count) AS event_count, sum(l.quantity_sum) AS quantity_sum,
       max(e.n) AS raw_n
FROM {agg} l
LEFT JOIN (
    SELECT line_id, toStartOfHour(occurred_at) AS hour, count() AS n
    FROM {raw} GROUP BY line_id, hour
) e ON l.line_id = e.line_id AND l.hour = e.hour
GROUP BY l.line_id, l.hour
ORDER BY l.line_id, l.hour
""".strip()


class CHError(Exception):
    pass


class CH:
    """ClickHouse HTTP 客户端：GET 只读 / POST 修改；自身 UA 标记；有限重试。"""

    def __init__(self, base, auth=None, retries=CH_RETRY, backoff=CH_BACKOFF, timeout=180):
        self.base = base.rstrip("/")
        self.auth = auth
        self.retries = retries
        self.backoff = backoff
        self.timeout = timeout

    def _req(self, sql, method, body, binary):
        url = self.base + "/?query=" + urllib.parse.quote(sql, safe="")
        headers = {"User-Agent": UA}
        if self.auth:
            headers["Authorization"] = self.auth
        data = None
        if method == "POST":
            data = body if body is not None else b""
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            payload = resp.read()
        return payload if binary else payload.decode("utf-8", "replace")

    def call(self, sql, method="GET", body=None, binary=False):
        last = None
        for attempt in range(self.retries):
            try:
                return self._req(sql, method, body, binary)
            except urllib.error.HTTPError as e:
                detail = ""
                try:
                    detail = e.read().decode("utf-8", "replace")[:300]
                except Exception:
                    pass
                last = "HTTP %s: %s" % (e.code, detail.strip())
                if e.code in (500, 502, 503, 504) and attempt < self.retries - 1:
                    time.sleep(self.backoff[min(attempt, len(self.backoff) - 1)])
                    continue
                raise CHError(last)
            except (urllib.error.URLError, OSError, TimeoutError) as e:
                last = "%s: %s" % (type(e).__name__, e)
                if attempt < self.retries - 1:
                    time.sleep(self.backoff[min(attempt, len(self.backoff) - 1)])
                    continue
                raise CHError(last)
        raise CHError("unreachable: %s" % last)

    def json_rows(self, sql):
        out = self.call(sql + " FORMAT JSONEachRow")
        rows = []
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows

    def scalar(self, sql):
        out = self.call(sql + " FORMAT TSVWithNames")
        lines = [l for l in out.splitlines() if l.strip()]
        return lines[1].strip() if len(lines) >= 2 else None


# ---------------------------------------------------------------- 探测与判定

def compile_matchers(db, table):
    q_db, q_tb = re.escape(db), re.escape(table)
    return (
        re.compile(r"(?<![A-Za-z0-9_$])%s\.%s(?![A-Za-z0-9_$])" % (q_db, q_tb)),
        re.compile(r"(?<![A-Za-z0-9_$])%s(?![A-Za-z0-9_$])" % q_tb),
        re.compile(r"(?is)\b(?:show\s+tables\s+from|use)\s+%s\b" % q_db),
    )


# ClickHouse 对 HTTP INSERT 会在服务端把查询重写为
#   "INSERT INTO db.tbl (col, ...) FORMAT <fmt>"
# 并以空 http_user_agent 单独记入 query_log（与原查询两条并存、不共享 query_id）。
# 注意：原查询的 tables 数组不含 MV 目标，重写条目才含（是原查询的超集）——而生产上
# MV 目标表的"被写入"信号只存在于重写条目，故不能一刀切排除重写条目。
# 归属规则（安全方向）：仅当同一秒内存在带工具 UA 的 INSERT 原查询、且其 tables 数组
# 是重写条目 tables 的子集时，该重写条目才归工具身份一并排除。工具从不向对象表发
# INSERT（只发往 <table>__ttl_verify_<tag> 自检临时表），故不会误伤第三方写入信号。
INSERT_REWRITE_RE = re.compile(r"(?is)^\s*INSERT\s+INTO\s+`?[\w$]+`?\s*\.\s*`?[\w$]+`?\s*\([^)]*\)\s*FORMAT\s+\w+")


def own_rewrite_keys(rows):
    """工具身份 INSERT 原查询的 (event_time, tables 集合) 清单（用于重写条目归属）。"""
    keys = []
    for r in rows:
        if not (r.get("http_user_agent") or "").startswith(UA):
            continue
        q = (r.get("query") or "").lstrip()
        if q[:6].upper() == "INSERT":
            keys.append((r.get("event_time"), frozenset(r.get("tables") or [])))
    return keys


def is_own_rewrite(r, own_keys):
    if (r.get("http_user_agent") or ""):
        return False
    if not INSERT_REWRITE_RE.search(r.get("query") or ""):
        return False
    rset = frozenset(r.get("tables") or [])
    return any(ts == r.get("event_time") and tset and tset <= rset
               for ts, tset in own_keys)


def match_access(rows, db, table, own_keys=None):
    """返回 (保留期内最后访问 ts|None, 命中条数)。

    命中判定（工具身份查询整体排除，不自我续命）：
      ① query_log.tables 数组含 "<db>.<table>"；
      ② query 文本含限定名 "<db>.<table>"；
      ③ current_database=<db> 且 query 文本含裸表名 "<table>"；
      ④ query 文本含 "SHOW TABLES FROM <db>" / "USE <db>"（数据库级内省，
         保守计为对该库全部对象的访问）。
    工具身份 = UA 以 mes-ttl-sweep 开头的查询，外加其 HTTP INSERT 服务端重写条目
    （空 UA；同秒有工具身份 INSERT 原查询且其 tables 是重写条目 tables 的子集，
    见 own_rewrite_keys——不能按集合相等匹配：MV 使重写条目成为原查询的超集，
    且第三方写入的 MV 目标信号只存在于重写条目，误排除会漏判真实访问）。
    """
    if own_keys is None:
        own_keys = own_rewrite_keys(rows)
    pat_q, pat_bare, pat_db = compile_matchers(db, table)
    last_any, hits = None, 0
    for r in rows:
        ua = r.get("http_user_agent") or ""
        if ua.startswith(UA) or is_own_rewrite(r, own_keys):
            continue
        tables = r.get("tables") or []
        q = r.get("query") or ""
        cdb = r.get("current_database") or ""
        if ("%s.%s" % (db, table)) in tables or pat_q.search(q) \
                or (cdb == db and pat_bare.search(q)) or pat_db.search(q):
            hits += 1
            ts = r.get("event_time")
            if ts and (last_any is None or ts > last_any):
                last_any = ts
    return last_any, hits


def parse_ts(s):
    if not s:
        return None
    try:
        return dt.datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def coverage(rows, server_now, min_days):
    """query_log 覆盖检查：最近 min_days 天（含今天，服务器本地日）每天都有记录。"""
    if min_days <= 0:
        return True, []
    days = set()
    for r in rows:
        ts = (r.get("event_time") or "")[:10]
        if ts:
            days.add(ts)
    today = server_now.date()
    missing = [(today - dt.timedelta(days=i)).isoformat()
               for i in range(min_days)
               if (today - dt.timedelta(days=i)).isoformat() not in days]
    return (not missing), missing


# ---------------------------------------------------------------- 行集陈旧判定

def compute_stale(ch, obj):
    """陈旧行判定式（可复算，写进设计文档）：

      对 agg 表（mes_line_hour）逐 (line_id, hour) 键聚合，与 raw 表（mes_event）
      同时段聚合做 anti-join：raw 侧该键不存在（raw_n 为空）→ 陈旧，可删；
      raw 侧存在但 event_count 与 raw 计数不符 → 仅告警（数据质量信号，不删，保守）；
      raw 侧存在且相符 → 健康行，两列都不进。
    """
    agg = "%s.%s" % (obj["db"], obj["table"])
    raw = "%s.%s" % (obj["raw_db"], obj["raw_table"])
    rows = ch.json_rows(STALE_SQL.format(agg=agg, raw=raw))
    stale, mismatch = [], []
    for r in rows:
        raw_n = r.get("raw_n")
        agg_n = int(r.get("event_count") or 0)
        if raw_n is None or int(raw_n) == 0:
            stale.append({"line_id": r["line_id"], "hour": r["hour"],
                          "event_count": agg_n,
                          "quantity_sum": int(r.get("quantity_sum") or 0)})
        elif int(raw_n) != agg_n:
            mismatch.append({"line_id": r["line_id"], "hour": r["hour"],
                             "agg_event_count": agg_n, "raw_event_count": int(raw_n)})
    return stale, mismatch


def sql_str(s):
    return "'" + str(s).replace("'", "''") + "'"


def tuple_in_clause(keys):
    parts = ["(%s, toDateTime(%s, 'UTC'))" % (sql_str(l), sql_str(h)) for l, h in keys]
    return "(line_id, hour) IN (" + ", ".join(parts) + ")"


# ---------------------------------------------------------------- 归档

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def table_exists(ch, db, table):
    rows = ch.json_rows(
        "SELECT 1 AS ok FROM system.tables WHERE database = %s AND name = %s LIMIT 1"
        % (sql_str(db), sql_str(table)))
    return bool(rows)


VIEW_ENGINES = ("MaterializedView", "View")


def table_engine(ch, db, table):
    rows = ch.json_rows(
        "SELECT engine FROM system.tables WHERE database = %s AND name = %s LIMIT 1"
        % (sql_str(db), sql_str(table)))
    return rows[0]["engine"] if rows else None


def dependent_views(ch, db, table):
    """返回把 <db>.<table> 当源（FROM）或当目标（TO）的 MV/视图名列表。

    CH 允许 DROP MV 的源表/目标表而留下悬空 MV（实测），故删表前必须查依赖。
    system.tables 的 dependencies_* 列对 MV 不填充（实测为空），用
    create_table_query 的限定名匹配（词边界）。
    """
    rows = ch.json_rows(
        "SELECT name, create_table_query FROM system.tables WHERE database = %s "
        "AND engine IN ('MaterializedView', 'View')" % sql_str(db))
    pat = re.compile(r"(?<![A-Za-z0-9_$])%s\.%s(?![A-Za-z0-9_$])"
                     % (re.escape(db), re.escape(table)))
    return [r["name"] for r in rows if pat.search(r.get("create_table_query") or "")]


def row_count(ch, db, table, where=""):
    sql = "SELECT count() AS n FROM %s.%s%s" % (db, table, (" " + where) if where else "")
    return int(ch.scalar(sql))


def object_row_count(ch, obj):
    """行数取证：视图（MV/View）无自有存储（SELECT 读到的是目标表数据），记 None。"""
    engine = table_engine(ch, obj["db"], obj["table"])
    if engine in VIEW_ENGINES:
        return None, engine
    return row_count(ch, obj["db"], obj["table"]), engine


def verify_name(table, tag):
    """自检临时表名：只保留 SQL 标识符安全字符（tag 含 -/. 等会引发语法错误）。"""
    return "%s__ttl_verify_%s" % (table, re.sub(r"[^0-9A-Za-z_]", "_", tag))


def fetch_ddl(ch, db, table):
    """SHOW CREATE TABLE 经 JSONEachRow 取（TSV 会把换行转义成字面 \\n，不可用）。
    普通表返回 CREATE TABLE ...，MV/视图返回 CREATE MATERIALIZED VIEW ...。"""
    rows = ch.json_rows("SHOW CREATE TABLE %s.%s" % (db, table))
    if not rows or "statement" not in rows[0]:
        raise CHError("DDL 获取失败: %s.%s" % (db, table))
    ddl = rows[0]["statement"]
    if not ddl.lstrip().upper().startswith("CREATE"):
        raise CHError("DDL 异常: %r" % ddl[:120])
    return ddl


def renamed_ddl(ddl, db, table, new_table):
    """把 DDL 的建表目标改名到 new_table。

    防护重点：若 DDL 里找不到预期的建表目标（带反引号/IF NOT EXISTS 等变体），
    替换会静默失败——那样按原 DDL 建出的就是真实表本身，随后的自检 DROP 会毁数据。
    因此替换后必须确认确已发生（out != ddl 且新名在场），否则抛错 fail-closed。
    """
    old = "CREATE TABLE %s.%s" % (db, table)
    new = "CREATE TABLE %s.%s" % (db, new_table)
    out = ddl.replace(old, new, 1)
    if out == ddl or new not in out:
        raise CHError("DDL 改名失败（建表目标未按预期替换），拒绝自检/删除")
    return out


def _drop_partial(base, suffixes):
    for s in suffixes:
        try:
            os.remove(base + s)
        except OSError:
            pass


def archive_table(ch, obj, adir, tag):
    """归档：普通表=DDL + Native 全量 + meta（含回灌自检）；视图=DDL only。

    自检失败 → 抛异常 → 调用方 fail-closed 不删；半成品归档文件一并清除。
    """
    db, table = obj["db"], obj["table"]
    base = os.path.join(adir, table)
    try:
        engine = table_engine(ch, db, table)
        ddl = fetch_ddl(ch, db, table)
        with open(base + ".sql", "w", encoding="utf-8") as f:
            f.write(ddl + "\n")
        if engine in VIEW_ENGINES:
            # 视图无自有存储（数据在其目标表，目标表是独立对象），只归档 DDL；
            # 恢复=重放 DDL（须先恢复其目标表），无数据回灌自检可做。
            meta = {
                "object": obj["id"], "kind": "view", "engine": engine, "db": db, "table": table,
                "rows": None,
                "ddl_file": os.path.basename(base + ".sql"),
                "archived_at": dt.datetime.now().isoformat(timespec="seconds"),
                "restore": "POST ?query=<.sql 内容>（须先恢复其目标表）",
            }
            with open(base + ".meta.json", "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=1)
            return meta
        n_before = row_count(ch, db, table)
        native = ch.call("SELECT * FROM %s.%s FORMAT Native" % (db, table), binary=True)
        n_after = row_count(ch, db, table)
        if n_after != n_before:
            raise CHError("归档期间行数漂移 %s→%s（疑有并发写入），放弃本次" % (n_before, n_after))
        with open(base + ".native", "wb") as f:
            f.write(native)
        meta = {
            "object": obj["id"], "kind": "table", "engine": engine, "db": db, "table": table,
            "rows": n_before, "native_bytes": len(native),
            "native_sha256": sha256_file(base + ".native"),
            "ddl_file": os.path.basename(base + ".sql"),
            "native_file": os.path.basename(base + ".native"),
            "archived_at": dt.datetime.now().isoformat(timespec="seconds"),
            "restore": "POST ?query=<.sql 内容> 后 POST ?query=INSERT INTO %s.%s FORMAT Native（body=<.native>）"
                       % (db, table),
        }
        # 可恢复自检：临时表按 DDL 重建 → Native 回灌 → 行数比对 → 删临时表
        vname = verify_name(table, tag)
        try:
            vddl = renamed_ddl(ddl, db, table, vname)
            ch.call(vddl, method="POST")
            with open(base + ".native", "rb") as f:
                body = f.read()
            ch.call("INSERT INTO %s.%s FORMAT Native" % (db, vname), method="POST", body=body)
            n_restored = row_count(ch, db, vname)
            if n_restored != n_before:
                raise CHError("归档自检失败：回灌 %s 行 vs 原 %s 行" % (n_restored, n_before))
            meta["selfcheck"] = {"restored_rows": n_restored, "ok": True}
        finally:
            try:
                if table_exists(ch, db, vname):
                    ch.call("DROP TABLE %s.%s" % (db, vname), method="POST")
            except CHError:
                pass
        with open(base + ".meta.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=1)
        return meta
    except Exception:
        _drop_partial(base, (".sql", ".native", ".meta.json"))
        raise


def archive_rowset(ch, obj, adir, tag, stale_rows):
    """行集归档：待删行全量 TSV + 精确 DELETE 语句 + 键清单 + meta；临时表回灌自检。"""
    db, table = obj["db"], obj["table"]
    keys = [(r["line_id"], r["hour"]) for r in stale_rows]
    if not keys:
        return None
    if len(keys) > MAX_STALE_KEYS:
        raise CHError("陈旧键数 %s 超过上限 %s，拒绝执行（防 SQL 爆炸）" % (len(keys), MAX_STALE_KEYS))
    in_clause = tuple_in_clause(keys)
    base = os.path.join(adir, table + ".stale-rows")
    try:
        tsv = ch.call("SELECT * FROM %s.%s WHERE %s ORDER BY line_id, hour FORMAT TSV"
                      % (db, table, in_clause))
        delete_sql = "DELETE FROM %s.%s WHERE %s" % (db, table, in_clause)
        with open(base + ".tsv", "w", encoding="utf-8") as f:
            f.write(tsv if tsv.endswith("\n") or not tsv else tsv + "\n")
        with open(base + ".delete.sql", "w", encoding="utf-8") as f:
            f.write(delete_sql + ";\n")
        with open(base + ".keys.json", "w", encoding="utf-8") as f:
            json.dump([{"line_id": l, "hour": h} for l, h in keys], f, ensure_ascii=False, indent=1)
        n_rows = len([l for l in tsv.splitlines() if l.strip()])
        # 可恢复自检：临时表按正式 DDL 重建 → TSV 回灌 → 行数比对 → 删临时表
        vname = verify_name(table, tag)
        ddl = fetch_ddl(ch, db, table)
        try:
            vddl = renamed_ddl(ddl, db, table, vname)
            ch.call(vddl, method="POST")
            ch.call("INSERT INTO %s.%s FORMAT TSV" % (db, vname), method="POST",
                    body=tsv.encode("utf-8"))
            n_restored = row_count(ch, db, vname)
            if n_restored != n_rows:
                raise CHError("行集归档自检失败：回灌 %s 行 vs 归档 %s 行" % (n_restored, n_rows))
        finally:
            try:
                if table_exists(ch, db, vname):
                    ch.call("DROP TABLE %s.%s" % (db, vname), method="POST")
            except CHError:
                pass
        meta = {
            "object": obj["id"], "kind": "rowset", "db": db, "table": table,
            "stale_keys": len(keys), "archived_rows": n_rows,
            "tsv_sha256": sha256_file(base + ".tsv"),
            "files": {"tsv": os.path.basename(base + ".tsv"),
                      "delete_sql": os.path.basename(base + ".delete.sql"),
                      "keys": os.path.basename(base + ".keys.json")},
            "delete_sql": delete_sql,
            "selfcheck": {"restored_rows": n_rows, "ok": True},
            "archived_at": dt.datetime.now().isoformat(timespec="seconds"),
            "restore": "POST ?query=INSERT INTO %s.%s FORMAT TSV（body=<.tsv>，列序 line_id,hour,event_count,quantity_sum）"
                       % (db, table),
        }
        with open(base + ".meta.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=1)
        return meta
    except Exception:
        _drop_partial(base, (".tsv", ".delete.sql", ".keys.json", ".meta.json"))
        raise


# ---------------------------------------------------------------- 删除

def delete_table(ch, obj):
    db, table = obj["db"], obj["table"]
    ch.call("DROP TABLE %s.%s" % (db, table), method="POST")
    if table_exists(ch, db, table):
        raise CHError("DROP 后表仍在")


def delete_rowset(ch, obj, keys):
    db, table = obj["db"], obj["table"]
    in_clause = tuple_in_clause(keys)
    ch.call("DELETE FROM %s.%s WHERE %s" % (db, table, in_clause), method="POST")
    # 验证：键过滤计数归零 + 陈旧复算为空
    if row_count(ch, db, table, "WHERE " + in_clause) != 0:
        raise CHError("DELETE 后键过滤计数非零（mutation 未生效？）")
    stale, _ = compute_stale(ch, obj)
    if stale:
        raise CHError("DELETE 后仍有 %d 个陈旧键" % len(stale))


# ---------------------------------------------------------------- 主流程

def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def load_objects(path):
    if not path:
        return [dict(o) for o in DEFAULT_OBJECTS], "builtin-default"
    data = load_json(path, None)
    if not data or "objects" not in data:
        raise SystemExit("objects-file 解析失败: %s" % path)
    objs = []
    for o in data["objects"]:
        for k in ("id", "kind", "db", "table"):
            if k not in o:
                raise SystemExit("objects-file 条目缺字段 %r: %r" % (k, o))
        if o["id"] in EXEMPT:
            raise SystemExit("objects-file 含永久豁免对象 %s，拒绝执行" % o["id"])
        if o["db"] == OTEL_DB:
            raise SystemExit(
                "objects-file 含 otel 库对象 %s，拒绝执行——%s" % (o["id"], OTEL_NEVER_DELETE))
        if o["kind"] == "rowset" and ("raw_db" not in o or "raw_table" not in o):
            raise SystemExit("rowset 对象缺 raw_db/raw_table: %r" % o)
        objs.append(o)
    return objs, path


def parse_ch_url(url):
    auth = None
    if "@" in url:
        scheme, rest = url.split("://", 1)
        userinfo, hostpart = rest.split("@", 1)
        url = "%s://%s" % (scheme, hostpart)
        auth = "Basic " + base64.b64encode(userinfo.encode()).decode()
    return url, auth


def audit_entries():
    """永久豁免对象的审计条目（每跑都记录一条 evidence，证明零动作）。"""
    out = []
    for eid, why in EXEMPT.items():
        db, table = eid.rsplit(".", 1)
        out.append({"id": eid, "kind": "exempt-audit", "db": db, "table": table, "note": why})
    return out


def _load_otel_ch_client():
    """importlib 单点加载 tools/otel/ch_client.py（凭据链单一真源，不复制不打印）。"""
    import importlib.util
    path = os.path.join(WS, "tools", "otel", "ch_client.py")
    spec = importlib.util.spec_from_file_location("af_otel_ch_client", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def otel_audit_rows():
    """otel 库只读审计行：逐表行数/字节水位 + 真库 TTL 回读与钉死值对账。

    纪律：只读（system.parts / system.tables 聚合查询），零 DDL/DML、零删除；
    凭据经 tools/otel/ch_client.py 的 F-11 链解析（env > openBao > 0600 文件 >
    缺省端点），口令只进 HTTP Basic 头，不进本函数返回值、不进日志。
    返回 (rows, error_str, missing_pinned)：error_str 非空表示审计未完成（fail-closed，
    不删任何东西）；missing_pinned=钉死清单（OTEL_TTL_POLICY_DAYS）中不在审计行内的
    表——审计对象是在场表并集，钉死表被 DROP 或 engine 改非 MergeTree 会同时从
    parts/tables 消失，审计只会缩水不会多出，故缺席即红（RT-E16 拦截机制②）。
    error 路径下钉死表全部视为未核（missing_pinned=全清单，宁红勿绿）。
    """
    try:
        cc = _load_otel_ch_client()
    except Exception as e:  # 加载失败即审计失败（不静默跳过）
        return [], "ch_client 加载失败: %s" % e, sorted(OTEL_TTL_POLICY_DAYS)
    try:
        rows = cc.query(
            "SELECT table, sum(rows) AS rows, sum(bytes_on_disk) AS bytes, count() AS parts "
            "FROM system.parts WHERE database='%s' AND active GROUP BY table ORDER BY table"
            % OTEL_DB)
        ttl_rows = cc.query(
            "SELECT name, engine_full FROM system.tables WHERE database='%s' AND engine='MergeTree'"
            % OTEL_DB)
    except Exception as e:
        return [], "otel 库只读审计失败（端点不在转录内）: %s" % str(e)[:160], \
            sorted(OTEL_TTL_POLICY_DAYS)
    # TTL 对账：从 engine_full 文本抽 toIntervalDay(N)，与钉死值比对
    ttl_actual = {}
    for r in ttl_rows:
        m = re.search(r"toIntervalDay\((\d+)\)", r.get("engine_full") or "")
        if m:
            ttl_actual[r["name"]] = int(m.group(1))
    # 审计对象=system.tables 全部 MergeTree 表 ∪ system.parts 出现的表。
    # 不能只按 system.parts 取：空表没有 active part，不出现——其 TTL 漂移将
    # 永不记账而水位行仍报「全一致」（2026-10-31 修复的空表盲区）。
    parts_by_table = {r["table"]: r for r in rows}
    out = []
    total_rows = 0
    total_bytes = 0
    for t in sorted(set(parts_by_table) | {r["name"] for r in ttl_rows}):
        pr = parts_by_table.get(t) or {}
        exp = OTEL_TTL_POLICY_DAYS.get(t)
        act = ttl_actual.get(t)
        n_rows = int(pr.get("rows") or 0)
        n_bytes = int(pr.get("bytes") or 0)
        out.append({
            "table": t,
            "rows": n_rows,
            "bytes_on_disk": n_bytes,
            "active_parts": int(pr.get("parts") or 0),
            "ttl_days_expected": exp,
            "ttl_days_actual": act,
            "ttl_match": (exp is not None and act == exp),
        })
        total_rows += n_rows
        total_bytes += n_bytes
    # 数量下界对账（RT-E16 拦截机制②，2026-11-01 补施工）：审计对象=在场表并集
    # （system.parts ∪ system.tables），钉死表被 DROP / engine 改非 MergeTree 后
    # 会从两侧同时消失——审计静默缩水而逐表对账仍全绿。钉死清单任何一表缺席即红，
    # 由 main() fail-closed 上抛退出码。
    audited = {r["table"] for r in out}
    missing = sorted(t for t in OTEL_TTL_POLICY_DAYS if t not in audited)
    return out, "", missing


# ---------------------------------------------------------------- 自测（全桩）

def _selftest_fixture(drift=None, drop=()):
    """otel 只读审计桩夹具：system.parts 行 + system.tables engine_full 行。

    drift={表: 天数 or None}：注入 TTL 漂移（None = TTL 子句被摘掉）；
    drop=(表,...)：钉死表不在场（模拟被删 / engine 改非 MergeTree → 审计缩水）。
    """
    drift = drift or {}
    parts, tables = [], []
    for t, exp in OTEL_TTL_POLICY_DAYS.items():
        if t in drop:
            continue
        act = drift[t] if t in drift else exp
        parts.append({"table": t, "rows": 11, "bytes": 222, "parts": 1})
        if act is None:
            ef = "MergeTree ORDER BY x SETTINGS index_granularity = 8192"
        else:
            ef = ("MergeTree ORDER BY x TTL toDateTime(Timestamp) + toIntervalDay(%d) "
                  "SETTINGS index_granularity = 8192" % act)
        tables.append({"name": t, "engine_full": ef})
    return parts, tables


class _SelftestOtelStub:
    """otel 只读审计的 CH 客户端桩（零网络零真库）：按 SQL 关键词回放夹具。"""

    def __init__(self, parts=None, tables=None, fail=False):
        self.parts = parts or []
        self.tables = tables or []
        self.fail = fail

    def query(self, sql):
        if self.fail:
            raise RuntimeError("selftest: 桩注入审计查询失败")
        if "system.parts" in sql:
            return [dict(r) for r in self.parts]
        if "system.tables" in sql:
            return [dict(r) for r in self.tables]
        raise AssertionError("selftest: 桩收到非预期查询 %s" % sql)


class _SelftestMainCH:
    """主 CH 桩：ALIVE=True 返服务器时间 + 空 query_log；False 抛 CHError（模拟死锚）。"""

    ALIVE = True

    def __init__(self, base, auth=None):
        pass

    def scalar(self, sql):
        if not _SelftestMainCH.ALIVE:
            raise CHError("selftest: 桩注入主锚不可达")
        return "2026-11-03 00:00:00"

    def json_rows(self, sql):
        if not _SelftestMainCH.ALIVE:
            raise CHError("selftest: 桩注入主锚不可达")
        return []


def _selftest_case(case):
    """跑一桩 main()（otel 审计桩 + 主 CH 桩），返回 (rc, 审计证据行, 问题列表, 输出)。"""
    import contextlib
    import io
    import shutil
    import tempfile
    tmp = tempfile.mkdtemp(prefix="mes-ttl-selftest-")
    objs = os.path.join(tmp, "objects.json")
    with open(objs, "w", encoding="utf-8") as f:
        json.dump({"objects": []}, f, ensure_ascii=False)
    argv = ["mes-ttl-sweep.py", "--dry-run", "--ch-url", "http://127.0.0.1:1",
            "--objects-file", objs,
            "--state-file", os.path.join(tmp, "state.json"),
            "--evidence-file", os.path.join(tmp, "evidence.jsonl"),
            "--log-file", os.path.join(tmp, "sweep.log"),
            "--archive-root", os.path.join(tmp, "archive")]
    saved_argv = sys.argv
    saved_ch = globals().get("CH")
    saved_loader = globals().get("_load_otel_ch_client")
    buf = io.StringIO()
    try:
        sys.argv = argv
        globals()["CH"] = _SelftestMainCH
        _SelftestMainCH.ALIVE = bool(case.get("main_alive"))
        globals()["_load_otel_ch_client"] = lambda: _SelftestOtelStub(
            case.get("parts"), case.get("tables"), bool(case.get("otel_fail")))
        with contextlib.redirect_stdout(buf):
            rc = main()
    finally:
        sys.argv = saved_argv
        globals()["CH"] = saved_ch
        globals()["_load_otel_ch_client"] = saved_loader
    rec = None
    try:
        with open(os.path.join(tmp, "evidence.jsonl"), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                if r.get("kind") == "otel-readonly-audit":
                    rec = r
    except (OSError, ValueError):
        rec = None
    problems = []
    if rc != case["expect_rc"]:
        problems.append("退出码期望 %d 实得 %d" % (case["expect_rc"], rc))
    if rec is None:
        problems.append("无 otel 审计证据行")
    else:
        if rec.get("action") != case["expect_action"]:
            problems.append("action 期望 %s 实得 %s" % (case["expect_action"], rec.get("action")))
        extra = rec.get("extra") or {}
        got = sorted(extra.get("ttl_drift_tables") or [])
        want = sorted(case.get("expect_drift") or [])
        if got != want:
            problems.append("ttl_drift_tables 期望 %s 实得 %s" % (want, got))
    shutil.rmtree(tmp, ignore_errors=True)  # 桩产物只在 /tmp 临时目录，用后即清
    return rc, rec, problems, buf.getvalue()


def selftest():
    """自测：otel 只读审计红牌 + 退出码口径（全桩、零网络、零真库、零生产副作用）。

    每桩真跑一遍 main()，断言退出码 + 审计证据行 action + 漂移表清单：
      ① 基线（TTL 全一致）× 主锚活/死 —— 不得红；
      ② 漂移（TTL 值被改成别的值 / TTL 被摘掉）× 主锚活/死 —— 必红牌；
      ③ 钉死表消失（审计缩水）—— 红牌（RT-E16 拦截机制② 回归护栏）；
      ④ 审计查询失败 —— 红牌（fail-closed 回归护栏）；
      ⑤ 不变量：漂移与非漂移在主锚活/死两种现势下退出码均可区分。
    """
    base_parts, base_tables = _selftest_fixture()
    up_parts, up_tables = _selftest_fixture(drift={"otel_traces": 365})
    dn_parts, dn_tables = _selftest_fixture(drift={"otel_metrics_sum": 7})
    gone_parts, gone_tables = _selftest_fixture(drop=("otel_logs",))
    no_ttl_parts, no_ttl_tables = _selftest_fixture(drift={"otel_traces": None})
    cases = [
        {"key": "base_dead", "name": "基线·主锚死（现势 5221 死锚）",
         "parts": base_parts, "tables": base_tables, "main_alive": False,
         "expect_rc": 1, "expect_action": "observe", "expect_drift": []},
        {"key": "base_alive", "name": "基线·主锚活",
         "parts": base_parts, "tables": base_tables, "main_alive": True,
         "expect_rc": 0, "expect_action": "observe", "expect_drift": []},
        {"key": "drift_dead", "name": "漂移 30d→365d·主锚死",
         "parts": up_parts, "tables": up_tables, "main_alive": False,
         "expect_rc": 5, "expect_action": "audit-ttl-drift", "expect_drift": ["otel_traces"]},
        {"key": "drift_alive", "name": "漂移 30d→365d·主锚活",
         "parts": up_parts, "tables": up_tables, "main_alive": True,
         "expect_rc": 4, "expect_action": "audit-ttl-drift", "expect_drift": ["otel_traces"]},
        {"key": "drift_dn_alive", "name": "漂移 90d→7d（缩短方向）·主锚活",
         "parts": dn_parts, "tables": dn_tables, "main_alive": True,
         "expect_rc": 4, "expect_action": "audit-ttl-drift", "expect_drift": ["otel_metrics_sum"]},
        {"key": "drift_nottl_alive", "name": "TTL 子句被摘掉·主锚活",
         "parts": no_ttl_parts, "tables": no_ttl_tables, "main_alive": True,
         "expect_rc": 4, "expect_action": "audit-ttl-drift", "expect_drift": ["otel_traces"]},
        {"key": "shrink_alive", "name": "钉死表消失（审计缩水）·主锚活",
         "parts": gone_parts, "tables": gone_tables, "main_alive": True,
         "expect_rc": 4, "expect_action": "audit-shrink", "expect_drift": []},
        {"key": "audit_err_alive", "name": "审计查询失败·主锚活",
         "parts": base_parts, "tables": base_tables, "otel_fail": True, "main_alive": True,
         "expect_rc": 4, "expect_action": "audit-error", "expect_drift": []},
        {"key": "audit_err_dead", "name": "审计查询失败·主锚死",
         "parts": base_parts, "tables": base_tables, "otel_fail": True, "main_alive": False,
         "expect_rc": 5, "expect_action": "audit-error", "expect_drift": []},
    ]
    fails = 0
    rcs = {}
    for c in cases:
        rc, rec, problems, out = _selftest_case(c)
        rcs[c["key"]] = rc
        if problems:
            fails += 1
            print("[FAIL] %s —— %s" % (c["name"], "；".join(problems)))
            for line in out.splitlines():
                print("      | " + line)
        else:
            print("[PASS] %s —— rc=%d action=%s drift=%s" % (
                c["name"], rc, (rec or {}).get("action"),
                (rec or {}).get("extra", {}).get("ttl_drift_tables")))
    # ⑤ 可区分性不变量：漂移 rc ≠ 非漂移 rc（主锚活/死两种现势）
    for dk, bk, label in (("drift_dead", "base_dead", "主锚死"), ("drift_alive", "base_alive", "主锚活")):
        if rcs.get(dk) == rcs.get(bk):
            fails += 1
            print("[FAIL] 可区分性不变量（%s）：漂移 rc=%s 与非漂移 rc=%s 相同"
                  % (label, rcs.get(dk), rcs.get(bk)))
        else:
            print("[PASS] 可区分性不变量（%s）：漂移 rc=%s ≠ 非漂移 rc=%s"
                  % (label, rcs.get(dk), rcs.get(bk)))
    print("mes-ttl-sweep --selftest: %d 桩，%d 失败" % (len(cases), fails))
    return 0 if fails == 0 else 1


def main():
    ap = argparse.ArgumentParser(description="MES 遗留数据 7 天无调用自删清扫器（默认干跑）")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="干跑：只观测记录，绝不删（默认）")
    mode.add_argument("--enforce", action="store_true",
                      help="执行态：仍须 arming 文件存在且对象满足双观测判定才真删")
    ap.add_argument("--ch-url", default=os.environ.get("MES_TTL_CH_URL", DEFAULT_CH_URL))
    ap.add_argument("--objects-file", default=os.environ.get("MES_TTL_OBJECTS_FILE"))
    ap.add_argument("--state-file", default=DEFAULT_STATE_FILE)
    ap.add_argument("--arming-file", default=DEFAULT_ARMING_FILE)
    ap.add_argument("--archive-root", default=DEFAULT_ARCHIVE_ROOT)
    ap.add_argument("--evidence-file", default=DEFAULT_EVIDENCE_FILE)
    ap.add_argument("--log-file", default=DEFAULT_LOG_FILE)
    ap.add_argument("--selftest", action="store_true",
                    help="内存桩自测：TTL 值漂移负例必红牌且退出码可区分")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    enforce_req = bool(args.enforce)
    for d in (os.path.dirname(args.state_file), os.path.dirname(args.evidence_file),
              os.path.dirname(args.log_file), args.archive_root):
        if d:
            os.makedirs(d, exist_ok=True)

    # 单实例锁（防 timer 与手动跑重叠）
    lock_path = args.state_file + ".lock"
    lock_fp = open(lock_path, "w")
    try:
        fcntl.flock(lock_fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("mes-ttl-sweep: 另一实例正在运行（lock=%s），退出" % lock_path)
        return 3

    log_fp = open(args.log_file, "a", encoding="utf-8")
    ev_fp = open(args.evidence_file, "a", encoding="utf-8")

    def log(line):
        log_fp.write(line + "\n")
        log_fp.flush()
        print(line)

    def evidence(rec):
        ev_fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
        ev_fp.flush()

    objects, objs_src = load_objects(args.objects_file)
    base, auth = parse_ch_url(args.ch_url)
    ch = CH(base, auth=auth)

    # ---------- otel 库只读审计行（先于主 CH 取证跑） ----------
    # 理由：otel 库在 mingda CH（与本 sweep 的主 CH 5221 旧锚不同机不同实例）；
    # 主锚若死（当前实况），放在其后的审计会整段被跳过——审计必须独立成立。
    # 本段严格只读：system.parts/system.tables 聚合查询，零 DDL/DML、零删除。
    otel_rows, otel_err, otel_missing = otel_audit_rows()
    otel_audit_fail = False  # 审计失败/钉死表缩水 → rc=1 上抛（RT-E16②③，机器可消费）
    otel_rec = {
        "ts": dt.datetime.now().isoformat(sep=" "),
        "run_id": "otel-audit",
        "object": "%s.*" % OTEL_DB,
        "kind": "otel-readonly-audit",
        "mode": "readonly-audit",
        "action": "observe",
        "deletable": False,
        "reason": OTEL_NEVER_DELETE,
        "extra": {"tables": otel_rows, "error": otel_err or None,
                  "ttl_policy_days": OTEL_TTL_POLICY_DAYS},
    }
    promised_n = len(OTEL_TTL_POLICY_DAYS)  # 承诺表数（钉死清单规模，机制③第二数字）
    red_reasons = []
    if otel_err:
        otel_rec["action"] = "audit-error"
        red_reasons.append("audit-error")
        log("[otel-audit] 失败（fail-closed，未做任何删除）: %s" % otel_err)
        otel_audit_fail = True
    else:
        tot_rows = sum(r["rows"] for r in otel_rows)
        tot_bytes = sum(r["bytes_on_disk"] for r in otel_rows)
        mism = [r["table"] for r in otel_rows if not r["ttl_match"]]
        # TTL 值漂移口径（2026-11-03 补施工，RT 新项「表在位但 TTL 值漂移」形态）：
        #   表在位（审计对象集内）但真库 TTL 实值 ≠ 钉死值——含「TTL 子句被摘掉」
        #   （实值为 None）。旧码此处只把 mism 写进 evidence 的 extra 并打一行 DRIFT
        #   文字：不置 otel_audit_fail、action 仍 observe、退出码与不漂移不可区分
        #   （主锚死态下恒占 rc=1）——机器消费面按 action 分流/按 rc 判红都看不见漂移。
        #   未钉死的在场表（exp is None）只记账不置红：新增表 ≠ 保留策略违规。
        drift = sorted(r["table"] for r in otel_rows
                       if r["ttl_days_expected"] is not None
                       and r["ttl_days_actual"] != r["ttl_days_expected"])
        unpinned = sorted(r["table"] for r in otel_rows if r["ttl_days_expected"] is None)
        otel_rec["extra"]["total_rows"] = tot_rows
        otel_rec["extra"]["total_bytes_on_disk"] = tot_bytes
        otel_rec["extra"]["ttl_mismatch_tables"] = mism
        otel_rec["extra"]["ttl_drift_tables"] = drift
        otel_rec["extra"]["ttl_unpinned_tables"] = unpinned
        otel_rec["extra"]["ttl_drift_detail"] = [
            {"table": r["table"], "ttl_days_expected": r["ttl_days_expected"],
             "ttl_days_actual": r["ttl_days_actual"]}
            for r in otel_rows if r["table"] in drift]
        otel_rec["extra"]["promised_table_count"] = promised_n
        otel_rec["extra"]["audited_table_count"] = len(otel_rows)
        if otel_missing:
            # RT-E16 拦截机制②：钉死表被删/engine 改 → 审计缩水即红牌（fail-closed，
            # 零删除；缩水前旧码只 log「全一致」且退出 0——门洞已封）。
            otel_rec["action"] = "audit-shrink"
            otel_rec["extra"]["pinned_missing_tables"] = otel_missing
            red_reasons.append("pinned-missing")
            otel_audit_fail = True
            log("[otel-audit] 红牌（审计缩水，fail-closed 未做任何删除）：审计表数 %d/承诺表数 %d，"
                "钉死表缺失: %s" % (len(otel_rows), promised_n, ",".join(otel_missing)))
        if drift:
            # 红牌：表在位但 TTL 值漂移（fail-closed，零删除）——action 改为可机器分流的
            # audit-ttl-drift，红牌原因入 extra.otel_red_reasons，退出码上抛（见末尾合成）。
            if otel_rec["action"] == "observe":
                otel_rec["action"] = "audit-ttl-drift"
            red_reasons.append("ttl-drift")
            otel_audit_fail = True
            log("[otel-audit] 红牌（TTL 值漂移，fail-closed 未做任何删除）：漂移表 %s —— %s"
                % (",".join(drift), "；".join(
                    "%s 实值=%s 钉死=%sd" % (
                        d["table"],
                        "无(TTL 子句缺失)" if d["ttl_days_actual"] is None
                        else "%sd" % d["ttl_days_actual"],
                        d["ttl_days_expected"])
                    for d in otel_rec["extra"]["ttl_drift_detail"])))
        # RT-E16 拦截机制③：审计水位行恒带「审计表数/承诺表数」两数字，缩水一眼可辨。
        log("[otel-audit] %s 库只读水位：审计表数 %d/承诺表数 %d / %d 行 / %d 字节；TTL 对账 %s"
            % (OTEL_DB, len(otel_rows), promised_n, tot_rows, tot_bytes,
               "全一致" if not mism else "不一致: " + ",".join(mism)))
        for r in otel_rows:
            log("[otel-audit]   %-34s rows=%-8d bytes=%-10d parts=%d TTL=%s/%sd %s"
                % (r["table"], r["rows"], r["bytes_on_disk"], r["active_parts"],
                   r["ttl_days_actual"], r["ttl_days_expected"],
                   "OK" if r["ttl_match"] else "DRIFT"))
    otel_rec["extra"]["otel_red_reasons"] = red_reasons  # 机器消费面（红牌原因清单）
    evidence(otel_rec)

    try:
        server_now = parse_ts(ch.scalar("SELECT now() AS ts"))
        if server_now is None:
            raise CHError("无法读取服务器时间")
        qrows = ch.json_rows(
            "SELECT event_time, substring(query, 1, 200000) AS query, tables, "
            "current_database, http_user_agent, type FROM system.query_log "
            "WHERE event_time >= now() - INTERVAL %d DAY" % HISTORY_FETCH_DAYS)
    except CHError as e:
        log("mes-ttl-sweep: CH 不可达或取证失败（%s），本次不观测不删" % e)
        # 退出码合成：otel 审计红牌 + 主锚不可达 = 5（双红）；否则 1（旧语义不变）。
        # 旧码此处恒 return 1——主锚死态下漂移与否完全不可区分（RT 新项，已修）。
        return 5 if otel_audit_fail else 1

    arming = load_json(args.arming_file, None)
    armed = bool(arming and arming.get("armed"))
    effective = "enforce" if (enforce_req and armed) else "dry-run"
    why = ""
    if enforce_req and not armed:
        why = "（arming 文件缺失/未置位 → 降级干跑）"
    run_id = dt.datetime.now().strftime("%Y%m%dT%H%M%S") + "-%d" % os.getpid()
    log("===== mes-ttl-sweep run=%s mode_req=%s arming=%s effective=%s%s ch=%s objects=%s ====="
        % (run_id, "enforce" if enforce_req else "dry-run",
           "present" if armed else "absent", effective, why, args.ch_url, objs_src))

    state = load_json(args.state_file, {"version": 1, "objects": {}})
    state.setdefault("objects", {})
    today = dt.date.today()
    archive_dir = os.path.join(args.archive_root, "mes-ttl-archive-%s" % today.strftime("%Y%m%d"))
    cutoff = server_now - dt.timedelta(days=IDLE_WINDOW_DAYS)
    own_keys = own_rewrite_keys(qrows)
    rc = 0
    # otel 审计红牌的退出码不在此处合成：主 CH 不可达路径（早于本行 return）与
    # 阶段一/阶段二的 rc=1（运行错误）都要与红牌叠加，故统一在末尾合成——
    # otel 红牌单独=4；otel 红牌 + 主 CH/运行错误=5（双红）；漂移与否均可区分。

    # ---------- 阶段一：判定（全部对象先判定；动作阶段需要全局"本运行可删集合"） ----------
    pending = []          # [(obj, rec)] 待进入动作阶段的非豁免、且表在场的对象
    deletable_set = set()  # 本运行判定可删且表在场的对象 id
    for obj in objects + audit_entries():
        oid = obj["id"]
        rec = {"ts": server_now.isoformat(sep=" "), "run_id": run_id, "object": oid,
               "kind": obj["kind"], "mode": effective, "armed": armed,
               "rows": None, "last_accessed_at": None, "idle_7d": None,
               "coverage_ok": None, "reason": None, "streak": 0, "deletable": False,
               "action": None, "archive": None, "extra": {}}
        try:
            if oid in EXEMPT:
                last_any, hits = match_access(qrows, obj["db"], obj["table"], own_keys)
                rec["last_accessed_at"] = last_any
                rec["action"] = "exempt"
                rec["reason"] = EXEMPT[oid]
                rec["extra"]["access_hits"] = hits
                log("[exempt]  %s — %s（保留期内最后访问 %s，命中 %d 次）"
                    % (oid, EXEMPT[oid], last_any or "无", hits))
                evidence(rec)
                continue

            last_any, hits = match_access(qrows, obj["db"], obj["table"], own_keys)
            min_days = int(obj.get("min_history_days", DEFAULT_MIN_HISTORY_DAYS))
            cov_ok, missing = coverage(qrows, server_now, min_days)
            in_window = last_any is not None and parse_ts(last_any) >= cutoff
            idle = (not in_window) and cov_ok
            reason = None
            if in_window:
                reason = "accessed_at=%s（7 天窗口内被查询 %d 次）" % (last_any, hits)
            elif not cov_ok:
                reason = "history_coverage_incomplete(query_log 缺 %d/%d 天: %s)" % (
                    len(missing), min_days, ",".join(missing[:3]))
            else:
                reason = "no_access_%dd+coverage_ok" % IDLE_WINDOW_DAYS

            hist = state["objects"].get(oid, [])
            hist.append({"ts": server_now.isoformat(sep=" "), "idle": bool(idle),
                         "last_accessed_at": last_any, "coverage_ok": bool(cov_ok)})
            hist = hist[-MAX_OBS_HISTORY:]
            state["objects"][oid] = hist
            streak = 0
            for o in reversed(hist):
                if o["idle"]:
                    streak += 1
                else:
                    break
            gap_ok = False
            if len(hist) >= 2:
                gap_ok = (parse_ts(hist[-1]["ts"]) - parse_ts(hist[-2]["ts"])
                          ).total_seconds() >= MIN_OBS_GAP_HOURS * 3600
            deletable = bool(idle and streak >= 2 and gap_ok)

            exists = table_exists(ch, obj["db"], obj["table"])
            rows, engine = (object_row_count(ch, obj) if exists else (None, None))
            extra = {"access_hits": hits, "missing_days": missing, "table_exists": exists,
                     "engine": engine}
            if obj["kind"] == "table" and exists:
                # 依赖可见性：即使只观测也记录（运营者据此决定是否把依赖视图纳入清单）
                extra["dependent_views"] = dependent_views(ch, obj["db"], obj["table"])
            if engine in VIEW_ENGINES:
                extra["note"] = "视图对象（无自有存储，行数不适用；归档=DDL only）"
            if obj["kind"] == "rowset":
                stale, mismatch = compute_stale(ch, obj)
                extra["stale_keys"] = len(stale)
                extra["stale_preview"] = ["%s@%s" % (s["line_id"], s["hour"]) for s in stale[:8]]
                extra["count_mismatch_warnings"] = mismatch[:8]
                extra["count_mismatch_total"] = len(mismatch)
            rec.update({"rows": rows, "last_accessed_at": last_any, "idle_7d": bool(idle),
                        "coverage_ok": bool(cov_ok), "reason": reason, "streak": streak,
                        "deletable": deletable, "extra": extra})

            if not exists:
                rec["action"] = "absent"
                log("[absent]   %s — 表已不存在（此前已删或从未建），无动作" % oid)
                evidence(rec)
                continue
            if deletable:
                deletable_set.add(oid)
            pending.append((obj, rec))
        except CHError as e:
            rec["action"] = "error"
            rec["reason"] = str(e)
            log("[error]    %s — %s（未删除，fail-closed）" % (oid, e))
            evidence(rec)
            rc = 1

    # ---------- 阶段二：动作（干跑只记录；enforce 且 arming 才真删） ----------
    for obj, rec in pending:
        oid = obj["id"]
        try:
            extra = rec["extra"]
            action = "observe"
            archive_meta = None
            if rec["deletable"] and effective == "enforce":
                if obj["kind"] == "table":
                    # 视图依赖闸：CH 允许删 MV 的源表/目标表而留下悬空 MV。依赖它的
                    # MV/视图若不在"本运行可删集合"内（不在清单或未达判定），拒绝删除
                    # 并留证——悬空 MV 的处置（是否纳入清单）归运营者裁决。
                    deps = dependent_views(ch, obj["db"], obj["table"])
                    extra["dependent_views"] = deps
                    blocking = [d for d in deps
                                if ("%s.%s" % (obj["db"], d)) not in deletable_set]
                    if blocking:
                        action = "blocked-dependent-view"
                        rec["reason"] = ("dependent views 未纳入本运行可删集合: %s"
                                         % ", ".join(blocking))
                    else:
                        os.makedirs(archive_dir, exist_ok=True)
                        archive_meta = archive_table(ch, obj, archive_dir, run_id)
                        delete_table(ch, obj)
                        action = "delete-table"
                else:
                    stale, mismatch = compute_stale(ch, obj)
                    extra["stale_keys"] = len(stale)
                    extra["stale_preview"] = ["%s@%s" % (s["line_id"], s["hour"]) for s in stale[:8]]
                    extra["count_mismatch_total"] = len(mismatch)
                    if not stale:
                        action = "noop-no-stale-rows"
                    else:
                        os.makedirs(archive_dir, exist_ok=True)
                        archive_meta = archive_rowset(ch, obj, archive_dir, run_id, stale)
                        delete_rowset(ch, obj, [(s["line_id"], s["hour"]) for s in stale])
                        action = "delete-stale-rows"
                        extra["deleted_keys"] = ["%s@%s" % (s["line_id"], s["hour"]) for s in stale]
                rec["archive"] = archive_dir if archive_meta else None
            elif rec["deletable"] and effective == "dry-run":
                action = "observe-deletable-blocked-by-dryrun"

            rec["action"] = action
            log("[%-8s] %s (%s) rows=%s last_accessed=%s idle7d=%s(%s) streak=%d deletable=%s"
                % (action, oid, obj["kind"], rec["rows"], rec["last_accessed_at"] or "保留期内无",
                   "yes" if rec["idle_7d"] else "no", rec["reason"], rec["streak"],
                   "yes" if rec["deletable"] else "no")
                + ("" if not extra.get("count_mismatch_total") else
                   " | 计数不符告警 %d 条（不删，仅记录）" % extra["count_mismatch_total"])
                + ("" if action != "blocked-dependent-view" else
                   " | 依赖视图未达可删判定，拒绝删除（fail-closed）"))
            evidence(rec)
        except CHError as e:
            rec["action"] = "error"
            rec["reason"] = str(e)
            log("[error]    %s — %s（未删除，fail-closed）" % (oid, e))
            evidence(rec)
            rc = 1

    try:
        with open(args.state_file, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=1)
    except OSError as e:
        log("mes-ttl-sweep: 状态文件写入失败: %s" % e)
        rc = 1
    log("===== run=%s done (effective=%s, 明细见 evidence jsonl) =====" % (run_id, effective))
    log_fp.close()
    ev_fp.close()
    # 退出码合成（机器可消费，2026-11-03）：
    #   otel 红牌单独 = 4；otel 红牌 + 主 CH 不可达/运行错误 = 5（双红）；无红牌 = 0/1。
    #   漂移（audit-ttl-drift）与不漂移（observe）在主锚活/死两种现势下退出码均可区分
    #   ——旧码主锚死态下恒占 rc=1，漂移与否不可区分。
    if otel_audit_fail:
        rc = 5 if rc else 4
    return rc


if __name__ == "__main__":
    sys.exit(main())
