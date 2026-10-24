<?php
/**
 * Odin: escenas del fondo 3D y mockups animados como datos editables.
 * Pantallas: Odin → Fondo 3D y Odin → Mockups.
 */

defined('ABSPATH') || exit;

/** Formas 3D disponibles y qué significa cada número de "args" (los ángulos van en grados). */
const ODIN_3D_SHAPES = [
	'box' => 'Caja: [ancho, alto, fondo]',
	'cone' => 'Cono: [radio, alto, lados]',
	'cylinder' => 'Cilindro: [radio arriba, radio abajo, alto, lados]',
	'sphere' => 'Esfera: [radio, segmentos, segmentos, inicio°, arco°, inicio vertical°, arco vertical°]',
	'torus' => 'Anillo: [radio, grosor, segmentos, segmentos, arco°]',
	'icosahedron' => 'Icosaedro: [radio, detalle]',
	'octahedron' => 'Octaedro: [radio, detalle]',
	'dodecahedron' => 'Dodecaedro: [radio, detalle]',
	'torusknot' => 'Nudo: [radio, grosor, segmentos, segmentos]',
];

/** Escenas originales de ODIN.01 (antes estaban fijas en el código JavaScript). */
function odin_default_scenes() {
	$p = static fn($shape, $args, $pos, $rot = [0, 0, 0], $accent = false) => compact('shape', 'args', 'pos', 'rot', 'accent');
	return [
		'default' => ['label' => 'Núcleo geométrico', 'parts' => []],
		'shop' => ['label' => 'Tienda', 'parts' => [
			$p('box', [1.8, 2, 0.9], [0, -0.35, 0]),
			$p('torus', [0.5, 0.06, 8, 24, 180], [0, 0.65, 0.25], [0, 0, 0], true),
			$p('torus', [0.5, 0.06, 8, 24, 180], [0, 0.65, -0.25], [0, 0, 0], true),
			$p('box', [0.6, 0.6, 0.6], [1.6, -1, 0.4], [11.5, 28.6, 0]),
			$p('box', [0.45, 0.95, 0.45], [-1.5, -0.85, 0.2], [0, -22.9, 5.7]),
			$p('cylinder', [0.35, 0.35, 0.08, 24], [-1.25, 0.85, 0.6], [90, 0, 17.2], true),
			$p('box', [0.55, 0.32, 0.04], [1.15, 0.55, 0.55], [0, 0, -20], true),
		]],
		'food' => ['label' => 'Restaurante', 'parts' => [
			$p('cylinder', [1.9, 1.6, 0.14, 32], [0, -0.95, 0]),
			$p('sphere', [1.3, 16, 8, 0, 360, 0, 90], [0, -0.85, 0]),
			$p('torus', [1.3, 0.05, 8, 48], [0, -0.85, 0], [90, 0, 0], true),
			$p('sphere', [0.16, 12, 8], [0, 0.55, 0], [0, 0, 0], true),
			$p('box', [0.12, 2.2, 0.06], [-2.3, -0.95, 0], [90, 0, 0]),
			$p('box', [0.16, 2.2, 0.05], [2.3, -0.95, 0], [90, 0, 0]),
		]],
		'house' => ['label' => 'Casa', 'parts' => [
			$p('box', [3.6, 0.12, 3], [0, -1.3, 0]),
			$p('box', [2.4, 1.6, 2], [0, -0.42, 0]),
			$p('cone', [1.95, 1.2, 4], [0, 0.98, 0], [0, 45, 0], true),
			$p('box', [0.3, 0.7, 0.3], [0.6, 1.15, 0.3]),
			$p('box', [0.45, 0.8, 0.06], [0, -0.82, 1.02], [0, 0, 0], true),
			$p('box', [0.45, 0.4, 0.06], [-0.75, -0.25, 1.02], [0, 0, 0], true),
			$p('box', [0.45, 0.4, 0.06], [0.75, -0.25, 1.02], [0, 0, 0], true),
		]],
	];
}

function odin_scenes() {
	return array_replace(odin_default_scenes(), (array) get_option('odin_scenes', []));
}

/** clave => nombre, para los selectores (incluye "sin fondo"). */
function odin_scenes_list() {
	return array_map(static fn($s) => $s['label'], odin_scenes()) + ['none' => 'Sin fondo 3D'];
}

/** Valida las piezas que llegan del editor (JSON). Devuelve [piezas, error]. */
function odin_scene_clean_parts($json) {
	$data = json_decode((string) $json, true);
	if (!is_array($data)) {
		return [null, 'El JSON no es válido: revisa comas, corchetes y comillas.'];
	}
	$num = static fn($v, $min, $max) => is_numeric($v) ? max($min, min($max, round((float) $v, 4))) : 0;
	$vec = static fn($v, $min, $max) => array_map(static fn($i) => $num($v[$i] ?? 0, $min, $max), [0, 1, 2]);
	$out = [];
	foreach (array_slice($data, 0, 40) as $i => $p) {
		if (!is_array($p) || !isset(ODIN_3D_SHAPES[$p['shape'] ?? ''])) {
			return [null, sprintf('La pieza %d tiene una forma desconocida. Formas válidas: %s.', $i + 1, implode(', ', array_keys(ODIN_3D_SHAPES)))];
		}
		$out[] = [
			'shape' => $p['shape'],
			'args' => array_map(static fn($v) => $num($v, -360, 360), array_slice((array) ($p['args'] ?? []), 0, 8)),
			'pos' => $vec((array) ($p['pos'] ?? []), -20, 20),
			'rot' => $vec((array) ($p['rot'] ?? []), -360, 360),
			'accent' => !empty($p['accent']),
		];
	}
	return [$out, ''];
}

// ---------------------------------------------------------------- mockups

function odin_builder_mockups() {
	return array_replace(odin_builder_mockups_default(), (array) get_option('odin_mockups', []));
}

// Vista previa de un mockup (solo editores): página mínima con el CSS del sitio y la animación de armado.
add_action('template_redirect', static function () {
	if (!isset($_GET['odin_mock_preview']) || !current_user_can('edit_pages')) {
		return;
	}
	$key = sanitize_key($_GET['odin_mock_preview']);
	$m = odin_builder_mockups()[$key] ?? null;
	if (!$m) {
		wp_die('Mockup no encontrado.', '', ['response' => 404]);
	}
	nocache_headers();
	$fonts = odin_kit()['fonts'] ?: odin_global_fonts_url();
	?><!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title><?php echo esc_html($m[0]); ?></title>
<?php if ($fonts) : ?><link rel="stylesheet" href="<?php echo esc_url($fonts); ?>"><?php endif; ?>
<style><?php echo odin_global_css() . str_ireplace('</style', '', odin_kit()['css']); // phpcs:ignore WordPress.Security.EscapeOutput ?>
body{margin:0;padding:24px;min-height:100vh;box-sizing:border-box;display:grid;place-items:center;overflow:hidden}body::before{display:none}
.odn-prev{width:min(560px,100%)}.odn-prev button{margin-top:14px;font:600 13px var(--font-body);background:transparent;color:var(--muted);border:1px solid var(--border);border-radius:999px;padding:6px 14px;cursor:pointer}</style>
</head><body>
<div class="odn-prev"><div class="mock assemble" aria-hidden="true" style="--k:1"><?php echo $m[1]; // phpcs:ignore WordPress.Security.EscapeOutput -- HTML de mockup guardado por un administrador ?></div><button type="button" onclick="odinPlay()">↻ Ver armado otra vez</button></div>
<script>function odinPlay(){var el=document.querySelector('.assemble'),t0=null;function f(t){t0=t0||t;var p=Math.min(1,(t-t0)/1600);el.style.setProperty('--k',(1-p*p*(3-2*p)).toFixed(3));if(p<1)requestAnimationFrame(f);}el.style.setProperty('--k',1);requestAnimationFrame(f);}setTimeout(odinPlay,300);</script>
</body></html>
	<?php
	exit;
}, 0);

// ---------------------------------------------------------------- pantallas de administración

add_action('admin_menu', static function () {
	add_submenu_page('edit.php?post_type=odin_template', 'Fondo 3D', 'Fondo 3D', 'manage_options', 'odin-3d', 'odin_admin_3d_page');
	add_submenu_page('edit.php?post_type=odin_template', 'Mockups animados', 'Mockups', 'manage_options', 'odin-mockups', 'odin_admin_mockups_page');
}, 20);

function odin_admin_notice() {
	$msg = isset($_GET['odin_msg']) ? sanitize_text_field(wp_unslash($_GET['odin_msg'])) : '';
	if ($msg) {
		$ok = !str_starts_with($msg, 'Error');
		printf('<div class="notice notice-%s is-dismissible"><p>%s</p></div>', $ok ? 'success' : 'error', esc_html($msg));
	}
}

function odin_admin_back($page, $msg, $anchor = '') {
	wp_safe_redirect(add_query_arg(['post_type' => 'odin_template', 'page' => $page, 'odin_msg' => rawurlencode($msg)], admin_url('edit.php')) . ($anchor ? '#' . $anchor : ''));
	exit;
}

function odin_admin_3d_page() {
	$kit = odin_kit();
	$d = odin_page_defaults();
	$scenes = odin_scenes();
	$defaults = odin_default_scenes();
	$post = esc_url(admin_url('admin-post.php'));
	?>
	<div class="wrap odin-admin">
		<h1>Fondo 3D animado</h1>
		<?php odin_admin_notice(); ?>
		<p>La escena 3D que se mueve detrás de las páginas Odin. Sus colores son los globales <strong>Primario</strong>, <strong>Acento</strong> y <strong>Fondo</strong> (<a href="<?php echo esc_url(admin_url('edit.php?post_type=odin_template&page=odin-settings')); ?>">Odin → Ajustes</a>). Cada página elige su escena en el editor: ⚙ Ajustes de la página → Fondo 3D.</p>

		<div class="odin-3d-grid">
			<div>
				<h2>Vista previa</h2>
				<iframe id="odin-3d-preview" title="Vista previa del fondo 3D" src="<?php echo esc_url(add_query_arg('odin_scene', $d['scene'], home_url('/'))); ?>"></iframe>
				<p class="description">Se muestra sobre tu portada. Pulsa «Ver» en cualquier escena para cambiarla aquí.</p>
			</div>
			<form method="post" action="<?php echo $post; // phpcs:ignore ?>">
				<h2>Ajustes generales</h2>
				<input type="hidden" name="action" value="odin_3d_settings"><?php wp_nonce_field('odin_3d'); ?>
				<table class="form-table" role="presentation">
					<tr><th scope="row">Activar</th><td><label><input type="checkbox" name="kit_scene" value="1" <?php checked($kit['scene']); ?>> Mostrar el fondo 3D en las páginas Odin</label></td></tr>
					<tr><th scope="row"><label for="odin-scene">Escena por defecto</label></th><td><select id="odin-scene" name="scene"><?php foreach (odin_scenes_list() as $k => $label) : ?><option value="<?php echo esc_attr($k); ?>" <?php selected($d['scene'], $k); ?>><?php echo esc_html($label); ?></option><?php endforeach; ?></select></td></tr>
					<tr><th scope="row"><label for="odin-particles">Partículas (estrellas)</label></th><td><input id="odin-particles" type="number" min="0" max="6000" step="100" name="particles" value="<?php echo esc_attr((int) $kit['particles']); ?>"><p class="description">0 = sin partículas. En móvil se usa el 40 %.</p></td></tr>
					<tr><th scope="row">Anillos</th><td><label><input type="checkbox" name="rings" value="1" <?php checked($kit['rings']); ?>> Mostrar los anillos orbitales</label></td></tr>
					<tr><th scope="row"><label for="odin-speed">Velocidad de giro</label></th><td><select id="odin-speed" name="speed"><?php foreach (['0.5' => 'Lenta', '1' => 'Normal', '1.5' => 'Rápida', '2' => 'Muy rápida'] as $v => $label) : ?><option value="<?php echo esc_attr($v); ?>" <?php selected((string) (float) $kit['speed'], (string) (float) $v); ?>><?php echo esc_html($label); ?></option><?php endforeach; ?></select></td></tr>
					<tr><th scope="row"><label for="odin-side">Posición en escritorio</label></th><td><select id="odin-side" name="side"><option value="right" <?php selected($kit['side'], 'right'); ?>>A la derecha del texto</option><option value="center" <?php selected($kit['side'], 'center'); ?>>Centrado detrás del texto</option></select></td></tr>
				</table>
				<?php submit_button('Guardar ajustes generales'); ?>
			</form>
		</div>

		<h2>Escenas</h2>
		<p>Cada escena es una lista de piezas que llegan volando y se arman al cargar la página. Cada pieza: <code>shape</code> (forma), <code>args</code> (medidas), <code>pos</code> [x, y, z] (el centro es [0,0,0]; usa valores entre −3 y 3), <code>rot</code> [x, y, z] en grados y <code>accent</code> (true = bordes en color acento). Una escena sin piezas muestra el núcleo geométrico.</p>
		<details class="odin-help"><summary>Formas disponibles y sus medidas</summary><ul><?php foreach (ODIN_3D_SHAPES as $k => $h) : ?><li><code><?php echo esc_html($k); ?></code> — <?php echo esc_html($h); ?></li><?php endforeach; ?></ul></details>

		<div class="odin-cards">
			<?php foreach ($scenes as $key => $sc) : ?>
				<form class="odin-card" id="escena-<?php echo esc_attr($key); ?>" method="post" action="<?php echo $post; // phpcs:ignore ?>">
					<input type="hidden" name="action" value="odin_scene_save"><input type="hidden" name="key" value="<?php echo esc_attr($key); ?>"><?php wp_nonce_field('odin_scene'); ?>
					<div class="odin-card__head">
						<input type="text" name="label" value="<?php echo esc_attr($sc['label']); ?>" aria-label="Nombre de la escena">
						<code><?php echo esc_html($key); ?></code>
						<button type="button" class="button odin-see" data-scene="<?php echo esc_attr($key); ?>">Ver ↑</button>
					</div>
					<textarea name="parts" rows="12" class="large-text code" spellcheck="false" aria-label="Piezas de <?php echo esc_attr($sc['label']); ?>"><?php echo esc_textarea(wp_json_encode($sc['parts'], JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE)); ?></textarea>
					<p>
						<button class="button button-primary" name="op" value="save">Guardar escena</button>
						<?php if (isset($defaults[$key]) && isset(((array) get_option('odin_scenes', []))[$key])) : ?><button class="button" name="op" value="restore" onclick="return confirm('¿Volver a la escena original?')">Restaurar original</button><?php endif; ?>
						<?php if (!isset($defaults[$key])) : ?><button class="button button-link-delete" name="op" value="delete" onclick="return confirm('¿Eliminar esta escena?')">Eliminar</button><?php endif; ?>
					</p>
				</form>
			<?php endforeach; ?>
			<form class="odin-card odin-card--new" method="post" action="<?php echo $post; // phpcs:ignore ?>">
				<input type="hidden" name="action" value="odin_scene_save"><input type="hidden" name="op" value="new"><?php wp_nonce_field('odin_scene'); ?>
				<h3>Nueva escena</h3>
				<p><label>Nombre<br><input type="text" name="label" required placeholder="Ej.: Gimnasio"></label></p>
				<p><label>Empezar copiando<br><select name="from"><?php foreach ($scenes as $k => $sc) : ?><option value="<?php echo esc_attr($k); ?>"><?php echo esc_html($sc['label']); ?></option><?php endforeach; ?></select></label></p>
				<?php submit_button('Crear escena', 'secondary', 'submit', false); ?>
			</form>
		</div>
	</div>
	<?php odin_admin_styles(); ?>
	<script>
	document.querySelectorAll('.odin-see').forEach(function (b) {
		b.addEventListener('click', function () {
			var f = document.getElementById('odin-3d-preview');
			f.src = <?php echo wp_json_encode(home_url('/')); ?> + '?odin_scene=' + encodeURIComponent(b.dataset.scene);
			f.scrollIntoView({ behavior: 'smooth', block: 'center' });
		});
	});
	</script>
	<?php
}

add_action('admin_post_odin_3d_settings', static function () {
	if (!current_user_can('manage_options')) {
		wp_die('Sin permiso.', '', ['response' => 403]);
	}
	check_admin_referer('odin_3d');
	update_option('odin_kit', array_merge(odin_kit(), [
		'scene' => !empty($_POST['kit_scene']),
		'particles' => max(0, min(6000, (int) ($_POST['particles'] ?? 3000))),
		'rings' => !empty($_POST['rings']),
		'speed' => max(0.1, min(4, (float) ($_POST['speed'] ?? 1))),
		'side' => ($_POST['side'] ?? '') === 'center' ? 'center' : 'right',
	]));
	$scene = sanitize_key($_POST['scene'] ?? '');
	if (isset(odin_scenes_list()[$scene])) {
		update_option('odin_defaults', array_merge(odin_page_defaults(), ['scene' => $scene]));
	}
	odin_admin_back('odin-3d', 'Ajustes del fondo 3D guardados.');
});

add_action('admin_post_odin_scene_save', static function () {
	if (!current_user_can('manage_options')) {
		wp_die('Sin permiso.', '', ['response' => 403]);
	}
	check_admin_referer('odin_scene');
	$saved = (array) get_option('odin_scenes', []);
	$op = sanitize_key($_POST['op'] ?? 'save');
	$label = sanitize_text_field(wp_unslash($_POST['label'] ?? ''));
	if ($op === 'new') {
		$key = sanitize_key(sanitize_title($label)) ?: 'escena';
		while (isset(odin_scenes()[$key]) || $key === 'none') {
			$key .= '-2';
		}
		$from = odin_scenes()[sanitize_key($_POST['from'] ?? '')] ?? ['parts' => []];
		$saved[$key] = ['label' => $label ?: $key, 'parts' => $from['parts']];
		update_option('odin_scenes', $saved);
		odin_admin_back('odin-3d', "Escena «{$saved[$key]['label']}» creada. Edita sus piezas abajo.", 'escena-' . $key);
	}
	$key = sanitize_key($_POST['key'] ?? '');
	if (!isset(odin_scenes()[$key])) {
		odin_admin_back('odin-3d', 'Error: escena no encontrada.');
	}
	if ($op === 'restore' || $op === 'delete') {
		unset($saved[$key]);
		update_option('odin_scenes', $saved);
		odin_admin_back('odin-3d', $op === 'restore' ? 'Escena restaurada a la original.' : 'Escena eliminada.');
	}
	[$parts, $err] = odin_scene_clean_parts(wp_unslash($_POST['parts'] ?? '[]'));
	if ($err) {
		odin_admin_back('odin-3d', 'Error: ' . $err, 'escena-' . $key);
	}
	$saved[$key] = ['label' => $label ?: odin_scenes()[$key]['label'], 'parts' => $parts];
	update_option('odin_scenes', $saved);
	odin_admin_back('odin-3d', 'Escena guardada. Pulsa «Ver» para comprobarla.', 'escena-' . $key);
});

function odin_admin_mockups_page() {
	$mocks = odin_builder_mockups();
	$defaults = odin_builder_mockups_default();
	$saved = (array) get_option('odin_mockups', []);
	$post = esc_url(admin_url('admin-post.php'));
	?>
	<div class="wrap odin-admin">
		<h1>Mockups animados</h1>
		<?php odin_admin_notice(); ?>
		<p>Ventanas decorativas cuyas piezas se arman al hacer scroll. Se usan en el widget <strong>Proyecto → «Mockup animado»</strong>. Cada pieza es un <code>&lt;div class="pc …"&gt;</code>: <code>--x</code>, <code>--y</code>, <code>--z</code> y <code>--r</code> dicen desde dónde llega volando y <code>--s</code> el orden (0 primero). Para montar uno sin código usa el widget <strong>«Mockup animado»</strong> del grupo Sitio.</p>
		<div class="odin-cards odin-cards--mock">
			<?php foreach ($mocks as $key => [$label, $html]) : ?>
				<form class="odin-card" id="mock-<?php echo esc_attr($key); ?>" method="post" action="<?php echo $post; // phpcs:ignore ?>">
					<input type="hidden" name="action" value="odin_mock_save"><input type="hidden" name="key" value="<?php echo esc_attr($key); ?>"><?php wp_nonce_field('odin_mock'); ?>
					<iframe title="Vista previa de <?php echo esc_attr($label); ?>" loading="lazy" src="<?php echo esc_url(add_query_arg('odin_mock_preview', $key, home_url('/'))); ?>"></iframe>
					<div class="odin-card__head">
						<input type="text" name="label" value="<?php echo esc_attr($label); ?>" aria-label="Nombre del mockup">
						<code><?php echo esc_html($key); ?></code>
					</div>
					<details><summary>Ver / editar el código</summary>
						<textarea name="html" rows="14" class="large-text code" spellcheck="false" aria-label="Código de <?php echo esc_attr($label); ?>"><?php echo esc_textarea($html); ?></textarea>
					</details>
					<p>
						<button class="button button-primary" name="op" value="save">Guardar</button>
						<?php if (isset($defaults[$key]) && isset($saved[$key])) : ?><button class="button" name="op" value="restore" onclick="return confirm('¿Volver al mockup original?')">Restaurar original</button><?php endif; ?>
						<?php if (!isset($defaults[$key])) : ?><button class="button button-link-delete" name="op" value="delete" onclick="return confirm('¿Eliminar este mockup?')">Eliminar</button><?php endif; ?>
					</p>
				</form>
			<?php endforeach; ?>
			<form class="odin-card odin-card--new" method="post" action="<?php echo $post; // phpcs:ignore ?>">
				<input type="hidden" name="action" value="odin_mock_save"><input type="hidden" name="op" value="new"><?php wp_nonce_field('odin_mock'); ?>
				<h3>Nuevo mockup</h3>
				<p><label>Nombre<br><input type="text" name="label" required placeholder="Ej.: Agenda de citas"></label></p>
				<p><label>Empezar copiando<br><select name="from"><?php foreach ($mocks as $k => $m) : ?><option value="<?php echo esc_attr($k); ?>"><?php echo esc_html($m[0]); ?></option><?php endforeach; ?></select></label></p>
				<?php submit_button('Crear mockup', 'secondary', 'submit', false); ?>
			</form>
		</div>
	</div>
	<?php
	odin_admin_styles();
}

add_action('admin_post_odin_mock_save', static function () {
	if (!current_user_can('manage_options')) {
		wp_die('Sin permiso.', '', ['response' => 403]);
	}
	check_admin_referer('odin_mock');
	$saved = (array) get_option('odin_mockups', []);
	$op = sanitize_key($_POST['op'] ?? 'save');
	$label = sanitize_text_field(wp_unslash($_POST['label'] ?? ''));
	if ($op === 'new') {
		$key = sanitize_key(sanitize_title($label)) ?: 'mockup';
		while (isset(odin_builder_mockups()[$key])) {
			$key .= '-2';
		}
		$from = odin_builder_mockups()[sanitize_key($_POST['from'] ?? '')] ?? ['', ''];
		$saved[$key] = [$label ?: $key, $from[1]];
		update_option('odin_mockups', $saved);
		odin_admin_back('odin-mockups', "Mockup «{$saved[$key][0]}» creado. Ya aparece en el widget Proyecto.", 'mock-' . $key);
	}
	$key = sanitize_key($_POST['key'] ?? '');
	if (!isset(odin_builder_mockups()[$key])) {
		odin_admin_back('odin-mockups', 'Error: mockup no encontrado.');
	}
	if ($op === 'restore' || $op === 'delete') {
		unset($saved[$key]);
		update_option('odin_mockups', $saved);
		odin_admin_back('odin-mockups', $op === 'restore' ? 'Mockup restaurado al original.' : 'Mockup eliminado.');
	}
	$html = (string) wp_unslash($_POST['html'] ?? '');
	// Solo quien puede publicar HTML sin filtrar guarda el código tal cual (estilos inline con --x, --y…).
	$html = current_user_can('unfiltered_html') ? $html : wp_kses_post($html);
	$saved[$key] = [$label ?: odin_builder_mockups()[$key][0], $html];
	update_option('odin_mockups', $saved);
	odin_admin_back('odin-mockups', 'Mockup guardado.', 'mock-' . $key);
});

function odin_admin_styles() {
	?>
	<style>
	.odin-admin .odin-3d-grid{display:grid;grid-template-columns:minmax(0,1.3fr) minmax(0,1fr);gap:24px;align-items:start}
	.odin-admin #odin-3d-preview{width:100%;height:440px;border:1px solid #dcdcde;border-radius:8px;background:#070b14}
	.odin-admin .odin-cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:16px;margin-top:12px}
	.odin-admin .odin-card{background:#fff;border:1px solid #dcdcde;border-radius:8px;padding:14px}
	.odin-admin .odin-card iframe{width:100%;height:300px;border:0;border-radius:6px;background:#070b14;margin-bottom:10px}
	.odin-admin .odin-card__head{display:flex;gap:8px;align-items:center;margin-bottom:8px}
	.odin-admin .odin-card__head input{flex:1;font-weight:600}
	.odin-admin .odin-card textarea{font-size:12px}
	.odin-admin .odin-card--new{border-style:dashed;background:#f6f7f7}
	.odin-admin .odin-help{margin:8px 0 4px}.odin-admin .odin-help summary{cursor:pointer;color:#2271b1}
	@media (max-width:960px){.odin-admin .odin-3d-grid{grid-template-columns:1fr}}
	</style>
	<?php
}
