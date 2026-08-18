# Modèle de données [MS-ADDM] et projection des objets AD

Les chapitres précédents ont mené le lecteur du cadrage `net.tcp` jusqu'à
l'enveloppe SOAP 1.2 en clair. À partir d'ici, le transport disparaît : tout ce
qui suit décrit la **sémantique applicative** d'ADWS, c'est-à-dire la manière
dont un objet de l'annuaire est identifié, projeté en XML, filtré, muté et
paginé.

## Les trois couches de vocabulaire

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

La distinction `ad:` contre `addata:` n'est pas cosmétique : c'est **la** règle
qui décide si le client Windows accepte ou rejette la réponse. Tout élément
placé dans `addata:` est traité comme un attribut d'annuaire et **doit** porter
un attribut XML `LdapSyntax` ; tout élément placé dans `ad:` est un élément
structurel et **ne doit pas** en porter. Ces deux invariants sont matérialisés
dans `classes/serialization/xml_renderer.py:45-49` (chemin `addata:`) et
`classes/serialization/object_projector.py:48-53` (chemin `ad:`).

## L'identité d'un objet : `objectReferenceProperty`

Le client n'adresse jamais un objet par une URL. Il place l'identité dans un
**en-tête SOAP** `<ad:objectReferenceProperty>`, accompagné d'un en-tête
`<ad:instance>`. La règle appliquée par le serveur Microsoft est la
suivante :

| Étape | Comportement |
|---|---|
| `objectReferenceProperty` | exigé pour `Get`, `Delete`, `Put` |
| `instance` | exigé pour **toutes** les opérations |
| Discrimination GUID / DN | `1623-1645` | 36 caractères + `guidRegex` → `Guid` |
| Repli DN | `1639-1643` | si le `Guid` reste `Guid.Empty` → `ObjectDn` |
| Résolution de l'instance | `1647-1653` | `GlobalInstanceMap`, sinon faute |

L'absence de l'un des deux en-têtes lève une `ArgumentException`
(`MustSpecifyObjectRefPropInTheHeader`, `MustSpecifyInstanceInfoInTheHeader`) ;
une valeur d'`instance` inconnue de la carte globale lève
`InvalidInstanceInTheHeader`.

Ce projet extrait la même valeur (`classes/parsing/context.py:64`) mais avec un
`findtext` non ancré (`.//ad:objectReferenceProperty`), qui la trouve donc
aussi bien dans l'en-tête que dans le corps. L'en-tête `<ad:instance>` n'est,
lui, **jamais lu** : aucune recherche de cet élément n'existe dans
`context.py`, et aucune faute n'est levée s'il manque. En revanche la
**résolution** est plus étroite : `classes/handlers/get.py:211-214` construit
la liste des DN à essayer et lance un `search(base=...)` sur chacun.
Conséquences à connaître :

- un `objectReferenceProperty` en forme **DN** fonctionne ;
- la branche RootDSE est déclenchée par trois valeurs, pas une seule
 (`classes/handlers/get.py:39-42`) : chaîne vide, littéral `root dse`
 (comparaison en minuscules) et
 `11111111-1111-1111-1111-111111111111` ;
- le second candidat `f"{obj_ref},{self.naming_context}"` (`get.py:214`) est
 **du code mort** : il est gardé par `hasattr(self, 'naming_context')`
 (`get.py:213`) et ni `BaseHandler.__init__` (`classes/handlers/base.py:19-29`)
 ni `GetHandler` ne définissent cet attribut — le contexte de nommage n'est
 accessible que par la méthode `self.db.naming_context`. Un DN relatif n'est
 donc jamais complété ;
- tout **autre GUID** n'est pas converti en DN : la recherche LDB échoue et le
 handler renvoie `Object not found`. La syntaxe `<GUID=…>` de LDB n'est pas
 employée. C'est un écart assumé par rapport au serveur Microsoft, sans impact
 observé sur les cmdlets testées, qui adressent par DN.

## Projection d'un objet : l'ordre imposé des éléments

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
`classes/handlers/pull.py:58-65`) — LDB renvoie la hiérarchie de la plus
générale à la plus spécifique, donc `top, person, organizationalPerson, user`
donne `user`. La valeur de repli est `top` ; c'est ce qui est utilisé pour la
RootDSE (`classes/handlers/get.py:161`).

Le tableau ci-dessous fait correspondre chaque étape du serveur Microsoft à sa
contrepartie dans le dépôt.

| Composant | Service ADWS Microsoft | Ce projet |
|---|---|---|
| Wrapper `addata:{classe}` | `65` / `69-73` | `object_projector.py:28` |
| `ad:objectReferenceProperty` | `75-82` | `object_projector.py:24` |
| Boucle des attributs `addata:` | `83-115` | `xml_renderer.py:22-33` |
| Attribut XML `LdapSyntax` | `106` | `xml_renderer.py:45-49` |
| `ad:containerHierarchyParent` | `116-123` | non émis |
| `ad:relativeDistinguishedName` | `124-131` | `object_projector.py:26` |
| `ad:distinguishedName` | `132-139` | `object_projector.py:27` |

Deux comportements du serveur de référence n'ont **aucune** contrepartie ici :

- `containerHierarchyParent` n'est émis que si `ParentIdentity` est renseigné
. Ce projet le déclare comme attribut synthétique
 et le **filtre** systématiquement (`object_projector.py:9-12`) sans jamais
 le produire ; aucune cmdlet testée ne s'en plaint.
- la **récupération par plages** (*range retrieval*) : quand le nom d'attribut
 contient ` ;range=`, Microsoft découpe le suffixe et émet deux attributs XML
 `rangeLow` et `rangeHigh` sur l'élément `addata:`
. Ce projet ne reconnaît pas la syntaxe
 ` ;range=` : un attribut lié très volumineux (par exemple `member` sur un
 groupe de plusieurs milliers d'entrées) est rendu d'un seul tenant ou tronqué
 par LDB, sans négociation de plage.

## Les quatre attributs synthétiques

| Élément | Espace | `LdapSyntax` | Source de la valeur |
|---|---|---|---|
| `objectReferenceProperty` | `ad:` | non | `objectGUID` converti en GUID canonique |
| `containerHierarchyParent` | `ad:` | non | non émis par ce projet |
| `relativeDistinguishedName` | `ad:` | non | premier segment du DN |
| `distinguishedName` | `ad:` | non | DN complet de l'objet |

Ces quatre noms sont regroupés dans `SYNTHETIC_KEYS`
(`classes/serialization/object_projector.py:9-12`), en minuscules, et
`_normal` (`object_projector.py:41-46`) les **retire du flux
d'attributs normaux**. Sans ce filtrage, Samba — qui expose `distinguishedName`
comme un attribut LDAP ordinaire — provoquerait l'émission simultanée d'un
`<addata:distinguishedName LdapSyntax="…">` et d'un `<ad:distinguishedName>`,
soit deux représentations concurrentes de la même donnée dans le même objet.

Côté Microsoft, les quatre synthétiques sont tous écrits comme des chaînes
Unicode : ils portent donc un enfant `<ad:value xsi:type="xsd:string">` mais
**jamais** d'attribut `LdapSyntax`, celui-ci n'étant émis que dans la boucle
des attributs `addata:`. Le dépôt obtient le même
résultat structurellement : `_synthetic` (`object_projector.py:48-53`) est une
fonction de deux lignes qui ne sait pas écrire d'attribut XML.

Point crucial : `objectReferenceProperty` est typé `xsd:string` alors que
l'attribut LDAP `objectGUID` est typé `xsd:base64Binary`. Ce n'est pas une
incohérence. Côté Microsoft, `objectReferenceProperty` est un identifiant global
et le sérialiseur de valeurs du client sérialise un identifiant global en `xsd:string` sous sa
forme canonique, alors que `objectGUID` est chargé
en `octets` et part en base64. Le dépôt reproduit ce dédoublement : conversion
`uuid.UUID(bytes_le=…)` pour l'EPR (`classes/handlers/get.py:270-271`,
`classes/handlers/pull.py:67-73`) et base64 brut pour l'attribut.

---

# WS-Transfer : Get, Put, Create, Delete

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

## Get

Un `Get` WS-Transfer pur a un corps **vide** (ou contenant uniquement un bloc
`<ad:controls>`). Toute l'information est dans les en-têtes.

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
liste d'attributs `['*']` — augmentée des attributs explicitement demandés
(`get.py:223-225`) puis étendue par `ConstructedAttrs.expand` (`get.py:226`) —
et le contrôle `sd_flags:1:0` (`get.py:220`).

Ce dernier mérite une lecture attentive, car la chaîne de contrôle LDB a la
forme `nom:criticité:valeur` — la même que celle produite par
`ControlsParser._translate` (`classes/parsing/controls_parser.py:62-74`). Ici
la **criticité vaut 1** et la **valeur du masque `SD_FLAGS` vaut 0** ; ce n'est
donc pas `OWNER_SECURITY_INFORMATION`. Le contrôle
`LDAP_SERVER_SD_FLAGS_OID` (`1.2.840.113556.1.4.801`, [MS-ADTS]) sélectionne
les portions du `nTSecurityDescriptor` à renvoyer ; avec un masque nul, la
SACL — dont la lecture exige le privilège `SeSecurityPrivilege` — est exclue,
ce qui évite qu'une lecture par un compte non privilégié n'échoue. La même
paire base vide / `sd_flags:1:0` est employée pour la RootDSE (`get.py:120`).

La réponse porte l'action `…/transfer/GetResponse` **quelle que soit** la forme
retenue (WS-Transfer ou IMDA) ; c'est aussi ce que fait le serveur Microsoft,
qui construit le même URI d'action sur ses deux branches :
le service ADWS Microsoft pour le `BaseObjectSearchResponse` IMDA et
le service ADWS Microsoft pour l'objet WS-Transfer. Le discriminant de
forme est traité en détail plus bas.

### Le cas RootDSE

`Get-ADRootDSE` est le tout premier échange de n'importe quelle session. Il
passe par le même `GetHandler`, branche `_get_root_dse`
(`classes/handlers/get.py:110-198`) : recherche `SCOPE_BASE` sur une base vide,
`objectClass` retiré du flux, wrapper `<addata:top>` et
`objectReferenceProperty` fixé à `11111111-1111-1111-1111-111111111111`.

Deux ajustements sont indispensables et méritent d'être connus :

- **Suppression d'attributs.** `_ROOTDSE_DROP`
 (`classes/handlers/get.py:15-17`) retire `vendorName` et `vendorVersion`, que
 Samba expose mais qu'un AD réel n'expose pas. Le client Windows résout le nom
 d'attribut dans une table de syntaxes RootDSE codée en dur, sans variante
 tolérante : une clé inconnue déclenche une exception côté client et **casse
 toutes les cmdlets** dès la connexion.
- **Ajout d'attributs.** `msDS-PortLDAP` et `msDS-PortSSL` sont injectés avec
 les valeurs `389` et `636` s'ils manquent (`classes/handlers/get.py:62-65`) :
 Samba ne les publie pas, le client les attend.

## Create

Le corps d'un `Create` est un `<da:AddRequest>` IMDA, jamais un objet
`addata:` complet. Le DN cible n'est pas transmis tel quel : le client envoie
un `relativeDistinguishedName` et un `container-hierarchy-parent`, tous deux
sous forme d'`<da:AttributeTypeAndValue>` ordinaires.

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

`CreateHandler._resolve_dn` (`classes/handlers/create.py:54-64`) applique trois
règles **dans cet ordre de priorité**, et non dans l'ordre inverse :

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
(`classes/handlers/create.py:74-90`) dont l'adresse est celle du `<a:To>` de la
requête avec `ResourceFactory` remplacé par `Resource`, et dont les
`ReferenceParameters` portent le `objectGUID` fraîchement lu et
`<ad:instance>ldap:389</ad:instance>`.

## Put

Le corps est un `<da:ModifyRequest>` contenant des `<da:Change>` portant chacun
un attribut `Operation` valant `add`, `delete` ou `replace`
(`classes/parsing/attribute_parser.py:19,37`). L'implémentation traite un `Put`
en deux temps (`classes/handlers/modify.py:21-36`) :

- **1.** `_apply_rename` (`modify.py:48-61`) : si le `ModifyRequest` touche
 `relativeDistinguishedName` ou `container-hierarchy-parent`, ce n'est pas une
 modification d'attribut mais un `modrdn`. Un `ldb.rename` est exécuté, les
 deux clés sont retirées du lot et le nouveau DN devient la cible.
- **2.** `_modify_attrs` (`modify.py:64-71`) : les changements restants sont
 compilés en `ldb.Message` par `LdapAttrBuilder.build_message` avec le drapeau
 par défaut `FLAG_MOD_REPLACE`, puis appliqués par `samdb.modify`.

C'est ce chemin unique qui sert `Set-ADUser`, `Rename-ADObject`,
`Move-ADObject`, `Enable-ADAccount`/`Disable-ADAccount` (qui ne sont qu'un
`replace` sur `userAccountControl`) et, très probablement, `Add-ADGroupMember`
et `Remove-ADGroupMember` — voir la réserve exprimée au chapitre des
appartenances.

La correspondance `Operation` → drapeau LDB est établie dans
`classes/directory/ldap_attr_builder.py:40-49` :

| `Operation` XML | Drapeau LDB | Effet |
|---|---|---|
| `add` | `FLAG_MOD_ADD` | ajoute des valeurs sans toucher aux existantes |
| `delete` ou `remove` | `FLAG_MOD_DELETE` | retire les valeurs listées |
| `replace` | `FLAG_MOD_REPLACE` | remplace l'ensemble des valeurs |
| absent | drapeau par défaut du contexte appelant | `ADD` pour Create, `REPLACE` pour Put |

La réponse `PutResponse` a un corps **vide** (`modify.py:74-75`).

## Delete

`Delete` n'a pas de corps utile. La seule subtilité est la suppression
récursive : `Remove-AD* -Recursive` joint le contrôle
`LDAP_SERVER_TREE_DELETE_OID` (`1.2.840.113556.1.4.805`). Le handler ne parse
pas le bloc de contrôles, il **cherche l'OID dans le XML brut**
(`classes/handlers/delete.py:40-44`) et, s'il le trouve, passe `tree_delete:1`
à `samdb.delete`. C'est un raccourci volontairement grossier mais robuste ;
il n'a pas de faux positif réaliste, l'OID étant unique.

---

# IMDA : BaseObjectSearchRequest et ModifyRequest

IMDA (*Identity Management Directory Access*) est la surcouche définie par
[MS-WSTIM] et étendue par [MS-WSPELD] pour Active Directory. Elle ne remplace
pas WS-Transfer : elle **s'y superpose**. Le client émet la même action
`…/transfer/Get`, mais ajoute un en-tête `<da:IdentityManagementOperation>` et
un corps `<da:BaseObjectSearchRequest>`.

## BaseObjectSearchRequest

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
**retire le seul préfixe `addata:`** (`classes/parsing/context.py:74-83`) ; le
préfixe `ad:` reste attaché au nom. `AttributeRenderer._normalize_request`
(`xml_renderer.py:61-73`) sait pourtant retirer les deux, mais n'est jamais
sollicité : le paramètre `requested` de `render_attributes` n'est passé par
**aucun** des quatre appelants (`get.py:142`, `schema.py:70`,
`object_projector.py:23` et `:31`). C'est du code mort. Le filtrage effectif a
lieu en amont, dans `GetHandler._prepare_attributes` (`get.py:67-77`), par
comparaison en minuscules et sans dépréfixage : un
`<da:AttributeType>ad:distinguishedName</da:AttributeType>` ne correspond donc
à aucune clé de l'objet LDB et disparaît du flux. D'où la nécessité, pour
`imda_projection`, d'émettre le DN synthétique inconditionnellement.

Le serveur Microsoft, lui, impose une limite dure de **100 `AttributeType` par
requête** : le test est à le service ADWS Microsoft et la faute
`EncodingLimit` (variante `EncodingLimitExceededDetailType.AttributeTypes`) est
levée à la ligne `312`. Cette limite n'est **pas** implémentée dans ce projet.

Immédiatement après, il **exige** un `Dialect` dès que des `AttributeTypes`
sont présents (`ArgumentException(MissingDialect)`,
le service ADWS Microsoft) puis le valide via
`DialectParser.IsDialectSupported` (`:318`). La table des dialectes admis est
codée dans `DialectParser.GetSupportedDialects`,
avec deux dialectes explicitement rejetés par `DialectParser.Create`
 ; les URI proviennent de les constantes du service ADWS Microsoft.

| `OperationType` | Dialecte admis |
|---|---|
| `Create`, `Put`, `Get` | `…/Dialect/XPath-Level-1` |
| `EnumerateSelection`, `EnumerateSort` | `…/Dialect/XPath-Level-1` |
| `EnumerateFilter` | `…/Dialect/LdapQuery` |
| toutes | `…/Dialect/QName` et `…/Dialect/XpathQuery` refusés |

**Ce projet ignore totalement l'attribut `Dialect`** — aucune occurrence dans
le code applicatif (seule l'URI `ADLQ` est déclarée, `src/soap/namespaces.py:11`,
et elle sert de préfixe de recherche XML, pas de valeur à valider). Un client
envoyant un dialecte absent, vide ou non supporté obtiendrait un traitement au
lieu d'une faute `FragmentDialectNotSupported` ; la constante existe pourtant
(`src/faults/fault_codes.py:8`) mais n'est jamais levée.

## AddRequest et ModifyRequest

Les mutations IMDA emploient deux structures voisines mais **non
interchangeables**, ce que reflète `BodyParser` (`classes/parsing/body_parser.py:22-32`) :

| Élément | Enfant répété | `default_op` transmis | Opération finale si `Operation` absent |
|---|---|---|---|
| `<da:AddRequest>` | `<da:AttributeTypeAndValue>` | `"add"` | `add` |
| `<da:ModifyRequest>` | `<da:Change>` | `None` | `replace` |

`AttributeParser.parse_changes` (`classes/parsing/attribute_parser.py:12-25`)
sélectionne le nom de balise selon le drapeau `use_change`, puis
`_read_entry` (`attribute_parser.py:27-39`) lit le triplet
`(name, operation, values)`. L'attribut XML `Operation` est relu sur **les
deux** formes — `op = (node.get("Operation") or default_op or "replace").lower`,
`attribute_parser.py:37` — de sorte qu'un `AttributeTypeAndValue` portant
explicitement `Operation="delete"` serait honoré ; aucun client observé
n'exploite cette latitude. Le nom d'attribut est nettoyé de ses préfixes
`addata:` **et** `ad:` par `_strip_prefix` (`attribute_parser.py:61-67`), à la
différence du chemin de lecture décrit plus haut.

La lecture des valeurs (`attribute_parser.py:41-59`) est le point de contact
avec le typage XSD en **entrée** : un enfant portant
`xsi:type="…base64Binary"` est décodé via `b64decode`, tout le reste est
conservé en texte. Un repli existe pour les corps qui placent la valeur
directement dans `<da:AttributeValue>` sans enfant `<ad:value>`.

Cette asymétrie est importante : en sortie, le codage est piloté par la
**syntaxe LDAP** de l'attribut ; en entrée, il est piloté par le `xsi:type`
annoncé par le client. Le serveur Microsoft procède de la même façon dans
le désérialiseur de valeurs du client :

| Contrôle | Ligne C# | Échec |
|---|---|---|
| Le préfixe doit résoudre vers l'espace XSD | `144-148` | `UnknownAttributeType` |
| Nom local `base64Binary` → `Convert.FromBase64String` | `151-163` | `InvalidBase64Binary` |
| Nom local `string` → valeur texte brute | `165-173` | — |
| Tout autre nom local | `167-171` | `UnknownAttributeType` |

Autrement dit, **aucun `xsi:type` autre que `xsd:string` et `xsd:base64Binary`
n'est accepté en écriture**. Le dépôt, lui, est laxiste :
`AttributeParser._read_values` (`attribute_parser.py:41-59`) ne teste que le
suffixe `base64Binary` et traite tout le reste comme du texte — un
`xsi:type="xsd:int"` passerait silencieusement là où Microsoft faute.

## Le pendant en réponse : BaseObjectSearchResponse

La réponse IMDA n'est plus un objet mais une **projection**, encapsulée dans
des éléments `<da:PartialAttribute>`. La spécification [MS-WSTIM] décrit deux
formes selon que la requête a listé ou non des types d'attributs. Ce n'est pas
une liberté d'implémentation : le désérialiseur du client applique un schéma
strict.

> **Limite de vérification.** Les deux formes décrites ci-dessous reposent sur
> [MS-WSTIM] et sur le comportement observé du client, non sur une source
> normative exhaustive pour l'élément `PartialAttribute` lui-même.

---

# Le choix du rendu : WS-Transfer contre IMDA

C'est l'invariant le plus coûteux à violer de tout le protocole, et le
paragraphe le plus important de ce chapitre.

## Le discriminant exact

Dans ce dépôt, `RequestContext.is_imda` est calculé en un seul endroit,
`classes/parsing/context.py:66-69` :

```python
is_imda = (
    root.find('.//da:IdentityManagementOperation', namespaces=ns) is not None or
    root.find('.//da:BaseObjectSearchRequest', namespaces=ns) is not None
)
```

Soit, en clair : **la requête est IMDA si le message contient un en-tête
`<da:IdentityManagementOperation>` OU un corps `<da:BaseObjectSearchRequest>`**,
n'importe où dans le document. Elle est WS-Transfer sinon.

Le serveur Microsoft, lui, ne teste **que l'en-tête**, au moyen du prédicat
`MessageContainsIdentityManagementHeader(request)` défini en
le service ADWS Microsoft et appelé en tête de chaque opération :
ligne `84` pour `Create`, `274` pour `Get`, `504` pour `Put`. Le corps n'est lu
qu'après. La disjonction retenue ici est donc **plus permissive** : un message
qui porterait un `BaseObjectSearchRequest` sans en-tête IMDA serait traité en
IMDA par ce projet et en WS-Transfer par Microsoft. Aucun client réel n'émet
cette combinaison, mais l'écart doit être documenté.

Deuxième conséquence du `findall` non ancré : quand un `Create` ou un `Put`
porte l'en-tête IMDA, les `<da:AttributeType>` contenus dans son
`<da:AddRequest>` ou son `<da:ModifyRequest>` alimentent eux aussi
`context.requested_attributes` (`context.py:73-83`), qui n'est donc pas
strictement une liste de projection. Sans effet pratique : `CreateHandler` et
`ModifyHandler` relisent intégralement le corps via `BodyParser` et n'utilisent
jamais ce champ.

## Les deux sous-formes IMDA

Une fois `is_imda` vrai, un second test départage les deux rendus. Il porte sur
la présence d'au moins un `<da:AttributeType>`, exposé par
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

**Forme a — au moins un `AttributeType` demandé.** Un
`<da:PartialAttribute>` par attribut, sans wrapper de classe d'objet, plus un
dernier `PartialAttribute` portant le `distinguishedName` synthétique
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

**Forme b — aucun `AttributeType`.** L'objet entier, dans sa forme WS-Transfer
exacte, à l'intérieur d'**un seul** `<da:PartialAttribute>`
(`classes/handlers/get.py:102-108`). La documentation [MS-WSTIM] le formule
ainsi : lorsque la requête ne spécifie aucun type d'attribut, le serveur
retourne la représentation XML de l'objet d'identité entier comme contenu d'un
unique élément `PartialAttribute`.

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
> `wrap_partial=context.is_imda` (`classes/handlers/get.py:142-151`), donc un
> `PartialAttribute` par attribut **même sans `AttributeType` demandé**, et
> sans `distinguishedName` synthétique (la RootDSE n'a pas de DN). C'est un
> écart local, validé empiriquement par le test `Get-ADRootDSE` du dépôt.

## Le symptôme Windows exact quand on se trompe

Répondre en forme WS-Transfer à une requête IMDA produit un document dont la
racine du corps est `<addata:{classe}>` alors que le désérialiseur attend
`<da:BaseObjectSearchResponse>`. Le parseur .NET applique le schéma en mode
strict et s'arrête sur le premier élément inattendu — presque toujours le
`<ad:distinguishedName>` final, puisqu'il est le dernier enfant du wrapper.
Message observé côté PowerShell francophone
(`documentation/06-depannage.md:106`) :

```text
Élément de fin 'subSchema' attendu, trouvé 'ad:distinguishedName'
```

Le nom de classe varie selon la cmdlet (`user`, `group`, `subSchema`, `top`…).
Si l'exception survient plus tôt, ou si le handler serveur lève avant d'écrire
le corps, le symptôme dégénère en :

```text
Get-ADUser : Le site distant a fermé le flux de transport.
```

Dans les deux cas, **aucune faute SOAP n'est visible côté client** : c'est le
parseur XML qui rompt, pas la couche applicative. Le seul diagnostic fiable est
la lecture du journal serveur.

## Pourquoi `distinguishedName` est toujours émis, en `ad:`, sans `LdapSyntax`

Trois raisons cumulatives, toutes vérifiables :

- **1. Contrainte de validation côté serveur.** Le service Microsoft refuse de
 sérialiser un objet dont l'un des quatre éléments d'identité est absent :
 identité d'objet, RDN, classe d'objet et nom distinctif. Ce contrôle est
 appliqué avant toute écriture, ce qui établit sans ambiguïté que ces quatre
 éléments font partie du contrat de l'objet ADWS.
- **2. Clé d'identité pour PowerShell.** Le module `ActiveDirectory` indexe les
 objets par leur DN. En forme a, aucun autre élément ne le porte : la
 projection n'a ni wrapper de classe, ni `objectReferenceProperty`, ni RDN.
 C'est pourquoi `imda_projection` ajoute inconditionnellement le
 `PartialAttribute` du DN (`object_projector.py:34-38`), **même si le client
 ne l'a pas demandé** — et c'est d'autant plus nécessaire qu'un
 `ad:distinguishedName` explicitement demandé serait, lui, filtré au passage
 (voir le dépréfixage manquant, plus haut).
- **3. Espace `ad:` et absence de `LdapSyntax`.** Le `distinguishedName` est
 écrit dans l'espace de noms `ad`, suivi directement de sa valeur :
 l'attribut `LdapSyntax` n'apparaît que dans la boucle des
 attributs `addata:`. Un `LdapSyntax` sur un élément `ad:` — ou pire, un
 `<addata:distinguishedName>` — sort du schéma attendu. Le dépôt garantit
 structurellement ce comportement en passant par `_synthetic`
 (`object_projector.py:48-53`), qui ne sait pas écrire d'attribut XML.

Symétriquement, un `LdapSyntax` **manquant** sur un élément `addata:`, ou
portant un OID au lieu d'un nom de membre d'énumération, fait échouer le
la conversion en énumération côté client et la réponse est rejetée en bloc.

---

# Sérialisation des valeurs par syntaxe LDAP

## Deux décisions indépendantes

Pour chaque attribut, le serveur prend deux décisions **séparées** :

- l'attribut XML `LdapSyntax`, qui porte le nom d'un membre de l'énumération
 `DirectorySyntaxType` — c'est la **syntaxe sémantique** ;
- l'attribut `xsi:type` de chaque `<ad:value>`, qui décrit uniquement la
 **représentation du transport**.

La preuve que ce sont deux axes indépendants tient dans une contrainte forte du
client : le désérialiseur de valeurs du client n'accepte
que deux jetons, `xsd:string` et `xsd:base64Binary`, et lève
`UnknownAttributeType` sur tout autre. Un entier, un booléen ou une date
voyagent donc en `xsd:string` ; seul du binaire voyage en base64. Le dépôt
encode cette règle explicitement dans `XSI_TYPE_BY_OID`
(`src/serialization/syntax_constants.py:76-87`).

## L'énumération `DirectorySyntaxType` complète

Telle que définie par le service Microsoft (23 membres,
dans l'ordre de déclaration).

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

Dix membres sur vingt-trois sont produits. Les treize autres n'apparaissent pas
dans `SYNTAX_NAME_BY_OID` ni dans `NAME_OVERRIDES`
(`src/serialization/syntax_constants.py:104-132`) : un attribut de syntaxe
`DNBinary` ou `ReplicaLink` sortira étiqueté `UnicodeString` par défaut.

## Table de correspondance exhaustive

Les identifiants de la colonne « OID interne » sont ceux définis dans
`src/serialization/syntax_constants.py:3-12`. Attention : ce sont des **clés de
répartition internes**, pas nécessairement les OID de syntaxe LDAP canoniques.
En particulier `SYNTAX_DIRECTORY_STRING` vaut `2.5.4.3`, qui est en réalité
l'OID du type d'attribut `cn` et non celui de *Directory String*
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

Deux constantes ne sont **jamais** produites par `syntax_for` car aucun attribut
n'y est semé : `SYNTAX_SID` et `SYNTAX_OID_STRING`. Les attributs concernés
obtiennent leur nom de syntaxe uniquement par la table de surcharges
`NAME_OVERRIDES`, tandis que leur **encodage de valeur** suit le bucket dans
lequel ils sont réellement placés. `objectSid` est ainsi dans
`BINARY_ATTRIBUTES` (encodage base64, correct) mais étiqueté `SidString` par
surcharge (correct aussi). Le résultat sur le fil est juste ; le chemin est
indirect.

Signalons également que `SYNTAX_GUID` et `SYNTAX_OCTET_STRING` partagent la
**même valeur littérale** `1.3.6.1.4.1.1466.115.121.1.40`
(`syntax_constants.py:4,12`) : ce sont deux noms du même bucket.

## Table des surcharges `NAME_OVERRIDES`

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

## L'ordre d'ensemencement compte

`SyntaxRegistry.__init__` (`classes/serialization/syntaxes.py:29-34`) sème les
buckets dans cet ordre : entiers, grands entiers, binaires, temps généralisés,
booléens, DN. Le dictionnaire est indexé en minuscules et **le dernier semé
gagne**. Deux attributs figurent dans deux listes :

- `msds-keyversionnumber` apparaît dans `LARGE_INTEGER_ATTRIBUTES`
 (`syntax_constants.py:54`) **et** dans `DN_ATTRIBUTES` (`:44`). `DN_ATTRIBUTES`
 étant semé en dernier, l'attribut sort étiqueté `DSDNString` alors que le
 schéma AD en fait un entier. Écart non corrigé, sans symptôme observé.
- `objectClassCategory` figure dans `BOOLEAN_ATTRIBUTES`
 (`syntax_constants.py:36`) alors que le schéma AD en fait une énumération
 entière ; il sort donc en `TRUE`/`FALSE`. Cet attribut n'est retourné que par
 le handler de schéma.

## Le codec de valeurs

`ValueCodec.encode_to_xsd` (`classes/serialization/value_codec.py:32-47`)
enchaîne :

- **1.** Déballage d'un `ldb.MessageElement` en `bytes` (première valeur) —
 garde-fou contre le `__str__` qui retourne `None` documenté en
 `documentation/06-depannage.md` §4.
- **2.** Valeur `None` → `(xsd:string, "")`.
- **3.** Répartition par OID : booléen, temps généralisé, entier/grand entier,
 binaire, sinon chaîne.

| Chemin | Fonction | Sortie |
|---|---|---|
| Booléen | `encode_boolean`, `src/serialization/value_special.py:8-11` | `TRUE` ou `FALSE`, jamais `true`/`1` |
| Temps généralisé | `encode_generalized_time`, `value_special.py:15-17` | chaîne native `YYYYMMDDHHMMSS.0Z` inchangée |
| Entier | `_encode_integer`, `value_codec.py:50-56` | décimal ASCII ; `0` si les octets ne décodent pas |
| Binaire | `_encode_binary`, `value_codec.py:59-62` | `base64` du binaire brut |
| Chaîne | `_encode_string`, `value_codec.py:65-74` | UTF-8 échappé, **repli base64** |

Deux détails ne sont pas anodins. `encode_boolean` (`value_special.py:10`)
admet les trois jetons `TRUE`, `1` et `YES` en entrée et normalise toujours la
sortie sur `TRUE`/`FALSE`. `_encode_binary` (`value_codec.py:62`) a un repli non
évident : une valeur du bucket binaire qui n'est pas de type `bytes` repart en
`xsd:string`, alors que le `LdapSyntax` annoncera `OctetString` ou `SidString`
— incohérence théorique, jamais observée, LDB rendant toujours des `bytes`.

Le repli base64 du chemin chaîne mérite une explication : il se déclenche sur
des octets non décodables en UTF-8, ou sur un texte contenant un caractère de
contrôle interdit par XML 1.0. Le motif `_CTRL` (`value_codec.py:21`) couvre
`\x00-\x08`, `\x0b`, `\x0c` et `\x0e-\x1f` — il préserve donc délibérément
tabulation, `LF` et `CR`. Sans ce garde-fou, un attribut binaire non déclaré
dans `BINARY_ATTRIBUTES` produirait un XML invalide, rejeté par le client.

## Attributs spéciaux et constructés

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

Les **attributs constructés** (`classes/serialization/constructed_attrs.py:3-21`)
posent un problème propre : LDB ne les calcule que s'ils sont **nommés
explicitement** dans la liste `attrs` d'une recherche ; le joker `*` ne les
couvre pas. `ConstructedAttrs.expand` (`constructed_attrs.py:34-43`) résout cela
en ajoutant les dix-sept noms à toute liste contenant `*`, et en renvoyant
`["*"] + CONSTRUCTED_ATTRIBUTES` quand la liste demandée est vide. La fonction
est appelée dans `classes/handlers/get.py:226` et
`classes/handlers/enumerate.py:27-28`.

Liste complète : `tokenGroups`, `tokenGroupsGlobalAndUniversal`,
`tokenGroupsNoGCAcceptable`, `canonicalName`, `primaryGroupToken`,
`msDS-PrincipalName`, `msDS-User-Account-Control-Computed`,
`msDS-UserPasswordExpiryTimeComputed`, `structuralObjectClass`,
`subSchemaSubentry`, `allowedAttributes`, `allowedAttributesEffective`,
`allowedChildClasses`, `allowedChildClassesEffective`, `createTimeStamp`,
`modifyTimeStamp`, `parentGUID`.

## Le rendu des éléments d'action personnalisée

Les réponses des actions `ca:` n'emploient **pas** le rendu `addata:`/`ad:value`.
Elles emploient la sérialisation par contrat de données de WCF, reproduite par
`classes/serialization/ca_elements.py` : éléments à texte simple
(`CaElement.text`, `ca_elements.py:14-17`), valeur nulle explicite
`xsi:nil="true"`, et tableaux sérialisés avec l'espace de noms des tableaux
`.NET` `http://schemas.microsoft.com/2003/10/Serialization/Arrays`
(`ca_elements.py:6,19-26`), chaque item étant un `<sera:string>`. Un tableau
`null` et un tableau vide sont deux choses distinctes sur le fil.

## La découverte dynamique des syntaxes n'est pas branchée

Deux mécanismes de découverte existent dans l'arbre mais ne participent pas au
rendu d'un `Get` ou d'un `Pull` :

- `SyntaxCache` (`classes/serialization/syntax_cache.py`) lit
 `(objectClass=attributeSchema)` et enregistre `lDAPDisplayName →
 attributeSyntax`. Il n'est instancié que par
 `ServiceContext.syntax_cache_for` (`classes/server/service_context.py:28-35`),
 fonction **qu'aucun handler n'appelle**. Vérifié par recherche sur l'ensemble
 du dépôt.
- `SchemaHandler._register_syntax_for` (`classes/handlers/schema.py:57-63`)
 enregistre `lDAPDisplayName → attributeID`, c'est-à-dire l'OID **du type
 d'attribut**, pas celui de sa syntaxe — le contraire de ce que fait
 `SyntaxCache._register_one` (`syntax_cache.py:48-55`), qui lit bien
 `attributeSyntax`. Comme chaque handler instancie son propre `SyntaxRegistry`
 (`classes/handlers/base.py:22`), cet enregistrement reste confiné au
 `SchemaHandler` et ne contamine pas les réponses `Get`. À l'intérieur du
 `SchemaHandler` lui-même, en revanche, il fait sortir chaque attribut de
 schéma étiqueté selon un OID qui n'appartient à aucun bucket connu, donc en
 `UnicodeString` par défaut.

Conséquence pratique : les syntaxes émises proviennent **exclusivement** des
tables statiques de `syntax_constants.py`. Un attribut d'extension de schéma
inconnu de ces tables sortira en `UnicodeString`/`xsd:string`, ou en base64 par
le repli de `_encode_string` si sa valeur n'est pas du texte propre.

---

# WS-Enumeration : Enumerate, Pull, Renew, GetStatus, Release

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

## Enumerate

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
`wsen:Enumerate` puis cherche en profondeur `adlq:BaseObject`, `adlq:Filter`,
`adlq:Scope` et tous les `ad:SelectionProperty`, en retirant les préfixes `ad:`
et `addata:` de chaque propriété de sélection. Le filtre subit ensuite un
dé-échappement XML explicite (`context.py:181-190`) : `&amp ;` redevient `&`,
faute de quoi un filtre `(&(a=1)(b=2))` arriverait à LDB sous la forme
`(&amp ;(a=1)(b=2))`.

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
défaut », mais LDB refuse une recherche sans base et lève
`(32, 'empty base DN at.../partition.c:821')`
(`documentation/06-depannage.md` §5).

La correspondance de portée (`enumerate.py:35-40`) :

| `adlq:Scope` | Constante LDB |
|---|---|
| `Base` | `ldb.SCOPE_BASE` |
| `OneLevel` | `ldb.SCOPE_ONELEVEL` |
| `Subtree` | `ldb.SCOPE_SUBTREE` |
| toute autre valeur | `ldb.SCOPE_SUBTREE` |

`_with_object_class` (`enumerate.py:100-104`) ajoute `objectClass` à la liste
d'attributs si elle n'y figure pas déjà : sans lui, `PullHandler` ne pourrait
pas déterminer le nom du wrapper `<addata:{classe}>` et retomberait sur `top`
pour chaque objet.

**Différence structurante avec le serveur Microsoft.** Ce dépôt exécute
l'intégralité du `samdb.search` **au moment de l'`Enumerate`** et matérialise
la liste complète en mémoire (`enumerate.py:47-79`). Le serveur Microsoft, lui,
ne fait que *préparer* la requête — `ClassManager.DirectoryAction.PrepareQuery`,
le service ADWS Microsoft — et récupère les pages paresseusement à
chaque `Pull` via `NextQueryPage`, la fin
de séquence étant signalée par `Query.NoMoreResults` (`:1154`). L'approche du
dépôt est plus simple mais consomme la mémoire d'un résultat complet ; un
garde-fou tronque à `MAX_RESULTS_PER_CONTEXT` = 50 000
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
secondes en dur, à deux endroits qu'il faut garder cohérents — l'argument
`ttl_seconds=3600` passé au cache (`enumerate.py:67`) et le `timedelta(hours=1)`
qui compose la chaîne renvoyée au client (`enumerate.py:81`). Le serveur
Microsoft honore la valeur demandée, la compare à `MaxEnumContextExpiration` et
lève `FaultBuilder.GenerateInvalidExpirationTimeFault`
 si elle dépasse ; le même contrôle est
rejoué sur `Renew` (`:1322`, `:1325`).

## Stockage du contexte et contrainte de « stickiness »

Le contexte est un `dataclass` (`classes/enumeration/enumeration_context.py`) :
identifiant, dates de création et d'expiration, base, filtre, liste
d'attributs, **résultats matérialisés** et un curseur `result_index`. Le cache
est un dictionnaire en mémoire de processus
(`classes/enumeration/enumeration_registry.py`), obtenu par un singleton paresseux
(`src/enumeration/enumeration.py:6-13`).

C'est le point de fragilité architecturale du service. Le serveur est un
`ForkingTCPServer` : **chaque connexion TCP est un processus distinct**, et le
singleton `_INSTANCE` n'est donc partagé par aucun autre fork. Un `Pull` qui
arriverait sur une autre connexion que son `Enumerate` recevrait la faute
`Invalid or expired enumeration context`.

Ce qui sauve le montage, c'est que le client Windows **réutilise la même
connexion `net.tcp`** pour toute la séquence `Enumerate`/`Pull`/`Release` : la
stickiness est une propriété du client, pas une garantie du serveur. Le serveur
Microsoft, lui, associe explicitement chaque contexte à une session et vérifie
la correspondance à l'entrée des quatre opérations concernées, par
`ClassManager.EnumerationRegistry.IsValidEnumContextForSession` :

| Opération | Appel | Cas `SessionMismatch` |
|---|---|---|
| `Pull` | Service ADWS Microsoft | `:1084` |
| `Renew` | `:1299` | `:1301` |
| `GetStatus` | `:1421` | `:1423` |
| `Release` | `:1521` | journalisé en `:1522` |

Ce projet ne fait aucune vérification de session — `session_id` est stocké (le
`message_id` de l'`Enumerate`, `enumerate.py:66`, champ déclaré en
`enumeration_context.py:16`) mais jamais relu ; aucune occurrence en lecture
n'existe dans le dépôt.

Limites du cache, et comparaison avec les valeurs par défaut du service
Microsoft lues dans le tableau `SettingDefault` de
la configuration du service ADWS Microsoft (les bornes minimales associées figurent en
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
service Microsoft : si `MaxEnumCtxsPerSession` dépasse `MaxEnumCtxsTotal`, le
premier est ramené au second et l'événement est journalisé
. Le dépôt n'a pas d'équivalent, faute de
notion de session.

## Pull

```xml
<s:Body>
  <wsen:Pull>
    <wsen:EnumerationContext>4b2f...-a71c</wsen:EnumerationContext>
    <wsen:MaxElements>256</wsen:MaxElements>
  </wsen:Pull>
</s:Body>
```

`classes/parsing/context.py:129-142` extrait `EnumerationContext` et convertit
`MaxElements` en entier, avec repli silencieux sur `None` si la conversion
échoue (`context.py:141-142`). `PullHandler` (`classes/handlers/pull.py:20`)
applique alors un défaut de **100**. Rappelons que le serveur Microsoft
applique un défaut de **1** (branche `else { num = 1u ; }`,
le service ADWS Microsoft) : un client qui omettrait
`MaxElements` obtiendrait donc des lots cent fois plus gros ici. Aucune cmdlet
observée n'omet ce champ — `-ResultPageSize` le pilote directement. Là où le
dépôt avale silencieusement une valeur non numérique, Microsoft lève une
`ArgumentException(UnrecognizedMaxElements)` sur débordement (`:1141-1144`).

`MaxCharacters` et `MaxTime` sont **totalement ignorés** par ce projet : ils ne
sont ni extraits ni contrôlés. Le serveur Microsoft, lui, lève
systématiquement une faute sur `MaxCharacters`
(`GenerateMaxCharsNotSupportedFault`, le service ADWS Microsoft)
et borne `MaxTime` par `MaxPullTimeout`.

Le découpage est un simple curseur
(`EnumerationContext.get_next_batch`, `enumeration_context.py:26-33`) et la fin
de séquence est la comparaison `result_index >= len(cached_results)`
(`enumeration_context.py:22-24`).

### Forme exacte des items

Les items d'un `PullResponse` emploient **exactement** la forme WS-Transfer :
`PullHandler._render_object_xml` (`classes/handlers/pull.py:49-56`) appelle
`serializer.whole_object`, le même point d'entrée que le `Get` WS-Transfer.
Aucun `PartialAttribute`, aucun `BaseObjectSearchResponse`.

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
- lot vide et fin de séquence sont deux choses distinctes : un lot vide s'écrit
 `<wsen:Items/>` (`pull.py:83-84`) ;
- la continuation est **exclusive** : soit `<wsen:EndOfSequence/>`, soit
 `<wsen:EnumerationContext>`, jamais les deux (`pull.py:85-91`). Le serveur
 Microsoft produit strictement la même alternative — branche vraie en
 le service ADWS Microsoft, branche fausse en `:1176-1182` — et
 positionne ensuite `message.Headers.RelatesTo = request.Headers.MessageId`
 (`:1184`), l'équivalent du `<a:RelatesTo>` que le dépôt écrit en
 `pull.py:106`.

## Renew, GetStatus, Release

| Message | Handler | Corps de réponse | Faute si contexte inconnu |
|---|---|---|---|
| `Renew` | `classes/handlers/renew.py` | `Expires` + `EnumerationContext` | `s:Sender`, texte `Invalid or expired…` |
| `GetStatus` | `classes/handlers/get_status.py` | `Expires` seul | idem |
| `Release` | `classes/handlers/release.py` | `<s:Body />` vide | `ADWSException` → faute générique |

`Renew` repousse l'expiration de 3600 s à partir de l'instant courant
(`renew.py:19-21`) sans lire la durée demandée par le client. `GetStatus`
renvoie l'expiration réelle stockée (`get_status.py:24`). Les deux emploient
`FaultBuilder.invalid_enumeration_context`
(`classes/faults/faults.py:43-48`). `Release` supprime l'entrée du dictionnaire
et répond même si le contexte n'existait plus
(`release.py:27-34`, `enumeration_registry.py:51-56`).

## Le filtre LDAP : ce qui est réellement parsé

`FilterParser` (`classes/parsing/filter_parser.py`) n'est **pas** un parseur
sémantique RFC 4515. C'est un normalisateur syntaxique de 59 lignes dont
l'unique fonction est de garantir un équilibrage correct des parenthèses :

- `parse` (`filter_parser.py:10-18`) rejette un filtre dont il reste des
 caractères après l'expression racine, et retourne `(objectClass=*)` sur
 entrée vide ;
- `_read_compound` (`:35-44`) traite `&`, `|` et `!` et **reparenthèse les
 opérandes nus** — la tolérance qu'ADWS observe côté Windows ;
- `_read_simple` (`:47-59`) avale les caractères jusqu'à la parenthèse
 fermante en respectant les échappements `\XX` de RFC 4515.

Le contenu de l'assertion n'est jamais interprété : `attribut`, `:règle:` et
`valeur` traversent le parseur **inchangés**. C'est précisément ce qui rend les
règles de correspondance étendues d'Active Directory utilisables sans une ligne
de code dédiée : elles sont transmises telles quelles à LDB, qui les implémente
nativement.

| OID | Nom | Sémantique | Statut dans ce projet |
|---|---|---|---|
| `1.2.840.113556.1.4.803` | `LDAP_MATCHING_RULE_BIT_AND` | tous les bits du masque | transmis à LDB, testé |
| `1.2.840.113556.1.4.804` | `LDAP_MATCHING_RULE_BIT_OR` | au moins un bit | transmis à LDB, non testé |
| `1.2.840.113556.1.4.1941` | `LDAP_MATCHING_RULE_IN_CHAIN` | appartenance transitive | transmis à LDB, non testé |

La suite de tests du dépôt couvre explicitement la règle `803` combinée à un
`OR` et à une négation (`tools/test/Test-ADWS-Sovereign.ps1:115-116`, filtre
`(|(samAccountName=admin*)(!(userAccountControl:1.2.840.113556.1.4.803:=2)))`),
et le cas figure au statut `Pass` sous le nom
`Get-ADUser LDAPFilter (OR + bitwise NOT)` dans le dernier relevé
(`tools/test/adws-test-results/adws-test-20260608-121931.json`). Les règles
`804` et `1941` ne sont couvertes par aucun test du dépôt ; leur bon
fonctionnement dépend uniquement de LDB. La documentation existante affirme le
support de `804` (`documentation/01-architecture.md:159`) : c'est vrai au sens
où le filtre est transmis intact, mais cette affirmation n'est adossée à aucune
mesure.

En revanche, si le filtre est **syntaxiquement invalide**, `EnumerateHandler`
retombe silencieusement sur le texte brut (`enumerate.py:92-98`) et laisse LDB
échouer, alors que `SearchHandler` (`classes/handlers/search.py:18-24`) émet une
faute typée `CannotProcessFilter`. Les deux chemins ne se comportent donc pas
de la même manière face à un filtre mal formé.

## Les contrôles LDAP v3 [MS-WSPELD]

Le client peut joindre un bloc `<ad:controls>` contenant des
`<ad:control type="OID" criticality="true|false">` avec un `<ad:controlValue>`
en base64. `ControlsParser` (`classes/parsing/controls_parser.py`) les traduit
en chaînes de contrôle LDB de la forme `nom:criticité[:valeur]`
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
pointent tous deux vers `show_recycled`. Six entrées n'apparaissent pas dans le
tableau ci-dessus : `crossdom_move_target` (`…1.4.521`),
`show_deactivated_link` (`…1.4.2026`), `managedBy` (`…1.4.2065`),
`search_notification` (`…1.4.1948`), `verify_name` (`…1.4.1338`) et le doublon
`show_recycled`.

Trois faiblesses de ce chemin méritent d'être connues :

- un OID absent de la table est **silencieusement supprimé** (`_translate`
 retourne `None`, `controls_parser.py:63-64`), y compris s'il est marqué
 critique — ce qui contrevient au principe LDAP selon lequel un contrôle
 critique non supporté doit faire échouer l'opération ;
- la valeur du contrôle est décodée en base64 puis **amputée de tous ses
 deux-points** (`decoded.replace(":", "")`, `controls_parser.py:71`), parce que
 le séparateur de la chaîne LDB est justement `:`. Un `controlValue` binaire
 arbitraire — cas normal pour `paged_results` ou `server_sort`, dont la valeur
 est du BER — en ressort mutilé, quand il n'est pas vidé par le
 `errors="ignore"` du décodage UTF-8 (`:70`) ;
- l'ensemble du parsing est enveloppé dans un `except Exception: return None`
 (`classes/parsing/context.py:171-178`) : une erreur de contrôle ne fera jamais
 échouer une requête, elle la fera passer sans contrôle du tout.

Enfin, la pagination `paged_results` est traduite mais **la pagination réelle
reste côté handler** : `EnumerateHandler` exécute une recherche complète unique
puis découpe dans `Pull`. Le contrôle est accepté, pas honoré au sens LDAP.

## WS-Eventing : statut réel

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
(`subscription_renew.py:20-21`, `subscription_status.py:19-20`) au lieu d'une
faute, ce qui donne au client l'illusion d'un abonnement toujours vivant.

Le verdict doit être énoncé sans détour : **la comptabilité des abonnements est
implémentée, la notification ne l'est pas**. `SubscriptionCache`
(`classes/enumeration/subscription_cache.py`) ne mémorise qu'un couple
`(uuid, datetime)` — aucun filtre, aucun point de terminaison de livraison,
aucune source d'événement branchée sur LDB. `NotifyHandler`
(`classes/handlers/notify.py:12-16`) retourne une liste d'événements vide
constante ; aucun message `Notify` sortant n'est jamais émis. Le cache plafonne
à `MAX_SUBSCRIPTIONS` = 256 avec éviction du plus ancien
(`subscription_cache.py:9,21-23`) et retient un `DEFAULT_TTL_SECONDS` de 3600
(`:10`). L'adresse du gestionnaire d'abonnement est en outre codée en dur sur
`net.tcp://localhost:9389/ActiveDirectoryWebServices/Windows/AccountManagement`
(`classes/handlers/subscribe.py:15-17`), donc inexploitable à distance. La durée
demandée est en revanche correctement décodée : `parse_expires`
(`src/enumeration/subscription_id.py:30-55`) interprète une durée ISO 8601
`PnYnMnDTnHnMnS` avec les approximations année = 365 jours et mois = 30 jours
(`subscription_id.py:14-15`), et retombe sur 3600 s en cas d'échec.

---

# Opérations spécifiques : mots de passe, appartenances, rôles FSMO, traduction de noms

Ces opérations n'ont pas d'équivalent WS-* : Microsoft les a définies comme des
actions SOAP propriétaires sous l'espace de noms `CustomActions`, réparties en
deux points de terminaison logiques, `AccountManagement` et
`TopologyManagement`. Elles sont routées par le **dernier segment** de l'URI
d'action (`classes/handlers/handler_registry.py:22-23`).

## Mots de passe

Deux actions distinctes, deux implémentations LDB distinctes.

**SetPassword** — réinitialisation administrative, déclenchée par
`Set-ADAccountPassword -Reset`. Corps :
`<ca:SetPasswordRequest>` contenant `<ca:AccountDN>` et `<ca:NewPassword>`
(`classes/handlers/set_password.py:31-37`). L'écriture
(`set_password.py:39-43`) est un `FLAG_MOD_REPLACE` sur `unicodePwd`.

**ChangePassword** — changement self-service avec ancien mot de passe. Corps :
`<ca:ChangePasswordRequest>` contenant `AccountDN`, `OldPassword`,
`NewPassword`. L'écriture (`classes/handlers/change_password.py:45-51`) est la
séquence canonique d'Active Directory : un `FLAG_MOD_DELETE` de l'ancienne
valeur suivi d'un `FLAG_MOD_ADD` de la nouvelle, **dans le même
`ldb.Message`**.

### L'encodage `unicodePwd`

Dans les trois points d'écriture — `set_password.py:40`,
`change_password.py:46-47` et `LdapAttrBuilder.encode_value`
(`classes/directory/ldap_attr_builder.py:15-16`) — la règle est identique et
non négociable :

```python
encoded = ('"' + new_password + '"').encode("utf-16-le")
```

Le mot de passe est **entouré de guillemets doubles ASCII**, puis encodé en
**UTF-16 little-endian**, **sans BOM**. C'est le format défini par [MS-ADTS]
pour l'attribut `unicodePwd`. Les guillemets font partie intégrante de la valeur
transmise ; ils ne sont pas un artefact de citation. Une valeur encodée en UTF-8,
en UTF-16 big-endian, avec BOM ou sans guillemets est rejetée par le module
`password_hash` de Samba avec une erreur de contrainte peu explicite.

### La limite connue sur le changement self-service

`ChangePassword` est la seule **opération de service** du dépôt qui échoue de
manière reproductible. Le relevé de test le plus récent
(`tools/test/adws-test-results/adws-test-20260608-121931.json`) totalise 28
cas, 26 `Pass` et 2 `Fail` ; le second échec, `50 parallel Get-ADUser -Filter *
(throttle 10)` (catégorie `Stress`), n'est pas un défaut du serveur mais une
erreur du script de test lui-même — « Le jeu de paramètres ne peut pas être
résolu à l'aide des paramètres nommés spécifiés », levée en 4 ms, donc avant
tout échange réseau. Pour le cas `Set-ADAccountPassword (Change with old)`, le
statut est `Fail` avec l'erreur exacte :

```text
(1, 'Failed to obtain remote address for the LDAP client while changing
the password')
```

La cause est structurelle et documentée en `documentation/01-architecture.md:155` :
le module `password_hash` de Samba exige, sur le chemin du changement avec
ancien mot de passe, l'adresse réseau du client (`remoteAddress`) afin
d'alimenter la politique de verrouillage et l'audit. Cette information n'est pas
fournissable depuis une connexion `SamDB` locale, car un `tsocket_address` ne se
construit pas depuis Python. Le **reset administrateur** (`-Reset`), lui, ne
passe pas par ce chemin et fonctionne — statut `Pass` dans le même relevé.

Les pistes de contournement identifiées, aucune n'étant implémentée : passer par
une connexion `ldapi://` authentifiée, ou déléguer l'identité GSSAPI du client
jusqu'à la couche LDAP.

## Appartenances de groupe

Trois actions de lecture, toutes sous `AccountManagement`, toutes rendues par
`PrincipalSerializer` (`classes/serialization/group_serializer.py`).

| Action | Handler | Stratégie de résolution |
|---|---|---|
| `GetADGroupMember` | `get_ad_group_member.py` | descente : lit `member` du groupe, récursive si demandé |
| `GetADPrincipalGroupMembership` | `get_ad_principal_group_membership.py` | remontée directe : `(&(objectClass=group)(member=DN))` |
| `GetADPrincipalAuthorizationGroup` | `get_ad_principal_authorization_group.py` | remontée transitive du même filtre |

**Descente.** `_walk` (`get_ad_group_member.py:44-60`) lit `member` en
`SCOPE_BASE` et, en mode récursif, se rappelle sur chaque valeur ; un ensemble
`seen` (`:41-42`) coupe les cycles. Chaque DN est ensuite hydraté par
`PrincipalLoader.load_many` (`classes/directory/principal_loader.py:28-34`), qui
exécute une recherche `SCOPE_BASE` **par membre** : coût linéaire, principale
limite de passage à l'échelle de cette action.

**Remontée.** Les deux autres actions n'emploient **pas** `memberOf` : elles
interrogent l'annuaire par le filtre inverse
`(&(objectClass=group)(member={dn}))` sur tout le naming context
(`get_ad_principal_group_membership.py:47-52`), la variante transitive
(`get_ad_principal_authorization_group.py:49-63`) répétant l'opération sur
chaque groupe trouvé. Ce choix évite de dépendre de la cohérence de l'attribut
lié `memberOf`, au prix d'une recherche sous-arbre par niveau d'imbrication.

**Ni `tokenGroups`, ni la règle `1.2.840.113556.1.4.1941` ne sont utilisés**
pour ces résolutions, alors que les deux fourniraient une transitivité calculée
par le serveur d'annuaire. `tokenGroups` reste néanmoins déclaré comme attribut
constructé et correctement sérialisé s'il est demandé dans un `Get`.

Le rendu (`group_serializer.py:5-18`) produit des `<ActiveDirectoryPrincipal>`
ou `<ActiveDirectoryGroup>` portant huit champs communs, plus `GroupScope` et
`GroupType` pour les groupes. Ces deux derniers sont dérivés du masque
`groupType` (`principal_loader.py:55-61`) :

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

- **1.** le handler n'est enregistré que sous la clé `Groups`
 (`src/handlers/handler_routing.py:57`). Le repli par suffixe de
 `HandlerRegistry.resolve` (`classes/handlers/handler_registry.py:22-23`)
 découpe l'URI sur le dernier `/` **sans passer en minuscules** — contrairement
 à la correspondance exacte de la ligne `19` — donc seul un dernier segment
 valant littéralement `Groups` fonctionne ;
- **2.** même atteint, `GroupHandler.handle` (`groups.py:19-25`) n'exécute la
 mutation que si la chaîne `add` ou `remove` figure dans l'action passée en
 minuscules ; à défaut, il **délègue à `GetADGroupMemberHandler`**, c'est-à-dire
 qu'il répond une liste de membres.

Les tests `Add-ADGroupMember` (catégorie `GroupModify`) et
`Remove-ADGroupMember + cleanup` (catégorie `Cleanup`) du dépôt sont pourtant
au statut `Pass` dans le dernier relevé. La lecture du code rend donc très
probable qu'ils empruntent en réalité le chemin **WS-Transfer Put** avec un
`<da:Change Operation="add">` sur `member`, que `ModifyHandler` traite
correctement. Cette hypothèse n'a pas pu être confirmée par une trace réseau au
moment de la rédaction, et le tableau final signale les deux voies.

## Rôles FSMO

`Move-ADDirectoryServerOperationMasterRole` émet l'action
`…/TopologyManagement/MoveADOperationMasterRole`. Le corps porte
`<ca:OperationMasterRole>` et `<ca:Seize>`
(`classes/handlers/move_operation_master_role.py:31-41`).

La correspondance rôle → objet porteur est une table de gabarits
(`src/directory/fsmo_roles.py:3-9`), le transfert consistant à réécrire
l'attribut `fSMORoleOwner` (`fsmo_roles.py:11`) de l'objet cible avec le DN des
`NTDS Settings` locaux.

| Rôle | Objet porteur de `fSMORoleOwner` |
|---|---|
| `PDCEmulator` | `{domain_dn}` |
| `RIDMaster` | `CN=RID Manager$,CN=System,{domain_dn}` |
| `InfrastructureMaster` | `CN=Infrastructure,{domain_dn}` |
| `SchemaMaster` | `{schema_dn}` |
| `DomainNamingMaster` | `CN=Partitions,{config_dn}` |

Un rôle absent de cette table provoque une `ValueError` traduite en faute
`MoveADOperationMasterRoleFault`. Le DN du nouveau propriétaire est découvert
par `(&(objectClass=nTDSDSA)(options=*))` dans le contexte de configuration
(`move_operation_master_role.py:53-61`).

> **Limite explicite.** Le drapeau `Seize` est extrait, journalisé, puis
> **délibérément ignoré** (`move_operation_master_role.py:22-23`, la ligne
> `_ = seize`). Transfert gracieux et saisie autoritaire produisent donc la
> même écriture ; le protocole de transfert propre à FSMO (`becomeDomainMaster`
> et consorts) n'est pas mis en œuvre. Aucun test du dépôt ne couvre cette
> action.

## Traduction de noms

`TranslateName` (`classes/handlers/translate_name.py`) implémente le service
rendu par `DsCrackNames` côté Windows. La requête porte une liste `<ca:Names>`,
un `<ca:FormatOffered>` et un `<ca:FormatDesired>`.

La résolution se fait en deux temps
(`classes/serialization/name_formats.py:22-34`) : `filter_for_offered`
(`src/serialization/name_filters.py:4-23`) construit le filtre LDAP à partir du
format d'entrée, puis un rendu (`src/serialization/name_renderers.py`) produit
le format de sortie.

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

Le nom NetBIOS nécessaire au format NT4 est lu dans `CN=Partitions` du contexte
de configuration via `(nCName={naming_context})`
(`name_renderers.py:38-51`). Le nom canonique est reconstruit par manipulation
de chaîne : les composants `DC=` forment le domaine par jointure sur `.`, les
autres composants sont inversés et joints par `/` (`name_renderers.py:21-28`).

Le statut est renvoyé sous forme de **code numérique**
(`translate_name.py:10`) : `0` pour `Found`, `2` pour `NotFound`, `4` pour
`NoMapping`, `2` par défaut. Ce sont les codes `DS_NAME_ERROR` d'Active
Directory.

## Topologie : Domain, DomainController, Forest, Version, OptionalFeature

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
cible selon le drapeau `<ca:Enable>` (`:57-63`). Un `FeatureId` inconnu lève un
`RuntimeError` traduit en `ChangeOptionalFeatureFault`. Aucun test du dépôt ne
couvre cette action.

`DomainSerializer` (`classes/serialization/domain_serializer.py:5-37`) projette
trente et un champs. Les conteneurs bien connus ne sont **pas lus dans
l'annuaire** : ils sont fabriqués par concaténation à partir du naming context
(`domain_serializer.py:57-68`), qu'ils existent ou non. Les rôles FSMO exposés
(`InfrastructureMaster`, `PDCEmulator`, `RIDMaster`) pointent tous vers la même
valeur `dns_host` — le DC local — sans consulter les `fSMORoleOwner` réels.

Même approche pour `GetADDomainController`
(`classes/handlers/get_ad_domain_controller.py:41-56`) : ports constants
(`389`, `636`), `IsGlobalCatalog` à `true` en dur, `IsReadOnly` à `false`,
`OperationMasterRole`, `Partitions` et les informations de système
d'exploitation à `nil`. Le site est déduit du DN des `NTDS Settings`, avec repli
sur `Default-First-Site-Name` (`get_ad_domain_controller.py:58-63`).
`GetADForest` (`classes/handlers/get_ad_forest.py:42-52`) n'expose qu'un domaine
et un catalogue global, tout le reste à `nil` — cohérent avec la limite
d'architecture annoncée : un seul domaine, aucune approbation.

## Traduction des erreurs en fautes SOAP

Toute exception doit ressortir en faute SOAP portant un `<a:RelatesTo>` égal au
`MessageID` de la requête. `ADWSDispatcher.dispatch`
(`classes/handlers/dispatcher.py:20-35`) capture `ADWSException` **et**
`Exception`, et `_fault` (`dispatcher.py:52-55`) récupère le `message_id` du
contexte s'il a pu être construit, chaîne vide sinon. Sans ce `RelatesTo`, le
client considère la réponse comme non sollicitée et l'ignore : la cmdlet reste
bloquée jusqu'au délai d'expiration (`documentation/06-depannage.md` §6).

Trois familles de fautes coexistent :

| Générateur | Fichier | `<s:Code><s:Value>` | Forme du `Detail` |
|---|---|---|---|
| `directory_error` | `classes/faults/faults.py:13-22` | `s:Receiver` | `<da:Fault>` + `ShortError`/`LongError` |
| `access_denied` | `faults.py:24-26` | `s:Sender` | aucun |
| `custom_action_fault` | `faults.py:28-41` | `s:Receiver` | `<{Nom}Fault>` à quatre champs |
| `invalid_enumeration_context` | `faults.py:43-48` | `s:Sender` | aucun |
| `TypedFaults.*` | `classes/faults/typed_faults.py` | `s:Sender` sauf `directory` | `Code` + `Message` |

Le `Detail` de `custom_action_fault` porte exactement quatre éléments dans
l'espace `CustomActions` (`faults.py:30-37`) : `<ArgumentError xsi:nil="true">`,
`<DirectoryError xsi:nil="true">`, `<Error>` et `<ShortError>`, les deux
derniers recevant le même texte. C'est aussi le seul générateur à positionner à
la fois un `<s:Subcode>` (`ca:{Nom}Fault`, `faults.py:40`) et une action de
faute spécifique — `http://schemas.microsoft.com/2008/1/ActiveDirectory/Data/fault`,
`src/soap/namespaces.py:13` — là où tous les autres retombent sur l'action
générique `http://www.w3.org/2005/08/addressing/soap/fault`
(`classes/soap/soap_envelope.py:18`). C'est ce que le module PowerShell attend
pour les actions personnalisées.

`TypedFaults` (`classes/faults/typed_faults.py:14-64`) offre cinq familles
prêtes à l'emploi, adossées aux constantes de `src/faults/fault_codes.py:6-24`
(`CannotProcessFilter`, `EncodingLimit`, `FragmentDialectNotSupported`,
`InvalidEnumerationContext`, `InvalidExpirationTime`, `TimedOut`…). **Aucun
handler ne les appelle** — recherche exhaustive : zéro site d'appel pour
`typed_faults.` comme pour `TypedFaults.`, alors que `BaseHandler` les expose
(`base.py:28`). C'est une réserve de conformité inutilisée, et l'essentiel des
écarts listés en fin de chapitre tient à cette non-levée.

---

# Correspondance cmdlets PowerShell -> échanges réseau

Le tableau suivant relie chaque cmdlet du module `ActiveDirectory` à la suite
d'actions SOAP qu'elle produit et au handler qui la sert. Les actions WS-* sont
abrégées : `WST` = `http://schemas.xmlsoap.org/ws/2004/09/transfer`,
`WSEN` = `http://schemas.xmlsoap.org/ws/2004/09/enumeration`,
`CA` = `http://schemas.microsoft.com/2008/1/ActiveDirectory/CustomActions`.

> **Portée de la vérification.** Les URI des actions `WST` et `WSEN` sont celles
> de la table de routage `ACTION_HANDLER_KEYS`
> (`src/handlers/handler_routing.py:35-51`), donc reconnues en **requête**.
> Celles des actions `CA` sont reconstruites à partir des constantes
> `REPLY_ACTION` de chaque handler, c'est-à-dire validées en **réponse** ; côté
> requête, seul leur dernier segment est effectivement utilisé pour le routage
> (`classes/handlers/handler_registry.py:22-23`). Les assemblies clientes qui
> construisent ces URI ne figurent pas dans le dump de référence disponible.

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

`*` : le message `Pull` est répété jusqu'à réception de `<wsen:EndOfSequence/>`.

Deux chemins secondaires complètent la carte :

- une action dont le dernier segment vaut `Groups` atteint `GroupHandler`
 (`classes/handlers/groups.py`), qui accepte un `<ca:GroupModificationRequest>`
 et répond `<ca:AddedMember>` ou `<ca:RemovedMember>` sous l'action
 `…/CustomActions/AccountManagement/{AddedMember|RemovedMember}Response`
 (`groups.py:36-38`) ;
- une action dont le dernier segment vaut `Search` atteint `SearchHandler`
 (`classes/handlers/search.py`), qui normalise le filtre puis délègue
 intégralement à `EnumerateHandler` — il ne produit donc pas de réponse
 propre : le client reçoit un `EnumerateResponse` ;
- une action dont le dernier segment vaut `Schema` atteint `SchemaHandler`, qui
 cherche `(|(objectClass=attributeSchema)(objectClass=classSchema))`
 (`schema.py:48-55`) en `SCOPE_ONELEVEL` sous le contexte de schéma — ou en
 `SCOPE_BASE` si un `objectReferenceProperty` est fourni — et répond un
 `<addata:SchemaResponse>` contenant un
 `<addata:schemaObject DistinguishedName="…">` par objet (`schema.py:65-76`),
 sous l'action
 `http://schemas.microsoft.com/2008/1/ActiveDirectory/SchemaResponse`. Cette
 forme est **propriétaire à ce dépôt** : ni [MS-ADDM] ni le code de référence
 de référence n'en décrivent l'équivalent. Les résultats sont mémorisés par
 `SchemaCache` sous la clé `{schema_dn}::{objectReference}` (`schema.py:24-29`).

## Synthèse des écarts connus

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
