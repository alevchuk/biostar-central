import os
import markdown
import pyzmail
import random
from datetime import datetime, timedelta

from django.views.generic import DetailView, ListView, TemplateView, UpdateView, View
from django.conf import settings
from django.core.cache import cache
from django.core.cache import cache
from django import shortcuts
from django.http import HttpResponseRedirect
from django.core.paginator import Paginator
from django.http import Http404
from django.core.urlresolvers import reverse
from django.utils.timezone import utc

from . import moderate
from braces.views import LoginRequiredMixin, JSONResponseMixin

from biostar.apps.users import auth
from biostar.apps.users.views import EditUser
from biostar.apps.messages.models import Message
from biostar.apps.users.models import User
from biostar.apps.posts.models import Post, Vote, Tag, Subscription, ReplyToken
from biostar.apps.posts.views import NewPost, NewAnswer, ShortForm
from biostar.apps.badges.models import Badge, Award
from biostar.apps.posts.auth import post_permissions
from biostar.apps.util import ln
from biostar.apps.util.email_reply_parser import EmailReplyParser

from common import general_util
from common import html_util
from common import json_util
from common.const import OrderedDict
from common import const
from common import validators
from common.cli import RunCommandException
from common.log import logger


def abspath(*args):
    """Generates absolute paths"""
    return os.path.abspath(os.path.join(*args))


class BaseListMixin(ListView):
    "Base class for each mixin"
    page_title = "Title"
    paginate_by = settings.PAGINATE_BY

    def get_title(self):
        return self.page_title

    def get_context_data(self, **kwargs):
        context = super(BaseListMixin, self).get_context_data(**kwargs)
        context['page_title'] = self.get_title()

        sort = self.request.GET.get('sort', const.POST_SORT_DEFAULT)
        limit = self.request.GET.get('limit', const.POST_LIMIT_DEFAULT)

        if sort not in const.POST_SORT_MAP:
            logger.warning("No sort in POST_SORT_MAP: '%s' '%s'", const.POST_SORT_INVALID_MSG, self.request)
            sort = const.POST_SORT_DEFAULT

        if limit not in const.POST_LIMIT_MAP:
            logger.warning("No limit in POST_SORT_MAP: '%s' '%s'", const.POST_LIMIT_INVALID_MSG, self.request)
            limit = const.POST_LIMIT_DEFAULT

        context['sort'] = sort
        context['limit'] = limit
        context['q'] = self.request.GET.get('q', '')

        return context


def apply_sort(request, query):
    # Note: the naming here needs to match that in the server_tag.py template tags.
    # Apply sort order
    sort = request.GET.get('sort', const.POST_SORT_DEFAULT)
    field = const.POST_SORT_MAP.get(sort, "-lastedit_date")
    query = query.order_by("-sticky", field)

    # Apply time limit.
    limit = request.GET.get('limit', const.POST_LIMIT_DEFAULT)
    days = const.POST_LIMIT_MAP.get(limit, 0)
    if days:
        delta = general_util.now() - timedelta(days=days)
        query = query.filter(lastedit_date__gt=delta)
    return query


LATEST = "latest"
MYPOSTS, MYTAGS, UNANSWERED, FOLLOWING, BOOKMARKS = "myposts mytags open following bookmarks".split()
POST_TYPES = dict(meta=Post.META_QUESTION)

# Topics that requires authorization
AUTH_TOPIC = set((MYPOSTS, MYTAGS, BOOKMARKS, FOLLOWING))


def posts_by_topic(request, topic):
    "Returns a post query that matches a topic"

    # One letter tags are always uppercase
    topic = Tag.fixcase(topic)

    if topic == MYTAGS:
        # Get the posts that the user wrote.
        # TODO: convert My Tags to Tags Search  'Posts matching the <b><i class="fa fa-tag"></i> Tags Search</b> ')
        #return Post.objects.tag_search(x)
        pass

    if topic == UNANSWERED:
        # Get unanswered posts.
        return Post.objects.top_level().filter(type=Post.QUESTION, reply_count=0)

    if topic in POST_TYPES:
        # A post type.
        return Post.objects.top_level().filter(type=POST_TYPES[topic])

    if topic and topic != LATEST:
        return Post.objects.tag_search(topic)

    # Return latest by default.
    return Post.objects.top_level()


class PostList(BaseListMixin):
    """
    This is the base class for any view that produces a list of posts.
    """
    model = Post
    template_name = "post_list.html"
    context_object_name = "posts"
    paginate_by = settings.PAGINATE_BY
    LATEST = "Latest"

    def __init__(self, *args, **kwds):
        super(PostList, self).__init__(*args, **kwds)
        self.limit = 250
        self.topic = None

    def get_title(self):
        if self.topic:
            return "%s Posts" % self.topic
        else:
            return "Latest Posts"

    def get_queryset(self):
        self.topic = self.kwargs.get("topic", "")

        query = posts_by_topic(self.request, self.topic)
        query = apply_sort(self.request, query)

        # Limit latest topics to a few pages.
        if not self.topic:
            query = query[:settings.SITE_LATEST_POST_LIMIT]
        return query

    def get_context_data(self, **kwargs):
        context = super(PostList, self).get_context_data(**kwargs)
        context['topic'] = self.topic or self.LATEST

        return context


class TagList(BaseListMixin):
    """
    Produces the list of tags
    """
    model = Tag
    page_title = "Tags"
    context_object_name = "tags"
    template_name = "tag_list.html"
    paginate_by = 100

    def get_queryset(self):
        objs = Tag.objects.all().order_by("-count")
        return objs


class VoteList(LoginRequiredMixin, ListView):
    """
    Produces the list of votes
    """
    model = Message
    template_name = "vote_list.html"
    context_object_name = "votes"
    paginate_by = settings.PAGINATE_BY
    topic = "votes"

    def get_queryset(self):
        objs = Vote.objects.select_related("author", "post").order_by('-date')
        return objs

    def get_context_data(self, **kwargs):
        context = super(VoteList, self).get_context_data(**kwargs)
        people = [v.author for v in context[self.context_object_name]]
        random.shuffle(people)
        context['topic'] = self.topic
        context['page_title'] = "Votes"
        context['people'] = people

        return context


class UserList(ListView):
    """
    Base class for the showing user listing.
    """
    model = User
    template_name = "user_list.html"
    context_object_name = "users"
    paginate_by = 60

    def get_queryset(self):
        self.q = self.request.GET.get('q', '')
        self.sort = self.request.GET.get('sort', const.USER_SORT_DEFAULT)
        self.limit = self.request.GET.get('limit', const.POST_LIMIT_DEFAULT)

        if self.sort not in const.USER_SORT_MAP:
            logger.warning("Warning! Invalid sort order! %s", self.request)
            self.sort = const.USER_SORT_DEFAULT

        if self.limit not in const.POST_LIMIT_MAP:
            logger.warning("Warning! Invalid limit applied! %s", self.request)
            self.limit = const.POST_LIMIT_DEFAULT

        # Apply the sort on users
        obj = User.objects.get_users(sort=self.sort, limit=self.limit, q=self.q)
        return obj

    def get_context_data(self, **kwargs):
        context = super(UserList, self).get_context_data(**kwargs)
        context['topic'] = "Users"

        context['sort'] = self.sort
        context['limit'] = self.limit
        context['q'] = self.q
        context['show_lastlogin'] = (self.sort == const.USER_SORT_DEFAULT)
        return context


class BaseDetailMixin(DetailView):
    def get_context_data(self, **kwargs):
        context = super(BaseDetailMixin, self).get_context_data(**kwargs)
        sort = self.request.GET.get('sort', const.POST_SORT_DEFAULT)
        limit = self.request.GET.get('limit', const.POST_LIMIT_DEFAULT)

        context['sort'] = sort
        context['limit'] = limit
        context['q'] = self.request.GET.get('q', '')
        return context


class UserDetails(BaseDetailMixin):
    """
    Renders a user profile.
    """
    model = User
    template_name = "user_details.html"
    context_object_name = "target"

    def get_object(self):
        obj = super(UserDetails, self).get_object()
        obj = auth.user_permissions(request=self.request, target=obj)
        return obj

    def get_context_data(self, **kwargs):
        context = super(UserDetails, self).get_context_data(**kwargs)
        target = context[self.context_object_name]
        #posts = Post.objects.filter(author=target).defer("content").order_by("-creation_date")
        posts = Post.objects.my_posts(target=target)
        paginator = Paginator(posts, 10)
        try:
            page = int(self.request.GET.get("page", 1))
            page_obj = paginator.page(page)
        except Exception, exc:
            logger.error("Invalid page number: %s", self.request)
            page_obj = paginator.page(1)
        context['page_obj'] = page_obj
        context['posts'] = page_obj.object_list
        awards = Award.objects.filter(user=target).select_related("badge", "user").order_by("-date")
        context['awards'] = awards[:25]

        return context


class EditUser(EditUser):
    template_name = "user_edit.html"


class PostDetails(DetailView):
    """
    Shows a thread, top level post and all related content.
    """
    model = Post
    context_object_name = "post"
    template_name = "post_details.html"

    def get(self, *args, **kwargs):
        # This will scroll the page to the right anchor.
        self.object = self.get_object()
        context = self.get_context_data(object=self.object)

        if not self.object.is_toplevel:
            return HttpResponseRedirect(self.object.get_absolute_url())

        return self.render_to_response(context)

    def get_object(self):
        obj = super(PostDetails, self).get_object()

        # Raise 404 if a deleted post is viewed by an anonymous user
        if (obj.status == Post.DELETED):
            raise Http404()

        # Adds the permissions
        obj = post_permissions(request=self.request, post=obj)

        # This will be piggybacked on the main object.
        obj.sub = Subscription.get_sub(post=obj)

        # Bail out if not at top level.
        if not obj.is_toplevel:
            return obj

        # Populate the object to build a tree that contains all posts in the thread.
        # Answers sorted before comments.
        thread = [post_permissions(request=self.request, post=post) for post in Post.objects.get_thread(obj)]

        # Do a little preprocessing.
        answers = [p for p in thread if p.type == Post.ANSWER]

        tree = OrderedDict()
        for post in thread:
            if post.type == Post.COMMENT:
                tree.setdefault(post.parent_id, []).append(post)

        store = {Vote.UP: set(), Vote.BOOKMARK: set()}

        pids = [p.id for p in thread]
        votes = Vote.objects.filter(post_id__in=pids).values_list("post_id", "type")

        for post_id, vote_type in votes:
            store.setdefault(vote_type, set()).add(post_id)

        # Shortcuts to each storage.
        bookmarks = store[Vote.BOOKMARK]
        upvotes = store[Vote.UP]

        # Can the current user accept answers
        can_accept = False

        def decorate(post):
            post.has_bookmark = post.id in bookmarks
            post.has_upvote = post.id in upvotes
            post.can_accept = can_accept or post.has_accepted

        # Add attributes by mutating the objects
        map(decorate, thread + [obj])

        # Additional attributes used during rendering
        obj.tree = tree
        obj.answers = answers

        # Add the more like this field
        post = super(PostDetails, self).get_object()

        return obj

    def get_context_data(self, **kwargs):

        context = super(PostDetails, self).get_context_data(**kwargs)
        context['request'] = self.request
        context['form'] = ShortForm()
        return context


class PostPublishView(TemplateView):
    """
    """

    template_name = "post_publish.html"

    def get_context_data(self, **kwargs):
        context = super(PostPublishView, self).get_context_data(**kwargs)
        node_id = int(context["node_id"])

        nodes_list = ln.get_nodes_list()

        # Lookup the node name
        node_name = "Unknown"
        list_pos = 0
        for pos, n in enumerate(nodes_list):
            if n["id"] == node_id:
                node_name = n["node_name"]
                list_pos = pos


        context["node_name"] = node_name

        next_node_id = nodes_list[(list_pos + 1) % len(nodes_list)]["id"]
        context["next_node_url"] = reverse("post-publish", kwargs=dict(memo=context["memo"], node_id=next_node_id))

        try:
            details = ln.add_invoice(context["memo"], node_id=context["node_id"])
        except RunCommandException as e:
            logger.excetion(e)
            return HttpResponseNotFound(
                "<h1>Command for <b>addinvoice</b> failed or timed-out. "
                "Please refresh this page.</h1>"
            )

        context['pay_req'] = details['pay_req']
        context['payment_amount'] = settings.PAYMENT_AMOUNT

        return context

    def get(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)
        memo = context["memo"]

        # Check payment and redirect if payment is confirmed
        node_id = int(context["node_id"])
        result = ln.check_payment(memo, node_id=node_id)
        checkpoint_value = result["checkpoint_value"]
        conclusion = ln.gen_check_conclusion(checkpoint_value, node_id=node_id, memo=memo)
        if conclusion == ln.CHECKPOINT_DONE:
            post_id = result["performed_action_id"]
            return post_redirect(pid=post_id, request=request, permanent=False)

        return super(PostPublishView, self).get(request, *args, **kwargs)


class RateLimitedNewPost(NewPost):
    "Applies limits to the number of top level posts that can be made"

    def get(self, request, *args, **kwargs):
        if moderate.user_exceeds_limits(request, top_level=True):
            return HttpResponseRedirect("/")
        return super(RateLimitedNewPost, self).get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        if moderate.user_exceeds_limits(request, top_level=True):
            return HttpResponseRedirect("/")
        return super(RateLimitedNewPost, self).post(request, *args, **kwargs)


class RateLimitedNewAnswer(NewAnswer):
    "Applies limits to the number of answers that can be made"

    def get(self, request, *args, **kwargs):
        if moderate.user_exceeds_limits(request):
            return HttpResponseRedirect("/")
        return super(RateLimitedNewAnswer, self).get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        if moderate.user_exceeds_limits(request):
            return HttpResponseRedirect("/")
        return super(RateLimitedNewAnswer, self).post(request, *args, **kwargs)



class BadgeView(BaseDetailMixin):
    model = Badge
    template_name = "badge_details.html"

    def get_context_data(self, **kwargs):
        context = super(BadgeView, self).get_context_data(**kwargs)

        # Get the current badge
        badge = context['badge']

        # Get recent awards related to this badge
        awards = Award.objects.filter(badge_id=badge.id).select_related('user').order_by("-date")[:60]

        context['awards'] = awards

        return context


class BadgeList(BaseListMixin):
    model = Badge
    template_name = "badge_list.html"
    context_object_name = "badges"

    def get_queryset(self):
        qs = super(BadgeList, self).get_queryset()
        qs = qs.order_by('-count')
        return qs

    def get_context_data(self, **kwargs):
        context = super(BadgeList, self).get_context_data(**kwargs)
        return context


from django.http import HttpResponse
from django.utils.encoding import smart_text
import json, StringIO, traceback


def email_handler(request):
    key = request.POST.get("key")
    if key != settings.EMAIL_REPLY_SECRET_KEY:
        data = dict(status="error", msg="key does not match")
    else:
        body = request.POST.get("body")
        body = smart_text(body, errors="ignore")


        # This is for debug only
        #fname = "%s/email-debug.txt" % settings.LIVE_DIR
        #fp = file(fname, "wt")
        #fp.write(body.encode("utf-8"))
        #fp.close()

        try:
            # Parse the incoming email.
            # Emails can be malformed in which case we will force utf8 on them before parsing
            try:
                msg = pyzmail.PyzMessage.factory(body)
            except Exception, exc:
                body = body.encode('utf8', errors='ignore')
                msg = pyzmail.PyzMessage.factory(body)

            # Extract the address from the address tuples.
            address = msg.get_addresses('to')[0][1]

            # Parse the token from the address.
            start, token, rest = address.split('+')

            # Verify that the token exists.
            token = ReplyToken.objects.get(token=token)

            # Find the post that the reply targets
            post, author = token.post, token.user

            # Extract the body of the email.
            part = msg.text_part or msg.html_part
            text = part.get_payload()

            # Remove the reply related content
            if settings.EMAIL_REPLY_REMOVE_QUOTED_TEXT:
                text = EmailReplyParser.parse_reply(text)
            else:
                text = text.decode("utf8", errors='replace')
                text = u"<div class='preformatted'>%s</div>" % text

            # Apply server specific formatting
            text = html_util.parse_html(text)

            # Apply the markdown on the text
            text = markdown.markdown(text)

            # Rate-limit sanity check, potentially a runaway process
            since = html_util.now() - timedelta(days=1)
            if Post.objects.filter(author=author, creation_date__gt=since).count() > settings.MAX_POSTS_TRUSTED_USER:
                raise Exception("too many posts created %s" % author.id)

            # Create the new post.
            post_type = Post.ANSWER if post.is_toplevel else Post.COMMENT
            obj = Post.objects.create(type=post_type, parent=post, content=text, author=author)

            # Delete the token. Disabled for now.
            # Old token should be deleted in the data pruning
            #token.delete()

            # Form the return message.
            data = dict(status="ok", id=obj.id)

        except Exception, exc:
            output = StringIO.StringIO()
            traceback.print_exc(file=output)
            data = dict(status="error", msg=str(output.getvalue()))

    data = json.dumps(data)
    return HttpResponse(data, content_type="application/json")

#
# These views below are here to catch old URLs from the 2009 version of the SE1 site
#
POST_REMAP_FILE = '%s/post-remap.txt' % settings.LIVE_DIR
if os.path.isfile(POST_REMAP_FILE):
    logger.info("loading post remap file %s" % POST_REMAP_FILE)
    REMAP = dict([line.split() for line in file(POST_REMAP_FILE)])
else:
    REMAP = {}


def post_redirect(request, pid, permanent=True):
    """
    Redirect to a post

    Permanent means that the browser will remember the request,
    and will redirect instantly without re-checking with the server.
    It can speed things up for the user, may not be the correct
    thing to do in some cases, and makes debugging much harder.
    """
    try:
        post = Post.objects.get(id=pid)
    except Post.DoesNotExist:
        raise Http404
    return shortcuts.redirect(post.get_absolute_url(), permanent=permanent)


def post_remap_redirect(request, pid):
    "Remap post id and redirect, SE1 ids"
    try:
        nid = REMAP[pid]
        post = Post.objects.get(id=nid)
        return shortcuts.redirect(post.get_absolute_url(), permanent=True)
    except Exception, exc:
        logger.error(request, "Unable to redirect: %s" % exc)
        return shortcuts.redirect("/")


def tag_redirect(request, tag):
    try:
        return shortcuts.redirect("/t/%s/" % tag, permanent=True)
    except Exception, exc:
        logger.error("Unable to redirect: %s, '%s'", exc, request)
        return shortcuts.redirect("/")
