# Use the official Ubuntu image as the base image
FROM ubuntu:latest

# Install necessary dependencies
RUN apt-get update && apt-get install -y \
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
    pkg-config

RUN git clone https://github.com/microsoft/vcpkg.git /opt/vcpkg
RUN /opt/vcpkg/bootstrap-vcpkg.sh

# Set the toolchain path as an environment variable
ENV VCPKG_ROOT=/opt/vcpkg
ENV PATH="${VCPKG_ROOT}:${PATH}"

RUN apt install wget

WORKDIR /opt
RUN wget -O boost_1_88_0.tar.gz https://sourceforge.net/projects/boost/files/boost/1.88.0/boost_1_88_0.tar.gz/download
RUN tar xzvf boost_1_88_0.tar.gz
WORKDIR /opt/boost_1_88_0
RUN ./bootstrap.sh --prefix=/usr/
RUN ./b2 install

WORKDIR /digital_twin_builder/src/digital_twin_builder/ipcamera/cpp/

COPY ./src/digital_twin_builder/ipcamera/cpp/vcpkg.json .

RUN ${VCPKG_ROOT}/vcpkg install

COPY ./src/digital_twin_builder/ipcamera/cpp/ .

RUN mkdir -p build
RUN rm -rf build/*
RUN cmake "-DCMAKE_TOOLCHAIN_FILE=${VCPKG_ROOT}/scripts/buildsystems/vcpkg.cmake" "-DBOOST_ROOT=/usr/boost/" --preset Debug -S .
RUN cmake --build ./build

WORKDIR /digital_twin_builder

RUN apt install -y python3-full python3-pip python3-venv

COPY requirements.txt .
RUN python3 -m venv .venv
RUN . .venv/bin/activate
RUN .venv/bin/python3 -m pip install --upgrade pip
RUN .venv/bin/python3 -m pip install -r requirements.txt
COPY . .
RUN .venv/bin/python3 -m pip install -e .

# Command to run the API when the container starts
