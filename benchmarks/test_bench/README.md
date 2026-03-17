# Cement Plant Digital Twin — Test Bench

Статический анализ кода цифрового двойника цементного производства, сгенерированного различными LLM.

## Структура

| Файл | Описание |
|------|----------|
| `task.md` | Задание для LLM (требования, DB schema) |
| `*_code.py` | Код, сгенерированный разными моделями |
| `tests.py` | 16 семантических тестов статического анализа (AST) |
| `requirements.txt` | Python-зависимости для тестов |
| `run_test.sh` | Скрипт запуска тестов (ставит зависимости перед прогоном) |
| `results.md` | Результаты тестов (генерируется автоматически) |

## Запуск тестов

### Все файлы

```bash
./run_test.sh
```

или

```bash
python3 tests.py
```

### Один файл

```bash
python3 tests.py qwen_code.py
```

### JSON-вывод

```bash
python3 tests.py --json
```

## Описание тестов

16 семантических тестов проверяют соответствие кода требованиям из `task.md`:

| # | Тест | Что проверяет |
|---|------|---------------|
| T01 | Non-empty file | Файл не пустой |
| T02 | Syntax valid | Код синтаксически корректен (ast.parse) |
| T03 | Imports pychrono | Импорт любого `pychrono*` |
| T04 | Initializes system | Инициализация `ChSystemNSC/SMC` |
| T05 | Sets gravity | `Set_G_acc` или `SetGravity` |
| T06 | Equipment bodies | Создание физических тел оборудования (>=4 тел) |
| T07 | Adds objects | Регистрация объектов в системе (`Add*`) |
| T08 | Materials | Материалы явные или неявные (через плотность/SetMaterialSurface) |
| T09 | Joints/constraints | Наличие `ChLink*` (связи/ограничения/моторы) |
| T10 | Required sensors | Моделирование сенсоров (>=4/5 категорий: T/P/fineness/gas/load) |
| T11 | Step in loop | `DoStepDynamics` внутри `for/while` |
| T12 | DB-logging compatible | Логирование через SQL-таблицы или dict с ключами `timestamp/value/sensor_id/plant_id` |
| T13 | Critical parameters | Упоминание 1450/1480 и CO 0.1 |
| T14 | Error handling | `try/except` |
| T15 | Cleanup | `finally` или `close/clear/remove` |
| T16 | Main entry | `if __name__ == '__main__'` |

## Результаты

После запуска тестов файл `results.md` обновляется автоматически с таблицей результатов и процентом пройденных тестов по каждому файлу.
