/**
 * @file load_output.hpp
 * @brief Safe control of the DAC setpoint, input switch, reference PWM, and fan.
 */

#pragma once

#include "dac8552.hpp"
#include "stm32f4xx_hal.h"

namespace ElectronicLoad::PHY {

class LoadOutput {
public:
    LoadOutput(Dac8552 &dac, TIM_HandleTypeDef &referenceTimer,
        TIM_HandleTypeDef &fanTimer);

    bool init();
    bool setCurrent(float currentA);
    void enabled(bool enabled);
    bool enabled() const;
    void makeSafe();

    static void emergencyDisableFromIsr();

private:
    Dac8552 &_dac;
    TIM_HandleTypeDef &_referenceTimer;
    TIM_HandleTypeDef &_fanTimer;
    bool _enabled = false;
};

} // namespace ElectronicLoad::PHY
