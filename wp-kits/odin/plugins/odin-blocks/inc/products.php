<?php
/**
 * Grilla de productos WooCommerce renderizada en servidor. Botón "añadir al carrito" por enlace:
 * funciona sin JS (no necesita los scripts de Woo en la página).
 */

defined('ABSPATH') || exit;

function odin_blocks_render_products($attrs) {
	if (!function_exists('wc_get_products')) {
		return '';
	}
	$a = wp_parse_args($attrs, [
		'count' => 8, 'columns' => 4, 'category' => '', 'orderby' => 'date',
		'onSale' => false, 'featured' => false, 'showPrice' => true, 'showButton' => true, 'showRating' => false,
	]);

	$args = ['status' => 'publish', 'visibility' => 'catalog', 'limit' => max(1, min(48, (int) $a['count']))];
	$order = [
		'date' => ['orderby' => 'date', 'order' => 'DESC'],
		'title' => ['orderby' => 'title', 'order' => 'ASC'],
		'rand' => ['orderby' => 'rand'],
		'price' => ['orderby' => 'meta_value_num', 'meta_key' => '_price', 'order' => 'ASC'],
		'price-desc' => ['orderby' => 'meta_value_num', 'meta_key' => '_price', 'order' => 'DESC'],
		'popularity' => ['orderby' => 'meta_value_num', 'meta_key' => 'total_sales', 'order' => 'DESC'],
		'rating' => ['orderby' => 'meta_value_num', 'meta_key' => '_wc_average_rating', 'order' => 'DESC'],
	];
	$args += $order[$a['orderby']] ?? $order['date'];
	if ($a['category'] !== '') {
		$args['category'] = [sanitize_title($a['category'])];
	}
	if ($a['featured']) {
		$args['featured'] = true;
	}
	if ($a['onSale']) {
		$args['include'] = wc_get_product_ids_on_sale() ?: [0];
	}

	$products = wc_get_products($args);
	if (!$products) {
		return defined('REST_REQUEST') && REST_REQUEST ? '<p>' . esc_html__('No hay productos que coincidan.', 'odin-blocks') . '</p>' : '';
	}

	$items = '';
	foreach ($products as $p) {
		$badge = $p->is_on_sale() ? '<span class="odin-product__badge">' . esc_html__('Oferta', 'odin-blocks') . '</span>' : '';
		$rating = $a['showRating'] && $p->get_average_rating() > 0 ? wc_get_rating_html($p->get_average_rating(), $p->get_rating_count()) : '';
		$price = $a['showPrice'] ? '<span class="odin-product__price">' . $p->get_price_html() . '</span>' : '';
		$button = $a['showButton'] && $p->is_purchasable() && $p->is_in_stock()
			? sprintf('<a href="%s" class="odin-product__btn wp-element-button" rel="nofollow">%s</a>', esc_url($p->add_to_cart_url()), esc_html($p->add_to_cart_text()))
			: '';
		$items .= sprintf(
			'<li class="odin-product"><a class="odin-product__link" href="%s">%s<span class="odin-product__img">%s</span><span class="odin-product__name">%s</span></a>%s%s%s</li>',
			esc_url($p->get_permalink()),
			$badge,
			$p->get_image('woocommerce_thumbnail', ['loading' => 'lazy']),
			esc_html($p->get_name()),
			$rating,
			$price,
			$button
		);
	}

	return sprintf(
		'<ul %s>%s</ul>',
		get_block_wrapper_attributes(['class' => 'odin-products', 'style' => '--odin-cols:' . max(1, min(6, (int) $a['columns']))]),
		$items
	);
}
