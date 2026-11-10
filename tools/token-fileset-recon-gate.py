#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""token 文件全集对账门（约定目录集枚举≡登记清册，差集逐条点名⇒红）——D-164/ESC-36。

设计来源（卡面正本）：factory-os issue #279（wave-14 · w14-d164-token-fileset-gate）；
  债本体=账本/阶段欠账台账.md D-164 行（2026-11-08 锚补全三要件）；新门设计=30-工件/
  逃逸问题台账-20261108.md ESC-36 条（「约定目录集内 token 件枚举≡清册（差集⇒红）」）；
  波次=波次清单/wave-14.json 卡 w14-d164-token-fileset-gate。形态对齐仓内 recon-gate 族
  （credential-ledger-recon-gate / bao-token-ttl-recon-gate：判据单一源自含、--selftest
  造夹具自证会咬人、坏形 fail-closed 不猜绿）。

债本体：凭据清册靠人肉盘点生成，无「盘面 token 件全集≡清册全集」对账——第 8 件长命
  token（/etc/opch-gov/bao-issuer.token，策略 opch-task-issuer，opch-gov-bao-renew.timer
  6h 续期）靠演练副产物而非门发现，清册「7 件 scoped token」计数须补 1（路径/策略名系
  台账与 TTL 册公开簿记面，非凭据字面；凭据值面本件零出现）。

【判据】（卡面＋锚行明文，只增拦截禁放宽）
  清册 JSON（--registry 传入，schema=af.token-fileset-registry.v1）自带约定目录集
  agreed_dirs（如 /opt/opch/secrets、/etc/opch-gov——形制同族内 watch_dirs：册自带、
  本件不内嵌基础设施路径）；目录集内文件全集递归枚举 ≡ 清册 entries 全集：
  · 盘面现存而清册无名（差集 盘面\清册）⇒ 红「清册外未登记」逐条点名——D-164 现势
    形态（第 8 件长命 token 即此面；如实红，清册补登后转绿）。
  · 清册在册而盘面缺席（差集 清册\盘面）⇒ 红「清册在册而盘面缺席」逐条点名；在册
    路径现势为目录（非凭据件）⇒ 红「盘面为目录非凭据件」。
  · 双向差集皆空 ⇒ 绿。子目录递归下钻（全集聚真）；符号链接目录不下钻但逐条点名
    注记（不静默）；符号链接件计为盘面件（密件目录内一面即一面）。
  · 条目 expires 过复审日 ⇒ 注记不红（D-150 册 expiry 语义同款，复审窗非轮换承诺）。
  · 不可证不猜绿：清册不可读/坏形/条目路径越约定目录集外（不可枚举=不可证）、目录
    不可扫 ⇒ 执行错（exit 2）；有实证红 ⇒ 红优先（exit 1）。

【串联边界】（卡面 env_precondition 明文）：与 ESC-12/D-150 TTL 门串联时本门只做全集
  入扫（枚举≡清册），不并吞其 explicit_max_ttl 判定——串联腿=全集入扫后逐件 TTL 由
  D-150 门自判（报告 annotations 留串联注记）。

【安全纪律】（内置，比照族内 credential-ledger-recon-gate）
  零凭据读取——盘面侧只 os.walk/os.path/os.stat 名录与元数据面（存在性/尺寸/mtime），
  绝不 open() 盘面凭据件本体（内容复算指纹即读取凭据=禁）；唯一被 open 者是清册 JSON
  本体（簿记面，只记路径+指纹，非凭据）。输出只含：路径＋清册自带 sha8 前 8 位指纹
  （点名展示）＋尺寸/mtime 数字读数＋对账结论；清册自由文本字段（reason/approved_by/
  notes）一律不回显。出仓词形纪律：本件零真实凭据字面——夹具全 SENTINEL 合成形，
  --selftest 内置泄密哨兵断言（哨兵串注入夹具，断言门全输出零命中）；持有凭据族词的
  变量名一律 _tag/_name 后缀断开。真跑面需现势清册与现势目录集（施工沙箱无该盘面，
  不伪造——如实留 rc 读数）。

【出口】0=绿（全集对账一致）；1=红（双向差集逐条点名）；2=执行错（清册坏形/不可扫
  ——fail-closed 不猜绿）。卡面明文钉「差集→rc=1、一致→rc=0」（锚补全验收口径）；
  执行错=2 与族内 credential-ledger-recon-gate（0/1/2）同形，族内另有 0/2/3 形
  （bao-token-ttl-recon-gate），如实注记不回改族约。

【清册形制】（夹具即样例；sha8 可缺省/8 位小写 hex/null，仅点名展示不参与判定）
  {"schema": "af.token-fileset-registry.v1", "updated": "2026-11-10",
   "agreed_dirs": ["/abs/dir1", "/abs/dir2"],
   "entries": [{"name": "...", "kind": "scoped-face", "path": "/abs/dir1/xxx.tag",
                "sha8": "0a1b2c3d", "expires": "2026-12-08",
                "reason": "...", "approved_by": "..."}]}

用法：
  python3 -I tools/token-fileset-recon-gate.py --selftest
  python3 -I tools/token-fileset-recon-gate.py --fixture all-match   # 或 rogue-face/
      ghost-entry/dir-gone（别名：全集一致/清册外/册存盘缺/目录不可扫；合成数据零真凭据）
  python3 -I tools/token-fileset-recon-gate.py --check --registry <清册.json>
"""
import datetime
import hashlib
import io
import json
import os
import re
import sys
import tempfile

SCHEMA = "af.token-fileset-registry.v1"
REPORT_SCHEMA = "af.token-fileset-recon.v1"
SHA8_RE = re.compile(r"^[0-9a-f]{8}$")
ENTRY_REQUIRED = ("name", "kind", "path", "expires")
GREEN, RED, ERROR = 0, 1, 2
CHAINED_NOTE = "全集入扫后逐件 explicit_max_ttl 由 D-150/ESC-12 门自判——本门不并吞其判定（卡面 env_precondition 明文）"

# 内置夹具（SENTINEL 合成形，零真凭据）：名 → 期望出口；中文别名供人工复放
FIXTURES = {"all-match": GREEN, "rogue-face": RED, "ghost-entry": RED, "dir-gone": ERROR}
FIXTURE_ALIAS = {"全集一致": "all-match", "清册外": "rogue-face",
                 "册存盘缺": "ghost-entry", "目录不可扫": "dir-gone"}
# 泄密哨兵（合成载荷，SENTINEL 形）：注入夹具，断言门全输出零命中
FX_SENTINELS = {"a": b"SENTINEL-FX-FACE-A", "b": b"SENTINEL-FX-FACE-B",
                "issuer": b"SENTINEL-FX-FACE-ISSUER", "rogue": b"SENTINEL-FX-ROGUE",
                "nested": b"SENTINEL-FX-NESTED", "link": b"SENTINEL-FX-LINK",
                "bidir": b"SENTINEL-FX-BIDIR"}


def err(msg):
    sys.stderr.write("[token-fileset-recon-gate] %s\n" % msg)


def sha8_of_text(text):
    """仅夹具合成面用（对合成载荷造点名指纹）；真跑面禁——内容复算即读取凭据本体。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


class GateError(Exception):
    """清册坏形/盘面不可扫/用法错——exit 2，不猜绿。"""


# ---- 清册装载与形制机检 ----------------------------------------------------------

def _under(dir_np, path_np):
    return path_np.startswith(dir_np + os.sep)


def load_registry(path):
    try:
        with open(path, "rb") as fh:   # 清册=簿记面（只记路径+指纹），非凭据本体
            raw = fh.read()
    except OSError as exc:
        raise GateError("清册不可读：%s（%s）" % (path, exc))
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise GateError("清册不可解码：%s" % exc)
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise GateError("清册 schema 非 %s" % SCHEMA)
    entries = data.get("entries")
    if not isinstance(entries, list):
        raise GateError("清册 entries 缺失或非列表")
    dirs = data.get("agreed_dirs")
    if not isinstance(dirs, list) or not dirs:
        raise GateError("清册 agreed_dirs 缺失或为空（无约定目录集=无可对面，不猜绿）")
    dirs_np = []
    for d in dirs:
        if not isinstance(d, str) or not d:
            raise GateError("agreed_dirs 条目非法：%r" % (d,))
        if not os.path.isabs(d):
            raise GateError("agreed_dirs 须绝对路径：%s" % d)
        dirs_np.append(os.path.normpath(d))
    if len(set(dirs_np)) != len(dirs_np):
        raise GateError("agreed_dirs 重复（册形损坏）")
    for i in range(len(dirs_np)):
        for j in range(len(dirs_np)):
            if i != j and _under(dirs_np[i], dirs_np[j]):
                raise GateError("agreed_dirs 嵌套（%s ⊂ %s·册形损坏）" % (dirs_np[j], dirs_np[i]))
    seen = set()
    for ent in entries:
        if not isinstance(ent, dict):
            raise GateError("清册条目非对象：%r" % (ent,))
        for key in ENTRY_REQUIRED:
            if key not in ent:
                raise GateError("清册条目缺字段 %s（%s）" % (key, ent.get("path") or ent.get("name")))
        name = ent["name"]
        if not isinstance(name, str) or not name:
            raise GateError("清册条目 name 非法")
        if not isinstance(ent["kind"], str) or not ent["kind"]:
            raise GateError("清册条目 kind 非法：%s" % name)
        if not isinstance(ent["path"], str) or not os.path.isabs(ent["path"]):
            raise GateError("清册条目 path 须非空绝对路径：%s" % name)
        np_path = os.path.normpath(ent["path"])
        if np_path in seen:
            raise GateError("清册条目 path 重复（册形损坏）：%s" % np_path)
        if any(np_path == d for d in dirs_np):
            raise GateError("清册条目 path 指向约定目录本身（须为目录内件）：%s" % np_path)
        if not any(_under(d, np_path) for d in dirs_np):
            raise GateError("清册条目 path 越约定目录集外（不可枚举=不可证，不猜绿）：%s" % np_path)
        fp = ent.get("sha8")
        if fp is not None and (not isinstance(fp, str) or not SHA8_RE.match(fp)):
            raise GateError("清册条目 sha8 须 8 位小写 hex 或 null：%s" % name)
        try:
            datetime.date.fromisoformat(ent["expires"])
        except (TypeError, ValueError):
            raise GateError("清册条目 expires 须 ISO 日期：%s" % name)
        seen.add(np_path)
    return data


# ---- 判定核（纯名录/元数据面，零内容读取；--selftest 与真跑共用） -----------------

def stat_meta(path):
    """盘面元数据一条：尺寸＋mtime（stat 面；绝不 open 文件内容）。"""
    try:
        st = os.stat(path)
    except OSError:
        return None, None
    return int(st.st_size), datetime.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")


def enumerate_face(dirs_np):
    """约定目录集全量递归枚举：返回 (盘面件集, 未下钻符号链接目录, 面错)。"""
    faces, symlink_dirs, errors = set(), [], []

    def on_walk_err(exc):
        errors.append("盘面枚举不可证：%s（%s）" % (getattr(exc, "filename", "?"), exc))

    for d in dirs_np:
        if not os.path.isdir(d):
            errors.append("约定目录不可扫（缺席或非目录）：%s" % d)
            continue
        for dirpath, dirnames, filenames in os.walk(d, followlinks=False, onerror=on_walk_err):
            for dn in dirnames:
                full = os.path.join(dirpath, dn)
                if os.path.islink(full):
                    symlink_dirs.append(full)   # 不下钻但点名注记（不静默）
            for fn in filenames:
                faces.add(os.path.normpath(os.path.join(dirpath, fn)))
    return faces, symlink_dirs, errors


def judge(registry, today=None):
    """registry=已过 load_registry 的好册 → (verdict, report)。"""
    today = today or datetime.date.today()
    dirs_np = [os.path.normpath(d) for d in registry["agreed_dirs"]]
    reg_by_path = {}
    expired_review = []
    for ent in registry["entries"]:
        np_path = os.path.normpath(ent["path"])
        reg_by_path[np_path] = ent
        try:
            if datetime.date.fromisoformat(ent["expires"]) < today:
                expired_review.append(np_path)
        except (TypeError, ValueError):
            pass   # 坏 expires 已在 load_registry 拦截，好册必达

    faces, symlink_dirs, errors = enumerate_face(dirs_np)
    red, rogue, ghost, matched = [], [], [], []
    for np_path in sorted(faces):
        if np_path in reg_by_path:
            matched.append(np_path)
        else:
            size, mtime = stat_meta(np_path)
            red.append({"path": np_path, "sha8": None, "size_disk": size, "mtime": mtime,
                        "why": "清册外未登记（盘面现存而清册无名）"})
            rogue.append(np_path)
    for np_path in sorted(reg_by_path):
        if np_path in faces:
            continue
        if os.path.isdir(np_path):
            red.append({"path": np_path, "sha8": reg_by_path[np_path].get("sha8"),
                        "size_disk": None, "mtime": None,
                        "why": "清册在册而盘面为目录非凭据件（面不符）"})
        else:
            red.append({"path": np_path, "sha8": reg_by_path[np_path].get("sha8"),
                        "size_disk": None, "mtime": None,
                        "why": "清册在册而盘面缺席"})
        ghost.append(np_path)

    verdict = RED if red else (ERROR if errors else GREEN)
    report = {
        "schema": REPORT_SCHEMA,
        "verdict": {GREEN: "GREEN", RED: "RED", ERROR: "INSUFFICIENT"}[verdict],
        "counts": {
            "agreed_dirs": len(dirs_np),
            "entries": len(reg_by_path),
            "faces": len(faces),
            "matched": len(matched),
            "rogue_faces": len(rogue),
            "ghost_entries": len(ghost),
            "red": len(red),
        },
        "red": red,
        "annotations": {
            "expired_review": expired_review,
            "symlink_dirs_not_followed": sorted(symlink_dirs),
            "face_errors": errors,
            "chained_ttl_gate": CHAINED_NOTE,
        },
    }
    return verdict, report


def render(report):
    c = report["counts"]
    out = ["== token-fileset-recon-gate · %s ==" % report["verdict"],
           "面：约定目录 %d｜盘面枚举 %d 件｜清册 %d 条｜红 %d｜对上 %d｜清册外 %d｜册存盘缺 %d" % (
               c["agreed_dirs"], c["faces"], c["entries"], c["red"],
               c["matched"], c["rogue_faces"], c["ghost_entries"])]
    for r in report["red"]:
        if r["size_disk"] is not None:
            tail = "盘面 %sB｜mtime %s" % (r["size_disk"], r["mtime"] or "—")
        elif "目录非凭据件" in r["why"]:
            tail = "盘面为目录"
        elif "盘面缺席" in r["why"]:
            tail = "盘面缺席"
        else:
            tail = "盘面元数据不可读"
        out.append("  红｜%s｜%s｜sha8=%s｜%s" % (r["why"], r["path"], r["sha8"] or "—", tail))
    ann = report["annotations"]
    out.append("  注记：复审逾期 %d%s｜未下钻符号链接目录 %d%s｜面错 %d%s｜串联=%s" % (
        len(ann["expired_review"]),
        ("（%s）" % "、".join(ann["expired_review"])) if ann["expired_review"] else "",
        len(ann["symlink_dirs_not_followed"]),
        ("（%s）" % "、".join(ann["symlink_dirs_not_followed"])) if ann["symlink_dirs_not_followed"] else "",
        len(ann["face_errors"]),
        ("｜" + "；".join(ann["face_errors"])) if ann["face_errors"] else "",
        "D-150 TTL 门自判（本门只全集入扫）"))
    return "\n".join(out)


def run_check(registry_path):
    registry = load_registry(registry_path)
    verdict, report = judge(registry)
    print(render(report))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return verdict


# ---- 内置夹具（SENTINEL 合成形，零真凭据；sha8 由夹具建造器对合成载荷自造） -------

def _fx_face(dirpath, fname_tag, payload_tag):
    path = os.path.join(dirpath, fname_tag)
    with open(path, "wb") as fh:
        fh.write(payload_tag)
    return {"path": path, "sha8": sha8_of_text(payload_tag.decode("ascii")), "size": len(payload_tag)}


def _fx_entry(face, name_tag, expires="2026-12-08"):
    return {"name": name_tag, "kind": "fixture-face", "path": face["path"],
            "sha8": face["sha8"], "expires": expires,
            "reason": "夹具（禁回显字段）", "approved_by": "夹具"}


def _reg(entries, dirs):
    return {"schema": SCHEMA, "updated": "2026-11-10", "agreed_dirs": dirs, "entries": entries}


def build_fixture(name, td):
    """在临时目录 td 内造合成盘面＋清册；name ∈ FIXTURES。"""
    if name not in FIXTURES:
        raise GateError("未知夹具：%s" % name)
    d_main = os.path.join(td, "faces-main")
    d_gov = os.path.join(td, "faces-gov")
    os.makedirs(d_main)
    os.makedirs(d_gov)
    fa = _fx_face(d_main, "fx-scoped-one.tag", FX_SENTINELS["a"])
    fb = _fx_face(d_main, "fx-scoped-two.tag", FX_SENTINELS["b"])
    fi = _fx_face(d_gov, "fx-issuer-face.tag", FX_SENTINELS["issuer"])
    entries = [_fx_entry(fa, "fx-scoped-one"), _fx_entry(fb, "fx-scoped-two"),
               _fx_entry(fi, "fx-issuer-face")]
    dirs = [d_main, d_gov]
    if name == "rogue-face":
        _fx_face(d_gov, "fx-rogue-extra.tag", FX_SENTINELS["rogue"])   # 清册外第 8 件形态 ⇒ 红
    elif name == "ghost-entry":
        ghost_path = os.path.join(d_main, "fx-ghost-absent.tag")
        entries.append({"name": "fx-ghost-absent", "kind": "fixture-face", "path": ghost_path,
                        "sha8": None, "expires": "2026-12-08",
                        "reason": "夹具（禁回显字段）", "approved_by": "夹具"})
    elif name == "dir-gone":
        dirs.append(os.path.join(td, "nope-dir"))   # 约定目录缺席 ⇒ 零红面缺不猜绿
    return _reg(entries, dirs)


def canonical_fixture(name):
    if name in FIXTURES:
        return name
    for alias, canon in FIXTURE_ALIAS.items():
        if name == alias:
            return canon
    raise GateError("未知夹具名：%s（可用 all-match/rogue-face/ghost-entry/dir-gone 或别名 全集一致/清册外/册存盘缺/目录不可扫）" % name)


def run_fixture(name):
    name = canonical_fixture(name)
    with tempfile.TemporaryDirectory(prefix="token-fileset-fx-") as td:
        rp = os.path.join(td, "registry.json")
        with open(rp, "w", encoding="utf-8") as fh:
            json.dump(build_fixture(name, td), fh, ensure_ascii=False, indent=1)
        return run_check(rp)


# ---- 自证面（零网络零真凭据：四夹具全链真跑＋泄密哨兵＋差集咬人＋坏形 fail-closed） -

def _capture_check(rp):
    buf = io.StringIO()
    saved = sys.stdout
    sys.stdout = buf
    try:
        got = run_check(rp)
    finally:
        sys.stdout = saved
    return got, buf.getvalue()


def run_selftest():
    today = datetime.date(2026, 11, 10)
    cases = []

    # ① 四夹具全链真跑（装载→判定→渲染→出口）＋泄密哨兵断言（零凭据读取纪律）
    for name in ("all-match", "rogue-face", "ghost-entry", "dir-gone"):
        want = FIXTURES[name]
        with tempfile.TemporaryDirectory(prefix="token-fileset-fx-") as td:
            rp = os.path.join(td, "registry.json")
            with open(rp, "w", encoding="utf-8") as fh:
                json.dump(build_fixture(name, td), fh, ensure_ascii=False, indent=1)
            got, out = _capture_check(rp)
        cases.append(("夹具·%s" % name, want, got))
        for s in FX_SENTINELS.values():
            if s.decode("ascii") in out:
                return 1, "泄密哨兵命中（%s 现于门输出）——零凭据读取纪律破" % s.decode("ascii")
        rep = json.loads(out.strip().splitlines()[-1])
        if name == "all-match":
            if rep["counts"]["red"] or rep["counts"]["matched"] != 3:
                return 1, "all-match 不应对红/对上≠3：%r" % (rep["counts"],)
        elif name == "rogue-face":
            if not (len(rep["red"]) == 1 and rep["red"][0]["path"].endswith("fx-rogue-extra.tag")
                    and "清册外" in rep["red"][0]["why"]):
                return 1, "rogue-face 红点名形制不符：%r" % (rep["red"],)
        elif name == "ghost-entry":
            if not (len(rep["red"]) == 1 and rep["red"][0]["path"].endswith("fx-ghost-absent.tag")
                    and "盘面缺席" in rep["red"][0]["why"]):
                return 1, "ghost-entry 红点名形制不符：%r" % (rep["red"],)
        elif name == "dir-gone":
            if rep["verdict"] != "INSUFFICIENT" or not any("nope-dir" in e for e in rep["annotations"]["face_errors"]):
                return 1, "dir-gone 面缺不猜绿形制不符：%r" % (rep["annotations"],)

    # ② 差集咬人与全集聚真（judge 级逐形态）
    with tempfile.TemporaryDirectory(prefix="token-fileset-fx-") as td:
        d_main = os.path.join(td, "faces-main")
        os.makedirs(d_main)
        f_ok = _fx_face(d_main, "fx-ok.tag", FX_SENTINELS["a"])

        # 双向差集并存 ⇒ 2 红（清册外＋册存盘缺同报）
        f_bidir = _fx_face(d_main, "fx-bidir-extra.tag", FX_SENTINELS["bidir"])
        led = _reg([_fx_entry(f_ok, "fx-ok"),
                    {"name": "fx-bidir-ghost", "kind": "fixture-face",
                     "path": os.path.join(d_main, "fx-bidir-ghost.tag"), "sha8": None,
                     "expires": "2026-12-08", "reason": "夹具", "approved_by": "夹具"}],
                   [d_main])
        v, rep = judge(led, today)
        cases.append(("双向差集红", RED, v))
        if len(rep["red"]) != 2 or not (any("清册外" in r["why"] for r in rep["red"])
                                        and any("盘面缺席" in r["why"] for r in rep["red"])):
            return 1, "双向差集红形制不符：%r" % (rep["red"],)
        os.remove(f_bidir["path"])

        # 子目录递归：未登记嵌套件 ⇒ 红点名（全集聚真，一层扫描会漏）
        os.makedirs(os.path.join(d_main, "sub"))
        f_nested = _fx_face(os.path.join(d_main, "sub"), "fx-nested.tag", FX_SENTINELS["nested"])
        v, rep = judge(_reg([_fx_entry(f_ok, "fx-ok")], [d_main]), today)
        cases.append(("子目录递归点名", RED, v))
        if not (rep["red"] and rep["red"][0]["path"].endswith(os.path.join("sub", "fx-nested.tag"))):
            return 1, "子目录递归点名形制不符：%r" % (rep["red"],)
        # 登记嵌套件 ⇒ 对上转绿
        v, rep = judge(_reg([_fx_entry(f_ok, "fx-ok"), _fx_entry(f_nested, "fx-nested")], [d_main]), today)
        cases.append(("登记嵌套件对上", GREEN, v))

        # 符号链接目录：不下钻但点名注记（不静默、不红）
        d_alias = os.path.join(td, "faces-alias")
        os.makedirs(d_alias)
        os.symlink(d_main, os.path.join(d_alias, "alias-dir.tag"))
        v, rep = judge(_reg([_fx_entry(f_ok, "fx-ok"), _fx_entry(f_nested, "fx-nested")],
                            [d_main, d_alias]), today)
        cases.append(("符号链接目录注记", GREEN, v))
        if not any(a.endswith("alias-dir.tag") for a in rep["annotations"]["symlink_dirs_not_followed"]):
            return 1, "符号链接目录注记形制不符：%r" % (rep["annotations"],)

        # 符号链接件＝盘面件：未登记 ⇒ 红点名
        os.symlink(f_ok["path"], os.path.join(d_alias, "fx-link-face.tag"))
        v, rep = judge(_reg([_fx_entry(f_ok, "fx-ok"), _fx_entry(f_nested, "fx-nested")],
                            [d_main, d_alias]), today)
        cases.append(("符号链接件点名", RED, v))
        if not (rep["red"] and rep["red"][0]["path"].endswith("fx-link-face.tag")):
            return 1, "符号链接件点名形制不符：%r" % (rep["red"],)

        # 红优先：面缺（目录缺席）＋实证红 ⇒ 红；零红＋面缺 ⇒ 执行错（夹具 dir-gone 已证）
        led = _reg([_fx_entry(f_ok, "fx-ok"), _fx_entry(f_nested, "fx-nested")],
                   [d_main, os.path.join(td, "nope")])
        _fx_face(d_main, "fx-priority-extra.tag", FX_SENTINELS["rogue"])
        cases.append(("面缺红优先", RED, judge(led, today)[0]))
        os.remove(os.path.join(d_main, "fx-priority-extra.tag"))
        cases.append(("面缺零红不猜绿", ERROR, judge(led, today)[0]))

        # 在册路径现势为目录 ⇒ 红（面不符点名；嵌套件同册登记以隔离单红）
        led = _reg([_fx_entry(f_ok, "fx-ok"), _fx_entry(f_nested, "fx-nested"),
                    {"name": "fx-dir-as-entry", "kind": "fixture-face",
                     "path": os.path.join(d_main, "sub"), "sha8": None,
                     "expires": "2026-12-08", "reason": "夹具", "approved_by": "夹具"}], [d_main])
        v, rep = judge(led, today)
        cases.append(("条目对目录红", RED, v))
        if not (rep["red"] and any("目录非凭据件" in r["why"] for r in rep["red"])):
            return 1, "条目对目录红形制不符：%r" % (rep["red"],)

        # 空册有面 ⇒ 全清册外红；空册空目录 ⇒ 绿；复审逾期 ⇒ 注记不红
        cases.append(("空册全清册外", RED, judge(_reg([], [d_main]), today)[0]))
        d_empty = os.path.join(td, "faces-empty")
        os.makedirs(d_empty)
        cases.append(("空册空面绿", GREEN, judge(_reg([], [d_empty]), today)[0]))
        v, rep = judge(_reg([_fx_entry(f_ok, "fx-ok", expires="2026-10-01"),
                             _fx_entry(f_nested, "fx-nested")], [d_main]), today)
        cases.append(("复审逾期注记", GREEN, v))
        if f_ok["path"] not in rep["annotations"]["expired_review"]:
            return 1, "复审逾期注记形制不符：%r" % (rep["annotations"],)

    # ③ 清册坏形 fail-closed（逐形态咬人）
    good = {"name": "fx", "kind": "fixture-face", "path": "/tmp/fx/a.tag",
            "sha8": "0a1b2c3d", "expires": "2026-12-08"}
    base = {"schema": SCHEMA, "updated": "2026-11-10", "agreed_dirs": ["/tmp/fx"],
            "entries": [good]}
    bads = {
        "坏schema": {**base, "schema": "other.v1"},
        "entries非列表": {**base, "entries": "x"},
        "缺agreed_dirs": {k: v for k, v in base.items() if k != "agreed_dirs"},
        "agreed_dirs空": {**base, "agreed_dirs": []},
        "相对dir": {**base, "agreed_dirs": ["rel/dir"]},
        "目录重复": {**base, "agreed_dirs": ["/tmp/fx", "/tmp/fx/"]},
        "目录嵌套": {**base, "agreed_dirs": ["/tmp/fx", "/tmp/fx/sub"]},
        "条目非对象": {**base, "entries": ["x"]},
        "缺字段path": {**base, "entries": [{k: v for k, v in good.items() if k != "path"}]},
        "缺字段expires": {**base, "entries": [{k: v for k, v in good.items() if k != "expires"}]},
        "name空": {**base, "entries": [dict(good, name="")]},
        "kind空": {**base, "entries": [dict(good, kind="")]},
        "path相对": {**base, "entries": [dict(good, path="rel/a.tag")]},
        "path越集外": {**base, "entries": [dict(good, path="/tmp/other/a.tag")]},
        "path指目录本身": {**base, "entries": [dict(good, path="/tmp/fx")]},
        "sha8非hex": {**base, "entries": [dict(good, sha8="ZZZZZZZZ")]},
        "sha8超8位": {**base, "entries": [dict(good, sha8="0a1b2c3d99")]},
        "expires坏": {**base, "entries": [dict(good, expires="soon")]},
        "path重复": {**base, "entries": [good, dict(good)]},
    }
    with tempfile.TemporaryDirectory(prefix="token-fileset-fx-") as td:
        for label, fixture in bads.items():
            fp = os.path.join(td, "bad.json")
            with open(fp, "w", encoding="utf-8") as fh:
                json.dump(fixture, fh, ensure_ascii=False)
            try:
                load_registry(fp)
                return 1, "坏形夹具未咬（%s）" % label
            except GateError:
                cases.append(("坏形·%s" % label, ERROR, ERROR))
        fp = os.path.join(td, "good.json")
        with open(fp, "w", encoding="utf-8") as fh:
            json.dump(base, fh, ensure_ascii=False)
        load_registry(fp)
        cases.append(("好册装载", GREEN, GREEN))

    # ④ 夹具名解析（别名可用；未知名咬人）
    if canonical_fixture("全集一致") != "all-match" or canonical_fixture("清册外") != "rogue-face" \
            or canonical_fixture("册存盘缺") != "ghost-entry" or canonical_fixture("目录不可扫") != "dir-gone":
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
    print("自证 %d 例全过（四夹具全链＋泄密哨兵零命中＋双向差集咬人＋坏形 fail-closed＋出口 0/1/2）" % len(cases))
    return 0, "ok"


def main(argv):
    if "--selftest" in argv:
        rc, msg = run_selftest()
        if rc != 0:
            err(msg)
        return rc
    check, registry_path, fixture = False, None, None
    rest = list(argv)
    try:
        while rest:
            a = rest.pop(0)
            if a == "--check":
                check = True
            elif a == "--registry":
                if not rest:
                    raise GateError("--registry 须跟清册路径")
                registry_path = rest.pop(0)
            elif a == "--fixture":
                if not rest:
                    raise GateError("--fixture 须跟夹具名")
                fixture = rest.pop(0)
            else:
                raise GateError("未知参数：%s" % a)
        if fixture is not None:
            if check or registry_path is not None:
                raise GateError("--fixture 不与 --check/--registry 同用")
            return run_fixture(fixture)
        if check:
            if registry_path is None:
                raise GateError("--check 须同给 --registry <清册.json>")
            return run_check(registry_path)
        if registry_path is not None:
            raise GateError("--registry 须与 --check 同用")
        raise GateError("缺模式：--selftest / --fixture <名> / --check --registry <清册.json>")
    except GateError as exc:
        err(str(exc))
        return ERROR


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
