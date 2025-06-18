from transformers import pipeline
import os

try:
    cotyope_pipe = pipeline("text-generation", model="MTSAIR/Cotype-Nano", device="cuda")
    code_llama_pipe = pipeline("text-generation", model="bugdaryan/Code-Llama-2-13B-instruct-text2sql", device="cuda")
    print("Models loaded successfully on CUDA.")
except Exception as e:
    print(f"Error loading models on CUDA, attempting CPU: {e}")
    cotyope_pipe = pipeline("text-generation", model="MTSAIR/Cotype-Nano")
    code_llama_pipe = pipeline("text-generation", model="bugdaryan/Code-Llama-2-13B-instruct-text2sql")
    print("Models loaded successfully on CPU.")

model_call_count = 0

def model_call(prompt, model='Cotype-Nano'):
    global model_call_count
    model_call_count += 1

    if model == 'Cotype-Nano':
        model_output = cotyope_pipe(prompt, max_length=2048, num_return_sequences=1)[0]['generated_text']  
    elif model == 'CodeLlama-2-13B':
        instruction = "Generate SQL based on the following text:"
        full_prompt = f"<s>[INST] {instruction} {prompt} [/INST]"
        model_output = code_llama_pipe(full_prompt, max_length=2048, num_return_sequences=1)[0]['generated_text'] 
    else:
        raise ValueError(f"Invalid model name: {model}.  Must be 'Cotype-Nano' or 'CodeLlama-2-13B'.")
    return model_output.strip()
