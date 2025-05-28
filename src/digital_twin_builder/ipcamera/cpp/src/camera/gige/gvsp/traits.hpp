#pragma once
#include "pixel_formats.hpp"
namespace camera::gige::gvsp::traits {
struct pixel_traits {
    std::size_t channels = 0;
    std::size_t bits_per_pixel = 0;
    bool is_signed = false;
    bool is_packed = false;
};

inline static constexpr pixel_traits mono1p = {.channels = 1, .bits_per_pixel = 1, .is_signed = false, .is_packed = true};
inline static constexpr pixel_traits mono2p = {.channels = 1, .bits_per_pixel = 2, .is_signed = false, .is_packed = true};
inline static constexpr pixel_traits mono4p = {.channels = 1, .bits_per_pixel = 4, .is_signed = false, .is_packed = true};
inline static constexpr pixel_traits mono8 = {.channels = 1, .bits_per_pixel = 8, .is_signed = false, .is_packed = false};
inline static constexpr pixel_traits mono8s = {.channels = 1, .bits_per_pixel = 8, .is_signed = true, .is_packed = false};
inline static constexpr pixel_traits mono10 = {.channels = 1, .bits_per_pixel = 10, .is_signed = false, .is_packed = false};
inline static constexpr pixel_traits mono10_packed1 = {.channels = 1, .bits_per_pixel = 10, .is_signed = false, .is_packed = true};
inline static constexpr pixel_traits mono12 = {.channels = 1, .bits_per_pixel = 12, .is_signed = false, .is_packed = false};
inline static constexpr pixel_traits mono12_packed1 = {.channels = 1, .bits_per_pixel = 12, .is_signed = false, .is_packed = true};
inline static constexpr pixel_traits mono14 = {.channels = 1, .bits_per_pixel = 14, .is_signed = false, .is_packed = false};
inline static constexpr pixel_traits mono16 = {.channels = 1, .bits_per_pixel = 16, .is_signed = false, .is_packed = false};
inline static constexpr pixel_traits rgb8 = {.channels = 3, .bits_per_pixel = 8, .is_signed = false, .is_packed = false};
inline static constexpr pixel_traits bgr8 = {.channels = 3, .bits_per_pixel = 8, .is_signed = false, .is_packed = false};
inline static constexpr pixel_traits rgba8 = {.channels = 4, .bits_per_pixel = 8, .is_signed = false, .is_packed = false};
inline static constexpr pixel_traits bgra8 = {.channels = 4, .bits_per_pixel = 8, .is_signed = false, .is_packed = false};
inline static constexpr pixel_traits rgb10 = {.channels = 3, .bits_per_pixel = 10, .is_signed = false, .is_packed = false};
inline static constexpr pixel_traits bgr10 = {.channels = 3, .bits_per_pixel = 10, .is_signed = false, .is_packed = false};
inline static constexpr pixel_traits rgb12 = {.channels = 3, .bits_per_pixel = 12, .is_signed = false, .is_packed = false};
inline static constexpr pixel_traits bgr12 = {.channels = 3, .bits_per_pixel = 12, .is_signed = false, .is_packed = false};
inline static constexpr pixel_traits rgb16 = {.channels = 3, .bits_per_pixel = 16, .is_signed = false, .is_packed = false};

pixel_traits get_pixel_traits(const pixel_formats& format);
}