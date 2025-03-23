#pragma once
#include <cstddef>
#include <cstdint>
#include <string>
#include <boost/asio.hpp>

namespace camera::gige::gvsp {
using boost::asio::ip::udp;
const std::size_t BUFFER_SIZE = 0xffff;

class client {
public:
    client(const std::string& rx_address, uint16_t rx_port);
    void set_endpoint(const udp::endpoint& tx_endpoint);
    const std::string& get_rx_address() const;
    uint16_t get_rx_port() const;
    void start_recieve();
    void handle_recieve(const boost::system::error_code& error, std::size_t bytes);
private:
    std::array<std::byte, BUFFER_SIZE> buffer_;
    udp::endpoint tx_endpoint_;
    std::string rx_address_;
    uint16_t rx_port_;

    udp::socket socket_;
    boost::asio::io_context io_context_;
};
}
