#pragma once

#include "command.hpp"
#include "registers.hpp"
#include <cstdint>
#include <string>
#include <thread>


namespace camera::gige::gvcp {
using boost::asio::ip::udp;

const std::string port{"3956"};

class client {
public:
    client(const std::string& address);
    bool get_control();
    bool drop_control();
    uint16_t start_streaming(const std::string& rx_address, uint16_t rx_port);
    void stop_streaming();
    ack execute(const cmd::command& cmd);
    const std::string& get_address() const;
    void start_heartbeat();
private:
    std::string address_;
    uint16_t req_id_ = 1;
    bool keepalive_ = false;
    std::thread heartbeat_thread_;

    boost::asio::io_context io_context_;
    udp::socket socket_ { io_context_ };
};
}
