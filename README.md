# Fyr

A self-hosted app launcher/dashboard: a React frontend and a Flask backend
(Home Assistant/MQTT data, auth, widgets), built together into one Docker
image (nginx + gunicorn, run side by side via supervisord).

## Layout on a server

The image is fully self-contained - frontend build and backend code are
both already inside it. `docker-compose.yml` is the only file a server
actually needs; there's no `build:` fallback, so it never tries to fetch or
build anything from source. You don't need to `git clone` this repo at all
to run it - copying just that one file is enough.

Secrets and runtime data are never part of this repo. They live in a
**sibling** folder, `Fyr-data/`, next to wherever `docker-compose.yml` sits:

```
your-folder/
  Fyr/                  <- can be just this one file, nothing else required
    docker-compose.yml
  Fyr-data/             <- you create this yourself
    .env                <- see the env vars listed below, fill in real values
    config/             <- apps.config, ui.conf, icons/ (what you hand-edit)
    data/               <- users.json, prefs.json, sessions (the app manages this itself)
```

`.env` needs at minimum: `HA_URL`, `HA_TOKEN`, `SESSION_SECRET` (generate
with `python3 -c "import secrets; print(secrets.token_hex(32))"`),
`STATUS_ALLOWED_HOSTS`, `CONFIG_DIR=/config`, `DATA_DIR=/data`. See
`Source/backend/.env.example` in this repo for the full list with comments,
if you do have the source checked out.

## First-time setup

```bash
mkdir -p Fyr Fyr-data/config Fyr-data/data
# copy docker-compose.yml into Fyr/, and write Fyr-data/.env (see above)

# authenticate once - the image is private
docker login ghcr.io -u hen-io --password-stdin

cd Fyr
docker compose pull
docker compose up -d

# create the first account (no self-register endpoint, by design)
docker exec -it fyr python3 manage.py adduser
```

Point your reverse proxy at this container's port `8080` (it uses
`network_mode: host`, so that's `http://127.0.0.1:8080` on this same
machine) for whichever domain should serve it.

## Updating to a new release

```bash
cd Fyr
docker compose pull
docker compose up -d
```

No `git pull` needed - `docker-compose.yml` itself only changes on rare
occasions (a new env var, a new volume); the image is what actually
changes on every release, and `pull` handles that.

The image tag is `latest` (always current) or `v<version>` (matching
`Source/launcher/package.json`'s version, same number shown in the app's
About page) if you want to pin a specific release.
