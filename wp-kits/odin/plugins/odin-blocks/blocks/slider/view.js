// Slider: scroll-snap nativo + flechas, puntos, autoplay y bucle. Sin dependencias.
(function () {
	function init(root) {
		var track = root.querySelector('.odin-slider__track');
		if (!track || root.dataset.ready) return;
		root.dataset.ready = '1';
		track.setAttribute('tabindex', '0');
		var loop = root.dataset.loop === '1';
		var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
		var dotsWrap = null;

		function pages() { return Math.max(1, Math.round(track.scrollWidth / track.clientWidth)); }
		function page() { return Math.round(track.scrollLeft / track.clientWidth); }
		function go(i) {
			var n = pages();
			if (i >= n) i = loop ? 0 : n - 1;
			if (i < 0) i = loop ? n - 1 : 0;
			track.scrollTo({ left: i * track.clientWidth, behavior: reduce ? 'auto' : 'smooth' });
		}

		if (root.dataset.arrows === '1') {
			[['prev', '‹', 'Anterior', -1], ['next', '›', 'Siguiente', 1]].forEach(function (b) {
				var btn = document.createElement('button');
				btn.type = 'button';
				btn.className = 'odin-slider__arrow odin-slider__arrow--' + b[0];
				btn.setAttribute('aria-label', b[2]);
				btn.textContent = b[1];
				btn.addEventListener('click', function () { go(page() + b[3]); });
				root.appendChild(btn);
			});
		}

		function renderDots() {
			if (root.dataset.dots !== '1') return;
			if (!dotsWrap) {
				dotsWrap = document.createElement('div');
				dotsWrap.className = 'odin-slider__dots';
				root.appendChild(dotsWrap);
			}
			var n = pages();
			dotsWrap.innerHTML = '';
			dotsWrap.hidden = n < 2;
			for (var i = 0; i < n; i++) {
				var d = document.createElement('button');
				d.type = 'button';
				d.setAttribute('aria-label', 'Ir a ' + (i + 1));
				d.addEventListener('click', go.bind(null, i));
				dotsWrap.appendChild(d);
			}
			mark();
		}
		function mark() {
			if (!dotsWrap) return;
			var p = page();
			Array.prototype.forEach.call(dotsWrap.children, function (d, i) {
				d.setAttribute('aria-current', i === p ? 'true' : 'false');
			});
		}

		var ticking = false;
		track.addEventListener('scroll', function () {
			if (ticking) return;
			ticking = true;
			requestAnimationFrame(function () { ticking = false; mark(); });
		}, { passive: true });
		window.addEventListener('resize', renderDots);
		renderDots();

		var secs = parseInt(root.dataset.autoplay, 10);
		if (secs > 0 && !reduce) {
			var paused = false;
			['mouseenter', 'focusin'].forEach(function (e) { root.addEventListener(e, function () { paused = true; }); });
			['mouseleave', 'focusout'].forEach(function (e) { root.addEventListener(e, function () { paused = false; }); });
			setInterval(function () {
				if (!paused && !document.hidden) go(page() + 1);
			}, secs * 1000);
		}
	}
	function boot() { document.querySelectorAll('.odin-slider').forEach(init); }
	document.readyState === 'loading' ? document.addEventListener('DOMContentLoaded', boot) : boot();
})();
