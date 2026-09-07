#!/usr/bin/env python3
"""Wikipedia's markup, and what the year lists mean by it.

Everything here is offline and instant: the parser is pure, so a page is a
string in this file rather than a request to Wikimedia. The fixtures are cut
down from the real articles — the shapes below are the ones that actually
turn up, including the two that break a naive split (a pipe inside a template,
and a film that held number one for three weeks written once with a rowspan).

    python3 tests/test_wiki.py
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

import certs                                            # noqa: E402
import lists                                            # noqa: E402
import verdicts                                         # noqa: E402
import wiki                                             # noqa: E402


AMERICAN = """
{{Short description|None}}
More than 356 '''American''' feature films were released in '''[[1949 in film|1949]]'''.

<gallery>
File:Tracy Hepburn Adams Rib.jpg| ''[[Adam's Rib]]''
</gallery>

==A-B==
{| class="wikitable" style="width:100%;"
|-
! style="width:21%;"| Title
! style="width:16%;"| Director
! style="width:31%;"| Cast
! style="width:13%;"| Genre
! style="width:19%;"| Notes
|-
|''[[Abandoned (1949 film)|Abandoned]]''|| [[Joseph M. Newman]] || \
[[Dennis O'Keefe]], [[Gale Storm]] || [[Film noir]] || [[Universal Pictures|Universal]]
|-
|''[[Adam's Rib]]''||{{sortname|George|Cukor}} ||[[Spencer Tracy]], \
[[Katharine Hepburn]]||Romantic comedy || [[MGM]]; script by [[Ruth Gordon]]<ref>{{cite web|url=http://x|title=y}}</ref>
|-
| ''[[Alias Mary Smith]]'' || [[E. Mason Hopper]] || [[Blanche Mehaffey]] || Mystery, Crime || Independent
|}
"""

BOX_OFFICE = """
==Number-one films==
{| class="wikitable sortable"
! {{abbr|#|Week number}}
! Week ending
! Film
! Notes
|-
| 1 || {{dts|link=off|1949|January|5}} || rowspan="2" | ''[[The Paleface (1948 film)|The Paleface]]'' ||
|-
| 2 || {{dts|link=off|1949|January|12}} ||
|-
| 3 || {{dts|link=off|1949|January|19}} || rowspan="3" | ''[[Jolson Sings Again]]''{{efn|†}} || style="background-color:#FFFF99"|†
|-
| 4 || {{dts|link=off|1949|January|26}} ||
|-
| 5 || {{dts|link=off|1949|February|2}} ||
|-
| 6 || {{dts|link=off|1949|February|9}} || TBD || No survey published.
|-
| 7 || {{dts|link=off|1949|February|16}} || TBD || No survey published.
|}
"""

YEAR_IN_FILM = """
==Top-grossing films (U.S.)==
{| class="wikitable sortable"
|+ Highest-grossing films of 1949
|-
! Rank !! Title !! Distributor !! Domestic rentals
|-
! style="text-align:center;"| '''1'''
|''[[Jolson Sings Again]]''
| [[Columbia Pictures|Columbia]]
| $5,000,000<ref name=Finler>{{cite book |title=The Hollywood Story}}</ref>
|-
! style="text-align:center;"| '''2'''
|''[[Battleground (film)|Battleground]]''
| rowspan="2" | [[MGM]]
| $4,722,000
|-
! style="text-align:center;"| '''3'''
| ''[[The Stratton Story]]''
| $3,831,000
|}

==Awards==
{| class="wikitable"
! Category/Organization !! 7th Golden Globe Awards !! 22nd Academy Awards
|-
| Best Film || ''[[Johnny Belinda (1948 film)|Johnny Belinda]]'' || ''[[All the King's Men (1949 film)|All the King's Men]]''
|-
| Best Director || Robert Rossen || Joseph L. Mankiewicz
|}
"""

TOPIC = """
The gangster cycle began with ''[[Little Caesar (film)|Little Caesar]]'' and
''[[The Public Enemy]]'', which ''[[Variety (magazine)|Variety]]'' reviewed
alongside ''[[The New York Times]]''.  See also [[Pre-Code Hollywood]].
"""


FAILED = []


def check(label, got, want):
    ok = got == want
    if not ok:
        FAILED.append(label)
    print(f"{'ok  ' if ok else 'FAIL'}  {label}")
    if not ok:
        print(f"        got  {got!r}\n        want {want!r}")


def main() -> int:
    # -- markup ------------------------------------------------------------
    check("a link becomes its label",
          wiki.text_of("''[[Abandoned (1949 film)|Abandoned]]''"), "Abandoned")
    check("a reference is not part of the text",
          wiki.text_of("MGM<ref>{{cite web|url=http://x}}</ref>"), "MGM")
    check("a template that names a person is read",
          wiki.text_of("{{sortname|George|Cukor}}"), "George Cukor")
    check("a template that names a date is read too",
          wiki.text_of("{{dts|link=off|1949|January|5}}"), "January 5 1949")
    check("a template that is only formatting is dropped",
          wiki.text_of("{{nowrap|Fox Film}} {{cite book|title=x}}"), "Fox Film")
    check("italics and bold are not the title",
          wiki.text_of("'''American''' ''feature'' films"),
          "American feature films")

    # A pipe inside a template separates arguments, not cells. This is the
    # split that a line-by-line reader gets wrong.
    check("cells are split on the pipes that are cells",
          wiki.split_top("a || {{dts|1949|May|3}} || [[x|y]]", "||"),
          ["a ", " {{dts|1949|May|3}} ", " [[x|y]]"])

    check("an article that names a work in italics is a candidate",
          [t for t, _ in wiki.italic_links(TOPIC)],
          ["Little Caesar (film)", "The Public Enemy", "Variety (magazine)",
           "The New York Times"])

    # -- the year lists ----------------------------------------------------
    rows = lists.parse_american(AMERICAN, 1949)
    check("every film on the page, and nothing from the gallery", len(rows), 3)
    check("the row is read column by column",
          [rows[1][k] for k in ("article", "title", "year", "director", "cast")],
          ["Adam's Rib", "Adam's Rib", 1949, "George Cukor",
           ["Spencer Tracy", "Katharine Hepburn"]])
    check("the genre is folded onto the app's vocabulary",
          [rows[0]["genres"], rows[1]["genres"], rows[2]["genres"]],
          [["Crime"], ["Romance", "Comedy"], ["Mystery", "Crime"]])
    # A compound the page writes as one phrase has to come apart, or a filter
    # for Drama never finds the film the page called a "Crime Drama".
    check("a compound genre is both of its genres",
          [lists.genres_from("Crime Drama"), lists.genres_from("Comedy horror"),
           lists.genres_from("Film noir"), lists.genres_from("Sci-Fi")],
          [["Crime", "Drama"], ["Comedy", "Horror"], ["Crime"],
           ["Science Fiction"]])
    check("a rare one the app has no word for is kept as it was written",
          lists.genres_from("Serial"), ["Serial"])
    check("but a category that is not a genre at all is dropped",
          [lists.genres_from("american black-and-white", strict=True),
           lists.genres_from("1930s crime action", strict=True)],
          [[], ["Crime", "Action"]])
    check("and what the page actually said is kept beside it",
          rows[0]["genreText"], "Film noir")

    weeks = lists.parse_boxoffice(BOX_OFFICE, 1949)
    check("a rowspan is a film that held number one for that many weeks",
          [(r["title"], r["weeks"]) for r in weeks],
          [("Jolson Sings Again", 3), ("The Paleface", 2)])
    check("the dagger is the biggest film of the year",
          [r["title"] for r in weeks if r["topOfYear"]], ["Jolson Sings Again"])
    check("a 1948 film that was number one in 1949 is still a 1948 film",
          [r["year"] for r in weeks if r["title"] == "The Paleface"], [1948])
    # The 1946 page says TBD for the sixteen weeks Variety published no
    # survey; sixteen weeks at number one is exactly the wrong answer.
    check("a week the page has no film for is not a film",
          [r["title"] for r in weeks if "TBD" in r["title"]], [])

    ranked = lists.parse_yearfilm(YEAR_IN_FILM, 1949)
    check("the ranked table is read with its money",
          [(r["title"], r["rank"], r["gross"]) for r in ranked[:3]],
          [("Jolson Sings Again", 1, "$5,000,000"),
           ("Battleground", 2, "$4,722,000"),
           ("The Stratton Story", 3, "$3,831,000")])
    check("and the award is named by whoever gave it",
          sorted((r["title"], r["award"]) for r in ranked if r["award"]),
          [("All the King's Men", "Academy Award for Best Picture"),
           ("Johnny Belinda", "Golden Globe for Best Picture")])

    check("a topic page offers what it names in italics",
          sorted(lists.topic_candidates(TOPIC)),
          ["Little Caesar (film)", "The New York Times", "The Public Enemy",
           "Variety (magazine)"])

    # -- the merge ---------------------------------------------------------
    check("the article is the identity, so two of one name stay apart",
          lists.key_of({"article": "The Killers (1946 film)"})
          == lists.key_of({"article": "The Killers (1964 film)"}), False)
    check("and one film written two ways is one film",
          lists.key_of({"article": "Adam's Rib"})
          == lists.key_of({"article": "Adam’s Rib"}), True)

    film = {"title": "Jolson Sings Again", "year": 1949, "genres": [],
            "cast": [], "signals": {}, "from": []}
    lists._blend(film, weeks[0], {"set": "boxoffice", "topic": ""})
    lists._blend(film, ranked[0], {"set": "yearfilm", "topic": ""})
    check("three pages fold into one film",
          [film["signals"], sorted(film["from"]), film["gross"]],
          [{"weeks": 3, "topOfYear": True, "rank": 1},
           ["boxoffice", "yearfilm"], "$5,000,000"])

    quiet = {"title": "Alias Mary Smith", "signals": {}, "from": ["american"],
             "director": "E. Mason Hopper", "cast": ["x"], "genres": ["Mystery"]}
    check("and the one everyone noticed sorts above the one nobody did",
          lists.score(film) > lists.score(quiet), True)

    # -- the query -------------------------------------------------------
    # The lean rows a query walks, stood up here rather than read from disk:
    # [key, year, score, haystack, genres, topics, flags].
    rows = [
        ["w:a", 1931, 40, "a", ["crime", "drama"], [], lists.BOXOFFICE,
         ["clark gable", "jean harlow"]],
        ["w:b", 1933, 30, "b", ["western"], [], 0, ["john wayne"]],
        ["w:c", 1935, 20, "c", ["crime", "western"], ["pre-code-hollywood"], 0,
         ["clark gable"]],
        ["w:d", 1949, 10, "d", ["comedy"], [], lists.AWARDED, []],
        ["w:e", None, 5, "e", [], [], 0, []],
    ]
    lists.catalogue = lambda: rows
    lists.full_records = lambda page: [{"key": r[lists.R_KEY]} for r in page]
    lists.coverage = lambda: {}
    shown = lambda **kw: [f["key"] for f in lists.query(**kw)["films"]]

    check("the whole catalogue when nothing is asked of it",
          shown(), ["w:a", "w:b", "w:c", "w:d", "w:e"])
    check("a year range is inclusive at both ends",
          shown(year_from=1931, year_to=1933), ["w:a", "w:b"])
    check("an open end is open", shown(year_from=1935), ["w:c", "w:d"])
    check("one genre, however it was spelled when it was clicked",
          shown(genres="Crime"), ["w:a", "w:c"])
    check("any of these is the wider net",
          shown(genres="crime,western"), ["w:a", "w:b", "w:c"])
    check("all of these is the narrower one",
          shown(genres=["crime", "western"], genre_mode="all"), ["w:c"])
    check("and a year range narrows it further still",
          shown(genres="crime,western", year_from=1931, year_to=1933),
          ["w:a", "w:b"])
    check("genres and the box-office cut are both true at once",
          shown(genres="crime", only="boxoffice"), ["w:a"])
    check("the same genre asked for twice is asked for once",
          lists.wanted_genres(["Crime", "crime", " CRIME "]), ["crime"])

    # An actor is the billed cast, not the haystack: the point of clicking a
    # name is that it means the person, not the word.
    check("one name finds everything they were in",
          shown(actor="Clark Gable"), ["w:a", "w:c"])
    check("however it was typed", shown(actor="clark  gable"), ["w:a", "w:c"])
    check("and it narrows with everything else",
          shown(actor="Clark Gable", genres="western"), ["w:c"])
    check("a lean row written before there was a cast field still answers",
          lists._cast_of(["w:x", 1931, 0, "x", [], [], 0]), [])

    # The counts a picker shows: each is worked out with its own filter
    # lifted, so it says what choosing it would give rather than what is
    # already chosen.
    facets = lists.query(genres="crime")["facets"]
    check("the genre counts ignore the genres already picked",
          [(g["label"], g["count"]) for g in facets["genres"]],
          [("Crime", 2), ("Western", 2), ("Comedy", 1), ("Drama", 1)])
    check("but the year counts do not",
          facets["years"], {"1931": 1, "1935": 1})
    narrowed = lists.query(year_from=1931, year_to=1933)["facets"]
    check("and the genre counts are only the years showing",
          [(g["label"], g["count"]) for g in narrowed["genres"]],
          [("Crime", 1), ("Drama", 1), ("Western", 1)])
    check("while the year counts ignore the range they are offered against",
          narrowed["years"], {"1931": 1, "1933": 1, "1935": 1, "1949": 1, "0": 1})

    # -- the rating ------------------------------------------------------
    # The one filter here that reads something the year lists never printed,
    # so unlike the rest it has three states and not two: rated, known to
    # have none, and never asked about. A picker that folded the last two
    # together would call a lookup that has not run an answer.
    check("a rating is stored as it is printed, whatever case it arrived in",
          [certs.clean(" pg-13 "), certs.clean("Q18665344"), certs.clean("")],
          ["PG-13", "", ""])
    check("and several are put on the scale, least restrictive first",
          certs.in_order(["R", "X", "G", "R"]), ["G", "R", "X"])
    check("one Wikidata has no word for keeps its place after the ones it does",
          certs.in_order(["Approved", "PG"]), ["PG", "APPROVED"])
    check("the same rating asked for twice is asked for once",
          lists.wanted_ratings(["pg", "PG", " Pg "]), ["PG"])
    check("and the two that are not ratings stay as they are",
          lists.wanted_ratings("PG,none,unknown"), ["PG", "none", "unknown"])

    with tempfile.TemporaryDirectory() as scratch:
        store = certs.Certs(Path(scratch) / "certs.json")
        store.put("w:a", "tt1", ["R"])
        store.put("w:b", "tt2", ["X", "R"])      # cut and rated again
        store.put("w:c", "", [])                 # asked, and there is none
        store.flush(force=True)                  # "w:d" and "w:e" never asked

        real_certs, certs.STORE = certs.STORE, store
        try:
            check("one rating finds the films that carry it",
                  shown(ratings="R"), ["w:a", "w:b"])
            check("including one that carries it as the second of two",
                  shown(ratings="X"), ["w:b"])
            check("several always mean any of them",
                  shown(ratings=["R", "none"]), ["w:a", "w:b", "w:c"])
            check("what Wikidata says has no rating is not what it has not "
                  "been asked about",
                  [shown(ratings="none"), shown(ratings="unknown")],
                  [["w:c"], ["w:d", "w:e"]])
            check("and it narrows with everything else",
                  shown(ratings="R", genres="western"), ["w:b"])
            facets = lists.query(ratings="R")["facets"]
            check("the picker offers the scale in the order it is read, not "
                  "biggest first",
                  [(r["label"], r["count"]) for r in facets["ratings"]],
                  [("R", 2), ("X", 1), ("Not rated", 1), ("Not looked up", 2)])
            check("with its own filter lifted, like every other count here",
                  [(g["label"], g["count"]) for g in
                   lists.query(ratings="R")["facets"]["genres"]],
                  [("Crime", 1), ("Drama", 1), ("Western", 1)])
            check("but the others applied",
                  [(r["label"], r["count"]) for r in
                   lists.query(genres="comedy")["facets"]["ratings"]],
                  [("Not looked up", 1)])
            check("and a rating nothing carries finds nothing rather than "
                  "everything", shown(ratings="NC-17"), [])
        finally:
            certs.STORE = real_certs

        check("what was written survives the process that wrote it",
              certs.Certs(store.path).get("w:b"), ["tt2", ["R", "X"]])
        check("and a film asked about is known even with no rating to show",
              [certs.Certs(store.path).known("w:c"),
               certs.Certs(store.path).known("w:d")], [True, False])

    # -- posters -----------------------------------------------------------
    # One call for fifty titles, answered under whatever name the article
    # actually lives at. Wikipedia is stubbed: what is under test is the
    # unpicking of the answer, not the network.
    asked = []

    def fake_api(params):
        asked.append(params)
        return {"query": {
            "normalized": [{"from": "city lights", "to": "City Lights"}],
            "redirects": [{"from": "Adam's Rib", "to": "Adam's Rib (1949 film)"}],
            "pages": [
                {"title": "City Lights",
                 "thumbnail": {"source": "https://thumb.wikimedia.org/a/city.jpg"}},
                {"title": "Adam's Rib (1949 film)",
                 "thumbnail": {"source": "https://thumb.wikimedia.org/b/rib.jpg"}},
                {"title": "Trader Horn (1931 film)"},
            ],
        }}

    real_api, lists._api = lists._api, fake_api
    lists._FACTS.clear()
    try:
        found = lists.page_images(
            ["city lights", "Adam's Rib", "Trader Horn (1931 film)"])
        check("a spelling Wikipedia fixed still answers to what was asked",
              found.get("city lights"), "https://thumb.wikimedia.org/a/city.jpg")
        check("and so does an article that redirects somewhere else",
              found.get("Adam's Rib"), "https://thumb.wikimedia.org/b/rib.jpg")
        check("a film with no free image is simply absent",
              "Trader Horn (1931 film)" in found, False)
        check("one call carries the whole batch",
              [asked[0]["titles"], asked[0]["prop"]],
              ["city lights|Adam's Rib|Trader Horn (1931 film)", "pageimages"])

        # `facts` folds the two calls together; Wikidata is stubbed out to
        # nothing here so the poster half can be seen on its own. What it
        # learns is written down, so it is written to a scratch file — the
        # real one is a quarter of an hour of Wikidata and not a test's to
        # scribble in.
        real_ids, lists.identifiers = lists.identifiers, lambda names: {}
        scratch = tempfile.TemporaryDirectory()
        real_certs = certs.STORE
        certs.STORE = certs.Certs(Path(scratch.name) / "certs.json")
        try:
            got = lists.facts(["city lights", "Trader Horn (1931 film)"])
            check("the one without an image is remembered as having none",
                  {k: v["thumb"] for k, v in got.items()},
                  {"city lights": "https://thumb.wikimedia.org/a/city.jpg",
                   "Trader Horn (1931 film)": ""})
            before = len(asked)
            lists.facts(["city lights", "Trader Horn (1931 film)"])
            check("so neither is asked about twice", len(asked), before)
            # And the half that is written down outlives the process: a
            # second run of the app knows without asking Wikidata again.
            check("what Wikidata said is on disk, keyed the way a verdict is",
                  sorted(certs.STORE.snapshot()),
                  ["w:city lights", "w:trader horn 1931 film"])
        finally:
            lists.identifiers = real_ids
            certs.STORE = real_certs
            scratch.cleanup()
    finally:
        lists._api = real_api
        lists._FACTS.clear()

    # -- the identifiers ---------------------------------------------------
    # One query for fifty films, answered under the article that was asked
    # for. Wikidata is stubbed; what is under test is the shape of the answer.
    def fake_sparql(url, **kw):
        fake_sparql.asked = url
        base = "https://en.wikipedia.org/wiki/"
        cell = lambda v: {"value": v}                          # noqa: E731
        return {"results": {"bindings": [
            {"article": cell(base + "City_Lights"), "imdb": cell("tt0021749"),
             "ratingLabel": cell("G")},
            {"article": cell(base + "Adam%27s_Rib"), "imdb": cell("tt0041090")},
            {"article": cell(base + "Barbary_Coast_(film)"),
             "ratingLabel": cell("Q18665344")},
            # A film cut and rated again arrives as one row per rating.
            {"article": cell(base + "A_Clockwork_Orange_(film)"),
             "imdb": cell("tt0066921"), "ratingLabel": cell("X")},
            {"article": cell(base + "A_Clockwork_Orange_(film)"),
             "imdb": cell("tt0066921"), "ratingLabel": cell("R")},
        ]}}

    real_fetch, lists.fetch_json = lists.fetch_json, fake_sparql
    lists._FACTS.clear()
    try:
        found = lists.identifiers(
            ["City Lights", "Adam's Rib", "Barbary Coast (film)",
             "A Clockwork Orange (film)", "Nowhere"])
        check("an id comes back under the article that was asked for",
              found.get("City Lights"),
              {"imdb": "tt0021749", "rating": "G", "ratings": ["G"]})
        check("an apostrophe in a title survives the round trip",
              found.get("Adam's Rib"),
              {"imdb": "tt0041090", "rating": "", "ratings": []})
        check("an item id is not a rating anyone can read, so it is dropped",
              found.get("Barbary Coast (film)"),
              {"imdb": "", "rating": "", "ratings": []})
        # Both are true of the film and both should find it, so the second
        # joins the first rather than overwriting it — and the one shown is
        # the one it is rated now, which is the lower of the two.
        check("a film rated twice keeps both, least restrictive first",
              found.get("A Clockwork Orange (film)"),
              {"imdb": "tt0066921", "rating": "R", "ratings": ["R", "X"]})
        check("and a film Wikidata does not have is simply absent",
              "Nowhere" in found, False)
        check("a bracket stays as it is, because the sitelink has it that way",
              "Barbary_Coast_(film)" in fake_sparql.asked.replace("%28", "(")
              .replace("%29", ")"), True)
        check("two properties are asked for, not every claim ever made",
              ["P345" in fake_sparql.asked, "P1657" in fake_sparql.asked,
               "wbgetentities" in fake_sparql.asked],
              [True, True, False])
    finally:
        lists.fetch_json = real_fetch
        lists._FACTS.clear()

    # -- verdicts ----------------------------------------------------------
    # Skipping is the half of the signal that says *not this*. Written to a
    # scratch file here, never to the real one.
    with tempfile.TemporaryDirectory() as scratch:
        store = verdicts.Verdicts(Path(scratch) / "verdicts.json")
        store.set("w:b", "skip")
        store.set("w:d", "skip")
        check("a verdict is counted", store.counts()["skip"], 2)
        check("and it says which films", sorted(store.keys("skip")), ["w:b", "w:d"])
        check("an empty verdict takes it back",
              [store.set("w:b", "")["skip"], sorted(store.keys("skip"))],
              [1, ["w:d"]])
        check("and it survives the process that wrote it",
              sorted(verdicts.Verdicts(store.path).keys("skip")), ["w:d"])
        check("a verdict nobody defined is not stored",
              store.set("w:a", "banana")["skip"], 1)

        real, verdicts.STORE = verdicts.STORE, store
        try:
            check("a skipped film is gone from the list",
                  shown(), ["w:a", "w:b", "w:c", "w:e"])
            check("and gone from the counts a picker offers",
                  lists.query()["facets"]["years"].get("1949"), None)
            check("show-skipped is the same catalogue, the other way round",
                  shown(skipped="only"), ["w:d"])
            check("and the filters still apply inside it",
                  shown(skipped="only", genres="western"), [])
            check("the count of them travels with every answer",
                  lists.query()["verdicts"]["skip"], 1)
            check("nothing is hidden when nothing is asked to be",
                  shown(skipped="all"), ["w:a", "w:b", "w:c", "w:d", "w:e"])
        finally:
            verdicts.STORE = real

    print(f"\n{'FAILED: ' + ', '.join(FAILED) if FAILED else 'all good'}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
