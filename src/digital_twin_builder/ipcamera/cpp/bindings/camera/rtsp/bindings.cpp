#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <camera/rtsp/client.hpp>

namespace py = pybind11;

PYBIND11_MODULE(_rtsp, m) {
    py::class_<camera::rtsp::client>(m, "rtsp")
        .def(py::init<const std::string &, int>(), py::arg("address"), py::arg("port"))
        .def("start", &camera::rtsp::client::setup)
        .def("stop", &camera::rtsp::client::play)
        .def("is_running", &camera::rtsp::client::teardown);
}
