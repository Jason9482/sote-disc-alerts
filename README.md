# Ace Combat 8 PS5 disc watcher - INR 5,500 ceiling

Revision: `acecombat8-5500-1`. Prepared 11 October 2026.

This update replaces the active Onimusha target with **Ace Combat 8: Wings of Theve**.
It does not deploy itself. Upload it into the existing repository's `main` branch.

## Configuration

- `target`: `acecombat8`
- `max_price_inr`: `5500` (inclusive item-price cap, not a delivered-price guarantee)
- `daily_health`: `false`
- `alert_possible`: `false`
- `reddit.enabled`: `false` (MonitoRSS remains independent)

New and used physical PS5 purchase offers are accepted where the parser can identify them.
INR 5,500 qualifies; INR 5,500.01 does not. Foreign-currency or unreadable prices are
suppressed while a numeric INR cap is active. Coupons, card discounts and shipping
are not calculated. No automated purchase, cart write or seller contact occurs.
Original case, disc condition, authenticity, delivery and payment protection remain manual checks.

## Update, not a reinstall

1. Pause the existing workflow and let a current run finish.
2. Upload the contents of UPLOAD_THESE_FILES to the repository root on main.
   Do not delete folders or upload the enclosing folder.
3. Leave `.github/workflows/watch.yml`, `requirements.txt`, the Discord secret and
   the tracker-state branch alone. The existing workflow and schedule remain.
4. Re-enable the workflow. Start a new `test`, then a new `status` run on main.
5. Update the three MonitoRSS connections separately, preserving the author exclusion.

The old `sote` folder, SOTE workflow/repository labels and original Discord channel
names are safe to keep. They are not the active search criteria.

## State and alerts

The first scan with a changed target discards remembered product URLs and alert
history for the previous target, but retains source cooldowns. It does not erase
GitHub history or old Discord messages. An unchanged qualifying offer is not sent
every scan. A genuine restock or a price moving back inside the cap can trigger a
new alert. A `status` run deliberately sends a health message; normal scheduled
scans do not send daily health messages with the supplied configuration.

Explicit preorder/backorder signals are not treated as ready stock. An old URL
slug containing 'preorder' by itself does not override a current product status.
Some titles that bundle discs with digital extras may require manual review.
Failed fetches are not 'out of stock'. A green workflow is not proof of full coverage.

## Coverage and access

There are 17 configured store entries, 16 enabled. Five sources have known exact
product links: DTZone, GameBuy, MCube, PSX Gaming and Play HQ. The others primarily
use bounded catalogue/sitemap discovery. Known links were located through public
retailer pages or their indexed results on 11 October 2026; they are not verified
stock claims or proof that GitHub can fetch/parse them. Source-specific notes are
in config.json. Amazon is not implemented. Flipkart is disabled without an exact
validated product URL. Numeric-ID catalogues and JavaScript-dependent pages can
remain unresolved. This is not complete coverage of every Indian shop.

Requests respect the existing rate limits, robots exclusions, HTTPS verification,
response size limits and backoff rules. No login automation, CAPTCHA bypass,
rotating proxies or private API endpoints are used.

## Reddit: change MonitoRSS, not this program

For the two new-post feeds, use these six keyword conditions in one ANY group:

- title contains ace combat 8
- description contains ace combat 8
- title contains wings of theve
- description contains wings of theve
- title contains acecombat8
- description contains acecombat8

For the sale-thread comments use only the three description conditions.
Preserve any existing outer ALL group and author-does-not-equal exclusion.
Do not put the author exclusion inside the ANY keyword group. Reddit prices,
platform, format and seller trustworthiness must still be checked manually.

## Tests and limitations

Run: `python -m unittest discover -s tests -v`

388 offline tests pass (305 earlier tests plus 83 new tests). Earlier Onimusha
configuration tests now read a historical fixture rather than the current user
config; this preserves their original assertions after the target switch.
That fixture is not active retailer configuration. Tests use synthetic data and
mock delivery, not live purchases or your Discord/Reddit accounts.

The five seeded retailer smoke checks all failed at DNS lookup from the build
environment. No live availability was established. Your new GitHub status report
is required to assess the actual source-by-source coverage.
