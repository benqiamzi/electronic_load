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

This source tree (0.3.7) retains the **linear DAC current loop**; the previously
flashed 0.3.4 firmware holds the DAC at zero while enabled. Check `*IDN?` before
testing the analog loop. On the reworked A channel, U17.1 drives approximately
4.79 V with the input disabled and DACA at zero. Temporarily shorting its
feedback capacitor C9 (100 nF) brought VGA to zero; removing the short restored
the high output. A controlled integrator reset across C9 is required during
input-off intervals. The fast-current ADC analog watchdog remains
as a last-resort safety cut at 2.6 A (5 us off-time), below the INA226 and
fast-current default software trip points of 2.75 A.

Software protection defaults to 30 V, 2.75 A, 50 W, and 80 °C. The firmware
accepts thresholds of 0.01–30 V, 0.01–2.75 A, 0.01–50 W, and 30–80 °C
while input is off. The temperature field stays at its default when temperature
protection is disabled. All faults latch and immediately disable `TC_EN`.
The INA226 alert also disables it directly from the EXTI ISR.

> **Hardware prerequisite:** fit and validate the A-channel integrator reset
> before enabling the load. The reset must engage when the actual input-switch
> command U16.Y is low (`COMPOUT` AND `TC_EN`), and release when U16.Y is high.
> A permanent short across C9 would disable the current-control integrator.
> The reworked C9 is 100 nF, so limit its discharge current in the switched
> reset path. Verify the B-channel component designators and reset separately.

> **ADC configuration is hand-edited:** `adc.c` now runs ADC1 in continuous scan
> with DMA2 Stream0 and the fast-current analog watchdog. Re-generating from
> `electronic_load.ioc` would overwrite these settings; re-apply them or update
> the .ioc before regenerating.

> **Temporary board configuration:** the analog multiplexer and thermistors are
> not populated, so temperature validity and over-temperature protection are
> disabled by `TemperatureProtectionEnabled` in `load_controller.hpp`. Restore
> it to `true` after installing and validating the temperature-sensing hardware.
> The INA240 fast-current monitor is populated and its protection remains
> enabled by `FastCurrentProtectionEnabled`.
> Both power channels are populated. The selected output mode can be A, B, or
> BOTH. `SOUR:CURR` always means total load current; BOTH mode divides that
> current equally between A and B so a mode change cannot double the total
> current. Mode changes are accepted only while the load is disabled.

## USB CDC commands

Commands are ASCII and terminated with CR or LF. Short and long forms are
accepted where shown.

| Command | Description |
| --- | --- |
| `*IDN?` | Read device identification. |
| `*RST` | Disable the load and reset the requested current to zero. Protection thresholds persist across this command. |
| `SOUR:CURR <A>` / `SOURCE:CURRENT <A>` | Set requested CC current. |
| `SOUR:CURR?` | Read requested current. |
| `SOUR:CHAN A|B|BOTH` | Select A, B, or both power loops; load must be disabled. |
| `SOUR:CHAN?` | Read the selected power-loop mode. |
| `FAN:DUTY <percent>` | Set fan PWM duty from 0–100%. Below 30% is rejected while enabled. |
| `FAN:DUTY?` | Read fan PWM duty. |
| `INP ON` / `INP OFF` | Enable or disable the load input. |
| `INP?` | Read input state. |
| `MEAS:VOLT?`, `MEAS:CURR?`, `MEAS:POW?` | Read INA226 measurements. |
| `MEAS:TEMP?` | Read left and right heatsink temperatures. |
| `MEAS:ALL?` | Read voltage, current, power, and both temperatures. |
| `STAT?` | Read state, latched fault, and requested current. |
| `SYST:FAULT:CLEAR` | Clear a fault after the measured condition is safe. |
| `SYST:PROT?` | Read `V,A,W,degC,temperature_enabled`. The final field is 0 or 1. |
| `SYST:PROT <V>,<A>,<W>,<degC>` | Set all software protection thresholds together while the input is off. |
| `SYST:PROT:DEF` | Restore firmware defaults while the input is off. |
| `SYST:ERR?` | Pop the oldest command error. |
| `DIAG:DAC <A>` | Write both DAC channels while keeping `TC_EN` disabled. |
| `DIAG:DAC:ZERO` | Set both DAC channels to zero; while enabled, keep the load in manual DAC mode. |
| `DIAG:DAC:VOLT?` | Read the last successfully written channel 1 and 2 DAC voltages. |
| `DIAG:DAC:MODE?` | Read `AUTO` or `MANUAL` DAC control mode. |
| `DIAG:DAC:VOLT <channel>,<V>` | Set a DAC output directly. With input OFF: 0–2.5 V. With input ON: only the selected output channel(s), with A+B total no more than 0.5 V. |
| `DIAG:MEAS?` | Read combined/INA226/fast-current/temperature validity, fast current, and sample age. |
| `DIAG:OC?` | Read the latched over-current source and the INA226/fast-current samples captured at the trip. |
| `DIAG:LIM?` | Read the watchdog threshold, off-time, and the cycle-by-cycle limit event count. |
| `DIAG:INA?` | Read INA226 configuration, raw shunt, calibration, mask/status, and alert-limit registers. Reading it also clears a latched INA226 alert. |

The protection write and restore commands reply with the active settings in
the same format as `SYST:PROT?`, or with `ERROR,<message>` on rejection.
These commands leave latched faults in place. Thresholds are stored in RAM
and return to defaults when the MCU reboots.

Transient INA226/ADC read errors retain the last valid measurement. A sustained
measurement outage longer than 100 ms latches `MEASUREMENT_FAILURE`; DAC/SPI
write failures latch `OUTPUT_FAILURE`, while initialization failures retain the
`SENSOR_FAILURE` name.

For first power-up, use a current-limited bench supply and no high-power input.
Confirm PB9 stays low, PA15 idles high, PB10 is approximately 37.9% duty, and
both DAC channels remain at zero. Then verify measurements before trying a small
setpoint such as `SOUR:CURR 0.05` followed by `INP ON`. With the gate clamp
fitted, the DAC carries the real setpoint; `DIAG:DAC:VOLT?` should read
0.2 V/A x setpoint (0.070 V at 0.35 A) once the load is enabled.

For a DAC communication check with the power stage disabled, send `DIAG:DAC 1`.
Both DAC outputs should measure approximately 0.100 V. Send `DIAG:DAC:ZERO`
after the measurement and confirm that both outputs return to approximately 0 V.

`DIAG:DAC:VOLT?` reports the commanded DAC values tracked by the firmware. The
DAC8552 has no output readback ADC, so these values are not physical voltage
measurements. A live single-channel write first zeroes both outputs, then enters
manual DAC mode. Subsequent writes persist until `SOUR:CURR` resumes automatic
control from zero, or `INP OFF` disables and zeroes the load. The existing
INA226/ADC current protection and fault shutdown remain active in manual mode.

The fan starts at 100%. If the operator configured less than 30% while disabled,
enabling the load first raises it to 30%. Fault trips force the fan to 100%.
