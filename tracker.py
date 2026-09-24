#!/usr/bin/env python3
"""Run from GitHub Actions. No local Python installation is needed for hosted use."""
from __future__ import annotations

import argparse
import json
import os
import sys

from sote.engine import read_config, run_scan
from sote.model import Listing
from sote.notify import Discord, NotificationError
from sote.storage import GitHubStore, LocalStore, StorageError


def main() -> int:
    parser = argparse.ArgumentParser(description="PS5 Shadow of the Erdtree availability watcher")
    parser.add_argument("--mode", choices=["test", "scan", "status", "dry-run", "demo"], default="scan")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--state-file", default="state.json")
    args = parser.parse_args()
    if args.mode == "demo":
        sample = Listing("EXAMPLE ONLY - not a real store", "Elden Ring Shadow of the Erdtree Edition PS5",
                         "https://example.com/fictional-product", status="in_stock", variant="Pre-Owned (WITHOUT DLC CODE)",
                         condition="Used (seller label)", price="2,800.00", dlc="Not included (seller statement)",
                         evidence="Synthetic demonstration; not a live listing")
        print(json.dumps(sample.as_dict(), indent=2))
        return 0
    if args.mode == "test":
        Discord().send("TEST: SOTE tracker connected",
                       "This confirms GitHub can post to this Discord channel. It is NOT a stock alert. "
                       "Next run the workflow in 'status' mode for the first store scan. "
                       "Check phone notification permissions with your phone locked.")
        print("Discord acknowledged the test message. Phone push delivery still needs your check.")
        return 0
    cfg = read_config(args.config)
    dry = args.mode == "dry-run"
    if os.getenv("GITHUB_ACTIONS") == "true" and not dry:
        store = GitHubStore()
    else:
        store = LocalStore(args.state_file)
    return run_scan(cfg, store, None if dry else Discord(), dry_run=dry, force_health=args.mode == "status")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (NotificationError, StorageError, ValueError, OSError) as exc:
        print(f"SETUP/RUN ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
