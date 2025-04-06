#pragma once

#include <cstdint>
#include <vector>
#include <string>


namespace camera::gige::gvsp::payload {
struct payload_type {
    virtual void read(std::byte* it, std::size_t size) = 0;
};

struct image : public payload_type {
    void read(std::byte* it, std::size_t size) override;
    void write_file(const std::string& path) const;
    std::vector<std::byte> data;
    uint64_t timestamp;
    uint32_t pixel_format;
    uint32_t size_x;
    uint32_t size_y;
    uint32_t offset_x;
    uint32_t offset_y;
    uint32_t padding_x;
    uint32_t padding_y;
};
}
