import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'urbix.settings')

app = Celery('urbix')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

# Optional but recommended
if __name__ == '__main__':
    app.start()