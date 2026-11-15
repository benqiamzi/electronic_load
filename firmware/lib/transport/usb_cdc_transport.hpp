/**
 * @file usb_cdc_transport.hpp
 * @brief Interrupt-safe fixed-buffer transport for the STM32 USB CDC class.
 */

#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

namespace ElectronicLoad::Transport {

class UsbCdcTransport {
public:
    void receiveFromIsr(const uint8_t *data, size_t length);
    void transmitCompleteFromIsr();
    bool pop(uint8_t &value);
    bool send(const char *text);
    void run();
    bool consumeRxOverflow();

private:
    static constexpr size_t RxSize = 512;
    static constexpr size_t TxDepth = 4;
    static constexpr size_t TxSize = 192;

    struct TxEntry {
        std::array<uint8_t, TxSize> data{};
        uint16_t length = 0;
    };

    std::array<uint8_t, RxSize> _rx{};
    volatile uint16_t _rxHead = 0;
    volatile uint16_t _rxTail = 0;
    volatile bool _rxOverflow = false;

    std::array<TxEntry, TxDepth> _tx{};
    uint8_t _txHead = 0;
    uint8_t _txTail = 0;
    uint8_t _txCount = 0;
    bool _txActive = false;
    volatile bool _txComplete = false;
};

} // namespace ElectronicLoad::Transport
