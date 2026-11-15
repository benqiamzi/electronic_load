#include "analog_monitor.hpp"

#include <cstddef>

#include "lib/logic/load_math.hpp"
#include "main.h"

namespace ElectronicLoad::PHY {

namespace {
constexpr uint32_t SamplePeriodMs = 2;
constexpr uint32_t TemperaturePeriodMs = 100;
constexpr uint32_t MuxSettleMs = 1;
constexpr uint32_t AdcTimeoutMs = 2;
}

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
}

void AnalogMonitor::run(uint32_t nowMs) {
    if (static_cast<uint32_t>(nowMs - _lastSampleMs) < SamplePeriodMs) {
        return;
    }
    _lastSampleMs = nowMs;

    uint16_t samples[3] = {};
    if (!sample(samples)) {
        _readings.valid = false;
        return;
    }

    _readings.fastCurrentA = Logic::Math::fastCurrentFromAdcCode(samples[0]);
    _readings.timestampMs = nowMs;

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
                    samples[1], _readings.rightTemperatureC);
                selectMux(true, true);
                _muxChangedMs = nowMs;
                _temperaturePhase = TemperaturePhase::WaitLeft;
            }
            break;

        case TemperaturePhase::WaitLeft:
            if (static_cast<uint32_t>(nowMs - _muxChangedMs) >= MuxSettleMs) {
                _leftValid = Logic::Math::ntcTemperatureFromAdcCode(
                    samples[1], _readings.leftTemperatureC);
                _lastTemperatureSequenceMs = nowMs;
                _temperaturePhase = TemperaturePhase::Idle;
            }
            break;
    }

    _readings.valid = _leftValid && _rightValid;
}

const AnalogReadings &AnalogMonitor::readings() const {
    return _readings;
}

bool AnalogMonitor::sample(uint16_t (&samples)[3]) {
    if (HAL_ADC_Start(&_adc) != HAL_OK) {
        return false;
    }

    for (size_t index = 0; index < 3; ++index) {
        if (HAL_ADC_PollForConversion(&_adc, AdcTimeoutMs) != HAL_OK) {
            (void)HAL_ADC_Stop(&_adc);
            return false;
        }
        samples[index] = static_cast<uint16_t>(HAL_ADC_GetValue(&_adc));
    }

    return HAL_ADC_Stop(&_adc) == HAL_OK;
}

void AnalogMonitor::selectMux(bool select0, bool select1) {
    HAL_GPIO_WritePin(V_SENSE_SEL0_GPIO_Port, V_SENSE_SEL0_Pin,
        select0 ? GPIO_PIN_SET : GPIO_PIN_RESET);
    HAL_GPIO_WritePin(V_SENSE_SEL1_GPIO_Port, V_SENSE_SEL1_Pin,
        select1 ? GPIO_PIN_SET : GPIO_PIN_RESET);
}

} // namespace ElectronicLoad::PHY
