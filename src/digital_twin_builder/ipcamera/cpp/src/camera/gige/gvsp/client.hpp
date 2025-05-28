#pragma once

#include "payload.hpp"
#include <cstddef>
#include <cstdint>
#include <string>
#include <thread>
#include <boost/asio.hpp>

namespace camera::gige::gvsp {
using boost::asio::ip::udp;
const std::size_t BUFFER_SIZE = 0xffff;

class client {
public:
    client(const std::string& rx_address, uint16_t rx_port);
    void set_endpoint(udp::endpoint&& tx_endpoint);
    void set_tx_address_and_port(const std::string& tx_address, uint16_t tx_port);
    const std::string& get_rx_address() const;
    uint16_t get_rx_port() const;
    void start_recieve();
    void stop_recieve();
private:
    void recieve();
    void handle_recieve(const boost::system::error_code& error, std::size_t bytes);

    std::jthread stream_thread_;

    struct meta {
        std::size_t payload_count = 0;
    } meta_;
    std::vector<std::unique_ptr<payload::payload_type>> payloads_;
    std::array<std::byte, BUFFER_SIZE> buffer_;
    udp::endpoint tx_endpoint_;
    std::string rx_address_;
    uint16_t rx_port_;
    bool running_ = false;

    boost::asio::io_context io_context_;
    udp::socket socket_;
};
}
