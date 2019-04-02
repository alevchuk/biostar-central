# Generated by Django 2.1.7 on 2019-03-28 00:39

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('lner', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='LightningInvoice',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('pay_req', models.CharField(db_index=True, max_length=255, unique=True, verbose_name='LN Invoice pay_req')),
            ],
        ),
    ]