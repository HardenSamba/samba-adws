# Enveloppe SOAP 1.2 et espaces de noms

## Position de la couche message dans l'empilement

Une fois le préambule [MS-NMF] consommé, le contexte GSSAPI établi et le
payload descellé puis décodé depuis le XML binaire WCF ([MS-NBFX] /
[MS-NBFS]), ce qui reste entre les mains du serveur est **du SOAP 1.2
textuel ordinaire**. C'est un choix d'architecture explicite du projet :
`src/nettcp/nmf.py:363` (`Record.payload_to_xml`) reconstruit une chaîne XML
lisible, et tout le code applicatif — parsing, routage, handlers,
sérialisation, fautes — ne manipule plus que des `str`. Le chemin retour est
symétrique : chaque handler retourne une **chaîne XML SOAP complète**, que
`ADWSDispatcher._encode_response` (`classes/handlers/dispatcher.py:45-50`)
re-compile en records WCF.

Le coût de cet aller-retour texte est assumé ; le bénéfice est qu'un message
d'erreur, un test ou une comparaison avec une capture Microsoft se font tous
sur le même artefact : le XML.

Trois niveaux doivent être distingués dans tout ce chapitre :

- **1. La spécification** — SOAP 1.2 (W3C), WS-Addressing 1.0, WS-Transfer,
 WS-Enumeration, WS-Eventing, et les profils Microsoft [MS-ADDM],
 [MS-WSTIM], [MS-WSDS], [MS-WSPELD].
- **2. Le client Windows réel** — le module PowerShell `ActiveDirectory` et
 ADAC, dont le comportement observable est parfois plus strict (ou plus
 laxiste) que la spec.
- **3. Cette implémentation Python** — qui vise la compatibilité fil avec le
 niveau 2, et dont les écarts avec le niveau 1 sont signalés au fil du texte.

## Forme canonique de l'enveloppe émise

La fabrique d'enveloppes centrale est `SoapEnvelope`
(`classes/soap/soap_envelope.py:21`). Elle produit une enveloppe SOAP 1.2
minifiée, préfixée d'un prologue XML, avec **un bloc `<s:Header>` réduit à
deux en-têtes** — `a:Action` et `a:RelatesTo` — et un `<s:Body>` fourni par
le handler.

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

## Table exhaustive des espaces de noms

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

Les constantes homologues de les constantes du service ADWS Microsoft portent les **mêmes URI et
les mêmes préfixes** : `AdNs` (`:81`), `AddataNs` (`:83`),
`AdCustomActionNs` (`:85`), `AdFault` (`:87`), `XsiNs` (`:89`), `XsdNs`
(`:91`), `IdentityManagementDirectoryAccess` (`:93`), `WSTransfer` (`:95`),
`WSEnumeration` (`:97`) et `LdapQuery` (`:105`), avec les préfixes `ad`,
`addata`, `xsi`, `xsd`, `da`, `wst`, `wsen`, `adlq` déclarés en
les constantes du service ADWS Microsoft. L'implémentation Python est donc alignée sur la
référence pour cette table. La même source déclare les dialectes que les
exemples de ce chapitre reprennent : `XPathLvl1Selection` (`:99`),
`QNameSelection` (`:101`), `XPath10SubsetQuery` (`:103`).

Deux constantes de la table Python n'apparaissent **pas** dans `NS_DECL` :
`WSEV` et `SERA`. Elles sont déclarées localement par les corps qui en ont
besoin — `subscribe.py:37` pose `xmlns:wse="{WSEV}"`, `ca_elements.py:22`
et `:26` posent `xmlns:sera`. Un corps qui oublierait la déclaration
produirait un préfixe non lié, donc un XML rejeté par le lecteur .NET.

## Deux familles d'enveloppes dans le code

Il faut savoir qu'**il existe deux générateurs d'enveloppe** dans
l'implémentation, ce qui est une dette technique assumée et une source de
divergence à surveiller. Le dossier `classes/handlers/` contient
trente et un fichiers de handler ; trois d'entre eux ne sont que des façades
de routage et ne fabriquent aucune enveloppe (`crud.py`, `transfer.py`,
`search.py`). Restent **vingt-huit** producteurs d'enveloppe, répartis
ainsi :

- **Famille A — `SoapEnvelope.wrap`, appelée via `self.envelope.wrap`.**
 Vingt-quatre handlers, dont `create.py:90`, `modify.py:75`,
 `delete.py:32`, `get_status.py:30`, `renew.py:28`, `schema.py:76`,
 `groups.py:38`, `set_password.py:24`, `get_version.py:20`,
 `subscribe.py:27` et l'ensemble des handlers d'actions personnalisées.
 L'alias `self.envelope` est posé une fois pour toutes dans
 `BaseHandler.__init__` (`classes/handlers/base.py:26`). `wrap` déclare les
 onze préfixes de `NS_DECL` et échappe `action` et `relates_to` avec
 `html.escape` (`soap_envelope.py:38-39`).
- **Famille B — enveloppes écrites à la main.** Quatre handlers construisent
 leur enveloppe littéralement : `get.py:167-188` et `get.py:279-300`,
 `enumerate.py:109-127`, `pull.py:93-114`, `release.py:43-55`. Ils
 ne déclarent que le sous-ensemble de préfixes dont ils ont besoin.

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

`ENV_NS_MAP` (`src/soap/namespaces.py:18-30`) est une table
préfixe → URI définie mais **jamais consommée** dans l'arbre courant : ce
n'est pas une source de vérité pour la sérialisation, seul `NS_DECL` l'est.

# En-têtes WS-Addressing

## Ce que la spécification impose

WS-Addressing 1.0 définit une famille d'en-têtes de type *Message
Addressing Properties* placés dans `<s:Header>` :

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

## Ce que le client Windows envoie réellement

Le module `ActiveDirectory` ouvre un canal `net.tcp` **orienté session et
bidirectionnel au niveau transport**. Les quatre contrats de service de la
référence portent tous `SessionMode = SessionMode.Required` et
`ProtectionLevel = ProtectionLevel.EncryptAndSign` : le contrat Resource du service Microsoft,
le contrat Enumeration du service Microsoft, le contrat AccountManagement du service Microsoft et
le contrat TopologyManagement du service Microsoft.

Deux précisions s'imposent. `EncryptAndSign` est la contrepartie
contractuelle du scellement GSSAPI : le service **refuse** un message non
chiffré, ce qui interdit tout mode « en clair pour déboguer » sans modifier
le binding. Et aucun de ces contrats ne déclare de `CallbackContract` : ce
sont des contrats **requête-réponse** (`Message Get(Message request)`,
le contrat Resource du service Microsoft), pas des contrats duplex au sens WCF. Le canal est
bidirectionnel parce que le transport l'est, pas parce que le contrat le
demande.

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
`pull.py:103`, `release.py:48`). C'est un écart au niveau 1 sans
conséquence observée au niveau 2.

Chez Microsoft, en revanche, `mustUnderstand` est bel et bien appliqué —
par la pile WCF, pas par le code ADWS. La preuve en est que la référence
installe deux `IDispatchMessageInspector` dont l'unique travail est
d'ajouter les en-têtes propriétaires à `Headers.UnderstoodHeaders`, faute de
quoi WCF lèverait une faute `MustUnderstand` sur ses propres messages :

| Inspecteur | En-tête marqué compris | Espace de noms | Ancrage |
|---|---|---|---|
| `ObjectIdAndInstanceInformationInspector` | `objectReferenceProperty` | `AD` | Service ADWS Microsoft |
| `ObjectIdAndInstanceInformationInspector` | `instance` | `AD` | Service ADWS Microsoft |
| `IdentityManagementMessageInspector` | `IdentityManagementOperation` | `DA` | Service ADWS Microsoft |

Deux détails de ces inspecteurs éclairent le protocole :
l’inspecteur d’en-têtes du service Microsoft exclut nommément
`…/transfer/Create` et `…/enumeration/Enumerate` du marquage
d'`objectReferenceProperty`, et
l’inspecteur de messages IMDA du service Microsoft sort immédiatement sur
`…/transfer/Delete` — un `Delete` n'est jamais une opération IMDA. Ce
serveur n'a pas à reproduire ces règles puisqu'il ne vérifie rien, mais
elles indiquent quels messages portent réellement quels en-têtes.

## Ce que cette implémentation lit et écrit

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
`context.py:44-52` : sept entrées — `soap`, `soap11`, `a`, `ad`, `da`,
`wsen`, `adlq` — et **ni `ca`, ni `addata`, ni `wst`**. Les corps d'actions
personnalisées sont donc parsés ailleurs, par `BodyParser`, qui porte sa
propre table (`body_parser.py:7-14`). `soap11` y figure sans jamais servir :
ADWS est exclusivement SOAP 1.2.

Deux points méritent attention.

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
`<a:RelatesTo></a:RelatesTo>` vide — voir ci-dessous.

## Le format `urn:uuid:` et la corrélation

Le `MessageID` produit par WCF est un URN UUID, forme
`urn:uuid:` + un GUID canonique 8-4-4-4-12 en minuscules. Le serveur ne
valide **pas** ce format et ne le régénère pas : il le traite comme une
chaîne opaque à recopier. C'est exactement le contrat attendu — la spec
n'impose qu'une chose, l'**égalité octet pour octet** entre le `MessageID`
de la requête et le `RelatesTo` de la réponse. Le test
`test_relates_to` (`tools/test/test_handlers.py:54-59`) vérifie précisément
cette égalité avec une valeur volontairement non-UUID (`urn:uuid:rt-9`),
ce qui confirme que la recopie est bien littérale.

Règles de corrélation appliquées par le serveur : toute réponse et toute
faute portent `<a:RelatesTo>` égal au `MessageID` de la requête, y compris
quand l'erreur survient avant l'appel du handler ; le serveur n'émet jamais
de `MessageID` propre ; et hors WS-Enumeration, où le lien est porté par
`<wsen:EnumerationContext>` dans le corps, il n'existe aucune corrélation
multi-messages.

## Pourquoi l'absence de `RelatesTo` bloque PowerShell jusqu'au timeout

Le canal `net.tcp` porte plusieurs messages sur une même session : côté
client, c'est la pile WCF — pas le module `ActiveDirectory` — qui décide à
qui remettre un message entrant. Son algorithme est celui de
WS-Addressing :

- **1.** Le client émet la requête et enregistre son `MessageID` dans une
 table de corrélation, puis bloque sur l'attente d'une réponse.
- **2.** Un message arrive sur le canal. WCF lit son `<a:RelatesTo>`.
- **3.** Si `RelatesTo` correspond à une entrée de la table, la réponse est
 remise à l'appelant bloqué et le `Task` se termine.
- **4.** Si `RelatesTo` est **absent** ou ne correspond à rien, le message
 n'appartient à aucune requête en cours. Sur un canal requête-réponse sans
 `CallbackContract` — ce qui est le cas de tous les contrats ADWS — il
 n'existe aucune destination pour un message non sollicité : il est
 **abandonné**.
- **5.** L'appelant n'a donc jamais été réveillé. Il reste bloqué jusqu'à
 l'expiration du timeout de réception du binding, puis la cmdlet remonte
 une erreur de délai — et non l'erreur réelle, qui a été perdue.

> **Statut de cette description.** Les étapes 1 à 3 sont le comportement
> normatif de WS-Addressing. Les étapes 4 et 5 sont une **inférence**
> cohérente avec l'absence de `CallbackContract` dans les contrats de la
> référence et avec `documentation/06-depannage.md` § 6, mais elles se
> produisent dans la pile WCF du client, hors du périmètre observable de ce
> dépôt. Le fait observable — pas de `RelatesTo`, cmdlet bloquée jusqu'au
> timeout — est en revanche solidement établi.

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
`xml.etree.ElementTree.ParseError: undefined entity`, que le
`except Exception` de `context.py:168-169` **rehabille en `ValueError`**
(`raise ValueError(f"Failed to parse request XML: {str(e)}") from e`). Ce
`ValueError` n'étant **pas** une `ADWSException`, il tombe dans le second
`except` du dispatcher et produit une stack trace complète dans
`journalctl` — la signature exacte décrite par
`documentation/06-depannage.md` § 9. Le dispatcher initialise
`context = None` (`dispatcher.py:22`) avant le `try` et ne le renseigne
qu'après le parsing réussi (`dispatcher.py:25`) ; dans le cas dégradé,
`relates_to` vaut la chaîne vide.

> **Limite connue et non corrigée.** Un `<a:RelatesTo></a:RelatesTo>` vide
> est syntaxiquement présent mais sémantiquement inutile : il ne corrèle
> rien, donc blocage jusqu'au timeout, exactement comme s'il était absent.
> **Quand la requête est illisible au point que son `MessageID` n'est pas
> extractible, aucune faute exploitable ne peut être renvoyée.** La seule
> parade est de ne jamais échouer au parsing — d'où l'importance
> structurelle du correctif d'entités XML de `src/wcf/records/text.py`
> (`documentation/06-depannage.md` § 9). Une amélioration possible serait
> d'extraire le `MessageID` par expression régulière sur le XML brut avant
> de tenter `ET.fromstring`, en dernier recours.

## Valeur d'`a:Action` en réponse

En réponse, l'action est celle de l'opération suffixée de `Response`. Pour
`Get`, la requête porte `…/transfer/Get` et la réponse `…/transfer/GetResponse` ;
`Put` et `Delete` suivent la même règle.

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
**WS-Addressing 1.0**. Le service Microsoft, lui, ne l'emploie jamais :
elle déclare des actions de faute par famille, portées par l'attribut
fautes déclarées par les contrats. Les six valeurs suivantes sont
toutes vérifiées dans le code de référence :

| Action de faute de la référence | Ancrage |
|---|---|
| `http://schemas.xmlsoap.org/ws/2004/08/addressing/fault` | Service ADWS Microsoft |
| `http://schemas.dmtf.org/wbem/wsman/1/wsman/fault` | Service ADWS Microsoft |
| `http://schemas.microsoft.com/2006/11/…/DirectoryAccess/fault` | Service ADWS Microsoft |
| `http://schemas.xmlsoap.org/ws/2004/09/transfer/fault` | Service ADWS Microsoft |
| `http://schemas.xmlsoap.org/ws/2004/09/enumeration/fault` | Service ADWS Microsoft |
| `http://schemas.microsoft.com/2008/1/ActiveDirectory/Data/fault` | Service ADWS Microsoft |

Le projet n'utilise que la dernière — via `FAULT_NS` — et uniquement pour
les fautes d'actions personnalisées (`classes/faults/faults.py:40`). Sur ce
point précis il est **exactement conforme** : le générateur de fautes du service ADWS Microsoft et
`:491` passent la même URI comme `faultAction` pour toutes les
`CustomActionFault`. Pour tout le reste, **écart assumé :** la valeur
d'`a:Action` d'une faute compte peu pour le client tant que `RelatesTo` est
correct, mais l'aligner rendrait les captures plus lisibles et le mapping
vers les fautes déclarées plus direct.

# Le référencement d'objet : ResourceReference, InstanceId, ObjectReferenceProperty

## Ce que fait le vrai ADWS

Contrairement à ce que suggérait une version antérieure de
`documentation/03-protocole.md`, le service Microsoft n'utilise **pas** un
bloc `<wsa:ResourceReference><wsa:InstanceId>…`. Il utilise **deux en-têtes
SOAP plats**, tous deux dans l'espace de noms
`http://schemas.microsoft.com/2008/1/ActiveDirectory` :

| En-tête | Type | Rôle |
|---|---|---|
| `ad:objectReferenceProperty` | chaîne | Identifie l'objet cible |
| `ad:instance` | chaîne | Identifie l'instance d'annuaire visée |

C'est vérifiable en deux endroits du code de référence :
l’inspecteur d’en-têtes du service Microsoft et `:23` recherchent
exactement ces deux noms par
`request.Headers.FindHeader(nom, "http://schemas.microsoft.com/2008/1/ActiveDirectory")`
et les marquent comme *understood* ;
le service ADWS Microsoft et `:1611` les relisent par
`GetHeader<string>` pour construire l'identifiant d'objet
(`DirectoryObjectIdentifier`). Les constantes correspondantes sont
`objectReferenceProperty` et
`WebServiceStrings.Instance = "instance"`.

Comportements observables importants de la référence :

- **`ad:objectReferenceProperty` n'est exigé que pour `Get`, `Delete` et
 `Put`.** Le test est explicite en le service ADWS Microsoft :
 `if (operation == RequestType.Get || operation == RequestType.Delete ||
 operation == RequestType.Put)`. Dans ce bloc, un en-tête absent
 ou vide provoque une erreur d'argument portant
 `MustSpecifyObjectRefPropInTheHeader`
. Hors de ces trois actions, l'en-tête n'est
 simplement pas lu.
- **Ne pas confondre avec l'exclusion de l'inspecteur.**
 l’inspecteur d’en-têtes du service Microsoft exclut `Create` et
 `Enumerate` du **marquage `UnderstoodHeaders`**, ce qui n'est pas la même
 chose que « non requis » : c'est une décision sur `mustUnderstand`, prise
 avant même que le service ne regarde le message.
- **`ad:instance` est exigé pour toutes les opérations**, sans condition :
 le service le lit systématiquement, et une absence ou une valeur vide
 provoque une erreur d'argument explicite.
- La valeur d'`objectReferenceProperty` est **soit un GUID canonique de 36
 caractères**, **soit un DN**. Le test est `text.Length == 36 &&
 guidRegex.IsMatch(text)`, le motif étant
 `^[0-9a-fA-F]{8}-…-[0-9a-fA-F]{12}$`. Si la
 chaîne matche, elle est convertie en `Guid` ; sinon elle est rangée comme
 DN. Les deux formes coexistent sur le fil, et le `Get-ADUser -Identity`
 d'un GUID comme d'un DN emprunte le même en-tête.
- La valeur d'`instance` est une chaîne de la forme
 `LdapInstancePrefix + port`, soit `ldap:389` pour l'instance NTDS par
 défaut. Les constantes sont toutes dans les constantes du service ADWS Microsoft :

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

## Le GUID de la RootDSE

La valeur `11111111-1111-1111-1111-111111111111` n'est **pas** un
« InstanceId » : c'est `rootDSEGuid`
, le GUID conventionnel par lequel le client
désigne la RootDSE dans `objectReferenceProperty`. Le projet le reconnaît en
entrée et le réémet en sortie :

- **En entrée** — `GetHandler.handle` (`classes/handlers/get.py:39-43`)
 route vers la RootDSE si `object_reference` est vide, vaut `'root dse'`
 (insensible à la casse) ou vaut ce GUID, la comparaison étant elle aussi
 faite en minuscules (`get.py:42`).
- **En sortie** — `get.py:153-159` place ce même GUID dans
 `<ad:objectReferenceProperty>` du corps WS-Transfer de la réponse RootDSE.
 Attention : ce bloc n'est émis que dans la branche **non-IMDA**
 (`get.py:152`) ; en IMDA la RootDSE sort en
 `<da:BaseObjectSearchResponse>` sans référence d'objet
 (`get.py:146-151`).

À nuancer : la constante `WebServiceStrings.InstanceId = "InstanceId"`
**existe**. Ce qui est faux, c'est de la relier
au GUID de la RootDSE ou d'en faire l'en-tête du couple objet/instance : sur
le fil, ce couple est porté par `objectReferenceProperty` et `instance`,
et par rien d'autre.

## Ce que cette implémentation extrait

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
- **L'en-tête `ad:identity` n'existe pas** dans le protocole ni dans ce code. L'identité de l'appelant est portée par le contexte GSSAPI
 de la connexion, pas par un en-tête SOAP — cf. `connection.py:56`, qui
 construit le `session_info` transmis au dispatcher
 (`connection.py:57`), lequel le pousse dans chaque `BaseHandler` via le
 `HandlerRegistry` (`handler_registry.py:12`) puis dans `SambaDB`
 (`base.py:21`). Toute mention d'un en-tête `identity` serait une
 invention.
- **Un en-tête `mustUnderstand` propre à une action personnalisée est
 ignoré.** le contrat SetPassword du service Microsoft déclare
 un en-tête de message obligatoire nommé `Server` : le vrai
 client peut donc désigner un serveur cible dans l'en-tête d'un
 `SetPassword`. `SetPasswordHandler._extract`
 (`classes/handlers/set_password.py:31-37`) ne lit que `AccountDN` et
 `NewPassword` ; ni `Server`, ni le membre de corps `PartitionDN`
 ne sont consultés. Sans conséquence sur un DC
 unique, mais à savoir avant tout scénario multi-serveurs.

## L'EPR de retour : `wst:ResourceCreated`

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

- **1.** L'adresse est obtenue en relisant `<a:To>` de la requête par
 expression régulière (`create.py:75`) puis en substituant
 `ResourceFactory` par `Resource` (`create.py:76`). C'est la traduction
 fidèle du fait que `Create` arrive sur l'endpoint fabrique
 (`WcfResourceFactoryEndpoint`) alors que les opérations
 ultérieures sur l'objet visent l'endpoint ressource
 (`WcfResourceEndpoint`). Si `<a:To>` est introuvable, le repli est
 l'adresse anonyme (`create.py:77`).
- **2.** L'`objectReferenceProperty` renvoyé est le **GUID** de l'objet
 fraîchement créé, relu par une recherche LDB sur `objectGUID`
 (`create.py:67-71`) et converti par `uuid.UUID(bytes_le=…)`. En cas
 d'échec de relecture, c'est le GUID nul qui est renvoyé
 (`uuid.UUID(int=0)`), ce qui est une valeur de repli discutable mais
 explicite.
- **3.** L'`ad:instance` est codé en dur à `ldap:389` (`create.py:86`),
 conforme à la constante de la référence.

Le préfixe employé dans ce corps est `wsa:`, redéclaré localement, alors que
l'enveloppe déclare déjà `a:` pour la même URI : légal en XML, sans effet
côté client, mais incohérent stylistiquement.

## Les synthétiques du corps, à ne pas confondre

`objectReferenceProperty` apparaît aussi **dans le corps** des objets
sérialisés, comme attribut synthétique. `SYNTHETIC_KEYS`
(`classes/serialization/object_projector.py:9-12`) énumère les quatre
noms concernés : `distinguishedname`, `relativedistinguishedname`,
`objectreferenceproperty`, `containerhierarchyparent`. Ils sont rendus par
`_synthetic` (`object_projector.py:48-53`) en espace `ad:`, **sans**
attribut `LdapSyntax` et toujours avec `xsi:type="xsd:string"`. Ils sont
retirés du flux d'attributs normaux par `_normal`
(`object_projector.py:41-46`) pour éviter un doublon
`<addata:distinguishedName>`.

> À distinguer strictement : `<ad:objectReferenceProperty>` du corps porte le
> **identifiant global** de l'objet en forme canonique `xsd:string` ; l'attribut LDAP
> `objectGUID` sort, lui, en `xsd:base64Binary` du binaire brut
> (cf. `documentation/04-handlers.md`, section format fil). Confondre les
> deux produit un objet que le client refuse de désérialiser.

# Catalogue des actions SOAP et routage

## L'algorithme de résolution

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
 déjà en minuscules** — c'est un invariant tacite du fichier : une clé
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

Si aucun handler ne répond, `ADWSDispatcher._invoke`
(`dispatcher.py:37-43`) lève une `ADWSException` dont le message énumère
toutes les clés connues — ce qui rend le diagnostic immédiat dans
`journalctl`.

## Table 1 — correspondances exactes (`ACTION_HANDLER_KEYS`)

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

## Table 2 — catalogue exhaustif action → handler → fichier → cmdlet

Vingt-neuf clés sont enregistrées dans `HANDLER_FACTORIES`
(`handler_routing.py:53-71`). Le tableau ci-dessous les couvre toutes.
Abréviations d'URI : `WST` = `http://schemas.xmlsoap.org/ws/2004/09/transfer`,
`WSEN` = `http://schemas.xmlsoap.org/ws/2004/09/enumeration`,
`WSEV` = `http://schemas.xmlsoap.org/ws/2004/08/eventing`,
`CA` = `http://schemas.microsoft.com/2008/1/ActiveDirectory/CustomActions`.

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
en décide. À lire comme une carte
d'usage corroborée par les journaux du service, non comme une donnée
extraite d'un fichier.

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

### D'où viennent ces URI, et lesquelles sont des extensions

Il faut distinguer deux façons dont une URI d'action naît dans WCF.

- **Action explicite.** Les contrats WS-Transfer et WS-Enumeration
 déclarent leur action de requête et leur action de réponse en toutes lettres :
 le contrat Resource du service Microsoft, `:24`, `:38` pour `Get`/`Put`/`Delete` ;
 le contrat Enumeration du service Microsoft, `:25`, `:35`, `:42`, `:48` pour
 `Enumerate`/`Pull`/`Renew`/`GetStatus`/`Release`. Ces neuf URI sont donc
 lues telles quelles dans la référence.
- **Action implicite.** Les contrats d'actions personnalisées n'écrivent
 qu'une opération nue (le contrat AccountManagement du service Microsoft,
 `:13`, `:17`, `:21`, `:25`, `:29`). WCF applique alors sa convention par
 défaut `{Namespace}/{ContractName}/{Operation}`, avec
 `Namespace = "…/CustomActions"` et `ContractName = "AccountManagement"`
 ou `"TopologyManagement"`. Les URI `CA/…` de
 la table 2 sont donc **reconstruites par convention**, pas lues sur le
 fil. Elles sont corroborées par les constantes `REPLY_ACTION` du dépôt et
 par `tools/test/test_handlers.py:16-19`, mais n'ont pas été observées
 dans une capture au moment d'écrire ce chapitre.

> **Honnêteté sur les trois dernières lignes de la table 2.** Les URI
> d'action se terminant par `/Search`, `/Schema` et `/Groups` **ne figurent
> dans aucune opération publiée par le service Microsoft**. Le contrat
> `IEnumeration` porte bien `Name = "Search"`, mais
> ses cinq opérations déclarent toutes une `Action` explicite, si bien
> qu'aucune action ne finit par `/Search`. Ces trois clés sont donc des
> **points d'extension du projet**, atteignables uniquement par un client
> construit exprès. `SearchHandler` reste néanmoins utile : il normalise le
> filtre LDAP via `FilterParser` puis délègue à `EnumerateHandler`
> (`classes/handlers/search.py:16-25`).

Même verdict pour `Notify`, avec une nuance : c'est la **seule** extension
qui dispose d'une entrée de correspondance exacte dans
`ACTION_HANDLER_KEYS` (`handler_routing.py:49-50`). Or
`IActiveDirectoryAccountManagement` ne déclare que six opérations —
`GetADGroupMember`, `GetADPrincipalGroupMembership`, `SetPassword`,
`ChangePassword`, `GetADPrincipalAuthorizationGroup`, `TranslateName` — et
`Notify` n'en fait pas partie. `NotifyHandler` renvoie
d'ailleurs un corps vide (`<ca:Events/>`, `notify.py:12-16`) : c'est un
bouchon, pas une implémentation. Aucune opération d'ajout ou de retrait de
membre n'y figure non plus, ce qui confirme que `Groups` est une invention
du projet, non une action que le module PowerShell émettrait.

## Table 3 — actions de réponse

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

## Les sous-routeurs

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
`ActionNotSupported` (`transfer.py:22-26`, `crud.py:26-30`) — et non une
exception, donc sans passer par le chemin d'erreur du dispatcher.

# Contrôles LDAP transportés en en-tête

## Forme sur le fil

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
autonome au sens strict : c'est un membre porté par les messages de corps des
opérations concernées (création, recherche par objet de base, modification).
Il n'existe par ailleurs **aucun** élément nommé `ldapControls` — cette
dénomination, parfois rencontrée, ne correspond à rien dans le protocole ni
dans ce dépôt.

## Ce que ce serveur parse

`ControlsParser` (`classes/parsing/controls_parser.py:31`) travaille sur le
document entier :

```python
for elem in root.findall(".//ad:controls/ad:control", NS):
```

Le XPath `.//ad:controls/ad:control` (`controls_parser.py:36`) attrape donc
les contrôles où qu'ils se trouvent, en-tête comme corps — ce qui rend le
parseur indifférent au fait qu'ils voyagent dans le corps.
`_read_one` (`controls_parser.py:51-59`) accepte l'attribut `type` **ou**
`OID` comme porteur de l'OID, lit `criticality` (défaut `false`) et le texte
de `<ad:controlValue>`.

`RequestContext._parse_controls` (`context.py:171-178`) appelle
`ControlsParser.to_ldb` dans un `try/except Exception` qui renvoie `None` en
cas d'échec : **un contrôle mal formé n'échoue jamais la requête**, il est
simplement ignoré. C'est une décision de robustesse, à connaître quand on
débogue un contrôle qui « ne fait rien ».

## Table exhaustive des OID reconnus

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
> de contrôles de Samba ne connaît pas fait **échouer la recherche entière**,
> pas seulement le contrôle. `managedBy` et `search_notification` ne sont pas
> des noms de contrôle `ldb` — le premier est un nom d'attribut d'annuaire,
> le second n'existe pas.

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

- **`sort_resp` est un contrôle de *réponse*.** Un client ne l'émet pas ;
 le trouver dans une table de traduction requête vers LDB est au mieux
 inutile.
- Un OID **absent de la table** est silencieusement supprimé :
 `_translate` (`controls_parser.py:62-74`) retourne `None` et
 `to_ldb` ne l'ajoute pas. Aucune faute n'est levée, même pour un contrôle
 déclaré `criticality="true"` — alors que la sémantique LDAP v3 exige
 qu'un contrôle critique non supporté fasse **échouer** l'opération. **C'est
 un écart au niveau 1, documenté ici.**
- `_read_one` accepte l'attribut `type` **ou** l'attribut `OID`
 (`controls_parser.py:53`). Seul `type` a un correspondant sur le fil
 ; `OID` est une tolérance défensive sans émetteur
 connu.
- `criticality` est lu avec `(elem.get("criticality") or "false").lower ==
 "true"` (`controls_parser.py:56`). Un client qui écrirait `1` au lieu de
 `true` — forme légale pour `xsd:boolean` — verrait donc son contrôle
 dégradé en non critique. Le sérialiseur .NET écrit `true`/`false`, donc le
 cas ne se présente pas au niveau 2, mais la lecture est plus étroite que
 le schéma.

## Traduction vers la syntaxe LDB

`_translate` (`controls_parser.py:62-74`) produit une chaîne au format
Samba `nom:criticité[:valeur]` :

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
> `:` produit, pour `paged_results` (dont la valeur est un
> `SEQUENCE { size INTEGER, cookie OCTET STRING }`), une chaîne sans
> signification. Autrement dit : **la taille de page demandée par le client
> ne survit pas à la traduction**. C'est cohérent avec la limite déjà notée
> dans `documentation/01-architecture.md` — « les contrôles `PagedResults`
> côté client sont acceptés mais le serveur fait un seul `search` complet
> et pagine côté handler ». Le contrôle n'est donc pas *honoré*, il est
> *toléré*.

## Où les contrôles sont réellement appliqués

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
`SECURITY_INFORMATION` de valeur **`0`**. Ce masque valant 1 pour OWNER,
2 pour GROUP, 4 pour DACL et 8 pour SACL, `0` ne demande **aucune** partie
du descripteur de sécurité — précisément l'intention : ne pas en payer le
coût de lecture, et ne pas déclencher le contrôle d'accès sur la SACL, qui
exige `SeSecurityPrivilege`. Deux conséquences directes :

- **`context.ldap_controls` n'est consommé que par `EnumerateHandler`**
 (donc aussi par `SearchHandler`, qui délègue). Un `show_deleted` envoyé
 sur un `Get` unitaire est parsé, rangé dans le contexte… et jamais
 utilisé — le `Get` écrase la liste par son `sd_flags:1:0` codé en dur.
- **`DeleteHandler` ne passe pas par `ControlsParser`.** Il cherche la
 chaîne littérale `1.2.840.113556.1.4.805` dans le XML brut
 (`delete.py:42`) et, si elle y figure, envoie `tree_delete:1`. C'est
 volontairement grossier — la constante `_TREE_DELETE_OID`
 (`delete.py:10`) est commentée comme provenant de `Remove-AD* -Recursive`
 — mais cela signifie qu'un OID mentionné n'importe où dans le message
 déclenche la suppression récursive. À durcir.

# Les fautes SOAP

## Structure XML exactement produite

Tout passe par `SoapEnvelope.fault`
(`classes/soap/soap_envelope.py:46-59`) et `_code`
(`classes/soap/soap_envelope.py:61-66`). Le corps produit est :

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

Deux valeurs seulement sont employées pour `<s:Code><s:Value>` :
`s:Sender` (constante `FaultBuilder.SENDER`, `classes/faults/faults.py:10`)
et `s:Receiver` (`FaultBuilder.RECEIVER`, `faults.py:11`). Ce sont les
codes SOAP 1.2 standards : faute imputable à l'émetteur, ou au récepteur.

> **Le sous-code est limité aux préfixes de `NS_DECL`.** Un sous-code SOAP
> 1.2 est un QName : son préfixe doit être déclaré sur l'enveloppe. `ca:`
> l'est (`soap_envelope.py:28`), donc `ca:SetPasswordFault` est valide.
> Mais un futur `wsman:AccessDenied` produirait un préfixe **non lié** —
> `wsman` n'est pas dans `NS_DECL` — donc un XML rejeté par le lecteur .NET.
> Câbler `TypedFaults` demande donc de toucher aussi à `NS_DECL`, pas
> seulement d'appeler la bonne fabrique.

## Générateurs disponibles

`FaultBuilder` (`classes/faults/faults.py:8`) — quatre fabriques :

| Méthode | Code | Sous-code | Détail |
|---|---|---|---|
| `directory_error` | `s:Receiver` | aucun | `<da:Fault>` ShortError + LongError |
| `access_denied` | `s:Sender` | aucun | aucun |
| `custom_action_fault` | `s:Receiver` | `ca:{nom}` | `<{nom}>` du namespace CA |
| `invalid_enumeration_context` | `s:Sender` | aucun | aucun |

`custom_action_fault` (`faults.py:28-41`) est la seule qui change aussi
l'action : elle passe `action=FAULT_NS`, soit
`http://schemas.microsoft.com/2008/1/ActiveDirectory/Data/fault`. C'est
**exactement** l'`Action` déclarée par toutes les fautes de custom
actions. Les douze noms de faute concernés se répartissent en six pour
AccountManagement et cinq pour TopologyManagement, plus `GetVersionFault`.

Le sous-code `ca:{nom}` produit par `faults.py:40` est lui aussi correct :
toutes ces fautes portent
`Namespace = "…/2008/1/ActiveDirectory/CustomActions"`, et WCF compose le
sous-code SOAP 1.2 à partir du couple (Namespace, Name).

> **Écart de code SOAP, non signalé jusqu'ici.** La référence construit ces
> fautes par `GenerateCustomActionFaultMessage(…, receiverFault: false, …)`
>, et `receiverFault: false` se traduit
> par `FaultCode.CreateSenderFaultCode`, donc
> `<s:Value>s:Sender</s:Value>`. Ce projet émet `cls.RECEIVER`, soit
> `s:Receiver` (`faults.py:39`). Le sous-code est le bon, le code
> principal ne l'est pas. Un client qui trie ses erreurs entre « ma faute »
> et « faute du serveur » classera donc à tort toute erreur d'action
> personnalisée du côté serveur.

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

Les quatre membres correspondent aux propriétés `ArgumentError`
, `Error` (`:42-53`), `DirectoryError`
(`:55-66`) et `ShortError` (`:68-79`) de la classe abstraite
`CustomActionFault`. L'ordre d'émission de `faults.py:32-35` —
`ArgumentError`, `DirectoryError`, `Error`, `ShortError` — est l'ordre
alphabétique du sérialiseur par contrat de données : c'est le bon, bien qu'il ne soit
pas l'ordre de déclaration en C#.

**Écarts sur le contenu**, tous vérifiés :

| Membre | Ce projet | La référence |
|---|---|---|
| `ArgumentError` | toujours `xsi:nil` | rempli si `ArgumentException` |
| `DirectoryError` | toujours `xsi:nil` | rempli si erreur d'annuaire |
| `ShortError` | copie de `Error` | via `LongToShortMap`, sinon `null` |
| `<s:Reason>` | le message d'erreur | chaîne fixe `ArgumentError` |

`TypedFaults` (`classes/faults/typed_faults.py:14`) — cinq fabriques, une
par famille de spécification :

| Méthode | Code SOAP | Élément de détail | Espace de noms du détail |
|---|---|---|---|
| `wsman` | `s:Sender` | `<wsman:FaultDetail>` | `…/wsman/1/wsman.xsd` |
| `wsaddressing` | `s:Sender` | `<wsa:FaultDetail>` | `…/ws/2004/08/addressing` |
| `directory` | `s:Receiver` | `<da:Fault>` | `…/IdentityManagement/DirectoryAccess` |
| `transfer` | `s:Sender` | `<wst:Fault>` | `…/ws/2004/09/transfer` |
| `enumeration` | `s:Sender` | `<wsen:Fault>` | `…/ws/2004/09/enumeration` |

Chacune produit un détail à deux enfants, `Code` (le nom court) et
`Message` (le texte). C'est un format **maison** : la référence utilise des
schémas de détail plus riches (`FaultDetail`, `SupportedDialect`,
`AttributeTypeNotValid`, …). Le rapprochement se fait sur le **nom** placé
dans `<*:Code>`.

## Table exhaustive des codes typés

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

Ces seize noms sont **exactement** ceux déclarés par les fautes de
la référence, ce qui est le point le plus important : un client qui
inspecte le sous-code y retrouvera un libellé qu'il connaît. La
vérification est directe : chaque nom correspond à une faute déclarée par
le contrat Resource du service Microsoft ou le contrat Enumeration du service Microsoft :

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

- **`WSEN_ENUMERATION_LIMIT` est mal classé.** `EnumerationContextLimitExceeded`
 est déclaré avec
 `Namespace = "http://schemas.microsoft.com/2008/1/ActiveDirectory"`
 et généré avec ce même espace de noms
, **pas** dans l'espace WS-Enumeration.
 L'émettre par `TypedFaults.enumeration` produirait donc un sous-code dans
 le mauvais espace de noms.
- **`CannotProcessFilter` existe en double.** Sous WS-Management pour
 `Get`/`Put` (le contrat Resource du service Microsoft, généré en le générateur de fautes du service ADWS Microsoft et
 `:177`) et sous WS-Enumeration pour `Enumerate` (le contrat Enumeration du service Microsoft,
 généré en le générateur de fautes du service ADWS Microsoft et `:359`). Le préfixe `WSMAN_` de
 `fault_codes.py:6` ne couvre donc que la moitié des cas.

Six noms de faute de la référence n'ont en revanche **aucune** constante
dans `fault_codes.py` : `AlreadyExists` (wsman, le générateur de fautes du service ADWS Microsoft),
`InvalidSortKey` (`:380`), `InvalidPropertyFault` (`:402`),
`MaxCharsNotSupported` (`:417`), `MaxTimeExceedsLimit` (`:422`) et
`UnsupportedSelectOrSortDialectFault`, les cinq
derniers dans l'espace de noms `AD`.

> **Écart majeur, à corriger en priorité.** Ni `TypedFaults` ni les
> constantes de `fault_codes.py` **ne sont utilisées par un seul handler**
> à ce jour. `BaseHandler.__init__` expose `self.typed_faults`
> (`classes/handlers/base.py:28`), mais aucune sous-classe ne l'appelle. En
> pratique, **toutes** les fautes émises sont soit `directory_error`, soit
> `custom_action_fault`, soit `invalid_enumeration_context`, soit la faute
> générique du dispatcher. L'infrastructure typée existe et est correcte ;
> son câblage reste à faire.

## Correspondance code LDB / Samba → faute

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

Dans tous les cas, le texte de l'exception Samba — typiquement
`(68, 'Entry... already exists')` ou
`(50, 'Insufficient access rights')` — est **recopié tel quel** dans
`<s:Reason><s:Text>` et dans `<da:LongError>`. L'information est donc
présente et exploitable par un humain, mais elle n'est pas normalisée : le
client ne peut pas la discriminer par sous-code.

Les six libellés listés par `documentation/03-protocole.md:241-249` sous le
titre « Codes de fault typés (`src/faults/fault_codes.py`) » —
`DirectoryError`, `InsufficientAccessRights`, `ConstraintViolation`,
`ObjectClassViolation`, `EntryAlreadyExists`, `NoSuchObject` — **ne
correspondent à aucune constante de ce fichier**, qui n'en contient aucun
des six. Ce sont en réalité des valeurs de l'énumération `ResultCode` de
`System.DirectoryServices.Protocols`, que le vrai ADWS teste pour choisir
sa faute. La documentation projet est donc à corriger sur ce point.

Le mapping réel de la référence se lit dans deux endroits complémentaires :
la chaîne de `catch` de chaque opération (pour le bloc `Create`,
le service ADWS Microsoft) et les fabriques de
le générateur de fautes du service ADWS Microsoft, qui portent le nom, l'espace de noms, l'action et le
caractère émetteur/récepteur de la faute. Le tableau ci-dessous croise les
deux ; toutes les cellules sont vérifiées dans le code de référence.

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

Le mécanisme central est `CreateMessageFault` :
un booléen `receiverFault` choisit entre
`FaultCode.CreateReceiverFaultCode(faultName, faultNamespace)` et
`FaultCode.CreateSenderFaultCode(…)`. Il faut en retenir que **la référence
émet `s:Sender` dans l'écrasante majorité des cas** — seules
`DestinationUnreachable` et `EndpointUnavailable` (variantes LDAP et
connexion) sont `s:Receiver`. Ce projet, lui, émet `s:Receiver` pour toutes
ses `directory_error` et ses `custom_action_fault`, et `s:Sender`
uniquement pour `access_denied` et `invalid_enumeration_context`. C'est
l'inverse de la référence pour la quasi-totalité des cas d'erreur réels.

Câbler ces deux tableaux dans `classes/faults/` — en interceptant le tuple
`(code, message)` que Samba met dans ses `ldb.LdbError` plutôt que
`str(e)` — est le chantier naturel pour aligner le niveau 3 sur le
niveau 2. Le code numérique LDAP est déjà à portée de main : la forme
`(68, 'Entry... already exists')` que l'on retrouve aujourd'hui dans le
`<s:Reason>` est la représentation textuelle d'un `ldb.LdbError` dont le
premier argument est précisément l'entier `ResultCode`. L'implémentation
actuelle ne consomme que `str(e)` et jette donc l'information la plus
exploitable du lot.

## Hiérarchie d'exceptions

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
`pull.py:23`, `:29` et `:47`, `release.py:23` et `:40`. Les six
sous-classes sont déclarées mais inutilisées — pendant exact de
l'observation faite sur `TypedFaults`. L'attribut `code` n'est jamais
renseigné autrement qu'à sa valeur par défaut, et n'est jamais lu.

## Inventaire du code mort de la couche message

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
faute** qui n'ont aucun consommateur. Autrement dit, l'infrastructure de
fautes typées est complète à un fil près : il manque le point d'appel.

# Construction des réponses dans l'implémentation

## Séquence exacte du dispatcher

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

## Le chemin d'erreur

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
 `dump_records` lèvent — c'est-à-dire si le handler a produit un XML
 invalide — l'exception remonte dans `handle_messages`, qui la journalise
 et retourne `False` : la connexion est fermée sans réponse. Côté Windows
 cela donne « Le site distant a fermé le flux de transport »
 (`documentation/06-depannage.md` § 2). C'est le seul chemin où le client
 ne reçoit rien du tout.

Enfin, deux familles de handlers **n'atteignent jamais le chemin d'erreur du
dispatcher** parce qu'elles rattrapent tout localement et retournent une
faute déjà construite : les handlers CRUD/CA (via `FaultBuilder`) et
`GetHandler` (via `build_soap_fault`, `classes/handlers/base.py:39-40`).
Seuls `EnumerateHandler`, `PullHandler` et `ReleaseHandler` laissent
délibérément remonter une `ADWSException`.

## Exemple 1 — WS-Transfer Get en mode IMDA

Requête (`Get-ADUser -Identity demo -Properties sAMAccountName`, forme
IMDA avec attributs demandés) :

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

`RequestContext` en tire : `action = ".../transfer/Get"`,
`message_id = "urn:uuid:2b5f…"`,
`object_reference = "CN=demo,CN=Users,DC=samba,DC=local"`,
`is_imda = True` (présence de `<da:BaseObjectSearchRequest>`,
`context.py:66-69`), `requested_attributes = ["sAMAccountName"]`
(le préfixe `addata:` est retiré en `context.py:79-80`).

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

Le `<da:PartialAttribute>` final portant `distinguishedName` est **toujours**
émis, y compris s'il n'a pas été demandé : c'est `imda_projection`
(`classes/serialization/object_projector.py:30-39`) qui l'ajoute
inconditionnellement, en concaténant `attrs_xml` puis
`<da:PartialAttribute>{dn_syn}</da:PartialAttribute>`
(`object_projector.py:34-38`). Il est en espace `ad:` et **sans**
`LdapSyntax` — invariant projet, et exigence du désérialiseur client.

> **Une exception à cet invariant, dans le code même.** `imda_projection`
> n'est appelée que lorsque `context.is_imda` **et**
> `context.requested_attributes` sont tous deux vrais (`get.py:273-274`).
> La RootDSE en mode IMDA passe par un chemin distinct
> (`get.py:146-151`) qui appelle
> `render_attributes(attributes, wrap_partial=True)` et n'ajoute **aucun**
> `distinguishedName`. C'est défendable — la RootDSE n'a pas de DN — mais
> cela signifie que l'affirmation « en IMDA, toujours émettre
> `distinguishedName` » souffre une exception qu'il faut connaître avant de
> déboguer une réponse RootDSE.

Le rendu des attributs ordinaires est porté par `AttributeRenderer` :
enveloppe `<da:PartialAttribute>` si `wrap_partial` (`xml_renderer.py:30`),
valeur en `<ad:value xsi:type="{xsd}">` (`:42`), attribut en
`<addata:{nom} LdapSyntax="{syn}">` (`:47`).

## Exemple 2 — WS-Enumeration Enumerate puis Pull

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
`PartialAttribute` ; et la continuation est **exclusive** — soit
`<wsen:EndOfSequence/>`, soit un nouveau `<wsen:EnumerationContext>`, jamais
les deux (`pull.py:85-91`). Si le lot est vide, l'élément est auto-fermé
`<wsen:Items/>` (`pull.py:83-84`).

L'ordre des enfants de `<addata:user>` est fixé par `whole_object`
(`object_projector.py:20-28`) : `objectReferenceProperty` (`:24`, omis si
le GUID est vide), les attributs ordinaires (`:23`),
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
divergence reste théorique — mais elle est réelle.

## Exemple 3 — action personnalisée SetPassword, succès et faute

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

> **La requête réelle est plus riche que cet exemple.**
> le contrat SetPassword du service Microsoft déclare quatre membres, pas deux : un en-tête
> un en-tête de message obligatoire `Server` et
> trois membres de corps, `PartitionDN` (`:12`), `AccountDN` (`:15`) et
> `NewPassword` (`:18`). Ce serveur n'en lit que deux.

`BodyParser.find_custom_body("SetPasswordRequest")`
(`classes/parsing/body_parser.py:34-38`) localise l'élément par
`.//ca:SetPasswordRequest` avec la table de préfixes de
`body_parser.py:7-14` ; `text_of` (`body_parser.py:40-46`) fait de même
pour les enfants. C'est ce qui rend le parsing indifférent au préfixe
choisi par le client : ElementTree résout `ca:` vers l'URI, si bien qu'un
client émettant `<tns:SetPasswordRequest xmlns:tns="…/CustomActions">`
est trouvé tout aussi bien.

> **Le « repli » des lignes 38 et 45 est un no-op.** `.//ca:X` résolu avec
> `NS` et `.//{CUSTOM_ACTIONS}X` désignent, pour ElementTree, exactement le
> même chemin : le second `find` ne peut jamais réussir là où le premier a
> échoué. La vraie limite est ailleurs — un élément **sans espace de noms**
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

## Exemple 4 — faute générique du dispatcher

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
élément qui rende la faute exploitable côté client est le `RelatesTo` — ce
qui referme la boucle du chapitre.

## Synthèse des écarts connus de la couche message

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

Les deux dernières lignes concernent la documentation du dépôt, pas le
code : `documentation/03-protocole.md:117-120` montre un bloc
`<wsa:ResourceReference><wsa:InstanceId>` qui n'existe nulle part dans la
référence, et `:241-249` attribue à `src/faults/fault_codes.py` six libellés
qui n'y figurent pas. Conformément au § 7 du CLAUDE.md, ces deux corrections
doivent partir dans le même commit que toute modification du comportement
décrit.
