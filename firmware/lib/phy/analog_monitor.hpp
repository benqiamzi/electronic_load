/**
 * @file analog_monitor.hpp
 * @brief ADC-backed fast-current and dual-thermistor monitor.
 *
 * ADC1 scans PA4, PA5, and the reserved PA6 input. PA5 is fed by an analog
 * multiplexer, so the monitor sequences its select pins without blocking the
 * application loop and converts the two 10 kOhm B3435 thermistors.
 */

#pragma once

#include <cstdint>

#include "stm32f4xx_hal.h"

namespace ElectronicLoad::PHY {

struct AnalogReadings {
    float fastCurrentA = 0.0f;
    float leftTemperatureC = 0.0f;
    float rightTemperatureC = 0.0f;
    uint32_t timestampMs = 0;
    bool valid = false;
};

class AnalogMonitor {
public:
    explicit AnalogMonitor(ADC_HandleTypeDef &adc);

    void init(uint32_t nowMs);
    void run(uint32_t nowMs);
    const AnalogReadings &readings() const;

private:
    enum class TemperaturePhase : uint8_t {
        Idle,
        WaitRight,
        WaitLeft,
    };

    bool sample(uint16_t (&samples)[3]);
    void selectMux(bool select0, bool select1);

    ADC_HandleTypeDef &_adc;
    AnalogReadings _readings;
    TemperaturePhase _temperaturePhase = TemperaturePhase::Idle;
    uint32_t _lastSampleMs = 0;
    uint32_t _lastTemperatureSequenceMs = 0;
    uint32_t _muxChangedMs = 0;
    bool _leftValid = false;
    bool _rightValid = false;
};

} // namespace ElectronicLoad::PHY
