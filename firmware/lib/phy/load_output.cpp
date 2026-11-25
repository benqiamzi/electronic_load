#include "load_output.hpp"

#include <algorithm>
#include <cmath>

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

    if (!setFanDuty(100.0f)) {
        return false;
    }
    if (HAL_TIM_PWM_Start(&_fanTimer, TIM_CHANNEL_3) != HAL_OK) {
        return false;
    }
    if (HAL_TIM_PWM_Start(&_referenceTimer, TIM_CHANNEL_3) != HAL_OK) {
        return false;
    }
    return true;
}

bool LoadOutput::setCurrent(float currentA, Logic::LoadChannelMode mode) {
    const Logic::Math::ChannelCurrents currents = Logic::Math::splitCurrent(currentA, mode);
    const uint16_t channelACode = Logic::Math::currentToDacCode(currents.channelA);
    const uint16_t channelBCode = Logic::Math::currentToDacCode(currents.channelB);
    return _dac.writeBoth(channelACode, channelBCode);
}

bool LoadOutput::setDacVoltage(uint8_t channel, float voltage) {
    const uint16_t code = Logic::Math::dacVoltageToCode(voltage);
    if (channel == 1U) {
        return _dac.writeBoth(code, _dac.channelBCode());
    }
    if (channel == 2U) {
        return _dac.writeBoth(_dac.channelACode(), code);
    }
    return false;
}

float LoadOutput::dacVoltage(uint8_t channel) const {
    if (channel == 1U) {
        return Logic::Math::dacCodeToVoltage(_dac.channelACode());
    }
    if (channel == 2U) {
        return Logic::Math::dacCodeToVoltage(_dac.channelBCode());
    }
    return 0.0f;
}

bool LoadOutput::setFanDuty(float dutyPercent) {
    if (!std::isfinite(dutyPercent) || dutyPercent < 0.0f || dutyPercent > 100.0f) {
        return false;
    }
    const uint32_t period = __HAL_TIM_GET_AUTORELOAD(&_fanTimer);
    const uint32_t compare = static_cast<uint32_t>(std::lround(
        static_cast<float>(period) * dutyPercent / 100.0f));
    __HAL_TIM_SET_COMPARE(&_fanTimer, TIM_CHANNEL_3, std::min(compare, period));
    _fanDutyPercent = dutyPercent;
    return true;
}

float LoadOutput::fanDuty() const {
    return _fanDutyPercent;
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
