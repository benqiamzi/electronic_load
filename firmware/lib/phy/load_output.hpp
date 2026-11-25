/**
 * @file load_output.hpp
 * @brief Safe control of the DAC setpoint, input switch, reference PWM, and fan.
 */

#pragma once

#include "dac8552.hpp"
#include "lib/logic/load_types.hpp"
#include "stm32f4xx_hal.h"

namespace ElectronicLoad::PHY {

class LoadOutput {
public:
    LoadOutput(Dac8552 &dac, TIM_HandleTypeDef &referenceTimer,
        TIM_HandleTypeDef &fanTimer);

    bool init();
    bool setCurrent(float currentA, Logic::LoadChannelMode mode);
    bool setDacVoltage(uint8_t channel, float voltage);
    float dacVoltage(uint8_t channel) const;
    bool setFanDuty(float dutyPercent);
    float fanDuty() const;
    void enabled(bool enabled);
    bool enabled() const;
    void makeSafe();

    static void emergencyDisableFromIsr();

    static constexpr float MinimumActiveFanDutyPercent = 30.0f;

private:
    Dac8552 &_dac;
    TIM_HandleTypeDef &_referenceTimer;
    TIM_HandleTypeDef &_fanTimer;
    bool _enabled = false;
    float _fanDutyPercent = 100.0f;
};

} // namespace ElectronicLoad::PHY
