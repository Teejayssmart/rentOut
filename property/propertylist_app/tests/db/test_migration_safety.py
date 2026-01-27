import pytest
from django.apps import apps
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

pytestmark = pytest.mark.django_db


def _app_migrations_on_disk(executor: MigrationExecutor, app_label: str) -> list[str]:
    """
    Returns migration names that exist ON DISK for a given app.
    Uses loader.disk_migrations (stable across Django versions).
    """
    disk = executor.loader.disk_migrations  # {(app_label, migration_name): Migration}
    names = [name for (app, name) in disk.keys() if app == app_label]
    return sorted(names)


def _app_leaf_migrations(executor: MigrationExecutor, app_label: str) -> list[str]:
    """
    Leaf migrations are the latest endpoints in the migration graph for this app.
    There can be more than one if you have branches.
    """
    leaf_nodes = executor.loader.graph.leaf_nodes(app_label)
    # leaf_nodes is list of tuples [(app_label, migration_name), ...]
    return sorted([name for (app, name) in leaf_nodes if app == app_label])


def test_migrations_apply_cleanly_to_latest():
    """
    Ensures migrations apply cleanly from zero to latest.
    This is the strongest “deploy will work on a fresh DB” signal.
    """
    call_command("migrate", verbosity=0, interactive=False)


def test_propertylist_app_migrations_are_reversible():
    """
    Checks that the app’s latest leaf migration can be reversed by one step,
    then re-applied. This is a rollback safety check.

    Notes:
    - If your app has multiple leaf migrations (branches), we test each leaf.
    - If there is only one migration (e.g. 0001_initial), reversing it may be too destructive
      for some projects; we skip in that case.
    """
    app_label = "propertylist_app"

    if not apps.is_installed(app_label):
        pytest.skip(f"{app_label} not in INSTALLED_APPS")

    executor = MigrationExecutor(connection)

    disk_names = _app_migrations_on_disk(executor, app_label)
    if not disk_names:
        pytest.skip(f"No migrations found on disk for {app_label}")

    # Apply everything first
    call_command("migrate", verbosity=0, interactive=False)

    leaf_names = _app_leaf_migrations(executor, app_label)
    if not leaf_names:
        pytest.skip(f"No leaf migrations found for {app_label}")

    for leaf in leaf_names:
        # For safety: if the leaf is the first migration and there are no others, skip
        if len(disk_names) == 1 and disk_names[0] == leaf:
            pytest.skip("Only one migration exists; reversing it is not a meaningful rollback check here.")

        # Unapply exactly that leaf migration (reverse one step for that leaf)
        # This keeps earlier migrations applied.
        call_command("migrate", app_label, leaf, verbosity=0, interactive=False)  # ensure at leaf (no-op)
        call_command("migrate", app_label, _previous_migration_name(disk_names, leaf), verbosity=0, interactive=False)

        # Re-apply back to leaf
        call_command("migrate", app_label, leaf, verbosity=0, interactive=False)


def _previous_migration_name(sorted_disk_names: list[str], current: str) -> str:
    """
    Returns the previous migration name in the disk-sorted list.
    Disk sorting is a practical best-effort for linear chains like 0001, 0002, ...
    For branched graphs, we’re still reversing only one step “by name order” which is fine
    for a rollback smoke test (it will fail if dependencies are invalid).
    """
    if current not in sorted_disk_names:
        # If current not found, just go to zero
        return "zero"

    idx = sorted_disk_names.index(current)
    if idx <= 0:
        return "zero"
    return sorted_disk_names[idx - 1]


def test_no_pending_migrations_in_repo():
    """
    Ensures there are no model changes without a migration committed.
    """
    call_command("makemigrations", "--check", "--dry-run", verbosity=0)