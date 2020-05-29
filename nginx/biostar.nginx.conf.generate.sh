#!/bin/bash

set -ue

# Required environmental variables:
# * DOMAIN_NAME
# * LIVE_DIR
# * LOG_DIR

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

cat $DIR/biostar.nginx.conf.TEMPLATE | \
	sed "s|%DOMAIN_NAME%|$DOMAIN_NAME|g" | \
	sed "s|%LIVE_DIR%|$LIVE_DIR|g" | \
	sed "s|%LOG_DIR%|$LOG_DIR|g" | \
	> $DIR/biostar.nginx.conf

echo "Generated $DIR/biostar.nginx.conf"
