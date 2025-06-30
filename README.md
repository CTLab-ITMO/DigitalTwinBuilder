# DigitalTwinBuilder
## Автоматизированное построение цифрового двойника производства

В данном репозитории разрабатывается библиотека с открытым кодом, включающую мультиагентную систему, агенты которой проведут опрос работников завода, спроектируют и создадут базу данных для цифрового двойника, а также сконфигурируют цифрового двойника производства. Библиотека включает конструктор для построения цифрового двойника, а также панель мониторинга получаемых данных. Также в репозитории содержится библиотека для взаимодействия с камерами видеонаблюдения и датчиками.

Библиотека поддерживает получение сигнала со следующих датчиков:
* Температуры; 
* Уровня; 
* Вибрации; 
* Давления;
* Износа;
* [RFID](https://sauk.ru/).

Библиотека поддерживает следующие протоколы к ip камер видеонаблюдения для построения производства и дальнейшего анализа: 
* [Gige Vision](https://www.automate.org/vision/vision-standards/vision-standards-gige-vision) - интерфейс передачи данных для цифровых камер промышленного класса
* [RTSP](https://datatracker.ietf.org/doc/html/rfc7826) - протокол для организации трансляций и передачи медиаконтента
* [ONVIF](https://www.onvif.org/profiles/) - протокол, который подробно описывает, как сетевые устройства передачи видео ( IP-камеры, видеорегистраторы), интегрируются с сетевыми программами обработки и отображения видеопотока.

## Project structure

```
DigitalTwinBuilder/
├── src/
│   └── DigitalTwinBuilder/ 
│       ├── DTlibrary/
│       │   ├── agents/
│       │   │   ├── __init__.py
│       │   │   ├── base_agent.py
│       │   │   ├── user_interaction_agent.py
│       │   │   ├── database_agent.py
│       │   │   └── digital_twin_agent.py
│       │   │   
│       │   ├── core/
│       │   │   ├── __init__.py
│       │   │   ├── database.py
│       │   │   ├── models.py
│       │   │   └── sensor_manager.py
│       │   │   
│       │   ├── sensors/
│       │   │   ├── __init__.py
│       │   │   ├── base_sensor.py
│       │   │   ├── level_sensor.py
│       │   │   ├── pressure_sensor.py
│       │   │   ├── rfid_sensor.py
│       │   │   ├── temperature_sensor.py
│       │   │   ├── vibration_sensor.py
│       │   │   └── wear_sensor.py
│       │   │ 
│       │   ├── main.py   
│       │   ├── web_interface.py   
│       │   └── requirements.txt 
│       │   
│       └── ipcamera/             # git submodule (later may be removed and added with PyPI package)
│           ├── cpp/
│           │   ├── src/
│           │   │   └── camera/
│           │   │       ├── client.cpp
│           │   │       ├── client.hpp
│           │   │       ├── CMakeLists.txt
│           │   │       ├── gige
│           │   │           └── ...
│           │   │       └── rtsp
│           │   │           └── ...
│           │   │
│           │   ├── bindings/
│           │   │   └── camera/
│           │   │       ├── bindings.cpp
│           │   │       ├── CMakeLists.txt
│           │   │       ├── gige
│           │   │           └── ...
│           │   │       └── rtsp
│           │   │           └── ...
│           │   │
│           │   ├── python/
│           │   │   └── ipcamera/
│           │   │       ├── __init__.py
│           │   │       └── camera/
│           │   │           ├── __init__.py
│           │   │           ├── camera.so
│           │   │           ├── gige
│           │   │           |   └── ...
│           │   │           └── rtsp
│           │   │               └── ...
│           │   │
│           │   └── CMakeLists.txt
│           ├── __init__.py   
│           └── _core.so 
├── main.py 
├── scripts/
├── tests/
├── setup.py
├── requirements.txt
└── README.md
```

## Building from source
### Installing dependencies
#### MacOS
```bash
brew install gcc cmake vcpkg boost
```
#### Fedora, CentOS
```bash
sudo dnf install gcc cmake vcpkg boost-devel
```
### IP camera module
```bash
mkdir -p build
rm -rf build/*
cmake -DCMAKE_TOOLCHAIN_FILE=$VCPKG_ROOT -DBOOST_ROOT=$BOOST_ROOT --preset Debug -S .
cmake --build ./build
```
Для запуска используйте бинарный файл ```./build/main```
## License

This project is licensed under the MIT License - see the [LICENSE](https://github.com/lizaelisaveta/DigitalTwinOfProduction/blob/main/LICENSE) file for details.
