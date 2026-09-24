# SOTE disc alerts: start here

**Your setup:** GitHub runs the checker. Discord sends alerts to your phone. Your PC can be switched off after setup.

This is a first-version personal tracker for **Elden Ring: Shadow of the Erdtree Edition on PS5**, new or used. Used copies without the DLC code are allowed, but the alert identifies that limitation when the seller states it. You do not need to install Python, Git, a database, a paid bot, Discord Nitro or a server.

**Important before starting:** the code has passed 74 offline tests. It has not been deployed to your accounts or tested end-to-end against live stores from a GitHub runner. The development environment could not make outbound retailer requests. Four exact-product pages were inspected separately through web browsing; that is not the same as validating this script against their raw HTML. The first `status` run below is the live compatibility test. Some configured stores will probably be blocked or unreadable.

## What you need to do

Create a Discord server/channel, create a public GitHub repository, store one private webhook secret, upload these files, and run the test. Everything can be done in your web browser. The optional GitHub connection suggested in the chat is **not required** for this route.

## 1. Make your private Discord alert channel

Open Discord on your PC/browser and sign in. Use the **+** button in the server list to create your own server, for example **Game alerts**. Do not invite anybody unless you intend them to see the alerts.

Create a normal **text channel** named `sote-alerts`. Do not use a forum channel or a thread: this version sends to a regular text channel.

Open the server menu, then **Server Settings -> Integrations -> Webhooks -> New Webhook** (the button may say **Create Webhook**). Name it **SOTE Watcher**, select `#sote-alerts`, save, then choose **Copy Webhook URL**.

**Treat that URL like a password. Do not paste it into this chat, your README, code, a screenshot, or a public issue. Anyone who has it can post through the webhook.** Keep it temporarily in a private clipboard/password manager for the next step. Use the URL exactly as copied; do not append `/github`.

Official reference: [Discord webhook setup](https://support.discord.com/hc/en-us/articles/228383668-Intro-to-Webhooks).

## 2. Create the free GitHub project

Sign in to a personal GitHub account. Open **New repository** from the upper-right **+** menu. Name it `sote-disc-alerts` and choose **Public**. Create the repository. Adding a starter README is optional because this package includes one.

Why public? GitHub currently provides free standard hosted runners for public repositories. This workflow uses the standard `ubuntu-latest` runner, not a paid larger runner, and does not upload artifacts or create a dependency cache. A private repository has a monthly free-minute allowance instead; it is not the same unlimited-public-runner arrangement.

Your code, store URLs and non-secret observation history will be public. Your Discord webhook remains in GitHub's secret store, not in the files. Do not add your address, phone number, delivery PIN or account passwords to the project. **No payment card or paid hosting subscription is needed for this public-repository setup.**

Official references: [new repositories](https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-new-repository), [Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions).

## 3. Put the webhook in GitHub's secret store

Inside your new repository, open:

**Settings -> Secrets and variables -> Actions -> Secrets -> New repository secret**

Use this exact name:

```text
DISCORD_WEBHOOK_URL
```

Paste the copied Discord webhook into the **Secret** field and choose **Add secret**. This is a repository **secret**, not a variable, file or GitHub repository webhook.

Do not create a personal access token. The workflow gets its own short-lived `GITHUB_TOKEN` automatically for saving alert history.

Official reference: [using GitHub Actions secrets](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets).

## 4. Upload the project files

On Windows, right-click the downloaded ZIP and choose **Extract All**. Open the extracted `sote-discord-tracker` folder. You should see `tracker.py`, `config.json`, `requirements.txt`, `sote`, `tests`, `docs`, and other guide files.

In the GitHub repository, open the **Code** tab, then **Add file -> Upload files**. For a completely empty repository, use its **uploading an existing file** link instead.

Drag the **contents inside** the extracted folder into the upload box. Include the `sote`, `tests` and `.github` folders as folders. Do not upload just the ZIP, and do not upload the enclosing `sote-discord-tracker` folder as an extra layer.

Commit the upload to your default branch (usually `main`). GitHub should show `tracker.py` at the **top level** of the file list, not inside another folder.

### Check the workflow file: this is the easy-to-miss part

In the GitHub file list, open `.github`, then `workflows`. The file `watch.yml` must be there.

If `.github` did not upload, or you cannot see it in Windows, use this fallback:

1. Open `WORKFLOW_TO_COPY.yml` from the extracted folder in Notepad and copy all of its contents.
2. In GitHub choose **Add file -> Create new file**.
3. In the filename field, type **`.github/workflows/watch.yml`** exactly, including the first dot and both slashes.
4. Paste the copied contents into the editor and commit to `main`.

Do not paste the webhook into the workflow. The `${{ secrets.DISCORD_WEBHOOK_URL }}` reference already reads it privately.

`WORKFLOW_TO_COPY.yml` at the project root is just a spare copy. Only `.github/workflows/watch.yml` activates the scheduler.

Official references: [uploading files](https://docs.github.com/en/repositories/working-with-files/managing-files/adding-a-file-to-a-repository), [creating files](https://docs.github.com/en/repositories/working-with-files/managing-files/creating-new-files).

## 5. Send the connection test

In your repository, open **Actions**. Enable Actions if GitHub asks. Select **SOTE stock watcher** on the left, then **Run workflow**.

Choose branch `main` and mode **`test`**, then run it. Open the new run and check its result. A successful run should post this message in Discord:

> TEST: SOTE tracker connected

That message tests the notification connection only. **It is not a real stock alert and it does not scan stores.**

If you do not see the workflow, first confirm that `.github/workflows/watch.yml` exists on the repository's default branch, not just `WORKFLOW_TO_COPY.yml` at the root.

Official reference: [running a workflow manually](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow).

## 6. Enable phone notifications and do the first real scan

Install/sign in to Discord on your phone using the same account. In the Game alerts server's notification settings, choose **All Messages**, enable **Mobile Push Notifications**, and ensure `#sote-alerts` is not muted. Allow Discord notifications in Android/iOS settings too.

Temporarily close Discord on your PC, lock your phone, and repeat the `test` workflow. This checks actual phone delivery, rather than merely a message appearing in the channel. Active desktop sessions, Do Not Disturb, battery restrictions and phone permissions can affect what you see or hear.

Now run the workflow again with mode **`status`**. This scans configured stores and forces a health message. Open the workflow run's **Summary** to see the source-by-source report.

Look for **matching product pages read**, **discovery pages read**, and **issues**. A green workflow result means the program completed; it does **not** mean all 14 configured targets were readable. A sitemap with no matching URL is not proof a store has no copy.

After upload, the schedule already requests a run every 30 minutes, at UTC minutes 17 and 47. Discovery of new catalogue/sitemap listings runs approximately every six hours; known matching pages are checked on each scheduled run. Your PC is no longer needed.

Official reference: [Discord mobile notifications](https://support.discord.com/hc/en-us/articles/218892547--Mobile-Notifications-Settings-101).

## What the three messages mean

| Message | Meaning |
|---|---|
| **IN-STOCK LEAD** | The exact-edition title/platform matched and the site exposed a purchase-stock signal. Shipping, checkout, seller and payment protection still need your check. |
| **CHECK MANUALLY** | A relevant product exists, but its edition/platform or current stock could not be confidently established. This is not a confirmed restock. |
| **HEALTH** | The workflow is running, and this report shows which stores were actually readable and which were not. Sent on the first scan and roughly once every 24 hours after that. |

The tracker does not order anything, log in to shops, contact sellers, establish escrow protection or verify DLC redemption. It cannot identify a particular box from a photograph. Before paying, verify the original SOTE case, disc, condition, voucher status/region, delivery and payment protections yourself.

## Starting coverage: be precise about it

The package has **14 configured retailer targets**, not 14 proven live integrations.

**Direct product seeds:** Console Garage, e2zStore, DTZone and Hitech Gamez. Their exact SOTE product pages were inspected through web browsing during the build. The code's adapters still need the first GitHub run. Console Garage's buyback variants are explicitly excluded.

**Additional experimental targets:** GameLoot, GameBuy, MX2Games and HGWorld use catalogue/sitemap discovery. MCube Games, Games The Shop, GameNation, DACBY and CeX India use bounded sitemap discovery. Flipkart has two exact-product URL probes. Dynamic pages, blocked requests, numeric-only product URLs and missing sitemaps can prevent discovery or stock interpretation. These limitations are reported, not hidden.

**Not included as a working source:** Amazon India has no validated exact-edition adapter/ASIN in this build. Reddit is disabled pending approved API access and the optional setup in `docs/REDDIT.md`. International stores are not preconfigured.

## Keeping it reliable

GitHub schedules are best-effort: a run can be delayed or dropped. Public-repository schedules can be disabled after 60 days without repository activity. The tracker records genuine observations on its separate `tracker-state` branch, but do not assume that guarantees permanent scheduling. Check the workflow if health messages stop. There is no independent watchdog that can notify you after GitHub itself has stopped running the job.

A broken page, denied robots policy, CAPTCHA or network failure is **not** recorded as out of stock. The checker does not bypass blocks. It uses low request rates and short-lived backoff windows. Discovery is bounded, so it can miss short-lived or unusually named listings. A repeated alert is also possible after an ambiguous Discord timeout or state-save failure; delivery cannot be made exactly-once across both services.

Official reference: [GitHub schedule behaviour](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows).

## Common fixes

| What you see | What to do |
|---|---|
| `DISCORD_WEBHOOK_URL is missing/invalid` | Check the exact repository-secret name; paste the normal Discord URL with no extra `/github` suffix. It belongs in Secrets, not Variables. |
| Discord returns HTTP 404 | The webhook was deleted or copied incorrectly. Make a new webhook and replace the GitHub secret. |
| `Cannot create tracker-state`, HTTP 403 | Open repository **Settings -> Actions -> General -> Workflow permissions**. Allow **Read and write permissions**, save and retry. Organization rules can still prevent this; a personal repository is simpler. |
| `requirements.txt` or `tracker.py` not found | The files are one folder too deep. Put them at the repository root. |
| `ModuleNotFoundError: sote` | The `sote` folder was omitted or flattened during upload. Upload the folder with its files inside. |
| No workflow / no Run workflow button | Confirm the active YAML is at `.github/workflows/watch.yml` on the default branch. |
| A store is HTTP 403/429, robots-blocked or unreadable | It is not being checked successfully. Inspect that row; do not assume out of stock. Do not add bypass proxies or login cookies. |
| A game appears in Discord, but no phone ping | Check server/channel notification settings and phone permissions; close the desktop Discord session for a test. |
| No daily health message | Open Actions and inspect the most recent run, enabled state and any setup/error messages. |

## Small changes you can make later

Edit `config.json` through GitHub's pencil button, then commit to `main`.

To receive only stronger stock leads, set `"alert_possible": false`. To add an INR price cap, change `"max_price_inr": null` to a number such as `"max_price_inr": 4500`. Listings whose price cannot be parsed can still alert; availability is the priority. To stop a problematic store, change its `"enabled": true` to `false`.

Do not edit the `tracker-state` branch for normal settings. It is the program's memory, not your configuration. Deleting it can cause repeats.

To pause after buying the game, go to **Actions -> SOTE stock watcher -> ... -> Disable workflow**. Resume from the same menu. The active schedule can be changed in `.github/workflows/watch.yml`; the root spare copy is not active.

**Your first milestone:** a phone notification from `test`, followed by a `status` report showing the actual source coverage. No secrets need to be shared to review that report.
