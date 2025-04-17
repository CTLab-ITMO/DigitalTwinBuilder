#include "camera/gige/gvcp/client.hpp"
#include "camera/gige/client.hpp"
#include "gige/gvcp/ack.hpp"
#include "gige/gvcp/command.hpp"
#include "gige/gvcp/registers.hpp"
#include "gige/gvcp/status_codes.hpp"
#include <cstdint>
#include <iostream>
#include <fstream>


int main() {
    camera::gige::client gige("192.168.1.38", "192.168.1.94", 10000);
    auto filename = gige.gvcp_.get_xml_genicam("tmp/");
    gige.gvcp_.parse_xml_genicam(filename);
    gige.start_stream();
    gige.gvsp_.io_context_.run();
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
