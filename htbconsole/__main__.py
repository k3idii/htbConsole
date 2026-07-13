#!/usr/bin/env python3
import sys


def prompt():
    try:
        choice = input("[h]tb, [c]tf or [cli] ? ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        sys.exit(0)
    return choice


def main():
    mode = None

    if len(sys.argv) > 1:
        arg = sys.argv[1].lower().strip()
        if arg == "cli":
            from .cli import main as cli_main
            sys.exit(cli_main(sys.argv[2:]))
        if arg in ("htb", "h"):
            mode = "htb"
        elif arg in ("ctf", "c"):
            mode = "ctf"
        else:
            print(f"Unknown mode: {arg}")
            print("Usage: htbconsole [htb|ctf|cli]")
            sys.exit(1)
    else:
        choice = prompt()
        if choice in ("h", "htb"):
            mode = "htb"
        elif choice in ("c", "ctf"):
            mode = "ctf"
        elif choice in ("cli", "cl"):
            mode = "cli"
        else:
            print(f"Unknown choice: {choice}")
            sys.exit(1)

    if mode == "cli":
        try:
            cmd = input("cli command (e.g., htb active): ").strip()
        except (EOFError, KeyboardInterrupt):
            sys.exit(0)
        import shlex
        from .cli import main as cli_main
        sys.exit(cli_main(shlex.split(cmd)))
    elif mode == "htb":
        from .tuiHTB import main as htb_main
        htb_main()
    else:
        from .tuiCTF import main as ctf_main
        ctf_main()


if __name__ == "__main__":
    main()
