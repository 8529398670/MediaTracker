"""What the importer is expected to swallow.

Every line here was a real failure once: a year written as a span, a stray
comma, a misspelling, a film filed under television, a link to a page that
does not say what it is about. Run it against a server that has a TMDB key
and a network:

    MT_PORT=8699 MT_DATA_DIR=/tmp/mt python3 server/app.py &
    python3 tests/test_importer.py            # or MT_BASE=... to point elsewhere

It calls the live providers on purpose. Their data moves, so a title drifting
out of this list is worth reading before it is worth "fixing" — but a whole
column of failures means the matcher has regressed.
"""
import json, os, sys, time, urllib.parse, urllib.request

BASE = os.environ.get("MT_BASE", "http://127.0.0.1:8699") + "/api/resolve"

# (input, kind, expected title fragment or None for "must not be confident")
CASES = [
    # a bare title, and a title with a year in every notation
    ("The weather girl - 2009",            "movie", "Weather Girl"),
    ("Weather Girl (2009)",                "movie", "Weather Girl"),
    ("Yes, Minister - 1980-1984",          "movie", "Yes Minister"),
    ("The Wire (2002-2008)",               "tv",    "The Wire"),
    ("Cheers - 1982-present",              "tv",    "Cheers"),
    # misspellings
    ("the shwashank redemtion",            "movie", "Shawshank"),
    ("O Brother , Where Art Though",       "movie", "O Brother"),
    ("Colin in Accounts",                  "tv",    "Colin from Accounts"),
    ("Inglorious Basterds",                "movie", "Inglourious Basterds"),
    ("Pulp Fictoin",                       "movie", "Pulp Fiction"),
    # punctuation and spelling conventions
    ("Your's, Mine, and Ours (1968)",      "movie", "Yours, Mine and Ours"),
    ("The Prince and Me 4",                "movie", "The Prince & Me 4"),
    ("Up Close and Personal (1996)",       "movie", "Up Close & Personal"),
    ("Wall-E",                             "movie", "WALL"),
    ("Amelie",                             "movie", "Am"),
    # prose that a document wrapped round a title
    # two films of this name and no year given: a choice, not a guess
    ('Practical "chic suspense" pick: The Thomas Crown Affair', "movie", None),
    ('Practical "chic suspense" pick: The Thomas Crown Affair (1999)', "movie", "Thomas Crown"),
    # filed under the wrong medium
    ("Days of Heaven",                     "tv",    "Days of Heaven"),
    ("An Education (2009)",                "tv",    "An Education"),
    ("Harley Quinn (2019)",                "movie", "Harley Quinn"),
    # links
    ("https://www.imdb.com/title/tt1085515/fullcredits/", "any", "Weather Girl"),
    ("https://m.imdb.com/title/tt0110912/?ref_=nv_sr_1",  "any", "Pulp Fiction"),
    ("tt0111161",                                          "any", "Shawshank"),
    ("https://www.themoviedb.org/movie/19900-weather-girl","any", "Weather Girl"),
    ("https://www.themoviedb.org/tv/1396",                 "any", "Breaking Bad"),
    ("https://en.wikipedia.org/wiki/O_Brother,_Where_Art_Thou%3F", "any", "O Brother"),
    ("https://en.wikipedia.org/wiki/Parasite_(2019_film)", "any", "Parasite"),
    ("https://letterboxd.com/film/weather-girl/",          "any", "Weather Girl"),
    ("https://www.rottentomatoes.com/m/o_brother_where_art_thou", "any", "O Brother"),
    ("https://trakt.tv/shows/colin-from-accounts",         "any", "Colin from Accounts"),
    ("https://www.tvmaze.com/shows/431",                   "any", "Friends"),
    ("https://myanimelist.net/anime/1535/Death_Note",      "anime", None),
    ("https://myanimelist.net/anime/1535/Death_Note",      "tv", None),
    # things that are not titles, and must not be answered with a guess
    ("https://www.imdb.com/name/nm0000138/",               "any", None),
    ("Sunrise",                                            "movie", None),
    ("asdfasdf",                                           "movie", None),
]

def call(text, kind):
    url = f"{BASE}?q={urllib.parse.quote(text)}&type={kind}"
    with urllib.request.urlopen(url, timeout=90) as r:
        return json.load(r)

good = bad = 0
for text, kind, want in CASES:
    t0 = time.time()
    try:
        d = call(text, kind)
    except Exception as exc:
        print(f"ERR  {text[:44]:46} {type(exc).__name__}")
        bad += 1
        continue
    ms = int((time.time() - t0) * 1000)
    best = d.get("best") or {}
    title = best.get("title") or ""
    if want is None:
        ok = not d.get("confident")
        detail = f"correctly unsure ({d.get('note') or title!r})" if ok else f"WRONGLY SURE: {title!r}"
    else:
        ok = bool(d.get("confident")) and want.lower() in title.lower()
        detail = f"{title!r} {best.get('year') or ''} {best.get('type') or ''}" \
                 + ("" if best.get("poster") else " NO-POSTER")
        if not ok:
            detail += f"   want {want!r} conf={d.get('confident')}"
    good += ok
    bad += not ok
    print(f"{'ok ' if ok else 'FAIL'} {text[:44]:46} {ms:5}ms {(d.get('via') or ''):13} {detail}")

print(f"\n{good} passed, {bad} failed, of {len(CASES)}")
sys.exit(1 if bad else 0)
