from abc import ABC, abstractmethod
from collections.abc import Iterator
from uuid import UUID

from .data_classes import ModelInfo, RequestParams


class Model(ABC):
    def __init__(self, model_info: ModelInfo):
        self.name: str = model_info.name
        self._model_info: ModelInfo = model_info
        self.__sessions: list[UUID] = []

    #region Session Management.
    def add_session(self, session_id: UUID):
        if not self._is_loaded():
            self._load()
        self.__sessions.append(session_id)

    def remove_session(self, session_id: UUID):
        if session_id in self.__sessions:
            self.__sessions.remove(session_id)

            if len(self.__sessions) == 0:
                self._unload()

    def get_session_count(self) -> int:
        return len(self.__sessions)
    #endregion
    
    #region Abstract methods to be implemented by subclasses.
    @abstractmethod
    def _load(self) -> None:
        pass

    @abstractmethod
    def _unload(self) -> None:
        pass

    @abstractmethod
    def _is_loaded(self) -> bool:
        pass

    @abstractmethod
    def chat(self, request: RequestParams) -> str | None:
        pass

    @abstractmethod
    def stream(self, request: RequestParams) -> Iterator[str] | None:
        pass
    #endregion