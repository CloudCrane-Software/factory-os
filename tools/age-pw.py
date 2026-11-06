#!/usr/bin/env python3
"""age-pw.py —— 一次采集托管口令，驱动若干次 age 调用。

为什么需要它：age 的 -p/--passphrase 强制从控制终端读口令（非 tty 直接报错），
所以"封存两件 + 往返自验两件"这种流程要么让 owner 输 4~6 次，要么就得把口令
经管道/env 传递 —— 后者会让口令进入 argv 或进程环境，破坏托管设计。

本包装器：口令只在真终端用 getpass 采集一次（不回显、不进 argv、不进 history），
然后通过 pty 反复投喂给 age 子进程。owner 全程只输一次。

用法：
  单次：  age-pw.py "<提示语>" <最大应答次数> <命令> [参数...]
  批量：  ... | age-pw.py --batch "<提示语>"      # 命令逐行从 stdin 读，口令只输一次
示例：
  age-pw.py "请输入托管口令：" 2 age -p -a -o root.age root.plain
  printf '%s\n' "age -p -a -o r.age r.plain" "age -d -o back.bin r.age" \
    | age-pw.py --batch "托管口令："
"""
import fcntl
import getpass
import os
import re
import select
import signal
import sys
import termios

# age 的口令提示实际长这样：
#   封存："Enter passphrase (leave empty to autogenerate a secure one):" + "Re-enter passphrase..."
#   解密："Enter passphrase:"
# 所以按"passphrase ... 冒号"匹配，不能锚定 "enter passphrase:"。
PROMPT_RE = re.compile(rb"passphrase[^:\n]*:\s*", re.I)


def read_pw(prompt):
    """从 /dev/tty 采集口令并临时关闭回显。

    刻意不用 getpass：getpass 读的是 stdin，而本脚本的口令必须来自控制终端
    （age 的规矩，也保证口令不会被重定向进管道或环境）。
    """
    try:
        fd = os.open("/dev/tty", os.O_RDWR)
    except OSError:  # 没有控制终端（CI 等），退回 stdin，仅供自检使用
        return getpass.getpass(prompt)
    old = termios.tcgetattr(fd)
    quiet = termios.tcgetattr(fd)
    quiet[3] &= ~termios.ECHO   # TCSADRAIN 而非 TCSAFLUSH：不清输入队列，手快的输入不被吞
    try:
        termios.tcsetattr(fd, termios.TCSADRAIN, quiet)
        os.write(fd, (prompt + "\n").encode())
        buf = b""
        while not buf.endswith(b"\n"):
            ch = os.read(fd, 1)
            if not ch:
                raise EOFError("age-pw: 口令输入流提前结束")
            buf += ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        os.close(fd)
    return buf.rstrip(b"\n").decode()


def feed(master_fd, password, limit, seen):
    """按需向子进程投喂口令：只在检测到新的口令提示时写一次。"""
    n = len(PROMPT_RE.findall(seen["buf"]))
    while seen["fed"] < min(n, limit):
        os.write(master_fd, password.encode() + b"\n")
        seen["fed"] += 1


def main():
    batch = "--batch" in sys.argv[1:]
    args = [a for a in sys.argv[1:] if a != "--batch"]
    if batch:
        if not args:
            sys.exit(__doc__)
        cmds = [l for l in sys.stdin.read().splitlines() if l.strip()]
        if not cmds:
            sys.exit("age-pw: --batch 没读到任何命令")
    else:
        if len(args) < 3:
            sys.exit(__doc__)
        cmds = None

    prompt = args[0]
    # 口令只在真终端采集一次
    password = read_pw(prompt)
    if not password:
        sys.exit("age-pw: 口令为空，中止")

    if batch:
        for line in cmds:
            rc = run_once(password, ["sh", "-c", line], limit=2)
            if rc != 0:
                sys.exit(f"age-pw: 批量命令失败（rc={rc}）：{line}")
        sys.exit(0)

    limit, argv = int(args[1]), args[2:]
    sys.exit(run_once(password, argv, limit))


def run_once(password, argv, limit):

    master_fd, slave_fd = os.openpty()
    try:
        pid = os.fork()
    except OSError as exc:  # pragma: no cover
        sys.exit(f"age-pw: fork 失败：{exc}")

    if pid == 0:
        # 子进程：把 pty 变成自己的控制终端，age 才肯从终端读口令
        try:
            os.close(master_fd)
            os.setsid()
            fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)
            for fd in (0, 1, 2):
                os.dup2(slave_fd, fd)
            if slave_fd > 2:
                os.close(slave_fd)
            os.execvp(argv[0], argv)
        except Exception as exc:  # pragma: no cover
            os.write(2, f"age-pw: 执行 {argv[0]} 失败：{exc}\n".encode())
        os._exit(127)

    os.close(slave_fd)
    seen = {"buf": b"", "fed": 0}
    try:
        while True:
            ready, _, _ = select.select([master_fd], [], [], 300)
            if not ready:
                break
            try:
                chunk = os.read(master_fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            os.write(2, chunk)          # 原样透传 age 的提示与错误
            seen["buf"] += chunk
            seen["buf"] = seen["buf"][-4096:]   # 只保留尾部，避免无限增长
            feed(master_fd, password, limit, seen)
    finally:
        os.close(master_fd)

    _, status = os.waitpid(pid, 0)
    if os.WIFSIGNALED(status):
        return 128 + os.WTERMSIG(status)
    return os.WEXITSTATUS(status)


if __name__ == "__main__":
    main()
