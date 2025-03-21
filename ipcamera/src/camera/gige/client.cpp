#include "client.hpp"
#include <cstdint>

namespace camera::gige {
client::client(const std::string& tx_address, const std::string& rx_address, uint16_t rx_port) : gvcp_(tx_address), gvsp_(rx_address, rx_port) {
}

void client::start_stream() {
    uint16_t tx_port = gvcp_.start_streaming(gvsp_.get_rx_address(), gvsp_.get_rx_port());
    gvsp_.set_endpoint(boost::asio::ip::udp::endpoint(boost::asio::ip::make_address_v4(gvcp_.get_address()), tx_port));
    gvsp_.start_recieve();
}
}
