#!/bin/bash
set -ue

# Required environmental variables:
# * SITE_NAME
# * SITE_DOMAIN
# * PG_HOST
# * PG_PASSWORD

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
CONF_DIR="$( cd $SCRIPT_DIR/.. && pwd )"
BIOSTAR_HOME="$( cd $CONF_DIR/.. && pwd )"
VIRTENV_DIR="$( cd $BIOSTAR_HOME/../../reader-env && pwd )"

echo "SCRIPT_DIR : $SCRIPT_DIR"
echo "CONF_DIR   : $CONF_DIR"
echo "VIRTENV_DIR: $VIRTENV_DIR"
echo "BIOSTAR_HOME: $BIOSTAR_HOME"

export VIRTUAL_ENV_DISABLE_PROMPT=1
source $VIRTENV_DIR/bin/activate

# The django module to use.
export DJANGO_SETTINGS_MODULE=biostar.settings.beta

# This will be either the Sqlite or the Postgres database name.
export DATABASE_NAME="beta"

# The level of verbosity for django commands.
export VERBOSITY=1

# The python executable to invoke.
export PYTHON="python"

# The django manager to run.
export DJANGO_ADMIN=manage.py

# Setting the various access logs.
ACCESS_LOG=~/log/gunicorn-access.log
ERROR_LOG=~/log/gunicorn-error.log

# The user and group the unicorn process will run as.
NUM_WORKERS=3

# Where to bind.
BIND="unix:/tmp/biostar.sock"
#BIND="localhost:8080"

# The WSGI module that starts the process.
DJANGO_WSGI_MODULE='biostar.wsgi'

# The gunicorn instance to run.
GUNICORN="gunicorn"

# How many requests to serve.
MAX_REQUESTS=1000

# The name of the application.
NAME="biostar_app"

echo "gunicorn starting with DJANGO_SETTINGS_MODULE=$DJANGO_SETTINGS_MODULE"

cd $BIOSTAR_HOME
exec $GUNICORN ${DJANGO_WSGI_MODULE}:application \
  --name $NAME \
  --workers $NUM_WORKERS \
  --max-requests $MAX_REQUESTS\
  --bind $BIND\
