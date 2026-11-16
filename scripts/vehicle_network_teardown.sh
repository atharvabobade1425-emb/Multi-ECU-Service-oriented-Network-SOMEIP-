#!/bin/bash
# Stops all ECU processes/daemons and removes the virtual vehicle network.
pkill -TERM -f "(vehicle_speed_service|cluster_client|climate_service|central_display).py" 2>/dev/null
sleep 1
pkill -TERM -f "someipyd_ecu.py --config config/netns" 2>/dev/null
sleep 1
for ns in vbus ecu_vehicle ecu_cluster ecu_climate ecu_display; do ip netns del $ns 2>/dev/null; done
rm -f /tmp/someipyd_ecu_*.sock
echo "Virtual vehicle network removed."
