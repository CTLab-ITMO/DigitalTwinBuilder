#include "boost/asio.hpp"

#include "command.hpp"
#include "registers.hpp"


namespace camera::gige::gvcp {
using boost::asio::ip::udp;

const std::string port{"3956"};

class client {
public:
    client(const std::string& address);
    bool get_control();
    bool start_streaming();
    void execute(const cmd::command& cmd);
private:
    uint16_t req_id_ = 1;

    boost::asio::io_context io_context_;
    udp::socket socket_{ io_context_ };
};
}
