#!/bin/bash

cat <<EOF | ./biostar.sh writer-$1 shell
from lner.models import LightningNode

print("{}\t{}\t{}".format("Name", "Score", "Ckpt"))
for l in LightningNode.objects.all():
	print("{}\t{}\t{}".format(l.node_name, l.qos_score, l.global_checkpoint))
EOF
