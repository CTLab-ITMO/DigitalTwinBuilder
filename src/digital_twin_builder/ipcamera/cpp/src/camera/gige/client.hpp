#pragma once
#include "gvcp/client.hpp"
#include "gvsp/client.hpp"
#include <cstdint>

namespace camera::gige {
class client {
public:
    client(gvcp::client&& gvcp, gvsp::client&& gvsp); // TODO:Maybe remove this constructor because it does same as second one
    client(const std::string& tx_address, const std::string& rx_address, uint16_t rx_port);
    void start_stream();
    void stop_stream();
    gvsp::client gvsp_;
    gvcp::client gvcp_;
private:
};
}
