"""
central_display.py  -  ECU 4: Central Display ECU (Service Consumer) - Task 15
--------------------------------------------------------------------
Consumes TWO services from TWO different providers:

  VehicleSpeedService 0x1234 / 0x5678   (Vehicle ECU)   client endpoint :3003
      GetSpeed(), GetVehicleState(), SpeedChanged, OverspeedWarning
  ClimateService      0x2234 / 0x0001   (Climate ECU)   client endpoint :3004
      GetCabinTemperature(), SetTargetTemperature(), CabinTemperatureChanged

Availability of each service is tracked independently. All values shown
on the display are obtained through SOME/IP (nothing is duplicated locally).

When ClimateService first becomes available the display runs the Task 20
SetTargetTemperature validation tests (220, 160, 300, 100, 350) and then sets
the driver's preferred target (22.0 degC). Disable the tests with --no-tests.

Run (after starting someipyd):   python3 src/central_display.py
--------------------------------------------------------------------
"""
import asyncio
import logging
import sys
from datetime import datetime

from someipy import ClientServiceInstance, MessageType, ReturnCode, connect_to_someipy_daemon
from someipy.someipy_logging import set_someipy_log_level

import ecu_common as ecu

import climate_interface as clim
import vehicle_speed_interface as veh

DISPLAY_CLIENT_ID = 0x0020
VEHICLE_CLIENT_PORT = 3003
CLIMATE_CLIENT_PORT = 3004
SUBSCRIPTION_TTL_S = 5
DASHBOARD_PERIOD_S = 15.0
VALIDATION_TESTS = [            # (Task, encoded value, expected status)
    ("20.1 normal valid", 220, clim.STATUS_ACCEPTED),
    ("20.2 lower boundary", 160, clim.STATUS_ACCEPTED),
    ("20.3 upper boundary", 300, clim.STATUS_ACCEPTED),
    ("20.4 invalid low", 100, clim.STATUS_INVALID_TEMPERATURE),
    ("20.5 invalid high", 350, clim.STATUS_INVALID_TEMPERATURE),
]
DRIVER_TARGET = 220             # preferred target re-applied whenever ClimateService (re)appears


def log(msg: str) -> None:
    print(f"{datetime.now():%H:%M:%S} [Central Display] {msg}", flush=True)


def avail(flag: bool) -> str:
    return "AVAILABLE" if flag else "NOT AVAILABLE"


class CentralDisplay:
    def __init__(self, vehicle: ClientServiceInstance, climate: ClientServiceInstance, run_tests: bool):
        self.vehicle, self.climate = vehicle, climate
        self.vehicle_ok = self.climate_ok = False
        self.speed = self.state = self.cabin = self.target = None
        self.run_tests = run_tests

    # ---------------- dashboard ----------------
    def dashboard(self) -> None:
        speed = f"{self.speed} km/h" if self.speed is not None and self.vehicle_ok else "---"
        state = veh.VEHICLE_STATE_NAMES.get(self.state, "---") if self.vehicle_ok else "---"
        cabin = f"{clim.to_celsius(self.cabin):.1f} degree Celsius" if self.cabin is not None and self.climate_ok else "---"
        target = f"{clim.to_celsius(self.target):.1f} degree Celsius" if self.target is not None and self.climate_ok else "---"
        lines = ["=" * 50, "CENTRAL VEHICLE DISPLAY", "=" * 50,
                 f"VehicleSpeedService : {avail(self.vehicle_ok)}",
                 f"ClimateService      : {avail(self.climate_ok)}", "",
                 f"Vehicle Speed       : {speed}",
                 f"Vehicle State       : {state}", "",
                 f"Cabin Temperature   : {cabin}",
                 f"Target Temperature  : {target}", "=" * 50]
        print("\n".join(f"{datetime.now():%H:%M:%S} [Central Display] {l}" for l in lines), flush=True)

    # ---------------- VehicleSpeedService ----------------
    async def get_speed(self) -> None:
        try:
            r = await ecu.call_method(self.vehicle, veh.GET_SPEED_METHOD_ID, b"")
            if r.message_type == MessageType.RESPONSE and r.return_code == ReturnCode.E_OK:
                self.speed = veh.SpeedPayload().deserialize(r.payload).speed_kmph.value
                log(f"GetSpeed() response -> {self.speed} km/h")
        except Exception as e:
            log(f"GetSpeed() failed: {e!r}")

    async def get_vehicle_state(self) -> None:
        try:
            r = await ecu.call_method(self.vehicle, veh.GET_VEHICLE_STATE_METHOD_ID, b"")
            if r.message_type == MessageType.RESPONSE and r.return_code == ReturnCode.E_OK:
                self.state = veh.VehicleStatePayload().deserialize(r.payload).state.value
                log(f"GetVehicleState() response -> {veh.VEHICLE_STATE_NAMES[self.state]}")
        except Exception as e:
            log(f"GetVehicleState() failed: {e!r}")

    def on_vehicle_event(self, event_id: int, payload: bytes) -> None:
        speed = veh.SpeedPayload().deserialize(payload).speed_kmph.value
        if event_id == veh.SPEED_CHANGED_EVENT_ID:
            self.speed = speed
            log(f"[0x1234/0x8001 SpeedChanged]     Vehicle Speed Updated : {speed} km/h")
            # keep the state consistent with the provider: ask the Vehicle ECU when it may have changed
            if speed == 0 or self.state == veh.VEHICLE_STATE_STOPPED:
                asyncio.get_running_loop().create_task(self.get_vehicle_state())
        elif event_id == veh.OVERSPEED_WARNING_EVENT_ID:
            log(f"[0x1234/0x8002 OverspeedWarning] !!! OVERSPEED WARNING !!! Vehicle Speed : {speed} km/h")

    # ---------------- ClimateService ----------------
    async def get_cabin_temperature(self) -> None:
        try:
            r = await ecu.call_method(self.climate, clim.GET_CABIN_TEMPERATURE_METHOD_ID, b"")
            if r.message_type == MessageType.RESPONSE and r.return_code == ReturnCode.E_OK:
                self.cabin = clim.CabinTemperaturePayload().deserialize(r.payload).temperature.value
                log(f"GetCabinTemperature() response -> {clim.to_celsius(self.cabin):.1f} degC ({self.cabin})")
        except Exception as e:
            log(f"GetCabinTemperature() failed: {e!r}")

    async def set_target_temperature(self, value: int, label: str = "") -> int | None:
        try:
            req = clim.TargetTemperaturePayload(value).serialize()
            r = await ecu.call_method(self.climate, clim.SET_TARGET_TEMPERATURE_METHOD_ID, req)
            if r.message_type == MessageType.RESPONSE and r.return_code == ReturnCode.E_OK:
                status = clim.SetTargetTemperatureStatusPayload().deserialize(r.payload).status.value
                if status == clim.STATUS_ACCEPTED:
                    self.target = value
                log(f"SetTargetTemperature({clim.to_celsius(value):.1f} degC, encoded {value}) {label}-> "
                    f"{clim.STATUS_NAMES.get(status, status)}"
                    + ("" if status == clim.STATUS_ACCEPTED else
                       f" (target stays {clim.to_celsius(self.target):.1f} degC)" if self.target else ""))
                return status
            log(f"SetTargetTemperature({value}) returned {r.message_type.name}/{r.return_code.name}")
        except Exception as e:
            log(f"SetTargetTemperature({value}) failed: {e!r}")
        return None

    async def run_validation_tests(self) -> None:
        log("---- Task 20: SetTargetTemperature validation tests ----")
        passed = 0
        for name, value, expected in VALIDATION_TESTS:
            status = await self.set_target_temperature(value, f"[Test {name}] ")
            ok = status == expected
            passed += ok
            log(f"     expected {clim.STATUS_NAMES[expected]:<19} -> {'PASS' if ok else 'FAIL'}")
            await asyncio.sleep(0.5)
        log(f"---- Validation tests: {passed}/{len(VALIDATION_TESTS)} PASS ----")

    def on_climate_event(self, event_id: int, payload: bytes) -> None:
        if event_id == clim.CABIN_TEMPERATURE_CHANGED_EVENT_ID:
            self.cabin = clim.CabinTemperaturePayload().deserialize(payload).temperature.value
            log(f"[0x2234/0x8001 CabinTemperatureChanged] Cabin Temperature Updated : "
                f"{clim.to_celsius(self.cabin):.1f} degree Celsius")

    # ---------------- independent availability tracking ----------------
    async def track_vehicle(self) -> None:
        while True:
            ok = await ecu.is_available(self.vehicle)
            if ok != self.vehicle_ok:
                self.vehicle_ok = ok
                log(f"VehicleSpeedService : {avail(ok)}   (ClimateService : {avail(self.climate_ok)})")
                if ok:
                    await self.get_speed()
                    await self.get_vehicle_state()
                self.dashboard()
            await asyncio.sleep(1.0)

    async def track_climate(self) -> None:
        tests_done = False
        while True:
            ok = await ecu.is_available(self.climate)
            if ok != self.climate_ok:
                self.climate_ok = ok
                log(f"ClimateService      : {avail(ok)}   (VehicleSpeedService : {avail(self.vehicle_ok)})")
                if ok:
                    await self.get_cabin_temperature()
                    if self.run_tests and not tests_done:
                        await self.run_validation_tests()
                        tests_done = True
                    await self.set_target_temperature(DRIVER_TARGET, "[driver preference] ")
                self.dashboard()
            await asyncio.sleep(1.0)

    async def refresh(self) -> None:
        while True:
            await asyncio.sleep(DASHBOARD_PERIOD_S)
            if self.vehicle_ok:
                await self.get_speed()
                await self.get_vehicle_state()
            if self.climate_ok:
                await self.get_cabin_temperature()
            self.dashboard()


async def main() -> None:
    set_someipy_log_level(logging.WARNING)
    ecu.install_stop_handlers()
    ip = ecu.interface_ip()

    daemon = await ecu.connect_daemon()
    vehicle = ClientServiceInstance(daemon=daemon, service=veh.build_vehicle_speed_service(),
                                    instance_id=veh.VEHICLE_SPEED_INSTANCE_ID, endpoint_ip=ip,
                                    endpoint_port=VEHICLE_CLIENT_PORT, client_id=DISPLAY_CLIENT_ID)
    climate = ClientServiceInstance(daemon=daemon, service=clim.build_climate_service(),
                                    instance_id=clim.CLIMATE_INSTANCE_ID, endpoint_ip=ip,
                                    endpoint_port=CLIMATE_CLIENT_PORT, client_id=DISPLAY_CLIENT_ID)
    display = CentralDisplay(vehicle, climate, run_tests="--no-tests" not in sys.argv)
    vehicle.register_callback(display.on_vehicle_event)
    climate.register_callback(display.on_climate_event)

    vehicle.subscribe_eventgroup(veh.speed_eventgroup, SUBSCRIPTION_TTL_S)
    vehicle.subscribe_eventgroup(veh.overspeed_eventgroup, SUBSCRIPTION_TTL_S)
    climate.subscribe_eventgroup(clim.cabin_temperature_eventgroup, SUBSCRIPTION_TTL_S)

    log(f"Central Display ECU started (client ID 0x{DISPLAY_CLIENT_ID:04X}; endpoints {ip}:{VEHICLE_CLIENT_PORT} "
        f"for 0x1234, {ip}:{CLIMATE_CLIENT_PORT} for 0x2234)")
    log("Subscribed: 0x1234 EG 0x0001 + 0x0002, 0x2234 EG 0x0001")
    display.dashboard()

    try:
        await asyncio.gather(display.track_vehicle(), display.track_climate(), display.refresh())
    except asyncio.CancelledError:
        pass
    finally:
        vehicle.unsubscribe_eventgroup(veh.speed_eventgroup)
        vehicle.unsubscribe_eventgroup(veh.overspeed_eventgroup)
        climate.unsubscribe_eventgroup(clim.cabin_temperature_eventgroup)
        set_someipy_log_level(logging.CRITICAL)   # hide someipy's harmless "No data received" on disconnect
        await daemon.disconnect_from_daemon()
        log("Stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
