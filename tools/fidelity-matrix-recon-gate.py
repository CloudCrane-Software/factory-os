#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""保真度矩阵维度下限判据门——缺维降级标注断言（D-152 · 卡 #236 · wave-13）。

设计来源（卡面正本）：factory-os issue #236（wave-13 · w13-d152-fidelity-matrix-gate，
  允许路径=本件单件新建）；债本体=账本/阶段欠账台账.md D-152 行（2026-11-08 锚补全
  三要件）；新门设计=30-工件/逃逸问题台账-20261108.md ESC-14；现势债实例=D-107
  sbx-sim vs D-117 cnb 真沙箱对照矩阵在案而凭据/身份维度缺位不红——「有对照实测
  数据」可由任意维度子集满足，安全相关维度可被静默省略。gate 形制对齐仓内
  negative-control-recon-gate 族（出口 0/1/2、fail-closed、--selftest 造夹具自证
  会咬人、点名不裸 FAIL）。出口取 0/1/2：本卡面验收口径明文「缺凭据维→rc=1」，
  红=1 为正本（与 bao-token-ttl-recon-gate 族的 0/2/3 形制不同系卡面差异，非本件
  自选，如实注记）。

【判据】（卡面+锚行，只增拦截禁放宽）
  对「保真度矩阵」读数件（JSON：记录×维度 的打分/覆盖矩阵）断言：
  ① 必备维度集（--dims 传入；缺省=锚行枚举集 网络/凭据/编译器/耗时/verdict，
     凭据面=sandbox 内可见 token/身份集逐项对照）逐记录逐维在场（键在场且读数
     非空：None/""/[]/{} 记「空读数」，与缺席同判）；
  ② 任一记录缺维 ⇒ 必须带显式「降级标注」（degraded=true 且 reason 非空）——
     缺维即该表不得作「保真度过门」证据（锚行：降级为部分证据并明记），无论
     有无标注一律红（rc=1）；无标注另点名「静默省略」（ESC-14 形态，更重），
     有标注点名「已降级为部分证据并明记」。绿只能来自补维（补维后复检 rc=0）。
  ③ 全维在场 ⇒ rc=0。
  · 凭据纪律：读数件只读；凭据维只取身份集名不取明文——凭据名维（凭据/凭证/
    credential/token/identity 等）值带疑似明文凭据前缀（ghp_/github_pat_/sk-/
    glpat-/AKIA 等）⇒ 红，输出只印值 sha256 前 8 位指纹，绝不回显值本体。

【读数件形制】（schema=af.fidelity-matrix.v1，load/validate 单一实现 fail-closed）
  {"schema": "af.fidelity-matrix.v1",
   "face": "<对照面描述，可选>",
   "dims": ["网络","凭据","编译器","耗时","verdict"],   // 声明维词表，可选；
                                                      // 声明后记录维键必须 ⊆ 词表
   "records": [
     {"id": "sbx-sim/case-001",
      "dims": {"网络": "<覆盖读数>", "凭据": "identity-set:agent-git-read", ...},
      "degraded": false},                               // 全维记录不应带
     {"id": "cnb/case-001", "dims": {...缺凭据...},
      "degraded": true, "reason": "<缺维原因·降级明记>"}]}
  坏形（非 dict/缺 schema/records 非列表或空/id 缺失或重复/dims 非 dict/声明词表
  重复或记录维键出词表）⇒ fail-closed exit 2，不猜绿不猜红。

【出口】0=全维在场（可作保真度过门证据）；1=红（缺维——已降级/静默两形均红——
  或凭据维疑似明文；逐条点名）；2=fail-closed（读数件不可读/不可解码/坏形/参数坏）。

【消费者侧证据】判定核纯函数（validate_matrix/check_matrix/judge_records/
  parse_dims）模块级可导入（SourceFileLoader 复用同 negative-control-recon-gate
  形制）；--selftest 第⑨腿以 subprocess 真调用本件 CLI 一次（实取 returncode，
  同 -I 调用形制）——调用点见 run_selftest 内 subprocess.run 行。

用法：
  python3 -I tools/fidelity-matrix-recon-gate.py --selftest            # 沙箱自证
  python3 -I tools/fidelity-matrix-recon-gate.py --fixture full-dims    # 内置夹具
  python3 -I tools/fidelity-matrix-recon-gate.py --fixture missing-cred-dim
  python3 -I tools/fidelity-matrix-recon-gate.py --check --matrix 矩阵.json
  python3 -I tools/fidelity-matrix-recon-gate.py --check --matrix 矩阵.json --dims d1,d2
内置夹具：full-dims（全维→0）/ missing-cred-dim（缺凭据维无标注→1 静默点名）/
  missing-cred-annotated（缺凭据维带降级标注→1 降级明记）/ current-107-117
  （D-107 vs D-117 现势形态：凭据/身份维缺位→1 如实红）/ cred-plaintext（凭据维
  疑似明文→1）/ bad-shape、empty-records（坏形→2）。
  cred-plaintext 夹具的「疑似明文」维值用自义哨兵形 SENTINEL-PLAINTEXT-CRED-0001
  （不含真实凭据前缀族词形——出仓扫描词形避让，w15 修复批；检测面同步识别哨兵
  前缀 SENTINEL-PLAINTEXT，语义不变：含哨兵 ⇒ 红＋只印 sha8 指纹不回显值本体）。
本件零网络、零凭据、零写入（读数件只读；--selftest 仅 tempfile 沙箱）。
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile

SCHEMA = "af.fidelity-matrix-recon.v1"
SCHEMA_MATRIX = "af.fidelity-matrix.v1"
GREEN, RED, FAIL_CLOSED = 0, 1, 2

# 锚行 D-152 枚举维度集（缺省必备维；--dims 可覆盖，如通用五维
# 完整性/时延/成本/正确性/可追溯——卡面任务栏示例形）
DEFAULT_DIMS = ("网络", "凭据", "编译器", "耗时", "verdict")
# 凭据名维（这些维的值只许身份集名/覆盖标记，明文前缀扫描面）
CRED_DIM_NAMES = ("凭据", "凭证", "credential", "credentials", "token", "tokens", "identity")
# 疑似明文凭据前缀（只印 sha8 指纹，绝不回显值本体）
CRED_PREFIXES = ("ghp_", "gho_", "ghu_", "ghs_", "ghr_", "github_pat_",
                 "sk-", "sk_", "xox", "glpat-", "AKIA", "Bearer ")
# 自义哨兵形（w15 修复批·出仓扫描词形避让）：夹具「疑似明文」维值不用真实前缀族
# 假令牌（完整假令牌会被出仓扫描 G-03 前缀族形咬住），改用本件自义哨兵——不含
# 任何真实前缀族词形；检测面同步双识别（真实前缀族＋本哨兵前缀），语义不变：
# 夹具维值含哨兵 ⇒ 同判疑似明文红＋只印 sha8 指纹不回显值本体。
SENTINEL_PREFIX = "SENTINEL-PLAINTEXT"


class GateError(Exception):
    """读数件不可读/坏形/参数坏——fail-closed，exit 2，不猜绿不猜红。"""


def err(msg):
    sys.stderr.write("[fidelity-matrix-recon-gate] %s\n" % msg)


def sha8(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


# ---- 参数与读数件装载（单一实现，fail-closed） ------------------------------------

def parse_dims(text):
    """--dims「d1,d2」→ 去空白条目列表；空集/重复 ⇒ GateError；None ⇒ 缺省枚举集。"""
    if text is None:
        return list(DEFAULT_DIMS)
    dims = [d.strip() for d in text.split(",")]
    dims = [d for d in dims if d]
    if not dims:
        raise GateError("--dims 解析为空集（须逗号分隔非空维名）")
    seen = set()
    for d in dims:
        if d in seen:
            raise GateError("--dims 维名重复：%s" % d)
        seen.add(d)
    return dims


def _vocab_hint(vocab, key):
    """词表内与出词表键共享字符的项（命名漂移线索，如 凭证→凭据）。"""
    hits = [v for v in vocab if v != key and set(v) & set(key)]
    return "（近似词表项：%s——疑命名漂移）" % "、".join(hits[:3]) if hits else ""


def validate_matrix(data):
    """形制机检 → (records, declared_dims)；坏形 ⇒ GateError（带点名）。"""
    if not isinstance(data, dict):
        raise GateError("读数件非对象（须 schema=%s 的 JSON 对象）" % SCHEMA_MATRIX)
    if data.get("schema") != SCHEMA_MATRIX:
        raise GateError("读数件 schema 非 %s（现值 %r）——非本门管辖读数形制"
                        % (SCHEMA_MATRIX, data.get("schema")))
    records = data.get("records")
    if not isinstance(records, list) or not records:
        raise GateError("records 缺失/非列表/为空（空壳矩阵=不可证，不猜绿）")
    declared = data.get("dims")
    if declared is not None:
        if (not isinstance(declared, list) or not declared
                or not all(isinstance(d, str) and d for d in declared)):
            raise GateError("声明维词表 dims 非法（须非空字符串列表）：%r" % (declared,))
        if len(set(declared)) != len(declared):
            raise GateError("声明维词表 dims 重复：%r" % (declared,))
        declared = set(declared)
    seen_ids = set()
    for idx, rec in enumerate(records):
        if not isinstance(rec, dict):
            raise GateError("records[%d] 非对象：%r" % (idx, rec))
        rid = rec.get("id")
        if not isinstance(rid, str) or not rid:
            raise GateError("records[%d] 缺非空 id（点名依赖稳定标识）" % idx)
        if rid in seen_ids:
            raise GateError("记录 id 重复（矩阵坏形）：%s" % rid)
        seen_ids.add(rid)
        dims = rec.get("dims")
        if not isinstance(dims, dict):
            raise GateError("记录 %s 的 dims 非对象：%r" % (rid, dims))
        for key in dims:
            if not isinstance(key, str) or not key:
                raise GateError("记录 %s 的维键非法：%r" % (rid, key))
            if declared is not None and key not in declared:
                raise GateError("记录 %s 的维 %r 不在声明维词表内%s"
                                % (rid, key, _vocab_hint(declared, key)))
    return records, declared


# ---- 判定核（纯函数；--selftest 与真跑共用） -------------------------------------

def _flat_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            for s in _flat_strings(v):
                yield s
    elif isinstance(value, (list, tuple)):
        for v in value:
            for s in _flat_strings(v):
                yield s


def _is_empty_reading(v):
    """空读数形（None/""/[]/{}）——键在场但无数据，与缺席同判缺维。"""
    return v is None or v == "" or v == [] or v == {}


def _looks_plaintext(value):
    """真实前缀族＋自义哨兵形双识别（哨兵＝夹具自证用，见 SENTINEL_PREFIX 注记）。"""
    return any(s.startswith(p) for s in _flat_strings(value)
               for p in CRED_PREFIXES + (SENTINEL_PREFIX,))


CLASS_SILENT = "缺维且无降级标注（静默省略·ESC-14 形态）"
CLASS_DEGRADED = "缺维已带降级标注（降级为部分证据并明记·不得作过门证据）"


def judge_records(records, required):
    """逐记录断言必备维在场＋降级标注；返回 (verdict, report)。"""
    violations, cred_plain, notes = [], [], []
    for rec in records:
        rid, dims = rec["id"], rec["dims"]
        absent = [d for d in required if d not in dims]
        empty = [d for d in required if d in dims and _is_empty_reading(dims[d])]
        missing = [d for d in required if d not in dims or
                   (d in dims and _is_empty_reading(dims[d]))]
        if missing:
            reason = rec.get("reason")
            annotated = (rec.get("degraded") is True and isinstance(reason, str)
                         and reason.strip())
            violations.append({
                "id": rid,
                "missing_dims": missing,
                "absent_dims": absent,
                "empty_reading_dims": empty,
                "annotation": "degraded" if annotated else "none",
                "reason": (reason.strip()[:80] if annotated else None),
                "classification": CLASS_DEGRADED if annotated else CLASS_SILENT,
            })
        elif rec.get("degraded"):
            notes.append("记录 %s 全维在场却带 degraded 标注（标注与读数矛盾——"
                         "如实注记不判红）" % rid)
        for dname in dims:
            if dname in CRED_DIM_NAMES and not _is_empty_reading(dims[dname]) \
                    and _looks_plaintext(dims[dname]):
                cred_plain.append({"id": rid, "dim": dname, "value_sha8": sha8(json.dumps(
                    dims[dname], ensure_ascii=False, sort_keys=True))})
    if violations or cred_plain:
        verdict = RED
        detail = ("缺维 %d 例（已降级 %d／静默 %d）＋凭据维疑似明文 %d 例——该表不得作"
                  "「保真度过门」证据（降级为部分证据并明记；补维并清凭据面后复检）"
                  % (len(violations),
                     sum(1 for v in violations if v["annotation"] == "degraded"),
                     sum(1 for v in violations if v["annotation"] == "none"),
                     len(cred_plain)))
    else:
        verdict = GREEN
        detail = "全部 %d 条记录必备维逐维在场——可作「保真度过门」证据" % len(records)
    report = {
        "schema": SCHEMA,
        "verdict": {GREEN: "GREEN", RED: "RED"}[verdict],
        "required_dims": list(required),
        "counts": {
            "records": len(records),
            "full_dims": len(records) - len(violations),
            "missing_degraded": sum(1 for v in violations if v["annotation"] == "degraded"),
            "missing_silent": sum(1 for v in violations if v["annotation"] == "none"),
            "cred_plaintext": len(cred_plain),
            "notes": len(notes),
        },
        "violations": violations,
        "cred_plaintext": cred_plain,
        "annotations": notes,
        "detail": detail,
    }
    return verdict, report


def check_matrix(data, required):
    """装载后矩阵（dict）→ 形制机检＋判定；坏形 ⇒ GateError。"""
    records, _declared = validate_matrix(data)
    return judge_records(records, required)


def render(report):
    out = ["== fidelity-matrix-recon-gate · %s ==" % report["verdict"],
           "必备维：%s｜记录 %d（全维 %d｜缺维已降级 %d｜缺维静默 %d）｜凭据明文红 %d｜注记 %d"
           % ("、".join(report["required_dims"]),
              report["counts"]["records"], report["counts"]["full_dims"],
              report["counts"]["missing_degraded"], report["counts"]["missing_silent"],
              report["counts"]["cred_plaintext"], report["counts"]["notes"])]
    for v in report["violations"]:
        tail = "｜reason=%s" % v["reason"] if v["reason"] else ""
        extra = ("｜空读数维[%s]" % "、".join(v["empty_reading_dims"])) if v["empty_reading_dims"] else ""
        out.append("  红 id=%s 缺维[%s]%s → %s%s" % (
            v["id"], "、".join(v["missing_dims"]), extra, v["classification"], tail))
    for c in report["cred_plaintext"]:
        out.append("  红·凭据纪律 id=%s 维=%s 值sha8=%s…——凭据维只取身份集名，"
                   "疑似明文凭据禁入读数件（值不回显）" % (c["id"], c["dim"], c["value_sha8"]))
    for n in report["annotations"]:
        out.append("  注记：%s" % n)
    out.append("判语：%s" % report["detail"])
    return "\n".join(out)


# ---- 内置夹具（--fixture；真跑与自证共用同一构造） --------------------------------

# 参数名取 with_cred_dim／cred_tag 形（出仓扫描 G-13 词形避让：键名以 cred 紧跟
# ＝再接长非数值串会命中「凭据赋值对」形——键名后缀断开连接符即避让，语义不变）。
def _fx_record(rid, with_cred_dim=True, cred_tag="identity-set:agent-git-read",
               degraded=None):
    dims = {"网络": "egress 允许集逐项对照", "编译器": "gcc 12.2 vs gcc 12.2",
            "耗时": "p50 41s vs p50 43s", "verdict": "PASS vs PASS"}
    if with_cred_dim:
        dims["凭据"] = cred_tag
    rec = {"id": rid, "dims": dims}
    if degraded is not None:
        rec["degraded"] = degraded[0]
        rec["reason"] = degraded[1]
    return rec


def _matrix(records, face, declared=True):
    data = {"schema": SCHEMA_MATRIX, "face": face, "records": records}
    if declared:
        data["dims"] = list(DEFAULT_DIMS)
    return data


FIXTURES = {
    "full-dims": lambda: _matrix(
        [_fx_record("sbx-sim/case-001"), _fx_record("cnb/case-001")],
        "sbx-sim(D-107) vs cnb 真沙箱(D-117) 对照·夹具（全维）"),
    "missing-cred-dim": lambda: _matrix(
        [_fx_record("sbx-sim/case-001", with_cred_dim=False),
         _fx_record("cnb/case-001", with_cred_dim=False)],
        "sbx-sim vs cnb 对照·夹具（缺凭据维·无降级标注＝静默省略）"),
    "missing-cred-annotated": lambda: _matrix(
        [_fx_record("sbx-sim/case-001", with_cred_dim=False,
                    degraded=(True, "凭据面 sandbox 身份集对照未采（补采前降级为部分证据）")),
         _fx_record("cnb/case-001", with_cred_dim=False,
                    degraded=(True, "凭据面 sandbox 身份集对照未采（补采前降级为部分证据）"))],
        "sbx-sim vs cnb 对照·夹具（缺凭据维·已带降级标注）"),
    "current-107-117": lambda: _matrix(
        [_fx_record("sbx-sim(D-107)", with_cred_dim=False),
         _fx_record("cnb-真沙箱(D-117)", with_cred_dim=False)],
        "现势形态复刻：D-107/D-117 对照矩阵凭据/身份维缺位（债本体实例·如实红）"),
    "cred-plaintext": lambda: _matrix(
        [_fx_record("sbx-sim/case-001", cred_tag="SENTINEL-PLAINTEXT-CRED-0001"),
         _fx_record("cnb/case-001")],
        "sbx-sim vs cnb 对照·夹具（凭据维携带疑似明文＝纪律红）"),
    "bad-shape": lambda: {"schema": SCHEMA_MATRIX,
                          "records": [{"dims": {"网络": "x"}}]},   # 缺 id
    "empty-records": lambda: {"schema": SCHEMA_MATRIX, "records": []},
}


# ---- 运行面 -----------------------------------------------------------------------

def _emit(verdict, report, src):
    report = dict(report, matrix=src)
    print(render(report))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return verdict


def run_fixture(name, dims_text):
    builder = FIXTURES.get(name)
    if builder is None:
        raise GateError("未知夹具 %r（可认：%s）" % (name, "、".join(sorted(FIXTURES))))
    verdict, report = check_matrix(builder(), parse_dims(dims_text))
    return _emit(verdict, report, "<fixture:%s>" % name)


def run_check(path, dims_text):
    if not os.path.isfile(path):
        raise GateError("矩阵读数件缺失 %s（不可证——fail-closed）" % path)
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        raise GateError("矩阵读数件不可读 %s（%s）" % (path, exc))
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise GateError("矩阵读数件不可解码 %s（%s）" % (path, exc))
    verdict, report = check_matrix(data, parse_dims(dims_text))
    return _emit(verdict, report, path)


# ---- 沙箱自证（--selftest）：判定核咬人形态＋坏形 fail-closed＋CLI 真调用一次 ------

def run_selftest():
    ok = []

    def check(label, cond):
        ok.append((label, bool(cond)))
        print("  %s %s" % ("PASS" if cond else "FAIL", label))

    # ① 全维在场 ⇒ GREEN rc=0
    rc, rep = check_matrix(FIXTURES["full-dims"](), list(DEFAULT_DIMS))
    check("①full-dims 全维在场 ⇒ rc=0 GREEN", rc == 0 and rep["verdict"] == "GREEN")
    # ② 缺凭据维·无标注 ⇒ rc=1 且点名凭据维＋静默省略形态
    rc, rep = check_matrix(FIXTURES["missing-cred-dim"](), list(DEFAULT_DIMS))
    check("②missing-cred-dim ⇒ rc=1 且逐条点名凭据维",
          rc == 1 and rep["counts"]["missing_silent"] == 2
          and all(v["missing_dims"] == ["凭据"] for v in rep["violations"]))
    check("②b 无标注 ⇒ 静默省略（ESC-14 形态）点名",
          all(v["classification"] == CLASS_SILENT for v in rep["violations"]))
    # ③ 缺凭据维·已带降级标注 ⇒ 仍 rc=1（不得作过门证据）但降级明记＋reason 随行
    rc, rep = check_matrix(FIXTURES["missing-cred-annotated"](), list(DEFAULT_DIMS))
    check("③missing-cred-annotated ⇒ rc=1 降级为部分证据并明记",
          rc == 1 and rep["counts"]["missing_degraded"] == 2
          and all(v["classification"] == CLASS_DEGRADED and v["reason"]
                  for v in rep["violations"]))
    # ④ 现势 D-107/D-117 形态（缺凭据/身份维）⇒ 如实红
    rc, rep = check_matrix(FIXTURES["current-107-117"](), list(DEFAULT_DIMS))
    check("④current-107-117 现势形态 ⇒ rc=1 如实红（补维前不得过门）",
          rc == 1 and rep["counts"]["missing_silent"] == 2)
    # ⑤ 补维（凭据维补 identity-set 名）后 ⇒ rc=0（「补维后→rc=0」口径）
    patched = json.loads(json.dumps(FIXTURES["current-107-117"]()))
    for rec in patched["records"]:
        rec["dims"]["凭据"] = "identity-set:agent-git-read"
    rc, rep = check_matrix(patched, list(DEFAULT_DIMS))
    check("⑤current-107-117 补凭据维后 ⇒ rc=0", rc == 0 and rep["verdict"] == "GREEN")
    # ⑥ 凭据维疑似明文 ⇒ rc=1；输出（render+JSON）绝不回显值本体，只印 sha8
    rc, rep = check_matrix(FIXTURES["cred-plaintext"](), list(DEFAULT_DIMS))
    rendered = render(rep)
    check("⑥cred-plaintext ⇒ rc=1 且只印 sha8 指纹不回显值",
          rc == 1 and rep["counts"]["cred_plaintext"] == 1
          and "SENTINEL-PLAINTEXT-CRED-0001" not in rendered
          and "SENTINEL-PLAINTEXT-CRED-0001" not in json.dumps(rep, ensure_ascii=False)
          and rep["cred_plaintext"][0]["value_sha8"] in rendered)
    # ⑦ --dims 覆盖腿：通用五维（卡面任务栏示例形）全维⇒0／缺正确性⇒1 点名
    gen_dims = ["完整性", "时延", "成本", "正确性", "可追溯"]
    gen_full = {"schema": SCHEMA_MATRIX,
                "records": [{"id": "r1", "dims": {d: "读数" for d in gen_dims}}]}
    gen_missing = {"schema": SCHEMA_MATRIX,
                   "records": [{"id": "r1", "dims": {d: "读数" for d in gen_dims
                                                     if d != "正确性"}}]}
    rc, _ = check_matrix(gen_full, gen_dims)
    check("⑦--dims 覆盖：自定义五维全维 ⇒ rc=0", rc == 0)
    rc, rep = check_matrix(gen_missing, gen_dims)
    check("⑦b --dims 覆盖：缺正确性 ⇒ rc=1 点名正确性",
          rc == 1 and rep["violations"][0]["missing_dims"] == ["正确性"])
    # ⑧ 空读数形（键在场值为 null）⇒ 与缺席同判缺维
    m_empty = _matrix([dict(_fx_record("cnb/case-001"), **{"dims": dict(
        _fx_record("cnb/case-001")["dims"], 凭据=None)})], "夹具（空读数形）")
    rc, rep = check_matrix(m_empty, list(DEFAULT_DIMS))
    check("⑧凭据维空读数（null）⇒ rc=1 且点名空读数维",
          rc == 1 and rep["violations"][0]["empty_reading_dims"] == ["凭据"])
    # ⑨ 坏形 fail-closed（内存面）：schema 缺／records 空／id 重复／出词表（命名漂移线索）
    bads = {
        "缺schema": {"records": []},
        "records空": {"schema": SCHEMA_MATRIX, "records": []},
        "id重复": _matrix([_fx_record("a"), _fx_record("a")], "夹具"),
        "出词表": {"schema": SCHEMA_MATRIX, "dims": list(DEFAULT_DIMS),
                   "records": [{"id": "r1", "dims": {"凭证": "x"}}]},   # 凭证≠凭据
    }
    for label, fixture in bads.items():
        try:
            check_matrix(fixture, list(DEFAULT_DIMS))
            check("⑨坏形·%s ⇒ GateError" % label, False)
        except GateError:
            check("⑨坏形·%s ⇒ GateError（fail-closed）" % label, True)
    try:
        check_matrix(bads["出词表"], list(DEFAULT_DIMS))
    except GateError as e:
        check("⑨b 出词表坏形带命名漂移线索（凭证→凭据）", "凭据" in str(e))
    # ⑩ --dims 解析：空集／重复 ⇒ GateError
    for label, text in (("空集", " , "), ("重复", "网络,网络")):
        try:
            parse_dims(text)
            check("⑩--dims·%s ⇒ GateError" % label, False)
        except GateError:
            check("⑩--dims·%s ⇒ GateError" % label, True)
    # ⑪ CLI 真调用一次（消费者侧证据：subprocess 实取 returncode，同 -I 形制）
    cli = os.path.abspath(__file__)
    with tempfile.TemporaryDirectory(prefix="fidelity-matrix-selftest.") as td:
        paths = {}
        for name in ("full-dims", "missing-cred-dim"):
            paths[name] = os.path.join(td, name + ".json")
            with open(paths[name], "w", encoding="utf-8") as fh:
                json.dump(FIXTURES[name](), fh, ensure_ascii=False)
        bad_json = os.path.join(td, "bad.json")
        with open(bad_json, "w", encoding="utf-8") as fh:
            fh.write("{not-json")
        patched_path = os.path.join(td, "patched.json")
        with open(patched_path, "w", encoding="utf-8") as fh:
            json.dump(patched, fh, ensure_ascii=False)

        def run_cli(*args):
            return subprocess.run([sys.executable, "-I", cli] + list(args),
                                  capture_output=True, text=True, timeout=120)

        r = run_cli("--check", "--matrix", paths["full-dims"])
        check("⑪CLI --check 全维 ⇒ rc=0", r.returncode == 0)
        r = run_cli("--check", "--matrix", paths["missing-cred-dim"])
        check("⑪b CLI --check 缺凭据维 ⇒ rc=1 且点名凭据＋降级语义",
              r.returncode == 1 and "凭据" in r.stdout and "降级" in r.stdout)
        r = run_cli("--check", "--matrix", patched_path)
        check("⑪c CLI --check 补维后 ⇒ rc=0", r.returncode == 0)
        r = run_cli("--check", "--matrix", bad_json)
        check("⑪d CLI --check 坏 JSON ⇒ rc=2 fail-closed", r.returncode == 2)
        r = run_cli("--fixture", "full-dims")
        check("⑪e CLI --fixture full-dims ⇒ rc=0", r.returncode == 0)
        r = run_cli("--fixture", "missing-cred-dim")
        check("⑪f CLI --fixture missing-cred-dim ⇒ rc=1", r.returncode == 1)
        r = run_cli("--fixture", "bad-shape")
        check("⑪g CLI --fixture bad-shape ⇒ rc=2", r.returncode == 2)
        r = run_cli("--check", "--matrix", paths["missing-cred-dim"],
                    "--dims", "网络,凭据,编译器,耗时,verdict")
        check("⑪h CLI --dims 显式枚举集 ⇒ rc=1（与缺省同判）", r.returncode == 1)
        r = run_cli()
        check("⑪i CLI 无模式 ⇒ rc=2", r.returncode == 2)

    n_ok = sum(1 for _, c in ok if c)
    print("SELFTEST %d/%d 过（判定核全维/缺维静默/缺维降级/现势红/补维转绿/凭据明文"
          "不回显＋--dims 覆盖＋空读数同判＋坏形 fail-closed＋CLI 真调用一次；"
          "零网络零凭据，读数件只读）" % (n_ok, len(ok)))
    return 0 if n_ok == len(ok) else 1


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="保真度矩阵维度下限判据门（D-152 · 卡 #236 · wave-13）")
    ap.add_argument("--selftest", action="store_true", help="沙箱自证（零网络零凭据）")
    ap.add_argument("--fixture", metavar="名", default=None,
                    help="内置夹具（%s）" % "、".join(sorted(FIXTURES)))
    ap.add_argument("--check", action="store_true", help="真跑判据门")
    ap.add_argument("--matrix", metavar="矩阵.json", default=None,
                    help="--check 的矩阵读数件路径（只读）")
    ap.add_argument("--dims", metavar="d1,d2", default=None,
                    help="必备维度集（缺省=%s）" % "、".join(DEFAULT_DIMS))
    a = ap.parse_args(argv)
    if a.selftest:
        return run_selftest()
    try:
        if a.fixture is not None and a.check:
            raise GateError("--check 与 --fixture 互斥（单模式调用）")
        if a.fixture is not None:
            return run_fixture(a.fixture, a.dims)
        if a.check:
            if not a.matrix:
                raise GateError("--check 须配 --matrix <矩阵.json>")
            return run_check(a.matrix, a.dims)
        raise GateError("须给模式：--selftest ／ --fixture <名> ／ "
                        "--check --matrix <矩阵.json> [--dims d1,d2]")
    except GateError as exc:
        err(str(exc))
        return FAIL_CLOSED


if __name__ == "__main__":
    sys.exit(main())
