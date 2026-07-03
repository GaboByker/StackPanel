#!/usr/bin/env python3
"""Portal inicial: elige entre proyectos independientes en distintos puertos."""
import json
import os
from datetime import timedelta

from flask import Flask, flash, g, redirect, render_template, request, url_for

from auth import (
    authenticate,
    create_admin,
    get_admin,
    get_admin_id,
    init_db,
    list_admins,
    login_admin,
    logout_admin,
)
from docker_control import list_service_status, start_service, stop_service

PORTAL_ROOT = os.path.dirname(os.path.abspath(__file__))
PUBLIC_HOST = os.environ.get('PUBLIC_HOST', '161.97.162.177')
PORTAL_PORT = int(os.environ.get('PORTAL_PORT', '5005'))

app = Flask(
    __name__,
    template_folder=os.path.join(PORTAL_ROOT, 'templates'),
    static_folder=os.path.join(PORTAL_ROOT, 'static'),
)
app.config['SECRET_KEY'] = os.environ.get('PORTAL_SECRET_KEY', 'portal-dev-change-me')
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

init_db(PORTAL_ROOT)


def load_projects():
    path = os.path.join(PORTAL_ROOT, 'projects.json')
    try:
        with open(path, encoding='utf-8') as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []

    projects = []
    for item in data:
        port = item.get('port')
        path = item.get('path', '/')
        if port:
            base = f'http://{PUBLIC_HOST}:{port}'
            url = base + (path if path.startswith('/') else f'/{path}')
            icon = item.get('icon_path')
            icon_url = f'{base}{icon}' if icon else None
        else:
            url = item.get('url', '/')
            icon_url = item.get('icon')
        projects.append({
            'id': item.get('id', ''),
            'name': item.get('name', 'Proyecto'),
            'description': item.get('description', ''),
            'url': url,
            'icon': icon_url,
        })
    return projects


@app.context_processor
def inject_admin():
    admin = get_admin(PORTAL_ROOT) if get_admin_id() else None
    return {'current_admin': admin}


@app.route('/')
def portal_home():
    return render_template('portal.html', projects=load_projects(), public_host=PUBLIC_HOST)


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
            login_admin(admin)
            flash('Sesión de administrador iniciada.', 'success')
            next_url = request.args.get('next') or url_for('admin_panel')
            if not next_url.startswith('/'):
                next_url = url_for('admin_panel')
            return redirect(next_url)
    return render_template('admin_login.html', error=error)


@app.route('/admin/logout')
def admin_logout():
    logout_admin()
    flash('Sesión cerrada.', 'success')
    return redirect(url_for('portal_home'))


@app.route('/admin')
def admin_panel():
    if not get_admin_id():
        return redirect(url_for('admin_login', next=request.path))
    return render_template(
        'admin_panel.html',
        services=list_service_status(),
        admins=list_admins(PORTAL_ROOT),
        public_host=PUBLIC_HOST,
    )


@app.route('/admin/containers/<service_key>/stop', methods=['POST'])
def admin_stop_container(service_key):
    if not get_admin_id():
        return redirect(url_for('admin_login'))
    ok, msg = stop_service(service_key)
    if ok:
        flash(f'Proyecto detenido. La aplicación ya no responde; los datos en disco se conservan.', 'success')
    else:
        flash(f'No se pudo detener: {msg}', 'error')
    return redirect(url_for('admin_panel'))


@app.route('/admin/containers/<service_key>/start', methods=['POST'])
def admin_start_container(service_key):
    if not get_admin_id():
        return redirect(url_for('admin_login'))
    ok, msg = start_service(service_key)
    if ok:
        flash('Proyecto iniciado. La aplicación debería estar disponible en unos segundos.', 'success')
    else:
        flash(f'No se pudo iniciar: {msg}', 'error')
    return redirect(url_for('admin_panel'))


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
            return redirect(url_for('admin_panel'))
    return render_template('admin_new.html', error=error)


if __name__ == '__main__':
    from waitress import serve

    print(f'Portal: http://{PUBLIC_HOST}:{PORTAL_PORT}/')
    print(f'Admin:  http://{PUBLIC_HOST}:{PORTAL_PORT}/admin/login')
    for project in load_projects():
        print(f"  - {project['name']}: {project['url']}")
    serve(app, host='0.0.0.0', port=PORTAL_PORT, threads=4)
