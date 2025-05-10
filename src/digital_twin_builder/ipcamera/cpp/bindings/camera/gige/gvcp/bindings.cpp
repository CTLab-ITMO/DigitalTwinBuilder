#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include "camera/gige/gvcp/client.hpp"

namespace py = pybind11;

PYBIND11_MODULE(_gvcp, m) {
    py::class_<camera::gige::gvcp::client>(m, "gvcp");
}
