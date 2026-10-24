<?php
/**
 * Odin Theme Builder: plantillas globales ([odin_template]), cabecera/pie/producto único
 * aplicados automáticamente, y ajustes de página con valores por defecto.
 */

defined('ABSPATH') || exit;

const ODIN_TPL_TYPES = [
	'section' => 'Sección global (shortcode)',
	'header' => 'Cabecera (toda la web)',
	'footer' => 'Pie de página (toda la web)',
	'single-product' => 'Producto único (WooCommerce)',
	'popup' => 'Popup / mensaje emergente (toda la web)',
];
const ODIN_LAYOUTS = ['odin' => 'Odin (cabecera y pie Odin, sin márgenes del tema)', 'default' => 'Del tema', 'full' => 'Ancho completo', 'canvas' => 'Lienzo (sin cabecera ni pie)'];

// ---------------------------------------------------------------- tipo de contenido

add_action('init', static function () {
	register_post_type('odin_template', [
		'labels' => [
			'name' => 'Plantillas Odin', 'singular_name' => 'Plantilla', 'menu_name' => 'Odin',
			'all_items' => 'Plantillas', 'add_new' => 'Añadir plantilla', 'add_new_item' => 'Añadir plantilla',
			'edit_item' => 'Editar plantilla', 'search_items' => 'Buscar plantillas', 'not_found' => 'No hay plantillas',
		],
		'public' => false,
		'publicly_queryable' => true, // necesario para el lienzo del editor; los visitantes reciben 404
		'exclude_from_search' => true,
		'show_ui' => true,
		'show_in_menu' => true,
		'show_in_rest' => false,
		'show_in_nav_menus' => false,
		'menu_icon' => 'dashicons-layout',
		'menu_position' => 59,
		'supports' => ['title'],
		'rewrite' => false,
		'query_var' => 'odin_template',
		'capability_type' => 'page',
		'map_meta_cap' => true,
	]);
	add_shortcode('odin_template', static fn($a) => odin_template_render((int) ($a['id'] ?? 0)));
	add_shortcode('odin_node', 'odin_builder_node_shortcode');
	add_shortcode('odin_year', static fn() => wp_date('Y'));
	// Ubicación de menú: activa Apariencia → Menús también con temas de bloques.
	register_nav_menus(['odin-main' => 'Menú principal (Odin)', 'odin-footer' => 'Menú del pie (Odin)']);
	wp_register_style('odin-kit', false, [], ODIN_BLOCKS_VERSION);
	wp_register_script('odin-widgets', ODIN_BLOCKS_URL . 'assets/odin-widgets.js', [], ODIN_BLOCKS_VERSION, ['strategy' => 'defer', 'in_footer' => true]);
});

// Las plantillas no son páginas públicas: 404 para visitantes, fuera de Yoast y de los buscadores.
add_action('template_redirect', static function () {
	if (is_singular('odin_template') && !current_user_can('edit_pages')) {
		global $wp_query;
		$wp_query->set_404();
		status_header(404);
		nocache_headers();
	}
}, 1);
add_filter('wpseo_sitemap_exclude_post_type', static fn($ex, $type) => $type === 'odin_template' ? true : $ex, 10, 2);
add_filter('wpseo_accessible_post_types', static function ($types) {
	unset($types['odin_template']);
	return $types;
});

function odin_template_type($id) {
	$t = get_post_meta($id, '_odin_tpl_type', true);
	return isset(ODIN_TPL_TYPES[$t]) ? $t : 'section';
}

/** Recalcula qué plantilla está activa por tipo (se guarda en una opción: 0 consultas por visita). */
function odin_templates_refresh() {
	$active = [];
	foreach (['header', 'footer', 'single-product'] as $type) {
		$ids = get_posts([
			'post_type' => 'odin_template', 'post_status' => 'publish', 'numberposts' => 1, 'fields' => 'ids',
			'orderby' => 'modified', 'order' => 'DESC', 'no_found_rows' => true,
			'meta_query' => [['key' => '_odin_tpl_type', 'value' => $type], ['key' => '_odin_tpl_active', 'value' => '1']],
		]);
		if ($ids) {
			$active[$type] = (int) $ids[0];
		}
	}
	$active['popup'] = array_map('intval', get_posts([
		'post_type' => 'odin_template', 'post_status' => 'publish', 'numberposts' => 20, 'fields' => 'ids', 'no_found_rows' => true,
		'meta_query' => [['key' => '_odin_tpl_type', 'value' => 'popup'], ['key' => '_odin_tpl_active', 'value' => '1']],
	]));
	update_option('odin_active_templates', $active, true);
}
foreach (['trashed_post', 'untrashed_post', 'deleted_post'] as $hook) {
	add_action($hook, static function ($id) {
		if (get_post_type($id) === 'odin_template') {
			odin_templates_refresh();
		}
	});
}

function odin_active_template_id($type) {
	$active = (array) get_option('odin_active_templates', []);
	return (int) ($active[$type] ?? 0);
}

// ---------------------------------------------------------------- render de plantillas

/** Registra el CSS de un árbol y carga solo los extras que su HTML necesita. */
function odin_builder_enqueue($handle, $css, $html) {
	static $base = false;
	wp_register_style($handle, false, ['odin-kit'], ODIN_BLOCKS_VERSION);
	wp_enqueue_style($handle);
	wp_add_inline_style($handle, ($base ? '' : odin_builder_base_css()) . $css);
	$base = true;
	odin_builder_enqueue_extras($html);
}

function odin_builder_enqueue_extras($html) {
	if (str_contains($html, 'odin-anim')) {
		wp_enqueue_style('odin-effects');
		wp_enqueue_script('odin-effects');
	} elseif (str_contains($html, 'odin-hide-')) {
		wp_enqueue_style('odin-effects');
	}
	if (str_contains($html, 'odin-products')) {
		wp_enqueue_style('odin-products-style');
	}
	if (str_contains($html, 'odin-form')) {
		wp_enqueue_style('odin-form-style');
	}
	if (str_contains($html, 'odn-tabs') || str_contains($html, 'odn-wcimg__thumbs') || str_contains($html, 'odn-menu') || str_contains($html, 'wa-bubble') || str_contains($html, 'pj__open')) {
		wp_enqueue_script('odin-widgets');
	}
	if (str_contains($html, 'obra__stage') && !odin_builder_is_canvas() && function_exists('wp_enqueue_script_module')) {
		wp_enqueue_script_module('odin-obra', ODIN_BLOCKS_URL . 'assets/odin-obra.js', [], ODIN_BLOCKS_VERSION);
	}
}

function odin_template_render($id, $inline_css = false) {
	static $stack = [];
	$post = get_post($id);
	if (!$post || $post->post_type !== 'odin_template' || in_array($id, $stack, true)) {
		return '';
	}
	if ($post->post_status !== 'publish' && !current_user_can('edit_post', $id)) {
		return '';
	}
	$tree = odin_builder_get_tree($id);
	if (!$tree) {
		return '';
	}
	// Dentro de otra página la plantilla no es editable: sin data-odn ni marcadores.
	$stack[] = $id;
	$was_preview = odin_builder_preview();
	odin_builder_preview(false);
	$prev_ctx = odin_builder_ctx($id);
	$html = do_shortcode(odin_builder_render($tree));
	odin_builder_ctx($prev_ctx);
	odin_builder_preview($was_preview);
	array_pop($stack);

	$css = (string) get_post_meta($id, '_odin_builder_css', true);
	if ($inline_css) {
		$html = '<style>' . odin_builder_base_css() . $css . '</style>' . $html;
	} else {
		odin_builder_enqueue('odin-tpl-' . $id, $css, $html);
	}
	return '<div class="odin-builder odin-template odin-template-' . (int) $id . '">' . $html . '</div>';
}

function odin_site_part($type) {
	if ($id = odin_active_template_id($type)) {
		return sprintf('<%1$s class="odin-site-%1$s">%2$s</%1$s>', $type, odin_template_render($id));
	}
	if (function_exists('wp_is_block_theme') && wp_is_block_theme()) {
		ob_start();
		block_template_part($type);
		return ob_get_clean();
	}
	return '';
}

// Cabecera/pie del tema de bloques → plantilla Odin activa (en toda la web, también páginas nuevas).
// pre_render_block: la cabecera/pie del tema ni se renderiza (ni carga su CSS).
add_filter('pre_render_block', static function ($pre, $block) {
	if ($pre !== null || ($block['blockName'] ?? '') !== 'core/template-part' || is_admin()) {
		return $pre;
	}
	// Al editar una cabecera/pie en Odin, el lienzo muestra la del tema para no duplicarla.
	if (odin_builder_is_canvas() && is_singular('odin_template')) {
		return $pre;
	}
	$slug = (string) ($block['attrs']['slug'] ?? '');
	foreach (['header', 'footer'] as $type) {
		if (str_starts_with($slug, $type) && ($id = odin_active_template_id($type))) {
			return sprintf('<%1$s class="odin-site-%1$s">%2$s</%1$s>', $type, odin_template_render($id));
		}
	}
	return $pre;
}, 10, 2);

// Producto único con plantilla Odin y páginas en modo "lienzo".
add_filter('template_include', static function ($template) {
	// Las plantillas Odin se editan sobre un lienzo limpio (sin título ni metadatos de la plantilla de entrada del tema).
	if (is_singular('odin_template')) {
		$GLOBALS['odin_page_mode'] = 'canvas';
		return ODIN_BLOCKS_DIR . '/templates/odin-page.php';
	}
	// En el lienzo, las páginas Odin usan su misma plantilla (lo que ves al editar = lo publicado).
	if (odin_builder_is_canvas() && !(is_singular(['page', 'post']) && in_array(odin_page_settings()['layout'], ['canvas', 'odin'], true))) {
		return $template;
	}
	if (!odin_builder_is_canvas() && function_exists('is_product') && is_product() && odin_active_template_id('single-product')) {
		$GLOBALS['odin_page_mode'] = 'product';
		return ODIN_BLOCKS_DIR . '/templates/odin-page.php';
	}
	if (is_singular(['page', 'post']) && in_array(odin_page_settings()['layout'], ['canvas', 'odin'], true)) {
		$GLOBALS['odin_page_mode'] = odin_page_settings()['layout'] === 'odin' ? 'page' : 'canvas';
		// En páginas 100 % Odin el diseño sale de la configuración global: fuera los estilos globales del tema.
		add_action('wp_enqueue_scripts', static function () {
			wp_dequeue_style('global-styles');
			wp_dequeue_style('classic-theme-styles');
		}, 100);
		return ODIN_BLOCKS_DIR . '/templates/odin-page.php';
	}
	return $template;
}, 99);

// ---------------------------------------------------------------- ajustes de página

function odin_page_defaults() {
	return wp_parse_args((array) get_option('odin_defaults', []), ['layout' => 'default', 'hideTitle' => false, 'bg' => '', 'scene' => 'default']);
}

/** Ajustes efectivos de una página hecha con Odin (los de la página o, si no tiene, los por defecto). */
function odin_page_settings($id = null) {
	$id = $id ?: get_queried_object_id();
	$off = ['layout' => 'default', 'hideTitle' => false, 'bg' => '', 'scene' => 'none', 'odin' => false];
	if (!$id || !in_array(get_post_type($id), ['page', 'post'], true) || odin_builder_get_tree($id) === null) {
		return $off;
	}
	$d = odin_page_defaults();
	$p = (array) get_post_meta($id, '_odin_page', true);
	return [
		'layout' => isset(ODIN_LAYOUTS[$p['layout'] ?? '']) ? $p['layout'] : $d['layout'],
		'hideTitle' => isset($p['hideTitle']) && $p['hideTitle'] !== '' ? $p['hideTitle'] === '1' : (bool) $d['hideTitle'],
		'bg' => !empty($p['bg']) ? $p['bg'] : $d['bg'],
		'scene' => isset(odin_scenes_list()[$p['scene'] ?? '']) ? $p['scene'] : (isset(odin_scenes_list()[$d['scene']]) ? $d['scene'] : 'default'),
		'odin' => true,
	];
}

function odin_page_clean(array $p) {
	return [
		'layout' => isset(ODIN_LAYOUTS[$p['layout'] ?? '']) ? $p['layout'] : '',
		'hideTitle' => in_array($p['hideTitle'] ?? '', ['1', '0'], true) ? $p['hideTitle'] : '',
		'bg' => !empty($p['bg']) ? (string) odin_builder_clean_value('color', $p['bg']) : '',
		'scene' => isset(odin_scenes_list()[$p['scene'] ?? '']) ? $p['scene'] : '',
	];
}

// ---------------------------------------------------------------- kit de diseño (CSS global, fuentes, fondo 3D)

function odin_kit() {
	return wp_parse_args((array) get_option('odin_kit', []), ['css' => '', 'fonts' => '', 'scene' => false, 'particles' => 3000, 'rings' => true, 'speed' => 1, 'side' => 'right']);
}

/** Escena 3D de la petición: la de la página o, para editores, la de ?odin_scene= (vista previa desde Ajustes). */
function odin_scene_for_request() {
	if (isset($_GET['odin_scene']) && current_user_can('edit_pages') && isset(odin_scenes_list()[sanitize_key($_GET['odin_scene'])])) {
		return sanitize_key($_GET['odin_scene']);
	}
	$ps = is_singular(['page', 'post']) ? odin_page_settings() : null;
	return $ps && $ps['odin'] ? $ps['scene'] : 'none';
}

/** Colores globales: nombre de variable CSS => [etiqueta, valor por defecto (paleta ODIN.01)]. */
const ODIN_GLOBAL_COLORS = [
	'bg' => ['Fondo', '#070b14'],
	'surface' => ['Superficie (tarjetas)', 'rgba(17, 24, 39, 0.62)'],
	'surface-solid' => ['Superficie sólida', '#111827'],
	'text' => ['Texto', '#e5e9f0'],
	'muted' => ['Texto secundario', '#a3adbf'],
	'primary' => ['Primario', '#3b82f6'],
	'primary-strong' => ['Primario fuerte', '#60a5fa'],
	'accent' => ['Acento (botones)', '#f5b841'],
	'on-accent' => ['Texto sobre acento', '#111827'],
	'border' => ['Bordes', 'rgba(148, 163, 184, 0.18)'],
];

function odin_global() {
	$g = wp_parse_args((array) get_option('odin_global', []), ['colors' => [], 'fontHead' => 'Outfit', 'fontBody' => 'Work Sans', 'radius' => '16px']);
	foreach (ODIN_GLOBAL_COLORS as $k => [, $def]) {
		$g['colors'][$k] = !empty($g['colors'][$k]) ? $g['colors'][$k] : $def;
	}
	return $g;
}

/** Variables CSS globales: las usan el kit, los widgets y también el tema (WooCommerce, carrito…). */
function odin_global_css() {
	$g = odin_global();
	$css = ':root{';
	foreach ($g['colors'] as $k => $v) {
		$css .= "--$k:$v;";
	}
	$font = static fn($f) => '"' . str_replace('"', '', $f) . '",system-ui,sans-serif';
	$css .= '--font-head:' . $font($g['fontHead']) . ';--font-body:' . $font($g['fontBody']) . ';--radius:' . $g['radius'] . ';'
		. '}';
	// Páginas del tema (tienda, carrito…): sus colores pasan a ser los globales, solo si se guardó una
	// configuración global (un sitio recién instalado conserva el aspecto por defecto del tema).
	if (get_option('odin_global') !== false) {
		$css .= 'body{--wp--preset--color--base:var(--bg);--wp--preset--color--contrast:var(--text);--wp--preset--color--accent-1:var(--accent);--wp--preset--color--accent-2:var(--primary);--wp--preset--font-family--manrope:var(--font-body)}';
	}
	return $css;
}

function odin_global_fonts_url() {
	$g = odin_global();
	$fams = array_unique(array_filter([$g['fontHead'], $g['fontBody']]));
	if (!$fams) {
		return '';
	}
	return 'https://fonts.googleapis.com/css2?' . implode('&', array_map(static fn($f) => 'family=' . str_replace('%20', '+', rawurlencode($f)) . ':wght@400;500;600;700', $fams)) . '&display=swap';
}

add_action('wp_enqueue_scripts', static function () {
	$kit = odin_kit();
	$fonts = $kit['fonts'] ?: odin_global_fonts_url();
	if ($fonts && str_starts_with($fonts, 'https://fonts.googleapis.com/')) {
		wp_enqueue_style('odin-fonts', $fonts, [], null);
	}
	// Variables globales siempre (también para widgets sin kit); el kit va justo después.
	wp_enqueue_style('odin-kit');
	wp_add_inline_style('odin-kit', odin_global_css() . $kit['css']);
	if ($kit['css'] === '') {
		return;
	}
	wp_enqueue_script('odin-kit', ODIN_BLOCKS_URL . 'assets/odin-kit.js', [], ODIN_BLOCKS_VERSION, ['strategy' => 'defer', 'in_footer' => true]);
	if ($kit['scene'] && odin_scene_for_request() !== 'none' && !odin_builder_is_canvas() && function_exists('wp_enqueue_script_module')) {
		wp_enqueue_script_module('odin-scene', ODIN_BLOCKS_URL . 'assets/odin-scene.js', [], ODIN_BLOCKS_VERSION);
		// Ajustes editables de la escena (Odin → Ajustes → Fondo 3D animado).
		add_action('wp_head', static function () use ($kit) {
			wp_print_inline_script_tag('window.odinScene3D=' . wp_json_encode([
				'particles' => max(0, min(6000, (int) $kit['particles'])),
				'rings' => (bool) $kit['rings'],
				'speed' => max(0.1, min(4, (float) $kit['speed'])),
				'side' => $kit['side'] === 'center' ? 'center' : 'right',
				'parts' => odin_scenes()[odin_scene_for_request()]['parts'] ?? [],
			]) . ';');
		}, 2);
	}
}, 1);

// Clase "js" en <html> antes de pintar: el menú se oculta en móvil solo si hay JavaScript.
add_action('wp_head', static function () {
	if (odin_kit()['css'] !== '') {
		echo "<script>document.documentElement.classList.add('js')</script>\n";
	}
}, 1);
add_filter('body_class', static function ($classes) {
	if (odin_kit()['scene'] && odin_scene_for_request() !== 'none') {
		$classes[] = 'odin-scene-' . odin_scene_for_request();
	}
	return $classes;
});

// ---------------------------------------------------------------- popups (mensajes emergentes)

function odin_popup_settings($id) {
	return wp_parse_args((array) get_post_meta($id, '_odin_popup', true), ['trigger' => 'load', 'delay' => 3, 'scroll' => 50, 'frequency' => 'session', 'days' => 7, 'width' => 560]);
}

function odin_popup_clean(array $p) {
	return [
		'trigger' => in_array($p['trigger'] ?? '', ['load', 'scroll', 'exit', 'click'], true) ? $p['trigger'] : 'load',
		'delay' => max(0, min(120, (int) ($p['delay'] ?? 3))),
		'scroll' => max(1, min(100, (int) ($p['scroll'] ?? 50))),
		'frequency' => in_array($p['frequency'] ?? '', ['always', 'session', 'days'], true) ? $p['frequency'] : 'session',
		'days' => max(1, min(365, (int) ($p['days'] ?? 7))),
		'width' => max(240, min(1400, (int) ($p['width'] ?? 560))),
	];
}

add_action('wp_footer', static function () {
	if (is_admin() || is_singular('odin_template') || odin_builder_is_canvas()) {
		return;
	}
	$ids = (array) (get_option('odin_active_templates', [])['popup'] ?? []);
	$out = '';
	foreach ($ids as $id) {
		$html = odin_template_render((int) $id);
		if ($html === '') {
			continue;
		}
		$p = odin_popup_settings($id);
		$out .= sprintf(
			'<dialog class="odin-popup" id="odin-popup-%1$d" style="--odin-popup-w:%2$dpx" data-trigger="%3$s" data-delay="%4$d" data-scroll="%5$d" data-anchor="" data-frequency="%6$s" data-days="%7$d" aria-modal="true"><button type="button" class="odin-popup__close" aria-label="Cerrar">&times;</button><div class="odin-popup__body">%8$s</div></dialog>',
			$id, $p['width'], esc_attr($p['trigger']), $p['delay'], $p['scroll'], esc_attr($p['frequency']), $p['days'], $html
		);
	}
	if ($out) {
		wp_enqueue_style('odin-popup-style');
		wp_enqueue_script('odin-popup-view-script');
		echo $out; // phpcs:ignore WordPress.Security.EscapeOutput -- HTML de plantillas Odin ya saneado
	}
}, 5);

add_filter('body_class', static function ($classes) {
	if (is_singular(['page', 'post']) && ($ps = odin_page_settings()) && $ps['odin']) {
		$classes[] = 'odin-layout-' . $ps['layout'];
	}
	return $classes;
});

add_filter('render_block', static function ($html, $block, $instance) {
	if (($block['blockName'] ?? '') === 'core/post-title' && is_singular(['page', 'post'])
		&& (int) ($instance->context['postId'] ?? 0) === get_queried_object_id() && odin_page_settings()['hideTitle']) {
		return '';
	}
	return $html;
}, 10, 3);

add_action('wp_enqueue_scripts', static function () {
	if (!is_singular(['page', 'post'])) {
		return;
	}
	$ps = odin_page_settings();
	if (!$ps['odin']) {
		return;
	}
	$css = '';
	if ($ps['layout'] === 'full') {
		// La página ocupa todo el ancho: anula el ancho de contenido del tema para el diseño Odin.
		$css .= '.odin-layout-full .wp-block-post-content>.odin-builder,.odin-layout-full .entry-content>.odin-builder{max-width:none!important;margin-left:calc(-1*var(--wp--style--root--padding-left,0px))!important;margin-right:calc(-1*var(--wp--style--root--padding-right,0px))!important}';
	}
	if ($ps['bg']) {
		$css .= 'body{background:' . $ps['bg'] . '}';
	}
	if ($css) {
		wp_register_style('odin-page', false, [], ODIN_BLOCKS_VERSION);
		wp_enqueue_style('odin-page');
		wp_add_inline_style('odin-page', $css);
	}
}, 20);

// ---------------------------------------------------------------- administración

add_action('add_meta_boxes_odin_template', static function ($post) {
	add_meta_box('odin-tpl', 'Ajustes de la plantilla', static function ($post) {
		wp_nonce_field('odin_tpl_save', 'odin_tpl_nonce');
		$type = odin_template_type($post->ID);
		$active = get_post_meta($post->ID, '_odin_tpl_active', true) === '1';
		echo '<p><label for="odin_tpl_type"><strong>Tipo</strong></label><br><select name="odin_tpl_type" id="odin_tpl_type">';
		foreach (ODIN_TPL_TYPES as $k => $label) {
			printf('<option value="%s"%s>%s</option>', esc_attr($k), selected($type, $k, false), esc_html($label));
		}
		echo '</select></p>';
		printf('<p><label><input type="checkbox" name="odin_tpl_active" value="1"%s> <strong>Activa</strong>: la cabecera/pie/producto se aplica automáticamente en toda la web (incluidas las páginas nuevas).</label></p>', checked($active, true, false));
		if ($post->post_status !== 'auto-draft') {
			printf('<p>Shortcode para insertarla en cualquier página: <code>[odin_template id="%d"]</code></p>', $post->ID);
		}
		echo '<p><button type="submit" name="odin_open_builder" value="1" class="button button-primary button-large">Guardar y editar con Odin</button></p>';
	}, 'odin_template', 'normal', 'high');
});

add_action('save_post_odin_template', static function ($id) {
	if (!isset($_POST['odin_tpl_nonce']) || !wp_verify_nonce(sanitize_key($_POST['odin_tpl_nonce']), 'odin_tpl_save') || !current_user_can('edit_post', $id) || wp_is_post_revision($id)) {
		return;
	}
	$type = sanitize_key($_POST['odin_tpl_type'] ?? 'section');
	update_post_meta($id, '_odin_tpl_type', isset(ODIN_TPL_TYPES[$type]) ? $type : 'section');
	update_post_meta($id, '_odin_tpl_active', empty($_POST['odin_tpl_active']) ? '0' : '1');
});
add_action('save_post_odin_template', static fn() => odin_templates_refresh(), 20);

// Una plantilla recién creada desde el menú se publica (si no, no se puede previsualizar en el lienzo).
add_filter('wp_insert_post_data', static function ($data, $raw) {
	if ($data['post_type'] === 'odin_template' && $data['post_status'] === 'draft' && !empty($raw['odin_open_builder']) && current_user_can('publish_pages')) {
		$data['post_status'] = 'publish';
	}
	return $data;
}, 10, 2);

add_filter('redirect_post_location', static function ($location, $id) {
	return !empty($_POST['odin_open_builder']) && get_post_type($id) === 'odin_template' ? odin_builder_edit_url($id) : $location;
}, 10, 2);

add_filter('manage_odin_template_posts_columns', static function ($cols) {
	return array_slice($cols, 0, 2, true) + ['odin_type' => 'Tipo', 'odin_active' => 'Activa', 'odin_code' => 'Shortcode'] + $cols;
});
add_action('manage_odin_template_posts_custom_column', static function ($col, $id) {
	if ($col === 'odin_type') {
		echo esc_html(ODIN_TPL_TYPES[odin_template_type($id)]);
	} elseif ($col === 'odin_active') {
		echo get_post_meta($id, '_odin_tpl_active', true) === '1' && odin_template_type($id) !== 'section' ? '<span style="color:#15803d">● Activa</span>' : '—';
	} elseif ($col === 'odin_code') {
		printf('<code style="user-select:all">[odin_template id="%d"]</code>', $id);
	}
}, 10, 2);

// Ajustes por defecto de las páginas Odin.
add_action('admin_menu', static function () {
	// Atajo: los menús del sitio (cabecera y pie) se editan en la pantalla de Menús de WordPress.
	add_submenu_page('edit.php?post_type=odin_template', 'Menús', 'Menús', 'edit_theme_options', 'nav-menus.php');
	add_submenu_page('edit.php?post_type=odin_template', 'Ajustes de Odin', 'Ajustes', 'manage_options', 'odin-settings', static function () {
		$d = odin_page_defaults();
		?>
		<div class="wrap">
			<h1>Ajustes de Odin</h1>
			<?php if (isset($_GET['updated'])) : ?><div class="notice notice-success"><p>Ajustes guardados.</p></div><?php endif; ?>
			<p>Valores por defecto de todas las páginas diseñadas con Odin. Cada página puede cambiarlos desde el editor (icono de engranaje).</p>
			<form method="post" action="<?php echo esc_url(admin_url('admin-post.php')); ?>">
				<input type="hidden" name="action" value="odin_settings">
				<?php wp_nonce_field('odin_settings'); ?>
				<table class="form-table" role="presentation">
					<tr><th scope="row"><label for="odin-layout">Diseño de página</label></th><td><select id="odin-layout" name="layout">
						<?php foreach (ODIN_LAYOUTS as $k => $label) : ?><option value="<?php echo esc_attr($k); ?>" <?php selected($d['layout'], $k); ?>><?php echo esc_html($label); ?></option><?php endforeach; ?>
					</select></td></tr>
					<tr><th scope="row">Título de la página</th><td><label><input type="checkbox" name="hideTitle" value="1" <?php checked($d['hideTitle']); ?>> Ocultar el título que pone el tema</label></td></tr>
					<tr><th scope="row"><label for="odin-bg">Color de fondo</label></th><td><input id="odin-bg" type="text" name="bg" value="<?php echo esc_attr($d['bg']); ?>" placeholder="#ffffff (vacío = el del tema)"></td></tr>
				</table>
				<h2>Fondo 3D animado</h2>
				<p>Escenas, piezas 3D, partículas, anillos y velocidad: <a class="button" href="<?php echo esc_url(admin_url('edit.php?post_type=odin_template&page=odin-3d')); ?>">Abrir Odin → Fondo 3D</a> · Mockups animados: <a class="button" href="<?php echo esc_url(admin_url('edit.php?post_type=odin_template&page=odin-mockups')); ?>">Abrir Odin → Mockups</a></p>
				<?php $g = odin_global(); ?>
				<h2>Configuración global</h2>
				<p>Colores y tipografías de todo el sitio. Los widgets los usan por defecto; en cada elemento puedes elegir otro color o volver al global.</p>
				<table class="form-table" role="presentation">
					<?php foreach (ODIN_GLOBAL_COLORS as $k => [$label, $def]) : ?>
					<tr><th scope="row"><label for="odin-c-<?php echo esc_attr($k); ?>"><?php echo esc_html($label); ?></label></th>
						<td><input id="odin-c-<?php echo esc_attr($k); ?>" type="text" name="colors[<?php echo esc_attr($k); ?>]" value="<?php echo esc_attr($g['colors'][$k]); ?>" data-default="<?php echo esc_attr($def); ?>" class="odin-color" style="width:220px"> <span class="odin-swatch" style="display:inline-block;width:28px;height:28px;vertical-align:middle;border-radius:6px;border:1px solid #ccc;background:<?php echo esc_attr($g['colors'][$k]); ?>"></span> <code>var(--<?php echo esc_html($k); ?>)</code></td></tr>
					<?php endforeach; ?>
					<tr><th scope="row"><label for="odin-fh">Fuente de títulos</label></th><td><input id="odin-fh" type="text" name="fontHead" value="<?php echo esc_attr($g['fontHead']); ?>" placeholder="Outfit"> <span class="description">Nombre exacto de Google Fonts</span></td></tr>
					<tr><th scope="row"><label for="odin-fb">Fuente del texto</label></th><td><input id="odin-fb" type="text" name="fontBody" value="<?php echo esc_attr($g['fontBody']); ?>" placeholder="Work Sans"></td></tr>
					<tr><th scope="row"><label for="odin-radius">Radio de bordes</label></th><td><input id="odin-radius" type="text" name="radius" value="<?php echo esc_attr($g['radius']); ?>" placeholder="16px"></td></tr>
				</table>
				<script>document.querySelectorAll('.odin-color').forEach(function(i){i.addEventListener('input',function(){i.nextElementSibling.style.background=i.value;});});</script>
				<?php $kit = odin_kit(); ?>
				<h2>Kit de diseño del sitio (avanzado)</h2>
				<p>CSS global del sitio (colores, tipografías y estilos de las clases que usan tus páginas). Se carga antes que el CSS de cada página, así lo que edites en Odin siempre manda.</p>
				<table class="form-table" role="presentation">
					<tr><th scope="row"><label for="odin-fonts">URL de fuentes (opcional)</label></th><td><input id="odin-fonts" class="large-text" type="url" name="fonts" value="<?php echo esc_attr($kit['fonts']); ?>" placeholder="Vacío = se genera sola con las fuentes de arriba"></td></tr>
					<tr><th scope="row"><label for="odin-css">CSS global</label></th><td><textarea id="odin-css" name="css" rows="22" class="large-text code" spellcheck="false"><?php echo esc_textarea($kit['css']); ?></textarea></td></tr>
				</table>
				<?php submit_button('Guardar ajustes'); ?>
			</form>
			<h2>Cabecera, pie y producto único</h2>
			<p>Crea una plantilla en <a href="<?php echo esc_url(admin_url('post-new.php?post_type=odin_template')); ?>">Odin → Añadir plantilla</a>, elige su tipo y márcala como <strong>Activa</strong>: se aplica sola en toda la web.</p>
		</div>
		<?php
	});
});

add_action('admin_post_odin_settings', static function () {
	if (!current_user_can('manage_options')) {
		wp_die('Sin permiso.', '', ['response' => 403]);
	}
	check_admin_referer('odin_settings');
	$p = odin_page_clean(['layout' => sanitize_key($_POST['layout'] ?? ''), 'hideTitle' => empty($_POST['hideTitle']) ? '0' : '1', 'bg' => sanitize_text_field(wp_unslash($_POST['bg'] ?? ''))]);
	update_option('odin_defaults', ['layout' => $p['layout'] ?: 'default', 'hideTitle' => $p['hideTitle'] === '1', 'bg' => $p['bg'], 'scene' => odin_page_defaults()['scene']]);
	$css = (string) wp_unslash($_POST['css'] ?? '');
	$css = current_user_can('unfiltered_html') ? $css : wp_strip_all_tags($css);
	$fonts = esc_url_raw(wp_unslash($_POST['fonts'] ?? ''));
	$colors = [];
	foreach (ODIN_GLOBAL_COLORS as $k => $_) {
		$c = odin_builder_clean_value('color', sanitize_text_field(wp_unslash($_POST['colors'][$k] ?? '')));
		if ($c && !str_starts_with($c, 'var(')) {
			$colors[$k] = $c;
		}
	}
	$fontname = static fn($f) => preg_replace('/[^A-Za-z0-9 ]/', '', sanitize_text_field(wp_unslash($f)));
	update_option('odin_global', [
		'colors' => $colors,
		'fontHead' => $fontname($_POST['fontHead'] ?? '') ?: 'Outfit',
		'fontBody' => $fontname($_POST['fontBody'] ?? '') ?: 'Work Sans',
		'radius' => (string) (odin_builder_clean_value('size', sanitize_text_field(wp_unslash($_POST['radius'] ?? ''))) ?: '16px'),
	]);
	update_option('odin_kit', array_merge(odin_kit(), [
		'css' => str_ireplace('</style', '', $css), // nunca puede cerrar la etiqueta <style>
		'fonts' => str_starts_with($fonts, 'https://fonts.googleapis.com/') ? $fonts : '',
	]));
	wp_safe_redirect(admin_url('edit.php?post_type=odin_template&page=odin-settings&updated=1'));
	exit;
});

// ---------------------------------------------------------------- REST: plantillas para el editor

add_action('rest_api_init', static function () {
	register_rest_route('odin/v1', '/menus', [
		'methods' => 'GET',
		'permission_callback' => static fn() => current_user_can('edit_pages'),
		'callback' => static fn() => array_map(static fn($m) => ['id' => $m->term_id, 'title' => $m->name], wp_get_nav_menus()),
	]);
	register_rest_route('odin/v1', '/templates', [
		[
			'methods' => 'GET',
			'permission_callback' => static fn() => current_user_can('edit_pages'),
			'callback' => static function () {
				$out = [];
				foreach (get_posts(['post_type' => 'odin_template', 'post_status' => ['publish', 'draft'], 'numberposts' => 200, 'orderby' => 'title', 'order' => 'ASC']) as $p) {
					$out[] = ['id' => $p->ID, 'title' => $p->post_title ?: '(sin título)', 'type' => odin_template_type($p->ID), 'edit' => odin_builder_edit_url($p->ID)];
				}
				return $out;
			},
		],
		[
			// "Hacer global": crea una plantilla de sección a partir de un elemento.
			'methods' => 'POST',
			'permission_callback' => static fn() => current_user_can('publish_pages'),
			'callback' => static function (WP_REST_Request $r) {
				$p = $r->get_json_params() ?: [];
				$id = wp_insert_post(['post_type' => 'odin_template', 'post_status' => 'publish', 'post_title' => sanitize_text_field($p['title'] ?? 'Sección global')], true);
				if (is_wp_error($id)) {
					return $id;
				}
				update_post_meta($id, '_odin_tpl_type', 'section');
				odin_builder_save($id, $p['tree'] ?? []);
				return ['id' => $id, 'title' => get_the_title($id), 'edit' => odin_builder_edit_url($id)];
			},
		],
	]);
});
