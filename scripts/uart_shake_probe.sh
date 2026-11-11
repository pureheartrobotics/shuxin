#!/system/bin/sh
stty -F /dev/ttyS7 115200 raw -echo -ixon -ixoff cs8
timeout 2 cat /dev/ttyS7 &
reader=$!
sleep 0.3
printf 'SHAKE\n' > /dev/ttyS7
printf 'HEAD 0 90\n' > /dev/ttyS7
sleep 1.5
kill $reader 2>/dev/null
wait $reader 2>/dev/null
echo
echo PROBE_DONE
