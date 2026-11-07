"""Background work: filling in titles, the IMDb ratings download, Apple TV
ids, and the Wikipedia catalogue harvest. Each job is a thread with a stop
flag and a status (runner.py); the lifespan in app/main.py starts the ones
that are due, and admins start or stop the rest from the Jobs screen."""
