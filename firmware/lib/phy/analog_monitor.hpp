/**
 * @file analog_monitor.hpp
 * @brief ADC-backed fast-current and dual-thermistor monitor.
 *
 * ADC1 runs a continuous 3-channel scan into a circular DMA buffer:
 * PA4 (fast current), PA5 (multiplexed thermistors), PA6 (reserved).
 * The fast-current channel also has the analog watchdog enabled so the
 * application can cut TC_EN from the ADC interrupt within a few microseconds.
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
    bool fastCurrentValid = false;
    bool temperatureValid = false;
};

class AnalogMonitor {
public:
    explicit AnalogMonitor(ADC_HandleTypeDef &adc);

    void init(uint32_t nowMs);
    void run(uint32_t nowMs);
    const AnalogReadings &readings() const;

    /**
     * @brief Arms the fast-current analog watchdog.
     * @param amps Current threshold; 0 or less disables the watchdog.
     */
    void setCurrentLimit(float amps);
    void disableCurrentLimit();
    uint16_t currentLimitCode() const;

private:
    enum class TemperaturePhase : uint8_t {
        Idle,
        WaitRight,
        WaitLeft,
    };

    void selectMux(bool select0, bool select1);
    void applyWatchdog(uint16_t code, bool enable);

    static constexpr uint32_t SamplePeriodMs = 2;
    static constexpr uint32_t TemperaturePeriodMs = 100;
    static constexpr uint32_t MuxSettleMs = 1;

    ADC_HandleTypeDef &_adc;
    uint16_t _adcDmaBuffer[3] = {};
    AnalogReadings _readings;
    TemperaturePhase _temperaturePhase = TemperaturePhase::Idle;
    uint32_t _lastSampleMs = 0;
    uint32_t _lastTemperatureSequenceMs = 0;
    uint32_t _muxChangedMs = 0;
    uint16_t _watchdogCode = 0;
    bool _adcReady = false;
    bool _leftValid = false;
    bool _rightValid = false;
};

} // namespace ElectronicLoad::PHY
