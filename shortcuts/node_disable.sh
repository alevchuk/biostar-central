#!/bin/bash

cat <<EOF | ./biostar.sh writer-prod shell
from lner.models import LightningNode

l = LightningNode.objects.get(node_name="bl3")
l.enabled = False
l.save()
EOF
