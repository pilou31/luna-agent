# Pack comptine #1 — « Luna, la petite étoile »

Comptine **originale** (paroles + musique + images créées par nous → aucun souci de droits).
Public : tout-petits (0-5 ans). Durée visée : ~1 min 30.

---

## 1) Paroles (à chanter, douces, répétitives)

**Couplet 1**
Luna, Luna, petite étoile,
Tout là-haut tu brilles dans le noir.
Luna, Luna, petite étoile,
Tu éclaires le ciel du soir.

**Refrain**
Brille, brille, petite Luna,
La nuit est douce autour de toi.
Brille, brille, petite Luna,
Dors bien, le monde est à toi.

**Couplet 2**
La lune ronde te fait un lit,
Les nuages passent tout doux.
Les p'tits oiseaux se sont endormis,
Et la Terre rêve avec nous.

**Refrain** (×1)

**Couplet 3**
Ferme les yeux, mon tout-petit,
Luna veille jusqu'au matin.
Demain le soleil dira « bonjour »,
Et Luna dira « à bientôt ».

**Refrain** (×1, puis tout doux pour finir)

---

## 2) Prompts d'images (5 scènes) — pour FLUX.1 schnell / SDXL / Qwen-Image

> Style commun à coller à chaque prompt (garde le MÊME style pour la cohérence) :
> `soft pastel children's book illustration, cute, cozy, rounded shapes, warm soft lighting, gentle, high quality, no text`

1. **Titre** : `a tiny smiling star named Luna with a cute face, floating in a deep blue night sky full of small sparkles, big crescent moon, soft pastel children's book illustration, cute, cozy, warm glow, no text`

2. **La ville qui dort** : `a small peaceful sleeping town at night seen from above, little houses with warm yellow windows, stars in the sky, a glowing little star watching over, soft pastel children's book illustration, cozy, no text`

3. **Le lit de nuages** : `a cute little star resting on a fluffy cloud like a bed, round moon beside it, calm night sky, very gentle and dreamy, soft pastel children's book illustration, cozy, no text`

4. **Les animaux endormis** : `cute baby animals sleeping peacefully under the stars, a little bird in a nest, a bunny, soft moonlight, a small glowing star above, soft pastel children's book illustration, cozy, no text`

5. **Vers le matin** : `a gentle night sky turning softly into dawn, pale pink and orange light at the horizon, the little star Luna waving goodbye, a sleepy sun rising, soft pastel children's book illustration, cozy, no text`

> Astuce : génère chaque image en **16:9 / 1920x1080** si l'option existe, sinon carré — le montage recadrera.

---

## 3) Prompt musique — pour MusicGen (facebook/MusicGen, licence MIT = usage commercial OK)

```
gentle soft lullaby for babies, slow tempo, music box and soft piano, warm and calm,
dreamy, soothing, in a major key, instrumental, no drums
```

Durée : règle sur **90 secondes** (ou le max du Space, puis on bouclera au montage si besoin).

> ⚠️ **N'utilise pas Suno** pour la version monétisée (licence gratuite = non-commercial). MusicGen est bon et libre pour le commerce.

---

## 4) Métadonnées YouTube

- **Titre** : `Luna, la petite étoile 🌙 Comptine douce pour s'endormir | Berceuse bébé`
- **Description** :
```
🌙 « Luna, la petite étoile » — une comptine douce et originale pour aider bébé à s'endormir.
Une berceuse calme avec de jolies illustrations pour un moment tendre avant la nuit. 💫

Bonne nuit à tous les petits ✨
#comptine #berceuse #bebe

Comptine, musique et illustrations originales © Luna Comptines.
```
- **Tags** : `comptine, berceuse, comptine bébé, berceuse bébé, musique douce bébé, pour s'endormir, comptine douce, dodo bébé, nursery rhyme français, étoile`
- **Catégorie** : `Music` (ou `Education`)
- **Public** : ⚠️ **réservé aux enfants** (`--made-for-kids`)
- **Confidentialité** : commence en `private` ou `unlisted` pour validation, puis `public`.

---

## 5) Où déposer les fichiers sur le serveur

```
~/work/comptine1/
  ├── 1.png   2.png   3.png   4.png   5.png   (les 5 images, dans l'ordre)
  └── luna.mp3   (ou luna.wav / luna.m4a — la musique)
```

## 6) Commandes (serveur, utilisateur hermes)

```bash
# Montage
python3 ~/content/montage.py --images-dir ~/work/comptine1 \
  --audio ~/work/comptine1/luna.mp3 --out ~/work/comptine1/luna.mp4

# Publication (dry-run d'abord pour vérifier, puis sans --dry-run)
python3 ~/content/youtube.py upload --file ~/work/comptine1/luna.mp4 \
  --title "Luna, la petite étoile 🌙 Comptine douce pour s'endormir | Berceuse bébé" \
  --description "$(cat ~/work/comptine1/description.txt)" \
  --tags "comptine,berceuse,comptine bébé,berceuse bébé,pour s'endormir,dodo bébé,étoile" \
  --category 10 --privacy unlisted --made-for-kids --dry-run
```
