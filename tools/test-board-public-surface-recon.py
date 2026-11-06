#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test-board-public-surface-recon.py — 看板**公网暴露面**一致性门（RT-E112）

背景（逃逸台账 RT-E112「账本一致批看板整改只落本地未达公网暴露面」；拦截机制①
「暴露面一致性门：状态/看板/ 本地件 vs curl 公网件 sha256 对账（或公网版落后
本地 mtime 超 N 即红）」；逃逸拦截-60.md:334「RT-E112 登记的暴露面一致性门仍未
施工」；欠账处置-20261103.md:96 RT-E112 行「销项复核批：判决『暴露面已一致』——
复核翻绿」）：
  · 2026-11-02 原缺陷：账本一致批对 状态/看板/v2/index.html 的整改（dataAge()
    陈旧标记）只落本地，公网 curl 到的 v2 页与修复前快照**逐字节一致**——整改
    声称治理的缺陷在唯一暴露面原样在场；且公网数据文件反而新鲜（公网数据新鲜
    + 页面陈旧 ⇒ 两个面各自读绿，缺陷不可感，模式⑭）。
  · 2026-11-02 18:3x 修复员-49 追记：公网页已与本地一致（curl 亲测 md5≡），
    数据面腿也修好（订单级 terminal 三键），但**机制①暴露面一致性门仍未施工**
    （自认「L5 门现只覆盖 portal 面」）⇒ 暴露面此后再次漂移时零机检可红。
  · RT-E165（逃逸台账:1355-1359）复现同根：「公网暴露面零机器巡检
    （RT-E112 一致性门未施工使暴露面漂移不可见）」。

本件 = 机制①的可落地最小闸：**公网面 × gov 在役面 × 本地正本**三方逐件逐键对账。
  面域（登记册）：公网 static/v2 面 = https://factory.hkmingdajiaoyu.com/static/v2
    （在役 gov:/opt/company/af-jobs/data/static/v2，由 caddy 直出）；
    本地正本 = 工作区 状态/看板/v2/（发布面正本镜像）。

判据（每腿都是可观测后果；任一不过 = 红，不静默 SKIP）：
  A 静态页字节对账：公网 index.html 的 sha256 ≡ 本地正本 ≡ gov 在役（三方同字节）。
    ——RT-E112 原缺陷面：公网页与本地整改页不等即红。
  B 动态件逐键对账（orders.json / stages.json / otel-sidecar.json）：
    B1 顶层键集三方相等（公网 ≡ 在役 ≡ 本地）——结构漂移即红（键集漂移＝消费端
       与生产端两套键名体制复发的那一面，RT-E165 的根因面）；
    B2 新鲜度：公网 ts 与在役 ts 距 now 均 ≤ MAX_AGE_S（陈旧即红）——
       「公网数据陈旧」这一形态本门唯一能测的面；
    B3 暴露滞后：公网 ts ≥ 在役 ts − LAG_TOL_S（公网面落后在役面超一个发布周期
       即红 = 暴露面漂移）；
    B4 订单键集：公网 orders[] 的 order_id 集合 ⊆ 在役 orders[] 的 order_id 集合
       （公网面出现在役面没有的订单键 = 伪件/漂移）。
  C fail-closed：公网或在役不可达/不可解析 ⇒ 红（不可证不猜绿）。

判别力自证（--selftest，零公网零在役）：
  G 绿路：三方一致且新鲜 ⇒ 全腿绿；
  R1 篡改公网 index.html 字节 ⇒ A 腿必红；
  R2 公网 ts 陈旧（now−1h）⇒ B2 腿必红；
  R3 公网顶层缺键 ⇒ B1 腿必红；
  R4 公网含在役没有的 order_id ⇒ B4 腿必红；
  R5 公网 ts 落后在役 1h ⇒ B3 腿必红；
  R6 在役面不可达（不可证）⇒ C 腿必红。
  任一红路未被判红 ⇒ 本门判别力不成立（红）。

用法：python3 -I tools/test-board-public-surface-recon.py [--selftest]
退出码：0 全绿；1 有红（含 fail-closed 不可证）；2 门件自身异常（本地正本缺件等）。
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCAL_DIR = os.path.join(WS, "状态", "看板", "v2")
PUBLIC_BASE = "https://factory.hkmingdajiaoyu.com/static/v2"
GOV_SSH = os.environ.get("GOV_SSH", "root@gov-host.invalid")
GOV_DIR = os.environ.get("GOV_STATIC_V2", "/opt/company/af-jobs/data/static/v2")

# 面域登记：静态页（字节恒定，逐字节对账）+ 三件动态数据（逐键 + 新鲜度对账）
STATIC_FILES = ["index.html"]
DYNAMIC_FILES = ["orders.json", "stages.json", "otel-sidecar.json"]
ALL_FILES = STATIC_FILES + DYNAMIC_FILES

MAX_AGE_S = 900        # 公网/在役 ts 距 now 的上限（陈旧即红）
LAG_TOL_S = 180        # 公网 ts 落后在役 ts 的上限（一个发布周期量级）
HTTP_TIMEOUT = 30
SSH_TIMEOUT = 60


# ---------------------------------------------------------------- 面读取
def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def fetch_public(path):
    """公网面取件。返回 bytes；不可达抛异常（调用方 fail-closed）。"""
    url = f"{PUBLIC_BASE}/{path}"
    req = urllib.request.Request(url, headers={"User-Agent": "af-board-surface-recon/1"})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
        if r.status != 200:
            raise RuntimeError(f"公网面非 200：{url} → {r.status}")
        return r.read()


_LIVE_HELPER = r'''
import hashlib, json, os, sys
d = sys.argv[1]
out = {}
for fn in sys.argv[2:]:
    p = os.path.join(d, fn)
    try:
        raw = open(p, "rb").read()
    except Exception as e:
        out[fn] = {"error": str(e)}
        continue
    rec = {"sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}
    if fn.endswith(".json"):
        try:
            doc = json.loads(raw)
            rec["keys"] = sorted(doc.keys())
            rec["ts"] = doc.get("ts")
            orders = doc.get("orders")
            if isinstance(orders, list):
                rec["order_ids"] = sorted(
                    o.get("order_id") for o in orders
                    if isinstance(o, dict) and o.get("order_id"))
        except Exception as e:
            rec["error"] = "json: %s" % e
    out[fn] = rec
print(json.dumps(out, ensure_ascii=False))
'''


def fetch_live_summary():
    """gov 在役面摘要（一次 ssh，取四件的 sha256/键集/ts/订单键集）。"""
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(_LIVE_HELPER)
        helper = f.name
    try:
        cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
               GOV_SSH, "python3 -", GOV_DIR] + ALL_FILES
        with open(helper, "rb") as stdin:
            r = subprocess.run(cmd, stdin=stdin, capture_output=True, timeout=SSH_TIMEOUT)
        if r.returncode != 0:
            raise RuntimeError(f"在役面 ssh rc={r.returncode}: "
                               f"{(r.stderr or b'').decode('utf-8', 'replace')[:200]}")
        return json.loads(r.stdout.decode("utf-8"))
    finally:
        try:
            os.unlink(helper)
        except OSError:
            pass


def local_side(path):
    """本地正本件 → 与在役面同构的摘要。"""
    p = os.path.join(LOCAL_DIR, path)
    with open(p, "rb") as f:
        raw = f.read()
    rec = {"sha256": sha256_bytes(raw), "size": len(raw)}
    if path.endswith(".json"):
        doc = json.loads(raw)
        rec["keys"] = sorted(doc.keys())
        rec["ts"] = doc.get("ts")
        orders = doc.get("orders")
        if isinstance(orders, list):
            rec["order_ids"] = sorted(o.get("order_id") for o in orders
                                      if isinstance(o, dict) and o.get("order_id"))
    return rec


def public_side(raw, path):
    rec = {"sha256": sha256_bytes(raw), "size": len(raw)}
    if path.endswith(".json"):
        doc = json.loads(raw)
        rec["keys"] = sorted(doc.keys())
        rec["ts"] = doc.get("ts")
        orders = doc.get("orders")
        if isinstance(orders, list):
            rec["order_ids"] = sorted(o.get("order_id") for o in orders
                                      if isinstance(o, dict) and o.get("order_id"))
    return rec


# ---------------------------------------------------------------- 判据核心（可注入夹具）
def reconcile(public_raws, live_sum, local_sums, now_ms):
    """三方对账。public_raws: {fn: bytes|None}；live_sum/local_sums: {fn: rec}。
    返回 (fails, legs)（legs = 每腿读数，供留证）。"""
    fails = []
    legs = []

    # ---- A 静态页字节对账 ----
    for fn in STATIC_FILES:
        raw = public_raws.get(fn)
        if raw is None:
            fails.append(f"A 静态页 {fn} 红：公网面取件失败（不可证）")
            legs.append((f"A/{fn}", "红", "公网面取件失败"))
            continue
        pub = public_side(raw, fn)
        liv = live_sum.get(fn) or {}
        loc = local_sums.get(fn) or {}
        if "error" in liv:
            fails.append(f"A 静态页 {fn} 红：在役面不可读（{liv['error']}）")
            legs.append((f"A/{fn}", "红", "在役面不可读"))
            continue
        if pub["sha256"] != liv.get("sha256"):
            fails.append(f"A 静态页 {fn} 红：公网面与在役面字节不等"
                         f"（公网 {pub['sha256'][:12]}… vs 在役 {str(liv.get('sha256'))[:12]}…）")
        elif pub["sha256"] != loc.get("sha256"):
            fails.append(f"A 静态页 {fn} 红：公网面与本地正本字节不等"
                         f"（公网 {pub['sha256'][:12]}… vs 本地 {str(loc.get('sha256'))[:12]}…）"
                         f"——RT-E112 原缺陷形态（本地整改未达公网暴露面）")
        else:
            legs.append((f"A/{fn}", "绿", f"三方同字节 sha256={pub['sha256'][:12]}…"))
            continue
        legs.append((f"A/{fn}", "红", "字节不等"))

    # ---- B 动态件逐键对账 ----
    now_s = now_ms / 1000.0
    for fn in DYNAMIC_FILES:
        raw = public_raws.get(fn)
        if raw is None:
            fails.append(f"B {fn} 红：公网面取件失败（不可证）")
            legs.append((f"B/{fn}", "红", "公网面取件失败"))
            continue
        try:
            pub = public_side(raw, fn)
        except Exception as e:
            fails.append(f"B {fn} 红：公网面 JSON 不可解析（{e}）")
            legs.append((f"B/{fn}", "红", "公网面 JSON 不可解析"))
            continue
        liv = live_sum.get(fn) or {}
        loc = local_sums.get(fn) or {}
        if "error" in liv:
            fails.append(f"B {fn} 红：在役面不可读（{liv['error']}）")
            legs.append((f"B/{fn}", "红", "在役面不可读"))
            continue
        leg_ok = True
        # B1 键集三方相等
        if pub["keys"] != liv.get("keys"):
            fails.append(f"B1 {fn} 红：公网面与在役面顶层键集不等"
                         f"（公网 {pub['keys']} vs 在役 {liv.get('keys')}）")
            leg_ok = False
        elif pub["keys"] != loc.get("keys"):
            fails.append(f"B1 {fn} 红：公网面与本地正本顶层键集不等"
                         f"（公网 {pub['keys']} vs 本地 {loc.get('keys')}）")
            leg_ok = False
        # B2 新鲜度
        for label, rec in (("公网", pub), ("在役", liv)):
            ts = rec.get("ts")
            if not isinstance(ts, (int, float)):
                fails.append(f"B2 {fn} 红：{label}面无 ts 字段（不可证新鲜度）")
                leg_ok = False
            elif now_s - ts / 1000.0 > MAX_AGE_S:
                fails.append(f"B2 {fn} 红：{label}面陈旧（ts 距 now "
                             f"{now_s - ts / 1000.0:.0f}s > {MAX_AGE_S}s）")
                leg_ok = False
        # B3 暴露滞后
        pts, lts = pub.get("ts"), liv.get("ts")
        if isinstance(pts, (int, float)) and isinstance(lts, (int, float)):
            lag = (lts - pts) / 1000.0
            if lag > LAG_TOL_S:
                fails.append(f"B3 {fn} 红：公网面落后在役面 {lag:.0f}s"
                             f"（> {LAG_TOL_S}s）——暴露面漂移")
                leg_ok = False
        # B4 订单键集
        if fn == "orders.json":
            pub_ids = set(pub.get("order_ids") or [])
            liv_ids = set(liv.get("order_ids") or [])
            extra = sorted(pub_ids - liv_ids)
            if extra:
                fails.append(f"B4 {fn} 红：公网面含在役面没有的订单键 {extra[:5]}"
                             f"（共 {len(extra)} 个）")
                leg_ok = False
        legs.append((f"B/{fn}", "绿" if leg_ok else "红",
                     f"键集{len(pub['keys'])}键 ts={pub.get('ts')} 滞后"
                     f"{(lts - pts) / 1000.0:.0f}s" if isinstance(pts, (int, float))
                     and isinstance(lts, (int, float)) else "键集对账"))
    return fails, legs


# ---------------------------------------------------------------- 生产面跑批
def run_production():
    fails = []
    legs = []
    public_raws = {}
    for fn in ALL_FILES:
        try:
            public_raws[fn] = fetch_public(fn)
        except Exception as e:
            public_raws[fn] = None
            fails.append(f"C 公网面不可达：{fn} 取件失败（{type(e).__name__}: {e}）")
    try:
        live_sum = fetch_live_summary()
    except Exception as e:
        live_sum = {}
        fails.append(f"C 在役面不可达：ssh 摘要失败（{type(e).__name__}: {e}）")
    local_sums = {}
    for fn in ALL_FILES:
        try:
            local_sums[fn] = local_side(fn)
        except Exception as e:
            local_sums[fn] = {}
            fails.append(f"C 本地正本不可读：{fn}（{e}）")
    if public_raws and live_sum and local_sums:
        f2, l2 = reconcile(public_raws, live_sum, local_sums, time.time() * 1000)
        fails.extend(f2)
        legs.extend(l2)
    return fails, legs


# ---------------------------------------------------------------- 判别力自证
def _mk_json(ts, keys=None, order_ids=None):
    doc = {"ts": ts}
    for k in (keys or []):
        doc[k] = 1
    if order_ids is not None:
        doc["orders"] = [{"order_id": o} for o in order_ids]
    return json.dumps(doc, ensure_ascii=False).encode()


def selftest():
    print("=== RT-E112 看板暴露面门 · 判别力自证 ===")
    fails = []
    now = int(time.time() * 1000)
    fresh = now - 60_000
    ids = ["A0001", "A0002"]

    pub_html = b"<html>board</html>"
    live_html = {"index.html": {"sha256": sha256_bytes(pub_html), "size": len(pub_html)}}
    loc_html = {"index.html": {"sha256": sha256_bytes(pub_html), "size": len(pub_html)}}

    ord_keys = ["orders", "source", "ts"]      # 三方一致的顶层键集基准

    def base_live():
        return {
            "index.html": dict(live_html["index.html"]),
            "orders.json": {"sha256": "x", "size": 1, "keys": list(ord_keys),
                            "ts": fresh, "order_ids": ids},
            "stages.json": {"sha256": "x", "size": 1, "keys": ["ts"], "ts": fresh},
            "otel-sidecar.json": {"sha256": "x", "size": 1, "keys": ["ts"], "ts": fresh},
        }

    def base_local():
        return {
            "index.html": dict(loc_html["index.html"]),
            "orders.json": {"sha256": "x", "size": 1, "keys": list(ord_keys),
                            "ts": fresh, "order_ids": ids},
            "stages.json": {"sha256": "x", "size": 1, "keys": ["ts"], "ts": fresh},
            "otel-sidecar.json": {"sha256": "x", "size": 1, "keys": ["ts"], "ts": fresh},
        }

    def base_public():
        return {
            "index.html": pub_html,
            "orders.json": _mk_json(fresh, ["source"], ids),
            "stages.json": _mk_json(fresh, []),
            "otel-sidecar.json": _mk_json(fresh, []),
        }

    cases = []

    # G 绿路
    f, _ = reconcile(base_public(), base_live(), base_local(), now)
    cases.append(("G 绿路（三方一致且新鲜）", not f, f))

    # R1 公网静态页字节被篡改
    p = base_public()
    p["index.html"] = b"<html>board-tampered</html>"
    f, _ = reconcile(p, base_live(), base_local(), now)
    cases.append(("R1 公网静态页字节篡改 → A 腿必红", bool(f), f))

    # R2 公网 ts 陈旧
    p = base_public()
    p["orders.json"] = _mk_json(now - 3_600_000, ["orders"], ids)
    f, _ = reconcile(p, base_live(), base_local(), now)
    cases.append(("R2 公网 ts 陈旧 1h → B2 腿必红", bool(f), f))

    # R3 公网顶层缺键
    p = base_public()
    p["orders.json"] = _mk_json(fresh, [], ids)
    f, _ = reconcile(p, base_live(), base_local(), now)
    cases.append(("R3 公网顶层缺键 → B1 腿必红", bool(f), f))

    # R4 公网含在役没有的订单键
    p = base_public()
    p["orders.json"] = _mk_json(fresh, ["orders"], ids + ["GHOST-9999"])
    f, _ = reconcile(p, base_live(), base_local(), now)
    cases.append(("R4 公网含在役没有的订单键 → B4 腿必红", bool(f), f))

    # R5 公网 ts 落后在役 1h
    p = base_public()
    p["orders.json"] = _mk_json(fresh - 3_600_000, ["orders"], ids)
    f, _ = reconcile(p, base_live(), base_local(), now)
    cases.append(("R5 公网 ts 落后在役 1h → B3 腿必红", bool(f), f))

    # R6 在役面不可达（缺件 → 不可证）
    liv = base_live()
    liv["orders.json"] = {"error": "No such file"}
    f, _ = reconcile(base_public(), liv, base_local(), now)
    cases.append(("R6 在役面不可达 → fail-closed 必红", bool(f), f))

    npass = 0
    for name, ok, fs in cases:
        if ok:
            npass += 1
            print(f"  [OK]   {name}")
        else:
            fails.append(f"判别力不成立：{name} 未被按预期判定")
            print(f"  [FAIL] {name}（读数：{fs[:2]}）")
    if fails:
        for f_ in fails:
            print(f"[RED] {f_}")
        print(f"小计：PASS={npass} FAIL={len(cases) - npass}")
        return 1
    print(f"小计：PASS={npass} FAIL=0（绿路 1 + 红路 6）")
    return 0


def main():
    if "--selftest" in sys.argv[1:]:
        return selftest()
    fails, legs = run_production()
    for name, st, detail in legs:
        print(f"  [{'PASS' if st == '绿' else 'FAIL'}] {name} —— {detail}")
    if fails:
        print(f"[FAIL] RT-E112 看板暴露面门红（{len(fails)} 条）：")
        for f in fails:
            print(f"  · {f}")
        print("小计：PASS=0 FAIL=1")
        return 1
    print("[PASS] RT-E112 看板暴露面门绿：公网面 ≡ 在役面 ≡ 本地正本（静态页同字节；"
          "动态件键集相等、ts 新鲜、暴露滞后在容差内、订单键集无伪件）")
    print("小计：PASS=1 FAIL=0")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001 —— 门件自身异常 = 不可证 = 红
        print(f"[RED rc=2] 门件执行异常：{e!r}", file=sys.stderr)
        sys.exit(2)
