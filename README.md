# Pragmata PS5 disc watcher - INR 4,000 or less

This repository was migrated from the SOTE watcher. The `sote` package folder
and existing Actions workflow label are retained for compatibility.

## Active configuration
- `target`: `pragmata`
- `max_price_inr`: `4000` (inclusive, advertised item price only)
- `alert_possible`: `false`
- `daily_health`: `false`
- GitHub direct Reddit module: disabled; existing MonitoRSS connections are separate.

Stock alerts require a matching PS5 purchase listing, an in-stock signal and a
readable INR price at or below the cap. Missing prices, price ranges, non-INR
prices, unknown stock and over-budget items do not generate purchase alerts.
Buyback, digital/account and other-platform product titles are excluded.
Prices for shipping, delivery PIN, original case condition and payment protection
are not verified automatically.

The switch resets old-target product discovery and alert history once, while
preserving store cooldowns. Do not delete the state branch. A price falling from
over budget into budget can notify even if the product never went out of stock.

## Running
The existing workflow is retained. Choose mode `test` for a connection check,
`status` for a scan and one explicit health message, or `scan` for a normal run.
Daily health is off; scheduled scans still run at the existing configured interval.
The code marker is `pragmata-switch-1`.

## Reddit
In each new-post connection, use ANY with two conditions:
- title does contain pragmata
- description does contain pragmata
In the sale-thread-comment connection, use description does contain pragmata.
Remove old Elden Ring/SOTE filters. Keep the same feed addresses and channels.
Reddit posts are unstructured leads: verify PS5 physical format and price yourself.
The shop price cap does NOT apply to MonitoRSS posts.

## Verification
The build passed 202 offline tests; no live storefront success is promised.
Existing blocked or unsupported stores remain incomplete. Check the per-source
run summary, not just the green workflow badge. A manual status run sends a
health message intentionally. The MonitoRSS health is separate.

Older START_HERE files in this repository describe the original SOTE setup and
are historical, not the active game criteria. Follow the Pragmata update guide
provided with this update instead.
