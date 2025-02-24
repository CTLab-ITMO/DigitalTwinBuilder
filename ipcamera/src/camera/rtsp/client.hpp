#include <string>
#include <cstdint>
#include <map>
#include <boost/asio.hpp>

namespace camera::rtsp::client {

struct response {
    std::string status;
    std::map<std::string, std::string> headers;
    std::string content;
};

class client {
public:
    client(const std::string& address, uint16_t port);
    response setup(const std::string& url, const std::map<std::string, std::string>& headers);
    response play(const std::pair<uint32_t, uint32_t>& range);
    response teardown();
private:
    void write(const std::string& method, const std::map<std::string, std::string>& headers);
    response read();

    std::string address_;
    uint16_t port_;
    std::string url_;
    std::string session_;
    uint16_t cseq_;

    boost::asio::io_context io_context_;
    boost::asio::ip::tcp::socket socket_{ io_context_ };

    inline static const std::string sep{"\r\n"};
};

}
