#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <camera/client.hpp>

namespace py = pybind11;

PYBIND11_MODULE(camera, m) {
    py::class_<camera::client>(m, "camera")
        .def(py::init<>())
        .def("start", &camera::client::start)
        .def("stop", &camera::client::stop)
        .def("is_running", &camera::client::is_running)
        .def("get_image", &camera::client::get_image);
}
