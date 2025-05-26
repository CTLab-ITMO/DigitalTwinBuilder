#pragma once

#include <array>
#include <cstdint>
#include <cstddef>
#include <vector>
#include <algorithm>
namespace utils {
    template <std::size_t S>
    using bytearr = std::array<std::byte, S>;
    using byte_iterator = std::byte*;

    template <class Integer, std::size_t S = sizeof(Integer)>
    std::enable_if_t<std::is_integral_v<Integer>, Integer> read_integer(byte_iterator& it);
    uint8_t read_uint8(byte_iterator& it);
    uint16_t read_uint16(byte_iterator& it);
    uint32_t read_uint24(byte_iterator& it);
    uint32_t read_uint32(byte_iterator& it);
    uint64_t read_uint64(byte_iterator& it);
    std::vector<std::byte> read_n_bytes(byte_iterator& it, std::size_t n);
    template <std::size_t S>
    bytearr<S> read_bytearr(byte_iterator& it);
    
}

