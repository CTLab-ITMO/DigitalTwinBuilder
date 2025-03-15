#include "client.hpp"
#include <cstdint>

namespace camera::gige {
gvsp::client start_stream(gvcp::client& gvcp, const std::string& rx_address, uint16_t rx_port) {
    uint16_t port = gvcp.start_streaming(rx_address, rx_port);
    return gvsp::client(gvcp.address(), port, rx_port);
}
}
