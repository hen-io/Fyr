<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="banne.png">
    <img src="assets/banner.png" alt="K93 ANS" height="100%">
  </picture>
</p>

# Fyr - Dashboard and app launcher for yuor selfhosted apps. the perceft home portal!

All-In-One Docker container with a highly configurable web-based app launcher for your selfhosted web apps.

Frontend is built on react & vite and backend is python-based. Shipped in a OCI-Container running Alpine Linux with nginx!

## Integrations

An integration connects Fyr to a service. It can provide

- **data** – named values that every data widget (sensor, gauge, chip, graph, value list) can show, and
- **its own widget types** – e.g. a download queue or a release calendar,
- optionally **actions** a widget may trigger (e.g. "pause all").

| Integration    | Data (metrics)                                                              | Widgets                                  |
| -------------- | --------------------------------------------------------------------------- | ---------------------------------------- |
| Home Assistant | any entity / attribute, history, calendars, services                        | buttons, calendar, weather (built in)    |
| MQTT           | any topic (JSON paths supported), history since Fyr started listening, publish | buttons (built in)                     |
| Sonarr         | queue, missing, series, episodes, upcoming, health issues, disk space       | release calendar, download queue         |
| Radarr         | queue, missing, movies, downloaded, upcoming, health issues, disk space     | release calendar, download queue         |
| qBittorrent    | download / upload speed, torrent counts per state, ratio, free space (login optional) | torrent list with pause / resume all |
| Backrest       | backups ok / warning / failed (30 days), plans, repos, snapshots, protected size, time to next backup | plan overview, recent operations |
| System (the host) | processor, load, memory, disk use and free space per path, uptime (no setup) | system resources (bars or rings)        |
| Jellyfin / Emby | movies, series, episodes, songs, sessions, playing, transcoding             | now playing                              |
| Jellyseerr / Overseerr | pending, approved, processing, available, declined, totals           | –                                        |
| Immich         | photos, videos, library size, disk use                                      | –                                        |
| Prowlarr       | indexers, queries, grabs, failed queries, health issues                     | –                                        |
| Frigate        | cameras, cameras online, detection fps, inference time, recording disk      | latest detections                        |
| AdGuard Home   | DNS queries, blocked, share blocked, response time, protection on/off       | –                                        |
| Uptime Kuma    | monitors up / down / pending / in maintenance (API key, `/metrics`)         | monitor list                             |
| Proxmox VE     | nodes, VMs and containers running, cluster processor and memory (API token) | nodes / VMs / containers list            |

Integrations are switched on in **Admin panel → Integrasjoner** (a catalogue: the ones in use first, search and group filter). The "new widget" picker also offers ready-made overviews (AdGuard, Jellyfin, Immich, media requests, Prowlarr, Proxmox, Frigate) built from these numbers.

Adding an integration is one `DataSource` subclass listed in `backend/app/datasources/registry.py` (`RestSource` covers the usual "URL + API key" service); the admin form, the source pickers and the widget editor derive from it.

## Widgets

Widgets that need no integration: clock (digital / analogue, any time zone), text (light formatting, live greeting), countdown, search, bookmarks, RSS / Atom news, embedded page, picture, app status and the app launcher. With Home Assistant: weather (with forecast) and calendar. Every widget scales with its cell and has its own text size, font, background, accent colour and click-through address.

A widget type is one component in `frontend/src/widgets/types/` plus one definition (its fields, defaults and size) in `frontend/src/widgets/definitions/`.

## Security notes

- Accounts are created by an admin only; passwords are hashed (scrypt), sessions live on the server and end everywhere when the password changes.
- Writes must come from the dashboard's own origin; login attempts are limited per address and per account. Behind a reverse proxy, set `TRUSTED_PROXIES` to the number of proxies in front of Fyr so the limiter sees the real client address.
- The status check only requests the exact addresses that are on the dashboard; feeds and integrations only fetch what an admin saved.
- Uploaded icons and avatars are decoded and re-encoded; the page ships with a strict Content-Security-Policy.

## Development

```
cd backend  && pip install -r requirements.txt -r requirements-dev.txt && python -m pytest
cd frontend && npm install && npx eslint src && npm run i18n:check && npm run build
```

`backend/tests/mock_services.py` is a stand-in for every supported service (`python tests/mock_services.py 9500`, then point an integration at `http://127.0.0.1:9500/<name>`); `backend/tests/security_probe.py` runs the security checks against a running instance. Container logs are also shown in **Admin panel → Logger**.

