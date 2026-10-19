"""SQLite storage: who opted in for which days, and the history of past pairings."""

import sqlite3
from datetime import date
from typing import Dict, Iterable, List, Set

# Lunch roulette only runs on these weekdays (date.weekday(): Mon=0 ... Sun=6).
DAYS = {"mon": 0, "tue": 1, "thu": 3}
DAY_NAMES = {"mon": "Monday", "tue": "Tuesday", "thu": "Thursday"}


class Store:
    def __init__(self, path: str = "lunch_roulette.db"):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS optins (
                user_id TEXT NOT NULL,
                day     TEXT NOT NULL,
                PRIMARY KEY (user_id, day)
            );
            CREATE TABLE IF NOT EXISTS pairings (
                lunch_date TEXT NOT NULL,
                group_id   INTEGER NOT NULL,
                user_id    TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS runs (
                lunch_date TEXT PRIMARY KEY
            );
            """
        )
        self.conn.commit()

    # --- opt-ins -----------------------------------------------------------

    def set_days(self, user_id: str, days: Iterable[str]) -> None:
        """Replace a user's opt-in days (empty iterable = fully opted out)."""
        with self.conn:
            self.conn.execute("DELETE FROM optins WHERE user_id = ?", (user_id,))
            self.conn.executemany(
                "INSERT INTO optins (user_id, day) VALUES (?, ?)",
                [(user_id, d) for d in days],
            )

    def get_days(self, user_id: str) -> Set[str]:
        rows = self.conn.execute("SELECT day FROM optins WHERE user_id = ?", (user_id,))
        return {r[0] for r in rows}

    def participants_for(self, day: str) -> List[str]:
        rows = self.conn.execute(
            "SELECT user_id FROM optins WHERE day = ? ORDER BY user_id", (day,)
        )
        return [r[0] for r in rows]

    # --- pairing history ---------------------------------------------------

    def record_run(self, lunch_date: date, groups: List[List[str]]) -> bool:
        """Save today's groups. Returns False if today was already paired
        (protects against double-sending if the job fires twice)."""
        try:
            with self.conn:
                self.conn.execute(
                    "INSERT INTO runs (lunch_date) VALUES (?)", (lunch_date.isoformat(),)
                )
                self.conn.executemany(
                    "INSERT INTO pairings (lunch_date, group_id, user_id) VALUES (?, ?, ?)",
                    [
                        (lunch_date.isoformat(), gid, uid)
                        for gid, group in enumerate(groups)
                        for uid in group
                    ],
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def recent_partners(self, since: date) -> Dict[str, Set[str]]:
        """Map each user to everyone they've lunched with on or after `since`."""
        rows = self.conn.execute(
            "SELECT lunch_date, group_id, user_id FROM pairings WHERE lunch_date >= ?",
            (since.isoformat(),),
        )
        groups: Dict[tuple, List[str]] = {}
        for lunch_date, gid, uid in rows:
            groups.setdefault((lunch_date, gid), []).append(uid)
        partners: Dict[str, Set[str]] = {}
        for members in groups.values():
            for uid in members:
                partners.setdefault(uid, set()).update(m for m in members if m != uid)
        return partners
