# Kit d'installation Conway Automaton (test bridé à 10 €)

Installe l'agent [Conway-Research/automaton](https://github.com/Conway-Research/automaton)
sur un petit VPS Ubuntu 24.04 (par ex. Hetzner, ~5 €/mois), à la version auditée
`d8f8168`.

## Contenu

| Fichier | Rôle |
|---|---|
| `install.sh` | Installe Node, crée l'utilisateur `automaton` sans droits admin, pare-feu, compile, lance les tests, crée le service (sans le démarrer) |
| `security-overrides.patch` | Force des versions corrigées des dépendances (20 failles sur 22 corrigées, dont les 2 critiques de `simple-git`) |
| `replication-lock.patch` | Corrige un défaut : la limite `maxChildren` était ignorée (toujours 3). Ajoute un verrou `AUTOMATON_DISABLE_REPLICATION=1` |
| `local-mode.patch` | **Mode local** : fait tourner l'agent sans Conway Cloud (fermé, plus de nouveaux comptes). Budget tenu par le créateur, IA via Anthropic (Claude Haiku 5.5), messages créateur ↔ agent en local, outils Conway et auto-modification du code désactivés |
| `update-local.sh` | Installe le mode local : code dans `/opt/automaton` (lecture seule pour l'agent), budget dans `/var/lib/automaton-creator`, clé Anthropic dans `/etc/automaton/secrets.env`, commande `luna` |
| `apply-limits.sh` | Plafonds de dépense du test : 1 $ par transfert, 3 $/jour max, 3 $/jour d'IA max, 0 enfant |

## Utilisation

```bash
# sur le VPS, en root
git clone -b claude/pensive-edison-4aoaqy https://github.com/pilou31/boutonLuna.git
cd boutonLuna/automaton-deploy
sudo bash install.sh
```

Puis suivre les 4 étapes affichées à la fin.

## Passer en mode local (Conway Cloud est fermé)

Après `install.sh` et l'étape `--setup` :

```bash
cd automaton-deploy && bash update-local.sh   # demande la clé Anthropic (masquée)
luna fund 10                                   # budget = ce que tu as mis chez Anthropic
luna say "Voici des idées de business : ..."
systemctl enable --now automaton
```

Commandes : `luna status`, `luna outbox`, `luna revenue 15 "vente X"`, `luna expense 3 "nom de domaine"`,
`journalctl -u automaton -f`, arrêt d'urgence `systemctl stop automaton`.

Le solde affiché par `luna status` est une estimation prudente (arrondi au centime supérieur par appel).
La vraie limite est le **plafond de dépense mensuel réglé dans la console Anthropic**.

## Règles du test

- Ne verser **jamais plus de 10 €** sur le portefeuille de l'agent.
- Ne relier **aucun** compte personnel (banque, PayPal, e-mail).
- Réplication bloquée tant que la règle « 100 € nets encaissés » n'est pas codée et testée.
- La constitution de l'agent (pas de fraude, pas de spam, pas de tromperie) reste en place.
- Arrêt d'urgence : `sudo systemctl stop automaton`.

## Risques restants

- 2 failles `ws` (via `@solana/web3.js`) non corrigeables sans toucher à la partie Solana.
- L'agent a un terminal et Internet : aucun audit ne garantit une sécurité absolue.
- Les clés du portefeuille sont dans `/home/automaton/.automaton/wallet.json` : à sauvegarder hors du serveur.
