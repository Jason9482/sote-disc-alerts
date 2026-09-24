# PS5 Shadow of the Erdtree disc watcher

Personal, conservative stock alerts from selected Indian retailers to Discord, scheduled with GitHub Actions. New and used discs are accepted; buyback listings, ordinary base-game titles, wrong platforms and digital-only products are filtered.

**Start with [START_HERE.md](START_HERE.md).** It covers the whole browser-only setup, including hosted MonitoRSS for all four selected Reddit communities. Python/Git installation is not required on your PC for the hosted setup.

## Setup revision 2

Updated 24 September 2026: added start-to-finish MonitoRSS instructions, the four-community / three-feed layout, authenticated preview checks, feed rotation, and troubleshooting. All 74 offline tests were rerun successfully. No live MonitoRSS or retailer deployment was performed. Engine behaviour is unchanged.

## Build status

Version 1.0.0, built 24 September 2026. **74 offline tests passed.** Actual GitHub deployment, live adapter compatibility and phone delivery still need your first run. This is a beta personal utility, not a guaranteed all-store availability service. See [the build report](docs/BUILD_REPORT.md) for what was and was not verified.

There are 14 configured retailer targets. Four have web-inspected exact-edition seed pages, Flipkart has experimental URL probes, and the remainder use experimental bounded discovery. A configured source is not necessarily readable. Amazon is not implemented. The built-in Reddit API module stays disabled. For the agreed no-personal-API-application route, use hosted MonitoRSS with [Part C of the setup guide](START_HERE.md#part-c---add-reddit-through-hosted-monitorss). It runs separately and must be connected and tested in your own account. `REDDIT_FEEDS_TO_COPY.txt` contains copy-ready feed addresses, not configuration consumed by the tracker.

## Behaviour

The workflow requests scans every 30 minutes. New listing discovery is attempted every six hours. Each store has a per-run request budget; robots directives, delays and access blocks are respected. No logins, proxies, CAPTCHA bypass, cart mutations or automated purchases are used.

The checker evaluates primary product sections and individual variants, not arbitrary page keywords. Console Garage's product-level aggregate stock is ignored because buyback can make it misleading. Negative purchase-section stock overrides stale positive schema. Ambiguous variants become manual-check leads.

Stock observation history is stored on a separate `tracker-state` branch using the workflow's automatically supplied GitHub token. No personal access token is required. Successful Discord delivery is acknowledged before an alert is marked sent. This reduces duplicates but does not provide exactly-once delivery across service failures.

Each alert labels delivery/PIN and payment protection as unverified. It does not certify the original case or DLC voucher. A daily health message and GitHub run summary expose blocked or unreadable sources. The system cannot send its own failure notice when the entire scheduler is stopped.

## Files

- `tracker.py`: command-line entry point.
- `config.json`: retailer targets and user preferences.
- `sote/`: product parsers, respectful HTTP client, alert history, Discord transport and optional approved-API Reddit module.
- `tests/test_tracker.py`: synthetic regression and mocked integration tests.
- `.github/workflows/watch.yml`: active GitHub schedule and manual test controls.
- `WORKFLOW_TO_COPY.yml`: spare workflow for browser upload; not active at the root.
- `START_HERE.md` / `START_HERE.html`: beginner setup guide.

## Local developer use (optional)

Python 3.13 was used for testing.

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python tracker.py --mode demo
python tracker.py --mode dry-run
```

`demo` is entirely offline and uses a fictional listing. `dry-run` makes live store requests but sends no notifications and saves no state. Normal local scans need `DISCORD_WEBHOOK_URL` in the process environment; never put it into the source. Local state is written to `state.json` and ignored by Git. GitHub-hosted scans use the state branch instead.

## Safety and maintenance

Use a personal public repository for the documented free-runner route. Never commit credentials or delivery details. Review provider terms; disable any source that does not permit your intended monitoring. Robots permission is not a blanket grant of permission. Do not merge unreviewed external code into a repository that runs with secrets.

The workflow runs only on schedule or manual dispatch, not on pull requests. Third-party Actions use official major-version tags. For stricter supply-chain controls, review and pin their commits. Python dependencies are pinned to the versions used in this build.

Main limitations: partial sitemap discovery, JS-only stock data, source redesigns, blocking from data-centre IP addresses, GitHub scheduling delays, inability to perform PIN/checkout tests, and image-only/private sale listings. The state branch contains actual observation commits, not a promise that GitHub will never suspend an inactive schedule.

## Official references

- [GitHub public-runner billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions)
- [GitHub schedules and inactivity](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)
- [GitHub Actions secrets](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets)
- [Discord webhook API](https://docs.discord.com/developers/resources/webhook)
- [Shopify product/variant JSON API](https://shopify.dev/docs/api/ajax/reference/product)
- [Reddit Responsible Builder Policy](https://support.reddithelp.com/hc/en-us/articles/42728983564564-Responsible-Builder-Policy)

No affiliation with the game publisher, GitHub, Discord, Reddit or any retailer is implied.
