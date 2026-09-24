# Build and verification report

**Build date:** 24 September 2026
**Version:** 1.0.0
**Runtime used for offline tests:** Python 3.13.5
**Direct dependencies:** requests 2.32.5; beautifulsoup4 4.14.3

## Completed

Implemented retailer product parsing, variant-level handling, bounded catalogue/sitemap discovery, robots rules with wildcard support, per-store request budgets and backoff, Discord notifications, persistent GitHub alert history, daily health reports, GitHub workflow, an optional approved-API Reddit module, configuration, browser-only setup documentation and an offline demo.

## Test results

74 synthetic/offline tests passed. These include target/negative matching, buyback filtering, Shopify per-variant stock, WooCommerce variants, unavailable/backorder handling, primary-product isolation, related-product false positives, stale schema conflicts, sale-price selection, safe discovery, XML constraints, deduplication, real restock transitions, unknown-state preservation, retry after unacknowledged delivery, local state integrity, GitHub permission errors, robots wildcard rules, webhook validation, mocked Discord confirmation, Reddit filtering and a mocked two-run end-to-end pipeline.

The local `demo` command completed and produced an explicitly fictional sample. Python files compiled successfully. No real webhook or OAuth credentials were used. Tests do not contact stores, Discord, GitHub or Reddit.

## External facts checked separately through browsing

Official GitHub billing, schedule, secrets, manual workflow, Actions repository and REST API documentation; Discord webhook and phone-notification documentation; Shopify's documented public product-JSON format; Reddit's current approval policy and API reference.

The exact Console Garage, e2zStore, DTZone and Hitech Gamez product pages were readable in the web research tool. e2zStore's Elden Ring tag catalogue was also inspected. These pages supplied source URLs and identified the need to isolate buyback and primary-product stock signals. They did not supply a successful live run of this program.

## Not yet verified

The execution environment could not resolve external retailer hosts and could not download the raw product pages. Consequently **none of the adapters has been fully live-tested from this build environment or a GitHub-hosted runner**. No claim is made that all 14 configured retailer targets currently expose accessible robots files, sitemaps, search results, structured data or stock controls.

A target with an exact seed URL is more concrete than a discovery-only target, but both need runtime validation. Sitemap-based targets with opaque/numeric product IDs may not produce any useful matches. Anti-bot pages and JavaScript-only sites may remain unavailable. No logged-in/PIN-specific checkout has been tested.

No GitHub repository was created or deployed in the user's account. The schedule is included as a file, not running. Discord phone notification delivery needs a real webhook and the user's device test. Reddit is disabled and no API approval or authenticated run was attempted.

## Acceptance check on the user's accounts

1. Upload to a personal public repository and set only the Discord webhook secret.
2. Run `test`: require a Discord message and verify a phone notification.
3. Run `status`: review the actual per-source success/failure report, not just the workflow's green tick.
4. Confirm a subsequent scheduled run and persistent `tracker-state` branch update.
5. Confirm the next daily health message. Disable consistently unreadable sources or revise their adapters instead of treating them as out of stock.

This is a working, tested-offline first build, not a claim of comprehensive production coverage.
