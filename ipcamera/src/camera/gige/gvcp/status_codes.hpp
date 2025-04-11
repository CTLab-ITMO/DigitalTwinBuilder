/**
 * @file status_codes.hpp
 * @brief GVCP protocol status/error codes
 * @version 0.1
 * @date 2025-04-11
 */

#pragma once
#include <cstdint>

/**
 * @namespace camera::gige::gvcp
 * @brief Namespace for GigE Vision Control Protocol (GVCP) related components
 * 
 * This namespace contains definitions and implementations related to the 
 * GigE Vision Control Protocol used for camera communication.
 */
namespace camera::gige::gvcp {

/**
 * @enum status_codes
 * @brief GVCP protocol status/error codes
 * 
 * Enumeration of all possible status codes defined by the GigE Vision Control Protocol.
 * These codes are used in GVCP command responses to indicate success or failure.
 */
enum status_codes : uint16_t {
        GEV_STATUS_SUCCESS = 0x0000,                              ///< Command completed successfully
        GEV_STATUS_PACKET_RESEND = 0x0100,                        ///< Request for packet resend
        
        // Error codes (0x8000-0x8FFF range)
        GEV_STATUS_NOT_IMPLEMENTED = 0x8001,                      ///< Command not implemented
        GEV_STATUS_INVALID_PARAMETER = 0x8002,                    ///< Invalid parameter in command
        GEV_STATUS_INVALID_ADDRESS = 0x8003,                      ///< Invalid memory address
        GEV_STATUS_WRITE_PROTECT = 0x8004,                        ///< Write to protected area attempted
        GEV_STATUS_BAD_ALIGNMENT = 0x8005,                        ///< Bad alignment in address/length
        GEV_STATUS_ACCESS_DENIED = 0x8006,                        ///< Access to resource denied
        GEV_STATUS_BUSY = 0x8007,                                 ///< Device is busy
        GEV_STATUS_LOCAL_PROBLEM = 0x8008,                        ///< Local problem in device
        GEV_STATUS_MSG_MISMATCH = 0x8009,                         ///< Message mismatch error
        GEV_STATUS_INVALID_PROTOCOL = 0x800A,                     ///< Invalid protocol specified
        GEV_STATUS_NO_MSG = 0x800B,                               ///< No message available
        GEV_STATUS_PACKET_UNAVAILABLE = 0x800C,                   ///< Packet unavailable
        GEV_STATUS_DATA_OVERRUN = 0x800D,                         ///< Data overrun occurred
        GEV_STATUS_INVALID_HEADER = 0x800E,                        ///< Invalid packet header
        GEV_STATUS_WRONG_CONFIG = 0x800F,                         ///< Wrong configuration
        GEV_STATUS_PACKET_NOT_YET_AVAILABLE = 0x8010,             ///< Packet not yet available
        GEV_STATUS_PACKET_AND_PREV_REMOVED_FROM_MEMORY = 0x8011,  ///< Packet and previous removed from memory
        GEV_STATUS_PACKET_REMOVED_FROM_MEMORY = 0x8012,            ///< Packet removed from memory
        GEV_STATUS_ERROR = 0x8FFF                                 ///< Generic error code
};

} // namespace camera::gige::gvcp