# net_speedtest

A macOS‑native, terminal‑friendly network speed and quality testing tool designed to deliver results on par with, and in some ways deeper than, commercial tools like **Speedtest by Ookla**.

This script intentionally favors **official, first‑party measurement engines** rather than fragile Python libraries, making it reliable on modern macOS versions (including Tahoe).

---

## What This Tool Measures

`net_speedtest` combines **three complementary perspectives** of network health:

### 1. Ookla Speedtest CLI
Industry‑standard ISP‑grade metrics:
- Download / Upload throughput
- Idle latency
- Jitter
- Packet loss
- Server metadata (location, ISP, host)

### 2. Apple `networkQuality`
Apple’s built‑in quality‑of‑experience measurement:
- Downlink & uplink capacity
- Responsiveness under load (RPM)
- Idle latency

This captures *how the network feels while in use*, not just peak throughput.

### 3. ICMP Ping Baselines
Low‑level path health:
- Packet loss
- Min / Avg / Max latency
- Approximate jitter
- Optional ping to selected speedtest server

---

## Why This Exists

Most speed tests answer only one question:
> *“How fast can this link go right now?”*

This tool answers the better question:
> *“How does this network actually behave under real‑world conditions?”*

That makes it ideal for:
- Wi‑Fi tuning
- ISP comparisons
- Bufferbloat detection
- Baseline vs degraded‑state analysis
- Automation and logging

---

## Requirements

### macOS
- macOS 12+ (Apple `networkQuality` required)
- Tested on modern macOS including **Tahoe**

### Required Tools
- **Apple `networkQuality`**  
  Included by default on modern macOS.

### Strongly Recommended
- **Ookla Speedtest CLI (official)**

> ⚠️ Important  
> Do **not** install `speedtest-cli`. That is a legacy Python wrapper and is **not supported** by this tool.

#### Install via Ookla’s official Homebrew tap
```bash
brew tap teamookla/speedtest
brew update

# Optional cleanup if previously installed
brew uninstall speedtest-cli --force

brew install speedtest
```

Verify installation:
```bash
which speedtest
speedtest --version
networkQuality -h
```

You should see output similar to:
```text
Speedtest by Ookla x.x.x
```

---

## Installation

Clone or copy the script:
```bash
chmod +x net_speedtest.py
```

Run directly:
```bash
./net_speedtest.py
```

Or via Python:
```bash
python3 net_speedtest.py
```

No Python dependencies required.

---

## Basic Usage

### Single run
```bash
./net_speedtest.py
```

### Recommended real‑world test (5 samples)
```bash
./net_speedtest.py --runs 5
```

### Quiet mode (for automation)
```bash
./net_speedtest.py --runs 3 --quiet
```

---

## Example Output

```text
net_speedtest - 2025-01-25T14:12:01-08:00

Environment
Host            : example-mac
OS              : Darwin 24.1.0
Machine         : arm64
Python          : 3.12.1
Default iface   : en0
Local IP        : 192.168.1.42
Public IP       : 73.xxx.xxx.xxx
ISP/Org         : Comcast Cable
Location        : Reno, NV, US

Ookla Speedtest (CLI)
Server           : Reno Speedtest (12345)
Server host      : speedtest.reno.net
Server location  : Reno, US
Idle latency     : 19.40 ms
Jitter           : 1.21 ms
Download         : 842.32 Mbps
Upload           : 38.41 Mbps
Packet loss      : 0.00%

Apple networkQuality
Downlink capacity        : 811.422 Mbps
Uplink capacity          : 37.882 Mbps
Downlink responsiveness  : 143 ms | 246 RPM
Uplink responsiveness    : 211 ms | 168 RPM
Idle latency             : 22.911 ms

ICMP Ping baselines
Target           : 1.1.1.1
Loss             : 0.0% (10/10)
RTT min/avg/max  : min 18.2 ms, avg 19.8 ms, max 23.1 ms
Jitter           : 1.12 ms
```

---

## Output Files

By default, results are stored locally:

- **JSONL (machine‑readable)**  
  `~/net_speedtest.jsonl`

- **Human log**  
  `~/net_speedtest.log`

These are append‑only and safe for long‑term tracking.

---

## Advanced Options

### Disable individual components
```bash
./net_speedtest.py --no-ookla
./net_speedtest.py --no-networkquality
./net_speedtest.py --no-ping
```

### Force an Ookla server
```bash
./net_speedtest.py --server-id 12345
```

### Ping the selected speedtest server
```bash
./net_speedtest.py --ping-speedtest-server
```

### Disable public IP lookup (privacy‑first)
```bash
./net_speedtest.py --no-ipinfo
```

---

## Recommended Testing Practices

For clean, comparable results:

- Prefer **ethernet** when possible
- Pause large downloads/uploads
- Disable VPN / Private Relay (temporarily)
- Run **3–5 samples**
- Compare **median**, not max

---

## Philosophy

This tool intentionally avoids:
- Fragile Python speedtest libraries
- Single‑metric “speed scores”
- Black‑box measurement

Instead, it focuses on:
- Transparency
- Repeatability
- Real‑world signal over marketing numbers

---

## License

MIT — use freely, modify responsibly.

---

Built for people who care not just about *speed*…  
but about *experience*.
