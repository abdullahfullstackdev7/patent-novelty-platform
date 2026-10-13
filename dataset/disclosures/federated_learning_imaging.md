# Federated Learning System for Hospital Imaging Models

Synthetic sample disclosure for demonstration. Not a real invention.

- Technical field: Medical imaging and distributed machine learning
- Priority date: 2018-03-01
- Jurisdiction: US

## Problem

Hospitals cannot pool patient scans to train diagnostic image models because of privacy rules, and models trained on one site generalize poorly to scanners and populations at other sites.

## Solution

Each hospital trains a local neural network on its own scans and sends only encrypted weight updates to a coordinating server. The server weights each update by a site data-quality score, aggregates them into a global model, and returns the model for the next round. A differential privacy noise stage is applied to updates before they leave the hospital.

## Key elements

E1. A local training module at each hospital that trains a neural network on locally stored medical images without exporting the images
E2. Encryption of model weight updates before transmission to a coordinating server
E3. A server-side aggregation module that combines the weight updates into a global model
E4. A per-site data-quality score computed from label consistency and image acquisition metadata
E5. Weighting of each site update during aggregation by its data-quality score
E6. A differential privacy noise stage applied to the weight updates before they leave the hospital
E7. Redistribution of the global model to the hospitals for a further training round

## Optional dependent features

- The quality score is recomputed each round
- Convergence is detected when the global validation loss changes by less than a threshold
