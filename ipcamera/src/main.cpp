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
    camera::gige::client gige("192.168.1.38", "192.168.1.94", 53211);
    auto res = gige.gvcp_.execute(camera::gige::gvcp::cmd::readreg(gige.gvcp_.req_id_++, std::vector<uint32_t>{0x0934}));
    if (res.get_header().status == camera::gige::gvcp::status_codes::GEV_STATUS_SUCCESS && !(std::get<camera::gige::gvcp::ack::readreg>(res.get_content()).register_data[0] & (1 << 28))) {
        std::cout << "manifest table is supported" << '\n';
        return 0;
    }
    camera::gige::gvcp::ack response = gige.gvcp_.execute(camera::gige::gvcp::cmd::readmem(gige.gvcp_.req_id_++, camera::gige::gvcp::registers::second_url, 512));
    if (response.get_header().status != camera::gige::gvcp::status_codes::GEV_STATUS_SUCCESS) {
        std::cout << "readmem failed with status: " << response.get_header().status << '\n';
    }
    std::stringstream sstream(std::string(reinterpret_cast<const char*>(std::get<camera::gige::gvcp::ack::readmem>(response.get_content()).data.data())));
    std::string location, filename, extension, temp;
    std::cout << sstream.view() << '\n';
    getline(sstream, location, ':');
    getline(sstream, filename, '.');
    getline(sstream, extension, ';');
    getline(sstream, temp, ';');
    std::cout << temp << '\n';
    uint32_t address = std::stoi(temp, nullptr, 16);
    getline(sstream, temp);
    std::cout << temp << '\n';
    uint32_t length = std::stoi(temp, nullptr, 16);
    std::cout << address << " " << length << std::endl;
    std::ofstream zip_out;
    zip_out.open(filename + std::string(".") + extension);
    uint32_t batch_length = 512;
    uint32_t count = length / batch_length + 1;
    std::cout << count << '\n';
    for (int i = 0; i < count; ++i) {
        std::cout << i << '\n';
        camera::gige::gvcp::ack xml_response = gige.gvcp_.execute(camera::gige::gvcp::cmd::readmem(gige.gvcp_.req_id_++, address + i * batch_length, batch_length));
        if (xml_response.get_header().status == camera::gige::gvcp::status_codes::GEV_STATUS_SUCCESS) {
            zip_out.write(reinterpret_cast<const char*>(std::get<camera::gige::gvcp::ack::readmem>(xml_response.get_content()).data.data()), batch_length);
        }
    }
    zip_out.close();

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
