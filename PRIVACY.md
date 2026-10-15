# Politique de confidentialité — Luna Publisher

_Dernière mise à jour : 15 octobre 2026_

## Qui

Luna Publisher est une application personnelle, à usage unique, exploitée par
le propriétaire du compte. Elle n'a aucun utilisateur tiers : elle agit
uniquement sur le compte Pinterest de son propriétaire.

## Ce que l'application fait

Luna Publisher utilise l'API officielle Pinterest (v5) pour **publier des
épingles de contenu original** (visuels créés par le propriétaire) sur le
compte Pinterest du propriétaire, et pour **lire la liste de ses propres
tableaux** afin de choisir la destination d'une publication.

## Données utilisées

- **Jeton d'accès OAuth Pinterest** : stocké localement sur le serveur du
  propriétaire, dans un fichier privé (permissions `600`), jamais publié ni
  partagé. Il sert uniquement à s'authentifier auprès de l'API Pinterest.
- **Identifiants des tableaux et des épingles** du propriétaire : lus pour
  publier, non conservés au-delà de l'opération.

L'application **ne collecte, ne stocke et ne transmet aucune donnée
d'autres personnes**. Elle ne lit pas les données d'autres utilisateurs
Pinterest. Elle ne vend ni ne partage aucune donnée avec des tiers.

## Portée (scopes) demandée

`boards:read`, `boards:write`, `pins:read`, `pins:write`,
`user_accounts:read` — le strict nécessaire pour lister ses tableaux et
publier ses propres épingles.

## Conservation et suppression

Les jetons restent sur le serveur du propriétaire tant que l'application est
utilisée. Le propriétaire peut révoquer l'accès à tout moment depuis les
paramètres de son compte Pinterest (Applications connectées) et supprimer le
fichier de jetons local, ce qui met fin à tout accès.

## Contact

Pour toute question relative à cette politique, contacter le propriétaire du
dépôt via la page GitHub du projet :
https://github.com/pilou31/luna-agent
