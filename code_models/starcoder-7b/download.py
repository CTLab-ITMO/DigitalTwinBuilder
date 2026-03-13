import os
from huggingface_hub import snapshot_download

# Указываем ваш токен
hf_token = ""

model_id = "bigcode/starcoder2-7b"
save_directory = "./code_models/starcoder-7b/starcoder2-7b"

print(f"Начинаю загрузку {model_id}...")

snapshot_download(
    repo_id=model_id,
    local_dir=save_directory,
    token=hf_token
)

print(f"Модель успешно загружена в папку {save_directory}")
