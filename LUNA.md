# luna-agent

Agent autonome **luna-1** de Pierre, basé sur
[Conway Automaton](https://github.com/Conway-Research/automaton) (licence MIT, voir `LICENSE`).

Conway Cloud a fermé (fin de bêta, plus de nouveaux comptes) : cette version tourne en
**mode local** sur un VPS, avec l'IA d'Anthropic et un budget tenu par le créateur.

## Ce qui change par rapport à l'original

| Domaine | Changement |
|---|---|
| Sécurité des dépendances | Versions corrigées forcées (20 failles sur 22, dont les 2 critiques de `simple-git`) |
| Réplication | `maxChildren` était ignoré (toujours 3) ; verrou `AUTOMATON_DISABLE_REPLICATION=1` |
| Mode local (`src/local/`) | Crédits = registre du créateur (`/var/lib/automaton-creator/ledger.json`, en lecture seule pour l'agent) moins le coût d'IA ; messages créateur ↔ agent en fichiers locaux ; commande `luna` |
| IA | Claude Haiku 5.5 via l'API Anthropic, réflexion désactivée, effort `low`, recherche web optionnelle |
| Outils | Outils Conway, transferts, réplication et auto-modification du code désactivés en mode local |
| Correctifs | Résultats d'outils correctement appariés pour Anthropic ; conversation toujours valide au réveil |

Tests : `src/__tests__/local-mode.test.ts` (13 tests).

## Déploiement

Le dossier `deploy/` contient le kit pour un VPS Ubuntu 24.04 :

1. `install.sh` puis l'étape `--setup` (voir `deploy/LISEZMOI.md`)
2. `update-local.sh` : installe le mode local (code dans `/opt/automaton`, clé Anthropic dans `/etc/automaton/secrets.env`)

Note : `update-local.sh` reconstruit le code depuis le dépôt Conway d'origine + les patchs de `deploy/`.

## Commandes du créateur (sur le serveur)

```
luna status                  # solde, coûts, bénéfice net
luna fund <euros> [note]     # ajouter du budget
luna revenue <euros> [note]  # vente réellement encaissée
luna expense <euros> [note]  # dépense business
luna say "message"           # écrire à l'agent
luna outbox [n]              # lire ses messages
journalctl -u automaton -f   # journal en direct
systemctl stop automaton     # arrêt d'urgence
```

## Règles

- La constitution de l'agent (pas de fraude, pas de spam, pas de tromperie) reste en place.
- Toute publication, création de compte, prise de contact ou dépense passe par l'accord du créateur.
- Ne jamais committer de clé API ni le fichier `wallet.json`.
