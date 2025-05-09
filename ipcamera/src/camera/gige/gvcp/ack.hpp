#pragma once

#include "status_codes.hpp"
#include <boost/asio.hpp>
#include <cstdint>
#include <variant>

namespace camera::gige::gvcp {
template <std::size_t S>
using bytearr = std::array<std::byte, S>;

enum class ack_values : uint16_t {
    discovery_ack = 0x0003,
    forceip_ack = 0x0005,
    readreg_ack = 0x0081,
    writereg_ack = 0x0083,
    readmem_ack = 0x0085,
    writemem_ack = 0x0087,
    pending_ack = 0x0089,
    event_ack = 0x00c1,
    eventdata_ack = 0x00c3,
    action_ack = 0x0101,
};

class ack {
public:
    struct header {
        status_codes status;
        ack_values answer;
        uint16_t length;
        uint16_t ack_id;
    };
    struct discovery {
        bytearr<2> spec_version_major;
        bytearr<2> spec_version_minor;
        bytearr<4> device_mode;
        bytearr<2> device_mac_address_high;
        bytearr<4> device_mac_address_low;
        bytearr<4> ip_config_options;
        bytearr<4> ip_config_current;
        bytearr<4> current_ip;
        bytearr<4> current_subnet_mask;
        bytearr<4> default_gateway;
        bytearr<32> manufacturer_name;
        bytearr<32> model_name;
        bytearr<32> device_version;
        bytearr<48> manufacturer_specific_information;
        bytearr<16> serial_number;
        bytearr<16> user_defined_name;
    };
    struct readreg {
        std::vector<uint32_t> register_data; 
    };
    struct writereg {
        uint16_t index;
    };
    struct readmem {
        bytearr<4> address;
        std::vector<std::byte> data;
    };
    struct writemem {
        uint16_t index;
    };

    using content = std::variant<discovery, readreg, writereg, readmem, writemem>;

    ack(boost::asio::ip::udp::socket& socket);
    inline const header& get_header() const { return header_; }
    inline const content& get_content() const { return content_; }
private:
    header header_;
    content content_;
};
}
