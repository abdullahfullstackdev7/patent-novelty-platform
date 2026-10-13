# Vehicle-to-Grid Charging Scheduler With Battery Degradation Cost

Synthetic sample disclosure for demonstration. Not a real invention.

- Technical field: Electric vehicle charging and grid services
- Priority date: 2018-06-10
- Jurisdiction: US

## Problem

Schedulers that sell stored vehicle energy back to the grid ignore the battery wear caused by additional charge cycles, so owners can lose more value than they earn.

## Solution

A scheduler receives electricity price forecasts, grid regulation signals and the departure time and required state of charge set by the driver. It estimates a marginal degradation cost per kilowatt hour from cycle depth and temperature, and solves an optimisation that charges and discharges the vehicle only when expected revenue exceeds the degradation cost while guaranteeing the departure charge level.

## Key elements

E1. Receipt of electricity price forecasts and grid regulation signals
E2. Receipt of a driver departure time and a required departure state of charge
E3. Estimation of a marginal battery degradation cost from cycle depth and battery temperature
E4. An optimisation that schedules charging and discharging of the vehicle battery
E5. Discharging to the grid only when expected revenue exceeds the degradation cost
E6. A constraint that guarantees the required state of charge at the departure time

## Optional dependent features

- The degradation model is updated from battery telemetry
- Fleet-level limits on aggregate discharge
