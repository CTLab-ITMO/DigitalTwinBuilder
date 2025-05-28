#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include "camera/gige/gvsp/client.hpp"

namespace py = pybind11;

PYBIND11_MODULE(_gvsp, m) {
    py::class_<camera::gige::gvsp::client>(m, "gvsp")
        .def(py::init<const std::string&, uint16_t>(), py::arg("rx_address"), py::arg("rx_port"))
        .def("set_endpoint", &camera::gige::gvsp::client::set_tx_address_and_port)
        .def("get_rx_address", &camera::gige::gvsp::client::get_rx_address)
        .def("get_rx_port", &camera::gige::gvsp::client::get_rx_port)
        .def("start_receive", &camera::gige::gvsp::client::start_recieve)
        .def("stop_receive", &camera::gige::gvsp::client::stop_recieve);
}
