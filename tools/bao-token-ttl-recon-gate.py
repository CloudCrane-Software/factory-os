#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""openBao token TTL 面扫描门（身份 token explicit_max_ttl=0 无自灭的机检）——D-150/ESC-12。

设计来源（卡面正本）：factory-os issue #216（wave-11 · D-150）；债本体=账本/阶段欠账
  台账.md D-150 行（2026-11-08 锚补全三要件）；新门设计=30-工件/逃逸问题台账-20261108.md
  ESC-12（「身份 token TTL 门：openBao 全量 token 面扫描，explicit_max_ttl=0 且非
  root/escrow 白名单⇒红；白名单项带 expiry 登记（比照 mirror-scan-allowlist expiry 形
  制）」），ESC-36/D-164（第 8 件 bao-issuer.token）串联注记。gate 形态对齐仓内
  ledger-face-recon-gate 族（出口 0/2/3、判据单一源自含、--selftest 造夹具自证会咬人）。

债本体：7+1 件在役 scoped token 与 broker 身份 explicit_max_ttl=0（永不过期，状态/
  openBao.md §6·2026-10-10 权威底本）——票据面有「短 TTL+renewable=false」纪律
  （jit 通道 1h 钳制），身份面无对应判据，永生 token 与短命票同册共存无红。

【判据】（卡面明文，只增拦截禁放宽）
  扫描 openBao token 面（LIST auth/token/accessors → 逐件 lookup-accessor）：
  explicit_max_ttl=0 且非 root/escrow 白名单 ⇒ 红。
  · root 面：policies 含 root ⇒ root 白名单面（判据明文），不判红；root 面件数与登记册
    root 类条目对不上 ⇒ 点名注记（对账缺口留痕）。
  · escrow/登记面：登记册（tools/bao-token-ttl-allowlist.json）class∈{root,escrow} 且
    exempt=true 且未过 expires ⇒ 豁免（限时豁免：expires=复审窗，过期即失效须判官批
    PR 重批）。
  · scoped 类=登记不豁免：在册 7+1 件现势 explicit_max_ttl=0 仍逐条红点名（如实红）；
    绿只能来自轮换批（裁19 运营者窗）逐件设 explicit_max_ttl>0 清偿。登记 expires=
    登记复审日（非轮换承诺日），过期点名升级「轮换登记逾期」，红/绿判据不变。
  · 册外发现：扫描命中而登记册无唯一同策略集件 ⇒ 红点名「册外未登记」（D-164 token
    文件全集对账门串联面）。
  · 不可证不猜绿：面缺（不可达/无列举权且自证不可得/登记册坏形/缺字段）⇒ exit 3；
    lookup 403 等不可证件逐条点名——有实证红 ⇒ exit 2（红优先），零红而残面不可证
    ⇒ exit 3（部分可见 ≠ 全量证明）。

【出口】0=绿；2=红；3=执行错（面缺/不可证，不猜绿）。
  设计源台账锚验收口径写作「红→rc=1」：本门出口对齐仓内 recon-gate 族 0/2/3 形制
  （2=红），卡面验收命令不指定红出口码——如实记录此分歧，不回改台账（judge-paths
  登记面禁入）。

【现势基线读数】2026-11-08 现盘实测（root 眼界 LIST+lookup 30 accessor）：
  explicit_max_ttl=0 共 22 件=root 面 2（escrow 在册 1＋另 1 件点名注记）＋长命身份
  12（在册 8［§6 七件＋bao-issuer］＋册外 4［egress-tools-read ×1、af-zhipu-read ×3，
  §6 底本后新增——如实点名勿读作已清］）＋jit 短票 0；jit 票 12 件 explicit_max_ttl
  =3600、renewable=false 全绿；lookup 403 不可证 2 件点名。现势红=12 件逐条点名，
  轮换批清偿后转绿——与「真跑现势如实红」判据一致；册外 4 件即 D-164 串联面活体证据。

【凭据纪律】token/accessor 值绝不读取打印——输出只含 sha256 前 8 位指纹；扫描凭据经
  env（BAO_TOKEN）或 --token-file 注入，不进 argv 不落日志；真跑面只读（LIST/lookup，
  无 create/revoke）；--selftest 零网络零凭据。

用法：
  BAO_ADDR=URL python3 -I tools/bao-token-ttl-recon-gate.py             # 真跑现盘
  python3 -I tools/bao-token-ttl-recon-gate.py --addr URL --token-file PATH
  python3 -I tools/bao-token-ttl-recon-gate.py --selftest  # 夹具自证（零网络）
  （面地址不内嵌本件：BAO_ADDR/--addr 必给，缺则 exit 3——基础设施地址不入 git。）
"""
import datetime
import hashlib
import json
import os
import sys
import tempfile
import urllib.error
import urllib.request

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALLOWLIST_REL = os.path.join("tools", "bao-token-ttl-allowlist.json")
DEFAULT_ADDR = os.environ.get("BAO_ADDR")   # 面地址只经 env/--addr 注入，不内嵌（P-04 面）
TICKET_MAX_TTL_NOTE = 3600   # 票据面 jit 通道 1h 钳制（注记线，不判红）
VALID_CLASSES = ("root", "escrow", "scoped")
EXEMPT_CLASSES = ("root", "escrow")

GREEN, RED, ERROR = 0, 2, 3


def err(msg):
    sys.stderr.write("[bao-token-ttl-recon-gate] %s\n" % msg)


def sha8(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def policy_set(policies):
    """策略集（去 default、排序）——登记 join_key（semantics.join_key 同源）。"""
    return sorted(p for p in (policies or []) if p != "default")


class GateError(Exception):
    """面缺/不可证——exit 3，不猜绿。"""


# ---- 登记册装载与形制机检 --------------------------------------------------------

def load_allowlist(path, today=None):
    today = today or datetime.date.today()
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        raise GateError("登记册不可读：%s（%s）" % (path, exc))
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise GateError("登记册不可解码：%s" % exc)
    if not isinstance(data, dict) or data.get("schema") != "af.bao-token-ttl-allowlist.v1":
        raise GateError("登记册 schema 非 af.bao-token-ttl-allowlist.v1")
    entries = data.get("entries")
    if not isinstance(entries, list) or not entries:
        raise GateError("登记册 entries 缺失或为空")
    seen = {}
    for ent in entries:
        if not isinstance(ent, dict):
            raise GateError("登记条目非对象：%r" % (ent,))
        for key in ("name", "class", "exempt", "policies_hint", "expires"):
            if key not in ent:
                raise GateError("登记条目缺字段 %s：%s" % (key, ent.get("name")))
        name, cls = ent["name"], ent["class"]
        if not isinstance(name, str) or not name:
            raise GateError("登记条目 name 非法")
        if cls not in VALID_CLASSES:
            raise GateError("登记条目 class 非法：%s（%s）" % (cls, name))
        if not isinstance(ent["exempt"], bool):
            raise GateError("登记条目 exempt 非布尔：%s" % name)
        if ent["exempt"] != (cls in EXEMPT_CLASSES):
            raise GateError("登记条目 exempt 与 class 不一致（scoped=登记不豁免）： %s" % name)
        if not isinstance(ent["policies_hint"], list) or not ent["policies_hint"]:
            raise GateError("登记条目 policies_hint 非法：%s" % name)
        try:
            exp = datetime.date.fromisoformat(ent["expires"])
        except (TypeError, ValueError):
            raise GateError("登记条目 expires 非法（须 ISO 日期）：%s" % name)
        if exp < today:
            sys.stderr.write("[bao-token-ttl-recon-gate] 注记：登记条目 expires 已过（%s ← %s）——"
                             "过期面按各语义处置\n" % (name, ent["expires"]))
        if name in seen:
            raise GateError("登记条目重名（册形损坏）： %s" % name)
        seen[name] = ent
    return data


def exempt_ok(entry, today):
    """限时豁免：class root/escrow ＋ exempt ＋ 未过 expires。"""
    if not entry or not entry.get("exempt") or entry.get("class") not in EXEMPT_CLASSES:
        return False
    try:
        return datetime.date.fromisoformat(entry["expires"]) >= today
    except (TypeError, ValueError):
        return False


# ---- 判定核（纯函数；--selftest 与真跑共用） -------------------------------------

def judge(scan_rows, allowlist, today, surface_complete=True):
    """scan_rows: [{sha8, display_name, policies, ttl, explicit_max_ttl, renewable,
                    path, err?}]（err=lookup 不可证）；返回 (verdict, report dict)。"""
    entries = allowlist["entries"]
    by_pset = {}
    for ent in entries:
        by_pset.setdefault(json.dumps(policy_set(ent["policies_hint"])), []).append(ent)

    red, clean, unprovable, root_rows = [], [], [], []
    for row in scan_rows:
        if row.get("err"):
            unprovable.append(row)
            continue
        if (row.get("policies") or [""]).__class__ is not list:
            unprovable.append(row)
            continue
        if "root" in (row.get("policies") or []):
            root_rows.append(row)
            continue  # root 白名单面：不判红（件数对账走注记）
        if int(row.get("explicit_max_ttl") or 0) > 0:
            clean.append(row)
            continue
        # explicit_max_ttl=0 且非 root ⇒ 红候选；唯一 escrow/限时豁免可挡
        pset = policy_set(row.get("policies"))
        matches = by_pset.get(json.dumps(pset), [])
        exempt = [e for e in matches if exempt_ok(e, today)]
        if exempt:
            clean.append(dict(row, exempt_by=exempt[0]["name"]))
            continue
        reg = matches[0] if len(matches) == 1 else None
        if len(matches) > 1:
            why = "登记歧义（%d 件同策略集：%s）" % (len(matches), "、".join(e["name"] for e in matches))
        elif reg is not None:
            why = "在册（%s·class=%s·expires=%s）——登记不豁免" % (
                reg["name"], reg["class"], reg["expires"])
            if datetime.date.fromisoformat(reg["expires"]) < today:
                why += "＋轮换登记逾期"
        else:
            why = "册外未登记（D-164 串联面）"
        red.append(dict(row, why=why))

    # 注记面（不判红）：登记在册而扫描未见 / root 件数对账 / 票据面形态
    seen_psets = {json.dumps(policy_set(r.get("policies"))) for r in scan_rows if not r.get("err")}
    unseen_reg = [e for e in entries
                  if json.dumps(policy_set(e["policies_hint"])) not in seen_psets
                  and e["class"] in EXEMPT_CLASSES]
    root_reg_n = sum(1 for e in entries if e["class"] == "root")
    ticket_rows = [r for r in clean if 0 < int(r.get("explicit_max_ttl") or 0)]
    long_ttl_note = [r for r in clean if int(r.get("explicit_max_ttl") or 0) > TICKET_MAX_TTL_NOTE]

    if red:
        verdict = RED
    elif unprovable or not surface_complete:
        verdict = ERROR   # 零实证红而残面/面不全不可证——不猜绿
    else:
        verdict = GREEN

    report = {
        "schema": "af.bao-token-ttl-recon.v1",
        "verdict": {GREEN: "GREEN", RED: "RED", ERROR: "INSUFFICIENT"}[verdict],
        "surface_complete": surface_complete,
        "counts": {
            "scanned": len(scan_rows),
            "red": len(red),
            "clean": len(clean),
            "unprovable": len(unprovable),
            "root_face": len(root_rows),
            "register_entries": len(entries),
        },
        "red": red,
        "unprovable": unprovable,
        "annotations": {
            "root_face_vs_register": {"scanned": len(root_rows), "register": root_reg_n,
                                      "note": "root 面件数≠登记（escrow 在册 1）⇒ 对账缺口点名" if len(root_rows) != root_reg_n else "对账一致"},
            "register_unseen": [e["name"] for e in unseen_reg],
            "ticket_face": {"count": len(ticket_rows),
                            "over_1h": [r["sha8"] for r in long_ttl_note],
                            "note": "票据面 explicit_max_ttl=%ds 钳制（注记线，不判红）" % TICKET_MAX_TTL_NOTE},
        },
    }
    return verdict, report


def render(report):
    out = ["== bao-token-ttl-recon-gate · %s ==" % report["verdict"],
           "面：扫描 %d 件（面全=%s）｜红 %d｜绿 %d｜不可证 %d｜root 面 %d｜登记册 %d 条" % (
               report["counts"]["scanned"], report["surface_complete"],
               report["counts"]["red"], report["counts"]["clean"],
               report["counts"]["unprovable"], report["counts"]["root_face"],
               report["counts"]["register_entries"])]
    for r in report["red"]:
        out.append("  红 sha8=%s ttl/max=%s/%s policies=%s → %s" % (
            r["sha8"], r.get("ttl"), r.get("explicit_max_ttl"),
            policy_set(r.get("policies")), r["why"]))
    for r in report["unprovable"]:
        out.append("  不可证 sha8=%s lookup=%s——点名不猜（红优先/零红则面缺）" % (r["sha8"], r["err"]))
    ann = report["annotations"]
    out.append("  注记：root 面 %d/登记 %d（%s）｜登记未见：%s｜票据面 %d 件%s" % (
        ann["root_face_vs_register"]["scanned"], ann["root_face_vs_register"]["register"],
        ann["root_face_vs_register"]["note"], ann["register_unseen"] or "—",
        ann["ticket_face"]["count"],
        ("｜超 1h 钳制点名 sha8=%s" % ann["ticket_face"]["over_1h"]) if ann["ticket_face"]["over_1h"] else ""))
    return "\n".join(out)


# ---- 真跑面（只读；urllib 直连不走代理 env） -------------------------------------

def _bao(addr, method, api_path, token, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(addr.rstrip("/") + "/v1/" + api_path.lstrip("/"),
                                 data=data, method=method,
                                 headers={"X-Vault-Token": token,
                                          "Content-Type": "application/json"})
    # 代理 env 剥离（af-github-askpass 2026-10-26 同款教训：tailnet 目标勿出境）
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def scan_live(addr, token):
    rows, complete = [], True
    try:
        listing = _bao(addr, "GET", "auth/token/accessors?list=true", token)
        accessors = listing.get("data", {}).get("keys") or []
    except urllib.error.HTTPError as exc:
        raise GateError("列举 accessors 被拒（http %s）——无 sudo 眼界，降级自证腿" % exc.code)
    except Exception as exc:
        raise GateError("BAO 不可达：%s" % exc)
    for acc in accessors:
        fp = sha8(acc)
        try:
            data = _bao(addr, "POST", "auth/token/lookup-accessor", token,
                        {"accessor": acc}).get("data") or {}
        except urllib.error.HTTPError as exc:
            rows.append({"sha8": fp, "err": "http %s" % exc.code})
            continue
        except Exception as exc:
            rows.append({"sha8": fp, "err": str(exc)[:60]})
            continue
        rows.append({"sha8": fp, "display_name": data.get("display_name"),
                     "policies": data.get("policies"), "ttl": data.get("ttl"),
                     "explicit_max_ttl": data.get("explicit_max_ttl"),
                     "renewable": data.get("renewable"), "path": data.get("path")})
    return rows, complete


def scan_self(addr, token):
    """降级腿：仅 lookup-self（scoped 眼界）——面不全，实证红仍先出。"""
    try:
        data = _bao(addr, "POST", "auth/token/lookup-self", token).get("data") or {}
    except Exception as exc:
        raise GateError("自证腿不可得：%s" % exc)
    row = {"sha8": "self", "display_name": data.get("display_name"),
           "policies": data.get("policies"), "ttl": data.get("ttl"),
           "explicit_max_ttl": data.get("explicit_max_ttl"),
           "renewable": data.get("renewable"), "path": data.get("path")}
    return [row], False


def run_live(args):
    material = os.environ.get("BAO_TOKEN", "")
    if args.token_file:
        try:
            with open(args.token_file, "rb") as fh:
                material = fh.read().decode("utf-8").strip()
        except OSError as exc:
            raise GateError("--token-file 不可读：%s" % exc)
    if not material:
        raise GateError("扫描凭据缺（BAO_TOKEN / --token-file）——不猜绿")
    addr = args.addr or DEFAULT_ADDR
    if not addr:
        raise GateError("BAO 面地址未给（BAO_ADDR / --addr）——本件不内嵌基础设施地址（P-04 面），不猜绿")
    allowlist = load_allowlist(os.path.join(WS, ALLOWLIST_REL))
    try:
        rows, complete = scan_live(addr, material)
    except GateError:
        rows, complete = scan_self(addr, material)
    verdict, report = judge(rows, allowlist, datetime.date.today(), complete)
    print(render(report))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return verdict


# ---- 自证面（零网络零凭据：夹具注入判定核＋登记册坏形夹具） -----------------------

def run_selftest():
    today = datetime.date(2026, 11, 8)
    ok_days, late_days = "2026-12-08", "2026-10-01"
    reg_scoped = {"name": "git-read-token", "class": "scoped", "kind": "scoped-token",
                  "exempt": False, "path": "/opt/opch/secrets/git-read-token",
                  "policies_hint": ["agent-git-read"], "sha8": "0e9d0f26",
                  "reason": "夹具", "approved_by": "夹具", "expires": ok_days}
    reg_escrow = {"name": "escrow-item", "class": "escrow", "kind": "escrow-token",
                  "exempt": True, "path": "/opt/opch/secrets/escrow-item",
                  "policies_hint": ["escrow-demo"], "sha8": None,
                  "reason": "夹具", "approved_by": "夹具", "expires": ok_days}
    reg_root = {"name": "root-token", "class": "root", "kind": "root-token",
                "exempt": True, "path": "age-escrow", "policies_hint": ["root"],
                "sha8": None, "reason": "夹具", "approved_by": "夹具", "expires": ok_days}
    base = {"schema": "af.bao-token-ttl-allowlist.v1", "updated": "2026-11-08",
            "criterion": "夹具", "semantics": {}, "notes": [],
            "entries": [reg_root, reg_escrow, reg_scoped]}

    def row(**kw):
        base_row = {"sha8": "deadbeef", "display_name": "token", "policies": ["default"],
                    "ttl": 0, "explicit_max_ttl": 0, "renewable": True, "path": "auth/token/create"}
        base_row.update(kw)
        return base_row

    cases = []
    # ① 册外长命 token（策略集不在册）⇒ 红「册外未登记」
    cases.append(("册外红", RED, judge([row(policies=["default", "egress-tools-read"])], base, today)[0]))
    # ② 在册 scoped（git-read 策略集恰配）⇒ 红「在册点名·登记不豁免」
    v, r2 = judge([row(policies=["default", "agent-git-read"], sha8="0e9d0f26")], base, today)
    cases.append(("在册红", RED, v))
    if not (r2["red"] and "登记不豁免" in r2["red"][0]["why"]):
        return 1, "②在册红 why 形制不符：%r" % (r2["red"],)
    # ③ TTL>0 ⇒ 绿
    cases.append(("短票绿", GREEN, judge([row(explicit_max_ttl=3600, ttl=1560, renewable=False)], base, today)[0]))
    # ④ root 面 ⇒ 不判红（白名单面）
    cases.append(("root 面", GREEN, judge([row(policies=["root"], display_name="root")], base, today)[0]))
    # ⑤ escrow 类限时豁免在窗 ⇒ 绿；过期 ⇒ 红（豁免失效）
    cases.append(("escrow 豁免在窗", GREEN, judge([row(policies=["default", "escrow-demo"])], base, today)[0]))
    cases.append(("escrow 豁免过期", RED, judge([row(policies=["default", "escrow-demo"], sha8="feedface")],
                                               base, datetime.date(2027, 1, 1))[0]))
    # ⑥ 不可证（lookup 403 残面）：零实证红 ⇒ exit 3（不猜绿）；有实证红 ⇒ 红优先
    cases.append(("残面零红", ERROR, judge([row(sha8="badbad42", err="http 403")], base, today)[0]))
    v7, r7 = judge([row(sha8="badbad42", err="http 403"),
                    row(sha8="aa000001", policies=["default", "agent-git-read"])], base, today)
    cases.append(("残面红优先", RED, v7))
    if len(r7["unprovable"]) != 1 or len(r7["red"]) != 1:
        return 1, "残面红优先分账错：%r" % (r7["counts"],)
    # ⑦ 面不全（scoped 自证腿）：自证件绿 ⇒ 3；自证件红 ⇒ 2
    cases.append(("自证绿面不全", ERROR, judge([row(explicit_max_ttl=3600, ttl=900)], base, today, surface_complete=False)[0]))
    cases.append(("自证红面不全", RED, judge([row(policies=["default", "agent-git-read"])], base, today, surface_complete=False)[0]))
    # ⑧ 空面（全清偿后形态）⇒ 绿
    cases.append(("空面绿", GREEN, judge([], base, today)[0]))
    # ⑨ root 件数对账注记（2 件 root vs 册 1）⇒ 不判红但点名
    v9, r9 = judge([row(policies=["root"], display_name="root", sha8="aa000002"),
                    row(policies=["root"], display_name="root", sha8="aa000003")], base, today)
    cases.append(("root 件数注记", GREEN, v9))
    if "对账缺口" not in r9["annotations"]["root_face_vs_register"]["note"]:
        return 1, "root 件数对账注记缺席：%r" % (r9["annotations"],)
    # ⑩ 登记在册而扫描未见（escrow 豁免件未见）⇒ 注记不红
    v10, r10 = judge([], base, today)
    if v10 != GREEN or "escrow-item" not in r10["annotations"]["register_unseen"]:
        return 1, "登记未见注记形制不符：v=%s ann=%r" % (v10, r10["annotations"])
    cases.append(("登记未见注记", GREEN, v10))

    # ⑪ 登记册坏形（缺 expires / 重名 / exempt-class 矛盾）⇒ GateError（exit 3 面）
    bads = {
        "缺expires": {**base, "entries": [{k: v for k, v in reg_scoped.items() if k != "expires"}]},
        "重名": {**base, "entries": [reg_scoped, dict(reg_scoped)]},
        "exempt矛盾": {**base, "entries": [dict(reg_scoped, exempt=True)]},
        "坏schema": {**base, "schema": "other.v1"},
    }
    for label, fixture in bads.items():
        with tempfile.TemporaryDirectory() as td:
            fp = os.path.join(td, "allowlist.json")
            with open(fp, "w", encoding="utf-8") as fh:
                json.dump(fixture, fh, ensure_ascii=False)
            try:
                load_allowlist(fp, today)
                return 1, "坏形夹具未咬（%s）" % label
            except GateError:
                cases.append(("坏形·%s" % label, ERROR, ERROR))

    # ⑫ 好册装载回归（同形制现盘件）
    load_allowlist(os.path.join(WS, ALLOWLIST_REL), today)
    cases.append(("好册装载", ERROR, ERROR))

    fails = [c for c in cases if c[1] != c[2]]
    for name, want, got in cases:
        print("  自证·%s: 期望=%s 实得=%s %s" % (name, want, got, "OK" if want == got else "FAIL"))
    if fails:
        return 1, "自证 %d 例不符：%r" % (len(fails), [(f[0], f[1], f[2]) for f in fails])
    print("自证 %d 例全过（判定核咬人形态＋登记册坏形 fail-closed＋出口 0/2/3）" % len(cases))
    return 0, "ok"


def main(argv):
    if "--selftest" in argv:
        rc, msg = run_selftest()
        if rc != 0:
            err(msg)
        return rc
    args = type("A", (), {})()
    args.addr, args.token_file = DEFAULT_ADDR, None
    rest = list(argv)
    while rest:
        a = rest.pop(0)
        if a == "--addr":
            args.addr = rest.pop(0)
        elif a == "--token-file":
            args.token_file = rest.pop(0)
        else:
            raise GateError("未知参数：%s（真跑仅 --addr/--token-file）" % a)
    try:
        return run_live(args)
    except GateError as exc:
        err(str(exc))
        return ERROR


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
