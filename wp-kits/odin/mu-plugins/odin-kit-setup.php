<?php
/**
 * Plugin Name: Odin Kit (configuración inicial)
 * Description: En el primer arranque activa Odin Blocks, WooCommerce, Yoast SEO y Site Kit, pone enlaces permanentes limpios y añade las reglas de seguridad y caché del servidor. Lo instala la app «WordPress + Odin» de StackPanel; después no hace nada.
 */

defined('ABSPATH') || exit;

add_action('init', static function () {
	if (get_option('odin_kit_setup') || wp_installing() || !is_blog_installed()) {
		return;
	}
	// Se marca primero: dos peticiones simultáneas no activan los plugins dos veces.
	update_option('odin_kit_setup', time());

	require_once ABSPATH . 'wp-admin/includes/plugin.php';
	require_once ABSPATH . 'wp-admin/includes/misc.php';
	require_once ABSPATH . 'wp-admin/includes/file.php';
	require_once ABSPATH . 'wp-admin/includes/theme.php';
	require_once ABSPATH . 'wp-admin/includes/class-wp-upgrader.php';

	// Solo los plugins del kit: fuera los de ejemplo de la imagen oficial y los temas que no se usan.
	$extra = array_values(array_filter(['akismet/akismet.php', 'hello.php'], static fn($p) => file_exists(WP_PLUGIN_DIR . '/' . $p)));
	if ($extra) {
		delete_plugins($extra);
	}
	foreach (wp_get_themes() as $slug => $theme) {
		if ($slug !== get_stylesheet() && $slug !== get_template()) {
			delete_theme($slug);
		}
	}

	// Traducciones de los plugins antes de activarlos: WooCommerce crea sus páginas (Tienda, Carrito…) en el idioma del sitio.
	wp_update_plugins();
	$translations = wp_get_translation_updates();
	if ($translations) {
		(new Language_Pack_Upgrader(new Automatic_Upgrader_Skin()))->bulk_upgrade($translations);
	}

	foreach (['odin-blocks/odin-blocks.php', 'woocommerce/woocommerce.php', 'wordpress-seo/wp-seo.php', 'google-site-kit/google-site-kit.php'] as $plugin) {
		if (file_exists(WP_PLUGIN_DIR . '/' . $plugin) && !is_plugin_active($plugin)) {
			activate_plugin($plugin);
		}
	}

	// Enlaces permanentes limpios (mejor para SEO); también regenera las reglas de WordPress en .htaccess.
	update_option('permalink_structure', '/%postname%/');
	flush_rewrite_rules(true);

	// Servidor (Apache): sin XML-RPC (fuerza bruta) y caché del navegador para estáticos versionados (?ver=).
	insert_with_markers(ABSPATH . '.htaccess', 'Odin', [
		'<Files xmlrpc.php>',
		'	Require all denied',
		'</Files>',
		'<IfModule mod_expires.c>',
		'	ExpiresActive On',
		'	ExpiresByType text/css "access plus 1 year"',
		'	ExpiresByType text/javascript "access plus 1 year"',
		'	ExpiresByType application/javascript "access plus 1 year"',
		'	ExpiresByType font/woff2 "access plus 1 year"',
		'	ExpiresByType image/svg+xml "access plus 1 year"',
		'	ExpiresByType image/webp "access plus 6 months"',
		'	ExpiresByType image/png "access plus 6 months"',
		'	ExpiresByType image/jpeg "access plus 6 months"',
		'</IfModule>',
	]);

	// Nunca ejecutar PHP subido a la biblioteca de medios.
	$uploads = wp_get_upload_dir()['basedir'];
	if (wp_mkdir_p($uploads) && !file_exists($uploads . '/.htaccess')) {
		file_put_contents($uploads . '/.htaccess', "<FilesMatch \"\\.(php[0-9]?|phtml|phar)$\">\n\tRequire all denied\n</FilesMatch>\n");
	}
}, 1);
