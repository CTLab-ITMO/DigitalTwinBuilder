#include "client.hpp"
#include <boost/bind/bind.hpp>
#include <cstdint>
#include <iostream>

namespace camera::gige::gvsp {
client::client(const std::string& rx_address, uint16_t rx_port) :  
    rx_address_(rx_address),
    rx_port_(rx_port),
    socket_(io_context_, udp::endpoint(udp::v4(), rx_port_)) {
}

void client::set_endpoint(udp::endpoint&& tx_endpoint) {
    tx_endpoint_ = std::move(tx_endpoint);
}
const std::string& client::get_rx_address() const {
    return rx_address_;
}

uint16_t client::get_rx_port() const {
    return rx_port_;
}

void client::start_recieve() {
    socket_.async_receive_from(boost::asio::buffer(buffer_), tx_endpoint_, boost::bind(&client::handle_recieve, this, boost::asio::placeholders::error, boost::asio::placeholders::bytes_transferred));
}

void client::handle_recieve(const boost::system::error_code& error, std::size_t bytes) {
    if (bytes > 0) {
        std::cout << "Recieved: " << bytes << std::endl;
    } else {
        std::cout << "Error: " << bytes << std::endl;
    }

    start_recieve();
}
}
