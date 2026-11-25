/**
 * @file load_controller.hpp
 * @brief Constant-current load policy, ramping, limits, and latched faults.
 */

#pragma once

#include <cstdint>

#include "load_math.hpp"
#include "load_types.hpp"
#include "lib/phy/load_output.hpp"

namespace ElectronicLoad::Logic {

class LoadController {
public:
    explicit LoadController(PHY::LoadOutput &output);

    void init(bool hardwareReady, uint32_t nowMs);
    void run(uint32_t nowMs);
    void measurements(const Measurements &measurements);
    void notifyOverCurrentFromIsr();

    /**
     * @brief Reports a fast-current limit event from the ADC watchdog ISR.
     *
     * The ISR has already cut TC_EN; the control loop re-arms it after the
     * fixed off-time, producing cycle-by-cycle current limiting.
     */
    void notifyCurrentLimitFromIsr();
    float currentLimitA() const;
    uint32_t currentLimitEvents() const;
    uint32_t currentLimitOffTimeUs() const;

    ControlResult current(float amps);
    float current() const;
    ControlResult channelMode(LoadChannelMode mode);
    LoadChannelMode channelMode() const;
    ControlResult fanDuty(float dutyPercent);
    float fanDuty() const;
    ControlResult input(bool enabled, uint32_t nowMs);
    bool input() const;
    ControlResult clearFault(uint32_t nowMs);
    ControlResult setProtectionThresholds(const ProtectionThresholds &thresholds);
    const ProtectionThresholds &protectionThresholds() const;
    bool temperatureProtectionEnabled() const;
    void reset(uint32_t nowMs);

    /**
     * @brief Write a diagnostic DAC setpoint while keeping the load switch disabled.
     * @param amps Equivalent total-current setpoint used for DAC conversion.
     * @return Success when the setpoint was accepted and transmitted to the DAC.
     */
    ControlResult diagnosticDac(float amps);
    ControlResult diagnosticDacZero();
    ControlResult diagnosticDacVoltage(uint8_t channel, float volts);
    float dacVoltage(uint8_t channel) const;
    bool dacManualMode() const;

    LoadState state() const;
    LoadFault fault() const;
    const Measurements &measurements() const;
    OverCurrentSource overCurrentSource() const;
    float overCurrentIna226A() const;
    float overCurrentFastA() const;

private:
    bool measurementFresh(uint32_t nowMs) const;
    bool conditionsSafeForEnable(float requestedCurrent, uint32_t nowMs) const;
    void trip(LoadFault fault);
    void latchOverCurrent(OverCurrentSource source);
    void disable();

    static constexpr float MaximumCurrentA = 2.5f;
    // INA240 fast-current monitoring is populated and participates in safety.
    static constexpr bool FastCurrentProtectionEnabled = true;
    // Temporary board configuration: the temperature mux and thermistors are
    // not populated. Set this back to true after that hardware is installed.
    static constexpr bool TemperatureProtectionEnabled = false;
    static constexpr float TemperatureRecoveryC = 70.0f;
    static constexpr float RampAmpsPerMillisecond = 0.001f;
    static constexpr uint32_t MeasurementTimeoutMs = 100;

    // Fast-current analog watchdog used as a last-resort safety cut.  With the
    // hardware gate clamp fitted, the linear DAC loop handles normal
    // regulation; the watchdog only fires on a genuine over-current transient.
    static constexpr uint32_t CurrentLimitOffTimeUs = 5;
    static constexpr float CurrentLimitMaxA = 2.6f;
    static constexpr float MaximumLiveDacVoltageSum =
        MaximumCurrentA * Math::DacVoltsPerChannelAmp;

    PHY::LoadOutput &_output;
    Measurements _measurements;
    ProtectionThresholds _protectionThresholds;
    LoadState _state = LoadState::Disabled;
    LoadFault _fault = LoadFault::None;
    float _requestedCurrentA = 0.0f;
    float _appliedCurrentA = 0.0f;
    bool _dacManualMode = false;
    LoadChannelMode _channelMode = LoadChannelMode::A;
    uint32_t _lastControlMs = 0;
    volatile bool _overcurrentPending = false;
    OverCurrentSource _overCurrentSource = OverCurrentSource::None;
    float _overCurrentIna226A = 0.0f;
    float _overCurrentFastA = 0.0f;
    bool _hardwareReady = false;

    volatile bool _currentLimitPending = false;
    bool _currentLimitActive = false;
    uint32_t _limitStartCycles = 0;
    uint32_t _limitOffCycles = 0;
    float _currentLimitA = 0.0f;
    uint32_t _limitEventCount = 0;
};

} // namespace ElectronicLoad::Logic
