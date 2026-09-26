"""Other's types, on the server. No network.

The app keeps Other's types as the library's own list — added, renamed and
deleted there — and the server is what keeps it: cleaned on the way in,
written with the titles, and left alone by a page too old to send it. A title
may carry a type the app made up, and the fill-in pass asks about it the way
the list says to.

    python3 tests/test_types.py
"""
import os
import pathlib
import shutil
import sys
import tempfile

DATA = tempfile.mkdtemp(prefix="mt-types-")
os.environ["MT_DATA_DIR"] = DATA          # the environment beats .env
os.environ["MT_NET"] = "0"
sys.dont_write_bytecode = True
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "server"))

from library import Library                      # noqa: E402
from normalize import normalize_item, normalize_types   # noqa: E402

bad = 0
total = 0


def check(label, got, want):
    global bad, total
    total += 1
    if got == want:
        print(f"ok    {label}")
    else:
        bad += 1
        print(f"FAIL  {label}\n        got  {got!r}\n        want {want!r}")


check("a list is cleaned: bad ids, the tabs, repeats and blank names go",
      normalize_types([
          {"id": "audiobook", "label": " Audiobooks ", "lookup": "book"},
          {"id": "stand-up", "label": "Stand-up", "lookup": "nonsense"},
          {"id": "tv", "label": "TV"},
          {"id": "Not An Id", "label": "x"},
          {"id": "stand-up", "label": "again"},
          {"id": "blank", "label": "   "},
          "not even a dict",
      ]),
      [{"id": "audiobook", "label": "Audiobooks", "lookup": "book"},
       {"id": "stand-up", "label": "Stand-up", "lookup": "other"}])
check("a title keeps a type the app made up",
      normalize_item({"title": "Live at the Apollo", "type": "stand-up"})["type"], "stand-up")
check("but not something that could never be an id",
      normalize_item({"title": "x", "type": "<b>"})["type"], "movie")

path = pathlib.Path(DATA) / "library.json"
lib = Library(path)
check("a new library has no list of its own: the app shows its starting one",
      "types" in lib.snapshot(), False)

ok, _ = lib.replace({"rev": lib.data["rev"], "items": [
    {"id": "t1", "title": "Live at the Apollo", "type": "stand-up"}],
    "types": [{"id": "stand-up", "label": "Stand-up", "lookup": "movie"},
              {"id": "other", "label": "Other", "lookup": "other"}]})
check("the list is written with the titles", [ok, [t["id"] for t in lib.snapshot()["types"]]],
      [True, ["stand-up", "other"]])
check("the fill-in pass asks about it the way the list says", lib.lookup_for("stand-up"), "movie")
check("a type the list does not name is not guessed at", lib.lookup_for("podcast"), None)

lib.replace({"rev": lib.data["rev"], "items": lib.data["items"]})
check("a page too old to send a list leaves it as it is",
      [t["id"] for t in lib.snapshot()["types"]], ["stand-up", "other"])
lib.replace({"rev": lib.data["rev"], "items": lib.data["items"], "types": []})
check("and an empty one is never taken for 'delete them all'",
      [t["id"] for t in lib.snapshot()["types"]], ["stand-up", "other"])

again = Library(path)
check("it survives a restart, and so does the title's type",
      [[t["label"] for t in again.snapshot()["types"]], again.snapshot()["items"][0]["type"]],
      [["Stand-up", "Other"], "stand-up"])

shutil.rmtree(DATA, ignore_errors=True)
print(f"\n{total - bad} passed, {bad} failed")
sys.exit(1 if bad else 0)
