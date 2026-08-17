# Android Intent Contract Compatibility Design

## Problem

Android Reason prompts instruct workers to emit Android-specific action kinds such as
`mobile_api_probe` and `mobile_authz_probe`. The real-website Reason contract currently
treats every action kind outside its four generic Web kinds as a custom high-risk action.
As a result, valid standard-risk Android work is rejected before an Intent is created,
Reason retries are exhausted, and the project remains in RECON.

## Scope

The fix changes only Reason-output normalization. It does not alter project scope
validation, high-risk authorization, execution behavior, or the Android prompts.

## Design

Define two explicit standard-risk action-kind sets:

- Generic actions: `surface_mapping`, `security_test`, `verify`, and `state_check`.
- Mobile actions: `android_app_launch`, `android_app_setup`, `mobile_app_setup`,
  `mobile_api_probe`, and `mobile_authz_probe`.

Generic actions remain valid for every surface type. Mobile actions are valid at
standard risk only when `surface_type` normalizes to `android` or `mobile_api`.
Any other custom action kind retains the existing requirement for `high` or
`irreversible` risk, including the existing identity and test-data requirements.

This keeps the Web safety boundary intact while accepting the action kinds produced by
the Android prompt and observed in the failed DVBA runs.

## Data Flow and Error Handling

Reason output continues through the existing Web-mode normalizer. The normalizer first
normalizes `action_kind` and `surface_type`, then decides whether the action is an
allowed standard-risk kind. Unsupported standard-risk actions raise the existing
validation error and do not create an Intent.

## Tests

Add focused contract tests that prove:

1. A standard-risk `mobile_api_probe` on an Android surface is accepted.
2. A standard-risk `mobile_app_setup` on an Android surface is accepted, matching the
   actual `proj_148` output.
3. A standard-risk `mobile_authz_probe` on a mobile API surface is accepted, matching
   the Android handoff prompt.
4. A mobile action on a Web surface is rejected.
5. An unknown standard-risk Web action remains rejected.

Run the focused contract tests first, then the complete dispatcher/config test module.

## Operational Recovery

After verification, rebuild the Dispatcher application image, restart the Dispatcher,
remove the stopped per-project worker container, and reactivate `proj_148`. The project
should then create its first Intent instead of exhausting Reason retries.
