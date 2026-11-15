#include "load_controller.hpp"

#include <algorithm>
#include <cmath>

namespace ElectronicLoad::Logic {

const char *loadStateName(LoadState state) {
    switch (state) {
        case LoadState::Disabled: return "DISABLED";
        case LoadState::Ramping: return "RAMPING";
        case LoadState::Enabled: return "ENABLED";
        case LoadState::Fault: return "FAULT";
    }
    return "UNKNOWN";
}

const char *loadFaultName(LoadFault fault) {
    switch (fault) {
        case LoadFault::None: return "NONE";
        case LoadFault::OverCurrent: return "OVER_CURRENT";
        case LoadFault::OverVoltage: return "OVER_VOLTAGE";
        case LoadFault::OverPower: return "OVER_POWER";
        case LoadFault::OverTemperature: return "OVER_TEMPERATURE";
        case LoadFault::SensorFailure: return "SENSOR_FAILURE";
    }
    return "UNKNOWN";
}

LoadController::LoadController(PHY::LoadOutput &output) : _output(output) {
}

void LoadController::init(bool hardwareReady, uint32_t nowMs) {
    _output.makeSafe();
    _hardwareReady = hardwareReady;
    _lastControlMs = nowMs;
    if (!hardwareReady) {
        _state = LoadState::Fault;
        _fault = LoadFault::SensorFailure;
    }
}

void LoadController::run(uint32_t nowMs) {
    if (_overcurrentPending) {
        _overcurrentPending = false;
        trip(LoadFault::OverCurrent);
    }

    if (_state != LoadState::Ramping && _state != LoadState::Enabled) {
        _lastControlMs = nowMs;
        return;
    }

    if (!measurementFresh(nowMs)) {
        trip(LoadFault::SensorFailure);
        return;
    }
    if (_measurements.currentA > OvercurrentThresholdA ||
        _measurements.fastCurrentA > OvercurrentThresholdA) {
        trip(LoadFault::OverCurrent);
        return;
    }
    if (_measurements.voltageV > MaximumVoltageV) {
        trip(LoadFault::OverVoltage);
        return;
    }
    if (_measurements.powerW > MaximumPowerW) {
        trip(LoadFault::OverPower);
        return;
    }
    if (_measurements.leftTemperatureC >= MaximumTemperatureC ||
        _measurements.rightTemperatureC >= MaximumTemperatureC) {
        trip(LoadFault::OverTemperature);
        return;
    }

    uint32_t elapsedMs = static_cast<uint32_t>(nowMs - _lastControlMs);
    _lastControlMs = nowMs;
    elapsedMs = std::min<uint32_t>(elapsedMs, 100);
    const float maximumStep = static_cast<float>(elapsedMs) * RampAmpsPerMillisecond;

    if (_appliedCurrentA < _requestedCurrentA) {
        _appliedCurrentA = std::min(_requestedCurrentA, _appliedCurrentA + maximumStep);
    } else if (_appliedCurrentA > _requestedCurrentA) {
        _appliedCurrentA = std::max(_requestedCurrentA, _appliedCurrentA - maximumStep);
    }

    if (!_output.setCurrent(_appliedCurrentA)) {
        trip(LoadFault::SensorFailure);
        return;
    }

    _state = std::fabs(_appliedCurrentA - _requestedCurrentA) < 0.0005f
        ? LoadState::Enabled : LoadState::Ramping;
}

void LoadController::measurements(const Measurements &newMeasurements) {
    _measurements = newMeasurements;
}

void LoadController::notifyOverCurrentFromIsr() {
    _overcurrentPending = true;
}

ControlResult LoadController::current(float amps) {
    if (!std::isfinite(amps) || amps < 0.0f || amps > MaximumCurrentA) {
        return ControlResult::failure("Current must be between 0 and 5 A");
    }
    if (input() && _measurements.valid && amps * _measurements.voltageV > MaximumPowerW) {
        return ControlResult::failure("Requested operating point exceeds 50 W");
    }
    _requestedCurrentA = amps;
    if (input()) {
        _state = LoadState::Ramping;
    }
    return ControlResult::ok();
}

float LoadController::current() const {
    return _requestedCurrentA;
}

ControlResult LoadController::input(bool enabledValue, uint32_t nowMs) {
    if (!enabledValue) {
        disable();
        return ControlResult::ok();
    }
    if (_state == LoadState::Fault) {
        return ControlResult::failure("A latched fault must be cleared first");
    }
    if (!conditionsSafeForEnable(_requestedCurrentA, nowMs)) {
        return ControlResult::failure("Measurements or operating point are not safe");
    }
    if (!_output.setCurrent(0.0f)) {
        trip(LoadFault::SensorFailure);
        return ControlResult::failure("Unable to initialize DAC output");
    }
    _appliedCurrentA = 0.0f;
    _lastControlMs = nowMs;
    _output.enabled(true);
    _state = LoadState::Ramping;
    return ControlResult::ok();
}

bool LoadController::input() const {
    return _state == LoadState::Ramping || _state == LoadState::Enabled;
}

ControlResult LoadController::clearFault(uint32_t nowMs) {
    if (_state != LoadState::Fault) {
        return ControlResult::ok();
    }
    if (!_hardwareReady) {
        return ControlResult::failure("Hardware initialization failed; restart required");
    }
    if (!measurementFresh(nowMs) || _measurements.currentA > 0.2f ||
        _measurements.fastCurrentA > 0.2f || _measurements.voltageV > MaximumVoltageV ||
        _measurements.powerW > MaximumPowerW ||
        _measurements.leftTemperatureC >= TemperatureRecoveryC ||
        _measurements.rightTemperatureC >= TemperatureRecoveryC) {
        return ControlResult::failure("Fault condition is still present");
    }
    _fault = LoadFault::None;
    _state = LoadState::Disabled;
    return ControlResult::ok();
}

void LoadController::reset(uint32_t nowMs) {
    disable();
    _requestedCurrentA = 0.0f;
    (void)clearFault(nowMs);
}

LoadState LoadController::state() const {
    return _state;
}

LoadFault LoadController::fault() const {
    return _fault;
}

const Measurements &LoadController::measurements() const {
    return _measurements;
}

bool LoadController::measurementFresh(uint32_t nowMs) const {
    return _measurements.valid &&
        static_cast<uint32_t>(nowMs - _measurements.timestampMs) <= MeasurementTimeoutMs;
}

bool LoadController::conditionsSafeForEnable(float requestedCurrent, uint32_t nowMs) const {
    return _hardwareReady && measurementFresh(nowMs) &&
        _measurements.currentA <= 0.2f && _measurements.fastCurrentA <= 0.2f &&
        _measurements.voltageV <= MaximumVoltageV &&
        requestedCurrent * _measurements.voltageV <= MaximumPowerW &&
        _measurements.leftTemperatureC < MaximumTemperatureC &&
        _measurements.rightTemperatureC < MaximumTemperatureC;
}

void LoadController::trip(LoadFault newFault) {
    _output.makeSafe();
    _appliedCurrentA = 0.0f;
    _fault = newFault;
    _state = LoadState::Fault;
}

void LoadController::disable() {
    _output.makeSafe();
    _appliedCurrentA = 0.0f;
    if (_state != LoadState::Fault) {
        _state = LoadState::Disabled;
        _fault = LoadFault::None;
    }
}

} // namespace ElectronicLoad::Logic
