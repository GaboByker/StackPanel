<?php
/**
 * Plugin Name: Odin Blocks
 * Description: Bloques de diseño ligeros para el editor de WordPress: formularios, slider, popup, productos y efectos. Sin JS en el frontend salvo el bloque que lo usa.
 * Version: 1.6.0
 * Requires at least: 6.5
 * Requires PHP: 8.0
 * Text Domain: odin-blocks
 */

defined('ABSPATH') || exit;

define('ODIN_BLOCKS_VERSION', '1.6.0');
define('ODIN_BLOCKS_DIR', __DIR__);
define('ODIN_BLOCKS_URL', plugin_dir_url(__FILE__));

require ODIN_BLOCKS_DIR . '/inc/form.php';
require ODIN_BLOCKS_DIR . '/inc/products.php';
require ODIN_BLOCKS_DIR . '/inc/effects.php';
require ODIN_BLOCKS_DIR . '/inc/mockups.php';
require ODIN_BLOCKS_DIR . '/inc/builder-core.php';
require ODIN_BLOCKS_DIR . '/inc/builder-admin.php';
require ODIN_BLOCKS_DIR . '/inc/builder-theme.php';
require ODIN_BLOCKS_DIR . '/inc/builder-assets.php';

add_action('init', static function () {
	// Un solo script de editor para todos los bloques; cada block.json lo referencia por handle.
	wp_register_script(
		'odin-blocks-editor',
		ODIN_BLOCKS_URL . 'assets/editor.js',
		['wp-blocks', 'wp-element', 'wp-block-editor', 'wp-components', 'wp-i18n', 'wp-hooks', 'wp-compose', 'wp-server-side-render', 'wp-data'],
		ODIN_BLOCKS_VERSION,
		true
	);
	wp_register_style('odin-blocks-editor', ODIN_BLOCKS_URL . 'assets/editor.css', [], ODIN_BLOCKS_VERSION);

	foreach (['form', 'field', 'slider', 'slide', 'popup'] as $name) {
		register_block_type(ODIN_BLOCKS_DIR . '/blocks/' . $name, ['render_callback' => 'odin_blocks_render_' . $name]);
	}
	if (class_exists('WooCommerce')) {
		register_block_type(ODIN_BLOCKS_DIR . '/blocks/products', ['render_callback' => 'odin_blocks_render_products']);
	}
});

add_filter('block_categories_all', static function ($categories) {
	array_unshift($categories, ['slug' => 'odin', 'title' => 'Odin']);
	return $categories;
});

// Los bloques contenedores solo envuelven su contenido interno en el servidor:
// así el HTML guardado es estable y cambiar el diseño nunca invalida bloques ya creados.
function odin_blocks_render_slider($attrs, $content) {
	$a = wp_parse_args($attrs, ['perView' => 1, 'autoplay' => false, 'interval' => 5, 'arrows' => true, 'dots' => true, 'loop' => true, 'gap' => 16]);
	$wrapper = get_block_wrapper_attributes([
		'class' => 'odin-slider',
		'style' => sprintf('--odin-pv:%d;--odin-gap:%dpx', max(1, min(6, (int) $a['perView'])), max(0, (int) $a['gap'])),
		'data-autoplay' => $a['autoplay'] ? max(2, (int) $a['interval']) : '0',
		'data-arrows' => $a['arrows'] ? '1' : '0',
		'data-dots' => $a['dots'] ? '1' : '0',
		'data-loop' => $a['loop'] ? '1' : '0',
		'role' => 'region',
		'aria-roledescription' => 'carrusel',
	]);
	return sprintf('<div %s><div class="odin-slider__track">%s</div></div>', $wrapper, $content);
}

function odin_blocks_render_slide($attrs, $content) {
	return sprintf('<div %s>%s</div>', get_block_wrapper_attributes(['class' => 'odin-slide', 'role' => 'group', 'aria-roledescription' => 'diapositiva']), $content);
}

function odin_blocks_render_popup($attrs, $content) {
	$a = wp_parse_args($attrs, ['trigger' => 'load', 'delay' => 3, 'scroll' => 50, 'anchor' => '', 'frequency' => 'session', 'days' => 7, 'width' => 560, 'popupId' => '']);
	$id = sanitize_key($a['popupId']) ?: 'odin-popup-' . substr(md5($content), 0, 8);
	$wrapper = get_block_wrapper_attributes([
		'class' => 'odin-popup',
		'id' => $id,
		'style' => '--odin-popup-w:' . max(240, (int) $a['width']) . 'px',
		'data-trigger' => in_array($a['trigger'], ['load', 'scroll', 'exit', 'click'], true) ? $a['trigger'] : 'load',
		'data-delay' => max(0, (int) $a['delay']),
		'data-scroll' => max(1, min(100, (int) $a['scroll'])),
		'data-anchor' => sanitize_html_class($a['anchor']),
		'data-frequency' => in_array($a['frequency'], ['always', 'session', 'days'], true) ? $a['frequency'] : 'session',
		'data-days' => max(1, (int) $a['days']),
		'aria-modal' => 'true',
	]);
	return sprintf(
		'<dialog %s><button type="button" class="odin-popup__close" aria-label="%s">&times;</button><div class="odin-popup__body">%s</div></dialog>',
		$wrapper,
		esc_attr__('Cerrar', 'odin-blocks'),
		$content
	);
}
