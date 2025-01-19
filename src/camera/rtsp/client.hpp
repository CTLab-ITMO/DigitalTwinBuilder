#include <string>
#include <cstdint>
#include <map>
#include <boost/asio.hpp>

namespace camera::rtsp::client {

class response {
    std::string status;
    std::map<std::string, std::string> headers;
    std::string content;
};

class client {
public:
    client(const std::string& address, uint16_t port);
    response setup(const std::string& url, const std::map<std::string, std::string>& headers);
    response teardown();
private:
    std::string address_;
    uint16_t port_;
    std::string url_;
    std::string session_;
    uint16_t cseq_;
};

}
