<?php
/**
 * Odin Builder — integración: REST, pantalla del editor, lienzo (iframe) y salida en el frontend.
 *
 * Al guardar, el HTML renderizado se escribe en post_content (dentro de un bloque HTML):
 * Yoast, el buscador y los feeds leen el contenido real. El CSS va en _odin_builder_css.
 */

defined('ABSPATH') || exit;

const ODIN_BUILDER_TYPES = ['page', 'post', 'odin_template'];

function odin_builder_get_tree($post_id) {
	$raw = get_post_meta($post_id, '_odin_builder', true);
	$tree = $raw ? json_decode($raw, true) : null;
	return is_array($tree) ? $tree : null;
}

/** Guarda un árbol: metadatos + HTML en post_content (los widgets dinámicos quedan como shortcode). */
function odin_builder_save($id, $raw_tree) {
	$tree = odin_builder_clean_tree($raw_tree);
	odin_builder_preview(false); // nunca guardar marcadores ni data-odn en el contenido público
	$prev = odin_builder_ctx($id);
	$html = odin_builder_render($tree);
	odin_builder_ctx($prev);
	update_post_meta($id, '_odin_builder', wp_slash(wp_json_encode($tree)));
	update_post_meta($id, '_odin_builder_css', odin_builder_css($tree));
	$res = wp_update_post(['ID' => $id, 'post_content' => wp_slash("<!-- wp:html -->\n<div class=\"odin-builder\">" . $html . "</div>\n<!-- /wp:html -->")], true);
	return is_wp_error($res) ? $res : $tree;
}

/** Recalcula árbol saneado + CSS de todo lo hecho con Odin (se ejecuta una vez por versión del motor de CSS). */
function odin_builder_regenerate_css() {
	foreach (get_posts(['post_type' => 'any', 'post_status' => 'any', 'numberposts' => -1, 'fields' => 'ids', 'meta_key' => '_odin_builder']) as $id) {
		$tree = odin_builder_clean_tree(odin_builder_get_tree($id) ?? []);
		update_post_meta($id, '_odin_builder', wp_slash(wp_json_encode($tree)));
		update_post_meta($id, '_odin_builder_css', odin_builder_css($tree));
	}
}
add_action('init', static function () {
	if (get_option('odin_css_engine') !== '2') {
		odin_builder_regenerate_css();
		update_option('odin_css_engine', '2');
	}
}, 20);

function odin_builder_can($post_id) {
	$post = get_post($post_id);
	return $post && in_array($post->post_type, ODIN_BUILDER_TYPES, true) && current_user_can('edit_post', $post->ID);
}

// ---------------------------------------------------------------- REST

add_action('rest_api_init', static function () {
	$id_arg = ['id' => ['validate_callback' => static fn($v) => is_numeric($v)]];
	$perm = static fn(WP_REST_Request $r) => odin_builder_can((int) $r['id']);

	register_rest_route('odin/v1', '/builder/(?P<id>\d+)', [
		[
			'methods' => 'GET',
			'permission_callback' => $perm,
			'args' => $id_arg,
			'callback' => static function (WP_REST_Request $r) {
				$post = get_post((int) $r['id']);
				$is_tpl = $post->post_type === 'odin_template';
				return [
					'tree' => odin_builder_get_tree($post->ID) ?? [],
					'title' => $post->post_title,
					'status' => $post->post_status,
					'link' => $is_tpl ? '' : get_permalink($post),
					'postType' => $post->post_type,
					'page' => $is_tpl ? null : odin_page_clean((array) get_post_meta($post->ID, '_odin_page', true)),
					'defaults' => odin_page_defaults(),
					'template' => $is_tpl ? ['type' => odin_template_type($post->ID), 'active' => get_post_meta($post->ID, '_odin_tpl_active', true) === '1', 'popup' => odin_popup_settings($post->ID)] : null,
					'scenes' => odin_scenes_list(),
					'layouts' => ODIN_LAYOUTS,
				];
			},
		],
		[
			'methods' => 'POST',
			'permission_callback' => $perm,
			'args' => $id_arg,
			'callback' => static function (WP_REST_Request $r) {
				$id = (int) $r['id'];
				$params = $r->get_json_params() ?: [];
				$is_tpl = get_post_type($id) === 'odin_template';
				if (!$is_tpl && isset($params['page']) && is_array($params['page'])) {
					update_post_meta($id, '_odin_page', odin_page_clean($params['page']));
				}
				if ($is_tpl && isset($params['template']) && is_array($params['template'])) {
					$type = sanitize_key($params['template']['type'] ?? 'section');
					update_post_meta($id, '_odin_tpl_type', isset(ODIN_TPL_TYPES[$type]) ? $type : 'section');
					update_post_meta($id, '_odin_tpl_active', empty($params['template']['active']) ? '0' : '1');
					if (isset($params['template']['popup']) && is_array($params['template']['popup'])) {
						update_post_meta($id, '_odin_popup', odin_popup_clean($params['template']['popup']));
					}
				}
				$tree = odin_builder_save($id, $params['tree'] ?? []);
				if (is_wp_error($tree)) {
					return $tree;
				}
				$status = $params['status'] ?? '';
				if (in_array($status, ['publish', 'draft'], true) && current_user_can($status === 'publish' ? 'publish_post' : 'edit_post', $id)) {
					wp_update_post(['ID' => $id, 'post_status' => $status]);
				}
				if ($is_tpl) {
					odin_templates_refresh();
				}
				return ['ok' => true, 'tree' => $tree, 'status' => get_post_status($id), 'link' => $is_tpl ? '' : get_permalink($id)];
			},
		],
	]);

	// Vista previa: el lienzo pide HTML+CSS renderizados por el mismo PHP que la web publicada.
	register_rest_route('odin/v1', '/render/(?P<id>\d+)', [
		'methods' => 'POST',
		'permission_callback' => $perm,
		'args' => $id_arg,
		'callback' => static function (WP_REST_Request $r) {
			$tree = odin_builder_clean_tree(($r->get_json_params() ?: [])['tree'] ?? []);
			odin_builder_preview(true);
			odin_builder_ctx((int) $r['id']);
			try {
				return ['html' => odin_builder_render($tree), 'css' => odin_builder_css($tree)];
			} finally {
				odin_builder_preview(false);
			}
		},
	]);
});

// ---------------------------------------------------------------- enlaces "Editar con Odin"

function odin_builder_edit_url($post_id) {
	return admin_url('admin.php?action=odin_builder&post=' . (int) $post_id);
}

foreach (['page_row_actions', 'post_row_actions'] as $hook) {
	add_filter($hook, static function ($actions, $post) {
		if (odin_builder_can($post->ID)) {
			$actions = ['odin' => sprintf('<a href="%s"><strong>Editar con Odin</strong></a>', esc_url(odin_builder_edit_url($post->ID)))] + $actions;
		}
		return $actions;
	}, 10, 2);
}

/** Plantillas que usa una página: widgets «Plantilla global» del árbol y shortcodes [odin_template] del contenido. */
function odin_builder_used_templates($post_id) {
	$ids = [];
	$walk = static function ($nodes) use (&$walk, &$ids) {
		foreach ((array) $nodes as $n) {
			if (($n['type'] ?? '') === 'template' && !empty($n['s']['templateId'])) {
				$ids[] = (int) $n['s']['templateId'];
			}
			$walk($n['c'] ?? []);
		}
	};
	$walk(odin_builder_get_tree($post_id));
	preg_match_all('/\[odin_template\s+id="?(\d+)/', (string) get_post_field('post_content', $post_id), $m);
	return array_values(array_unique(array_merge($ids, array_map('intval', $m[1]))));
}

// Barra superior: «Editar con Odin» con desplegable (esta página, cabecera, pie, popups y plantillas que usa).
add_action('admin_bar_menu', static function ($bar) {
	if (is_admin() || !current_user_can('edit_pages')) {
		return;
	}
	$page = is_singular(ODIN_BUILDER_TYPES) && odin_builder_can(get_queried_object_id()) ? get_queried_object_id() : 0;
	$bar->add_node(['id' => 'odin-builder', 'title' => '✎ Editar con Odin', 'href' => $page ? odin_builder_edit_url($page) : admin_url('edit.php?post_type=odin_template')]);
	$add = static function ($id, $title, $post_id) use ($bar) {
		if ($post_id && odin_builder_can($post_id)) {
			$bar->add_node(['parent' => 'odin-builder', 'id' => 'odin-builder-' . $id, 'title' => esc_html($title), 'href' => odin_builder_edit_url($post_id)]);
		}
	};
	if ($page) {
		$add('page', 'Esta página: ' . get_the_title($page), $page);
	}
	if (function_exists('odin_active_template_id')) {
		$add('header', 'Cabecera', odin_active_template_id('header'));
		$add('footer', 'Pie de página', odin_active_template_id('footer'));
		foreach ((array) (get_option('odin_active_templates', [])['popup'] ?? []) as $pid) {
			$add('popup-' . $pid, 'Popup: ' . get_the_title($pid), (int) $pid);
		}
	}
	if ($page) {
		foreach (odin_builder_used_templates($page) as $tid) {
			$add('tpl-' . $tid, 'Plantilla / shortcode: ' . get_the_title($tid), $tid);
		}
	}
	$bar->add_node(['parent' => 'odin-builder', 'id' => 'odin-builder-all', 'title' => 'Todas las plantillas…', 'href' => admin_url('edit.php?post_type=odin_template')]);
	if (current_user_can('manage_options')) {
		$bar->add_node(['parent' => 'odin-builder', 'id' => 'odin-builder-settings', 'title' => 'Ajustes globales (colores, fuentes, fondo 3D)…', 'href' => admin_url('edit.php?post_type=odin_template&page=odin-settings')]);
	}
}, 80);

// Aviso en el editor de bloques: esta página la gestiona Odin.
add_action('enqueue_block_editor_assets', static function () {
	$post = get_post();
	if ($post && odin_builder_get_tree($post->ID) !== null) {
		wp_add_inline_script('wp-edit-post', sprintf(
			'wp.domReady(function(){wp.data.dispatch("core/notices").createWarningNotice(%s,{isDismissible:false,actions:[{label:"Abrir Odin Builder",url:%s}]});});',
			wp_json_encode('Esta página se diseña con Odin Builder. Los cambios hechos aquí se sobrescriben al guardar en Odin.'),
			wp_json_encode(odin_builder_edit_url($post->ID))
		));
	}
});

// ---------------------------------------------------------------- pantalla del editor

add_action('admin_action_odin_builder', static function () {
	$post_id = isset($_GET['post']) ? (int) $_GET['post'] : 0;
	if (!odin_builder_can($post_id)) {
		wp_die('No tienes permiso para editar esta página con Odin.', '', ['response' => 403]);
	}
	wp_enqueue_media(['post' => $post_id]);
	// common/forms = CSS base de wp-admin; sin ellos el selector de medios muestra textos ocultos y se solapa.
	wp_enqueue_style('odin-builder', ODIN_BLOCKS_URL . 'assets/builder.css', ['common', 'forms', 'wp-components'], ODIN_BLOCKS_VERSION);
	wp_enqueue_script('odin-builder', ODIN_BLOCKS_URL . 'assets/builder.js', ['wp-element', 'wp-components', 'wp-api-fetch'], ODIN_BLOCKS_VERSION, true);
	wp_localize_script('odin-builder', 'odinBuilder', [
		'postId' => $post_id,
		'canvasUrl' => add_query_arg(['odin_canvas' => 1, '_odin' => wp_create_nonce('odin_canvas_' . $post_id)], get_preview_post_link($post_id) ?: get_permalink($post_id)),
		'exitUrl' => get_edit_post_link($post_id, 'raw') ?: admin_url('edit.php?post_type=page'),
		'listUrl' => admin_url('edit.php?post_type=' . get_post_type($post_id)),
		'canUnfiltered' => current_user_can('unfiltered_html'),
		'hasWoo' => class_exists('WooCommerce'),
		'breakpoints' => ['t' => ODIN_BP_TABLET, 'm' => ODIN_BP_MOBILE],
		'icons' => odin_builder_icons(),
		'globalColors' => array_map(static fn($k, $c) => ['var' => "var(--$k)", 'label' => $c[0], 'value' => odin_global()['colors'][$k]], array_keys(ODIN_GLOBAL_COLORS), ODIN_GLOBAL_COLORS),
		'mocks' => array_map(static fn($m) => $m[0], odin_builder_mockups()),
		'formTypes' => ODIN_FORM_TYPES,
		'newTemplateUrl' => admin_url('post-new.php?post_type=odin_template'),
		'menusUrl' => admin_url('nav-menus.php'),
	]);
	nocache_headers();
	header('Content-Type: text/html; charset=utf-8');
	?><!doctype html>
<html <?php language_attributes(); ?>>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Odin Builder · <?php echo esc_html(get_the_title($post_id)); ?></title>
<?php wp_print_styles(); wp_print_head_scripts(); ?>
</head>
<body class="odin-builder-app wp-core-ui">
<div id="odin-builder-root"></div>
<?php wp_print_media_templates(); wp_print_footer_scripts(); ?>
</body>
</html>
	<?php
	exit;
});

// ---------------------------------------------------------------- lienzo (iframe dentro del editor)

function odin_builder_is_canvas() {
	static $is = null;
	if ($is === null) {
		$id = get_queried_object_id();
		$is = isset($_GET['odin_canvas'], $_GET['_odin']) && $id
			&& wp_verify_nonce(sanitize_key($_GET['_odin']), 'odin_canvas_' . $id)
			&& odin_builder_can($id);
	}
	return $is;
}

add_action('template_redirect', static function () {
	if (!isset($_GET['odin_canvas']) || !odin_builder_is_canvas()) {
		return;
	}
	show_admin_bar(false);
	$id = get_queried_object_id();
	add_filter('the_content', static function ($content) use ($id) {
		return get_the_ID() === $id ? '<div id="odin-canvas" class="odin-builder"></div>' : $content;
	}, 1);
	add_action('wp_enqueue_scripts', static function () {
		wp_enqueue_style('odin-effects');
		wp_enqueue_style('odin-builder-canvas', ODIN_BLOCKS_URL . 'assets/builder-canvas.css', [], ODIN_BLOCKS_VERSION);
		wp_enqueue_script('odin-builder-canvas', ODIN_BLOCKS_URL . 'assets/builder-canvas.js', [], ODIN_BLOCKS_VERSION, true);
		wp_add_inline_style('odin-builder-canvas', odin_builder_base_css());
		wp_enqueue_script('odin-widgets');
		wp_enqueue_style('odin-form-style');
		if (wp_style_is('odin-products-style', 'registered')) {
			wp_enqueue_style('odin-products-style');
		}
	}, 100);
	header('X-Frame-Options: SAMEORIGIN');
});

// ---------------------------------------------------------------- frontend

add_action('wp_enqueue_scripts', static function () {
	if (!is_singular(ODIN_BUILDER_TYPES) || odin_builder_is_canvas()) {
		return;
	}
	$id = get_queried_object_id();
	if (odin_builder_get_tree($id) === null) {
		return;
	}
	odin_builder_enqueue('odin-builder', (string) get_post_meta($id, '_odin_builder_css', true), get_post_field('post_content', $id));

	// El HTML de la página se guarda estático: el schema FAQPage se genera en cada visita desde el árbol.
	$walk = static function ($nodes) use (&$walk) {
		foreach ($nodes as $n) {
			if (($n['type'] ?? '') === 'faq' && !empty($n['s']['schema'])) {
				odin_builder_faq_schema(array_map(static fn($i) => (array) $i, (array) ($n['s']['items'] ?? [])));
			}
			if (!empty($n['c'])) {
				$walk($n['c']);
			}
		}
	};
	$walk(odin_builder_get_tree($id));
});
