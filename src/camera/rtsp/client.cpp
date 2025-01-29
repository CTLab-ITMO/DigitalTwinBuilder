#include <sstream>
#include <iostream>

#include "client.hpp"

namespace camera::rtsp::client {

const std::string sep("\r\n");
using boost::asio::ip::tcp;

client::client(const std::string& address, uint16_t port) : address_(address), port_(port) {
    tcp::resolver resolver(io_context_);
    tcp::resolver::query query(address_, std::to_string(port_));
    boost::asio::connect(socket_, resolver.resolve(query));
}

response client::setup(const std::string& url, const std::map<std::string, std::string>& headers) {
    url_ = url;
    write("SETUP", headers);
    return read();
}

response client::teardown() {
    write("TEARDOWN", {});
    return read();
}

void client::write(const std::string& method, const std::map<std::string, std::string>& headers) {
    boost::asio::streambuf buf;
    std::ostream request(&buf);

    request << method << " " << url_ << " RTSP/2.0" << sep;
    for (auto const& [key, val]: headers) {
        request << key << ": " << val << sep;
    }
    if (!session_.empty()) {
        request << "Session: " << session_ << sep;
    }
    request << "CSeq: " << cseq_++ << sep;
    request << sep;
    boost::asio::write(socket_, buf);
}

response client::read() {
    response res;
    boost::asio::streambuf buf;
    boost::asio::read_until(socket_, buf, sep);
    
    std::string rtsp_version, status_message;
    uint status_code;

    std::istream response(&buf);
    response >> rtsp_version;
    response >> status_code;
    std::getline(response, status_message);

    // TODO: validation of version
    // TODO: branching on status code and version ?
    boost::asio::read_until(socket_, buf, sep + sep);

    std::string header, name, value;
    int content_length = 0;
    while(std::getline(response, header) && header != "\r") {
        std::cout << header << '\n';
        std::stringstream ss(header);
        ss >> name >> value;
        name.pop_back();
        value.pop_back();
        res.headers[name] = value;
    }

    return res;
}

}
