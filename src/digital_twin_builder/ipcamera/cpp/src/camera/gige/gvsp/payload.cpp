/**
 * @file payload.cpp
 * @brief Implementation of image payload handling for GigE Vision GVSP protocol
 *
 * This file contains the implementation of image payload handling functions
 * for the Gigabit Ethernet Vision (GigE Vision) GVSP protocol, specifically
 * for camera image data.
 */

#include "payload.hpp"
#include "utils.hpp"
#include <cassert>
#include <iostream>
#include <fstream>

namespace camera::gige::gvsp::payload {
image::image(std::byte*& it) {
    timestamp = utils::read_uint64(it);
    pixel_format = static_cast<pixel_formats>(utils::read_uint32(it));
    size_x = utils::read_uint32(it);
    size_y = utils::read_uint32(it);
    offset_x = utils::read_uint32(it);
    offset_y = utils::read_uint32(it);
    padding_x = utils::read_uint16(it);
}

/**
 * @brief Writes the image data to a PGM (Portable GrayMap) file
 *
 * This function saves the image data in binary PGM format (P5). The file will be
 * created at the specified path with a ".pgm" extension added automatically.
 *
 * @param path The base path where the file should be saved (without extension)
 * @throw std::ios_base::failure If file operations fail
 */
void image::write_file(const std::string& path, image_formats format) const {
    assert(size_x * size_y == data.size());
    switch (format) {
        case pgm:
            std::ofstream f(path + ".pgm", std::ios_base::out
                                         | std::ios_base::binary
                                         | std::ios_base::trunc);
            f << "P5\n" << size_x << " " << size_y << "\n" << 255 << "\n";
            f.write(reinterpret_cast<const char*>(data.data()), data.size());
            break;
        case bmp:
            std::ofstream f(path + ".bmp", std::ios_base::out
                                         | std::ios_base::binary
                                         | std::ios_base::trunc);
            f << "BM\n";
            return;
    }
}

/**
 * @brief Reads raw image data into the payload buffer
 *
 * This function copies raw image data from a byte iterator into the internal buffer.
 *
 * @param it Iterator pointing to the beginning of raw image data
 * @param size Number of bytes to read from the iterator
 *
 */
void image::read(std::byte* it, std::size_t size) {
    std::copy_n(it, size, std::back_inserter(data));
}

} // namespace camera::gige:gvsp:payload
