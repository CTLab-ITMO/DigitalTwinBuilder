#include <iostream>
#include "camera/rtsp/client.hpp"

int main() {
    camera::rtsp::client::client client("89.104.66.175", 8554);
    camera::rtsp::client::response res = client.setup("rtsp://89.104.66.175:8554/picture", {});
    try {
        camera::rtsp::client::response res1 = client.play({0, 30});
    } catch (const std::exception& e) {
        std::cout << "Error: " << e.what();
    }
    std::string input;
    while (input != ":q") {
        std::cin >> input;
    }
    client.teardown();
    return 0;
}
