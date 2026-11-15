/**
 * @file dac8552.hpp
 * @brief SPI driver for the dual-channel DAC8552 current-setpoint DAC.
 */

#pragma once

#include <cstdint>

#include "stm32f4xx_hal.h"

namespace ElectronicLoad::PHY {

class Dac8552 {
public:
    explicit Dac8552(SPI_HandleTypeDef &spi);

    bool init();
    bool writeBoth(uint16_t channelA, uint16_t channelB);
    bool writeZero();

private:
    bool writeFrame(uint8_t control, uint16_t value);

    SPI_HandleTypeDef &_spi;
};

} // namespace ElectronicLoad::PHY
