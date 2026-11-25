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

enum class LoadChannelMode : uint8_t {
    A,
    B,
    Both,
};

enum class LoadFault : uint8_t {
    None,
    OverCurrent,
    OverVoltage,
    OverPower,
    OverTemperature,
    SensorFailure,
    MeasurementFailure,
    OutputFailure,
};

enum class OverCurrentSource : uint8_t {
    None,
    Ina226Alert,
    Ina226Measurement,
    FastAdc,
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
    bool ina226Valid = false;
    bool fastCurrentValid = false;
    bool temperatureValid = false;
};

struct ProtectionThresholds {
    float voltageV = 30.0f;
    float currentA = 2.75f;
    float powerW = 50.0f;
    float temperatureC = 80.0f;
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
const char *loadChannelModeName(LoadChannelMode mode);
const char *overCurrentSourceName(OverCurrentSource source);

} // namespace ElectronicLoad::Logic
