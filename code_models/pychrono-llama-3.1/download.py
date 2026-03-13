import os
from huggingface_hub import snapshot_download

# Указываем ваш токен
hf_token = ""

model_id = "jwang2373/pychrono_llama3.1_8b_SFT"
save_directory = "./code_models/pychrono-llama-3.1/pychrono-llama3.1-8b"

print(f"Начинаю загрузку {model_id}...")

snapshot_download(
    repo_id=model_id,
    local_dir=save_directory,
    token=hf_token
)

print(f"Модель успешно загружена в папку {save_directory}")
