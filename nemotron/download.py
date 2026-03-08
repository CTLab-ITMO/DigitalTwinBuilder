import os
from huggingface_hub import snapshot_download

# Указываем ваш токен
hf_token = ""

model_id = "nvidia/Nemotron-Orchestrator-8B"
save_directory = "./nemotron/nemotron-8b"

print(f"Начинаю загрузку {model_id}...")

# Запускаем скачивание с токеном
snapshot_download(
    repo_id=model_id,
    local_dir=save_directory,
    token=hf_token
)

print(f"Модель успешно загружена в папку {save_directory}")
