"""Is this the same work, or one that merely shares a name?

Normalise both sides, compare them the ordinary way — the token-set
comparison any fuzzy-match library does — over the two or three canonical
forms a title comes in. Then rank on the things that actually separate two
works of one name: the year, and how many people have rated it.

One domain rule on top of the general one: a number in a title is part of
its identity. "Rocky" is not "Rocky II" and "Days of Heaven" is not "100
Days to Heaven", however close the letters run.

Pure: no providers, no network, no state.
"""

from __future__ import annotations

import math
import re
import unicodedata
from difflib import SequenceMatcher

# Words that carry no part of a title's identity.
STOP_WORDS = {"the", "a", "an", "of", "in", "on", "at", "to", "for", "and",
              "from", "with", "by", "part"}

ARTICLE = re.compile(r"^(?:the|a|an|le|la|les|el|los|das|der|die)\s+", re.I)

# Where a provider appends a subtitle. Comparing before it as well as after is
# what makes "Sunrise" the same work as "Sunrise: A Song of Two Humans"
# without also making it "The Hunger Games: Sunrise on the Reaping".
SUBTITLE = re.compile(r"\s*[:–—]\s+|\s+-\s+")


def fold(text: str) -> str:
    """A title reduced to what two spellings of it have in common."""
    flat = unicodedata.normalize("NFKD", str(text or ""))
    flat = "".join(c for c in flat if not unicodedata.combining(c)).lower()
    flat = flat.replace("&", " and ").replace("+", " and ")
    flat = re.sub(r"['’‘`]", "", flat)          # "Your's" is "Yours"
    return " ".join(re.sub(r"[^\w\s]+", " ", flat).split())


def forms(title: str) -> list[str]:
    """The shapes a title is worth being compared in."""
    out = []
    for text in (title, SUBTITLE.split(str(title or ""), maxsplit=1)[0]):
        folded = fold(text)
        for shape in (folded, ARTICLE.sub("", folded).strip()):
            if len(shape) > 1 and shape not in out:
                out.append(shape)
    return out


def _numbers(folded: str) -> tuple:
    return tuple(w for w in folded.split() if w.isdigit())


def _pair(a: str, b: str) -> float:
    if a == b:
        return 1.0
    if _numbers(a) != _numbers(b):
        return 0.0

    sorted_words = lambda t: " ".join(sorted(t.split()))       # noqa: E731
    score = max(SequenceMatcher(None, a, b).ratio(),
                SequenceMatcher(None, sorted_words(a), sorted_words(b)).ratio())

    # One title sitting inside a much longer one. Worth credit, discounted by
    # how much of the longer title it leaves unaccounted for — which is the
    # difference between a subtitle and a different film that happens to
    # contain the word.
    short, long = sorted((a, b), key=len)
    words_long = set(long.split())
    if words_long and len(short) / len(long) < 0.7:
        covered = len(set(short.split()) & words_long) / len(words_long)
        score = max(score, covered * (0.6 + 0.4 * covered))
    return min(score, 1.0)


def similarity(wanted: str, found: str) -> float:
    """How nearly two titles are the same work, from 0 to 1."""
    ours, theirs = forms(wanted), forms(found)
    if not ours or not theirs:
        return 0.0
    return max(_pair(a, b) for a in ours for b in theirs)


# Below this they are different works, whatever the year says. Above CERTAIN
# they are one work spelled two ways, and only the year tells them apart.
FLOOR = 0.62
CERTAIN = 0.93


def rank(rows: list[dict], title: str, year: int | None = None,
         kind: str = "any") -> list[dict]:
    """Score every candidate and sort them, best first.

    The year is a hint, not a gate: half the years in a list written by hand
    are the year it was watched or simply wrong, and refusing everything three
    years out means refusing "Far and Away" because the document says 1989.
    What settles it instead is how well known the work is — the 1992 film has
    thirteen hundred ratings and the programme of the same name has one.
    """
    scored = []
    for row in rows:
        near = similarity(title, row.get("title") or "")
        if near < FLOOR:
            continue
        score = near

        found = row.get("year")
        if year and found:
            gap = abs(found - year)
            score += 0.16 if gap == 0 else 0.11 if gap == 1 else 0.05 if gap <= 2 \
                else -0.02 if gap <= 5 else -0.10
        elif year:
            score -= 0.03

        # Ratings, not TMDB's popularity: popularity tracks this week's
        # traffic and an unreleased film outscores every classic on it.
        score += min(0.13, math.log10(1 + (row.get("_votes") or 0)) * 0.042)
        score += min(0.02, (row.get("_pop") or 0) / 1000.0)
        if row.get("poster"):
            score += 0.03
        if kind and kind != "any":
            score += 0.02 if row.get("type") == kind else -0.01

        out = dict(row)
        out["_score"] = round(score, 4)
        out["_title_score"] = round(near, 4)
        scored.append(out)

    scored.sort(key=lambda r: -r["_score"])
    return scored


def confident(scored: list[dict], year: int | None = None) -> bool:
    """Whether the top of a ranking is safe to write without being asked.

    Either the name matches almost exactly, or the year agrees. Two works of
    one name with no year between them is the case where a guess puts another
    film's poster on the card, so that one is a question, not an answer.
    """
    if not scored:
        return False
    best = scored[0]
    if best["_title_score"] < FLOOR:
        return False

    found = best.get("year")
    if year and found and abs(found - year) <= 1:
        return True
    if best["_title_score"] < CERTAIN:
        return False
    return not (len(scored) > 1 and not year
                and scored[1]["_title_score"] >= CERTAIN
                and best["_score"] - scored[1]["_score"] < 0.05)
