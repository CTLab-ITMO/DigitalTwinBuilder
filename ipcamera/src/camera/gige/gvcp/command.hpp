#pragma once

#include "ack.hpp"
#include <boost/asio.hpp>
#include <cstdint>
#include <type_traits>

namespace camera::gige::gvcp::cmd {

enum class command_values : uint16_t {
    discovery_cmd = 0x0002,
    forceip_cmd = 0x0004,
    packetresend_cmd = 0x0040,
    readreg_cmd = 0x0080,
    writereg_cmd = 0x0082,
    readmem_cmd = 0x0084,
    writemem_cmd = 0x0086,
    event_cmd = 0x00c0,
    eventdata_cmd = 0x00c2,
    action_cmd = 0x0100
};

class command {
public:
    boost::asio::const_buffer get_buffer() const;
    ack get_ack(boost::asio::ip::udp::socket& socket) const;
protected:
    template <class T>
    std::enable_if_t<std::is_integral_v<T>> writeint(T val); // TODO: SFINAE restrict non integral
    std::vector<std::byte> content_;
};

class discovery : public command {
public:
    discovery(uint16_t req_id);
};

class readmem : public command {
public:
    readmem(uint16_t req_id, uint32_t address, uint16_t count);
};

class readreg : public command {
public:
    readreg(uint16_t req_id, const std::vector<uint32_t>& addresses);
};

class writemem : public command {
public:
    writemem(uint16_t req_id, uint32_t address, const std::vector<std::byte>& data);
};

class writereg : public command {
public:
    writereg(uint16_t req_id, const std::vector<std::pair<uint32_t, uint32_t>>& addresses);
};

}
