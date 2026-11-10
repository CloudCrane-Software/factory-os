#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""凭据发放最小授权断言门（清册簿记面对账，零凭据读取）——D-166/ESC-38。

设计来源（卡面正本）：factory-os issue #280（wave-14 迟建 · w14-d166-least-privilege-gate）；
  债本体=账本/阶段欠账台账.md D-166 行（2026-11-08 锚补全三要件）；新门设计=ESC-38 条
  （凭据发放最小授权断言）。形态对齐仓内 recon-gate 族（credential-ledger-recon-gate /
  bao-token-ttl-recon-gate 等：判据单一源自含、--selftest 造夹具自证会咬人、坏形
  fail-closed 不猜绿、红=1/执行错=2 形制——同 D-162 注记，不回改族内 0/2/3 红旧约）。

债本体：凭据能力面与消费面无对账——现势实例=meters 腿取数持全权 CNB 令牌服务只读
  额度/用量 API，token 权限集与消费 API 面无逐条断言，能力面大于需要面无红
  （Q5 沙箱越权教训在凭据权限维度的镜像）。降权属运营者窗（族 D/W5 repo-only/read
  向）；本门只落断言门本体——门在场后降权前如实红，降权后转绿。
  （卡面纪律：令牌明文/指纹全文一律不入本件与输出，只记件名与位置。）

【判据】（卡面＋锚行明文；清册 JSON 逐条对账，册自带 API 目录做语义桥）
  清册（--roster 传入，schema=af.least-privilege-roster.v1）两条腿：
  · 在役腿（entries 逐条）：每条须含「消费 API 白名单」列（api_allowlist）。
    以册自带 api_catalog（API 名→该 API 最小所需权限集）对白名单逐 API 求并，
    得「证成权限面」；条目 privileges（现势实读权限集·簿记面）⊄ 证成面 ⇒ 红
    「权限集⊄白名单证成面」点名（附 ⊄ 见证=超出权限名目）。
    白名单列缺席 ⇒ 红「白名单列缺席（清册未迁移）」点名——断言不了即红，不猜绿；
    空白名单=无消费即无证成：非空权限集 ⇒ 红、空权限集 ⇒ 绿。
  · 发放腿（issuances 逐条）：新发 token 实发 policies 集 ≢ 申请卡面 scope 集
    （集语义：多发/漏发任一 ⇒ 红「发放腿 scope 失配」点名，附多发/漏发名目）。
  · 白名单内 API 不在 api_catalog ⇒ 不可证（面错注记）；零红时有面错 ⇒ 执行错。
  · 不可证不猜绿：清册不可读/坏形 ⇒ 执行错（exit 2）；有实证红 ⇒ 红优先（exit 1）。

【安全纪律】（内置，卡面钉死）
  簿记面断言，零凭据读取——本门只吃清册 JSON（件名/位置/权限名/API 名面），不触
  凭据本体、不触盘面、零网络。清册自由文本字段（reason/approved_by/notes）一律
  不回显；可选 sha8 指纹字段（8 位 hex，D-162 同形）仅原样点名不参与判定。
  --selftest 内置泄密负例：合成哨兵串注入自由文本字段，断言门全输出零命中。
  夹具权限/API 名目全用 fx.* 合成形（ESC-43 出仓词形避让：禁真实前缀族字面）。

【出口】0=绿（全断言通过）；1=红（⊄/失配/列缺席逐条点名）；2=执行错（清册不可读/
  坏形/用法错——fail-closed 不猜绿）。卡面明文钉「权限⊆白名单→rc=0、⊄→rc=1、
  发放 scope 失配→rc=1」。

【清册形制】（夹具即样例；issuances 可缺席=无发放记录可证）
  {"schema": "af.least-privilege-roster.v1", "updated": "2026-11-10",
   "api_catalog": {"fx.api.quota-read": ["fx.perm.repo-read"],
                    "fx.api.usage-read": ["fx.perm.repo-read"]},
   "entries": [{"name": "...", "kind": "scoped-token", "path": "位置（可选）",
                     "sha8": "ab12cd34"|null,
                     "privileges": ["fx.perm.repo-read"],
                     "api_allowlist": ["fx.api.quota-read"],
                     "reason": "...（禁回显）", "approved_by": "...（禁回显）"}],
   "issuances": [{"ref": "申请卡标识", "request_scope": ["fx.perm.repo-read"],
                   "issued_policies": ["fx.perm.repo-read"], "reason": "...（禁回显）"}]}

用法：
  python3 -I tools/least-privilege-recon-gate.py --selftest
  python3 -I tools/least-privilege-recon-gate.py --fixture <名>
      （内置夹具：subset-green/两腿全绿 rc=0 · over-privilege/权限超面 rc=1 ·
        issue-scope-mismatch/发放失配 rc=1；合成数据零真凭据）
  python3 -I tools/least-privilege-recon-gate.py --check --roster <清册.json>
"""
import datetime
import io
import json
import os
import re
import sys
import tempfile

SCHEMA = "af.least-privilege-roster.v1"
REPORT_SCHEMA = "af.least-privilege-recon.v1"
SHA8_RE = re.compile(r"^[0-9a-f]{8}$")
ENTRY_KEYS = ("name", "kind", "privileges")
ISSU_KEYS = ("ref", "request_scope", "issued_policies")
GREEN, RED, ERROR = 0, 1, 2

# 内置夹具（合成数据，零真凭据；权限/API 名目全 fx.* 合成形）：名 → 期望出口
FIXTURES = {"subset-green": GREEN, "over-privilege": RED, "issue-scope-mismatch": RED}
FIXTURE_ALIAS = {"两腿全绿": "subset-green", "权限超面": "over-privilege", "发放失配": "issue-scope-mismatch"}

# 泄密哨兵（合成）：注入自由文本字段，断言全输出零命中
SENTINEL_TEXT = "SENTINEL-FREE-TEXT-DO-NOT-ECHO"


def err(msg):
    sys.stderr.write("[least-privilege-recon-gate] %s\n" % msg)


class GateError(Exception):
    """清册坏形/用法错——exit 2，不猜绿。"""


# ---- 清册装载与形制机检 --------------------------------------------------------

def _check_str_list(value, label):
    if not isinstance(value, list):
        raise GateError("%s 须列表" % label)
    for item in value:
        if not isinstance(item, str) or not item:
            raise GateError("%s 元素须非空字符串：%r" % (label, item))


def load_roster(path):
    try:
        with open(path, "rb") as fh:   # 清册=簿记面（件名/位置/权限名），非凭据本体
            raw = fh.read()
    except OSError as exc:
        raise GateError("清册不可读：%s（%s）" % (path, exc))
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise GateError("清册不可解码：%s" % exc)
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise GateError("清册 schema 非 %s" % SCHEMA)
    try:
        datetime.date.fromisoformat(data.get("updated"))
    except (TypeError, ValueError):
        raise GateError("清册 updated 须 ISO 日期")

    catalog = data.get("api_catalog")
    if not isinstance(catalog, dict) or not catalog:
        raise GateError("清册 api_catalog 缺席或非对象（语义桥不可少——无目录即无证成面）")
    for api_name, need in catalog.items():
        if not isinstance(api_name, str) or not api_name:
            raise GateError("api_catalog 键须非空字符串：%r" % (api_name,))
        _check_str_list(need, "api_catalog[%s] 最小所需权限集" % api_name)

    entries = data.get("entries")
    if not isinstance(entries, list):
        raise GateError("清册 entries 缺失或非列表")
    issues = data.get("issuances", [])
    if not isinstance(issues, list):
        raise GateError("清册 issuances 非列表")
    if not entries and not issues:
        raise GateError("空册无可证面（entries 与 issuances 均空）——不猜绿")

    seen_cred, seen_ref = set(), set()
    for ent in entries:
        if not isinstance(ent, dict):
            raise GateError("清册条目非对象：%r" % (ent,))
        for key in ENTRY_KEYS:
            if key not in ent:
                raise GateError("清册条目缺字段 %s（%s）" % (key, ent.get("name") or ent.get("path")))
        name = ent["name"]
        if not isinstance(name, str) or not name:
            raise GateError("清册条目 name 非法：%r" % (name,))
        if not isinstance(ent["kind"], str) or not ent["kind"]:
            raise GateError("清册条目 kind 非法：%s" % name)
        if "api_allowlist" in ent and ent["api_allowlist"] is not None:
            _check_str_list(ent["api_allowlist"], "api_allowlist（%s）" % name)
        _check_str_list(ent["privileges"], "privileges（%s）" % name)
        path_pos = ent.get("path")
        if path_pos is not None and (not isinstance(path_pos, str) or not path_pos):
            raise GateError("清册条目 path 须非空字符串或缺席：%s" % name)
        sha8 = ent.get("sha8")
        if sha8 is not None and (not isinstance(sha8, str) or not SHA8_RE.match(sha8)):
            raise GateError("清册条目 sha8 须 8 位小写 hex 或 null：%s" % name)
        if name in seen_cred:
            raise GateError("清册条目 name 重复（册形损坏）：%s" % name)
        seen_cred.add(name)

    for rec in issues:
        if not isinstance(rec, dict):
            raise GateError("发放记录非对象：%r" % (rec,))
        for key in ISSU_KEYS:
            if key not in rec:
                raise GateError("发放记录缺字段 %s（%s）" % (key, rec.get("ref")))
        ref = rec["ref"]
        if not isinstance(ref, str) or not ref:
            raise GateError("发放记录 ref 非法：%r" % (ref,))
        _check_str_list(rec["request_scope"], "request_scope（%s）" % ref)
        _check_str_list(rec["issued_policies"], "issued_policies（%s）" % ref)
        if ref in seen_ref:
            raise GateError("发放记录 ref 重复（册形损坏）：%s" % ref)
        seen_ref.add(ref)
    return data


# ---- 判定核（纯簿记面对账，零凭据读取；--selftest 与真跑共用） -------------------

def _fmt_set(names):
    return "∅" if not names else "{%s}" % "、".join(sorted(names))


def judge(roster):
    """roster=已过 load_roster 的好册 → (verdict, report)。"""
    catalog = roster["api_catalog"]
    red, matched_c, matched_i, face_errors = [], [], [], []

    for ent in roster["entries"]:
        name, kind = ent["name"], ent["kind"]
        pos = ent.get("path")
        allow = ent.get("api_allowlist", None)
        priv_set = set(ent["privileges"])
        if allow is None:
            red.append({"leg": "在役腿", "why": "白名单列缺席（清册未迁移）",
                        "name": name, "kind": kind, "path": pos, "sha8": ent.get("sha8"),
                        "privileges": sorted(priv_set), "justified": None, "witness": sorted(priv_set)})
            continue
        justified, unknown_api = set(), []
        for api_name in allow:
            if api_name not in catalog:
                unknown_api.append(api_name)
                continue
            justified |= set(catalog[api_name])
        if unknown_api:
            face_errors.append("白名单 API 不在目录（不可证）：%s → %s" % (
                name, "、".join(sorted(unknown_api))))
        witness = priv_set - justified
        if witness:
            red.append({"leg": "在役腿", "why": "权限集⊄白名单证成面",
                        "name": name, "kind": kind, "path": pos, "sha8": ent.get("sha8"),
                        "privileges": sorted(priv_set), "justified": sorted(justified),
                        "witness": sorted(witness)})
        else:
            matched_c.append({"name": name, "privileges": sorted(priv_set),
                              "api_allowlist": sorted(set(allow))})

    for rec in roster.get("issuances") or []:
        ref = rec["ref"]
        req_set = set(rec["request_scope"])
        got_set = set(rec["issued_policies"])
        over = got_set - req_set
        under = req_set - got_set
        if over or under:
            red.append({"leg": "发放腿", "why": "scope 失配（新发 policies ≢ 申请卡面 scope）",
                        "ref": ref, "request_scope": sorted(req_set),
                        "issued_policies": sorted(got_set),
                        "over": sorted(over), "under": sorted(under)})
        else:
            matched_i.append({"ref": ref, "scope": sorted(req_set)})

    verdict = RED if red else (ERROR if face_errors else GREEN)
    report = {
        "schema": REPORT_SCHEMA,
        "verdict": {GREEN: "GREEN", RED: "RED", ERROR: "INSUFFICIENT"}[verdict],
        "counts": {
            "entries": len(roster["entries"]),
            "issuances": len(roster.get("issuances") or []),
            "red": len(red),
            "matched_entries": len(matched_c),
            "matched_issuances": len(matched_i),
            "api_catalog": len(catalog),
        },
        "red": red,
        "matched": {"entries": matched_c, "issuances": matched_i},
        "annotations": {"face_errors": face_errors},
    }
    return verdict, report


def render(report):
    c = report["counts"]
    out = ["== least-privilege-recon-gate · %s ==" % report["verdict"],
           "面：清册 %d 条｜发放记录 %d 条｜红 %d｜对上（在役 %d/发放 %d）｜API 目录 %d 项" % (
               c["entries"], c["issuances"], c["red"],
               c["matched_entries"], c["matched_issuances"], c["api_catalog"])]
    for r in report["red"]:
        if r["leg"] == "在役腿":
            out.append("  红｜%s｜%s｜%s｜位置 %s｜sha8 %s｜权限集 %s｜证成面 %s｜⊄ 见证 %s" % (
                r["leg"], r["why"], r["name"], r["path"] or "—", r["sha8"] or "—",
                _fmt_set(r["privileges"]),
                _fmt_set(r["justified"]) if r["justified"] is not None else "（列缺席·无以证成）",
                _fmt_set(r["witness"])))
        else:
            out.append("  红｜%s｜%s｜%s｜申请 %s｜实发 %s｜多发 %s｜漏发 %s" % (
                r["leg"], r["why"], r["ref"], _fmt_set(r["request_scope"]),
                _fmt_set(r["issued_policies"]), _fmt_set(r["over"]), _fmt_set(r["under"])))
    ann = report["annotations"]
    out.append("  注记：面错 %d%s" % (
        len(ann["face_errors"]),
        ("｜" + "；".join(ann["face_errors"])) if ann["face_errors"] else ""))
    out.append("  纪律：簿记面断言·零凭据读取·自由文本字段不回显（D-166 卡面钉死）")
    return "\n".join(out)


def run_check(roster_path):
    roster = load_roster(roster_path)
    verdict, report = judge(roster)
    print(render(report))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return verdict


# ---- 内置夹具（合成数据，零真凭据；权限/API 名目全 fx.* 合成形） -----------------

def _fx_catalog():
    return {
        "fx.api.quota-read": ["fx.perm.repo-read"],
        "fx.api.usage-read": ["fx.perm.repo-read"],
        "fx.api.build-write": ["fx.perm.repo-write"],
    }


def _fx_cred(name, privileges, allowlist, kind="fixture-scoped-token", path=None, sha8=None):
    ent = {"name": name, "kind": kind, "privileges": privileges,
           "reason": SENTINEL_TEXT, "approved_by": SENTINEL_TEXT}   # 自由文本：禁回显
    if allowlist is not None:
        ent["api_allowlist"] = allowlist
    if path is not None:
        ent["path"] = path
    if sha8 is not None:
        ent["sha8"] = sha8
    return ent


def build_fixture(name, td):
    """造合成清册；name ∈ FIXTURES。td 保留形参对齐族形（本门无盘面腿，册即全量）。"""
    del td
    entries, issues = [], []
    if name == "subset-green":
        entries = [
            _fx_cred("fx-git-read", ["fx.perm.repo-read"],
                     ["fx.api.quota-read", "fx.api.usage-read"], path="/fx/secrets/git-read.token",
                     sha8="ab12cd34"),
            _fx_cred("fx-zero-priv", [], []),   # 空权限×空白名单 ⇒ 绿
        ]
        issues = [{"ref": "fx-card-001", "request_scope": ["fx.perm.repo-read"],
                   "issued_policies": ["fx.perm.repo-read"], "reason": SENTINEL_TEXT}]
    elif name == "over-privilege":
        # 现势镜像（合成形）：全权令牌只服务只读 API ⇒ 权限集⊄证成面（D-166 债形态）
        entries = [
            _fx_cred("fx-meters-leg", ["fx.perm.all", "fx.perm.repo-write"],
                     ["fx.api.quota-read", "fx.api.usage-read"], path="/fx/secrets/meters.token"),
            _fx_cred("fx-git-read", ["fx.perm.repo-read"], ["fx.api.quota-read"]),
        ]
        issues = [{"ref": "fx-card-002", "request_scope": ["fx.perm.repo-read"],
                   "issued_policies": ["fx.perm.repo-read"], "reason": SENTINEL_TEXT}]
    elif name == "issue-scope-mismatch":
        entries = [_fx_cred("fx-git-read", ["fx.perm.repo-read"], ["fx.api.quota-read"])]
        issues = [
            {"ref": "fx-card-003", "request_scope": ["fx.perm.repo-read"],
             "issued_policies": ["fx.perm.repo-read", "fx.perm.repo-write"],   # 多发
             "reason": SENTINEL_TEXT},
            {"ref": "fx-card-004", "request_scope": ["fx.perm.repo-read", "fx.perm.repo-write"],
             "issued_policies": ["fx.perm.repo-read"],   # 漏发
             "reason": SENTINEL_TEXT},
        ]
    return {"schema": SCHEMA, "updated": "2026-11-10", "api_catalog": _fx_catalog(),
            "notes": [SENTINEL_TEXT], "entries": entries, "issuances": issues}


def canonical_fixture(name):
    if name in FIXTURES:
        return name
    for alias, canon in FIXTURE_ALIAS.items():
        if name == alias:
            return canon
    raise GateError("未知夹具名：%s（可用 subset-green/over-privilege/issue-scope-mismatch "
                    "或别名 两腿全绿/权限超面/发放失配）" % name)


def run_fixture(name):
    name = canonical_fixture(name)
    with tempfile.TemporaryDirectory(prefix="least-priv-fx-") as td:
        rp = os.path.join(td, "roster.json")
        with open(rp, "w", encoding="utf-8") as fh:
            json.dump(build_fixture(name, td), fh, ensure_ascii=False, indent=1)
        return run_check(rp)


# ---- 自证面（零网络零真凭据：三夹具全链真跑＋泄密哨兵＋断言咬人＋坏形 fail-closed） -

def run_selftest():
    cases = []

    # ① 三夹具全链真跑（装载→判定→渲染→出口）＋泄密哨兵断言（自由文本禁回显纪律）
    for name in ("subset-green", "over-privilege", "issue-scope-mismatch"):
        want = FIXTURES[name]
        with tempfile.TemporaryDirectory(prefix="least-priv-fx-") as td:
            rp = os.path.join(td, "roster.json")
            with open(rp, "w", encoding="utf-8") as fh:
                json.dump(build_fixture(name, td), fh, ensure_ascii=False, indent=1)
            buf = io.StringIO()
            saved = sys.stdout
            sys.stdout = buf
            try:
                got = run_check(rp)
            finally:
                sys.stdout = saved
        cases.append(("夹具·%s" % name, want, got))
        out = buf.getvalue()
        if SENTINEL_TEXT in out:
            return 1, "泄密哨兵命中（自由文本现于门输出）——不回显纪律破"
        rep = json.loads(out.strip().splitlines()[-1])
        if name == "over-privilege":
            if not (rep["red"] and rep["red"][0]["leg"] == "在役腿"
                    and rep["red"][0]["name"] == "fx-meters-leg"
                    and rep["red"][0]["why"] == "权限集⊄白名单证成面"
                    and set(rep["red"][0]["witness"]) == {"fx.perm.all", "fx.perm.repo-write"}):
                return 1, "over-privilege 红点名形制不符：%r" % (rep["red"],)
        elif name == "issue-scope-mismatch":
            refs = [r["ref"] for r in rep["red"]]
            if rep["verdict"] != "RED" or refs != ["fx-card-003", "fx-card-004"] \
                    or rep["red"][0]["over"] != ["fx.perm.repo-write"] \
                    or rep["red"][1]["under"] != ["fx.perm.repo-write"]:
                return 1, "issue-scope-mismatch 失配形制不符：%r" % (rep["red"],)
        elif name == "subset-green" and rep["counts"]["red"]:
            return 1, "subset-green 不应红：%r" % (rep["counts"],)

    # ② 断言咬人（judge 级逐形态）
    cat = _fx_catalog()

    # 白名单列缺席 ⇒ 红点名（断言不了即红，不猜绿——清册未迁移形态）
    led = {"schema": SCHEMA, "updated": "2026-11-10", "api_catalog": cat,
           "entries": [_fx_cred("fx-no-column", ["fx.perm.repo-read"], None)]}
    v, rep = judge(load_roster_dict(led))
    cases.append(("列缺席红", RED, v))
    if not (rep["red"] and rep["red"][0]["why"].startswith("白名单列缺席")
            and rep["red"][0]["name"] == "fx-no-column"):
        return 1, "列缺席红形制不符：%r" % (rep["red"],)

    # 空白名单：非空权限 ⇒ 红；空权限 ⇒ 绿
    led2 = {"schema": SCHEMA, "updated": "2026-11-10", "api_catalog": cat,
            "entries": [_fx_cred("fx-idle-but-armed", ["fx.perm.repo-read"], []),
                            _fx_cred("fx-idle", [], [])]}
    v2, rep2 = judge(load_roster_dict(led2))
    cases.append(("空白名单×非空权限红", RED, v2))
    if not (rep2["red"] and rep2["red"][0]["name"] == "fx-idle-but-armed"
            and rep2["red"][0]["witness"] == ["fx.perm.repo-read"]):
        return 1, "空白名单红形制不符：%r" % (rep2["red"],)
    cases.append(("空白名单×空权限绿", GREEN, judge(load_roster_dict(
        {"schema": SCHEMA, "updated": "2026-11-10", "api_catalog": cat,
         "entries": [_fx_cred("fx-idle", [], [])]}))[0]))

    # 权限恰等证成面 ⇒ 绿（⊄ 严格性：等集不红）
    cases.append(("恰等证成绿", GREEN, judge(load_roster_dict(
        {"schema": SCHEMA, "updated": "2026-11-10", "api_catalog": cat,
         "entries": [_fx_cred("fx-exact", ["fx.perm.repo-read", "fx.perm.repo-write"],
                                  ["fx.api.quota-read", "fx.api.build-write"])]}))[0]))

    # 发放腿集语义：乱序等集 ⇒ 绿；空集等集 ⇒ 绿
    cases.append(("发放乱序等集绿", GREEN, judge(load_roster_dict(
        {"schema": SCHEMA, "updated": "2026-11-10", "api_catalog": cat,
         "entries": [_fx_cred("fx-git-read", ["fx.perm.repo-read"], ["fx.api.quota-read"])],
         "issuances": [{"ref": "fx-card-005", "request_scope": ["a-fx.perm", "b-fx.perm"],
                        "issued_policies": ["b-fx.perm", "a-fx.perm"]}]}))[0]))

    # 白名单 API 不在目录：零红 ⇒ 执行错（不可证不猜绿）；有红 ⇒ 红优先
    led6 = {"schema": SCHEMA, "updated": "2026-11-10", "api_catalog": cat,
            "entries": [_fx_cred("fx-unknown-api", [], ["fx.api.nope"])]}
    v6, rep6 = judge(load_roster_dict(led6))
    cases.append(("未知API·零红执行错", ERROR, v6))
    if not rep6["annotations"]["face_errors"]:
        return 1, "未知API面错注记形制不符：%r" % (rep6["annotations"],)
    led7 = {"schema": SCHEMA, "updated": "2026-11-10", "api_catalog": cat,
            "entries": [_fx_cred("fx-unknown-api", ["fx.perm.all"], ["fx.api.nope"]),
                            _fx_cred("fx-ok", ["fx.perm.repo-read"], ["fx.api.quota-read"])]}
    v7, rep7 = judge(load_roster_dict(led7))
    cases.append(("未知API·红优先", RED, v7))
    if len(rep7["red"]) != 1 or rep7["red"][0]["name"] != "fx-unknown-api":
        return 1, "红优先形制不符：%r" % (rep7["red"],)

    # ③ 清册坏形 fail-closed（逐形态咬人）
    good_entry = {"name": "fx", "kind": "fixture-scoped-token",
                 "privileges": ["fx.perm.repo-read"], "api_allowlist": ["fx.api.quota-read"],
                 "reason": SENTINEL_TEXT}
    base = {"schema": SCHEMA, "updated": "2026-11-10", "api_catalog": cat,
            "entries": [good_entry]}
    bads = {
        "坏schema": {**base, "schema": "other.v1"},
        "坏updated": {**base, "updated": "soon"},
        "目录缺席": {k: v for k, v in base.items() if k != "api_catalog"},
        "目录值非列表": {**base, "api_catalog": {"fx.api.quota-read": "fx.perm.repo-read"}},
        "entries非列表": {**base, "entries": "x"},
        "issuances非列表": {**base, "issuances": "x"},
        "缺字段name": {**base, "entries": [
            {k: v for k, v in good_entry.items() if k != "name"}]},
        "privileges非列表": {**base, "entries": [dict(good_entry, privileges="x")]},
        "权限名空串": {**base, "entries": [dict(good_entry, privileges=[""])]},
        "allowlist元素非串": {**base, "entries": [dict(good_entry, api_allowlist=[7])]},
        "sha8非hex": {**base, "entries": [dict(good_entry, sha8="ZZZZZZZZ")]},
        "sha8超8位": {**base, "entries": [dict(good_entry, sha8="ab12cd3499")]},
        "name重复": {**base, "entries": [good_entry, dict(good_entry)]},
        "发放缺ref": {**base, "issuances": [
            {"request_scope": ["fx.perm.repo-read"], "issued_policies": ["fx.perm.repo-read"]}]},
        "发放scope非列表": {**base, "issuances": [
            {"ref": "fx-card-006", "request_scope": "x", "issued_policies": ["fx.perm.repo-read"]}]},
        "ref重复": {**base, "issuances": [
            {"ref": "fx-card-007", "request_scope": [], "issued_policies": []},
            {"ref": "fx-card-007", "request_scope": [], "issued_policies": []}]},
        "空册": {"schema": SCHEMA, "updated": "2026-11-10", "api_catalog": cat,
                 "entries": [], "issuances": []},
    }
    with tempfile.TemporaryDirectory(prefix="least-priv-fx-") as td:
        for label, fixture in bads.items():
            fp = os.path.join(td, "bad.json")
            with open(fp, "w", encoding="utf-8") as fh:
                json.dump(fixture, fh, ensure_ascii=False)
            try:
                load_roster(fp)
                return 1, "坏形夹具未咬（%s）" % label
            except GateError:
                cases.append(("坏形·%s" % label, ERROR, ERROR))
        fp = os.path.join(td, "good.json")
        with open(fp, "w", encoding="utf-8") as fh:
            json.dump(base, fh, ensure_ascii=False)
        load_roster(fp)
        cases.append(("好册装载", GREEN, GREEN))
        # 不可读路径 ⇒ 执行错
        try:
            load_roster(os.path.join(td, "nope.json"))
            return 1, "缺件未咬"
        except GateError:
            cases.append(("清册缺件", ERROR, ERROR))

    # ④ 夹具名解析（别名可用；未知名咬人）＋CLI 用法错
    if canonical_fixture("两腿全绿") != "subset-green" or canonical_fixture("权限超面") != "over-privilege" \
            or canonical_fixture("发放失配") != "issue-scope-mismatch":
        return 1, "夹具别名解析错"
    try:
        canonical_fixture("no-such-fixture")
        return 1, "未知夹具名未咬"
    except GateError:
        cases.append(("未知夹具名咬人", ERROR, ERROR))
    for argv, label in (([], "缺模式"), (["--nope"], "未知参数"),
                        (["--check"], "check缺roster"), (["--roster", "x"], "roster无check"),
                        (["--fixture", "a", "--check", "--roster", "b"], "fixture与check同用")):
        got = main(argv)   # 用法错经 main 内捕 → 返回 2（stderr 留痕），不抛出
        if got != ERROR:
            return 1, "用法错未咬（%s → rc=%s）" % (label, got)
        cases.append(("用法错·%s" % label, ERROR, ERROR))

    fails = [c for c in cases if c[1] != c[2]]
    for label, want, got in cases:
        print("  自证·%s: 期望=%s 实得=%s %s" % (label, want, got, "OK" if want == got else "FAIL"))
    if fails:
        return 1, "自证 %d 例不符：%r" % (len(fails), [(f[0], f[1], f[2]) for f in fails])
    print("自证 %d 例全过（三夹具全链＋泄密哨兵零命中＋断言咬人＋坏形 fail-closed＋出口 0/1/2）" % len(cases))
    return 0, "ok"


def load_roster_dict(data):
    """自证面辅助：dict 直载（坏形仍走 load_roster 全检——先落盘再读，形制同一）。"""
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     prefix="least-priv-fx-", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False)
        path = fh.name
    try:
        return load_roster(path)
    finally:
        os.unlink(path)


def main(argv):
    if "--selftest" in argv:
        rc, msg = run_selftest()
        if rc != 0:
            err(msg)
        return rc
    check, roster_path, fixture = False, None, None
    rest = list(argv)
    try:
        while rest:
            a = rest.pop(0)
            if a == "--check":
                check = True
            elif a == "--roster":
                if not rest:
                    raise GateError("--roster 须跟清册路径")
                roster_path = rest.pop(0)
            elif a == "--fixture":
                if not rest:
                    raise GateError("--fixture 须跟夹具名")
                fixture = rest.pop(0)
            else:
                raise GateError("未知参数：%s" % a)
        if fixture is not None:
            if check or roster_path is not None:
                raise GateError("--fixture 不与 --check/--roster 同用")
            return run_fixture(fixture)
        if check:
            if roster_path is None:
                raise GateError("--check 须同给 --roster <清册.json>")
            return run_check(roster_path)
        if roster_path is not None:
            raise GateError("--roster 须与 --check 同用")
        raise GateError("缺模式：--selftest / --fixture <名> / --check --roster <清册.json>")
    except GateError as exc:
        err(str(exc))
        return ERROR


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
