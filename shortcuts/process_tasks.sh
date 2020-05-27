#!/bin/bash -e


# E.g. $ ./process_tasks.sh writer-dev
# runs process tasks, and cleans up all children when exited

./biostar.sh $1 process_tasks &
pid=$!

echo "Pid $pid"

trap cleanup EXIT

descendent_pids() {
    pids=$(pgrep -P $1)
    echo $pids
    for pid in $pids; do
        descendent_pids $pid
    done
}

function cleanup() {
        echo "Cleaning up pid $pid"

        descendants="$(descendent_pids $pid)"

        for i in $descendants; do
                kill $i
        done

        sleep 2

        for i in $descendants; do
                kill -9 $i 2> /dev/null
        done
}

while :; do
        sleep 1
done
