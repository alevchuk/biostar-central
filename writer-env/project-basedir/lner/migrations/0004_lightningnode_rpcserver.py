# Generated by Django 2.1.7 on 2019-03-30 14:18

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('lner', '0003_auto_20190329_2133'),
    ]

    operations = [
        migrations.AddField(
            model_name='lightningnode',
            name='rpcserver',
            field=models.CharField(default='localhost:10009', max_length=255, verbose_name='host:port of ln daemon'),
        ),
    ]