#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# /*!
# ********************************************************************************
# \file       uart_ft.py
# \brief      Send a file to a Linux board over serial using ZMODEM (rz/sz).
# \author     Kawanami
# \version    1.0
# \date       04/11/2025
#
# \details
#   - Opens the serial TTY, optional login, then cd to a known base directory
#     (default $HOME) to avoid nested paths across runs.
#   - Creates the destination directory, cd into it, starts 'rz' on the board,
#     closes serial and runs local 'sz' to push the file, reopens to wait for prompt.
#   - Returns to base dir and exits cleanly.
#
# \remarks
#   - Requires 'lrzsz' on both sides (rz on board, sz on host) + pyserial.
#   - Prefer absolute paths for --dest-dir (e.g. /root/firmware).
#
# \section uart_ft_version_history Version history
# | Version | Date       | Author     | Description                             |
# |:-------:|:----------:|:-----------|:----------------------------------------|
# | 1.0     | 04/11/2025 | Kawanami   | Initial version.                        |
# ********************************************************************************
# */

import argparse
import os
import sys
import time
import subprocess
from pathlib import Path

try:
    import serial
except ImportError:
    print("ERROR: pyserial is required. Install with: pip install pyserial", file=sys.stderr)
    sys.exit(1)


def read_until(ser: serial.Serial, token: bytes, timeout_s: float):
    """Read bytes until 'token' or timeout. Returns buffer (may be empty)."""
    end = time.time() + timeout_s
    buf = bytearray()
    while time.time() < end:
        chunk = ser.read(1)
        if chunk:
            buf += chunk
            if token in buf:
                return bytes(buf)
        else:
            time.sleep(0.01)
    return bytes(buf)


def write_line(ser: serial.Serial, line: str):
    """Write a line to serial with newline."""
    ser.write(line.encode("utf-8") + b"\n")
    ser.flush()


def try_login(ser: serial.Serial, user: str, password: str | None, prompt: bytes, timeout_s: float = 8.0):
    """
    Attempt a simple login: wait 'login:', send user, then (optional) password,
    finally wait for prompt.
    """
    write_line(ser, "")
    _ = read_until(ser, b"login:", timeout_s=2.5)

    write_line(ser, user)
    if password is not None:
        _ = read_until(ser, b"Password:", timeout_s=2.5)
        write_line(ser, password)

    _ = read_until(ser, prompt, timeout_s=timeout_s)


def run_remote_command(ser: serial.Serial, cmd: str, prompt: bytes, settle_s: float = 0.15, timeout_s: float = 8.0):
    """Send a shell command and wait for prompt back."""
    write_line(ser, cmd)
    time.sleep(settle_s)
    _ = read_until(ser, prompt, timeout_s=timeout_s)


def sh_quote(s: str) -> str:
    """Minimal shell quoting for file paths."""
    return "'" + s.replace("'", "'\"'\"'") + "'"


def main():
    ap = argparse.ArgumentParser(description="UART file transfer to Linux board using ZMODEM (rz/sz)")
    ap.add_argument("--dev", required=True, help="Serial device (e.g. /dev/ttyUSB0)")
    ap.add_argument("--baud", type=int, default=115200, help="Baud rate (default: 115200)")
    ap.add_argument("--login", action="store_true", help="Attempt login sequence")
    ap.add_argument("--user", default="root", help="Login user (default: root)")
    ap.add_argument("--password", default=None, help="Login password (if any)")
    ap.add_argument("--prompt", default="# ", help="Shell prompt to wait for (default: '# ')")
    ap.add_argument("--base-dir", default="$HOME", help="Base directory after login (default: $HOME)")
    ap.add_argument("--dest-dir", required=True, help="Destination directory on the board (prefer absolute path)")
    ap.add_argument("--file", required=True, help="Local file to send")
    ap.add_argument("--rx-opts", default="-y", help="Options for 'rz' on the board (default: -y)")
    ap.add_argument("--sz-opts", default="-y -b", help="Options for 'sz' on the host (default: -y -b)")
    args = ap.parse_args()

    dev = args.dev
    baud = args.baud
    prompt_bytes = args.prompt.encode("utf-8")

    local_path = Path(args.file).expanduser().resolve()
    if not local_path.is_file():
        print(f"ERROR: file not found: {local_path}", file=sys.stderr)
        sys.exit(1)

    # 1) Open serial
    ser = serial.Serial(dev, baudrate=baud, timeout=0.1)
    time.sleep(0.2)

    # 2) Login or poke prompt
    if args.login:
        try_login(ser, args.user, args.password, prompt_bytes, timeout_s=10.0)
    else:
        write_line(ser, "")
        _ = read_until(ser, prompt_bytes, timeout_s=2.0)

    # 3) Reset to known base directory
    run_remote_command(ser, f"cd {args.base_dir}", prompt_bytes)

    # 4) Create dest dir and cd into it  (FIX: args.dest_dir)
    run_remote_command(ser, f"mkdir -p {args.dest_dir} && cd {args.dest_dir}", prompt_bytes)

    # 5) Start 'rz' on the board
    run_remote_command(ser, f"rz {args.rx_opts}", prompt_bytes, settle_s=0.05)
    time.sleep(0.2)

    # 6) Close serial so 'sz' can use the TTY exclusively
    ser.close()

    # 7) Run 'sz' locally with redirection to the same TTY
    sz_cmd = f"sz {args.sz_opts} -- {sh_quote(str(local_path))} > {dev} < {dev}"
    ret = subprocess.call(sz_cmd, shell=True)
    if ret != 0:
        print(f"ERROR: sz failed with code {ret}", file=sys.stderr)
        sys.exit(ret)

    # 8) Re-open serial and wait for prompt (rz completion)
    ser = serial.Serial(dev, baudrate=baud, timeout=0.1)
    _ = read_until(ser, prompt_bytes, timeout_s=10.0)

    # 9) Go back to base dir then exit
    run_remote_command(ser, f"cd {args.base_dir}", prompt_bytes)
    write_line(ser, "exit")
    ser.close()

    print("OK: transfer complete.")


if __name__ == "__main__":
    main()
