/**
 * @file load_math.hpp
 * @brief Pure conversion helpers used by the electronic-load control stack.
 */

#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>

namespace ElectronicLoad::Logic::Math {

constexpr float DacReferenceVoltage = 2.5f;
constexpr float DacVoltsPerTotalAmp = 0.1f;
constexpr float FastCurrentVoltsPerAmp = 0.25f;
constexpr float AdcReferenceVoltage = 3.3f;
constexpr float AdcFullScale = 4095.0f;
constexpr float NtcSeriesResistanceOhms = 100000.0f;
constexpr float NtcNominalResistanceOhms = 10000.0f;
constexpr float NtcNominalTemperatureK = 298.15f;
constexpr float NtcBeta = 3435.0f;

inline uint16_t currentToDacCode(float currentA) {
    const float voltage = std::clamp(currentA * DacVoltsPerTotalAmp,
        0.0f, DacReferenceVoltage);
    const float normalized = voltage / DacReferenceVoltage;
    return static_cast<uint16_t>(normalized * 65535.0f + 0.5f);
}

inline float adcCodeToVoltage(uint16_t code) {
    return static_cast<float>(code) * AdcReferenceVoltage / AdcFullScale;
}

inline float fastCurrentFromAdcCode(uint16_t code) {
    return adcCodeToVoltage(code) / FastCurrentVoltsPerAmp;
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
