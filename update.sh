#!/usr/bin/env bash
set -e

ENV_NAME="sandboxed-llm"

# 1. Enter python environment
source ~/miniconda3/etc/profile.d/conda.sh
conda activate "$ENV_NAME"

# 2. Updates pip
pip install --upgrade pip

# 3. Updates FFmpeg
conda upgrade -c conda-forge ffmpeg

# 3. Updates Python packages with pip
pip install --upgrade ruff mypy pytest
pip install --upgrade fastapi uvicorn python-dotenv PyYAML types-PyYAML psutil types-psutil 
pip install --upgrade torch --extra-index-url https://download.pytorch.org/whl/cu133

# 3. Install llama-cpp-python with specific CMake settings
pip install --upgrade llama-cpp-python \
  --config-settings=cmake.args="-DGGML_CUDA=ON -DGGML_CUDA_F16=ON -DGGML_CUDA_DMMV=ON -DGGML_CUDA_KQUANTS=ON -DGGML_BLAS=ON -DGGML_BLAS_VENDOR=OpenBLAS"
