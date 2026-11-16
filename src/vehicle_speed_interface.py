"""
vehicle_speed_interface.py
--------------------------------------------------------------------
SOME/IP interface definition of the VehicleSpeedService
(provided by the Vehicle ECU).

Assignment 1 (retained):
    Method  GetSpeed()          Method ID 0x0001   -> uint16 speed [km/h]
    Event   SpeedChanged        Event  ID 0x8001   Event Group 0x0001

Assignment 2 (added in Task 11):
    Method  GetVehicleState()   Method ID 0x0002   -> uint8 state (0 = STOPPED, 1 = MOVING)
    Event   OverspeedWarning    Event  ID 0x8002   Event Group 0x0002 (speed > 80 km/h)

Both the provider (vehicle_speed_service.py) and every consumer
(cluster_client.py, central_display.py) import this file so that
all ECUs use exactly the same IDs and payload layouts.
--------------------------------------------------------------------
"""
from dataclasses import dataclass

from someipy import Event, EventGroup, Method, ServiceBuilder, TransportLayerProtocol
from someipy.serialization import SomeIpPayload, Uint8, Uint16

# ------------------------------------------------------------------
# Service identification
# ------------------------------------------------------------------
SERVICE_NAME = "VehicleSpeedService"
VEHICLE_SPEED_SERVICE_ID = 0x1234
VEHICLE_SPEED_INSTANCE_ID = 0x5678
VEHICLE_SPEED_MAJOR_VERSION = 1

# ------------------------------------------------------------------
# Assignment 1 elements
# ------------------------------------------------------------------
GET_SPEED_METHOD_ID = 0x0001
SPEED_CHANGED_EVENT_ID = 0x8001
SPEED_EVENTGROUP_ID = 0x0001

# ------------------------------------------------------------------
# Assignment 2 additions (Task 11.1)
# ------------------------------------------------------------------
GET_VEHICLE_STATE_METHOD_ID = 0x0002
OVERSPEED_WARNING_EVENT_ID = 0x8002
OVERSPEED_EVENTGROUP_ID = 0x0002

OVERSPEED_THRESHOLD_KMPH = 80          # warning only when speed > 80 km/h

VEHICLE_STATE_STOPPED = 0
VEHICLE_STATE_MOVING = 1
VEHICLE_STATE_NAMES = {VEHICLE_STATE_STOPPED: "STOPPED", VEHICLE_STATE_MOVING: "MOVING"}

# Network endpoints (all ECUs run on one host -> loopback)
DEFAULT_INTERFACE_IP = "127.0.0.1"
VEHICLE_ECU_PORT = 3000                # provider endpoint of VehicleSpeedService


# ------------------------------------------------------------------
# Payload definitions (serialised big-endian by someipy)
# ------------------------------------------------------------------
@dataclass
class SpeedPayload(SomeIpPayload):
    """uint16 vehicle speed in km/h (GetSpeed response, SpeedChanged, OverspeedWarning)."""
    speed_kmph: Uint16

    def __init__(self, speed_kmph: int = 0):
        self.speed_kmph = Uint16(speed_kmph)


@dataclass
class VehicleStatePayload(SomeIpPayload):
    """uint8 vehicle state: 0 = STOPPED, 1 = MOVING (GetVehicleState response) - Task 11.2."""
    state: Uint8

    def __init__(self, state: int = VEHICLE_STATE_STOPPED):
        self.state = Uint8(state)


def vehicle_state_from_speed(speed_kmph: int) -> int:
    """Task 11.3: 0 km/h -> STOPPED, > 0 km/h -> MOVING."""
    return VEHICLE_STATE_STOPPED if speed_kmph == 0 else VEHICLE_STATE_MOVING


# ------------------------------------------------------------------
# Service element definitions
# ------------------------------------------------------------------
speed_changed_event = Event(id=SPEED_CHANGED_EVENT_ID, protocol=TransportLayerProtocol.UDP)
overspeed_warning_event = Event(id=OVERSPEED_WARNING_EVENT_ID, protocol=TransportLayerProtocol.UDP)

speed_eventgroup = EventGroup(id=SPEED_EVENTGROUP_ID, events=[speed_changed_event])
overspeed_eventgroup = EventGroup(id=OVERSPEED_EVENTGROUP_ID, events=[overspeed_warning_event])


def build_vehicle_speed_service(get_speed_handler=None, get_vehicle_state_handler=None):
    """Build the VehicleSpeedService description.

    The provider passes its method handlers; consumers call it without
    handlers (they only need the IDs to call methods and subscribe).
    """
    get_speed_method = Method(
        id=GET_SPEED_METHOD_ID,
        protocol=TransportLayerProtocol.UDP,
        method_handler=get_speed_handler,
    )
    get_vehicle_state_method = Method(
        id=GET_VEHICLE_STATE_METHOD_ID,
        protocol=TransportLayerProtocol.UDP,
        method_handler=get_vehicle_state_handler,
    )
    return (
        ServiceBuilder()
        .with_service_id(VEHICLE_SPEED_SERVICE_ID)
        .with_major_version(VEHICLE_SPEED_MAJOR_VERSION)
        .with_method(get_speed_method)
        .with_method(get_vehicle_state_method)
        .with_eventgroup(speed_eventgroup)
        .with_eventgroup(overspeed_eventgroup)
        .build()
    )
