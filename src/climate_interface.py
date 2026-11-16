"""
climate_interface.py
--------------------------------------------------------------------
SOME/IP interface definition of the ClimateService
(provided by the Climate ECU) - Task 13.

    Service ID 0x2234, Instance ID 0x0001, Major Version 1, UDP

    Method  GetCabinTemperature()    Method ID 0x0001  -> int16 cabin temp [0.1 degC]
    Method  SetTargetTemperature()   Method ID 0x0002  int16 target [0.1 degC]
                                                       -> uint8 status (0 = ACCEPTED,
                                                                         1 = INVALID_TEMPERATURE)
    Event   CabinTemperatureChanged  Event ID  0x8001  Event Group 0x0001 -> int16 [0.1 degC]

Temperatures are fixed-point integers in tenths of a degree:
    240 = 24.0 degC, 245 = 24.5 degC, 160..300 = valid target range.

Note: Method ID 0x0001 and Event ID 0x8001 are also used by
VehicleSpeedService. That is allowed - IDs are only unique *within*
a service, so the Service ID (0x2234 vs 0x1234) must always be read
together with the Method/Event ID.
--------------------------------------------------------------------
"""
from dataclasses import dataclass

from someipy import Event, EventGroup, Method, ServiceBuilder, TransportLayerProtocol
from someipy.serialization import Sint16, SomeIpPayload, Uint8

SERVICE_NAME = "ClimateService"
CLIMATE_SERVICE_ID = 0x2234
CLIMATE_INSTANCE_ID = 0x0001
CLIMATE_MAJOR_VERSION = 1

GET_CABIN_TEMPERATURE_METHOD_ID = 0x0001
SET_TARGET_TEMPERATURE_METHOD_ID = 0x0002
CABIN_TEMPERATURE_CHANGED_EVENT_ID = 0x8001
CABIN_TEMPERATURE_EVENTGROUP_ID = 0x0001

# Valid target range: 16.0 .. 30.0 degC  ->  160 .. 300 (tenths of a degree)
TARGET_TEMPERATURE_MIN = 160
TARGET_TEMPERATURE_MAX = 300

STATUS_ACCEPTED = 0
STATUS_INVALID_TEMPERATURE = 1
STATUS_NAMES = {STATUS_ACCEPTED: "ACCEPTED", STATUS_INVALID_TEMPERATURE: "INVALID_TEMPERATURE"}

DEFAULT_INTERFACE_IP = "127.0.0.1"
CLIMATE_ECU_PORT = 3001               # provider endpoint of ClimateService


def to_celsius(tenths: int) -> float:
    """240 -> 24.0"""
    return tenths / 10.0


# ------------------------------------------------------------------
# Payload definitions
# ------------------------------------------------------------------
@dataclass
class CabinTemperaturePayload(SomeIpPayload):
    """int16 cabin temperature in 0.1 degC (GetCabinTemperature response, CabinTemperatureChanged)."""
    temperature: Sint16

    def __init__(self, temperature: int = 0):
        self.temperature = Sint16(temperature)


@dataclass
class TargetTemperaturePayload(SomeIpPayload):
    """int16 requested target temperature in 0.1 degC (SetTargetTemperature request)."""
    target_temperature: Sint16

    def __init__(self, target_temperature: int = 0):
        self.target_temperature = Sint16(target_temperature)


@dataclass
class SetTargetTemperatureStatusPayload(SomeIpPayload):
    """uint8 status: 0 = ACCEPTED, 1 = INVALID_TEMPERATURE (SetTargetTemperature response)."""
    status: Uint8

    def __init__(self, status: int = STATUS_ACCEPTED):
        self.status = Uint8(status)


# ------------------------------------------------------------------
# Service element definitions
# ------------------------------------------------------------------
cabin_temperature_changed_event = Event(
    id=CABIN_TEMPERATURE_CHANGED_EVENT_ID, protocol=TransportLayerProtocol.UDP
)
cabin_temperature_eventgroup = EventGroup(
    id=CABIN_TEMPERATURE_EVENTGROUP_ID, events=[cabin_temperature_changed_event]
)


def build_climate_service(get_cabin_temperature_handler=None, set_target_temperature_handler=None):
    """Build the ClimateService description (handlers only on the provider side)."""
    return (
        ServiceBuilder()
        .with_service_id(CLIMATE_SERVICE_ID)
        .with_major_version(CLIMATE_MAJOR_VERSION)
        .with_method(Method(id=GET_CABIN_TEMPERATURE_METHOD_ID, protocol=TransportLayerProtocol.UDP,
                            method_handler=get_cabin_temperature_handler))
        .with_method(Method(id=SET_TARGET_TEMPERATURE_METHOD_ID, protocol=TransportLayerProtocol.UDP,
                            method_handler=set_target_temperature_handler))
        .with_eventgroup(cabin_temperature_eventgroup)
        .build()
    )
