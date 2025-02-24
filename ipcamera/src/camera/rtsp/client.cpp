#include <cstdint>
#include <sstream>
#include <iostream>
#include <string>

#include "client.hpp"

namespace camera::rtsp::client {

using boost::asio::ip::tcp;

client::client(const std::string& address, uint16_t port) : address_(address), port_(port) {
    tcp::resolver resolver(io_context_);
    boost::asio::connect(socket_, resolver.resolve(address_, std::to_string(port_)));
}

response client::setup(const std::string& url, const std::map<std::string, std::string>& headers) {
    url_ = url;
    write("SETUP", headers);
    response r = read();
    if (r.headers.contains("session")) {
        session_ = r.headers["session"];
    }
    return r;
}

response client::play(const std::pair<uint32_t, uint32_t>& range) {
    write("PLAY", {{"Range", std::string("npt=") + std::to_string(range.first) + std::string("-") + std::to_string(range.second)}});
    return read();
}

response client::teardown() {
    write("TEARDOWN", {});
    return read();
}

void client::write(const std::string& method, const std::map<std::string, std::string>& headers) {
    boost::asio::streambuf buf;
    std::ostream request(&buf);

    request << method << " " << url_ << " RTSP/1.0" << sep;
    request << "CSeq: " << cseq_++ << sep;
    if (!session_.empty()) {
        request << "Session: " << session_ << sep;
    }
    for (auto const& [key, val]: headers) {
        request << key << ": " << val << sep;
    }
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
    if (status_code == 200) {
        boost::asio::read_until(socket_, buf, sep + sep);

        std::string header, name, value;
        int content_length = 0;
        while(std::getline(response, header) && header != "\r") {
            std::stringstream ss(header);
            ss >> name >> value;
            name.pop_back();
            std::cout << name << " " << value << '\n';
            res.headers[name] = value;
        }
    } else {
        std::cout << status_code << ' ' << status_message << '\n';
    }

    return res;
}

}
