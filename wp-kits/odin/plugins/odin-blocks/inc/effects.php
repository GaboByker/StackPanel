<?php
/**
 * Efectos para cualquier bloque: animación de entrada y ocultar por dispositivo.
 * El editor guarda los atributos odinAnim / odinHide; aquí se convierten en clases.
 * El CSS/JS de efectos solo se carga en páginas que los usan.
 */

defined('ABSPATH') || exit;

const ODIN_ANIMS = ['fade', 'fade-up', 'fade-down', 'fade-left', 'fade-right', 'zoom'];

add_action('init', static function () {
	wp_register_style('odin-effects', ODIN_BLOCKS_URL . 'assets/effects.css', [], ODIN_BLOCKS_VERSION);
	wp_register_script('odin-effects', ODIN_BLOCKS_URL . 'assets/effects.js', [], ODIN_BLOCKS_VERSION, ['strategy' => 'defer', 'in_footer' => true]);
});

// Los atributos también deben existir en servidor: si no, la vista previa REST de bloques dinámicos da 400.
add_filter('register_block_type_args', static function ($args) {
	$args['attributes'] = ($args['attributes'] ?? []) + [
		'odinAnim' => ['type' => 'string'],
		'odinDelay' => ['type' => 'number'],
		'odinHide' => ['type' => 'array', 'items' => ['type' => 'string']],
	];
	return $args;
});

add_filter('render_block', static function ($html, $block) {
	$attrs = $block['attrs'] ?? [];
	if ((empty($attrs['odinAnim']) && empty($attrs['odinHide'])) || $html === '') {
		return $html;
	}
	$classes = [];
	if (!empty($attrs['odinAnim']) && in_array($attrs['odinAnim'], ODIN_ANIMS, true)) {
		$classes[] = 'odin-anim';
		$classes[] = 'odin-anim--' . $attrs['odinAnim'];
		wp_enqueue_script('odin-effects');
	}
	foreach ((array) ($attrs['odinHide'] ?? []) as $device) {
		if (in_array($device, ['mobile', 'tablet', 'desktop'], true)) {
			$classes[] = 'odin-hide-' . $device;
		}
	}
	if (!$classes) {
		return $html;
	}
	wp_enqueue_style('odin-effects');

	$p = new WP_HTML_Tag_Processor($html);
	if ($p->next_tag()) {
		foreach ($classes as $c) {
			$p->add_class($c);
		}
		if (!empty($attrs['odinDelay'])) {
			$style = (string) $p->get_attribute('style');
			$p->set_attribute('style', trim($style . ';--odin-delay:' . min(3000, max(0, (int) $attrs['odinDelay'])) . 'ms', ';'));
		}
		return $p->get_updated_html();
	}
	return $html;
}, 10, 2);
