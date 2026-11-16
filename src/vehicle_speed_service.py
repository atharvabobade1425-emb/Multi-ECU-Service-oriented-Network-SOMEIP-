"""
vehicle_speed_service.py  -  ECU 1: Vehicle ECU (Service Provider)
--------------------------------------------------------------------
Offers VehicleSpeedService (0x1234 / 0x5678):

  Methods  GetSpeed()          0x0001  (Assignment 1)
           GetVehicleState()   0x0002  (Assignment 2, Task 11.3)
  Events   SpeedChanged        0x8001  in event group 0x0001 (Assignment 1)
           OverspeedWarning    0x8002  in event group 0x0002 (Assignment 2, Task 11.4)

The speed is simulated with a fixed drive profile that passes through
70, 80, 90 and 100 km/h, so the > 80 km/h overspeed rule can be verified.

Run (after starting someipyd):   python3 src/vehicle_speed_service.py
--------------------------------------------------------------------
"""
import asyncio
import logging
import sys
from datetime import datetime
from typing import Tuple

from someipy import (MessageType, MethodResult, ReturnCode, ServerServiceInstance,
                     connect_to_someipy_daemon)
from someipy.someipy_logging import set_someipy_log_level

import ecu_common as ecu

from vehicle_speed_interface import (
    DEFAULT_INTERFACE_IP, OVERSPEED_EVENTGROUP_ID, OVERSPEED_THRESHOLD_KMPH,
    OVERSPEED_WARNING_EVENT_ID, SPEED_CHANGED_EVENT_ID, SPEED_EVENTGROUP_ID,
    VEHICLE_ECU_PORT, VEHICLE_SPEED_INSTANCE_ID, VEHICLE_STATE_NAMES, SpeedPayload,
    VehicleStatePayload, build_vehicle_speed_service, vehicle_state_from_speed)

# Simulated drive cycle [km/h]: start, accelerate past the threshold, brake, stop.
SPEED_PROFILE = [0, 0, 20, 40, 50, 60, 70, 80, 90, 100, 90, 80, 70, 50, 30, 10, 0, 0]
UPDATE_PERIOD_S = 2.0

# Known consumer endpoints - only used to print who called a method
CONSUMER_NAMES = {3002: "Instrument Cluster", 3003: "Central Display"}

current_speed_kmph = 0


def log(msg: str) -> None:
    print(f"{datetime.now():%H:%M:%S} [Vehicle ECU] {msg}", flush=True)


# virtual vehicle network mode: consumers are identified by their ECU IP address
CONSUMER_IPS = {"192.168.50.20": "Instrument Cluster", "192.168.50.40": "Central Display"}


def caller(addr: Tuple[str, int]) -> str:
    name = CONSUMER_IPS.get(addr[0]) or CONSUMER_NAMES.get(addr[1], "unknown consumer")
    return f"{name} ({addr[0]}:{addr[1]})"


# ---------------- method handlers ----------------
async def get_speed_handler(input_data: bytes, addr: Tuple[str, int]) -> MethodResult:
    """GetSpeed(): empty request -> uint16 current speed."""
    log(f"GetSpeed request from {caller(addr)} -> response {current_speed_kmph} km/h")
    result = MethodResult()
    result.message_type = MessageType.RESPONSE
    result.return_code = ReturnCode.E_OK
    result.payload = SpeedPayload(current_speed_kmph).serialize()
    return result


async def get_vehicle_state_handler(input_data: bytes, addr: Tuple[str, int]) -> MethodResult:
    """GetVehicleState(): receive request, read speed, determine state, return uint8."""
    state = vehicle_state_from_speed(current_speed_kmph)
    log(f"GetVehicleState request from {caller(addr)} -> speed {current_speed_kmph} km/h "
        f"-> response {state} ({VEHICLE_STATE_NAMES[state]})")
    result = MethodResult()
    result.message_type = MessageType.RESPONSE
    result.return_code = ReturnCode.E_OK
    result.payload = VehicleStatePayload(state).serialize()
    return result


# ---------------- speed simulation + events ----------------
async def simulate_speed(service_instance: ServerServiceInstance) -> None:
    global current_speed_kmph
    step = 0
    while True:
        new_speed = SPEED_PROFILE[step % len(SPEED_PROFILE)]
        step += 1
        if new_speed != current_speed_kmph:
            current_speed_kmph = new_speed
            payload = SpeedPayload(current_speed_kmph).serialize()

            # 1) SpeedChanged for every simulated speed change
            service_instance.send_event(SPEED_EVENTGROUP_ID, SPEED_CHANGED_EVENT_ID, payload)
            msg = f"Speed = {current_speed_kmph:3d} km/h -> SpeedChanged sent"

            # 2) OverspeedWarning only when speed > 80 km/h
            if current_speed_kmph > OVERSPEED_THRESHOLD_KMPH:
                service_instance.send_event(OVERSPEED_EVENTGROUP_ID, OVERSPEED_WARNING_EVENT_ID, payload)
                msg += ", OverspeedWarning sent"
            else:
                msg += ", OverspeedWarning not generated"
            log(msg)
        else:
            log(f"Speed = {current_speed_kmph:3d} km/h (unchanged, no event)")
        await asyncio.sleep(UPDATE_PERIOD_S)


async def main() -> None:
    set_someipy_log_level(logging.WARNING)
    ecu.install_stop_handlers()
    interface_ip = ecu.interface_ip()

    daemon = await ecu.connect_daemon()
    service = build_vehicle_speed_service(get_speed_handler, get_vehicle_state_handler)
    instance = ServerServiceInstance(
        daemon=daemon,
        service=service,
        instance_id=VEHICLE_SPEED_INSTANCE_ID,
        endpoint_ip=interface_ip,
        endpoint_port=VEHICLE_ECU_PORT,
        ttl=5,
        cyclic_offer_delay_ms=2000,
    )

    log("=" * 60)
    log(f"Offering VehicleSpeedService 0x{service.id:04X} / instance 0x{VEHICLE_SPEED_INSTANCE_ID:04X} "
        f"on {interface_ip}:{VEHICLE_ECU_PORT} (UDP)")
    log("Methods: GetSpeed 0x0001, GetVehicleState 0x0002 | "
        "Events: SpeedChanged 0x8001 (EG 0x0001), OverspeedWarning 0x8002 (EG 0x0002)")
    log("=" * 60)
    await instance.start_offer()

    try:
        await simulate_speed(instance)
    except asyncio.CancelledError:
        log("Stop offering VehicleSpeedService (StopOffer)")
        await instance.stop_offer()
    finally:
        set_someipy_log_level(logging.CRITICAL)   # hide someipy's harmless "No data received" on disconnect
        await daemon.disconnect_from_daemon()
        log("Disconnected from someipy daemon")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
