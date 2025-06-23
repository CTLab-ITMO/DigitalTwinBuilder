#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include "camera/client.hpp"

namespace py = pybind11;

PYBIND11_MODULE(_camera, m) {
    py::class_<camera::client>(m, "camera_client")
        .def(py::init<>())
        .def("start", &camera::client::start)
        .def("stop", &camera::client::stop)
        .def("is_running", &camera::client::is_running);
}
