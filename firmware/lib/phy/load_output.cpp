#include "load_output.hpp"

#include "lib/logic/load_math.hpp"
#include "main.h"

namespace ElectronicLoad::PHY {

LoadOutput::LoadOutput(Dac8552 &dac, TIM_HandleTypeDef &referenceTimer,
    TIM_HandleTypeDef &fanTimer) :
    _dac(dac),
    _referenceTimer(referenceTimer),
    _fanTimer(fanTimer) {
}

bool LoadOutput::init() {
    emergencyDisableFromIsr();
    if (!_dac.init()) {
        return false;
    }

    __HAL_TIM_SET_COMPARE(&_fanTimer, TIM_CHANNEL_3, __HAL_TIM_GET_AUTORELOAD(&_fanTimer));
    if (HAL_TIM_PWM_Start(&_fanTimer, TIM_CHANNEL_3) != HAL_OK) {
        return false;
    }
    if (HAL_TIM_PWM_Start(&_referenceTimer, TIM_CHANNEL_3) != HAL_OK) {
        return false;
    }
    return true;
}

bool LoadOutput::setCurrent(float currentA) {
    const uint16_t code = Logic::Math::currentToDacCode(currentA);
    return _dac.writeBoth(code, code);
}

void LoadOutput::enabled(bool enabledValue) {
    _enabled = enabledValue;
    HAL_GPIO_WritePin(TC_EN_GPIO_Port, TC_EN_Pin,
        enabledValue ? GPIO_PIN_SET : GPIO_PIN_RESET);
}

bool LoadOutput::enabled() const {
    return _enabled;
}

void LoadOutput::makeSafe() {
    enabled(false);
    (void)_dac.writeZero();
}

void LoadOutput::emergencyDisableFromIsr() {
    HAL_GPIO_WritePin(TC_EN_GPIO_Port, TC_EN_Pin, GPIO_PIN_RESET);
}

} // namespace ElectronicLoad::PHY
