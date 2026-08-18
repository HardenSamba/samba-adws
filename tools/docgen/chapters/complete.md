# Partie I. Guide de référence des protocoles

## Ce que ce guide explique

Active Directory Web Services (ADWS) est le service par lequel les outils
d’administration Microsoft modernes parlent à un contrôleur de domaine. Il
écoute sur le port **9389/tcp** et n’est pas un protocole unique : c’est un
**empilement** d’une dizaine de protocoles distincts, chacun normalisé
séparément, qui coopèrent pour transporter une requête d’annuaire.

Ce guide décrit chacun de ces protocoles pour lui-même : *comment il parle*,
*quels messages il définit*, *quelles réponses il autorise*, *quelles
options il offre*, et *comment il s’articule avec ses voisins*. Il ne décrit
aucune implémentation particulière. Il ne contient aucun extrait de
programme. Un lecteur qui l’aura parcouru doit pouvoir lire une capture
réseau ADWS et nommer chaque octet qu’il y voit.

### Ce que le guide couvre

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

### Conventions de lecture

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

### Le principe d’encapsulation

Une requête d’administration traverse l’intégralité de la pile. Prenons la
demande « lis-moi l’objet utilisateur Administrator ». Elle existe
successivement sous six formes :

1. Une intention applicative : lire un objet d’annuaire.
2. Un document SOAP 1.2 avec des en-têtes WS-Addressing qui nomment
  l’opération et identifient le message.
3. Une suite d’enregistrements binaires qui encodent ce document sans
  jamais écrire de balise textuelle.
4. Un jeton GSS-API qui chiffre et signe cette suite d’octets.
5. Un enregistrement de cadrage .NET qui préfixe le tout d’un type et
  d’une longueur.
6. Un flux d’octets TCP.

Chaque couche ignore le contenu des couches supérieures. Cette indépendance
est ce qui permet de décrire les protocoles un par un.

## Le rôle d’ADWS et ses points de terminaison

### Pourquoi ce service existe

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
- une **sémantique d’opération** normalisée par les spécifications WS-*,
  avec des mécanismes standards d’énumération paginée et de gestion
  d’erreur.

Les outils qui en dépendent exclusivement sont le module PowerShell
`ActiveDirectory` (l’ensemble des cmdlets `*-AD*`) et le Centre
d’administration Active Directory, qui n’est qu’une interface graphique
posée sur ce même module. Sans ADWS joignable, ces outils échouent dès la
première commande, alors même que LDAP et Kerberos fonctionnent
parfaitement.

### Comment un client trouve le service

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

Retenons que **rien de tout cela n’est du protocole ADWS** : la découverte
est entièrement à la charge du client et repose sur DNS. Un service ADWS n’a
aucun moyen d’influer sur la sélection.

Lorsque cette chaîne échoue, le client rapporte qu’il ne trouve pas de
serveur par défaut exécutant Active Directory Web Services. Le message
recouvre trois causes très différentes : aucun DC trouvé par DNS, DC trouvé
mais port 9389 injoignable, ou port ouvert mais négociation échouée.

### Les points de terminaison

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
par Kerberos. Le préfixe `UserName/` correspond à un mode où des
identifiants explicites sont portés dans le message lui-même, protégé par
TLS ; ce mode suppose qu’un certificat serveur ait pu être provisionné, et
il est rarement rencontré en pratique.

Un point de terminaison supplémentaire publie les **métadonnées** du
service. Il permet à un outil générique de découvrir les contrats offerts
sans les connaître à l’avance.

> Le chemin demandé est transmis très tôt dans la connexion, avant toute
> authentification, par un enregistrement de cadrage dédié. Le service peut
> donc refuser une adresse inconnue sans jamais engager de négociation
> cryptographique.

### Le cycle de vie d’une connexion

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
  chiffré, circule dans un enregistrement de cadrage. Plusieurs requêtes se
  succèdent sur la même connexion.
- **5. Terminaison.** Un enregistrement de fin clôt proprement l’échange.

Les temps 1 et 2 sont observables en clair dans une capture réseau. À partir
du temps 4, tout est chiffré : une capture ne montre plus que des longueurs
et des octets opaques.

## Le cadrage : .NET Message Framing [MS-NMF]

### Le problème que résout ce protocole

TCP transporte un flux d’octets sans frontières. Il faut donc un mécanisme
qui délimite les messages, et qui permette en outre de négocier des
paramètres avant tout échange applicatif. C’est le rôle du .NET Message
Framing, désigné par sa spécification **[MS-NMF]**.

Le protocole définit un vocabulaire d’**enregistrements** (*records*).
Chaque enregistrement commence par un octet qui donne son type ; le reste
dépend du type. Certains enregistrements servent uniquement à la mise en
place de la connexion, d’autres transportent les messages applicatifs.

### Les quatre modes d’échange

MS-NMF prévoit quatre modes, choisis par le client au tout début de la
connexion.

| Mode | Valeur | Sémantique |
|---|---|---|
| Singleton-Unsized | `0x01` | Un seul message, longueur non annoncée |
| Duplex | `0x02` | Messages bidirectionnels multiples |
| Simplex | `0x03` | Messages unidirectionnels |
| Singleton-Sized | `0x04` | Un seul message, longueur annoncée |

ADWS emploie le mode **Duplex**. C’est le seul qui autorise une conversation
: plusieurs requêtes et plusieurs réponses sur une même connexion, dans les
deux sens, ce qu’exige un client qui enchaîne des commandes.

### L’encodage des entiers

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

### Le catalogue des enregistrements

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

### Le préambule

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

#### L’enregistrement Version

Il annonce la version du cadrage lui-même, sous la forme de deux octets :
majeure puis mineure. La valeur employée est la version 1.0. Ce champ ne
décrit ni la version d’ADWS ni celle de l’annuaire.

#### L’enregistrement Via

Il porte l’**URL complète** que le client souhaite atteindre, préfixée de sa
longueur en varint. C’est cet enregistrement qui sélectionne le point de
terminaison. Comme il circule en clair et avant authentification, il est
visible dans toute capture réseau et constitue le moyen le plus simple
d’identifier ce que cherche un client.

#### L’enregistrement KnownEncoding

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

#### La demande d’élévation

Le client émet enfin un enregistrement **UpgradeRequest** dont la charge
utile est une chaîne nommant le protocole d’élévation souhaité. Pour une
authentification intégrée, cette chaîne est `application/negotiate`.

Le service répond par un **UpgradeResponse** vide, qui vaut acceptation. À
partir de cet instant précis, le flux TCP ne transporte plus des
enregistrements de cadrage mais le protocole d’élévation, jusqu’à ce que
celui-ci soit terminé.

> C’est le point charnière de toute la connexion. Avant l’UpgradeResponse,
> on lit du cadrage. Juste après, on lit du NegotiateStream. Plus tard, on
> relit du cadrage, mais chiffré. Confondre ces trois régimes est l’erreur
> la plus fréquente dans l’analyse d’une capture ADWS.

### La fin de préambule

Une fois la sécurité établie, le client émet un enregistrement
**PreambleEnd**, auquel le service répond par un **PreambleAck**. Ces deux
enregistrements circulent déjà **protégés** par le contexte de sécurité qui
vient d’être négocié : ils constituent la première preuve que le canal
fonctionne dans les deux sens.

### Les fautes de cadrage

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

### La terminaison

L’enregistrement **End** clôt l’échange. Il est émis par la partie qui n’a
plus rien à transmettre. Sur le terrain, une connexion ADWS se termine
fréquemment par une simple fermeture TCP après une période d’inactivité,
sans End explicite : les deux comportements se rencontrent.

## L’élévation de sécurité : NegotiateStream [MS-NNS]

### Ce que NegotiateStream apporte

Une fois l’élévation acceptée, le flux TCP est confié au protocole
**NegotiateStream**, spécifié par **[MS-NNS]**. Son rôle est double :

- **pendant la négociation**, transporter les jetons d’authentification
  entre le client et le service, dans les deux sens, autant de fois que
  nécessaire ;
- **après la négociation**, délimiter les blocs de données protégées,
  puisque le chiffrement produit des blocs dont la taille diffère de celle
  du texte clair.

NegotiateStream ne réalise lui-même aucune cryptographie. Il ne fait que
transporter les jetons produits par la couche d’authentification, puis
encadrer les données une fois celle-ci terminée.

### Le message de handshake

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

La charge utile qui suit l’en-tête est le **jeton d’authentification
opaque**. NegotiateStream ne l’interprète pas : il ignore s’il transporte du
SPNEGO, du Kerberos ou du NTLM.

Lorsque le MessageId vaut `0x15`, la charge utile contient un code d’erreur
permettant d’identifier la cause du rejet.

### Le cadrage des données applicatives

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

> Le changement de cadrage au HandshakeDone explique une confusion
> classique. On lit parfois que l’élévation de sécurité d’ADWS consiste en «
> des jetons bruts précédés d’une longueur ». C’est la description du régime
> *postérieur* au handshake. Pendant le handshake, l’en-tête de cinq octets
> est bien présent, et la longueur y est gros-boutiste.

## La sélection du mécanisme : SPNEGO (RFC 4178)

### Le rôle de SPNEGO

Le client et le service doivent s’accorder sur un **mécanisme
d’authentification** avant de l’employer. SPNEGO, pour *Simple and Protected
GSS-API Negotiation Mechanism*, est un pseudo-mécanisme dont l’unique objet
est cette mise d’accord. Il est normalisé par la **RFC 4178**.

SPNEGO est lui-même un mécanisme GSS-API : il s’identifie par un OID et se
manipule comme n’importe quel autre. Cette récursion est délibérée. Elle
permet d’ajouter la négociation sans modifier l’interface de programmation
ni les couches de transport.

### Les identifiants de mécanisme

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

### Les deux messages SPNEGO

SPNEGO définit deux structures, encodées en ASN.1 selon les règles DER.

#### NegTokenInit

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

Le champ `mechListMIC` protège la négociation contre la **manipulation par
un tiers**. Sans lui, un attaquant en position d’intermédiaire pourrait
retrancher les mécanismes forts de la liste afin de forcer un repli vers un
mécanisme faible. Le MIC, calculé avec une clé issue de l’authentification
réussie, rend cette manipulation détectable.

#### NegTokenResp

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

### Le déroulement typique

Le nombre d’allers-retours n’est pas fixé par la norme : il dépend du
mécanisme retenu et de la nécessité d’échanger un MIC. Le scénario le plus
courant en environnement Kerberos comporte deux à trois échanges.

1. Le client envoie un `NegTokenInit` proposant Kerberos en tête de
  liste, avec l’AP-REQ Kerberos déjà joint dans `mechToken`.
2. Le service accepte Kerberos, valide l’AP-REQ, puis répond un
  `NegTokenResp` portant `supportedMech` égal à l’OID Kerberos, l’AP-REP
  dans `responseToken`, et un `negState` valant soit `accept-completed`,
  soit `request-mic` si un contrôle d’intégrité est réclamé.
3. Le cas échéant, un dernier `NegTokenResp` porte le `mechListMIC`.

### L’enveloppe du jeton initial

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

## L’authentification : Kerberos v5 (RFC 4120)

### Le modèle à trois parties

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

Les échanges AS et TGS ont lieu **avec le KDC, sur le port 88**, et sont
donc extérieurs à la connexion ADWS. Lorsqu’un client ouvre une session
ADWS, il possède déjà son TGT, obtenu à l’ouverture de session Windows ; il
lui reste au plus à demander un ticket de service, puis à le présenter.

```schema:gssapi-handshake-protocols
Figure 4 — L’élévation de sécurité complète : le cadrage NegotiateStream
transporte les jetons SPNEGO, eux-mêmes porteurs des messages Kerberos.
```

### Le nom du service

Pour demander un ticket, le client doit nommer le service visé par un
**SPN** (*Service Principal Name*), de la forme `classe/hôte`.

ADWS relève de la famille des services hébergés par le système, dont le SPN
générique est `HOST/<nom-de-machine>`. Ce SPN est enregistré automatiquement
pour tout compte d’ordinateur joint au domaine et couvre l’ensemble des
services système.

> Il n’existe **pas** de SPN dédié du type `ADWS/serveur`. Le service
> s’appuie sur le SPN d’hôte. C’est pourquoi un contrôleur correctement
> joint au domaine n’exige aucune déclaration de SPN supplémentaire pour
> qu’ADWS fonctionne.

L’erreur `KDC_ERR_S_PRINCIPAL_UNKNOWN` signale que le SPN demandé n’existe
dans aucun compte de l’annuaire. Elle survient typiquement lorsque le client
vise un nom d’hôte, ou un alias, qui n’est pas enregistré.

### Le contenu de l’AP-REQ

L’AP-REQ est le message que le client présente au service. Il comporte deux
parties essentielles, chiffrées avec des clés différentes.

| Partie | Chiffrée avec | Contenu |
|---|---|---|
| Ticket | La clé long terme du service | Identité du client, clé de session, validité |
| Authenticator | La clé de session | Horodatage, somme de contrôle, sous-clé |

Le **ticket** a été fabriqué par le KDC et chiffré avec la clé du compte du
service. Le client ne peut ni le lire ni le modifier ; il se contente de le
relayer. Le service le déchiffre avec sa propre clé et en extrait la **clé
de session**.

L’**authenticator** est chiffré par le client avec cette clé de session. Il
prouve que le client détient réellement la clé, et ne rejoue pas un ticket
intercepté. Il contient un horodatage, ce qui explique la sensibilité de
Kerberos à la dérive d’horloge : au-delà d’une tolérance, généralement de
cinq minutes, l’authenticator est rejeté.

L’authenticator peut également porter une **sous-clé**, proposée par le
client pour servir de base au chiffrement des messages ultérieurs, de
préférence à la clé de session issue du ticket.

### Les options de l’AP-REQ

Deux drapeaux du message conditionnent la suite de l’échange.

| Drapeau | Effet |
|---|---|
| `MUTUAL-REQUIRED` | Le service doit prouver son identité par un AP-REP |
| `USE-SESSION-KEY` | Le ticket est chiffré avec une clé de session |

L’authentification **mutuelle** est déterminante pour ADWS : sans elle, le
client n’aurait aucune garantie de parler au véritable contrôleur de
domaine. C’est l’AP-REP qui apporte cette preuve, puisque seul le détenteur
de la clé du service a pu déchiffrer le ticket et donc produire une réponse
valide.

### Les types de chiffrement

Kerberos est agnostique quant à l’algorithme. Chaque clé porte un
identifiant de type.

| Identifiant | Algorithme | Statut |
|---|---|---|
| 18 | AES-256 CTS avec HMAC-SHA1-96 | Recommandé |
| 17 | AES-128 CTS avec HMAC-SHA1-96 | Accepté |
| 23 | RC4 avec HMAC-MD5 | Obsolète |
| 3 | DES-CBC-MD5 | Proscrit |

Le KDC retient le type le plus fort commun au client, au service et à la
politique de domaine. Un environnement moderne aboutit à AES-256.

L’erreur `KRB_AP_ERR_MODIFIED` indique que le service n’a pas pu déchiffrer
le ticket. La cause la plus fréquente n’est pas une altération malveillante
mais une **désynchronisation de clé** : le secret du compte de service a
changé sans que la clé ayant servi à émettre le ticket ait été mise à jour.

### Les erreurs Kerberos courantes

| Erreur | Signification | Origine habituelle |
|---|---|---|
| `KDC_ERR_S_PRINCIPAL_UNKNOWN` | SPN introuvable | Nom d’hôte non enregistré |
| `KDC_ERR_C_PRINCIPAL_UNKNOWN` | Compte client inconnu | Compte absent ou supprimé |
| `KRB_AP_ERR_SKEW` | Dérive d’horloge excessive | Horloges désynchronisées |
| `KRB_AP_ERR_MODIFIED` | Déchiffrement impossible | Clé de service désynchronisée |
| `KRB_AP_ERR_TKT_EXPIRED` | Ticket périmé | Session très longue |
| `KRB_AP_ERR_REPEAT` | Rejeu détecté | Authenticator déjà présenté |

## La protection des messages : GSS-API (RFC 2743 et RFC 4121)

### Ce qu’est GSS-API

GSS-API, pour *Generic Security Service Application Program Interface*,
n’est pas un protocole de transport mais une **interface normalisée** entre
une application et un mécanisme de sécurité. La RFC 2743 en définit
l’abstraction ; la RFC 4121 précise la manière dont Kerberos v5 s’y
conforme.

L’intérêt pour ADWS est direct : l’application manipule des jetons opaques
sans jamais implémenter Kerberos. Elle en produit un, l’envoie, en reçoit un
autre, le fournit à la bibliothèque, et recommence jusqu’à ce que celle-ci
déclare le contexte établi.

### L’établissement du contexte

L’établissement suit une boucle symétrique. Chaque partie appelle
répétitivement une primitive qui consomme le jeton reçu et produit
éventuellement un jeton à émettre.

| Étape | Côté client | Côté service |
|---|---|---|
| 1 | Produit le premier jeton | Attend |
| 2 | Attend | Consomme, produit une réponse |
| 3 | Consomme, produit si nécessaire | Attend |
| n | Signale « contexte établi » | Signale « contexte établi » |

Deux états intermédiaires sont normalisés : « il faut continuer » et «
terminé ». Tant que l’état est « il faut continuer », un jeton
supplémentaire doit être transmis. C’est exactement ce que NegotiateStream
matérialise par ses MessageId `0x16` et `0x14`.

### Les services demandés à l’établissement

Le client déclare les garanties qu’il souhaite. Les principales :

| Service | Garantie apportée |
|---|---|
| Authentification mutuelle | Le service prouve son identité au client |
| Intégrité | Toute altération d’un message est détectée |
| Confidentialité | Le contenu des messages est chiffré |
| Séquencement | Les rejeux et réordonnancements sont détectés |
| Délégation | Le service peut agir au nom du client |

ADWS exige au minimum authentification mutuelle, intégrité et
confidentialité. C’est ce triplet qui garantit qu’un observateur du réseau
ne peut ni lire ni modifier une opération d’annuaire.

### Le jeton de protection par message

Une fois le contexte établi, chaque message applicatif est protégé. La RFC
4121 définit pour cela un jeton dont l’en-tête fait **seize octets**.

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
bourrage ajoutés. RRC indique une rotation circulaire appliquée au jeton,
une particularité de la RFC 4121 destinée à placer la somme de contrôle à un
emplacement prévisible.

### Deux niveaux de protection

GSS-API distingue deux opérations, qui produisent des jetons différents.

| Opération | TOK_ID | Effet |
|---|---|---|
| Protection complète | `0x05 0x04` | Chiffre et authentifie le message |
| Signature seule | `0x04 0x04` | Authentifie sans chiffrer |

ADWS emploie la protection complète. Le message est donc à la fois
confidentiel et intègre. Un observateur ne voit qu’une longueur et des
octets indistinguables d’aléa.

### L’effet sur la taille des messages

La protection **augmente** la taille du message transmis. Il faut compter
l’en-tête de seize octets, un confondeur, une copie de l’en-tête et une
somme de contrôle. Pour Kerberos AES, ce surcoût est de l’ordre de plusieurs
dizaines d’octets par jeton.

Cette expansion a une conséquence pratique : la taille du texte clair confié
à la protection doit rester suffisamment en deçà de la taille maximale d’un
bloc NegotiateStream pour que le jeton résultant tienne dans un seul bloc.
Sans cette marge, un jeton unique déborderait sur deux blocs, et un
destinataire qui suppose « un bloc, un jeton » échouerait à le déchiffrer.

### L’identité obtenue

À l’issue de l’établissement, le service dispose de l’**identité
authentifiée** du client, et non d’une simple confirmation binaire. Cette
identité comprend le nom du principal Kerberos et, dans un contexte Active
Directory, les informations d’autorisation transportées par le ticket, dont
la liste des groupes de sécurité.

C’est cette identité qui doit ensuite gouverner les autorisations sur
l’annuaire : ADWS n’ajoute aucun modèle d’autorisation propre. Les droits
appliqués sont ceux d’Active Directory, évalués selon les descripteurs de
sécurité des objets visés.

## L’encodage : XML binaire .NET [MS-NBFX] et [MS-NBFS]

### Pourquoi un XML binaire

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

### Le modèle d’enregistrements

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

### La convention du bit de poids faible

Les enregistrements de texte suivent une règle d’économie remarquable :
chaque type de texte occupe **deux valeurs consécutives**, l’une paire,
l’autre impaire.

- La valeur **paire** signifie « voici une valeur ».
- La valeur **impaire**, c’est-à-dire la paire plus un, signifie « voici une
  valeur, et l’élément qui la contient se termine immédiatement après ».

Cette convention supprime un enregistrement de fin dans le cas très fréquent
d’un élément ne contenant qu’une valeur. Sur un document d’annuaire où la
quasi-totalité des éléments sont des feuilles, l’économie est substantielle.

### Le catalogue des enregistrements de texte

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

### Les enregistrements d’élément

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

### Les enregistrements d’attribut

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

### Les encodages particuliers

Trois types de valeurs méritent un examen détaillé, car leur représentation
n’est pas intuitive.

#### Les dates

Une date-heure est encodée sur huit octets. Les 62 bits de poids faible
comptent le nombre d’intervalles de **100 nanosecondes** écoulés depuis le
**1er janvier de l’an 1 à minuit**. Les deux bits de poids fort indiquent la
nature du fuseau.

| Bits de poids fort | Sens |
|---|---|
| `00` | Fuseau non spécifié |
| `01` | Temps universel coordonné |
| `10` | Heure locale de l’émetteur |

Cette origine, très antérieure à l’époque Unix, est celle du système de
dates de la plateforme .NET.

#### Les identifiants

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

#### Les durées

Une durée occupe huit octets et compte, elle aussi, des intervalles de 100
nanosecondes. Une valeur négative représente une durée orientée vers le
passé, ce qui sert notamment à exprimer des délais d’expiration relatifs.

### Le dictionnaire

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

> L’usage du dictionnaire de session est signalé dès le préambule de
> cadrage, par la valeur d’encodage choisie. Une implémentation qui
> n’annonce que le XML binaire sans dictionnaire de session se prive de
> cette optimisation mais reste parfaitement interopérable.

```schema:wcf-encode-protocols
Figure 5 — La chaîne d’encodage d’un message : du document logique aux
octets protégés.
```

### Un exemple d’encodage

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

## La messagerie : SOAP 1.2

### L’enveloppe

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

### Les espaces de noms

Un message ADWS mobilise une dizaine d’espaces de noms, chacun rattaché à
une spécification.

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

### Le modèle de faute

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

La distinction entre `Sender` et `Receiver` est opérationnelle : elle
indique au client si réessayer a un sens. Une faute `Sender` signifie que la
requête est mal formée et que la réémettre à l’identique échouera ; une
faute `Receiver` signale un problème côté service, potentiellement
transitoire.

Le `Subcode` permet d’affiner sans sortir du cadre normalisé. C’est là que
sont portées les erreurs propres à l’annuaire.

## L’adressage : WS-Addressing

### Le rôle des en-têtes d’adressage

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

### L’en-tête Action

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

### La corrélation requête-réponse

Le mécanisme est simple et strict.

- La requête porte un `a:MessageID` unique, généralement de la forme
  `urn:uuid:` suivie d’un identifiant.
- La réponse **doit** porter un `a:RelatesTo` reprenant cette valeur **à
  l’identique**.

Cette règle n’admet aucune exception, y compris pour les fautes. Une faute
sans `a:RelatesTo` est, du point de vue du client, un message non sollicité.

> C’est la source d’un symptôme déroutant : une commande qui ne rend jamais
> la main. Le service a bien répondu, la réponse est bien arrivée, mais
> faute de corrélation le client l’ignore et continue d’attendre jusqu’à
> expiration de son délai. Le réseau paraît sain, le service paraît muet.

### L’adresse anonyme

L’en-tête `a:ReplyTo` porte une adresse de réponse. Dans un échange
requête-réponse sur une connexion déjà établie, cette adresse prend une
valeur conventionnelle qui signifie « réponds sur le canal existant ».

```xml
<a:ReplyTo>
  <a:Address>http://www.w3.org/2005/08/addressing/anonymous</a:Address>
</a:ReplyTo>
```

Cette valeur, dite **adresse anonyme**, évite au service d’avoir à ouvrir
une connexion vers le client, ce qui serait impraticable à travers un
pare-feu.

### Les références de point de terminaison

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

### Les en-têtes propres à l’annuaire

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

## Le transfert de ressource : WS-Transfer

### Le modèle

WS-Transfer traite l’annuaire comme un ensemble de **ressources**
adressables. Chaque objet (utilisateur, ordinateur, groupe, unité
d’organisation) est une ressource dotée d’une représentation XML. Le
protocole définit quatre opérations, calquées sur le cycle de vie d’une
ressource.

| Opération | Action | Effet |
|---|---|---|
| Get | `.../transfer/Get` | Lire la représentation d’une ressource |
| Put | `.../transfer/Put` | Remplacer la représentation |
| Create | `.../transfer/Create` | Créer une ressource |
| Delete | `.../transfer/Delete` | Supprimer une ressource |

La ressource visée n’est **pas** nommée dans le corps du message : elle
l’est par les en-têtes d’adressage. Le corps d’un Get est d’ailleurs vide.

### L’opération Get

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

Trois règles de forme appellent une remarque.

- Chaque attribut d’annuaire est un élément de l’espace `addata`, portant un
  attribut `LdapSyntax` qui nomme sa syntaxe.
- Chaque valeur est un élément `ad:value` portant un attribut `xsi:type` qui
  donne son type XSD. Un attribut multivalué contient plusieurs `ad:value`.
- Certains éléments relèvent de l’espace `ad` et non `addata` : ce sont des
  **attributs synthétiques**, calculés par le service et non stockés tels
  quels. Ils ne portent pas de `LdapSyntax`.

### L’opération Create

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

### L’opération Put

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

### L’opération Delete

Requête et réponse sont vides : l’objet visé par les en-têtes est supprimé,
et la réponse ne fait que confirmer. La suppression récursive d’une
sous-arborescence relève d’un contrôle LDAP transporté en en-tête, décrit
plus loin.

## L’accès annuaire : IMDA [MS-WSTIM] et [MS-WSDS]

### Deux façons de lire un objet

ADWS offre **deux formulations distinctes** pour lire un objet, issues de
deux familles de spécifications.

- **WS-Transfer** renvoie la représentation entière, dans un élément nommé
  d’après la classe de l’objet.
- **IMDA**, pour *Identity Management Directory Access*, permet de demander
  un **sous-ensemble d’attributs** et renvoie chaque attribut isolément.

Le choix n’appartient pas au service : il découle de la requête émise par le
client. Un service doit répondre dans la forme correspondant à la question
posée.

### La requête IMDA de lecture

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

#### Cas 1 : des attributs sont demandés

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

#### Cas 2 : aucun attribut n’est demandé

La réponse place la représentation entière de l’objet, dans la forme
WS-Transfer, à l’intérieur d’un **unique** conteneur `da:PartialAttribute`.

> Se tromper de forme est une erreur silencieuse côté service et bruyante
> côté client : la désérialisation échoue en signalant qu’un élément de fin
> était attendu à l’endroit où apparaît un élément inattendu.

### La modification IMDA

Symétriquement, IMDA définit une requête de modification portant une liste
de changements, chacun désignant un attribut, un mode d’opération et des
valeurs.

## L’énumération : WS-Enumeration

### Le problème

Une recherche d’annuaire peut renvoyer des dizaines de milliers d’objets.
Les transmettre dans une seule réponse serait impraticable. WS-Enumeration
définit un mécanisme de **curseur** : le service constitue un jeu de
résultats, en remet un identifiant au client, et celui-ci le consomme par
tranches.

```schema:ws-enumeration-protocols
Figure 6 — Le cycle d’énumération : constitution du contexte, consommation
par tranches successives, puis libération.
```

### Les cinq opérations

| Opération | Action | Rôle |
|---|---|---|
| Enumerate | `.../enumeration/Enumerate` | Ouvre un contexte de résultats |
| Pull | `.../enumeration/Pull` | Consomme une tranche de résultats |
| Renew | `.../enumeration/Renew` | Prolonge la validité du contexte |
| GetStatus | `.../enumeration/GetStatus` | Interroge l’état du contexte |
| Release | `.../enumeration/Release` | Libère le contexte |

### L’ouverture

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

### La consommation

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

### L’expiration et la libération

Un contexte a une durée de vie limitée. Le client peut la prolonger par
Renew, s’enquérir de l’état par GetStatus, et doit libérer le contexte par
Release dès qu’il n’en a plus besoin. Un contexte abandonné expire de
lui-même.

> Le contexte est une **ressource d’état côté service**. Cela a une
> conséquence d’architecture importante : les Pull successifs doivent
> atteindre l’instance qui détient le contexte. Un répartiteur de charge qui
> disperserait les requêtes d’une même énumération sur plusieurs instances
> provoquerait des erreurs de contexte inconnu.

## La notification : WS-Eventing

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
> opérations courantes d’administration d’annuaire ne l’emploient pas. Il
> est décrit ici pour l’exhaustivité de l’empilement, sans qu’un scénario
> d’administration usuel s’y ramène.

## Les contrôles LDAP transportés [MS-WSPELD]

### Le principe

LDAP définit des **contrôles** : des modificateurs de comportement attachés
à une opération, identifiés par un OID. ADWS permet de transporter ces
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

### Les contrôles usuels

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

Le contrôle **SD Flags** appelle une précision. Le descripteur de sécurité
d’un objet comporte quatre parties : propriétaire, groupe, liste de contrôle
d’accès discrétionnaire et liste d’audit. Lire cette dernière exige un
privilège élevé. Le contrôle permet de ne demander que les parties
nécessaires, et donc d’éviter un refus d’accès sur une lecture qui aurait
autrement réussi.

### Les règles de correspondance étendues

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

## Le modèle de données [MS-ADDM] et [MS-ADTS]

### Objets, classes et attributs

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

L’identifiant global est le seul désignateur véritablement stable ; c’est
lui que les références de point de terminaison privilégient.

### Les syntaxes d’attribut

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

### Les attributs à sémantique particulière

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

L’attribut `unicodePwd` demande une précision. Il n’est jamais lisible :
toute tentative de lecture échoue. Son écriture obéit à une convention
stricte, la chaîne du mot de passe est entourée de guillemets doubles, puis
encodée en UTF-16 en ordre petit-boutiste, et le résultat est transmis comme
une suite d’octets.

Deux modes d’écriture existent, aux exigences de privilège différentes.

| Mode | Contenu de l’opération | Privilège requis |
|---|---|---|
| Réinitialisation | Un remplacement de la nouvelle valeur | Droit de réinitialiser |
| Changement | Une suppression de l’ancienne, puis un ajout de la nouvelle | Connaissance de l’ancien |

### Les attributs construits

Certains attributs ne sont pas stockés mais **calculés** au moment de la
lecture. Ils ne sont renvoyés que s’ils sont demandés explicitement.

| Attribut | Calcul |
|---|---|
| `canonicalName` | Le nom distinctif réécrit en notation de chemin |
| `tokenGroups` | L’ensemble transitif des groupes du principal |
| `allowedAttributes` | Les attributs autorisés par le schéma pour cette classe |
| `msDS-PrincipalName` | Le nom du principal sous forme domaine et compte |

### L’objet racine

Un objet particulier, la **racine du service d’annuaire**, se lit sans
authentification préalable dans LDAP et décrit les capacités du serveur. Il
n’a ni classe ni nom distinctif : il s’interroge par une lecture de portée «
base » sur un nom vide.

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

## Les fautes propres à l’annuaire

### Le mécanisme

Les erreurs d’annuaire sont portées par le `Subcode` de la faute SOAP, ce
qui permet au client de les distinguer programmatiquement sans analyser un
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

### La lecture d’une faute

Une faute bien formée porte quatre informations exploitables : la
responsabilité, par `Code/Value` ; la nature, par `Subcode` ; une
description lisible, par `Reason/Text` ; et la corrélation, par l’en-tête
`a:RelatesTo`.

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

## Synthèse : une opération de bout en bout

### Ce que fait réellement une commande d’administration

Reprenons la demande « lis-moi l’objet utilisateur Administrator » et
suivons-la à travers toutes les couches décrites.

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

### Le coût d’une session

Une session complète mobilise, au minimum, un aller-retour DNS, un
établissement TCP, un préambule sans réponse, deux à trois allers-retours
d’authentification, un aller-retour de fin de préambule, puis un
aller-retour par opération applicative.

C’est pourquoi les clients **réutilisent la connexion** : le coût
d’établissement est intégralement amorti dès la seconde commande. Une suite
de commandes successives sur le même serveur ne rejoue ni la découverte, ni
l’authentification.

### Lire une capture réseau

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
la présence d’un AP-REQ Kerberos. Au-delà, seules les tailles de blocs
restent observables.

### Glossaire des sigles

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

# Partie II. Vue d’ensemble de la relation client-serveur

## Positionnement du service ADWS dans l'écosystème Active Directory

### Le trou fonctionnel que ce projet comble

Un contrôleur de domaine Samba AD expose nativement les quatre piliers d'un
domaine Active Directory : **LDAP** (389/tcp, 636/tcp, 3268/tcp pour le
catalogue global), **Kerberos** (88/tcp+udp), **SMB** (445/tcp, pour SYSVOL
et les stratégies de groupe) et **DNS** (53/tcp+udp, avec les
enregistrements SRV `_ldap._tcp.dc._msdcs.<domaine>`). Il n'expose **pas**
les *Active Directory Web Services*, le service Microsoft qui écoute sur
**9389/tcp**.

Cette absence n'est pas un détail cosmétique. Elle rend inutilisables, en
bloc, les outils d'administration Microsoft les plus courants :

- le module PowerShell **`ActiveDirectory`**
  (`Microsoft.ActiveDirectory.Management`, livré par RSAT), c'est-à-dire
  l'intégralité des cmdlets `*-AD*` ;
- la console **ADAC** (`dsac.exe`, *Active Directory Administrative
  Center*), qui n'est qu'une interface graphique posée sur le même module ;
- tout script tiers construit sur ce namespace .NET.

Le symptôme canonique, documenté dans `documentation/01-architecture.md:8`
et repris dans `documentation/06-depannage.md` §7, est le suivant :

```text
Get-ADUser : Unable to find a default server with Active Directory Web
Services running
```

### Pourquoi le module PowerShell ne parle pas LDAP

Il est tentant de croire que les cmdlets `Get-ADUser` et consorts émettent
du LDAP, puisque l'annuaire est un annuaire LDAP. **Ce n'est pas le cas.**
Le module `ActiveDirectory` est un client **WS-\*** : il construit des
enveloppes SOAP 1.2, les encode en XML binaire WCF, les transporte sur
`net.tcp` et les adresse au service ADWS. C'est ADWS qui, **côté serveur**,
retraduit ces requêtes en opérations LDAP (`ldap_bind`, `ldap_search_ext`,
`ldap_add`, `ldap_modify`) contre l'instance d'annuaire locale.

La configuration de référence du service Microsoft confirme cette
architecture en deux temps. Elle documente un **pool de connexions LDAP**
interne au service (`MaxPoolConnections = 10`, `MaxConnectionsPerUser = 5`,
`MaxPercentageReservedConnections = 50`), maintenu « séparément pour chaque
instance d'annuaire », AD DS, catalogue global, instances AD LDS, et l'outil
de montage de base de données AD. ADWS est donc, littéralement, une
**passerelle WS-\* → LDAP** multi-instances.

La conséquence pratique est double :

1. Une console qui parle LDAP directement, comme **ADUC** (`dsa.msc`),
  fonctionne contre Samba **sans ADWS**. C'est la recommandation explicite
  du projet (`README.md`, section « Console graphique »).
2. Une console ou un module qui ne parle **que** ADWS n'a aucun chemin
  de repli. Sans les 9389/tcp, il ne fonctionne pas, d'où ce projet.

### Ce que couvre exactement cette implémentation

Ce dépôt réimplémente en Python, du côté Linux, le protocole servi par
`Microsoft.ActiveDirectory.WebServices.exe`, de la trame TCP jusqu'à l'appel
`samba.samdb`. Le point d'entrée unique est `python3 -m src.main`
(`src/main.py:9`), qui construit la configuration, enregistre les types de
records NMF et démarre le serveur (`src/main.py:15-17`).

Trois niveaux de lecture doivent être tenus séparés dans tout ce chapitre,
et le seront systématiquement :

| Niveau | Source de vérité | Statut |
|---|---|---|
| Spécification | Microsoft Open Specifications, RFC | Normatif |
| Client Windows réel | Comportement observé sur le réseau | Descriptif |
| Cette implémentation | Code de `src/` et `classes/` | Ce qui tourne |

### Ce que ce service n'est pas

ADWS n'est **pas** un service d'authentification : il ne délivre pas de
tickets et ne remplace pas le KDC. Il n'est pas non plus un service de
réplication : la réplication reste du ressort de `[MS-DRSR]` entre DC.
Enfin, il ne se substitue pas à LDAP : sur un DC Microsoft comme sur ce
projet, LDAP reste le canal d'accès réel à l'annuaire ; ADWS n'en est qu'un
habillage réseau.

## Acteurs, points de terminaison et topologie réseau

### Les acteurs d'une session

| Acteur | Rôle | Emplacement |
|---|---|---|
| Module `ActiveDirectory` | Client WS-* (cmdlets `*-AD*`) | Poste Windows |
| ADAC `dsac.exe` | Client graphique, même pile | Poste Windows |
| KDC Samba | Délivre le ticket de service | DC Samba, 88 |
| Service ADWS souverain | Serveur `net.tcp` 9389 | DC Samba |
| `sam.ldb` via `python3-samba` | Annuaire réel | DC Samba, local |

Le service ADWS de ce projet est **co-localisé** avec l'annuaire : il
n'ouvre pas de connexion LDAP réseau vers 389/tcp, il ouvre un `SamDB`
**local** sur les fichiers LDB (`classes/directory/samba_db.py:23-28`).
C'est une divergence d'architecture assumée par rapport à l'ADWS Microsoft,
qui passe par un pool LDAP même en local. Elle a une conséquence directe sur
l'identité de l'appelant, détaillée plus loin.

### Les points de terminaison réels de l'ADWS Microsoft

Le service Microsoft publie ses endpoints WCF. L’adresse de base est
construite ainsi : préfixe `net.tcp://`, suffixe
`:9389/ActiveDirectoryWebServices`. À cette base s'ajoutent un **préfixe de
binding** (`Windows/` ou `UserName/`) puis le nom d'endpoint.

| Endpoint | Contrat WCF | Constante |
|---|---|---|
| `Windows/Resource` | `IResource` | `WcfResourceEndpoint` |
| `Windows/ResourceFactory` | `IResourceFactory` | `WcfResourceFactoryEndpoint` |
| `Windows/Enumeration` | `IEnumeration` | `WcfEnumEndpoint` |
| `Windows/AccountManagement` | `IActiveDirectoryAccountManagement` | `WcfAcctMgmtEndpoint` |
| `Windows/TopologyManagement` | `IActiveDirectoryTopologyManagementV1` | `WcfTopoMgmtEndpoint` |

Deux compléments importants, souvent omis :

- Le même quintuplet est **dupliqué** sous le préfixe `UserName/` , mais
  **seulement si** un certificat serveur a pu être provisionné
  (`ProvisionCertificate`). Ce chemin correspond au binding
  `TransportWithMessageCredential`, c'est-à-dire une authentification par
  nom d'utilisateur/mot de passe portée dans le message. **Ce projet
  n'implémente pas le préfixe `UserName/`** ; il n'accepte que Kerberos via
  GSSAPI.
- Un sixième endpoint, `mex`, publie les métadonnées WS-MetadataExchange. Il
  est exposé sans préfixe de binding et sa politique HTTP GET est désactivée
  (`HttpGetEnabled = false`). **Non implémenté ici.**

L'URL complète vue sur le fil pour une lecture d'objet est donc :

```text
net.tcp://dc.samba.local:9389/ActiveDirectoryWebServices/Windows/Resource
```

### Ce que ce projet expose réellement : un endpoint unique de fait

Le serveur Python n'implémente **aucun démultiplexage par endpoint**. Il
ouvre une socket TCP unique sur `0.0.0.0:9389`
(`classes/server/config.py:15-16`, `classes/server/server.py:25-32`) et
traite chaque connexion de manière identique quel que soit l'URI demandé.

La démonstration tient en trois observations vérifiables :

1. Le `ViaRecord` du préambule (code `0x02`) est **lu et journalisé,
  jamais comparé** : `classes/server/protocol.py:45-46` se contente d'écrire
  `[PREAMBLE]... ViaRecord received from client`. Aucune extraction de
  chemin, aucune table d'endpoints.
2. L'en-tête WS-Addressing `<a:To>` n'est **pas extrait** par le
  parseur de requête : `RequestContext.from_xml`
  (`classes/parsing/context.py:37-169`) récupère `a:Action` (ligne 55),
  `a:MessageID` (60), `ad:objectReferenceProperty` (64), le marqueur IMDA
  `da:IdentityManagementOperation` / `da:BaseObjectSearchRequest` (66-69),
  les éléments `wsen:Enumerate` / `wsen:Pull` / `wsen:Release` (92, 129,
  145) et les `adlq:BaseObject` / `adlq:Filter` / `adlq:Scope` (95, 99,
  104), mais jamais `a:To` ni `a:Via`. Aucun des sept préfixes déclarés dans
  la table `ns` (`context.py:44-52` : `soap`, `soap11`, `a`, `ad`, `da`,
  `wsen`, `adlq`) ne sert à lire une adresse de destination.
3. Le seul usage de `<a:To>` dans tout le dépôt est cosmétique : le
  handler de création le relit **par expression régulière** dans le XML brut
  pour fabriquer l'adresse de l'EPR `ResourceCreated`, en substituant
  `ResourceFactory` par `Resource` (`classes/handlers/create.py:75-77`). Si
  l'en-tête est absent, il retombe sur l'adresse anonyme WS-Addressing.

**Le routage est donc intégralement porté par `<a:Action>`**, via
`HandlerRegistry.resolve` (`classes/handlers/handler_registry.py:15-23`) :

- correspondance **exacte, insensible à la casse**, dans la table
  `ACTION_HANDLER_KEYS` (`src/handlers/handler_routing.py:35-51`, 14
  entrées) : l'URI reçue est passée en minuscules (`normalized =
  action_url.lower`, `handler_registry.py:18`) et les 14 clés de la table
  sont écrites en minuscules ;
- à défaut, correspondance sur le **dernier segment** de l'URI d'action
  (`action_url.rsplit("/", 1)[-1]`, `handler_registry.py:22`) dans
  `HANDLER_FACTORIES` (`src/handlers/handler_routing.py:53-71`, 29 entrées).
  Ce second chemin est **sensible à la casse** : aucun `lower` n'est
  appliqué, le suffixe doit être exactement `GetADDomain`, `SetPassword`,
  etc.

Le rapport entre les deux tables mérite d'être explicité : sur les 29 clés
de `HANDLER_FACTORIES`, **14 seulement** sont atteignables par la table
exacte ; les **15 autres** (toutes les actions `CustomActions` plus
`Search`, `Schema` et `Groups`) ne sont joignables que par le suffixe.

> La table exacte n'est pas un doublon du routage par suffixe : elle
> **désambiguïse** les collisions de dernier segment.
> `.../ws/2004/09/enumeration/Renew` et `.../ws/2004/08/eventing/Renew`
> finissent tous deux par `Renew`, de même que les deux `GetStatus`. Sans la
> table exacte, WS-Eventing serait routé vers les handlers WS-Enumeration.

Conséquence opérationnelle, à énoncer clairement : **un client qui
adresserait `.../Windows/TopologyManagement` mais enverrait une action
WS-Transfer `Get` serait servi normalement par ce serveur**, là où l'ADWS
Microsoft rejetterait la requête au niveau du dispatcher WCF (contrat
`IActiveDirectoryTopologyManagementV1` n'exposant pas cette opération).
C'est une **permissivité** de l'implémentation, pas une conformité.

### Correspondance endpoint → actions SOAP supportées

Le tableau ci-dessous rétablit, pour la documentation, la répartition
**logique** des actions par endpoint Microsoft, et indique le handler qui
les sert dans ce projet. La colonne « endpoint » est celle qu'utilise le
client Windows ; elle n'a, encore une fois, **aucun effet** sur le routage
serveur ici.

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

Les espaces de noms d'action sont ceux déclarés dans
`src/soap/namespaces.py` :

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

`WSEV` est le seul de la liste à **ne pas** avoir de constante
correspondante côté Microsoft : WS-Eventing est implémenté ici sans
contrepartie Microsoft connue.

Trois clés de `HANDLER_FACTORIES` n'ont pas d'action Microsoft canonique et
ne sont atteignables que par le routage par suffixe :

- `Search` (`search.py`) : normalise le filtre via `FilterParser` puis
  délègue à `EnumerateHandler` ;
- `Schema` (`schema.py`) : introspection `classSchema`/`attributeSchema`,
  avec un cache porté par l'attribut de classe `_CACHE: SchemaCache` ;
- `Groups` (`groups.py`, `GroupHandler`) : aiguille sur `add`/`remove`
  présents dans l'URI d'action, sinon délègue à `GetADGroupMemberHandler`.

> **Handler inatteignable, vérifié.** `GroupHandler` est enregistré sous la
> clé `Groups` (`src/handlers/handler_routing.py:57`). Le routage par
> suffixe exige qu'une URI d'action se termine par `/Groups` ; aucune action
> Microsoft connue ne le fait, et la table exacte ne contient pas cette clé.
> `GroupHandler` est donc **du code mort en pratique** : l'ajout et le
> retrait de membre arrivent en réalité comme un `transfer/Put` sur l'objet
> groupe et sont servis par `modify.py`. Les journaux du dépôt le confirment
> : sur 98 connexions, `handler=GroupHandler` n'apparaît **jamais**, alors
> que `TransferHandler` apparaît 13 fois.

Enfin, les quatre handlers WS-Eventing (`Subscribe`, `Unsubscribe`,
`SubscriptionRenew`, `SubscriptionStatus`) sont enregistrés et répondent,
mais seul `SubscribeHandler` publie une adresse de gestionnaire
d'abonnement, et celle-ci est **codée en dur sur `localhost`**
(`classes/handlers/subscribe.py:15-17`), un client distant ne pourra donc
pas recontacter ce gestionnaire. Les trois autres se contentent de manipuler
le cache d'abonnements et ne réémettent aucune adresse
(`classes/handlers/unsubscribe.py`, `subscription_renew.py`,
`subscription_status.py`).

### Découverte côté client : DNS, CLDAP et le flag `DS_WS`

La localisation du service est **entièrement côté client**. Rien, dans ce
dépôt, n'implémente ni n'influence cette phase : elle se déroule avant que
la moindre socket ne s'ouvre sur 9389.

La séquence effectuée par un client Windows est la suivante :

1. **Résolution DNS SRV.** Le *DC locator* interroge
  `_ldap._tcp.dc._msdcs.<domaine>` (et, selon le contexte,
  `_ldap._tcp.<site>._sites.dc._msdcs.<domaine>`) pour obtenir la liste des
  contrôleurs de domaine candidats, puis résout leurs enregistrements
  A/AAAA.
2. **LDAP ping (CLDAP).** Il envoie une requête `CLDAP` sans connexion
  sur **UDP/389** vers chaque candidat, avec un filtre `NtVer`. Le DC répond
  une structure `NETLOGON_SAM_LOGON_RESPONSE_EX` dont le champ `Flags`
  déclare les services rendus (PDC, GC, KDC, écriture, horloge, etc.). Voir
  `[MS-ADTS]`, chapitre localisation de contrôleur de domaine, et
  `[MS-NRPC]` pour la structure de réponse.
3. **Filtrage par capacité.** Le module `ActiveDirectory` et ADAC
  n'appellent pas un simple « trouve-moi un DC » : ils appellent le locator
  avec l'exigence **« ne me renvoie un DC que s'il annonce ADWS »**
  (`DS_WEB_SERVICE_REQUIRED`). Le DC ne satisfait ce filtre que s'il a
  positionné le bit `NBT_SERVER_ADS_WEB_SERVICE` dans sa réponse CLDAP.

**Samba ne positionne pas ce bit.** C'est la cause de fond, établie dans
`documentation/06-depannage.md:252-255` : le nom du flag client
`DS_WEB_SERVICE_REQUIRED` et la valeur `0x2000` de
`NBT_SERVER_ADS_WEB_SERVICE` y sont donnés, avec le fichier Samba
responsable `source4/cldap_server/netlogon.c`
(`documentation/06-depannage.md:276`). Ce projet fournit **le service** ADWS
mais ne peut pas modifier **l'annonce CLDAP** de Samba, qui est émise par
`samba-ad-dc` sur UDP/389.

> **Ce qui n'est pas vérifiable ici.** La valeur numérique du flag client
> `DS_WEB_SERVICE_REQUIRED` de `DsGetDcName` n'apparaît **nulle part** dans
> ce dépôt : seul son nom est cité. La valeur `0x2000` documentée est celle
> du bit serveur `NBT_SERVER_ADS_WEB_SERVICE` dans le champ `Flags` de la
> réponse CLDAP, pas celle du flag d'appel côté client. Les deux ne se
> confondent pas.

Le diagnostic est binaire et reproductible depuis le client :

```powershell
nltest /dsgetdc:samba.local        # succes  -> DNS et DC locator OK
nltest /dsgetdc:samba.local /ws    # 1355    -> le DC n'annonce pas ADWS
Test-NetConnection 192.168.141.10 -Port 9389   # True -> le service repond
```

Ces trois commandes sont celles de `documentation/06-depannage.md:261-263`.
Le code `1355` est `ERROR_NO_SUCH_DOMAIN`
(`documentation/06-depannage.md:255`). Si la troisième commande réussit
alors que la deuxième échoue, **il n'y a rien à corriger côté serveur** : le
service tourne, seule l'annonce manque.

| Comportement client | Sans `-Server` | Avec `-Server` |
|---|---|---|
| Découverte DC locator | Requise | Court-circuitée |
| Exigence flag `DS_WS` | Oui | Non |
| Résultat contre Samba | `1355` / `ADServerDownException` | Fonctionne |
| Chemin validé par le projet | Non | Oui |

Contournements retenus par le projet : passer **toujours** `-Server` (au
besoin via `$PSDefaultParameterValues`, cf. `README.md`), et utiliser
**ADUC** (`dsa.msc`, LDAP direct) plutôt qu'ADAC pour l'administration
graphique.

### Ce que le serveur ne fait pas, et ne fera pas

À isoler explicitement pour éviter les fausses pistes de diagnostic :

- Aucune émission d'enregistrement DNS SRV ni de réponse CLDAP.
- Aucune publication `serviceConnectionPoint` dans l'annuaire.
- Aucune extraction ni validation de `<a:To>`, `<a:Via>`, `<a:ReplyTo>` :
  hormis la relecture par expression régulière de `<a:To>` dans
  `create.py:75`.
- Aucune validation **sémantique** du `Mode` ni de l'`Encoding` : le serveur
  n'exige nulle part `Mode = DUPLEX` ni `Encoding = 8`. Il y a en revanche
  une validation **syntaxique** involontaire, héritée de la coercition en
  énumération (`as_enum('B', Mode)` et `as_enum('B', KnownEncoding)`,
  `src/nettcp/nmf.py:306-325`) : une valeur hors énumération lève un
  `ValueError` et la connexion se ferme. Un client annonçant `Mode = SIMPLEX
  (3)` serait donc accepté sans broncher, alors qu'un `Encoding = 0` serait
  rejeté.
- Aucune négociation de dictionnaire dynamique `[MS-NBFSE]` : la réponse est
  systématiquement préfixée d'un octet `0x00`, soit « dictionnaire de
  session de taille nulle » (`classes/handlers/dispatcher.py:49`).
- Aucun endpoint `mex` ni `UserName/`.
- Aucune application des quotas `[MS-ADDM]` ni des limites de configuration
  du service Microsoft (voir le tableau de comparaison plus loin).

## Anatomie complète d'une session : les cinq phases

### Vue d'ensemble

Une session ADWS se décompose en cinq phases strictement ordonnées. Les
phases 2, 3 et 5 sont régies par `[MS-NMF]` ; la phase 3 imbrique en outre
le cadrage `[MS-NNS]` et les jetons GSSAPI/SPNEGO (`RFC 4178`, `RFC 4121`,
`RFC 4120`, `RFC 2743`) ; la phase 4 imbrique `[MS-NBFX]`/`[MS-NBFS]` puis
SOAP 1.2 et le modèle de données `[MS-ADDM]`.

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
> (`─── PHASE 1: PREAMBLE NEGOTIATION ───`, `─── PHASE 2: SECURITY
> NEGOTIATION ───`, `─── PHASE 3: MESSAGE EXCHANGE ───`). La correspondance
> est la suivante :

| Ce document | Journal serveur | Fonction |
|---|---|---|
| Phase 1 (TCP) | non journalisée comme phase | `ConnectionHandler.handle` |
| Phase 2 (préambule) | `PHASE 1: PREAMBLE NEGOTIATION` | `handle_preamble` |
| Phase 3 (sécurité) | `PHASE 2: SECURITY NEGOTIATION` | `handle_security` |
| Phase 4 (messages) | `PHASE 3: MESSAGE EXCHANGE` | `handle_messages` |
| Phase 5 (fermeture) | `CONNECTION CLOSED` | bloc `finally` |

### Phase 1 — Établissement TCP

Le serveur est un `socketserver.ForkingTCPServer` lié à
`(config.server.host, config.server.port)`, par défaut `0.0.0.0:9389`
(`classes/server/config.py:15-16`, surchargeable par `ADWS_HOST` et
`ADWS_PORT`, `classes/server/config.py:40-42`). Le bind est **différé**
(`bind_and_activate=False`) afin de positionner `allow_reuse_address`
**avant** l'appel à `server_bind`, faute de quoi un socket en `TIME_WAIT`
fait échouer tout redémarrage avec `EADDRINUSE`
(`classes/server/server.py:25-32`).

Dès l'`accept`, `socketserver` **fork** un processus enfant qui exécute
`ConnectionHandler.handle` (`classes/server/connection.py:27`). Le premier
acte de ce handler est de poser un délai d'attente de 10 secondes sur la
socket (`classes/server/connection.py:39`), puis d'envelopper la socket dans
un `SocketStream` (`src/nettcp/stream/socket.py:19`).

> **Piège vérifié dans le code.** `SocketStream.read(count)` appelle
> `self._socket.setblocking(1)` (`src/nettcp/stream/socket.py:32`), et
> `SocketStream.write` fait de même (`src/nettcp/stream/socket.py:51`). En
> Python, `setblocking(True)` est **strictement équivalent à
> `settimeout(None)`** : le délai posé ligne 39 de `connection.py` est donc
> **annulé dès la première lecture ou écriture de record**. En pratique la
> socket est purement bloquante pour toute la durée de la session, et la
> branche `except socket_timeout` de `classes/server/protocol.py:115`, ainsi
> que l'`EndRecord` qu'elle émet, n'est jamais empruntée par ce chemin. La
> variante `read(None)` bascule au contraire en non bloquant et s'appuie sur
> un `select.select` **sans timeout** (`src/nettcp/stream/socket.py:26-30`),
> ce qui revient au même : attente indéfinie. Conséquence en cascade : les
> deux seuls garde-fous temporels du serveur, le `settimeout(10)` de
> `connection.py:39` et le `settimeout(2)` de `protocol.py:164`, sont **tous
> les deux inopérants**, le premier parce qu'il est écrasé, le second parce
> qu'il vise un attribut inexistant (voir phase 5). Une connexion qui ne dit
> plus rien immobilise son processus enfant indéfiniment.

### Phase 2 — Préambule NMF

Le client envoie une séquence fixe de records, **sans aucune négociation
préalable et sans attendre de réponse**. Les codes et l'ordre sont ceux de
`[MS-NMF]` et sont implémentés dans `src/nettcp/nmf.py`. Le client de
référence embarqué dans le dépôt (`src/nettcp/stream/nmf.py:19-27`) émet
exactement :

| Record | Code | Champs | Valeur émise |
|---|---|---|---|
| `VersionRecord` | `0x00` | Major, Minor | `1`, `0` |
| `ModeRecord` | `0x01` | Mode | `2` = DUPLEX |
| `ViaRecord` | `0x02` | Longueur varint, URL UTF-8 | URL cible |
| `KnownEncodingRecord` | `0x03` | Encoding | `8` = binaire + dictionnaire |
| `UpgradeRequestRecord` | `0x09` | Longueur `21`, protocole | `application/negotiate` |

> **Statut de ces valeurs.** Les codes de record et l'ordre relèvent de
> `[MS-NMF]`, niveau *spécification*. Les valeurs de la dernière colonne
> sont celles que le **client de référence du dépôt** écrit littéralement
> (`src/nettcp/stream/nmf.py:21-24, 30-31`), niveau *implémentation
> vérifiée*. Que le module PowerShell `ActiveDirectory` émette exactement
> les mêmes octets, en particulier `Encoding = 8`, est une **déduction** :
> le serveur ne journalise pas les valeurs reçues (il ne journalise que le
> type de record, `classes/server/protocol.py:41-48`) et aucune capture
> réseau n'est versionnée. La déduction s'appuie sur deux faits observables
> : les sessions réelles aboutissent, et les charges reçues commencent bien
> par un bloc de dictionnaire de session (`build_dictionary`,
> `src/nettcp/protocol2xml.py:30-48`), ce qui n'a de sens qu'avec
> `BINARY_DICT = 8`.

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

Les longueurs sont des `varint` à bit de continuation : tant qu'elles
restent sous `0x80` elles tiennent sur un seul octet, ce qui est le cas ici
(73 et 21). Au-delà de 127 caractères d'URL, le `ViaRecord` porte deux
octets de longueur.

L'énumération `KnownEncoding` de `src/nettcp/nmf.py:178-184` liste `UTF8=3,
UTF16=4, UNICODE_LITTL_ENDIAN=5, MTOM=6, BINARY=7, BINARY_DICT=8`, et `Mode`
(`src/nettcp/nmf.py:187-191`) `SINGLETON_UNSIZED=1, DUPLEX=2, SIMPLEX=3,
SINGLETON_SIZED=4`.

> **Précision de parité.** La table d'encodages de `[MS-NMF]` couvre aussi
> les valeurs `0x00` à `0x02`, réservées à SOAP 1.1 (UTF-8, UTF-16, Unicode
> little-endian). L'énumération vendorée ne déclare **que la moitié SOAP
> 1.2** (`0x03` à `0x08`). Conséquence directe et vérifiable : un client
> annonçant un encodage SOAP 1.1 ferait échouer la coercition `as_enum('B',
> KnownEncoding)` (`src/nettcp/nmf.py:153-170`, `321-325`) sur un
> `ValueError`, capté par le `except Exception` de
> `classes/server/protocol.py:65`, connexion fermée sans réponse. Le module
> `ActiveDirectory` n'emprunte jamais ce chemin : il parle SOAP 1.2 binaire
> avec dictionnaire.

> Le tableau de `documentation/03-protocole.md:36-40` contient deux
> inexactitudes à corriger : les codes de `ModeRecord`, `ViaRecord` et
> `KnownEncodingRecord` y sont décalés d'un cran (`0x02`, `0x03`, `0x04` au
> lieu de `0x01`, `0x02`, `0x03`), et l'encodage y est donné pour `3` alors
> que la valeur émise est `8`. Le même document, dans son schéma de la phase
> 3, place le code `0x06` et la longueur *hors* du scellement GSSAPI, ce qui
> est également faux (voir plus loin). Les valeurs faisant foi sont celles
> de `src/nettcp/nmf.py`.

Côté serveur, `ProtocolHandler.handle_preamble`
(`classes/server/protocol.py:31`) boucle sur `nmf.Record.parse_stream` et se
contente de **journaliser** les codes `0x00`, `0x01`, `0x02`, `0x03` (lignes
41-48). Il ne répond rien. Deux records seulement terminent la phase :

- `0x09` `UpgradeRequestRecord` : mémorisé dans `self.pending_upgrade` et
  rendu à la phase suivante (`classes/server/protocol.py:49-54`) ;
- `0x0c` `PreambleEndRecord` : le serveur répond immédiatement
  `PreambleAckRecord` (`0x0b`) et termine le préambule
  (`classes/server/protocol.py:55-60`).

> **Il n'existe aucun chemin de session en clair.** On pourrait croire que
> la branche `0x0c` ouvre une session sans chiffrement. Ce n'est pas le cas
> : `ConnectionHandler.handle` appelle `handle_security`
> inconditionnellement après le préambule
> (`classes/server/connection.py:50`), et `handle_security` lit alors le
> record suivant et **exige** un `0x09`
> (`classes/server/protocol.py:78-86`). Un client qui terminerait son
> préambule par `PreambleEndRecord` sans demander d'upgrade recevrait son
> `PreambleAckRecord` puis verrait la connexion se fermer. Le chiffrement
> GSSAPI est donc structurellement obligatoire dans cette implémentation.

Tout autre code produit un avertissement et un `return False`
(`classes/server/protocol.py:61-63`), et la connexion est **fermée sans
aucune réponse** (`classes/server/connection.py:45-47`). Notons que le code
`0x04` (`ExtensibleEncodingRecord` de `[MS-NMF]`) n'est **pas déclaré** dans
`src/nettcp/nmf.py` : son arrivée lèverait un `KeyError` dans
`Record.parse_stream` (`src/nettcp/nmf.py:262`), capté par le `except
Exception` de `classes/server/protocol.py:65`, même issue, connexion fermée.

### Phase 3 — Upgrade de sécurité GSSAPI/SPNEGO

Cette phase est le point de bascule de la session. Côté Windows, le
transport `net.tcp` avec `SecurityMode.Transport` et
`ProtectionLevel.EncryptAndSign` s'appuie sur `NegotiateStream`
(`[MS-NNS]`). Côté serveur Linux, il n'y a pas de `NegotiateStream`.NET : on
reproduit **le cadrage** `[MS-NNS]` et on délègue la cryptographie à
`samba.gensec`.

Le déroulé exact, ancré dans le code :

1. Le serveur émet `UpgradeResponseRecord` (`0x0A`, un octet nu : la
  classe n'a aucun champ, `src/nettcp/nmf.py:336-337`) via
  `classes/server/protocol.py:92`.
2. Il remplace son flux par un `GENSECStream`
  (`classes/server/protocol.py:96`), qui enveloppe lui-même un
  `NegotiateStream` (`src/nettcp/stream/gssapi.py:89`).
3. `negotiate_server` lit d'abord un jeton client
  (`src/nettcp/stream/gssapi.py:105`), puis démarre un contexte serveur
  `gensec.Security.start_server` avec un `auth.AuthContext` (lignes
  107-108), charge les identifiants **du compte machine du DC**
  (`creds.guess(lp_ctx)` puis `creds.set_machine_account(lp_ctx)`, lignes
  113-116) et sélectionne le mécanisme `spnego` (ligne 118).
4. Il boucle sur `client_ctx.update(token)` (lignes 123-132). Tant que
  `server_finished` est faux, il écrit le jeton serveur en cadrage «
  handshake in progress » et relit le jeton suivant. Au dernier tour, il
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
`HANDSHAKE_ERROR = 0x15`, `HANDSHAKE_IN_PROGRESS = 0x16`, conformes à
`[MS-NNS]`. Les champs `major`/`minor` sont émis à `1` et `0`
(`negotiate.py:52-56`, `84-88`). Sur réception d'un `0x15`, le lecteur lit 8
octets supplémentaires et interprète le **second** mot de 32 bits big-endian
comme code d'erreur (`negotiate.py:68-72`).

La bascule de cadrage est portée par le seul drapeau `_handshake_done`
(`negotiate.py:48`) : il passe à vrai en lecture quand un `0x14` arrive
(`negotiate.py:73-74`) et en écriture dans `write_handshake_done`
(`negotiate.py:82-83`). Tant qu'il est faux, `write` préfixe l'en-tête
`0x16` de 5 octets ; une fois vrai, il émet des trames `uint32` LE
plafonnées à **`0xFC30`** (64 560 octets, `negotiate.py:59-62`). En amont,
`GENSECStream.write` découpe le texte clair en tranches de **`0xF000`** (61
440 octets, `src/nettcp/stream/gssapi.py:17`) : la marge de 3 120 octets
absorbe l'en-tête CFX Kerberos, le *confounder*, l'en-tête dupliqué et le
HMAC. Le commentaire du code est explicite : si un jeton scellé débordait
sur une seconde trame, le lecteur, qui suppose « une trame = un jeton »,
échouerait au `unwrap`.

À partir de cet instant, **toute** lecture et **toute** écriture passent par
`client_ctx.wrap` / `client_ctx.unwrap`
(`src/nettcp/stream/gssapi.py:144-170`). Les couches supérieures ne le
voient pas.

> **Branche morte, vérifiée.** `GENSECStream.write` et `GENSECStream.read`
> commencent par `if not self.client_ctx: self.negotiate`
> (`src/nettcp/stream/gssapi.py:145-146` et `155-156`). Or `GENSECStream` ne
> définit **pas** de méthode `negotiate`, seulement `negotiate_server`
> (`src/nettcp/stream/gssapi.py:104`). Ces deux lignes sont un reliquat de
> la classe cliente `GSSAPIStream` dont `GENSECStream` a été dérivée par
> copier-coller (`src/nettcp/stream/gssapi.py:20-78`). Elles ne se
> déclenchent jamais parce que `ProtocolHandler.handle_security` appelle
> explicitement `negotiate_server` avant tout échange
> (`classes/server/protocol.py:97`) ; si elles se déclenchaient, elles
> lèveraient un `AttributeError`.

Trois points de vigilance opérationnels :

- Le SPN présenté par le client doit exister sur le compte machine du DC. À
  défaut, `gensec` lève `samba.NTSTATUSError (3221225572)`, soit
  `0xC0000064` `STATUS_NO_SUCH_USER` ; le client Windows n'affiche que « Le
  site distant a fermé le flux de transport ». Correctif : `samba-tool spn
  add "host/$(hostname -f)" "$(hostname -s)$"`
  (`documentation/06-depannage.md:59`).
- Une dérive d'horloge entre le client et le KDC fait également échouer la
  phase 3 avec la **même** manifestation côté Windows, toute erreur GSSAPI
  aboutit à une fermeture de socket. En revanche le NTSTATUS côté serveur
  diffère (`KRB5KRB_AP_ERR_SKEW`, cf. RFC 4120) : ce cas **n'est pas
  documenté dans ce dépôt** et n'apparaît dans aucune trace versionnée. La
  tolérance de 5 minutes est la valeur par défaut de Kerberos, pas une
  constante de ce projet.
- Le keytab n'a pas à être exporté : `set_machine_account(lp_ctx)` lit
  directement les secrets Samba (`documentation/03-protocole.md` renvoie à
  `/var/lib/samba/private/secrets.tdb`).

> **Divergence majeure, vérifiée dans le code.** L'identité Kerberos
> négociée **n'est pas propagée à l'annuaire**.
> `classes/server/connection.py:56` construit `session_info =
> system_session` et le passe au dispatcher ; `SambaDB` ouvre ensuite
> `SamDB(lp=lp, session_info=self.session_info)`
> (`classes/directory/samba_db.py:26`). Le repli est doublé : si aucun
> `session_info` n'est transmis, `SambaDB.__init__` en fabrique un lui-même
> par `session_info or system_session` (`classes/directory/samba_db.py:15`).
> Aucune interrogation du contexte gensec pour en extraire une identité
> n'existe dans le dépôt : `GENSECStream` n'expose d'ailleurs que
> `client_ctx`, jamais le `session_info` que `samba.gensec` sait produire.
> Autrement dit : la poignée de main Kerberos joue le rôle de **portier**
> (seul un principal disposant d'un ticket valide pour le SPN du DC peut
> ouvrir une session), mais les opérations d'annuaire s'exécutent ensuite
> avec la **session système**, donc sans application des ACL AD de
> l'appelant. C'est un écart par rapport au comportement de l'ADWS
> Microsoft, qui associe chaque connexion LDAP du pool à un jeu
> d'identifiants client (paramètre `MaxConnectionsPerUser`).

### Phase 4 — Messages applicatifs scellés

`handle_messages` (`classes/server/protocol.py:107`) boucle indéfiniment sur
`nmf.Record.parse_stream`. Trois codes sont acceptés :

| Code | Record | Traitement |
|---|---|---|
| `0x0c` | `PreambleEndRecord` | Répond `0x0b`, poursuit la boucle |
| `0x06` | `SizedEnvelopedMessageRecord` | Dispatch, répond un `0x06` |
| `0x07` | `EndRecord` | Sort de la boucle, ferme |

Le `PreambleEndRecord` traité **ici** et non en phase 2 n'est pas une
bizarrerie : c'est l'ordre normal d'une session avec upgrade. Le client de
référence du dépôt l'illustre (`src/nettcp/stream/nmf.py:39-42`) : il écrit
`PreambleEndRecord` **après** avoir installé le flux GSSAPI, puis attend
`PreambleAckRecord`. Cet échange transite donc **déjà scellé**.

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
`ProtocolHandler.send_record` sérialise le record complet puis le confie au
flux courant : `data = record.to_bytes` puis `self.stream.write(data)`
(`classes/server/protocol.py:185-188`) ; après la phase 3, `self.stream` est
un `GENSECStream` dont le `write` applique `client_ctx.wrap` sur **tout** ce
qu'on lui donne (`src/nettcp/stream/gssapi.py:144-152`). En réception,
`nmf.Record.parse_stream(self.stream)` commence par `stream.read(1)` pour
lire le code : cet appel traverse `GENSECStream.read`, qui déchiffre une
trame NNS entière avant de rendre le premier octet
(`src/nettcp/stream/gssapi.py:154-170`, `src/nettcp/nmf.py:256-260`).

Le `varint` suit l'encodage `[MS-NMF]` à bit de continuation
(`src/nettcp/nmf.py:43-57` pour la lecture en flux, `78-100` pour
l'écriture, jusqu'à 5 octets, soit 28 bits utiles). Le champ `Payload` est
ensuite lu brut sur `Size` octets (`src/nettcp/nmf.py:348-353`).

Le premier octet de la charge utile est le **préfixe de dictionnaire de
session**. En émission, le dispatcher écrit `b"\x00" + encoded`
(`classes/handlers/dispatcher.py:49`) : dictionnaire dynamique vide. En
réception, `payload_to_xml` appelle `build_dictionary`
(`src/nettcp/nmf.py:363-373`, `src/nettcp/protocol2xml.py:30-48`), qui lit
un `MultiByteInt31` de taille puis autant d'octets de chaînes UTF-8,
indexées de 2 en 2 à partir de 1. C'est la confirmation que l'encodage
négocié est bien `KnownEncoding = 8` et non `7`.

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
(`classes/handlers/dispatcher.py:31-35`), y compris lorsque l'erreur
survient **avant** la résolution du handler : `_fault` récupère alors
`context.message_id` s'il existe, et une chaîne vide sinon
(`classes/handlers/dispatcher.py:52-55`). C'est indispensable : sans
`<a:RelatesTo>`, le client PowerShell considère la réponse comme non
sollicitée, la jette, et la cmdlet bloque jusqu'au *timeout*
(`documentation/06-depannage.md` §6). L'enveloppe de fault est produite par
`SoapEnvelope.fault` (`classes/soap/soap_envelope.py:46-59`), avec pour
action par défaut `http://www.w3.org/2005/08/addressing/soap/fault`
(`classes/soap/soap_envelope.py:18`).

Le compteur `self.request_index` (`classes/server/protocol.py:168`) numérote
les messages **par connexion** ; on le retrouve tel quel dans les journaux
(`[MESSAGES]... MESSAGE #0`, `#1`, …), ce qui permet de reconstituer une
session depuis `journalctl` sans capture réseau.

### Phase 5 — Fermeture

Deux terminaisons propres existent.

**Fermeture initiée par le client.** Le client envoie `EndRecord` (`0x07`,
un octet nu). Le serveur journalise, sort de la boucle et laisse le bloc
`finally` de `ConnectionHandler.handle` fermer la connexion
(`classes/server/protocol.py:170-173`,
`classes/server/connection.py:66-70`). C'est le cas observé dans tous les
journaux réels du dépôt. Le client de référence procède de même : `close`
écrit `EndRecord` puis ferme (`src/nettcp/stream/nmf.py:58-60`).

> **Écart de conformité.** Le mode `DUPLEX` de `[MS-NMF]` prévoit que
> **chaque extrémité** signale la fin de son flux par un `EndRecord`
> (demi-fermeture indépendante). Ce serveur n'émet un `EndRecord` que dans
> la branche `socket.timeout / ConnectionReset / BrokenPipe`
> (`classes/server/protocol.py:115-125`) ; à la réception d'un `EndRecord`
> client, il **ne renvoie pas** le sien. En pratique le client ferme
> immédiatement la socket derrière son `EndRecord`, ce qui rend l'écart
> inoffensif, mais il existe.

**Fermeture initiée par le serveur.** Elle n'intervient que sur erreur ou
inactivité. Le code prévoit d'abaisser le délai à 2 secondes après chaque
réponse, `self.stream._socket.settimeout(2)`
(`classes/server/protocol.py:164`), mais `self.stream` a été remplacé par un
`GENSECStream` en phase 3 (`classes/server/protocol.py:96`), et
`GENSECStream` **ne possède pas d'attribut `_socket`** : son constructeur ne
pose que `_inner`, `client_ctx`, `_readcache`, `settings` et `lp_ctx`
(`src/nettcp/stream/gssapi.py:84-102`). L'`AttributeError` est avalée par le
`except Exception: pass` des lignes 165-166. **Cette réduction de délai est
donc sans effet.** Le `_socket` réel est deux niveaux plus bas :
`GENSECStream._inner` est un `NegotiateStream`, dont `_inner` est le
`SocketStream` qui, lui, porte `_socket`
(`src/nettcp/stream/socket.py:20-21`).

**Fermeture non propre.** Si le client coupe la socket sans `EndRecord`,
`SocketStream.read(1)` retourne `b''` et l'assertion `assert len(data) == s`
de `src/nettcp/nmf.py:259` lève une `AssertionError`. Celle-ci n'est ni un
`socket.timeout` ni un `EOFError` : elle tombe dans le `except Exception`
global de `classes/server/protocol.py:179-181`, journalisée en
`[MESSAGES]... Error:` avec la trace, puis `handle_messages` retourne
`False` et `connection.py:59-60` journalise `[MESSAGES] Message exchange
failed`. Une déconnexion brutale apparaît donc dans les journaux **comme une
erreur**, ce qu'il faut savoir pour ne pas partir en chasse d'un bug
inexistant.

### Diagramme de séquence complet et annoté

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

### Coût réseau minimal d'une session

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

Soit **4 allers-retours applicatifs après la poignée de main TCP**, dans le
cas le plus favorable.

Trois réserves méthodologiques, à énoncer plutôt qu'à masquer :

- Le nombre d'allers-retours SPNEGO **n'est pas borné par le code** :
  `negotiate_server` boucle sur `client_ctx.update(token)` jusqu'à ce que
  `server_finished` soit vrai (`src/nettcp/stream/gssapi.py:123-132`).
  L'hypothèse d'un aller-retour unique correspond au cas nominal Kerberos
  avec authentification mutuelle ; elle n'est pas mesurée ici, et un
  mécanisme SPNEGO qui replierait sur NTLM en consommerait davantage.
- La coalescence TCP côté client .NET (préambule et premier jeton dans un
  même segment) est un comportement plausible de l'empilement, **non mesuré
  dans ce dépôt** : aucune capture réseau n'y est versionnée. Le seul chemin
  d'observation disponible est `tools/work/proxy.py`.
- Le tableau compte des **allers-retours logiques**, pas des segments TCP.
  Les deux ne coïncident pas.

Ce que les traces versionnées montrent en revanche sans ambiguïté, c'est
l'amortissement : une même connexion porte `Create`, `Put`, `Get` puis
`Delete` en messages `#0` à `#3`, quatre messages, un seul préambule, une
seule négociation Kerberos.

## Modèle d'exécution serveur et conséquences sur la session

### `ForkingTCPServer` : le choix structurant

`python3-samba` n'est **pas** *thread-safe* : les structures C internes de
LDB et de `samba.credentials` ne supportent pas l'accès concurrent. Le
projet a donc retenu `socketserver.ForkingTCPServer`
(`classes/server/server.py:25`) : **une connexion TCP = un processus
enfant**, isolé par la mémoire virtuelle.

| Propriété | Conséquence |
|---|---|
| Isolation mémoire totale | Aucun verrou à poser, aucun état partagé |
| Coût d'un `fork` par connexion | Amorti si le client réutilise la connexion |
| Aucun partage de cache | Chaque cache est rechauffé par processus |
| Crash confiné | Un enfant qui meurt ne tue pas le service |

Le corollaire est la règle d'or du projet, rappelée dans `CLAUDE.md` §5 et
dans `documentation/04-handlers.md` : **ne jamais ouvrir un `SamDB` au
niveau module**. Un handle ouvert avant le `fork` serait dupliqué dans tous
les enfants, avec des descripteurs de fichiers et des verrous LDB partagés,
cas d'école de corruption.

### L'ouverture paresseuse de `SamDB`

`SambaDB` (`classes/directory/samba_db.py:10`) matérialise cette règle. Le
constructeur ne fait **rien** de coûteux : il mémorise le logger et un
`session_info`, et laisse `self._db = None` (lignes 12-15). L'ouverture
réelle n'a lieu qu'au premier accès à la propriété `db` (lignes 17-21), qui
appelle `_open` : chargement de `LoadParm`, puis construction du `SamDB`
(lignes 23-27).

Ce n'est pas une micro-optimisation : c'est ce qui garantit que le `SamDB`
est **toujours** créé après le `fork`, dans l'espace mémoire de l'enfant,
quelle que soit la profondeur d'instanciation des handlers. Or
`HandlerRegistry` instancie **tous** les handlers d'un coup, par
compréhension de dictionnaire sur `HANDLER_FACTORIES`
(`classes/handlers/handler_registry.py:11-13`), et `BaseHandler.__init__`
construit un `SambaDB` pour chacun (`classes/handlers/base.py:21`).

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
`BaseHandler`**, donc **38 objets `SambaDB`** créés par connexion, mais
**aucun** n'ouvre l'annuaire tant qu'il n'est pas sollicité.

Le moment de cette construction est lui aussi précis : `ADWSDispatcher`, et
donc `HandlerRegistry`, n'est instancié qu'**après** la phase de sécurité,
juste avant `handle_messages` (`classes/server/connection.py:56-58`). Les 38
objets sont donc créés une fois par connexion, dans le processus enfant,
entre la fin du handshake Kerberos et le premier message applicatif.

La trace réelle le confirme : dans une session `Get-ADRootDSE`, la ligne
`[DB] SamDB connection established` (`classes/directory/samba_db.py:27`)
n'apparaît **qu'après** `[GetHandler] Processing:`, 48 ms après le début du
traitement, et jamais avant.

### Caches par processus

Tout ce qui ressemble à un état global dans ce code est en réalité **un état
par processus enfant**, remis à zéro à chaque connexion. Il faut le savoir
pour ne pas surestimer l'effet des caches.

| Cache | Emplacement | Portée réelle |
|---|---|---|
| `ServiceContext` (singleton) | `classes/server/service_context.py:21-26` | Un fork |
| `LdapSessionPool` | `classes/directory/ldap_session_pool.py:13` | Un fork |
| `InstanceIndex` | `classes/directory/instance_index.py:9` | Un fork |
| `SyntaxCache` par `SamDB` | `classes/server/service_context.py:28-35` | Un fork |
| `EnumerationRegistry` | `src/enumeration/enumeration.py:6-13` | Un fork |
| `SchemaHandler._CACHE` | `classes/handlers/schema.py` (attribut de classe) | Un fork |

Les verrous `threading.Lock` / `threading.RLock` présents dans
`ServiceContext`, `InstanceIndex` et `LdapSessionPool` protègent donc contre
une concurrence **intra-processus** qui, en pratique, n'existe pas dans ce
modèle d'exécution. Ils sont inoffensifs et préparent une éventuelle bascule
vers un modèle mixte.

Le `LdapSessionPool` mérite une note : il implémente un plafond de sessions
par utilisateur (`DEFAULT_PER_USER_LIMIT = 10`) et un ramasse-miettes sur
inactivité (`DEFAULT_IDLE_TIMEOUT = 600` secondes), ce qui reproduit la
logique `MaxConnectionsPerUser` de l'ADWS Microsoft. Comme il vit dans un
processus qui ne traite qu'une connexion, son plafond ne peut pas jouer son
rôle de garde-fou global.

### Adhérence de session des contextes d'énumération

Une énumération WS-Enumeration s'étale sur plusieurs messages : `Enumerate`
(création du contexte) → `Pull` × N → `Release`. Le contexte est identifié
par un UUID et **stocké en mémoire** :

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
**même connexion TCP** pour toute la séquence, donc le même fork. Les
journaux du dépôt le montrent : `MESSAGE #0` = `Enumerate`, `MESSAGE #1` =
`Pull`, sur la même connexion.

> **Fragilité connue.** Si un client ouvrait une seconde connexion pour
> émettre son `Pull`, ce que rien n'interdit dans `[MS-WSDS]`, le second
> fork ne connaîtrait pas l'UUID et `PullHandler` lèverait `Invalid or
> expired enumeration context` (`classes/handlers/pull.py:29-31`). Aucun
> stockage partagé (fichier, tmpfs, socket unix) n'est implémenté.

Notons aussi que l'`Enumerate` de ce projet **matérialise l'intégralité du
résultat** en mémoire dès la première requête
(`classes/handlers/enumerate.py:73` `materialized = list(results)`), tronque
à `MAX_RESULTS_PER_CONTEXT` (`enumerate.py:74-78`), puis pagine côté serveur
au fil des `Pull`. L'ADWS Microsoft procède différemment : les constantes du
service ADWS Microsoft fixe `pageSize = 1000` côté LDAP et les constantes du
service ADWS Microsoft `DefaultPullElements = 1u`, c'est-à-dire une
pagination LDAP réelle appuyée sur le contrôle `1.2.840.113556.1.4.319`
(`LdapPagedControlOID`).

Les contrôles LDAP envoyés par le client sont bien reconnus et traduits en
chaînes `ldb` (`classes/parsing/controls_parser.py:8-28`) : la table
`LDB_CONTROL_BY_OID` compte **19 OID**, pour **18 noms `ldb` distincts**,
`1.2.840.113556.1.4.1340` et `1.2.840.113556.1.4.2064` se traduisent tous
deux en `show_recycled`. La traduction produit `nom:criticité` ou
`nom:criticité:valeur` (`controls_parser.py:62-74`), et le résultat est
passé tel quel à `SamDB.search(controls=...)` (`enumerate.py:53`). Mais
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

### Machine d'états : table complète

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

La ligne « `0x0c` en PREAMBULE » est celle qu'on lit de travers le plus
souvent. Elle ne mène **pas** à l'état MESSAGES : `handle_preamble` renvoie
`True`, et `ConnectionHandler.handle` enchaîne inconditionnellement sur
`handle_security` (`classes/server/connection.py:50`). Il n'y a donc qu'une
seule porte vers l'état MESSAGES, et elle passe par la négociation GSSAPI.

Le tableau ci-dessous récapitule les treize codes de `[MS-NMF]` et leur sort
exact dans ce serveur. `register_types` (`src/nettcp/nmf.py:394-406`)
enregistre par introspection **toutes** les sous-classes de `Record` du
module : un code défini est donc toujours *analysable*, même s'il n'est
jamais *accepté* par la machine d'états.

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
classe par `rec = cls._records[code]` (`src/nettcp/nmf.py:262`). Un code
absent du registre lève un `KeyError`, pas un avertissement propre. La
différence est visible dans les journaux : un code **connu mais inattendu**
produit `... Unexpected record code: 0x05`, tandis qu'un code **inconnu**
produit une trace d'exception `... Error:`.

L'absence d'émission de `FaultRecord` mérite un mot : les erreurs
applicatives remontent en **SOAP fault** dans un `0x06` normal, jamais en
fault de couche NMF. Une erreur de couche NMF ou WCF, elle, coupe simplement
la connexion, d'où le message Windows « Le site distant a fermé le flux de
transport » (`documentation/06-depannage.md` §2).

### Bornes et quotas : ce projet contre l'ADWS Microsoft

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

Côté projet, deux champs de configuration sont **déclarés mais jamais lus**
: `ServerConfig.max_connections = 128` et `ServerConfig.timeout = 300`
(`classes/server/config.py:17-18`), aucune autre occurrence dans le dépôt.
C'est un des chantiers de la phase 5 « performance + durcissement ». Le seul
plafond réellement actif est `MAX_CONTEXTS = 256` du cache d'énumération, et
il est **par processus**, donc sans effet global.

Enfin, la version annoncée diverge :

| Champ | ADWS Microsoft | Ce projet |
|---|---|---|
| Version majeure | `1` | — |
| Version mineure | `1` | — |
| Chaîne de version | `Active Directory Web Services v1.1` | — |
| `ca:Server` | non exposé sous cette forme | `1.0.0` (`get_version.py:9`) |
| `ca:Protocol` | `1.1` implicite | `1.1` (`get_version.py:10`) |

`GetVersionHandler` répond donc `Server = 1.0.0` là où Microsoft annonce
`v1.1` dans `VersionString`. Aucune cmdlet connue ne s'appuie sur cette
valeur, mais l'écart est réel et doit être tracé.

## Cartographie du code : de la socket au SamDB

### Table de correspondance par étape

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

`src/nettcp/` et `src/wcf/` sont du code tiers **vendoré** (attribution «
Copyright 2016 Timo Schmid » en tête de fichier), intégré au dépôt mais
exclu des normes de codage du projet, c'est explicité dans
`documentation/01-architecture.md:79-80` et matérialisé dans
`pyproject.toml:9-10` et `:30-33`. C'est ce qui explique que ces fichiers
enfreignent ouvertement les règles de `CLAUDE.md` §6.1 (plusieurs classes
par fichier, absence d'annotations de type, commentaires en ligne) : ils
sont hors périmètre du vérificateur `tools/norms`.

### Chronologie mesurable d'un `Get-ADRootDSE`

La séquence ci-dessous est reconstituée depuis une trace réelle du dépôt
(`adws.log`, connexion `172.19.0.3:64321`, 4 juin 2026 à 05:21:28). Il
s'agit bien d'un **`Get-ADRootDSE`** : le journal montre `[GetHandler]
Processing: 11111111-1111-1111-1111-111111111111`, qui est exactement
l'identifiant conventionnel de la racine d'annuaire. Les durées sont celles
mesurées par l'horodatage du journal serveur ; le temps réseau client n'y
figure pas, et chaque poste inclut son propre coût de journalisation, ce
sont donc des **bornes supérieures**.

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

1. Le **coût dominant d'une cmdlet isolée est la négociation
  Kerberos**, pas l'accès à l'annuaire. C'est l'argument central en faveur
  de la réutilisation de connexion : une session qui enchaîne dix messages
  amortit ces 79 ms une seule fois.
2. Le client PowerShell **ouvre une connexion par cmdlet** lorsqu'il
  n'a rien à enchaîner. Les journaux montrent quatre connexions successives
  (`64321`, `64322`, `64323`, `64324`) pour quatre cmdlets, chacune payant
  son préambule et son handshake. En revanche, une cmdlet composite paie une
  seule fois : les traces `Create` → `Put` → `Get` → `Delete` tiennent sur
  une connexion unique, en messages `#0` à `#3`.
3. L'ouverture du `SamDB` (~49 ms entre `handler=GetHandler` et `[DB]
  SamDB connection established`) est payée **une fois par processus**, au
  premier handler qui touche l'annuaire. Sur une session multi-messages, les
  messages suivants n'en supportent pas le coût.

Le nombre minimal d'allers-retours réseau pour une cmdlet isolée est donc de
**5** : la poignée de main TCP, puis les quatre échanges applicatifs du
tableau de la section précédente (`UpgradeResponse`, jeton SPNEGO,
`PreambleAck`, message SOAP), la fermeture ne comptant que pour une
demi-boucle. Ce chiffre suppose un aller-retour SPNEGO unique, hypothèse
discutée plus haut.

### Points de rupture typiques et où regarder

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
faut alors remonter le journal jusqu'à la dernière trace avant `[CONNECTION]
CONNECTION CLOSED`.

Pour observer le clair, la capture `tcpdump -i any -w /tmp/adws.pcap port
9389` ne montre que du chiffré à partir de la phase 3 ; le seul moyen de
voir le XML applicatif est de passer par l'outil de capture
`tools/work/proxy.py` ou de décoder un payload isolé avec
`src.wcf.records.dump_records`.

### Récapitulatif des écarts vérifiés dans le code

Ce chapitre a mis au jour, pièce en main, sept écarts entre ce qui est
annoncé (spécification, `CLAUDE.md`, `documentation/`) et ce que le code
fait réellement. Ils sont rassemblés ici pour servir de liste de travail ;
chacun est démontré dans la section correspondante.

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
l'encodage donné pour `3` (lignes 36-40), et le schéma de la phase 3 qui
place le code `0x06` et la longueur hors du scellement GSSAPI.

> Aucun de ces écarts n'empêche les cmdlets de fonctionner contre un DC
> Samba : les phases 1 à 5 se déroulent, les objets remontent, les écritures
> passent. Ils décrivent en revanche exactement le périmètre de la phase 5
> du projet, « performance + durcissement sécurité », et en particulier le
> premier, qui est le seul à avoir une portée de sécurité réelle.

# Partie III. Le cadrage .NET Message Framing

## Rôle et principes du cadrage .NET Message Framing

### Ce que le cadrage résout

TCP fournit un flux d'octets continu, sans notion de frontière de message.
Le service ADWS, lui, échange des *messages* SOAP discrets. Il faut donc une
couche qui découpe le flux en unités et qui transporte les propriétés de
session indispensables avant même que le premier message n'existe : version
du cadrage, mode de communication, URI de destination, encodage retenu,
éventuelle demande d'élévation de sécurité.

C'est exactement le périmètre du .NET Message Framing Protocol, publié par
Microsoft sous la référence **[MC-NMF]** ; la liaison TCP proprement dite
fait l'objet de **[MS-NMFTB]**. Ce dépôt et `CLAUDE.md` emploient la forme
**[MS-NMF]**, conservée ici par cohérence : c'est le même corpus normatif,
et les sections citées renvoient au document [MC-NMF].

Le cadrage NMF est délibérément minimal. Il ne fait **pas** :

- de corrélation requête/réponse : c'est le rôle de WS-Addressing
  (`<a:MessageID>` / `<a:RelatesTo>`, cf. le chapitre SOAP) ;
- de multiplexage : une connexion transporte un message à la fois, en
  séquence stricte, jamais deux messages entrelacés ;
- de compression : la compacité vient de la couche [MS-NBFX]/[MS-NBFS] ;
- de chiffrement : la confidentialité vient de l'*upgrade* de sécurité, donc
  de GSSAPI/Kerberos ;
- de contrôle de flux applicatif : pas de fenêtre, pas d'accusé de réception
  par message (le seul acquittement est celui du préambule).

### Records, initiateur et receveur

L'unité élémentaire est le **record** : un octet de type, suivi
éventuellement d'une charge utile dont la forme dépend du type. [MS-NMF]
distingue deux familles :

- les **Property Records**, qui portent des propriétés de session (version,
  mode, via, encodage, demande et réponse d'*upgrade*, fin et acquittement
  de préambule) ;
- les **Envelope Records**, qui portent la charge utile applicative
  (`SizedEnvelopeRecord`, `UnsizedEnvelopeRecord`).

Le protocole est **asymétrique** : la grammaire ABNF de [MS-NMF] section
3.1.1.2 définit deux flux distincts, `ProtocolStream-a` de l'initiateur vers
le receveur et `ProtocolStream-b` du receveur vers l'initiateur. Le client
Windows est toujours l'initiateur ; le serveur souverain n'émet jamais de
`VersionRecord`, de `ModeRecord`, de `ViaRecord` ni de
`KnownEncodingRecord`.

Dans ce projet, le vocabulaire du code reflète cette asymétrie : la classe
serveur `ProtocolHandler` (`classes/server/protocol.py:21`) ne sait que
*lire* les records de propriété, tandis que la classe cliente `NMFStream`
(`src/nettcp/stream/nmf.py:11`), utilisée uniquement par l'outillage de
debug, sait les *produire*.

### Les quatre modes de cadrage

Le `ModeRecord` fixe la forme du dialogue pour toute la durée de la
connexion. [MS-NMF] section 2.2.3.2 en définit quatre ; la valeur `0x00` est
invalide et `0x05`–`0xFF` est réservée.

| Valeur | Mode | Sens | Enveloppes |
|---|---|---|---|
| `0x01` | Singleton-Unsized | Un message aller, ou une paire requête/réponse | `UnsizedEnvelopeRecord` |
| `0x02` | Duplex | Messages bidirectionnels multiples | `SizedEnvelopeRecord` |
| `0x03` | Simplex | Messages unidirectionnels multiples | `SizedEnvelopeRecord` |
| `0x04` | Singleton-Sized | Un unique message unidirectionnel | flux d'octets brut |

**ADWS utilise exclusivement le mode Duplex (`0x02`).** C'est le mode
qu'impose la liaison `NetTcpBinding` de WCF côté Microsoft (configuration
`ActiveDirectoryWebServicesNetTcpBindingConfiguration`), et c'est celui que
le client de debug du dépôt fixe en dur. La raison est fonctionnelle : une
session ADWS enchaîne des dizaines d'aller-retours sur la même connexion TCP
(`Get-ADRootDSE`, puis `Enumerate`, puis une série de `Pull`, puis
`Release`), et l'affinité de session est indispensable, le cache de
contextes d'énumération est un *singleton* de processus
(`src/enumeration/enumeration.py:6-13`), donc lié au processus fils qui a
servi le `Enumerate` (cf. `documentation/03-protocole.md`, section «
Énumération paginée »).

> **Niveau de preuve.** Aucune capture réseau d'un client Windows n'existe
> dans ce dépôt. L'affirmation « le client PowerShell envoie toujours Duplex
> » est déduite de la spécification et du comportement de `NetTcpBinding`,
> pas d'une trace observée. Ce qui est vérifié dans le code, c'est que le
> serveur souverain ne traite correctement que ce mode.

Dans l'implémentation, l'énumération `Mode` est déclarée en
`src/nettcp/nmf.py:187-191` avec les quatre valeurs. Le client de debug fixe
`ModeRecord(Mode=2)` en dur (`src/nettcp/stream/nmf.py:22`). Côté serveur,
`ProtocolHandler.handle_preamble` journalise la réception du `ModeRecord`
(`classes/server/protocol.py:43-44`) mais **ne vérifie pas** la valeur : une
session annoncée Simplex ou Singleton-Sized serait traitée comme du Duplex.

### Position dans l'empilement, avant et après l'*upgrade*

Le point le plus contre-intuitif du cadrage ADWS est que la couche NMF se
retrouve **des deux côtés** de la couche de sécurité. Le préambule circule
en clair ; l'*upgrade* « application/negotiate » installe un tunnel GSSAPI ;
et tous les records NMF ultérieurs (y compris `PreambleEndRecord`,
`PreambleAckRecord`, `SizedEnvelopeRecord` et `EndRecord`) transitent *à
l'intérieur* de ce tunnel.

```text
AVANT l'upgrade                      APRÈS l'upgrade
───────────────                      ───────────────
┌───────────────────────┐            ┌───────────────────────────────┐
│ Records NMF en clair  │            │ NBFX/NBFS (XML binaire WCF)   │
│ 00 / 01 / 02 / 03 /09 │            ├───────────────────────────────┤
├───────────────────────┤            │ Records NMF : 06 / 07 / 0b/0c │
│ TCP 9389              │            ├───────────────────────────────┤
└───────────────────────┘            │ GSSAPI wrap (Kerberos AES)    │
                                     ├───────────────────────────────┤
                                     │ Cadrage NNS : uint32 LE + tok │
                                     ├───────────────────────────────┤
                                     │ TCP 9389                      │
                                     └───────────────────────────────┘
```

Cette lecture est directement vérifiable dans le code : après
`handle_security`, `self.stream` est remplacé par un `GENSECStream`
(`classes/server/protocol.py:96`), et c'est ce flux déchiffrant qui est
passé à `nmf.Record.parse_stream` dans la boucle de messages
(`classes/server/protocol.py:114`). L'octet de type de record lui-même est
donc lu à travers `GENSECStream.read(1)`, c'est-à-dire après
désencapsulation.

Le schéma d'empilement de `documentation/03-protocole.md:8-21` place GSSAPI
*au-dessus* de « Net.tcp framing (MS-NMF) » : c'est vrai du préambule, faux
des enveloppes. La formulation de [MS-NMF] est plus juste : une fois
l'*upgrade* accepté, **tous les octets suivants du flux protocolaire passent
par le flux élevé**.

## Encodage des primitives : entiers variables et chaînes

### L'entier à taille variable (« Record Size Encoding »)

Toutes les longueurs de NMF utilisent le même encodage, décrit en [MS-NMF]
section 2.2.2. Il s'agit d'un entier non signé en base 128, **groupes de
poids faible en premier**, chaque octet portant sept bits de donnée et un
bit de continuation en position de poids fort.

Algorithme d'encodage :

1. Tant que la valeur restante dépasse `0x7F`, émettre `(valeur &
  0x7F) | 0x80` puis décaler la valeur de 7 bits à droite.
2. Émettre le reste, `valeur & 0x7F`, sans bit de continuation.

Algorithme de décodage :

1. Lire un octet. Accumuler `(octet & 0x7F) << (7 * rang)`.
2. Si le bit `0x80` est positionné, incrémenter le rang et recommencer
  ; sinon, l'entier est complet.

La table normative de [MS-NMF] section 2.2.2 donne les bornes suivantes :

| Intervalle de valeur | Octets |
|---|---|
| `0x00`–`0x7F` | 1 |
| `0x80`–`0x3FFF` | 2 |
| `0x4000`–`0x1FFFFF` | 3 |
| `0x200000`–`0x0FFFFFFF` | 4 |
| `0x10000000`–`0xFFFFFFFF` | 5 |

La spécification prévoit des tailles allant jusqu'à `0xFFFFFFFF`, soit cinq
octets, tandis que sa grammaire ABNF restreint le cinquième octet, ce qui
abaisse le plafond exprimable. Cette divergence interne est sans conséquence
pour ADWS, dont les messages sont plafonnés bien plus bas.

### Exemples chiffrés, vérifiés contre le code du dépôt

Les valeurs ci-dessous ont été produites en exécutant `varint_encode`
(`src/nettcp/nmf.py:78`) et `varint.stream` (`src/nettcp/nmf.py:60`) du
dépôt. Elles ne sont pas reconstituées à la main.

| Valeur | Encodage | Octets | Remarque |
|---|---|---|---|
| `0` | `00` | 1 | cas spécial explicite ligne 79-80 |
| `1` | `01` | 1 | — |
| `0x15` (21) | `15` | 1 | longueur de `application/negotiate` |
| `0x4A` (74) | `4a` | 1 | longueur d'un Via typique |
| `0x7F` (127) | `7f` | 1 | dernière valeur sur 1 octet |
| `0x80` (128) | `80 01` | 2 | première continuation |
| `0x81` (129) | `81 01` | 2 | — |
| `0x3A98` (15000) | `98 75` | 2 | taille de réponse plausible |
| `0x3FFF` | `ff 7f` | 2 | dernière valeur sur 2 octets |
| `0xFFFF` (65535) | `ff ff 03` | 3 | — |
| `0x4000` | `80 80 01` | 3 | — |
| `0xF000` (61440) | `80 e0 03` | 3 | taille du bloc GSS `_PLAINTEXT_CHUNK` |
| `0x100000` (1 Mio) | `80 80 40` | 3 | quota `MaxReceivedMessageSize` réel |
| `0x1FFFFF` | `ff ff 7f` | 3 | dernière valeur sur 3 octets |
| `0x200000` | `80 80 80 01` | 4 | — |
| `0x0FFFFFFF` | `ff ff ff 7f` | 4 | dernière valeur sur 4 octets |
| `0x10000000` | `80 80 80 80 01` | 5 | — |
| `0xFFFFFFFF` | `ff ff ff ff 0f` | 5 | maximum normatif |

Lecture de `ff ff 03` : premier octet `0xFF` → bits 0-6 = `0x7F`,
continuation ; deuxième octet `0xFF` → bits 7-13 = `0x7F`, continuation ;
troisième octet `0x03` → bits 14-20 = `3`, fin. Total : `0x7F | (0x7F << 7)
| (3 << 14)` = `65535`.

### Écarts de l'implémentation Python

Le décodeur du dépôt s'écarte de la spécification sur trois points, tous
vérifiés par exécution.

**Aucune borne sur le nombre d'octets.** `varint_stream`
(`src/nettcp/nmf.py:60-73`) boucle sur `while True` et ne sort que sur un
octet nul ou un octet sans bit de continuation. Un varint de sept octets est
accepté sans broncher : l'entrée `80 80 80 80 80 80 01` est décodée en
`0x40000000000`, très au-delà du plafond de cinq octets de la spécification.
Comparativement, le décodeur de la couche WCF, `MultiByteInt31.parse`
(`src/wcf/datatypes.py:20-31`), borne explicitement sa boucle par `range(5)`
(ligne 23) et traite l'octet manquant comme une fin de flux. Cette absence
de borne côté NMF est un vecteur de déni de service : un pair malveillant
qui émet un flux continu d'octets `0x80` fait diverger l'entier Python, de
taille arbitraire, jusqu'à épuisement mémoire du processus fils. C'est un
point de durcissement à traiter en phase 5.

**L'octet nul termine le varint.** Les deux décodeurs contiennent `if not d:
break` (`src/nettcp/nmf.py:50-51` et `:65-66`), ce qui interrompt la lecture
sur un `0x00` sans l'accumuler. Conséquence : la séquence `80 00`, malformée
au sens de la grammaire ABNF (le dernier octet doit être `%x01-7F`), est
décodée en `0` au lieu d'être rejetée. Cette tolérance est empruntée à
l'implémentation d'origine ; elle n'a pas d'effet observé avec un client
Windows conforme, mais elle relâche la validation.

**Troncature silencieuse à l'encodage au-delà de 2^35.** `varint_encode`
(`src/nettcp/nmf.py:78-100`) ne comporte que cinq branches ; la dernière
émet `(val >> 28) & 0x7f` comme cinquième octet. La valeur `0x7FFFFFFFF`
(2^35 − 1) fait encore l'aller-retour correctement ; `0x800000000` est
encodée en `80 80 80 80 00` et se relit en `0`. Aucune exception n'est
levée. Comme les messages ADWS réels sont de l'ordre du kilo-octet, ce cas
est inatteignable en production, mais il n'est pas gardé.

### Chaînes de caractères

NMF ne connaît qu'une seule forme de chaîne : **un varint de longueur en
octets, suivi des octets UTF-8**. Pas de terminateur nul, pas de marque
d'ordre d'octets, pas d'échappement ; la grammaire ABNF n'admet que des
séquences UTF-8 valides.

Trois records du dépôt portent une chaîne, `ViaRecord`
(`src/nettcp/nmf.py:313-318`), `UpgradeRequestRecord` (`:328-333`) et
`FaultRecord` (`:379-384`). Le `ExtensibleEncodingRecord` en porte une
également selon la spécification, mais il n'est pas implémenté ici.

L'implémentation matérialise ce couple longueur/valeur par une liste
`fields` de deux entrées, la seconde renvoyant à la première par son nom :

```python
class ViaRecord(Record):
    code = 0x02
    fields = [
        ('ViaLength', varint),
        ('Via', pt(utf8, 'ViaLength')),
    ]
```

L'auxiliaire `pt` (`src/nettcp/nmf.py:34-40`) est un `functools.partial`
enrichi qui propage les attributs `encode` et `stream` du décodeur, de sorte
que le lecteur générique `Record.parse_stream` (`src/nettcp/nmf.py:255-273`)
sache appeler `utf8_stream('ViaLength', obj, stream)` et lire exactement
`ViaLength` octets (`src/nettcp/nmf.py:111-113`).

> **Attention, longueur en octets, pas en caractères.** Le constructeur
> `ViaRecord(ViaLength=len(self.url), Via=self.url)`
> (`src/nettcp/stream/nmf.py:23`) mesure la longueur d'une chaîne Python,
> donc un nombre de *caractères*. Pour une URL `net.tcp` purement ASCII, le
> seul cas rencontré, les deux coïncident. Une URL comportant un caractère
> non-ASCII produirait un `ViaLength` inférieur au nombre d'octets
> réellement émis et désynchroniserait le flux. Ce code n'étant utilisé que
> par l'outillage client de debug, le serveur n'est pas exposé ; le
> correctif serait `len(self.url.encode('utf-8'))`.

## Catalogue exhaustif des records

### Table maîtresse

Les valeurs d'octet ci-dessous sont celles déclarées dans
`src/nettcp/nmf.py` et concordent avec la table normative de [MS-NMF]
section 2.2.1. La colonne « Ligne » renvoie à la déclaration de la classe
correspondante.

| Octet | Record | Direction | Charge utile |
|---|---|---|---|
| `0x00` | VersionRecord | client → serveur | 2 octets : major, minor |
| `0x01` | ModeRecord | client → serveur | 1 octet : mode |
| `0x02` | ViaRecord | client → serveur | varint + UTF-8 |
| `0x03` | KnownEncodingRecord | client → serveur | 1 octet : encodage |
| `0x04` | ExtensibleEncodingRecord | client → serveur | varint + UTF-8 |
| `0x05` | UnsizedEnvelopeRecord | bidirectionnel | chunks + terminateur |
| `0x06` | SizedEnvelopeRecord | bidirectionnel | varint + octets |
| `0x07` | EndRecord | bidirectionnel | aucune |
| `0x08` | FaultRecord | serveur → client | varint + URI UTF-8 |
| `0x09` | UpgradeRequestRecord | client → serveur | varint + UTF-8 |
| `0x0A` | UpgradeResponseRecord | serveur → client | aucune |
| `0x0B` | PreambleAckRecord | serveur → client | aucune |
| `0x0C` | PreambleEndRecord | client → serveur | aucune |
| `0x0D`–`0xFF` | réservé | — | — |

Correspondance avec le code du dépôt :

| Octet | Classe Python | Fichier et ligne | Émis par le serveur |
|---|---|---|---|
| `0x00` | `VersionRecord` | `src/nettcp/nmf.py:298` | non |
| `0x01` | `ModeRecord` | `src/nettcp/nmf.py:306` | non |
| `0x02` | `ViaRecord` | `src/nettcp/nmf.py:313` | non |
| `0x03` | `KnownEncodingRecord` | `src/nettcp/nmf.py:321` | non |
| `0x04` | *absente* | — | non |
| `0x05` | `UnsizedEnvelopedMessageRecord` | `src/nettcp/nmf.py:387` | non |
| `0x06` | `SizedEnvelopedMessageRecord` | `src/nettcp/nmf.py:348` | oui |
| `0x07` | `EndRecord` | `src/nettcp/nmf.py:375` | oui |
| `0x08` | `FaultRecord` | `src/nettcp/nmf.py:379` | non |
| `0x09` | `UpgradeRequestRecord` | `src/nettcp/nmf.py:328` | non |
| `0x0A` | `UpgradeResponseRecord` | `src/nettcp/nmf.py:336` | oui |
| `0x0B` | `PreambleAckRecord` | `src/nettcp/nmf.py:344` | oui |
| `0x0C` | `PreambleEndRecord` | `src/nettcp/nmf.py:340` | non |

Les noms des classes d'enveloppe diffèrent de ceux de la spécification
(`SizedEnvelopedMessageRecord` pour *Sized Envelope Record*) : c'est un
héritage de la bibliothèque vendorisée d'origine, conservé tel quel pour ne
pas casser les imports. Ces deux noms figurent d'ailleurs dans le `__all__`
du module (`src/nettcp/nmf.py:11-25`), qui expose onze classes de record,
`FaultRecord` n'y est pas listé, ce qui est cohérent avec le fait qu'il ne
soit jamais utilisé.

L'enregistrement des types se fait par introspection : `register_types`
(`src/nettcp/nmf.py:394-406`) parcourt les classes du module et appelle
`Record.register` pour chaque sous-classe de `Record`. Un contrôle exécuté
sur le dépôt donne la liste effective des codes enregistrés : `0, 1, 2, 3,
5, 6, 7, 8, 9, 10, 11, 12`. **Le code `0x04` est absent** : la classe
`ExtensibleEncodingRecord` n'existe pas dans ce projet. Un client qui
annoncerait un encodage extensible (une chaîne de type MIME au lieu d'un
octet connu) provoquerait un `KeyError` dans `Record.parse_stream`
(`src/nettcp/nmf.py:262`) et la fermeture immédiate de la connexion. Ce
n'est pas un problème pratique, le client PowerShell utilise toujours le
`KnownEncodingRecord`, mais c'est un écart formel avec la règle ABNF
`EncodingRecord = KnownEncodingRecord / ExtensibleEncodingRecord`.

### VersionRecord : ne pas confondre deux versions

`VersionRecord` porte deux octets bruts. La grammaire ABNF est catégorique :
`MajorVersionNumber = %x01` et `MinorVersionNumber = %x00`. La version du
*cadrage* est donc figée à **1.0**.

Il ne faut pas la confondre avec la version du *service* ADWS, renvoyée par
l'action applicative `GetVersion` (cf. `documentation/04-handlers.md`).
Quatre plans de versionnement cohabitent et ne doivent jamais être confondus
:

| Plan | Valeur | Ancrage |
|---|---|---|
| Cadrage NMF | major 1, minor 0 | `src/nettcp/nmf.py:298-303` |
| Handshake NNS | major 1, minor 0 | `src/nettcp/stream/negotiate.py:53-54` |
| Service ADWS (Microsoft) | 1.1 | Service ADWS Microsoft |
| Service ADWS (ce projet) | Server 1.0.0, Protocol 1.1 | `classes/handlers/get_version.py:9-10` |

Microsoft déclare `VersionMajor = 1`, `VersionMinor = 1` et `VersionString =
"Active Directory Web Services v1.1"` ; le handler souverain, lui, annonce
`<ca:Server>1.0.0</ca:Server>` et ne reprend `1.1` que dans `<ca:Protocol>`.
L'effet de cet écart sur le module PowerShell n'a pas été observé dans ce
dépôt.

Le serveur souverain n'inspecte ni `MajorVersion` ni `MinorVersion`
(`classes/server/protocol.py:41-42` se contente d'un message de journal) et
n'émet donc jamais le fault `UnsupportedVersion`.

### KnownEncodingRecord : la table complète

[MS-NMF] section 2.2.3.3 définit neuf valeurs ; `0x09`–`0xFF` sont
réservées.

| Octet | SOAP | Encodage | Membre `KnownEncoding` |
|---|---|---|---|
| `0x00` | 1.1 | UTF-8 | *non déclaré* |
| `0x01` | 1.1 | UTF-16 | *non déclaré* |
| `0x02` | 1.1 | Unicode little-endian | *non déclaré* |
| `0x03` | 1.2 | UTF-8 | `UTF8` |
| `0x04` | 1.2 | UTF-16 | `UTF16` |
| `0x05` | 1.2 | Unicode little-endian | `UNICODE_LITTL_ENDIAN` |
| `0x06` | 1.2 | MTOM | `MTOM` |
| `0x07` | 1.2 | binaire [MS-NBFS] | `BINARY` |
| `0x08` | 1.2 | binaire + dictionnaire in-band [MS-NBFSE] | `BINARY_DICT` |

L'énumération Python correspondante est en `src/nettcp/nmf.py:178-184`. Elle
ne déclare **que** les valeurs 3 à 8 ; les trois encodages SOAP 1.1 sont
absents. Comme le champ est décodé par `as_enum('B', KnownEncoding)`
(`src/nettcp/nmf.py:153-170`), une valeur hors énumération lève un
`ValueError` lors de la construction du membre, exception qui remonte
jusqu'au `except Exception` de `handle_preamble`
(`classes/server/protocol.py:65`) et provoque la fermeture de la connexion
sans réponse. Dit autrement, **ce serveur rejette de fait tout encodage SOAP
1.1**, ce qui est cohérent avec ADWS mais n'est pas une validation explicite
: c'est un effet de bord du typage.

**ADWS impose la valeur `0x08`**, binaire avec dictionnaire in-band. Le
client de debug la fixe en dur (`KnownEncodingRecord(Encoding=8)`,
`src/nettcp/stream/nmf.py:24`) et le format de la charge utile le confirme :
tout message applicatif commence par un `MultiByteInt31` donnant la taille
de la table de dictionnaire de session (`src/nettcp/protocol2xml.py:32-35`),
et le dispatcher préfixe systématiquement ses réponses d'un octet `0x00`
correspondant à une table vide (`classes/handlers/dispatcher.py:49`). Ce
préfixe n'existerait pas avec l'encodage `0x07`.

> Le serveur **ne vérifie pas** la valeur reçue : `handle_preamble` se
> contente de journaliser (`classes/server/protocol.py:47-48`). Un client
> qui annoncerait `0x03` (SOAP 1.2 texte) serait accepté au préambule, puis
> échouerait au premier message quand le décodeur binaire tenterait de lire
> une table de dictionnaire dans du XML textuel. Le fault normatif
> `ContentTypeInvalid` n'est jamais émis.

### Les records sans charge utile

`UpgradeResponseRecord` (`0x0A`), `PreambleAckRecord` (`0x0B`),
`PreambleEndRecord` (`0x0C`) et `EndRecord` (`0x07`) se réduisent à leur
octet de type. Dans le code, cela se traduit par une classe sans attribut
`fields`, qui hérite donc de `Record.fields = []` (`src/nettcp/nmf.py:222`).
Leur méthode `to_bytes` produit un unique octet, ce qui explique la
comparaison directe `if d != UpgradeResponseRecord.to_bytes` du client de
debug (`src/nettcp/stream/nmf.py:34`).

### FaultRecord : le vocabulaire normatif

`FaultRecord` transporte un URI UTF-8 précédé de sa longueur ; la
spécification interdit une longueur nulle. Les noms de fault définis par
[MS-NMF] section 2.2.5.1 vivent dans l'espace de noms
`http://schemas.microsoft.com/ws/2006/05/framing/faults/`. Un fault complet
ressemble donc à
`http://schemas.microsoft.com/ws/2006/05/framing/faults/UnsupportedMode`.

| Nom de fault | Sens |
|---|---|
| `ConnectionDispatchFailed` | Endpoint du Via existant, dispatch échoué |
| `ContentTypeInvalid` | Encodage annoncé non supporté par l'endpoint |
| `ContentTypeTooLong` | Record d'encodage dépassant le quota de taille |
| `EndpointNotFound` | Endpoint du Via introuvable |
| `EndpointUnavailable` | Endpoint existant mais indisponible |
| `MaxMessageSizeExceededFault` | Message dépassant le quota de taille |
| `ServerTooBusy` | Ressources insuffisantes pour la connexion |
| `ServiceActivationFailed` | Processus de l'endpoint non activable |
| `UnsupportedMode` | Valeur du ModeRecord non supportée |
| `UnsupportedVersion` | Valeur du VersionRecord non supportée |
| `UpgradeInvalid` | Élévation demandée non supportée |
| `ViaTooLong` | Via dépassant le quota de taille |

> **Portée de cette table.** Ces douze noms proviennent exclusivement de la
> spécification. **Aucun d'eux n'apparaît nulle part dans ce dépôt** : une
> recherche sur `UnsupportedMode`, `ViaTooLong`, `ServerTooBusy` et
> `EndpointNotFound` dans `src/` et `classes/` ne renvoie aucun résultat. La
> table n'est donc pas présentée comme exhaustive : d'autres noms de fault
> de cadrage circulent dans la littérature WCF sans avoir pu être corroborés
> ici, et ils ne sont volontairement pas repris.

> **État de cette implémentation :** la classe `FaultRecord`
> (`src/nettcp/nmf.py:379-384`) sait *décoder* un fault entrant, mais aucun
> point du dépôt ne l'instancie. Une recherche exhaustive sur `FaultRecord`
> dans les sources Python ne remonte que sa déclaration
> (`src/nettcp/nmf.py:379`). **Aucune des chaînes ci-dessus n'est connue,
> produite ni consommée par le serveur souverain.** Elles sont documentées
> ici parce qu'elles peuvent apparaître dans une capture `tcpdump` en
> provenance d'un ADWS Microsoft, et parce qu'elles constituent la feuille
> de route naturelle du durcissement de la couche de cadrage.

## Le préambule : séquence, ordre et validation

### La grammaire normative

La grammaire ABNF de [MS-NMF] section 3.1.1.2 décrit précisément la séquence
attendue dans le cas Duplex, dans les deux sens :

```text
DuplexStream-a = VersionRecord ModeRecordType DuplexMode ViaRecord
                 EncodingRecord *UpgradeRequest PreambleEndRecord
                 *SizedEnvelopeRecord EndRecord

DuplexStream-b = (*UpgradeResponse FaultRecord)
               / (*UpgradeResponse PreambleAckRecord
                  *SizedEnvelopeRecord (FaultRecord / EndRecord))

UpgradeRequest  = UpgradeRequestRecord Octets
UpgradeResponse = UpgradeResponseRecord Octets
EncodingRecord  = KnownEncodingRecord / ExtensibleEncodingRecord
```

Deux enseignements. D'abord, l'ordre est **strict** : version, mode, via,
encodage, puis zéro ou plusieurs *upgrades*, puis fin de préambule. Ensuite,
les règles `UpgradeRequest` et `UpgradeResponse` sont suivies de `Octets` :
la négociation de sécurité proprement dite n'est pas cadrée par NMF, elle
est un flux d'octets opaque inséré dans la séquence. C'est là que
s'intercale le cadrage [MS-NNS] côté Microsoft, ou `samba.gensec` côté
serveur souverain.

### Hexdump annoté d'un préambule client complet

Le fragment ci-dessous a été produit en instanciant les classes du dépôt
pour un Via réaliste
(`net.tcp://dc1.samba.local:9389/ActiveDirectoryWebServices/`
`Windows/Resource`, 74 octets). Il fait 106 octets et correspond exactement
à ce qu'un client PowerShell envoie en ouverture de session.

```text
00                     VersionRecord (type 0x00)
   01                    MajorVersion = 1   (ABNF : MUST %x01)
   00                    MinorVersion = 0   (ABNF : MUST %x00)
01                     ModeRecord (type 0x01)
   02                    Mode = 0x02 = Duplex
02                     ViaRecord (type 0x02)
   4a                    ViaLength = 74 (varint 1 octet, < 0x80)
   6e 65 74 2e 74 63 70 3a   "net.tcp:"
   2f 2f 64 63 31 2e 73 61   "//dc1.sa"
   6d 62 61 2e 6c 6f 63 61   "mba.loca"
   6c 3a 39 33 38 39 2f 41   "l:9389/A"
   63 74 69 76 65 44 69 72   "ctiveDir"
   65 63 74 6f 72 79 57 65   "ectoryWe"
   62 53 65 72 76 69 63 65   "bService"
   73 2f 57 69 6e 64 6f 77   "s/Window"
   73 2f 52 65 73 6f 75 72   "s/Resour"
   63 65                     "ce"       (9 x 8 + 2 = 74 octets)
03                     KnownEncodingRecord (type 0x03)
   08                    Encoding = 0x08 : binaire + dictionnaire in-band
09                     UpgradeRequestRecord (type 0x09)
   15                    UpgradeProtocolLength = 21
   61 70 70 6c 69 63 61 74   "applicat"
   69 6f 6e 2f 6e 65 67 6f   "ion/nego"
   74 69 61 74 65            "tiate"    (8 + 8 + 5 = 21 octets)
```

Point remarquable : `PreambleEndRecord` (`0x0C`) **ne figure pas** dans ce
bloc. Il est envoyé plus tard, après l'établissement du contexte de
sécurité, et voyage donc chiffré (voir la section suivante).

### Le Via : forme, endpoints, et ce que le serveur en fait

La forme canonique de l'URI Via est reconstituable à partir de la référence
de référence. les constantes du service ADWS Microsoft définit
`WcfNetEndpointPrefix = "net.tcp://"`, `WcfNetEndpointSuffix =
":9389/ActiveDirectoryWebServices"`, les préfixes d'authentification
`"Windows/"` et `"UserName/"`, et les noms d'endpoints. la configuration
d’hôte du service ADWS Microsoft montre comment ils sont assemblés.

| Chemin après `/ActiveDirectoryWebServices/` | Contrat WCF | Ligne |
|---|---|---|
| `Windows/Resource` | `IResource` | Service ADWS Microsoft |
| `Windows/ResourceFactory` | `IResourceFactory` | Service ADWS Microsoft |
| `Windows/Enumeration` | `IEnumeration` | Service ADWS Microsoft |
| `Windows/AccountManagement` | `IActiveDirectoryAccountManagement` | Service ADWS Microsoft |
| `Windows/TopologyManagement` | `IActiveDirectoryTopologyManagementV1` | Service ADWS Microsoft |
| `mex` | `IMetadataExchange` | Service ADWS Microsoft |

L'endpoint `mex` est le seul à ne pas porter de préfixe d'authentification :
il est ajouté hors de la boucle sur les descripteurs de liaison, avec
`MetadataExchangeBindings.CreateMexTcpBinding`.

Le préfixe `UserName/` n'est instancié que si un certificat serveur a pu
être provisionné ; il correspond à la liaison
`TransportWithMessageCredential`. Le serveur souverain n'implémente pas ce
chemin, seule l'authentification intégrée Windows/Kerberos est supportée.

Une trace d'un endpoint apparaît d'ailleurs dans notre propre code : le
handler `SubscribeHandler` renvoie
`net.tcp://localhost:9389/ActiveDirectoryWebServices/Windows/AccountManagement`
comme adresse de gestionnaire d'abonnement
(`classes/handlers/subscribe.py:16`).

**Ce que le serveur souverain fait du Via : rien.** Le record est lu, son
champ `Via` est peuplé, et `handle_preamble` se contente de journaliser «
ViaRecord received from client » (`classes/server/protocol.py:45-46`).
Aucune comparaison de nom d'hôte, aucune validation de chemin, aucun
routage. Une recherche sur `ViaRecord` dans les sources ne remonte que la
déclaration de la classe et le constructeur du client de debug.

Les conséquences sont à connaître :

- **Tous les chemins sont acceptés**, y compris un chemin inexistant ou
  vide. Le fault `EndpointNotFound` n'est jamais émis.
- **Le routage se fait exclusivement sur l'action SOAP**, pas sur l'endpoint
  : `HandlerRegistry.resolve(action)` (cf. `documentation/04-handlers.md`)
  décide seul du handler. Un `Enumerate` envoyé sur l'endpoint `Resource`
  fonctionnerait, là où un ADWS Microsoft le refuserait au niveau du contrat
  WCF.
- **Le nom d'hôte du Via n'est pas corrélé au SPN Kerberos.** C'est GSSAPI
  qui tranche l'identité du service ; le Via n'est pas une donnée de
  sécurité ici.

### L'UpgradeRequestRecord et le déclenchement de l'élévation

[MS-NMF] section 2.2.3.7 identifie deux chaînes d'*upgrade* connues :

| Chaîne | Longueur | Protocole |
|---|---|---|
| `application/negotiate` | 21 octets | SPNEGO, RFC 4178 |
| `application/ssl-tls` | 19 octets | TLS, RFC 5246 |

ADWS utilise **`application/negotiate`**. La chaîne est un simple sélecteur
: elle indique au receveur que, s'il accepte, le flux doit être remis à une
implémentation SPNEGO qui négociera un mécanisme (Kerberos en pratique, NTLM
en repli) et installera un contexte de sécurité. Rien dans NMF ne décrit ce
qui se passe ensuite : la règle ABNF `UpgradeRequest = UpgradeRequestRecord
Octets` délègue entièrement.

Le déclenchement est donc purement conventionnel : c'est la présence du
record `0x09` avant `PreambleEndRecord` qui bascule la connexion. Côté
serveur souverain, la mécanique est en trois temps
(`classes/server/protocol.py:84-98`) :

1. Vérifier que le code du record vaut bien `0x09`, sinon échouer.
2. Répondre un `UpgradeResponseRecord` nu (`0x0A`).
3. Remplacer le flux par un `GENSECStream` et lancer
  `negotiate_server`.

> **Le contenu de la chaîne n'est jamais examiné.** Le test de
> `classes/server/protocol.py:84` porte sur le code du record, pas sur
> `obj.UpgradeProtocol`. Un client demandant `application/ssl-tls` recevrait
> un `UpgradeResponseRecord` puis se verrait imposer une négociation SPNEGO,
> et échouerait de façon opaque. Le fault normatif `UpgradeInvalid` n'est
> pas émis. Ajouter un contrôle explicite sur la chaîne est un correctif
> d'une ligne qui améliorerait nettement le diagnostic.

### Où se situent réellement PreambleEnd et PreambleAck

C'est le point le plus souvent mal compris du préambule ADWS. La grammaire
place `PreambleEndRecord` après les *upgrades* ; comme l'*upgrade* a
installé un tunnel, ce record et son acquittement circulent **dans le
tunnel**.

```text
client                                                   serveur
  │  00 01 00 | 01 02 | 02 <len> <via> | 03 08              │   en clair
  │  09 15 "application/negotiate"                          │   en clair
  │ ──────────────────────────────────────────────────────► │
  │                                                    0A    │   en clair
  │ ◄────────────────────────────────────────────────────── │
  │  [ NNS 0x16 | tokens SPNEGO / AP-REQ ]                   │   opaque
  │ ──────────────────────────────────────────────────────► │
  │  [ NNS 0x16 ou 0x14 | tokens SPNEGO / AP-REP ]           │   opaque
  │ ◄────────────────────────────────────────────────────── │
  │  wrap( 0C )                        PreambleEndRecord     │   scellé
  │ ──────────────────────────────────────────────────────► │
  │  wrap( 0B )                        PreambleAckRecord     │   scellé
  │ ◄────────────────────────────────────────────────────── │
  │  wrap( 06 <size> <payload> )       message applicatif    │   scellé
  │ ◄────────────────────────────────────────────────────► │
```

Ancrages : côté client de debug, `PreambleEndRecord.to_bytes` est écrit sur
`self._inner` *après* que celui-ci a été remplacé par un `GSSAPIStream`
(`src/nettcp/stream/nmf.py:37-42`). Côté serveur, le `0x0C` n'est pas traité
en phase 1 mais dans la boucle de messages, sur le flux déchiffrant :
`classes/server/protocol.py:133-138` intercepte le code `0x0c`, répond
`PreambleAckRecord` puis boucle. La branche `0x0c` de `handle_preamble`
(`classes/server/protocol.py:55-60`) n'est atteinte que par un client qui
n'aurait pas demandé d'*upgrade*, cas qui échoue immédiatement après,
puisque `handle_security` exige un record `0x09`.

### Ce que le serveur valide, et ce qu'il ne valide pas

| Élément | Validé ? | Où |
|---|---|---|
| Code de record connu | oui, implicitement | `src/nettcp/nmf.py:262` (KeyError) |
| Ordre des records | non | `classes/server/protocol.py:37-63` |
| Présence du VersionRecord | non | idem |
| Valeur de version 1.0 | non | `classes/server/protocol.py:41-42` |
| Valeur du mode | partiellement | `ValueError` si hors 1-4 |
| Longueur / contenu du Via | non | `classes/server/protocol.py:45-46` |
| Valeur d'encodage | partiellement | `ValueError` si hors 3-8 |
| Chaîne d'*upgrade* | non | `classes/server/protocol.py:84` |
| Présence de l'*upgrade* | **oui** | `classes/server/protocol.py:84-86` |

La dernière ligne est la propriété de sécurité essentielle : **il n'existe
pas de chemin non authentifié**. Une connexion qui enverrait un préambule
complet suivi de `PreambleEndRecord` sans `UpgradeRequestRecord` verrait
`handle_preamble` émettre un `PreambleAckRecord`
(`classes/server/protocol.py:57-58`) puis renvoyer `True` ;
`handle_security` lirait alors le record suivant, constaterait qu'il ne vaut
pas `0x09` et renverrait `False` (`classes/server/protocol.py:84-86`).
`ConnectionHandler.handle` interrompt le traitement
(`classes/server/connection.py:50-52`) et la connexion est fermée.
L'acquittement de préambule est donc bien émis en clair dans ce cas
dégénéré, mais **aucun message applicatif ne peut suivre** : la phase 3
n'est jamais atteinte.

## Cadrage des messages applicatifs

### Anatomie du SizedEnvelopeRecord

En mode Duplex, chaque message applicatif est exactement un record `0x06` :

```text
┌──────┬────────────────┬──────────────────────────────────┐
│ 0x06 │ varint Size    │ Size octets de charge utile      │
└──────┴────────────────┴──────────────────────────────────┘
```

La charge utile est **opaque pour NMF**. Après désencapsulation GSSAPI,
c'est du XML binaire WCF précédé de la table de dictionnaire de session
[MS-NBFSE].

Dans le dépôt, la classe est déclarée en `src/nettcp/nmf.py:348-353` avec le
couple de champs habituel `('Size', varint)` puis `('Payload', pt(raw_bytes,
'Size'))`. Son `__repr__` est volontairement tronqué aux dix premiers octets
de la charge utile (`src/nettcp/nmf.py:355-361`) pour ne pas noyer les
journaux. La méthode `payload_to_xml` (`src/nettcp/nmf.py:363-373`) fait le
pont vers la couche WCF : elle construit le dictionnaire in-band, parse les
records NBFX et rend du XML texte.

Côté émission, le serveur construit le record dans la boucle de messages
(`classes/server/protocol.py:153-157`) à partir des octets rendus par le
dispatcher, puis l'écrit via `send_record`
(`classes/server/protocol.py:183-188`).

### Hexdump annoté d'un SizedEnvelopeRecord

L'exemple ci-dessous est le cadrage réel, octets produits par le code du
dépôt, d'une enveloppe SOAP minimale `<s:Envelope …><s:Body/></s:Envelope>`
encodée en WCF binaire. Treize octets au total, dont onze de charge utile.

```text
06                 SizedEnvelopeRecord (type 0x06)
   0b              Size = 11 (varint 1 octet)
   ── charge utile (11 octets) ─────────────────────────────
   00              [MS-NBFSE] taille de la table de dictionnaire
                   in-band = 0 : aucune chaîne de session
   56              [MS-NBFX] PrefixDictionaryElementS  -> "<s:"
   02              id de dictionnaire 2 = "Envelope"
   0b              [MS-NBFX] DictionaryXmlnsAttribute
   01              longueur du préfixe = 1
   73              octet du préfixe : ASCII 0x73 = 's'
   04              id de dictionnaire 4 =
                   "http://www.w3.org/2003/05/soap-envelope"
   56              PrefixDictionaryElementS  -> "<s:"
   0e              id de dictionnaire 14 = "Body"
   01              EndElementRecord -> "</s:Body>"
   01              EndElementRecord -> "</s:Envelope>"
```

Les identifiants 2, 4 et 14 sont ceux de la table statique
`src/wcf/dictionary.py`, vérifiés par exécution : `dictionary[2]` vaut
`Envelope`, `dictionary[4]` vaut `http://www.w3.org/2003/05/soap-envelope`
et `dictionary[14]` vaut `Body`. L'ensemble des treize octets a été régénéré
en faisant passer l'enveloppe par `XMLParser.parse`
(`src/wcf/xml2records.py:64`) puis `dump_records`
(`src/wcf/records/__init__.py:90`), puis en cadrant le résultat avec
`SizedEnvelopedMessageRecord`, il ne s'agit pas d'une reconstitution
manuelle.

| Octet | Classe WCF | Ancrage |
|---|---|---|
| `0x56` | `PrefixDictionaryElementSRecord` | `src/wcf/records/elements.py:321-334` |
| `0x0B` | `DictionaryXmlnsAttributeRecord` | `src/wcf/records/attributes.py:255-256` |
| `0x01` | `EndElementRecord` | `src/wcf/records/base.py:151-152` |

Les classes `PrefixDictionaryElement*Record` ne sont pas écrites à la main :
elles sont fabriquées par une boucle `for c in range(0x44, 0x5D + 1)` qui
associe à chaque octet la lettre `chr(c - 0x44 + ord('a'))`. Pour `s`, on
obtient bien `0x44 + 18 = 0x56`. Le détail de cet encodage relève du
chapitre [MS-NBFX] ; il est donné ici pour montrer où s'arrête la
responsabilité du cadrage.

### Le préfixe de dictionnaire, marqueur de l'encodage 0x08

L'octet `0x00` en tête de charge utile n'est pas décoratif : c'est le
`MultiByteInt31` de taille de la table de dictionnaire de session, imposé
par l'encodage `0x08`. Trois points d'ancrage dans le dépôt :

- `src/nettcp/protocol2xml.py:32-35` lit cette taille puis la table avant
  tout autre record ;
- `src/nettcp/nmf.py:369` appelle `build_dictionary` sur la charge utile
  reçue avant de parser les records ;
- `classes/handlers/dispatcher.py:49` préfixe la réponse encodée par
  `b"\x00"`, c'est-à-dire une table vide.

Ce projet **n'émet jamais de table de dictionnaire dynamique** : il
n'utilise que la table statique Microsoft (`src/wcf/dictionary.py`), qui
compte 487 entrées, toutes d'identifiant **pair**, de `0` (`mustUnderstand`)
à `972`, chiffres relevés par exécution. Le compteur `idx` de
`protocol2xml.py` part de `1` et progresse de 2, donc les chaînes de session
reçues d'un client occupent les identifiants **impairs** : les deux espaces
ne peuvent pas entrer en collision. Le serveur sait donc *lire* une table
dynamique envoyée par le client, mais jamais en produire. C'est une limite
déjà consignée dans `documentation/03-protocole.md:96`.

### Taille du record contre taille des trames de sécurité

Une confusion fréquente consiste à croire que la taille annoncée dans le
varint d'un `SizedEnvelopeRecord` correspond à ce qui passe sur le fil en
une fois. Il n'en est rien : le record NMF est *à l'intérieur* du tunnel, et
le tunnel a ses propres trames, plus petites.

| Grandeur | Valeur | Ancrage |
|---|---|---|
| Bloc de clair `_PLAINTEXT_CHUNK` | `0xF000` = 61 440 | `src/nettcp/stream/gssapi.py:17` |
| Découpe à l'émission, via `wrap` | par `_PLAINTEXT_CHUNK` | `src/nettcp/stream/gssapi.py:148-152` |
| Plafond d'une trame post-handshake | `0xFC30` = 64 560 | `src/nettcp/stream/negotiate.py:60-62` |
| En-tête de trame post-handshake | 4 octets, `uint32` LE | `src/nettcp/stream/negotiate.py:61` |
| En-tête de trame de handshake | 5 octets, type + 1 + 1 + `uint16` BE | `src/nettcp/stream/negotiate.py:24-30` |
| Marge disponible pour le jeton GSS | 3 120 octets (`0xFC30 − 0xF000`) | calcul |
| Surcoût réel annoncé du jeton | ~ 60 octets | commentaire `gssapi.py:12-16` |

Le commentaire de `src/nettcp/stream/gssapi.py:12-16` explique la contrainte
: le jeton Kerberos AES CFX ajoute en-tête, *confounder*, en-tête dupliqué
et HMAC, soit environ soixante octets ; si le bloc de clair collait au
plafond de trame, un seul jeton chevaucherait sur deux trames et le lecteur,
qui suppose « une trame = un jeton », échouerait au désencapsulage. Le choix
de `0xF000` laisse une marge de 3 120 octets, très supérieure au surcoût
constaté, un arrondi confortable plutôt qu'une valeur ajustée au plus juste.

Attention à ne pas confondre les deux classes de flux du dépôt :
`GSSAPIStream` (client de debug) chiffre avec `encrypt`/`decrypt`
(`src/nettcp/stream/gssapi.py:55` et `:65`), tandis que `GENSECStream`, le
seul flux utilisé côté serveur, passe par `wrap`/`unwrap` de `samba.gensec`
(`src/nettcp/stream/gssapi.py:150` et `:160`). Les deux partagent la même
constante `_PLAINTEXT_CHUNK` et le même `NegotiateStream` sous-jacent.

Conséquence pratique : une réponse `Get-ADUser` de 150 kio produit **un**
`SizedEnvelopeRecord` dont le varint vaut 153 600 environ, découpé en trois
blocs de clair, donc trois trames NNS. Réciproquement, à la lecture,
`GENSECStream.read(count)` accumule dans `_readcache` autant de trames que
nécessaire pour satisfaire la demande
(`src/nettcp/stream/gssapi.py:162-170`) : le lecteur de records ne voit
jamais cette découpe.

### Quotas de taille : Microsoft contre ce projet

Les réglages par défaut du service Windows sont les suivants :

| Paramètre | Valeur Microsoft | Équivalent ici |
|---|---|---|
| `maxReceivedMessageSize` | 1 048 576 (1 Mio) | aucun |
| `receiveTimeout` | `00:10:00` | 10 s puis neutralisé |
| `maxArrayLength` | 16 384 | aucun |
| `maxStringContentLength` | 32 768 | aucun |
| `maxDepth` | 10 | aucun |
| `MaxConcurrentSessions` | 500 | aucun (voir ci-dessous) |
| `MaxConcurrentCalls` | 32 | aucun |
| `OperationTimeout` | `00:02:00` | aucun |
| `MaxPullTimeout` | `00:02:00` | aucun |
| `MaxEnumContextExpiration` | `00:30:00` | cf. chapitre énumération |
| `MaxEnumCtxsPerSession` | 5 | aucun |
| `MaxEnumCtxsTotal` | 100 | aucun |
| `MaxPoolConnections` | 10 | sans objet (pas de pool LDAP) |

Le serveur souverain **n'applique aucun quota de taille de message**. Un
`SizedEnvelopeRecord` annonçant un varint de plusieurs gigaoctets amènerait
`raw_bytes_stream` (`src/nettcp/nmf.py:123-125`) à demander autant d'octets
à `GENSECStream.read(count)`, qui bouclerait sur les trames jusqu'à
épuisement mémoire du processus fils. C'est, avec le varint non borné, le
deuxième point de durcissement identifié pour la phase 5.

Le parallélisme mérite la même prudence. La valeur `max_connections = 128`
de `classes/server/config.py:17` est déclarée mais **jamais lue** : le
constructeur de `socketserver.ForkingTCPServer`
(`classes/server/server.py:25-29`) ne reçoit que l'adresse, la classe de
handler et `bind_and_activate=False`. Le seul plafond effectif est donc
`ForkingMixIn.max_children`, dont la valeur par défaut dans la bibliothèque
standard Python est 40 et que ce projet ne surcharge pas. Il n'existe pas
non plus d'équivalent au `MaxConcurrentCalls` de Microsoft, puisqu'un
processus fils ne traite jamais qu'un message à la fois.

### Le cas UnsizedEnvelopeRecord

Le mode Singleton-Unsized emploie le record `0x05`, dont la charge utile est
une suite de fragments `(varint taille, octets)` terminée par un octet
`0x00`, la règle ABNF est `UnsizedEnvelopeRecord = UnsizedEnvelopeRecordType
1*(EncodedSize Octets) Terminator` avec `Terminator = %x00`. C'est un
cadrage de type *chunked*, utile quand l'émetteur ne connaît pas la taille
totale à l'avance.

ADWS n'en fait jamais usage, et l'état du code le confirme :

- la classe `UnsizedEnvelopedMessageRecord` existe
  (`src/nettcp/nmf.py:387-391`) avec un champ `DataChunks` ;
- l'encodeur est explicitement neutralisé : `data_chunks.encode = None`
  (`src/nettcp/nmf.py:140`), donc toute tentative de `to_bytes` échouerait ;
- le décodeur en flux `data_chunks_stream` (`src/nettcp/nmf.py:142-149`)
  référence une variable `data` qui n'existe pas dans sa portée, le
  paramètre s'appelle `stream`. Un `NameError` se produirait à la première
  invocation.

Ce code est donc mort et cassé ; il n'est jamais atteint parce que le mode
Duplex n'utilise que le record `0x06`. Le signaler évite qu'un lecteur le
prenne pour une fonctionnalité disponible.

## Terminaison de connexion et gestion des erreurs de cadrage

### La fin normale : EndRecord

La grammaire termine `DuplexStream-a` par un `EndRecord` et autorise
`DuplexStream-b` à se clore par un `FaultRecord` ou un `EndRecord`. Le
record `0x07` est nu : un octet, aucune charge utile, aucun acquittement
attendu.

Comportement du serveur souverain :

| Événement | Réaction | Ancrage |
|---|---|---|
| `EndRecord` reçu | journalise, sort de la boucle, ferme | `classes/server/protocol.py:170-173` |
| `socket.timeout` en lecture | émet un `EndRecord`, puis ferme | `classes/server/protocol.py:115-125` |
| `ConnectionResetError` | émet un `EndRecord`, puis ferme | même bloc `except`, ligne 115 |
| `BrokenPipeError` | émet un `EndRecord` (échec avalé) | même bloc `except`, ligne 115 |
| `EOFError` / `OSError` | ferme sans rien émettre | `classes/server/protocol.py:126-129` |
| Code de record inattendu | journalise un avertissement, ferme | `classes/server/protocol.py:175-177` |
| Exception quelconque | journalise la trace, ferme | `classes/server/protocol.py:179-181` |

Le cas `BrokenPipeError` mérite d'être lu littéralement : le code tente
d'écrire un `EndRecord` sur un tube déjà rompu, et l'échec de cette écriture
est absorbé par un `except Exception: pass`
(`classes/server/protocol.py:123-124`). La tentative est donc
systématiquement vaine, mais sans conséquence.

Le serveur **n'accuse pas réception** d'un `EndRecord` client : il ne
renvoie pas de `EndRecord` en écho, il se contente de sortir.

### Le timeout, en théorie et dans le code

`ConnectionHandler.handle` pose `self.request.settimeout(10)`
(`classes/server/connection.py:39`), et la boucle de messages tente de
réduire ce délai à deux secondes après la première réponse
(`classes/server/protocol.py:163-166`). La lecture attentive du code montre
que ni l'un ni l'autre ne prend effet durablement :

- `SocketStream.read(count)` appelle `self._socket.setblocking(1)`
  (`src/nettcp/stream/socket.py:32`) et `SocketStream.write` fait de même
  (`src/nettcp/stream/socket.py:51`). Or, en Python, `setblocking(True)` est
  strictement équivalent à `settimeout(None)` : **le délai de 10 secondes
  est effacé dès la première lecture ou écriture**.
- La réduction à 2 secondes cible `self.stream._socket`, mais `self.stream`
  est à ce stade un `GENSECStream`, qui n'expose pas d'attribut `_socket`,
  l'`AttributeError` est avalée par le `except Exception: pass` de
  `classes/server/protocol.py:165-166`.

Conséquence : la branche `except socket_timeout` de
`classes/server/protocol.py:115` n'est, en lecture du code, jamais
empruntée, et le processus fils reste bloqué en `recv` jusqu'à ce que le
client ferme. Si le client émet un RST, `ConnectionResetError` est levée et
le serveur émet un `EndRecord` de courtoisie ; si le client ferme
proprement, la chaîne d'appels est la suivante :

- `GENSECStream.read(1)` a son `_readcache` vide et appelle
  `NegotiateStream.read` (`src/nettcp/stream/gssapi.py:162-166`) ;
- le handshake étant terminé, celui-ci lit quatre octets d'en-tête
  (`src/nettcp/stream/negotiate.py:79`) ;
- `SocketStream.read(4)` sort de sa boucle sur `if not d: break`
  (`src/nettcp/stream/socket.py:36-37`) et rend `b''` ;
- `struct.unpack('<I', b'')` lève une `struct.error`.

`struct.error` n'est ni `OSError` ni `EOFError` : elle échappe donc au
`except (EOFError, OSError)` de `classes/server/protocol.py:126` et tombe
dans le `except Exception` général de la ligne 179, produisant une trace
d'erreur complète pour ce qui est une déconnexion normale. Le garde-fou
prévu pour ce cas (`raise IOError('connection closed mid-message')`,
`src/nettcp/stream/gssapi.py:164-165`) n'est jamais atteint, puisque
`NegotiateStream` lève avant de pouvoir rendre une chaîne vide ; il aurait
d'ailleurs été correctement classé, `IOError` étant un alias d'`OSError`.
C'est cosmétique, la connexion est de toute façon terminée, mais cela pollue
le journal et complique le diagnostic décrit dans
`documentation/06-depannage.md` section 2.

### Erreurs de cadrage : fermeture sèche, jamais de fault

C'est la règle à retenir, et elle est sans exception dans l'implémentation
actuelle :

> **Toute erreur de cadrage entraîne la fermeture de la connexion sans
> aucune réponse. Le serveur souverain n'émet jamais de `FaultRecord`
> (`0x08`).**

Le mécanisme est uniforme. Chacune des trois phases de `ProtocolHandler` est
enveloppée dans un `try` / `except Exception` qui journalise et renvoie
`False` (`classes/server/protocol.py:65-67`, `:103-105`, `:179-181`).
`ConnectionHandler.handle` teste ces retours et sort du bloc `try` sans
écrire sur le socket (`classes/server/connection.py:45-60`) ; `socketserver`
ferme alors la socket. Les seules exceptions attrapées nommément au niveau
connexion sont `BrokenPipeError`, `ConnectionResetError` et `EOFError`
(`classes/server/connection.py:62-63`), traitées comme une déconnexion
normale ; tout le reste tombe dans un `except Exception` qui journalise une
trace (`classes/server/connection.py:64-65`).

Les déclencheurs concrets, par ordre de probabilité :

| Cause | Exception levée | Phase |
|---|---|---|
| Octet de type inconnu (`0x04`, `0x0D`+) | `KeyError` | 1 ou 3 |
| Encodage hors 3-8 | `ValueError` | 1 |
| Mode hors 1-4 | `ValueError` | 1 |
| Flux tronqué au milieu d'un record | `AssertionError` | 1 ou 3 |
| Absence d'`UpgradeRequestRecord` | retour `False` explicite | 2 |
| Échec Kerberos (SPN, horloge) | `samba.NTSTATUSError` | 2 |

Le cas Kerberos est le seul dont une trace réelle soit conservée dans le
dépôt : `documentation/06-depannage.md:33` montre `samba.NTSTATUSError:
(3221225572, 'The specified account does not exist.')`, soit le NTSTATUS
`0xC0000064` (`STATUS_NO_SUCH_USER`), SPN absent d'AD. Levée depuis
`negotiate_server`, elle est captée par le `except Exception` de la phase 2
et se solde par la même fermeture sèche.

L'`AssertionError` mérite une note : `Record.parse_stream` vérifie `assert
len(data) == s, repr(data)` (`src/nettcp/nmf.py:259`). Si le pair ferme au
milieu d'un record, `read(1)` rend `b''` et l'assertion échoue ; son message
porte la représentation des octets lus, utile en journal `DEBUG`. Une
exécution avec `python3 -O` supprimerait l'assertion et laisserait passer un
`struct.error` moins parlant : le service doit être lancé sans optimisation,
ce que fait `python3 -m src.main`.

Côté Windows, cette fermeture sèche se présente sous la forme `Le site
distant a fermé le flux de transport` (`documentation/06-depannage.md:78`).
Un `FaultRecord` correctement formé donnerait au client un message bien plus
précis ; c'est l'argument principal pour implémenter l'émission de faults de
cadrage.

### Ne pas confondre fault de cadrage et fault SOAP

Deux mécanismes d'erreur totalement disjoints coexistent :

| Critère | `FaultRecord` NMF | SOAP Fault |
|---|---|---|
| Couche | cadrage, octet `0x08` | applicatif, dans un `0x06` |
| Contenu | un URI UTF-8 | une enveloppe SOAP complète |
| Corrélation | aucune | `<a:RelatesTo>` obligatoire |
| Émis par ce projet | **non** | oui |
| Producteur | — | `classes/handlers/dispatcher.py:31-35` |

Le dispatcher attrape `ADWSException` et toute exception résiduelle et les
convertit en enveloppe SOAP par `_fault`
(`classes/handlers/dispatcher.py:52-55`). Ce fault applicatif est ensuite
encodé et **cadré normalement dans un `SizedEnvelopeRecord`** : du point de
vue NMF, c'est un message comme un autre. L'invariant « tout fault DOIT
porter `<a:RelatesTo>` » du `CLAUDE.md` section 5 concerne exclusivement ce
second mécanisme.

> **Angle mort à connaître.** `_fault` s'écrit `relates_to =
> context.message_id if context else ""`
> (`classes/handlers/dispatcher.py:54`). Le `context` n'est construit qu'à
> la ligne 25, après `record.payload_to_xml`. Toute défaillance survenant
> *avant* (décodage du dictionnaire in-band, parsing NBFX, XML malformé)
> produit donc un fault dont le `<a:RelatesTo>` est **vide**. C'est
> précisément le cas que l'invariant du projet cherche à interdire :
> PowerShell ignore la réponse et la cmdlet bloque jusqu'au timeout. Les
> erreurs de la couche de cadrage proprement dite n'atteignent jamais le
> dispatcher, elles ferment la connexion, mais les erreurs de la couche
> NBFX, elles, empruntent ce chemin.

## Implémentation dans ce projet

### Cartographie des fichiers

| Fichier | Rôle dans le cadrage |
|---|---|
| `src/nettcp/nmf.py` | Primitives varint/UTF-8, classes de records, registre |
| `src/nettcp/stream/socket.py` | Adaptateur socket brut, lecture par compte |
| `src/nettcp/stream/negotiate.py` | Cadrage [MS-NNS] du handshake et des jetons |
| `src/nettcp/stream/gssapi.py` | `GENSECStream` : wrap/unwrap via `samba.gensec` |
| `src/nettcp/stream/nmf.py` | Émetteur de préambule côté client (debug) |
| `src/nettcp/protocol2xml.py` | Rejeu de traces, dictionnaire in-band |
| `classes/server/protocol.py` | Machine d'état des trois phases côté serveur |
| `classes/server/connection.py` | Cycle de vie d'une connexion, timeout initial |
| `tools/work/proxy.py` | Proxy de capture/rejeu, hors runtime |

### Le lecteur générique de records

L'architecture de `src/nettcp/nmf.py` repose sur une description déclarative
: chaque classe de record porte un `code` et une liste `fields` de couples
`(nom, décodeur)`. Trois méthodes exploitent cette description :

- `Record.parse(data)` (`src/nettcp/nmf.py:232-253`) : décodage depuis un
  buffer complet, renvoie le nombre d'octets consommés et l'objet. Utilisé
  par l'outillage de rejeu de traces.
- `Record.parse_stream(stream)` (`src/nettcp/nmf.py:255-273`) : décodage
  incrémental depuis un flux. **C'est le seul chemin utilisé par le
  serveur** (`classes/server/protocol.py:38`, `:80`, `:114`).
- `Record.to_bytes` (`src/nettcp/nmf.py:275-287`) : encodage, avec
  journalisation du champ fautif en cas d'échec.

Le décodeur d'un champ est soit une chaîne de format `struct` (cas de
`MajorVersion`, `'B'`), soit un appelable exposant `stream` et `encode`.
Ajouter un record se réduit donc à déclarer la classe : `register_types`
l'enregistre. L'appel a lieu deux fois, au démarrage, avant tout `fork`
(`src/main.py:15`), et à chaque instanciation de `NMFStream`
(`src/nettcp/stream/nmf.py:17`), et l'opération est idempotente.

Point de détail : `register_types` enregistre aussi la classe de base
`Record` sous la clé `None` (elle est trivialement sous-classe d'elle-même).
Cette entrée est inatteignable, la clé de recherche étant toujours un entier
issu d'un octet. Les classes `Enum`, `KnownEncoding`, `Mode` et `DataChunk`
du même module ne descendent pas de `Record` et ne sont pas enregistrées.

Le cadrage [MS-NNS] réutilise la même machinerie sans polluer le registre
NMF : `class Handshake(Record)` redéfinit `_records = {}`
(`src/nettcp/stream/negotiate.py:20-21`), si bien que
`Handshake.register(...)` peuple un dictionnaire distinct, l'enregistrement
y est d'ailleurs explicite et non introspectif
(`src/nettcp/stream/negotiate.py:40-42`). Les types de messages de handshake
y valent `0x14` (done), `0x15` (error) et `0x16` (in progress)
(`src/nettcp/stream/negotiate.py:14-17`), ce sont des valeurs [MS-NNS], à ne
jamais confondre avec des codes de record NMF.

| Champ du handshake NNS | Format | Ancrage |
|---|---|---|
| type de message | `uint8` | `negotiate.py:25` |
| major | `uint8` = 1 | `negotiate.py:27` |
| minor | `uint8` = 0 | `negotiate.py:28` |
| taille de charge utile | `uint16` **big-endian** (`>H`) | `negotiate.py:29` |

Le contraste est instructif : l'en-tête de handshake code sa taille en
gros-boutiste sur deux octets, alors que les trames post-handshake la codent
en petit-boutiste sur quatre (`negotiate.py:61` et `:79`), et que NMF, lui,
utilise son varint. Trois conventions de longueur cohabitent donc sur la
même connexion.

> **Défaut latent dans la branche d'erreur.** `NegotiateStream.read`
> initialise `error = None`, ne le renseigne que si `payload_size > 0`
> (`src/nettcp/stream/negotiate.py:69-71`), puis formate systématiquement
> `"Negotiate Error: {:08x}".format(error)` (ligne 72). Un `HandshakeError`
> sans charge utile produirait donc un `TypeError` de formatage à la place
> du diagnostic attendu. Ce chemin n'a jamais été déclenché dans ce dépôt ;
> le constat est statique.

### Interaction avec le modèle `ForkingTCPServer`

L'invariant du projet (un processus par connexion, parce que `python3-samba`
n'est pas *thread-safe*) a des conséquences directes sur la couche de
cadrage.

`src/nettcp/protocol2xml.py` maintient trois états globaux mutables :
`old_dictionary` (ligne 25), `dictionary_cache` (ligne 26) et le compteur
`idx` (ligne 28), ce dernier incrémenté de 2 par entrée de dictionnaire de
session (ligne 41), les identifiants de session sont impairs, la table
statique occupant les pairs. Le module comporte même une assertion `assert
idx not in dictionary_cache[key]` (ligne 39) qui deviendrait fausse si
plusieurs connexions partageaient l'état. Le modèle *forking* garantit
qu'elles ne le partagent pas : chaque processus fils hérite d'une copie au
moment du `fork` et repart de zéro. La même remarque vaut pour le registre
`Record._records`, peuplé une fois avant le `fork` et jamais modifié
ensuite.

Cette dépendance implicite au *forking* est un piège : rendre le serveur
multithread sans réécrire `protocol2xml.py` casserait les dictionnaires de
session.

### Statut normatif du code de cadrage

`src/nettcp/` et `src/wcf/` sont du **code tiers vendoré**, explicitement
exclu des normes internes :

- `pyproject.toml:11` : `extend-exclude = ["tools", "src/nettcp",
  "src/wcf"]` pour ruff ;
- `pyproject.toml:31` : `exclude = '^src/(nettcp|wcf)/'` pour mypy ;
- `pyproject.toml:34-36` : les modules `src.nettcp.*` et `src.wcf.*` sont
  déclarés `follow_imports = "skip"`, ce qui les traite comme une frontière
  `Any` pour que les appels depuis `classes/` passent en mode strict ;
- `.pre-commit-config.yaml` : le filtre `files:
  ^(src|classes)/(?!nettcp/|wcf/)` est appliqué aux cinq hooks Python :
  ruff, flake8, `tools/norms` et mypy sont bloquants, pylint est en stage
  `manual`.

C'est pourquoi `src/nettcp/nmf.py` comporte dix-sept classes et quatorze
fonctions au niveau module, en contradiction frontale avec la règle « une
classe et cinq fonctions maximum par fichier » de `CLAUDE.md` section 6.1.
Le code *maison* qui pilote ce cadrage, lui, est soumis aux normes :
`ProtocolHandler` (`classes/server/protocol.py`) est une classe unique
totalisant cinq fonctions, `__init__` plus les quatre méthodes publiques
`handle_preamble`, `handle_security`, `handle_messages` et `send_record`, ce
qui est exactement la limite.

Toute évolution de la couche de cadrage doit donc arbitrer : corriger sur
place dans le code vendoré (rapide, mais non vérifié par les linters) ou
remonter la logique dans `classes/server/` (conforme, mais plus invasif).
Pour les durcissements listés ci-dessous, la seconde voie est préférable :
un contrôle de taille maximale et un contrôle de longueur de varint ont leur
place dans `ProtocolHandler`, pas dans la bibliothèque d'origine.

### Synthèse des écarts connus

| Point | Spec [MS-NMF] | Ce projet |
|---|---|---|
| Modes supportés | 4 | Duplex de fait ; les autres ne sont pas rejetés |
| `ExtensibleEncodingRecord` `0x04` | prévu | absent, `KeyError` |
| Encodages SOAP 1.1 `0x00`-`0x02` | prévus | rejetés par `ValueError` |
| Validation de l'encodage `0x08` | attendue | aucune |
| Validation du Via | attendue | aucune, tous chemins acceptés |
| Validation de la chaîne d'*upgrade* | attendue | aucune |
| Émission de `FaultRecord` | *MAY* | jamais |
| Borne du varint (5 octets) | normative | absente |
| Quota de taille de message | *MAY* (1 Mio chez Microsoft) | absent |
| `UnsizedEnvelopeRecord` | prévu | classe présente, code cassé |
| Élévation TLS `application/ssl-tls` | prévue | non implémentée |
| Endpoint `UserName/` | prévu | non implémenté |

### Erratum sur la documentation existante

Le tableau « Phase 1, Préambule NMF » de
`documentation/03-protocole.md:34-40` comporte des valeurs d'octet erronées,
probablement issues d'une transcription manuelle : les codes de record y
sont décalés d'un rang à partir du `ModeRecord`. La correction, vérifiée
contre `src/nettcp/nmf.py:298-325` et contre la table normative :

| Record | Valeur publiée | Valeur exacte |
|---|---|---|
| `VersionRecord` | `0x00 0x01 0x00 0x01` | `0x00 0x01 0x00` |
| `ModeRecord` | `0x02 0x02` | `0x01 0x02` |
| `ViaRecord` | `0x03 …` | `0x02 <varint> <utf8>` |
| `KnownEncodingRecord` | `0x04 0x03` | `0x03 0x08` |

Le libellé « encoding=BINARY_WITH_DICT (3) » du même tableau est doublement
inexact : le membre déclaré en `src/nettcp/nmf.py:184` s'appelle
`BINARY_DICT` et vaut **8**, la valeur 3 désignant SOAP 1.2 en UTF-8
textuel.

Trois autres imprécisions du même document relèvent du présent chapitre :

| Emplacement | Texte publié | Correction |
|---|---|---|
| `03-protocole.md:58` | `PreambleEndRecord (0x0c)` serveur → client | client → serveur ; c'est `PreambleAckRecord` (`0x0b`) qui revient |
| `03-protocole.md:48` | tokens « préfixés d'un `int32` little-endian » | vrai après le handshake seulement ; pendant, en-tête NNS de 5 octets à taille `uint16` gros-boutiste |
| `03-protocole.md:27` | « MS-NBFS :.NET Binary Format: SOAP Extension » | [MS-NBFS] = *SOAP Data Structure* ; l'*Extension* est [MS-NBFSE] |

Ces corrections doivent être portées dans `documentation/03-protocole.md`
conformément à la règle du dépôt qui veut que toute correction de
comportement documenté mette à jour la documentation dans le même commit.

### Feuille de route de durcissement (phase 5)

Par ordre décroissant de rapport bénéfice/coût :

1. Borner le varint à cinq octets dans `varint_stream`, à l'image de
  `MultiByteInt31.parse`. Trois lignes, supprime un vecteur de déni de
  service.
2. Refuser un `SizedEnvelopeRecord` dont la taille annoncée dépasse un
  plafond configurable, aligné par défaut sur le 1 Mio de Microsoft. À
  placer dans `ProtocolHandler.handle_messages`, avant l'appel au
  dispatcher.
3. Émettre un `FaultRecord` au lieu de fermer sèchement, au minimum
  pour `UnsupportedMode`, `ContentTypeInvalid`, `UpgradeInvalid` et
  `MaxMessageSizeExceededFault`. Gain immédiat sur la qualité des messages
  d'erreur côté PowerShell.
4. Valider explicitement mode, encodage et chaîne d'*upgrade*, plutôt
  que de s'en remettre aux exceptions de l'énumération.
5. Réparer la gestion des délais : remplacer les `setblocking(1)` de
  `src/nettcp/stream/socket.py` par un `settimeout` explicite, et cibler la
  socket réelle plutôt que `self.stream._socket` dans
  `classes/server/protocol.py:164`.
6. Traiter la fermeture propre du client (`recv` rendant `b''`) comme
  un événement normal, pour cesser de journaliser une trace d'erreur à
  chaque fin de session.

Aucun de ces six points ne modifie le comportement observable d'un client
conforme : ils ne touchent que les chemins d'erreur et les limites de
ressources, ce qui est précisément le périmètre de la phase 5.

# Partie IV. Authentification GSSAPI et Kerberos

## Modèle de sécurité : ce que le canal doit garantir

### Le contrat imposé par le client

Le client ADWS n'est pas négociable. C'est le module PowerShell
`ActiveDirectory` (ou ADAC, ou tout consommateur de
`Microsoft.ActiveDirectory.Management`) qui ouvre une liaison WCF
`NetTcpBinding` vers `net.tcp://<dc>:9389/…`. La configuration exacte de
cette liaison est lisible dans la référence C# de référence du service
Microsoft : `CreateAdwsTransportBinding` positionne trois propriétés qui
déterminent tout le reste de ce chapitre.

| Propriété WCF | Valeur | Conséquence protocolaire |
|---|---|---|
| `Security.Mode` | `Transport` | La sécurité est au niveau flux, pas WS-Security |
| `Security.Transport.ProtectionLevel` | `EncryptAndSign` | Chaque message est chiffré **et** signé |
| `Security.Transport.ClientCredentialType` | `Windows` | SSPI / SPNEGO, donc Kerberos ou NTLM |

Ces trois valeurs caractérisent la liaison employée par les endpoints
`Windows/`. Une seconde liaison existe côté Microsoft pour les endpoints
`UserName/`, en `TransportWithMessageCredential` : elle porte les
identifiants dans le message et suppose qu'un certificat serveur ait été
provisionné. Les deux liaisons coexistent, et le préfixe d'adresse détermine
laquelle s'applique. Le préfixe d'endpoint concerné ici est `Windows/`
(`WcfWindowsEndpointPrefix = "Windows/"`), c'est-à-dire la branche
`TcpClientCredentialType.Windows`, la seule que le serveur souverain
implémente. Ce préfixe apparaît d'ailleurs dans le code du projet, dans
l'adresse de gestionnaire d'abonnement rendue par
`classes/handlers/subscribe.py:16` :
`net.tcp://localhost:9389/ActiveDirectoryWebServices/Windows/AccountManagement`.

> Le second endpoint Microsoft, `UserName/…`, n'est pas implémenté par ce
> projet. Il n'existe donc **aucun** chemin d'authentification par mot de
> passe en clair vers ce serveur : c'est un choix de conception, pas un
> manque.

Nuance sur le mot « endpoint » : le serveur Python **ne lit ni ne valide
jamais** l'URL cible. Le `ViaRecord` qui la transporte est journalisé
(`classes/server/protocol.py:45-46`) puis jeté ; aucun routage par chemin
n'existe. Le choix `Windows/` contre `UserName/` est donc entièrement une
décision du client.

### Les quatre propriétés à garantir

Le canal doit fournir, avant qu'un seul octet de SOAP ne circule :

- **Authentification du client** : le serveur doit savoir *qui* parle, avec
  une preuve cryptographique émise par le KDC du domaine, pas un mot de
  passe.
- **Authentification mutuelle** : le client doit vérifier qu'il parle bien
  au DC et non à un intercepteur. C'est ce que demande `GSS_C_MUTUAL_FLAG`,
  et c'est pour cela que le service doit posséder la clé du SPN demandé.
- **Intégrité** : toute altération d'un message doit être détectée
  (`GSS_C_INTEG_FLAG`, checksum HMAC du token Wrap RFC 4121).
- **Confidentialité** : les attributs d'annuaire (`unicodePwd` en écriture,
  `nTSecurityDescriptor`, appartenances de groupe) ne doivent pas transiter
  en clair (`GSS_C_CONF_FLAG`, correspondant à `EncryptAndSign`).

### Ce que ce serveur garantit réellement

| Propriété | Assurée ? | Par quoi |
|---|---|---|
| Authentification client | Oui | `samba.gensec` + SPNEGO, `gssapi.py:118` |
| Authentification mutuelle | Oui | AP-REP émis par gensec si le client l'exige |
| Intégrité | Oui | `wrap`/`unwrap` gensec, `gssapi.py:150` et `:160` |
| Confidentialité | Si le client la demande | Aucun `want_feature` dans le dépôt |
| Autorisation par identité | **Non** | `connection.py:56` force `system_session` |
| Anti-rejeu explicite | Délégué | Aucune vérification de `SND_SEQ` dans le dépôt |
| Résistance à l'épuisement | **Non** | Timeout annulé par `socket.py:32` |

Le dernier point est le plus important et le plus souvent mal compris : le
serveur **authentifie** le client de façon irréprochable, puis **n'utilise
pas** l'identité obtenue pour exécuter les opérations LDB. La section «
Identité, délégation et contrôle d'accès » détaille ce point, mesures à
l'appui.

## Anatomie de l'upgrade de sécurité NMF

### Où se situe l'upgrade dans le préambule

[MS-NMF] définit un préambule composé de records typés (un octet de code,
puis des champs). Le client envoie sa séquence sans attendre de réponse. Les
codes implémentés dans `src/nettcp/nmf.py` sont les suivants.

| Code | Record | Champs | Ligne |
|---|---|---|---|
| `0x00` | `VersionRecord` | MajorVersion, MinorVersion | `nmf.py:298` |
| `0x01` | `ModeRecord` | Mode (enum) | `nmf.py:306` |
| `0x02` | `ViaRecord` | ViaLength (varint), Via (UTF-8) | `nmf.py:313` |
| `0x03` | `KnownEncodingRecord` | Encoding (enum) | `nmf.py:321` |
| `0x09` | `UpgradeRequestRecord` | Length (varint), Protocol (UTF-8) | `nmf.py:328` |

Le client de référence vendoré (`src/nettcp/stream/nmf.py:20-33`) montre la
séquence qu'émet un client conforme : `VersionRecord(1,0)` (`:21`),
`ModeRecord(2)` (DUPLEX, `nmf.py:189`) en `:22`, `ViaRecord(url)` en `:23`,
`KnownEncodingRecord(8)` (`BINARY_DICT`, `nmf.py:184`) en `:24`, puis :

```python
UpgradeRequestRecord(UpgradeProtocolLength=21,
                     UpgradeProtocol='application/negotiate')
```

La chaîne `application/negotiate` fait exactement 21 octets, d'où le
`UpgradeProtocolLength=21` littéral de `src/nettcp/stream/nmf.py:30`. Ce
client est celui du projet amont, pas le client Windows : il documente une
séquence valide, il ne prouve pas l'ordre exact retenu par WCF.

La séquence réellement émise sur le fil, octet par octet, se déduit de
`Record.to_bytes` (`nmf.py:275-287`) : un octet de code, puis les champs
déclarés dans `fields`.

| Record | Octets émis | Ancrage |
|---|---|---|
| `VersionRecord(1,0)` | `00 01 00` | `nmf.py:298-303` |
| `ModeRecord(DUPLEX)` | `01 02` | `nmf.py:306-310`, `:189` |
| `ViaRecord(url)` | `02` + varint(len) + UTF-8 | `nmf.py:313-318` |
| `KnownEncodingRecord(8)` | `03 08` | `nmf.py:321-325`, `:184` |
| `UpgradeRequestRecord` | `09 15` + `application/negotiate` | `nmf.py:328-333` |

> **Écart avec la documentation du dépôt.** Le tableau de
> `documentation/03-protocole.md` (lignes 34 à 40) est décalé d'un octet à
> partir de sa deuxième ligne : il annonce `0x00 0x01 0x00 0x01` pour
> `VersionRecord` (soit les trois octets de la version **plus** le code du
> record suivant), `0x02 0x02` pour `ModeRecord` (soit la valeur `DUPLEX`
> **plus** le code de `ViaRecord`), et `0x04 0x03` avec « BINARY_WITH_DICT
> (3) » pour `KnownEncodingRecord`. Le code fait autorité : le code de
> record est `0x03` (`nmf.py:322`) et la valeur d'encodage est `8`
> (`BINARY_DICT`, `nmf.py:184`, confirmée par `stream/nmf.py:24`). La paire
> correcte est donc `03 08`.

### La bascule côté serveur, ligne à ligne

`classes/server/protocol.py` traite l'`UpgradeRequestRecord` de façon
particulière : il **termine le préambule**. Le record est mémorisé plutôt
que consommé.

1. `protocol.py:49-54` : sur `code == 0x09`, l'objet est stocké dans
  `self.pending_upgrade` et `handle_preamble` retourne `True`. Aucune
  réponse n'est émise à cet instant.
2. `protocol.py:75-77` : `handle_security` récupère `pending_upgrade`
  au lieu de relire le socket.
3. `protocol.py:84-86` : si le code n'est pas `0x09`, la connexion est
  abandonnée.
4. `protocol.py:92` : `send_record(nmf.UpgradeResponseRecord)` écrit
  **un seul octet**, `0x0A` (`nmf.py:337`), directement sur le socket brut.
5. `protocol.py:96` : `self.stream = GENSECStream(self.stream)` : le
  `SocketStream` est enveloppé. À partir de cette affectation, tout `read` /
  `write` du reste du serveur passe par la pile de sécurité.
6. `protocol.py:97` : `self.stream.negotiate_server` exécute le
  handshake complet, de façon synchrone et bloquante.

> **Faille de durcissement.** Le contenu du champ `UpgradeProtocol` n'est
> **jamais comparé** à `application/negotiate` : `protocol.py:84` ne teste
> que le code de record. Un client demandant `application/ssl-tls` recevrait
> le même `UpgradeResponseRecord` puis échouerait au handshake. Point à
> traiter en phase 5 (durcissement).

### Le cadrage réellement implémenté : MS-NNS, et pas autre chose

On lit fréquemment que « ce serveur ne fait pas de NegotiateStream, juste
des tokens GSSAPI préfixés d'une longueur ». **C'est faux.**
`src/nettcp/stream/negotiate.py` est une implémentation littérale du .NET
NegotiateStream Protocol [MS-NNS], avec ses **deux** cadrages distincts.

#### Cadrage A — le message Handshake (phase de négociation)

`negotiate.py:24-30` déclare la structure suivante :

```python
class HandshakeDone(Record):
    code = MessageType.HANDSHAKE_DONE      # 0x14
    fields = [
        ('major', 'B'),
        ('minor', 'B'),
        ('payload_size', '>H')             # BIG-ENDIAN
    ]
```

Elle correspond exactement à la structure « Handshake Message » de [MS-NNS]
:

| Offset | Long. | Champ [MS-NNS] | Code du projet |
|---|---|---|---|
| 0 | 1 | `MessageId` | `Record.code_fmt = 'B'` (`nmf.py:220`) |
| 1 | 1 | `MajorVersion` (=0x01) | `('major', 'B')`, écrit `major=1` |
| 2 | 1 | `MinorVersion` (=0x00) | `('minor', 'B')`, écrit `minor=0` |
| 3 | 1 | `HighByteOfPayloadSize` | octet de poids fort de `>H` |
| 4 | 1 | `LowByteOfPayloadSize` | octet de poids faible de `>H` |
| 5.. | var | `AuthPayload` | token SPNEGO opaque |

Le format `'>H'` de `struct` place le poids fort en premier : c'est
littéralement la paire `HighByteOfPayloadSize` / `LowByteOfPayloadSize` de
la spécification. L'en-tête fait donc **5 octets**, ce que confirme la
lecture : `negotiate.py:66` fait `Handshake.parse(self._inner.read(5))`.

Les trois `MessageId` sont déclarés en `negotiate.py:14-17` :

| Valeur | Nom [MS-NNS] | Constante du projet | Émis par ce serveur ? |
|---|---|---|---|
| `0x14` | `HandshakeDone` | `HANDSHAKE_DONE` | Oui (`write_handshake_done`) |
| `0x15` | `HandshakeError` | `HANDSHAKE_ERROR` | **Non — jamais** |
| `0x16` | `HandshakeInProgress` | `HANDSHAKE_IN_PROGRESS` | Oui (`write` avant fin) |

Le choix de qui écrit quoi est explicite dans
`GENSECStream.negotiate_server` :

- `gssapi.py:129` : `self._inner.write_handshake_done(server_to_client)`
  quand gensec signale la fin ; cela force `_handshake_done = True`
  (`negotiate.py:83`) puis émet un record `0x14`.
- `gssapi.py:131` : `self._inner.write(server_to_client)` sinon ; comme
  `_handshake_done` est encore faux, `negotiate.py:51-57` fabrique un
  `HandshakeInProgress` (`0x16`).

#### Cadrage B — le message de données (après le handshake)

Une fois `_handshake_done` vrai, `NegotiateStream` change complètement de
cadrage (`negotiate.py:59-62`) :

```python
while data:
    data2 = data[:0xFC30]
    self._inner.write(struct.pack('<I', len(data2)) + data2)
    data = data[0xFC30:]
```

| Aspect | Valeur | Ancrage |
|---|---|---|
| Taille du préfixe | 4 octets | `struct.pack('<I', …)` |
| Endianness | **little-endian** | le `<` de `'<I'` |
| Maximum par trame | `0xFC30` (64 560) | `negotiate.py:60` et [MS-NNS] |
| Écrit par | `NegotiateStream.write` | `negotiate.py:61` |
| Lu par | `NegotiateStream.read` | `negotiate.py:79-80` |

`0xFC30` n'est pas une constante arbitraire choisie par l'auteur : [MS-NNS]
impose que le champ `PayloadSize` du « Data Message » ne dépasse pas
`0x0000FC30` (64 560 octets). Le code respecte donc la limite normative.

> **Deuxième écart avec la documentation du dépôt.**
> `documentation/03-protocole.md:48` décrit les tokens de la phase 2 comme «
> préfixés d'un `int32` little-endian de longueur ». C'est vrai des messages
> de **données**, faux des messages de **handshake** : tant que
> `_handshake_done` est faux (`negotiate.py:48,51,65`), le cadrage est
> l'en-tête de 5 octets ci-dessus, dont la taille est **big-endian**. Le
> préfixe `int32` little-endian n'apparaît qu'à partir du premier octet qui
> suit le `HandshakeDone`.

#### Synthèse : deux endianness dans le même fichier

C'est le piège de lecture principal de `negotiate.py`.

| Champ | Endianness | Format `struct` | Ligne |
|---|---|---|---|
| `payload_size` du Handshake | big-endian | `'>H'` | `negotiate.py:29` |
| `PayloadSize` du Data Message | little-endian | `'<I'` | `negotiate.py:61,79` |
| `ErrorCode` du HandshakeError | big-endian (dans ce code) | `'>II'` | `negotiate.py:71` |

Le troisième cas mérite une réserve. [MS-NNS] décrit l'`AuthPayload` d'un
`HandshakeError` comme une structure de 8 octets : `Reserved` (4 octets, mis
à zéro, à ignorer) puis `ErrorCode` (4 octets, un HRESULT ou
`ERROR_TRUST_FAILURE` = `0x000006FE`). Le projet lit bien 8 octets et
retient le second entier (`negotiate.py:71`), mais le décode en
**big-endian**. L'endianness normative de ce champ n'a pas pu être confirmée
; comme le serveur n'est jamais destinataire d'un `HandshakeError` en
pratique, ce chemin de code n'a probablement jamais été exercé. Il contient
d'ailleurs un défaut latent : si `payload_size == 0`, `error` reste `None`
et le `"{:08x}".format(None)` de `negotiate.py:72` lève un `TypeError` au
lieu de l'`IOError` attendu.

#### Ce que ce serveur ne fait pas comme .NET

| Aspect | Client .NET (SSPI) | Ce serveur (Python) |
|---|---|---|
| Cadrage handshake | [MS-NNS] Handshake Message | identique (`negotiate.py`) |
| Cadrage données | [MS-NNS] Data Message | identique (`negotiate.py`) |
| Fournisseur de sécurité | SSPI / `NegotiateStream`.NET | `samba.gensec` |
| Signalement d'erreur | `HandshakeError` + HRESULT | fermeture brutale du socket |
| Mode « ni signature ni chiffrement » | données non cadrées | non implémenté |

La différence réelle n'est donc **pas** le cadrage : c'est le *moteur* de
sécurité et la *gestion d'erreur*. Le serveur ne construit jamais de
`HandshakeError` ; `protocol.py:103-105` intercepte l'exception, journalise,
et `handle_security` retourne `False`, ce qui fait retourner
`ConnectionHandler.handle` (`connection.py:50-52`) et ferme le socket. C'est
la cause directe du message Windows documenté en
`documentation/06-depannage.md:41` : « The remote endpoint has terminated
the transport stream ». Windows ne reçoit pas de code d'erreur, il constate
une fermeture.

## SPNEGO : négociation du mécanisme (RFC 4178)

### Pourquoi SPNEGO et pas Kerberos directement

`TcpClientCredentialType.Windows` signifie « SSPI avec le paquet `Negotiate`
». Le paquet `Negotiate` de Windows est SPNEGO (RFC 4178, étendu par
[MS-SPNG]) : un pseudo-mécanisme GSS-API dont le rôle est de choisir un vrai
mécanisme parmi une liste. Le serveur y répond en armant le même
pseudo-mécanisme :

```python
self.client_ctx.start_mech_by_name("spnego")     # gssapi.py:118
```

C'est un choix explicite du projet : plutôt que de laisser gensec
sélectionner le mécanisme d'après l'OID du premier token, `gssapi.py:118`
impose SPNEGO. C'est correct pour un client WCF `Windows`, qui envoie
toujours du SPNEGO. Le comportement face à un client qui présenterait un
`InitialContextToken` Kerberos brut dépend du backend SPNEGO de Samba et
**n'a pas été vérifié** : aucun code du dépôt ne traite ce cas, et aucun
repli sur `start_mech_by_name("krb5")` n'existe.

### Le tableau des OID

Un `MechType` SPNEGO est un OID DER. Voici ceux qui apparaissent dans un
échange ADWS réel, avec leur encodage DER complet (octet de type `06`,
longueur, puis contenu).

| Mécanisme | OID | Encodage DER |
|---|---|---|
| SPNEGO | 1.3.6.1.5.5.2 | `06 06 2B 06 01 05 05 02` |
| Kerberos V5 | 1.2.840.113554.1.2.2 | `06 09 2A 86 48 86 F7 12 01 02 02` |
| MS KRB5 (legacy) | 1.2.840.48018.1.2.2 | `06 09 2A 86 48 82 F7 12 01 02 02` |
| NTLMSSP | 1.3.6.1.4.1.311.2.2.10 | `06 0A 2B 06 01 04 01 82 37 02 02 0A` |
| NEGOEX | 1.3.6.1.4.1.311.2.2.30 | `06 0A 2B 06 01 04 01 82 37 02 02 1E` |

L'OID « MS KRB5 » (1.2.840.48018.1.2.2) est un artefact historique : une
implémentation Microsoft ancienne avait mal transcrit `113554` en `48018`.
Les clients Windows le proposent encore, en général **en premier**, pour
compatibilité. Un serveur SPNEGO correct doit le traiter comme un synonyme
de Kerberos V5 ; Samba le fait, ce qui explique que ce projet n'ait rien à
coder à ce sujet.

> L'ordre exact de la `MechTypeList` dépend de la version de Windows et de
> la configuration (NEGOEX est présent sur les OS récents). Cet ordre
> **n'est pas observable dans ce dépôt** : aucun code n'analyse le token
> SPNEGO, il est transmis tel quel à gensec.

### Le wrapper GSS-API InitialContextToken (RFC 2743 §3.1)

Le **premier** token d'un échange GSS-API, et lui seul, est encapsulé dans
un `InitialContextToken` :

```text
InitialContextToken ::= [APPLICATION 0] IMPLICIT SEQUENCE {
        thisMech          MechType,
        innerContextToken ANY DEFINED BY thisMech
}
```

Concrètement sur le fil : l'étiquette `[APPLICATION 0] SEQUENCE` en DER vaut
l'octet `0x60`, suivi de la longueur DER, de l'OID du mécanisme, puis du
token interne. Les tokens **suivants** de la même conversation ne portent
pas ce wrapper.

```text
60 82 XX XX                     [APPLICATION 0], longueur longue (2 octets)
   06 06 2B 06 01 05 05 02      thisMech = SPNEGO (1.3.6.1.5.5.2)
   A0 82 XX XX                  [0] negTokenInit  (CHOICE NegotiationToken)
      30 82 XX XX               SEQUENCE NegTokenInit
         A0 ..  30 ..           [0] mechTypes : MechTypeList
            06 09 2A 86 48 82 F7 12 01 02 02     MS KRB5
            06 09 2A 86 48 86 F7 12 01 02 02     Kerberos V5
            06 0A 2B 06 01 04 01 82 37 02 02 0A  NTLMSSP
         A2 82 XX XX  04 82 XX XX                [2] mechToken OCTET STRING
            60 82 XX XX                          InitialContextToken imbriqué
               06 09 2A 86 48 86 F7 12 01 02 02  thisMech = Kerberos V5
               01 00                             TOK_ID = KRB_AP_REQ
               6E 82 XX XX  ...                  AP-REQ [APPLICATION 14]
         A3 ..  04 ..                            [3] mechListMIC (optionnel)
```

> Ce schéma est **reconstitué** d'après RFC 2743 §3.1, RFC 4178 §4.2.1 et
> RFC 4121 §4.1. Il n'est **pas** extrait d'une capture de ce dépôt : le
> projet ne décode aucun token SPNEGO. Les longueurs `XX XX` dépendent de la
> taille du ticket, elle-même fonction du PAC (souvent 1 à 4 Ko).

### NegTokenInit et NegTokenResp

RFC 4178 §4.2 définit deux structures. La première, émise par l'initiateur :

| Champ | Étiquette | Rôle |
|---|---|---|
| `mechTypes` | `[0]` | Liste ordonnée des mécanismes proposés |
| `reqFlags` | `[1]` | `ContextFlags` (déconseillé, ignoré en pratique) |
| `mechToken` | `[2]` | Token optimiste du premier mécanisme |
| `mechListMIC` | `[3]` | MIC calculé sur l'encodage de `mechTypes` |

La seconde, émise par l'accepteur (et par l'initiateur aux tours suivants) :

| Champ | Étiquette | Rôle |
|---|---|---|
| `negState` | `[0]` | État de la négociation (voir ci-dessous) |
| `supportedMech` | `[1]` | OID retenu, présent au premier tour de réponse |
| `responseToken` | `[2]` | Token du mécanisme choisi (ici l'AP-REP) |
| `mechListMIC` | `[3]` | MIC de l'accepteur sur la même `mechTypes` |

Les quatre valeurs de `negState` :

| Valeur | Nom | Signification |
|---|---|---|
| 0 | `accept-completed` | Contexte établi, plus rien à échanger |
| 1 | `accept-incomplete` | Il faut au moins un tour de plus |
| 2 | `reject` | Aucun mécanisme commun, ou échec définitif |
| 3 | `request-mic` | L'accepteur exige l'échange des `mechListMIC` |

Le `mechListMIC` est la protection anti-rétrogradation de SPNEGO : un
attaquant qui retirerait Kerberos de la `mechTypes` pour forcer NTLM
invaliderait le MIC. `request-mic` (valeur 3) est le mécanisme par lequel
l'accepteur impose cet échange. Windows l'exige systématiquement depuis les
correctifs de durcissement NTLM. **Tout cela est traité intégralement par
Samba** : le projet ne voit que des `bytes`.

### Conséquence directe sur le nombre d'allers-retours

La boucle `while not server_finished` de `gssapi.py:123-132` ne présume pas
du nombre de tours, et c'est nécessaire :

| Scénario | Tours (client→serveur) | Cause |
|---|---|---|
| Kerberos optimiste accepté | 1 | `mechToken` valide dès `NegTokenInit` |
| `request-mic` demandé | 2 | Un tour supplémentaire pour les MIC |
| Repli NTLM | 3 | Negotiate / Challenge / Authenticate |

Le repli NTLM est possible **par construction**. La mécanique exacte mérite
d'être posée : dans RFC 4178, l'accepteur ne publie pas sa propre liste, il
**choisit** dans celle de l'initiateur et renvoie le mécanisme retenu dans
`supportedMech`. Comme le client Windows place NTLMSSP dans sa `mechTypes`
et que gensec, sur un DC Samba de configuration usuelle, dispose du backend
NTLMSSP, rien n'empêche la sélection de NTLM lorsque Kerberos échoue. Ce
projet n'a aucun code pour l'interdire : il n'y a aucun appel à
`want_feature` ni aucune restriction de mécanisme dans le dépôt (recherche
exhaustive sur `want_feature` et `GENSEC_FEATURE` : zéro occurrence).
Interdire NTLM se fait au niveau de `smb.conf` (paramètre `ntlm auth`), donc
hors de ce code, et le `documentation/` du dépôt ne prescrit rien à ce
sujet.

## Kerberos : obtention du ticket de service côté client

### Le SPN effectivement demandé

WCF, pour une `EndpointAddress` `net.tcp://<host>:9389/…` sans identité
explicite, dérive un `SpnEndpointIdentity` de la forme `host/<host>` à
partir du nom DNS de l'URI. Ce comportement n'est pas dans ce dépôt (il est
côté Windows), mais le dépôt le **confirme** de trois façons indépendantes :

| Source | Contenu | Ligne |
|---|---|---|
| `documentation/02-installation.md` | « PowerShell demande un ticket pour `host/<fqdn-du-dc>` » | 82 |
| `tools/installation/install.sh` | `spn="host/${fqdn}"` puis `samba-tool spn add` | 65-69 |
| `documentation/06-depannage.md` | « Il faut au minimum `host/<fqdn>` dans la liste » | 54 |

Le SPN dérivé dépend donc **littéralement de ce que l'utilisateur a tapé** :

| Commande PowerShell | SPN demandé | Résultat attendu |
|---|---|---|
| `-Server samba.local` | `host/samba.local` | Kerberos si le SPN existe |
| `-Server SAMBA` | `host/SAMBA` | Kerberos (SPN court usuel) |
| `-Server 192.168.141.10` | `host/192.168.141.10` | SPN absent d'AD |

Le troisième cas est le piège classique : le KDC répond
`KDC_ERR_S_PRINCIPAL_UNKNOWN` et Windows bascule silencieusement sur NTLM.
Comme Samba accepte NTLMSSP via SPNEGO, la connexion **peut réussir quand
même**, avec une authentification plus faible. Ce comportement de repli est
déduit des spécifications et de la configuration Samba par défaut ; il **n'a
pas été vérifié expérimentalement dans ce dépôt** et aucun code ne le trace.

### La chaîne TGT vers AP-REQ

- **1. TGT.** Le client possède déjà un `krbtgt/REALM@REALM` obtenu à
  l'ouverture de session (ou via `kinit`, cf.
  `documentation/02-installation.md:74`). Rien de spécifique à ADWS ici.
- **2. TGS-REQ.** Le client demande au KDC un ticket pour `host/samba.local`
  : un `PA-TGS-REQ` (padata type 1) portant un AP-REQ vers `krbtgt`, et le
  SPN cible dans le champ `sname` du corps.
- **3. TGS-REP.** Le KDC répond avec le `Ticket` chiffré sous la **clé de
  long terme du compte machine du DC**, et une partie chiffrée sous la clé
  de session du TGT qui porte la nouvelle clé de session de service.
- **4. AP-REQ.** Le client assemble le ticket tel quel plus un
  `Authenticator` chiffré sous la clé de session de service.
- **5. AP-REP.** Le serveur, s'il a pu déchiffrer, renvoie `ctime`/`cusec`
  recopiés et éventuellement une sous-clé d'accepteur. C'est cet AP-REP qui
  réalise l'authentification **mutuelle**.

Les étapes 1 à 3 se déroulent sur le port 88 (TCP/UDP), listé parmi les
ports requis du client vers le DC en `documentation/02-installation.md:39`
(table des ports, lignes 37 à 42). Le serveur ADWS ne voit que l'étape 4 et
produit l'étape 5 : il n'est ni KDC ni relais vers le KDC.

### Les flags demandés

Le code client vendoré `GSSAPIStream.__init__` (`gssapi.py:21-24`) montre
explicitement les flags qu'un initiateur GSS-API doit poser pour ADWS :

```python
flags=(gssapi.RequirementFlag.mutual_authentication |
       gssapi.RequirementFlag.confidentiality |
       gssapi.RequirementFlag.integrity)
```

Ces trois flags correspondent point pour point au contrat
`ProtectionLevel.EncryptAndSign` + `ClientCredentialType.Windows` de la
configuration d’hôte du service ADWS Microsoft. Leur encodage numérique, tel
qu'il apparaît dans le checksum GSS-API de l'authenticator (RFC 4121
§4.1.1.1) :

| Bit | Flag GSS-API | Demandé par ADWS |
|---|---|---|
| `0x01` | `GSS_C_DELEG_FLAG` | Non |
| `0x02` | `GSS_C_MUTUAL_FLAG` | Oui |
| `0x04` | `GSS_C_REPLAY_FLAG` | Implicite (impliqué par SEQUENCE) |
| `0x08` | `GSS_C_SEQUENCE_FLAG` | Oui côté WCF |
| `0x10` | `GSS_C_CONF_FLAG` | Oui (`EncryptAndSign`) |
| `0x20` | `GSS_C_INTEG_FLAG` | Oui |

> `GSSAPIStream` (`gssapi.py:20-78`) est le chemin **client**, hérité du
> projet amont de Timo Schmid. Il n'est jamais instancié par le serveur :
> `protocol.py` n'utilise que `GENSECStream`. Il sert de référence de
> comportement et est employé par le client de test
> `src/nettcp/stream/nmf.py:37`.

### Types de chiffrement

Le projet ne configure **aucun** type de chiffrement : recherche exhaustive
sur `etype`, `enctype`, `aes`, `rc4` dans les sources, aucun résultat hors
dictionnaire WCF XML-Enc (`src/wcf/dictionary.py:168-173`, sans rapport).
Tout est délégué à la bibliothèque Kerberos de Samba et à `/etc/krb5.conf`.

| etype | Nom | Référence | Statut sur un DC Samba |
|---|---|---|---|
| 18 | `aes256-cts-hmac-sha1-96` | RFC 3962 | Proposé, préféré |
| 17 | `aes128-cts-hmac-sha1-96` | RFC 3962 | Proposé |
| 23 | `rc4-hmac` | RFC 4757 | Proposé (compatibilité) |
| 16 | `des3-cbc-sha1-kd` | RFC 3961 | Obsolète, non utilisé |
| 1 / 3 | `des-cbc-crc` / `des-cbc-md5` | RFC 3961 | Désactivés par défaut |

L'attribut `msDS-SupportedEncryptionTypes` du compte machine ([MS-KILE]
§2.2.7) gouverne ce que le KDC accepte de proposer :

| Bit | Type couvert |
|---|---|
| `0x01` | DES-CBC-CRC |
| `0x02` | DES-CBC-MD5 |
| `0x04` | RC4-HMAC |
| `0x08` | AES128-CTS-HMAC-SHA1-96 |
| `0x10` | AES256-CTS-HMAC-SHA1-96 |

Le support des etypes RFC 8009 (19 = `aes128-cts-hmac-sha256-128`, 20 =
`aes256-cts-hmac-sha384-192`) dépend entièrement de la version de Samba et
de sa bibliothèque Kerberos ; il **n'a pas été vérifié** pour la version
ciblée par ce projet, que le `CLAUDE.md` §8 laisse d'ailleurs « à préciser
». Les mentions « Kerberos AES256 » de `documentation/03-protocole.md:15` et
« Kerberos AES » de `README.md:39` décrivent l'usage nominal attendu, pas
une contrainte imposée ou vérifiée par le code : aucune ligne du dépôt ne
refuse un etype.

## Le token AP-REQ : structure et champs

### Le tableau des TOK_ID

Juste après l'OID du mécanisme dans un `InitialContextToken` Kerberos, deux
octets identifient le type de token (RFC 4121 §4.1 pour les deux premiers,
§4.2.6 pour les tokens par-message).

| TOK_ID | Nom | Sens | Référence |
|---|---|---|---|
| `01 00` | `KRB_AP_REQ` | Requête d'authentification | RFC 4121 §4.1 |
| `02 00` | `KRB_AP_REP` | Réponse d'authentification mutuelle | RFC 4121 §4.1 |
| `03 00` | `KRB_ERROR` | Erreur Kerberos encapsulée GSS | RFC 4121 §4.1 |
| `04 04` | MIC (CFX) | `GSS_GetMIC`, version 2 | RFC 4121 §4.2.6.1 |
| `05 04` | Wrap (CFX) | `GSS_Wrap`, version 2 | RFC 4121 §4.2.6.2 |

Les TOK_ID à second octet `0x04` sont ceux de la « version 2 » (dite CFX,
introduite par RFC 4121) ; ceux à second octet `0x01` appartiennent au
format historique RFC 1964, qui utilisait `01 01` pour le MIC et `02 01`
pour le Wrap. Un DC Samba et un client Windows moderne n'utilisent que CFX
dès lors que l'etype est AES. RFC 4121 ne définit **que** ces deux tokens
par message : il n'existe pas de token de destruction de contexte en version
2, contrairement au `01 02` de RFC 1964. Aucun de ces octets n'apparaît dans
le code de ce dépôt, la table sert à lire une capture, pas à décrire un
traitement.

### Structure de l'AP-REQ (RFC 4120 §5.5.1)

```text
AP-REQ ::= [APPLICATION 14] SEQUENCE {
        pvno            [0] INTEGER (5),
        msg-type        [1] INTEGER (14),
        ap-options      [2] APOptions,
        ticket          [3] Ticket,
        authenticator   [4] EncryptedData -- Authenticator
}
```

L'étiquette `[APPLICATION 14]` se traduit par l'octet `0x6E` en DER, c'est
le premier octet visible après le `01 00` du TOK_ID.

| Champ | Contenu pour ADWS |
|---|---|
| `pvno` | 5 |
| `msg-type` | 14 (`KRB_AP_REQ`) |
| `ap-options` | `mutual-required` positionné (bit 2) |
| `ticket` | Ticket pour `host/<fqdn>`, chiffré sous la clé machine du DC |
| `authenticator` | `EncryptedData` (usage 11), clé = clé de session du ticket |

`APOptions` est un `KerberosFlags` (BIT STRING) : `reserved` = bit 0,
`use-session-key` = bit 1, `mutual-required` = bit 2. Comme la numérotation
des bits part du poids fort, `mutual-required` seul donne `0x20` dans le
premier octet utile de la chaîne de bits.

### Structure de l'Authenticator

```text
Authenticator ::= [APPLICATION 2] SEQUENCE {
        authenticator-vno  [0] INTEGER (5),
        crealm             [1] Realm,
        cname              [2] PrincipalName,
        cksum              [3] Checksum OPTIONAL,
        cusec              [4] Microseconds,
        ctime              [5] KerberosTime,
        subkey             [6] EncryptionKey OPTIONAL,
        seq-number         [7] UInt32 OPTIONAL,
        authorization-data [8] AuthorizationData OPTIONAL
}
```

Trois champs sont décisifs pour comprendre le reste du chapitre.

Le premier est **`cksum`**. Pour GSS-API, c'est un checksum de type
**0x8003** défini par RFC 4121 §4.1.1 ; ce n'est pas un vrai checksum, mais
un conteneur de paramètres, disposé ainsi.

| Offset | Long. | Champ | Valeur / rôle |
|---|---|---|---|
| 0..3 | 4 | `Lgth` | `10 00 00 00` (16, little-endian) |
| 4..19 | 16 | `Bnd` | MD5 des channel bindings, ou 16 octets nuls |
| 20..23 | 4 | `Flags` | Flags GSS-API, little-endian |
| 24..25 | 2 | `DlgOpt` | Présent seulement si `GSS_C_DELEG_FLAG` |
| 26..27 | 2 | `Dlgth` | Longueur du `KRB_CRED` délégué |
| 28.. | var | `Deleg` | `KRB_CRED` délégué |

ADWS ne demandant pas la délégation, les champs `DlgOpt`/`Dlgth`/`Deleg`
sont **absents** et le checksum fait exactement 24 octets. Le champ `Flags`
porte les valeurs `0x02 | 0x08 | 0x10 | 0x20` (mutual, sequence, conf,
integ), soit `0x3A`, encodé `3A 00 00 00`.

Le deuxième est **`subkey`**, la sous-clé proposée par l'initiateur. Si elle
est présente, c'est elle, et non la clé de session du ticket, qui sert de
base à la dérivation des clés de scellement RFC 4121. L'accepteur peut à son
tour proposer la sienne dans l'AP-REP : le flag `AcceptorSubkey` (bit `0x04`
du champ `Flags` du token Wrap) signale alors que la clé de l'accepteur est
utilisée.

Le troisième est le couple **`ctime` / `cusec`**, l'horodatage du client,
que le serveur compare à son horloge locale avec une tolérance par défaut de
5 minutes (`clockskew`). Au-delà, l'authentification échoue, cause de
l'avertissement de `documentation/06-depannage.md:69`.

### Ce que ce projet manipule de tout cela

**Rien.** Aucun octet de l'AP-REQ n'est analysé par du code Python de ce
dépôt. `GENSECStream.negotiate_server` transmet le token intégral à
`self.client_ctx.update(token)` (`gssapi.py:125`). La section précédente est
donc une description du *contenu* du champ `AuthPayload` du message NNS,
utile pour lire une capture Wireshark, et non de structures que le projet
construirait ou validerait.

## Établissement du contexte côté serveur avec samba.gensec

### La séquence exacte, ligne par ligne

Tout tient dans `GENSECStream` (`src/nettcp/stream/gssapi.py:84-132`). Voici
l'ordre réel des opérations, sans reformulation.

| Ordre | Ligne | Appel | Effet |
|---|---|---|---|
| 1 | `:89` | `NegotiateStream(stream)` | Installe le cadrage [MS-NNS] |
| 2 | `:99` | `LoadParm` + `load_default` | Charge `smb.conf` |
| 3 | `:102` | `lp_ctx.get("netbios name")` | Renseigne `target_hostname` |
| 4 | `:105` | `self._inner.read` | Lit le **premier** token client |
| 5 | `:107` | `gensec.Security.start_server(...)` | Crée le contexte accepteur |
| 6 | `:113` | `Credentials` | Conteneur de credentials vide |
| 7 | `:114` | `creds.guess(self.lp_ctx)` | Devine realm, workgroup, ccache |
| 8 | `:115` | `creds.set_machine_account(lp_ctx)` | Charge la clé machine |
| 9 | `:116` | `self.client_ctx.set_credentials(creds)` | Attache les credentials |
| 10 | `:118` | `start_mech_by_name("spnego")` | Arme SPNEGO |
| 11 | `:123-132` | boucle `update` | Échange les tokens |

Deux points d'ordre méritent d'être soulignés parce qu'ils sont
contre-intuitifs.

- **La lecture précède la création du contexte.** `gssapi.py:105` lit le
  token avant que `start_server` ne soit appelé. Aucun contexte gensec n'est
  alloué tant que le client n'a rien dit, c'est économe, mais cela signifie
  aussi qu'un client muet ne laisse aucune trace exploitable dans les
  journaux. Et il reste muet aussi longtemps qu'il le souhaite : le timeout
  de 10 secondes posé en `connection.py:39` **est annulé dès la première
  lecture**. `SocketStream` appelle `self._socket.setblocking(1)` avant
  chaque `recv` (`socket.py:32`) et avant chaque `sendall` (`socket.py:51`)
  ; or `setblocking(True)` équivaut, par définition de l'API socket de
  Python, à `settimeout(None)`. La conséquence est double : un client qui
  ouvre la connexion et se tait immobilise un processus fils indéfiniment,
  et le chemin `except socket_timeout` de `protocol.py:115-125`, celui qui
  est censé envoyer l'`EndRecord` de clôture, n'est jamais atteint. C'est un
  point de durcissement de phase 5 aussi important que l'identité : le
  serveur étant en `ForkingTCPServer` (`classes/server/server.py:25`),
  chaque connexion muette coûte un processus.
- **`guess` puis `set_machine_account`.** L'ordre compte :
  `set_machine_account` écrase les identifiants devinés par `guess`.
  Inverser les deux lignes ferait tenter une authentification avec les
  credentials du processus (root, ou un ccache résiduel) au lieu du compte
  machine.

### Le contrat de `update`

`gssapi.py:125` :

```python
server_finished, server_to_client = self.client_ctx.update(token)
```

L'API Python de gensec renvoie un tuple `(bool, bytes)` et **traduit** les
NTSTATUS de la couche C :

| NTSTATUS interne | Retour Python | Traitement dans `gssapi.py` |
|---|---|---|
| `NT_STATUS_MORE_PROCESSING_REQUIRED` | `(False, token)` | `:131` write + `:132` read |
| `NT_STATUS_OK` | `(True, token)` | `:129` `write_handshake_done(token)` |
| tout autre | lève `samba.NTSTATUSError` | remonte à `protocol.py:103` |

La troisième ligne est la clé du diagnostic : la trace de
`documentation/06-depannage.md:33` (`samba.NTSTATUSError: (3221225572, 'The
specified account does not exist.')`) est exactement une exception échappée
de `update`, remontée jusqu'au `except Exception` de `protocol.py:103`.

> **Trace obsolète dans la documentation.** La même trace, en
> `documentation/06-depannage.md:31`, situe l'appel à
> `src/nettcp/stream/gssapi.py`, ligne 119. Dans l'état actuel du fichier,
> la ligne 119 est vide : l'appel à `update` est en `gssapi.py:125`. Le
> numéro de ligne de la documentation date d'une version antérieure du
> fichier et ne doit pas servir de repère.

Noter que `write_handshake_done` est appelé **même si `server_to_client` est
vide** : [MS-NNS] autorise un `AuthPayload` de longueur nulle dans un
`HandshakeDone` lorsque le paquet de sécurité n'a pas produit de token
final. Le code est donc conforme sans avoir eu à traiter ce cas
explicitement.

### Pourquoi aucun keytab externe n'est requis

C'est la conséquence directe de `creds.set_machine_account(self.lp_ctx)`
(`gssapi.py:115`). Cet appel lit le secret du compte machine du DC dans la
base de secrets locale de Samba, `/var/lib/samba/private/secrets.tdb` (et
`secrets.ldb`), ce que confirme `documentation/03-protocole.md:57`. Sur un
contrôleur de domaine, ces secrets contiennent les clés de long terme de
tous les etypes du compte machine, celles-là mêmes avec lesquelles le KDC a
chiffré le ticket de service.

| Approche classique | Ce projet |
|---|---|
| `samba-tool domain exportkeytab /etc/adws.keytab` | inutile |
| `KRB5_KTNAME=/etc/adws.keytab` dans l'environnement | absent |
| Rotation manuelle du keytab au changement de mdp machine | automatique |

Le corollaire opérationnel est une **contrainte de privilèges** : la base de
secrets n'est lisible que par root. C'est pourquoi
`documentation/02-installation.md:124` prescrit `sudo python3 -m src.main`
et pourquoi l'unit systemd tourne en root. Un `Requires=samba-ad-dc.service`
est d'ailleurs posé dans `tools/installation/samba-adws.service`.

Second corollaire, moins évident : **le serveur ne restreint pas le service
demandé**, il ne le connaît même pas. Aucun `target_service` n'est posé dans
`settings` (`gssapi.py:97-102`), et aucune comparaison de SPN n'existe dans
le dépôt. Un ticket émis pour un autre SPN du même compte machine, par
exemple `cifs/<fqdn>`, se déchiffre avec la même clé de long terme ; la
question de savoir si gensec le rejette malgré tout relève de son
implémentation et **n'a pas été vérifiée expérimentalement ici**. Ce qui est
certain, c'est que ce projet n'apporte aucune restriction de son côté.

### Ce que `settings` contient, et ce qu'il ne contient pas

```python
self.settings["lp_ctx"] = self.lp_ctx = LoadParm()     # gssapi.py:99
self.settings["target_hostname"] = self.lp_ctx.get("netbios name")   # :102
```

`target_hostname` est renseigné avec le **nom NetBIOS**, pas le FQDN, alors
que le SPN présenté par le client porte le FQDN. L'écart n'a jamais provoqué
d'incident documenté dans ce dépôt, vraisemblablement parce que ce champ
sert surtout à l'initiateur pour construire le nom de service cible, mais
cette explication est une **interprétation, non vérifiée** dans le code de
Samba. Ce qui est certain et vérifiable : le dictionnaire `settings` ne
contient que ces deux clés (`gssapi.py:97-102`), aucun `target_service` n'y
figure, et aucun `want_feature` n'est appelé. Le niveau de protection
effectif est donc **entièrement dicté par les flags du client**.

## Scellement des messages : wrap / unwrap (RFC 4121)

### L'ordre d'emboîtement : la réponse formelle

C'est la question la plus fréquemment mal tranchée. Voici la démonstration
par le code, dans le sens émission.

1. `protocol.py:153-156` construit
  `nmf.SizedEnvelopedMessageRecord(Payload=payload, Size=len(payload))` où
  `payload` est le XML binaire WCF produit par le dispatcher.
2. `protocol.py:157` appelle `send_record(response)` qui fait
  `self.stream.write(record.to_bytes)` (`protocol.py:185-188`). `to_bytes`
  (`nmf.py:275-287`) sérialise `0x06` + varint(Size) + Payload.
3. `self.stream` a été remplacé par `GENSECStream` en
  `protocol.py:96`. On entre donc dans `GENSECStream.write`
  (`gssapi.py:144-152`), qui découpe en tranches de `_PLAINTEXT_CHUNK` et
  applique `self.client_ctx.wrap(data2)`.
4. Le token scellé part dans `self._inner.write(e_data)`, c'est-à-dire
  `NegotiateStream.write` (`negotiate.py:59-62`), qui préfixe un `uint32`
  little-endian.

**Conclusion sans ambiguïté** : l'en-tête du record NMF (`0x06` + varint de
taille) est **à l'intérieur** de la zone chiffrée. L'ordre est donc :

```text
XML SOAP
  -> XML binaire WCF (MS-NBFX)
    -> SizedEnvelopedMessageRecord : 0x06 || varint(Size) || Payload
      -> GSS wrap (RFC 4121, TOK_ID 05 04)
        -> Data Message MS-NNS : uint32 LE (<= 0xFC30) || token
          -> TCP
```

Le sens réception le confirme exactement : `protocol.py:114` appelle
`nmf.Record.parse_stream(self.stream)`, où `self.stream` est le
`GENSECStream`. `Record.parse_stream` (`nmf.py:256-273`) lit **1 octet**
pour le code, puis les champs, chacun de ces `read` traverse
`GENSECStream.read(count)` (`gssapi.py:162-170`), qui descelle des trames
entières et sert les octets demandés depuis `_readcache`. Le parseur NMF ne
voit donc que du clair.

> **Correction d'une erreur de la documentation du dépôt.** Le schéma de
> `documentation/03-protocole.md:67-71` dessine `0x06 | varint length |
> GSSAPI-wrapped(WCF binary)`, ce qui laisse entendre que l'en-tête NMF est
> en clair. Le code montre l'inverse. Une capture réseau après la phase 2 ne
> montre **que** des trames `uint32 LE + token opaque` : on ne voit plus
> jamais l'octet `0x06`.

### Le token Wrap version 2 (RFC 4121 §4.2.6.2)

L'en-tête fait 16 octets et précède les données scellées.

| Offset | Long. | Champ | Contenu |
|---|---|---|---|
| 0..1 | 2 | `TOK_ID` | `05 04` |
| 2 | 1 | `Flags` | Voir table des bits ci-dessous |
| 3 | 1 | `Filler` | `FF` |
| 4..5 | 2 | `EC` | Extra count, big-endian |
| 6..7 | 2 | `RRC` | Right rotation count, big-endian |
| 8..15 | 8 | `SND_SEQ` | Numéro de séquence, big-endian |
| 16.. | var | `Data` | Données chiffrées + tag d'intégrité |

Les bits du champ `Flags` :

| Bit | Nom | Signification |
|---|---|---|
| `0x01` | `SentByAcceptor` | Le token vient de l'accepteur (le serveur) |
| `0x02` | `Sealed` | Confidentialité appliquée, pas seulement l'intégrité |
| `0x04` | `AcceptorSubkey` | Les clés dérivent de la sous-clé de l'accepteur |

Avec confidentialité, la charge utile n'est pas simplement le clair chiffré
: RFC 4121 §4.2.4 impose de chiffrer la concaténation `confounder ||
plaintext || filler || copie de l'en-tête`, puis d'appliquer la rotation
`RRC`. Pour `aes256-cts-hmac-sha1-96`, le surcoût se décompose ainsi.

| Élément | Octets |
|---|---|
| En-tête en clair | 16 |
| Confounder (taille de bloc AES) | 16 |
| Copie de l'en-tête, chiffrée | 16 |
| Tag HMAC-SHA1-96 tronqué | 12 |
| **Total (avec EC = 0)** | **60** |

Ce chiffre de 60 octets n'est pas théorique : c'est celui qui figure dans le
commentaire de `src/nettcp/stream/gssapi.py:12-16`, et c'est lui qui a dicté
la valeur de `_PLAINTEXT_CHUNK`.

### Pourquoi `_PLAINTEXT_CHUNK = 0xF000`

```python
_PLAINTEXT_CHUNK = 0xF000       # gssapi.py:17
```

| Grandeur | Valeur | Origine |
|---|---|---|
| Trame MS-NNS maximale | 64 560 (`0xFC30`) | [MS-NNS] Data Message |
| Clair par appel à `wrap` | 61 440 (`0xF000`) | `gssapi.py:17` |
| Surcoût GSS estimé | 60 | RFC 4121, en-tête + confounder + HMAC |
| Token résultant | 61 500 | 61 440 + 60 |
| Marge restante | 3 060 | 64 560 - 61 500 |

Le commentaire de `gssapi.py:12-16` explique la raison d'être de cette marge
: « otherwise a single wrapped token spills into a second frame and the
reader, which assumes one frame == one token, fails to unwrap it ». C'est
exact et vérifiable : `GENSECStream.read` (`gssapi.py:163-166`) appelle
`unwrap` sur le résultat d'**un seul** `self._inner.read`. Il n'existe aucun
réassemblage de token à cheval sur deux trames MS-NNS. Si le clair dépassait
la marge, le descellement échouerait.

Le découpage n'est en revanche **pas** un problème pour les gros messages :
une réponse `Pull` de 500 Ko produit simplement neuf tokens successifs, et
le `_readcache` de `GENSECStream` (`gssapi.py:162-169`) recolle le clair de
façon transparente pour le parseur NMF.

### Ce que le projet fait, et ce que la bibliothèque fait

| Opération | Réalisée par | Ancrage |
|---|---|---|
| Construction de l'en-tête `05 04` | Samba (gensec) | opaque au projet |
| Choix `Sealed` vs signature seule | Samba, d'après les flags client | pas de `want_feature` |
| Incrément de `SND_SEQ` | Samba | jamais lu par le projet |
| Vérification du HMAC | Samba, dans `unwrap` | `gssapi.py:160,166` |
| Détection de rejeu / hors-séquence | Samba, si le flag est négocié | non configuré |
| Découpage en tranches | **Le projet** | `gssapi.py:148-152` |
| Cadrage `uint32` LE | **Le projet** | `negotiate.py:61` |
| Réassemblage du clair | **Le projet** | `gssapi.py:162-169` |

Le périmètre du projet est donc strictement : découper, cadrer, recoller.
Toute la cryptographie est chez Samba.

### MIC, rejeu et numéros de séquence

- Le **`mechListMIC`** de SPNEGO est produit et vérifié par gensec pendant
  la phase de handshake. Le projet ne le voit pas.
- Le **MIC par message** (TOK_ID `04 04`) n'est jamais utilisé : ADWS scelle
  tout, il n'y a pas de message signé sans être chiffré. Aucun appel à une
  fonction `sign`/`check_packet` n'existe dans le dépôt.
- Le **`SND_SEQ`** est géré par Samba. Le projet ne l'inspecte pas et ne
  peut donc pas journaliser un désalignement de séquence : un tel incident
  se manifeste par une exception d'`unwrap` remontée en
  `protocol.py:179-181`.
- Le **cache anti-rejeu Kerberos** (`rcache`) dépend de la compilation de
  Samba et de la configuration Kerberos système. Aucune variable
  `KRB5RCACHE*` ni aucun réglage de rcache n'apparaît dans ce dépôt : **non
  vérifié**, et non gouverné par ce projet.

## Identité, délégation et contrôle d'accès

### Le constat, sans ménagement

L'identité du client est établie de façon cryptographiquement solide, puis
**abandonnée**. La preuve tient en trois lignes de
`classes/server/connection.py`.

```python
session_info = system_session() if system_session else None
dispatcher = ADWSDispatcher(self.logger, session_info=session_info)
```

Ces deux lignes sont `connection.py:56-57` ; elles sont précédées du
commentaire `Use system_session for SamDB context - auth is done via GSSAPI`
(`connection.py:55`), qui assume explicitement le raccourci. Le
`session_info` transmis à tout l'étage applicatif est
`samba.auth.system_session`, c'est-à-dire l'identité **SYSTEM** de la base,
pas celle du client. Le contexte gensec (`GENSECStream.client_ctx`) n'est
consulté à aucun moment après la négociation : une recherche exhaustive sur
`client_ctx` dans le dépôt ne retourne que des occurrences internes à
`src/nettcp/stream/gssapi.py`, et **aucun** appel à la méthode
`session_info` de l'objet gensec n'existe nulle part.

### Chemin complet du `session_info`

| Étape | Fichier | Valeur véhiculée |
|---|---|---|
| Création | `connection.py:56` | `system_session` |
| Injection dispatcher | `connection.py:57` | idem |
| Stockage | `dispatcher.py:17-18` | idem |
| Registre de handlers | `handler_registry.py:11-13` | idem |
| Handler de base | `base.py:19-21` | idem |
| Ouverture LDB | `samba_db.py:15,26` | `SamDB(lp=lp, session_info=...)` |

`samba_db.py:15` applique de surcroît un repli `session_info or
system_session` : même un `None` accidentel finit en SYSTEM.

Le pool de sessions LDAP mérite une précision, car il est facile de le
prendre pour une amorce fonctionnelle. `LdapSessionPool.acquire`
(`ldap_session_pool.py:28-50`) indexe bien ses `SambaDB` par `(owner_sid,
instance)` et accepte un `session_info` par appelant, ce qui montre
l'intention d'un jour porter l'identité réelle. Mais l'objet n'est
qu'**instancié** (`classes/server/service_context.py:18`) : une recherche
sur `session_pool` dans tout le dépôt ne retourne que cette instanciation et
l'import qui la précède. Aucun handler n'appelle `acquire`, `release` ni
`get`. Le chemin de requête réel reste celui du tableau ci-dessus,
c'est-à-dire le `SambaDB` créé directement par `BaseHandler.__init__`
(`base.py:21`). À cela s'ajoute que le serveur est en `ForkingTCPServer`
(`server.py:25`) : le singleton `ServiceContext`
(`service_context.py:21-26`) est reconstruit dans chaque processus fils,
donc un pool de connexions inter-clients ne pourrait de toute façon pas
fonctionner sous cette forme.

### Conséquences concrètes

- **Toutes les opérations d'annuaire s'exécutent avec les privilèges du
  service**, c'est-à-dire root sur le DC, donc SYSTEM dans LDB. Les ACL AD
  ne sont pas évaluées contre l'utilisateur qui a lancé la cmdlet.
- Le message d'erreur `InsufficientAccessRights` documenté en
  `documentation/06-depannage.md:293` ne peut donc **pas** provenir d'un
  refus d'ACL lié à l'appelant : il proviendrait d'une contrainte LDB ou
  d'une vérification de politique côté Samba. La section 8 de ce document («
  Droits insuffisants », `documentation/06-depannage.md:282`), dont la cause
  annoncée est « Le compte authentifié … n'a pas les droits AD »
  (`documentation/06-depannage.md:298`), décrit une intention de conception,
  pas le comportement du code actuel.
- Il n'y a **aucun contrôle d'autorisation applicatif** : dès lors que le
  handshake GSSAPI réussit, n'importe quel compte du domaine peut déclencher
  n'importe quelle opération exposée par les handlers, y compris les
  mutations. Le seul rempart est l'authentification.

> **Point de durcissement prioritaire (phase 5).** Remplacer
> `system_session` par la `session_info` produite par le contexte gensec est
> la modification qui apporterait le plus de sécurité, et la plus
> structurante : elle transformerait le service d'un proxy privilégié en un
> véritable relais d'identité, avec évaluation des ACL AD par Samba.

### Délégation

Aucune forme de délégation n'est implémentée :

| Mécanisme | État |
|---|---|
| `GSS_C_DELEG_FLAG` / ticket transmis | Non demandé, non exploité |
| Délégation contrainte S4U2Proxy | Absent |
| S4U2Self (protocol transition) | Absent |
| Connexion `ldapi://` sous l'identité client | Absent |

`documentation/01-architecture.md:155` cite précisément l'absence de
délégation comme cause d'une limite fonctionnelle : le changement de mot de
passe self-service (`Set-ADAccountPassword` avec ancien et nouveau mot de
passe) échoue parce que le module Samba `password_hash` exige l'adresse
réseau du client, non fournissable via une `SamDB` locale. La piste
explicitement mentionnée est la « délégation de l'identité du client GSSAPI
». Le reset administrateur (`-Reset`) fonctionne, lui, puisqu'il s'exécute
avec des privilèges SYSTEM.

## Diagnostic des échecs d'authentification

### Ce que le serveur journalise réellement

Trois messages seulement encadrent la phase 2, tous dans `protocol.py` :

| Message | Ligne | Interprétation |
|---|---|---|
| `[SECURITY] PHASE 2: SECURITY NEGOTIATION` | `:71` | `handle_security` démarre |
| `[SECURITY] Starting GSSAPI negotiation...` | `:95` | `UpgradeResponseRecord` déjà émis |
| `[SECURITY] GSSAPI negotiation completed` | `:99` | Contexte établi, `wrap` actif |

Si le troisième n'apparaît pas, l'échec est dans la boucle `update`. La
trace complète est journalisée par `protocol.py:104` avec `exc_info=True`.

Il faut ici démonter une idée reçue, car elle fait perdre un temps
considérable en diagnostic. La pile de sécurité comporte bien trois traces
DEBUG utiles, `Doing step` (`gssapi.py:124`), `NNS Handshake done`
(`negotiate.py:75`) et, si `python-helperlib` est installé, un hexdump
complet de chaque lecture et écriture (`socket.py:41-43` et `:47-49`), mais
**`ADWS_LOG_LEVEL=DEBUG` ne les fait pas apparaître.** Trois mécanismes se
conjuguent contre l'opérateur.

| Obstacle | Emplacement | Effet |
|---|---|---|
| `ADWS_LOG_LEVEL` ne vise que le logger `adws` | `config.py:46`, `:56` | Périmètre trop étroit |
| Le handler console est figé à `INFO` | `config.py:60` | DEBUG jamais affiché |
| `basicConfig(level=INFO)` à l'import | `src/wcf/records/text.py:62` | Racine forcée à INFO |

Le détail du troisième obstacle mérite d'être explicité. Les modules
`src/wcf/records/text.py:62`, `src/wcf/records/elements.py:44` et
`src/wcf/records/attributes.py:44` appellent
`logging.basicConfig(level=INFO)` **au moment de leur import**, et cet
import a lieu dès le chargement du dispatcher
(`classes/handlers/dispatcher.py:4`). Or les loggers de la pile de sécurité
s'appellent `src.nettcp.stream.gssapi.GSSAPIStream`,
`src.nettcp.stream.negotiate.NegotiateStream` et
`src.nettcp.stream.socket.SocketStream` (`gssapi.py:10`, `negotiate.py:11`,
`socket.py:16`) : ils héritent du logger **racine**, pas du logger `adws`
configuré par `Config.setup_logging`. Leur niveau effectif est donc `INFO`,
quelle que soit la valeur de `ADWS_LOG_LEVEL`, et le test
`log.isEnabledFor(logging.DEBUG)` de `socket.py:41` et `:47` est faux.

Pour réellement observer les tokens du handshake, il faut abaisser le niveau
du logger racine, par exemple en ajoutant
`logging.getLogger.setLevel(DEBUG)` après `config.setup_logging` dans
`src/main.py`, ou en instrumentant temporairement `src/nettcp/stream/`. À
défaut, le proxy `tools/work/proxy.py` (qui, lui, appelle
`logging.basicConfig(level='DEBUG')` en `proxy.py:34`) reste la voie la plus
rapide.

### Table de diagnostic : erreurs Kerberos

| Code | Nom | Cause probable | Remède |
|---|---|---|---|
| 6 | `KDC_ERR_C_PRINCIPAL_UNKNOWN` | Compte client absent du domaine | Vérifier le compte |
| 7 | `KDC_ERR_S_PRINCIPAL_UNKNOWN` | SPN `host/<cible>` non enregistré | `samba-tool spn add` |
| 14 | `KDC_ERR_ETYPE_NOSUPP` | Aucun etype commun client / KDC | Réactiver AES sur le compte |
| 24 | `KDC_ERR_PREAUTH_FAILED` | Mot de passe client erroné | Réauthentifier la session |
| 32 | `KRB_AP_ERR_TKT_EXPIRED` | Ticket périmé | `klist purge` puis relancer |
| 34 | `KRB_AP_ERR_REPEAT` | Rejeu détecté par le cache | Vérifier proxy / rejeu réseau |
| 37 | `KRB_AP_ERR_SKEW` | Dérive d'horloge > 5 min | `timedatectl` / `w32tm` |
| 41 | `KRB_AP_ERR_MODIFIED` | Clé de service fausse | Resynchroniser le mdp machine |

Les valeurs numériques sont celles de RFC 4120 §7.5.9. La lecture de cette
table suppose une distinction que le terrain confond souvent : les codes
`KDC_ERR_*` (6, 7, 14, 24) sont émis par le **KDC vers le client**, lors du
TGS-REQ, et ne traversent jamais le port 9389, le serveur ADWS ne les voit
pas et ne peut donc pas les journaliser. Les codes `KRB_AP_ERR_*` (32, 34,
37, 41) naissent en revanche de la validation de l'AP-REQ par l'accepteur,
donc dans `update` (`gssapi.py:125`), et se manifestent sous forme de
`samba.NTSTATUSError`. `KRB_AP_ERR_MODIFIED` (41) est le plus trompeur : il
signifie littéralement « je n'ai pas pu déchiffrer le ticket ». Sur ce
serveur, cela se produit si le mot de passe du compte machine a changé sans
que `secrets.tdb` ne soit à jour, ou si le SPN demandé est enregistré sur un
**autre** compte que celui du DC.

### Table de diagnostic : NTSTATUS remontés par gensec

| NTSTATUS | Décimal | Nom | Cause côté ADWS |
|---|---|---|---|
| `0xC0000064` | 3221225572 | `STATUS_NO_SUCH_USER` | SPN demandé absent d'AD |
| `0xC000006D` | 3221225581 | `STATUS_LOGON_FAILURE` | Échec générique du paquet |
| `0xC0000133` | 3221225779 | `STATUS_TIME_DIFFERENCE_AT_DC` | Dérive d'horloge |
| `0xC0000022` | 3221225506 | `STATUS_ACCESS_DENIED` | Secrets illisibles (pas root) |
| `0xC000000D` | 3221225485 | `STATUS_INVALID_PARAMETER` | Token malformé / tronqué |

Seul le premier est attesté par une trace réelle du dépôt
(`documentation/06-depannage.md:33-36`, qui donne `3221225572` et son
interprétation). Les quatre autres sont les correspondances NTSTATUS
standard des causes listées ; ils **n'ont pas été observés** dans les
journaux versionnés de ce projet et sont donnés à titre de grille de
lecture.

### Symptômes côté Windows et leur traduction

| Message Windows | Origine serveur | Section du dépôt |
|---|---|---|
| `The remote endpoint has terminated the transport stream` | `protocol.py:105` a rendu `False` | 06 §1 et §2 |
| `Le site distant a fermé le flux de transport` | idem, localisé | 06 §2 |
| `Unable to find a default server…` | Jamais atteint le port 9389 | 06 §7 |
| Cmdlet qui bloque jusqu'au timeout | Fault SOAP sans `RelatesTo` | 06 §6 |

Le premier symptôme est **indiscernable** entre un échec Kerberos et un
crash de handler, parce que le serveur ferme le socket dans les deux cas
sans émettre de `HandshakeError`. C'est la raison pour laquelle
`documentation/06-depannage.md:83-85` liste trois causes possibles pour un
seul message. Émettre un vrai `HandshakeError` (`negotiate.py` déclare déjà
la classe `HandshakeError`, code `0x15`, mais rien ne l'instancie)
permettrait à Windows d'afficher le HRESULT, amélioration de diagnostic
identifiée, non implémentée.

### Séquence de vérification opérationnelle

1. `sudo samba-tool spn list "$(hostname -s)$"` : le SPN `host/<fqdn>`
  doit être présent (`documentation/06-depannage.md:51`).
2. `timedatectl status` sur le DC et `w32tm /query /status` sur le
  client : écart inférieur à 5 minutes.
3. `klist purge` puis `klist` côté Windows après correction d'un SPN :
  le cache de tickets doit être vidé, sinon l'ancien ticket erroné est
  réutilisé.
4. `ss -tlnp | grep 9389` : le service écoute et tourne bien en root.
5. `sudo journalctl -u samba-adws -f` pendant la reproduction :
  chercher la présence ou l'absence de `[SECURITY] GSSAPI negotiation
  completed`.
6. En dernier recours, observer les tokens du handshake : ils sont en
  clair jusqu'au `HandshakeDone` inclus. `ADWS_LOG_LEVEL=DEBUG`
  (`config.py:46`) **ne suffit pas** (voir ci-dessus) : il faut abaisser le
  niveau du logger racine, ou passer par `tools/work/proxy.py`.

### Diagramme de séquence complet de la phase de sécurité

```text
 CLIENT Windows (WCF NetTcpBinding)          SERVEUR (python3 -m src.main)
 ==================================          =============================
   |                                                        |
   |  0x09 UpgradeRequestRecord                             |
   |  varint(21) "application/negotiate"          EN CLAIR  |
   |------------------------------------------------------->|  protocol.py:49
   |                                                        |  stocke pending_upgrade
   |                                                        |
   |  0x0A UpgradeResponseRecord (1 octet)        EN CLAIR   |
   |<-------------------------------------------------------|  protocol.py:92
   |                                                        |
   |                        [ GENSECStream installe MS-NNS ]|  protocol.py:96
   |                                                        |
   |  16 01 00 HH LL || AuthPayload                         |
   |  HandshakeInProgress, taille big-endian                |
   |  AuthPayload = InitialContextToken(SPNEGO)             |
   |                  NegTokenInit{ mechTypes,              |
   |                               mechToken = AP-REQ,      |
   |                               mechListMIC }            |
   |------------------------------------------------------->|  gssapi.py:105
   |                                                        |
   |                        start_server()                  |  gssapi.py:107
   |                        Credentials().guess()           |  gssapi.py:114
   |                        set_machine_account()           |  gssapi.py:115
   |                          -> lit secrets.tdb            |
   |                        start_mech_by_name("spnego")    |  gssapi.py:118
   |                        update(token)                   |  gssapi.py:125
   |                                                        |
   |            [ cas A : un tour de plus necessaire ]      |
   |  16 01 00 HH LL || NegTokenResp{ accept-incomplete,    |
   |                                  supportedMech,        |
   |                                  responseToken }       |
   |<-------------------------------------------------------|  gssapi.py:131
   |  16 01 00 HH LL || NegTokenResp{ mechListMIC }         |
   |------------------------------------------------------->|  gssapi.py:132
   |                                                        |
   |            [ cas B : terminal ]                        |
   |  14 01 00 HH LL || NegTokenResp{ accept-completed,     |
   |                                  responseToken=AP-REP, |
   |                                  mechListMIC }         |
   |<-------------------------------------------------------|  gssapi.py:129
   |                                                        |  _handshake_done = True
   |                                                        |  negotiate.py:83
   |                                                        |
 ============ A PARTIR D'ICI : uint32 LE + GSS wrap ============
   |                                                        |
   |  <I len> || wrap( 0x0C PreambleEndRecord )             |
   |------------------------------------------------------->|  protocol.py:133
   |                                                        |
   |  <I len> || wrap( 0x0B PreambleAckRecord )             |
   |<-------------------------------------------------------|  protocol.py:137
   |                                                        |
   |  <I len> || wrap( 0x06 varint(n) <XML binaire WCF> )   |
   |------------------------------------------------------->|  protocol.py:140
   |                                                        |  dispatcher.dispatch()
   |  <I len> || wrap( 0x06 varint(m) <XML binaire WCF> )   |
   |<-------------------------------------------------------|  protocol.py:157
   |                                                        |
   |  <I len> || wrap( 0x07 EndRecord )                     |
   |------------------------------------------------------->|  protocol.py:170
   |                                                        |
```

Deux détails de ce diagramme sont souvent manqués et méritent d'être
répétés.

- Le **`PreambleEndRecord` traverse le canal chiffré**, et il va du **client
  vers le serveur**. Contrairement à ce que son nom suggère, il n'appartient
  pas à la phase de préambule en clair : il arrive **après** le handshake,
  donc scellé. `protocol.py:133-138` le traite dans `handle_messages` (la «
  phase 3 » du code), pas dans `handle_preamble`, et y répond par un
  `PreambleAckRecord` (`0x0b`, `nmf.py:344-345`). Le client de référence
  vendoré confirme l'ordre : `src/nettcp/stream/nmf.py:37` installe
  `GSSAPIStream`, puis `:39` écrit `PreambleEndRecord` et `:41` attend
  l'acquittement ; `tools/work/proxy.py:144-148` fait la même chose côté
  proxy, en accepteur cette fois.
- Le **`0x0A UpgradeResponseRecord` est le dernier octet en clair** émis par
  le serveur. Tout ce qui suit est soit un message de handshake MS-NNS (dont
  l'`AuthPayload` est un token SPNEGO, lisible mais non exploitable), soit
  une trame de données scellée.

> **Troisième écart avec la documentation du dépôt.** Le schéma de
> `documentation/03-protocole.md:50-55` dessine `client ◄───
> PreambleEndRecord (0x0c) ───── serveur`, c'est-à-dire une émission par le
> serveur, présentée comme le signal « sécurité OK ». Le sens est inversé :
> c'est le client qui émet `0x0c` une fois le canal établi, et c'est le
> serveur qui répond `0x0b` (`protocol.py:133-137`). Le signal « sécurité OK
> » côté client, c'est le `HandshakeDone` (`0x14`), pas le
> `PreambleEndRecord`.

### Défauts latents identifiés dans la pile de sécurité

Ces points sont vérifiés dans le code et non encore corrigés. Ils sont
listés ici parce qu'ils déterminent le comportement observable en cas
d'anomalie.

| Défaut | Emplacement | Effet |
|---|---|---|
| `UpgradeProtocol` non validé | `protocol.py:84` | Tout protocole d'upgrade accepté |
| `HandshakeError` jamais émis | `protocol.py:103-105` | Windows ne reçoit aucun HRESULT |
| `negotiate` inexistant | `gssapi.py:146,156` | `AttributeError` si I/O avant handshake |
| `error = None` non gardé | `negotiate.py:70-72` | `TypeError` au lieu d'`IOError` |
| `SocketStream.read` partiel | `socket.py:34-39` | Retour court silencieux si le pair coupe |
| `setblocking(1)` annule le timeout | `socket.py:32,51` | Connexion muette bloquante sans fin |
| `stream._socket` inexistant | `protocol.py:164` | Réduction de timeout silencieusement perdue |
| `assert` sur lecture courte | `nmf.py:259` | `AssertionError` si le pair coupe net |

Le sixième et le septième se renforcent l'un l'autre et méritent le détail.
`connection.py:39` pose `settimeout(10)`, mais chaque `SocketStream.read`
avec un compte appelle `setblocking(1)` (`socket.py:32`), équivalent
documenté de `settimeout(None)` : le délai disparaît avant même la lecture
du premier octet du préambule. `protocol.py:162-166` tente ensuite de le
ramener à 2 secondes après la première réponse, via
`self.stream._socket.settimeout(2)`, mais à ce stade `self.stream` est un
`GENSECStream`, qui n'expose ni `_socket` ni `__getattr__` (le socket réel
est deux niveaux plus bas, dans le `SocketStream` enveloppé par
`NegotiateStream`). L'`AttributeError` est avalée par le `except Exception:
pass` de `protocol.py:165-166`. Résultat net : aucun des deux délais n'est
jamais actif après la phase 1, et le `except socket_timeout` de
`protocol.py:115` est du code mort.

Le troisième mérite une note : `GENSECStream.write` et `GENSECStream.read`
appellent `self.negotiate` si `client_ctx` est nul, mais `GENSECStream` ne
définit que `negotiate_server`. Ce chemin est mort en pratique
(`protocol.py:96-97` appelle toujours `negotiate_server` immédiatement après
l'instanciation), mais c'est un vestige de copie depuis `GSSAPIStream`, qui
lui possède bien `negotiate` (`gssapi.py:33`).

Enfin, un point de gouvernance de code : `src/nettcp/` et `src/wcf/` sont
des bibliothèques vendorées, explicitement exclues des normes du projet dans
`pyproject.toml` (`extend-exclude = ["tools", "src/nettcp", "src/wcf"]`,
ligne 11, et `exclude = '^src/(nettcp|wcf)/'` pour mypy, ligne 31). C'est ce
qui explique que `gssapi.py` héberge deux classes dans un même fichier, du
code commenté et des fonctions dépassant vingt lignes, en contradiction
apparente avec le §6.1 du `CLAUDE.md`. Toute réécriture de cette couche
devrait, elle, s'y conformer.

# Partie V. L’encodage XML binaire

## Pourquoi un XML binaire

Le service ADWS ne transporte pas du XML texte. Entre le cadrage .NET
Message Framing (`[MS-NMF]`, couche traitée au chapitre précédent) et
l'enveloppe SOAP 1.2 se glisse une couche de sérialisation propriétaire : le
*.NET Binary Format: XML Data Structure*, spécifié par `[MS-NBFX]`, complété
par le *.NET Binary Format: SOAP Data Structure* (`[MS-NBFS]`, la table de
chaînes prédéfinie) et par son extension de session `[MS-NBFSE]`.

Trois raisons expliquent ce choix côté Microsoft.

- **Le balisage.** Une réponse ADWS est extrêmement répétitive : les mêmes
  URI d'espaces de noms et les mêmes noms d'éléments (`Envelope`, `Header`,
  `Body`, `Action`, `MessageID`, `RelatesTo`) reviennent dans chaque
  message. `[MS-NBFS]` remplace chacune de ces chaînes par un index d'un ou
  deux octets.
- **Le re-parsing.** Un lecteur binaire n'a pas de tokenizer : il lit un
  octet de type, dont il déduit la structure et la longueur exacte de la
  charge utile.
- **Le typage.** Un `xsd:int` circule sur 4 octets, un `xsd:dateTime` sur 8,
  un GUID sur 16 ; le type est porté par l'octet de record, sans
  reconversion de texte.

Ce n'est pas une optimisation optionnelle. Le client annonce l'encodage dans
le `KnownEncodingRecord` du préambule NMF (`src/nettcp/nmf.py:321`), dont
les valeurs possibles sont énumérées en `src/nettcp/nmf.py:178` : `UTF8 =
3`, `UTF16 = 4`, `UNICODE_LITTL_ENDIAN = 5`, `MTOM = 6`, `BINARY = 7`,
`BINARY_DICT = 8`. Le module `ActiveDirectory` demande le binaire avec
dictionnaire de session ; le serveur ne négocie rien, il subit. Toute la
couche `src/wcf/` existe pour honorer ce contrat.

> `documentation/03-protocole.md` indique `encoding=BINARY_WITH_DICT (3)`
> dans son tableau de préambule. La valeur `3` correspond en réalité à
> `UTF8` dans `src/nettcp/nmf.py:179` ; la valeur du binaire avec
> dictionnaire est `8`. Le comportement du code (voir la section MS-NBFSE
> plus bas) confirme que le mode réellement pratiqué est bien `BINARY_DICT`.
> La valeur exacte de l'octet envoyé par le client n'est pas journalisée par
> ce projet : elle n'est **pas vérifiable dans le code**.

#### Gain mesuré sur ce dépôt

L'encodeur du projet a été exécuté sur une enveloppe de réponse réellement
produite par `SoapEnvelope.wrap` (`classes/soap/soap_envelope.py:33`), avec
l'action `.../transfer/GetResponse`, un `RelatesTo` de type `urn:uuid:` et
un corps réduit à
`<ad:distinguishedName>CN=Administrator,CN=Users,DC=example,DC=com</ad:distinguishedName>`
:

| Représentation | Taille | Rapport |
|---|---|---|
| XML texte minifié (sortie de `wrap`) | 1057 caractères | 100 % |
| Records MS-NBFX (`dump_records`) | 734 octets | 69 % |

Le gain est réel mais bien inférieur à ce que le format permet, pour deux
raisons propres à cette implémentation, détaillées plus loin : les sept
espaces de noms non indexés déclarés par `SoapEnvelope.NS_DECL` ne figurent
pas dans la table `[MS-NBFS]` (**451 octets** mesurés, fixes, sur chaque
enveloppe), et l'encodeur choisit systématiquement des records texte UTF-16
(`UnicodeChars*`) là où la variante UTF-8 (`Chars*`), tout aussi conforme,
suffirait, ce qui double le volume de chaque valeur textuelle latine.

## Modèle de données MS-NBFX

### Un flux, pas un arbre

Un document MS-NBFX est une **suite linéaire de records**. Il n'y a ni
en-tête de document, ni longueur globale, ni table des matières : le premier
octet du flux est déjà le type du premier record. La structure arborescente
est reconstruite par le lecteur au fil de la lecture, comme dans un flux
SAX.

Chaque record commence par **un octet de type**, suivi d'une charge utile
dont la forme est entièrement déterminée par ce type. Il n'y a pas de
longueur générique : un lecteur qui ne connaît pas un type ne peut pas le
sauter. C'est exactement le comportement de `Record.parse`
(`src/wcf/records/base.py:103`) : une boucle qui lit un octet, cherche la
classe correspondante dans la table `Record.records`
(`src/wcf/records/base.py:42`), et délègue le décodage de la charge utile à
cette classe.

Trois familles de records structurent le document :

| Famille | Plage d'octets | Nombre | Rôle |
|---|---|---|---|
| Contrôle | 0x01 – 0x03 | 3 | EndElement, Comment, Array |
| Attributs | 0x04 – 0x3F | 60 | attributs et déclarations d'espaces de noms |
| Éléments | 0x40 – 0x77 | 56 | balises ouvrantes |
| Texte | 0x80 – 0xBC (pairs) | 31 | contenu typé (nœuds texte et valeurs d'attributs) |

Comptage exécuté sur la table de correspondance après import complet du
paquet : `Record.records` contient exactement **150 entrées**, et **106**
des 256 valeurs d'octet possibles n'y figurent pas. La plage 0x78 – 0x7F
n'est utilisée par aucun record dans cette implémentation ; elle est absente
des trois modules `elements.py`, `attributes.py` et `text.py`.

### L'ordre canonique

MS-NBFX impose un ordre strict, que l'implémentation reproduit :

1. le record d'élément (nom + préfixe),
2. zéro ou plusieurs records d'attribut, immédiatement à la suite,
3. le contenu (records de texte et records d'éléments enfants),
4. un `EndElementRecord` (0x01), sauf si le dernier record de contenu
  portait le bit *WithEndElement* (voir plus bas).

Cet ordre est visible dans `ShortElementRecord.to_bytes`
(`src/wcf/records/elements.py:68`), qui sérialise son propre octet de type,
son nom, puis boucle sur `self.attributes`. Côté lecture, `Record.parse`
(`src/wcf/records/base.py:120`) rattache tout record d'attribut au dernier
élément rencontré (`last_el`), ce qui est correct **tant que** le producteur
respecte l'ordre canonique. Un attribut émis après un enfant serait
silencieusement rattaché au mauvais parent, le décodeur du projet ne détecte
pas cette violation.

### Les types dérivés

Trois primitives non-record servent de briques à tous les records.

#### MultiByteInt31

Entier non signé sur 31 bits, encodé en base 128, **petit-boutiste par
groupes de 7 bits**, le bit de poids fort de chaque octet servant de bit de
continuation (`src/wcf/datatypes.py:3`). C'est le même principe que le
`varint` de MS-NMF, mais les deux implémentations sont distinctes dans ce
dépôt (`src/nettcp/nmf.py:43` pour NMF, `src/wcf/datatypes.py:7` pour NBFX).

Algorithme d'écriture (`src/wcf/datatypes.py:7`) : tant que la valeur
dépasse 0x7F, émettre `(valeur & 0x7F) | 0x80` et décaler de 7 bits ;
émettre enfin `valeur & 0x7F`.

| Valeur | Octets | Détail |
|---|---|---|
| 0 | `00` | tient sur 7 bits |
| 1 | `01` | |
| 127 | `7F` | dernière valeur sur 1 octet |
| 128 | `80 01` | `0x80` = 0 + continuation, puis `0x01` = 1 x 128 |
| 300 | `AC 02` | `0x2C` = 44, plus `2 x 128` = 256, total 300 |
| 972 | `CC 07` | `0x4C` = 76, plus `7 x 128` = 896, total 972 |
| 16384 | `80 80 01` | 0 + 0 + `1 x 128^2` |

La valeur 972 est celle du dernier index du dictionnaire statique du projet
: tous les index de la table `[MS-NBFS]` tiennent donc sur **deux octets au
plus**.

Le décodeur (`src/wcf/datatypes.py:21`) boucle sur `range(5)`, donc lit au
maximum 5 octets, ce qui autorise 35 bits alors que la spécification n'en
définit que 31. Aucun contrôle de dépassement n'est effectué : un flux
corrompu produira un index aberrant plutôt qu'une erreur. Il ne signale pas
non plus la fin de flux prématurée (`if not b: break`, `datatypes.py:25`),
qui rend simplement la valeur partielle accumulée.

#### Utf8String

Chaîne préfixée d'un `MultiByteInt31` donnant sa longueur **en octets** (pas
en caractères), suivie des octets UTF-8 (`src/wcf/datatypes.py:34`). Exemple
vérifié : `Utf8String('Envelope').to_bytes` produit `08 45 6E 76 65 6C 6F 70
65`.

C'est la forme employée pour tous les noms d'éléments, noms d'attributs et
préfixes littéraux.

#### Decimal

Structure `DECIMAL`.NET sur 16 octets, reproduite par
`src/wcf/datatypes.py:55` :

| Champ | Taille | Contenu |
|---|---|---|
| réservé | 2 octets | toujours `00 00` à l'écriture |
| scale | 1 octet | exposant décimal, 0 à 28 (contrôlé ligne 57) |
| sign | 1 octet | `0x80` si négatif, `0x00` sinon |
| high | 4 octets LE | bits 64 à 95 de la mantisse |
| low | 8 octets LE | bits 0 à 63 de la mantisse |

La valeur est `(high x 2^64 + low) / 10^scale`, éventuellement niée
(`src/wcf/datatypes.py:74`). Exemple vérifié : `Decimal(False, 0, 1337, 3)`
sérialise en `00 00 03 00 00 00 00 00 39 05 00 00 00 00 00 00` et se relit
`1.337`.

### Ce que MS-NBFX ne transporte pas

Le format ne code que l'*infoset* utile. Sont absents du modèle :

- la déclaration XML (`<?xml version="1.0" encoding="utf-8"?>`) : elle est
  produite par `SoapEnvelope.wrap` (`classes/soap/soap_envelope.py:35`) puis
  **perdue** à l'encodage, ce qui est conforme et sans conséquence ;
- les instructions de traitement et les DTD ;
- les sections CDATA en tant que telles : leur contenu devient du texte
  ordinaire ;
- l'espace blanc non significatif entre éléments.

## Records de structure : éléments, attributs, espaces de noms

### Records d'élément

Quatre formes générales, plus deux familles de 26 raccourcis par lettre de
préfixe. Toutes sont définies dans `src/wcf/records/elements.py`.

| Record | Octet | Charge utile | Référence |
|---|---|---|---|
| `ShortElementRecord` | 0x40 | `Utf8String` nom | `elements.py:60` |
| `ElementRecord` | 0x41 | `Utf8String` préfixe, puis nom | `elements.py:108` |
| `ShortDictionaryElementRecord` | 0x42 | `MultiByteInt31` index | `elements.py:150` |
| `DictionaryElementRecord` | 0x43 | `Utf8String` préfixe, puis index | `elements.py:195` |
| `PrefixDictionaryElement[A-Z]` | 0x44 – 0x5D | `MultiByteInt31` index | `elements.py:321` |
| `PrefixElement[A-Z]` | 0x5E – 0x77 | `Utf8String` nom | `elements.py:337` |

Les deux familles préfixées sont **générées dynamiquement** par deux boucles
`for c in range(...)` qui fabriquent 26 sous-classes chacune via `type`
(`elements.py:321-335` et `elements.py:337-351`). La lettre du préfixe se
déduit de l'octet : `chr(c - 0x44 + ord('a'))` pour la première famille,
`chr(c - 0x5E + ord('a'))` pour la seconde. Le préfixe est donc toujours
**une seule lettre minuscule** : c'est la raison pour laquelle les
conventions de préfixe des messages WCF privilégient des noms d'une lettre.
Sur les enveloppes produites par ce dépôt, seuls `s` et `a` empruntent
effectivement ces raccourcis ; la fréquence des autres lettres dans le
trafic entrant Windows n'a **pas été mesurée** sur ce projet.

`ShortElementRecord.__init__` refuse le nom `xmlns` par une **assertion**
(`elements.py:64`, `assert name != 'xmlns'`) : une déclaration d'espace de
noms n'est jamais un élément, elle possède ses propres records. Cette garde
disparaît sous `python3 -O`, qui désactive les `assert` ; elle ne constitue
donc pas une validation d'entrée fiable.

### Records d'attribut

| Record | Octet | Charge utile | Référence |
|---|---|---|---|
| `ShortAttributeRecord` | 0x04 | nom `Utf8String`, puis record texte | `attributes.py:53` |
| `AttributeRecord` | 0x05 | préfixe, nom, record texte | `attributes.py:92` |
| `ShortDictionaryAttributeRecord` | 0x06 | index, record texte | `attributes.py:136` |
| `DictionaryAttributeRecord` | 0x07 | préfixe, index, record texte | `attributes.py:177` |
| `ShortXmlnsAttributeRecord` | 0x08 | URI `Utf8String` | `attributes.py:295` |
| `XmlnsAttributeRecord` | 0x09 | préfixe `Utf8String`, URI `Utf8String` | `attributes.py:327` |
| `ShortDictionaryXmlnsAttributeRecord` | 0x0A | index de l'URI | `attributes.py:222` |
| `DictionaryXmlnsAttributeRecord` | 0x0B | préfixe, index de l'URI | `attributes.py:256` |
| `PrefixDictionaryAttribute[A-Z]` | 0x0C – 0x25 | index, record texte | `attributes.py:431` |
| `PrefixAttribute[A-Z]` | 0x26 – 0x3F | nom `Utf8String`, record texte | `attributes.py:447` |

Deux points essentiels :

- **La valeur d'un attribut est elle-même un record de texte.**
  `ShortAttributeRecord` ne stocke pas une chaîne mais un objet `Text`
  (`attributes.py:57`), qu'il sérialise par `self.value.to_bytes`
  (`attributes.py:66`) et dont l'octet de type est relu récursivement à
  l'analyse (`attributes.py:86`). Une valeur `"1"` coûte donc **un seul
  octet** : `0x82`, le `OneTextRecord`, vérifié sur le dump de l'exemple
  complet, segment `1E 00 82`.
- **Les records `xmlns*` n'ont pas de valeur texte.** L'URI est soit un
  `Utf8String` littéral, soit un index de dictionnaire. Il n'y a **aucune**
  famille `PrefixDictionaryXmlns[A-Z]` ni `PrefixXmlns[A-Z]` : ni MS-NBFX ni
  cette implémentation ne définissent de raccourci par lettre pour les
  déclarations d'espaces de noms. Le préfixe d'une déclaration `xmlns:x` est
  toujours écrit en clair sous forme de `Utf8String` (`attributes.py:271`
  pour la variante indexée, `attributes.py:340` pour la variante littérale).

### Table exhaustive des raccourcis par lettre

Les quatre familles générées couvrent exactement les 26 lettres `a` à `z`,
sans trou.

| Lettre | PrefixDictionaryElement | PrefixElement | PrefixDictionaryAttribute | PrefixAttribute |
|---|---|---|---|---|
| a | 0x44 | 0x5E | 0x0C | 0x26 |
| b | 0x45 | 0x5F | 0x0D | 0x27 |
| c | 0x46 | 0x60 | 0x0E | 0x28 |
| d | 0x47 | 0x61 | 0x0F | 0x29 |
| e | 0x48 | 0x62 | 0x10 | 0x2A |
| f | 0x49 | 0x63 | 0x11 | 0x2B |
| g | 0x4A | 0x64 | 0x12 | 0x2C |
| h | 0x4B | 0x65 | 0x13 | 0x2D |
| i | 0x4C | 0x66 | 0x14 | 0x2E |
| j | 0x4D | 0x67 | 0x15 | 0x2F |
| k | 0x4E | 0x68 | 0x16 | 0x30 |
| l | 0x4F | 0x69 | 0x17 | 0x31 |
| m | 0x50 | 0x6A | 0x18 | 0x32 |
| n | 0x51 | 0x6B | 0x19 | 0x33 |
| o | 0x52 | 0x6C | 0x1A | 0x34 |
| p | 0x53 | 0x6D | 0x1B | 0x35 |
| q | 0x54 | 0x6E | 0x1C | 0x36 |
| r | 0x55 | 0x6F | 0x1D | 0x37 |
| s | 0x56 | 0x70 | 0x1E | 0x38 |
| t | 0x57 | 0x71 | 0x1F | 0x39 |
| u | 0x58 | 0x72 | 0x20 | 0x3A |
| v | 0x59 | 0x73 | 0x21 | 0x3B |
| w | 0x5A | 0x74 | 0x22 | 0x3C |
| x | 0x5B | 0x75 | 0x23 | 0x3D |
| y | 0x5C | 0x76 | 0x24 | 0x3E |
| z | 0x5D | 0x77 | 0x25 | 0x3F |

Deux repères mnémotechniques pour lire un dump à l'oeil nu : `0x56` est
`<s:` + nom de dictionnaire (le préfixe SOAP), `0x44` est `<a:` + nom de
dictionnaire (le préfixe WS-Addressing). Ces deux octets ouvrent la
quasi-totalité des messages ADWS.

### Règles de choix appliquées par l'encodeur du projet

`XMLParser._parse_tag` (`src/wcf/xml2records.py:75`) applique l'arbre de
décision suivant, dans cet ordre :

- nom qualifié avec préfixe **d'une seule lettre** :
 - nom local présent dans le dictionnaire →
   `PrefixDictionaryElement<L>Record` ;
 - sinon → `PrefixElement<L>Record`.
- nom qualifié avec préfixe **de plusieurs lettres** :
 - nom local dans le dictionnaire → `DictionaryElementRecord` ;
 - sinon → `ElementRecord`.
- nom sans préfixe :
 - dans le dictionnaire → `ShortDictionaryElementRecord` ;
 - sinon → `ShortElementRecord`.

`XMLParser._parse_attr` (`src/wcf/xml2records.py:183`) suit la même logique,
avec une branche dédiée aux déclarations : `xmlns:x` donne
`DictionaryXmlnsAttributeRecord` ou `XmlnsAttributeRecord` selon que l'URI
est indexée, `xmlns` nu donne les variantes `Short*`.

Conséquence directe et mesurable : les préfixes ADWS multi-lettres (`ad`,
`da`, `addata`, `adlq`, `wsen`, `wst`, `ca`, `xsi`, `xsd`, déclarés dans la
table `ENV_NS_MAP` de `src/soap/namespaces.py:18`) **ne bénéficient jamais**
des raccourcis 0x44-0x5D. Chaque balise `<addata:cn>` transporte donc 7
octets rien que pour le préfixe (1 octet de longueur `MultiByteInt31` plus
les 6 octets UTF-8 de `addata`), auxquels s'ajoutent le nom local et l'octet
de type. C'est un axe d'optimisation identifié pour la phase 5, sans risque
d'interopérabilité : le choix du préfixe est libre du côté émetteur, seul
l'URI d'espace de noms fait foi.

### EndElement, Comment, Array

| Record | Octet | Statut dans ce projet |
|---|---|---|
| `EndElementRecord` | 0x01 | implémenté, émis et lu |
| `CommentRecord` | 0x02 | lu ; **jamais émis** |
| `ArrayRecord` | 0x03 | lu ; **jamais émis** |

**`EndElementRecord`** (`src/wcf/records/base.py:151`) ne porte aucune
charge utile : c'est l'octet `0x01` seul. Il ferme le dernier élément
ouvert. À la lecture (`base.py:110`) il provoque un `parents.pop`, donc un
retour d'un niveau ; il n'est pas ajouté à l'arbre. À l'écriture,
`dump_records` (`src/wcf/records/__init__.py:117`) en émet un après les
enfants d'un élément **sauf** si le dernier enfant était un record de texte
(auquel cas c'est le bit *WithEndElement* qui a fait le travail).

**`CommentRecord`** (`base.py:155`) porte un `Utf8String`. Le décodage
fonctionne : `b'\x02\x05hello'` se relit `<!-- hello -->`. L'encodage est en
revanche **hors d'atteinte** : `XMLParser.handle_comment`
(`src/wcf/xml2records.py:274`) référence une variable `data` non définie et
lèverait un `NameError`, mais la question ne se pose pas car le parseur
Expat de `src/wcf/html_parser.py:27` n'enregistre que `StartElementHandler`,
`EndElementHandler` et `CharacterDataHandler` : aucun `CommentHandler` n'est
posé, donc les commentaires du XML sortant sont silencieusement ignorés.
Sans conséquence : le serveur ne produit pas de commentaires.

**`ArrayRecord`** (`base.py:184`) encode une répétition homogène : un record
d'élément modèle, ses attributs, un `EndElement`, l'octet du type de texte
répété (toujours la variante *WithEndElement*, cf. la table `datatypes` de
`base.py:187`), un `MultiByteInt31` de cardinalité, puis les charges utiles
concaténées **sans leur octet de type** (`base.py:228`). Vérification
effectuée :

```text
03 40 04 69 74 65 6D 01 8D 02 01 00 00 00 02 00 00 00
 |  |___________________|  |  |  |___________|___________|
 |          |             |  |        deux Int32 bruts
 |          |             |  cardinalite = 2
 |          |             type repete 0x8D = Int32TextWithEndElement
 |          ShortElement "item" + EndElement
 ArrayRecord
```

Ce flux se relit `<item>1</item><item>2</item>`. Deux limites relevées : le
paramètre `attributes` de `ArrayRecord.__init__` est reçu puis **écrasé**
par une liste vide (`base.py:211`), donc les attributs d'un tableau reçu
sont perdus au décodage ; et l'encodeur du projet ne produit jamais de
tableau, ce qui est conforme mais laisse la compaction des grosses listes
d'attributs multi-valués inexploitée.

> Le décodeur ne signale pas les octets inconnus : `Record.parse` se
> contente d'un `log.warn('type 0x%x not found')`
> (`src/wcf/records/base.py:134`) et **poursuit** la lecture à l'octet
> suivant. Un flux désaligné produit donc du XML plausible mais faux, et non
> une erreur franche. C'est le premier réflexe à avoir face à une réponse
> incohérente.

## Records de texte : catalogue des types primitifs

### La convention de l'octet impair

C'est la règle la plus importante du format, et la plus facile à manquer.

Tous les records de texte occupent une valeur **paire** entre 0x80 et 0xBC.
La valeur **impaire immédiatement supérieure** (`type + 1`) désigne le
*même* record, avec la même charge utile, suivi d'un `EndElement` implicite.
`[MS-NBFX]` les nomme `<Type>WithEndElement` : `Chars8Text` = 0x98,
`Chars8TextWithEndElement` = 0x99.

Cela économise un octet par élément feuille, soit, sur une réponse ADWS qui
contient plusieurs centaines de `<ad:value>`, plusieurs centaines d'octets.

L'implémentation ne crée **pas** de classes distinctes pour les variantes
impaires. Elle traite la convention aux deux extrémités :

- **En lecture** (`src/wcf/records/base.py:125`) : si l'octet lu n'est pas
  dans la table `Record.records`, le décodeur essaie `type - 1`. Si cette
  classe existe, il l'utilise pour décoder la charge utile, puis exécute un
  `parents.pop`, exactement l'effet d'un `EndElement`.
- **En écriture** (`src/wcf/records/__init__.py:104`) : `dump_records`
  incrémente `r.type` de 1 lorsque `r` est le **dernier** record d'une liste
  de frères **et** que c'est un `Text`.

Cette convention est non ambiguë uniquement dans la plage 0x80-0xBD, où
seuls les octets pairs sont attribués. Dans les plages de structure
(0x01-0x77), les octets pairs et impairs sont tous deux attribués à des
records distincts : `0x41` n'est pas `0x40 WithEndElement`, c'est
`ElementRecord`. Le test `type - 1 in Record.records` n'est donc jamais
atteint pour ces octets-là, puisqu'ils sont trouvés dès la première branche.

> **Un faux positif vérifié.** Le repli `type - 1` n'est pas restreint à la
> plage texte : il s'applique à tout octet absent de la table. Énumération
> exhaustive des 256 valeurs, exécutée sur `Record.records` : 32 octets non
> attribués ont leur prédécesseur attribué, dont 31 sont les variantes texte
> *WithEndElement* légitimes (0x81, 0x83,..., 0xBD), et **un seul** est une
> aberration : `0x78`, dont le prédécesseur `0x77` est
> `PrefixElementZRecord`. Un octet `0x78` reçu, qui n'est défini par aucun
> record, est donc silencieusement décodé comme un `PrefixElementZRecord`
> suivi d'un `EndElement`, et le décodeur consomme derrière lui un
> `Utf8String` qui n'existe pas. Les 74 autres octets non attribués (0x00,
> 0x79-0x7F, 0xBE-0xFF) tombent bien dans la branche d'avertissement.

> **Défaut vérifié : `dump_records` n'est pas idempotent.** L'incrémentation
> de `src/wcf/records/__init__.py:105` mute l'objet en place. Encoder deux
> fois le même arbre donne deux résultats différents : sur l'enveloppe de
> test, le premier appel produit `... B7 02 78 00...`
> (`UnicodeChars8TextWithEndElement`), le second produit `... B8 02 78
> 00...`, soit `UnicodeChars16Text`, dont la longueur se lit sur 2 octets.
> Le message devient illisible pour le client. Un arbre de records est donc
> à usage unique ; il ne doit jamais être mis en cache et réémis.

### Catalogue exhaustif

Les 31 records de texte définis dans `src/wcf/records/text.py`, dans l'ordre
des octets. La colonne « +EE » donne la variante *WithEndElement*.

| Record | Octet | +EE | Charge utile | Type XSD |
|---|---|---|---|---|
| `ZeroTextRecord` | 0x80 | 0x81 | aucune | `xsd:int` (valeur 0) |
| `OneTextRecord` | 0x82 | 0x83 | aucune | `xsd:int` (valeur 1) |
| `FalseTextRecord` | 0x84 | 0x85 | aucune | `xsd:boolean` |
| `TrueTextRecord` | 0x86 | 0x87 | aucune | `xsd:boolean` |
| `Int8TextRecord` | 0x88 | 0x89 | 1 octet signé | `xsd:byte` |
| `Int16TextRecord` | 0x8A | 0x8B | 2 octets LE signés | `xsd:short` |
| `Int32TextRecord` | 0x8C | 0x8D | 4 octets LE signés | `xsd:int` |
| `Int64TextRecord` | 0x8E | 0x8F | 8 octets LE signés | `xsd:long` |
| `FloatTextRecord` | 0x90 | 0x91 | 4 octets IEEE 754 | `xsd:float` |
| `DoubleTextRecord` | 0x92 | 0x93 | 8 octets IEEE 754 | `xsd:double` |
| `DecimalTextRecord` | 0x94 | 0x95 | 16 octets DECIMAL | `xsd:decimal` |
| `DatetimeTextRecord` | 0x96 | 0x97 | 8 octets, 62 bits ticks | `xsd:dateTime` |
| `Chars8TextRecord` | 0x98 | 0x99 | 1 octet longueur, UTF-8 | `xsd:string` |
| `Chars16TextRecord` | 0x9A | 0x9B | 2 octets longueur, UTF-8 | `xsd:string` |
| `Chars32TextRecord` | 0x9C | 0x9D | 4 octets longueur, UTF-8 | `xsd:string` |
| `Bytes8TextRecord` | 0x9E | 0x9F | 1 octet longueur, binaire | `xsd:base64Binary` |
| `Bytes16TextRecord` | 0xA0 | 0xA1 | 2 octets longueur, binaire | `xsd:base64Binary` |
| `Bytes32TextRecord` | 0xA2 | 0xA3 | 4 octets longueur, binaire | `xsd:base64Binary` |
| `StartListTextRecord` | 0xA4 | 0xA5 | aucune | ouverture de liste |
| `EndListTextRecord` | 0xA6 | 0xA7 | aucune | fermeture de liste |
| `EmptyTextRecord` | 0xA8 | 0xA9 | aucune | chaîne vide |
| `DictionaryTextRecord` | 0xAA | 0xAB | `MultiByteInt31` index | `xsd:string` |
| `UniqueIdTextRecord` | 0xAC | 0xAD | 16 octets GUID | `urn:uuid:` |
| `TimeSpanTextRecord` | 0xAE | 0xAF | 8 octets LE signés | `xsd:duration` |
| `UuidTextRecord` | 0xB0 | 0xB1 | 16 octets GUID | `xsd:guid` |
| `UInt64TextRecord` | 0xB2 | 0xB3 | 8 octets LE non signés | `xsd:unsignedLong` |
| `BoolTextRecord` | 0xB4 | 0xB5 | 1 octet 0 ou 1 | `xsd:boolean` |
| `UnicodeChars8TextRecord` | 0xB6 | 0xB7 | 1 octet longueur, UTF-16LE | `xsd:string` |
| `UnicodeChars16TextRecord` | 0xB8 | 0xB9 | 2 octets longueur, UTF-16LE | `xsd:string` |
| `UnicodeChars32TextRecord` | 0xBA | 0xBB | 4 octets longueur, UTF-16LE | `xsd:string` |
| `QNameDictionaryTextRecord` | 0xBC | 0xBD | 1 octet préfixe, 3 octets index | `xsd:QName` |

Les longueurs des records `Chars*`, `Bytes*` et `UnicodeChars*` sont
exprimées **en octets**, jamais en caractères :
`UnicodeChars8TextRecord.to_bytes` (`src/wcf/records/text.py:284`) encode
d'abord en UTF-16LE puis compte les octets obtenus. Une chaîne latine de 58
caractères occupe donc 116 octets et tient tout juste dans la variante 8
bits.

Trois records ne définissent ni `to_bytes`, ni `parse`, ni `__str__` :
`StartListTextRecord` (`text.py:824`), `EndListTextRecord` (`text.py:828`)
et `EmptyTextRecord` (`text.py:832`). Leurs corps de classe se réduisent à
la ligne `type = 0x..`. Ils héritent donc de `Record.to_bytes`
(`base.py:58`), qui émet l'octet nu, et de `Record.parse` (`base.py:96`),
qui renvoie `cls` sans rien consommer : sur ces deux points le comportement
est correct.

> **Défaut vérifié : rendu textuel absent.** Ces trois classes n'ayant pas
> de `__str__`, `str(record)` retombe sur `Record.__repr__` (`base.py:70`).
> Contrôle exécuté sur le flux `40 04 74 65 73 74 A9 01`, soit `<test>`
> suivi d'un `EmptyTextWithEndElement` : `print_records` produit
> `<test><EmptyTextRecord(type=0xA8)></test>` au lieu de `<test></test>`.
> Même symptôme pour `A4`/`A6`, qui donnent
> `<StartListTextRecord(type=0xA4)>` et `<EndListTextRecord(type=0xA6)>`. Le
> XML texte intermédiaire est alors invalide au sens de l'infoset attendu,
> et le nom de classe se retrouve interprété comme un élément par
> `ET.fromstring`. Le défaut est **latent** : l'encodeur ne produit jamais
> ces records, `_store_data` (`src/wcf/xml2records.py:109`) écarte
> explicitement les `EmptyTextRecord`, et le module `ActiveDirectory` de
> PowerShell n'en émet pas non plus dans les échanges observés sur ce dépôt.
> Il se réveillerait avec un client utilisant les listes typées de
> `[MS-NBFX]`.

### Correction du tableau de la documentation existante

Le tableau « type XSD vers record » de `documentation/03-protocole.md:89-94`
contient trois erreurs, relevées par confrontation directe avec
`src/wcf/records/text.py`. Elles sont reproduites ci-dessous avec leur
valeur exacte, afin qu'un lecteur qui partirait de l'ancienne documentation
ne cherche pas un record inexistant dans un dump.

| Ligne | Affirmation de `03-protocole.md` | Valeur exacte |
|---|---|---|
| 89 | `Int32TextRecord` = 0x88 | 0x88 est `Int8TextRecord` ; `Int32` = **0x8C** |
| 90 | `Int64TextRecord` = 0x8a | 0x8A est `Int16TextRecord` ; `Int64` = **0x8E** |
| 94 | `GuidTextRecord` (0xb0) | la classe s'appelle **`UuidTextRecord`** ; 0xB0 est juste |

Seule la troisième est bénigne : l'octet est correct, seul le nom de classe
est erroné (`text.py:716`). Les deux premières décalent la lecture d'un dump
de plusieurs octets, puisque `Int8` consomme 1 octet de charge utile là où
`Int32` en consomme 4.

### Records réellement produits par l'encodeur

Le catalogue ci-dessus décrit ce que le **décodeur** sait lire.
L'**encodeur** de ce projet, lui, n'emprunte qu'un sous-ensemble : recherche
exhaustive des instanciations dans `src/wcf/xml2records.py`.

| Record | Lu | Émis | Déclencheur à l'encodage |
|---|---|---|---|
| `Zero`, `One` | oui | oui | texte `0` ou `1` |
| `False`, `True` | oui | oui | `false` / `true`, insensible à la casse |
| `Int8/16/32/64`, `UInt64` | oui | oui | `int_reg`, par plage de valeur |
| `Double` | oui | oui | `float_reg` |
| `Float` | oui | **non** | aucun |
| `Decimal` | oui | **non** | aucun |
| `Datetime` | oui | oui | `datetime_reg` |
| `TimeSpan` | oui | **non** | aucun |
| `Chars8/16/32` | oui | **non** | aucun |
| `UnicodeChars8/16/32` | oui | oui | repli textuel |
| `Bytes8/16/32` | oui | oui | heuristique base64 |
| `Dictionary` | oui | oui | chaîne présente dans `inverted_dict` |
| `UniqueId`, `Uuid` | oui | oui | `urn:uuid:` / GUID nu |
| `QNameDictionary` | oui | oui | `x:` + nom de dictionnaire |
| `Bool` | oui | **non** | aucun (`true`/`false` passent par `TrueText`) |
| `StartList`, `EndList` | oui | **non** | aucun |
| `EmptyText` | oui | **non** | construit puis écarté (`xml2records.py:109`) |
| `Comment` | oui | **non** | aucun handler Expat de commentaire |
| `Array` | oui | **non** | aucun |

### Encodages particuliers

#### DateTime : ticks .NET et DateTimeKind

Une valeur `xsd:dateTime` est un entier 64 bits little-endian dont :

- les **62 bits de poids faible** portent le nombre de *ticks*, un tick
  valant 100 ns, comptés depuis `0001-01-01T00:00:00` ;
- les **2 bits de poids fort** portent le `DateTimeKind`.NET.

L'écriture est faite en une expression (`src/wcf/records/text.py:559`) :
`((self.tz & 3) << 62) | (self.value & 0x3FFFFFFFFFFFFFFF)`, empaquetée en
`<Q`. La lecture inverse (`text.py:575-576`) : `tz = data >> 62`, `value =
data & 0x3FFFFFFFFFFFFFFF`.

| Valeur de `tz` | Signification | Émis par ce projet pour |
|---|---|---|
| 0 | `Unspecified` | horodatage sans suffixe |
| 1 | `Utc` | suffixe `Z` |
| 2 | `Local` | décalage explicite `+hh:mm` / `-hh:mm` |
| 3 | non utilisé | jamais produit |

La détection du suffixe est faite par `_parse_datetime_to_ticks`
(`src/wcf/xml2records.py:29`) : `Z` final donne `tz = 1` ; une chaîne d'au
moins 6 caractères dont le sixième en partant de la fin (`head[-6]`) est `+`
ou `-` et dont le troisième en partant de la fin (`head[-3]`) est `:` donne
`tz = 2` ; sinon `tz = 0` (`xml2records.py:32-37`). La conversion en ticks
utilise la constante `_DOTNET_EPOCH_OFFSET_SECONDS = 62135596800`
(`src/wcf/xml2records.py:26`), soit le nombre de secondes entre `0001-01-01`
et l'époque Unix.

Exemple entièrement vérifié, `2026-08-07T10:00:00Z` :

```text
secondes Unix                    = 1786096800
+ 62135596800 (decalage epoque)  = 63921693600
x 10 000 000 (ticks/seconde)     = 639216936000000000  = 0x08DEF46AA4B19000
| (1 << 62)  (DateTimeKind=Utc)                        = 0x48DEF46AA4B19000

octets emis : 96 00 90 B1 A4 6A F4 DE 48
              |  |____________________|
              |     0x48DEF46AA4B19000 en little-endian
              DatetimeTextRecord
```

Trois bornes utiles, tirées des doctests du module : `0` tick vaut
`0001-01-01T00:00:00` (`text.py:541`), `621355968000000000` ticks valent
`1970-01-01T00:00:00`, donc l'époque Unix (`text.py:539`), et la charge
utile `FF 3F 37 F4 75 28 CA 2B`, soit `0x2BCA2875F4373FFF` en
petit-boutiste, vaut `9999-12-31T23:59:59.999999` (`text.py:567`).

> **Écart vérifié.** `DatetimeTextRecord.__str__` (`text.py:537`) ignore
> `self.tz` : il reconstruit la date à partir des seuls ticks et rend un ISO
> 8601 **sans suffixe**. Une requête client portant `2026-08-07T10:00:00Z`
> est donc restituée `2026-08-07T10:00:00` au XML texte intermédiaire, et la
> couche `classes/parsing/` ne voit jamais le `Z`. Contrôle exécuté sur un
> aller-retour complet `<a:V>2026-08-07T10:00:00Z</a:V>` : le record émis
> est bien un `0x97` (`DatetimeTextWithEndElement`) porteur de `tz = 1`,
> mais la relecture par `print_records` rend
> `<a:V>2026-08-07T10:00:00</a:V>`. Le chemin d'écriture (serveur vers
> client) est donc correct sur le fil : le défaut est purement dans le rendu
> textuel, et unidirectionnel. Second écart, même méthode :
> `datetime.timedelta(microseconds=ticks // 10)` perd les ticks non
> multiples de 10, soit une résolution ramenée de 100 ns à 1 microseconde.
> Sans impact sur les attributs AD, dont la granularité utile est la
> seconde.

#### TimeSpan

Entier signé 64 bits little-endian, en ticks de 100 ns, écrit tel quel
(`src/wcf/records/text.py:847`).

> **Défaut vérifié.** `TimeSpanTextRecord.__str__` (`text.py:851`) calcule
> `datetime.timedelta(milliseconds=self.value / 10)`. Or `value / 10` est un
> nombre de **microsecondes**, pas de millisecondes : le rendu est mille
> fois trop grand. Contrôle exécuté : `TimeSpanTextRecord(36000000000)`, qui
> vaut exactement une heure (3600 x 10^7 ticks), s'affiche `41 days,
> 16:00:00`. La correction est le remplacement du mot-clef par
> `microseconds=`. Le doctest du module encode l'erreur au lieu de la
> détecter : `text.py:857-859` affirme que la charge utile `00 51 25 02 00
> 00 00 00`, soit 36 000 000 ticks (3,6 secondes) se rend `1:00:00`. Le
> défaut est **latent** dans ce projet : aucun chemin de code n'émet ni ne
> consomme de `TimeSpan` ADWS, et l'encodeur `_parse_data` ne produit jamais
> ce record.

#### UniqueId, Uuid et l'ordre des octets

Les deux records portent 16 octets, mais dans l'ordre **`bytes_le`** de
.NET, pas dans l'ordre canonique de la RFC 4122 : les trois premiers champs
du GUID (`time_low` sur 4 octets, `time_mid` sur 2, `time_hi_and_version`
sur 2) sont petit-boutistes, les deux derniers (`clock_seq` sur 2, `node`
sur 6) sont gros-boutistes. L'implémentation délègue à Python : écriture
`self.uuid.bytes_le` (`text.py:692`), lecture `cls(bytes_le=u)`
(`text.py:713`).

Exemple vérifié, tiré du test unitaire `text.py:688` :

```text
GUID textuel : 33221100-5544-7766-8899-aabbccddeeff

octets emis  : 00 11 22 33 | 44 55 | 66 77 | 88 99 | aa bb cc dd ee ff
               |__________|  |____|  |____|  |____|  |________________|
               time_low LE   mid LE  hi LE   clock_seq et node, tels quels
```

La différence entre les deux records est purement lexicale, portée par
`__str__` : `UniqueIdTextRecord` rend la forme URN `urn:uuid:33221100-...`
(`text.py:701`), `UuidTextRecord` rend la forme nue `33221100-...`
(`text.py:724`). Les octets sont identiques. C'est exactement la distinction
dont ADWS a besoin : `<a:MessageID>` et `<a:RelatesTo>` sont des URN, tandis
que `<ad:objectReferenceProperty>` porte un GUID nu, vérifié dans les
handlers, par exemple `classes/handlers/create.py:85`.

#### QNameDictionaryText

Format compact pour un nom qualifié dont le préfixe est une lettre et le nom
local est dans le dictionnaire : un octet donnant le rang de la lettre
(`ord(prefix) - ord('a')`, donc `0` pour `a`), puis **trois octets
gros-boutistes** pour l'index, et non un `MultiByteInt31`
(`src/wcf/records/text.py:382-385` à l'écriture, `text.py:404-405` à la
lecture). Vérifié : `QNameDictionaryTextRecord('b', 2)` produit `BC 01 00 00
02` et se relit `b:Envelope`. Corollaire : l'index d'un QName est plafonné à
2^24 - 1 et coûte toujours 3 octets, même pour `Envelope` dont l'index vaut
2.

C'est le seul endroit du format où un index de dictionnaire n'est pas encodé
en `MultiByteInt31`, un piège classique lors de l'écriture d'un décodeur.

#### Chars contre UnicodeChars

Les deux familles codent une chaîne ; `Chars*` en UTF-8 (`text.py:604`),
`UnicodeChars*` en UTF-16LE (`text.py:284`). `[MS-NBFX]` définit les deux et
laisse le choix à l'émetteur ; un lecteur conforme doit accepter les deux.
Le choix ne change que le volume.

| Critère | `Chars8/16/32` | `UnicodeChars8/16/32` |
|---|---|---|
| Octets | 0x98 / 0x9A / 0x9C | 0xB6 / 0xB8 / 0xBA |
| Encodage | UTF-8 | UTF-16LE |
| Longueur préfixée | 1 / 2 / 4 octets | 1 / 2 / 4 octets |
| Coût d'un caractère latin | 1 octet | 2 octets |
| Émis par cet encodeur | jamais | toujours |
| Échappement XML au rendu | oui (`escape`) | non |

> **Choix de cette implémentation.** `XMLParser._parse_data`
> (`src/wcf/xml2records.py:175`) utilise systématiquement
> `UnicodeChars8/16/32` comme repli textuel. Aucun chemin de l'encodeur ne
> produit de `Chars8/16/32TextRecord`, vérifié par recherche exhaustive des
> instanciations dans `src/wcf/xml2records.py`. Toute valeur d'annuaire
> sortante est donc transmise en UTF-16 : c'est correct, mais représente le
> double du volume nécessaire pour du texte latin. `[MS-NBFX]` n'impose ni
> ne recommande l'une des deux familles ; la répartition réelle `Chars*` /
> `UnicodeChars*` dans le trafic entrant Windows **n'a pas été mesurée sur
> une capture de ce dépôt** et ne doit pas être affirmée. Piste de phase 5,
> sans risque d'interopérabilité.

> **Défaut vérifié dans le sens du décodage.** L'échappement XML n'est
> appliqué que par `Chars8TextRecord.__str__` (`text.py:597`, via la
> fonction `escape` de `text.py:54`), dont héritent `Chars16` et `Chars32`.
> Les `UnicodeChars*` rendent leur valeur brute (`text.py:295`). Contrôle
> exécuté sur la chaîne `a<b&c` : `Chars8TextRecord` rend `a&lt ;b&amp ;c`,
> `UnicodeChars8TextRecord` rend `a<b&c`, ce dernier casse le XML texte
> intermédiaire et fait échouer `ET.fromstring` dans
> `classes/parsing/context.py:40`. Le défaut reste sans effet tant que le
> client n'émet pas de `UnicodeChars*` porteur de `<`, `>` ou `&` ; il
> n'existe **aucune preuve dans ce dépôt** que ce cas ne se produise jamais,
> seulement l'absence d'incident journalisé. Le périmètre de `escape`
> lui-même a déjà été corrigé une fois, cf. `documentation/06-depannage.md`
> section 9 : la table `_XML_ENTITY_BY_CP` (`text.py:47`) ne mappe plus que
> `<`, `>`, `&` et `"`, laissant les caractères accentués littéraux.

> **Défaut latent, décodage UTF-16.** `UnicodeChars8TextRecord.parse`
> (`text.py:307`) appelle `data.decode('utf-16')` et non `utf-16le`. Une
> charge utile commençant par `FF FE` est alors interprétée comme un BOM et
> consommée. Contrôle exécuté : la chaîne `U+FEFF` suivie de `abc` s'encode
> `B6 08 FF FE 61 00 62 00 63 00` et se relit `abc`, le caractère de tête
> est perdu. Cas de figure marginal pour de l'annuaire AD.

#### Heuristique de typage à l'encodage et effet base64

`XMLParser._parse_data` (`src/wcf/xml2records.py:117`) déduit le record de
texte de la **forme** de la chaîne, jamais d'un type déclaré. L'ordre des
tests est celui de la chaîne `if`/`elif` des lignes 127 à 172 ; le repli
textuel des lignes 175 à 181 est atteint lorsqu'aucune branche n'a rendu de
valeur.

| Rang | Test | Ligne | Record produit |
|---|---|---|---|
| 1 | `data == '0'` | 127 | `ZeroTextRecord` |
| 2 | `data == '1'` | 129 | `OneTextRecord` |
| 3 | `data.lower == 'false'` | 131 | `FalseTextRecord` |
| 4 | `data.lower == 'true'` | 133 | `TrueTextRecord` |
| 5 | `x:` + nom de dictionnaire | 135 | `QNameDictionaryTextRecord` |
| 6 | `uniqueid_reg` (`urn:uuid:`) | 137 | `UniqueIdTextRecord` |
| 7 | `uuid_reg` (GUID nu) | 140 | `UuidTextRecord` |
| 8 | `int_reg` | 143 | `Int8/16/32/64/UInt64TextRecord` |
| 9 | `data == ''` | 155 | `EmptyTextRecord` (puis écarté) |
| 10 | `b64` | 157 | `Bytes8/16/32TextRecord` |
| 11 | `float_reg` | 166 | `DoubleTextRecord` |
| 12 | `data in inverted_dict` | 168 | `DictionaryTextRecord` |
| 13 | `datetime_reg` | 170 | `DatetimeTextRecord` |
| 14 | repli | 175 | `UnicodeChars8/16/32TextRecord` |

Les expressions rationnelles sont définies en `xml2records.py:55-61`. Deux
d'entre elles méritent d'être lues attentivement : `int_reg` vaut
`^-?[1-9]\d*$`, donc exclut tout entier à zéro de tête ; `base64_reg` vaut
`^[a-zA-Z0-9/+]*={0,2}$`, donc accepte toute chaîne alphanumérique.

Le test base64 (`xml2records.py:122`) est appliqué **avant** la chaîne de
décision, à titre de pré-calcul, et sa branche passe **avant** la recherche
dans le dictionnaire. Il est très permissif : toute chaîne composée
uniquement de `[A-Za-z0-9+/]`, avec un éventuel `=` ou `==` final, et que
`base64.b64decode` accepte, devient un `Bytes8/16/32TextRecord`.
Aller-retour complet mesuré, valeur par valeur, à travers `XMLParser.parse`
puis `Record.parse` et `print_records` :

| Valeur d'annuaire | Octet émis | Record | Valeur relue |
|---|---|---|---|
| `user` | `0x9F` | `Bytes8Text+EE` | `user` |
| `computer` | `0x9F` | `Bytes8Text+EE` | `computer` |
| `organizationalPerson` | `0x9F` | `Bytes8Text+EE` | `organizationalPerson` |
| `Envelope` | `0x9F` | `Bytes8Text+EE` | `Envelope` |
| `Administrator` | `0xB7` | `UnicodeChars8Text+EE` | `Administrator` |
| `top`, `group`, `person` | `0xB7` | `UnicodeChars8Text+EE` | inchangé |
| `CN=Users,DC=x,DC=y` | `0xB7` | `UnicodeChars8Text+EE` | inchangé |
| `S-1-5-21-1-2-3-500` | `0xB7` | `UnicodeChars8Text+EE` | inchangé |
| `512` | `0x8B` | `Int16Text+EE` | `512` |
| `007` | `0x93` | `DoubleText+EE` | **`7`** |
| `0123456789` | `0x93` | `DoubleText+EE` | **`123456789`** |

Un `objectClass` valant `user` part donc sur le fil en `base64Binary` au
lieu de `string`. **Cela reste sans effet observable** :
`Bytes8TextRecord.__str__` (`text.py:749`) ré-encode en base64, et pour
toute longueur multiple de 4 sans remplissage la transformation est
exactement inverse, le lecteur retrouve `user`. Le type consommé par les
cmdlets provient de l'attribut `xsi:type` porté par `<ad:value>` ; cette
dernière affirmation découle du contrat de sérialisation `[MS-ADDM]` et
**n'a pas été mesurée** sur un client de ce dépôt.

Le cas non réversible existe cependant : une chaîne base64 **non canonique**
avec remplissage perd de l'information. Contrôle exécuté : `ab==` se décode
en un octet `0x69` et se ré-encode `aQ==`. Une valeur d'annuaire de la forme
`xy==` serait donc altérée. La parade est de restreindre le test base64 aux
longueurs multiples de 4 sans remplissage, ou de le déplacer après la
recherche dans le dictionnaire.

#### Deux défauts vérifiés de la chaîne de typage

> **Corruption des entiers à zéro de tête.** `int_reg` refusant `^-?[1-9]`,
> une valeur comme `007` échappe à la branche entière, mais satisfait
> `float_reg` et devient un `DoubleTextRecord`. Contrôle exécuté sur
> `<a:V>007</a:V>` : le flux émis est `5E 01 56 93 00 00 00 00 00 00 1C 40`
> (un double IEEE 754 valant 7,0) et la relecture rend `7`. De même
> `0123456789` devient `123456789`. Tout attribut d'annuaire dont la valeur
> textuelle est un nombre décimal à zéro de tête (`employeeID`,
> `postalCode`, certains identifiants métier) est donc **altéré en sortie**.
> C'est, de tous les écarts recensés dans ce chapitre, le seul qui produise
> une valeur fausse sur un chemin nominal. **Débordement `Int64` non
> gardé.** La borne inférieure de la branche 64 bits est écrite `-2**64 <=
> val` (`xml2records.py:151`) au lieu de `-2**63`. Contrôle exécuté :
> `-9223372036854775809` est routé vers `Int64TextRecord`, dont `to_bytes`
> lève alors `struct.error: 'q' format requires -9223372036854775808 <=
> number <= 9223372036854775807`. L'exception remonte au dispatcher, qui la
> traduit en fault SOAP. La fenêtre concernée, `[-2^64, -2^63)`, ne
> correspond à aucune valeur d'annuaire réaliste ; le défaut est **latent**.

## Le dictionnaire statique (MS-NBFS)

### Taille et forme de la table

Le dictionnaire statique du projet est un simple `dict` Python littéral, de
`src/wcf/dictionary.py:29` à `src/wcf/dictionary.py:517`. Comptage effectué
sur le fichier : **487 entrées**, clés `0x00` à `0x3CC` (972 en décimal),
**pas de 2, sans aucun trou**, vérifié par énumération exhaustive des clés.

Les clés stockées sont directement les **valeurs de fil**, c'est-à-dire les
identifiants tels qu'ils apparaissent dans un `MultiByteInt31` de record. La
table `[MS-NBFS]` proprement dite numérote ses chaînes de 0 à 486 ; la
valeur de fil vaut `2 x index`. Le fichier du projet a donc déjà appliqué le
doublement, ce qui évite toute conversion à l'exécution.

### La règle pair / impair

C'est le mécanisme d'extensibilité de `[MS-NBFS]` et `[MS-NBFSE]` :

| Parité de l'identifiant | Origine de la chaîne |
|---|---|
| **pair** | table statique `[MS-NBFS]`, identique pour tous les échanges |
| **impair** | dictionnaire de session `[MS-NBFSE]`, défini en tête de message |

La règle est confirmée par le code du projet : le dictionnaire statique
n'utilise que des clés paires (vérifié : zéro clé impaire sur 487), et
l'allocateur de session `build_dictionary` (`src/nettcp/protocol2xml.py:30`)
part de `idx = 1` (`protocol2xml.py:28`) et progresse par `idx += 2`
(`protocol2xml.py:41`).

Un décodeur qui rencontre un identifiant impair non déclaré lèvera un
`KeyError` sur `dictionary[self.index]` (par exemple `elements.py:156`),
remonté au dispatcher et traduit en fault SOAP.

### Index exacts utiles au diagnostic

Les valeurs suivantes sont relevées telles quelles dans
`src/wcf/dictionary.py` ; ce sont celles que l'on croise dans tout dump
ADWS.

| Index | Chaîne | Ligne |
|---|---|---|
| `0x00` | `mustUnderstand` | `dictionary.py:30` |
| `0x02` | `Envelope` | `dictionary.py:31` |
| `0x04` | `http://www.w3.org/2003/05/soap-envelope` | `dictionary.py:32` |
| `0x06` | `http://www.w3.org/2005/08/addressing` | `dictionary.py:33` |
| `0x08` | `Header` | `dictionary.py:34` |
| `0x0A` | `Action` | `dictionary.py:35` |
| `0x0C` | `To` | `dictionary.py:36` |
| `0x0E` | `Body` | `dictionary.py:37` |
| `0x12` | `RelatesTo` | `dictionary.py:39` |
| `0x14` | `http://www.w3.org/2005/08/addressing/anonymous` | `dictionary.py:40` |
| `0x1A` | `MessageID` | `dictionary.py:43` |
| `0x2C` | `ReplyTo` | `dictionary.py:52` |
| `0x84` | `s` | `dictionary.py:96` |
| `0x86` | `Fault` | `dictionary.py:97` |
| `0x8E` | `Code` | `dictionary.py:101` |
| `0x90` | `Reason` | `dictionary.py:102` |
| `0x92` | `Text` | `dictionary.py:103` |
| `0x9A` | `Value` | `dictionary.py:107` |
| `0xA2` | chaîne vide | `dictionary.py:111` |
| `0xB6` | `a` | `dictionary.py:121` |
| `0x256` | `xmlns` | `dictionary.py:329` |
| `0x372` | `http://www.w3.org/2001/XMLSchema-instance` | `dictionary.py:471` |
| `0x374` | `http://www.w3.org/2001/XMLSchema` | `dictionary.py:472` |
| `0x376` | `nil` | `dictionary.py:473` |
| `0x378` | `type` | `dictionary.py:474` |
| `0x396` | `string` | `dictionary.py:489` |
| `0x398` | `base64Binary` | `dictionary.py:490` |
| `0x3CC` | `detail` | `dictionary.py:516` |

La table couvre SOAP 1.1 et 1.2, WS-Addressing (deux révisions),
WS-ReliableMessaging, WS-Trust, WS-SecureConversation, WS-Coordination,
WS-AtomicTransaction, SAML 1.x, XML Signature, XML Encryption et les noms de
types XSD. Elle ne contient **aucun** vocabulaire ADWS.

### Le dictionnaire inversé

`src/wcf/dictionary.py:519` construit `inverted_dict` par simple
compréhension `{v: k for k, v in dictionary.items}`. Vérification effectuée
: les deux tables comptent 487 entrées, donc **aucune valeur n'est
dupliquée** et l'inversion est bijective. C'est cette table qui pilote
toutes les décisions d'indexation de `src/wcf/xml2records.py`.

Neuf entrées sont des chaînes d'un seul caractère (`s`, `a`, `c`, `e`, `k`,
`o`, `r`, `t`, `u`), destinées à indexer des **préfixes** littéraux. Effet
de bord à connaître : un nœud texte valant exactement `a` sera encodé en
`DictionaryTextRecord(0xB6)` et non en `UnicodeChars8`, comportement
correct, le décodage restitue `a`.

### Ce qui manque : les espaces de noms ADWS

`SoapEnvelope.NS_DECL` (`classes/soap/soap_envelope.py:23`) déclare **onze**
espaces de noms. Quatre d'entre eux ont leur URI dans la table statique ;
les sept autres, tous propres à ADWS ou aux WS-*, n'y figurent pas. Le coût
de chaque déclaration a été mesuré par différence entre `dump_records` d'un
`<s:E xmlns:p="URI"></s:E>` et `dump_records` d'un `<s:E></s:E>` :

| Préfixe | Longueur de l'URI | Index statique | Coût mesuré |
|---|---|---|---|
| `s` (SOAP 1.2) | 39 | `0x04` | 4 octets |
| `a` (WS-Addressing) | 36 | `0x06` | 4 octets |
| `xsi` | 41 | `0x372` | 7 octets |
| `xsd` | 32 | `0x374` | 7 octets |
| `wst` | 46 | aucun | 52 octets |
| `wsen` | 49 | aucun | 56 octets |
| `ad` | 51 | aucun | 56 octets |
| `addata` | 56 | aucun | 65 octets |
| `ca` | 65 | aucun | 70 octets |
| `adlq` | 69 | aucun | 76 octets |
| `da` | 71 | aucun | 76 octets |

La formule est directe pour les URI non indexées : `XmlnsAttributeRecord`
coûte 1 octet de type, plus le `Utf8String` du préfixe, plus le `Utf8String`
de l'URI, soit `1 + (1 + len(prefixe)) + (1 + len(uri))`. Pour les URI
indexées, `DictionaryXmlnsAttributeRecord` coûte `1 + (1 + len(prefixe)) +
len(MultiByteInt31)`.

Totaux mesurés : les onze déclarations pèsent **473 octets** encodés, dont
**451 octets** pour les seules sept non indexées. L'élément vide de
référence `<s:Envelope></s:Envelope>` ne coûte, lui, que **3 octets** (`56
02 01`). Ce sont donc 451 octets fixes payés sur chaque réponse pour du
vocabulaire strictement constant. C'est précisément ce que le dictionnaire
de session `[MS-NBFSE]` est fait pour supprimer.

## Le dictionnaire de session (MS-NBFSE) : statut dans ce projet

### Le mécanisme

Quand l'encodage négocié est `BINARY_DICT` (valeur 8), chaque message
applicatif est précédé, **à l'intérieur** de la charge utile du
`SizedEnvelopedMessageRecord` NMF, d'un préambule de dictionnaire de session
:

```text
+--------------------+---------------------------+-------------------------+
| MultiByteInt31     | N octets : suite de       | records MS-NBFX         |
| taille de la table | Utf8String concatenees    | (le document lui-meme)  |
+--------------------+---------------------------+-------------------------+
```

Chaque `Utf8String` définit une chaîne de session ; les identifiants sont
attribués séquentiellement en **impairs** : 1, 3, 5,... Une fois définie,
une chaîne peut être référencée par n'importe quel record `*Dictionary*` du
message et des messages suivants de la même session.

### Ce que fait réellement l'implémentation

Contrairement à ce qu'affirme `documentation/03-protocole.md` (« Le
dictionnaire dynamique négocié par session (MS-NBFSE) n'est pas implémenté
»), le mécanisme **est implémenté à la réception**, et volontairement
neutralisé à l'émission.

**À la réception**, `SizedEnvelopedMessageRecord.payload_to_xml`
(`src/nettcp/nmf.py:363`) appelle `build_dictionary(fp, ('client', 'c>s'))`
avant `Record.parse`. La fonction (`src/nettcp/protocol2xml.py:30`) lit la
taille, découpe la table en `Utf8String`, attribue les identifiants impairs,
puis **fusionne** le résultat dans le dictionnaire global du module
`src/wcf/dictionary.py` :

```python
dictionary.clear()
dictionary.update(old_dictionary)
dictionary.update(dictionary_cache[key])
```

**À l'émission**, `ADWSDispatcher._encode_response`
(`classes/handlers/dispatcher.py:46`) préfixe systématiquement la sortie de
`dump_records` par un octet `\x00` :

```python
records: Any = XMLParser.parse(response_xml)
encoded: Any = dump_records(records)
result: bytes = b"\x00" + encoded
return result
```

Cet octet **n'est pas un octet de cadrage** : c'est le `MultiByteInt31`
valant zéro, c'est-à-dire une **table de session vide**. Le serveur déclare
ainsi ne définir aucune chaîne de session, ce qui est licite et rend toutes
ses réponses interprétables avec la seule table statique.

> La documentation de la compétence `decode-wcf`
> (`.claude/skills/decode-wcf/SKILL.md`) décrit ce `\x00` comme un « framing
> byte ». La formulation exacte est : préambule `[MS-NBFSE]` de longueur
> nulle. La conséquence pratique est la même, pour décoder une trame
> sortante capturée, retirer le premier octet.

### Limites et risques identifiés

- **État global mutable.** `build_dictionary` modifie en place le `dict`
  importé depuis `src/wcf/dictionary.py`, plus deux globales `idx` et
  `dictionary_cache` (`protocol2xml.py:26-28`). C'est une violation directe
  de la règle « pas d'état global mutable » de `CLAUDE.md` §6.1. Le modèle
  `ForkingTCPServer` limite les dégâts, chaque connexion est un processus
  distinct, mais l'état grossit sans borne au fil des messages d'une même
  connexion.
- **Numérotation cumulative.** `idx` ne repart jamais de 1. Si un client
  redéfinit sa table de session au cours d'une même connexion, les chaînes
  reçues seront enregistrées sous de nouveaux identifiants impairs, tandis
  que le client continuera de référencer les anciens : désynchronisation
  silencieuse. Ce scénario n'a pas été observé sur le trafic du projet ; il
  n'est **pas vérifié en conditions réelles**.
- **Écriture sur la sortie standard.** `build_dictionary` fait un `print` de
  la taille de table et de chaque entrée (`protocol2xml.py:33` et
  `protocol2xml.py:47`) : c'est du code de mise au point laissé sur le
  chemin nominal de chaque requête.
- **Fragilité avérée.** Le journal `adws.log` conserve la trace d'un échec
  direct de cette fonction :

```text
File "/opt/adws/src/adws/dispatcher.py", line 24, in dispatch
    xml_request = record.payload_to_xml()
File "/opt/adws/nettcp/nmf.py", line 369, in payload_to_xml
    build_dictionary(fp, ('client', 'c>s'))
File "/opt/adws/nettcp/protocol2xml.py", line 38, in build_dictionary
    string = Utf8String.parse(table)
File "/opt/adws/wcf/datatypes.py", line 52, in parse
    return cls(data.decode('utf-8'))
UnicodeDecodeError: 'utf-8' codec can't decode byte 0x82 in position 11:
invalid start byte
```

Les numéros de ligne concordent avec l'arbre actuel (`nmf.py:369` est bien
l'appel à `build_dictionary`, `protocol2xml.py:38` est bien
`Utf8String.parse(table)`, `datatypes.py:52` est bien le `decode('utf-8')`)
; seule l'arborescence a changé depuis, le dispatcher étant passé de
`src/adws/` à `classes/handlers/`.

L'octet `0x82` en position 11 est le type d'un `OneTextRecord` : la fonction
lisait déjà le **document**, pas la table. Autrement dit la taille lue en
tête n'était pas une taille de table de session. Deux hypothèses subsistent,
le message reçu n'était pas encodé en `BINARY_DICT`, ou la table était vide
et le premier octet du document a été pris pour une longueur, et **aucune
capture n'est disponible pour trancher**. `build_dictionary` n'effectue
aucune validation : ni borne supérieure sur la taille annoncée, ni
vérification que les octets lus sont bien de l'UTF-8 valide, ni contrôle que
`table.tell` s'arrête exactement sur `size`. Un contrôle de cohérence à cet
endroit est le durcissement le plus rentable de toute la couche.

## Chaîne d'encodage et de décodage dans l'implémentation

### Vue d'ensemble

```text
  RECEPTION (client -> serveur)
  ============================
  SizedEnvelopedMessageRecord.Payload   (deja desscelle par GSSAPI)
        |
        | src/nettcp/nmf.py:363   payload_to_xml()
        v
  build_dictionary()                    src/nettcp/protocol2xml.py:30
        |  (table de session -> dictionnaire global)
        v
  Record.parse(fp)                      src/wcf/records/base.py:75
        |  (octets -> arbre de Record)
        v
  print_records(records, fp=out)        src/wcf/records/__init__.py:42
        |  (arbre -> XML texte)
        v
  RequestContext.from_xml(xml)          classes/parsing/context.py:37
        |  (ElementTree -> action, message_id, DN, filtres)
        v
  HandlerRegistry.resolve(action).handle(context)

  EMISSION (serveur -> client)
  ===========================
  handler.handle() -> chaine XML        classes/soap/soap_envelope.py:33
        |
        | classes/handlers/dispatcher.py:47
        v
  XMLParser.parse(response_xml)         src/wcf/xml2records.py:313
        |  (Expat -> arbre de Record)
        v
  dump_records(records)                 src/wcf/records/__init__.py:90
        |  (arbre -> octets)
        v
  b"\x00" + encoded                     classes/handlers/dispatcher.py:49
        |  (prefixe MS-NBFSE vide)
        v
  SizedEnvelopedMessageRecord           classes/server/protocol.py:153
```

### Le rôle de `html_parser.py`

Le nom du fichier est trompeur : `src/wcf/html_parser.py` ne parse pas du
HTML. C'est une **réécriture** de l'ancien `HTMLParser` de la bibliothèque
standard, dont le code vendoré dépendait, remplacée par un pilote autour de
`xml.parsers.expat` (`html_parser.py:27`). Sa docstring l'annonce : *«
Case-preserving XML parser replacing HTMLParser for WCF »*
(`html_parser.py:7`). Deux motifs à ce remplacement :

- **La casse.** `HTMLParser` normalise les noms de balises et d'attributs en
  minuscules. Or les noms d'attributs AD sont sensibles à la casse
  (`objectGUID`, `sAMAccountName`, `distinguishedName`).
- **Les préfixes.** Le commentaire de `html_parser.py:24-26` est explicite :
  le parseur est créé **sans séparateur d'espace de noms**, afin qu'Expat
  restitue les noms qualifiés complets (`s:Envelope`) plutôt que la forme
  `{uri}local`. C'est ce qui permet à `_parse_tag` de récupérer le préfixe
  littéral, indispensable pour choisir un record
  `PrefixDictionaryElement<L>`. Corollaire : les déclarations `xmlns`
  restent des attributs ordinaires dans la liste passée à `handle_starttag`,
  donc encodables.

La classe n'expose que trois handlers Expat : `StartElementHandler`,
`EndElementHandler`, `CharacterDataHandler` (`html_parser.py:28-30`). Tout
le reste de l'interface historique (`handle_charref`, `handle_entityref`,
`handle_decl`, `handle_comment`, `parse_marked_section`) subsiste dans
`XMLParser` mais constitue du **code mort** : Expat résout les références de
caractères et d'entités lui-même et les livre via `CharacterDataHandler`.
Cela explique aussi que `self.interesting` conserve toujours la valeur
`INTERESTING_NORMAL` (`src/wcf/constants.py:6`) et que le drapeau `is_cdata`
testé en `xml2records.py:257` soit toujours faux.

Une dernière subtilité : `feed` appelle `self._parser.Parse(data, False)`
(`html_parser.py:38`), donc en mode non final, et `close` n'est jamais
invoqué par `XMLParser.parse`. Cela fonctionne parce que le document fourni
est toujours complet et bien formé ; un document tronqué ne déclencherait
pas d'erreur.

### Pourquoi passer par du XML texte intermédiaire

Le serveur pourrait, en théorie, construire directement un arbre de `Record`
et l'émettre. Il ne le fait pas, et c'est un choix d'architecture assumé :

- **Une seule représentation canonique pour la logique métier.** Les
  handlers produisent des chaînes XML par interpolation
  (`SoapEnvelope.wrap`, `classes/soap/soap_envelope.py:33`) et les parseurs
  de `classes/parsing/` consomment de l'`ElementTree`. Aucun code métier n'a
  connaissance des records.
- **Auditabilité.** Un XML texte se lit dans un journal, se compare, se
  rejoue ; un arbre de records ne se lit pas.
- **Isolation du code vendoré.** `src/wcf/` et `src/nettcp/` sont identifiés
  comme du code tiers vendoré, exclu des normes §6.1
  (`documentation/01-architecture.md:79-80`). La frontière est justement la
  chaîne XML.

Le prix payé est de **deux passes de sérialisation supplémentaires par
message** : une reconstruction textuelle au décodage (`print_records`), une
réanalyse Expat à l'encodage. Le coût relatif de ces deux passes sur un gros
`PullResponse` **n'a pas été profilé** dans ce dépôt ; il constitue
néanmoins la cible évidente d'une optimisation de phase 5.

### Deux effets de bord de `print_records`

`print_records` (`src/wcf/records/__init__.py:42`) **indente** sa sortie :
chaque élément est précédé d'un saut de ligne et de `skip` espaces
(`__init__.py:62`). Le XML reconstruit n'est donc pas l'original mais une
version formatée.

L'indentation n'est écrite **que devant les éléments**. Un élément dont le
contenu est purement textuel voit sa valeur écrite en ligne, intacte,
vérifié sur l'aller-retour de l'exemple complet plus bas, où
`<a:Action>http://...</a:Action>` reste sur une ligne. En revanche, un
élément à contenu mixte (texte puis élément) verrait son texte suivi d'un
saut de ligne parasite. ADWS ne produit pas de contenu mixte ; le risque est
nul en pratique, mais la reconstruction n'est pas fidèle à l'infoset au sens
strict.

## Exemple complet : encodage pas à pas d'une enveloppe SOAP

### Le document de départ

Une enveloppe de réponse réduite aux deux seuls espaces de noms indexés, de
structure identique à celle que produit `SoapEnvelope.wrap` mais amputée des
neuf autres déclarations et de la déclaration XML, afin que le dump reste
lisible :

```xml
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
            xmlns:a="http://www.w3.org/2005/08/addressing">
  <s:Header>
    <a:Action s:mustUnderstand="1"
      >http://schemas.xmlsoap.org/ws/2004/09/transfer/GetResponse</a:Action>
    <a:RelatesTo>urn:uuid:11111111-2222-3333-4444-555555555555</a:RelatesTo>
  </s:Header>
  <s:Body></s:Body>
</s:Envelope>
```

Soit **332 caractères** une fois minifié. L'encodage produit **159 octets**.

### Le flux binaire annoté

Sortie réelle de `dump_records(XMLParser.parse(xml))`, annotée segment par
segment.

```text
0000  56 02
      |  +-- MultiByteInt31 index 0x02 = "Envelope"
      +----- 0x56 PrefixDictionaryElementS  ==> <s:Envelope

0002  0B 01 73 04
      |  |  |  +-- index 0x04 = "http://www.w3.org/2003/05/soap-envelope"
      |  |  +----- octets du prefixe : 's'
      |  +-------- Utf8String longueur 1
      +----------- 0x0B DictionaryXmlnsAttribute  ==> xmlns:s="..."

0006  0B 01 61 06
      +----------- idem, prefixe 'a', index 0x06
                   ==> xmlns:a="http://www.w3.org/2005/08/addressing"

000A  56 08        0x56 PrefixDictionaryElementS, index 0x08 = "Header"
                   ==> <s:Header>

000C  44 0A        0x44 PrefixDictionaryElementA, index 0x0A = "Action"
                   ==> <a:Action

000E  1E 00 82
      |  |  +-- 0x82 OneTextRecord  ==> valeur "1"
      |  +----- index 0x00 = "mustUnderstand"
      +-------- 0x1E PrefixDictionaryAttributeS
                ==> s:mustUnderstand="1"

0011  B7 74 68 00 74 00 74 00 70 00 3A 00 2F 00 2F 00 ...
      |  |  +-- 116 octets UTF-16LE : "http://schemas.xmlsoap.org/ws/
      |  |      2004/09/transfer/GetResponse" (58 caracteres)
      |  +----- longueur sur 1 octet = 0x74 = 116
      +-------- 0xB7 = 0xB6 + 1 : UnicodeChars8Text AVEC EndElement
                ==> le texte, puis </a:Action>

0087  44 12        0x44 PrefixDictionaryElementA, index 0x12 = "RelatesTo"
                   ==> <a:RelatesTo>

0089  AD 11 11 11 11 22 22 33 33 44 44 55 55 55 55 55 55
      |  +-- 16 octets bytes_le du GUID
      +----- 0xAD = 0xAC + 1 : UniqueIdText AVEC EndElement
             ==> urn:uuid:11111111-2222-3333-4444-555555555555
                 puis </a:RelatesTo>

009A  01           EndElementRecord  ==> </s:Header>

009B  56 0E        0x56 PrefixDictionaryElementS, index 0x0E = "Body"
                   ==> <s:Body>

009D  01           EndElementRecord  ==> </s:Body>

009E  01           EndElementRecord  ==> </s:Envelope>
```

Trois observations sur ce flux :

- **Aucune balise fermante n'est écrite en clair.** Deux des quatre
  fermetures sont gratuites, portées par le bit *WithEndElement* des records
  `0xB7` et `0xAD`.
- **`<s:Body></s:Body>` coûte 3 octets** : `56 0E 01`. La version textuelle
  en coûte 17.
- **La valeur de `<a:Action>` représente 118 des 159 octets**, soit 74 % du
  message. C'est l'illustration parfaite de la raison d'être de `[MS-NBFSE]`
  : cette URI est identique dans toutes les réponses `GetResponse`, une
  seule définition de session la ramènerait à deux octets pour tous les
  messages suivants.

### L'opération inverse

Le décodage complet est réalisé par le couple `Record.parse` puis
`print_records` (commande exacte à la section suivante). Résultat obtenu sur
les 159 octets ci-dessus :

```xml
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
 xmlns:a="http://www.w3.org/2005/08/addressing">
 <s:Header>
  <a:Action s:mustUnderstand="1">http://schemas.xmlsoap.org/ws/2004/09/
transfer/GetResponse</a:Action>
  <a:RelatesTo>urn:uuid:11111111-2222-3333-4444-555555555555</a:RelatesTo>
 </s:Header>
 <s:Body></s:Body>
</s:Envelope>
```

Les retours à la ligne à l'intérieur de l'URI et de la balise `<s:Envelope>`
sont un artefact de mise en page du présent document ; l'indentation, elle,
est bien produite par `print_records`. L'aller-retour est fidèle au niveau
du contenu : mêmes éléments, mêmes attributs, mêmes valeurs textuelles.

### L'outil de mise au point du dépôt

Le dépôt expose une compétence `decode-wcf`
(`.claude/skills/decode-wcf/SKILL.md:20` et `:27`) et
`documentation/03-protocole.md:269` propose une ligne de commande. **Les
deux sont inexactes** : elles appellent `dump_records(data)` sur des octets,
alors que `dump_records` (`src/wcf/records/__init__.py:90`) attend un
**arbre de records** et produit des octets. C'est la fonction du sens
inverse.

Le mode de défaillance est pernicieux. `dump_records` itère sur son argument
; sur un `bytes`, l'itération produit des `int`, et `int.to_bytes` accepte
depuis Python 3.11 des paramètres par défaut (`length=1`,
`byteorder='big'`). Contrôle exécuté sous CPython 3.12 :
`dump_records(b'\x56\x02\x01')` rend `b'V\x02\x01'`, c'est-à-dire **l'entrée
inchangée**, sans lever la moindre exception. La commande documentée
n'échoue donc pas : elle réaffiche le payload brut, ce qu'un lecteur pressé
peut prendre pour un décodage. Sous Python 3.10 et antérieurs,
`int.to_bytes` sans argument lève un `TypeError`, et l'erreur est au moins
visible.

La commande correcte, à exécuter depuis la racine du dépôt, est la suivante.

Depuis un fichier binaire :

```bash
python3 -c "
import sys; from io import BytesIO, StringIO
from src.wcf.records import Record, print_records
data = open(sys.argv[1],'rb').read()
if data[:1] == b'\x00': data = data[1:]
out = StringIO(); print_records(Record.parse(BytesIO(data)), fp=out)
print(out.getvalue())
" /tmp/payload.bin
```

Depuis une chaîne hexadécimale :

```bash
python3 -c "
from io import BytesIO, StringIO
from src.wcf.records import Record, print_records
data = bytes.fromhex('5602 0B01 7304 5608 440A'.replace(' ',''))
out = StringIO(); print_records(Record.parse(BytesIO(data)), fp=out)
print(out.getvalue())
"
```

`repr_records` (`src/wcf/records/__init__.py:81`) affiche un record par
ligne, sans reconstruction XML, utile pour vérifier qu'une valeur n'a pas
été typée `Bytes8TextRecord` par l'heuristique base64.

Pour le sens inverse, c'est-à-dire vérifier ce qu'un XML de handler donnera
sur le fil :

```bash
python3 -c "
from src.wcf.records import dump_records
from src.wcf.xml2records import XMLParser
xml = open('/tmp/reponse.xml').read()
b = dump_records(XMLParser.parse(xml))
print(len(b), 'octets')
print(' '.join('%02X' % c for c in b))
"
```

> Rappel opérationnel : après la négociation GSSAPI (phase 2 du protocole
> NMF), les octets observés par `tcpdump` sont **scellés**. Une capture
> réseau brute ne se décode pas. Le clair s'obtient par le journal de
> records de `tools/work/proxy.py` (`RECORD_LOG`), conformément à
> `documentation/03-protocole.md`. Un payload sortant du dispatcher porte de
> plus le préfixe `[MS-NBFSE]` `\x00` : le retirer avant décodage.

### Synthèse des écarts de cette implémentation

Les écarts sont classés par gravité décroissante. « Actif » signifie qu'un
chemin nominal du serveur l'emprunte aujourd'hui ; « latent » qu'il faudrait
un flux entrant que ce dépôt n'a jamais observé pour le déclencher.

| Point | Attendu | Cette implémentation | Statut |
|---|---|---|---|
| Entier à zéro de tête | chaîne préservée | `007` devient `7` (`Double`) | **actif** |
| `dump_records` idempotent | oui | mute `r.type`, 2e appel invalide | **actif** |
| Records de texte pour chaînes | libre | toujours `UnicodeChars*` (UTF-16) | actif |
| Dictionnaire de session émis | facultatif | jamais produit, préfixe `\x00` | actif |
| `print` sur le chemin nominal | non | `build_dictionary` écrit sur stdout | actif |
| Validation de la table de session | souhaitable | aucune borne, aucun contrôle | actif |
| `DateTimeKind` en lecture | restitué | ignoré par `__str__` | actif |
| Octet inconnu en lecture | erreur | avertissement, lecture poursuivie | actif |
| Octet 0x78 en lecture | erreur | décodé en `PrefixElementZ` + fin | latent |
| Échappement XML en lecture | intégral | absent des `UnicodeChars*` | latent |
| `StartList/EndList/Empty` en lecture | rendus | rendus par leur `__repr__` | latent |
| `TimeSpanTextRecord` au rendu | exact | erroné d'un facteur 1000 | latent |
| Décodage `UnicodeChars*` | `utf-16le` | `utf-16`, consomme un BOM de tête | latent |
| Borne `Int64` à l'encodage | `-2^63` | `-2^64`, `struct.error` possible | latent |
| Attributs d'un `ArrayRecord` reçu | conservés | écrasés par une liste vide | latent |
| `ArrayRecord`, `Comment`, `Decimal` | possibles | lus seulement, jamais émis | latent |

Aucun des écarts marqués « latent » n'empêche le fonctionnement nominal
validé au chapitre Tests (`documentation/05-tests.md:129`, **26/28** sur
`Test-ADWS-Sovereign.ps1`) : les chemins concernés ne sont pas empruntés par
le module `ActiveDirectory` de PowerShell dans les scénarios couverts. Les
écarts marqués « actif » sont, eux, présents sur chaque requête ; seul le
premier produit une valeur fausse, et il n'est pas couvert par la suite de
tests actuelle. L'ensemble constitue la dette technique connue de la couche
d'encodage et la liste de travail de la phase 5.

Trois points ont été explicitement laissés **non tranchés**, faute de
capture ou de mesure disponible dans ce dépôt, et ne doivent pas être
présentés comme acquis : la valeur réelle de l'octet `KnownEncodingRecord`
envoyé par le client, la répartition `Chars*` / `UnicodeChars*` du trafic
entrant, et la cause exacte du `UnicodeDecodeError` historique de
`build_dictionary`. Aucune section précise des spécifications Microsoft
n'est citée dans ce chapitre : les documents `[MS-NBFX]`, `[MS-NBFS]`,
`[MS-NBFSE]` et `[MS-NMF]` sont référencés par leur nom, et toutes les
valeurs d'octet données ici sont issues de la lecture et de l'exécution du
code de ce dépôt.

# Partie VI. SOAP, WS-Addressing et gestion des fautes

## Enveloppe SOAP 1.2 et espaces de noms

### Position de la couche message dans l'empilement

Une fois le préambule [MS-NMF] consommé, le contexte GSSAPI établi et le
payload descellé puis décodé depuis le XML binaire WCF ([MS-NBFX] /
[MS-NBFS]), ce qui reste entre les mains du serveur est **du SOAP 1.2
textuel ordinaire**. C'est un choix d'architecture explicite du projet :
`src/nettcp/nmf.py:363` (`Record.payload_to_xml`) reconstruit une chaîne XML
lisible, et tout le code applicatif (parsing, routage, handlers,
sérialisation, fautes) ne manipule plus que des `str`. Le chemin retour est
symétrique : chaque handler retourne une **chaîne XML SOAP complète**, que
`ADWSDispatcher._encode_response` (`classes/handlers/dispatcher.py:45-50`)
re-compile en records WCF.

Le coût de cet aller-retour texte est assumé ; le bénéfice est qu'un message
d'erreur, un test ou une comparaison avec une capture Microsoft se font tous
sur le même artefact : le XML.

Trois niveaux doivent être distingués dans tout ce chapitre :

- **1. La spécification** : SOAP 1.2 (W3C), WS-Addressing 1.0, WS-Transfer,
  WS-Enumeration, WS-Eventing, et les profils Microsoft [MS-ADDM],
  [MS-WSTIM], [MS-WSDS], [MS-WSPELD].
- **2. Le client Windows réel** : le module PowerShell `ActiveDirectory` et
  ADAC, dont le comportement observable est parfois plus strict (ou plus
  laxiste) que la spec.
- **3. Cette implémentation Python** : qui vise la compatibilité fil avec le
  niveau 2, et dont les écarts avec le niveau 1 sont signalés au fil du
  texte.

### Forme canonique de l'enveloppe émise

La fabrique d'enveloppes centrale est `SoapEnvelope`
(`classes/soap/soap_envelope.py:21`). Elle produit une enveloppe SOAP 1.2
minifiée, préfixée d'un prologue XML, avec **un bloc `<s:Header>` réduit à
deux en-têtes**, `a:Action` et `a:RelatesTo`, et un `<s:Body>` fourni par le
handler.

```xml
<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
            xmlns:a="http://www.w3.org/2005/08/addressing"
            xmlns:wsen="http://schemas.xmlsoap.org/ws/2004/09/enumeration"
            xmlns:wst="http://schemas.xmlsoap.org/ws/2004/09/transfer"
            xmlns:ad="http://schemas.microsoft.com/2008/1/ActiveDirectory"
            xmlns:addata="http://schemas.microsoft.com/2008/1/ActiveDirectory/Data"
            xmlns:da="http://schemas.microsoft.com/2006/11/IdentityManagement/DirectoryAccess"
            xmlns:adlq="http://schemas.microsoft.com/2008/1/ActiveDirectory/Dialect/LdapQuery"
            xmlns:ca="http://schemas.microsoft.com/2008/1/ActiveDirectory/CustomActions"
            xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
            xmlns:xsd="http://www.w3.org/2001/XMLSchema">
  <s:Header>
    <a:Action s:mustUnderstand="1">…</a:Action>
    <a:RelatesTo>urn:uuid:…</a:RelatesTo>
  </s:Header>
  <s:Body>…</s:Body>
</s:Envelope>
```

Toutes les déclarations d'espaces de noms sont **hissées au niveau de
`<s:Envelope>`** (constante `SoapEnvelope.NS_DECL`,
`classes/soap/soap_envelope.py:23-30`). C'est délibéré : le lecteur XML .NET
côté client résout les préfixes en amont du corps, et le codec WCF binaire
gagne à ne déclarer chaque URI qu'une fois. `_minify`
(`classes/soap/soap_envelope.py:68-70`) supprime ensuite tout blanc situé
entre deux balises via `re.sub(r">\s+<", "><", …)`.

> La sortie du dispatcher est préfixée d'un octet `\x00`
> (`classes/handlers/dispatcher.py:49`). Ce n'est pas du SOAP : c'est la
> **taille (nulle) de la table de dictionnaire dynamique en bande**
> [MS-NBFSE], encodée en `MultiByteInt31`. La preuve en est le chemin
> symétrique : `Record.payload_to_xml` (`src/nettcp/nmf.py:363-373`) appelle
> `build_dictionary` (`src/nettcp/protocol2xml.py:30`) qui commence par
> `size = MultiByteInt31.parse(fp).value` (`:32`) avant de laisser
> `Record.parse` lire les records WCF. Le projet n'implémente pas le
> dictionnaire dynamique : il annonce donc systématiquement zéro entrée.
> Oublier cet octet casse le décodage côté client.

### Table exhaustive des espaces de noms

Les URI ci-dessous sont recopiées **telles quelles** depuis
`src/soap/namespaces.py:3-16` et, pour les deux dernières, depuis
`src/faults/fault_codes.py:2` et `classes/serialization/ca_elements.py:6`.
Aucune n'est reconstruite de mémoire.

| Préfixe | Constante | URI |
|---|---|---|
| `s` | `SOAP_ENV` | `http://www.w3.org/2003/05/soap-envelope` |
| `a` | `WSA` | `http://www.w3.org/2005/08/addressing` |
| `wsen` | `WSEN` | `http://schemas.xmlsoap.org/ws/2004/09/enumeration` |
| `wst` | `WST` | `http://schemas.xmlsoap.org/ws/2004/09/transfer` |
| `wse` | `WSEV` | `http://schemas.xmlsoap.org/ws/2004/08/eventing` |
| `ad` | `AD` | `http://schemas.microsoft.com/2008/1/ActiveDirectory` |
| `addata` | `ADDATA` | `http://schemas.microsoft.com/2008/1/ActiveDirectory/Data` |
| `da` | `DA` | `http://schemas.microsoft.com/2006/11/IdentityManagement/DirectoryAccess` |
| `adlq` | `ADLQ` | `http://schemas.microsoft.com/2008/1/ActiveDirectory/Dialect/LdapQuery` |
| `ca` | `CUSTOM_ACTIONS` | `http://schemas.microsoft.com/2008/1/ActiveDirectory/CustomActions` |
| — | `FAULT_NS` | `http://schemas.microsoft.com/2008/1/ActiveDirectory/Data/fault` |
| `wsman` | `WSMAN_FAULT` | `http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd` |
| `xsi` | `XSI` | `http://www.w3.org/2001/XMLSchema-instance` |
| `xsd` | `XSD` | `http://www.w3.org/2001/XMLSchema` |
| `wsa` | `WSADDR_FAULT_NS` | `http://schemas.xmlsoap.org/ws/2004/08/addressing` |
| `sera` | `SERA` | `http://schemas.microsoft.com/2003/10/Serialization/Arrays` |

Origine et rôle de chacun :

| Constante | Spécification d'origine | Rôle dans ADWS |
|---|---|---|
| `SOAP_ENV` | SOAP 1.2 (W3C) | Enveloppe, Header, Body, Fault |
| `WSA` | WS-Addressing 1.0 | Action, MessageID, RelatesTo, To, EPR |
| `WSEN` | WS-Enumeration (2004/09) | Enumerate, Pull, Release, Renew, GetStatus |
| `WST` | WS-Transfer (2004/09) | Get, Put, Delete, Create, ResourceCreated |
| `WSEV` | WS-Eventing (2004/08) | Subscribe, Unsubscribe, Renew, GetStatus |
| `AD` | [MS-ADDM] | Synthétiques `ad:`, `ad:controls`, en-têtes AD |
| `ADDATA` | [MS-ADDM] | Attributs d'annuaire `<addata:nom>` |
| `DA` | [MS-WSTIM] / IMDA | PartialAttribute, BaseObjectSearch* |
| `ADLQ` | [MS-WSDS] dialecte LdapQuery | BaseObject, Filter, Scope |
| `CUSTOM_ACTIONS` | [MS-ADCAP] actions propriétaires | AccountManagement, TopologyManagement |
| `FAULT_NS` | Profil de faute ADWS | Valeur d'`a:Action` des fautes CA |
| `WSMAN_FAULT` | WS-Management (DMTF) | Sous-codes CannotProcessFilter, AccessDenied |
| `XSI` / `XSD` | XML Schema (W3C) | `xsi:type`, `xsi:nil` sur `<ad:value>` |
| `WSADDR_FAULT_NS` | WS-Addressing 2004/08 | Détail de faute d'adressage |
| `SERA` | Sérialisation .NET (tableaux) | `<sera:string>` dans les réponses CA |

Les constantes homologues de les constantes du service ADWS Microsoft
portent les **mêmes URI et les mêmes préfixes** : `AdNs` (`:81`), `AddataNs`
(`:83`), `AdCustomActionNs` (`:85`), `AdFault` (`:87`), `XsiNs` (`:89`),
`XsdNs` (`:91`), `IdentityManagementDirectoryAccess` (`:93`), `WSTransfer`
(`:95`), `WSEnumeration` (`:97`) et `LdapQuery` (`:105`), avec les préfixes
`ad`, `addata`, `xsi`, `xsd`, `da`, `wst`, `wsen`, `adlq` déclarés en les
constantes du service ADWS Microsoft. L'implémentation Python est donc
alignée sur la référence pour cette table. La même source déclare les
dialectes que les exemples de ce chapitre reprennent : `XPathLvl1Selection`
(`:99`), `QNameSelection` (`:101`), `XPath10SubsetQuery` (`:103`).

Deux constantes de la table Python n'apparaissent **pas** dans `NS_DECL` :
`WSEV` et `SERA`. Elles sont déclarées localement par les corps qui en ont
besoin, `subscribe.py:37` pose `xmlns:wse="{WSEV}"`, `ca_elements.py:22` et
`:26` posent `xmlns:sera`. Un corps qui oublierait la déclaration produirait
un préfixe non lié, donc un XML rejeté par le lecteur .NET.

### Deux familles d'enveloppes dans le code

Il faut savoir qu'**il existe deux générateurs d'enveloppe** dans
l'implémentation, ce qui est une dette technique assumée et une source de
divergence à surveiller. Le dossier `classes/handlers/` contient trente et
un fichiers de handler ; trois d'entre eux ne sont que des façades de
routage et ne fabriquent aucune enveloppe (`crud.py`, `transfer.py`,
`search.py`). Restent **vingt-huit** producteurs d'enveloppe, répartis ainsi
:

- **Famille A : `SoapEnvelope.wrap`, appelée via `self.envelope.wrap`.**
  Vingt-quatre handlers, dont `create.py:90`, `modify.py:75`,
  `delete.py:32`, `get_status.py:30`, `renew.py:28`, `schema.py:76`,
  `groups.py:38`, `set_password.py:24`, `get_version.py:20`,
  `subscribe.py:27` et l'ensemble des handlers d'actions personnalisées.
  L'alias `self.envelope` est posé une fois pour toutes dans
  `BaseHandler.__init__` (`classes/handlers/base.py:26`). `wrap` déclare les
  onze préfixes de `NS_DECL` et échappe `action` et `relates_to` avec
  `html.escape` (`soap_envelope.py:38-39`).
- **Famille B : enveloppes écrites à la main.** Quatre handlers construisent
  leur enveloppe littéralement : `get.py:167-188` et `get.py:279-300`,
  `enumerate.py:109-127`, `pull.py:93-114`, `release.py:43-55`. Ils ne
  déclarent que le sous-ensemble de préfixes dont ils ont besoin.

| Handler | Préfixes déclarés | Ancrage |
|---|---|---|
| `get.py` (RootDSE) | `s a ad addata da xsi xsd` | `get.py:169-177` |
| `get.py` (objet) | `s a ad addata da xsi xsd` | `get.py:281-289` |
| `enumerate.py` | `s a wsen` | `enumerate.py:111-113` |
| `pull.py` | `s a wsen addata ad xsi xsd` | `pull.py:95-101` |
| `release.py` | `s a` | `release.py:45-46` |

Deux divergences de forme séparent les deux familles : la famille B ne passe
pas par `_minify` mais applique son propre `re.sub(r'>\s+<', '><', …)`
(`get.py:190` et `:302`) ou s'écrit d'emblée sans blancs ; et
`release.py:53` émet un `<s:Body />` auto-fermé là où `wrap` émet toujours
`<s:Body>…</s:Body>` (`soap_envelope.py:41`).

> **Écart notable.** Dans la famille B, `enumerate.py:118`, `pull.py:106` et
> `release.py:51` appliquent `html.escape(context.message_id)`, alors que
> `get.py:182` et `get.py:294` insèrent `context.message_id` **brut**. Un
> `MessageID` contenant `&` ou `<` produirait donc un XML de réponse
> malformé sur le chemin Get. En pratique le client émet toujours un
> `urn:uuid:` ASCII, mais la dissymétrie est réelle et vérifiable.

`ENV_NS_MAP` (`src/soap/namespaces.py:18-30`) est une table préfixe → URI
définie mais **jamais consommée** dans l'arbre courant : ce n'est pas une
source de vérité pour la sérialisation, seul `NS_DECL` l'est.

## En-têtes WS-Addressing

### Ce que la spécification impose

WS-Addressing 1.0 définit une famille d'en-têtes de type *Message Addressing
Properties* placés dans `<s:Header>` :

| En-tête | Cardinalité (spec) | Sens |
|---|---|---|
| `a:Action` | obligatoire | Sémantique de l'opération, sous forme d'URI |
| `a:MessageID` | requis si réponse attendue | Identifiant unique du message |
| `a:To` | optionnel | Destination du message |
| `a:ReplyTo` | requis si `MessageID` présent | Où renvoyer la réponse |
| `a:FaultTo` | optionnel | Où renvoyer les fautes |
| `a:RelatesTo` | obligatoire en réponse | Corrélation vers le `MessageID` |

`a:RelatesTo` porte un attribut optionnel `RelationshipType` dont la valeur
par défaut est la relation « réponse ». Le projet ne l'émet jamais et
s'appuie sur ce défaut, ce que le client accepte.

### Ce que le client Windows envoie réellement

Le module `ActiveDirectory` ouvre un canal `net.tcp` **orienté session et
bidirectionnel au niveau transport**. Les quatre contrats de service de la
référence portent tous `SessionMode = SessionMode.Required` et
`ProtectionLevel = ProtectionLevel.EncryptAndSign` : le contrat Resource du
service Microsoft, le contrat Enumeration du service Microsoft, le contrat
AccountManagement du service Microsoft et le contrat TopologyManagement du
service Microsoft.

Deux précisions s'imposent. `EncryptAndSign` est la contrepartie
contractuelle du scellement GSSAPI : le service **refuse** un message non
chiffré, ce qui interdit tout mode « en clair pour déboguer » sans modifier
le binding. Et aucun de ces contrats ne déclare de `CallbackContract` : ce
sont des contrats **requête-réponse** (`Message Get(Message request)`, le
contrat Resource du service Microsoft), pas des contrats duplex au sens WCF.
Le canal est bidirectionnel parce que le transport l'est, pas parce que le
contrat le demande.

La réponse revient donc sur la **même connexion TCP** que la requête, et
`a:ReplyTo` porte l'adresse anonyme
`http://www.w3.org/2005/08/addressing/anonymous`, qui signifie exactement
cela. Un en-tête typique en entrée :

```xml
<s:Header>
  <a:Action s:mustUnderstand="1">
    http://schemas.xmlsoap.org/ws/2004/09/transfer/Get</a:Action>
  <a:MessageID>urn:uuid:ece4c158-8f5b-4a2e-9f11-1c0b57d6b2f0</a:MessageID>
  <a:ReplyTo>
    <a:Address>http://www.w3.org/2005/08/addressing/anonymous</a:Address>
  </a:ReplyTo>
  <a:To s:mustUnderstand="1">
    net.tcp://samba.local:9389/ActiveDirectoryWebServices/Windows/Resource</a:To>
  <ad:objectReferenceProperty>CN=Administrator,CN=Users,DC=samba,DC=local
    </ad:objectReferenceProperty>
  <ad:instance>ldap:389</ad:instance>
</s:Header>
```

`s:mustUnderstand="1"` sur `a:Action` et `a:To` est la convention WCF : un
récepteur qui ne comprend pas l'en-tête doit lever une faute
`MustUnderstand` plutôt que l'ignorer silencieusement. **Ce serveur
n'implémente aucune vérification `mustUnderstand`** : il ne fait que le
**réémettre** sur `a:Action` en sortie (`classes/soap/soap_envelope.py:38`
et, pour la famille B, `get.py:179`, `get.py:291`, `enumerate.py:115`,
`pull.py:103`, `release.py:48`). C'est un écart au niveau 1 sans conséquence
observée au niveau 2.

Chez Microsoft, en revanche, `mustUnderstand` est bel et bien appliqué, par
la pile WCF, pas par le code ADWS. La preuve en est que la référence
installe deux `IDispatchMessageInspector` dont l'unique travail est
d'ajouter les en-têtes propriétaires à `Headers.UnderstoodHeaders`, faute de
quoi WCF lèverait une faute `MustUnderstand` sur ses propres messages :

| Inspecteur | En-tête marqué compris | Espace de noms | Ancrage |
|---|---|---|---|
| `ObjectIdAndInstanceInformationInspector` | `objectReferenceProperty` | `AD` | Service ADWS Microsoft |
| `ObjectIdAndInstanceInformationInspector` | `instance` | `AD` | Service ADWS Microsoft |
| `IdentityManagementMessageInspector` | `IdentityManagementOperation` | `DA` | Service ADWS Microsoft |

Deux détails de ces inspecteurs éclairent le protocole : l’inspecteur
d’en-têtes du service Microsoft exclut nommément `…/transfer/Create` et
`…/enumeration/Enumerate` du marquage d'`objectReferenceProperty`, et
l’inspecteur de messages IMDA du service Microsoft sort immédiatement sur
`…/transfer/Delete`, un `Delete` n'est jamais une opération IMDA. Ce serveur
n'a pas à reproduire ces règles puisqu'il ne vérifie rien, mais elles
indiquent quels messages portent réellement quels en-têtes.

### Ce que cette implémentation lit et écrit

`RequestContext.from_xml` (`classes/parsing/context.py:37-169`) est le seul
point d'extraction des en-têtes d'adressage. Son comportement, en-tête par
en-tête :

| En-tête | Lu ? | Où | Remarque |
|---|---|---|---|
| `a:Action` | oui | `context.py:55-58` | XPath `.//a:Action`, repli sans NS |
| `a:MessageID` | oui | `context.py:60-62` | XPath `.//a:MessageID`, repli sans NS |
| `a:To` | partiel | `create.py:75` | regex sur le XML brut, Create seulement |
| `a:ReplyTo` | non | — | ignoré (canal duplex, réponse en ligne) |
| `a:FaultTo` | non | — | non implémenté dans ce projet |
| `a:RelatesTo` | n/a | — | jamais reçu, toujours émis |
| `ad:objectReferenceProperty` | oui | `context.py:64` | XPath `.//`, en-tête ou corps |
| `ad:instance` | **non** | — | jamais lu par ce serveur |
| `da:IdentityManagementOperation` | oui | `context.py:67` | bascule `is_imda` |

La table de préfixes de ces XPath est déclarée en dur dans
`context.py:44-52` : sept entrées (`soap`, `soap11`, `a`, `ad`, `da`,
`wsen`, `adlq`) et **ni `ca`, ni `addata`, ni `wst`**. Les corps d'actions
personnalisées sont donc parsés ailleurs, par `BodyParser`, qui porte sa
propre table (`body_parser.py:7-14`). `soap11` y figure sans jamais servir :
ADWS est exclusivement SOAP 1.2.

Deux points appellent une remarque.

**Le repli sans espace de noms.** Si `.//a:Action` ne trouve rien, le code
retente `.//Action` sans espace de noms (`context.py:57-58`, `61-62`). C'est
une tolérance défensive utile face à un décodeur WCF qui aurait perdu les
préfixes ; elle n'est exigée par aucune spec.

**Le XPath `.//`, pas `s:Header/`.** Les recherches portent sur le document
entier. Un `<a:Action>` figurant dans le corps serait donc capté : robuste
face aux variations de sérialisation WCF, mais laxiste. Le risque de
détournement du routage est borné par le fait que la connexion est
authentifiée Kerberos et scellée avant d'atteindre cette couche.

**Valeur par défaut.** Si aucune action n'est trouvée, `context.action` vaut
la chaîne `"Unknown"` (`context.py:153`) ; si aucun `MessageID` n'est
trouvé, `context.message_id` vaut la chaîne vide (`context.py:154`). Le
premier cas conduit à une faute « Unknown action » ; le second conduit à un
`<a:RelatesTo></a:RelatesTo>` vide, voir ci-dessous.

### Le format `urn:uuid:` et la corrélation

Le `MessageID` produit par WCF est un URN UUID, forme `urn:uuid:` + un GUID
canonique 8-4-4-4-12 en minuscules. Le serveur ne valide **pas** ce format
et ne le régénère pas : il le traite comme une chaîne opaque à recopier.
C'est exactement le contrat attendu, la spec n'impose qu'une chose,
l'**égalité octet pour octet** entre le `MessageID` de la requête et le
`RelatesTo` de la réponse. Le test `test_relates_to`
(`tools/test/test_handlers.py:54-59`) vérifie précisément cette égalité avec
une valeur volontairement non-UUID (`urn:uuid:rt-9`), ce qui confirme que la
recopie est bien littérale.

Règles de corrélation appliquées par le serveur : toute réponse et toute
faute portent `<a:RelatesTo>` égal au `MessageID` de la requête, y compris
quand l'erreur survient avant l'appel du handler ; le serveur n'émet jamais
de `MessageID` propre ; et hors WS-Enumeration, où le lien est porté par
`<wsen:EnumerationContext>` dans le corps, il n'existe aucune corrélation
multi-messages.

### Pourquoi l'absence de `RelatesTo` bloque PowerShell jusqu'au timeout

Le canal `net.tcp` porte plusieurs messages sur une même session : côté
client, c'est la pile WCF, pas le module `ActiveDirectory`, qui décide à qui
remettre un message entrant. Son algorithme est celui de WS-Addressing :

1. Le client émet la requête et enregistre son `MessageID` dans une
  table de corrélation, puis bloque sur l'attente d'une réponse.
2. Un message arrive sur le canal. WCF lit son `<a:RelatesTo>`.
3. Si `RelatesTo` correspond à une entrée de la table, la réponse est
  remise à l'appelant bloqué et le `Task` se termine.
4. Si `RelatesTo` est **absent** ou ne correspond à rien, le message
  n'appartient à aucune requête en cours. Sur un canal requête-réponse sans
  `CallbackContract`, ce qui est le cas de tous les contrats ADWS, il
  n'existe aucune destination pour un message non sollicité : il est
  **abandonné**.
5. L'appelant n'a donc jamais été réveillé. Il reste bloqué jusqu'à
  l'expiration du timeout de réception du binding, puis la cmdlet remonte
  une erreur de délai, et non l'erreur réelle, qui a été perdue.

> **Statut de cette description.** Les étapes 1 à 3 sont le comportement
> normatif de WS-Addressing. Les étapes 4 et 5 sont une **inférence**
> cohérente avec l'absence de `CallbackContract` dans les contrats de la
> référence et avec `documentation/06-depannage.md` § 6, mais elles se
> produisent dans la pile WCF du client, hors du périmètre observable de ce
> dépôt. Le fait observable (pas de `RelatesTo`, cmdlet bloquée jusqu'au
> timeout) est en revanche solidement établi.

L'effet pratique le plus pernicieux : **une faute mal formée est pire qu'une
absence de réponse**, parce qu'elle consomme le temps du timeout tout en
masquant la cause. Le code garantit l'invariant en trois endroits :

- **`SoapEnvelope.wrap`** (`classes/soap/soap_envelope.py:39`) émet
  `<a:RelatesTo>` **inconditionnellement**, y compris vide :
  `html.escape(relates_to or "")`. Il n'existe aucun chemin qui produise une
  enveloppe sans cet élément.
- **`SoapEnvelope.fault`** (`classes/soap/soap_envelope.py:46-59`) délègue à
  `wrap`. Toutes les fautes héritent donc de la garantie ; c'est la raison
  pour laquelle `fault` n'est pas un générateur indépendant.
- **`ADWSDispatcher._fault`** (`classes/handlers/dispatcher.py:52-55`) :

```python
@staticmethod
def _fault(context: Optional[RequestContext], message: str) -> str:
    relates_to = context.message_id if context else ""
    return SoapEnvelope.fault(relates_to, "s:Receiver", message)
```

Le paramètre `context` est **`Optional`** parce que l'erreur peut survenir
*pendant* `RequestContext.from_xml`. Le cas nominal est documenté : un XML
mal décodé fait échouer `ET.fromstring` (`context.py:41`) avec
`xml.etree.ElementTree.ParseError: undefined entity`, que le `except
Exception` de `context.py:168-169` **rehabille en `ValueError`** (`raise
ValueError(f"Failed to parse request XML: {str(e)}") from e`). Ce
`ValueError` n'étant **pas** une `ADWSException`, il tombe dans le second
`except` du dispatcher et produit une stack trace complète dans
`journalctl`, la signature exacte décrite par
`documentation/06-depannage.md` § 9. Le dispatcher initialise `context =
None` (`dispatcher.py:22`) avant le `try` et ne le renseigne qu'après le
parsing réussi (`dispatcher.py:25`) ; dans le cas dégradé, `relates_to` vaut
la chaîne vide.

> **Limite connue et non corrigée.** Un `<a:RelatesTo></a:RelatesTo>` vide
> est syntaxiquement présent mais sémantiquement inutile : il ne corrèle
> rien, donc blocage jusqu'au timeout, exactement comme s'il était absent.
> **Quand la requête est illisible au point que son `MessageID` n'est pas
> extractible, aucune faute exploitable ne peut être renvoyée.** La seule
> parade est de ne jamais échouer au parsing, d'où l'importance structurelle
> du correctif d'entités XML de `src/wcf/records/text.py`
> (`documentation/06-depannage.md` § 9). Une amélioration possible serait
> d'extraire le `MessageID` par expression régulière sur le XML brut avant
> de tenter `ET.fromstring`, en dernier recours.

### Valeur d'`a:Action` en réponse

En réponse, l'action est celle de l'opération suffixée de `Response`. Pour
`Get`, la requête porte `…/transfer/Get` et la réponse
`…/transfer/GetResponse` ; `Put` et `Delete` suivent la même règle.

Dans ce projet, **vingt-deux handlers sur vingt-huit** portent cette valeur
dans une constante de classe `REPLY_ACTION`. Les six autres ne l'ont pas :
`GetHandler`, `EnumerateHandler`, `PullHandler` et `ReleaseHandler` écrivent
l'URI en dur dans leur enveloppe manuelle, `SchemaHandler` la construit dans
une variable locale (`schema.py:75`) et `GroupHandler` la calcule à
l'exécution (`groups.py:37`). Le catalogue plus bas donne les vingt-huit
valeurs avec leur ancrage exact.

Pour les fautes, la valeur par défaut de ce serveur est
`_DEFAULT_FAULT_ACTION = "http://www.w3.org/2005/08/addressing/soap/fault"`
(`classes/soap/soap_envelope.py:18`), c'est-à-dire l'action de faute
**WS-Addressing 1.0**. Le service Microsoft, lui, ne l'emploie jamais : elle
déclare des actions de faute par famille, portées par l'attribut fautes
déclarées par les contrats. Les six valeurs suivantes sont toutes vérifiées
dans le code de référence :

| Action de faute de la référence | Ancrage |
|---|---|
| `http://schemas.xmlsoap.org/ws/2004/08/addressing/fault` | Service ADWS Microsoft |
| `http://schemas.dmtf.org/wbem/wsman/1/wsman/fault` | Service ADWS Microsoft |
| `http://schemas.microsoft.com/2006/11/…/DirectoryAccess/fault` | Service ADWS Microsoft |
| `http://schemas.xmlsoap.org/ws/2004/09/transfer/fault` | Service ADWS Microsoft |
| `http://schemas.xmlsoap.org/ws/2004/09/enumeration/fault` | Service ADWS Microsoft |
| `http://schemas.microsoft.com/2008/1/ActiveDirectory/Data/fault` | Service ADWS Microsoft |

Le projet n'utilise que la dernière, via `FAULT_NS`, et uniquement pour les
fautes d'actions personnalisées (`classes/faults/faults.py:40`). Sur ce
point précis il est **exactement conforme** : le générateur de fautes du
service ADWS Microsoft et `:491` passent la même URI comme `faultAction`
pour toutes les `CustomActionFault`. Pour tout le reste, **écart assumé :**
la valeur d'`a:Action` d'une faute compte peu pour le client tant que
`RelatesTo` est correct, mais l'aligner rendrait les captures plus lisibles
et le mapping vers les fautes déclarées plus direct.

## Le référencement d'objet : ResourceReference, InstanceId, ObjectReferenceProperty

### Ce que fait le vrai ADWS

Contrairement à ce que suggérait une version antérieure de
`documentation/03-protocole.md`, le service Microsoft n'utilise **pas** un
bloc `<wsa:ResourceReference><wsa:InstanceId>…`. Il utilise **deux en-têtes
SOAP plats**, tous deux dans l'espace de noms
`http://schemas.microsoft.com/2008/1/ActiveDirectory` :

| En-tête | Type | Rôle |
|---|---|---|
| `ad:objectReferenceProperty` | chaîne | Identifie l'objet cible |
| `ad:instance` | chaîne | Identifie l'instance d'annuaire visée |

C'est vérifiable en deux endroits du code de référence : l’inspecteur
d’en-têtes du service Microsoft et `:23` recherchent exactement ces deux
noms par `request.Headers.FindHeader(nom,
"http://schemas.microsoft.com/2008/1/ActiveDirectory")` et les marquent
comme *understood* ; le service ADWS Microsoft et `:1611` les relisent par
`GetHeader<string>` pour construire l'identifiant d'objet
(`DirectoryObjectIdentifier`). Les constantes correspondantes sont
`objectReferenceProperty` et `WebServiceStrings.Instance = "instance"`.

Comportements observables importants de la référence :

- **`ad:objectReferenceProperty` n'est exigé que pour `Get`, `Delete` et
  `Put`.** Le test est explicite en le service ADWS Microsoft : `if
  (operation == RequestType.Get || operation == RequestType.Delete ||
  operation == RequestType.Put)`. Dans ce bloc, un en-tête absent ou vide
  provoque une erreur d'argument portant
  `MustSpecifyObjectRefPropInTheHeader` . Hors de ces trois actions,
  l'en-tête n'est simplement pas lu.
- **Ne pas confondre avec l'exclusion de l'inspecteur.** l’inspecteur
  d’en-têtes du service Microsoft exclut `Create` et `Enumerate` du
  **marquage `UnderstoodHeaders`**, ce qui n'est pas la même chose que « non
  requis » : c'est une décision sur `mustUnderstand`, prise avant même que
  le service ne regarde le message.
- **`ad:instance` est exigé pour toutes les opérations**, sans condition :
  le service le lit systématiquement, et une absence ou une valeur vide
  provoque une erreur d'argument explicite.
- La valeur d'`objectReferenceProperty` est **soit un GUID canonique de 36
  caractères**, **soit un DN**. Le test est `text.Length == 36 &&
  guidRegex.IsMatch(text)`, le motif étant
  `^[0-9a-fA-F]{8}-…-[0-9a-fA-F]{12}$`. Si la chaîne matche, elle est
  convertie en `Guid` ; sinon elle est rangée comme DN. Les deux formes
  coexistent sur le fil, et le `Get-ADUser -Identity` d'un GUID comme d'un
  DN emprunte le même en-tête.
- La valeur d'`instance` est une chaîne de la forme `LdapInstancePrefix +
  port`, soit `ldap:389` pour l'instance NTDS par défaut. Les constantes
  sont toutes dans les constantes du service ADWS Microsoft :

| Constante | Valeur | Ligne |
|---|---|---|
| `LdapInstancePrefix` | `ldap:` | `:79` |
| `AdLdapPort` | `389` | `:65` |
| `AdLdapsPort` | `636` | `:67` |
| `AdGcPort` | `3268` | `:69` |
| `AdGcsPort` | `3269` | `:71` |
| `AddsInstanceName` | `NTDS` | `:75` |
| `AddsGcInstanceName` | `GC` | `:77` |

Les adresses d'endpoint des exemples viennent de la même source :
`"net.tcp://"` (`:15`) + hôte + `":9389/ActiveDirectoryWebServices"` (`:17`)
+ `"Windows/"` (`:23`) + le nom d'endpoint, à choisir parmi `Resource`
(`:27`), `ResourceFactory` (`:29`), `Enumeration` (`:31`), `mex` (`:33`),
`AccountManagement` (`:35`) et `TopologyManagement` (`:37`). La branche
alternative `"UserName/"` (`:25`) n'est pas gérée par ce serveur, qui
n'accepte que Kerberos.

### Le GUID de la RootDSE

La valeur `11111111-1111-1111-1111-111111111111` n'est **pas** un «
InstanceId » : c'est `rootDSEGuid` , le GUID conventionnel par lequel le
client désigne la RootDSE dans `objectReferenceProperty`. Le projet le
reconnaît en entrée et le réémet en sortie :

- **En entrée** : `GetHandler.handle` (`classes/handlers/get.py:39-43`)
  route vers la RootDSE si `object_reference` est vide, vaut `'root dse'`
  (insensible à la casse) ou vaut ce GUID, la comparaison étant elle aussi
  faite en minuscules (`get.py:42`).
- **En sortie** : `get.py:153-159` place ce même GUID dans
  `<ad:objectReferenceProperty>` du corps WS-Transfer de la réponse RootDSE.
  Attention : ce bloc n'est émis que dans la branche **non-IMDA**
  (`get.py:152`) ; en IMDA la RootDSE sort en
  `<da:BaseObjectSearchResponse>` sans référence d'objet (`get.py:146-151`).

À nuancer : la constante `WebServiceStrings.InstanceId = "InstanceId"`
**existe**. Ce qui est faux, c'est de la relier au GUID de la RootDSE ou
d'en faire l'en-tête du couple objet/instance : sur le fil, ce couple est
porté par `objectReferenceProperty` et `instance`, et par rien d'autre.

### Ce que cette implémentation extrait

Le dataclass `RequestContext` (`classes/parsing/context.py:11`) ne possède
qu'**un seul** champ pour l'identification d'objet : `object_reference`
(`context.py:15`). Il est peuplé en `context.py:64` par :

```python
object_ref = root.findtext('.//ad:objectReferenceProperty', namespaces=ns)
```

Conséquences, à connaître :

- Le XPath est `.//`, donc l'élément est cherché **partout dans le
  document**, en-tête comme corps. Un `<ad:objectReferenceProperty>` présent
  dans un `<da:AddRequest>` serait donc capté comme cible. C'est neutralisé
  côté Create par le filtre `CreateHandler.DN_ROUTING`
  (`classes/handlers/create.py:23-25`), qui écarte `distinguishedname`,
  `relativedistinguishedname` et `container-hierarchy-parent` des attributs
  LDAP réellement écrits, et par `_resolve_dn` (`create.py:54-64`) qui
  reconstruit le DN cible à partir du RDN et du parent.
- **L'en-tête `ad:instance` n'est jamais lu.** Ce serveur est mono-instance
  par construction (il parle au `SamDB` local). `InstanceIndex`
  (`classes/directory/instance_index.py`) enregistre bien deux instances,
  `primary` (`localhost:389`, `NTDS`) et `gc` (`localhost:3268`, `GC`), et
  `ServiceContext` l'expose (`classes/server/service_context.py:17`), mais
  **aucun handler ne consulte cette table** pour router une requête. Le
  service accepte donc n'importe quelle valeur d'`ad:instance`, y compris
  aucune. C'est une simplification, pas un bug : il n'y a rien d'autre à
  atteindre.
- **L'en-tête `ad:identity` n'existe pas** dans le protocole ni dans ce
  code. L'identité de l'appelant est portée par le contexte GSSAPI de la
  connexion, pas par un en-tête SOAP, cf. `connection.py:56`, qui construit
  le `session_info` transmis au dispatcher (`connection.py:57`), lequel le
  pousse dans chaque `BaseHandler` via le `HandlerRegistry`
  (`handler_registry.py:12`) puis dans `SambaDB` (`base.py:21`). Toute
  mention d'un en-tête `identity` serait une invention.
- **Un en-tête `mustUnderstand` propre à une action personnalisée est
  ignoré.** le contrat SetPassword du service Microsoft déclare un en-tête
  de message obligatoire nommé `Server` : le vrai client peut donc désigner
  un serveur cible dans l'en-tête d'un `SetPassword`.
  `SetPasswordHandler._extract` (`classes/handlers/set_password.py:31-37`)
  ne lit que `AccountDN` et `NewPassword` ; ni `Server`, ni le membre de
  corps `PartitionDN` ne sont consultés. Sans conséquence sur un DC unique,
  mais à savoir avant tout scénario multi-serveurs.

### L'EPR de retour : `wst:ResourceCreated`

La seule référence d'objet **émise** par le serveur sous forme d'EPR
WS-Addressing est celle de la réponse `Create`
(`classes/handlers/create.py:74-90`) :

```xml
<wst:ResourceCreated
    xmlns:wst="http://schemas.xmlsoap.org/ws/2004/09/transfer"
    xmlns:wsa="http://www.w3.org/2005/08/addressing"
    xmlns:ad="http://schemas.microsoft.com/2008/1/ActiveDirectory">
  <wsa:Address>net.tcp://samba.local:9389/ActiveDirectoryWebServices/Windows/Resource
    </wsa:Address>
  <wsa:ReferenceParameters>
    <ad:objectReferenceProperty>f6aac55f-…-…-…</ad:objectReferenceProperty>
    <ad:instance>ldap:389</ad:instance>
  </wsa:ReferenceParameters>
</wst:ResourceCreated>
```

Trois détails ancrés dans le code :

1. L'adresse est obtenue en relisant `<a:To>` de la requête par
  expression régulière (`create.py:75`) puis en substituant
  `ResourceFactory` par `Resource` (`create.py:76`). C'est la traduction
  fidèle du fait que `Create` arrive sur l'endpoint fabrique
  (`WcfResourceFactoryEndpoint`) alors que les opérations ultérieures sur
  l'objet visent l'endpoint ressource (`WcfResourceEndpoint`). Si `<a:To>`
  est introuvable, le repli est l'adresse anonyme (`create.py:77`).
2. L'`objectReferenceProperty` renvoyé est le **GUID** de l'objet
  fraîchement créé, relu par une recherche LDB sur `objectGUID`
  (`create.py:67-71`) et converti par `uuid.UUID(bytes_le=…)`. En cas
  d'échec de relecture, c'est le GUID nul qui est renvoyé
  (`uuid.UUID(int=0)`), ce qui est une valeur de repli discutable mais
  explicite.
3. L'`ad:instance` est codé en dur à `ldap:389` (`create.py:86`),
  conforme à la constante de la référence.

Le préfixe employé dans ce corps est `wsa:`, redéclaré localement, alors que
l'enveloppe déclare déjà `a:` pour la même URI : légal en XML, sans effet
côté client, mais incohérent stylistiquement.

### Les synthétiques du corps, à ne pas confondre

`objectReferenceProperty` apparaît aussi **dans le corps** des objets
sérialisés, comme attribut synthétique. `SYNTHETIC_KEYS`
(`classes/serialization/object_projector.py:9-12`) énumère les quatre noms
concernés : `distinguishedname`, `relativedistinguishedname`,
`objectreferenceproperty`, `containerhierarchyparent`. Ils sont rendus par
`_synthetic` (`object_projector.py:48-53`) en espace `ad:`, **sans**
attribut `LdapSyntax` et toujours avec `xsi:type="xsd:string"`. Ils sont
retirés du flux d'attributs normaux par `_normal`
(`object_projector.py:41-46`) pour éviter un doublon
`<addata:distinguishedName>`.

> À distinguer strictement : `<ad:objectReferenceProperty>` du corps porte
> le **identifiant global** de l'objet en forme canonique `xsd:string` ;
> l'attribut LDAP `objectGUID` sort, lui, en `xsd:base64Binary` du binaire
> brut (cf. `documentation/04-handlers.md`, section format fil). Confondre
> les deux produit un objet que le client refuse de désérialiser.

## Catalogue des actions SOAP et routage

### L'algorithme de résolution

`HandlerRegistry.resolve` (`classes/handlers/handler_registry.py:15-23`)
tient en neuf lignes et procède en deux temps :

```python
def resolve(self, action_url: str) -> Optional[BaseHandler]:
    if not action_url:
        return None
    normalized = action_url.lower()
    key = ACTION_HANDLER_KEYS.get(normalized)
    if key:
        return self._handlers.get(key)
    suffix = action_url.rsplit("/", 1)[-1]
    return self._handlers.get(suffix)
```

- **1. Correspondance exacte, insensible à la casse.** L'URI complète est
  passée en minuscules et cherchée dans `ACTION_HANDLER_KEYS`
  (`src/handlers/handler_routing.py:35-51`), dont **toutes les clés sont
  déjà en minuscules**, c'est un invariant tacite du fichier : une clé
  écrite en casse mixte y serait morte.
- **2. Repli sur le dernier segment d'URL, sensible à la casse.**
  `action_url.rsplit("/", 1)[-1]` est cherché tel quel dans le dictionnaire
  d'instances, dont les clés viennent de `HANDLER_FACTORIES`
  (`handler_routing.py:53-71`) et sont en `PascalCase`. Un client qui
  émettrait `…/getversion` en minuscules ne serait donc **pas** routé par ce
  second mécanisme.

Les handlers sont instanciés **une fois par connexion**, à la construction
du registre (`handler_registry.py:11-13`), donc une fois par process fils du
`ForkingTCPServer`. C'est cohérent avec l'invariant projet « jamais de
`SamDB` au niveau module » : chaque `BaseHandler.__init__`
(`classes/handlers/base.py:19-29`) construit son propre `SambaDB`.

Si aucun handler ne répond, `ADWSDispatcher._invoke` (`dispatcher.py:37-43`)
lève une `ADWSException` dont le message énumère toutes les clés connues, ce
qui rend le diagnostic immédiat dans `journalctl`.

### Table 1 — correspondances exactes (`ACTION_HANDLER_KEYS`)

Quatorze entrées, recopiées de `src/handlers/handler_routing.py:35-51`. La
colonne « Clé » est la valeur cherchée ensuite dans `HANDLER_FACTORIES`.

| URI d'action (en minuscules dans le code) | Clé |
|---|---|
| `http://schemas.xmlsoap.org/ws/2004/09/transfer/get` | `Get` |
| `http://schemas.xmlsoap.org/ws/2004/09/transfer/put` | `Put` |
| `http://schemas.xmlsoap.org/ws/2004/09/transfer/delete` | `Delete` |
| `http://schemas.xmlsoap.org/ws/2004/09/transfer/create` | `Create` |
| `http://schemas.xmlsoap.org/ws/2004/09/enumeration/enumerate` | `Enumerate` |
| `http://schemas.xmlsoap.org/ws/2004/09/enumeration/pull` | `Pull` |
| `http://schemas.xmlsoap.org/ws/2004/09/enumeration/release` | `Release` |
| `http://schemas.xmlsoap.org/ws/2004/09/enumeration/renew` | `Renew` |
| `http://schemas.xmlsoap.org/ws/2004/09/enumeration/getstatus` | `GetStatus` |
| `http://schemas.xmlsoap.org/ws/2004/08/eventing/subscribe` | `Subscribe` |
| `http://schemas.xmlsoap.org/ws/2004/08/eventing/unsubscribe` | `Unsubscribe` |
| `http://schemas.xmlsoap.org/ws/2004/08/eventing/renew` | `SubscriptionRenew` |
| `http://schemas.xmlsoap.org/ws/2004/08/eventing/getstatus` | `SubscriptionStatus` |
| `…/2008/1/ActiveDirectory/CustomActions/AccountManagement/Notify` | `Notify` |

> **Raison d'être de cette table.** Sans elle, `…/eventing/Renew` et
> `…/enumeration/Renew` partageraient le même dernier segment `Renew` et
> tomberaient tous deux sur `RenewHandler` (contexte d'énumération). Idem
> pour `GetStatus`. Les clés `SubscriptionRenew` et `SubscriptionStatus`
> sont donc **inatteignables par le repli sur suffixe** : elles n'existent
> que grâce à la correspondance exacte. C'est la seule collision réelle du
> catalogue, et elle est correctement traitée.

### Table 2 — catalogue exhaustif action → handler → fichier → cmdlet

Vingt-neuf clés sont enregistrées dans `HANDLER_FACTORIES`
(`handler_routing.py:53-71`). Le tableau ci-dessous les couvre toutes.
Abréviations d'URI : `WST` =
`http://schemas.xmlsoap.org/ws/2004/09/transfer`, `WSEN` =
`http://schemas.xmlsoap.org/ws/2004/09/enumeration`, `WSEV` =
`http://schemas.xmlsoap.org/ws/2004/08/eventing`, `CA` =
`http://schemas.microsoft.com/2008/1/ActiveDirectory/CustomActions`.

| Action SOAP | Clé | Classe de handler | Fichier |
|---|---|---|---|
| `WST/Get` | `Get` | `GetHandler` | `classes/handlers/get.py` |
| `WST/Put` | `Put` | `TransferHandler` | `classes/handlers/transfer.py` |
| `WST/Delete` | `Delete` | `TransferHandler` | `classes/handlers/transfer.py` |
| `WST/Create` | `Create` | `CRUDHandler` | `classes/handlers/crud.py` |
| `WSEN/Enumerate` | `Enumerate` | `EnumerateHandler` | `classes/handlers/enumerate.py` |
| `WSEN/Pull` | `Pull` | `PullHandler` | `classes/handlers/pull.py` |
| `WSEN/Release` | `Release` | `ReleaseHandler` | `classes/handlers/release.py` |
| `WSEN/Renew` | `Renew` | `RenewHandler` | `classes/handlers/renew.py` |
| `WSEN/GetStatus` | `GetStatus` | `GetStatusHandler` | `classes/handlers/get_status.py` |
| `WSEV/Subscribe` | `Subscribe` | `SubscribeHandler` | `classes/handlers/subscribe.py` |
| `WSEV/Unsubscribe` | `Unsubscribe` | `UnsubscribeHandler` | `classes/handlers/unsubscribe.py` |
| `WSEV/Renew` | `SubscriptionRenew` | `SubscriptionRenewHandler` | `classes/handlers/subscription_renew.py` |
| `WSEV/GetStatus` | `SubscriptionStatus` | `SubscriptionStatusHandler` | `classes/handlers/subscription_status.py` |
| `CA/AccountManagement/GetADGroupMember` | `GetADGroupMember` | `GetADGroupMemberHandler` | `classes/handlers/get_ad_group_member.py` |
| `CA/AccountManagement/GetADPrincipalGroupMembership` | `GetADPrincipalGroupMembership` | `GetADPrincipalGroupMembershipHandler` | `classes/handlers/get_ad_principal_group_membership.py` |
| `CA/AccountManagement/GetADPrincipalAuthorizationGroup` | `GetADPrincipalAuthorizationGroup` | `GetADPrincipalAuthorizationGroupHandler` | `classes/handlers/get_ad_principal_authorization_group.py` |
| `CA/AccountManagement/SetPassword` | `SetPassword` | `SetPasswordHandler` | `classes/handlers/set_password.py` |
| `CA/AccountManagement/ChangePassword` | `ChangePassword` | `ChangePasswordHandler` | `classes/handlers/change_password.py` |
| `CA/AccountManagement/TranslateName` | `TranslateName` | `TranslateNameHandler` | `classes/handlers/translate_name.py` |
| `CA/AccountManagement/Notify` | `Notify` | `NotifyHandler` | `classes/handlers/notify.py` |
| `CA/TopologyManagement/GetADDomain` | `GetADDomain` | `GetADDomainHandler` | `classes/handlers/get_ad_domain.py` |
| `CA/TopologyManagement/GetADDomainController` | `GetADDomainController` | `GetADDomainControllerHandler` | `classes/handlers/get_ad_domain_controller.py` |
| `CA/TopologyManagement/GetADForest` | `GetADForest` | `GetADForestHandler` | `classes/handlers/get_ad_forest.py` |
| `CA/TopologyManagement/GetVersion` | `GetVersion` | `GetVersionHandler` | `classes/handlers/get_version.py` |
| `CA/TopologyManagement/MoveADOperationMasterRole` | `MoveADOperationMasterRole` | `MoveOperationMasterRoleHandler` | `classes/handlers/move_operation_master_role.py` |
| `CA/TopologyManagement/ChangeOptionalFeature` | `ChangeOptionalFeature` | `ChangeOptionalFeatureHandler` | `classes/handlers/change_optional_feature.py` |
| toute URI finissant par `/Search` | `Search` | `SearchHandler` | `classes/handlers/search.py` |
| toute URI finissant par `/Schema` | `Schema` | `SchemaHandler` | `classes/handlers/schema.py` |
| toute URI finissant par `/Groups` | `Groups` | `GroupHandler` | `classes/handlers/groups.py` |

Cmdlet PowerShell déclenchante, action par action. Cette table relève du
**niveau 2** : elle décrit ce que le client émet, ce qui n'est ni dans le
code de ce dépôt ni dans le service : c'est le module `ActiveDirectory` qui
en décide. À lire comme une carte d'usage corroborée par les journaux du
service, non comme une donnée extraite d'un fichier.

| Action SOAP | Cmdlet(s) PowerShell |
|---|---|
| `WST/Get` | `Get-ADRootDSE`, `Get-ADUser`, `Get-ADObject` (identité unique) |
| `WST/Put` | `Set-ADUser`, `Set-ADGroup`, `Set-ADObject`, `Rename-ADObject`, `Move-ADObject` |
| `WST/Delete` | `Remove-ADUser`, `Remove-ADGroup`, `Remove-ADObject` |
| `WST/Create` | `New-ADUser`, `New-ADGroup`, `New-ADComputer`, `New-ADObject` |
| `WSEN/Enumerate` | `Get-AD* -Filter`, `Get-AD* -LDAPFilter`, `Search-ADAccount` |
| `WSEN/Pull` | suite d'un `Enumerate` (implicite, même cmdlet) |
| `WSEN/Release` | fin d'un pipeline d'énumération (implicite) |
| `WSEN/Renew` | prolongation de contexte (implicite, énumérations longues) |
| `WSEN/GetStatus` | interrogation d'état de contexte (implicite) |
| `WSEV/*` | souscription d'événements ; non déclenchée par les cmdlets AD usuelles |
| `CA/…/GetADGroupMember` | `Get-ADGroupMember` |
| `CA/…/GetADPrincipalGroupMembership` | `Get-ADPrincipalGroupMembership` |
| `CA/…/GetADPrincipalAuthorizationGroup` | `Get-ADPrincipalAuthorizationGroup` |
| `CA/…/SetPassword` | `Set-ADAccountPassword -Reset` |
| `CA/…/ChangePassword` | `Set-ADAccountPassword` avec ancien mot de passe |
| `CA/…/TranslateName` | conversion de noms (DN, NT4, UPN, canonique) |
| `CA/…/Notify` | aucune cmdlet identifiée (extension projet) |
| `CA/…/GetADDomain` | `Get-ADDomain` |
| `CA/…/GetADDomainController` | `Get-ADDomainController` |
| `CA/…/GetADForest` | `Get-ADForest` |
| `CA/…/GetVersion` | sonde de version ADWS à la connexion |
| `CA/…/MoveADOperationMasterRole` | `Move-ADDirectoryServerOperationMasterRole` |
| `CA/…/ChangeOptionalFeature` | `Enable-ADOptionalFeature` |
| `…/Search` | aucune cmdlet identifiée (extension projet) |
| `…/Schema` | aucune cmdlet identifiée (extension projet) |
| `…/Groups` | aucune cmdlet identifiée (extension projet) |

#### D'où viennent ces URI, et lesquelles sont des extensions

Il faut distinguer deux façons dont une URI d'action naît dans WCF.

- **Action explicite.** Les contrats WS-Transfer et WS-Enumeration déclarent
  leur action de requête et leur action de réponse en toutes lettres : le
  contrat Resource du service Microsoft, `:24`, `:38` pour
  `Get`/`Put`/`Delete` ; le contrat Enumeration du service Microsoft, `:25`,
  `:35`, `:42`, `:48` pour `Enumerate`/`Pull`/`Renew`/`GetStatus`/`Release`.
  Ces neuf URI sont donc lues telles quelles dans la référence.
- **Action implicite.** Les contrats d'actions personnalisées n'écrivent
  qu'une opération nue (le contrat AccountManagement du service Microsoft,
  `:13`, `:17`, `:21`, `:25`, `:29`). WCF applique alors sa convention par
  défaut `{Namespace}/{ContractName}/{Operation}`, avec `Namespace =
  "…/CustomActions"` et `ContractName = "AccountManagement"` ou
  `"TopologyManagement"`. Les URI `CA/…` de la table 2 sont donc
  **reconstruites par convention**, pas lues sur le fil. Elles sont
  corroborées par les constantes `REPLY_ACTION` du dépôt et par
  `tools/test/test_handlers.py:16-19`, mais n'ont pas été observées dans une
  capture au moment d'écrire ce chapitre.

> **Honnêteté sur les trois dernières lignes de la table 2.** Les URI
> d'action se terminant par `/Search`, `/Schema` et `/Groups` **ne figurent
> dans aucune opération publiée par le service Microsoft**. Le contrat
> `IEnumeration` porte bien `Name = "Search"`, mais ses cinq opérations
> déclarent toutes une `Action` explicite, si bien qu'aucune action ne finit
> par `/Search`. Ces trois clés sont donc des **points d'extension du
> projet**, atteignables uniquement par un client construit exprès.
> `SearchHandler` reste néanmoins utile : il normalise le filtre LDAP via
> `FilterParser` puis délègue à `EnumerateHandler`
> (`classes/handlers/search.py:16-25`).

Même verdict pour `Notify`, avec une nuance : c'est la **seule** extension
qui dispose d'une entrée de correspondance exacte dans `ACTION_HANDLER_KEYS`
(`handler_routing.py:49-50`). Or `IActiveDirectoryAccountManagement` ne
déclare que six opérations, `GetADGroupMember`,
`GetADPrincipalGroupMembership`, `SetPassword`, `ChangePassword`,
`GetADPrincipalAuthorizationGroup`, `TranslateName`, et `Notify` n'en fait
pas partie. `NotifyHandler` renvoie d'ailleurs un corps vide
(`<ca:Events/>`, `notify.py:12-16`) : c'est un bouchon, pas une
implémentation. Aucune opération d'ajout ou de retrait de membre n'y figure
non plus, ce qui confirme que `Groups` est une invention du projet, non une
action que le module PowerShell émettrait.

### Table 3 — actions de réponse

Vingt-huit lignes pour vingt-neuf clés : `Search` n'y figure pas, car
`SearchHandler` délègue à `EnumerateHandler` et renvoie donc un
`EnumerateResponse` (`search.py:25`). L'ancrage est celui de la constante
`REPLY_ACTION` quand elle existe, celui de la ligne littérale sinon.

| Clé | Valeur de `<a:Action>` en réponse | Ancrage |
|---|---|---|
| `Get` | `WST/GetResponse` | `get.py:180`, `get.py:292` |
| `Put` | `WST/PutResponse` | `modify.py:18` |
| `Delete` | `WST/DeleteResponse` | `delete.py:16` |
| `Create` | `WST/CreateResponse` | `create.py:18` |
| `Enumerate` | `WSEN/EnumerateResponse` | `enumerate.py:116` |
| `Pull` | `WSEN/PullResponse` | `pull.py:104` |
| `Release` | `WSEN/ReleaseResponse` | `release.py:49` |
| `Renew` | `WSEN/RenewResponse` | `renew.py:11` |
| `GetStatus` | `WSEN/GetStatusResponse` | `get_status.py:9` |
| `Subscribe` | `WSEV/SubscribeResponse` | `subscribe.py:14` |
| `Unsubscribe` | `WSEV/UnsubscribeResponse` | `unsubscribe.py:10` |
| `SubscriptionRenew` | `WSEV/RenewResponse` | `subscription_renew.py:12` |
| `SubscriptionStatus` | `WSEV/GetStatusResponse` | `subscription_status.py:12` |
| `GetADGroupMember` | `CA/AccountManagement/GetADGroupMemberResponse` | `get_ad_group_member.py:15` |
| `GetADPrincipalGroupMembership` | `CA/AccountManagement/…Response` | `get_ad_principal_group_membership.py:15` |
| `GetADPrincipalAuthorizationGroup` | `CA/AccountManagement/…Response` | `get_ad_principal_authorization_group.py:15` |
| `SetPassword` | `CA/AccountManagement/SetPasswordResponse` | `set_password.py:13` |
| `ChangePassword` | `CA/AccountManagement/ChangePasswordResponse` | `change_password.py:13` |
| `TranslateName` | `CA/AccountManagement/TranslateNameResponse` | `translate_name.py:20` |
| `Notify` | `CA/AccountManagement/NotifyResponse` | `notify.py:8` |
| `GetADDomain` | `CA/TopologyManagement/GetADDomainResponse` | `get_ad_domain.py:12` |
| `GetADDomainController` | `CA/TopologyManagement/…Response` | `get_ad_domain_controller.py:18` |
| `GetADForest` | `CA/TopologyManagement/GetADForestResponse` | `get_ad_forest.py:29` |
| `GetVersion` | `CA/TopologyManagement/GetVersionResponse` | `get_version.py:8` |
| `MoveADOperationMasterRole` | `CA/TopologyManagement/…Response` | `move_operation_master_role.py:14` |
| `ChangeOptionalFeature` | `CA/TopologyManagement/…Response` | `change_optional_feature.py:15` |
| `Schema` | `…/2008/1/ActiveDirectory/SchemaResponse` | `schema.py:75` |
| `Groups` | `CA/AccountManagement/{Added,Removed}MemberResponse` | `groups.py:37` |

`GroupHandler` est le seul dont l'action de réponse est **calculée à
l'exécution** : il inspecte l'action entrante et choisit `AddedMember` ou
`RemovedMember` selon qu'elle contient `add` ou `remove`
(`classes/handlers/groups.py:20-25`), puis compose
`{CUSTOM_ACTIONS}/AccountManagement/{label}Response`.

### Les sous-routeurs

Trois handlers ne traitent pas directement l'action : ils la réaiguillent.

| Handler d'entrée | Condition | Délégué |
|---|---|---|
| `TransferHandler` | action finit par `/put` | `ModifyHandler` (`modify.py`) |
| `TransferHandler` | action finit par `/delete` | `DeleteHandler` (`delete.py`) |
| `CRUDHandler` | action finit par `/create` | `CreateHandler` (`create.py`) |
| `CRUDHandler` | action finit par `/put` | `ModifyHandler` |
| `CRUDHandler` | action finit par `/delete` | `DeleteHandler` |
| `SearchHandler` | toujours | `EnumerateHandler` après normalisation |
| `GroupHandler` | ni `add` ni `remove` | `GetADGroupMemberHandler` |

Les tests d'action y sont faits en minuscules sur le suffixe
(`transfer.py:17-21`, `crud.py:19-25`). Si aucun cas ne matche, les deux
premiers renvoient une faute `directory_error` de sous-libellé
`ActionNotSupported` (`transfer.py:22-26`, `crud.py:26-30`), et non une
exception, donc sans passer par le chemin d'erreur du dispatcher.

## Contrôles LDAP transportés en en-tête

### Forme sur le fil

[MS-WSPELD] définit le transport des contrôles LDAP v3 dans les messages
ADWS. La structure est un conteneur `<ad:controls>` contenant des
`<ad:control>`, chacun portant :

| Élément / attribut | Espace de noms | Type | Sens |
|---|---|---|---|
| `type` (attribut) | aucun | chaîne | OID du contrôle |
| `criticality` (attribut) | aucun | booléen | Contrôle critique ou non |
| `controlValue` (élément) | `AD` | `xsd:base64Binary` | Valeur BER du contrôle |
| `xsi:type` (attribut) | `XSI` | QName | Type déclaré de la valeur |

Deux points de forme méritent d'être soulignés.

D'abord, `controlValue` n'est pas une chaîne libre : son contenu textuel est
le **base64 d'un blob BER**, c'est-à-dire la valeur du contrôle telle que
LDAP la définit, encodée en ASN.1/BER puis en base64. Un `xsi:type`
facultatif accompagne la valeur. C'est cette double couche d'encodage qui
commande tout ce qui suit sur les limites de la traduction.

Ensuite, et malgré son nom courant, `controls` n'est **pas** un en-tête SOAP
autonome au sens strict : c'est un membre porté par les messages de corps
des opérations concernées (création, recherche par objet de base,
modification). Il n'existe par ailleurs **aucun** élément nommé
`ldapControls`, cette dénomination, parfois rencontrée, ne correspond à rien
dans le protocole ni dans ce dépôt.

### Ce que ce serveur parse

`ControlsParser` (`classes/parsing/controls_parser.py:31`) travaille sur le
document entier :

```python
for elem in root.findall(".//ad:controls/ad:control", NS):
```

Le XPath `.//ad:controls/ad:control` (`controls_parser.py:36`) attrape donc
les contrôles où qu'ils se trouvent, en-tête comme corps, ce qui rend le
parseur indifférent au fait qu'ils voyagent dans le corps. `_read_one`
(`controls_parser.py:51-59`) accepte l'attribut `type` **ou** `OID` comme
porteur de l'OID, lit `criticality` (défaut `false`) et le texte de
`<ad:controlValue>`.

`RequestContext._parse_controls` (`context.py:171-178`) appelle
`ControlsParser.to_ldb` dans un `try/except Exception` qui renvoie `None` en
cas d'échec : **un contrôle mal formé n'échoue jamais la requête**, il est
simplement ignoré. C'est une décision de robustesse, à connaître quand on
débogue un contrôle qui « ne fait rien ».

### Table exhaustive des OID reconnus

Les dix-neuf entrées de `LDB_CONTROL_BY_OID`
(`classes/parsing/controls_parser.py:8-28`), dans l'ordre du fichier. La
colonne « Nom LDB émis » est la chaîne effectivement passée à Samba ; la
colonne « Nom [MS-ADTS] » est le nom canonique de l'OID.

| OID | Nom LDB émis | Nom [MS-ADTS] | Verdict |
|---|---|---|---|
| `1.2.840.113556.1.4.319` | `paged_results` | LDAP_SERVER_PAGED_RESULTS | conforme |
| `1.2.840.113556.1.4.473` | `server_sort` | LDAP_SERVER_SORT | conforme |
| `1.2.840.113556.1.4.474` | `sort_resp` | LDAP_SERVER_RESP_SORT | contrôle de réponse |
| `1.2.840.113556.1.4.529` | `extended_dn` | LDAP_SERVER_EXTENDED_DN | conforme |
| `1.2.840.113556.1.4.801` | `sd_flags` | LDAP_SERVER_SD_FLAGS | conforme |
| `1.2.840.113556.1.4.805` | `tree_delete` | LDAP_SERVER_TREE_DELETE | conforme |
| `1.2.840.113556.1.4.521` | `crossdom_move_target` | LDAP_SERVER_CROSSDOM_MOVE_TARGET | conforme |
| `1.2.840.113556.1.4.417` | `show_deleted` | LDAP_SERVER_SHOW_DELETED | conforme |
| `1.2.840.113556.1.4.1340` | `show_recycled` | LDAP_SERVER_SEARCH_OPTIONS | **erroné** |
| `1.2.840.113556.1.4.2026` | `show_deactivated_link` | LDAP_SERVER_DN_INPUT | **erroné** |
| `1.2.840.113556.1.4.1413` | `permissive_modify` | LDAP_SERVER_PERMISSIVE_MODIFY | conforme |
| `1.2.840.113556.1.4.1339` | `domain_scope` | LDAP_SERVER_DOMAIN_SCOPE | conforme |
| `1.2.840.113556.1.4.2065` | `managedBy` | LDAP_SERVER_SHOW_DEACTIVATED_LINK | **erroné** |
| `1.2.840.113556.1.4.1504` | `asq` | LDAP_SERVER_ASQ | conforme |
| `1.2.840.113556.1.4.1948` | `search_notification` | LDAP_SERVER_RANGE_RETRIEVAL_NOERR | **erroné** |
| `1.2.840.113556.1.4.2064` | `show_recycled` | LDAP_SERVER_SHOW_RECYCLED | conforme |
| `2.16.840.1.113730.3.4.2` | `manageDSAIT` | ManageDsaIT (RFC 3296) | conforme |
| `1.2.840.113556.1.4.1338` | `verify_name` | LDAP_SERVER_VERIFY_NAME | conforme |
| `1.2.840.113556.1.4.841` | `dirsync` | LDAP_SERVER_DIRSYNC | conforme |

> **Quatre mappings à corriger.** Ils ne sont pas anodins : le nom LDB est
> passé littéralement à `SamDB.search(controls=…)`, et un nom que le parseur
> de contrôles de Samba ne connaît pas fait **échouer la recherche
> entière**, pas seulement le contrôle. `managedBy` et `search_notification`
> ne sont pas des noms de contrôle `ldb`, le premier est un nom d'attribut
> d'annuaire, le second n'existe pas.

Correctif proposé, OID par OID :

| OID | Nom LDB actuel | Nom LDB attendu |
|---|---|---|
| `…1.4.1340` | `show_recycled` | `search_options` |
| `…1.4.2026` | `show_deactivated_link` | pas d'équivalent `ldb` direct |
| `…1.4.2065` | `managedBy` | `show_deactivated_link` |
| `…1.4.1948` | `search_notification` | pas d'équivalent `ldb` direct |

À noter que `show_recycled` est bien un nom `ldb` valide, mais associé au
seul OID `…1.4.2064`, déjà présent dans la table : `…1.4.1340` en est un
doublon qui, en prime, détourne l'OID de `search_options`.

Autres observations à porter au dossier :

- **`sort_resp` est un contrôle de *réponse*.** Un client ne l'émet pas ; le
  trouver dans une table de traduction requête vers LDB est au mieux
  inutile.
- Un OID **absent de la table** est silencieusement supprimé : `_translate`
  (`controls_parser.py:62-74`) retourne `None` et `to_ldb` ne l'ajoute pas.
  Aucune faute n'est levée, même pour un contrôle déclaré
  `criticality="true"`, alors que la sémantique LDAP v3 exige qu'un contrôle
  critique non supporté fasse **échouer** l'opération. **C'est un écart au
  niveau 1, documenté ici.**
- `_read_one` accepte l'attribut `type` **ou** l'attribut `OID`
  (`controls_parser.py:53`). Seul `type` a un correspondant sur le fil ;
  `OID` est une tolérance défensive sans émetteur connu.
- `criticality` est lu avec `(elem.get("criticality") or "false").lower ==
  "true"` (`controls_parser.py:56`). Un client qui écrirait `1` au lieu de
  `true`, forme légale pour `xsd:boolean`, verrait donc son contrôle dégradé
  en non critique. Le sérialiseur .NET écrit `true`/`false`, donc le cas ne
  se présente pas au niveau 2, mais la lecture est plus étroite que le
  schéma.

### Traduction vers la syntaxe LDB

`_translate` (`controls_parser.py:62-74`) produit une chaîne au format Samba
`nom:criticité[:valeur]` :

```python
name = LDB_CONTROL_BY_OID.get(ctrl["oid"])
if not name:
    return None
criticality = "1" if ctrl["critical"] else "0"
if not ctrl["value"]:
    return f"{name}:{criticality}"
try:
    decoded = b64decode(ctrl["value"]).decode("utf-8", errors="ignore")
    decoded = decoded.replace(":", "").strip()
except Exception:
    decoded = ""
return f"{name}:{criticality}:{decoded}" if decoded else f"{name}:{criticality}"
```

Le `try/except Exception` de `controls_parser.py:69-73` est la seconde ligne
de défense après celui de `RequestContext._parse_controls` : une valeur qui
n'est pas du base64 valide donne `decoded = ""`, donc un contrôle réduit à
`nom:criticité`, jamais une exception.

> **Limite structurelle.** La valeur d'un contrôle LDAP est un **blob BER**,
> pas du texte. La décoder en UTF-8 avec `errors="ignore"` puis retirer les
> `:` produit, pour `paged_results` (dont la valeur est un `SEQUENCE { size
> INTEGER, cookie OCTET STRING }`), une chaîne sans signification. Autrement
> dit : **la taille de page demandée par le client ne survit pas à la
> traduction**. C'est cohérent avec la limite déjà notée dans
> `documentation/01-architecture.md`, « les contrôles `PagedResults` côté
> client sont acceptés mais le serveur fait un seul `search` complet et
> pagine côté handler ». Le contrôle n'est donc pas *honoré*, il est
> *toléré*.

### Où les contrôles sont réellement appliqués

Recensement exhaustif des points où un contrôle atteint LDB :

| Handler | Contrôles passés à LDB | Origine |
|---|---|---|
| `EnumerateHandler` | `context.ldap_controls or None` | parsés (`enumerate.py:53`) |
| `GetHandler` (RootDSE) | `["sd_flags:1:0"]` en dur | `get.py:120` |
| `GetHandler` (objet) | `["sd_flags:1:0"]` en dur | `get.py:220` |
| `DeleteHandler` | `["tree_delete:1"]` si détecté | `delete.py:40-44` |
| `CreateHandler` | aucun (`db.add(msg)`) | `create.py:35` |
| `ModifyHandler` | aucun (`db.modify(msg)`) | `modify.py:70` |
| tous les autres | aucun | — |

La chaîne `sd_flags:1:0` mérite d'être décodée, car sa lecture naïve induit
en erreur. Le format `ldb` est `nom:criticité:valeur` : il s'agit donc du
contrôle `sd_flags` (`…1.4.801`), déclaré **critique** (`1`), avec un masque
`SECURITY_INFORMATION` de valeur **`0`**. Ce masque valant 1 pour OWNER, 2
pour GROUP, 4 pour DACL et 8 pour SACL, `0` ne demande **aucune** partie du
descripteur de sécurité, précisément l'intention : ne pas en payer le coût
de lecture, et ne pas déclencher le contrôle d'accès sur la SACL, qui exige
`SeSecurityPrivilege`. Deux conséquences directes :

- **`context.ldap_controls` n'est consommé que par `EnumerateHandler`**
  (donc aussi par `SearchHandler`, qui délègue). Un `show_deleted` envoyé
  sur un `Get` unitaire est parsé, rangé dans le contexte… et jamais
  utilisé, le `Get` écrase la liste par son `sd_flags:1:0` codé en dur.
- **`DeleteHandler` ne passe pas par `ControlsParser`.** Il cherche la
  chaîne littérale `1.2.840.113556.1.4.805` dans le XML brut
  (`delete.py:42`) et, si elle y figure, envoie `tree_delete:1`. C'est
  volontairement grossier, la constante `_TREE_DELETE_OID` (`delete.py:10`)
  est commentée comme provenant de `Remove-AD* -Recursive`, mais cela
  signifie qu'un OID mentionné n'importe où dans le message déclenche la
  suppression récursive. À durcir.

## Les fautes SOAP

### Structure XML exactement produite

Tout passe par `SoapEnvelope.fault` (`classes/soap/soap_envelope.py:46-59`)
et `_code` (`classes/soap/soap_envelope.py:61-66`). Le corps produit est :

```xml
<s:Body>
  <s:Fault>
    <s:Code>
      <s:Value>s:Receiver</s:Value>
      <s:Subcode><s:Value>ca:SetPasswordFault</s:Value></s:Subcode>
    </s:Code>
    <s:Reason>
      <s:Text xml:lang="en-US">message d'erreur</s:Text>
    </s:Reason>
    <s:Detail>…</s:Detail>
  </s:Fault>
</s:Body>
```

Faits précis, tous vérifiables ligne à ligne :

- `<s:Subcode>` est **imbriqué dans `<s:Code>`**, après `<s:Value>`
  (`soap_envelope.py:63-66`), conformément à SOAP 1.2. Il n'est émis que si
  l'appelant fournit un `subcode` non vide.
- `<s:Reason><s:Text>` porte toujours `xml:lang="en-US"`, en dur
  (`soap_envelope.py:54`). Le message n'est jamais localisé.
- `<s:Detail>` n'est émis que si `detail_xml` est non vide
  (`soap_envelope.py:56-57`).
- Le message et le code sont échappés par `html.escape`
  (`soap_envelope.py:54`, `:63`, `:65`).
- L'enveloppe et donc `<a:Action>` et `<a:RelatesTo>` viennent de `wrap` :
  **aucune faute ne peut être produite sans `RelatesTo`**.

Deux valeurs seulement sont employées pour `<s:Code><s:Value>` : `s:Sender`
(constante `FaultBuilder.SENDER`, `classes/faults/faults.py:10`) et
`s:Receiver` (`FaultBuilder.RECEIVER`, `faults.py:11`). Ce sont les codes
SOAP 1.2 standards : faute imputable à l'émetteur, ou au récepteur.

> **Le sous-code est limité aux préfixes de `NS_DECL`.** Un sous-code SOAP
> 1.2 est un QName : son préfixe doit être déclaré sur l'enveloppe. `ca:`
> l'est (`soap_envelope.py:28`), donc `ca:SetPasswordFault` est valide. Mais
> un futur `wsman:AccessDenied` produirait un préfixe **non lié**, `wsman`
> n'est pas dans `NS_DECL`, donc un XML rejeté par le lecteur .NET. Câbler
> `TypedFaults` demande donc de toucher aussi à `NS_DECL`, pas seulement
> d'appeler la bonne fabrique.

### Générateurs disponibles

`FaultBuilder` (`classes/faults/faults.py:8`), quatre fabriques :

| Méthode | Code | Sous-code | Détail |
|---|---|---|---|
| `directory_error` | `s:Receiver` | aucun | `<da:Fault>` ShortError + LongError |
| `access_denied` | `s:Sender` | aucun | aucun |
| `custom_action_fault` | `s:Receiver` | `ca:{nom}` | `<{nom}>` du namespace CA |
| `invalid_enumeration_context` | `s:Sender` | aucun | aucun |

`custom_action_fault` (`faults.py:28-41`) est la seule qui change aussi
l'action : elle passe `action=FAULT_NS`, soit
`http://schemas.microsoft.com/2008/1/ActiveDirectory/Data/fault`. C'est
**exactement** l'`Action` déclarée par toutes les fautes de custom actions.
Les douze noms de faute concernés se répartissent en six pour
AccountManagement et cinq pour TopologyManagement, plus `GetVersionFault`.

Le sous-code `ca:{nom}` produit par `faults.py:40` est lui aussi correct :
toutes ces fautes portent `Namespace =
"…/2008/1/ActiveDirectory/CustomActions"`, et WCF compose le sous-code SOAP
1.2 à partir du couple (Namespace, Name).

> **Écart de code SOAP, non signalé jusqu'ici.** La référence construit ces
> fautes par `GenerateCustomActionFaultMessage(…, receiverFault: false, …)`
> , et `receiverFault: false` se traduit par
> `FaultCode.CreateSenderFaultCode`, donc `<s:Value>s:Sender</s:Value>`. Ce
> projet émet `cls.RECEIVER`, soit `s:Receiver` (`faults.py:39`). Le
> sous-code est le bon, le code principal ne l'est pas. Un client qui trie
> ses erreurs entre « ma faute » et « faute du serveur » classera donc à
> tort toute erreur d'action personnalisée du côté serveur.

Son détail reproduit la forme `CustomActionFault` de la référence :

```xml
<SetPasswordFault
    xmlns="http://schemas.microsoft.com/2008/1/ActiveDirectory/CustomActions"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <ArgumentError xsi:nil="true"></ArgumentError>
  <DirectoryError xsi:nil="true"></DirectoryError>
  <Error>message</Error>
  <ShortError>message</ShortError>
</SetPasswordFault>
```

Les quatre membres correspondent aux propriétés `ArgumentError` , `Error`
(`:42-53`), `DirectoryError` (`:55-66`) et `ShortError` (`:68-79`) de la
classe abstraite `CustomActionFault`. L'ordre d'émission de
`faults.py:32-35` (`ArgumentError`, `DirectoryError`, `Error`, `ShortError`)
est l'ordre alphabétique du sérialiseur par contrat de données : c'est le
bon, bien qu'il ne soit pas l'ordre de déclaration en C#.

**Écarts sur le contenu**, tous vérifiés :

| Membre | Ce projet | La référence |
|---|---|---|
| `ArgumentError` | toujours `xsi:nil` | rempli si `ArgumentException` |
| `DirectoryError` | toujours `xsi:nil` | rempli si erreur d'annuaire |
| `ShortError` | copie de `Error` | via `LongToShortMap`, sinon `null` |
| `<s:Reason>` | le message d'erreur | chaîne fixe `ArgumentError` |

`TypedFaults` (`classes/faults/typed_faults.py:14`), cinq fabriques, une par
famille de spécification :

| Méthode | Code SOAP | Élément de détail | Espace de noms du détail |
|---|---|---|---|
| `wsman` | `s:Sender` | `<wsman:FaultDetail>` | `…/wsman/1/wsman.xsd` |
| `wsaddressing` | `s:Sender` | `<wsa:FaultDetail>` | `…/ws/2004/08/addressing` |
| `directory` | `s:Receiver` | `<da:Fault>` | `…/IdentityManagement/DirectoryAccess` |
| `transfer` | `s:Sender` | `<wst:Fault>` | `…/ws/2004/09/transfer` |
| `enumeration` | `s:Sender` | `<wsen:Fault>` | `…/ws/2004/09/enumeration` |

Chacune produit un détail à deux enfants, `Code` (le nom court) et `Message`
(le texte). C'est un format **maison** : la référence utilise des schémas de
détail plus riches (`FaultDetail`, `SupportedDialect`,
`AttributeTypeNotValid`, …). Le rapprochement se fait sur le **nom** placé
dans `<*:Code>`.

### Table exhaustive des codes typés

Constantes de `src/faults/fault_codes.py` (lignes 6 à 24), regroupées par
famille. Ce sont les valeurs destinées au paramètre `name` de `TypedFaults`.

| Constante Python | Valeur | Famille |
|---|---|---|
| `WSMAN_CANNOT_PROCESS_FILTER` | `CannotProcessFilter` | WS-Management |
| `WSMAN_ENCODING_LIMIT` | `EncodingLimit` | WS-Management |
| `WSMAN_FRAGMENT_DIALECT` | `FragmentDialectNotSupported` | WS-Management |
| `WSMAN_SCHEMA_VALIDATION` | `SchemaValidationError` | WS-Management |
| `WSMAN_ACCESS_DENIED` | `AccessDenied` | WS-Management |
| `WSADDR_DESTINATION_UNREACHABLE` | `DestinationUnreachable` | WS-Addressing |
| `WSADDR_ENDPOINT_UNAVAILABLE` | `EndpointUnavailable` | WS-Addressing |
| `WSADDR_ACTION_NOT_SUPPORTED` | `ActionNotSupportedFault` | WS-Addressing |
| `DA_UNWILLING_TO_PERFORM` | `UnwillingToPerform` | DirectoryAccess |
| `WST_INVALID_REPRESENTATION` | `InvalidRepresentation` | WS-Transfer |
| `WSEN_INVALID_CONTEXT` | `InvalidEnumerationContext` | WS-Enumeration |
| `WSEN_TIMED_OUT` | `TimedOut` | WS-Enumeration |
| `WSEN_UNABLE_TO_RENEW` | `UnableToRenew` | WS-Enumeration |
| `WSEN_INVALID_EXPIRATION_TIME` | `InvalidExpirationTime` | WS-Enumeration |
| `WSEN_FILTER_DIALECT_UNAVAILABLE` | `FilterDialectRequestedUnavailable` | WS-Enumeration |
| `WSEN_ENUMERATION_LIMIT` | `EnumerationContextLimitExceeded` | WS-Enumeration |

Ces seize noms sont **exactement** ceux déclarés par les fautes de la
référence, ce qui est le point le plus important : un client qui inspecte le
sous-code y retrouvera un libellé qu'il connaît. La vérification est directe
: chaque nom correspond à une faute déclarée par le contrat Resource du
service Microsoft ou le contrat Enumeration du service Microsoft :

| Nom de faute | Espace de noms du sous-code | Action de faute | Ancrage |
|---|---|---|---|
| `DestinationUnreachable` | WS-A 2004/08 | WS-A 2004/08 | Service ADWS Microsoft |
| `EncodingLimit` | wsman.xsd | wsman | Service ADWS Microsoft |
| `FragmentDialectNotSupported` | wsman.xsd | wsman | Service ADWS Microsoft |
| `CannotProcessFilter` | wsman.xsd | wsman | Service ADWS Microsoft |
| `SchemaValidationError` | wsman.xsd | wsman | Service ADWS Microsoft |
| `AccessDenied` | wsman.xsd | wsman | Service ADWS Microsoft |
| `UnwillingToPerform` | DirectoryAccess | DirectoryAccess | Service ADWS Microsoft |
| `EndpointUnavailable` | WS-A 2004/08 | WS-A 2004/08 | Service ADWS Microsoft |
| `InvalidRepresentation` | WS-Transfer | WS-Transfer | Service ADWS Microsoft |
| `ActionNotSupportedFault` | WS-A 2004/08 | WS-A 2004/08 | Service ADWS Microsoft |
| `FilterDialectRequestedUnavailable` | WS-Enumeration | WS-Enum | Service ADWS Microsoft |
| `InvalidExpirationTime` | WS-Enumeration | WS-Enum | Service ADWS Microsoft |
| `EnumerationContextLimitExceeded` | **AD** | AD Data/fault | Service ADWS Microsoft |
| `InvalidEnumerationContext` | WS-Enumeration | WS-Enum | Service ADWS Microsoft |
| `TimedOut` | WS-Enumeration | WS-Enum | Service ADWS Microsoft |
| `UnableToRenew` | WS-Enumeration | WS-Enum | Service ADWS Microsoft |

Deux nuances que le regroupement par préfixe de `fault_codes.py` masque :

- **`WSEN_ENUMERATION_LIMIT` est mal classé.**
  `EnumerationContextLimitExceeded` est déclaré avec `Namespace =
  "http://schemas.microsoft.com/2008/1/ActiveDirectory"` et généré avec ce
  même espace de noms , **pas** dans l'espace WS-Enumeration. L'émettre par
  `TypedFaults.enumeration` produirait donc un sous-code dans le mauvais
  espace de noms.
- **`CannotProcessFilter` existe en double.** Sous WS-Management pour
  `Get`/`Put` (le contrat Resource du service Microsoft, généré en le
  générateur de fautes du service ADWS Microsoft et `:177`) et sous
  WS-Enumeration pour `Enumerate` (le contrat Enumeration du service
  Microsoft, généré en le générateur de fautes du service ADWS Microsoft et
  `:359`). Le préfixe `WSMAN_` de `fault_codes.py:6` ne couvre donc que la
  moitié des cas.

Six noms de faute de la référence n'ont en revanche **aucune** constante
dans `fault_codes.py` : `AlreadyExists` (wsman, le générateur de fautes du
service ADWS Microsoft), `InvalidSortKey` (`:380`), `InvalidPropertyFault`
(`:402`), `MaxCharsNotSupported` (`:417`), `MaxTimeExceedsLimit` (`:422`) et
`UnsupportedSelectOrSortDialectFault`, les cinq derniers dans l'espace de
noms `AD`.

> **Écart majeur, à corriger en priorité.** Ni `TypedFaults` ni les
> constantes de `fault_codes.py` **ne sont utilisées par un seul handler** à
> ce jour. `BaseHandler.__init__` expose `self.typed_faults`
> (`classes/handlers/base.py:28`), mais aucune sous-classe ne l'appelle. En
> pratique, **toutes** les fautes émises sont soit `directory_error`, soit
> `custom_action_fault`, soit `invalid_enumeration_context`, soit la faute
> générique du dispatcher. L'infrastructure typée existe et est correcte ;
> son câblage reste à faire.

### Correspondance code LDB / Samba → faute

Il faut être direct : **cette implémentation ne fait aucune traduction
structurée des codes d'erreur LDB en fautes typées.** Le mécanisme réel est
le suivant.

| Chemin | Traitement de l'erreur | Faute produite |
|---|---|---|
| `CreateHandler.handle` | `except Exception` | `directory_error(…, "CreateFailed")` |
| `ModifyHandler.handle` | `except Exception` | `directory_error(…, "ModifyFailed")` |
| `DeleteHandler.handle` | `except Exception` | `directory_error(…, "DeleteFailed")` |
| `SchemaHandler.handle` | `except Exception` | `directory_error(…, "SchemaError")` |
| `SearchHandler` (filtre) | `except ValueError` | `directory_error(…, "CannotProcessFilter")` |
| `TransferHandler` / `CRUDHandler` | action inconnue | `directory_error(…, "ActionNotSupported")` |
| `ModifyHandler` / `DeleteHandler` | DN absent | `directory_error(…, "InvalidRequest")` |
| `SubscribeHandler` | `except Exception` | `directory_error(…, "SubscribeFault")` |
| handlers d'actions CA | `except Exception` | `custom_action_fault(…, "{Op}Fault")` |
| `GroupHandler._modify_member` | `except Exception` | `custom_action_fault(…, "{label}Fault")` |
| `GetStatusHandler` / `RenewHandler` | contexte absent/expiré | `invalid_enumeration_context` |
| `EnumerateHandler` / `PullHandler` / `ReleaseHandler` | `ADWSException` remontée | faute générique du dispatcher |
| `GetHandler` | `except Exception` | `build_soap_fault` générique |

Dans tous les cas, le texte de l'exception Samba (typiquement `(68,
'Entry... already exists')` ou `(50, 'Insufficient access rights')`) est
**recopié tel quel** dans `<s:Reason><s:Text>` et dans `<da:LongError>`.
L'information est donc présente et exploitable par un humain, mais elle
n'est pas normalisée : le client ne peut pas la discriminer par sous-code.

Les six libellés listés par `documentation/03-protocole.md:241-249` sous le
titre « Codes de fault typés (`src/faults/fault_codes.py`) »,
`DirectoryError`, `InsufficientAccessRights`, `ConstraintViolation`,
`ObjectClassViolation`, `EntryAlreadyExists`, `NoSuchObject`, **ne
correspondent à aucune constante de ce fichier**, qui n'en contient aucun
des six. Ce sont en réalité des valeurs de l'énumération `ResultCode` de
`System.DirectoryServices.Protocols`, que le vrai ADWS teste pour choisir sa
faute. La documentation projet est donc à corriger sur ce point.

Le mapping réel de la référence se lit dans deux endroits complémentaires :
la chaîne de `catch` de chaque opération (pour le bloc `Create`, le service
ADWS Microsoft) et les fabriques de le générateur de fautes du service ADWS
Microsoft, qui portent le nom, l'espace de noms, l'action et le caractère
émetteur/récepteur de la faute. Le tableau ci-dessous croise les deux ;
toutes les cellules sont vérifiées dans le code de référence.

| `ResultCode` LDAP | Faute du vrai ADWS | Code SOAP | Ancrage |
|---|---|---|---|
| `NoSuchObject` | `DestinationUnreachable` | `s:Receiver` | Service ADWS Microsoft |
| `ObjectClassViolation` | `InvalidRepresentation` | `s:Sender` | Service ADWS Microsoft |
| `EntryAlreadyExists` | `AlreadyExists` | `s:Sender` | Service ADWS Microsoft |
| `InsufficientAccessRights` | `AccessDenied` | `s:Sender` | Service ADWS Microsoft |
| `ConstraintViolation` | `InvalidRepresentation` | `s:Sender` | Service ADWS Microsoft |
| autre / non classé | `UnwillingToPerform` | `s:Sender` | Service ADWS Microsoft |

Les exceptions non LDAP ont elles aussi leur mapping, vérifiable dans la
même chaîne de `catch` :

| Exception .NET | Faute du vrai ADWS | Code SOAP | Ancrage |
|---|---|---|---|
| `LdapException` | `UnwillingToPerform` | `s:Sender` | Service ADWS Microsoft |
| `ArgumentException` | `UnwillingToPerform` | `s:Sender` | Service ADWS Microsoft |
| `NoConnectionAvailableException` | `EndpointUnavailable` | `s:Receiver` | Service ADWS Microsoft |
| `InvalidExpressionException` | `CannotProcessFilter` | `s:Sender` | Service ADWS Microsoft |
| `EncodingLimitExceeded…` | `EncodingLimit` | `s:Sender` | Service ADWS Microsoft |
| action inconnue | `ActionNotSupportedFault` | `s:Sender` | Service ADWS Microsoft |

Le mécanisme central est `CreateMessageFault` : un booléen `receiverFault`
choisit entre `FaultCode.CreateReceiverFaultCode(faultName, faultNamespace)`
et `FaultCode.CreateSenderFaultCode(…)`. Il faut en retenir que **la
référence émet `s:Sender` dans l'écrasante majorité des cas**, seules
`DestinationUnreachable` et `EndpointUnavailable` (variantes LDAP et
connexion) sont `s:Receiver`. Ce projet, lui, émet `s:Receiver` pour toutes
ses `directory_error` et ses `custom_action_fault`, et `s:Sender` uniquement
pour `access_denied` et `invalid_enumeration_context`. C'est l'inverse de la
référence pour la quasi-totalité des cas d'erreur réels.

Câbler ces deux tableaux dans `classes/faults/` (en interceptant le tuple
`(code, message)` que Samba met dans ses `ldb.LdbError` plutôt que `str(e)`)
est le chantier naturel pour aligner le niveau 3 sur le niveau 2. Le code
numérique LDAP est déjà à portée de main : la forme `(68, 'Entry... already
exists')` que l'on retrouve aujourd'hui dans le `<s:Reason>` est la
représentation textuelle d'un `ldb.LdbError` dont le premier argument est
précisément l'entier `ResultCode`. L'implémentation actuelle ne consomme que
`str(e)` et jette donc l'information la plus exploitable du lot.

### Hiérarchie d'exceptions

`classes/faults/exceptions.py` définit une base et six sous-classes :

| Classe | Sens documenté |
|---|---|
| `ADWSException` | Base ; porte `message` et `code` (défaut 0) |
| `ADWSProtocolException` | Erreurs de niveau protocole |
| `ADWSDataException` | Erreurs de manipulation de données |
| `ADWSAuthenticationException` | Échecs d'authentification |
| `ADWSTransformException` | Erreurs de transformation XML/WCF |
| `ADWSObjectNotFoundException` | Objet absent de l'annuaire |
| `ADWSAccessDeniedException` | Accès refusé |

Seule `ADWSException` est effectivement levée dans l'arbre courant, en huit
points exactement : `dispatcher.py:41`, `enumerate.py:59` et `:90`,
`pull.py:23`, `:29` et `:47`, `release.py:23` et `:40`. Les six sous-classes
sont déclarées mais inutilisées, pendant exact de l'observation faite sur
`TypedFaults`. L'attribut `code` n'est jamais renseigné autrement qu'à sa
valeur par défaut, et n'est jamais lu.

### Inventaire du code mort de la couche message

Regrouper ces constats évite de les redécouvrir un par un. Chacune des
lignes suivantes désigne un symbole défini, correct, et jamais atteint :

| Symbole | Fichier | Ce qui manque |
|---|---|---|
| `ENV_NS_MAP` | `src/soap/namespaces.py:18-30` | aucun import |
| `WSMAN_FAULT` | `src/soap/namespaces.py:14` | aucun import |
| les 16 noms de faute | `src/faults/fault_codes.py:6-24` | aucun import |
| `TypedFaults` (5 fabriques) | `classes/faults/typed_faults.py` | jamais appelée |
| `FaultBuilder.access_denied` | `classes/faults/faults.py:24-26` | jamais appelée |
| 6 sous-classes d'`ADWSException` | `classes/faults/exceptions.py:13-35` | jamais levées |
| `InstanceIndex` | `classes/directory/instance_index.py` | aucun handler consommateur |
| `ADWSException.code` | `classes/faults/exceptions.py:10` | jamais renseigné |

`typed_faults.py` importe bien les cinq constantes d'espace de noms de
`fault_codes.py` (`typed_faults.py:4-10`) ; ce sont les **seize noms de
faute** qui n'ont aucun consommateur. Dit autrement, l'infrastructure de
fautes typées est complète à un fil près : il manque le point d'appel.

## Construction des réponses dans l'implémentation

### Séquence exacte du dispatcher

`ADWSDispatcher.dispatch` (`classes/handlers/dispatcher.py:20-35`) est le
point unique par lequel passe tout message applicatif. Sa séquence :

```text
  record (SizedEnvelopedMessageRecord, déjà descellé GSSAPI)
        │
        ▼
  [1] record.payload_to_xml()               src/nettcp/nmf.py:363
        │     lit la table de dictionnaire dynamique (0 octet),
        │     décode les records WCF, rend une chaîne XML
        ▼
  [2] RequestContext.from_xml(xml)          classes/parsing/context.py:37
        │     action, message_id, object_reference, is_imda,
        │     requested_attributes, base_dn/filter/scope,
        │     enumeration_context/max_elements, ldap_controls, raw_xml
        ▼
  [3] HandlerRegistry.resolve(action)       handler_registry.py:15
        │     exact (minuscules) → sinon dernier segment d'URL
        ▼
  [4] handler.handle(context) -> str        classes/handlers/*.py
        │     XML SOAP complet (enveloppe + header + body)
        ▼
  [5] XMLParser.parse(response_xml)         src/wcf/xml2records.py:313
        │     XML texte → liste de records WCF
        ▼
  [6] dump_records(records)                 src/wcf/records/__init__.py:90
        │     records → octets
        ▼
  [7] b"\x00" + encoded                     dispatcher.py:49
        │     préfixe = table de dictionnaire dynamique vide
        ▼
  bytes rendus à ProtocolHandler.handle_messages (protocol.py:147)
```

L'appelant est `ProtocolHandler.handle_messages`
(`classes/server/protocol.py:107`), boucle de lecture de records NMF qui
aiguille sur le champ `code` : `0x0c` (`PreambleEndRecord`) déclenche un
`PreambleAckRecord` (`protocol.py:133-137`), `0x07` (`EndRecord`) ferme la
conversation (`:170-173`), et `0x06` (`SizedEnvelopedMessageRecord`,
`src/nettcp/nmf.py:348-349`) est le seul code qui atteigne le dispatcher
(`:140`, appel en `:147`). La réponse est réemballée dans un
`SizedEnvelopedMessageRecord` (`:153-156`) puis écrite sur le
`GENSECStream`, donc scellée GSSAPI à l'écriture. Détail d'exploitation :
`protocol.py:164` abaisse ensuite le délai d'attente de la socket à deux
secondes, si bien qu'une pause plus longue côté client se traduit par une
fermeture de connexion, pas par une faute SOAP.

### Le chemin d'erreur

Deux `except` seulement, et ils convergent :

```python
except ADWSException as e:
    return self._encode_response(self._fault(context, e.message))
except Exception as e:
    self.logger.exception("[DISPATCH] unexpected failure")
    return self._encode_response(self._fault(context, str(e)))
```

Points structurants :

- **La faute repasse par `_encode_response`.** Elle est donc encodée en WCF
  binaire et préfixée du `\x00` exactement comme une réponse normale. Une
  faute émise en XML brut serait indécodable par le client.
- **Seul le second `except` journalise une stack trace.** Une
  `ADWSException` est considérée comme une erreur métier attendue : elle
  produit une faute sans bruit dans les logs. C'est la raison pratique de
  l'invariant projet « toujours lever une `ADWSException` typée » : une
  exception nue pollue les journaux d'une trace complète à chaque erreur
  utilisateur banale.
- **`context` peut être `None`** ; voir la discussion de `_fault` plus haut.
- **Le dispatcher ne rattrape rien au-delà de lui-même.** Si `XMLParser` ou
  `dump_records` lèvent, c'est-à-dire si le handler a produit un XML
  invalide, l'exception remonte dans `handle_messages`, qui la journalise et
  retourne `False` : la connexion est fermée sans réponse. Côté Windows cela
  donne « Le site distant a fermé le flux de transport »
  (`documentation/06-depannage.md` § 2). C'est le seul chemin où le client
  ne reçoit rien du tout.

Enfin, deux familles de handlers **n'atteignent jamais le chemin d'erreur du
dispatcher** parce qu'elles rattrapent tout localement et retournent une
faute déjà construite : les handlers CRUD/CA (via `FaultBuilder`) et
`GetHandler` (via `build_soap_fault`, `classes/handlers/base.py:39-40`).
Seuls `EnumerateHandler`, `PullHandler` et `ReleaseHandler` laissent
délibérément remonter une `ADWSException`.

### Exemple 1 — WS-Transfer Get en mode IMDA

Requête (`Get-ADUser -Identity demo -Properties sAMAccountName`, forme IMDA
avec attributs demandés) :

```xml
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
            xmlns:a="http://www.w3.org/2005/08/addressing"
            xmlns:ad="http://schemas.microsoft.com/2008/1/ActiveDirectory"
            xmlns:da="http://schemas.microsoft.com/2006/11/IdentityManagement/DirectoryAccess">
  <s:Header>
    <a:Action s:mustUnderstand="1">
      http://schemas.xmlsoap.org/ws/2004/09/transfer/Get</a:Action>
    <a:MessageID>urn:uuid:2b5f1c40-9d21-4a77-8f0e-1d8c3b7a4e56</a:MessageID>
    <a:ReplyTo>
      <a:Address>http://www.w3.org/2005/08/addressing/anonymous</a:Address>
    </a:ReplyTo>
    <a:To s:mustUnderstand="1">
      net.tcp://samba.local:9389/ActiveDirectoryWebServices/Windows/Resource</a:To>
    <ad:objectReferenceProperty>CN=demo,CN=Users,DC=samba,DC=local
      </ad:objectReferenceProperty>
    <ad:instance>ldap:389</ad:instance>
  </s:Header>
  <s:Body>
    <da:BaseObjectSearchRequest Dialect="http://schemas.microsoft.com/2008/1/
ActiveDirectory/Dialect/XPath-Level-1">
      <da:AttributeType>addata:sAMAccountName</da:AttributeType>
    </da:BaseObjectSearchRequest>
  </s:Body>
</s:Envelope>
```

`RequestContext` en tire : `action = ".../transfer/Get"`, `message_id =
"urn:uuid:2b5f…"`, `object_reference =
"CN=demo,CN=Users,DC=samba,DC=local"`, `is_imda = True` (présence de
`<da:BaseObjectSearchRequest>`, `context.py:66-69`), `requested_attributes =
["sAMAccountName"]` (le préfixe `addata:` est retiré en `context.py:79-80`).

Réponse (`GetHandler._get_object` → `imda_projection`, forme a) :

```xml
<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
            xmlns:a="http://www.w3.org/2005/08/addressing"
            xmlns:ad="http://schemas.microsoft.com/2008/1/ActiveDirectory"
            xmlns:addata="http://schemas.microsoft.com/2008/1/ActiveDirectory/Data"
            xmlns:da="http://schemas.microsoft.com/2006/11/IdentityManagement/DirectoryAccess"
            xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
            xmlns:xsd="http://www.w3.org/2001/XMLSchema">
  <s:Header>
    <a:Action s:mustUnderstand="1">
      http://schemas.xmlsoap.org/ws/2004/09/transfer/GetResponse</a:Action>
    <a:RelatesTo>urn:uuid:2b5f1c40-9d21-4a77-8f0e-1d8c3b7a4e56</a:RelatesTo>
  </s:Header>
  <s:Body>
    <da:BaseObjectSearchResponse>
      <da:PartialAttribute>
        <addata:sAMAccountName LdapSyntax="UnicodeString">
          <ad:value xsi:type="xsd:string">demo</ad:value>
        </addata:sAMAccountName>
      </da:PartialAttribute>
      <da:PartialAttribute>
        <ad:distinguishedName>
          <ad:value xsi:type="xsd:string">CN=demo,CN=Users,DC=samba,DC=local</ad:value>
        </ad:distinguishedName>
      </da:PartialAttribute>
    </da:BaseObjectSearchResponse>
  </s:Body>
</s:Envelope>
```

Le `<da:PartialAttribute>` final portant `distinguishedName` est
**toujours** émis, y compris s'il n'a pas été demandé : c'est
`imda_projection` (`classes/serialization/object_projector.py:30-39`) qui
l'ajoute inconditionnellement, en concaténant `attrs_xml` puis
`<da:PartialAttribute>{dn_syn}</da:PartialAttribute>`
(`object_projector.py:34-38`). Il est en espace `ad:` et **sans**
`LdapSyntax`, invariant projet, et exigence du désérialiseur client.

> **Une exception à cet invariant, dans le code même.** `imda_projection`
> n'est appelée que lorsque `context.is_imda` **et**
> `context.requested_attributes` sont tous deux vrais (`get.py:273-274`). La
> RootDSE en mode IMDA passe par un chemin distinct (`get.py:146-151`) qui
> appelle `render_attributes(attributes, wrap_partial=True)` et n'ajoute
> **aucun** `distinguishedName`. C'est défendable, la RootDSE n'a pas de DN,
> mais cela signifie que l'affirmation « en IMDA, toujours émettre
> `distinguishedName` » souffre une exception qu'il faut connaître avant de
> déboguer une réponse RootDSE.

Le rendu des attributs ordinaires est porté par `AttributeRenderer` :
enveloppe `<da:PartialAttribute>` si `wrap_partial` (`xml_renderer.py:30`),
valeur en `<ad:value xsi:type="{xsd}">` (`:42`), attribut en `<addata:{nom}
LdapSyntax="{syn}">` (`:47`).

### Exemple 2 — WS-Enumeration Enumerate puis Pull

Requête `Enumerate` (`Get-ADUser -Filter *`) :

```xml
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
            xmlns:a="http://www.w3.org/2005/08/addressing"
            xmlns:wsen="http://schemas.xmlsoap.org/ws/2004/09/enumeration"
            xmlns:ad="http://schemas.microsoft.com/2008/1/ActiveDirectory"
            xmlns:adlq="http://schemas.microsoft.com/2008/1/ActiveDirectory/Dialect/LdapQuery">
  <s:Header>
    <a:Action s:mustUnderstand="1">
      http://schemas.xmlsoap.org/ws/2004/09/enumeration/Enumerate</a:Action>
    <a:MessageID>urn:uuid:7d3a0e18-4c62-45b1-9a77-0f2e5b91c3d4</a:MessageID>
    <a:To s:mustUnderstand="1">
      net.tcp://samba.local:9389/ActiveDirectoryWebServices/Windows/Enumeration</a:To>
    <ad:instance>ldap:389</ad:instance>
  </s:Header>
  <s:Body>
    <wsen:Enumerate>
      <wsen:Filter Dialect="http://schemas.microsoft.com/2008/1/
ActiveDirectory/Dialect/LdapQuery">
        <adlq:LdapQuery>
          <adlq:BaseObject>DC=samba,DC=local</adlq:BaseObject>
          <adlq:Scope>Subtree</adlq:Scope>
          <adlq:Filter>(&amp;(objectClass=user)(objectCategory=person))</adlq:Filter>
        </adlq:LdapQuery>
      </wsen:Filter>
      <ad:Selection Dialect="http://schemas.microsoft.com/2008/1/
ActiveDirectory/Dialect/XPath-Level-1">
        <ad:SelectionProperty>addata:sAMAccountName</ad:SelectionProperty>
        <ad:SelectionProperty>ad:distinguishedName</ad:SelectionProperty>
      </ad:Selection>
    </wsen:Enumerate>
  </s:Body>
</s:Envelope>
```

`RequestContext` extrait ici `base_dn` (`context.py:95-97`), `ldap_scope`
(`:104-106`), `ldap_filter` (`:99-102`, désérialisé des cinq entités XML
prédéfinies par `_unescape_xml_entities`, `context.py:180-190`) et
`selection_attributes` (préfixes `ad:` / `addata:` retirés, `:114-119`).
Tous ces XPath sont **relatifs à `<wsen:Enumerate>`** (`context.py:92-93`),
non au document : c'est le seul bloc du parseur qui ne cherche pas partout.

Réponse `EnumerateResponse` (`enumerate.py:106-129`) :

```xml
<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
            xmlns:a="http://www.w3.org/2005/08/addressing"
            xmlns:wsen="http://schemas.xmlsoap.org/ws/2004/09/enumeration">
  <s:Header>
    <a:Action s:mustUnderstand="1">
      http://schemas.xmlsoap.org/ws/2004/09/enumeration/EnumerateResponse</a:Action>
    <a:RelatesTo>urn:uuid:7d3a0e18-4c62-45b1-9a77-0f2e5b91c3d4</a:RelatesTo>
  </s:Header>
  <s:Body>
    <wsen:EnumerateResponse>
      <wsen:Expires>2026-08-07T15:42:10.512345Z</wsen:Expires>
      <wsen:EnumerationContext>3f1c9a02-…</wsen:EnumerationContext>
    </wsen:EnumerateResponse>
  </s:Body>
</s:Envelope>
```

L'ordre `Expires` puis `EnumerationContext` est celui du code
(`enumerate.py:122-123`) ; la durée de vie est d'une heure, en dur
(`enumerate.py:67`, `:81`). Le format d'horodatage est
`datetime.utcnow.isoformat + "Z"`, donc à la microseconde.

Requête `Pull` puis réponse (`pull.py:75-114`) :

```xml
<s:Body>
  <wsen:Pull>
    <wsen:EnumerationContext>3f1c9a02-…</wsen:EnumerationContext>
    <wsen:MaxElements>256</wsen:MaxElements>
  </wsen:Pull>
</s:Body>
```

```xml
<s:Body>
  <wsen:PullResponse>
    <wsen:Items>
      <addata:user>
        <ad:objectReferenceProperty>
          <ad:value xsi:type="xsd:string">f6aac55f-…</ad:value>
        </ad:objectReferenceProperty>
        <addata:sAMAccountName LdapSyntax="UnicodeString">
          <ad:value xsi:type="xsd:string">demo</ad:value>
        </addata:sAMAccountName>
        <ad:relativeDistinguishedName>
          <ad:value xsi:type="xsd:string">CN=demo</ad:value>
        </ad:relativeDistinguishedName>
        <ad:distinguishedName>
          <ad:value xsi:type="xsd:string">CN=demo,CN=Users,DC=samba,DC=local</ad:value>
        </ad:distinguishedName>
      </addata:user>
    </wsen:Items>
    <wsen:EndOfSequence/>
  </wsen:PullResponse>
</s:Body>
```

Deux règles à retenir : les items d'un `Pull` emploient la forme **objet
entier** (`whole_object`, appelé en `pull.py:56`), jamais des
`PartialAttribute` ; et la continuation est **exclusive**, soit
`<wsen:EndOfSequence/>`, soit un nouveau `<wsen:EnumerationContext>`, jamais
les deux (`pull.py:85-91`). Si le lot est vide, l'élément est auto-fermé
`<wsen:Items/>` (`pull.py:83-84`).

L'ordre des enfants de `<addata:user>` est fixé par `whole_object`
(`object_projector.py:20-28`) : `objectReferenceProperty` (`:24`, omis si le
GUID est vide), les attributs ordinaires (`:23`),
`relativeDistinguishedName` (`:26`), `distinguishedName` (`:27`).

Quelques valeurs par défaut, et leur contrepartie dans la référence :

| Paramètre | Ce projet | Ancrage | Référence |
|---|---|---|---|
| `MaxElements` absent | 100 | `pull.py:20` | 1 |
| durée de vie du contexte | 3600 s | `enumerate.py:67`, `:81` | non lu ici |
| résultats maximum par contexte | 50000 | `enumeration_registry.py:12` | non lu ici |
| `Scope` absent | `Subtree` | `enumerate.py:25` | non lu ici |
| filtre absent | `(objectClass=*)` | `enumerate.py:24` | non lu ici |

L'écart sur `MaxElements` mérite un mot : un client qui omettrait
`<wsen:MaxElements>` obtiendrait un objet par `Pull` chez Microsoft, cent
ici. Le module `ActiveDirectory` renseigne toujours le champ, si bien que la
divergence reste théorique, mais elle est réelle.

### Exemple 3 — action personnalisée SetPassword, succès et faute

Requête (`Set-ADAccountPassword -Reset`) :

```xml
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
            xmlns:a="http://www.w3.org/2005/08/addressing"
            xmlns:ca="http://schemas.microsoft.com/2008/1/ActiveDirectory/CustomActions">
  <s:Header>
    <a:Action s:mustUnderstand="1">http://schemas.microsoft.com/2008/1/
ActiveDirectory/CustomActions/AccountManagement/SetPassword</a:Action>
    <a:MessageID>urn:uuid:9c02f6b7-3e51-4d88-b0a4-77e6c1d2f309</a:MessageID>
    <a:To s:mustUnderstand="1">net.tcp://samba.local:9389/
ActiveDirectoryWebServices/Windows/AccountManagement</a:To>
    <ca:Server s:mustUnderstand="1">dc1.samba.local</ca:Server>
  </s:Header>
  <s:Body>
    <ca:SetPasswordRequest>
      <ca:PartitionDN>DC=samba,DC=local</ca:PartitionDN>
      <ca:AccountDN>CN=demo,CN=Users,DC=samba,DC=local</ca:AccountDN>
      <ca:NewPassword>…</ca:NewPassword>
    </ca:SetPasswordRequest>
  </s:Body>
</s:Envelope>
```

> **La requête réelle est plus riche que cet exemple.** le contrat
> SetPassword du service Microsoft déclare quatre membres, pas deux : un
> en-tête un en-tête de message obligatoire `Server` et trois membres de
> corps, `PartitionDN` (`:12`), `AccountDN` (`:15`) et `NewPassword`
> (`:18`). Ce serveur n'en lit que deux.

`BodyParser.find_custom_body("SetPasswordRequest")`
(`classes/parsing/body_parser.py:34-38`) localise l'élément par
`.//ca:SetPasswordRequest` avec la table de préfixes de
`body_parser.py:7-14` ; `text_of` (`body_parser.py:40-46`) fait de même pour
les enfants. C'est ce qui rend le parsing indifférent au préfixe choisi par
le client : ElementTree résout `ca:` vers l'URI, si bien qu'un client
émettant `<tns:SetPasswordRequest xmlns:tns="…/CustomActions">` est trouvé
tout aussi bien.

> **Le « repli » des lignes 38 et 45 est un no-op.** `.//ca:X` résolu avec
> `NS` et `.//{CUSTOM_ACTIONS}X` désignent, pour ElementTree, exactement le
> même chemin : le second `find` ne peut jamais réussir là où le premier a
> échoué. La vraie limite est ailleurs, un élément **sans espace de noms**
> ne serait trouvé par aucune des deux formes, contrairement au repli
> `.//Action` de `context.py:58` qui, lui, couvre réellement ce cas.

Réponse en cas de succès (`set_password.py:23-24`) :

```xml
<?xml version="1.0" encoding="utf-8"?>
<s:Envelope …déclarations NS_DECL…>
  <s:Header>
    <a:Action s:mustUnderstand="1">http://schemas.microsoft.com/2008/1/
ActiveDirectory/CustomActions/AccountManagement/SetPasswordResponse</a:Action>
    <a:RelatesTo>urn:uuid:9c02f6b7-3e51-4d88-b0a4-77e6c1d2f309</a:RelatesTo>
  </s:Header>
  <s:Body>
    <SetPasswordResponse
      xmlns="http://schemas.microsoft.com/2008/1/ActiveDirectory/CustomActions">
    </SetPasswordResponse>
  </s:Body>
</s:Envelope>
```

Réponse en cas d'échec (`set_password.py:27-29` →
`FaultBuilder.custom_action_fault`) :

```xml
<?xml version="1.0" encoding="utf-8"?>
<s:Envelope …déclarations NS_DECL…>
  <s:Header>
    <a:Action s:mustUnderstand="1">
      http://schemas.microsoft.com/2008/1/ActiveDirectory/Data/fault</a:Action>
    <a:RelatesTo>urn:uuid:9c02f6b7-3e51-4d88-b0a4-77e6c1d2f309</a:RelatesTo>
  </s:Header>
  <s:Body>
    <s:Fault>
      <s:Code>
        <s:Value>s:Receiver</s:Value>
        <s:Subcode><s:Value>ca:SetPasswordFault</s:Value></s:Subcode>
      </s:Code>
      <s:Reason>
        <s:Text xml:lang="en-US">Constraint violation - password too short</s:Text>
      </s:Reason>
      <s:Detail>
        <SetPasswordFault
          xmlns="http://schemas.microsoft.com/2008/1/ActiveDirectory/CustomActions"
          xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
          <ArgumentError xsi:nil="true"></ArgumentError>
          <DirectoryError xsi:nil="true"></DirectoryError>
          <Error>Constraint violation - password too short</Error>
          <ShortError>Constraint violation - password too short</ShortError>
        </SetPasswordFault>
      </s:Detail>
    </s:Fault>
  </s:Body>
</s:Envelope>
```

### Exemple 4 — faute générique du dispatcher

Pour une action inconnue, `_invoke` lève une `ADWSException`
(`dispatcher.py:41`) et `_fault` produit :

```xml
<?xml version="1.0" encoding="utf-8"?>
<s:Envelope …déclarations NS_DECL…>
  <s:Header>
    <a:Action s:mustUnderstand="1">
      http://www.w3.org/2005/08/addressing/soap/fault</a:Action>
    <a:RelatesTo>urn:uuid:1a2b3c4d-…</a:RelatesTo>
  </s:Header>
  <s:Body>
    <s:Fault>
      <s:Code><s:Value>s:Receiver</s:Value></s:Code>
      <s:Reason>
        <s:Text xml:lang="en-US">Unknown action: …/Foo. Known: Get, Enumerate, …</s:Text>
      </s:Reason>
    </s:Fault>
  </s:Body>
</s:Envelope>
```

Ni `<s:Subcode>` ni `<s:Detail>` : le dispatcher appelle
`SoapEnvelope.fault(relates_to, "s:Receiver", message)` sans plus. Le seul
élément qui rende la faute exploitable côté client est le `RelatesTo`, ce
qui referme la boucle du chapitre.

### Synthèse des écarts connus de la couche message

| Écart | Niveau visé | Statut |
|---|---|---|
| `mustUnderstand` jamais vérifié en entrée | spec | assumé |
| `a:ReplyTo` / `a:FaultTo` ignorés | spec | assumé (canal duplex) |
| Action de faute WS-A 1.0 au lieu des actions par famille | client | à aligner |
| Fautes CA en `s:Receiver` au lieu de `s:Sender` | client | à corriger |
| `directory_error` en `s:Receiver` pour des erreurs client | client | à corriger |
| `<s:Reason>` porte le message, pas la chaîne fixe attendue | client | mineur |
| `ArgumentError` / `DirectoryError` toujours `xsi:nil` | client | à enrichir |
| `ad:instance` jamais lu | client | assumé (mono-instance) |
| En-tête `Server` de `SetPasswordRequest` ignoré | client | assumé (mono-DC) |
| `PartitionDN` du corps `SetPassword` ignoré | client | assumé |
| `message_id` non échappé dans `get.py` | robustesse | à corriger |
| Contrôle critique inconnu silencieusement ignoré | spec LDAP v3 | à corriger |
| Quatre OID de contrôle mal traduits en noms LDB | spec LDAP | **bug** |
| Valeur BER des contrôles décodée en UTF-8 | spec | limite structurelle |
| `criticality` lue seulement sous la forme `true` | spec XSD | mineur |
| `context.ldap_controls` utilisé par le seul `Enumerate` | client | à étendre |
| `tree_delete` détecté par recherche de chaîne brute | robustesse | à durcir |
| `TypedFaults` et `fault_codes` non câblés | client | chantier ouvert |
| `EnumerationContextLimitExceeded` classé sous WS-Enum | client | à reclasser |
| Aucun mapping `ResultCode` LDAP → faute typée | client | chantier ouvert |
| `RelatesTo` vide si le parsing échoue | client | limite connue |
| `MaxElements` par défaut 100 au lieu de 1 | client | sans effet observé |
| `documentation/03-protocole.md` décrit un `ResourceReference` | doc | à corriger |
| `documentation/03-protocole.md` attribue des `ResultCode` à `fault_codes.py` | doc | à corriger |

Les deux dernières lignes concernent la documentation du dépôt, pas le code
: `documentation/03-protocole.md:117-120` montre un bloc
`<wsa:ResourceReference><wsa:InstanceId>` qui n'existe nulle part dans la
référence, et `:241-249` attribue à `src/faults/fault_codes.py` six libellés
qui n'y figurent pas. Conformément au § 7 du CLAUDE.md, ces deux corrections
doivent partir dans le même commit que toute modification du comportement
décrit.

# Partie VII. Les opérations d’annuaire

## Modèle de données [MS-ADDM] et projection des objets AD

Les chapitres précédents ont mené le lecteur du cadrage `net.tcp` jusqu'à
l'enveloppe SOAP 1.2 en clair. À partir d'ici, le transport disparaît : tout
ce qui suit décrit la **sémantique applicative** d'ADWS, c'est-à-dire la
manière dont un objet de l'annuaire est identifié, projeté en XML, filtré,
muté et paginé.

### Les trois couches de vocabulaire

ADWS ne définit pas son propre modèle d'annuaire : il projette le modèle
d'Active Directory décrit par [MS-ADTS] à travers un jeu d'espaces de noms
défini par [MS-ADDM] (*Active Directory Web Services: Data Model and Common
Elements*). Cinq espaces de noms portent la totalité de la charge utile
applicative, et le dépôt les centralise dans un module unique
(`src/soap/namespaces.py:3-16`).

| Préfixe | URI | Rôle |
|---|---|---|
| `ad` | `http://schemas.microsoft.com/2008/1/ActiveDirectory` | Éléments *structurels* : `value`, `objectReferenceProperty`, `distinguishedName`, `controls`, `instance` |
| `addata` | `http://schemas.microsoft.com/2008/1/ActiveDirectory/Data` | Un élément **par attribut LDAP**, nommé d'après son `lDAPDisplayName` |
| `da` | `http://schemas.microsoft.com/2006/11/IdentityManagement/DirectoryAccess` | Opérations IMDA ([MS-WSTIM]) : `BaseObjectSearchRequest`, `AddRequest`, `ModifyRequest` |
| `adlq` | `http://schemas.microsoft.com/2008/1/ActiveDirectory/Dialect/LdapQuery` | Dialecte de filtre pour `Enumerate` |
| `ca` | `http://schemas.microsoft.com/2008/1/ActiveDirectory/CustomActions` | Actions propriétaires hors WS-* (mots de passe, topologie, groupes) |

La distinction `ad:` contre `addata:` n'est pas cosmétique : c'est **la**
règle qui décide si le client Windows accepte ou rejette la réponse. Tout
élément placé dans `addata:` est traité comme un attribut d'annuaire et
**doit** porter un attribut XML `LdapSyntax` ; tout élément placé dans `ad:`
est un élément structurel et **ne doit pas** en porter. Ces deux invariants
sont matérialisés dans `classes/serialization/xml_renderer.py:45-49` (chemin
`addata:`) et `classes/serialization/object_projector.py:48-53` (chemin
`ad:`).

### L'identité d'un objet : `objectReferenceProperty`

Le client n'adresse jamais un objet par une URL. Il place l'identité dans un
**en-tête SOAP** `<ad:objectReferenceProperty>`, accompagné d'un en-tête
`<ad:instance>`. La règle appliquée par le serveur Microsoft est la suivante
:

| Étape | Comportement |
|---|---|
| `objectReferenceProperty` | exigé pour `Get`, `Delete`, `Put` |
| `instance` | exigé pour **toutes** les opérations |
| Discrimination GUID / DN | `1623-1645` | 36 caractères + `guidRegex` → `Guid` |
| Repli DN | `1639-1643` | si le `Guid` reste `Guid.Empty` → `ObjectDn` |
| Résolution de l'instance | `1647-1653` | `GlobalInstanceMap`, sinon faute |

L'absence de l'un des deux en-têtes lève une `ArgumentException`
(`MustSpecifyObjectRefPropInTheHeader`,
`MustSpecifyInstanceInfoInTheHeader`) ; une valeur d'`instance` inconnue de
la carte globale lève `InvalidInstanceInTheHeader`.

Ce projet extrait la même valeur (`classes/parsing/context.py:64`) mais avec
un `findtext` non ancré (`.//ad:objectReferenceProperty`), qui la trouve
donc aussi bien dans l'en-tête que dans le corps. L'en-tête `<ad:instance>`
n'est, lui, **jamais lu** : aucune recherche de cet élément n'existe dans
`context.py`, et aucune faute n'est levée s'il manque. En revanche la
**résolution** est plus étroite : `classes/handlers/get.py:211-214`
construit la liste des DN à essayer et lance un `search(base=...)` sur
chacun. Conséquences à connaître :

- un `objectReferenceProperty` en forme **DN** fonctionne ;
- la branche RootDSE est déclenchée par trois valeurs, pas une seule
  (`classes/handlers/get.py:39-42`) : chaîne vide, littéral `root dse`
  (comparaison en minuscules) et `11111111-1111-1111-1111-111111111111` ;
- le second candidat `f"{obj_ref},{self.naming_context}"` (`get.py:214`) est
  **du code mort** : il est gardé par `hasattr(self, 'naming_context')`
  (`get.py:213`) et ni `BaseHandler.__init__`
  (`classes/handlers/base.py:19-29`) ni `GetHandler` ne définissent cet
  attribut, le contexte de nommage n'est accessible que par la méthode
  `self.db.naming_context`. Un DN relatif n'est donc jamais complété ;
- tout **autre GUID** n'est pas converti en DN : la recherche LDB échoue et
  le handler renvoie `Object not found`. La syntaxe `<GUID=…>` de LDB n'est
  pas employée. C'est un écart assumé par rapport au serveur Microsoft, sans
  impact observé sur les cmdlets testées, qui adressent par DN.

### Projection d'un objet : l'ordre imposé des éléments

Le serveur Microsoft écrit toujours les composants d'un objet dans un ordre
fixe. Le dépôt reproduit cet ordre dans
`classes/serialization/object_projector.py:20-28` :

```text
<addata:{objectClassStructurelle}>
  <ad:objectReferenceProperty>        (si le GUID est connu)
  <addata:attribut1 LdapSyntax="…">   (flux des attributs LDAP)
  <addata:attribut2 LdapSyntax="…">
  ...
  [<ad:containerHierarchyParent>]     (non émis par ce projet)
  <ad:relativeDistinguishedName>
  <ad:distinguishedName>
</addata:{objectClassStructurelle}>
```

Le nom du wrapper est la classe **structurelle**, obtenue en prenant la
*dernière* valeur de `objectClass` (`classes/handlers/get.py:79-100`,
`classes/handlers/pull.py:58-65`), LDB renvoie la hiérarchie de la plus
générale à la plus spécifique, donc `top, person, organizationalPerson,
user` donne `user`. La valeur de repli est `top` ; c'est ce qui est utilisé
pour la RootDSE (`classes/handlers/get.py:161`).

Le tableau ci-dessous fait correspondre chaque étape du serveur Microsoft à
sa contrepartie dans le dépôt.

| Composant | Service ADWS Microsoft | Ce projet |
|---|---|---|
| Wrapper `addata:{classe}` | `65` / `69-73` | `object_projector.py:28` |
| `ad:objectReferenceProperty` | `75-82` | `object_projector.py:24` |
| Boucle des attributs `addata:` | `83-115` | `xml_renderer.py:22-33` |
| Attribut XML `LdapSyntax` | `106` | `xml_renderer.py:45-49` |
| `ad:containerHierarchyParent` | `116-123` | non émis |
| `ad:relativeDistinguishedName` | `124-131` | `object_projector.py:26` |
| `ad:distinguishedName` | `132-139` | `object_projector.py:27` |

Deux comportements du serveur de référence n'ont **aucune** contrepartie ici
:

- `containerHierarchyParent` n'est émis que si `ParentIdentity` est
  renseigné . Ce projet le déclare comme attribut synthétique et le
  **filtre** systématiquement (`object_projector.py:9-12`) sans jamais le
  produire ; aucune cmdlet testée ne s'en plaint.
- la **récupération par plages** (*range retrieval*) : quand le nom
  d'attribut contient ` ;range=`, Microsoft découpe le suffixe et émet deux
  attributs XML `rangeLow` et `rangeHigh` sur l'élément `addata:` . Ce
  projet ne reconnaît pas la syntaxe ` ;range=` : un attribut lié très
  volumineux (par exemple `member` sur un groupe de plusieurs milliers
  d'entrées) est rendu d'un seul tenant ou tronqué par LDB, sans négociation
  de plage.

### Les quatre attributs synthétiques

| Élément | Espace | `LdapSyntax` | Source de la valeur |
|---|---|---|---|
| `objectReferenceProperty` | `ad:` | non | `objectGUID` converti en GUID canonique |
| `containerHierarchyParent` | `ad:` | non | non émis par ce projet |
| `relativeDistinguishedName` | `ad:` | non | premier segment du DN |
| `distinguishedName` | `ad:` | non | DN complet de l'objet |

Ces quatre noms sont regroupés dans `SYNTHETIC_KEYS`
(`classes/serialization/object_projector.py:9-12`), en minuscules, et
`_normal` (`object_projector.py:41-46`) les **retire du flux d'attributs
normaux**. Sans ce filtrage, Samba, qui expose `distinguishedName` comme un
attribut LDAP ordinaire, provoquerait l'émission simultanée d'un
`<addata:distinguishedName LdapSyntax="…">` et d'un
`<ad:distinguishedName>`, soit deux représentations concurrentes de la même
donnée dans le même objet.

Côté Microsoft, les quatre synthétiques sont tous écrits comme des chaînes
Unicode : ils portent donc un enfant `<ad:value xsi:type="xsd:string">` mais
**jamais** d'attribut `LdapSyntax`, celui-ci n'étant émis que dans la boucle
des attributs `addata:`. Le dépôt obtient le même résultat structurellement
: `_synthetic` (`object_projector.py:48-53`) est une fonction de deux lignes
qui ne sait pas écrire d'attribut XML.

Point crucial : `objectReferenceProperty` est typé `xsd:string` alors que
l'attribut LDAP `objectGUID` est typé `xsd:base64Binary`. Ce n'est pas une
incohérence. Côté Microsoft, `objectReferenceProperty` est un identifiant
global et le sérialiseur de valeurs du client sérialise un identifiant
global en `xsd:string` sous sa forme canonique, alors que `objectGUID` est
chargé en `octets` et part en base64. Le dépôt reproduit ce dédoublement :
conversion `uuid.UUID(bytes_le=…)` pour l'EPR
(`classes/handlers/get.py:270-271`, `classes/handlers/pull.py:67-73`) et
base64 brut pour l'attribut.

---

## WS-Transfer : Get, Put, Create, Delete

WS-Transfer fournit les quatre opérations élémentaires sur une ressource
unique. ADWS n'ajoute aucune action à ce jeu ; il en spécialise le corps.

| Action SOAP | Action de réponse | Handler d'entrée | Implémentation |
|---|---|---|---|
| `…/transfer/Get` | `…/transfer/GetResponse` | `GetHandler` | `classes/handlers/get.py` |
| `…/transfer/Put` | `…/transfer/PutResponse` | `TransferHandler` | `classes/handlers/modify.py` |
| `…/transfer/Delete` | `…/transfer/DeleteResponse` | `TransferHandler` | `classes/handlers/delete.py` |
| `…/transfer/Create` | `…/transfer/CreateResponse` | `CRUDHandler` | `classes/handlers/create.py` |

Le routage exact est table-dirigé : `ACTION_HANDLER_KEYS`
(`src/handlers/handler_routing.py:35-51`) contient les URI complètes en
minuscules, et `HandlerRegistry.resolve`
(`classes/handlers/handler_registry.py:15-23`) tente d'abord cette
correspondance exacte insensible à la casse, puis retombe sur le **dernier
segment** de l'URI. `TransferHandler` et `CRUDHandler` sont de simples
aiguilleurs qui relisent le suffixe de l'action (`transfer.py:16-26`,
`crud.py:18-30`) pour appeler `ModifyHandler`, `DeleteHandler` ou
`CreateHandler`.

### Get

Un `Get` WS-Transfer pur a un corps **vide** (ou contenant uniquement un
bloc `<ad:controls>`). Toute l'information est dans les en-têtes.

```xml
<s:Header>
  <a:Action s:mustUnderstand="1"
    >http://schemas.xmlsoap.org/ws/2004/09/transfer/Get</a:Action>
  <a:MessageID>urn:uuid:ece4c158-...</a:MessageID>
  <ad:instance>ldap:389</ad:instance>
  <ad:objectReferenceProperty
    >CN=Administrator,CN=Users,DC=samba,DC=local</ad:objectReferenceProperty>
</s:Header>
<s:Body/>
```

Côté serveur, `GetHandler._get_object` (`classes/handlers/get.py:200-310`)
exécute une recherche `SCOPE_BASE` avec l'expression `(objectClass=*)`, la
liste d'attributs `['*']`, augmentée des attributs explicitement demandés
(`get.py:223-225`) puis étendue par `ConstructedAttrs.expand`
(`get.py:226`), et le contrôle `sd_flags:1:0` (`get.py:220`).

Ce dernier mérite une lecture attentive, car la chaîne de contrôle LDB a la
forme `nom:criticité:valeur`, la même que celle produite par
`ControlsParser._translate` (`classes/parsing/controls_parser.py:62-74`).
Ici la **criticité vaut 1** et la **valeur du masque `SD_FLAGS` vaut 0** ;
ce n'est donc pas `OWNER_SECURITY_INFORMATION`. Le contrôle
`LDAP_SERVER_SD_FLAGS_OID` (`1.2.840.113556.1.4.801`, [MS-ADTS]) sélectionne
les portions du `nTSecurityDescriptor` à renvoyer ; avec un masque nul, la
SACL, dont la lecture exige le privilège `SeSecurityPrivilege`, est exclue,
ce qui évite qu'une lecture par un compte non privilégié n'échoue. La même
paire base vide / `sd_flags:1:0` est employée pour la RootDSE
(`get.py:120`).

La réponse porte l'action `…/transfer/GetResponse` **quelle que soit** la
forme retenue (WS-Transfer ou IMDA) ; c'est aussi ce que fait le serveur
Microsoft, qui construit le même URI d'action sur ses deux branches : le
service ADWS Microsoft pour le `BaseObjectSearchResponse` IMDA et le service
ADWS Microsoft pour l'objet WS-Transfer. Le discriminant de forme est traité
en détail plus bas.

#### Le cas RootDSE

`Get-ADRootDSE` est le tout premier échange de n'importe quelle session. Il
passe par le même `GetHandler`, branche `_get_root_dse`
(`classes/handlers/get.py:110-198`) : recherche `SCOPE_BASE` sur une base
vide, `objectClass` retiré du flux, wrapper `<addata:top>` et
`objectReferenceProperty` fixé à `11111111-1111-1111-1111-111111111111`.

Deux ajustements sont indispensables et méritent d'être connus :

- **Suppression d'attributs.** `_ROOTDSE_DROP`
  (`classes/handlers/get.py:15-17`) retire `vendorName` et `vendorVersion`,
  que Samba expose mais qu'un AD réel n'expose pas. Le client Windows résout
  le nom d'attribut dans une table de syntaxes RootDSE codée en dur, sans
  variante tolérante : une clé inconnue déclenche une exception côté client
  et **casse toutes les cmdlets** dès la connexion.
- **Ajout d'attributs.** `msDS-PortLDAP` et `msDS-PortSSL` sont injectés
  avec les valeurs `389` et `636` s'ils manquent
  (`classes/handlers/get.py:62-65`) : Samba ne les publie pas, le client les
  attend.

### Create

Le corps d'un `Create` est un `<da:AddRequest>` IMDA, jamais un objet
`addata:` complet. Le DN cible n'est pas transmis tel quel : le client
envoie un `relativeDistinguishedName` et un `container-hierarchy-parent`,
tous deux sous forme d'`<da:AttributeTypeAndValue>` ordinaires.

```xml
<s:Body>
  <da:AddRequest Dialect="http://schemas.microsoft.com/2008/1/
ActiveDirectory/Dialect/XPath-Level-1">
    <da:AttributeTypeAndValue>
      <da:AttributeType>ad:relativeDistinguishedName</da:AttributeType>
      <da:AttributeValue>
        <ad:value xsi:type="xsd:string">CN=demo</ad:value>
      </da:AttributeValue>
    </da:AttributeTypeAndValue>
    <da:AttributeTypeAndValue>
      <da:AttributeType>ad:container-hierarchy-parent</da:AttributeType>
      <da:AttributeValue>
        <ad:value xsi:type="xsd:string">CN=Users,DC=samba,DC=local</ad:value>
      </da:AttributeValue>
    </da:AttributeTypeAndValue>
    <da:AttributeTypeAndValue>
      <da:AttributeType>addata:objectClass</da:AttributeType>
      <da:AttributeValue>
        <ad:value xsi:type="xsd:string">user</ad:value>
      </da:AttributeValue>
    </da:AttributeTypeAndValue>
  </da:AddRequest>
</s:Body>
```

`CreateHandler._resolve_dn` (`classes/handlers/create.py:54-64`) applique
trois règles **dans cet ordre de priorité**, et non dans l'ordre inverse :

| Rang | Source | Ligne |
|---|---|---|
| **1.** | `distinguishedName` explicite dans le corps | `create.py:60-61` |
| **2.** | `f"{rdn},{parent}"` recomposé | `create.py:62-64` |
| **3.** | `objectReferenceProperty` de l'en-tête (repli) | `create.py:63-64` |

Le repli de rang 3 sert deux fois : comme `parent` si
`container-hierarchy-parent` manque, et comme DN complet si le `rdn` manque
aussi. Les trois clés de routage sont ensuite retirées du jeu d'attributs
(`DN_ROUTING`, `classes/handlers/create.py:23-25`) : ce ne sont pas des
attributs LDAP.

La réponse est un EPR WS-Addressing `ResourceCreated`
(`classes/handlers/create.py:74-90`) dont l'adresse est celle du `<a:To>` de
la requête avec `ResourceFactory` remplacé par `Resource`, et dont les
`ReferenceParameters` portent le `objectGUID` fraîchement lu et
`<ad:instance>ldap:389</ad:instance>`.

### Put

Le corps est un `<da:ModifyRequest>` contenant des `<da:Change>` portant
chacun un attribut `Operation` valant `add`, `delete` ou `replace`
(`classes/parsing/attribute_parser.py:19,37`). L'implémentation traite un
`Put` en deux temps (`classes/handlers/modify.py:21-36`) :

1. `_apply_rename` (`modify.py:48-61`) : si le `ModifyRequest` touche
  `relativeDistinguishedName` ou `container-hierarchy-parent`, ce n'est pas
  une modification d'attribut mais un `modrdn`. Un `ldb.rename` est exécuté,
  les deux clés sont retirées du lot et le nouveau DN devient la cible.
2. `_modify_attrs` (`modify.py:64-71`) : les changements restants sont
  compilés en `ldb.Message` par `LdapAttrBuilder.build_message` avec le
  drapeau par défaut `FLAG_MOD_REPLACE`, puis appliqués par `samdb.modify`.

C'est ce chemin unique qui sert `Set-ADUser`, `Rename-ADObject`,
`Move-ADObject`, `Enable-ADAccount`/`Disable-ADAccount` (qui ne sont qu'un
`replace` sur `userAccountControl`) et, très probablement,
`Add-ADGroupMember` et `Remove-ADGroupMember`, voir la réserve exprimée au
chapitre des appartenances.

La correspondance `Operation` → drapeau LDB est établie dans
`classes/directory/ldap_attr_builder.py:40-49` :

| `Operation` XML | Drapeau LDB | Effet |
|---|---|---|
| `add` | `FLAG_MOD_ADD` | ajoute des valeurs sans toucher aux existantes |
| `delete` ou `remove` | `FLAG_MOD_DELETE` | retire les valeurs listées |
| `replace` | `FLAG_MOD_REPLACE` | remplace l'ensemble des valeurs |
| absent | drapeau par défaut du contexte appelant | `ADD` pour Create, `REPLACE` pour Put |

La réponse `PutResponse` a un corps **vide** (`modify.py:74-75`).

### Delete

`Delete` n'a pas de corps utile. La seule subtilité est la suppression
récursive : `Remove-AD* -Recursive` joint le contrôle
`LDAP_SERVER_TREE_DELETE_OID` (`1.2.840.113556.1.4.805`). Le handler ne
parse pas le bloc de contrôles, il **cherche l'OID dans le XML brut**
(`classes/handlers/delete.py:40-44`) et, s'il le trouve, passe
`tree_delete:1` à `samdb.delete`. C'est un raccourci volontairement grossier
mais robuste ; il n'a pas de faux positif réaliste, l'OID étant unique.

---

## IMDA : BaseObjectSearchRequest et ModifyRequest

IMDA (*Identity Management Directory Access*) est la surcouche définie par
[MS-WSTIM] et étendue par [MS-WSPELD] pour Active Directory. Elle ne
remplace pas WS-Transfer : elle **s'y superpose**. Le client émet la même
action `…/transfer/Get`, mais ajoute un en-tête
`<da:IdentityManagementOperation>` et un corps
`<da:BaseObjectSearchRequest>`.

### BaseObjectSearchRequest

```xml
<s:Header>
  <a:Action s:mustUnderstand="1"
    >http://schemas.xmlsoap.org/ws/2004/09/transfer/Get</a:Action>
  <da:IdentityManagementOperation s:mustUnderstand="1"/>
  <ad:instance>ldap:389</ad:instance>
  <ad:objectReferenceProperty>CN=demo,CN=Users,DC=samba,DC=local
  </ad:objectReferenceProperty>
</s:Header>
<s:Body>
  <da:BaseObjectSearchRequest Dialect="http://schemas.microsoft.com/2008/1/
ActiveDirectory/Dialect/XPath-Level-1">
    <da:AttributeType>addata:cn</da:AttributeType>
    <da:AttributeType>addata:objectSid</da:AttributeType>
    <da:AttributeType>ad:distinguishedName</da:AttributeType>
  </da:BaseObjectSearchRequest>
</s:Body>
```

Le parseur du dépôt collecte tous les `<da:AttributeType>` en profondeur et
**retire le seul préfixe `addata:`** (`classes/parsing/context.py:74-83`) ;
le préfixe `ad:` reste attaché au nom.
`AttributeRenderer._normalize_request` (`xml_renderer.py:61-73`) sait
pourtant retirer les deux, mais n'est jamais sollicité : le paramètre
`requested` de `render_attributes` n'est passé par **aucun** des quatre
appelants (`get.py:142`, `schema.py:70`, `object_projector.py:23` et `:31`).
C'est du code mort. Le filtrage effectif a lieu en amont, dans
`GetHandler._prepare_attributes` (`get.py:67-77`), par comparaison en
minuscules et sans dépréfixage : un
`<da:AttributeType>ad:distinguishedName</da:AttributeType>` ne correspond
donc à aucune clé de l'objet LDB et disparaît du flux. D'où la nécessité,
pour `imda_projection`, d'émettre le DN synthétique inconditionnellement.

Le serveur Microsoft, lui, impose une limite dure de **100 `AttributeType`
par requête** : le test est à le service ADWS Microsoft et la faute
`EncodingLimit` (variante `EncodingLimitExceededDetailType.AttributeTypes`)
est levée à la ligne `312`. Cette limite n'est **pas** implémentée dans ce
projet.

Immédiatement après, il **exige** un `Dialect` dès que des `AttributeTypes`
sont présents (`ArgumentException(MissingDialect)`, le service ADWS
Microsoft) puis le valide via `DialectParser.IsDialectSupported` (`:318`).
La table des dialectes admis est codée dans
`DialectParser.GetSupportedDialects`, avec deux dialectes explicitement
rejetés par `DialectParser.Create` ; les URI proviennent de les constantes
du service ADWS Microsoft.

| `OperationType` | Dialecte admis |
|---|---|
| `Create`, `Put`, `Get` | `…/Dialect/XPath-Level-1` |
| `EnumerateSelection`, `EnumerateSort` | `…/Dialect/XPath-Level-1` |
| `EnumerateFilter` | `…/Dialect/LdapQuery` |
| toutes | `…/Dialect/QName` et `…/Dialect/XpathQuery` refusés |

**Ce projet ignore totalement l'attribut `Dialect`**, aucune occurrence dans
le code applicatif (seule l'URI `ADLQ` est déclarée,
`src/soap/namespaces.py:11`, et elle sert de préfixe de recherche XML, pas
de valeur à valider). Un client envoyant un dialecte absent, vide ou non
supporté obtiendrait un traitement au lieu d'une faute
`FragmentDialectNotSupported` ; la constante existe pourtant
(`src/faults/fault_codes.py:8`) mais n'est jamais levée.

### AddRequest et ModifyRequest

Les mutations IMDA emploient deux structures voisines mais **non
interchangeables**, ce que reflète `BodyParser`
(`classes/parsing/body_parser.py:22-32`) :

| Élément | Enfant répété | `default_op` transmis | Opération finale si `Operation` absent |
|---|---|---|---|
| `<da:AddRequest>` | `<da:AttributeTypeAndValue>` | `"add"` | `add` |
| `<da:ModifyRequest>` | `<da:Change>` | `None` | `replace` |

`AttributeParser.parse_changes`
(`classes/parsing/attribute_parser.py:12-25`) sélectionne le nom de balise
selon le drapeau `use_change`, puis `_read_entry`
(`attribute_parser.py:27-39`) lit le triplet `(name, operation, values)`.
L'attribut XML `Operation` est relu sur **les deux** formes (`op =
(node.get("Operation") or default_op or "replace").lower`,
`attribute_parser.py:37`) de sorte qu'un `AttributeTypeAndValue` portant
explicitement `Operation="delete"` serait honoré ; aucun client observé
n'exploite cette latitude. Le nom d'attribut est nettoyé de ses préfixes
`addata:` **et** `ad:` par `_strip_prefix` (`attribute_parser.py:61-67`), à
la différence du chemin de lecture décrit plus haut.

La lecture des valeurs (`attribute_parser.py:41-59`) est le point de contact
avec le typage XSD en **entrée** : un enfant portant
`xsi:type="…base64Binary"` est décodé via `b64decode`, tout le reste est
conservé en texte. Un repli existe pour les corps qui placent la valeur
directement dans `<da:AttributeValue>` sans enfant `<ad:value>`.

Cette asymétrie est importante : en sortie, le codage est piloté par la
**syntaxe LDAP** de l'attribut ; en entrée, il est piloté par le `xsi:type`
annoncé par le client. Le serveur Microsoft procède de la même façon dans le
désérialiseur de valeurs du client :

| Contrôle | Ligne C# | Échec |
|---|---|---|
| Le préfixe doit résoudre vers l'espace XSD | `144-148` | `UnknownAttributeType` |
| Nom local `base64Binary` → `Convert.FromBase64String` | `151-163` | `InvalidBase64Binary` |
| Nom local `string` → valeur texte brute | `165-173` | — |
| Tout autre nom local | `167-171` | `UnknownAttributeType` |

Dit autrement, **aucun `xsi:type` autre que `xsd:string` et
`xsd:base64Binary` n'est accepté en écriture**. Le dépôt, lui, est laxiste :
`AttributeParser._read_values` (`attribute_parser.py:41-59`) ne teste que le
suffixe `base64Binary` et traite tout le reste comme du texte, un
`xsi:type="xsd:int"` passerait silencieusement là où Microsoft faute.

### Le pendant en réponse : BaseObjectSearchResponse

La réponse IMDA n'est plus un objet mais une **projection**, encapsulée dans
des éléments `<da:PartialAttribute>`. La spécification [MS-WSTIM] décrit
deux formes selon que la requête a listé ou non des types d'attributs. Ce
n'est pas une liberté d'implémentation : le désérialiseur du client applique
un schéma strict.

> **Limite de vérification.** Les deux formes décrites ci-dessous reposent
> sur [MS-WSTIM] et sur le comportement observé du client, non sur une
> source normative exhaustive pour l'élément `PartialAttribute` lui-même.

---

## Le choix du rendu : WS-Transfer contre IMDA

C'est l'invariant le plus coûteux à violer de tout le protocole, et le
paragraphe le plus important de ce chapitre.

### Le discriminant exact

Dans ce dépôt, `RequestContext.is_imda` est calculé en un seul endroit,
`classes/parsing/context.py:66-69` :

```python
is_imda = (
    root.find('.//da:IdentityManagementOperation', namespaces=ns) is not None or
    root.find('.//da:BaseObjectSearchRequest', namespaces=ns) is not None
)
```

Soit, en clair : **la requête est IMDA si le message contient un en-tête
`<da:IdentityManagementOperation>` OU un corps
`<da:BaseObjectSearchRequest>`**, n'importe où dans le document. Elle est
WS-Transfer sinon.

Le serveur Microsoft, lui, ne teste **que l'en-tête**, au moyen du prédicat
`MessageContainsIdentityManagementHeader(request)` défini en le service ADWS
Microsoft et appelé en tête de chaque opération : ligne `84` pour `Create`,
`274` pour `Get`, `504` pour `Put`. Le corps n'est lu qu'après. La
disjonction retenue ici est donc **plus permissive** : un message qui
porterait un `BaseObjectSearchRequest` sans en-tête IMDA serait traité en
IMDA par ce projet et en WS-Transfer par Microsoft. Aucun client réel n'émet
cette combinaison, mais l'écart doit être documenté.

Deuxième conséquence du `findall` non ancré : quand un `Create` ou un `Put`
porte l'en-tête IMDA, les `<da:AttributeType>` contenus dans son
`<da:AddRequest>` ou son `<da:ModifyRequest>` alimentent eux aussi
`context.requested_attributes` (`context.py:73-83`), qui n'est donc pas
strictement une liste de projection. Sans effet pratique : `CreateHandler`
et `ModifyHandler` relisent intégralement le corps via `BodyParser` et
n'utilisent jamais ce champ.

### Les deux sous-formes IMDA

Une fois `is_imda` vrai, un second test départage les deux rendus. Il porte
sur la présence d'au moins un `<da:AttributeType>`, exposé par
`context.requested_attributes` (`classes/parsing/context.py:157`, qui vaut
`None` et non `[]` quand la liste est vide).

`classes/handlers/get.py:273-277` :

```python
if context.is_imda and context.requested_attributes:
    body_xml = self.serializer.imda_projection(attributes2, dn)
else:
    obj_xml = self.serializer.whole_object(attributes2, obj_class, guid, dn)
    body_xml = self._wrap_imda_object(obj_xml) if context.is_imda else obj_xml
```

**Forme a, au moins un `AttributeType` demandé.** Un `<da:PartialAttribute>`
par attribut, sans wrapper de classe d'objet, plus un dernier
`PartialAttribute` portant le `distinguishedName` synthétique
(`classes/serialization/object_projector.py:30-39`).

```xml
<s:Body>
  <da:BaseObjectSearchResponse>
    <da:PartialAttribute>
      <addata:cn LdapSyntax="UnicodeString">
        <ad:value xsi:type="xsd:string">demo</ad:value>
      </addata:cn>
    </da:PartialAttribute>
    <da:PartialAttribute>
      <addata:objectSid LdapSyntax="SidString">
        <ad:value xsi:type="xsd:base64Binary">AQUAAAAAAAUV...</ad:value>
      </addata:objectSid>
    </da:PartialAttribute>
    <da:PartialAttribute>
      <ad:distinguishedName>
        <ad:value xsi:type="xsd:string">CN=demo,CN=Users,DC=samba,DC=local
        </ad:value>
      </ad:distinguishedName>
    </da:PartialAttribute>
  </da:BaseObjectSearchResponse>
</s:Body>
```

**Forme b, aucun `AttributeType`.** L'objet entier, dans sa forme
WS-Transfer exacte, à l'intérieur d'**un seul** `<da:PartialAttribute>`
(`classes/handlers/get.py:102-108`). La documentation [MS-WSTIM] le formule
ainsi : lorsque la requête ne spécifie aucun type d'attribut, le serveur
retourne la représentation XML de l'objet d'identité entier comme contenu
d'un unique élément `PartialAttribute`.

```xml
<s:Body>
  <da:BaseObjectSearchResponse>
    <da:PartialAttribute>
      <addata:user>
        <ad:objectReferenceProperty>...</ad:objectReferenceProperty>
        <addata:cn LdapSyntax="UnicodeString">...</addata:cn>
        <ad:relativeDistinguishedName>...</ad:relativeDistinguishedName>
        <ad:distinguishedName>...</ad:distinguishedName>
      </addata:user>
    </da:PartialAttribute>
  </da:BaseObjectSearchResponse>
</s:Body>
```

> **Exception RootDSE.** `_get_root_dse` n'emploie ni `imda_projection` ni
> `_wrap_imda_object` : il rend directement les attributs avec
> `wrap_partial=context.is_imda` (`classes/handlers/get.py:142-151`), donc
> un `PartialAttribute` par attribut **même sans `AttributeType` demandé**,
> et sans `distinguishedName` synthétique (la RootDSE n'a pas de DN). C'est
> un écart local, validé empiriquement par le test `Get-ADRootDSE` du dépôt.

### Le symptôme Windows exact quand on se trompe

Répondre en forme WS-Transfer à une requête IMDA produit un document dont la
racine du corps est `<addata:{classe}>` alors que le désérialiseur attend
`<da:BaseObjectSearchResponse>`. Le parseur .NET applique le schéma en mode
strict et s'arrête sur le premier élément inattendu, presque toujours le
`<ad:distinguishedName>` final, puisqu'il est le dernier enfant du wrapper.
Message observé côté PowerShell francophone
(`documentation/06-depannage.md:106`) :

```text
Élément de fin 'subSchema' attendu, trouvé 'ad:distinguishedName'
```

Le nom de classe varie selon la cmdlet (`user`, `group`, `subSchema`,
`top`…). Si l'exception survient plus tôt, ou si le handler serveur lève
avant d'écrire le corps, le symptôme dégénère en :

```text
Get-ADUser : Le site distant a fermé le flux de transport.
```

Dans les deux cas, **aucune faute SOAP n'est visible côté client** : c'est
le parseur XML qui rompt, pas la couche applicative. Le seul diagnostic
fiable est la lecture du journal serveur.

### Pourquoi `distinguishedName` est toujours émis, en `ad:`, sans `LdapSyntax`

Trois raisons cumulatives, toutes vérifiables :

- **1. Contrainte de validation côté serveur.** Le service Microsoft refuse
  de sérialiser un objet dont l'un des quatre éléments d'identité est absent
  : identité d'objet, RDN, classe d'objet et nom distinctif. Ce contrôle est
  appliqué avant toute écriture, ce qui établit sans ambiguïté que ces
  quatre éléments font partie du contrat de l'objet ADWS.
- **2. Clé d'identité pour PowerShell.** Le module `ActiveDirectory` indexe
  les objets par leur DN. En forme a, aucun autre élément ne le porte : la
  projection n'a ni wrapper de classe, ni `objectReferenceProperty`, ni RDN.
  C'est pourquoi `imda_projection` ajoute inconditionnellement le
  `PartialAttribute` du DN (`object_projector.py:34-38`), **même si le
  client ne l'a pas demandé**, et c'est d'autant plus nécessaire qu'un
  `ad:distinguishedName` explicitement demandé serait, lui, filtré au
  passage (voir le dépréfixage manquant, plus haut).
- **3. Espace `ad:` et absence de `LdapSyntax`.** Le `distinguishedName` est
  écrit dans l'espace de noms `ad`, suivi directement de sa valeur :
  l'attribut `LdapSyntax` n'apparaît que dans la boucle des attributs
  `addata:`. Un `LdapSyntax` sur un élément `ad:` (ou pire, un
  `<addata:distinguishedName>`) sort du schéma attendu. Le dépôt garantit
  structurellement ce comportement en passant par `_synthetic`
  (`object_projector.py:48-53`), qui ne sait pas écrire d'attribut XML.

Symétriquement, un `LdapSyntax` **manquant** sur un élément `addata:`, ou
portant un OID au lieu d'un nom de membre d'énumération, fait échouer le la
conversion en énumération côté client et la réponse est rejetée en bloc.

---

## Sérialisation des valeurs par syntaxe LDAP

### Deux décisions indépendantes

Pour chaque attribut, le serveur prend deux décisions **séparées** :

- l'attribut XML `LdapSyntax`, qui porte le nom d'un membre de l'énumération
  `DirectorySyntaxType`, c'est la **syntaxe sémantique** ;
- l'attribut `xsi:type` de chaque `<ad:value>`, qui décrit uniquement la
  **représentation du transport**.

La preuve que ce sont deux axes indépendants tient dans une contrainte forte
du client : le désérialiseur de valeurs du client n'accepte que deux jetons,
`xsd:string` et `xsd:base64Binary`, et lève `UnknownAttributeType` sur tout
autre. Un entier, un booléen ou une date voyagent donc en `xsd:string` ;
seul du binaire voyage en base64. Le dépôt encode cette règle explicitement
dans `XSI_TYPE_BY_OID` (`src/serialization/syntax_constants.py:76-87`).

### L'énumération `DirectorySyntaxType` complète

Telle que définie par le service Microsoft (23 membres, dans l'ordre de
déclaration).

| Membre | Émis par ce projet | Membre | Émis par ce projet |
|---|---|---|---|
| `Boolean` | oui | `NTSecurityDescriptor` | oui |
| `Enumeration` | non | `NumericString` | non |
| `Integer` | oui | `ObjectIdentifier` | oui |
| `LargeInteger` | oui | `OctetString` | oui |
| `AccessPoint` | non | `PrintableString` | non |
| `DNString` | non | `SidString` | oui |
| `ORName` | non | `TeletexString` | non |
| `DNBinary` | non | `UnicodeString` | oui (défaut) |
| `DSDNString` | oui | `UTCTimeString` | non |
| `PresentationAddress` | non | `GeneralizedTimeString` | oui |
| `ReplicaLink` | non | | |
| `CaseString` | non | | |
| `IA5String` | non | | |

Dix membres sur vingt-trois sont produits. Les treize autres n'apparaissent
pas dans `SYNTAX_NAME_BY_OID` ni dans `NAME_OVERRIDES`
(`src/serialization/syntax_constants.py:104-132`) : un attribut de syntaxe
`DNBinary` ou `ReplicaLink` sortira étiqueté `UnicodeString` par défaut.

### Table de correspondance exhaustive

Les identifiants de la colonne « OID interne » sont ceux définis dans
`src/serialization/syntax_constants.py:3-12`. Attention : ce sont des **clés
de répartition internes**, pas nécessairement les OID de syntaxe LDAP
canoniques. En particulier `SYNTAX_DIRECTORY_STRING` vaut `2.5.4.3`, qui est
en réalité l'OID du type d'attribut `cn` et non celui de *Directory String*
(`1.3.6.1.4.1.1466.115.121.1.15`) ; il sert ici de sentinelle de repli.

| Bucket (constante) | OID interne | `LdapSyntax` émis | `xsi:type` |
|---|---|---|---|
| `INTEGER_ATTRIBUTES` | `1.3.6.1.4.1.1466.115.121.1.27` | `Integer` | `xsd:string` |
| `LARGE_INTEGER_ATTRIBUTES` | `1.2.840.113556.1.4.906` | `LargeInteger` | `xsd:string` |
| `BOOLEAN_ATTRIBUTES` | `1.3.6.1.4.1.1466.115.121.1.7` | `Boolean` | `xsd:string` |
| `GENERALIZED_TIME_ATTRIBUTES` | `1.3.6.1.4.1.1466.115.121.1.24` | `GeneralizedTimeString` | `xsd:string` |
| `BINARY_ATTRIBUTES` | `1.3.6.1.4.1.1466.115.121.1.40` | `OctetString` | `xsd:base64Binary` |
| `DN_ATTRIBUTES` | `1.3.6.1.4.1.1466.115.121.1.12` | `DSDNString` | `xsd:string` |
| (non peuplé) | `1.2.840.113556.1.4.907` | `SidString` | `xsd:base64Binary` |
| (non peuplé) | `1.3.6.1.4.1.1466.115.121.1.38` | `ObjectIdentifier` | `xsd:string` |
| repli | `2.5.4.3` | `UnicodeString` | `xsd:string` |

Deux constantes ne sont **jamais** produites par `syntax_for` car aucun
attribut n'y est semé : `SYNTAX_SID` et `SYNTAX_OID_STRING`. Les attributs
concernés obtiennent leur nom de syntaxe uniquement par la table de
surcharges `NAME_OVERRIDES`, tandis que leur **encodage de valeur** suit le
bucket dans lequel ils sont réellement placés. `objectSid` est ainsi dans
`BINARY_ATTRIBUTES` (encodage base64, correct) mais étiqueté `SidString` par
surcharge (correct aussi). Le résultat sur le fil est juste ; le chemin est
indirect.

Signalons également que `SYNTAX_GUID` et `SYNTAX_OCTET_STRING` partagent la
**même valeur littérale** `1.3.6.1.4.1.1466.115.121.1.40`
(`syntax_constants.py:4,12`) : ce sont deux noms du même bucket.

### Table des surcharges `NAME_OVERRIDES`

Source : `src/serialization/syntax_constants.py:119-132`.

| Attribut | Bucket réel | `LdapSyntax` forcé |
|---|---|---|
| `objectSid` | binaire | `SidString` |
| `sIDHistory` | binaire | `SidString` |
| `tokenGroups` | binaire | `SidString` |
| `tokenGroupsGlobalAndUniversal` | binaire | `SidString` |
| `tokenGroupsNoGCAcceptable` | binaire | `SidString` |
| `mS-DS-CreatorSID` | binaire | `SidString` |
| `nTSecurityDescriptor` | binaire | `NTSecurityDescriptor` |
| `msDS-AllowedToActOnBehalfOfOtherIdentity` | binaire | `NTSecurityDescriptor` |
| `objectClass` | repli | `ObjectIdentifier` |
| `supportedControl` | repli | `ObjectIdentifier` |
| `supportedCapabilities` | repli | `ObjectIdentifier` |
| `supportedExtension` | repli | `ObjectIdentifier` |

### L'ordre d'ensemencement compte

`SyntaxRegistry.__init__` (`classes/serialization/syntaxes.py:29-34`) sème
les buckets dans cet ordre : entiers, grands entiers, binaires, temps
généralisés, booléens, DN. Le dictionnaire est indexé en minuscules et **le
dernier semé gagne**. Deux attributs figurent dans deux listes :

- `msds-keyversionnumber` apparaît dans `LARGE_INTEGER_ATTRIBUTES`
  (`syntax_constants.py:54`) **et** dans `DN_ATTRIBUTES` (`:44`).
  `DN_ATTRIBUTES` étant semé en dernier, l'attribut sort étiqueté
  `DSDNString` alors que le schéma AD en fait un entier. Écart non corrigé,
  sans symptôme observé.
- `objectClassCategory` figure dans `BOOLEAN_ATTRIBUTES`
  (`syntax_constants.py:36`) alors que le schéma AD en fait une énumération
  entière ; il sort donc en `TRUE`/`FALSE`. Cet attribut n'est retourné que
  par le handler de schéma.

### Le codec de valeurs

`ValueCodec.encode_to_xsd` (`classes/serialization/value_codec.py:32-47`)
enchaîne :

1. Déballage d'un `ldb.MessageElement` en `bytes` (première valeur) :
  garde-fou contre le `__str__` qui retourne `None` documenté en
  `documentation/06-depannage.md` §4.
2. Valeur `None` → `(xsd:string, "")`.
3. Répartition par OID : booléen, temps généralisé, entier/grand
  entier, binaire, sinon chaîne.

| Chemin | Fonction | Sortie |
|---|---|---|
| Booléen | `encode_boolean`, `src/serialization/value_special.py:8-11` | `TRUE` ou `FALSE`, jamais `true`/`1` |
| Temps généralisé | `encode_generalized_time`, `value_special.py:15-17` | chaîne native `YYYYMMDDHHMMSS.0Z` inchangée |
| Entier | `_encode_integer`, `value_codec.py:50-56` | décimal ASCII ; `0` si les octets ne décodent pas |
| Binaire | `_encode_binary`, `value_codec.py:59-62` | `base64` du binaire brut |
| Chaîne | `_encode_string`, `value_codec.py:65-74` | UTF-8 échappé, **repli base64** |

Deux détails ne sont pas anodins. `encode_boolean` (`value_special.py:10`)
admet les trois jetons `TRUE`, `1` et `YES` en entrée et normalise toujours
la sortie sur `TRUE`/`FALSE`. `_encode_binary` (`value_codec.py:62`) a un
repli non évident : une valeur du bucket binaire qui n'est pas de type
`bytes` repart en `xsd:string`, alors que le `LdapSyntax` annoncera
`OctetString` ou `SidString`, incohérence théorique, jamais observée, LDB
rendant toujours des `bytes`.

Le repli base64 du chemin chaîne demande à être explicité : il se déclenche
sur des octets non décodables en UTF-8, ou sur un texte contenant un
caractère de contrôle interdit par XML 1.0. Le motif `_CTRL`
(`value_codec.py:21`) couvre `\x00-\x08`, `\x0b`, `\x0c` et `\x0e-\x1f`, il
préserve donc délibérément tabulation, `LF` et `CR`. Sans ce garde-fou, un
attribut binaire non déclaré dans `BINARY_ATTRIBUTES` produirait un XML
invalide, rejeté par le client.

### Attributs spéciaux et constructés

| Attribut | Traitement | Encodage sur le fil |
|---|---|---|
| `objectSid` | bucket binaire + surcharge nom | `SidString` / `base64Binary` du SID brut |
| `objectGUID` | bucket binaire | `OctetString` / `base64Binary` des 16 octets |
| `objectReferenceProperty` | synthétique `ad:`, `UUID(bytes_le=…)` | pas de `LdapSyntax` / `xsd:string` canonique |
| `nTSecurityDescriptor` | bucket binaire + surcharge | `NTSecurityDescriptor` / `base64Binary` brut, jamais SDDL |
| `userAccountControl` | `INTEGER_ATTRIBUTES` | `Integer` / `xsd:string` décimal |
| `pwdLastSet` | `LARGE_INTEGER_ATTRIBUTES` | `LargeInteger` / `xsd:string`, intervalles FILETIME |
| `accountExpires` | `LARGE_INTEGER_ATTRIBUTES` | idem ; `0` et `9223372036854775807` = jamais |
| `lastLogonTimestamp` | `LARGE_INTEGER_ATTRIBUTES` | idem |
| `badPasswordTime`, `lockoutTime` | `LARGE_INTEGER_ATTRIBUTES` | idem |
| `whenCreated`, `whenChanged` | `GENERALIZED_TIME_ATTRIBUTES` | `GeneralizedTimeString` / `xsd:string` |
| `canonicalName` | constructé, demandé explicitement à LDB | repli `UnicodeString` / `xsd:string` |
| `tokenGroups` | constructé + bucket binaire + surcharge | `SidString` / `base64Binary`, multivalué |
| `primaryGroupToken` | constructé + `INTEGER_ATTRIBUTES` | `Integer` / `xsd:string` |
| `msDS-User-Account-Control-Computed` | constructé + `INTEGER_ATTRIBUTES` | `Integer` / `xsd:string` |
| `msDS-UserPasswordExpiryTimeComputed` | constructé + `LARGE_INTEGER_ATTRIBUTES` | `LargeInteger` / `xsd:string` |
| `msDS-Behavior-Version` | `INTEGER_ATTRIBUTES` | `Integer` / `xsd:string` |
| `msDS-PortLDAP`, `msDS-PortSSL` | `INTEGER_ATTRIBUTES` + injection RootDSE | `Integer` / `xsd:string` |
| `msDS-PrincipalName` | constructé, aucun bucket | `UnicodeString` / `xsd:string` |
| `unicodePwd` | bucket binaire, jamais lu en pratique | écriture seule, voir §mots de passe |

Les **attributs constructés**
(`classes/serialization/constructed_attrs.py:3-21`) posent un problème
propre : LDB ne les calcule que s'ils sont **nommés explicitement** dans la
liste `attrs` d'une recherche ; le joker `*` ne les couvre pas.
`ConstructedAttrs.expand` (`constructed_attrs.py:34-43`) résout cela en
ajoutant les dix-sept noms à toute liste contenant `*`, et en renvoyant
`["*"] + CONSTRUCTED_ATTRIBUTES` quand la liste demandée est vide. La
fonction est appelée dans `classes/handlers/get.py:226` et
`classes/handlers/enumerate.py:27-28`.

Liste complète : `tokenGroups`, `tokenGroupsGlobalAndUniversal`,
`tokenGroupsNoGCAcceptable`, `canonicalName`, `primaryGroupToken`,
`msDS-PrincipalName`, `msDS-User-Account-Control-Computed`,
`msDS-UserPasswordExpiryTimeComputed`, `structuralObjectClass`,
`subSchemaSubentry`, `allowedAttributes`, `allowedAttributesEffective`,
`allowedChildClasses`, `allowedChildClassesEffective`, `createTimeStamp`,
`modifyTimeStamp`, `parentGUID`.

### Le rendu des éléments d'action personnalisée

Les réponses des actions `ca:` n'emploient **pas** le rendu
`addata:`/`ad:value`. Elles emploient la sérialisation par contrat de
données de WCF, reproduite par `classes/serialization/ca_elements.py` :
éléments à texte simple (`CaElement.text`, `ca_elements.py:14-17`), valeur
nulle explicite `xsi:nil="true"`, et tableaux sérialisés avec l'espace de
noms des tableaux `.NET`
`http://schemas.microsoft.com/2003/10/Serialization/Arrays`
(`ca_elements.py:6,19-26`), chaque item étant un `<sera:string>`. Un tableau
`null` et un tableau vide sont deux choses distinctes sur le fil.

### La découverte dynamique des syntaxes n'est pas branchée

Deux mécanismes de découverte existent dans l'arbre mais ne participent pas
au rendu d'un `Get` ou d'un `Pull` :

- `SyntaxCache` (`classes/serialization/syntax_cache.py`) lit
  `(objectClass=attributeSchema)` et enregistre `lDAPDisplayName →
  attributeSyntax`. Il n'est instancié que par
  `ServiceContext.syntax_cache_for`
  (`classes/server/service_context.py:28-35`), fonction **qu'aucun handler
  n'appelle**. Vérifié par recherche sur l'ensemble du dépôt.
- `SchemaHandler._register_syntax_for` (`classes/handlers/schema.py:57-63`)
  enregistre `lDAPDisplayName → attributeID`, c'est-à-dire l'OID **du type
  d'attribut**, pas celui de sa syntaxe, le contraire de ce que fait
  `SyntaxCache._register_one` (`syntax_cache.py:48-55`), qui lit bien
  `attributeSyntax`. Comme chaque handler instancie son propre
  `SyntaxRegistry` (`classes/handlers/base.py:22`), cet enregistrement reste
  confiné au `SchemaHandler` et ne contamine pas les réponses `Get`. À
  l'intérieur du `SchemaHandler` lui-même, en revanche, il fait sortir
  chaque attribut de schéma étiqueté selon un OID qui n'appartient à aucun
  bucket connu, donc en `UnicodeString` par défaut.

Conséquence pratique : les syntaxes émises proviennent **exclusivement** des
tables statiques de `syntax_constants.py`. Un attribut d'extension de schéma
inconnu de ces tables sortira en `UnicodeString`/`xsd:string`, ou en base64
par le repli de `_encode_string` si sa valeur n'est pas du texte propre.

---

## WS-Enumeration : Enumerate, Pull, Renew, GetStatus, Release

Toute cmdlet employant `-Filter`, `-LDAPFilter` ou `-SearchBase` passe par
WS-Enumeration. Le cycle nominal comporte trois messages ; deux messages
optionnels servent la gestion de durée de vie.

```text
client --> Enumerate  {Filter(LdapQuery), Selection}
       <-- EnumerateResponse {EnumerationContext=UUID, Expires}

client --> Pull       {EnumerationContext, MaxElements}
       <-- PullResponse {Items[...], EnumerationContext | EndOfSequence}
       (répété jusqu'à EndOfSequence)

client --> Release    {EnumerationContext}
       <-- ReleaseResponse  (corps vide)
```

### Enumerate

```xml
<s:Body>
  <wsen:Enumerate>
    <wsen:Expires>PT30M</wsen:Expires>
    <wsen:Filter Dialect="http://schemas.microsoft.com/2008/1/
ActiveDirectory/Dialect/LdapQuery">
      <adlq:LdapQuery>
        <adlq:Filter>(&amp;(objectClass=user)(objectCategory=person))
        </adlq:Filter>
        <adlq:BaseObject>DC=samba,DC=local</adlq:BaseObject>
        <adlq:Scope>Subtree</adlq:Scope>
      </adlq:LdapQuery>
    </wsen:Filter>
    <ad:Selection Dialect="http://schemas.microsoft.com/2008/1/
ActiveDirectory/Dialect/XPath-Level-1">
      <ad:SelectionProperty>addata:sAMAccountName</ad:SelectionProperty>
      <ad:SelectionProperty>addata:userAccountControl</ad:SelectionProperty>
      <ad:SelectionProperty>ad:distinguishedName</ad:SelectionProperty>
    </ad:Selection>
  </wsen:Enumerate>
</s:Body>
```

Le parseur (`classes/parsing/context.py:92-122`) localise l'élément
`wsen:Enumerate` puis cherche en profondeur `adlq:BaseObject`,
`adlq:Filter`, `adlq:Scope` et tous les `ad:SelectionProperty`, en retirant
les préfixes `ad:` et `addata:` de chaque propriété de sélection. Le filtre
subit ensuite un dé-échappement XML explicite (`context.py:181-190`) : `&amp
;` redevient `&`, faute de quoi un filtre `(&(a=1)(b=2))` arriverait à LDB
sous la forme `(&amp ;(a=1)(b=2))`.

Trois traductions et un repli sont appliqués dans `EnumerateHandler.handle`
(`classes/handlers/enumerate.py:19-90`) :

| Élément absent ou vide | Valeur retenue | Ligne |
|---|---|---|
| `adlq:Filter` | `(objectClass=*)` | `enumerate.py:24` |
| `adlq:Scope` | `Subtree` | `enumerate.py:25` |
| `adlq:BaseObject` | `defaultNamingContext` de la RootDSE | `enumerate.py:30-33` |
| `ad:Selection` | `["*"] + attributs constructés` | `enumerate.py:27-28` |

Le repli sur le naming context est indispensable : PowerShell envoie
légitimement un `BaseObject` vide pour signifier « tout le contexte par
défaut », mais LDB refuse une recherche sans base et lève `(32, 'empty base
DN at.../partition.c:821')` (`documentation/06-depannage.md` §5).

La correspondance de portée (`enumerate.py:35-40`) :

| `adlq:Scope` | Constante LDB |
|---|---|
| `Base` | `ldb.SCOPE_BASE` |
| `OneLevel` | `ldb.SCOPE_ONELEVEL` |
| `Subtree` | `ldb.SCOPE_SUBTREE` |
| toute autre valeur | `ldb.SCOPE_SUBTREE` |

`_with_object_class` (`enumerate.py:100-104`) ajoute `objectClass` à la
liste d'attributs si elle n'y figure pas déjà : sans lui, `PullHandler` ne
pourrait pas déterminer le nom du wrapper `<addata:{classe}>` et retomberait
sur `top` pour chaque objet.

**Différence structurante avec le serveur Microsoft.** Ce dépôt exécute
l'intégralité du `samdb.search` **au moment de l'`Enumerate`** et
matérialise la liste complète en mémoire (`enumerate.py:47-79`). Le serveur
Microsoft, lui, ne fait que *préparer* la requête
(`ClassManager.DirectoryAction.PrepareQuery`, le service ADWS Microsoft) et
récupère les pages paresseusement à chaque `Pull` via `NextQueryPage`, la
fin de séquence étant signalée par `Query.NoMoreResults` (`:1154`).
L'approche du dépôt est plus simple mais consomme la mémoire d'un résultat
complet ; un garde-fou tronque à `MAX_RESULTS_PER_CONTEXT` = 50 000
(`classes/enumeration/enumeration_registry.py:12`, troncature à
`enumerate.py:74-78`) avec un avertissement journalisé.

La réponse (`enumerate.py:106-129`) :

```xml
<s:Body>
  <wsen:EnumerateResponse>
    <wsen:Expires>2026-08-07T13:22:41.153204Z</wsen:Expires>
    <wsen:EnumerationContext>4b2f...-a71c</wsen:EnumerationContext>
  </wsen:EnumerateResponse>
</s:Body>
```

Le `wsen:Expires` de la **requête** est ignoré : la TTL est fixée à 3600
secondes en dur, à deux endroits qu'il faut garder cohérents, l'argument
`ttl_seconds=3600` passé au cache (`enumerate.py:67`) et le
`timedelta(hours=1)` qui compose la chaîne renvoyée au client
(`enumerate.py:81`). Le serveur Microsoft honore la valeur demandée, la
compare à `MaxEnumContextExpiration` et lève
`FaultBuilder.GenerateInvalidExpirationTimeFault` si elle dépasse ; le même
contrôle est rejoué sur `Renew` (`:1322`, `:1325`).

### Stockage du contexte et contrainte de « stickiness »

Le contexte est un `dataclass`
(`classes/enumeration/enumeration_context.py`) : identifiant, dates de
création et d'expiration, base, filtre, liste d'attributs, **résultats
matérialisés** et un curseur `result_index`. Le cache est un dictionnaire en
mémoire de processus (`classes/enumeration/enumeration_registry.py`), obtenu
par un singleton paresseux (`src/enumeration/enumeration.py:6-13`).

C'est le point de fragilité architecturale du service. Le serveur est un
`ForkingTCPServer` : **chaque connexion TCP est un processus distinct**, et
le singleton `_INSTANCE` n'est donc partagé par aucun autre fork. Un `Pull`
qui arriverait sur une autre connexion que son `Enumerate` recevrait la
faute `Invalid or expired enumeration context`.

Ce qui sauve le montage, c'est que le client Windows **réutilise la même
connexion `net.tcp`** pour toute la séquence `Enumerate`/`Pull`/`Release` :
la stickiness est une propriété du client, pas une garantie du serveur. Le
serveur Microsoft, lui, associe explicitement chaque contexte à une session
et vérifie la correspondance à l'entrée des quatre opérations concernées,
par `ClassManager.EnumerationRegistry.IsValidEnumContextForSession` :

| Opération | Appel | Cas `SessionMismatch` |
|---|---|---|
| `Pull` | Service ADWS Microsoft | `:1084` |
| `Renew` | `:1299` | `:1301` |
| `GetStatus` | `:1421` | `:1423` |
| `Release` | `:1521` | journalisé en `:1522` |

Ce projet ne fait aucune vérification de session, `session_id` est stocké
(le `message_id` de l'`Enumerate`, `enumerate.py:66`, champ déclaré en
`enumeration_context.py:16`) mais jamais relu ; aucune occurrence en lecture
n'existe dans le dépôt.

Limites du cache, et comparaison avec les valeurs par défaut du service
Microsoft lues dans le tableau `SettingDefault` de la configuration du
service ADWS Microsoft (les bornes minimales associées figurent en
`:602-610`) :

| Paramètre | Ce projet | ADWS Microsoft (défaut) | Ligne C# |
|---|---|---|---|
| Contextes simultanés | 256, éviction du plus ancien | `MaxEnumCtxsTotal` = 100 | `584` |
| Contextes par session | non suivi | `MaxEnumCtxsPerSession` = 5 | `583` |
| Durée de vie d'un contexte | 3600 s, non négociable | `MaxEnumContextExpiration` = 30 min | `580` |
| Résultats mémorisés par contexte | 50 000, troncature | pagination paresseuse | — |
| Éléments par `Pull` sans `MaxElements` | 100 | **1** | `1149` |
| Délai maximal d'un `Pull` | non implémenté | `MaxPullTimeout` = 2 min | `582` |
| Connexions LDAP par utilisateur | non plafonné | `MaxConnectionsPerUser` = 5 | `576` |
| Vérification de session | aucune | `SessionMismatch` | `1084` |

Une contrainte de cohérence supplémentaire est appliquée au démarrage du
service Microsoft : si `MaxEnumCtxsPerSession` dépasse `MaxEnumCtxsTotal`,
le premier est ramené au second et l'événement est journalisé . Le dépôt n'a
pas d'équivalent, faute de notion de session.

### Pull

```xml
<s:Body>
  <wsen:Pull>
    <wsen:EnumerationContext>4b2f...-a71c</wsen:EnumerationContext>
    <wsen:MaxElements>256</wsen:MaxElements>
  </wsen:Pull>
</s:Body>
```

`classes/parsing/context.py:129-142` extrait `EnumerationContext` et
convertit `MaxElements` en entier, avec repli silencieux sur `None` si la
conversion échoue (`context.py:141-142`). `PullHandler`
(`classes/handlers/pull.py:20`) applique alors un défaut de **100**.
Rappelons que le serveur Microsoft applique un défaut de **1** (branche
`else { num = 1u ; }`, le service ADWS Microsoft) : un client qui omettrait
`MaxElements` obtiendrait donc des lots cent fois plus gros ici. Aucune
cmdlet observée n'omet ce champ, `-ResultPageSize` le pilote directement. Là
où le dépôt avale silencieusement une valeur non numérique, Microsoft lève
une `ArgumentException(UnrecognizedMaxElements)` sur débordement
(`:1141-1144`).

`MaxCharacters` et `MaxTime` sont **totalement ignorés** par ce projet : ils
ne sont ni extraits ni contrôlés. Le serveur Microsoft, lui, lève
systématiquement une faute sur `MaxCharacters`
(`GenerateMaxCharsNotSupportedFault`, le service ADWS Microsoft) et borne
`MaxTime` par `MaxPullTimeout`.

Le découpage est un simple curseur (`EnumerationContext.get_next_batch`,
`enumeration_context.py:26-33`) et la fin de séquence est la comparaison
`result_index >= len(cached_results)` (`enumeration_context.py:22-24`).

#### Forme exacte des items

Les items d'un `PullResponse` emploient **exactement** la forme WS-Transfer
: `PullHandler._render_object_xml` (`classes/handlers/pull.py:49-56`)
appelle `serializer.whole_object`, le même point d'entrée que le `Get`
WS-Transfer. Aucun `PartialAttribute`, aucun `BaseObjectSearchResponse`.

```xml
<s:Body>
  <wsen:PullResponse>
    <wsen:Items>
      <addata:user>
        <ad:objectReferenceProperty>
          <ad:value xsi:type="xsd:string">f6aac55f-...</ad:value>
        </ad:objectReferenceProperty>
        <addata:sAMAccountName LdapSyntax="UnicodeString">
          <ad:value xsi:type="xsd:string">demo</ad:value>
        </addata:sAMAccountName>
        <ad:relativeDistinguishedName>
          <ad:value xsi:type="xsd:string">CN=demo</ad:value>
        </ad:relativeDistinguishedName>
        <ad:distinguishedName>
          <ad:value xsi:type="xsd:string">CN=demo,CN=Users,DC=samba,DC=local
          </ad:value>
        </ad:distinguishedName>
      </addata:user>
      <addata:user>...</addata:user>
    </wsen:Items>
    <wsen:EnumerationContext>4b2f...-a71c</wsen:EnumerationContext>
  </wsen:PullResponse>
</s:Body>
```

Trois détails d'enveloppe conditionnent l'acceptation par le client
(`classes/handlers/pull.py:93-114`) :

- l'enveloppe **doit** déclarer `xmlns:xsd` et `xmlns:xsi`, puisque chaque
  `<ad:value>` porte un `xsi:type="xsd:…"` ;
- lot vide et fin de séquence sont deux choses distinctes : un lot vide
  s'écrit `<wsen:Items/>` (`pull.py:83-84`) ;
- la continuation est **exclusive** : soit `<wsen:EndOfSequence/>`, soit
  `<wsen:EnumerationContext>`, jamais les deux (`pull.py:85-91`). Le serveur
  Microsoft produit strictement la même alternative (branche vraie en le
  service ADWS Microsoft, branche fausse en `:1176-1182`) et positionne
  ensuite `message.Headers.RelatesTo = request.Headers.MessageId` (`:1184`),
  l'équivalent du `<a:RelatesTo>` que le dépôt écrit en `pull.py:106`.

### Renew, GetStatus, Release

| Message | Handler | Corps de réponse | Faute si contexte inconnu |
|---|---|---|---|
| `Renew` | `classes/handlers/renew.py` | `Expires` + `EnumerationContext` | `s:Sender`, texte `Invalid or expired…` |
| `GetStatus` | `classes/handlers/get_status.py` | `Expires` seul | idem |
| `Release` | `classes/handlers/release.py` | `<s:Body />` vide | `ADWSException` → faute générique |

`Renew` repousse l'expiration de 3600 s à partir de l'instant courant
(`renew.py:19-21`) sans lire la durée demandée par le client. `GetStatus`
renvoie l'expiration réelle stockée (`get_status.py:24`). Les deux emploient
`FaultBuilder.invalid_enumeration_context`
(`classes/faults/faults.py:43-48`). `Release` supprime l'entrée du
dictionnaire et répond même si le contexte n'existait plus
(`release.py:27-34`, `enumeration_registry.py:51-56`).

### Le filtre LDAP : ce qui est réellement parsé

`FilterParser` (`classes/parsing/filter_parser.py`) n'est **pas** un parseur
sémantique RFC 4515. C'est un normalisateur syntaxique de 59 lignes dont
l'unique fonction est de garantir un équilibrage correct des parenthèses :

- `parse` (`filter_parser.py:10-18`) rejette un filtre dont il reste des
  caractères après l'expression racine, et retourne `(objectClass=*)` sur
  entrée vide ;
- `_read_compound` (`:35-44`) traite `&`, `|` et `!` et **reparenthèse les
  opérandes nus** : la tolérance qu'ADWS observe côté Windows ;
- `_read_simple` (`:47-59`) avale les caractères jusqu'à la parenthèse
  fermante en respectant les échappements `\XX` de RFC 4515.

Le contenu de l'assertion n'est jamais interprété : `attribut`, `:règle:` et
`valeur` traversent le parseur **inchangés**. C'est précisément ce qui rend
les règles de correspondance étendues d'Active Directory utilisables sans
une ligne de code dédiée : elles sont transmises telles quelles à LDB, qui
les implémente nativement.

| OID | Nom | Sémantique | Statut dans ce projet |
|---|---|---|---|
| `1.2.840.113556.1.4.803` | `LDAP_MATCHING_RULE_BIT_AND` | tous les bits du masque | transmis à LDB, testé |
| `1.2.840.113556.1.4.804` | `LDAP_MATCHING_RULE_BIT_OR` | au moins un bit | transmis à LDB, non testé |
| `1.2.840.113556.1.4.1941` | `LDAP_MATCHING_RULE_IN_CHAIN` | appartenance transitive | transmis à LDB, non testé |

La suite de tests du dépôt couvre explicitement la règle `803` combinée à un
`OR` et à une négation (`tools/test/Test-ADWS-Sovereign.ps1:115-116`, filtre
`(|(samAccountName=admin*)(!(userAccountControl:1.2.840.113556.1.4.803:=2)))`),
et le cas figure au statut `Pass` sous le nom `Get-ADUser LDAPFilter (OR +
bitwise NOT)` dans le dernier relevé
(`tools/test/adws-test-results/adws-test-20260608-121931.json`). Les règles
`804` et `1941` ne sont couvertes par aucun test du dépôt ; leur bon
fonctionnement dépend uniquement de LDB. La documentation existante affirme
le support de `804` (`documentation/01-architecture.md:159`) : c'est vrai au
sens où le filtre est transmis intact, mais cette affirmation n'est adossée
à aucune mesure.

En revanche, si le filtre est **syntaxiquement invalide**,
`EnumerateHandler` retombe silencieusement sur le texte brut
(`enumerate.py:92-98`) et laisse LDB échouer, alors que `SearchHandler`
(`classes/handlers/search.py:18-24`) émet une faute typée
`CannotProcessFilter`. Les deux chemins ne se comportent donc pas de la même
manière face à un filtre mal formé.

### Les contrôles LDAP v3 [MS-WSPELD]

Le client peut joindre un bloc `<ad:controls>` contenant des `<ad:control
type="OID" criticality="true|false">` avec un `<ad:controlValue>` en base64.
`ControlsParser` (`classes/parsing/controls_parser.py`) les traduit en
chaînes de contrôle LDB de la forme `nom:criticité[:valeur]`
(`controls_parser.py:62-74`), puis `EnumerateHandler` les passe à
`samdb.search(controls=…)` (`enumerate.py:53`).

| OID | Nom LDB | Usage typique |
|---|---|---|
| `1.2.840.113556.1.4.319` | `paged_results` | `-ResultPageSize` |
| `1.2.840.113556.1.4.473` | `server_sort` | tri serveur |
| `1.2.840.113556.1.4.474` | `sort_resp` | réponse de tri |
| `1.2.840.113556.1.4.529` | `extended_dn` | DN étendu avec GUID/SID |
| `1.2.840.113556.1.4.801` | `sd_flags` | portions du descripteur de sécurité |
| `1.2.840.113556.1.4.805` | `tree_delete` | `Remove-AD* -Recursive` |
| `1.2.840.113556.1.4.417` | `show_deleted` | objets tombstone |
| `1.2.840.113556.1.4.1340` | `show_recycled` | corbeille AD |
| `1.2.840.113556.1.4.1413` | `permissive_modify` | modification idempotente |
| `1.2.840.113556.1.4.1339` | `domain_scope` | pas de référence hors domaine |
| `1.2.840.113556.1.4.1504` | `asq` | *attribute scoped query* |
| `1.2.840.113556.1.4.841` | `dirsync` | synchronisation incrémentale |
| `2.16.840.1.113730.3.4.2` | `manageDSAIT` | manipulation des références |

La table `LDB_CONTROL_BY_OID` compte dix-neuf entrées
(`controls_parser.py:8-28`) mais seulement dix-huit noms LDB distincts : les
OID `1.2.840.113556.1.4.1340` (`:17`) et `1.2.840.113556.1.4.2064` (`:24`)
pointent tous deux vers `show_recycled`. Six entrées n'apparaissent pas dans
le tableau ci-dessus : `crossdom_move_target` (`…1.4.521`),
`show_deactivated_link` (`…1.4.2026`), `managedBy` (`…1.4.2065`),
`search_notification` (`…1.4.1948`), `verify_name` (`…1.4.1338`) et le
doublon `show_recycled`.

Trois faiblesses de ce chemin méritent d'être connues :

- un OID absent de la table est **silencieusement supprimé** (`_translate`
  retourne `None`, `controls_parser.py:63-64`), y compris s'il est marqué
  critique, ce qui contrevient au principe LDAP selon lequel un contrôle
  critique non supporté doit faire échouer l'opération ;
- la valeur du contrôle est décodée en base64 puis **amputée de tous ses
  deux-points** (`decoded.replace(":", "")`, `controls_parser.py:71`), parce
  que le séparateur de la chaîne LDB est justement `:`. Un `controlValue`
  binaire arbitraire (cas normal pour `paged_results` ou `server_sort`, dont
  la valeur est du BER) en ressort mutilé, quand il n'est pas vidé par le
  `errors="ignore"` du décodage UTF-8 (`:70`) ;
- l'ensemble du parsing est enveloppé dans un `except Exception: return
  None` (`classes/parsing/context.py:171-178`) : une erreur de contrôle ne
  fera jamais échouer une requête, elle la fera passer sans contrôle du
  tout.

Enfin, la pagination `paged_results` est traduite mais **la pagination
réelle reste côté handler** : `EnumerateHandler` exécute une recherche
complète unique puis découpe dans `Pull`. Le contrôle est accepté, pas
honoré au sens LDAP.

### WS-Eventing : statut réel

Le dépôt contient les quatre handlers WS-Eventing plus une action de
notification, tous routés (`src/handlers/handler_routing.py:45-50,67-70`) :

| Action | Handler | Comportement effectif |
|---|---|---|
| `…/eventing/Subscribe` | `classes/handlers/subscribe.py` | crée un UUID + expiration, renvoie un `SubscriptionManager` |
| `…/eventing/Unsubscribe` | `classes/handlers/unsubscribe.py` | retire l'entrée, réponse vide, jamais d'échec |
| `…/eventing/Renew` | `classes/handlers/subscription_renew.py` | repousse l'expiration, **invente** une date si l'ID est inconnu |
| `…/eventing/GetStatus` | `classes/handlers/subscription_status.py` | renvoie l'expiration, **invente** `now + 3600 s` si l'ID est inconnu |
| `…/CustomActions/AccountManagement/Notify` | `classes/handlers/notify.py` | renvoie `<ca:Events/>` **toujours vide** |

L'identifiant d'abonnement est extrait du XML brut par expression régulière
(`_IDENTIFIER_PATTERN`, `src/enumeration/subscription_id.py:4-7`) et non par
analyse XML ; le préfixe `uuid:` est retiré s'il est présent (`:25-26`). Les
deux handlers `Renew` et `GetStatus` ne distinguent pas un abonnement expiré
d'un abonnement inexistant : ils répondent une expiration fabriquée
(`subscription_renew.py:20-21`, `subscription_status.py:19-20`) au lieu
d'une faute, ce qui donne au client l'illusion d'un abonnement toujours
vivant.

Le verdict doit être énoncé sans détour : **la comptabilité des abonnements
est implémentée, la notification ne l'est pas**. `SubscriptionCache`
(`classes/enumeration/subscription_cache.py`) ne mémorise qu'un couple
`(uuid, datetime)`, aucun filtre, aucun point de terminaison de livraison,
aucune source d'événement branchée sur LDB. `NotifyHandler`
(`classes/handlers/notify.py:12-16`) retourne une liste d'événements vide
constante ; aucun message `Notify` sortant n'est jamais émis. Le cache
plafonne à `MAX_SUBSCRIPTIONS` = 256 avec éviction du plus ancien
(`subscription_cache.py:9,21-23`) et retient un `DEFAULT_TTL_SECONDS` de
3600 (`:10`). L'adresse du gestionnaire d'abonnement est en outre codée en
dur sur
`net.tcp://localhost:9389/ActiveDirectoryWebServices/Windows/AccountManagement`
(`classes/handlers/subscribe.py:15-17`), donc inexploitable à distance. La
durée demandée est en revanche correctement décodée : `parse_expires`
(`src/enumeration/subscription_id.py:30-55`) interprète une durée ISO 8601
`PnYnMnDTnHnMnS` avec les approximations année = 365 jours et mois = 30
jours (`subscription_id.py:14-15`), et retombe sur 3600 s en cas d'échec.

---

## Opérations spécifiques : mots de passe, appartenances, rôles FSMO, traduction de noms

Ces opérations n'ont pas d'équivalent WS-* : Microsoft les a définies comme
des actions SOAP propriétaires sous l'espace de noms `CustomActions`,
réparties en deux points de terminaison logiques, `AccountManagement` et
`TopologyManagement`. Elles sont routées par le **dernier segment** de l'URI
d'action (`classes/handlers/handler_registry.py:22-23`).

### Mots de passe

Deux actions distinctes, deux implémentations LDB distinctes.

**SetPassword**, réinitialisation administrative, déclenchée par
`Set-ADAccountPassword -Reset`. Corps : `<ca:SetPasswordRequest>` contenant
`<ca:AccountDN>` et `<ca:NewPassword>`
(`classes/handlers/set_password.py:31-37`). L'écriture
(`set_password.py:39-43`) est un `FLAG_MOD_REPLACE` sur `unicodePwd`.

**ChangePassword**, changement self-service avec ancien mot de passe. Corps
: `<ca:ChangePasswordRequest>` contenant `AccountDN`, `OldPassword`,
`NewPassword`. L'écriture (`classes/handlers/change_password.py:45-51`) est
la séquence canonique d'Active Directory : un `FLAG_MOD_DELETE` de
l'ancienne valeur suivi d'un `FLAG_MOD_ADD` de la nouvelle, **dans le même
`ldb.Message`**.

#### L'encodage `unicodePwd`

Dans les trois points d'écriture, `set_password.py:40`,
`change_password.py:46-47` et `LdapAttrBuilder.encode_value`
(`classes/directory/ldap_attr_builder.py:15-16`), la règle est identique et
non négociable :

```python
encoded = ('"' + new_password + '"').encode("utf-16-le")
```

Le mot de passe est **entouré de guillemets doubles ASCII**, puis encodé en
**UTF-16 little-endian**, **sans BOM**. C'est le format défini par [MS-ADTS]
pour l'attribut `unicodePwd`. Les guillemets font partie intégrante de la
valeur transmise ; ils ne sont pas un artefact de citation. Une valeur
encodée en UTF-8, en UTF-16 big-endian, avec BOM ou sans guillemets est
rejetée par le module `password_hash` de Samba avec une erreur de contrainte
peu explicite.

#### La limite connue sur le changement self-service

`ChangePassword` est la seule **opération de service** du dépôt qui échoue
de manière reproductible. Le relevé de test le plus récent
(`tools/test/adws-test-results/adws-test-20260608-121931.json`) totalise 28
cas, 26 `Pass` et 2 `Fail` ; le second échec, `50 parallel Get-ADUser
-Filter * (throttle 10)` (catégorie `Stress`), n'est pas un défaut du
serveur mais une erreur du script de test lui-même, « Le jeu de paramètres
ne peut pas être résolu à l'aide des paramètres nommés spécifiés », levée en
4 ms, donc avant tout échange réseau. Pour le cas `Set-ADAccountPassword
(Change with old)`, le statut est `Fail` avec l'erreur exacte :

```text
(1, 'Failed to obtain remote address for the LDAP client while changing
the password')
```

La cause est structurelle et documentée en
`documentation/01-architecture.md:155` : le module `password_hash` de Samba
exige, sur le chemin du changement avec ancien mot de passe, l'adresse
réseau du client (`remoteAddress`) afin d'alimenter la politique de
verrouillage et l'audit. Cette information n'est pas fournissable depuis une
connexion `SamDB` locale, car un `tsocket_address` ne se construit pas
depuis Python. Le **reset administrateur** (`-Reset`), lui, ne passe pas par
ce chemin et fonctionne, statut `Pass` dans le même relevé.

Les pistes de contournement identifiées, aucune n'étant implémentée : passer
par une connexion `ldapi://` authentifiée, ou déléguer l'identité GSSAPI du
client jusqu'à la couche LDAP.

### Appartenances de groupe

Trois actions de lecture, toutes sous `AccountManagement`, toutes rendues
par `PrincipalSerializer` (`classes/serialization/group_serializer.py`).

| Action | Handler | Stratégie de résolution |
|---|---|---|
| `GetADGroupMember` | `get_ad_group_member.py` | descente : lit `member` du groupe, récursive si demandé |
| `GetADPrincipalGroupMembership` | `get_ad_principal_group_membership.py` | remontée directe : `(&(objectClass=group)(member=DN))` |
| `GetADPrincipalAuthorizationGroup` | `get_ad_principal_authorization_group.py` | remontée transitive du même filtre |

**Descente.** `_walk` (`get_ad_group_member.py:44-60`) lit `member` en
`SCOPE_BASE` et, en mode récursif, se rappelle sur chaque valeur ; un
ensemble `seen` (`:41-42`) coupe les cycles. Chaque DN est ensuite hydraté
par `PrincipalLoader.load_many`
(`classes/directory/principal_loader.py:28-34`), qui exécute une recherche
`SCOPE_BASE` **par membre** : coût linéaire, principale limite de passage à
l'échelle de cette action.

**Remontée.** Les deux autres actions n'emploient **pas** `memberOf` : elles
interrogent l'annuaire par le filtre inverse
`(&(objectClass=group)(member={dn}))` sur tout le naming context
(`get_ad_principal_group_membership.py:47-52`), la variante transitive
(`get_ad_principal_authorization_group.py:49-63`) répétant l'opération sur
chaque groupe trouvé. Ce choix évite de dépendre de la cohérence de
l'attribut lié `memberOf`, au prix d'une recherche sous-arbre par niveau
d'imbrication.

**Ni `tokenGroups`, ni la règle `1.2.840.113556.1.4.1941` ne sont utilisés**
pour ces résolutions, alors que les deux fourniraient une transitivité
calculée par le serveur d'annuaire. `tokenGroups` reste néanmoins déclaré
comme attribut constructé et correctement sérialisé s'il est demandé dans un
`Get`.

Le rendu (`group_serializer.py:5-18`) produit des
`<ActiveDirectoryPrincipal>` ou `<ActiveDirectoryGroup>` portant huit champs
communs, plus `GroupScope` et `GroupType` pour les groupes. Ces deux
derniers sont dérivés du masque `groupType` (`principal_loader.py:55-61`) :

| Bit testé | Valeur | Résultat |
|---|---|---|
| `0x00000004` | positionné | `GroupScope = DomainLocal` |
| `0x00000008` | positionné | `GroupScope = Universal` |
| aucun des deux | — | `GroupScope = Global` |
| `0x80000000` | positionné | `GroupType = Security` |
| `0x80000000` | absent | `GroupType = Distribution` |

Le `SID` renvoyé dans ces structures est en **base64** du SID binaire
(`LdbValue.sid_b64`, `classes/serialization/ldb_value.py:22-26`), et non en
forme textuelle `S-1-5-…`.

**Add-ADGroupMember et Remove-ADGroupMember.** Le dépôt contient un
`GroupHandler` (`classes/handlers/groups.py`) capable d'exécuter un
`FLAG_MOD_ADD`/`FLAG_MOD_DELETE` sur `member` à partir d'un corps
`<ca:GroupModificationRequest>` (`groups.py:27-41`). Deux verrous rendent ce
chemin pratiquement inatteignable :

1. le handler n'est enregistré que sous la clé `Groups`
  (`src/handlers/handler_routing.py:57`). Le repli par suffixe de
  `HandlerRegistry.resolve` (`classes/handlers/handler_registry.py:22-23`)
  découpe l'URI sur le dernier `/` **sans passer en minuscules**,
  contrairement à la correspondance exacte de la ligne `19`, donc seul un
  dernier segment valant littéralement `Groups` fonctionne ;
2. même atteint, `GroupHandler.handle` (`groups.py:19-25`) n'exécute
  la mutation que si la chaîne `add` ou `remove` figure dans l'action passée
  en minuscules ; à défaut, il **délègue à `GetADGroupMemberHandler`**,
  c'est-à-dire qu'il répond une liste de membres.

Les tests `Add-ADGroupMember` (catégorie `GroupModify`) et
`Remove-ADGroupMember + cleanup` (catégorie `Cleanup`) du dépôt sont
pourtant au statut `Pass` dans le dernier relevé. La lecture du code rend
donc très probable qu'ils empruntent en réalité le chemin **WS-Transfer
Put** avec un `<da:Change Operation="add">` sur `member`, que
`ModifyHandler` traite correctement. Cette hypothèse n'a pas pu être
confirmée par une trace réseau au moment de la rédaction, et le tableau
final signale les deux voies.

### Rôles FSMO

`Move-ADDirectoryServerOperationMasterRole` émet l'action
`…/TopologyManagement/MoveADOperationMasterRole`. Le corps porte
`<ca:OperationMasterRole>` et `<ca:Seize>`
(`classes/handlers/move_operation_master_role.py:31-41`).

La correspondance rôle → objet porteur est une table de gabarits
(`src/directory/fsmo_roles.py:3-9`), le transfert consistant à réécrire
l'attribut `fSMORoleOwner` (`fsmo_roles.py:11`) de l'objet cible avec le DN
des `NTDS Settings` locaux.

| Rôle | Objet porteur de `fSMORoleOwner` |
|---|---|
| `PDCEmulator` | `{domain_dn}` |
| `RIDMaster` | `CN=RID Manager$,CN=System,{domain_dn}` |
| `InfrastructureMaster` | `CN=Infrastructure,{domain_dn}` |
| `SchemaMaster` | `{schema_dn}` |
| `DomainNamingMaster` | `CN=Partitions,{config_dn}` |

Un rôle absent de cette table provoque une `ValueError` traduite en faute
`MoveADOperationMasterRoleFault`. Le DN du nouveau propriétaire est
découvert par `(&(objectClass=nTDSDSA)(options=*))` dans le contexte de
configuration (`move_operation_master_role.py:53-61`).

> **Limite explicite.** Le drapeau `Seize` est extrait, journalisé, puis
> **délibérément ignoré** (`move_operation_master_role.py:22-23`, la ligne
> `_ = seize`). Transfert gracieux et saisie autoritaire produisent donc la
> même écriture ; le protocole de transfert propre à FSMO
> (`becomeDomainMaster` et consorts) n'est pas mis en œuvre. Aucun test du
> dépôt ne couvre cette action.

### Traduction de noms

`TranslateName` (`classes/handlers/translate_name.py`) implémente le service
rendu par `DsCrackNames` côté Windows. La requête porte une liste
`<ca:Names>`, un `<ca:FormatOffered>` et un `<ca:FormatDesired>`.

La résolution se fait en deux temps
(`classes/serialization/name_formats.py:22-34`) : `filter_for_offered`
(`src/serialization/name_filters.py:4-23`) construit le filtre LDAP à partir
du format d'entrée, puis un rendu (`src/serialization/name_renderers.py`)
produit le format de sortie.

| Format | Filtre de recherche (entrée) | Rendu (sortie) |
|---|---|---|
| DN / `1779` | `(distinguishedName=…)` | `str(entry.dn)` |
| NT4 / `NTAccount` | `(sAMAccountName=…)` après découpe sur `\` | `NETBIOS\sAMAccountName` |
| UPN | `(userPrincipalName=…)` | `userPrincipalName` |
| SPN / service | `(servicePrincipalName=…)` | `servicePrincipalName` |
| GUID / uniqueId | `(objectGUID=…)` accolades retirées | `{guid}` avec accolades |
| SID | `(objectSid=…)` | pas de rendu dédié → DN |
| Canonical | pas de filtre dédié | `domaine/OU/CN` |
| DisplayName | pas de filtre dédié | `displayName`, repli `cn` |
| inconnu | disjonction `sAMAccountName`/`UPN`/`DN`/`cn` | DN |

Le nom NetBIOS nécessaire au format NT4 est lu dans `CN=Partitions` du
contexte de configuration via `(nCName={naming_context})`
(`name_renderers.py:38-51`). Le nom canonique est reconstruit par
manipulation de chaîne : les composants `DC=` forment le domaine par
jointure sur `.`, les autres composants sont inversés et joints par `/`
(`name_renderers.py:21-28`).

Le statut est renvoyé sous forme de **code numérique**
(`translate_name.py:10`) : `0` pour `Found`, `2` pour `NotFound`, `4` pour
`NoMapping`, `2` par défaut. Ce sont les codes `DS_NAME_ERROR` d'Active
Directory.

### Topologie : Domain, DomainController, Forest, Version, OptionalFeature

| Action | Handler | Sources LDB |
|---|---|---|
| `GetADDomain` | `get_ad_domain.py` + `DomainLoader` | objet `domainDNS`, `CN=Partitions` pour le NetBIOS |
| `GetADDomainController` | `get_ad_domain_controller.py` | `(objectClass=nTDSDSA)` dans le contexte de configuration |
| `GetADForest` | `get_ad_forest.py` | RootDSE seule |
| `GetVersion` | `get_version.py` | aucune, constantes `1.0.0` / `1.1` |
| `ChangeOptionalFeature` | `change_optional_feature.py` | `msDS-OptionalFeatureGUID`, écrit `msDS-EnabledFeature` |

`ChangeOptionalFeatureHandler` résout la fonctionnalité par le filtre
`(&(objectClass=msDS-OptionalFeature)(msDS-OptionalFeatureGUID={feature_id}))`
dans le contexte de configuration (`change_optional_feature.py:44-55`), puis
ajoute ou retire le DN obtenu de l'attribut `msDS-EnabledFeature` de l'objet
cible selon le drapeau `<ca:Enable>` (`:57-63`). Un `FeatureId` inconnu lève
un `RuntimeError` traduit en `ChangeOptionalFeatureFault`. Aucun test du
dépôt ne couvre cette action.

`DomainSerializer` (`classes/serialization/domain_serializer.py:5-37`)
projette trente et un champs. Les conteneurs bien connus ne sont **pas lus
dans l'annuaire** : ils sont fabriqués par concaténation à partir du naming
context (`domain_serializer.py:57-68`), qu'ils existent ou non. Les rôles
FSMO exposés (`InfrastructureMaster`, `PDCEmulator`, `RIDMaster`) pointent
tous vers la même valeur `dns_host`, le DC local, sans consulter les
`fSMORoleOwner` réels.

Même approche pour `GetADDomainController`
(`classes/handlers/get_ad_domain_controller.py:41-56`) : ports constants
(`389`, `636`), `IsGlobalCatalog` à `true` en dur, `IsReadOnly` à `false`,
`OperationMasterRole`, `Partitions` et les informations de système
d'exploitation à `nil`. Le site est déduit du DN des `NTDS Settings`, avec
repli sur `Default-First-Site-Name` (`get_ad_domain_controller.py:58-63`).
`GetADForest` (`classes/handlers/get_ad_forest.py:42-52`) n'expose qu'un
domaine et un catalogue global, tout le reste à `nil`, cohérent avec la
limite d'architecture annoncée : un seul domaine, aucune approbation.

### Traduction des erreurs en fautes SOAP

Toute exception doit ressortir en faute SOAP portant un `<a:RelatesTo>` égal
au `MessageID` de la requête. `ADWSDispatcher.dispatch`
(`classes/handlers/dispatcher.py:20-35`) capture `ADWSException` **et**
`Exception`, et `_fault` (`dispatcher.py:52-55`) récupère le `message_id` du
contexte s'il a pu être construit, chaîne vide sinon. Sans ce `RelatesTo`,
le client considère la réponse comme non sollicitée et l'ignore : la cmdlet
reste bloquée jusqu'au délai d'expiration (`documentation/06-depannage.md`
§6).

Trois familles de fautes coexistent :

| Générateur | Fichier | `<s:Code><s:Value>` | Forme du `Detail` |
|---|---|---|---|
| `directory_error` | `classes/faults/faults.py:13-22` | `s:Receiver` | `<da:Fault>` + `ShortError`/`LongError` |
| `access_denied` | `faults.py:24-26` | `s:Sender` | aucun |
| `custom_action_fault` | `faults.py:28-41` | `s:Receiver` | `<{Nom}Fault>` à quatre champs |
| `invalid_enumeration_context` | `faults.py:43-48` | `s:Sender` | aucun |
| `TypedFaults.*` | `classes/faults/typed_faults.py` | `s:Sender` sauf `directory` | `Code` + `Message` |

Le `Detail` de `custom_action_fault` porte exactement quatre éléments dans
l'espace `CustomActions` (`faults.py:30-37`) : `<ArgumentError
xsi:nil="true">`, `<DirectoryError xsi:nil="true">`, `<Error>` et
`<ShortError>`, les deux derniers recevant le même texte. C'est aussi le
seul générateur à positionner à la fois un `<s:Subcode>` (`ca:{Nom}Fault`,
`faults.py:40`) et une action de faute spécifique
(`http://schemas.microsoft.com/2008/1/ActiveDirectory/Data/fault`,
`src/soap/namespaces.py:13`) là où tous les autres retombent sur l'action
générique `http://www.w3.org/2005/08/addressing/soap/fault`
(`classes/soap/soap_envelope.py:18`). C'est ce que le module PowerShell
attend pour les actions personnalisées.

`TypedFaults` (`classes/faults/typed_faults.py:14-64`) offre cinq familles
prêtes à l'emploi, adossées aux constantes de
`src/faults/fault_codes.py:6-24` (`CannotProcessFilter`, `EncodingLimit`,
`FragmentDialectNotSupported`, `InvalidEnumerationContext`,
`InvalidExpirationTime`, `TimedOut`…). **Aucun handler ne les appelle**,
recherche exhaustive : zéro site d'appel pour `typed_faults.` comme pour
`TypedFaults.`, alors que `BaseHandler` les expose (`base.py:28`). C'est une
réserve de conformité inutilisée, et l'essentiel des écarts listés en fin de
chapitre tient à cette non-levée.

---

## Correspondance cmdlets PowerShell -> échanges réseau

Le tableau suivant relie chaque cmdlet du module `ActiveDirectory` à la
suite d'actions SOAP qu'elle produit et au handler qui la sert. Les actions
WS-* sont abrégées : `WST` =
`http://schemas.xmlsoap.org/ws/2004/09/transfer`, `WSEN` =
`http://schemas.xmlsoap.org/ws/2004/09/enumeration`, `CA` =
`http://schemas.microsoft.com/2008/1/ActiveDirectory/CustomActions`.

> **Portée de la vérification.** Les URI des actions `WST` et `WSEN` sont
> celles de la table de routage `ACTION_HANDLER_KEYS`
> (`src/handlers/handler_routing.py:35-51`), donc reconnues en **requête**.
> Celles des actions `CA` sont reconstruites à partir des constantes
> `REPLY_ACTION` de chaque handler, c'est-à-dire validées en **réponse** ;
> côté requête, seul leur dernier segment est effectivement utilisé pour le
> routage (`classes/handlers/handler_registry.py:22-23`). Les assemblies
> clientes qui construisent ces URI ne figurent pas dans le dump de
> référence disponible.

| Cmdlet | Suite d'actions SOAP | Handler(s) | Rendu |
|---|---|---|---|
| `Get-ADRootDSE` | `WST/Get` (objRef = `11111111-…`) | `GetHandler._get_root_dse` | `addata:top` ou `PartialAttribute` |
| `Get-ADUser -Identity` | `WST/Get` | `GetHandler._get_object` | WS-T ou IMDA selon en-tête |
| `Get-ADComputer -Identity` | `WST/Get` | `GetHandler._get_object` | idem |
| `Get-ADGroup -Identity` | `WST/Get` | `GetHandler._get_object` | idem |
| `Get-ADObject -Identity` | `WST/Get` | `GetHandler._get_object` | idem |
| `Get-ADUser -Filter` | `WSEN/Enumerate` → `Pull`* → `Release` | `EnumerateHandler`, `PullHandler`, `ReleaseHandler` | items en forme WS-T |
| `Get-ADComputer -Filter` | idem | idem | idem |
| `Get-ADGroup -Filter` | idem | idem | idem |
| `Get-ADObject -Filter` | idem | idem | idem |
| `Get-ADObject -ResultPageSize n` | `Enumerate` + `Pull{MaxElements=n}`* | idem | idem |
| `Get-ADDomain` | `CA/TopologyManagement/GetADDomain` | `GetADDomainHandler` | `ca:` contrat de données |
| `Get-ADDomainController` | `CA/TopologyManagement/GetADDomainController` | `GetADDomainControllerHandler` | `ca:` contrat de données |
| `Get-ADForest` | `CA/TopologyManagement/GetADForest` | `GetADForestHandler` | `ca:` contrat de données |
| `Get-ADGroupMember` | `CA/AccountManagement/GetADGroupMember` | `GetADGroupMemberHandler` | `ActiveDirectoryPrincipal` |
| `Get-ADGroupMember -Recursive` | idem, `<ca:Recursive>true` | idem, `_walk` récursif | idem |
| `Get-ADPrincipalGroupMembership` | `CA/AccountManagement/GetADPrincipalGroupMembership` | `GetADPrincipalGroupMembershipHandler` | `ActiveDirectoryGroup` |
| `Get-ADPrincipalAuthorizationGroup` | `CA/AccountManagement/GetADPrincipalAuthorizationGroup` | `GetADPrincipalAuthorizationGroupHandler` | `ActiveDirectoryGroup` |
| `New-ADUser` / `New-ADGroup` | `WST/Create` (`da:AddRequest`) | `CRUDHandler` → `CreateHandler` | EPR `wst:ResourceCreated` |
| `New-ADOrganizationalUnit` | `WST/Create` | idem | idem |
| `New-ADComputer` | `WST/Create` | idem | idem |
| `Set-ADUser` / `Set-ADGroup` | `WST/Put` (`da:ModifyRequest`) | `TransferHandler` → `ModifyHandler` | `PutResponse` vide |
| `Set-ADObject`, `Set-ADComputer` | `WST/Put` | idem | idem |
| `Enable-ADAccount` / `Disable-ADAccount` | `WST/Put` sur `userAccountControl` | idem | idem |
| `Rename-ADObject` | `WST/Put` avec `relativeDistinguishedName` | `ModifyHandler._apply_rename` | `PutResponse` vide |
| `Move-ADObject` | `WST/Put` avec `container-hierarchy-parent` | idem | idem |
| `Remove-ADUser` / `Remove-ADGroup` | `WST/Delete` | `TransferHandler` → `DeleteHandler` | `DeleteResponse` vide |
| `Remove-ADObject -Recursive` | `WST/Delete` + contrôle `…1.4.805` | idem, `tree_delete:1` | idem |
| `Add-ADGroupMember` | `WST/Put` `Operation="add"` sur `member` | `ModifyHandler` (voir réserve) | `PutResponse` vide |
| `Remove-ADGroupMember` | `WST/Put` `Operation="delete"` sur `member` | `ModifyHandler` (voir réserve) | `PutResponse` vide |
| `Set-ADAccountPassword -Reset` | `CA/AccountManagement/SetPassword` | `SetPasswordHandler` | `<SetPasswordResponse/>` sans contenu |
| `Set-ADAccountPassword` (ancien+nouveau) | `CA/AccountManagement/ChangePassword` | `ChangePasswordHandler` | **échoue**, voir limite |
| `Move-ADDirectoryServerOperationMasterRole` | `CA/TopologyManagement/MoveADOperationMasterRole` | `MoveOperationMasterRoleHandler` | corps vide, `Seize` ignoré |
| `Enable-ADOptionalFeature` | `CA/TopologyManagement/ChangeOptionalFeature` | `ChangeOptionalFeatureHandler` | corps vide |

`*` : le message `Pull` est répété jusqu'à réception de
`<wsen:EndOfSequence/>`.

Deux chemins secondaires complètent la carte :

- une action dont le dernier segment vaut `Groups` atteint `GroupHandler`
  (`classes/handlers/groups.py`), qui accepte un
  `<ca:GroupModificationRequest>` et répond `<ca:AddedMember>` ou
  `<ca:RemovedMember>` sous l'action
  `…/CustomActions/AccountManagement/{AddedMember|RemovedMember}Response`
  (`groups.py:36-38`) ;
- une action dont le dernier segment vaut `Search` atteint `SearchHandler`
  (`classes/handlers/search.py`), qui normalise le filtre puis délègue
  intégralement à `EnumerateHandler`, il ne produit donc pas de réponse
  propre : le client reçoit un `EnumerateResponse` ;
- une action dont le dernier segment vaut `Schema` atteint `SchemaHandler`,
  qui cherche `(|(objectClass=attributeSchema)(objectClass=classSchema))`
  (`schema.py:48-55`) en `SCOPE_ONELEVEL` sous le contexte de schéma, ou en
  `SCOPE_BASE` si un `objectReferenceProperty` est fourni, et répond un
  `<addata:SchemaResponse>` contenant un `<addata:schemaObject
  DistinguishedName="…">` par objet (`schema.py:65-76`), sous l'action
  `http://schemas.microsoft.com/2008/1/ActiveDirectory/SchemaResponse`.
  Cette forme est **propriétaire à ce dépôt** : ni [MS-ADDM] ni le code de
  référence de référence n'en décrivent l'équivalent. Les résultats sont
  mémorisés par `SchemaCache` sous la clé `{schema_dn}::{objectReference}`
  (`schema.py:24-29`).

### Synthèse des écarts connus

| Domaine | Comportement attendu (spec / Windows) | Ce projet |
|---|---|---|
| Discriminant IMDA | en-tête seul | en-tête **ou** corps |
| En-tête `<ad:instance>` | obligatoire, validé | jamais lu |
| `Dialect` sur un `Get` typé | obligatoire puis validé | ignoré, aucune faute |
| Limite de 100 `AttributeType` | faute `EncodingLimit` | non implémentée |
| Récupération par plages ` ;range=` | `rangeLow`/`rangeHigh` émis | non reconnue |
| `wsen:Expires` demandé | honoré et borné | ignoré, 3600 s fixes |
| `Pull` sans `MaxElements` | 1 élément | 100 éléments |
| `MaxElements` non numérique | `UnrecognizedMaxElements` | replié sur le défaut |
| `MaxCharacters` | faute systématique | ignoré |
| `MaxTime` | borné par `MaxPullTimeout` | ignoré |
| Contexte lié à la session | `SessionMismatch` vérifié | non vérifié |
| Quota de contextes par session | 5 par session, 100 au total | 256 au total, aucun par session |
| Pagination LDAP | pages LDAP successives | recherche complète puis découpe |
| Contrôle critique non supporté | échec de l'opération | supprimé silencieusement |
| `controlValue` binaire | transmis intact | deux-points retirés, UTF-8 forcé |
| `xsi:type` inconnu en écriture | `UnknownAttributeType` | accepté comme texte |
| `objectReferenceProperty` en GUID | résolu en DN | non résolu (sauf RootDSE) |
| `containerHierarchyParent` | émis si parent connu | jamais émis |
| `nTSecurityDescriptor` en écriture | SDDL accepté | non câblé, lecture base64 seule |
| WS-Eventing | notifications livrées | abonnements comptés, aucun événement |
| `Seize` FSMO | saisie autoritaire | ignoré, transfert simple |
| Rôles FSMO exposés par `GetADDomain` | `fSMORoleOwner` réels | tous pointés sur le DC local |
| Découverte des syntaxes | schéma AD interrogé | tables statiques uniquement |
| Fautes typées WS-* | levées selon le cas | `TypedFaults` jamais appelé |
| Changement self-service de mot de passe | supporté | **échoue** (`remoteAddress` Samba) |

# Partie VIII. Traces de bout en bout et diagnostic

## Méthode et outillage de capture

Ce chapitre met en mouvement la mécanique décrite précédemment : quatre
scénarios complets, de l'octet sur la socket à l'objet affiché dans la
console PowerShell, puis une grille de diagnostic. Principe directeur : **on
ne diagnostique pas ADWS depuis le réseau**. Le trafic est scellé dès la fin
du préambule ; l'observation utile se fait aux deux extrémités de la couche
de chiffrement (juste avant `wrap`, juste après `unwrap`) et dans le journal
applicatif.

> **Convention typographique.** Dans les blocs XML, une barre oblique
> inverse en fin de ligne (`\`) marque une coupure de mise en page imposée
> par la largeur de la page : la valeur réelle est la concaténation des deux
> fragments, sans espace ni saut de ligne.

### Ce que la couche transport laisse voir, et à partir de quand

Trois régimes se succèdent sur la même connexion TCP 9389.

| Régime | Contenu sur le fil | Lisible en pcap |
|---|---|---|
| Préambule NMF | records `0x00`–`0x03`, `0x09` | Oui, intégralement |
| Négociation SPNEGO | tokens GSS-API bruts (RFC 4178) | Oui, mais binaire ASN.1 |
| Messages applicatifs | WCF binaire scellé Kerberos | Non, ciphertext |

La bascule est nette : `ProtocolHandler.handle_security` remplace le
`SocketStream` par un `GENSECStream` (`classes/server/protocol.py:96`) ;
toute écriture passe dès lors par `wrap` (`src/nettcp/stream/gssapi.py:150`)
et toute lecture par `unwrap` (`:160`). Le contexte est établi par
`samba.gensec`, mécanisme `spnego` (`:118`), avec les identifiants du compte
machine (`:113-116`) : la clé de session dérive du keytab Samba et
n'apparaît ni dans le dépôt ni dans la capture.

> Conséquence pratique : un `.pcap` d'un incident ADWS ne sert **qu'à**
> valider le préambule, l'échec Kerberos et le fait que des octets
> circulent. Dès que la phase 3 démarre, il ne dit plus rien du contenu
> applicatif.

### tcpdump : ce qu'on obtient réellement

```bash
sudo tcpdump -i any -s 0 -w /tmp/adws.pcap 'tcp port 9389'
```

Sur les premiers octets d'une connexion saine, on retrouve exactement les
records définis dans `src/nettcp/nmf.py`. Les valeurs ci-dessous sont
**produites par le code du dépôt** (`Record.to_bytes`), pas reconstituées de
mémoire.

| Record | Classe (`src/nettcp/nmf.py`) | Code | Octets émis |
|---|---|---|---|
| Version 1.0 | `VersionRecord:298` | `0x00` | `00 01 00` |
| Mode duplex | `ModeRecord:306` | `0x01` | `01 02` |
| Via (URL) | `ViaRecord:313` | `0x02` | `02 <varint> <utf8>` |
| Encoding | `KnownEncodingRecord:321` | `0x03` | `03 08` |
| UpgradeRequest | `UpgradeRequestRecord:328` | `0x09` | `09 15 "application/negotiate"` |
| UpgradeResponse | `UpgradeResponseRecord:336` | `0x0A` | `0a` |
| PreambleAck | `PreambleAckRecord:344` | `0x0B` | `0b` |
| PreambleEnd | `PreambleEndRecord:340` | `0x0C` | `0c` |
| Message | `SizedEnvelopedMessageRecord:348` | `0x06` | `06 <varint> <payload>` |
| End | `EndRecord:375` | `0x07` | `07` |
| Fault | `FaultRecord:379` | `0x08` | `08 <varint> <utf8>` |

> **Correction par rapport à `documentation/03-protocole.md:36-39`.** Ce
> tableau attribue `0x02` à `ModeRecord`, `0x03` à `ViaRecord`, `0x04` à
> `KnownEncodingRecord`, donne `BINARY_WITH_DICT = 3` et fait commencer le
> `VersionRecord` par `0x00 0x01 0x00 0x01`. Le code contredit chacun de ces
> points : `Mode = 0x01`, `Via = 0x02`, `KnownEncoding = 0x03`
> (`src/nettcp/nmf.py:306`, `:313`, `:321`), l'encodage négocié est
> `KnownEncoding.BINARY_DICT = 8` (`:184`), et le `VersionRecord` tient en
> trois octets `00 01 00` (`:298-303`). La constante `BINARY_WITH_DICT`
> n'existe pas ; la valeur `3` désigne en réalité `UTF8` (`:179`). C'est
> bien la valeur `8`, et non `7`, qui explique le préfixe de dictionnaire de
> session en tête de chaque payload (voir plus bas).

Le `ViaRecord` de l'URL
`net.tcp://dc1.samdom.example.com:9389/ActiveDirectoryWebServices/Windows/Resource`
(81 caractères) commence donc par `02 51 6e 65 74 …`, où `0x51` = 81 est la
longueur en varint MS-NMF. L'en-tête d'un message applicatif dont le payload
fait 6833 octets, taille réellement observée pour une réponse RootDSE dans
`adws.log` :

```text
06 b1 35        SizedEnvelopedMessageRecord, Size = 6833
06 e6 03        SizedEnvelopedMessageRecord, Size = 486  (requête RootDSE)
```

Entre les deux, la sous-couche NegotiateStream ([MS-NNS] côté Windows)
ajoute son propre cadrage, lui aussi vérifiable dans le code :

| Phase | En-tête | Octets |
|---|---|---|
| Handshake en cours | `HandshakeInProgress` `0x16` | `16 01 00 <BE uint16>` |
| Handshake terminé | `HandshakeDone` `0x14` | `14 01 00 <BE uint16>` |
| Handshake en erreur | `HandshakeError` `0x15` | `15 01 00 <BE uint16>` |
| Après handshake | longueur seule | `<LE uint32>` |

Références : `src/nettcp/stream/negotiate.py:14-17` pour les types, `:50-62`
pour l'écriture (taille de trame plafonnée à `0xFC30`), `:64-80` pour la
lecture. Noter l'asymétrie : la taille du handshake est **big-endian** sur 2
octets, celle des trames post-handshake **little-endian** sur 4 octets.

Contrainte de dimensionnement à connaître, car elle produit des pannes
difficiles : le clair soumis à `wrap` est découpé en blocs de
`_PLAINTEXT_CHUNK = 0xF000` octets (`src/nettcp/stream/gssapi.py:17`), marge
volontaire sous le plafond de trame `0xFC30`, parce que le lecteur suppose
**une trame = un token GSS** (`:154-166`). Un token débordant sur deux
trames ne serait jamais désencapsulé.

### Le proxy de debug du dépôt : ce qu'il fait vraiment

`tools/work/proxy.py` est présenté par la documentation existante comme
l'outil qui donne le XML en clair, via une constante `RECORD_LOG`. **Cette
constante n'existe pas.** Une recherche sur l'ensemble du dépôt ne la trouve
que dans trois fichiers de documentation
(`documentation/03-protocole.md:264`, `documentation/06-depannage.md:402`,
`.claude/skills/decode-wcf/SKILL.md:38`), jamais dans du code. Voici l'état
réel du fichier.

- Le journal de trace se règle par l'option `-t/--trace_file` de la ligne de
  commande (`tools/work/proxy.py:168`), pas par une constante. Le format
  écrit est `timestamp<TAB>ip:port<TAB>sens<TAB>hex`
  (`tools/work/proxy.py:86-92`), où `sens` vaut `c>s` ou `s>c`.
- L'outil écoute par défaut sur `localhost:8090` (`tools/work/proxy.py:165`)
  et prend `TARGET_HOST` et `TARGET_PORT` en arguments positionnels
  (`:172-173`). Il force par ailleurs le logger racine en `DEBUG` dès
  l'import (`:34`).
- **Il ne relaie pas.** Après avoir ouvert une connexion vers la cible
  (`tools/work/proxy.py:97`), la ligne qui réécrirait les records du client
  vers le serveur est commentée (`tools/work/proxy.py:123`). Sur réception
  de l'`UpgradeRequestRecord`, le proxy répond lui-même
  l'`UpgradeResponseRecord` puis exécute **sa propre** négociation GSSAPI
  côté serveur (`tools/work/proxy.py:136-148`) : le client s'authentifie
  donc contre le proxy, pas contre le DC.
- Les imports du module sont relatifs à son emplacement d'origine
  `src/nettcp/` : `from.stream.socket import SocketStream` et `from.nmf
  import...` (`tools/work/proxy.py:18-20`). Depuis `tools/work/`, qui ne
  contient ni `stream/`, ni `nmf.py`, ni `__init__.py`, l'import échoue.

**Le proxy n'est donc pas, en l'état, un outil de capture utilisable.** Ce
n'est pas un défaut bloquant du service, c'est un vestige vendoré hors du
chemin d'exécution, mais toute procédure de dépannage qui s'appuie dessus
est à réécrire.

### Décoder un payload WCF hors ligne

C'est ici que la documentation existante induit le plus sûrement en erreur.
La recette publiée, `dump_records(data)` sur des octets, **n'est pas un
décodeur**. `dump_records` fait exactement l'inverse : il prend un *arbre de
records* et rend des octets (`src/wcf/records/__init__.py:90-124`). C'est la
fonction employée par le dispatcher pour **encoder** la réponse
(`classes/handlers/dispatcher.py:47-48`).

Appelée sur des octets, elle itère sur des `int` et appelle `int.to_bytes`,
disponible avec arguments par défaut depuis Python 3.11, donc **retourne
l'entrée inchangée**. Aucune erreur, aucun XML : un faux positif silencieux.

Le décodage réel se fait comme dans
`SizedEnvelopedMessageRecord.payload_to_xml` (`src/nettcp/nmf.py:363-373`) :
lire d'abord le dictionnaire de session, puis parser l'arbre, puis
l'imprimer.

```python
from io import BytesIO, StringIO
from src.wcf.records import Record, print_records
from src.nettcp.protocol2xml import build_dictionary

payload = open("/tmp/payload.bin", "rb").read()
fp = BytesIO(payload)
build_dictionary(fp, ("capture", "c>s"))   # consomme le préfixe MS-NBFSE
out = StringIO()
print_records(Record.parse(fp), fp=out)
print(out.getvalue())
```

Ce préfixe est le point le plus souvent manqué. L'encodage négocié étant
`BINARY_DICT` (valeur 8), chaque payload commence par un `MultiByteInt31`
donnant la taille, en octets, de la table de chaînes de **session**
([MS-NBFSE]), suivie de ce nombre d'octets de chaînes UTF-8
longueur-préfixées (`src/nettcp/protocol2xml.py:30-48`). Les index de
session sont **impairs** (`idx` part à 1 et progresse de 2,
`src/nettcp/protocol2xml.py:28` et `:41`) tandis que le dictionnaire
statique [MS-NBFS] occupe les index **pairs**, de `0x000` à `0x3CC` (972 en
décimal), soit 487 entrées dans `src/wcf/dictionary.py`.

> **Deuxième dérive, `documentation/03-protocole.md:96`.** Ce document
> affirme que « le dictionnaire dynamique négocié par session (MS-NBFSE)
> n'est pas implémenté ». À nuancer fortement : le serveur ne *produit*
> effectivement jamais de table de session, mais il en *consomme* une à
> chaque message entrant, et `build_dictionary` fusionne ces index impairs
> dans le dictionnaire global avant le parsing
> (`src/nettcp/protocol2xml.py:42-44`). Le mécanisme est bien implémenté
> côté lecture, c'est même la source de l'incident `UnicodeDecodeError`
> analysé au scénario 4.

Effet de bord : `dictionary` est un dictionnaire de **module** vidé puis
reconstruit à chaque appel, et `idx` est une globale protégée par un
`assert` (`src/nettcp/protocol2xml.py:31`, `:39`, `:42-44`). Le modèle
`ForkingTCPServer` l'absout, un process par connexion, mais tout portage
fileté casserait ici en premier.

Le serveur, lui, n'alimente jamais de dictionnaire de session :
`_encode_response` préfixe la réponse d'un octet `\x00`
(`classes/handlers/dispatcher.py:49`), c'est-à-dire « table de session vide
». D'où la règle de dépannage : sur une trame **sortante**, retirer le
premier octet ou laisser `build_dictionary` le consommer ; les deux
reviennent au même.

Exemple entièrement vérifié, l'enveloppe `Get` minimale ci-dessous a été
réellement encodée par le dépôt (`XMLParser.parse` puis `dump_records`), et
les 124 octets produits sont reproduits tels quels :

```text
56 02                  <s:Envelope   0x56 = PrefixDictionaryElementS, dict 0x02
0b 01 73 04            xmlns:s=...   0x0B = DictionaryXmlnsAttribute, 's', 0x04
0b 01 61 06            xmlns:a=...   'a' -> dict 0x06 (WS-Addressing)
56 08                  <s:Header>    dict 0x08 = Header
44 0a                  <a:Action     0x44 = PrefixDictionaryElementA, dict 0x0A
1e 00 82               s:mustUnderstand="1"  (0x1E = PrefixDictAttributeS,
                                        dict 0x00, 0x82 = OneTextRecord)
b7 64 68 00 74 00 ...  texte UTF-16LE ; 0x64 = 100 octets = 50 caractères ;
                       0xB7 = UnicodeChars8 (0xB6) + 1, marque de fin
                       d'élément fusionnée -> ferme <a:Action>
01                     EndElementRecord -> </s:Header>
56 0e                  <s:Body>      dict 0x0E = Body
01                     EndElementRecord -> </s:Body>
01                     EndElementRecord -> </s:Envelope>
```

Deux points sont contre-intuitifs. D'abord, le préfixe `00` de table de
session vide **n'apparaît pas** ci-dessus : il est ajouté par le dispatcher,
pas par `dump_records` (`classes/handlers/dispatcher.py:49`) ; sur le fil la
trame commence donc par `00 56 02 …`. Ensuite, la marque de fin d'élément
est **fusionnée dans le dernier record de texte** : `dump_records`
incrémente le type du dernier `Text` enfant
(`src/wcf/records/__init__.py:103-106`) et n'émet alors pas de
`EndElementRecord` séparé (`:117-119`), d'où `0xB7`. Un élément sans enfant
textuel, lui, produit bien un `0x01` explicite (`:120-122`).

Les familles de codes de records structurels, toutes relevées dans le dépôt
:

| Famille | Plage | Source |
|---|---|---|
| `EndElementRecord` | `0x01` | `src/wcf/records/base.py:152` |
| Attributs `xmlns` (dict.) | `0x0A`–`0x0B` | `src/wcf/records/attributes.py:222,256` |
| `PrefixDictionaryAttribute{A..Z}` | `0x0C`–`0x25` | `src/wcf/records/attributes.py:431` |
| `PrefixAttribute{A..Z}` | `0x26`–`0x3F` | `src/wcf/records/attributes.py:447` |
| `PrefixDictionaryElement{A..Z}` | `0x44`–`0x5D` | `src/wcf/records/elements.py:321` |
| `PrefixElement{A..Z}` | `0x5E`–`0x77` | `src/wcf/records/elements.py:337` |

La règle de dérivation est arithmétique : le code d'un préfixe à une lettre
vaut `base + (lettre - 'a')`. C'est ce qui donne `'a'` = `0x44` et `'s'` =
`0x56` pour les éléments, `'s'` = `0x1E` pour les attributs. Un hexdump se
lit donc à vue dès qu'on a ces six lignes en tête.

Les correspondances utiles du dictionnaire statique, toutes relevées dans
`src/wcf/dictionary.py` :

| Chaîne | Index | Chaîne | Index |
|---|---|---|---|
| `mustUnderstand` | 0 | `Address` | 42 |
| `Envelope` | 2 | `ReplyTo` | 44 |
| namespace SOAP 1.2 | 4 | `Expires` | 110 |
| namespace WS-Addressing | 6 | `Fault` | 134 |
| `Header` | 8 | `Code` | 142 |
| `Action` | 10 | `Reason` | 144 |
| `To` | 12 | `Text` | 146 |
| `Body` | 14 | `Detail` | 152 |
| `RelatesTo` | 18 | `Value` | 154 |
| `MessageID` | 26 | `Subcode` | 156 |

Aucun nom d'élément WS-Enumeration (`Enumerate`, `Pull`, `Items`,
`EnumerationContext`, `EndOfSequence`) n'est présent dans la table statique
: vérifié, `inverted_dict` renvoie `None` pour chacun. C'est précisément ce
que le dictionnaire de session sert à compenser côté client. Côté serveur,
ces noms partent donc en toutes lettres, ce qui gonfle la réponse mais ne
pose aucun problème d'interopérabilité.

Les codes de records de texte, également vérifiés dans
`src/wcf/records/text.py` :

| Type | Record | Code | Ligne |
|---|---|---|---|
| entier 8 bits | `Int8TextRecord` | `0x88` | 114 |
| entier 16 bits | `Int16TextRecord` | `0x8A` | 146 |
| entier 32 bits | `Int32TextRecord` | `0x8C` | 168 |
| entier 64 bits | `Int64TextRecord` | `0x8E` | 190 |
| dateTime | `DatetimeTextRecord` | `0x96` | 531 |
| chaîne UTF-8 courte | `Chars8TextRecord` | `0x98` | 582 |
| chaîne UTF-16 courte | `UnicodeChars8TextRecord` | `0xB6` | 269 |
| base64 court | `Bytes8TextRecord` | `0x9E` | 728 |
| GUID | `UuidTextRecord` | `0xB0` | 717 |

> `documentation/03-protocole.md:89-90` associe `0x88` à `xsd:int` et `0x8A`
> à `xsd:long`. Le code dit `0x88 = Int8` et `0x8A = Int16` ; `Int32` est
> `0x8C`, `Int64` est `0x8E`. La règle réelle est dynamique : `xml2records`
> choisit la largeur d'après la **valeur**, pas d'après le type XSD déclaré
> (`src/wcf/xml2records.py:143-153`). La même ligne 94 annonce un
> `GuidTextRecord` : la classe s'appelle `UuidTextRecord`
> (`src/wcf/records/text.py:716-717`).

### Obtenir le clair quand on ne peut pas décoder le réseau

Trois méthodes, par coût croissant.

- **Le journal applicatif** donne l'action et le `MessageID` de chaque
  requête (`classes/handlers/dispatcher.py:26-28`) puis le handler résolu
  (`:42`) : suffisant pour identifier *quel* message pose problème, pas son
  contenu.
- **Une instrumentation temporaire du dispatcher.** Le point d'observation
  canonique est `xml_request = record.payload_to_xml` (`:24`), où la requête
  est déjà descellée et convertie en XML texte. Écrire `xml_request` puis
  `response_xml` dans un fichier donne ce que le proxy prétendait fournir,
  sans MITM.
- **La rejouabilité hors ligne.** Sauvegarder `record.Payload` en binaire
  permet de rejouer le décodage à froid, sans reproduire l'incident côté
  Windows.

Deux lecteurs de trace hexadécimale existent par ailleurs : `python3 -m
src.nettcp.protocol2xml TRACE_FILE` reconstruit les records NMF et décode
les payloads `0x06` (`src/nettcp/protocol2xml.py:81-101`) ; `python3 -m
src.nettcp.nmf TRACE_FILE` s'arrête aux records
(`src/nettcp/nmf.py:409-431`).

### Les trois harnais de test

| Harnais | Emplacement | Portée | Réseau |
|---|---|---|---|
| Diagnostic | `tools/test/test_adws.py` | environnement | port seulement |
| Handlers | `tools/test/test_handlers.py` | logique isolée | aucun |
| Bout en bout | `tools/test/Test-ADWS-Sovereign.ps1` | cmdlets réelles | complet |

`test_adws.py` exécute six contrôles (`tools/test/test_adws.py:96-100`) :
port `127.0.0.1:9389`, imports `samba`/`samba.samdb`/`ldb`/`gssapi`,
connexion `SamDB` avec lecture du `defaultNamingContext`, encodage XML vers
records (`:48-56`, aller simple, pas aller-retour), **échappement
non-ASCII** et intégrité de la table de routage. Le cinquième est un test de
non-régression du bug « undefined entity » sur les accents (`:62-71`). Le
correctif tient dans une table de quatre entrées
(`src/wcf/records/text.py:46`, appliquée en `:49-56`) : seuls `<`, `>`, `&`
et `"` sont mappés, tout autre point de code reste littéral. La table
`codepoint2name` de `html.entities`, encore importée (`:38-41`), n'est plus
utilisée nulle part, vestige du bug.

`test_handlers.py` construit un `HandlerRegistry` réel sur `system_session`
puis vérifie trois propriétés (`tools/test/test_handlers.py:39-59`) : chaque
clé de `HANDLER_FACTORIES` se résout, `GetVersion` produit un corps
`<ca:Version…>`, et le `<a:RelatesTo>` est bien recopié, garde-fou de
l'invariant le plus coûteux du projet (voir scénario 4).

`Test-ADWS-Sovereign.ps1` est la validation de référence : exécuté depuis un
poste joint au domaine, il journalise un `.log` et un `.json` horodatés dans
`-OutputDirectory` (`:18-19`) et couvre huit phases, connectivité, lectures,
énumérations, mutations, mots de passe, groupes, schéma, charge (`:74`,
`:91`, `:105`, `:127`, `:166`, `:190`, `:222`, `:238`). Le test i18n de la
phase 4 construit ses accents par `[char]0xE9` (`:147-149`) pour être
indépendant de l'encodage du script.

## Scénario 1 : Get-ADUser sur un objet unique, de la socket au résultat

Commande de référence, exécutée depuis un poste joint au domaine :

```powershell
Get-ADUser -Identity 'CN=Administrator,CN=Users,DC=samdom,DC=example,DC=com' `
           -Server dc1.samdom.example.com
```

Le passage par un DN évite l'étape de résolution d'identité (qui, elle,
emprunte la machinerie du scénario 2).

> **Statut des chronologies de ce chapitre.** Les tailles et horodatages
> cités sont relevés dans le fichier `adws.log` du dépôt (sessions du 3 juin
> 2026) ; ils sont donc réels. En revanche l'**enchaînement** présenté
> ci-dessous est une reconstruction : la session de 21:24:07 ne contient que
> le `Get` RootDSE suivi d'un `EndRecord`, tandis que les sessions de
> 10:03:43 et 12:32:41 montrent plusieurs messages applicatifs sur une même
> connexion. Les étapes 21 à 24 décrivent donc le second aller-retour tel
> que le code le traite, pas une trace continue. Second avertissement : les
> tracebacks de `adws.log` référencent des chemins de l'ancienne
> arborescence (`/opt/adws/src/adws/dispatcher.py`,
> `/opt/adws/nettcp/nmf.py`) et deux lignes de journal du `PullHandler` de
> l'époque n'existent plus dans le code actuel. Le journal est un document
> d'archive : les numéros de ligne cités dans ce chapitre viennent du code,
> pas de lui.

Valeurs relevées : requête `Get` RootDSE 486 octets, réponse 6833 octets
(`adws.log`, 21:24:07,376 et 21:24:07,608).

### Chronologie

| Étape | Couche | Record NMF | Contenu | Code |
|---|---|---|---|---|
| 1 C→S | TCP | — | connexion sur 9389 | `classes/server/server.py:25` |
| 2 S | serveur | — | fork du process enfant | `classes/server/server.py:25` |
| 3 S | serveur | — | `settimeout(10)` | `classes/server/connection.py:39` |
| 4 C→S | NMF | `0x00` | Version 1.0 | `classes/server/protocol.py:41` |
| 5 C→S | NMF | `0x01` | Mode duplex | `classes/server/protocol.py:43` |
| 6 C→S | NMF | `0x02` | Via `.../Windows/Resource` | `classes/server/protocol.py:45` |
| 7 C→S | NMF | `0x03` | Encoding `BINARY_DICT` | `classes/server/protocol.py:47` |
| 8 C→S | NMF | `0x09` | `application/negotiate` | `classes/server/protocol.py:49` |
| 9 S→C | NMF | `0x0A` | UpgradeResponse | `classes/server/protocol.py:92` |
| 10 C→S | NNS | `0x16` | token SPNEGO/AP-REQ | `src/nettcp/stream/negotiate.py:64` |
| 11 S→C | NNS | `0x16`/`0x14` | tokens serveur, puis Done | `src/nettcp/stream/gssapi.py:123` |
| 12 C→S | NMF | `0x0C` | PreambleEnd (scellé) | `classes/server/protocol.py:133` |
| 13 S→C | NMF | `0x0B` | PreambleAck | `classes/server/protocol.py:137` |
| 14 C→S | NMF | `0x06` | Get RootDSE, 486 o | `classes/server/protocol.py:140` |
| 15 S | WCF | — | dictionnaire + records → XML | `src/nettcp/nmf.py:363` |
| 16 S | SOAP | — | `RequestContext.from_xml` | `classes/parsing/context.py:38` |
| 17 S | routage | — | action → `GetHandler` | `classes/handlers/handler_registry.py:15` |
| 18 S | LDB | — | `search(base="", SCOPE_BASE)` | `classes/handlers/get.py:122` |
| 19 S→C | NMF | `0x06` | GetResponse RootDSE, 6833 o | `classes/server/protocol.py:153` |
| 20 S | serveur | — | `settimeout(2)` | `classes/server/protocol.py:164` |
| 21 C→S | NMF | `0x06` | Get sur le DN cible | `classes/server/protocol.py:140` |
| 22 S | LDB | — | `search(base=dn, SCOPE_BASE)` | `classes/handlers/get.py:228` |
| 23 S | rendu | — | `whole_object` ou projection IMDA | `classes/handlers/get.py:273-277` |
| 24 S→C | NMF | `0x06` | GetResponse objet | `classes/server/protocol.py:153` |
| 25 C→S | NMF | `0x07` | EndRecord | `classes/server/protocol.py:170` |

L'étape 20 est une singularité de cette implémentation : après la première
réponse, le délai d'attente de la socket tombe de 10 à **2 secondes**
(`classes/server/connection.py:39` puis
`classes/server/protocol.py:162-166`). Passé ce délai sans nouveau message,
le serveur émet un `EndRecord` et ferme (`:119-125`), comportement visible
dans `adws.log` à 10:03:43,233. D'où les connexions très courtes, souvent
une par cmdlet : le client rouvre un canal neuf plutôt que d'en réutiliser
un fermé.

### La requête SOAP

Le corps est vide : en WS-Transfer `Get`, tout est dans les en-têtes
WS-Addressing et dans les paramètres de référence ADWS. La forme ci-dessous
est reconstituée d'après ce que le parseur consomme réellement
(`classes/parsing/context.py:55-64`) et d'après les noms employés par le
protocole : `objectReferenceProperty`, le préfixe d'instance `ldap:`,
`containerHierarchyParent`, `relativeDistinguishedName` et l'identifiant
conventionnel de la racine d'annuaire
`11111111-1111-1111-1111-111111111111`.

```xml
<s:Envelope
    xmlns:s="http://www.w3.org/2003/05/soap-envelope"
    xmlns:a="http://www.w3.org/2005/08/addressing"
    xmlns:ad="http://schemas.microsoft.com/2008/1/ActiveDirectory">
  <s:Header>
    <a:Action s:mustUnderstand="1"
      >http://schemas.xmlsoap.org/ws/2004/09/transfer/Get</a:Action>
    <a:MessageID>urn:uuid:6c656016-ba72-4009-8429-e1299d045ed0</a:MessageID>
    <a:ReplyTo>
      <a:Address>http://www.w3.org/2005/08/addressing/anonymous</a:Address>
    </a:ReplyTo>
    <a:To s:mustUnderstand="1"
      >net.tcp://dc1.samdom.example.com:9389/ActiveDirectoryWebServices/Windows/Resource</a:To>
    <ad:instance>ldap:389</ad:instance>
    <ad:objectReferenceProperty
      >CN=Administrator,CN=Users,DC=samdom,DC=example,DC=com</ad:objectReferenceProperty>
  </s:Header>
  <s:Body />
</s:Envelope>
```

Le `MessageID` est authentique : il figure tel quel dans `adws.log` à
21:24:07,474. Trois champs seulement sont exploités par le serveur :
`a:Action` (routage), `a:MessageID` (corrélation) et
`ad:objectReferenceProperty` (cible). Tout le reste est ignoré, y compris
`a:To` : le routage repose exclusivement sur `a:Action`
(`classes/handlers/handler_registry.py:15-23`), alors que [MS-ADDM] fait
discriminer le point de terminaison (voir la liste au scénario 3). L'en-tête
`<ad:instance>` est bien celui que lit le service Microsoft, sous forme
d'en-tête SOAP du namespace `ad` ; cette implémentation ne le consulte pas.

`GetHandler.handle` bascule vers le RootDSE si la référence est vide, vaut
`root dse` ou le GUID `11111111-…` (`classes/handlers/get.py:39-45`). Sinon
il résout l'objet en essayant d'abord le DN reçu, puis ce DN suffixé du
`defaultNamingContext` (`:211-217`), c'est ce qui permet à un DN relatif de
fonctionner, au prix d'une recherche ldb supplémentaire en cas d'échec.

### La réponse WS-Transfer

Sortie littérale de `_get_object` (`classes/handlers/get.py:279-302`), corps
produit par `whole_object`
(`classes/serialization/object_projector.py:20-28`). La réponse est
**minifiée** sur le fil (`re.sub(r'>\s+<', '><', response)`,
`classes/handlers/get.py:302`) ; elle est ré-indentée ici pour la lecture.

```xml
<?xml version="1.0" encoding="utf-8"?>
<s:Envelope
    xmlns:s="http://www.w3.org/2003/05/soap-envelope"
    xmlns:a="http://www.w3.org/2005/08/addressing"
    xmlns:ad="http://schemas.microsoft.com/2008/1/ActiveDirectory"
    xmlns:addata="http://schemas.microsoft.com/2008/1/ActiveDirectory/Data"
    xmlns:da="http://schemas.microsoft.com/2006/11/IdentityManagement/DirectoryAccess"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:xsd="http://www.w3.org/2001/XMLSchema">
  <s:Header>
    <a:Action s:mustUnderstand="1"
      >http://schemas.xmlsoap.org/ws/2004/09/transfer/GetResponse</a:Action>
    <a:RelatesTo>urn:uuid:6c656016-ba72-4009-8429-e1299d045ed0</a:RelatesTo>
  </s:Header>
  <s:Body>
    <addata:user>
      <ad:objectReferenceProperty>
        <ad:value xsi:type="xsd:string"
          >f6aac55f-3a2e-4b1c-9d70-1e4a2b6c8d91</ad:value>
      </ad:objectReferenceProperty>
      <addata:objectClass LdapSyntax="ObjectIdentifier">
        <ad:value xsi:type="xsd:string">top</ad:value>
        <ad:value xsi:type="xsd:string">person</ad:value>
        <ad:value xsi:type="xsd:string">organizationalPerson</ad:value>
        <ad:value xsi:type="xsd:string">user</ad:value>
      </addata:objectClass>
      <addata:sAMAccountName LdapSyntax="UnicodeString">
        <ad:value xsi:type="xsd:string">Administrator</ad:value>
      </addata:sAMAccountName>
      <addata:userAccountControl LdapSyntax="Integer">
        <ad:value xsi:type="xsd:string">512</ad:value>
      </addata:userAccountControl>
      <addata:pwdLastSet LdapSyntax="LargeInteger">
        <ad:value xsi:type="xsd:string">133628160000000000</ad:value>
      </addata:pwdLastSet>
      <addata:objectGUID LdapSyntax="OctetString">
        <ad:value xsi:type="xsd:base64Binary">X8Wq9i46HEudcB5KK2yNkQ==</ad:value>
      </addata:objectGUID>
      <addata:objectSid LdapSyntax="SidString">
        <ad:value xsi:type="xsd:base64Binary">AQUAAAAAAAUVAAAA…</ad:value>
      </addata:objectSid>
      <addata:nTSecurityDescriptor LdapSyntax="NTSecurityDescriptor">
        <ad:value xsi:type="xsd:base64Binary">AQAEnIgEAAA…</ad:value>
      </addata:nTSecurityDescriptor>
      <ad:relativeDistinguishedName>
        <ad:value xsi:type="xsd:string">CN=Administrator</ad:value>
      </ad:relativeDistinguishedName>
      <ad:distinguishedName>
        <ad:value xsi:type="xsd:string"
          >CN=Administrator,CN=Users,DC=samdom,DC=example,DC=com</ad:value>
      </ad:distinguishedName>
    </addata:user>
  </s:Body>
</s:Envelope>
```

Les valeurs binaires sont tronquées et les valeurs scalaires sont
représentatives, non relevées ; **la structure, les noms de `LdapSyntax` et
les `xsi:type`, eux, sont exacts** et se déduisent mécaniquement du code :

| Attribut | Table source | `LdapSyntax` | `xsi:type` |
|---|---|---|---|
| `objectClass` | `NAME_OVERRIDES:128` | `ObjectIdentifier` | `xsd:string` |
| `cn` | défaut | `UnicodeString` | `xsd:string` |
| `userAccountControl` | `INTEGER_ATTRIBUTES:22` | `Integer` | `xsd:string` |
| `pwdLastSet` | `LARGE_INTEGER_ATTRIBUTES:52` | `LargeInteger` | `xsd:string` |
| `whenCreated` | `GENERALIZED_TIME_ATTRIBUTES:68` | `GeneralizedTimeString` | `xsd:string` |
| `objectGUID` | `BINARY_ATTRIBUTES:59` | `OctetString` | `xsd:base64Binary` |
| `objectSid` | `NAME_OVERRIDES:120` | `SidString` | `xsd:base64Binary` |
| `nTSecurityDescriptor` | `NAME_OVERRIDES:126` | `NTSecurityDescriptor` | `xsd:base64Binary` |

La règle qui gouverne la colonne de droite est la contrainte la plus dure du
protocole telle que ce projet l'a établie : **le fil ne porte que deux
`xsi:type`**, `xsd:string` et `xsd:base64Binary`
(`src/serialization/syntax_constants.py:72-87`). Entiers, booléens et dates
voyagent en chaîne ; leur type LDAP réel est porté par `LdapSyntax`, jamais
par `xsi:type`. Émettre `xsd:integer` provoquait historiquement une
`KeyNotFoundException` côté client et cassait toutes les cmdlets à la
connexion (`documentation/05-tests.md:147-152`).

Trois attributs sont **synthétiques** : `objectReferenceProperty`,
`relativeDistinguishedName` et `distinguishedName` sortent en espace `ad:`,
**sans** `LdapSyntax` (`classes/serialization/object_projector.py:48-53`),
et sont retirés du flux d'attributs ordinaires pour éviter un doublon
(`:41-46`, `SYNTHETIC_KEYS:9-12`). `objectReferenceProperty` porte le **GUID
canonique** en `xsd:string`, à ne pas confondre avec `objectGUID` qui part
en base64 des 16 octets bruts. La conversion se fait par
`uuid.UUID(bytes_le=…)` (`classes/handlers/get.py:271`), noter le
`bytes_le`, imposé par la représentation Windows du GUID.

### La variante IMDA

Si le client passe par `<da:BaseObjectSearchRequest>` ou
`<da:IdentityManagementOperation>` (`classes/parsing/context.py:66-69`), le
rendu change complètement. Requête typique, en demandant deux attributs :

```xml
<s:Body>
  <da:BaseObjectSearchRequest
      xmlns:da="http://schemas.microsoft.com/2006/11/IdentityManagement/DirectoryAccess">
    <da:AttributeType>addata:sAMAccountName</da:AttributeType>
    <da:AttributeType>addata:userAccountControl</da:AttributeType>
  </da:BaseObjectSearchRequest>
</s:Body>
```

Le préfixe `addata:` est retiré à l'analyse
(`classes/parsing/context.py:79-83`), puis les attributs LDB sont filtrés
sur cette liste (`classes/handlers/get.py:67-77`). Corps de réponse produit
par `imda_projection` (`classes/serialization/object_projector.py:30-39`) :

```xml
<s:Body>
  <da:BaseObjectSearchResponse>
    <da:PartialAttribute>
      <addata:sAMAccountName LdapSyntax="UnicodeString">
        <ad:value xsi:type="xsd:string">Administrator</ad:value>
      </addata:sAMAccountName>
    </da:PartialAttribute>
    <da:PartialAttribute>
      <addata:userAccountControl LdapSyntax="Integer">
        <ad:value xsi:type="xsd:string">512</ad:value>
      </addata:userAccountControl>
    </da:PartialAttribute>
    <da:PartialAttribute>
      <ad:distinguishedName>
        <ad:value xsi:type="xsd:string"
          >CN=Administrator,CN=Users,DC=samdom,DC=example,DC=com</ad:value>
      </ad:distinguishedName>
    </da:PartialAttribute>
  </da:BaseObjectSearchResponse>
</s:Body>
```

Le dernier `<da:PartialAttribute>` est **inconditionnel** :
`distinguishedName` est toujours émis, même s'il n'a pas été demandé
(`classes/serialization/object_projector.py:34-38`). PowerShell s'en sert
comme clé d'identité ; son absence casse la désérialisation.

Trois formes coexistent donc, et le discriminant est `context.is_imda and
context.requested_attributes` (`classes/handlers/get.py:273`) :

| Requête | Attributs demandés | Corps de réponse |
|---|---|---|
| `wxf:Get` nu | — | `<addata:{classe}>` |
| `da:BaseObjectSearchRequest` | 1 ou plus | `PartialAttribute` par attribut |
| `da:BaseObjectSearchRequest` | 0 | objet entier dans **un** `PartialAttribute` |

La troisième forme passe par `_wrap_imda_object`
(`classes/handlers/get.py:102-108`). Se tromper de forme produit côté
Windows l'erreur `Élément de fin '…' attendu, trouvé
'ad:distinguishedName'`.

### Le cas particulier du RootDSE

Le chemin RootDSE n'utilise **pas** `ObjectProjector` : il appelle
directement `renderer.render_attributes`
(`classes/handlers/get.py:142-144`). Conséquence concrète : la réponse
RootDSE en WS-Transfer contient `<ad:objectReferenceProperty>` puis les
attributs, mais **aucun** `relativeDistinguishedName` ni `distinguishedName`
final. Le wrapper est `<addata:top>` et le GUID est la constante
`11111111-1111-1111-1111-111111111111` (`classes/handlers/get.py:153-165`).

Deux corrections y sont appliquées avant rendu :

- `vendorName` et `vendorVersion`, que Samba expose mais pas AD, sont
  **supprimés** (`_ROOTDSE_DROP`, `classes/handlers/get.py:15-17`, appliqué
  en `:60-61`). Le client cherche chaque nom d'attribut RootDSE dans une
  table figée sans `TryGetValue` : une clé inconnue lève une
  `KeyNotFoundException` et casse toutes les cmdlets dès la connexion.
- `msDS-PortLDAP` et `msDS-PortSSL` sont **injectés** aux valeurs `389` et
  `636` s'ils manquent (`classes/handlers/get.py:62-65`).

## Scénario 2 : Get-ADUser -Filter * — énumération paginée complète

```powershell
Get-ADUser -Filter * -Server dc1.samdom.example.com
```

Trois actions WS-Enumeration, sur la même connexion TCP.

### Chronologie

| Étape | Couche | Record NMF | Contenu | Code |
|---|---|---|---|---|
| 1–13 | — | — | identiques au scénario 1 | — |
| 14 C→S | NMF | `0x06` | `Enumerate` + LdapQuery, 1338 o | `classes/server/protocol.py:140` |
| 15 S | SOAP | — | extraction BaseObject/Filter/Scope | `classes/parsing/context.py:92-122` |
| 16 S | filtre | — | normalisation du filtre LDAP | `classes/handlers/enumerate.py:93-98` |
| 17 S | LDB | — | `search` **complet**, non paginé | `classes/handlers/enumerate.py:48-54` |
| 18 S | cache | — | création du contexte UUID, TTL 3600 s | `classes/handlers/enumerate.py:61-68` |
| 19 S→C | NMF | `0x06` | `EnumerateResponse`, 317 o | `classes/handlers/enumerate.py:106` |
| 20 C→S | NMF | `0x06` | `Pull` n°1 + MaxElements, 555 o | `classes/server/protocol.py:140` |
| 21 S | cache | — | `get_next_batch(max)` | `classes/enumeration/enumeration_context.py:26` |
| 22 S | rendu | — | `whole_object` par item | `classes/handlers/pull.py:49-56` |
| 23 S→C | NMF | `0x06` | `PullResponse`, 1169 o | `classes/handlers/pull.py:75` |
| 24 C→S | NMF | `0x06` | `Pull` n°2..n | `classes/handlers/pull.py:15` |
| 25 S→C | NMF | `0x06` | `PullResponse` … `EndOfSequence` | `classes/handlers/pull.py:85-91` |
| 26 C→S | NMF | `0x06` | `Release` | `classes/handlers/release.py:16` |
| 27 S→C | NMF | `0x06` | `ReleaseResponse`, corps vide | `classes/handlers/release.py:42` |
| 28 C→S | NMF | `0x07` | EndRecord | `classes/server/protocol.py:170` |

Les tailles 1338 / 317 / 555 / 1169 octets sont relevées dans `adws.log`
(session du 3 juin 2026, 09:46:12), pour une recherche filtrée sur
`(sAMAccountName=Administrator)` rendant un seul objet. Cette session
s'arrête après le `Pull` : elle ne comporte ni `Release` ni `EndRecord`, le
client ayant été un harnais de test et non le module PowerShell. Les étapes
26 à 28 décrivent donc le comportement du code, pas cette trace.

### Message 1 — Enumerate

La requête porte deux dialectes distincts : un dialecte de **filtre**
(`.../Dialect/LdapQuery`) et un dialecte de **sélection**
(`.../Dialect/XPath-Level-1`), tous deux nommés dans les constantes du
service ADWS Microsoft. Le serveur ne valide pas les URI de dialecte : il
cherche directement les éléments `adlq:`
(`classes/parsing/context.py:95-106`) et `ad:SelectionProperty` (`:110`).

```xml
<s:Envelope
    xmlns:s="http://www.w3.org/2003/05/soap-envelope"
    xmlns:a="http://www.w3.org/2005/08/addressing"
    xmlns:wsen="http://schemas.xmlsoap.org/ws/2004/09/enumeration"
    xmlns:ad="http://schemas.microsoft.com/2008/1/ActiveDirectory"
    xmlns:adlq="http://schemas.microsoft.com/2008/1/ActiveDirectory/Dialect/LdapQuery">
  <s:Header>
    <a:Action s:mustUnderstand="1"
      >http://schemas.xmlsoap.org/ws/2004/09/enumeration/Enumerate</a:Action>
    <a:MessageID>urn:uuid:00000000-0000-0000-0000-000000000001</a:MessageID>
    <a:To s:mustUnderstand="1"
      >net.tcp://dc1.samdom.example.com:9389/ActiveDirectoryWebServices\
/Windows/Enumeration</a:To>
    <ad:instance>ldap:389</ad:instance>
  </s:Header>
  <s:Body>
    <wsen:Enumerate>
      <wsen:Filter
          Dialect="http://schemas.microsoft.com/2008/1/ActiveDirectory/Dialect/LdapQuery">
        <adlq:LdapQuery>
          <adlq:Filter>(sAMAccountName=Administrator)</adlq:Filter>
          <adlq:BaseObject>DC=samdom,DC=example,DC=com</adlq:BaseObject>
          <adlq:Scope>subtree</adlq:Scope>
        </adlq:LdapQuery>
      </wsen:Filter>
      <ad:Selection
          Dialect="http://schemas.microsoft.com/2008/1/ActiveDirectory/Dialect/XPath-Level-1">
        <ad:SelectionProperty>addata:cn</ad:SelectionProperty>
        <ad:SelectionProperty>addata:objectGUID</ad:SelectionProperty>
        <ad:SelectionProperty>addata:objectSid</ad:SelectionProperty>
        <ad:SelectionProperty>ad:distinguishedName</ad:SelectionProperty>
        <ad:SelectionProperty>addata:userAccountControl</ad:SelectionProperty>
      </ad:Selection>
      <ad:controls>
        <ad:control type="1.2.840.113556.1.4.319" criticality="true" />
      </ad:controls>
    </wsen:Enumerate>
  </s:Body>
</s:Envelope>
```

Traitements notables côté serveur :

- Le filtre est **désamorcé des entités XML** (`&amp ;` → `&`,
  `classes/parsing/context.py:181-190`) puis normalisé par `FilterParser`
  (`classes/handlers/enumerate.py:93-98`). La normalisation reparenthèse les
  opérandes de `!` « nus » (`(!attr=val)`, forme qu'AD tolère et que ldb
  refuse) en `(!(attr=val))` (`classes/parsing/filter_parser.py:35-44`). En
  cas d'échec d'analyse, le filtre brut est transmis tel quel (`:96-98`).
- Un `BaseObject` vide retombe sur le `defaultNamingContext`
  (`classes/handlers/enumerate.py:30-33`), sans quoi ldb refuse la recherche
  avec `empty base DN`.
- Les attributs de sélection passent par `ConstructedAttrs.expand`
  (`classes/serialization/constructed_attrs.py:33-43`). **Attention au
  contresens** : cette fonction n'ajoute les 17 attributs construits
  (`tokenGroups`, `canonicalName`, `msDS-PrincipalName`, …, `:3-21`) que
  dans deux cas, liste vide, ou liste contenant `*`. Face à une liste
  explicite de `SelectionProperty`, elle la renvoie **inchangée**. La trace
  le confirme : cinq `SelectionProperty` en entrée donnent `[ENUMERATE]
  Attributes: ['cn', 'objectGUID', 'objectSid', 'distinguishedName',
  'userAccountControl']`, sans aucun ajout. `objectClass` est ensuite ajouté
  d'office s'il manque (`classes/handlers/enumerate.py:100-104`), le rendu
  en a besoin pour nommer le wrapper.
- À défaut de `<adlq:Filter>`, le filtre par défaut est `(objectClass=*)`
  (`classes/handlers/enumerate.py:24`), et le scope par défaut `Subtree`
  (`:25`).
- Les contrôles LDAP sont traduits en syntaxe ldb
  (`classes/parsing/controls_parser.py:42-74`) via une table de 19 OID
  (`:8-28`), sous la forme `nom:criticité[:valeur]`.

Réponse, produite littéralement par `_build_enumerate_response`
(`classes/handlers/enumerate.py:106-129`) :

```xml
<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
            xmlns:a="http://www.w3.org/2005/08/addressing"
            xmlns:wsen="http://schemas.xmlsoap.org/ws/2004/09/enumeration">
  <s:Header>
    <a:Action s:mustUnderstand="1"
      >http://schemas.xmlsoap.org/ws/2004/09/enumeration/EnumerateResponse</a:Action>
    <a:RelatesTo>urn:uuid:00000000-0000-0000-0000-000000000001</a:RelatesTo>
  </s:Header>
  <s:Body>
    <wsen:EnumerateResponse>
      <wsen:Expires>2026-06-03T10:46:12.134281Z</wsen:Expires>
      <wsen:EnumerationContext
        >020b12b2-a945-4ce6-b721-369d36f583e4</wsen:EnumerationContext>
    </wsen:EnumerateResponse>
  </s:Body>
</s:Envelope>
```

L'UUID `020b12b2-…` est authentique (`adws.log`, 09:46:12,134). `Expires`
est calculé à `utcnow + 1 h`, sérialisé en ISO 8601 avec un `Z` ajouté
manuellement (`classes/handlers/enumerate.py:81`).

> **Écart de conception à assumer.** L'`Enumerate` exécute **une seule
> recherche LDB complète** et matérialise tous les résultats en mémoire
> (`classes/handlers/enumerate.py:48-79`). La pagination est ensuite
> purement côté serveur, par découpage de la liste. Le contrôle
> `PagedResults` (`1.2.840.113556.1.4.319`) envoyé par le client est traduit
> et transmis à ldb, mais aucune reprise de curseur n'est implémentée. La
> liste est tronquée à `MAX_RESULTS_PER_CONTEXT = 50000`
> (`classes/enumeration/enumeration_registry.py:12`), avec un `WARNING`
> explicite (`classes/handlers/enumerate.py:74-78`).

### Messages 2 à n — Pull

```xml
<s:Body>
  <wsen:Pull>
    <wsen:EnumerationContext
      >020b12b2-a945-4ce6-b721-369d36f583e4</wsen:EnumerationContext>
    <wsen:MaxElements>5</wsen:MaxElements>
  </wsen:Pull>
</s:Body>
```

La valeur `5` est celle observée dans la trace ; aucune capture du dépôt ne
donne celle du module PowerShell réel. Le serveur relit ces deux champs
(`classes/parsing/context.py:129-142`) (un `MaxElements` non numérique
retombe silencieusement sur `None` (`:139-142`), donc sur le défaut de 100)
puis `get_next_batch` découpe la liste en place :

```python
start = self.result_index
end = min(start + max_elements, len(self.cached_results))
batch = self.cached_results[start:end]
self.result_index = end
```

(`classes/enumeration/enumeration_context.py:29-33`). `is_end_of_sequence`
vaut `result_index >= len(cached_results)` (`:22-24`) et est évalué
**après** le découpage (`classes/handlers/pull.py:33-34`).

Réponse intermédiaire, quand il reste des objets :

```xml
<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
            xmlns:a="http://www.w3.org/2005/08/addressing"
            xmlns:wsen="http://schemas.xmlsoap.org/ws/2004/09/enumeration"
            xmlns:addata="http://schemas.microsoft.com/2008/1/ActiveDirectory/Data"
            xmlns:ad="http://schemas.microsoft.com/2008/1/ActiveDirectory"
            xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
            xmlns:xsd="http://www.w3.org/2001/XMLSchema">
  <s:Header>
    <a:Action s:mustUnderstand="1"
      >http://schemas.xmlsoap.org/ws/2004/09/enumeration/PullResponse</a:Action>
    <a:RelatesTo>urn:uuid:00000000-0000-0000-0000-000000000002</a:RelatesTo>
  </s:Header>
  <s:Body>
    <wsen:PullResponse>
      <wsen:Items>
        <addata:user>
          <ad:objectReferenceProperty>
            <ad:value xsi:type="xsd:string"
              >f6aac55f-3a2e-4b1c-9d70-1e4a2b6c8d91</ad:value>
          </ad:objectReferenceProperty>
          <!-- attributs demandés, puis les deux synthétiques de queue,
               exactement comme dans la réponse WS-Transfer du scénario 1 -->
          <ad:distinguishedName>
            <ad:value xsi:type="xsd:string"
              >CN=Administrator,CN=Users,DC=samdom,DC=example,DC=com</ad:value>
          </ad:distinguishedName>
        </addata:user>
        <!-- … un <addata:{classe}> par objet du lot … -->
      </wsen:Items>
      <wsen:EnumerationContext
        >020b12b2-a945-4ce6-b721-369d36f583e4</wsen:EnumerationContext>
    </wsen:PullResponse>
  </s:Body>
</s:Envelope>
```

Réponse finale, quand le lot épuise la liste : `<wsen:EnumerationContext>`
est remplacé par `<wsen:EndOfSequence/>` (`classes/handlers/pull.py:85-91`).
Si le lot est vide, `<wsen:Items/>` est auto-fermé (`:83-84`).

Points structurels à retenir :

- Les items de `Pull` emploient **exactement** la forme WS-Transfer (objet
  entier, wrapper `<addata:{classe}>`), jamais des `PartialAttribute`
  (`classes/handlers/pull.py:56` appelle `whole_object`).
- L'enveloppe `Pull` **doit** déclarer `xsd` : les `<ad:value>` portent
  `xsi:type="xsd:…"` (`classes/handlers/pull.py:101`). Une déclaration
  manquante rend le document invalide côté client.
- La classe du wrapper est la **dernière** valeur de `objectClass`, décodée
  en s'appuyant sur le protocole d'indexation et non sur `str`
  (`classes/handlers/pull.py:58-65`). C'est la parade au bug historique
  `__str__ returned non-string (type NoneType)` : `ldb.MessageElement` n'est
  pas une `list` et son `__str__` C peut renvoyer `None`.

### Ce qui se passe sur plusieurs Pull

Le contexte d'énumération est un **objet mutable partagé entre les Pull
d'une même connexion**. Trois propriétés en découlent, toutes vérifiables.

- **Le curseur est monotone.** `result_index` n'est jamais remis à zéro ; un
  `Pull` rejoué avec le même contexte renvoie le lot *suivant*, pas le même.
  Il n'y a donc **aucune idempotence** : une retransmission côté client, ou
  un `Pull` doublé, saute silencieusement des objets.
- **Le contexte est local au process.** `get_enumeration_registry` est un
  singleton de module (`src/enumeration/enumeration.py:6-13`) et le serveur
  est un `ForkingTCPServer` (`classes/server/server.py:25`). Chaque
  connexion étant un process distinct, un `Pull` arrivant sur une **autre**
  connexion ne trouve pas le contexte et reçoit `Invalid or expired
  enumeration context` (`classes/handlers/pull.py:28-31`). Le fonctionnement
  repose entièrement sur le fait que le client réutilise la même connexion
  TCP pour tout le cycle Enumerate/Pull/Release.
- **La taille de lot par défaut diffère de la référence.** En l'absence de
  `MaxElements`, cette implémentation prend **100**
  (`classes/handlers/pull.py:20`), alors que le service Microsoft utilise
  `DefaultPullElements = 1`. En pratique le module PowerShell envoie
  toujours `MaxElements`, la divergence reste théorique.

Le cache lui-même est plafonné à `MAX_CONTEXTS = 256`
(`classes/enumeration/enumeration_registry.py:11`) avec éviction du plus
ancien et un `WARNING` (`:26-29`). Une lecture de contexte expiré le
supprime et renvoie `None` (`:43-49`). `Renew` réarme l'expiration à une
heure (`classes/handlers/renew.py:19-21`), `GetStatus` la restitue sans la
modifier (`classes/handlers/get_status.py:24-29`).

### Message final — Release

```xml
<s:Body>
  <wsen:Release>
    <wsen:EnumerationContext
      >020b12b2-a945-4ce6-b721-369d36f583e4</wsen:EnumerationContext>
  </wsen:Release>
</s:Body>
```

```xml
<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
            xmlns:a="http://www.w3.org/2005/08/addressing">
  <s:Header>
    <a:Action s:mustUnderstand="1"
      >http://schemas.xmlsoap.org/ws/2004/09/enumeration/ReleaseResponse</a:Action>
    <a:RelatesTo>urn:uuid:00000000-0000-0000-0000-000000000003</a:RelatesTo>
  </s:Header>
  <s:Body />
</s:Envelope>
```

`ReleaseHandler` supprime l'entrée du cache et journalise `[RELEASE] Context
deleted successfully` (`classes/handlers/release.py:27-30`). Un `Release`
sur un contexte inconnu n'est **pas** une erreur : `release_context` renvoie
`False` sans lever (`:51-56` du cache), et la réponse est un
`ReleaseResponse` normal. Un client qui abandonne sans `Release` ne fuit
rien de durable : le process enfant meurt avec la connexion.

## Scénario 3 : New-ADUser puis Set-ADAccountPassword — écriture et mot de passe

```powershell
New-ADUser -Name adwsTest-User -SamAccountName adwsTest-User `
           -AccountPassword $pw -Enabled $true -Server dc1.samdom.example.com
Set-ADAccountPassword adwsTest-User -Reset -NewPassword $resetPw `
           -Server dc1.samdom.example.com
```

### Chronologie

| Étape | Couche | Record NMF | Contenu | Code |
|---|---|---|---|---|
| 1–13 | — | — | préambule + GSSAPI | — |
| 14 C→S | NMF | `0x06` | `transfer/Create` + `da:AddRequest` | `classes/server/protocol.py:140` |
| 15 S | routage | — | `Create` → `CRUDHandler` | `src/handlers/handler_routing.py:39` |
| 16 S | CRUD | — | suffixe `/create` → `CreateHandler` | `classes/handlers/crud.py:20-21` |
| 17 S | parsing | — | `da:AttributeTypeAndValue` | `classes/parsing/attribute_parser.py:12-25` |
| 18 S | DN | — | RDN + `container-hierarchy-parent` | `classes/handlers/create.py:53-64` |
| 19 S | LDB | — | `db.add(msg)` | `classes/handlers/create.py:35` |
| 20 S | LDB | — | relecture de `objectGUID` | `classes/handlers/create.py:67-71` |
| 21 S→C | NMF | `0x06` | `ResourceCreated` (EPR) | `classes/handlers/create.py:74-90` |
| 22 C→S | NMF | `0x06` | `transfer/Get` de contrôle | `classes/handlers/get.py:200-304` |
| 23 C→S | NMF | `0x06` | `SetPassword` (custom action) | `src/handlers/handler_routing.py:61` |
| 24 S | LDB | — | `unicodePwd` en UTF-16LE guillemeté | `classes/handlers/set_password.py:39-43` |
| 25 S→C | NMF | `0x06` | `SetPasswordResponse` vide | `classes/handlers/set_password.py:23-24` |
| 26 C→S | NMF | `0x07` | EndRecord | `classes/server/protocol.py:170` |

Ce séquencement est attesté dans `adws.log`, réparti sur deux sessions dont
voici les tailles réelles.

| Message | Session | Requête | Réponse |
|---|---|---|---|
| `transfer/Create` | 12:32:41 | 1039 o | 1001 o |
| `transfer/Get` de contrôle | 12:32:41 | 623 o | 73239 o |
| `transfer/Delete` | 12:32:41 | 621 o | 631 o |
| `transfer/Create` | 19:02:03 | 1109 o | 1001 o |
| `SetPassword` | 19:02:03 | 936 o | 804 o |

Le rapport 623 octets en requête pour 73239 en réponse mérite d'être médité
: c'est un `Get` sans liste d'attributs, donc un objet complet, `*` plus les
17 attributs construits (`ConstructedAttrs.expand` avec une liste vide
renvoie `["*"] + CONSTRUCTED_ATTRIBUTES`,
`classes/serialization/constructed_attrs.py:35-36`). Un facteur
d'amplification de 117 sur un seul objet utilisateur explique à lui seul
pourquoi la phase 5 du projet porte sur la performance.

### Le Create

La particularité d'ADWS est qu'un `Create` n'envoie **jamais** de
`distinguishedName` complet. La cible est décrite par son RDN et le DN de
son conteneur, sous les noms `relativeDistinguishedName` et
`container-hierarchy-parent` (les constantes du service ADWS Microsoft,
repris en `classes/handlers/create.py:23-25`).

```xml
<s:Envelope
    xmlns:s="http://www.w3.org/2003/05/soap-envelope"
    xmlns:a="http://www.w3.org/2005/08/addressing"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:xsd="http://www.w3.org/2001/XMLSchema"
    xmlns:da="http://schemas.microsoft.com/2006/11/IdentityManagement/DirectoryAccess">
  <s:Header>
    <a:Action s:mustUnderstand="1"
      >http://schemas.xmlsoap.org/ws/2004/09/transfer/Create</a:Action>
    <a:MessageID>urn:uuid:00000000-0000-0000-0000-000000000001</a:MessageID>
    <a:To s:mustUnderstand="1"
      >net.tcp://dc1.samdom.example.com:9389/ActiveDirectoryWebServices\
/Windows/ResourceFactory</a:To>
  </s:Header>
  <s:Body>
    <da:AddRequest Dialect="http://schemas.microsoft.com/2008/1/ActiveDirectory">
      <da:AttributeTypeAndValue>
        <da:AttributeType>ad:relativeDistinguishedName</da:AttributeType>
        <da:AttributeValue>
          <ad:value xsi:type="xsd:string"
            xmlns:ad="http://schemas.microsoft.com/2008/1/ActiveDirectory"
            >CN=adwsTest-User</ad:value>
        </da:AttributeValue>
      </da:AttributeTypeAndValue>
      <da:AttributeTypeAndValue>
        <da:AttributeType>ad:container-hierarchy-parent</da:AttributeType>
        <da:AttributeValue>
          <ad:value xsi:type="xsd:string"
            xmlns:ad="http://schemas.microsoft.com/2008/1/ActiveDirectory"
            >CN=Users,DC=samdom,DC=example,DC=com</ad:value>
        </da:AttributeValue>
      </da:AttributeTypeAndValue>
      <!-- idem pour addata:objectClass = user et
           addata:sAMAccountName = adwsTest-User -->
      <da:AttributeTypeAndValue>
        <da:AttributeType>addata:unicodePwd</da:AttributeType>
        <da:AttributeValue>
          <ad:value xsi:type="xsd:base64Binary"
            xmlns:ad="http://schemas.microsoft.com/2008/1/ActiveDirectory"
            >IgBQAEAAcwBzAHcAMAByAGQAIQAiAA==</ad:value>
        </da:AttributeValue>
      </da:AttributeTypeAndValue>
    </da:AddRequest>
  </s:Body>
</s:Envelope>
```

Traitement, pas à pas :

- `BodyParser.find_add_request` localise `da:AddRequest`
  (`classes/parsing/body_parser.py:22-26`), `AttributeParser.parse_changes`
  en extrait une liste `{name, operation, values}`
  (`classes/parsing/attribute_parser.py:12-25`). Les préfixes
  `ad:`/`addata:` sont retirés (`:61-67`), et toute valeur typée
  `base64Binary` est décodée en `bytes` dès l'analyse (`:49-53`).
- `_resolve_dn` recompose `f"{rdn},{parent}"`
  (`classes/handlers/create.py:53-64`) ; un `distinguishedName` explicite,
  s'il est présent, l'emporte (`:60-61`).
- Les trois clés de routage sont **retirées** avant écriture (`DN_ROUTING`,
  `classes/handlers/create.py:23-25`, filtré en `:50`) : ce ne sont pas des
  attributs LDAP.
- `LdapAttrBuilder.build_message` construit le `ldb.Message` avec
  `FLAG_MOD_ADD` par défaut (`classes/handlers/create.py:32-34`,
  `classes/directory/ldap_attr_builder.py:19-30`). `unicodePwd` bénéficie
  d'un encodage spécial si la valeur arrive en texte : guillemets puis
  UTF-16LE (`classes/directory/ldap_attr_builder.py:15-16`).
- Le GUID est relu après création pour construire l'EPR
  (`classes/handlers/create.py:67-71`), avec un repli sur le GUID nul si la
  relecture échoue.

Réponse, c'est la forme exacte qui a débloqué `New-ADUser` :

```xml
<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
            xmlns:a="http://www.w3.org/2005/08/addressing"
            xmlns:wsen="http://schemas.xmlsoap.org/ws/2004/09/enumeration"
            xmlns:wst="http://schemas.xmlsoap.org/ws/2004/09/transfer"
            xmlns:ad="http://schemas.microsoft.com/2008/1/ActiveDirectory"
            xmlns:addata="http://schemas.microsoft.com/2008/1/ActiveDirectory/Data"
            xmlns:da="http://schemas.microsoft.com/2006/11/IdentityManagement/DirectoryAccess"
            xmlns:adlq="http://schemas.microsoft.com/2008/1/ActiveDirectory/Dialect/LdapQuery"
            xmlns:ca="http://schemas.microsoft.com/2008/1/ActiveDirectory/CustomActions"
            xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
            xmlns:xsd="http://www.w3.org/2001/XMLSchema">
  <s:Header>
    <a:Action s:mustUnderstand="1"
      >http://schemas.xmlsoap.org/ws/2004/09/transfer/CreateResponse</a:Action>
    <a:RelatesTo>urn:uuid:00000000-0000-0000-0000-000000000001</a:RelatesTo>
  </s:Header>
  <s:Body>
    <wst:ResourceCreated
        xmlns:wst="http://schemas.xmlsoap.org/ws/2004/09/transfer"
        xmlns:wsa="http://www.w3.org/2005/08/addressing"
        xmlns:ad="http://schemas.microsoft.com/2008/1/ActiveDirectory">
      <wsa:Address
        >net.tcp://dc1.samdom.example.com:9389/ActiveDirectoryWebServices\
/Windows/Resource</wsa:Address>
      <wsa:ReferenceParameters>
        <ad:objectReferenceProperty
          >3f1c9a20-77bd-4e2a-9a5e-b0d4f1c62e88</ad:objectReferenceProperty>
        <ad:instance>ldap:389</ad:instance>
      </wsa:ReferenceParameters>
    </wst:ResourceCreated>
  </s:Body>
</s:Envelope>
```

Deux détails sont **critiques** et ont chacun coûté un cycle de débogage.
D'abord, `Address` et `ReferenceParameters` sont en espace **WS-Addressing**
(`wsa`), pas en `wst` (`classes/handlers/create.py:79-88`) : l'inverse fait
échouer la désérialisation côté client. Ensuite, l'adresse est dérivée du
`a:To` de la requête en remplaçant `ResourceFactory` par `Resource`
(`:75-77`), avec repli sur l'adresse anonyme WS-Addressing si le `a:To` est
introuvable : le client doit repartir sur le point de terminaison de
ressource, pas sur celui de fabrique. Les six points de terminaison sont
figés côté Microsoft dans les constantes du service ADWS Microsoft :
`Resource` (`:26`), `ResourceFactory` (`:29`), `Enumeration` (`:31`), `mex`
(`:33`), `AccountManagement` (`:35`) et `TopologyManagement` (`:37`).

### Le SetPassword

`Set-ADAccountPassword -Reset` emprunte une **action personnalisée**, pas
WS-Transfer. L'action est
`…/ActiveDirectory/CustomActions/AccountManagement/SetPassword`, résolue par
le routage sur le **dernier segment** d'URL
(`classes/handlers/handler_registry.py:22-23`).

```xml
<s:Envelope
    xmlns:s="http://www.w3.org/2003/05/soap-envelope"
    xmlns:a="http://www.w3.org/2005/08/addressing">
  <s:Header>
    <a:Action s:mustUnderstand="1"
      >http://schemas.microsoft.com/2008/1/ActiveDirectory/CustomActions\
/AccountManagement/SetPassword</a:Action>
    <a:MessageID>urn:uuid:00000000-0000-0000-0000-000000000004</a:MessageID>
    <a:To s:mustUnderstand="1"
      >net.tcp://dc1.samdom.example.com:9389/ActiveDirectoryWebServices\
/Windows/AccountManagement</a:To>
  </s:Header>
  <s:Body>
    <SetPasswordRequest
        xmlns="http://schemas.microsoft.com/2008/1/ActiveDirectory/CustomActions">
      <AccountDN>CN=adwsTest-User,CN=Users,DC=samdom,DC=example,DC=com</AccountDN>
      <NewPassword>Reset@1234</NewPassword>
    </SetPasswordRequest>
  </s:Body>
</s:Envelope>
```

`BodyParser.find_custom_body` retrouve l'élément indifféremment par préfixe
`ca:` ou par nom qualifié complet (`classes/parsing/body_parser.py:34-38`),
et `text_of` lit ses enfants de la même façon (`:40-46`). Le mot de passe
transite **en clair dans le XML** : sa confidentialité repose intégralement
sur le scellement GSSAPI de la phase 3, qui est donc une exigence de
sécurité et pas seulement de compatibilité.

L'écriture est un `FLAG_MOD_REPLACE` sur `unicodePwd`, valeur guillemetée
puis encodée en UTF-16LE (`classes/handlers/set_password.py:39-43`), la
convention [MS-ADTS] pour la réinitialisation administrative.

```xml
<?xml version="1.0" encoding="utf-8"?>
<s:Envelope [les onze déclarations de NS_DECL, voir plus haut]>
  <s:Header>
    <a:Action s:mustUnderstand="1"
      >http://schemas.microsoft.com/2008/1/ActiveDirectory/CustomActions\
/AccountManagement/SetPasswordResponse</a:Action>
    <a:RelatesTo>urn:uuid:00000000-0000-0000-0000-000000000004</a:RelatesTo>
  </s:Header>
  <s:Body>
    <SetPasswordResponse
        xmlns="http://schemas.microsoft.com/2008/1/ActiveDirectory/CustomActions"
      ></SetPasswordResponse>
  </s:Body>
</s:Envelope>
```

Le corps est **vide mais non auto-fermé**
(`classes/handlers/set_password.py:23`) et redéclare le namespace
CustomActions en défaut, sans préfixe : c'est la forme que le client attend.
Toute réponse passant par `SoapEnvelope.wrap` porte les onze déclarations de
`NS_DECL` (`classes/soap/soap_envelope.py:23-30`), même celles qui n'en
utilisent qu'une, c'est le cas ici. Les réponses construites à la main
(`GetResponse`, `EnumerateResponse`, `PullResponse`, `ReleaseResponse`) ne
déclarent, elles, que ce dont elles ont besoin :

| Réponse | Déclarations | Source |
|---|---|---|
| `GetResponse` | 7 (s, a, ad, addata, da, xsi, xsd) | `classes/handlers/get.py:281-289` |
| `EnumerateResponse` | 3 (s, a, wsen) | `classes/handlers/enumerate.py:111-113` |
| `PullResponse` | 7 (+ wsen, sans da) | `classes/handlers/pull.py:95-101` |
| `ReleaseResponse` | 2 (s, a) | `classes/handlers/release.py:45-46` |
| via `wrap` | 11 | `classes/soap/soap_envelope.py:23-30` |

### Le changement self-service, et pourquoi il échoue

`ChangePasswordHandler` construit la modification canonique, suppression de
l'ancien `unicodePwd`, ajout du nouveau, dans le **même** message ldb
(`classes/handlers/change_password.py:45-51`), ce qui est la forme correcte
d'un changement authentifié par l'ancien mot de passe.

L'échec est en aval : le module Samba `password_hash` exige l'adresse réseau
du client (`remoteAddress`) sur ce chemin, information qu'une connexion
`SamDB` locale ne porte pas, et qu'on ne peut pas fabriquer depuis Python
(un `tsocket_address` n'a pas de constructeur exposé). L'erreur remontée est
`Failed to obtain remote address for the LDAP client`
(`documentation/05-tests.md:141-143`). Elle est convertie en faute
`ChangePasswordFault` par `custom_action_fault`
(`classes/handlers/change_password.py:27-29`). Le **reset administrateur
fonctionne** ; c'est le seul écart fonctionnel connu et documenté sur le
périmètre validé.

## Scénario 4 : un échec authentifié — anatomie d'une faute

L'exemple est réel : il figure dans `adws.log` à 10:00:04,771. Un
`Remove-ADUser` porte sur un DN déjà supprimé.

```text
2026-06-03 10:00:04,727 [DISPATCH] action=…/transfer/Delete
                                   message_id=urn:uuid:00000000-…-000000000003
2026-06-03 10:00:04,728 [DISPATCH] handler=TransferHandler
2026-06-03 10:00:04,728 [DeleteHandler] Processing: CN=adwsTest1,CN=Users,…
2026-06-03 10:00:04,768 [DB] SamDB connection established
2026-06-03 10:00:04,771 ERROR [DELETE] failure
_ldb.LdbError: (32, 'objectclass: Cannot delete CN=adwsTest1,CN=Users,
DC=samdom,DC=example,DC=com, entry does not exist!')
2026-06-03 10:00:04,778 [MESSAGES] ▶ SENDING message #2 to client
2026-06-03 10:00:04,779 [MESSAGES] Response payload size: 1224 bytes
```

### Chronologie

| Étape | Couche | Record NMF | Contenu | Code |
|---|---|---|---|---|
| 1 C→S | NMF | `0x06` | `transfer/Delete`, 607 o | `classes/server/protocol.py:140` |
| 2 S | WCF | — | payload → XML | `src/nettcp/nmf.py:363` |
| 3 S | SOAP | — | contexte : action + msgid + DN | `classes/parsing/context.py:38` |
| 4 S | routage | — | `Delete` → `TransferHandler` | `src/handlers/handler_routing.py:38` |
| 5 S | LDB | — | `db.delete(Dn(...))` → `LdbError` | `classes/handlers/delete.py:30` |
| 6 S | handler | — | capture locale + `logger.exception` | `classes/handlers/delete.py:33-37` |
| 7 S | faute | — | `directory_error(msgid, msg, code)` | `classes/faults/faults.py:13-22` |
| 8 S | SOAP | — | enveloppe + `RelatesTo` | `classes/soap/soap_envelope.py:46-59` |
| 9 S | WCF | — | XML → records + `\x00` | `classes/handlers/dispatcher.py:45-50` |
| 10 S→C | NMF | `0x06` | fault SOAP, 1224 o | `classes/server/protocol.py:153` |

Le point saillant : la faute est produite **par le handler**, pas par le
dispatcher. `DeleteHandler` intercepte lui-même l'exception ldb et retourne
un XML de faute comme s'il s'agissait d'une réponse normale
(`classes/handlers/delete.py:33-37`). Le dispatcher ne voit donc jamais
d'exception ; du point de vue de la couche NMF, l'échange est nominal.

### La faute complète

Rendu littéral de `FaultBuilder.directory_error`
(`classes/faults/faults.py:13-22`) passé dans `SoapEnvelope.fault`
(`classes/soap/soap_envelope.py:46-59`). Les déclarations de namespace de
l'enveloppe sont abrégées ici : ce sont les onze de `NS_DECL`
(`classes/soap/soap_envelope.py:23-30`), déjà listées au scénario 3.

```xml
<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
            xmlns:a="http://www.w3.org/2005/08/addressing"
            xmlns:da="http://schemas.microsoft.com/2006/11/IdentityManagement/DirectoryAccess"
            xmlns:ca="http://schemas.microsoft.com/2008/1/ActiveDirectory/CustomActions"
            xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
            xmlns:xsd="http://www.w3.org/2001/XMLSchema">
  <s:Header>
    <a:Action s:mustUnderstand="1"
      >http://www.w3.org/2005/08/addressing/soap/fault</a:Action>
    <a:RelatesTo>urn:uuid:00000000-0000-0000-0000-000000000003</a:RelatesTo>
  </s:Header>
  <s:Body>
    <s:Fault>
      <s:Code>
        <s:Value>s:Receiver</s:Value>
      </s:Code>
      <s:Reason>
        <s:Text xml:lang="en-US">(32, &#x27;objectclass: Cannot delete
CN=adwsTest1,CN=Users,DC=samdom,DC=example,DC=com, entry does not
exist!&#x27;)</s:Text>
      </s:Reason>
      <s:Detail>
        <da:Fault
            xmlns:da="http://schemas.microsoft.com/2006/11/IdentityManagement/DirectoryAccess">
          <da:ShortError>DeleteFailed</da:ShortError>
          <da:LongError>(32, &#x27;objectclass: Cannot delete
CN=adwsTest1,CN=Users,DC=samdom,DC=example,DC=com, entry does not
exist!&#x27;)</da:LongError>
        </da:Fault>
      </s:Detail>
    </s:Fault>
  </s:Body>
</s:Envelope>
```

Éléments à noter, tous vérifiés :

- L'action de faute est `http://www.w3.org/2005/08/addressing/soap/fault`
  (`classes/soap/soap_envelope.py:18`), c'est-à-dire l'URI **WS-Addressing
  1.0**. `documentation/03-protocole.md:226` annonce l'URI 2004/08 : c'est
  une dérive documentaire, le code utilise bien 2005/08.
- `xml:lang` vaut `en-US` (`classes/soap/soap_envelope.py:54`), pas `en`.
- Le message est échappé par `html.escape(reason)`, avec `quote=True` par
  défaut : les apostrophes du message ldb deviennent `&#x27 ;`. C'est une
  référence de caractère numérique, valide en XML, contrairement aux entités
  nommées HTML qui avaient causé le bug des accents.
- `<s:Detail>` n'est émis que si un détail est fourni
  (`classes/soap/soap_envelope.py:56-57`).

### Les autres constructeurs de faute

Quatre familles coexistent, chacune avec son enveloppe de détail.

| Constructeur | `s:Code` | Détail | Fichier |
|---|---|---|---|
| `directory_error` | `s:Receiver` | `da:Fault` / ShortError+LongError | `faults.py:13` |
| `access_denied` | `s:Sender` | aucun | `faults.py:24` |
| `custom_action_fault` | `s:Receiver` | `<{Nom}Fault>` + Subcode `ca:` | `faults.py:28` |
| `invalid_enumeration_context` | `s:Sender` | aucun | `faults.py:43` |

`custom_action_fault` est la seule à poser un `<s:Subcode>` et à changer
l'action de faute pour `…/ActiveDirectory/Data/fault`
(`classes/faults/faults.py:38-41`, `src/soap/namespaces.py:13`), c'est la
forme attendue pour les actions personnalisées. Son détail contient quatre
éléments : `ArgumentError` et `DirectoryError` en `xsi:nil="true"`, puis
`Error` et `ShortError` (`classes/faults/faults.py:31-37`).

`TypedFaults` fournit en parallèle cinq familles typées
(`classes/faults/typed_faults.py:16-64`), toutes de forme
`<{préfixe}:FaultDetail><Code/><Message/>` :

| Méthode | `s:Code` | Namespace du détail |
|---|---|---|
| `wsman` | `s:Sender` | `schemas.dmtf.org/wbem/wsman/1/wsman.xsd` |
| `wsaddressing` | `s:Sender` | addressing **2004/08** |
| `directory` | `s:Receiver` | IdentityManagement/DirectoryAccess |
| `transfer` | `s:Sender` | ws/2004/09/transfer |
| `enumeration` | `s:Sender` | ws/2004/09/enumeration |

Deux constats s'imposent, tous deux vérifiables par simple recherche.

- **`TypedFaults` n'est appelée par aucun handler.** Elle est exposée sur
  `BaseHandler.typed_faults` (`classes/handlers/base.py:28`) et jamais
  déréférencée ailleurs. Toutes les fautes réellement émises passent par
  `FaultBuilder`.
- **Les seize constantes de noms de `src/faults/fault_codes.py:6-24` ne sont
  importées nulle part.** Seules les quatre constantes de namespace du haut
  du fichier (`:1-4`) le sont, par `typed_faults.py:4-10`. Les noms
  `CannotProcessFilter`, `EncodingLimit`, `FragmentDialectNotSupported`,
  `SchemaValidationError`, `AccessDenied`, `DestinationUnreachable`,
  `EndpointUnavailable`, `ActionNotSupportedFault`, `UnwillingToPerform`,
  `InvalidRepresentation`, `InvalidEnumerationContext`, `TimedOut`,
  `UnableToRenew`, `InvalidExpirationTime`,
  `FilterDialectRequestedUnavailable` et `EnumerationContextLimitExceeded`
  sont donc du vocabulaire déclaré, pas du vocabulaire émis.

> **Dérive documentaire à corriger.**
> `documentation/03-protocole.md:240-249` annonce des codes
> `DirectoryError`, `InsufficientAccessRights`, `ConstraintViolation`,
> `ObjectClassViolation`, `EntryAlreadyExists`, `NoSuchObject` dans
> `src/faults/fault_codes.py`. **Aucun de ces six noms n'est présent dans le
> fichier.** Ce qui circule réellement, c'est le `da:ShortError` que chaque
> handler choisit librement, sous forme de chaîne littérale.

Liste exhaustive des `da:ShortError` réellement émis, relevée handler par
handler sous `classes/handlers/` :

| `ShortError` | Émis par | Ligne |
|---|---|---|
| `CreateFailed` | `create.py` | 40 |
| `ModifyFailed` | `modify.py` | 35 |
| `DeleteFailed` | `delete.py` | 36 |
| `InvalidRequest` | `delete.py`, `modify.py` | 25, 26 |
| `ActionNotSupported` | `crud.py`, `transfer.py` | 29, 25 |
| `SchemaError` | `schema.py` | 36 |
| `CannotProcessFilter` | `search.py` | 23 |
| `SubscribeFault` | `subscribe.py` | 31 |

Seul `CannotProcessFilter` coïncide avec un nom déclaré dans
`src/faults/fault_codes.py`, et encore, par recopie littérale, pas par
import de la constante. C'est exactement le genre d'écart qu'un audit de
parité doit réduire : le vocabulaire de faute doit venir d'un seul endroit.

### Le chemin d'erreur du dispatcher, et son point mortel

`ADWSDispatcher.dispatch` couvre trois cas
(`classes/handlers/dispatcher.py:20-35`) :

```python
try:
    xml_request = record.payload_to_xml()
    context = RequestContext.from_xml(xml_request)
    ...
    return self._encode_response(self._invoke(context))
except ADWSException as e:
    return self._encode_response(self._fault(context, e.message))
except Exception as e:
    self.logger.exception("[DISPATCH] unexpected failure")
    return self._encode_response(self._fault(context, str(e)))
```

`_fault` récupère le `MessageID` s'il existe :

```python
relates_to = context.message_id if context else ""
return SoapEnvelope.fault(relates_to, "s:Receiver", message)
```

(`classes/handlers/dispatcher.py:52-55`). Le `if context else ""` est le
point mortel du protocole. Si l'exception survient **avant** que `context`
soit affecté, donc pendant `payload_to_xml` ou pendant `from_xml`, la faute
part avec `<a:RelatesTo></a:RelatesTo>` **vide**. PowerShell traite alors la
réponse comme non sollicitée et l'ignore : la cmdlet reste bloquée jusqu'à
son propre délai d'expiration, et le journal serveur ne montre aucune
anomalie au-delà de l'exception initiale.

Ce cas n'est pas théorique, il est présent deux fois dans `adws.log` :

- 09:36:27,244 : `UnicodeDecodeError` dans `build_dictionary` en lisant la
  table de session (`src/nettcp/protocol2xml.py:38`) : la faute part avec un
  `RelatesTo` vide, 793 octets.
- 10:00:04,643 : `ValueError: Failed to parse request XML: unbound prefix`
  levée par `RequestContext.from_xml` (`classes/parsing/context.py:169`) :
  même situation, 775 octets.

La règle de diagnostic qui en découle : **une cmdlet qui ne rend jamais la
main alors que le serveur a bien répondu signale presque toujours une erreur
en amont du parsing du contexte.** Chercher dans le journal une exception
dont la trace mentionne `payload_to_xml`, `build_dictionary` ou `from_xml`,
pas le handler.

Le correctif structurel est simple et n'a pas encore été appliqué : extraire
le `MessageID` du XML brut par une expression régulière de repli avant de
construire le contexte, afin que `_fault` ait toujours une corrélation à
renvoyer.

## Grille de diagnostic par symptôme

Les tables ci-dessous se lisent de gauche à droite : symptôme observable
côté Windows, couche à suspecter, vérification, correction.

### Transport et sécurité

| Symptôme Windows | Couche | Vérification | Correctif |
|---|---|---|---|
| `remote endpoint has terminated the transport stream` | GSSAPI | ligne `[SECURITY]` en erreur + NTSTATUS au journal | ajouter le SPN `host/<fqdn>` au compte machine |
| `STATUS_NO_SUCH_USER` (`0xC0000064`) côté serveur | Kerberos | `samba-tool spn list "$(hostname -s)$"` | `samba-tool spn add`, puis `klist purge` |
| même erreur, SPN correct | horloge | `timedatectl` vs `w32tm /query /status` | resynchroniser (dérive > 5 min = échec) |
| connexion fermée sans aucune trace serveur | réseau | `ss -tlnp` sur 9389, pare-feu | ouvrir 9389/tcp |
| échange coupé après la 1re réponse | délai socket | `settimeout(2)` en `protocol.py:164` | augmenter le délai si le client tarde |
| gros objet tronqué / token non désencapsulé | cadrage | `_PLAINTEXT_CHUNK` vs `0xFC30` | ne pas relever `_PLAINTEXT_CHUNK` |

### Encodage NMF / WCF

| Symptôme Windows | Couche | Vérification | Correctif |
|---|---|---|---|
| `ADServerDownException` sur une écriture accentuée | WCF decode | journal : `undefined entity` | `escape` limité aux 4 entités XML |
| `UnicodeDecodeError` dans `build_dictionary` | MS-NBFSE | trace mentionnant `protocol2xml.py:38` | payload désynchronisé : vérifier le descellement |
| `not well-formed (invalid token)` à l'encodage | WCF encode | trace `html_parser.py:38` | valeur non échappée injectée dans le XML |
| `unbound prefix` au parsing | SOAP | trace `context.py:169` | préfixe utilisé sans `xmlns:` dans la réponse |
| décodage manuel qui « réussit » sans rien produire | outillage | usage de `dump_records` sur des octets | utiliser `Record.parse` + `print_records` |

### Sérialisation et application

| Symptôme Windows | Couche | Vérification | Correctif |
|---|---|---|---|
| `Élément de fin '…' attendu, trouvé 'ad:distinguishedName'` | rendu | `context.is_imda` vs forme émise | choisir `imda_projection` / `whole_object` |
| objet remonté sans identité | rendu | présence de `distinguishedName` | l'émettre toujours en IMDA |
| `KeyNotFoundException` dès `Get-ADRootDSE` | RootDSE | attribut hors table client (`vendorName`) | ajouter à `_ROOTDSE_DROP` |
| la conversion en énumération en échec sur `LdapSyntax` | syntaxes | valeur émise = OID au lieu du nom | `ldap_syntax_name_for` |
| valeur rejetée à la désérialisation | `xsi:type` | type autre que string/base64Binary | `XSI_TYPE_BY_OID` |
| `__str__ returned non-string (type NoneType)` | LDB | `str` sur un `MessageElement` | dérouler en `bytes` puis décoder |
| `empty base DN at …/partition.c` | recherche | `<adlq:BaseObject>` vide | repli sur `naming_context` |
| énumération silencieusement partielle | pagination | `WARNING` de troncature à 50000 | relever `MAX_RESULTS_PER_CONTEXT` |
| `Invalid or expired enumeration context` | forking | Pull arrivé sur une autre connexion | conserver la connexion, ou persister le cache |
| scope ignoré, recherche trop large | scope | valeur `<adlq:Scope>` hors `Base`/`OneLevel`/`Subtree` | comparer insensiblement à la casse |
| `Insufficient access rights` | AD | reproduire en LDAP direct (`ldbedit`) | droit AD manquant, pas un bug ADWS |
| `Failed to obtain remote address` | Samba | changement self-service de mot de passe | utiliser `-Reset` (limite connue) |

Le cas du scope mérite un mot : `scope_map` n'accepte que les trois clés
exactes `Base`, `OneLevel`, `Subtree` et retombe silencieusement sur
`SCOPE_SUBTREE` (`classes/handlers/enumerate.py:35-40`). Une valeur en
minuscules (observée telle quelle dans `adws.log`, ligne `[ENUMERATE] Scope:
subtree (ldb:2)`) est donc traitée comme `Subtree`. Sans conséquence pour
`subtree`, mais un `base` en minuscules deviendrait une recherche de
sous-arbre complète : plus lent, et sémantiquement faux.

### Découverte et environnement

| Symptôme Windows | Couche | Vérification | Correctif |
|---|---|---|---|
| `Unable to find a default server` | découverte | `nltest /dsgetdc:<domaine>` | vérifier DNS et SRV |
| idem, `nltest` OK mais `/ws` en `1355` | CLDAP Samba | `nltest /dsgetdc:<domaine> /ws` | limite Samba : passer `-Server` |
| ADAC refuse de se connecter | CLDAP Samba | même test `/ws` | utiliser ADUC (`dsa.msc`, LDAP direct) |
| cmdlet bloquée jusqu'au timeout | corrélation | `RelatesTo` vide dans la faute | erreur avant construction du contexte |

Le cas `1355` est structurel et **ne se corrige pas côté serveur** : le
module `ActiveDirectory` et ADAC appellent le DC locator avec
`DS_WEB_SERVICE_REQUIRED`, et Samba ne positionne pas le drapeau
`NBT_SERVER_ADS_WEB_SERVICE` (`0x2000`) dans sa réponse Netlogon/CLDAP. Le
projet fournit le service TCP 9389, pas l'annonce UDP 389. Le contournement
supporté est `-Server`.

### Séquence de diagnostic recommandée

1. Le service écoute-t-il ? `ss -tlnp | grep 9389`, puis `python3
  tools/test/test_adws.py` sur le DC.
2. La logique répond-elle hors réseau ? `python3
  tools/test/test_handlers.py` : si `RelatesTo echoed` échoue, arrêter là,
  rien d'autre ne fonctionnera.
3. Le préambule et Kerberos passent-ils ? Chercher la ligne
  `[SECURITY]` portant `GSSAPI negotiation completed` dans le journal.
4. Le message arrive-t-il jusqu'à un handler ? Chercher `[DISPATCH]
  handler=` : son absence désigne l'encodage ou le parsing.
5. Le handler produit-il une faute ? Chercher `ERROR` puis le
  `da:ShortError` correspondant.
6. Rejouer la suite complète : `Test-ADWS-Sovereign.ps1
  -SkipMutations`, puis sans l'option.

## Journalisation côté serveur

### Configuration effective

Tout part de `Config` (`classes/server/config.py:36-83`). Le journal est
piloté par trois variables d'environnement, lues à la construction :

| Variable | Défaut | Effet | Ligne |
|---|---|---|---|
| `ADWS_LOG_FILE` | `adws.log` | chemin du fichier | `config.py:45` |
| `ADWS_LOG_LEVEL` | `INFO` | niveau du logger `adws` | `config.py:46-47` |
| `ADWS_HOST` | `0.0.0.0` | interface d'écoute | `config.py:41` |
| `ADWS_PORT` | `9389` | port d'écoute | `config.py:42` |

Le service systemd les fixe via `/etc/default/samba-adws`
(`tools/installation/install.sh:81-87`) :
`ADWS_LOG_FILE=/var/log/samba-adws/adws.log` et `ADWS_LOG_LEVEL=INFO`.
L'unité tourne en `WorkingDirectory` = répertoire d'installation, en `root`,
avec `Restart=on-failure` (`tools/installation/samba-adws.service`). Lancé à
la main par `python3 -m src.main`, le fichier `adws.log` est créé dans le
répertoire courant.

`setup_logging` (`classes/server/config.py:50-77`) installe **deux**
handlers sur le logger nommé `adws` :

| Handler | Niveau | Destination | Rotation |
|---|---|---|---|
| `StreamHandler` | `INFO` | stderr → journald | — |
| `RotatingFileHandler` | `DEBUG` | `ADWS_LOG_FILE` | 10 Mo × 5 |

Attention au piège classique : le niveau du **logger**
(`setLevel(self.logging.level)`, `config.py:56`) prime sur celui des
handlers. Le handler fichier est configuré en `DEBUG` (`config.py:71`) mais
ne verra jamais de `DEBUG` tant que `ADWS_LOG_LEVEL` reste à `INFO`. Passer
en verbeux se fait donc **uniquement** par la variable d'environnement, pas
en touchant les handlers.

Format : `%(asctime)s - %(name)s - %(levelname)s - %(message)s`
(`classes/server/config.py:34`). Les modules obtiennent un logger enfant par
`config.get_logger(name)` (`:79-83`) ; en pratique tout le service utilise
`adws.server`, créé une fois dans `ADWSServer.__init__`
(`classes/server/server.py:17`) et transmis au dispatcher puis aux handlers.

### Anatomie d'une session dans le journal

Les préfixes entre crochets sont le vrai index de lecture.

| Préfixe | Émetteur | Signification |
|---|---|---|
| `[LDB]` | `server.py:34-57` | vérification des backends au démarrage |
| `[CONNECTION]` | `connection.py:31-70` | ouverture/fermeture, IP:port du client |
| `[PREAMBLE]` | `protocol.py:33-63` | un record reçu par ligne |
| `[SECURITY]` | `protocol.py:71-104` | upgrade + négociation GSSAPI |
| `[MESSAGES]` | `protocol.py:109-177` | numéro et taille de chaque message |
| `[DISPATCH]` | `dispatcher.py:21-42` | action, MessageID, handler résolu |
| `[<Handler>]` | `base.py:35-37` | cible traitée (`Root DSE` si absente) |
| `[DB]` | `samba_db.py:27` | ouverture paresseuse de `SamDB` |
| `[ENUMERATE]` | `enumerate.py:33-56` | base, filtre, scope, attributs, cardinal |
| `[ENUM]` | `enumeration_registry.py:28-54` | cycle de vie des contextes |
| `[PULL]` / `[RELEASE]` | `pull.py:35`, `release.py:25` | lot rendu, contexte libéré |
| `[CREATE]` / `[MODIFY]` / `[DELETE]` | handlers CRUD | succès et échecs d'écriture |

Extrait authentique d'une connexion complète (`adws.log`, 3 juin 21:24) :

```text
[CONNECTION] ╔═ NEW CLIENT CONNECTION ═╗
[CONNECTION] Client: 172.19.0.3:65106
[PREAMBLE] ◀ VersionRecord received from client
[PREAMBLE] ◀ ModeRecord received from client
[PREAMBLE] ◀ ViaRecord received from client
[PREAMBLE] ◀ KnownEncodingRecord received from client
[PREAMBLE] ◀ UpgradeRequestRecord received (preamble end)
[SECURITY] ▶ Sending UpgradeResponseRecord to client
[SECURITY] → Starting GSSAPI negotiation...
[SECURITY] ✓ GSSAPI negotiation completed
[MESSAGES] ◀ MESSAGE #0 received from client
[MESSAGES] Request payload size: 486 bytes
[DISPATCH] action=…/transfer/Get message_id=urn:uuid:6c656016-…
[DISPATCH] handler=GetHandler
[GetHandler] Processing: 11111111-1111-1111-1111-111111111111
[DB] SamDB connection established
[MESSAGES] ▶ SENDING message #0 to client
[MESSAGES] Response payload size: 6833 bytes (sent to client)
[MESSAGES] ◀ EndRecord received from client
[CONNECTION] ╚═ CONNECTION CLOSED ═╝
```

Cette séquence est le gabarit de référence : toute panne se localise en
trouvant **la dernière ligne atteinte**.

| Dernière ligne vue | Couche fautive |
|---|---|
| pas de `GSSAPI negotiation completed` | Kerberos / SPN |
| message reçu, pas de `[DISPATCH] action=` | encodage WCF ou parsing SOAP |
| `[DISPATCH] action=` sans `[DISPATCH] handler=` | action inconnue du routage |
| `[DISPATCH] handler=` puis `ERROR` | logique du handler ou droits AD |

### Ce qui échappe au logger

Trois flux ne passent pas par `adws`, ce qui explique des « logs manquants
».

- **Le dictionnaire de session.** `build_dictionary` utilise `print`, pas le
  logger (`src/nettcp/protocol2xml.py:33` et `:47`). Chaque message entrant
  écrit donc sur **stdout** une ligne `Dictionary table: N bytes`, suivie
  d'une ligne par chaîne de session. Ces lignes atterrissent dans
  `journalctl` mais **jamais** dans `adws.log`. C'est une source de bruit
  notable sur un DC chargé et, accessoirement, un point d'observation
  gratuit sur le trafic entrant.
- **Le code vendoré.** `src/wcf/records/text.py:61` appelle
  `logging.basicConfig(level=logging.INFO)` à l'import, ce qui configure le
  logger **racine**. Les journaux `DEBUG` de `src/wcf/` et `src/nettcp/`
  (encodage record par record, hexdumps) restent donc muets tant qu'on ne
  relève pas explicitement le niveau racine.
- **Les hexdumps de socket.** `SocketStream` sait tracer les octets lus et
  écrits (`src/nettcp/stream/socket.py:41-49`) mais uniquement si la
  bibliothèque optionnelle `helperlib` est installée **et** le logger en
  `DEBUG`. Sans elle, `print_hexdump` vaut `False` et la trace est
  silencieusement désactivée (`:10-14`).

### Passer en mode verbeux

```bash
sudo sed -i 's/^ADWS_LOG_LEVEL=.*/ADWS_LOG_LEVEL=DEBUG/' /etc/default/samba-adws
sudo systemctl restart samba-adws
sudo journalctl -u samba-adws -f
```

En `DEBUG`, on gagne les lignes `[SEND] <RecordName> (N bytes)`
(`classes/server/protocol.py:187`), les `[MESSAGES]` de `Connection timeout`
(`:117`), la trace du `PreambleEndRecord` reçu (`:134`) et les `Failed to
search DN …` de la boucle de résolution du Get
(`classes/handlers/get.py:240`).

Pour la couche vendorée, il faut en plus relever le logger racine, par
exemple en ajoutant temporairement
`logging.getLogger.setLevel(logging.DEBUG)` juste après l'appel à
`config.setup_logging` (`src/main.py:11`).

### Limites de la journalisation actuelle

Trois manques documentés, tous confirmés dans le code :

- **Pas d'identifiant de process.** Le format
  (`classes/server/config.py:34`) ne contient ni `%(process)d` ni
  identifiant de connexion. Comme le serveur est un `ForkingTCPServer`, les
  lignes de connexions concurrentes s'entrelacent dans le même fichier sans
  moyen de les démêler. Sur un DC réel où PowerShell ouvre une connexion par
  cmdlet, c'est la gêne principale. Ajouter `%(process)d` au format est un
  correctif d'une ligne.
- **Pas de rotation côté journald.** Le `RotatingFileHandler` gère 10 Mo × 5
  (`classes/server/config.py:31-33`), mais la sortie console est dupliquée
  intégralement dans le journal systemd, sans plafond propre.
- **Le corps applicatif n'est jamais journalisé.** Ni la requête XML ni la
  réponse ne sont écrites, à aucun niveau. C'est défendable, les
  `SetPasswordRequest` contiennent des mots de passe en clair, mais cela
  impose l'instrumentation temporaire décrite en début de chapitre pour tout
  incident de sérialisation. Une piste propre serait un niveau `TRACE`
  dédié, écrivant le XML avec un masquage des éléments `NewPassword`,
  `OldPassword` et `unicodePwd`.

Ces trois points sont des candidats naturels pour la phase 5 (performance et
durcissement), au même titre que le repli sur le `MessageID` évoqué au
scénario 4.
