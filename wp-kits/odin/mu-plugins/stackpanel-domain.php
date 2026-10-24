<?php
/**
 * Plugin Name: StackPanel · dominio
 * Description: El sitio sigue el dominio que le asigna StackPanel. Cuando el proxy anuncia una URL nueva (cabecera firmada), cambia home/siteurl y las URL guardadas en la base de datos (contenido Odin, Yoast, opciones). Lo instala la app «WordPress + Odin».
 */

defined('ABSPATH') || exit;

add_action('muplugins_loaded', 'stackpanel_domain_check');

/** El proxy envía X-StackPanel-Url (fija en su config, no el Host del visitante) y X-StackPanel-Key (clave de esta app). */
function stackpanel_domain_check() {
	$url = $_SERVER['HTTP_X_STACKPANEL_URL'] ?? '';
	$key = $_SERVER['HTTP_X_STACKPANEL_KEY'] ?? '';
	if ($url === '' || $key === '' || !preg_match('#^https?://[a-z0-9.-]+$#', $url)) {
		return;
	}
	$file = WP_CONTENT_DIR . '/stackpanel-key.php';
	$secret = is_readable($file) ? (string) include $file : '';
	if ($secret === '' || !hash_equals($secret, $key)) {
		return;
	}
	$from = stackpanel_domain_origin((string) get_option('home'));
	if ($from === '' || $from === $url) {
		return;
	}
	if (!stackpanel_domain_migrate($from, $url)) {
		// Otra petición está migrando: mejor «vuelve en 5 s» que una página con la URL antigua.
		status_header(503);
		header('Retry-After: 5');
		header('Refresh: 5');
		exit('Actualizando el dominio del sitio…');
	}
	// Esta petición ya cargó la URL antigua: se repite para que el primer visitante vea la página buena.
	if (($_SERVER['REQUEST_METHOD'] ?? '') === 'GET' && !headers_sent() && !wp_doing_ajax()) {
		header('Location: ' . $url . ($_SERVER['REQUEST_URI'] ?? '/'), true, 302);
		exit;
	}
}

/** scheme://host[:puerto] de una URL (sin ruta). */
function stackpanel_domain_origin($url) {
	$p = wp_parse_url($url);
	return empty($p['scheme']) || empty($p['host']) ? '' : $p['scheme'] . '://' . $p['host'] . (isset($p['port']) ? ':' . $p['port'] : '');
}

/** Reemplaza el origen antiguo por el nuevo en todas las tablas del sitio (texto, serializado y JSON con \/). Devuelve false si otra petición ya está migrando. */
function stackpanel_domain_migrate($from, $to) {
	global $wpdb;
	// Bloqueo: dos peticiones simultáneas no migran a la vez (caduca a los 10 minutos si algo se cortó).
	if (!add_option('stackpanel_domain_lock', time(), '', 'no')) {
		if (time() - (int) get_option('stackpanel_domain_lock') < 600) {
			return false;
		}
		update_option('stackpanel_domain_lock', time(), 'no');
	}
	@set_time_limit(0);
	ignore_user_abort(true);
	$pairs = [$from => $to, str_replace('/', '\/', $from) => str_replace('/', '\/', $to)];
	$rows = 0;
	$tables = $wpdb->get_col($wpdb->prepare('SHOW TABLES LIKE %s', $wpdb->esc_like($wpdb->prefix) . '%'));
	foreach ($tables as $table) {
		$cols = $wpdb->get_results("SHOW COLUMNS FROM `$table`");
		$pk = array_values(array_filter($cols, static fn($c) => $c->Key === 'PRI'));
		if (count($pk) !== 1) {
			continue; // sin clave primaria simple no se puede actualizar fila a fila con seguridad
		}
		$pk = $pk[0]->Field;
		foreach ($cols as $c) {
			if (!preg_match('/char|text/i', $c->Type) || $c->Field === $pk || ($table === $wpdb->posts && $c->Field === 'guid')) {
				continue; // el GUID de una entrada no debe cambiar
			}
			$like = implode(' OR ', array_map(static fn($f) => $wpdb->prepare("`{$c->Field}` LIKE %s", '%' . $wpdb->esc_like($f) . '%'), array_keys($pairs)));
			foreach ($wpdb->get_results("SELECT `$pk` AS id, `{$c->Field}` AS v FROM `$table` WHERE $like") as $row) {
				$new = stackpanel_domain_replace($row->v, $pairs);
				if ($new !== $row->v && $wpdb->update($table, [$c->Field => $new], [$pk => $row->id]) !== false) {
					++$rows;
				}
			}
		}
	}
	wp_cache_flush();
	$history = (array) get_option('stackpanel_domain_history', []);
	// Solo hosts (sin esquema): así una migración futura no reescribe el historial.
	$history[] = ['from' => wp_parse_url($from, PHP_URL_HOST) . (wp_parse_url($from, PHP_URL_PORT) ? ':' . wp_parse_url($from, PHP_URL_PORT) : ''), 'to' => wp_parse_url($to, PHP_URL_HOST), 'rows' => $rows, 'at' => time()];
	update_option('stackpanel_domain_history', array_slice($history, -20), 'no');
	delete_option('stackpanel_domain_lock');
	wp_cache_flush();
	return true;
}

/** Texto plano o serializado (se recorre y se vuelve a serializar para que las longitudes cuadren). */
function stackpanel_domain_replace($value, array $pairs) {
	if (is_serialized($value)) {
		$data = @unserialize($value, ['allowed_classes' => false]);
		// Si no se puede leer se deja tal cual: reemplazar a ciegas rompería las longitudes.
		return $data === false && $value !== serialize(false) ? $value : serialize(stackpanel_domain_walk($data, $pairs));
	}
	return strtr($value, $pairs);
}

function stackpanel_domain_walk($data, array $pairs) {
	if (is_string($data)) {
		return stackpanel_domain_replace($data, $pairs); // también serializado dentro de serializado
	}
	if (is_array($data)) {
		foreach ($data as $k => $v) {
			$data[$k] = stackpanel_domain_walk($v, $pairs);
		}
	}
	return $data; // objetos sin clase cargada (__PHP_Incomplete_Class) se conservan intactos
}
