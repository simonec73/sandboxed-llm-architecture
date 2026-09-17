#!/usr/bin/env bash
set -e

ENV_NAME="parametrized-llm"

# 1. Create python environment
source ~/miniconda3/etc/profile.d/conda.sh
conda create -y -n "$ENV_NAME" python=3.12
conda activate "$ENV_NAME"

# 2. Install Python packages with pip
pip install ruff mypy pytest
pip install fastapi uvicorn python-dotenv PyYAML types-PyYAML psutil types-psutil 
pip install torch --extra-index-url https://download.pytorch.org/whl/cu133

# 3. Install llama-cpp-python with specific CMake settings
pip install llama-cpp-python \
  --config-settings=cmake.args="-DGGML_CUDA=ON -DGGML_CUDA_F16=ON -DGGML_CUDA_DMMV=ON -DGGML_CUDA_KQUANTS=ON -DGGML_BLAS=ON -DGGML_BLAS_VENDOR=OpenBLAS"
