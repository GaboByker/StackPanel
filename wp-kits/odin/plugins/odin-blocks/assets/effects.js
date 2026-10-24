// Animación de entrada: añade .is-visible cuando el bloque entra en pantalla.
(function () {
	var els = document.querySelectorAll('.odin-anim');
	if (!els.length) return;
	var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
	if (reduce || !('IntersectionObserver' in window)) {
		els.forEach(function (el) { el.classList.add('is-visible'); });
		return;
	}
	document.documentElement.classList.add('odin-anim-ready');
	var io = new IntersectionObserver(function (entries) {
		entries.forEach(function (en) {
			if (en.isIntersecting) {
				en.target.classList.add('is-visible');
				io.unobserve(en.target);
			}
		});
	}, { rootMargin: '0px 0px -10% 0px' });
	els.forEach(function (el) { io.observe(el); });
})();
