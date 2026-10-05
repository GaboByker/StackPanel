"""Datos para las gráficas de /admin/resources: historial del host y por
proyecto, agrupado en intervalos para que el navegador dibuje pocas
decenas/cientos de puntos aunque el rango sea de 7 días."""
import os
from datetime import datetime, timedelta, timezone

import panel_db
from system_monitor import _format_bytes

# rango -> (horas, minutos por intervalo). El muestreo es cada 5 min.
RANGES = {
    '1h': (1, 5),
    '6h': (6, 5),
    '24h': (24, 10),
    '7d': (168, 60),
}
DEFAULT_RANGE = '24h'
TOP_PROJECTS = 5   # el resto se agrupa en "Otros"


def _parse(ts):
    return datetime.fromisoformat(ts)


def _bucket_start(dt, minutes):
    total = dt.hour * 60 + dt.minute
    total -= total % minutes
    return dt.replace(hour=total // 60, minute=total % 60, second=0, microsecond=0)


def _avg(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def _round(v, digits=1):
    return None if v is None else round(v, digits)


def build(root, range_key):
    if range_key not in RANGES:
        range_key = DEFAULT_RANGE
    hours, step_min = RANGES[range_key]
    host_rows = panel_db.list_metrics_history(root, hours=hours)
    project_rows = panel_db.list_project_metrics_history(root, hours=hours)

    # Las filas antiguas no guardaban el nº de núcleos: se usa el último conocido.
    known_cpus = next((r['cpus'] for r in reversed(host_rows) if r.get('cpus')), None)
    cpus = known_cpus or os.cpu_count() or 1

    # Docker da la CPU sumada por núcleo (400 % = 4 núcleos al tope); se pasa a
    # porcentaje de la capacidad total del servidor.
    def cpu_share(value, row_cpus=None):
        if value is None:
            return None
        return min(max(value / (row_cpus or cpus), 0.0), 100.0)

    now = datetime.now(timezone.utc)
    step = timedelta(minutes=step_min)
    first = _bucket_start(now - timedelta(hours=hours), step_min) + step
    slots = []
    t = first
    while t <= now:
        slots.append(t)
        t += step
    index = {s: i for i, s in enumerate(slots)}
    n = len(slots)

    cpu_b, mem_b, disk_b = ([[] for _ in range(n)] for _ in range(3))
    for row in host_rows:
        i = index.get(_bucket_start(_parse(row['ts']), step_min))
        if i is None:
            continue
        cpu_b[i].append(cpu_share(row['cpu_percent'], row.get('cpus')))
        mem_b[i].append(row['mem_percent'])
        disk_b[i].append(row['disk_percent'])

    # Por proyecto: promedio por muestra dentro de cada intervalo.
    labels, per_cpu, per_mem, samples_in = {}, {}, {}, [set() for _ in range(n)]
    for row in project_rows:
        i = index.get(_bucket_start(_parse(row['ts']), step_min))
        if i is None:
            continue
        key = row['project_key']
        labels[key] = row['label'] or key
        samples_in[i].add(row['ts'])
        per_cpu.setdefault(key, [0.0] * n)[i] += cpu_share(row['cpu_percent']) or 0.0
        per_mem.setdefault(key, [0] * n)[i] += row['memory_bytes'] or 0

    # Los proyectos con color son los que más memoria usan en los últimos 7 días,
    # no en el rango elegido, para que no cambien de color al cambiar de rango.
    week_mem = {}
    for row in (project_rows if hours == 168 else panel_db.list_project_metrics_history(root, hours=168)):
        week_mem[row['project_key']] = week_mem.get(row['project_key'], 0) + (row['memory_bytes'] or 0)
    ranked = sorted(week_mem, key=week_mem.get, reverse=True)
    top = [k for k in ranked if k in labels][:TOP_PROJECTS]
    rest = [k for k in labels if k not in top]

    def series_values(per, k, digits):
        return [
            _round(per[k][i] / len(samples_in[i]), digits) if samples_in[i] else None
            for i in range(n)
        ]

    def series_rest(per, digits):
        out = []
        for i in range(n):
            if not samples_in[i]:
                out.append(None)
                continue
            out.append(_round(sum(per[k][i] for k in rest) / len(samples_in[i]), digits))
        return out

    # Slot de color = puesto en el ranking semanal (1..5); "Otros" va en gris (0).
    projects = [{'key': k, 'label': labels[k], 'slot': ranked.index(k) + 1} for k in top]
    project_cpu = {k: series_values(per_cpu, k, 2) for k in top}
    project_mem = {k: series_values(per_mem, k, 0) for k in top}
    if rest:
        projects.append({'key': '_otros', 'label': f'Otros ({len(rest)})', 'slot': 0})
        project_cpu['_otros'] = series_rest(per_cpu, 2)
        project_mem['_otros'] = series_rest(per_mem, 0)

    cpu = [_round(_avg(b)) for b in cpu_b]
    mem = [_round(_avg(b)) for b in mem_b]
    disk = [_round(_avg(b), 2) for b in disk_b]

    latest = host_rows[-1] if host_rows else None
    cpu_raw = [cpu_share(r['cpu_percent'], r.get('cpus')) for r in host_rows]
    cpu_raw = [v for v in cpu_raw if v is not None]
    mem_raw = [r['mem_percent'] for r in host_rows if r['mem_percent'] is not None]

    current_projects = []
    if project_rows:
        last_ts = project_rows[-1]['ts']
        for row in project_rows:
            if row['ts'] == last_ts and (row['memory_bytes'] or row['cpu_percent']):
                current_projects.append({
                    'key': row['project_key'],
                    'label': row['label'] or row['project_key'],
                    'cpu': round(cpu_share(row['cpu_percent']) or 0.0, 2),
                    'mem': row['memory_bytes'] or 0,
                })
        current_projects.sort(key=lambda p: p['mem'], reverse=True)

    return {
        'range': range_key,
        'ranges': list(RANGES),
        'step_min': step_min,
        'cpus': cpus,
        't': [s.isoformat() for s in slots],
        'cpu': cpu, 'mem': mem, 'disk': disk,
        'projects': projects,
        'project_cpu': project_cpu,
        'project_mem': project_mem,
        'has_projects': bool(project_rows),
        'current_projects': current_projects,
        'samples': len(host_rows),
        'latest': None if not latest else {
            'ts': latest['ts'],
            'cpu': _round(cpu_share(latest['cpu_percent'], latest.get('cpus'))),
            'mem': latest['mem_percent'],
            'disk': latest['disk_percent'],
            'mem_used': latest.get('mem_used_bytes'),
            'mem_total': latest.get('mem_total_bytes'),
            'disk_used': latest.get('disk_used_bytes'),
            'disk_total': latest.get('disk_total_bytes'),
            'mem_used_h': _format_bytes(latest.get('mem_used_bytes')) if latest.get('mem_used_bytes') is not None else None,
            'mem_total_h': _format_bytes(latest.get('mem_total_bytes')) if latest.get('mem_total_bytes') else None,
            'disk_free_h': _format_bytes(latest['disk_total_bytes'] - latest['disk_used_bytes'])
            if latest.get('disk_total_bytes') and latest.get('disk_used_bytes') is not None else None,
            'disk_total_h': _format_bytes(latest.get('disk_total_bytes')) if latest.get('disk_total_bytes') else None,
        },
        'stats': {
            'cpu_avg': _round(_avg(cpu_raw)),
            'cpu_max': _round(max(cpu_raw)) if cpu_raw else None,
            'mem_avg': _round(_avg(mem_raw)),
            'mem_max': _round(max(mem_raw)) if mem_raw else None,
        },
    }
