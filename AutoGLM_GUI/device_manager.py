"""Global device manager with background polling and state caching."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from phone_agent.adb.connection import ADBConnection, ConnectionType, DeviceInfo

from AutoGLM_GUI.logger import logger


class DeviceState(str, Enum):
    """Device availability state."""

    ONLINE = "online"  # Device connected and responsive
    OFFLINE = "offline"  # Device connected but not responsive
    DISCONNECTED = "disconnected"  # Device not in ADB device list


@dataclass
class ManagedDevice:
    """Extended device information managed by DeviceManager."""

    # Core device info (from phone_agent.adb.connection.DeviceInfo)
    device_id: str
    status: str  # "device" | "offline" | "unauthorized" etc.
    connection_type: ConnectionType
    model: Optional[str] = None

    # Extended management info
    state: DeviceState = DeviceState.ONLINE
    serial: Optional[str] = None  # True serial from get_device_serial()
    is_initialized: bool = False  # Whether PhoneAgent exists in state.agents
    last_seen: float = field(default_factory=time.time)
    first_seen: float = field(default_factory=time.time)
    error_count: int = 0  # Consecutive polling errors for this device

    def to_api_dict(self) -> dict:
        """Convert to API response format (compatible with current /api/devices)."""
        return {
            "id": self.device_id,
            "model": self.model or "Unknown",
            "status": self.status,
            "connection_type": self.connection_type.value,
            "is_initialized": self.is_initialized,
            "serial": self.serial or "",
        }


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
        # Device state storage
        self._devices: dict[str, ManagedDevice] = {}
        self._devices_lock = threading.RLock()  # Reentrant for nested calls

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
        """Get all cached devices (thread-safe snapshot)."""
        with self._devices_lock:
            return list(self._devices.values())

    def get_device(self, device_id: str) -> Optional[ManagedDevice]:
        """Get single device info by ID."""
        with self._devices_lock:
            return self._devices.get(device_id)

    def update_initialization_status(
        self, device_id: str, is_initialized: bool
    ) -> None:
        """Update device initialization status (called when agent created/destroyed)."""
        with self._devices_lock:
            device = self._devices.get(device_id)
            if device:
                device.is_initialized = is_initialized
                logger.debug(
                    f"Device {device_id} initialization status: {is_initialized}"
                )

    def force_refresh(self) -> None:
        """Trigger immediate device list refresh (blocking)."""
        logger.info("Force refreshing device list...")
        self._poll_devices()

    # Internal methods

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
        """Poll ADB device list and update cache."""
        from AutoGLM_GUI.adb_plus import get_device_serial
        from AutoGLM_GUI.state import agents

        # Query ADB
        adb_devices = self._adb_conn.list_devices()
        current_ids = {d.device_id for d in adb_devices}

        with self._devices_lock:
            previous_ids = set(self._devices.keys())

            # Detect changes
            added = current_ids - previous_ids
            removed = previous_ids - current_ids
            existing = current_ids & previous_ids

            # Add new devices
            for device_info in adb_devices:
                if device_info.device_id in added:
                    serial = get_device_serial(device_info.device_id, self._adb_path)
                    managed = ManagedDevice(
                        device_id=device_info.device_id,
                        status=device_info.status,
                        connection_type=device_info.connection_type,
                        model=device_info.model,
                        serial=serial,
                        state=DeviceState.ONLINE
                        if device_info.status == "device"
                        else DeviceState.OFFLINE,
                        is_initialized=device_info.device_id in agents,
                    )
                    self._devices[device_info.device_id] = managed
                    logger.info(
                        f"Device added: {device_info.device_id} ({serial or 'no serial'})"
                    )

            # Update existing devices
            for device_info in adb_devices:
                if device_info.device_id in existing:
                    managed = self._devices[device_info.device_id]
                    managed.status = device_info.status
                    managed.connection_type = device_info.connection_type
                    managed.model = device_info.model or managed.model
                    managed.state = (
                        DeviceState.ONLINE
                        if device_info.status == "device"
                        else DeviceState.OFFLINE
                    )
                    managed.last_seen = time.time()
                    managed.is_initialized = device_info.device_id in agents
                    managed.error_count = 0  # Reset per-device errors on successful poll

            # Mark removed devices as disconnected
            for device_id in removed:
                managed = self._devices[device_id]
                managed.state = DeviceState.DISCONNECTED
                managed.last_seen = time.time()
                logger.warning(f"Device disconnected: {device_id}")

                # Optional: Remove after grace period (or keep for history)
                # For now, keep in cache for UX continuity

    def _handle_poll_error(self, error: Exception) -> None:
        """Handle polling failure with exponential backoff."""
        self._consecutive_failures += 1

        # Calculate new interval
        self._current_interval = min(
            self._min_interval
            * (self._backoff_multiplier**self._consecutive_failures),
            self._max_interval,
        )

        logger.warning(
            f"Device polling failed (attempt {self._consecutive_failures}): {error}. "
            f"Retrying in {self._current_interval:.1f}s"
        )
