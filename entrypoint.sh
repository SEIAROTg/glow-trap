#!/bin/sh

chronyd -x
/usr/sbin/dhcpd -4 -d -q --no-pid -cf /etc/dhcp/dhcpd.conf &
./main.py
