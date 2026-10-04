"""A trail of who did what: logins (good and bad), password and account
changes, and every change to the settings, apps, dashboard and integrations.
One line per event on the backend's log, which is what the admin panel's Logs
tab shows and what a tool like fail2ban can read.

    2026-10-03 18:02:11 AUDIT login_failed user="admin" addr="203.0.113.5"

What browsers report about their own use (a visit, an app opened) is written
the same way with CLIENT in place of AUDIT - see routes/clientlog.py.

Never pass a password (or anything derived from one) to record()."""

import json
import logging
import sys

_logger = logging.getLogger("fyr.audit")
if not _logger.handlers:
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setFormatter(logging.Formatter("%(asctime)s AUDIT %(message)s", "%Y-%m-%d %H:%M:%S"))
    _logger.addHandler(_handler)
    _logger.setLevel(logging.INFO)
    _logger.propagate = False


def _clean(value):
    # Usernames and addresses come from the request: quoted and escaped, so a
    # name containing a line break cannot forge a second log line.
    return json.dumps(str(value)[:80], ensure_ascii=True)


def record(event, **fields):
    _logger.info("%s %s", event, " ".join(f"{key}={_clean(value)}" for key, value in fields.items()))


_client = logging.getLogger("fyr.client")
if not _client.handlers:
    _client_handler = logging.StreamHandler(sys.stderr)
    _client_handler.setFormatter(logging.Formatter("%(asctime)s CLIENT %(message)s", "%Y-%m-%d %H:%M:%S"))
    _client.addHandler(_client_handler)
    _client.setLevel(logging.INFO)
    _client.propagate = False


def record_client(event, **fields):
    _client.info("%s %s", event, " ".join(f"{key}={_clean(value)}" for key, value in fields.items()))
