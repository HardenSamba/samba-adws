# Positionnement du service ADWS dans l'écosystème Active Directory

## Le trou fonctionnel que ce projet comble

Un contrôleur de domaine Samba AD expose nativement les quatre piliers d'un
domaine Active Directory : **LDAP** (389/tcp, 636/tcp, 3268/tcp pour le
catalogue global), **Kerberos** (88/tcp+udp), **SMB** (445/tcp, pour SYSVOL et
les stratégies de groupe) et **DNS** (53/tcp+udp, avec les enregistrements SRV
`_ldap._tcp.dc._msdcs.<domaine>`). Il n'expose **pas** les *Active Directory Web
Services* — le service Microsoft qui écoute sur **9389/tcp**.

Cette absence n'est pas un détail cosmétique. Elle rend inutilisables, en bloc,
les outils d'administration Microsoft les plus courants :

- le module PowerShell **`ActiveDirectory`** (`Microsoft.ActiveDirectory.Management`,
 livré par RSAT), c'est-à-dire l'intégralité des cmdlets `*-AD*` ;
- la console **ADAC** (`dsac.exe`, *Active Directory Administrative Center*), qui
 n'est qu'une interface graphique posée sur le même module ;
- tout script tiers construit sur ce namespace .NET.

Le symptôme canonique, documenté dans `documentation/01-architecture.md:8` et
repris dans `documentation/06-depannage.md` §7, est le suivant :

```text
Get-ADUser : Unable to find a default server with Active Directory Web
Services running
```

## Pourquoi le module PowerShell ne parle pas LDAP

Il est tentant de croire que les cmdlets `Get-ADUser` et consorts émettent du
LDAP, puisque l'annuaire est un annuaire LDAP. **Ce n'est pas le cas.** Le
module `ActiveDirectory` est un client **WS-\*** : il construit des enveloppes
SOAP 1.2, les encode en XML binaire WCF, les transporte sur `net.tcp` et les
adresse au service ADWS. C'est ADWS qui, **côté serveur**, retraduit ces
requêtes en opérations LDAP (`ldap_bind`, `ldap_search_ext`, `ldap_add`,
`ldap_modify`) contre l'instance d'annuaire locale.

La configuration de référence du service Microsoft confirme cette architecture en
deux temps. Elle documente un **pool de
connexions LDAP** interne au service (`MaxPoolConnections = 10`,
`MaxConnectionsPerUser = 5`, `MaxPercentageReservedConnections = 50`), maintenu
« séparément pour chaque instance d'annuaire » — AD DS, catalogue global,
instances AD LDS, et l'outil de montage de base de données AD. ADWS est donc,
littéralement, une **passerelle WS-\* → LDAP** multi-instances.

La conséquence pratique est double :

- **1.** Une console qui parle LDAP directement, comme **ADUC** (`dsa.msc`),
 fonctionne contre Samba **sans ADWS**. C'est la recommandation explicite du
 projet (`README.md`, section « Console graphique »).
- **2.** Une console ou un module qui ne parle **que** ADWS n'a aucun chemin de
 repli. Sans les 9389/tcp, il ne fonctionne pas — d'où ce projet.

## Ce que couvre exactement cette implémentation

Ce dépôt réimplémente en Python, du côté Linux, le protocole servi par
`Microsoft.ActiveDirectory.WebServices.exe`, de la trame TCP jusqu'à l'appel
`samba.samdb`. Le point d'entrée unique est `python3 -m src.main`
(`src/main.py:9`), qui construit la configuration, enregistre les types de
records NMF et démarre le serveur (`src/main.py:15-17`).

Trois niveaux de lecture doivent être tenus séparés dans tout ce chapitre, et
le seront systématiquement :

| Niveau | Source de vérité | Statut |
|---|---|---|
| Spécification | Microsoft Open Specifications, RFC | Normatif |
| Client Windows réel | Comportement observé sur le réseau | Descriptif |
| Cette implémentation | Code de `src/` et `classes/` | Ce qui tourne |

## Ce que ce service n'est pas

ADWS n'est **pas** un service d'authentification : il ne délivre pas de tickets
et ne remplace pas le KDC. Il n'est pas non plus un service de réplication : la
réplication reste du ressort de `[MS-DRSR]` entre DC. Enfin, il ne se substitue
pas à LDAP : sur un DC Microsoft comme sur ce projet, LDAP reste le canal
d'accès réel à l'annuaire ; ADWS n'en est qu'un habillage réseau.

# Acteurs, points de terminaison et topologie réseau

## Les acteurs d'une session

| Acteur | Rôle | Emplacement |
|---|---|---|
| Module `ActiveDirectory` | Client WS-* (cmdlets `*-AD*`) | Poste Windows |
| ADAC `dsac.exe` | Client graphique, même pile | Poste Windows |
| KDC Samba | Délivre le ticket de service | DC Samba, 88 |
| Service ADWS souverain | Serveur `net.tcp` 9389 | DC Samba |
| `sam.ldb` via `python3-samba` | Annuaire réel | DC Samba, local |

Le service ADWS de ce projet est **co-localisé** avec l'annuaire : il n'ouvre
pas de connexion LDAP réseau vers 389/tcp, il ouvre un `SamDB` **local** sur les
fichiers LDB (`classes/directory/samba_db.py:23-28`). C'est une divergence
d'architecture assumée par rapport à l'ADWS Microsoft, qui passe par un pool
LDAP même en local. Elle a une conséquence directe sur l'identité de l'appelant,
détaillée plus loin.

## Les points de terminaison réels de l'ADWS Microsoft

Le service Microsoft publie ses endpoints WCF.
L’adresse de base est construite ainsi : préfixe `net.tcp://`, suffixe
`:9389/ActiveDirectoryWebServices`. À cette base s'ajoutent un **préfixe de
binding** (`Windows/` ou `UserName/`) puis le nom
d'endpoint.

| Endpoint | Contrat WCF | Constante |
|---|---|---|
| `Windows/Resource` | `IResource` | `WcfResourceEndpoint` |
| `Windows/ResourceFactory` | `IResourceFactory` | `WcfResourceFactoryEndpoint` |
| `Windows/Enumeration` | `IEnumeration` | `WcfEnumEndpoint` |
| `Windows/AccountManagement` | `IActiveDirectoryAccountManagement` | `WcfAcctMgmtEndpoint` |
| `Windows/TopologyManagement` | `IActiveDirectoryTopologyManagementV1` | `WcfTopoMgmtEndpoint` |

Deux compléments importants, souvent omis :

- Le même quintuplet est **dupliqué** sous le préfixe `UserName/`
, mais **seulement si** un certificat serveur a pu
 être provisionné (`ProvisionCertificate`). Ce chemin correspond au binding
 `TransportWithMessageCredential`, c'est-à-dire
 une authentification par nom d'utilisateur/mot de passe portée dans le
 message. **Ce projet n'implémente pas le préfixe `UserName/`** ; il n'accepte
 que Kerberos via GSSAPI.
- Un sixième endpoint, `mex`, publie les métadonnées
 WS-MetadataExchange. Il est exposé sans préfixe de binding et sa politique
 HTTP GET est désactivée (`HttpGetEnabled = false`). **Non implémenté ici.**

L'URL complète vue sur le fil pour une lecture d'objet est donc :

```text
net.tcp://dc.samba.local:9389/ActiveDirectoryWebServices/Windows/Resource
```

## Ce que ce projet expose réellement : un endpoint unique de fait

Le serveur Python n'implémente **aucun démultiplexage par endpoint**. Il ouvre
une socket TCP unique sur `0.0.0.0:9389` (`classes/server/config.py:15-16`,
`classes/server/server.py:25-32`) et traite chaque connexion de manière
identique quel que soit l'URI demandé.

La démonstration tient en trois observations vérifiables :

- **1.** Le `ViaRecord` du préambule (code `0x02`) est **lu et journalisé, jamais
 comparé** : `classes/server/protocol.py:45-46` se contente d'écrire
 `[PREAMBLE]... ViaRecord received from client`. Aucune extraction de chemin,
 aucune table d'endpoints.
- **2.** L'en-tête WS-Addressing `<a:To>` n'est **pas extrait** par le parseur de
 requête : `RequestContext.from_xml` (`classes/parsing/context.py:37-169`)
 récupère `a:Action` (ligne 55), `a:MessageID` (60),
 `ad:objectReferenceProperty` (64), le marqueur IMDA
 `da:IdentityManagementOperation` / `da:BaseObjectSearchRequest` (66-69), les
 éléments `wsen:Enumerate` / `wsen:Pull` / `wsen:Release` (92, 129, 145) et les
 `adlq:BaseObject` / `adlq:Filter` / `adlq:Scope` (95, 99, 104) — mais jamais
 `a:To` ni `a:Via`. Aucun des sept préfixes déclarés dans la table `ns`
 (`context.py:44-52` : `soap`, `soap11`, `a`, `ad`, `da`, `wsen`, `adlq`) ne
 sert à lire une adresse de destination.
- **3.** Le seul usage de `<a:To>` dans tout le dépôt est cosmétique : le
 handler de création le relit **par expression régulière** dans le XML brut
 pour fabriquer l'adresse de l'EPR `ResourceCreated`, en substituant
 `ResourceFactory` par `Resource` (`classes/handlers/create.py:75-77`). Si
 l'en-tête est absent, il retombe sur l'adresse anonyme WS-Addressing.

**Le routage est donc intégralement porté par `<a:Action>`**, via
`HandlerRegistry.resolve` (`classes/handlers/handler_registry.py:15-23`) :

- correspondance **exacte, insensible à la casse**, dans la table
 `ACTION_HANDLER_KEYS` (`src/handlers/handler_routing.py:35-51`, 14 entrées) :
 l'URI reçue est passée en minuscules (`normalized = action_url.lower`,
 `handler_registry.py:18`) et les 14 clés de la table sont écrites en
 minuscules ;
- à défaut, correspondance sur le **dernier segment** de l'URI d'action
 (`action_url.rsplit("/", 1)[-1]`, `handler_registry.py:22`) dans
 `HANDLER_FACTORIES` (`src/handlers/handler_routing.py:53-71`, 29 entrées).
 Ce second chemin est **sensible à la casse** : aucun `lower` n'est appliqué,
 le suffixe doit être exactement `GetADDomain`, `SetPassword`, etc.

Le rapport entre les deux tables mérite d'être explicité : sur les 29 clés de
`HANDLER_FACTORIES`, **14 seulement** sont atteignables par la table exacte ;
les **15 autres** — toutes les actions `CustomActions` plus `Search`, `Schema`
et `Groups` — ne sont joignables que par le suffixe.

> La table exacte n'est pas un doublon du routage par suffixe : elle **désambiguïse**
> les collisions de dernier segment. `.../ws/2004/09/enumeration/Renew` et
> `.../ws/2004/08/eventing/Renew` finissent tous deux par `Renew`, de même que les
> deux `GetStatus`. Sans la table exacte, WS-Eventing serait routé vers les
> handlers WS-Enumeration.

Conséquence opérationnelle, à énoncer clairement : **un client qui adresserait
`.../Windows/TopologyManagement` mais enverrait une action WS-Transfer `Get`
serait servi normalement par ce serveur**, là où l'ADWS Microsoft rejetterait
la requête au niveau du dispatcher WCF (contrat `IActiveDirectoryTopologyManagementV1`
n'exposant pas cette opération). C'est une **permissivité** de l'implémentation,
pas une conformité.

## Correspondance endpoint → actions SOAP supportées

Le tableau ci-dessous rétablit, pour la documentation, la répartition
**logique** des actions par endpoint Microsoft, et indique le handler qui les
sert dans ce projet. La colonne « endpoint » est celle qu'utilise le client
Windows ; elle n'a, encore une fois, **aucun effet** sur le routage serveur ici.

| Endpoint Windows | Action SOAP (suffixe) | Handler du projet |
|---|---|---|
| `Resource` | `transfer/Get` | `get.py` — `GetHandler` |
| `Resource` | `transfer/Put` | `transfer.py` → `modify.py` |
| `Resource` | `transfer/Delete` | `transfer.py` → `delete.py` |
| `ResourceFactory` | `transfer/Create` | `crud.py` → `create.py` |
| `Enumeration` | `enumeration/Enumerate` | `enumerate.py` |
| `Enumeration` | `enumeration/Pull` | `pull.py` |
| `Enumeration` | `enumeration/Release` | `release.py` |
| `Enumeration` | `enumeration/Renew` | `renew.py` |
| `Enumeration` | `enumeration/GetStatus` | `get_status.py` |
| `AccountManagement` | `.../AccountManagement/SetPassword` | `set_password.py` |
| `AccountManagement` | `.../AccountManagement/ChangePassword` | `change_password.py` |
| `AccountManagement` | `.../AccountManagement/TranslateName` | `translate_name.py` |
| `AccountManagement` | `.../GetADGroupMember` | `get_ad_group_member.py` |
| `AccountManagement` | `.../GetADPrincipalGroupMembership` | `get_ad_principal_group_membership.py` |
| `AccountManagement` | `.../GetADPrincipalAuthorizationGroup` | `get_ad_principal_authorization_group.py` |
| `AccountManagement` | `.../AccountManagement/Notify` | `notify.py` |
| `Resource` | ajout/retrait de membre = `transfer/Put` | `transfer.py` → `modify.py` |
| `TopologyManagement` | `.../GetADDomain` | `get_ad_domain.py` |
| `TopologyManagement` | `.../GetADDomainController` | `get_ad_domain_controller.py` |
| `TopologyManagement` | `.../GetADForest` | `get_ad_forest.py` |
| `TopologyManagement` | `.../GetVersion` | `get_version.py` |
| `TopologyManagement` | `.../MoveADOperationMasterRole` | `move_operation_master_role.py` |
| `TopologyManagement` | `.../ChangeOptionalFeature` | `change_optional_feature.py` |

Les espaces de noms d'action sont ceux déclarés dans `src/soap/namespaces.py` :

| Constante | Valeur | Contrepartie Microsoft |
|---|---|---|
| `WST` | `http://schemas.xmlsoap.org/ws/2004/09/transfer` | Service ADWS Microsoft |
| `WSEN` | `.../ws/2004/09/enumeration` | Service ADWS Microsoft |
| `WSEV` | `.../ws/2004/08/eventing` | aucune |
| `CUSTOM_ACTIONS` | `.../2008/1/ActiveDirectory/CustomActions` | Service ADWS Microsoft |
| `AD` | `.../2008/1/ActiveDirectory` | Service ADWS Microsoft |
| `ADDATA` | `.../2008/1/ActiveDirectory/Data` | Service ADWS Microsoft |
| `DA` | `.../2006/11/IdentityManagement/DirectoryAccess` | Service ADWS Microsoft |
| `ADLQ` | `.../ActiveDirectory/Dialect/LdapQuery` | Service ADWS Microsoft |

`WSEV` est le seul de la liste à **ne pas** avoir de constante correspondante côté Microsoft : WS-Eventing est implémenté ici sans contrepartie Microsoft connue.

Trois clés de `HANDLER_FACTORIES` n'ont pas d'action Microsoft canonique et ne
sont atteignables que par le routage par suffixe :

- `Search` (`search.py`) — normalise le filtre via `FilterParser` puis délègue à
 `EnumerateHandler` ;
- `Schema` (`schema.py`) — introspection `classSchema`/`attributeSchema`, avec
 un cache porté par l'attribut de classe `_CACHE: SchemaCache` ;
- `Groups` (`groups.py`, `GroupHandler`) — aiguille sur `add`/`remove` présents
 dans l'URI d'action, sinon délègue à `GetADGroupMemberHandler`.

> **Handler inatteignable, vérifié.** `GroupHandler` est enregistré sous la clé
> `Groups` (`src/handlers/handler_routing.py:57`). Le routage par suffixe exige
> qu'une URI d'action se termine par `/Groups` ; aucune action Microsoft connue
> ne le fait, et la table exacte ne contient pas cette clé. `GroupHandler` est
> donc **du code mort en pratique** : l'ajout et le retrait de membre arrivent
> en réalité comme un `transfer/Put` sur l'objet groupe et sont servis par
> `modify.py`. Les journaux du dépôt le confirment : sur 98 connexions,
> `handler=GroupHandler` n'apparaît **jamais**, alors que `TransferHandler`
> apparaît 13 fois.

Enfin, les quatre handlers WS-Eventing (`Subscribe`, `Unsubscribe`,
`SubscriptionRenew`, `SubscriptionStatus`) sont enregistrés et répondent, mais
seul `SubscribeHandler` publie une adresse de gestionnaire d'abonnement, et
celle-ci est **codée en dur sur `localhost`**
(`classes/handlers/subscribe.py:15-17`) — un client distant ne pourra donc pas
recontacter ce gestionnaire. Les trois autres se contentent de manipuler le
cache d'abonnements et ne réémettent aucune adresse
(`classes/handlers/unsubscribe.py`, `subscription_renew.py`,
`subscription_status.py`).

## Découverte côté client : DNS, CLDAP et le flag `DS_WS`

La localisation du service est **entièrement côté client**. Rien, dans ce dépôt,
n'implémente ni n'influence cette phase : elle se déroule avant que la moindre
socket ne s'ouvre sur 9389.

La séquence effectuée par un client Windows est la suivante :

- **1.** **Résolution DNS SRV.** Le *DC locator* interroge
 `_ldap._tcp.dc._msdcs.<domaine>` (et, selon le contexte,
 `_ldap._tcp.<site>._sites.dc._msdcs.<domaine>`) pour obtenir la liste des
 contrôleurs de domaine candidats, puis résout leurs enregistrements A/AAAA.
- **2.** **LDAP ping (CLDAP).** Il envoie une requête `CLDAP` sans connexion sur
 **UDP/389** vers chaque candidat, avec un filtre `NtVer`. Le DC répond une
 structure `NETLOGON_SAM_LOGON_RESPONSE_EX` dont le champ `Flags` déclare les
 services rendus (PDC, GC, KDC, écriture, horloge, etc.). Voir `[MS-ADTS]`,
 chapitre localisation de contrôleur de domaine, et `[MS-NRPC]` pour la
 structure de réponse.
- **3.** **Filtrage par capacité.** Le module `ActiveDirectory` et ADAC
 n'appellent pas un simple « trouve-moi un DC » : ils appellent le locator avec
 l'exigence **« ne me renvoie un DC que s'il annonce ADWS »**
 (`DS_WEB_SERVICE_REQUIRED`). Le DC ne satisfait ce filtre que s'il a positionné
 le bit `NBT_SERVER_ADS_WEB_SERVICE` dans sa réponse CLDAP.

**Samba ne positionne pas ce bit.** C'est la cause de fond, établie dans
`documentation/06-depannage.md:252-255` : le nom du flag client
`DS_WEB_SERVICE_REQUIRED` et la valeur `0x2000` de `NBT_SERVER_ADS_WEB_SERVICE`
y sont donnés, avec le fichier Samba responsable
`source4/cldap_server/netlogon.c` (`documentation/06-depannage.md:276`). Ce
projet fournit **le service** ADWS mais ne peut pas modifier **l'annonce
CLDAP** de Samba, qui est émise par `samba-ad-dc` sur UDP/389.

> **Ce qui n'est pas vérifiable ici.** La valeur numérique du flag client
> `DS_WEB_SERVICE_REQUIRED` de `DsGetDcName` n'apparaît **nulle part** dans ce
> dépôt : seul son nom est cité. La valeur `0x2000` documentée est celle du bit
> serveur `NBT_SERVER_ADS_WEB_SERVICE` dans le champ `Flags` de la réponse
> CLDAP, pas celle du flag d'appel côté client. Les deux ne se confondent pas.

Le diagnostic est binaire et reproductible depuis le client :

```powershell
nltest /dsgetdc:samba.local        # succes  -> DNS et DC locator OK
nltest /dsgetdc:samba.local /ws    # 1355    -> le DC n'annonce pas ADWS
Test-NetConnection 192.168.141.10 -Port 9389   # True -> le service repond
```

Ces trois commandes sont celles de `documentation/06-depannage.md:261-263`. Le
code `1355` est `ERROR_NO_SUCH_DOMAIN` (`documentation/06-depannage.md:255`).
Si la troisième commande réussit alors que la deuxième échoue, **il n'y a rien à
corriger côté serveur** : le service tourne, seule l'annonce manque.

| Comportement client | Sans `-Server` | Avec `-Server` |
|---|---|---|
| Découverte DC locator | Requise | Court-circuitée |
| Exigence flag `DS_WS` | Oui | Non |
| Résultat contre Samba | `1355` / `ADServerDownException` | Fonctionne |
| Chemin validé par le projet | Non | Oui |

Contournements retenus par le projet : passer **toujours** `-Server` (au besoin
via `$PSDefaultParameterValues`, cf. `README.md`), et utiliser **ADUC**
(`dsa.msc`, LDAP direct) plutôt qu'ADAC pour l'administration graphique.

## Ce que le serveur ne fait pas, et ne fera pas

À isoler explicitement pour éviter les fausses pistes de diagnostic :

- Aucune émission d'enregistrement DNS SRV ni de réponse CLDAP.
- Aucune publication `serviceConnectionPoint` dans l'annuaire.
- Aucune extraction ni validation de `<a:To>`, `<a:Via>`, `<a:ReplyTo>` — hormis
 la relecture par expression régulière de `<a:To>` dans `create.py:75`.
- Aucune validation **sémantique** du `Mode` ni de l'`Encoding` : le serveur
 n'exige nulle part `Mode = DUPLEX` ni `Encoding = 8`. Il y a en revanche une
 validation **syntaxique** involontaire, héritée de la coercition en énumération
 (`as_enum('B', Mode)` et `as_enum('B', KnownEncoding)`,
 `src/nettcp/nmf.py:306-325`) : une valeur hors énumération lève un `ValueError`
 et la connexion se ferme. Un client annonçant `Mode = SIMPLEX (3)` serait donc
 accepté sans broncher, alors qu'un `Encoding = 0` serait rejeté.
- Aucune négociation de dictionnaire dynamique `[MS-NBFSE]` : la réponse est
 systématiquement préfixée d'un octet `0x00`, soit « dictionnaire de session de
 taille nulle » (`classes/handlers/dispatcher.py:49`).
- Aucun endpoint `mex` ni `UserName/`.
- Aucune application des quotas `[MS-ADDM]` ni des limites de configuration
 du service Microsoft (voir le tableau de comparaison plus loin).

# Anatomie complète d'une session : les cinq phases

## Vue d'ensemble

Une session ADWS se décompose en cinq phases strictement ordonnées. Les phases
2, 3 et 5 sont régies par `[MS-NMF]` ; la phase 3 imbrique en outre le cadrage
`[MS-NNS]` et les jetons GSSAPI/SPNEGO (`RFC 4178`, `RFC 4121`, `RFC 4120`,
`RFC 2743`) ; la phase 4 imbrique `[MS-NBFX]`/`[MS-NBFS]` puis SOAP 1.2 et le
modèle de données `[MS-ADDM]`.

| Phase | Contenu | Code du projet |
|---|---|---|
| 1 | Établissement TCP sur 9389 | `classes/server/server.py:25-32` |
| 2 | Préambule NMF (4 records) | `classes/server/protocol.py:31-67` |
| 3 | Upgrade sécurité GSSAPI | `classes/server/protocol.py:69-105` |
| 4 | Messages applicatifs scellés | `classes/server/protocol.py:107-181` |
| 5 | Fermeture (`EndRecord`) | `classes/server/protocol.py:170-173` |

> **Attention à la numérotation.** Le code et les journaux emploient une
> numérotation **à trois phases**, et non à cinq : la docstring de
> `classes/server/protocol.py:1-6` annonce « Phase 1: Preamble / Phase 2:
> Security / Phase 3: Messages », et c'est ce qui est écrit dans `adws.log`
> (`─── PHASE 1: PREAMBLE NEGOTIATION ───`,
> `─── PHASE 2: SECURITY NEGOTIATION ───`,
> `─── PHASE 3: MESSAGE EXCHANGE ───`). La correspondance est la suivante :

| Ce document | Journal serveur | Fonction |
|---|---|---|
| Phase 1 (TCP) | non journalisée comme phase | `ConnectionHandler.handle` |
| Phase 2 (préambule) | `PHASE 1: PREAMBLE NEGOTIATION` | `handle_preamble` |
| Phase 3 (sécurité) | `PHASE 2: SECURITY NEGOTIATION` | `handle_security` |
| Phase 4 (messages) | `PHASE 3: MESSAGE EXCHANGE` | `handle_messages` |
| Phase 5 (fermeture) | `CONNECTION CLOSED` | bloc `finally` |

## Phase 1 — Établissement TCP

Le serveur est un `socketserver.ForkingTCPServer` lié à
`(config.server.host, config.server.port)`, par défaut `0.0.0.0:9389`
(`classes/server/config.py:15-16`, surchargeable par `ADWS_HOST` et `ADWS_PORT`,
`classes/server/config.py:40-42`). Le bind est **différé** (`bind_and_activate=False`)
afin de positionner `allow_reuse_address` **avant** l'appel à `server_bind`,
faute de quoi un socket en `TIME_WAIT` fait échouer tout redémarrage avec
`EADDRINUSE` (`classes/server/server.py:25-32`).

Dès l'`accept`, `socketserver` **fork** un processus enfant qui exécute
`ConnectionHandler.handle` (`classes/server/connection.py:27`). Le premier acte
de ce handler est de poser un délai d'attente de 10 secondes sur la socket
(`classes/server/connection.py:39`), puis d'envelopper la socket dans un
`SocketStream` (`src/nettcp/stream/socket.py:19`).

> **Piège vérifié dans le code.** `SocketStream.read(count)` appelle
> `self._socket.setblocking(1)` (`src/nettcp/stream/socket.py:32`), et
> `SocketStream.write` fait de même (`src/nettcp/stream/socket.py:51`). En
> Python, `setblocking(True)` est **strictement équivalent à
> `settimeout(None)`** : le délai posé ligne 39 de `connection.py` est donc
> **annulé dès la première lecture ou écriture de record**. En pratique la
> socket est purement bloquante pour toute la durée de la session, et la branche
> `except socket_timeout` de `classes/server/protocol.py:115` — ainsi que
> l'`EndRecord` qu'elle émet — n'est jamais empruntée par ce chemin. La variante
> `read(None)` bascule au contraire en non bloquant et s'appuie sur un
> `select.select` **sans timeout** (`src/nettcp/stream/socket.py:26-30`), ce qui
> revient au même : attente indéfinie.
>
> Conséquence en cascade : les deux seuls garde-fous temporels du serveur — le
> `settimeout(10)` de `connection.py:39` et le `settimeout(2)` de
> `protocol.py:164` — sont **tous les deux inopérants**, le premier parce qu'il
> est écrasé, le second parce qu'il vise un attribut inexistant (voir phase 5).
> Une connexion qui ne dit plus rien immobilise son processus enfant
> indéfiniment.

## Phase 2 — Préambule NMF

Le client envoie une séquence fixe de records, **sans aucune négociation
préalable et sans attendre de réponse**. Les codes et l'ordre sont ceux de
`[MS-NMF]` et sont implémentés dans `src/nettcp/nmf.py`. Le client de référence
embarqué dans le dépôt (`src/nettcp/stream/nmf.py:19-27`) émet exactement :

| Record | Code | Champs | Valeur émise |
|---|---|---|---|
| `VersionRecord` | `0x00` | Major, Minor | `1`, `0` |
| `ModeRecord` | `0x01` | Mode | `2` = DUPLEX |
| `ViaRecord` | `0x02` | Longueur varint, URL UTF-8 | URL cible |
| `KnownEncodingRecord` | `0x03` | Encoding | `8` = binaire + dictionnaire |
| `UpgradeRequestRecord` | `0x09` | Longueur `21`, protocole | `application/negotiate` |

> **Statut de ces valeurs.** Les codes de record et l'ordre relèvent de
> `[MS-NMF]` — niveau *spécification*. Les valeurs de la dernière colonne sont
> celles que le **client de référence du dépôt** écrit littéralement
> (`src/nettcp/stream/nmf.py:21-24, 30-31`) — niveau *implémentation vérifiée*.
> Que le module PowerShell `ActiveDirectory` émette exactement les mêmes octets,
> en particulier `Encoding = 8`, est une **déduction** : le serveur ne journalise
> pas les valeurs reçues (il ne journalise que le type de record,
> `classes/server/protocol.py:41-48`) et aucune capture réseau n'est versionnée.
> La déduction s'appuie sur deux faits observables : les sessions réelles
> aboutissent, et les charges reçues commencent bien par un bloc de dictionnaire
> de session (`build_dictionary`, `src/nettcp/protocol2xml.py:30-48`), ce qui
> n'a de sens qu'avec `BINARY_DICT = 8`.

Reconstitution octet par octet, dérivée des définitions de records
(`src/nettcp/nmf.py:298-333`) et du client de référence
(`src/nettcp/stream/nmf.py:20-31`). L'exemple prend l'URL
`net.tcp://dc.samba.local:9389/ActiveDirectoryWebServices/Windows/Resource`,
longue de **73 caractères**, soit `0x49` :

```text
00 01 00                       VersionRecord      major=1 minor=0
01 02                          ModeRecord         Mode=2 (DUPLEX)
02 49 6E 65 74 2E 74 63 70 ..  ViaRecord          len=0x49 (73), "net.tcp://..."
03 08                          KnownEncodingRecord  Encoding=8
09 15 61 70 70 6C 69 63 61 ..  UpgradeRequest     len=0x15 (21), "application/..."
```

Les longueurs sont des `varint` à bit de continuation : tant qu'elles restent
sous `0x80` elles tiennent sur un seul octet, ce qui est le cas ici (73 et 21).
Au-delà de 127 caractères d'URL, le `ViaRecord` porte deux octets de longueur.

L'énumération `KnownEncoding` de `src/nettcp/nmf.py:178-184` liste
`UTF8=3, UTF16=4, UNICODE_LITTL_ENDIAN=5, MTOM=6, BINARY=7, BINARY_DICT=8`,
et `Mode` (`src/nettcp/nmf.py:187-191`)
`SINGLETON_UNSIZED=1, DUPLEX=2, SIMPLEX=3, SINGLETON_SIZED=4`.

> **Précision de parité.** La table d'encodages de `[MS-NMF]` couvre aussi les
> valeurs `0x00` à `0x02`, réservées à SOAP 1.1 (UTF-8, UTF-16, Unicode
> little-endian). L'énumération vendorée ne déclare **que la moitié SOAP 1.2**
> (`0x03` à `0x08`). Conséquence directe et vérifiable : un client annonçant un
> encodage SOAP 1.1 ferait échouer la coercition `as_enum('B', KnownEncoding)`
> (`src/nettcp/nmf.py:153-170`, `321-325`) sur un `ValueError`, capté par le
> `except Exception` de `classes/server/protocol.py:65` — connexion fermée sans
> réponse. Le module `ActiveDirectory` n'emprunte jamais ce chemin : il parle
> SOAP 1.2 binaire avec dictionnaire.

> Le tableau de `documentation/03-protocole.md:36-40` contient deux inexactitudes
> à corriger : les codes de `ModeRecord`, `ViaRecord` et `KnownEncodingRecord` y
> sont décalés d'un cran (`0x02`, `0x03`, `0x04` au lieu de `0x01`, `0x02`,
> `0x03`), et l'encodage y est donné pour `3` alors que la valeur émise est `8`.
> Le même document, dans son schéma de la phase 3, place le code `0x06` et la
> longueur *hors* du scellement GSSAPI, ce qui est également faux (voir plus
> loin). Les valeurs faisant foi sont celles de `src/nettcp/nmf.py`.

Côté serveur, `ProtocolHandler.handle_preamble` (`classes/server/protocol.py:31`)
boucle sur `nmf.Record.parse_stream` et se contente de **journaliser** les codes
`0x00`, `0x01`, `0x02`, `0x03` (lignes 41-48). Il ne répond rien. Deux records
seulement terminent la phase :

- `0x09` `UpgradeRequestRecord` : mémorisé dans `self.pending_upgrade` et rendu
 à la phase suivante (`classes/server/protocol.py:49-54`) ;
- `0x0c` `PreambleEndRecord` : le serveur répond immédiatement `PreambleAckRecord`
 (`0x0b`) et termine le préambule (`classes/server/protocol.py:55-60`).

> **Il n'existe aucun chemin de session en clair.** On pourrait croire que la
> branche `0x0c` ouvre une session sans chiffrement. Ce n'est pas le cas :
> `ConnectionHandler.handle` appelle `handle_security` inconditionnellement
> après le préambule (`classes/server/connection.py:50`), et `handle_security`
> lit alors le record suivant et **exige** un `0x09`
> (`classes/server/protocol.py:78-86`). Un client qui terminerait son préambule
> par `PreambleEndRecord` sans demander d'upgrade recevrait son
> `PreambleAckRecord` puis verrait la connexion se fermer. Le chiffrement
> GSSAPI est donc structurellement obligatoire dans cette implémentation.

Tout autre code produit un avertissement et un `return False`
(`classes/server/protocol.py:61-63`), et la connexion est **fermée sans aucune
réponse** (`classes/server/connection.py:45-47`). Notons que le code `0x04`
(`ExtensibleEncodingRecord` de `[MS-NMF]`) n'est **pas déclaré** dans
`src/nettcp/nmf.py` : son arrivée lèverait un `KeyError` dans
`Record.parse_stream` (`src/nettcp/nmf.py:262`), capté par le `except Exception`
de `classes/server/protocol.py:65` — même issue, connexion fermée.

## Phase 3 — Upgrade de sécurité GSSAPI/SPNEGO

Cette phase est le point de bascule de la session. Côté Windows, le transport
`net.tcp` avec `SecurityMode.Transport` et
`ProtectionLevel.EncryptAndSign` s'appuie sur
`NegotiateStream` (`[MS-NNS]`). Côté serveur Linux, il n'y a pas de
`NegotiateStream`.NET : on reproduit **le cadrage** `[MS-NNS]` et on délègue la
cryptographie à `samba.gensec`.

Le déroulé exact, ancré dans le code :

- **1.** Le serveur émet `UpgradeResponseRecord` (`0x0A`, un octet nu — la classe
 n'a aucun champ, `src/nettcp/nmf.py:336-337`) via
 `classes/server/protocol.py:92`.
- **2.** Il remplace son flux par un `GENSECStream`
 (`classes/server/protocol.py:96`), qui enveloppe lui-même un `NegotiateStream`
 (`src/nettcp/stream/gssapi.py:89`).
- **3.** `negotiate_server` lit d'abord un jeton client
 (`src/nettcp/stream/gssapi.py:105`), puis démarre un contexte serveur
 `gensec.Security.start_server` avec un `auth.AuthContext`
 (lignes 107-108), charge les identifiants **du compte machine du DC**
 (`creds.guess(lp_ctx)` puis `creds.set_machine_account(lp_ctx)`, lignes
 113-116) et sélectionne le mécanisme `spnego` (ligne 118).
- **4.** Il boucle sur `client_ctx.update(token)` (lignes 123-132). Tant que
 `server_finished` est faux, il écrit le jeton serveur en cadrage
 « handshake in progress » et relit le jeton suivant. Au dernier tour, il
 appelle `write_handshake_done` (ligne 129).

Le cadrage `[MS-NNS]` est implémenté dans `src/nettcp/stream/negotiate.py` :

| État | En-tête | Taille | Sens |
|---|---|---|---|
| Handshake en cours | `0x16` + major + minor + `uint16` BE | 5 octets | Jeton SPNEGO |
| Handshake terminé | `0x14` + major + minor + `uint16` BE | 5 octets | Dernier jeton |
| Erreur | `0x15` + major + minor + `uint16` BE | 5 octets | Code d'erreur |
| Après handshake | `uint32` **little-endian** | 4 octets | Charge scellée |

Les codes proviennent de l'énumération `MessageType`
(`src/nettcp/stream/negotiate.py:14-17`) : `HANDSHAKE_DONE = 0x14`,
`HANDSHAKE_ERROR = 0x15`, `HANDSHAKE_IN_PROGRESS = 0x16` — conformes à
`[MS-NNS]`. Les champs `major`/`minor` sont émis à `1` et `0`
(`negotiate.py:52-56`, `84-88`). Sur réception d'un `0x15`, le lecteur lit
8 octets supplémentaires et interprète le **second** mot de 32 bits big-endian
comme code d'erreur (`negotiate.py:68-72`).

La bascule de cadrage est portée par le seul drapeau `_handshake_done`
(`negotiate.py:48`) : il passe à vrai en lecture quand un `0x14` arrive
(`negotiate.py:73-74`) et en écriture dans `write_handshake_done`
(`negotiate.py:82-83`). Tant qu'il est faux, `write` préfixe l'en-tête
`0x16` de 5 octets ; une fois vrai, il émet des trames `uint32` LE plafonnées à
**`0xFC30`** (64 560 octets, `negotiate.py:59-62`). En amont,
`GENSECStream.write` découpe le texte clair en
tranches de **`0xF000`** (61 440 octets, `src/nettcp/stream/gssapi.py:17`) : la
marge de 3 120 octets absorbe l'en-tête CFX Kerberos, le *confounder*, l'en-tête
dupliqué et le HMAC. Le commentaire du code est explicite : si un jeton scellé
débordait sur une seconde trame, le lecteur — qui suppose « une trame = un
jeton » — échouerait au `unwrap`.

À partir de cet instant, **toute** lecture et **toute** écriture passent par
`client_ctx.wrap` / `client_ctx.unwrap`
(`src/nettcp/stream/gssapi.py:144-170`). Les couches supérieures ne le voient
pas.

> **Branche morte, vérifiée.** `GENSECStream.write` et `GENSECStream.read`
> commencent par `if not self.client_ctx: self.negotiate`
> (`src/nettcp/stream/gssapi.py:145-146` et `155-156`). Or `GENSECStream` ne
> définit **pas** de méthode `negotiate` — seulement `negotiate_server`
> (`src/nettcp/stream/gssapi.py:104`). Ces deux lignes sont un reliquat de la
> classe cliente `GSSAPIStream` dont `GENSECStream` a été dérivée par
> copier-coller (`src/nettcp/stream/gssapi.py:20-78`). Elles ne se déclenchent
> jamais parce que `ProtocolHandler.handle_security` appelle explicitement
> `negotiate_server` avant tout échange (`classes/server/protocol.py:97`) ;
> si elles se déclenchaient, elles lèveraient un `AttributeError`.

Trois points de vigilance opérationnels :

- Le SPN présenté par le client doit exister sur le compte machine du DC. À
 défaut, `gensec` lève `samba.NTSTATUSError (3221225572)`, soit `0xC0000064`
 `STATUS_NO_SUCH_USER` ; le client Windows n'affiche que « Le site distant a
 fermé le flux de transport ». Correctif :
 `samba-tool spn add "host/$(hostname -f)" "$(hostname -s)$"`
 (`documentation/06-depannage.md:59`).
- Une dérive d'horloge entre le client et le KDC fait également échouer la
 phase 3 avec la **même** manifestation côté Windows — toute erreur GSSAPI
 aboutit à une fermeture de socket. En revanche le NTSTATUS côté serveur
 diffère (`KRB5KRB_AP_ERR_SKEW`, cf. RFC 4120) : ce cas **n'est pas documenté
 dans ce dépôt** et n'apparaît dans aucune trace versionnée. La tolérance de
 5 minutes est la valeur par défaut de Kerberos, pas une constante de ce
 projet.
- Le keytab n'a pas à être exporté : `set_machine_account(lp_ctx)` lit
 directement les secrets Samba (`documentation/03-protocole.md` renvoie à
 `/var/lib/samba/private/secrets.tdb`).

> **Divergence majeure, vérifiée dans le code.** L'identité Kerberos négociée
> **n'est pas propagée à l'annuaire**. `classes/server/connection.py:56` construit
> `session_info = system_session` et le passe au dispatcher ; `SambaDB` ouvre
> ensuite `SamDB(lp=lp, session_info=self.session_info)`
> (`classes/directory/samba_db.py:26`). Le repli est doublé : si aucun
> `session_info` n'est transmis, `SambaDB.__init__` en fabrique un lui-même par
> `session_info or system_session` (`classes/directory/samba_db.py:15`).
> Aucune interrogation du contexte gensec pour en extraire une identité
> n'existe dans le dépôt : `GENSECStream` n'expose d'ailleurs que `client_ctx`,
> jamais le `session_info` que `samba.gensec` sait produire. Autrement dit :
> la poignée de main Kerberos joue le rôle de **portier** (seul un principal
> disposant d'un ticket valide pour le SPN du DC peut ouvrir une session), mais
> les opérations d'annuaire s'exécutent ensuite avec la **session système**, donc
> sans application des ACL AD de l'appelant. C'est un écart par rapport au
> comportement de l'ADWS Microsoft, qui associe chaque connexion LDAP du pool à
> un jeu d'identifiants client (paramètre `MaxConnectionsPerUser`).

## Phase 4 — Messages applicatifs scellés

`handle_messages` (`classes/server/protocol.py:107`) boucle indéfiniment sur
`nmf.Record.parse_stream`. Trois codes sont acceptés :

| Code | Record | Traitement |
|---|---|---|
| `0x0c` | `PreambleEndRecord` | Répond `0x0b`, poursuit la boucle |
| `0x06` | `SizedEnvelopedMessageRecord` | Dispatch, répond un `0x06` |
| `0x07` | `EndRecord` | Sort de la boucle, ferme |

Le `PreambleEndRecord` traité **ici** et non en phase 2 n'est pas une bizarrerie :
c'est l'ordre normal d'une session avec upgrade. Le client de référence du dépôt
l'illustre (`src/nettcp/stream/nmf.py:39-42`) : il écrit `PreambleEndRecord`
**après** avoir installé le flux GSSAPI, puis attend `PreambleAckRecord`. Cet
échange transite donc **déjà scellé**.

Un message applicatif a la forme suivante. **Le point le plus souvent mal
représenté est l'imbrication** : le record NMF n'est *pas* en clair avec une
charge chiffrée à l'intérieur ; c'est **le record entier**, code `0x06` et
`varint Size` compris, qui est scellé, puis précédé de la longueur de trame
`[MS-NNS]` en clair.

```text
┌───────────────────────┬───────────────────────────────────────────┐
│ uint32 LE = taille    │  jeton GSS scellé                         │  <- MS-NNS
│ du jeton (en clair)   │                                           │
└───────────────────────┴───────────────────────────────────────────┘
                             │
                             └─ unwrap ─►
   ┌──────┬─────────────┬──────┬────────────────────────────────┐
   │ 0x06 │ varint Size │ 0x00 │  records WCF (MS-NBFX/MS-NBFS) │
   └──────┴─────────────┴──────┴────────────────────────────────┘
     code    Size porte    préfixe de dictionnaire de session
     NMF     sur les       (taille 0 en émission)
             Size octets
             suivants
```

La démonstration tient en deux lignes de code. En émission,
`ProtocolHandler.send_record` sérialise le record complet puis le confie au flux
courant : `data = record.to_bytes` puis `self.stream.write(data)`
(`classes/server/protocol.py:185-188`) ; après la phase 3, `self.stream` est un
`GENSECStream` dont le `write` applique `client_ctx.wrap` sur **tout** ce qu'on
lui donne (`src/nettcp/stream/gssapi.py:144-152`). En réception,
`nmf.Record.parse_stream(self.stream)` commence par `stream.read(1)` pour lire
le code : cet appel traverse `GENSECStream.read`, qui déchiffre une trame NNS
entière avant de rendre le premier octet (`src/nettcp/stream/gssapi.py:154-170`,
`src/nettcp/nmf.py:256-260`).

Le `varint` suit l'encodage `[MS-NMF]` à bit de continuation
(`src/nettcp/nmf.py:43-57` pour la lecture en flux, `78-100` pour l'écriture,
jusqu'à 5 octets — soit 28 bits utiles). Le champ `Payload` est ensuite lu brut
sur `Size` octets (`src/nettcp/nmf.py:348-353`).

Le premier octet de la charge utile est le **préfixe de dictionnaire de session**.
En émission, le dispatcher écrit `b"\x00" + encoded`
(`classes/handlers/dispatcher.py:49`) : dictionnaire dynamique vide. En
réception, `payload_to_xml` appelle `build_dictionary`
(`src/nettcp/nmf.py:363-373`, `src/nettcp/protocol2xml.py:30-48`), qui lit un
`MultiByteInt31` de taille puis autant d'octets de chaînes UTF-8, indexées de 2
en 2 à partir de 1. C'est la confirmation que l'encodage négocié est bien
`KnownEncoding = 8` et non `7`.

Le cycle complet d'un message est le suivant, ligne à ligne :

```text
protocol.py:114   parse_stream  -> SizedEnvelopedMessageRecord (déscellé)
dispatcher.py:24  payload_to_xml -> XML texte (records WCF décodés)
dispatcher.py:25  RequestContext.from_xml -> action, message_id, DN, is_imda
dispatcher.py:38  registry.resolve(action) -> handler
handler.handle()  -> chaîne XML SOAP complète
dispatcher.py:47  XMLParser.parse -> records WCF
dispatcher.py:48  dump_records   -> octets binaires
dispatcher.py:49  b"\x00" + ...  -> charge utile
protocol.py:153   SizedEnvelopedMessageRecord(Payload=..., Size=len(...))
protocol.py:157   send_record -> wrap GSSAPI -> trame NNS -> socket
```

Toute exception est convertie en **SOAP fault** par le dispatcher
(`classes/handlers/dispatcher.py:31-35`), y compris lorsque l'erreur survient
**avant** la résolution du handler : `_fault` récupère alors
`context.message_id` s'il existe, et une chaîne vide sinon
(`classes/handlers/dispatcher.py:52-55`). C'est indispensable : sans
`<a:RelatesTo>`, le client PowerShell considère la réponse comme non sollicitée,
la jette, et la cmdlet bloque jusqu'au *timeout*
(`documentation/06-depannage.md` §6). L'enveloppe de fault est produite par
`SoapEnvelope.fault` (`classes/soap/soap_envelope.py:46-59`), avec pour action
par défaut `http://www.w3.org/2005/08/addressing/soap/fault`
(`classes/soap/soap_envelope.py:18`).

Le compteur `self.request_index` (`classes/server/protocol.py:168`) numérote les
messages **par connexion** ; on le retrouve tel quel dans les journaux
(`[MESSAGES]... MESSAGE #0`, `#1`, …), ce qui permet de reconstituer une session
depuis `journalctl` sans capture réseau.

## Phase 5 — Fermeture

Deux terminaisons propres existent.

**Fermeture initiée par le client.** Le client envoie `EndRecord` (`0x07`, un
octet nu). Le serveur journalise, sort de la boucle et laisse le bloc `finally`
de `ConnectionHandler.handle` fermer la connexion
(`classes/server/protocol.py:170-173`, `classes/server/connection.py:66-70`).
C'est le cas observé dans tous les journaux réels du dépôt. Le client de
référence procède de même : `close` écrit `EndRecord` puis ferme
(`src/nettcp/stream/nmf.py:58-60`).

> **Écart de conformité.** Le mode `DUPLEX` de `[MS-NMF]` prévoit que **chaque
> extrémité** signale la fin de son flux par un `EndRecord` (demi-fermeture
> indépendante). Ce serveur n'émet un `EndRecord` que dans la branche
> `socket.timeout / ConnectionReset / BrokenPipe`
> (`classes/server/protocol.py:115-125`) ; à la réception d'un `EndRecord`
> client, il **ne renvoie pas** le sien. En pratique le client ferme
> immédiatement la socket derrière son `EndRecord`, ce qui rend l'écart
> inoffensif — mais il existe.

**Fermeture initiée par le serveur.** Elle n'intervient que sur erreur ou
inactivité. Le code prévoit d'abaisser le délai à 2 secondes après chaque
réponse — `self.stream._socket.settimeout(2)`
(`classes/server/protocol.py:164`) — mais `self.stream` a été remplacé par un
`GENSECStream` en phase 3 (`classes/server/protocol.py:96`), et `GENSECStream`
**ne possède pas d'attribut `_socket`** : son constructeur ne pose que `_inner`,
`client_ctx`, `_readcache`, `settings` et `lp_ctx`
(`src/nettcp/stream/gssapi.py:84-102`). L'`AttributeError` est avalée par le
`except Exception: pass` des lignes 165-166. **Cette réduction de délai est donc
sans effet.** Le `_socket` réel est deux niveaux plus bas :
`GENSECStream._inner` est un `NegotiateStream`, dont `_inner` est le
`SocketStream` qui, lui, porte `_socket` (`src/nettcp/stream/socket.py:20-21`).

**Fermeture non propre.** Si le client coupe la socket sans `EndRecord`,
`SocketStream.read(1)` retourne `b''` et l'assertion
`assert len(data) == s` de `src/nettcp/nmf.py:259` lève une `AssertionError`.
Celle-ci n'est ni un `socket.timeout` ni un `EOFError` : elle tombe dans le
`except Exception` global de `classes/server/protocol.py:179-181`, journalisée
en `[MESSAGES]... Error:` avec la trace, puis `handle_messages` retourne `False`
et `connection.py:59-60` journalise `[MESSAGES] Message exchange failed`. Une
déconnexion brutale apparaît donc dans les journaux **comme une erreur**, ce
qu'il faut savoir pour ne pas partir en chasse d'un bug inexistant.

## Diagramme de séquence complet et annoté

```text
 Client Windows                                    Serveur ADWS (fork)
 (module ActiveDirectory)                          python3 -m src.main
       │                                                    │
       │  ── PHASE 1 : TCP ──────────────────────────────── │
       │  SYN / SYN-ACK / ACK          port 9389            │
       ├───────────────────────────────────────────────────►│ accept()
       │                                                    │ fork()
       │                                                    │ settimeout(10)
       │                                                    │   (annulé au 1er
       │                                                    │    setblocking(1))
       │  ── PHASE 2 : PREAMBULE NMF (aucune réponse) ───── │
       │  00 01 00        VersionRecord     1.0             │
       │  01 02           ModeRecord        DUPLEX          │
       │  02 <len> <url>  ViaRecord         .../Resource    │ lu, journalisé,
       │  03 08           KnownEncoding     binaire+dict    │ jamais validé
       │  09 15 "application/negotiate"     UpgradeRequest  │
       ├───────────────────────────────────────────────────►│ protocol.py:31-67
       │                                                    │
       │  ── PHASE 3 : UPGRADE SECURITE ────────────────── │
       │◄───────────────────────────────────────────────────┤ 0A UpgradeResponse
       │                                                    │ protocol.py:92
       │  [NNS 0x16] SPNEGO NegTokenInit (AP-REQ Kerberos)  │
       ├───────────────────────────────────────────────────►│ gensec.update()
       │◄───────────────────────────────────────────────────┤ [NNS 0x14]
       │           SPNEGO NegTokenResp (AP-REP) + done      │ write_handshake_done
       │                                                    │
       │  === à partir d'ici : cadrage uint32 LE, ==========│
       │  === charge scellée wrap/unwrap AES     ==========│
       │                                                    │
       │  0C PreambleEndRecord              (scellé)        │
       ├───────────────────────────────────────────────────►│ protocol.py:133
       │◄───────────────────────────────────────────────────┤ 0B PreambleAck
       │                                    (scellé aussi)  │ protocol.py:137
       │                                                    │
       │  ── PHASE 4 : MESSAGES APPLICATIFS ─────────────── │
       │  <uint32 LE> wrap( 06 <varint size> 00 + WCF )     │
       │       SOAP 1.2 : a:Action = .../transfer/Get       │
       │                  a:MessageID = urn:uuid:...        │
       ├───────────────────────────────────────────────────►│ dispatcher.dispatch
       │                                                    │  payload_to_xml
       │                                                    │  RequestContext
       │                                                    │  resolve -> Get
       │                                                    │  SamDB (ouverture
       │                                                    │  paresseuse ici)
       │                                                    │  ldb search
       │◄───────────────────────────────────────────────────┤ wrap(06 <size> ..)
       │       a:RelatesTo = MessageID de la requête        │ protocol.py:153
       │                                                    │
       │  [ 0..N messages supplémentaires sur la même TCP ] │
       │                                                    │
       │  ── PHASE 5 : FERMETURE ────────────────────────── │
       │  07 EndRecord                                      │
       ├───────────────────────────────────────────────────►│ protocol.py:170
       │  FIN                                               │ (pas d'EndRecord
       ├───────────────────────────────────────────────────►│  en retour)
       │                                                    │ exit du fork
```

## Coût réseau minimal d'une session

En comptant en **allers-retours applicatifs** (un envoi client suivi d'une
réponse serveur), une session complète d'un seul message coûte :

| # | Échange | Aller-retour |
|---|---|---|
| 0 | Poignée de main TCP | 1 RTT |
| 1 | Préambule + `UpgradeRequest` → `UpgradeResponse` | 1 RTT |
| 2 | Jeton SPNEGO client → jeton serveur + « done » | 1 RTT |
| 3 | `PreambleEnd` → `PreambleAck` | 1 RTT |
| 4 | Message SOAP → réponse SOAP | 1 RTT |
| 5 | `EndRecord` + FIN | 0,5 RTT |

Soit **4 allers-retours applicatifs après la poignée de main TCP**, dans le cas
le plus favorable.

Trois réserves méthodologiques, à énoncer plutôt qu'à masquer :

- Le nombre d'allers-retours SPNEGO **n'est pas borné par le code** :
 `negotiate_server` boucle sur `client_ctx.update(token)` jusqu'à ce que
 `server_finished` soit vrai (`src/nettcp/stream/gssapi.py:123-132`). L'hypothèse
 d'un aller-retour unique correspond au cas nominal Kerberos avec
 authentification mutuelle ; elle n'est pas mesurée ici, et un mécanisme SPNEGO
 qui replierait sur NTLM en consommerait davantage.
- La coalescence TCP côté client .NET (préambule et premier jeton dans un même
 segment) est un comportement plausible de l'empilement, **non mesuré dans ce
 dépôt** : aucune capture réseau n'y est versionnée. Le seul chemin d'observation
 disponible est `tools/work/proxy.py`.
- Le tableau compte des **allers-retours logiques**, pas des segments TCP. Les
 deux ne coïncident pas.

Ce que les traces versionnées montrent en revanche sans ambiguïté, c'est
l'amortissement : une même connexion porte `Create`, `Put`, `Get` puis `Delete`
en messages `#0` à `#3` — quatre messages, un seul préambule, une seule
négociation Kerberos.

# Modèle d'exécution serveur et conséquences sur la session

## `ForkingTCPServer` : le choix structurant

`python3-samba` n'est **pas** *thread-safe* : les structures C internes de LDB
et de `samba.credentials` ne supportent pas l'accès concurrent. Le projet a donc
retenu `socketserver.ForkingTCPServer` (`classes/server/server.py:25`) : **une
connexion TCP = un processus enfant**, isolé par la mémoire virtuelle.

| Propriété | Conséquence |
|---|---|
| Isolation mémoire totale | Aucun verrou à poser, aucun état partagé |
| Coût d'un `fork` par connexion | Amorti si le client réutilise la connexion |
| Aucun partage de cache | Chaque cache est rechauffé par processus |
| Crash confiné | Un enfant qui meurt ne tue pas le service |

Le corollaire est la règle d'or du projet, rappelée dans `CLAUDE.md` §5 et dans
`documentation/04-handlers.md` : **ne jamais ouvrir un `SamDB` au niveau
module**. Un handle ouvert avant le `fork` serait dupliqué dans tous les
enfants, avec des descripteurs de fichiers et des verrous LDB partagés — cas
d'école de corruption.

## L'ouverture paresseuse de `SamDB`

`SambaDB` (`classes/directory/samba_db.py:10`) matérialise cette règle. Le
constructeur ne fait **rien** de coûteux : il mémorise le logger et un
`session_info`, et laisse `self._db = None` (lignes 12-15). L'ouverture réelle
n'a lieu qu'au premier accès à la propriété `db` (lignes 17-21), qui appelle
`_open` : chargement de `LoadParm`, puis construction du `SamDB`
(lignes 23-27).

Ce n'est pas une micro-optimisation : c'est ce qui garantit que le `SamDB` est
**toujours** créé après le `fork`, dans l'espace mémoire de l'enfant, quelle
que soit la profondeur d'instanciation des handlers. Or `HandlerRegistry`
instancie **tous** les handlers d'un coup, par compréhension de dictionnaire sur
`HANDLER_FACTORIES` (`classes/handlers/handler_registry.py:11-13`), et
`BaseHandler.__init__` construit un `SambaDB` pour chacun
(`classes/handlers/base.py:21`).

Le décompte exact est plus élevé qu'il n'y paraît, car cinq handlers
composites en instancient d'autres dans leur propre constructeur :

| Handler composite | Sous-handlers construits | Source |
|---|---|---|
| `CRUDHandler` (clé `Create`) | `Create`, `Modify`, `Delete` | `crud.py:14-16` |
| `TransferHandler` (clé `Put`) | `Modify`, `Delete` | `transfer.py:13-14` |
| `TransferHandler` (clé `Delete`) | `Modify`, `Delete` | `transfer.py:13-14` |
| `SearchHandler` (clé `Search`) | `Enumerate` | `search.py:13` |
| `GroupHandler` (clé `Groups`) | `GetADGroupMember` | `groups.py:17` |

Soit **29 handlers de premier niveau + 9 imbriqués = 38 instances de
`BaseHandler`**, donc **38 objets `SambaDB`** créés par connexion — mais
**aucun** n'ouvre l'annuaire tant qu'il n'est pas sollicité.

Le moment de cette construction est lui aussi précis : `ADWSDispatcher` — et
donc `HandlerRegistry` — n'est instancié qu'**après** la phase de sécurité,
juste avant `handle_messages` (`classes/server/connection.py:56-58`). Les 38
objets sont donc créés une fois par connexion, dans le processus enfant, entre
la fin du handshake Kerberos et le premier message applicatif.

La trace réelle le confirme : dans une session `Get-ADRootDSE`, la ligne
`[DB] SamDB connection established` (`classes/directory/samba_db.py:27`)
n'apparaît **qu'après** `[GetHandler] Processing:` — 48 ms après le début du
traitement, et jamais avant.

## Caches par processus

Tout ce qui ressemble à un état global dans ce code est en réalité **un état par
processus enfant**, remis à zéro à chaque connexion. Il faut le savoir pour ne
pas surestimer l'effet des caches.

| Cache | Emplacement | Portée réelle |
|---|---|---|
| `ServiceContext` (singleton) | `classes/server/service_context.py:21-26` | Un fork |
| `LdapSessionPool` | `classes/directory/ldap_session_pool.py:13` | Un fork |
| `InstanceIndex` | `classes/directory/instance_index.py:9` | Un fork |
| `SyntaxCache` par `SamDB` | `classes/server/service_context.py:28-35` | Un fork |
| `EnumerationRegistry` | `src/enumeration/enumeration.py:6-13` | Un fork |
| `SchemaHandler._CACHE` | `classes/handlers/schema.py` (attribut de classe) | Un fork |

Les verrous `threading.Lock` / `threading.RLock` présents dans `ServiceContext`,
`InstanceIndex` et `LdapSessionPool` protègent donc contre une concurrence
**intra-processus** qui, en pratique, n'existe pas dans ce modèle d'exécution.
Ils sont inoffensifs et préparent une éventuelle bascule vers un modèle
mixte.

Le `LdapSessionPool` mérite une note : il implémente un plafond de sessions par
utilisateur (`DEFAULT_PER_USER_LIMIT = 10`) et un ramasse-miettes sur inactivité
(`DEFAULT_IDLE_TIMEOUT = 600` secondes), ce qui reproduit la logique
`MaxConnectionsPerUser` de l'ADWS Microsoft. Comme il vit dans un processus qui
ne traite qu'une connexion, son plafond ne peut pas jouer son rôle de garde-fou
global.

## Adhérence de session des contextes d'énumération

Une énumération WS-Enumeration s'étale sur plusieurs messages :
`Enumerate` (création du contexte) → `Pull` × N → `Release`. Le contexte est
identifié par un UUID et **stocké en mémoire** :

| Élément | Valeur | Source |
|---|---|---|
| Contextes simultanés | `MAX_CONTEXTS = 256` | `classes/enumeration/enumeration_registry.py:11` |
| Résultats par contexte | `MAX_RESULTS_PER_CONTEXT = 50000` | `classes/enumeration/enumeration_registry.py:12` |
| Durée de vie | `ttl_seconds = 3600` | `classes/handlers/enumerate.py:67` |
| `MaxElements` par défaut | `100` si absent | `classes/handlers/pull.py:20` |
| Éviction | Le contexte le plus ancien | `classes/enumeration/enumeration_registry.py:26-29` |
| Identifiant | `uuid.uuid4` | `classes/enumeration/enumeration_registry.py:30` |
| Expiration annoncée | `utcnow + 1 h`, ISO 8601 + `Z` | `classes/handlers/enumerate.py:81` |

Le contexte n'étant partagé par aucun mécanisme inter-processus, **tous les
`Pull` d'une même énumération doivent atterrir dans le processus qui a servi
l'`Enumerate`**. C'est le cas parce que le client Windows réutilise la
**même connexion TCP** pour toute la séquence — donc le même fork. Les journaux
du dépôt le montrent : `MESSAGE #0` = `Enumerate`, `MESSAGE #1` = `Pull`, sur la
même connexion.

> **Fragilité connue.** Si un client ouvrait une seconde connexion pour émettre
> son `Pull` — ce que rien n'interdit dans `[MS-WSDS]` — le second fork ne
> connaîtrait pas l'UUID et `PullHandler` lèverait
> `Invalid or expired enumeration context` (`classes/handlers/pull.py:29-31`).
> Aucun stockage partagé (fichier, tmpfs, socket unix) n'est implémenté.

Notons aussi que l'`Enumerate` de ce projet **matérialise l'intégralité du
résultat** en mémoire dès la première requête (`classes/handlers/enumerate.py:73`
`materialized = list(results)`), tronque à `MAX_RESULTS_PER_CONTEXT`
(`enumerate.py:74-78`), puis pagine côté serveur au fil des `Pull`. L'ADWS
Microsoft procède différemment : les constantes du service ADWS Microsoft fixe `pageSize = 1000`
côté LDAP et les constantes du service ADWS Microsoft `DefaultPullElements = 1u`, c'est-à-dire une
pagination LDAP réelle appuyée sur le contrôle `1.2.840.113556.1.4.319`
(`LdapPagedControlOID`).

Les contrôles LDAP envoyés par le client sont bien reconnus et traduits en
chaînes `ldb` (`classes/parsing/controls_parser.py:8-28`) : la table
`LDB_CONTROL_BY_OID` compte **19 OID**, pour **18 noms `ldb` distincts** —
`1.2.840.113556.1.4.1340` et `1.2.840.113556.1.4.2064` se traduisent tous deux
en `show_recycled`. La traduction produit `nom:criticité` ou
`nom:criticité:valeur` (`controls_parser.py:62-74`), et le résultat est passé
tel quel à `SamDB.search(controls=...)` (`enumerate.py:53`). Mais
`paged_results` n'est **pas** exploité pour découper la recherche : il est
transmis à `ldb` sans que le handler gère de cookie de continuation.

Quelques OID notables de cette table, tous vérifiés dans le fichier :

| OID | Nom `ldb` | Usage courant |
|---|---|---|
| `1.2.840.113556.1.4.319` | `paged_results` | Pagination LDAP |
| `1.2.840.113556.1.4.417` | `show_deleted` | Objets supprimés |
| `1.2.840.113556.1.4.473` | `server_sort` | Tri serveur |
| `1.2.840.113556.1.4.529` | `extended_dn` | DN avec GUID/SID |
| `1.2.840.113556.1.4.801` | `sd_flags` | Portions de `nTSecurityDescriptor` |
| `1.2.840.113556.1.4.841` | `dirsync` | Synchronisation incrémentale |
| `1.2.840.113556.1.4.1504` | `asq` | Attribute Scoped Query |

## Machine d'états : table complète

| État | Record reçu | Action serveur | État suivant |
|---|---|---|---|
| PREAMBULE | `0x00` Version | Journalise | PREAMBULE |
| PREAMBULE | `0x01` Mode | Journalise | PREAMBULE |
| PREAMBULE | `0x02` Via | Journalise | PREAMBULE |
| PREAMBULE | `0x03` KnownEncoding | Journalise | PREAMBULE |
| PREAMBULE | `0x09` UpgradeRequest | Mémorise le record | SECURITE |
| PREAMBULE | `0x0c` PreambleEnd | Émet `0x0b` | SECURITE |
| PREAMBULE | autre | Avertit, ferme | FERMÉ |
| SECURITE | `0x09` (mémorisé) | Émet `0x0A`, GSSAPI | MESSAGES |
| SECURITE | `0x09` (relu du flux) | Émet `0x0A`, GSSAPI | MESSAGES |
| SECURITE | tout autre code | Erreur, ferme | FERMÉ |
| MESSAGES | `0x0c` PreambleEnd | Émet `0x0b` | MESSAGES |
| MESSAGES | `0x06` SizedEnveloped | Dispatch, émet `0x06` | MESSAGES |
| MESSAGES | `0x07` End | Journalise | FERMÉ |
| MESSAGES | autre | Avertit, ferme | FERMÉ |
| MESSAGES | EOF / socket coupée | `AssertionError`, ferme | FERMÉ |

La ligne « `0x0c` en PREAMBULE » est celle qu'on lit de travers le plus souvent.
Elle ne mène **pas** à l'état MESSAGES : `handle_preamble` renvoie `True`, et
`ConnectionHandler.handle` enchaîne inconditionnellement sur `handle_security`
(`classes/server/connection.py:50`). Il n'y a donc qu'une seule porte vers
l'état MESSAGES, et elle passe par la négociation GSSAPI.

Le tableau ci-dessous récapitule les treize codes de `[MS-NMF]` et leur sort
exact dans ce serveur. `register_types` (`src/nettcp/nmf.py:394-406`)
enregistre par introspection **toutes** les sous-classes de `Record` du module :
un code défini est donc toujours *analysable*, même s'il n'est jamais *accepté*
par la machine d'états.

| Code | Record | Défini ? | Sort dans ce serveur |
|---|---|---|---|
| `0x00` | `VersionRecord` | oui | Lu, journalisé, non validé |
| `0x01` | `ModeRecord` | oui | Lu, journalisé, non validé |
| `0x02` | `ViaRecord` | oui | Lu, journalisé, non validé |
| `0x03` | `KnownEncodingRecord` | oui | Lu, journalisé, non validé |
| `0x04` | `ExtensibleEncodingRecord` | **non** | `KeyError` puis fermeture |
| `0x05` | `UnsizedEnvelopedMessageRecord` | oui | Analysable, jamais accepté |
| `0x06` | `SizedEnvelopedMessageRecord` | oui | Reçu et émis (phase 4) |
| `0x07` | `EndRecord` | oui | Reçu ; émis sur timeout seulement |
| `0x08` | `FaultRecord` | oui | Analysable, jamais émis |
| `0x09` | `UpgradeRequestRecord` | oui | Reçu, déclenche la phase 3 |
| `0x0A` | `UpgradeResponseRecord` | oui | Émis en phase 3 |
| `0x0B` | `PreambleAckRecord` | oui | Émis en réponse à `0x0C` |
| `0x0C` | `PreambleEndRecord` | oui | Reçu (généralement scellé) |

Le cas de `0x04` mérite d'être distingué : `Record.parse_stream` résout la
classe par `rec = cls._records[code]` (`src/nettcp/nmf.py:262`). Un code absent
du registre lève un `KeyError`, pas un avertissement propre. La différence est
visible dans les journaux : un code **connu mais inattendu** produit
`... Unexpected record code: 0x05`, tandis qu'un code **inconnu** produit une
trace d'exception `... Error:`.

L'absence d'émission de `FaultRecord` mérite un mot : les erreurs applicatives
remontent en **SOAP fault** dans un `0x06` normal, jamais en fault de couche
NMF. Une erreur de couche NMF ou WCF, elle, coupe simplement la connexion — d'où
le message Windows « Le site distant a fermé le flux de transport »
(`documentation/06-depannage.md` §2).

## Bornes et quotas : ce projet contre l'ADWS Microsoft

| Paramètre | ADWS Microsoft | Ce projet |
|---|---|---|
| `MaxReceivedMessageSize` | 1 048 576 octets | Non implémenté |
| `MaxStringContentLength` | 32 768 | Non implémenté |
| `MaxArrayLength` | 16 384 | Non implémenté |
| `MaxDepth` (lecteur XML) | 10 | Non implémenté |
| `receiveTimeout` | 00:10:00 | Non appliqué |
| `MaxConcurrentCalls` | 32 | Aucune limite |
| `MaxConcurrentSessions` | 500 | Aucune limite |
| `MaxEnumCtxsPerSession` | 5 | Aucune limite |
| `MaxEnumCtxsTotal` | 100 | 256 par processus |
| `MaxEnumContextExpiration` | 00:30:00 | 3600 s |
| `MaxPullTimeout` | 00:02:00 | Non implémenté |
| `OperationTimeout` | 00:02:00 | Non implémenté |
| `MaxPoolConnections` | 10 par instance | Sans objet (`SamDB` local) |
| `MaxConnectionsPerUser` | 5 | 10 (`DEFAULT_PER_USER_LIMIT`) |
| `MaxPercentageReservedConnections` | 50 | Non implémenté |

Les valeurs de la colonne Microsoft sont les réglages par défaut du service
Windows.

Côté projet, deux champs de configuration sont **déclarés mais jamais lus** :
`ServerConfig.max_connections = 128` et `ServerConfig.timeout = 300`
(`classes/server/config.py:17-18`) — aucune autre occurrence dans le dépôt.
C'est un des chantiers de la phase 5 « performance + durcissement ». Le seul
plafond réellement actif est `MAX_CONTEXTS = 256` du cache d'énumération, et il
est **par processus**, donc sans effet global.

Enfin, la version annoncée diverge :

| Champ | ADWS Microsoft | Ce projet |
|---|---|---|
| Version majeure | `1` | — |
| Version mineure | `1` | — |
| Chaîne de version | `Active Directory Web Services v1.1` | — |
| `ca:Server` | non exposé sous cette forme | `1.0.0` (`get_version.py:9`) |
| `ca:Protocol` | `1.1` implicite | `1.1` (`get_version.py:10`) |

`GetVersionHandler` répond donc `Server = 1.0.0` là où Microsoft annonce `v1.1`
dans `VersionString`. Aucune cmdlet connue ne s'appuie
sur cette valeur, mais l'écart est réel et doit être tracé.

# Cartographie du code : de la socket au SamDB

## Table de correspondance par étape

| Étape | Fichier | Élément |
|---|---|---|
| Amorçage | `src/main.py` | `main`, `nmf.register_types` |
| Configuration | `classes/server/config.py` | `Config`, `ServerConfig` |
| Écoute, fork | `classes/server/server.py` | `ADWSServer` |
| Cycle de connexion | `classes/server/connection.py` | `ConnectionHandler.handle` |
| Phases NMF | `classes/server/protocol.py` | `ProtocolHandler` |
| Records NMF | `src/nettcp/nmf.py` | `Record` et sous-classes |
| Socket brute | `src/nettcp/stream/socket.py` | `SocketStream` |
| Cadrage MS-NNS | `src/nettcp/stream/negotiate.py` | `NegotiateStream` |
| Sécurité GSSAPI | `src/nettcp/stream/gssapi.py` | `GENSECStream` |
| Décodage WCF | `src/wcf/records/`, `src/wcf/datatypes.py` | `Record.parse` |
| Encodage WCF | `src/wcf/xml2records.py` | `XMLParser.parse` |
| Dictionnaire | `src/wcf/dictionary.py` | Table statique |
| Aiguillage | `classes/handlers/dispatcher.py` | `ADWSDispatcher.dispatch` |
| Analyse SOAP | `classes/parsing/context.py` | `RequestContext.from_xml` |
| Résolution d'action | `classes/handlers/handler_registry.py` | `HandlerRegistry.resolve` |
| Table de routage | `src/handlers/handler_routing.py` | `ACTION_HANDLER_KEYS` |
| Contrat handler | `classes/handlers/base.py` | `BaseHandler.handle` |
| Enveloppe SOAP | `classes/soap/soap_envelope.py` | `SoapEnvelope.wrap` |
| Sérialisation objet | `classes/serialization/object_projector.py` | `ObjectProjector` |
| Accès annuaire | `classes/directory/samba_db.py` | `SambaDB.db` |
| Erreurs typées | `classes/faults/`, `src/faults/` | `ADWSException` |

`src/nettcp/` et `src/wcf/` sont du code tiers **vendoré** (attribution
« Copyright 2016 Timo Schmid » en tête de fichier), intégré au dépôt mais exclu
des normes de codage du projet — c'est explicité dans
`documentation/01-architecture.md:79-80` et matérialisé dans
`pyproject.toml:9-10` et `:30-33`. C'est ce qui explique que ces fichiers
enfreignent ouvertement les règles de `CLAUDE.md` §6.1 (plusieurs classes par
fichier, absence d'annotations de type, commentaires en ligne) : ils sont hors
périmètre du vérificateur `tools/norms`.

## Chronologie mesurable d'un `Get-ADRootDSE`

La séquence ci-dessous est reconstituée depuis une trace réelle du dépôt
(`adws.log`, connexion `172.19.0.3:64321`, 4 juin 2026 à 05:21:28). Il s'agit
bien d'un **`Get-ADRootDSE`** : le journal montre
`[GetHandler] Processing: 11111111-1111-1111-1111-111111111111`, qui est
exactement l'identifiant conventionnel de la racine d'annuaire. Les durées sont celles mesurées par l'horodatage du
journal serveur ; le temps réseau client n'y figure pas, et chaque poste inclut
son propre coût de journalisation — ce sont donc des **bornes supérieures**.

| Instant | Événement journalisé | Δ |
|---|---|---|
| `28,645` | `[CONNECTION] NEW CLIENT CONNECTION` | — |
| `28,650` | `VersionRecord` reçu | +5 ms |
| `28,654` | `UpgradeRequestRecord` reçu (fin préambule) | +9 ms |
| `28,657` | `UpgradeResponseRecord` émis | +12 ms |
| `28,736` | Négociation GSSAPI terminée | +91 ms |
| `28,743` | Message #0 reçu, 486 octets | +98 ms |
| `28,778` | Action et `MessageID` extraits | +133 ms |
| `28,780` | `handler=GetHandler` | +135 ms |
| `28,829` | `[DB] SamDB connection established` | +184 ms |
| `28,841` | Réponse #0 émise, 6 664 octets | +196 ms |
| `28,843` | `EndRecord` reçu du client | +198 ms |
| `28,846` | `[CONNECTION] CONNECTION CLOSED` | +201 ms |

Décomposition du budget, pour un DC de laboratoire. **Chaque poste est une
différence d'horodatages de journal**, donc une borne supérieure incluant le
coût de la journalisation elle-même ; ce ne sont pas des mesures
instrumentées :

| Poste | Intervalle | Durée | Part |
|---|---|---|---|
| Préambule NMF | `28,645` → `28,654` | ~9 ms | 4 % |
| Négociation Kerberos (gensec) | `28,657` → `28,736` | ~79 ms | 39 % |
| Décodage WCF + analyse SOAP | `28,743` → `28,778` | ~35 ms | 17 % |
| Ouverture `SamDB` | `28,780` → `28,829` | ~49 ms | 24 % |
| Recherche, sérialisation, envoi | `28,829` → `28,841` | ~12 ms | 6 % |
| Divers (fork, journaux, clôture) | reste | ~17 ms | 8 % |

Trois enseignements se dégagent, tous vérifiables sur la trace :

- **1.** Le **coût dominant d'une cmdlet isolée est la négociation Kerberos**,
 pas l'accès à l'annuaire. C'est l'argument central en faveur de la réutilisation
 de connexion : une session qui enchaîne dix messages amortit ces 79 ms une
 seule fois.
- **2.** Le client PowerShell **ouvre une connexion par cmdlet** lorsqu'il n'a
 rien à enchaîner. Les journaux montrent quatre connexions successives
 (`64321`, `64322`, `64323`, `64324`) pour quatre cmdlets, chacune payant son
 préambule et son handshake. En revanche, une cmdlet composite paie une seule
 fois : les traces `Create` → `Put` → `Get` → `Delete` tiennent sur une
 connexion unique, en messages `#0` à `#3`.
- **3.** L'ouverture du `SamDB` (~49 ms entre `handler=GetHandler` et
 `[DB] SamDB connection established`) est payée **une fois par processus**, au
 premier handler qui touche l'annuaire. Sur une session multi-messages, les
 messages suivants n'en supportent pas le coût.

Le nombre minimal d'allers-retours réseau pour une cmdlet isolée est donc de
**5** : la poignée de main TCP, puis les quatre échanges applicatifs du tableau
de la section précédente (`UpgradeResponse`, jeton SPNEGO, `PreambleAck`,
message SOAP), la fermeture ne comptant que pour une demi-boucle. Ce chiffre
suppose un aller-retour SPNEGO unique, hypothèse discutée plus haut.

## Points de rupture typiques et où regarder

| Symptôme côté Windows | Phase | Où regarder | Réf. |
|---|---|---|---|
| « flux de transport fermé » | 3 | `src/nettcp/stream/gssapi.py` | §2 |
| `STATUS_NO_SUCH_USER` (`0xC0000064`) | 3 | SPN du compte machine | §1 |
| « Élément de fin attendu, trouvé … » | 4 | `classes/parsing/context.py` | §3 |
| Cmdlet bloquée jusqu'au timeout | 4 | `dispatcher._fault` / `RelatesTo` | §6 |
| `undefined entity` dans le journal | 4 | `src/wcf/records/text.py` | §9 |
| `empty base DN` | 4 | `classes/handlers/enumerate.py:30-33` | §5 |
| `Unable to find a default server` (`1355`) | 0 | Flag `DS_WS` Samba | §7 |

La colonne « Réf. » renvoie aux sections de `documentation/06-depannage.md`.

La règle de lecture est simple : **une erreur qui produit une SOAP fault est
applicative** (phase 4, le dispatcher a fait son travail) ; **une erreur qui
coupe la connexion est protocolaire** (phase 2, 3, ou couche WCF/NMF), et il
faut alors remonter le journal jusqu'à la dernière trace avant
`[CONNECTION] CONNECTION CLOSED`.

Pour observer le clair, la capture `tcpdump -i any -w /tmp/adws.pcap port 9389`
ne montre que du chiffré à partir de la phase 3 ; le seul moyen de voir le XML
applicatif est de passer par l'outil de capture `tools/work/proxy.py` ou de
décoder un payload isolé avec `src.wcf.records.dump_records`.

## Récapitulatif des écarts vérifiés dans le code

Ce chapitre a mis au jour, pièce en main, sept écarts entre ce qui est annoncé
(spécification, `CLAUDE.md`, `documentation/`) et ce que le code fait
réellement. Ils sont rassemblés ici pour servir de liste de travail ; chacun est
démontré dans la section correspondante.

| Écart | Ancrage | Effet observable |
|---|---|---|
| Identité Kerberos non propagée au `SamDB` | `connection.py:56` | ACL AD non appliquées |
| `settimeout(2)` sur un objet sans `_socket` | `protocol.py:164` | Réduction sans effet |
| `settimeout(10)` écrasé par `setblocking(1)` | `socket.py:32` | Attente indéfinie |
| Aucun `EndRecord` en retour du client | `protocol.py:170-173` | DUPLEX incomplet |
| `max_connections` / `timeout` jamais lus | `config.py:17-18` | Aucun plafond global |
| `GroupHandler` inatteignable (clé `Groups`) | `handler_routing.py:57` | Code mort |
| `Server = 1.0.0` vs `v1.1` Microsoft | `get_version.py:9` | Version incohérente |

Deux écarts documentaires s'y ajoutent, à corriger dans
`documentation/03-protocole.md` : les codes de records décalés d'un cran et
l'encodage donné pour `3` (lignes 36-40), et le schéma de la phase 3 qui place
le code `0x06` et la longueur hors du scellement GSSAPI.

> Aucun de ces écarts n'empêche les cmdlets de fonctionner contre un DC Samba :
> les phases 1 à 5 se déroulent, les objets remontent, les écritures passent.
> Ils décrivent en revanche exactement le périmètre de la phase 5 du projet —
> « performance + durcissement sécurité » — et en particulier le premier, qui
> est le seul à avoir une portée de sécurité réelle.
