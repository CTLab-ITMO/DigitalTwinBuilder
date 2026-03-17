enerate a complete PyChrono simulation script for the digital twin.

Requirements:
{
  "production_type": "цементное производство",
  "processes": [
    "добыча и дробление сырья",
    "помол сырьевой муки",
    "обжиг клинкера во вращающейся печи",
    "охлаждение клинкера",
    "помол цемента",
    "отгрузка"
  ],
  "equipment": [
    "дробилка",
    "сырьевая мельница",
    "вращающаяся печь",
    "колосниковый холодильник",
    "цементная мельница",
    "силосы"
  ],
  "sensors": [
    "температура в печи",
    "разрежение в циклонах",
    "тонкость помола",
    "состав отходящих газов (CO, NOx)",
    "уровень загрузки мельницы"
  ],
  "goals": "стабилизация качества клинкера, снижение удельного расхода топлива, уменьшение выбросов CO2",
  "data_sources": "датчики в печи, газоанализаторы, лаборатория",
  "update_frequency": {
    "температура": "1 раз в минуту",
    "газоанализ": "каждые 10 секунд",
    "лаборатория": "1 раз в час"
  },
  "critical_parameters": {
    "температура спекания": "1450-1480°C",
    "содержание свободной извести в клинкере": "< 1.5%",
    "CO в отходящих газах": "< 0.1%"
  },
  "additional_info": "уровень загрузки мельницы также важен для контроля производительности"
}

Database Schema:
{
  "tables": {
    "plant_data": {
      "name": "plant_data",
      "columns": [
        {
          "name": "id",
          "data_type": "serial PRIMARY KEY",
          "constraints": []
        },
        {
          "name": "timestamp",
          "data_type": "TIMESTAMP WITH TIME ZONE",
          "constraints": [
            "NOT NULL"
          ]
        },
        {
          "name": "value",
          "data_type": "DOUBLE PRECISION",
          "constraints": [
            "NOT NULL"
          ]
        },
        {
          "name": "sensor_id",
          "data_type": "integer",
          "constraints": [
            "NOT NULL",
            "REFERENCES sensor_metadata(id) ON DELETE CASCADE"
          ]
        },
        {
          "name": "plant_id",
          "data_type": "integer",
          "constraints": [
            "NOT NULL",
            "REFERENCES metadata(id) ON DELETE CASCADE"
          ]
        }
      ],
      "relationships": [
        {
          "from_table": "sensor_metadata",
          "to_table": "plant_data",
          "foreign_key": "id",
          "local_key": "sensor_id",
          "type": "many_to_many"
        },
        {
          "from_table": "metadata",
          "to_table": "plant_data",
          "foreign_key": "id",
          "local_key": "plant_id",
          "type": "many_to_many"
        }
      ]
    },
    "sensor_metadata": {
      "name": "sensor_metadata",
      "columns": [
        {
          "name": "id",
          "data_type": "serial PRIMARY KEY",
          "constraints": []
        },
        {
          "name": "sensor_type",
          "data_type": "VARCHAR(255)",
          "constraints": [
            "NOT NULL"
          ]
        },
        {
          "name": "location",
          "data_type": "VARCHAR(255)",
          "constraints": [
            "NOT NULL"
          ]
        },
        {
          "name": "calibration_status",
          "data_type": "BOOLEAN",
          "constraints": [
            "NOT NULL"
          ]
        },
        {
          "name": "sensor_id",
          "data_type": "integer",
          "constraints": [
            "NOT NULL",
            "UNIQUE"
          ]
        }
      ],
      "relationships": [
        {
          "from_table": "plant_data",
          "to_table": "sensor_metadata",
          "foreign_key": "id",
          "local_key": "sensor_id",
          "type": "many_to_one"
        }
      ]
    },
    "metadata": {
      "name": "metadata",
      "columns": [
        {
          "name": "id",
          "data_type": "serial PRIMARY KEY",
          "constraints": []
        },
        {
          "name": "plant_name",
          "data_type": "VARCHAR(255)",
          "constraints": [
            "NOT NULL"
          ]
        },
        {
          "name": "location",
          "data_type": "VARCHAR(255)",
          "constraints": [
            "NOT NULL"
          ]
        },
        {
          "name": "version",
          "data_type": "integer",
          "constraints": [
            "NOT NULL"
          ]
        },
        {
          "name": "last_updated",
          "data_type": "TIMESTAMP WITH TIME ZONE",
          "constraints": [
            "NOT NULL"
          ]
        }
      ],
      "relationships": [
        {
          "from_table": "plant_data",
          "to_table": "metadata",
          "foreign_key": "id",
          "local_key": "plant_id",
          "type": "many_to_many"
        }
      ]
    },
    "configuration": {
      "name": "configuration",
      "columns": [
        {
          "name": "id",
          "data_type": "serial PRIMARY KEY",
          "constraints": []
        },
        {
          "name": "key",
          "data_type": "VARCHAR(255)",
          "constraints": [
            "NOT NULL"
          ]
        },
        {
          "name": "value",
          "data_type": "VARCHAR(255)",
          "constraints": [
            "NOT NULL"
          ]
        },
        {
          "name": "plant_id",
          "data_type": "integer",
          "constraints": [
            "NOT NULL",
            "REFERENCES metadata(id) ON DELETE CASCADE"
          ]
        }
      ],
      "relationships": [
        {
          "from_table": "metadata",
          "to_table": "configuration",
          "foreign_key": "id",
          "local_key": "plant_id",
          "type": "many_to_many"
        }
      ]
    },
    "system_config": {
      "name": "system_config",
      "columns": [
        {
          "name": "id",
          "data_type": "serial PRIMARY KEY",
          "constraints": []
        },
        {
          "name": "setting",
          "data_type": "VARCHAR(255)",
          "constraints": [
            "NOT NULL"
          ]
        },
        {
          "name": "value",
          "data_type": "BOOLEAN",
          "constraints": [
            "NOT NULL"
          ]
        },
        {
          "name": "type",
          "data_type": "VARCHAR(255)",
          "constraints": [
            "NOT NULL"
          ]
        }
      ],
      "relationships": [
        {
          "from_table": "configuration",
          "to_table": "system_config",
          "foreign_key": "id",
          "local_key": "configuration_id",
          "type": "many_to_many"
        }
      ]
    }
  }
}

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
Start directly with import statements.