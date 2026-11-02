#!/usr/bin/env python3
"""
Guion -> video final para YouTube (Onde Ninguém Pisa).

Qué hace:
  1. Lee el guion (.md exportado del doc). Narra solo el texto en portugués;
     las notas [IMAGEN: ...] definen qué clips van en cada tramo.
  2. Genera la voz con edge-tts (gratis, voz pt-BR).
  3. Busca y descarga clips de Pixabay para cada nota [IMAGEN].
  4. Corta los clips al largo exacto de la narración y los monta en 1080p.
  5. Mezcla música de fondo si hay un musica.mp3 junto al guion.
  6. Genera subtítulos .srt (para subirlos aparte a YouTube) y créditos.

Uso:
    pip install edge-tts requests --break-system-packages   # o en un venv
    export PIXABAY_API_KEY="tu_clave"
    python3 hacer_video.py roteiro_01.md                # video completo
    python3 hacer_video.py roteiro_01.md --solo-voz     # solo voz + duración

Se puede volver a correr: lo que ya se generó se reutiliza. Para rehacer un
paso, borra su carpeta dentro de salida/<guion>/ (voz/, clips/, tramos/).

Variables opcionales:
    VOZ=pt-BR-AntonioNeural   (otra: pt-BR-FranciscaNeural)
    VELOCIDAD=-5%             (más lento: -10%, más rápido: +5%)
"""

import argparse
import asyncio
import json
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(".env")

# ---------------- CONFIGURACIÓN ----------------
VOZ = os.environ.get("VOZ", "pt-BR-AntonioNeural")
VELOCIDAD = os.environ.get("VELOCIDAD", "-5%")
ANCHO, ALTO, FPS = 1920, 1080, 30
CORTE_MAX = 6.0          # segundos máximos de cada clip en pantalla
CORTE_MIN = 2.5          # clips más cortos que esto no se usan
PAUSA_PARRAFO = 0.35     # silencio entre párrafos
PAUSA_NOTA = 1.2         # silencio para [PAUSA]
COLA_FINAL = 8.0         # segundos extra al final para la pantalla final de YouTube
VOLUMEN_MUSICA = 0.10    # 0.0–1.0 relativo a la voz
INICIO_TITULOS = ("gancho",)
FIN_TITULOS = ("verificación", "verificacion", "antes de grabar", "ficha")
BUSQUEDAS_RESPALDO = ["amazon rainforest", "jungle river", "rainforest aerial"]
# ------------------------------------------------


def sh(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("\n[ERROR] " + " ".join(map(str, cmd))[:300])
        print(r.stderr[-1500:])
        sys.exit(1)
    return r.stdout


def duracion(path):
    out = sh(["ffprobe", "-v", "error", "-show_entries", "format=duration",
              "-of", "default=nw=1:nk=1", str(path)])
    return float(out.strip())


# ---------- 1. Leer el guion ----------
def parsear(path):
    lineas = Path(path).read_text(encoding="utf-8").splitlines()
    hay_inicio = any(l.strip().startswith("#") and any(k in l.lower() for k in INICIO_TITULOS)
                     for l in lineas)
    activo = not hay_inicio
    segmentos, actual = [], None
    for raw in lineas:
        l = raw.strip()
        if not l:
            continue
        if l.startswith("#"):
            t = l.lstrip("#").strip().lower()
            if any(k in t for k in INICIO_TITULOS):
                activo = True
            elif any(k in t for k in FIN_TITULOS):
                activo = False
            continue
        if not activo or l.startswith(("|", "- ", "* ", ">")):
            continue
        m = re.match(r"^\[(.*)\]$", l)
        if m:
            nota = m.group(1).strip()
            tipo = nota.split(":", 1)[0].split(".", 1)[0].strip().upper()
            if tipo.startswith("IMAGEN"):
                desc = nota.split(":", 1)[1].strip() if ":" in nota else nota
                actual = {"nota": desc, "items": []}
                segmentos.append(actual)
            elif tipo.startswith("PAUSA") and actual is not None:
                actual["items"].append({"pausa": PAUSA_NOTA})
            continue  # [MÚSICA], [PANTALLA FINAL], etc. no se narran
        texto = re.sub(r"[*_`]", "", l)
        if actual is None:
            actual = {"nota": "", "items": []}
            segmentos.append(actual)
        actual["items"].append({"texto": texto})
    return [s for s in segmentos if any("texto" in i for i in s["items"])]


# ---------- 2. Voz ----------
async def _tts(texto, destino):
    import edge_tts
    com = edge_tts.Communicate(texto, VOZ, rate=VELOCIDAD)
    await com.save(str(destino))


def silencio(seg, destino):
    if not destino.exists():
        sh(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
            "-t", f"{seg:.3f}", "-c:a", "pcm_s16le", str(destino)])
    return destino


def generar_voz(segmentos, carpeta):
    carpeta.mkdir(parents=True, exist_ok=True)
    piezas, t, n = [], 0.0, 0
    sil_p = silencio(PAUSA_PARRAFO, carpeta / "sil_parrafo.wav")
    for s in segmentos:
        s["inicio"] = t
        for item in s["items"]:
            if "pausa" in item:
                f = silencio(item["pausa"], carpeta / f"sil_{item['pausa']}.wav")
                piezas.append(f)
                t += item["pausa"]
                continue
            n += 1
            mp3, wav = carpeta / f"p{n:03d}.mp3", carpeta / f"p{n:03d}.wav"
            if not wav.exists():
                print(f"  voz {n:03d}: {item['texto'][:60]}…")
                asyncio.run(_tts(item["texto"], mp3))
                sh(["ffmpeg", "-y", "-i", str(mp3), "-ar", "44100", "-ac", "1",
                    "-c:a", "pcm_s16le", str(wav)])
            d = duracion(wav)
            item["inicio"], item["fin"] = t, t + d
            piezas += [wav, sil_p]
            t += d + PAUSA_PARRAFO
        s["fin"] = t
    cola = silencio(COLA_FINAL, carpeta / "sil_cola.wav")
    piezas.append(cola)
    segmentos[-1]["fin"] = t + COLA_FINAL
    lista = carpeta / "lista.txt"
    lista.write_text("".join(f"file '{p.resolve()}'\n" for p in piezas), encoding="utf-8")
    narracion = carpeta / "narracion.wav"
    sh(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lista),
        "-c:a", "pcm_s16le", str(narracion)])
    return narracion


# ---------- 3. Clips de Pixabay ----------
def cargar_busquedas(guion_path):
    f = Path(guion_path).with_name("busquedas.json")
    if not f.exists():
        f = Path(__file__).with_name("busquedas.json")
    if f.exists():
        return {k.lower(): v for k, v in json.loads(f.read_text(encoding="utf-8")).items()
                if not k.startswith("_")}
    return {}


def busquedas_para(nota, tabla):
    n = nota.lower()
    for clave, qs in tabla.items():
        if clave in n:
            return qs
    return [nota[:90]] if nota else []


def pixabay(q, key, cache_dir, lang="en"):
    import requests
    cache_dir.mkdir(parents=True, exist_ok=True)
    cf = cache_dir / (re.sub(r"[^a-z0-9]+", "_", f"{lang}_{q.lower()}")[:80] + ".json")
    if cf.exists():
        return json.loads(cf.read_text())
    r = requests.get("https://pixabay.com/api/videos/", timeout=30, params={
        "key": key, "q": q, "lang": lang, "per_page": 20,
        "safesearch": "true", "video_type": "film"})
    if r.status_code != 200:
        print(f"  [aviso] Pixabay {r.status_code} para '{q}': {r.text[:120]}")
        return []
    hits = r.json().get("hits", [])
    cf.write_text(json.dumps(hits))
    return hits


def elegir_archivo(hit):
    v = hit.get("videos", {})
    for calidad in ("large", "medium", "small"):
        f = v.get(calidad) or {}
        if f.get("url") and f.get("width", 0) >= 1280:
            return f["url"]
    for calidad in ("large", "medium", "small", "tiny"):
        if (v.get(calidad) or {}).get("url"):
            return v[calidad]["url"]
    return None


def descargar(url, destino):
    import requests
    if destino.exists() and destino.stat().st_size > 0:
        return destino
    tmp = destino.with_suffix(".part")
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(tmp, "wb") as fh:
            for chunk in r.iter_content(1 << 20):
                fh.write(chunk)
    tmp.rename(destino)
    return destino


def clips_para_segmento(seg, tabla, key, base, usados, creditos):
    """Devuelve lista de (archivo, duración_útil) que cubren la duración del tramo."""
    necesario = seg["fin"] - seg["inicio"]
    elegidos, total = [], 0.0
    consultas = [(q, "en") for q in busquedas_para(seg["nota"], tabla)]
    if seg["nota"]:
        consultas.append((seg["nota"][:90], "es"))
    consultas += [(q, "en") for q in BUSQUEDAS_RESPALDO]
    for q, lang in consultas:
        if total >= necesario:
            break
        for hit in pixabay(q, key, base / "busquedas", lang):
            if total >= necesario:
                break
            if hit["id"] in usados or hit.get("duration", 0) < CORTE_MIN + 1:
                continue
            url = elegir_archivo(hit)
            if not url:
                continue
            archivo = descargar(url, base / "clips" / f"{hit['id']}.mp4")
            usados.add(hit["id"])
            elegidos.append((archivo, duracion(archivo)))
            total += min(duracion(archivo) - 0.4, CORTE_MAX)
            creditos.append(f"{hit['id']}\t{hit.get('user', '')}\t{hit.get('pageURL', '')}")
    if not elegidos:
        print(f"  [ERROR] Sin clips para: {seg['nota'][:60]}")
        sys.exit(1)
    return elegidos


# ---------- 4. Montaje ----------
def cortar(origen, inicio, largo, destino):
    vf = (f"scale={ANCHO}:{ALTO}:force_original_aspect_ratio=increase,"
          f"crop={ANCHO}:{ALTO},fps={FPS},format=yuv420p,setsar=1")
    sh(["ffmpeg", "-y", "-ss", f"{inicio:.2f}", "-i", str(origen), "-t", f"{largo:.3f}",
        "-an", "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
        "-r", str(FPS), str(destino)])


def montar_tramo(i, seg, clips, carpeta):
    """Cubre exactamente la duración del tramo; mide cada pieza real para no desfasarse."""
    necesario = seg["fin"] - seg["inicio"]
    piezas, t, k = [], 0.0, 0
    while t < necesario - 0.02:
        archivo, dur_clip = clips[k % len(clips)]
        vuelta = k // len(clips)          # si faltan clips, se reusan desde otro punto
        rango = max(dur_clip - CORTE_MIN - 0.4, 0.1)
        inicio = 0.3 + (vuelta * 1.7) % rango
        disponible = dur_clip - inicio - 0.1
        restante = necesario - t
        largo = min(CORTE_MAX, disponible, restante)
        if 0 < restante - largo < 0.6 and disponible >= restante:
            largo = restante              # absorbe un resto muy corto
        destino = carpeta / f"t{i:02d}_{k:02d}.mp4"
        if not destino.exists():
            cortar(archivo, inicio, largo, destino)
        piezas.append(destino)
        t += duracion(destino)
        k += 1
        if k > 400:
            sys.exit(f"[ERROR] Tramo {i + 1}: no logro cubrir su duración con los clips")
    return piezas


def subtitulos(segmentos, destino):
    def fmt(s):
        h, r = divmod(max(s, 0), 3600)
        m, r = divmod(r, 60)
        return f"{int(h):02d}:{int(m):02d}:{int(r):02d},{int((r % 1) * 1000):03d}"

    def trozos(texto):
        frases = re.split(r"(?<=[.!?…:])\s+", texto)
        out = []
        for f in frases:
            while len(f) > 84:
                corte = f.rfind(", ", 0, 84)
                corte = corte + 1 if corte > 30 else f.rfind(" ", 0, 84)
                out.append(f[:corte].strip())
                f = f[corte:].strip()
            if f:
                out.append(f)
        return out

    n, lineas = 0, []
    for s in segmentos:
        for it in s["items"]:
            if "texto" not in it:
                continue
            partes = trozos(it["texto"])
            total = sum(len(p) for p in partes)
            t = it["inicio"]
            for p in partes:
                d = (it["fin"] - it["inicio"]) * len(p) / total
                n += 1
                lineas.append(f"{n}\n{fmt(t)} --> {fmt(t + d)}\n{p}\n")
                t += d
    destino.write_text("\n".join(lineas), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("guion")
    ap.add_argument("--solo-voz", action="store_true", help="genera solo la narración y muestra la duración")
    args = ap.parse_args()

    for b in ("ffmpeg", "ffprobe"):
        if not shutil.which(b):
            sys.exit(f"Falta {b}. Instálalo (ej: sudo apt install ffmpeg).")

    guion = Path(args.guion)
    base = Path("salida") / guion.stem
    base.mkdir(parents=True, exist_ok=True)

    segmentos = parsear(guion)
    n_par = sum(1 for s in segmentos for i in s["items"] if "texto" in i)
    print(f"Guion: {len(segmentos)} tramos de imagen, {n_par} párrafos narrados.")

    print("1/4 Generando voz…")
    narracion = generar_voz(segmentos, base / "voz")
    dur = duracion(narracion)
    print(f"    Duración total: {dur / 60:.1f} min ({dur:.0f} s)")
    if args.solo_voz:
        print(f"Listo. Escucha {narracion}")
        return

    key = os.environ.get("PIXABAY_API_KEY")
    if not key:
        sys.exit("Falta PIXABAY_API_KEY (export PIXABAY_API_KEY=...)")

    print("2/4 Buscando y descargando clips…")
    tabla = cargar_busquedas(guion)
    usados, creditos, plan = set(), [], []
    for i, s in enumerate(segmentos):
        print(f"  tramo {i + 1}/{len(segmentos)} ({s['fin'] - s['inicio']:.0f} s): {s['nota'][:55]}")
        plan.append(clips_para_segmento(s, tabla, key, base, usados, creditos))

    print("3/4 Cortando y montando…")
    (base / "tramos").mkdir(exist_ok=True)
    todas = []
    for i, (s, clips) in enumerate(zip(segmentos, plan)):
        todas += montar_tramo(i, s, clips, base / "tramos")
    lista = base / "tramos" / "lista.txt"
    lista.write_text("".join(f"file '{p.resolve()}'\n" for p in todas), encoding="utf-8")
    video_mudo = base / "video_sin_audio.mp4"
    sh(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lista), "-c", "copy", str(video_mudo)])

    print("4/4 Mezclando audio…")
    final = base / "video_final.mp4"
    musica = guion.with_name("musica.mp3")
    if musica.exists():
        sh(["ffmpeg", "-y", "-i", str(video_mudo), "-i", str(narracion),
            "-stream_loop", "-1", "-i", str(musica),
            "-filter_complex",
            f"[2:a]volume={VOLUMEN_MUSICA}[m];[1:a][m]amix=inputs=2:duration=first:normalize=0[a]",
            "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-t", f"{dur:.2f}", str(final)])
    else:
        print("    (sin musica.mp3: el video sale solo con voz)")
        sh(["ffmpeg", "-y", "-i", str(video_mudo), "-i", str(narracion),
            "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-t", f"{dur:.2f}", str(final)])

    subtitulos(segmentos, base / "subtitulos.srt")
    (base / "creditos.txt").write_text("id\tautor\tpagina\n" + "\n".join(creditos), encoding="utf-8")

    print(f"\nListo: {final}  ({duracion(final) / 60:.1f} min)")
    print(f"Subtítulos: {base / 'subtitulos.srt'}  (súbelos aparte en YouTube Studio)")
    print(f"Créditos de clips: {base / 'creditos.txt'}")


if __name__ == "__main__":
    main()
