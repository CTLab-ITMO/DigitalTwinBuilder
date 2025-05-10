#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include "camera/rtsp/client.hpp"

namespace py = pybind11;

PYBIND11_MODULE(_rtsp, m) {
    py::class_<camera::rtsp::client>(m, "rtsp")
        .def(py::init<const std::string &, uint16_t>(), py::arg("address"), py::arg("port"))
        .def("setup", &camera::rtsp::client::setup)
        .def("play", &camera::rtsp::client::play)
        .def("teardown", &camera::rtsp::client::teardown);
}
