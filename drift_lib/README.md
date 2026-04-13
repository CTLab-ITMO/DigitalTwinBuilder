# dataset

Небольшой набор вещей вокруг датасета диалогов и детектора дрейфа по эмбеддингам.

## Что лежит в репо

- `train_dataset_qwen_32b.json` — записи с полем `dialog` (внутри обычно `meta_info` и массив сообщений).
- **`drift_lib/`** — пакет Python: E5 (`intfloat/multilingual-e5-small`, 384), онлайн MMD, чтение JSON, скрипты и SQL для Postgres.
- `drift_lib/db/schema.sql` — таблицы под PostgreSQL + pgvector (`user_query_events`, `embedding_drift_alerts`).
- `drift_lib/db/pg_insert_example.py` — вставка запроса и вектора через пакет **`pgvector`** (`register_vector` + numpy), с запасным режимом строкового литерала.
- `drift_lib/scripts/dialog_drift_scan.py` — читает JSON, режет диалоги на окна, считает эмбеддинги и прогоняет детектор (см. `--help`).

## Установка

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

(`requirements.txt` в корне подключает `drift_lib/requirements.txt`.)

Перед вставками в БД выполни `drift_lib/db/schema.sql` в своём инстансе Postgres (нужен пакет [pgvector](https://github.com/pgvector/pgvector) на сервере).

## Скрипт по датасету

Из корня этого каталога (`PYTHONPATH=.` должен указывать на каталог **dataset**, чтобы импортировался пакет `drift_lib`):

```bash
PYTHONPATH=. python drift_lib/scripts/dialog_drift_scan.py --max-dialogs 5
```

Большой файл читается потоково через `ijson`. Если файл маленький и помещается в память — `--json-load-all`.

## Без PostgreSQL

База только для сохранения запросов в проде; **детектор и MMD от БД не зависят**.

### Smoke: как гонять детектор

Оба смоука **обязательно гоняют intfloat/multilingual-e5-small** (`sentence-transformers`, при первом запуске — скачивание весов). MMD в смоуках по умолчанию через NumPy (`mmd_backend="numpy"`).

**Если падает импорт (TensorFlow / Keras / `tf_keras` / `CodeCarbonCallback`):**

```bash
pip uninstall -y tensorflow tensorflow-intel tf_keras keras
pip install -U -r drift_lib/requirements.txt
export TRANSFORMERS_NO_TF=1
```

Эмбеддер по умолчанию на **CPU** (`ST_DEVICE`, по умолчанию `cpu`) и при CPU задаёт пустой `CUDA_VISIBLE_DEVICES`, чтобы реже трогать драйвер CUDA. Для GPU: `ST_DEVICE=cuda:0`.

**Если torch ругается на старый драйвер CUDA**, поставь CPU-сборку PyTorch:  
`pip install --upgrade torch --index-url https://download.pytorch.org/whl/cpu`

1. **Без JSON** — две пачки разных текстов → E5 → детектор:

   `PYTHONPATH=. python drift_lib/scripts/smoke_drift_no_db.py`

2. **Твой JSON** — `ijson`, первый диалог из `train_dataset_qwen_32b.json`, окна → E5 → детектор:

   `PYTHONPATH=. python drift_lib/scripts/smoke_drift_from_json.py`

   Параметры: `python drift_lib/scripts/smoke_drift_from_json.py --help`.

В коде детектора `mmd_backend="auto"`: сначала alibi, при ошибке импорта — `drift_lib/mmd_numpy.py`.

Для отладки без трансформеров остаётся класс `HashEmbeddingModel` в `drift_lib/embedding_model.py`, но **смоук-скрипты его не используют**.

## Прочее

- `download.py` — выгрузка из YT-таблицы, к этому репо отношения почти нет.
