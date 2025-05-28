/**
 * @file registers.hpp
 * @brief GVCP protocol register addresses
 * @version 0.1
 * @date 2025-04-11
 */

#pragma once
#include <cstdint>

/**
 * @namespace camera::gige::gvcp
 * @brief Namespace for GigE Vision Control Protocol (GVCP) related components
 * 
 * Contains definitions and implementations related to the GigE Vision Control Protocol
 * used for camera communication and control.
 */
namespace camera::gige::gvcp {

/**
 * @enum registers
 * @brief GVCP protocol register addresses
 * 
 * Enumeration of all standard register addresses defined by the GigE Vision Control Protocol.
 * These memory-mapped registers are used to configure and control GigE Vision devices.
 * 
 * @note Register addresses are in hexadecimal format
 * @note All registers are 32-bit unless otherwise specified
 */
enum registers : uint16_t {
    // Device Information Registers
    version = 0x0000,                            ///< Device version information
    device_mode = 0x0004,                        ///< Current device operating mode
    mac_address_high = 0x0008,                   ///< Upper 32 bits of MAC address
    mac_address_low = 0x000c,                    ///< Lower 16 bits of MAC address (padded to 32-bit)

    // Network Configuration Registers
    network_interface_capability = 0x0010,       ///< Supported network interface features
    network_interface_configuration = 0x0014,    ///< Current network interface configuration
    current_ip_address = 0x0024,                 ///< Current IP address
    current_subnet_mask = 0x0034,                 ///< Current subnet mask
    current_default_gateway = 0x0044,            ///< Current default gateway

    // Device Identification Registers
    manufacture_name = 0x0048,                   ///< Manufacturer name string
    model_name = 0x0068,                         ///< Device model name string
    device_version = 0x0088,                     ///< Device version string
    manufacture_info = 0x00a8,                   ///< Additional manufacturer information
    serial_number = 0x00d8,                      ///< Device serial number string
    user_defined_name = 0x00d8,                  ///< User-assigned device name

    // URL and Interface Configuration
    first_url = 0x0200,                          ///< First URL location
    second_url = 0x0400,                         ///< Second URL location
    number_of_interfaces = 0x0600,               ///< Number of network interfaces
    persistent_ip_address = 0x064c,              ///< Persistent IP address
    persistent_subnet_mask = 0x065c,             ///< Persistent subnet mask
    persistent_default_gateway = 0x066c,         ///< Persistent default gateway
    link_speed = 0x0670,                         ///< Current link speed

    // Channel and Capability Registers
    number_of_message_channels = 0x0900,         ///< Available message channels
    number_of_stream_channel = 0x0904,           ///< Available stream channels
    number_of_action_signals = 0x0908,           ///< Available action signals
    action_device_key = 0x090c,                  ///< Action device key
    number_of_active_links = 0x0910,             ///< Currently active links
    gvsp_capability = 0x092c,                    ///< GVSP protocol capabilities
    message_channel_capability = 0x0930,         ///< Message channel capabilities
    gvcp_capability = 0x0934,                   ///< GVCP protocol capabilities

    // Timing and Synchronization
    heartbeat_timeout = 0x0938,                  ///< Heartbeat timeout value
    timestamp_tick_frequency_high = 0x093c,      ///< High part of timestamp frequency
    timestamp_tick_frequency_low = 0x0940,       ///< Low part of timestamp frequency
    timestamp_control = 0x0944,                  ///< Timestamp control register
    timestamp_value_high = 0x0948,               ///< High part of current timestamp
    timestamp_value_low = 0x094c,                ///< Low part of current timestamp

    // Protocol Configuration
    discovery_ack_delay = 0x0950,                ///< Discovery acknowledgment delay
    gvcp_configuration = 0x0954,                ///< GVCP protocol configuration
    pending_timeout = 0x0958,                    ///< Pending operation timeout
    control_switchover_key = 0x095c,             ///< Control channel switchover key
    gvsp_configuration = 0x0960,                ///< GVSP protocol configuration

    // Physical Layer Configuration
    physical_link_configuration_capability = 0x0964,  ///< Physical link capabilities
    physical_link_configuration = 0x0968,        ///< Physical link configuration
    ieee_1588_status = 0x096c,                   ///< IEEE 1588 (PTP) status
    scheduled_action_command_queue_size = 0x0970, ///< Action command queue size
    ieee_1588_extended_capabilities = 0x0974,    ///< Extended PTP capabilities
    ieee_1588_supported_profiles = 0x0978,       ///< Supported PTP profiles
    ieee_1588_selected_profile = 0x097c,         ///< Currently selected PTP profile

    // Control Channel Configuration
    control_channel_privilege = 0x0a00,          ///< Control channel privilege level
    primary_application_port = 0x0a04,           ///< Primary application port
    primary_application_ip_address = 0x0a14,     ///< Primary application IP

    // Message Channel Configuration
    message_channel_port = 0x0b00,               ///< Message channel port
    message_channel_destination_address = 0x0b10, ///< Message channel destination
    message_channel_transmition_timeout = 0x0b14, ///< Message transmission timeout
    message_channel_retry_count = 0x0b18,        ///< Message retry count
    message_channel_source_port = 0x0b1c,        ///< Message channel source port
    message_channel_configuration = 0x0b20,      ///< Message channel configuration

    // Stream Channel 0 Configuration
    stream_channel_port_0 = 0x0d00,              ///< Stream channel 0 port
    stream_channel_packet_size_0 = 0x0d04,       ///< Stream channel 0 packet size
    stream_channel_packet_delay_0 = 0x0d08,      ///< Stream channel 0 packet delay
    stream_channel_destination_address_0 = 0x0d18, ///< Stream channel 0 destination
    stream_channel_source_port_0 = 0x0d1c,       ///< Stream channel 0 source port
    stream_channel_capability_0 = 0x0d20,        ///< Stream channel 0 capabilities
    stream_channel_configuration_0 = 0x0d24,     ///< Stream channel 0 configuration
    stream_channel_zone_0 = 0x0d28,              ///< Stream channel 0 zone
    stream_channel_zone_direction_0 = 0x0d2c,    ///< Stream channel 0 zone direction
    stream_channel_max_packet_count_0 = 0x0d30,  ///< Stream channel 0 max packets
    stream_channel_max_block_size_high_0 = 0x0d34, ///< High part of max block size
    stream_channel_max_block_size_low_0 = 0x0d38, ///< Low part of max block size
    stream_channel_extended_bootstrap_address_0 = 0x0d3c, ///< Extended bootstrap address

    // Special Function Registers
    manifest_table = 0x9000,                     ///< Manifest table location
    action_group_key_0 = 0x9800,                 ///< Action group 0 key
    action_group_mask_0 = 0x9804                 ///< Action group 0 mask
};

} // namespace camera::gige::gvcp