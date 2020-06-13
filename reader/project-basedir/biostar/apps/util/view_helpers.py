from django.conf import settings
from django import shortcuts
from django.core.urlresolvers import reverse

from biostar.apps.util import ln
from biostar.apps.posts.models import Post

from common import json_util
from common.log import logger


def gen_invoice(publish_url, memo, node_id):
    context = {}

    nodes_list = ln.get_nodes_list()

    if len(nodes_list) == 0:
        raise ln.LNUtilError("No nodes found")

    if not node_id:
        node_with_top_score = nodes_list[0]
        for node in nodes_list:
            if node["qos_score"] > node_with_top_score["qos_score"]:
                node_with_top_score = node

        node_id = node_with_top_score["id"]
    else:
        node_id = int(node_id)

    context["node_id"] = str(node_id)

    # Lookup the node name
    node_name = "Unknown"
    list_pos = 0
    for pos, n in enumerate(nodes_list):
        if n["id"] == node_id:
            node_name = n["node_name"]
            list_pos = pos

    context["node_name"] = node_name

    next_node_id = nodes_list[(list_pos + 1) % len(nodes_list)]["id"]
    context["next_node_url"] = reverse(
        publish_url,
        kwargs=dict(
            memo=memo,
            node_id=next_node_id
        )
    )
    context["open_channel_url"] = reverse(
        "open-channel-node-selected",
        kwargs=dict(
            node_id=next_node_id
        )
    )

    try:
        details = ln.addinvoice(memo, node_id=node_id)
    except ln.LNUtilError as e:
        logger.exception(e)
        raise


    context['pay_req'] = details['pay_req']

    deserialized_memo = json_util.deserialize_memo(memo)
    context['payment_amount'] = deserialized_memo.get("amt", settings.PAYMENT_AMOUNT)

    return context


def check_invoice(memo, node_id):
    if not memo:
        msg = "memo was not provided"
        logger.error(msg)
        raise ln.LNUtilError(msg)

    # Check payment and redirect if payment is confirmed
    node_id = int(node_id)
    result = ln.check_payment(memo, node_id=node_id)
    checkpoint_value = result["checkpoint_value"]
    conclusion = ln.gen_check_conclusion(checkpoint_value, node_id=node_id, memo=memo)
    if conclusion == ln.CHECKPOINT_DONE:
        post_id = result["performed_action_id"]
        return post_id


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
