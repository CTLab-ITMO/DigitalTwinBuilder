#include "command.hpp"
#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <iostream>
#include <type_traits>

namespace camera::gige::gvcp::cmd {

const std::string port("3956");
const std::byte header{0x42};

boost::asio::const_buffer command::get_buffer() const {
    for (auto c : content_) {
        std::cout << std::to_string(std::to_integer<uint16_t>(c)) << " ";
    }
    std::cout << '\n';
    return boost::asio::buffer(content_);
}

ack command::get_ack(boost::asio::ip::udp::socket& socket) const {
    return ack(socket);
}

template <class T>
std::enable_if_t<std::is_integral_v<T>> command::writeint(T val) {
    for (std::size_t i = sizeof(T); i > 0; --i) {
        content_.push_back(std::byte((val >> (8 * (i - 1))) & 0xff));
    }
}

discovery::discovery(uint16_t req_id) {
    content_ = {
        header, 
        std::byte{0x11},
    };
    writeint(static_cast<uint16_t>(command_values::discovery_cmd));
    writeint(uint16_t(0));
    writeint(req_id);
}

readmem::readmem(uint16_t req_id, uint32_t address, uint16_t count) {
    content_ = {
        header,
        std::byte{0x01},
    };
    writeint(static_cast<uint16_t>(command_values::readmem_cmd));
    writeint(uint16_t(0x08));
    writeint(req_id);
    writeint(address);
    writeint(uint32_t(count));
}

readreg::readreg(uint16_t req_id, const std::vector<uint32_t>& addresses) {
    uint16_t length = addresses.size() * 4;
    content_ = {
        header,
        std::byte{0x01},
    };
    writeint(static_cast<uint16_t>(command_values::readreg_cmd));
    writeint(length);
    writeint(req_id);
    for (auto& address : addresses) {
        writeint(address);// TODO: check multiple of four (cleared last two bits)
    }
}

writemem::writemem(uint16_t req_id, uint32_t address, const std::vector<std::byte>& data) {
    content_ = {
        header,
        std::byte{0x01},
    };
    writeint(static_cast<uint16_t>(command_values::writemem_cmd));
    writeint(uint16_t(0x08));
    writeint(req_id);
    writeint(address);// TODO: check clear 30 and 31 bits
    for (auto byte : data) {
        content_.push_back(byte);
    }
}

writereg::writereg(uint16_t req_id, const std::vector<std::pair<uint32_t, uint32_t>>& addresses) {
    uint16_t length = addresses.size() * 8;
    content_ = {
        header,
        std::byte{0x01},
    };
    writeint(static_cast<uint16_t>(command_values::writereg_cmd));
    writeint(length);
    writeint(req_id);
    for (auto& address : addresses) {
        writeint(address.first);// TODO: check multiple of four (cleared last two bits)
        writeint(address.second);
    }
}
}
