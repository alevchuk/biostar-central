from .base import *

DEBUG = False

# For security check run: biostar.sh writer-prod check --deploy
# 2019-03-25 No CSRF protection because we do not have cookies https://docs.djangoproject.com/en/2.1/ref/csrf/
# 2019-03-25 No SSL for writer
# SECURE_HSTS_SECONDS=3600  # https://docs.djangoproject.com/en/2.1/ref/middleware/#http-strict-transport-security
# SECURE_SSL_REDIRECT=True  # https://docs.djangoproject.com/en/2.1/ref/settings/#secure-ssl-redirect

ALLOWED_HOSTS = ['127.0.0.1']  # https://docs.djangoproject.com/en/2.1/ref/settings/#allowed-hosts

with open('/etc/biostar/django-secret') as django_secret:
    SECRET_KEY = django_secret.read().strip()

with open('/etc/biostar/dbpass') as dbpass:
    with open('/etc/biostar/dbhost') as dbhost:
        DATABASES = {
            'default': {
                # To ENGINE 'django.db.backends.XYZ'
                # add 'postgresql_psycopg2', 'mysql', 'sqlite3' or 'oracle'.
                'ENGINE': 'django.db.backends.postgresql_psycopg2',
                'NAME': 'biostar',  # database name
                'USER': 'biostar',
                'PASSWORD': dbpass.read().strip(),
                'HOST': dbhost.read().strip(),
                'PORT': '5432',
            }
        }