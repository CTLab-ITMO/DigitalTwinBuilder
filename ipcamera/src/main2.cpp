#include "camera/gige/gvcp/client.hpp"
#include "camera/gige/client.hpp"
#include "gige/gvcp/ack.hpp"
#include "gige/gvcp/command.hpp"
#include "gige/gvcp/registers.hpp"
#include <cstdint>
#include <iostream>


int main() {
    camera::gige::client gige("192.168.150.15", "192.168.1.94", 53211);
    camera::gige::gvcp::ack response = gige.gvcp_.execute(camera::gige::gvcp::cmd::readmem(gige.gvcp_.req_id_++, camera::gige::gvcp::registers::second_url, 512));
    std::stringstream sstream(std::string(reinterpret_cast<const char*>(std::get<camera::gige::gvcp::ack::readmem>(response.get_content()).data.data())));
    char b = sstream.get();
    std::stringstream location;
    while (b != ':') {
        location << b;
        sstream >> b;
    }
    std::cout << location.view() << std::endl;
    b = sstream.get();
    std::stringstream filename;
    while (b != '.') {
        filename << b;
        sstream >> b;
    }
    std::cout << filename.view() << std::endl;
    b = sstream.get();
    std::stringstream extension;
    while (b != ';') {
        extension << b;
        sstream >> b;
    }
    std::cout << extension.view() << std::endl;
    b = sstream.get();
    uint32_t address = 0;
    while (b != ';') {
        address *= 10;
        address += b - '0';
        sstream >> b;
    }
    std::cout << address << std::endl;
    b = sstream.get();
    uint32_t length;
    while (!sstream.eof()) {
        length *= 10;
        length += b - '0';
        sstream >> b;
    }
    std::cout << length << std::endl;
    std::ofstream zip_out;
    uint16_t count = length / 536 + 1;
    camera::gige::gvcp::ack xml_response;
    for (int i = 0; i < count; ++i) {
        xml_response = gige.gvcp_.execute(camera::gige::gvcp::cmd::readmem(gige.gvcp_.req_id_++, address + i * 536, 536));
    }
    return 0;
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
