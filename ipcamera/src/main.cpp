#include "camera/gige/gvcp/client.hpp"
#include "camera/gige/client.hpp"
#include "gige/gvcp/command.hpp"
#include <cstdint>
#include <iostream>


int main() {
    camera::gige::client gige("192.168.1.38", "192.168.1.94", 49999);
    gige.start_stream();
    std::string input;
    while(true) {
        std::cin >> input;
        if (input == ":q") {
            gige.stop_stream();
            break;
        }
        std::cout << "To leave enter :q" << std::endl;
    }
    return 0;
}
