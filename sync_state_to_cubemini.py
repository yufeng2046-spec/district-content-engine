#!/usr/bin/env python3
"""
Sync local Anjuke browser state to CubeMini for headless scraping.

Supports per-city state files (anjuke_state_{city}.json) and legacy
global state (anjuke_state.json). Syncs all state files + shows CubeMini
status.

Usage:
    python3 sync_state_to_cubemini.py                    # Sync all states + show status
    python3 sync_state_to_cubemini.py --kill             # Kill CubeMini scrapers + sync
    python3 sync_state_to_cubemini.py --restart CITY DISTRICT  # Kill + sync + restart scrape
    python3 sync_state_to_cubemini.py --no-sync          # Show status only (skip sync)
"""

import os, sys, time, json, glob
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# ═══ CubeMini connection ═══
# 2026-08-28: 跳板机公网 IP 从 120.12.17.243 改为 120.12.31.54 (用户提供)
JUMP_HOST = "120.12.31.54"
JUMP_PORT = 2222
JUMP_USER = "frank"
JUMP_PASS = "0808"
TARGET_HOST = "192.168.31.101"
TARGET_USER = "frank"
TARGET_PASS = "0808"

REMOTE_DIR = "/home/frank/district-content-engine"


def ssh_exec(cmd: str, timeout: int = 15) -> tuple[str, str]:
    """Execute command on CubeMini, returns (stdout, stderr)."""
    import paramiko

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(JUMP_HOST, JUMP_PORT, JUMP_USER, JUMP_PASS,
                   allow_agent=False, look_for_keys=False, timeout=15)
    transport = client.get_transport()
    channel = transport.open_channel(
        "direct-tcpip", (TARGET_HOST, 22), ("127.0.0.1", 0), timeout=15
    )

    target = paramiko.SSHClient()
    target.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    target.connect(TARGET_HOST, 22, TARGET_USER, TARGET_PASS,
                   sock=channel, allow_agent=False, look_for_keys=False, timeout=15)

    stdin, stdout, stderr = target.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode()
    err = stderr.read().decode()

    channel.close()
    target.close()
    client.close()
    return out, err


def ssh_sftp_put(local: str, remote: str) -> None:
    """Copy file to CubeMini via SFTP."""
    import paramiko

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(JUMP_HOST, JUMP_PORT, JUMP_USER, JUMP_PASS,
                   allow_agent=False, look_for_keys=False, timeout=15)
    transport = client.get_transport()
    channel = transport.open_channel(
        "direct-tcpip", (TARGET_HOST, 22), ("127.0.0.1", 0), timeout=15
    )

    target = paramiko.SSHClient()
    target.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    target.connect(TARGET_HOST, 22, TARGET_USER, TARGET_PASS,
                   sock=channel, allow_agent=False, look_for_keys=False, timeout=15)

    sftp = target.open_sftp()
    sftp.put(local, remote)
    sftp.close()
    channel.close()
    target.close()
    client.close()


def ssh_sftp_get(local: str, remote: str) -> None:
    """Copy file FROM CubeMini via SFTP (mirror of ssh_sftp_put)."""
    import paramiko

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(JUMP_HOST, JUMP_PORT, JUMP_USER, JUMP_PASS,
                   allow_agent=False, look_for_keys=False, timeout=15)
    transport = client.get_transport()
    channel = transport.open_channel(
        "direct-tcpip", (TARGET_HOST, 22), ("127.0.0.1", 0), timeout=15
    )

    target = paramiko.SSHClient()
    target.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    target.connect(TARGET_HOST, 22, TARGET_USER, TARGET_PASS,
                   sock=channel, allow_agent=False, look_for_keys=False, timeout=15)

    sftp = target.open_sftp()
    sftp.get(remote, local)
    sftp.close()
    channel.close()
    target.close()
    client.close()


def show_status():
    """Show CubeMini scraping status and DB stats."""
    print("\n📊 CubeMini Status:")
    out, _ = ssh_exec(
        "cd /home/frank/district-content-engine && "
        "PYTHONPATH=/home/frank/district-content-engine "
        "/home/frank/crawler-venv/bin/python3 -c \"\n"
        "from db.connection import get_db\n"
        "conn = get_db()\n"
        "total = conn.execute('SELECT COUNT(*) FROM communities').fetchone()[0]\n"
        "detail = conn.execute('SELECT COUNT(*) FROM communities WHERE detail_scraped_at IS NOT NULL').fetchone()[0]\n"
        "with_sq = conn.execute('SELECT COUNT(*) FROM communities WHERE shangquan_id IS NOT NULL').fetchone()[0]\n"
        "print(f'DB: {total:,} communities | {detail:,} w/ details | {with_sq:,} w/ shangquan_id')\n"
        "for row in conn.execute('''\n"
        "    SELECT COALESCE(d.city_name, substr(c.region_id,1,instr(c.region_id||\\\"_\\\",\\\"_\\\")-1)) as city,\n"
        "           COUNT(DISTINCT c.region_id) as dists, COUNT(*) as total\n"
        "    FROM communities c\n"
        "    LEFT JOIN districts d ON c.region_id = d.slug\n"
        "    GROUP BY 1 ORDER BY total DESC LIMIT 10\n"
        "''').fetchall():\n"
        "    print(f'  {row[0]:10s}: {row[1]:>2}区, {row[2]:>6}小区')\n"
        "conn.close()\n"
        "\"",
        timeout=15,
    )
    for line in out.strip().split("\n"):
        if line.strip():
            print(f"  {line.strip()}")

    # Check running processes
    out, _ = ssh_exec(
        "ps aux | grep -E 'scrape_anjuke|cube_' | grep -v grep || echo '  (no scraper running)'",
        timeout=10,
    )
    has_process = False
    for line in out.strip().split("\n"):
        if "python" in line.lower() or "scrape" in line.lower():
            print(f"  🔄 {line.strip()[:120]}")
            has_process = True
    if not has_process:
        print("  ⏸️  No scraper running")


def show_local_sessions() -> None:
    """Show status of all per-city state files locally."""
    print("\n📂 Local State Files:")
    state_files = sorted(BASE_DIR.glob("anjuke_state*.json"))
    if not state_files:
        print("  (no state files found)")
        return

    for sf in state_files:
        age_min = (time.time() - sf.stat().st_mtime) / 60
        size_kb = sf.stat().st_size / 1024
        age_str = f"{age_min:.0f}min" if age_min < 60 else f"{age_min/60:.1f}h"
        status = "✅" if age_min < 120 else ("⚠️" if age_min < 480 else "❌")
        # Extract city name from filename
        name = sf.stem
        if name.startswith("anjuke_state_"):
            city = name.replace("anjuke_state_", "")
            print(f"  {status} {city:<12s} {size_kb:>6.0f}KB  {age_str}")
        else:
            print(f"  {status} {sf.name:<20s} {size_kb:>6.0f}KB  {age_str}")

    # Also check cookies
    cookies = BASE_DIR / "anjuke_cookies.json"
    if cookies.exists():
        age_min = (time.time() - cookies.stat().st_mtime) / 60
        print(f"  🍪 anjuke_cookies.json  {cookies.stat().st_size/1024:.0f}KB  {age_min:.0f}min")


def show_cubemini_sessions() -> None:
    """Check per-city state files on CubeMini."""
    print("\n📂 CubeMini State Files:")
    out, _ = ssh_exec(
        f"ls -lh {REMOTE_DIR}/anjuke_state*.json 2>/dev/null || echo '(none)'",
        timeout=10,
    )
    for line in out.strip().split("\n"):
        if line.strip() and "(none)" not in line:
            print(f"  {line.strip()}")
        elif "(none)" in line:
            print("  (no state files on CubeMini)")


def sync_state():
    """Copy ALL local state files to CubeMini."""
    print("\n📤 Syncing state files to CubeMini...")

    state_files = sorted(BASE_DIR.glob("anjuke_state*.json"))
    if not state_files:
        print("  ❌ No state files found locally")
        return False

    synced = 0
    for sf in state_files:
        try:
            ssh_sftp_put(str(sf), f"{REMOTE_DIR}/{sf.name}")
            size_kb = sf.stat().st_size / 1024
            age_min = (time.time() - sf.stat().st_mtime) / 60
            print(f"  ✅ {sf.name} ({size_kb:.0f}KB, {age_min:.0f}min ago)")
            synced += 1
        except Exception as e:
            print(f"  ❌ {sf.name}: {e}")

    # Sync cookies separately
    cookies = BASE_DIR / "anjuke_cookies.json"
    if cookies.exists():
        try:
            ssh_sftp_put(str(cookies), f"{REMOTE_DIR}/anjuke_cookies.json")
            print(f"  🍪 anjuke_cookies.json ({cookies.stat().st_size/1024:.0f}KB)")
            synced += 1
        except Exception as e:
            print(f"  ❌ cookies: {e}")

    print(f"  Synced {synced} files")
    return synced > 0


def kill_scraper():
    """Kill any running scraper on CubeMini."""
    print("\n🛑 Stopping CubeMini scrapers...")
    out, _ = ssh_exec(
        "pkill -f 'scrape_anjuke.py' 2>/dev/null; "
        "pkill -f 'cube_expand.py' 2>/dev/null; "
        "sleep 1; echo 'done'",
        timeout=10,
    )
    print(f"  ✅ Scrapers stopped")


def restart_scrape(city: str, district: str):
    """Start a new scrape on CubeMini with per-city state file."""
    region_id = f"{city}_{district}"
    state_name = f"anjuke_state_{city}.json"
    legacy_name = "anjuke_state.json"

    # Check which state file to use
    out, _ = ssh_exec(
        f"if [ -f {REMOTE_DIR}/{state_name} ]; then echo 'per_city'; "
        f"elif [ -f {REMOTE_DIR}/{legacy_name} ]; then echo 'legacy'; "
        f"else echo 'none'; fi",
        timeout=5,
    )
    state_type = out.strip()

    if state_type == "per_city":
        state_arg = f"--state {REMOTE_DIR}/{state_name}"
        print(f"  📂 Using per-city state: {state_name}")
    elif state_type == "legacy":
        state_arg = ""
        print(f"  📂 Using legacy state (no per-city file for {city})")
    else:
        print(f"  ⚠️  No state file found on CubeMini! Run sync first.")
        return

    cmd = (
        f"cd {REMOTE_DIR} && "
        f"PYTHONPATH={REMOTE_DIR} "
        f"nohup /home/frank/crawler-venv/bin/python3 data/scrape_anjuke.py "
        f"--region {region_id} --shangquan all {state_arg} "
        f">> /tmp/cube_{district}.log 2>&1 &"
        f"echo PID=\\$!"
    )
    print(f"\n🚀 Starting CubeMini scrape: {region_id}")
    try:
        out, err = ssh_exec(cmd, timeout=8)
        print(f"  {out.strip()}")
        if err and "SyntaxWarning" not in err:
            print(f"  STDERR: {err[:200]}")
    except Exception:
        # nohup & causes paramiko timeout — process is still running on CubeMini
        print(f"  ✅ Launched (detached) — check /tmp/cube_{district}.log")


def main():
    kill = "--kill" in sys.argv
    restart = "--restart" in sys.argv
    no_sync = "--no-sync" in sys.argv
    city = district = None
    if restart:
        try:
            idx = sys.argv.index("--restart")
            city = sys.argv[idx + 1]
            district = sys.argv[idx + 2]
        except (ValueError, IndexError):
            print("Usage: --restart CITY DISTRICT  (e.g. --restart shanghai pudong)")
            return

    print("=" * 50)
    print("Anjuke State Sync → CubeMini")
    print("=" * 50)

    if kill or restart:
        kill_scraper()
        time.sleep(2)

    if not no_sync:
        sync_state()
    else:
        print("\n⏭️  Skipping sync (--no-sync)")

    show_local_sessions()

    if not no_sync:
        time.sleep(1)
        show_cubemini_sessions()

    if restart and city and district:
        time.sleep(2)
        restart_scrape(city, district)

    time.sleep(2)
    show_status()

    print("\n✅ Done")
    if not restart:
        print("💡 To restart scraping: python3 sync_state_to_cubemini.py --restart CITY DISTRICT")
        print("💡 To create sessions:   python3 session_factory.py")


if __name__ == "__main__":
    main()
