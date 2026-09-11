# Plan: Enforce disabled-organization and deactivated-device rules in openwisp-firmware-upgrader

Implements https://github.com/openwisp/openwisp-firmware-upgrader/issues/445 plus the
deactivated-device gaps still open in the decision matrix (follow-up of the closed #382).

> Target executor: AI agent using the Sonnet model. Follow the steps in order.
> Everything here was verified against the working tree at commit `bbec0e7`.

---

## 1. Context

OpenWISP is rolling out two related policies across modules:

- **Deactivated devices** (`Device._is_deactivated`): no new network or management
  operations may target them. Read and cleanup stay available.
- **Disabled organizations** (`Organization.is_active == False`): objects stay readable
  and deletable, but create and update are blocked; queued background work must
  revalidate before running.

`openwisp-users` PR #544 (branch `issues/522-disabled-org`, checked out at
`~/openwisp/openwisp-users`) provides the shared primitives, and `openwisp-controller`
PR #1456 (branch `issues/1393-disabled-org`, at `~/openwisp/openwisp-controller`)
implements the policy for devices. Both are installed as editable packages in
`~/openwisp/venv-firmware-upgrader`, so their behavior is live in this repo's test runs.

This repo already implements most of the deactivated-device policy. It has **zero**
references to organization `is_active`. The goal of this change is to close the
disabled-organization gap and the few remaining deactivated-device gaps, with tests
covering every row of `var/firmware-upgrader-matrix.csv`.

**Outcome:** upgrades cannot be created or executed for devices in disabled
organizations; mass upgrades exclude them; queued workers revalidate; reads, deletes,
cancellation, status aggregation and cleanup keep working.

---

## 1b. Companion deliverable: cross-module reference file

**Already written** at
`var/openwisp-org-device-state-reference.md` (gitignored, so it does not leak into a PR).
It catalogues every reusable primitive introduced by openwisp-users PR #544 and
openwisp-controller PR #1456 (dotted import paths, signatures, opt-out flags), the agreed
policy semantics (blocked vs. allowed operations, expected HTTP/admin status codes), the
upstream test helper recipes, and known gaps/traps (e.g. `DisabledOrgReadOnly` never
blocking POST, serializer MRO requirements, the best-effort nature of
`deactivate_organization_devices`). Read it before starting implementation instead of
re-deriving these facts from the two upstream branches.

---

## 2. Setup

```bash
cd /home/pandafy/openwisp/openwisp-firmware-upgrader
source ~/openwisp/venv-firmware-upgrader/bin/activate
git checkout -b issues/445-disabled-org master
```

Read `AGENTS.md` first. It is binding. Key points for this change:

- Focused tests: `./runtests.py -k <dotted.path> --no-input --failfast --verbosity=2`
  (add `--parallel` when running more than one TestCase class).
- Run `openwisp-qa-format` after each change, and `./run-qa-checks` before finishing.
- Commit subject: past tense, ends with `#445`, e.g.
  `[change] Limited firmware upgrade operations on disabled organizations #445`.
- Do not edit `CHANGES.rst`; the releaser publishes commit subjects automatically.

**Documentation is deliberately out of scope** for this change (user decision). Mark the
docs checklist item N/A in the PR. Note that AGENTS.md normally requires a docs update
for user-facing behavior changes, so a follow-up may be requested.

---

## 3. What already works: do not reimplement

Verified in the live tree. Reuse these instead of writing new code.

### Already handled by openwisp-users PR #544 (inherited, no code needed here)

| Mechanism                                                                             | Where                                                                | Effect on this repo                                                                                                                                                                                                                                                                                      |
| ------------------------------------------------------------------------------------- | -------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ProtectedAPIMixin.permission_classes` now includes `DisabledOrgReadOnly`             | `openwisp_users/api/mixins.py:347`                                   | `openwisp_firmware_upgrader/api/views.py:48` inherits it and does **not** override `permission_classes`, so PUT/PATCH on Category, Build, FirmwareImage, BatchUpgradeOperation, DeviceFirmware objects of a disabled org returns 403. DELETE and reads stay allowed.                                     |
| `FilterSerializerByOrgManaged._filter_organization_field` / `_filter_related_field`   | `openwisp_users/api/mixins.py:210-231`                               | `BaseSerializer` (`api/serializers.py:22`) already inherits it, so **create** into a disabled org returns 400 with `"Organization with pk ... does not exist or is disabled."` This also filters `group`/`location` in `BatchUpgradeSerializer`.                                                         |
| `MultitenantAdminMixin.has_change_permission` / `get_inline_instances` / `_edit_form` | `openwisp_users/multitenancy.py:80-170`                              | `BaseAdmin` and `BaseVersionAdmin` (`admin.py:69,73`) inherit it, so Category/Build/BatchUpgradeOperation change forms are 403 for disabled orgs, org selectors exclude disabled orgs, and the firmware inlines on the controller `DeviceAdmin` become add/change-disabled while delete stays available. |
| `organizations_managed` excludes disabled orgs                                        | `openwisp_users/base/models.py:152`                                  | Non-superusers lose list/detail visibility of disabled-org objects everywhere for free.                                                                                                                                                                                                                  |
| Controller cascade: disabling an org deactivates all its devices                      | `openwisp_controller/config/handlers.py:190` + `config/tasks.py:226` | The existing `is_deactivated()` guards in this repo catch most cases already. The org checks added below close the race window and the shared-category case.                                                                                                                                             |

### Already handled in this repo (deactivated devices)

- `AbstractDeviceFirmware.clean` raises `DEACTIVATED_DEVICE_FIRMWARE_ERROR` (`base/models.py:405`).
- `AbstractUpgradeOperation.clean` raises `DEACTIVATED_DEVICE_UPGRADE_OPERATION_ERROR` (`base/models.py:860`).
- `AbstractUpgradeOperation.upgrade()` aborts on deactivated devices (`base/models.py:939`).
  Because Celery retries re-enter `upgrade()`, **the "no re-check before retry" gap in the
  matrix is already closed**; the same code path will cover organizations after step 5.
- `_find_related_device_firmwares` excludes `device___is_deactivated=True` (`base/models.py:219`).
- `_find_firmwareless_devices` excludes `_is_deactivated=True` (`base/models.py:241`).
- `DeviceFirmwareDetailView.get_object` blocks writes and PUT-as-create for deactivated
  devices (`api/views.py:384,392`). **The matrix's "PUT-as-create bypass" note is stale.**
- `DeviceFirmwareInline` uses `DeactivatedDeviceReadOnlyMixin` (`admin.py:802`).

Updating `var/firmware-upgrader-matrix.csv` is **not** required; leave it as the source
document.

---

## 4. Design decisions (agreed with the user)

1. **Execution-time re-check only.** Do not connect a receiver for
   `openwisp_users.signals.organization_disabled`. The controller already deactivates the
   org's devices, and the guards added to `UpgradeOperation.upgrade()` and
   `BatchUpgradeOperation.upgrade()` re-validate when the worker actually runs. This
   mirrors `openwisp_controller/config/whois/tasks.py:75` and
   `geo/estimated_location/tasks.py:32`.
2. **Terminal status for a blocked in-flight operation is `aborted`**, not `cancelled`.
   `STATUS_CHOICES` documents `aborted` as "aborted due to prerequisites not met"
   (`base/models.py:827`), and the existing deactivated-device abort already uses it.
   `cancelled` stays reserved for explicit user cancellation.
   The one exception is a **batch** that ends up with zero operations: it is marked
   `cancelled` so it reaches a terminal state instead of hanging in `in-progress`.
3. **Direct writes raise; bulk resolution silently excludes.** Assigning a
   `DeviceFirmware` or creating an `UpgradeOperation` for a disabled org raises
   `ValidationError` (consistent with the deactivated-device handling in this repo).
   Mass-upgrade target queries filter the rows out silently (consistent with
   `openwisp_controller/pki/admin.py:18`).
4. **Shared categories:** a shared category (`organization_id is None`) can still be used
   for mass upgrades, but devices of disabled organizations are excluded from the target
   queries. A category owned by a disabled organization rejects upgrade initiation
   outright.
5. **Read, delete, cancel, status aggregation and file cleanup are never blocked.** Do not
   add guards to `AbstractUpgradeOperation.cancel`, `log_line`, `update_progress`,
   `calculate_and_update_status`, the websocket publishers, or
   `delete_firmware_files` / `_remove_file`.

---

## 5. Implementation

Work TDD where the behavior is unambiguous: for each step below, add the failing test
from section 6 first, then the code.

### Step 1: `openwisp_firmware_upgrader/constants.py`

Add two constants alongside the existing deactivated-device ones, same naming style:

```python
DISABLED_ORGANIZATION_FIRMWARE_ERROR = _(
    "Firmware upgrades are not allowed for disabled organizations."
)
DISABLED_ORGANIZATION_UPGRADE_OPERATION_ERROR = _(
    "Upgrade operations are not allowed for disabled organizations."
)
```

### Step 2: `base/models.py` validation guards

Import the new constants next to the existing ones (`base/models.py:22-25`).

- **`AbstractDeviceFirmware.clean`** (line 402): immediately after the
  `self.device.is_deactivated()` check, add:

  ```python
  if not self.device.organization.is_active:
      raise ValidationError(DISABLED_ORGANIZATION_FIRMWARE_ERROR)
  ```

  The device organization is authoritative here: `clean()` already rejects a mismatch
  between the image category organization and the device organization, and for shared
  categories the device organization is the only meaningful one.

- **`AbstractUpgradeOperation.clean`** (line 858): mirror the same pattern using
  `DISABLED_ORGANIZATION_UPGRADE_OPERATION_ERROR`, keeping the existing
  `hasattr(self, "device") and self.device` guard.

These two cover the whole `DeviceFirmware.save(upgrade=True)` -> `create_upgrade_operation`
-> `operation.full_clean()` chain (`base/models.py:446-473`), which is the shared path
for the REST API, the admin inline and batch expansion. No separate guard is needed in
`create_upgrade_operation`.

### Step 3: `base/models.py` target-resolution queries

- **`_find_related_device_firmwares`** (line 213): add
  `.filter(device__organization__is_active=True)` next to the existing
  `.exclude(device___is_deactivated=True)`.
- **`_find_firmwareless_devices`** (line 238): add `organization__is_active=True` to the
  `Device.objects.filter(...)` call.

This single change covers the preview (`dry_run`), the admin confirmation page, the REST
dry-run endpoint, `upgrade_related_devices` and `upgrade_firmwareless_devices`, because
they all resolve targets through these two methods. It also gives the shared-category
behavior required by the matrix.

Add `select_related("device__organization")` where `select_devices=True` in
`_find_related_device_firmwares` so the added join does not turn into an N+1 in the
confirmation page.

### Step 4: `AbstractBuild.batch_upgrade` (line 174)

Before the `dry_run` call, reject initiation when the category belongs to a disabled
organization:

```python
if self.category.organization_id and not self.category.organization.is_active:
    raise ValidationError(DISABLED_ORGANIZATION_FIRMWARE_ERROR)
```

This is the single choke point for both entrypoints: `BuildBatchUpgradeView.post`
(`api/views.py:125-132`) already converts `ValidationError` into a 400 response, and
`BuildAdmin.upgrade_selected` (`admin.py:260-263`) already converts it into an admin error
message. No changes are needed in either caller for this behavior.

### Step 5: `AbstractUpgradeOperation.upgrade` (line 935)

Extend the existing early-abort block. Keep the deactivated-device branch as it is and add
a second one so the log line names the real reason:

```python
if not self.device.organization.is_active:
    self.status = "aborted"
    self.log_line(
        _("Upgrade aborted because the organization has been disabled."),
        save=False,
    )
    self.save()
    return
```

Place it directly after the `is_deactivated()` branch. This is the execution-time
revalidation required by the issue: `tasks.upgrade_firmware` calls `upgrade()` on every
attempt including Celery retries, so no guard is needed inside the task itself.

### Step 6: `AbstractBatchUpgradeOperation.upgrade` (line 615)

Two changes:

1. At the start, before setting `in-progress`, bail out when the build's category
   organization has been disabled since the batch was scheduled:

   ```python
   if self.build.category.organization_id and not self.build.category.organization.is_active:
       self.status = "cancelled"
       self.save()
       return
   ```

2. At the end, after `upgrade_related_devices()` and the optional
   `upgrade_firmwareless_devices()`, mark the batch terminal when nothing was queued:

   ```python
   if not self.upgradeoperation_set.exists():
       self.status = "cancelled"
       self.save(update_fields=["status"])
   ```

   This is required because `calculate_and_update_status` returns `self.status` unchanged
   when there are zero operations (`base/models.py:804-811`), so a batch whose targets all
   became deactivated or disabled would otherwise stay `in-progress` forever. Do **not**
   use the `total_operations` cached property here; it may have been populated earlier in
   the request.

### Step 7: auto-creation paths (deactivated-device gaps from the matrix)

- **`AbstractDeviceFirmware.create_for_device`** (line 475): add an early return at the
  top of the method:

  ```python
  if device.is_deactivated() or not device.organization.is_active:
      return
  ```

  This is the authoritative guard for both Celery auto-creation tasks. It also removes the
  current behavior where every deactivated device produces a `logger.warning` from the
  swallowed `ValidationError` at line 504.

- **`AbstractDeviceFirmware.auto_add_device_firmware_to_device`** (line 510): add the same
  condition as an early return before `transaction.on_commit(...)`, so no pointless task
  is queued when a `DeviceConnection` is created for a deactivated device or a device in a
  disabled organization.

- **`tasks.create_all_device_firmwares`** (`tasks.py:83`): narrow the queryset so the task
  does not iterate the whole device table:

  ```python
  queryset = Device.objects.filter(
      os=fw_image.build.os,
      _is_deactivated=False,
      organization__is_active=True,
  ).select_related("organization")
  ```

  The `create_for_device` guard stays as the invariant; this filter is the efficiency
  counterpart, so add a short comment saying so.

### Step 8: `api/views.py` PUT-as-create hole

In `DeviceFirmwareDetailView.get_object` (line 374), the PUT-as-create branch never reaches
`DisabledOrgReadOnly.has_object_permission` (DRF only calls it when an object exists).
Extend the existing deactivated-device check to cover the organization, mirroring
`openwisp_controller/geo/api/views.py:206`:

```python
if self._device.is_deactivated():
    raise PermissionDenied(DEACTIVATED_DEVICE_FIRMWARE_ERROR)
if not self._device.organization.is_active:
    raise PermissionDenied(DISABLED_ORGANIZATION_FIRMWARE_ERROR)
```

The existing-object branch at line 392 needs no change: `DisabledOrgReadOnly` already
covers it via `organization_field = "device__organization"` (line 306).

Add `"device__organization"` to the `select_related` of the `DeviceFirmwareDetailView`
queryset (line 303) to keep the query count flat.

Leave `UpgradeOperationCancelView` untouched: cancellation must stay available (matrix row
`upgrade.operation.cancel`).

### Step 9: `admin.py`

- **`BuildAdmin.upgrade_selected`** (line 202): add an early check right after the
  `queryset.count() > 1` guard, so the user gets a clear message instead of an empty
  confirmation page. Follow `openwisp_controller/config/admin.py:742`:

  ```python
  build = queryset.first()
  if build.category.organization_id and not build.category.organization.is_active:
      self.message_user(
          request,
          _("Cannot start a mass upgrade for a disabled organization."),
          messages.ERROR,
      )
      return None
  ```

  Move the existing `build = queryset.first()` assignment (line 224) above this check.
  `batch_upgrade` (step 4) remains the authoritative guard.

- **`BatchUpgradeConfirmationForm.__init__`** (line 138): add
  `organization__is_active=True` to both `device_group_qs` and `location_qs`, so a shared
  category cannot be scoped to a group or location of a disabled organization. The REST
  equivalent is already handled by `FilterSerializerByOrgManaged`.

- **`DeviceUpgradeOperationInline`** (line 865): add
  `DeactivatedDeviceReadOnlyMixin` to the bases, matching `DeviceFirmwareInline`
  (line 802). It is currently read-only only by virtue of `readonly_fields = fields` and an
  inherited `has_add_permission`, which is implicit rather than enforced.

**Do not** add `multitenant_parent` to `UpgradeOperationAdmin`. Its absence
(`admin.py:423`) is pre-existing and unrelated to this issue; flag it to the user as a
possible follow-up rather than fixing it here.

---

## 6. Tests

Every row of `var/firmware-upgrader-matrix.csv` must end up covered. Add assertions to the
**existing** test classes rather than creating new ones.

### Wiring the shared helpers

- `openwisp_firmware_upgrader/tests/test_admin.py`: `BaseTestAdmin` already inherits
  `TestMultitenantAdminMixin`, which now inherits
  `openwisp_users.tests.utils.TestDisabledOrgAdminMixin`. The helpers are available with
  no import change.
- `openwisp_firmware_upgrader/tests/test_api.py`: add
  `from openwisp_users.tests.test_api import TestDisabledOrgApiMixin` and mix it into
  `TestAPIUpgraderMixin` (line 45).

Helper signatures (verified):

```python
_test_disabled_org_api_crud(
    obj, detail_url, list_url=None, create_payload=None, update_payload=None,
    roles=("org_admin", "superuser"),
    operations=("list", "retrieve", "create", "update", "delete"),
    org_admin_expected=None, superuser_expected=None,
    auth_mechanism="bearer", unchanged_field="name", organization=None,
)
_test_disabled_org_admin_crud(
    obj, change_data, roles=("org_admin", "superuser"),
    operations=("view", "change", "delete"), organization=None,
    org_admin_expected=None, superuser_expected=None, unchanged_field="name",
)
_test_disabled_org_admin_inline_readonly(
    model_admin, disabled_obj, active_obj=None,
    inline_models=None, inline_admins=None, user=None,
)
_test_disabled_org_admin_org_field_excludes_disabled(url, disabled_org, roles=("superuser",), ...)
```

Default expectations encoded by the helpers: API superuser gets list 200 / retrieve 200 /
create 400 / update 403 / delete 204; API org_admin gets 403 everywhere. Admin superuser
gets view 200 / change 403 / delete 200; admin org_admin gets view 302 / change 200
unchanged / delete 200 still present. Pass `org_admin_expected` or `superuser_expected`
only where firmware-upgrader genuinely differs, and say why in a comment.

Setup idiom used across OpenWISP: create the objects while the organization is active,
then disable it so the signal path runs.

```python
org.is_active = False
org.save(update_fields=["is_active"])
```

`unchanged_field` must be set per model: `Category` has `name`, `Build` has `version`,
`FirmwareImage` has `type`.

### Coverage map

| Matrix operation                                                                              | Test file / class                                                                                                                                                                                                                                                                        | What to assert                                                                                                                                                                                                                                                                             |
| --------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `category.manage`, `build.manage`, `image.register`                                           | `test_api.py` (`TestCategoryViews`, `TestBuildViews`, `TestFirmwareImageViews`), `test_admin.py` (`TestAdmin`)                                                                                                                                                                           | `_test_disabled_org_api_crud` and `_test_disabled_org_admin_crud` for each model. Confirms the inherited upstream guards actually hold in this repo.                                                                                                                                       |
| `automation.image.fanout_device_firmware`                                                     | `test_tasks.py::TestTasks`                                                                                                                                                                                                                                                               | Create an image after deactivating a device / disabling an org; assert `DeviceFirmware.objects.filter(device=...).count() == 0`. Use `subTest` for the two cases.                                                                                                                          |
| `automation.connection.autolink_device_firmware`                                              | `test_tasks.py::TestTasks`                                                                                                                                                                                                                                                               | Create a `DeviceConnection` for a deactivated device and for a device in a disabled org; assert no `DeviceFirmware` was created and (with `mock.patch`) that `create_device_firmware.delay` was not called.                                                                                |
| `device-firmware.assign`                                                                      | `test_models.py::TestModels` (extend `test_deactivated_device_validation` at line 1141), `test_api.py` (extend `test_deactivated_device` at 1356 and `test_deactivated_device_put_as_create` at 1385), `test_admin.py` (extend `test_device_firmware_inline_deactivated_device` at 2076) | Model: `assertRaises(ValidationError)` with `DISABLED_ORGANIZATION_FIRMWARE_ERROR`. API: PUT/PATCH -> 403, PUT-as-create -> 403, DELETE -> allowed. Admin: inline add/change disabled, delete allowed via `_test_disabled_org_admin_inline_readonly` against the controller `DeviceAdmin`. |
| `device-firmware.read`                                                                        | `test_api.py`                                                                                                                                                                                                                                                                            | GET on the device firmware detail endpoint still returns 200 for a disabled org and a deactivated device.                                                                                                                                                                                  |
| `upgrade.operation.progress_persist`, `batch.status.recalculate`, `realtime.progress.publish` | `test_models.py::TestModels`, `test_websockets.py`                                                                                                                                                                                                                                       | Disable the org **after** operations exist, then assert `log_line`, `update_progress` and `calculate_and_update_status` still work and the batch reaches a terminal status.                                                                                                                |
| `upgrade.operation.retry`                                                                     | `test_models.py::TestModelsTransaction`                                                                                                                                                                                                                                                  | Disable the org mid-upgrade, re-enter `upgrade()`, assert status `aborted` and the abort log line, and that no further retry is scheduled.                                                                                                                                                 |
| `upgrade.operation.cancel`                                                                    | `test_api.py` (cancel view tests, from line 2072)                                                                                                                                                                                                                                        | Cancel still returns 200 for an in-progress operation whose org was disabled and whose device was deactivated.                                                                                                                                                                             |
| `upgrade.operation.create`                                                                    | `test_models.py::TestModels`                                                                                                                                                                                                                                                             | `DeviceFirmware.save(upgrade=True)` for a disabled org raises `ValidationError`, and `UpgradeOperation.objects.count()` is unchanged.                                                                                                                                                      |
| `upgrade.operation.execute`, `async.upgrade.worker_run`                                       | `test_models.py::TestModels` (extend `test_upgrade_operation_aborts_when_device_deactivated_before_worker_runs` at line 345), `test_tasks.py`                                                                                                                                            | Disable the org after the operation is created, run `upgrade_firmware`, assert status `aborted`, the log line, and that no `DeviceConnection` was attempted (`mock.patch` on `get_working_connection`, `assert_not_called`).                                                               |
| `batch.upgrade.preview`                                                                       | `test_api.py` (extend `test_build_upgradeable_excludes_deactivated_devices` at line 357), `test_admin.py`                                                                                                                                                                                | Dry-run excludes devices of disabled orgs for a shared category; a disabled-org category returns 400 on POST.                                                                                                                                                                              |
| `batch.upgrade.schedule`                                                                      | `test_models.py::TestModels` (extend `test_batch_upgrade_excludes_deactivated_devices` at line 1085), `test_api.py`, `test_admin.py`                                                                                                                                                     | `batch_upgrade` on a disabled-org build raises `ValidationError`; API returns 400; the admin action shows the error message and creates no `BatchUpgradeOperation`.                                                                                                                        |
| `batch.upgrade.execute_related`, `batch.upgrade.execute_firmwareless`                         | `test_models.py::TestModelsTransaction`                                                                                                                                                                                                                                                  | With a shared category and two orgs (one disabled), the batch creates operations only for the active org's devices.                                                                                                                                                                        |
| `async.batch.worker_run`                                                                      | `test_models.py::TestModelsTransaction`                                                                                                                                                                                                                                                  | Disable the org between `batch_upgrade()` and the worker call; assert the batch ends `cancelled` with zero operations, not stuck `in-progress`.                                                                                                                                            |
| `storage.firmware.asset_delete`, `storage.firmware.file_delete`                               | `test_private_storage.py`, `test_api.py`                                                                                                                                                                                                                                                 | DELETE of a `FirmwareImage` / `Build` / `Category` in a disabled org still succeeds and still schedules file cleanup.                                                                                                                                                                      |

### Test hygiene rules for this repo

- Prefer `self.assertEqual` over `assertTrue` / `assertFalse` / `assertIsNone`.
- Group near-identical cases (deactivated device vs disabled org) with `subTest`,
  especially in `TransactionTestCase` classes where setup is expensive. Leave one blank
  line before each `with self.subTest(...)` only when a method has several of them.
- No docstrings on test methods whose name already describes the scenario.
- Keep tests quiet: use `capture_stdout` / `capture_any_output` from `openwisp_utils.tests`
  where the code under test logs.
- Adding `device.organization` lookups will change some `assertNumQueries` counts. The
  `select_related` additions in steps 3 and 8 should absorb most of it. Where a count
  genuinely must change, change it deliberately and add a brief comment; do not delete the
  assertion.

### Sample-app suite

AGENTS.md requires tenant-isolation and admin/REST authorization changes to be covered by
both suites. `tests/openwisp2/sample_firmware_upgrader/tests.py` subclasses
`TestAdmin`, `TestModels`, `TestModelsTransaction`, `TestTasks` and the API test classes,
so the new tests are inherited automatically. Verify that no new class needs to be
imported there, and run the sample-app suite (below). No new migration should be required;
if `makemigrations --check` complains, stop and report rather than generating one.

---

## 7. Verification

Run focused tests as you go:

```bash
source ~/openwisp/venv-firmware-upgrader/bin/activate

./runtests.py --no-input --failfast --verbosity=2 \
  -k openwisp_firmware_upgrader.tests.test_models

./runtests.py --no-input --failfast --verbosity=2 --parallel \
  -k openwisp_firmware_upgrader.tests.test_api \
  -k openwisp_firmware_upgrader.tests.test_admin \
  -k openwisp_firmware_upgrader.tests.test_tasks
```

Then formatting and QA:

```bash
openwisp-qa-format
./run-qa-checks
```

Sample-app integration suite:

```bash
SAMPLE_APP=1 ./runtests.py --no-input --failfast --verbosity=2 \
  -k openwisp2.sample_firmware_upgrader.tests
```

Manual smoke check of the end-to-end behavior (optional but valuable):

```bash
./tests/manage.py shell
# create an org, category, build, image, device with connection and DeviceFirmware
# then: org.is_active = False; org.save(update_fields=["is_active"])
# assert: DeviceFirmware(...).full_clean() raises ValidationError
# assert: build.batch_upgrade(firmwareless=True) raises ValidationError
# assert: existing UpgradeOperation.upgrade() sets status == "aborted"
```

**Full suite:** AGENTS.md requires a passing full run before pushing or opening a PR. This
change touches model validation, tenant isolation and admin/REST authorization, so the
full suite is mandatory. Do not run it unattended: report to the user and ask them to run
`./runtests` (20 minute timeout) or to confirm you should.

---

## 8. Files touched

| File                                                                                                                                                | Change                                                                                                                                                                                                                                                                                      |
| --------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `var/openwisp-org-device-state-reference.md`                                                                                                        | new, gitignored cross-module reference (section 1b) — already written                                                                                                                                                                                                                       |
| `openwisp_firmware_upgrader/constants.py`                                                                                                           | 2 new error message constants                                                                                                                                                                                                                                                               |
| `openwisp_firmware_upgrader/base/models.py`                                                                                                         | guards in `AbstractDeviceFirmware.clean`, `create_for_device`, `auto_add_device_firmware_to_device`; `AbstractUpgradeOperation.clean` and `upgrade`; `AbstractBuild.batch_upgrade`, `_find_related_device_firmwares`, `_find_firmwareless_devices`; `AbstractBatchUpgradeOperation.upgrade` |
| `openwisp_firmware_upgrader/tasks.py`                                                                                                               | queryset filter in `create_all_device_firmwares`                                                                                                                                                                                                                                            |
| `openwisp_firmware_upgrader/api/views.py`                                                                                                           | org check in `DeviceFirmwareDetailView.get_object` PUT-as-create branch; `select_related`                                                                                                                                                                                                   |
| `openwisp_firmware_upgrader/admin.py`                                                                                                               | early check in `BuildAdmin.upgrade_selected`; active-org filters in `BatchUpgradeConfirmationForm.__init__`; `DeactivatedDeviceReadOnlyMixin` on `DeviceUpgradeOperationInline`                                                                                                             |
| `openwisp_firmware_upgrader/tests/test_models.py`, `test_api.py`, `test_admin.py`, `test_tasks.py`, `test_private_storage.py`, `test_websockets.py` | new assertions in existing classes                                                                                                                                                                                                                                                          |

No migrations. No new models, settings, signals or dependencies.

---

## 9. Out of scope

- Documentation (user decision; AGENTS.md would normally require it).
- `CHANGES.rst` (handled by the releaser from the commit subject).
- `UpgradeOperationAdmin` missing `multitenant_parent` (`admin.py:423`): pre-existing,
  unrelated. Report it, do not fix it.
- Any change to `openwisp-users` or `openwisp-controller`. Both are prerequisites already
  checked out and installed; if a needed primitive turns out to be missing, stop and ask.
- Updating `var/firmware-upgrader-matrix.csv`. Its stale notes about the PUT-as-create hole
  and the missing mass-upgrade excludes should be reported to the user, not edited.
