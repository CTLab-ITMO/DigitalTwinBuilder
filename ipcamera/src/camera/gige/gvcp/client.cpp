#include "client.hpp"
#include "registers.hpp"
#include <boost/asio/io_context.hpp>
#include <cstdint>
#include <exception>
#include <iostream>
#include <thread>

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

uint16_t client::start_streaming(const std::string& rx_address, uint16_t rx_port, uint16_t stream_channel_no) {
    if (!get_control()) {
        return 0;
    }
    uint16_t stream_channel_offset = 0x40 * stream_channel_no;
    std::cout << "reading stream port" << '\n';
    ack response_stream_channel_source_port = execute(cmd::readreg(req_id_++, std::vector<uint32_t>{registers::stream_channel_source_port_0 + stream_channel_offset}));
    if (response_stream_channel_source_port.get_header().status != status_codes::GEV_STATUS_SUCCESS) {
        return 0;
    }
    std::cout << "writing stream address " <<  boost::asio::ip::make_address_v4(rx_address).to_uint()<< '\n';
    ack response_address_write = execute(cmd::writereg(req_id_++, {{registers::stream_channel_destination_address_0 + stream_channel_offset, boost::asio::ip::make_address_v4(rx_address).to_uint()}}));
    std::cout << "writing stream port" << '\n';
    ack response_port_write = execute(cmd::writereg(req_id_++, {{registers::stream_channel_port_0 + stream_channel_offset, static_cast<uint32_t>(rx_port)} }));
    if (response_port_write.get_header().status != status_codes::GEV_STATUS_SUCCESS) {
        return 0;
    }
    ack response_acq_write = execute(cmd::writereg(req_id_++, {{0x00030804, 1}}));
    keepalive_ = true;
    heartbeat_thread_ = std::thread(&client::start_heartbeat, this);
    return std::get<ack::readreg>(response_stream_channel_source_port.get_content()).register_data[0];
}

void client::stop_streaming(uint16_t stream_channel_no) {
    keepalive_ = false;
    uint16_t stream_channel_offset = 0x40 * stream_channel_no;
    ack response_port_address_write = execute(cmd::writereg(req_id_++, { {registers::stream_channel_port_0 + stream_channel_offset, 0}, {registers::stream_channel_destination_address_0 + stream_channel_offset, 0} }));
    drop_control();
    heartbeat_thread_.join();
}

void client::start_heartbeat() {
    while (keepalive_) {
        ack response = execute(cmd::readreg(req_id_++, std::vector<uint32_t>{registers::control_channel_privilege}));
        std::this_thread::sleep_for(std::chrono::milliseconds(2000));

    }

}

ack client::execute(const cmd::command& cmd) {
    socket_.send(cmd.get_buffer());
    return cmd.get_ack(socket_);
}

const std::string& client::get_address() const {
    return address_;
}

std::vector<std::string> client::get_all_gige_devices() {
    boost::asio::io_context io_context;
    udp::resolver resolver(io_context);
    auto res=resolver.resolve(udp::v4(), boost::asio::ip::host_name(),"");
    auto it = res.begin();

    while(it!=res.end())
    {
        boost::asio::ip::address addr=(it++)->endpoint().address();

        std::cout<<addr.to_string()<<std::endl;
    }
}
}
