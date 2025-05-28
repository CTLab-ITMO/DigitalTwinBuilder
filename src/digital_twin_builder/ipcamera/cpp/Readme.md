# IPCamera Module

The IPCamera module provides a set of bindings and utilities to interact with network cameras using different protocols such as RTSP and GigE Vision. This module is implemented using C++ and exposes functionality to Python using pybind11.

## Installing Python module

## Building in docker
### Setup
Port 53899 used as an example, you can change it to whatever you like, but don't forget to change it in python code too.
    ```bash
    docker build --tag "ipcamera" -f Dockerfile .
    docker run -p 53899:53899/udp -it ipcamera bash
    ```
Now you can use ipcamera module in docker

## Building locally
### Dependencies


The module depends on the following libraries:
- Boost (system component)
- libzip
- pugixml
- Python 3 (development components)

These dependencies are managed by vcpkg and should be automatically downloaded and configured during the build process if vcpkg and necessary system packages are present.

#### Ubuntu
1. Installing system packages
    ```bash
    apt-get update && apt-get install -y \
    build-essential \
    g++ \
    libcpprest-dev \
    libboost-all-dev \
    libssl-dev \
    libicu-dev \
    libbz2-dev \
    cmake \
    python3-dev \
    autoconf \
    automake \
    autoconf-archive \
    git \
    curl \
    zip \
    autotools-dev \
    pkg-config \
    wget
    ```

2. Installing vcpkg
    ```bash
    git clone https://github.com/microsoft/vcpkg.git /opt/vcpkg
    /opt/vcpkg/bootstrap-vcpkg.sh
    ```

    ```bash
    export VCPKG_ROOT=/opt/vcpkg
    export PATH="${VCPKG_ROOT}:${PATH}"
    ```


3. Intalling boost library
    ```bash
    wget -O boost_1_88_0.tar.gz https://sourceforge.net/projects/boost/files/boost/1.88.0/boost_1_88_0.tar.gz/download
    tar xzvf boost_1_88_0.tar.gz
    cd boost_1_88_0
    ./bootstrap.sh --prefix=/usr/
    ./b2 install
    ```

4. 
### Building

To build and install the IPCamera module, follow these steps:

1. Clone the repository:
   ```bash
   git clone github.com/CTLab-ITMO/DigitalTwinBuilder
   cd DigitalTwinBuilder/src/digital_twin_builder/ipcamera/cpp
   ```

2. Create a build directory and configure the project:
   ```bash
   mkdir build
   cmake "-DCMAKE_TOOLCHAIN_FILE=${VCPKG_ROOT}/scripts/buildsystems/vcpkg.cmake" "-DBOOST_ROOT=/usr/boost/" --preset Debug -S .
   ```

3. Build the project:
   ```bash
   cmake --build ./build
   ```

## Usage
    ```python
    from ipcamera.camera.gige import gige
    camera_ip = "192.168.150.15"
    my_ip = "192.168.1.94"
    streaming_port = 53899
    g = gige(camera_ip, my_ip, streaming_port)
    g.start_stream()
    print("Enter :q to quit")
    answer = ""
    while (answer != ":q"):
        answer = input()
    g.stop_stream()
    ```


## Directory Structure

- `src/`: Contains the source code for the camera implementations.
- `bindings/`: Contains the pybind11 binding code.
- `python/`: Contains python init files and compiled c++ code.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
