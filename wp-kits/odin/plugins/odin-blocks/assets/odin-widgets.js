// Odin: pestañas (ratón y teclado) y miniaturas de la galería de producto. Sin dependencias.
(function () {
	function tabs(root) {
		var list = root.querySelector('.odn-tabs__list');
		if (!list || list.dataset.ready) return;
		list.dataset.ready = '1';
		var btns = Array.prototype.slice.call(list.querySelectorAll('[role=tab]'));
		function show(i, focus) {
			btns.forEach(function (b, j) {
				var on = i === j;
				b.setAttribute('aria-selected', on ? 'true' : 'false');
				b.tabIndex = on ? 0 : -1;
				var p = document.getElementById(b.getAttribute('aria-controls'));
				if (p) p.hidden = !on;
			});
			if (focus) btns[i].focus();
		}
		btns.forEach(function (b, i) {
			b.addEventListener('click', function () { show(i); });
			b.addEventListener('keydown', function (e) {
				var k = { ArrowRight: 1, ArrowLeft: -1, Home: -i, End: btns.length - 1 - i }[e.key];
				if (k === undefined) return;
				e.preventDefault();
				show((i + k + btns.length) % btns.length, true);
			});
		});
	}
	function gallery(root) {
		if (root.dataset.ready) return;
		root.dataset.ready = '1';
		var main = root.querySelector('.odn-wcimg__main');
		root.querySelectorAll('.odn-wcimg__thumbs button').forEach(function (b) {
			b.addEventListener('click', function () {
				if (!main) return;
				main.removeAttribute('srcset');
				main.src = b.dataset.full;
				root.querySelectorAll('.odn-wcimg__thumbs button').forEach(function (x) { x.setAttribute('aria-current', x === b ? 'true' : 'false'); });
			});
		});
	}
	// Menú: botón ☰ en móvil y submenús desplegables (se cierran al hacer clic fuera o con Esc).
	function menu(root) {
		if (root.dataset.ready) return;
		root.dataset.ready = '1';
		var bar = root.closest('.nav') || root;
		var btn = root.querySelector('.nav-toggle');
		var subs = root.querySelectorAll('.has-sub details');
		var setOpen = function (open) {
			bar.classList.toggle('open', open);
			if (!btn) return;
			btn.setAttribute('aria-expanded', String(open));
			btn.setAttribute('aria-label', open ? 'Cerrar menú' : 'Abrir menú');
		};
		if (btn) btn.addEventListener('click', function () { setOpen(!bar.classList.contains('open')); });
		root.querySelectorAll('nav a').forEach(function (a) { a.addEventListener('click', function () { setOpen(false); subs.forEach(function (d) { d.open = false; }); }); });
		document.addEventListener('click', function (e) { subs.forEach(function (d) { if (d.open && !d.contains(e.target)) d.open = false; }); });
		document.addEventListener('keydown', function (e) { if (e.key === 'Escape') { setOpen(false); subs.forEach(function (d) { d.open = false; }); } });
	}
	// Burbuja de WhatsApp: al cerrarla no vuelve a salir en esta visita.
	function bubble(b) {
		if (b.dataset.ready) return;
		b.dataset.ready = '1';
		try { if (sessionStorage.getItem('odin-wa-closed')) b.hidden = true; } catch (e) {}
		var c = b.querySelector('.wa-close');
		if (c) c.addEventListener('click', function () { b.hidden = true; try { sessionStorage.setItem('odin-wa-closed', '1'); } catch (e) {} });
	}
	// Proyecto con galería: modal con carrusel de fotos y vídeos de YouTube (el iframe se crea al dar play).
	var modal = null;
	function proyectoModal() {
		if (modal) return modal;
		modal = document.createElement('dialog');
		modal.className = 'modal';
		modal.setAttribute('aria-labelledby', 'pj-modal-t');
		modal.innerHTML = '<div class="modal__box"><button type="button" class="modal__close" aria-label="Cerrar">&times;</button>'
			+ '<div class="slider" aria-roledescription="carrusel"><div class="slider__stage"><div class="slider__slide" aria-live="polite"></div>'
			+ '<button type="button" class="slider__nav slider__nav--prev" aria-label="Anterior">&#8249;</button><button type="button" class="slider__nav slider__nav--next" aria-label="Siguiente">&#8250;</button>'
			+ '<span class="slider__count" aria-hidden="true"></span></div><div class="slider__thumbs" role="group" aria-label="Miniaturas"></div></div>'
			+ '<div class="modal__info"><p class="eyebrow modal__tag"></p><h2 id="pj-modal-t"></h2><p class="modal__lugar"></p><p class="modal__desc"></p><ul class="modal__datos"></ul>'
			+ '<a class="btn btn--gold modal__cta" target="_blank" rel="noopener"></a></div></div>';
		document.body.appendChild(modal);
		var q = function (s) { return modal.querySelector(s); };
		var slide = q('.slider__slide'), thumbs = q('.slider__thumbs'), count = q('.slider__count'), navs = modal.querySelectorAll('.slider__nav');
		var mk = function (tag, props) { return Object.assign(document.createElement(tag), props || {}); };
		var media = [], i = 0, origen = null;
		function poster(m) {
			var b = mk('button', { type: 'button', className: 'slider__play' });
			b.setAttribute('aria-label', 'Reproducir: ' + m.alt);
			var ico = mk('span', { className: 'slider__play-ico' });
			ico.setAttribute('aria-hidden', 'true');
			b.append(mk('img', { src: m.src, alt: '' }), ico);
			b.addEventListener('click', function () {
				var f = mk('iframe', { src: 'https://www.youtube-nocookie.com/embed/' + encodeURIComponent(m.id) + '?autoplay=1&rel=0', title: m.alt, allow: 'accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture', allowFullscreen: true });
				f.setAttribute('referrerpolicy', 'strict-origin-when-cross-origin');
				b.replaceWith(f);
			});
			return b;
		}
		function mostrar(n) {
			i = (n + media.length) % media.length;
			var m = media[i];
			slide.replaceChildren(m.t === 'yt' ? poster(m) : mk('img', { src: m.src, alt: m.alt }));
			slide.classList.toggle('is-video', m.t === 'yt');
			count.textContent = (i + 1) + ' / ' + media.length;
			thumbs.querySelectorAll('button').forEach(function (t, k) { t.setAttribute('aria-current', String(k === i)); });
			if (thumbs.children[i]) thumbs.children[i].scrollIntoView({ block: 'nearest', inline: 'center', behavior: 'smooth' });
			var sig = media[(i + 1) % media.length];
			if (sig && sig.t === 'img') new Image().src = sig.src; // precarga la siguiente foto
		}
		modal.abrir = function (p, boton) {
			origen = boton;
			media = p.media || [];
			i = 0;
			q('.modal__tag').textContent = p.tag || '';
			q('#pj-modal-t').textContent = p.title || '';
			q('.modal__lugar').textContent = p.lugar || '';
			q('.modal__lugar').hidden = !p.lugar;
			q('.modal__desc').textContent = p.desc || '';
			q('.modal__datos').replaceChildren.apply(q('.modal__datos'), (p.datos || []).map(function (d) { return mk('li', { textContent: d }); }));
			var cta = q('.modal__cta');
			cta.hidden = !p.wa;
			cta.href = p.wa || '#';
			cta.textContent = p.cta || 'Quiero un proyecto así';
			thumbs.replaceChildren.apply(thumbs, media.map(function (m, k) {
				var t = mk('button', { type: 'button', className: m.t === 'yt' ? 'is-video' : '' });
				t.setAttribute('aria-label', m.t === 'yt' ? 'Ver video' : 'Ver foto ' + (k + 1));
				t.append(mk('img', { src: m.src, alt: '', loading: 'lazy' }));
				t.addEventListener('click', function () { mostrar(k); });
				return t;
			}));
			var una = media.length < 2;
			navs.forEach(function (b) { b.hidden = una; });
			thumbs.hidden = una;
			count.hidden = una;
			mostrar(0);
			modal.showModal();
			document.documentElement.classList.add('modal-abierto');
		};
		navs[0].addEventListener('click', function () { mostrar(i - 1); });
		navs[1].addEventListener('click', function () { mostrar(i + 1); });
		q('.modal__close').addEventListener('click', function () { modal.close(); });
		modal.addEventListener('click', function (e) { if (e.target === modal) modal.close(); }); // clic en el fondo
		modal.addEventListener('close', function () {
			slide.replaceChildren(); // detiene el vídeo
			document.documentElement.classList.remove('modal-abierto');
			if (origen) origen.focus();
		});
		modal.addEventListener('keydown', function (e) {
			if (e.target.closest('.slider__thumbs')) return;
			if (e.key === 'ArrowRight') mostrar(i + 1);
			if (e.key === 'ArrowLeft') mostrar(i - 1);
		});
		var x0 = null; // deslizar con el dedo
		slide.addEventListener('pointerdown', function (e) { x0 = e.clientX; });
		slide.addEventListener('pointerup', function (e) {
			if (x0 === null || media.length < 2) return;
			var dx = e.clientX - x0;
			x0 = null;
			if (Math.abs(dx) > 50) mostrar(i + (dx < 0 ? 1 : -1));
		});
		return modal;
	}
	function proyecto(b) {
		if (b.dataset.ready || document.getElementById('odin-canvas')) return;
		b.dataset.ready = '1';
		b.addEventListener('click', function () {
			proyectoModal().abrir(JSON.parse(b.dataset.pj), b);
		});
	}
	function boot() {
		document.querySelectorAll('.odn-tabs').forEach(tabs);
		document.querySelectorAll('.pj__open').forEach(proyecto);
		document.querySelectorAll('.odn-wc-images').forEach(gallery);
		document.querySelectorAll('.odn-menu').forEach(menu);
		document.querySelectorAll('.wa-bubble').forEach(bubble);
	}
	document.readyState === 'loading' ? document.addEventListener('DOMContentLoaded', boot) : boot();
	// Solo en el lienzo del editor, que vuelve a pintar el HTML: reengancha.
	var canvas = document.getElementById('odin-canvas');
	if (canvas) new MutationObserver(boot).observe(canvas, { childList: true });
})();
