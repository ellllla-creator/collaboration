"""Lunch Roulette Slack bot.

- Opt in/out any time via the App Home tab (checkboxes) or `/lunch-roulette`.
- Every Monday, Tuesday and Thursday at 9:00 America/Los_Angeles, everyone
  opted in for that day is randomly paired and DM'd their lunch partner.

Run:  python -m lunch_roulette.app            (bot + scheduler)
      python -m lunch_roulette.app --run-now  (pair today immediately, then exit)
      python -m lunch_roulette.app --run-now --dry-run  (print pairs, send nothing)
"""

import argparse
import logging
import os
from datetime import date, datetime, timedelta
from typing import List, Optional
from zoneinfo import ZoneInfo

import sentry_sdk
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sentry_sdk.crons import monitor
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from .db import DAY_NAMES, DAYS, Store
from .pairing import make_groups

log = logging.getLogger("lunch_roulette")

# Errors (including log.exception / log.error calls) are reported to Sentry.
# With SENTRY_DSN unset this is a no-op, so local runs and tests send nothing.
sentry_sdk.init(
    dsn=os.environ.get("SENTRY_DSN"),
    environment=os.environ.get("SENTRY_ENVIRONMENT", "production"),
    traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0")),
)

TZ = ZoneInfo(os.environ.get("LUNCH_TZ", "America/Los_Angeles"))
PAIR_HOUR = int(os.environ.get("LUNCH_PAIR_HOUR", "9"))
CRON_SCHEDULE = f"0 {PAIR_HOUR} * * 1,2,4"  # Mon, Tue, Thu
# Only members of this channel (e.g. #sfo-office) may opt in. Unset = anyone.
SFO_CHANNEL_ID = os.environ.get("SFO_CHANNEL_ID")
# Try not to re-pair people who had lunch together within this many days.
NO_REPEAT_DAYS = int(os.environ.get("LUNCH_NO_REPEAT_DAYS", "28"))

store = Store(os.environ.get("LUNCH_DB_PATH", "lunch_roulette.db"))
app = App(
    token=os.environ.get("SLACK_BOT_TOKEN"),
    signing_secret=os.environ.get("SLACK_SIGNING_SECRET"),
    token_verification_enabled=False if os.environ.get("LUNCH_OFFLINE") else True,
)


# --- eligibility ------------------------------------------------------------

def is_sfo_member(client, user_id: str) -> bool:
    if not SFO_CHANNEL_ID:
        return True
    cursor = None
    while True:
        resp = client.conversations_members(channel=SFO_CHANNEL_ID, cursor=cursor, limit=1000)
        if user_id in resp["members"]:
            return True
        cursor = resp.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            return False


def not_eligible_text() -> str:
    return (
        f"Lunch Roulette is for SFO onsite folks. Join <#{SFO_CHANNEL_ID}> first, "
        "then try again."
    )


def describe(days) -> str:
    if not days:
        return "You're not signed up for Lunch Roulette."
    names = [DAY_NAMES[d] for d in DAYS if d in days]
    return (
        f"You're in for *{', '.join(names)}*. "
        f"Pairs go out at {PAIR_HOUR}:00 each of those mornings."
    )


# --- App Home (checkbox opt-in) ---------------------------------------------

def home_view(user_id: str) -> dict:
    days = store.get_days(user_id)
    options = [
        {"text": {"type": "plain_text", "text": DAY_NAMES[d]}, "value": d} for d in DAYS
    ]
    checkboxes = {"type": "checkboxes", "action_id": "set_days", "options": options}
    selected = [o for o in options if o["value"] in days]
    if selected:
        checkboxes["initial_options"] = selected
    return {
        "type": "home",
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": "🍱 Lunch Roulette"}},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "Pick the days you're in the SFO office and up for lunch. "
                        f"At {PAIR_HOUR}:00 that morning you'll get a DM with your "
                        "random lunch buddy. Change this any time."
                    ),
                },
            },
            {"type": "actions", "elements": [checkboxes]},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": describe(days)}]},
        ],
    }


@app.event("app_home_opened")
def on_home_opened(event, client):
    client.views_publish(user_id=event["user"], view=home_view(event["user"]))


@app.action("set_days")
def on_set_days(ack, body, client):
    ack()
    user_id = body["user"]["id"]
    days = {o["value"] for o in body["actions"][0].get("selected_options", [])}
    if days and not is_sfo_member(client, user_id):
        client.chat_postMessage(channel=user_id, text=not_eligible_text())
        days = set()
    store.set_days(user_id, days)
    client.views_publish(user_id=user_id, view=home_view(user_id))


# --- slash command ----------------------------------------------------------

HELP = (
    "*Lunch Roulette*\n"
    "`/lunch-roulette join` – opt in for Mon, Tue and Thu\n"
    "`/lunch-roulette join mon thu` – opt in for specific days\n"
    "`/lunch-roulette leave` – opt out of everything\n"
    "`/lunch-roulette leave tue` – drop specific days\n"
    "`/lunch-roulette status` – see what you're signed up for\n"
    "Or use the checkboxes on the app's Home tab."
)


def parse_days(words: List[str]) -> Optional[set]:
    days = {w[:3].lower() for w in words}
    return days if days <= set(DAYS) else None


@app.command("/lunch-roulette")
def on_command(ack, command, client, respond):
    ack()
    user_id = command["user_id"]
    words = (command.get("text") or "").split()
    action, args = (words[0].lower(), words[1:]) if words else ("help", [])
    current = store.get_days(user_id)

    if action in ("join", "in", "optin"):
        days = parse_days(args) if args else set(DAYS)
        if days is None:
            return respond("Days must be some of: mon, tue, thu.")
        if not is_sfo_member(client, user_id):
            return respond(not_eligible_text())
        store.set_days(user_id, current | days)
    elif action in ("leave", "out", "optout"):
        days = parse_days(args) if args else set(DAYS)
        if days is None:
            return respond("Days must be some of: mon, tue, thu.")
        store.set_days(user_id, current - days)
    elif action != "status":
        return respond(HELP)
    respond(describe(store.get_days(user_id)))


# --- daily pairing ----------------------------------------------------------

def day_key(d: date) -> Optional[str]:
    return next((k for k, v in DAYS.items() if v == d.weekday()), None)


def partner_text(me: str, group: List[str]) -> str:
    others = [f"<@{u}>" for u in group if u != me]
    who = " and ".join(others)
    return (
        f"🍱 Lunch Roulette: you are paired up with {who} for lunch today! "
        "Reach out to pick a time and place."
    )


def run_pairing(today: Optional[date] = None, dry_run: bool = False) -> List[List[str]]:
    today = today or datetime.now(TZ).date()
    key = day_key(today)
    if key is None:
        log.info("%s is not a lunch roulette day; skipping", today)
        return []

    people = store.participants_for(key)
    if len(people) < 2:
        log.info("Only %d participant(s) for %s; nobody to pair", len(people), today)
        if dry_run or not store.record_run(today, []):
            return []
        for uid in people:
            app.client.chat_postMessage(
                channel=uid,
                text="🍱 Lunch Roulette: not enough people signed up today, so no "
                "pairing. Try again next time!",
            )
        return []

    recent = store.recent_partners(today - timedelta(days=NO_REPEAT_DAYS))
    groups = make_groups(people, recent)

    if dry_run:
        for g in groups:
            print(" + ".join(g))
        return groups

    if not store.record_run(today, groups):
        log.warning("Pairs for %s were already sent; not sending again", today)
        return []

    for group in groups:
        for uid in group:
            try:
                app.client.chat_postMessage(channel=uid, text=partner_text(uid, group))
            except Exception:
                log.exception("Failed to DM %s", uid)
    log.info("Paired %d people into %d groups for %s", len(people), len(groups), today)
    return groups


# Sentry Cron Monitor: alerts if the 9am run fails, or doesn't happen at all
# (e.g. the bot is down). The monitor is created in Sentry on first check-in.
@monitor(
    monitor_slug="lunch-roulette-pairing",
    monitor_config={
        "schedule": {"type": "crontab", "value": CRON_SCHEDULE},
        "timezone": str(TZ),
        "checkin_margin": 60,  # minutes; matches misfire_grace_time below
        "max_runtime": 15,
    },
)
def scheduled_pairing():
    run_pairing()


def main():
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-now", action="store_true", help="pair today and exit")
    parser.add_argument("--dry-run", action="store_true", help="print pairs, send nothing")
    opts = parser.parse_args()

    if opts.run_now:
        run_pairing(dry_run=opts.dry_run)
        return

    scheduler = BackgroundScheduler(timezone=TZ)
    scheduler.add_job(
        scheduled_pairing,
        CronTrigger(day_of_week="mon,tue,thu", hour=PAIR_HOUR, minute=0, timezone=TZ),
        misfire_grace_time=60 * 60,  # if the bot was briefly down at 9:00, still run by 10:00
        coalesce=True,
    )
    scheduler.start()
    log.info("Scheduler started: Mon/Tue/Thu at %02d:00 %s", PAIR_HOUR, TZ)
    SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"]).start()


if __name__ == "__main__":
    main()
