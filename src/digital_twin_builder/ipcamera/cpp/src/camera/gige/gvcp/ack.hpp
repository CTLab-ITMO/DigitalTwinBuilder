#pragma once

#include "status_codes.hpp"
#include <boost/asio.hpp>
#include <boost/endian/arithmetic.hpp>
#include <cstdint>
#include <variant>

namespace camera::gige::gvcp {
namespace ack {
    using namespace boost::endian;
    template <std::size_t S>
    using bytearr = std::array<std::byte, S>;
#pragma pack(push, 1)
    enum class ack_values : uint16_t { // in big endian
        discovery_ack = 0x0300,
        forceip_ack = 0x0500,
        readreg_ack = 0x8100,
        writereg_ack = 0x8300,
        readmem_ack = 0x8500,
        writemem_ack = 0x8700,
        pending_ack = 0x8900,
        event_ack = 0xc100,
        eventdata_ack = 0xc300,
        action_ack = 0x0101,
    };

    struct header_content {
        status_codes status;
        ack_values answer;
        big_uint16_t length;
        big_uint16_t ack_id;
    };
    struct discovery {
        header_content header;
        big_uint16_t spec_version_major;
        big_uint16_t spec_version_minor;
        big_uint32_t device_mode;
        big_uint16_t device_mac_address_high;
        big_uint32_t device_mac_address_low;
        big_uint32_t ip_config_options;
        big_uint32_t ip_config_current;
        bytearr<12> reserved1;
        big_uint32_t current_ip;
        bytearr<12> reserved2;
        big_uint32_t current_subnet_mask;
        bytearr<12> reserved3;
        big_uint32_t default_gateway;
        bytearr<32> manufacturer_name;
        bytearr<32> model_name;
        bytearr<32> device_version;
        bytearr<48> manufacturer_specific_information;
        bytearr<16> serial_number;
        bytearr<16> user_defined_name;
    };
    struct readreg {
        header_content header;
        std::array<big_uint32_t, 135> register_data; 
    };
    struct writereg {
        header_content header;
        big_uint16_t reserved;
        big_uint16_t index;
    };
    struct readmem {
        header_content header;
        big_uint32_t address;
        bytearr<536> data;
    };
    struct writemem {
        header_content header;
        big_uint16_t reserved;
        big_uint16_t index;
    };
#pragma pack(pop)
}

template <typename content>
class acknowledge {
public:
    acknowledge(boost::asio::ip::udp::socket& socket);
    inline const ack::header_content& get_header() const { return get_content().header; }
    inline const content& get_content() const { return content_; }
private:
    content content_;
};
}
