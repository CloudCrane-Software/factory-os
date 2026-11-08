#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""openBao CLI 垫片·D-143 四态 fail-loud 仓内镜像件——factory-os #259（wave-18）。

正本关系（如实注记）：
  · 活体面＝gov 宿主在役垫片 /usr/local/bin/bao（部署窗通道，2026-11-08 06:11-06:18
    CST 已按裁决 #29 手术；回滚件 /root/bao-wrapper.bak-20261108T0612Z-d143，824B
    原件）——本卡不触碰活体，部署窗不在作用域。
  · 仓内正本缺位如实注记（台账 D-143 锚补全段原文口径）：本件为仓内镜像件——只含
    判定逻辑，不含任何凭据真值与部署路径真值。与活体面的差异点＝底层二进制与 root
    兜底凭据源均经 env 注入（BAO_SHIM_BIN / BAO_SHIM_ROOT_TOKEN_FILE），缺则
    fail-loud exit 3，不内嵌、不猜测。

四态语义（逐字对齐裁决日志 #29「D-143 执行读数回填」，ESC-14 闭环）：
  ① BAO_TOKEN 与 VAULT_TOKEN 同设 ⇒ exit 3 拒跑（env 凭据歧义）。
  ② 仅 VAULT_TOKEN 在场 ⇒ exit 3 拒跑并指路 export BAO_TOKEN——重考官亲历的
    「静默升 root」陷阱自本态摘除。
  ③ 双空 ⇒ 原语义兜底 root＋stderr 明示（行为保持，管理路径专用；旧版静默兜底，
    本版必打印明示行后再走 root 面）。
  ④ 显式 BAO_TOKEN ⇒ 与旧版逐字节等价（env 原样直通、不加一行输出；裁决 #29
    测量口径：version 直通）。
  卡面题述「BAO_TOKEN 缺失⇒显式报错退出、禁静默兜底 root」按裁决 #29 终态落为
  四态：「禁静默」落在 ② 摘陷阱＋③ stderr 明示；③ 保留兜底 root（管理路径专用），
  即禁的是静默、不是兜底本身——镜像件如实注记此口径，不回改卡面。

【出口】态③④＝底层命令 rc 直通；态①②与镜像件 fail-loud 边（底层不可达 / root
  兜底凭据源缺或空）＝exit 3。态④ execve 前零输出零 env 改写（逐字节等价）。

【凭据纪律】零凭据：本件与 --selftest 均不含真值；selftest 底层桩只回显凭据的
  sha256 前 8 位指纹（对齐仓内 recon-gate 族凭据纪律——值绝不读取打印），零网络。

【边界】stdin 契约腿（ESC-39）不在裁决 #29 范围，归身份宪章 D11/G-9，镜像件同边
  不含。VAULT_TOKEN 自动映射通道本裁未启用：态②一律拒跑指路，不做自动映射（台账
  修复方向「显式映射或显式拒绝」取「显式拒绝」边）。

用法：
  python3 -I tools/bao-shim.py <bao 参数…>    # 态由 env 在场情况决定（见上四态）
  python3 -I tools/bao-shim.py --selftest     # 四态夹具自证（零网络零凭据）
"""
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile

BAO_KEY_NAME = "BAO_TOKEN"          # 态④直通键（与旧垫片同名同语义）
VAULT_KEY_NAME = "VAULT_TOKEN"      # 旧垫片忽略此键——本版歧义面显式化
BIN_ENV_NAME = "BAO_SHIM_BIN"      # 底层二进制注入位（selftest 桩/部署面覆写）
ROOT_FILE_ENV_NAME = "BAO_SHIM_ROOT_TOKEN_FILE"  # 态③ root 兜底凭据源（部署面注入）

RC_OK, RC_REFUSE = 0, 3

STATE_AMBIG = "S1-ambig"
STATE_VAULT_ONLY = "S2-vault-only"
STATE_BOTH_EMPTY = "S3-both-empty"
STATE_EXPLICIT = "S4-explicit"

MSG_AMBIG = ("[bao-shim] 态① BAO_TOKEN 与 VAULT_TOKEN 同设：env 凭据歧义，拒跑"
             "（exit 3）——请只保留其一后重试")
MSG_VAULT_ONLY = ("[bao-shim] 态② 仅 VAULT_TOKEN 在场而 BAO_TOKEN 缺席：拒跑（exit 3）"
                  "——旧垫片静默兜底 root 陷阱已摘除；请显式 export BAO_TOKEN"
                  "（可映射 VAULT_TOKEN 同源值）后重试")
MSG_FALLBACK = ("[bao-shim] 态③ BAO_TOKEN 与 VAULT_TOKEN 均空：按原语义兜底 root 身份，"
                "本行即 stderr 明示（行为保持，管理路径专用——旧版的静默兜底不再静默）")
MSG_BIN_MISSING = ("[bao-shim] 底层 bao 二进制不可达（%s）：exit 3 fail-loud，"
                   "不静默降级")
MSG_ROOT_SRC_MISSING = ("[bao-shim] 态③ root 兜底凭据源缺失或为空（%s 未提供/不可读）："
                        "exit 3 fail-loud——镜像件零凭据，不内嵌不猜测部署路径"
                        "（活体面凭据源走 gov 部署窗，不在本卡作用域）")
MSG_EXEC_FAIL = "[bao-shim] exec 底层失败（%s）：%s —— exit 3 fail-loud"


def err(msg):
    sys.stderr.write(msg + "\n")


def sha8(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


# ---- 判定核（纯函数；--selftest 与真跑共用） -------------------------------------
def decide(bao_set, vault_set):
    """四态判定（裁决 #29 逐字对齐）。

    返回 (态号, 拒跑rc或None, 态注记或None)：拒跑rc 非 None ⇒ 拒跑态；
    None ⇒ 放行态（态③注记=stderr 明示行；态④注记=None=零增写）。
    """
    if bao_set and vault_set:
        return STATE_AMBIG, RC_REFUSE, MSG_AMBIG
    if vault_set and not bao_set:
        return STATE_VAULT_ONLY, RC_REFUSE, MSG_VAULT_ONLY
    if bao_set:
        return STATE_EXPLICIT, None, None
    return STATE_BOTH_EMPTY, None, MSG_FALLBACK


def resolve_bin():
    """底层二进制解析：BIN_ENV_NAME 注入位优先，缺省查 PATH 上的 bao。"""
    return shutil.which(os.environ.get(BIN_ENV_NAME, "bao"))


def read_root_source():
    """态③ root 兜底凭据源：ROOT_FILE_ENV_NAME 指文件，读入去首尾空白。

    镜像件零凭据：源未提供/不可读/读后为空 ⇒ None（fail-loud，绝不伪造）。
    """
    path = os.environ.get(ROOT_FILE_ENV_NAME, "")
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            val = fh.read().strip()
    except OSError:
        return None
    return val or None


def run(argv):
    env = os.environ
    state, refuse_rc, note = decide(bool(env.get(BAO_KEY_NAME)),
                                    bool(env.get(VAULT_KEY_NAME)))
    if refuse_rc is not None:          # 态①②：拒跑，底层不可达不关切
        err(note)
        return refuse_rc
    bin_path = resolve_bin()
    if not bin_path:
        err(MSG_BIN_MISSING % os.environ.get(BIN_ENV_NAME, "bao"))
        return RC_REFUSE
    if state == STATE_BOTH_EMPTY:      # 态③：先 stderr 明示，再兜底 root
        err(note)
        root_val = read_root_source()
        if root_val is None:
            err(MSG_ROOT_SRC_MISSING % ROOT_FILE_ENV_NAME)
            return RC_REFUSE
        child = dict(env)
        child.pop(BIN_ENV_NAME, None)        # 垫片内部控制位不泄入底层
        child.pop(ROOT_FILE_ENV_NAME, None)
        child[BAO_KEY_NAME] = root_val
        try:
            os.execve(bin_path, [bin_path] + argv, child)
        except OSError as exc:
            err(MSG_EXEC_FAIL % (bin_path, exc))
            return RC_REFUSE
    # 态④：显式 BAO_TOKEN——与旧版逐字节等价：env 原样直通、零输出
    try:
        os.execve(bin_path, [bin_path] + argv, env)
    except OSError as exc:
        err(MSG_EXEC_FAIL % (bin_path, exc))
        return RC_REFUSE
    return RC_OK  # 不可达（execve 成功即进程替换）


# ---- selftest 底层桩：只回显 argv 与凭据 sha8 指纹（值绝不打印） ------------------
STUB_SRC = '''#!/usr/bin/env python3
import hashlib, os, sys
cred = os.environ.get("BAO_TOKEN", "")
print("stub_argv=%r" % (sys.argv[1:],))
print("stub_cred_fp=%s" % hashlib.sha256(cred.encode("utf-8")).hexdigest()[:8])
'''


def run_selftest():
    """四态夹具真跑（子进程＋底层桩）：断言逐条 rc 与 stderr 指路文本＋边例 fail-loud。"""
    self_path = os.path.abspath(__file__)
    cases = []   # (名, 期望rc, 实得rc, 细节断言结果)
    with tempfile.TemporaryDirectory() as td:
        stub_path = os.path.join(td, "bao-stub.py")
        with open(stub_path, "w", encoding="utf-8") as fh:
            fh.write(STUB_SRC)
        os.chmod(stub_path, 0o755)
        root_src_path = os.path.join(td, "root-src.txt")
        with open(root_src_path, "w", encoding="utf-8") as fh:
            fh.write("root-t1\n")     # 夹具哑值（零凭据纪律：非真值）

        base = dict(os.environ)       # 父面在场的同族键一律洗净，态由夹具注入
        for k in (BAO_KEY_NAME, VAULT_KEY_NAME, BIN_ENV_NAME, ROOT_FILE_ENV_NAME):
            base.pop(k, None)

        def spawn(env, args):
            return subprocess.run([sys.executable, "-I", self_path] + list(args),
                                  env=env, capture_output=True)

        # 态①：同设 ⇒ rc=3 歧义拒跑，stderr 含歧义报错，底层未达
        env1 = dict(base)
        env1[BAO_KEY_NAME] = "t1"
        env1[VAULT_KEY_NAME] = "v1"
        env1[BIN_ENV_NAME] = stub_path
        r1 = spawn(env1, ("token", "lookup"))
        s1 = r1.stderr.decode("utf-8", "replace")
        ok1 = ("歧义" in s1) and (r1.stdout == b"")
        cases.append(("态①双设歧义拒跑", 3, r1.returncode, ok1))

        # 态②：仅 VAULT_TOKEN ⇒ rc=3 拒跑并指路 export BAO_TOKEN，底层未达
        env2 = dict(base)
        env2[VAULT_KEY_NAME] = "v1"
        env2[BIN_ENV_NAME] = stub_path
        r2 = spawn(env2, ("token", "lookup"))
        s2 = r2.stderr.decode("utf-8", "replace")
        ok2 = ("export BAO_TOKEN" in s2) and ("兜底" in s2) and (r2.stdout == b"")
        cases.append(("态②仅VAULT拒跑指路", 3, r2.returncode, ok2))

        # 态③：双空 ⇒ 兜底 root＋stderr 明示；底层收到 root 源凭据（指纹对账）
        env3 = dict(base)
        env3[BIN_ENV_NAME] = stub_path
        env3[ROOT_FILE_ENV_NAME] = root_src_path
        r3 = spawn(env3, ("token", "lookup"))
        s3 = r3.stderr.decode("utf-8", "replace")
        want3 = ("stub_cred_fp=%s" % sha8("root-t1")).encode("utf-8")
        ok3 = ("兜底 root" in s3) and ("明示" in s3) and (want3 in r3.stdout)
        cases.append(("态③双空兜底root明示", 0, r3.returncode, ok3))

        # 态④：显式 BAO_TOKEN ⇒ 与旧版逐字节等价：stderr 零增写、env 直通（指纹对账）
        env4 = dict(base)
        env4[BAO_KEY_NAME] = "scoped-t1"
        env4[BIN_ENV_NAME] = stub_path
        r4 = spawn(env4, ("version",))
        want4 = ("stub_cred_fp=%s" % sha8("scoped-t1")).encode("utf-8")
        ok4 = (r4.stderr == b"") and (want4 in r4.stdout) \
            and (b"stub_argv=['version']" in r4.stdout)
        cases.append(("态④显式直通零增写", 0, r4.returncode, ok4))

        # 边例A：态④底层不可达 ⇒ exit 3 fail-loud，不静默降级
        envA = dict(base)
        envA[BAO_KEY_NAME] = "t1"
        envA[BIN_ENV_NAME] = os.path.join(td, "no-such-bin")
        rA = spawn(envA, ("version",))
        sA = rA.stderr.decode("utf-8", "replace")
        okA = "不可达" in sA
        cases.append(("边例④底层缺位红", 3, rA.returncode, okA))

        # 边例B：态③凭据源缺 ⇒ exit 3 fail-loud（明示行已打、底层未达）
        envB = dict(base)
        envB[BIN_ENV_NAME] = stub_path
        envB[ROOT_FILE_ENV_NAME] = os.path.join(td, "missing-src.txt")
        rB = spawn(envB, ("version",))
        sB = rB.stderr.decode("utf-8", "replace")
        okB = ("凭据源缺失" in sB) and ("兜底" in sB) and (rB.stdout == b"")
        cases.append(("边例③凭据源缺红", 3, rB.returncode, okB))

    fails = [c for c in cases if c[1] != c[2] or not c[3]]
    for name, want, got, detail_ok in cases:
        print("  自证·%s: 期望rc=%s 实得rc=%s 文本/指纹断言%s %s"
              % (name, want, got, "过" if detail_ok else "败",
                 "OK" if (want == got and detail_ok) else "FAIL"))
    if fails:
        print("自证 %d 例不符：%r" % (len(fails), [(f[0], f[1], f[2], f[3]) for f in fails]))
        return 1
    print("自证 %d 例全过（四态 rc/stderr 对齐裁决 #29＋fail-loud 边例；零网络零凭据）"
          % len(cases))
    return 0


def main(argv):
    if "--selftest" in argv:
        return run_selftest()
    return run(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
