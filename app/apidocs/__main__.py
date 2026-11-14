"""Write the API reference from the code:

    python -m app.apidocs        rewrite config/api.json, mcp.json, api.md and mcp.md
    scripts/api_docs.sh          the same

It needs nothing but the app's own requirements: no database, no server, no
test client. app/tests/test_api_docs.py fails while a committed file differs
from what this would write."""
from __future__ import annotations

from app.apidocs.generate import CONFIG, documents


def main() -> None:
    for name, text in documents().items():
        (CONFIG / name).write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote config/{name}")


if __name__ == "__main__":
    main()
