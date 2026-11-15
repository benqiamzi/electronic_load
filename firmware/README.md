# STM32F411 electronic load firmware

This firmware provides an initial constant-current control and USB CDC command
interface for the electronic-load PCB. It uses a layered C++20 superloop while
keeping STM32Cube-generated startup and HAL code in C.

## Implemented hardware

- DAC8552 setpoint output on SPI3: PC10/SCK, PC12/MOSI, PA15/SYNC.
- 1.25 V filtered reference PWM on PB10/TIM2_CH3.
- INA226 voltage/current/power monitor on I2C1 with PB5 alert shutdown.
- Fast analog current feedback on PA4 and two multiplexed thermistors on PA5.
- Load enable on PB9, fan PWM on PC8/TIM3_CH3, and active-low status LED on PC13.
- USB FS CDC command transport.

The current firmware supports CC mode from 0 A to 5 A. Software protection is
set to 30 V, 50 W, 5.25 A, and 80 degC. All faults are latched and immediately
disable `TC_EN`; the INA226 alert also disables it directly from the EXTI ISR.

## USB CDC commands

Commands are ASCII and terminated with CR or LF. Short and long forms are
accepted where shown.

| Command | Description |
| --- | --- |
| `*IDN?` | Read device identification. |
| `*RST` | Disable the load and reset the requested current to zero. |
| `SOUR:CURR <A>` / `SOURCE:CURRENT <A>` | Set requested CC current. |
| `SOUR:CURR?` | Read requested current. |
| `INP ON` / `INP OFF` | Enable or disable the load input. |
| `INP?` | Read input state. |
| `MEAS:VOLT?`, `MEAS:CURR?`, `MEAS:POW?` | Read INA226 measurements. |
| `MEAS:TEMP?` | Read left and right heatsink temperatures. |
| `MEAS:ALL?` | Read voltage, current, power, and both temperatures. |
| `STAT?` | Read state, latched fault, and requested current. |
| `SYST:FAULT:CLEAR` | Clear a fault after the measured condition is safe. |
| `SYST:ERR?` | Pop the oldest command error. |

For first power-up, use a current-limited bench supply and no high-power input.
Confirm PB9 stays low, PA15 idles high, PB10 is approximately 37.9% duty, and
both DAC channels remain at zero. Then verify measurements before trying a small
setpoint such as `SOUR:CURR 0.05` followed by `INP ON`.
