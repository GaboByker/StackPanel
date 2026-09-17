#!/usr/bin/env python3
"""Portal inicial: elige entre proyectos independientes en distintos puertos."""
import crypt
import os
import re
import secrets
import shutil
import sqlite3
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

from auth import (
    authenticate,
    change_password,
    confirm_totp,
    create_admin,
    disable_totp,
    get_admin,
    get_admin_id,
    get_totp_state,
    init_db,
    list_admins,
    login_admin,
    logout_admin,
    set_totp_secret,
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
import subprocess
import pyotp

PORTAL_ROOT = os.path.dirname(os.path.abspath(__file__))
PUBLIC_HOST = os.environ.get('PUBLIC_HOST', '161.97.162.177')
PORTAL_PORT = int(os.environ.get('PORTAL_PORT', '5005'))
STACK_ROOT = os.environ.get(
    'STACK_ROOT',
    '/stack' if os.path.isdir('/stack') else os.path.dirname(PORTAL_ROOT),
)
PROXY_SITES_DIR = os.environ.get(
    'PROXY_SITES_DIR',
    '/app/proxy-sites' if os.path.isdir('/app/proxy-sites') else os.path.join(STACK_ROOT, 'proxy', 'sites'),
)
CERTBOT_EMAIL = os.environ.get('CERTBOT_EMAIL', 'darkblood1977@gmail.com')
HOST_STACK_ROOT = os.environ.get('HOST_STACK_ROOT', STACK_ROOT)
BACKUPS_DIR = os.environ.get('BACKUPS_DIR', '/app/backups')


def get_public_host():
    return panel_db.get_setting(PORTAL_ROOT, 'public_host') or PUBLIC_HOST


def get_certbot_email():
    return panel_db.get_setting(PORTAL_ROOT, 'certbot_email') or CERTBOT_EMAIL


def _project_paths(key):
    """(local_folder, host_folder) para un project_key nuevo: local_folder es
    donde este proceso puede escribir (montaje r/w html-rw); host_folder es la
    misma carpeta vista como ruta del host real, la que necesita Docker para
    los binds de los contenedores que se crean."""
    local_folder = os.path.join(files_control.html_root(STACK_ROOT), key)
    host_folder = os.path.join(HOST_STACK_ROOT, 'html', key)
    return local_folder, host_folder

GRAPHIFY_PROJECTS = {
    'portal': 'portal',
    'social-hub': 'html/social-hub',
    'empires': 'html/Empires-Allies',
    'social-empires': 'html/social-empires',
    'finanzas-personales': 'html/finanzas-personales',
    'wapicenter': 'html/WApiCenter',
    'gemma4-api-manager': 'html/gemma4-api-manager',
    'wanqara-dashboard': 'html/wanqara-dashboard',
}
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
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
app.config['SESSION_REFRESH_EACH_REQUEST'] = False
app.config['MAX_CONTENT_LENGTH'] = int(os.environ.get('PORTAL_MAX_UPLOAD_MB', '512')) * 1024 * 1024
csrf = CSRFProtect(app)

init_db(PORTAL_ROOT)
panel_db.init_db(PORTAL_ROOT)
os.makedirs(BACKUPS_DIR, exist_ok=True)
scheduler.start(PORTAL_ROOT, STACK_ROOT, BACKUPS_DIR)


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
    return projects


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
                login_admin(admin)
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


@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if get_admin_id():
        return redirect(url_for('admin_panel'))
    error = None
    if request.method == 'POST':
        admin, error = authenticate(
            PORTAL_ROOT,
            request.form.get('email', ''),
            request.form.get('password', ''),
        )
        if admin:
            if admin.get('totp_enabled'):
                session['pending_admin_id'] = admin['id']
                session['pending_next'] = request.args.get('next') or url_for('admin_panel')
                return redirect(url_for('admin_login_verify'))
            login_admin(admin)
            panel_db.log_action(PORTAL_ROOT, admin['email'], 'login', '')
            flash('Sesión de administrador iniciada.', 'success')
            next_url = request.args.get('next') or url_for('admin_panel')
            if not next_url.startswith('/'):
                next_url = url_for('admin_panel')
            return redirect(next_url)
    resp = make_response(render_template('admin_login.html', error=error))
    return _no_cache(resp)


@app.route('/admin/login/verify', methods=['GET', 'POST'])
def admin_login_verify():
    admin_id = session.get('pending_admin_id')
    if not admin_id:
        return redirect(url_for('admin_login'))
    error = None
    if request.method == 'POST':
        secret, enabled = get_totp_state(PORTAL_ROOT, admin_id)
        code = (request.form.get('code') or '').strip()
        if enabled and secret and pyotp.TOTP(secret).verify(code, valid_window=1):
            next_url = session.get('pending_next') or url_for('admin_panel')
            row = next((a for a in list_admins(PORTAL_ROOT) if a['id'] == admin_id), None)
            login_admin({'id': admin_id})  # limpia la sesión y guarda admin_id
            panel_db.log_action(PORTAL_ROOT, row['email'] if row else '', 'login_2fa', '')
            flash('Sesión de administrador iniciada.', 'success')
            return redirect(next_url)
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
    if not project.get('folder'):
        # Proyectos agregados como "solo enlace" (sin carpeta propia) no
        # tienen dónde recibir archivos todavía; se les crea una carpeta en
        # html/ la primera vez que alguien pide un acceso SFTP.
        folder = f"html/{project['project_key']}"
        html_root = files_control.html_root(STACK_ROOT)
        target_dir = os.path.join(html_root, project['project_key'])
        os.makedirs(target_dir, exist_ok=True)
        try:
            os.chown(target_dir, -1, os.stat(html_root).st_gid)
        except OSError:
            pass
        os.chmod(target_dir, 0o775)
        panel_db.set_project_folder(PORTAL_ROOT, project_id, folder)
        project['folder'] = folder

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
    return render_template(
        'admin_project_database.html', project=project,
        databases=panel_db.list_databases(PORTAL_ROOT, project_id), error=error,
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
    candidate, error = db_autodetect.autodetect(local_folder)
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

    panel_db.insert_project(
        PORTAL_ROOT, key, name, app_templates.TEMPLATES[template_key]['label'],
        'port', port, None, '/', None,
        folder=f'html/{key}', containers=containers, volumes=volumes,
        template=template_key, secrets=secrets,
    )
    panel_db.log_action(PORTAL_ROOT, current_admin_email(), 'app_install', f'{template_key}: {name}')
    flash(f'{name} instalado y en marcha en el puerto {port}.', 'success')
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


@app.route('/admin/firewall')
def admin_firewall():
    gate = _require_admin()
    if gate:
        return gate
    port_projects = [
        p for p in panel_db.list_projects_raw(PORTAL_ROOT)
        if p.get('access_mode') == 'port' and p.get('port')
    ]
    port_projects.sort(key=lambda p: p['port'])
    resp = make_response(render_template('admin_firewall.html', port_projects=port_projects))
    return _no_cache(resp)


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
            code = (request.form.get('code') or '').strip()
            if secret and pyotp.TOTP(secret).verify(code, valid_window=1):
                confirm_totp(PORTAL_ROOT, admin_id)
                panel_db.log_action(PORTAL_ROOT, current_admin_email(), '2fa_enabled', '')
                flash('Verificación en dos pasos activada.', 'success')
                return redirect(url_for('admin_admins'))
            error = 'Código incorrecto. Escanea de nuevo o verifica la hora de tu teléfono.'
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
    return render_template(
        'admin_2fa.html', enabled=enabled, secret=secret, otpauth_uri=otpauth_uri, error=error,
    )


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


def _svg_points(values, width=760, height=140):
    values = [v if v is not None else 0 for v in values]
    if not values:
        return ''
    n = len(values)
    step = width / max(n - 1, 1)
    points = []
    for i, v in enumerate(values):
        x = round(i * step, 1)
        y = round(height - (min(max(v, 0), 100) / 100 * height), 1)
        points.append(f'{x},{y}')
    return ' '.join(points)


@app.route('/admin/resources')
def admin_resources():
    gate = _require_admin()
    if gate:
        return gate
    history = panel_db.list_metrics_history(PORTAL_ROOT, hours=24)
    cpu_points = _svg_points([h['cpu_percent'] for h in history])
    mem_points = _svg_points([h['mem_percent'] for h in history])
    disk_points = _svg_points([h['disk_percent'] for h in history])
    return render_template(
        'admin_resources.html', history=history,
        cpu_points=cpu_points, mem_points=mem_points, disk_points=disk_points,
    )


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
            flash('Contraseña actualizada.', 'success')
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
