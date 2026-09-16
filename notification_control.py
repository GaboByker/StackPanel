"""Envío de notificaciones a Discord/Slack/Email. Las credenciales las
configura el propio administrador en /admin/notifications; nada viene
precargado. Cada canal y cada tipo de evento tiene su propia casilla."""
import json
import smtplib
import urllib.request
from email.mime.text import MIMEText

import panel_db

SETTING_KEYS = [
    'discord_webhook_url', 'discord_enabled',
    'slack_webhook_url', 'slack_enabled',
    'smtp_host', 'smtp_port', 'smtp_user', 'smtp_password', 'smtp_from', 'smtp_to', 'smtp_use_tls',
    'smtp_enabled',
    'notify_project_down', 'notify_disk_full', 'notify_ssl_expiring',
]

_CHECKBOX_KEYS = {
    'discord_enabled', 'slack_enabled', 'smtp_enabled', 'smtp_use_tls',
    'notify_project_down', 'notify_disk_full', 'notify_ssl_expiring',
}


def get_config(root):
    values = panel_db.get_settings(root, SETTING_KEYS)
    return {k: values.get(k, '') for k in SETTING_KEYS}


def save_config(root, form):
    values = {}
    for key in SETTING_KEYS:
        if key in _CHECKBOX_KEYS:
            values[key] = '1' if form.get(key) == 'on' else '0'
        else:
            values[key] = (form.get(key) or '').strip()
    panel_db.set_settings(root, values)


def _post_json(url, payload, timeout=10):
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300, ''
    except Exception as exc:
        return False, str(exc)


def send_discord(url, title, message):
    return _post_json(url, {'content': f'**{title}**\n{message}'})


def send_slack(url, title, message):
    return _post_json(url, {'text': f'*{title}*\n{message}'})


def send_email(cfg, title, message):
    host = cfg.get('smtp_host')
    if not host:
        return False, 'SMTP no configurado.'
    try:
        port = int(cfg.get('smtp_port') or '587')
        msg = MIMEText(message)
        msg['Subject'] = title
        msg['From'] = cfg.get('smtp_from') or cfg.get('smtp_user') or ''
        msg['To'] = cfg.get('smtp_to') or ''
        with smtplib.SMTP(host, port, timeout=15) as server:
            if cfg.get('smtp_use_tls') == '1':
                server.starttls()
            if cfg.get('smtp_user'):
                server.login(cfg['smtp_user'], cfg.get('smtp_password') or '')
            server.sendmail(msg['From'], [msg['To']], msg.as_string())
        return True, ''
    except Exception as exc:
        return False, str(exc)


def notify(root, event_key, title, message):
    """event_key: 'project_down' | 'disk_full' | 'ssl_expiring' | 'test'.
    'test' ignora las casillas de evento (se usa para el botón de prueba)."""
    cfg = get_config(root)
    if event_key != 'test' and cfg.get(f'notify_{event_key}') != '1':
        return []
    results = []
    if cfg.get('discord_enabled') == '1' and cfg.get('discord_webhook_url'):
        ok, err = send_discord(cfg['discord_webhook_url'], title, message)
        results.append(('discord', ok, err))
    if cfg.get('slack_enabled') == '1' and cfg.get('slack_webhook_url'):
        ok, err = send_slack(cfg['slack_webhook_url'], title, message)
        results.append(('slack', ok, err))
    if cfg.get('smtp_enabled') == '1':
        ok, err = send_email(cfg, title, message)
        results.append(('email', ok, err))
    return results
