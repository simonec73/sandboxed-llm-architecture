import os
from collections.abc import Iterator
from uuid import UUID

import yaml
from dotenv import load_dotenv

from logging_config import logger

from .data_classes import ModelInfo, RequestParams
from .model_llamacpp import LlamaCppModel
from .utils import get_yaml

load_dotenv()

class ModelManager:
    def __init__(self):
        self.__yaml_path = get_yaml("models")
        self.__modelInfos = self.__load_model_infos()
        self.__models: list[LlamaCppModel] = []
        
    def __load_model_infos(self) -> list[ModelInfo]:
        configs: list[ModelInfo] = []
    
        if self.__yaml_path is None or not os.path.exists(self.__yaml_path):
            logger.warning(f"YAML file path is invalid or does not exist: {self.__yaml_path}")
            return []

        with open(self.__yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if data is None:
            logger.warning(f"YAML file is empty: {self.__yaml_path}")
            return []

        if not isinstance(data, list):
            logger.warning(f"YAML file must be a list of models: {self.__yaml_path}")
            return []

        for entry in data:
            name = entry.get("model")

            if name == "emotion":
                logger.warning(f"Skipping 'emotion' model in YAML file: {self.__yaml_path}")
                continue
            if name == "tts":
                logger.warning(f"Skipping 'tts' model in YAML file: {self.__yaml_path}")
                continue

            host = entry.get("host")
            model_path = entry.get("model_path")
            chat_format = entry.get("chat_format")
            jinja = entry.get("jinja")
            bos = entry.get("bos")
            eos = entry.get("eos")
            n_ctx = entry.get("n_ctx", 3048)
            n_gpu_layers = entry.get("n_gpu_layers", -1)
            rope_freq_scale = entry.get("rope_freq_scale", 1.0)
            flash_attention = entry.get("flash_attention", True)
            n_threads = entry.get("n_threads", -1)
            n_batch = entry.get("n_batch", 512)

            configs.append(
                ModelInfo(
                    name=name,
                    host=host,
                    model_path=model_path,
                    jinja=jinja,
                    bos=bos,
                    eos=eos,
                    chat_format=chat_format,
                    n_ctx=n_ctx,
                    n_gpu_layers=n_gpu_layers,
                    rope_freq_scale=rope_freq_scale,
                    flash_attention=flash_attention,
                    n_threads=n_threads,
                    n_batch=n_batch,
                )
            )

        return configs

    def get_model_infos(self) -> list[ModelInfo]:
        return [
            model_info
            for model_info in self.__modelInfos
            if model_info.model_path is not None and os.path.isfile(model_info.model_path)
        ]
    
    def get_model_info(self, model_name: str) -> ModelInfo | None:
        model_infos = self.get_model_infos()
        for model_info in model_infos:
            if model_info.name == model_name:
                return model_info
        return None
    
    def is_model_defined(self, model_name: str) -> bool:
        return any(model.name == model_name for model in self.get_model_infos())
    
    def load_model(self, model_name: str, session_id: UUID) -> bool:
        model_info = self.get_model_info(model_name)
        if model_info is None:
            logger.warning(f"Model Info for '{model_name}' could not be loaded.")
            return False
        
        model = next((m for m in self.__models if m.name == model_name), None)
        if model is not None:
            logger.info(f"Model '{model_name}' is already loaded.")
            model.add_session(session_id)  # Increment reference count
            return True

        if model_info.host == "llamacpp":
            model = LlamaCppModel(model_info)
        else:
            logger.warning(f"Unsupported host '{model_info.host}' for model '{model_name}'.")
            return False
        
        model.add_session(session_id)  # Increment reference count
        self.__models.append(model)
        return True
    
    def unload_model(self, model_name: str, session_id: UUID) -> bool:
        model = next((m for m in self.__models if m.name == model_name), None)
        if model is None:
            logger.warning(f"Model '{model_name}' is not loaded.")
            return False

        model.remove_session(session_id)  # Decrement reference count
        if model.get_session_count() == 0:
            model._unload()
            self.__models.remove(model)
        return True
    
    def chat(self, model_name: str, request: RequestParams) -> str | None:
        model = next((m for m in self.__models if m.name == model_name), None)
        if model is None:
            logger.warning(f"Model '{model_name}' is not loaded.")
            return None

        return model.chat(request)

    def stream(self, model_name: str, request: RequestParams) -> Iterator[str] | None:
        model = next((m for m in self.__models if m.name == model_name), None)
        if model is None:
            logger.warning(f"Model '{model_name}' is not loaded.")
            return None

        return model.stream(request)