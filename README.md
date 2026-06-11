# GPU Offload — Pi to PC

Offload GPU-heavy ML work from the Raspberry Pi to the PC (pop-os, RTX 3060) on the local network.

## Architecture

```
Pi (Hermes agent)                         PC (pop-os, RTX 3060)
┌──────────────────┐    SSH / HTTP     ┌──────────────────────────┐
│ gpu_dispatcher.py │ ──────────────► │ gpu_job_server.py         │
│                   │                  │ (HTTP server, port 8765)  │
│ - detect PC       │                  │                           │
│ - run commands    │                  │ - Accept Python scripts   │
│ - check GPU       │                  │ - Run with GPU access     │
│ - status          │                  │ - Return results          │
└──────────────────┘                  └──────────────────────────┘
```

- **Pi side**: `scripts/gpu_dispatcher.py` — detects PC, runs commands via SSH
- **PC side**: `scripts/gpu_job_server.py` — HTTP server that accepts Python scripts and runs them with GPU access
- **Communication**: Local network, SSH for direct commands, HTTP for job submission

## File Layout

```
Agent-Skill/
├── README.md                  # This file
├── scripts/
│   ├── gpu_dispatcher.py      # Pi-side dispatcher (SSH-based)
│   └── gpu_job_server.py      # PC-side HTTP job server
└── references/
    └── wol.md                 # Wake-on-LAN reference
```

## Quick Start

### 1. Copy scripts to their locations

```bash
# On the Pi:
cp scripts/gpu_dispatcher.py ~/.hermes/scripts/gpu_dispatcher.py

# On the PC (replace <pc-host> with your PC's hostname or IP):
scp scripts/gpu_job_server.py <user>@<pc-host>:~/Desktop/RL/gpu_job_server.py
```

### 2. Set up SSH key authentication (one-time)

Generate an SSH key on the Pi if you don't have one:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519
```

Copy the public key to the PC:

```bash
ssh-copy-id -i ~/.ssh/id_ed25519.pub <user>@<pc-host>
```

### 3. Start the GPU job server on the PC

```bash
# Quick start:
nohup python3 ~/Desktop/RL/gpu_job_server.py --port 8765 &

# Or set up as a systemd service (see below).
```

### 4. Test from the Pi

```bash
# Check if PC is online and GPU status
python3 ~/.hermes/scripts/gpu_dispatcher.py status

# Just detect PC
python3 ~/.hermes/scripts/gpu_dispatcher.py detect

# Run a command on the PC
python3 ~/.hermes/scripts/gpu_dispatcher.py run "nvidia-smi"

# Run Python on the PC
python3 ~/.hermes/scripts/gpu_dispatcher.py exec "import torch; print(torch.cuda.is_available())"
```

## PC systemd Service (auto-start on boot)

Create `/etc/systemd/system/gpu-job-server.service` on the PC (replace `<user>` with your username):

```ini
[Unit]
Description=GPU Job Server for Pi offload
After=network.target

[Service]
Type=simple
User=<user>
WorkingDirectory=/home/<user>/Desktop/RL
ExecStart=/usr/bin/python3 /home/<user>/Desktop/RL/gpu_job_server.py --port 8765
Restart=on-failure
RestartSec=5
StandardOutput=append:/home/<user>/Desktop/RL/gpu_job_server.log
StandardError=append:/home/<user>/Desktop/RL/gpu_job_server.log

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable gpu-job-server
sudo systemctl start gpu-job-server
```

## GPU Job Server API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/status` | GET | PC + GPU status |
| `/jobs` | GET | List all jobs |
| `/job/<id>` | GET | Get job result |
| `/submit` | POST | Submit a Python script to run on GPU |

### Submit a job

```bash
curl -X POST http://<pc-host>:8765/submit \
  -H "Content-Type: application/json" \
  -d '{"script": "import torch; print(torch.cuda.is_available())"}'
```

## Wake-on-LAN

If the PC is offline, wake it from the Pi. You'll need the PC's MAC address and local broadcast address:

```python
import socket

mac = 'AA:BB:CC:DD:EE:FF'          # Replace with your PC's MAC
broadcast = '<your-local-broadcast>'  # e.g. 192.168.1.255 — check with `ip route`

mac_bytes = bytes.fromhex(mac.replace(':', ''))
packet = b'\xff' * 6 + mac_bytes * 16

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
for port in [9, 7, 40000]:
    sock.sendto(packet, (broadcast, port))
sock.close()
```

Then wait ~90 seconds for the PC to fully boot.

See `references/wol.md` for full WoL details.

## Configuration

Edit `gpu_dispatcher.py` to change:
- `PC_HOST`: PC hostname or IP
- `PC_USER`: SSH username
- `SSH_KEY`: Path to SSH key

## Verified Environment (June 2026)

| | |
|---|---|
| **PC OS** | Pop!_OS 24.04 LTS |
| **GPU** | NVIDIA GeForce RTX 3060, 12GB VRAM |
| **Driver** | 580.82.09, CUDA 13.0 |
| **Python** | 3.12.3 (system, no PyTorch) |
| **GPU job server** | `~/Desktop/RL/gpu_job_server.py` |
| **systemd service** | `gpu-job-server` enabled and auto-starts on boot |

## Pitfalls

- **`sudo` over SSH**: Non-interactive SSH cannot run `sudo` without a TTY. Run sudo commands directly on the PC terminal, or set up passwordless sudo on the PC.
- **PyTorch not in system Python**: The PC's system Python doesn't have PyTorch. Submitted jobs must use a venv/conda that has it.
- **Port conflict**: Before starting the GPU job server, check if port 8765 is already in use: `ss -tlnp | grep 8765`.
- **`shutdown`/`reboot` blocked**: Hermes cannot execute shutdown/reboot commands. The user must run these directly on the PC.
- **systemd auto-restart masks port conflicts**: Check `systemctl status gpu-job-server` for `activating (auto-restart)` state if things look wrong.
