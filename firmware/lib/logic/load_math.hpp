/**
 * @file load_math.hpp
 * @brief Pure conversion helpers used by the electronic-load control stack.
 */

#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>

#include "load_types.hpp"

namespace ElectronicLoad::Logic::Math {

constexpr float DacReferenceVoltage = 2.5f;
// One populated power channel uses a 5 mOhm shunt and approximately 40 V/V
// feedback gain, giving about 0.2 V at the DAC setpoint per output ampere.
constexpr float DacVoltsPerChannelAmp = 0.2f;
constexpr float FastCurrentVoltsPerAmp = 0.25f;
constexpr float AdcReferenceVoltage = 3.3f;
constexpr float AdcFullScale = 4095.0f;
constexpr float NtcSeriesResistanceOhms = 100000.0f;
constexpr float NtcNominalResistanceOhms = 10000.0f;
constexpr float NtcNominalTemperatureK = 298.15f;
constexpr float NtcBeta = 3435.0f;

constexpr bool protectionThresholdsValid(const ProtectionThresholds &thresholds) {
    constexpr ProtectionThresholds ceiling{};
    return thresholds.voltageV >= 0.01f && thresholds.voltageV <= ceiling.voltageV &&
        thresholds.currentA >= 0.01f && thresholds.currentA <= ceiling.currentA &&
        thresholds.powerW >= 0.01f && thresholds.powerW <= ceiling.powerW &&
        thresholds.temperatureC >= 30.0f && thresholds.temperatureC <= ceiling.temperatureC;
}

struct ChannelCurrents {
    float channelA;
    float channelB;
};

inline ChannelCurrents splitCurrent(float totalCurrentA, LoadChannelMode mode) {
    const float current = std::max(totalCurrentA, 0.0f);
    switch (mode) {
        case LoadChannelMode::A:
            return {current, 0.0f};
        case LoadChannelMode::B:
            return {0.0f, current};
        case LoadChannelMode::Both:
            return {current * 0.5f, current * 0.5f};
    }
    return {0.0f, 0.0f};
}

inline uint16_t dacVoltageToCode(float voltage) {
    const float clamped = std::clamp(voltage, 0.0f, DacReferenceVoltage);
    const float normalized = clamped / DacReferenceVoltage;
    return static_cast<uint16_t>(normalized * 65535.0f + 0.5f);
}

inline float dacCodeToVoltage(uint16_t code) {
    return static_cast<float>(code) * DacReferenceVoltage / 65535.0f;
}

inline uint16_t currentToDacCode(float currentA) {
    const float voltage = std::clamp(currentA * DacVoltsPerChannelAmp,
        0.0f, DacReferenceVoltage);
    return dacVoltageToCode(voltage);
}

inline float adcCodeToVoltage(uint16_t code) {
    return static_cast<float>(code) * AdcReferenceVoltage / AdcFullScale;
}

inline float fastCurrentFromAdcCode(uint16_t code) {
    return adcCodeToVoltage(code) / FastCurrentVoltsPerAmp;
}

inline uint16_t fastCurrentToAdcCode(float currentA) {
    if (!std::isfinite(currentA) || currentA <= 0.0f) {
        return 0;
    }
    const float volts = currentA * FastCurrentVoltsPerAmp;
    const float normalized = std::clamp(volts / AdcReferenceVoltage, 0.0f, 1.0f);
    return static_cast<uint16_t>(normalized * AdcFullScale + 0.5f);
}

inline bool ntcTemperatureFromAdcCode(uint16_t code, float &temperatureC) {
    if (code < 8U || code > 4087U) {
        return false;
    }

    const float ratio = static_cast<float>(code) / AdcFullScale;
    const float resistance = NtcSeriesResistanceOhms * ratio / (1.0f - ratio);
    if (!std::isfinite(resistance) || resistance <= 0.0f) {
        return false;
    }

    const float inverseTemperature = 1.0f / NtcNominalTemperatureK +
        std::log(resistance / NtcNominalResistanceOhms) / NtcBeta;
    if (!std::isfinite(inverseTemperature) || inverseTemperature <= 0.0f) {
        return false;
    }

    temperatureC = 1.0f / inverseTemperature - 273.15f;
    return std::isfinite(temperatureC) && temperatureC > -40.0f && temperatureC < 150.0f;
}

} // namespace ElectronicLoad::Logic::Math
