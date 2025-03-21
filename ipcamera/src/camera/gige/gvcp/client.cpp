#include "client.hpp"
#include <cstdint>
#include <exception>
#include <iostream>

namespace camera::gige::gvcp {

client::client(const std::string& address) : address_(address) {
    udp::resolver resolver(io_context_);
    boost::asio::connect(socket_, resolver.resolve(address, port));
}

bool client::get_control() {
    std::cout << "reading control port" << '\n';
    ack response_ccp_read = execute(cmd::readreg(req_id_++, std::vector<uint32_t>{registers::control_channel_privilege}));
    if (response_ccp_read.get_header().status == status_codes::GEV_STATUS_SUCCESS && std::get<ack::readreg>(response_ccp_read.get_content()).register_data[0] == 0) {
        std::cout << "writing control port" << '\n';
        ack response_ccp_write = execute(cmd::writereg(req_id_++, {{registers::control_channel_privilege, 0b10}}));
        return response_ccp_write.get_header().status == status_codes::GEV_STATUS_SUCCESS;
    }
    return false;
}

bool client::drop_control() {
    ack response_ccp_write = execute(cmd::writereg(req_id_++, {{registers::control_channel_privilege, 0}}));
    return response_ccp_write.get_header().status == status_codes::GEV_STATUS_SUCCESS;
}

uint16_t client::start_streaming(const std::string& rx_address, uint16_t rx_port) {
    if (!get_control()) {
        return 0;
    }
    std::cout << "reading stream port" << '\n';
    ack response_stream_channel_source_port = execute(cmd::readreg(req_id_++, std::vector<uint32_t>{registers::stream_channel_source_port_0}));
    if (response_stream_channel_source_port.get_header().status != status_codes::GEV_STATUS_SUCCESS) {
        return 0;
    }
    std::cout << "writing stream port and address" << '\n';
    ack response_port_address_write = execute(cmd::writereg(req_id_++, {{registers::stream_channel_destination_address_0, boost::asio::ip::make_address_v4(rx_address).to_uint()}, {registers::stream_channel_port_0, rx_port} }));
    if (response_port_address_write.get_header().status != status_codes::GEV_STATUS_SUCCESS) {
        return 0;
    }
    do {
        response_port_address_write = execute(cmd::readreg(req_id_++, std::vector<uint32_t>{registers::stream_channel_port_0}));
        std::cout << "still" << std::endl;
    } while (response_port_address_write.get_header().status == status_codes::GEV_STATUS_SUCCESS);
    return std::get<ack::readreg>(response_stream_channel_source_port.get_content()).register_data[0];
}

ack client::execute(const cmd::command& cmd) {
    socket_.send(cmd.get_buffer());
    return cmd.get_ack(socket_);
}

const std::string& client::get_address() const {
    return address_;
}
}
