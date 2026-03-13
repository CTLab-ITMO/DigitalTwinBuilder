import os
from huggingface_hub import snapshot_download

# Указываем ваш токен
hf_token = ""

model_id = "Qwen/Qwen3-Coder-30B-A3B-Instruct"
save_directory = "./code_models/qwen3-coder-30b/qwen3-coder-30b"

print(f"Начинаю загрузку {model_id}...")

snapshot_download(
    repo_id=model_id,
    local_dir=save_directory,
    token=hf_token
)

print(f"Модель успешно загружена в папку {save_directory}")
