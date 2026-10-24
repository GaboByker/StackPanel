<?php
/**
 * Página completa de Odin: producto único con plantilla Odin, o página en modo "lienzo".
 * Se carga desde builder-theme.php (template_include).
 */

defined('ABSPATH') || exit;

$odin_mode = $GLOBALS['odin_page_mode'] ?? 'canvas';
// Todo se renderiza antes de wp_head: así los estilos de bloques y de Odin van en <head>.
$odin_header = $odin_mode === 'canvas' ? '' : odin_site_part('header');
the_post();
if ($odin_mode === 'product') {
	global $product;
	$product = wc_get_product(get_the_ID());
	$odin_main = odin_builder_capture('woocommerce_output_all_notices')
		. sprintf('<div id="product-%d" class="%s">%s</div>', get_the_ID(), esc_attr(implode(' ', wc_get_product_class('', $product))), odin_template_render(odin_active_template_id('single-product')));
	if (isset(WC()->structured_data)) {
		WC()->structured_data->generate_product_data($product);
	}
} else {
	// 'page' = cabecera y pie Odin + contenido sin márgenes del tema; 'canvas' = solo el contenido.
	$odin_main = apply_filters('the_content', get_the_content());
}
$odin_footer = $odin_mode === 'canvas' ? '' : odin_site_part('footer');
?><!doctype html>
<html <?php language_attributes(); ?>>
<head>
<meta charset="<?php bloginfo('charset'); ?>">
<meta name="viewport" content="width=device-width, initial-scale=1">
<?php wp_head(); ?>
</head>
<body <?php body_class('odin-page odin-page--' . $odin_mode); ?>>
<?php wp_body_open(); ?>
<div class="wp-site-blocks">
<?php echo $odin_header; // phpcs:ignore WordPress.Security.EscapeOutput -- HTML renderizado y saneado por Odin/el tema ?>
<main id="main" class="odin-main"><?php echo $odin_main; // phpcs:ignore WordPress.Security.EscapeOutput ?></main>
<?php echo $odin_footer; // phpcs:ignore WordPress.Security.EscapeOutput ?>
</div>
<?php wp_footer(); ?>
</body>
</html>
