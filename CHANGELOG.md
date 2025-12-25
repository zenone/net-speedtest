# CHANGELOG

All notable changes between the **original `network_speedtest.py`** script and the **new `net_speedtest.py`** implementation are documented here.

---

## net_speedtest (Current)

### 🔁 Architectural Overhaul
**BREAKING CHANGE**

- Replaced Python-based speed test libraries with **first‑party system tools**:
  - ✅ Ookla **Speedtest CLI** (`speedtest -f json`)
  - ✅ Apple **networkQuality**
- Shifted from *library‑driven measurement* → *tool‑orchestrated measurement* for long‑term macOS compatibility.
- Script now has **zero third‑party Python dependencies**.

**Why this matters:**  
Python speedtest libraries (e.g., `speedtest-cli`) are increasingly brittle on modern macOS and Python versions. The new approach mirrors how professional monitoring systems operate.

---

### 🚀 Measurement Improvements

#### Added
- **Responsiveness under load (RPM)** via `networkQuality`
- **Multiple-run sampling** with median aggregation
- **Optional DNS resolution timing**
- **Optional ping to selected speedtest server**
- **Packet loss reporting** (when available from Ookla)
- **Server metadata capture** (ID, host, location, ISP)
- **Environment snapshot** (OS, interface, IP, Python, hardware)

#### Changed
- Throughput calculations now correctly convert:
  - `bytes/sec → bits/sec → Mbps`
- Jitter reporting:
  - Ookla jitter preserved
  - ICMP jitter approximated from RTT deltas (clearly labeled)

---

### 📦 Output & Data Handling

#### Added
- **JSONL output** for time‑series analysis
- **Append‑only human log**
- **Summary block** with median values across runs
- Machine‑readable structure suitable for:
  - Automation
  - Cron / launchd
  - Long‑term trend tracking

#### Changed
- Output is now deterministic and schema‑stable
- Raw tool outputs optionally preserved for debugging

---

### 🖥 Terminal & UX Improvements

- Colorized output (TTY‑aware, auto‑disabled for pipes)
- Clear sectioning:
  - Environment
  - Ookla Speedtest
  - Apple networkQuality
  - ICMP baselines
- Quiet mode for automation
- Explicit install guidance when tools are missing

---

### 🔐 Security & Privacy Improvements

- Removed direct dependency on raw socket ICMP libraries
- System `ping` used instead (no elevated privileges)
- Public IP lookup (`ipinfo.io`) is now:
  - Optional
  - Explicitly disable‑able via `--no-ipinfo`
- No secrets, tokens, or credentials stored or required

---

### ⚙️ Reliability & Compatibility

- Tested against modern macOS (including Tahoe)
- Defensive parsing for:
  - `networkQuality` output variants
  - Ookla JSON schema drift
- Timeouts enforced on all subprocess calls
- Graceful degradation when tools are unavailable

---

### 🧪 Testing & Validation (Manual)

- Cross‑validated results against:
  - Speedtest.net web UI
  - Apple networkQuality standalone runs
- Median‑based aggregation reduces transient noise
- Designed for reproducibility rather than single‑run “score chasing”

---

### 📚 Documentation

- Added comprehensive **README.md** with:
  - Installation
  - Usage examples
  - Sample output
  - Best practices
  - Philosophy & intent
- CLI help expanded with sane defaults and clear flags

---

## [Original] – network_speedtest.py

### Initial Implementation

- Python‑centric speed testing using:
  - `speedtest` Python module
  - `ping3`
  - `requests`
  - `termcolor`
- Single‑run measurements
- Limited environment awareness
- Minimal output persistence
- No responsiveness‑under‑load signal
- Higher breakage risk on newer Python/macOS versions

---

## Migration Notes

This is **not** a drop‑in replacement.

If migrating automation:
- Replace calls to `network_speedtest.py` with `net_speedtest.py`
- Install Ookla Speedtest CLI for full feature parity
- Expect **richer output**, not identical fields

---

## Design Philosophy Shift (Summary)

| Old Script | New Script |
|-----------|-----------|
| Library‑driven | Tool‑orchestrated |
| Throughput‑only | Experience‑aware |
| Single snapshot | Multi‑sample median |
| Python fragile | macOS‑native |
| Ad‑hoc output | Structured, loggable |

---

Built to answer not just **“How fast is it?”**  
…but **“How does it behave when it matters?”**
