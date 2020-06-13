from django.db import models
from common import validators
from django.conf import settings
from django.utils import timezone


class CustomModel(models.Model):
    created = models.DateTimeField(editable=False)
    modified = models.DateTimeField()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self.id:
            self.created = timezone.now()
        self.modified = timezone.now()
        return super(CustomModel, self).save(*args, **kwargs)


class LightningNode(CustomModel):
    node_name = models.CharField(verbose_name='LN Node Name', db_index=True, max_length=255, unique=True)
    node_key = models.CharField(verbose_name='LN Identity Pubkey', db_index=True, max_length=255, unique=False, default="Unknown")
    rpcserver = models.CharField(verbose_name='host:port of ln daemon', max_length=255, default="localhost:10009")
    global_checkpoint = models.IntegerField(
        verbose_name='add_index of the last global checkpoint',
        default=-1
    )
    qos_score = models.FloatField(
        verbose_name='Higher score means higher quality of service. Expected range is 0.0 to -100.0',
        default=-1
    )
    enabled = models.BooleanField(
        verbose_name="Should this node show up in the Web UI and used in process_tasks?",
        default=True
    )
    is_tor = models.BooleanField(
        verbose_name="Should this node receive open channels through Tor?",
        default=True
    )
    connect_ip = models.CharField(verbose_name='Public IP:port of the target node', max_length=255, default="1.2.3.4:9735")
    connect_tor = models.CharField(verbose_name='Public onion:port of the target node', max_length=255, default="abczyx123.onion:9735")

class InvoiceRequest(CustomModel):
    lightning_node = models.ForeignKey(LightningNode, on_delete=models.CASCADE)
    memo = models.CharField(
        verbose_name='LN Invoice memo',
        max_length=settings.MAX_MEMO_SIZE
    )

class Invoice(CustomModel):
    lightning_node = models.ForeignKey(LightningNode, on_delete=models.CASCADE, default=None)
    invoice_request = models.ForeignKey(InvoiceRequest, null=True, default=None, on_delete=models.CASCADE)
    r_hash = models.CharField(verbose_name='LN Invoice r_hash', max_length=255, default="__DEFAULT__")
    pay_req = models.CharField(verbose_name='LN Invoice pay_req', max_length=settings.MAX_PAYREQ_SIZE)
    add_index = models.IntegerField(verbose_name='LN Invoice add_index', default=-1)
    checkpoint_value =  models.CharField(
        verbose_name='E.g. done, expired, canceled, deserialize_failure, or memo_invalid.',
        max_length=255,
        default="no_checkpoint"
    )
    performed_action_type =  models.CharField(
        verbose_name='E.g. "post"',
        max_length=255,
        default="no_action"
    )
    performed_action_id =  models.IntegerField(verbose_name='E.g. post.id', default=-1)


class VerifyMessageResult(models.Model):
    memo = models.CharField(
        verbose_name='LN Invoice memo',
        max_length=settings.MAX_MEMO_SIZE
    )
    valid = models.BooleanField(verbose_name="Is message valid against it's signature?")
    identity_pubkey = models.CharField(verbose_name='LN Identity Pubkey', max_length=255)

    class Meta:
        managed = False


class PayAwardResult(models.Model):
    payment_successful = models.BooleanField(verbose_name="Is message valid against it's signature?")
    failure_message =  models.CharField(
        verbose_name="The failure message to report back to the user",
        max_length=255,
        default=""
    )

    class Meta:
        managed = False
