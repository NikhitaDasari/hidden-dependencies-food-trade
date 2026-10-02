# Core Food Team Onboarding Guide

## What the team should understand first

The Core Food capability is not one model. It is a governed chain of evidence, controls, alternative specifications, stability analysis, supplier relationships, and analyst review.

## Quick orientation

### If you are a data engineer

Focus on:

- Source manifests
- M49 normalization
- Annual grains
- Source hashes
- Period controls
- Output reproducibility

### If you are a data scientist

Focus on:

- Feature definitions
- Scenario specifications
- Transformation choices
- Weight sensitivity
- Stability bands
- Missingness policy

### If you are a domain expert

Focus on:

- Country-food case interpretation
- Supplier relationship interpretation
- Immediate trade partner limitation
- Intervention hypotheses
- Analyst review queue

### If you are a governance or risk reviewer

Focus on:

- Policy files
- Population separation
- Evidence-confidence separation
- Prohibited claims
- Publication eligibility
- Provenance summaries

### If you are preparing a presentation

Use:

- Aggregated counts
- Stability bands
- Selected reviewed case studies
- Clear uncertainty and limitations
- No exact official rankings

## Current reviewed analytical portfolio

```text
143 eligible country-food cases
283 eligible supplier-food cases
426 mandatory analyst-review cases
14,433 supporting supplier relationships
143 intervention hypotheses
```

## How to interpret a country-food case

A country-food case combines:

- Stable developmental vulnerability signal
- Governed model-readiness status
- High-governed evidence confidence
- Exposure and concentration features
- Observed immediate supplier relationships
- Limitations and prohibited claims

It does not mean the country-food system will fail.

## How to interpret a supplier-food case

A supplier-food case combines:

- Observed importer breadth
- Importer dependence
- Vulnerability-weighted reach
- Relationship persistence
- Stability across six vulnerability specifications

It does not prove that the supplier is the agricultural origin or that disruption will occur.

## How to participate in analyst review

For each case:

1. Verify the country, food scope, and M49 identifiers.
2. Confirm the record is in the primary population.
3. Review the stability band and scenario availability.
4. Inspect the largest observed supplier shares.
5. Review relationship persistence.
6. Read all limitations and prohibited claims.
7. Determine whether external context is required.
8. Approve, reject, or return the case for further evidence.
9. Document the reviewer, date, rationale, and publication decision.

## Review questions

- Is the signal stable across scenarios?
- Is the finding driven by one unusually large supplier relationship?
- Does the network have sufficient temporal coverage?
- Could re-export or routing explain the observed supplier?
- Is limited evidence influencing the interpretation?
- Is the proposed intervention only a hypothesis?
- What additional data is required before external use?

## Communication language

Preferred wording:

> Developmental country-food vulnerability signal

> Observed immediate trade-partner dependence

> Supplier-food systemic-reach signal

> Static no-substitution removal stress test

> Intervention hypothesis for analyst review

Avoid:

> Official risk rank

> Failure probability

> Agricultural origin

> Proven chokepoint

> Guaranteed intervention

> Predicted disruption

## Ownership model

Recommended responsibilities:

- Data owner: Source integrity and refresh
- Engineering owner: Pipeline execution and reproducibility
- Methodology owner: Feature, scenario, and threshold governance
- Domain reviewer: Case interpretation
- Governance reviewer: Prohibited claims and publication controls
- Product or presentation owner: Approved narrative and visualization

## Change-management rule

Any change to periods, features, weights, thresholds, populations, eligibility, or publication rules should update the relevant policy file, rerun downstream builds, refresh provenance, and undergo pull-request review.
