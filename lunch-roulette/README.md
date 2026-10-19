# 🍱 Lunch Roulette

A small Slack bot that pairs up Sentry SFO onsite folks for lunch.

- **Opt in any time** for any of **Monday, Tuesday, Thursday** — via checkboxes on the
  app's Home tab, or `/lunch-roulette join mon thu`. Opt-ins stick week to week until
  you change them.
- **At 9:00 AM Pacific** on each of those days, everyone opted in for that day is
  randomly paired and gets a DM: *"you are paired up with @someone for lunch today"*.
- Odd number of people → one group of three, so nobody is left out.
- Tries to avoid re-pairing people who lunched together in the last 28 days.
- Only members of the SFO channel (`SFO_CHANNEL_ID`) can opt in.

## Commands

| Command | What it does |
|---|---|
| `/lunch-roulette join` | Opt in for Mon, Tue and Thu |
| `/lunch-roulette join mon thu` | Opt in for specific days |
| `/lunch-roulette leave` / `leave tue` | Opt out of all / some days |
| `/lunch-roulette status` | Show your days |

Opting in after 9:00 on a roulette day takes effect from the next roulette day.

## Setup

1. **Create the Slack app**: api.slack.com/apps → *Create New App* → *From a manifest* →
   paste [slack_manifest.yml](slack_manifest.yml). Install it to the workspace
   (likely needs a Slack admin's approval at Sentry).
2. **Tokens**:
   - *OAuth & Permissions* → Bot token (`xoxb-…`) → `SLACK_BOT_TOKEN`
   - *Basic Information* → App-Level Token with `connections:write` (`xapp-…`) → `SLACK_APP_TOKEN`
3. **SFO channel**: add the bot to the SFO office channel and copy its ID
   (channel details → bottom of the About tab) → `SFO_CHANNEL_ID`.
4. **Run**:

```bash
pip install -r requirements.txt
```

```bash
SLACK_BOT_TOKEN=xoxb-... SLACK_APP_TOKEN=xapp-... SFO_CHANNEL_ID=C0123456 python3 -m lunch_roulette.app
```

It uses Socket Mode, so it needs no public URL — just a long-running process
(a small VM, container, or internal k8s deployment). Opt-ins live in a SQLite file
(`LUNCH_DB_PATH`, default `lunch_roulette.db`); put it on a persistent volume.

### Optional settings

| Env var | Default | |
|---|---|---|
| `LUNCH_TZ` | `America/Los_Angeles` | Timezone for the 9am run |
| `LUNCH_PAIR_HOUR` | `9` | Hour pairs are sent |
| `LUNCH_NO_REPEAT_DAYS` | `28` | Avoid repeat partners within this window |
| `LUNCH_DB_PATH` | `lunch_roulette.db` | SQLite file |

### Sentry

The bot reports errors to Sentry and checks in a
[Cron Monitor](https://docs.sentry.io/product/crons/) (`lunch-roulette-pairing`)
on every 9am run, so you get alerted if pairing fails or doesn't run at all.
Create a Python project in Sentry, then set:

| Env var | Default | |
|---|---|---|
| `SENTRY_DSN` | unset (Sentry off) | The project's DSN (*Settings → Client Keys*) |
| `SENTRY_ENVIRONMENT` | `production` | Environment shown in Sentry |
| `SENTRY_TRACES_SAMPLE_RATE` | `0` | Set e.g. `1.0` to also send performance traces |

The cron monitor is created in Sentry automatically on the first scheduled run.

### Handy for testing

```bash
python3 -m lunch_roulette.app --run-now --dry-run
```

prints today's pairs without sending anything; `--run-now` alone pairs and sends
immediately. Each day can only be sent once, so a restart at 9:00 won't double-DM.

## Tests

```bash
python3 -m unittest discover tests
```
