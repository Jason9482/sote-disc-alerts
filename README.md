# Onimusha: Way of the Sword PS5 watcher - unlimited price

Revision: `onimusha-unlimited-1` | Built: 2026-10-06

This is an update for the existing SOTE/Pragmata GitHub Actions project.
Keep the existing workflow, secrets, requirements, Discord destinations and state branch.
The Python package is still called `sote`; that name is not the active search target.

## Active settings

- Target: Onimusha: Way of the Sword, PS5 physical purchase listings.
- New and used accepted; no numeric price ceiling.
- `max_price_inr: null` means unlimited. Do not use 0 or the string "null".
- `daily_health: false`: scheduled scans do not send routine daily health messages.
- A manually requested `status` run still sends a health report.
- `alert_possible: false`: ambiguous edition/platform/stock leads do not alert.
- Direct GitHub Reddit module stays disabled. MonitoRSS is separate.

## Installation

Temporarily disable the existing workflow and wait for any active run to finish.
Upload the CONTENTS of `UPLOAD_THESE_FILES` to your repository ROOT on `main`:
`sote/`, `tests/`, `config.json`, `tracker.py`, `README.md`.
Do not delete existing folders. Do not upload the enclosing folder or ZIP.
Re-enable the workflow, start a NEW `test` run, then a NEW `status` run.
You should see `Onimusha: Way of the Sword` and `Unlimited (no price cap)`.

Do not edit `tracker-state`, `.github/workflows/watch.yml` or webhook secrets.
Old target URLs and alert history reset automatically on the first real target switch;
store cooldowns remain. Old commits and existing Discord messages are not erased.

## What it does and does not do

Known product pages are checked on the existing schedule; catalogue and sitemap
sampling is bounded and takes place about every six hours. Matching distinguishes
Way of the Sword from older Onimusha games, wrong platforms, digital accounts,
code-only products, buybacks and explicit case/SteelBook-only products.
Readable in-stock exact matches can alert at ANY listed price. An unreadable price
is labelled unverified and does not suppress an otherwise eligible stock lead.
No currency conversion or price-ceiling comparison is performed in unlimited mode.
Out-of-stock, unknown-stock, preorder/backorder and ambiguous-platform results do
not become purchase alerts. Matching descriptions are store claims, not guarantees.

An ordinary price change by itself does not cause a repeated alert in unlimited
mode. New in-stock offers and returns to stock do. Successful delivery is acknowledged
before deduplication is committed. A network timeout can still cause a duplicate.

The update does not add working coverage to every previously blocked store.
15 sources are configured; only GameBuy, Flipkart and Sheenu currently have specific
Onimusha seed URLs. Others rely on bounded discovery. Amazon is manual-only.
A green workflow is NOT proof that all sources were checked. Inspect each source's
result, evidence and discovery diagnostics. No checkout, PIN delivery, final price,
buyer-protection or seller-trust verification is performed. No purchases are made.

## Reddit / MonitoRSS

Keep the three existing feeds and destinations. Change their connection filters:

New-post feeds (IndianGaming, and combined resale/Bangalore/PlayStation): one ANY group:
- title DOES CONTAIN onimusha
- description DOES CONTAIN onimusha
- title DOES CONTAIN way of the sword
- description DOES CONTAIN way of the sword

Sale-thread comments: one ANY group:
- description DOES CONTAIN onimusha
- description DOES CONTAIN way of the sword

Remove old Pragmata/Elden Ring/price conditions, save, reopen, preview and test.
These are broad leads, not automatic checks of the game, platform or physical format.
Older Onimusha games, discussions and wanted posts can appear. Check them manually.
Photo-only mentions can be missed. No price limit is configured in either system.
Do not create a fourth feed. A replaced megathread still needs its URL updated manually.

## Testing and limits

305 offline tests passed. Production-client probes could not resolve the three seed
store domains in this build environment. The first GitHub status run is the live
scanner compatibility check. Public pages viewed with a separate web tool are not
proof that the Python scanner can fetch or parse them. No user account or webhook
was accessed or modified while building this update.

The original and capped-target regression fixtures remain in tests; the presence of
4000 in a test does NOT impose a live limit. The installed config uses JSON null.

## Local developer verification (not needed for browser setup)

```sh
python -m unittest discover -s tests -v
python tracker.py --mode demo --config config.json
```

`demo` is entirely synthetic and does not send messages or query stores.
Do not commit real credentials, private source content or local state files.
