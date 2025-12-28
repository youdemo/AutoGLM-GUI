"""Global device manager with background polling and state caching."""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Optional

from phone_agent.adb.connection import ADBConnection, ConnectionType, DeviceInfo

from AutoGLM_GUI.logger import logger

if TYPE_CHECKING:
    from AutoGLM_GUI.phone_agent_manager import PhoneAgentManager


class DeviceState(str, Enum):
    """Device availability state."""

    ONLINE = "online"  # Device connected and responsive
    OFFLINE = "offline"  # Device connected but not responsive
    DISCONNECTED = "disconnected"  # Device not in ADB device list
    AVAILABLE_MDNS = "available"  # Discovered via mDNS but not connected


@dataclass
class DeviceConnection:
    """Single connection method for a device (USB, WiFi, mDNS, etc.)."""

    device_id: str  # USB serial OR IP:port
    connection_type: ConnectionType
    status: str  # "device" | "offline" | "unauthorized"
    last_seen: float = field(default_factory=time.time)

    def priority_score(self) -> int:
        """Calculate connection priority for sorting.

        Priority:
        1. Connection type (USB > WiFi/Remote > mDNS)
        2. Status (device > offline > unauthorized)
        """
        # Type priority (higher is better)
        type_priority = {
            ConnectionType.USB: 300,
            ConnectionType.WIFI: 200,
            ConnectionType.REMOTE: 200,
        }

        # Status priority
        status_priority = {
            "device": 30,
            "offline": 20,
            "unauthorized": 10,
        }

        return type_priority.get(self.connection_type, 0) + status_priority.get(
            self.status, 0
        )


@dataclass
class ManagedDevice:
    """Device information aggregated by serial (multiple connections supported)."""

    # Core identity (indexed by serial now)
    serial: str  # Hardware serial number (ro.serialno)

    # Connections (multiple connection methods)
    connections: list[DeviceConnection] = field(default_factory=list)
    primary_connection_idx: int = 0  # Index of primary connection

    # Device metadata
    model: Optional[str] = None

    # Device-level state
    state: DeviceState = DeviceState.ONLINE
    is_initialized: bool = False  # Device-level initialization

    # Timestamps
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    error_count: int = 0  # Consecutive polling errors

    @property
    def primary_connection(self) -> DeviceConnection:
        """Get the primary connection."""
        if not self.connections:
            raise ValueError(f"Device {self.serial} has no connections")
        return self.connections[self.primary_connection_idx]

    @property
    def primary_device_id(self) -> str:
        """Get the device_id of the primary connection (used in API)."""
        return self.primary_connection.device_id

    @property
    def status(self) -> str:
        """Status of primary connection."""
        return self.primary_connection.status

    @property
    def connection_type(self) -> ConnectionType:
        """Type of primary connection."""
        return self.primary_connection.connection_type

    def select_primary_connection(self) -> None:
        """Select best connection as primary based on priority."""
        if not self.connections:
            return

        # Sort by priority (descending)
        sorted_conns = sorted(
            enumerate(self.connections),
            key=lambda x: x[1].priority_score(),
            reverse=True,
        )

        self.primary_connection_idx = sorted_conns[0][0]

    def to_api_dict(self) -> dict:
        """Convert to API response format (backward compatible)."""
        return {
            "id": self.primary_device_id,  # Primary connection's device_id
            "serial": self.serial,
            "model": self.model or "Unknown",
            "status": self.status,
            "connection_type": self.connection_type.value,
            "is_initialized": self.is_initialized,
            "state": self.state.value,  # Device state (online/offline/disconnected/available)
            "is_available_only": self.state
            == DeviceState.AVAILABLE_MDNS,  # mDNS discovered but not connected
        }

    def to_api_dict_with_agent(self, agent_manager: PhoneAgentManager) -> dict:
        """转换为 API 响应格式,包含 Agent 状态.

        通过 serial 查找 Agent,处理连接切换场景.

        Args:
            agent_manager: PhoneAgentManager 实例

        Returns:
            dict: 设备信息及可选的 Agent 状态
        """
        # 基础设备信息
        result = {
            "id": self.primary_device_id,
            "serial": self.serial,
            "model": self.model or "Unknown",
            "status": self.status,
            "connection_type": self.connection_type.value,
            "state": self.state.value,
            "is_available_only": self.state == DeviceState.AVAILABLE_MDNS,
        }

        # 通过 serial 查找 Agent (处理连接切换)
        agent_device_id = agent_manager.find_agent_by_serial(self.serial)

        if agent_device_id:
            # Agent 存在(可能在不同的 device_id 下)
            metadata = agent_manager.get_metadata(agent_device_id)

            if metadata:
                result["agent"] = {
                    "state": metadata.state.value,
                    "created_at": metadata.created_at,
                    "last_used": metadata.last_used,
                    "error_message": metadata.error_message,
                    "model_name": metadata.model_config.model_name,
                }
                result["is_initialized"] = True
            else:
                # 不应该发生,但安全处理
                result["agent"] = None
                result["is_initialized"] = True
        else:
            # 无 Agent 初始化
            result["agent"] = None
            result["is_initialized"] = False

        return result


# Helper functions


def _is_mdns_connection(device_id: str) -> bool:
    """Check if device_id is from mDNS discovery."""
    mdns_patterns = [
        "._adb-tls-connect._tcp",
        "._adb-tls-pairing._tcp",
        ".local.",  # mDNS hostname suffix
    ]
    return any(pattern in device_id for pattern in mdns_patterns)


def _create_managed_device(
    serial: str, device_infos: list[DeviceInfo], agents: dict
) -> ManagedDevice:
    """Create ManagedDevice from DeviceInfo list."""
    connections = [
        DeviceConnection(
            device_id=d.device_id,
            connection_type=d.connection_type,
            status=d.status,
            last_seen=time.time(),
        )
        for d in device_infos
    ]

    # Extract model (prefer device with model info)
    model = None
    for device_info in device_infos:
        if device_info.model:
            model = device_info.model
            break

    # Create managed device
    managed = ManagedDevice(
        serial=serial,
        connections=connections,
        model=model,
    )

    # Select primary connection
    managed.select_primary_connection()

    # Set state
    managed.state = (
        DeviceState.ONLINE if managed.status == "device" else DeviceState.OFFLINE
    )

    # Check if initialized (any connection has agent)
    managed.is_initialized = any(conn.device_id in agents for conn in connections)

    return managed


class DeviceManager:
    """Singleton manager for ADB device discovery and state management.

    Features:
    - Background polling thread (every 10s)
    - Thread-safe device state cache
    - Exponential backoff on ADB failures
    - Integration with existing state.agents
    """

    _instance: Optional[DeviceManager] = None
    _lock = threading.Lock()

    def __init__(self, adb_path: str = "adb"):
        """Private constructor. Use get_instance() instead."""
        # Device state storage (indexed by serial now)
        self._devices: dict[str, ManagedDevice] = {}  # Key: serial
        self._devices_lock = threading.RLock()  # Reentrant for nested calls

        # Reverse mapping for backward compatibility
        self._device_id_to_serial: dict[str, str] = {}  # Key: device_id -> serial

        # Polling thread control
        self._poll_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._poll_interval = 10.0  # seconds

        # Exponential backoff state
        self._current_interval = 10.0
        self._min_interval = 10.0
        self._max_interval = 60.0
        self._backoff_multiplier = 2.0
        self._consecutive_failures = 0

        # ADB connection
        self._adb_path = adb_path
        self._adb_conn = ADBConnection(adb_path=adb_path)

        # mDNS discovery support
        self._mdns_supported: Optional[bool] = None  # Lazy check
        self._mdns_devices: dict[str, ManagedDevice] = {}  # Key: serial
        self._enable_mdns_discovery: bool = True  # Feature toggle

    @classmethod
    def get_instance(cls, adb_path: str = "adb") -> DeviceManager:
        """Get singleton instance (thread-safe)."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(adb_path=adb_path)
                    logger.info("DeviceManager singleton created")
        return cls._instance

    def start_polling(self) -> None:
        """Start background polling thread."""
        with self._devices_lock:
            if self._poll_thread and self._poll_thread.is_alive():
                logger.warning("Polling thread already running")
                return

            self._stop_event.clear()
            self._poll_thread = threading.Thread(
                target=self._polling_loop, name="DeviceManager-Poll", daemon=True
            )
            self._poll_thread.start()
            logger.info(
                f"DeviceManager polling started (interval: {self._poll_interval:.1f}s)"
            )

    def stop_polling(self) -> None:
        """Stop background polling thread (graceful shutdown)."""
        if not self._poll_thread:
            return

        logger.info("Stopping DeviceManager polling...")
        self._stop_event.set()

        if self._poll_thread.is_alive():
            self._poll_thread.join(timeout=5.0)
            if self._poll_thread.is_alive():
                logger.warning("Polling thread did not stop gracefully")
            else:
                logger.info("DeviceManager polling stopped")

    def get_devices(self) -> list[ManagedDevice]:
        """Get all cached devices (connected + available mDNS)."""
        with self._devices_lock:
            # Merge connected and mDNS devices
            all_devices = list(self._devices.values())

            # Add mDNS devices that aren't already connected
            connected_serials = set(self._devices.keys())
            mdns_only = [
                dev
                for serial, dev in self._mdns_devices.items()
                if serial not in connected_serials
            ]

            all_devices.extend(mdns_only)
            return all_devices

    def get_device(self, device_id: str) -> Optional[ManagedDevice]:
        """Get single device info by ID (deprecated, use get_device_by_serial)."""
        # For backward compatibility, try to interpret as serial
        with self._devices_lock:
            return self._devices.get(device_id)

    def get_device_by_device_id(self, device_id: str) -> Optional[ManagedDevice]:
        """Get device by any of its connection device_ids (backward compatibility).

        This method supports looking up devices by either:
        - Serial number (direct lookup)
        - Any device_id from any connection (reverse mapping)
        """
        with self._devices_lock:
            # First try direct serial lookup (if device_id IS a serial)
            if device_id in self._devices:
                return self._devices[device_id]

            # Use reverse mapping
            serial = self._device_id_to_serial.get(device_id)
            if serial:
                return self._devices.get(serial)

            return None

    def get_agent_by_serial(self, serial: str) -> Optional[str]:
        """
        Find device_id of initialized PhoneAgent for this device serial.

        This method helps locate agents when device_id changes due to
        connection switching (e.g., USB → WiFi).

        Args:
            serial: Hardware serial number of the device

        Returns:
            device_id of the initialized agent if found, None otherwise

        Example:
            >>> # Device was initialized via USB
            >>> agents["ABC123"] = PhoneAgent(device_id="ABC123")
            >>>
            >>> # User switches to WiFi, device_id changes
            >>> dm = DeviceManager.get_instance()
            >>> agent_device_id = dm.get_agent_by_serial("ABC123")
            >>> if agent_device_id:
            >>>     agent = agents[agent_device_id]  # Found!
        """
        from AutoGLM_GUI.state import agents

        with self._devices_lock:
            device = self._devices.get(serial)
            if not device:
                return None

            # Check all connections for initialized agents
            for conn in device.connections:
                if conn.device_id in agents:
                    logger.debug(
                        f"Found agent for serial {serial} at device_id {conn.device_id}"
                    )
                    return conn.device_id

            return None

    def update_initialization_status(
        self, device_id: str, is_initialized: bool
    ) -> None:
        """
        Update device initialization status with connection switch detection.

        Args:
            device_id: Current device_id (may differ from initial device_id)
            is_initialized: Initialization status

        Note:
            This method detects connection switching:
            - If agent exists under different device_id for same serial, logs warning
            - Helps identify cases where agent reinitialization may be needed
        """
        from AutoGLM_GUI.state import agents

        device = self.get_device_by_device_id(device_id)

        if device:
            with self._devices_lock:
                # Check for connection switching
                # (agent exists under different device_id for same device)
                if is_initialized:
                    # Find if agent exists under different device_id
                    for conn in device.connections:
                        if conn.device_id != device_id and conn.device_id in agents:
                            # Connection switch detected!
                            logger.warning(
                                f"Connection switch detected for device {device.serial}: "
                                f"{conn.device_id} → {device_id}. "
                                f"Agent exists under old device_id. "
                                f"Consider using DeviceManager.get_agent_by_serial() "
                                f"to locate the existing agent."
                            )
                            break

                # Update status
                device.is_initialized = is_initialized
                logger.debug(
                    f"Device {device.serial} (via {device_id}) "
                    f"initialization status: {is_initialized}"
                )
        else:
            logger.warning(
                f"Cannot update initialization status: device_id {device_id} not found"
            )

    def force_refresh(self) -> None:
        """Trigger immediate device list refresh (blocking)."""
        logger.info("Force refreshing device list...")
        self._poll_devices()

    # Internal methods

    def _check_mdns_support(self) -> bool:
        """
        Check if ADB supports mDNS discovery (lazy initialization).

        Returns:
            True if supported, False otherwise
        """
        if self._mdns_supported is None:
            from AutoGLM_GUI.adb_plus.version import supports_mdns_services

            self._mdns_supported = supports_mdns_services(self._adb_path)

            if self._mdns_supported:
                logger.info("ADB mDNS discovery is supported")
            else:
                logger.info("ADB mDNS discovery not available (requires ADB 30.0.0+)")

        return self._mdns_supported

    def _polling_loop(self) -> None:
        """Background polling loop (runs in thread)."""
        logger.debug("Polling loop started")

        while not self._stop_event.is_set():
            try:
                self._poll_devices()

                # Reset backoff on success
                if self._consecutive_failures > 0:
                    logger.info("Polling recovered, resetting backoff")
                self._consecutive_failures = 0
                self._current_interval = self._min_interval

            except Exception as e:
                self._handle_poll_error(e)

            # Sleep with interruptible wait
            self._stop_event.wait(timeout=self._current_interval)

    def _poll_devices(self) -> None:
        """Poll ADB device list and update cache (serial-based aggregation)."""
        from AutoGLM_GUI.adb_plus import get_device_serial
        from AutoGLM_GUI.state import agents

        # Step 1: Get ADB devices and fetch serials
        adb_devices = self._adb_conn.list_devices()
        device_with_serials: list[tuple[DeviceInfo, str]] = []

        for device_info in adb_devices:
            serial = get_device_serial(device_info.device_id, self._adb_path)

            if not serial:
                # CRITICAL: Log error and skip this device
                logger.error(
                    f"Failed to get serial for device {device_info.device_id}. "
                    f"Skipping this device. Check ADB access."
                )
                continue

            device_with_serials.append((device_info, serial))

        # Step 2: Group devices by serial
        grouped_by_serial: dict[str, list[DeviceInfo]] = defaultdict(list)

        for device_info, serial in device_with_serials:
            grouped_by_serial[serial].append(device_info)

        # Step 3: Filter mDNS connections (if other connections exist)
        for serial, device_infos in grouped_by_serial.items():
            filtered = []
            has_non_mdns = False

            # First pass: check if we have non-mDNS connections
            for device_info in device_infos:
                if not _is_mdns_connection(device_info.device_id):
                    has_non_mdns = True
                    break

            # Second pass: filter out mDNS if non-mDNS exists
            for device_info in device_infos:
                if has_non_mdns and _is_mdns_connection(device_info.device_id):
                    logger.debug(
                        f"Filtering mDNS connection {device_info.device_id} "
                        f"(device has clearer connection)"
                    )
                    continue
                filtered.append(device_info)

            grouped_by_serial[serial] = filtered

        # Step 4: Update device cache
        with self._devices_lock:
            current_serials = set(grouped_by_serial.keys())
            previous_serials = set(self._devices.keys())

            added_serials = current_serials - previous_serials
            removed_serials = previous_serials - current_serials
            existing_serials = current_serials & previous_serials

            # Add new devices
            for serial in added_serials:
                device_infos = grouped_by_serial[serial]
                managed = _create_managed_device(serial, device_infos, agents)
                self._devices[serial] = managed

                # Update reverse mapping
                for conn in managed.connections:
                    self._device_id_to_serial[conn.device_id] = serial

                logger.info(
                    f"Device added: {serial} ({managed.model or 'Unknown'}) "
                    f"via {managed.connection_type.value} ({managed.primary_device_id})"
                )

            # Update existing devices
            for serial in existing_serials:
                device_infos = grouped_by_serial[serial]
                managed = self._devices[serial]

                # Rebuild connections
                old_device_ids = {conn.device_id for conn in managed.connections}
                new_connections = [
                    DeviceConnection(
                        device_id=d.device_id,
                        connection_type=d.connection_type,
                        status=d.status,
                        last_seen=time.time(),
                    )
                    for d in device_infos
                ]

                managed.connections = new_connections
                managed.last_seen = time.time()
                managed.error_count = 0

                # Update model if available
                for device_info in device_infos:
                    if device_info.model:
                        managed.model = device_info.model
                        break

                # Re-select primary connection
                managed.select_primary_connection()

                # Update state
                managed.state = (
                    DeviceState.ONLINE
                    if managed.status == "device"
                    else DeviceState.OFFLINE
                )

                # Sync is_initialized from agents (check any device_id)
                old_initialized = managed.is_initialized
                new_initialized = any(
                    conn.device_id in agents for conn in managed.connections
                )

                # If was initialized but no longer has agent, keep it True temporarily
                # This prevents false negatives during connection transitions
                if old_initialized and not new_initialized:
                    # Check if any old connection had an agent
                    had_agent_connection = any(
                        old_id in agents for old_id in old_device_ids
                    )
                    if had_agent_connection:
                        logger.info(
                            f"Device {serial} lost agent connection during transition, "
                            f"keeping is_initialized=True"
                        )
                        new_initialized = True

                managed.is_initialized = new_initialized

                # Update reverse mapping
                new_device_ids = {conn.device_id for conn in managed.connections}

                # Remove stale mappings
                for old_id in old_device_ids - new_device_ids:
                    self._device_id_to_serial.pop(old_id, None)

                # Add new mappings
                for new_id in new_device_ids:
                    self._device_id_to_serial[new_id] = serial

            # Mark removed devices as disconnected
            for serial in removed_serials:
                managed = self._devices[serial]
                managed.state = DeviceState.DISCONNECTED
                managed.last_seen = time.time()
                logger.warning(
                    f"Device disconnected: {serial} ({managed.model or 'Unknown'})"
                )

                # Remove reverse mappings
                for conn in managed.connections:
                    self._device_id_to_serial.pop(conn.device_id, None)

        # Step 5: Discover mDNS devices (if enabled and supported)
        if self._enable_mdns_discovery and self._check_mdns_support():
            from AutoGLM_GUI.adb_plus import (
                discover_mdns_devices,
                extract_serial_from_mdns,
            )

            try:
                mdns_devices = discover_mdns_devices(self._adb_path)

                with self._devices_lock:
                    connected_serials = set(self._devices.keys())

                    # Process discovered mDNS devices
                    for mdns_dev in mdns_devices:
                        # Extract serial from mDNS name
                        serial = extract_serial_from_mdns(mdns_dev.name)

                        if not serial:
                            logger.debug(
                                f"Could not extract serial from mDNS device: {mdns_dev.name}"
                            )
                            continue

                        # Skip if already connected
                        if serial in connected_serials:
                            logger.debug(
                                f"mDNS device {mdns_dev.name} already connected as {serial}"
                            )
                            continue

                        # Create or update AVAILABLE_MDNS device
                        if serial not in self._mdns_devices:
                            # Create minimal device info
                            available_device = ManagedDevice(
                                serial=serial,
                                connections=[
                                    DeviceConnection(
                                        device_id=f"{mdns_dev.ip}:{mdns_dev.port}",
                                        connection_type=ConnectionType.REMOTE,
                                        status="available",  # Not connected yet
                                        last_seen=time.time(),
                                    )
                                ],
                                state=DeviceState.AVAILABLE_MDNS,
                                model=None,  # Unknown until connected
                                is_initialized=False,
                            )
                            self._mdns_devices[serial] = available_device
                            logger.info(
                                f"Discovered mDNS device: {mdns_dev.name} at {mdns_dev.ip}:{mdns_dev.port}"
                            )
                        else:
                            # Update last_seen
                            self._mdns_devices[serial].last_seen = time.time()

                    # Clean up stale mDNS devices (not seen for 60s)
                    current_time = time.time()
                    stale_serials = [
                        serial
                        for serial, dev in self._mdns_devices.items()
                        if current_time - dev.last_seen > 60
                    ]
                    for serial in stale_serials:
                        del self._mdns_devices[serial]
                        logger.debug(f"Removed stale mDNS device: {serial}")

            except Exception as e:
                logger.debug(f"mDNS discovery failed: {e}")

    def _handle_poll_error(self, error: Exception) -> None:
        """Handle polling failure with exponential backoff."""
        self._consecutive_failures += 1

        # Calculate new interval
        self._current_interval = min(
            self._min_interval * (self._backoff_multiplier**self._consecutive_failures),
            self._max_interval,
        )

        logger.warning(
            f"Device polling failed (attempt {self._consecutive_failures}): {error}. "
            f"Retrying in {self._current_interval:.1f}s"
        )

    # WiFi Connection Methods

    def connect_wifi(
        self, device_id: str, port: int = 5555
    ) -> tuple[bool, str, Optional[str]]:
        """Connect to device over WiFi (from USB connection).

        Args:
            device_id: Device ID (USB serial or IP:port)
            port: TCP port for WiFi connection (default: 5555)

        Returns:
            Tuple of (success, message, wifi_device_id)
        """
        from phone_agent.adb.connection import ADBConnection, ConnectionType

        from AutoGLM_GUI.adb_plus import get_wifi_ip

        conn = ADBConnection(adb_path=self._adb_path)

        # Get device info
        device_info = conn.get_device_info(device_id)
        if not device_info:
            return (False, "No connected device found", None)

        # Already WiFi connection
        if device_info.connection_type == ConnectionType.REMOTE:
            address = device_info.device_id
            return (True, "Already connected over WiFi", address)

        # 1) Enable tcpip
        ok, msg = conn.enable_tcpip(port=port, device_id=device_info.device_id)
        if not ok:
            return (False, msg or "Failed to enable tcpip", None)

        # 2) Get device IP
        ip = get_wifi_ip(conn.adb_path, device_info.device_id) or conn.get_device_ip(
            device_info.device_id
        )
        if not ip:
            return (False, "Failed to get device IP", None)

        address = f"{ip}:{port}"

        # 3) Connect WiFi
        ok, msg = conn.connect(address)
        if not ok:
            return (False, msg or "Failed to connect over WiFi", None)

        logger.info(f"Successfully switched device {device_id} to WiFi: {address}")
        return (True, "Switched to WiFi successfully", address)

    def disconnect_wifi(self, device_id: str) -> tuple[bool, str]:
        """Disconnect WiFi connection.

        Args:
            device_id: Device ID (IP:port)

        Returns:
            Tuple of (success, message)
        """
        from phone_agent.adb.connection import ADBConnection

        conn = ADBConnection(adb_path=self._adb_path)
        ok, msg = conn.disconnect(device_id)

        if ok:
            logger.info(f"Successfully disconnected WiFi device: {device_id}")
        else:
            logger.warning(f"Failed to disconnect WiFi device {device_id}: {msg}")

        return (ok, msg)

    def connect_wifi_manual(
        self, ip: str, port: int
    ) -> tuple[bool, str, Optional[str]]:
        """Manually connect to WiFi device (without USB).

        Args:
            ip: Device IP address
            port: TCP port (1-65535)

        Returns:
            Tuple of (success, message, device_id)
        """
        import re

        from phone_agent.adb.connection import ADBConnection

        # IP format validation
        ip_pattern = r"^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$"
        if not re.match(ip_pattern, ip):
            return (False, "Invalid IP address format", None)

        # Port range validation
        if not (1 <= port <= 65535):
            return (False, "Port must be between 1 and 65535", None)

        conn = ADBConnection(adb_path=self._adb_path)
        address = f"{ip}:{port}"

        # Direct connect
        ok, msg = conn.connect(address)
        if not ok:
            return (False, msg or f"Failed to connect to {address}", None)

        logger.info(f"Successfully connected to WiFi device manually: {address}")
        return (True, f"Successfully connected to {address}", address)

    def pair_wifi(
        self, ip: str, pairing_port: int, pairing_code: str, connection_port: int
    ) -> tuple[bool, str, Optional[str]]:
        """Pair and connect to WiFi device using wireless debugging (Android 11+).

        Args:
            ip: Device IP address
            pairing_port: Wireless debugging pairing port (1-65535)
            pairing_code: 6-digit pairing code
            connection_port: Wireless debugging connection port (1-65535)

        Returns:
            Tuple of (success, message, device_id)
        """
        import re

        from phone_agent.adb.connection import ADBConnection

        from AutoGLM_GUI.adb_plus import pair_device

        # IP format validation
        ip_pattern = r"^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$"
        if not re.match(ip_pattern, ip):
            return (False, "Invalid IP address format", None)

        # Pairing port validation
        if not (1 <= pairing_port <= 65535):
            return (False, "Pairing port must be between 1 and 65535", None)

        # Connection port validation
        if not (1 <= connection_port <= 65535):
            return (False, "Connection port must be between 1 and 65535", None)

        # Pairing code validation (6 digits)
        if not pairing_code.isdigit() or len(pairing_code) != 6:
            return (False, "Pairing code must be 6 digits", None)

        conn = ADBConnection(adb_path=self._adb_path)

        # Step 1: Pair device
        ok, msg = pair_device(
            ip=ip,
            port=pairing_port,
            pairing_code=pairing_code,
            adb_path=conn.adb_path,
        )

        if not ok:
            logger.warning(f"Failed to pair WiFi device {ip}:{pairing_port}: {msg}")
            return (False, msg, None)

        # Step 2: Connect to device
        connection_address = f"{ip}:{connection_port}"
        ok, connect_msg = conn.connect(connection_address)

        if not ok:
            logger.warning(
                f"Paired successfully but connection failed to {connection_address}: {connect_msg}"
            )
            return (
                False,
                f"Paired successfully but connection failed: {connect_msg}",
                None,
            )

        logger.info(
            f"Successfully paired and connected to WiFi device: {connection_address}"
        )
        return (
            True,
            f"Successfully paired and connected to {connection_address}",
            connection_address,
        )
