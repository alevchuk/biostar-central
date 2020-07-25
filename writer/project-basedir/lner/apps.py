from django.apps import AppConfig
from common.log import logger


class LnerConfig(AppConfig):
    name = 'lner'


    def ready(self):
        logger.info(f"{self.name} ready")
