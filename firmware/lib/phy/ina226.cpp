#include "ina226.hpp"

#include <algorithm>

namespace ElectronicLoad::PHY {

namespace {
constexpr uint8_t FirstAddress = 0x40;
constexpr uint8_t LastAddress = 0x4f;
constexpr uint8_t ConfigurationRegister = 0x00;
constexpr uint8_t BusVoltageRegister = 0x02;
constexpr uint8_t PowerRegister = 0x03;
constexpr uint8_t CurrentRegister = 0x04;
constexpr uint8_t CalibrationRegister = 0x05;
constexpr uint8_t MaskEnableRegister = 0x06;
constexpr uint8_t AlertLimitRegister = 0x07;
constexpr uint8_t ManufacturerIdRegister = 0xfe;
constexpr uint16_t ManufacturerId = 0x5449;
constexpr uint16_t Configuration = 0x4127;
constexpr uint16_t Calibration = 5120;
constexpr uint16_t ShuntOvervoltageEnable = 0x8000;
constexpr uint16_t AlertLimit = 10500;
constexpr float BusVoltageLsbV = 0.00125f;
constexpr float BusDividerRatio = 2.0f;
constexpr float CurrentLsbA = 0.0002f;
constexpr float PowerLsbW = 0.005f;
constexpr uint32_t I2cTimeoutMs = 10;
}

Ina226::Ina226(I2C_HandleTypeDef &i2c) : _i2c(i2c) {
}

bool Ina226::init() {
    uint16_t manufacturer = 0;
    _address = 0;
    for (uint8_t address = FirstAddress; address <= LastAddress; ++address) {
        _address = static_cast<uint16_t>(address) << 1;
        if (readRegister(ManufacturerIdRegister, manufacturer) &&
            manufacturer == ManufacturerId) {
            break;
        }
        _address = 0;
    }

    if (_address == 0) {
        return false;
    }

    return writeRegister(ConfigurationRegister, Configuration) &&
        writeRegister(CalibrationRegister, Calibration) &&
        writeRegister(AlertLimitRegister, AlertLimit) &&
        writeRegister(MaskEnableRegister, ShuntOvervoltageEnable);
}

bool Ina226::read(Ina226Readings &readings) {
    uint16_t busRaw = 0;
    uint16_t currentRaw = 0;
    uint16_t powerRaw = 0;
    if (!readRegister(BusVoltageRegister, busRaw) ||
        !readRegister(CurrentRegister, currentRaw) ||
        !readRegister(PowerRegister, powerRaw)) {
        return false;
    }

    readings.voltageV = static_cast<float>(busRaw) * BusVoltageLsbV * BusDividerRatio;
    readings.currentA = std::max(0.0f,
        static_cast<float>(static_cast<int16_t>(currentRaw)) * CurrentLsbA);
    readings.powerW = static_cast<float>(powerRaw) * PowerLsbW * BusDividerRatio;
    return true;
}

bool Ina226::writeRegister(uint8_t reg, uint16_t value) {
    uint8_t data[2] = {
        static_cast<uint8_t>(value >> 8),
        static_cast<uint8_t>(value & 0xffU),
    };
    return HAL_I2C_Mem_Write(&_i2c, _address, reg, I2C_MEMADD_SIZE_8BIT,
        data, sizeof(data), I2cTimeoutMs) == HAL_OK;
}

bool Ina226::readRegister(uint8_t reg, uint16_t &value) {
    uint8_t data[2] = {};
    if (HAL_I2C_Mem_Read(&_i2c, _address, reg, I2C_MEMADD_SIZE_8BIT,
            data, sizeof(data), I2cTimeoutMs) != HAL_OK) {
        return false;
    }
    value = static_cast<uint16_t>(data[0] << 8) | data[1];
    return true;
}

} // namespace ElectronicLoad::PHY
