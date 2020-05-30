#!/bin/bash

set -ue

# Required environmental variables:
# * DOMAIN_NAME
# * LIVE_DIR
# * LOG_DIR

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

for conf in biostar.nginx.conf__certbot biostar.nginx.conf__no_certbot; do
    cat $DIR/$conf.TEMPLATE | \
    	sed "s|%DOMAIN_NAME%|$DOMAIN_NAME|g" | \
    	sed "s|%LIVE_DIR%|$LIVE_DIR|g" | \
    	sed "s|%LOG_DIR%|$LOG_DIR|g" > ~/$conf

    echo "Generated ~/$conf"
done

