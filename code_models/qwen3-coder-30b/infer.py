import argparse
import json
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

MODEL_DIR = "./qwen3-coder-30b/qwen3-coder-30b"

# Распределение по 4 GPU: cuda:1, cuda:2, cuda:3, cuda:4
GPU_MEMORY = {1: "80GiB", 2: "80GiB", 3: "80GiB", 4: "80GiB", "cpu": "0GiB"}

SYSTEM_PROMPT = (
        "You are an expert Python developer specializing in the PyChrono multi-physics simulator.\n"
        "Based on the provided requirements for a digital twin and the database schema, generate a complete, executable Python script that creates a PyChrono simulation.\n"
        "The script should:\n"
        "- Initialize the PyChrono system.\n"
        "- Define physical bodies, materials, joints, and any other necessary components based on the requirements.\n"
        "- Set up the simulation environment (terrain, gravity, etc.).\n"
        "- Implement the main simulation loop.\n"
        "- Log or output simulation data that corresponds to the tables and fields defined in the database schema.\n"
        "- Include necessary imports, comments, and follow PyChrono best practices.\n"
        "The output should be only the Python code, without any markdown code block markers (no ```python or ```)."
    )


def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def generate_prompt(requirements: dict, db_schema: dict) -> str:
    return f"""Generate a complete PyChrono simulation script for the digital twin.

Requirements:
{json.dumps(requirements, ensure_ascii=False, indent=2)}

Database Schema:
{json.dumps(db_schema, ensure_ascii=False, indent=2)}

The Python script should:
1. Import necessary PyChrono modules
2. Initialize the Chrono system
3. Create physical bodies representing equipment (furnaces, crystallizers, rollers, etc.)
4. Set up materials with appropriate properties (steel, refractory, etc.)
5. Define joints and constraints between bodies
6. Implement sensors to measure simulation parameters
7. Create a simulation loop that:
   - Steps the simulation forward in time
   - Collects sensor data
   - Logs data that matches the database schema tables
8. Include error handling and proper cleanup

The code should be production-ready and executable. Do not include markdown formatting or code blocks.
Start directly with import statements."""


def run_inference(prompt: str, max_new_tokens: int = 4096) -> str:
    tokenizer = AutoTokenizer.from_pretrained(MODEL_DIR)
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_DIR,
        torch_dtype=torch.bfloat16,
        device_map="auto",
        max_memory=GPU_MEMORY,
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]

    text = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
    )
    model_inputs = tokenizer([text], return_tensors="pt").to(model.device)

    with torch.no_grad():
        generated_ids = model.generate(
            **model_inputs,
            max_new_tokens=max_new_tokens,
            do_sample=True,
            temperature=0.7,
            top_p=0.8,
            top_k=20,
            repetition_penalty=1.05,
        )

    output_ids = generated_ids[0][len(model_inputs.input_ids[0]):].tolist()
    return tokenizer.decode(output_ids, skip_special_tokens=True)


OUTPUT_FILE = "./qwen3-coder-30b/output.txt"


def save_output(prompt: str, result: str) -> None:
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("=== Prompt ===\n")
        f.write(prompt + "\n\n")
        f.write("=== Output ===\n")
        f.write(result + "\n")


def main(req_path: str, db_path: str) -> str:
    requirements = load_json(req_path)
    db_schema = load_json(db_path)

    model_input = generate_prompt(requirements, db_schema)
    print("Generating...")

    result = run_inference(model_input)
    save_output(model_input, result)
    print(f"Done. Result saved to {OUTPUT_FILE}")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run Qwen3-Coder-30B inference to generate digital twin configuration."
    )
    parser.add_argument("req_json", help="Path to requirements JSON file")
    parser.add_argument("db_json", help="Path to database schema JSON file")
    args = parser.parse_args()

    main(args.req_json, args.db_json)
