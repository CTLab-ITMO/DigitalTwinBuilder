#pragma once

#include "command.hpp"
#include "registers.hpp"
#include <cstdint>
#include <string>


namespace camera::gige::gvcp {
using boost::asio::ip::udp;

const std::string port{"3956"};

class client {
public:
    client(const std::string& address);
    bool get_control();
    bool drop_control();
    uint16_t start_streaming(const std::string& rx_address, uint16_t rx_port);
    ack execute(const cmd::command& cmd);
    const std::string& get_address() const;
private:
    std::string address_;
    uint16_t req_id_ = 1;

    boost::asio::io_context io_context_;
    udp::socket socket_ { io_context_ };
};
}
