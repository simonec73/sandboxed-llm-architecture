import os
from threading import Event, RLock, Thread
from uuid import UUID

from logging_config import logger

from .model_manager import ModelManager
from .session import Session
from .session_model import ModelSession


class SessionManager:
    def __init__(self, model_manager: ModelManager):
        self.__sessions: dict[UUID, Session] = {} # Dictionary to store sessions with session_id as key and Session object as value
        self.__model_manager = model_manager
        self.__sandboxed_session: Session | None = None
        self.__sessions_lock = RLock()
        self.__cleanup_stop = Event()
        self.__cleanup_thread = Thread(target=self.__cleanup_loop, daemon=True)
        self.__cleanup_thread.start()

    def __cleanup_loop(self):
        while not self.__cleanup_stop.wait(60.0):
            self.close_inactive_sessions()
    
    def create_session(self, model_name: str, global_session: bool = False) -> UUID:
        session: Session = ModelSession(model_name, self.__model_manager, global_session, sandboxed_session=self.__sandboxed_session)

        with self.__sessions_lock:
            self.__sessions[session.session_id] = session
        
        return session.session_id

    def get_session(self, session_id: UUID) -> Session | None:
        with self.__sessions_lock:
            return self.__sessions.get(session_id)

    def get_global_session(self, model_name: str) -> ModelSession | None:
        with self.__sessions_lock:
            for session in self.__sessions.values():
                if isinstance(session, ModelSession) and session.is_global_session() and session.get_model_name() == model_name:
                    return session
        return None

    def close_session(self, session_id: UUID):
        with self.__sessions_lock:
            session = self.__sessions.pop(session_id, None)

        if session:
            logger.info(f"Closing session: {session_id}")
            session.close()

    def close_inactive_sessions(self, timeout: float = 600.0):
        with self.__sessions_lock:
            inactive_sessions = [
                (session_id, session)
                for session_id, session in self.__sessions.items()
                if not session.is_active(timeout)
            ]
            for session_id, _session in inactive_sessions:
                del self.__sessions[session_id]

        for session_id, session in inactive_sessions:
            logger.info(f"Closing inactive session: {session_id}")
            session.close()

    def close_all_sessions(self):
        self.__cleanup_stop.set()
        self.__cleanup_thread.join()

        with self.__sessions_lock:
            sessions = list(self.__sessions.values())
            self.__sessions.clear()

        for session in sessions:
            session.close()

    def register_sandboxed_model(self):
        sandboxed_model = os.getenv("SANDBOXED_MODEL")
        if sandboxed_model is not None and self.__model_manager.is_model_defined(sandboxed_model):
            logger.info(f"Sandboxed model set to '{sandboxed_model}'")
            session: Session | None = self.get_global_session(sandboxed_model)
            if session is None:
                logger.info(f"No global session found for the sandboxed model '{sandboxed_model}'. Creating a new session.")
                session_id = self.create_session(sandboxed_model, global_session=True)
                self.__sandboxed_session = self.get_session(session_id)
            else:
                logger.info(f"Using existing global session '{session.session_id}' for model '{sandboxed_model}'.")
                self.__sandboxed_session = session

            if self.__sandboxed_session is not None:
                self.__sandboxed_session.set_can_timeout(False)