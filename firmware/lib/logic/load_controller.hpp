/**
 * @file load_controller.hpp
 * @brief Constant-current load policy, ramping, limits, and latched faults.
 */

#pragma once

#include <cstdint>

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

    ControlResult current(float amps);
    float current() const;
    ControlResult input(bool enabled, uint32_t nowMs);
    bool input() const;
    ControlResult clearFault(uint32_t nowMs);
    void reset(uint32_t nowMs);

    LoadState state() const;
    LoadFault fault() const;
    const Measurements &measurements() const;

private:
    bool measurementFresh(uint32_t nowMs) const;
    bool conditionsSafeForEnable(float requestedCurrent, uint32_t nowMs) const;
    void trip(LoadFault fault);
    void disable();

    static constexpr float MaximumCurrentA = 5.0f;
    static constexpr float OvercurrentThresholdA = 5.25f;
    static constexpr float MaximumVoltageV = 30.0f;
    static constexpr float MaximumPowerW = 50.0f;
    static constexpr float MaximumTemperatureC = 80.0f;
    static constexpr float TemperatureRecoveryC = 70.0f;
    static constexpr float RampAmpsPerMillisecond = 0.001f;
    static constexpr uint32_t MeasurementTimeoutMs = 100;

    PHY::LoadOutput &_output;
    Measurements _measurements;
    LoadState _state = LoadState::Disabled;
    LoadFault _fault = LoadFault::None;
    float _requestedCurrentA = 0.0f;
    float _appliedCurrentA = 0.0f;
    uint32_t _lastControlMs = 0;
    volatile bool _overcurrentPending = false;
    bool _hardwareReady = false;
};

} // namespace ElectronicLoad::Logic
