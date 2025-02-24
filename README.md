# DigitalTwinBuilder
## Автоматизированное построение цифрового двойника производства

В данном репозитории разрабатывается библиотека с открытым кодом, включающую LLM, которая проанализирует документацию и проведет опрос работников завода, совместив это с анализом данных с камер видеонаблюдения для построения цифрового двойника производства. Библиотека включает конструктор для построения цифрового двойника, а также рекомендации по контролю производственных процессов.

Библиотека поддерживает следующие протоколы к ip камер видеонаблюдения для построения производства и дальнейшего анализа: 
* [Gige Vision](https://www.automate.org/vision/vision-standards/vision-standards-gige-vision) - интерфейс передачи данных для цифровых камер промышленного класса
* [RTSP](https://datatracker.ietf.org/doc/html/rfc7826) - протокол для организации трансляций и передачи медиаконтента
* [ONVIF](https://www.onvif.org/profiles/) - протокол, который подробно описывает, как сетевые устройства передачи видео ( IP-камеры, видеорегистраторы), интегрируются с сетевыми программами обработки и отображения видеопотока.

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
