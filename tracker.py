#!/usr/bin/env python3
"""Run from GitHub Actions. No local Python installation is needed for hosted use."""
from __future__ import annotations

import argparse
import json
import os
import sys

from sote.engine import read_config, run_scan
from sote.budget import price_limit_label
from sote.model import Listing, target_name
from sote.notify import Discord, NotificationError
from sote.storage import GitHubStore, LocalStore, StorageError


def main() -> int:
    parser = argparse.ArgumentParser(description="Configured PS5 disc and price watcher")
    parser.add_argument("--mode", choices=["test", "scan", "status", "dry-run", "demo"], default="scan")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--state-file", default="state.json")
    args = parser.parse_args()
    cfg = read_config(args.config)
    target = cfg.get("target", "sote")
    if args.mode == "demo":
        sample = Listing("EXAMPLE ONLY - not a real store", f"{target_name(target)} PS5",
                         "https://example.com/fictional-product", status="in_stock", variant="Pre-Owned",
                         condition="Used (seller label)", price="3,900.00", dlc="Not included (seller statement)",
                         evidence="Synthetic demonstration; not a live listing")
        print(json.dumps(sample.as_dict(), indent=2))
        return 0
    notifier = None if args.mode == "dry-run" else Discord(target=target, max_price_inr=cfg.get("max_price_inr"))
    if args.mode == "test":
        notifier.send(f"TEST: {target_name(target)} tracker connected",
                       f"Target: {target_name(target)} PS5. Price limit: {price_limit_label(cfg.get('max_price_inr'))}. "
                       f"Daily health messages: {'on' if cfg.get('daily_health', False) else 'off'}. "
                       "This confirms GitHub can post here. It is NOT a stock alert. "
                       "Next run the workflow in 'status' mode for the first store scan. "
                       "Check phone notification permissions with your phone locked.")
        print("Discord acknowledged the test message. Phone push delivery still needs your check.")
        return 0
    dry = args.mode == "dry-run"
    if os.getenv("GITHUB_ACTIONS") == "true" and not dry:
        store = GitHubStore()
    else:
        store = LocalStore(args.state_file)
    return run_scan(cfg, store, notifier, dry_run=dry, force_health=args.mode == "status")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (NotificationError, StorageError, ValueError, OSError) as exc:
        print(f"SETUP/RUN ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
