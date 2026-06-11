# WoL Reference - Wake-on-LAN from the Pi

## PC Network Details
- **MAC**: `AA:BB:CC:DD:EE:FF` (replace with your PC's actual MAC)
- **Hostname**: `<pc-host>` (replace with your PC's hostname)
- **IP**: `192.168.0.X` (DHCP, may change — use hostname instead)
- **Broadcast**: `<your-local-broadcast>` (e.g. `192.168.1.255` — check with `ip route`)

## Sending a WoL Magic Packet (Pure Python, No Dependencies)

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

## Boot Timing
- **~10 seconds**: NIC responds to ARP (PC starting to boot)
- **~30 seconds**: May respond to ping but services not ready
- **~90 seconds**: Fully booted, GPU job server accessible on port 8765
- **~120 seconds**: All services (Ollama, etc.) fully initialized

## One-Liner (copy-paste into terminal)
```bash
python3 -c "
import socket
mac = 'AA:BB:CC:DD:EE:FF'
broadcast = '192.168.0.255'
mac_bytes = bytes.fromhex(mac.replace(':', ''))
packet = b'\xff' * 6 + mac_bytes * 16
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
for port in [9, 7, 40000]:
    sock.sendto(packet, (broadcast, port))
sock.close()
print('WoL sent!')
" && sleep 90 && python3 ~/.hermes/scripts/gpu_dispatcher.py detect
```

## Troubleshooting
- **PC doesn't wake**: Check BIOS "Wake on LAN" / "Power On By PCI-E" is enabled
- **Linux WoL config**: `sudo ethtool eth0 | grep Wake-on` → should show `g`
- **WoL works from S5 (soft off)** but NOT from a full power cut (G3 state)
- **If PC gets new IP**: Update `PC_HOST` in `gpu_dispatcher.py` or use hostname
- **Verify WoL worked**: `python3 ~/.hermes/scripts/gpu_dispatcher.py detect` → `"pc_online": true`
