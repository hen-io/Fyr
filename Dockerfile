# Fyr - Dashboard with launcher for your selfhosted apps!
#
# The frontend is already built before this ever runs (this repo ships
# frontend/, not the raw React source it was built from - see
# frontend/package.json for the version that was built), so there's no
# Node stage here at all - just the backend and that pre-built static
# output going into the image as-is.

FROM python:3.13-alpine

RUN apk add --no-cache nginx supervisor

WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app/ ./app/
COPY backend/manage.py backend/wsgi.py ./

COPY frontend/ /usr/share/nginx/html/
# A leftover package.json from the frontend build is not something nginx
# should serve. Name, author and versions live in app.meta.json instead.
RUN rm -f /usr/share/nginx/html/package.json
COPY app.meta.json /app/app.meta.json

COPY docker/nginx.conf /etc/nginx/http.d/default.conf
COPY docker/supervisord.conf /etc/supervisord.conf
COPY docker/entrypoint.sh /entrypoint.sh
# Strip any CR left by a Windows checkout - a CRLF shebang makes the container
# fail with "exec /entrypoint.sh: no such file or directory".
RUN sed -i 's/\r$//' /entrypoint.sh && chmod +x /entrypoint.sh

EXPOSE 80
CMD ["/entrypoint.sh"]
