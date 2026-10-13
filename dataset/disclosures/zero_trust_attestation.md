# Zero-Trust Device Attestation Using Hardware-Bound Credentials

Synthetic sample disclosure for demonstration. Not a real invention.

- Technical field: Network security and device identity
- Priority date: 2018-03-22
- Jurisdiction: US

## Problem

Network access decisions rely on credentials that can be copied from a compromised device, and devices are trusted for long periods after a single successful login.

## Solution

Each device holds a private key sealed in a hardware security module and produces a signed attestation of its firmware measurements on every access request. A policy engine verifies the signature and measurements against an approved list, grants access scoped to a single session, and requires fresh attestation when the session token expires or the device posture changes.

## Key elements

E1. A private key sealed in a hardware security module of the device
E2. Generation by the device of a signed attestation of firmware measurements with each access request
E3. A policy engine that verifies the signature and compares the measurements with an approved list
E4. Granting of access scoped to a single session
E5. Expiry of the session token after a time limit
E6. A requirement for fresh attestation when the session token expires or the device posture changes

## Optional dependent features

- Posture includes disk encryption state
- Revocation of an approved measurement takes effect on the next request
