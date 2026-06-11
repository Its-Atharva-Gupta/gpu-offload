#!/usr/bin/env python3
"""
GPU Dispatcher - Runs on the Pi, offloads work to the PC via SSH.

Usage:
    python3 gpu_dispatcher.py status          # Check PC + GPU status
    python3 gpu_dispatcher.py run "python3 script.py"  # Run a command on PC
    python3 gpu_dispatcher.py exec "import torch; print(torch.cuda.is_available())"  # Run Python on PC
    python3 gpu_dispatcher.py detect          # Just detect if PC is online
"""

import subprocess
import sys
import json
import time
import os
import socket

PC_HOST = "pop-os.local"
PC_USER = "atharva"
SSH_KEY = os.path.expanduser("~/.ssh/id_ed25519")
SSH_TIMEOUT = 5
STATUS_FILE = os.path.expanduser("~/.hermes/gpu_dispatcher_status.json")


def pc_is_online():
    """Check if PC is reachable on the local network."""
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", "2", PC_HOST],
            capture_output=True, text=True, timeout=5
        )
        return result.returncode == 0
    except Exception:
        return False


def ssh_run(command, timeout=300):
    """Run a command on the PC via SSH. Returns (stdout, stderr, returncode)."""
    ssh_cmd = [
        "ssh",
        "-i", SSH_KEY,
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=" + str(SSH_TIMEOUT),
        "-o", "BatchMode=yes",
        f"{PC_USER}@{PC_HOST}",
        command
    ]
    try:
        result = subprocess.run(
            ssh_cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except subprocess.TimeoutExpired:
        return "", "SSH command timed out", -1
    except Exception as e:
        return "", str(e), -1


def get_gpu_info():
    """Get GPU info from the PC."""
    stdout, stderr, rc = ssh_run("nvidia-smi --query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu --format=csv,noheader 2>/dev/null")
    if rc != 0:
        return None
    gpus = []
    for line in stdout.split("\n"):
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 5:
            gpus.append({
                "name": parts[0],
                "memory_total": parts[1],
                "memory_used": parts[2],
                "memory_free": parts[3],
                "utilization": parts[4]
            })
    return gpus


def get_python_info():
    """Get Python/CUDA info from the PC."""
    stdout, stderr, rc = ssh_run(
        "python3 -c \"import torch; print('torch:', torch.__version__); "
        "print('cuda:', torch.cuda.is_available()); "
        "print('device:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'N/A')\" 2>/dev/null"
    )
    return stdout if rc == 0 else None


def save_status(status):
    """Save status to file for other processes to read."""
    os.makedirs(os.path.dirname(STATUS_FILE), exist_ok=True)
    with open(STATUS_FILE, "w") as f:
        json.dump(status, f, indent=2)


def load_status():
    """Load last known status."""
    try:
        with open(STATUS_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def status_check():
    """Full status check of the PC and GPU."""
    online = pc_is_online()
    result = {
        "timestamp": time.time(),
        "pc_online": online,
        "pc_host": PC_HOST,
    }
    if online:
        result["gpu"] = get_gpu_info()
        result["python"] = get_python_info()
    else:
        result["gpu"] = None
        result["python"] = None
        result["note"] = "PC is offline or unreachable"

    save_status(result)
    return result


def run_on_pc(command, timeout=300):
    """Run a command on the PC and stream results."""
    online = pc_is_online()
    if not online:
        return {
            "success": False,
            "error": "PC is offline. Command queued but not executed.",
            "command": command
        }

    stdout, stderr, rc = ssh_run(command, timeout=timeout)
    return {
        "success": rc == 0,
        "returncode": rc,
        "stdout": stdout,
        "stderr": stderr,
        "command": command
    }


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    action = sys.argv[1]

    if action == "status":
        result = status_check()
        print(json.dumps(result, indent=2))

    elif action == "detect":
        online = pc_is_online()
        print(json.dumps({"pc_online": online, "host": PC_HOST}))

    elif action == "run":
        if len(sys.argv) < 3:
            print("Usage: gpu_dispatcher.py run <command>")
            sys.exit(1)
        result = run_on_pc(sys.argv[2])
        print(json.dumps(result, indent=2))

    elif action == "exec":
        if len(sys.argv) < 3:
            print("Usage: gpu_dispatcher.py exec <python_code>")
            sys.exit(1)
        # Wrap in python3 -c
        code = sys.argv[2]
        result = run_on_pc(f'python3 -c "{code}"')
        print(json.dumps(result, indent=2))

    elif action == "gpu":
        info = get_gpu_info()
        print(json.dumps(info, indent=2) if info else "No GPU info available")

    else:
        print(f"Unknown action: {action}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
