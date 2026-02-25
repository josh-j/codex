def get_adv(settings, key, default='unknown'):
    """
    Look up a value in a list of option_value dicts (key/value pairs).
    """
    settings = settings or []
    for s in settings:
        if isinstance(s, dict) and s.get('key') == key:
            return s.get('value')
    return default

def stig_eval(rules, item=None):
    """
    Evaluates a list of STIG rules against a discovery item.
    Rules are dicts with:
      id: str
      title: str (optional)
      severity: str (optional, default: medium)
      check: bool
      pass_msg: str (optional)
      fail_msg: str (optional)
    """
    results = []
    for rule in rules:
        rule_id = str(rule.get('id', 'UNKNOWN'))
        title = str(rule.get('title') or rule_id)
        severity = rule.get('severity', 'medium')
        check_passed = bool(rule.get('check', False))

        status = 'pass' if check_passed else 'failed'

        if check_passed:
            details = rule.get('pass_msg') or "Check passed"
        else:
            details = rule.get('fail_msg') or "Check failed"

        results.append({
            "id": rule_id,
            "title": title,
            "status": status,
            "severity": severity,
            "checktext": str(details),
            "fixtext": ""
        })
    return results

class FilterModule:
    def filters(self):
        return {
            "stig_eval": stig_eval,
            "get_adv": get_adv,
        }
