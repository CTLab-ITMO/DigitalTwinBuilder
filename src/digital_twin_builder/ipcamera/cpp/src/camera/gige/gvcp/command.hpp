/**
* @file command.hpp
* @brief GVCP (GigE Vision Control Protocol) command classes implementation
* @version 0.1
* @date 2025-04-12
* 
* This file defines the base command class and specific command implementations 
* for the GigE Vision Control Protocol (GVCP) used in camera communication.
*/

#pragma once

#include <boost/asio.hpp>
#include <boost/endian/arithmetic.hpp>
#include <cstdint>
#include <type_traits>
#include <array>
#include <vector>

/**
* @brief Namespace for GigE Vision Control Protocol (GVCP) command classes
*/
namespace camera::gige::gvcp {

namespace cmd {
using namespace boost::endian;
#pragma pack(push, 1)
    enum class command_values : uint16_t { // in big endian
        discovery_cmd = 0x0200,      ///< Device discovery command
        forceip_cmd = 0x0400,        ///< Force IP configuration command
        packetresend_cmd = 0x4000,   ///< Packet resend request command
        readreg_cmd = 0x8000,        ///< Register read command
        writereg_cmd = 0x8200,       ///< Register write command
        readmem_cmd = 0x8400,        ///< Memory read command
        writemem_cmd = 0x8600,       ///< Memory write command
        event_cmd = 0xc000,          ///< Event notification command
        eventdata_cmd = 0xc200,      ///< Event data transmission command
        action_cmd = 0x0001          ///< Action trigger command
    };

    struct header_content {
        uint8_t key_value{0x42};
        uint8_t flag{0x01};
        command_values command;
        big_uint16_t length;
        big_uint16_t req_id;
    };

    struct discovery {
        discovery(uint16_t req_id);
        header_content header;
    };

    struct readmem {
        readmem(uint16_t req_id, uint32_t address, uint16_t count);
        header_content header;
        big_uint32_t address;
        big_uint16_t reserved;
        big_uint16_t count;
    };

    struct readreg {
        readreg(uint16_t req_id, const std::vector<uint32_t>& addresses);
        header_content header;
        std::array<big_uint32_t, 135> addresses;
    };

    struct writemem {
        writemem(uint16_t req_id, uint32_t address, const std::vector<std::byte>& data);
        header_content header;
        big_uint32_t address;
        std::array<std::byte, 536> data;
    };

    struct writereg {
        writereg(uint16_t req_id, const std::vector<std::pair<uint32_t, uint32_t>>& addresses);
        header_content header;
        std::array<std::pair<big_uint32_t, big_uint32_t>, 67> addresses;
    };
#pragma pack(pop)
}

template <class content>
class command {
public:
    command(content cmd_content);

    boost::asio::const_buffer get_buffer() const;
private:
    template<class T>
    std::enable_if_t<std::is_integral_v<T>> writeint(T val); 
    content content_; ///< Internal buffer for command data
};

} // namespace camera::gige::gvcp::cmd
