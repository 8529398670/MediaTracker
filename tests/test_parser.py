"""How a title with a year on it is read. No network, no providers.

The same twenty shapes are parsed by server/seed.py and by the copy of the
parser in public/js/porting.js, and the two have to agree — the browser
importer and the start-up seed import must not disagree about what a line
says. The JavaScript half of that check needs a JS runtime and lives in
tests/parity.sh; this half runs anywhere.

    python3 tests/test_parser.py
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "server"))

from seed import is_placeholder, split_title           # noqa: E402

# (line, title, year, notes)
CASES = [
    # a year given as the run a programme was on: the first year names it,
    # and the whole span comes off the title
    ("Yes, Minister – 1980–1984",    "Yes, Minister", 1980, ""),
    ("Dickinson – 2019–2021",        "Dickinson",     2019, ""),
    ("Seinfeld - 1989-98",           "Seinfeld",      1989, ""),
    ("Cheers - 1982-present",        "Cheers",        1982, ""),
    ("Twin Peaks – 1990–?",          "Twin Peaks",    1990, ""),
    ("The Wire (2002-2008)",         "The Wire",      2002, ""),
    ("Friends (1994–2004)",          "Friends",       1994, ""),
    # one year, however it is written
    ("The weather girl - 2009",      "The weather girl", 2009, ""),
    ("Alien (1979)",                 "Alien",         1979, ""),
    ("Kill Bill: Vol. 1 - 2003",     "Kill Bill: Vol. 1", 2003, ""),
    # how Wikipedia disambiguates, which is how a pasted link arrives
    ("Parasite (2019 film)",         "Parasite",      2019, ""),
    ("Alien (1979 film)",            "Alien",         1979, ""),
    ("The Wire (TV series)",         "The Wire",      None, "TV series"),
    # a note is a note
    ("Wagon Master (1950) (a note)", "Wagon Master",  1950, "a note"),
    # a title that is a year is not a year
    ("1917",                         "1917",          None, ""),
    ("Yes, Minister – 1980 (1984)",  "Yes, Minister", 1984, ""),
]

PLACEHOLDERS = ["asdf", "asdfasdf", "qwerty", "zxcv", "", "   ", "asdf123"]
NOT_PLACEHOLDERS = ["Alien", "M", "1917", "Se7en", "Up"]

def main() -> int:
    bad = 0
    for line, title, year, notes in CASES:
        got = split_title(line)
        if got != (title, year, notes):
            bad += 1
            print(f"FAIL {line!r}\n  want {(title, year, notes)}\n  got  {got}")
        else:
            print(f"ok   {line!r:32} -> {got[0]!r} {got[1]}")

    for text in PLACEHOLDERS:
        if not is_placeholder(text):
            bad += 1
            print(f"FAIL {text!r} should be read as a placeholder")
    for text in NOT_PLACEHOLDERS:
        if is_placeholder(text):
            bad += 1
            print(f"FAIL {text!r} is a title, not a placeholder")

    total = len(CASES) + len(PLACEHOLDERS) + len(NOT_PLACEHOLDERS)
    print(f"\n{total - bad} passed, {bad} failed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
