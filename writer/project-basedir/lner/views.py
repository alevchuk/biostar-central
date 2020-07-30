import time
import re
import json

from django.shortcuts import get_object_or_404
from django.http import Http404
from django.conf import settings
from django.db.models import Max

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework import viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework import permissions
from rest_framework import mixins

from lner.models import LightningNode
from lner.models import Invoice
from lner.models import InvoiceRequest
from lner.models import VerifyMessageResult
from lner.models import PayAwardResult

from bounty.models import Bounty, BountyAward

from lner import lnclient
from lner.serializers import LightningNodeSerializer
from lner.serializers import InvoiceSerializer
from lner.serializers import InvoiceRequestSerializer
from lner.serializers import CheckPaymentSerializer
from lner.serializers import VerifyMessageResponseSerializer
from lner.serializers import PayAwardResponseSerializer

from common import log
from common import validators
from common import json_util

from common.const import MEMO_RE


logger = log.getLogger("lner.views")


class LightningNodeViewSet(viewsets.ModelViewSet):
    """
    List all available lightning nodes
    """
    queryset = LightningNode.objects.all()
    serializer_class = LightningNodeSerializer


class CreateInvoiceError(Exception):
    pass


class CreateInvoiceViewSet(viewsets.ModelViewSet):
    """
    Create a new lightning invoice
    """
    queryset = []
    serializer_class = InvoiceRequestSerializer

    MAX_RETRIES = 3
    RETRY_SLEEP_SECONDS = 1

    def create(self, request, format=None, retry_addinvoice=False, retry_num=0):
        memo = request.POST["memo"]

        if retry_num >= CreateInvoiceViewSet.MAX_RETRIES:
            raise CreateInvoiceError(
                "Retry count exceeded: {}".format(retry_num)
            )

        node = LightningNode.objects.get(id=request.POST["node_id"])
        request_obj, created = InvoiceRequest.objects.get_or_create(
            lightning_node=node,
            memo=memo
        )

        if created or retry_addinvoice:
            logger.info("New invoice request created: {}".format(request_obj))
            # InvoiceRequest just got created? do:
            #  1. addinvoice RPC to the node
            #  2. create Invoice

            if settings.MOCK_LN_CLIENT:
                invoice_stdout = {}

                invoice_stdout["pay_req"] = "FAKE"
                invoice_stdout["r_hash"] = "FAKE"
                invoice_stdout["node_id"] = node.id

                if len(Invoice.objects.all()) == 0:
                    invoice_stdout["add_index"] = 1
                else:
                    # TODO: Mock multiple nodes. Currently Mock uses Invoice.objects.aggregate which ignores node.
                    invoice_stdout["add_index"] = Invoice.objects.aggregate(Max('add_index'))["add_index__max"] + 1

                serializer = InvoiceSerializer(data=invoice_stdout, many=False)  # re-serialize
                is_valid = serializer.is_valid(raise_exception=False)  # validate data going into the database

                invoice_obj = Invoice(
                    invoice_request=request_obj,
                    lightning_node=node,
                    pay_req=serializer.validated_data.get("pay_req"),
                    r_hash=serializer.validated_data.get("r_hash"),
                    add_index=serializer.validated_data.get("add_index")
                )
                invoice_obj.save()
                return Response(serializer.validated_data)

            else:
                # TODO: surface addinvoice timeout and other exceptions back to the user
                # Bounties can specify amount in the memo
                deserialized_memo = json_util.deserialize_memo(memo)
                command_results = lnclient.addinvoice(
                    memo,
                    node.rpcserver,
                    amt=deserialized_memo.get("amt", settings.PAYMENT_AMOUNT),
                    expiry=settings.INVOICE_EXPIRY,
                )

                if command_results["success"]:
                    # Raise node score
                    if node.qos_score > 0:
                        node.qos_score = 0

                    # precondition: qos_score is always non-positive
                    node.qos_score = node.qos_score / 2
                    node.save()

                    logger.info("Successful addinvoice on the node")

                    try:
                        invoice_stdout = json.loads(command_results["stdouterr"])
                    except Exception as e:
                        msg = "Successful addinvoice yet failed to parse json output"
                        logger.exception(e)
                        logger.error(msg)

                        raise CreateInvoiceError(msg)
                else:
                    logger.info("Failed when trying to run addinvoice on the node")

                    # 1. lower node score
                    till_negative_100 = (node.qos_score + 100)
                    if till_negative_100 < 0:
                        till_negative_100 = 0

                    # precondition: qos_score is always non-positive; till_negative_100 is always non-negative
                    node.qos_score = node.qos_score - (till_negative_100 / 2)
                    node.save()

                    # 2. show error to the user
                    log_msg = "Failed when trying to run addinvoice on the node: failure_type={} failure_msg='{}' stdouterr='{}'".format(
                        command_results["failure_type"],
                        command_results["failure_msg"],
                        command_results["stdouterr"],
                    )
                    user_msg = "Failed when trying to run addinvoice on the node: failure_type={} failure_msg='{}'".format(
                        command_results["failure_type"],
                        command_results["failure_msg"],
                    )
                    logger.error(log_msg)
                    raise CreateInvoiceError(user_msg)

                invoice_stdout["node_id"] = node.id
                if "payment_request" in invoice_stdout:
                    # lncli returns "payment_request" instead of "pay_req", probably since
                    # commit 8f5d78c875b8eca436f7ee2e86e743afee262386 (Dec 20 2019)  build+lncli: default to hex encoding for byte slices
                    invoice_stdout["pay_req"] = invoice_stdout["payment_request"]

                serializer = InvoiceSerializer(data=invoice_stdout, many=False)  # re-serialize
                is_valid = serializer.is_valid(raise_exception=False)  # validate data going into the database

                if not is_valid:
                    msg = "Output of addinvoice was not valid: errors={} stdout={}".format(serializer.errors, invoice_stdout)
                    logger.error(msg)
                    raise CreateInvoiceError(msg)

                invoice_obj = Invoice(
                    invoice_request=request_obj,
                    lightning_node=node,
                    pay_req=serializer.validated_data.get("pay_req"),
                    r_hash=serializer.validated_data.get("r_hash"),
                    add_index=serializer.validated_data.get("add_index")
                )
                logger.info("New invoice created! {}".format(invoice_obj))

                invoice_obj.save()
                logger.info("Saved results of addinvoice to DB")

                return Response(serializer.validated_data)

        else:
            logger.info("Good it already exists: {}".format(request_obj))
            try:
                invoice_obj = Invoice.objects.get(invoice_request=request_obj, lightning_node_id=node.id)
            except Invoice.DoesNotExist:
                logger.info("Re-trying to create new invoice")
                retry_num += 1
                time.sleep(CreateInvoiceViewSet.RETRY_SLEEP_SECONDS)
                return self.create(request, format=format, retry_addinvoice=True, retry_num=retry_num)

            logger.info("Fetched invoice from DB: {}".format(invoice_obj))
            invoice_obj.node_id = node.id
            serializer = InvoiceSerializer(invoice_obj)

            if serializer.is_valid:
                logger.info("Invoice is valid")
            else:
                msg = "Invoice is NOT valid, errors: {}".format(serializer.errors)
                logger.error(msg)
                raise CreateInvoiceError(msg)

            return Response(serializer.data)


class CheckPaymentViewSet(viewsets.ModelViewSet):
    """
    Check invoice to see if payment was settled
    """

    queryset = []
    serializer_class = CheckPaymentSerializer

    def get_queryset(self):
        memo = self.request.query_params.get("memo")
        node_id = self.request.query_params.get("node_id")

        assert re.match(MEMO_RE, memo), "Got invalid memo {}".format(memo)

        invoice_request = get_object_or_404(InvoiceRequest, memo=memo, lightning_node_id=node_id)
        invoice = get_object_or_404(Invoice, invoice_request=invoice_request, lightning_node_id=node_id)

        return [invoice]



class VerifyMessageViewSet(viewsets.ModelViewSet):
    """
    Check message against a signature
    """

    queryset = []
    serializer_class = VerifyMessageResponseSerializer

    def get_queryset(self):
        memo = self.request.query_params.get("memo")
        sig = self.request.query_params.get("sig")

        assert memo is not None, "Missing a required field: memo"
        assert sig is not None, "Missing a required field: sig"

        sig = validators.pre_validate_signature(sig)

        node = LightningNode.objects.filter(enabled=True).order_by("-qos_score").first()

        result_json = lnclient.verifymessage(msg=memo, sig=sig, rpcserver=node.rpcserver, mock=settings.MOCK_LN_CLIENT)
        pubkey = result_json["pubkey"]
        valid = result_json["valid"]

        verify_message_result = VerifyMessageResult(memo=memo, identity_pubkey=pubkey, valid=valid)

        return [verify_message_result]


def payment_fail(msg):
    logger.error(msg)
    return [PayAwardResult(payment_successful=False, failure_message=msg)]


class PayAwardViewSet(viewsets.ModelViewSet):
    """
    Check message against a signature
    """

    queryset = []
    serializer_class = PayAwardResponseSerializer

    def get_queryset(self):
        node_id = self.request.query_params.get("node_id")
        award_id = self.request.query_params.get("award_id")
        invoice = self.request.query_params.get("invoice")
        sig = self.request.query_params.get("sig")

        assert invoice is not None, "Missing a required field: invoice"
        assert sig is not None, "Missing a required field: sig"

        sig = validators.pre_validate_signature(sig)

        node_id = self.request.query_params.get("node_id")
        logger.info("Looking up node id: {}".format(node_id))

        # Lookup node
        node = get_object_or_404(LightningNode.objects, id=node_id)
        if not node.enabled:
            return payment_fail("Node is not enabled, try a different node")

        sig_verify_json = lnclient.verifymessage(msg=invoice, sig=sig, rpcserver=node.rpcserver, mock=settings.MOCK_LN_CLIENT)
        logger.info("Attempting to pay award for: {}".format(sig_verify_json))

        valid = sig_verify_json["valid"]
        sig_pubkey = sig_verify_json["pubkey"]

        if not valid:
            return payment_fail("Signature is invalid")

        # Lookup Award
        award = BountyAward.objects.get(id=award_id)

        # Check award recipient
        award_pubkey = award.post.author.pubkey
        if award_pubkey != sig_pubkey:
            return payment_fail("Incorrect signature, this award will be payed out only to {}".format(award_pubkey))

        # Calculate award amount
        # TODO: put into a shard function get_bounty_sats
        bounty_sats = 0

        bounties_to_pay = []
        for b in Bounty.objects.filter(post_id=award.post.parent.id, is_active=True, is_payed=False):
            bounties_to_pay.append(b)
            bounty_sats += b.amt

        logger.info("Need to pay award in the amount of: {} sat".format(bounty_sats))

        # Decode invoice and lookup amount
        decodepayreq_out = lnclient.decodepayreq(payreq=invoice, rpcserver=node.rpcserver, mock=settings.MOCK_LN_CLIENT)
        if decodepayreq_out["success"] is not True:
            if decodepayreq_out["failure_type"] == "timeout":
                return payment_fail("LND decodepayreq timed out")
            else:
                # TODO: from stdouterr remove anything that looks like an IP address
                # E.g. [lncli] rpc error: code = Unknown desc = caveat "ipaddr 172.1.1.1" not satisfied: macaroon locked to different IP address
                return payment_fail("LND decodepayreq failed. LND error message was: {}".format(decodepayreq_out["stdouterr"]))

        payreq_decoded = json.loads(decodepayreq_out["stdouterr"])

        num_satoshis = payreq_decoded["num_satoshis"]
        num_msat = payreq_decoded["num_msat"]
        logger.info("User requested: num_satoshis={} and num_msat={} ".format(num_satoshis, num_msat))

        if int(bounty_sats) == 0:
            return payment_fail("This bounty has already been payed out")

        # Check invoice amount
        if not settings.MOCK_LN_CLIENT:
            if int(bounty_sats) != int(num_satoshis):
                return payment_fail(
                    (
                        "Invoice num_satoshis amount is incorrect, "
                        "we expect to send you {} sats, yet the invoice says {}"
                    ).format(bounty_sats, num_satoshis)
                )

            if int(bounty_sats) != int(int(num_msat) / 1000):
                return payment_fail(
                    (
                        "Invoice num_satoshis amount is incorrect, "
                        "we expect to send you {} sats, yet your invoice says {} msats which is {} sats"
                    ).format(
                        bounty_sats,
                        num_msat,
                        int(int(num_msat) / 1000)
                    )
                )

        logger.info("Entered critical section")

        # ! TODO (2020-05-19): Check for recent payments on all nodes, in case we crash in the middle of critical section

        logger.info("about to pay")

        pay_result = lnclient.payinvoice(payreq=invoice, rpcserver=node.rpcserver, mock=settings.MOCK_LN_CLIENT)
        logger.info("pay_result: {}".format(pay_result))

        if pay_result["success"] is not True:
            if pay_result["failure_type"] == "timeout":
                return payment_fail("LND payinvoice timed out")
            else:
                # TODO: from stdouterr remove anything that looks like an IP address
                # E.g. [lncli] rpc error: code = Unknown desc = caveat "ipaddr 172.1.1.1" not satisfied: macaroon locked to different IP address
                return payment_fail("LND payinvoice failed. LND error message was: {}".format(pay_result["stdouterr"]))

        logger.info("payed, about to update db")

        for b in bounties_to_pay:
            b.is_payed = True
            b.is_active = False
            b.save()

        logger.info("updated db")

        logger.info("Exited critical section")

        return [PayAwardResult(payment_successful=True)]
