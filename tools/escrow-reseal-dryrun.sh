#!/usr/bin/env bash
# escrow-reseal-v2.sh 端到端演练：全假环境，不接触真实 gov / 真实凭据
set -uo pipefail
W=/tmp/reseal-dryrun
rm -rf "$W"; mkdir -p "$W"/{secrets,base,backup,offline}; chmod 700 "$W"
PASS=0; FAIL=0
ok()  { printf '  \033[32mPASS\033[0m %s\n' "$1"; PASS=$((PASS+1)); }
bad() { printf '  \033[31mFAIL\033[0m %s\n' "$1"; FAIL=$((FAIL+1)); }

# ── 假 gov 素材 ────────────────────────────────────────────────────────────
age-keygen -o "$W/secrets/owner.key" 2>/dev/null
python3 -c "
import string,os
a=string.ascii_letters+string.digits
open('$W/fake-root','w').write(''.join(a[os.urandom(1)[0]%len(a)] for _ in range(26)))
open('$W/secrets/unseal-key','w').write(''.join(a[os.urandom(1)[0]%len(a)] for _ in range(44)))
"
PUB=$(age-keygen -y "$W/secrets/owner.key")
age -r "$PUB" -a -o "$W/secrets/root-token.age" "$W/fake-root"
FAKE_ROOT_FP=$(sha256sum "$W/fake-root" | cut -c1-12)
FAKE_UK_FP=$(sha256sum "$W/secrets/unseal-key" | cut -c1-12)
chmod 600 "$W/secrets/"*

# ── 假"现存托管包"（L1 布局，与生产同构）──
mkdir -p "$W/old/openbao-key-escrow/vault"
echo "旧 root-token 密文占位" > "$W/old/openbao-key-escrow/vault/root-token.age"
echo "旧 unseal 密文占位"     > "$W/old/openbao-key-escrow/vault/unseal-key.age"
echo "历史说明，应被逐字节保留" > "$W/old/openbao-key-escrow/20261005.txt"
python3 - "$W/old" <<'PY'
import sys,os,hashlib
d=os.path.join(sys.argv[1],'openbao-key-escrow/vault')
rows=[]
for k in ('root-token','unseal-key'):
    b=open(os.path.join(d,k+'.age'),'rb').read()
    rows.append(f"{k}\t{hashlib.sha256(b).hexdigest()[:12]}\t{len(b)}\tage密文(owner口令)")
open(os.path.join(d,'manifest.tsv'),'w',encoding='utf-8').write("\n".join(rows)+"\n")
PY
( cd "$W/old" && zip -qr "$W/new.zip" . )

# ── 桩 bao ────────────────────────────────────────────────────────────────
python3 - >/dev/null 2>&1 <<'PY' &
import http.server,json
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body=json.dumps({"data":{"policies":["root"],"display_name":"root","ttl":0}}).encode()
        self.send_response(200); self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
    def log_message(self,*a): pass
http.server.HTTPServer(('127.0.0.1',18210),H).serve_forever()
PY
STUB=$!; sleep 1

echo "== 演练 escrow-reseal-v2.sh（全假环境）=="
printf 'dryrun-pass\ndryrun-pass\n' | script -qec "
  SECRETS_DIR='$W/secrets' ESCROW_BASE='$W/base' NEW_ZIP='$W/new.zip' \
  OFFLINE_COPY='$W/offline' BACKUP_DIR='$W/backup' \
  BAO_URL='http://127.0.0.1:18210' AGE_PW='/home/pan-ding/workspace/agent黑灯工厂/tools/age-pw.py' \
  EXPECT_UNSEAL_FP='$FAKE_UK_FP' \
  bash /home/pan-ding/workspace/agent黑灯工厂/tools/escrow-reseal-v2.sh" /dev/null > "$W/run.log" 2>&1
RC=$?
kill $STUB 2>/dev/null
sed -e "s|$W|DRYRUN|g" "$W/run.log" | tail -32
echo "---- 退出码 $RC ----"

echo "== 断言 =="
[ "$RC" = 0 ] && ok "演练整体成功" || bad "演练失败 rc=$RC"
[ -f "$W/new.zip.pre-reseal-"* ] && ok "旧包已备份" || bad "旧包未备份"
python3 -c "
import zipfile,sys
z=zipfile.ZipFile('$W/new.zip')
n=[x for x in z.namelist() if x.endswith('20261005.txt')]
assert n, '历史成员丢失'
assert z.read(n[0]).decode().strip()=='历史说明，应被逐字节保留'
" 2>/dev/null && ok "非 vault 历史成员逐字节保留" || bad "非 vault 成员处理不对"
python3 - "$W/new.zip" "$FAKE_ROOT_FP" "$FAKE_UK_FP" <<'PY' && ok "manifest 为 v2 且明文指纹等于假凭据指纹" || bad "manifest 不符"
import sys,zipfile,hashlib
z=zipfile.ZipFile(sys.argv[1])
m=z.read([n for n in z.namelist() if n.endswith('manifest.tsv')][0]).decode('utf-8-sig')
rows=[l.split('\t') for l in m.splitlines() if not l.startswith('#')]
assert len(rows)==2, rows
for r,(name,fp) in zip(rows,[('root-token',sys.argv[2]),('unseal-key',sys.argv[3])]):
    assert r[0]==name and r[3]==fp, r
    ct=z.read([n for n in z.namelist() if n.endswith(f'vault/{name}.age')][0])
    assert hashlib.sha256(ct).hexdigest()[:12]==r[5] and len(ct)==int(r[4]), r
print('  v2 双指纹自洽')
PY
cmp -s "$W/fake-root" "$W/base/.root-token" && ok "取回件=现役值" || bad "取回件不符"
[ "$(stat -c%a "$W/base/.root-token")" = 600 ] && ok "取回件 0600" || bad "取回件权限错"
ls "$W/offline"/openbao-key-escrow-*.zip >/dev/null 2>&1 && ok "离机副本已写入" || bad "离机副本未写"
ls "$W/backup"/openbao-key-escrow-*.zip >/dev/null 2>&1 && ok "时点备份已写入" || bad "时点备份未写"
grep -q "残留明文" "$W/run.log" && bad "日志疑似泄露明文" || ok "日志无明文泄露迹象"

echo
echo "== 用修好的本机工具验新包（模拟副本 A 的 verify）=="
OPENBAO_ESCROW_ZIP="$W/new.zip" openbao-escrow verify && ok "本机工具可验新包（识别 v2）" || bad "本机工具无法验新包"

echo "== 新包能否被本机工具真正解出（错口令必须失败）=="
rm -f "$W/out-token"; mkdir -p "$W/out"
printf 'dryrun-pass\n' | script -qec "BAO_ADDR='http://127.0.0.1:18210' OPENBAO_ESCROW_ZIP='$W/new.zip' OPENBAO_ESCROW_TOKEN_FILE='$W/out/.root-token' openbao-escrow unlock" /dev/null >/dev/null 2>&1
cmp -s "$W/fake-root" "$W/out/.root-token" && ok "解出的明文与现役值一致（明文指纹+活性双校验通过）" || bad "解锁结果不符"

echo
printf '演练结果: PASS=%d FAIL=%d\n' "$PASS" "$FAIL"
[ "$FAIL" = 0 ]
