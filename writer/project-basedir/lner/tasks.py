import logging
import sys
import time
import json

from datetime import datetime
from datetime import timedelta

from django.utils import timezone
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.exceptions import ObjectDoesNotExist

from django.db.models import F

from rest_framework import serializers
from background_task import background

from common.log import logger
from common import validators
from common import json_util
from common import general_util

from posts.models import Post
from posts.models import Vote
from posts.models import Tag
from posts.models import Vote

from users.models import User

from bounty.models import Bounty, BountyAward

from lner import lnclient
from lner.models import LightningNode
from lner.models import Invoice
from lner.models import InvoiceRequest

from prometheus_client import Gauge, start_http_server


logger.info("Python version: {}".format(sys.version.replace("\n", " ")))

METRICS_PORT = 2891
LAST_CHECK_GAUGE = Gauge(
    'check_last_success_unixtime',
    'Last time node was successfully checked',
    ["node_name"]
)

BETWEEN_NODES_DELAY = 1


def human_time(ts):
    return datetime.utcfromtimestamp(int(ts)).strftime('%Y-%m-%d %H:%M:%S')


def sleep(seconds):
    logger.debug("Sleeping for {} seconds".format(seconds))
    time.sleep(seconds)


# TODO: move to shared library
def get_anon_user():
    user, created = User.objects.get_or_create(pubkey="Unknown")
    if created:
        logger.info("This is probably an empty DB! Anonymous user created: {}".format(user))

    return user

# TODO: move to a shared library
def update_deadline(earliest_bounty, new_deadline):
    earliest_bounty.award_time = new_deadline
    earliest_bounty.save()
    logger.info(
        "Updated award time to {} on {}".format(
            earliest_bounty.award_time,
            earliest_bounty,
        )
    )


def award_bounty(question_post):
    """
    Award Preliminary Bounty (actual award happens after timer runs out)

    TODO: instead of earliest_bounty have only 1 bounty active at any given time
        for the feature to add to bounties, create a new bounty add model
    """

    # 1. find all bounties
    b_list = Bounty.objects.filter(post_id=question_post.id, is_active=True).order_by(
        'activation_time'
    )
    logger.debug("{} active bounties found".format(len(b_list)))
    if len(b_list) == 0:
        return

    # 2. find earliest bounty start time
    earliest_bounty = b_list.first()
    logger.debug("earliest_bounty start time is {}".format(earliest_bounty.activation_time))

    # 3. check award time to see if bounty is still in the game
    if earliest_bounty.award_time:
        deadline = earliest_bounty.award_time + settings.AWARD_TIMEDELTA
        if timezone.now() > deadline:
            # TODO: check if CLAIM_TIMEDELTA is passed and make available to the next top answer
            logger.debug("The deadline is already passed, so don't change the winner")
            return
    else:
        logger.info("This bounty has no awards yet")

    # TODO: extract into a shared function
    # 4. find the top voted answer among answers after the bounty start time
    # creation date breaks ties, oldest wins
    a_list = Post.objects.filter(
        parent=question_post.id,
        creation_date__gt=earliest_bounty.activation_time,
    ).exclude(
        author=get_anon_user(),
    ).order_by(
        'vote_count',
        '-creation_date'
    )
    logger.info("{} candidate answers found".format(len(a_list)))
    if len(a_list) == 0:
        return

    top_answer = a_list.last()
    logger.info("Top voted answer is {}".format(top_answer))

    # 5. create or update the award
    new_deadline = timezone.now() + settings.AWARD_TIMEDELTA
    try:
        award = BountyAward.objects.get(bounty=earliest_bounty)
    except BountyAward.DoesNotExist:
        award = BountyAward.objects.create(bounty=earliest_bounty, post=top_answer)
        logger.info("Created new award {}".format(award))

        update_deadline(earliest_bounty, new_deadline)
    else:
        if award.post == top_answer:
            logger.info("Already awarded to this answer")
        else:
            award.post = top_answer
            award.save()
            logger.info("Updated existing award {}".format(award))

            update_deadline(earliest_bounty, new_deadline)


class CheckpointHelper(object):
    def __init__(self, node, invoice, creation_date):
        self.node = node
        self.invoice = invoice
        self.add_index = invoice.add_index
        self.creation_date = creation_date

        logger.debug(
                (
                    "Processing invoice of node={} at add_index={} creation_date={}"
                ).format(
                    self.node.node_name,
                    self.add_index,
                    human_time(self.creation_date)
                )
        )

    def __repr__(self):
        return "node-{}-add-index-{}-value-{}".format(self.node.pk, self.add_index, self.invoice.checkpoint_value)

    def set_checkpoint(self, checkpoint_value, action_type=None, action_id=None):
        if self.invoice.checkpoint_value == checkpoint_value:
            logger.debug("Invoice already has this checkpoint {}".format(self))
        else:
            if action_type and action_id:
                self.invoice.performed_action_type = action_type
                self.invoice.performed_action_id = action_id

            self.invoice.checkpoint_value = checkpoint_value
            self.invoice.save()
            logger.info("Updated checkpoint to {}".format(self))

    def is_checkpointed(self):
        return self.invoice.checkpoint_value != "no_checkpoint"


class Runner(object):
    def __init__(self):
        self.all_invoices_from_db = {}  # Dict[LightningNode, Dict[int, Invoice]]  # where int is add_index

        self.invoice_count_from_db = {}  # Dict[LightningNode, int]]
        self.invoice_count_from_nodes = {}  # Dict[LightningNode, int]]

        self.total_pre_processing_times_array = []
        self.total_run_processing_times_array = []
        self.pre_processing_times_array = []
        self.run_processing_times_array = []

    def reset_timing_stats(self):
        self.pre_processing_times_array = []
        self.run_processing_times_array = []

    def log_timing_stats(self):
        if len(self.pre_processing_times_array) > 0:
            logger.debug("Pre-run Max was {:.3f} seconds".format(max(self.pre_processing_times_array)))
            logger.debug("Pre-run Avg was {:.3f} seconds".format(sum(self.pre_processing_times_array) / len(self.pre_processing_times_array)))
            logger.debug("Pre-run Min was {:.3f} seconds".format(min(self.pre_processing_times_array)))
            logger.debug("\n")

        if len(self.run_processing_times_array) > 0:
            logger.debug("Run Max was {:.3f} seconds".format(max(self.run_processing_times_array)))
            logger.debug("Run Avg was {:.3f} seconds".format(sum(self.run_processing_times_array) / len(self.run_processing_times_array)))
            logger.debug("Run Min was {:.3f} seconds".format(min(self.run_processing_times_array)))
            logger.debug("\n")

    def log_cumulative_timing_stats(self):

        if len(self.total_pre_processing_times_array) > 0:
            logger.info("\n")
            logger.info("Cumulative pre-run total was {:.3f} seconds".format(sum(self.total_pre_processing_times_array)))
            logger.info("Cumulative pre-run max was {:.3f} seconds".format(max(self.total_pre_processing_times_array)))
            logger.info("Cumulative pre-run avg was {:.3f} seconds".format(sum(self.total_pre_processing_times_array) / len(self.total_pre_processing_times_array)))
            logger.info("Cumulative pre-run min was {:.3f} seconds".format(min(self.total_pre_processing_times_array)))

        if len(self.total_run_processing_times_array) > 0:
            logger.info("\n")
            logger.info("Cumulative total was {:.3f} seconds".format(sum(self.total_run_processing_times_array)))
            logger.info("Cumulative max was {:.3f} seconds".format(max(self.total_run_processing_times_array)))
            logger.info("Cumulative avg was {:.3f} seconds".format(sum(self.total_run_processing_times_array) / len(self.total_run_processing_times_array)))
            logger.info("Cumulative min was {:.3f} seconds".format(min(self.total_run_processing_times_array)))

    def pre_run(self, node):
        start_time = time.time()
        self.all_invoices_from_db[node] = {}

        # Delete invoices that are passed retention
        for invoice_obj in Invoice.objects.filter(lightning_node=node, add_index__lte=node.global_checkpoint):
            if invoice_obj.created < timezone.now() - settings.INVOICE_RETENTION:
                logger.info("Deleting invoice {} because it is older then retention {}".format(invoice_obj, settings.INVOICE_RETENTION))
                invoice_request = InvoiceRequest.objects.get(id=invoice_obj.invoice_request.id)
                if invoice_request:
                    invoice_request.delete()  # cascading delete also deletes the invoice
                else:
                    logger.info("There was no invoice request, deleting just the invoice")
                    invoice_obj.delete()

        # Get all invoices:
        # - not checkpointed ones needed for re-checking
        # - checkpointed ones needed for de-duplication
        invoices_from_db = Invoice.objects.filter(lightning_node=node, add_index__gt=node.global_checkpoint)
        self.invoice_count_from_db[node] = len(invoices_from_db)

        # TODO: Handle duplicates (e.g. payments to different nodes), first come first serve
        for invoice_obj in invoices_from_db:
            invoice_request = InvoiceRequest.objects.get(id=invoice_obj.invoice_request.id)
            self.all_invoices_from_db[node][invoice_obj.add_index] = invoice_obj

        processing_wall_time = time.time() - start_time
        logger.debug(
            (
                "Pre-run took {:.3f} seconds\n"
            ).format(
                processing_wall_time
            )
        )

        self.pre_processing_times_array.append(processing_wall_time)
        self.total_pre_processing_times_array.append(processing_wall_time)

    def add_ckpt(self, msg, node):
        return "{} (node_name={}, global_checkpoint={})".format(msg, node.node_name, node.global_checkpoint)

    def run_one_node(self, node):
        start_time = time.time()
        healthy = True

        invoices_details = lnclient.listinvoices(
            index_offset=node.global_checkpoint,
            rpcserver=node.rpcserver,
            mock=settings.MOCK_LN_CLIENT
        )

        if node not in self.all_invoices_from_db:
            invoice_list_from_db = {}
            logger.warning(self.add_ckpt("DB has no invoice entry for this node", node=node))
        else:
            invoice_list_from_db = self.all_invoices_from_db[node]

        # example of invoices_details: {"invoices": [], 'first_index_offset': '5', 'last_index_offset': '72'}
        invoice_list_from_node = invoices_details['invoices']
        self.invoice_count_from_nodes[node] = len(invoice_list_from_node)

        if settings.MOCK_LN_CLIENT:
            # Here the mock pulls invoices from DB Invoice model, while in prod invoices are pulled from the Lightning node
            # 1. Mocked lnclient.listinvoices returns an empty list
            # 2. The web front end adds the InvoiceRequest to the DB before it creates the actual invoices with lnclient.addinvoice
            # 3. Mocked API lnclient.addinvoice simply fakes converting InvoiceRequest to Invoice and saves to DB
            # 4. Here the mocked proces_tasks pulls invoices from DB Invoice model and pretends they came from lnclient.listinvoices
            # 5. After X seconds passed based on Invoice created time, here Mock update the Invoice checkpoint to "done" faking a payment

            invoice_list_from_node = []
            for invoice_obj in Invoice.objects.filter(lightning_node=node, checkpoint_value="no_checkpoint"):
                invoice_request = InvoiceRequest.objects.get(id=invoice_obj.invoice_request.id)
                if invoice_request.lightning_node.id != node.id:
                    continue

                mock_settled = (invoice_obj.created + timedelta(seconds=3) < timezone.now())
                creation_unixtime = int(time.mktime(invoice_obj.created.timetuple()))

                action_details = json_util.deserialize_memo(invoice_request.memo)

                if "amt" not in action_details:
                    logger.error(self.add_ckpt(f"NOT MOCKING because invoice_request does not have 'amt': {action_details}", node=node))
                else:
                    invoice_list_from_node.append(
                        {
                            "settled": mock_settled,
                            "settle_date": str(int(time.time())) if mock_settled else 0,
                            "state": "SETTLED" if mock_settled else "OPEN",
                            "memo": invoice_request.memo,
                            "add_index": invoice_obj.add_index,
                            "payment_request": invoice_obj.pay_req,
                            "pay_req": invoice_obj.pay_req,  # Old format
                            "r_hash": invoice_obj.r_hash,
                            "creation_date": str(creation_unixtime),
                            "expiry": str(creation_unixtime + 120),
                            "amt_paid": int(action_details["amt"]) * 1000,
                        }
                    )

        retry_mini_map = {int(invoice['add_index']): False for invoice in invoice_list_from_node}

        one_hour_ago = timezone.now() - timedelta(hours=1)
        recent_invoices = [i.id for i in invoice_list_from_db.values() if i.modified > one_hour_ago]
        if len(recent_invoices) == 0:
            logger.debug("invoice_list_from_db is empty")
        else:
            logger.debug("Recent invoice_list_from_db was: {}".format(recent_invoices))


        for raw_invoice in invoice_list_from_node:
            # Example of raw_invoice:
            # {
            # 'htlcs': [],
            # 'settled': False,
            # 'add_index': '5',
            # 'value': '1',
            # 'memo': '',
            # 'cltv_expiry': '40', 'description_hash': None, 'route_hints': [],
            # 'r_hash': '+fw...=', 'settle_date': '0', 'private': False, 'expiry': '3600',
            # 'creation_date': '1574459849',
            # 'amt_paid': '0', 'features': {}, 'state': 'OPEN', 'amt_paid_sat': '0',
            # 'value_msat': '1000', 'settle_index': '0',
            # 'amt_paid_msat': '0', 'r_preimage': 'd...=', 'fallback_addr': '',
            # 'payment_request': 'lnbc...'
            # }
            created = general_util.unixtime_to_datetime(int(raw_invoice["creation_date"]))
            if created < general_util.now() - settings.INVOICE_RETENTION:
                logger.debug("Got old invoice from listinvoices, skipping... {} is older then retention {}".format(
                    created,
                    settings.INVOICE_RETENTION
                    )
                )
                continue

            add_index_from_node = int(raw_invoice["add_index"])
            invoice = invoice_list_from_db.get(add_index_from_node)

            if raw_invoice['state'] == "OPEN":
                logger.debug("Skipping invoice because it's still open: {}".format(raw_invoice.get("add_index")))
                if time.time() > int(raw_invoice['creation_date']) + int(raw_invoice['expiry']):
                    logger.info(
                        (
                            "Skipping invoice / advancing global checkpoint "
                            "because it's still open and "
                            "will not try again later, because it's expired, add_index={}, raw_invoice={}"
                        ).format(raw_invoice.get("add_index"), raw_invoice)
                    )
                else:
                    retry_mini_map[add_index_from_node] = True  # try again later

                continue

            if invoice is None:
                logger.debug("Unknown add_index {}".format(add_index_from_node))
                logger.debug("Raw invoice from node was: {}".format(raw_invoice))

                if raw_invoice['state'] == "CANCELED":
                    logger.info("Skipping add_index {} because invoice is canceled...".format(add_index_from_node))
                    retry_mini_map[add_index_from_node] = False  # advance global checkpoint

                elif not raw_invoice['memo'].startswith("{}_".format(settings.FRIENDLY_PREFIX)):
                    logger.info("Skipping add_index {} because this is not for {}_".format(
                        add_index_from_node,
                        settings.FRIENDLY_PREFIX
                    ))
                    retry_mini_map[add_index_from_node] = False  # advance global checkpoint

                else:
                    logger.error(self.add_ckpt(f"Unknown add_index {add_index_from_node} something is fishy, try again later", node=node))
                    retry_mini_map[add_index_from_node] = True  # error, something is fishy, try again later
                    healthy = False

                continue

            # Validate
            if invoice.invoice_request.memo != raw_invoice["memo"]:
                logger.error(
                    self.add_ckpt(
                        "Memo in DB does not match the one in invoice request: db=({}) invoice_request=({})".format(
                            invoice.invoice_request.memo,
                            raw_invoice["memo"]
                        ),
                        node=node
                    )
                )


                retry_mini_map[add_index_from_node] = True  # error, try again later
                healthy = False

                continue

            if invoice.pay_req != raw_invoice["payment_request"]:
                logger.error(self.add_ckpt(
                    "Payment request does not match the one in invoice request: db=({}) invoice_request=({})".format(
                        invoice.pay_req,
                        raw_invoice["payment_request"]
                    ),
                    node=node
                ))

                retry_mini_map[add_index_from_node] = True  # error, try again later
                healthy = False

                continue

            checkpoint_helper = CheckpointHelper(
                node=node,
                invoice=invoice,
                creation_date=raw_invoice["creation_date"]
            )

            if checkpoint_helper.is_checkpointed():
                continue

            if raw_invoice['state'] == 'CANCELED':
                checkpoint_helper.set_checkpoint("canceled")
                continue

            if raw_invoice['settled'] and (raw_invoice['state'] != 'SETTLED' or int(raw_invoice['settle_date']) == 0):
                checkpoint_helper.set_checkpoint("inconsistent")
                continue

            if time.time() > int(raw_invoice['creation_date']) + int(raw_invoice['expiry']):
                checkpoint_helper.set_checkpoint("expired")
                continue

            if not raw_invoice['settled']:
                logger.debug("Skipping invoice at {}: Not yet settled - in some wierd state {} - going to try again later".format(checkpoint_helper, raw_invoice))
                retry_mini_map[checkpoint_helper.add_index] = True  # try again later
                continue

            #
            # Invoice is settled
            #

            logger.info("Processing invoice at {}: SETTLED".format(checkpoint_helper))

            memo = raw_invoice["memo"]
            try:
                action_details = json_util.deserialize_memo(memo)
            except json_util.JsonUtilException:
                checkpoint_helper.set_checkpoint("deserialize_failure")
                continue

            if "amt" not in action_details:
                logger.error(
                    self.add_ckpt(
                        f"SKIPPING PAYED INVOICE. 'amt' is not specified in memo {action_details}",
                        node=node
                    )
                )
                checkpoint_helper.set_checkpoint("memo_invalid")
                continue

            try:
                int(action_details["amt"])
            except Exception:
                logger.error(
                    self.add_ckpt(
                        f"SKIPPING PAYED INVOICE. 'amt' is not an integer in memo {action_details}",
                        node=node
                    )
                )

                checkpoint_helper.set_checkpoint("memo_invalid")
                continue
            else:
                if int(action_details["amt"]) * 1000 != int(raw_invoice["amt_paid"]):
                    logger.error(
                        self.add_ckpt(
                            'SKIPPING PAYED INVOICE. "amt" does not matched what is payed ("amt" was {}, "amt_paid" was {})'.format(
                                int(action_details["amt"]) * 1000,
                                raw_invoice["amt_paid"]
                            ),
                            node=node
                        )
                    )
                    checkpoint_helper.set_checkpoint("memo_invalid")
                    continue

            try:
                validators.validate_memo(action_details)
            except ValidationError as e:
                logger.exception(e)
                checkpoint_helper.set_checkpoint("memo_invalid")
                continue

            action = action_details.get("action")

            if action:
                if action in ["Upvote", "Accept"]:
                    vote_type = Vote.VOTE_TYPE_MAP[action]
                    change = action_details["amt"]
                    post_id = action_details["post_id"]
                    try:
                        post = Post.objects.get(pk=post_id)
                    except (ObjectDoesNotExist, ValueError):
                        logger.error(self.add_ckpt(f"SKIPPING PAYED INVOICE for vote. The post for vote does not exist: {action_details}", node=node))
                        checkpoint_helper.set_checkpoint("invalid_post")
                        continue

                    user = get_anon_user()

                    logger.info("Creating a new vote: author={}, post={}, type={}".format(user, post, vote_type))
                    vote = Vote.objects.create(author=user, post=post, type=vote_type)

                    # Update user reputation
                    # TODO: refactor score logic to be shared with "mark_fake_test_data.py"
                    User.objects.filter(pk=post.author.id).update(score=F('score') + change)

                    # The thread score represents all votes in a thread
                    Post.objects.filter(pk=post.root_id).update(thread_score=F('thread_score') + change)

                    if vote_type == Vote.ACCEPT:
                        if "sig" not in action_details:
                            checkpoint_helper.set_checkpoint("sig_missing")
                            continue

                        sig = action_details.pop("sig")
                        sig = validators.pre_validate_signature(sig)

                        verifymessage_detail = lnclient.verifymessage(
                            msg=json.dumps(action_details, sort_keys=True),
                            sig=sig,
                            rpcserver=node.rpcserver,
                            mock=settings.MOCK_LN_CLIENT
                        )

                        if not verifymessage_detail["valid"]:
                            checkpoint_helper.set_checkpoint("invalid_signiture")
                            continue

                        if verifymessage_detail["pubkey"] != post.parent.author.pubkey:
                            checkpoint_helper.set_checkpoint("signiture_unauthorized")
                            continue

                        if change > 0:
                            # First, un-accept all answers
                            for answer in Post.objects.filter(parent=post.parent, type=Post.ANSWER):
                                if answer.has_accepted:
                                    Post.objects.filter(pk=answer.id).update(vote_count=F('vote_count') - change, has_accepted=False)

                            # There does not seem to be a negation operator for F objects.
                            Post.objects.filter(pk=post.id).update(vote_count=F('vote_count') + change, has_accepted=True)
                            Post.objects.filter(pk=post.root_id).update(has_accepted=True)
                        else:
                            # TODO: change "change". here change is set to payment amount, so does not make sense to be called change
                            # TODO: detect un-accept attempt and raise "Un-accept not yet supported"
                            raise Exeption("Payment amount has to be positive")
                    else:
                        Post.objects.filter(pk=post.id).update(vote_count=F('vote_count') + change)

                        # Upvote on an Answer is the trigger for potential bounty awards
                        if post.type == Post.ANSWER and post.author != get_anon_user():
                            award_bounty(question_post=post.parent)

                    checkpoint_helper.set_checkpoint("done", action_type="upvote", action_id=post.id)

                elif action == "Bounty":
                    valid = True
                    for keyword in ["post_id", "amt"]:
                        if keyword not in action_details:
                            logger.warning(self.add_ckpt(f"Bounty invalid because {keyword} is missing", node=node))
                            valid = False

                    if not valid:
                        logger.warning(self.add_ckpt("Could not start Bounty: bounty_invalid", node=node))
                        checkpoint_helper.set_checkpoint("bounty_invalid")
                        continue

                    post_id = action_details["post_id"]
                    amt = action_details["amt"]

                    try:
                        post_obj = Post.objects.get(pk=post_id)
                    except (ObjectDoesNotExist, ValueError):
                        logger.error(self.add_ckpt(f"Bounty invalid because post {post_id} does not exist", node=node))
                        checkpoint_helper.set_checkpoint("bounty_invalid_post_does_not_exist")
                        continue

                    logger.info("Starting bounty for post {}!".format(post_id))

                    new_b = Bounty(
                        post_id=post_obj,
                        amt=amt,
                        activation_time=timezone.now(),
                    )
                    new_b.save()

                    checkpoint_helper.set_checkpoint("done", action_type="bounty", action_id=post_id)
                else:
                    logger.error(self.add_ckpt(f"Invalid action: {action_details}", node=node))
                    checkpoint_helper.set_checkpoint("invalid_action")
                    continue
            else:
                # Posts do not include the "action" key to save on memo space
                logger.info("Action details {}".format(action_details))

                if "sig" in action_details:
                    sig = action_details.pop("sig")
                    sig = validators.pre_validate_signature(sig)

                    verifymessage_detail = lnclient.verifymessage(
                        msg=json.dumps(action_details, sort_keys=True),
                        sig=sig,
                        rpcserver=node.rpcserver,
                        mock=settings.MOCK_LN_CLIENT
                    )

                    if not verifymessage_detail["valid"]:
                        checkpoint_helper.set_checkpoint("invalid_signiture")
                        continue
                    pubkey = verifymessage_detail["pubkey"]
                else:
                    pubkey = "Unknown"


                if "parent_post_id" in action_details:
                    # Find the parent.
                    try:
                        parent_post_id = int(action_details["parent_post_id"])
                        parent = Post.objects.get(pk=parent_post_id)
                    except (ObjectDoesNotExist, ValueError):
                        logger.error(self.add_ckpt(f"The post parent does not exist: {action_details}", node=node))
                        checkpoint_helper.set_checkpoint("invalid_parent_post")
                        continue

                    title = parent.title
                    tag_val = parent.tag_val
                else:
                    title = action_details["title"]
                    tag_val = action_details["tag_val"]
                    parent = None

                user, created = User.objects.get_or_create(pubkey=pubkey)

                post = Post(
                    author=user,
                    parent=parent,
                    type=action_details["post_type"],
                    title=title,
                    content=action_details["content"],
                    tag_val=tag_val,
                )

                # TODO: Catch failures when post title is duplicate (e.g. another node already saved post)
                post.save()

                # New Answer is the trigger for potential bounty awards
                if post.type == Post.ANSWER and user != get_anon_user():
                    award_bounty(question_post=post.parent)

                # Save tags
                if "tag_val" in action_details:
                    tags = action_details["tag_val"].split(",")
                    for tag in tags:
                        tag_obj, created = Tag.objects.get_or_create(name=tag)
                        if created:
                            logger.info("Created a new tag: {}".format(tag))

                        tag_obj.count += 1
                        post.tag_set.add(tag_obj)

                        tag_obj.save()
                        post.save()

                checkpoint_helper.set_checkpoint("done", action_type="post", action_id=post.id)

        # advance global checkpoint
        new_global_checkpoint = None

        for add_index in sorted(retry_mini_map.keys()):
            retry = retry_mini_map[add_index]
            if retry:
                break
            else:
                logger.info("add_index={} advances global checkpoint".format(add_index))
                new_global_checkpoint = add_index

        if new_global_checkpoint:
            node.global_checkpoint = new_global_checkpoint
            node.save()
            logger.info("Saved new global checkpoint {}".format(new_global_checkpoint))

        processing_wall_time = time.time() - start_time

        if healthy:
            LAST_CHECK_GAUGE.labels(node.node_name).set_to_current_time()

        logger.debug("Processing node {} took {:.3f} seconds".format(node.node_name, processing_wall_time))

        self.run_processing_times_array.append(processing_wall_time)
        self.total_run_processing_times_array.append(processing_wall_time)


def one_node_helper(runner, node):
    created = (node.global_checkpoint == -1)
    if created:
        logger.info("Global checkpoint does not exist")
        node.global_checkpoint = 0
        node.save()

    # pre-run!
    runner.pre_run(node)

    # run
    runner.run_one_node(node)

    logger.debug(
        (
            "Processed {} invoices from node and {} from db\n\n\n\n\n"
        ).format(
            runner.invoice_count_from_nodes[node],
            runner.invoice_count_from_db[node],
        )
    )

@background(queue='queue-1', remove_existing_tasks=True)
def run_many():
    start_time = time.time()
    runner = Runner()

    num_runs = 10
    for _ in range(num_runs):
        node_list = LightningNode.objects.all()

        runner.reset_timing_stats()

        exceptions_per_node = {}
        total_enabled_nodes = 0

        for node in node_list:
            logger.debug("--------------------- {} id={} ----------------------------".format(node.node_name, node.id))

            if not node.enabled:
                logger.debug("Node {} disabled, skipping...".format(node.node_name))
                continue
            else:
                total_enabled_nodes += 1

            try:
                one_node_helper(runner, node)

            except Exception as e:
                logger.warning("Exception in one of the nodes in run_many: {}".format(e))
                exceptions_per_node[node.node_name] = e

            sleep(BETWEEN_NODES_DELAY)

        if total_enabled_nodes == 0:
            logger.error("No nodes enabled")
        elif len(exceptions_per_node) >= total_enabled_nodes:
            logger.error("All nodes has exceptions, e.g. {}".format(exceptions_per_node[node_list[0].node_name]))

        runner.log_timing_stats()

    runner.log_cumulative_timing_stats()

    logger.info("\n")
    processing_wall_time = time.time() - start_time
    logger.info("Finished {} runs in wall-time of {:.3f} seconds".format(num_runs, processing_wall_time))

    logger.info("\n\n\n\n\n")


logger.info("Starting metrics on port {} ...".format(METRICS_PORT))
start_http_server(METRICS_PORT)
logger.info("Metrics server started")

# schedule a new task after "repeat" number of seconds
run_many(repeat=1)
