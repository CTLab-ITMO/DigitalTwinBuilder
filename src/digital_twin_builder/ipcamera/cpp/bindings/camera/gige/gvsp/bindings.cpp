#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include "camera/gige/gvsp/client.hpp"

namespace py = pybind11;

PYBIND11_MODULE(_gvsp, m) {
    py::class_<camera::gige::gvsp::client>(m, "gvsp");
}
