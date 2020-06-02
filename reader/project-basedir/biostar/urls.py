from django.conf.urls import include, url
from django.conf import settings

from django.views.generic import TemplateView
from biostar.server import views, ajax, search, moderate, api
from biostar.apps.posts.views import NewAnswer, NewPost, EditPost, PostPreviewView, VotePublishView, PostPublishView, AcceptPreviewView
from biostar.apps.users.views import DigestManager
from biostar.apps.util.views import QRCode, PaymentCheck, ChannelOpenView, TakeCustodyView
from biostar.apps.bounty.views import BountyFormView, BountyPublishView
import biostar.apps.info.views as info

from common.const import MEMO_RE

urlpatterns = [

    # Post listing.
    url(r'^$', views.PostList.as_view(), name="home"),

    # Listing of all tags.
    url(r'^t/$', views.TagList.as_view(), name="tag-list"),

    # Badge view details.
    url(r'^b/(?P<pk>\d+)/$', views.BadgeView.as_view(), name="badge-view"),

    # Badge list details.
    url(r'^b/list/$', views.BadgeList.as_view(), name="badge-list"),

    # Topic listing.
    url(r'^t/(?P<topic>.+)/$', views.PostList.as_view(), name="topic-list"),


    # ==============================
    # LN
    # ==============================

    # QR code image
    url(
        r'^qr/(?P<pay_req>[\w]+)/qr.svg$',
        QRCode.as_view(content_type='image/svg+xml'),
        name="qr-code"
    ),

    # Payment check image
    url(
        r'^payment_check/(?P<node_id>\d+)/(?P<memo>{})/payment_check.svg$'.format(MEMO_RE),
        PaymentCheck.as_view(content_type='image/svg+xml'),
        name="payment-check"
    ),

    # Open channel
    url(r'^x/open/channel/best_node/$'.format(MEMO_RE), ChannelOpenView.as_view(), name="open-channel"),
    url(r'^x/open/channel/(?P<node_id>\d+)/$'.format(MEMO_RE), ChannelOpenView.as_view(), name="open-channel-node-selected"),


    # ==============================
    # User
    # ==============================

    # The list of users.
    url(r'^user/list/$', views.UserList.as_view(), name="user-list"),

    # User details.
    url(r'^u/(?P<pk>\d+)/$', views.UserDetails.as_view(), name="user-details"),

    # User details.
    url(r'^u/edit/(?P<pk>\d+)/$', views.EditUser.as_view(), name="user-edit"),


    # ==============================
    # Post
    # ==============================

    # Post details.
    # NOTICE: just the domain name followed by a forward slash and a number
    url(r'^(?P<pk>\d+)/$', views.PostDetails.as_view(), name="post-details"),

    # New post / answer / comment
    url(r'^x/new/post/$', views.NewPost.as_view(), name="new-post"),
    url(r'^x/new/answer/(?P<pid>\d+)/$', views.NewAnswer.as_view(post_type="answer"), name="new-answer"),
    url(r'^x/new/comment/(?P<pid>\d+)/$', views.NewAnswer.as_view(post_type="comment"), name="new-comment"),
    url(r'^x/new/bounty/(?P<pid>\d+)/$', BountyFormView.as_view(), name="bounty-form"),

    # Preview
    url(r'^x/preview/new/(?P<memo>{})/$'.format(MEMO_RE), PostPreviewView.as_view(), name="post-preview"),
    url(r'^x/preview/edit/(?P<memo>{})/$'.format(MEMO_RE), views.NewPost.as_view(), name="post-preview-edit"),
    url(r'^x/preview/accept/best_node/(?P<memo>{})/$'.format(MEMO_RE), AcceptPreviewView.as_view(), name="accept-preview"),
    url(r'^x/preview/accept/(?P<node_id>\d+)/(?P<memo>{})/$'.format(MEMO_RE), AcceptPreviewView.as_view(), name="accept-preview-node-selected"),

    # Publish (QR code Invoice)
    url(r'^x/publish/post/best_node/(?P<memo>{})/$'.format(MEMO_RE), PostPublishView.as_view(), name="post-publish"),
    url(r'^x/publish/post/(?P<node_id>\d+)/(?P<memo>{})/$'.format(MEMO_RE), PostPublishView.as_view(), name="post-publish-node-selected"),

    url(r'^x/publish/vote/best_node/(?P<memo>{})/$'.format(MEMO_RE), VotePublishView.as_view(), name="vote-publish"),
    url(r'^x/publish/vote/(?P<node_id>\d+)/(?P<memo>{})/$'.format(MEMO_RE), VotePublishView.as_view(), name="vote-publish-node-selected"),

    url(r'^x/publish/accept/best_node/(?P<memo>{})/$'.format(MEMO_RE), VotePublishView.as_view(), name="accept-publish"),
    url(r'^x/publish/accept/(?P<node_id>\d+)/(?P<memo>{})/$'.format(MEMO_RE), VotePublishView.as_view(), name="accept-publish-node-selected"),

    url(r'^x/publish/bounty/best_node/(?P<memo>{})/$'.format(MEMO_RE), BountyPublishView.as_view(), name="bounty-publish"),
    url(r'^x/publish/bounty/(?P<node_id>\d+)/(?P<memo>{})/$'.format(MEMO_RE), BountyPublishView.as_view(), name="bounty-publish-node-selected"),

    # Take Custody
    url(r'^x/take/custody/best_node/(?P<award_id>\d+)/$', TakeCustodyView.as_view(), name="take-custody"),
    url(r'^x/take/custody/(?P<node_id>\d+)/(?P<award_id>\d+)/$', TakeCustodyView.as_view(), name="take-custody-node-selected"),

    # # Edit an existing post. (Not implemented)
    # url(r'^x/edit/(?P<pk>\d+)/$', EditPost.as_view(), name="post-edit"),

    # # ==============================
    # # Moderator
    # # ==============================

    # # Produces the moderator panel.
    # url(r'^local/moderate/post/(?P<pk>\d+)/$', moderate.PostModeration.as_view(), name="post-moderation"),

    # # Produces the moderator panel.
    # url(r'^local/moderate/user/(?P<pk>\d+)/$', moderate.UserModeration.as_view(), name="user-moderation"),


    # ==============================
    # Vote
    # ==============================

    # Search the body.
    url(r'^local/search/page/', search.Search.as_view(), name="search-page"),

    # Search the titles.
    url(r'^local/search/title/', search.search_title, name="search-title"),

     # Returns suggested tags
    url(r'^local/search/tags/', search.suggest_tags, name="suggest-tags"),

    # Local robots.txt.
    url(r'^robots\.txt$', TemplateView.as_view(template_name="robots.txt", content_type='text/plain'), name='robots'),

]

# Adding the sitemap.
urlpatterns += [
    url(r'^sitemap\.xml$', 'django.contrib.sitemaps.views.sitemap', {'sitemaps': search.sitemaps})
]

from biostar.server.feeds import LatestFeed, TagFeed, UserFeed, PostFeed, PostTypeFeed

# Adding the RSS related urls.
urlpatterns += [

    # RSS feeds
    url(r'^feeds/latest/$', LatestFeed(), name='latest-feed'),

    url(r'^feeds/tag/(?P<text>[\w\-_\+!]+)/$', TagFeed(), name='tag-feed'),
    url(r'^feeds/user/(?P<text>[\w\-_\+!]+)/$', UserFeed(), name='user-feed'),
    url(r'^feeds/post/(?P<text>[\w\-_\+!]+)/$', PostFeed(), name='post-feed' ),
    url(r'^feeds/type/(?P<text>[\w\-_\+!]+)/$', PostTypeFeed(), name='post-type'),
]

urlpatterns += [
    url(r'^info/faq/$', info.FaqView.as_view(), name='info-faq'),
    url(r'^info/policy/$', info.PolicyView.as_view(), name='info-policy'),
    url(r'^info/about/$', info.AboutView.as_view(), name='info-about'),
    url(r'^info/rss/$', info.RSSView.as_view(), name='info-rss'),

    # url(r'^info/help/$', views.InfoHelpView.as_view(), name='info-help'),
]

# This is used only for the debug toolbar
if settings.DEBUG:
    import debug_toolbar

    urlpatterns += [
        url(r'^__debug__/', include(debug_toolbar.urls)),
    ]
