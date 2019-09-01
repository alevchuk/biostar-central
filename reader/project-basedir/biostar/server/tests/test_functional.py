from django.test import TestCase, SimpleTestCase
from django.test import Client
from django.core.urlresolvers import reverse
from django.conf import settings
from biostar.apps.users.models import User
from biostar.apps.posts.models import Post, Tag, PostView, Subscription
from biostar.apps.messages.models import Message, MessageBody

import logging, random
import unittest

logging.disable(logging.WARNING)

user_count = lambda: User.objects.all().count()
post_count = lambda: Post.objects.all().count()
subs_count = lambda: Subscription.objects.all().count()
get_user = lambda x: User.objects.get(pubkey=x)

haystack_logger = logging.getLogger('haystack')

# Set up some test data.
NAME_1, EMAIL_1, PASSWD_1 = "John Doe", "user1@example.org", "0123567"
NAME_2, EMAIL_2, PASSWD_2 = "Jane Doe", "user2@example.org", "3456789"

USER_DATA = [
    (EMAIL_1, PASSWD_1),
    (EMAIL_2, PASSWD_2),
]

# The name of test posts
TITLE_1 = "Post 1, title needs to be sufficiently long"
CAT_1, TAG_VAL_1 = Post.QUESTION, "tagA tagB galaXY"

TITLE_2 = "Post 2, title needs to be sufficiently long"
CAT_2, TAG_VAL_2 = Post.JOB, "jobA jobB galaxy"

CONTENT = """
    Lorem ipsum dolor sit amet, consectetur adipisicing elit,
    sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.
    """

POST_DATA = [
    (TITLE_1, CAT_1, TAG_VAL_1),
    (TITLE_2, CAT_2, TAG_VAL_2),
]

class UserTest(TestCase):
    # The name of test users

    def code(self, response, code=200):
        self.assertEqual(response.status_code, code)

    def tearDown(self):
        haystack_logger.setLevel(logging.INFO)

    def setUp(self):

        # Disable haystack logger, testing will raise errors
        # on the more_like_this field in templates.
        haystack_logger.setLevel(logging.CRITICAL)


    def create_new_post(self, title, post_type, tag_val):
        p_count = post_count()
        s_count = subs_count()
        r = self.client.post(
            reverse("new-post"),
            dict(title=title, tag_val=tag_val, post_type=post_type, content=CONTENT),
        )

        # Needs to redirect to post
        self.code(r, 302)

        # After creating a new post the post count and subscription counts increase.
        self.assertEqual(post_count(), p_count + 1)
        self.assertEqual(subs_count(), s_count + 1)

    def create_new_answer(self, post):
        p_count = post_count()
        r = self.client.post(
            reverse("new-answer", kwargs=dict(pid=post.id)),
            dict(content=CONTENT),
        )
        self.code(r, 302)
        self.assertEqual(post_count(), p_count + 1)

    def get_post(self, pk):
        "Gets a post and returns it"
        post = Post.objects.get(pk=pk)
        r = self.client.get(reverse("post-details", kwargs=dict(pk=pk)))
        if post.is_toplevel:
            self.assertContains(r, post.title)
            self.code(r)
        else:
            self.code(r, 302)

        # Verify that a subscription exists for this post and author.

        self.assertTrue(Subscription.objects.get_subs(post).filter(user=post.author).count() == 1)
        return post


    @unittest.skip("2019-01-04 create_new_post does not redirect to a post")
    def test_user_answer(self):
        "Test posting an answer."
        self.login(EMAIL_1, PASSWD_1)
        title = TITLE_1
        self.create_new_post(title=title, post_type=CAT_1, tag_val=TAG_VAL_1)
        post1 = Post.objects.get(title=title)
        post2 = self.get_post(post1.id)
        self.assertEqual(post1, post2)

        # Same user adds a new answer.
        p_count = post_count()

        self.create_new_answer(post1)

        # No message has been added because it is the same user.
        self.logout()

        # A different user adds an answer
        self.login(EMAIL_2, PASSWD_2)
        self.create_new_answer(post1)

        # Test voting and that it applies to user and posts
        user1 = get_user(EMAIL_1)
        post = Post.objects.get(title=TITLE_1, type=Post.QUESTION)

        # First access adds a vote.
        r = self.client.post(reverse("vote-submit"), data=dict(post_id=post.id, vote_type="vote"))
        user2 = get_user(EMAIL_1)
        self.assertEqual(user1.score + 1, user2.score)

        # Seconds access removes a vote.
        r = self.client.post(reverse("vote-submit"), data=dict(post_id=post.id, vote_type="vote"))
        user3 = get_user(EMAIL_1)
        self.assertEqual(user1.score, user3.score)

        # Bookmarks also add reputation.
        r = self.client.post(reverse("vote-submit"), data=dict(post_id=post.id, vote_type="bookmark"))
        user4 = get_user(EMAIL_1)
        self.assertEqual(user1.score + 1, user4.score)



class SiteTest(SimpleTestCase):

    def code(self, response, code=200):
        self.assertEqual(response.status_code, code)

    def test_site_navigation(self):
        "Testing site navigation."

        # Main site navigation.
        names = "home user-list tag-list rss latest-feed signup".split()
        for name in names:
            r = self.client.get(reverse(name))
            self.code(r)

        # Check that default categories work.
        for topic in settings.CATEGORIES:
            r = self.client.get(reverse("topic-list", kwargs=dict(topic=topic)))
            self.code(r)

    def test_redirects(self):
        "Testing page redirects."

        # Pages with redirects.
        names = "login logout new-post user-votes".split()
        for name in names:
            r = self.client.get(reverse(name))
            self.code(r, 302)

    def test_edit_pages(self):
        "Testing page redirects."
        # Pages that take parameters and redirect.
        names = "user-edit post-edit user-moderation post-moderation ".split()
        for name in names:
            r = self.client.get(reverse(name, kwargs=dict(pk=1)))
            self.code(r, 302)



