"""mini-pkv 命令行入口：装配 core 引擎与 persist 文件 backend。

退出码（冻结）：0=成功，1=未找到，2=用法错（argparse），3=存储错，4=校验错。
"""

import argparse
import sys

from pkv.core import KVStore
from pkv.persist import FileBackend, PersistenceError

PROG = "pkv"

EXIT_OK = 0
EXIT_MISS = 1
EXIT_USAGE = 2
EXIT_STORAGE = 3
EXIT_INVALID = 4

DEFAULT_FILE = "pkv.db"


def _warn(text):
    """错误信息统一走 stderr，前缀 `pkv: `。"""
    sys.stderr.write("%s: %s\n" % (PROG, text))


def build_parser():
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="mini-pkv：标准库实现的持久化 KV 存储",
    )
    parser.add_argument(
        "--file",
        metavar="PATH",
        default=DEFAULT_FILE,
        help="存储文件路径（缺省 %s，置于子命令之前）" % DEFAULT_FILE,
    )

    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)

    p_set = subparsers.add_parser("set", help="写入键值")
    p_set.add_argument("key", metavar="KEY")
    p_set.add_argument("value", metavar="VALUE")
    p_set.add_argument("--ttl", metavar="SECONDS", type=float, default=None, help="存活秒数")

    p_get = subparsers.add_parser("get", help="读取键值")
    p_get.add_argument("key", metavar="KEY")

    p_del = subparsers.add_parser("del", help="删除键")
    p_del.add_argument("key", metavar="KEY")

    subparsers.add_parser("list", help="列出存活键")

    return parser


def _run(args):
    """一次子命令 = 一次进程 = 一次 load + 若干 save。"""
    store = KVStore(backend=FileBackend(args.file))

    if args.command == "set":
        store.set(args.key, args.value, ttl=args.ttl)
        return EXIT_OK

    if args.command == "get":
        value = store.get(args.key)
        if value is None:
            _warn("key not found: %s" % args.key)
            return EXIT_MISS
        sys.stdout.write(value + "\n")
        return EXIT_OK

    if args.command == "del":
        if not store.delete(args.key):
            _warn("key not found: %s" % args.key)
            return EXIT_MISS
        return EXIT_OK

    if args.command == "list":
        for key in store.list():
            sys.stdout.write(key + "\n")
        return EXIT_OK

    _warn("unknown command: %s" % args.command)
    return EXIT_USAGE


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return _run(args)
    except PersistenceError as exc:
        _warn("storage error: %s" % exc)
        return EXIT_STORAGE
    except OSError as exc:
        _warn("storage error: %s" % exc)
        return EXIT_STORAGE
    except (TypeError, ValueError) as exc:
        _warn("invalid argument: %s" % exc)
        return EXIT_INVALID


if __name__ == "__main__":
    sys.exit(main())
