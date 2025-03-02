#include "command.hpp"
#include <algorithm>
#include <cstdint>

namespace camera::gige::gvcp::cmd {

const std::string port("3956");
const std::byte header{0x42};
const std::byte zero{0x00};

byteint int2bytes(uint32_t v) {
    return std::array<std::byte, 4>{std::byte(v >> 24), std::byte((v >> 16) & 0xff), std::byte((v >> 8) & 0xff), std::byte(v & 0xff)};
}


boost::asio::const_buffer command::get_buffer() const {
    return boost::asio::buffer(content_);
}

void command::writeint(uint32_t val) {
    for (int i = 3; i >= 0; --i) {
        content_.push_back(std::byte((val >> (8 * i)) & 0xff));
    }
}

void command::writeint(byteint val) {
    for (std::byte byte : val) {
         content_.push_back(byte);
    }
}

discovery::discovery(uint16_t req_id) {
    content_ = {
        header, 
        std::byte{0x11},
        zero, std::byte{0x02},
        zero, zero,
        std::byte(req_id >> 8), std::byte(req_id & 0xff)
    };
}

readmem::readmem(uint16_t req_id, const byteint& address, uint16_t count) {
    content_ = {
        header,
        std::byte{0x01},
        zero, std::byte{0x84},
        zero, std::byte{0x08},
        std::byte(req_id >> 8), std::byte(req_id & 0xff),
        address[0], address[1], address[2], address[3],// TODO: check clear 30 and 31 bits
        zero, zero, 
        std::byte(count >> 8), std::byte(count & 0xff)// TODO: check multiple of four (cleared last two bits)
    };
}

readmem::readmem(uint16_t req_id, uint32_t address, uint16_t count) : readmem(req_id, int2bytes(address), count) {}

readreg::readreg(uint16_t req_id, uint16_t length) {
    content_ = {
        header,
        std::byte{0x01},
        zero, std::byte{0x80},
        std::byte(length >> 8), std::byte(length & 0xff),
        std::byte(req_id >> 8), std::byte(req_id & 0xff)
    };
}

readreg::readreg(uint16_t req_id, const std::vector<byteint>& addresses) : readreg(req_id, addresses.size()) {
    for (auto& address : addresses) {
        writeint(address);// TODO: check multiple of four (cleared last two bits)
    }
}

readreg::readreg(uint16_t req_id, const std::vector<uint32_t>& addresses) : readreg(req_id, addresses.size()) {
    for (auto& address : addresses) {
        writeint(address & 0b00);// TODO: maybe exception when address invalid
    }
}

writemem::writemem(uint16_t req_id, const byteint& address, const std::vector<std::byte>& data) {
    content_ = {
        header,
        std::byte{0x01},
        zero, std::byte{0x84},
        zero, std::byte{0x08},
        std::byte(req_id >> 8), std::byte(req_id & 0xff),
        address[0], address[1], address[2], address[3]// TODO: check clear 30 and 31 bits
    };
    for (auto byte : data) {
        content_.push_back(byte);
    }
}

writemem::writemem(uint16_t req_id, uint32_t address, const std::vector<std::byte>& data) : writemem(req_id, int2bytes(address), data) {}

writereg::writereg(uint16_t req_id, uint16_t length) {
    content_ = {
        header,
        std::byte{0x01},
        zero, std::byte{0x80},
        std::byte(length >> 8), std::byte(length & 0xff),
        std::byte(req_id >> 8), std::byte(req_id & 0xff)
    };
}

writereg::writereg(uint16_t req_id, const std::vector<std::pair<byteint, byteint>>& addresses) : writereg(req_id, addresses.size()) {
    for (auto& address : addresses) {
        writeint(address.first);// TODO: check multiple of four (cleared last two bits)
        writeint(address.second);
    }
}

writereg::writereg(uint16_t req_id, const std::vector<std::pair<uint32_t, uint32_t>>& addresses) : writereg(req_id, addresses.size()) {
    for (auto& address : addresses) {
        writeint(address.first & 0b00);// TODO: maybe exception when address invalid
        writeint(address.second);
    }
}
}
