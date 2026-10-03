"""How passwords are stored, checked and judged. Everything about a password
goes through here, so there is one place to read (and change) the policy."""

import secrets
import threading
import unicodedata
from contextlib import contextmanager

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error, InvalidHashError
from werkzeug.security import check_password_hash

# Argon2id (the algorithm OWASP and RFC 9106 recommend first) with a random
# 16-byte salt per password: three passes over 64 MiB of memory, about a tenth
# of a second per check on an ordinary server - well above OWASP's minimum
# (two passes over 19 MiB). The cost is what makes a stolen users.json slow
# and expensive to guess passwords against.
#
# Changing these is safe: a stored hash names the algorithm and settings it
# was made with, old ones keep working - including the scrypt and PBKDF2
# hashes of earlier versions - and each is re-made with the current settings
# the next time its owner logs in (see needs_rehash).
PARAMS = {"time_cost": 3, "memory_cost": 64 * 1024, "parallelism": 1}

MIN_LENGTH = 8
MAX_LENGTH = 1024

# A check costs real memory and processor time, and the login form is open to
# anyone. At most this many run at once; the rest wait their turn briefly and
# are then told to come back, so a flood of login attempts can neither exhaust
# the container's memory nor occupy every request thread.
MAX_CONCURRENT = 2
WAIT_SECONDS = 8
_slots = threading.BoundedSemaphore(MAX_CONCURRENT)


class Busy(Exception):
    """Too many password checks are already running."""


@contextmanager
def _slot():
    if not _slots.acquire(timeout=WAIT_SECONDS):
        raise Busy()
    try:
        yield
    finally:
        _slots.release()


def _hasher():
    return PasswordHasher(salt_len=16, hash_len=32, **PARAMS)


def _normal(password):
    """The same characters can be typed as different code points depending on
    the keyboard and operating system ("é" as one character or as e + accent).
    Normalising first means such a password works from every device."""
    return unicodedata.normalize("NFKC", password)


def hash_password(password):
    with _slot():
        return _hasher().hash(_normal(password))


def needs_rehash(stored):
    """True for anything that is not Argon2id with exactly the current settings."""
    if not isinstance(stored, str) or not stored.startswith("$argon2id$"):
        return True
    try:
        return _hasher().check_needs_rehash(stored)
    except Exception:
        return True


_dummies = {}


def dummy_hash():
    """A real hash nobody knows the password of. A login for a username that
    does not exist is checked against this, so it costs the same work as one
    that does - response time must not reveal which usernames are real."""
    key = tuple(sorted(PARAMS.items()))
    if key not in _dummies:
        _dummies[key] = _hasher().hash(secrets.token_urlsafe(32))
    return _dummies[key]


def _matches(stored, candidate):
    with _slot():
        try:
            if stored.startswith("$argon2"):
                return _hasher().verify(stored, candidate)
            # scrypt / PBKDF2 hashes from before Argon2id (Werkzeug's format)
            return check_password_hash(stored, candidate)
        except (Argon2Error, InvalidHashError):  # wrong password, or a damaged hash
            return False
        except Exception:  # an unknown or malformed legacy format is simply "no"
            return False


def verify_password(stored, password):
    """(matches, stale). `stale` means the stored hash should be replaced by a
    fresh one made from this password - it was made with an older algorithm
    or older settings."""
    if not isinstance(stored, str) or not stored:
        stored = dummy_hash()
    normal = _normal(password)
    if _matches(stored, normal):
        return True, needs_rehash(stored)
    # hashes made before passwords were normalised
    if normal != password and _matches(stored, password):
        return True, True
    return False, False


# --- what counts as an acceptable password ---------------------------------------
#
# Length is what matters; there are no "must contain a digit and a symbol"
# rules (they push people towards Password1!). What is refused instead is what
# an attacker tries first: the well-known passwords, keyboard runs, a common
# word with a year or a few digits after it, and the account's own name.

_COMMON = frozenset(
    """
    1q2w3e4r5t 1q2w3e4r5t6y q1w2e3r4t5 q1w2e3r4t5y6 1qaz2wsx3edc zaq12wsx3edc 1qazxsw23edc
    qwerty12345 qwerty123456 123456789a a123456789 1234567890a abc1234567 abcd123456 123qweasdzxc
    qwe123asd456 123456qwerty qazwsxedcrfv 1a2b3c4d5e aa12345678 987654321a iloveyou12 trustno1234
    """.split()
)

_WORDS = frozenset(
    """
    password passord passwort passwords qwerty qwertyui qwertyuiop asdf asdfgh asdfghjkl zxcvbnm qazwsx
    admin administrator root toor user guest test testing demo login access secret hemmelig changeme
    default welcome velkommen letmein iloveyou dragon monkey master shadow sunshine princess football
    fotball baseball superman batman starwars whatever computer internet trustno hello hallo heisann
    summer winter spring autumn sommer vinter norge norway oslo bergen trondheim stavanger
    fyr dashboard homeassistant hjemme home server
    """.split()
)

_RUNS = ("01234567890123456789", "abcdefghijklmnopqrstuvwxyz", "qwertyuiopasdfghjklzxcvbnm", "qwertyuiopåasdfghjkløæzxcvbnm")
_EDGE = "0123456789 !\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~"
_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s", "!": "i"})


def _is_common(folded):
    if folded in _COMMON or len(set(folded)) <= 2:
        return True
    if any(folded in run or folded in run[::-1] for run in _RUNS):
        return True
    # "Sommer2025!", "P@ssw0rd123": a common word dressed up with digits and symbols
    core = folded.strip(_EDGE).translate(_LEET)
    half = len(core) // 2
    return core in _WORDS or (len(core) % 2 == 0 and core[:half] == core[half:] and core[:half] in _WORDS)


def password_problem(password, username=""):
    """None for an acceptable password, otherwise the reason as an error code."""
    if not isinstance(password, str) or len(password) < MIN_LENGTH:
        return "password_too_short"
    if len(password) > MAX_LENGTH:
        return "password_too_long"
    folded = _normal(password).casefold()
    name = (username or "").casefold()
    if len(name) >= 3 and name in folded:
        # the username padded out with a few characters, digits or a common word
        rest = folded.replace(name, "")
        if len(rest) < 6 or not rest.strip(_EDGE) or _is_common(rest):
            return "password_too_similar"
    if _is_common(folded):
        return "password_too_common"
    return None
