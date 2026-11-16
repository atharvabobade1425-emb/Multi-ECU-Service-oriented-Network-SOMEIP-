"""
cluster_client.py  -  ECU 2: Instrument Cluster ECU (Service Consumer) - Task 12
--------------------------------------------------------------------
Consumes VehicleSpeedService (0x1234 / 0x5678):

  Methods   GetSpeed() 0x0001, GetVehicleState() 0x0002   (request-response)
  Events    SpeedChanged 0x8001      via event group 0x0001 (publish-subscribe)
            OverspeedWarning 0x8002  via event group 0x0002

Client endpoint 127.0.0.1:3002, SOME/IP Client ID 0x0010.

Run (after starting someipyd):   python3 src/cluster_client.py
--------------------------------------------------------------------
"""
import asyncio
import logging
import sys
from datetime import datetime

from someipy import ClientServiceInstance, MessageType, ReturnCode, connect_to_someipy_daemon
from someipy.someipy_logging import set_someipy_log_level

import ecu_common as ecu

from vehicle_speed_interface import (
    DEFAULT_INTERFACE_IP, GET_SPEED_METHOD_ID, GET_VEHICLE_STATE_METHOD_ID,
    OVERSPEED_WARNING_EVENT_ID, SPEED_CHANGED_EVENT_ID, VEHICLE_SPEED_INSTANCE_ID,
    VEHICLE_STATE_NAMES, SpeedPayload, VehicleStatePayload, build_vehicle_speed_service,
    overspeed_eventgroup, speed_eventgroup)

CLUSTER_PORT = 3002
CLUSTER_CLIENT_ID = 0x0010
METHOD_POLL_PERIOD_S = 8.0       # periodic GetSpeed / GetVehicleState calls
SUBSCRIPTION_TTL_S = 5


def log(msg: str) -> None:
    print(f"{datetime.now():%H:%M:%S} [Instrument Cluster] {msg}", flush=True)


class InstrumentCluster:
    def __init__(self, client: ClientServiceInstance):
        self.client = client
        self.available = False

    # ---------------- request-response ----------------
    async def call_get_speed(self) -> None:
        try:
            r = await ecu.call_method(self.client, GET_SPEED_METHOD_ID, b"")
            if r.message_type == MessageType.RESPONSE and r.return_code == ReturnCode.E_OK:
                log(f"GetSpeed() response        -> Vehicle Speed : {SpeedPayload().deserialize(r.payload).speed_kmph.value} km/h")
            else:
                log(f"GetSpeed() returned {r.message_type.name} / {r.return_code.name}")
        except Exception as e:
            log(f"GetSpeed() failed: {e!r}")

    async def call_get_vehicle_state(self) -> None:
        try:
            r = await ecu.call_method(self.client, GET_VEHICLE_STATE_METHOD_ID, b"")
            if r.message_type == MessageType.RESPONSE and r.return_code == ReturnCode.E_OK:
                state = VehicleStatePayload().deserialize(r.payload).state.value
                log(f"GetVehicleState() response -> Vehicle State : {VEHICLE_STATE_NAMES.get(state, state)}")
            else:
                log(f"GetVehicleState() returned {r.message_type.name} / {r.return_code.name}")
        except Exception as e:
            log(f"GetVehicleState() failed: {e!r}")

    # ---------------- publish-subscribe ----------------
    def on_event(self, event_id: int, payload: bytes) -> None:
        speed = SpeedPayload().deserialize(payload).speed_kmph.value
        if event_id == SPEED_CHANGED_EVENT_ID:
            log(f"SpeedChanged notification received (0x{event_id:04X}) -> Vehicle Speed : {speed} km/h")
            if speed == 0:
                # Vehicle has stopped: confirm the state with the GetVehicleState() method
                asyncio.get_running_loop().create_task(self.call_get_vehicle_state())
        elif event_id == OVERSPEED_WARNING_EVENT_ID:
            log(f"!!! OVERSPEED WARNING (0x{event_id:04X}) !!!  Vehicle Speed : {speed} km/h")

    # ---------------- availability (Service Discovery) ----------------
    async def run(self) -> None:
        log("Waiting for VehicleSpeedService 0x1234 / 0x5678 ...")
        last_poll = 0.0
        loop = asyncio.get_running_loop()
        while True:
            now_available = await ecu.is_available(self.client)
            if now_available != self.available:
                self.available = now_available
                if now_available:
                    log("VehicleSpeedService AVAILABLE")
                    await self.call_get_speed()
                    await self.call_get_vehicle_state()
                    last_poll = loop.time()
                else:
                    log("VehicleSpeedService NOT AVAILABLE")
            elif self.available and loop.time() - last_poll >= METHOD_POLL_PERIOD_S:
                await self.call_get_speed()
                await self.call_get_vehicle_state()
                last_poll = loop.time()
            await asyncio.sleep(1.0)


async def main() -> None:
    set_someipy_log_level(logging.WARNING)
    ecu.install_stop_handlers()
    interface_ip = ecu.interface_ip()

    daemon = await ecu.connect_daemon()
    client = ClientServiceInstance(
        daemon=daemon,
        service=build_vehicle_speed_service(),
        instance_id=VEHICLE_SPEED_INSTANCE_ID,
        endpoint_ip=interface_ip,
        endpoint_port=CLUSTER_PORT,
        client_id=CLUSTER_CLIENT_ID,
    )
    cluster = InstrumentCluster(client)
    client.register_callback(cluster.on_event)

    # Subscribe to both event groups; the daemon sends SubscribeEventgroup
    # entries whenever it sees an OfferService for 0x1234.
    client.subscribe_eventgroup(speed_eventgroup, SUBSCRIPTION_TTL_S)
    client.subscribe_eventgroup(overspeed_eventgroup, SUBSCRIPTION_TTL_S)
    log("=" * 60)
    log(f"Instrument Cluster ECU started (client ID 0x{CLUSTER_CLIENT_ID:04X}, endpoint {interface_ip}:{CLUSTER_PORT})")
    log("Subscribed to event groups 0x0001 (SpeedChanged) and 0x0002 (OverspeedWarning)")
    log("=" * 60)

    try:
        await cluster.run()
    except asyncio.CancelledError:
        pass
    finally:
        client.unsubscribe_eventgroup(speed_eventgroup)
        client.unsubscribe_eventgroup(overspeed_eventgroup)
        set_someipy_log_level(logging.CRITICAL)   # hide someipy's harmless "No data received" on disconnect
        await daemon.disconnect_from_daemon()
        log("Stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
