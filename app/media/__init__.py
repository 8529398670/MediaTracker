"""Pure media logic: no database, no network, no HTTP.

Everything in here can be called from a route, a job, the legacy importer or
a test with plain values, which is what lets the same rules hold whichever
door a title comes in through.
"""
