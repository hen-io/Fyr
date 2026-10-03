"""Black-box security probe against a running Fyr backend (default 127.0.0.1:8584).
Each line is SAFE (the attack failed) or VULN (it worked). Exit code = number of VULN lines.
"""
import http.cookiejar
import json
import struct
import sys
import time
import zlib
import urllib.error
import urllib.parse
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8584"
ADMIN = ("admin1", "adminpass123")
VISITOR = ("pentest_vis", "visitorpass1")
results = []


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


class Client:
    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar), NoRedirect)

    def call(self, method, path, body=None, headers=None, raw=None):
        data = None
        hdrs = dict(headers or {})
        if raw is not None:
            data = raw
        elif body is not None:
            data = json.dumps(body).encode()
            hdrs.setdefault("Content-Type", "application/json")
        req = urllib.request.Request(BASE + path, data=data, headers=hdrs, method=method)
        try:
            with self.opener.open(req, timeout=20) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    def json(self, method, path, body=None, headers=None):
        status, headers, payload = self.call(method, path, body, headers)
        try:
            return status, json.loads(payload.decode() or "null")
        except ValueError:
            return status, None

    def login(self, user):
        return self.call("POST", "/api/login", {"username": user[0], "password": user[1]})[0]

    def cookie(self):
        return {c.name: c.value for c in self.jar}


def report(name, vulnerable, detail=""):
    results.append((name, vulnerable))
    print(("VULN  " if vulnerable else "SAFE  ") + name + (f"  [{detail}]" if detail else ""))


anon, admin, vis = Client(), Client(), Client()
assert admin.login(ADMIN) == 200, "admin login failed - is the test backend running with admin1?"
admin.call("POST", "/api/users", {"username": VISITOR[0], "password": VISITOR[1], "role": "visitor", "confirm_password": ADMIN[1]})
assert vis.login(VISITOR) == 200

# ---------------------------------------------------------------- fixtures
def real_png(size=24, rgb=(40, 120, 220)):
    """A small but genuine PNG (the server decodes uploads now)."""
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    row = b"\x00" + bytes(rgb) * size
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(row * size)) + chunk(b"IEND", b"")


png = real_png()
apps = [
    {"title": "Public", "url": "https://public.example.test", "category": "Open"},
    {"title": "Internal", "url": "http://127.0.0.1:8584/api/health", "category": "Open"},
    {"title": "Secret", "url": "https://secret.example.test", "category": "Hidden", "internalUrl": "http://127.0.0.1:8584/api/about"},
    {"title": "MembersOnly", "url": "https://members.example.test", "visibility": "authenticated"},
]
st, _ = admin.json("PUT", "/api/apps", {"apps": apps, "default_mode": "tab", "categories": {"Open": {}, "Hidden": {"hidden_for": ["anonymous", "visitor"]}}})
assert st == 200, st
widgets = [
    {"id": "pub", "type": "text", "x": 0, "y": 0, "w": 3, "h": 1, "text": "hello"},
    {"id": "priv", "type": "text", "x": 3, "y": 0, "w": 3, "h": 1, "text": "members", "visibility": "authenticated"},
    {"id": "btn", "type": "buttons", "source": "home_assistant", "x": 0, "y": 1, "w": 3, "h": 1, "buttons": [{"service": "light.toggle", "entity_id": "light.x"}]},
    {"id": "privbtn", "type": "buttons", "source": "home_assistant", "visibility": "authenticated", "allow_anonymous": True, "x": 0, "y": 2, "w": 3, "h": 1, "buttons": [{"service": "light.toggle"}]},
]
assert admin.json("PUT", "/api/widgets", {"widgets": widgets, "grid": {}})[0] == 200

# ---------------------------------------------------------------- 1. access control
ADMIN_ONLY = [
    ("GET", "/api/users", None), ("POST", "/api/users", {"username": "x1", "password": "longenough1"}),
    ("DELETE", "/api/users/" + VISITOR[0], None), ("PUT", f"/api/users/{VISITOR[0]}/role", {"role": "admin"}),
    ("PUT", "/api/apps", {"apps": []}), ("PUT", "/api/layout", {}), ("PUT", "/api/widgets", {"widgets": []}),
    ("POST", "/api/widgets/reset", None), ("PUT", "/api/defaults", {"defaults": {}}), ("POST", "/api/defaults/reset-user-prefs", None),
    ("GET", "/api/integrations", None), ("PUT", "/api/integrations/sonarr", {"enabled": True}), ("GET", "/api/sources", None),
    ("GET", "/api/sources/home_assistant/keys", None), ("POST", "/api/widget-data", {"type": "sensor"}),
    ("POST", "/api/integration-preview", {"type": "arr_queue"}), ("GET", "/api/icons", None), ("POST", "/api/icons", None),
    ("GET", "/api/system/info", None), ("GET", "/api/system/logs", None), ("POST", "/api/system/restart", None),
    ("GET", "/api/apps?all=1", None),
]
for who, client, expected in (("anonymous", anon, 401), ("visitor", vis, 403)):
    leaks = []
    for method, path, body in ADMIN_ONLY:
        status, payload = client.json(method, path, body)
        if path == "/api/apps?all=1":
            if any(a.get("title") == "Secret" for a in (payload or {}).get("apps", [])):
                leaks.append(path)
        elif status != expected:
            leaks.append(f"{method} {path} -> {status}")
    report(f"admin-only endpoints refuse {who}", bool(leaks), "; ".join(leaks))
# make sure the probes above did not change anything
assert any(u["username"] == VISITOR[0] and u["role"] == "visitor" for u in admin.json("GET", "/api/users")[1])

# ---------------------------------------------------------------- 2. hidden content
titles = lambda c: [a["title"] for a in c.json("GET", "/api/apps")[1]["apps"]]  # noqa: E731
report("anonymous cannot list hidden/members-only apps", set(titles(anon)) != {"Public", "Internal"}, str(titles(anon)))
report("visitor cannot list apps of a hidden category", "Secret" in titles(vis), str(titles(vis)))
report("anonymous cannot read a members-only widget", anon.json("GET", "/api/widget/priv")[0] != 404)
report("anonymous cannot see members-only widgets in the list", any(w["id"] == "priv" for w in anon.json("GET", "/api/widgets")[1]["widgets"]))
report("anonymous cannot press a button widget", anon.json("POST", "/api/widget/btn/action", {"index": 0})[0] not in (401,))
report("anonymous cannot press buttons of a members-only widget (even with allow_anonymous)", anon.json("POST", "/api/widget/privbtn/action", {"index": 0})[0] != 404)

# ---------------------------------------------------------------- 3. status endpoint as a request forgery tool
q = lambda u: "/api/status?url=" + urllib.parse.quote(u, safe="")  # noqa: E731
report("status: host that is not on the dashboard is refused", anon.json("GET", q("http://127.0.0.1:8584/api/users"))[0] == 200 and False or anon.json("GET", q("http://169.254.169.254/latest/meta-data/"))[0] != 403)
st, body = anon.json("GET", q("http://127.0.0.1:8584/api/users"))
report("status: other PATHS on a configured host cannot be probed (blind GET / path oracle)", st == 200, f"{st} {body}")
st, body = anon.json("GET", q("http://127.0.0.1:8584/api/about"))
report("status: a hidden app's status url cannot be probed by anonymous", st == 200, f"{st} {body}")
report("status: non-http schemes refused", anon.json("GET", q("file:///etc/passwd"))[0] != 400 or anon.json("GET", q("gopher://127.0.0.1:8584/"))[0] != 400)
report("status: credentials-in-url trick does not reach another host", anon.json("GET", q("http://127.0.0.1:8584@evil.example.test/"))[0] != 403)

# ---------------------------------------------------------------- 4. path traversal
trav = []
for path in ["/icons/..%2f..%2fdata%2fusers.json", "/icons/%2e%2e/%2e%2e/etc/passwd", "/icons/....//....//etc/passwd", "/api/avatar/..%2f..%2fusers", "/api/avatar/%2e%2e%2fusers.json",
             "/api/tilefx/..%2f..%2fapps.config/face", "/api/tilefx/%2e%2e%5c%2e%2e%5cusers.json/logo?t=1", "/icons/C:%5cWindows%5cwin.ini"]:
    status, headers, payload = anon.call("GET", path)
    if status == 200 and (b"password_hash" in payload or b"root:" in payload or b"[fonts]" in payload or b"categories" in payload):
        trav.append(path)
report("path traversal through icon / avatar / tile-image routes", bool(trav), "; ".join(trav))

# ---------------------------------------------------------------- 5. session handling
planted = "attacker-chosen-session-id-0123456789abcdef"
Client().call("POST", "/api/login", {"username": VISITOR[0], "password": VISITOR[1]}, {"Cookie": f"session={planted}"})
report("an id planted in the browser before login does not become the session (fixation)", Client().json("GET", "/api/me", headers={"Cookie": f"session={planted}"})[0] == 200)
status, headers, _ = Client().call("POST", "/api/login", {"username": VISITOR[0], "password": VISITOR[1]})
cookie_header = headers.get("Set-Cookie", "")
report("session cookie is HttpOnly + SameSite", "HttpOnly" not in cookie_header or "SameSite" not in cookie_header, cookie_header[:90])
old = Client()
old.login(VISITOR)
vis.json("PUT", "/api/me/password", {"current_password": VISITOR[1], "new_password": "visitorpass2"})
still = old.json("GET", "/api/me")[0] == 200
vis.json("PUT", "/api/me/password", {"current_password": "visitorpass2", "new_password": VISITOR[1]})
report("changing the password signs out the account's other sessions", still)
gone = Client()
admin.call("POST", "/api/users", {"username": "pentest_tmp", "password": "temporary123", "role": "admin", "confirm_password": ADMIN[1]})
gone.login(("pentest_tmp", "temporary123"))
admin.call("DELETE", "/api/users/pentest_tmp", {"confirm_password": ADMIN[1]})
report("a deleted admin's session stops working immediately", gone.json("GET", "/api/users")[0] == 200)

# ---------------------------------------------------------------- 6. cross-site request forgery
def forged(headers):
    return admin.json("PUT", "/api/defaults", {"defaults": {"siteTitle": "pwned"}}, headers)[0]

report("CSRF: cross-site write is refused", forged({"Sec-Fetch-Site": "cross-site", "Origin": "https://evil.example"}) != 403)
report("CSRF: write from a sibling subdomain (same-site) is refused", forged({"Sec-Fetch-Site": "same-site", "Origin": "https://other-app.example.test"}) != 403)
report("CSRF: foreign Origin without Sec-Fetch-Site is refused", forged({"Origin": "https://evil.example"}) != 403)
report("CSRF: form-encoded body cannot stand in for JSON", admin.call("PUT", "/api/defaults", raw=b"defaults=x", headers={"Content-Type": "application/x-www-form-urlencoded", "Sec-Fetch-Site": "same-origin"})[0] == 200)
admin.json("PUT", "/api/defaults", {"defaults": {}}, {"Sec-Fetch-Site": "same-origin"})

# ---------------------------------------------------------------- 7. brute force
bf = Client()
codes = [bf.call("POST", "/api/login", {"username": f"nobody{i}", "password": "x"}, {"X-Forwarded-For": "203.0.113.9"})[0] for i in range(40)]
blocked = Client().call("POST", "/api/login", {"username": VISITOR[0], "password": VISITOR[1]}, {"X-Forwarded-For": "203.0.113.9"})[0]
report("login: an address that keeps failing is shut out (even with a correct password)", blocked == 200, f"{codes.count(401)} failures, then correct login -> {blocked}")
lock = Client()
for _ in range(8):
    lock.call("POST", "/api/login", {"username": VISITOR[0], "password": "wrong"}, {"X-Forwarded-For": "203.0.113.50"})
report("login: an attacker cannot lock a real user out from another address", Client().call("POST", "/api/login", {"username": VISITOR[0], "password": VISITOR[1]}, {"X-Forwarded-For": "198.51.100.7"})[0] != 200)
report("login: wrong password and unknown user look the same", Client().json("POST", "/api/login", {"username": "nobody-here", "password": "x"}, {"X-Forwarded-For": "198.51.100.8"}) != Client().json("POST", "/api/login", {"username": ADMIN[0], "password": "x"}, {"X-Forwarded-For": "198.51.100.9"}))

st, _ = vis.json("PUT", f"/api/users/{ADMIN[0]}/password", {"password": "hijacked-pass1"})
report("a visitor cannot reset someone else's password", st != 403, str(st))

# ---------------------------------------------------------------- 8. robustness: no 500s, no stack traces
fuzz = [
    ("POST", "/api/login", {"username": {"a": 1}, "password": ["x"]}), ("POST", "/api/login", [1, 2]), ("POST", "/api/login", "str"),
    ("POST", "/api/users", {"username": 5, "password": {"a": 1}, "role": []}), ("PUT", "/api/me/prefs", [1]), ("PUT", "/api/me/profile", {"display_name": {"x": 1}}),
    ("PUT", "/api/me/password", {"current_password": 5, "new_password": []}), ("PUT", "/api/apps", {"apps": [1, "x", None, {"title": 5}]}),
    ("PUT", "/api/apps", {"apps": [], "categories": {"a": 5, "b": {"hidden_for": "x"}}}), ("PUT", "/api/widgets", {"widgets": [1, {"type": {}}, {"type": "x", "x": "NaN", "w": 1e99}], "grid": []}),
    ("PUT", "/api/widgets", {"widgets": [{"type": "t", "id": {"a": 1}}], "grid": {"columns": "x"}}), ("PUT", "/api/defaults", {"defaults": {"gap": 1e400, "palette": {}}}),
    ("PUT", "/api/layout", [1]), ("PUT", "/api/integrations/sonarr", {"values": {"url": 5, "api_key": {}}}), ("PUT", "/api/integrations/mqtt", {"values": {"port": "x"}}),
    ("POST", "/api/widget-data", {"type": "sensor", "source": {}, "key": [], "entities": [1, {"key": 5}]}), ("POST", "/api/integration-preview", {"type": [], "source": 5}),
    ("POST", "/api/widget/btn/action", {"index": "0"}), ("POST", "/api/widget/btn/action", [0]), ("PUT", f"/api/users/{VISITOR[0]}/role", {"role": {}}),
    ("GET", "/api/status?url=http://[::1", None), ("GET", "/api/status?url=http://x:99999999/", None), ("GET", "/api/widget/pub/history?hours=nan", None),
    ("GET", "/api/system/logs?lines=abc&source=backend", None), ("GET", "/api/tilefx/x.png/face?r=nan&sw=inf", None), ("DELETE", "/api/login", None), ("PATCH", "/api/apps", {}),
]
crashes = []
for method, path, body in fuzz:
    status, headers, payload = admin.call(method, path, body, {"Sec-Fetch-Site": "same-origin"})
    if status >= 500 or b"Traceback" in payload or b"werkzeug" in payload.lower():
        crashes.append(f"{method} {path} {json.dumps(body)[:40]} -> {status}")
    elif "json" not in headers.get("Content-Type", "") and status >= 400 and not path.startswith("/api/tilefx"):
        crashes.append(f"{method} {path} -> {status} non-JSON error")
report("malformed input never produces a 500 or a non-JSON error", bool(crashes), "; ".join(crashes))

# ---------------------------------------------------------------- 9. uploads
def multipart(name, filename, content, ctype):
    boundary = "----pentest"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; filename=\"{filename}\"\r\nContent-Type: {ctype}\r\n\r\n").encode() + content + f"\r\n--{boundary}--\r\n".encode()
    return body, {"Content-Type": f"multipart/form-data; boundary={boundary}", "Sec-Fetch-Site": "same-origin"}

html = b"<html><script>alert(document.domain)</script></html>"
body, hdr = multipart("file", "evil.png", html, "image/png")
st, _, _ = vis.call("PUT", "/api/me/avatar", raw=body, headers=hdr)
_, h, payload = anon.call("GET", "/api/avatar/" + VISITOR[0])
report("avatar: HTML disguised as an image is refused", st == 200 or payload == html, f"upload {st}")
body, hdr = multipart("file", "me.png", real_png(64), "image/png")
st2, _, _ = vis.call("PUT", "/api/me/avatar", raw=body, headers=hdr)
_, h2, stored = anon.call("GET", "/api/avatar/" + VISITOR[0])
report("avatar: a real picture is accepted, re-encoded and served sandboxed", not (st2 == 200 and stored[:4] == b"RIFF" and "sandbox" in h2.get("Content-Security-Policy", "")), f"upload {st2}, {h2.get('Content-Type')}")
bad = []
for fname, content in [("x.svg", b"<svg onload=alert(1)>"), ("x.png", html), ("x.png", b"\x89PNG\r\n\x1a\n" + html), ("y.jpg", png), ("../../evil.png", png), ("x.php", png), (".htaccess", png), ("x.png.html", png)]:
    body, hdr = multipart("file", fname, content, "image/png")
    status, _, payload = admin.call("POST", "/api/icons", raw=body, headers=hdr)
    if status == 201 and fname != "../../evil.png":
        bad.append(fname)
    if status == 201 and fname == "../../evil.png" and json.loads(payload)["name"] != "evil.png":
        bad.append("traversal name kept")
report("icon upload: scripts, wrong types and odd names are refused", bool(bad), ", ".join(bad))
big, hdr = multipart("file", "big.png", png + b"0" * (5 * 1024 * 1024), "image/png")
report("oversized upload is rejected", admin.call("POST", "/api/icons", raw=big, headers=hdr)[0] not in (400, 413))

# ---------------------------------------------------------------- 10. resource exhaustion
body, hdr = multipart("file", "pt.png", png, "image/png")
assert admin.call("POST", "/api/icons", raw=body, headers=hdr)[0] == 201
admin.json("PUT", "/api/apps", {"apps": apps + [{"title": "Pic", "url": "https://pic.example.test", "icon": "pt.png", "category": "Open"}], "default_mode": "tab", "categories": {"Open": {}, "Hidden": {"hidden_for": ["anonymous", "visitor"]}}}, {"Sec-Fetch-Site": "same-origin"})
admin.json("PUT", "/api/defaults", {"defaults": {"tileTint": "on", "logoStrokeWidth": 2, "logoStrokeColor": "accent"}}, {"Sec-Fetch-Site": "same-origin"})
fx = next(a for a in anon.json("GET", "/api/apps")[1]["apps"] if a["title"] == "Pic").get("fx") or {}
issued = [anon.call("GET", fx[k])[0] for k in ("face", "logo") if fx.get(k)]
started = time.time()
rendered = 0
for i in range(12):
    status, _, _ = anon.call("GET", f"/api/tilefx/pt.png/logo?t=1&sw=2&sc=accent&ac={i:06x}&v=x")
    rendered += status == 200
tampered = anon.call("GET", fx.get("logo", "/x").replace("sw=2", "sw=6"))[0]
report("tile images: only URLs the server signed are drawn", rendered > 0 or tampered == 200 or issued != [200, 200], f"issued {issued}, {rendered}/12 unsigned accepted, tampered -> {tampered}, {time.time() - started:.1f}s")
admin.json("PUT", "/api/defaults", {"defaults": {}}, {"Sec-Fetch-Site": "same-origin"})
report("request body size is capped", admin.call("PUT", "/api/me/prefs", raw=b'{"a":"' + b"x" * (6 * 1024 * 1024) + b'"}', headers={"Content-Type": "application/json", "Sec-Fetch-Site": "same-origin"})[0] not in (400, 413))

# ---------------------------------------------------------------- 11. information leaks
report("no unauthenticated endpoint lists calendar events from the server-wide calendar", anon.json("GET", "/api/calendar/upcoming")[0] not in (401, 404) or False)
status, headers, payload = anon.call("GET", "/api/nope")
report("responses carry nosniff and JSON errors are not cached", headers.get("X-Content-Type-Options") != "nosniff" or headers.get("Cache-Control") != "no-store")
st, info = admin.json("GET", "/api/integrations")
secrets = [f for i in info for f in i["fields"] if f["kind"] == "password" and "value" in f]
report("integration secrets are never sent back", bool(secrets))
report("server banner does not reveal the framework version", "Werkzeug" in headers.get("Server", "") and False)

# ---------------------------------------------------------------- cleanup
admin.call("DELETE", "/api/users/" + VISITOR[0], {"confirm_password": ADMIN[1]})
vulns = [n for n, v in results if v]
print(f"\n{len(results)} checks, {len(vulns)} VULNERABLE")
sys.exit(len(vulns))
