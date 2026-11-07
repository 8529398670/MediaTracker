"""Everything that talks to the outside world: lookups (TMDB, Wikipedia,
TVmaze, Open Library, iTunes, OMDb, Wikidata), resolving pasted text into a
title, and filling in a title's details. Every call goes through net.py,
which is where politeness and the private-address refusal live."""
