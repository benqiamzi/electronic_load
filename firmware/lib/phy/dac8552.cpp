#include "dac8552.hpp"

#include "main.h"

namespace ElectronicLoad::PHY {

namespace {
constexpr uint8_t WriteBufferA = 0x00;
constexpr uint8_t WriteBufferBAndLoadBoth = 0x34;
constexpr uint32_t SpiTimeoutMs = 10;
}

Dac8552::Dac8552(SPI_HandleTypeDef &spi) : _spi(spi) {
}

bool Dac8552::init() {
    HAL_GPIO_WritePin(DAC_SYNC_GPIO_Port, DAC_SYNC_Pin, GPIO_PIN_SET);
    return writeZero();
}

bool Dac8552::writeBoth(uint16_t channelA, uint16_t channelB) {
    if (!writeFrame(WriteBufferA, channelA)) {
        return false;
    }
    return writeFrame(WriteBufferBAndLoadBoth, channelB);
}

bool Dac8552::writeZero() {
    return writeBoth(0, 0);
}

bool Dac8552::writeFrame(uint8_t control, uint16_t value) {
    uint8_t frame[3] = {
        control,
        static_cast<uint8_t>(value >> 8),
        static_cast<uint8_t>(value & 0xffU),
    };

    HAL_GPIO_WritePin(DAC_SYNC_GPIO_Port, DAC_SYNC_Pin, GPIO_PIN_RESET);
    const HAL_StatusTypeDef status = HAL_SPI_Transmit(&_spi, frame, sizeof(frame), SpiTimeoutMs);
    HAL_GPIO_WritePin(DAC_SYNC_GPIO_Port, DAC_SYNC_Pin, GPIO_PIN_SET);
    return status == HAL_OK;
}

} // namespace ElectronicLoad::PHY
