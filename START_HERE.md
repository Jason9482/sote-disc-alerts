# SOTE alerts: complete setup

**Indian shops + four Reddit communities -> Discord on your phone**

Setup guide revision 2 - 24 September 2026. Tracker engine: the existing version 1.0.0.

You will use two separate services: **GitHub runs the shop tracker**; **hosted MonitoRSS handles Reddit**. Both send messages into your Discord server. Nothing needs to keep running on your PC after setup. This is not a single program installed on your phone.

**Your four communities:** r/IndianGaming, r/Indiangaming_Resale, r/PlaystationIndia and r/BangaloreMarketplace.

## Before you start

Use a personal GitHub account, your normal Discord account and the spare Reddit account you already prepared. Keep your phone nearby with Discord installed and signed in to the same Discord account as on your PC. You do not need to install Python, Git, Docker or a database on your PC, create a Reddit developer application, or buy hosting for the setup below.

**The free-plan constraint:** MonitoRSS currently advertises three feeds, checked every 20 minutes. We will keep IndianGaming separate, combine the other three communities into one feed, and reserve the third feed for the PlayStation sale megathread. Reddit's legacy documentation describes combined-community RSS feeds, but it is no longer maintained. **The combined feed and comment feed must pass the authenticated MonitoRSS preview before you rely on this arrangement.** I could not test those feeds inside your account. A valid-looking URL is not proof of live coverage. [S1, S2, S3]

The retailer code passed **74 offline tests again during this revision**. It has not been deployed to your accounts. Live retailer access, your MonitoRSS feeds, and phone delivery still need the checks below.

Already uploaded the previous ZIP? The running retailer code does not need replacing for MonitoRSS to work. Use this guide for the Reddit setup. Do not create a second running GitHub tracker, which could send duplicate alerts.

## Part A - Prepare Discord

### 1. Make a server and two channels

Open [Discord](https://discord.com/app) on your PC or in the browser. Create a server with the **+** in the left-hand server list and choose **Create My Own**. Name it **Game alerts**. Keep it just for you; there is no need to invite anybody.

Create two ordinary **text channels**:

| Channel | What it receives |
|---|---|
| `sote-alerts` | Indian-store leads and the tracker health report |
| `reddit-sote` | Reddit keyword matches from MonitoRSS |

Do not use a forum channel or a thread. Keeping both channels in the same server makes phone settings simpler.

### 2. Enable phone notifications

On your phone, open the Game alerts server's notification settings. Select **All Messages**, enable **Mobile Push Notifications**, and make sure the server and both channels are not muted. Enable Discord notifications in Android/iOS settings as well. On Android, check that the **Server / Messages** notification category is permitted. [S4]

During the later test, temporarily close desktop Discord and lock the phone. A message visible in a channel does not prove that a phone notification worked.

### 3. Create the shop-tracker webhook

On desktop Discord open:

**Game alerts -> Server Settings -> Integrations -> Webhooks -> New Webhook**

The button may say **Create Webhook**. Name it **SOTE Watcher**, select **#sote-alerts**, save, and choose **Copy Webhook URL**. [S5]

**Keep the webhook URL private.** Do not paste it into chat, a screenshot, code, a README, or a public issue. The next step puts it in GitHub's private secret store. Copy it exactly; do not append `/github`.

MonitoRSS will use its own bot for #reddit-sote. You do not need a second webhook for this guide.

## Part B - Start the Indian-store tracker

### 4. Create a public GitHub repository

Sign in to [GitHub](https://github.com) using a personal account. Open the **+** menu -> **New repository**. Enter:

```text
sote-disc-alerts
```

Choose **Public**, add a README if the page offers that option, and click **Create repository**. A repository is just the online folder that holds your tracker. [S6]

GitHub currently makes standard hosted runner time free for public repositories. This workflow uses `ubuntu-latest`, no paid larger runner, and no artifact uploads or dependency cache. Your code and non-secret shop-check history will be public. Never upload passwords, your address or your delivery PIN. [S7]

### 5. Save the Discord webhook as a secret

Inside the repository go to:

**Settings -> Secrets and variables -> Actions -> New repository secret**

Set the **Name** to this exact text:

```text
DISCORD_WEBHOOK_URL
```

Paste your webhook URL in **Secret** and save it. Use **Secrets**, not **Variables**, and not the separate repository **Webhooks** page. [S8]

Do not create a personal access token. The supplied workflow uses its automatically provided GitHub token to save alert history.

### 6. Extract and upload the tracker files

On Windows, right-click **SOTE_Tracker_With_Reddit_Setup.zip** -> **Extract All**. Open the extracted **sote-discord-tracker** folder. You should see `tracker.py`, `config.json`, `requirements.txt`, `sote`, `tests`, `.github`, and the guides.

In GitHub select **Code -> Add file -> Upload files**. Drag in the **contents of the sote-discord-tracker folder**, including its folders. Commit the upload to the default branch, normally **main**. [S9]

**Do not upload only the ZIP. Do not upload the enclosing sote-discord-tracker folder as an extra level.** On GitHub, `tracker.py` must be visible at the top level.

Check that this file exists:

```text
.github/workflows/watch.yml
```

When Windows or the upload omits `.github`, use the fallback:

1. Open `WORKFLOW_TO_COPY.yml` on your PC with Notepad and copy its entire contents.
2. In GitHub choose **Add file -> Create new file**.
3. For the filename enter `.github/workflows/watch.yml` exactly, including the first dot and both slashes.
4. Paste the contents and commit to **main**.

The root `WORKFLOW_TO_COPY.yml` is only a spare; it does not activate a schedule by itself. **Never paste your actual webhook URL into either workflow file.**

Leave `config.json` unchanged for the first run. In particular, keep the built-in `reddit.enabled` setting **false**. The direct-API Reddit module is not the Reddit route in this guide. Leave `REDDIT_APPROVED` and every `REDDIT_*` credential unset in GitHub.

### 7. Send a phone test

In GitHub open:

**Actions -> SOTE stock watcher -> Run workflow**

Enable Actions if prompted. Select the default branch, usually **main**. Choose mode **test** and click **Run workflow**. GitHub only shows the manual control when the actual workflow is on the default branch. [S10]

The expected Discord message is:

```text
TEST: SOTE tracker connected
```

Check that it reaches **#sote-alerts** and gives your locked phone a notification. This tests delivery only, not store stock.

### 8. Run the first real scan

Run the same workflow again, this time with mode **status**. It checks the configured stores and forces a health message. Open the workflow run's **Summary** for the source-by-source result.

**A green workflow is not proof that all shops were readable.** Review the successful product-page checks, discovery checks and failures. `Blocked`, `unreadable`, a timeout, or no discovered URL is not the same as `out of stock`.

The package contains 14 configured shop targets, not 14 validated integrations. Some are experimental sitemap/catalogue discovery. Amazon India is not implemented. Exact-edition seed pages are included for Console Garage, e2zStore, DTZone and Hitech Gamez; the first GitHub run establishes whether this code can read them.

The supplied schedule requests a run every **30 minutes**, at UTC minutes 17 and 47. New-listing discovery is attempted about every **six hours**. A shop health report is sent about once every 24 hours. Nothing needs to run on your PC. GitHub can delay or drop scheduled runs; it is a best-effort service. [S11]

## Part C - Add Reddit through hosted MonitoRSS

### 9. Add MonitoRSS to your Discord server

Open [the official MonitoRSS website](https://monitorss.xyz). Choose **Add to Discord**, select **Game alerts**, review the permissions, and authorize it. Then use **Dashboard** on that site and sign in with the same Discord account. Use the hosted service; do not follow the self-hosting/Docker installation in its source repository. [S1, S12]

Make sure the bot can view and send messages in **#reddit-sote** and embed links there. A channel made private can require explicitly giving the bot access. Do not make a separate paid workspace or buy a subscription just to follow this guide.

The dashboard is an authenticated app, and its layout can change. Labels such as Add Feed, destination/connection, preview and filtering below describe the relevant controls; their exact wording may differ. The old docs.monitorss.xyz site is deprecated, so use the current dashboard's help for a changed control. [S13]

### 10. Connect your spare Reddit account

In another browser tab, log in to **the spare Reddit account**. Return to MonitoRSS and start adding a Reddit feed. Use its **Connect Reddit** prompt; current MonitoRSS releases require a Reddit connection when adding Reddit feeds. [S2]

On the Reddit authorization screen, check that the displayed username is your spare account, review the permissions and authorize. Then return to MonitoRSS. Enter any Reddit password only on Reddit's own sign-in page, never into this tracker or a message.

**No Reddit password, client ID, token or developer application goes into GitHub for this setup.** The Reddit authorization belongs to MonitoRSS. You are not enabling the optional direct-API module in the ZIP.

### 11. Add and verify these three feeds

Use the feed addresses below one at a time. For each one, paste the **whole URL**, inspect its preview before applying filters, and set the Discord destination to **Game alerts -> #reddit-sote**. A feed that was merely saved, without a Discord destination/connection, is not a completed alert setup.

#### Feed 1 - IndianGaming: new posts

```text
https://www.reddit.com/r/IndianGaming/new/.rss?limit=100
```

Suggested name: **IndianGaming - new posts**.

Start with this single-community feed. Confirm the preview contains real recent posts and links to r/IndianGaming. No recent Elden Ring item is required for this connectivity test.

#### Feed 2 - Resale, Bangalore marketplace and PlayStation: new posts

```text
https://www.reddit.com/r/Indiangaming_Resale+BangaloreMarketplace+PlaystationIndia/new/.rss?limit=100
```

Suggested name: **Resale + Bangalore + PlayStation**.

The **+** signs join the three communities into one RSS source, so it uses one feed slot rather than three. Reddit's legacy RSS page documents this multireddit pattern. [S3]

After saving, check that the stored URL still contains **all three names** and **/new/**. Inspect the preview's links to see which communities the returned entries belong to. A quieter community may not have an item in that particular snapshot; that alone does not prove it is excluded.

**This combined feed is not live-tested here.** MonitoRSS must accept it under your connected account. A successful Feed 1 does not establish that Feed 2 works. If it fails, use the combined-feed troubleshooting below rather than quietly dropping a community.

#### Feed 3 - PlayStation sale megathread: comments

```text
https://www.reddit.com/r/PlaystationIndia/comments/1w2y8w7/wtb_wts_anyone_selling_price_check_megathread/.rss?sort=new&limit=100
```

Suggested name: **PlayStation - sale-thread comments**.

This is the buy/sell thread referenced during this setup check. Open the [PlayStation India community](https://www.reddit.com/r/PlaystationIndia/) and compare its highlighted **WTB / WTS / Anyone Selling / Price Check Megathread** before adding it. If the moderators have replaced it, use the newer thread URL and put `.rss?sort=new&limit=100` after its final slash. [S14]

In the preview, look for **individual comment text and comment links**, not only the original thread announcement. Reddit documents a separate RSS pattern for comments on an individual post. [S3]

**When moderators replace the megathread, update Feed 3's URL.** This setup does not automatically discover replacement threads. Feed 3 does not cover every comment in all four communities.

The `limit=100` parameter requests a larger recent snapshot; it is not a promise that every item will be returned. If more items arrive than the available snapshot holds between checks, some can be missed. Text in an image is not searched.

### 12. Apply the same keyword rule to all three feeds

Open each feed's Discord destination/connection and its filtering controls. Configure an **include/allow rule** using **ANY / OR**, not ALL / AND. Match without case sensitivity where the control allows it. MonitoRSS advertises article keyword filtering. [S1]

Use these four keywords as **separate alternatives**:

```text
elden ring
eldenring
erdtree
sote
```

Search the **title** and the field that actually contains the **post/comment text**. In a feed preview, that text field may be called `description`, `content`, or another feed-specific property. Select the actual text-bearing field rather than guessing from its name. If body text is not present, the feed can only provide title matches; do not count it as full-text coverage.

The intended rule is:

| Field | Include when it contains ANY of |
|---|---|
| Title | elden ring; eldenring; erdtree; sote |
| Actual post/comment text | elden ring; eldenring; erdtree; sote |

**Either field may match.** When the dashboard permits only one keyword per condition, add four title conditions and four text conditions inside one **ANY / OR** group. Do not paste the four-line block into a single plain-text condition that expects one phrase. Do not require both title and body to match.

Save the rule and check the filter preview/results. A message such as `Selling Elden Ring PS5` should qualify. A comment saying `SOTE disc available` should qualify. `Selling a sofa` should not. Use available preview examples; do not create fake listings on the communities to test the bot.

Do **not** require PS5, WTS or the complete edition title at first. A seller might omit these details and show the Erdtree box in a picture. This broad filter also admits gameplay discussion, wanted ads and ordinary Elden Ring copies; you inspect these leads manually. The shop tracker's stricter matching does not automatically filter the separate MonitoRSS channel.

Leave the default Discord message format initially. Check that it contains a title and an **original Reddit link**; include a short text snippet using the dashboard's field picker if needed. You do not need to type template syntax by hand.

### 13. Test Reddit delivery and finish

Use each feed connection's **preview/test-message control** when available. Select a returned article/comment and send a test to **#reddit-sote**. A test may bypass filters: use it to verify delivery, then check the filtering results separately.

Confirm the message appears in the right Discord channel, opens the correct Reddit post/comment, and triggers a phone notification. Keep all three feeds and their destinations enabled. A preview with no current matching SOTE item is normal; a preview with a fetch/authentication error is not.

The advertised free polling interval is **20 minutes**, not instant. The tracker and MonitoRSS are separate: a successful GitHub health message does **not** verify that Reddit feeds are healthy. [S1]

**Finished means:** shop test received on phone; shop status inspected; each of the three Reddit feeds previews correctly; Discord destinations and filters are saved; and a Reddit test reaches the phone. Nothing is deployed or connected simply by downloading this package.

## Troubleshooting

| What you see | What to check |
|---|---|
| No SOTE stock watcher in GitHub Actions | `tracker.py` must be at the repository root, and `.github/workflows/watch.yml` must be on the default branch. The root spare workflow alone is not enough. |
| GitHub says the webhook is missing | The repository secret must be named exactly `DISCORD_WEBHOOK_URL`. It must be a secret, not a variable. |
| Discord webhook fails with 401/404 | Re-copy or recreate it in Discord, replace the GitHub secret, and run test. Do not publish the URL. |
| GitHub cannot save history / 403 | The supplied workflow requests `contents: write`. Inspect repository/organization restrictions rather than making a personal token. Prefer a personal repository. |
| Retailer gets 403, CAPTCHA or a timeout | This source was not successfully checked. Do not bypass access controls or label it sold out. Other readable sources can still work. |
| MonitoRSS requires Reddit authorization | Connect the spare account through its authorization prompt. This does not require filling GitHub Reddit credentials. |
| A feed loads but sends nothing | Check its Discord destination, enabled state, bot permissions, filter results and delivery logs. There may simply be no new keyword match. |
| Comments never qualify | Check that Feed 3 returns comments and that the rule examines comment text, not only the thread title. |
| A message appears but the phone stays quiet | Verify All Messages, Mobile Push, channel mutes and OS permissions. Close desktop Discord during the test and check Do Not Disturb/battery settings. |
| No shop health message for more than a day | Inspect GitHub's latest run and whether the schedule is enabled. GitHub cannot notify through this script while the entire schedule is stopped. |

### Combined-feed fallback

First confirm Feed 1 works using the connected Reddit account. Recheck Feed 2 for accidental spaces or missing plus signs. Paste the complete RSS URL rather than choosing a single-community preset that discards the combined names.

If MonitoRSS rejects the combined URL, one alternative to test is a **public Reddit custom feed** containing the same three communities. On Reddit, open a community's three-dot menu -> **Add to Custom Feed -> Create A Custom Feed**. Name it `sote-watch`, add r/Indiangaming_Resale, r/BangaloreMarketplace and r/PlaystationIndia, and make it public. Reddit documents custom feeds that combine communities. [S15]

Open that custom feed, select **New**, and use its actual URL with `.rss` appended after the final slash. A typical pattern is:

```text
https://www.reddit.com/user/YOUR_REDDIT_USERNAME/m/sote_watch/new/.rss?limit=100
```

**Use the actual username and custom-feed slug from the address bar, not the placeholder above.** Replace Feed 2; do not add a fourth slot. This fallback also needs a successful MonitoRSS preview and is not verified here.

If neither combined nor custom feeds work, the advertised three-feed plan cannot be assumed to cover four separate communities plus a comment thread. Keep any working sources, record the error and resolve that limitation before relying on complete coverage. Do not create extra accounts to evade quotas or pay based on an unverified assumption.

## Ongoing care and stopping

Check MonitoRSS feed status periodically, especially after a Reddit authorization error. Check the PlayStation megathread weekly and replace Feed 3 when a new one is pinned. RSS is a recent-items feed, not a comprehensive historical search or guaranteed edit tracker.

Check that GitHub continues running. GitHub says public-repository schedules can be disabled after 60 days without repository activity and can be delayed or dropped under load. This utility does not guarantee uninterrupted monitoring. [S11]

After buying the game, disable **SOTE stock watcher** in GitHub Actions and disable/delete the three MonitoRSS feeds. Stopping one does not stop the other. You may then revoke MonitoRSS's Reddit authorization and delete the Discord webhook. [S16]

**Buying safety:** these are unverified leads, not buyer protection. Confirm the PS5 disc, original SOTE case, condition, included/redeemed DLC voucher, delivery and payment terms before buying. The PlayStation sale thread itself warns that moderators are not responsible for transactions. [S14]

## References and verification

[S1] [MonitoRSS official hosted service: free feed allowance, polling, filtering and setup](https://monitorss.xyz/).

[S2] [MonitoRSS release notes: Reddit connection requirement](https://github.com/synzen/MonitoRSS/releases).

[S3] [Reddit legacy RSS documentation: subreddit, multireddit and post-comment feeds](https://www.reddit.com/r/reddit.com/wiki/rss/). This page explicitly says it is no longer updated.

[S4] [Discord mobile notifications](https://support.discord.com/hc/en-us/articles/218892547--Mobile-Notifications-Settings-101).

[S5] [Discord webhook creation](https://support.discord.com/hc/en-us/articles/228383668-Intro-to-Webhooks).

[S6] [GitHub: create a repository](https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-new-repository).

[S7] [GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions).

[S8] [GitHub Actions secrets](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets).

[S9] [GitHub: upload files](https://docs.github.com/en/repositories/working-with-files/managing-files/adding-a-file-to-a-repository).

[S10] [GitHub: manually run a workflow](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow).

[S11] [GitHub: scheduled workflow limitations](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).

[S12] [MonitoRSS project: public instance versus self-hosting](https://github.com/synzen/MonitoRSS).

[S13] [Deprecated MonitoRSS documentation notice](https://docs.monitorss.xyz/advanced-bot-customizations/filtered-message-formats).

[S14] [PlayStation India sale megathread](https://www.reddit.com/r/PlaystationIndia/comments/1w2y8w7/wtb_wts_anyone_selling_price_check_megathread/) and [current community](https://www.reddit.com/r/PlaystationIndia/).

[S15] [Reddit: create a custom feed](https://support.reddithelp.com/hc/en-us/articles/360043043412-What-is-a-custom-feed-and-how-do-I-make-one).

[S16] [GitHub: disabling/enabling a workflow](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/disable-and-enable-workflows).

The feed URLs are proposed configuration addresses, not a claim of successful authenticated fetching. GitHub and MonitoRSS account setup must be completed by you. No credentials are included. This revision updates setup documentation and the inactive optional subreddit list; it does not add a new custom Reddit scraper or deploy anything.
