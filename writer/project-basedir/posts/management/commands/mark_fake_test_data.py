__author__ = 'ialbert'

from django.core.management import call_command
from django.conf import settings
from django.db import connection, transaction
from django.core.management.base import BaseCommand, CommandError
from django.contrib.humanize.templatetags import humanize

from django.db.models import F

from optparse import make_option
from common.log import logger

from posts.models import Tag
from posts.models import Post
from posts.models import Vote
from users.models import User
from badges.models import Award

from users.management.awards import create_user_award
from users.management.awards import init_awards

import random
import os

os.environ['DJANGO_COLORS'] = 'nocolor'

class Command(BaseCommand):
    help = 'Go through all real posts and ask if they should be marked as fake test data'

    def add_arguments(self, parser):
        parser.add_argument(
            "--fix-only",
            action="store_true",
            help="Do not mark anything as fake, only fix related data",
        )

        parser.add_argument(
            "--mark-as-real",
            action="store_true",
            help="Go through all fake posts and ask if they should be marked as real"
        )

        parser.add_argument(
            "--limit",
            type=int,
            default=1,
            help="How many posts to mark as fake"
        )

    def handle(self, *args, **options):
        mark_fake_test_data(
            fix_only=options.get("fix_only"),
            mark_as_real=options.get("mark_as_real"),
            limit=options.get("limit")
        )


def yesno(question):
    res = input("{} (Enter y/n) ".format(question)).lower()

    if res not in {"y", "n"}:
        print('Please type "y" or "n" ')
        res = yesno(question)

    return res == "y"


class LatestUpdateTracker(object):
    """Calculate latest updated for top-level posts"""

    def __init__(self):
        self.lastedit_post = {}

    def update(self, parent_id, post):
        """
        So that we can find which one was latest
        update() needs to be called on every post
        that's related to parent_id and
        on the parent post itself
        """

        if parent_id not in self.lastedit_post:
            self.lastedit_post[parent_id] = post

        if self.lastedit_post[parent_id].creation_date < post.creation_date:
            self.lastedit_post[parent_id] = post

    def get_latest(self, parent_id):
        return self.lastedit_post[parent_id]


def mark_fake_test_data(fix_only, mark_as_real, limit):
    lut = LatestUpdateTracker()

    # Ask if posts need to be marked as fake / real
    if not fix_only:
        for p in Post.objects.all().filter(is_fake_test_data=mark_as_real).order_by('-creation_date'):
            print(
                "id={}\tcreation_date={}\t{}\t{}\ttitle={}".format(
                    p.id,
                    p.creation_date,
                    humanize.naturaltime(p.creation_date),
                    "TOP_LEVEL" if p.is_toplevel else "-",
                    p.title
                )
            )

            if mark_as_real:
                if yesno("Mark as real?"):
                    limit -= 1
                    p.is_fake_test_data = False
                    p.save()
                    print("Marked post as real!")
            else:
                if yesno("Mark as fake?"):
                    limit -= 1
                    p.is_fake_test_data = True
                    p.save()
                    print("Marked post as fake test data!")

            if limit < 1:
                print("Limit of 1 reached")
                break

    # Re-query posts, now that is_fake_test_data fields got modified
    posts = Post.objects.all().filter(is_fake_test_data=mark_as_real).order_by('-creation_date')

    # Calculate latest updated for all top-level posts
    for p in posts:
        if p.is_toplevel:
            lut.update(p.id, p)
        else:
            lut.update(p.parent.id, p)

    # Posts
    print("\nPosts:")
    for p in posts:
        if p.is_toplevel:
            l = lut.get_latest(p.id)
            if p.lastedit_user != l.author:
                print("Top level post need update id={}\ttitle={}".format(p.id, p.title))
                p.lastedit_date = l.creation_date
                p.lastedit_user = l.author
                p.save()
                print("- updated lastedit to author={} date={}".format(l.author.id, l.creation_date))

    # Users
    # TODO: implement inverse when mark_as_real=True
    print("\nUsers:")
    for u in User.objects.all():
        # has real posts
        if Post.objects.filter(author=u, is_fake_test_data=False):
            if u.is_fake_test_data:
                print("User (id={}\tpubkey={})".format(u.id, u.pubkey))
                u.is_fake_test_data = False
                u.save()
                print("User has real posts, marked user {} as real!".format(u.id))

        # does not have real posts
        else:
            if not u.is_fake_test_data:
                print("User (id={}\tpubkey={})".format(u.id, u.pubkey))
                u.is_fake_test_data = True
                u.save()
                print("No real posts by user, marked user {} as fake test data!".format(u.id))


    # Votes
    # TODO: implement inverse when mark_as_real=True
    print("\nVotes:")
    for v in Vote.objects.exclude(is_fake_test_data=True):
        if v.post.is_fake_test_data:
            print("Vote (id={})".format(v.id))
            v.is_fake_test_data = True
            v.save()
            print("Vote is for a fake test data post, marked vote {} as fake test data!".format(v.id))

    # Update scores
    # TODO: implement inverse when mark_as_real=True
    # TODO: refactor to share logic with process_tasks
    # Now that the votes changed, we need to update User and Thread scores

    logger.warning("Setting all user's reputations to 0")
    User.objects.all().update(score=0)

    logger.warning("Setting all post's thread_score to 0")
    Post.objects.all().update(thread_score=0)

    change = settings.POST_PAYMENT_AMOUNT  # TODO: BUG?: This may not always be true. Votes have custom amounts.

    for v in Vote.objects.exclude(is_fake_test_data=True):
        if v.type in [Vote.UP, Vote.ACCEPT]:
            logger.info("Counting vote {}: author={}, post={}, type={}".format(v.id, v.author.id, v.post.id, v.human_vote_type()))

            # Update user reputation
            User.objects.filter(pk=v.post.author.id).update(score=F('score') + change)

            # The thread score represents all votes in a thread
            Post.objects.filter(pk=v.post.root_id).update(thread_score=F('thread_score') + change)


    # Awards
    print("\nAwards:")
    for a in Award.objects.all():
        if a.user.is_fake_test_data:
            if not a.is_fake_test_data:
                a.is_fake_test_data = True
                a.save()
                print("Award author is not real, marked award {} as fake test data!".format(a.id))
        else:
            # If user is real yet the post is fake, then mark award as fake
            if a.is_fake_test_data:
                a.is_fake_test_data = False
                a.save()
                print("Award author is real, marked award {} as real!".format(a.id))


    # Tags
    print("\nTags:")
    for t in Tag.objects.all():
        # Has real posts
        if Post.objects.filter(tag_set=t, is_fake_test_data=False):
            if t.is_fake_test_data:
                print("Tag (id={}\tname={})".format(t.id, t.name))

                t.is_fake_test_data = False
                t.save()
                print("Tag has real posts, marked {} as real!".format(t.id))

        # Does not have real posts
        else:
            if not t.is_fake_test_data:
                print("Tag (id={}\tname={})".format(t.id, t.name))

                t.is_fake_test_data = True
                t.save()
                print("Tag does not have real posts, marked {} as fake test data!".format(t.id))


    # Reply counts
    # Update reply counts in case some reply was marked as fake
    print("\nUpdating reply counts!")
    for p in Post.objects.all():
        # When saving update_reply_count gets called.
        # Child posts update parents,
        # since one parent can have multiple children, the computation
        # is duplicated for every child, so this can potentially be an efficiency improvement.
        p.save()
