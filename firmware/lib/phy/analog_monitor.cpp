#include "analog_monitor.hpp"

#include <cstddef>

#include "lib/logic/load_math.hpp"
#include "main.h"

namespace ElectronicLoad::PHY {

AnalogMonitor::AnalogMonitor(ADC_HandleTypeDef &adc) : _adc(adc) {
}

void AnalogMonitor::init(uint32_t nowMs) {
    _readings = {};
    _leftValid = false;
    _rightValid = false;
    _lastSampleMs = nowMs;
    _lastTemperatureSequenceMs = nowMs - TemperaturePeriodMs;
    selectMux(true, false);
    _muxChangedMs = nowMs;
    _temperaturePhase = TemperaturePhase::WaitRight;
    _watchdogCode = 0;

    _adcReady = HAL_ADC_Start_DMA(&_adc,
        reinterpret_cast<uint32_t *>(_adcDmaBuffer),
        static_cast<uint32_t>(sizeof(_adcDmaBuffer) / sizeof(_adcDmaBuffer[0]))) == HAL_OK;
    if (_adcReady) {
        applyWatchdog(0, false);
    }
}

void AnalogMonitor::run(uint32_t nowMs) {
    if (!_adcReady) {
        return;
    }
    if (static_cast<uint32_t>(nowMs - _lastSampleMs) < SamplePeriodMs) {
        return;
    }
    _lastSampleMs = nowMs;

    _readings.fastCurrentA = Logic::Math::fastCurrentFromAdcCode(_adcDmaBuffer[0]);
    _readings.timestampMs = nowMs;
    _readings.fastCurrentValid = true;

    switch (_temperaturePhase) {
        case TemperaturePhase::Idle:
            if (static_cast<uint32_t>(nowMs - _lastTemperatureSequenceMs) >=
                TemperaturePeriodMs) {
                selectMux(true, false);
                _muxChangedMs = nowMs;
                _temperaturePhase = TemperaturePhase::WaitRight;
            }
            break;

        case TemperaturePhase::WaitRight:
            if (static_cast<uint32_t>(nowMs - _muxChangedMs) >= MuxSettleMs) {
                _rightValid = Logic::Math::ntcTemperatureFromAdcCode(
                    _adcDmaBuffer[1], _readings.rightTemperatureC);
                selectMux(true, true);
                _muxChangedMs = nowMs;
                _temperaturePhase = TemperaturePhase::WaitLeft;
            }
            break;

        case TemperaturePhase::WaitLeft:
            if (static_cast<uint32_t>(nowMs - _muxChangedMs) >= MuxSettleMs) {
                _leftValid = Logic::Math::ntcTemperatureFromAdcCode(
                    _adcDmaBuffer[1], _readings.leftTemperatureC);
                _lastTemperatureSequenceMs = nowMs;
                _temperaturePhase = TemperaturePhase::Idle;
            }
            break;
    }

    _readings.temperatureValid = _leftValid && _rightValid;
}

const AnalogReadings &AnalogMonitor::readings() const {
    return _readings;
}

void AnalogMonitor::setCurrentLimit(float amps) {
    if (!_adcReady || !(amps > 0.0f)) {
        disableCurrentLimit();
        return;
    }
    const uint16_t code = Logic::Math::fastCurrentToAdcCode(amps);
    if (code == _watchdogCode) {
        return;
    }
    _watchdogCode = code;
    applyWatchdog(code, true);
}

void AnalogMonitor::disableCurrentLimit() {
    if (_watchdogCode == 0) {
        return;
    }
    _watchdogCode = 0;
    applyWatchdog(0, false);
}

uint16_t AnalogMonitor::currentLimitCode() const {
    return _watchdogCode;
}

void AnalogMonitor::applyWatchdog(uint16_t code, bool enable) {
    ADC_AnalogWDGConfTypeDef config = {};
    config.Channel = ADC_CHANNEL_4;
    config.WatchdogMode = enable
        ? ADC_ANALOGWATCHDOG_SINGLE_REG
        : ADC_ANALOGWATCHDOG_NONE;
    config.HighThreshold = enable ? code : 0;
    config.LowThreshold = 0;
    config.ITMode = enable ? ENABLE : DISABLE;
    (void)HAL_ADC_AnalogWDGConfig(&_adc, &config);
}

void AnalogMonitor::selectMux(bool select0, bool select1) {
    HAL_GPIO_WritePin(V_SENSE_SEL0_GPIO_Port, V_SENSE_SEL0_Pin,
        select0 ? GPIO_PIN_SET : GPIO_PIN_RESET);
    HAL_GPIO_WritePin(V_SENSE_SEL1_GPIO_Port, V_SENSE_SEL1_Pin,
        select1 ? GPIO_PIN_SET : GPIO_PIN_RESET);
}

} // namespace ElectronicLoad::PHY
