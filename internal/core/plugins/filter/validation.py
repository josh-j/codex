# collections/ansible_collections/internal/core/plugins/filter/validation.py

import os

import yaml
from ansible.errors import AnsibleFilterError


def _find_missing_keys(data, template, path=""):
    """
    Recursively walks a template dictionary and ensures 'data' has all the same keys.
    """
    missing = []

    # If the live data isn't a dictionary where we expect one, fail this path
    if not isinstance(data, dict):
        return [f"{path} (Expected dict, got {type(data).__name__})"]

    for key, value in template.items():
        current_path = f"{path}.{key}" if path else key

        if key not in data:
            missing.append(current_path)
        elif isinstance(value, dict):
            # If the default value is a nested dictionary, recurse into it
            missing.extend(_find_missing_keys(data.get(key, {}), value, current_path))

    return missing


def _type_name(value):
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, dict):
        return "dict"
    if isinstance(value, list):
        return "list"
    if value is None:
        return "null"
    return type(value).__name__


def _types_compatible(data_value, template_value):
    # Dict/list container type checks
    if isinstance(template_value, dict):
        return isinstance(data_value, dict)
    if isinstance(template_value, list):
        return isinstance(data_value, list)

    # Scalars (bool before int because bool is a subclass of int)
    if isinstance(template_value, bool):
        return isinstance(data_value, bool)
    if isinstance(template_value, int):
        return isinstance(data_value, int) and not isinstance(data_value, bool)
    if isinstance(template_value, float):
        # Allow ints where schema expects float to reduce false positives in YAML/Jinja coercions
        return (isinstance(data_value, float) or isinstance(data_value, int)) and not isinstance(data_value, bool)
    if isinstance(template_value, str):
        return isinstance(data_value, str)
    if template_value is None:
        return True

    # Unknown template types: don't over-constrain
    return True


def _find_type_mismatches(data, template, path=""):
    mismatches = []

    if isinstance(template, dict):
        if not isinstance(data, dict):
            return [f"{path} (Expected dict, got {_type_name(data)})"]

        for key, value in template.items():
            current_path = f"{path}.{key}" if path else key
            if key not in data:
                continue
            mismatches.extend(_find_type_mismatches(data.get(key), value, current_path))
        return mismatches

    if not _types_compatible(data, template):
        mismatches.append(f"{path} (Expected {_type_name(template)}, got {_type_name(data)})")

    return mismatches


def validate_schema_from_file(data, filepath, root_key):
    """
    Dynamically loads a YAML file, extracts the root_key (e.g., 'ubuntu_ctx'),
    and validates that 'data' matches its nested key structure.
    """
    if not os.path.isfile(filepath):
        raise AnsibleFilterError(f"Schema validation failed: File not found at {filepath}")

    try:
        with open(filepath) as f:
            schema_yaml = yaml.safe_load(f)
    except Exception as e:
        raise AnsibleFilterError(f"Schema validation failed: Could not parse YAML at {filepath}: {e}") from e

    if not isinstance(schema_yaml, dict) or root_key not in schema_yaml:
        raise AnsibleFilterError(f"Schema validation failed: Root key '{root_key}' not found in {filepath}")

    template_dict = schema_yaml[root_key]

    # Walk the template and compare it to the live data
    missing_keys = _find_missing_keys(data, template_dict, root_key)

    if missing_keys:
        raise AnsibleFilterError(
            f"Validation failed against schema {filepath}.\nMissing required keys: {', '.join(missing_keys)}"
        )

    # We return the original data so it can be used inline if needed,
    # though it's typically just used in an assert check.
    return True


def validate_typed_schema_from_file(data, filepath, root_key):
    """
    Loads a YAML schema template and validates:
      1) required key shape (same as validate_schema_from_file)
      2) container/scalar types inferred from template values
    """
    if not os.path.isfile(filepath):
        raise AnsibleFilterError(f"Typed schema validation failed: File not found at {filepath}")

    try:
        with open(filepath) as f:
            schema_yaml = yaml.safe_load(f)
    except Exception as e:
        raise AnsibleFilterError(f"Typed schema validation failed: Could not parse YAML at {filepath}: {e}") from e

    if not isinstance(schema_yaml, dict) or root_key not in schema_yaml:
        raise AnsibleFilterError(f"Typed schema validation failed: Root key '{root_key}' not found in {filepath}")

    template_dict = schema_yaml[root_key]

    missing_keys = _find_missing_keys(data, template_dict, root_key)
    if missing_keys:
        raise AnsibleFilterError(
            f"Validation failed against typed schema {filepath}.\nMissing required keys: {', '.join(missing_keys)}"
        )

    type_mismatches = _find_type_mismatches(data, template_dict, root_key)
    if type_mismatches:
        raise AnsibleFilterError(
            f"Type validation failed against schema {filepath}.\nMismatched types: {', '.join(type_mismatches)}"
        )

    return True


class FilterModule:
    def filters(self):
        return {
            "validate_schema_from_file": validate_schema_from_file,
            "validate_typed_schema_from_file": validate_typed_schema_from_file,
        }
