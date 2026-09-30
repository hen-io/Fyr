<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="banne.png">
    <img src="assets/banner.png" alt="K93 ANS" height="100%">
  </picture>
</p>

# Fyr - Dashboard and app launcher for yuor selfhosted apps. the perceft home portal!

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


## Language

The UI is available in Norwegian and English. The default language is set in **Admin panel → Standardvalg → Språk / Language**; a user can choose their own in Settings.

The Norwegian text in the source *is* the translation key (`t("Lagre")`), so only English needs a dictionary: `frontend/src/i18n/en.js`. A missing entry falls back to the Norwegian text. `npm run i18n:check` (in `frontend/`) lists strings that still lack an English translation.
