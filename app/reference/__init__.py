"""Public reference data kept as plain files under <app dir>/storage/:
the IMDb ratings table, the poster cache, the Wikipedia film catalogue and
its age ratings. None of it is personal and all of it can be fetched again,
so it is not encrypted -- encrypting 30 MB of Wikipedia would cost memory and
CPU and protect nothing. Everything personal lives in the database."""
