"""Acceso directo desde el panel a los WordPress del servidor.

El panel deja en wp-content/mu-plugins un plugin "must-use" que acepta un
enlace firmado (HMAC-SHA256 con una clave propia de cada sitio), válido 60 s
y de un solo uso; al validarlo inicia sesión como administrador y redirige a
wp-admin. La clave vive en wp-content/mu-plugins/stackpanel-sso/key.php
(un archivo PHP que solo devuelve la clave: servido por HTTP no muestra nada).

También completa la instalación de un WordPress recién creado (el paso de
"título + usuario + contraseña"), para que se pueda entrar desde el minuto uno.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

PLUGIN_FILE = 'stackpanel-sso.php'
KEY_DIR = 'stackpanel-sso'
TOKEN_TTL = 60

_PLUGIN_PHP = r"""<?php
/**
 * Plugin Name: StackPanel SSO
 * Description: Acceso directo desde StackPanel (enlace firmado, de un solo uso, 60 s). Lo gestiona el panel: no editar.
 */
defined('ABSPATH') || exit;

add_action('init', static function () {
	if (empty($_GET['stackpanel_sso']) || !is_string($_GET['stackpanel_sso'])) {
		return;
	}
	nocache_headers();
	$fail = static function ($msg) {
		wp_die(esc_html($msg), 'StackPanel', array('response' => 403));
	};
	$key_file = __DIR__ . '/stackpanel-sso/key.php';
	$key = is_readable($key_file) ? include $key_file : '';
	if (!is_string($key) || strlen($key) < 32) {
		$fail('El acceso directo no está configurado en este sitio.');
	}
	$parts = explode('.', wp_unslash($_GET['stackpanel_sso']), 2);
	if (count($parts) !== 2) {
		$fail('Enlace de acceso inválido.');
	}
	$b64 = static function ($raw) {
		return rtrim(strtr(base64_encode($raw), '+/', '-_'), '=');
	};
	if (!hash_equals($b64(hash_hmac('sha256', $parts[0], $key, true)), $parts[1])) {
		$fail('Enlace de acceso inválido.');
	}
	$data = json_decode(base64_decode(strtr($parts[0], '-_', '+/')), true);
	if (!is_array($data) || empty($data['nonce']) || empty($data['exp']) || time() > (int) $data['exp']) {
		$fail('El enlace caducó. Vuelve a pulsar «Entrar» en el panel.');
	}
	$used = 'stackpanel_sso_' . md5((string) $data['nonce']);
	if (get_transient($used)) {
		$fail('Este enlace ya se usó. Vuelve a pulsar «Entrar» en el panel.');
	}
	set_transient($used, 1, 10 * MINUTE_IN_SECONDS);

	$user = !empty($data['user']) ? get_user_by('login', (string) $data['user']) : false;
	if (!$user || !user_can($user, 'manage_options')) {
		$admins = get_users(array('role' => 'administrator', 'orderby' => 'ID', 'order' => 'ASC', 'number' => 1));
		$user = $admins ? $admins[0] : false;
	}
	if (!$user) {
		$fail('Este WordPress no tiene ningún administrador.');
	}
	wp_clear_auth_cookie();
	wp_set_current_user($user->ID);
	wp_set_auth_cookie($user->ID, false);
	do_action('wp_login', $user->user_login, $user);
	wp_safe_redirect(admin_url());
	exit;
}, 1);
"""


def wp_content(local_folder):
    return os.path.join(local_folder, 'wp-content')


def is_wordpress(local_folder):
    if not local_folder:
        return False
    content = wp_content(local_folder)
    return os.path.isdir(os.path.join(content, 'themes')) or os.path.isdir(os.path.join(content, 'plugins'))


def _key_path(local_folder):
    return os.path.join(wp_content(local_folder), 'mu-plugins', KEY_DIR, 'key.php')


def _read_key(local_folder):
    try:
        with open(_key_path(local_folder)) as fh:
            raw = fh.read()
    except OSError:
        return None
    start = raw.find("'")
    end = raw.rfind("'")
    key = raw[start + 1:end] if 0 <= start < end else ''
    return key if len(key) >= 32 else None


def ensure(local_folder, rotate=False):
    """Instala/actualiza el plugin y devuelve la clave del sitio.
    rotate=True genera una clave nueva (p. ej. tras clonar un sitio)."""
    mu_dir = os.path.join(wp_content(local_folder), 'mu-plugins')
    os.makedirs(os.path.join(mu_dir, KEY_DIR), exist_ok=True)

    plugin_path = os.path.join(mu_dir, PLUGIN_FILE)
    try:
        with open(plugin_path) as fh:
            current = fh.read()
    except OSError:
        current = None
    if current != _PLUGIN_PHP:
        with open(plugin_path, 'w') as fh:
            fh.write(_PLUGIN_PHP)
        os.chmod(plugin_path, 0o644)

    key = None if rotate else _read_key(local_folder)
    if not key:
        key = secrets.token_hex(32)
        path = _key_path(local_folder)
        with open(path, 'w') as fh:
            fh.write(f"<?php\n// Clave del acceso directo de StackPanel. La genera el panel.\nreturn '{key}';\n")
        os.chmod(path, 0o644)
        index = os.path.join(mu_dir, KEY_DIR, 'index.php')
        if not os.path.exists(index):
            with open(index, 'w') as fh:
                fh.write('<?php // Silence is golden.\n')
    return key


def _b64(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode()


def login_url(site_url, key, user=None):
    payload = {'exp': int(time.time()) + TOKEN_TTL, 'nonce': secrets.token_hex(16)}
    if user:
        payload['user'] = user
    body = _b64(json.dumps(payload, separators=(',', ':')).encode())
    sig = _b64(hmac.new(key.encode(), body.encode(), hashlib.sha256).digest())
    base = site_url.rstrip('/') + '/'
    return base + '?' + urllib.parse.urlencode({'stackpanel_sso': f'{body}.{sig}'})


# --- instalación automática de un WordPress nuevo ---------------------------

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def _request(base, path, public_url, data=None, timeout=20):
    """Pide `path` al contenedor (base = http://contenedor) pero con el Host y
    el esquema del sitio público, para que WordPress guarde esa URL."""
    parsed = urllib.parse.urlparse(public_url)
    headers = {'Host': parsed.netloc, 'User-Agent': 'StackPanel'}
    if parsed.scheme == 'https':
        headers['X-Forwarded-Proto'] = 'https'
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    req = urllib.request.Request(base + path, data=body, headers=headers)
    try:
        with _opener.open(req, timeout=timeout) as resp:
            return resp.status, resp.headers, resp.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers, ''


def _installed(base, public_url):
    status, headers, _ = _request(base, '/wp-login.php', public_url)
    location = (headers or {}).get('Location', '') if status in (301, 302) else ''
    if status == 200:
        return True
    if 'install.php' in location:
        return False
    return None


def complete_install(bases, public_url, title, admin_email, user, language='es_ES', wait=90):
    """Hace el paso de instalación de WordPress. `bases` son direcciones donde
    probar a alcanzar el contenedor (por nombre en su red, o por el puerto
    publicado en el host). Devuelve (password, error)."""
    deadline = time.time() + wait
    base = None
    while time.time() < deadline and not base:
        for candidate in bases:
            try:
                status, _, _ = _request(candidate, '/wp-admin/install.php', public_url, timeout=5)
            except (OSError, urllib.error.URLError):
                continue
            if status == 200:
                base = candidate
                break
        if not base:
            time.sleep(3)
    if not base:
        return None, 'WordPress no respondió a tiempo para completar la instalación.'
    if _installed(base, public_url):
        return None, 'Este WordPress ya estaba instalado.'

    password = secrets.token_urlsafe(18)
    try:
        # Paso 1: elegir idioma (descarga el paquete de traducción si hay red).
        _request(base, '/wp-admin/install.php?step=1', public_url, data={'language': language}, timeout=60)
        _request(base, '/wp-admin/install.php?step=2', public_url, data={
            'weblog_title': title,
            'user_name': user,
            'admin_password': password,
            'admin_password2': password,
            'pw_weak': '1',
            'admin_email': admin_email,
            'blog_public': '1',
            'language': language,
        }, timeout=90)
    except (OSError, urllib.error.URLError) as exc:
        return None, f'No se pudo completar la instalación: {exc}'
    if not _installed(base, public_url):
        return None, 'WordPress no aceptó los datos de instalación.'
    return password, None
