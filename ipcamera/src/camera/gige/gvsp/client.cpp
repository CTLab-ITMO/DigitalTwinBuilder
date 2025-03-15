#include "client.hpp"
#include <boost/bind/bind.hpp>
#include <cstdint>
#include <iostream>

namespace camera::gige::gvsp {
client::client(const std::string& tx_address, 
               uint16_t tx_port,
               uint16_t rx_port
               ) :  
    rx_port_(rx_port),
    socket_(io_context_, udp::endpoint(udp::v4(), rx_port_)),
    tx_endpoint_(boost::asio::ip::make_address(tx_address), tx_port) {
    start_recieve();
}
void client::start_recieve() {
    socket_.async_receive_from(boost::asio::buffer(buffer_), tx_endpoint_, boost::bind(&client::handle_recieve, this, boost::asio::placeholders::error, boost::asio::placeholders::bytes_transferred));
}

void client::handle_recieve(const boost::system::error_code& error, std::size_t bytes) {
    if (!error && bytes > 0) {
        std::cout << "Recieved:" << bytes << std::endl;
    }

    start_recieve();
}
}
