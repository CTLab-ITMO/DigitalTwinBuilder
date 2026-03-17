import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../src'))
from digital_twin_builder.config import LLM_MODEL

def evaluate_json(client, expected, actual):
    prompt = "Необходимо оценить насколько построенный json соответствует ожидаемому, оценивать нужно только существенные различия, такие как различающиеся числовые значения, пропущенные данные и так далее. Оценку необходимо дать от 0 до 1, где 0 - json файлы содержат полностью разные данные, 1 - json файлы содержат одни и те же данные. ВАЖНО: обоснование должно быть максимально кратким, сплошным тесктом, без markdown форматирования, без переноса строк\nОтвет вывести в формате: \n[число] \n[oбоснование]"
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": f"Ожидаемый: ```json{expected}``` Построенный: ```json{actual}```"}
    ]
    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=messages,
        stream=False
    )
    return response.choices[0].message.content
