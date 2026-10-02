# Core Food Publication Review Guide

## Purpose

This guide governs analyst review of the country-food and supplier-food cases produced by the Core Food decision-support capability.

Analytical eligibility does not constitute publication approval.

## Review Population

The publication-decision file contains:

- 143 country-food cases
- 283 supplier-food cases
- 426 total cases

All records initially default to:

```text
review_status = PENDING_REVIEW
publication_decision = HOLD
```

This fail-closed default prevents unreviewed analytical cases from entering presentation outputs.

## Allowed Review Statuses

```text
PENDING_REVIEW
REVIEW_IN_PROGRESS
REVIEW_COMPLETE
RETURNED_FOR_EVIDENCE
```

## Allowed Publication Decisions

```text
APPROVED_FOR_INTERNAL_PRESENTATION
APPROVED_FOR_EXTERNAL_PRESENTATION
REJECTED
HOLD
```

## Required Fields for Approval

A case can be approved only when all of the following conditions are met:

- Review status is `REVIEW_COMPLETE`
- Publication decision is an approved decision
- Reviewer name is recorded
- Review date is recorded
- Review rationale is recorded
- Approved display name is recorded
- Approved narrative scope is recorded
- Evidence verification is true
- Prohibited-claims verification is true
- The source case is not sensitivity-only

## Evidence Review

The reviewer must confirm:

1. Entity and Core Food identifiers are correct.
2. The case belongs to the primary governed population.
3. Stability is supported across the required scenarios.
4. Supporting supplier relationships are traceable.
5. Pooled supplier shares reconcile to one.
6. Immediate trade partners are not described as agricultural origin.
7. Static removal results are not described as forecasts.
8. Intervention categories remain hypotheses.
9. Limitations are complete and visible.
10. Prohibited claims are not made.

## Prohibited Claims

Reviewers must prevent claims of:

```text
AGRICULTURAL_ORIGIN
CAUSAL_DISRUPTION
FAILURE_PROBABILITY
INTERVENTION_EFFECTIVENESS
OFFICIAL_COUNTRY_RANK
OFFICIAL_SUPPLIER_RANK
```

## Internal Approval

`APPROVED_FOR_INTERNAL_PRESENTATION` permits controlled internal discussion only.

Internal approval does not authorize public release, external distribution, or publication.

## External Approval

`APPROVED_FOR_EXTERNAL_PRESENTATION` requires:

- Complete evidence review
- Complete prohibited-claims review
- Communication and narrative review
- Approved display name
- Approved narrative scope
- Visible limitations
- Named reviewer and review date

## Intervention Interpretation

Intervention categories are hypotheses for analyst review.

They do not establish:

- Feasibility
- Effectiveness
- Cost efficiency
- Implementation readiness
- Expected impact
- Causal benefit

## Supplier Interpretation

Supplier relationships represent observed immediate trade partners.

They do not establish:

- Agricultural production origin
- Ultimate upstream origin
- Sole-source production
- Causal disruption risk
- Probability of supplier failure

## Static Removal Interpretation

Static supplier-removal results assume no:

- Supplier substitution
- Inventory response
- Price response
- Logistics response
- Policy response
- Production response
- Consumer response
- Trade rerouting

They are controlled stress-test diagnostics, not forecasts.

## Fail-Closed Publication Behavior

Cases with any of the following conditions must not appear in approved presentation outputs:

- Pending review
- Review in progress
- Returned for evidence
- Publication decision of `HOLD`
- Publication decision of `REJECTED`
- Missing reviewer identity
- Missing review date
- Missing review rationale
- Missing approved narrative scope
- Evidence verification is false
- Prohibited-claims verification is false
- Sensitivity-only status is true

## Recommended Initial Review Portfolio

The initial presentation portfolio should contain approximately:

```text
8 to 12 country-food cases
8 to 12 supplier-food cases
```

The portfolio should provide diversity across:

- Core Food categories
- Geographic regions
- Vulnerability patterns
- Supplier-dependence structures
- Stability profiles
- Intervention-review categories

## Review Record

Every completed review should document:

```text
case_type
entity_m49
analytical_scope_code
review_status
publication_decision
reviewer_name
review_date
review_rationale
approved_display_name
approved_narrative_scope
additional_limitations
evidence_verified
prohibited_claims_verified
```

## Change Management

Any change to review statuses, publication decisions, approval rules, required metadata, or prohibited claims must update the governed policy, undergo validation, and be reviewed through a pull request.
