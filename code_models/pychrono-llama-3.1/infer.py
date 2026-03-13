import argparse
import json
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

MODEL_DIR = "./pychrono-llama-3.1/pychrono-llama3.1-8b"


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


def run_inference(prompt: str, max_new_tokens: int = 2048) -> str:
    tokenizer = AutoTokenizer.from_pretrained(MODEL_DIR)
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_DIR,
        dtype=torch.bfloat16,
        device_map="auto",
    )

    system_prompt = (
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

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]
    encoded = tokenizer.apply_chat_template(
        messages,
        add_generation_prompt=True,
        return_tensors="pt",
    )
    input_ids = encoded.input_ids.to(model.device) if hasattr(encoded, "input_ids") else encoded.to(model.device)

    with torch.no_grad():
        output_ids = model.generate(
            input_ids,
            max_new_tokens=max_new_tokens,
            do_sample=True,
            temperature=1,
            top_p=0.95,
            repetition_penalty=1.1,
            eos_token_id=tokenizer.eos_token_id,
            pad_token_id=tokenizer.eos_token_id,
        )

    generated = output_ids[0][input_ids.shape[-1]:]
    return tokenizer.decode(generated, skip_special_tokens=True)


OUTPUT_FILE = "./pychrono-llama-3.1/output.txt"


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
        description="Run PyChrono Llama 3.1 inference to generate a simulation script."
    )
    parser.add_argument("req_json", help="Path to requirements JSON file")
    parser.add_argument("db_json", help="Path to database schema JSON file")
    args = parser.parse_args()

    main(args.req_json, args.db_json)
