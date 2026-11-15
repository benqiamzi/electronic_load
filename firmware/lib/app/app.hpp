/**
 * @file app.hpp
 * @brief Top-level composition and cooperative scheduling for the electronic load.
 *
 * The application owns the hardware adapters, safety controller, USB transport,
 * and command interpreter. It is initialized only after CubeMX has configured the
 * peripherals and then runs as a non-blocking superloop on the main CPU context.
 */

#pragma once

#include <cstddef>
#include <cstdint>

#include "lib/logic/load_controller.hpp"
#include "lib/phy/analog_monitor.hpp"
#include "lib/phy/dac8552.hpp"
#include "lib/phy/ina226.hpp"
#include "lib/phy/load_output.hpp"
#include "lib/proto/command_interpreter.hpp"
#include "lib/transport/usb_cdc_transport.hpp"

namespace ElectronicLoad::App {

class Application {
public:
    Application();

    /** Initializes hardware adapters and leaves the load output disabled. */
    void init();

    /** Runs due acquisition, protection, control, command, and transport work. */
    void runOnce();

    /**
     * Queues a USB receive packet from the USB interrupt context.
     *
     * @param data Pointer to the received bytes.
     * @param length Number of received bytes.
     */
    void usbReceivedFromIsr(const uint8_t *data, size_t length);

    /** Marks the active USB transmission complete from interrupt context. */
    void usbTransmitCompleteFromIsr();

    /** Immediately disables the load after an INA226 alert interrupt. */
    void inaAlertFromIsr();

private:
    /** Updates the combined measurement snapshot when an INA226 sample is due. */
    void acquireMeasurements(uint32_t nowMs);

    /**
     * Drives the active-low status LED from the current load state.
     *
     * @param nowMs Current HAL millisecond tick.
     */
    void updateStatusLed(uint32_t nowMs);

    static constexpr uint32_t Ina226PeriodMs = 10;

    PHY::Dac8552 _dac;
    PHY::LoadOutput _output;
    PHY::Ina226 _ina226;
    PHY::AnalogMonitor _analogMonitor;
    Transport::UsbCdcTransport _transport;
    Logic::LoadController _controller;
    Proto::CommandInterpreter _commandInterpreter;
    PHY::Ina226Readings _ina226Readings;
    uint32_t _lastIna226Ms = 0;
    bool _ina226Valid = false;
    bool _initialized = false;
};

} // namespace ElectronicLoad::App
