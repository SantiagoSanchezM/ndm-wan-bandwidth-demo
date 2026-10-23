# Far end of one simulated WAN circuit: iperf3 server + SNMP agent,
# with the circuit's capacity and latency applied by tc/netem.
FROM debian:bookworm-slim

RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      iperf3 snmpd iproute2 \
 && rm -rf /var/lib/apt/lists/*

COPY --chmod=755 set-rate entrypoint.sh /usr/local/bin/

EXPOSE 5201/tcp 5201/udp 161/udp
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
