# Ce que ce guide explique

Active Directory Web Services (ADWS) est le service par lequel les outils
d’administration Microsoft modernes parlent à un contrôleur de domaine. Il
écoute sur le port **9389/tcp** et n’est pas un protocole unique : c’est un
**empilement** d’une dizaine de protocoles distincts, chacun normalisé
séparément, qui coopèrent pour transporter une requête d’annuaire.

Ce guide décrit chacun de ces protocoles pour lui-même : *comment il parle*,
*quels messages il définit*, *quelles réponses il autorise*, *quelles options
il offre*, et *comment il s’articule avec ses voisins*. Il ne décrit aucune
implémentation particulière. Il ne contient aucun extrait de programme. Un
lecteur qui l’aura parcouru doit pouvoir lire une capture réseau ADWS et
nommer chaque octet qu’il y voit.

## Ce que le guide couvre

| Couche | Protocole | Norme de référence |
|---|---|---|
| Transport | TCP sur le port 9389 | RFC 9293 |
| Cadrage | .NET Message Framing | [MS-NMF] |
| Négociation d’authentification | NegotiateStream | [MS-NNS] |
| Sélection de mécanisme | SPNEGO | RFC 4178 |
| Authentification | Kerberos v5 | RFC 4120 |
| Interface de sécurité | GSS-API | RFC 2743, RFC 4121 |
| Encodage | XML binaire .NET | [MS-NBFX], [MS-NBFS] |
| Messagerie | SOAP 1.2 | W3C SOAP 1.2 |
| Adressage | WS-Addressing | W3C WS-Addressing 1.0 |
| Transfert de ressource | WS-Transfer | W3C Submission 2006 |
| Énumération | WS-Enumeration | W3C Submission 2006 |
| Notification | WS-Eventing | W3C Submission 2006 |
| Accès annuaire | IMDA et extensions AD | [MS-WSTIM], [MS-WSDS], [MS-WSPELD] |
| Modèle de données | Objets et attributs AD | [MS-ADDM], [MS-ADTS] |

## Conventions de lecture

- Les noms de messages, d’éléments XML, d’en-têtes et de constantes sont
  donnés dans leur forme originale, en anglais.
- Les valeurs numériques sont écrites en hexadécimal préfixé `0x` lorsqu’il
  s’agit d’octets sur le fil, en décimal sinon.
- Les schémas XML sont formatés pour la lisibilité ; sur le fil, ils ne sont
  jamais transmis sous forme textuelle mais sous forme binaire (voir le
  chapitre consacré à l’encodage).
- Lorsqu’un point n’est pas établi avec certitude par une norme publique, le
  texte le signale explicitement plutôt que de trancher.

```schema:stack-protocols
Figure 1 — L’empilement protocolaire d’ADWS. Chaque couche encapsule la
suivante ; une requête traverse les sept niveaux à l’aller et au retour.
```

## Le principe d’encapsulation

Une requête d’administration traverse l’intégralité de la pile. Prenons la
demande « lis-moi l’objet utilisateur Administrator ». Elle existe
successivement sous six formes :

- **1.** Une intention applicative : lire un objet d’annuaire.
- **2.** Un document SOAP 1.2 avec des en-têtes WS-Addressing qui nomment
  l’opération et identifient le message.
- **3.** Une suite d’enregistrements binaires qui encodent ce document sans
  jamais écrire de balise textuelle.
- **4.** Un jeton GSS-API qui chiffre et signe cette suite d’octets.
- **5.** Un enregistrement de cadrage .NET qui préfixe le tout d’un type et
  d’une longueur.
- **6.** Un flux d’octets TCP.

Chaque couche ignore le contenu des couches supérieures. Cette indépendance
est ce qui permet de décrire les protocoles un par un.

# Le rôle d’ADWS et ses points de terminaison

## Pourquoi ce service existe

Un contrôleur de domaine Active Directory expose historiquement son annuaire
par **LDAP** (389/tcp, 636/tcp pour LDAPS) et son authentification par
**Kerberos** (88/tcp et 88/udp). Ces deux protocoles suffisent à tout faire,
mais ils exposent une interface de bas niveau : un client LDAP manipule des
DN, des filtres et des attributs bruts.

ADWS a été introduit avec Windows Server 2008 R2 pour offrir une **façade de
service web** au-dessus de cet annuaire. Son intérêt n’est pas de remplacer
LDAP, mais de proposer :

- une interface **orientée objet** plutôt qu’orientée entrée d’annuaire, où
  un utilisateur est une ressource typée et non un ensemble d’attributs ;
- un **protocole traversant** les infrastructures qui filtrent LDAP, puisque
  tout passe par un seul port et un cadrage documenté ;
- une **sémantique d’opération** normalisée par les spécifications WS-*, avec
  des mécanismes standards d’énumération paginée et de gestion d’erreur.

Les outils qui en dépendent exclusivement sont le module PowerShell
`ActiveDirectory` (l’ensemble des cmdlets `*-AD*`) et le Centre
d’administration Active Directory, qui n’est qu’une interface graphique posée
sur ce même module. Sans ADWS joignable, ces outils échouent dès la première
commande, alors même que LDAP et Kerberos fonctionnent parfaitement.

## Comment un client trouve le service

Le client ne connaît pas l’adresse du service à l’avance. Sa procédure de
localisation, lorsqu’aucun serveur n’est imposé explicitement, suit trois
étapes.

- **1. Découverte DNS.** Le client interroge les enregistrements SRV du
  domaine pour obtenir la liste des contrôleurs. Les enregistrements
  consultés sont ceux qui servent à toute localisation de DC, notamment
  `_ldap._tcp.dc._msdcs.<domaine>` et, quand un site est connu,
  `_ldap._tcp.<site>._sites.dc._msdcs.<domaine>`.
- **2. Sélection d’un contrôleur.** Le client retient un candidat en tenant
  compte de la priorité et du poids annoncés par les enregistrements SRV, et
  de son appartenance de site.
- **3. Tentative de connexion ADWS.** Le client ouvre une connexion TCP vers
  le port 9389 du contrôleur retenu. C’est seulement à cette étape qu’ADWS
  entre en jeu.

Il est essentiel de comprendre que **rien de tout cela n’est du protocole
ADWS** : la découverte est entièrement à la charge du client et repose sur
DNS. Un service ADWS n’a aucun moyen d’influer sur la sélection.

Lorsque cette chaîne échoue, le client rapporte qu’il ne trouve pas de
serveur par défaut exécutant Active Directory Web Services. Le message
recouvre trois causes très différentes : aucun DC trouvé par DNS, DC trouvé
mais port 9389 injoignable, ou port ouvert mais négociation échouée.

## Les points de terminaison

Le service ne publie pas une adresse unique mais **plusieurs points de
terminaison**, distingués par le chemin de leur URL. L’adresse est de la
forme suivante :

```text
net.tcp://<serveur>:9389/ActiveDirectoryWebServices/<binding>/<endpoint>
```

Le segment `<binding>` désigne le mode d’authentification attendu, et le
segment `<endpoint>` le contrat de service visé.

| Point de terminaison | Objet |
|---|---|
| `Resource` | Lecture et modification d’un objet désigné |
| `ResourceFactory` | Création d’objets |
| `Enumeration` | Recherche et parcours paginé de résultats |
| `AccountManagement` | Opérations de compte, dont les mots de passe |
| `TopologyManagement` | Opérations de topologie, dont les rôles FSMO |

Deux préfixes de binding coexistent. Le préfixe `Windows/` correspond à une
authentification intégrée, où l’identité est prouvée au niveau du transport
par Kerberos. Le préfixe `UserName/` correspond à un mode où des identifiants
explicites sont portés dans le message lui-même, protégé par TLS ; ce mode
suppose qu’un certificat serveur ait pu être provisionné, et il est
rarement rencontré en pratique.

Un point de terminaison supplémentaire publie les **métadonnées** du service.
Il permet à un outil générique de découvrir les contrats offerts sans les
connaître à l’avance.

> Le chemin demandé est transmis très tôt dans la connexion, avant toute
> authentification, par un enregistrement de cadrage dédié. Le service peut
> donc refuser une adresse inconnue sans jamais engager de négociation
> cryptographique.

## Le cycle de vie d’une connexion

Une connexion ADWS suit toujours le même déroulement, en cinq temps. Ce
découpage sert de fil conducteur au reste du guide.

```schema:session-phases-protocols
Figure 2 — Les cinq temps d’une session ADWS, du connect TCP à la fermeture.
Les deux premiers temps circulent en clair, les suivants sont chiffrés.
```

- **1. Établissement TCP.** Une connexion classique vers le port 9389.
- **2. Préambule de cadrage.** Le client annonce, en clair, la version du
  cadrage, le mode d’échange, l’adresse visée et l’encodage souhaité, puis
  demande une élévation de sécurité.
- **3. Négociation d’authentification.** Client et service échangent des
  jetons jusqu’à établir un contexte de sécurité mutuellement authentifié.
- **4. Échange applicatif.** Chaque message SOAP, encodé en binaire puis
  chiffré, circule dans un enregistrement de cadrage. Plusieurs requêtes
  se succèdent sur la même connexion.
- **5. Terminaison.** Un enregistrement de fin clôt proprement l’échange.

Les temps 1 et 2 sont observables en clair dans une capture réseau. À partir
du temps 4, tout est chiffré : une capture ne montre plus que des longueurs
et des octets opaques.

# Le cadrage : .NET Message Framing [MS-NMF]

## Le problème que résout ce protocole

TCP transporte un flux d’octets sans frontières. Il faut donc un mécanisme
qui délimite les messages, et qui permette en outre de négocier des
paramètres avant tout échange applicatif. C’est le rôle du .NET Message
Framing, désigné par sa spécification **[MS-NMF]**.

Le protocole définit un vocabulaire d’**enregistrements** (*records*). Chaque
enregistrement commence par un octet qui donne son type ; le reste dépend du
type. Certains enregistrements servent uniquement à la mise en place de la
connexion, d’autres transportent les messages applicatifs.

## Les quatre modes d’échange

MS-NMF prévoit quatre modes, choisis par le client au tout début de la
connexion.

| Mode | Valeur | Sémantique |
|---|---|---|
| Singleton-Unsized | `0x01` | Un seul message, longueur non annoncée |
| Duplex | `0x02` | Messages bidirectionnels multiples |
| Simplex | `0x03` | Messages unidirectionnels |
| Singleton-Sized | `0x04` | Un seul message, longueur annoncée |

ADWS emploie le mode **Duplex**. C’est le seul qui autorise une conversation :
plusieurs requêtes et plusieurs réponses sur une même connexion, dans les
deux sens, ce qu’exige un client qui enchaîne des commandes.

## L’encodage des entiers

Les longueurs sont encodées en **entier variable sur sept bits**, une
technique aussi appelée *varint*. Le principe : chaque octet porte sept bits
utiles dans ses bits de poids faible, et son bit de poids fort indique s’il
est suivi d’un autre octet.

- Bit de poids fort à `1` : un octet supplémentaire suit.
- Bit de poids fort à `0` : c’est le dernier octet.
- Les groupes de sept bits sont assemblés du **moins significatif au plus
  significatif**.

| Valeur décimale | Encodage | Explication |
|---|---|---|
| 0 | `0x00` | Un octet, aucun bit de continuation |
| 5 | `0x05` | Un octet |
| 127 | `0x7F` | Dernière valeur tenant sur un octet |
| 128 | `0x80 0x01` | 0 sur les 7 bits bas, puis 1 |
| 300 | `0xAC 0x02` | 44 + 2 × 128 |
| 16 383 | `0xFF 0x7F` | Dernière valeur sur deux octets |

Les chaînes de caractères suivent la même logique : une longueur en varint,
puis les octets UTF-8 correspondants. Il n’y a pas de terminateur.

## Le catalogue des enregistrements

Chaque enregistrement est identifié par son premier octet.

| Octet | Enregistrement | Sens | Contenu |
|---|---|---|---|
| `0x00` | Version | Client vers service | Majeure, mineure |
| `0x01` | Mode | Client vers service | Un octet de mode |
| `0x02` | Via | Client vers service | Longueur puis URL cible |
| `0x03` | KnownEncoding | Client vers service | Un octet d’encodage |
| `0x04` | ExtensibleEncoding | Client vers service | Type MIME explicite |
| `0x05` | UnsizedEnvelope | Bidirectionnel | Message par fragments |
| `0x06` | SizedEnvelope | Bidirectionnel | Longueur puis message |
| `0x07` | End | Bidirectionnel | Aucun ; fin d’échange |
| `0x08` | Fault | Service vers client | Chaîne de faute de cadrage |
| `0x09` | UpgradeRequest | Client vers service | Nom du protocole d’élévation |
| `0x0A` | UpgradeResponse | Service vers client | Aucun ; accord |
| `0x0B` | PreambleAck | Service vers client | Aucun ; préambule accepté |
| `0x0C` | PreambleEnd | Client vers service | Aucun ; fin de préambule |

Deux enregistrements portent les messages applicatifs. Le **SizedEnvelope**
annonce la longueur du message avant de le transmettre ; c’est celui
qu’utilise ADWS. L’**UnsizedEnvelope** transmet le message par fragments
successifs, chacun préfixé de sa taille, la séquence se terminant par un
fragment de taille nulle ; il sert lorsque la longueur totale n’est pas
connue à l’avance.

## Le préambule

Le préambule est une séquence **fixe**, envoyée par le client sans attendre
de réponse. Le service accumule les enregistrements et ne répond qu’au
moment où le client réclame l’élévation de sécurité.

```schema:nmf-preamble-protocols
Figure 3 — Le préambule de cadrage. Les quatre premiers enregistrements sont
émis en rafale ; le service ne répond qu’après la demande d’élévation.
```

L’ordre est imposé : Version, Mode, Via, KnownEncoding, puis la demande
d’élévation. Un service qui reçoit ces enregistrements dans un ordre
différent, ou un enregistrement inattendu, est en droit de fermer la
connexion.

### L’enregistrement Version

Il annonce la version du cadrage lui-même, sous la forme de deux octets :
majeure puis mineure. La valeur employée est la version 1.0. Ce champ ne
décrit ni la version d’ADWS ni celle de l’annuaire.

### L’enregistrement Via

Il porte l’**URL complète** que le client souhaite atteindre, préfixée de sa
longueur en varint. C’est cet enregistrement qui sélectionne le point de
terminaison. Comme il circule en clair et avant authentification, il est
visible dans toute capture réseau et constitue le moyen le plus simple
d’identifier ce que cherche un client.

### L’enregistrement KnownEncoding

Il désigne, sur un seul octet, la façon dont les messages applicatifs seront
sérialisés.

| Valeur | Encodage |
|---|---|
| `0x00` | SOAP 1.1, UTF-8 |
| `0x01` | SOAP 1.1, UTF-16 |
| `0x02` | SOAP 1.1, UTF-16 gros-boutiste |
| `0x03` | SOAP 1.2, UTF-8 |
| `0x04` | SOAP 1.2, UTF-16 |
| `0x05` | SOAP 1.2, UTF-16 gros-boutiste |
| `0x06` | MTOM |
| `0x07` | XML binaire, sans dictionnaire de session |
| `0x08` | XML binaire, avec dictionnaire de session |

ADWS s’appuie sur l’**XML binaire**. C’est ce choix qui rend les messages
illisibles dans une capture, indépendamment du chiffrement : même déchiffré,
un message ADWS n’est pas du texte XML.

### La demande d’élévation

Le client émet enfin un enregistrement **UpgradeRequest** dont la charge
utile est une chaîne nommant le protocole d’élévation souhaité. Pour une
authentification intégrée, cette chaîne est `application/negotiate`.

Le service répond par un **UpgradeResponse** vide, qui vaut acceptation. À
partir de cet instant précis, le flux TCP ne transporte plus des
enregistrements de cadrage mais le protocole d’élévation, jusqu’à ce que
celui-ci soit terminé.

> C’est le point charnière de toute la connexion. Avant l’UpgradeResponse, on
> lit du cadrage. Juste après, on lit du NegotiateStream. Plus tard, on relit
> du cadrage, mais chiffré. Confondre ces trois régimes est l’erreur la plus
> fréquente dans l’analyse d’une capture ADWS.

## La fin de préambule

Une fois la sécurité établie, le client émet un enregistrement
**PreambleEnd**, auquel le service répond par un **PreambleAck**. Ces deux
enregistrements circulent déjà **protégés** par le contexte de sécurité qui
vient d’être négocié : ils constituent la première preuve que le canal
fonctionne dans les deux sens.

## Les fautes de cadrage

Le service peut signaler une erreur de niveau cadrage par un enregistrement
**Fault**, dont la charge utile est une chaîne identifiant la nature du
problème. Ces fautes sont distinctes des fautes SOAP : elles surviennent
avant même qu’un message applicatif ait pu être interprété.

| Chaîne de faute | Sens |
|---|---|
| `ConnectionDispatchFailed` | Le service n’a pas pu router la connexion |
| `EndpointNotFound` | L’adresse du Via ne correspond à aucun endpoint |
| `EndpointUnavailable` | L’endpoint existe mais refuse la connexion |
| `MaxMessageSizeExceededFault` | Message plus grand que la limite acceptée |
| `ServerTooBusy` | Service saturé |
| `ServiceActivationFailed` | Le service n’a pas pu démarrer |
| `UpgradeInvalid` | Protocole d’élévation refusé |

> Cette liste est d’origine normative et n’est pas exhaustive ; une
> implémentation peut définir d’autres chaînes.

## La terminaison

L’enregistrement **End** clôt l’échange. Il est émis par la partie qui n’a
plus rien à transmettre. En pratique, une connexion ADWS se termine
fréquemment par une simple fermeture TCP après une période d’inactivité,
sans End explicite : les deux comportements se rencontrent.

# L’élévation de sécurité : NegotiateStream [MS-NNS]

## Ce que NegotiateStream apporte

Une fois l’élévation acceptée, le flux TCP est confié au protocole
**NegotiateStream**, spécifié par **[MS-NNS]**. Son rôle est double :

- **pendant la négociation**, transporter les jetons d’authentification entre
  le client et le service, dans les deux sens, autant de fois que nécessaire ;
- **après la négociation**, délimiter les blocs de données protégées, puisque
  le chiffrement produit des blocs dont la taille diffère de celle du texte
  clair.

NegotiateStream ne réalise lui-même aucune cryptographie. Il ne fait que
transporter les jetons produits par la couche d’authentification, puis
encadrer les données une fois celle-ci terminée.

## Le message de handshake

Pendant la phase de négociation, chaque échange est précédé d’un en-tête de
**cinq octets**.

| Décalage | Longueur | Champ | Description |
|---|---|---|---|
| 0 | 1 | MessageId | Nature du message |
| 1 | 1 | MajorVersion | Version majeure, `0x01` |
| 2 | 1 | MinorVersion | Version mineure, `0x00` |
| 3 | 1 | PayloadSizeHigh | Octet de poids fort de la longueur |
| 4 | 1 | PayloadSizeLow | Octet de poids faible de la longueur |

La longueur de la charge utile est donc codée sur **deux octets en ordre
gros-boutiste**, ce qui la plafonne à 65 535 octets. Cet ordre est notable :
il s’oppose à celui employé pour le cadrage des données applicatives.

Trois valeurs de MessageId sont définies.

| Valeur | Nom | Sens |
|---|---|---|
| `0x14` | HandshakeDone | La négociation est terminée avec succès |
| `0x15` | HandshakeError | La négociation a échoué |
| `0x16` | HandshakeInProgress | Un jeton supplémentaire est nécessaire |

La charge utile qui suit l’en-tête est le **jeton d’authentification opaque**.
NegotiateStream ne l’interprète pas : il ignore s’il transporte du SPNEGO, du
Kerberos ou du NTLM.

Lorsque le MessageId vaut `0x15`, la charge utile contient un code d’erreur
permettant d’identifier la cause du rejet.

## Le cadrage des données applicatives

Dès qu’un message **HandshakeDone** a été échangé, le cadrage change
radicalement. Il n’y a plus d’en-tête de cinq octets ni d’identifiant de
message. Chaque bloc protégé est simplement précédé de sa longueur sur
**quatre octets en ordre petit-boutiste**.

```text
+---------------------+------------------------------------------+
| longueur  (4 o, LE) |  bloc protege (jeton GSS-API complet)    |
+---------------------+------------------------------------------+
```

Le protocole impose une taille maximale par bloc. Un message applicatif plus
grand que cette limite est découpé : l’émetteur protège et transmet
successivement plusieurs blocs, que le destinataire déchiffre puis
reconcatène. La frontière entre blocs n’a **aucune signification
applicative** : elle ne coïncide pas avec une frontière de message SOAP.

> Le changement de cadrage au HandshakeDone explique une confusion classique.
> On lit parfois que l’élévation de sécurité d’ADWS consiste en « des jetons
> bruts précédés d’une longueur ». C’est la description du régime *postérieur*
> au handshake. Pendant le handshake, l’en-tête de cinq octets est bien
> présent, et la longueur y est gros-boutiste.

# La sélection du mécanisme : SPNEGO (RFC 4178)

## Le rôle de SPNEGO

Le client et le service doivent s’accorder sur un **mécanisme
d’authentification** avant de l’employer. SPNEGO, pour *Simple and Protected
GSS-API Negotiation Mechanism*, est un pseudo-mécanisme dont l’unique objet
est cette mise d’accord. Il est normalisé par la **RFC 4178**.

SPNEGO est lui-même un mécanisme GSS-API : il s’identifie par un OID et se
manipule comme n’importe quel autre. Cette récursion est délibérée. Elle
permet d’ajouter la négociation sans modifier l’interface de programmation
ni les couches de transport.

## Les identifiants de mécanisme

Chaque mécanisme est désigné par un **OID**, identifiant hiérarchique
normalisé.

| OID | Mécanisme |
|---|---|
| `1.3.6.1.5.5.2` | SPNEGO lui-même |
| `1.2.840.113554.1.2.2` | Kerberos v5 |
| `1.2.840.48018.1.2.2` | Variante Microsoft de Kerberos v5 |
| `1.3.6.1.4.1.311.2.2.10` | NTLM |
| `1.3.6.1.4.1.311.2.2.30` | Négociation étendue Microsoft |

Dans un environnement de domaine sain, c’est Kerberos v5 qui est retenu.
NTLM demeure présent dans la liste proposée par le client, comme mécanisme
de repli.

> La présence de deux OID Kerberos est un héritage historique. Certaines
> implémentations anciennes annonçaient un OID incorrect ; les deux sont
> désormais reconnus et désignent le même mécanisme.

## Les deux messages SPNEGO

SPNEGO définit deux structures, encodées en ASN.1 selon les règles DER.

### NegTokenInit

C’est le premier jeton, émis par le client. Il comporte quatre champs, tous
optionnels sauf le premier.

| Champ | Rôle |
|---|---|
| `mechTypes` | Liste ordonnée des mécanismes proposés, par préférence |
| `reqFlags` | Services de sécurité souhaités ; champ déprécié |
| `mechToken` | Jeton initial du mécanisme préféré |
| `mechListMIC` | Contrôle d’intégrité de la liste `mechTypes` |

Le champ `mechToken` réalise une **optimisation importante** : plutôt que
d’attendre l’accord sur le mécanisme, le client joint immédiatement le
premier jeton de son mécanisme préféré. Si le service l’accepte, un
aller-retour complet est économisé.

Le champ `mechListMIC` protège la négociation contre la **manipulation par un
tiers**. Sans lui, un attaquant en position d’intermédiaire pourrait
retrancher les mécanismes forts de la liste afin de forcer un repli vers un
mécanisme faible. Le MIC, calculé avec une clé issue de l’authentification
réussie, rend cette manipulation détectable.

### NegTokenResp

C’est la réponse du service, et le format de tous les jetons ultérieurs.

| Champ | Rôle |
|---|---|
| `negState` | État de la négociation |
| `supportedMech` | Mécanisme retenu par le service |
| `responseToken` | Jeton du mécanisme retenu |
| `mechListMIC` | Contrôle d’intégrité |

Le champ `negState` prend quatre valeurs.

| Valeur | Sens |
|---|---|
| `accept-completed` | Négociation terminée avec succès |
| `accept-incomplete` | Au moins un jeton supplémentaire est attendu |
| `reject` | Négociation refusée |
| `request-mic` | Le MIC de la liste est exigé avant conclusion |

## Le déroulement typique

Le nombre d’allers-retours n’est pas fixé par la norme : il dépend du
mécanisme retenu et de la nécessité d’échanger un MIC. Le scénario le plus
courant en environnement Kerberos comporte deux à trois échanges.

- **1.** Le client envoie un `NegTokenInit` proposant Kerberos en tête de
  liste, avec l’AP-REQ Kerberos déjà joint dans `mechToken`.
- **2.** Le service accepte Kerberos, valide l’AP-REQ, puis répond un
  `NegTokenResp` portant `supportedMech` égal à l’OID Kerberos, l’AP-REP dans
  `responseToken`, et un `negState` valant soit `accept-completed`, soit
  `request-mic` si un contrôle d’intégrité est réclamé.
- **3.** Le cas échéant, un dernier `NegTokenResp` porte le `mechListMIC`.

## L’enveloppe du jeton initial

Le tout premier jeton n’est pas transmis nu. Il est encapsulé dans une
structure définie par la **RFC 2743**, appelée *InitialContextToken*.

```text
0x60  <longueur DER>
  0x06 <longueur> <OID du mecanisme>    <- ici : SPNEGO, 1.3.6.1.5.5.2
  <contenu specifique au mecanisme>
```

L’octet `0x60` est une étiquette ASN.1 de classe application. Repérer cette
séquence dans une capture est le moyen le plus direct d’identifier le début
d’une négociation GSS-API.

Pour les jetons Kerberos, le contenu qui suit l’OID commence par un
identifiant de type sur deux octets.

| Identifiant | Message |
|---|---|
| `0x01 0x00` | AP-REQ, la demande d’authentification |
| `0x02 0x00` | AP-REP, la réponse mutuelle |
| `0x03 0x00` | KRB-ERROR, une erreur Kerberos |

# L’authentification : Kerberos v5 (RFC 4120)

## Le modèle à trois parties

Kerberos repose sur un tiers de confiance, le **KDC** (*Key Distribution
Center*), hébergé par le contrôleur de domaine. Le principe fondateur : le
client n’envoie jamais son secret au service ; il présente un **ticket**
délivré par le KDC, que le service vérifie sans consulter le KDC.

Trois échanges structurent le protocole. Seul le dernier concerne ADWS
directement.

| Échange | Messages | Objet |
|---|---|---|
| AS | AS-REQ, AS-REP | Obtenir un ticket d’octroi de tickets (TGT) |
| TGS | TGS-REQ, TGS-REP | Obtenir un ticket de service à partir du TGT |
| AP | AP-REQ, AP-REP | Présenter le ticket de service au service visé |

Les échanges AS et TGS ont lieu **avec le KDC, sur le port 88**, et sont donc
extérieurs à la connexion ADWS. Lorsqu’un client ouvre une session ADWS, il
possède déjà son TGT, obtenu à l’ouverture de session Windows ; il lui reste
au plus à demander un ticket de service, puis à le présenter.

```schema:gssapi-handshake-protocols
Figure 4 — L’élévation de sécurité complète : le cadrage NegotiateStream
transporte les jetons SPNEGO, eux-mêmes porteurs des messages Kerberos.
```

## Le nom du service

Pour demander un ticket, le client doit nommer le service visé par un **SPN**
(*Service Principal Name*), de la forme `classe/hôte`.

ADWS relève de la famille des services hébergés par le système, dont le SPN
générique est `HOST/<nom-de-machine>`. Ce SPN est enregistré automatiquement
pour tout compte d’ordinateur joint au domaine et couvre l’ensemble des
services système.

> Il n’existe **pas** de SPN dédié du type `ADWS/serveur`. Le service s’appuie
> sur le SPN d’hôte. C’est pourquoi un contrôleur correctement joint au
> domaine n’exige aucune déclaration de SPN supplémentaire pour qu’ADWS
> fonctionne.

L’erreur `KDC_ERR_S_PRINCIPAL_UNKNOWN` signale que le SPN demandé n’existe
dans aucun compte de l’annuaire. Elle survient typiquement lorsque le client
vise un nom d’hôte, ou un alias, qui n’est pas enregistré.

## Le contenu de l’AP-REQ

L’AP-REQ est le message que le client présente au service. Il comporte deux
parties essentielles, chiffrées avec des clés différentes.

| Partie | Chiffrée avec | Contenu |
|---|---|---|
| Ticket | La clé long terme du service | Identité du client, clé de session, validité |
| Authenticator | La clé de session | Horodatage, somme de contrôle, sous-clé |

Le **ticket** a été fabriqué par le KDC et chiffré avec la clé du compte du
service. Le client ne peut ni le lire ni le modifier ; il se contente de le
relayer. Le service le déchiffre avec sa propre clé et en extrait la **clé de
session**.

L’**authenticator** est chiffré par le client avec cette clé de session. Il
prouve que le client détient réellement la clé, et ne rejoue pas un ticket
intercepté. Il contient un horodatage, ce qui explique la sensibilité de
Kerberos à la dérive d’horloge : au-delà d’une tolérance, généralement de
cinq minutes, l’authenticator est rejeté.

L’authenticator peut également porter une **sous-clé**, proposée par le client
pour servir de base au chiffrement des messages ultérieurs, de préférence à
la clé de session issue du ticket.

## Les options de l’AP-REQ

Deux drapeaux du message conditionnent la suite de l’échange.

| Drapeau | Effet |
|---|---|
| `MUTUAL-REQUIRED` | Le service doit prouver son identité par un AP-REP |
| `USE-SESSION-KEY` | Le ticket est chiffré avec une clé de session |

L’authentification **mutuelle** est déterminante pour ADWS : sans elle, le
client n’aurait aucune garantie de parler au véritable contrôleur de domaine.
C’est l’AP-REP qui apporte cette preuve, puisque seul le détenteur de la clé
du service a pu déchiffrer le ticket et donc produire une réponse valide.

## Les types de chiffrement

Kerberos est agnostique quant à l’algorithme. Chaque clé porte un identifiant
de type.

| Identifiant | Algorithme | Statut |
|---|---|---|
| 18 | AES-256 CTS avec HMAC-SHA1-96 | Recommandé |
| 17 | AES-128 CTS avec HMAC-SHA1-96 | Accepté |
| 23 | RC4 avec HMAC-MD5 | Obsolète |
| 3 | DES-CBC-MD5 | Proscrit |

Le KDC retient le type le plus fort commun au client, au service et à la
politique de domaine. Un environnement moderne aboutit à AES-256.

L’erreur `KRB_AP_ERR_MODIFIED` indique que le service n’a pas pu déchiffrer le
ticket. La cause la plus fréquente n’est pas une altération malveillante mais
une **désynchronisation de clé** : le secret du compte de service a changé
sans que la clé ayant servi à émettre le ticket ait été mise à jour.

## Les erreurs Kerberos courantes

| Erreur | Signification | Origine habituelle |
|---|---|---|
| `KDC_ERR_S_PRINCIPAL_UNKNOWN` | SPN introuvable | Nom d’hôte non enregistré |
| `KDC_ERR_C_PRINCIPAL_UNKNOWN` | Compte client inconnu | Compte absent ou supprimé |
| `KRB_AP_ERR_SKEW` | Dérive d’horloge excessive | Horloges désynchronisées |
| `KRB_AP_ERR_MODIFIED` | Déchiffrement impossible | Clé de service désynchronisée |
| `KRB_AP_ERR_TKT_EXPIRED` | Ticket périmé | Session très longue |
| `KRB_AP_ERR_REPEAT` | Rejeu détecté | Authenticator déjà présenté |

# La protection des messages : GSS-API (RFC 2743 et RFC 4121)

## Ce qu’est GSS-API

GSS-API, pour *Generic Security Service Application Program Interface*, n’est
pas un protocole de transport mais une **interface normalisée** entre une
application et un mécanisme de sécurité. La RFC 2743 en définit l’abstraction ;
la RFC 4121 précise la manière dont Kerberos v5 s’y conforme.

L’intérêt pour ADWS est direct : l’application manipule des jetons opaques
sans jamais implémenter Kerberos. Elle en produit un, l’envoie, en reçoit un
autre, le fournit à la bibliothèque, et recommence jusqu’à ce que celle-ci
déclare le contexte établi.

## L’établissement du contexte

L’établissement suit une boucle symétrique. Chaque partie appelle
répétitivement une primitive qui consomme le jeton reçu et produit
éventuellement un jeton à émettre.

| Étape | Côté client | Côté service |
|---|---|---|
| 1 | Produit le premier jeton | Attend |
| 2 | Attend | Consomme, produit une réponse |
| 3 | Consomme, produit si nécessaire | Attend |
| n | Signale « contexte établi » | Signale « contexte établi » |

Deux états intermédiaires sont normalisés : « il faut continuer » et
« terminé ». Tant que l’état est « il faut continuer », un jeton
supplémentaire doit être transmis. C’est exactement ce que NegotiateStream
matérialise par ses MessageId `0x16` et `0x14`.

## Les services demandés à l’établissement

Le client déclare les garanties qu’il souhaite. Les principales :

| Service | Garantie apportée |
|---|---|
| Authentification mutuelle | Le service prouve son identité au client |
| Intégrité | Toute altération d’un message est détectée |
| Confidentialité | Le contenu des messages est chiffré |
| Séquencement | Les rejeux et réordonnancements sont détectés |
| Délégation | Le service peut agir au nom du client |

ADWS exige au minimum authentification mutuelle, intégrité et
confidentialité. C’est ce triplet qui garantit qu’un observateur du réseau ne
peut ni lire ni modifier une opération d’annuaire.

## Le jeton de protection par message

Une fois le contexte établi, chaque message applicatif est protégé. La
RFC 4121 définit pour cela un jeton dont l’en-tête fait **seize octets**.

| Décalage | Longueur | Champ | Description |
|---|---|---|---|
| 0 | 2 | TOK_ID | `0x05 0x04` pour un message protégé |
| 2 | 1 | Flags | Drapeaux de sens et de chiffrement |
| 3 | 1 | Filler | Toujours `0xFF` |
| 4 | 2 | EC | Nombre d’octets de bourrage |
| 6 | 2 | RRC | Décalage de rotation appliqué |
| 8 | 8 | SND_SEQ | Numéro de séquence, gros-boutiste |

Le champ **Flags** porte trois bits significatifs.

| Bit | Nom | Sens quand il vaut 1 |
|---|---|---|
| 0 | SentByAcceptor | Le jeton vient du service, non du client |
| 1 | Sealed | Le message est chiffré, pas seulement signé |
| 2 | AcceptorSubkey | Le service a imposé sa propre sous-clé |

Le champ **SND_SEQ** est le mécanisme anti-rejeu : chaque jeton porte un
numéro croissant. Un destinataire qui reçoit deux fois le même numéro, ou un
numéro trop ancien, rejette le message.

Les champs **EC** et **RRC** relèvent de la construction cryptographique.
L’algorithme AES en mode CTS impose un alignement ; EC compte les octets de
bourrage ajoutés. RRC indique une rotation circulaire appliquée au jeton, une
particularité de la RFC 4121 destinée à placer la somme de contrôle à un
emplacement prévisible.

## Deux niveaux de protection

GSS-API distingue deux opérations, qui produisent des jetons différents.

| Opération | TOK_ID | Effet |
|---|---|---|
| Protection complète | `0x05 0x04` | Chiffre et authentifie le message |
| Signature seule | `0x04 0x04` | Authentifie sans chiffrer |

ADWS emploie la protection complète. Le message est donc à la fois
confidentiel et intègre. Un observateur ne voit qu’une longueur et des octets
indistinguables d’aléa.

## L’effet sur la taille des messages

La protection **augmente** la taille du message transmis. Il faut compter
l’en-tête de seize octets, un confondeur, une copie de l’en-tête et une somme
de contrôle. Pour Kerberos AES, ce surcoût est de l’ordre de plusieurs
dizaines d’octets par jeton.

Cette expansion a une conséquence pratique : la taille du texte clair confié
à la protection doit rester suffisamment en deçà de la taille maximale d’un
bloc NegotiateStream pour que le jeton résultant tienne dans un seul bloc.
Sans cette marge, un jeton unique déborderait sur deux blocs, et un
destinataire qui suppose « un bloc, un jeton » échouerait à le déchiffrer.

## L’identité obtenue

À l’issue de l’établissement, le service dispose de l’**identité
authentifiée** du client, et non d’une simple confirmation binaire. Cette
identité comprend le nom du principal Kerberos et, dans un contexte Active
Directory, les informations d’autorisation transportées par le ticket, dont
la liste des groupes de sécurité.

C’est cette identité qui doit ensuite gouverner les autorisations sur
l’annuaire : ADWS n’ajoute aucun modèle d’autorisation propre. Les droits
appliqués sont ceux d’Active Directory, évalués selon les descripteurs de
sécurité des objets visés.

# L’encodage : XML binaire .NET [MS-NBFX] et [MS-NBFS]

## Pourquoi un XML binaire

Le XML textuel est verbeux. Un document SOAP répète les mêmes noms
d’éléments, les mêmes URI d’espaces de noms et les mêmes préfixes des
dizaines de fois. Pour un service d’annuaire qui renvoie des milliers
d’objets, ce coût devient dominant.

Deux spécifications répondent à ce problème.

- **[MS-NBFX]** définit une représentation binaire de l’*infoset* XML : au
  lieu de balises textuelles, une suite d’**enregistrements** typés.
- **[MS-NBFS]** ajoute un **dictionnaire** de chaînes fréquentes, qui
  remplace une chaîne connue par un simple index numérique.

Le résultat n’est ni du XML ni une compression générique : c’est une
sérialisation directe de la structure du document. Un décodeur reconstitue
le document XML exact, avec les mêmes éléments, attributs et valeurs.

## Le modèle d’enregistrements

Le principe est uniforme : chaque enregistrement commence par un octet de
type, suivi d’une charge utile dont la forme dépend du type. Les
enregistrements se succèdent sans séparateur, et leur imbrication reproduit
celle du document.

Trois familles coexistent.

| Famille | Rôle |
|---|---|
| Éléments | Ouvrent un élément et nomment son préfixe |
| Attributs | Déclarent un attribut ou un espace de noms |
| Textes | Portent une valeur typée |

Un élément est fermé par un enregistrement de fin dédié, dont la valeur est
`0x01`.

## La convention du bit de poids faible

Les enregistrements de texte suivent une règle d’économie remarquable :
chaque type de texte occupe **deux valeurs consécutives**, l’une paire,
l’autre impaire.

- La valeur **paire** signifie « voici une valeur ».
- La valeur **impaire**, c’est-à-dire la paire plus un, signifie « voici une
  valeur, et l’élément qui la contient se termine immédiatement après ».

Cette convention supprime un enregistrement de fin dans le cas très fréquent
d’un élément ne contenant qu’une valeur. Sur un document d’annuaire où la
quasi-totalité des éléments sont des feuilles, l’économie est substantielle.

## Le catalogue des enregistrements de texte

| Type | Valeur paire | Charge utile | Type XSD correspondant |
|---|---|---|---|
| ZeroText | `0x80` | Aucune | Le nombre 0 |
| OneText | `0x82` | Aucune | Le nombre 1 |
| FalseText | `0x84` | Aucune | `xsd:boolean` faux |
| TrueText | `0x86` | Aucune | `xsd:boolean` vrai |
| Int8Text | `0x88` | 1 octet | `xsd:byte` |
| Int16Text | `0x8A` | 2 octets | `xsd:short` |
| Int32Text | `0x8C` | 4 octets | `xsd:int` |
| Int64Text | `0x8E` | 8 octets | `xsd:long` |
| FloatText | `0x90` | 4 octets | `xsd:float` |
| DoubleText | `0x92` | 8 octets | `xsd:double` |
| DecimalText | `0x94` | 16 octets | `xsd:decimal` |
| DateTimeText | `0x96` | 8 octets | `xsd:dateTime` |
| Chars8Text | `0x98` | Longueur 1 o, puis UTF-8 | `xsd:string` court |
| Chars16Text | `0x9A` | Longueur 2 o, puis UTF-8 | `xsd:string` moyen |
| Chars32Text | `0x9C` | Longueur 4 o, puis UTF-8 | `xsd:string` long |
| Bytes8Text | `0x9E` | Longueur 1 o, puis octets | `xsd:base64Binary` |
| Bytes16Text | `0xA0` | Longueur 2 o, puis octets | `xsd:base64Binary` |
| Bytes32Text | `0xA2` | Longueur 4 o, puis octets | `xsd:base64Binary` |
| StartListText | `0xA4` | Aucune | Début de liste |
| EndListText | `0xA6` | Aucune | Fin de liste |
| EmptyText | `0xA8` | Aucune | Chaîne vide |
| DictionaryText | `0xAA` | Index en varint | Chaîne du dictionnaire |
| UniqueIdText | `0xAC` | 16 octets | Identifiant `urn:uuid:` |
| TimeSpanText | `0xAE` | 8 octets | `xsd:duration` |
| UuidText | `0xB0` | 16 octets | `xsd:guid` |
| UInt64Text | `0xB2` | 8 octets | `xsd:unsignedLong` |
| BoolText | `0xB4` | 1 octet | `xsd:boolean` |
| UnicodeChars8Text | `0xB6` | Longueur 1 o, puis UTF-16 | `xsd:string` |
| UnicodeChars16Text | `0xB8` | Longueur 2 o, puis UTF-16 | `xsd:string` |
| UnicodeChars32Text | `0xBA` | Longueur 4 o, puis UTF-16 | `xsd:string` |
| QNameDictionaryText | `0xBC` | Préfixe puis index | Nom qualifié |

Les valeurs `0x00` sont réservées et `0x01` marque la fin d’un élément.

## Les enregistrements d’élément

| Type | Valeur | Description |
|---|---|---|
| EndElement | `0x01` | Ferme l’élément courant |
| Comment | `0x02` | Commentaire XML |
| Array | `0x03` | Tableau homogène d’éléments |
| ShortElement | `0x40` | Élément sans préfixe, nom littéral |
| Element | `0x41` | Élément avec préfixe littéral |
| ShortDictionaryElement | `0x42` | Élément sans préfixe, nom du dictionnaire |
| DictionaryElement | `0x43` | Élément avec préfixe, nom du dictionnaire |
| PrefixDictionaryElement A à Z | `0x44` à `0x5D` | Préfixe implicite `a` à `z` |
| PrefixElement A à Z | `0x5E` à `0x77` | Préfixe implicite, nom littéral |

Les deux dernières plages méritent une explication. Plutôt que d’écrire le
préfixe d’espace de noms à chaque élément, le format réserve vingt-six
valeurs consécutives, une par lettre de l’alphabet. L’enregistrement `0x44`
signifie « élément de préfixe `a` », `0x45` « élément de préfixe `b` », et
ainsi de suite. Comme les documents SOAP emploient invariablement des
préfixes d’une lettre, presque tous les éléments tiennent sur un seul octet
de type.

## Les enregistrements d’attribut

| Type | Valeur | Description |
|---|---|---|
| ShortAttribute | `0x04` | Attribut sans préfixe, nom littéral |
| Attribute | `0x05` | Attribut avec préfixe littéral |
| ShortDictionaryAttribute | `0x06` | Attribut sans préfixe, nom du dictionnaire |
| DictionaryAttribute | `0x07` | Attribut avec préfixe, nom du dictionnaire |
| ShortXmlnsAttribute | `0x08` | Déclaration d’espace de noms par défaut |
| XmlnsAttribute | `0x09` | Déclaration d’espace de noms avec préfixe |
| ShortDictionaryXmlnsAttribute | `0x0A` | Idem, URI du dictionnaire |
| DictionaryXmlnsAttribute | `0x0B` | Idem, préfixe et URI du dictionnaire |
| PrefixDictionaryAttribute A à Z | `0x0C` à `0x25` | Préfixe implicite, nom du dictionnaire |
| PrefixAttribute A à Z | `0x26` à `0x3F` | Préfixe implicite, nom littéral |

## Les encodages particuliers

Trois types de valeurs méritent un examen détaillé, car leur représentation
n’est pas intuitive.

### Les dates

Une date-heure est encodée sur huit octets. Les 62 bits de poids faible
comptent le nombre d’intervalles de **100 nanosecondes** écoulés depuis le
**1er janvier de l’an 1 à minuit**. Les deux bits de poids fort indiquent la
nature du fuseau.

| Bits de poids fort | Sens |
|---|---|
| `00` | Fuseau non spécifié |
| `01` | Temps universel coordonné |
| `10` | Heure locale de l’émetteur |

Cette origine, très antérieure à l’époque Unix, est celle du système de dates
de la plateforme .NET.

### Les identifiants

Un identifiant globalement unique occupe seize octets, mais **pas** dans
l’ordre de sa représentation textuelle. Les trois premiers champs sont
stockés en ordre **petit-boutiste**, les deux derniers en ordre naturel.

```text
Texte    : 6BA7B810-9DAD-11D1-80B4-00C04FD430C8
                ^^^^^^^^ ^^^^ ^^^^  ces trois champs sont inverses
Octets   : 10 B8 A7 6B  AD 9D  D1 11  80 B4 00 C0 4F D4 30 C8
```

Cette particularité est une source classique d’erreur d’interprétation : un
identifiant lu naïvement paraît incohérent avec sa forme textuelle.

### Les durées

Une durée occupe huit octets et compte, elle aussi, des intervalles de
100 nanosecondes. Une valeur négative représente une durée orientée vers le
passé, ce qui sert notamment à exprimer des délais d’expiration relatifs.

## Le dictionnaire

Le dictionnaire est le second levier d’économie. Plutôt que d’écrire
`http://schemas.xmlsoap.org/ws/2004/09/transfer`, on écrit l’index de cette
chaîne dans une table connue des deux parties.

Deux tables coexistent, distinguées par la parité de l’index.

| Parité de l’index | Table |
|---|---|
| Paire | Dictionnaire **statique**, figé par la spécification |
| Impaire | Dictionnaire de **session**, construit dynamiquement |

Le dictionnaire **statique** contient plusieurs centaines de chaînes
prédéfinies : noms d’éléments SOAP, URI d’espaces de noms WS-*, noms
d’attributs courants. Il est identique pour toutes les implémentations et ne
se négocie pas.

Le dictionnaire de **session** permet à un émetteur de déclarer, en cours
d’échange, qu’une chaîne récurrente propre à l’application recevra désormais
un index. C’est particulièrement rentable pour les noms d’attributs
d’annuaire, qui se répètent à chaque objet renvoyé.

> L’usage du dictionnaire de session est signalé dès le préambule de cadrage,
> par la valeur d’encodage choisie. Une implémentation qui n’annonce que le
> XML binaire sans dictionnaire de session se prive de cette optimisation
> mais reste parfaitement interopérable.

```schema:wcf-encode-protocols
Figure 5 — La chaîne d’encodage d’un message : du document logique aux
octets protégés.
```

## Un exemple d’encodage

Considérons un fragment minimal.

```xml
<a:Action>http://schemas.xmlsoap.org/ws/2004/09/transfer/Get</a:Action>
```

Sa forme binaire enchaîne :

- un enregistrement d’élément à préfixe implicite `a`, désignant le nom
  `Action` par son index de dictionnaire ;
- un enregistrement de texte impair, portant l’URI de l’action, soit par son
  index de dictionnaire si elle y figure, soit sous forme de chaîne ;
- **aucun** enregistrement de fin, puisque la valeur impaire l’a implicité.

Ce qui occupe soixante-dix caractères en XML textuel tient en quelques
octets.

# La messagerie : SOAP 1.2

## L’enveloppe

Tous les messages ADWS sont des documents SOAP 1.2. La structure est
invariable : une enveloppe, un en-tête optionnel, un corps obligatoire.

```xml
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
            xmlns:a="http://www.w3.org/2005/08/addressing">
  <s:Header>
    <!-- metadonnees de routage et de correlation -->
  </s:Header>
  <s:Body>
    <!-- charge utile de l operation -->
  </s:Body>
</s:Envelope>
```

Rappelons que ce document ne circule **jamais** sous cette forme textuelle :
il est toujours encodé en binaire. La forme textuelle sert uniquement à
raisonner sur sa structure.

## Les espaces de noms

Un message ADWS mobilise une dizaine d’espaces de noms, chacun rattaché à une
spécification.

| Préfixe usuel | URI | Origine |
|---|---|---|
| `s` | `http://www.w3.org/2003/05/soap-envelope` | SOAP 1.2 |
| `a` | `http://www.w3.org/2005/08/addressing` | WS-Addressing 1.0 |
| `wxf` | `http://schemas.xmlsoap.org/ws/2004/09/transfer` | WS-Transfer |
| `wsen` | `http://schemas.xmlsoap.org/ws/2004/09/enumeration` | WS-Enumeration |
| `wse` | `http://schemas.xmlsoap.org/ws/2004/08/eventing` | WS-Eventing |
| `ad` | `http://schemas.microsoft.com/2008/1/ActiveDirectory` | Modèle AD |
| `addata` | `http://schemas.microsoft.com/2008/1/ActiveDirectory/Data` | Attributs AD |
| `da` | `http://schemas.microsoft.com/2006/11/IdentityManagement/DirectoryAccess` | IMDA |
| `ca` | `http://schemas.microsoft.com/2008/1/ActiveDirectory/CustomActions` | Actions AD |
| `adlq` | `http://schemas.microsoft.com/2008/1/ActiveDirectory/Dialect/LdapQuery` | Dialecte LDAP |

## Le modèle de faute

SOAP 1.2 impose une structure de faute unique, qui remplace le corps normal
de la réponse.

```xml
<s:Fault>
  <s:Code>
    <s:Value>s:Receiver</s:Value>
    <s:Subcode>
      <s:Value>ad:DirectoryError</s:Value>
    </s:Subcode>
  </s:Code>
  <s:Reason>
    <s:Text xml:lang="en">Description lisible de l erreur</s:Text>
  </s:Reason>
  <s:Detail>
    <!-- informations structurees specifiques -->
  </s:Detail>
</s:Fault>
```

Le champ `Code/Value` est contraint à cinq valeurs normalisées.

| Valeur | Sens |
|---|---|
| `s:VersionMismatch` | Version de SOAP non supportée |
| `s:MustUnderstand` | Un en-tête obligatoire n’a pas été compris |
| `s:DataEncodingUnknown` | Encodage de données inconnu |
| `s:Sender` | L’émetteur est responsable de l’erreur |
| `s:Receiver` | Le destinataire n’a pas pu traiter le message |

La distinction entre `Sender` et `Receiver` est opérationnelle : elle indique
au client si réessayer a un sens. Une faute `Sender` signifie que la requête
est mal formée et que la réémettre à l’identique échouera ; une faute
`Receiver` signale un problème côté service, potentiellement transitoire.

Le `Subcode` permet d’affiner sans sortir du cadre normalisé. C’est là que
sont portées les erreurs propres à l’annuaire.

# L’adressage : WS-Addressing

## Le rôle des en-têtes d’adressage

SOAP ne dit rien de la manière de nommer une opération ni de corréler une
réponse à sa requête. WS-Addressing comble ce manque avec un jeu d’en-têtes
transportés dans l’enveloppe.

| En-tête | Obligation | Rôle |
|---|---|---|
| `a:Action` | Obligatoire | Nomme l’opération demandée |
| `a:MessageID` | Obligatoire en requête | Identifie le message de façon unique |
| `a:To` | Obligatoire | Adresse du destinataire |
| `a:ReplyTo` | Obligatoire en requête | Où adresser la réponse |
| `a:RelatesTo` | Obligatoire en réponse | Rappelle l’identifiant de la requête |
| `a:FaultTo` | Optionnel | Où adresser une faute |
| `a:From` | Optionnel | Émetteur |

## L’en-tête Action

C’est l’en-tête déterminant : il désigne **l’opération**, et non la
ressource. Un service ADWS choisit son traitement à partir de cette seule
valeur.

```xml
<a:Action s:mustUnderstand="1">
  http://schemas.xmlsoap.org/ws/2004/09/transfer/Get
</a:Action>
```

L’attribut `mustUnderstand` positionné à `1` signifie que le destinataire
doit refuser le message s’il ne sait pas traiter cet en-tête. Il ne s’agit
pas de comprendre l’action elle-même, mais de reconnaître le mécanisme
d’adressage.

## La corrélation requête-réponse

Le mécanisme est simple et strict.

- La requête porte un `a:MessageID` unique, généralement de la forme
  `urn:uuid:` suivie d’un identifiant.
- La réponse **doit** porter un `a:RelatesTo` reprenant cette valeur
  **à l’identique**.

Cette règle n’admet aucune exception, y compris pour les fautes. Une faute
sans `a:RelatesTo` est, du point de vue du client, un message non sollicité.

> C’est la source d’un symptôme déroutant : une commande qui ne rend jamais
> la main. Le service a bien répondu, la réponse est bien arrivée, mais faute
> de corrélation le client l’ignore et continue d’attendre jusqu’à
> expiration de son délai. Le réseau paraît sain, le service paraît muet.

## L’adresse anonyme

L’en-tête `a:ReplyTo` porte une adresse de réponse. Dans un échange
requête-réponse sur une connexion déjà établie, cette adresse prend une
valeur conventionnelle qui signifie « réponds sur le canal existant ».

```xml
<a:ReplyTo>
  <a:Address>http://www.w3.org/2005/08/addressing/anonymous</a:Address>
</a:ReplyTo>
```

Cette valeur, dite **adresse anonyme**, évite au service d’avoir à ouvrir une
connexion vers le client, ce qui serait impraticable à travers un pare-feu.

## Les références de point de terminaison

WS-Addressing définit une structure permettant de désigner une ressource de
façon portable : l’*Endpoint Reference*, ou EPR. Elle combine une adresse et
un ensemble de propriétés de référence qui identifient la ressource au sein
du service.

```xml
<a:EndpointReference>
  <a:Address>net.tcp://dc.exemple.local:9389/...</a:Address>
  <a:ReferenceParameters>
    <ad:instance>11111111-1111-1111-1111-111111111111</ad:instance>
    <ad:objectReferenceProperty>...</ad:objectReferenceProperty>
  </a:ReferenceParameters>
</a:EndpointReference>
```

Cette structure est renvoyée après une création d’objet : elle constitue le
« reçu » que le client conservera pour désigner la ressource nouvellement
créée.

## Les en-têtes propres à l’annuaire

Deux en-têtes complètent l’adressage pour identifier une ressource
d’annuaire.

| En-tête | Contenu | Rôle |
|---|---|---|
| `ad:instance` | Un identifiant fixe | Désigne l’instance d’annuaire visée |
| `ad:objectReferenceProperty` | Identifiant de l’objet | Désigne l’objet visé |

L’en-tête d’instance porte une valeur conventionnelle unique lorsqu’un
service ne dessert qu’un annuaire. L’en-tête de référence d’objet accepte
plusieurs formes de désignation : identifiant globalement unique, nom
distinctif, ou identifiant de sécurité.

# Le transfert de ressource : WS-Transfer

## Le modèle

WS-Transfer traite l’annuaire comme un ensemble de **ressources** adressables.
Chaque objet — utilisateur, ordinateur, groupe, unité d’organisation — est une
ressource dotée d’une représentation XML. Le protocole définit quatre
opérations, calquées sur le cycle de vie d’une ressource.

| Opération | Action | Effet |
|---|---|---|
| Get | `.../transfer/Get` | Lire la représentation d’une ressource |
| Put | `.../transfer/Put` | Remplacer la représentation |
| Create | `.../transfer/Create` | Créer une ressource |
| Delete | `.../transfer/Delete` | Supprimer une ressource |

La ressource visée n’est **pas** nommée dans le corps du message : elle l’est
par les en-têtes d’adressage. Le corps d’un Get est d’ailleurs vide.

## L’opération Get

La requête est minimale. Toute l’information tient dans les en-têtes.

```xml
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
            xmlns:a="http://www.w3.org/2005/08/addressing"
            xmlns:ad="http://schemas.microsoft.com/2008/1/ActiveDirectory">
  <s:Header>
    <a:Action s:mustUnderstand="1">
      http://schemas.xmlsoap.org/ws/2004/09/transfer/Get</a:Action>
    <a:MessageID>urn:uuid:11111111-2222-3333-4444-555555555555</a:MessageID>
    <a:To s:mustUnderstand="1">net.tcp://dc.exemple.local:9389/...</a:To>
    <a:ReplyTo>
      <a:Address>http://www.w3.org/2005/08/addressing/anonymous</a:Address>
    </a:ReplyTo>
    <ad:instance>11111111-1111-1111-1111-111111111111</ad:instance>
    <ad:objectReferenceProperty>
      CN=Administrator,CN=Users,DC=exemple,DC=local
    </ad:objectReferenceProperty>
  </s:Header>
  <s:Body/>
</s:Envelope>
```

La réponse porte la représentation complète de l’objet, dans un élément dont
le **nom est la classe structurelle** de l’objet.

```xml
<s:Body>
  <addata:user
      xmlns:addata="http://schemas.microsoft.com/2008/1/ActiveDirectory/Data"
      xmlns:ad="http://schemas.microsoft.com/2008/1/ActiveDirectory"
      xmlns:xsd="http://www.w3.org/2001/XMLSchema"
      xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
    <ad:objectReferenceProperty>
      <ad:value xsi:type="xsd:string">f6aac55f-...</ad:value>
    </ad:objectReferenceProperty>
    <addata:cn LdapSyntax="UnicodeString">
      <ad:value xsi:type="xsd:string">Administrator</ad:value>
    </addata:cn>
    <addata:objectSid LdapSyntax="SidString">
      <ad:value xsi:type="xsd:base64Binary">AQUAAAAAAAUV...</ad:value>
    </addata:objectSid>
    <ad:distinguishedName>
      <ad:value xsi:type="xsd:string">CN=Administrator,...</ad:value>
    </ad:distinguishedName>
  </addata:user>
</s:Body>
```

Trois règles de forme méritent attention.

- Chaque attribut d’annuaire est un élément de l’espace `addata`, portant un
  attribut `LdapSyntax` qui nomme sa syntaxe.
- Chaque valeur est un élément `ad:value` portant un attribut `xsi:type` qui
  donne son type XSD. Un attribut multivalué contient plusieurs `ad:value`.
- Certains éléments relèvent de l’espace `ad` et non `addata` : ce sont des
  **attributs synthétiques**, calculés par le service et non stockés tels
  quels. Ils ne portent pas de `LdapSyntax`.

## L’opération Create

La requête porte, dans son corps, la représentation de l’objet à créer, dans
la même forme que celle renvoyée par un Get.

La réponse n’est pas l’objet créé mais un **accusé** contenant une référence
de point de terminaison désignant la ressource nouvelle.

```xml
<s:Body>
  <wxf:ResourceCreated
      xmlns:wxf="http://schemas.xmlsoap.org/ws/2004/09/transfer">
    <a:Address>net.tcp://dc.exemple.local:9389/...</a:Address>
    <a:ReferenceParameters>
      <ad:instance>11111111-1111-1111-1111-111111111111</ad:instance>
      <ad:objectReferenceProperty>...</ad:objectReferenceProperty>
    </a:ReferenceParameters>
  </wxf:ResourceCreated>
</s:Body>
```

## L’opération Put

Malgré son nom, Put ne remplace pas nécessairement l’objet entier. Dans le
contexte de l’annuaire, il porte une **liste de modifications** ciblées, ce
qui évite d’avoir à réécrire l’ensemble des attributs.

Chaque modification déclare un mode d’opération.

| Mode | Effet |
|---|---|
| `add` | Ajoute une ou plusieurs valeurs à un attribut |
| `delete` | Retire une ou plusieurs valeurs |
| `replace` | Remplace l’ensemble des valeurs de l’attribut |

Le mode `replace` avec une liste de valeurs vide équivaut à supprimer
l’attribut.

## L’opération Delete

Requête et réponse sont vides : l’objet visé par les en-têtes est supprimé,
et la réponse ne fait que confirmer. La suppression récursive d’une
sous-arborescence relève d’un contrôle LDAP transporté en en-tête, décrit
plus loin.

# L’accès annuaire : IMDA [MS-WSTIM] et [MS-WSDS]

## Deux façons de lire un objet

ADWS offre **deux formulations distinctes** pour lire un objet, issues de
deux familles de spécifications.

- **WS-Transfer** renvoie la représentation entière, dans un élément nommé
  d’après la classe de l’objet.
- **IMDA**, pour *Identity Management Directory Access*, permet de demander
  un **sous-ensemble d’attributs** et renvoie chaque attribut isolément.

Le choix n’appartient pas au service : il découle de la requête émise par le
client. Un service doit répondre dans la forme correspondant à la question
posée.

## La requête IMDA de lecture

Elle est portée par un élément dédié dans le corps du message.

```xml
<s:Body>
  <da:BaseObjectSearchRequest
      xmlns:da="http://schemas.microsoft.com/2006/11/IdentityManagement/DirectoryAccess"
      Dialect="http://schemas.microsoft.com/2008/1/ActiveDirectory/Dialect/LdapQuery">
    <da:AttributeType>addata:cn</da:AttributeType>
    <da:AttributeType>addata:objectSid</da:AttributeType>
  </da:BaseObjectSearchRequest>
</s:Body>
```

Deux cas se présentent selon que des `da:AttributeType` sont listés ou non.

### Cas 1 : des attributs sont demandés

La réponse place **chaque attribut dans son propre conteneur**.

```xml
<s:Body>
  <da:BaseObjectSearchResponse
      xmlns:da="http://schemas.microsoft.com/2006/11/IdentityManagement/DirectoryAccess">
    <da:PartialAttribute>
      <addata:cn LdapSyntax="UnicodeString">
        <ad:value xsi:type="xsd:string">Administrator</ad:value>
      </addata:cn>
    </da:PartialAttribute>
    <da:PartialAttribute>
      <addata:objectSid LdapSyntax="SidString">
        <ad:value xsi:type="xsd:base64Binary">AQUAAAAAAAUV...</ad:value>
      </addata:objectSid>
    </da:PartialAttribute>
    <da:PartialAttribute>
      <ad:distinguishedName>
        <ad:value xsi:type="xsd:string">CN=Administrator,...</ad:value>
      </ad:distinguishedName>
    </da:PartialAttribute>
  </da:BaseObjectSearchResponse>
</s:Body>
```

Une règle est constante : le **nom distinctif est toujours renvoyé**, même
s’il n’a pas été demandé. Il l’est comme attribut synthétique, dans l’espace
`ad`, sans `LdapSyntax`.

### Cas 2 : aucun attribut n’est demandé

La réponse place la représentation entière de l’objet — dans la forme
WS-Transfer — à l’intérieur d’un **unique** conteneur `da:PartialAttribute`.

> Se tromper de forme est une erreur silencieuse côté service et bruyante
> côté client : la désérialisation échoue en signalant qu’un élément de fin
> était attendu à l’endroit où apparaît un élément inattendu.

## La modification IMDA

Symétriquement, IMDA définit une requête de modification portant une liste
de changements, chacun désignant un attribut, un mode d’opération et des
valeurs.

# L’énumération : WS-Enumeration

## Le problème

Une recherche d’annuaire peut renvoyer des dizaines de milliers d’objets. Les
transmettre dans une seule réponse serait impraticable. WS-Enumeration
définit un mécanisme de **curseur** : le service constitue un jeu de
résultats, en remet un identifiant au client, et celui-ci le consomme par
tranches.

```schema:ws-enumeration-protocols
Figure 6 — Le cycle d’énumération : constitution du contexte, consommation
par tranches successives, puis libération.
```

## Les cinq opérations

| Opération | Action | Rôle |
|---|---|---|
| Enumerate | `.../enumeration/Enumerate` | Ouvre un contexte de résultats |
| Pull | `.../enumeration/Pull` | Consomme une tranche de résultats |
| Renew | `.../enumeration/Renew` | Prolonge la validité du contexte |
| GetStatus | `.../enumeration/GetStatus` | Interroge l’état du contexte |
| Release | `.../enumeration/Release` | Libère le contexte |

## L’ouverture

La requête porte le critère de recherche, exprimé dans un dialecte identifié
par une URI. Pour l’annuaire, le dialecte est celui des requêtes LDAP.

```xml
<s:Body>
  <wsen:Enumerate xmlns:wsen="http://schemas.xmlsoap.org/ws/2004/09/enumeration">
    <wsen:Filter
        Dialect="http://schemas.microsoft.com/2008/1/ActiveDirectory/Dialect/LdapQuery">
      <adlq:LdapQuery
          xmlns:adlq="http://schemas.microsoft.com/2008/1/ActiveDirectory/Dialect/LdapQuery">
        <adlq:Filter>(objectClass=user)</adlq:Filter>
        <adlq:BaseObject>DC=exemple,DC=local</adlq:BaseObject>
        <adlq:Scope>Subtree</adlq:Scope>
        <adlq:AttributeList>
          <ad:SelectionProperty>addata:cn</ad:SelectionProperty>
        </adlq:AttributeList>
      </adlq:LdapQuery>
    </wsen:Filter>
  </wsen:Enumerate>
</s:Body>
```

Le champ `Scope` reprend la sémantique LDAP.

| Valeur | Portée |
|---|---|
| `Base` | L’objet de base seulement |
| `OneLevel` | Les enfants directs de l’objet de base |
| `Subtree` | L’objet de base et toute sa descendance |

La réponse remet un **contexte d’énumération** et une date d’expiration.

```xml
<s:Body>
  <wsen:EnumerateResponse
      xmlns:wsen="http://schemas.xmlsoap.org/ws/2004/09/enumeration">
    <wsen:EnumerationContext>a1b2c3d4-...</wsen:EnumerationContext>
    <wsen:Expires>2026-08-13T14:32:00Z</wsen:Expires>
  </wsen:EnumerateResponse>
</s:Body>
```

## La consommation

Chaque Pull rappelle le contexte et déclare combien d’éléments le client est
prêt à recevoir.

```xml
<s:Body>
  <wsen:Pull xmlns:wsen="http://schemas.xmlsoap.org/ws/2004/09/enumeration">
    <wsen:EnumerationContext>a1b2c3d4-...</wsen:EnumerationContext>
    <wsen:MaxElements>256</wsen:MaxElements>
  </wsen:Pull>
</s:Body>
```

Trois limites peuvent être exprimées.

| Élément | Limite portée sur |
|---|---|
| `MaxElements` | Le nombre d’objets renvoyés |
| `MaxCharacters` | La taille de la réponse |
| `MaxTime` | Le temps que le service peut consacrer |

La réponse porte les objets, dans la même forme que celle d’un Get
WS-Transfer, et **l’un ou l’autre** de deux éléments terminaux.

- `wsen:EnumerationContext` : d’autres objets restent à lire.
- `wsen:EndOfSequence` : le jeu de résultats est épuisé.

La présence de `EndOfSequence` est le seul signal fiable de fin. Un Pull
renvoyant moins d’objets que demandé ne signifie pas que le jeu est épuisé.

## L’expiration et la libération

Un contexte a une durée de vie limitée. Le client peut la prolonger par
Renew, s’enquérir de l’état par GetStatus, et doit libérer le contexte par
Release dès qu’il n’en a plus besoin. Un contexte abandonné expire de
lui-même.

> Le contexte est une **ressource d’état côté service**. Cela a une
> conséquence d’architecture importante : les Pull successifs doivent
> atteindre l’instance qui détient le contexte. Un répartiteur de charge qui
> disperserait les requêtes d’une même énumération sur plusieurs instances
> provoquerait des erreurs de contexte inconnu.

# La notification : WS-Eventing

WS-Eventing définit un mécanisme d’abonnement à des notifications
d’événements. Le client souscrit, reçoit des notifications, puis se
désabonne.

| Opération | Action | Rôle |
|---|---|---|
| Subscribe | `.../eventing/Subscribe` | Créer un abonnement |
| Renew | `.../eventing/Renew` | Prolonger un abonnement |
| GetStatus | `.../eventing/GetStatus` | Interroger l’état d’un abonnement |
| Unsubscribe | `.../eventing/Unsubscribe` | Résilier un abonnement |

Un abonnement porte une adresse de livraison, un filtre désignant les
événements d’intérêt, et une durée de validité.

> La place de WS-Eventing dans le périmètre ADWS est marginale. Les
> opérations courantes d’administration d’annuaire ne l’emploient pas. Il est
> décrit ici pour l’exhaustivité de l’empilement, sans qu’un scénario
> d’administration usuel s’y ramène.

# Les contrôles LDAP transportés [MS-WSPELD]

## Le principe

LDAP définit des **contrôles** : des modificateurs de comportement attachés à
une opération, identifiés par un OID. ADWS permet de transporter ces
contrôles dans les en-têtes SOAP, ce qui donne accès à des comportements
d’annuaire qui n’ont pas d’équivalent dans les spécifications WS-*.

```xml
<s:Header>
  <ad:controls xmlns:ad="http://schemas.microsoft.com/2008/1/ActiveDirectory">
    <ad:control type="1.2.840.113556.1.4.417" criticality="true"/>
  </ad:controls>
</s:Header>
```

L’attribut de criticité est déterminant : lorsqu’il vaut vrai, un service
incapable d’honorer le contrôle **doit** rejeter l’opération plutôt que de
l’exécuter en ignorant le contrôle.

## Les contrôles usuels

| OID | Nom | Effet |
|---|---|---|
| `1.2.840.113556.1.4.319` | Paged Results | Pagination des résultats |
| `1.2.840.113556.1.4.417` | Show Deleted | Rend visibles les objets supprimés |
| `1.2.840.113556.1.4.529` | Extended DN | Enrichit les DN renvoyés |
| `1.2.840.113556.1.4.801` | SD Flags | Sélectionne les parties du descripteur de sécurité |
| `1.2.840.113556.1.4.805` | Tree Delete | Supprime récursivement une sous-arborescence |
| `1.2.840.113556.1.4.841` | Dirsync | Renvoie les changements depuis un jeton |
| `1.2.840.113556.1.4.1338` | Verify Name | Vérifie un nom auprès d’un DC donné |
| `1.2.840.113556.1.4.1339` | Domain Scope | Interdit le renvoi vers un autre domaine |
| `1.2.840.113556.1.4.1340` | Search Options | Options de recherche diverses |
| `1.2.840.113556.1.4.1413` | Permissive Modify | Tolère les modifications sans effet |
| `1.2.840.113556.1.4.2064` | Show Recycled | Rend visibles les objets recyclés |

Le contrôle **SD Flags** mérite une mention particulière. Le descripteur de
sécurité d’un objet comporte quatre parties : propriétaire, groupe, liste de
contrôle d’accès discrétionnaire et liste d’audit. Lire cette dernière exige
un privilège élevé. Le contrôle permet de ne demander que les parties
nécessaires, et donc d’éviter un refus d’accès sur une lecture qui aurait
autrement réussi.

## Les règles de correspondance étendues

Les filtres LDAP admettent des opérateurs particuliers, également désignés
par des OID, qui s’écrivent dans le filtre lui-même.

| OID | Nom | Sémantique |
|---|---|---|
| `1.2.840.113556.1.4.803` | Bitwise AND | Tous les bits du masque sont posés |
| `1.2.840.113556.1.4.804` | Bitwise OR | Au moins un bit du masque est posé |
| `1.2.840.113556.1.4.1941` | In Chain | Correspondance transitive sur une chaîne |

La règle **In Chain** est celle qui permet de résoudre l’appartenance
récursive à des groupes en une seule requête, en suivant les imbrications.

```text
(memberOf:1.2.840.113556.1.4.1941:=CN=Admins,OU=Groupes,DC=exemple,DC=local)
```

# Le modèle de données [MS-ADDM] et [MS-ADTS]

## Objets, classes et attributs

Un annuaire Active Directory est un arbre d’**objets**. Chaque objet
appartient à une ou plusieurs **classes**, dont l’une est dite structurelle
et détermine sa nature. Chaque objet porte des **attributs**, dont le schéma
définit la syntaxe et la cardinalité.

Trois identifiants coexistent pour désigner un objet.

| Identifiant | Nature | Stabilité |
|---|---|---|
| Nom distinctif | Chemin dans l’arbre | Change si l’objet est déplacé |
| Identifiant global | Valeur binaire de 16 octets | Immuable |
| Identifiant de sécurité | Valeur binaire variable | Immuable, principaux seulement |

L’identifiant global est le seul désignateur véritablement stable ; c’est lui
que les références de point de terminaison privilégient.

## Les syntaxes d’attribut

Le schéma associe à chaque attribut une syntaxe, qui détermine comment sa
valeur est représentée sur le fil.

| Syntaxe | Type XSD sur le fil | Exemple d’attribut |
|---|---|---|
| `UnicodeString` | `xsd:string` | `cn`, `description` |
| `IA5String` | `xsd:string` | Chaînes ASCII |
| `Integer` | `xsd:int` | `userAccountControl` |
| `Integer8` | `xsd:long` | `pwdLastSet`, `accountExpires` |
| `Bool` | `xsd:boolean` | Indicateurs |
| `OctetString` | `xsd:base64Binary` | `objectGUID` |
| `SidString` | `xsd:base64Binary` | `objectSid` |
| `NTSecurityDescriptor` | `xsd:base64Binary` | `nTSecurityDescriptor` |
| `GeneralizedTimeString` | `xsd:dateTime` | `whenCreated` |
| `DNString` | `xsd:string` | `member`, `manager` |
| `ObjectIdentifier` | `xsd:string` | Identifiants de schéma |

## Les attributs à sémantique particulière

Certains attributs demandent une interprétation qui ne découle pas de leur
syntaxe.

| Attribut | Interprétation |
|---|---|
| `userAccountControl` | Champ de bits : compte désactivé, mot de passe non expirant, etc. |
| `pwdLastSet` | Intervalles de 100 ns depuis 1601 ; `0` signifie « changement requis » |
| `accountExpires` | Même échelle ; `0` et la valeur maximale signifient « jamais » |
| `objectSid` | Structure binaire, présentée textuellement sous la forme `S-1-5-...` |
| `unicodePwd` | Mot de passe, encodé en UTF-16 et entouré de guillemets doubles |
| `member` | Multivalué, contient des noms distinctifs |
| `tokenGroups` | Calculé à la demande, jamais stocké |

L’attribut `unicodePwd` mérite un développement. Il n’est jamais lisible :
toute tentative de lecture échoue. Son écriture obéit à une convention
stricte — la chaîne du mot de passe est entourée de guillemets doubles, puis
encodée en UTF-16 en ordre petit-boutiste, et le résultat est transmis
comme une suite d’octets.

Deux modes d’écriture existent, aux exigences de privilège différentes.

| Mode | Contenu de l’opération | Privilège requis |
|---|---|---|
| Réinitialisation | Un remplacement de la nouvelle valeur | Droit de réinitialiser |
| Changement | Une suppression de l’ancienne, puis un ajout de la nouvelle | Connaissance de l’ancien |

## Les attributs construits

Certains attributs ne sont pas stockés mais **calculés** au moment de la
lecture. Ils ne sont renvoyés que s’ils sont demandés explicitement.

| Attribut | Calcul |
|---|---|
| `canonicalName` | Le nom distinctif réécrit en notation de chemin |
| `tokenGroups` | L’ensemble transitif des groupes du principal |
| `allowedAttributes` | Les attributs autorisés par le schéma pour cette classe |
| `msDS-PrincipalName` | Le nom du principal sous forme domaine et compte |

## L’objet racine

Un objet particulier, la **racine du service d’annuaire**, se lit sans
authentification préalable dans LDAP et décrit les capacités du serveur. Il
n’a ni classe ni nom distinctif : il s’interroge par une lecture de portée
« base » sur un nom vide.

Ses attributs les plus utiles :

| Attribut | Contenu |
|---|---|
| `defaultNamingContext` | Le contexte de nommage du domaine |
| `configurationNamingContext` | Le contexte de configuration |
| `schemaNamingContext` | Le contexte de schéma |
| `rootDomainNamingContext` | Le domaine racine de la forêt |
| `dnsHostName` | Le nom DNS du contrôleur |
| `serverName` | Le nom distinctif de l’objet serveur |
| `supportedControl` | La liste des OID de contrôles supportés |
| `supportedCapabilities` | La liste des capacités du serveur |
| `domainFunctionality` | Le niveau fonctionnel du domaine |
| `forestFunctionality` | Le niveau fonctionnel de la forêt |
| `highestCommittedUSN` | Le plus grand numéro de séquence appliqué |

# Les fautes propres à l’annuaire

## Le mécanisme

Les erreurs d’annuaire sont portées par le `Subcode` de la faute SOAP, ce qui
permet au client de les distinguer programmatiquement sans analyser un
message en langue naturelle.

| Sous-code | Cause |
|---|---|
| `DirectoryError` | Erreur d’annuaire générique |
| `InsufficientAccessRights` | Droits insuffisants sur l’objet visé |
| `ConstraintViolation` | Contrainte violée : mot de passe trop faible, attribut requis absent |
| `ObjectClassViolation` | Classe d’objet incompatible avec l’opération |
| `EntryAlreadyExists` | Un objet occupe déjà le nom distinctif demandé |
| `NoSuchObject` | L’objet visé n’existe pas |
| `InvalidAttributeSyntax` | Valeur incompatible avec la syntaxe de l’attribut |
| `UnwillingToPerform` | Le service refuse l’opération |
| `ReferralError` | L’objet relève d’un autre contrôleur |

## La lecture d’une faute

Une faute bien formée porte quatre informations exploitables : la
responsabilité, par `Code/Value` ; la nature, par `Subcode` ; une description
lisible, par `Reason/Text` ; et la corrélation, par l’en-tête `a:RelatesTo`.

```xml
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
            xmlns:a="http://www.w3.org/2005/08/addressing">
  <s:Header>
    <a:Action>
      http://schemas.xmlsoap.org/ws/2004/08/addressing/fault</a:Action>
    <a:RelatesTo>urn:uuid:11111111-2222-3333-4444-555555555555</a:RelatesTo>
  </s:Header>
  <s:Body>
    <s:Fault>
      <s:Code>
        <s:Value>s:Sender</s:Value>
        <s:Subcode>
          <s:Value>ad:NoSuchObject</s:Value>
        </s:Subcode>
      </s:Code>
      <s:Reason>
        <s:Text xml:lang="en">The object does not exist.</s:Text>
      </s:Reason>
    </s:Fault>
  </s:Body>
</s:Envelope>
```

# Synthèse : une opération de bout en bout

## Ce que fait réellement une commande d’administration

Reprenons la demande « lis-moi l’objet utilisateur Administrator » et suivons-la
à travers toutes les couches décrites.

| Étape | Couche | Ce qui circule |
|---|---|---|
| 1 | DNS | Recherche des enregistrements SRV du domaine |
| 2 | TCP | Ouverture d’une connexion vers le port 9389 |
| 3 | MS-NMF | Version, Mode, Via, KnownEncoding, demande d’élévation |
| 4 | MS-NMF | Accord d’élévation renvoyé par le service |
| 5 | MS-NNS | En-tête de handshake portant un jeton SPNEGO |
| 6 | RFC 4178 | NegTokenInit : liste de mécanismes et AP-REQ joint |
| 7 | RFC 4120 | Validation du ticket, extraction de la clé de session |
| 8 | RFC 4178 | NegTokenResp : mécanisme retenu et AP-REP |
| 9 | MS-NNS | HandshakeDone : le contexte est établi |
| 10 | RFC 4121 | Chaque message est désormais chiffré et signé |
| 11 | MS-NMF | PreambleEnd et PreambleAck, déjà protégés |
| 12 | MS-NBFX | La requête SOAP est encodée en enregistrements binaires |
| 13 | SOAP | Enveloppe portant l’action WS-Transfer Get |
| 14 | WS-Addressing | En-têtes d’action, d’identifiant et de destination |
| 15 | MS-ADDM | Réponse : représentation de l’objet, attribut par attribut |
| 16 | MS-NMF | Enregistrement de fin, ou fermeture de la connexion |

## Le coût d’une session

Une session complète mobilise, au minimum, un aller-retour DNS, un
établissement TCP, un préambule sans réponse, deux à trois allers-retours
d’authentification, un aller-retour de fin de préambule, puis un
aller-retour par opération applicative.

C’est pourquoi les clients **réutilisent la connexion** : le coût
d’établissement est intégralement amorti dès la seconde commande. Une suite
de commandes successives sur le même serveur ne rejoue ni la découverte, ni
l’authentification.

## Lire une capture réseau

Une capture ADWS se lit en trois zones, dont les frontières sont
identifiables sans déchiffrement.

| Zone | Repère de début | Lisibilité |
|---|---|---|
| Préambule | Premier octet `0x00` après l’établissement | Entièrement lisible |
| Négociation | Après l’octet `0x0A` du service | En-têtes lisibles, jetons opaques |
| Applicatif | Après l’en-tête de MessageId `0x14` | Longueurs seules |

Dans la zone de préambule, l’enregistrement Via révèle en clair le point de
terminaison visé. Dans la zone de négociation, la séquence `0x60` suivie de
l’OID SPNEGO marque le premier jeton, et l’identifiant `0x01 0x00` confirme
la présence d’un AP-REQ Kerberos. Au-delà, seules les tailles de blocs restent
observables.

## Glossaire des sigles

| Sigle | Développement |
|---|---|
| ADWS | Active Directory Web Services |
| AP-REQ, AP-REP | Messages de présentation de ticket Kerberos |
| DN | Distinguished Name, nom distinctif |
| EPR | Endpoint Reference, référence de point de terminaison |
| GSS-API | Generic Security Service Application Program Interface |
| IMDA | Identity Management Directory Access |
| KDC | Key Distribution Center |
| MIC | Message Integrity Code |
| NMF | .NET Message Framing |
| NNS | .NET NegotiateStream |
| OID | Object Identifier |
| SPN | Service Principal Name |
| SPNEGO | Simple and Protected GSS-API Negotiation Mechanism |
| TGT | Ticket Granting Ticket |
| USN | Update Sequence Number |
