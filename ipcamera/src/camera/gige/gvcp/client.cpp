#include "client.hpp"
#include "registers.hpp"
#include <boost/asio/io_context.hpp>
#include <zip.h>
#include <pugixml.hpp>
#include <cstdint>
#include <exception>
#include <iostream>
#include <thread>
#include <fstream>

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
    ack response_acq_write = execute(cmd::writereg(req_id_++, {{0x00030804, 1}})); //TODO: replace magic number with genicam register
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

std::string client::get_xml_genicam(const std::string& path) {
    auto res = execute(cmd::readreg(req_id_++, std::vector<uint32_t>{0x0934}));
    if (res.get_header().status == status_codes::GEV_STATUS_SUCCESS && !(std::get<ack::readreg>(res.get_content()).register_data[0] & (1 << 28))) {
        std::cout << "manifest table is supported" << '\n';
        return 0;
    }
    auto response = execute(cmd::readmem(req_id_++, registers::second_url, 512));
    if (response.get_header().status != status_codes::GEV_STATUS_SUCCESS) {
        std::cout << "readmem failed with status: " << response.get_header().status << '\n';
    }
    std::stringstream sstream(std::string(reinterpret_cast<const char*>(std::get<ack::readmem>(response.get_content()).data.data())));
    std::string location, name, extension, temp;
    std::cout << sstream.view() << '\n';
    getline(sstream, location, ':');
    getline(sstream, name, '.');
    getline(sstream, extension, ';');
    getline(sstream, temp, ';');
    std::cout << temp << '\n';
    uint32_t address = std::stoi(temp, nullptr, 16);
    getline(sstream, temp);
    std::cout << temp << '\n';
    uint32_t length = std::stoi(temp, nullptr, 16);
    std::cout << address << " " << length << std::endl;

    std::string filename = path + name + std::string(".") + extension;
    std::string unzipped_filename = path + name + ".xml";
    std::ofstream file_out(filename);
    uint32_t batch_length = 512;
    uint32_t count = length / batch_length + 1;
    std::cout << count << '\n';
    for (int i = 0; i < count; ++i) {
        std::cout << i << '\n';
        auto xml_response = execute(cmd::readmem(req_id_++, address + i * batch_length, batch_length));
        if (xml_response.get_header().status == status_codes::GEV_STATUS_SUCCESS) {
            file_out.write(reinterpret_cast<const char*>(std::get<ack::readmem>(xml_response.get_content()).data.data()), batch_length);
        }
    }
    file_out.close();

    if (extension == "zip") {
        struct zip *zip_file; // дескриптор zip файла
        struct zip_file *zipped_file;
        int err; // переменая для возврата кодов ошибок

        zip_file = zip_open(filename.c_str(), 0, &err);
        if (!zip_file) {
            throw std::runtime_error("can't open zip file " + filename); // TODO: custom error
        };

        zipped_file = zip_fopen_index(zip_file, 0, 0);
        if (!zipped_file) {
            throw std::runtime_error("can't unzip zip file " + unzipped_filename); // TODO: custom error
        }
        std::ofstream unzipped_file(unzipped_filename);
        constexpr std::size_t buffer_size = 4096;
        std::array<char, buffer_size> buffer;
        std::size_t acquired_size;
        while ((acquired_size = zip_fread(zipped_file, buffer.data(), buffer_size)) > 0) {
            unzipped_file.write(buffer.data(), acquired_size);
        }
        unzipped_file.close();
        zip_fclose(zipped_file);
        zip_close(zip_file);
        std::remove(filename.c_str());
    }
    return unzipped_filename;
}


void client::parse_xml_genicam(const std::string& filename) const {

}
}
