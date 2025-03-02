#include <boost/asio.hpp>
#include <cstdint>
#include "ack.hpp"

namespace camera::gige::gvcp::cmd {

using byteint = std::array<std::byte, 4>;

byteint int2bytes(uint32_t v);

class command {
public:
    boost::asio::const_buffer get_buffer() const;
    ack get_ack(boost::asio::ip::udp::socket& socket) const;
protected:
    void writeint(uint32_t val);
    void writeint(byteint val);
    std::vector<std::byte> content_;
};

class discovery : public command {
public:
    discovery(uint16_t req_id);
};

class readmem : public command {
public:
    readmem(uint16_t req_id, const byteint& address, uint16_t count);
    readmem(uint16_t req_id, uint32_t address, uint16_t count);
};

class readreg : public command {
public:
    readreg(uint16_t req_id, const std::vector<byteint>& addresses);
    readreg(uint16_t req_id, const std::vector<uint32_t>& addresses);
private:
    readreg(uint16_t req_id, uint16_t length);
};

class writemem : public command {
public:
    writemem(uint16_t req_id, const byteint& address, const std::vector<std::byte>& data);
    writemem(uint16_t req_id, uint32_t address, const std::vector<std::byte>& data);
};

class writereg : public command {
public:
    writereg(uint16_t req_id, const std::vector<std::pair<byteint, byteint>>& addresses);
    writereg(uint16_t req_id, const std::vector<std::pair<uint32_t, uint32_t>>& addresses);
private:
    writereg(uint16_t req_id, uint16_t length);
};

}
