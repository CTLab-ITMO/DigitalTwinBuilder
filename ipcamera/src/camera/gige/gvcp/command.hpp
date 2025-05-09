/**
* @file command.hpp
* @brief GVCP (GigE Vision Control Protocol) command classes implementation
* @version 0.1
* @date 2025-04-12
* 
* This file defines the base command class and specific command implementations 
* for the GigE Vision Control Protocol (GVCP) used in camera communication.
*/

#pragma once

#include "ack.hpp"
#include <boost/asio.hpp>
#include <cstdint>
#include <type_traits>

/**
* @brief Namespace for GigE Vision Control Protocol (GVCP) command classes
*/
namespace camera::gige::gvcp::cmd {

/**
* @brief Enumeration of GVCP command types
*/
enum class command_values : uint16_t {
    discovery_cmd = 0x0002,      ///< Device discovery command
    forceip_cmd = 0x0004,        ///< Force IP configuration command
    packetresend_cmd = 0x0040,   ///< Packet resend request command
    readreg_cmd = 0x0080,        ///< Register read command
    writereg_cmd = 0x0082,       ///< Register write command
    readmem_cmd = 0x0084,        ///< Memory read command
    writemem_cmd = 0x0086,       ///< Memory write command
    event_cmd = 0x00c0,          ///< Event notification command
    eventdata_cmd = 0x00c2,      ///< Event data transmission command
    action_cmd = 0x0100          ///< Action trigger command
};

/**
* @brief Base class for all GVCP commands
*
* This class provides common functionality for all GVCP commands, including buffer management and acknowledgment handling.
*/
class command {
public:
    /**
    * @brief Get a const buffer representation of the command
    * @return boost::asio::const_buffer containing the serialized command data
    */
    boost::asio::const_buffer get_buffer() const;

    /**
    * @brief Send the command and receive an acknowledgment from the device.
    *
    * This method sends the serialized version of this Command to a device over a UDP socket, 
    then waits for and returns an acknowledgment from the device.
    *
    * @param socket The UDP socket to use for communication with the device.
    *
    * @return The acknowledgment received from the device as an `ack` object.
    */
    ack get_ack(boost::asio::ip::udp::socket& socket) const;
 
protected:
    /**
    * @brief Write an integral value to the content buffer in network byte order.
    *
    * This template method writes integral values to the internal buffer,
    converting them to network byte order as required by GVCP protocol.
    *
    * @tparam T Integral type of value to write (automatically deduced) 
    * @param val Value to write to buffer.
    * @note This template method is SFINAE-enabled and will only be available for integral types.
    */
    template <class T>
    std::enable_if_t<std::is_integral_v<T>> writeint(T val); 
    std::vector<std::byte> content_; ///< Internal buffer for command data
};

/** @brief A command class for device discovery.
 * 
 * This class represents a discovery command used to identify devices.
 * It inherits from the base 'command' class.
 */
class discovery : public command {
public:
    /**
     * @brief Construct a new discovery command object.
     * 
     * @param req_id The request ID for this command.
     */
    discovery(uint16_t req_id);
};

/**
 * @brief A command class for reading memory.
 * 
 * This class represents a command to read memory from a device.
 * It inherits from the base 'command' class.
 */
class readmem : public command {
public:
    /**
     * @brief Construct a new readmem command object.
     * 
     * @param req_id The request ID for this command.
     * @param address The starting memory address to read from.
     * @param count The number of bytes to read.
     */
    readmem(uint16_t req_id, uint32_t address, uint16_t count);
};

/**
 * @brief A command class for reading registers.
 * 
 * This class represents a command to read multiple registers from a device.
 * It inherits from the base 'command' class.
 */
class readreg : public command {
public:
    /**
     * @brief Construct a new readreg command object.
     * 
     * @param req_id The request ID for this command.
     * @param addresses A vector of register addresses to read from.
     */
    readreg(uint16_t req_id, const std::vector<uint32_t>& addresses);
};

/**
 * @brief A command class for writing data to memory.
 * 
 * This class represents a command to write a block of data to a specific memory address.
 * It inherits from the base `command` class.
 */
class writemem : public command {
public:
    /**
     * @brief Constructs a writemem command object.
     * 
     * @param req_id The request ID for tracking/identification purposes.
     * @param address The target memory address where data will be written.
     * @param data The data to be written, as a vector of bytes.
     */
    writemem(uint16_t req_id, uint32_t address, const std::vector<std::byte>& data);
};

/**
 * @brief A command class for writing to registers.
 * 
 * This class represents a command to write values to multiple registers.
 * It inherits from the base `command` class.
 */
class writereg : public command {
public:
    /**
     * @brief Constructs a writereg command object.
     * 
     * @param req_id The request ID for tracking/identification purposes.
     * @param addresses A vector of register address-value pairs to be written.
     *                  Each pair consists of:
     *                  - first: The register address
     *                  - second: The value to write to the register
     */
    writereg(uint16_t req_id, const std::vector<std::pair<uint32_t, uint32_t>>& addresses);
};

} // namespace camera::gige::gvcp::cmd
