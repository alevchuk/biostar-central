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

from django.db.models import Q, F

from rest_framework import serializers
from background_task import background

from common import lnclient
from common.log import logger
from common import validators
from common import json_util
from common import general_util

from posts.models import Post
from posts.models import Vote
from posts.models import Tag
from posts.models import Vote

from users.models import User

from lner.models import LightningNode
from lner.models import Invoice
from lner.models import InvoiceRequest

logger.info("Python version: {}".format(sys.version.replace("\n", " ")))


BETWEEN_NODES_DELAY = 1


def human_time(ts):
    return datetime.utcfromtimestamp(int(ts)).strftime('%Y-%m-%d %H:%M:%S')


def sleep(seconds):
    logger.info("Sleeping for {} seconds".format(seconds))
    time.sleep(seconds)


class CheckpointHelper(object):
    def __init__(self, node, invoice, creation_date):
        self.node = node
        self.invoice = invoice
        self.add_index = invoice.add_index
        self.creation_date = creation_date

        logger.info(
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
            logger.info("Invoice already has this checkpoint {}".format(self))
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
        logger.info(
            (
                "Pre-run took {:.3f} seconds\n"
            ).format(
                processing_wall_time
            )
        )

        return processing_wall_time

    def run_one_node(self, node):
        start_time = time.time()

        invoices_details = lnclient.listinvoices(
            index_offset=node.global_checkpoint,
            rpcserver=node.rpcserver,
            mock=settings.MOCK_LN_CLIENT
        )

        if node not in self.all_invoices_from_db:
            invoice_list_from_db = {}
            logger.info("DB has no invoices for this node")
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

                mock_setteled = (invoice_obj.created + timedelta(seconds=3) < timezone.now())
                creation_unixtime = int(time.mktime(invoice_obj.created.timetuple()))

                invoice_list_from_node.append(
                    {
                        "settled": mock_setteled,
                        "settle_date": str(int(time.time())) if mock_setteled else 0,
                        "state": "SETTLED" if mock_setteled else "OPEN",
                        "memo": invoice_request.memo,
                        "add_index": invoice_obj.add_index,
                        "payment_request": invoice_obj.pay_req,
                        "pay_req": invoice_obj.pay_req,  # Old format
                        "r_hash": invoice_obj.r_hash,
                        "creation_date": str(creation_unixtime),
                        "expiry": str(creation_unixtime + 120)
                    }
                )

        retry_mini_map = {int(invoice['add_index']): False for invoice in invoice_list_from_node}

        one_hour_ago = timezone.now() - timedelta(hours=1)
        recent_invoices = [i.id for i in invoice_list_from_db.values() if i.modified > one_hour_ago]
        if len(recent_invoices) > 0:
            logger.info("Recent invoice_list_from_db was: {}".format(recent_invoices))

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
                logger.info("Got old invoice from listinvoices, skipping... {} is older then retention {}".format(
                    created,
                    settings.INVOICE_RETENTION
                    )
                )
                continue

            add_index_from_node = int(raw_invoice["add_index"])

            invoice = invoice_list_from_db.get(add_index_from_node)

            if invoice is None:
                logger.error("Unknown add_index {}".format(add_index_from_node))
                logger.error("Raw invoice from node was: {}".format(raw_invoice))

                if raw_invoice['state'] == "CANCELED":
                    logger.error("Skipping because invoice is cancelled...")
                    retry_mini_map[add_index_from_node] = False  # advance global checkpoint
                else:
                    retry_mini_map[add_index_from_node] = True  # try again later

                continue

            # Validate
            if invoice.invoice_request.memo != raw_invoice["memo"]:
                logger.error("Memo in DB does not match the one in invoice request: db=({}) invoice_request=({})".format(
                    invoice.invoice_request.memo,
                    raw_invoice["memo"]
                ))

                retry_mini_map[add_index_from_node] = True  # try again later
                continue

            if invoice.pay_req != raw_invoice["payment_request"]:
                logger.error("Payment request does not match the one in invoice request: db=({}) invoice_request=({})".format(
                    invoice.pay_req,
                    raw_invoice["payment_request"]
                ))

                retry_mini_map[add_index_from_node] = True  # try again later
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
                logger.info("Skipping invoice at {}: Not yet settled".format(checkpoint_helper))
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
                    change = settings.PAYMENT_AMOUNT
                    post_id = action_details["post_id"]
                    try:
                        post = Post.objects.get(pk=post_id)
                    except (ObjectDoesNotExist, ValueError):
                        logger.error("Skipping vote. The post for vote does not exist: {}".format(action_details))
                        checkpoint_helper.set_checkpoint("invalid_post")
                        continue

                    user, created = User.objects.get_or_create(pubkey="Unknown")


                    # Only maintain one vote for each user/post pair.
                    votes = Vote.objects.filter(author=user, post=post, type=vote_type)
                    vote = Vote.objects.create(author=user, post=post, type=vote_type)

                    # Update user reputation
                    User.objects.filter(pk=post.author.id).update(score=F('score') + change)

                    # The thread score represents all votes in a thread
                    Post.objects.filter(pk=post.root_id).update(thread_score=F('thread_score') + change)

                    if vote.type == Vote.BOOKMARK:
                        # Apply the vote
                        Post.objects.filter(pk=post.id).update(book_count=F('book_count') + change, vote_count=F('vote_count') + change)
                        Post.objects.filter(pk=post.id).update(subs_count=F('subs_count') + change)
                        Post.objects.filter(pk=post.root_id).update(subs_count=F('subs_count') + change)

                    elif vote_type == Vote.ACCEPT:

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
                            raise Exeption("Un-accepting is not supported")
                    else:
                        Post.objects.filter(pk=post.id).update(vote_count=F('vote_count') + change)

                    # Clear old votes.
                    if votes:
                        votes.delete()

                    checkpoint_helper.set_checkpoint("done", action_type="upvote", action_id=post.id)
                else:
                    logger.error("Invalid action: {}".format(action_details))
                    checkpoint_helper.set_checkpoint("invalid_action")
                    continue
            else:

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
                        logger.error("The post parent does not exist: {}".format(action_details))
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

        logger.info("Processing node {} took {:.3f} seconds".format(node.node_name, processing_wall_time))
        return processing_wall_time


@background(queue='queue-1', remove_existing_tasks=True)
def run_many():
    start_time = time.time()
    runner = Runner()
    total_prerun_processing_times_array = []
    total_run_processing_times_array = []

    num_runs = 10
    for _ in range(num_runs):
        node_list = LightningNode.objects.all()

        prerun_processing_times_array = []
        run_processing_times_array = []

        # initialize checkpoints
        for node in node_list:
            logger.info("--------------------- {} id={} ----------------------------".format(node.node_name, node.id))

            created = (node.global_checkpoint == -1)
            if created:
                logger.info("Global checkpoint does not exist")
                node.global_checkpoint = 0
                node.save()

            # pre-run!
            p = runner.pre_run(node)

            # run
            t = runner.run_one_node(node)

            prerun_processing_times_array.append(p)
            total_prerun_processing_times_array.append(p)

            run_processing_times_array.append(t)
            total_run_processing_times_array.append(t)

            logger.info(
                (
                    "Processed {} invoices from node and {} from db\n\n\n\n\n"
                ).format(
                    runner.invoice_count_from_nodes[node],
                    runner.invoice_count_from_db[node],
                )
            )

            sleep(BETWEEN_NODES_DELAY)

        logger.info("Pre-run Max was {:.3f} seconds".format(max(prerun_processing_times_array)))
        logger.info("Pre-run Avg was {:.3f} seconds".format(sum(prerun_processing_times_array) / len(prerun_processing_times_array)))
        logger.info("Pre-run Min was {:.3f} seconds".format(min(prerun_processing_times_array)))
        logger.info("\n")
        logger.info("Run Max was {:.3f} seconds".format(max(run_processing_times_array)))
        logger.info("Run Avg was {:.3f} seconds".format(sum(run_processing_times_array) / len(run_processing_times_array)))
        logger.info("Run Min was {:.3f} seconds".format(min(run_processing_times_array)))

        logger.info("\n")


    logger.info("\n")
    logger.info("Cumulative pre-run total was {:.3f} seconds".format(sum(prerun_processing_times_array)))
    logger.info("Cumulative pre-run max was {:.3f} seconds".format(max(prerun_processing_times_array)))
    logger.info("Cumulative pre-run avg was {:.3f} seconds".format(sum(prerun_processing_times_array) / len(prerun_processing_times_array)))
    logger.info("Cumulative pre-run min was {:.3f} seconds".format(min(prerun_processing_times_array)))

    logger.info("\n")
    logger.info("Cumulative total was {:.3f} seconds".format(sum(run_processing_times_array)))
    logger.info("Cumulative max was {:.3f} seconds".format(max(run_processing_times_array)))
    logger.info("Cumulative avg was {:.3f} seconds".format(sum(run_processing_times_array) / len(run_processing_times_array)))
    logger.info("Cumulative min was {:.3f} seconds".format(min(run_processing_times_array)))

    logger.info("\n")
    processing_wall_time = time.time() - start_time
    logger.info("Finished {} runs in wall-time of {:.3f} seconds".format(num_runs, processing_wall_time))

    logger.info("\n\n\n\n\n")

# schedule a new task after "repeat" number of seconds
run_many(repeat=1)
