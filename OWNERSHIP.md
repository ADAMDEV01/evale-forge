# Business data ownership rollout

## Ownership map

`datasets`, `rubrics`, and `evaluation_runs` have nullable `user_id` columns
referencing `users.id` with `ON DELETE RESTRICT` and a lookup index. `test_cases`
and `dataset_versions` derive ownership through their dataset;
`rubric_criteria` derives through its rubric; `evaluation_results` derives
through their run; and `human_reviews` derives through their result.

Runs have a direct owner because they are a primary list/read boundary and may
refer to a rubric as well as a dataset. Evaluation verifies that the dataset
and any referenced rubric belong to the authenticated user before provider
execution. Test-case and rubric-criterion operations verify their owned parent
before writes; results and reviews are accessed only through an owned run.

Existing uniqueness remains scoped to existing parent identities:
`test_cases(dataset_id, title)` is already dataset-scoped. User email remains
globally unique. No existing uniqueness rule is broadened or replaced in this
revision. There are currently no unique constraints on rubric names or rubric
criterion names.

## Migration and adoption

Revision `ce4d8129ab31` adds nullable owner references and indexes. It first
checks legacy references among datasets, versions, cases, runs, rubrics,
criteria, results, reviews, and refresh sessions. It aborts before schema
changes if it detects an orphan or a test case whose version belongs to a
different dataset.

The migration never picks a user and does not backfill ownership. Existing rows
remain `user_id = NULL`, so an existing installation is in a **pending
adoption** state after upgrade. New records created through the business API
receive the authenticated user's ID; fresh databases have no legacy rows to
adopt.

Adoption is an explicit, separately approved operation through
`adopt_unowned_records(session, designated_admin_user_id)` in
`backend.app.db.ownership_adoption`. The caller must supply the designated,
active administrator's exact user ID. There is no automatic admin selection.
The operation checks references and existing assignments first, rejects
conflicting ownership, assigns only `NULL` owner columns in one transaction,
and is safe to retry for that same administrator. Do not expose this helper as a
public API endpoint or call it from startup/migration code.

Downgrade is refused once any dataset, rubric, or run has an owner; this avoids
discarding adopted ownership. The business API now scopes dataset, rubric, and
run operations to the verified authenticated user. Child records are authorized
through their owned parent. Unowned legacy records are excluded from lists and
single-resource operations return 404. Health endpoints remain public.

## Relationship and lifecycle notes

Deleting a user is restricted while owned top-level records reference it.
Child ownership is derived, so ordinary child updates must not change its
parent to a resource owned by a different user. Cross-owner reassignment needs
a dedicated, explicitly authorized operation; ordinary request payloads do not
set or change `user_id`. Ownership does not automatically adopt existing
unowned records; they remain inaccessible until the separately approved
adoption operation is run.
