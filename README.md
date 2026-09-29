<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="banne.png">
    <img src="assets/banner.png" alt="K93 ANS" height="100%">
  </picture>
</p>

# Fyr - Dashboard and app launcher for yuor selfhosted apps . the perceft home portal!

## Integrations

An integration connects Fyr to a service. It can provide

- **data** – named values that every data widget (sensor, gauge, chip, graph, value list) can show, and
- **its own widget types** – e.g. a download queue or a release calendar,
- optionally **actions** a widget may trigger (e.g. "pause all").

Switch them on and fill in the connection under **Admin panel → Integrasjoner / Integrations**. Secrets (tokens, passwords, API keys) are write-only: they are stored in `connections.json` in the data volume and never sent back to the browser.

| Integration    | Data (metrics)                                                              | Widgets                                  |
| -------------- | --------------------------------------------------------------------------- | ---------------------------------------- |
| Home Assistant | any entity / attribute, history, calendars, services                        | buttons, calendar, weather (built in)    |
| MQTT           | any topic (JSON paths supported), history since Fyr started listening, publish | buttons (built in)                     |
| Sonarr         | queue, missing, series, episodes, upcoming, health issues, disk space       | release calendar, download queue         |
| Radarr         | queue, missing, movies, downloaded, upcoming, health issues, disk space     | release calendar, download queue         |
| qBittorrent    | download / upload speed, torrent counts per state, ratio, free space        | torrent list with pause / resume all     |

Choose the integration as the widget's *data source*; the key field then suggests the metrics it offers (e.g. `queue`, `download_speed`).

### Adding an integration

1. Write a subclass of `DataSource` (or `MetricSource` for a service that exposes a few named numbers) in `backend/app/datasources/`. `base.py` documents what it can provide: `FIELDS` (the admin form), `get_value` / `list_keys` / `get_history`, `WIDGETS` + `widget_data()`, `ACTIONS` + `run_widget_action()`.
2. List it in `CATALOG` in `datasources/registry.py`. The admin form, the source pickers and the widget editor derive from it.
3. If it ships its own widget type, add the React component in `frontend/src/widgets/` and one entry in `widgets/registry.js` (`integration: ["<id>"]`), and add the type to `INTEGRATION_WIDGETS` in `routes/widgets.py`.

The server decides what a widget may do: a button/action request only carries *which* action, never a URL or payload, and needs a login unless the widget is explicitly marked `allow_anonymous`.

## Language

The UI is available in Norwegian and English. The default language is set in **Admin panel → Standardvalg → Språk / Language**; a user can choose their own in Settings.

The Norwegian text in the source *is* the translation key (`t("Lagre")`), so only English needs a dictionary: `frontend/src/i18n/en.js`. A missing entry falls back to the Norwegian text. `npm run i18n:check` (in `frontend/`) lists strings that still lack an English translation.
