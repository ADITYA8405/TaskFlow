import os

from celery import Celery

# Let the worker load Django settings the same way manage.py does.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('config')

# Read every Django setting that starts with CELERY_, e.g. CELERY_BROKER_URL.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Find tasks.py modules in all INSTALLED_APPS.
app.autodiscover_tasks()
