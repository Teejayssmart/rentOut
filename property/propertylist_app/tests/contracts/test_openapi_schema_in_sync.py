from pathlib import Path

import pytest
from django.core.management import call_command


@pytest.mark.django_db
def test_openapi_schema_file_is_in_sync(tmp_path):
    """
    Fails if someone changes endpoints/serializers but forgets to regenerate openapi_v1.yaml.
    """
    generated = tmp_path / "openapi_generated.yaml"
    call_command("spectacular", "--file", str(generated))

    repo_schema_path = Path("openapi_v1.yaml")
    assert repo_schema_path.exists(), "openapi_v1.yaml is missing. Regenerate and commit it."

    # Compare raw text (good enough for drift prevention)
    generated_text = generated.read_text(encoding="utf-8").strip()
    repo_text = repo_schema_path.read_text(encoding="utf-8").strip()

    assert generated_text == repo_text, (
        "OpenAPI schema file is out of date.\n"
        "Run: py manage.py spectacular --file openapi_v1.yaml\n"
        "Then commit the updated file."
    )