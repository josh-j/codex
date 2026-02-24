#!/usr/bin/env python3
# collections/ansible_collections/internal/core/plugins/filter/validation.py

from __future__ import absolute_import, division, print_function

__metaclass__ = type

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


def validate_schema_from_file(data, filepath, root_key):
    """
    Dynamically loads a YAML file, extracts the root_key (e.g., 'ubuntu_ctx'),
    and validates that 'data' matches its nested key structure.
    """
    if not os.path.isfile(filepath):
        raise AnsibleFilterError(
            f"Schema validation failed: File not found at {filepath}"
        )

    try:
        with open(filepath, "r") as f:
            schema_yaml = yaml.safe_load(f)
    except Exception as e:
        raise AnsibleFilterError(
            f"Schema validation failed: Could not parse YAML at {filepath}: {e}"
        )

    if not isinstance(schema_yaml, dict) or root_key not in schema_yaml:
        raise AnsibleFilterError(
            f"Schema validation failed: Root key '{root_key}' not found in {filepath}"
        )

    template_dict = schema_yaml[root_key]

    # Walk the template and compare it to the live data
    missing_keys = _find_missing_keys(data, template_dict, root_key)

    if missing_keys:
        raise AnsibleFilterError(
            f"Validation failed against schema {filepath}.\n"
            f"Missing required keys: {', '.join(missing_keys)}"
        )

    # We return the original data so it can be used inline if needed,
    # though it's typically just used in an assert check.
    return True


class FilterModule(object):
    def filters(self):
        return {
            "validate_schema_from_file": validate_schema_from_file,
        }
