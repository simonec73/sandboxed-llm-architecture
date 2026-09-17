import time
import uuid
from abc import ABC, abstractmethod
from uuid import UUID


class Session(ABC):
    def __init__(self):
        self.session_id: UUID = uuid.uuid4()
        self._can_timeout: bool = True  # Flag to indicate if the session can timeout
        self.__last_activity: float = time.time()  # Initialize last activity timestamp

    def _touch(self):
        """Update the last activity timestamp to the current time."""
        self.__last_activity = time.time()

    def is_active(self, timeout: float) -> bool:
        """Check if the session is active based on the last activity timestamp and a timeout."""
        return (not self._can_timeout) or (time.time() - self.__last_activity) < timeout

    def set_can_timeout(self, can_timeout: bool):
        """Set whether the session can timeout."""
        self._can_timeout = can_timeout

    @abstractmethod
    def close(self):
        pass
