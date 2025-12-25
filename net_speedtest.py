#!/usr/bin/env python3
"""
net_speedtest.py

A macOS-friendly network speed/quality test runner that prefers best-in-class CLIs when available:

1) Ookla Speedtest CLI (`speedtest`) for ISP-like download/upload/latency/jitter/packet loss.
2) Apple's built-in `networkQuality` for responsiveness under load (RPM) + uplink/downlink capacity.
3) Lightweight ICMP ping tests for baseline latency/jitter/loss to well-known targets.

This script has **zero third-party Python dependencies**. It shells out to optional system tools if installed.

Practical notes:
- For best results: prefer ethernet, pause big downloads/uploads, disable VPN temporarily, and run multiple samples.
- Run 3–5 samples and look at the median.

Outputs:
- Human-readable terminal output (unless --quiet)
- JSONL records appended to ~/net_speedtest.jsonl (configurable)
- Simple log appended to ~/net_speedtest.log (configurable)
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime as _dt
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


APP_NAME = "net_speedtest"
DEFAULT_LOG_PATH = Path.home() / f"{APP_NAME}.log"
DEFAULT_JSON_PATH = Path.home() / f"{APP_NAME}.jsonl"


# ----------------------------
# Utilities
# ----------------------------
def which(cmd: str) -> Optional[str]:
    return shutil.which(cmd)


def run_cmd(cmd: List[str], timeout_s: int = 120) -> Tuple[int, str, str]:
    """Run a command safely and return (exit_code, stdout, stderr)."""
    try:
        p = subprocess.run(
            cmd,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_s,
        )
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except FileNotFoundError:
        return 127, "", f"Command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", f"Timeout after {timeout_s}s: {' '.join(cmd)}"


def now_iso() -> str:
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


def human_mbps(bits_per_second: float) -> float:
    return (bits_per_second / 1_000_000.0) if bits_per_second is not None else float("nan")


def safe_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(x)
    except (TypeError, ValueError):
        return None


def write_jsonl(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def write_log(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(line.rstrip() + "\n")


def ansi(color: str) -> str:
    colors = {
        "reset": "\033[0m",
        "dim": "\033[2m",
        "bold": "\033[1m",
        "red": "\033[31m",
        "green": "\033[32m",
        "yellow": "\033[33m",
        "cyan": "\033[36m",
    }
    return colors.get(color, "")


def supports_color() -> bool:
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


# ----------------------------
# Data models
# ----------------------------
@dataclass
class PingStats:
    target: str
    sent: int
    received: int
    loss_pct: float
    rtt_min_ms: Optional[float]
    rtt_avg_ms: Optional[float]
    rtt_max_ms: Optional[float]
    jitter_ms: Optional[float]  # avg abs diff between consecutive RTTs


@dataclass
class OoklaResult:
    server_name: Optional[str]
    server_id: Optional[str]
    server_host: Optional[str]
    server_location: Optional[str]
    isp: Optional[str]
    external_ip: Optional[str]
    idle_latency_ms: Optional[float]
    jitter_ms: Optional[float]
    low_latency_ms: Optional[float]
    high_latency_ms: Optional[float]
    download_mbps: Optional[float]
    upload_mbps: Optional[float]
    download_bytes: Optional[int]
    upload_bytes: Optional[int]
    packet_loss_pct: Optional[float]
    raw: Dict[str, Any]


@dataclass
class NetworkQualityResult:
    uplink_mbps: Optional[float]
    downlink_mbps: Optional[float]
    uplink_resp_rpm: Optional[float]
    downlink_resp_rpm: Optional[float]
    uplink_resp_ms: Optional[float]
    downlink_resp_ms: Optional[float]
    idle_latency_ms: Optional[float]
    raw_text: str


@dataclass
class EnvironmentInfo:
    timestamp: str
    hostname: str
    os: str
    machine: str
    python: str
    default_interface: Optional[str]
    local_ip: Optional[str]


# ----------------------------
# Environment / host info
# ----------------------------
def get_default_interface_and_ip() -> Tuple[Optional[str], Optional[str]]:
    """
    Best-effort: discover default route interface, then pull its IPv4 address.
    """
    rc, out, _ = run_cmd(["route", "-n", "get", "default"], timeout_s=10)
    if rc != 0:
        return None, None

    m = re.search(r"interface:\s+(\S+)", out)
    iface = m.group(1) if m else None
    if not iface:
        return None, None

    rc2, out2, _ = run_cmd(["ipconfig", "getifaddr", iface], timeout_s=5)
    ip = out2.strip() if rc2 == 0 and out2.strip() else None
    return iface, ip


def get_env_info() -> EnvironmentInfo:
    iface, ip = get_default_interface_and_ip()
    return EnvironmentInfo(
        timestamp=now_iso(),
        hostname=platform.node(),
        os=f"{platform.system()} {platform.release()}",
        machine=platform.machine(),
        python=platform.python_version(),
        default_interface=iface,
        local_ip=ip,
    )


def fetch_public_ip_info(timeout_s: int = 10) -> Dict[str, Any]:
    """
    Uses ipinfo.io's free endpoint. If it fails, returns empty dict.
    """
    url = "https://ipinfo.io/json"
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as resp:
            data = resp.read().decode("utf-8", errors="replace")
            return json.loads(data)
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError):
        return {}


def dns_lookup_time(host: str) -> Optional[float]:
    """
    Measures time spent in a simple DNS lookup via system resolver.
    """
    import socket

    start = time.perf_counter()
    try:
        socket.getaddrinfo(host, None, family=socket.AF_INET)
        return (time.perf_counter() - start) * 1000.0
    except OSError:
        return None


# ----------------------------
# Ping (ICMP) via system ping
# ----------------------------
def ping_target(target: str, count: int = 10, timeout_s: int = 20) -> Optional[PingStats]:
    """
    Uses /sbin/ping on macOS (no raw-socket Python requirements).
    Parses packet loss and RTT stats from standard output.
    """
    if not which("ping"):
        return None

    # macOS ping: -c count, -n numeric, -q quiet summary only
    rc, out, err = run_cmd(["ping", "-n", "-q", "-c", str(count), target], timeout_s=timeout_s)
    text = out + "\n" + err

    m = re.search(r"(\d+)\s+packets transmitted,\s+(\d+)\s+packets received,\s+([\d.]+)%\s+packet loss", text)
    if not m:
        return None
    sent = int(m.group(1))
    received = int(m.group(2))
    loss = float(m.group(3))

    m2 = re.search(r"round-trip.*=\s*([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)\s*ms", text)
    rmin = safe_float(m2.group(1)) if m2 else None
    ravg = safe_float(m2.group(2)) if m2 else None
    rmax = safe_float(m2.group(3)) if m2 else None

    # Jitter approximation from per-packet RTT
    jitter = None
    if count >= 4:
        rc3, out3, _ = run_cmd(["ping", "-n", "-c", str(count), target], timeout_s=timeout_s)
        rtts = [safe_float(x) for x in re.findall(r"time=([\d.]+)\s*ms", out3)]
        rtts = [x for x in rtts if x is not None]
        if len(rtts) >= 2:
            diffs = [abs(rtts[i] - rtts[i - 1]) for i in range(1, len(rtts))]
            jitter = sum(diffs) / len(diffs)

    return PingStats(
        target=target,
        sent=sent,
        received=received,
        loss_pct=loss,
        rtt_min_ms=rmin,
        rtt_avg_ms=ravg,
        rtt_max_ms=rmax,
        jitter_ms=jitter,
    )


# ----------------------------
# Apple's networkQuality
# ----------------------------
def parse_network_quality_summary(text: str) -> NetworkQualityResult:
    """
    Parses networkQuality SUMMARY output.

    Variants exist across macOS versions, so parsing is defensive.
    """
    def grab_mbps(label: str) -> Optional[float]:
        m = re.search(rf"{label}\s+capacity:\s*([\d.]+)\s*Mbps", text, flags=re.I)
        return safe_float(m.group(1)) if m else None

    def grab_resp(label: str) -> Tuple[Optional[float], Optional[float]]:
        # returns (ms, rpm)
        m = re.search(rf"{label}\s+Responsiveness:.*\(([\d.]+)\s*milliseconds\s*\|\s*([\d.]+)\s*RPM\)", text, flags=re.I)
        if m:
            return safe_float(m.group(1)), safe_float(m.group(2))
        m2 = re.search(rf"{label}\s+Responsiveness:.*\(([\d.]+)\s*RPM\)", text, flags=re.I)
        if m2:
            return None, safe_float(m2.group(1))
        return None, None

    def grab_idle_latency() -> Optional[float]:
        m = re.search(r"Idle Latency:\s*([\d.]+)\s*milliseconds", text, flags=re.I)
        return safe_float(m.group(1)) if m else None

    up = grab_mbps("Uplink")
    down = grab_mbps("Downlink")
    up_ms, up_rpm = grab_resp("Uplink")
    down_ms, down_rpm = grab_resp("Downlink")
    idle = grab_idle_latency()

    return NetworkQualityResult(
        uplink_mbps=up,
        downlink_mbps=down,
        uplink_resp_rpm=up_rpm,
        downlink_resp_rpm=down_rpm,
        uplink_resp_ms=up_ms,
        downlink_resp_ms=down_ms,
        idle_latency_ms=idle,
        raw_text=text.strip(),
    )


def run_network_quality(timeout_s: int = 120) -> Optional[NetworkQualityResult]:
    if not which("networkQuality"):
        return None
    rc, out, err = run_cmd(["networkQuality", "-s"], timeout_s=timeout_s)
    text = (out + "\n" + err).strip()
    if rc != 0 or "SUMMARY" not in text.upper():
        return None
    return parse_network_quality_summary(text)


# ----------------------------
# Ookla Speedtest CLI
# ----------------------------
def parse_ookla_json(payload: Dict[str, Any]) -> OoklaResult:
    """
    Parses `speedtest -f json` output.

    Ookla machine-readable formats commonly use bytes/sec for bandwidth.
    We convert bytes/sec -> Mbps via (bytes/sec * 8) / 1_000_000.
    """
    server = payload.get("server") or {}
    isp = payload.get("isp")
    interface = payload.get("interface") or {}
    ping = payload.get("ping") or {}
    download = payload.get("download") or {}
    upload = payload.get("upload") or {}
    pl = payload.get("packetLoss")  # may be absent

    def server_location() -> Optional[str]:
        name = server.get("name")
        country = server.get("country")
        location = server.get("location")
        parts = [p for p in [name or location, country] if p]
        return ", ".join(parts) if parts else None

    def bytes_per_sec_to_mbps(x: Any) -> Optional[float]:
        v = safe_float(x)
        if v is None:
            return None
        return human_mbps(v * 8.0)

    idle = safe_float(ping.get("latency"))
    jitter = safe_float(ping.get("jitter"))
    low = safe_float(ping.get("low"))
    high = safe_float(ping.get("high"))

    dl = bytes_per_sec_to_mbps(download.get("bandwidth"))
    ul = bytes_per_sec_to_mbps(upload.get("bandwidth"))

    dl_bytes = download.get("bytes")
    ul_bytes = upload.get("bytes")

    def to_int_maybe(v: Any) -> Optional[int]:
        try:
            if v is None:
                return None
            return int(v)
        except (TypeError, ValueError):
            return None

    return OoklaResult(
        server_name=server.get("name"),
        server_id=str(server.get("id")) if server.get("id") is not None else None,
        server_host=server.get("host"),
        server_location=server_location(),
        isp=isp,
        external_ip=interface.get("externalIp"),
        idle_latency_ms=idle,
        jitter_ms=jitter,
        low_latency_ms=low,
        high_latency_ms=high,
        download_mbps=dl,
        upload_mbps=ul,
        download_bytes=to_int_maybe(dl_bytes),
        upload_bytes=to_int_maybe(ul_bytes),
        packet_loss_pct=safe_float(pl),
        raw=payload,
    )


def run_ookla_speedtest(
    timeout_s: int = 180,
    server_id: Optional[str] = None,
) -> Optional[OoklaResult]:
    if not which("speedtest"):
        return None

    cmd = ["speedtest", "--accept-license", "--accept-gdpr", "-f", "json"]
    if server_id:
        cmd += ["-s", str(server_id)]

    rc, out, _ = run_cmd(cmd, timeout_s=timeout_s)
    if rc != 0:
        return None

    try:
        payload = json.loads(out)
        return parse_ookla_json(payload)
    except json.JSONDecodeError:
        return None


# ----------------------------
# Rendering
# ----------------------------
def format_table(rows: List[Tuple[str, str]]) -> str:
    w = max(len(k) for k, _ in rows) if rows else 0
    out = []
    for k, v in rows:
        out.append(f"{k:<{w}} : {v}")
    return "\n".join(out)


def maybe_c(s: str, color: str) -> str:
    if supports_color():
        return f"{ansi(color)}{s}{ansi('reset')}"
    return s


def _fmt_resp(ms: Optional[float], rpm: Optional[float]) -> str:
    if ms is not None and rpm is not None:
        return f"{ms:.3f} ms | {rpm:.0f} RPM"
    if rpm is not None:
        return f"{rpm:.0f} RPM"
    if ms is not None:
        return f"{ms:.3f} ms"
    return "n/a"


def _fmt_rtt(rmin: Optional[float], ravg: Optional[float], rmax: Optional[float]) -> str:
    parts = []
    for label, v in [("min", rmin), ("avg", ravg), ("max", rmax)]:
        parts.append(f"{label} {v:.2f} ms" if v is not None else f"{label} n/a")
    return ", ".join(parts)


def print_report(
    env: EnvironmentInfo,
    ipinfo: Dict[str, Any],
    ping_stats: List[PingStats],
    nq: Optional[NetworkQualityResult],
    ookla: Optional[OoklaResult],
) -> None:
    print(maybe_c(f"\n{APP_NAME} - {env.timestamp}\n", "bold"))

    env_rows = [
        ("Host", env.hostname),
        ("OS", env.os),
        ("Machine", env.machine),
        ("Python", env.python),
        ("Default iface", env.default_interface or "unknown"),
        ("Local IP", env.local_ip or "unknown"),
    ]
    if ipinfo:
        env_rows += [
            ("Public IP", ipinfo.get("ip", "unknown")),
            ("ISP/Org", ipinfo.get("org", "unknown")),
            ("Location", ", ".join([x for x in [ipinfo.get("city"), ipinfo.get("region"), ipinfo.get("country")] if x]) or "unknown"),
        ]
    print(maybe_c("Environment", "cyan"))
    print(format_table(env_rows))

    if ookla:
        print(maybe_c("\nOokla Speedtest (CLI)", "cyan"))
        rows = [
            ("Server", f"{ookla.server_name or 'unknown'} ({ookla.server_id or 'n/a'})"),
            ("Server host", ookla.server_host or "unknown"),
            ("Server location", ookla.server_location or "unknown"),
            ("ISP", ookla.isp or "unknown"),
            ("Idle latency", f"{ookla.idle_latency_ms:.2f} ms" if ookla.idle_latency_ms is not None else "n/a"),
            ("Jitter", f"{ookla.jitter_ms:.2f} ms" if ookla.jitter_ms is not None else "n/a"),
            ("Download", f"{ookla.download_mbps:.2f} Mbps" if ookla.download_mbps is not None else "n/a"),
            ("Upload", f"{ookla.upload_mbps:.2f} Mbps" if ookla.upload_mbps is not None else "n/a"),
            ("Packet loss", f"{ookla.packet_loss_pct:.2f}%" if ookla.packet_loss_pct is not None else "n/a"),
        ]
        print(format_table(rows))
    else:
        print(maybe_c("\nOokla Speedtest (CLI)", "cyan"))
        print(maybe_c("  Not available (install `speedtest` CLI for best parity with Ookla app).", "yellow"))

    if nq:
        print(maybe_c("\nApple networkQuality", "cyan"))
        rows = [
            ("Downlink capacity", f"{nq.downlink_mbps:.3f} Mbps" if nq.downlink_mbps is not None else "n/a"),
            ("Uplink capacity", f"{nq.uplink_mbps:.3f} Mbps" if nq.uplink_mbps is not None else "n/a"),
            ("Downlink responsiveness", _fmt_resp(nq.downlink_resp_ms, nq.downlink_resp_rpm)),
            ("Uplink responsiveness", _fmt_resp(nq.uplink_resp_ms, nq.uplink_resp_rpm)),
            ("Idle latency", f"{nq.idle_latency_ms:.3f} ms" if nq.idle_latency_ms is not None else "n/a"),
        ]
        print(format_table(rows))
    else:
        print(maybe_c("\nApple networkQuality", "cyan"))
        print(maybe_c("  Not available (should exist on macOS 12+).", "yellow"))

    if ping_stats:
        print(maybe_c("\nICMP Ping baselines", "cyan"))
        for ps in ping_stats:
            rows = [
                ("Target", ps.target),
                ("Loss", f"{ps.loss_pct:.1f}% ({ps.received}/{ps.sent})"),
                ("RTT min/avg/max", _fmt_rtt(ps.rtt_min_ms, ps.rtt_avg_ms, ps.rtt_max_ms)),
                ("Jitter", f"{ps.jitter_ms:.2f} ms" if ps.jitter_ms is not None else "n/a"),
            ]
            print(format_table(rows))
            print()
    else:
        print(maybe_c("\nICMP Ping baselines", "cyan"))
        print(maybe_c("  Ping unavailable.", "yellow"))

    print(maybe_c("Tip", "dim"))
    print(maybe_c("  Run 3–5 samples and look at the median. If results vary wildly, something is loading the link.", "dim"))


# ----------------------------
# Orchestration
# ----------------------------
def run_once(args: argparse.Namespace) -> Dict[str, Any]:
    env = get_env_info()
    ipinfo = fetch_public_ip_info(timeout_s=args.http_timeout) if args.include_ipinfo else {}
    dns_ms = dns_lookup_time(args.dns_probe_host) if args.dns_probe_host else None

    ookla = run_ookla_speedtest(timeout_s=args.ookla_timeout, server_id=args.server_id) if args.use_ookla else None
    nq = run_network_quality(timeout_s=args.nq_timeout) if args.use_networkquality else None

    ping_targets = list(args.ping_target) if args.ping_target else []
    if args.ping_speedtest_server and ookla and ookla.server_host:
        ping_targets.insert(0, ookla.server_host.split(":")[0])

    ping_stats: List[PingStats] = []
    if args.use_ping and ping_targets:
        for t in ping_targets:
            ps = ping_target(t, count=args.ping_count, timeout_s=args.ping_timeout)
            if ps:
                ping_stats.append(ps)

    record: Dict[str, Any] = {
        "timestamp": env.timestamp,
        "env": dataclasses.asdict(env),
        "ipinfo": ipinfo,
        "dns_lookup_ms": dns_ms,
        "results": {
            "ookla": dataclasses.asdict(ookla) if ookla else None,
            "networkQuality": dataclasses.asdict(nq) if nq else None,
            "ping": [dataclasses.asdict(p) for p in ping_stats],
        },
        "tooling": {
            "has_speedtest": bool(which("speedtest")),
            "has_networkQuality": bool(which("networkQuality")),
            "has_ping": bool(which("ping")),
        },
    }
    return record


def median(values: List[float]) -> Optional[float]:
    vs = [v for v in values if v is not None]
    if not vs:
        return None
    vs.sort()
    mid = len(vs) // 2
    if len(vs) % 2 == 1:
        return vs[mid]
    return (vs[mid - 1] + vs[mid]) / 2.0


def summarize_runs(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    dl = []
    ul = []
    idle = []
    jitter = []
    nq_down = []
    nq_up = []
    for r in records:
        ookla = (r.get("results") or {}).get("ookla") or {}
        if ookla:
            dl.append(ookla.get("download_mbps"))
            ul.append(ookla.get("upload_mbps"))
            idle.append(ookla.get("idle_latency_ms"))
            jitter.append(ookla.get("jitter_ms"))
        nq = (r.get("results") or {}).get("networkQuality") or {}
        if nq:
            nq_down.append(nq.get("downlink_mbps"))
            nq_up.append(nq.get("uplink_mbps"))

    return {
        "runs": len(records),
        "median": {
            "download_mbps": median([safe_float(x) for x in dl]),
            "upload_mbps": median([safe_float(x) for x in ul]),
            "idle_latency_ms": median([safe_float(x) for x in idle]),
            "jitter_ms": median([safe_float(x) for x in jitter]),
            "nq_downlink_mbps": median([safe_float(x) for x in nq_down]),
            "nq_uplink_mbps": median([safe_float(x) for x in nq_up]),
        },
    }


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=APP_NAME,
        description="Run macOS-friendly network speed + quality tests (Ookla + networkQuality + ping).",
    )

    p.add_argument("--runs", type=int, default=1, help="Number of samples to run (recommend 3-5).")
    p.add_argument("--sleep-between", type=float, default=2.0, help="Seconds to sleep between runs.")

    # Ookla
    p.add_argument("--no-ookla", dest="use_ookla", action="store_false", help="Disable Ookla speedtest CLI.")
    p.add_argument("--server-id", type=str, default=None, help="Force Ookla server id (-s).")
    p.add_argument("--ookla-timeout", type=int, default=180, help="Timeout for Ookla speedtest CLI.")

    # networkQuality
    p.add_argument("--no-networkquality", dest="use_networkquality", action="store_false", help="Disable Apple networkQuality.")
    p.add_argument("--nq-timeout", type=int, default=120, help="Timeout for networkQuality.")

    # ping
    p.add_argument("--no-ping", dest="use_ping", action="store_false", help="Disable ICMP ping baselines.")
    p.add_argument("--ping-target", action="append", default=["1.1.1.1", "8.8.8.8"], help="Ping target (repeatable).")
    p.add_argument("--ping-speedtest-server", action="store_true", help="Also ping the chosen speedtest server host (if known).")
    p.add_argument("--ping-count", type=int, default=10, help="ICMP pings per target.")
    p.add_argument("--ping-timeout", type=int, default=20, help="Timeout per ping target test.")

    # ipinfo / dns
    p.add_argument("--no-ipinfo", dest="include_ipinfo", action="store_false", help="Disable public IP geo/org lookup.")
    p.add_argument("--http-timeout", type=int, default=10, help="HTTP timeout for ipinfo.")
    p.add_argument("--dns-probe-host", type=str, default="icloud.com", help="Host used for DNS timing probe (set empty to disable).")

    # output
    p.add_argument("--jsonl", type=Path, default=DEFAULT_JSON_PATH, help="Path to append JSONL results.")
    p.add_argument("--log", type=Path, default=DEFAULT_LOG_PATH, help="Path to append human logs.")
    p.add_argument("--quiet", action="store_true", help="Suppress human output; still writes JSONL/log.")
    p.add_argument("--print-raw", action="store_true", help="Print raw tool outputs (debugging).")

    p.set_defaults(use_ookla=True, use_networkquality=True, use_ping=True, include_ipinfo=True)
    return p


def main() -> int:
    args = build_arg_parser().parse_args()

    records: List[Dict[str, Any]] = []
    for i in range(args.runs):
        record = run_once(args)
        records.append(record)

        write_jsonl(args.jsonl, record)
        write_log(args.log, f"{record['timestamp']} {json.dumps(record['results']['ookla'] or {}, ensure_ascii=False)}")

        if not args.quiet:
            env = EnvironmentInfo(**record["env"])
            ipinfo = record.get("ipinfo") or {}
            ping_list = [PingStats(**p) for p in ((record.get("results") or {}).get("ping") or [])]
            nq_dict = (record.get("results") or {}).get("networkQuality")
            nq = NetworkQualityResult(**nq_dict) if nq_dict else None
            ookla_dict = (record.get("results") or {}).get("ookla")
            ookla = OoklaResult(**ookla_dict) if ookla_dict else None

            print_report(env, ipinfo, ping_list, nq, ookla)

            if args.print_raw:
                if ookla and ookla.raw:
                    print(maybe_c("\nRaw Ookla JSON", "yellow"))
                    print(json.dumps(ookla.raw, indent=2, ensure_ascii=False))
                if nq:
                    print(maybe_c("\nRaw networkQuality output", "yellow"))
                    print(nq.raw_text)

        if i < args.runs - 1:
            time.sleep(max(0.0, args.sleep_between))

    summary = summarize_runs(records)
    write_jsonl(args.jsonl, {"summary": summary, "timestamp": now_iso()})

    if not args.quiet:
        print(maybe_c("\nSummary (median)", "green"))
        for k, v in summary["median"].items():
            if v is None:
                vv = "n/a"
            elif "mbps" in k:
                vv = f"{v:.2f} Mbps"
            else:
                vv = f"{v:.2f}"
            print(f"  {k}: {vv}")

        print(maybe_c(f"\nSaved:", "dim"))
        print(maybe_c(f"  JSONL: {args.jsonl}", "dim"))
        print(maybe_c(f"  Log  : {args.log}", "dim"))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
