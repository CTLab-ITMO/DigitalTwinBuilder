#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include "camera/gige/gvcp/client.hpp"
#include "camera/gige/gvcp/command.hpp"
#include "camera/gige/gvcp/registers.hpp"

namespace py = pybind11;

PYBIND11_MODULE(_gvcp, m) {
    py::class_<camera::gige::gvcp::client>(m, "gvcp_client")
        .def(py::init<const std::string&>(), py::arg("tx_address"))
        .def("get_control", &camera::gige::gvcp::client::get_control)
        .def("drop_control", &camera::gige::gvcp::client::drop_control)
        .def("start_streaming", &camera::gige::gvcp::client::start_streaming)
        .def("stop_streaming", &camera::gige::gvcp::client::stop_streaming)
        .def("discovery", &camera::gige::gvcp::client::execute<camera::gige::gvcp::ack::discovery, camera::gige::gvcp::cmd::discovery>)
        .def("writereg", &camera::gige::gvcp::client::execute<camera::gige::gvcp::ack::writereg, camera::gige::gvcp::cmd::writereg>)
        .def("readreg", &camera::gige::gvcp::client::execute<camera::gige::gvcp::ack::readreg, camera::gige::gvcp::cmd::readreg>)
        .def("writemem", &camera::gige::gvcp::client::execute<camera::gige::gvcp::ack::writemem, camera::gige::gvcp::cmd::writemem>)
        .def("readmem", &camera::gige::gvcp::client::execute<camera::gige::gvcp::ack::readmem, camera::gige::gvcp::cmd::readmem>)
        .def("get_address", &camera::gige::gvcp::client::get_address)
        .def("start_heartbeat", &camera::gige::gvcp::client::start_heartbeat)
        .def("stop_heartbeat", &camera::gige::gvcp::client::stop_heartbeat)
        .def("get_all_gige_devices", &camera::gige::gvcp::client::get_all_gige_devices)
        .def("get_xml_genicam", &camera::gige::gvcp::client::get_xml_genicam)
        .def("parse_xml_genicam", &camera::gige::gvcp::client::parse_xml_genicam);
    
    py::class_<camera::gige::gvcp::cmd::discovery>(m, "discovery")
        .def(py::init<uint16_t>(), py::arg("req_id"));
    
    py::class_<camera::gige::gvcp::cmd::writereg>(m, "writereg")
        .def(py::init<uint16_t, const std::vector<std::pair<uint32_t, uint32_t>>&>(), py::arg("req_id"), py::arg("addresses"));
    
    py::class_<camera::gige::gvcp::cmd::readreg>(m, "readreg")
        .def(py::init<uint16_t, const std::vector<uint32_t>&>(), py::arg("req_id"), py::arg("addresses"));
    
    py::class_<camera::gige::gvcp::cmd::writemem>(m, "writemem")
        .def(py::init<uint16_t, uint32_t, const std::vector<std::byte>&>(), py::arg("req_id"), py::arg("address"), py::arg("data"));
    
    py::class_<camera::gige::gvcp::cmd::readmem>(m, "readmem")
        .def(py::init<uint16_t, uint32_t, uint16_t>(), py::arg("req_id"), py::arg("address"), py::arg("count"));

    py::enum_<camera::gige::gvcp::registers>(m, "registers")
        .value("version", camera::gige::gvcp::registers::version)
        .value("device_mode", camera::gige::gvcp::registers::device_mode)
        .value("mac_address_high", camera::gige::gvcp::registers::mac_address_high)
        .value("mac_address_low", camera::gige::gvcp::registers::mac_address_low)
        .value("network_interface_capability", camera::gige::gvcp::registers::network_interface_capability)
        .value("network_interface_configuration", camera::gige::gvcp::registers::network_interface_configuration)
        .value("current_ip_address", camera::gige::gvcp::registers::current_ip_address)
        .value("current_subnet_mask", camera::gige::gvcp::registers::current_subnet_mask)
        .value("current_default_gateway", camera::gige::gvcp::registers::current_default_gateway)
        .value("manufacture_name", camera::gige::gvcp::registers::manufacture_name)
        .value("model_name", camera::gige::gvcp::registers::model_name)
        .value("device_version", camera::gige::gvcp::registers::device_version)
        .value("manufacture_info", camera::gige::gvcp::registers::manufacture_info)
        .value("serial_number", camera::gige::gvcp::registers::serial_number)
        .value("user_defined_name", camera::gige::gvcp::registers::user_defined_name)
        .value("first_url", camera::gige::gvcp::registers::first_url)
        .value("second_url", camera::gige::gvcp::registers::second_url)
        .value("number_of_interfaces", camera::gige::gvcp::registers::number_of_interfaces)
        .value("persistent_ip_address", camera::gige::gvcp::registers::persistent_ip_address)
        .value("persistent_subnet_mask", camera::gige::gvcp::registers::persistent_subnet_mask)
        .value("persistent_default_gateway", camera::gige::gvcp::registers::persistent_default_gateway)
        .value("link_speed", camera::gige::gvcp::registers::link_speed)
        .value("number_of_message_channels", camera::gige::gvcp::registers::number_of_message_channels)
        .value("number_of_stream_channel", camera::gige::gvcp::registers::number_of_stream_channel)
        .value("number_of_action_signals", camera::gige::gvcp::registers::number_of_action_signals)
        .value("action_device_key", camera::gige::gvcp::registers::action_device_key)
        .value("number_of_active_links", camera::gige::gvcp::registers::number_of_active_links)
        .value("gvsp_capability", camera::gige::gvcp::registers::gvsp_capability)
        .value("message_channel_capability", camera::gige::gvcp::registers::message_channel_capability)
        .value("gvcp_capability", camera::gige::gvcp::registers::gvcp_capability)
        .value("heartbeat_timeout", camera::gige::gvcp::registers::heartbeat_timeout)
        .value("timestamp_tick_frequency_high", camera::gige::gvcp::registers::timestamp_tick_frequency_high)
        .value("timestamp_tick_frequency_low", camera::gige::gvcp::registers::timestamp_tick_frequency_low)
        .value("timestamp_control", camera::gige::gvcp::registers::timestamp_control)
        .value("timestamp_value_high", camera::gige::gvcp::registers::timestamp_value_high)
        .value("timestamp_value_low", camera::gige::gvcp::registers::timestamp_value_low)
        .value("discovery_ack_delay", camera::gige::gvcp::registers::discovery_ack_delay)
        .value("gvcp_configuration", camera::gige::gvcp::registers::gvcp_configuration)
        .value("pending_timeout", camera::gige::gvcp::registers::pending_timeout)
        .value("control_switchover_key", camera::gige::gvcp::registers::control_switchover_key)
        .value("gvsp_configuration", camera::gige::gvcp::registers::gvsp_configuration)
        .value("physical_link_configuration_capability", camera::gige::gvcp::registers::physical_link_configuration_capability)
        .value("physical_link_configuration", camera::gige::gvcp::registers::physical_link_configuration)
        .value("ieee_1588_status", camera::gige::gvcp::registers::ieee_1588_status)
        .value("scheduled_action_command_queue_size", camera::gige::gvcp::registers::scheduled_action_command_queue_size)
        .value("ieee_1588_extended_capabilities", camera::gige::gvcp::registers::ieee_1588_extended_capabilities)
        .value("ieee_1588_supported_profiles", camera::gige::gvcp::registers::ieee_1588_supported_profiles)
        .value("ieee_1588_selected_profile", camera::gige::gvcp::registers::ieee_1588_selected_profile)
        .value("control_channel_privilege", camera::gige::gvcp::registers::control_channel_privilege)
        .value("primary_application_port", camera::gige::gvcp::registers::primary_application_port)
        .value("primary_application_ip_address", camera::gige::gvcp::registers::primary_application_ip_address)
        .value("message_channel_port", camera::gige::gvcp::registers::message_channel_port)
        .value("message_channel_destination_address", camera::gige::gvcp::registers::message_channel_destination_address)
        .value("message_channel_transmition_timeout", camera::gige::gvcp::registers::message_channel_transmition_timeout)
        .value("message_channel_retry_count", camera::gige::gvcp::registers::message_channel_retry_count)
        .value("message_channel_source_port", camera::gige::gvcp::registers::message_channel_source_port)
        .value("message_channel_configuration", camera::gige::gvcp::registers::message_channel_configuration)
        .value("stream_channel_port_0", camera::gige::gvcp::registers::stream_channel_port_0)
        .value("stream_channel_packet_size_0", camera::gige::gvcp::registers::stream_channel_packet_size_0)
        .value("stream_channel_packet_delay_0", camera::gige::gvcp::registers::stream_channel_packet_delay_0)
        .value("stream_channel_destination_address_0", camera::gige::gvcp::registers::stream_channel_destination_address_0)
        .value("stream_channel_source_port_0", camera::gige::gvcp::registers::stream_channel_source_port_0)
        .value("stream_channel_capability_0", camera::gige::gvcp::registers::stream_channel_capability_0)
        .value("stream_channel_configuration_0", camera::gige::gvcp::registers::stream_channel_configuration_0)
        .value("stream_channel_zone_0", camera::gige::gvcp::registers::stream_channel_zone_0)
        .value("stream_channel_zone_direction_0", camera::gige::gvcp::registers::stream_channel_zone_direction_0)
        .value("stream_channel_max_packet_count_0", camera::gige::gvcp::registers::stream_channel_max_packet_count_0)
        .value("stream_channel_max_block_size_high_0", camera::gige::gvcp::registers::stream_channel_max_block_size_high_0)
        .value("stream_channel_max_block_size_low_0", camera::gige::gvcp::registers::stream_channel_max_block_size_low_0)
        .value("stream_channel_extended_bootstrap_address_0", camera::gige::gvcp::registers::stream_channel_extended_bootstrap_address_0)
        .value("manifest_table", camera::gige::gvcp::registers::manifest_table)
        .value("action_group_key_0", camera::gige::gvcp::registers::action_group_key_0)
        .value("action_group_mask_0", camera::gige::gvcp::registers::action_group_mask_0);
    
    py::enum_<camera::gige::gvcp::status_codes>(m, "status_codes")
        .value("GEV_STATUS_SUCCESS", camera::gige::gvcp::status_codes::GEV_STATUS_SUCCESS)
        .value("GEV_STATUS_PACKET_RESEND", camera::gige::gvcp::status_codes::GEV_STATUS_PACKET_RESEND)
        .value("GEV_STATUS_NOT_IMPLEMENTED", camera::gige::gvcp::status_codes::GEV_STATUS_NOT_IMPLEMENTED)
        .value("GEV_STATUS_INVALID_PARAMETER", camera::gige::gvcp::status_codes::GEV_STATUS_INVALID_PARAMETER)
        .value("GEV_STATUS_INVALID_ADDRESS", camera::gige::gvcp::status_codes::GEV_STATUS_INVALID_ADDRESS)
        .value("GEV_STATUS_WRITE_PROTECT", camera::gige::gvcp::status_codes::GEV_STATUS_WRITE_PROTECT)
        .value("GEV_STATUS_BAD_ALIGNMENT", camera::gige::gvcp::status_codes::GEV_STATUS_BAD_ALIGNMENT)
        .value("GEV_STATUS_ACCESS_DENIED", camera::gige::gvcp::status_codes::GEV_STATUS_ACCESS_DENIED)
        .value("GEV_STATUS_BUSY", camera::gige::gvcp::status_codes::GEV_STATUS_BUSY)
        .value("GEV_STATUS_LOCAL_PROBLEM", camera::gige::gvcp::status_codes::GEV_STATUS_LOCAL_PROBLEM)
        .value("GEV_STATUS_MSG_MISMATCH", camera::gige::gvcp::status_codes::GEV_STATUS_MSG_MISMATCH)
        .value("GEV_STATUS_INVALID_PROTOCOL", camera::gige::gvcp::status_codes::GEV_STATUS_INVALID_PROTOCOL)
        .value("GEV_STATUS_NO_MSG", camera::gige::gvcp::status_codes::GEV_STATUS_NO_MSG)
        .value("GEV_STATUS_PACKET_UNAVAILABLE", camera::gige::gvcp::status_codes::GEV_STATUS_PACKET_UNAVAILABLE)
        .value("GEV_STATUS_DATA_OVERRUN", camera::gige::gvcp::status_codes::GEV_STATUS_DATA_OVERRUN)
        .value("GEV_STATUS_INVALID_HEADER", camera::gige::gvcp::status_codes::GEV_STATUS_INVALID_HEADER)
        .value("GEV_STATUS_WRONG_CONFIG", camera::gige::gvcp::status_codes::GEV_STATUS_WRONG_CONFIG)
        .value("GEV_STATUS_PACKET_NOT_YET_AVAILABLE", camera::gige::gvcp::status_codes::GEV_STATUS_PACKET_NOT_YET_AVAILABLE)
        .value("GEV_STATUS_PACKET_AND_PREV_REMOVED_FROM_MEMORY", camera::gige::gvcp::status_codes::GEV_STATUS_PACKET_AND_PREV_REMOVED_FROM_MEMORY)
        .value("GEV_STATUS_PACKET_REMOVED_FROM_MEMORY", camera::gige::gvcp::status_codes::GEV_STATUS_PACKET_REMOVED_FROM_MEMORY)
        .value("GEV_STATUS_ERROR", camera::gige::gvcp::status_codes::GEV_STATUS_ERROR);
        
}
