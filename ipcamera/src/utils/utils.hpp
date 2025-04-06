#pragma once

#include <array>

namespace utils {
    template <std::size_t S>
    using bytearr = std::array<std::byte, S>;
    using byte_iterator = std::byte*;

    template <class Integer, std::size_t S = sizeof(Integer)>
    std::enable_if_t<std::is_integral_v<Integer>, Integer> read_integer(byte_iterator& it) {
        Integer res = 0;
        for (std::size_t i = 0; i < S; ++i) {
            res <<= 8;
            res += std::to_integer<Integer>(*(it++));
        }
        return res;
    }
    constexpr uint8_t(*read_uint8)(byte_iterator& it) = &read_integer<uint8_t>;
    constexpr uint16_t(*read_uint16)(byte_iterator& it) = &read_integer<uint16_t>;
    constexpr uint32_t(*read_uint24)(byte_iterator& it) = &read_integer<uint32_t, 3>;
    constexpr uint32_t(*read_uint32)(byte_iterator& it) = &read_integer<uint32_t>;
    constexpr uint64_t(*read_uint64)(byte_iterator& it) = &read_integer<uint64_t>;
    std::vector<std::byte> read_n_bytes(byte_iterator& it, std::size_t n) {
        std::vector<std::byte> res(n);
        std::copy_n(it, n, res.begin());
        it += n;
        return res;
    }
    template <std::size_t S>
    bytearr<S> read_bytearr(byte_iterator& it) {
        bytearr<S> res;
        std::copy_n(it, S, res.begin());
        it += S;
        return res;
    }
}

