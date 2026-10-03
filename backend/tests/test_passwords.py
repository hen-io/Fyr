"""How passwords are stored and judged, and the account rules around them."""

import logging
import os
import re
import threading
import time
import unicodedata

import pytest
from werkzeug.security import generate_password_hash

from app import auth, passwords, ratelimit
from app.passwords import password_problem
from conftest import ADMIN, FAST_PARAMS, REAL_PARAMS, VISITOR

FAST_PREFIX = "$argon2id$v=19$m=64,t=1,p=1$"

CONFIRM = {"confirm_password": ADMIN[1]}
FRONTEND = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "src")


def _stored(app, username):
    return auth.load_users(app.config)[username]


def _put_raw_hash(app, username, hashed):
    auth.update_users(lambda users: users[username].update(password_hash=hashed), app.config)


# --- the hash itself ----------------------------------------------------------------


def test_the_real_settings_are_at_or_above_the_owasp_floor_for_argon2id():
    # OWASP's minimum: 19 MiB with two passes (or 46 MiB with one), one lane
    assert REAL_PARAMS["memory_cost"] >= 19 * 1024 and REAL_PARAMS["time_cost"] >= 2 and REAL_PARAMS["parallelism"] >= 1
    assert FAST_PARAMS != REAL_PARAMS


def test_hashing_with_the_real_settings(monkeypatch):
    monkeypatch.setattr(passwords, "PARAMS", REAL_PARAMS)
    one, two = passwords.hash_password("correct horse battery"), passwords.hash_password("correct horse battery")
    assert one.startswith("$argon2id$v=19$m=65536,t=3,p=1$") and one != two  # Argon2id, a fresh salt every time
    assert passwords.verify_password(one, "correct horse battery") == (True, False)
    assert passwords.verify_password(one, "correct horse batterY") == (False, False)
    assert passwords.dummy_hash().startswith("$argon2id$v=19$m=65536,t=3,p=1$")


@pytest.mark.parametrize("method", ["scrypt:32768:8:1", "scrypt:65536:8:2", "pbkdf2:sha256:1000"])
def test_hashes_from_earlier_versions_still_verify_and_are_marked_for_upgrade(method):
    old = generate_password_hash("correct horse battery", method=method)
    assert passwords.verify_password(old, "correct horse battery") == (True, True)
    assert passwords.verify_password(old, "wrong") == (False, False)


def test_argon2_hash_with_weaker_settings_is_marked_for_upgrade(monkeypatch):
    weak = passwords.hash_password("correct horse battery")  # made with the test settings
    monkeypatch.setattr(passwords, "PARAMS", REAL_PARAMS)
    assert passwords.verify_password(weak, "correct horse battery") == (True, True)


def test_a_hash_made_with_older_settings_is_upgraded_at_the_next_login(app, login):
    old = generate_password_hash(VISITOR[1], method="pbkdf2:sha256:1000")
    _put_raw_hash(app, VISITOR[0], old)
    epoch = _stored(app, VISITOR[0]).get("session_epoch")

    assert app.test_client().post("/api/login", json={"username": VISITOR[0], "password": "wrong-password"}).status_code == 401
    assert _stored(app, VISITOR[0])["password_hash"] == old  # a wrong password upgrades nothing

    session = login(VISITOR)
    upgraded = _stored(app, VISITOR[0])
    assert upgraded["password_hash"].startswith(FAST_PREFIX)
    assert upgraded.get("session_epoch") == epoch and session.get("/api/me").status_code == 200  # same password: nobody is signed out
    assert login(VISITOR).get("/api/me").status_code == 200


def test_damaged_or_missing_hash_never_logs_in_and_never_crashes(app, anon):
    for broken in ("", "not-a-hash", "nosuchmethod:1$salt$abcd", "$argon2id$v=19$m=64,t=1,p=1$broken", "$argon2id$", None):
        _put_raw_hash(app, VISITOR[0], broken)
        assert anon.post("/api/login", json={"username": VISITOR[0], "password": VISITOR[1]}).status_code == 401
        assert anon.post("/api/login", json={"username": VISITOR[0], "password": ""}).status_code == 401
        ratelimit.reset()
    _put_raw_hash(app, VISITOR[0], passwords.hash_password(VISITOR[1]))


def test_unknown_user_costs_the_same_work_as_a_wrong_password(app, anon, monkeypatch):
    calls = []
    real = passwords._matches
    monkeypatch.setattr(passwords, "_matches", lambda stored, candidate: calls.append(stored[: len(FAST_PREFIX)]) or real(stored, candidate))
    anon.post("/api/login", json={"username": "nobody-at-all", "password": "x"})
    anon.post("/api/login", json={"username": VISITOR[0], "password": "x"})
    assert calls == [FAST_PREFIX, FAST_PREFIX]


def test_the_same_password_works_however_the_keyboard_composed_it(app, login):
    composed = unicodedata.normalize("NFC", "blåbærsyltetøy-kafé")
    decomposed = unicodedata.normalize("NFD", composed)
    assert composed != decomposed
    assert login(VISITOR).put("/api/me/password", json={"current_password": VISITOR[1], "new_password": decomposed}).status_code == 200
    assert login((VISITOR[0], composed)).get("/api/me").status_code == 200
    assert login((VISITOR[0], decomposed)).get("/api/me").status_code == 200

    # an account whose hash was made before normalising still gets in, and is brought up to date
    _put_raw_hash(app, VISITOR[0], passwords._hasher().hash(decomposed))
    assert login((VISITOR[0], decomposed)).get("/api/me").status_code == 200
    assert login((VISITOR[0], composed)).get("/api/me").status_code == 200
    _put_raw_hash(app, VISITOR[0], passwords.hash_password(VISITOR[1]))


def test_a_flood_of_checks_is_turned_away_instead_of_piling_up(anon, monkeypatch):
    monkeypatch.setattr(passwords, "_slots", threading.BoundedSemaphore(1))
    monkeypatch.setattr(passwords, "WAIT_SECONDS", 0.05)
    passwords._slots.acquire()  # every slot is taken
    response = anon.post("/api/login", json={"username": VISITOR[0], "password": VISITOR[1]})
    assert response.status_code == 503 and response.get_json() == {"error": "busy"} and response.headers["Retry-After"]
    passwords._slots.release()
    assert anon.post("/api/login", json={"username": VISITOR[0], "password": VISITOR[1]}).status_code == 200


# --- what is accepted as a password ---------------------------------------------------


@pytest.mark.parametrize(
    "password,username,expected",
    [
        ("short12", "", "password_too_short"),
        ("password", "", "password_too_common"),
        ("12345678", "", "password_too_common"),
        ("kari1234", "kari", "password_too_similar"),
        ("blå-hest", "kari", None),
        (None, "", "password_too_short"),
        ("x" * 1025, "", "password_too_long"),
        ("correct horse battery", "henrik", None),
        ("Tr0ub4dor&3x", "henrik", None),
        ("gul-sykkel-på-taket", "kari", None),
        ("adminpass123", "admin1", None),
        ("henrik1234", "henrik", "password_too_similar"),
        ("Henrik!2025", "henrik", "password_too_similar"),
        ("henrik123456", "henrik", "password_too_similar"),
        ("henrik-qwertyuiop", "henrik", "password_too_similar"),
        ("henrikSommer2025", "henrik", "password_too_similar"),
        ("henrik-liker-fisk", "henrik", None),
        ("1234567890", "", "password_too_common"),
        ("0987654321", "", "password_too_common"),
        ("qwertyuiop", "", "password_too_common"),
        ("aaaaaaaaaaaa", "", "password_too_common"),
        ("1212121212", "", "password_too_common"),
        ("Password123", "", "password_too_common"),
        ("P@ssw0rd123!", "", "password_too_common"),
        ("Sommer2025!", "", "password_too_common"),
        ("passordpassord", "", "password_too_common"),
        ("1q2w3e4r5t", "", "password_too_common"),
        ("homeassistant1", "", "password_too_common"),
    ],
)
def test_password_rules(password, username, expected):
    assert password_problem(password, username) == expected


def test_every_way_of_setting_a_password_applies_the_rules(admin, login):
    me = login(VISITOR)
    assert me.put("/api/me/password", json={"current_password": VISITOR[1], "new_password": "Password123"}).get_json() == {"error": "password_too_common"}
    assert me.put("/api/me/password", json={"current_password": VISITOR[1], "new_password": VISITOR[0] * 2 + "99"}).get_json() == {"error": "password_too_similar"}
    assert me.put("/api/me/password", json={"current_password": VISITOR[1], "new_password": "x" * 1500}).get_json() == {"error": "password_too_long"}
    assert admin.post("/api/users", json={"username": "newbie", "password": "qwertyuiop", **CONFIRM}).get_json() == {"error": "password_too_common"}
    assert admin.put(f"/api/users/{VISITOR[0]}/password", json={"password": "Sommer2025!", **CONFIRM}).get_json() == {"error": "password_too_common"}
    assert me.get("/api/me").status_code == 200 and login(VISITOR).get("/api/me").status_code == 200  # nothing was changed


def test_minimum_length_matches_the_frontend():
    with open(os.path.join(FRONTEND, "constants", "password.js"), encoding="utf-8") as handle:
        assert int(re.search(r"PASSWORD_MIN_LENGTH = (\d+)", handle.read()).group(1)) == passwords.MIN_LENGTH


# --- the users file ---------------------------------------------------------------------


@pytest.mark.skipif(os.name == "nt", reason="file modes are not meaningful on Windows")
def test_the_users_file_is_readable_by_its_owner_only(app, login):
    login(VISITOR).put("/api/me/profile", json={"display_name": "V"})
    assert os.stat(os.path.join(app.config["DATA_DIR"], "users.json")).st_mode & 0o077 == 0


def test_a_slower_write_cannot_undo_a_password_change(app, login):
    """Two requests each doing read-then-write used to be able to overwrite
    one another: a profile update that read the file just before a password
    change would write the OLD password (and old sessions) back."""
    started = threading.Event()

    def slow_profile_update(users):
        started.set()
        time.sleep(0.3)  # still "in the middle of" its read-change-write
        users[VISITOR[0]]["display_name"] = "written late"

    writer = threading.Thread(target=lambda: auth.update_users(slow_profile_update, app.config))
    writer.start()
    assert started.wait(2)
    epoch = auth.change_password(VISITOR[0], "a-brand-new-password", app.config)
    writer.join()

    stored = _stored(app, VISITOR[0])
    assert stored["display_name"] == "written late" and stored["session_epoch"] == epoch
    assert login((VISITOR[0], "a-brand-new-password")).get("/api/me").status_code == 200
    assert app.test_client().post("/api/login", json={"username": VISITOR[0], "password": VISITOR[1]}).status_code == 401
    auth.change_password(VISITOR[0], VISITOR[1], app.config)
    auth.set_user_fields(VISITOR[0], app.config, display_name=None)


# --- sessions of an account that is replaced ------------------------------------------------


def test_a_recreated_account_does_not_bring_old_sessions_back(admin, login):
    """Delete "ghost" and create a new "ghost" (now an admin): a session of the
    old one that has been sitting unused must not become a session of the new one."""
    assert admin.post("/api/users", json={"username": "ghost", "password": "the-first-ghost", "role": "visitor", **CONFIRM}).status_code == 201
    forgotten = login(("ghost", "the-first-ghost"))
    assert admin.delete("/api/users/ghost", json=CONFIRM).status_code == 200
    assert admin.post("/api/users", json={"username": "ghost", "password": "the-second-ghost", "role": "admin", **CONFIRM}).status_code == 201
    assert forgotten.get("/api/me").status_code == 401
    assert forgotten.get("/api/users").status_code == 401
    assert login(("ghost", "the-second-ghost")).get("/api/users").status_code == 200
    assert admin.delete("/api/users/ghost", json=CONFIRM).status_code == 200


def test_command_line_overwrite_keeps_the_profile_and_ends_sessions(app, login):
    session = login(VISITOR)
    assert session.put("/api/me/profile", json={"display_name": "Kept"}).status_code == 200
    before = _stored(app, VISITOR[0])["session_epoch"]
    auth.create_user(VISITOR[0], "set-from-the-shell", "visitor", app.config, overwrite=True)  # what manage.py adduser does
    after = _stored(app, VISITOR[0])
    assert after["display_name"] == "Kept" and after["session_epoch"] > before
    assert session.get("/api/me").status_code == 401
    with pytest.raises(auth.Refused):
        auth.create_user(VISITOR[0], "another-password-1", "visitor", app.config)
    auth.create_user(VISITOR[0], VISITOR[1], "visitor", app.config, overwrite=True)
    auth.set_user_fields(VISITOR[0], app.config, display_name=None)


# --- the trail ------------------------------------------------------------------------------


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


def test_account_events_are_logged_without_secrets(admin, anon, login):
    capture = _Capture()
    logger = logging.getLogger("fyr.audit")
    logger.addHandler(capture)
    try:
        anon.post("/api/login", json={"username": "eve\nlogin user=\"admin1\"", "password": "s3cret-guess"}, headers={"X-Forwarded-For": "203.0.113.200"})
        login(VISITOR).put("/api/me/password", json={"current_password": VISITOR[1], "new_password": "another-password-9"})
        admin.put(f"/api/users/{VISITOR[0]}/password", json={"password": VISITOR[1], **CONFIRM})
        admin.put(f"/api/users/{VISITOR[0]}/role", json={"role": "admin", "confirm_password": "wrong"})
    finally:
        logger.removeHandler(capture)
    text = "\n".join(capture.lines)
    events = [line.split(" ", 1)[0] for line in capture.lines]
    assert events == ["login_failed", "login", "password_changed", "password_reset", "admin_confirmation_failed"]
    assert 'addr="203.0.113.200"' in capture.lines[0] and "\\n" in capture.lines[0] and len(capture.lines) == 5  # the forged line break stayed inside the quotes
    for secret in ("s3cret-guess", VISITOR[1], "another-password-9", ADMIN[1], "wrong"):
        assert secret not in text
