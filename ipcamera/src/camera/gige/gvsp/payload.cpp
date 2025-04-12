/**
 * @file payload.cpp
 * @brief Implementation of image payload handling for GigE Vision GVSP protocol
 *
 * This file contains the implementation of image payload handling functions
 * for the Gigabit Ethernet Vision (GigE Vision) GVSP protocol, specifically
 * for camera image data.
 */

#include "payload.hpp"
#include <iostream>
#include <fstream>

namespace camera::gige::gvsp::payload {

/**
 * @brief Writes the image data to a PGM (Portable GrayMap) file
 *
 * This function saves the image data in binary PGM format (P5). The file will be
 * created at the specified path with a ".pgm" extension added automatically.
 *
 * @param path The base path where the file should be saved (without extension)
 * @throw std::ios_base::failure If file operations fail
 */
void image::write_file(const std::string& path) const {
    std::ofstream f(path + ".pgm",std::ios_base::out
                                 |std::ios_base::binary
                                 |std::ios_base::trunc);

    int maxColorValue = 255;
    f << "P5\n" << size_x << " " << size_y << "\n" << maxColorValue << "\n";
    f.write(reinterpret_cast<const char*>(data.data()), data.size());
}

/**
 * @brief Reads raw image data into the payload buffer
 *
 * This function copies raw image data from a byte iterator into the internal buffer.
 * Currently only supports mono8 pixel format (hardcoded).
 *
 * @param it Iterator pointing to the beginning of raw image data
 * @param size Number of bytes to read from the iterator
 *
 * @todo Implement support for different pixel formats beyond mono8
 */
void image::read(std::byte* it, std::size_t size) {
    // TODO: pixel_formats currently mono8 hard coded
    std::copy_n(it, size, std::back_inserter(data));
}

} // namespace camera::gige:gvsp:payload