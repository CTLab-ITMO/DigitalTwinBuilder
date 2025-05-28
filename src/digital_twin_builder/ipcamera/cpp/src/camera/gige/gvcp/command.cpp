#include "command.hpp"
#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <iostream>
#include <type_traits>

namespace camera::gige::gvcp {


template <class content>
boost::asio::const_buffer command<content>::get_buffer() const {
    return boost::asio::buffer(&content_, sizeof(content));
}

// template <class T>
// std::enable_if_t<std::is_integral_v<T>> command::writeint(T val) {
//     for (std::size_t i = sizeof(T); i > 0; --i) {
//         content_.push_back(std::byte((val >> (8 * (i - 1))) & 0xff));
//     }
// }

template <class content>
command<content>::command(content cmd_content) {
    content_ = cmd_content;
}

namespace cmd {
discovery::discovery(uint16_t req_id) : header{.flag=0x11, .command=command_values::discovery_cmd, .length=static_cast<uint16_t>(0), .req_id=req_id} {}

readmem::readmem(uint16_t req_id, uint32_t address, uint16_t count) : header{.command=command_values::readmem_cmd, .length=static_cast<uint16_t>(8), .req_id=req_id}, address(address), count(count) {}

readreg::readreg(uint16_t req_id, const std::vector<uint32_t>& reg_addresses) : header{.command=command_values::readreg_cmd, .length=static_cast<uint16_t>(reg_addresses.size() * 4), .req_id=req_id} {
    copy_n(reg_addresses.begin(), reg_addresses.size(), addresses.begin());
}

writemem::writemem(uint16_t req_id, uint32_t address, const std::vector<std::byte>& memory_data) : header{.command=command_values::writemem_cmd, .length=static_cast<uint16_t>(memory_data.size() + 4), .req_id=req_id}, address(address) {
    copy_n(memory_data.begin(), memory_data.size(), data.begin());
}

writereg::writereg(uint16_t req_id, const std::vector<std::pair<uint32_t, uint32_t>>& reg_addresses) : header{.command=command_values::writereg_cmd, .length=static_cast<uint16_t>(reg_addresses.size() * 8), .req_id=req_id} {
    copy_n(reg_addresses.begin(), reg_addresses.size(), addresses.begin());
}
}
}
