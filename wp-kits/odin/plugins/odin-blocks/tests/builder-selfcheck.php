<?php
/**
 * Autoprueba del núcleo de Odin Builder.
 * Uso (dentro del contenedor): php wp-cli.phar --allow-root eval-file wp-content/plugins/odin-blocks/tests/builder-selfcheck.php
 */

defined('ABSPATH') || exit;

$fails = 0;
$check = static function ($ok, $msg) use (&$fails) {
	echo ($ok ? '  ok   ' : '  FAIL ') . $msg . PHP_EOL;
	$fails += $ok ? 0 : 1;
};

wp_set_current_user(0); // sin unfiltered_html, como un editor no administrador

$tree = odin_builder_clean_tree([
	['id' => 'c1', 'type' => 'container', 's' => [
		'bgColor' => ['d' => '#fff', 'm' => 'red;}body{display:none'],
		'bgGradient' => 'linear-gradient(180deg, rgba(0,0,0,.5), transparent)',
		'bgImage' => 'https://example.com/a.jpg',
		'padding' => ['d' => '40px 20px', 't' => '20px', 'm' => '10px'],
		'display' => 'grid', 'cols' => ['d' => 3, 'm' => 1],
		'evil' => 'x',
	], 'c' => [
		['id' => 'h1', 'type' => 'heading', 's' => ['text' => '<script>alert(1)</script>Hola', 'tag' => 'h1', 'fontSize' => ['d' => '48px', 'm' => '28px'], 'hColor' => '#f00']],
		['id' => 'x1', 'type' => 'malware', 's' => []],
		['id' => 'i1', 'type' => 'image', 's' => ['src' => 'javascript:alert(1)']],
		['id' => 'b1', 'type' => 'button', 's' => ['text' => 'Comprar', 'link' => 'https://example.com', 'newTab' => true]],
		['id' => 'm1', 'type' => 'html', 's' => ['code' => '<p>ok</p><script>steal()</script>']],
		['id' => 's1', 'type' => 'spacer', 's' => ['height' => ['d' => '80px', 'm' => '20px']]],
		['id' => 'g1', 'type' => 'container', 's' => ['bgGradient' => 'linear-gradient(red, blue) ; } body {']],
	]],
]);

$c = (array) $tree[0]['s'];
$check(!isset($c['evil']), 'ajuste desconocido descartado');
$check(($c['bgColor'] ?? []) === ['d' => '#fff'], 'color con inyección CSS descartado (solo queda el válido)');
$kids = $tree[0]['c'];
$check(count($kids) === 6 && !in_array('malware', array_column($kids, 'type'), true), 'widget desconocido descartado');
$check(!isset(((array) $kids[1]['s'])['src']), 'URL javascript: descartada');
$check(!str_contains(((array) $kids[3]['s'])['code'] ?? '', '<script'), 'HTML libre sin <script> para no-admins');
$check(!isset(((array) $kids[5]['s'])['bgGradient']), 'degradado con inyección descartado');

$html = odin_builder_render($tree);
$check(!str_contains($html, '<script'), 'el HTML final no contiene <script>');
$check(str_contains($html, '>Hola</h1>'), 'título sin la etiqueta <script> ni su contenido');
$check(str_contains($html, 'target="_blank"') && str_contains($html, 'rel="noopener"'), 'botón en pestaña nueva con noopener');

$css = odin_builder_css($tree);
$check(!str_contains($css, 'display:none') && !str_contains($css, '}body'), 'CSS sin inyección');
$check(str_contains($css, '.odn-c1.odn-c1.odn-c1{') && str_contains($css, 'padding:40px 20px'), 'CSS de escritorio generado');
$check(str_contains($css, '@media(max-width:1024px){') && str_contains($css, '@media(max-width:767px){'), 'media queries tablet y móvil');
$check(str_contains($css, 'grid-template-columns:repeat(3,minmax(0,1fr))') && str_contains($css, 'grid-template-columns:repeat(1,minmax(0,1fr))'), 'columnas grid responsive');
$check(str_contains($css, 'background-image:linear-gradient(180deg, rgba(0,0,0,.5), transparent),url("https://example.com/a.jpg")'), 'degradado + imagen fusionados (overlay)');
$check(str_contains($css, '.odn-h1.odn-h1.odn-h1:hover{color:#f00}') && str_contains($css, 'transition:'), 'hover con transición');
$check(str_contains($css, '.odn-s1.odn-s1.odn-s1{height:80px}') && preg_match('/767px\)\{[^@]*\.odn-s1\.odn-s1\.odn-s1\{height:20px\}/', $css) === 1, 'altura del espaciador responsive');

// Widgets de Torres: proyecto con galería, pasos y obra 3D
$w = odin_builder_clean_tree([
	['id' => 'p1', 'type' => 'pjcard', 's' => ['title' => 'Casa "A" <b>', 'size' => 'big', 'tilt' => true, 'phone' => '+593 98 000', 'media' => [
		['kind' => 'img', 'src' => 'https://example.com/1.jpg'], ['kind' => 'img', 'src' => 'https://example.com/2.jpg'],
		['kind' => 'yt', 'src' => 'https://example.com/v.jpg', 'yt' => 'abc"><script>x'], ['kind' => 'img', 'src' => 'javascript:alert(1)'],
	]]],
	['id' => 'q1', 'type' => 'pasos', 's' => ['items' => [['title' => 'Uno'], ['title' => 'Dos']]]],
	['id' => 'o1', 'type' => 'obra3d', 's' => ['stages' => 99]],
]);
$h = odin_builder_render($w);
$check(str_contains($h, '<span class="pj__count">2 fotos · video</span>'), 'proyecto: contador de fotos/vídeo calculado (URL javascript: descartada)');
$check(str_contains($h, 'pj tilt pj--big') && !str_contains($h, '<b>') && !str_contains($h, '<script'), 'proyecto: clases de tamaño y texto escapado');
preg_match('/data-pj="([^"]*)"/', $h, $m);
$pj = json_decode(html_entity_decode($m[1] ?? ''), true);
$check(($pj['media'][2]['id'] ?? '') === 'abcx' && str_starts_with($pj['wa'] ?? '', 'https://wa.me/59398000?text='), 'proyecto: ID de YouTube saneado y enlace de WhatsApp');
$check(str_contains($h, '<span class="paso__n">01</span><h2>Uno</h2>') && str_contains($h, 'data-step="2"><span class="paso__n">02</span>'), 'pasos numerados');
$check(str_contains($h, 'data-stages="20"') && str_contains($h, '<span>20</span>'), 'obra 3D: etapas limitadas a 20');

echo $fails ? "\n$fails FALLO(S)\n" : "\nTodo OK\n";
