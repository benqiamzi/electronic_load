/**
 * @file c_api.h
 * @brief C bridge between STM32Cube generated code and the C++ application.
 */

#pragma once

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/** Initializes the electronic-load application after all hardware peripherals. */
void electronicLoadInit(void);

/** Runs one non-blocking iteration of the application superloop. */
void electronicLoadRunOnce(void);

/**
 * Copies bytes received by USB CDC into the application receive queue.
 *
 * @param data Pointer to the received USB packet.
 * @param length Number of bytes in the packet.
 */
void electronicLoadUsbReceived(const uint8_t *data, uint32_t length);

/** Notifies the application that the active USB CDC transfer completed. */
void electronicLoadUsbTransmitComplete(void);

/** Handles the active-low INA226 alert from the GPIO interrupt callback. */
void electronicLoadInaAlert(void);

#ifdef __cplusplus
}
#endif
