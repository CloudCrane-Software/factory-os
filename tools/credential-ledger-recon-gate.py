#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""凭据登记册↔盘面对账巡检门（指纹面巡检，零凭据读取）——D-162/ESC-34。

设计来源（卡面正本）：factory-os issue #235（wave-13 · w13-d162-credential-ledger-gate）；
  债本体=账本/阶段欠账台账.md D-162 行（2026-11-08 锚补全三要件）；新门设计=30-工件/
  逃逸问题台账-20261108.md ESC-34 条（登记面↔盘面对账巡检门）。形态对齐仓内
  recon-gate 族（ledger-face-recon-gate / bao-token-ttl-recon-gate 等：判据单一源自含、
  --selftest 造夹具自证会咬人、坏形 fail-closed 不猜绿）。

债本体：权威凭据登记册（轮换盘点总表族）与 gov 盘面无逐条对账腿——/etc/bao/root-token
  现役现存（26B，mtime 2026-11-06 11:42，sha8=15542b22，bao 垫片兜底序列与 SSH 引导
  签发都读它=活跃消费路）而登记面曾陈述「/etc/bao/ 为空目录」被证伪；既有凭据面扫描
  只扫仓内 blob（G-13 线），不扫盘面↔登记面一致性——簿记漂移禁静默。

【判据】（卡面＋锚行明文，登记册逐条对盘面实读）
  登记册 JSON（--ledger 传入，schema=af.credential-ledger.v1）逐条对账：
  · presence=present 条目：盘面路径缺席 ⇒ 红「登记在册而盘面缺席」；登记册自带
    size_bytes 与盘面 stat 尺寸不符 ⇒ 红「尺寸漂移（指纹面）」。
  · presence=absent 条目（登记面负陈述：该路径无凭据件）：盘面现存 ⇒ 红「登记面陈述
    缺席而盘面现存（簿记漂移·陈述被证伪）」——D-162 现势形态（真跑现势如实红，
    登记册补登后转绿）。
  · watch_dirs（登记册自带约定目录集）内盘面件而登记册无 ⇒ 警告计数（不红，注记
    新增面提示补登）；只扫一层，子目录跳过计数注记。
  · mtime 只作读数展示（续期天然改写），不判红；登记 expires 过复审日 ⇒ 注记不红。
  · 不可证不猜绿：登记册不可读/坏形、watch_dir 不可扫 ⇒ 执行错（exit 2）；有实证红
    ⇒ 红优先（exit 1）。

【安全纪律】（内置，卡面钉死）
  指纹面巡检，零凭据读取——盘面侧只取 os.path.exists＋os.stat（存在性/尺寸/mtime），
  绝不 open() 凭据文件本体（内容复算指纹即读取凭据=禁）；sha256 前 8 位指纹只取自
  登记册自带 sha8 字段用于点名。输出只含：路径＋指纹前 8 位＋尺寸/mtime 数字读数＋
  对账结论；登记册自带自由文本字段（reason/approved_by/notes）一律不回显。
  --selftest 内置泄密负例：合成密文哨兵串注入夹具，断言门全输出零命中。
  （登记册本体按「禁 secret 入 git，只记指纹+路径」形制只含簿记面，可读可载。）

【出口】0=绿（全对账通过）；1=红（簿记漂移逐条点名）；2=执行错（登记册不可读/坏形/
  盘面不可扫——fail-closed 不猜绿）。卡面明文钉「登记面≡盘面→rc=0、漂移→rc=1」，
  区别于族内 0/2/3 形制（红=2）：本门红=1、执行错=2，如实注记不回改族约。

【登记册形制】（夹具即样例；presence=absent 负陈述条目 sha8/size_bytes 须 null）
  {"schema": "af.credential-ledger.v1", "updated": "2026-11-08",
   "watch_dirs": ["/etc/bao", "/opt/opch/secrets"],
   "entries": [{"name": "...", "kind": "root-token", "path": "/etc/bao/root-token",
                "presence": "present", "sha8": "15542b22", "size_bytes": 26,
                "expires": "2026-12-08", "reason": "...", "approved_by": "..."}]}

用法：
  python3 -I tools/credential-ledger-recon-gate.py --selftest
  python3 -I tools/credential-ledger-recon-gate.py --fixture all-match
      （内置夹具：all-match/全对 rc=0 · missing-disk/缺盘面件 rc=1 ·
        unregistered-new/未登记新增 rc=0＋警告；合成数据零真凭据）
  python3 -I tools/credential-ledger-recon-gate.py --check --ledger <登记册.json>
"""
import datetime
import hashlib
import io
import json
import os
import re
import sys
import tempfile

SCHEMA = "af.credential-ledger.v1"
REPORT_SCHEMA = "af.credential-ledger-recon.v1"
SHA8_RE = re.compile(r"^[0-9a-f]{8}$")
ENTRY_KEYS = ("name", "kind", "path", "presence", "sha8", "size_bytes", "expires")
PRESENCE_VALUES = ("present", "absent")
GREEN, RED, ERROR = 0, 1, 2

# 内置夹具（合成数据，零真凭据）：名 → 期望出口；中文别名供人工复放
FIXTURES = {"all-match": GREEN, "missing-disk": RED, "unregistered-new": GREEN}
FIXTURE_ALIAS = {"全对": "all-match", "缺盘面件": "missing-disk", "未登记新增": "unregistered-new"}


def err(msg):
    sys.stderr.write("[credential-ledger-recon-gate] %s\n" % msg)


def sha8_of_text(text):
    """仅夹具合成面用（对合成数据造登记指纹）；真跑面禁——内容复算即读取凭据本体。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


class GateError(Exception):
    """登记册坏形/盘面不可扫/用法错——exit 2，不猜绿。"""


# ---- 登记册装载与形制机检 --------------------------------------------------------

def load_ledger(path):
    try:
        with open(path, "rb") as fh:   # 登记册=簿记面（只记指纹+路径），非凭据本体
            raw = fh.read()
    except OSError as exc:
        raise GateError("登记册不可读：%s（%s）" % (path, exc))
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise GateError("登记册不可解码：%s" % exc)
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise GateError("登记册 schema 非 %s" % SCHEMA)
    entries = data.get("entries")
    if not isinstance(entries, list):
        raise GateError("登记册 entries 缺失或非列表")
    watch = data.get("watch_dirs", [])
    if not isinstance(watch, list) or any(not isinstance(d, str) or not d for d in watch):
        raise GateError("登记册 watch_dirs 非法")
    for d in watch:
        if not os.path.isabs(d):
            raise GateError("watch_dir 须绝对路径：%s" % d)
    if not entries and not watch:
        raise GateError("空册无可对面（entries 与 watch_dirs 均空）——不猜绿")
    seen = set()
    for ent in entries:
        if not isinstance(ent, dict):
            raise GateError("登记条目非对象：%r" % (ent,))
        for key in ENTRY_KEYS:
            if key not in ent:
                raise GateError("登记条目缺字段 %s（%s）" % (key, ent.get("path") or ent.get("name")))
        name = ent["name"]
        if not isinstance(name, str) or not name:
            raise GateError("登记条目 name 非法")
        if not isinstance(ent["kind"], str) or not ent["kind"]:
            raise GateError("登记条目 kind 非法：%s" % name)
        if not isinstance(ent["path"], str) or not os.path.isabs(ent["path"]):
            raise GateError("登记条目 path 须非空绝对路径：%s" % name)
        if ent["presence"] not in PRESENCE_VALUES:
            raise GateError("登记条目 presence 非法（present/absent）：%s" % name)
        fp = ent["sha8"]
        if fp is not None and (not isinstance(fp, str) or not SHA8_RE.match(fp)):
            raise GateError("登记条目 sha8 须 8 位小写 hex 或 null：%s" % name)
        size = ent["size_bytes"]
        if size is not None and (not isinstance(size, int) or isinstance(size, bool) or size < 0):
            raise GateError("登记条目 size_bytes 须非负整数或 null：%s" % name)
        try:
            datetime.date.fromisoformat(ent["expires"])
        except (TypeError, ValueError):
            raise GateError("登记条目 expires 须 ISO 日期：%s" % name)
        if ent["path"] in seen:
            raise GateError("登记条目 path 重复（册形损坏）：%s" % ent["path"])
        seen.add(ent["path"])
    return data


# ---- 判定核（纯读盘面元数据，零内容读取；--selftest 与真跑共用） -------------------

def stat_face(path):
    """盘面实读一条：存在性＋尺寸＋mtime（stat 元数据面；绝不 open 文件内容）。"""
    if not os.path.exists(path):
        return None
    st = os.stat(path)
    return {"size": int(st.st_size),
            "mtime": datetime.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")}


def judge(ledger, today=None):
    """ledger=已过 load_ledger 的好册 → (verdict, report)。"""
    today = today or datetime.date.today()
    entries = ledger["entries"]
    watch_dirs = ledger.get("watch_dirs") or []
    registered = set(e["path"] for e in entries)

    red, matched, new_faces, face_errors = [], [], [], []
    expired_review, skipped_subdirs = [], 0

    for ent in entries:
        path = ent["path"]
        try:
            face = stat_face(path)
        except OSError as exc:
            face_errors.append("盘面 stat 不可证：%s（%s）" % (path, exc))
            continue
        try:
            if datetime.date.fromisoformat(ent["expires"]) < today:
                expired_review.append(path)
        except (TypeError, ValueError):
            pass   # 坏 expires 已在 load_ledger 拦截，好册必达
        if ent["presence"] == "present":
            if face is None:
                red.append({"path": path, "sha8": ent["sha8"],
                            "why": "登记在册而盘面缺席",
                            "size_reg": ent["size_bytes"], "size_disk": None, "mtime": None})
            elif ent["size_bytes"] is not None and face["size"] != ent["size_bytes"]:
                red.append({"path": path, "sha8": ent["sha8"],
                            "why": "尺寸漂移（指纹面）",
                            "size_reg": ent["size_bytes"], "size_disk": face["size"],
                            "mtime": face["mtime"]})
            else:
                matched.append({"path": path, "sha8": ent["sha8"], "size": face["size"],
                                "mtime": face["mtime"]})
        else:   # presence=absent：登记面负陈述
            if face is not None:
                red.append({"path": path, "sha8": ent["sha8"],
                            "why": "登记面陈述缺席而盘面现存（簿记漂移·陈述被证伪）",
                            "size_reg": ent["size_bytes"], "size_disk": face["size"],
                            "mtime": face["mtime"]})
            else:
                matched.append({"path": path, "sha8": None, "size": None, "mtime": None})

    for d in watch_dirs:
        try:
            it = os.scandir(d)
        except OSError as exc:
            face_errors.append("watch_dir 不可扫：%s（%s）" % (d, exc))
            continue
        with it:
            for dent in it:
                try:
                    if dent.is_dir():   # 一层扫描：子目录跳过计数注记（含指往目录的符号链接）
                        skipped_subdirs += 1
                        continue
                except OSError as exc:
                    face_errors.append("盘面枚举不可证：%s（%s）" % (dent.path, exc))
                    continue
                if dent.path not in registered:
                    new_faces.append(dent.path)

    verdict = RED if red else (ERROR if face_errors else GREEN)
    report = {
        "schema": REPORT_SCHEMA,
        "verdict": {GREEN: "GREEN", RED: "RED", ERROR: "INSUFFICIENT"}[verdict],
        "counts": {
            "entries": len(entries),
            "red": len(red),
            "matched": len(matched),
            "new_faces": len(new_faces),
            "watch_dirs": len(watch_dirs),
            "absent_claims": sum(1 for e in entries if e["presence"] == "absent"),
        },
        "red": red,
        "new_faces": new_faces,
        "annotations": {
            "expired_review": expired_review,
            "skipped_subdirs": skipped_subdirs,
            "face_errors": face_errors,
        },
    }
    return verdict, report


def render(report):
    c = report["counts"]
    out = ["== credential-ledger-recon-gate · %s ==" % report["verdict"],
           "面：登记册 %d 条｜红 %d｜对上 %d｜新增面警告 %d｜watch_dirs %d" % (
               c["entries"], c["red"], c["matched"], c["new_faces"], c["watch_dirs"])]
    for r in report["red"]:
        out.append("  红｜%s｜sha8=%s｜%s（登记 %sB / 盘面 %sB / mtime %s）" % (
            r["why"], r["sha8"] or "—", r["path"],
            r["size_reg"] if r["size_reg"] is not None else "—",
            r["size_disk"] if r["size_disk"] is not None else "—",
            r["mtime"] or "—"))
    for p in report["new_faces"]:
        out.append("  警告（不红）｜新增面未登记（提示补登）｜%s" % p)
    ann = report["annotations"]
    out.append("  注记：复审逾期 %d%s｜跳过子目录 %d｜面错 %d%s" % (
        len(ann["expired_review"]),
        ("（%s）" % "、".join(ann["expired_review"])) if ann["expired_review"] else "",
        ann["skipped_subdirs"], len(ann["face_errors"]),
        ("｜" + "；".join(ann["face_errors"])) if ann["face_errors"] else ""))
    return "\n".join(out)


def run_check(ledger_path):
    ledger = load_ledger(ledger_path)
    verdict, report = judge(ledger)
    print(render(report))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return verdict


# ---- 内置夹具（合成数据，零真凭据；sha8 由夹具建造器对合成串自造） -----------------

def _fx_token(dirpath, fname, payload):
    path = os.path.join(dirpath, fname)
    with open(path, "wb") as fh:
        fh.write(payload)
    return {"path": path, "sha8": sha8_of_text(payload.decode("ascii")), "size": len(payload)}


def _fx_entry(face, name, presence="present", expires="2026-12-08"):
    present = presence == "present"
    return {"name": name, "kind": "fixture-token", "path": face["path"],
            "presence": presence, "sha8": face["sha8"] if present else None,
            "size_bytes": face["size"] if present else None, "expires": expires,
            "reason": "夹具（禁回显字段）", "approved_by": "夹具"}


def build_fixture(name, td):
    """在临时目录 td 内造合成盘面＋登记册；name ∈ FIXTURES。"""
    if name not in FIXTURES:
        raise GateError("未知夹具：%s" % name)
    watch = os.path.join(td, "watch")
    os.makedirs(watch)
    fa = _fx_token(watch, "agent-git-read.token", b"SYNTH-FIXTURE-A")
    fb = _fx_token(watch, "bao-issuer.token", b"SYNTH-ROOT-TOKEN-26B-FACE!")   # 26B，呼应 root-token 现势尺寸
    never = {"path": os.path.join(watch, "never-issued.token"), "sha8": None, "size": None}
    entries = [
        _fx_entry(fa, "agent-git-read"),
        _fx_entry(fb, "bao-issuer"),
        _fx_entry(never, "never-issued", presence="absent"),   # 登记面负陈述（all-match 中成立）
    ]
    if name == "missing-disk":
        os.remove(fa["path"])   # 登记在册而盘面缺席 ⇒ 红
    elif name == "unregistered-new":
        _fx_token(watch, "rogue-new.token", b"SYNTH-ROGUE-NEW")   # 新增面 ⇒ 警告不红
    return {"schema": SCHEMA, "updated": "2026-11-08", "watch_dirs": [watch],
            "notes": ["合成夹具（零真凭据）"], "entries": entries}


def canonical_fixture(name):
    if name in FIXTURES:
        return name
    for alias, canon in FIXTURE_ALIAS.items():
        if name == alias:
            return canon
    raise GateError("未知夹具名：%s（可用 all-match/missing-disk/unregistered-new 或别名 全对/缺盘面件/未登记新增）" % name)


def run_fixture(name):
    name = canonical_fixture(name)
    with tempfile.TemporaryDirectory(prefix="cred-ledger-fx-") as td:
        lp = os.path.join(td, "ledger.json")
        with open(lp, "w", encoding="utf-8") as fh:
            json.dump(build_fixture(name, td), fh, ensure_ascii=False, indent=1)
        return run_check(lp)


# ---- 自证面（零网络零真凭据：三夹具全链真跑＋泄密哨兵＋漂移咬人＋坏形 fail-closed） --

def run_selftest():
    today = datetime.date(2026, 11, 8)
    cases = []

    # ① 三夹具全链真跑（装载→判定→渲染→出口）＋泄密哨兵断言（零凭据读取纪律）
    for name in ("all-match", "missing-disk", "unregistered-new"):
        want = FIXTURES[name]
        with tempfile.TemporaryDirectory(prefix="cred-ledger-fx-") as td:
            lp = os.path.join(td, "ledger.json")
            with open(lp, "w", encoding="utf-8") as fh:
                json.dump(build_fixture(name, td), fh, ensure_ascii=False, indent=1)
            buf = io.StringIO()
            saved = sys.stdout
            sys.stdout = buf
            try:
                got = run_check(lp)
            finally:
                sys.stdout = saved
        cases.append(("夹具·%s" % name, want, got))
        out = buf.getvalue()
        for sentinel in ("SYNTH-FIXTURE-A", "SYNTH-ROOT-TOKEN-26B-FACE", "SYNTH-ROGUE-NEW"):
            if sentinel in out:
                return 1, "泄密哨兵命中（%s 现于门输出）——零凭据读取纪律破" % sentinel
        rep = json.loads(out.strip().splitlines()[-1])
        if name == "missing-disk":
            if not (rep["red"] and "agent-git-read.token" in rep["red"][0]["path"]
                    and rep["red"][0]["why"] == "登记在册而盘面缺席"):
                return 1, "missing-disk 红点名形制不符：%r" % (rep["red"],)
        elif name == "unregistered-new":
            if rep["verdict"] != "GREEN" or rep["counts"]["new_faces"] != 1 \
                    or "rogue-new.token" not in rep["new_faces"][0]:
                return 1, "unregistered-new 警告形制不符：%r" % (rep["counts"],)
        elif name == "all-match" and rep["counts"]["red"]:
            return 1, "all-match 不应红：%r" % (rep["counts"],)

    # ② 漂移咬人（judge 级逐形态）
    with tempfile.TemporaryDirectory(prefix="cred-ledger-fx-") as td:
        watch = os.path.join(td, "watch")
        os.makedirs(watch)
        f_ok = _fx_token(watch, "ok.token", b"SYNTH-FIXTURE-A")
        f_nosize = _fx_token(watch, "nosize.token", b"SYNTH-FIXTURE-A-NULL")
        f_root = _fx_token(watch, "root-token", b"SYNTH-ROOT-TOKEN-26B-FACE!")

        # D-162 形态：登记面负陈述被盘面证伪 ⇒ 红点名
        led = {"schema": SCHEMA, "updated": "2026-11-08", "watch_dirs": [watch], "entries": [
            _fx_entry(f_ok, "ok"),
            _fx_entry({"path": f_root["path"], "sha8": None, "size": None},
                      "bao-empty-claim", presence="absent")]}
        v, rep = judge(led, today)
        cases.append(("absent 证伪红", RED, v))
        if not (rep["red"] and rep["red"][0]["path"] == f_root["path"]
                and "证伪" in rep["red"][0]["why"]):
            return 1, "absent 证伪红形制不符：%r" % (rep["red"],)

        # 尺寸漂移 ⇒ 红（指纹面）；sha8/size 未登记（null）条目对上 ⇒ 不拦
        led2 = {"schema": SCHEMA, "updated": "2026-11-08", "watch_dirs": [watch], "entries": [
            _fx_entry(dict(f_ok, size=99), "size-drift"),
            _fx_entry(dict(f_nosize, sha8=None, size=None), "null-fp")]}
        v2, rep2 = judge(led2, today)
        cases.append(("尺寸漂移红", RED, v2))
        if not (rep2["red"] and "尺寸漂移" in rep2["red"][0]["why"]
                and rep2["red"][0]["size_reg"] == 99 and rep2["red"][0]["size_disk"] == f_ok["size"]):
            return 1, "尺寸漂移红形制不符：%r" % (rep2["red"],)
        cases.append(("null 指纹不拦", GREEN, judge(
            {"schema": SCHEMA, "updated": "2026-11-08", "watch_dirs": [watch], "entries": [
                _fx_entry(dict(f_nosize, sha8=None, size=None), "null-fp")]}, today)[0]))

        # 复审逾期 ⇒ 注记不红
        v3, rep3 = judge({"schema": SCHEMA, "updated": "2026-11-08", "watch_dirs": [watch],
                          "entries": [_fx_entry(f_ok, "ok", expires="2026-10-01")]}, today)
        cases.append(("复审逾期注记", GREEN, v3))
        if f_ok["path"] not in rep3["annotations"]["expired_review"]:
            return 1, "复审逾期注记形制不符：%r" % (rep3["annotations"],)

        # watch_dir 缺：零红 ⇒ 面缺不猜绿；有红 ⇒ 红优先
        led4 = {"schema": SCHEMA, "updated": "2026-11-08",
                "watch_dirs": [os.path.join(td, "nope")], "entries": [_fx_entry(f_ok, "ok")]}
        cases.append(("watch_dir 缺·零红", ERROR, judge(led4, today)[0]))
        led5 = {"schema": SCHEMA, "updated": "2026-11-08",
                "watch_dirs": [os.path.join(td, "nope")],
                "entries": [_fx_entry({"path": os.path.join(td, "gone.token"),
                                       "sha8": "0e9d0f26", "size": 16}, "gone")]}
        cases.append(("watch_dir 缺·红优先", RED, judge(led5, today)[0]))

        # 子目录跳过注记（一层扫描）
        os.makedirs(os.path.join(watch, "subdir"))
        v6, rep6 = judge(led, today)
        cases.append(("子目录跳过注记", RED, v6))
        if rep6["annotations"]["skipped_subdirs"] != 1:
            return 1, "子目录跳过注记形制不符：%r" % (rep6["annotations"],)

    # ③ 登记册坏形 fail-closed（逐形态咬人）
    good = {"name": "fx", "kind": "fixture-token", "path": "/tmp/fx/a.token",
            "presence": "present", "sha8": "0e9d0f26", "size_bytes": 16, "expires": "2026-12-08"}
    base = {"schema": SCHEMA, "updated": "2026-11-08", "watch_dirs": ["/tmp/fx"],
            "entries": [good]}
    bads = {
        "坏schema": {**base, "schema": "other.v1"},
        "entries非列表": {**base, "entries": "x"},
        "缺字段": {**base, "entries": [{k: v for k, v in good.items() if k != "sha8"}]},
        "presence非法": {**base, "entries": [dict(good, presence="maybe")]},
        "sha8非hex": {**base, "entries": [dict(good, sha8="ZZZZZZZZ")]},
        "sha8超8位": {**base, "entries": [dict(good, sha8="0e9d0f2699")]},
        "size负": {**base, "entries": [dict(good, size_bytes=-1)]},
        "size布尔": {**base, "entries": [dict(good, size_bytes=True)]},
        "expires坏": {**base, "entries": [dict(good, expires="soon")]},
        "相对path": {**base, "entries": [dict(good, path="rel/a.token")]},
        "path重复": {**base, "entries": [good, dict(good)]},
        "相对watch_dir": {**base, "watch_dirs": ["rel"]},
        "空册": {"schema": SCHEMA, "updated": "2026-11-08", "entries": [], "watch_dirs": []},
    }
    with tempfile.TemporaryDirectory(prefix="cred-ledger-fx-") as td:
        for label, fixture in bads.items():
            fp = os.path.join(td, "bad.json")
            with open(fp, "w", encoding="utf-8") as fh:
                json.dump(fixture, fh, ensure_ascii=False)
            try:
                load_ledger(fp)
                return 1, "坏形夹具未咬（%s）" % label
            except GateError:
                cases.append(("坏形·%s" % label, ERROR, ERROR))
        fp = os.path.join(td, "good.json")
        with open(fp, "w", encoding="utf-8") as fh:
            json.dump(base, fh, ensure_ascii=False)
        load_ledger(fp)
        cases.append(("好册装载", GREEN, GREEN))

    # ④ 夹具名解析（别名可用；未知名咬人）
    if canonical_fixture("全对") != "all-match" or canonical_fixture("缺盘面件") != "missing-disk" \
            or canonical_fixture("未登记新增") != "unregistered-new":
        return 1, "夹具别名解析错"
    try:
        canonical_fixture("no-such-fixture")
        return 1, "未知夹具名未咬"
    except GateError:
        cases.append(("未知夹具名咬人", ERROR, ERROR))

    fails = [c for c in cases if c[1] != c[2]]
    for label, want, got in cases:
        print("  自证·%s: 期望=%s 实得=%s %s" % (label, want, got, "OK" if want == got else "FAIL"))
    if fails:
        return 1, "自证 %d 例不符：%r" % (len(fails), [(f[0], f[1], f[2]) for f in fails])
    print("自证 %d 例全过（三夹具全链＋泄密哨兵零命中＋漂移咬人＋坏形 fail-closed＋出口 0/1/2）" % len(cases))
    return 0, "ok"


def main(argv):
    if "--selftest" in argv:
        rc, msg = run_selftest()
        if rc != 0:
            err(msg)
        return rc
    check, ledger_path, fixture = False, None, None
    rest = list(argv)
    try:
        while rest:
            a = rest.pop(0)
            if a == "--check":
                check = True
            elif a == "--ledger":
                if not rest:
                    raise GateError("--ledger 须跟登记册路径")
                ledger_path = rest.pop(0)
            elif a == "--fixture":
                if not rest:
                    raise GateError("--fixture 须跟夹具名")
                fixture = rest.pop(0)
            else:
                raise GateError("未知参数：%s" % a)
        if fixture is not None:
            if check or ledger_path is not None:
                raise GateError("--fixture 不与 --check/--ledger 同用")
            return run_fixture(fixture)
        if check:
            if ledger_path is None:
                raise GateError("--check 须同给 --ledger <登记册.json>")
            return run_check(ledger_path)
        if ledger_path is not None:
            raise GateError("--ledger 须与 --check 同用")
        raise GateError("缺模式：--selftest / --fixture <名> / --check --ledger <登记册.json>")
    except GateError as exc:
        err(str(exc))
        return ERROR


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
