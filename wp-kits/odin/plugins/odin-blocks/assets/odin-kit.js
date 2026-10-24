// Odin kit: animaciones del sitio (aparición al hacer scroll, tarjetas 3D, mockups que se arman,
// terminal que escribe y vídeo que se reproduce al verse). En el lienzo del editor no se ejecuta.
(function () {
	if (document.getElementById('odin-canvas')) return;
	var reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;

	// Aparición de los bloques de cada sección
	if ('IntersectionObserver' in window) {
		var io = new IntersectionObserver(function (entries) {
			entries.forEach(function (e) { if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); } });
		}, { threshold: 0.12 });
		document.querySelectorAll('.section > *').forEach(function (el) { el.classList.add('reveal'); io.observe(el); });
	}

	// Inclinación 3D con el puntero (solo ratón)
	if (!reduce && matchMedia('(hover: hover)').matches) {
		document.querySelectorAll('.tilt').forEach(function (el) {
			el.addEventListener('pointermove', function (ev) {
				var r = el.getBoundingClientRect();
				el.style.setProperty('--ry', ((ev.clientX - r.left) / r.width - 0.5) * 10 + 'deg');
				el.style.setProperty('--rx', -((ev.clientY - r.top) / r.height - 0.5) * 10 + 'deg');
			});
			el.addEventListener('pointerleave', function () { el.style.removeProperty('--rx'); el.style.removeProperty('--ry'); });
		});
	}

	// Mockups que se arman pieza por pieza con el scroll
	var assemblies = document.querySelectorAll('.assemble');
	if (assemblies.length && !reduce) {
		var ticking = false;
		var update = function () {
			ticking = false;
			var vh = innerHeight;
			assemblies.forEach(function (el) {
				var p = Math.min(1, Math.max(0, (vh - el.getBoundingClientRect().top) / (vh * 0.7)));
				el.style.setProperty('--k', (1 - p * p * (3 - 2 * p)).toFixed(3));
			});
		};
		addEventListener('scroll', function () { if (!ticking) { ticking = true; requestAnimationFrame(update); } }, { passive: true });
		addEventListener('resize', update);
		update();
	}

	// Terminal: escribe los comandos línea a línea, en bucle
	document.querySelectorAll('.terminal-body').forEach(function (term) {
		if (reduce) return;
		var caret = term.querySelector('.caret');
		var lines = Array.prototype.map.call(term.querySelectorAll('.t-line'), function (el) {
			return { el: el, cmd: !!el.querySelector('b'), text: el.textContent.replace(/^\$\s/, '') };
		});
		var sleep = function (ms) { return new Promise(function (r) { setTimeout(r, ms); }); };
		(async function type() {
			for (;;) {
				lines.forEach(function (l) { l.el.textContent = ''; });
				for (var i = 0; i < lines.length; i++) {
					var l = lines[i];
					if (l.cmd) {
						var b = document.createElement('b');
						b.textContent = '$';
						var tn = document.createTextNode(' ');
						l.el.append(b, tn, caret);
						await sleep(500);
						for (var j = 0; j < l.text.length; j++) { tn.data += l.text[j]; await sleep(35 + Math.random() * 55); }
						await sleep(300);
					} else {
						await sleep(350);
						l.el.textContent = l.text;
						l.el.append(caret);
					}
				}
				await sleep(5000);
			}
		})();
	});

	// Scroll: <html>.odin-scrolled, profundidad de .tilt (--depth de -1 a 1 según su posición en pantalla)
	// y botón fijo .cta-movil (visible tras la primera pantalla y oculto al llegar a #contacto).
	var tilts = Array.prototype.slice.call(document.querySelectorAll('.tilt'));
	var ctaMovil = document.querySelectorAll('.cta-movil');
	var contacto = document.getElementById('contacto');
	var pending = false;
	var onScroll = function () {
		pending = false;
		var y = scrollY, h = innerHeight;
		document.documentElement.classList.toggle('odin-scrolled', y > 8);
		ctaMovil.forEach(function (b) { b.classList.toggle('is-visible', y > h * 0.9 && (!contacto || contacto.getBoundingClientRect().top > h)); });
		if (reduce) return;
		tilts.forEach(function (el) {
			var r = el.getBoundingClientRect();
			if (r.bottom < 0 || r.top > h) return;
			el.style.setProperty('--depth', Math.max(-1, Math.min(1, ((r.top + r.height / 2) / h - 0.5) * 2)).toFixed(3));
		});
	};
	addEventListener('scroll', function () { if (!pending) { pending = true; requestAnimationFrame(onScroll); } }, { passive: true });
	addEventListener('resize', onScroll);
	onScroll();

	if ('IntersectionObserver' in window) {
		// Paso activo de un proceso (widget Pasos de obra)
		var pio = new IntersectionObserver(function (en) {
			en.forEach(function (e) { e.target.classList.toggle('is-on', e.isIntersecting); });
		}, { rootMargin: '-35% 0px -35% 0px' });
		document.querySelectorAll('.paso').forEach(function (el) { pio.observe(el); });
		// Enlace del menú (#ancla) de la sección visible
		var anchors = Array.prototype.filter.call(document.querySelectorAll('.odn-menu a[href*="#"]'), function (a) {
			return a.hash && a.pathname === location.pathname && document.getElementById(a.hash.slice(1));
		});
		if (anchors.length) {
			var aio = new IntersectionObserver(function (en) {
				en.forEach(function (e) {
					if (e.isIntersecting) anchors.forEach(function (a) { a.classList.toggle('is-active', a.hash === '#' + e.target.id); });
				});
			}, { rootMargin: '-45% 0px -50% 0px' });
			anchors.forEach(function (a) { aio.observe(document.getElementById(a.hash.slice(1))); });
		}
	}

	// Vídeos en marco de teléfono: se reproducen (en silencio) solo mientras se ven
	if (!reduce && 'IntersectionObserver' in window) {
		document.querySelectorAll('.phone video').forEach(function (v) {
			new IntersectionObserver(function (en) {
				if (en[0].isIntersecting) v.play().catch(function () {}); else v.pause();
			}, { threshold: 0.4 }).observe(v);
		});
	}
})();
