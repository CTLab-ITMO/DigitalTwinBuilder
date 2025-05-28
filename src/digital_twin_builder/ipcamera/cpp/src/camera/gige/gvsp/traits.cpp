#include "traits.hpp"
namespace camera::gige::gvsp::traits {
pixel_traits get_pixel_traits(const pixel_formats& format) { 
    switch (format) {
        case pixel_formats::Mono1p: return mono1p;
        case pixel_formats::Mono2p: return mono2p;
        case pixel_formats::Mono4p: return mono4p;
        case pixel_formats::Mono8: return mono8;
        case pixel_formats::Mono8s: return mono8s;
        case pixel_formats::Mono10: return mono10;
        case pixel_formats::Mono10Packed1: return mono10_packed1;
        case pixel_formats::Mono12: return mono12;
        case pixel_formats::Mono12Packed1: return mono12_packed1;
        case pixel_formats::Mono14: return mono14;
        case pixel_formats::Mono16: return mono16;
        case pixel_formats::RGB8: return rgb8;
        case pixel_formats::BGR8: return bgr8;
        case pixel_formats::RGBa8: return rgba8;
        case pixel_formats::BGRa8: return bgra8;
        case pixel_formats::RGB10: return rgb10;
        case pixel_formats::BGR10: return bgr10;
        case pixel_formats::RGB12: return rgb12;
        case pixel_formats::BGR12: return bgr12;
        case pixel_formats::RGB16: return rgb16;
        default: return {};
    }
}
}