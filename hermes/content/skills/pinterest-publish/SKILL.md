---
name: pinterest-publish
description: >-
  Publier une épingle sur le compte Pinterest de Pierre via l'API officielle.
  Utilise cette compétence quand tu veux publier un visuel que TU as créé
  (comptine, série, contenu original) sur Pinterest. La publication de ton
  propre contenu est autonome ; tu n'as pas besoin de demander l'accord de Pierre.
---

# pinterest-publish

Publie du contenu **original que tu as créé** sur le compte Pinterest de Pierre.
Compte réel, API officielle, jamais de création de compte.

## Prérequis (déjà fait par Pierre)

Le compte est connecté : `python3 ~/content/pinterest.py boards` liste des tableaux.
Si ça répond « non connecté », préviens Pierre : c'est à lui de lancer `connect`.

## Étapes

1. Prépare un **visuel** (image carrée ou verticale) et héberge-le à une URL
   publique que tu possèdes, ou génère-le puis publie-le sur ton propre espace.
   Pinterest a besoin d'une `image_url` accessible.
2. Liste les tableaux pour choisir la bonne destination :
   ```
   python3 ~/content/pinterest.py boards
   ```
3. Vérifie d'abord sans publier (`--dry-run`), relis le résultat :
   ```
   python3 ~/content/pinterest.py pin --board <ID> --image-url <URL> \
     --title "Titre court" --description "Description utile" --link <URL optionnelle> --dry-run
   ```
4. Si tout est correct, publie en retirant `--dry-run`.

## Règles

- Contenu **original** uniquement : pas de copie, pas d'image d'un tiers sans droit.
- Titre clair, description honnête : **pas** de promesses de gains, pas de faux avis,
  pas de mots-trompeurs. Respecte les règles de ton créateur.
- Une épingle à la fois, pas de rafale : Pinterest bannit le spam.
- Après publication, note dans ta mémoire ce qui marche (sujets, formats) pour
  t'améliorer.
