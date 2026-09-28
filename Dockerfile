# Fyr - Dashboard with launcher for your selfhosted apps!

FROM node:22-alpine AS frontend-builder
WORKDIR /frontend
COPY launcher/package.json launcher/package-lock.json ./
RUN npm ci
COPY launcher/ ./
RUN npm run build

FROM python:3.13-alpine

RUN apk add --no-cache nginx supervisor

WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app/ ./app/
COPY backend/manage.py backend/wsgi.py ./

COPY --from=frontend-builder /frontend/dist/ /usr/share/nginx/html/

COPY docker/nginx.conf /etc/nginx/http.d/default.conf
COPY docker/supervisord.conf /etc/supervisord.conf

EXPOSE 8080
CMD ["supervisord", "-c", "/etc/supervisord.conf"]
