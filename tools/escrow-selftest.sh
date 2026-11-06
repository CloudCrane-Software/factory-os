#!/usr/bin/env bash
# escrow 工具自检（合成包 + 桩 bao，不接触真实托管包与真实口令）
set -uo pipefail
T=/tmp/escrow-selftest
PASS=0; FAIL=0
ok()   { printf '  \033[32mPASS\033[0m %s\n' "$1"; PASS=$((PASS+1)); }
bad()  { printf '  \033[31mFAIL\033[0m %s\n' "$1"; FAIL=$((FAIL+1)); }
chk()  { if [ "$2" = "$3" ]; then ok "$1"; else bad "$1 (期望[$3] 实际[$2])"; fi; }

rm -rf "$T"; mkdir -p "$T/pkg/openbao-key-escrow/vault"; chmod 700 "$T"

# 假凭据：26 字节，模仿真 root token 的长度（非真实 token）
python3 -c "import os,sys,string; a=string.ascii_letters+string.digits; open('$T/plain','w').write(''.join(a[os.urandom(1)[0]%len(a)] for _ in range(26)))"
python3 -c "import os,sys,string; a=string.ascii_letters+string.digits; open('$T/uk-plain','w').write(''.join(a[os.urandom(1)[0]%len(a)] for _ in range(44)))"
[ "$(stat -c%s "$T/plain")" = 26 ] || { echo "假凭据长度不对: $(stat -c%s "$T/plain")"; exit 1; }

# 用口令封存（age 从 tty 读口令，用 script 提供 pty）
printf 'test-pass-123\ntest-pass-123\n' | script -qec \
  "age -p -a -o '$T/pkg/openbao-key-escrow/vault/root-token.age' '$T/plain'" /dev/null >/dev/null 2>&1
printf 'test-pass-123\ntest-pass-123\n' | script -qec \
  "age -p -a -o '$T/pkg/openbao-key-escrow/vault/unseal-key.age' '$T/uk-plain'" /dev/null >/dev/null 2>&1
chmod 600 "$T/pkg/openbao-key-escrow/vault/"*.age

# v2 manifest：密文 + 明文双指纹
python3 - "$T/pkg/openbao-key-escrow/vault" "$T" <<'PY'
import sys,os,hashlib,datetime
d,t=sys.argv[1],sys.argv[2]; now=datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
rows=["# key\tsealed-utc\tplain-size\tplain-sha256-12\tcipher-size\tcipher-sha256-12\tnote"]
for key,pfile in (("root-token",os.path.join(t,'plain')),("unseal-key",os.path.join(t,'uk-plain'))):
    pt=open(pfile,'rb').read()
    ct=open(os.path.join(d,key+'.age'),'rb').read()
    rows.append("\t".join([key,now,f"{len(pt)}B",hashlib.sha256(pt).hexdigest()[:12],
                           str(len(ct)),hashlib.sha256(ct).hexdigest()[:12],"age密文(owner口令)"]))
open(os.path.join(d,'manifest.tsv'),'w',encoding='utf-8').write("\n".join(rows)+"\n")
PY

( cd "$T/pkg" && zip -qr "$T/test.zip" . )
export OPENBAO_ESCROW_ZIP="$T/test.zip"
export OPENBAO_ESCROW_TOKEN_FILE="$T/out/.root-token"
export OPENBAO_ESCROW_UNSEAL_FILE="$T/out/.unseal-key"
mkdir -p "$T/out"

echo "== 1) verify（无口令，验包完整性）=="
if openbao-escrow verify >"$T/v1.log" 2>&1; then ok "verify 通过"; else bad "verify 失败"; cat "$T/v1.log"; fi
grep -q 'root-token 布局=v2' "$T/v1.log" && ok "识别 v2 布局" || bad "未识别 v2 布局"

echo "== 2) 篡改密文 → verify 必须失败 =="
cp "$T/test.zip" "$T/tampered.zip"
python3 - <<'PY'
import zipfile,shutil
src='/tmp/escrow-selftest/test.zip'; dst='/tmp/escrow-selftest/tampered.zip'
zi=zipfile.ZipFile(src)
with zipfile.ZipFile(dst,'w') as zo:
    for i in zi.infolist():
        d=zi.read(i.filename)
        if i.filename.endswith('root-token.age'):
            d=bytes([d[0]^0xFF])+d[1:]
        zo.writestr(i,d)
PY
if OPENBAO_ESCROW_ZIP="$T/tampered.zip" openbao-escrow verify >"$T/v2.log" 2>&1; then
  bad "篡改后 verify 竟然通过"
else ok "篡改后 verify 拒绝（$(grep -c '包完整性失败' "$T/v2.log") 处失败）"; fi

echo "== 3) 篡改包 unlock → 必须拒绝且不落取回件 =="
rm -f "$T/out/.root-token"
printf 'test-pass-123\n' | script -qec \
  "OPENBAO_ESCROW_ZIP='$T/tampered.zip' OPENBAO_ESCROW_TOKEN_FILE='$T/out/.root-token' openbao-escrow unlock" /dev/null >"$T/v3.log" 2>&1
if [ -e "$T/out/.root-token" ]; then bad "篡改包 unlock 后仍落了取回件"; else ok "篡改包 unlock 未落取回件"; fi

echo "== 4) bao 不可达 → 活性跳过，仍可解锁 =="
rm -f "$T/out/.root-token"
printf 'test-pass-123\n' | script -qec \
  "BAO_ADDR='http://127.0.0.1:1' OPENBAO_ESCROW_ZIP='$T/test.zip' OPENBAO_ESCROW_TOKEN_FILE='$T/out/.root-token' openbao-escrow unlock" /dev/null >"$T/v4.log" 2>&1
if [ -e "$T/out/.root-token" ]; then
  if cmp -s "$T/plain" "$T/out/.root-token"; then ok "bao 不可达时解锁成功且明文一致"; else bad "明文不一致"; fi
  grep -q '活性校验：跳过' "$T/v4.log" && ok "活性跳过有明确提示" || bad "缺活性跳过提示"
else bad "bao 不可达时解锁失败"; cat "$T/v4.log"; fi
rm -f "$T/out/.root-token"

echo "== 5) 桩 bao（policies=root）→ 三道校验全过 =="
python3 - >"$T/stub.log" 2>&1 <<'PY' &
import http.server,json
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body=json.dumps({"data":{"policies":["root"],"parent":"","display_name":"root",
                                "num_uses":0,"ttl":0,"orphan":True}}).encode()
        self.send_response(200); self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
    def log_message(self,*a): pass
http.server.HTTPServer(('127.0.0.1',18200),H).serve_forever()
PY
STUB=$!; sleep 1
printf 'test-pass-123\n' | script -qec \
  "BAO_ADDR='http://127.0.0.1:18200' OPENBAO_ESCROW_ZIP='$T/test.zip' OPENBAO_ESCROW_TOKEN_FILE='$T/out/.root-token' openbao-escrow unlock" /dev/null >"$T/v5.log" 2>&1
if [ -e "$T/out/.root-token" ] && cmp -s "$T/plain" "$T/out/.root-token"; then ok "全校验通过并安装取回件"; else bad "解锁失败"; cat "$T/v5.log"; fi
grep -q '活性 OK: lookup-self 200' "$T/v5.log" && ok "活性校验确认 root" || bad "活性校验未生效"
[ "$(stat -c%a "$T/out/.root-token")" = 600 ] && ok "取回件权限 0600" || bad "权限不是 0600"
kill $STUB 2>/dev/null

echo "== 6) 桩 bao（policies 无 root）→ 必须拒绝 =="
python3 - >/dev/null 2>&1 <<'PY' &
import http.server,json
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body=json.dumps({"data":{"policies":["reader"]}}).encode()
        self.send_response(200); self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
    def log_message(self,*a): pass
http.server.HTTPServer(('127.0.0.1',18201),H).serve_forever()
PY
STUB2=$!; sleep 1
rm -f "$T/out/.root-token"
printf 'test-pass-123\n' | script -qec \
  "BAO_ADDR='http://127.0.0.1:18201' OPENBAO_ESCROW_ZIP='$T/test.zip' OPENBAO_ESCROW_TOKEN_FILE='$T/out/.root-token' openbao-escrow unlock" /dev/null >"$T/v6.log" 2>&1
if [ -e "$T/out/.root-token" ]; then bad "非 root token 竟然解锁成功"; else ok "非 root token 被拒且未落盘"; fi
kill $STUB2 2>/dev/null

echo "== 7) 桩 bao（HTTP 403）→ 必须拒绝 =="
python3 - >/dev/null 2>&1 <<'PY' &
import http.server
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(403); self.send_header('Content-Length','0'); self.end_headers()
    def log_message(self,*a): pass
http.server.HTTPServer(('127.0.0.1',18202),H).serve_forever()
PY
STUB3=$!; sleep 1
rm -f "$T/out/.root-token"
printf 'test-pass-123\n' | script -qec \
  "BAO_ADDR='http://127.0.0.1:18202' OPENBAO_ESCROW_ZIP='$T/test.zip' OPENBAO_ESCROW_TOKEN_FILE='$T/out/.root-token' openbao-escrow unlock" /dev/null >"$T/v6b.log" 2>&1
if [ -e "$T/out/.root-token" ]; then bad "403 token 竟然解锁成功"; else ok "HTTP 403 被拒且未落盘"; fi
kill $STUB3 2>/dev/null

echo "== 8) 错口令 → 必须失败且不留取回件 =="
rm -f "$T/out/.root-token"
printf 'wrong-pass\n' | script -qec \
  "BAO_ADDR='http://127.0.0.1:1' OPENBAO_ESCROW_ZIP='$T/test.zip' OPENBAO_ESCROW_TOKEN_FILE='$T/out/.root-token' openbao-escrow unlock" /dev/null >"$T/v8.log" 2>&1
if [ -e "$T/out/.root-token" ]; then bad "错口令后仍落了取回件"; else ok "错口令被拒且未落盘"; fi

echo
printf '自检结果: PASS=%d FAIL=%d\n' "$PASS" "$FAIL"
[ "$FAIL" = 0 ]
