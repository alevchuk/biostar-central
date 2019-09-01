from django.db import models

class LightningNode(models.Model):
    identity_pubkey = models.CharField(verbose_name='LN Identity Pubkey', db_index=True, max_length=255, unique=True)

class LightningInvoice(models.Model):
	r_hash = models.CharField(verbose_name='LN Invoice r_hash', max_length=255, default="__DEFAULT__")
	pay_req = models.CharField(verbose_name='LN Invoice pay_req', max_length=255)
	add_index = models.IntegerField(verbose_name='LN Invoice add_index', default=-1)
