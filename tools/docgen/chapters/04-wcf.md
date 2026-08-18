# Pourquoi un XML binaire

Le service ADWS ne transporte pas du XML texte. Entre le cadrage .NET Message Framing
(`[MS-NMF]`, couche traitée au chapitre précédent) et l'enveloppe SOAP 1.2 se glisse une
couche de sérialisation propriétaire : le *.NET Binary Format: XML Data Structure*,
spécifié par `[MS-NBFX]`, complété par le *.NET Binary Format: SOAP Data Structure*
(`[MS-NBFS]`, la table de chaînes prédéfinie) et par son extension de session
`[MS-NBFSE]`.

Trois raisons expliquent ce choix côté Microsoft.

- **Le balisage.** Une réponse ADWS est extrêmement répétitive : les mêmes URI
 d'espaces de noms et les mêmes noms d'éléments (`Envelope`, `Header`, `Body`,
 `Action`, `MessageID`, `RelatesTo`) reviennent dans chaque message. `[MS-NBFS]`
 remplace chacune de ces chaînes par un index d'un ou deux octets.
- **Le re-parsing.** Un lecteur binaire n'a pas de tokenizer : il lit un octet de type,
 dont il déduit la structure et la longueur exacte de la charge utile.
- **Le typage.** Un `xsd:int` circule sur 4 octets, un `xsd:dateTime` sur 8, un GUID
 sur 16 ; le type est porté par l'octet de record, sans reconversion de texte.

Ce n'est pas une optimisation optionnelle. Le client annonce l'encodage dans le
`KnownEncodingRecord` du préambule NMF (`src/nettcp/nmf.py:321`), dont les valeurs
possibles sont énumérées en `src/nettcp/nmf.py:178` : `UTF8 = 3`, `UTF16 = 4`,
`UNICODE_LITTL_ENDIAN = 5`, `MTOM = 6`, `BINARY = 7`, `BINARY_DICT = 8`. Le module
`ActiveDirectory` demande le binaire avec dictionnaire de session ; le serveur ne
négocie rien, il subit. Toute la couche `src/wcf/` existe pour honorer ce contrat.

> `documentation/03-protocole.md` indique `encoding=BINARY_WITH_DICT (3)` dans son
> tableau de préambule. La valeur `3` correspond en réalité à `UTF8` dans
> `src/nettcp/nmf.py:179` ; la valeur du binaire avec dictionnaire est `8`.
> Le comportement du code (voir la section MS-NBFSE plus bas) confirme que le mode
> réellement pratiqué est bien `BINARY_DICT`. La valeur exacte de l'octet envoyé par le
> client n'est pas journalisée par ce projet : elle n'est **pas vérifiable dans le code**.

### Gain mesuré sur ce dépôt

L'encodeur du projet a été exécuté sur une enveloppe de réponse réellement produite
par `SoapEnvelope.wrap` (`classes/soap/soap_envelope.py:33`), avec l'action
`.../transfer/GetResponse`, un `RelatesTo` de type `urn:uuid:` et un corps réduit à
`<ad:distinguishedName>CN=Administrator,CN=Users,DC=example,DC=com</ad:distinguishedName>` :

| Représentation | Taille | Rapport |
|---|---|---|
| XML texte minifié (sortie de `wrap`) | 1057 caractères | 100 % |
| Records MS-NBFX (`dump_records`) | 734 octets | 69 % |

Le gain est réel mais bien inférieur à ce que le format permet, pour deux raisons
propres à cette implémentation, détaillées plus loin : les sept espaces de noms
non indexés déclarés par `SoapEnvelope.NS_DECL` ne figurent pas dans la table
`[MS-NBFS]` (**451 octets** mesurés, fixes, sur chaque enveloppe), et l'encodeur
choisit systématiquement des records texte UTF-16 (`UnicodeChars*`) là où la variante
UTF-8 (`Chars*`), tout aussi conforme, suffirait — ce qui double le volume de chaque
valeur textuelle latine.

# Modèle de données MS-NBFX

## Un flux, pas un arbre

Un document MS-NBFX est une **suite linéaire de records**. Il n'y a ni en-tête de
document, ni longueur globale, ni table des matières : le premier octet du flux est
déjà le type du premier record. La structure arborescente est reconstruite par le
lecteur au fil de la lecture, comme dans un flux SAX.

Chaque record commence par **un octet de type**, suivi d'une charge utile dont la forme
est entièrement déterminée par ce type. Il n'y a pas de longueur générique : un lecteur
qui ne connaît pas un type ne peut pas le sauter. C'est exactement le comportement de
`Record.parse` (`src/wcf/records/base.py:103`) : une boucle qui lit un octet, cherche la
classe correspondante dans la table `Record.records` (`src/wcf/records/base.py:42`), et
délègue le décodage de la charge utile à cette classe.

Trois familles de records structurent le document :

| Famille | Plage d'octets | Nombre | Rôle |
|---|---|---|---|
| Contrôle | 0x01 – 0x03 | 3 | EndElement, Comment, Array |
| Attributs | 0x04 – 0x3F | 60 | attributs et déclarations d'espaces de noms |
| Éléments | 0x40 – 0x77 | 56 | balises ouvrantes |
| Texte | 0x80 – 0xBC (pairs) | 31 | contenu typé (nœuds texte et valeurs d'attributs) |

Comptage exécuté sur la table de correspondance après import complet du paquet :
`Record.records` contient exactement **150 entrées**, et **106** des 256 valeurs
d'octet possibles n'y figurent pas. La plage 0x78 – 0x7F n'est utilisée par aucun
record dans cette implémentation ; elle est absente des trois modules `elements.py`,
`attributes.py` et `text.py`.

## L'ordre canonique

MS-NBFX impose un ordre strict, que l'implémentation reproduit :

- **1.** le record d'élément (nom + préfixe),
- **2.** zéro ou plusieurs records d'attribut, immédiatement à la suite,
- **3.** le contenu (records de texte et records d'éléments enfants),
- **4.** un `EndElementRecord` (0x01), sauf si le dernier record de contenu portait le
 bit *WithEndElement* (voir plus bas).

Cet ordre est visible dans `ShortElementRecord.to_bytes`
(`src/wcf/records/elements.py:68`), qui sérialise son propre octet de type, son nom,
puis boucle sur `self.attributes`. Côté lecture, `Record.parse`
(`src/wcf/records/base.py:120`) rattache tout record d'attribut au dernier élément
rencontré (`last_el`), ce qui est correct **tant que** le producteur respecte l'ordre
canonique. Un attribut émis après un enfant serait silencieusement rattaché au mauvais
parent — le décodeur du projet ne détecte pas cette violation.

## Les types dérivés

Trois primitives non-record servent de briques à tous les records.

### MultiByteInt31

Entier non signé sur 31 bits, encodé en base 128, **petit-boutiste par groupes de
7 bits**, le bit de poids fort de chaque octet servant de bit de continuation
(`src/wcf/datatypes.py:3`). C'est le même principe que le `varint` de MS-NMF, mais les
deux implémentations sont distinctes dans ce dépôt (`src/nettcp/nmf.py:43` pour NMF,
`src/wcf/datatypes.py:7` pour NBFX).

Algorithme d'écriture (`src/wcf/datatypes.py:7`) : tant que la valeur dépasse 0x7F,
émettre `(valeur & 0x7F) | 0x80` et décaler de 7 bits ; émettre enfin `valeur & 0x7F`.

| Valeur | Octets | Détail |
|---|---|---|
| 0 | `00` | tient sur 7 bits |
| 1 | `01` | |
| 127 | `7F` | dernière valeur sur 1 octet |
| 128 | `80 01` | `0x80` = 0 + continuation, puis `0x01` = 1 x 128 |
| 300 | `AC 02` | `0x2C` = 44, plus `2 x 128` = 256, total 300 |
| 972 | `CC 07` | `0x4C` = 76, plus `7 x 128` = 896, total 972 |
| 16384 | `80 80 01` | 0 + 0 + `1 x 128^2` |

La valeur 972 est celle du dernier index du dictionnaire statique du projet : tous les
index de la table `[MS-NBFS]` tiennent donc sur **deux octets au plus**.

Le décodeur (`src/wcf/datatypes.py:21`) boucle sur `range(5)`, donc lit au maximum
5 octets, ce qui autorise 35 bits alors que la spécification n'en définit que 31.
Aucun contrôle de dépassement n'est effectué : un flux corrompu produira un index
aberrant plutôt qu'une erreur. Il ne signale pas non plus la fin de flux prématurée
(`if not b: break`, `datatypes.py:25`), qui rend simplement la valeur partielle
accumulée.

### Utf8String

Chaîne préfixée d'un `MultiByteInt31` donnant sa longueur **en octets** (pas en
caractères), suivie des octets UTF-8 (`src/wcf/datatypes.py:34`). Exemple vérifié :
`Utf8String('Envelope').to_bytes` produit `08 45 6E 76 65 6C 6F 70 65`.

C'est la forme employée pour tous les noms d'éléments, noms d'attributs et préfixes
littéraux.

### Decimal

Structure `DECIMAL`.NET sur 16 octets, reproduite par `src/wcf/datatypes.py:55` :

| Champ | Taille | Contenu |
|---|---|---|
| réservé | 2 octets | toujours `00 00` à l'écriture |
| scale | 1 octet | exposant décimal, 0 à 28 (contrôlé ligne 57) |
| sign | 1 octet | `0x80` si négatif, `0x00` sinon |
| high | 4 octets LE | bits 64 à 95 de la mantisse |
| low | 8 octets LE | bits 0 à 63 de la mantisse |

La valeur est `(high x 2^64 + low) / 10^scale`, éventuellement niée
(`src/wcf/datatypes.py:74`). Exemple vérifié : `Decimal(False, 0, 1337, 3)` sérialise en
`00 00 03 00 00 00 00 00 39 05 00 00 00 00 00 00` et se relit `1.337`.

## Ce que MS-NBFX ne transporte pas

Le format ne code que l'*infoset* utile. Sont absents du modèle :

- la déclaration XML (`<?xml version="1.0" encoding="utf-8"?>`) — elle est produite par
 `SoapEnvelope.wrap` (`classes/soap/soap_envelope.py:35`) puis **perdue** à
 l'encodage, ce qui est conforme et sans conséquence ;
- les instructions de traitement et les DTD ;
- les sections CDATA en tant que telles : leur contenu devient du texte ordinaire ;
- l'espace blanc non significatif entre éléments.

# Records de structure : éléments, attributs, espaces de noms

## Records d'élément

Quatre formes générales, plus deux familles de 26 raccourcis par lettre de préfixe.
Toutes sont définies dans `src/wcf/records/elements.py`.

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
(`elements.py:321-335` et `elements.py:337-351`). La lettre du préfixe se déduit de
l'octet : `chr(c - 0x44 + ord('a'))` pour la première famille,
`chr(c - 0x5E + ord('a'))` pour la seconde. Le préfixe est donc toujours **une seule
lettre minuscule** : c'est la raison pour laquelle les conventions de préfixe des
messages WCF privilégient des noms d'une lettre. Sur les enveloppes produites par ce
dépôt, seuls `s` et `a` empruntent effectivement ces raccourcis ; la fréquence des
autres lettres dans le trafic entrant Windows n'a **pas été mesurée** sur ce projet.

`ShortElementRecord.__init__` refuse le nom `xmlns` par une **assertion**
(`elements.py:64`, `assert name != 'xmlns'`) : une déclaration d'espace de noms n'est
jamais un élément, elle possède ses propres records. Cette garde disparaît sous
`python3 -O`, qui désactive les `assert` ; elle ne constitue donc pas une validation
d'entrée fiable.

## Records d'attribut

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

- **La valeur d'un attribut est elle-même un record de texte.** `ShortAttributeRecord`
 ne stocke pas une chaîne mais un objet `Text` (`attributes.py:57`), qu'il sérialise
 par `self.value.to_bytes` (`attributes.py:66`) et dont l'octet de type est relu
 récursivement à l'analyse (`attributes.py:86`). Une valeur `"1"` coûte donc **un
 seul octet** : `0x82`, le `OneTextRecord` — vérifié sur le dump de l'exemple
 complet, segment `1E 00 82`.
- **Les records `xmlns*` n'ont pas de valeur texte.** L'URI est soit un `Utf8String`
 littéral, soit un index de dictionnaire. Il n'y a **aucune** famille
 `PrefixDictionaryXmlns[A-Z]` ni `PrefixXmlns[A-Z]` : ni MS-NBFX ni cette
 implémentation ne définissent de raccourci par lettre pour les déclarations
 d'espaces de noms. Le préfixe d'une déclaration `xmlns:x` est toujours écrit en clair
 sous forme de `Utf8String` (`attributes.py:271` pour la variante indexée,
 `attributes.py:340` pour la variante littérale).

## Table exhaustive des raccourcis par lettre

Les quatre familles générées couvrent exactement les 26 lettres `a` à `z`, sans trou.

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
`<s:` + nom de dictionnaire (le préfixe SOAP), `0x44` est `<a:` + nom de dictionnaire
(le préfixe WS-Addressing). Ces deux octets ouvrent la quasi-totalité des messages ADWS.

## Règles de choix appliquées par l'encodeur du projet

`XMLParser._parse_tag` (`src/wcf/xml2records.py:75`) applique l'arbre de décision
suivant, dans cet ordre :

- nom qualifié avec préfixe **d'une seule lettre** :
 - nom local présent dans le dictionnaire → `PrefixDictionaryElement<L>Record` ;
 - sinon → `PrefixElement<L>Record`.
- nom qualifié avec préfixe **de plusieurs lettres** :
 - nom local dans le dictionnaire → `DictionaryElementRecord` ;
 - sinon → `ElementRecord`.
- nom sans préfixe :
 - dans le dictionnaire → `ShortDictionaryElementRecord` ;
 - sinon → `ShortElementRecord`.

`XMLParser._parse_attr` (`src/wcf/xml2records.py:183`) suit la même logique, avec une
branche dédiée aux déclarations : `xmlns:x` donne `DictionaryXmlnsAttributeRecord` ou
`XmlnsAttributeRecord` selon que l'URI est indexée, `xmlns` nu donne les variantes
`Short*`.

Conséquence directe et mesurable : les préfixes ADWS multi-lettres (`ad`, `da`,
`addata`, `adlq`, `wsen`, `wst`, `ca`, `xsi`, `xsd`, déclarés dans la table
`ENV_NS_MAP` de `src/soap/namespaces.py:18`) **ne bénéficient jamais** des raccourcis
0x44-0x5D. Chaque balise `<addata:cn>` transporte donc 7 octets rien que pour le
préfixe (1 octet de longueur `MultiByteInt31` plus les 6 octets UTF-8 de `addata`),
auxquels s'ajoutent le nom local et l'octet de type. C'est un axe d'optimisation
identifié pour la phase 5, sans risque d'interopérabilité : le choix du préfixe est
libre du côté émetteur, seul l'URI d'espace de noms fait foi.

## EndElement, Comment, Array

| Record | Octet | Statut dans ce projet |
|---|---|---|
| `EndElementRecord` | 0x01 | implémenté, émis et lu |
| `CommentRecord` | 0x02 | lu ; **jamais émis** |
| `ArrayRecord` | 0x03 | lu ; **jamais émis** |

**`EndElementRecord`** (`src/wcf/records/base.py:151`) ne porte aucune charge utile :
c'est l'octet `0x01` seul. Il ferme le dernier élément ouvert. À la lecture
(`base.py:110`) il provoque un `parents.pop`, donc un retour d'un niveau ; il n'est
pas ajouté à l'arbre. À l'écriture, `dump_records` (`src/wcf/records/__init__.py:117`)
en émet un après les enfants d'un élément **sauf** si le dernier enfant était un record
de texte (auquel cas c'est le bit *WithEndElement* qui a fait le travail).

**`CommentRecord`** (`base.py:155`) porte un `Utf8String`. Le décodage fonctionne :
`b'\x02\x05hello'` se relit `<!-- hello -->`. L'encodage est en revanche **hors
d'atteinte** : `XMLParser.handle_comment` (`src/wcf/xml2records.py:274`) référence une
variable `data` non définie et lèverait un `NameError`, mais la question ne se pose pas
car le parseur Expat de `src/wcf/html_parser.py:27` n'enregistre que
`StartElementHandler`, `EndElementHandler` et `CharacterDataHandler` : aucun
`CommentHandler` n'est posé, donc les commentaires du XML sortant sont silencieusement
ignorés. Sans conséquence : le serveur ne produit pas de commentaires.

**`ArrayRecord`** (`base.py:184`) encode une répétition homogène : un record d'élément
modèle, ses attributs, un `EndElement`, l'octet du type de texte répété (toujours la
variante *WithEndElement*, cf. la table `datatypes` de `base.py:187`), un
`MultiByteInt31` de cardinalité, puis les charges utiles concaténées **sans leur octet
de type** (`base.py:228`). Vérification effectuée :

```text
03 40 04 69 74 65 6D 01 8D 02 01 00 00 00 02 00 00 00
 |  |___________________|  |  |  |___________|___________|
 |          |             |  |        deux Int32 bruts
 |          |             |  cardinalite = 2
 |          |             type repete 0x8D = Int32TextWithEndElement
 |          ShortElement "item" + EndElement
 ArrayRecord
```

Ce flux se relit `<item>1</item><item>2</item>`. Deux limites relevées : le paramètre
`attributes` de `ArrayRecord.__init__` est reçu puis **écrasé** par une liste vide
(`base.py:211`), donc les attributs d'un tableau reçu sont perdus au décodage ; et
l'encodeur du projet ne produit jamais de tableau, ce qui est conforme mais laisse la
compaction des grosses listes d'attributs multi-valués inexploitée.

> Le décodeur ne signale pas les octets inconnus : `Record.parse` se contente d'un
> `log.warn('type 0x%x not found')` (`src/wcf/records/base.py:134`) et **poursuit** la
> lecture à l'octet suivant. Un flux désaligné produit donc du XML plausible mais faux,
> et non une erreur franche. C'est le premier réflexe à avoir face à une réponse
> incohérente.

# Records de texte : catalogue des types primitifs

## La convention de l'octet impair

C'est la règle la plus importante du format, et la plus facile à manquer.

Tous les records de texte occupent une valeur **paire** entre 0x80 et 0xBC. La valeur
**impaire immédiatement supérieure** (`type + 1`) désigne le *même* record, avec la
même charge utile, suivi d'un `EndElement` implicite. `[MS-NBFX]` les nomme
`<Type>WithEndElement` : `Chars8Text` = 0x98, `Chars8TextWithEndElement` = 0x99.

Cela économise un octet par élément feuille — soit, sur une réponse ADWS qui contient
plusieurs centaines de `<ad:value>`, plusieurs centaines d'octets.

L'implémentation ne crée **pas** de classes distinctes pour les variantes impaires.
Elle traite la convention aux deux extrémités :

- **En lecture** (`src/wcf/records/base.py:125`) : si l'octet lu n'est pas dans la table
 `Record.records`, le décodeur essaie `type - 1`. Si cette classe existe, il l'utilise
 pour décoder la charge utile, puis exécute un `parents.pop` — exactement l'effet
 d'un `EndElement`.
- **En écriture** (`src/wcf/records/__init__.py:104`) : `dump_records` incrémente
 `r.type` de 1 lorsque `r` est le **dernier** record d'une liste de frères **et** que
 c'est un `Text`.

Cette convention est non ambiguë uniquement dans la plage 0x80-0xBD, où seuls les
octets pairs sont attribués. Dans les plages de structure (0x01-0x77), les octets pairs
et impairs sont tous deux attribués à des records distincts : `0x41` n'est pas
`0x40 WithEndElement`, c'est `ElementRecord`. Le test `type - 1 in Record.records`
n'est donc jamais atteint pour ces octets-là, puisqu'ils sont trouvés dès la première
branche.

> **Un faux positif vérifié.** Le repli `type - 1` n'est pas restreint à la plage
> texte : il s'applique à tout octet absent de la table. Énumération exhaustive des
> 256 valeurs, exécutée sur `Record.records` : 32 octets non attribués ont leur
> prédécesseur attribué, dont 31 sont les variantes texte *WithEndElement* légitimes
> (0x81, 0x83,..., 0xBD) — et **un seul** est une aberration : `0x78`, dont le
> prédécesseur `0x77` est `PrefixElementZRecord`. Un octet `0x78` reçu, qui n'est
> défini par aucun record, est donc silencieusement décodé comme un
> `PrefixElementZRecord` suivi d'un `EndElement`, et le décodeur consomme derrière lui
> un `Utf8String` qui n'existe pas. Les 74 autres octets non attribués (0x00,
> 0x79-0x7F, 0xBE-0xFF) tombent bien dans la branche d'avertissement.

> **Défaut vérifié : `dump_records` n'est pas idempotent.** L'incrémentation de
> `src/wcf/records/__init__.py:105` mute l'objet en place. Encoder deux fois le même
> arbre donne deux résultats différents : sur l'enveloppe de test, le premier appel
> produit `... B7 02 78 00...` (`UnicodeChars8TextWithEndElement`), le second produit
> `... B8 02 78 00...` — soit `UnicodeChars16Text`, dont la longueur se lit sur
> 2 octets. Le message devient illisible pour le client. Un arbre de records est donc à
> usage unique ; il ne doit jamais être mis en cache et réémis.

## Catalogue exhaustif

Les 31 records de texte définis dans `src/wcf/records/text.py`, dans l'ordre des octets.
La colonne « +EE » donne la variante *WithEndElement*.

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

Les longueurs des records `Chars*`, `Bytes*` et `UnicodeChars*` sont exprimées **en
octets**, jamais en caractères : `UnicodeChars8TextRecord.to_bytes`
(`src/wcf/records/text.py:284`) encode d'abord en UTF-16LE puis compte les octets
obtenus. Une chaîne latine de 58 caractères occupe donc 116 octets et tient tout juste
dans la variante 8 bits.

Trois records ne définissent ni `to_bytes`, ni `parse`, ni `__str__` :
`StartListTextRecord` (`text.py:824`), `EndListTextRecord` (`text.py:828`) et
`EmptyTextRecord` (`text.py:832`). Leurs corps de classe se réduisent à la ligne
`type = 0x..`. Ils héritent donc de `Record.to_bytes` (`base.py:58`), qui émet l'octet
nu, et de `Record.parse` (`base.py:96`), qui renvoie `cls` sans rien consommer :
sur ces deux points le comportement est correct.

> **Défaut vérifié : rendu textuel absent.** Ces trois classes n'ayant pas de
> `__str__`, `str(record)` retombe sur `Record.__repr__` (`base.py:70`). Contrôle
> exécuté sur le flux `40 04 74 65 73 74 A9 01`, soit `<test>` suivi d'un
> `EmptyTextWithEndElement` : `print_records` produit
> `<test><EmptyTextRecord(type=0xA8)></test>` au lieu de `<test></test>`. Même
> symptôme pour `A4`/`A6`, qui donnent `<StartListTextRecord(type=0xA4)>` et
> `<EndListTextRecord(type=0xA6)>`. Le XML texte intermédiaire est alors invalide au
> sens de l'infoset attendu, et le nom de classe se retrouve interprété comme un
> élément par `ET.fromstring`. Le défaut est **latent** : l'encodeur ne produit jamais
> ces records — `_store_data` (`src/wcf/xml2records.py:109`) écarte explicitement les
> `EmptyTextRecord` — et le module `ActiveDirectory` de PowerShell n'en émet pas non
> plus dans les échanges observés sur ce dépôt. Il se réveillerait avec un client
> utilisant les listes typées de `[MS-NBFX]`.

## Correction du tableau de la documentation existante

Le tableau « type XSD vers record » de `documentation/03-protocole.md:89-94` contient
trois erreurs, relevées par confrontation directe avec `src/wcf/records/text.py`.
Elles sont reproduites ci-dessous avec leur valeur exacte, afin qu'un lecteur qui
partirait de l'ancienne documentation ne cherche pas un record inexistant dans un dump.

| Ligne | Affirmation de `03-protocole.md` | Valeur exacte |
|---|---|---|
| 89 | `Int32TextRecord` = 0x88 | 0x88 est `Int8TextRecord` ; `Int32` = **0x8C** |
| 90 | `Int64TextRecord` = 0x8a | 0x8A est `Int16TextRecord` ; `Int64` = **0x8E** |
| 94 | `GuidTextRecord` (0xb0) | la classe s'appelle **`UuidTextRecord`** ; 0xB0 est juste |

Seule la troisième est bénigne : l'octet est correct, seul le nom de classe est erroné
(`text.py:716`). Les deux premières décalent la lecture d'un dump de plusieurs octets,
puisque `Int8` consomme 1 octet de charge utile là où `Int32` en consomme 4.

## Records réellement produits par l'encodeur

Le catalogue ci-dessus décrit ce que le **décodeur** sait lire. L'**encodeur** de ce
projet, lui, n'emprunte qu'un sous-ensemble : recherche exhaustive des instanciations
dans `src/wcf/xml2records.py`.

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

## Encodages particuliers

### DateTime : ticks .NET et DateTimeKind

Une valeur `xsd:dateTime` est un entier 64 bits little-endian dont :

- les **62 bits de poids faible** portent le nombre de *ticks*, un tick valant 100 ns,
 comptés depuis `0001-01-01T00:00:00` ;
- les **2 bits de poids fort** portent le `DateTimeKind`.NET.

L'écriture est faite en une expression (`src/wcf/records/text.py:559`) :
`((self.tz & 3) << 62) | (self.value & 0x3FFFFFFFFFFFFFFF)`, empaquetée en `<Q`. La
lecture inverse (`text.py:575-576`) : `tz = data >> 62`,
`value = data & 0x3FFFFFFFFFFFFFFF`.

| Valeur de `tz` | Signification | Émis par ce projet pour |
|---|---|---|
| 0 | `Unspecified` | horodatage sans suffixe |
| 1 | `Utc` | suffixe `Z` |
| 2 | `Local` | décalage explicite `+hh:mm` / `-hh:mm` |
| 3 | non utilisé | jamais produit |

La détection du suffixe est faite par `_parse_datetime_to_ticks`
(`src/wcf/xml2records.py:29`) : `Z` final donne `tz = 1` ; une chaîne d'au moins
6 caractères dont le sixième en partant de la fin (`head[-6]`) est `+` ou `-` et dont
le troisième en partant de la fin (`head[-3]`) est `:` donne `tz = 2` ; sinon
`tz = 0` (`xml2records.py:32-37`). La conversion en ticks utilise la constante
`_DOTNET_EPOCH_OFFSET_SECONDS = 62135596800` (`src/wcf/xml2records.py:26`), soit le
nombre de secondes entre `0001-01-01` et l'époque Unix.

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
`1970-01-01T00:00:00` — donc l'époque Unix (`text.py:539`) — et la charge utile
`FF 3F 37 F4 75 28 CA 2B`, soit `0x2BCA2875F4373FFF` en petit-boutiste, vaut
`9999-12-31T23:59:59.999999` (`text.py:567`).

> **Écart vérifié.** `DatetimeTextRecord.__str__` (`text.py:537`) ignore
> `self.tz` : il reconstruit la date à partir des seuls ticks et rend un ISO 8601 **sans
> suffixe**. Une requête client portant `2026-08-07T10:00:00Z` est donc restituée
> `2026-08-07T10:00:00` au XML texte intermédiaire, et la couche `classes/parsing/`
> ne voit jamais le `Z`. Contrôle exécuté sur un aller-retour complet
> `<a:V>2026-08-07T10:00:00Z</a:V>` : le record émis est bien un `0x97`
> (`DatetimeTextWithEndElement`) porteur de `tz = 1`, mais la relecture par
> `print_records` rend `<a:V>2026-08-07T10:00:00</a:V>`. Le chemin d'écriture
> (serveur vers client) est donc correct sur le fil : le défaut est purement dans le
> rendu textuel, et unidirectionnel.
>
> Second écart, même méthode : `datetime.timedelta(microseconds=ticks // 10)` perd les
> ticks non multiples de 10, soit une résolution ramenée de 100 ns à 1 microseconde.
> Sans impact sur les attributs AD, dont la granularité utile est la seconde.

### TimeSpan

Entier signé 64 bits little-endian, en ticks de 100 ns, écrit tel quel
(`src/wcf/records/text.py:847`).

> **Défaut vérifié.** `TimeSpanTextRecord.__str__` (`text.py:851`) calcule
> `datetime.timedelta(milliseconds=self.value / 10)`. Or `value / 10` est un nombre de
> **microsecondes**, pas de millisecondes : le rendu est mille fois trop grand. Contrôle
> exécuté : `TimeSpanTextRecord(36000000000)`, qui vaut exactement une heure
> (3600 x 10^7 ticks), s'affiche `41 days, 16:00:00`. La correction est le remplacement
> du mot-clef par `microseconds=`. Le doctest du module encode l'erreur au lieu de la
> détecter : `text.py:857-859` affirme que la charge utile `00 51 25 02 00 00 00 00`,
> soit 36 000 000 ticks — 3,6 secondes — se rend `1:00:00`. Le défaut est **latent**
> dans ce projet : aucun chemin de code n'émet ni ne consomme de `TimeSpan` ADWS, et
> l'encodeur `_parse_data` ne produit jamais ce record.

### UniqueId, Uuid et l'ordre des octets

Les deux records portent 16 octets, mais dans l'ordre **`bytes_le`** de .NET, pas dans
l'ordre canonique de la RFC 4122 : les trois premiers champs du GUID
(`time_low` sur 4 octets, `time_mid` sur 2, `time_hi_and_version` sur 2) sont
petit-boutistes, les deux derniers (`clock_seq` sur 2, `node` sur 6) sont gros-boutistes.
L'implémentation délègue à Python : écriture `self.uuid.bytes_le` (`text.py:692`),
lecture `cls(bytes_le=u)` (`text.py:713`).

Exemple vérifié, tiré du test unitaire `text.py:688` :

```text
GUID textuel : 33221100-5544-7766-8899-aabbccddeeff

octets emis  : 00 11 22 33 | 44 55 | 66 77 | 88 99 | aa bb cc dd ee ff
               |__________|  |____|  |____|  |____|  |________________|
               time_low LE   mid LE  hi LE   clock_seq et node, tels quels
```

La différence entre les deux records est purement lexicale, portée par `__str__` :
`UniqueIdTextRecord` rend la forme URN `urn:uuid:33221100-...` (`text.py:701`),
`UuidTextRecord` rend la forme nue `33221100-...` (`text.py:724`). Les octets sont
identiques. C'est exactement la distinction dont ADWS a besoin : `<a:MessageID>` et
`<a:RelatesTo>` sont des URN, tandis que `<ad:objectReferenceProperty>` porte un GUID
nu — vérifié dans les handlers, par exemple `classes/handlers/create.py:85`.

### QNameDictionaryText

Format compact pour un nom qualifié dont le préfixe est une lettre et le nom local est
dans le dictionnaire : un octet donnant le rang de la lettre
(`ord(prefix) - ord('a')`, donc `0` pour `a`), puis **trois octets gros-boutistes**
pour l'index — et non un `MultiByteInt31` (`src/wcf/records/text.py:382-385` à
l'écriture, `text.py:404-405` à la lecture). Vérifié : `QNameDictionaryTextRecord('b', 2)`
produit `BC 01 00 00 02` et se relit `b:Envelope`. Corollaire : l'index d'un QName est
plafonné à 2^24 - 1 et coûte toujours 3 octets, même pour `Envelope` dont l'index vaut 2.

C'est le seul endroit du format où un index de dictionnaire n'est pas encodé en
`MultiByteInt31` — un piège classique lors de l'écriture d'un décodeur.

### Chars contre UnicodeChars

Les deux familles codent une chaîne ; `Chars*` en UTF-8 (`text.py:604`),
`UnicodeChars*` en UTF-16LE (`text.py:284`). `[MS-NBFX]` définit les deux et laisse
le choix à l'émetteur ; un lecteur conforme doit accepter les deux. Le choix ne
change que le volume.

| Critère | `Chars8/16/32` | `UnicodeChars8/16/32` |
|---|---|---|
| Octets | 0x98 / 0x9A / 0x9C | 0xB6 / 0xB8 / 0xBA |
| Encodage | UTF-8 | UTF-16LE |
| Longueur préfixée | 1 / 2 / 4 octets | 1 / 2 / 4 octets |
| Coût d'un caractère latin | 1 octet | 2 octets |
| Émis par cet encodeur | jamais | toujours |
| Échappement XML au rendu | oui (`escape`) | non |

> **Choix de cette implémentation.** `XMLParser._parse_data` (`src/wcf/xml2records.py:175`)
> utilise systématiquement `UnicodeChars8/16/32` comme repli textuel. Aucun chemin de
> l'encodeur ne produit de `Chars8/16/32TextRecord` — vérifié par recherche exhaustive
> des instanciations dans `src/wcf/xml2records.py`. Toute valeur d'annuaire sortante
> est donc transmise en UTF-16 : c'est correct, mais représente le double du volume
> nécessaire pour du texte latin. `[MS-NBFX]` n'impose ni ne recommande l'une des deux
> familles ; la répartition réelle `Chars*` / `UnicodeChars*` dans le trafic entrant
> Windows **n'a pas été mesurée sur une capture de ce dépôt** et ne doit pas être
> affirmée. Piste de phase 5, sans risque d'interopérabilité.

> **Défaut vérifié dans le sens du décodage.** L'échappement XML n'est appliqué que par
> `Chars8TextRecord.__str__` (`text.py:597`, via la fonction `escape` de `text.py:54`),
> dont héritent `Chars16` et `Chars32`. Les `UnicodeChars*` rendent leur valeur brute
> (`text.py:295`). Contrôle exécuté sur la chaîne `a<b&c` : `Chars8TextRecord` rend
> `a&lt ;b&amp ;c`, `UnicodeChars8TextRecord` rend `a<b&c` — ce dernier casse le XML
> texte intermédiaire et fait échouer `ET.fromstring` dans
> `classes/parsing/context.py:40`. Le défaut reste sans effet tant que le client
> n'émet pas de `UnicodeChars*` porteur de `<`, `>` ou `&` ; il n'existe **aucune
> preuve dans ce dépôt** que ce cas ne se produise jamais, seulement l'absence
> d'incident journalisé.
>
> Le périmètre de `escape` lui-même a déjà été corrigé une fois, cf.
> `documentation/06-depannage.md` section 9 : la table
> `_XML_ENTITY_BY_CP` (`text.py:47`) ne mappe plus que `<`, `>`, `&` et `"`, laissant
> les caractères accentués littéraux.

> **Défaut latent, décodage UTF-16.** `UnicodeChars8TextRecord.parse` (`text.py:307`)
> appelle `data.decode('utf-16')` et non `utf-16le`. Une charge utile commençant par
> `FF FE` est alors interprétée comme un BOM et consommée. Contrôle exécuté : la chaîne
> `U+FEFF` suivie de `abc` s'encode `B6 08 FF FE 61 00 62 00 63 00` et se relit `abc` —
> le caractère de tête est perdu. Cas de figure marginal pour de l'annuaire AD.

### Heuristique de typage à l'encodage et effet base64

`XMLParser._parse_data` (`src/wcf/xml2records.py:117`) déduit le record de texte de la
**forme** de la chaîne, jamais d'un type déclaré. L'ordre des tests est celui de la
chaîne `if`/`elif` des lignes 127 à 172 ; le repli textuel des lignes 175 à 181 est
atteint lorsqu'aucune branche n'a rendu de valeur.

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

Les expressions rationnelles sont définies en `xml2records.py:55-61`. Deux d'entre
elles méritent d'être lues attentivement : `int_reg` vaut `^-?[1-9]\d*$`, donc exclut
tout entier à zéro de tête ; `base64_reg` vaut `^[a-zA-Z0-9/+]*={0,2}$`, donc accepte
toute chaîne alphanumérique.

Le test base64 (`xml2records.py:122`) est appliqué **avant** la chaîne de décision, à
titre de pré-calcul, et sa branche passe **avant** la recherche dans le dictionnaire.
Il est très permissif : toute chaîne composée uniquement de `[A-Za-z0-9+/]`, avec un
éventuel `=` ou `==` final, et que `base64.b64decode` accepte, devient un
`Bytes8/16/32TextRecord`. Aller-retour complet mesuré, valeur par valeur, à travers
`XMLParser.parse` puis `Record.parse` et `print_records` :

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

Un `objectClass` valant `user` part donc sur le fil en `base64Binary` au lieu de
`string`. **Cela reste sans effet observable** : `Bytes8TextRecord.__str__`
(`text.py:749`) ré-encode en base64, et pour toute longueur multiple de 4 sans
remplissage la transformation est exactement inverse — le lecteur retrouve `user`. Le
type consommé par les cmdlets provient de l'attribut `xsi:type` porté par
`<ad:value>` ; cette dernière affirmation découle du contrat de sérialisation
`[MS-ADDM]` et **n'a pas été mesurée** sur un client de ce dépôt.

Le cas non réversible existe cependant : une chaîne base64 **non canonique** avec
remplissage perd de l'information. Contrôle exécuté : `ab==` se décode en un octet
`0x69` et se ré-encode `aQ==`. Une valeur d'annuaire de la forme `xy==` serait donc
altérée. La parade est de restreindre le test base64 aux longueurs multiples de 4 sans
remplissage, ou de le déplacer après la recherche dans le dictionnaire.

### Deux défauts vérifiés de la chaîne de typage

> **Corruption des entiers à zéro de tête.** `int_reg` refusant `^-?[1-9]`, une valeur
> comme `007` échappe à la branche entière, mais satisfait `float_reg` et devient un
> `DoubleTextRecord`. Contrôle exécuté sur `<a:V>007</a:V>` : le flux émis est
> `5E 01 56 93 00 00 00 00 00 00 1C 40` — un double IEEE 754 valant 7,0 — et la
> relecture rend `7`. De même `0123456789` devient `123456789`. Tout attribut
> d'annuaire dont la valeur textuelle est un nombre décimal à zéro de tête
> (`employeeID`, `postalCode`, certains identifiants métier) est donc **altéré en
> sortie**. C'est, de tous les écarts recensés dans ce chapitre, le seul qui produise
> une valeur fausse sur un chemin nominal.
>
> **Débordement `Int64` non gardé.** La borne inférieure de la branche 64 bits est
> écrite `-2**64 <= val` (`xml2records.py:151`) au lieu de `-2**63`. Contrôle
> exécuté : `-9223372036854775809` est routé vers `Int64TextRecord`, dont `to_bytes`
> lève alors `struct.error: 'q' format requires -9223372036854775808 <= number <=
> 9223372036854775807`. L'exception remonte au dispatcher, qui la traduit en fault
> SOAP. La fenêtre concernée, `[-2^64, -2^63)`, ne correspond à aucune valeur
> d'annuaire réaliste ; le défaut est **latent**.

# Le dictionnaire statique (MS-NBFS)

## Taille et forme de la table

Le dictionnaire statique du projet est un simple `dict` Python littéral, de
`src/wcf/dictionary.py:29` à `src/wcf/dictionary.py:517`. Comptage effectué sur le
fichier : **487 entrées**, clés `0x00` à `0x3CC` (972 en décimal), **pas de 2, sans
aucun trou** — vérifié par énumération exhaustive des clés.

Les clés stockées sont directement les **valeurs de fil**, c'est-à-dire les identifiants
tels qu'ils apparaissent dans un `MultiByteInt31` de record. La table `[MS-NBFS]`
proprement dite numérote ses chaînes de 0 à 486 ; la valeur de fil vaut `2 x index`.
Le fichier du projet a donc déjà appliqué le doublement, ce qui évite toute conversion
à l'exécution.

## La règle pair / impair

C'est le mécanisme d'extensibilité de `[MS-NBFS]` et `[MS-NBFSE]` :

| Parité de l'identifiant | Origine de la chaîne |
|---|---|
| **pair** | table statique `[MS-NBFS]`, identique pour tous les échanges |
| **impair** | dictionnaire de session `[MS-NBFSE]`, défini en tête de message |

La règle est confirmée par le code du projet : le dictionnaire statique n'utilise que
des clés paires (vérifié : zéro clé impaire sur 487), et l'allocateur de session
`build_dictionary` (`src/nettcp/protocol2xml.py:30`) part de `idx = 1`
(`protocol2xml.py:28`) et progresse par `idx += 2` (`protocol2xml.py:41`).

Un décodeur qui rencontre un identifiant impair non déclaré lèvera un `KeyError` sur
`dictionary[self.index]` (par exemple `elements.py:156`), remonté au dispatcher et
traduit en fault SOAP.

## Index exacts utiles au diagnostic

Les valeurs suivantes sont relevées telles quelles dans `src/wcf/dictionary.py` ; ce
sont celles que l'on croise dans tout dump ADWS.

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

La table couvre SOAP 1.1 et 1.2, WS-Addressing (deux révisions), WS-ReliableMessaging,
WS-Trust, WS-SecureConversation, WS-Coordination, WS-AtomicTransaction, SAML 1.x,
XML Signature, XML Encryption et les noms de types XSD. Elle ne contient **aucun**
vocabulaire ADWS.

## Le dictionnaire inversé

`src/wcf/dictionary.py:519` construit `inverted_dict` par simple compréhension
`{v: k for k, v in dictionary.items}`. Vérification effectuée : les deux tables
comptent 487 entrées, donc **aucune valeur n'est dupliquée** et l'inversion est
bijective. C'est cette table qui pilote toutes les décisions d'indexation de
`src/wcf/xml2records.py`.

Neuf entrées sont des chaînes d'un seul caractère (`s`, `a`, `c`, `e`, `k`, `o`, `r`,
`t`, `u`), destinées à indexer des **préfixes** littéraux. Effet de bord à connaître :
un nœud texte valant exactement `a` sera encodé en `DictionaryTextRecord(0xB6)` et non
en `UnicodeChars8` — comportement correct, le décodage restitue `a`.

## Ce qui manque : les espaces de noms ADWS

`SoapEnvelope.NS_DECL` (`classes/soap/soap_envelope.py:23`) déclare **onze** espaces
de noms. Quatre d'entre eux ont leur URI dans la table statique ; les sept autres, tous
propres à ADWS ou aux WS-*, n'y figurent pas. Le coût de chaque déclaration a été
mesuré par différence entre `dump_records` d'un `<s:E xmlns:p="URI"></s:E>` et
`dump_records` d'un `<s:E></s:E>` :

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

La formule est directe pour les URI non indexées : `XmlnsAttributeRecord` coûte
1 octet de type, plus le `Utf8String` du préfixe, plus le `Utf8String` de l'URI —
soit `1 + (1 + len(prefixe)) + (1 + len(uri))`. Pour les URI indexées,
`DictionaryXmlnsAttributeRecord` coûte `1 + (1 + len(prefixe)) + len(MultiByteInt31)`.

Totaux mesurés : les onze déclarations pèsent **473 octets** encodés, dont **451
octets** pour les seules sept non indexées. L'élément vide de référence
`<s:Envelope></s:Envelope>` ne coûte, lui, que **3 octets** (`56 02 01`). Ce sont donc
451 octets fixes payés sur chaque réponse pour du vocabulaire strictement constant.
C'est précisément ce que le dictionnaire de session `[MS-NBFSE]` est fait pour
supprimer.

# Le dictionnaire de session (MS-NBFSE) : statut dans ce projet

## Le mécanisme

Quand l'encodage négocié est `BINARY_DICT` (valeur 8), chaque message applicatif est
précédé, **à l'intérieur** de la charge utile du `SizedEnvelopedMessageRecord` NMF,
d'un préambule de dictionnaire de session :

```text
+--------------------+---------------------------+-------------------------+
| MultiByteInt31     | N octets : suite de       | records MS-NBFX         |
| taille de la table | Utf8String concatenees    | (le document lui-meme)  |
+--------------------+---------------------------+-------------------------+
```

Chaque `Utf8String` définit une chaîne de session ; les identifiants sont attribués
séquentiellement en **impairs** : 1, 3, 5,... Une fois définie, une chaîne peut être
référencée par n'importe quel record `*Dictionary*` du message et des messages suivants
de la même session.

## Ce que fait réellement l'implémentation

Contrairement à ce qu'affirme `documentation/03-protocole.md` (« Le dictionnaire
dynamique négocié par session (MS-NBFSE) n'est pas implémenté »), le mécanisme **est
implémenté à la réception**, et volontairement neutralisé à l'émission.

**À la réception** — `SizedEnvelopedMessageRecord.payload_to_xml`
(`src/nettcp/nmf.py:363`) appelle `build_dictionary(fp, ('client', 'c>s'))` avant
`Record.parse`. La fonction (`src/nettcp/protocol2xml.py:30`) lit la taille, découpe la
table en `Utf8String`, attribue les identifiants impairs, puis **fusionne** le résultat
dans le dictionnaire global du module `src/wcf/dictionary.py` :

```python
dictionary.clear()
dictionary.update(old_dictionary)
dictionary.update(dictionary_cache[key])
```

**À l'émission** — `ADWSDispatcher._encode_response`
(`classes/handlers/dispatcher.py:46`) préfixe systématiquement la sortie de
`dump_records` par un octet `\x00` :

```python
records: Any = XMLParser.parse(response_xml)
encoded: Any = dump_records(records)
result: bytes = b"\x00" + encoded
return result
```

Cet octet **n'est pas un octet de cadrage** : c'est le `MultiByteInt31` valant zéro,
c'est-à-dire une **table de session vide**. Le serveur déclare ainsi ne définir aucune
chaîne de session, ce qui est licite et rend toutes ses réponses interprétables avec la
seule table statique.

> La documentation de la compétence `decode-wcf`
> (`.claude/skills/decode-wcf/SKILL.md`) décrit ce `\x00` comme un « framing byte ».
> La formulation exacte est : préambule `[MS-NBFSE]` de longueur nulle. La conséquence
> pratique est la même — pour décoder une trame sortante capturée, retirer le premier
> octet.

## Limites et risques identifiés

- **État global mutable.** `build_dictionary` modifie en place le `dict` importé depuis
 `src/wcf/dictionary.py`, plus deux globales `idx` et `dictionary_cache`
 (`protocol2xml.py:26-28`). C'est une violation directe de la règle « pas d'état global
 mutable » de `CLAUDE.md` §6.1. Le modèle `ForkingTCPServer` limite les dégâts —
 chaque connexion est un processus distinct — mais l'état grossit sans borne au fil des
 messages d'une même connexion.
- **Numérotation cumulative.** `idx` ne repart jamais de 1. Si un client redéfinit sa
 table de session au cours d'une même connexion, les chaînes reçues seront enregistrées
 sous de nouveaux identifiants impairs, tandis que le client continuera de référencer
 les anciens : désynchronisation silencieuse. Ce scénario n'a pas été observé sur le
 trafic du projet ; il n'est **pas vérifié en conditions réelles**.
- **Écriture sur la sortie standard.** `build_dictionary` fait un `print` de la taille
 de table et de chaque entrée (`protocol2xml.py:33` et `protocol2xml.py:47`) : c'est du
 code de mise au point laissé sur le chemin nominal de chaque requête.
- **Fragilité avérée.** Le journal `adws.log` conserve la trace d'un échec direct de
 cette fonction :

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

Les numéros de ligne concordent avec l'arbre actuel (`nmf.py:369` est bien l'appel à
`build_dictionary`, `protocol2xml.py:38` est bien `Utf8String.parse(table)`,
`datatypes.py:52` est bien le `decode('utf-8')`) ; seule l'arborescence a changé
depuis, le dispatcher étant passé de `src/adws/` à `classes/handlers/`.

L'octet `0x82` en position 11 est le type d'un `OneTextRecord` : la fonction lisait
déjà le **document**, pas la table. Autrement dit la taille lue en tête n'était pas une
taille de table de session. Deux hypothèses subsistent — le message reçu n'était pas
encodé en `BINARY_DICT`, ou la table était vide et le premier octet du document a été
pris pour une longueur — et **aucune capture n'est disponible pour trancher**.
`build_dictionary` n'effectue aucune validation : ni borne supérieure sur la taille
annoncée, ni vérification que les octets lus sont bien de l'UTF-8 valide, ni contrôle
que `table.tell` s'arrête exactement sur `size`. Un contrôle de cohérence à cet
endroit est le durcissement le plus rentable de toute la couche.

# Chaîne d'encodage et de décodage dans l'implémentation

## Vue d'ensemble

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

## Le rôle de `html_parser.py`

Le nom du fichier est trompeur : `src/wcf/html_parser.py` ne parse pas du HTML. C'est
une **réécriture** de l'ancien `HTMLParser` de la bibliothèque standard, dont le code
vendoré dépendait, remplacée par un pilote autour de `xml.parsers.expat`
(`html_parser.py:27`). Sa docstring l'annonce : *« Case-preserving XML parser replacing
HTMLParser for WCF »* (`html_parser.py:7`). Deux motifs à ce remplacement :

- **La casse.** `HTMLParser` normalise les noms de balises et d'attributs en minuscules.
 Or les noms d'attributs AD sont sensibles à la casse (`objectGUID`, `sAMAccountName`,
 `distinguishedName`).
- **Les préfixes.** Le commentaire de `html_parser.py:24-26` est explicite : le parseur
 est créé **sans séparateur d'espace de noms**, afin qu'Expat restitue les noms
 qualifiés complets (`s:Envelope`) plutôt que la forme `{uri}local`. C'est ce qui
 permet à `_parse_tag` de récupérer le préfixe littéral, indispensable pour choisir un
 record `PrefixDictionaryElement<L>`. Corollaire : les déclarations `xmlns` restent des
 attributs ordinaires dans la liste passée à `handle_starttag`, donc encodables.

La classe n'expose que trois handlers Expat : `StartElementHandler`,
`EndElementHandler`, `CharacterDataHandler` (`html_parser.py:28-30`). Tout le reste de
l'interface historique (`handle_charref`, `handle_entityref`, `handle_decl`,
`handle_comment`, `parse_marked_section`) subsiste dans `XMLParser` mais constitue du
**code mort** : Expat résout les références de caractères et d'entités lui-même et les
livre via `CharacterDataHandler`. Cela explique aussi que `self.interesting` conserve
toujours la valeur `INTERESTING_NORMAL` (`src/wcf/constants.py:6`) et que le drapeau
`is_cdata` testé en `xml2records.py:257` soit toujours faux.

Une dernière subtilité : `feed` appelle `self._parser.Parse(data, False)`
(`html_parser.py:38`), donc en mode non final, et `close` n'est jamais invoqué par
`XMLParser.parse`. Cela fonctionne parce que le document fourni est toujours complet et
bien formé ; un document tronqué ne déclencherait pas d'erreur.

## Pourquoi passer par du XML texte intermédiaire

Le serveur pourrait, en théorie, construire directement un arbre de `Record` et
l'émettre. Il ne le fait pas, et c'est un choix d'architecture assumé :

- **Une seule représentation canonique pour la logique métier.** Les handlers
 produisent des chaînes XML par interpolation (`SoapEnvelope.wrap`,
 `classes/soap/soap_envelope.py:33`) et les parseurs de `classes/parsing/` consomment
 de l'`ElementTree`. Aucun code métier n'a connaissance des records.
- **Auditabilité.** Un XML texte se lit dans un journal, se compare, se rejoue ; un
 arbre de records ne se lit pas.
- **Isolation du code vendoré.** `src/wcf/` et `src/nettcp/` sont identifiés comme du
 code tiers vendoré, exclu des normes §6.1 (`documentation/01-architecture.md:79-80`).
 La frontière est justement la chaîne XML.

Le prix payé est de **deux passes de sérialisation supplémentaires par message** : une
reconstruction textuelle au décodage (`print_records`), une réanalyse Expat à
l'encodage. Le coût relatif de ces deux passes sur un gros `PullResponse` **n'a pas été
profilé** dans ce dépôt ; il constitue néanmoins la cible évidente d'une optimisation
de phase 5.

## Deux effets de bord de `print_records`

`print_records` (`src/wcf/records/__init__.py:42`) **indente** sa sortie : chaque
élément est précédé d'un saut de ligne et de `skip` espaces (`__init__.py:62`). Le XML
reconstruit n'est donc pas l'original mais une version formatée.

L'indentation n'est écrite **que devant les éléments**. Un élément dont le contenu est
purement textuel voit sa valeur écrite en ligne, intacte — vérifié sur l'aller-retour de
l'exemple complet plus bas, où `<a:Action>http://...</a:Action>` reste sur une ligne.
En revanche, un élément à contenu mixte (texte puis élément) verrait son texte suivi
d'un saut de ligne parasite. ADWS ne produit pas de contenu mixte ; le risque est nul en
pratique, mais la reconstruction n'est pas fidèle à l'infoset au sens strict.

# Exemple complet : encodage pas à pas d'une enveloppe SOAP

## Le document de départ

Une enveloppe de réponse réduite aux deux seuls espaces de noms indexés, de structure
identique à celle que produit `SoapEnvelope.wrap` mais amputée des neuf autres
déclarations et de la déclaration XML, afin que le dump reste lisible :

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

## Le flux binaire annoté

Sortie réelle de `dump_records(XMLParser.parse(xml))`, annotée segment par segment.

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

- **Aucune balise fermante n'est écrite en clair.** Deux des quatre fermetures sont
 gratuites, portées par le bit *WithEndElement* des records `0xB7` et `0xAD`.
- **`<s:Body></s:Body>` coûte 3 octets** : `56 0E 01`. La version textuelle en coûte 17.
- **La valeur de `<a:Action>` représente 118 des 159 octets**, soit 74 % du message.
 C'est l'illustration parfaite de la raison d'être de `[MS-NBFSE]` : cette URI est
 identique dans toutes les réponses `GetResponse`, une seule définition de session la
 ramènerait à deux octets pour tous les messages suivants.

## L'opération inverse

Le décodage complet est réalisé par le couple `Record.parse` puis `print_records`
(commande exacte à la section suivante). Résultat obtenu sur les 159 octets ci-dessus :

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

Les retours à la ligne à l'intérieur de l'URI et de la balise `<s:Envelope>` sont un
artefact de mise en page du présent document ; l'indentation, elle, est bien produite
par `print_records`. L'aller-retour est fidèle au niveau du contenu : mêmes éléments,
mêmes attributs, mêmes valeurs textuelles.

## L'outil de mise au point du dépôt

Le dépôt expose une compétence `decode-wcf` (`.claude/skills/decode-wcf/SKILL.md:20`
et `:27`) et `documentation/03-protocole.md:269` propose une ligne de commande.
**Les deux sont inexactes** : elles appellent `dump_records(data)` sur des octets,
alors que `dump_records` (`src/wcf/records/__init__.py:90`) attend un **arbre de
records** et produit des octets. C'est la fonction du sens inverse.

Le mode de défaillance est pernicieux. `dump_records` itère sur son argument ; sur un
`bytes`, l'itération produit des `int`, et `int.to_bytes` accepte depuis Python 3.11
des paramètres par défaut (`length=1`, `byteorder='big'`). Contrôle exécuté sous
CPython 3.12 : `dump_records(b'\x56\x02\x01')` rend `b'V\x02\x01'`, c'est-à-dire
**l'entrée inchangée**, sans lever la moindre exception. La commande documentée
n'échoue donc pas : elle réaffiche le payload brut, ce qu'un lecteur pressé peut
prendre pour un décodage. Sous Python 3.10 et antérieurs, `int.to_bytes` sans
argument lève un `TypeError`, et l'erreur est au moins visible.

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

`repr_records` (`src/wcf/records/__init__.py:81`) affiche un record par ligne, sans
reconstruction XML — utile pour vérifier qu'une valeur n'a pas été typée
`Bytes8TextRecord` par l'heuristique base64.

Pour le sens inverse, c'est-à-dire vérifier ce qu'un XML de handler donnera sur le fil :

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

> Rappel opérationnel : après la négociation GSSAPI (phase 2 du protocole NMF), les
> octets observés par `tcpdump` sont **scellés**. Une capture réseau brute ne se décode
> pas. Le clair s'obtient par le journal de records de `tools/work/proxy.py`
> (`RECORD_LOG`), conformément à `documentation/03-protocole.md`. Un payload sortant du
> dispatcher porte de plus le préfixe `[MS-NBFSE]` `\x00` : le retirer avant décodage.

## Synthèse des écarts de cette implémentation

Les écarts sont classés par gravité décroissante. « Actif » signifie qu'un chemin
nominal du serveur l'emprunte aujourd'hui ; « latent » qu'il faudrait un flux entrant
que ce dépôt n'a jamais observé pour le déclencher.

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

Aucun des écarts marqués « latent » n'empêche le fonctionnement nominal validé au
chapitre Tests (`documentation/05-tests.md:129`, **26/28** sur
`Test-ADWS-Sovereign.ps1`) : les chemins concernés ne sont pas empruntés par le module
`ActiveDirectory` de PowerShell dans les scénarios couverts. Les écarts marqués
« actif » sont, eux, présents sur chaque requête ; seul le premier produit une valeur
fausse, et il n'est pas couvert par la suite de tests actuelle. L'ensemble constitue la
dette technique connue de la couche d'encodage et la liste de travail de la phase 5.

Trois points ont été explicitement laissés **non tranchés**, faute de capture ou de
mesure disponible dans ce dépôt, et ne doivent pas être présentés comme acquis : la
valeur réelle de l'octet `KnownEncodingRecord` envoyé par le client, la répartition
`Chars*` / `UnicodeChars*` du trafic entrant, et la cause exacte du `UnicodeDecodeError`
historique de `build_dictionary`. Aucune section précise des spécifications Microsoft
n'est citée dans ce chapitre : les documents `[MS-NBFX]`, `[MS-NBFS]`, `[MS-NBFSE]` et
`[MS-NMF]` sont référencés par leur nom, et toutes les valeurs d'octet données ici sont
issues de la lecture et de l'exécution du code de ce dépôt.
