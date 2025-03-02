#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <iostream>
#include <type_traits>
#include <vector>
#include "ack.hpp"

namespace camera::gige::gvcp {
using byte_iterator = std::byte*;
namespace utils {
    template <class Integer>
    std::enable_if_t<std::is_integral_v<Integer>, Integer> read_integer(byte_iterator& it) {
        Integer res = 0;
        for (std::size_t i = 0; i < sizeof(Integer); ++i) {
            res <<= 8;
            res += std::to_integer<uint8_t>(*(it++));
        }
        return res;
    }
    constexpr uint16_t(*read_uint16)(byte_iterator& it) = &read_integer<uint16_t>;
    std::vector<std::byte> read_n_bytes(std::vector<std::byte>::iterator& it, std::size_t n) {
        std::vector<std::byte> res;
        std::copy_n(it, n, res.begin());
        return res;
    }
}

ack::ack(boost::asio::ip::udp::socket& socket) {
    constexpr std::size_t max_packet_size = 576;
    std::array<std::byte, max_packet_size> buf;
    std::size_t len = socket.receive(boost::asio::buffer(buf));
    byte_iterator it = buf.begin();
    status_ = static_cast<status>(utils::read_uint16(it));
    answer_ = utils::read_uint16(it);
    length_ = utils::read_uint16(it);
    ack_id_ = utils::read_uint16(it);
    std::cout.write(reinterpret_cast<char*>(buf.data()), len);
    switch (answer_) {
        case(1):
            break;
        default:
            break;
    }
}
}
