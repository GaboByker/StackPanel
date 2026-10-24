// Popup sobre <dialog> nativo (foco, Esc y capa superior los da el navegador).
(function () {
	function store(kind) {
		try { return window[kind]; } catch (e) { return null; }
	}
	function init(dlg) {
		var d = dlg.dataset, key = 'odin_popup_' + dlg.id;
		var ss = store('sessionStorage'), ls = store('localStorage');

		function allowed() {
			try {
				if (d.frequency === 'session') return !(ss && ss.getItem(key));
				if (d.frequency === 'days') {
					var last = ls && parseInt(ls.getItem(key), 10);
					return !last || Date.now() - last > d.days * 864e5;
				}
			} catch (e) {}
			return true;
		}
		function remember() {
			try {
				if (ss) ss.setItem(key, '1');
				if (ls) ls.setItem(key, String(Date.now()));
			} catch (e) {}
		}
		function open(force) {
			if (dlg.open || (!force && !allowed())) return;
			dlg.showModal();
			remember();
		}

		dlg.querySelector('.odin-popup__close').addEventListener('click', function () { dlg.close(); });
		dlg.addEventListener('click', function (e) { if (e.target === dlg) dlg.close(); });

		// Cualquier enlace a #id-del-popup (o #ancla configurada) lo abre siempre.
		var targets = ['#' + dlg.id];
		if (d.anchor) targets.push('#' + d.anchor);
		document.addEventListener('click', function (e) {
			var a = e.target.closest && e.target.closest('a[href]');
			if (a && targets.indexOf(a.getAttribute('href')) !== -1) {
				e.preventDefault();
				open(true);
			}
		});

		if (d.trigger === 'load') {
			setTimeout(open, (parseInt(d.delay, 10) || 0) * 1000);
		} else if (d.trigger === 'scroll') {
			var onScroll = function () {
				var h = document.documentElement;
				if ((h.scrollTop + innerHeight) / h.scrollHeight * 100 >= d.scroll) {
					removeEventListener('scroll', onScroll);
					open();
				}
			};
			addEventListener('scroll', onScroll, { passive: true });
		} else if (d.trigger === 'exit') {
			var onOut = function (e) {
				if (e.clientY <= 0 && !e.relatedTarget) {
					document.removeEventListener('mouseout', onOut);
					open();
				}
			};
			document.addEventListener('mouseout', onOut);
		}
	}
	function boot() { document.querySelectorAll('dialog.odin-popup').forEach(init); }
	document.readyState === 'loading' ? document.addEventListener('DOMContentLoaded', boot) : boot();
})();
