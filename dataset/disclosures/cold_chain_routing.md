# Cold-Chain Delivery Routing With Predicted Temperature Excursions

Synthetic sample disclosure for demonstration. Not a real invention.

- Technical field: Logistics and perishable goods transport
- Priority date: 2018-02-20
- Jurisdiction: US

## Problem

Route planners for refrigerated delivery treat temperature as a fixed constraint and ignore how door openings, traffic delays and ambient heat change the load temperature along the route.

## Solution

A routing system models payload temperature with a thermal model of each vehicle compartment. For every candidate route it predicts the time-temperature profile using forecast ambient temperature, expected stop durations and traffic delay, then selects the route and stop order that keeps predicted excursions below a limit while minimising travel time.

## Key elements

E1. A thermal model of a refrigerated vehicle compartment that predicts payload temperature over time
E2. Inputs to the model comprising forecast ambient temperature, expected stop duration and traffic delay
E3. Prediction of a time-temperature profile for each of a plurality of candidate routes
E4. Selection of a route and stop order that keeps the predicted temperature excursion below a limit
E5. Minimisation of travel time subject to the excursion limit
E6. Re-planning of remaining stops when a sensed compartment temperature deviates from the prediction

## Optional dependent features

- Door-open events are learned per driver
- Priority is given to pharmaceuticals
