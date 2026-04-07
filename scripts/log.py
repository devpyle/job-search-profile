"""Minimal log helper with consistent formatting and verbosity gating.

Usage:
    from log import log, init as log_init

    log_init()                          # call once from main(), reads --verbose from sys.argv
    log("Searching...", source="Adzuna") # always prints:  [Adzuna] Searching...
    log("details", verbose=True)         # only prints with --verbose flag
"""

import sys

VERBOSE = False


def init(argv=None):
    """Set VERBOSE from --verbose flag. Call once from main()."""
    global VERBOSE
    if argv is None:
        argv = sys.argv
    VERBOSE = "--verbose" in argv


def log(msg, *, source="", verbose=False):
    """Print with optional [source] prefix. Suppressed when verbose=True and VERBOSE is off."""
    if verbose and not VERBOSE:
        return
    prefix = f"[{source}] " if source else ""
    print(f"  {prefix}{msg}")
