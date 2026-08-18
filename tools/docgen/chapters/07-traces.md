# Méthode et outillage de capture

Ce chapitre met en mouvement la mécanique décrite précédemment : quatre
scénarios complets, de l'octet sur la socket à l'objet affiché dans la console
PowerShell, puis une grille de diagnostic. Principe directeur : **on ne
diagnostique pas ADWS depuis le réseau**. Le trafic est scellé dès la fin du
préambule ; l'observation utile se fait aux deux extrémités de la couche de
chiffrement — juste avant `wrap`, juste après `unwrap` — et dans le
journal applicatif.

> **Convention typographique.** Dans les blocs XML, une barre oblique inverse en
> fin de ligne (`\`) marque une coupure de mise en page imposée par la largeur
> de la page : la valeur réelle est la concaténation des deux fragments, sans
> espace ni saut de ligne.

## Ce que la couche transport laisse voir, et à partir de quand

Trois régimes se succèdent sur la même connexion TCP 9389.

| Régime | Contenu sur le fil | Lisible en pcap |
|---|---|---|
| Préambule NMF | records `0x00`–`0x03`, `0x09` | Oui, intégralement |
| Négociation SPNEGO | tokens GSS-API bruts (RFC 4178) | Oui, mais binaire ASN.1 |
| Messages applicatifs | WCF binaire scellé Kerberos | Non, ciphertext |

La bascule est nette : `ProtocolHandler.handle_security` remplace le
`SocketStream` par un `GENSECStream` (`classes/server/protocol.py:96`) ; toute
écriture passe dès lors par `wrap` (`src/nettcp/stream/gssapi.py:150`) et
toute lecture par `unwrap` (`:160`). Le contexte est établi par
`samba.gensec`, mécanisme `spnego` (`:118`), avec les identifiants du compte
machine (`:113-116`) : la clé de session dérive du keytab Samba et n'apparaît
ni dans le dépôt ni dans la capture.

> Conséquence pratique : un `.pcap` d'un incident ADWS ne sert **qu'à** valider
> le préambule, l'échec Kerberos et le fait que des octets circulent. Dès que la
> phase 3 démarre, il ne dit plus rien du contenu applicatif.

## tcpdump : ce qu'on obtient réellement

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

> **Correction par rapport à `documentation/03-protocole.md:36-39`.** Ce tableau
> attribue `0x02` à `ModeRecord`, `0x03` à `ViaRecord`, `0x04` à
> `KnownEncodingRecord`, donne `BINARY_WITH_DICT = 3` et fait commencer le
> `VersionRecord` par `0x00 0x01 0x00 0x01`. Le code contredit chacun de ces
> points : `Mode = 0x01`, `Via = 0x02`, `KnownEncoding = 0x03`
> (`src/nettcp/nmf.py:306`, `:313`, `:321`), l'encodage négocié est
> `KnownEncoding.BINARY_DICT = 8` (`:184`), et le `VersionRecord` tient en trois
> octets `00 01 00` (`:298-303`). La constante `BINARY_WITH_DICT` n'existe pas ;
> la valeur `3` désigne en réalité `UTF8` (`:179`). C'est bien la valeur `8`,
> et non `7`, qui explique le préfixe de dictionnaire de session en tête de
> chaque payload (voir plus bas).

Le `ViaRecord` de l'URL
`net.tcp://dc1.samdom.example.com:9389/ActiveDirectoryWebServices/Windows/Resource`
(81 caractères) commence donc par `02 51 6e 65 74 …`, où `0x51` = 81 est la
longueur en varint MS-NMF. L'en-tête d'un message applicatif dont le payload fait 6833 octets — taille
réellement observée pour une réponse RootDSE dans `adws.log` :

```text
06 b1 35        SizedEnvelopedMessageRecord, Size = 6833
06 e6 03        SizedEnvelopedMessageRecord, Size = 486  (requête RootDSE)
```

Entre les deux, la sous-couche NegotiateStream ([MS-NNS] côté Windows) ajoute
son propre cadrage, lui aussi vérifiable dans le code :

| Phase | En-tête | Octets |
|---|---|---|
| Handshake en cours | `HandshakeInProgress` `0x16` | `16 01 00 <BE uint16>` |
| Handshake terminé | `HandshakeDone` `0x14` | `14 01 00 <BE uint16>` |
| Handshake en erreur | `HandshakeError` `0x15` | `15 01 00 <BE uint16>` |
| Après handshake | longueur seule | `<LE uint32>` |

Références : `src/nettcp/stream/negotiate.py:14-17` pour les types,
`:50-62` pour l'écriture (taille de trame plafonnée à `0xFC30`), `:64-80` pour
la lecture. Noter l'asymétrie : la taille du handshake est **big-endian** sur 2
octets, celle des trames post-handshake **little-endian** sur 4 octets.

Contrainte de dimensionnement à connaître, car elle produit des pannes
difficiles : le clair soumis à `wrap` est découpé en blocs de
`_PLAINTEXT_CHUNK = 0xF000` octets (`src/nettcp/stream/gssapi.py:17`), marge
volontaire sous le plafond de trame `0xFC30`, parce que le lecteur suppose
**une trame = un token GSS** (`:154-166`). Un token débordant sur deux trames ne
serait jamais désencapsulé.

## Le proxy de debug du dépôt : ce qu'il fait vraiment

`tools/work/proxy.py` est présenté par la documentation existante comme l'outil
qui donne le XML en clair, via une constante `RECORD_LOG`. **Cette constante
n'existe pas.** Une recherche sur l'ensemble du dépôt ne la trouve que dans
trois fichiers de documentation (`documentation/03-protocole.md:264`,
`documentation/06-depannage.md:402`, `.claude/skills/decode-wcf/SKILL.md:38`),
jamais dans du code. Voici l'état réel du fichier.

- Le journal de trace se règle par l'option `-t/--trace_file` de la ligne de
 commande (`tools/work/proxy.py:168`), pas par une constante. Le format écrit
 est `timestamp<TAB>ip:port<TAB>sens<TAB>hex` (`tools/work/proxy.py:86-92`),
 où `sens` vaut `c>s` ou `s>c`.
- L'outil écoute par défaut sur `localhost:8090` (`tools/work/proxy.py:165`) et
 prend `TARGET_HOST` et `TARGET_PORT` en arguments positionnels (`:172-173`).
 Il force par ailleurs le logger racine en `DEBUG` dès l'import (`:34`).
- **Il ne relaie pas.** Après avoir ouvert une connexion vers la cible
 (`tools/work/proxy.py:97`), la ligne qui réécrirait les records du client vers
 le serveur est commentée (`tools/work/proxy.py:123`). Sur réception de
 l'`UpgradeRequestRecord`, le proxy répond lui-même l'`UpgradeResponseRecord`
 puis exécute **sa propre** négociation GSSAPI côté serveur
 (`tools/work/proxy.py:136-148`) : le client s'authentifie donc contre le
 proxy, pas contre le DC.
- Les imports du module sont relatifs à son emplacement d'origine
 `src/nettcp/` : `from.stream.socket import SocketStream` et `from.nmf
 import...` (`tools/work/proxy.py:18-20`). Depuis `tools/work/`, qui ne
 contient ni `stream/`, ni `nmf.py`, ni `__init__.py`, l'import échoue.

**Le proxy n'est donc pas, en l'état, un outil de capture utilisable.** Ce n'est
pas un défaut bloquant du service — c'est un vestige vendoré hors du chemin
d'exécution — mais toute procédure de dépannage qui s'appuie dessus est à
réécrire.

## Décoder un payload WCF hors ligne

C'est ici que la documentation existante induit le plus sûrement en erreur. La
recette publiée — `dump_records(data)` sur des octets — **n'est pas un
décodeur**. `dump_records` fait exactement l'inverse : il prend un *arbre de
records* et rend des octets (`src/wcf/records/__init__.py:90-124`). C'est la
fonction employée par le dispatcher pour **encoder** la réponse
(`classes/handlers/dispatcher.py:47-48`).

Appelée sur des octets, elle itère sur des `int` et appelle `int.to_bytes` —
disponible avec arguments par défaut depuis Python 3.11 — donc **retourne
l'entrée inchangée**. Aucune erreur, aucun XML : un faux positif silencieux.

Le décodage réel se fait comme dans `SizedEnvelopedMessageRecord.payload_to_xml`
(`src/nettcp/nmf.py:363-373`) : lire d'abord le dictionnaire de session, puis
parser l'arbre, puis l'imprimer.

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
donnant la taille, en octets, de la table de chaînes de **session** ([MS-NBFSE]),
suivie de ce nombre d'octets de chaînes UTF-8 longueur-préfixées
(`src/nettcp/protocol2xml.py:30-48`). Les index de session sont **impairs**
(`idx` part à 1 et progresse de 2, `src/nettcp/protocol2xml.py:28` et `:41`)
tandis que le dictionnaire statique [MS-NBFS] occupe les index **pairs**, de
`0x000` à `0x3CC` (972 en décimal), soit 487 entrées dans
`src/wcf/dictionary.py`.

> **Deuxième dérive, `documentation/03-protocole.md:96`.** Ce document affirme
> que « le dictionnaire dynamique négocié par session (MS-NBFSE) n'est pas
> implémenté ». À nuancer fortement : le serveur ne *produit* effectivement
> jamais de table de session, mais il en *consomme* une à chaque message
> entrant, et `build_dictionary` fusionne ces index impairs dans le dictionnaire
> global avant le parsing (`src/nettcp/protocol2xml.py:42-44`). Le mécanisme est
> bien implémenté côté lecture — c'est même la source de l'incident
> `UnicodeDecodeError` analysé au scénario 4.

Effet de bord : `dictionary` est un dictionnaire de **module** vidé puis
reconstruit à chaque appel, et `idx` est une globale protégée par un `assert`
(`src/nettcp/protocol2xml.py:31`, `:39`, `:42-44`). Le modèle
`ForkingTCPServer` l'absout — un process par connexion — mais tout portage
fileté casserait ici en premier.

Le serveur, lui, n'alimente jamais de dictionnaire de session : `_encode_response`
préfixe la réponse d'un octet `\x00` (`classes/handlers/dispatcher.py:49`),
c'est-à-dire « table de session vide ». D'où la règle de dépannage : sur une
trame **sortante**, retirer le premier octet ou laisser `build_dictionary` le
consommer ; les deux reviennent au même.

Exemple entièrement vérifié — l'enveloppe `Get` minimale ci-dessous a été
réellement encodée par le dépôt (`XMLParser.parse` puis `dump_records`), et les
124 octets produits sont reproduits tels quels :

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

Deux points sont contre-intuitifs. D'abord, le préfixe `00` de table de session
vide **n'apparaît pas** ci-dessus : il est ajouté par le dispatcher, pas par
`dump_records` (`classes/handlers/dispatcher.py:49`) ; sur le fil la trame
commence donc par `00 56 02 …`. Ensuite, la marque de fin d'élément est
**fusionnée dans le dernier record de texte** : `dump_records` incrémente le
type du dernier `Text` enfant (`src/wcf/records/__init__.py:103-106`) et n'émet
alors pas de `EndElementRecord` séparé (`:117-119`), d'où `0xB7`. Un élément
sans enfant textuel, lui, produit bien un `0x01` explicite (`:120-122`).

Les familles de codes de records structurels, toutes relevées dans le dépôt :

| Famille | Plage | Source |
|---|---|---|
| `EndElementRecord` | `0x01` | `src/wcf/records/base.py:152` |
| Attributs `xmlns` (dict.) | `0x0A`–`0x0B` | `src/wcf/records/attributes.py:222,256` |
| `PrefixDictionaryAttribute{A..Z}` | `0x0C`–`0x25` | `src/wcf/records/attributes.py:431` |
| `PrefixAttribute{A..Z}` | `0x26`–`0x3F` | `src/wcf/records/attributes.py:447` |
| `PrefixDictionaryElement{A..Z}` | `0x44`–`0x5D` | `src/wcf/records/elements.py:321` |
| `PrefixElement{A..Z}` | `0x5E`–`0x77` | `src/wcf/records/elements.py:337` |

La règle de dérivation est arithmétique : le code d'un préfixe à une lettre vaut
`base + (lettre - 'a')`. C'est ce qui donne `'a'` = `0x44` et `'s'` = `0x56` pour
les éléments, `'s'` = `0x1E` pour les attributs. Un hexdump se lit donc à vue dès
qu'on a ces six lignes en tête.

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
`EnumerationContext`, `EndOfSequence`) n'est présent dans la table statique :
vérifié, `inverted_dict` renvoie `None` pour chacun. C'est précisément ce que le
dictionnaire de session sert à compenser côté client. Côté serveur, ces noms
partent donc en toutes lettres, ce qui gonfle la réponse mais ne pose aucun
problème d'interopérabilité.

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

> `documentation/03-protocole.md:89-90` associe `0x88` à `xsd:int` et `0x8A` à
> `xsd:long`. Le code dit `0x88 = Int8` et `0x8A = Int16` ; `Int32` est `0x8C`,
> `Int64` est `0x8E`. La règle réelle est dynamique : `xml2records` choisit la
> largeur d'après la **valeur**, pas d'après le type XSD déclaré
> (`src/wcf/xml2records.py:143-153`). La même ligne 94 annonce un
> `GuidTextRecord` : la classe s'appelle `UuidTextRecord`
> (`src/wcf/records/text.py:716-717`).

## Obtenir le clair quand on ne peut pas décoder le réseau

Trois méthodes, par coût croissant.

- **Le journal applicatif** donne l'action et le `MessageID` de chaque requête
 (`classes/handlers/dispatcher.py:26-28`) puis le handler résolu (`:42`) :
 suffisant pour identifier *quel* message pose problème, pas son contenu.
- **Une instrumentation temporaire du dispatcher.** Le point d'observation
 canonique est `xml_request = record.payload_to_xml` (`:24`), où la requête
 est déjà descellée et convertie en XML texte. Écrire `xml_request` puis
 `response_xml` dans un fichier donne ce que le proxy prétendait fournir, sans
 MITM.
- **La rejouabilité hors ligne.** Sauvegarder `record.Payload` en binaire permet
 de rejouer le décodage à froid, sans reproduire l'incident côté Windows.

Deux lecteurs de trace hexadécimale existent par ailleurs :
`python3 -m src.nettcp.protocol2xml TRACE_FILE` reconstruit les records NMF et
décode les payloads `0x06` (`src/nettcp/protocol2xml.py:81-101`) ;
`python3 -m src.nettcp.nmf TRACE_FILE` s'arrête aux records
(`src/nettcp/nmf.py:409-431`).

## Les trois harnais de test

| Harnais | Emplacement | Portée | Réseau |
|---|---|---|---|
| Diagnostic | `tools/test/test_adws.py` | environnement | port seulement |
| Handlers | `tools/test/test_handlers.py` | logique isolée | aucun |
| Bout en bout | `tools/test/Test-ADWS-Sovereign.ps1` | cmdlets réelles | complet |

`test_adws.py` exécute six contrôles (`tools/test/test_adws.py:96-100`) : port
`127.0.0.1:9389`, imports `samba`/`samba.samdb`/`ldb`/`gssapi`, connexion
`SamDB` avec lecture du `defaultNamingContext`, encodage XML vers records
(`:48-56` — aller simple, pas aller-retour), **échappement non-ASCII** et
intégrité de la table de routage. Le cinquième est un test de non-régression du
bug « undefined entity » sur les accents (`:62-71`). Le correctif tient dans une
table de quatre entrées (`src/wcf/records/text.py:46`, appliquée en `:49-56`) :
seuls `<`, `>`, `&` et `"` sont mappés, tout autre point de code reste littéral.
La table `codepoint2name` de `html.entities`, encore importée (`:38-41`), n'est
plus utilisée nulle part — vestige du bug.

`test_handlers.py` construit un `HandlerRegistry` réel sur `system_session`
puis vérifie trois propriétés (`tools/test/test_handlers.py:39-59`) : chaque
clé de `HANDLER_FACTORIES` se résout, `GetVersion` produit un corps
`<ca:Version…>`, et le `<a:RelatesTo>` est bien recopié — garde-fou de
l'invariant le plus coûteux du projet (voir scénario 4).

`Test-ADWS-Sovereign.ps1` est la validation de référence : exécuté depuis un
poste joint au domaine, il journalise un `.log` et un `.json` horodatés dans
`-OutputDirectory` (`:18-19`) et couvre huit phases — connectivité, lectures,
énumérations, mutations, mots de passe, groupes, schéma, charge (`:74`, `:91`,
`:105`, `:127`, `:166`, `:190`, `:222`, `:238`). Le test i18n de la phase 4
construit ses accents par `[char]0xE9` (`:147-149`) pour être indépendant de
l'encodage du script.

# Scénario 1 : Get-ADUser sur un objet unique, de la socket au résultat

Commande de référence, exécutée depuis un poste joint au domaine :

```powershell
Get-ADUser -Identity 'CN=Administrator,CN=Users,DC=samdom,DC=example,DC=com' `
           -Server dc1.samdom.example.com
```

Le passage par un DN évite l'étape de résolution d'identité (qui, elle, emprunte
la machinerie du scénario 2).

> **Statut des chronologies de ce chapitre.** Les tailles et horodatages cités
> sont relevés dans le fichier `adws.log` du dépôt (sessions du 3 juin 2026) ;
> ils sont donc réels. En revanche l'**enchaînement** présenté ci-dessous est une
> reconstruction : la session de 21:24:07 ne contient que le `Get` RootDSE suivi
> d'un `EndRecord`, tandis que les sessions de 10:03:43 et 12:32:41 montrent
> plusieurs messages applicatifs sur une même connexion. Les étapes 21 à 24
> décrivent donc le second aller-retour tel que le code le traite, pas une trace
> continue. Second avertissement : les tracebacks de `adws.log` référencent des
> chemins de l'ancienne arborescence (`/opt/adws/src/adws/dispatcher.py`,
> `/opt/adws/nettcp/nmf.py`) et deux lignes de journal du `PullHandler` de
> l'époque n'existent plus dans le code actuel. Le journal est un document
> d'archive : les numéros de ligne cités dans ce chapitre viennent du code, pas
> de lui.

Valeurs relevées : requête `Get` RootDSE 486 octets, réponse 6833 octets
(`adws.log`, 21:24:07,376 et 21:24:07,608).

## Chronologie

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
(`classes/server/connection.py:39` puis `classes/server/protocol.py:162-166`).
Passé ce délai sans nouveau message, le serveur émet un `EndRecord` et ferme
(`:119-125`) — comportement visible dans `adws.log` à 10:03:43,233. D'où les
connexions très courtes, souvent une par cmdlet : le client rouvre un canal
neuf plutôt que d'en réutiliser un fermé.

## La requête SOAP

Le corps est vide : en WS-Transfer `Get`, tout est dans les en-têtes
WS-Addressing et dans les paramètres de référence ADWS. La forme ci-dessous est
reconstituée d'après ce que le parseur consomme réellement
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
`root dse` ou le GUID `11111111-…` (`classes/handlers/get.py:39-45`). Sinon il
résout l'objet en essayant d'abord le DN reçu, puis ce DN suffixé du
`defaultNamingContext` (`:211-217`) — c'est ce qui permet à un DN relatif de
fonctionner, au prix d'une recherche ldb supplémentaire en cas d'échec.

## La réponse WS-Transfer

Sortie littérale de `_get_object` (`classes/handlers/get.py:279-302`), corps
produit par `whole_object`
(`classes/serialization/object_projector.py:20-28`). La réponse est **minifiée**
sur le fil (`re.sub(r'>\s+<', '><', response)`, `classes/handlers/get.py:302`) ;
elle est ré-indentée ici pour la lecture.

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
représentatives, non relevées ; **la structure, les noms de `LdapSyntax` et les
`xsi:type`, eux, sont exacts** et se déduisent mécaniquement du code :

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
voyagent en chaîne ; leur type LDAP réel est porté par `LdapSyntax`, jamais par
`xsi:type`. Émettre `xsd:integer` provoquait historiquement une
`KeyNotFoundException` côté client et cassait toutes les cmdlets à la connexion
(`documentation/05-tests.md:147-152`).

Trois attributs sont **synthétiques** : `objectReferenceProperty`,
`relativeDistinguishedName` et `distinguishedName` sortent en espace `ad:`,
**sans** `LdapSyntax` (`classes/serialization/object_projector.py:48-53`), et
sont retirés du flux d'attributs ordinaires pour éviter un doublon
(`:41-46`, `SYNTHETIC_KEYS:9-12`). `objectReferenceProperty` porte le **GUID
canonique** en `xsd:string`, à ne pas confondre avec `objectGUID` qui part en
base64 des 16 octets bruts. La conversion se fait par
`uuid.UUID(bytes_le=…)` (`classes/handlers/get.py:271`) — noter le
`bytes_le`, imposé par la représentation Windows du GUID.

## La variante IMDA

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

Le préfixe `addata:` est retiré à l'analyse (`classes/parsing/context.py:79-83`),
puis les attributs LDB sont filtrés sur cette liste
(`classes/handlers/get.py:67-77`). Corps de réponse produit par
`imda_projection` (`classes/serialization/object_projector.py:30-39`) :

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

Le dernier `<da:PartialAttribute>` est **inconditionnel** : `distinguishedName`
est toujours émis, même s'il n'a pas été demandé
(`classes/serialization/object_projector.py:34-38`). PowerShell s'en sert comme
clé d'identité ; son absence casse la désérialisation.

Trois formes coexistent donc, et le discriminant est
`context.is_imda and context.requested_attributes`
(`classes/handlers/get.py:273`) :

| Requête | Attributs demandés | Corps de réponse |
|---|---|---|
| `wxf:Get` nu | — | `<addata:{classe}>` |
| `da:BaseObjectSearchRequest` | 1 ou plus | `PartialAttribute` par attribut |
| `da:BaseObjectSearchRequest` | 0 | objet entier dans **un** `PartialAttribute` |

La troisième forme passe par `_wrap_imda_object`
(`classes/handlers/get.py:102-108`). Se tromper de forme produit côté Windows
l'erreur `Élément de fin '…' attendu, trouvé 'ad:distinguishedName'`.

## Le cas particulier du RootDSE

Le chemin RootDSE n'utilise **pas** `ObjectProjector` : il appelle directement
`renderer.render_attributes` (`classes/handlers/get.py:142-144`). Conséquence
concrète : la réponse RootDSE en WS-Transfer contient
`<ad:objectReferenceProperty>` puis les attributs, mais **aucun**
`relativeDistinguishedName` ni `distinguishedName` final. Le wrapper est
`<addata:top>` et le GUID est la constante
`11111111-1111-1111-1111-111111111111` (`classes/handlers/get.py:153-165`).

Deux corrections y sont appliquées avant rendu :

- `vendorName` et `vendorVersion`, que Samba expose mais pas AD, sont
 **supprimés** (`_ROOTDSE_DROP`, `classes/handlers/get.py:15-17`, appliqué en
 `:60-61`). Le client cherche chaque nom d'attribut RootDSE dans une table
 figée sans `TryGetValue` : une clé inconnue lève une `KeyNotFoundException` et
 casse toutes les cmdlets dès la connexion.
- `msDS-PortLDAP` et `msDS-PortSSL` sont **injectés** aux valeurs `389` et `636`
 s'ils manquent (`classes/handlers/get.py:62-65`).

# Scénario 2 : Get-ADUser -Filter * — énumération paginée complète

```powershell
Get-ADUser -Filter * -Server dc1.samdom.example.com
```

Trois actions WS-Enumeration, sur la même connexion TCP.

## Chronologie

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
`(sAMAccountName=Administrator)` rendant un seul objet. Cette session s'arrête
après le `Pull` : elle ne comporte ni `Release` ni `EndRecord`, le client ayant
été un harnais de test et non le module PowerShell. Les étapes 26 à 28 décrivent
donc le comportement du code, pas cette trace.

## Message 1 — Enumerate

La requête porte deux dialectes distincts : un dialecte de **filtre**
(`.../Dialect/LdapQuery`) et un dialecte de **sélection**
(`.../Dialect/XPath-Level-1`), tous deux nommés dans les constantes du service ADWS Microsoft.
Le serveur ne valide pas les URI de dialecte : il cherche directement les
éléments `adlq:` (`classes/parsing/context.py:95-106`) et `ad:SelectionProperty`
(`:110`).

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
 opérandes de `!` « nus » — `(!attr=val)`, forme qu'AD tolère et que ldb refuse
 — en `(!(attr=val))` (`classes/parsing/filter_parser.py:35-44`). En cas
 d'échec d'analyse, le filtre brut est transmis tel quel (`:96-98`).
- Un `BaseObject` vide retombe sur le `defaultNamingContext`
 (`classes/handlers/enumerate.py:30-33`), sans quoi ldb refuse la recherche avec
 `empty base DN`.
- Les attributs de sélection passent par `ConstructedAttrs.expand`
 (`classes/serialization/constructed_attrs.py:33-43`). **Attention au
 contresens** : cette fonction n'ajoute les 17 attributs construits
 (`tokenGroups`, `canonicalName`, `msDS-PrincipalName`, …, `:3-21`) que dans
 deux cas — liste vide, ou liste contenant `*`. Face à une liste explicite de
 `SelectionProperty`, elle la renvoie **inchangée**. La trace le confirme :
 cinq `SelectionProperty` en entrée donnent
 `[ENUMERATE] Attributes: ['cn', 'objectGUID', 'objectSid',
 'distinguishedName', 'userAccountControl']`, sans aucun ajout. `objectClass`
 est ensuite ajouté d'office s'il manque
 (`classes/handlers/enumerate.py:100-104`) — le rendu en a besoin pour nommer le
 wrapper.
- À défaut de `<adlq:Filter>`, le filtre par défaut est `(objectClass=*)`
 (`classes/handlers/enumerate.py:24`), et le scope par défaut `Subtree`
 (`:25`).
- Les contrôles LDAP sont traduits en syntaxe ldb
 (`classes/parsing/controls_parser.py:42-74`) via une table de 19 OID
 (`:8-28`), sous la forme `nom:criticité[:valeur]`.

Réponse, produite littéralement par
`_build_enumerate_response` (`classes/handlers/enumerate.py:106-129`) :

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

L'UUID `020b12b2-…` est authentique (`adws.log`, 09:46:12,134). `Expires` est
calculé à `utcnow + 1 h`, sérialisé en ISO 8601 avec un `Z` ajouté
manuellement (`classes/handlers/enumerate.py:81`).

> **Écart de conception à assumer.** L'`Enumerate` exécute **une seule
> recherche LDB complète** et matérialise tous les résultats en mémoire
> (`classes/handlers/enumerate.py:48-79`). La pagination est ensuite purement
> côté serveur, par découpage de la liste. Le contrôle `PagedResults`
> (`1.2.840.113556.1.4.319`) envoyé par le client est traduit et transmis à ldb,
> mais aucune reprise de curseur n'est implémentée. La liste est tronquée à
> `MAX_RESULTS_PER_CONTEXT = 50000`
> (`classes/enumeration/enumeration_registry.py:12`), avec un `WARNING` explicite
> (`classes/handlers/enumerate.py:74-78`).

## Messages 2 à n — Pull

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
(`classes/parsing/context.py:129-142`) — un `MaxElements` non numérique retombe
silencieusement sur `None` (`:139-142`), donc sur le défaut de 100 — puis
`get_next_batch` découpe la liste en place :

```python
start = self.result_index
end = min(start + max_elements, len(self.cached_results))
batch = self.cached_results[start:end]
self.result_index = end
```

(`classes/enumeration/enumeration_context.py:29-33`). `is_end_of_sequence` vaut
`result_index >= len(cached_results)` (`:22-24`) et est évalué **après** le
découpage (`classes/handlers/pull.py:33-34`).

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

Réponse finale, quand le lot épuise la liste : `<wsen:EnumerationContext>` est
remplacé par `<wsen:EndOfSequence/>`
(`classes/handlers/pull.py:85-91`). Si le lot est vide, `<wsen:Items/>` est
auto-fermé (`:83-84`).

Points structurels à retenir :

- Les items de `Pull` emploient **exactement** la forme WS-Transfer (objet
 entier, wrapper `<addata:{classe}>`), jamais des `PartialAttribute`
 (`classes/handlers/pull.py:56` appelle `whole_object`).
- L'enveloppe `Pull` **doit** déclarer `xsd` : les `<ad:value>` portent
 `xsi:type="xsd:…"` (`classes/handlers/pull.py:101`). Une déclaration manquante
 rend le document invalide côté client.
- La classe du wrapper est la **dernière** valeur de `objectClass`, décodée en
 s'appuyant sur le protocole d'indexation et non sur `str`
 (`classes/handlers/pull.py:58-65`). C'est la parade au bug historique
 `__str__ returned non-string (type NoneType)` : `ldb.MessageElement` n'est pas
 une `list` et son `__str__` C peut renvoyer `None`.

## Ce qui se passe sur plusieurs Pull

Le contexte d'énumération est un **objet mutable partagé entre les Pull d'une
même connexion**. Trois propriétés en découlent, toutes vérifiables.

- **Le curseur est monotone.** `result_index` n'est jamais remis à zéro ; un
 `Pull` rejoué avec le même contexte renvoie le lot *suivant*, pas le même. Il
 n'y a donc **aucune idempotence** : une retransmission côté client, ou un
 `Pull` doublé, saute silencieusement des objets.
- **Le contexte est local au process.** `get_enumeration_registry` est un singleton
 de module (`src/enumeration/enumeration.py:6-13`) et le serveur est un
 `ForkingTCPServer` (`classes/server/server.py:25`). Chaque connexion étant un
 process distinct, un `Pull` arrivant sur une **autre** connexion ne trouve pas
 le contexte et reçoit `Invalid or expired enumeration context`
 (`classes/handlers/pull.py:28-31`). Le fonctionnement repose entièrement sur
 le fait que le client réutilise la même connexion TCP pour tout le cycle
 Enumerate/Pull/Release.
- **La taille de lot par défaut diffère de la référence.** En l'absence de
 `MaxElements`, cette implémentation prend **100**
 (`classes/handlers/pull.py:20`), alors que le service Microsoft utilise
 `DefaultPullElements = 1`. En pratique le module
 PowerShell envoie toujours `MaxElements`, la divergence reste théorique.

Le cache lui-même est plafonné à `MAX_CONTEXTS = 256`
(`classes/enumeration/enumeration_registry.py:11`) avec éviction du plus ancien et
un `WARNING` (`:26-29`). Une lecture de contexte expiré le supprime et renvoie
`None` (`:43-49`). `Renew` réarme l'expiration à une heure
(`classes/handlers/renew.py:19-21`), `GetStatus` la restitue sans la modifier
(`classes/handlers/get_status.py:24-29`).

## Message final — Release

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

`ReleaseHandler` supprime l'entrée du cache et journalise
`[RELEASE] Context deleted successfully` (`classes/handlers/release.py:27-30`).
Un `Release` sur un contexte inconnu n'est **pas** une erreur :
`release_context` renvoie `False` sans lever (`:51-56` du cache), et la réponse
est un `ReleaseResponse` normal. Un client qui abandonne sans `Release` ne fuit
rien de durable : le process enfant meurt avec la connexion.

# Scénario 3 : New-ADUser puis Set-ADAccountPassword — écriture et mot de passe

```powershell
New-ADUser -Name adwsTest-User -SamAccountName adwsTest-User `
           -AccountPassword $pw -Enabled $true -Server dc1.samdom.example.com
Set-ADAccountPassword adwsTest-User -Reset -NewPassword $resetPw `
           -Server dc1.samdom.example.com
```

## Chronologie

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

Le rapport 623 octets en requête pour 73239 en réponse mérite d'être médité :
c'est un `Get` sans liste d'attributs, donc un objet complet, `*` plus les 17
attributs construits (`ConstructedAttrs.expand` avec une liste vide renvoie
`["*"] + CONSTRUCTED_ATTRIBUTES`, `classes/serialization/constructed_attrs.py:35-36`).
Un facteur d'amplification de 117 sur un seul objet utilisateur explique à lui
seul pourquoi la phase 5 du projet porte sur la performance.

## Le Create

La particularité d'ADWS est qu'un `Create` n'envoie **jamais** de
`distinguishedName` complet. La cible est décrite par son RDN et le DN de son
conteneur, sous les noms `relativeDistinguishedName` et
`container-hierarchy-parent` (les constantes du service ADWS Microsoft, repris en
`classes/handlers/create.py:23-25`).

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
 (`classes/parsing/body_parser.py:22-26`), `AttributeParser.parse_changes` en
 extrait une liste `{name, operation, values}`
 (`classes/parsing/attribute_parser.py:12-25`). Les préfixes `ad:`/`addata:`
 sont retirés (`:61-67`), et toute valeur typée `base64Binary` est décodée en
 `bytes` dès l'analyse (`:49-53`).
- `_resolve_dn` recompose `f"{rdn},{parent}"`
 (`classes/handlers/create.py:53-64`) ; un `distinguishedName` explicite, s'il
 est présent, l'emporte (`:60-61`).
- Les trois clés de routage sont **retirées** avant écriture
 (`DN_ROUTING`, `classes/handlers/create.py:23-25`, filtré en `:50`) : ce ne
 sont pas des attributs LDAP.
- `LdapAttrBuilder.build_message` construit le `ldb.Message` avec
 `FLAG_MOD_ADD` par défaut (`classes/handlers/create.py:32-34`,
 `classes/directory/ldap_attr_builder.py:19-30`). `unicodePwd` bénéficie d'un
 encodage spécial si la valeur arrive en texte : guillemets puis UTF-16LE
 (`classes/directory/ldap_attr_builder.py:15-16`).
- Le GUID est relu après création pour construire l'EPR
 (`classes/handlers/create.py:67-71`), avec un repli sur le GUID nul si la
 relecture échoue.

Réponse — c'est la forme exacte qui a débloqué `New-ADUser` :

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
`a:To` de la requête en remplaçant `ResourceFactory` par `Resource` (`:75-77`),
avec repli sur l'adresse anonyme WS-Addressing si le `a:To` est introuvable : le
client doit repartir sur le point de terminaison de ressource, pas sur celui de
fabrique. Les six points de terminaison sont figés côté Microsoft dans
les constantes du service ADWS Microsoft : `Resource` (`:26`), `ResourceFactory` (`:29`),
`Enumeration` (`:31`), `mex` (`:33`), `AccountManagement` (`:35`) et
`TopologyManagement` (`:37`).

## Le SetPassword

`Set-ADAccountPassword -Reset` emprunte une **action personnalisée**, pas
WS-Transfer. L'action est
`…/ActiveDirectory/CustomActions/AccountManagement/SetPassword`, résolue par le
routage sur le **dernier segment** d'URL
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
`ca:` ou par nom qualifié complet
(`classes/parsing/body_parser.py:34-38`), et `text_of` lit ses enfants de la
même façon (`:40-46`). Le mot de passe transite **en clair dans le XML** : sa
confidentialité repose intégralement sur le scellement GSSAPI de la phase 3, qui
est donc une exigence de sécurité et pas seulement de compatibilité.

L'écriture est un `FLAG_MOD_REPLACE` sur `unicodePwd`, valeur guillemetée puis
encodée en UTF-16LE (`classes/handlers/set_password.py:39-43`) — la convention
[MS-ADTS] pour la réinitialisation administrative.

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

Le corps est **vide mais non auto-fermé** (`classes/handlers/set_password.py:23`)
et redéclare le namespace CustomActions en défaut, sans préfixe : c'est la forme
que le client attend. Toute réponse passant par `SoapEnvelope.wrap` porte les
onze déclarations de `NS_DECL` (`classes/soap/soap_envelope.py:23-30`), même
celles qui n'en utilisent qu'une — c'est le cas ici. Les réponses construites à
la main (`GetResponse`, `EnumerateResponse`, `PullResponse`, `ReleaseResponse`)
ne déclarent, elles, que ce dont elles ont besoin :

| Réponse | Déclarations | Source |
|---|---|---|
| `GetResponse` | 7 (s, a, ad, addata, da, xsi, xsd) | `classes/handlers/get.py:281-289` |
| `EnumerateResponse` | 3 (s, a, wsen) | `classes/handlers/enumerate.py:111-113` |
| `PullResponse` | 7 (+ wsen, sans da) | `classes/handlers/pull.py:95-101` |
| `ReleaseResponse` | 2 (s, a) | `classes/handlers/release.py:45-46` |
| via `wrap` | 11 | `classes/soap/soap_envelope.py:23-30` |

## Le changement self-service, et pourquoi il échoue

`ChangePasswordHandler` construit la modification canonique — suppression de
l'ancien `unicodePwd`, ajout du nouveau, dans le **même** message ldb
(`classes/handlers/change_password.py:45-51`) — ce qui est la forme correcte
d'un changement authentifié par l'ancien mot de passe.

L'échec est en aval : le module Samba `password_hash` exige l'adresse réseau du
client (`remoteAddress`) sur ce chemin, information qu'une connexion `SamDB`
locale ne porte pas, et qu'on ne peut pas fabriquer depuis Python (un
`tsocket_address` n'a pas de constructeur exposé). L'erreur remontée est
`Failed to obtain remote address for the LDAP client`
(`documentation/05-tests.md:141-143`). Elle est convertie en faute
`ChangePasswordFault` par `custom_action_fault`
(`classes/handlers/change_password.py:27-29`). Le **reset administrateur
fonctionne** ; c'est le seul écart fonctionnel connu et documenté sur le
périmètre validé.

# Scénario 4 : un échec authentifié — anatomie d'une faute

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

## Chronologie

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
dispatcher. `DeleteHandler` intercepte lui-même l'exception ldb et retourne un
XML de faute comme s'il s'agissait d'une réponse normale
(`classes/handlers/delete.py:33-37`). Le dispatcher ne voit donc jamais
d'exception ; du point de vue de la couche NMF, l'échange est nominal.

## La faute complète

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
 (`classes/soap/soap_envelope.py:18`), c'est-à-dire l'URI **WS-Addressing 1.0**.
 `documentation/03-protocole.md:226` annonce l'URI 2004/08 : c'est une dérive
 documentaire, le code utilise bien 2005/08.
- `xml:lang` vaut `en-US` (`classes/soap/soap_envelope.py:54`), pas `en`.
- Le message est échappé par `html.escape(reason)`, avec `quote=True` par
 défaut : les apostrophes du message ldb deviennent `&#x27 ;`. C'est une
 référence de caractère numérique, valide en XML — contrairement aux entités
 nommées HTML qui avaient causé le bug des accents.
- `<s:Detail>` n'est émis que si un détail est fourni
 (`classes/soap/soap_envelope.py:56-57`).

## Les autres constructeurs de faute

Quatre familles coexistent, chacune avec son enveloppe de détail.

| Constructeur | `s:Code` | Détail | Fichier |
|---|---|---|---|
| `directory_error` | `s:Receiver` | `da:Fault` / ShortError+LongError | `faults.py:13` |
| `access_denied` | `s:Sender` | aucun | `faults.py:24` |
| `custom_action_fault` | `s:Receiver` | `<{Nom}Fault>` + Subcode `ca:` | `faults.py:28` |
| `invalid_enumeration_context` | `s:Sender` | aucun | `faults.py:43` |

`custom_action_fault` est la seule à poser un `<s:Subcode>` et à changer l'action
de faute pour `…/ActiveDirectory/Data/fault`
(`classes/faults/faults.py:38-41`, `src/soap/namespaces.py:13`) — c'est la forme
attendue pour les actions personnalisées. Son détail contient quatre éléments :
`ArgumentError` et `DirectoryError` en `xsi:nil="true"`, puis `Error` et
`ShortError` (`classes/faults/faults.py:31-37`).

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
 importées nulle part.** Seules les quatre constantes de namespace du haut du
 fichier (`:1-4`) le sont, par `typed_faults.py:4-10`. Les noms
 `CannotProcessFilter`, `EncodingLimit`, `FragmentDialectNotSupported`,
 `SchemaValidationError`, `AccessDenied`, `DestinationUnreachable`,
 `EndpointUnavailable`, `ActionNotSupportedFault`, `UnwillingToPerform`,
 `InvalidRepresentation`, `InvalidEnumerationContext`, `TimedOut`,
 `UnableToRenew`, `InvalidExpirationTime`,
 `FilterDialectRequestedUnavailable` et `EnumerationContextLimitExceeded` sont
 donc du vocabulaire déclaré, pas du vocabulaire émis.

> **Dérive documentaire à corriger.** `documentation/03-protocole.md:240-249`
> annonce des codes `DirectoryError`, `InsufficientAccessRights`,
> `ConstraintViolation`, `ObjectClassViolation`, `EntryAlreadyExists`,
> `NoSuchObject` dans `src/faults/fault_codes.py`. **Aucun de ces six noms n'est
> présent dans le fichier.** Ce qui circule réellement, c'est le `da:ShortError`
> que chaque handler choisit librement, sous forme de chaîne littérale.

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
`src/faults/fault_codes.py` — et encore, par recopie littérale, pas par import
de la constante. C'est exactement le genre d'écart qu'un audit de parité doit
réduire : le vocabulaire de faute doit venir d'un seul endroit.

## Le chemin d'erreur du dispatcher, et son point mortel

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

(`classes/handlers/dispatcher.py:52-55`). Le `if context else ""` est le point
mortel du protocole. Si l'exception survient **avant** que `context` soit
affecté — donc pendant `payload_to_xml` ou pendant `from_xml` — la faute
part avec `<a:RelatesTo></a:RelatesTo>` **vide**. PowerShell traite alors la
réponse comme non sollicitée et l'ignore : la cmdlet reste bloquée jusqu'à son
propre délai d'expiration, et le journal serveur ne montre aucune anomalie
au-delà de l'exception initiale.

Ce cas n'est pas théorique, il est présent deux fois dans `adws.log` :

- 09:36:27,244 — `UnicodeDecodeError` dans `build_dictionary` en lisant la table
 de session (`src/nettcp/protocol2xml.py:38`) : la faute part avec un
 `RelatesTo` vide, 793 octets.
- 10:00:04,643 — `ValueError: Failed to parse request XML: unbound prefix` levée
 par `RequestContext.from_xml` (`classes/parsing/context.py:169`) : même
 situation, 775 octets.

La règle de diagnostic qui en découle : **une cmdlet qui ne rend jamais la main
alors que le serveur a bien répondu signale presque toujours une erreur en amont
du parsing du contexte.** Chercher dans le journal une exception dont la trace
mentionne `payload_to_xml`, `build_dictionary` ou `from_xml`, pas le handler.

Le correctif structurel est simple et n'a pas encore été appliqué : extraire le
`MessageID` du XML brut par une expression régulière de repli avant de construire
le contexte, afin que `_fault` ait toujours une corrélation à renvoyer.

# Grille de diagnostic par symptôme

Les tables ci-dessous se lisent de gauche à droite : symptôme observable côté
Windows, couche à suspecter, vérification, correction.

## Transport et sécurité

| Symptôme Windows | Couche | Vérification | Correctif |
|---|---|---|---|
| `remote endpoint has terminated the transport stream` | GSSAPI | ligne `[SECURITY]` en erreur + NTSTATUS au journal | ajouter le SPN `host/<fqdn>` au compte machine |
| `STATUS_NO_SUCH_USER` (`0xC0000064`) côté serveur | Kerberos | `samba-tool spn list "$(hostname -s)$"` | `samba-tool spn add`, puis `klist purge` |
| même erreur, SPN correct | horloge | `timedatectl` vs `w32tm /query /status` | resynchroniser (dérive > 5 min = échec) |
| connexion fermée sans aucune trace serveur | réseau | `ss -tlnp` sur 9389, pare-feu | ouvrir 9389/tcp |
| échange coupé après la 1re réponse | délai socket | `settimeout(2)` en `protocol.py:164` | augmenter le délai si le client tarde |
| gros objet tronqué / token non désencapsulé | cadrage | `_PLAINTEXT_CHUNK` vs `0xFC30` | ne pas relever `_PLAINTEXT_CHUNK` |

## Encodage NMF / WCF

| Symptôme Windows | Couche | Vérification | Correctif |
|---|---|---|---|
| `ADServerDownException` sur une écriture accentuée | WCF decode | journal : `undefined entity` | `escape` limité aux 4 entités XML |
| `UnicodeDecodeError` dans `build_dictionary` | MS-NBFSE | trace mentionnant `protocol2xml.py:38` | payload désynchronisé : vérifier le descellement |
| `not well-formed (invalid token)` à l'encodage | WCF encode | trace `html_parser.py:38` | valeur non échappée injectée dans le XML |
| `unbound prefix` au parsing | SOAP | trace `context.py:169` | préfixe utilisé sans `xmlns:` dans la réponse |
| décodage manuel qui « réussit » sans rien produire | outillage | usage de `dump_records` sur des octets | utiliser `Record.parse` + `print_records` |

## Sérialisation et application

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
minuscules — observée telle quelle dans `adws.log`, ligne
`[ENUMERATE] Scope: subtree (ldb:2)` — est donc traitée comme `Subtree`. Sans
conséquence pour `subtree`, mais un `base` en minuscules deviendrait une
recherche de sous-arbre complète : plus lent, et sémantiquement faux.

## Découverte et environnement

| Symptôme Windows | Couche | Vérification | Correctif |
|---|---|---|---|
| `Unable to find a default server` | découverte | `nltest /dsgetdc:<domaine>` | vérifier DNS et SRV |
| idem, `nltest` OK mais `/ws` en `1355` | CLDAP Samba | `nltest /dsgetdc:<domaine> /ws` | limite Samba : passer `-Server` |
| ADAC refuse de se connecter | CLDAP Samba | même test `/ws` | utiliser ADUC (`dsa.msc`, LDAP direct) |
| cmdlet bloquée jusqu'au timeout | corrélation | `RelatesTo` vide dans la faute | erreur avant construction du contexte |

Le cas `1355` est structurel et **ne se corrige pas côté serveur** : le module
`ActiveDirectory` et ADAC appellent le DC locator avec
`DS_WEB_SERVICE_REQUIRED`, et Samba ne positionne pas le drapeau
`NBT_SERVER_ADS_WEB_SERVICE` (`0x2000`) dans sa réponse Netlogon/CLDAP. Le
projet fournit le service TCP 9389, pas l'annonce UDP 389. Le contournement
supporté est `-Server`.

## Séquence de diagnostic recommandée

- **1.** Le service écoute-t-il ? `ss -tlnp | grep 9389`, puis
 `python3 tools/test/test_adws.py` sur le DC.
- **2.** La logique répond-elle hors réseau ?
 `python3 tools/test/test_handlers.py` — si `RelatesTo echoed` échoue, arrêter
 là, rien d'autre ne fonctionnera.
- **3.** Le préambule et Kerberos passent-ils ? Chercher
 la ligne `[SECURITY]` portant `GSSAPI negotiation completed` dans le journal.
- **4.** Le message arrive-t-il jusqu'à un handler ? Chercher
 `[DISPATCH] handler=` — son absence désigne l'encodage ou le parsing.
- **5.** Le handler produit-il une faute ? Chercher `ERROR` puis le
 `da:ShortError` correspondant.
- **6.** Rejouer la suite complète : `Test-ADWS-Sovereign.ps1 -SkipMutations`,
 puis sans l'option.

# Journalisation côté serveur

## Configuration effective

Tout part de `Config` (`classes/server/config.py:36-83`). Le journal est piloté
par trois variables d'environnement, lues à la construction :

| Variable | Défaut | Effet | Ligne |
|---|---|---|---|
| `ADWS_LOG_FILE` | `adws.log` | chemin du fichier | `config.py:45` |
| `ADWS_LOG_LEVEL` | `INFO` | niveau du logger `adws` | `config.py:46-47` |
| `ADWS_HOST` | `0.0.0.0` | interface d'écoute | `config.py:41` |
| `ADWS_PORT` | `9389` | port d'écoute | `config.py:42` |

Le service systemd les fixe via `/etc/default/samba-adws`
(`tools/installation/install.sh:81-87`) : `ADWS_LOG_FILE=/var/log/samba-adws/adws.log`
et `ADWS_LOG_LEVEL=INFO`. L'unité tourne en `WorkingDirectory` = répertoire
d'installation, en `root`, avec `Restart=on-failure`
(`tools/installation/samba-adws.service`). Lancé à la main par
`python3 -m src.main`, le fichier `adws.log` est créé dans le répertoire courant.

`setup_logging` (`classes/server/config.py:50-77`) installe **deux** handlers sur
le logger nommé `adws` :

| Handler | Niveau | Destination | Rotation |
|---|---|---|---|
| `StreamHandler` | `INFO` | stderr → journald | — |
| `RotatingFileHandler` | `DEBUG` | `ADWS_LOG_FILE` | 10 Mo × 5 |

Attention au piège classique : le niveau du **logger** (`setLevel(self.logging.level)`,
`config.py:56`) prime sur celui des handlers. Le handler fichier est configuré en
`DEBUG` (`config.py:71`) mais ne verra jamais de `DEBUG` tant que
`ADWS_LOG_LEVEL` reste à `INFO`. Passer en verbeux se fait donc **uniquement**
par la variable d'environnement, pas en touchant les handlers.

Format : `%(asctime)s - %(name)s - %(levelname)s - %(message)s`
(`classes/server/config.py:34`). Les modules obtiennent un logger enfant par
`config.get_logger(name)` (`:79-83`) ; en pratique tout le service utilise
`adws.server`, créé une fois dans `ADWSServer.__init__`
(`classes/server/server.py:17`) et transmis au dispatcher puis aux handlers.

## Anatomie d'une session dans le journal

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

Cette séquence est le gabarit de référence : toute panne se localise en trouvant
**la dernière ligne atteinte**.

| Dernière ligne vue | Couche fautive |
|---|---|
| pas de `GSSAPI negotiation completed` | Kerberos / SPN |
| message reçu, pas de `[DISPATCH] action=` | encodage WCF ou parsing SOAP |
| `[DISPATCH] action=` sans `[DISPATCH] handler=` | action inconnue du routage |
| `[DISPATCH] handler=` puis `ERROR` | logique du handler ou droits AD |

## Ce qui échappe au logger

Trois flux ne passent pas par `adws`, ce qui explique des « logs manquants ».

- **Le dictionnaire de session.** `build_dictionary` utilise `print`, pas le
 logger (`src/nettcp/protocol2xml.py:33` et `:47`). Chaque message entrant
 écrit donc sur **stdout** une ligne `Dictionary table: N bytes`, suivie d'une
 ligne par chaîne de session. Ces lignes atterrissent dans `journalctl` mais
 **jamais** dans `adws.log`. C'est une source de bruit notable sur un DC chargé
 et, accessoirement, un point d'observation gratuit sur le trafic entrant.
- **Le code vendoré.** `src/wcf/records/text.py:61` appelle
 `logging.basicConfig(level=logging.INFO)` à l'import, ce qui configure le
 logger **racine**. Les journaux `DEBUG` de `src/wcf/` et `src/nettcp/`
 (encodage record par record, hexdumps) restent donc muets tant qu'on ne relève
 pas explicitement le niveau racine.
- **Les hexdumps de socket.** `SocketStream` sait tracer les octets lus et écrits
 (`src/nettcp/stream/socket.py:41-49`) mais uniquement si la bibliothèque
 optionnelle `helperlib` est installée **et** le logger en `DEBUG`. Sans elle,
 `print_hexdump` vaut `False` et la trace est silencieusement désactivée
 (`:10-14`).

## Passer en mode verbeux

```bash
sudo sed -i 's/^ADWS_LOG_LEVEL=.*/ADWS_LOG_LEVEL=DEBUG/' /etc/default/samba-adws
sudo systemctl restart samba-adws
sudo journalctl -u samba-adws -f
```

En `DEBUG`, on gagne les lignes `[SEND] <RecordName> (N bytes)`
(`classes/server/protocol.py:187`), les `[MESSAGES]` de `Connection timeout`
(`:117`), la trace du `PreambleEndRecord` reçu (`:134`) et les
`Failed to search DN …` de la boucle de résolution du Get
(`classes/handlers/get.py:240`).

Pour la couche vendorée, il faut en plus relever le logger racine, par exemple
en ajoutant temporairement `logging.getLogger.setLevel(logging.DEBUG)` juste
après l'appel à `config.setup_logging` (`src/main.py:11`).

## Limites de la journalisation actuelle

Trois manques documentés, tous confirmés dans le code :

- **Pas d'identifiant de process.** Le format
 (`classes/server/config.py:34`) ne contient ni `%(process)d` ni identifiant de
 connexion. Comme le serveur est un `ForkingTCPServer`, les lignes de
 connexions concurrentes s'entrelacent dans le même fichier sans moyen de les
 démêler. Sur un DC réel où PowerShell ouvre une connexion par cmdlet, c'est la
 gêne principale. Ajouter `%(process)d` au format est un correctif d'une ligne.
- **Pas de rotation côté journald.** Le `RotatingFileHandler` gère 10 Mo × 5
 (`classes/server/config.py:31-33`), mais la sortie console est dupliquée
 intégralement dans le journal systemd, sans plafond propre.
- **Le corps applicatif n'est jamais journalisé.** Ni la requête XML ni la
 réponse ne sont écrites, à aucun niveau. C'est défendable — les
 `SetPasswordRequest` contiennent des mots de passe en clair — mais cela impose
 l'instrumentation temporaire décrite en début de chapitre pour tout incident
 de sérialisation. Une piste propre serait un niveau `TRACE` dédié, écrivant le
 XML avec un masquage des éléments `NewPassword`, `OldPassword` et
 `unicodePwd`.

Ces trois points sont des candidats naturels pour la phase 5 (performance et
durcissement), au même titre que le repli sur le `MessageID` évoqué au
scénario 4.
