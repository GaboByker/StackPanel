<?php
/**
 * Formularios: render, envío (admin-post, funciona sin JS), antispam y bandeja de envíos.
 *
 * La configuración del formulario (destinatario, campos, tipos) viaja firmada con HMAC:
 * el visitante no puede cambiar el destinatario ni inyectar campos.
 */

defined('ABSPATH') || exit;

const ODIN_FORM_TYPES = ['text', 'email', 'tel', 'number', 'url', 'date', 'textarea', 'select', 'radio', 'checkbox'];
const ODIN_FORM_MAX_LEN = 5000;
const ODIN_FORM_MIN_SECONDS = 3;
const ODIN_FORM_RATE = 5; // envíos por IP cada 10 min

function odin_form_field_def(array $attrs) {
	$label = trim((string) ($attrs['label'] ?? ''));
	$name = sanitize_key(str_replace('-', '_', (string) ($attrs['name'] ?? '')));
	if ($name === '') {
		$name = sanitize_key(str_replace('-', '_', sanitize_title($label))) ?: 'campo';
	}
	$type = $attrs['type'] ?? 'text';
	$type = in_array($type, ODIN_FORM_TYPES, true) ? $type : 'text';
	$options = array_values(array_filter(array_map('trim', explode("\n", (string) ($attrs['options'] ?? '')))));
	return [
		'name' => $name,
		'label' => $label ?: $name,
		'type' => $type,
		'required' => !empty($attrs['required']),
		'options' => $options,
	];
}

function odin_form_collect_fields(array $blocks, array &$out) {
	foreach ($blocks as $b) {
		if (($b['blockName'] ?? '') === 'odin/field') {
			$def = odin_form_field_def($b['attrs'] ?? []);
			$out[$def['name']] = $def;
		}
		if (!empty($b['innerBlocks'])) {
			odin_form_collect_fields($b['innerBlocks'], $out);
		}
	}
}

function odin_form_b64(string $raw) {
	return rtrim(strtr(base64_encode($raw), '+/', '-_'), '=');
}

function odin_form_sign(array $cfg) {
	$payload = odin_form_b64(wp_json_encode($cfg));
	return $payload . '.' . odin_form_b64(hash_hmac('sha256', $payload, wp_salt('auth'), true));
}

function odin_form_verify(string $token) {
	$parts = explode('.', $token, 2);
	if (count($parts) !== 2 || !hash_equals(odin_form_b64(hash_hmac('sha256', $parts[0], wp_salt('auth'), true)), $parts[1])) {
		return null;
	}
	$cfg = json_decode(base64_decode(strtr($parts[0], '-_', '+/')), true);
	return is_array($cfg) && isset($cfg['id'], $cfg['fields']) ? $cfg : null;
}

function odin_blocks_render_form($attrs, $content, $block) {
	$a = wp_parse_args($attrs, [
		'formId' => '',
		'recipient' => '',
		'subject' => 'Nuevo mensaje desde la web',
		'submitLabel' => 'Enviar',
		'successMessage' => '¡Gracias! Hemos recibido tu mensaje.',
		'errorMessage' => 'No se pudo enviar. Revisa los campos e inténtalo de nuevo.',
	]);
	$fields = [];
	odin_form_collect_fields($block->parsed_block['innerBlocks'] ?? [], $fields);
	$id = sanitize_key($a['formId']) ?: 'odin-form-' . substr(md5(serialize(array_keys($fields))), 0, 8);
	$to = is_email($a['recipient']) ? $a['recipient'] : get_option('admin_email');

	$token = odin_form_sign([
		'id' => $id,
		'to' => $to,
		'subject' => sanitize_text_field($a['subject']),
		'fields' => $fields,
		't' => time(),
	]);

	$status = '';
	if (isset($_GET['odin_form'], $_GET['odin_status']) && $_GET['odin_form'] === $id) {
		$ok = $_GET['odin_status'] === 'ok';
		$msg = $ok ? $a['successMessage'] : ($_GET['odin_status'] === 'limit' ? 'Demasiados envíos. Inténtalo en unos minutos.' : $a['errorMessage']);
		$status = sprintf('<div class="odin-form__status is-%s" role="status">%s</div>', $ok ? 'ok' : 'error', esc_html($msg));
	}

	return sprintf(
		'<form %1$s method="post" action="%2$s">%3$s<input type="hidden" name="action" value="odin_form">%7$s<input type="hidden" name="_odin" value="%4$s"><div class="odin-form__hp" aria-hidden="true"><label>No rellenar <input type="text" name="odin_hp" tabindex="-1" autocomplete="off"></label></div><div class="odin-form__fields">%5$s</div><button type="submit" class="odin-form__submit wp-element-button">%6$s</button></form>',
		get_block_wrapper_attributes(['class' => 'odin-form', 'id' => $id]),
		esc_url(admin_url('admin-post.php')),
		$status,
		esc_attr($token),
		$content,
		esc_html($a['submitLabel']),
		wp_referer_field(false) // vuelve a esta página aunque el navegador no envíe Referer
	);
}

function odin_blocks_render_field($attrs) {
	$f = odin_form_field_def($attrs);
	$a = wp_parse_args($attrs, ['placeholder' => '', 'width' => '100']);
	$w = in_array($a['width'], ['100', '50', '33'], true) ? $a['width'] : '100';
	$uid = wp_unique_id('odin-f-');
	$name = 'odin[' . $f['name'] . ']';
	$req = $f['required'] ? ' required' : '';
	$ph = $a['placeholder'] !== '' ? ' placeholder="' . esc_attr($a['placeholder']) . '"' : '';
	$label = esc_html($f['label']) . ($f['required'] ? ' <span class="odin-field__req" aria-hidden="true">*</span>' : '');

	switch ($f['type']) {
		case 'textarea':
			$control = sprintf('<textarea id="%s" name="%s" rows="5" maxlength="%d"%s%s></textarea>', $uid, esc_attr($name), ODIN_FORM_MAX_LEN, $req, $ph);
			break;
		case 'select':
			$opts = '<option value="">' . esc_html($a['placeholder'] ?: '—') . '</option>';
			foreach ($f['options'] as $o) {
				$opts .= sprintf('<option value="%1$s">%1$s</option>', esc_attr($o));
			}
			$control = sprintf('<select id="%s" name="%s"%s>%s</select>', $uid, esc_attr($name), $req, $opts);
			break;
		case 'radio':
			$control = '';
			foreach ($f['options'] as $i => $o) {
				$control .= sprintf('<label class="odin-field__choice"><input type="radio" name="%s" value="%s"%s> %s</label>', esc_attr($name), esc_attr($o), $i === 0 ? $req : '', esc_html($o));
			}
			return sprintf('<fieldset class="odin-field is-w-%s"><legend>%s</legend>%s</fieldset>', $w, $label, $control);
		case 'checkbox':
			return sprintf('<div class="odin-field is-checkbox is-w-%s"><label class="odin-field__choice"><input type="checkbox" id="%s" name="%s" value="1"%s> %s</label></div>', $w, $uid, esc_attr($name), $req, $label);
		default:
			$control = sprintf('<input type="%s" id="%s" name="%s" maxlength="%d"%s%s>', $f['type'], $uid, esc_attr($name), ODIN_FORM_MAX_LEN, $req, $ph);
	}
	return sprintf('<div class="odin-field is-w-%s"><label for="%s">%s</label>%s</div>', $w, $uid, $label, $control);
}

// --- Envío ---

function odin_form_redirect($cfg_id, $status) {
	$back = wp_get_referer() ?: home_url('/');
	$back = remove_query_arg(['odin_form', 'odin_status'], $back);
	wp_safe_redirect(add_query_arg(['odin_form' => $cfg_id, 'odin_status' => $status], $back) . '#' . $cfg_id);
	exit;
}

/** Devuelve [datos limpios, hay_error]. Solo acepta los campos definidos en la config firmada. */
function odin_form_validate(array $fields, array $input) {
	$data = [];
	$error = false;
	foreach ($fields as $name => $f) {
		$raw = isset($input[$name]) && is_string($input[$name]) ? wp_unslash($input[$name]) : '';
		$raw = mb_substr($raw, 0, ODIN_FORM_MAX_LEN);
		switch ($f['type']) {
			case 'checkbox':
				$val = $raw === '1' ? 'Sí' : '';
				break;
			case 'email':
				$val = sanitize_email($raw);
				$error = $error || ($raw !== '' && !is_email($val));
				break;
			case 'number':
				$val = trim($raw);
				$error = $error || ($val !== '' && !is_numeric($val));
				break;
			case 'url':
				$val = esc_url_raw(trim($raw));
				break;
			case 'select':
			case 'radio':
				$val = in_array($raw, $f['options'], true) ? $raw : '';
				$error = $error || ($raw !== '' && $val === '');
				break;
			case 'textarea':
				$val = sanitize_textarea_field($raw);
				break;
			default:
				$val = sanitize_text_field($raw);
		}
		if ($f['required'] && $val === '') {
			$error = true;
		}
		$data[$name] = ['label' => $f['label'], 'value' => $val, 'type' => $f['type']];
	}
	return [$data, $error];
}

function odin_form_handle() {
	$cfg = odin_form_verify(isset($_POST['_odin']) ? wp_unslash((string) $_POST['_odin']) : '');
	if (!$cfg) {
		wp_die('Formulario inválido.', '', ['response' => 400]);
	}
	$id = sanitize_key($cfg['id']);

	// Bots: honeypot relleno o envío instantáneo. Se responde "ok" para no darles pistas.
	if (!empty($_POST['odin_hp']) || time() - (int) $cfg['t'] < ODIN_FORM_MIN_SECONDS) {
		odin_form_redirect($id, 'ok');
	}

	$rate_key = 'odin_form_' . md5($_SERVER['REMOTE_ADDR'] ?? '');
	$count = (int) get_transient($rate_key);
	if ($count >= ODIN_FORM_RATE) {
		odin_form_redirect($id, 'limit');
	}

	[$data, $error] = odin_form_validate((array) $cfg['fields'], isset($_POST['odin']) && is_array($_POST['odin']) ? $_POST['odin'] : []);
	if ($error) {
		odin_form_redirect($id, 'error');
	}
	set_transient($rate_key, $count + 1, 10 * MINUTE_IN_SECONDS);

	$lines = [];
	$reply_to = '';
	foreach ($data as $d) {
		$lines[] = $d['label'] . ': ' . $d['value'];
		if ($d['type'] === 'email' && $d['value'] && !$reply_to) {
			$reply_to = $d['value'];
		}
	}
	$page = esc_url_raw(wp_get_referer() ?: '');
	$body = implode("\n", $lines) . "\n\n— Enviado desde: " . $page;
	$subject = $cfg['subject'] ?: 'Nuevo mensaje desde la web';

	// Primero se guarda: si el correo falla, el mensaje no se pierde.
	wp_insert_post([
		'post_type' => 'odin_entry',
		'post_status' => 'private',
		'post_title' => wp_strip_all_tags($subject . ($reply_to ? ' — ' . $reply_to : '')),
		'post_content' => $body,
		'meta_input' => ['_odin_form' => $id, '_odin_data' => $data, '_odin_page' => $page],
	]);

	if (is_email($cfg['to'] ?? '')) {
		wp_mail($cfg['to'], $subject, $body, $reply_to ? ['Reply-To: ' . $reply_to] : []);
	}

	/** Para integraciones (webhooks, CRM, etc.). */
	do_action('odin_form_submitted', $data, $cfg);

	odin_form_redirect($id, 'ok');
}
add_action('admin_post_odin_form', 'odin_form_handle');
add_action('admin_post_nopriv_odin_form', 'odin_form_handle');

// --- Bandeja de envíos en wp-admin ---

add_action('init', static function () {
	register_post_type('odin_entry', [
		'labels' => ['name' => 'Envíos de formularios', 'singular_name' => 'Envío', 'menu_name' => 'Formularios'],
		'public' => false,
		'show_ui' => true,
		'show_in_rest' => false,
		'menu_icon' => 'dashicons-email-alt',
		'supports' => ['title'],
		'capability_type' => 'post',
		'capabilities' => ['create_posts' => 'do_not_allow'],
		'map_meta_cap' => true,
	]);
});

add_action('add_meta_boxes_odin_entry', static function () {
	add_meta_box('odin-entry-data', 'Datos enviados', static function ($post) {
		echo '<table class="widefat striped"><tbody>';
		foreach ((array) get_post_meta($post->ID, '_odin_data', true) as $d) {
			printf('<tr><th style="width:30%%">%s</th><td>%s</td></tr>', esc_html($d['label'] ?? ''), nl2br(esc_html($d['value'] ?? '')));
		}
		echo '</tbody></table>';
		$page = get_post_meta($post->ID, '_odin_page', true);
		if ($page) {
			printf('<p>Página: <a href="%1$s">%1$s</a></p>', esc_url($page));
		}
	}, 'odin_entry', 'normal', 'high');
});
