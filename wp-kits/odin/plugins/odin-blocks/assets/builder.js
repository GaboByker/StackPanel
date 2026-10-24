/**
 * Odin Builder — editor visual. Sin build: usa React (wp.element) y componentes que ya trae WordPress.
 * El lienzo es la página real en un iframe; el HTML/CSS de la vista previa lo genera el mismo PHP del frontend.
 */
(function (wp, cfg) {
	'use strict';
	const { createElement: el, useState, useEffect, useRef, Fragment } = wp.element;
	const C = wp.components;
	const apiFetch = wp.apiFetch;

	// Iconos SVG de trazo (una sola familia). Decorativos: el botón que los contiene lleva aria-label.
	const ICONS = {
		desktop: '<rect x="2" y="4" width="20" height="13" rx="2"/><path d="M8 21h8M12 17v4"/>',
		tablet: '<rect x="5" y="2" width="14" height="20" rx="2"/><path d="M11 18h2"/>',
		mobile: '<rect x="7" y="2" width="10" height="20" rx="2"/><path d="M11 18h2"/>',
		undo: '<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>',
		redo: '<path d="m15 14 5-5-5-5"/><path d="M20 9H9.5a5.5 5.5 0 0 0 0 11H13"/>',
		layers: '<path d="m12 2-10 5 10 5 10-5-10-5Z"/><path d="m2 17 10 5 10-5M2 12l10 5 10-5"/>',
		close: '<path d="M18 6 6 18M6 6l12 12"/>',
		back: '<path d="m15 18-6-6 6-6"/>',
		up: '<path d="M12 19V5M5 12l7-7 7 7"/>',
		down: '<path d="M12 5v14M19 12l-7 7-7-7"/>',
		copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
		trash: '<path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/>',
		container: '<rect x="3" y="4" width="18" height="16" rx="2"/><rect x="7" y="8" width="10" height="8" rx="1" stroke-dasharray="2 2"/>',
		cols2: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M12 4v16"/>',
		cols3: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16M15 4v16"/>',
		hero: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 10h10M9 14h6"/>',
		heading: '<path d="M6 4v16M18 4v16M6 12h12"/>',
		text: '<path d="M4 6h16M4 12h16M4 18h10"/>',
		image: '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="m21 15-5-5L5 21"/>',
		button: '<rect x="3" y="8" width="18" height="8" rx="4"/><path d="M8 12h8"/>',
		spacer: '<path d="M12 3v18M8 7l4-4 4 4M8 17l4 4 4-4"/>',
		divider: '<path d="M3 12h18"/><path d="M8 6h8M8 18h8" opacity=".4"/>',
		video: '<rect x="2" y="5" width="20" height="14" rx="2"/><path d="m10 9 5 3-5 3V9Z"/>',
		code: '<path d="m16 18 6-6-6-6M8 6l-6 6 6 6"/>',
		cart: '<circle cx="9" cy="20" r="1"/><circle cx="18" cy="20" r="1"/><path d="M2 3h3l2.7 12.4a2 2 0 0 0 2 1.6h8.6a2 2 0 0 0 2-1.6L22 7H6"/>',
		link: '<path d="M10 13a5 5 0 0 0 7.07 0l3-3a5 5 0 0 0-7.07-7.07l-1 1"/><path d="M14 11a5 5 0 0 0-7.07 0l-3 3a5 5 0 0 0 7.07 7.07l1-1"/>',
		external: '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14 21 3"/>',
		cols4: '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="M7 4v16M12 4v16M17 4v16"/>',
		grid: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
		split: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/>',
		star: '<path d="m12 2 3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/>',
		iconbox: '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="12" cy="9" r="2.5"/><path d="M7 15h10M9 18h6"/>',
		list: '<path d="M9 6h12M9 12h12M9 18h12M4 6h.01M4 12h.01M4 18h.01"/>',
		accordion: '<rect x="3" y="3" width="18" height="6" rx="1"/><rect x="3" y="11" width="18" height="10" rx="1"/><path d="m15 6-1.5 1.5L12 6"/>',
		tabs: '<path d="M3 8h18v12H3zM3 8V4h6v4M9 4h6v4"/>',
		gallery: '<rect x="3" y="3" width="8" height="8" rx="1"/><rect x="13" y="3" width="8" height="8" rx="1"/><rect x="3" y="13" width="8" height="8" rx="1"/><rect x="13" y="13" width="8" height="8" rx="1"/>',
		quote: '<path d="M3 21c3 0 7-1 7-8V5H3v7h4c0 4-2 6-4 6M14 21c3 0 7-1 7-8V5h-7v7h4c0 4-2 6-4 6"/>',
		share: '<circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><path d="m8.6 13.5 6.8 4M15.4 6.5l-6.8 4"/>',
		pin: '<path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/>',
		alert: '<circle cx="12" cy="12" r="10"/><path d="M12 8v4M12 16h.01"/>',
		mail: '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="m22 6-10 7L2 6"/>',
		globe: '<circle cx="12" cy="12" r="10"/><path d="M2 12h20M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>',
		tag: '<path d="M20.59 13.41 13.42 20.58a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82zM7 7h.01"/>',
		gear: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
		plus: '<path d="M12 5v14M5 12h14"/>',
		apps: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
		user: '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
		chat: '<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/>',
		arrow: '<path d="M5 12h14M12 5l7 7-7 7"/>',
		minus: '<path d="M5 12h14"/>',
	};
	const Icon = ({ n, s }) => el('svg', { className: 'odb-icon', viewBox: '0 0 24 24', width: s || 18, height: s || 18, fill: 'none', stroke: 'currentColor', strokeWidth: 1.75, strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true, focusable: false, dangerouslySetInnerHTML: { __html: ICONS[n] } });

	// ------------------------------------------------------------ definiciones
	const WIDGETS = {
		container: { label: 'Contenedor', icon: 'container', def: () => ({ padding: { d: '20px' } }) },
		heading: { label: 'Título', icon: 'heading', def: () => ({ text: 'Escribe tu título', tag: 'h2' }) },
		text: { label: 'Texto', icon: 'text', def: () => ({ html: '<p>Escribe aquí tu texto.</p>' }) },
		image: { label: 'Imagen', icon: 'image', def: () => ({}) },
		button: { label: 'Botón', icon: 'button', def: () => ({ text: 'Haz clic', link: '#' }) },
		spacer: { label: 'Espaciador', icon: 'spacer', def: () => ({ height: { d: '40px' } }) },
		divider: { label: 'Divisor', icon: 'divider', def: () => ({}) },
		video: { label: 'Vídeo', icon: 'video', def: () => ({}) },
		html: { label: 'HTML', icon: 'code', def: () => ({}), only: cfg.canUnfiltered },
		products: { label: 'Productos', icon: 'cart', def: () => ({ count: 4, columns: 4 }), only: cfg.hasWoo },
		icon: { label: 'Icono', icon: 'star', group: 'general', def: () => ({ icon: 'star' }) },
		iconbox: { label: 'Caja de icono', icon: 'iconbox', group: 'general', def: () => ({ icon: 'zap', title: 'Título de la caja', html: '<p>Describe aquí esta ventaja.</p>' }) },
		iconlist: { label: 'Lista con iconos', icon: 'list', group: 'general', def: () => ({ items: [{ icon: 'check', text: 'Primer elemento' }, { icon: 'check', text: 'Segundo elemento' }] }) },
		accordion: { label: 'Acordeón', icon: 'accordion', group: 'general', def: () => ({ openFirst: true, items: [{ title: '¿Primera pregunta?', content: '<p>Respuesta.</p>' }, { title: '¿Segunda pregunta?', content: '<p>Respuesta.</p>' }] }) },
		tabs: { label: 'Pestañas', icon: 'tabs', group: 'general', def: () => ({ items: [{ title: 'Pestaña 1', content: '<p>Contenido 1.</p>' }, { title: 'Pestaña 2', content: '<p>Contenido 2.</p>' }] }) },
		gallery: { label: 'Galería', icon: 'gallery', group: 'general', def: () => ({ columns: 3, ratio: '1/1' }) },
		testimonial: { label: 'Testimonio', icon: 'quote', group: 'general', def: () => ({ quote: '<p>Un servicio excelente, lo recomiendo.</p>', name: 'Nombre del cliente', role: 'Cliente', rating: 5 }) },
		social: { label: 'Redes sociales', icon: 'share', group: 'general', def: () => ({ shape: 'circle', items: [{ network: 'facebook', url: 'https://facebook.com/' }, { network: 'instagram', url: 'https://instagram.com/' }, { network: 'whatsapp', url: 'https://wa.me/' }] }) },
		map: { label: 'Mapa', icon: 'pin', group: 'general', def: () => ({ address: 'Quito, Ecuador', zoom: 14 }) },
		alert: { label: 'Alerta', icon: 'alert', group: 'general', def: () => ({ kind: 'info', title: 'Aviso', html: '<p>Mensaje importante.</p>' }) },
		form: { label: 'Formulario', icon: 'mail', group: 'general', def: () => ({ submitLabel: 'Enviar', fields: [{ label: 'Nombre', type: 'text', required: true, width: '50' }, { label: 'Email', type: 'email', required: true, width: '50' }, { label: 'Mensaje', type: 'textarea', required: true, width: '100' }] }) },
		template: { label: 'Plantilla global', icon: 'globe', group: 'global', def: () => ({}) },
		card: { label: 'Tarjeta', icon: 'iconbox', group: 'site', def: () => ({ icon: 'monitor', title: 'Título de la tarjeta', html: '<p>Describe aquí el servicio.</p>', tilt: true }) },
		facts: { label: 'Datos rápidos', icon: 'list', group: 'site', def: () => ({ items: [{ value: '3', label: 'sistemas en producción' }, { value: 'Docker', label: 'en cada entrega' }] }) },
		terminal: { label: 'Terminal animada', icon: 'code', group: 'site', def: () => ({ title: 'odin.01 ~ proyecto', lines: [{ kind: 'cmd', text: 'npm run build' }, { kind: 'ok', text: '✓ build listo' }] }) },
		phonevideo: { label: 'Vídeo en teléfono', icon: 'video', group: 'site', def: () => ({ label: 'Vídeo de presentación' }) },
		linkcards: { label: 'Lista de negocios', icon: 'apps', group: 'site', def: () => ({ items: [{ title: 'Tiendas online', link: '/', text: 'Catálogo, carrito y pedidos.' }] }) },
		chips: { label: 'Chips / etiquetas', icon: 'tag', group: 'site', def: () => ({ look: 'stack', items: [{ text: 'WordPress' }, { text: 'Docker' }] }) },
		project: { label: 'Proyecto', icon: 'gallery', group: 'site', def: () => ({ mock: 'dashboard', kicker: 'Categoría', title: 'Nombre del proyecto', html: '<p>Qué resuelve este proyecto.</p>', features: [{ text: 'Característica' }], stats: [{ value: '100', label: 'dato destacado' }], tags: [{ text: 'React' }] }) },
		person: { label: 'Persona / equipo', icon: 'user', group: 'site', def: () => ({ initials: 'AB', name: 'Nombre Apellido', role: 'Cargo', text: 'Qué hace en el equipo.' }) },
		steps: { label: 'Pasos / proceso', icon: 'list', group: 'site', def: () => ({ items: [{ title: 'Paso uno', text: 'Descripción.' }, { title: 'Paso dos', text: 'Descripción.' }] }) },
		faq: { label: 'Preguntas (FAQ)', icon: 'accordion', group: 'site', def: () => ({ schema: true, items: [{ q: '¿Pregunta frecuente?', a: '<p>Respuesta.</p>' }] }) },
		breadcrumbs: { label: 'Ruta de navegación', icon: 'arrow', group: 'site', def: () => ({ items: [{ text: 'Inicio', link: '/' }, { text: 'Página actual' }] }) },
		menu: { label: 'Menú', icon: 'list', group: 'site', def: () => ({ label: 'Principal' }) },
		mockup: { label: 'Mockup animado', icon: 'apps', group: 'site', def: () => ({ title: 'Mi sistema', grid: true, maxWidth: { d: '640px' }, width: { d: '100%' }, pieces: [
			{ kind: 'node', text: 'Paso 1', left: 16, top: 22, fromX: -170, fromY: -90, fromZ: 180, rotate: -30, order: 1 },
			{ kind: 'node-accent', text: '¿Condición?', left: 58, top: 22, fromX: 140, fromY: -150, fromZ: 220, rotate: 25, order: 2 },
			{ kind: 'node', text: 'Paso 2', left: 16, top: 56, fromX: -150, fromY: 130, fromZ: 160, rotate: 20, order: 3 },
			{ kind: 'bubble', text: 'Hola, quiero información', left: 50, top: 80, fromX: 220, fromY: 60, fromZ: 300, rotate: 15, order: 5 }] }) },
		obra3d: { label: 'Obra 3D (scroll)', icon: 'apps', group: 'site', def: () => ({ label: 'Modelo 3D de una casa que se construye por etapas', stages: 6 }) },
		pasos: { label: 'Pasos de obra', icon: 'list', group: 'site', def: () => ({ label: 'Cómo trabajamos', items: [{ title: 'Primer paso', text: 'Descripción.' }, { title: 'Segundo paso', text: 'Descripción.' }] }) },
		pjcard: { label: 'Proyecto con galería', icon: 'gallery', group: 'site', def: () => ({ tag: 'Categoría', title: 'Nombre del proyecto', text: 'Resumen corto.', tilt: true, size: 'normal', cta: 'Quiero un proyecto así' }) },
		whatsapp: { label: 'WhatsApp flotante', icon: 'chat', group: 'site', def: () => ({ phone: '593', message: 'Hola, quiero información', bubbleTitle: '¿Hablamos?', bubbleText: 'Escríbenos por WhatsApp.', delay: 4 }) },
		'wc-title': { label: 'Título producto', icon: 'heading', group: 'woo', def: () => ({ tag: 'h1' }) },
		'wc-price': { label: 'Precio', icon: 'tag', group: 'woo', def: () => ({}) },
		'wc-images': { label: 'Imágenes producto', icon: 'image', group: 'woo', def: () => ({}) },
		'wc-add-to-cart': { label: 'Añadir al carrito', icon: 'cart', group: 'woo', def: () => ({}) },
		'wc-excerpt': { label: 'Descripción corta', icon: 'text', group: 'woo', def: () => ({}) },
		'wc-description': { label: 'Descripción', icon: 'text', group: 'woo', def: () => ({}) },
		'wc-rating': { label: 'Valoración', icon: 'star', group: 'woo', def: () => ({}) },
		'wc-meta': { label: 'SKU / categorías', icon: 'list', group: 'woo', def: () => ({}) },
		'wc-tabs': { label: 'Pestañas producto', icon: 'tabs', group: 'woo', def: () => ({}) },
		'wc-related': { label: 'Relacionados', icon: 'gallery', group: 'woo', def: () => ({ count: 4, columns: 4 }) },
	};
	const uid = () => Math.random().toString(36).slice(2, 10);
	const node = (type, s, c) => ({ id: uid(), type, s: Object.assign(WIDGETS[type].def(), s || {}), c: c || [] });
	const PRESETS = [
		{ label: '2 columnas', icon: 'cols2', make: () => node('container', { display: { d: 'grid' }, cols: { d: 2, m: 1 }, gap: { d: '24px' } }, [node('container'), node('container')]) },
		{ label: '3 columnas', icon: 'cols3', make: () => node('container', { display: { d: 'grid' }, cols: { d: 3, t: 2, m: 1 }, gap: { d: '24px' } }, [node('container'), node('container'), node('container')]) },
		{ label: '4 columnas', icon: 'cols4', make: () => node('container', { display: { d: 'grid' }, cols: { d: 4, t: 2, m: 1 }, gap: { d: '24px' } }, [node('container'), node('container'), node('container'), node('container')]) },
		{ label: 'Cuadrícula 2×2', icon: 'grid', make: () => node('container', { display: { d: 'grid' }, cols: { d: 2, m: 1 }, rows: { d: 2 }, gap: { d: '24px' } }, [node('container'), node('container'), node('container'), node('container')]) },
		{ label: '1/3 + 2/3', icon: 'split', make: () => node('container', { display: { d: 'grid' }, cols: { d: 3, m: 1 }, gap: { d: '24px' } }, [node('container'), node('container', { colSpan: { d: 2, m: 1 } })]) },
		{ label: 'Hero', icon: 'hero', make: () => node('container', { minHeight: { d: '70vh' }, justify: { d: 'center' }, align: { d: 'center' }, textAlign: { d: 'center' }, padding: { d: '80px 20px' }, bgColor: { d: '#111111' }, color: { d: '#ffffff' } }, [node('heading', { text: 'Título principal', tag: 'h1', fontSize: { d: '56px', m: '34px' } }), node('text', { html: '<p>Una frase que explique lo que ofreces.</p>' }), node('button', { text: 'Empezar' })]) },
	];

	// Claves con valor por dispositivo ({d,t,m}).
	const RESP = new Set(['bgColor', 'bgGradient', 'bgImage', 'bgPos', 'bgSize', 'bWidth', 'radius', 'width', 'maxWidth', 'minHeight', 'padding', 'margin', 'color', 'fontSize', 'lineHeight', 'letterSpacing', 'textAlign', 'display', 'direction', 'justify', 'align', 'wrap', 'gap', 'cols', 'rows', 'colSpan', 'rowSpan', 'grow', 'order', 'alignSelf', 'offsetX', 'offsetY', 'height', 'weight']);

	const L = { // etiquetas de opciones
		'': '— Por defecto —', div: 'div', section: 'section', header: 'header', footer: 'footer', article: 'article', aside: 'aside', nav: 'nav',
		flex: 'Flex', grid: 'Grid (columnas)', block: 'Bloque', row: 'Fila →', column: 'Columna ↓', 'row-reverse': 'Fila ←', 'column-reverse': 'Columna ↑',
		'flex-start': 'Inicio', center: 'Centro', 'flex-end': 'Final', 'space-between': 'Espacio entre', 'space-around': 'Espacio alrededor', 'space-evenly': 'Espacio uniforme', stretch: 'Estirar', baseline: 'Línea base',
		nowrap: 'Sin salto', wrap: 'Saltar línea', left: 'Izquierda', right: 'Derecha', justify: 'Justificado', none: 'Ninguno', uppercase: 'MAYÚSCULAS', lowercase: 'minúsculas', capitalize: 'Capitalizar',
		solid: 'Sólido', dashed: 'Guiones', dotted: 'Puntos', double: 'Doble', sm: 'Suave', md: 'Media', lg: 'Grande', xl: 'Muy grande',
		cover: 'Cubrir', contain: 'Contener', auto: 'Auto', fill: 'Rellenar', 'no-repeat': 'No repetir', repeat: 'Repetir', 'repeat-x': 'Repetir X', 'repeat-y': 'Repetir Y', scroll: 'Normal', fixed: 'Fijo (parallax)',
		fade: 'Aparecer', 'fade-up': 'Subir', 'fade-down': 'Bajar', 'fade-left': 'Desde la derecha', 'fade-right': 'Desde la izquierda', zoom: 'Zoom',
		date: 'Más recientes', popularity: 'Más vendidos', rating: 'Mejor valorados', price: 'Precio ↑', 'price-desc': 'Precio ↓', title: 'Nombre', rand: 'Aleatorio',
		'1': 'Sin zoom', '1.03': 'Zoom 3%', '1.05': 'Zoom 5%', '1.1': 'Zoom 10%',
		top: 'Arriba', info: 'Información', success: 'Éxito', warning: 'Advertencia', danger: 'Peligro', circle: 'Círculo', square: 'Cuadrado',
		facebook: 'Facebook', instagram: 'Instagram', twitter: 'X / Twitter', youtube: 'YouTube', linkedin: 'LinkedIn', whatsapp: 'WhatsApp', tiktok: 'TikTok', mail: 'Email', phone: 'Teléfono',
		'1/1': 'Cuadrado 1:1', '4/3': '4:3', '3/2': '3:2', '16/9': '16:9', '3/4': 'Vertical 3:4',
		text: 'Texto', email: 'Email', tel: 'Teléfono', number: 'Número', url: 'URL', textarea: 'Área de texto', radio: 'Opción única', checkbox: 'Casilla', select: 'Desplegable',
		node: 'Nodo', 'node-accent': 'Nodo destacado', bubble: 'Burbuja de chat', toast: 'Aviso (ok)', 'toast-alert': 'Aviso de alerta', chip: 'Chip de estado', kpi: 'Gráfica (KPI)', card: 'Tarjeta',
		'100': 'Completo', '50': 'Mitad', '33': 'Un tercio', '0': 'No', h1: 'h1', h2: 'h2', h3: 'h3', p: 'p',
	};
	const opts = (list) => ['', ...list].map((v) => (Array.isArray(v) ? { value: v[0], label: v[1] } : { value: v, label: L[v] || v }));
	const BG_POS = ['center center', 'top center', 'bottom center', 'center left', 'center right', 'top left', 'top right', 'bottom left', 'bottom right'];

	const CONTENT = {
		container: [{ title: 'Contenedor', f: [['_children', 'children', 'Columnas / elementos internos'], ['tag', 'select', 'Etiqueta HTML', ['div', 'section', 'header', 'footer', 'article', 'aside', 'nav']], ['link', 'url', 'Enlace (todo el bloque)']] }],
		heading: [{ title: 'Título', f: [['text', 'textarea', 'Texto'], ['tag', 'select', 'Etiqueta', ['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'div']], ['link', 'url', 'Enlace']] }],
		text: [{ title: 'Texto', f: [['html', 'rich', 'Contenido (admite HTML básico: <strong>, <em>, <a>, listas…)']] }],
		image: [{ title: 'Imagen', f: [['src', 'image', 'Imagen'], ['alt', 'text', 'Texto alternativo (SEO)'], ['link', 'url', 'Enlace'], ['fit', 'select', 'Ajuste', ['cover', 'contain', 'fill', 'none']], ['caption', 'text', 'Pie de foto']] }],
		button: [{ title: 'Botón', f: [['text', 'text', 'Texto'], ['link', 'url', 'Enlace'], ['newTab', 'bool', 'Abrir en pestaña nueva'], ['nofollow', 'bool', 'nofollow'], ['btnStyle', 'select', 'Estilo base', [['theme', 'Botón del tema'], ['none', 'Solo mis clases (ej. btn)']]]] }],
		spacer: [{ title: 'Espaciador', f: [['height', 'size', 'Altura']] }],
		divider: [{ title: 'Divisor', f: [['weight', 'size', 'Grosor'], ['style', 'select', 'Estilo', ['solid', 'dashed', 'dotted', 'double']], ['lineColor', 'color', 'Color de la línea']] }],
		video: [{ title: 'Vídeo', f: [['url', 'url', 'URL de YouTube o Vimeo']] }],
		html: [{ title: 'HTML', f: [['code', 'code', 'Código HTML (los scripts no se ejecutan en el editor)']] }],
		icon: [{ title: 'Icono', f: [['icon', 'icon', 'Icono'], ['link', 'url', 'Enlace']] }],
		iconbox: [{ title: 'Caja de icono', f: [['icon', 'icon', 'Icono'], ['title', 'text', 'Título'], ['html', 'rich', 'Texto'], ['link', 'url', 'Enlace del título'], ['position', 'select', 'Posición del icono', ['top', 'left']]] }],
		iconlist: [{ title: 'Elementos', f: [['items', 'repeater', 'Elementos', [['icon', 'icon', 'Icono'], ['text', 'text', 'Texto'], ['link', 'url', 'Enlace']], { icon: 'check', text: 'Nuevo elemento' }]] }],
		accordion: [{ title: 'Acordeón', f: [['items', 'repeater', 'Elementos', [['title', 'text', 'Título'], ['content', 'rich', 'Contenido']], { title: 'Nueva pregunta', content: '<p>Respuesta.</p>' }], ['openFirst', 'bool', 'Primero abierto']] }],
		tabs: [{ title: 'Pestañas', f: [['items', 'repeater', 'Pestañas', [['title', 'text', 'Título'], ['content', 'rich', 'Contenido']], { title: 'Nueva pestaña', content: '<p>Contenido.</p>' }]] }],
		gallery: [{ title: 'Galería', f: [['images', 'gallery', 'Imágenes'], ['columns', 'int', 'Columnas (móvil: 2)'], ['ratio', 'select', 'Proporción', ['auto', '1/1', '4/3', '3/2', '16/9', '3/4']]] }],
		testimonial: [{ title: 'Testimonio', f: [['quote', 'rich', 'Testimonio'], ['name', 'text', 'Nombre'], ['role', 'text', 'Cargo / empresa'], ['src', 'image', 'Foto'], ['rating', 'int', 'Estrellas (0–5)']] }],
		social: [{ title: 'Redes sociales', f: [['items', 'repeater', 'Redes', [['network', 'select', 'Red', ['facebook', 'instagram', 'twitter', 'youtube', 'linkedin', 'whatsapp', 'tiktok', 'mail', 'phone']], ['url', 'url', 'URL']], { network: 'facebook', url: 'https://' }], ['shape', 'select', 'Forma', ['circle', 'square', 'none']]] }],
		map: [{ title: 'Mapa', f: [['address', 'text', 'Dirección o lugar'], ['zoom', 'int', 'Zoom (1–20)'], ['height', 'size', 'Altura']] }],
		alert: [{ title: 'Alerta', f: [['kind', 'select', 'Tipo', ['info', 'success', 'warning', 'danger']], ['title', 'text', 'Título'], ['html', 'rich', 'Texto']] }],
		form: [{ title: 'Campos', f: [['fields', 'repeater', 'Campos', [['label', 'text', 'Etiqueta'], ['type', 'select', 'Tipo', cfg.formTypes || ['text', 'email', 'textarea']], ['required', 'bool', 'Obligatorio'], ['options', 'textarea', 'Opciones (una por línea, para desplegable/opción única)'], ['width', 'select', 'Ancho', ['100', '50', '33']]], { label: 'Nuevo campo', type: 'text', width: '100' }]] },
			{ title: 'Envío', f: [['recipient', 'email', 'Enviar a (vacío = email del administrador)'], ['subject', 'text', 'Asunto'], ['submitLabel', 'text', 'Texto del botón'], ['successMessage', 'text', 'Mensaje de éxito']] }],
		template: [{ title: 'Plantilla global', f: [['templateId', 'template', 'Plantilla']] }],
		card: [{ title: 'Tarjeta', f: [['icon', 'icon', 'Icono'], ['title', 'text', 'Título'], ['html', 'rich', 'Texto'], ['link', 'url', 'Enlace del título'], ['tilt', 'bool', 'Inclinación 3D al pasar el ratón']] }],
		facts: [{ title: 'Datos rápidos', f: [['items', 'repeater', 'Datos', [['value', 'text', 'Valor destacado'], ['label', 'text', 'Texto']], { value: '0', label: 'dato' }]] }],
		terminal: [{ title: 'Terminal', f: [['title', 'text', 'Título de la ventana'], ['lines', 'repeater', 'Líneas (se escriben solas)', [['kind', 'select', 'Tipo', ['cmd', 'ok', 'info', 'text']], ['text', 'text', 'Texto']], { kind: 'cmd', text: 'comando' }]] }],
		phonevideo: [{ title: 'Vídeo', f: [['src', 'video', 'Vídeo MP4 (vertical)'], ['poster', 'bgimage', 'Imagen de portada'], ['label', 'text', 'Descripción (accesibilidad)']] }],
		linkcards: [{ title: 'Elementos', f: [['items', 'repeater', 'Elementos', [['title', 'text', 'Título'], ['link', 'url', 'Enlace (opcional)'], ['text', 'text', 'Texto']], { title: 'Nuevo', text: 'Descripción.' }]] }],
		chips: [{ title: 'Chips', f: [['items', 'repeater', 'Elementos', [['text', 'text', 'Texto']], { text: 'Nuevo' }], ['look', 'select', 'Estilo', [['stack', 'Bloques'], ['tags', 'Etiquetas pequeñas']]]] }],
		project: [{ title: 'Proyecto', f: [['mock', 'mock', 'Mockup animado'], ['kicker', 'text', 'Categoría'], ['title', 'text', 'Título'], ['titleTag', 'select', 'Etiqueta del título (SEO)', ['h3', 'h2']], ['html', 'rich', 'Descripción']] },
			{ title: 'Listas', f: [['features', 'repeater', 'Características', [['text', 'text', 'Texto']], { text: 'Nueva característica' }], ['stats', 'repeater', 'Datos', [['value', 'text', 'Valor'], ['label', 'text', 'Texto']], { value: '0', label: 'dato' }], ['tags', 'repeater', 'Tecnologías', [['text', 'text', 'Texto']], { text: 'Nueva' }]] }],
		person: [{ title: 'Persona', f: [['name', 'text', 'Nombre'], ['role', 'text', 'Cargo'], ['text', 'textarea', 'Descripción'], ['initials', 'text', 'Iniciales (si no hay foto)'], ['src', 'image', 'Foto (opcional)']] }],
		steps: [{ title: 'Pasos', f: [['items', 'repeater', 'Pasos (se numeran solos)', [['title', 'text', 'Título'], ['text', 'textarea', 'Texto']], { title: 'Nuevo paso', text: 'Descripción.' }]] }],
		faq: [{ title: 'Preguntas', f: [['items', 'repeater', 'Preguntas', [['q', 'text', 'Pregunta'], ['a', 'rich', 'Respuesta']], { q: '¿Nueva pregunta?', a: '<p>Respuesta.</p>' }], ['schema', 'bool', 'Datos para Google (FAQPage)']] }],
		breadcrumbs: [{ title: 'Ruta', f: [['items', 'repeater', 'Pasos de la ruta', [['text', 'text', 'Texto'], ['link', 'url', 'Enlace (vacío en el último)']], { text: 'Página', link: '/' }]] }],
		menu: [{ title: 'Menú', f: [['menuId', 'menu', 'Menú de WordPress'], ['label', 'text', 'Nombre accesible'], ['noToggle', 'bool', 'Sin botón ☰ en móvil (ej. menú del pie)']] }],
		mockup: [{ title: 'Ventana', f: [['title', 'text', 'Título de la ventana'], ['grid', 'bool', 'Fondo de puntos']] },
			{ title: 'Piezas (se arman al hacer scroll)', f: [['pieces', 'repeater', 'Piezas', [
				['kind', 'select', 'Tipo', ['node', 'node-accent', 'bubble', 'toast', 'toast-alert', 'chip', 'kpi', 'card']], ['text', 'text', 'Texto'],
				['left', 'int', 'Posición: % desde la izquierda'], ['top', 'int', 'Posición: % desde arriba'],
				['fromX', 'int', 'Llega desde X (px, negativo = izquierda)'], ['fromY', 'int', 'Llega desde Y (px, negativo = arriba)'], ['fromZ', 'int', 'Profundidad Z (px, más = más cerca)'],
				['rotate', 'int', 'Giro inicial (grados)'], ['order', 'int', 'Orden de llegada (0 = primero, 9 = último)']],
				{ kind: 'node', text: 'Nueva pieza', left: 30, top: 40, fromX: 150, fromY: -100, fromZ: 200, rotate: 15, order: 4 }]] }],
		obra3d: [{ title: 'Obra 3D', f: [['label', 'text', 'Descripción (accesibilidad)'], ['stages', 'int', 'Número de etapas del contador'], ['src', 'image', 'Imagen si el navegador no tiene 3D']] }],
		pasos: [{ title: 'Pasos', f: [['label', 'text', 'Nombre accesible de la lista'], ['items', 'repeater', 'Pasos (se numeran solos; se resalta el que está en pantalla)', [['title', 'text', 'Título'], ['text', 'textarea', 'Texto']], { title: 'Nuevo paso', text: 'Descripción.' }]] }],
		pjcard: [{ title: 'Tarjeta', f: [['src', 'image', 'Imagen de portada'], ['alt', 'text', 'Texto alternativo (SEO)'], ['tag', 'text', 'Categoría'], ['title', 'text', 'Título'], ['text', 'text', 'Resumen'], ['size', 'select', 'Tamaño en la rejilla', [['normal', 'Normal'], ['big', 'Grande (2×2)'], ['wide', 'Ancha (2×1)']]], ['tilt', 'bool', 'Profundidad al hacer scroll']] },
			{ title: 'Ventana del proyecto', f: [['place', 'text', 'Lugar'], ['desc', 'textarea', 'Descripción'], ['datos', 'repeater', 'Datos', [['text', 'text', 'Texto']], { text: 'Nuevo dato' }], ['phone', 'text', 'WhatsApp (con código de país)'], ['cta', 'text', 'Texto del botón']] },
			{ title: 'Fotos y vídeos', f: [['media', 'repeater', 'Fotos y vídeos (el contador de la tarjeta se calcula solo)', [['kind', 'select', 'Tipo', [['img', 'Foto'], ['yt', 'Vídeo de YouTube']]], ['src', 'bgimage', 'Imagen (en vídeos: portada)'], ['alt', 'text', 'Texto alternativo'], ['yt', 'text', 'ID del vídeo de YouTube (solo vídeos)']], { kind: 'img' }]] }],
		whatsapp: [{ title: 'WhatsApp', f: [['phone', 'text', 'Número con código de país (ej. 593963752082)'], ['message', 'text', 'Mensaje inicial'], ['bubbleTitle', 'text', 'Título de la burbuja'], ['bubbleText', 'text', 'Texto de la burbuja (vacío = sin burbuja)'], ['delay', 'int', 'Segundos antes de mostrar la burbuja']] }],
		'wc-title': [{ title: 'Título del producto', f: [['tag', 'select', 'Etiqueta', ['h1', 'h2', 'h3', 'p']]] }],
		'wc-related': [{ title: 'Relacionados', f: [['count', 'int', 'Cantidad'], ['columns', 'int', 'Columnas']] }],
		products: [{ title: 'Productos', f: [['count', 'int', 'Cantidad'], ['columns', 'int', 'Columnas'], ['category', 'text', 'Slug de categoría (vacío = todas)'], ['orderby', 'select', 'Orden', ['date', 'popularity', 'rating', 'price', 'price-desc', 'title', 'rand']], ['onSale', 'bool', 'Solo en oferta']] }],
	};
	const TYPO = ['heading', 'text', 'button', 'container', 'products'];
	const STYLE = [
		{ title: 'Tamaño y espaciado', f: [['padding', 'box', 'Relleno (padding)'], ['margin', 'box', 'Margen'], ['width', 'size', 'Ancho'], ['maxWidth', 'size', 'Ancho máximo'], ['minHeight', 'size', 'Alto mínimo']] },
		{ title: 'Diseño (layout)', when: (t) => t === 'container', f: [['display', 'select', 'Tipo', ['flex', 'grid', 'block']], ['direction', 'select', 'Dirección', ['column', 'row', 'column-reverse', 'row-reverse'], (s, d) => eff(s, 'display', d) !== 'grid'], ['cols', 'int', 'Columnas', null, (s, d) => eff(s, 'display', d) === 'grid'], ['rows', 'int', 'Filas', null, (s, d) => eff(s, 'display', d) === 'grid'], ['justify', 'select', 'Justificar contenido', ['flex-start', 'center', 'flex-end', 'space-between', 'space-around', 'space-evenly']], ['align', 'select', 'Alinear elementos', ['stretch', 'flex-start', 'center', 'flex-end', 'baseline']], ['wrap', 'select', 'Salto de línea', ['nowrap', 'wrap']], ['gap', 'size', 'Separación entre elementos']] },
		{ title: 'Tipografía', when: (t) => TYPO.includes(t), f: [['color', 'color', 'Color del texto'], ['fontSize', 'size', 'Tamaño'], ['fontWeight', 'select', 'Grosor', ['300', '400', '500', '600', '700', '800', '900']], ['lineHeight', 'size', 'Alto de línea'], ['letterSpacing', 'size', 'Espaciado de letras'], ['textAlign', 'select', 'Alineación', ['left', 'center', 'right', 'justify']], ['textTransform', 'select', 'Transformar', ['none', 'uppercase', 'lowercase', 'capitalize']]] },
		{ title: 'Fondo', when: (t) => t !== 'spacer' && t !== 'divider', f: [['bgColor', 'color', 'Color'], ['bgGradient', 'gradient', 'Degradado (encima de la imagen = overlay)'], ['bgImage', 'bgimage', 'Imagen'], ['bgPos', 'select', 'Posición', BG_POS], ['bgSize', 'select', 'Tamaño', ['cover', 'contain', 'auto']], ['bgRepeat', 'select', 'Repetición', ['no-repeat', 'repeat', 'repeat-x', 'repeat-y']], ['bgFixed', 'select', 'Desplazamiento', ['scroll', 'fixed']]] },
		{ title: 'Borde y sombra', f: [['bStyle', 'select', 'Tipo de borde', ['none', 'solid', 'dashed', 'dotted', 'double']], ['bWidth', 'box', 'Grosor'], ['bColor', 'color', 'Color del borde'], ['radius', 'box', 'Radio (esquinas)'], ['shadow', 'select', 'Sombra', ['none', 'sm', 'md', 'lg', 'xl']]] },
		{ title: 'Posición en el contenedor', f: [['offsetY', 'size', 'Mover vertical (negativo = subir)'], ['offsetX', 'size', 'Mover horizontal (negativo = izquierda)'], ['alignSelf', 'select', 'Alinearse en su celda', [['flex-start', 'Arriba / inicio'], ['center', 'Centro'], ['flex-end', 'Abajo / final'], ['stretch', 'Estirar']]], ['colSpan', 'int', 'Ocupar columnas (grid)'], ['rowSpan', 'int', 'Ocupar filas (grid)'], ['grow', 'select', 'Crecer para llenar (flex)', [['0', 'No'], ['1', 'Sí']]], ['order', 'int', 'Orden (ej. -1 = primero)']] },
		{ title: 'Hover (al pasar el ratón)', f: [['hColor', 'color', 'Color del texto'], ['hBgColor', 'color', 'Color de fondo'], ['hBColor', 'color', 'Color del borde'], ['hScale', 'select', 'Zoom', ['1', '1.03', '1.05', '1.1']]] },
	];
	const ADVANCED = [
		{ title: 'Animación de entrada', f: [['anim', 'select', 'Animación', ['fade', 'fade-up', 'fade-down', 'fade-left', 'fade-right', 'zoom']], ['animDelay', 'int', 'Retraso (ms)']] },
		{ title: 'Responsive', f: [['hide', 'devices', 'Ocultar en']] },
		{ title: 'Atributos', f: [['cssId', 'text', 'ID CSS (para anclas #id)'], ['cssClass', 'text', 'Clases CSS'], ['zIndex', 'int', 'z-index']] },
	];

	// ------------------------------------------------------------ valores responsive
	const isObj = (v) => v && typeof v === 'object' && !Array.isArray(v);
	function val(s, k, dev) {
		const v = s[k];
		if (!RESP.has(k)) return v;
		return isObj(v) ? v[dev] : dev === 'd' ? v : undefined;
	}
	function inherited(s, k, dev) {
		if (!RESP.has(k) || dev === 'd') return undefined;
		const v = isObj(s[k]) ? s[k] : { d: s[k] };
		return dev === 'm' ? (v.t !== undefined ? v.t : v.d) : v.d;
	}
	const eff = (s, k, dev) => { const v = val(s, k, dev); return v !== undefined ? v : inherited(s, k, dev); };
	function withVal(s, k, dev, v) {
		const ns = Object.assign({}, s);
		const empty = v === '' || v === null || v === undefined || v === false || (Array.isArray(v) && !v.length);
		if (RESP.has(k)) {
			const o = Object.assign({}, isObj(s[k]) ? s[k] : s[k] !== undefined ? { d: s[k] } : {});
			if (empty) delete o[dev]; else o[dev] = v;
			if (Object.keys(o).length) ns[k] = o; else delete ns[k];
		} else if (empty) delete ns[k];
		else ns[k] = v;
		return ns;
	}

	// ------------------------------------------------------------ árbol
	function find(list, id) {
		for (const n of list) {
			if (n.id === id) return n;
			const f = n.c && find(n.c, id);
			if (f) return f;
		}
		return null;
	}
	function parentOf(list, id, parent) {
		for (const n of list) {
			if (n.id === id) return parent || null;
			const f = n.c && parentOf(n.c, id, n);
			if (f !== undefined) return f;
		}
		return undefined;
	}
	const update = (list, id, fn) => list.map((n) => (n.id === id ? fn(n) : n.c && n.c.length ? Object.assign({}, n, { c: update(n.c, id, fn) }) : n));
	function remove(list, id) {
		let removed = null;
		const walk = (l) => l.filter((n) => (n.id === id ? ((removed = n), false) : true)).map((n) => (n.c && n.c.length ? Object.assign({}, n, { c: walk(n.c) }) : n));
		return [walk(list), removed];
	}
	function insert(list, target, pos, item) {
		if (!target) return list.concat([item]);
		if (pos === 'inside') return update(list, target, (n) => Object.assign({}, n, { c: (n.c || []).concat([item]) }));
		const walk = (l) => {
			const i = l.findIndex((n) => n.id === target);
			if (i !== -1) {
				const copy = l.slice();
				copy.splice(pos === 'before' ? i : i + 1, 0, item);
				return copy;
			}
			return l.map((n) => (n.c && n.c.length ? Object.assign({}, n, { c: walk(n.c) }) : n));
		};
		return walk(list);
	}
	const clone = (n) => Object.assign({}, n, { id: uid(), s: JSON.parse(JSON.stringify(n.s || {})), c: (n.c || []).map(clone) });
	function move(list, id, dir) {
		const walk = (l) => {
			const i = l.findIndex((n) => n.id === id);
			if (i !== -1) {
				const j = i + dir;
				if (j < 0 || j >= l.length) return l;
				const copy = l.slice();
				[copy[i], copy[j]] = [copy[j], copy[i]];
				return copy;
			}
			return l.map((n) => (n.c && n.c.length ? Object.assign({}, n, { c: walk(n.c) }) : n));
		};
		return walk(list);
	}

	// ------------------------------------------------------------ controles
	const DEV_ICON = { d: 'desktop', t: 'tablet', m: 'mobile' };
	const DEV_NAME = { d: 'Escritorio', t: 'Tablet', m: 'Móvil' };
	const UNITS = ['px', '%', 'em', 'rem', 'vh', 'vw'];

	function SizeInput({ id, value, placeholder, onChange }) {
		const m = /^(-?\d*\.?\d+)([a-z%]*)$/.exec(value || '') || [];
		const pm = /^(-?\d*\.?\d+)([a-z%]*)$/.exec(placeholder || '') || [];
		const unit = m[2] || pm[2] || 'px';
		return el('div', { className: 'odb-size' },
			el('input', { id, type: 'number', step: 'any', value: m[1] || '', placeholder: pm[1] || '', onChange: (e) => onChange(e.target.value === '' ? '' : e.target.value + unit) }),
			el('select', { 'aria-label': 'Unidad', value: unit, onChange: (e) => m[1] && onChange(m[1] + e.target.value) }, UNITS.map((u) => el('option', { key: u, value: u }, u))),
			value && el('button', { type: 'button', className: 'odb-clear', 'aria-label': 'Quitar valor', title: 'Quitar valor', onClick: () => onChange('') }, el(Icon, { n: 'close', s: 14 })));
	}

	function BoxInput({ label, value, placeholder, onChange, min }) {
		const parse = (v) => {
			const p = (v || '').trim().split(/\s+/).filter(Boolean);
			if (!p.length) return ['', '', '', ''];
			return [p[0], p[1] || p[0], p[2] || p[0], p[3] || p[1] || p[0]];
		};
		const vals = parse(value), ph = parse(placeholder);
		const [linked, setLinked] = useState(new Set(vals).size <= 1);
		const unitOf = (v) => (/[a-z%]+$/.exec(v || '') || ['px'])[0];
		const num = (v) => (v ? parseFloat(v) : '');
		const unit = unitOf(vals.find(Boolean) || ph.find(Boolean));
		const emit = (arr, u) => {
			const out = arr.map((x) => (x === '' ? '0' : x) + (x === '' || x === '0' ? (x === '' ? '' : u) : u));
			if (arr.every((x) => x === '')) return onChange('');
			onChange(new Set(out).size === 1 ? out[0] : out.join(' '));
		};
		const set = (i, x) => {
			const arr = vals.map(num).map(String).map((v) => (v === 'NaN' ? '' : v));
			if (linked) arr.fill(x); else arr[i] = x;
			emit(arr, unit);
		};
		return el('div', { className: 'odb-box', role: 'group', 'aria-label': label },
			['Arriba', 'Derecha', 'Abajo', 'Izq.'].map((lbl, i) => el('label', { key: i },
				el('input', { type: 'number', step: 'any', min, value: num(vals[i]), placeholder: ph[i] ? parseFloat(ph[i]) : '', onChange: (e) => set(i, min === 0 && parseFloat(e.target.value) < 0 ? '0' : e.target.value) }),
				el('span', null, lbl))),
			el('button', { type: 'button', className: 'odb-link' + (linked ? ' is-on' : ''), 'aria-pressed': linked, 'aria-label': 'Vincular los 4 lados', title: 'Vincular los 4 lados', onClick: () => setLinked(!linked) }, el(Icon, { n: 'link', s: 15 })),
			el('select', { 'aria-label': 'Unidad', value: unit, onChange: (e) => emit(vals.map(num).map((v) => (isNaN(v) || v === '' ? '' : String(v))), e.target.value) }, UNITS.slice(0, 5).map((u) => el('option', { key: u, value: u }, u))));
	}

	function ColorInput({ id, value, placeholder, onChange }) {
		const hex = /^#[0-9a-f]{6}$/i.test(value || '') ? value : /^#[0-9a-f]{6}$/i.test(placeholder || '') ? placeholder : '#000000';
		const globals = cfg.globalColors || [];
		return el('div', { className: 'odb-colorwrap' }, el('div', { className: 'odb-color' },
			el('input', { type: 'color', 'aria-label': 'Selector de color', value: hex, onChange: (e) => onChange(e.target.value) }),
			el('input', { id, type: 'text', value: value || '', placeholder: placeholder || '#hex, rgba(…)', onChange: (e) => onChange(e.target.value) }),
			value && el('button', { type: 'button', className: 'odb-clear', 'aria-label': 'Quitar valor', title: 'Quitar valor', onClick: () => onChange('') }, el(Icon, { n: 'close', s: 14 }))),
			globals.length > 0 && el('div', { className: 'odb-globals', role: 'group', 'aria-label': 'Colores globales' }, globals.map((g) => el('button', {
				key: g.var, type: 'button', title: g.label + ' (global)', 'aria-label': 'Color global: ' + g.label, 'aria-pressed': value === g.var,
				className: value === g.var ? 'is-active' : '', style: { background: g.value }, onClick: () => onChange(g.var),
			}))));
	}

	function pickImage(cb) {
		const frame = wp.media({ title: 'Elegir imagen', library: { type: 'image' }, multiple: false, button: { text: 'Usar imagen' } });
		frame.on('select', () => cb(frame.state().get('selection').first().toJSON()));
		frame.open();
	}

	const GRADIENTS = ['linear-gradient(180deg,rgba(0,0,0,0) 0%,rgba(0,0,0,.7) 100%)', 'linear-gradient(135deg,#667eea 0%,#764ba2 100%)', 'linear-gradient(135deg,#f093fb 0%,#f5576c 100%)', 'linear-gradient(135deg,#43e97b 0%,#38f9d7 100%)', 'linear-gradient(90deg,#111 0%,#444 100%)'];

	const iconSvg = (n, size) => el('svg', { viewBox: '0 0 24 24', width: size || 20, height: size || 20, fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true, dangerouslySetInnerHTML: { __html: (cfg.icons || {})[n] || '' } });

	function IconPicker({ value, onChange }) {
		const [open, setOpen] = useState(false);
		return el('div', { className: 'odb-iconpick' },
			el('button', { type: 'button', className: 'odb-iconpick__current', 'aria-expanded': open, onClick: () => setOpen(!open) }, iconSvg(value || 'star'), el('span', null, value || 'star'), el(Icon, { n: open ? 'up' : 'down', s: 14 })),
			open && el('div', { className: 'odb-iconpick__grid', role: 'listbox', 'aria-label': 'Iconos' }, Object.keys(cfg.icons || {}).map((n) => el('button', {
				key: n, type: 'button', role: 'option', 'aria-selected': n === value, 'aria-label': n, title: n, className: n === value ? 'is-active' : '',
				onClick: () => { onChange(n); setOpen(false); },
			}, iconSvg(n)))));
	}

	function itemControl(kind, value, onChange, list) {
		switch (kind) {
			case 'icon': return el(IconPicker, { value, onChange });
			case 'select': return el('select', { value: value || '', onChange: (e) => onChange(e.target.value) }, opts(list).slice(1).map((o) => el('option', { key: o.value, value: o.value }, o.label)));
			case 'bool': return el('input', { type: 'checkbox', checked: !!value, onChange: (e) => onChange(e.target.checked) });
			case 'int': return el('input', { type: 'number', value: value === undefined ? '' : value, onChange: (e) => onChange(e.target.value === '' ? '' : parseInt(e.target.value, 10)) });
			case 'bgimage': return el('div', { className: 'odb-img' }, value && el('img', { src: value, alt: '' }),
				el('button', { type: 'button', className: 'button', onClick: () => pickImage((a) => onChange(a.url)) }, value ? 'Cambiar' : 'Elegir imagen'),
				el('input', { type: 'url', value: value || '', placeholder: 'o pega una URL', onChange: (e) => onChange(e.target.value) }));
			case 'rich': case 'textarea': return el('textarea', { rows: kind === 'rich' ? 4 : 3, value: value || '', onChange: (e) => onChange(e.target.value) });
			default: return el('input', { type: kind === 'url' ? 'url' : 'text', value: value || '', onChange: (e) => onChange(e.target.value) });
		}
	}

	function Repeater({ value, fields, blank, onChange }) {
		const items = Array.isArray(value) ? value : [];
		const [open, setOpen] = useState(-1);
		const set = (i, k, v) => onChange(items.map((it, j) => (j === i ? Object.assign({}, it, { [k]: v }) : it)));
		const mv = (i, d) => { const a = items.slice(); const j = i + d; if (j < 0 || j >= a.length) return; [a[i], a[j]] = [a[j], a[i]]; onChange(a); };
		return el('div', { className: 'odb-rep' },
			items.map((it, i) => el('div', { key: i, className: 'odb-rep__item' + (open === i ? ' is-open' : '') },
				el('div', { className: 'odb-rep__head' },
					el('button', { type: 'button', className: 'odb-rep__title', 'aria-expanded': open === i, onClick: () => setOpen(open === i ? -1 : i) },
						it.icon ? iconSvg(it.icon, 16) : null, el('span', null, it.title || it.label || it.text || L[it.network] || '#' + (i + 1))),
					el('button', { type: 'button', 'aria-label': 'Subir', title: 'Subir', onClick: () => mv(i, -1) }, el(Icon, { n: 'up', s: 14 })),
					el('button', { type: 'button', 'aria-label': 'Bajar', title: 'Bajar', onClick: () => mv(i, 1) }, el(Icon, { n: 'down', s: 14 })),
					el('button', { type: 'button', className: 'is-danger', 'aria-label': 'Eliminar', title: 'Eliminar', onClick: () => onChange(items.filter((_, j) => j !== i)) }, el(Icon, { n: 'trash', s: 14 }))),
				open === i && el('div', { className: 'odb-rep__body' }, fields.map(([k, kind, label, list]) =>
					el('label', { key: k, className: 'odb-rep__field' + (kind === 'bool' ? ' is-inline' : '') }, el('span', null, label), itemControl(kind, it[k], (v) => set(i, k, v), list)))))),
			el('button', { type: 'button', className: 'odb-add', onClick: () => { onChange(items.concat([Object.assign({}, blank)])); setOpen(items.length); } }, el(Icon, { n: 'plus', s: 14 }), 'Añadir'));
	}

	function GalleryInput({ value, onChange }) {
		const imgs = Array.isArray(value) ? value : [];
		function add() {
			const frame = wp.media({ title: 'Añadir imágenes', library: { type: 'image' }, multiple: true, button: { text: 'Añadir a la galería' } });
			frame.on('select', () => onChange(imgs.concat(frame.state().get('selection').toJSON().map((a) => ({ src: a.url, imageId: a.id, alt: a.alt || '' })))));
			frame.open();
		}
		return el('div', { className: 'odb-gal' },
			el('div', { className: 'odb-gal__grid' }, imgs.map((im, i) => el('div', { key: i, className: 'odb-gal__item' },
				el('img', { src: im.src, alt: '' }),
				el('button', { type: 'button', 'aria-label': 'Quitar imagen ' + (i + 1), onClick: () => onChange(imgs.filter((_, j) => j !== i)) }, el(Icon, { n: 'close', s: 12 }))))),
			el('button', { type: 'button', className: 'odb-add', onClick: add }, el(Icon, { n: 'plus', s: 14 }), 'Añadir imágenes'));
	}

	let menuCache = null;
	function MenuPicker({ id, value, onChange }) {
		const [list, setList] = useState(menuCache);
		useEffect(() => { if (!menuCache) apiFetch({ path: '/odin/v1/menus' }).then((r) => { menuCache = r; setList(r); }).catch(() => setList([])); }, []);
		return el('div', null,
			el('select', { id, value: value || '', onChange: (e) => onChange(e.target.value ? parseInt(e.target.value, 10) : '') },
				el('option', { value: '' }, list ? '— Elige un menú —' : 'Cargando…'), (list || []).map((m) => el('option', { key: m.id, value: m.id }, m.title))),
			value && el('a', { className: 'odb-tpl__links', href: cfg.menusUrl + '?action=edit&menu=' + value, target: '_blank', rel: 'noopener', style: { display: 'inline-flex', gap: '4px', marginTop: '6px' } }, el(Icon, { n: 'external', s: 13 }), 'Editar este menú (enlaces y orden)'),
			el('p', { className: 'odb-help' }, 'Los enlaces se editan en Odin → Menús (o Apariencia → Menús). Los elementos con subelementos se muestran como desplegables. Al volver, recarga el editor para ver los cambios.'));
	}

	let tplCache = null;
	function TemplatePicker({ id, value, onChange }) {
		const [list, setList] = useState(tplCache);
		useEffect(() => { if (!tplCache) apiFetch({ path: '/odin/v1/templates' }).then((r) => { tplCache = r; setList(r); }).catch(() => setList([])); }, []);
		const cur = (list || []).find((t) => t.id === value);
		return el('div', { className: 'odb-tpl' },
			el('select', { id, value: value || '', onChange: (e) => onChange(e.target.value ? parseInt(e.target.value, 10) : '') },
				el('option', { value: '' }, list ? '— Elige una plantilla —' : 'Cargando…'),
				(list || []).filter((t) => t.id !== cfg.postId * 1).map((t) => el('option', { key: t.id, value: t.id }, t.title + ' (' + ({ section: 'sección', header: 'cabecera', footer: 'pie', 'single-product': 'producto' }[t.type] || t.type) + ')'))),
			el('div', { className: 'odb-tpl__links' },
				cur && el('a', { href: cur.edit, target: '_blank', rel: 'noopener' }, el(Icon, { n: 'external', s: 13 }), 'Editar plantilla'),
				el('a', { href: cfg.newTemplateUrl, target: '_blank', rel: 'noopener' }, el(Icon, { n: 'plus', s: 13 }), 'Nueva plantilla')),
			el('p', { className: 'odb-help' }, 'Al editar la plantilla original se actualiza en todas las páginas donde la uses. También puedes usar el shortcode [odin_template id="…"].'));
	}

	function Field({ f, s, dev, setS, setDev, type, ctx }) {
		const [k, kind, label, list, show] = f;
		if (typeof show === 'function' && !show(s, dev)) return null;
		const resp = RESP.has(k);
		const v = val(s, k, dev);
		const ph = inherited(s, k, dev);
		const set = (x) => setS(withVal(s, k, dev, x));
		const id = 'odb-f-' + k;
		let control;
		switch (kind) {
			case 'icon': control = el(IconPicker, { value: v, onChange: set }); break;
			case 'email': control = el('input', { id, type: 'email', value: v || '', onChange: (e) => set(e.target.value) }); break;
			case 'template': control = el(TemplatePicker, { id, value: v, onChange: set }); break;
			case 'mock': control = el('select', { id, value: v || '', onChange: (e) => set(e.target.value) }, el('option', { value: '' }, 'Sin mockup'), Object.keys(cfg.mocks || {}).map((k) => el('option', { key: k, value: k }, cfg.mocks[k]))); break;
			case 'menu': control = el(MenuPicker, { id, value: v, onChange: set }); break;
			case 'video':
				control = el('div', { className: 'odb-img' },
					v && el('video', { src: v, muted: true, style: { width: '100%', maxHeight: '160px', borderRadius: '6px', background: '#000' } }),
					el('button', { type: 'button', className: 'button', onClick: () => { const f = wp.media({ title: 'Elegir vídeo', library: { type: 'video' }, multiple: false }); f.on('select', () => set(f.state().get('selection').first().toJSON().url)); f.open(); } }, v ? 'Cambiar vídeo' : 'Elegir vídeo'),
					el('input', { type: 'url', value: v || '', placeholder: 'o pega una URL .mp4', onChange: (e) => set(e.target.value) }));
				break;
			case 'repeater': control = el(Repeater, { value: v, fields: list, blank: f[4] || {}, onChange: set }); break;
			case 'gallery': control = el(GalleryInput, { value: v, onChange: set }); break;
			case 'children':
				control = el('div', { className: 'odb-children' },
					el('span', null, (ctx.node.c || []).length + ' elemento(s)'),
					el('button', { type: 'button', className: 'odb-add', onClick: ctx.addChild }, el(Icon, { n: 'plus', s: 14 }), 'Columna'),
					el('button', { type: 'button', className: 'odb-add', disabled: !(ctx.node.c || []).length, onClick: ctx.removeChild }, el(Icon, { n: 'minus', s: 14 }), 'Columna'));
				break;
			case 'select':
				control = el('select', { id, value: v || '', onChange: (e) => set(e.target.value) }, opts(list).map((o) => el('option', { key: o.value, value: o.value }, o.value === '' && ph ? '↳ ' + (L[ph] || ph) : o.label)));
				break;
			case 'size': control = el(SizeInput, { id, value: v, placeholder: ph, onChange: set }); break;
			case 'box': control = el(BoxInput, { key: dev + k, label, min: k === 'margin' ? undefined : 0, value: v, placeholder: ph, onChange: set }); break;
			case 'color': control = el(ColorInput, { id, value: v, placeholder: ph, onChange: set }); break;
			case 'gradient':
				control = el('div', { className: 'odb-grad' },
					el('div', { className: 'odb-grad__presets' }, GRADIENTS.map((g, i) => el('button', { key: g, type: 'button', style: { background: g }, 'aria-label': 'Degradado ' + (i + 1), title: g, onClick: () => set(g) }))),
					el('input', { id, type: 'text', value: v || '', placeholder: ph || 'linear-gradient(…)', onChange: (e) => set(e.target.value) }),
					v && el('button', { type: 'button', className: 'odb-clear', 'aria-label': 'Quitar degradado', onClick: () => set('') }, el(Icon, { n: 'close', s: 14 })));
				break;
			case 'bgimage':
				control = el('div', { className: 'odb-img' },
					(v || ph) && el('img', { src: v || ph, alt: '' }),
					el('button', { className: 'button', onClick: () => pickImage((a) => set(a.url)) }, v ? 'Cambiar' : 'Elegir imagen'),
					v && el('button', { className: 'button-link', onClick: () => set('') }, 'Quitar'));
				break;
			case 'image':
				control = el('div', { className: 'odb-img' },
					s.src && el('img', { src: s.src, alt: '' }),
					el('button', { className: 'button', onClick: () => pickImage((a) => setS(Object.assign({}, s, { src: a.url, imageId: a.id, alt: s.alt || a.alt || '' }))) }, s.src ? 'Cambiar imagen' : 'Elegir de la biblioteca'),
					el('input', { type: 'url', value: s.src || '', placeholder: 'o pega una URL', onChange: (e) => { const ns = withVal(s, 'src', dev, e.target.value); delete ns.imageId; setS(ns); } }));
				break;
			case 'bool': control = el('input', { id, type: 'checkbox', checked: !!v, onChange: (e) => set(e.target.checked) }); break;
			case 'int': control = el('input', { id, type: 'number', value: v === undefined ? '' : v, placeholder: ph === undefined ? '' : ph, onChange: (e) => set(e.target.value === '' ? '' : parseInt(e.target.value, 10)) }); break;
			case 'textarea': control = el('textarea', { id, rows: 2, value: v || '', onChange: (e) => set(e.target.value) }); break;
			case 'rich':
			case 'code': control = el('textarea', { id, rows: kind === 'code' ? 12 : 8, className: kind === 'code' ? 'is-code' : '', value: v || '', onChange: (e) => set(e.target.value) }); break;
			case 'devices':
				control = el('div', { className: 'odb-devs' }, [['d', 'Escritorio'], ['t', 'Tablet'], ['m', 'Móvil']].map(([d, lbl]) => el('label', { key: d },
					el('input', { type: 'checkbox', checked: (v || []).includes(d), onChange: (e) => set(e.target.checked ? (v || []).concat([d]) : (v || []).filter((x) => x !== d)) }), ' ' + lbl)));
				break;
			default: control = el('input', { id, type: kind === 'url' ? 'url' : 'text', value: v || '', placeholder: ph || '', onChange: (e) => set(e.target.value) });
		}
		return el('div', { className: 'odb-field' + (kind === 'bool' ? ' is-inline' : '') },
			el('div', { className: 'odb-field__label' },
				el(['box', 'devices', 'image', 'bgimage', 'icon', 'repeater', 'gallery', 'children', 'video'].includes(kind) ? 'span' : 'label', { htmlFor: id }, label),
				resp && el('button', { type: 'button', className: 'odb-dev' + (dev !== 'd' ? ' is-' + dev : ''), 'aria-label': 'Editando valor de ' + DEV_NAME[dev] + '. Cambiar dispositivo', title: 'Valor para ' + DEV_NAME[dev] + ' (clic para cambiar)', onClick: () => setDev(dev === 'd' ? 't' : dev === 't' ? 'm' : 'd') }, el(Icon, { n: DEV_ICON[dev], s: 14 }))),
			control);
	}

	function Sections({ sections, n, dev, setS, setDev, ctx }) {
		return (sections || []).filter((sec) => !sec.when || sec.when(n.type)).map((sec, i) => el(C.PanelBody, { key: sec.title, title: sec.title, initialOpen: i === 0 },
			sec.f.map((f) => el(Field, { key: f[0], f, s: n.s, dev, setS, setDev, type: n.type, ctx }))));
	}

	// ------------------------------------------------------------ app
	function App() {
		const [tree, setTreeRaw] = useState(null);
		const [meta, setMeta] = useState({});
		const [sel, setSel] = useState(null);
		const [dev, setDev] = useState('d');
		const [panel, setPanel] = useState('widgets');
		const [tab, setTab] = useState('content');
		const [dirty, setDirty] = useState(false);
		const [msg, setMsg] = useState('');
		const [pageCfg, setPageCfg] = useState({});
		const [tplCfg, setTplCfg] = useState(null);
		const [, force] = useState(0);
		const hist = useRef({ past: [], future: [] });
		const frame = useRef(null);
		const ready = useRef(false);
		const seq = useRef(0);
		const treeRef = useRef(tree);
		treeRef.current = tree;
		const selRef = useRef(sel);
		selRef.current = sel;

		const post = (m) => frame.current && frame.current.contentWindow && frame.current.contentWindow.postMessage(Object.assign({ source: 'odin-editor' }, m), location.origin);

		function setTree(next) {
			hist.current.past.push(treeRef.current);
			if (hist.current.past.length > 100) hist.current.past.shift();
			hist.current.future = [];
			setTreeRaw(next);
			setDirty(true);
		}
		function undo() {
			const h = hist.current;
			if (!h.past.length) return;
			h.future.push(treeRef.current);
			setTreeRaw(h.past.pop());
			setDirty(true);
			force((x) => x + 1);
		}
		function redo() {
			const h = hist.current;
			if (!h.future.length) return;
			h.past.push(treeRef.current);
			setTreeRaw(h.future.pop());
			setDirty(true);
			force((x) => x + 1);
		}

		// acciones sobre el árbol
		function add(widgetOrNode, target, pos) {
			const item = typeof widgetOrNode === 'string' ? node(widgetOrNode) : widgetOrNode;
			const t = treeRef.current;
			if (target === undefined) {
				// clic en un widget: dentro del contenedor seleccionado, después del elemento seleccionado o al final
				const cur = selRef.current && find(t, selRef.current);
				target = cur ? cur.id : null;
				pos = cur ? (cur.type === 'container' ? 'inside' : 'after') : 'inside';
			}
			setTree(insert(t, target, pos, item));
			setSel(item.id);
			setPanel('settings');
			setTab('content');
		}
		function del(id) {
			setTree(remove(treeRef.current, id)[0]);
			if (selRef.current === id) { setSel(null); setPanel('widgets'); }
		}
		function dup(id) {
			const n = find(treeRef.current, id);
			if (!n) return;
			const c = clone(n);
			setTree(insert(treeRef.current, id, 'after', c));
			setSel(c.id);
		}
		function moveTo(id, target, pos) {
			if (id === target) return;
			const [rest, n] = remove(treeRef.current, id);
			if (n) setTree(insert(rest, target, pos, n));
		}

		// carga
		useEffect(() => {
			apiFetch({ path: '/odin/v1/builder/' + cfg.postId }).then((r) => { setTreeRaw(r.tree || []); setMeta(r); setPageCfg(r.page || {}); setTplCfg(r.template); }).catch((e) => setMsg('Error al cargar: ' + e.message));
		}, []);

		// vista previa (renderizada por el servidor) con debounce
		function renderCanvas() {
			if (!ready.current || !treeRef.current) return;
			const n = ++seq.current;
			apiFetch({ path: '/odin/v1/render/' + cfg.postId, method: 'POST', data: { tree: treeRef.current } })
				.then((r) => { if (n === seq.current) post({ type: 'render', html: r.html, css: r.css, selected: selRef.current }); })
				.catch((e) => setMsg('Vista previa: ' + e.message));
		}
		useEffect(() => {
			const t = setTimeout(renderCanvas, 180);
			return () => clearTimeout(t);
		}, [tree]);
		useEffect(() => { post({ type: 'select', id: sel, scroll: true }); }, [sel]);

		// mensajes del lienzo
		useEffect(() => {
			function onMsg(e) {
				if (e.origin !== location.origin || !e.data || e.data.source !== 'odin-canvas') return;
				const m = e.data;
				if (m.type === 'ready') { ready.current = true; renderCanvas(); }
				else if (m.type === 'select') { setSel(m.id); setPanel('settings'); }
				else if (m.type === 'add' && WIDGETS[m.widget]) add(m.widget, m.target, m.pos);
				else if (m.type === 'add' && m.widget && m.widget.indexOf('preset:') === 0) add(PRESETS[+m.widget.slice(7)].make(), m.target, m.pos);
				else if (m.type === 'move') moveTo(m.id, m.target, m.pos);
				else if (m.type === 'dup') dup(m.id);
				else if (m.type === 'del') del(m.id);
			}
			addEventListener('message', onMsg);
			return () => removeEventListener('message', onMsg);
		}, []);

		// atajos y aviso al salir
		useEffect(() => {
			function onKey(e) {
				const typing = /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName);
				const mod = e.ctrlKey || e.metaKey;
				if (mod && e.key.toLowerCase() === 's') { e.preventDefault(); save(); }
				else if (mod && e.key.toLowerCase() === 'z' && !typing) { e.preventDefault(); e.shiftKey ? redo() : undo(); }
				else if (mod && e.key.toLowerCase() === 'y' && !typing) { e.preventDefault(); redo(); }
				else if ((e.key === 'Delete' || e.key === 'Backspace') && !typing && selRef.current) { e.preventDefault(); del(selRef.current); }
				else if (e.key === 'Escape' && !typing) { setSel(null); setPanel('widgets'); }
			}
			function onLeave(e) { if (dirtyRef.current) { e.preventDefault(); e.returnValue = ''; } }
			addEventListener('keydown', onKey);
			addEventListener('beforeunload', onLeave);
			return () => { removeEventListener('keydown', onKey); removeEventListener('beforeunload', onLeave); };
		}, []);
		const dirtyRef = useRef(dirty);
		dirtyRef.current = dirty;
		const pageRef = useRef(pageCfg);
		pageRef.current = pageCfg;
		const tplRef = useRef(tplCfg);
		tplRef.current = tplCfg;

		function makeGlobal() {
			const n = find(treeRef.current, selRef.current);
			if (!n) return;
			const title = window.prompt('Nombre de la plantilla global (podrás usarla en otras páginas):', WIDGETS[n.type].label + ' global');
			if (!title) return;
			setMsg('Creando plantilla…');
			apiFetch({ path: '/odin/v1/templates', method: 'POST', data: { title, tree: [n] } }).then((r) => {
				tplCache = null;
				const ref = node('template', { templateId: r.id });
				setTree(update(treeRef.current, n.id, () => ref));
				setSel(ref.id);
				setMsg('Plantilla global creada ✓');
			}).catch((e) => setMsg('Error: ' + e.message));
		}

		function save(status) {
			setMsg('Guardando…');
			return apiFetch({ path: '/odin/v1/builder/' + cfg.postId, method: 'POST', data: { tree: treeRef.current, status: status || '', page: pageRef.current, template: tplRef.current } })
				.then((r) => { setDirty(false); setMeta(Object.assign({}, meta, r)); setMsg(status === 'publish' ? 'Publicado ✓' : 'Guardado ✓'); setTimeout(() => setMsg(''), 2500); })
				.catch((e) => setMsg('Error al guardar: ' + e.message));
		}

		if (!tree) return el('div', { className: 'odb-loading' }, msg || 'Cargando Odin Builder…');

		const cur = sel && find(tree, sel);
		const setS = (s) => setTree(update(tree, sel, (n) => Object.assign({}, n, { s })));
		const widths = { d: '100%', t: '768px', m: '390px' };
		const parent = cur ? parentOf(tree, cur.id) : null;

		// --- panel izquierdo
		let side;
		if (panel === 'settings' && cur) {
			side = el(Fragment, null,
				el('div', { className: 'odb-side__head' },
					el('button', { type: 'button', className: 'odb-back', onClick: () => { setSel(null); setPanel('widgets'); } }, el(Icon, { n: 'back', s: 16 }), 'Widgets'),
					el('strong', null, el(Icon, { n: WIDGETS[cur.type].icon, s: 16 }), WIDGETS[cur.type].label),
					cur.type !== 'template' && !cur.type.startsWith('wc-') && el('button', { type: 'button', className: 'odb-parent', title: 'Convertir en plantilla global reutilizable en otras páginas', onClick: makeGlobal }, el(Icon, { n: 'globe', s: 14 }), 'Global'),
					parent && el('button', { type: 'button', className: 'odb-parent', title: 'Seleccionar el contenedor padre', onClick: () => setSel(parent.id) }, el(Icon, { n: 'up', s: 14 }), 'Padre')),
				el('div', { className: 'odb-tabs', role: 'tablist', 'aria-label': 'Ajustes del elemento' }, [['content', 'Contenido'], ['style', 'Estilo'], ['advanced', 'Avanzado']].map(([k, lbl]) => el('button', { key: k, type: 'button', role: 'tab', 'aria-selected': tab === k, className: tab === k ? 'is-active' : '', onClick: () => setTab(k) }, lbl))),
				el('div', { className: 'odb-side__body', role: 'tabpanel', key: cur.id + tab },
					el(Sections, {
						sections: tab === 'content' ? (CONTENT[cur.type] || [{ title: WIDGETS[cur.type].label, f: [] }]) : tab === 'style' ? STYLE : ADVANCED, n: cur, dev, setS, setDev,
						ctx: {
							node: cur,
							addChild: () => setTree(update(tree, cur.id, (x) => Object.assign({}, x, { c: (x.c || []).concat([node('container')]) }))),
							removeChild: () => setTree(update(tree, cur.id, (x) => Object.assign({}, x, { c: (x.c || []).slice(0, -1) }))),
						},
					})));
		} else if (panel === 'page') {
			const d = meta.defaults || {};
			const setP = (k, v) => { setPageCfg(Object.assign({}, pageCfg, { [k]: v })); setDirty(true); };
			const setT = (k, v) => { setTplCfg(Object.assign({}, tplCfg, { [k]: v })); setDirty(true); };
			const LAY = meta.layouts || { default: 'Del tema', full: 'Ancho completo', canvas: 'Lienzo (sin cabecera ni pie)' };
			const SCN = meta.scenes || {};
			side = el(Fragment, null,
				el('div', { className: 'odb-side__head' }, el('strong', null, el(Icon, { n: 'gear', s: 16 }), tplCfg ? 'Ajustes de la plantilla' : 'Ajustes de la página')),
				el('div', { className: 'odb-side__body odb-pad' }, tplCfg
					? el(Fragment, null,
						el('div', { className: 'odb-field' }, el('div', { className: 'odb-field__label' }, el('label', { htmlFor: 'odb-tpl-type' }, 'Tipo de plantilla')),
							el('select', { id: 'odb-tpl-type', value: tplCfg.type, onChange: (e) => setT('type', e.target.value) },
								[['section', 'Sección global (shortcode)'], ['header', 'Cabecera (toda la web)'], ['footer', 'Pie de página (toda la web)'], ['single-product', 'Producto único (WooCommerce)'], ['popup', 'Popup / mensaje emergente']].map(([v, l]) => el('option', { key: v, value: v }, l)))),
						tplCfg.type === 'popup' && (() => {
							const pp = tplCfg.popup || {};
							const setPP = (k, v) => setT('popup', Object.assign({}, pp, { [k]: v }));
							const num = (k, lbl, min, max) => el('div', { className: 'odb-field', key: k }, el('div', { className: 'odb-field__label' }, el('label', { htmlFor: 'odb-pp-' + k }, lbl)),
								el('input', { id: 'odb-pp-' + k, type: 'number', min, max, value: pp[k] === undefined ? '' : pp[k], onChange: (e) => setPP(k, parseInt(e.target.value || '0', 10)) }));
							return el('div', { className: 'odb-popupcfg' },
								el('div', { className: 'odb-field' }, el('div', { className: 'odb-field__label' }, el('label', { htmlFor: 'odb-pp-trigger' }, 'Se abre')),
									el('select', { id: 'odb-pp-trigger', value: pp.trigger || 'load', onChange: (e) => setPP('trigger', e.target.value) },
										[['load', 'Al cargar la página'], ['scroll', 'Al hacer scroll'], ['exit', 'Al intentar salir (escritorio)'], ['click', 'Solo con un enlace a #odin-popup-' + cfg.postId]].map(([v, l]) => el('option', { key: v, value: v }, l)))),
								(pp.trigger || 'load') === 'load' && num('delay', 'Retraso (segundos)', 0, 120),
								pp.trigger === 'scroll' && num('scroll', 'Al llegar al % de la página', 1, 100),
								el('div', { className: 'odb-field' }, el('div', { className: 'odb-field__label' }, el('label', { htmlFor: 'odb-pp-freq' }, 'Frecuencia')),
									el('select', { id: 'odb-pp-freq', value: pp.frequency || 'session', onChange: (e) => setPP('frequency', e.target.value) },
										[['always', 'Siempre'], ['session', 'Una vez por visita'], ['days', 'Una vez cada X días']].map(([v, l]) => el('option', { key: v, value: v }, l)))),
								pp.frequency === 'days' && num('days', 'Días', 1, 365),
								num('width', 'Ancho máximo (px)', 240, 1400),
								el('p', { className: 'odb-help' }, 'Cualquier botón o enlace a #odin-popup-' + cfg.postId + ' también lo abre.'));
						})(),
						tplCfg.type !== 'section' && el('div', { className: 'odb-field is-inline' }, el('div', { className: 'odb-field__label' }, el('label', { htmlFor: 'odb-tpl-active' }, 'Activa en toda la web')),
							el('input', { id: 'odb-tpl-active', type: 'checkbox', checked: !!tplCfg.active, onChange: (e) => setT('active', e.target.checked) })),
						el('p', { className: 'odb-help' }, tplCfg.type === 'section' ? 'Insértala en cualquier página con el widget «Plantilla global» o con el shortcode [odin_template id="' + cfg.postId + '"].' : tplCfg.type === 'single-product' ? 'Se usa en todos los productos. Añade los widgets del grupo WooCommerce (título, precio, imágenes, carrito…).' : 'Se aplica automáticamente en todas las páginas, también en las nuevas. Guarda para aplicar los cambios.'))
					: el(Fragment, null,
						el('div', { className: 'odb-field' }, el('div', { className: 'odb-field__label' }, el('label', { htmlFor: 'odb-pg-layout' }, 'Diseño de página')),
							el('select', { id: 'odb-pg-layout', value: pageCfg.layout || '', onChange: (e) => setP('layout', e.target.value) },
								el('option', { value: '' }, 'Por defecto (' + (LAY[d.layout] || 'Del tema') + ')'), Object.keys(LAY).map((k) => el('option', { key: k, value: k }, LAY[k])))),
						el('div', { className: 'odb-field' }, el('div', { className: 'odb-field__label' }, el('label', { htmlFor: 'odb-pg-title' }, 'Título del tema')),
							el('select', { id: 'odb-pg-title', value: pageCfg.hideTitle || '', onChange: (e) => setP('hideTitle', e.target.value) },
								el('option', { value: '' }, 'Por defecto (' + (d.hideTitle ? 'oculto' : 'visible') + ')'), el('option', { value: '1' }, 'Ocultar'), el('option', { value: '0' }, 'Mostrar'))),
						el('div', { className: 'odb-field' }, el('div', { className: 'odb-field__label' }, el('label', { htmlFor: 'odb-pg-scene' }, 'Fondo 3D')),
							el('select', { id: 'odb-pg-scene', value: pageCfg.scene || '', onChange: (e) => setP('scene', e.target.value) },
								el('option', { value: '' }, 'Por defecto (' + (SCN[d.scene] || '—') + ')'), Object.keys(SCN).map((k) => el('option', { key: k, value: k }, SCN[k])))),
						el('div', { className: 'odb-field' }, el('div', { className: 'odb-field__label' }, el('label', { htmlFor: 'odb-f-pagebg' }, 'Color de fondo de la página')),
							el(ColorInput, { id: 'odb-f-pagebg', value: pageCfg.bg || '', placeholder: d.bg || '', onChange: (v) => setP('bg', v) })),
						el('p', { className: 'odb-help' }, 'Los valores «Por defecto» se cambian para todas las páginas en Odin → Ajustes. La vista previa del título y el diseño se ve al pulsar «Ver».'))));
		} else if (panel === 'nav') {
			const item = (n, depth) => el(Fragment, { key: n.id },
				el('div', { className: 'odb-nav__item' + (n.id === sel ? ' is-active' : ''), style: { paddingLeft: 10 + depth * 16 + 'px' } },
					el('button', { type: 'button', className: 'odb-nav__name', 'aria-current': n.id === sel ? 'true' : undefined, onClick: () => setSel(n.id) }, el(Icon, { n: WIDGETS[n.type].icon, s: 15 }), el('span', null, n.s.text || n.s.cssId || WIDGETS[n.type].label)),
					el('span', { className: 'odb-nav__acts' },
						[['up', 'Subir', () => setTree(move(tree, n.id, -1))], ['down', 'Bajar', () => setTree(move(tree, n.id, 1))], ['copy', 'Duplicar', () => dup(n.id)], ['trash', 'Eliminar', () => del(n.id)]].map(([ic, t, fn]) =>
							el('button', { key: ic, type: 'button', 'aria-label': t + ' ' + WIDGETS[n.type].label, title: t, className: ic === 'trash' ? 'is-danger' : '', onClick: fn }, el(Icon, { n: ic, s: 14 }))))),
				(n.c || []).map((ch) => item(ch, depth + 1)));
			side = el(Fragment, null, el('div', { className: 'odb-side__head' }, el('strong', null, 'Estructura')),
				el('div', { className: 'odb-side__body odb-nav' }, tree.length ? tree.map((n) => item(n, 0)) : el('p', { className: 'odb-empty' }, 'La página está vacía. Añade un widget desde el panel Widgets.')));
		} else {
			const tile = (key, label, icon, onClick) => el('button', {
				key, type: 'button', className: 'odb-tile', draggable: true, onClick,
				onDragStart: (e) => { e.dataTransfer.setData('text/plain', key); e.dataTransfer.effectAllowed = 'copy'; post({ type: 'dragType', widget: key }); },
				onDragEnd: () => post({ type: 'dragType', widget: null }),
			}, el(Icon, { n: icon, s: 22 }), el('span', null, label));
			side = el(Fragment, null,
				el('div', { className: 'odb-side__head' }, el('strong', null, 'Widgets'), el('span', { className: 'odb-muted' }, 'Arrastra o haz clic')),
				el('div', { className: 'odb-side__body' },
					el('h4', null, 'Estructura'),
					el('div', { className: 'odb-tiles' }, tile('container', 'Contenedor', 'container', () => add('container')), PRESETS.map((p, i) => tile('preset:' + i, p.label, p.icon, () => add(p.make())))),
					[['basic', 'Básicos'], ['general', 'Generales'], ['site', 'Sitio'], ['global', 'Global'], ['woo', 'WooCommerce · producto actual']].map(([g, title]) => {
						if (g === 'woo' && !(cfg.hasWoo && tplCfg && tplCfg.type === 'single-product')) return null;
						const keys = Object.keys(WIDGETS).filter((k) => k !== 'container' && (WIDGETS[k].group || 'basic') === g && (!('only' in WIDGETS[k]) || !!WIDGETS[k].only));
						return el(Fragment, { key: g }, el('h4', null, title), el('div', { className: 'odb-tiles' }, keys.map((k) => tile(k, WIDGETS[k].label, WIDGETS[k].icon, () => add(k)))));
					})));
		}

		return el('div', { className: 'odb' },
			el('header', { className: 'odb-top' },
				el('a', { className: 'odb-icon-btn', href: cfg.listUrl, 'aria-label': 'Salir del editor', title: 'Salir' }, el(Icon, { n: 'close' })),
				el('span', { className: 'odb-brand' }, 'Odin'),
				el('span', { className: 'odb-title' }, meta.title || '(sin título)', meta.status && meta.status !== 'publish' ? el('span', { className: 'odb-badge' }, 'Borrador') : null),
				el('div', { className: 'odb-devices', role: 'group', 'aria-label': 'Vista previa por dispositivo' }, ['d', 't', 'm'].map((d) => el('button', { key: d, type: 'button', className: 'odb-icon-btn' + (dev === d ? ' is-active' : ''), 'aria-pressed': dev === d, 'aria-label': DEV_NAME[d], title: DEV_NAME[d], onClick: () => setDev(d) }, el(Icon, { n: DEV_ICON[d] })))),
				el('div', { className: 'odb-actions' },
					el('span', { className: 'odb-msg', role: 'status', 'aria-live': 'polite' }, msg),
					el('button', { type: 'button', className: 'odb-icon-btn', 'aria-label': 'Deshacer', title: 'Deshacer (Ctrl+Z)', disabled: !hist.current.past.length, onClick: undo }, el(Icon, { n: 'undo' })),
					el('button', { type: 'button', className: 'odb-icon-btn', 'aria-label': 'Rehacer', title: 'Rehacer (Ctrl+Shift+Z)', disabled: !hist.current.future.length, onClick: redo }, el(Icon, { n: 'redo' })),
					el('button', { type: 'button', className: 'odb-icon-btn' + (panel === 'page' ? ' is-active' : ''), 'aria-pressed': panel === 'page', 'aria-label': 'Ajustes de la página', title: 'Ajustes de la página', onClick: () => { setSel(null); setPanel(panel === 'page' ? 'widgets' : 'page'); } }, el(Icon, { n: 'gear' })),
					el('button', { type: 'button', className: 'odb-icon-btn' + (panel === 'nav' ? ' is-active' : ''), 'aria-pressed': panel === 'nav', 'aria-label': 'Estructura de la página', title: 'Estructura', onClick: () => setPanel(panel === 'nav' ? 'widgets' : 'nav') }, el(Icon, { n: 'layers' })),
					el('span', { className: 'odb-sep', 'aria-hidden': true }),
					meta.link && el('a', { className: 'odb-btn is-ghost', href: meta.link, target: '_blank', rel: 'noopener' }, el(Icon, { n: 'external', s: 15 }), 'Ver'),
					el('button', { type: 'button', className: 'odb-btn is-ghost', onClick: () => save('draft') }, meta.status === 'publish' ? 'Pasar a borrador' : 'Guardar borrador'),
					el('button', { type: 'button', className: 'odb-btn is-primary', onClick: () => save('publish') }, meta.status === 'publish' ? 'Actualizar' : 'Publicar', dirty && el('span', { className: 'odb-dot', 'aria-label': 'cambios sin guardar' })))),
			el('aside', { className: 'odb-side' }, side),
			el('main', { className: 'odb-stage is-' + dev },
				el('div', { className: 'odb-frame', style: { width: widths[dev] } },
					el('iframe', { ref: frame, src: cfg.canvasUrl, title: 'Vista previa' }))));
	}

	const mount = document.getElementById('odin-builder-root');
	if (wp.element.createRoot) wp.element.createRoot(mount).render(el(App));
	else wp.element.render(el(App), mount);
})(window.wp, window.odinBuilder);
