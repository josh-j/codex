from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import datetime

def aggregate_report_data(hostvars, groups):
    """
    Aggregates results from all hosts into a single report model.
    Replaces the heavy Jinja2 logic in aggregate.yaml.
    """
    def _parse_day(date_str):
        if not date_str:
            return None
        try:
            return datetime.datetime.strptime(date_str, '%Y-%m-%d').strftime('%A')
        except Exception:
            return None

    report = {
        'meta': {
            'date': 'N/A',
            'day': 'N/A',
            'generated': 'N/A',
            'run_id': 'N/A'
        },
        'data': {
            'vcenters': [],
            'vcenter_infra': [],
            'cluster_capacity': [],
            'unisphere': [],
            'backups': [],
            'ucs': [],
            'alerts': [],
            'alarms': [],
            'reports': []
        },
        'counts': {
            'alarms': {'critical': 0, 'warning': 0},
            'alerts': {'critical': 0, 'warning': 0, 'info': 0},
            'reports_generated': 0,
            'sites_audited': len(groups.get('all', []))
        },
        'totals': {'critical': 0, 'warning': 0}
    }

    # 1. Collect all alerts and reports + Tag with site
    all_hosts = groups.get('all', [])
    for host in all_hosts:
        h_vars = hostvars.get(host, {})
        ncs = h_vars.get('ncs', {})
        
        # Meta from first host found
        if report['meta']['run_id'] == 'N/A' and 'check' in ncs:
            report['meta']['run_id'] = ncs['check'].get('id', 'N/A')
            report['meta']['date'] = ncs['check'].get('date', report['meta']['date'])
            report['meta']['generated'] = ncs['check'].get('timestamp', report['meta']['generated'])
            day = _parse_day(report['meta']['date'])
            if day:
                report['meta']['day'] = day

        # Aggregate Alerts
        for alert in ncs.get('alerts', []):
            alert_copy = alert.copy()
            alert_copy['site'] = alert.get('site', host)
            report['data']['alerts'].append(alert_copy)
            
            sev = alert.get('severity', '').upper()
            if sev == 'CRITICAL':
                report['counts']['alerts']['critical'] += 1
            elif sev == 'WARNING':
                report['counts']['alerts']['warning'] += 1
            elif sev == 'INFO':
                report['counts']['alerts']['info'] += 1

        # Aggregate Reports
        for rep in ncs.get('reports', []):
            rep_copy = rep.copy()
            rep_copy['site'] = rep.get('site', host)
            report['data']['reports'].append(rep_copy)

    # 2. vCenter Summaries & Alarms
    vcenters = groups.get('vcenters', [])
    for host in vcenters:
        h_vars = hostvars.get(host, {})
        ncs = h_vars.get('ncs', {})
        vc = h_vars.get('vcenter', {})
        conn = vc.get('connection', {})
        appliance = vc.get('appliance', {})
        health = appliance.get('health', {})
        config = appliance.get('config', {})
        backup = appliance.get('backup', {})
        
        # summary table data
        report['data']['vcenter_infra'].append({
            'site': host,
            'version': appliance.get('info', {}).get('version', 'unknown'),
            'health_overall': health.get('overall', 'unknown'),
            'health_database': health.get('database', 'unknown'),
            'health_storage': health.get('storage', 'unknown'),
            'backup_enabled': backup.get('enabled', False),
            'ssh_enabled': config.get('ssh_enabled', False)
        })

        # Cluster capacity data
        for cname, cdata in vc.get('clusters', {}).get('by_name', {}).items():
            util = cdata.get('utilization', {})
            comp = cdata.get('compliance', {})
            report['data']['cluster_capacity'].append({
                'site': host,
                'cluster': cname,
                'hosts': len(cdata.get('hosts', [])),
                'cpu_pct': util.get('cpu_pct', 0),
                'mem_pct': util.get('mem_pct', 0),
                'ha': comp.get('ha_enabled', False),
                'drs': comp.get('drs_enabled', False)
            })

        # Alarms
        for alarm in vc.get('alarms', {}).get('list', []):
            if isinstance(alarm, dict):
                alarm_copy = alarm.copy()
                alarm_copy['site'] = host
                report['data']['alarms'].append(alarm_copy)
                
                sev = alarm.get('severity', '').lower()
                if sev == 'critical':
                    report['counts']['alarms']['critical'] += 1
                elif sev == 'warning':
                    report['counts']['alarms']['warning'] += 1

    # 3. Storage / Backup / UCS summaries
    mapping = [
        ('sa', 'unisphere'),
        ('dd', 'backups'),
        ('ucsm', 'ucs')
    ]
    
    for group_name, report_key in mapping:
        for host in groups.get(group_name, []):
            h_vars = hostvars.get(host, {})
            ncs = h_vars.get('ncs', {})
            alerts = ncs.get('alerts', [])
            
            report['data'][report_key].append({
                'site': host,
                'check_timestamp': ncs.get('check', {}).get('timestamp', 'N/A'),
                'alerts_total': len(alerts),
                'alerts_critical': len([a for a in alerts if a.get('severity') == 'CRITICAL']),
                'reports_generated': len(ncs.get('reports', []))
            })

    # 4. Final Totals
    report['counts']['reports_generated'] = len(report['data']['reports'])
    report['totals']['critical'] = report['counts']['alarms']['critical'] + report['counts']['alerts']['critical']
    report['totals']['warning'] = report['counts']['alarms']['warning'] + report['counts']['alerts']['warning']

    return report

class FilterModule(object):
    def filters(self):
        return {
            'aggregate_report_data': aggregate_report_data
        }
