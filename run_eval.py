#!/usr/bin/env python3
"""Evaluation Runner for magicpin Vera AI Challenge.

Pre-flight checks:
1. Verifies python dependencies.
2. Checks if the bot is already live on http://localhost:8080.
3. If not live, displays command to start Uvicorn or optionally spawns it.
4. Executes judge_simulator.py across targeted scenarios and reports results.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from typing import List, Tuple
from urllib import request as urlrequest
from urllib import error as urlerror

BOT_HOST = "127.0.0.1"
BOT_PORT = 8080
BASE_URL = f"http://{BOT_HOST}:{BOT_PORT}"
JUDGE_SCRIPT = "judge_simulator.py"

# Terminal styling
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def print_status(tag: str, msg: str, color: str = CYAN) -> None:
    print(f"{color}{BOLD}[{tag}]{RESET} {msg}")


def is_port_open(host: str, port: int) -> bool:
    """Checks if a TCP socket is listening on the host and port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1.0)
        return sock.connect_ex((host, port)) == 0


def verify_bot_health(url: str) -> bool:
    """Pings /v1/healthz to ensure the bot is answering correctly."""
    try:
        req = urlrequest.Request(f"{url}/v1/healthz", headers={"Accept": "application/json"})
        with urlrequest.urlopen(req, timeout=3.0) as resp:
            return resp.status == 200
    except (urlerror.URLError, TimeoutError, ConnectionRefusedError):
        return False


def run_scenario(scenario_name: str) -> Tuple[bool, str]:
    """Executes a single scenario via judge_simulator.py."""
    if not os.path.exists(JUDGE_SCRIPT):
        return False, f"Cannot find '{JUDGE_SCRIPT}' in current directory."

    env = os.environ.copy()
    # Ensure stdout/stderr decode cleanly
    env["PYTHONUNBUFFERED"] = "1"

    cmd = [sys.executable, JUDGE_SCRIPT]
    print_status("RUN", f"Executing scenario '{scenario_name}'...", CYAN)

    # Note: If judge_simulator.py expects TEST_SCENARIO inside the script,
    # we can pass it as an argument or let it run its configured test.
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env,
    )

    combined_output = proc.stdout + "\n" + proc.stderr
    passed = (proc.returncode == 0) and ("[FAIL]" not in proc.stdout)

    return passed, combined_output


def main() -> None:
    print_status("INIT", "Starting magicpin Vera Evaluation Runner", BOLD)

    # 1. Check judge_simulator.py existence
    if not os.path.exists(JUDGE_SCRIPT):
        print_status("FAIL", f"'{JUDGE_SCRIPT}' not found. Please place it in the project root.", RED)
        sys.exit(1)

    # 2. Check if the bot server is running
    print_status("CHECK", f"Checking if bot is live at {BASE_URL}...", CYAN)
    if not is_port_open(BOT_HOST, BOT_PORT):
        print_status("WARN", f"Port {BOT_PORT} is not responding.", YELLOW)
        print(f"\n{YELLOW}Please start your bot in a separate terminal before evaluating:{RESET}")
        print(f"  {BOLD}uvicorn app.main:app --host 0.0.0.0 --port {BOT_PORT} --reload{RESET}\n")
        sys.exit(1)

    # 3. Check healthz endpoint
    if not verify_bot_health(BASE_URL):
        print_status("FAIL", f"Port {BOT_PORT} is open, but GET /v1/healthz did not return HTTP 200.", RED)
        sys.exit(1)

    print_status("PASS", "Bot is live and healthy!", GREEN)

    # 4. Scenarios to test
    # By default, judge_simulator.py runs the scenario configured in its file (e.g. 'all' or 'phase2_short')
    scenarios_to_evaluate: List[str] = [
        "all",  # Runs warmup, auto_reply, intent, hostile
    ]

    summary_results: List[Tuple[str, bool]] = []

    for scenario in scenarios_to_evaluate:
        print("\n" + "=" * 60)
        passed, log = run_scenario(scenario)

        # Print the live judge output
        print(log.strip())

        summary_results.append((scenario, passed))
        if passed:
            print_status("RESULT", f"Scenario '{scenario}' PASSED!", GREEN)
        else:
            print_status("RESULT", f"Scenario '{scenario}' FAILED or dropped points.", RED)

    # 5. Final Summary Table
    print("\n" + "=" * 60)
    print_status("SUMMARY", "Evaluation Complete", BOLD)
    all_passed = True
    for name, success in summary_results:
        status_text = f"{GREEN}PASS{RESET}" if success else f"{RED}FAIL{RESET}"
        print(f"  * {name:<25}: {status_text}")
        if not success:
            all_passed = False

    if all_passed:
        print_status("SUCCESS", "All targeted scenarios passed without operational penalties!", GREEN)
        sys.exit(0)
    else:
        print_status("ALERT", "One or more evaluation tests encountered errors or penalties.", RED)
        sys.exit(1)


if __name__ == "__main__":
    main()