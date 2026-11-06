#!/usr/bin/env python3
"""exp-mirror-ro-mount.py — SIL 裁决镜像 ro 自挂载守护（FUSE，无 sudo 等价重挂）。

背景（2026-11-05 波次 A5 / C3，RT-E88 产出腿停摆修复）：SIL 环镜像真实性门
（self-improve-loop.py mirror_source_ro_gate，RT-E85④ 口径）的可信路径唯一＝
findmnt OPTIONS 含 ro——exp1/exp2 镜像目录（~/exp1-raw/mirror/orders、
~/exp2-raw/mirror/orders）此前是裸 rw 目录（bind 挂载在某次重启后丢失，机器
uptime 内亦无挂载记录），双源被 fail-closed 拒用 ⇒ 签名不前进、裁决不产生，
而环活性（轮/队列/心跳）全绿——裁决产出腿停摆且巡检面不可见（本修复前
sil-verdict-probe.py 已将该停摆读成显式红 rc=1）。

恢复路径的合同（守护与探针同一判据源）：把镜像目录以 ro 方式挂回。本机
约束：禁 sudo（setuid mount 拒绝非 root bind：mount rc=32 实测）；bindfs/
fuse-overlayfs/sshfs 均未安装；unshare 用户命名空间内的挂载只活在私有命名
空间、在役守护（主命名空间）不可见——均不可用。可用面：/dev/fuse 在位 +
fusermount（setuid，允许 user 在**当前**命名空间挂载 FUSE，全进程可见）。

本件＝把镜像目录**自挂载**为只读 FUSE 镜像（bind 挂载的等价替代）：
  · 内核 VFS 层 MNT_READONLY（-o ro）——findmnt OPTIONS 含 ro，与真 bind ro
    挂载同一可信路径；一切写/建/删/改属/改名/截断在 VFS 层即 EROFS，不抵达
    本守护，写拒不由用户态进程裁量（机制性只读，非 chmod 收权那种同 uid 可逆
    的权限位口径——RT-E85④ 明令不得用 chmod 替代，本件不是 chmod 路径）；
  · 源目录经**预开 rootfd + dir_fd 族系统调用**解析（挂载完成后路径名再解析
    会穿过自己的挂载点无限递归——自挂载的标准解法），子目录 readdir 走
    「openat(rootfd)→fd→listdir(fd)」（os.listdir 不支持 dir_fd）；
  · serve 守护启动前 prctl(PR_SET_DUMPABLE, 0)（A5-C3 终审必修，2026-11-05）：
    守护预开的 rootfd（/proc/<serve-pid>/fd/4＝底层镜像目录句柄）此前对同 uid
    敞开——同 uid 进程可 open 该 proc fd 得到底层句柄、openat 直写底层 inode，
    挂载点随即供出伪造内容而 findmnt 仍报 ro、判据仍绿（修前沙箱实证：复放件
    30-工件/外派/a5-redgates/c3-fd-escape-replay.py，同脚本修前红/修后绿）。
    PR_SET_DUMPABLE=0 后 /proc/<pid>/fd 族转 root 属主，同 uid 非 root 打开即
    EACCES（ptrace 注入面同封）；prctl 失败＝**不挂载**（fail-closed 留红，
    绝不带逃逸口挂出可信绿）。「与真 bind ro 同口径可信」断言据此修订：该等价
    仅在 fd 逃逸面封堵后成立（真 bind ro 无用户态守护本体，本件守护是同 uid
    可 kill 的用户态进程——残余边界见下，可用性面非完整性面）；
  · lstat/readlink 不跟随符号链接（与 bind 挂载呈现一致：树内链接呈现为链接，
    逃逸面仍由守护在册 _mirror_escape_links 判据拒用，本件不弱化任何逃逸腿）；
  · getattr/readdir/open/read/access/statfs 只读面齐备，守护枚举（glob+read）
    与两个聚合器经挂载点读取行为与 bind 挂载等价（沙箱逐项实测）。

判据不变性：本件**不改守护、不改探针**——ro 判定仍由守护在册
mirror_source_ro_gate（findmnt 单一源）作出；探针的机械实测（④）照读
findmnt。挂载在＝可信路径成立；守护进程死亡＝挂载消失＝门翻红（fail-closed，
不留假绿）。残余边界（如实）：FUSE 守护本体是用户态进程、无监督拉起（死亡/
机器重启后须重挂；@reboot cron 已配，进程中途死亡时门红可见、人工或后续批
并入 keepalive 名册兜底——本批如实登记，不在本件内加监督面）。

用法：
  python3 tools/exp-mirror-ro-mount.py --all          # 挂全部在册镜像（exp1+exp2）
  python3 tools/exp-mirror-ro-mount.py <src> <mnt>    # 单挂（src=mnt=自挂载）
退出码：0=已挂载或本次挂载成功；2=用法/前置失败（源缺件/已挂载/挂载失败）。
运行面：双守护后台化（libfuse daemonize），日志 状态观测/exp-mirror-ro-mount.log，
pidfile 状态观测/exp-mirror-ro-mount.<名>.pid。卸载＝fusermount -u <镜像目录>。
"""
import ctypes
import errno
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)          # -I 隔离模式下 script dir 不在 sys.path，显式补

from fuse import FUSE, FuseOSError, Operations, LoggingMixIn  # noqa: E402  (vendored fusepy)

EROFS = errno.EROFS

# 在册镜像源（判据源＝守护在册 exp_sources()：SIL_EXP_MIRROR / SIL_EXP_MIRROR2 缺省）
MIRRORS = (
    ("exp1", os.path.expanduser("~/exp1-raw/mirror/orders")),
    ("exp2", os.path.expanduser("~/exp2-raw/mirror/orders")),
)
LOG = os.path.join(WS, "状态观测", "exp-mirror-ro-mount.log")
PIDDIR = os.path.join(WS, "状态观测")


def _log(msg):
    line = "%s %s" % (time.strftime("%F %T"), msg)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def _guard(path):
    """FUSE 回调路径 → rootfd 相对路径；拒 '..' 成分（纵深防御，内核已先行解析）。"""
    parts = [p for p in path.split("/") if p]
    if any(p == ".." for p in parts):
        raise FuseOSError(errno.EACCES)
    return "/".join(parts)


class ROMirror(LoggingMixIn, Operations):
    """只读自镜像：全部解析走预开 rootfd（dir_fd 族），写面一律 EROFS。"""

    def __init__(self, root):
        self.root = root
        self.rootfd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)

    @staticmethod
    def _stat_dict(st):
        return {k: getattr(st, k) for k in (
            "st_atime", "st_ctime", "st_gid", "st_ino", "st_mode",
            "st_mtime", "st_nlink", "st_size", "st_uid")}

    def access(self, path, mode):
        path = _guard(path)
        if not path:
            return 0
        if not os.access(path, mode, dir_fd=self.rootfd):
            raise FuseOSError(errno.EACCES)
        return 0

    def chmod(self, path, mode):
        raise FuseOSError(EROFS)

    def chown(self, path, uid, gid):
        raise FuseOSError(EROFS)

    def getattr(self, path, fh=None):
        path = _guard(path)
        st = os.fstat(self.rootfd) if not path else os.lstat(path, dir_fd=self.rootfd)
        return self._stat_dict(st)

    def readdir(self, path, fh):
        path = _guard(path)
        if not path:
            return [".", ".."] + os.listdir(self.rootfd)
        fd2 = os.open(path, os.O_RDONLY | os.O_DIRECTORY, dir_fd=self.rootfd)
        try:
            return [".", ".."] + os.listdir(fd2)
        finally:
            os.close(fd2)

    def readlink(self, path):
        path = _guard(path)
        return os.readlink(path, dir_fd=self.rootfd)

    def mknod(self, path, mode, dev):
        raise FuseOSError(EROFS)

    def rmdir(self, path):
        raise FuseOSError(EROFS)

    def mkdir(self, path, mode):
        raise FuseOSError(EROFS)

    def statfs(self, path):
        stv = os.fstatvfs(self.rootfd)
        return {k: getattr(stv, k) for k in (
            "f_bavail", "f_bfree", "f_blocks", "f_bsize", "f_favail",
            "f_ffree", "f_files", "f_flag", "f_frsize", "f_namemax")}

    def unlink(self, path):
        raise FuseOSError(EROFS)

    def symlink(self, target, source):
        raise FuseOSError(EROFS)

    def rename(self, old, new):
        raise FuseOSError(EROFS)

    def link(self, target, source):
        raise FuseOSError(EROFS)

    def utimens(self, path, times=None):
        raise FuseOSError(EROFS)

    def open(self, path, flags):
        path = _guard(path)
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_APPEND
                    | os.O_CREAT | os.O_TRUNC):
            raise FuseOSError(EROFS)
        return os.open(path, flags, dir_fd=self.rootfd)

    def create(self, path, mode, fi=None):
        raise FuseOSError(EROFS)

    def read(self, path, length, offset, fh):
        return os.pread(fh, length, offset)

    def write(self, path, buf, offset, fh):
        raise FuseOSError(EROFS)

    def truncate(self, path, length, fh=None):
        raise FuseOSError(EROFS)

    def flush(self, path, fh):
        return 0

    def release(self, path, fh):
        return os.close(fh)

    def fsync(self, path, fdatasync, fh):
        return 0


def _already_mounted(path):
    """该路径已被（任意）挂载覆盖？读 /proc/self/mounts，不依赖 findmnt 解析。"""
    try:
        with open("/proc/self/mounts", "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2 and parts[1] == path:
                    return True
    except OSError:
        pass
    return False


def _pid_alive(pidfile):
    try:
        with open(pidfile, "r") as f:
            pid = int(f.read().strip())
        with open("/proc/%d/cmdline" % pid, "rb") as f:
            return b"exp-mirror-ro-mount" in f.read()
    except (OSError, ValueError):
        return False


def mount_one(name, path):
    """挂一件（自挂载 path 于 path）。返回 0=成功/在位，2=失败。

    fuse_main daemon 化后**不返回**（服务循环即进程本体），pidfile/日志无法在
    FUSE() 调用点后写——故服务模式拆独立子进程（--serve），本进程只 preflight、
    拉起、等挂载出现、登记 pidfile+日志。"""
    if not os.path.isdir(path):
        _log("FAIL %s 源目录缺件 %s——不挂（守护枚举对空根另行判红）" % (name, path))
        return 2
    if _already_mounted(path):
        _log("SKIP %s %s 已挂载——幂等返回" % (name, path))
        return 0
    pidfile = os.path.join(PIDDIR, "exp-mirror-ro-mount.%s.pid" % name)
    if _pid_alive(pidfile):
        _log("SKIP %s pidfile 活（%s）但挂载未覆盖——进程僵留，拒绝叠挂，须人工处置"
             % (name, pidfile))
        return 2
    import subprocess
    child = subprocess.Popen(
        [sys.executable, os.path.join(_HERE, "exp-mirror-ro-mount.py"),
         "--serve", path],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ok = False
    for _ in range(50):                      # 最多等 5s
        time.sleep(0.1)
        if _already_mounted(path):
            ok = True
            break
    if not ok:
        child.terminate()
        _log("FAIL %s %s 挂载 5s 未出现——拉起失败（见 --serve 子进程）" % (name, path))
        return 2
    pid = _serve_pid(path)
    with open(pidfile, "w") as f:
        f.write("%d\n" % pid)
    _log("OK %s %s 已 ro 自挂载（FUSE/exp-mirror-ro，serve pid=%s）"
         % (name, path, pid))
    return 0


def _serve_pid(path):
    """/proc 里 cmdline 含 --serve 与该挂载路径（全路径逐字）的守护 pid。"""
    pb = os.path.abspath(path).encode()
    try:
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            try:
                with open("/proc/%s/cmdline" % pid, "rb") as f:
                    cmd = f.read()
            except OSError:
                continue
            if (b"--serve" in cmd and pb in cmd
                    and b"exp-mirror-ro-mount" in cmd):
                return int(pid)
    except OSError:
        pass
    return -1


PR_SET_DUMPABLE = 4        # linux/prctl.h


def _seal_same_uid_fd_escape():
    """prctl(PR_SET_DUMPABLE, 0)：封堵同 uid 经 /proc/<pid>/fd 的底层句柄面。

    A5-C3 终审必修（2026-11-05）：守护预开 rootfd 后，/proc/<serve-pid>/fd/4
    对同 uid 敞开＝底层镜像目录可写句柄，伪造内容可绕过挂载点直写底层 inode
    （挂载点随即供出伪造内容而 findmnt 仍 ro、判据仍绿）。置 dumpable=0 后
    /proc/<pid> 敏感族（fd/mem/environ 等）转 root 属主，同 uid 非 root 打开
    即 EACCES；cmdline 不受限（_pid_alive/_serve_pid 的 pidfile 面不受影响）。
    由 --serve 在 FUSE 构造前调用：libfuse daemonize 为 fork 非 exec，dumpable
    属性随 fork 继承，覆盖 daemon 本体。返回 (ok, detail)；失败由调用方
    fail-closed（不挂载）——绝不带逃逸口挂出可信绿。"""
    try:
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        libc.prctl.restype = ctypes.c_int
        rc = libc.prctl(PR_SET_DUMPABLE, ctypes.c_long(0), 0, 0, 0)
    except OSError as e:
        return False, "prctl 调用失败: %s" % e
    if rc != 0:
        err = ctypes.get_errno()
        return False, "prctl(PR_SET_DUMPABLE,0) rc=%d errno=%d(%s)" % (
            rc, err, errno.errorcode.get(err, "?"))
    return True, "PR_SET_DUMPABLE=0 已置（/proc/<pid>/fd 同 uid 面已封）"


def _serve(path):
    """服务模式：构造 FUSE（blocking，daemon 化由 libfuse 完成；异常必须留痕）。"""
    ok, detail = _seal_same_uid_fd_escape()
    if not ok:
        _log("FAIL serve %s 同 uid fd 逃逸面封堵失败，拒绝挂载（fail-closed）：%s"
             % (path, detail))
        return 2
    try:
        # ro=True → 内核 MS_RDONLY（findmnt OPTIONS 含 ro，机制性只读）；
        # nonempty=True → 允许自挂载（bind 语义）；nothreads → 单线程服务足够
        # （只读面、读方仅守护枚举与两聚合器）；不实现任何写面 op（VFS 先拒）。
        FUSE(ROMirror(path), path, foreground=False, nothreads=True,
             allow_other=False, ro=True, nonempty=True,
             fsname="exp-mirror-ro", subtype="exp-mirror-ro")
    except Exception as e:  # noqa: BLE001 —— 挂载失败必须显式红，不静默
        _log("FAIL serve %s 挂载失败：%s: %s" % (path, type(e).__name__, e))
        return 2
    return 0


def main():
    argv = sys.argv[1:]
    if not argv:
        print(__doc__)
        return 2
    if argv[0] == "--serve" and len(argv) == 2:
        return _serve(argv[1])
    if argv[0] == "--all":
        # 每镜像一个独立子进程——pidfile/日志按名区分；聚合退出码。
        rc = 0
        for name, path in MIRRORS:
            r = mount_one(name, path)
            if r != 0:
                rc = r
        return rc
    if len(argv) == 2:
        if argv[0] != argv[1]:
            print("FAIL 本件只支持自挂载（src=mnt），非自挂载的独立挂点会引入"
                  "「绕开挂载点写源」的漂移面：%s -> %s" % (argv[0], argv[1]))
            return 2
        name = next((n for n, p in MIRRORS if p == argv[0]), "manual")
        return mount_one(name, argv[0])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
