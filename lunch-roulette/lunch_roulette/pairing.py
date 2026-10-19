"""Random pairing. Odd one out joins a pair to make a trio, so nobody is left alone.

We try a number of random shuffles and keep the one with the fewest
"repeat" lunches (people who were paired recently), so pairings stay fresh.
"""

import random
from typing import Dict, List, Optional, Set

ATTEMPTS = 200


def _group(shuffled: List[str]) -> List[List[str]]:
    groups = [shuffled[i : i + 2] for i in range(0, len(shuffled) - 1, 2)]
    if len(shuffled) % 2 == 1:
        groups[-1].append(shuffled[-1])  # make the last pair a trio
    return groups


def _repeats(groups: List[List[str]], recent: Dict[str, Set[str]]) -> int:
    count = 0
    for g in groups:
        for i, a in enumerate(g):
            for b in g[i + 1 :]:
                if b in recent.get(a, ()):
                    count += 1
    return count


def make_groups(
    people: List[str],
    recent: Optional[Dict[str, Set[str]]] = None,
    rng: Optional[random.Random] = None,
) -> List[List[str]]:
    """Split `people` into pairs (plus one trio if the count is odd).

    Fewer than 2 people -> no groups.
    """
    people = list(dict.fromkeys(people))  # dedupe, keep order
    if len(people) < 2:
        return []
    rng = rng or random.Random()
    recent = recent or {}

    best, best_score = None, None
    for _ in range(ATTEMPTS):
        shuffled = people[:]
        rng.shuffle(shuffled)
        groups = _group(shuffled)
        score = _repeats(groups, recent)
        if best_score is None or score < best_score:
            best, best_score = groups, score
            if score == 0:
                break
    return best
