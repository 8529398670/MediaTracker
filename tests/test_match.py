"""Is this the same work, or one that merely shares a name?

No network and no providers — server/match.py is pure, which is the point of
it being its own module. Every pair below is one the matcher used to get
wrong, in one direction or the other: the ones it wrongly rejected because a
list spells things differently from a database, and the ones it wrongly
accepted because two different works have most of their letters in common.

    python3 tests/test_match.py
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "server"))

from match import FLOOR, confident, explains, rank, similarity   # noqa: E402

# (typed, found, should it be treated as the same work)
SAME = [
    # a list written by hand against a database
    ("The weather girl", "Weather Girl", True),
    ("Your\'s, Mine, and Ours", "Yours, Mine and Ours", True),
    ("The Prince and Me 4", "The Prince & Me 4: The Elephant Adventure", True),
    ("Up Close & Personal", "Up Close and Personal", True),
    ("Amelie", "Amélie", True),
    ("Wall-E", "WALL·E", True),
    ("Yes, Minister", "Yes Minister", True),
    ("Space 1999", "Space: 1999", True),
    # a title that is the beginning of the record's own name
    ("Sunrise", "Sunrise: A Song of Two Humans", True),
    # typos
    ("O Brother , Where Art Though", "O Brother, Where Art Thou?", True),
    ("Colin in Accounts", "Colin from Accounts", True),
    ("The Goonie", "The Goonies", True),
    # and the ones that are not the same work at all
    ("Sunrise", "The Hunger Games: Sunrise on the Reaping", False),
    ("Days of Heaven", "100 Days to Heaven", False),
    ("An Education", "Hellementary: An Education in Death", False),
    ("The Thing", "The Thing From Another World", False),
    ("Dickinson", "Dickinsonia", False),
    ("Physical", "Physically Fit", False),
    # a part number is not a spelling
    ("Rocky", "Rocky II", False),
    ("Alien", "Alien 3", False),
    ("Toy Story", "Toy Story 3", False),
    ("Rocky II", "Rocky 2", True),
]

# Whether a record accounts for every word that was typed. This is what tells
# two identically shaped document lines apart.
EXPLAINS = [
    ("Shockproof - Patricia Night",
     {"title": "Shockproof", "cast": ["Cornel Wilde", "Patricia Knight"]}, True),
    ("Once Upon a Time - Carry Grant",
     {"title": "Once Upon a Time in Mexico", "cast": ["Antonio Banderas"]}, False),
    ("The Shadow", {"title": "The Shadow Strays", "cast": []}, False),
    ("The Shadow", {"title": "The Shadow", "cast": ["Alec Baldwin"]}, True),
    ("Blade Runner", {"title": "Blade Runner 2049", "cast": ["Ryan Gosling"]}, False),
    ("Colin in Accounts",
     {"title": "Colin from Accounts", "cast": ["Patrick Brammall"]}, True),
]


def main() -> int:
    bad = 0
    for typed, found, same in SAME:
        score = similarity(typed, found)
        if (score >= FLOOR) != same:
            bad += 1
            print(f"FAIL {score:.3f} {typed!r} vs {found!r} — "
                  f"{'should' if same else 'should not'} match")
        else:
            print(f"ok   {score:.3f} {'same ' if same else 'other'} "
                  f"{typed!r} / {found!r}")

    for query, row, want in EXPLAINS:
        got = explains(query, row)
        if got != want:
            bad += 1
            print(f"FAIL explains({query!r}, {row['title']!r}) = {got}, want {want}")
        else:
            print(f"ok   explains {query!r} / {row['title']!r} = {got}")

    # The year is a hint, not a gate: a document's year is wrong as often as
    # not, and the well-known work is what a bare title means.
    rows = [
        {"title": "Far and Away", "year": 1992, "type": "movie",
         "poster": "p", "_votes": 1343, "_pop": 10.6, "sourceId": "movie/1"},
        {"title": "Far And Away", "year": 2017, "type": "tv",
         "poster": "p", "_votes": 1, "_pop": 0.9, "sourceId": "tv/2"},
    ]
    ranked = rank(rows, "Far and Away", 1989, "tv")
    if not ranked or ranked[0]["year"] != 1992:
        bad += 1
        print(f"FAIL a document year of 1989 should still find the 1992 film, "
              f"got {ranked[0] if ranked else None}")
    else:
        print("ok   a wrong year in the document still finds the known film")

    # A name that is merely very close is enough when the year agrees, and is
    # not enough on its own — which is the whole difference between a typo and
    # a different subject with a similar name.
    typo = [{"title": "Ninotchka", "year": 1939, "type": "movie", "poster": "p",
             "_votes": 400, "_pop": 5.0, "sourceId": "movie/1"}]
    if not confident(rank(typo, "Ninotchkia", 1939, "movie"), 1939, "Ninotchkia"):
        bad += 1
        print("FAIL 'Ninotchkia' in 1939 should be Ninotchka (1939)")
    else:
        print("ok   a one-letter typo is accepted when the year agrees")
    apart = [{"title": "Dickinsonia", "year": 2023, "type": "movie", "poster": "p",
              "_votes": 2, "_pop": 1.0, "sourceId": "movie/2"}]
    if rank(apart, "Dickinson", 2019, "movie"):
        bad += 1
        print("FAIL 'Dickinson' must not match 'Dickinsonia'")
    else:
        print("ok   a similar name with a different year is still refused")

    # Two works of one name and nothing to separate them is a question.
    pair = [{"title": "The Thing", "year": 1982, "type": "movie", "poster": "p",
             "_votes": 8216, "_pop": 19.7, "sourceId": "movie/1"},
            {"title": "The Thing", "year": 2011, "type": "movie", "poster": "p",
             "_votes": 3321, "_pop": 10.1, "sourceId": "movie/2"}]
    if confident(rank(pair, "The Thing", None, "movie"), None, "The Thing"):
        bad += 1
        print("FAIL two films of one name with no year given should not be certain")
    else:
        print("ok   two films of one name with no year given is a question")
    if not confident(rank(pair, "The Thing", 1982, "movie"), 1982, "The Thing"):
        bad += 1
        print("FAIL a year of 1982 should settle it")
    else:
        print("ok   a year settles which of the two it is")

    total = len(SAME) + len(EXPLAINS) + 6
    print(f"\n{total - bad} passed, {bad} failed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
