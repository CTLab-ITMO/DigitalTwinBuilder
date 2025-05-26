#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <iostream>
#include <type_traits>
#include <vector>
#include <boost/asio.hpp>
#include "ack.hpp"

namespace camera::gige::gvcp {
template<typename content>
acknowledge<content>::acknowledge(boost::asio::ip::udp::socket& socket) {
    std::size_t len = socket.receive(boost::asio::buffer(&content_, sizeof(content)));
}
}
