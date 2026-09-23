"""Sync error type. Reported cleanly by the CLI, no tracebacks."""


class SyncError(Exception):
    """Expected sync failure: bad bundle, checksum mismatch, unknown peer, etc."""
