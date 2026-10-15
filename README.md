# César Vidal — web de pruebas

Vista previa: <https://cesarvidalmusic.github.io/cesarvidalmusic-preview/>

Este repositorio permite probar cambios antes de llevarlos a la web oficial.
GitHub Pages publica automáticamente la rama `main`, desde la raíz. No añadir
un archivo `CNAME` ni configurar aquí el dominio `cesarvidalmusic.art`.

## Transición entre páginas

Las 13 páginas HTML comparten `page-transition.js` y `css/page-transition.css`.
La salida dura 500 ms y la entrada 650 ms, conservando el fondo oscuro, el
degradado y el desenfoque aprobados. Los ajustes de duración están en las
variables CSS. La preferencia de movimiento reducido usa 80 ms y 100 ms.

Cada HTML detecta la navegación desde el `<head>`, incluye la cortina de entrada
y marca su contenedor con `data-page-transition-content`. La galería expone
`window.cvPageReady` para que su contenido esté listo antes del fundido.

El controlador cubre enlaces internos del menú y tarjetas creadas dinámicamente.
Respeta enlaces externos, descargas, nuevas pestañas y enlaces desactivados.
Al añadir otra página, incluir los mismos elementos y registrar su nombre en
`ALLOWED_PAGES` dentro de `page-transition.js`. Al cambiar los archivos compartidos,
actualizar su parámetro de versión en los HTML para renovar la caché del navegador.

## Comprobación de cambios

En el entorno de desarrollo, con Python Playwright, Chromium y Node disponibles:

```sh
python3 tests/test_page_transitions.py
```

La prueba inicia un servidor local temporal y comprueba los enlaces internos,
las entradas y salidas completas, móvil, movimiento reducido, caché, cargas
lentas y recuperación cuando faltan recursos o se bloquea el almacenamiento.
No comprueba la reproducción de servicios externos como Bandcamp.

Tras subir cambios a este repositorio, esperar a que termine correctamente el
despliegue de Pages y probar la vista previa en el navegador. La publicación
de esta copia es independiente de la web oficial.
