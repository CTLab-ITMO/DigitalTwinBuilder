#pragma once
#include "gvcp/client.hpp"
#include "gvsp/client.hpp"

namespace camera::gige {
gvsp::client start_stream(gvcp::client& gvcp, const std::string& address, uint16_t port);
}
