#include "command_interpreter.hpp"

#include <cctype>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>

namespace ElectronicLoad::Proto {

CommandInterpreter::CommandInterpreter(Logic::LoadController &controller,
    Transport::UsbCdcTransport &transport) :
    _controller(controller),
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
        _transport.send("ElectronicLoad,EL-F411,0,0.1.0\n");
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
    if (commandEquals(command, "SOUR:CURR", "SOURCE:CURRENT")) {
        float value = 0.0f;
        if (argument == nullptr || !parseNumber(argument, value)) {
            pushError(-104, "Current must be a finite number");
            return;
        }
        sendControlError(_controller.current(value));
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

bool CommandInterpreter::commandEquals(const char *value, const char *shortForm,
    const char *longForm) {
    return std::strcmp(value, shortForm) == 0 || std::strcmp(value, longForm) == 0;
}

bool CommandInterpreter::parseNumber(const char *text, float &value) {
    char *end = nullptr;
    value = std::strtof(text, &end);
    while (end != nullptr && (*end == ' ' || *end == '\t')) {
        ++end;
    }
    return end != text && end != nullptr && *end == '\0' && std::isfinite(value);
}

} // namespace ElectronicLoad::Proto
