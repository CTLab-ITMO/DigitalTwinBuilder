#pragma once
#include "gvcp/client.hpp"
#include "gvcp/registers.hpp"
#include "gvsp/client.hpp"
#include <cstdint>

namespace camera::gige {
class client {
public:
    client(gvcp::client&& gvcp, gvsp::client&& gvsp); // TODO:Maybe remove this constructor because it does same as second one
    client(const std::string& tx_address, const std::string& rx_address, uint16_t rx_port);
    void start_stream();
    void stop_stream();
    std::vector<std::string> get_all_registers();
    void write_register(const std::string& register_name, uint32_t value);
    void write_register(gvcp::registers register_name, uint32_t value);
    uint32_t read_register(const std::string& register_name);
    uint32_t read_register(gvcp::registers register_name);
    gvsp::client gvsp_;
    gvcp::client gvcp_;
private:
};
}
