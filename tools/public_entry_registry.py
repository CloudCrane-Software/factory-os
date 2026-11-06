#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""public_entry_registry.py — 公网入口登记册正本（配置面 ↔ 运行时面共享的唯一权威副本）

纪律原文（CI门族确证发现「公网入口登记纪律」，修复前状态 2026-11-03 实测）：
  「入口清单是本探针的登记册：工厂侧新增公网反代入口必须登记进 ENTRIES
   （新公网反代入口 → 追加一行，缺登记=巡检盲区）」——修复前该纪律**零机检**：
  · 配置面门 tools/caddy-deploy-integrity-probe.sh（B/D 腿）知道五个公网限速 zone
    （afjobs_ai_pub×1 / jobs_pub×2 / otlp_pub×1 / zhihui_pub×1，即 gov
    ops/caddy/Caddyfile 里带 rate_limit 的公网 site 块），
  · 运行时行为面门 tools/rate-limit-symmetry-probe.py 的 ENTRIES 与
    tools/test-path-traversal-404.py 的 ENTRANCES 只有三条（jobs./factory./ai./af-jobs），
  · 两面之间无任何对账件（grep 'caddy|Caddyfile' tools/rate-limit-symmetry-probe.py
    仅注释命中），也无第三个独立登记册文件——
  ⇒ otlp./zhihui. 两个**已限速**公网口的运行时「429 真出现」「穿越真 404」两个行为
    断言零门覆盖；且新增公网反代入口若漏登记，三个门全绿（巡检盲区）。

本模块=登记册正本（唯一副本，配置面与运行时面共用同一份数据）：
  · ENTRIES：五条公网限速入口逐条登记——
      slug           入口短名（输出用）
      base           运行时面 URL（探针实际打点；ai. 带 /af-jobs 前缀）
      caddy_site     配置面 site 块标识（与 gov ops/caddy/Caddyfile 逐字对应）
      kind           入口类型（portal=af-jobs 门户面 / ingest=OTLP 摄入口 / demo=演示站）
      contract_mode  穿越腿契约口径：
                       content=该入口有公开契约体（200 体必须逐字节等于契约参照件；
                               参照件取不到=不可证=fail-closed）
                       auth   =该入口无公开内容（静态 bearer 认证面）：未认证基线必须
                               401/403（fail-closed），穿越变体出现 200=未认证泄露=红
                       none   =无契约参照（仅断言穿越变体不得 200）
      contract_path  契约参照件路径（content 模式）
      probe_path     限速腿打压路径（B 腿并发打此路径断言 429 出现）
  · parse_sites()/public_zoned_sites()：Caddyfile 顶层 site 块解析（site → zone 列表）
    ——配置面↔登记册对账门（tools/public-entry-registry-check.py）用。
  · expand_site()：site 头里的 {$DOMAIN} 展开成主机名。DOMAIN 权威值取
    gov:/opt/company/platform/ops/compose/.env（不在本模块写死——写死=第二份正本）。

调用方（三处，共用同一份正本，不允许各写一份手抄清单）：
  · tools/rate-limit-symmetry-probe.py    运行时行为面（429 + 穿越两腿，五入口全覆盖）
  · tools/test-path-traversal-404.py       门户穿越回归（registry kind=portal 三入口）
  · tools/public-entry-registry-check.py   登记对账门（缺登记=红）

退出码约定（本模块自身不退出）：登记册不合规一律抛 RegistryError，调用方必须
fail-closed（不可证不猜绿），不得静默退回内置清单。
"""

import re

# ---------------------------------------------------------------------------
# 登记册正本（五条公网限速入口 = gov ops/caddy/Caddyfile 中带 rate_limit zone
# 的公网 site 块逐条对应；新增公网反代入口 → 追加一条，缺登记=巡检盲区=红）
# ---------------------------------------------------------------------------
ENTRIES = [
    {
        "slug": "jobs",
        "base": "https://jobs.hkmingdajiaoyu.com",
        "caddy_site": "jobs.{$DOMAIN}",
        "kind": "portal",
        "contract_mode": "content",
        "contract_path": "/AGENTS.md",
        "probe_path": "/healthz",
        "note": "正口（Caddy jobs. 块，zone jobs_pub，P3-4）",
    },
    {
        "slug": "factory",
        "base": "https://factory.hkmingdajiaoyu.com",
        "caddy_site": "factory.{$DOMAIN}",
        "kind": "portal",
        "contract_mode": "content",
        "contract_path": "/AGENTS.md",
        "probe_path": "/healthz",
        "note": "只读镜像（Caddy factory. 块，zone jobs_pub，写端点 404）",
    },
    {
        "slug": "ai",
        "base": "https://ai.hkmingdajiaoyu.com/af-jobs",
        "caddy_site": "ai.{$DOMAIN}",
        "kind": "portal",
        "contract_mode": "content",
        "contract_path": "/AGENTS.md",
        "probe_path": "/healthz",
        "note": "临时镜像（Higress 路由，zone afjobs_ai_pub，af-jobs-interim 20261027）",
    },
    {
        "slug": "otlp",
        "base": "https://otlp.hkmingdajiaoyu.com",
        "caddy_site": "otlp.{$DOMAIN}",
        "kind": "ingest",
        "contract_mode": "auth",
        "contract_path": "/",
        "probe_path": "/healthz",
        "note": "公网 OTLP 摄入口（zone otlp_pub；静态 bearer 认证——未认证面恒 401 fail-closed）",
    },
    {
        "slug": "zhihui",
        "base": "https://zhihui.hkmingdajiaoyu.com",
        "caddy_site": "zhihui.{$DOMAIN}",
        "kind": "demo",
        "contract_mode": "content",
        "contract_path": "/health",
        "probe_path": "/health",
        "note": "智绘龙江大赛演示站（zone zhihui_pub；/docs 与 /openapi.json 一律 404）",
    },
]

REQUIRED_FIELDS = ("slug", "base", "caddy_site", "kind",
                   "contract_mode", "contract_path", "probe_path")
VALID_KINDS = ("portal", "ingest", "demo")
VALID_CONTRACT_MODES = ("content", "auth", "none")


class RegistryError(Exception):
    """登记册不合规（调用方必须 fail-closed——不可证不猜绿）。"""


def host_of(base):
    """https://host[:port]/path → host[:port]（登记册 base 的主机名部分）。"""
    rest = base.split("://", 1)[-1]
    return rest.split("/", 1)[0]


def validate_entries(entries):
    """登记册 schema 自检；不合规抛 RegistryError（调用方 fail-closed）。"""
    if not isinstance(entries, list) or not entries:
        raise RegistryError("登记册为空——入口册为空=巡检盲区（不可证不猜绿）")
    seen_slug, seen_base = set(), set()
    for i, e in enumerate(entries):
        if not isinstance(e, dict):
            raise RegistryError(f"登记册第 {i} 条不是 dict")
        for f in REQUIRED_FIELDS:
            if not isinstance(e.get(f), str) or not e[f].strip():
                raise RegistryError(f"登记册第 {i} 条缺字段 {f}（slug={e.get('slug')!r}）")
        if e["kind"] not in VALID_KINDS:
            raise RegistryError(f"登记册第 {i} 条 kind 非法：{e['kind']!r}（允许 {VALID_KINDS}）")
        if e["contract_mode"] not in VALID_CONTRACT_MODES:
            raise RegistryError(f"登记册第 {i} 条 contract_mode 非法：{e['contract_mode']!r}"
                                f"（允许 {VALID_CONTRACT_MODES}）")
        if not e["base"].startswith("https://"):
            raise RegistryError(f"登记册第 {i} 条 base 非 https：{e['base']!r}")
        if not e["contract_path"].startswith("/") or not e["probe_path"].startswith("/"):
            raise RegistryError(f"登记册第 {i} 条 contract_path/probe_path 必须以 / 开头")
        host = host_of(e["base"])
        label = e["caddy_site"].split(".")[0]
        if not host.startswith(label + "."):
            raise RegistryError(f"登记册第 {i} 条 base 主机名 {host!r} 与 caddy_site 标签 "
                                f"{label!r} 不符（登记册与配置面域名漂移）")
        if e["slug"] in seen_slug:
            raise RegistryError(f"登记册 slug 重复：{e['slug']!r}")
        if e["base"] in seen_base:
            raise RegistryError(f"登记册 base 重复：{e['base']!r}")
        seen_slug.add(e["slug"])
        seen_base.add(e["base"])
    return entries


def load_entries(entries=None):
    """返回校验过的登记册条目列表（默认本模块正本 ENTRIES）。"""
    return validate_entries(list(ENTRIES) if entries is None else list(entries))


def portal_entries(entries=None):
    """门户面入口（kind=portal）——门户穿越回归门（test-path-traversal-404.py）的入口集。"""
    return [e for e in load_entries(entries) if e["kind"] == "portal"]


# ---------------------------------------------------------------------------
# Caddyfile 解析（配置面读数；纯函数、零网络）
# ---------------------------------------------------------------------------
_SITE_RE = re.compile(r"^(\S.*?)\s*\{\s*$")
_ZONE_RE = re.compile(r"\bzone\s+([A-Za-z0-9_\-]+)")
_RATELIMIT_RE = re.compile(r"\brate_limit\s*\{")


def parse_sites(text):
    """解析 Caddyfile 顶层 site 块 → [{site, zones, has_ratelimit}]。

    顶层 site 头形如 `jobs.{$DOMAIN} {`（列 0）；嵌套块（route/rate_limit/…）缩进，
    只贡献 zone 名；列 0 的 `}` 收束当前 site 块；全局 options 块（单独 `{`）不计。
    """
    sites, cur = [], None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if not line[:1].isspace():                       # 顶层行
            if line.strip() == "}":
                cur = None
                continue
            m = _SITE_RE.match(line)
            if m:
                cur = {"site": m.group(1).strip(), "zones": [], "has_ratelimit": False}
                sites.append(cur)
            else:
                cur = None                              # 非 site 顶层行（全局 options 块等）
            continue
        if cur is None:                                  # 缩进行但不在 site 块内 → 忽略
            continue
        if _RATELIMIT_RE.search(line):
            cur["has_ratelimit"] = True
        m = _ZONE_RE.search(line)
        if m:
            cur["zones"].append(m.group(1))
    return sites


def expand_site(site, domain):
    """把 site 头里的 {$DOMAIN} 展开成主机名；残留未知占位符 → None（不可对账）。"""
    out = site.replace("{$DOMAIN}", domain)
    return None if "{$" in out else out


def public_zoned_sites(text, domain):
    """配置面公网限速口 → (dns_map, other_list)。

    dns_map  = {主机名: [zone...]}（带 zone 的 DNS 名 site 块；登记册对账对象）
    other    = [(site, zones)]（带 zone 但非 DNS 名 site 块——非公网入口登记对象，
               显式列出不静默丢弃）
    """
    dns_map, other = {}, []
    for s in parse_sites(text):
        if not s["zones"]:
            continue
        host = expand_site(s["site"], domain)
        if host is None or "://" in host or "." not in host:
            other.append((s["site"], list(s["zones"])))
            continue
        dns_map.setdefault(host, []).extend(s["zones"])
    return dns_map, other
