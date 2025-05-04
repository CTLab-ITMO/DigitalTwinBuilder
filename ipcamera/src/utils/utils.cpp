#include "utils.hpp"

namespace utils {
    template <class Integer, std::size_t S>
    std::enable_if_t<std::is_integral_v<Integer>, Integer> read_integer(byte_iterator& it) {
        Integer res = 0;
        for (std::size_t i = 0; i < S; ++i) {
            res <<= 8;
            res += std::to_integer<Integer>(*(it++));
        }
        return res;
    }
    std::vector<std::byte> read_n_bytes(byte_iterator& it, std::size_t n) {
        std::vector<std::byte> res(n);
        std::copy_n(it, n, res.begin());
        it += n;
        return res;
    }
    uint8_t read_uint8(byte_iterator& it) { return read_integer<uint8_t>(it); }
    uint16_t read_uint16(byte_iterator& it) { return read_integer<uint16_t>(it); }
    uint32_t read_uint24(byte_iterator& it) { return read_integer<uint32_t, 3>(it); }
    uint32_t read_uint32(byte_iterator& it) { return read_integer<uint32_t>(it); }
    uint64_t read_uint64(byte_iterator& it) { return read_integer<uint64_t>(it); }
    template <std::size_t S>
    bytearr<S> read_bytearr(byte_iterator& it) {
        bytearr<S> res;
        std::copy_n(it, S, res.begin());
        it += S;
        return res;
    }
}

