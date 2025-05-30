#include "client.hpp"
#include "command.hpp"
#include <boost/asio/detail/socket_ops.hpp>
#include <cstdint>
#include <iostream>
#include <filesystem>

namespace camera::gige {
client::client(const std::string& tx_address, const std::string& rx_address, uint16_t rx_port) : gvcp_(tx_address), gvsp_(rx_address, rx_port) {
    std::filesystem::create_directory("tmp/");
    auto filename = gvcp_.get_xml_genicam("tmp/");
    gvcp_.parse_xml_genicam(filename);
}
void client::start_stream() {
    uint16_t tx_port = gvcp_.start_streaming(gvsp_.get_rx_address(), gvsp_.get_rx_port());
    std::cout << "tx_port: " << tx_port << std::endl;
    gvsp_.set_endpoint(boost::asio::ip::udp::endpoint(boost::asio::ip::make_address_v4(gvcp_.get_address()), tx_port));
    gvsp_.start_recieve();
}

void client::stop_stream() {
    gvsp_.stop_recieve();
    gvcp_.stop_streaming();
}
}
