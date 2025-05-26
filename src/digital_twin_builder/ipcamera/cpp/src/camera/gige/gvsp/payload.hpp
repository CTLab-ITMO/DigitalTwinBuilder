/**
 * @file
 * @brief GigE Vision Streaming Protocol (GVSP) payload handling for camera interface
 */

#pragma once

#include "pixel_formats.hpp"
#include <cstdint>
#include <vector>
#include <string>

/**
 * @namespace camera::gige::gvsp::payload
 * @brief Namespace for GigE Vision Streaming Protocol payload handling
 */
namespace camera::gige::gvsp::payload {
enum image_formats : uint32_t {
    pgm = 0,
    bmp = 1
};

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

    /**
     * @brief Writes the image data to a file
     * @param path Filesystem path where the image should be saved
     */
    void write_file(const std::string& path) const;

    std::vector<std::byte> data;      ///< Raw image pixel data
    uint64_t timestamp;               ///< Timestamp of image capture (in nanoseconds)
    pixel_formats pixel_format;            ///< Pixel format code (GVSP_PIXEL_FORMAT)
    uint32_t size_x;                  ///< Width of the image in pixels
    uint32_t size_y;                  ///< Height of the image in pixels 
    uint32_t offset_x;                ///< X offset of ROI (Region of Interest)
    uint32_t offset_y;                ///< Y offset of ROI (Region of Interest)
    uint32_t padding_x;               ///< X padding added to each line (in bytes)
    uint32_t padding_y;               ///< Y padding added after last line (in bytes)
};

} // namespace camera::gige::gvsp::payload
