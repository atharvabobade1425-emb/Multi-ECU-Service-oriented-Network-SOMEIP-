"""
climate_service.py  -  ECU 3: Climate ECU (Service Provider) - Task 14
--------------------------------------------------------------------
Offers ClimateService (0x2234 / 0x0001):

  Methods  GetCabinTemperature()     0x0001  -> int16 cabin temperature [0.1 degC]
           SetTargetTemperature()    0x0002  int16 target -> uint8 status
  Event    CabinTemperatureChanged   0x8001  in event group 0x0001

State kept by the ECU:  current cabin temperature, target temperature.
Validation: target must be 160..300 (16.0..30.0 degC); otherwise the
response is INVALID_TEMPERATURE and the target is NOT changed.

Run (after starting someipyd):   python3 src/climate_service.py
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

from climate_interface import (
    CABIN_TEMPERATURE_CHANGED_EVENT_ID, CABIN_TEMPERATURE_EVENTGROUP_ID, CLIMATE_ECU_PORT,
    CLIMATE_INSTANCE_ID, DEFAULT_INTERFACE_IP, STATUS_ACCEPTED, STATUS_INVALID_TEMPERATURE,
    STATUS_NAMES, TARGET_TEMPERATURE_MAX, TARGET_TEMPERATURE_MIN, CabinTemperaturePayload,
    SetTargetTemperatureStatusPayload, TargetTemperaturePayload, build_climate_service,
    to_celsius)

# Simulated cabin temperature sequence [0.1 degC]: 24.0 -> 26.0 -> 24.0 in 0.5 degC steps
CABIN_PROFILE = [240, 245, 250, 255, 260, 255, 250, 245]
UPDATE_PERIOD_S = 3.0

CONSUMER_NAMES = {3004: "Central Display"}

cabin_temperature = CABIN_PROFILE[0]   # current cabin temperature (0.1 degC)
target_temperature = 220               # current target temperature (22.0 degC)


def log(msg: str) -> None:
    print(f"{datetime.now():%H:%M:%S} [Climate ECU] {msg}", flush=True)


# virtual vehicle network mode: consumers are identified by their ECU IP address
CONSUMER_IPS = {"192.168.50.20": "Instrument Cluster", "192.168.50.40": "Central Display"}


def caller(addr: Tuple[str, int]) -> str:
    name = CONSUMER_IPS.get(addr[0]) or CONSUMER_NAMES.get(addr[1], "unknown consumer")
    return f"{name} ({addr[0]}:{addr[1]})"


def ok_response(payload: bytes) -> MethodResult:
    result = MethodResult()
    result.message_type = MessageType.RESPONSE
    result.return_code = ReturnCode.E_OK       # SOME/IP transport was fine
    result.payload = payload
    return result


# ---------------- method handlers ----------------
async def get_cabin_temperature_handler(input_data: bytes, addr: Tuple[str, int]) -> MethodResult:
    log(f"GetCabinTemperature request from {caller(addr)} -> "
        f"Current Cabin Temperature = {to_celsius(cabin_temperature):.1f} degC ({cabin_temperature}) -> response sent")
    return ok_response(CabinTemperaturePayload(cabin_temperature).serialize())


async def set_target_temperature_handler(input_data: bytes, addr: Tuple[str, int]) -> MethodResult:
    global target_temperature
    try:
        requested = TargetTemperaturePayload().deserialize(input_data).target_temperature.value
    except Exception as e:                      # payload too short / malformed
        log(f"SetTargetTemperature: malformed payload from {caller(addr)} ({e})")
        result = MethodResult()
        result.message_type = MessageType.RESPONSE
        result.return_code = ReturnCode.E_MALFORMED_MESSAGE
        return result

    # Application-level validation (NOT done by SOME/IP itself)
    if TARGET_TEMPERATURE_MIN <= requested <= TARGET_TEMPERATURE_MAX:
        old = target_temperature
        target_temperature = requested
        status = STATUS_ACCEPTED
        detail = f"target {to_celsius(old):.1f} -> {to_celsius(target_temperature):.1f} degC"
    else:
        status = STATUS_INVALID_TEMPERATURE
        detail = (f"outside {to_celsius(TARGET_TEMPERATURE_MIN):.1f}..{to_celsius(TARGET_TEMPERATURE_MAX):.1f} degC, "
                  f"target unchanged at {to_celsius(target_temperature):.1f} degC")

    log(f"SetTargetTemperature({to_celsius(requested):.1f} degC = {requested}) from {caller(addr)} "
        f"-> Status = {STATUS_NAMES[status]} ({status}); {detail}")
    return ok_response(SetTargetTemperatureStatusPayload(status).serialize())


# ---------------- cabin temperature simulation ----------------
async def simulate_cabin_temperature(instance: ServerServiceInstance) -> None:
    global cabin_temperature
    step = 0
    while True:
        await asyncio.sleep(UPDATE_PERIOD_S)
        step += 1
        new_value = CABIN_PROFILE[step % len(CABIN_PROFILE)]
        if new_value != cabin_temperature:
            cabin_temperature = new_value
            instance.send_event(CABIN_TEMPERATURE_EVENTGROUP_ID, CABIN_TEMPERATURE_CHANGED_EVENT_ID,
                                CabinTemperaturePayload(cabin_temperature).serialize())
            log(f"Cabin temperature = {to_celsius(cabin_temperature):.1f} degC ({cabin_temperature}) "
                f"-> CabinTemperatureChanged sent (target {to_celsius(target_temperature):.1f} degC)")


async def main() -> None:
    set_someipy_log_level(logging.WARNING)
    ecu.install_stop_handlers()
    interface_ip = ecu.interface_ip()

    daemon = await ecu.connect_daemon()
    service = build_climate_service(get_cabin_temperature_handler, set_target_temperature_handler)
    instance = ServerServiceInstance(
        daemon=daemon,
        service=service,
        instance_id=CLIMATE_INSTANCE_ID,
        endpoint_ip=interface_ip,
        endpoint_port=CLIMATE_ECU_PORT,
        ttl=5,
        cyclic_offer_delay_ms=2000,
    )

    log("=" * 60)
    log(f"Offering ClimateService 0x{service.id:04X} / instance 0x{CLIMATE_INSTANCE_ID:04X} "
        f"on {interface_ip}:{CLIMATE_ECU_PORT} (UDP)")
    log("Methods: GetCabinTemperature 0x0001, SetTargetTemperature 0x0002 | "
        "Event: CabinTemperatureChanged 0x8001 (EG 0x0001)")
    log(f"Initial state: cabin {to_celsius(cabin_temperature):.1f} degC, target {to_celsius(target_temperature):.1f} degC")
    log("=" * 60)
    await instance.start_offer()

    try:
        await simulate_cabin_temperature(instance)
    except asyncio.CancelledError:
        log("Stop offering ClimateService (StopOffer)")
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
