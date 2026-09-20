import sys

from src.cli.main import main


def _force_utf8_streams() -> None:
    """机器输出契约：非终端（重定向/管道）的 stdin/stdout/stderr 固定为 UTF-8。"""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            if stream.isatty():
                continue
            reconfigure(encoding="utf-8")
        except (ValueError, OSError):
            continue


if __name__ == "__main__":
    _force_utf8_streams()
    raise SystemExit(main())
