#!/bin/sh
set -e

NAME=$(python3 -c "import json; print(json.load(open('/app/package.json'))['name'])")
VERSION=$(python3 -c "import json; print(json.load(open('/app/package.json'))['version'])")
AUTHOR=$(python3 -c "import json; print(json.load(open('/app/package.json'))['author'])")
HOMEPAGE=$(python3 -c "import json; print(json.load(open('/app/package.json'))['homepage'])")

cat <<BANNER
==================================================
  ${NAME} v${VERSION}
  by ${AUTHOR}
  ${HOMEPAGE}
==================================================
BANNER

exec supervisord -c /etc/supervisord.conf
