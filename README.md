<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="banne.png">
    <img src="assets/banner.png" alt="Fyr" height="100%">
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