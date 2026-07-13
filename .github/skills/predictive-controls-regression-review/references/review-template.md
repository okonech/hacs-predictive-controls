# Predictive Controls Review Template

## Summary

- **Incident or proposal:**
- **Date:**
- **Primary category:**
- **Affected public entity:**
- **Status:** Reproduced / diagnosed / fixed / blocked by design decision

## Public Contract

- **Observed behavior:**
- **Expected behavior:**
- **Material event sequence:**
- **Public assertion:**

## Evidence

### Verified

-

### Assumed or unavailable

-

### Disconfirming check

-

## Requirement Matrix

| Area                | Requirement IDs | Finding |
| ------------------- | --------------- | ------- |
| Goals               |                 |         |
| Observation/model   |                 |         |
| Movement/prediction |                 |         |
| Policy              |                 |         |
| Governance          |                 |         |

## Root Cause

- **Controlling layer:**
- **Mechanism:**
- **Why current tests did not prevent it:**

## Model Review

### Approach A

- **Description:**
- **Probabilistic meaning:**
- **Strengths:**
- **Failure modes:**

### Approach B

- **Description:**
- **Probabilistic meaning:**
- **Strengths:**
- **Failure modes:**

### Decision

- **Selected approach:**
- **Why it is generic:**
- **Calibration impact:**
- **Multi-occupant impact:**
- **Stuck/flapping sensor impact:**
- **Missed-event impact:**
- **Route-learning and prediction impact:**
- **Persistence and restart impact:**
- **Performance impact:**

## Retained Regression

- **Test:**
- **Pre-fix failure:**
- **Public assertion:**
- **Internal invariant:**
- **Inverse/adversarial cases:**

## Implementation

- **Files and owning layers:**
- **Specification changes:**
- **Diagnostics/persistence changes:**
- **No room-specific behavior:** Confirmed / not confirmed

## Validation

- **Focused regression:**
- **Related suites:**
- **Full Python suite and coverage:**
- **Ruff:**
- **mypy:**
- **Frontend:**
- **Benchmark:**
- **Live Home Assistant:** Not queried / queried read-only through approved tooling

## Residual Risk

-
