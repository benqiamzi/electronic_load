# A-loop startup comparison in LTspice

These netlists are copies of `E:\LTspice\高精度恒流源电路.net` with controlled
startup changes. The original file is untouched. They retain its AD8552 op-amp
model, one IRFP250N, and 15 V input source, so their current peaks are **not**
predictions for the reworked GS8552 board. The board's A-loop feedback capacitor
is C9; the corresponding capacitor in these netlists is **C4** (`Vi-` to
`U1_OUT`). Netlist C3 is a 250 pF gate-to-source capacitor.

## Run

Open each `.net` file in LTspice and run the transient analysis. Open the SPICE
error log (`Ctrl+L`) to see the `.meas` results. Add traces `V(U1_OUT)`, `V(Vg)`,
and `I(R4)` to compare waveforms. The files use the original machine's LTspice
library paths, including `ADI.lib`.

| File | Changed condition |
| --- | --- |
| `a_loop_zero_initial.net` | Rails are on; U1 output starts at 0 V; TC_EN rises at 100 us. |
| `a_loop_precharged_4v79.net` | Same circuit and timing, but `.ic V(U1_OUT)=4.79 V(Vi-)=0`. |
| `a_loop_precharged_reset.net` | Same 4.79 V initial condition; the previously floating M4 is connected across C4 through 100 ohms. |
| `a_loop_long_off_50ms.net` | Original `startup` mode with TC_EN delayed to 50 ms and setpoint delayed to 50.1 ms. |

These files ran successfully in LTspice 26.0.1 on 2026-11-23:

| Case | U1_OUT before enable | Peak current from enable until setpoint begins | Full-window peak | Current near end |
| --- | ---: | ---: | ---: | ---: |
| Zero initial condition | 0.00012 V at 99 us | 0.000055 A, 100-200 us | 0.716 A | 0.500 A |
| 4.79 V initial condition | 4.347 V at 99 us | 0.801 A, 100-200 us | 0.801 A | 0.500 A |
| 4.79 V initial condition, reset switch | 0.00090 V at 99 us | 0.000013 A, 100-200 us | 0.716 A | 0.500 A |
| 50 ms off, no reset | 0.00827 V at 49.9 ms | Not separately measured | 0.736 A | 0.501 A |

The initial-condition pair differs only in the `.ic` line, so it isolates the
effect of the measured precharge. The `.ic` constraint is a **stress test**: it
imposes the real board's measured state on the AD8552 model. It does not claim
that this model would develop that state by itself. In fact, the 50 ms off test
remains low. The reset case shows that the switched path removes the early pulse
in this model; it does not eliminate the later approximately 0.716 A overshoot.

## Important differences from the real board

- The installed A-loop op-amp is GS8552 at approximately 5.11 V, while these
  files use an AD8552 macro model at 5 V.
- The real A-loop has two IRFP250N devices, gate diodes and 47 kohm gate-source
  resistors; these files retain the source netlist's single-device drive.
- The current board ran firmware 0.3.4 during debugging. That version holds the
  DAC at zero while enabled; the simulated setpoint rises toward 0.5 A.
- The original `.meas` line covered only 1.8-2 ms, before the later current
  peak. These copies measure from enable through the complete transient.

To obtain a quantitative board prediction, update the op-amp and power-stage
models, the input supply and current limit, and the firmware DAC waveform.
Then compare both the pre-enable `U1_OUT` voltage and current peak over the
entire enable event. A model that does not reach the measured 4.79 V idle state
cannot validate that failure mode.

The source netlist was edited during this investigation and briefly contained
`.tran ... startup uic V(C3)=4.79`, which LTspice rejected. `C3` is not a node,
and that capacitor is not the feedback capacitor. The working precharge test
uses `.ic V(U1_OUT)=4.79 V(Vi-)=0` with `.tran` and no `startup` or `uic`.
