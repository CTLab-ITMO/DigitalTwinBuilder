/**
 * @file
 * @brief GigE Vision Streaming Protocol (GVSP) payload handling for camera interface
 */

#pragma once

#include "pixel_formats.hpp"
#include "traits.hpp"
#include <cstdint>
#include <vector>
#include <string>

/**
 * @namespace camera::gige::gvsp::payload
 * @brief Namespace for GigE Vision Streaming Protocol payload handling
 */
namespace camera::gige::gvsp::payload {

/**
 * @struct payload_type
 * @brief Abstract base class for GVSP payload types
 * 
 * Provides the interface for reading payload data from a byte stream.
 */
struct payload_type {
    /**
     * @brief Pure virtual function to read payload data from a byte stream
     * @param it Iterator pointing to the beginning of the byte stream
     * @param size Size of the available data in bytes
     */
    virtual void read(std::byte* it, std::size_t size) = 0;
};

/**
 * @struct image
 * @brief Image payload structure for GVSP protocol
 *
 * Contains image data and metadata received through GVSP protocol.
 */
struct image : public payload_type {
    image(std::byte*& it);

    /**
     * @brief Reads image data from a byte stream
     * @param it Iterator pointing to the beginning of the byte stream
     * @param size Size of the available data in bytes
     */
    void read(std::byte* it, std::size_t size) override;

    std::vector<std::byte> data;      ///< Raw image pixel data
    uint64_t timestamp;               ///< Timestamp of image capture (in nanoseconds)
    pixel_formats pixel_format;       ///< Pixel format code (GVSP_PIXEL_FORMAT)
    uint32_t size_x;                  ///< Width of the image in pixels
    uint32_t size_y;                  ///< Height of the image in pixels 
    uint32_t offset_x;                ///< X offset of ROI (Region of Interest)
    uint32_t offset_y;                ///< Y offset of ROI (Region of Interest)
    uint32_t padding_x;               ///< X padding added to each line (in bytes)
    uint32_t padding_y;               ///< Y padding added after last line (in bytes)
};

namespace image_format {
    struct bmp {
        #pragma pack(push, 1)
        struct bmp_header {
            uint16_t signature{0x4D42};         // signature
            uint32_t file_size{0};              // file size in bytes     
            uint32_t reserved{0};               // reserved
            uint32_t offset{
                sizeof(bmp_header) +
                sizeof(bmp_info)
            };                                  // offset to image data
        };
        struct bmp_info {
            uint32_t size{sizeof(bmp_info)};    // size of this header
            int32_t width{0};                   // width in pixels
            int32_t height{0};                  // height in pixels
            uint16_t planes{1};                 // number of color planes
            uint16_t bits_per_pixel{0};         // bits per pixel
            uint32_t compression{0};            // compression type
            uint32_t size_image{0};             // size of image data
            int32_t x_pixels_per_meter{100};    // pixels per meter in x axis
            int32_t y_pixels_per_meter{100};    // pixels per meter in y axis
            uint32_t colors_used{0};            // number of colors used
            uint32_t colors_important{0};       // number of important colors
        };
        #pragma pack(pop)

        static void write_file(const std::string& path, const image& img);
    };


    struct pgm {
        #pragma pack(push, 1)
        struct pgm_header {
            const char magic_number{'P'};
            const char version{'5'};
            const char separator0{'\n'};
            int32_t width{0};
            const char space{' '};
            int32_t height{0};
            const char separator1{'\n'};
            uint32_t max_value{255};
            const char separator2{'\n'};
        };
        #pragma pack(pop)
        
        static void write_file(const std::string& path, const image& img);
    };

    
}

} // namespace camera::gige::gvsp::payload
