#include "usb_cdc_transport.hpp"

#include <algorithm>
#include <cstring>

extern "C" {
#include "usbd_cdc_if.h"
}

namespace ElectronicLoad::Transport {

void UsbCdcTransport::receiveFromIsr(const uint8_t *data, size_t length) {
    for (size_t index = 0; index < length; ++index) {
        const uint16_t next = static_cast<uint16_t>((_rxHead + 1U) % RxSize);
        if (next == _rxTail) {
            _rxOverflow = true;
            return;
        }
        _rx[_rxHead] = data[index];
        _rxHead = next;
    }
}

void UsbCdcTransport::transmitCompleteFromIsr() {
    _txComplete = true;
}

bool UsbCdcTransport::pop(uint8_t &value) {
    if (_rxTail == _rxHead) {
        return false;
    }
    value = _rx[_rxTail];
    _rxTail = static_cast<uint16_t>((_rxTail + 1U) % RxSize);
    return true;
}

bool UsbCdcTransport::send(const char *text) {
    if (text == nullptr || _txCount >= TxDepth) {
        return false;
    }
    const size_t length = std::min(std::strlen(text), TxSize - 1U);
    TxEntry &entry = _tx[_txHead];
    std::memcpy(entry.data.data(), text, length);
    entry.length = static_cast<uint16_t>(length);
    _txHead = static_cast<uint8_t>((_txHead + 1U) % TxDepth);
    ++_txCount;
    return true;
}

void UsbCdcTransport::run() {
    if (_txComplete) {
        _txComplete = false;
        if (_txActive && _txCount > 0) {
            _txTail = static_cast<uint8_t>((_txTail + 1U) % TxDepth);
            --_txCount;
        }
        _txActive = false;
    }

    if (_txActive || _txCount == 0) {
        return;
    }

    TxEntry &entry = _tx[_txTail];
    if (CDC_Transmit_FS(entry.data.data(), entry.length) == USBD_OK) {
        _txActive = true;
    }
}

bool UsbCdcTransport::consumeRxOverflow() {
    const bool overflow = _rxOverflow;
    _rxOverflow = false;
    return overflow;
}

} // namespace ElectronicLoad::Transport
