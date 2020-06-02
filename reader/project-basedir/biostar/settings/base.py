# -*- coding: utf8 -*-
#
# Django settings for biostar project.
#
from __future__ import absolute_import

import os
import stat

from .base_common import *

from django.core.exceptions import ImproperlyConfigured
from .logger import LOGGING
import uuid
uuid._uuid_generate_random = None

# Turn off debug mode on deployed servers.
DEBUG = True

# Template debug mode.
TEMPLATE_DEBUG = DEBUG

# Should the django compressor be used.
USE_COMPRESSOR = False

# The start categories. These tags have special meaning internally.
START_CATEGORIES = [
    "Latest", "Open",
]

# These should be the most frequent (or special) tags on the site.
NAVBAR_TAGS = []

# The last categories. These tags have special meaning internally.
END_CATEGORIES = [
    "Meta",
]

# These are the tags that always show up in the tag recommendation dropdown.
POST_TAG_LIST = NAVBAR_TAGS + ["software error"]

# This will form the navbar
CATEGORIES = START_CATEGORIES + NAVBAR_TAGS + END_CATEGORIES

# This will appear as a top banner.
# It should point to a template that will be included.
TOP_BANNER = ""


# TOP_BANNER = "test-banner.html"

def get_env(name, default=None, strict=False, func=None):
    """Get the environment variable or return exception"""

    if strict and name not in os.environ:
        msg = "*** Required environment variable '{}' not set.".format(name)
        raise ImproperlyConfigured(msg)

    value = os.environ.get(name, default)

    if not value:
        msg = "*** Required environment variable '{}' not set and has no default value".format(
            name)
        raise ImproperlyConfigured(msg)

    if func:
        return func(value)
    else:
        return unicode(value, encoding="utf-8")


def abspath(*args):
    """Generates absolute paths"""
    return os.path.abspath(os.path.join(*args))


# Current directory
__THIS_DIR = os.path.split(__file__)[0]
__DEFAULT_HOME = abspath(__THIS_DIR, "..", "..")
__DEFAULT_BIOSTAR_ADMIN_NAME = "Biostar Admin"
__DEFAULT_BIOSTAR_ADMIN_EMAIL = "admin@lvh.me"
__DEFAULT_SECRET_KEY = 'admin@lvh.me'
__DEFAULT_SITE_DOMAIN = 'www.lvh.me'
__DEFAULT_FROM_EMAIL = 'noreply@lvh.me'

# Displays debug comments when the server is run from this IP.
INTERNAL_IPS = ('127.0.0.1',)

# Set location relative to the current file directory.
HOME_DIR = get_env("BIOSTAR_HOME", __DEFAULT_HOME)
LIVE_DIR = abspath(HOME_DIR, 'live')

__DEFAULT_WRITER_HOST = "localhost"
WRITER_HOST = get_env("WRITER_HOST", __DEFAULT_WRITER_HOST)

DATABASE_NAME = get_env("DATABASE_NAME")
STATIC_DIR = abspath(HOME_DIR, 'biostar', 'static')

TEMPLATE_DIRS = (
    abspath(HOME_DIR, 'biostar', 'server', 'templates'),
    abspath(HOME_DIR, 'biostar', 'apps', 'info', 'templates'),

    # Put strings here, like "/home/html/django_templates" or "C:/www/django/templates".
    # Always use forward slashes, even on Windows.
    # Don't forget to use absolute paths, not relative paths.
)

# Absolute path to the directory static files should be collected to.
# Don't put anything in this directory yourself; store your static files
# in apps' "static/" subdirectories and in STATICFILES_DIRS.
# Example: "/var/www/example.com/static/"
EXPORT_DIR = abspath(LIVE_DIR, "export")
STATIC_ROOT = abspath(EXPORT_DIR, "static")

# Absolute filesystem path to the directory that will hold user-uploaded files.
MEDIA_ROOT = abspath(EXPORT_DIR, "media")


# Default search index location.
WHOOSH_INDEX = abspath(LIVE_DIR, "whoosh_index")

# These settings create an admin user.

ADMIN_NAME = get_env("BIOSTAR_ADMIN_NAME", __DEFAULT_BIOSTAR_ADMIN_NAME)
ADMIN_EMAIL = get_env("BIOSTAR_ADMIN_EMAIL", __DEFAULT_BIOSTAR_ADMIN_EMAIL)
ADMIN_LOCATION = "Anytown, USA"
ADMINS = (
    (ADMIN_NAME, ADMIN_EMAIL),
)

# Get the secret key from the environment.
SECRET_KEY = get_env("SECRET_KEY", __DEFAULT_SECRET_KEY)
READER_TO_WRITER_AUTH_TOKEN = None

MANAGERS = ADMINS

# admin site may fail if this setting is active
TEMPLATE_STRING_IF_INVALID = "*** MISSING ***"

SITE_ID = 1
SITE_NAME = "Site Name"
SITE_DOMAIN = get_env("SITE_DOMAIN", __DEFAULT_SITE_DOMAIN)

# Hosts/domain names that are valid for this site; required if DEBUG is False
# See https://docs.djangoproject.com/en/1.5/ref/settings/#allowed-hosts

# These parameters will be inserted into the database automatically.
ALLOWED_HOSTS = ["localhost", "www.lvh.me", SITE_DOMAIN]

ATOMIC_REQUESTS = True
CONN_MAX_AGE = 10;

# Allowed html content.
ALLOWED_TAGS = "p div br code pre h1 h2 h3 h4 hr span s sub sup b i img strong strike em underline super table thead tr th td tbody".split()
ALLOWED_STYLES = 'color font-weight background-color width height'.split()
ALLOWED_ATTRIBUTES = {
    '*': ['class', 'style'],
    'a': ['href', 'rel'],
    'img': ['src', 'alt', 'width', 'height'],
    'table': ['border', 'cellpadding', 'cellspacing'],

}

# Local time zone for this installation. Choices can be found here:
# http://en.wikipedia.org/wiki/List_of_tz_zones_by_name
# although not all choices may be available on all operating systems.
# In a Windows environment this must be set to your system time zone.
TIME_ZONE = 'America/Chicago'

# Language code for this installation. All choices can be found here:
# http://www.i18nguy.com/unicode/language-identifiers.html
LANGUAGE_CODE = 'en-us'

# Configure language detection
LANGUAGE_DETECTION = ['en']

SERVER_EMAIL = DEFAULT_FROM_EMAIL = get_env("DEFAULT_FROM_EMAIL", __DEFAULT_FROM_EMAIL)

# What domain will handle the replies.
EMAIL_REPLY_PATTERN = "reply+%s+code@biostars.io"

# The format of the email that is sent
EMAIL_FROM_PATTERN = u'''"%s on Biostar" <%s>'''

# The secret key that is required to parse the email
EMAIL_REPLY_SECRET_KEY = "abc"

# The subject of the reply goes here
EMAIL_REPLY_SUBJECT = u"[biostar] %s"

# Should replying to an email remove the quoted text
EMAIL_REPLY_REMOVE_QUOTED_TEXT = True

# If you set this to False, Django will make some optimizations so as not
# to load the internationalization machinery.
USE_I18N = True

# If you set this to False, Django will not format dates, numbers and
# calendars according to the current locale.
USE_L10N = True

# If you set this to False, Django will not use timezone-aware datetimes.
USE_TZ = True

# URL that handles the media served from MEDIA_ROOT. Make sure to use a
# trailing slash.
# Examples: "http://example.com/media/", "http://media.example.com/"
MEDIA_URL = '/static/upload/'

# URL prefix for static files.
# Example: "http://example.com/static/", "http://static.example.com/"
STATIC_URL = '/static/'

# Additional locations of static files
STATICFILES_DIRS = (
    # Use absolute paths, not relative paths.
    STATIC_DIR,
)

# List of finder classes that know how to find static files in
# various locations.
STATICFILES_FINDERS = (
    'django.contrib.staticfiles.finders.FileSystemFinder',
    'django.contrib.staticfiles.finders.AppDirectoriesFinder',
    'compressor.finders.CompressorFinder',
)

# List of callables that know how to import templates from various sources.
TEMPLATE_LOADERS = (
    'django.template.loaders.filesystem.Loader',
    'django.template.loaders.app_directories.Loader',
)

MIDDLEWARE_CLASSES = (
    'django.middleware.common.CommonMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'biostar.server.middleware.Visit',
)

ROOT_URLCONF = 'biostar.urls'

# Python dotted path to the WSGI application used by Django's runserver.
WSGI_APPLICATION = 'biostar.wsgi.application'


# The user score that halves the chance.
HALF_LIFE = 30.0

# Avataar server name (3 options):
#   A. Default is a cookie-less server provided by ln.support
#   B. You could use a third-party server "https://avatars.dicebear.com"
#   C. To use own avatar server change to:
#   __DEFAULT_AVATAR_SERVER_NAME = "/"
#   and run your own server:
#   https://github.com/DiceBear/avatars/tree/5a12112e98830c9ab017ed494fa4e3b20266303f/server#3-start-server
__DEFAULT_AVATAR_SERVER_NAME = "https://ln.support"
AVATAR_SERVER_NAME = get_env("AVATAR_SERVER_NAME", __DEFAULT_AVATAR_SERVER_NAME)

LOGIN_REDIRECT_URL = "/"

MESSAGE_TAGS = {
    10: 'alert-info', 20: 'alert-info',
    25: 'alert-success', 30: 'alert-warning', 40: 'alert-danger',
}

INSTALLED_APPS = [
    'readonly',  # reader must be read-only

    'django.contrib.contenttypes',

    'django.contrib.sites',
    'django.contrib.staticfiles',
    'django.contrib.sitemaps',

    # The javascript and CSS asset manager.
    'compressor',

    # Enabling the admin and its documentation.
    'django.contrib.admin',
    'django.contrib.humanize',

    # Biostar specific apps.
    'biostar.apps.users',
    'biostar.apps.util',
    'biostar.apps.posts',
    'biostar.apps.messages',
    'biostar.apps.badges',
    'biostar.apps.bounty',

    # The main Biostar server.
    'biostar.server',

    # External apps.
    'haystack',  # Modular search for Django
    'crispy_forms',  # application that lets you easily build, customize and reuse forms
    #'djcelery',  # was used by Biostar for sending emails
    #             # "queue, execution units, called tasks, are executed concurrently
    #             # on a single or more worker servers using multiprocessing, Eventlet,
    #             # or gevent. Tasks can execute asynchronously (in the background) or
    #             # synchronously (wait until ready)"
    'kombu.transport.django',  # "transport using the Django database as a message store"
    'captcha',  # mostly deleted in the De-Cookify commit 19e67656233669db8c386fa69b125571faeaff4e
]

CRISPY_TEMPLATE_PACK = 'bootstrap3'

AUTH_USER_MODEL = 'users.User'

DEBUG_TOOLBAR_PATCH_SETTINGS = False

# Default search is provided via Whoosh

HAYSTACK_CONNECTIONS = {
    'default': {
        'ENGINE': 'haystack.backends.whoosh_backend.WhooshEngine',
        'PATH': WHOOSH_INDEX,
    },
}

TEMPLATE_CONTEXT_PROCESSORS = (
    # Django specific context processors.
    "django.core.context_processors.debug",
    "django.core.context_processors.static",
    "django.core.context_processors.request",

    # Biostar specific context.
    'biostar.server.context.shortcuts',
)

ACCOUNT_CONFIRM_EMAIL_ON_GET = True

# Should the captcha be shown on the signup page.
CAPTCHA = True

# For how long does a user need to be a member to become trusted.
TRUST_RANGE_DAYS = 7

# Votes needed to start trusting the user
TRUST_VOTE_COUNT = 5

# How many non top level posts per day for users.
MAX_POSTS_NEW_USER = 5
MAX_POSTS_TRUSTED_USER = 30

# How many top level posts per day for a new user.
MAX_TOP_POSTS_NEW_USER = 2
MAX_TOP_POSTS_TRUSTED_USER = 5


# The site logo.
SITE_LOGO = "ln.support.v2.logo.png"

# Digest title
DAILY_DIGEST_TITLE = '[biostar daily digest] %s'
WEEKLY_DIGEST_TITLE = '[biostar weekly digest] %s'

# The default CSS file to load.
SITE_STYLE_CSS = "biostar.style.v2.css"

# Set it to None if all posts should be accesible via the Latest tab.
SITE_LATEST_POST_LIMIT = None

# How many recent objects to show in the sidebar.
RECENT_VOTE_COUNT = 7
RECENT_USER_COUNT = 7
RECENT_POST_COUNT = 12

# Time between two accesses from the same IP to qualify as a different view.
POST_VIEW_MINUTES = 5

# Default  expiration in seconds.
CACHE_TIMEOUT = 60

COMPRESS_OFFLINE_CONTEXT = {
    'STATIC_URL': STATIC_URL,
    'SITE_STYLE_CSS': SITE_STYLE_CSS,
}

# The cache mechanism is deployment dependent. Override it externally.
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.dummy.DummyCache' if DEBUG else 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'unique-snowflake'
    }
}

# The celery configuration file
CELERY_CONFIG = 'biostar.celeryconfig'

# How far to look for posts for anonymous users.
COUNT_INTERVAL_WEEKS = 10000


# The number of posts to show per page.
PAGINATE_BY = 25


# Use a mock email backend for development.
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# On deployed servers the following must be set.
EMAIL_HOST = get_env("EMAIL_HOST", "localhost")
EMAIL_PORT = get_env("EMAIL_PORT", default=25, func=int)
EMAIL_HOST_USER = get_env("EMAIL_HOST_USER", "postmaster")
EMAIL_HOST_PASSWORD = get_env("EMAIL_HOST_PASSWORD", "password")

DJANGO_SETTINGS_MODULE = get_env('DJANGO_SETTINGS_MODULE', 'biostar.settings.base')

if __name__ == '__main__':
    """
    When run from command line report the environment
    """
    print("")
    print("Biostar environment:")
    print("")
    print("BIOSTAR_HOME={}".format(HOME_DIR))
    print("BIOSTAR_ADMIN_EMAIL={}".format(ADMIN_EMAIL))
    print("BIOSTAR_ADMIN_NAME={}".format(ADMIN_NAME))
    print("")
    print("DJANGO_SETTINGS_MODULE={}".format(DJANGO_SETTINGS_MODULE))
    print("DATABASE_NAME={}".format(DATABASE_NAME))
    print("DEFAULT_FROM_EMAIL={}".format(DEFAULT_FROM_EMAIL))
