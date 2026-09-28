# Fyr - one container running both the static frontend (via nginx) and the
# Flask/gunicorn backend, supervised together by supervisord. Built from the
# repo root (not Source/backend or Source/launcher alone) since it needs
# both trees. nginx is the only thing this container exposes - gunicorn
# binds 127.0.0.1 only and is reached exclusively through nginx's /api and
# /icons proxy_pass (see docker/nginx.conf).

# ---- stage 1: build the frontend ----
FROM node:22-alpine AS frontend-builder
WORKDIR /frontend
COPY Source/launcher/package.json Source/launcher/package-lock.json ./
RUN npm ci
COPY Source/launcher/ ./
RUN npm run build

# ---- stage 2: the actual image ----
FROM python:3.13-alpine

RUN apk add --no-cache nginx supervisor

WORKDIR /app
COPY Source/backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY Source/backend/app/ ./app/
COPY Source/backend/manage.py Source/backend/wsgi.py ./

COPY --from=frontend-builder /frontend/dist/ /usr/share/nginx/html/

COPY docker/nginx.conf /etc/nginx/http.d/default.conf
COPY docker/supervisord.conf /etc/supervisord.conf

EXPOSE 8080
CMD ["supervisord", "-c", "/etc/supervisord.conf"]
