from biostar.settings.base import *

DEBUG = 0
TEMPLATE_DEBUG = 0

USE_COMPRESSOR = False

SITE_NAME = get_env("SITE_NAME", "Site Name")

with open('/etc/biostar/django-secret') as django_secret:
    SECRET_KEY = django_secret.read().strip()

with open('/etc/biostar/dbpass') as dbpass:
    with open('/etc/biostar/dbhost') as dbhost:
        DATABASES = {
            'default': {
                # To ENGINE 'django.db.backends.XYZ'
                # add 'postgresql_psycopg2', 'mysql', 'sqlite3' or 'oracle'.
                'ENGINE': 'django.db.backends.postgresql_psycopg2',
                'NAME': DATABASE_NAME,
                'USER': 'biostar',
                'PASSWORD': dbpass.read().strip(),
                'HOST': dbhost.read().strip(),
                'PORT': '5432',
            }
        }

with open('/etc/biostar/writer-auth-token') as writer_auth_token:
    WRITER_AUTH_TOKEN = writer_auth_token.read().strip()