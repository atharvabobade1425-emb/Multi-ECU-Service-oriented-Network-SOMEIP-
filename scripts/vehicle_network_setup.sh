#!/bin/bash
# =====================================================================
# vehicle_network_setup.sh - "virtual vehicle network" mode
#
# Creates four virtual ECUs on one Linux PC. Each ECU is a network
# namespace with its own IP address on a shared virtual Ethernet bus
# (Linux bridge), and later runs its OWN someipy daemon:
#
#   ecu_vehicle  192.168.50.10   Vehicle ECU            (VehicleSpeedService provider)
#   ecu_cluster  192.168.50.20   Instrument Cluster ECU (consumer)
#   ecu_climate  192.168.50.30   Climate ECU            (ClimateService provider)
#   ecu_display  192.168.50.40   Central Display ECU    (consumer of both)
#                    \  \  /  /
#                  [ vbus: bridge br0 ]   <- capture point for Wireshark
#
# Why: with ONE shared daemon (localhost mode) someipy delivers events and
# subscriptions to local applications internally, so they never appear in
# Wireshark. With one daemon per ECU every SOME/IP-SD Offer/Subscribe/Ack,
# method call and event notification really crosses the network.
#
# Usage: sudo ./vehicle_network_setup.sh     (undo: sudo ./vehicle_network_teardown.sh)
# =====================================================================
set -e
ECUS="vehicle:10 cluster:20 climate:30 display:40"

for ns in vbus ecu_vehicle ecu_cluster ecu_climate ecu_display; do ip netns del $ns 2>/dev/null || true; done

ip netns add vbus
ip -n vbus link set lo up
ip -n vbus link add br0 type bridge
ip -n vbus link set br0 type bridge mcast_snooping 0 stp_state 0 forward_delay 0
ip -n vbus link set br0 up

i=1
for e in $ECUS; do
    name=${e%%:*}; host=${e##*:}; ns=ecu_$name
    ip netns add $ns
    ip -n $ns link set lo up
    ip link add eth0-$name type veth peer name port$i
    ip link set eth0-$name netns $ns
    ip link set port$i netns vbus
    ip -n $ns link set eth0-$name name eth0
    ip -n $ns link set eth0 address 02:00:00:50:00:$host
    ip -n $ns addr add 192.168.50.$host/24 dev eth0
    ip -n $ns link set eth0 up
    ip -n $ns route add 224.0.0.0/4 dev eth0          # SOME/IP-SD multicast 224.224.224.245
    ip -n vbus link set port$i master br0
    ip -n vbus link set port$i up
    i=$((i+1))
done

echo "Virtual vehicle network ready:"
for e in $ECUS; do name=${e%%:*}; printf "  %-12s " ecu_$name; ip -n ecu_$name -br addr show eth0; done
