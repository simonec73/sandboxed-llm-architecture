import inspect
import os
from collections.abc import Iterator
from threading import Lock
from typing import Any, cast

import psutil
import torch
from llama_cpp import Llama
from llama_cpp.llama_chat_format import Jinja2ChatFormatter

from logging_config import logger

from .data_classes import ModelInfo, RequestParams
from .model import Model

_LLAMA_INIT_PARAMS = inspect.signature(Llama.__init__).parameters

class LlamaCppModel(Model):
    def __init__(self, model_info: ModelInfo):
        super().__init__(model_info)
        self.__inference_lock = Lock()
        self.__model: Llama | None = self.__load()
        self.__resolved_eos_token: str | None = None
        self.__COMMON_STOP_SEQUENCES = [
            "<|im_end|>",       # ChatML (Qwen, some Yi, some Mistral fine-tunes)
            "<|end_of_text|>",  # Llama-3 base
            "<|eot_id|>",       # Llama-3 instruct
            "</s>",             # Llama-2, Mistral, many others
            "<|endoftext|>",    # GPT-2/GPT-J style, some older models
            "[/INST]",          # Mistral-instruct style (as a safety net, not primary)
            "<end_of_turn>",    # Gemma
            "<|assistant|>",    # Some Alpaca/Vicuna-style derivatives (as a guard against role bleed)
        ]

    #region Model Loading and Unloading.
    def __get_available_ram(self) -> int:
        return psutil.virtual_memory().available
        
    def __get_available_vram(self) -> int:
        if torch.cuda.is_available():
            free_memory, _ = torch.cuda.mem_get_info(0)
            return free_memory
        else:
            logger.warning("CUDA is not available. Cannot determine available VRAM.")
            return 0
        
    def __get_file_size(self, file_path: str) -> int:
        try:
            return os.path.getsize(file_path)
        except OSError as e:
            logger.error(f"Error getting file size for {file_path}: {e}")
            return 0
        
    def __get_n_threads(self) -> int:
        if self._model_info.n_threads < 1:
            # Use logical CPU count and reserve 2 threads for system responsiveness.
            virtual_cores = os.cpu_count()
            if virtual_cores is None:
                return 1
            else:
                return max(virtual_cores - 2, 1)
        else:
            return self._model_info.n_threads

    def __get_model_layer_count(self, model_path: str) -> int | None:
        metadata_model: Llama | None = None
        try:
            # Ask llama.cpp to load metadata only (no tensor weights) and expose GGUF keys.
            metadata_model = Llama(
                model_path=model_path,
                n_ctx=16,
                n_gpu_layers=0,
                vocab_only=True,
                verbose=False,
            )

            metadata = metadata_model.metadata
            architecture_raw = metadata.get("general.architecture")
            architecture = str(architecture_raw) if architecture_raw is not None else None

            candidate_keys = []
            if architecture is not None:
                candidate_keys.append(f"{architecture}.block_count")

            candidate_keys.extend(
                key for key in metadata if key.endswith(".block_count") and key not in candidate_keys
            )

            for key in candidate_keys:
                value = metadata.get(key)
                if value is None:
                    continue
                try:
                    block_count = int(value)
                except (TypeError, ValueError):
                    continue
                if block_count > 0:
                    return block_count

            logger.warning(
                f"Could not find transformer block count in GGUF metadata for model '{self._model_info.name}'."
            )
            return None
        except Exception as error: # noqa: BLE001
            logger.warning(
                f"Failed reading GGUF metadata for model '{self._model_info.name}': {error}"
            )
            return None
        finally:
            if metadata_model is not None:
                try:
                    metadata_model.close()
                except Exception:    # noqa: S110, BLE001
                    pass
    
    def __does_model_fit_in_cpu(self, model_size: int, available_ram: int, available_vram: int) -> bool:
        if model_size > 0 and available_ram > 0 and model_size * 1.1 <= available_ram:
            return True  # Use CPU
        else:
            logger.error(f"Model '{self._model_info.name}' does not fit in available memory. "
                            f"Model size: {model_size} bytes, Available VRAM: {available_vram} bytes, "
                            f"Available RAM: {available_ram} bytes.")
            return False

    def __get_n_gpu_layers(self) -> int | None:
        n_gpu_layers: int = self._model_info.n_gpu_layers
        available_vram = self.__get_available_vram()
        available_ram = self.__get_available_ram()
        model_size = self.__get_file_size(self._model_info.model_path)

        if n_gpu_layers < 0:
            # Check if the whole model can fit in GPU memory, considering a 10% overhead; 
            # if so, use GPU for all layers, otherwise check and eventually use the CPU.
            if model_size > 0 and available_vram > 0 and model_size * 1.1 <= available_vram:
                return -1  # Use GPU for all layers
            elif self.__does_model_fit_in_cpu(model_size, available_ram, available_vram):
                return 0  # Use CPU for all layers
            else:
                return None
        elif n_gpu_layers == 0:
            # Check if the whole model can fit in CPU memory, considering a 10% overhead; 
            # if so, use the CPU for all layers, otherwise do not load the model.
            if self.__does_model_fit_in_cpu(model_size, available_ram, available_vram):
                return 0  # Use CPU for all layers
            else:
                return None
        else:
            model_layers = self.__get_model_layer_count(self._model_info.model_path)
            if model_layers is None or model_layers <= 0:
                logger.error(
                    f"Cannot validate requested GPU layers for model '{self._model_info.name}' because metadata layer count is unavailable."
                )
                return None

            if n_gpu_layers > model_layers:
                logger.warning(
                    f"Requested {n_gpu_layers} GPU layers exceeds model layer count ({model_layers}) for model '{self._model_info.name}'. Clamping to {model_layers}."
                )
                n_gpu_layers = model_layers

            # Check if the layers as they are split can fit in GPU and CPU memory, considering a 10% overhead; 
            # if so, use the specified number of GPU layers, otherwise do not load the model.
            estimated_gpu_footprint = model_size * 1.1 * n_gpu_layers / model_layers
            estimated_cpu_footprint = model_size * 1.1 * (model_layers - n_gpu_layers) / model_layers
            if model_size > 0 and available_vram > 0 and available_ram > 0 and estimated_gpu_footprint <= available_vram and estimated_cpu_footprint <= available_ram:
                return n_gpu_layers
            else:
                logger.error(f"Model '{self._model_info.name}' with {n_gpu_layers} GPU layers does not fit in available VRAM. "
                                f"Model size: {model_size} bytes, Estimated GPU footprint: {int(estimated_gpu_footprint)} bytes, "
                                f"Estimated CPU footprint: {int(estimated_cpu_footprint)} bytes, Available VRAM: {available_vram} bytes, "
                                f"Available RAM: {available_ram} bytes, Model layers: {model_layers}.")
                return None

    def __resolve_special_token(self, model: Llama, string_key: str, id_key: str, fallback: str = "") -> str:
        """
        Resolve a special token (BOS/EOS/etc.) from GGUF metadata.
        Tries the string form first, falls back to detokenizing the ID form,
        then falls back to a provided default.
        """
        # 1. Try direct string metadata
        token_str = model.metadata.get(string_key)
        if token_str:
            return token_str

        # 2. Try resolving from token ID
        token_id = model.metadata.get(id_key)
        if token_id is not None:
            try:
                tokenId = int(token_id)
                decoded = model.detokenize([tokenId]).decode("utf-8", errors="ignore")
                if decoded:
                    return decoded
            except (ValueError, TypeError):
                pass

        # 3. Try the model's built-in token_get_text if available (llama-cpp-python exposes this on some versions)
        try:
            if hasattr(model, "token_eos") and id_key.endswith("eos_token_id"):
                decoded = model.detokenize([model.token_eos()]).decode("utf-8", errors="ignore")
                if decoded:
                    return decoded
        except Exception: # noqa: BLE001, S110
            pass

        return fallback

    def __load_chat_handler(self, model: Llama):
        chat_template: str | None = None
        if self._model_info.jinja and os.path.exists(self._model_info.jinja) and os.path.isfile(self._model_info.jinja):
            with open(self._model_info.jinja, "r", encoding="utf-8") as f:
                chat_template = f.read()

        if not chat_template or len(chat_template.strip()) == 0:
            chat_template = model.metadata.get("tokenizer.chat_template")

        if not chat_template:
            logger.warning(f"No embedded or configured chat_template found; falling back to '{self._model_info.chat_format}'.")
            model.chat_format = self._model_info.chat_format
            return
        
        bos: str | None = self._model_info.bos
        if not bos:
            bos = self.__resolve_special_token(
                model,
                string_key="tokenizer.ggml.bos_token",
                id_key="tokenizer.ggml.bos_token_id",
                fallback="",
            )

        eos: str | None = self._model_info.eos
        if not eos:
            eos = self.__resolve_special_token(
                model,
                string_key="tokenizer.ggml.eos_token",
                id_key="tokenizer.ggml.eos_token_id",
                fallback="</s>",  # generic fallback, rarely used since template usually defines its own
            )

        logger.info(f"Resolved chat tokens — BOS: {bos!r}, EOS: {eos!r}")

        formatter = Jinja2ChatFormatter(
            template=chat_template,
            eos_token=eos,
            bos_token=bos,
            add_generation_prompt=True,  # confirm this kwarg exists in your installed version
        )

        model.chat_handler = formatter.to_chat_handler()

        # Store resolved eos_token on the model_info or model object so you can
        # pass it as a `stop` sequence at generation time too (belt-and-suspenders).
        self.__resolved_eos_token = eos

    def __load(self) -> Llama | None:
        nThreads = self.__get_n_threads()
        n_gpu_layers: int | None = self.__get_n_gpu_layers()
        if n_gpu_layers is None:
            return None  # Model cannot fit in available memory

        logger.info(f"Loading model '{self._model_info.name}' on {'GPU' if n_gpu_layers != 0 else 'CPU'}.")

        llama_kwargs: dict[str, Any] = {
            "model_path": self._model_info.model_path,
            "n_ctx": self._model_info.n_ctx,
            "n_gpu_layers": n_gpu_layers,
            "rope_freq_scale": self._model_info.rope_freq_scale,
            "n_threads": nThreads,
            "n_batch": self._model_info.n_batch,
            "verbose": False,
        }

        if "flash_attn" in _LLAMA_INIT_PARAMS:
            llama_kwargs["flash_attn"] = self._model_info.flash_attention
        elif "flash_attention" in _LLAMA_INIT_PARAMS:
            llama_kwargs["flash_attention"] = self._model_info.flash_attention
        elif self._model_info.flash_attention:
            logger.warning(
                "Installed llama_cpp binding does not expose a flash attention constructor option; continuing without it."
            )

        try:
            model: Llama = Llama(**llama_kwargs)
        except Exception as e: # noqa: BLE001
            logger.error(f"Failed to load model '{self._model_info.name}': {e}")
            return None

        # Extract the embedded chat template from GGUF metadata
        self.__load_chat_handler(model)

        return model

    def _load(self) -> None:
        with self.__inference_lock:
            if self.__model is None:
                self.__model = self.__load()

    def _unload(self) -> None:
        with self.__inference_lock:
            if self.__model is not None:
                self.__model.close()
                self.__model = None
                logger.info(f"Model '{self._model_info.name}' has been unloaded.")

    def _is_loaded(self) -> bool:
        return self.__model is not None
    #endregion

    #region Chat Handling    
    def __convert_logit_bias(self, input_bias: dict[str, float]) -> dict[int, float] | None:
        if self.__model is None:
            logger.error("Model is not loaded. Cannot convert logit bias.")
            return None
        
        result: dict[int, float] = {}

        for text, bias in input_bias.items():
            token_ids = self.__model.tokenize(text.encode("utf-8"))

            for tid in token_ids:
                result[tid] = bias

        return result

    def __build_chat_kwargs(self, request: RequestParams, stream: bool = False) -> dict:
        kwargs = {
            "messages": request.messages,
            "stop": [self.__resolved_eos_token] if self.__resolved_eos_token else self.__COMMON_STOP_SEQUENCES,
            "stream": stream,
        }

        optional_params = {
            "temperature": request.temperature,
            "top_k": request.top_k,
            "top_p": request.top_p,
            "typical_p": request.typical_p,
            "min_p": request.min_p,
            "tfs_z": request.tfs_z,
            "repeat_penalty": request.repeat_penalty,
            "max_tokens": request.max_tokens,
            "presence_penalty": request.presence_penalty,
            "frequency_penalty": request.frequency_penalty,
            "logit_bias": self.__convert_logit_bias(request.logit_bias) if request.logit_bias else None,
        }

        for key, value in optional_params.items():
            if value is not None:
                kwargs[key] = value

        return kwargs
    
    def chat(self, request: RequestParams) -> str | None:
        with self.__inference_lock:
            if not self._is_loaded():
                self.__model = self.__load()

            if self.__model is None:
                logger.error("Model is not loaded. Cannot perform chat.")
                return None

            response = self.__model.create_chat_completion(**self.__build_chat_kwargs(request))

            response_dict = cast(dict, response)
            choices = response_dict.get("choices", [])
            if not choices:
                return None

            message = choices[0].get("message", {})
            return message.get("content")
    
    def stream(self, request: RequestParams) -> Iterator[str] | None:
        def token_stream():
            with self.__inference_lock:
                if not self._is_loaded():
                    self.__model = self.__load()

                model = self.__model
                if model is None:
                    logger.error("Model is not loaded. Cannot perform streaming chat.")
                    return

                for chunk in model.create_chat_completion(**self.__build_chat_kwargs(request, stream=True)):
                    chunk_dict = cast(dict, chunk)
                    choices = chunk_dict.get("choices", [])
                    if not choices:
                        continue

                    delta = choices[0].get("delta", {})
                    text = delta.get("content")
                    if text:
                        yield text

        return token_stream()
    #endregion