from ansible.utils.display import Display
from ansible.module_utils.common.dict_transformations import recursive_diff
import copy

display = Display()

def recursive_combine(base, update):
    """
    Recursively merges two dictionaries.
    Replaces the Jinja2 complexity: combine(..., recursive=True)
    """
    if not isinstance(base, dict):
        base = {}
    if not isinstance(update, dict):
        update = {}

    result = copy.deepcopy(base)
    
    for key, value in update.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = recursive_combine(result[key], value)
        else:
            result[key] = value
            
    return result

class FilterModule(object):
    def filters(self):
        return {
            'recursive_combine': recursive_combine
        }
