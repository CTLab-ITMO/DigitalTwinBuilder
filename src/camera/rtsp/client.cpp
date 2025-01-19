#include "client.hpp"

namespace camera::rtsp::client {

using boost::asio::ip::tcp;

client::client(const std::string& address, uint16_t port) : address_(address), port_(port) {
    
}

response client::setup(const std::string& url, const std::map<std::string, std::string>& headers) {
    return response();
}

response client::teardown() {
    return response();
}

}
