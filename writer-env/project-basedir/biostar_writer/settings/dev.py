from .base import *

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = '2%ufmqb35@r2c&ovp@q0sc#iwfisr9y3(c3n_2-zyaii7dhkc#'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = []

# Database
# https://docs.djangoproject.com/en/2.1/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': os.path.join(BASE_DIR, 'live', 'db.sqlite3'),
    }
}
