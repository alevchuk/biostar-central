from .base import *

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = '2%ufmqb35@r2c&ovp@q0sc#iwfisr9y3(c3n_2-zyaii7dhkc#'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

FIXTURE_DIRS = []
SITE_ID = 1  # Local Dev Site Name http://www.lvh.me

ALLOWED_HOSTS = ["127.0.0.1", "localhost"]  # https://docs.djangoproject.com/en/2.1/ref/settings/#allowed-hosts


# Database
# https://docs.djangoproject.com/en/2.1/ref/settings/#databases
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': os.path.join(BASE_DIR, 'live', 'db.sqlite3'),
    }
}

# No authentication requied, all API calls are allowed
REST_FRAMEWORK = {
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.AllowAny',
    ],
}

# ln-central specific config
MOCK_LN_CLIENT = True

AWARD_TIMEDELTA = timedelta(minutes=1)
