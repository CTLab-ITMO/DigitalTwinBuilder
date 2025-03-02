#include "client.hpp"

namespace camera::gige::gvcp {

client::client(const std::string& address) {
    udp::resolver resolver(io_context_);
    boost::asio::connect(socket_, resolver.resolve(address, port));
}

bool client::get_control() {
    execute(cmd::readreg(req_id_++, std::vector<uint32_t>{registers::gev_ccp}));
    execute(cmd::writereg(req_id_++, {{registers::gev_ccp, 2}}));
    return true;
}

bool client::start_streaming() {
    return true;
}

void client::execute(const cmd::command& cmd) {
    socket_.send(cmd.get_buffer());
}
}
