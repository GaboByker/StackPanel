#!/usr/bin/env python3
"""Portal inicial: elige entre proyectos independientes en distintos puertos."""
import crypt
import os
import re
import secrets
import shutil
import sqlite3
import time
from datetime import datetime, timedelta, timezone

from flask import (
    Flask,
    abort,
    flash,
    g,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
    session,
    url_for,
)
from flask_wtf import CSRFProtect
from flask_wtf.csrf import CSRFError

from auth import (
    authenticate,
    change_password,
    confirm_totp,
    create_admin,
    disable_totp,
    get_admin,
    get_admin_id,
    get_session_epoch,
    get_totp_state,
    init_db,
    list_admins,
    login_admin,
    logout_admin,
    revoke_sessions,
    set_totp_secret,
    verify_totp,
)
from docker_control import (
    list_service_status,
    start_service,
    stop_service,
    containers_status,
    stop_containers,
    start_containers,
    remove_containers,
    remove_volumes,
    container_logs,
    list_all_containers,
    list_published_ports,
    probe_http_port,
    PROBE_HOST,
)
from system_monitor import get_system_metrics
import panel_db
import proxy_control
import app_templates
import backup_control
import files_control
import project_scan
import notification_control
import db_viewer
import db_autodetect
import scheduler
import docker_ops
import sftp_control
import project_git
import firewall_rules
import guard_client
import security
import resource_charts
import ssh_access
import wp_sso
import sshadm_client
import site_presets
import subprocess
import pyotp
import segno

PORTAL_ROOT = os.path.dirname(os.path.abspath(__file__))
PUBLIC_HOST = os.environ.get('PUBLIC_HOST', 'localhost')
PORTAL_PORT = int(os.environ.get('PORTAL_PORT', '5005'))
STACK_ROOT = os.environ.get(
    'STACK_ROOT',
    '/stack' if os.path.isdir('/stack') else os.path.dirname(PORTAL_ROOT),
)
PROXY_SITES_DIR = os.environ.get(
    'PROXY_SITES_DIR',
    '/app/proxy-sites' if os.path.isdir('/app/proxy-sites') else os.path.join(STACK_ROOT, 'proxy', 'sites'),
)
CERTBOT_EMAIL = os.environ.get('CERTBOT_EMAIL', '')
HOST_STACK_ROOT = os.environ.get('HOST_STACK_ROOT', STACK_ROOT)
BACKUPS_DIR = os.environ.get('BACKUPS_DIR', '/app/backups')


def get_public_host():
    return panel_db.get_setting(PORTAL_ROOT, 'public_host') or PUBLIC_HOST


def get_certbot_email():
    return panel_db.get_setting(PORTAL_ROOT, 'certbot_email') or CERTBOT_EMAIL


def _project_local_folder(project):
    """Carpeta del proyecto en el montaje r/w del panel (solo proyectos bajo html/)."""
    folder = (project or {}).get('folder') or ''
    if not folder.startswith('html/'):
        return None
    return os.path.join(files_control.html_root(STACK_ROOT), folder[5:])


def _is_wordpress(project):
    return project.get('template') == 'wordpress' or wp_sso.is_wordpress(_project_local_folder(project))


def _project_paths(key):
    """(local_folder, host_folder) para un project_key nuevo: local_folder es
    donde este proceso puede escribir (montaje r/w html-rw); host_folder es la
    misma carpeta vista como ruta del host real, la que necesita Docker para
    los binds de los contenedores que se crean."""
    local_folder = os.path.join(files_control.html_root(STACK_ROOT), key)
    host_folder = os.path.join(HOST_STACK_ROOT, 'html', key)
    return local_folder, host_folder


def _ensure_project_folder(project):
    """Crea html/<key> si el proyecto todavía no tiene carpeta propia y la
    registra en la base de datos. Devuelve el project (dict) actualizado."""
    if project.get('folder'):
        return project
    folder = f"html/{project['project_key']}"
    html_root = files_control.html_root(STACK_ROOT)
    target_dir = os.path.join(html_root, project['project_key'])
    os.makedirs(target_dir, exist_ok=True)
    try:
        os.chown(target_dir, -1, os.stat(html_root).st_gid)
    except OSError:
        pass
    os.chmod(target_dir, 0o775)
    panel_db.set_project_folder(PORTAL_ROOT, project['id'], folder)
    project['folder'] = folder
    return project

# Grafos de código disponibles: el del propio panel y los de los proyectos
# de esta instalación (site_presets.py).
GRAPHIFY_PROJECTS = {'portal': 'portal', **site_presets.get('graphify_projects', {})}
_GRAPHIFY_FILES = frozenset({
    'graph.html',
    'graph.json',
    'graph.svg',
    'GRAPH_REPORT.md',
    'manifest.json',
    'cost.json',
})

app = Flask(
    __name__,
    template_folder=os.path.join(PORTAL_ROOT, 'templates'),
    static_folder=os.path.join(PORTAL_ROOT, 'static'),
)
app.config['SECRET_KEY'] = os.environ.get('PORTAL_SECRET_KEY', 'portal-dev-change-me')
# Techo del cookie; la vida real de la sesión (horas máximas e inactividad)
# la decide security.get_rules() en _validate_admin_session.
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
app.config['SESSION_REFRESH_EACH_REQUEST'] = False
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
# Activar (PORTAL_COOKIE_SECURE=1) cuando el panel se sirva por HTTPS.
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('PORTAL_COOKIE_SECURE') == '1'
app.config['MAX_CONTENT_LENGTH'] = int(os.environ.get('PORTAL_MAX_UPLOAD_MB', '512')) * 1024 * 1024
csrf = CSRFProtect(app)

init_db(PORTAL_ROOT)
panel_db.init_db(PORTAL_ROOT)
security.init_db(PORTAL_ROOT)
ssh_access.init_db(PORTAL_ROOT)
security.ensure_jail_defaults(PORTAL_ROOT)
os.makedirs(BACKUPS_DIR, exist_ok=True)
scheduler.start(PORTAL_ROOT, STACK_ROOT, BACKUPS_DIR)


@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    flash('El formulario expiró por inactividad. Volvé a intentar la acción.', 'error')
    next_url = request.referrer
    if next_url and next_url.startswith(request.host_url):
        return redirect(next_url)
    return redirect(url_for('admin_panel') if get_admin_id() else url_for('admin_login'))


def _no_cache(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, private, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


def _clear_session_cookie(response):
    iface = app.session_interface
    response.delete_cookie(
        iface.get_cookie_name(app),
        domain=iface.get_cookie_domain(app),
        path=iface.get_cookie_path(app),
        secure=iface.get_cookie_secure(app),
        samesite=iface.get_cookie_samesite(app),
        httponly=iface.get_cookie_httponly(app),
    )
    return response


def load_projects():
    projects = []
    for item in panel_db.list_projects_raw(PORTAL_ROOT):
        path = item.get('path') or '/'
        if not path.startswith('/'):
            path = '/' + path
        suffix = '' if path == '/' else path

        if item.get('access_mode') == 'domain' and item.get('domain'):
            base = f"https://{item['domain']}"
        else:
            base = f"http://{get_public_host()}:{item.get('port')}"
        url = base + suffix

        icon = item.get('icon_path')
        if icon and str(icon).startswith(('http://', 'https://')):
            icon_url = icon
        elif icon:
            icon_url = base + (icon if icon.startswith('/') else f'/{icon}')
        else:
            icon_url = None

        projects.append({
            'db_id': item['id'],
            'id': item.get('project_key', ''),
            'name': item.get('name', 'Proyecto'),
            'description': item.get('description', ''),
            'access_mode': item.get('access_mode'),
            'port': item.get('port'),
            'domain': item.get('domain'),
            'path': path,
            'icon_path': icon,
            'url': url,
            'icon': icon_url,
            'folder': item.get('folder'),
            'containers': panel_db.project_containers(item),
            'template': item.get('template'),
            'monitor_health': bool(item.get('monitor_health', 1)),
            'auto_backup': bool(item.get('auto_backup', 0)),
            'cpu_limit': item.get('cpu_limit'),
            'mem_limit_mb': item.get('mem_limit_mb'),
        })
    _autolink_containers(projects)
    return projects


def _autolink_containers(projects):
    """Si un proyecto se registró antes de que existieran sus contenedores
    (p.ej. se importó la carpeta y luego se hizo el build), quedaba sin
    contenedores y no aparecía en el Resumen. Los buscamos y los guardamos."""
    pending = [p for p in projects if not p['containers'] and (p['folder'] or '').startswith('html/')]
    if not pending:
        return
    all_containers, err = list_all_containers()
    if err or not all_containers:
        return
    claimed = {c for p in projects for c in p['containers']}
    for project in pending:
        dir_name = project['folder'].split('/', 1)[1].strip('/')
        if not dir_name or '/' in dir_name:
            continue
        found = sorted({
            c['name'] for c in project_scan.match_containers(dir_name, all_containers)
            if c['name'] not in claimed
        })
        if found:
            panel_db.set_containers(PORTAL_ROOT, project['db_id'], found)
            project['containers'] = found
            claimed.update(found)


def _donut_segments(categories):
    """Arma los segmentos de un donut SVG (técnica stroke-dasharray sobre circunferencia=100).
    categories: lista de (label, value, color)."""
    total = sum(value for _, value, _ in categories)
    segments = []
    cumulative = 0.0
    for label, value, color in categories:
        pct = (value / total * 100) if total else 0
        segments.append({
            'label': label,
            'value': value,
            'pct': round(pct, 1),
            'color': color,
            'dasharray': f'{pct:.3f} {100 - pct:.3f}',
            'dashoffset': round(25 - cumulative, 3),
        })
        cumulative += pct
    return segments


def _status_donut_segments(running, stopped, custom):
    return _donut_segments([
        ('En marcha', running, 'var(--success-text)'),
        ('Detenidos', stopped, 'var(--danger-text)'),
        ('Sin contenedor', custom, 'var(--text-faint)'),
    ])


def _require_admin():
    if get_admin_id():
        return None
    return redirect(url_for('admin_login', next=request.path))


def list_graphify_graphs():
    by_id = {p['id']: p for p in load_projects()}
    graphs = []
    for project_id, folder in GRAPHIFY_PROJECTS.items():
        graph_html = os.path.join(STACK_ROOT, folder, 'graphify-out', 'graph.html')
        if not os.path.isfile(graph_html):
            continue
        meta = by_id.get(project_id, {})
        default_name = 'Portal' if project_id == 'portal' else folder
        graphs.append({
            'id': project_id,
            'name': meta.get('name', default_name),
            'folder': folder,
            'url': url_for('admin_graphify_file', project_id=project_id, filename='graph.html'),
            'report_url': url_for(
                'admin_graphify_file', project_id=project_id, filename='GRAPH_REPORT.md'
            ) if os.path.isfile(
                os.path.join(STACK_ROOT, folder, 'graphify-out', 'GRAPH_REPORT.md')
            ) else None,
        })
    return graphs


def _graphify_out_dir(project_id):
    folder = GRAPHIFY_PROJECTS.get(project_id)
    if not folder:
        return None
    out_dir = os.path.join(STACK_ROOT, folder, 'graphify-out')
    if not os.path.isdir(out_dir):
        return None
    return out_dir


@app.context_processor
def inject_admin():
    admin = get_admin(PORTAL_ROOT) if get_admin_id() else None
    return {'current_admin': admin}


@app.before_request
def _block_banned_ips():
    g.client_ip = security.client_ip(request)
    if security.is_banned(PORTAL_ROOT, g.client_ip):
        resp = make_response(
            'Acceso bloqueado temporalmente por demasiados intentos fallidos.\n', 403
        )
        resp.headers['Content-Type'] = 'text/plain; charset=utf-8'
        return _no_cache(resp)
    return None


_TWO_FA_EXEMPT = ('/admin/2fa', '/admin/logout', '/static/')


@app.before_request
def _validate_admin_session():
    """Cierra la sesión si fue revocada, superó su vida máxima o lleva
    demasiado tiempo inactiva; y obliga a configurar 2FA si es requisito."""
    admin_id = get_admin_id()
    if not admin_id:
        return None
    rules = security.get_rules(PORTAL_ROOT)
    now = int(datetime.now(timezone.utc).timestamp())
    epoch = get_session_epoch(PORTAL_ROOT, admin_id)
    expired = (
        epoch is None
        or session.get('epoch') != epoch
        or now - int(session.get('auth_at', 0)) > rules['sec_session_hours'] * 3600
        or now - int(session.get('seen_at', 0)) > rules['sec_idle_minutes'] * 60
    )
    if expired:
        logout_admin()
        if request.path.startswith('/admin'):
            flash('Tu sesión expiró. Vuelve a iniciar sesión.', 'error')
            return redirect(url_for('admin_login', next=request.path))
        return None
    # Se renueva como mucho una vez por minuto para no reescribir la cookie
    # en cada petición (las métricas se consultan cada pocos segundos).
    if now - int(session.get('seen_at', 0)) >= 60:
        session['seen_at'] = now
    if rules['sec_require_2fa'] and not request.path.startswith(_TWO_FA_EXEMPT):
        _, enabled = get_totp_state(PORTAL_ROOT, admin_id)
        if not enabled:
            flash('La verificación en dos pasos es obligatoria. Actívala para continuar.', 'error')
            return redirect(url_for('admin_2fa'))
    return None


@app.after_request
def _security_headers(response):
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
    response.headers.setdefault('Referrer-Policy', 'same-origin')
    return response


@app.before_request
def _ensure_first_run_setup():
    if request.path == '/setup' or request.path.startswith('/static/'):
        return None
    if not list_admins(PORTAL_ROOT):
        return redirect(url_for('setup_wizard'))
    return None


@app.route('/setup', methods=['GET', 'POST'])
def setup_wizard():
    if list_admins(PORTAL_ROOT):
        return redirect(url_for('admin_login'))
    error = None
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        password2 = request.form.get('password2', '')
        public_host = request.form.get('public_host', '').strip()
        certbot_email = request.form.get('certbot_email', '').strip()
        if password != password2:
            error = 'Las contraseñas no coinciden.'
        else:
            new_email, error = create_admin(PORTAL_ROOT, email, password, None)
            if new_email:
                settings = {}
                if public_host:
                    settings['public_host'] = public_host
                if certbot_email:
                    settings['certbot_email'] = certbot_email
                if settings:
                    panel_db.set_settings(PORTAL_ROOT, settings)
                admin, _ = authenticate(PORTAL_ROOT, new_email, password)
                login_admin(admin, PORTAL_ROOT)
                panel_db.log_action(PORTAL_ROOT, new_email, 'setup_completed', '')
                flash('Panel configurado. ¡Bienvenido!', 'success')
                return redirect(url_for('admin_panel'))
    detected_host = request.host.split(':')[0]
    return render_template('setup_wizard.html', error=error, detected_host=detected_host)


@app.route('/')
def portal_home():
    resp = make_response(
        render_template('portal.html', projects=load_projects(), public_host=get_public_host())
    )
    return _no_cache(resp)


def _safe_next(url):
    return url if url and url.startswith('/') and not url.startswith('//') else url_for('admin_panel')


@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if get_admin_id():
        return redirect(url_for('admin_panel'))
    error = None
    if request.method == 'POST':
        ip = g.client_ip
        email = request.form.get('email', '')
        ua = request.headers.get('User-Agent', '')
        if security.account_locked(PORTAL_ROOT, email.strip().lower(), ip):
            # Mismo mensaje que un fallo normal: no se le confirma al atacante
            # que la cuenta existe ni que está protegida.
            security.record_attempt(PORTAL_ROOT, ip, 'login', email, False, ua)
            error = 'Correo o contraseña incorrectos.'
        else:
            admin, error = authenticate(PORTAL_ROOT, email, request.form.get('password', ''))
            if admin and admin.get('totp_enabled'):
                # La contraseña sola no cuenta como acceso: el éxito se
                # registra cuando también pasa el segundo paso.
                session.clear()
                session['pending_admin_id'] = admin['id']
                session['pending_at'] = int(datetime.now(timezone.utc).timestamp())
                session['pending_tries'] = 0
                session['pending_next'] = _safe_next(request.args.get('next'))
                return redirect(url_for('admin_login_verify'))
            security.record_attempt(PORTAL_ROOT, ip, 'login', email, bool(admin), ua)
            if admin:
                login_admin(admin, PORTAL_ROOT)
                panel_db.log_action(PORTAL_ROOT, admin['email'], 'login', ip)
                flash('Sesión de administrador iniciada.', 'success')
                return redirect(_safe_next(request.args.get('next')))
        if security.is_banned(PORTAL_ROOT, ip):
            return _block_banned_ips()
    resp = make_response(render_template('admin_login.html', error=error))
    return _no_cache(resp)


_PENDING_2FA_SECONDS = 300


@app.route('/admin/login/verify', methods=['GET', 'POST'])
def admin_login_verify():
    admin_id = session.get('pending_admin_id')
    now = int(datetime.now(timezone.utc).timestamp())
    if not admin_id or now - int(session.get('pending_at', 0)) > _PENDING_2FA_SECONDS:
        session.clear()
        return redirect(url_for('admin_login'))
    error = None
    if request.method == 'POST':
        ip = g.client_ip
        row = next((a for a in list_admins(PORTAL_ROOT) if a['id'] == admin_id), None)
        email = row['email'] if row else ''
        ua = request.headers.get('User-Agent', '')
        if verify_totp(PORTAL_ROOT, admin_id, request.form.get('code')):
            next_url = _safe_next(session.get('pending_next'))
            security.record_attempt(PORTAL_ROOT, ip, '2fa', email, True, ua)
            login_admin({'id': admin_id}, PORTAL_ROOT)  # limpia la sesión y guarda admin_id
            panel_db.log_action(PORTAL_ROOT, email, 'login_2fa', ip)
            flash('Sesión de administrador iniciada.', 'success')
            return redirect(next_url)
        security.record_attempt(PORTAL_ROOT, ip, '2fa', email, False, ua)
        session['pending_tries'] = int(session.get('pending_tries', 0)) + 1
        if security.pending_2fa_exhausted(session['pending_tries']):
            session.clear()
            flash('Demasiados códigos incorrectos. Vuelve a iniciar sesión.', 'error')
            return redirect(url_for('admin_login'))
        if security.is_banned(PORTAL_ROOT, ip):
            return _block_banned_ips()
        error = 'Código incorrecto.'
    return render_template('admin_login_verify.html', error=error)


@app.route('/admin/logout', methods=['GET', 'POST'])
def admin_logout():
    email = current_admin_email()
    if email:
        panel_db.log_action(PORTAL_ROOT, email, 'logout', '')
    logout_admin()
    referer = request.referrer or ''
    if '/admin' in referer:
        target = url_for('admin_login') + '?logout=1'
    else:
        target = url_for('portal_home') + '?logout=1'
    response = redirect(target, code=303)
    _clear_session_cookie(response)
    return _no_cache(response)


@app.route('/admin')
def admin_panel():
    gate = _require_admin()
    if gate:
        return gate
    all_services = list_service_status()
    services = [svc for svc in all_services if svc['key'] != 'proxy']
    managed_containers = {c for svc in all_services for c in svc['containers']}
    docker_projects = []
    for project in load_projects():
        if not project['containers']:
            continue
        if managed_containers.intersection(project['containers']):
            # Ya está cubierto por un servicio fijo (arriba); evita la tarjeta duplicada.
            continue
        project['docker_status'] = containers_status(project['containers'])
        docker_projects.append(project)
    resp = make_response(
        render_template(
            'admin_panel.html',
            services=services,
            docker_projects=docker_projects,
            public_host=get_public_host(),
        )
    )
    return _no_cache(resp)


@app.route('/admin/projects')
def admin_projects():
    gate = _require_admin()
    if gate:
        return gate
    projects = load_projects()
    running = stopped = custom = with_db = 0
    for project in projects:
        project['docker_status'] = containers_status(project['containers']) if project['containers'] else None
        project['db_count'] = len(panel_db.list_databases(PORTAL_ROOT, project['db_id']))
        project['is_wordpress'] = _is_wordpress(project)
        if project['db_count']:
            with_db += 1
        if project['docker_status']:
            if project['docker_status']['running']:
                running += 1
            else:
                stopped += 1
        else:
            custom += 1
    stats = {
        'total': len(projects),
        'running': running,
        'stopped': stopped,
        'custom': custom,
        'with_db': with_db,
        'auto_backup': sum(1 for p in projects if p['auto_backup']),
        'monitored': sum(1 for p in projects if p['monitor_health']),
    }
    stats['donut_segments'] = _status_donut_segments(running, stopped, custom)
    resp = make_response(
        render_template(
            'admin_projects.html',
            projects=projects,
            stats=stats,
            public_host=get_public_host(),
        )
    )
    return _no_cache(resp)


@app.route('/admin/api/docker-ports')
def admin_api_docker_ports():
    if not get_admin_id():
        return {'error': 'No autorizado'}, 401
    containers, err = list_all_containers()
    used_ports = {p['port'] for p in panel_db.list_projects_raw(PORTAL_ROOT) if p.get('port')}
    ports = []
    seen = set()
    for c in containers:
        if c['state'] != 'running':
            continue
        for port in c['host_ports']:
            if port in seen:
                continue
            seen.add(port)
            ports.append({
                'port': port,
                'container': c['name'],
                'registered': port in used_ports,
                'http_ok': probe_http_port(PROBE_HOST, port),
            })
    ports.sort(key=lambda p: p['port'])
    return jsonify({'ports': ports, 'error': err or None})


@app.route('/admin/projects/new', methods=['GET', 'POST'])
def admin_project_new():
    gate = _require_admin()
    if gate:
        return gate
    error = None
    if request.method == 'POST':
        project, error = panel_db.create_project(
            PORTAL_ROOT,
            request.form.get('name', ''),
            request.form.get('description', ''),
            request.form.get('access_mode', 'port'),
            request.form.get('port', ''),
            request.form.get('domain', ''),
            request.form.get('path', '/'),
            request.form.get('icon_path', ''),
        )
        if project:
            project = _ensure_project_folder(project)
            want_ssl = request.form.get('access_mode') == 'domain' and request.form.get('request_ssl') == 'on'
            if project.get('access_mode') == 'domain' and project.get('domain'):
                target_host = 'host.docker.internal'
                target_port = request.form.get('proxy_target_port') or project.get('port') or 80
                site, site_error = panel_db.create_site(
                    PORTAL_ROOT, project['domain'], target_host, target_port, project_id=project['id'],
                )
                if site:
                    ok, apply_error = proxy_control.apply_site(
                        PROXY_SITES_DIR, site['domain'], site['target_host'], site['target_port'], ssl_ready=False,
                    )
                    if not ok:
                        flash(f'Proyecto creado, pero el proxy no se pudo aplicar: {apply_error}', 'error')
                    elif want_ssl:
                        cert_ok, cert_out = proxy_control.issue_certificate(site['domain'], get_certbot_email())
                        if cert_ok:
                            proxy_control.apply_site(
                                PROXY_SITES_DIR, site['domain'], site['target_host'], site['target_port'], ssl_ready=True,
                            )
                            panel_db.set_site_ssl(PORTAL_ROOT, site['id'], True)
                            flash('Proyecto y dominio creados. Certificado SSL emitido.', 'success')
                        else:
                            flash(
                                f'Proyecto y dominio creados, pero no se pudo emitir el SSL todavía: {cert_out.strip()[-300:]}',
                                'error',
                            )
                    else:
                        flash('Proyecto y dominio creados. Emite el SSL cuando el DNS ya apunte aquí.', 'success')
                else:
                    flash(f'Proyecto creado, pero el sitio del proxy falló: {site_error}', 'error')
            else:
                flash('Proyecto creado.', 'success')
            return redirect(url_for('admin_projects'))
    return render_template('admin_project_form.html', error=error, public_host=get_public_host())


@app.route('/admin/projects/<int:project_id>/delete', methods=['POST'])
def admin_project_delete(project_id):
    if not get_admin_id():
        return redirect(url_for('admin_login'))
    project = panel_db.get_project(PORTAL_ROOT, project_id)
    panel_db.delete_project(PORTAL_ROOT, project_id)
    panel_db.log_action(PORTAL_ROOT, current_admin_email(), 'project_delete', project['name'] if project else str(project_id))
    flash('Proyecto eliminado del portal.', 'success')
    return redirect(url_for('admin_projects'))


@app.route('/admin/projects/<int:project_id>/stop', methods=['POST'])
def admin_project_stop(project_id):
    if not get_admin_id():
        return redirect(url_for('admin_login'))
    project = panel_db.get_project(PORTAL_ROOT, project_id)
    if not project:
        abort(404)
    containers = panel_db.project_containers(project)
    if not containers:
        flash('Este proyecto no tiene contenedores vinculados para detener.', 'error')
    else:
        ok, msg = stop_containers(containers)
        if ok:
            panel_db.set_desired_state(PORTAL_ROOT, project_id, 'stopped')
        panel_db.log_action(PORTAL_ROOT, current_admin_email(), 'project_stop', project['name'])
        flash('Proyecto detenido.' if ok else f'No se pudo detener: {msg}', 'success' if ok else 'error')
    return redirect(url_for('admin_projects'))


@app.route('/admin/projects/<int:project_id>/start', methods=['POST'])
def admin_project_start(project_id):
    if not get_admin_id():
        return redirect(url_for('admin_login'))
    project = panel_db.get_project(PORTAL_ROOT, project_id)
    if not project:
        abort(404)
    containers = panel_db.project_containers(project)
    if not containers:
        flash('Este proyecto no tiene contenedores vinculados para iniciar.', 'error')
    else:
        ok, msg = start_containers(containers)
        if ok:
            panel_db.set_desired_state(PORTAL_ROOT, project_id, 'running')
        panel_db.log_action(PORTAL_ROOT, current_admin_email(), 'project_start', project['name'])
        flash('Proyecto iniciado.' if ok else f'No se pudo iniciar: {msg}', 'success' if ok else 'error')
    return redirect(url_for('admin_projects'))


@app.route('/admin/projects/<int:project_id>/description', methods=['POST'])
def admin_project_description(project_id):
    if not get_admin_id():
        return redirect(url_for('admin_login'))
    project = panel_db.get_project(PORTAL_ROOT, project_id)
    if not project:
        abort(404)
    panel_db.set_description(PORTAL_ROOT, project_id, request.form.get('description', ''))
    panel_db.log_action(PORTAL_ROOT, current_admin_email(), 'project_description', project['name'])
    flash('Descripción actualizada.', 'success')
    return redirect(url_for('admin_project_detail', project_id=project_id))


def _gen_sftp_password():
    return secrets.token_urlsafe(9)


def _hash_sftp_password(password):
    return crypt.crypt(password, crypt.mksalt(crypt.METHOD_SHA512))


@app.route('/admin/projects/<int:project_id>/sftp/create', methods=['POST'])
def admin_project_sftp_create(project_id):
    if not get_admin_id():
        return redirect(url_for('admin_login'))
    project = panel_db.get_project(PORTAL_ROOT, project_id)
    if not project:
        abort(404)
    # Proyectos antiguos que quedaron "solo enlace" (sin carpeta propia)
    # todavía pueden no tener carpeta; se crea aquí también por si acaso.
    project = _ensure_project_folder(project)

    username = (request.form.get('username') or '').strip().lower()
    if not panel_db.KEY_RE.match(username):
        flash('El usuario debe ser minúsculas/números/guiones, sin espacios.', 'error')
        return redirect(url_for('admin_project_detail', project_id=project_id))

    custom_password = (request.form.get('password') or '').strip()
    if custom_password and len(custom_password) < 8:
        flash('La contraseña debe tener al menos 8 caracteres.', 'error')
        return redirect(url_for('admin_project_detail', project_id=project_id))
    password = custom_password or _gen_sftp_password()
    try:
        user = panel_db.create_sftp_user(PORTAL_ROOT, project_id, username, _hash_sftp_password(password))
    except sqlite3.IntegrityError:
        flash(f'El usuario "{username}" ya está en uso (los usuarios SFTP son únicos en todo el panel).', 'error')
        return redirect(url_for('admin_project_detail', project_id=project_id))

    allow_write = request.form.get('allow_write') == 'on'
    if not allow_write:
        panel_db.set_sftp_user_write(PORTAL_ROOT, user['id'], False)

    ok, err = sftp_control.sync(PORTAL_ROOT, STACK_ROOT, HOST_STACK_ROOT)
    panel_db.log_action(PORTAL_ROOT, current_admin_email(), 'sftp_create', f"{project['name']}: {username}")
    if not ok:
        flash(f'Acceso creado pero el servidor SFTP no se pudo actualizar: {err}', 'error')
    else:
        warning = ''
        if allow_write and not sftp_control.folder_group_writable(STACK_ROOT, project['folder']):
            warning = ' Aviso: la carpeta de este proyecto no es de escritura para el grupo, así que aunque diga "Escritura" no va a poder subir archivos hasta que ajustes los permisos de esa carpeta en el servidor.'
        flash(
            f'Acceso SFTP creado. Usuario: "{username}" · Contraseña: "{password}" '
            f'(cópiala ahora, no se vuelve a mostrar) · Servidor: {get_public_host()}:{sftp_control.SFTP_PORT}.{warning}',
            'success',
        )
    return redirect(url_for('admin_project_detail', project_id=project_id))


@app.route('/admin/projects/<int:project_id>/sftp/<int:user_id>/toggle-write', methods=['POST'])
def admin_project_sftp_toggle_write(project_id, user_id):
    if not get_admin_id():
        return redirect(url_for('admin_login'))
    user = panel_db.get_sftp_user(PORTAL_ROOT, user_id)
    if not user or user['project_id'] != project_id:
        abort(404)
    new_write = not user['allow_write']
    panel_db.set_sftp_user_write(PORTAL_ROOT, user_id, new_write)
    ok, err = sftp_control.sync(PORTAL_ROOT, STACK_ROOT, HOST_STACK_ROOT)
    if not ok:
        flash(f'Permiso guardado, pero el servidor SFTP no se pudo actualizar: {err}', 'error')
    else:
        project = panel_db.get_project(PORTAL_ROOT, project_id)
        warning = ''
        if new_write and project and project.get('folder') and not sftp_control.folder_group_writable(STACK_ROOT, project['folder']):
            warning = ' Aviso: la carpeta de este proyecto no es de escritura para el grupo, así que no va a poder subir archivos hasta que ajustes los permisos en el servidor.'
        flash('Permiso actualizado.' + warning, 'success')
    return redirect(url_for('admin_project_detail', project_id=project_id))


@app.route('/admin/projects/<int:project_id>/sftp/<int:user_id>/reset-password', methods=['POST'])
def admin_project_sftp_reset_password(project_id, user_id):
    if not get_admin_id():
        return redirect(url_for('admin_login'))
    user = panel_db.get_sftp_user(PORTAL_ROOT, user_id)
    if not user or user['project_id'] != project_id:
        abort(404)
    custom_password = (request.form.get('password') or '').strip()
    if custom_password and len(custom_password) < 8:
        flash('La contraseña debe tener al menos 8 caracteres.', 'error')
        return redirect(url_for('admin_project_detail', project_id=project_id))
    password = custom_password or _gen_sftp_password()
    panel_db.set_sftp_user_password(PORTAL_ROOT, user_id, _hash_sftp_password(password))
    ok, err = sftp_control.sync(PORTAL_ROOT, STACK_ROOT, HOST_STACK_ROOT)
    if not ok:
        flash(f'Contraseña guardada pero el servidor SFTP no se pudo actualizar: {err}', 'error')
    else:
        flash(
            f'Nueva contraseña para "{user["username"]}": "{password}" (cópiala ahora, no se vuelve a mostrar).',
            'success',
        )
    return redirect(url_for('admin_project_detail', project_id=project_id))


@app.route('/admin/projects/<int:project_id>/sftp/<int:user_id>/delete', methods=['POST'])
def admin_project_sftp_delete(project_id, user_id):
    if not get_admin_id():
        return redirect(url_for('admin_login'))
    user = panel_db.get_sftp_user(PORTAL_ROOT, user_id)
    if not user or user['project_id'] != project_id:
        abort(404)
    panel_db.delete_sftp_user(PORTAL_ROOT, user_id)
    ok, err = sftp_control.sync(PORTAL_ROOT, STACK_ROOT, HOST_STACK_ROOT)
    flash('Acceso SFTP eliminado.' if ok else f'Acceso eliminado, pero el servidor SFTP no se pudo actualizar: {err}', 'success' if ok else 'error')
    return redirect(url_for('admin_project_detail', project_id=project_id))


@app.route('/admin/projects/<int:project_id>/monitor-toggle', methods=['POST'])
def admin_project_monitor_toggle(project_id):
    if not get_admin_id():
        return redirect(url_for('admin_login'))
    project = panel_db.get_project(PORTAL_ROOT, project_id)
    if not project:
        abort(404)
    panel_db.set_monitor_health(PORTAL_ROOT, project_id, not project.get('monitor_health'))
    return redirect(url_for('admin_project_detail', project_id=project_id))


@app.route('/admin/projects/<int:project_id>/auto-backup-quick-toggle', methods=['POST'])
def admin_project_auto_backup_quick_toggle(project_id):
    if not get_admin_id():
        return redirect(url_for('admin_login'))
    project = panel_db.get_project(PORTAL_ROOT, project_id)
    if not project:
        abort(404)
    panel_db.set_auto_backup(PORTAL_ROOT, project_id, not project.get('auto_backup'))
    return redirect(url_for('admin_backups'))


@app.route('/admin/projects/<int:project_id>/backup-settings', methods=['POST'])
def admin_project_backup_settings(project_id):
    if not get_admin_id():
        return redirect(url_for('admin_login'))
    project = panel_db.get_project(PORTAL_ROOT, project_id)
    if not project:
        abort(404)
    days = request.form.getlist('backup_days')
    hour = int(request.form.get('backup_hour') or '3')
    retention = int(request.form.get('backup_retention') or '7')
    panel_db.set_backup_schedule(
        PORTAL_ROOT, project_id, request.form.get('auto_backup') == 'on', days, hour, retention,
    )
    flash('Horario de backup actualizado.', 'success')
    return redirect(url_for('admin_project_detail', project_id=project_id))


@app.route('/admin/projects/<int:project_id>/limits', methods=['POST'])
def admin_project_limits(project_id):
    if not get_admin_id():
        return redirect(url_for('admin_login'))
    project = panel_db.get_project(PORTAL_ROOT, project_id)
    if not project:
        abort(404)
    cpu_raw = (request.form.get('cpu_limit') or '').strip()
    mem_raw = (request.form.get('mem_limit_mb') or '').strip()
    cpu_limit = float(cpu_raw) if cpu_raw else None
    mem_limit_mb = int(mem_raw) if mem_raw else None
    panel_db.set_resource_limits(PORTAL_ROOT, project_id, cpu_limit, mem_limit_mb)
    errors = []
    for container in panel_db.project_containers(project):
        ok, err = docker_ops.update_container_resources(container, cpu_limit, mem_limit_mb)
        if not ok:
            errors.append(f'{container}: {err}')
    if errors:
        flash('Límites guardados, pero no se pudieron aplicar a: ' + '; '.join(errors), 'error')
    else:
        flash('Límites de recursos actualizados.', 'success')
    return redirect(url_for('admin_project_detail', project_id=project_id))


@app.route('/admin/projects/<int:project_id>/backup')
def admin_project_backup(project_id):
    if not get_admin_id():
        return redirect(url_for('admin_login'))
    project = panel_db.get_project(PORTAL_ROOT, project_id)
    if not project:
        abort(404)
    folder_abs = os.path.join(STACK_ROOT, project['folder']) if project.get('folder') else None
    volumes = panel_db.project_volumes(project)
    if not (folder_abs and os.path.isdir(folder_abs)) and not volumes:
        flash('Este proyecto no tiene carpeta ni volúmenes registrados para respaldar.', 'error')
        return redirect(url_for('admin_projects'))

    manifest = None
    if project.get('template'):
        manifest = {
            'template': project['template'],
            'project_key': project['project_key'],
            'name': project['name'],
            'secrets': panel_db.project_secrets(project),
        }
    data = backup_control.build_backup(folder_abs, volumes, manifest=manifest)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    filename = f"{project['project_key']}-{stamp}.tar.gz"
    try:
        with open(os.path.join(BACKUPS_DIR, filename), 'wb') as fh:
            fh.write(data)
    except OSError:
        pass
    panel_db.log_action(PORTAL_ROOT, current_admin_email(), 'backup', project['name'])
    response = make_response(data)
    response.headers['Content-Type'] = 'application/gzip'
    response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@app.route('/admin/projects/<int:project_id>')
def admin_project_detail(project_id):
    gate = _require_admin()
    if gate:
        return gate
    project = panel_db.get_project(PORTAL_ROOT, project_id)
    if not project:
        abort(404)
    project['url'] = next((p['url'] for p in load_projects() if p['db_id'] == project_id), None)
    containers = panel_db.project_containers(project)
    folder_abs = os.path.join(STACK_ROOT, project['folder']) if project.get('folder') else None
    has_git = bool(folder_abs and os.path.isdir(os.path.join(folder_abs, '.git')))
    has_env = bool(folder_abs and os.path.isfile(os.path.join(folder_abs, '.env')))
    return render_template(
        'admin_project_detail.html',
        project=project,
        containers=containers,
        docker_status=containers_status(containers) if containers else None,
        databases=panel_db.list_databases(PORTAL_ROOT, project_id),
        has_git=has_git,
        has_env=has_env,
        can_clone=bool(project.get('template')),
        has_php_config=project.get('template') == 'wordpress',
        is_wordpress=_is_wordpress(project),
        wp_credentials={k: v for k, v in panel_db.project_secrets(project).items() if k.startswith('wp_admin_')},
        repos=panel_db.project_repos(project),
        sftp_users=panel_db.list_sftp_users(PORTAL_ROOT, project_id),
        sftp_host=get_public_host(),
        sftp_port=sftp_control.SFTP_PORT,
    )


@app.route('/admin/projects/<int:project_id>/git-pull-repo/<role>', methods=['POST'])
def admin_project_git_pull_repo(project_id, role):
    if not get_admin_id():
        return redirect(url_for('admin_login'))
    project = panel_db.get_project(PORTAL_ROOT, project_id)
    if not project or not project.get('folder'):
        abort(404)
    role = re.sub(r'[^a-z0-9-]+', '', (role or '').lower())
    repo_folder = os.path.join(STACK_ROOT, project['folder'], role)
    if not os.path.isdir(repo_folder):
        abort(404)
    ok, output = project_git.pull_repo(repo_folder)
    if ok:
        panel_db.log_action(PORTAL_ROOT, current_admin_email(), 'git_pull', f"{project['name']}/{role}")
        flash(f'"{role}" actualizado: {output or "ya estaba al día."}', 'success')
    else:
        flash(f'git pull falló en "{role}": {output}', 'error')
    return redirect(url_for('admin_project_detail', project_id=project_id))


@app.route('/admin/projects/<int:project_id>/logs')
def admin_project_logs(project_id):
    gate = _require_admin()
    if gate:
        return gate
    project = panel_db.get_project(PORTAL_ROOT, project_id)
    if not project:
        abort(404)
    containers = panel_db.project_containers(project)
    selected = request.args.get('container') or (containers[0] if containers else None)
    logs, error = (None, 'Este proyecto no tiene contenedores vinculados.')
    if selected:
        logs, error = container_logs(selected, tail=300)
    return render_template(
        'admin_project_logs.html', project=project, containers=containers,
        selected=selected, logs=logs, error=error,
    )


@app.route('/admin/projects/<int:project_id>/env', methods=['GET', 'POST'])
def admin_project_env(project_id):
    gate = _require_admin()
    if gate:
        return gate
    project = panel_db.get_project(PORTAL_ROOT, project_id)
    if not project or not project.get('folder'):
        abort(404)
    local_folder = os.path.join(files_control.html_root(STACK_ROOT), project['folder'][5:])
    env_path = os.path.join(local_folder, '.env')
    error = None
    if request.method == 'POST':
        lines = []
        keys = request.form.getlist('key')
        values = request.form.getlist('value')
        for key, value in zip(keys, values):
            key = key.strip()
            if not key:
                continue
            if not re.match(r'^[A-Za-z_][A-Za-z0-9_]*$', key):
                error = f'Nombre de variable inválido: {key}'
                continue
            lines.append(f'{key}={value}')
        if not error:
            try:
                with open(env_path, 'w', encoding='utf-8') as fh:
                    fh.write('\n'.join(lines) + '\n')
                panel_db.log_action(PORTAL_ROOT, current_admin_email(), 'env_edit', project['name'])
                flash('Variables de entorno guardadas. Reinicia el proyecto para que tomen efecto.', 'success')
                return redirect(url_for('admin_project_env', project_id=project_id))
            except OSError as exc:
                error = str(exc)

    env_vars = []
    if os.path.isfile(env_path):
        with open(env_path, encoding='utf-8') as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, value = line.split('=', 1)
                env_vars.append((key, value))
    return render_template('admin_project_env.html', project=project, env_vars=env_vars, error=error)


@app.route('/admin/projects/<int:project_id>/git-pull', methods=['POST'])
def admin_project_git_pull(project_id):
    if not get_admin_id():
        return redirect(url_for('admin_login'))
    project = panel_db.get_project(PORTAL_ROOT, project_id)
    if not project or not project.get('folder'):
        abort(404)
    local_folder = os.path.join(files_control.html_root(STACK_ROOT), project['folder'][5:])
    if not os.path.isdir(os.path.join(local_folder, '.git')):
        flash('Esta carpeta no es un repositorio Git.', 'error')
        return redirect(url_for('admin_project_detail', project_id=project_id))
    try:
        result = subprocess.run(
            ['git', 'pull', '--ff-only'], cwd=local_folder, capture_output=True, text=True, timeout=120,
        )
        output = (result.stdout or '') + (result.stderr or '')
        panel_db.log_action(PORTAL_ROOT, current_admin_email(), 'git_pull', project['name'])
        if result.returncode == 0:
            flash(f'git pull: {output.strip()[-300:]}', 'success')
        else:
            flash(f'git pull falló: {output.strip()[-300:]}', 'error')
    except (subprocess.SubprocessError, OSError) as exc:
        flash(f'No se pudo correr git pull: {exc}', 'error')
    return redirect(url_for('admin_project_detail', project_id=project_id))


@app.route('/admin/projects/<int:project_id>/wp-login', methods=['POST'])
def admin_project_wp_login(project_id):
    """Acceso directo a wp-admin: enlace firmado, de un solo uso y 60 s de vida."""
    if not get_admin_id():
        return redirect(url_for('admin_login'))
    project = panel_db.get_project(PORTAL_ROOT, project_id)
    local_folder = _project_local_folder(project)
    if not project or not wp_sso.is_wordpress(local_folder):
        abort(404)
    url = next((p['url'] for p in load_projects() if p['db_id'] == project_id), None)
    if not url:
        flash('Este proyecto no tiene una dirección pública para abrir WordPress.', 'error')
        return redirect(url_for('admin_project_detail', project_id=project_id))
    try:
        key = wp_sso.ensure(local_folder)
    except OSError as exc:
        flash(f'No se pudo preparar el acceso directo: {exc}', 'error')
        return redirect(url_for('admin_project_detail', project_id=project_id))
    user = panel_db.project_secrets(project).get('wp_admin_user')
    panel_db.log_action(PORTAL_ROOT, current_admin_email(), 'wp_login', project['name'])
    return redirect(wp_sso.login_url(url, key, user))


@app.route('/admin/projects/<int:project_id>/clone', methods=['POST'])
def admin_project_clone(project_id):
    if not get_admin_id():
        return redirect(url_for('admin_login'))
    project = panel_db.get_project(PORTAL_ROOT, project_id)
    if not project or not project.get('template'):
        flash('Solo se pueden clonar proyectos instalados con "Instalar app".', 'error')
        return redirect(url_for('admin_projects'))

    new_name = (request.form.get('name') or f"{project['name']} copia").strip()
    used_ports = [p.get('port') for p in panel_db.list_projects_raw(PORTAL_ROOT)]
    port = app_templates.pick_free_port(used_ports)
    if not port:
        flash('No hay puertos libres disponibles.', 'error')
        return redirect(url_for('admin_project_detail', project_id=project_id))

    key = panel_db.reserve_key(PORTAL_ROOT, new_name)
    src_local = os.path.join(files_control.html_root(STACK_ROOT), project['folder'][5:])
    local_folder, host_folder = _project_paths(key)
    try:
        shutil.copytree(src_local, local_folder)
    except OSError as exc:
        flash(f'No se pudo copiar los archivos: {exc}', 'error')
        return redirect(url_for('admin_project_detail', project_id=project_id))

    containers, volumes, secrets, error = app_templates.install(project['template'], key, local_folder, host_folder, port)
    if error:
        flash(f'Archivos copiados, pero no se pudo levantar el clon: {error}', 'error')
        return redirect(url_for('admin_project_detail', project_id=project_id))
    if wp_sso.is_wordpress(local_folder):
        wp_sso.ensure(local_folder, rotate=True)   # el clon no comparte la clave de acceso del original
        old_secrets = panel_db.project_secrets(project)
        for field in ('wp_admin_user', 'wp_admin_password'):
            if old_secrets.get(field):
                secrets = {**(secrets or {}), field: old_secrets[field]}

    panel_db.insert_project(
        PORTAL_ROOT, key, new_name, project.get('description', ''), 'port', port, None, '/', None,
        folder=f'html/{key}', containers=containers, volumes=volumes, template=project['template'], secrets=secrets,
    )
    panel_db.log_action(PORTAL_ROOT, current_admin_email(), 'project_clone', f"{project['name']} -> {new_name}")
    flash(f'"{new_name}" creado como copia, corriendo en el puerto {port}.', 'success')
    return redirect(url_for('admin_projects'))


@app.route('/admin/projects/<int:project_id>/database', methods=['GET', 'POST'])
def admin_project_database(project_id):
    gate = _require_admin()
    if gate:
        return gate
    project = panel_db.get_project(PORTAL_ROOT, project_id)
    if not project:
        abort(404)
    error = None
    if request.method == 'POST':
        db = panel_db.add_database(
            PORTAL_ROOT, project_id,
            request.form.get('engine', 'mysql'),
            request.form.get('host', '').strip(),
            request.form.get('port', '').strip() or (3306 if request.form.get('engine') == 'mysql' else 5432),
            request.form.get('username', '').strip(),
            request.form.get('password', ''),
            request.form.get('dbname', '').strip(),
        )
        ok, err = db_viewer.test_connection(db)
        if ok:
            flash('Conexión agregada y verificada.', 'success')
        else:
            flash(f'Conexión agregada, pero no se pudo verificar ahora mismo: {err}', 'error')
        return redirect(url_for('admin_project_database', project_id=project_id))
    template_label = None
    if project.get('template'):
        template_label = app_templates.TEMPLATES.get(project['template'], {}).get('label', project['template'])
    return render_template(
        'admin_project_database.html', project=project,
        databases=panel_db.list_databases(PORTAL_ROOT, project_id), error=error,
        template_label=template_label,
    )


@app.route('/admin/projects/<int:project_id>/database/autodetect', methods=['POST'])
def admin_project_database_autodetect(project_id):
    if not get_admin_id():
        return redirect(url_for('admin_login'))
    project = panel_db.get_project(PORTAL_ROOT, project_id)
    if not project or not project.get('folder'):
        flash('Este proyecto no tiene carpeta asociada; agrega la conexión manualmente.', 'error')
        return redirect(url_for('admin_project_database', project_id=project_id))
    local_folder = os.path.join(files_control.html_root(STACK_ROOT), project['folder'][5:])
    candidate, error = db_autodetect.autodetect(local_folder, project=project)
    if not candidate:
        flash(error, 'error')
        return redirect(url_for('admin_project_database', project_id=project_id))
    panel_db.add_database(
        PORTAL_ROOT, project_id, candidate['engine'], candidate['host'], candidate['port'],
        candidate['username'], candidate['password'], candidate['dbname'],
    )
    panel_db.log_action(PORTAL_ROOT, current_admin_email(), 'db_autodetect', f"{project['name']}: {candidate['host']}:{candidate['port']}")
    flash(f"Conectado automáticamente a {candidate['dbname']} ({candidate['host']}:{candidate['port']}).", 'success')
    return redirect(url_for('admin_project_database', project_id=project_id))


@app.route('/admin/projects/<int:project_id>/php-config', methods=['GET', 'POST'])
def admin_project_php_config(project_id):
    gate = _require_admin()
    if gate:
        return gate
    project = panel_db.get_project(PORTAL_ROOT, project_id)
    if not project or project.get('template') != 'wordpress' or not project.get('folder'):
        abort(404)
    local_folder = os.path.join(files_control.html_root(STACK_ROOT), project['folder'][5:])
    host_folder = os.path.join(HOST_STACK_ROOT, project['folder'])
    app_container = f"{project['project_key']}-app"

    error = None
    if request.method == 'POST':
        values = {key: request.form.get(key, '') for key in app_templates.DEFAULT_PHP_CONFIG}
        ok, err = app_templates.save_php_config(app_container, local_folder, host_folder, values)
        if ok:
            panel_db.log_action(PORTAL_ROOT, current_admin_email(), 'php_config', project['name'])
            flash('Configuración de PHP guardada. El contenedor se reinició para aplicarla.', 'success')
            return redirect(url_for('admin_project_php_config', project_id=project_id))
        error = err
        flash(f'No se pudo guardar: {err}', 'error')

    values = app_templates.read_php_config(local_folder)
    return render_template(
        'admin_project_php_config.html', project=project, values=values, error=error,
    )


@app.route('/admin/projects/<int:project_id>/database/<int:db_id>/delete', methods=['POST'])
def admin_project_database_delete(project_id, db_id):
    if not get_admin_id():
        return redirect(url_for('admin_login'))
    db = panel_db.get_database(PORTAL_ROOT, db_id)
    if not db or db['project_id'] != project_id:
        abort(404)
    panel_db.delete_database(PORTAL_ROOT, db_id)
    flash('Conexión eliminada.', 'success')
    return redirect(url_for('admin_project_database', project_id=project_id))


@app.route('/admin/projects/<int:project_id>/database/<int:db_id>/toggle-write', methods=['POST'])
def admin_project_database_toggle_write(project_id, db_id):
    if not get_admin_id():
        return redirect(url_for('admin_login'))
    db = panel_db.get_database(PORTAL_ROOT, db_id)
    if not db or db['project_id'] != project_id:
        abort(404)
    panel_db.set_database_allow_write(PORTAL_ROOT, db_id, not db['allow_write'])
    return redirect(url_for('admin_project_database', project_id=project_id))


@app.route('/admin/projects/<int:project_id>/database/<int:db_id>/view', methods=['GET', 'POST'])
def admin_project_database_view(project_id, db_id):
    gate = _require_admin()
    if gate:
        return gate
    project = panel_db.get_project(PORTAL_ROOT, project_id)
    db = panel_db.get_database(PORTAL_ROOT, db_id)
    if not project or not db or db['project_id'] != project_id:
        abort(404)

    columns, rows, error = None, None, None
    sql = request.form.get('sql', '') if request.method == 'POST' else request.args.get('sql', '')
    table = request.args.get('table', '')

    if request.method == 'POST' and sql:
        columns, rows, error = db_viewer.run_query(db, sql, allow_write=bool(db['allow_write']))
        if error is None:
            is_write = bool(re.match(r'^\s*(insert|update|delete)\b', sql, re.IGNORECASE))
            panel_db.log_action(
                PORTAL_ROOT, current_admin_email(),
                'db_query_write' if is_write else 'db_query', f"{project['name']}: {sql[:200]}",
            )
    elif table:
        columns, rows, error = db_viewer.browse_table(db, table)
        sql = f'SELECT * FROM {table} LIMIT 100'

    tables, tables_error = db_viewer.list_tables(db)
    return render_template(
        'admin_project_database_view.html', project=project, db=db,
        tables=tables, tables_error=tables_error,
        columns=columns, rows=rows, error=error, sql=sql, table=table,
    )


@app.route('/admin/projects/scan')
def admin_projects_scan():
    gate = _require_admin()
    if gate:
        return gate
    registered = {p['folder'] for p in panel_db.list_projects_raw(PORTAL_ROOT) if p.get('folder')}
    candidates = project_scan.scan_candidates(STACK_ROOT, registered)
    return render_template('admin_project_scan.html', candidates=candidates)


@app.route('/admin/projects/scan/import', methods=['POST'])
def admin_projects_scan_import():
    if not get_admin_id():
        return redirect(url_for('admin_login'))

    folder = request.form.get('folder', '').strip()
    name = request.form.get('name', '').strip()
    port_raw = request.form.get('port', '').strip()
    containers = [c.strip() for c in request.form.get('containers', '').split(',') if c.strip()]

    registered = {p['folder'] for p in panel_db.list_projects_raw(PORTAL_ROOT) if p.get('folder')}
    if not folder or not folder.startswith('html/') or '..' in folder:
        abort(400)
    if folder in registered:
        flash('Ese proyecto ya estaba registrado.', 'error')
        return redirect(url_for('admin_projects_scan'))
    if not name:
        flash('El nombre es obligatorio.', 'error')
        return redirect(url_for('admin_projects_scan'))
    try:
        port = int(port_raw)
        if not (1 <= port <= 65535):
            raise ValueError
    except ValueError:
        flash('El puerto es obligatorio y debe ser un número válido.', 'error')
        return redirect(url_for('admin_projects_scan'))

    key = panel_db.reserve_key(PORTAL_ROOT, name)
    panel_db.insert_project(
        PORTAL_ROOT, key, name, request.form.get('description', ''),
        'port', port, None, '/', None,
        folder=folder, containers=containers, volumes=[],
    )
    flash(f'{name} agregado al portal.', 'success')
    return redirect(url_for('admin_projects'))


@app.route('/admin/projects/install')
def admin_project_install_index():
    gate = _require_admin()
    if gate:
        return gate
    return render_template('admin_project_install.html', templates=app_templates.TEMPLATES)


@app.route('/admin/projects/install/<template_key>', methods=['POST'])
def admin_project_install(template_key):
    if not get_admin_id():
        return redirect(url_for('admin_login'))
    if template_key not in app_templates.TEMPLATES:
        abort(404)
    name = request.form.get('name', '').strip()
    if not name:
        flash('El nombre es obligatorio.', 'error')
        return redirect(url_for('admin_project_install_index'))

    used_ports = [p.get('port') for p in panel_db.list_projects_raw(PORTAL_ROOT)]
    port = app_templates.pick_free_port(used_ports)
    if not port:
        flash('No hay puertos libres disponibles en el rango reservado.', 'error')
        return redirect(url_for('admin_project_install_index'))

    key = panel_db.reserve_key(PORTAL_ROOT, name)
    local_folder, host_folder = _project_paths(key)
    containers, volumes, secrets, error = app_templates.install(template_key, key, local_folder, host_folder, port)
    if error:
        flash(f'No se pudo instalar {name}: {error}', 'error')
        return redirect(url_for('admin_project_install_index'))

    wp_warning = None
    if template_key == 'wordpress':
        # Deja el WordPress instalado (título, admin, idioma) para poder entrar
        # directo desde el panel sin pasar por el asistente.
        wp_sso.ensure(local_folder)
        wp_user = f'{key}-admin'
        wp_password, wp_warning = wp_sso.complete_install(
            [f'http://{key}-app', f'http://host.docker.internal:{port}'],
            f'http://{get_public_host()}:{port}/', name, current_admin_email() or get_certbot_email(), wp_user,
        )
        if wp_password:
            secrets = {**(secrets or {}), 'wp_admin_user': wp_user, 'wp_admin_password': wp_password}

    panel_db.insert_project(
        PORTAL_ROOT, key, name, app_templates.TEMPLATES[template_key]['label'],
        'port', port, None, '/', None,
        folder=f'html/{key}', containers=containers, volumes=volumes,
        template=template_key, secrets=secrets,
    )
    panel_db.log_action(PORTAL_ROOT, current_admin_email(), 'app_install', f'{template_key}: {name}')
    flash(f'{name} instalado y en marcha en el puerto {port}.', 'success')
    if wp_warning:
        flash(f'WordPress quedó en marcha, pero falta terminar su instalación desde el navegador: {wp_warning}', 'error')
    return redirect(url_for('admin_projects'))


@app.route('/admin/projects/from-git', methods=['GET', 'POST'])
def admin_project_from_git():
    gate = _require_admin()
    if gate:
        return gate
    if request.method == 'GET':
        return render_template('admin_project_from_git.html')

    name = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()
    urls = request.form.getlist('repo_url')
    branches = request.form.getlist('repo_branch')
    roles = request.form.getlist('repo_role')
    ports = request.form.getlist('repo_port')
    commands = request.form.getlist('repo_command')
    dockerfiles = request.form.getlist('repo_dockerfile')
    try:
        public_index = int(request.form.get('public_repo', 0))
    except ValueError:
        public_index = 0

    if not name:
        flash('El nombre del proyecto es obligatorio.', 'error')
        return redirect(url_for('admin_project_from_git'))

    repos = []
    seen_roles = set()
    for i, url in enumerate(urls):
        url = (url or '').strip()
        if not url:
            continue
        role = (roles[i] if i < len(roles) else '').strip() or f'repo{len(repos) + 1}'
        role = re.sub(r'[^a-z0-9-]+', '-', role.lower()).strip('-') or f'repo{len(repos) + 1}'
        if role in seen_roles:
            flash(f'El rol "{role}" está repetido; usá nombres distintos para cada repositorio.', 'error')
            return redirect(url_for('admin_project_from_git'))
        seen_roles.add(role)
        port_raw = (ports[i] if i < len(ports) else '').strip()
        repos.append({
            'url': url,
            'branch': (branches[i] if i < len(branches) else '').strip() or None,
            'role': role,
            'container_port': int(port_raw) if port_raw.isdigit() else None,
            'command': (commands[i] if i < len(commands) else '').strip() or None,
            'dockerfile': (dockerfiles[i] if i < len(dockerfiles) else '').strip() or None,
        })

    if not repos:
        flash('Agregá al menos un repositorio con su URL.', 'error')
        return redirect(url_for('admin_project_from_git'))
    if public_index >= len(repos):
        public_index = 0

    used_ports = set(p.get('port') for p in panel_db.list_projects_raw(PORTAL_ROOT) if p.get('port'))
    public_port = app_templates.pick_free_port(used_ports)
    if not public_port:
        flash('No hay puertos libres disponibles.', 'error')
        return redirect(url_for('admin_project_from_git'))

    key = panel_db.reserve_key(PORTAL_ROOT, name)
    local_folder, host_folder = _project_paths(key)
    repos_result, containers, error, warnings = project_git.create_from_repos(
        local_folder, host_folder, key, repos, public_index, public_port,
    )
    if error:
        flash(f'No se pudo crear "{name}": {error}', 'error')
        return redirect(url_for('admin_project_from_git'))

    panel_db.insert_project(
        PORTAL_ROOT, key, name, description, 'port', public_port, None, '/', None,
        folder=f'html/{key}', containers=containers, volumes=[], template=None, secrets={}, repos=repos_result,
    )
    panel_db.log_action(PORTAL_ROOT, current_admin_email(), 'project_from_git', f'{name} ({len(repos)} repo(s))')
    for warning in warnings:
        flash(warning, 'error')
    flash(f'"{name}" creado desde Git, corriendo en el puerto {public_port}.', 'success')
    return redirect(url_for('admin_projects'))


@app.route('/admin/projects/restore', methods=['GET', 'POST'])
def admin_project_restore():
    gate = _require_admin()
    if gate:
        return gate
    error = None
    if request.method == 'POST':
        upload = request.files.get('backup_file')
        name = request.form.get('name', '').strip()
        if not upload or not upload.filename:
            error = 'Selecciona un archivo de backup (.tar.gz).'
        elif not name:
            error = 'El nombre del nuevo proyecto es obligatorio.'
        else:
            data = upload.read()
            manifest = backup_control.read_backup_manifest(data)
            if not manifest or manifest.get('template') not in app_templates.TEMPLATES:
                error = (
                    'Este backup no tiene una plantilla reconocida (no fue creado con "Instalar app"), '
                    'así que no puedo recrear los contenedores automáticamente.'
                )
            else:
                used_ports = [p.get('port') for p in panel_db.list_projects_raw(PORTAL_ROOT)]
                port = app_templates.pick_free_port(used_ports)
                if not port:
                    error = 'No hay puertos libres disponibles en el rango reservado.'
                else:
                    key = panel_db.reserve_key(PORTAL_ROOT, name)
                    local_folder, host_folder = _project_paths(key)
                    backup_control.restore_backup(data, local_folder)
                    containers, volumes, secrets, install_error = app_templates.install(
                        manifest['template'], key, local_folder, host_folder, port, manifest.get('secrets'),
                    )
                    if install_error:
                        error = f'Se restauraron los archivos, pero no se pudo levantar el contenedor: {install_error}'
                    else:
                        panel_db.insert_project(
                            PORTAL_ROOT, key, name, request.form.get('description', ''),
                            'port', port, None, '/', None,
                            folder=f'html/{key}', containers=containers, volumes=volumes,
                            template=manifest['template'], secrets=secrets,
                        )
                        panel_db.log_action(PORTAL_ROOT, current_admin_email(), 'project_restore', name)
                        flash(f'Proyecto "{name}" restaurado y en marcha en el puerto {port}.', 'success')
                        return redirect(url_for('admin_projects'))
    return render_template('admin_project_restore.html', error=error)


@app.route('/admin/files/', defaults={'subpath': ''}, methods=['GET', 'POST'])
@app.route('/admin/files/<path:subpath>', methods=['GET', 'POST'])
def admin_files(subpath):
    gate = _require_admin()
    if gate:
        return gate
    try:
        abs_path = files_control.safe_join(STACK_ROOT, subpath)
    except files_control.PathError:
        abort(404)
    if not os.path.exists(abs_path):
        abort(404)

    if request.method == 'POST':
        try:
            files_control.write_file(STACK_ROOT, subpath, request.form.get('content', ''))
            flash('Archivo guardado.', 'success')
        except files_control.PathError as exc:
            flash(str(exc), 'error')
        return redirect(url_for('admin_files', subpath=subpath))

    if os.path.isdir(abs_path):
        entries = files_control.list_dir(STACK_ROOT, subpath)
        resp = make_response(render_template(
            'admin_files.html', mode='dir', subpath=subpath, entries=entries,
            parent=files_control.parent_of(subpath),
        ))
        return _no_cache(resp)

    content, file_error = None, None
    try:
        content = files_control.read_file(STACK_ROOT, subpath)
    except files_control.PathError as exc:
        file_error = str(exc)
    resp = make_response(render_template(
        'admin_files.html', mode='file', subpath=subpath, content=content, file_error=file_error,
        parent=files_control.parent_of(subpath),
    ))
    return _no_cache(resp)


def _project_owning_subpath(subpath):
    """Encuentra el proyecto cuya carpeta (html/<folder>) contiene subpath,
    para saber qué contenedores detener antes de borrar un archivo suyo."""
    subpath = (subpath or '').strip('/')
    for project in panel_db.list_projects_raw(PORTAL_ROOT):
        folder = project.get('folder') or ''
        if not folder.startswith('html/'):
            continue
        folder_rel = folder[5:].strip('/')
        if not folder_rel:
            continue
        if subpath == folder_rel or subpath.startswith(folder_rel + '/'):
            return project
    return None


def _stop_project_if_running(subpath):
    """Si subpath pertenece a un proyecto con contenedores en marcha, los
    detiene antes de una operación destructiva sobre sus archivos."""
    project = _project_owning_subpath(subpath)
    if not project:
        return True, None
    containers = panel_db.project_containers(project)
    if not containers or not containers_status(containers).get('running'):
        return True, None
    ok, msg = stop_containers(containers)
    if not ok:
        return False, f'No se pudo detener "{project["name"]}": {msg}'
    panel_db.set_desired_state(PORTAL_ROOT, project['id'], 'stopped')
    panel_db.log_action(PORTAL_ROOT, current_admin_email(), 'project_stop', project['name'])
    return True, None


@app.route('/admin/files/<path:subpath>/delete', methods=['POST'])
def admin_files_delete(subpath):
    gate = _require_admin()
    if gate:
        return gate
    try:
        abs_path = files_control.safe_join(STACK_ROOT, subpath)
    except files_control.PathError:
        abort(404)
    if not os.path.exists(abs_path):
        abort(404)
    is_dir = os.path.isdir(abs_path)

    ok, err = _stop_project_if_running(subpath)
    if not ok:
        flash(err, 'error')
        return redirect(url_for('admin_files', subpath=files_control.parent_of(subpath)))

    try:
        if is_dir:
            files_control.delete_dir(STACK_ROOT, subpath)
            flash('Carpeta eliminada.', 'success')
            panel_db.log_action(PORTAL_ROOT, current_admin_email(), 'folder_delete', subpath)
        else:
            files_control.delete_file(STACK_ROOT, subpath)
            flash('Archivo eliminado.', 'success')
            panel_db.log_action(PORTAL_ROOT, current_admin_email(), 'file_delete', subpath)
    except files_control.PathError as exc:
        flash(str(exc), 'error')
    return redirect(url_for('admin_files', subpath=files_control.parent_of(subpath)))


@app.route('/admin/projects/<int:project_id>/wipe', methods=['POST'])
def admin_project_wipe(project_id):
    gate = _require_admin()
    if gate:
        return gate
    project = panel_db.get_project(PORTAL_ROOT, project_id)
    if not project:
        abort(404)

    containers = panel_db.project_containers(project)
    volumes = panel_db.project_volumes(project)
    folder = project.get('folder') or ''

    if containers:
        ok, msg = remove_containers(containers)
        if not ok:
            flash(f'No se pudieron eliminar los contenedores de "{project["name"]}": {msg}', 'error')
            return redirect(url_for('admin_project_detail', project_id=project_id))

    if volumes:
        ok, msg = remove_volumes(volumes)
        if not ok:
            flash(
                f'Contenedores de "{project["name"]}" eliminados, pero fallaron los volúmenes: {msg}',
                'error',
            )
            return redirect(url_for('admin_project_detail', project_id=project_id))

    if folder.startswith('html/'):
        folder_rel = folder[5:].strip('/')
        if folder_rel:
            try:
                files_control.delete_dir(STACK_ROOT, folder_rel)
            except files_control.PathError:
                pass

    panel_db.delete_project(PORTAL_ROOT, project_id)
    panel_db.log_action(PORTAL_ROOT, current_admin_email(), 'project_wipe', project['name'])
    flash(f'"{project["name"]}" eliminado por completo: contenedores, volúmenes y archivos.', 'success')
    return redirect(url_for('admin_projects'))


def _panel_port():
    host = request.host
    if host.rsplit(':', 1)[-1].isdigit() and not host.endswith(']'):
        return int(host.rsplit(':', 1)[1])
    return 443 if request.scheme == 'https' else 80


@app.route('/admin/firewall')
def admin_firewall():
    gate = _require_admin()
    if gate:
        return gate
    if firewall_rules.expire_if_needed(PORTAL_ROOT):
        flash('El último cambio de puertos no se confirmó a tiempo y se revirtió solo.', 'error')
    guard_status, guard_error = guard_client.status()
    published, docker_err = list_published_ports()
    listening = (guard_status or {}).get('listening') or []
    resp = make_response(render_template(
        'admin_firewall.html',
        rows=firewall_rules.port_table(PORTAL_ROOT, published, listening),
        policies=firewall_rules.POLICIES,
        pending=firewall_rules.get_pending(PORTAL_ROOT),
        confirm_seconds=firewall_rules.CONFIRM_SECONDS,
        guard=guard_status,
        guard_error=guard_error,
        docker_err=docker_err,
        my_ip=g.client_ip,
        panel_port=_panel_port(),
    ))
    return _no_cache(resp)


@app.route('/admin/firewall/apply', methods=['POST'])
def admin_firewall_apply():
    gate = _require_admin()
    if gate:
        return gate
    rules, error = firewall_rules.parse_form(request.form)
    if not error:
        guard_status, _ = guard_client.status()
        static_allow = (guard_status or {}).get('static_allow') or []
        error = firewall_rules.lockout_error(PORTAL_ROOT, rules, g.client_ip, _panel_port(), static_allow)
    if error:
        flash(error, 'error')
        return redirect(url_for('admin_firewall'))
    firewall_rules.propose(PORTAL_ROOT, rules, current_admin_email())
    panel_db.log_action(PORTAL_ROOT, current_admin_email(), 'fw_proposed', firewall_rules.describe(rules))
    flash(
        f'Cambios aplicados a prueba. Si sigues viendo esta página, confírmalos antes de '
        f'{firewall_rules.CONFIRM_SECONDS // 60} minutos; si no, se revierten solos.',
        'success',
    )
    return redirect(url_for('admin_firewall'))


@app.route('/admin/firewall/confirm', methods=['POST'])
def admin_firewall_confirm():
    gate = _require_admin()
    if gate:
        return gate
    if firewall_rules.confirm(PORTAL_ROOT):
        panel_db.log_action(
            PORTAL_ROOT, current_admin_email(), 'fw_confirmed',
            firewall_rules.describe(firewall_rules.get_committed(PORTAL_ROOT)),
        )
        flash('Cambios de puertos confirmados.', 'success')
    else:
        flash('No hay cambios pendientes: el plazo ya venció y se revirtieron.', 'error')
    return redirect(url_for('admin_firewall'))


@app.route('/admin/firewall/revert', methods=['POST'])
def admin_firewall_revert():
    gate = _require_admin()
    if gate:
        return gate
    firewall_rules.revert(PORTAL_ROOT)
    panel_db.log_action(PORTAL_ROOT, current_admin_email(), 'fw_reverted', 'revertido a mano')
    flash('Cambios descartados: se volvió a las reglas anteriores.', 'success')
    return redirect(url_for('admin_firewall'))


_BAN_DURATIONS = {
    '60': ('1 hora', 60),
    '1440': ('24 horas', 1440),
    '10080': ('7 días', 10080),
    '43200': ('30 días', 43200),
    'perm': ('Permanente', None),
}


@app.route('/admin/security')
def admin_security():
    gate = _require_admin()
    if gate:
        return gate
    ip = g.client_ip
    guard_status, guard_error = guard_client.status()
    service = request.args.get('service') or None
    if service not in security.SERVICE_LABELS:
        service = None
    def _table_args(prefix, default_sort):
        try:
            page = int(request.args.get(prefix + 'page', 1))
            per = int(request.args.get(prefix + 'per', security.PAGE_SIZES[0]))
        except ValueError:
            page, per = 1, security.PAGE_SIZES[0]
        return {
            'q': request.args.get(prefix + 'q', ''),
            'sort': request.args.get(prefix + 'sort', default_sort),
            'direction': request.args.get(prefix + 'dir', 'desc'),
            'page': page,
            'per_page': per,
        }

    bans = security.query_bans(PORTAL_ROOT, active=True, **_table_args('b', 'created_at'))
    history = security.query_bans(PORTAL_ROOT, active=False, **_table_args('h', 'created_at'))
    result = request.args.get('eres', '')
    events = security.query_events(
        PORTAL_ROOT, service=service, result=result if result in ('ok', 'fail') else '',
        **_table_args('e', 'ts'),
    )
    # Estado de las tres tablas en la URL: cada enlace de orden/página cambia
    # solo lo suyo y conserva el resto.
    table_params = {'service': service, 'eres': events['result']}
    for prefix, t, default_sort in (('b', bans, 'created_at'), ('h', history, 'created_at'), ('e', events, 'ts')):
        table_params.update({
            prefix + 'q': t['q'],
            prefix + 'sort': t['sort'] if t['sort'] != default_sort else None,
            prefix + 'dir': t['direction'] if t['direction'] != 'desc' else None,
            prefix + 'per': t['per_page'] if t['per_page'] != security.PAGE_SIZES[0] else None,
            prefix + 'page': t['page'] if t['page'] != 1 else None,
        })
    table_params = {k: v for k, v in table_params.items() if v}
    resp = make_response(render_template(
        'admin_security.html',
        summary=security.summary(PORTAL_ROOT),
        bans=bans,
        history=history,
        table_params=table_params,
        allowlist=security.list_allowlist(PORTAL_ROOT),
        events=events,
        service_filter=service,
        service_labels=security.SERVICE_LABELS,
        jails=security.get_jails(PORTAL_ROOT),
        jail_modes=security.JAIL_MODES,
        jail_stats=security.jail_stats(PORTAL_ROOT),
        chart=security.attack_chart(PORTAL_ROOT),
        rules=security.get_rules(PORTAL_ROOT),
        recidive=security.recidive_examples(security.get_rules(PORTAL_ROOT), security.get_jails(PORTAL_ROOT)),
        recidive_max=security.human_minutes(security.get_rules(PORTAL_ROOT)['sec_ban_max_minutes']),
        durations=_BAN_DURATIONS,
        my_ip=ip,
        my_ip_allowlisted=security.is_allowlisted(PORTAL_ROOT, ip),
        trusted_proxies=os.environ.get('PORTAL_TRUSTED_PROXIES', ''),
        guard=guard_status,
        guard_error=guard_error,
    ))
    return _no_cache(resp)


@app.route('/admin/security/jails', methods=['POST'])
def admin_security_jails():
    gate = _require_admin()
    if gate:
        return gate
    ok, error = security.save_jails(PORTAL_ROOT, request.form)
    if ok:
        detail = ', '.join(
            f'{name}={conf["mode"]}/{conf["max_failures"]}x{conf["window_minutes"]}m/{conf["ban_minutes"]}m'
            for name, conf in security.get_jails(PORTAL_ROOT).items()
        )
        panel_db.log_action(PORTAL_ROOT, current_admin_email(), 'jails_updated', detail)
        flash('Detección automática guardada. El servidor la aplica en unos segundos.', 'success')
    else:
        flash(error, 'error')
    return redirect(url_for('admin_security') + '#deteccion')


@app.route('/admin/security/guard/sync', methods=['POST'])
def admin_security_guard_sync():
    gate = _require_admin()
    if gate:
        return gate
    ok, message = guard_client.sync()
    if ok:
        flash(f'Firewall del servidor sincronizado ({message}).', 'success')
    else:
        flash(f'El agente del firewall no respondió: {message}', 'error')
    return redirect(url_for('admin_security') + '#firewall')


@app.route('/admin/security/rules', methods=['POST'])
def admin_security_rules():
    gate = _require_admin()
    if gate:
        return gate
    ok, error = security.save_rules(PORTAL_ROOT, request.form)
    if ok:
        rules = security.get_rules(PORTAL_ROOT)
        detail = ', '.join(f'{k.removeprefix("sec_")}={v}' for k, v in rules.items())
        panel_db.log_action(PORTAL_ROOT, current_admin_email(), 'security_rules_updated', detail)
        flash('Reglas de seguridad guardadas.', 'success')
    else:
        flash(error, 'error')
    return redirect(url_for('admin_security') + '#reglas')


def _security_back(default_anchor):
    """Vuelve a la misma búsqueda/página de la tabla desde la que se actuó.
    Solo se aceptan rutas de esta misma página (nada de redirecciones abiertas)."""
    back = request.form.get('back', '')
    if not back.startswith('/admin/security') or '//' in back or '\\' in back:
        return url_for('admin_security') + '#' + default_anchor
    return back if '#' in back else back + '#' + default_anchor


@app.route('/admin/security/ban', methods=['POST'])
def admin_security_ban():
    gate = _require_admin()
    if gate:
        return gate
    duration = _BAN_DURATIONS.get(request.form.get('duration', ''), _BAN_DURATIONS['1440'])
    cidr, error = security.manual_ban(
        PORTAL_ROOT,
        request.form.get('ip', ''),
        duration[1],
        (request.form.get('reason') or '').strip(),
        current_admin_email(),
        g.client_ip,
    )
    if cidr:
        panel_db.log_action(PORTAL_ROOT, current_admin_email(), 'ip_banned_manual', f'{cidr} · {duration[0]}')
        flash(f'{cidr} bloqueada ({duration[0].lower()}).', 'success')
    else:
        flash(error, 'error')
    return redirect(_security_back('bloqueos'))


@app.route('/admin/security/ban/<int:ban_id>/lift', methods=['POST'])
def admin_security_lift(ban_id):
    gate = _require_admin()
    if gate:
        return gate
    cidr = security.lift_ban(PORTAL_ROOT, ban_id, current_admin_email())
    if cidr:
        panel_db.log_action(PORTAL_ROOT, current_admin_email(), 'ip_unbanned', cidr)
        flash(f'{cidr} desbloqueada.', 'success')
    return redirect(_security_back('bloqueos'))


@app.route('/admin/security/allow', methods=['POST'])
def admin_security_allow():
    gate = _require_admin()
    if gate:
        return gate
    cidr, error = security.add_allowlist(
        PORTAL_ROOT, request.form.get('ip', ''), request.form.get('note', ''), current_admin_email(),
    )
    if cidr:
        panel_db.log_action(PORTAL_ROOT, current_admin_email(), 'allowlist_added', cidr)
        flash(f'{cidr} agregada a la lista blanca.', 'success')
    else:
        flash(error, 'error')
    return redirect(url_for('admin_security') + '#lista-blanca')


@app.route('/admin/security/allow/<int:entry_id>/delete', methods=['POST'])
def admin_security_allow_delete(entry_id):
    gate = _require_admin()
    if gate:
        return gate
    cidr = security.remove_allowlist(PORTAL_ROOT, entry_id)
    if cidr:
        panel_db.log_action(PORTAL_ROOT, current_admin_email(), 'allowlist_removed', cidr)
        flash(f'{cidr} quitada de la lista blanca.', 'success')
    return redirect(url_for('admin_security') + '#lista-blanca')


@app.route('/admin/security/sessions/revoke', methods=['POST'])
def admin_security_revoke_sessions():
    gate = _require_admin()
    if gate:
        return gate
    revoke_sessions(PORTAL_ROOT)
    login_admin({'id': get_admin_id()}, PORTAL_ROOT)
    panel_db.log_action(PORTAL_ROOT, current_admin_email(), 'sessions_revoked', 'todas menos la actual')
    flash('Se cerraron todas las sesiones abiertas, excepto la tuya.', 'success')
    return redirect(url_for('admin_security') + '#sesiones')


@app.route('/admin/ssh')
def admin_ssh():
    gate = _require_admin()
    if gate:
        return gate
    service = request.args.get('service') or None
    if service not in ssh_access.SERVICES:
        service = None
    try:
        page = int(request.args.get('page', 1))
        per = int(request.args.get('per', ssh_access.PAGE_SIZES[0]))
    except ValueError:
        page, per = 1, ssh_access.PAGE_SIZES[0]
    logins = ssh_access.query_logins(
        PORTAL_ROOT, service=service, q=request.args.get('q', ''),
        only_new=request.args.get('new') == '1', page=page, per_page=per,
    )
    sessions, sessions_error = guard_client.ssh_sessions()
    params = {
        'service': service, 'q': logins['q'], 'new': '1' if logins['only_new'] else None,
        'per': logins['per_page'] if logins['per_page'] != ssh_access.PAGE_SIZES[0] else None,
    }
    resp = make_response(render_template(
        'admin_ssh.html',
        summary=ssh_access.summary(PORTAL_ROOT),
        logins=logins,
        params={k: v for k, v in params.items() if v},
        known=ssh_access.known_ips(PORTAL_ROOT),
        services=ssh_access.SERVICES,
        sessions=sessions,
        sessions_error=sessions_error,
        retention_days=ssh_access.LOGIN_RETENTION_DAYS,
        my_ip=g.client_ip,
    ))
    return _no_cache(resp)


@app.route('/admin/ssh/sessions/terminate', methods=['POST'])
def admin_ssh_terminate():
    gate = _require_admin()
    if gate:
        return gate
    session_id = request.form.get('session_id', '')
    host = request.form.get('host', '')
    ok, message = guard_client.ssh_terminate(session_id)
    if not ok:
        flash(f'No se pudo cerrar la sesión: {message}', 'error')
        return redirect(url_for('admin_ssh') + '#sesiones')
    panel_db.log_action(PORTAL_ROOT, current_admin_email(), 'ssh_session_terminated', message)
    flash(message + '.', 'success')
    if request.form.get('ban') == '1' and host:
        duration = _BAN_DURATIONS['1440']
        cidr, error = security.manual_ban(
            PORTAL_ROOT, host, duration[1], f'Sesión SSH {session_id} cerrada desde el panel',
            current_admin_email(), g.client_ip,
        )
        if cidr:
            panel_db.log_action(PORTAL_ROOT, current_admin_email(), 'ip_banned_manual', f'{cidr} · {duration[0]}')
            flash(f'{cidr} bloqueada (24 horas).', 'success')
        else:
            flash(f'La sesión se cerró, pero no se bloqueó la IP: {error}', 'error')
    return redirect(url_for('admin_ssh') + '#sesiones')


# --- usuarios, claves y sshd del servidor (stackpanel-sshadm) ---------------

SSH_UNLOCK_MINUTES = 10
_SSHD_FIELDS = ('PermitRootLogin', 'PasswordAuthentication', 'MaxAuthTries', 'X11Forwarding')


def _ssh_unlocked_left():
    """Segundos que le quedan al desbloqueo de la gestión SSH (0 = bloqueada)."""
    return max(0, int(session.get('ssh_unlock_until', 0)) - int(time.time()))


def _ssh_require_unlock(back):
    """Las acciones sobre cuentas y sshd piden la contraseña del panel (y 2FA)
    de nuevo: una sesión robada no alcanza para crear un usuario con sudo."""
    if _ssh_unlocked_left():
        return None
    flash(f'Por seguridad, confirma tu identidad para gestionar SSH (vale {SSH_UNLOCK_MINUTES} minutos).', 'error')
    return redirect(back)


def _ssh_back(default):
    back = request.form.get('back', '')
    if not back.startswith('/admin/ssh') or '//' in back or '\\' in back:
        return default
    return back


def _ssh_run(cmd, back, audit, **args):
    ok, message = sshadm_client.run(cmd, **args)
    if ok:
        panel_db.log_action(PORTAL_ROOT, current_admin_email(), audit, message)
        flash(message + '.', 'success')
    else:
        flash(message, 'error')
    return redirect(back), ok


@app.route('/admin/ssh/unlock', methods=['POST'])
def admin_ssh_unlock():
    gate = _require_admin()
    if gate:
        return gate
    back = _ssh_back(url_for('admin_ssh_users'))
    email = current_admin_email()
    admin, _ = authenticate(PORTAL_ROOT, email, request.form.get('password', ''))
    ok = bool(admin) and admin['id'] == get_admin_id()
    if ok and admin['totp_enabled']:
        ok = verify_totp(PORTAL_ROOT, admin['id'], request.form.get('code', ''))
    security.record_attempt(PORTAL_ROOT, g.client_ip, 'reauth', email, ok, request.headers.get('User-Agent', ''))
    if not ok:
        flash('Contraseña o código incorrectos.', 'error')
        return redirect(back)
    session['ssh_unlock_until'] = int(time.time()) + SSH_UNLOCK_MINUTES * 60
    panel_db.log_action(PORTAL_ROOT, email, 'ssh_unlocked', g.client_ip)
    return redirect(back)


@app.route('/admin/ssh/lock', methods=['POST'])
def admin_ssh_lock():
    gate = _require_admin()
    if gate:
        return gate
    session.pop('ssh_unlock_until', None)
    return redirect(_ssh_back(url_for('admin_ssh_users')))


def _ssh_render(template, **ctx):
    resp = make_response(render_template(
        template, unlock_left=_ssh_unlocked_left(), unlock_minutes=SSH_UNLOCK_MINUTES,
        totp_enabled=get_totp_state(PORTAL_ROOT, get_admin_id())[1], my_ip=g.client_ip, **ctx,
    ))
    return _no_cache(resp)


@app.route('/admin/ssh/users')
def admin_ssh_users():
    gate = _require_admin()
    if gate:
        return gate
    status, error = sshadm_client.status()
    return _ssh_render('admin_ssh_users.html', st=status, st_error=error)


@app.route('/admin/ssh/users/<name>')
def admin_ssh_user(name):
    gate = _require_admin()
    if gate:
        return gate
    status, error = sshadm_client.status()
    user = next((u for u in (status or {}).get('users', []) if u['name'] == name), None)
    if status and not user:
        flash(f'No existe el usuario {name} (o es una cuenta del sistema).', 'error')
        return redirect(url_for('admin_ssh_users'))
    sessions, _ = guard_client.ssh_sessions()
    return _ssh_render(
        'admin_ssh_user.html', st=status, st_error=error, user=user, name=name,
        user_sessions=[s for s in (sessions or []) if s['user'] == name],
    )


@app.route('/admin/ssh/users/create', methods=['POST'])
def admin_ssh_user_create():
    gate = _require_admin()
    if gate:
        return gate
    back = url_for('admin_ssh_users')
    gate = _ssh_require_unlock(back)
    if gate:
        return gate
    name = (request.form.get('user') or '').strip()
    password = request.form.get('password', '')
    if password and password != request.form.get('password2', ''):
        flash('Las contraseñas no coinciden.', 'error')
        return redirect(back)
    resp, ok = _ssh_run(
        'create_user', back, 'ssh_user_created', user=name, sudo=request.form.get('sudo') == 'on',
        password=password, key=request.form.get('key', ''), label=request.form.get('label', ''),
    )
    return redirect(url_for('admin_ssh_user', name=name)) if ok else resp


@app.route('/admin/ssh/users/<name>/<action>', methods=['POST'])
def admin_ssh_user_action(name, action):
    gate = _require_admin()
    if gate:
        return gate
    back = url_for('admin_ssh_user', name=name)
    gate = _ssh_require_unlock(back)
    if gate:
        return gate
    f = request.form
    if action == 'add-key':
        return _ssh_run('add_key', back, 'ssh_key_added', user=name, key=f.get('key', ''), label=f.get('label', ''))[0]
    if action == 'remove-key':
        return _ssh_run('remove_key', back, 'ssh_key_removed', user=name, fingerprint=f.get('fingerprint', ''))[0]
    if action == 'password':
        if f.get('password', '') != f.get('password2', ''):
            flash('Las contraseñas no coinciden.', 'error')
            return redirect(back)
        return _ssh_run('set_password', back, 'ssh_password_set', user=name, password=f.get('password', ''))[0]
    if action == 'sudo':
        return _ssh_run('set_sudo', back, 'ssh_sudo_changed', user=name, enabled=f.get('enabled') == '1')[0]
    if action == 'delete':
        if f.get('confirm_name', '') != name:
            flash(f'Para borrar, escribe exactamente el nombre del usuario ({name}).', 'error')
            return redirect(back)
        resp, ok = _ssh_run('delete_user', back, 'ssh_user_deleted', user=name, remove_home=f.get('remove_home') == 'on')
        return redirect(url_for('admin_ssh_users')) if ok else resp
    abort(404)


def _sshd_login_since(applied_at):
    """Primer acceso SSH correcto registrado después de aplicar el cambio."""
    if not applied_at:
        return None
    with panel_db._connect(PORTAL_ROOT) as conn:
        row = conn.execute(
            "SELECT ts, ip, email, detail FROM auth_events WHERE success = 1 AND service = 'sshd' AND ts > ? "
            'ORDER BY id LIMIT 1',
            (applied_at,),
        ).fetchone()
    return dict(row) if row else None


@app.route('/admin/ssh/config')
def admin_ssh_config():
    gate = _require_admin()
    if gate:
        return gate
    status, error = sshadm_client.status()
    pending = (status or {}).get('pending')
    return _ssh_render(
        'admin_ssh_config.html', st=status, st_error=error, pending=pending,
        login_seen=_sshd_login_since(pending['applied_at']) if pending else None,
    )


@app.route('/admin/ssh/config/check')
def admin_ssh_config_check():
    gate = _require_admin()
    if gate:
        return jsonify({'error': 'auth'}), 401
    status, _ = sshadm_client.status()
    pending = (status or {}).get('pending')
    login = _sshd_login_since(pending['applied_at']) if pending else None
    return jsonify({'pending': bool(pending), 'seconds_left': (pending or {}).get('seconds_left', 0), 'login': login})


@app.route('/admin/ssh/config/<action>', methods=['POST'])
def admin_ssh_config_action(action):
    gate = _require_admin()
    if gate:
        return gate
    back = url_for('admin_ssh_config')
    if action == 'revert':
        # Volver atrás nunca necesita desbloqueo: es la salida segura.
        return _ssh_run('sshd_revert', back, 'sshd_reverted')[0]
    gate = _ssh_require_unlock(back)
    if gate:
        return gate
    if action == 'apply':
        settings = {k: request.form.get(k, '') for k in _SSHD_FIELDS}
        return _ssh_run('sshd_propose', back, 'sshd_proposed', settings=settings)[0]
    if action == 'confirm':
        status, error = sshadm_client.status()
        pending = (status or {}).get('pending')
        if not pending:
            flash('No hay cambios pendientes: el plazo ya venció y se revirtieron.', 'error')
            return redirect(back)
        if not _sshd_login_since(pending['applied_at']):
            flash('Todavía no se registró ningún acceso SSH nuevo. Abre una conexión nueva '
                  '(sin cerrar la actual) y vuelve a intentarlo.', 'error')
            return redirect(back)
        return _ssh_run('sshd_confirm', back, 'sshd_confirmed')[0]
    abort(404)


@app.route('/admin/proxy')
def admin_proxy():
    gate = _require_admin()
    if gate:
        return gate
    port_projects = [
        p for p in panel_db.list_projects_raw(PORTAL_ROOT)
        if p.get('access_mode') == 'port' and p.get('port')
    ]
    proxy_service = next((svc for svc in list_service_status() if svc['key'] == 'proxy'), None)
    sites = panel_db.list_sites(PORTAL_ROOT)
    ssl_active = sum(1 for s in sites if s.get('ssl_enabled'))
    ssl_pending = len(sites) - ssl_active
    managed = sum(1 for s in sites if s.get('managed'))
    stats = {
        'total': len(sites),
        'ssl_active': ssl_active,
        'ssl_pending': ssl_pending,
        'managed': managed,
        'custom': len(sites) - managed,
        'donut_segments': _donut_segments([
            ('SSL activo', ssl_active, 'var(--success-text)'),
            ('SSL pendiente', ssl_pending, 'var(--warn-text)'),
        ]),
    }
    resp = make_response(
        render_template(
            'admin_proxy.html',
            sites=sites,
            port_projects=port_projects,
            proxy_service=proxy_service,
            stats=stats,
        )
    )
    return _no_cache(resp)


@app.route('/admin/proxy/new', methods=['POST'])
def admin_proxy_new():
    if not get_admin_id():
        return redirect(url_for('admin_login'))
    site, error = panel_db.create_site(
        PORTAL_ROOT,
        request.form.get('domain', ''),
        request.form.get('target_host', ''),
        request.form.get('target_port', ''),
    )
    if error:
        flash(error, 'error')
        return redirect(url_for('admin_proxy'))
    ok, apply_error = proxy_control.apply_site(
        PROXY_SITES_DIR, site['domain'], site['target_host'], site['target_port'], ssl_ready=False,
    )
    if ok:
        flash(f"Sitio {site['domain']} creado y activo por HTTP. Emite el SSL cuando el DNS apunte aquí.", 'success')
    else:
        flash(f'Sitio guardado, pero el proxy no se pudo aplicar: {apply_error}', 'error')
    return redirect(url_for('admin_proxy'))


@app.route('/admin/proxy/<int:site_id>/ssl', methods=['POST'])
def admin_proxy_ssl(site_id):
    if not get_admin_id():
        return redirect(url_for('admin_login'))
    site = panel_db.get_site(PORTAL_ROOT, site_id)
    if not site:
        abort(404)
    if not site['managed']:
        flash('Este sitio tiene un config personalizado; renueva su SSL manualmente.', 'error')
        return redirect(url_for('admin_proxy'))
    cert_ok, cert_out = proxy_control.issue_certificate(site['domain'], get_certbot_email())
    if not cert_ok:
        flash(f"No se pudo emitir el certificado: {cert_out.strip()[-300:]}", 'error')
        return redirect(url_for('admin_proxy'))
    ok, apply_error = proxy_control.apply_site(
        PROXY_SITES_DIR, site['domain'], site['target_host'], site['target_port'], ssl_ready=True,
    )
    if ok:
        panel_db.set_site_ssl(PORTAL_ROOT, site_id, True)
        flash(f"SSL activo para {site['domain']}.", 'success')
    else:
        flash(f'Certificado emitido, pero no se pudo activar en el proxy: {apply_error}', 'error')
    return redirect(url_for('admin_proxy'))


@app.route('/admin/proxy/<int:site_id>/delete', methods=['POST'])
def admin_proxy_delete(site_id):
    if not get_admin_id():
        return redirect(url_for('admin_login'))
    site = panel_db.get_site(PORTAL_ROOT, site_id)
    if not site:
        abort(404)
    if not site['managed']:
        flash('Este sitio tiene un config personalizado; no se puede eliminar desde el panel.', 'error')
        return redirect(url_for('admin_proxy'))
    proxy_control.remove_site(PROXY_SITES_DIR, site['domain'])
    panel_db.delete_site(PORTAL_ROOT, site_id)
    flash(f"Sitio {site['domain']} eliminado.", 'success')
    return redirect(url_for('admin_proxy'))


@app.route('/admin/graphify')
def admin_graphify_index():
    gate = _require_admin()
    if gate:
        return gate
    resp = make_response(
        render_template(
            'admin_graphify.html',
            graphs=list_graphify_graphs(),
            public_host=get_public_host(),
        )
    )
    return _no_cache(resp)


@app.route('/admin/graphify/<project_id>/')
def admin_graphify_project(project_id):
    gate = _require_admin()
    if gate:
        return gate
    if project_id not in GRAPHIFY_PROJECTS:
        abort(404)
    return redirect(
        url_for('admin_graphify_file', project_id=project_id, filename='graph.html')
    )


@app.route('/admin/graphify/<project_id>/<path:filename>')
def admin_graphify_file(project_id, filename):
    gate = _require_admin()
    if gate:
        return gate
    out_dir = _graphify_out_dir(project_id)
    if not out_dir:
        abort(404)
    basename = os.path.basename(filename)
    if basename != filename or basename not in _GRAPHIFY_FILES:
        abort(404)
    return send_from_directory(out_dir, filename)


@app.route('/admin/api/metrics')
def admin_metrics_api():
    if not get_admin_id():
        return {'error': 'No autorizado'}, 401
    return jsonify(get_system_metrics())


@app.route('/admin/containers/<service_key>/stop', methods=['POST'])
def admin_stop_container(service_key):
    if not get_admin_id():
        return redirect(url_for('admin_login'))
    ok, msg = stop_service(service_key)
    if ok:
        flash(f'Proyecto detenido. La aplicación ya no responde; los datos en disco se conservan.', 'success')
    else:
        flash(f'No se pudo detener: {msg}', 'error')
    return redirect(url_for('admin_proxy') if service_key == 'proxy' else url_for('admin_panel'))


@app.route('/admin/containers/<service_key>/start', methods=['POST'])
def admin_start_container(service_key):
    if not get_admin_id():
        return redirect(url_for('admin_login'))
    ok, msg = start_service(service_key)
    if ok:
        flash('Proyecto iniciado. La aplicación debería estar disponible en unos segundos.', 'success')
    else:
        flash(f'No se pudo iniciar: {msg}', 'error')
    return redirect(url_for('admin_proxy') if service_key == 'proxy' else url_for('admin_panel'))


@app.route('/admin/2fa', methods=['GET', 'POST'])
def admin_2fa():
    gate = _require_admin()
    if gate:
        return gate
    admin_id = get_admin_id()
    secret, enabled = get_totp_state(PORTAL_ROOT, admin_id)
    error = None
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'generate':
            secret = pyotp.random_base32()
            set_totp_secret(PORTAL_ROOT, admin_id, secret)
        elif action == 'confirm':
            if secret and verify_totp(PORTAL_ROOT, admin_id, request.form.get('code')):
                confirm_totp(PORTAL_ROOT, admin_id)
                panel_db.log_action(PORTAL_ROOT, current_admin_email(), '2fa_enabled', '')
                flash('Verificación en dos pasos activada.', 'success')
                return redirect(url_for('admin_admins'))
            error = 'Código incorrecto. Escanea de nuevo o verifica la hora de tu teléfono.'
        elif action == 'disable' and security.get_rules(PORTAL_ROOT)['sec_require_2fa']:
            error = 'La verificación en dos pasos es obligatoria en este panel; no se puede desactivar.'
        elif action == 'disable':
            disable_totp(PORTAL_ROOT, admin_id)
            panel_db.log_action(PORTAL_ROOT, current_admin_email(), '2fa_disabled', '')
            flash('Verificación en dos pasos desactivada.', 'success')
            return redirect(url_for('admin_admins'))
        secret, enabled = get_totp_state(PORTAL_ROOT, admin_id)

    admin = get_admin(PORTAL_ROOT)
    otpauth_uri = pyotp.totp.TOTP(secret).provisioning_uri(
        name=admin['email'] if admin else '', issuer_name='Panel'
    ) if secret else None
    # El QR se genera aquí mismo (SVG en línea): la clave secreta nunca sale
    # hacia un servicio externo de códigos QR.
    qr_svg = segno.make(otpauth_uri, error='m').svg_inline(
        scale=5, border=4, dark='#000000', light='#ffffff',
    ) if otpauth_uri and not enabled else None
    return _no_cache(make_response(render_template(
        'admin_2fa.html', enabled=enabled, secret=secret, otpauth_uri=otpauth_uri, error=error,
        qr_svg=qr_svg,
    )))


def current_admin_email():
    admin = get_admin(PORTAL_ROOT)
    return admin['email'] if admin else ''


@app.route('/admin/admins')
def admin_admins():
    gate = _require_admin()
    if gate:
        return gate
    resp = make_response(render_template('admin_admins.html', admins=list_admins(PORTAL_ROOT)))
    return _no_cache(resp)


@app.route('/admin/notifications', methods=['GET', 'POST'])
def admin_notifications():
    gate = _require_admin()
    if gate:
        return gate
    if request.method == 'POST':
        notification_control.save_config(PORTAL_ROOT, request.form)
        panel_db.log_action(PORTAL_ROOT, current_admin_email(), 'notifications_saved', '')
        flash('Configuración de notificaciones guardada.', 'success')
        return redirect(url_for('admin_notifications'))
    return render_template('admin_notifications.html', cfg=notification_control.get_config(PORTAL_ROOT))


@app.route('/admin/notifications/test', methods=['POST'])
def admin_notifications_test():
    if not get_admin_id():
        return redirect(url_for('admin_login'))
    results = notification_control.notify(
        PORTAL_ROOT, 'test', 'Prueba del panel',
        'Si ves este mensaje, la notificación quedó bien configurada.',
    )
    if not results:
        flash('No hay ningún canal activado con datos completos para probar.', 'error')
    else:
        summary = '; '.join(f"{name}: {'ok' if ok else err}" for name, ok, err in results)
        flash(f'Prueba enviada — {summary}', 'success')
    return redirect(url_for('admin_notifications'))


@app.route('/admin/backups')
def admin_backups():
    gate = _require_admin()
    if gate:
        return gate
    files = []
    if os.path.isdir(BACKUPS_DIR):
        for name in sorted(os.listdir(BACKUPS_DIR), reverse=True):
            full = os.path.join(BACKUPS_DIR, name)
            if os.path.isfile(full):
                files.append({
                    'name': name,
                    'size': os.path.getsize(full),
                    'mtime': datetime.fromtimestamp(os.path.getmtime(full)),
                })
    return render_template(
        'admin_backups.html', files=files,
        projects=[p for p in panel_db.list_projects_raw(PORTAL_ROOT) if p.get('containers') and p.get('containers') != '[]'],
    )


@app.route('/admin/backups/<path:filename>/download')
def admin_backup_download(filename):
    if not get_admin_id():
        return redirect(url_for('admin_login'))
    if '/' in filename or '..' in filename:
        abort(400)
    full = os.path.join(BACKUPS_DIR, filename)
    if not os.path.isfile(full):
        abort(404)
    return send_file(full, as_attachment=True, download_name=filename)


@app.route('/admin/backups/<path:filename>/delete', methods=['POST'])
def admin_backup_delete(filename):
    if not get_admin_id():
        return redirect(url_for('admin_login'))
    if '/' in filename or '..' in filename:
        abort(400)
    full = os.path.join(BACKUPS_DIR, filename)
    if os.path.isfile(full):
        os.remove(full)
        flash(f'{filename} eliminado.', 'success')
    return redirect(url_for('admin_backups'))


@app.route('/admin/resources')
def admin_resources():
    gate = _require_admin()
    if gate:
        return gate
    data = resource_charts.build(PORTAL_ROOT, request.args.get('range', resource_charts.DEFAULT_RANGE))
    return render_template('admin_resources.html', data=data)


@app.route('/admin/audit')
def admin_audit():
    gate = _require_admin()
    if gate:
        return gate
    return render_template('admin_audit.html', entries=panel_db.list_audit(PORTAL_ROOT, limit=200))


@app.route('/admin/password', methods=['GET', 'POST'])
def admin_change_password():
    gate = _require_admin()
    if gate:
        return gate
    error = None
    if request.method == 'POST':
        ok, error = change_password(
            PORTAL_ROOT,
            get_admin_id(),
            request.form.get('current_password', ''),
            request.form.get('new_password', ''),
        )
        if ok:
            # change_password ya invalidó todas las sesiones de este admin;
            # se renueva solo la actual para no echarlo a él también.
            login_admin({'id': get_admin_id()}, PORTAL_ROOT)
            panel_db.log_action(PORTAL_ROOT, current_admin_email(), 'password_changed', g.client_ip)
            flash('Contraseña actualizada. Se cerraron tus otras sesiones abiertas.', 'success')
            return redirect(url_for('admin_admins'))
    return render_template('admin_password.html', error=error)


@app.route('/admin/admins/new', methods=['GET', 'POST'])
def admin_create_admin():
    if not get_admin_id():
        return redirect(url_for('admin_login'))
    error = None
    if request.method == 'POST':
        email, error = create_admin(
            PORTAL_ROOT,
            request.form.get('email', ''),
            request.form.get('password', ''),
            get_admin_id(),
        )
        if email:
            flash(f'Administrador {email} creado.', 'success')
            return redirect(url_for('admin_admins'))
    return render_template('admin_new.html', error=error)


if __name__ == '__main__':
    from waitress import serve

    print(f'Portal: http://{get_public_host()}:{PORTAL_PORT}/')
    print(f'Admin:  http://{get_public_host()}:{PORTAL_PORT}/admin/login')
    for project in load_projects():
        print(f"  - {project['name']}: {project['url']}")
    serve(app, host='0.0.0.0', port=PORTAL_PORT, threads=4)
