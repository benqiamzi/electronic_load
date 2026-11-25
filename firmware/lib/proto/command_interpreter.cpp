#include "command_interpreter.hpp"

#include <cctype>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>

namespace ElectronicLoad::Proto {

CommandInterpreter::CommandInterpreter(Logic::LoadController &controller,
    PHY::Ina226 &ina226,
    Transport::UsbCdcTransport &transport) :
    _controller(controller),
    _ina226(ina226),
    _transport(transport) {
}

void CommandInterpreter::run(uint32_t nowMs) {
    if (_transport.consumeRxOverflow()) {
        pushError(-350, "USB receive buffer overflow");
    }
    uint8_t value = 0;
    while (_transport.pop(value)) {
        accept(value, nowMs);
    }
}

void CommandInterpreter::accept(uint8_t value, uint32_t nowMs) {
    if (value == '\r' || value == '\n') {
        if (_discardLine) {
            _discardLine = false;
            _lineLength = 0;
            return;
        }
        if (_lineLength == 0) {
            return;
        }
        _line[_lineLength] = '\0';
        execute(nowMs);
        _lineLength = 0;
        return;
    }

    if (_discardLine) {
        return;
    }
    if (_lineLength >= LineSize - 1U) {
        _discardLine = true;
        _lineLength = 0;
        pushError(-100, "Command line too long");
        return;
    }
    _line[_lineLength++] = static_cast<char>(std::toupper(value));
}

void CommandInterpreter::execute(uint32_t nowMs) {
    char *command = _line.data();
    while (*command == ' ' || *command == '\t') {
        ++command;
    }
    char *end = command + std::strlen(command);
    while (end > command && (end[-1] == ' ' || end[-1] == '\t')) {
        *--end = '\0';
    }

    char response[192] = {};
    if (std::strcmp(command, "*IDN?") == 0) {
        _transport.send("ElectronicLoad,EL-F411,0,0.3.7\n");
        return;
    }
    if (std::strcmp(command, "*RST") == 0) {
        _controller.reset(nowMs);
        return;
    }
    if (commandEquals(command, "INP?", "INPUT?")) {
        _transport.send(_controller.input() ? "1\n" : "0\n");
        return;
    }
    if (commandEquals(command, "SOUR:CURR?", "SOURCE:CURRENT?")) {
        std::snprintf(response, sizeof(response), "%.4f\n", _controller.current());
        _transport.send(response);
        return;
    }
    if (commandEquals(command, "SOUR:CHAN?", "SOURCE:CHANNEL?")) {
        std::snprintf(response, sizeof(response), "%s\n",
            Logic::loadChannelModeName(_controller.channelMode()));
        _transport.send(response);
        return;
    }
    if (commandEquals(command, "FAN:DUTY?", "FAN:DUTY?")) {
        std::snprintf(response, sizeof(response), "%.1f\n", _controller.fanDuty());
        _transport.send(response);
        return;
    }

    const Logic::Measurements &measurement = _controller.measurements();
    if (commandEquals(command, "MEAS:VOLT?", "MEASURE:VOLTAGE?")) {
        std::snprintf(response, sizeof(response), "%.4f\n", measurement.voltageV);
        _transport.send(response);
        return;
    }
    if (commandEquals(command, "MEAS:CURR?", "MEASURE:CURRENT?")) {
        std::snprintf(response, sizeof(response), "%.4f\n", measurement.currentA);
        _transport.send(response);
        return;
    }
    if (commandEquals(command, "MEAS:POW?", "MEASURE:POWER?")) {
        std::snprintf(response, sizeof(response), "%.4f\n", measurement.powerW);
        _transport.send(response);
        return;
    }
    if (commandEquals(command, "MEAS:TEMP?", "MEASURE:TEMPERATURE?")) {
        std::snprintf(response, sizeof(response), "%.2f,%.2f\n",
            measurement.leftTemperatureC, measurement.rightTemperatureC);
        _transport.send(response);
        return;
    }
    if (commandEquals(command, "MEAS:ALL?", "MEASURE:ALL?")) {
        std::snprintf(response, sizeof(response), "%.4f,%.4f,%.4f,%.2f,%.2f\n",
            measurement.voltageV, measurement.currentA, measurement.powerW,
            measurement.leftTemperatureC, measurement.rightTemperatureC);
        _transport.send(response);
        return;
    }
    if (commandEquals(command, "STAT?", "STATUS?")) {
        std::snprintf(response, sizeof(response), "%s,%s,%.4f\n",
            Logic::loadStateName(_controller.state()),
            Logic::loadFaultName(_controller.fault()), _controller.current());
        _transport.send(response);
        return;
    }
    if (commandEquals(command, "SYST:ERR?", "SYSTEM:ERROR?")) {
        sendError();
        return;
    }
    if (commandEquals(command, "SYST:FAULT:CLEAR", "SYSTEM:FAULT:CLEAR")) {
        sendControlError(_controller.clearFault(nowMs));
        return;
    }
    if (commandEquals(command, "SYST:PROT?", "SYSTEM:PROTECTION?")) {
        sendProtectionSettings(Logic::ControlResult::ok());
        return;
    }
    if (commandEquals(command, "SYST:PROT:DEF", "SYSTEM:PROTECTION:DEFAULT")) {
        sendProtectionSettings(_controller.setProtectionThresholds({}));
        return;
    }
    if (commandEquals(command, "DIAG:DAC:ZERO", "DIAGNOSTIC:DAC:ZERO")) {
        sendControlError(_controller.diagnosticDacZero());
        return;
    }
    if (commandEquals(command, "DIAG:DAC:MODE?", "DIAGNOSTIC:DAC:MODE?")) {
        _transport.send(_controller.dacManualMode() ? "MANUAL\n" : "AUTO\n");
        return;
    }
    if (commandEquals(command, "DIAG:DAC:VOLT?", "DIAGNOSTIC:DAC:VOLTAGE?")) {
        std::snprintf(response, sizeof(response), "%.5f,%.5f\n",
            _controller.dacVoltage(1U), _controller.dacVoltage(2U));
        _transport.send(response);
        return;
    }
    if (commandEquals(command, "DIAG:MEAS?", "DIAGNOSTIC:MEASUREMENT?")) {
        const uint32_t ageMs = static_cast<uint32_t>(nowMs - measurement.timestampMs);
        std::snprintf(response, sizeof(response), "%u,%u,%u,%u,%.4f,%lu\n",
            measurement.valid ? 1U : 0U,
            measurement.ina226Valid ? 1U : 0U,
            measurement.fastCurrentValid ? 1U : 0U,
            measurement.temperatureValid ? 1U : 0U,
            measurement.fastCurrentA,
            static_cast<unsigned long>(ageMs));
        _transport.send(response);
        return;
    }
    if (commandEquals(command, "DIAG:OC?", "DIAGNOSTIC:OVERCURRENT?")) {
        std::snprintf(response, sizeof(response), "%s,%.4f,%.4f\n",
            Logic::overCurrentSourceName(_controller.overCurrentSource()),
            _controller.overCurrentIna226A(), _controller.overCurrentFastA());
        _transport.send(response);
        return;
    }
    if (commandEquals(command, "DIAG:LIM?", "DIAGNOSTIC:LIMIT?")) {
        std::snprintf(response, sizeof(response), "%.3f,%lu,%lu\n",
            _controller.currentLimitA(),
            static_cast<unsigned long>(_controller.currentLimitOffTimeUs()),
            static_cast<unsigned long>(_controller.currentLimitEvents()));
        _transport.send(response);
        return;
    }
    if (commandEquals(command, "DIAG:INA?", "DIAGNOSTIC:INA226?")) {
        PHY::Ina226Diagnostics diagnostics;
        if (!_ina226.readDiagnostics(diagnostics)) {
            pushError(-350, "Unable to read INA226 diagnostic registers");
            _transport.send("ERROR\n");
            return;
        }
        std::snprintf(response, sizeof(response),
            "%04X,%d,%04X,%04X,%04X\n",
            diagnostics.configuration, diagnostics.shuntRaw,
            diagnostics.calibration, diagnostics.maskEnable,
            diagnostics.alertLimit);
        _transport.send(response);
        return;
    }

    char *argument = std::strchr(command, ' ');
    if (argument != nullptr) {
        *argument++ = '\0';
        while (*argument == ' ' || *argument == '\t') {
            ++argument;
        }
    }

    if (commandEquals(command, "INP", "INPUT")) {
        if (argument == nullptr) {
            pushError(-109, "Missing input state");
        } else if (std::strcmp(argument, "ON") == 0 || std::strcmp(argument, "1") == 0) {
            sendControlError(_controller.input(true, nowMs));
        } else if (std::strcmp(argument, "OFF") == 0 || std::strcmp(argument, "0") == 0) {
            sendControlError(_controller.input(false, nowMs));
        } else {
            pushError(-222, "Input state must be ON or OFF");
        }
        return;
    }
    if (commandEquals(command, "SYST:PROT", "SYSTEM:PROTECTION")) {
        Logic::ProtectionThresholds thresholds;
        if (!parseProtectionThresholds(argument, thresholds)) {
            sendProtectionSettings(Logic::ControlResult::failure(
                "Expected four finite thresholds: volts,amps,watts,degC"));
            return;
        }
        sendProtectionSettings(_controller.setProtectionThresholds(thresholds));
        return;
    }
    if (commandEquals(command, "SOUR:CURR", "SOURCE:CURRENT")) {
        float value = 0.0f;
        if (argument == nullptr || !parseNumber(argument, value)) {
            pushError(-104, "Current must be a finite number");
            return;
        }
        sendControlError(_controller.current(value));
        return;
    }
    if (commandEquals(command, "SOUR:CHAN", "SOURCE:CHANNEL")) {
        if (argument == nullptr) {
            pushError(-109, "Missing channel mode");
        } else if (std::strcmp(argument, "A") == 0) {
            sendControlError(_controller.channelMode(Logic::LoadChannelMode::A));
        } else if (std::strcmp(argument, "B") == 0) {
            sendControlError(_controller.channelMode(Logic::LoadChannelMode::B));
        } else if (std::strcmp(argument, "BOTH") == 0) {
            sendControlError(_controller.channelMode(Logic::LoadChannelMode::Both));
        } else {
            pushError(-222, "Channel mode must be A, B, or BOTH");
        }
        return;
    }
    if (commandEquals(command, "FAN:DUTY", "FAN:DUTY")) {
        float value = 0.0f;
        if (argument == nullptr || !parseNumber(argument, value)) {
            pushError(-104, "Fan duty must be a finite number");
            return;
        }
        sendControlError(_controller.fanDuty(value));
        return;
    }
    if (commandEquals(command, "DIAG:DAC", "DIAGNOSTIC:DAC")) {
        float value = 0.0f;
        if (argument == nullptr || !parseNumber(argument, value)) {
            pushError(-104, "DAC diagnostic value must be a finite number");
            return;
        }
        sendControlError(_controller.diagnosticDac(value));
        return;
    }
    if (commandEquals(command, "DIAG:DAC:VOLT", "DIAGNOSTIC:DAC:VOLTAGE")) {
        char *separator = argument != nullptr ? std::strchr(argument, ',') : nullptr;
        if (separator == nullptr) {
            pushError(-109, "DAC voltage requires channel,volts");
            return;
        }
        *separator++ = '\0';
        char *channelEnd = nullptr;
        const long channel = std::strtol(argument, &channelEnd, 10);
        while (channelEnd != nullptr && (*channelEnd == ' ' || *channelEnd == '\t')) {
            ++channelEnd;
        }
        if (channelEnd == argument || channelEnd == nullptr || *channelEnd != '\0' ||
            channel < 1 || channel > 2) {
            pushError(-222, "DAC channel must be 1 or 2");
            return;
        }
        float volts = 0.0f;
        if (!parseNumber(separator, volts)) {
            pushError(-104, "DAC voltage must be a finite number");
            return;
        }
        sendControlError(_controller.diagnosticDacVoltage(
            static_cast<uint8_t>(channel), volts));
        return;
    }

    pushError(-100, "Unknown command");
}

void CommandInterpreter::pushError(int code, const char *message) {
    if (_errorCount >= ErrorDepth) {
        return;
    }
    _errors[_errorHead] = {code, message};
    _errorHead = static_cast<uint8_t>((_errorHead + 1U) % ErrorDepth);
    ++_errorCount;
}

void CommandInterpreter::sendError() {
    char response[160] = {};
    if (_errorCount == 0) {
        _transport.send("0,\"No error\"\n");
        return;
    }
    const ErrorEntry entry = _errors[_errorTail];
    _errorTail = static_cast<uint8_t>((_errorTail + 1U) % ErrorDepth);
    --_errorCount;
    std::snprintf(response, sizeof(response), "%d,\"%s\"\n", entry.code, entry.message);
    _transport.send(response);
}

void CommandInterpreter::sendControlError(const Logic::ControlResult &result) {
    if (!result) {
        pushError(-221, result.error != nullptr ? result.error : "Settings conflict");
    }
}

void CommandInterpreter::sendProtectionSettings(const Logic::ControlResult &result) {
    char response[128] = {};
    if (!result) {
        std::snprintf(response, sizeof(response), "ERROR,%s\n", result.error);
    } else {
        const auto &thresholds = _controller.protectionThresholds();
        std::snprintf(response, sizeof(response), "%.4f,%.4f,%.4f,%.4f,%u\n",
            thresholds.voltageV, thresholds.currentA, thresholds.powerW,
            thresholds.temperatureC, _controller.temperatureProtectionEnabled() ? 1U : 0U);
    }
    _transport.send(response);
}

bool CommandInterpreter::parseProtectionThresholds(
    char *argument, Logic::ProtectionThresholds &thresholds) {
    if (argument == nullptr) {
        return false;
    }
    const std::array<float *, 3> fields = {
        &thresholds.voltageV, &thresholds.currentA, &thresholds.powerW,
    };
    for (float *field : fields) {
        char *separator = std::strchr(argument, ',');
        if (separator == nullptr) {
            return false;
        }
        *separator++ = '\0';
        if (!parseNumber(argument, *field)) {
            return false;
        }
        argument = separator;
    }
    return parseNumber(argument, thresholds.temperatureC);
}

bool CommandInterpreter::commandEquals(const char *value, const char *shortForm,
    const char *longForm) {
    return std::strcmp(value, shortForm) == 0 || std::strcmp(value, longForm) == 0;
}

bool CommandInterpreter::parseNumber(const char *text, float &value) {
    char *end = nullptr;
    value = std::strtof(text, &end);
    if (end == text || end == nullptr) {
        return false;
    }
    while (end != nullptr && (*end == ' ' || *end == '\t')) {
        ++end;
    }
    return *end == '\0' && std::isfinite(value);
}

} // namespace ElectronicLoad::Proto
