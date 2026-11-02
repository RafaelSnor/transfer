# Onde Ninguém Pisa — del guion al video

## Qué hay aquí
- `roteiro_01.md`: guion del video 1, ya corregido.
- `busquedas.json`: qué buscar en Pixabay para cada nota `[IMAGEN: ...]`. Edítalo si un clip no te gusta.
- `hacer_video.py`: el pipeline.

## Instalar (una sola vez)
```
sudo apt install ffmpeg            # versión 4.4 o mayor
pip install edge-tts requests      # agrega --break-system-packages si pip lo pide
export PIXABAY_API_KEY="tu_clave"
```

## Usar
1. Primero solo la voz, para escucharla y medir la duración:
   `python3 hacer_video.py roteiro_01.md --solo-voz`
2. Video completo:
   `python3 hacer_video.py roteiro_01.md`
3. Música (opcional): pon un `musica.mp3` libre de derechos junto al guion y vuelve a correr.

Todo sale en `salida/roteiro_01/`:
- `video_final.mp4`: el video para subir.
- `subtitulos.srt`: súbelo aparte en YouTube Studio (Subtítulos → Subir archivo).
- `creditos.txt`: de qué video de Pixabay salió cada clip.

## Cambiar algo
- **Otra voz:** `VOZ=pt-BR-FranciscaNeural python3 hacer_video.py roteiro_01.md` (borra antes `salida/roteiro_01/voz/`).
- **Más lento o rápido:** `VELOCIDAD=-10%` o `VELOCIDAD=+5%`.
- **Un clip feo:** borra `salida/roteiro_01/clips/` y `tramos/`, cambia la búsqueda en `busquedas.json` y vuelve a correr.
- **Editaste el guion:** borra `salida/roteiro_01/voz/` y `tramos/` y vuelve a correr (los clips descargados se reusan).

## Para el video 2
Copia el guion nuevo como `roteiro_02.md` (mismo formato: notas `[IMAGEN: ...]` y texto en portugués) y agrega sus búsquedas en `busquedas.json`.
