# Advanced direct-API module - not needed for this setup

**For the agreed hosted MonitoRSS route, follow Part C of [START_HERE.md](../START_HERE.md).** Leave the built-in `reddit.enabled` flag false and every GitHub `REDDIT_*` setting unset. Your spare Reddit account connects to MonitoRSS, not to this code. The advanced material below is retained only for a future separately approved direct-API deployment.

---

# Optional Reddit module: a separate setup phase

**Leave Reddit disabled for the first retailer-tracker setup.** The Discord alert channel and store checks work without Reddit credentials.

Reddit's current Responsible Builder Policy requires explicit approval before API access. Owning an account or having old credentials does not by itself establish approval for this application. Do not set the approval flag merely to bypass this requirement.

Official policy: https://support.reddithelp.com/hc/en-us/articles/42728983564564-Responsible-Builder-Policy

## What is implemented

A read-only OAuth API adapter can inspect the newest submissions in `r/IndianGaming` and `r/PlaystationIndia`, plus their newest comments. The latter can include comments inside sale megathreads. It does not parse all historic megathreads, retrieve every comment, inspect images, read private groups or message anybody. One bounded page per feed is used; high activity can exceed coverage.

The filter looks for SOTE/Erdtree, PS5 and sale intent, and excludes obvious wanted/sold/deleted posts. It sends a **link-only private-sale lead**, not a claim of buyer protection. The module does not copy usernames, photos, titles or post bodies into Discord or the repository. A generic notification links to the source for manual inspection.

Public Git history stores keyed deduplication hashes, opaque Discord message IDs and timestamps; it does not store Reddit source IDs, permalinks, usernames or post text. The source URL is recovered from the private Discord notification when rechecking a lead. Existing retained leads are rechecked through the approved API; removed/non-sale items cause their alert to be deleted. Alerts expire after roughly 24 hours, on the next successful workflow run. Turning off the module clears its retained messages on the next normal scan. These cleanups depend on the workflow, credentials and APIs remaining functional.

When stopping the whole tracker, first disable Reddit in configuration, run `status` once to clean up its alerts, and then disable the GitHub workflow. You can also delete the private alert messages/channel yourself. No implementation can guarantee cleanup while its host or APIs are unavailable.

## What is still needed before enabling it

Obtain approval for your particular personal monitoring use case and an approved OAuth application with **read** access. The app needs a refresh token from Reddit's OAuth authorization flow. The package does not obtain approval or generate a refresh token for you; that requires the approved app and a separate authorization step.

After approval and authorization, add these repository **secrets**:

```text
REDDIT_CLIENT_ID
REDDIT_CLIENT_SECRET
REDDIT_REFRESH_TOKEN
REDDIT_USER_AGENT
```

Use the user-agent required by your approved application (for example an honest platform/app/version string that identifies its developer account). Do not impersonate a browser or reuse somebody else's developer credentials.

Add the repository **variable** `REDDIT_APPROVED` with value `true`, then change `reddit.enabled` to `true` in `config.json`. The workflow already passes these values to the module. Test with `status` and read the Reddit status in the health summary.

If authorization is missing, denied or rate-limited, the module reports that and does not fall back to scraping, unauthenticated JSON, RSS, proxies or multiple accounts. Approval and future API availability are not guaranteed.

## Validation status

Sale filtering, wanted/deleted exclusions and the approval gate are covered by offline tests. No approved Reddit credentials were supplied, so live authorization, feed access and the full cleanup path have **not** been validated against the actual services. Treat this module as experimental until an approved live test succeeds.

Official API documentation: https://www.reddit.com/dev/api/
Official OAuth documentation: https://github.com/reddit-archive/reddit/wiki/OAuth2
