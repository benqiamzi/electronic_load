#include "app.hpp"

#include "lib/app/c_api.h"

extern "C" {
#include "adc.h"
#include "i2c.h"
#include "main.h"
#include "spi.h"
#include "tim.h"
}

namespace ElectronicLoad::App {

Application::Application() :
    _dac(hspi3),
    _output(_dac, htim2, htim3),
    _ina226(hi2c1),
    _analogMonitor(hadc1),
    _controller(_output),
    _commandInterpreter(_controller, _ina226, _transport) {
}

void Application::init() {
    const uint32_t nowMs = HAL_GetTick();
    PHY::LoadOutput::emergencyDisableFromIsr();
    const bool outputReady = _output.init();
    const bool monitorReady = _ina226.init();
    _analogMonitor.init(nowMs);
    _lastIna226Ms = nowMs - Ina226PeriodMs;
    _controller.init(outputReady && monitorReady, nowMs);
    _initialized = true;
    if (HAL_GPIO_ReadPin(INA226_INT_GPIO_Port, INA226_INT_Pin) == GPIO_PIN_RESET) {
        _controller.notifyOverCurrentFromIsr();
    }
    updateStatusLed(nowMs);
}

void Application::runOnce() {
    if (!_initialized) {
        return;
    }

    const uint32_t nowMs = HAL_GetTick();
    _analogMonitor.run(nowMs);
    acquireMeasurements(nowMs);
    _controller.run(nowMs);
    _analogMonitor.setCurrentLimit(_controller.currentLimitA());
    _commandInterpreter.run(nowMs);
    _transport.run();
    updateStatusLed(nowMs);
}

void Application::usbReceivedFromIsr(const uint8_t *data, size_t length) {
    if (_initialized && data != nullptr) {
        _transport.receiveFromIsr(data, length);
    }
}

void Application::usbTransmitCompleteFromIsr() {
    if (_initialized) {
        _transport.transmitCompleteFromIsr();
    }
}

void Application::inaAlertFromIsr() {
    PHY::LoadOutput::emergencyDisableFromIsr();
    if (_initialized) {
        _controller.notifyOverCurrentFromIsr();
    }
}

void Application::currentLimitFromIsr() {
    PHY::LoadOutput::emergencyDisableFromIsr();
    if (_initialized) {
        _controller.notifyCurrentLimitFromIsr();
    }
}

void Application::acquireMeasurements(uint32_t nowMs) {
    if (static_cast<uint32_t>(nowMs - _lastIna226Ms) < Ina226PeriodMs) {
        return;
    }
    _lastIna226Ms = nowMs;
    _ina226Valid = _ina226.read(_ina226Readings);

    const PHY::AnalogReadings &analog = _analogMonitor.readings();
    Logic::Measurements measurements;
    // Host-visible voltage/current/power are sourced exclusively from INA226.
    // The fast ADC current channel remains an independent protection input.
    measurements.voltageV = _ina226Readings.voltageV;
    measurements.currentA = _ina226Readings.currentA;
    measurements.powerW = _ina226Readings.powerW;
    measurements.leftTemperatureC = analog.leftTemperatureC;
    measurements.rightTemperatureC = analog.rightTemperatureC;
    measurements.fastCurrentA = analog.fastCurrentA;
    measurements.timestampMs = nowMs;
    measurements.ina226Valid = _ina226Valid;
    measurements.fastCurrentValid = analog.fastCurrentValid;
    measurements.temperatureValid = analog.temperatureValid;
    // Temperature hardware is not populated on the current board revision.
    // INA226 and the installed INA240 fast-current channel remain required.
    measurements.valid = _ina226Valid && analog.fastCurrentValid;
    // Retain the last good sample across isolated I2C/ADC errors. The
    // controller's 100 ms freshness limit still trips a sustained failure.
    if (measurements.valid) {
        _controller.measurements(measurements);
    }
}

void Application::updateStatusLed(uint32_t nowMs) {
    bool ledOn = false;
    switch (_controller.state()) {
        case Logic::LoadState::Disabled:
            ledOn = false;
            break;
        case Logic::LoadState::Ramping:
        case Logic::LoadState::Enabled:
            ledOn = true;
            break;
        case Logic::LoadState::Fault:
            ledOn = ((nowMs / 200U) & 1U) != 0U;
            break;
    }
    HAL_GPIO_WritePin(STATUS_GPIO_Port, STATUS_Pin,
        ledOn ? GPIO_PIN_RESET : GPIO_PIN_SET);
}

} // namespace ElectronicLoad::App

namespace ElectronicLoad::App::Internal {

Application applicationInstance;

} // namespace ElectronicLoad::App::Internal

extern "C" void electronicLoadInit(void) {
    ElectronicLoad::App::Internal::applicationInstance.init();
}

extern "C" void electronicLoadRunOnce(void) {
    ElectronicLoad::App::Internal::applicationInstance.runOnce();
}

extern "C" void electronicLoadUsbReceived(const uint8_t *data, uint32_t length) {
    ElectronicLoad::App::Internal::applicationInstance.usbReceivedFromIsr(data, length);
}

extern "C" void electronicLoadUsbTransmitComplete(void) {
    ElectronicLoad::App::Internal::applicationInstance.usbTransmitCompleteFromIsr();
}

extern "C" void electronicLoadInaAlert(void) {
    ElectronicLoad::App::Internal::applicationInstance.inaAlertFromIsr();
}

extern "C" void electronicLoadCurrentLimit(void) {
    ElectronicLoad::App::Internal::applicationInstance.currentLimitFromIsr();
}

extern "C" void HAL_GPIO_EXTI_Callback(uint16_t gpioPin) {
    if (gpioPin == INA226_INT_Pin) {
        electronicLoadInaAlert();
    }
}

extern "C" void HAL_ADC_LevelOutOfWindowCallback(ADC_HandleTypeDef *adcHandle) {
    if (adcHandle == &hadc1) {
        electronicLoadCurrentLimit();
    }
}
