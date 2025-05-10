#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include "camera/gige/client.hpp"

namespace py = pybind11;

PYBIND11_MODULE(_gige, m) {
    py::class_<camera::gige::client>(m, "gige");
}
