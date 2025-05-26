#include "client.hpp"
#include "ack.hpp"
#include "command.hpp"
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
template <class ack_content, class cmd_content>
ack_content client::execute(const cmd_content& cmd) = delete;

template <>
ack::discovery client::execute(const cmd::discovery& cmd) {
    socket_.send(boost::asio::buffer(&cmd, sizeof(cmd::discovery)));
    ack::discovery content;
    socket_.receive(boost::asio::buffer(&content, sizeof(content)));
    return content;
}

template <>
ack::readreg client::execute(const cmd::readreg& cmd) {
    socket_.send(boost::asio::buffer(reinterpret_cast<const char*>(&cmd), sizeof(cmd)));
    for (int i = 0; i < 12; ++i) {
        std::cout << (((uint16_t)reinterpret_cast<const char*>(&cmd)[i]) & 0x00ff) << " ";
    }
    std::cout << std::endl;
    ack::readreg content;
    socket_.receive(boost::asio::buffer(reinterpret_cast<char*>(&content), sizeof(content)));
    return content;
}

template <>
ack::writereg client::execute(const cmd::writereg& cmd) {
    socket_.send(boost::asio::buffer(&cmd, sizeof(cmd)));
    for (int i = 0; i < sizeof(cmd); ++i) {
        std::cout << (((uint16_t)reinterpret_cast<const char*>(&cmd)[i]) & 0x00ff) << " ";
    }
    std::cout << std::endl;
    ack::writereg content;
    socket_.receive(boost::asio::buffer(&content, sizeof(content)));
    for (int i = 0; i < sizeof(content); ++i) {
        std::cout << (((uint16_t)reinterpret_cast<const char*>(&content)[i]) & 0x00ff) << " ";
    }
    std::cout << std::endl;
    std::cout << (uint16_t)content.header.answer << '\n';
    return content;
}

template <>
ack::readmem client::execute(const cmd::readmem& cmd) {
    socket_.send(boost::asio::buffer(&cmd, sizeof(cmd)));
    ack::readmem content;
    socket_.receive(boost::asio::buffer(&content, sizeof(content)));
    return content;
}

template <>
ack::writemem client::execute(const cmd::writemem& cmd) {
    socket_.send(boost::asio::buffer(&cmd, sizeof(cmd::writemem)));
    ack::writemem content;
    socket_.receive(boost::asio::buffer(&content, sizeof(content)));
    return content;
}

client::client(const std::string& address) : address_(address) {
    udp::resolver resolver(io_context_);
    boost::asio::connect(socket_, resolver.resolve(address, gvcp_port));
}

bool client::get_control() {
    std::cout << "reading control port" << '\n';
    auto response_ccp_read = execute<ack::readreg>(cmd::readreg(req_id_inc(), std::vector<uint32_t>{registers::control_channel_privilege}));
    if (response_ccp_read.header.status == status_codes::GEV_STATUS_SUCCESS && response_ccp_read.register_data[0] == 0) {
        std::cout << "writing control port" << '\n';
        auto response_ccp_write = execute<ack::writereg>(cmd::writereg(req_id_inc(), {{registers::control_channel_privilege, 0b10}}));
        return response_ccp_write.header.status == status_codes::GEV_STATUS_SUCCESS;
    }
    return false;
}

bool client::drop_control() {
    auto response_ccp_write = execute<ack::writereg>(cmd::writereg(req_id_inc(), {{registers::control_channel_privilege, 0}}));
    return response_ccp_write.header.status == status_codes::GEV_STATUS_SUCCESS;
}

uint16_t client::start_streaming(const std::string& rx_address, uint16_t rx_port, uint16_t stream_channel_no) {
    if (!get_control()) {
        return 0;
    }
    uint16_t stream_channel_offset = 0x40 * stream_channel_no;
    std::cout << "reading stream port" << '\n';
    auto response_stream_channel_source_port = execute<ack::readreg>(cmd::readreg(req_id_inc(), std::vector<uint32_t>{registers::stream_channel_source_port_0 + stream_channel_offset}));
    if (response_stream_channel_source_port.header.status != status_codes::GEV_STATUS_SUCCESS) {
        return 0;
    }
    std::cout << "writing stream info" << '\n';
    auto response_write = execute<ack::writereg>(cmd::writereg(req_id_inc(), {
        {registers::stream_channel_destination_address_0 + stream_channel_offset, boost::asio::ip::make_address_v4(rx_address).to_uint()},
        {genicam_regs["AcquisitionStart"], 1}, {registers::stream_channel_port_0 + stream_channel_offset, static_cast<uint32_t>(rx_port)} }));
    keepalive_ = true;
    heartbeat_thread_ = std::thread(&client::start_heartbeat, this);
    return response_stream_channel_source_port.register_data[0];
}

void client::stop_streaming(uint16_t stream_channel_no) {
    keepalive_ = false;
    uint16_t stream_channel_offset = 0x40 * stream_channel_no;
    auto response_write = execute<ack::writereg>(cmd::writereg(req_id_inc(), { 
        {registers::stream_channel_port_0 + stream_channel_offset, 0}, 
        {genicam_regs["AcquisitionStop"], 1}, 
        {registers::stream_channel_destination_address_0 + stream_channel_offset, 0} }));
    drop_control();
    heartbeat_thread_.join();
}

void client::start_heartbeat() {
    while (keepalive_) {
        auto response = execute<ack::readreg>(cmd::readreg(req_id_inc(), std::vector<uint32_t>{registers::control_channel_privilege}));
        std::this_thread::sleep_for(std::chrono::milliseconds(2000));

    }

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
    return {};
}

std::string client::get_xml_genicam(const std::string& path) {
    auto res = execute<ack::readreg>(cmd::readreg(req_id_inc(), std::vector<uint32_t>{0x0934}));
    std::cout << res.header.status << '\n';
    if (res.header.status == status_codes::GEV_STATUS_SUCCESS && !res.register_data[0] & (1 << 28)) {
        std::cout << "manifest table is supported" << '\n';
        throw std::runtime_error("Not implemented"); // TODO: manifest table
    }
    ack::readmem response = execute<ack::readmem>(cmd::readmem(req_id_inc(), registers::second_url, 512));
    std::stringstream sstream(std::string(reinterpret_cast<const char*>(response.data.data())));
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
        auto xml_response = execute<ack::readmem>(cmd::readmem(req_id_inc(), address + i * batch_length, batch_length));
        if (xml_response.header.status == status_codes::GEV_STATUS_SUCCESS) {
            file_out.write(reinterpret_cast<const char*>(xml_response.data.data()), batch_length);
        }
    }
    file_out.close();

    if (extension == "zip") {
        struct zip *zip_file;
        struct zip_file *zipped_file;
        int err;

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


void client::parse_xml_genicam(const std::string& filename) {
    pugi::xml_document doc;
    pugi::xml_parse_result result = doc.load_file(filename.c_str(), filename.length(), pugi::xml_encoding::encoding_utf8);
    if (!result)
        throw std::runtime_error("can't parse xml file " + filename);

    pugi::xpath_node_set root_categories = doc.select_nodes("/RegisterDescription/Category[@Name='Root']/pFeature");
    for (pugi::xpath_node category : root_categories) {
        std::string category_value = category.node().child_value(); 
        pugi::xpath_node_set category_features = doc.select_nodes(("/RegisterDescription/Category[@Name='" + category_value + "']/pFeature").c_str());
        for (pugi::xpath_node feature : category_features) {
            std::string feature_name = feature.node().child_value();
            std::string group = "/RegisterDescription/Group[@Comment='" + category_value + "']/*[@Name='";
            pugi::xml_node feature_node = doc.select_node((group + feature_name + "']").c_str()).node();
            std::cout << feature_name << " ";
            std::string feature_node_pvalue = feature_node.child("pValue").child_value();
            std::string feature_reg = doc.select_node((group + feature_node_pvalue + "']/pAddress").c_str()).node().child_value();
            std::string feature_reg_addr = doc.select_node(("/RegisterDescription/Group[@Comment='RegAddr']/Group[@Comment='Inq RegAddr']/Integer[@Name='" + feature_reg + "']/Value").c_str()).node().child_value();
            std::cout << feature_node_pvalue << " " << feature_reg << " " << feature_reg_addr << '\n';
            if (feature_reg_addr != "") {
                genicam_regs[feature_name] = std::stoi(feature_reg_addr, nullptr, 16);
            }
        }
    }
}

uint16_t client::req_id_inc() {
    if (++req_id_ == 0) [[unlikely]] {
        return ++req_id_;
    } else [[likely]] {
        return req_id_;
    }
}
}
