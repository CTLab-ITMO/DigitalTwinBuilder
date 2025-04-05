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
    uint16_t start_streaming(const std::string& rx_address, uint16_t rx_port, uint16_t stream_channel_no = 0);
    void stop_streaming(uint16_t stream_channel_no = 0);
    ack execute(const cmd::command& cmd);
    const std::string& get_address() const;
    void start_heartbeat();
    static std::vector<std::string> get_all_gige_devices();
    std::string get_xml_genicam(const std::string& path);
    uint16_t req_id_ = 1;
private:
    std::string address_;
    bool keepalive_ = false;
    std::thread heartbeat_thread_;

    boost::asio::io_context io_context_;
    udp::socket socket_ { io_context_ };
};
}
