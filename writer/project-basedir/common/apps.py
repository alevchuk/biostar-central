from django.apps import AppConfig
from common.log import logger
import sys
import os
import prometheus_client

METRICS_PORT = 9999

class CommonConfig(AppConfig):
    name = 'common'

    def ready(self):
        logger.info(f"{self.name} ready")
        self.setup_metrics()

    def setup_metrics(self):
        if "runserver" not in sys.argv:
            logger.info("Skipping metrics...")
            return  # other microservices have their own metric ports

        # https://github.com/django/django/blob/master/django/utils/autoreload.py
        if os.environ.get('RUN_MAIN') is None:
            logger.info("This is autoreloader, skipping metrics")
            return

        logger.info("Starting metrics on port {} ...".format(METRICS_PORT))
        prometheus_client.start_http_server(METRICS_PORT)
        logger.info("Metrics server started")
