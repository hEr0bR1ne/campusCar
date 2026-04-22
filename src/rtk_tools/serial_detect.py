#!/usr/bin/env python3
import glob
import subprocess
from typing import Optional

from config import DEFAULT_BAUD, SERIAL_GLOBS

def stty_init(port: str, baud: int = DEFAULT_BAUD) -> bool:
    try:
        subprocess.run(
            ["sudo", "stty", "-F", port, str(baud), "raw", "-echo", "-ixon", "-ixoff", "-crtscts"],
            check=True,
            text=True,
            capture_output=True,
        )
        return True
    except subprocess.CalledProcessError:
        return False

def probe_gga(port: str) -> str:
    cmd = f"sudo timeout 1s cat '{port}' 2>/dev/null | strings | grep '^\\$GNGGA' | head -n 1"
    p = subprocess.run(["bash", "-lc", cmd], text=True, capture_output=True)
    return (p.stdout or "").strip()

def candidate_ports() -> list[str]:
    ports = []
    for pattern in SERIAL_GLOBS:
        for p in glob.glob(pattern):
            if p not in ports:
                ports.append(p)
    return ports

def detect_serial_port(baud: int = DEFAULT_BAUD) -> Optional[str]:
    for port in candidate_ports():
        if not stty_init(port, baud):
            continue
        if probe_gga(port):
            return port
    return None

if __name__ == "__main__":
    print(detect_serial_port() or "")
