#include "load_controller.hpp"

#include <algorithm>
#include <cmath>

#include "load_math.hpp"

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
        case LoadFault::MeasurementFailure: return "MEASUREMENT_FAILURE";
        case LoadFault::OutputFailure: return "OUTPUT_FAILURE";
    }
    return "UNKNOWN";
}

const char *loadChannelModeName(LoadChannelMode mode) {
    switch (mode) {
        case LoadChannelMode::A: return "A";
        case LoadChannelMode::B: return "B";
        case LoadChannelMode::Both: return "BOTH";
    }
    return "UNKNOWN";
}

const char *overCurrentSourceName(OverCurrentSource source) {
    switch (source) {
        case OverCurrentSource::None: return "NONE";
        case OverCurrentSource::Ina226Alert: return "INA226_ALERT";
        case OverCurrentSource::Ina226Measurement: return "INA226_MEAS";
        case OverCurrentSource::FastAdc: return "FAST_ADC";
    }
    return "UNKNOWN";
}

LoadController::LoadController(PHY::LoadOutput &output) : _output(output) {
}

void LoadController::init(bool hardwareReady, uint32_t nowMs) {
    _output.makeSafe();
    _hardwareReady = hardwareReady;
    _lastControlMs = nowMs;
    CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
    DWT->CYCCNT = 0;
    DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;
    _limitOffCycles = CurrentLimitOffTimeUs * (SystemCoreClock / 1000000U);
    if (!hardwareReady) {
        _state = LoadState::Fault;
        _fault = LoadFault::SensorFailure;
    }
}

void LoadController::run(uint32_t nowMs) {
    if (_overcurrentPending) {
        _overcurrentPending = false;
        latchOverCurrent(OverCurrentSource::Ina226Alert);
        trip(LoadFault::OverCurrent);
    }

    if (_currentLimitPending) {
        _currentLimitPending = false;
        if (input()) {
            _currentLimitActive = true;
            _limitStartCycles = DWT->CYCCNT;
            ++_limitEventCount;
        }
    }
    if (_currentLimitActive && input() &&
        static_cast<uint32_t>(DWT->CYCCNT - _limitStartCycles) >= _limitOffCycles) {
        _currentLimitActive = false;
        _output.enabled(true);
    }

    if (_state != LoadState::Ramping && _state != LoadState::Enabled) {
        _lastControlMs = nowMs;
        return;
    }

    if (!measurementFresh(nowMs)) {
        trip(LoadFault::MeasurementFailure);
        return;
    }
    const bool fastOvercurrent = FastCurrentProtectionEnabled &&
        _measurements.fastCurrentA > _protectionThresholds.currentA;
    if (_measurements.currentA > _protectionThresholds.currentA) {
        latchOverCurrent(OverCurrentSource::Ina226Measurement);
        trip(LoadFault::OverCurrent);
        return;
    }
    if (fastOvercurrent) {
        latchOverCurrent(OverCurrentSource::FastAdc);
        trip(LoadFault::OverCurrent);
        return;
    }
    if (_measurements.voltageV > _protectionThresholds.voltageV) {
        trip(LoadFault::OverVoltage);
        return;
    }
    if (_measurements.powerW > _protectionThresholds.powerW) {
        trip(LoadFault::OverPower);
        return;
    }
    if constexpr (TemperatureProtectionEnabled) {
        if (_measurements.leftTemperatureC >= _protectionThresholds.temperatureC ||
            _measurements.rightTemperatureC >= _protectionThresholds.temperatureC) {
            trip(LoadFault::OverTemperature);
            return;
        }
    }

    if (_dacManualMode) {
        _lastControlMs = nowMs;
        _state = LoadState::Enabled;
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

    // Software average-current loop was replaced by the hardware clamp: the
    // DAC carries the real setpoint again and the analog loop regulates.
    if (!_output.setCurrent(_appliedCurrentA, _channelMode)) {
        trip(LoadFault::OutputFailure);
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

void LoadController::notifyCurrentLimitFromIsr() {
    _currentLimitPending = true;
}

float LoadController::currentLimitA() const {
    return input() ? _currentLimitA : 0.0f;
}

uint32_t LoadController::currentLimitEvents() const {
    return _limitEventCount;
}

uint32_t LoadController::currentLimitOffTimeUs() const {
    return CurrentLimitOffTimeUs;
}

ControlResult LoadController::current(float amps) {
    if (!std::isfinite(amps) || amps < 0.0f || amps > MaximumCurrentA) {
        return ControlResult::failure("Current must be between 0 and 2.5 A");
    }
    if (amps > _protectionThresholds.currentA) {
        return ControlResult::failure("Requested current exceeds protection threshold");
    }
    if (input() && _measurements.valid &&
        amps * _measurements.voltageV > _protectionThresholds.powerW) {
        return ControlResult::failure("Requested operating point exceeds power protection threshold");
    }
    if (_dacManualMode) {
        if (!_output.setCurrent(0.0f, _channelMode)) {
            trip(LoadFault::OutputFailure);
            return ControlResult::failure("Unable to resume automatic DAC control");
        }
        _dacManualMode = false;
        _appliedCurrentA = 0.0f;
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

ControlResult LoadController::channelMode(LoadChannelMode mode) {
    if (_state != LoadState::Disabled) {
        return ControlResult::failure("Disable load before changing channel mode");
    }
    _output.makeSafe();
    _appliedCurrentA = 0.0f;
    _dacManualMode = false;
    _channelMode = mode;
    if (!_output.setCurrent(0.0f, _channelMode)) {
        trip(LoadFault::OutputFailure);
        return ControlResult::failure("Unable to initialize selected channel mode");
    }
    return ControlResult::ok();
}

LoadChannelMode LoadController::channelMode() const {
    return _channelMode;
}

ControlResult LoadController::fanDuty(float dutyPercent) {
    if (!std::isfinite(dutyPercent) || dutyPercent < 0.0f || dutyPercent > 100.0f) {
        return ControlResult::failure("Fan duty must be between 0 and 100 percent");
    }
    if (input() && dutyPercent < PHY::LoadOutput::MinimumActiveFanDutyPercent) {
        return ControlResult::failure("Fan duty must be at least 30 percent while load is enabled");
    }
    if (!_output.setFanDuty(dutyPercent)) {
        trip(LoadFault::OutputFailure);
        return ControlResult::failure("Unable to set fan duty");
    }
    return ControlResult::ok();
}

float LoadController::fanDuty() const {
    return _output.fanDuty();
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
    if (_output.fanDuty() < PHY::LoadOutput::MinimumActiveFanDutyPercent &&
        !_output.setFanDuty(PHY::LoadOutput::MinimumActiveFanDutyPercent)) {
        trip(LoadFault::OutputFailure);
        return ControlResult::failure("Unable to start cooling fan");
    }
    if (!_output.setCurrent(0.0f, _channelMode)) {
        trip(LoadFault::OutputFailure);
        return ControlResult::failure("Unable to initialize DAC output");
    }
    _appliedCurrentA = 0.0f;
    _dacManualMode = false;
    _overCurrentSource = OverCurrentSource::None;
    _overCurrentIna226A = 0.0f;
    _overCurrentFastA = 0.0f;
    _currentLimitA = CurrentLimitMaxA;
    _currentLimitActive = false;
    _currentLimitPending = false;
    _limitEventCount = 0;
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
    const float recoveryTemperature = std::min(
        TemperatureRecoveryC, _protectionThresholds.temperatureC - 5.0f);
    const bool temperatureUnsafe = TemperatureProtectionEnabled &&
        (_measurements.leftTemperatureC >= recoveryTemperature ||
         _measurements.rightTemperatureC >= recoveryTemperature);
    const float offCurrentLimit = std::min(0.2f, _protectionThresholds.currentA);
    const bool fastCurrentUnsafe = FastCurrentProtectionEnabled &&
        _measurements.fastCurrentA > offCurrentLimit;
    if (!measurementFresh(nowMs) || _measurements.currentA > offCurrentLimit ||
        fastCurrentUnsafe || _measurements.voltageV > _protectionThresholds.voltageV ||
        _measurements.powerW > _protectionThresholds.powerW || temperatureUnsafe) {
        return ControlResult::failure("Fault condition is still present");
    }
    _fault = LoadFault::None;
    _state = LoadState::Disabled;
    return ControlResult::ok();
}

ControlResult LoadController::setProtectionThresholds(const ProtectionThresholds &thresholds) {
    if (input()) {
        return ControlResult::failure("Disable load before changing protection thresholds");
    }
    if (!Math::protectionThresholdsValid(thresholds)) {
        return ControlResult::failure("Protection thresholds out of range");
    }
    if (!TemperatureProtectionEnabled &&
        thresholds.temperatureC != _protectionThresholds.temperatureC) {
        return ControlResult::failure("Temperature protection is unavailable on this board");
    }
    _protectionThresholds = thresholds;
    return ControlResult::ok();
}

const ProtectionThresholds &LoadController::protectionThresholds() const {
    return _protectionThresholds;
}

bool LoadController::temperatureProtectionEnabled() const {
    return TemperatureProtectionEnabled;
}

void LoadController::reset(uint32_t nowMs) {
    disable();
    _requestedCurrentA = 0.0f;
    _channelMode = LoadChannelMode::A;
    (void)_output.setCurrent(0.0f, _channelMode);
    (void)clearFault(nowMs);
}

ControlResult LoadController::diagnosticDac(float amps) {
    if (_state != LoadState::Disabled) {
        return ControlResult::failure("DAC diagnostic requires disabled state");
    }
    if (!std::isfinite(amps) || amps < 0.0f || amps > MaximumCurrentA) {
        return ControlResult::failure("DAC diagnostic value must be between 0 and 2.5 A");
    }

    _output.enabled(false);
    if (!_output.setCurrent(amps, _channelMode)) {
        trip(LoadFault::OutputFailure);
        return ControlResult::failure("Unable to write DAC diagnostic value");
    }
    return ControlResult::ok();
}

ControlResult LoadController::diagnosticDacZero() {
    if (_state == LoadState::Fault) {
        return ControlResult::failure("Clear the latched fault before DAC control");
    }
    if (!_output.setCurrent(0.0f, _channelMode)) {
        trip(LoadFault::OutputFailure);
        return ControlResult::failure("Unable to zero DAC outputs");
    }
    if (input()) {
        _dacManualMode = true;
        _requestedCurrentA = 0.0f;
        _appliedCurrentA = 0.0f;
        _state = LoadState::Enabled;
    } else {
        _output.enabled(false);
    }
    return ControlResult::ok();
}

ControlResult LoadController::diagnosticDacVoltage(uint8_t channel, float volts) {
    if (_state == LoadState::Fault) {
        return ControlResult::failure("Clear the latched fault before DAC control");
    }
    if (channel < 1U || channel > 2U) {
        return ControlResult::failure("DAC channel must be 1 or 2");
    }
    if (!std::isfinite(volts) || volts < 0.0f ||
        volts > Math::DacReferenceVoltage) {
        return ControlResult::failure("DAC voltage must be between 0 and 2.5 V");
    }

    const bool live = input();
    if (live) {
        if ((_channelMode == LoadChannelMode::A && channel != 1U) ||
            (_channelMode == LoadChannelMode::B && channel != 2U)) {
            return ControlResult::failure("DAC channel does not match selected load mode");
        }
        const float otherVoltage = _dacManualMode
            ? _output.dacVoltage(channel == 1U ? 2U : 1U) : 0.0f;
        if (volts + otherVoltage > MaximumLiveDacVoltageSum + 0.00001f) {
            return ControlResult::failure("Live DAC A+B total must not exceed 0.5 V");
        }
        const float estimatedCurrentA =
            (volts + otherVoltage) / Math::DacVoltsPerChannelAmp;
        if (estimatedCurrentA > _protectionThresholds.currentA) {
            return ControlResult::failure("Live DAC setpoint exceeds current protection threshold");
        }
        if (_measurements.valid &&
            estimatedCurrentA * _measurements.voltageV > _protectionThresholds.powerW) {
            return ControlResult::failure("Live DAC setpoint exceeds power protection threshold");
        }
        if (!_dacManualMode && !_output.setCurrent(0.0f, _channelMode)) {
            trip(LoadFault::OutputFailure);
            return ControlResult::failure("Unable to enter manual DAC control");
        }
    } else {
        _output.enabled(false);
    }
    if (!_output.setDacVoltage(channel, volts)) {
        trip(LoadFault::OutputFailure);
        return ControlResult::failure("Unable to write DAC diagnostic voltage");
    }
    if (live) {
        _dacManualMode = true;
        _requestedCurrentA = 0.0f;
        _appliedCurrentA = 0.0f;
        _state = LoadState::Enabled;
    }
    return ControlResult::ok();
}

float LoadController::dacVoltage(uint8_t channel) const {
    return _output.dacVoltage(channel);
}

bool LoadController::dacManualMode() const {
    return _dacManualMode;
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

OverCurrentSource LoadController::overCurrentSource() const {
    return _overCurrentSource;
}

float LoadController::overCurrentIna226A() const {
    return _overCurrentIna226A;
}

float LoadController::overCurrentFastA() const {
    return _overCurrentFastA;
}

bool LoadController::measurementFresh(uint32_t nowMs) const {
    return _measurements.valid &&
        (!TemperatureProtectionEnabled || _measurements.temperatureValid) &&
        static_cast<uint32_t>(nowMs - _measurements.timestampMs) <= MeasurementTimeoutMs;
}

bool LoadController::conditionsSafeForEnable(float requestedCurrent, uint32_t nowMs) const {
    const bool temperatureSafe = !TemperatureProtectionEnabled ||
        (_measurements.leftTemperatureC < _protectionThresholds.temperatureC &&
         _measurements.rightTemperatureC < _protectionThresholds.temperatureC);
    const float offCurrentLimit = std::min(0.2f, _protectionThresholds.currentA);
    const bool fastCurrentSafe = !FastCurrentProtectionEnabled ||
        _measurements.fastCurrentA <= offCurrentLimit;
    return _hardwareReady && measurementFresh(nowMs) &&
        _measurements.currentA <= offCurrentLimit && fastCurrentSafe &&
        _measurements.voltageV <= _protectionThresholds.voltageV &&
        _measurements.powerW <= _protectionThresholds.powerW &&
        requestedCurrent <= _protectionThresholds.currentA &&
        requestedCurrent * _measurements.voltageV <= _protectionThresholds.powerW &&
        temperatureSafe;
}

void LoadController::trip(LoadFault newFault) {
    _output.makeSafe();
    _dacManualMode = false;
    (void)_output.setFanDuty(100.0f);
    _appliedCurrentA = 0.0f;
    _currentLimitA = 0.0f;
    _currentLimitActive = false;
    _currentLimitPending = false;
    _fault = newFault;
    _state = LoadState::Fault;
}

void LoadController::latchOverCurrent(OverCurrentSource source) {
    _overCurrentSource = source;
    _overCurrentIna226A = _measurements.currentA;
    _overCurrentFastA = _measurements.fastCurrentA;
}

void LoadController::disable() {
    _output.makeSafe();
    _dacManualMode = false;
    _appliedCurrentA = 0.0f;
    _currentLimitA = 0.0f;
    _currentLimitActive = false;
    _currentLimitPending = false;
    if (_state != LoadState::Fault) {
        _state = LoadState::Disabled;
        _fault = LoadFault::None;
    }
}

} // namespace ElectronicLoad::Logic
