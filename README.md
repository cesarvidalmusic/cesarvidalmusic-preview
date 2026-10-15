# cesarvidalmusic.art

Personal website of César Vidal — saxophonist, composer and improviser.

---

## Estructura de archivos

```
cesarvidalmusic/
├── index.html          ← Home
├── bio.html
├── music.html
├── projects.html
├── contact.html
├── css/
│   └── style.css
├── fonts/
│   ├── Mattone-Black.woff2     ← DEBES DESCARGAR (ver abajo)
│   └── Mattone-Regular.woff2  ← DEBES DESCARGAR (ver abajo)
└── img/
    ├── hero.jpg                ← Tu foto principal (home)
    └── bio-photo.jpg           ← Tu foto de la página Bio
```

---

## Paso 1: Descargar las fuentes

1. Ve a https://www.collletttivo.it/typefaces/mattone
2. Haz click en **Download**
3. Descomprime el zip
4. Copia `Mattone-Black.woff2` y `Mattone-Regular.woff2` a la carpeta `fonts/`

---

## Paso 2: Agregar tus fotos

- `img/hero.jpg` → tu foto principal (la de Amsterdam en B&N, horizontal)
- `img/bio-photo.jpg` → retrato para la página Bio

Puedes usar JPG o WEBP. Recomendado: máximo 1.5MB por imagen para que cargue rápido.

---

## Paso 3: Actualizar los links

Busca los comentarios `<!-- Replace ... -->` en cada HTML y pon tus URLs reales:
- Email en contact.html
- Links de Bandcamp, Apple Music, Instagram, YouTube

---

## Paso 4: Subir a GitHub Pages

1. Crea una cuenta en https://github.com si no tienes
2. Crea un repositorio nuevo llamado `cesarvidalmusic` (público)
3. Sube todos los archivos (arrastra y suelta en la interfaz web de GitHub)
4. Ve a Settings → Pages → Source: Deploy from branch → main → / (root)
5. GitHub te dará una URL tipo `tuusuario.github.io/cesarvidalmusic`

---

## Paso 5: Conectar tu dominio de Porkbun

En Porkbun, ve a DNS de tu dominio y agrega estos registros:

| Type  | Host | Answer               | TTL  |
|-------|------|----------------------|------|
| A     | @    | 185.199.108.153      | 600  |
| A     | @    | 185.199.109.153      | 600  |
| A     | @    | 185.199.110.153      | 600  |
| A     | @    | 185.199.111.153      | 600  |
| CNAME | www  | tuusuario.github.io  | 600  |

Luego en GitHub → Settings → Pages → Custom domain: escribe `cesarvidalmusic.art`
Activa "Enforce HTTPS" (puede tardar unos minutos en aparecer).

---

## Actualizar el sitio en el futuro

Para cambiar cualquier contenido: edita el archivo HTML en GitHub directamente desde el navegador (botón del lápiz), haz commit, y el sitio se actualiza en ~1 minuto.
