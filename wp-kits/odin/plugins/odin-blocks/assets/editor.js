/**
 * Odin Blocks — editor. Sin build: usa los globales wp.* que ya carga el editor.
 * Los bloques contenedores guardan solo su contenido interno; el HTML final lo genera PHP.
 */
(function (wp) {
	var el = wp.element.createElement;
	var useEffect = wp.element.useEffect;
	var be = wp.blockEditor;
	var c = wp.components;
	var registerBlockType = wp.blocks.registerBlockType;
	var InnerBlocks = be.InnerBlocks;

	function panel(title, children, opened) {
		return el(be.InspectorControls, null, el(c.PanelBody, { title: title, initialOpen: opened !== false }, children));
	}
	function text(label, value, onChange, help) {
		return el(c.TextControl, { __nextHasNoMarginBottom: true, label: label, value: value || '', onChange: onChange, help: help });
	}
	function toggle(label, checked, onChange) {
		return el(c.ToggleControl, { __nextHasNoMarginBottom: true, label: label, checked: !!checked, onChange: onChange });
	}
	function range(label, value, onChange, min, max) {
		return el(c.RangeControl, { __nextHasNoMarginBottom: true, label: label, value: value, onChange: onChange, min: min, max: max });
	}
	function select(label, value, options, onChange) {
		return el(c.SelectControl, { __nextHasNoMarginBottom: true, label: label, value: value, options: options, onChange: onChange });
	}
	function opts(map) {
		return Object.keys(map).map(function (k) { return { value: k, label: map[k] }; });
	}
	function set(props, key) {
		return function (v) { var o = {}; o[key] = v; props.setAttributes(o); };
	}
	function tag(label) { return el('span', { className: 'odin-editor-tag' }, label); }
	function useAutoId(props, key, prefix) {
		useEffect(function () {
			if (!props.attributes[key]) {
				var o = {};
				o[key] = prefix + props.clientId.slice(0, 8);
				props.setAttributes(o);
			}
		}, []);
	}
	var saveInner = function () { return el(InnerBlocks.Content); };

	// ---------- Formulario ----------
	registerBlockType('odin/form', {
		edit: function (props) {
			var a = props.attributes;
			useAutoId(props, 'formId', 'form-');
			var inner = be.useInnerBlocksProps({ className: 'odin-form__fields' }, {
				allowedBlocks: ['odin/field', 'core/heading', 'core/paragraph', 'core/group', 'core/columns'],
				template: [
					['odin/field', { label: 'Nombre', type: 'text', required: true, width: '50' }],
					['odin/field', { label: 'Email', type: 'email', required: true, width: '50' }],
					['odin/field', { label: 'Mensaje', type: 'textarea', required: true }]
				]
			});
			return el(wp.element.Fragment, null,
				panel('Envío', [
					text('Enviar a (email)', a.recipient, set(props, 'recipient'), 'Vacío = email del administrador.'),
					text('Asunto del email', a.subject, set(props, 'subject')),
					text('Texto del botón', a.submitLabel, set(props, 'submitLabel')),
					el(c.TextareaControl, { __nextHasNoMarginBottom: true, label: 'Mensaje de éxito', value: a.successMessage, onChange: set(props, 'successMessage') }),
					el(c.TextareaControl, { __nextHasNoMarginBottom: true, label: 'Mensaje de error', value: a.errorMessage, onChange: set(props, 'errorMessage') }),
					el('p', { className: 'description' }, 'Los envíos se guardan en wp-admin → Formularios.')
				]),
				el('div', be.useBlockProps({ className: 'odin-form odin-editor-box' }),
					tag('Formulario'),
					el('div', inner),
					el('div', { style: { marginTop: '1rem' } }, el('span', { className: 'wp-element-button' }, a.submitLabel || 'Enviar'))
				)
			);
		},
		save: saveInner
	});

	var FIELD_TYPES = opts({ text: 'Texto', email: 'Email', tel: 'Teléfono', number: 'Número', url: 'URL', date: 'Fecha', textarea: 'Área de texto', select: 'Desplegable', radio: 'Opción única', checkbox: 'Casilla' });

	registerBlockType('odin/field', {
		edit: function (props) {
			var a = props.attributes;
			var hasOptions = a.type === 'select' || a.type === 'radio';
			var label = (a.label || 'Campo') + (a.required ? ' *' : '');
			var preview;
			if (a.type === 'checkbox') {
				preview = el('label', null, el('input', { type: 'checkbox', disabled: true }), ' ', label);
			} else {
				var first = (a.options || '').split('\n')[0];
				preview = [
					el('strong', { key: 'l' }, label),
					el('div', { key: 'f', className: 'odin-editor-field__fake' + (a.type === 'textarea' ? ' is-textarea' : '') },
						hasOptions ? (first || 'Añade opciones en el panel lateral') + (a.type === 'select' ? ' ▾' : '') : (a.placeholder || ''))
				];
			}
			return el(wp.element.Fragment, null,
				panel('Campo', [
					text('Etiqueta', a.label, set(props, 'label')),
					select('Tipo', a.type, FIELD_TYPES, set(props, 'type')),
					toggle('Obligatorio', a.required, set(props, 'required')),
					a.type !== 'checkbox' && text('Placeholder', a.placeholder, set(props, 'placeholder')),
					hasOptions && el(c.TextareaControl, { __nextHasNoMarginBottom: true, label: 'Opciones (una por línea)', value: a.options, onChange: set(props, 'options') }),
					select('Ancho', a.width, opts({ '100': 'Completo', '50': 'Mitad', '33': 'Un tercio' }), set(props, 'width')),
					text('Nombre interno', a.name, set(props, 'name'), 'Opcional. Vacío = se genera de la etiqueta. Debe ser único en el formulario.')
				]),
				el('div', be.useBlockProps({ className: 'odin-editor-field' }), preview)
			);
		},
		save: function () { return null; }
	});

	// ---------- Slider ----------
	registerBlockType('odin/slider', {
		edit: function (props) {
			var a = props.attributes;
			var inner = be.useInnerBlocksProps({ className: 'odin-editor-slider__track' }, {
				allowedBlocks: ['odin/slide'],
				template: [['odin/slide'], ['odin/slide'], ['odin/slide']],
				orientation: 'horizontal'
			});
			return el(wp.element.Fragment, null,
				panel('Slider', [
					range('Diapositivas visibles', a.perView, set(props, 'perView'), 1, 6),
					range('Separación (px)', a.gap, set(props, 'gap'), 0, 64),
					toggle('Flechas', a.arrows, set(props, 'arrows')),
					toggle('Puntos', a.dots, set(props, 'dots')),
					toggle('Volver al inicio al final', a.loop, set(props, 'loop')),
					toggle('Reproducción automática', a.autoplay, set(props, 'autoplay')),
					a.autoplay && range('Segundos por diapositiva', a.interval, set(props, 'interval'), 2, 15),
					el('p', { className: 'description' }, 'En móvil se muestra 1 y en tablet máximo 2.')
				]),
				el('div', be.useBlockProps({ className: 'odin-editor-box odin-editor-slider' }), tag('Slider · ' + a.perView + ' visible(s)'), el('div', inner))
			);
		},
		save: saveInner
	});

	registerBlockType('odin/slide', {
		edit: function () {
			var inner = be.useInnerBlocksProps(be.useBlockProps(), {
				template: [['core/heading', { placeholder: 'Título de la diapositiva' }], ['core/paragraph', { placeholder: 'Texto…' }]]
			});
			return el('div', inner);
		},
		save: saveInner
	});

	// ---------- Popup ----------
	var TRIGGERS = { load: 'Al cargar la página', scroll: 'Al hacer scroll', exit: 'Al intentar salir (escritorio)', click: 'Solo al hacer clic en un enlace' };
	registerBlockType('odin/popup', {
		edit: function (props) {
			var a = props.attributes;
			useAutoId(props, 'popupId', 'popup-');
			var inner = be.useInnerBlocksProps({}, {
				template: [['core/heading', { content: 'Título del popup' }], ['core/paragraph', { placeholder: 'Contenido…' }], ['core/buttons']]
			});
			var when = TRIGGERS[a.trigger] + (a.trigger === 'load' ? ' (' + a.delay + ' s)' : a.trigger === 'scroll' ? ' (' + a.scroll + '%)' : '');
			return el(wp.element.Fragment, null,
				panel('Popup', [
					select('Se abre', a.trigger, opts(TRIGGERS), set(props, 'trigger')),
					a.trigger === 'load' && range('Retraso (segundos)', a.delay, set(props, 'delay'), 0, 60),
					a.trigger === 'scroll' && range('Al llegar al % de la página', a.scroll, set(props, 'scroll'), 5, 100),
					select('Frecuencia', a.frequency, opts({ always: 'Siempre', session: 'Una vez por visita', days: 'Una vez cada X días' }), set(props, 'frequency')),
					a.frequency === 'days' && range('Días', a.days, set(props, 'days'), 1, 90),
					range('Ancho máximo (px)', a.width, set(props, 'width'), 280, 1200),
					text('ID del popup', a.popupId, set(props, 'popupId'), 'Un enlace a #' + (a.popupId || 'id') + ' lo abre siempre (botones, menús…).'),
					text('Ancla extra (opcional)', a.anchor, set(props, 'anchor'), 'Ej.: "oferta" → los enlaces a #oferta también lo abren.')
				]),
				el('div', be.useBlockProps({ className: 'odin-editor-box', style: { maxWidth: a.width + 'px' } }),
					tag('Popup · ' + when),
					el('div', inner)
				)
			);
		},
		save: saveInner
	});

	// ---------- Productos ----------
	if (wp.blocks.getBlockType && wp.serverSideRender) {
		registerBlockType('odin/products', {
			edit: function (props) {
				var a = props.attributes;
				var cats = wp.data.useSelect(function (s) {
					return s('core').getEntityRecords('taxonomy', 'product_cat', { per_page: 100, _fields: 'id,name,slug' });
				}, []);
				var catOpts = [{ value: '', label: 'Todas' }].concat((cats || []).map(function (t) { return { value: t.slug, label: t.name }; }));
				return el(wp.element.Fragment, null,
					panel('Productos', [
						range('Cantidad', a.count, set(props, 'count'), 1, 24),
						range('Columnas', a.columns, set(props, 'columns'), 1, 6),
						select('Categoría', a.category, catOpts, set(props, 'category')),
						select('Ordenar por', a.orderby, opts({ date: 'Más recientes', popularity: 'Más vendidos', rating: 'Mejor valorados', price: 'Precio: menor a mayor', 'price-desc': 'Precio: mayor a menor', title: 'Nombre', rand: 'Aleatorio' }), set(props, 'orderby')),
						toggle('Solo en oferta', a.onSale, set(props, 'onSale')),
						toggle('Solo destacados', a.featured, set(props, 'featured')),
						toggle('Mostrar precio', a.showPrice, set(props, 'showPrice')),
						toggle('Mostrar valoración', a.showRating, set(props, 'showRating')),
						toggle('Botón añadir al carrito', a.showButton, set(props, 'showButton'))
					]),
					el('div', be.useBlockProps(), el(wp.serverSideRender, { block: 'odin/products', attributes: a }))
				);
			},
			save: function () { return null; }
		});
	}

	// ---------- Efectos para todos los bloques ----------
	var SKIP = ['odin/field', 'odin/slide', 'core/freeform', 'core/html', 'core/shortcode'];
	wp.hooks.addFilter('blocks.registerBlockType', 'odin/effects-attrs', function (settings, name) {
		if (SKIP.indexOf(name) !== -1) return settings;
		settings.attributes = Object.assign({}, settings.attributes, {
			odinAnim: { type: 'string' },
			odinDelay: { type: 'number' },
			odinHide: { type: 'array', items: { type: 'string' } }
		});
		return settings;
	});

	var ANIMS = opts({ '': 'Ninguna', fade: 'Aparecer', 'fade-up': 'Subir', 'fade-down': 'Bajar', 'fade-left': 'Desde la derecha', 'fade-right': 'Desde la izquierda', zoom: 'Zoom' });
	var DEVICES = { mobile: 'Ocultar en móvil', tablet: 'Ocultar en tablet', desktop: 'Ocultar en escritorio' };

	wp.hooks.addFilter('editor.BlockEdit', 'odin/effects-panel', wp.compose.createHigherOrderComponent(function (BlockEdit) {
		return function (props) {
			if (SKIP.indexOf(props.name) !== -1 || !props.isSelected) return el(BlockEdit, props);
			var a = props.attributes;
			var hide = a.odinHide || [];
			return el(wp.element.Fragment, null,
				el(BlockEdit, props),
				panel('Efectos (Odin)', [
					select('Animación de entrada', a.odinAnim || '', ANIMS, function (v) { props.setAttributes({ odinAnim: v || undefined }); }),
					a.odinAnim && range('Retraso (ms)', a.odinDelay || 0, function (v) { props.setAttributes({ odinDelay: v || undefined }); }, 0, 2000),
					Object.keys(DEVICES).map(function (d) {
						return el(c.CheckboxControl, {
							key: d,
							__nextHasNoMarginBottom: true,
							label: DEVICES[d],
							checked: hide.indexOf(d) !== -1,
							onChange: function (on) {
								var next = hide.filter(function (x) { return x !== d; });
								if (on) next.push(d);
								props.setAttributes({ odinHide: next.length ? next : undefined });
							}
						});
					})
				], false)
			);
		};
	}, 'withOdinEffects'));
})(window.wp);
