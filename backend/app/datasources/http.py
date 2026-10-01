import base64
import json
import ssl
import urllib.error
import urllib.parse
import urllib.request

MAX_BODY = 8 * 1024 * 1024


class HttpError(Exception):
    def __init__(self, status, message=""):
        super().__init__(f"HTTP {status} {message}".strip())
        self.status = status


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """An integration URL is admin-configured, but a redirect could still
    bounce a request (carrying an API key header) to another host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _insecure_context():
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


_opener = urllib.request.build_opener(_NoRedirect)
# For services with a self-signed certificate (the integration's "verify TLS"
# switch turned off): the connection is still encrypted, the certificate just
# is not checked.
_opener_insecure = urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=_insecure_context()))
class _HttpOnlyRedirect(urllib.request.HTTPRedirectHandler):
    """Follows a few redirects, but only to http(s) addresses."""

    max_redirections = 4

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.lower().startswith(("http://", "https://")):
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


# For public documents (feeds) that carry no credentials: a few redirects are
# normal there (http -> https, a moved feed).
_opener_following = urllib.request.build_opener(_HttpOnlyRedirect)


def request(url, *, headers=None, data=None, form=None, method=None, timeout=8, verify=True, follow_redirects=False, max_body=MAX_BODY):
    """One HTTP request -> (status, headers, body bytes). Does not follow
    redirects unless asked to, caps the response size, raises HttpError for
    4xx/5xx."""
    body = None
    headers = dict(headers or {})
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")
    elif form is not None:
        body = urllib.parse.urlencode(form).encode("utf-8")
        headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    opener = _opener_following if follow_redirects else _opener if verify else _opener_insecure
    try:
        with opener.open(req, timeout=timeout) as resp:
            payload = resp.read(max_body + 1)
            if len(payload) > max_body:
                raise HttpError(502, "response too large")
            return resp.status, resp.headers, payload
    except urllib.error.HTTPError as err:
        raise HttpError(err.code, err.reason if isinstance(err.reason, str) else "") from None


def get_json(url, **kwargs):
    _status, _headers, payload = request(url, **kwargs)
    return json.loads(payload.decode("utf-8")) if payload else None


def get_text(url, **kwargs):
    _status, _headers, payload = request(url, **kwargs)
    return payload.decode("utf-8", errors="replace")


def join(base, path):
    return base.rstrip("/") + path


def basic_auth(username, password):
    token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def describe_failure(err, auth_message="Feil brukernavn/passord"):
    """A short, user-facing reason for a failed connectivity check."""
    if isinstance(err, HttpError):
        return auth_message if err.status in (401, 403) else str(err)
    return str(getattr(err, "reason", err))[:120]
