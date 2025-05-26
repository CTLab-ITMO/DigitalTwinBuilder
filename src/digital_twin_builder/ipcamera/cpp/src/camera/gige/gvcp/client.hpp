#pragma once

#include "command.hpp"
#include "ack.hpp"
#include <cstdint>
#include <string>
#include <thread>
#include <unordered_map>

namespace camera::gige::gvcp {
using boost::asio::ip::udp;

const std::string gvcp_port{"3956"};

class client {
public:
    client(const std::string& address);
    bool get_control();
    bool drop_control();
    uint16_t start_streaming(const std::string& rx_address, uint16_t rx_port, uint16_t stream_channel_no = 0);
    void stop_streaming(uint16_t stream_channel_no = 0);
    template <class ack_content, class cmd_content>
    ack_content execute(const cmd_content& cmd);
    const std::string& get_address() const;
    void start_heartbeat();
    static std::vector<std::string> get_all_gige_devices();
    std::string get_xml_genicam(const std::string& path);
    void parse_xml_genicam(const std::string& filename);
    uint16_t req_id_inc();
private:
    std::unordered_map<std::string, uint32_t> genicam_regs;
    uint16_t req_id_{0};
    std::string address_;
    bool keepalive_ = false;
    std::thread heartbeat_thread_;

    boost::asio::io_context io_context_;
    udp::socket socket_ { io_context_ };
};
}
