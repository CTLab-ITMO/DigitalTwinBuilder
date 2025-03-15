#include "camera/gige/gvcp/client.hpp"
#include "camera/gige/client.hpp"
#include <cstdint>
#include <iostream>


int main() {
    std::cout << "creating client" << '\n';
    camera::gige::gvcp::client gvcp("192.168.150.15");
    std::cout << "starting stream" << '\n';
    uint16_t port = gvcp.start_streaming("192.168.1.12", 13);
    std::cout << "stream started on port " << port << '\n';
    std::string input;
    while(true) {
        std::cin >> input;
        if (input == ":q") {
            gvcp.drop_control();
            break;
        }
        std::cout << "To leave enter :q" << std::endl;
    }
    return 0;
}
