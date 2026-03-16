import json
from jsonschema import validate
from Levenshtein import distance as levenshtein_distance

def compare_values(answer, model_output):
    # base case
    if isinstance(answer, (bool, int, float)):
            return 1 if answer == model_output else 0
    elif isinstance(answer, str):
        if not isinstance(model_output, str):
            return 0
        # use levenshtein distance to calculate similarity for string
        max_len = max(len(answer), len(model_output))
        if max_len == 0: # both empty string
            return 1
        lev_distance = levenshtein_distance(answer, model_output)
        return (max_len - lev_distance) / max_len
    # list case
    elif isinstance(answer, list):
        # if list is empty, return 1 when model output is also empty
        if not answer:
            return 1 if (isinstance(model_output, list) and not model_output) else 0

        # if list of dict, compare index by index
        if all(isinstance(item, dict) for item in answer):
            if not isinstance(model_output, list) or not all(isinstance(item, dict) for item in model_output):
                return 0
            
            score = 0
            min_len = min(len(answer), len(model_output))
            max_len = max(len(answer), len(model_output)) ## as it is hard for list of dict to calculate union, use max length to substitute

            for i in range(min_len):
                score += compare_values(answer[i], model_output[i])

            return score / max_len if (max_len > 0) else 1
        
        # if list of base data types, compute Jaccard similarity
        else:
            if not isinstance(model_output, list):
                return 0
            
            answer_set = set(answer)
            model_output_set = set(model_output)

            common_elements = answer_set & model_output_set
            all_elements = answer_set | model_output_set

            return len(common_elements) / len(all_elements) if all_elements else 1

    # dict case   
    elif isinstance(answer, dict):
        if not isinstance(model_output, dict):
            return 0
        
        answer_keys = set(answer.keys())
        if not answer_keys: # empty dict
                return 1 if not model_output else 0
        
        all_keys = answer_keys.union(set(model_output.keys()))

        score = 0
        for key in answer_keys:
            if key in model_output:
                # compare the value in common keys recursively
                score += compare_values(answer[key], model_output[key])

        return score / len(all_keys) if all_keys else 1
    
    # other data types 
    else:
        return 0



def json_evaluation_new(model_output_json: dict, answer_json: dict, schema: dict):
    try:
        validate(instance=model_output_json, schema=schema)
    except:
        return 0, 0, "JSON output doesn't match the schema"
    
    format_score = 1

    similarity_score = compare_values(answer_json, model_output_json)

    return format_score, similarity_score, "Give score in 3 criteria"