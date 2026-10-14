# luna sur Hermes — mode local, réglage C

Fait tourner l'agent **luna** sur [Hermes Agent](https://github.com/NousResearch/hermes-agent)
(Nous Research, MIT), avec les garde-fous décidés avec Pierre.

## Les 3 pièces

| Pièce | Rôle |
|---|---|
| `guard/luna_guard.py` | **Gardien.** Seul détenteur de la clé Anthropic. Chaque agent l'appelle avec un jeton opaque. Il facture chaque appel, tient le **budget commun (20 €)**, bloque au dépassement, limite à **3 copies** (codé en dur), tient le registre (vie = budget + ventes − dépenses − coût IA) et porte le **verrou d'arrêt général**. Bibliothèque standard seulement. |
| `plugin/luna-rules/` | **Plugin Hermes.** Injecte les interdits dans le prompt et, avant chaque outil : bloque l'accès aux autres projets et au trading ; demande ta validation Telegram pour écrire à une personne, agir dans un site lié à tes comptes, ou payer. Le reste est autonome. |
| `deploy/` | `install-hermes.sh` (installe tout), `luna` (commande de pilotage), services systemd. |

## Réglage C (autonomie bornée)

- **Autonome, sans rien demander :** travail interne (chercher, coder, tester, rédiger),
  publier son propre travail sous sa propre identité, dépenser < 2 € par action.
- **Validation Telegram avant :** écrire à une vraie personne, agir dans un site lié à tes
  comptes, tout paiement.
- **Toujours bloqué :** faux avis, usurpation, spam, promesses de gains, contenu adulte,
  trading avec ton argent, accès aux autres projets du serveur.

La vraie garantie n'est pas le filtre de mots, c'est que l'agent **n'a aucun identifiant** de
tes comptes ni moyen de paiement, et que le budget est plafonné côté gardien.

## Installation (VPS Ubuntu 24.04, en root)

```bash
cd hermes/deploy && sudo bash install-hermes.sh   # demande la clé Anthropic
luna fund 20                                       # budget = ce que tu as mis chez Anthropic
luna gateway                                       # connecter Telegram (limiter à ton ID)
luna start                                         # démarrer l'agent principal luna-0
```

Pilotage : `luna status`, `luna copy` (max 3), `luna stop-all`, `luna resume`,
`journalctl -u hermes@luna-0 -f`.

## Apprentissage

Hermes apprend nativement : il s'écrit des compétences après une tâche réussie, garde une
mémoire et s'améliore de session en session. Activé via `skills.autonomous_creation`.

## Isolation de tes autres projets

Utilisateur `hermes` sans sudo ; service durci (`ProtectHome`, `ProtectSystem=strict`,
`NoNewPrivileges`) ; config et plugin en lecture seule (root) ; les autres dossiers de
`/home` et `/root` passés en `700`. **Recommandation :** ne pas mettre le bot de trading et
l'agent sur la même machine ; à défaut, vérifier que les clés Tradovate sont en `600`.

## Modules de contenu (à brancher, API officielles, comptes à toi)

À ajouter au fur et à mesure — chacun publie sur **un** compte réel que tu possèdes, jamais
de création de comptes en série :

- **Pinterest** (API officielle) — demandé, à intégrer.
- **YouTube comptines** (API officielle) — en attente de ton tuto.
- **Séries IA** — contenu original généré, publié sur tes chaînes.

Chaque module demande : que tu crées le compte une fois, une app développeur chez la
plateforme, et un jeton rangé dans le `.env` (jamais dans le dépôt).

## Tests

`cd hermes && python3 -m unittest tests.test_guard tests.test_rules` — 18 tests
(gardien : budget, plafond de copies, arrêt ; règles : interdits, validations, blocages).
