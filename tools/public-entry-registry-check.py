#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""public-entry-registry-check.py — 公网入口登记对账门（缺登记=巡检盲区=红）

发现（CI门族确证发现「公网入口登记纪律」，2026-11-03）：纪律自陈
「入口清单是本探针的登记册：工厂侧新增公网反代入口必须登记进 ENTRIES
（缺登记=巡检盲区）」，但**零机检**：
  · 配置面门 tools/caddy-deploy-integrity-probe.sh（B/D 腿）知道五个公网限速 zone
    （afjobs_ai_pub×1 / jobs_pub×2 / otlp_pub×1 / zhihui_pub×1），
  · 运行时行为面门 tools/rate-limit-symmetry-probe.py 的 ENTRIES 与
    tools/test-path-traversal-404.py 的 ENTRANCES 只有三条（jobs./factory./ai./af-jobs），
  · 两面之间无任何对账件（grep 'caddy|Caddyfile' tools/rate-limit-symmetry-probe.py
    仅注释命中），也无第三个独立登记册文件——
  ⇒ otlp./zhihui. 两个**已限速**公网口的运行时「429 真出现」「穿越真 404」两个行为
    断言零门覆盖；且新增公网反代入口若漏登记，三个门全绿（巡检盲区）。

本门=登记纪律的机检替身，三方对账（判据源=登记册正本 tools/public_entry_registry.py
与 gov 在役配置面 ops/caddy/Caddyfile，两面互为对方的上游）：
  ① 配置面 → 登记册：gov Caddyfile（HEAD 正本 + 在役挂载源双面）里带 rate_limit
     zone 的公网 site 块，每个都必须登记进正本册——**缺登记即红**（巡检盲区）。
  ② 登记册 → 配置面：正本册每条都必须在配置面有对应限速 site（登记漂移即红：
     配置丢了 zone 或册子写了不存在的口）。
  ③ 登记册 ↔ 运行时探针：两个运行时探针必须**消费**登记册（入口册逐条相等；
     门户穿越回归门 = 正本册 kind=portal 条目），且探针源码内不得出现硬编码的
     公网入口 URL（第二份正本 = 漂移源）。
  ④ 配置面自漂：HEAD 正本与在役挂载源的公网限速口集合必须一致。

范围口径（如实）：本门对账对象=「带 rate_limit zone 的公网 DNS 名 site 块」。
langfuse./zot./net./board. 等无 zone 的公网站点与 tailnet-only 绑定（:8200/:3000）
系设计现状（见 tools/caddy-deploy-integrity-probe.sh 范围口径），不在登记对象内；
非 DNS 名却带 zone 的 site 块列为「范围外」并显式打印，不静默丢弃。

只读面：本门只读 gov（ssh cat/git show/grep），不动生产面任何文件。

用法：python3 -I tools/public-entry-registry-check.py [--selftest]
退出码：0 绿；1 红（缺登记/登记漂移/探针未消费登记册/配置面自漂）；2 前置失败
        （gov 不可达、Caddyfile 缺件、登记册坏件）——不可证不猜绿，不静默 SKIP。
--selftest：零网络判别力自证（夹具）——绿路 1 条 + 红路 7 条（缺登记/登记漂移/
        域名漂移/运行时探针未消费/门户册不符/硬编码 URL/配置面自漂），
        每条红路必须被判红、绿路必须判绿。
"""

import importlib.util
import os
import re
import subprocess
import sys

_TOOLS = os.path.dirname(os.path.abspath(__file__))
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)
import public_entry_registry as _reg                # noqa: E402 —— 登记册正本

GOV_SSH = "root@gov-host.invalid"
REPO = "/opt/company/platform"
CF_REL = "ops/caddy/Caddyfile"
ENV_REL = "ops/compose/.env"

RUNTIME_PROBE = "rate-limit-symmetry-probe.py"     # 运行时行为面探针（429 + 穿越两腿）
TRAVERSAL_PROBE = "test-path-traversal-404.py"      # 门户穿越回归门


class PreflightError(Exception):
    """前置失败（gov 不可达/缺件/登记册坏）——不可证不猜绿。"""


# --------------------------------------------------------------- gov 只读取数
def ssh_gov(cmd):
    r = subprocess.run(["ssh", "-o", "ConnectTimeout=10", "-o", "BatchMode=yes",
                        GOV_SSH, cmd], capture_output=True, text=True, timeout=90)
    if r.returncode != 0:
        raise PreflightError(f"gov 不可达/命令失败 rc={r.returncode}：{cmd[:120]}｜"
                             f"stderr={(r.stderr or '').strip()[:200]}")
    return r.stdout


def fetch_domain():
    out = ssh_gov(f"grep -E '^DOMAIN=' '{REPO}/{ENV_REL}' | head -1")
    dom = out.strip().split("=", 1)[-1].strip()
    if not dom or "." not in dom:
        raise PreflightError(f"gov {ENV_REL} 的 DOMAIN 取不到（读到 {out!r}）——site 块无法展开")
    return dom


def fetch_caddyfiles():
    head = ssh_gov(f"cd '{REPO}' && git show HEAD:{CF_REL}")
    live = ssh_gov(f"cat '{REPO}/{CF_REL}'")
    if not head.strip() or not live.strip():
        raise PreflightError(f"gov {CF_REL} 读数为空（HEAD 正本/在役挂载源）——配置面不可证")
    return {"HEAD正本": head, "在役挂载源": live}


def _import_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise PreflightError(f"模块加载失败：{path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_runtime_views():
    """读两个运行时探针的入口册视图 + 源码（判据=它们是否消费登记册）。"""
    views = {}
    for fname, attr in ((RUNTIME_PROBE, "ENTRIES"), (TRAVERSAL_PROBE, "ENTRANCES")):
        path = os.path.join(_TOOLS, fname)
        if not os.path.isfile(path):
            raise PreflightError(f"运行时探针缺件：{path}")
        try:
            mod = _import_module(path, "regchk_" + fname.replace("-", "_").replace(".", "_"))
        except SystemExit as e:            # 探针自身 fail-closed（登记册坏件等）
            raise PreflightError(f"运行时探针 {fname} 导入即退 rc={e.code}") from e
        except Exception as e:             # noqa: BLE001
            raise PreflightError(f"运行时探针 {fname} 导入异常：{e!r}") from e
        views[attr] = list(getattr(mod, attr, []))
        views.setdefault("sources", {})[fname] = open(path, encoding="utf-8").read()
    return views["ENTRIES"], views["ENTRANCES"], views["sources"]


# --------------------------------------------------------------- 对账本体
def reconcile(registry, config_texts, domain, runtime_bases, traversal_entrances,
              probe_sources=None):
    """配置面 ↔ 登记册正本 ↔ 运行时探针 三方对账（纯函数，零网络）。"""
    failures, notes = [], []
    cfg = {}
    for label, text in config_texts.items():
        dns, other = _reg.public_zoned_sites(text, domain)
        cfg[label] = dns
        for site, zones in other:
            notes.append(f"范围外（{label}）：非 DNS 名 site 块带限速 zone（{site} → {zones}）"
                         f"——非公网入口登记对象，人工确认")

    reg_hosts = {}
    for e in registry:
        host = _reg.expand_site(e["caddy_site"], domain)
        if host is None:
            failures.append(f"登记册条目 {e['slug']}：caddy_site={e['caddy_site']!r} 无法用 "
                            f"DOMAIN={domain} 展开（未知占位符）——不可对账")
            continue
        base_host = _reg.host_of(e["base"])
        if base_host != host:
            failures.append(f"登记册条目 {e['slug']}：base 主机名 {base_host} ≠ caddy_site 展开值 "
                            f"{host}（登记册与配置面域名漂移）")
        reg_hosts[host] = e

    for label, dns in cfg.items():
        missing = sorted(set(dns) - set(reg_hosts))
        if missing:
            failures.append(f"缺登记（{label}）：{len(missing)} 个公网限速口未登记进正本册 "
                            f"{missing}——巡检盲区（运行时行为面测不到，429/穿越两腿零覆盖）")
        extra = sorted(set(reg_hosts) - set(dns))
        if extra:
            failures.append(f"登记漂移（{label}）：{len(extra)} 个正本册条目在配置面无对应限速 site "
                            f"{extra}——登记册与 Caddyfile 不一致")
    labels = list(cfg)
    if len(labels) == 2 and set(cfg[labels[0]]) != set(cfg[labels[1]]):
        failures.append(f"配置面自漂：{labels[0]} 与 {labels[1]} 的公网限速口集合不一致"
                        f"（{sorted(cfg[labels[0]])} vs {sorted(cfg[labels[1]])}）")

    reg_bases = [e["base"] for e in registry]
    if sorted(runtime_bases) != sorted(reg_bases):
        failures.append(f"运行时探针入口册 ≠ 正本册：探针={sorted(runtime_bases)} "
                        f"正本册={sorted(reg_bases)}——存在第二份手抄入口册或探针未消费登记册")
    portal_exp = [(e["slug"], e["base"]) for e in registry if e["kind"] == "portal"]
    if sorted(traversal_entrances) != sorted(portal_exp):
        failures.append(f"门户穿越回归门入口册 ≠ 正本册门户条目(kind=portal)：门="
                        f"{sorted(traversal_entrances)} 正本册={sorted(portal_exp)}")
    for fname, src in (probe_sources or {}).items():
        for i, line in enumerate(src.splitlines(), 1):
            for e in registry:
                lit = f"https://{_reg.host_of(e['base'])}"
                if lit in line:
                    failures.append(f"运行时探针 {fname}:{i} 出现硬编码公网入口 URL {lit}"
                                    f"——须从登记册消费（第二份正本=漂移源）")
    return {"failures": failures, "notes": notes, "cfg": cfg, "reg_hosts": reg_hosts}


# --------------------------------------------------------------- 判别力自证
FIX_DOMAIN = "hkmingdajiaoyu.com"
FIX_CADDY = """# 夹具 Caddyfile（零网络）
jobs.{$DOMAIN} {
	rate_limit {
		zone jobs_pub {
			key {http.request.remote.host}
			window 1m
			events 120
		}
	}
	reverse_proxy 172.18.0.1:8090
}

otlp.{$DOMAIN} {
	route {
		rate_limit {
			zone otlp_pub {
				key {http.request.remote.host}
				window 1m
				events 120
			}
		}
		reverse_proxy otelcol:4318
	}
}
"""
FIX_CADDY_NO_OTLP = """# 夹具 Caddyfile（在役面少了 otlp. 限速块 → 配置面自漂）
jobs.{$DOMAIN} {
	rate_limit {
		zone jobs_pub {
			key {http.request.remote.host}
			window 1m
			events 120
		}
	}
	reverse_proxy 172.18.0.1:8090
}
"""
FIX_REGISTRY = [
    {"slug": "jobs", "base": "https://jobs.hkmingdajiaoyu.com",
     "caddy_site": "jobs.{$DOMAIN}", "kind": "portal", "contract_mode": "content",
     "contract_path": "/AGENTS.md", "probe_path": "/healthz"},
    {"slug": "otlp", "base": "https://otlp.hkmingdajiaoyu.com",
     "caddy_site": "otlp.{$DOMAIN}", "kind": "ingest", "contract_mode": "auth",
     "contract_path": "/", "probe_path": "/healthz"},
]


def _fix_case(registry=None, texts=None, runtime=None, traversal=None, sources=None):
    reg = registry if registry is not None else FIX_REGISTRY
    tx = texts if texts is not None else {"HEAD正本": FIX_CADDY, "在役挂载源": FIX_CADDY}
    rt = runtime if runtime is not None else [e["base"] for e in FIX_REGISTRY]
    tv = traversal if traversal is not None else [("jobs", "https://jobs.hkmingdajiaoyu.com")]
    src = sources if sources is not None else {}
    return reconcile(reg, tx, FIX_DOMAIN, rt, tv, src)


def selftest():
    results = []

    def case(name, expect_red, res):
        fails = res["failures"]
        ok = (bool(fails) == expect_red)
        detail = (fails[0][:150] if fails else "无失败项")
        results.append((name, ok, detail))

    # 绿路①：配置面两口 ↔ 登记册两条 ↔ 探针入口册一致 → 无失败项
    case("G1 判别力·登记齐全无失败项", False, _fix_case())

    # 红路①：配置面新增一个限速口、登记册未登记 → 缺登记
    extra_cfg = FIX_CADDY + """
zhihui.{$DOMAIN} {
	route {
		rate_limit {
			zone zhihui_pub {
				key {http.request.remote.host}
				window 1m
				events 120
			}
		}
		reverse_proxy zhihui-demo:8307
	}
}
"""
    case("R1 判别力·配置面新增限速口未登记 → 缺登记红", True,
         _fix_case(texts={"HEAD正本": extra_cfg, "在役挂载源": extra_cfg}))

    # 红路②：登记册多一条、配置面没有 → 登记漂移
    reg_extra = list(FIX_REGISTRY) + [{
        "slug": "zhihui", "base": "https://zhihui.hkmingdajiaoyu.com",
        "caddy_site": "zhihui.{$DOMAIN}", "kind": "demo", "contract_mode": "content",
        "contract_path": "/health", "probe_path": "/health"}]
    case("R2 判别力·登记册多一条配置面无 → 登记漂移红", True, _fix_case(registry=reg_extra))

    # 红路③：登记册条目 base 主机名与 caddy_site 不符 → 域名漂移
    reg_drift = [dict(e) for e in FIX_REGISTRY]
    reg_drift[0] = dict(reg_drift[0], base="https://jobs.example.com")
    case("R3 判别力·登记册域名漂移红", True, _fix_case(registry=reg_drift))

    # 红路④：运行时探针入口册少一条（未消费登记册）→ 红
    case("R4 判别力·运行时探针入口册≠正本册红", True,
         _fix_case(runtime=["https://jobs.hkmingdajiaoyu.com"]))

    # 红路⑤：门户穿越门入口册与正本册门户条目不符 → 红
    case("R5 判别力·门户穿越门入口册≠正本册红", True, _fix_case(traversal=[]))

    # 红路⑥：运行时探针源码里出现硬编码公网入口 URL（第二份正本）→ 红
    case("R6 判别力·探针内硬编码入口 URL 红", True,
         _fix_case(sources={RUNTIME_PROBE: 'ENTRIES = ["https://jobs.hkmingdajiaoyu.com"]\n'}))

    # 红路⑦：HEAD 正本与在役挂载源集合不一致（在役少了 otlp. 限速块）→ 配置面自漂红
    case("R7 判别力·配置面自漂红", True,
         _fix_case(texts={"HEAD正本": FIX_CADDY, "在役挂载源": FIX_CADDY_NO_OTLP}))

    npass = sum(1 for _, ok, _ in results if ok)
    for n, ok, d in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {n} —— {d}")
    print(f"小计：PASS={npass} FAIL={len(results) - npass}")
    return 0 if npass == len(results) else 1


# --------------------------------------------------------------- 主流程
def main():
    argv = sys.argv[1:]
    if "--selftest" in argv:
        return selftest()
    try:
        registry = _reg.load_entries()
    except _reg.RegistryError as e:
        print(f"[RED rc=2] 登记册不合规：{e}——不可证不猜绿（fail-closed）", file=sys.stderr)
        return 2
    try:
        domain = fetch_domain()
        texts = fetch_caddyfiles()
        runtime_bases, traversal_entrances, sources = load_runtime_views()
    except PreflightError as e:
        print(f"[RED rc=2] 前置失败：{e}", file=sys.stderr)
        return 2

    res = reconcile(registry, texts, domain, runtime_bases, traversal_entrances, sources)
    cfg, reg_hosts = res["cfg"], res["reg_hosts"]
    head_hosts = set(cfg.get("HEAD正本", {}))
    print(f"配置面公网限速口（gov {CF_REL}，DOMAIN={domain}）：{len(head_hosts)} 个")
    for host in sorted(head_hosts):
        e = reg_hosts.get(host)
        tag = (f"登记={e['slug']}（{e['caddy_site']}）探针两腿=在册"
               if e else "登记=缺！巡检盲区")
        print(f"  - {host}  zone={','.join(cfg['HEAD正本'][host])}  {tag}")
    for n in res["notes"]:
        print(f"  [说明] {n}")
    for f in res["failures"]:
        print(f"  [FAIL] {f}")
    if res["failures"]:
        print(f"红：公网入口登记对账失守——{len(res['failures'])} 项（缺登记/漂移/未消费登记册/配置面自漂）")
        return 1
    print(f"绿：配置面 {len(head_hosts)} 个公网限速口 ↔ 登记册正本 {len(registry)} 条 ↔ "
          f"运行时探针入口册一致（缺登记=0 漂移=0 硬编码入口 URL=0）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
