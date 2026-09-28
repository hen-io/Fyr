# Fyr - Dashboard with launcher for your selfhosted apps!
#
# The frontend is already built before this ever runs (this repo ships
# frontend/, not the raw React source it was built from - see
# launcher/package.json for the version that was built), so there's no
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

COPY docker/nginx.conf /etc/nginx/http.d/default.conf
COPY docker/supervisord.conf /etc/supervisord.conf

EXPOSE 8080
CMD ["supervisord", "-c", "/etc/supervisord.conf"]
