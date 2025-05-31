#include <chrono>
#include <thread>
#include "camera/gige/client.hpp"


int main() {
    using namespace std::chrono_literals;
    auto gige = camera::gige::client("192.168.150.15", "192.168.1.94", 53899);
    gige.start_stream();
    std::this_thread::sleep_for(10s);
    gige.stop_stream();
    return 0;
}
