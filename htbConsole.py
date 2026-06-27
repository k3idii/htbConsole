#!/usr/bin/env python3
"""Standalone proxy → htbConsole package launcher.

Lets the app run in-place from the repo root without installing:

    python htbConsole.py [htb|ctf]

Equivalent installed/standalone entry points:

    python -m htbconsole [htb|ctf]
    htbconsole [htb|ctf]
"""
from htbconsole.__main__ import main

if __name__ == "__main__":
    main()
