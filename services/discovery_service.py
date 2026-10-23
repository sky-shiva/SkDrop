import logging
import socket
import threading
from typing import Optional

from .config import DEVICE_ID, DEVICE_NAME, DEVICE_TYPE, ENABLE_MDNS, PORT, get_local_ip
from .device_service import register_discovered_device

logger = logging.getLogger("skdrop.discovery")

SERVICE_TYPE = "_skdrop._tcp.local."

_zeroconf = None
_service_info = None
_browser = None
_discovery_status = {
    "enabled": ENABLE_MDNS,
    "active": False,
    "method": "mDNS/DNS-SD",
    "service_type": SERVICE_TYPE,
    "message": "Initializing...",
}


class SkDropServiceListener:
    """Listener for mDNS service discovery events."""

    def add_service(self, zc, type_, name):
        try:
            info = zc.get_service_info(type_, name)
            if not info or not info.addresses:
                return

            ip = socket.inet_ntoa(info.addresses[0])
            port = info.port
            properties = {
                k.decode("utf-8", "ignore"): v.decode("utf-8", "ignore")
                for k, v in (info.properties or {}).items()
            }

            peer_id = properties.get("id", name.split(".")[0])
            peer_name = properties.get("name", name.split(".")[0])
            peer_type = properties.get("type", "desktop")

            if peer_id and peer_id != DEVICE_ID:
                register_discovered_device(peer_id, peer_name, peer_type, ip, port)
                logger.info(f"Discovered peer via mDNS: {peer_name} ({ip}:{port})")
        except Exception as e:
            logger.debug(f"Error handling discovered service {name}: {e}")

    def update_service(self, zc, type_, name):
        self.add_service(zc, type_, name)

    def remove_service(self, zc, type_, name):
        pass


def _run_discovery_thread():
    """Background worker thread to run Zeroconf registration and browsing."""
    global _zeroconf, _service_info, _browser, _discovery_status

    if not ENABLE_MDNS:
        _discovery_status["active"] = False
        _discovery_status["message"] = "mDNS discovery disabled by configuration."
        return

    try:
        from zeroconf import IPVersion, ServiceBrowser, ServiceInfo, Zeroconf

        local_ip = get_local_ip()
        if local_ip.startswith("127."):
            _discovery_status["active"] = False
            _discovery_status["message"] = "No external network interface detected. Discovery inactive."
            return

        _zeroconf = Zeroconf(ip_version=IPVersion.V4Only)

        server_name = f"{DEVICE_NAME.replace(' ', '-')}-{DEVICE_ID[:6]}.local."
        service_name = f"SkDrop-{DEVICE_ID[:6]}.{SERVICE_TYPE}"

        properties = {
            b"id": DEVICE_ID.encode(),
            b"name": DEVICE_NAME.encode(),
            b"type": DEVICE_TYPE.encode(),
            b"version": b"1.0",
        }

        _service_info = ServiceInfo(
            SERVICE_TYPE,
            service_name,
            addresses=[socket.inet_aton(local_ip)],
            port=PORT,
            properties=properties,
            server=server_name,
        )

        _zeroconf.register_service(_service_info)
        _browser = ServiceBrowser(_zeroconf, SERVICE_TYPE, SkDropServiceListener())

        _discovery_status["active"] = True
        _discovery_status["message"] = f"Advertising on {local_ip}:{PORT} via mDNS"
        logger.info(f"mDNS active: advertising {service_name} at {local_ip}:{PORT}")

    except Exception as exc:
        _discovery_status["active"] = False
        _discovery_status["message"] = (
            f"mDNS unavailable ({exc.__class__.__name__}). "
            "Manual IP and QR pairing are fully available."
        )
        logger.warning(f"mDNS discovery could not start: {exc}. Continuing with manual/QR pairing.")


def start_discovery():
    """Launch discovery in a daemon thread so it never blocks startup."""
    t = threading.Thread(target=_run_discovery_thread, daemon=True, name="SkDropDiscovery")
    t.start()


def stop_discovery():
    """Safely stop Zeroconf browsing and advertising."""
    global _zeroconf, _service_info, _browser, _discovery_status

    if _zeroconf:
        try:
            if _service_info:
                _zeroconf.unregister_service(_service_info)
            if _browser:
                _browser.cancel()
            _zeroconf.close()
        except Exception as e:
            logger.debug(f"Error closing zeroconf: {e}")
        finally:
            _zeroconf = None
            _service_info = None
            _browser = None
            _discovery_status["active"] = False
            _discovery_status["message"] = "Stopped"


def get_discovery_status() -> dict:
    """Return status of discovery service."""
    return dict(_discovery_status)
