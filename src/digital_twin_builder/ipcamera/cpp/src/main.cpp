#include <chrono>
#include <thread>
#include <iostream>
#include "camera/gige/client.hpp"


int main() {
    using namespace std::chrono_literals;
    using namespace camera::gige::gvcp;
    auto gvcp = client("192.168.150.15");
    auto response = gvcp.execute<ack::discovery>(cmd::discovery(1));
    std::cout << response.current_ip << '\n';
    camera::gige::gvcp::client::get_all_gige_devices();
    
    // auto gige = camera::gige::client("192.168.150.15", "192.168.1.94", 53899);
    // gige.start_stream();
    std::this_thread::sleep_for(10s);
    // gige.stop_stream();
    return 0;
}
