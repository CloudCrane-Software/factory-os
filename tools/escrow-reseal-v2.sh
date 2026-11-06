#!/usr/bin/env bash
# escrow-reseal-v2.sh —— 用现役 root token + unseal key 重新封存 owner 的 escrow 托管库（v2 清单格式）
#
# 为什么重做（2026-10-20）：
#   10-10 的 escrow-rebuild.sh 把 manifest 写成 L1 布局
#   （key / 密文 sha256:12 / 密文字节数 / note），而本机 openbao-escrow 工具按
#   L2 布局（key / 日期 / 明文字节数 / 明文 sha256）去读第 2、3 列 → 解出**真** root
#   token 也被判"指纹校验失败"（实得 26B/155… vs 期望 353B/ae）。
#   本脚本产出的 v2 清单同时登记**密文**与**明文**指纹，解封端两道都能真验；
#   另加凭据活性校验（lookup-self 必须 policies 含 root），不再拿密文指纹冒充明文指纹。
#
# 安全设计（沿用 owner 原设计，不改）：
#   - 托管口令只在真终端采集一次（age-pw.py 经 pty 投喂），不回显、不进 argv、不进 history
#   - zip 内所有凭据件都是 age 密文，无明文；明文只在 0600 临时目录里存在，退出时 shred
#   - root token 取回全程不经 stdout、不打印
#   - 旧包以 .pre-reseal-<ts>.bak 保留，不删（可回退）
#
# 用法（gov 上）：
#   ssh root@gov-host.invalid
#   /opt/opch/jit-broker/escrow-reseal-v2.sh
#
# 自检/演练覆盖（默认值即生产值，自检时才覆盖）：
#   SECRETS_DIR  ESCROW_BASE  NEW_ZIP  OFFLINE_COPY  BACKUP_DIR
#   BAO_URL  BAO_CTR  AGE_PW  EXPECT_UNSEAL_FP  SKIP_OFFLINE  ASSUME_YES
set -euo pipefail

SECRETS_DIR="${SECRETS_DIR:-/opt/opch/secrets}"
ESCROW_BASE="${ESCROW_BASE:-/root/.local/share/openbao-escrow}"
NEW_ZIP="${NEW_ZIP:-/root/openbao-key-escrow.zip}"
OFFLINE_COPY="${OFFLINE_COPY:-/root/m0-backups/bao-offline-escrow}"
BACKUP_DIR="${BACKUP_DIR:-/opt/opch/backups/escrow}"
BAO_URL="${BAO_URL:-}"                       # 空=先试宿主机端口，失败再走容器
BAO_CTR="${BAO_CTR:-company-bao-1}"
AGE_PW="${AGE_PW:-/opt/opch/jit-broker/age-pw.py}"
EXPECT_UNSEAL_FP="${EXPECT_UNSEAL_FP:-4985cf5ff3d5}"
SKIP_OFFLINE="${SKIP_OFFLINE:-0}"
ASSUME_YES="${ASSUME_YES:-0}"
ESC_PREFIX="openbao-key-escrow/vault"
TS="$(date +%Y%m%d-%H%M%S)"

die() { printf '[FATAL] %s\n' "$*" >&2; exit 1; }
log() { printf '\n[%s] %s\n' "$(date '+%H:%M:%S')" "$*" >&2; }
ok()  { printf '      ✓ %s\n' "$*" >&2; }
command -v age >/dev/null || die "gov 上没有 age"
[ -x "$AGE_PW" ] || command -v python3 >/dev/null || die "缺 python3（age-pw.py 需要）"
[ -r "$AGE_PW" ] || die "缺 $AGE_PW"
[ -r "$SECRETS_DIR/owner.key" ] || die "缺 $SECRETS_DIR/owner.key"
[ -r "$SECRETS_DIR/root-token.age" ] || die "缺 $SECRETS_DIR/root-token.age"
[ -f "$NEW_ZIP" ] || die "找不到现存托管包 $NEW_ZIP"

WORK="$(mktemp -d)"; chmod 700 "$WORK"; umask 077
cleanup() { for f in "$WORK"/*; do [ -e "$f" ] && shred -u "$f" 2>/dev/null || true; done
           rmdir "$WORK" 2>/dev/null || true; }
trap cleanup EXIT

sha12() { sha256sum "$1" | cut -c1-12; }

# ── 凭据活性：lookup-self 必须 200 且 policies 含 root ─────────────────────────
# bao 的 8200 端口没有映射到宿主机，宿主机 curl 127.0.0.1:8200 必然连不上；
# 容器镜像里也没有 curl —— 容器内查询必须走 bao CLI（escrow-rebuild.sh 的既有做法）。
lookup_policies() {  # $1=token → 打印 policies（查不到则非零退出）
  local t="$1" out="" url="${BAO_URL:-}"
  if [ -z "$url" ]; then
    curl -s -o /dev/null -m 3 http://127.0.0.1:8200/v1/sys/health 2>/dev/null && url="http://127.0.0.1:8200"
  fi
  if [ -n "$url" ]; then
    out=$(curl -s -m 10 -H "X-Vault-Token: $t" "$url/v1/auth/token/lookup-self" 2>/dev/null || true)
  fi
  if [ -z "$out" ] && command -v docker >/dev/null && docker ps --format '{{.Names}}' | grep -qx "$BAO_CTR"; then
    out=$(docker exec -i -e "BAO_TOKEN=$t" "$BAO_CTR" \
            sh -c 'export BAO_ADDR=http://127.0.0.1:8200 VAULT_ADDR=http://127.0.0.1:8200; bao token lookup -format=json' \
            2>/dev/null || true)
    if [ -z "$out" ]; then   # 兜底：万一将来容器里装了 curl
      out=$(docker exec -i -e "BAO_TOKEN=$t" "$BAO_CTR" \
              sh -c 'curl -s -m 10 -H "X-Vault-Token: $BAO_TOKEN" http://127.0.0.1:8200/v1/auth/token/lookup-self' \
              2>/dev/null || true)
    fi
  fi
  [ -n "$out" ] || return 1
  printf '%s' "$out" | python3 -c 'import json,sys
try: print(" ".join(json.load(sys.stdin).get("data",{}).get("policies",[])))
except Exception: sys.exit(1)'
}
assert_live_root() {  # $1=token → 打印 policies；失败只回报原因，由调用方统一 die
  local pol
  if ! pol=$(lookup_policies "$1"); then
    printf '      查不到 bao（宿主机端口未映射 + 容器内 bao CLI 查询失败）\n' >&2
    return 1
  fi
  if ! printf '%s' "$pol" | tr ' ' '\n' | grep -qx root; then
    printf '      这份 token 不是 root（policies=[%s]）\n' "$pol" >&2
    return 1
  fi
  printf '%s' "$pol"
}

# ── 1) 取现役 root ──────────────────────────────────────────────────────────
log "[1/7] 取现役 root token（$SECRETS_DIR/root-token.age + owner.key）"
age -d -i "$SECRETS_DIR/owner.key" "$SECRETS_DIR/root-token.age" > "$WORK/root.plain" \
  || die "root 解密失败"
[ -s "$WORK/root.plain" ] || die "root 为空"
ROOT_SIZE=$(stat -c%s "$WORK/root.plain"); ROOT_FP=$(sha12 "$WORK/root.plain")
ok "root ${ROOT_SIZE}B sha256:${ROOT_FP}…（值不打印）"

# ── 2) 活性校验：绝不封存废钥匙 ──────────────────────────────────────────────
log "[2/7] 校验 root 活性（lookup-self 必须 policies 含 root）"
if ! ROOT_POL=$(assert_live_root "$(cat "$WORK/root.plain")"); then
  die "root 活性校验不通过，拒绝封存一把废钥匙"
fi
ok "lookup-self 通过，policies=$ROOT_POL"

# ── 3) 取 unseal key ───────────────────────────────────────────────────────
log "[3/7] 取 unseal key"
UKSRC=""
for c in "$ESCROW_BASE/.unseal-key" "$SECRETS_DIR/unseal-key" "$SECRETS_DIR/unseal-key.plain"; do
  [ -r "$c" ] && { UKSRC="$c"; break; }
done
if [ -z "$UKSRC" ]; then
  cat >&2 <<'HINT'
  盘上已无明文 unseal key（2026-10-20 起全部 shred，只保留 age 密文）。
  正确取用顺序：
    1) 在任一持包机上执行  openbao-escrow unlock-unseal   # 你的托管口令，从 escrow 解出
    2) 再执行本脚本
  gov 上另有 /opt/opch/secrets/unseal-key.age（owner.key 身份加密），
  edge-recovery.sh 走那条路径，不依赖本脚本。
HINT
  die "找不到明文 unseal key（试过 $ESCROW_BASE/.unseal-key、$SECRETS_DIR/unseal-key）"
fi
cp "$UKSRC" "$WORK/unseal.plain"; chmod 600 "$WORK/unseal.plain"
UK_SIZE=$(stat -c%s "$WORK/unseal.plain"); UK_FP=$(sha12 "$WORK/unseal.plain")
if [ "$UK_SIZE" != 44 ] || [ "${UK_FP:0:12}" != "$EXPECT_UNSEAL_FP" ]; then
  [ "$ASSUME_YES" = 1 ] || die "unseal key 与登记不符（${UK_SIZE}B sha256:${UK_FP}… ≠ 期望 44B/${EXPECT_UNSEAL_FP}）；确认无误可 ASSUME_YES=1 重跑"
fi
ok "unseal ${UK_SIZE}B sha256:${UK_FP}… 来源=$UKSRC"

# ── 4) owner 输一次口令，封存两件 ───────────────────────────────────────────
log "[4/7] 请 owner 输入托管口令（两件共用同一个口令，本次只输这一次）"
printf '%s\n' \
  "age -p -a -o '$WORK/root-token.age' '$WORK/root.plain'" \
  "age -p -a -o '$WORK/unseal-key.age' '$WORK/unseal.plain'" \
  | python3 "$AGE_PW" --batch "  托管口令（不回显）：" \
  || die "封存失败（口令两次输入不一致？）"
[ -s "$WORK/root-token.age" ] && [ -s "$WORK/unseal-key.age" ] || die "密文未生成"
ok "两件已封存：root-token.age $(stat -c%s "$WORK/root-token.age")B / unseal-key.age $(stat -c%s "$WORK/unseal-key.age")B"

# ── 5) 组装 v2 包：密文 + 明文双指纹 ───────────────────────────────────────
log "[5/7] 组装 v2 托管包（保留原有非 vault 成员逐字节不变）"
mkdir -p "$WORK/pkg/$ESC_PREFIX"
cp "$WORK/root-token.age" "$WORK/pkg/$ESC_PREFIX/root-token.age"
cp "$WORK/unseal-key.age" "$WORK/pkg/$ESC_PREFIX/unseal-key.age"
python3 - "$WORK/pkg/$ESC_PREFIX" "$WORK" <<'PY'
import sys, os, hashlib, datetime
d, work = sys.argv[1], sys.argv[2]
now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
rows = ["# key\tsealed-utc\tplain-size\tplain-sha256-12\tcipher-size\tcipher-sha256-12\tnote"]
for key, pfile in (("root-token", os.path.join(work, "root.plain")),
                   ("unseal-key", os.path.join(work, "unseal.plain"))):
    pt = open(pfile, "rb").read()
    ct = open(os.path.join(d, key + ".age"), "rb").read()
    rows.append("\t".join([key, now, f"{len(pt)}B", hashlib.sha256(pt).hexdigest()[:12],
                           str(len(ct)), hashlib.sha256(ct).hexdigest()[:12], "age密文(owner口令)"]))
open(os.path.join(d, "manifest.tsv"), "w", encoding="utf-8").write("\n".join(rows) + "\n")
print("\n".join(rows), file=sys.stderr)
PY
# 旧包里 vault/ 之外的成员逐字节保留（历史说明、工具等）
python3 - "$NEW_ZIP" "$WORK/pkg" <<'PY'
import sys, os, zipfile, shutil
src, pkg = sys.argv[1], sys.argv[2]
zi = zipfile.ZipFile(src)
prefix = os.path.dirname('openbao-key-escrow/vault')
for info in zi.infolist():
    name = info.filename
    if name.endswith('/'):
        continue
    if name.startswith('openbao-key-escrow/vault/'):
        continue
    dst = os.path.join(pkg, name)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, 'wb') as fh:
        fh.write(zi.read(name))
    print(f'  保留成员: {name}', file=sys.stderr)
zi.close()
PY
( cd "$WORK/pkg" && zip -qr "$WORK/new.zip" . ) || die "打包失败"

# ── 6) 往返自验：解包 → 用同一口令解密 → 比对 → 查活性 ────────────────────
log "[6/7] 往返自验（解包→解密→比对→lookup）"
python3 - "$WORK/new.zip" "$WORK" <<'PY'
import sys, zipfile
z = zipfile.ZipFile(sys.argv[1])
for key in ("root-token", "unseal-key"):
    raw = [n for n in z.namelist() if n.endswith(f"vault/{key}.age")][0]
    open(f"{sys.argv[2]}/v-{key}.age", "wb").write(z.read(raw))
PY
printf '%s\n' \
  "age -d -o '$WORK/v-root.plain' '$WORK/v-root-token.age'" \
  "age -d -o '$WORK/v-unseal.plain' '$WORK/v-unseal-key.age'" \
  | python3 "$AGE_PW" --batch "  托管口令（不回显，用于往返自验）：" \
  || die "往返自验解不开（口令与封存时不一致？）"
cmp -s "$WORK/v-root.plain"   "$WORK/root.plain"   || die "往返：root 内容不一致"
cmp -s "$WORK/v-unseal.plain" "$WORK/unseal.plain" || die "往返：unseal 内容不一致"
if ! VR_POL=$(assert_live_root "$(cat "$WORK/v-root.plain")"); then
  die "往返：解出的 root 查不到或不是 root"
fi
ok "root 往返一致 + lookup-self policies=$VR_POL"
ok "unseal 往返一致"
# 自检：manifest 双指纹必须同时对得上密文与明文
python3 - "$WORK/new.zip" "$WORK" <<'PY'
import sys, os, zipfile, hashlib
z = zipfile.ZipFile(sys.argv[1]); work = sys.argv[2]
PLAIN = {"root-token": "v-root.plain", "unseal-key": "v-unseal.plain"}
m = [n for n in z.namelist() if n.endswith('manifest.tsv')][0]
for line in z.read(m).decode('utf-8-sig').splitlines():
    if line.lstrip().startswith('#'):
        continue
    p = line.split('\t')
    ct = z.read([n for n in z.namelist() if n.endswith(f"vault/{p[0]}.age")][0])
    pt = open(os.path.join(work, PLAIN[p[0]]), 'rb').read()
    assert hashlib.sha256(ct).hexdigest()[:12] == p[5] and len(ct) == int(p[4]), f'{p[0]} 密文指纹不符'
    assert hashlib.sha256(pt).hexdigest()[:12] == p[3] and len(pt) == int(p[2].rstrip('B')), f'{p[0]} 明文指纹不符'
    print(f"  自检 {p[0]}: 密文 {p[4]}B/{p[5]} + 明文 {p[2]}/{p[3]} 双指纹一致", file=sys.stderr)
PY

# ── 7) 落盘 + 备份 + 同步副本 ─────────────────────────────────────────────
log "[7/7] 落盘并同步副本"
BAK="$NEW_ZIP.pre-reseal-$TS.bak"
cp -p "$NEW_ZIP" "$BAK"; chmod 600 "$BAK"
install -m 600 "$WORK/new.zip" "$NEW_ZIP.new"; mv "$NEW_ZIP.new" "$NEW_ZIP"
ok "新包   $NEW_ZIP ($(stat -c%s "$NEW_ZIP")B sha256:$(sha12 "$NEW_ZIP")…)"
ok "旧包   $BAK（保留可回退）"

ln -sf "$NEW_ZIP" "$ESCROW_BASE/openbao-key-escrow.zip"
ok "主位置软链 $ESCROW_BASE/openbao-key-escrow.zip → $NEW_ZIP"

mkdir -p "$BACKUP_DIR"
install -m 600 "$NEW_ZIP" "$BACKUP_DIR/openbao-key-escrow-$TS.zip"
ok "时点备份 $BACKUP_DIR/openbao-key-escrow-$TS.zip"

if [ "$SKIP_OFFLINE" != 1 ] && [ -d "$OFFLINE_COPY" ]; then
  install -m 600 "$NEW_ZIP" "$OFFLINE_COPY/openbao-key-escrow-$TS.zip"
  ok "离机副本 $OFFLINE_COPY/openbao-key-escrow-$TS.zip（旧的 $OFFLINE_COPY/openbao-key-escrow.zip 保留，未覆盖）"
fi

# 取回件同步为现行值，供立刻使用
install -m 600 "$WORK/root.plain" "$ESCROW_BASE/.root-token"
ok "取回件 $ESCROW_BASE/.root-token（0600，已为现行有效值）"

# 轮换记录：写在包外，不改包结构
cat > "$NEW_ZIP.reseal-$TS.txt" <<EOF
escrow 重新封存记录 $TS
起因：2026-10-20 发现本机 openbao-escrow 按 L2 布局读 manifest，而 10-10 重建的包是
      L1 布局（登记的是密文指纹）→ 解出真 root token 也被判"指纹校验失败"。
处理：用现役 root token（${ROOT_SIZE}B sha256:${ROOT_FP}…，lookup-self policies=$ROOT_POL）
      与 unseal key（${UK_SIZE}B sha256:${UK_FP}…）重新 age 封存，manifest 升到 v2 布局
      （密文与明文双指纹），并经"解包→解密→比对→lookup"往返自验。
旧包：$BAK
EOF
chmod 600 "$NEW_ZIP.reseal-$TS.txt"

log "重新封存完成"
cat >&2 <<EOF

  新包        $NEW_ZIP
  旧包备份    $BAK
  轮换记录    $NEW_ZIP.reseal-$TS.txt
  zip 指纹    sha256:$(sha12 "$NEW_ZIP")…

请到各副本机验证（都需要你的托管口令）：
  1) openbao-escrow verify      # 不需要口令：验包完整性（密文指纹）
  2) openbao-escrow unlock      # 需要口令：解密 → 明文指纹 → 活性(policies=root) 三道校验
  3) 满意后 openbao-escrow lock  # shred 销毁取回件
EOF
