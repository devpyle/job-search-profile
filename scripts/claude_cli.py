"""Run the `claude` CLI, riding out Claude Code self-updates.

When Claude Code auto-updates, it replaces its binary in place. For a short
window the path is missing (ENOENT), not yet executable (EACCES), still
being written (ETXTBSY), or only partly written ("Exec format error",
ENOEXEC). A call that lands in that window used to fail the
whole job: a card stuck in Drafting, a radar run with every rating missing.
These errors mean "try again shortly", so retry them with a backoff.
"""

import errno
import subprocess
import time

_UPDATE_ERRNOS = {errno.ENOENT, errno.EACCES, errno.ETXTBSY, errno.ENOEXEC}
# Waits between attempts, in seconds (~2.5 minutes total) — longer than an
# update takes, short enough that a really-missing binary still fails fast-ish.
_BACKOFF = (5, 15, 30, 45, 60)


def run_cli(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """subprocess.run(cmd, **kwargs), retrying while the binary is mid-update."""
    for wait in (*_BACKOFF, None):
        try:
            return subprocess.run(cmd, **kwargs)
        except OSError as e:
            if e.errno not in _UPDATE_ERRNOS or wait is None:
                raise
            time.sleep(wait)
