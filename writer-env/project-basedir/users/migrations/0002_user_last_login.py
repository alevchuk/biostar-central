# Generated by Django 2.1.7 on 2019-03-22 23:34

import datetime
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='last_login',
            field=models.DateTimeField(default=datetime.datetime.now),
        ),
    ]