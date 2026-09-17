
from dataclasses import dataclass


@dataclass
class ModelInfo:
    name: str                                    # Name of the model
    host: str                                    # Host of the model (e.g., "llamacpp", "openvino", etc.)
    model_path: str                              # Full path to the model file
    jinja: str | None = None                     # Jinja template for the model. It has the highest priority if provided. If not provided, the model will try to use the embedded chat_template. If that is not available, it will fall back to the chat_format.
    bos: str | None = None                       # Beginning of sequence token. It has the highest priority if provided. If not provided, the model will try to use the bosToken from the embedded metadata. If that is not available, it will fall back to '<s>'.'.
    eos: str | None = None                       # End of sequence token. It has the highest priority if provided. If not provided, the model will try to use the eosToken from the embedded metadata. If that is not available, it will fall back to '</s>'.
    chat_format: str | None = None               # Chat format of the model (can be 'llama-2', 'llama-3', 'alpaca', 'qwen', 'vicuna', 'oasst_llama', 'baichuan-2', 'baichuan', 'openbuddy', 'redpajama-incite', 'snoozy', 'phind', 'intel', 'open-orca', 'mistrallite', 'zephyr', 'pygmalion', 'chatml', 'mistral-instruct', 'chatglm3', 'openchat', 'saiga', 'gemma', 'functionary', 'functionary-v2', 'functionary-v1', 'chatml-function-calling')
    n_ctx: int = 3048                            # Number of context tokens
    n_gpu_layers: int = -1                       # Number of GPU layers
    rope_freq_scale: float = 1.0                 # RoPE frequency scale
    flash_attention: bool = True                 # Use flash attention
    n_threads: int = -1                          # Number of threads (-1 for automatic: 1 for each core - 2 for hyperthreading)
    n_batch: int = 512                           # Batch size

@dataclass
class RequestParams:
    messages: list[dict[str, str]]               # List of messages for the chat
    data: list[dict[str, str]] | None = None     # List of structured data nodes for the chat, optional
    temperature: float | None = None             # Indication of how much randomness to introduce into the output: 0.0 (deterministic) to 1.0 (highly random)
    top_k: int | None = None                     # The number of highest probability vocabulary tokens to keep for top-k-filtering
    top_p: float | None = None                   # The cumulative probability for nucleus sampling (top-p)
    typical_p: float | None = None               # The cumulative probability for typical sampling (typical-p)
    min_p: float | None = None                   # The minimum probability for sampling (min-p)
    tfs_z: float | None = None                   # The threshold for tail-free sampling (TFS)
    repeat_penalty: float | None = None          # The penalty factor for repeated tokens (values > 1.0 penalize repetition, values < 1.0 encourage it)
    max_tokens: int | None = None                # The maximum number of tokens to predict in the response (cuts off the response if it exceeds this limit)
    presence_penalty: float | None = None        # The penalty factor for the presence of certain tokens (values > 0.0 penalize presence, values < 0.0 encourage it)
    frequency_penalty: float | None = None       # The penalty factor for the frequency of certain tokens (values > 0.0 penalize frequency, values < 0.0 encourage it)
    logit_bias: dict[str, float] | None = None   # The bias for specific tokens (string → bias)