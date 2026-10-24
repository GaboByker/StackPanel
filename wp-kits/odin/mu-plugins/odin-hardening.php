<?php
/**
 * Plugin Name: Odin Hardening
 * Description: Seguridad y rendimiento base. No bloquea instalar ni actualizar plugins.
 */
defined('ABSPATH') || exit;

// Sin editor de código en wp-admin (instalar/actualizar plugins sigue funcionando).
defined('DISALLOW_FILE_EDIT') || define('DISALLOW_FILE_EDIT', true);
defined('WP_POST_REVISIONS') || define('WP_POST_REVISIONS', 5);
defined('AUTOSAVE_INTERVAL') || define('AUTOSAVE_INTERVAL', 120);
defined('EMPTY_TRASH_DAYS') || define('EMPTY_TRASH_DAYS', 7);

// --- Seguridad ---
add_filter('xmlrpc_enabled', '__return_false');
add_filter('login_errors', static fn($msg) => str_contains($msg, 'Demasiados intentos') ? $msg : 'Usuario o contraseña incorrectos.');
remove_action('wp_head', 'wp_generator');
add_filter('the_generator', '__return_empty_string');

// Ocultar usuarios a visitantes anónimos (REST y ?author=N).
add_filter('rest_endpoints', static function ($endpoints) {
	if (!is_user_logged_in()) {
		unset($endpoints['/wp/v2/users'], $endpoints['/wp/v2/users/(?P<id>[\d]+)']);
	}
	return $endpoints;
});
add_action('template_redirect', static function () {
	if (isset($_GET['author']) && !is_user_logged_in()) {
		wp_safe_redirect(home_url('/'), 301);
		exit;
	}
});

// Límite de intentos de login: 5 fallos por IP => bloqueo de 15 min.
$odin_login_key = static fn() => 'odin_login_' . md5($_SERVER['REMOTE_ADDR'] ?? '');
add_filter('authenticate', static function ($user) use ($odin_login_key) {
	if ((int) get_transient($odin_login_key()) >= 5) {
		return new WP_Error('too_many_attempts', 'Demasiados intentos. Espera 15 minutos.');
	}
	return $user;
}, 30);
add_action('wp_login_failed', static function () use ($odin_login_key) {
	$k = $odin_login_key();
	set_transient($k, (int) get_transient($k) + 1, 15 * MINUTE_IN_SECONDS);
});

// --- Rendimiento ---
remove_action('wp_head', 'print_emoji_detection_script', 7);
remove_action('admin_print_scripts', 'print_emoji_detection_script');
remove_action('wp_print_styles', 'print_emoji_styles');
remove_action('admin_print_styles', 'print_emoji_styles');
add_filter('heartbeat_settings', static function ($s) {
	$s['interval'] = 60;
	return $s;
});
add_filter('woocommerce_allow_marketplace_suggestions', '__return_false');

// jQuery Migrate solo en wp-admin.
add_action('wp_default_scripts', static function ($scripts) {
	if (!is_admin() && isset($scripts->registered['jquery'])) {
		$scripts->registered['jquery']->deps = array_diff($scripts->registered['jquery']->deps, ['jquery-migrate']);
	}
});

// CSS/JS de WooCommerce solo en páginas de tienda o con shortcode/bloque/widget de Woo.
// ponytail: detecta contenido del post actual; si pones un carrito en una cabecera global, añade aquí su condición.
$odin_is_shop = static function () {
	if (!function_exists('is_woocommerce') || is_woocommerce() || is_cart() || is_checkout() || is_account_page()) {
		return true;
	}
	$post = is_singular() ? get_post() : null;
	return $post && preg_match('/\[(woocommerce_|products?|add_to_cart)|wp:woocommerce\//', $post->post_content);
};
add_filter('woocommerce_enqueue_styles', static fn($styles) => $odin_is_shop() ? $styles : []);
add_action('wp_enqueue_scripts', static function () use ($odin_is_shop) {
	if ($odin_is_shop()) {
		return;
	}
	foreach (['wc-add-to-cart', 'woocommerce', 'wc-jquery-blockui', 'wc-js-cookie'] as $h) {
		wp_dequeue_script($h);
	}
	wp_dequeue_style('woocommerce-blocktheme');
}, 99);
