/**
 * Odin Builder — lienzo (dentro del iframe). Pinta el HTML que manda el editor,
 * informa clics/hover y gestiona soltar widgets. Solo habla con su mismo origen.
 */
(function () {
	var root = document.getElementById('odin-canvas');
	if (!root || window.parent === window) return;
	var origin = location.origin;
	var live = document.createElement('style');
	live.id = 'odin-live-css';
	document.head.appendChild(live);
	var NAMES = { container: 'Contenedor', heading: 'Título', text: 'Texto', image: 'Imagen', button: 'Botón', spacer: 'Espaciador', divider: 'Divisor', video: 'Vídeo', html: 'HTML', products: 'Productos', icon: 'Icono', iconbox: 'Caja de icono', iconlist: 'Lista con iconos', accordion: 'Acordeón', tabs: 'Pestañas', gallery: 'Galería', testimonial: 'Testimonio', social: 'Redes sociales', map: 'Mapa', alert: 'Alerta', form: 'Formulario', template: 'Plantilla global', 'wc-title': 'Título producto', 'wc-price': 'Precio', 'wc-images': 'Imágenes producto', 'wc-add-to-cart': 'Añadir al carrito', 'wc-excerpt': 'Descripción corta', 'wc-description': 'Descripción', 'wc-rating': 'Valoración', 'wc-meta': 'SKU / categorías', 'wc-tabs': 'Pestañas producto', 'wc-related': 'Relacionados', card: 'Tarjeta', facts: 'Datos rápidos', terminal: 'Terminal', phonevideo: 'Vídeo en teléfono', linkcards: 'Lista de negocios', chips: 'Chips', project: 'Proyecto', person: 'Persona', steps: 'Pasos', faq: 'Preguntas', breadcrumbs: 'Ruta', menu: 'Menú', whatsapp: 'WhatsApp', mockup: 'Mockup animado', obra3d: 'Obra 3D', pasos: 'Pasos de obra', pjcard: 'Proyecto con galería' };
	var selected = null, dragType = null, dragId = null, marker = null, dropTarget = null;

	function send(msg) { window.parent.postMessage(Object.assign({ source: 'odin-canvas' }, msg), origin); }
	function nodeOf(el) { return el && el.closest ? el.closest('[data-odn]') : null; }
	function byId(id) { return id ? root.querySelector('[data-odn="' + id + '"]') : null; }

	// --- barra flotante del elemento seleccionado
	var bar = document.createElement('div');
	bar.className = 'odn-ui-bar';
	bar.innerHTML = '<span class="odn-ui-name"></span><button type="button" data-act="drag" draggable="true" aria-label="Arrastrar para mover" title="Arrastrar para mover"><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 6h.01M15 6h.01M9 12h.01M15 12h.01M9 18h.01M15 18h.01" stroke-width="3"/></svg></button><button type="button" data-act="dup" aria-label="Duplicar" title="Duplicar"><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg></button><button type="button" data-act="del" aria-label="Eliminar" title="Eliminar"><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/></svg></button>';
	document.body.appendChild(bar);
	bar.addEventListener('click', function (e) {
		var btn = e.target.closest('button'); var act = btn && btn.dataset.act;
		if (selected && (act === 'dup' || act === 'del')) send({ type: act, id: selected });
	});
	bar.querySelector('[data-act=drag]').addEventListener('dragstart', function (e) {
		dragId = selected;
		e.dataTransfer.effectAllowed = 'move';
		e.dataTransfer.setData('text/plain', 'odin');
	});

	function placeBar() {
		var el = byId(selected);
		document.querySelectorAll('.odn-ui-selected').forEach(function (x) { x.classList.remove('odn-ui-selected'); });
		if (!el) { bar.style.display = 'none'; return; }
		el.classList.add('odn-ui-selected');
		var r = el.getBoundingClientRect();
		bar.style.display = 'flex';
		bar.style.top = Math.max(0, r.top + scrollY - 26) + 'px';
		bar.style.left = Math.max(0, r.left + scrollX) + 'px';
		bar.querySelector('.odn-ui-name').textContent = NAMES[el.dataset.odnType] || el.dataset.odnType;
	}

	// --- render
	window.addEventListener('message', function (e) {
		if (e.origin !== origin || !e.data || e.data.source !== 'odin-editor') return;
		var m = e.data;
		if (m.type === 'render') {
			live.textContent = m.css;
			root.innerHTML = m.html || '<div class="odn-ui-empty" data-odn-root>Arrastra un widget aquí para empezar</div>';
			selected = m.selected || null;
			placeBar();
		} else if (m.type === 'select') {
			selected = m.id;
			placeBar();
			var el = byId(m.id);
			if (el && m.scroll) el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
		} else if (m.type === 'dragType') {
			dragType = m.widget;
		}
	});

	// --- selección y hover
	root.addEventListener('click', function (e) {
		e.preventDefault(); // en el lienzo los enlaces no navegan
		var n = nodeOf(e.target);
		if (n) send({ type: 'select', id: n.dataset.odn });
	}, true);
	root.addEventListener('submit', function (e) { e.preventDefault(); }, true);
	root.addEventListener('mouseover', function (e) {
		document.querySelectorAll('.odn-ui-hover').forEach(function (x) { x.classList.remove('odn-ui-hover'); });
		var n = nodeOf(e.target);
		if (n) n.classList.add('odn-ui-hover');
	});
	addEventListener('scroll', placeBar, { passive: true });
	addEventListener('resize', placeBar);

	// --- soltar: antes / después / dentro (contenedores)
	function clearMarker() { if (marker) marker.remove(); marker = null; dropTarget = null; }
	function horizontal(el) {
		var p = el.parentElement && getComputedStyle(el.parentElement);
		return p && (p.display.indexOf('flex') !== -1 && p.flexDirection.indexOf('row') === 0 || p.display.indexOf('grid') !== -1);
	}
	document.addEventListener('dragover', function (e) {
		if (!dragType && !dragId) return;
		e.preventDefault();
		var n = nodeOf(e.target);
		clearMarker();
		marker = document.createElement('div');
		marker.className = 'odn-ui-marker';
		if (!n) {
			dropTarget = { target: null, pos: 'inside' };
			root.appendChild(marker);
			return;
		}
		if (dragId && (n.dataset.odn === dragId || n.closest('[data-odn="' + dragId + '"]'))) { marker = null; return; }
		var r = n.getBoundingClientRect();
		var isRow = horizontal(n);
		var rel = isRow ? (e.clientX - r.left) / r.width : (e.clientY - r.top) / r.height;
		var pos = rel < 0.25 ? 'before' : rel > 0.75 ? 'after' : (n.dataset.odnType === 'container' ? 'inside' : rel < 0.5 ? 'before' : 'after');
		dropTarget = { target: n.dataset.odn, pos: pos };
		if (pos === 'inside') { marker.classList.add('is-inside'); n.appendChild(marker); }
		else { if (isRow) marker.classList.add('is-vertical'); n.parentNode.insertBefore(marker, pos === 'before' ? n : n.nextSibling); }
	});
	document.addEventListener('dragleave', function (e) { if (!e.relatedTarget) clearMarker(); });
	document.addEventListener('drop', function (e) {
		if (!dropTarget) return;
		e.preventDefault();
		send(dragId ? { type: 'move', id: dragId, target: dropTarget.target, pos: dropTarget.pos } : { type: 'add', widget: dragType, target: dropTarget.target, pos: dropTarget.pos });
		clearMarker();
		dragId = dragType = null;
	});
	document.addEventListener('dragend', function () { clearMarker(); dragId = null; });

	send({ type: 'ready' });
})();
