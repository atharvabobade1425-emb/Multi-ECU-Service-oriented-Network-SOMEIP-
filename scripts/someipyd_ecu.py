#!/usr/bin/env python3
"""
someipyd_ecu.py - launches the standard someipy daemon (someipyd) with three
small fixes for someipy 2.1.2 from PyPI (needed when every ECU has its own
daemon, i.e. when subscriptions and events really travel over the network).

Problem (someipy 2.1.2): `someipy.service.Method` defines __eq__ but no
__hash__, so it is unhashable. When a daemon receives a SubscribeEventgroup
over the NETWORK for a service that also has methods, it crashes with
"TypeError: unhashable type: 'Method'" and never sends the SubscribeAck or
any events. (With a single shared daemon on localhost the subscription is
handled internally, so the bug does not appear.)

Fix 1: the same __hash__ that is already on the someipy master branch
(hash of method id + protocol), applied only if missing.
Fix 2: events are sent only to subscribers of their own event group (see below).
Fix 3: the service-TTL checker no longer crashes when a subscription expires (see below).

Usage: identical to someipyd, e.g.  python3 someipyd_ecu.py --config config/netns/vehicle.json
"""
import sys

from someipy import service
from someipy import someipyd

# ---- Fix 1: Method must be hashable (same as someipy master) ----
if getattr(service.Method, "__hash__", None) is None:
    service.Method.__hash__ = lambda self: hash((self.id, self.protocol))

# ---- Fix 2: send an event only to subscribers of ITS event group ----
# someipy 2.1.2 sends every event to every remote subscriber of the service,
# whichever event group they subscribed to. A consumer subscribed to event
# groups 0x0001 and 0x0002 therefore received each SpeedChanged twice, and a
# consumer subscribed only to 0x0001 would also receive OverspeedWarning.
# The original handler is kept; it is just given the subscribers of the
# event group named in the request (EventGroupSubscriber.eventgroup_id).
_original_send_event = someipyd.SomeipDaemon._handle_send_event_request


def _send_event_to_eventgroup_subscribers(self, message, writer_id):
    eventgroup_id = message["eventgroup_id"]
    saved = {}
    for offered_service, subs in self._service_subscribers.items():
        subs.update()                                   # drop expired subscriptions first
        saved[offered_service] = subs._subscribers
        subs._subscribers = [s for s in saved[offered_service] if s.eventgroup_id == eventgroup_id]
    try:
        return _original_send_event(self, message, writer_id)
    finally:
        for offered_service, full_list in saved.items():
            self._service_subscribers[offered_service]._subscribers = full_list


someipyd.SomeipDaemon._handle_send_event_request = _send_event_to_eventgroup_subscribers

# ---- Fix 3: keep the service-TTL checker alive ----
# When an active subscription expires (e.g. its provider stopped), someipy 2.1.2
# logs `subscription.eventgroup_id`, an attribute that does not exist
# (it is subscription.eventgroup.id). The AttributeError kills the TTL checker
# task, so services are never removed again and consumers keep seeing a
# stopped provider as available. Providing the attribute fixes it.
from someipy._internal._daemon.subscription import Subscription  # noqa: E402

if not hasattr(Subscription, "eventgroup_id"):
    Subscription.eventgroup_id = property(lambda self: self.eventgroup.id)

from someipy.someipyd import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
