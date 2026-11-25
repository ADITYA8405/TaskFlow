# TaskFlow image. The default command serves the app with Gunicorn (production).
# compose.yaml overrides the command with runserver for local development.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Copy requirements first so dependency layers are reused when only code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Collect static files into the image for WhiteNoise to serve. Settings refuse to
# load without a secret key, so a placeholder is used for this build step only; it
# is not stored in the image. No database is needed.
RUN DJANGO_SECRET_KEY=collectstatic-build-only python manage.py collectstatic --noinput

# Migrations are not run here; apply them as a separate, deliberate step.
# Worker processes: set WEB_CONCURRENCY (Gunicorn reads it; default 1).
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--access-logfile", "-"]
