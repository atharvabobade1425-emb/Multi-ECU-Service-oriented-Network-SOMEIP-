"""
ecu_common.py - helpers shared by the consumer ECUs.

Why this exists
---------------
In someipy 2.1.x every application talks to the someipy daemon over ONE
Unix-domain socket, and the replies to FindService queries (used by both
ClientServiceInstance.is_available() and call_method()) are read from a
single queue without a request ID. If one application runs two such
queries concurrently - e.g. the Central Display tracking VehicleSpeedService
and ClimateService in parallel tasks - the answers can be delivered to the
wrong caller (observed during development: ClimateService was reported
AVAILABLE before the Climate ECU had started).

Serialising all daemon queries of one application through a lock removes
the race without changing any SOME/IP behaviour on the network.
"""
import asyncio
import os
import sys

from someipy import ClientServiceInstance, MethodResult, connect_to_someipy_daemon

DEFAULT_INTERFACE_IP = "127.0.0.1"
DEFAULT_DAEMON_SOCKET = "/tmp/someipyd.sock"

_daemon_lock: asyncio.Lock | None = None


def _arg(name: str, env: str, default: str) -> str:
    if name in sys.argv and sys.argv.index(name) + 1 < len(sys.argv):
        return sys.argv[sys.argv.index(name) + 1]
    return os.environ.get(env, default)


def interface_ip() -> str:
    """ECU IP address: --interface_ip <ip> or $ECU_IP, default 127.0.0.1 (localhost mode)."""
    return _arg("--interface_ip", "ECU_IP", DEFAULT_INTERFACE_IP)


async def connect_daemon():
    """Connect to the someipy daemon: --daemon-socket <path> or $SOMEIPY_SOCKET,
    default /tmp/someipyd.sock (one shared daemon in localhost mode)."""
    path = _arg("--daemon-socket", "SOMEIPY_SOCKET", DEFAULT_DAEMON_SOCKET)
    if path == DEFAULT_DAEMON_SOCKET:
        return await connect_to_someipy_daemon()
    return await connect_to_someipy_daemon({"socket_path": path})


def _lock() -> asyncio.Lock:
    global _daemon_lock
    if _daemon_lock is None:
        _daemon_lock = asyncio.Lock()
    return _daemon_lock


async def is_available(client: ClientServiceInstance) -> bool:
    """Thread-safe (task-safe) wrapper around ClientServiceInstance.is_available()."""
    async with _lock():
        return await client.is_available()


METHOD_TIMEOUT_S = 3.0


async def call_method(client: ClientServiceInstance, method_id: int, payload: bytes) -> MethodResult:
    """Task-safe wrapper around ClientServiceInstance.call_method() (request-response).
    someipy waits up to 10 s for a response; a shorter timeout keeps the ECU responsive
    (and its availability tracking running) when the provider has just disappeared."""
    async with _lock():
        return await asyncio.wait_for(client.call_method(method_id, payload), METHOD_TIMEOUT_S)


def install_stop_handlers() -> None:
    """Make Ctrl+C (SIGINT) and SIGTERM stop the ECU gracefully: the running main
    task is cancelled, so providers send StopOffer and consumers unsubscribe."""
    import signal
    loop = asyncio.get_running_loop()
    task = asyncio.current_task()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, task.cancel)
