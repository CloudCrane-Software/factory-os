#!/usr/bin/env python3
"""ch_client.py — mingda CH 连接与查询（OTel 库管理面，零明文纪律）。

凭据解析链（与 tools/bench-mes.py F-11 同口径，扩展 openBao 源）：
  1. 入参 url ＞ 环境变量 OTEL_CH_URL ＞ 环境变量 MES_CH_URL
  2. openBao kv/data/opch/obs/clickhouse-otel（user/password 两字段；bao-agent 现取，
     输出重定向进内存、绝不进转录/日志——AGENT.md 硬纪律 1）
  3. 0600 凭据文件 ~/.config/mes-ch/url（F-11 既有链）
  4. 缺省端点 http://mes-host.invalid:15221（无凭据→401 显性失败，不静默写错库）

纪律：口令只进 HTTP Basic 头；任何输出/异常只含端点与库名，绝不含凭据值。
openBao 源登记：2026-10-28 实测该 secret（opch_otel 用户）认证 mingda:15221 失败
（AUTHENTICATION_FAILED），链上保留作显式覆盖位，缺省走 F-11 链——见 amvp-report.md 降级 D-3。
"""
import base64
import json
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_ENDPOINT = "http://mes-host.invalid:15221"
BAO_AGENT = os.path.expanduser("~/.local/bin/bao-agent")
BAO_PATH = "kv/data/opch/obs/clickhouse-otel"
MES_CH_FILE = os.path.expanduser("~/.config/mes-ch/url")


class CHError(Exception):
    pass


def _bao_field(field: str) -> str:
    """openBao 现取单字段明文（子进程 stdout 直读，不回显、不进日志）。"""
    r = subprocess.run([BAO_AGENT, "get", BAO_PATH, "--reveal"],
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise CHError(f"openBao 读取失败 rc={r.returncode}")
    d = json.loads(r.stdout)

    def find(o):
        if isinstance(o, dict):
            if field in o and isinstance(o[field], str):
                return o[field]
            for v in o.values():
                hit = find(v)
                if hit:
                    return hit
        return None

    v = find(d)
    if not v:
        raise CHError(f"openBao {BAO_PATH} 无字段 {field}")
    return v


def resolve(url: str | None = None, use_bao: bool = False) -> tuple[str, str | None]:
    """→ (base_url, auth_header)。url 形如 http://user:pass@host:port 或裸端点。"""
    if url is None:
        url = os.environ.get("OTEL_CH_URL") or os.environ.get("MES_CH_URL")
    if not url and use_bao:
        try:
            user = _bao_field("user")
            pw = _bao_field("password")
            url = f"http://{urllib.parse.quote(user)}:{urllib.parse.quote(pw)}@{DEFAULT_ENDPOINT.split('://', 1)[1]}"
        except Exception:
            url = None
    if not url:
        try:
            with open(MES_CH_FILE, encoding="utf-8") as f:
                url = f.read().strip()
        except OSError:
            url = DEFAULT_ENDPOINT
    auth = None
    if "@" in url:
        scheme, rest = url.split("://", 1)
        userinfo, hostpart = rest.split("@", 1)
        url = f"{scheme}://{hostpart}"
        auth = "Basic " + base64.b64encode(userinfo.encode()).decode()
    return url, auth


def query(sql: str, url: str | None = None, fmt: str = "JSONEachRow") -> list[dict]:
    base, auth = resolve(url)
    full = base + "/?query=" + urllib.parse.quote(sql)
    if fmt:
        full += "&default_format=" + fmt
    req = urllib.request.Request(full)
    if auth:
        req.add_header("Authorization", auth)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            rows = []
            for line in r.read().decode().splitlines():
                if line.strip():
                    rows.append(json.loads(line))
            return rows
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise CHError(f"CH HTTP {e.code}: {body[:300]}") from None
    except Exception as e:
        raise CHError(f"CH 连接失败（端点 {base}）: {e}") from None


def query_post(sql: str, url: str | None = None, fmt: str = "JSONEachRow") -> list[dict]:
    """POST 体通道查询（query() 的姊妹通道，2026-11-01 MES 队列补投收口）。

    GET 通道（query()）把整条 SQL 放进查询串：HTTP 表单字段值有长度上限，mingda CH
    实测超限即 HTTP 500 `Poco::Exception … HTML Form Exception: Field value too long`
    ——大 IN 清单（如 factory-status-push MES 队列全量 event_id 预查，数千个 id 一条
    IN）必须走 POST 体。注意查询文本本身仍受服务端 max_query_size（默认 262,144B）
    解析上限，超大清单调用方自行分批。凭据解析/鉴权/异常口径与 query() 完全一致。"""
    base, auth = resolve(url)
    req = urllib.request.Request(base + ("/?default_format=" + fmt if fmt else "/"),
                                 data=sql.encode(), headers={"Content-Type": "text/plain"})
    if auth:
        req.add_header("Authorization", auth)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            rows = []
            for line in r.read().decode().splitlines():
                if line.strip():
                    rows.append(json.loads(line))
            return rows
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise CHError(f"CH HTTP {e.code}: {body[:300]}") from None
    except Exception as e:
        raise CHError(f"CH 连接失败（端点 {base}）: {e}") from None


def execute(sql: str, url: str | None = None) -> None:
    base, auth = resolve(url)
    req = urllib.request.Request(base + "/", data=sql.encode(),
                                 headers={"Content-Type": "text/plain"})
    if auth:
        req.add_header("Authorization", auth)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            r.read()
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise CHError(f"CH HTTP {e.code}: {body[:300]}") from None
    except Exception as e:
        raise CHError(f"CH 连接失败（端点 {base}）: {e}") from None


def split_statements(sql_text: str) -> list[str]:
    """按行级分号切段；跳过纯注释行与空段（本 DDL 无心号内嵌）。"""
    stmts, buf = [], []
    for line in sql_text.splitlines():
        s = line.strip()
        if s.startswith("--") and not buf:
            continue
        buf.append(line)
        if s.endswith(";"):
            stmt = "\n".join(buf).strip()
            body = "\n".join(l for l in buf if not l.strip().startswith("--")).strip()
            if body:
                stmts.append(stmt)
            buf = []
    tail = "\n".join(buf).strip()
    if tail:
        stmts.append(tail)
    return stmts


def apply_ddl(path: str, url: str | None = None) -> list[str]:
    """逐段执行 DDL 文件（幂等：全 CREATE IF NOT EXISTS）。返回已执行段首行摘要。"""
    done = []
    with open(path, encoding="utf-8") as f:
        for stmt in split_statements(f.read()):
            execute(stmt, url)
            head = next(l for l in stmt.splitlines() if l.strip() and not l.strip().startswith("--"))
            done.append(head.strip()[:80])
    return done


if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3 and sys.argv[1] == "query":
        for row in query(sys.argv[2]):
            print(json.dumps(row, ensure_ascii=False))
    elif len(sys.argv) >= 3 and sys.argv[1] == "apply":
        for s in apply_ddl(sys.argv[2]):
            print("OK:", s)
    else:
        print("用法: ch_client.py query <sql> | apply <ddl.sql>")
