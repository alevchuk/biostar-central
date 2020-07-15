from __future__ import print_function, unicode_literals, absolute_import, division
import logging
import datetime
import string
import time
from django.db import models
from django.conf import settings
from django.contrib.sites.models import Site

from django.utils.timezone import utc
from django.utils.translation import ugettext_lazy as _

# TODO: remove version check after upgrading reader
import django
if django.VERSION[0] == 1:
    from django.core.urlresolvers import reverse
else:
    from django.urls import reverse

# "import bleach" needs packages: bleach, html5lib
import bleach
from django.db.models import Q, F
from django.core.exceptions import ObjectDoesNotExist

from common import const
from common import general_util
from common import html_util
from common import json_util
from common import validators

try:
    # writer
    from users.models import User
except ImportError:
    # reader
    from biostar.apps.users.models import User

try:
    # only reader needs this, only reader has this
    from biostar.apps.util import ln
except  ImportError:
    # writer
    pass


# HTML sanitization parameters.
import json
import binascii
import zlib

from common.log import logger


class Tag(models.Model):
    name = models.TextField(max_length=50, db_index=True)
    count = models.IntegerField(default=0)
    is_fake_test_data = models.BooleanField(default=False)

    @staticmethod
    def fixcase(name):
        return name.upper() if len(name) == 1 else name.lower()

    @staticmethod
    def update_counts(sender, instance, action, pk_set, *args, **kwargs):
        "Applies tag count updates upon post changes"

        if action == 'post_add':
            Tag.objects.filter(pk__in=pk_set).update(count=F('count') + 1)

        if action == 'post_remove':
            Tag.objects.filter(pk__in=pk_set).update(count=F('count') - 1)

        if action == 'pre_clear':
            instance.tag_set.all().update(count=F('count') - 1)

    def __unicode__(self):
        return self.name


class PostManager(models.Manager):

    def my_bookmarks(self):
        query = self.filter(votes__type=Vote.BOOKMARK)
        query = query.select_related("root", "author", "lastedit_user")
        query = query.prefetch_related("tag_set")
        return query

    def my_posts(self, target):

        # Show all posts for moderators or targets
        query = self.filter(author=target).exclude(status=Post.DELETED).exclude(is_fake_test_data=True)

        query = query.select_related("root", "author", "lastedit_user")
        query = query.prefetch_related("tag_set")
        query = query.order_by("-creation_date")
        return query

    def fixcase(self, text):
        return text.upper() if len(text) == 1 else text.lower()

    def tag_search(self, text):
        "Performs a query by one or more , separated tags"
        include, exclude = [], []
        # Split the given tags on ',' and '+'.
        terms = text.split(',') if ',' in text else text.split('+')
        for term in terms:
            term = term.strip()
            if term.endswith("!"):
                exclude.append(self.fixcase(term[:-1]))
            else:
                include.append(self.fixcase(term))

        if include:
            query = self.filter(type__in=Post.TOP_LEVEL, tag_set__name__in=include).exclude(
                tag_set__name__in=exclude)
        else:
            query = self.filter(type__in=Post.TOP_LEVEL).exclude(tag_set__name__in=exclude)

        query = query.filter(status=Post.OPEN)

        # Hide test data
        query = query.exclude(is_fake_test_data=True)

        # Remove fields that are not used.
        query = query.defer('content', 'html')

        # Get the tags.
        query = query.select_related("root", "author", "lastedit_user").prefetch_related("tag_set").distinct()

        return query

    def get_thread(self, root):
        # Populate the object to build a tree that contains all posts in the thread.
        query = self.filter(root=root).exclude(status=Post.DELETED).select_related("root", "author", "lastedit_user") \
            .order_by("type", "-has_accepted", "-vote_count", "creation_date")

        return query

    def top_level(self):
        "Returns posts"

        query = self.filter(type__in=Post.TOP_LEVEL).exclude(status=Post.DELETED)

        # Hide test data
        query = query.exclude(is_fake_test_data=True)

        return query.select_related("root", "author", "lastedit_user").prefetch_related("tag_set").defer("content", "html")


class Post(models.Model):
    "Represents a post in Biostar"

    objects = PostManager()

    # Post statuses.
    PENDING, OPEN, CLOSED, DELETED = range(4)
    STATUS_CHOICES = [(PENDING, "Pending"), (OPEN, "Open"), (CLOSED, "Closed"), (DELETED, "Deleted")]

    # Question types. Answers should be listed before comments.
    (
        QUESTION, # 0
        ANSWER, # 1
        META_QUESTION, # ?
        COMMENT # ?
    ) = range(4)

    TYPE_CHOICES = [
        (QUESTION, "Question"),  # 0
        (ANSWER, "Answer"),  # 1
        (META_QUESTION, "Meta"), # TODO: check
        (COMMENT, "Comment"),  # TODO: check
    ]

    TOP_LEVEL = set((QUESTION, META_QUESTION))

    title = models.CharField(max_length=200, null=False, unique=False, validators=[validators.validate_signable_field])

    # The user that originally created the post.
    author = models.ForeignKey(User, on_delete=models.CASCADE)

    # The user that edited the post most recently.
    lastedit_user = models.ForeignKey(User, related_name='editor', on_delete=models.CASCADE)

    # Indicates the information value of the post.
    rank = models.FloatField(default=0, blank=True)

    # Post status: open, closed, deleted.
    status = models.IntegerField(choices=STATUS_CHOICES, default=OPEN)

    # The type of the post: question, answer, comment.
    type = models.IntegerField(choices=TYPE_CHOICES, db_index=True)

    # Number of upvotes for the post
    vote_count = models.IntegerField(default=0, blank=True, db_index=True)

    # The number of views for the post.
    view_count = models.IntegerField(default=0, blank=True)

    # The number of replies that a post has.
    reply_count = models.IntegerField(default=0, blank=True)

    # The number of comments that a post has.
    comment_count = models.IntegerField(default=0, blank=True)

    # Bookmark count.
    book_count = models.IntegerField(default=0)

    # Indicates indexing is needed.
    changed = models.BooleanField(default=True)

    # How many people follow that thread.
    subs_count = models.IntegerField(default=0)

    # The total score of the thread (used for top level only)
    thread_score = models.IntegerField(default=0, blank=True, db_index=True)

    # Date related fields.
    creation_date = models.DateTimeField(db_index=True)
    lastedit_date = models.DateTimeField(db_index=True)

    # Stickiness of the post.
    sticky = models.BooleanField(default=False, db_index=True)

    # Indicates whether the post has accepted answer.
    has_accepted = models.BooleanField(default=False, blank=True)

    # This will maintain the ancestor/descendant relationship bewteen posts.
    root = models.ForeignKey('self', related_name="descendants", null=True, blank=True, on_delete=models.CASCADE)

    # This will maintain parent/child replationships between posts.
    parent = models.ForeignKey('self', null=True, blank=True, related_name='children', on_delete=models.CASCADE)

    # This is the HTML that the user enters.
    content = models.TextField(default='', validators=[validators.validate_signable_field])

    # This is the  HTML that gets displayed.
    html = models.TextField(default='')

    # The tag value is the canonical form of the post's tags
    tag_val = models.CharField(max_length=100, default="", blank=True)

    # The tag set is built from the tag string and used only for fast filtering
    tag_set = models.ManyToManyField(Tag, blank=True, )

    # What site does the post belong to.
    site = models.ForeignKey(Site, null=True, on_delete=models.CASCADE)

    # Rows used for testing
    is_fake_test_data = models.BooleanField(default=False)


    def parse_tags(self):
        return html_util.split_tags(self.tag_val)

    def add_tags(self, text):
        text = text.strip()
        if not text:
            return
        # Sanitize the tag value
        self.tag_val = bleach.clean(text, tags=[], attributes=[], styles={}, strip=True)
        # Clear old tags
        self.tag_set.clear()
        tags = [Tag.objects.get_or_create(name=name)[0] for name in self.parse_tags()]
        self.tag_set.add(*tags)
        #self.save()

    @property
    def as_text(self):
        "Returns the body of the post after stripping the HTML tags"
        text = bleach.clean(self.content, tags=[], attributes=[], styles={}, strip=True)
        return text

    def peek(self, length=300):
        "A short peek at the post"
        return self.as_text[:length]

    def get_title(self):
        if self.status == Post.OPEN:
            return self.title
        else:
            return "(%s) %s" % ( self.get_status_display(), self.title)

    @property
    def is_open(self):
        return self.status == Post.OPEN

    @property
    def age_in_days(self):
        delta = general_util.now() - self.creation_date
        return delta.days

    def update_reply_count(self):
        "This can be used to set the answer count."
        if self.type == Post.ANSWER:
            reply_count = Post.objects.filter(
                parent=self.parent,
                type=Post.ANSWER,
                status=Post.OPEN,
            ).exclude(is_fake_test_data=True).count()

            Post.objects.filter(pk=self.parent_id).update(reply_count=reply_count)

    def delete(self, using=None):
        # Collect tag names.
        tag_names = [t.name for t in self.tag_set.all()]

        # While there is a signal to do this it is much faster this way.
        Tag.objects.filter(name__in=tag_names).update(count=F('count') - 1)

        # Remove tags with zero counts.
        Tag.objects.filter(count=0).delete()
        super(Post, self).delete(using=using)

    def save(self, *args, **kwargs):
        # Sanitize the post body.
        self.html = html_util.parse_html(self.content)

        # Must add tags with instance method. This is just for safety.
        self.tag_val = html_util.strip_tags(self.tag_val)

        # Posts other than a question also carry the same tag
        if self.is_toplevel and self.type != Post.QUESTION:
            required_tag = self.get_type_display()
            if required_tag not in self.tag_val:
                self.tag_val += "," + required_tag

        if not self.id:
            # Set the titles
            if self.parent and not self.title:
                self.title = self.parent.title

            if self.parent and self.parent.type in (Post.ANSWER, Post.COMMENT):
                # Only comments may be added to a parent that is answer or comment.
                self.type = Post.COMMENT

            if self.type is None:
                # Set post type if it was left empty.
                self.type = self.COMMENT if self.parent else self.FORUM

            # This runs only once upon object creation.
            self.title = self.parent.title if self.parent else self.title
            self.lastedit_user = self.author
            self.status = self.status or Post.PENDING
            self.creation_date = self.creation_date or general_util.now()
            self.lastedit_date = self.creation_date

            # Set the timestamps on the parent
            if self.type == Post.ANSWER and self.parent:
                self.parent.lastedit_date = self.lastedit_date
                self.parent.lastedit_user = self.lastedit_user
                self.parent.save()

        # Recompute post reply count
        self.update_reply_count()

        super(Post, self).save(*args, **kwargs)

    def __unicode__(self):
        return "%s: %s (id=%s)" % (self.get_type_display(), self.title, self.id)

    @property
    def is_toplevel(self):
        return self.type in Post.TOP_LEVEL

    def get_absolute_url(self):
        "A blog will redirect to the original post"
        #if self.url:
        #    return self.url
        url = reverse("post-details", kwargs=dict(pk=self.root_id))
        return url if self.is_toplevel else "%s#%s" % (url, self.id)

    def get_vote_url(self):
        obj = dict(
            action="Upvote",
            post_id=self.id,
            unixtime=int(time.time()),
            amt=1,
        )
        memo = json_util.serialize_memo(obj)
        url = reverse("vote-publish", kwargs=dict(memo=memo))

        return url

    def get_accept_url(self):
        obj = dict(
            action="Accept",
            post_id=self.id,
            unixtime=int(time.time()),
            amt=1,
        )
        memo = json_util.serialize_memo(obj)
        url = reverse("accept-preview", kwargs=dict(memo=memo))

        return url

    def get_accept_publish_url(self, memo):
        url = reverse("accept-publish", kwargs=dict(memo=memo))

        return url

    @staticmethod
    def check_root(sender, instance, created, *args, **kwargs):
        "We need to ensure that the parent and root are set on object creation."
        if created:

            if not (instance.root or instance.parent):
                # Neither root or parent are set.
                instance.root = instance.parent = instance

            elif instance.parent:
                # When only the parent is set the root must follow the parent root.
                instance.root = instance.parent.root

            elif instance.root:
                # The root should never be set on creation.
                raise Exception('Root may not be set on creation')

            if instance.parent.type in (Post.ANSWER, Post.COMMENT):
                # Answers and comments may only have comments associated with them.
                instance.type = Post.COMMENT

            assert instance.root and instance.parent

            if not instance.is_toplevel:
                # Title is inherited from top level.
                instance.title = "%s: %s" % (instance.get_type_display()[0], instance.root.title[:80])

                if instance.type == Post.ANSWER:
                    Post.objects.filter(id=instance.root.id).update(reply_count=F("reply_count") + 1)

            instance.save()


class PostPreview(models.Model):
    objects = []

    title = models.CharField(max_length=200, null=False, blank=False, validators=[validators.validate_signable_field])

    # The type of the post: question, answer, comment.
    type = models.IntegerField(choices=Post.TYPE_CHOICES, null=False, blank=False)

    # All posts other than Questions, and Meta Questions, have a parent post id
    parent_post_id = models.IntegerField(blank=True, null=True)

    # This is the HTML that the user enters.
    content = models.TextField(default='', null=False, blank=False, validators=[validators.validate_signable_field])

    # The tag value is the canonical form of the post's tags
    tag_val = models.CharField(max_length=100, null=False, blank=False)

    date = models.DateTimeField()

    memo = models.CharField(max_length=settings.MAX_MEMO_SIZE, null=True, blank=False)

    is_fake_test_data = models.BooleanField(default=False)

    @property
    def is_toplevel(self):
        return self.type in Post.TOP_LEVEL

    def serialize_memo(self):
        assert self.date.tzinfo == utc, "date must be in UTC"

        if self.is_toplevel:
            obj = dict(
                title=validators.validate_signable_field(self.title),
                post_type=self.type,
                tag_val=self.tag_val,
                content=validators.validate_signable_field(self.content),
                unixtime=int(
                    (self.date - datetime.datetime(1970,1,1).replace(tzinfo=utc)).total_seconds()
                ),
                amt=settings.POST_PAYMENT_AMOUNT,
            )
        else:
            obj = dict(
                parent_post_id=self.parent_post_id,
                post_type=self.type,
                content=validators.validate_signable_field(self.content),
                unixtime=int(
                    (self.date - datetime.datetime(1970,1,1).replace(tzinfo=utc)).total_seconds()
                ),
                amt=settings.POST_PAYMENT_AMOUNT,
            )

        memo = json_util.serialize_memo(obj)

        return memo

    def get_absolute_url(self, memo):
        url = reverse("post-preview", kwargs=dict(memo=memo))
        return url

    def get_edit_url(self, memo):
        url = reverse("post-preview-edit", kwargs=dict(memo=memo))
        return url

    def get_preview_url(self, memo):
        url = reverse("post-preview", kwargs=dict(memo=memo))
        return url

    def get_publish_url(self, memo):
        url = reverse("post-publish", kwargs=dict(memo=memo))
        return url


class ReplyToken(models.Model):
    """
    Connects a user and a post to a unique token. Sending back the token identifies
    both the user and the post that they are replying to.
    """
    # TODO: remove
    # user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    post = models.ForeignKey(Post, on_delete=models.CASCADE)
    token = models.CharField(max_length=256)
    date = models.DateTimeField(auto_created=True)
    is_fake_test_data = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        if not self.id:
            self.token = general_util.make_uuid()
        super(ReplyToken, self).save(*args, **kwargs)


class EmailEntry(models.Model):
    """
    Represents an digest digest email entry.
    """
    DRAFT, PENDING, PUBLISHED = 0, 1, 2

    # The email entry may be posted as an entry.
    post = models.ForeignKey(Post, null=True, on_delete=models.CASCADE)

    # This is a simplified text content of the Post body.
    text = models.TextField(default='')

    # The data the entry was created at.
    creation_date = models.DateTimeField(auto_now_add=True)

    # The date the email was sent
    sent_at = models.DateTimeField(null=True, blank=True)

    # The date the email was sent
    status = models.IntegerField(choices=((DRAFT, "Draft"), (PUBLISHED, "Published")))

    is_fake_test_data = models.BooleanField(default=False)


class Vote(models.Model):
    # Post statuses.
    UP, DOWN, BOOKMARK, ACCEPT = range(4)
    VOTE_TYPE_MAP = {
        "Upvote": UP,
        "Accept": ACCEPT,
        "Downvote": DOWN,
        "Bookmark": BOOKMARK,
    }
    TYPE_CHOICES = [(UP, "Upvote"), (DOWN, "DownVote"), (BOOKMARK, "Bookmark"), (ACCEPT, "Accept")]

    author = models.ForeignKey(User, on_delete=models.CASCADE)
    post = models.ForeignKey(Post, related_name='votes', on_delete=models.CASCADE)
    type = models.IntegerField(choices=TYPE_CHOICES, db_index=True)
    date = models.DateTimeField(db_index=True, auto_now=True)
    is_fake_test_data = models.BooleanField(default=False)

    def human_vote_type(self):
        human_vote_type = None
        for vote_name, vote_id in Vote.VOTE_TYPE_MAP.items():
            if self.type == vote_id:
                human_vote_type = vote_name

        return human_vote_type

    def __unicode__(self):
        return u"Vote: %s, %s, %s" % (self.post_id, self.author_id, self.get_type_display())


class SubscriptionManager(models.Manager):
    def get_subs(self, post):
        "Returns all suscriptions for a post"
        return self.filter(post=post.root).select_related("user")


class Subscription(models.Model):
    "Connects a post to a user"

    class Meta:
        unique_together = (("user", "post"),)

    # TODO: Remove
    # user = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_("User"), db_index=True, on_delete=models.CASCADE)
    user = models.ForeignKey(User, verbose_name=_("User"), db_index=True, on_delete=models.CASCADE)
    post = models.ForeignKey(Post, verbose_name=_("Post"), related_name="subs", db_index=True, on_delete=models.CASCADE)
    type = models.IntegerField(choices=const.MESSAGING_TYPE_CHOICES, default=const.LOCAL_MESSAGE, db_index=True)
    date = models.DateTimeField(_("Date"), db_index=True)
    is_fake_test_data = models.BooleanField(default=False)

    objects = SubscriptionManager()

    def __unicode__(self):
        return "%s to %s" % (self.user.pubkey, self.post.title)

    def save(self, *args, **kwargs):

        if not self.id:
            # Set the date to current time if missing.
            self.date = self.date or general_util.now()

        super(Subscription, self).save(*args, **kwargs)


    @staticmethod
    def get_sub(post):
        return None

    @staticmethod
    def create(sender, instance, created, *args, **kwargs):
        "Creates a subscription of a user to a post"
        user = instance.author
        root = instance.root
        if Subscription.objects.filter(post=root, user=user).count() == 0:
            sub_type = user.profile.message_prefs
            if sub_type == const.DEFAULT_MESSAGES:
                sub_type = const.EMAIL_MESSAGE if instance.is_toplevel else const.LOCAL_MESSAGE
            sub = Subscription(post=root, user=user, type=sub_type)
            sub.date = general_util.now()
            sub.save()
            # Increase the subscription count of the root.
            Post.objects.filter(pk=root.id).update(subs_count=F('subs_count') + 1)

    @staticmethod
    def finalize_delete(sender, instance, *args, **kwargs):
        # Decrease the subscription count of the post.
        Post.objects.filter(pk=instance.post.root_id).update(subs_count=F('subs_count') - 1)


# Data signals
from django.db.models.signals import post_save, post_delete, m2m_changed

post_save.connect(Post.check_root, sender=Post)
post_save.connect(Subscription.create, sender=Post, dispatch_uid="create_subs")
post_delete.connect(Subscription.finalize_delete, sender=Subscription, dispatch_uid="delete_subs")
m2m_changed.connect(Tag.update_counts, sender=Post.tag_set.through)

