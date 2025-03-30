#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <iostream>
#include <type_traits>
#include <vector>
#include <boost/asio.hpp>
#include "ack.hpp"
#include "status_codes.hpp"

namespace camera::gige::gvcp {
using byte_iterator = std::byte*;
namespace utils {
    template <class Integer>
    std::enable_if_t<std::is_integral_v<Integer>, Integer> read_integer(byte_iterator& it) {
        Integer res = 0;
        for (std::size_t i = 0; i < sizeof(Integer); ++i) {
            res <<= 8;
            res += std::to_integer<Integer>(*(it++));
        }
        return res;
    }
    constexpr uint16_t(*read_uint16)(byte_iterator& it) = &read_integer<uint16_t>;
    std::vector<std::byte> read_n_bytes(byte_iterator& it, std::size_t n) {
        std::vector<std::byte> res(n);
        std::copy_n(it, n, res.begin());
        it += n;
        return res;
    }
    template <std::size_t S>
    bytearr<S> read_bytearr(byte_iterator& it) {
        bytearr<S> res;
        std::copy_n(it, S, res.begin());
        it += S;
        return res;
    }
}

ack::ack(boost::asio::ip::udp::socket& socket) {
    using namespace utils;
    constexpr std::size_t max_packet_size = 576;
    std::array<std::byte, max_packet_size> buf;
    std::size_t len = socket.receive(boost::asio::buffer(buf));
    if (true) {
        for (int i = 0; i < len; ++i) {
           std::cout << std::to_string(std::to_integer<uint16_t>(buf[i])) << " ";
        }
        std::cout << std::endl;
    }
    byte_iterator it = buf.begin();
    header_.status = static_cast<status_codes>(utils::read_uint16(it));
    header_.answer = static_cast<ack_values>(utils::read_uint16(it));
    header_.length = read_uint16(it);
    header_.ack_id = read_uint16(it);
    if (get_header().status == status_codes::GEV_STATUS_SUCCESS) {
    switch (header_.answer) {
        case(ack_values::discovery_ack): {
            discovery discovery;
            discovery.spec_version_major = read_bytearr<2>(it);
            discovery.spec_version_minor = read_bytearr<2>(it);
            discovery.device_mode = read_bytearr<4>(it);
            it += 2;
            discovery.device_mac_address_high = read_bytearr<2>(it);
            discovery.device_mac_address_low = read_bytearr<4>(it);
            discovery.ip_config_options = read_bytearr<4>(it);
            discovery.ip_config_current = read_bytearr<4>(it);
            it += 12;
            discovery.current_ip = read_bytearr<4>(it);
            it += 12;
            discovery.current_subnet_mask = read_bytearr<4>(it);
            it += 12;
            discovery.default_gateway = read_bytearr<4>(it);
            discovery.manufacturer_name = read_bytearr<32>(it);
            discovery.model_name = read_bytearr<32>(it);
            discovery.device_version = read_bytearr<32>(it);
            discovery.manufacturer_specific_information = read_bytearr<48>(it);
            discovery.serial_number = read_bytearr<16>(it);
            discovery.user_defined_name = read_bytearr<16>(it);
            content_ = discovery;
            break;
        } case(ack_values::readreg_ack): {
            readreg readreg;
            for (std::size_t i = 0; i < header_.length; i += 4) {
                readreg.register_data.push_back(read_integer<uint32_t>(it));
            }
            content_ = readreg;
            break;
        } case(ack_values::writereg_ack):
            it += 2;
            content_ = writereg{ read_uint16(it) };
            break;
        case(ack_values::readmem_ack):
            std::cout << "length " << header_.length << '\n';
            content_ = readmem{ read_bytearr<4>(it), read_n_bytes(it, header_.length - 4) };
            break;
        case(ack_values::writemem_ack):
            it += 2;
            content_ = writereg{ read_uint16(it) };
            break;
        default:
            // TODO: not implemented
            break;
    }
    } else {
        std::cout << get_header().status - 0x8000 << '\n';
    }
}
}
