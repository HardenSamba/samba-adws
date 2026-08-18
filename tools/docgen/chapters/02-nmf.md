# Rôle et principes du cadrage .NET Message Framing

## Ce que le cadrage résout

TCP fournit un flux d'octets continu, sans notion de frontière de message. Le
service ADWS, lui, échange des *messages* SOAP discrets. Il faut donc une couche
qui découpe le flux en unités et qui transporte les propriétés de session
indispensables avant même que le premier message n'existe : version du cadrage,
mode de communication, URI de destination, encodage retenu, éventuelle demande
d'élévation de sécurité.

C'est exactement le périmètre du .NET Message Framing Protocol, publié par
Microsoft sous la référence **[MC-NMF]** ; la liaison TCP proprement dite fait
l'objet de **[MS-NMFTB]**. Ce dépôt et `CLAUDE.md` emploient la forme
**[MS-NMF]**, conservée ici par cohérence : c'est le même corpus normatif, et
les sections citées renvoient au document [MC-NMF].

Le cadrage NMF est délibérément minimal. Il ne fait **pas** :

- de corrélation requête/réponse — c'est le rôle de WS-Addressing
 (`<a:MessageID>` / `<a:RelatesTo>`, cf. le chapitre SOAP) ;
- de multiplexage — une connexion transporte un message à la fois, en séquence
 stricte, jamais deux messages entrelacés ;
- de compression — la compacité vient de la couche [MS-NBFX]/[MS-NBFS] ;
- de chiffrement — la confidentialité vient de l'*upgrade* de sécurité, donc de
 GSSAPI/Kerberos ;
- de contrôle de flux applicatif — pas de fenêtre, pas d'accusé de réception
 par message (le seul acquittement est celui du préambule).

## Records, initiateur et receveur

L'unité élémentaire est le **record** : un octet de type, suivi éventuellement
d'une charge utile dont la forme dépend du type. [MS-NMF] distingue deux
familles :

- les **Property Records**, qui portent des propriétés de session (version,
 mode, via, encodage, demande et réponse d'*upgrade*, fin et acquittement de
 préambule) ;
- les **Envelope Records**, qui portent la charge utile applicative
 (`SizedEnvelopeRecord`, `UnsizedEnvelopeRecord`).

Le protocole est **asymétrique** : la grammaire ABNF de [MS-NMF] section 3.1.1.2
définit deux flux distincts, `ProtocolStream-a` de l'initiateur vers le receveur
et `ProtocolStream-b` du receveur vers l'initiateur. Le client Windows est
toujours l'initiateur ; le serveur souverain n'émet jamais de `VersionRecord`,
de `ModeRecord`, de `ViaRecord` ni de `KnownEncodingRecord`.

Dans ce projet, le vocabulaire du code reflète cette asymétrie : la classe
serveur `ProtocolHandler` (`classes/server/protocol.py:21`) ne sait que *lire*
les records de propriété, tandis que la classe cliente `NMFStream`
(`src/nettcp/stream/nmf.py:11`), utilisée uniquement par l'outillage de debug,
sait les *produire*.

## Les quatre modes de cadrage

Le `ModeRecord` fixe la forme du dialogue pour toute la durée de la connexion.
[MS-NMF] section 2.2.3.2 en définit quatre ; la valeur `0x00` est invalide et
`0x05`–`0xFF` est réservée.

| Valeur | Mode | Sens | Enveloppes |
|---|---|---|---|
| `0x01` | Singleton-Unsized | Un message aller, ou une paire requête/réponse | `UnsizedEnvelopeRecord` |
| `0x02` | Duplex | Messages bidirectionnels multiples | `SizedEnvelopeRecord` |
| `0x03` | Simplex | Messages unidirectionnels multiples | `SizedEnvelopeRecord` |
| `0x04` | Singleton-Sized | Un unique message unidirectionnel | flux d'octets brut |

**ADWS utilise exclusivement le mode Duplex (`0x02`).** C'est le mode
qu'impose la liaison `NetTcpBinding` de WCF côté Microsoft (configuration
`ActiveDirectoryWebServicesNetTcpBindingConfiguration`), et c'est celui que le client de debug du dépôt fixe en
dur. La raison est fonctionnelle : une session ADWS enchaîne des dizaines
d'aller-retours sur la même connexion TCP (`Get-ADRootDSE`, puis `Enumerate`,
puis une série de `Pull`, puis `Release`), et l'affinité de session est
indispensable — le cache de contextes d'énumération est un *singleton* de
processus (`src/enumeration/enumeration.py:6-13`), donc lié au processus fils
qui a servi le `Enumerate` (cf. `documentation/03-protocole.md`, section
« Énumération paginée »).

> **Niveau de preuve.** Aucune capture réseau d'un client Windows n'existe dans
> ce dépôt. L'affirmation « le client PowerShell envoie toujours Duplex » est
> déduite de la spécification et du comportement de `NetTcpBinding`, pas d'une
> trace observée. Ce qui est vérifié dans le code, c'est que le serveur
> souverain ne traite correctement que ce mode.

Dans l'implémentation, l'énumération `Mode` est déclarée en
`src/nettcp/nmf.py:187-191` avec les quatre valeurs. Le client de debug fixe
`ModeRecord(Mode=2)` en dur (`src/nettcp/stream/nmf.py:22`). Côté serveur,
`ProtocolHandler.handle_preamble` journalise la réception du `ModeRecord`
(`classes/server/protocol.py:43-44`) mais **ne vérifie pas** la valeur : une
session annoncée Simplex ou Singleton-Sized serait traitée comme du Duplex.

## Position dans l'empilement, avant et après l'*upgrade*

Le point le plus contre-intuitif du cadrage ADWS est que la couche NMF se
retrouve **des deux côtés** de la couche de sécurité. Le préambule circule en
clair ; l'*upgrade* « application/negotiate » installe un tunnel GSSAPI ; et
tous les records NMF ultérieurs — y compris `PreambleEndRecord`,
`PreambleAckRecord`, `SizedEnvelopeRecord` et `EndRecord` — transitent
*à l'intérieur* de ce tunnel.

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
(`classes/server/protocol.py:96`), et c'est ce flux déchiffrant qui est passé à
`nmf.Record.parse_stream` dans la boucle de messages
(`classes/server/protocol.py:114`). L'octet de type de record lui-même est donc
lu à travers `GENSECStream.read(1)`, c'est-à-dire après désencapsulation.

Le schéma d'empilement de `documentation/03-protocole.md:8-21` place GSSAPI
*au-dessus* de « Net.tcp framing (MS-NMF) » : c'est vrai du préambule, faux des
enveloppes. La formulation de [MS-NMF] est plus juste : une fois l'*upgrade*
accepté, **tous les octets suivants du flux protocolaire passent par le flux
élevé**.

# Encodage des primitives : entiers variables et chaînes

## L'entier à taille variable (« Record Size Encoding »)

Toutes les longueurs de NMF utilisent le même encodage, décrit en [MS-NMF]
section 2.2.2. Il s'agit d'un entier non signé en base 128, **groupes de poids
faible en premier**, chaque octet portant sept bits de donnée et un bit de
continuation en position de poids fort.

Algorithme d'encodage :

- **1.** Tant que la valeur restante dépasse `0x7F`, émettre
 `(valeur & 0x7F) | 0x80` puis décaler la valeur de 7 bits à droite.
- **2.** Émettre le reste, `valeur & 0x7F`, sans bit de continuation.

Algorithme de décodage :

- **1.** Lire un octet. Accumuler `(octet & 0x7F) << (7 * rang)`.
- **2.** Si le bit `0x80` est positionné, incrémenter le rang et recommencer ;
 sinon, l'entier est complet.

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

## Exemples chiffrés, vérifiés contre le code du dépôt

Les valeurs ci-dessous ont été produites en exécutant `varint_encode`
(`src/nettcp/nmf.py:78`) et `varint.stream` (`src/nettcp/nmf.py:60`) du dépôt.
Elles ne sont pas reconstituées à la main.

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

Lecture de `ff ff 03` : premier octet `0xFF` → bits 0-6 = `0x7F`, continuation ;
deuxième octet `0xFF` → bits 7-13 = `0x7F`, continuation ; troisième octet
`0x03` → bits 14-20 = `3`, fin. Total :
`0x7F | (0x7F << 7) | (3 << 14)` = `65535`.

## Écarts de l'implémentation Python

Le décodeur du dépôt s'écarte de la spécification sur trois points, tous
vérifiés par exécution.

**Aucune borne sur le nombre d'octets.** `varint_stream`
(`src/nettcp/nmf.py:60-73`) boucle sur `while True` et ne sort que sur un octet
nul ou un octet sans bit de continuation. Un varint de sept octets est accepté
sans broncher : l'entrée `80 80 80 80 80 80 01` est décodée en
`0x40000000000`, très au-delà du plafond de cinq octets de la spécification.
Comparativement, le décodeur de la couche WCF, `MultiByteInt31.parse`
(`src/wcf/datatypes.py:20-31`), borne explicitement sa boucle par `range(5)`
(ligne 23) et traite l'octet manquant comme une fin de flux. Cette
absence de borne côté NMF est un vecteur de déni de service : un pair
malveillant qui émet un flux continu d'octets `0x80` fait diverger l'entier
Python — de taille arbitraire — jusqu'à épuisement mémoire du processus fils.
C'est un point de durcissement à traiter en phase 5.

**L'octet nul termine le varint.** Les deux décodeurs contiennent
`if not d: break` (`src/nettcp/nmf.py:50-51` et `:65-66`), ce qui interrompt la
lecture sur un `0x00` sans l'accumuler. Conséquence : la séquence `80 00`,
malformée au sens de la grammaire ABNF (le dernier octet doit être `%x01-7F`),
est décodée en `0` au lieu d'être rejetée. Cette tolérance est empruntée à
l'implémentation d'origine ; elle n'a pas d'effet observé avec un client Windows
conforme, mais elle relâche la validation.

**Troncature silencieuse à l'encodage au-delà de 2^35.** `varint_encode`
(`src/nettcp/nmf.py:78-100`) ne comporte que cinq branches ; la dernière émet
`(val >> 28) & 0x7f` comme cinquième octet. La valeur `0x7FFFFFFFF` (2^35 − 1)
fait encore l'aller-retour correctement ; `0x800000000` est encodée en
`80 80 80 80 00` et se relit en `0`. Aucune exception n'est levée. Comme les
messages ADWS réels sont de l'ordre du kilo-octet, ce cas est inatteignable en
production, mais il n'est pas gardé.

## Chaînes de caractères

NMF ne connaît qu'une seule forme de chaîne : **un varint de longueur en
octets, suivi des octets UTF-8**. Pas de terminateur nul, pas de marque
d'ordre d'octets, pas d'échappement ; la grammaire ABNF n'admet que des
séquences UTF-8 valides.

Trois records du dépôt portent une chaîne — `ViaRecord`
(`src/nettcp/nmf.py:313-318`), `UpgradeRequestRecord` (`:328-333`) et
`FaultRecord` (`:379-384`). Le `ExtensibleEncodingRecord` en porte une
également selon la spécification, mais il n'est pas implémenté ici.

L'implémentation matérialise ce couple longueur/valeur par une liste `fields`
de deux entrées, la seconde renvoyant à la première par son nom :

```python
class ViaRecord(Record):
    code = 0x02
    fields = [
        ('ViaLength', varint),
        ('Via', pt(utf8, 'ViaLength')),
    ]
```

L'auxiliaire `pt` (`src/nettcp/nmf.py:34-40`) est un `functools.partial` enrichi
qui propage les attributs `encode` et `stream` du décodeur, de sorte que le
lecteur générique `Record.parse_stream` (`src/nettcp/nmf.py:255-273`) sache
appeler `utf8_stream('ViaLength', obj, stream)` et lire exactement `ViaLength`
octets (`src/nettcp/nmf.py:111-113`).

> **Attention — longueur en octets, pas en caractères.** Le constructeur
> `ViaRecord(ViaLength=len(self.url), Via=self.url)`
> (`src/nettcp/stream/nmf.py:23`) mesure la longueur d'une chaîne Python, donc
> un nombre de *caractères*. Pour une URL `net.tcp` purement ASCII — le seul
> cas rencontré — les deux coïncident. Une URL comportant un caractère
> non-ASCII produirait un `ViaLength` inférieur au nombre d'octets réellement
> émis et désynchroniserait le flux. Ce code n'étant utilisé que par
> l'outillage client de debug, le serveur n'est pas exposé ; le correctif serait
> `len(self.url.encode('utf-8'))`.

# Catalogue exhaustif des records

## Table maîtresse

Les valeurs d'octet ci-dessous sont celles déclarées dans `src/nettcp/nmf.py` et
concordent avec la table normative de [MS-NMF] section 2.2.1. La colonne
« Ligne » renvoie à la déclaration de la classe correspondante.

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
(`SizedEnvelopedMessageRecord` pour *Sized Envelope Record*) : c'est un héritage
de la bibliothèque vendorisée d'origine, conservé tel quel pour ne pas casser
les imports. Ces deux noms figurent d'ailleurs dans le `__all__` du module
(`src/nettcp/nmf.py:11-25`), qui expose onze classes de record — `FaultRecord`
n'y est pas listé, ce qui est cohérent avec le fait qu'il ne soit jamais
utilisé.

L'enregistrement des types se fait par introspection : `register_types`
(`src/nettcp/nmf.py:394-406`) parcourt les classes du module et appelle
`Record.register` pour chaque sous-classe de `Record`. Un contrôle exécuté sur
le dépôt donne la liste effective des codes enregistrés :
`0, 1, 2, 3, 5, 6, 7, 8, 9, 10, 11, 12`. **Le code `0x04` est absent** : la
classe `ExtensibleEncodingRecord` n'existe pas dans ce projet. Un client qui
annoncerait un encodage extensible (une chaîne de type MIME au lieu d'un octet
connu) provoquerait un `KeyError` dans `Record.parse_stream`
(`src/nettcp/nmf.py:262`) et la fermeture immédiate de la connexion. Ce n'est
pas un problème pratique — le client PowerShell utilise toujours le
`KnownEncodingRecord` — mais c'est un écart formel avec la règle ABNF
`EncodingRecord = KnownEncodingRecord / ExtensibleEncodingRecord`.

## VersionRecord : ne pas confondre deux versions

`VersionRecord` porte deux octets bruts. La grammaire ABNF est catégorique :
`MajorVersionNumber = %x01` et `MinorVersionNumber = %x00`. La version du
*cadrage* est donc figée à **1.0**.

Il ne faut pas la confondre avec la version du *service* ADWS, renvoyée par
l'action applicative `GetVersion` (cf. `documentation/04-handlers.md`). Quatre
plans de versionnement cohabitent et ne doivent jamais être confondus :

| Plan | Valeur | Ancrage |
|---|---|---|
| Cadrage NMF | major 1, minor 0 | `src/nettcp/nmf.py:298-303` |
| Handshake NNS | major 1, minor 0 | `src/nettcp/stream/negotiate.py:53-54` |
| Service ADWS (Microsoft) | 1.1 | Service ADWS Microsoft |
| Service ADWS (ce projet) | Server 1.0.0, Protocol 1.1 | `classes/handlers/get_version.py:9-10` |

Microsoft déclare `VersionMajor = 1`, `VersionMinor = 1` et
`VersionString = "Active Directory Web Services v1.1"` ; le handler souverain,
lui, annonce `<ca:Server>1.0.0</ca:Server>` et ne reprend `1.1` que dans
`<ca:Protocol>`. L'effet de cet écart sur le module PowerShell n'a pas été
observé dans ce dépôt.

Le serveur souverain n'inspecte ni `MajorVersion` ni `MinorVersion`
(`classes/server/protocol.py:41-42` se contente d'un message de journal) et
n'émet donc jamais le fault `UnsupportedVersion`.

## KnownEncodingRecord : la table complète

[MS-NMF] section 2.2.3.3 définit neuf valeurs ; `0x09`–`0xFF` sont réservées.

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

L'énumération Python correspondante est en `src/nettcp/nmf.py:178-184`. Elle ne
déclare **que** les valeurs 3 à 8 ; les trois encodages SOAP 1.1 sont absents.
Comme le champ est décodé par `as_enum('B', KnownEncoding)`
(`src/nettcp/nmf.py:153-170`), une valeur hors énumération lève un `ValueError`
lors de la construction du membre, exception qui remonte jusqu'au
`except Exception` de `handle_preamble` (`classes/server/protocol.py:65`) et
provoque la fermeture de la connexion sans réponse. Autrement dit, **ce serveur
rejette de fait tout encodage SOAP 1.1**, ce qui est cohérent avec ADWS mais
n'est pas une validation explicite : c'est un effet de bord du typage.

**ADWS impose la valeur `0x08`**, binaire avec dictionnaire in-band. Le client
de debug la fixe en dur (`KnownEncodingRecord(Encoding=8)`,
`src/nettcp/stream/nmf.py:24`) et le format de la charge utile le confirme :
tout message applicatif commence par un `MultiByteInt31` donnant la taille de la
table de dictionnaire de session (`src/nettcp/protocol2xml.py:32-35`), et le
dispatcher préfixe systématiquement ses réponses d'un octet `0x00` correspondant
à une table vide (`classes/handlers/dispatcher.py:49`). Ce préfixe n'existerait
pas avec l'encodage `0x07`.

> Le serveur **ne vérifie pas** la valeur reçue : `handle_preamble` se contente
> de journaliser (`classes/server/protocol.py:47-48`). Un client qui
> annoncerait `0x03` (SOAP 1.2 texte) serait accepté au préambule, puis
> échouerait au premier message quand le décodeur binaire tenterait de lire une
> table de dictionnaire dans du XML textuel. Le fault normatif
> `ContentTypeInvalid` n'est jamais émis.

## Les records sans charge utile

`UpgradeResponseRecord` (`0x0A`), `PreambleAckRecord` (`0x0B`),
`PreambleEndRecord` (`0x0C`) et `EndRecord` (`0x07`) se réduisent à leur octet
de type. Dans le code, cela se traduit par une classe sans attribut `fields`,
qui hérite donc de `Record.fields = []` (`src/nettcp/nmf.py:222`). Leur méthode
`to_bytes` produit un unique octet, ce qui explique la comparaison directe
`if d != UpgradeResponseRecord.to_bytes` du client de debug
(`src/nettcp/stream/nmf.py:34`).

## FaultRecord : le vocabulaire normatif

`FaultRecord` transporte un URI UTF-8 précédé de sa longueur ; la spécification
interdit une longueur nulle. Les noms de fault définis par [MS-NMF]
section 2.2.5.1 vivent dans l'espace de noms
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
> `EndpointNotFound` dans `src/` et `classes/` ne renvoie aucun résultat. La table n'est donc pas présentée comme exhaustive :
> d'autres noms de fault de cadrage circulent dans la littérature WCF sans avoir
> pu être corroborés ici, et ils ne sont volontairement pas repris.

> **État de cette implémentation :** la classe `FaultRecord`
> (`src/nettcp/nmf.py:379-384`) sait *décoder* un fault entrant, mais aucun
> point du dépôt ne l'instancie. Une recherche exhaustive sur `FaultRecord` dans
> les sources Python ne remonte que sa déclaration (`src/nettcp/nmf.py:379`).
> **Aucune des chaînes ci-dessus n'est connue, produite ni consommée par le
> serveur souverain.** Elles sont documentées ici parce qu'elles peuvent
> apparaître dans une capture `tcpdump` en provenance d'un ADWS Microsoft, et
> parce qu'elles constituent la feuille de route naturelle du durcissement de la
> couche de cadrage.

# Le préambule : séquence, ordre et validation

## La grammaire normative

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
encodage, puis zéro ou plusieurs *upgrades*, puis fin de préambule. Ensuite, les
règles `UpgradeRequest` et `UpgradeResponse` sont suivies de `Octets` : la
négociation de sécurité proprement dite n'est pas cadrée par NMF, elle est un
flux d'octets opaque inséré dans la séquence. C'est là que s'intercale le
cadrage [MS-NNS] côté Microsoft, ou `samba.gensec` côté serveur souverain.

## Hexdump annoté d'un préambule client complet

Le fragment ci-dessous a été produit en instanciant les classes du dépôt pour
un Via réaliste (`net.tcp://dc1.samba.local:9389/ActiveDirectoryWebServices/`
`Windows/Resource`, 74 octets). Il fait 106 octets et correspond exactement à ce
qu'un client PowerShell envoie en ouverture de session.

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
bloc. Il est envoyé plus tard, après l'établissement du contexte de sécurité,
et voyage donc chiffré (voir la section suivante).

## Le Via : forme, endpoints, et ce que le serveur en fait

La forme canonique de l'URI Via est reconstituable à partir de la référence
de référence. les constantes du service ADWS Microsoft définit
`WcfNetEndpointPrefix = "net.tcp://"`,
`WcfNetEndpointSuffix = ":9389/ActiveDirectoryWebServices"`, les préfixes
d'authentification `"Windows/"` et `"UserName/"`, et les noms d'endpoints.
la configuration d’hôte du service ADWS Microsoft montre comment ils sont assemblés.

| Chemin après `/ActiveDirectoryWebServices/` | Contrat WCF | Ligne |
|---|---|---|
| `Windows/Resource` | `IResource` | Service ADWS Microsoft |
| `Windows/ResourceFactory` | `IResourceFactory` | Service ADWS Microsoft |
| `Windows/Enumeration` | `IEnumeration` | Service ADWS Microsoft |
| `Windows/AccountManagement` | `IActiveDirectoryAccountManagement` | Service ADWS Microsoft |
| `Windows/TopologyManagement` | `IActiveDirectoryTopologyManagementV1` | Service ADWS Microsoft |
| `mex` | `IMetadataExchange` | Service ADWS Microsoft |

L'endpoint `mex` est le seul à ne pas porter de préfixe d'authentification : il
est ajouté hors de la boucle sur les descripteurs de liaison, avec
`MetadataExchangeBindings.CreateMexTcpBinding`.

Le préfixe `UserName/` n'est instancié que si un certificat serveur a pu être
provisionné ; il correspond à la liaison
`TransportWithMessageCredential`. Le serveur souverain n'implémente pas ce
chemin — seule l'authentification intégrée Windows/Kerberos est supportée.

Une trace d'un endpoint apparaît d'ailleurs dans notre propre code : le handler
`SubscribeHandler` renvoie
`net.tcp://localhost:9389/ActiveDirectoryWebServices/Windows/AccountManagement`
comme adresse de gestionnaire d'abonnement
(`classes/handlers/subscribe.py:16`).

**Ce que le serveur souverain fait du Via : rien.** Le record est lu, son champ
`Via` est peuplé, et `handle_preamble` se contente de journaliser
« ViaRecord received from client » (`classes/server/protocol.py:45-46`). Aucune
comparaison de nom d'hôte, aucune validation de chemin, aucun routage. Une
recherche sur `ViaRecord` dans les sources ne remonte que la déclaration de la
classe et le constructeur du client de debug.

Les conséquences sont à connaître :

- **Tous les chemins sont acceptés**, y compris un chemin inexistant ou vide.
 Le fault `EndpointNotFound` n'est jamais émis.
- **Le routage se fait exclusivement sur l'action SOAP**, pas sur l'endpoint :
 `HandlerRegistry.resolve(action)` (cf. `documentation/04-handlers.md`)
 décide seul du handler. Un `Enumerate` envoyé sur l'endpoint `Resource`
 fonctionnerait, là où un ADWS Microsoft le refuserait au niveau du contrat
 WCF.
- **Le nom d'hôte du Via n'est pas corrélé au SPN Kerberos.** C'est GSSAPI qui
 tranche l'identité du service ; le Via n'est pas une donnée de sécurité ici.

## L'UpgradeRequestRecord et le déclenchement de l'élévation

[MS-NMF] section 2.2.3.7 identifie deux chaînes d'*upgrade* connues :

| Chaîne | Longueur | Protocole |
|---|---|---|
| `application/negotiate` | 21 octets | SPNEGO, RFC 4178 |
| `application/ssl-tls` | 19 octets | TLS, RFC 5246 |

ADWS utilise **`application/negotiate`**. La chaîne est un simple sélecteur :
elle indique au receveur que, s'il accepte, le flux doit être remis à une
implémentation SPNEGO qui négociera un mécanisme (Kerberos en pratique, NTLM en
repli) et installera un contexte de sécurité. Rien dans NMF ne décrit ce qui se
passe ensuite : la règle ABNF `UpgradeRequest = UpgradeRequestRecord Octets`
délègue entièrement.

Le déclenchement est donc purement conventionnel : c'est la présence du record
`0x09` avant `PreambleEndRecord` qui bascule la connexion. Côté serveur
souverain, la mécanique est en trois temps
(`classes/server/protocol.py:84-98`) :

- **1.** Vérifier que le code du record vaut bien `0x09`, sinon échouer.
- **2.** Répondre un `UpgradeResponseRecord` nu (`0x0A`).
- **3.** Remplacer le flux par un `GENSECStream` et lancer
 `negotiate_server`.

> **Le contenu de la chaîne n'est jamais examiné.** Le test de
> `classes/server/protocol.py:84` porte sur le code du record, pas sur
> `obj.UpgradeProtocol`. Un client demandant `application/ssl-tls` recevrait un
> `UpgradeResponseRecord` puis se verrait imposer une négociation SPNEGO, et
> échouerait de façon opaque. Le fault normatif `UpgradeInvalid` n'est pas émis.
> Ajouter un contrôle explicite sur la chaîne est un correctif d'une ligne qui
> améliorerait nettement le diagnostic.

## Où se situent réellement PreambleEnd et PreambleAck

C'est le point le plus souvent mal compris du préambule ADWS. La grammaire
place `PreambleEndRecord` après les *upgrades* ; comme l'*upgrade* a installé un
tunnel, ce record et son acquittement circulent **dans le tunnel**.

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
(`src/nettcp/stream/nmf.py:37-42`). Côté serveur, le `0x0C` n'est pas traité en
phase 1 mais dans la boucle de messages, sur le flux déchiffrant :
`classes/server/protocol.py:133-138` intercepte le code `0x0c`, répond
`PreambleAckRecord` puis boucle. La branche `0x0c` de `handle_preamble`
(`classes/server/protocol.py:55-60`) n'est atteinte que par un client qui
n'aurait pas demandé d'*upgrade* — cas qui échoue immédiatement après, puisque
`handle_security` exige un record `0x09`.

## Ce que le serveur valide, et ce qu'il ne valide pas

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

La dernière ligne est la propriété de sécurité essentielle : **il n'existe pas
de chemin non authentifié**. Une connexion qui enverrait un préambule complet
suivi de `PreambleEndRecord` sans `UpgradeRequestRecord` verrait
`handle_preamble` émettre un `PreambleAckRecord`
(`classes/server/protocol.py:57-58`) puis renvoyer `True` ; `handle_security`
lirait alors le record suivant, constaterait qu'il ne vaut pas `0x09` et
renverrait `False` (`classes/server/protocol.py:84-86`).
`ConnectionHandler.handle` interrompt le traitement
(`classes/server/connection.py:50-52`) et la connexion est fermée. L'acquittement
de préambule est donc bien émis en clair dans ce cas dégénéré, mais **aucun
message applicatif ne peut suivre** : la phase 3 n'est jamais atteinte.

# Cadrage des messages applicatifs

## Anatomie du SizedEnvelopeRecord

En mode Duplex, chaque message applicatif est exactement un record `0x06` :

```text
┌──────┬────────────────┬──────────────────────────────────┐
│ 0x06 │ varint Size    │ Size octets de charge utile      │
└──────┴────────────────┴──────────────────────────────────┘
```

La charge utile est **opaque pour NMF**. Après désencapsulation GSSAPI, c'est
du XML binaire WCF précédé de la table de dictionnaire de session [MS-NBFSE].

Dans le dépôt, la classe est déclarée en `src/nettcp/nmf.py:348-353` avec le
couple de champs habituel `('Size', varint)` puis
`('Payload', pt(raw_bytes, 'Size'))`. Son `__repr__` est volontairement tronqué
aux dix premiers octets de la charge utile (`src/nettcp/nmf.py:355-361`) pour ne
pas noyer les journaux. La méthode `payload_to_xml`
(`src/nettcp/nmf.py:363-373`) fait le pont vers la couche WCF : elle construit
le dictionnaire in-band, parse les records NBFX et rend du XML texte.

Côté émission, le serveur construit le record dans la boucle de messages
(`classes/server/protocol.py:153-157`) à partir des octets rendus par le
dispatcher, puis l'écrit via `send_record`
(`classes/server/protocol.py:183-188`).

## Hexdump annoté d'un SizedEnvelopeRecord

L'exemple ci-dessous est le cadrage réel — octets produits par le code du
dépôt — d'une enveloppe SOAP minimale
`<s:Envelope …><s:Body/></s:Envelope>` encodée en WCF binaire. Treize octets au
total, dont onze de charge utile.

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
`src/wcf/dictionary.py` — vérifiés par exécution : `dictionary[2]` vaut
`Envelope`, `dictionary[4]` vaut `http://www.w3.org/2003/05/soap-envelope` et
`dictionary[14]` vaut `Body`. L'ensemble des treize octets a été régénéré en
faisant passer l'enveloppe par `XMLParser.parse` (`src/wcf/xml2records.py:64`)
puis `dump_records` (`src/wcf/records/__init__.py:90`), puis en cadrant le
résultat avec `SizedEnvelopedMessageRecord` — il ne s'agit pas d'une
reconstitution manuelle.

| Octet | Classe WCF | Ancrage |
|---|---|---|
| `0x56` | `PrefixDictionaryElementSRecord` | `src/wcf/records/elements.py:321-334` |
| `0x0B` | `DictionaryXmlnsAttributeRecord` | `src/wcf/records/attributes.py:255-256` |
| `0x01` | `EndElementRecord` | `src/wcf/records/base.py:151-152` |

Les classes `PrefixDictionaryElement*Record` ne sont pas écrites à la main :
elles sont fabriquées par une boucle `for c in range(0x44, 0x5D + 1)` qui
associe à chaque octet la lettre `chr(c - 0x44 + ord('a'))`. Pour `s`, on
obtient bien `0x44 + 18 = 0x56`. Le détail de cet encodage relève du chapitre
[MS-NBFX] ; il est donné ici pour montrer où s'arrête la responsabilité du
cadrage.

## Le préfixe de dictionnaire, marqueur de l'encodage 0x08

L'octet `0x00` en tête de charge utile n'est pas décoratif : c'est le
`MultiByteInt31` de taille de la table de dictionnaire de session, imposé par
l'encodage `0x08`. Trois points d'ancrage dans le dépôt :

- `src/nettcp/protocol2xml.py:32-35` lit cette taille puis la table avant tout
 autre record ;
- `src/nettcp/nmf.py:369` appelle `build_dictionary` sur la charge utile reçue
 avant de parser les records ;
- `classes/handlers/dispatcher.py:49` préfixe la réponse encodée par
 `b"\x00"`, c'est-à-dire une table vide.

Ce projet **n'émet jamais de table de dictionnaire dynamique** : il n'utilise
que la table statique Microsoft (`src/wcf/dictionary.py`), qui compte 487
entrées, toutes d'identifiant **pair**, de `0` (`mustUnderstand`) à `972`
— chiffres relevés par exécution. Le compteur `idx` de `protocol2xml.py` part
de `1` et progresse de 2, donc les chaînes de session reçues d'un client
occupent les identifiants **impairs** : les deux espaces ne peuvent pas
entrer en collision. Le serveur sait donc *lire* une table dynamique envoyée par
le client, mais jamais en produire. C'est une limite déjà consignée dans
`documentation/03-protocole.md:96`.

## Taille du record contre taille des trames de sécurité

Une confusion fréquente consiste à croire que la taille annoncée dans le varint
d'un `SizedEnvelopeRecord` correspond à ce qui passe sur le fil en une fois. Il
n'en est rien : le record NMF est *à l'intérieur* du tunnel, et le tunnel a ses
propres trames, plus petites.

| Grandeur | Valeur | Ancrage |
|---|---|---|
| Bloc de clair `_PLAINTEXT_CHUNK` | `0xF000` = 61 440 | `src/nettcp/stream/gssapi.py:17` |
| Découpe à l'émission, via `wrap` | par `_PLAINTEXT_CHUNK` | `src/nettcp/stream/gssapi.py:148-152` |
| Plafond d'une trame post-handshake | `0xFC30` = 64 560 | `src/nettcp/stream/negotiate.py:60-62` |
| En-tête de trame post-handshake | 4 octets, `uint32` LE | `src/nettcp/stream/negotiate.py:61` |
| En-tête de trame de handshake | 5 octets, type + 1 + 1 + `uint16` BE | `src/nettcp/stream/negotiate.py:24-30` |
| Marge disponible pour le jeton GSS | 3 120 octets (`0xFC30 − 0xF000`) | calcul |
| Surcoût réel annoncé du jeton | ~ 60 octets | commentaire `gssapi.py:12-16` |

Le commentaire de `src/nettcp/stream/gssapi.py:12-16` explique la contrainte :
le jeton Kerberos AES CFX ajoute en-tête, *confounder*, en-tête dupliqué et
HMAC, soit environ soixante octets ; si le bloc de clair collait au plafond de
trame, un seul jeton chevaucherait sur deux trames et le lecteur, qui suppose
« une trame = un jeton », échouerait au désencapsulage. Le choix de `0xF000`
laisse une marge de 3 120 octets, très supérieure au surcoût constaté — un
arrondi confortable plutôt qu'une valeur ajustée au plus juste.

Attention à ne pas confondre les deux classes de flux du dépôt :
`GSSAPIStream` (client de debug) chiffre avec `encrypt`/`decrypt`
(`src/nettcp/stream/gssapi.py:55` et `:65`), tandis que `GENSECStream` — le seul
flux utilisé côté serveur — passe par `wrap`/`unwrap` de `samba.gensec`
(`src/nettcp/stream/gssapi.py:150` et `:160`). Les deux partagent la même
constante `_PLAINTEXT_CHUNK` et le même `NegotiateStream` sous-jacent.

Conséquence pratique : une réponse `Get-ADUser` de 150 kio produit **un**
`SizedEnvelopeRecord` dont le varint vaut 153 600 environ, découpé en trois
blocs de clair, donc trois trames NNS. Réciproquement, à la lecture,
`GENSECStream.read(count)` accumule dans `_readcache` autant de trames que
nécessaire pour satisfaire la demande
(`src/nettcp/stream/gssapi.py:162-170`) : le lecteur de records ne voit jamais
cette découpe.

## Quotas de taille : Microsoft contre ce projet

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
`raw_bytes_stream` (`src/nettcp/nmf.py:123-125`) à demander autant d'octets à
`GENSECStream.read(count)`, qui bouclerait sur les trames jusqu'à épuisement
mémoire du processus fils. C'est, avec le varint non borné, le deuxième point
de durcissement identifié pour la phase 5.

Le parallélisme mérite la même prudence. La valeur `max_connections = 128` de
`classes/server/config.py:17` est déclarée mais **jamais lue** : le constructeur
de `socketserver.ForkingTCPServer` (`classes/server/server.py:25-29`) ne reçoit
que l'adresse, la classe de handler et `bind_and_activate=False`. Le seul
plafond effectif est donc `ForkingMixIn.max_children`, dont la valeur par défaut
dans la bibliothèque standard Python est 40 et que ce projet ne surcharge pas.
Il n'existe pas non plus d'équivalent au `MaxConcurrentCalls` de Microsoft,
puisqu'un processus fils ne traite jamais qu'un message à la fois.

## Le cas UnsizedEnvelopeRecord

Le mode Singleton-Unsized emploie le record `0x05`, dont la charge utile est une
suite de fragments `(varint taille, octets)` terminée par un octet `0x00` — la
règle ABNF est
`UnsizedEnvelopeRecord = UnsizedEnvelopeRecordType 1*(EncodedSize Octets) Terminator`
avec `Terminator = %x00`. C'est un cadrage de type *chunked*, utile quand
l'émetteur ne connaît pas la taille totale à l'avance.

ADWS n'en fait jamais usage, et l'état du code le confirme :

- la classe `UnsizedEnvelopedMessageRecord` existe
 (`src/nettcp/nmf.py:387-391`) avec un champ `DataChunks` ;
- l'encodeur est explicitement neutralisé : `data_chunks.encode = None`
 (`src/nettcp/nmf.py:140`), donc toute tentative de `to_bytes` échouerait ;
- le décodeur en flux `data_chunks_stream` (`src/nettcp/nmf.py:142-149`)
 référence une variable `data` qui n'existe pas dans sa portée — le paramètre
 s'appelle `stream`. Un `NameError` se produirait à la première invocation.

Ce code est donc mort et cassé ; il n'est jamais atteint parce que le mode
Duplex n'utilise que le record `0x06`. Le signaler évite qu'un lecteur le
prenne pour une fonctionnalité disponible.

# Terminaison de connexion et gestion des erreurs de cadrage

## La fin normale : EndRecord

La grammaire termine `DuplexStream-a` par un `EndRecord` et autorise
`DuplexStream-b` à se clore par un `FaultRecord` ou un `EndRecord`. Le record
`0x07` est nu : un octet, aucune charge utile, aucun acquittement attendu.

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

Le cas `BrokenPipeError` mérite d'être lu littéralement : le code tente d'écrire
un `EndRecord` sur un tube déjà rompu, et l'échec de cette écriture est absorbé
par un `except Exception: pass` (`classes/server/protocol.py:123-124`). La
tentative est donc systématiquement vaine, mais sans conséquence.

Le serveur **n'accuse pas réception** d'un `EndRecord` client : il ne renvoie
pas de `EndRecord` en écho, il se contente de sortir.

## Le timeout, en théorie et dans le code

`ConnectionHandler.handle` pose `self.request.settimeout(10)`
(`classes/server/connection.py:39`), et la boucle de messages tente de réduire
ce délai à deux secondes après la première réponse
(`classes/server/protocol.py:163-166`). La lecture attentive du code montre que
ni l'un ni l'autre ne prend effet durablement :

- `SocketStream.read(count)` appelle `self._socket.setblocking(1)`
 (`src/nettcp/stream/socket.py:32`) et `SocketStream.write` fait de même
 (`src/nettcp/stream/socket.py:51`). Or, en Python, `setblocking(True)` est
 strictement équivalent à `settimeout(None)` : **le délai de 10 secondes est
 effacé dès la première lecture ou écriture**.
- La réduction à 2 secondes cible `self.stream._socket`, mais `self.stream` est
 à ce stade un `GENSECStream`, qui n'expose pas d'attribut `_socket` —
 l'`AttributeError` est avalée par le `except Exception: pass` de
 `classes/server/protocol.py:165-166`.

Conséquence : la branche `except socket_timeout` de
`classes/server/protocol.py:115` n'est, en lecture du code, jamais empruntée, et
le processus fils reste bloqué en `recv` jusqu'à ce que le client ferme. Si le
client émet un RST, `ConnectionResetError` est levée et le serveur émet un
`EndRecord` de courtoisie ; si le client ferme proprement, la chaîne d'appels
est la suivante :

- `GENSECStream.read(1)` a son `_readcache` vide et appelle
 `NegotiateStream.read` (`src/nettcp/stream/gssapi.py:162-166`) ;
- le handshake étant terminé, celui-ci lit quatre octets d'en-tête
 (`src/nettcp/stream/negotiate.py:79`) ;
- `SocketStream.read(4)` sort de sa boucle sur `if not d: break`
 (`src/nettcp/stream/socket.py:36-37`) et rend `b''` ;
- `struct.unpack('<I', b'')` lève une `struct.error`.

`struct.error` n'est ni `OSError` ni `EOFError` : elle échappe donc au
`except (EOFError, OSError)` de `classes/server/protocol.py:126` et tombe dans
le `except Exception` général de la ligne 179, produisant une trace d'erreur
complète pour ce qui est une déconnexion normale. Le garde-fou prévu pour ce
cas — `raise IOError('connection closed mid-message')`,
`src/nettcp/stream/gssapi.py:164-165` — n'est jamais atteint, puisque
`NegotiateStream` lève avant de pouvoir rendre une chaîne vide ; il aurait
d'ailleurs été correctement classé, `IOError` étant un alias d'`OSError`. C'est
cosmétique — la connexion est de toute façon terminée — mais cela pollue le
journal et complique le diagnostic décrit dans
`documentation/06-depannage.md` section 2.

## Erreurs de cadrage : fermeture sèche, jamais de fault

C'est la règle à retenir, et elle est sans exception dans l'implémentation
actuelle :

> **Toute erreur de cadrage entraîne la fermeture de la connexion sans aucune
> réponse. Le serveur souverain n'émet jamais de `FaultRecord` (`0x08`).**

Le mécanisme est uniforme. Chacune des trois phases de `ProtocolHandler` est
enveloppée dans un `try` / `except Exception` qui journalise et renvoie `False`
(`classes/server/protocol.py:65-67`, `:103-105`, `:179-181`).
`ConnectionHandler.handle` teste ces retours et sort du bloc `try` sans écrire
sur le socket (`classes/server/connection.py:45-60`) ; `socketserver` ferme
alors la socket. Les seules exceptions attrapées nommément au niveau connexion
sont `BrokenPipeError`, `ConnectionResetError` et `EOFError`
(`classes/server/connection.py:62-63`), traitées comme une déconnexion normale ;
tout le reste tombe dans un `except Exception` qui journalise une trace
(`classes/server/connection.py:64-65`).

Les déclencheurs concrets, par ordre de probabilité :

| Cause | Exception levée | Phase |
|---|---|---|
| Octet de type inconnu (`0x04`, `0x0D`+) | `KeyError` | 1 ou 3 |
| Encodage hors 3-8 | `ValueError` | 1 |
| Mode hors 1-4 | `ValueError` | 1 |
| Flux tronqué au milieu d'un record | `AssertionError` | 1 ou 3 |
| Absence d'`UpgradeRequestRecord` | retour `False` explicite | 2 |
| Échec Kerberos (SPN, horloge) | `samba.NTSTATUSError` | 2 |

Le cas Kerberos est le seul dont une trace réelle soit conservée dans le dépôt :
`documentation/06-depannage.md:33` montre
`samba.NTSTATUSError: (3221225572, 'The specified account does not exist.')`,
soit le NTSTATUS `0xC0000064` (`STATUS_NO_SUCH_USER`) — SPN absent d'AD. Levée
depuis `negotiate_server`, elle est captée par le `except Exception` de la
phase 2 et se solde par la même fermeture sèche.

L'`AssertionError` mérite une note : `Record.parse_stream` vérifie
`assert len(data) == s, repr(data)` (`src/nettcp/nmf.py:259`). Si le pair ferme
au milieu d'un record, `read(1)` rend `b''` et l'assertion échoue ; son message
porte la représentation des octets lus, utile en journal `DEBUG`. Une exécution
avec `python3 -O` supprimerait l'assertion et laisserait passer un
`struct.error` moins parlant : le service doit être lancé sans optimisation, ce
que fait `python3 -m src.main`.

Côté Windows, cette fermeture sèche se présente sous la forme
`Le site distant a fermé le flux de transport`
(`documentation/06-depannage.md:78`). Un `FaultRecord` correctement formé
donnerait au client un message bien plus précis ; c'est l'argument principal
pour implémenter l'émission de faults de cadrage.

## Ne pas confondre fault de cadrage et fault SOAP

Deux mécanismes d'erreur totalement disjoints coexistent :

| Critère | `FaultRecord` NMF | SOAP Fault |
|---|---|---|
| Couche | cadrage, octet `0x08` | applicatif, dans un `0x06` |
| Contenu | un URI UTF-8 | une enveloppe SOAP complète |
| Corrélation | aucune | `<a:RelatesTo>` obligatoire |
| Émis par ce projet | **non** | oui |
| Producteur | — | `classes/handlers/dispatcher.py:31-35` |

Le dispatcher attrape `ADWSException` et toute exception résiduelle et les
convertit en enveloppe SOAP par `_fault` (`classes/handlers/dispatcher.py:52-55`).
Ce fault applicatif est ensuite encodé et **cadré normalement dans un
`SizedEnvelopeRecord`** : du point de vue NMF, c'est un message comme un autre.
L'invariant « tout fault DOIT porter `<a:RelatesTo>` » du `CLAUDE.md` section 5
concerne exclusivement ce second mécanisme.

> **Angle mort à connaître.** `_fault` s'écrit
> `relates_to = context.message_id if context else ""`
> (`classes/handlers/dispatcher.py:54`). Le `context` n'est construit qu'à la
> ligne 25, après `record.payload_to_xml`. Toute défaillance survenant *avant*
> — décodage du dictionnaire in-band, parsing NBFX, XML malformé — produit donc
> un fault dont le `<a:RelatesTo>` est **vide**. C'est précisément le cas que
> l'invariant du projet cherche à interdire : PowerShell ignore la réponse et la
> cmdlet bloque jusqu'au timeout. Les erreurs de la couche de cadrage
> proprement dite n'atteignent jamais le dispatcher — elles ferment la connexion
> —, mais les erreurs de la couche NBFX, elles, empruntent ce chemin.

# Implémentation dans ce projet

## Cartographie des fichiers

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

## Le lecteur générique de records

L'architecture de `src/nettcp/nmf.py` repose sur une description déclarative :
chaque classe de record porte un `code` et une liste `fields` de couples
`(nom, décodeur)`. Trois méthodes exploitent cette description :

- `Record.parse(data)` (`src/nettcp/nmf.py:232-253`) — décodage depuis un buffer
 complet, renvoie le nombre d'octets consommés et l'objet. Utilisé par
 l'outillage de rejeu de traces.
- `Record.parse_stream(stream)` (`src/nettcp/nmf.py:255-273`) — décodage
 incrémental depuis un flux. **C'est le seul chemin utilisé par le serveur**
 (`classes/server/protocol.py:38`, `:80`, `:114`).
- `Record.to_bytes` (`src/nettcp/nmf.py:275-287`) — encodage, avec
 journalisation du champ fautif en cas d'échec.

Le décodeur d'un champ est soit une chaîne de format `struct` (cas de
`MajorVersion`, `'B'`), soit un appelable exposant `stream` et `encode`. Ajouter
un record se réduit donc à déclarer la classe : `register_types` l'enregistre.
L'appel a lieu deux fois — au démarrage, avant tout `fork` (`src/main.py:15`),
et à chaque instanciation de `NMFStream` (`src/nettcp/stream/nmf.py:17`) — et
l'opération est idempotente.

Point de détail : `register_types` enregistre aussi la classe de base `Record`
sous la clé `None` (elle est trivialement sous-classe d'elle-même). Cette entrée
est inatteignable, la clé de recherche étant toujours un entier issu d'un octet.
Les classes `Enum`, `KnownEncoding`, `Mode` et `DataChunk` du même module ne
descendent pas de `Record` et ne sont pas enregistrées.

Le cadrage [MS-NNS] réutilise la même machinerie sans polluer le registre NMF :
`class Handshake(Record)` redéfinit `_records = {}`
(`src/nettcp/stream/negotiate.py:20-21`), si bien que
`Handshake.register(...)` peuple un dictionnaire distinct — l'enregistrement y
est d'ailleurs explicite et non introspectif
(`src/nettcp/stream/negotiate.py:40-42`). Les types de messages de handshake y
valent `0x14` (done), `0x15` (error) et `0x16` (in progress)
(`src/nettcp/stream/negotiate.py:14-17`) — ce sont des valeurs [MS-NNS], à ne
jamais confondre avec des codes de record NMF.

| Champ du handshake NNS | Format | Ancrage |
|---|---|---|
| type de message | `uint8` | `negotiate.py:25` |
| major | `uint8` = 1 | `negotiate.py:27` |
| minor | `uint8` = 0 | `negotiate.py:28` |
| taille de charge utile | `uint16` **big-endian** (`>H`) | `negotiate.py:29` |

Le contraste est instructif : l'en-tête de handshake code sa taille en
gros-boutiste sur deux octets, alors que les trames post-handshake la codent en
petit-boutiste sur quatre (`negotiate.py:61` et `:79`), et que NMF, lui, utilise
son varint. Trois conventions de longueur cohabitent donc sur la même connexion.

> **Défaut latent dans la branche d'erreur.** `NegotiateStream.read` initialise
> `error = None`, ne le renseigne que si `payload_size > 0`
> (`src/nettcp/stream/negotiate.py:69-71`), puis formate systématiquement
> `"Negotiate Error: {:08x}".format(error)` (ligne 72). Un `HandshakeError` sans
> charge utile produirait donc un `TypeError` de formatage à la place du
> diagnostic attendu. Ce chemin n'a jamais été déclenché dans ce dépôt ; le
> constat est statique.

## Interaction avec le modèle `ForkingTCPServer`

L'invariant du projet — un processus par connexion, parce que `python3-samba`
n'est pas *thread-safe* — a des conséquences directes sur la couche de cadrage.

`src/nettcp/protocol2xml.py` maintient trois états globaux mutables :
`old_dictionary` (ligne 25), `dictionary_cache` (ligne 26) et le compteur `idx`
(ligne 28), ce dernier incrémenté de 2 par entrée de dictionnaire de session
(ligne 41) — les identifiants de session sont impairs, la table statique
occupant les pairs. Le module comporte même une assertion
`assert idx not in dictionary_cache[key]` (ligne 39) qui deviendrait fausse si
plusieurs connexions partageaient l'état. Le modèle *forking* garantit qu'elles
ne le partagent pas : chaque processus fils hérite d'une copie au moment du
`fork` et repart de zéro. La même remarque vaut pour le registre
`Record._records`, peuplé une fois avant le `fork` et jamais modifié ensuite.

Cette dépendance implicite au *forking* est un piège : rendre le serveur
multithread sans réécrire `protocol2xml.py` casserait les dictionnaires de
session.

## Statut normatif du code de cadrage

`src/nettcp/` et `src/wcf/` sont du **code tiers vendoré**, explicitement exclu
des normes internes :

- `pyproject.toml:11` — `extend-exclude = ["tools", "src/nettcp", "src/wcf"]`
 pour ruff ;
- `pyproject.toml:31` — `exclude = '^src/(nettcp|wcf)/'` pour mypy ;
- `pyproject.toml:34-36` — les modules `src.nettcp.*` et `src.wcf.*` sont
 déclarés `follow_imports = "skip"`, ce qui les traite comme une frontière
 `Any` pour que les appels depuis `classes/` passent en mode strict ;
- `.pre-commit-config.yaml` — le filtre `files: ^(src|classes)/(?!nettcp/|wcf/)`
 est appliqué aux cinq hooks Python : ruff, flake8, `tools/norms` et mypy sont
 bloquants, pylint est en stage `manual`.

C'est pourquoi `src/nettcp/nmf.py` comporte dix-sept classes et quatorze
fonctions au niveau module, en contradiction frontale avec la règle « une classe
et cinq fonctions maximum par fichier » de `CLAUDE.md` section 6.1. Le code
*maison* qui pilote ce cadrage, lui, est soumis aux normes : `ProtocolHandler`
(`classes/server/protocol.py`) est une classe unique totalisant cinq fonctions
— `__init__` plus les quatre méthodes publiques `handle_preamble`,
`handle_security`, `handle_messages` et `send_record` —, ce qui est exactement
la limite.

Toute évolution de la couche de cadrage doit donc arbitrer : corriger sur place
dans le code vendoré (rapide, mais non vérifié par les linters) ou remonter la
logique dans `classes/server/` (conforme, mais plus invasif). Pour les
durcissements listés ci-dessous, la seconde voie est préférable : un contrôle de
taille maximale et un contrôle de longueur de varint ont leur place dans
`ProtocolHandler`, pas dans la bibliothèque d'origine.

## Synthèse des écarts connus

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

## Erratum sur la documentation existante

Le tableau « Phase 1 — Préambule NMF » de `documentation/03-protocole.md:34-40`
comporte des valeurs d'octet erronées, probablement issues d'une transcription
manuelle : les codes de record y sont décalés d'un rang à partir du
`ModeRecord`. La correction, vérifiée contre `src/nettcp/nmf.py:298-325` et
contre la table normative :

| Record | Valeur publiée | Valeur exacte |
|---|---|---|
| `VersionRecord` | `0x00 0x01 0x00 0x01` | `0x00 0x01 0x00` |
| `ModeRecord` | `0x02 0x02` | `0x01 0x02` |
| `ViaRecord` | `0x03 …` | `0x02 <varint> <utf8>` |
| `KnownEncodingRecord` | `0x04 0x03` | `0x03 0x08` |

Le libellé « encoding=BINARY_WITH_DICT (3) » du même tableau est doublement
inexact : le membre déclaré en `src/nettcp/nmf.py:184` s'appelle `BINARY_DICT`
et vaut **8**, la valeur 3 désignant SOAP 1.2 en UTF-8 textuel.

Trois autres imprécisions du même document relèvent du présent chapitre :

| Emplacement | Texte publié | Correction |
|---|---|---|
| `03-protocole.md:58` | `PreambleEndRecord (0x0c)` serveur → client | client → serveur ; c'est `PreambleAckRecord` (`0x0b`) qui revient |
| `03-protocole.md:48` | tokens « préfixés d'un `int32` little-endian » | vrai après le handshake seulement ; pendant, en-tête NNS de 5 octets à taille `uint16` gros-boutiste |
| `03-protocole.md:27` | « MS-NBFS :.NET Binary Format: SOAP Extension » | [MS-NBFS] = *SOAP Data Structure* ; l'*Extension* est [MS-NBFSE] |

Ces corrections doivent être portées dans `documentation/03-protocole.md`
conformément à la règle du dépôt qui veut que toute correction de comportement
documenté mette à jour la documentation dans le même commit.

## Feuille de route de durcissement (phase 5)

Par ordre décroissant de rapport bénéfice/coût :

- **1.** Borner le varint à cinq octets dans `varint_stream`, à l'image de
 `MultiByteInt31.parse`. Trois lignes, supprime un vecteur de déni de service.
- **2.** Refuser un `SizedEnvelopeRecord` dont la taille annoncée dépasse un
 plafond configurable, aligné par défaut sur le 1 Mio de Microsoft. À placer
 dans `ProtocolHandler.handle_messages`, avant l'appel au dispatcher.
- **3.** Émettre un `FaultRecord` au lieu de fermer sèchement, au minimum pour
 `UnsupportedMode`, `ContentTypeInvalid`, `UpgradeInvalid` et
 `MaxMessageSizeExceededFault`. Gain immédiat sur la qualité des messages
 d'erreur côté PowerShell.
- **4.** Valider explicitement mode, encodage et chaîne d'*upgrade*, plutôt que
 de s'en remettre aux exceptions de l'énumération.
- **5.** Réparer la gestion des délais : remplacer les `setblocking(1)` de
 `src/nettcp/stream/socket.py` par un `settimeout` explicite, et cibler la
 socket réelle plutôt que `self.stream._socket` dans
 `classes/server/protocol.py:164`.
- **6.** Traiter la fermeture propre du client (`recv` rendant `b''`) comme un
 événement normal, pour cesser de journaliser une trace d'erreur à chaque fin
 de session.

Aucun de ces six points ne modifie le comportement observable d'un client
conforme : ils ne touchent que les chemins d'erreur et les limites de
ressources, ce qui est précisément le périmètre de la phase 5.
