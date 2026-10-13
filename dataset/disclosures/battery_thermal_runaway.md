# Early Detection of Battery Thermal Runaway Using Impedance and Gas Sensing

Synthetic sample disclosure for demonstration. Not a real invention.

- Technical field: Lithium-ion battery safety
- Priority date: 2018-04-12
- Jurisdiction: US

## Problem

Thermal runaway in lithium-ion packs is usually detected only after cell temperature has risen sharply, which leaves too little time to isolate the pack.

## Solution

A battery management unit measures cell impedance at several frequencies and reads a gas sensor that detects electrolyte vapour inside the pack housing. A classifier combines impedance drift and gas concentration trends to raise an early warning minutes before temperature rises, and the unit opens a contactor and signals the vehicle controller.

## Key elements

E1. A battery management unit that measures electrochemical impedance of lithium-ion cells at a plurality of frequencies
E2. A gas sensor inside the pack housing that detects electrolyte vapour
E3. A classifier that combines impedance drift and gas concentration trend to compute a thermal runaway risk score
E4. An early warning raised when the risk score exceeds a threshold before cell temperature rises above a limit
E5. A contactor that is opened in response to the early warning to isolate the pack
E6. A signal sent to a vehicle controller identifying the affected module

## Optional dependent features

- Impedance measurement is done during idle periods
- The risk threshold adapts to cell age
