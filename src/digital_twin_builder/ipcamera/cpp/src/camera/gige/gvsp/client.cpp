#include "client.hpp"
#include "utils.hpp"
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
    using namespace utils;
    if (bytes > 0) {
        auto it = buffer_.begin();
        auto status = read_uint16(it);
        uint64_t block_id = read_uint16(it);
        uint16_t flag;
        auto packet_format = read_uint8(it);
        bool ei_flag = packet_format & (1 << 7);
        packet_format &= ~(1 << 7);
        uint32_t packet_id = read_uint24(it);
        if (ei_flag) {
            flag = block_id;
            block_id = read_uint64(it);
            packet_id = read_uint32(it);
        }
        switch (packet_format) {
            case 1: {
                auto payload_specific = read_uint16(it);
                auto payload_type = read_uint16(it);
                switch (payload_type) {
                    case 1: {
                        std::cout << "Image leader" << std::endl;
                        payloads_.push_back(std::unique_ptr<payload::image>(new payload::image(it)));
                        break;
                    } default:
                        std::cerr << "Not implemented payload type" << std::endl;
                        break;
                }
                break;
            } case 2: {
                it += 2;
                auto payload_type = read_uint16(it);
                switch (payload_type) {
                    case 1: {
                        std::cout << "Image trailer" << std::endl;
                        auto size_y = read_uint32(it);
                        dynamic_cast<payload::image*>(payloads_.back().get())->write_file("tmp/" + std::to_string(meta_.payload_count));
                        break;
                    } default:
                        std::cerr << "Not implemented payload type" << std::endl;
                        break;
                }
                ++meta_.payload_count;
                break;
            } case 3:
                payloads_.back()->read(it, bytes - 8);
                break;
            case 5:
                // TODO:H264 payload
                break;
            case 6:
                // TODO:MultiZone payload
                break;
            case 7:
                // TODO:MultiPart payload
                break;
            case 8:
                // TODO:GenDC payload
                break;
            default:
                std::cerr << "Invalid packet format" << std::endl;
                break;
        }
    } else {
        std::cout << "Error: " << bytes << std::endl;
    }
    if (meta_.payload_count < 10) {
        start_recieve();
    }
}
}
