"""Logging in, sessions, accounts."""

from conftest import ADMIN, VISITOR


def test_me_requires_login(anon):
    response = anon.get("/api/me")
    assert response.status_code == 401
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_login_and_logout(anon):
    assert anon.post("/api/login", json={"username": ADMIN[0], "password": "wrong"}).status_code == 401
    assert anon.post("/api/login", json={"username": ADMIN[0], "password": ADMIN[1]}).status_code == 200
    assert anon.get("/api/me").get_json()["role"] == "admin"
    assert anon.post("/api/logout").status_code == 200
    assert anon.get("/api/me").status_code == 401


def test_session_cookie_flags(app):
    response = app.test_client().post("/api/login", json={"username": VISITOR[0], "password": VISITOR[1]})
    cookie = response.headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie


def test_unknown_user_and_wrong_password_look_identical(anon):
    unknown = anon.post("/api/login", json={"username": "nobody", "password": "x"})
    wrong = anon.post("/api/login", json={"username": ADMIN[0], "password": "x"})
    assert (unknown.status_code, unknown.get_json()) == (wrong.status_code, wrong.get_json())


def test_planted_session_id_is_not_adopted(app):
    planted = "attacker-chosen-session-id-0123456789"
    victim = app.test_client()
    victim.set_cookie("session", planted)
    assert victim.post("/api/login", json={"username": VISITOR[0], "password": VISITOR[1]}).status_code == 200
    attacker = app.test_client()
    attacker.set_cookie("session", planted)
    assert attacker.get("/api/me").status_code == 401


# --- throttling -------------------------------------------------------------


def _fail(client, username, address, times):
    for _ in range(times):
        client.post("/api/login", json={"username": username, "password": "nope"}, headers={"X-Forwarded-For": address})


def test_repeated_failures_lock_that_address_out_of_the_account(app):
    client = app.test_client()
    _fail(client, VISITOR[0], "203.0.113.5", 6)
    good = {"username": VISITOR[0], "password": VISITOR[1]}
    assert client.post("/api/login", json=good, headers={"X-Forwarded-For": "203.0.113.5"}).status_code == 401
    # ...but the account's owner, coming from elsewhere, is not locked out by a stranger
    assert app.test_client().post("/api/login", json=good, headers={"X-Forwarded-For": "198.51.100.7"}).status_code == 200


def test_one_address_trying_many_usernames_is_shut_out(app):
    client = app.test_client()
    for i in range(25):
        client.post("/api/login", json={"username": f"guess{i}", "password": "x"}, headers={"X-Forwarded-For": "203.0.113.9"})
    good = {"username": VISITOR[0], "password": VISITOR[1]}
    assert client.post("/api/login", json=good, headers={"X-Forwarded-For": "203.0.113.9"}).status_code == 401


def test_forwarded_for_from_the_client_is_not_trusted_beyond_the_proxy(app):
    """Only the last hop (what our own nginx appended) counts: a client cannot
    dodge the limit by inventing a different left-most address each time."""
    client = app.test_client()
    for i in range(6):
        client.post("/api/login", json={"username": VISITOR[0], "password": "nope"}, headers={"X-Forwarded-For": f"10.9.9.{i}, 203.0.113.77"})
    good = {"username": VISITOR[0], "password": VISITOR[1]}
    assert client.post("/api/login", json=good, headers={"X-Forwarded-For": "10.1.1.1, 203.0.113.77"}).status_code == 401


# --- passwords and sessions ---------------------------------------------------


def test_changing_password_ends_other_sessions(login):
    here, elsewhere = login(VISITOR), login(VISITOR)
    assert here.put("/api/me/password", json={"current_password": "wrong", "new_password": "newpassword1"}).status_code == 401
    assert here.put("/api/me/password", json={"current_password": VISITOR[1], "new_password": "short"}).status_code == 400
    assert here.put("/api/me/password", json={"current_password": VISITOR[1], "new_password": "newpassword1"}).status_code == 200
    assert here.get("/api/me").status_code == 200
    assert elsewhere.get("/api/me").status_code == 401
    assert here.put("/api/me/password", json={"current_password": "newpassword1", "new_password": VISITOR[1]}).status_code == 200


def test_sign_out_everywhere_else(login):
    here, elsewhere = login(VISITOR), login(VISITOR)
    assert here.delete("/api/me/sessions").status_code == 200
    assert here.get("/api/me").status_code == 200
    assert elsewhere.get("/api/me").status_code == 401


def test_admin_resets_a_password(admin, login, app):
    assert admin.put(f"/api/users/{VISITOR[0]}/password", json={"password": "short"}).status_code == 400
    assert admin.put("/api/users/nobody/password", json={"password": "longenough1"}).status_code == 404
    old_session = login(VISITOR)
    assert admin.put(f"/api/users/{VISITOR[0]}/password", json={"password": "resetpass123"}).status_code == 200
    assert old_session.get("/api/me").status_code == 401
    assert login((VISITOR[0], "resetpass123")).get("/api/me").status_code == 200
    assert admin.put(f"/api/users/{VISITOR[0]}/password", json={"password": VISITOR[1]}).status_code == 200


def test_visitor_cannot_reset_passwords(visitor):
    assert visitor.put(f"/api/users/{ADMIN[0]}/password", json={"password": "hijacked-pass1"}).status_code == 403


# --- user management ----------------------------------------------------------


def test_user_management_rules(admin, visitor):
    assert visitor.get("/api/users").status_code == 403
    assert admin.post("/api/users", json={"username": "../x", "password": "longenough1"}).status_code == 400
    assert admin.post("/api/users", json={"username": "ok", "password": "short"}).status_code == 400
    assert admin.post("/api/users", json={"username": ADMIN[0], "password": "longenough1"}).status_code == 409
    assert admin.delete(f"/api/users/{ADMIN[0]}").status_code == 400  # not yourself
    assert admin.put(f"/api/users/{ADMIN[0]}/role", json={"role": "visitor"}).status_code == 400  # not the last admin


def test_deleted_account_loses_access_and_leaves_nothing_behind(admin, login, app):
    assert admin.post("/api/users", json={"username": "temp1", "password": "temporary123", "role": "admin"}).status_code == 201
    temp = login(("temp1", "temporary123"))
    assert temp.put("/api/me/prefs", json={"palette": "nordic"}).status_code == 200
    assert temp.get("/api/users").status_code == 200
    assert admin.delete("/api/users/temp1").status_code == 200
    assert temp.get("/api/users").status_code == 401
    from app.prefs import load_all_prefs

    assert "temp1" not in load_all_prefs(app.config)


def test_prefs_roundtrip_and_size_cap(visitor, admin):
    assert visitor.put("/api/me/prefs", json={"palette": "x"}).status_code == 200
    assert visitor.get("/api/me/prefs").get_json() == {"palette": "x"}
    assert visitor.put("/api/me/prefs", json={"a": "x" * 70000}).status_code == 400
    assert admin.post("/api/defaults/reset-user-prefs").status_code == 200
    assert visitor.get("/api/me/prefs").get_json() == {}
