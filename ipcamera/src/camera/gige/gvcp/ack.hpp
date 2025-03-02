#include <boost/asio.hpp>
#include "status.hpp"

namespace camera::gige::gvcp {
class ack {
public:
    ack(boost::asio::ip::udp::socket& socket);
private:
    status status_; // TODO: status enum
    uint16_t answer_;
    uint16_t length_;
    uint16_t ack_id_;
    std::unordered_map<std::string, std::vector<std::byte>> content_;
};
}
