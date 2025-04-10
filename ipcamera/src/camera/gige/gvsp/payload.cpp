#include "payload.hpp"
#include <iostream>
#include <fstream>

namespace camera::gige::gvsp::payload {
void image::write_file(const std::string& path) const {
    std::ofstream f(path + ".pgm",std::ios_base::out
                                 |std::ios_base::binary
                                 |std::ios_base::trunc);

    int maxColorValue = 255;
    f << "P5\n" << size_x << " " << size_y << "\n" << maxColorValue << "\n";
    f.write(reinterpret_cast<const char*>(data.data()), data.size());
}

void image::read(std::byte* it, std::size_t size) {
    // TODO: pixel_formats currently mono8 hard coded
    std::copy_n(it, size, std::back_inserter(data));
}
}
