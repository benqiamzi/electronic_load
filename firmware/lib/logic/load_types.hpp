/**
 * @file load_types.hpp
 * @brief Shared electronic-load state, fault, measurement, and result types.
 */

#pragma once

#include <cstdint>

namespace ElectronicLoad::Logic {

enum class LoadState : uint8_t {
    Disabled,
    Ramping,
    Enabled,
    Fault,
};

enum class LoadFault : uint8_t {
    None,
    OverCurrent,
    OverVoltage,
    OverPower,
    OverTemperature,
    SensorFailure,
};

struct Measurements {
    float voltageV = 0.0f;
    float currentA = 0.0f;
    float powerW = 0.0f;
    float leftTemperatureC = 0.0f;
    float rightTemperatureC = 0.0f;
    float fastCurrentA = 0.0f;
    uint32_t timestampMs = 0;
    bool valid = false;
};

struct ControlResult {
    bool success = false;
    const char *error = nullptr;

    static constexpr ControlResult ok() {
        return {true, nullptr};
    }

    static constexpr ControlResult failure(const char *message) {
        return {false, message};
    }

    explicit constexpr operator bool() const {
        return success;
    }
};

const char *loadStateName(LoadState state);
const char *loadFaultName(LoadFault fault);

} // namespace ElectronicLoad::Logic
