/**
 * @file command_interpreter.hpp
 * @brief Fixed-memory SCPI-style command parser for the USB CDC interface.
 */

#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

#include "lib/logic/load_controller.hpp"
#include "lib/phy/ina226.hpp"
#include "lib/transport/usb_cdc_transport.hpp"

namespace ElectronicLoad::Proto {

class CommandInterpreter {
public:
    CommandInterpreter(Logic::LoadController &controller,
        PHY::Ina226 &ina226,
        Transport::UsbCdcTransport &transport);

    void run(uint32_t nowMs);

private:
    struct ErrorEntry {
        int code = 0;
        const char *message = "No error";
    };

    void accept(uint8_t value, uint32_t nowMs);
    void execute(uint32_t nowMs);
    void pushError(int code, const char *message);
    void sendError();
    void sendControlError(const Logic::ControlResult &result);
    void sendProtectionSettings(const Logic::ControlResult &result);
    static bool parseProtectionThresholds(char *argument, Logic::ProtectionThresholds &thresholds);
    static bool commandEquals(const char *value, const char *shortForm,
        const char *longForm);
    static bool parseNumber(const char *text, float &value);

    static constexpr size_t LineSize = 128;
    static constexpr size_t ErrorDepth = 8;

    Logic::LoadController &_controller;
    PHY::Ina226 &_ina226;
    Transport::UsbCdcTransport &_transport;
    std::array<char, LineSize> _line{};
    size_t _lineLength = 0;
    bool _discardLine = false;
    std::array<ErrorEntry, ErrorDepth> _errors{};
    uint8_t _errorHead = 0;
    uint8_t _errorTail = 0;
    uint8_t _errorCount = 0;
};

} // namespace ElectronicLoad::Proto
