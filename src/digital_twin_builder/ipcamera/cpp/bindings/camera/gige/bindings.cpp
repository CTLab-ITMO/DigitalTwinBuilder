#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include "camera/gige/client.hpp"

namespace py = pybind11;

PYBIND11_MODULE(_gige, m) {
    py::class_<camera::gige::client>(m, "gige")
        .def(py::init<const std::string&, const std::string&, uint16_t>(), py::arg("tx_address"), py::arg("rx_address"), py::arg("port"))
        .def("start_stream", &camera::gige::client::start_stream)
        .def("stop_stream", &camera::gige::client::stop_stream);
}
