<?php
// Autoprueba del mu-plugin stackpanel-domain.php dentro de una transacción (ROLLBACK al final: el sitio no cambia).
// Uso (dentro del contenedor): php wp-cli.phar --allow-root eval-file wp-content/plugins/odin-blocks/tests/stackpanel-domain-selfcheck.php
global $wpdb;
$fails = 0;
$ok = static function ($c, $m) use (&$fails) { echo ($c ? '  ok   ' : '  FAIL ') . $m . PHP_EOL; $fails += $c ? 0 : 1; };
$pairs = ['https://a.com' => 'https://b.com', 'https:\/\/a.com' => 'https:\/\/b.com'];
$ser = serialize(['x' => 'https://a.com/img.jpg', 'n' => [1, 'https://a.com'], 'j' => '{"u":"https:\/\/a.com\/p"}', 's' => serialize(['https://a.com'])]);
$out = unserialize(stackpanel_domain_replace($ser, $pairs));
$ok($out['x'] === 'https://b.com/img.jpg' && $out['n'][1] === 'https://b.com' && $out['j'] === '{"u":"https:\/\/b.com\/p"}' && unserialize($out['s']) === ['https://b.com'], 'serializado anidado + JSON escapado');
$ok(stackpanel_domain_replace('s:5:"roto', $pairs) === 's:5:"roto', 'serializado roto se deja intacto');
$ok(stackpanel_domain_origin('http://161.97.162.177:20003/blog') === 'http://161.97.162.177:20003', 'origen con puerto y ruta');

$from = stackpanel_domain_origin(get_option('home'));
$wpdb->query('START TRANSACTION');
stackpanel_domain_migrate($from, 'https://prueba.invalid');
$ok(get_option('home') === 'https://prueba.invalid' && get_option('siteurl') === 'https://prueba.invalid', 'home y siteurl cambiados');
$left = 0;
foreach ($wpdb->get_col($wpdb->prepare('SHOW TABLES LIKE %s', $wpdb->esc_like($wpdb->prefix) . '%')) as $t) {
	foreach ($wpdb->get_results("SHOW COLUMNS FROM `$t`") as $c) {
		if (preg_match('/char|text/i', $c->Type) && !($t === $wpdb->posts && $c->Field === 'guid')) {
			$left += (int) $wpdb->get_var($wpdb->prepare("SELECT COUNT(*) FROM `$t` WHERE `{$c->Field}` LIKE %s OR `{$c->Field}` LIKE %s", '%' . $wpdb->esc_like($from) . '%', '%' . $wpdb->esc_like(str_replace('/', '\/', $from)) . '%'));
		}
	}
}
$ok($left === 0, "no queda el origen antiguo ($left)");
$front = (int) get_option('page_on_front');
$tree = json_decode((string) get_post_meta($front, '_odin_builder', true), true);
$ok(is_array($tree) && str_contains(wp_json_encode($tree), 'prueba.invalid'), 'árbol Odin sigue siendo JSON válido y con el dominio nuevo');
$ok(is_array(get_option('wpseo_titles')) && is_array(get_option('odin_kit')), 'opciones serializadas siguen leyéndose');
$h = get_option('stackpanel_domain_history');
$ok(end($h)['to'] === 'prueba.invalid' && end($h)['rows'] > 0, 'historial: ' . end($h)['from'] . ' → ' . end($h)['to'] . ', ' . end($h)['rows'] . ' filas');
$ok(get_option('stackpanel_domain_lock') === false, 'bloqueo liberado');
$wpdb->query('ROLLBACK');
wp_cache_flush();
$ok(get_option('home') === $from, 'ROLLBACK: el sitio sigue en ' . get_option('home'));
echo $fails ? "$fails FALLO(S)\n" : "Todo OK\n";
