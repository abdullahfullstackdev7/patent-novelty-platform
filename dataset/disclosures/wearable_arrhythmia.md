# Wearable Patch for Atrial Fibrillation Detection With On-Device Inference

Synthetic sample disclosure for demonstration. Not a real invention.

- Technical field: Wearable cardiac monitoring
- Priority date: 2018-05-03
- Jurisdiction: US

## Problem

Continuous electrocardiogram monitoring produces large data volumes that drain wearable batteries when streamed, while simple threshold detectors give many false alarms during motion.

## Solution

A skin patch records single-lead electrocardiogram and accelerometer signals. A small neural network running on the patch microcontroller classifies each thirty second window, using the accelerometer to gate windows corrupted by motion. Only windows classified as irregular are compressed and transmitted to a phone, together with a confidence value.

## Key elements

E1. A skin patch with electrodes recording a single-lead electrocardiogram signal
E2. An accelerometer in the patch that produces a motion signal
E3. A neural network executed on a microcontroller of the patch that classifies fixed-length signal windows as regular or irregular rhythm
E4. Gating of windows by the motion signal so that motion-corrupted windows are not classified
E5. Compression and wireless transmission of only the windows classified as irregular
E6. Transmission of a classification confidence value with each transmitted window

## Optional dependent features

- The network is quantised to eight bits
- The patch enters a low power mode between windows
