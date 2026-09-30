import json
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


_opener = urllib.request.build_opener(_NoRedirect)


def request(url, *, headers=None, data=None, form=None, method=None, timeout=8):
    """One HTTP request -> (status, headers, body bytes). Never follows
    redirects, caps the response size, raises HttpError for 4xx/5xx."""
    body = None
    headers = dict(headers or {})
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")
    elif form is not None:
        body = urllib.parse.urlencode(form).encode("utf-8")
        headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with _opener.open(req, timeout=timeout) as resp:
            payload = resp.read(MAX_BODY + 1)
            if len(payload) > MAX_BODY:
                raise HttpError(502, "response too large")
            return resp.status, resp.headers, payload
    except urllib.error.HTTPError as err:
        raise HttpError(err.code, err.reason if isinstance(err.reason, str) else "") from None


def get_json(url, **kwargs):
    _status, _headers, payload = request(url, **kwargs)
    return json.loads(payload.decode("utf-8")) if payload else None


def join(base, path):
    return base.rstrip("/") + path
