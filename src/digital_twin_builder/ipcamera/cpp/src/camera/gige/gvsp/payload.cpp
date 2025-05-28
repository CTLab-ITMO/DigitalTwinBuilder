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
#include <numeric>

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

// /**
//  * @brief Writes the image data to a PGM (Portable GrayMap) file
//  *
//  * This function saves the image data in binary PGM format (P5). The file will be
//  * created at the specified path with a ".pgm" extension added automatically.
//  *
//  * @param path The base path where the file should be saved (without extension)
//  * @throw std::ios_base::failure If file operations fail
//  */
// void image::write_file(const std::string& path, image_formats format) const {
//     assert(size_x * size_y == data.size());
//     switch (format) {
//         case pgm:
//             std::ofstream f(path + ".pgm", std::ios_base::out
//                                          | std::ios_base::binary
//                                          | std::ios_base::trunc);
//             f << "P5\n" << size_x << " " << size_y << "\n" << 255 << "\n";
//             f.write(reinterpret_cast<const char*>(data.data()), data.size());
//             break;
//         case bmp:
//             std::ofstream f(path + ".bmp", std::ios_base::out
//                                          | std::ios_base::binary
//                                          | std::ios_base::trunc);
//             f << "BM\n";
//             return;
//     }
// }

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

namespace image_format {
void bmp::write_file(const std::string& path, const image& img) {
    std::ofstream f(path + ".bmp", std::ios_base::out
                                 | std::ios_base::binary
                                 | std::ios_base::trunc);
    bmp_header header;
    header.file_size = sizeof(bmp_header) + sizeof(bmp_info) + img.data.size();
    
    bmp_info info;
    info.width = img.size_x;
    info.height = img.size_y;
    info.bits_per_pixel = traits::get_pixel_traits(img.pixel_format).bits_per_pixel;
    info.colors_used = 1 << info.bits_per_pixel;
    std::vector<uint32_t> palette;
    if (info.bits_per_pixel <= 8) {
        palette.resize(info.colors_used);
        for (int i = 0; i < info.colors_used; ++i) {
            // works for monochrome TODO: multichannel
            uint32_t color = 256  * i / info.colors_used;
            palette[i] = 0x00000000 | (color << 16) | (color << 8) | color;
        }
        header.file_size += sizeof(uint32_t) * palette.size();
        header.offset += sizeof(uint32_t) * palette.size();
    }
    f.write(reinterpret_cast<const char*>(&header), sizeof(bmp_header));
    f.write(reinterpret_cast<const char*>(&info), sizeof(bmp_info));
    if (info.bits_per_pixel <= 8) {
        f.write(reinterpret_cast<const char*>(palette.data()), palette.size() * sizeof(uint32_t));
    }
    if (info.bits_per_pixel % 8 == 0 || traits::get_pixel_traits(img.pixel_format).is_packed) {
        if (info.bits_per_pixel * info.width % 32 == 0) {
            f.write(reinterpret_cast<const char*>(img.data.data()), img.data.size());
        } else {

            std::size_t row_size = (info.bits_per_pixel * info.width + 31) / 32 * 4;
            for (std::size_t i = 0; i < info.height; ++i) {
                f.write(reinterpret_cast<const char*>(img.data.data() + i * info.width), row_size);
            }
        }
    } else {
        std::size_t row_size = (info.bits_per_pixel * info.width + 31) / 32 * 4;
        //TODO: unpacked formats not align to byte
    }
    
}
void pgm::write_file(const std::string& path, const image& img) {
    std::ofstream f(path + ".pgm", std::ios_base::out
                                 | std::ios_base::binary
                                 | std::ios_base::trunc);
    pgm_header header;
    header.width = img.size_x;
    header.height = img.size_y;
    header.max_value = 255;
    f.write(reinterpret_cast<const char*>(&header), sizeof(pgm_header));
    f.write(reinterpret_cast<const char*>(img.data.data()), img.data.size());
}
}
} // namespace camera::gige:gvsp:payload
