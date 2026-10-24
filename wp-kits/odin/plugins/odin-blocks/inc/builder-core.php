<?php
/**
 * Odin Builder — núcleo: esquema, saneado, CSS responsive y render de widgets.
 *
 * Árbol: nodo = {id, type, s: {clave: valor | {d,t,m}}, c: [nodos]}.
 * d = escritorio, t = tablet (≤1024px), m = móvil (≤767px).
 * Todo valor pasa por una lista blanca antes de guardarse o convertirse en CSS.
 */

defined('ABSPATH') || exit;

const ODIN_BP_TABLET = 1024;
const ODIN_BP_MOBILE = 767;

/** Controles de estilo comunes a todos los nodos: clave => [tipo, propiedad CSS, responsive, pseudo]. */
function odin_builder_style_schema() {
	return [
		// Fondo
		'bgColor' => ['color', 'background-color', true],
		'bgGradient' => ['gradient', 'background-image', true],
		'bgImage' => ['url', 'background-image', true],
		'bgPos' => [['center center', 'top center', 'bottom center', 'center left', 'center right', 'top left', 'top right', 'bottom left', 'bottom right'], 'background-position', true],
		'bgSize' => [['cover', 'contain', 'auto'], 'background-size', true],
		'bgRepeat' => [['no-repeat', 'repeat', 'repeat-x', 'repeat-y'], 'background-repeat', false],
		'bgFixed' => [['scroll', 'fixed'], 'background-attachment', false],
		// Borde y sombra
		'bWidth' => ['boxpos', 'border-width', true],
		'bStyle' => [['none', 'solid', 'dashed', 'dotted', 'double'], 'border-style', false],
		'bColor' => ['color', 'border-color', false],
		'radius' => ['boxpos', 'border-radius', true],
		'shadow' => [['none', 'sm', 'md', 'lg', 'xl'], 'box-shadow', false],
		// Tamaño y espaciado
		'width' => ['size', 'width', true],
		'maxWidth' => ['size', 'max-width', true],
		'minHeight' => ['size', 'min-height', true],
		'padding' => ['boxpos', 'padding', true],
		'margin' => ['box', 'margin', true],
		'zIndex' => ['int', 'z-index', false],
		// Tipografía
		'color' => ['color', 'color', true],
		'fontSize' => ['size', 'font-size', true],
		'fontWeight' => [['300', '400', '500', '600', '700', '800', '900'], 'font-weight', false],
		'lineHeight' => ['size', 'line-height', true],
		'letterSpacing' => ['size', 'letter-spacing', true],
		'textAlign' => [['left', 'center', 'right', 'justify'], 'text-align', true],
		'textTransform' => [['none', 'uppercase', 'lowercase', 'capitalize'], 'text-transform', false],
		// Layout (contenedor)
		'display' => [['flex', 'grid', 'block'], 'display', true],
		'direction' => [['row', 'column', 'row-reverse', 'column-reverse'], 'flex-direction', true],
		'justify' => [['flex-start', 'center', 'flex-end', 'space-between', 'space-around', 'space-evenly'], 'justify-content', true],
		'align' => [['stretch', 'flex-start', 'center', 'flex-end', 'baseline'], 'align-items', true],
		'wrap' => [['nowrap', 'wrap'], 'flex-wrap', true],
		'gap' => ['size', 'gap', true],
		'cols' => ['int', 'grid-template-columns', true],
		'rows' => ['int', 'grid-template-rows', true],
		// Hijo dentro de un contenedor
		'colSpan' => ['int', 'grid-column', true],
		'rowSpan' => ['int', 'grid-row', true],
		'grow' => [['0', '1'], 'flex', true],
		'order' => ['int', 'order', true],
		'alignSelf' => [['flex-start', 'center', 'flex-end', 'stretch'], 'align-self', true],
		'offsetX' => ['size', 'translate', true],
		'offsetY' => ['size', 'translate', true],
		// Hover
		'hColor' => ['color', 'color', false, ':hover'],
		'hBgColor' => ['color', 'background-color', false, ':hover'],
		'hBColor' => ['color', 'border-color', false, ':hover'],
		'hScale' => [['1', '1.03', '1.05', '1.1'], 'transform', false, ':hover'],
	];
}

/** Ajustes de contenido por widget: clave => tipo. */
function odin_builder_widgets() {
	return [
		'container' => ['tag' => ['div', 'section', 'header', 'footer', 'article', 'aside', 'nav'], 'link' => 'url'],
		'heading' => ['text' => 'text', 'tag' => ['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'div'], 'link' => 'url'],
		'text' => ['html' => 'rich'],
		'image' => ['src' => 'url', 'imageId' => 'int', 'alt' => 'text', 'link' => 'url', 'fit' => ['cover', 'contain', 'fill', 'none'], 'caption' => 'text'],
		'button' => ['text' => 'text', 'link' => 'url', 'newTab' => 'bool', 'nofollow' => 'bool', 'btnStyle' => ['theme', 'none']],
		'spacer' => ['height' => 'size'],
		'divider' => ['weight' => 'size', 'style' => ['solid', 'dashed', 'dotted', 'double'], 'lineColor' => 'color'],
		'video' => ['url' => 'url'],
		'html' => ['code' => 'code'],
		'products' => ['count' => 'int', 'columns' => 'int', 'category' => 'text', 'orderby' => ['date', 'popularity', 'rating', 'price', 'price-desc', 'title', 'rand'], 'onSale' => 'bool'],
		'icon' => ['icon' => 'icon', 'link' => 'url'],
		'iconbox' => ['icon' => 'icon', 'title' => 'text', 'html' => 'rich', 'link' => 'url', 'position' => ['top', 'left']],
		'iconlist' => ['items' => ['repeater' => ['icon' => 'icon', 'text' => 'text', 'link' => 'url']]],
		'accordion' => ['items' => ['repeater' => ['title' => 'text', 'content' => 'rich']], 'openFirst' => 'bool'],
		'tabs' => ['items' => ['repeater' => ['title' => 'text', 'content' => 'rich']]],
		'gallery' => ['images' => ['repeater' => ['src' => 'url', 'imageId' => 'int', 'alt' => 'text']], 'columns' => 'int', 'ratio' => ['auto', '1/1', '4/3', '3/2', '16/9', '3/4']],
		'testimonial' => ['quote' => 'rich', 'name' => 'text', 'role' => 'text', 'src' => 'url', 'imageId' => 'int', 'rating' => 'int'],
		'social' => ['items' => ['repeater' => ['network' => ['facebook', 'instagram', 'twitter', 'youtube', 'linkedin', 'whatsapp', 'tiktok', 'mail', 'phone'], 'url' => 'url']], 'shape' => ['circle', 'square', 'none']],
		'map' => ['address' => 'text', 'zoom' => 'int', 'height' => 'size'],
		'alert' => ['kind' => ['info', 'success', 'warning', 'danger'], 'title' => 'text', 'html' => 'rich'],
		'form' => ['fields' => ['repeater' => ['label' => 'text', 'type' => ODIN_FORM_TYPES, 'required' => 'bool', 'options' => 'textarea', 'width' => ['100', '50', '33']]], 'recipient' => 'email', 'subject' => 'text', 'submitLabel' => 'text', 'successMessage' => 'text'],
		'template' => ['templateId' => 'int'],
		'card' => ['icon' => 'icon', 'title' => 'text', 'html' => 'rich', 'link' => 'url', 'tilt' => 'bool', 'tag' => ['article', 'div']],
		'facts' => ['items' => ['repeater' => ['value' => 'text', 'label' => 'text']]],
		'terminal' => ['title' => 'text', 'lines' => ['repeater' => ['kind' => ['cmd', 'ok', 'info', 'text'], 'text' => 'text']]],
		'phonevideo' => ['src' => 'url', 'poster' => 'url', 'label' => 'text'],
		'linkcards' => ['items' => ['repeater' => ['title' => 'text', 'link' => 'url', 'text' => 'text']]],
		'chips' => ['items' => ['repeater' => ['text' => 'text']], 'look' => ['stack', 'tags']],
		'project' => ['mock' => 'mock', 'kicker' => 'text', 'title' => 'text', 'titleTag' => ['h3', 'h2'], 'html' => 'rich', 'features' => ['repeater' => ['text' => 'text']], 'stats' => ['repeater' => ['value' => 'text', 'label' => 'text']], 'tags' => ['repeater' => ['text' => 'text']]],
		'person' => ['initials' => 'text', 'name' => 'text', 'role' => 'text', 'text' => 'textarea', 'src' => 'url', 'imageId' => 'int'],
		'steps' => ['items' => ['repeater' => ['title' => 'text', 'text' => 'textarea']]],
		'faq' => ['items' => ['repeater' => ['q' => 'text', 'a' => 'rich']], 'schema' => 'bool'],
		'breadcrumbs' => ['items' => ['repeater' => ['text' => 'text', 'link' => 'url']]],
		'menu' => ['menuId' => 'int', 'label' => 'text', 'noToggle' => 'bool'],
		'mockup' => ['title' => 'text', 'grid' => 'bool', 'pieces' => ['repeater' => [
			'kind' => ['node', 'node-accent', 'bubble', 'toast', 'toast-alert', 'chip', 'kpi', 'card'],
			'text' => 'text', 'left' => 'int', 'top' => 'int', 'fromX' => 'int', 'fromY' => 'int', 'fromZ' => 'int', 'rotate' => 'int', 'order' => 'int',
		]]],
		'whatsapp' => ['phone' => 'text', 'message' => 'text', 'bubbleTitle' => 'text', 'bubbleText' => 'text', 'delay' => 'int'],
		'obra3d' => ['label' => 'text', 'stages' => 'int', 'src' => 'url', 'imageId' => 'int'],
		'pasos' => ['label' => 'text', 'items' => ['repeater' => ['title' => 'text', 'text' => 'textarea']]],
		'pjcard' => ['src' => 'url', 'imageId' => 'int', 'alt' => 'text', 'tag' => 'text', 'title' => 'text', 'text' => 'text', 'size' => ['normal', 'big', 'wide'], 'tilt' => 'bool',
			'place' => 'text', 'desc' => 'textarea', 'datos' => ['repeater' => ['text' => 'text']],
			'media' => ['repeater' => ['kind' => ['img', 'yt'], 'src' => 'url', 'alt' => 'text', 'yt' => 'text']], 'phone' => 'text', 'cta' => 'text'],
		// WooCommerce: producto actual (plantilla de producto único)
		'wc-title' => ['tag' => ['h1', 'h2', 'h3', 'p']],
		'wc-price' => [],
		'wc-images' => [],
		'wc-add-to-cart' => [],
		'wc-excerpt' => [],
		'wc-description' => [],
		'wc-meta' => [],
		'wc-rating' => [],
		'wc-tabs' => [],
		'wc-related' => ['count' => 'int', 'columns' => 'int'],
	];
}

/** Iconos SVG de trazo (una familia). Se usan en widgets y en el selector del editor. */
function odin_builder_icons() {
	return [
		'check' => '<path d="M20 6 9 17l-5-5"/>',
		'star' => '<path d="m12 2 3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/>',
		'heart' => '<path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78L12 21.23l8.84-8.84a5.5 5.5 0 0 0 0-7.78z"/>',
		'phone' => '<path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.13.96.36 1.9.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.91.34 1.85.57 2.81.7A2 2 0 0 1 22 16.92z"/>',
		'mail' => '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="m22 6-10 7L2 6"/>',
		'map-pin' => '<path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/>',
		'clock' => '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
		'truck' => '<path d="M1 3h15v13H1zM16 8h4l3 3v5h-7V8z"/><circle cx="5.5" cy="18.5" r="2.5"/><circle cx="18.5" cy="18.5" r="2.5"/>',
		'shield' => '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
		'cart' => '<circle cx="9" cy="20" r="1"/><circle cx="18" cy="20" r="1"/><path d="M2 3h3l2.7 12.4a2 2 0 0 0 2 1.6h8.6a2 2 0 0 0 2-1.6L22 7H6"/>',
		'user' => '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
		'arrow-right' => '<path d="M5 12h14M12 5l7 7-7 7"/>',
		'zap' => '<path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z"/>',
		'award' => '<circle cx="12" cy="8" r="7"/><path d="M8.21 13.89 7 23l5-3 5 3-1.21-9.12"/>',
		'gift' => '<path d="M20 12v10H4V12M2 7h20v5H2zM12 22V7M12 7H7.5a2.5 2.5 0 0 1 0-5C11 2 12 7 12 7zM12 7h4.5a2.5 2.5 0 0 0 0-5C13 2 12 7 12 7z"/>',
		'info' => '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>',
		'facebook' => '<path d="M18 2h-3a5 5 0 0 0-5 5v3H7v4h3v8h4v-8h3l1-4h-4V7a1 1 0 0 1 1-1h3z"/>',
		'instagram' => '<rect x="2" y="2" width="20" height="20" rx="5"/><path d="M16 11.37A4 4 0 1 1 12.63 8 4 4 0 0 1 16 11.37zM17.5 6.5h.01"/>',
		'twitter' => '<path d="M4 4l16 16M20 4 4 20"/>',
		'youtube' => '<path d="M22.54 6.42a2.78 2.78 0 0 0-1.94-2C18.88 4 12 4 12 4s-6.88 0-8.6.46a2.78 2.78 0 0 0-1.94 2A29 29 0 0 0 1 11.75a29 29 0 0 0 .46 5.33A2.78 2.78 0 0 0 3.4 19c1.72.46 8.6.46 8.6.46s6.88 0 8.6-.46a2.78 2.78 0 0 0 1.94-2 29 29 0 0 0 .46-5.25 29 29 0 0 0-.46-5.33z"/><path d="m9.75 15.02 5.75-3.27-5.75-3.27v6.54z"/>',
		'linkedin' => '<path d="M16 8a6 6 0 0 1 6 6v7h-4v-7a2 2 0 0 0-4 0v7h-4v-7a6 6 0 0 1 6-6zM2 9h4v12H2z"/><circle cx="4" cy="4" r="2"/>',
		'whatsapp' => '<path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/>',
		'tiktok' => '<path d="M14 3v11.5a3.5 3.5 0 1 1-3.5-3.5"/><path d="M14 3c.5 2.5 2.5 4.5 5 5"/>',
		'chat' => '<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/>',
		'table' => '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18M9 9v11"/>',
		'location' => '<path d="M12 21s-7-6.2-7-11a7 7 0 0 1 14 0c0 4.8-7 11-7 11z"/><circle cx="12" cy="10" r="2.5"/>',
		'search' => '<circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/>',
		'calendar' => '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
		'server' => '<rect x="3" y="4" width="18" height="6" rx="1.5"/><rect x="3" y="14" width="18" height="6" rx="1.5"/><path d="M7 7h.01M7 17h.01"/>',
		'monitor' => '<rect x="3" y="4" width="18" height="14" rx="2"/><path d="M3 8h18M8 21h8"/>',
		'qr' => '<rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><path d="M14 14h3v3M21 14v7h-4M14 18v3"/>',
		'apps' => '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
		'code' => '<path d="M8 6l-6 6 6 6M16 6l6 6-6 6"/>',
		'chef' => '<path d="M6 14a4 4 0 1 1 2-7.5A4 4 0 0 1 16 6.5 4 4 0 1 1 18 14v6H6z"/><path d="M6 17h12"/>',
		'lines' => '<path d="M4 7h16M4 12h10M4 17h7"/>',
		'chart' => '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
		'package' => '<path d="M3 7l9-4 9 4-9 4zM3 7v10l9 4 9-4V7M12 11v10"/>',
		'filter' => '<path d="M3 5h18l-7 8v6l-4 2v-8z"/>',
		'cart2' => '<path d="M3 4h2l2.4 11h10.2L20 8H6.2"/><circle cx="9" cy="19" r="1.5"/><circle cx="17" cy="19" r="1.5"/>',
		'home' => '<path d="M3 11l9-7 9 7v10H3z"/><path d="M9 21v-6h6v6"/>',
		'megaphone' => '<path d="M3 11l14-6v14L3 13z"/><path d="M7 13v5h3"/>',
		'refresh' => '<path d="M21 12a9 9 0 1 1-4-7.5L21 3v5h-5"/>',
		'shield2' => '<path d="M12 3l8 3v6c0 4.5-3.4 8-8 9-4.6-1-8-4.5-8-9V6z"/>',
		'palette' => '<path d="M12 3a9 9 0 1 0 0 18c1 0 1.5-.8 1.5-1.6 0-1.2-1-1.4-1-2.4 0-.9.7-1.5 1.6-1.5H17a4 4 0 0 0 4-4c0-4.7-4-8.5-9-8.5z"/><circle cx="7.5" cy="11" r="1"/><circle cx="12" cy="7.5" r="1"/><circle cx="16.5" cy="11" r="1"/>',
		'users' => '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0M16 4.5a3.5 3.5 0 0 1 0 7M18 14a6 6 0 0 1 3.5 6"/>',
		// Arquitectura (dibujados en 48×48, escalados a la rejilla de 24)
		'casa' => '<g transform="scale(.5)"><path d="M6 40V18L24 6l18 12v22"/><path d="M6 40h36M18 40V26h12v14"/></g>',
		'sillon' => '<g transform="scale(.5)"><path d="M12 30V20a6 6 0 0 1 6-6h12a6 6 0 0 1 6 6v10"/><path d="M8 30h32v6H8zM12 36v5M36 36v5"/></g>',
		'edificios' => '<g transform="scale(.5)"><path d="M8 42h32M12 42V14h10v28M26 42V22h10v20"/><path d="M12 20h10M12 26h10M26 28h10M26 34h10"/></g>',
		'lapiz' => '<g transform="scale(.5)"><path d="M30 8l10 10-20 20H10V28z"/><path d="M26 12l10 10"/></g>',
		'topografia' => '<g transform="scale(.5)"><path d="M4 36l12-10 10 6 18-16"/><circle cx="16" cy="26" r="2"/><circle cx="26" cy="32" r="2"/><circle cx="44" cy="16" r="2"/><path d="M4 42h40"/></g>',
		'suelo' => '<g transform="scale(.5)"><path d="M4 14h40M4 24h40M4 34h40"/><path d="M24 6v36" stroke-dasharray="3 3"/><path d="M20 38l4 4 4-4"/></g>',
		'propiedad' => '<g transform="scale(.5)"><path d="M6 42V16h16v26M26 42V16h16v26M4 42h40"/><path d="M11 22h6M11 30h6M31 22h6M31 30h6"/></g>',
		'documento' => '<g transform="scale(.5)"><path d="M12 6h18l8 8v28H12z"/><path d="M30 6v8h8M18 24h14M18 30h14M18 36h8"/></g>',
	];
}

function odin_builder_svg($name, $class = 'odn-svg') {
	$icons = odin_builder_icons();
	return '<svg class="' . esc_attr($class) . '" viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">' . ($icons[$name] ?? $icons['star']) . '</svg>';
}

/** Ajustes avanzados comunes. */
function odin_builder_common() {
	return ['cssId' => 'slug', 'cssClass' => 'classes', 'anim' => ['', 'fade', 'fade-up', 'fade-down', 'fade-left', 'fade-right', 'zoom'], 'animDelay' => 'int', 'hide' => 'devices'];
}

// ---------------------------------------------------------------- saneado

function odin_builder_clean_value($type, $v) {
	if (is_array($type) && isset($type['repeater'])) {
		if (!is_array($v)) {
			return null;
		}
		$items = [];
		foreach (array_slice(array_values($v), 0, 60) as $it) {
			if (!is_array($it)) {
				continue;
			}
			$clean = [];
			foreach ($type['repeater'] as $fk => $ft) {
				if (isset($it[$fk]) && $it[$fk] !== '' && ($c = odin_builder_clean_value($ft, $it[$fk])) !== null) {
					$clean[$fk] = $c;
				}
			}
			$items[] = $clean;
		}
		return $items ?: null;
	}
	if (is_array($type)) {
		return in_array((string) $v, $type, true) ? (string) $v : null;
	}
	$v = is_scalar($v) ? trim((string) $v) : $v;
	switch ($type) {
		case 'color':
			return is_string($v) && preg_match('/^(#[0-9a-f]{3,8}|(rgb|hsl)a?\([\d.,%\s\/]+\)|transparent|currentColor|var\(--wp--preset--color--[a-z0-9-]+\)|var\(--(bg|surface|surface-solid|text|muted|primary|primary-strong|accent|on-accent|border)\))$/i', $v) ? $v : null;
		case 'gradient':
			return is_string($v) && preg_match('/^(linear|radial)-gradient\([#%(),.\sa-z0-9-]+\)$/i', $v) ? $v : null;
		case 'size':
			return is_string($v) && preg_match('/^(auto|-?\d*\.?\d+(px|%|em|rem|vh|vw|fr)?)$/', $v) ? $v : null;
		case 'boxpos': // relleno, borde y radio: el CSS no admite negativos
			return is_string($v) && !str_contains($v, '-') ? odin_builder_clean_value('box', $v) : null;
		case 'box':
			return is_string($v) && preg_match('/^(auto|-?\d*\.?\d+(px|%|em|rem|vh|vw)?)(\s+(auto|-?\d*\.?\d+(px|%|em|rem|vh|vw)?)){0,3}$/', $v) ? $v : null;
		case 'int':
			return is_numeric($v) ? (int) $v : null;
		case 'bool':
			return !empty($v) && $v !== 'false';
		case 'url':
			return is_string($v) && $v !== '' ? (esc_url_raw($v) ?: null) : null;
		case 'text':
			return is_string($v) ? sanitize_text_field($v) : null;
		case 'textarea':
			return is_string($v) ? sanitize_textarea_field($v) : null;
		case 'email':
			return is_string($v) && is_email($v) ? sanitize_email($v) : null;
		case 'icon':
			return is_string($v) && isset(odin_builder_icons()[$v]) ? $v : null;
		case 'mock':
			return is_string($v) && function_exists('odin_builder_mockups') && isset(odin_builder_mockups()[$v]) ? $v : null;
		case 'rich':
			return is_string($v) ? wp_kses_post($v) : null;
		case 'code':
			// HTML libre solo para quien ya puede publicar HTML sin filtrar (administradores).
			return is_string($v) ? (current_user_can('unfiltered_html') ? $v : wp_kses_post($v)) : null;
		case 'slug':
			return is_string($v) ? (sanitize_html_class($v) ?: null) : null;
		case 'classes':
			return is_string($v) ? (implode(' ', array_filter(array_map('sanitize_html_class', explode(' ', $v)))) ?: null) : null;
		case 'devices':
			return is_array($v) ? array_values(array_intersect(['d', 't', 'm'], $v)) : null;
	}
	return null;
}

/** Sanea un valor que puede ser responsive ({d,t,m}). */
function odin_builder_clean_setting($type, $v, $responsive) {
	if ($responsive && is_array($v) && array_intersect_key($v, ['d' => 1, 't' => 1, 'm' => 1])) {
		$out = [];
		foreach (['d', 't', 'm'] as $dev) {
			if (isset($v[$dev]) && $v[$dev] !== '' && ($c = odin_builder_clean_value($type, $v[$dev])) !== null) {
				$out[$dev] = $c;
			}
		}
		return $out ?: null;
	}
	return $v === '' || $v === null ? null : odin_builder_clean_value($type, $v);
}

function odin_builder_clean_tree($nodes, $depth = 0) {
	if (!is_array($nodes) || $depth > 12) {
		return [];
	}
	$widgets = odin_builder_widgets();
	$style = odin_builder_style_schema();
	$common = odin_builder_common();
	$out = [];
	foreach (array_slice($nodes, 0, 500) as $n) {
		if (!is_array($n) || !isset($widgets[$n['type'] ?? ''])) {
			continue;
		}
		$type = $n['type'];
		$id = preg_replace('/[^a-z0-9]/', '', strtolower((string) ($n['id'] ?? ''))) ?: substr(md5(uniqid('', true)), 0, 8);
		$s = [];
		foreach ((array) ($n['s'] ?? []) as $k => $v) {
			if (isset($style[$k])) {
				$c = odin_builder_clean_setting($style[$k][0], $v, $style[$k][2]);
			} elseif (isset($widgets[$type][$k])) {
				$c = odin_builder_clean_setting($widgets[$type][$k], $v, $widgets[$type][$k] === 'size');
			} elseif (isset($common[$k])) {
				$c = odin_builder_clean_value($common[$k], $v);
			} else {
				continue;
			}
			if ($c !== null && $c !== []) {
				$s[$k] = $c;
			}
		}
		$out[] = [
			'id' => substr($id, 0, 12),
			'type' => $type,
			's' => (object) $s,
			'c' => $type === 'container' ? odin_builder_clean_tree($n['c'] ?? [], $depth + 1) : [],
		];
	}
	return $out;
}

// ---------------------------------------------------------------- CSS

function odin_builder_css_value($key, $v) {
	switch ($key) {
		case 'bgImage':
			return 'url("' . esc_url($v) . '")';
		case 'shadow':
			return ['none' => 'none', 'sm' => '0 1px 3px rgba(0,0,0,.12)', 'md' => '0 4px 14px rgba(0,0,0,.12)', 'lg' => '0 10px 30px rgba(0,0,0,.15)', 'xl' => '0 20px 50px rgba(0,0,0,.2)'][$v];
		case 'cols':
			return 'repeat(' . max(1, min(12, (int) $v)) . ',minmax(0,1fr))';
		case 'rows':
			return 'repeat(' . max(1, min(12, (int) $v)) . ',auto)';
		case 'colSpan':
		case 'rowSpan':
			return 'span ' . max(1, min(12, (int) $v));
		case 'grow':
			return $v === '1' ? '1 1 0' : '0 1 auto';
		case 'hScale':
			return 'scale(' . $v . ')';
	}
	return (string) $v;
}

/** CSS de toda la página: base + @media tablet + @media móvil. */
function odin_builder_css(array $nodes) {
	$rules = ['d' => [], 't' => [], 'm' => []];
	odin_builder_collect_css($nodes, $rules);
	$css = implode('', $rules['d']);
	if ($rules['t']) {
		$css .= '@media(max-width:' . ODIN_BP_TABLET . 'px){' . implode('', $rules['t']) . '}';
	}
	if ($rules['m']) {
		$css .= '@media(max-width:' . ODIN_BP_MOBILE . 'px){' . implode('', $rules['m']) . '}';
	}
	return $css;
}

function odin_builder_collect_css(array $nodes, array &$rules) {
	$schema = odin_builder_style_schema();
	foreach ($nodes as $n) {
		$s = (array) $n['s'];
		// Clase repetida = especificidad (0,3,0): lo que editas en Odin gana a reglas del kit como «.hero .terminal».
		$sel = str_repeat('.odn-' . $n['id'], 3);
		$decl = []; // [dispositivo][selector] => [declaraciones]
		foreach (['d', 't', 'm'] as $i => $dev) {
			$pick = static function ($k) use ($s, $i) {
				$v = $s[$k] ?? null;
				if (!is_array($v)) {
					return $i === 0 ? $v : null;
				}
				foreach (array_reverse(array_slice(['d', 't', 'm'], 0, $i + 1)) as $dd) {
					if (isset($v[$dd])) {
						return $v[$dd];
					}
				}
				return null;
			};
			$own = static fn($k) => is_array($s[$k] ?? null) ? isset($s[$k][$dev]) : ($i === 0 && isset($s[$k]));
			if ($own('offsetX') || $own('offsetY')) {
				$decl[$dev][$sel][] = 'translate:' . ($pick('offsetX') ?? '0') . ' ' . ($pick('offsetY') ?? '0');
			}
		}
		foreach ($s as $k => $v) {
			if (!isset($schema[$k]) || $k === 'offsetX' || $k === 'offsetY') {
				continue;
			}
			$pseudo = $schema[$k][3] ?? '';
			$values = is_array($v) && $schema[$k][2] ? $v : ['d' => $v];
			foreach ($values as $dev => $val) {
				$decl[$dev][$sel . $pseudo][] = $schema[$k][1] . ':' . odin_builder_css_value($k, $val);
			}
		}
		// Ajustes de widget que también son responsive.
		$widget_css = ['spacer' => ['height' => 'height'], 'divider' => ['weight' => 'border-top-width'], 'map' => ['height' => 'height']];
		foreach ($widget_css[$n['type']] ?? [] as $k => $prop) {
			foreach (isset($s[$k]) ? (is_array($s[$k]) ? $s[$k] : ['d' => $s[$k]]) : [] as $dev => $val) {
				$decl[$dev][$sel][] = $prop . ':' . $val;
			}
		}
		if (!empty($s['hColor']) || !empty($s['hBgColor']) || !empty($s['hScale']) || !empty($s['hBColor'])) {
			$decl['d'][$sel][] = 'transition:color .2s,background-color .2s,border-color .2s,transform .2s';
		}
		foreach ($decl as $dev => $sels) {
			foreach ($sels as $selector => $props) {
				// Degradado + imagen = una sola capa (el degradado hace de overlay encima de la imagen).
				$bg = array_filter($props, static fn($p) => str_starts_with($p, 'background-image:'));
				if (count($bg) > 1) {
					usort($bg, static fn($a, $b) => str_contains($a, 'gradient') ? -1 : 1);
					$props = array_diff($props, $bg);
					$props[] = 'background-image:' . implode(',', array_map(static fn($p) => substr($p, 17), $bg));
				}
				$rules[$dev][] = $selector . '{' . implode(';', $props) . '}';
			}
		}
		if (!empty($n['c'])) {
			odin_builder_collect_css($n['c'], $rules);
		}
	}
}

// ---------------------------------------------------------------- render

/** Post cuyo árbol se está renderizando (para los widgets dinámicos que se guardan como shortcode). */
function odin_builder_ctx($set = null) {
	static $id = 0;
	if ($set !== null) {
		$prev = $id;
		$id = (int) $set;
		return $prev;
	}
	return $id;
}

/** Busca un nodo por id en un árbol. */
function odin_builder_find(array $nodes, $id) {
	foreach ($nodes as $n) {
		if ($n['id'] === $id) {
			return $n;
		}
		if (!empty($n['c']) && ($f = odin_builder_find($n['c'], $id))) {
			return $f;
		}
	}
	return null;
}

/**
 * [odin_node post="" node=""] — widgets que deben calcularse en cada visita (productos, formularios).
 * Se guardan como shortcode en el contenido para no quedar congelados.
 */
function odin_builder_node_shortcode($atts) {
	$post_id = (int) ($atts['post'] ?? 0);
	$post = get_post($post_id);
	if (!$post || ($post->post_status !== 'publish' && !current_user_can('read_post', $post_id))) {
		return '';
	}
	$tree = json_decode((string) get_post_meta($post_id, '_odin_builder', true), true);
	$node = is_array($tree) ? odin_builder_find($tree, preg_replace('/[^a-z0-9]/', '', (string) ($atts['node'] ?? ''))) : null;
	if (!$node) {
		return '';
	}
	odin_builder_dynamic_now(true);
	$html = odin_builder_render_node($node);
	odin_builder_dynamic_now(false);
	if (function_exists('odin_builder_enqueue_extras')) {
		odin_builder_enqueue_extras($html);
	}
	return $html;
}

function odin_builder_dynamic_now($set = null) {
	static $on = false;
	if ($set !== null) {
		$on = (bool) $set;
	}
	return $on;
}

/** En el contenido guardado, los widgets dinámicos se sustituyen por su shortcode. */
function odin_builder_defer(array $n) {
	return !odin_builder_preview() && !odin_builder_dynamic_now() && odin_builder_ctx()
		? sprintf('[odin_node post="%d" node="%s"]', odin_builder_ctx(), $n['id'])
		: null;
}

/** Producto para los widgets wc-*: el actual o, en la vista previa, el último publicado. */
function odin_builder_product() {
	global $product, $post;
	if ($product instanceof WC_Product) {
		return $product;
	}
	if (!function_exists('wc_get_product')) {
		return null;
	}
	if ($post && $post->post_type === 'product') {
		return $product = wc_get_product($post->ID);
	}
	if (odin_builder_preview()) {
		$p = wc_get_products(['limit' => 1, 'status' => 'publish']);
		if ($p) {
			$product = $p[0];
			$post = get_post($product->get_id());
			setup_postdata($post);
			return $product;
		}
	}
	return null;
}

/** Ejecuta una función de plantilla de Woo y devuelve su salida. */
function odin_builder_capture(callable $fn, ...$args) {
	ob_start();
	$fn(...$args);
	return ob_get_clean();
}

/** Modo vista previa (lienzo del editor): añade data-odn y marcadores en widgets vacíos. */
function odin_builder_preview($set = null) {
	static $on = false;
	if ($set !== null) {
		$on = (bool) $set;
	}
	return $on;
}

function odin_builder_placeholder(array $n, $label) {
	return odin_builder_preview() ? '<div' . odin_builder_attrs($n, 'odn-placeholder') . '>' . esc_html($label) . '</div>' : '';
}

function odin_builder_render(array $nodes) {
	$html = '';
	foreach ($nodes as $n) {
		$html .= odin_builder_render_node($n);
	}
	return $html;
}

function odin_builder_attrs(array $n, $extra_class = '') {
	$s = (array) $n['s'];
	$cls = ['odn', 'odn-' . $n['type'], 'odn-' . $n['id']];
	if ($extra_class) {
		$cls[] = $extra_class;
	}
	if (!empty($s['cssClass'])) {
		$cls[] = $s['cssClass'];
	}
	if (!empty($s['anim'])) {
		array_push($cls, 'odin-anim', 'odin-anim--' . $s['anim']);
	}
	$map = ['d' => 'desktop', 't' => 'tablet', 'm' => 'mobile'];
	foreach ((array) ($s['hide'] ?? []) as $dev) {
		$cls[] = 'odin-hide-' . $map[$dev];
	}
	$out = ' class="' . esc_attr(implode(' ', $cls)) . '"';
	if (!empty($s['cssId'])) {
		$out .= ' id="' . esc_attr($s['cssId']) . '"';
	}
	if (!empty($s['animDelay'])) {
		$out .= ' style="--odin-delay:' . min(3000, max(0, (int) $s['animDelay'])) . 'ms"';
	}
	if (odin_builder_preview()) {
		$out .= ' data-odn="' . esc_attr($n['id']) . '" data-odn-type="' . esc_attr($n['type']) . '"';
	}
	return $out;
}

function odin_builder_render_node(array $n) {
	$s = (array) $n['s'];
	switch ($n['type']) {
		case 'container':
			$inner = odin_builder_render($n['c']);
			if (!empty($s['link'])) {
				return sprintf('<a href="%s"%s>%s</a>', esc_url($s['link']), odin_builder_attrs($n), $inner);
			}
			$tag = $s['tag'] ?? 'div';
			return "<$tag" . odin_builder_attrs($n) . ">$inner</$tag>";
		case 'heading':
			$tag = $s['tag'] ?? 'h2';
			$text = esc_html($s['text'] ?? '');
			if (!empty($s['link'])) {
				$text = sprintf('<a href="%s">%s</a>', esc_url($s['link']), $text);
			}
			return "<$tag" . odin_builder_attrs($n) . ">$text</$tag>";
		case 'text':
			return '<div' . odin_builder_attrs($n) . '>' . wpautop($s['html'] ?? '') . '</div>';
		case 'image':
			$fit = !empty($s['fit']) ? 'object-fit:' . $s['fit'] : '';
			$img = !empty($s['imageId']) ? wp_get_attachment_image((int) $s['imageId'], 'large', false, array_filter(['alt' => $s['alt'] ?? '', 'loading' => 'lazy', 'style' => $fit])) : '';
			if (!$img && !empty($s['src'])) {
				$img = sprintf('<img src="%s" alt="%s" loading="lazy" decoding="async"%s>', esc_url($s['src']), esc_attr($s['alt'] ?? ''), $fit ? ' style="' . esc_attr($fit) . '"' : '');
			}
			if (!$img) {
				return odin_builder_placeholder($n, '🖼 Elige una imagen');
			}
			if (!empty($s['link'])) {
				$img = sprintf('<a href="%s">%s</a>', esc_url($s['link']), $img);
			}
			$cap = !empty($s['caption']) ? '<figcaption>' . esc_html($s['caption']) . '</figcaption>' : '';
			return '<figure' . odin_builder_attrs($n) . ">$img$cap</figure>";
		case 'button':
			$rel = array_filter([!empty($s['newTab']) ? 'noopener' : '', !empty($s['nofollow']) ? 'nofollow' : '']);
			return sprintf(
				'<a href="%s"%s%s%s>%s</a>',
				esc_url($s['link'] ?? '#'),
				odin_builder_attrs($n, ($s['btnStyle'] ?? 'theme') === 'none' ? '' : 'wp-element-button'),
				!empty($s['newTab']) ? ' target="_blank"' : '',
				$rel ? ' rel="' . implode(' ', $rel) . '"' : '',
				esc_html($s['text'] ?? 'Botón')
			);
		case 'spacer':
			return '<div' . odin_builder_attrs($n) . ' aria-hidden="true"></div>';
		case 'divider':
			return sprintf('<hr%s style="border-top-style:%s;border-top-color:%s">', odin_builder_attrs($n), esc_attr($s['style'] ?? 'solid'), esc_attr($s['lineColor'] ?? 'currentColor'));
		case 'video':
			$embed = !empty($s['url']) ? wp_oembed_get($s['url']) : '';
			return $embed ? '<div' . odin_builder_attrs($n) . ">$embed</div>" : odin_builder_placeholder($n, '▶ Pega la URL de YouTube o Vimeo');
		case 'html':
			if (($s['code'] ?? '') === '') {
				return odin_builder_placeholder($n, '</> HTML personalizado');
			}
			// En el lienzo no se ejecutan scripts del usuario mientras edita.
			return '<div' . odin_builder_attrs($n) . '>' . (odin_builder_preview() ? wp_kses_post($s['code']) : $s['code']) . '</div>';
		case 'products':
			if (($deferred = odin_builder_defer($n)) !== null) {
				return $deferred;
			}
			$out = function_exists('odin_blocks_render_products') && function_exists('wc_get_products')
				? odin_blocks_render_products(array_intersect_key($s, array_flip(['count', 'columns', 'category', 'orderby', 'onSale'])))
				: '';
			return $out ? '<div' . odin_builder_attrs($n) . ">$out</div>" : odin_builder_placeholder($n, '🛒 No hay productos que coincidan');
	}
	return odin_builder_render_more($n, $s);
}

function odin_builder_render_more(array $n, array $s) {
	$a = odin_builder_attrs($n);
	$items = array_values(array_map(static fn($i) => (array) $i, (array) ($s['items'] ?? [])));
	switch ($n['type']) {
		case 'icon':
			$svg = odin_builder_svg($s['icon'] ?? 'star');
			return !empty($s['link']) ? sprintf('<a href="%s"%s>%s</a>', esc_url($s['link']), $a, $svg) : "<div$a>$svg</div>";
		case 'iconbox':
			$title = esc_html($s['title'] ?? '');
			if (!empty($s['link'])) {
				$title = sprintf('<a href="%s">%s</a>', esc_url($s['link']), $title);
			}
			return '<div' . odin_builder_attrs($n, ($s['position'] ?? 'top') === 'left' ? 'is-left' : 'is-top') . '><span class="odn-iconbox__icon">' . odin_builder_svg($s['icon'] ?? 'star') . '</span><div class="odn-iconbox__body"><h3 class="odn-iconbox__title">' . $title . '</h3>' . wpautop($s['html'] ?? '') . '</div></div>';
		case 'iconlist':
			$li = '';
			foreach ($items as $it) {
				$t = esc_html($it['text'] ?? '');
				if (!empty($it['link'])) {
					$t = sprintf('<a href="%s">%s</a>', esc_url($it['link']), $t);
				}
				$li .= '<li>' . odin_builder_svg($it['icon'] ?? 'check') . "<span>$t</span></li>";
			}
			return $li ? "<ul$a>$li</ul>" : odin_builder_placeholder($n, 'Añade elementos a la lista');
		case 'accordion':
			$out = '';
			foreach ($items as $i => $it) {
				$out .= sprintf('<details%s><summary>%s</summary><div class="odn-acc__body">%s</div></details>', $i === 0 && !empty($s['openFirst']) ? ' open' : '', esc_html($it['title'] ?? ''), wpautop($it['content'] ?? ''));
			}
			return $out ? "<div$a>$out</div>" : odin_builder_placeholder($n, 'Añade elementos al acordeón');
		case 'tabs':
			if (!$items) {
				return odin_builder_placeholder($n, 'Añade pestañas');
			}
			$tabs = $panels = '';
			foreach ($items as $i => $it) {
				$tabs .= sprintf('<button type="button" role="tab" id="t-%1$s-%2$d" aria-controls="p-%1$s-%2$d" aria-selected="%3$s"%4$s>%5$s</button>', $n['id'], $i, $i ? 'false' : 'true', $i ? ' tabindex="-1"' : '', esc_html($it['title'] ?? ''));
				$panels .= sprintf('<div role="tabpanel" id="p-%1$s-%2$d" aria-labelledby="t-%1$s-%2$d" tabindex="0"%3$s>%4$s</div>', $n['id'], $i, $i ? ' hidden' : '', wpautop($it['content'] ?? ''));
			}
			return "<div$a><div class=\"odn-tabs__list\" role=\"tablist\">$tabs</div>$panels</div>";
		case 'gallery':
			$imgs = '';
			foreach ((array) ($s['images'] ?? []) as $im) {
				$im = (array) $im;
				$img = !empty($im['imageId']) ? wp_get_attachment_image((int) $im['imageId'], 'medium_large', false, ['loading' => 'lazy', 'alt' => $im['alt'] ?? '']) : '';
				if (!$img && !empty($im['src'])) {
					$img = sprintf('<img src="%s" alt="%s" loading="lazy" decoding="async">', esc_url($im['src']), esc_attr($im['alt'] ?? ''));
				}
				$imgs .= $img ? "<figure>$img</figure>" : '';
			}
			if (!$imgs) {
				return odin_builder_placeholder($n, '🖼 Añade imágenes a la galería');
			}
			$style = sprintf('--odn-cols:%d;--odn-ratio:%s', max(1, min(8, (int) ($s['columns'] ?? 3))), esc_attr($s['ratio'] ?? 'auto'));
			return "<div$a><div class=\"odn-gallery__grid\" style=\"$style\">$imgs</div></div>";
		case 'testimonial':
			$photo = !empty($s['imageId']) ? wp_get_attachment_image((int) $s['imageId'], 'thumbnail', false, ['loading' => 'lazy', 'alt' => '']) : (!empty($s['src']) ? sprintf('<img src="%s" alt="" loading="lazy">', esc_url($s['src'])) : '');
			$stars = !empty($s['rating']) ? '<span class="odn-stars" role="img" aria-label="' . esc_attr(sprintf('%d de 5 estrellas', min(5, (int) $s['rating']))) . '">' . str_repeat(odin_builder_svg('star'), min(5, max(1, (int) $s['rating']))) . '</span>' : '';
			return sprintf('<figure%s>%s<blockquote>%s</blockquote><figcaption>%s<span><strong>%s</strong>%s</span></figcaption></figure>', $a, $stars, wpautop($s['quote'] ?? ''), $photo, esc_html($s['name'] ?? ''), !empty($s['role']) ? '<small>' . esc_html($s['role']) . '</small>' : '');
		case 'social':
			$out = '';
			foreach ($items as $it) {
				$net = $it['network'] ?? 'facebook';
				$url = $net === 'mail' && !empty($it['url']) && !str_contains($it['url'], ':') ? 'mailto:' . $it['url'] : ($it['url'] ?? '#');
				$out .= sprintf('<a href="%s" aria-label="%s" rel="noopener" target="_blank">%s</a>', esc_url($url), esc_attr(ucfirst($net)), odin_builder_svg($net));
			}
			return $out ? '<div' . odin_builder_attrs($n, 'is-' . ($s['shape'] ?? 'circle')) . ">$out</div>" : odin_builder_placeholder($n, 'Añade redes sociales');
		case 'map':
			if (empty($s['address'])) {
				return odin_builder_placeholder($n, '📍 Escribe una dirección');
			}
			return sprintf('<div%s><iframe src="https://maps.google.com/maps?q=%s&amp;z=%d&amp;output=embed" title="%s" loading="lazy" referrerpolicy="no-referrer-when-downgrade"></iframe></div>', $a, rawurlencode($s['address']), max(1, min(20, (int) ($s['zoom'] ?? 14))), esc_attr('Mapa: ' . $s['address']));
		case 'alert':
			return sprintf('<div%s>%s<div>%s%s</div></div>', odin_builder_attrs($n, 'is-' . ($s['kind'] ?? 'info')), odin_builder_svg('info'), !empty($s['title']) ? '<strong>' . esc_html($s['title']) . '</strong>' : '', wpautop($s['html'] ?? ''));
		case 'form':
			if (($deferred = odin_builder_defer($n)) !== null) {
				return $deferred;
			}
			if (!function_exists('odin_blocks_render_form')) {
				return '';
			}
			$inner = [];
			$fields_html = '';
			foreach ((array) ($s['fields'] ?? []) as $f) {
				$f = (array) $f;
				$inner[] = ['blockName' => 'odin/field', 'attrs' => $f, 'innerBlocks' => []];
				$fields_html .= odin_blocks_render_field($f);
			}
			if (!$inner) {
				return odin_builder_placeholder($n, '✉ Añade campos al formulario');
			}
			$form = odin_blocks_render_form([
				'formId' => 'form-' . $n['id'],
				'recipient' => $s['recipient'] ?? '',
				'subject' => $s['subject'] ?? 'Nuevo mensaje desde la web',
				'submitLabel' => $s['submitLabel'] ?? 'Enviar',
				'successMessage' => $s['successMessage'] ?? '¡Gracias! Hemos recibido tu mensaje.',
			], $fields_html, (object) ['parsed_block' => ['innerBlocks' => $inner]]);
			return "<div$a>$form</div>";
		case 'template':
			$id = (int) ($s['templateId'] ?? 0);
			if (!$id) {
				return odin_builder_placeholder($n, '◇ Elige una plantilla global');
			}
			if (!odin_builder_preview()) {
				return sprintf('<div%s>[odin_template id="%d"]</div>', $a, $id);
			}
			$html = function_exists('odin_template_render') ? odin_template_render($id, true) : '';
			return $html ? "<div$a>$html</div>" : odin_builder_placeholder($n, '◇ La plantilla está vacía o no existe');
	}
	if (str_starts_with($n['type'], 'wc-')) {
		return odin_builder_render_wc($n, $s, $a);
	}
	return odin_builder_render_site($n, $s);
}

/** Widgets de sitio: tarjetas, datos, terminal, proyectos, equipo, pasos, FAQ, menú, WhatsApp… */
function odin_builder_render_site(array $n, array $s) {
	$rows = static fn($k) => array_values(array_map(static fn($i) => (array) $i, (array) ($s[$k] ?? [])));
	$li = static fn($k, $f) => implode('', array_map($f, $rows($k)));
	switch ($n['type']) {
		case 'card':
			$tag = ($s['tag'] ?? 'article') === 'div' ? 'div' : 'article';
			$title = esc_html($s['title'] ?? '');
			if (!empty($s['link'])) {
				$title = sprintf('<a href="%s">%s</a>', esc_url($s['link']), $title);
			}
			return "<$tag" . odin_builder_attrs($n, 'card' . (!empty($s['tilt']) ? ' tilt' : '')) . '>' . (!empty($s['icon']) ? odin_builder_svg($s['icon'], 'icon') : '') . "<h3>$title</h3>" . wpautop($s['html'] ?? '') . "</$tag>";
		case 'facts':
			return '<ul' . odin_builder_attrs($n, 'hero-facts') . ' aria-label="Datos rápidos">' . $li('items', static fn($i) => '<li><strong>' . esc_html($i['value'] ?? '') . '</strong> ' . esc_html($i['label'] ?? '') . '</li>') . '</ul>';
		case 'terminal':
			$lines = $li('lines', static function ($l) {
				$t = esc_html($l['text'] ?? '');
				$k = $l['kind'] ?? 'text';
				return $k === 'cmd' ? '<span class="t-line"><b>$</b> ' . $t . "</span>\n" : '<span class="t-line' . ($k === 'ok' ? ' t-ok' : ($k === 'info' ? ' t-info' : '')) . '">' . $t . "</span>\n";
			});
			return '<div' . odin_builder_attrs($n, 'terminal') . ' aria-hidden="true"><div class="terminal-bar"><i></i><i></i><i></i><span>' . esc_html($s['title'] ?? '') . '</span></div><pre class="terminal-body"><code>' . rtrim($lines) . '</code><span class="caret"></span></pre></div>';
		case 'phonevideo':
			if (empty($s['src'])) {
				return odin_builder_placeholder($n, '▶ Elige un vídeo MP4 vertical');
			}
			return sprintf('<div%s><video class="odn-promo" src="%s"%s width="720" height="1280" muted loop playsinline preload="none" controls aria-label="%s"></video></div>', odin_builder_attrs($n, 'phone'), esc_url($s['src']), !empty($s['poster']) ? ' poster="' . esc_url($s['poster']) . '"' : '', esc_attr($s['label'] ?? 'Vídeo'));
		case 'linkcards':
			return '<ul' . odin_builder_attrs($n, 'industries') . '>' . $li('items', static function ($i) {
				$t = esc_html($i['title'] ?? '');
				return '<li><h3>' . (!empty($i['link']) ? '<a href="' . esc_url($i['link']) . '">' . $t . '</a>' : $t) . '</h3><p>' . esc_html($i['text'] ?? '') . '</p></li>';
			}) . '</ul>';
		case 'chips':
			$look = ($s['look'] ?? 'stack') === 'tags' ? 'tags' : 'stack';
			return '<ul' . odin_builder_attrs($n, $look) . '>' . $li('items', static fn($i) => '<li>' . esc_html($i['text'] ?? '') . '</li>') . '</ul>';
		case 'project':
			$mocks = function_exists('odin_builder_mockups') ? odin_builder_mockups() : [];
			$mock = isset($mocks[$s['mock'] ?? '']) ? '<div class="mock assemble" aria-hidden="true">' . $mocks[$s['mock']][1] . '</div>' : '';
			$feat = $li('features', static fn($i) => '<li>' . esc_html($i['text'] ?? '') . '</li>');
			$stats = $li('stats', static fn($i) => '<div><dt>' . esc_html($i['value'] ?? '') . '</dt><dd>' . esc_html($i['label'] ?? '') . '</dd></div>');
			$tags = $li('tags', static fn($i) => '<li>' . esc_html($i['text'] ?? '') . '</li>');
			return '<article' . odin_builder_attrs($n, 'project') . ">$mock<div class=\"project-body\">"
				. (!empty($s['kicker']) ? '<p class="kicker">' . esc_html($s['kicker']) . '</p>' : '')
				. sprintf('<%1$s>%2$s</%1$s>', ($s['titleTag'] ?? 'h3') === 'h2' ? 'h2' : 'h3', esc_html($s['title'] ?? '')) . wpautop($s['html'] ?? '')
				. ($feat ? "<ul class=\"features\">$feat</ul>" : '') . ($stats ? "<dl class=\"stats\">$stats</dl>" : '') . ($tags ? "<ul class=\"tags\" aria-label=\"Tecnologías\">$tags</ul>" : '')
				. '</div></article>';
		case 'person':
			$photo = !empty($s['imageId']) ? wp_get_attachment_image((int) $s['imageId'], 'thumbnail', false, ['class' => 'avatar', 'alt' => '']) : (!empty($s['src']) ? '<img class="avatar" src="' . esc_url($s['src']) . '" alt="" loading="lazy">' : '<span class="avatar" aria-hidden="true">' . esc_html($s['initials'] ?? '') . '</span>');
			return '<article' . odin_builder_attrs($n, 'person') . ">$photo<div><h4>" . esc_html($s['name'] ?? '') . '</h4>' . (!empty($s['role']) ? '<p class="role">' . esc_html($s['role']) . '</p>' : '') . '<p>' . esc_html($s['text'] ?? '') . '</p></div></article>';
		case 'obra3d':
			// Lienzo de la casa 3D que se construye con el scroll del contenedor padre (assets/odin-obra.js).
			$stages = max(1, min(20, (int) ($s['stages'] ?? 6)));
			$img = !empty($s['imageId']) ? wp_get_attachment_image_url((int) $s['imageId'], 'large') : ($s['src'] ?? '');
			return '<div' . odin_builder_attrs($n, 'obra__stage') . ' data-stages="' . $stages . '"' . ($img ? ' style="--obra-img:url(' . esc_attr(esc_url($img)) . ')"' : '') . '>'
				. '<canvas role="img" aria-label="' . esc_attr($s['label'] ?? '') . '"></canvas>'
				. '<div class="obra__meter" aria-hidden="true"><span class="obra__num">00</span><i><b class="obra__bar"></b></i><span>' . sprintf('%02d', $stages) . '</span></div></div>';
		case 'pasos':
			$k = 0;
			return '<ol' . odin_builder_attrs($n, 'pasos') . ' aria-label="' . esc_attr($s['label'] ?? '') . '">' . $li('items', static function ($i) use (&$k) {
				++$k;
				return sprintf('<li class="paso" data-step="%1$d"><span class="paso__n">%1$02d</span><h2>%2$s</h2><p>%3$s</p></li>', $k, esc_html($i['title'] ?? ''), esc_html($i['text'] ?? ''));
			}) . '</ol>';
		case 'pjcard':
			$img = !empty($s['imageId']) ? wp_get_attachment_image((int) $s['imageId'], 'large', false, ['alt' => $s['alt'] ?? '', 'loading' => 'lazy', 'decoding' => 'async'])
				: (!empty($s['src']) ? sprintf('<img src="%s" alt="%s" loading="lazy" decoding="async">', esc_url($s['src']), esc_attr($s['alt'] ?? '')) : '');
			$media = array_values(array_filter($rows('media'), static fn($m) => !empty($m['src'])));
			$fotos = count(array_filter($media, static fn($m) => ($m['kind'] ?? 'img') === 'img'));
			$count = implode(' · ', array_filter([$fotos ? $fotos . ($fotos === 1 ? ' foto' : ' fotos') : '', count($media) > $fotos ? 'video' : '']));
			$title = esc_html($s['title'] ?? '');
			if ($media) {
				$phone = preg_replace('/\D/', '', (string) ($s['phone'] ?? ''));
				$data = [
					'title' => $s['title'] ?? '', 'tag' => $s['tag'] ?? '', 'lugar' => $s['place'] ?? '', 'desc' => $s['desc'] ?? '',
					'datos' => array_values(array_filter(array_column($rows('datos'), 'text'))),
					'media' => array_map(static fn($m) => ($m['kind'] ?? 'img') === 'yt'
						? ['t' => 'yt', 'id' => preg_replace('/[^\w-]/', '', (string) ($m['yt'] ?? '')), 'src' => $m['src'], 'alt' => $m['alt'] ?? '']
						: ['t' => 'img', 'src' => $m['src'], 'alt' => $m['alt'] ?? ''], $media),
					'cta' => $s['cta'] ?? '',
					'wa' => $phone ? 'https://wa.me/' . $phone . '?text=' . rawurlencode('Hola, vi el proyecto ' . ($s['title'] ?? '') . ' en su página y quiero cotizar algo similar') : '',
				];
				$title = sprintf('<button type="button" class="pj__open" aria-haspopup="dialog" data-pj="%s">%s</button>', esc_attr(wp_json_encode($data)), $title);
			}
			$size = ['big' => ' pj--big', 'wide' => ' pj--wide'][$s['size'] ?? ''] ?? '';
			return '<article' . odin_builder_attrs($n, 'pj' . (!empty($s['tilt']) ? ' tilt' : '') . $size) . ">$img<div class=\"pj__info\">"
				. (!empty($s['tag']) ? '<p class="pj__tag">' . esc_html($s['tag']) . '</p>' : '') . "<h3>$title</h3>"
				. (!empty($s['text']) ? '<p>' . esc_html($s['text']) . '</p>' : '') . '</div>'
				. ($count ? '<span class="pj__count">' . $count . '</span>' : '') . '</article>';
		case 'steps':
			return '<ol' . odin_builder_attrs($n, 'steps') . '>' . $li('items', static fn($i) => '<li><h3>' . esc_html($i['title'] ?? '') . '</h3><p>' . esc_html($i['text'] ?? '') . '</p></li>') . '</ol>';
		case 'faq':
			$items = $rows('items');
			if (!$items) {
				return odin_builder_placeholder($n, '? Añade preguntas');
			}
			if (!odin_builder_preview() && !empty($s['schema'])) {
				odin_builder_faq_schema($items);
			}
			return '<div' . odin_builder_attrs($n, 'faq') . '>' . implode('', array_map(static fn($i) => '<details><summary><h3>' . esc_html($i['q'] ?? '') . '</h3></summary>' . wpautop($i['a'] ?? '') . '</details>', $items)) . '</div>';
		case 'breadcrumbs':
			$items = $rows('items');
			$out = [];
			foreach ($items as $k => $i) {
				$t = esc_html($i['text'] ?? '');
				$out[] = $k === count($items) - 1 || empty($i['link']) ? '<span aria-current="page">' . $t . '</span>' : '<a href="' . esc_url($i['link']) . '">' . $t . '</a>';
			}
			return '<nav' . odin_builder_attrs($n, 'crumbs') . ' aria-label="Ruta de navegación">' . implode('<span aria-hidden="true">/</span>', $out) . '</nav>';
		case 'menu':
			return odin_builder_render_menu($n, $s);
		case 'mockup':
			// Mismo motor que los mockups del original: --x/--y/--z/--r = desde dónde llega cada pieza, --s = orden.
			$clamp = static fn($v, $min, $max) => max($min, min($max, (int) $v));
			$pieces = '';
			foreach ($rows('pieces') as $p) {
				$kind = $p['kind'] ?? 'node';
				$style = sprintf('left:%d%%;top:%d%%;right:auto;bottom:auto;--x:%dpx;--y:%dpx;--z:%dpx;--r:%ddeg;--s:%s',
					$clamp($p['left'] ?? 10, 0, 95), $clamp($p['top'] ?? 20, 0, 95), $clamp($p['fromX'] ?? 0, -500, 500), $clamp($p['fromY'] ?? 0, -500, 500),
					$clamp($p['fromZ'] ?? 200, -500, 600), $clamp($p['rotate'] ?? 0, -180, 180), number_format($clamp($p['order'] ?? 1, 0, 9) / 10, 1, '.', ''));
				$t = esc_html($p['text'] ?? '');
				$map = [
					'node' => ['pc fnode', $t], 'node-accent' => ['pc fnode cond', $t], 'bubble' => ['pc bubble', $t],
					'toast' => ['pc toast', '<i class="ok"></i>' . $t], 'toast-alert' => ['pc toast alert', '<i class="warn"></i>' . $t],
					'chip' => ['pc chip', '<i class="dot"></i>' . $t], 'card' => ['pc tile', $t],
					'kpi' => ['pc kpi', '<span>' . $t . '</span><svg viewBox="0 0 60 20"><polyline points="0,16 12,12 24,14 36,6 48,8 60,2"/></svg>'],
				];
				[$class, $inner] = $map[$kind] ?? $map['node'];
				$pieces .= sprintf('<div class="%s" style="%s">%s</div>', $class, esc_attr($style), $inner);
			}
			return '<div' . odin_builder_attrs($n) . '><div class="mock assemble" aria-hidden="true"><div class="pc win' . (!empty($s['grid']) ? ' grid-bg' : '') . '" style="--y:60px;--z:-160px;--s:0"><div class="win-bar"><i></i><i></i><i></i><span>' . esc_html($s['title'] ?? '') . '</span></div><div class="win-side"><b></b><b></b><b></b><b></b></div></div>' . $pieces . '</div></div>';
		case 'whatsapp':
			$phone = preg_replace('/\D/', '', (string) ($s['phone'] ?? ''));
			if (!$phone) {
				return odin_builder_placeholder($n, 'WhatsApp: escribe el número con código de país');
			}
			$href = 'https://wa.me/' . $phone . (!empty($s['message']) ? '?text=' . rawurlencode($s['message']) : '');
			$bubble = !empty($s['bubbleText']) ? sprintf('<div class="wa-bubble" role="status" style="--wa-delay:%ds"><button class="wa-close" type="button" aria-label="Cerrar mensaje">&times;</button>%s%s</div>', max(0, (int) ($s['delay'] ?? 4)), !empty($s['bubbleTitle']) ? '<strong>' . esc_html($s['bubbleTitle']) . '</strong> ' : '', esc_html($s['bubbleText'])) : '';
			return '<div' . odin_builder_attrs($n) . ">$bubble" . sprintf('<a class="wa-float" href="%s" target="_blank" rel="noopener" aria-label="Escribir por WhatsApp"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M17.47 14.38c-.3-.15-1.76-.87-2.03-.97-.27-.1-.47-.15-.67.15-.2.3-.77.97-.94 1.16-.17.2-.35.22-.64.08-.3-.15-1.26-.46-2.39-1.48-.88-.79-1.48-1.76-1.65-2.06-.17-.3-.02-.46.13-.61.13-.13.3-.35.45-.52.15-.17.2-.3.3-.5.1-.2.05-.37-.03-.52-.07-.15-.67-1.61-.92-2.21-.24-.58-.49-.5-.67-.51h-.57c-.2 0-.52.07-.79.37-.27.3-1.04 1.02-1.04 2.48 0 1.46 1.07 2.88 1.21 3.07.15.2 2.1 3.2 5.08 4.49.71.31 1.26.49 1.69.63.71.23 1.36.2 1.87.12.57-.09 1.76-.72 2.01-1.41.25-.7.25-1.29.17-1.41-.07-.12-.27-.2-.57-.35M12.05 21.79h-.01a9.87 9.87 0 0 1-5.03-1.38l-.36-.21-3.74.98 1-3.65-.24-.37a9.86 9.86 0 0 1-1.51-5.26c0-5.45 4.44-9.88 9.89-9.88 2.64 0 5.12 1.03 6.99 2.9a9.83 9.83 0 0 1 2.89 6.99c0 5.45-4.44 9.88-9.89 9.88m8.41-18.3A11.82 11.82 0 0 0 12.05 0C5.5 0 .16 5.34.16 11.89c0 2.1.55 4.14 1.59 5.95L.06 24l6.3-1.65a11.88 11.88 0 0 0 5.68 1.45h.01c6.55 0 11.89-5.34 11.89-11.89a11.82 11.82 0 0 0-3.48-8.41z"/></svg></a>', esc_url($href)) . '</div>';
	}
	return '';
}

/** Menú de WordPress (Apariencia → Menús) con submenús desplegables y botón ☰ en móvil. */
function odin_builder_render_menu(array $n, array $s) {
	$items = !empty($s['menuId']) ? wp_get_nav_menu_items((int) $s['menuId']) : [];
	if (!$items) {
		return odin_builder_placeholder($n, '☰ Elige un menú (Apariencia → Menús)');
	}
	$tree = [];
	foreach ($items as $it) {
		$tree[(int) $it->menu_item_parent][] = $it;
	}
	$current = untrailingslashit(strtok((is_ssl() ? 'https://' : 'http://') . ($_SERVER['HTTP_HOST'] ?? '') . ($_SERVER['REQUEST_URI'] ?? ''), '?'));
	$link = static function ($it) use ($current) {
		$cur = untrailingslashit($it->url) === $current ? ' aria-current="page"' : '';
		return sprintf('<a href="%s"%s%s>%s</a>', esc_url($it->url), $cur, $it->target === '_blank' ? ' target="_blank" rel="noopener"' : '', esc_html($it->title));
	};
	$html = '';
	foreach ($tree[0] ?? [] as $it) {
		$kids = $tree[(int) $it->ID] ?? [];
		if ($kids) {
			$html .= '<li class="has-sub"><details><summary>' . esc_html($it->title) . '</summary><ul class="sub">' . implode('', array_map(static fn($k) => '<li>' . $link($k) . '</li>', $kids)) . '</ul></details></li>';
		} else {
			$html .= '<li>' . $link($it) . '</li>';
		}
	}
	$id = 'menu-' . $n['id'];
	$toggle = empty($s['noToggle']) ? '<button class="nav-toggle" type="button" aria-expanded="false" aria-controls="' . $id . '" aria-label="Abrir menú"><span></span><span></span><span></span></button>' : '';
	return '<div' . odin_builder_attrs($n, 'odn-menu') . '>' . $toggle . '<nav id="' . $id . '" aria-label="' . esc_attr($s['label'] ?? 'Principal') . "\"><ul>$html</ul></nav></div>";
}

/** Acumula preguntas para un único FAQPage (schema.org) en el pie de la página. */
function odin_builder_faq_schema($items = null) {
	static $all = [], $hooked = false;
	if ($items === null) {
		return $all;
	}
	foreach ($items as $i) {
		if (!empty($i['q']) && !empty($i['a'])) {
			$all[] = ['@type' => 'Question', 'name' => $i['q'], 'acceptedAnswer' => ['@type' => 'Answer', 'text' => wp_strip_all_tags($i['a'])]];
		}
	}
	if (!$hooked) {
		$hooked = true;
		add_action('wp_footer', static function () {
			$q = odin_builder_faq_schema();
			if ($q) {
				echo '<script type="application/ld+json">' . wp_json_encode(['@context' => 'https://schema.org', '@type' => 'FAQPage', 'mainEntity' => $q], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_HEX_TAG) . "</script>\n";
			}
		});
	}
}

function odin_builder_render_wc(array $n, array $s, $a) {
	$p = odin_builder_product();
	if (!$p) {
		return odin_builder_placeholder($n, '🛒 Crea un producto para ver aquí sus datos');
	}
	switch ($n['type']) {
		case 'wc-title':
			$tag = $s['tag'] ?? 'h1';
			return "<$tag" . odin_builder_attrs($n, 'product_title') . '>' . esc_html($p->get_name()) . "</$tag>";
		case 'wc-price':
			return "<p$a>" . $p->get_price_html() . '</p>';
		case 'wc-images':
			$main = $p->get_image('woocommerce_single', ['loading' => 'eager', 'class' => 'odn-wcimg__main']);
			$thumbs = '';
			$ids = array_merge($p->get_image_id() ? [$p->get_image_id()] : [], $p->get_gallery_image_ids());
			if (count($ids) > 1) {
				foreach ($ids as $i => $id) {
					$thumbs .= sprintf('<button type="button" data-full="%s" aria-label="%s"%s>%s</button>', esc_url(wp_get_attachment_image_url($id, 'woocommerce_single')), esc_attr(sprintf('Ver imagen %d', $i + 1)), $i ? '' : ' aria-current="true"', wp_get_attachment_image($id, 'woocommerce_gallery_thumbnail'));
				}
				$thumbs = '<div class="odn-wcimg__thumbs">' . $thumbs . '</div>';
			}
			return "<div$a>$main$thumbs</div>";
		case 'wc-add-to-cart':
			return "<div$a>" . odin_builder_capture('woocommerce_template_single_add_to_cart') . '</div>';
		case 'wc-excerpt':
			return "<div$a>" . apply_filters('woocommerce_short_description', get_post_field('post_excerpt', $p->get_id())) . '</div>';
		case 'wc-description':
			return "<div$a>" . wc_format_content($p->get_description()) . '</div>';
		case 'wc-meta':
			return "<div$a>" . odin_builder_capture('woocommerce_template_single_meta') . '</div>';
		case 'wc-rating':
			$r = odin_builder_capture('woocommerce_template_single_rating');
			return $r ? "<div$a>$r</div>" : odin_builder_placeholder($n, '★ Sin valoraciones todavía');
		case 'wc-tabs':
			return "<div$a>" . odin_builder_capture('woocommerce_output_product_data_tabs') . '</div>';
		case 'wc-related':
			$r = odin_builder_capture('woocommerce_related_products', ['posts_per_page' => max(1, (int) ($s['count'] ?? 4)), 'columns' => max(1, min(6, (int) ($s['columns'] ?? 4)))]);
			return $r ? "<div$a>$r</div>" : odin_builder_placeholder($n, 'Sin productos relacionados');
	}
	return '';
}

/** CSS base del builder (layout por defecto). Se imprime una vez por página que usa el builder. */
function odin_builder_base_css() {
	return odin_builder_where('.odn-container{display:flex;flex-direction:column;gap:20px;box-sizing:border-box;position:relative;background-size:cover;background-position:center}'
		. '.odn-container>.odn{min-width:0}a.odn-container{color:inherit;text-decoration:none}'
		. '.odn-image{margin:0}.odn-image img{display:block;width:100%;height:auto}'
		. '.odn-text>:first-child{margin-top:0}.odn-text>:last-child{margin-bottom:0}'
		. '.odn-spacer{height:40px}.odn-divider{border:0;border-top-width:1px;margin:0;width:100%}'
		. '.odn-heading{margin:0}.odn-video iframe{width:100%;height:auto;aspect-ratio:16/9}'
		. '.odn-button{display:inline-block;text-decoration:none;align-self:flex-start}'
		. '.odn-svg{display:inline-block;width:1em;height:1em;vertical-align:middle;flex:none}'
		. '.odn-icon{font-size:40px;line-height:1;display:inline-flex}a.odn-icon{color:inherit}'
		. '.odn-iconbox{display:flex;gap:16px}.odn-iconbox.is-top{flex-direction:column}.odn-iconbox__icon{font-size:40px;line-height:1;color:var(--wp--preset--color--accent-1,currentColor)}.odn-iconbox__title{margin:0 0 6px;font-size:1.15em}.odn-iconbox__title a{color:inherit;text-decoration:none}.odn-iconbox__body>p:last-child{margin-bottom:0}'
		. '.odn-iconlist{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:10px}.odn-iconlist li{display:flex;align-items:center;gap:10px}.odn-iconlist .odn-svg{color:var(--wp--preset--color--accent-1,currentColor)}'
		. '.odn-accordion details{border-bottom:1px solid color-mix(in srgb,currentColor 15%,transparent)}.odn-accordion summary{cursor:pointer;padding:14px 0;font-weight:600;list-style:none;display:flex;justify-content:space-between}.odn-accordion summary::-webkit-details-marker{display:none}.odn-accordion summary::after{content:"+";font-weight:400}.odn-accordion details[open] summary::after{content:"−"}.odn-acc__body{padding:0 0 14px}'
		. '.odn-tabs__list{display:flex;gap:4px;border-bottom:1px solid color-mix(in srgb,currentColor 15%,transparent);flex-wrap:wrap}.odn-tabs__list button{background:none;border:0;border-bottom:2px solid transparent;padding:10px 16px;font:inherit;color:inherit;cursor:pointer;opacity:.7}.odn-tabs__list button[aria-selected=true]{border-bottom-color:currentColor;opacity:1;font-weight:600}.odn-tabs [role=tabpanel]{padding:16px 0}'
		. '.odn-gallery__grid{display:grid;grid-template-columns:repeat(var(--odn-cols),minmax(0,1fr));gap:12px}.odn-gallery figure{margin:0}.odn-gallery img{display:block;width:100%;height:auto;aspect-ratio:var(--odn-ratio);object-fit:cover;border-radius:4px}@media(max-width:767px){.odn-gallery__grid{grid-template-columns:repeat(2,minmax(0,1fr))}}'
		. '.odn-testimonial{margin:0;display:flex;flex-direction:column;gap:12px}.odn-testimonial blockquote{margin:0;font-size:1.1em;font-style:italic}.odn-testimonial figcaption{display:flex;align-items:center;gap:12px}.odn-testimonial figcaption img{width:52px;height:52px;border-radius:50%;object-fit:cover}.odn-testimonial small{display:block;opacity:.7}.odn-stars{color:#f59e0b;display:flex;gap:2px}.odn-stars .odn-svg{fill:currentColor}'
		. '.odn-social{display:flex;flex-wrap:wrap;gap:10px}.odn-social a{display:inline-flex;align-items:center;justify-content:center;width:40px;height:40px;font-size:20px;color:inherit;border:1px solid currentColor;text-decoration:none;transition:transform .2s}.odn-social a:hover{transform:translateY(-2px)}.odn-social.is-circle a{border-radius:50%}.odn-social.is-square a{border-radius:6px}.odn-social.is-none a{border:0;width:auto;height:auto}'
		. '.odn-map{height:320px}.odn-map iframe{display:block;width:100%;height:100%;border:0}'
		. '.odn-alert{display:flex;gap:12px;padding:14px 16px;border-radius:8px;border-left:4px solid}.odn-alert>.odn-svg{font-size:20px;margin-top:2px}.odn-alert p{margin:4px 0 0}.odn-alert.is-info{background:#eff6ff;color:#1e3a8a}.odn-alert.is-success{background:#ecfdf5;color:#065f46}.odn-alert.is-warning{background:#fffbeb;color:#92400e}.odn-alert.is-danger{background:#fef2f2;color:#991b1b}'
		. '.odn-wc-images{display:flex;flex-direction:column;gap:10px}.odn-wcimg__main{width:100%;height:auto;border-radius:6px}.odn-wcimg__thumbs{display:grid;grid-template-columns:repeat(5,1fr);gap:8px}.odn-wcimg__thumbs button{padding:0;border:2px solid transparent;border-radius:4px;background:none;cursor:pointer}.odn-wcimg__thumbs button[aria-current=true]{border-color:currentColor}.odn-wcimg__thumbs img{display:block;width:100%;height:auto;border-radius:2px}'
		. '.odn-wc-price{font-size:1.4em;margin:0}.odn-wc-price del{opacity:.55;margin-right:.3em}.odn-wc-add-to-cart form.cart{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:0}.odn-wc-add-to-cart .quantity input{width:4.5em;padding:.6em}'
		. '.odn-menu{display:contents}.odn-menu ul{display:flex;gap:4px;list-style:none;margin:0;padding:0}.odn-menu a{text-decoration:none}.odn-menu .has-sub details{position:relative}.odn-menu summary{cursor:pointer;list-style:none}.odn-menu .sub{position:absolute;top:100%;left:0;z-index:30;display:grid;min-width:200px;background:#fff;padding:8px}.nav-toggle{display:none}'
		. '.wa-float{position:fixed;right:20px;bottom:20px;z-index:40;width:60px;height:60px;border-radius:50%;display:grid;place-items:center;background:#25d366}.wa-float svg{width:32px;height:32px;fill:#fff}.wa-bubble{position:fixed;right:92px;bottom:30px;z-index:40;max-width:250px;padding:12px 34px 12px 14px;border-radius:14px 14px 4px 14px;background:#f8fafc;color:#0f172a;font-size:.88rem;line-height:1.4;box-shadow:0 16px 40px -12px rgba(0,0,0,.5)}.wa-bubble[hidden]{display:none}.wa-close{position:absolute;top:4px;right:4px;width:28px;height:28px;border:0;border-radius:50%;background:transparent;cursor:pointer}');
}

/** Envuelve cada selector de una regla en :where() (especificidad 0). */
function odin_builder_where($css) {
	return preg_replace_callback('/(^|})([^{}@]+)\{/', static function ($m) {
		// Los pseudo-elementos no pueden ir dentro de :where().
		$sels = array_map(static fn($x) => preg_match('/^(.*?)(::[\w-]+.*)$/', trim($x), $p) ? ':where(' . $p[1] . ')' . $p[2] : ':where(' . trim($x) . ')', explode(',', $m[2]));
		return $m[1] . implode(',', $sels) . '{';
	}, $css);
}
