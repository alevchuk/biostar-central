import logging
import sys
import time
import json

from datetime import datetime
from datetime import timedelta

from django.utils import timezone
from django.conf import settings

from rest_framework import serializers

from common.log import logger


from bounty.models import Bounty
from bounty.models import BountyAward

from posts.models import Post

from users.models import User

from django.core.management.base import BaseCommand

from prometheus_client import Gauge, start_http_server


SLEEP_BETWEEN_CHECKS = 600  # 10 minutes

METRICS_PORT = 2892
LAST_CHECK_GAUGE = Gauge(
    'check_last_success_unixtime',
    'Last time node was successfully checked',
    ["node_name"]
)

logger.info("Python version: {}".format(sys.version.replace("\n", " ")))


def sleep(seconds):
    logger.debug("Sleeping for {} seconds".format(seconds))
    time.sleep(seconds)


# TODO: move to shared library
def get_anon_user():
    user, created = User.objects.get_or_create(pubkey="Unknown")
    if created:
        logger.info("This is probably an empty DB! Anonymous user created: {}".format(user))

    return user


def post_link():
    if "lvh.me" in settings.SITE_DOMAIN:
        return "http://{}:8080".format(settings.SITE_DOMAIN)
    else:
        return "https://{}".format(settings.SITE_DOMAIN)

def run_one():
    awards_to_expand = []

    # 1. For each active bounty
    # Note: we only expand active bounties that are not yet payed
    for bounty in Bounty.objects.filter(is_active=True, is_payed=False):
        award_list = BountyAward.objects.filter(bounty=bounty).order_by('created')

        if len(award_list) == 0:
            logger.info("No awards, so no expand for bounty {} for {}/{}".format(
                    bounty.id,
                    post_link(),
                    bounty.post_id.id,
                )
            )
            continue

        award = award_list.last()  # most recently created

        # 2. Find time when the next award expansion needs to happen
        next_award_time = award.created + settings.CLAIM_TIMEDELTA

        # 3. Check if the ^ time is in the past
        now = timezone.now()
        logger.info(
            "Is it time to expand bounty {} for {}/{} ? The latest award is {} and the next award time is in {:.3f} days".format(
                bounty.id,
                post_link(),
                bounty.post_id.id,
                award.id,
                (next_award_time - now).total_seconds() / 86400.0
            )
        )

        if next_award_time < now:
            awards_to_expand.append(award)

    # 4. Expand
    for award in awards_to_expand:
        logger.info("\n\n")
        logger.info(
            "Expanding bounty {} for {}/{}, the latest award is {}".format(
                award.bounty.id,
                post_link(),
                award.bounty.post_id.id,
                award.id,
            )
        )

        # TODO: extract into a shared function
        #
        # 4.1. Find the next top votes answer
        #
        # Find the top voted answer among answers after the bounty start time
        # creation date breaks ties, oldest wins
        a_list = Post.objects.filter(
            parent=award.bounty.post_id.id,
            creation_date__gt=award.bounty.activation_time,
        ).exclude(
            author=get_anon_user(),
        ).exclude(
            id=award.post.id
        ).order_by(
            'vote_count',
            '-creation_date'
        )
        logger.info("{} answers found".format(len(a_list)))

        if len(a_list) == 0:
            logger.info("No contenders found, no next top voted answers")
        else:
            top_answer = a_list.last()
            logger.info("Next top voted answer is {}/{}".format(post_link(), top_answer.id))

            # 4.2. Add award
            award = BountyAward.objects.create(bounty=award.bounty, post=top_answer)
            logger.info("Created new award {}".format(award))


    logger.info("\n")


def run_many():
    num_runs = 0

    while True:
        start_time = time.time()
        num_runs += 1

        run_one()

        processing_wall_time = time.time() - start_time
        logger.info("Finished in wall-time of {:.3f} seconds, total number of runs is {}".format(processing_wall_time, num_runs))
        logger.info("\n\n\n\n\n")

        sleep(SLEEP_BETWEEN_CHECKS)


class Command(BaseCommand):
    help = 'Performs actions on users'

    def add_arguments(self, parser):
        parser.add_argument('--award', action='store_true', help='goes over the users and attempts to create awards')

    def handle(self, *args, **options):
        logger.info("Starting metrics on port {} ...".format(METRICS_PORT))

        start_http_server(METRICS_PORT)
        logger.info("Metrics server started")

        run_many()
