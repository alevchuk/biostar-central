#!/bin/bash -e


# E.g. $ ./process_tasks.sh writer-dev
# runs process tasks, and cleans up all children when exited

$@ &  #  <---------- run the command in the background
ppid=$!

echo "Pid $ppid"

trap cleanup EXIT

descendent_pids() {
    pids=$(pgrep -P $1)
    echo $pids
    for pid in $pids; do
        descendent_pids $pid
    done
}

terminate_descendents(){
   opts=$1

   echo "Cleaning up descendants of pid $ppid"

   descendants="$(descendent_pids $ppid)"
   for i in $descendants; do
           kill $opts $i
   done
}

function cleanup() {
        terminate_descendents
        sleep 2
        terminate_descendents
        sleep 2
        terminate_descendents -9
}

while :; do
        sleep 1
done
