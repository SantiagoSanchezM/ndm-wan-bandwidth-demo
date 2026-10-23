#!/bin/sh
set -e

set-rate "${RATE:-100mbit}" "${DELAY:-10ms}"

# MIBS= : no MIB text files in this slim image; snmpd serves the OIDs regardless.
MIBS= snmpd -f -Lo -C -c /etc/snmp/snmpd.conf -p /run/snmpd.pid &
exec iperf3 --server --port 5201
