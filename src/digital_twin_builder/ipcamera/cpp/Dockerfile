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

WORKDIR /app

COPY vcpkg.json .

RUN ${VCPKG_ROOT}/vcpkg install

COPY . .

RUN mkdir -p build
RUN rm -rf build/*
RUN cmake "-DCMAKE_TOOLCHAIN_FILE=${VCPKG_ROOT}/scripts/buildsystems/vcpkg.cmake" "-DBOOST_ROOT=/usr/boost/" --preset Debug -S .
RUN cmake --build ./build

# Command to run the API when the container starts
CMD ["./build/main"]
