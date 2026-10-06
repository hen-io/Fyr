#!/bin/sh
set -e

# Name, author and versions come from app.meta.json (Source/app.meta.json).
META=/app/app.meta.json
field() { python3 -c "import json,sys; print(json.load(open('$META')).get('$1', ''))"; }

NAME=$(field name)
VERSION=$(field version)
FRONTEND_VERSION=$(field frontend_version)
BACKEND_VERSION=$(field backend_version)
AUTHOR=$(field author)
HOMEPAGE=$(field homepage)

cat <<BANNER
==================================================
  ${NAME} v${VERSION}
  frontend v${FRONTEND_VERSION} / backend v${BACKEND_VERSION}
  by ${AUTHOR}
  ${HOMEPAGE}
==================================================
BANNER

exec supervisord -c /etc/supervisord.conf
