/**
 * @file ina226.hpp
 * @brief INA226 voltage, current, power, and alert configuration driver.
 */

#pragma once

#include <cstdint>

#include "stm32f4xx_hal.h"

namespace ElectronicLoad::PHY {

struct Ina226Readings {
    float voltageV = 0.0f;
    float currentA = 0.0f;
    float powerW = 0.0f;
};

struct Ina226Diagnostics {
    uint16_t configuration = 0;
    int16_t shuntRaw = 0;
    uint16_t calibration = 0;
    uint16_t maskEnable = 0;
    uint16_t alertLimit = 0;
};

class Ina226 {
public:
    explicit Ina226(I2C_HandleTypeDef &i2c);

    bool init();
    bool read(Ina226Readings &readings);
    bool readDiagnostics(Ina226Diagnostics &diagnostics);

private:
    bool writeRegister(uint8_t reg, uint16_t value);
    bool readRegister(uint8_t reg, uint16_t &value);

    I2C_HandleTypeDef &_i2c;
    uint16_t _address = 0;
};

} // namespace ElectronicLoad::PHY
