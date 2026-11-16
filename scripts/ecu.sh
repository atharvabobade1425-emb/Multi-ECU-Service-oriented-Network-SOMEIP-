#!/bin/bash
# =====================================================================
# ecu.sh - start one virtual ECU (its own daemon + application) in the
# virtual vehicle network. Use one terminal per ECU, e.g.:
#
#   Terminal 1:  sudo scripts/ecu.sh vehicle     # Vehicle ECU
#   Terminal 2:  sudo scripts/ecu.sh cluster     # Instrument Cluster ECU
#   Terminal 3:  sudo scripts/ecu.sh climate     # Climate ECU
#   Terminal 4:  sudo scripts/ecu.sh display     # Central Display ECU
#
# Ctrl+C stops the application (StopOffer / unsubscribe), then its daemon.
# =====================================================================
cd "$(dirname "$0")/.."
case "$1" in
    vehicle) APP=vehicle_speed_service.py; HOST=10 ;;
    cluster) APP=cluster_client.py;        HOST=20 ;;
    climate) APP=climate_service.py;       HOST=30 ;;
    display) APP=central_display.py;       HOST=40 ;;
    *) echo "usage: $0 vehicle|cluster|climate|display [app args]"; exit 1 ;;
esac
NAME=$1; shift
NS=ecu_$NAME
SOCK=/tmp/someipyd_$NS.sock
CFG=config/netns/$NAME.json

# start this ECU's daemon if it is not running yet
if ! pgrep -f "someipyd_ecu.py --config $CFG" >/dev/null; then
    rm -f $SOCK
    ip netns exec $NS python3 -u scripts/someipyd_ecu.py --config $CFG >> logs/daemon_$NAME.log 2>&1 &
    until [ -S $SOCK ]; do sleep 0.2; done
fi

cd src
exec ip netns exec $NS env ECU_IP=192.168.50.$HOST SOMEIPY_SOCKET=$SOCK python3 -u $APP "$@"
