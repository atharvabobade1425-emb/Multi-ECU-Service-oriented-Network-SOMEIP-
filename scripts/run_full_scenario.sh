#!/bin/bash
# =====================================================================
# run_full_scenario.sh - automated run of Tasks 16-22 in the virtual
# vehicle network, with a complete Wireshark capture.
#
#   Task 17  consumers first -> Vehicle ECU -> Climate ECU (discovery order)
#   Task 18  two consumers of VehicleSpeedService (methods + events)
#   Task 19  Central Display consumes both services
#   Task 20  SetTargetTemperature validation (run by the Central Display)
#   Task 21.1 Climate ECU stopped (Ctrl+C -> StopOffer) and restarted
#   Task 21.2 Vehicle ECU hard failure (process + daemon killed, no StopOffer)
#             and restarted
#   Task 22  full capture -> captures/assignment2-multi-ecu.pcapng
#
# Usage: sudo ./scripts/vehicle_network_setup.sh && sudo ./scripts/run_full_scenario.sh
# Output: captures/assignment2-multi-ecu.pcapng, logs/run/*.log
# =====================================================================
cd "$(dirname "$0")/.."
OUT=logs/run; mkdir -p $OUT captures
rm -f $OUT/*.log logs/daemon_*.log
T0=$(date +%s.%N)
mark() {   # timeline marker
    printf "%s  t=%6.1fs  %s\n" "$(date +%H:%M:%S)" "$(echo "$(date +%s.%N) - $T0" | bc)" "$*" | tee -a $OUT/timeline.log
}
start_ecu() { scripts/ecu.sh "$1" "${@:2}" >> $OUT/$1.log 2>&1 & }
app_pid()  { pgrep -f "$1" | head -1; }

ip netns exec vbus tshark -i br0 -w captures/assignment2-multi-ecu.pcapng -q > /tmp/scenario_tshark.err 2>&1 &
TS=$!; until grep -q Capturing /tmp/scenario_tshark.err; do sleep 0.2; done
mark "Wireshark capture started on vbus/br0"

mark "TASK 17.1  start consumers first: Instrument Cluster ECU + Central Display ECU"
start_ecu cluster; start_ecu display
sleep 8
mark "TASK 17.2  start Vehicle ECU (VehicleSpeedService 0x1234)"
start_ecu vehicle
sleep 12
mark "TASK 17.3  start Climate ECU (ClimateService 0x2234) - Central Display runs Task 20 tests"
start_ecu climate
sleep 34

mark "TASK 21.1  STOP Climate ECU (Ctrl+C / SIGTERM -> StopOffer)"
kill -TERM $(app_pid climate_service.py)
sleep 18
mark "TASK 21.1  RESTART Climate ECU"
start_ecu climate
sleep 20

mark "TASK 21.2  STOP Vehicle ECU - hard failure: application and its daemon killed (no StopOffer)"
kill -KILL $(app_pid vehicle_speed_service.py) $(app_pid "someipyd_ecu.py --config config/netns/vehicle.json")
sleep 18
mark "TASK 21.2  RESTART Vehicle ECU (daemon + application)"
start_ecu vehicle
sleep 30

mark "END  stop all ECUs gracefully"
pkill -TERM -f "(cluster_client|central_display|vehicle_speed_service|climate_service).py"
sleep 3
pkill -TERM -f "someipyd_ecu.py --config config/netns"
sleep 1
kill -INT $TS; wait $TS 2>/dev/null
chmod 644 captures/assignment2-multi-ecu.pcapng
cp logs/daemon_*.log $OUT/ 2>/dev/null
mark "capture saved: captures/assignment2-multi-ecu.pcapng ($(capinfos -c captures/assignment2-multi-ecu.pcapng | awk '/Number/{print $4}') packets)"
