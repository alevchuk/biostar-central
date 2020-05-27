#!/bin/bash

cat <<EOF | ./biostar.sh writer-prod shell
from lner.models import LightningNode

l = LightningNode.objects.get(node_name="l1")
l.enabled = True
l.save()
EOF
