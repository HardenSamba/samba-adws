# Modèle de sécurité : ce que le canal doit garantir

## Le contrat imposé par le client

Le client ADWS n'est pas négociable. C'est le module PowerShell `ActiveDirectory`
(ou ADAC, ou tout consommateur de `Microsoft.ActiveDirectory.Management`) qui
ouvre une liaison WCF `NetTcpBinding` vers `net.tcp://<dc>:9389/…`. La
configuration exacte de cette liaison est lisible dans la référence C# de référence
du service Microsoft : `CreateAdwsTransportBinding` positionne
trois propriétés qui déterminent tout le reste de ce chapitre.

| Propriété WCF | Valeur | Conséquence protocolaire |
|---|---|---|
| `Security.Mode` | `Transport` | La sécurité est au niveau flux, pas WS-Security |
| `Security.Transport.ProtectionLevel` | `EncryptAndSign` | Chaque message est chiffré **et** signé |
| `Security.Transport.ClientCredentialType` | `Windows` | SSPI / SPNEGO, donc Kerberos ou NTLM |

Ces trois valeurs caractérisent la liaison employée par les endpoints
`Windows/`. Une seconde liaison existe côté Microsoft pour les endpoints
`UserName/`, en `TransportWithMessageCredential` : elle porte les identifiants
dans le message et suppose qu'un certificat serveur ait été provisionné. Les
deux liaisons coexistent, et le préfixe d'adresse détermine laquelle
s'applique.
Le préfixe d'endpoint concerné ici est `Windows/`
(`WcfWindowsEndpointPrefix = "Windows/"`),
c'est-à-dire la branche `TcpClientCredentialType.Windows` — la seule que le
serveur souverain implémente. Ce préfixe apparaît d'ailleurs dans le code du
projet, dans l'adresse de gestionnaire d'abonnement rendue par
`classes/handlers/subscribe.py:16` :
`net.tcp://localhost:9389/ActiveDirectoryWebServices/Windows/AccountManagement`.

> Le second endpoint Microsoft, `UserName/…`, n'est pas implémenté par ce
> projet. Il n'existe donc **aucun** chemin d'authentification par mot de passe
> en clair vers ce serveur : c'est un choix de conception, pas un manque.

Nuance sur le mot « endpoint » : le serveur Python **ne lit ni ne valide jamais**
l'URL cible. Le `ViaRecord` qui la transporte est journalisé
(`classes/server/protocol.py:45-46`) puis jeté ; aucun routage par chemin
n'existe. Le choix `Windows/` contre `UserName/` est donc entièrement une
décision du client.

## Les quatre propriétés à garantir

Le canal doit fournir, avant qu'un seul octet de SOAP ne circule :

- **Authentification du client** — le serveur doit savoir *qui* parle, avec une
 preuve cryptographique émise par le KDC du domaine, pas un mot de passe.
- **Authentification mutuelle** — le client doit vérifier qu'il parle bien au DC
 et non à un intercepteur. C'est ce que demande `GSS_C_MUTUAL_FLAG`, et c'est
 pour cela que le service doit posséder la clé du SPN demandé.
- **Intégrité** — toute altération d'un message doit être détectée
 (`GSS_C_INTEG_FLAG`, checksum HMAC du token Wrap RFC 4121).
- **Confidentialité** — les attributs d'annuaire (`unicodePwd` en écriture,
 `nTSecurityDescriptor`, appartenances de groupe) ne doivent pas transiter en
 clair (`GSS_C_CONF_FLAG`, correspondant à `EncryptAndSign`).

## Ce que ce serveur garantit réellement

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
serveur **authentifie** le client de façon irréprochable, puis **n'utilise pas**
l'identité obtenue pour exécuter les opérations LDB. La section « Identité,
délégation et contrôle d'accès » détaille ce point, mesures à l'appui.

# Anatomie de l'upgrade de sécurité NMF

## Où se situe l'upgrade dans le préambule

[MS-NMF] définit un préambule composé de records typés (un octet de code, puis
des champs). Le client envoie sa séquence sans attendre de réponse. Les codes
implémentés dans `src/nettcp/nmf.py` sont les suivants.

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

La chaîne `application/negotiate` fait exactement 21 octets — d'où le
`UpgradeProtocolLength=21` littéral de `src/nettcp/stream/nmf.py:30`. Ce client
est celui du projet amont, pas le client Windows : il documente une séquence
valide, il ne prouve pas l'ordre exact retenu par WCF.

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
> `documentation/03-protocole.md` (lignes 34 à 40) est décalé d'un octet à partir
> de sa deuxième ligne : il annonce `0x00 0x01 0x00 0x01` pour `VersionRecord`
> (soit les trois octets de la version **plus** le code du record suivant),
> `0x02 0x02` pour `ModeRecord` (soit la valeur `DUPLEX` **plus** le code de
> `ViaRecord`), et `0x04 0x03` avec « BINARY_WITH_DICT (3) » pour
> `KnownEncodingRecord`. Le code fait autorité : le code de record est `0x03`
> (`nmf.py:322`) et la valeur d'encodage est `8` (`BINARY_DICT`, `nmf.py:184`,
> confirmée par `stream/nmf.py:24`). La paire correcte est donc `03 08`.

## La bascule côté serveur, ligne à ligne

`classes/server/protocol.py` traite l'`UpgradeRequestRecord` de façon
particulière : il **termine le préambule**. Le record est mémorisé plutôt que
consommé.

- **1.** `protocol.py:49-54` — sur `code == 0x09`, l'objet est stocké dans
 `self.pending_upgrade` et `handle_preamble` retourne `True`. Aucune réponse
 n'est émise à cet instant.
- **2.** `protocol.py:75-77` — `handle_security` récupère `pending_upgrade`
 au lieu de relire le socket.
- **3.** `protocol.py:84-86` — si le code n'est pas `0x09`, la connexion est
 abandonnée.
- **4.** `protocol.py:92` — `send_record(nmf.UpgradeResponseRecord)` écrit
 **un seul octet**, `0x0A` (`nmf.py:337`), directement sur le socket brut.
- **5.** `protocol.py:96` — `self.stream = GENSECStream(self.stream)` : le
 `SocketStream` est enveloppé. À partir de cette affectation, tout `read` /
 `write` du reste du serveur passe par la pile de sécurité.
- **6.** `protocol.py:97` — `self.stream.negotiate_server` exécute le
 handshake complet, de façon synchrone et bloquante.

> **Faille de durcissement.** Le contenu du champ `UpgradeProtocol` n'est
> **jamais comparé** à `application/negotiate` : `protocol.py:84` ne teste que
> le code de record. Un client demandant `application/ssl-tls` recevrait le même
> `UpgradeResponseRecord` puis échouerait au handshake. Point à traiter en
> phase 5 (durcissement).

## Le cadrage réellement implémenté : MS-NNS, et pas autre chose

On lit fréquemment que « ce serveur ne fait pas de NegotiateStream, juste des
tokens GSSAPI préfixés d'une longueur ». **C'est faux.**
`src/nettcp/stream/negotiate.py` est une implémentation littérale du .NET
NegotiateStream Protocol [MS-NNS], avec ses **deux** cadrages distincts.

### Cadrage A — le message Handshake (phase de négociation)

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

Elle correspond exactement à la structure « Handshake Message » de [MS-NNS] :

| Offset | Long. | Champ [MS-NNS] | Code du projet |
|---|---|---|---|
| 0 | 1 | `MessageId` | `Record.code_fmt = 'B'` (`nmf.py:220`) |
| 1 | 1 | `MajorVersion` (=0x01) | `('major', 'B')`, écrit `major=1` |
| 2 | 1 | `MinorVersion` (=0x00) | `('minor', 'B')`, écrit `minor=0` |
| 3 | 1 | `HighByteOfPayloadSize` | octet de poids fort de `>H` |
| 4 | 1 | `LowByteOfPayloadSize` | octet de poids faible de `>H` |
| 5.. | var | `AuthPayload` | token SPNEGO opaque |

Le format `'>H'` de `struct` place le poids fort en premier : c'est
littéralement la paire `HighByteOfPayloadSize` / `LowByteOfPayloadSize` de la
spécification. L'en-tête fait donc **5 octets**, ce que confirme la lecture :
`negotiate.py:66` fait `Handshake.parse(self._inner.read(5))`.

Les trois `MessageId` sont déclarés en `negotiate.py:14-17` :

| Valeur | Nom [MS-NNS] | Constante du projet | Émis par ce serveur ? |
|---|---|---|---|
| `0x14` | `HandshakeDone` | `HANDSHAKE_DONE` | Oui (`write_handshake_done`) |
| `0x15` | `HandshakeError` | `HANDSHAKE_ERROR` | **Non — jamais** |
| `0x16` | `HandshakeInProgress` | `HANDSHAKE_IN_PROGRESS` | Oui (`write` avant fin) |

Le choix de qui écrit quoi est explicite dans `GENSECStream.negotiate_server` :

- `gssapi.py:129` — `self._inner.write_handshake_done(server_to_client)` quand
 gensec signale la fin ; cela force `_handshake_done = True`
 (`negotiate.py:83`) puis émet un record `0x14`.
- `gssapi.py:131` — `self._inner.write(server_to_client)` sinon ; comme
 `_handshake_done` est encore faux, `negotiate.py:51-57` fabrique un
 `HandshakeInProgress` (`0x16`).

### Cadrage B — le message de données (après le handshake)

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
> `documentation/03-protocole.md:48` décrit les tokens de la phase 2 comme
> « préfixés d'un `int32` little-endian de longueur ». C'est vrai des messages de
> **données**, faux des messages de **handshake** : tant que `_handshake_done`
> est faux (`negotiate.py:48,51,65`), le cadrage est l'en-tête de 5 octets
> ci-dessus, dont la taille est **big-endian**. Le préfixe `int32` little-endian
> n'apparaît qu'à partir du premier octet qui suit le `HandshakeDone`.

### Synthèse : deux endianness dans le même fichier

C'est le piège de lecture principal de `negotiate.py`.

| Champ | Endianness | Format `struct` | Ligne |
|---|---|---|---|
| `payload_size` du Handshake | big-endian | `'>H'` | `negotiate.py:29` |
| `PayloadSize` du Data Message | little-endian | `'<I'` | `negotiate.py:61,79` |
| `ErrorCode` du HandshakeError | big-endian (dans ce code) | `'>II'` | `negotiate.py:71` |

Le troisième cas mérite une réserve. [MS-NNS] décrit l'`AuthPayload` d'un
`HandshakeError` comme une structure de 8 octets : `Reserved` (4 octets, mis à
zéro, à ignorer) puis `ErrorCode` (4 octets, un HRESULT ou
`ERROR_TRUST_FAILURE` = `0x000006FE`). Le projet lit bien 8 octets et retient le
second entier (`negotiate.py:71`), mais le décode en **big-endian**.
L'endianness normative de ce champ n'a pas pu être confirmée ; comme le serveur
n'est jamais destinataire d'un `HandshakeError` en pratique, ce chemin de code
n'a probablement jamais été exercé. Il contient d'ailleurs un défaut latent :
si `payload_size == 0`, `error` reste `None` et le
`"{:08x}".format(None)` de `negotiate.py:72` lève un `TypeError` au lieu de
l'`IOError` attendu.

### Ce que ce serveur ne fait pas comme .NET

| Aspect | Client .NET (SSPI) | Ce serveur (Python) |
|---|---|---|
| Cadrage handshake | [MS-NNS] Handshake Message | identique (`negotiate.py`) |
| Cadrage données | [MS-NNS] Data Message | identique (`negotiate.py`) |
| Fournisseur de sécurité | SSPI / `NegotiateStream`.NET | `samba.gensec` |
| Signalement d'erreur | `HandshakeError` + HRESULT | fermeture brutale du socket |
| Mode « ni signature ni chiffrement » | données non cadrées | non implémenté |

La différence réelle n'est donc **pas** le cadrage : c'est le *moteur* de
sécurité et la *gestion d'erreur*. Le serveur ne construit jamais de
`HandshakeError` ; `protocol.py:103-105` intercepte l'exception, journalise, et
`handle_security` retourne `False`, ce qui fait retourner
`ConnectionHandler.handle` (`connection.py:50-52`) et ferme le socket. C'est
la cause directe du message Windows documenté en
`documentation/06-depannage.md:41` : « The remote endpoint has terminated the
transport stream ». Windows ne reçoit pas de code d'erreur, il constate une
fermeture.

# SPNEGO : négociation du mécanisme (RFC 4178)

## Pourquoi SPNEGO et pas Kerberos directement

`TcpClientCredentialType.Windows` signifie « SSPI avec le paquet `Negotiate` ».
Le paquet `Negotiate` de Windows est SPNEGO (RFC 4178, étendu par [MS-SPNG]) :
un pseudo-mécanisme GSS-API dont le rôle est de choisir un vrai mécanisme parmi
une liste. Le serveur y répond en armant le même pseudo-mécanisme :

```python
self.client_ctx.start_mech_by_name("spnego")     # gssapi.py:118
```

C'est un choix explicite du projet : plutôt que de laisser gensec sélectionner
le mécanisme d'après l'OID du premier token, `gssapi.py:118` impose SPNEGO.
C'est correct pour un client WCF `Windows`, qui envoie toujours du SPNEGO. Le
comportement face à un client qui présenterait un `InitialContextToken` Kerberos
brut dépend du backend SPNEGO de Samba et **n'a pas été vérifié** : aucun code du
dépôt ne traite ce cas, et aucun repli sur `start_mech_by_name("krb5")` n'existe.

## Le tableau des OID

Un `MechType` SPNEGO est un OID DER. Voici ceux qui apparaissent dans un
échange ADWS réel, avec leur encodage DER complet (octet de type `06`, longueur,
puis contenu).

| Mécanisme | OID | Encodage DER |
|---|---|---|
| SPNEGO | 1.3.6.1.5.5.2 | `06 06 2B 06 01 05 05 02` |
| Kerberos V5 | 1.2.840.113554.1.2.2 | `06 09 2A 86 48 86 F7 12 01 02 02` |
| MS KRB5 (legacy) | 1.2.840.48018.1.2.2 | `06 09 2A 86 48 82 F7 12 01 02 02` |
| NTLMSSP | 1.3.6.1.4.1.311.2.2.10 | `06 0A 2B 06 01 04 01 82 37 02 02 0A` |
| NEGOEX | 1.3.6.1.4.1.311.2.2.30 | `06 0A 2B 06 01 04 01 82 37 02 02 1E` |

L'OID « MS KRB5 » (1.2.840.48018.1.2.2) est un artefact historique : une
implémentation Microsoft ancienne avait mal transcrit `113554` en `48018`. Les
clients Windows le proposent encore, en général **en premier**, pour
compatibilité. Un serveur SPNEGO correct doit le traiter comme un synonyme de
Kerberos V5 ; Samba le fait, ce qui explique que ce projet n'ait rien à coder à
ce sujet.

> L'ordre exact de la `MechTypeList` dépend de la version de Windows et de la
> configuration (NEGOEX est présent sur les OS récents). Cet ordre **n'est pas
> observable dans ce dépôt** : aucun code n'analyse le token SPNEGO, il est
> transmis tel quel à gensec.

## Le wrapper GSS-API InitialContextToken (RFC 2743 §3.1)

Le **premier** token d'un échange GSS-API, et lui seul, est encapsulé dans un
`InitialContextToken` :

```text
InitialContextToken ::= [APPLICATION 0] IMPLICIT SEQUENCE {
        thisMech          MechType,
        innerContextToken ANY DEFINED BY thisMech
}
```

Concrètement sur le fil : l'étiquette `[APPLICATION 0] SEQUENCE` en DER vaut
l'octet `0x60`, suivi de la longueur DER, de l'OID du mécanisme, puis du token
interne. Les tokens **suivants** de la même conversation ne portent pas ce
wrapper.

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
> RFC 4121 §4.1. Il n'est **pas** extrait d'une capture de ce dépôt : le projet
> ne décode aucun token SPNEGO. Les longueurs `XX XX` dépendent de la taille du
> ticket, elle-même fonction du PAC (souvent 1 à 4 Ko).

## NegTokenInit et NegTokenResp

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

Le `mechListMIC` est la protection anti-rétrogradation de SPNEGO : un attaquant
qui retirerait Kerberos de la `mechTypes` pour forcer NTLM invaliderait le MIC.
`request-mic` (valeur 3) est le mécanisme par lequel l'accepteur impose cet
échange. Windows l'exige systématiquement depuis les correctifs de durcissement
NTLM. **Tout cela est traité intégralement par Samba** : le projet ne voit que
des `bytes`.

## Conséquence directe sur le nombre d'allers-retours

La boucle `while not server_finished` de `gssapi.py:123-132` ne présume pas du
nombre de tours, et c'est nécessaire :

| Scénario | Tours (client→serveur) | Cause |
|---|---|---|
| Kerberos optimiste accepté | 1 | `mechToken` valide dès `NegTokenInit` |
| `request-mic` demandé | 2 | Un tour supplémentaire pour les MIC |
| Repli NTLM | 3 | Negotiate / Challenge / Authenticate |

Le repli NTLM est possible **par construction**. La mécanique exacte mérite
d'être posée : dans RFC 4178, l'accepteur ne publie pas sa propre liste, il
**choisit** dans celle de l'initiateur et renvoie le mécanisme retenu dans
`supportedMech`. Comme le client Windows place NTLMSSP dans sa `mechTypes` et que
gensec, sur un DC Samba de configuration usuelle, dispose du backend NTLMSSP,
rien n'empêche la sélection de NTLM lorsque Kerberos échoue. Ce projet n'a aucun
code pour l'interdire : il n'y a aucun appel à `want_feature` ni aucune
restriction de mécanisme dans le dépôt (recherche exhaustive sur `want_feature`
et `GENSEC_FEATURE` : zéro occurrence). Interdire NTLM se fait au niveau de
`smb.conf` (paramètre `ntlm auth`), donc hors de ce code — et le
`documentation/` du dépôt ne prescrit rien à ce sujet.

# Kerberos : obtention du ticket de service côté client

## Le SPN effectivement demandé

WCF, pour une `EndpointAddress` `net.tcp://<host>:9389/…` sans identité
explicite, dérive un `SpnEndpointIdentity` de la forme `host/<host>` à partir du
nom DNS de l'URI. Ce comportement n'est pas dans ce dépôt (il est côté Windows),
mais le dépôt le **confirme** de trois façons indépendantes :

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
`KDC_ERR_S_PRINCIPAL_UNKNOWN` et Windows bascule silencieusement sur NTLM. Comme
Samba accepte NTLMSSP via SPNEGO, la connexion **peut réussir quand même**, avec
une authentification plus faible. Ce comportement de repli est déduit des
spécifications et de la configuration Samba par défaut ; il **n'a pas été vérifié
expérimentalement dans ce dépôt** et aucun code ne le trace.

## La chaîne TGT vers AP-REQ

- **1. TGT.** Le client possède déjà un `krbtgt/REALM@REALM` obtenu à l'ouverture
 de session (ou via `kinit`, cf. `documentation/02-installation.md:74`). Rien de
 spécifique à ADWS ici.
- **2. TGS-REQ.** Le client demande au KDC un ticket pour `host/samba.local` :
 un `PA-TGS-REQ` (padata type 1) portant un AP-REQ vers `krbtgt`, et le SPN
 cible dans le champ `sname` du corps.
- **3. TGS-REP.** Le KDC répond avec le `Ticket` chiffré sous la **clé de long
 terme du compte machine du DC**, et une partie chiffrée sous la clé de session
 du TGT qui porte la nouvelle clé de session de service.
- **4. AP-REQ.** Le client assemble le ticket tel quel plus un `Authenticator`
 chiffré sous la clé de session de service.
- **5. AP-REP.** Le serveur, s'il a pu déchiffrer, renvoie `ctime`/`cusec`
 recopiés et éventuellement une sous-clé d'accepteur. C'est cet AP-REP qui
 réalise l'authentification **mutuelle**.

Les étapes 1 à 3 se déroulent sur le port 88 (TCP/UDP), listé parmi les ports
requis du client vers le DC en `documentation/02-installation.md:39` (table des
ports, lignes 37 à 42). Le serveur ADWS ne voit que l'étape 4 et produit
l'étape 5 : il n'est ni KDC ni relais vers le KDC.

## Requested flags

The vendored `GSSAPIStream` client explicitly requests the five services used
by the protected ADWS stream:

```python
flags=(gssapi.RequirementFlag.mutual_authentication |
       gssapi.RequirementFlag.confidentiality |
       gssapi.RequirementFlag.integrity |
       gssapi.RequirementFlag.replay_detection |
       gssapi.RequirementFlag.out_of_sequence_detection)
```

Mutual authentication, confidentiality, and integrity implement the service's
`ProtectionLevel.EncryptAndSign` and `ClientCredentialType.Windows` contract.
Replay and sequence detection prevent a caller from silently losing the
ordering guarantees described by this protocol. After SPNEGO completes, the
client verifies that all five flags were negotiated before it sends WCF data.
Their numeric GSS-API encoding is:

| Bit | GSS-API flag | Linux client request |
|---|---|---|
| `0x01` | `GSS_C_DELEG_FLAG` | No |
| `0x02` | `GSS_C_MUTUAL_FLAG` | Yes |
| `0x04` | `GSS_C_REPLAY_FLAG` | Yes |
| `0x08` | `GSS_C_SEQUENCE_FLAG` | Yes |
| `0x10` | `GSS_C_CONF_FLAG` | Yes (`EncryptAndSign`) |
| `0x20` | `GSS_C_INTEG_FLAG` | Yes |

> `GSSAPIStream` (`gssapi.py:20-78`) is the **client** path inherited from Timo
> Schmid's upstream project. The server never instantiates it: `protocol.py`
> uses only `GENSECStream`. `src/nettcp/stream/nmf.py:37` uses the initiator for
> the public `samba_adws.client.ADWSClient`; server-side Samba imports remain
> lazy so this path works on a Linux workstation.

## Types de chiffrement

Le projet ne configure **aucun** type de chiffrement : recherche exhaustive sur
`etype`, `enctype`, `aes`, `rc4` dans les sources — aucun résultat hors
dictionnaire WCF XML-Enc (`src/wcf/dictionary.py:168-173`, sans rapport). Tout
est délégué à la bibliothèque Kerberos de Samba et à `/etc/krb5.conf`.

| etype | Nom | Référence | Statut sur un DC Samba |
|---|---|---|---|
| 18 | `aes256-cts-hmac-sha1-96` | RFC 3962 | Proposé, préféré |
| 17 | `aes128-cts-hmac-sha1-96` | RFC 3962 | Proposé |
| 23 | `rc4-hmac` | RFC 4757 | Proposé (compatibilité) |
| 16 | `des3-cbc-sha1-kd` | RFC 3961 | Obsolète, non utilisé |
| 1 / 3 | `des-cbc-crc` / `des-cbc-md5` | RFC 3961 | Désactivés par défaut |

L'attribut `msDS-SupportedEncryptionTypes` du compte machine ([MS-KILE] §2.2.7)
gouverne ce que le KDC accepte de proposer :

| Bit | Type couvert |
|---|---|
| `0x01` | DES-CBC-CRC |
| `0x02` | DES-CBC-MD5 |
| `0x04` | RC4-HMAC |
| `0x08` | AES128-CTS-HMAC-SHA1-96 |
| `0x10` | AES256-CTS-HMAC-SHA1-96 |

Le support des etypes RFC 8009 (19 = `aes128-cts-hmac-sha256-128`, 20 =
`aes256-cts-hmac-sha384-192`) dépend entièrement de la version de Samba et de sa
bibliothèque Kerberos ; il **n'a pas été vérifié** pour la version ciblée par ce
projet, que le `CLAUDE.md` §8 laisse d'ailleurs « à préciser ». Les mentions
« Kerberos AES256 » de `documentation/03-protocole.md:15` et « Kerberos AES » de
`README.md:39` décrivent l'usage nominal attendu, pas une contrainte imposée ou
vérifiée par le code : aucune ligne du dépôt ne refuse un etype.

# Le token AP-REQ : structure et champs

## Le tableau des TOK_ID

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
introduite par RFC 4121) ; ceux à second octet `0x01` appartiennent au format
historique RFC 1964, qui utilisait `01 01` pour le MIC et `02 01` pour le Wrap.
Un DC Samba et un client Windows moderne n'utilisent que CFX dès lors que
l'etype est AES. RFC 4121 ne définit **que** ces deux tokens par message : il
n'existe pas de token de destruction de contexte en version 2, contrairement au
`01 02` de RFC 1964. Aucun de ces octets n'apparaît dans le code de ce dépôt —
la table sert à lire une capture, pas à décrire un traitement.

## Structure de l'AP-REQ (RFC 4120 §5.5.1)

```text
AP-REQ ::= [APPLICATION 14] SEQUENCE {
        pvno            [0] INTEGER (5),
        msg-type        [1] INTEGER (14),
        ap-options      [2] APOptions,
        ticket          [3] Ticket,
        authenticator   [4] EncryptedData -- Authenticator
}
```

L'étiquette `[APPLICATION 14]` se traduit par l'octet `0x6E` en DER — c'est le
premier octet visible après le `01 00` du TOK_ID.

| Champ | Contenu pour ADWS |
|---|---|
| `pvno` | 5 |
| `msg-type` | 14 (`KRB_AP_REQ`) |
| `ap-options` | `mutual-required` positionné (bit 2) |
| `ticket` | Ticket pour `host/<fqdn>`, chiffré sous la clé machine du DC |
| `authenticator` | `EncryptedData` (usage 11), clé = clé de session du ticket |

`APOptions` est un `KerberosFlags` (BIT STRING) : `reserved` = bit 0,
`use-session-key` = bit 1, `mutual-required` = bit 2. Comme la numérotation des
bits part du poids fort, `mutual-required` seul donne `0x20` dans le premier
octet utile de la chaîne de bits.

## Structure de l'Authenticator

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

Le premier est **`cksum`**. Pour GSS-API, c'est un checksum de type **0x8003**
défini par RFC 4121 §4.1.1 ; ce n'est pas un vrai checksum, mais un conteneur de
paramètres, disposé ainsi.

| Offset | Long. | Champ | Valeur / rôle |
|---|---|---|---|
| 0..3 | 4 | `Lgth` | `10 00 00 00` (16, little-endian) |
| 4..19 | 16 | `Bnd` | MD5 des channel bindings, ou 16 octets nuls |
| 20..23 | 4 | `Flags` | Flags GSS-API, little-endian |
| 24..25 | 2 | `DlgOpt` | Présent seulement si `GSS_C_DELEG_FLAG` |
| 26..27 | 2 | `Dlgth` | Longueur du `KRB_CRED` délégué |
| 28.. | var | `Deleg` | `KRB_CRED` délégué |

ADWS ne demandant pas la délégation, les champs `DlgOpt`/`Dlgth`/`Deleg` sont
**absents** et le checksum fait exactement 24 octets. Le champ `Flags` porte les
valeurs `0x02 | 0x08 | 0x10 | 0x20` (mutual, sequence, conf, integ), soit `0x3A`,
encodé `3A 00 00 00`.

Le deuxième est **`subkey`**, la sous-clé proposée par l'initiateur. Si elle est
présente, c'est elle, et non la clé de session du ticket, qui sert de base à la
dérivation des clés de scellement RFC 4121. L'accepteur peut à son tour proposer
la sienne dans l'AP-REP : le flag `AcceptorSubkey` (bit `0x04` du champ `Flags`
du token Wrap) signale alors que la clé de l'accepteur est utilisée.

Le troisième est le couple **`ctime` / `cusec`**, l'horodatage du client, que le
serveur compare à son horloge locale avec une tolérance par défaut de 5 minutes
(`clockskew`). Au-delà, l'authentification échoue — cause de l'avertissement de
`documentation/06-depannage.md:69`.

## Ce que ce projet manipule de tout cela

**Rien.** Aucun octet de l'AP-REQ n'est analysé par du code Python de ce dépôt.
`GENSECStream.negotiate_server` transmet le token intégral à
`self.client_ctx.update(token)` (`gssapi.py:125`). La section précédente est
donc une description du *contenu* du champ `AuthPayload` du message NNS, utile
pour lire une capture Wireshark, et non de structures que le projet
construirait ou validerait.

# Établissement du contexte côté serveur avec samba.gensec

## La séquence exacte, ligne par ligne

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

Deux points d'ordre méritent d'être soulignés parce qu'ils sont contre-intuitifs.

- **La lecture précède la création du contexte.** `gssapi.py:105` lit le token
 avant que `start_server` ne soit appelé. Aucun contexte gensec n'est alloué
 tant que le client n'a rien dit — c'est économe, mais cela signifie aussi
 qu'un client muet ne laisse aucune trace exploitable dans les journaux. Et il
 reste muet aussi longtemps qu'il le souhaite : le timeout de 10 secondes posé
 en `connection.py:39` **est annulé dès la première lecture**. `SocketStream`
 appelle `self._socket.setblocking(1)` avant chaque `recv` (`socket.py:32`) et
 avant chaque `sendall` (`socket.py:51`) ; or `setblocking(True)` équivaut, par
 définition de l'API socket de Python, à `settimeout(None)`. La conséquence est
 double : un client qui ouvre la connexion et se tait immobilise un processus
 fils indéfiniment, et le chemin `except socket_timeout` de
 `protocol.py:115-125` — celui qui est censé envoyer l'`EndRecord` de clôture —
 n'est jamais atteint. C'est un point de durcissement de phase 5 aussi
 important que l'identité : le serveur étant en `ForkingTCPServer`
 (`classes/server/server.py:25`), chaque connexion muette coûte un processus.
- **`guess` puis `set_machine_account`.** L'ordre compte :
 `set_machine_account` écrase les identifiants devinés par `guess`. Inverser
 les deux lignes ferait tenter une authentification avec les credentials du
 processus (root, ou un ccache résiduel) au lieu du compte machine.

## Le contrat de `update`

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
`documentation/06-depannage.md:33` — `samba.NTSTATUSError: (3221225572, 'The
specified account does not exist.')` — est exactement une exception échappée de
`update`, remontée jusqu'au `except Exception` de `protocol.py:103`.

> **Trace obsolète dans la documentation.** La même trace, en
> `documentation/06-depannage.md:31`, situe l'appel à
> `src/nettcp/stream/gssapi.py`, ligne 119. Dans l'état actuel du fichier, la
> ligne 119 est vide : l'appel à `update` est en `gssapi.py:125`. Le numéro de
> ligne de la documentation date d'une version antérieure du fichier et ne doit
> pas servir de repère.

Noter que `write_handshake_done` est appelé **même si `server_to_client` est
vide** : [MS-NNS] autorise un `AuthPayload` de longueur nulle dans un
`HandshakeDone` lorsque le paquet de sécurité n'a pas produit de token final.
Le code est donc conforme sans avoir eu à traiter ce cas explicitement.

## Pourquoi aucun keytab externe n'est requis

C'est la conséquence directe de `creds.set_machine_account(self.lp_ctx)`
(`gssapi.py:115`). Cet appel lit le secret du compte machine du DC dans la base
de secrets locale de Samba — `/var/lib/samba/private/secrets.tdb` (et
`secrets.ldb`), ce que confirme `documentation/03-protocole.md:57`. Sur un
contrôleur de domaine, ces secrets contiennent les clés de long terme de tous
les etypes du compte machine, celles-là mêmes avec lesquelles le KDC a chiffré
le ticket de service.

| Approche classique | Ce projet |
|---|---|
| `samba-tool domain exportkeytab /etc/adws.keytab` | inutile |
| `KRB5_KTNAME=/etc/adws.keytab` dans l'environnement | absent |
| Rotation manuelle du keytab au changement de mdp machine | automatique |

Le corollaire opérationnel est une **contrainte de privilèges** : la base de
secrets n'est lisible que par root. C'est pourquoi
`documentation/02-installation.md:124` prescrit `sudo python3 -m src.main` et
pourquoi l'unit systemd tourne en root. Un `Requires=samba-ad-dc.service` est
d'ailleurs posé dans `tools/installation/samba-adws.service`.

Second corollaire, moins évident : **le serveur ne restreint pas le service
demandé** — il ne le connaît même pas. Aucun `target_service` n'est posé dans
`settings` (`gssapi.py:97-102`), et aucune comparaison de SPN n'existe dans le
dépôt. Un ticket émis pour un autre SPN du même compte machine, par exemple
`cifs/<fqdn>`, se déchiffre avec la même clé de long terme ; la question de
savoir si gensec le rejette malgré tout relève de son implémentation et **n'a
pas été vérifiée expérimentalement ici**. Ce qui est certain, c'est que ce projet
n'apporte aucune restriction de son côté.

## Ce que `settings` contient, et ce qu'il ne contient pas

```python
self.settings["lp_ctx"] = self.lp_ctx = LoadParm()     # gssapi.py:99
self.settings["target_hostname"] = self.lp_ctx.get("netbios name")   # :102
```

`target_hostname` est renseigné avec le **nom NetBIOS**, pas le FQDN, alors que
le SPN présenté par le client porte le FQDN. L'écart n'a jamais provoqué
d'incident documenté dans ce dépôt — vraisemblablement parce que ce champ sert
surtout à l'initiateur pour construire le nom de service cible — mais cette
explication est une **interprétation, non vérifiée** dans le code de Samba.
Ce qui est certain et vérifiable : le dictionnaire `settings` ne contient que ces
deux clés (`gssapi.py:97-102`), aucun `target_service` n'y figure, et aucun
`want_feature` n'est appelé. Le niveau de protection effectif est donc
**entièrement dicté par les flags du client**.

# Scellement des messages : wrap / unwrap (RFC 4121)

## L'ordre d'emboîtement : la réponse formelle

C'est la question la plus fréquemment mal tranchée. Voici la démonstration par
le code, dans le sens émission.

- **1.** `protocol.py:153-156` construit
 `nmf.SizedEnvelopedMessageRecord(Payload=payload, Size=len(payload))` où
 `payload` est le XML binaire WCF produit par le dispatcher.
- **2.** `protocol.py:157` appelle `send_record(response)` qui fait
 `self.stream.write(record.to_bytes)` (`protocol.py:185-188`). `to_bytes`
 (`nmf.py:275-287`) sérialise `0x06` + varint(Size) + Payload.
- **3.** `self.stream` a été remplacé par `GENSECStream` en `protocol.py:96`.
 On entre donc dans `GENSECStream.write` (`gssapi.py:144-152`), qui découpe en
 tranches de `_PLAINTEXT_CHUNK` et applique `self.client_ctx.wrap(data2)`.
- **4.** Le token scellé part dans `self._inner.write(e_data)`, c'est-à-dire
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
`nmf.Record.parse_stream(self.stream)`, où `self.stream` est le `GENSECStream`.
`Record.parse_stream` (`nmf.py:256-273`) lit **1 octet** pour le code, puis les
champs — chacun de ces `read` traverse `GENSECStream.read(count)`
(`gssapi.py:162-170`), qui descelle des trames entières et sert les octets
demandés depuis `_readcache`. Le parseur NMF ne voit donc que du clair.

> **Correction d'une erreur de la documentation du dépôt.** Le schéma de
> `documentation/03-protocole.md:67-71` dessine
> `0x06 | varint length | GSSAPI-wrapped(WCF binary)`, ce qui laisse entendre que
> l'en-tête NMF est en clair. Le code montre l'inverse. Une capture réseau après
> la phase 2 ne montre **que** des trames `uint32 LE + token opaque` : on ne voit
> plus jamais l'octet `0x06`.

## Le token Wrap version 2 (RFC 4121 §4.2.6.2)

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

Avec confidentialité, la charge utile n'est pas simplement le clair chiffré :
RFC 4121 §4.2.4 impose de chiffrer la concaténation
`confounder || plaintext || filler || copie de l'en-tête`, puis d'appliquer la
rotation `RRC`. Pour `aes256-cts-hmac-sha1-96`, le surcoût se décompose ainsi.

| Élément | Octets |
|---|---|
| En-tête en clair | 16 |
| Confounder (taille de bloc AES) | 16 |
| Copie de l'en-tête, chiffrée | 16 |
| Tag HMAC-SHA1-96 tronqué | 12 |
| **Total (avec EC = 0)** | **60** |

Ce chiffre de 60 octets n'est pas théorique : c'est celui qui figure dans le
commentaire de `src/nettcp/stream/gssapi.py:12-16`, et c'est lui qui a dicté la
valeur de `_PLAINTEXT_CHUNK`.

## Pourquoi `_PLAINTEXT_CHUNK = 0xF000`

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

Le commentaire de `gssapi.py:12-16` explique la raison d'être de cette marge :
« otherwise a single wrapped token spills into a second frame and the reader,
which assumes one frame == one token, fails to unwrap it ». C'est exact et
vérifiable : `GENSECStream.read` (`gssapi.py:163-166`) appelle `unwrap` sur le
résultat d'**un seul** `self._inner.read`. Il n'existe aucun réassemblage de
token à cheval sur deux trames MS-NNS. Si le clair dépassait la marge, le
descellement échouerait.

Le découpage n'est en revanche **pas** un problème pour les gros messages : une
réponse `Pull` de 500 Ko produit simplement neuf tokens successifs, et le
`_readcache` de `GENSECStream` (`gssapi.py:162-169`) recolle le clair de façon
transparente pour le parseur NMF.

## Ce que le projet fait, et ce que la bibliothèque fait

| Opération | Réalisée par | Ancrage |
|---|---|---|
| Construction de l'en-tête `05 04` | Samba (gensec) | opaque au projet |
| Choix `Sealed` vs signature seule | Samba, d'après les flags client | pas de `want_feature` |
| Incrément de `SND_SEQ` | Samba | jamais lu par le projet |
| Vérification du HMAC | Samba, dans `unwrap` | `gssapi.py:160,166` |
| Détection de rejeu / hors-séquence | Samba, si le flag est négocié | requested and checked by the Linux client |
| Découpage en tranches | **Le projet** | `gssapi.py:148-152` |
| Cadrage `uint32` LE | **Le projet** | `negotiate.py:61` |
| Réassemblage du clair | **Le projet** | `gssapi.py:162-169` |

Le périmètre du projet est donc strictement : découper, cadrer, recoller.
Toute la cryptographie est chez Samba.

## MIC, rejeu et numéros de séquence

- Le **`mechListMIC`** de SPNEGO est produit et vérifié par gensec pendant la
 phase de handshake. Le projet ne le voit pas.
- Le **MIC par message** (TOK_ID `04 04`) n'est jamais utilisé : ADWS scelle
 tout, il n'y a pas de message signé sans être chiffré. Aucun appel à une
 fonction `sign`/`check_packet` n'existe dans le dépôt.
- Le **`SND_SEQ`** est géré par Samba. Le projet ne l'inspecte pas et ne peut
 donc pas journaliser un désalignement de séquence : un tel incident se
 manifeste par une exception d'`unwrap` remontée en `protocol.py:179-181`.
- Le **cache anti-rejeu Kerberos** (`rcache`) dépend de la compilation de Samba
 et de la configuration Kerberos système. Aucune variable `KRB5RCACHE*` ni
 aucun réglage de rcache n'apparaît dans ce dépôt : **non vérifié**, et non
 gouverné par ce projet.

# Identité, délégation et contrôle d'accès

## Le constat, sans ménagement

L'identité du client est établie de façon cryptographiquement solide, puis
**abandonnée**. La preuve tient en trois lignes de `classes/server/connection.py`.

```python
session_info = system_session() if system_session else None
dispatcher = ADWSDispatcher(self.logger, session_info=session_info)
```

Ces deux lignes sont `connection.py:56-57` ; elles sont précédées du commentaire
`Use system_session for SamDB context - auth is done via GSSAPI`
(`connection.py:55`), qui assume explicitement le raccourci. Le `session_info`
transmis à tout l'étage applicatif est
`samba.auth.system_session`, c'est-à-dire l'identité **SYSTEM** de la base,
pas celle du client. Le contexte gensec (`GENSECStream.client_ctx`) n'est
consulté à aucun moment après la négociation : une recherche exhaustive sur
`client_ctx` dans le dépôt ne retourne que des occurrences internes à
`src/nettcp/stream/gssapi.py`, et **aucun** appel à la méthode `session_info`
de l'objet gensec n'existe nulle part.

## Chemin complet du `session_info`

| Étape | Fichier | Valeur véhiculée |
|---|---|---|
| Création | `connection.py:56` | `system_session` |
| Injection dispatcher | `connection.py:57` | idem |
| Stockage | `dispatcher.py:17-18` | idem |
| Registre de handlers | `handler_registry.py:11-13` | idem |
| Handler de base | `base.py:19-21` | idem |
| Ouverture LDB | `samba_db.py:15,26` | `SamDB(lp=lp, session_info=...)` |

`samba_db.py:15` applique de surcroît un repli
`session_info or system_session` : même un `None` accidentel finit en SYSTEM.

Le pool de sessions LDAP mérite une précision, car il est facile de le prendre
pour une amorce fonctionnelle. `LdapSessionPool.acquire`
(`ldap_session_pool.py:28-50`) indexe bien ses `SambaDB` par
`(owner_sid, instance)` et accepte un `session_info` par appelant, ce qui montre
l'intention d'un jour porter l'identité réelle. Mais l'objet n'est
qu'**instancié** (`classes/server/service_context.py:18`) : une recherche sur
`session_pool` dans tout le dépôt ne retourne que cette instanciation et
l'import qui la précède. Aucun handler n'appelle `acquire`, `release` ni
`get`. Le chemin de requête réel reste celui du tableau ci-dessus, c'est-à-dire
le `SambaDB` créé directement par `BaseHandler.__init__` (`base.py:21`). À cela
s'ajoute que le serveur est en `ForkingTCPServer` (`server.py:25`) : le
singleton `ServiceContext` (`service_context.py:21-26`) est reconstruit dans
chaque processus fils, donc un pool de connexions inter-clients ne pourrait de
toute façon pas fonctionner sous cette forme.

## Conséquences concrètes

- **Toutes les opérations d'annuaire s'exécutent avec les privilèges du
 service**, c'est-à-dire root sur le DC, donc SYSTEM dans LDB. Les ACL AD ne
 sont pas évaluées contre l'utilisateur qui a lancé la cmdlet.
- Le message d'erreur `InsufficientAccessRights` documenté en
 `documentation/06-depannage.md:293` ne peut donc **pas** provenir d'un refus
 d'ACL lié à l'appelant : il proviendrait d'une contrainte LDB ou d'une
 vérification de politique côté Samba. La section 8 de ce document
 (« Droits insuffisants », `documentation/06-depannage.md:282`), dont la cause
 annoncée est « Le compte authentifié … n'a pas les droits AD »
 (`documentation/06-depannage.md:298`), décrit une intention de conception, pas
 le comportement du code actuel.
- Il n'y a **aucun contrôle d'autorisation applicatif** : dès lors que le
 handshake GSSAPI réussit, n'importe quel compte du domaine peut déclencher
 n'importe quelle opération exposée par les handlers, y compris les mutations.
 Le seul rempart est l'authentification.

> **Point de durcissement prioritaire (phase 5).** Remplacer `system_session`
> par la `session_info` produite par le contexte gensec est la modification qui
> apporterait le plus de sécurité, et la plus structurante : elle transformerait
> le service d'un proxy privilégié en un véritable relais d'identité, avec
> évaluation des ACL AD par Samba.

## Délégation

Aucune forme de délégation n'est implémentée :

| Mécanisme | État |
|---|---|
| `GSS_C_DELEG_FLAG` / ticket transmis | Non demandé, non exploité |
| Délégation contrainte S4U2Proxy | Absent |
| S4U2Self (protocol transition) | Absent |
| Connexion `ldapi://` sous l'identité client | Absent |

`documentation/01-architecture.md:155` cite précisément l'absence de délégation
comme cause d'une limite fonctionnelle : le changement de mot de passe
self-service (`Set-ADAccountPassword` avec ancien et nouveau mot de passe) échoue
parce que le module Samba `password_hash` exige l'adresse réseau du client, non
fournissable via une `SamDB` locale. La piste explicitement mentionnée est la
« délégation de l'identité du client GSSAPI ». Le reset administrateur
(`-Reset`) fonctionne, lui, puisqu'il s'exécute avec des privilèges SYSTEM.

# Diagnostic des échecs d'authentification

## Ce que le serveur journalise réellement

Trois messages seulement encadrent la phase 2, tous dans `protocol.py` :

| Message | Ligne | Interprétation |
|---|---|---|
| `[SECURITY] PHASE 2: SECURITY NEGOTIATION` | `:71` | `handle_security` démarre |
| `[SECURITY] Starting GSSAPI negotiation...` | `:95` | `UpgradeResponseRecord` déjà émis |
| `[SECURITY] GSSAPI negotiation completed` | `:99` | Contexte établi, `wrap` actif |

Si le troisième n'apparaît pas, l'échec est dans la boucle `update`. La trace
complète est journalisée par `protocol.py:104` avec `exc_info=True`.

Il faut ici démonter une idée reçue, car elle fait perdre un temps considérable
en diagnostic. La pile de sécurité comporte bien trois traces DEBUG utiles —
`Doing step` (`gssapi.py:124`), `NNS Handshake done` (`negotiate.py:75`) et, si
`python-helperlib` est installé, un hexdump complet de chaque lecture et
écriture (`socket.py:41-43` et `:47-49`) — mais **`ADWS_LOG_LEVEL=DEBUG` ne les
fait pas apparaître.** Trois mécanismes se conjuguent contre l'opérateur.

| Obstacle | Emplacement | Effet |
|---|---|---|
| `ADWS_LOG_LEVEL` ne vise que le logger `adws` | `config.py:46`, `:56` | Périmètre trop étroit |
| Le handler console est figé à `INFO` | `config.py:60` | DEBUG jamais affiché |
| `basicConfig(level=INFO)` à l'import | `src/wcf/records/text.py:62` | Racine forcée à INFO |

Le détail du troisième obstacle mérite d'être explicité. Les modules
`src/wcf/records/text.py:62`, `src/wcf/records/elements.py:44` et
`src/wcf/records/attributes.py:44` appellent `logging.basicConfig(level=INFO)`
**au moment de leur import**, et cet import a lieu dès le chargement du
dispatcher (`classes/handlers/dispatcher.py:4`). Or les loggers de la pile de
sécurité s'appellent `src.nettcp.stream.gssapi.GSSAPIStream`,
`src.nettcp.stream.negotiate.NegotiateStream` et
`src.nettcp.stream.socket.SocketStream` (`gssapi.py:10`, `negotiate.py:11`,
`socket.py:16`) : ils héritent du logger **racine**, pas du logger `adws`
configuré par `Config.setup_logging`. Leur niveau effectif est donc `INFO`,
quelle que soit la valeur de `ADWS_LOG_LEVEL`, et le test
`log.isEnabledFor(logging.DEBUG)` de `socket.py:41` et `:47` est faux.

Pour réellement observer les tokens du handshake, il faut abaisser le niveau du
logger racine — par exemple en ajoutant `logging.getLogger.setLevel(DEBUG)`
après `config.setup_logging` dans `src/main.py`, ou en instrumentant
temporairement `src/nettcp/stream/`. À défaut, le proxy `tools/work/proxy.py`
(qui, lui, appelle `logging.basicConfig(level='DEBUG')` en `proxy.py:34`) reste
la voie la plus rapide.

## Table de diagnostic : erreurs Kerberos

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

Les valeurs numériques sont celles de RFC 4120 §7.5.9. La lecture de cette table
suppose une distinction que le terrain confond souvent : les codes `KDC_ERR_*`
(6, 7, 14, 24) sont émis par le **KDC vers le client**, lors du TGS-REQ, et ne
traversent jamais le port 9389 — le serveur ADWS ne les voit pas et ne peut donc
pas les journaliser. Les codes `KRB_AP_ERR_*` (32, 34, 37, 41) naissent en
revanche de la validation de l'AP-REQ par l'accepteur, donc dans `update`
(`gssapi.py:125`), et se manifestent sous forme de `samba.NTSTATUSError`.
`KRB_AP_ERR_MODIFIED` (41) est le plus trompeur : il signifie littéralement
« je n'ai pas pu déchiffrer le ticket ». Sur ce serveur, cela se produit si le
mot de passe du compte machine a changé sans que `secrets.tdb` ne soit à jour,
ou si le SPN demandé est enregistré sur un **autre** compte que celui du DC.

## Table de diagnostic : NTSTATUS remontés par gensec

| NTSTATUS | Décimal | Nom | Cause côté ADWS |
|---|---|---|---|
| `0xC0000064` | 3221225572 | `STATUS_NO_SUCH_USER` | SPN demandé absent d'AD |
| `0xC000006D` | 3221225581 | `STATUS_LOGON_FAILURE` | Échec générique du paquet |
| `0xC0000133` | 3221225779 | `STATUS_TIME_DIFFERENCE_AT_DC` | Dérive d'horloge |
| `0xC0000022` | 3221225506 | `STATUS_ACCESS_DENIED` | Secrets illisibles (pas root) |
| `0xC000000D` | 3221225485 | `STATUS_INVALID_PARAMETER` | Token malformé / tronqué |

Seul le premier est attesté par une trace réelle du dépôt
(`documentation/06-depannage.md:33-36`, qui donne `3221225572` et son
interprétation). Les quatre autres sont les correspondances NTSTATUS standard
des causes listées ; ils **n'ont pas été observés** dans les journaux versionnés
de ce projet et sont donnés à titre de grille de lecture.

## Symptômes côté Windows et leur traduction

| Message Windows | Origine serveur | Section du dépôt |
|---|---|---|
| `The remote endpoint has terminated the transport stream` | `protocol.py:105` a rendu `False` | 06 §1 et §2 |
| `Le site distant a fermé le flux de transport` | idem, localisé | 06 §2 |
| `Unable to find a default server…` | Jamais atteint le port 9389 | 06 §7 |
| Cmdlet qui bloque jusqu'au timeout | Fault SOAP sans `RelatesTo` | 06 §6 |

Le premier symptôme est **indiscernable** entre un échec Kerberos et un crash de
handler, parce que le serveur ferme le socket dans les deux cas sans émettre de
`HandshakeError`. C'est la raison pour laquelle
`documentation/06-depannage.md:83-85` liste trois causes possibles pour un seul
message. Émettre un vrai `HandshakeError` (`negotiate.py` déclare déjà la classe
`HandshakeError`, code `0x15`, mais rien ne l'instancie) permettrait à Windows
d'afficher le HRESULT — amélioration de diagnostic identifiée, non implémentée.

## Séquence de vérification opérationnelle

- **1.** `sudo samba-tool spn list "$(hostname -s)$"` — le SPN `host/<fqdn>`
 doit être présent (`documentation/06-depannage.md:51`).
- **2.** `timedatectl status` sur le DC et `w32tm /query /status` sur le client —
 écart inférieur à 5 minutes.
- **3.** `klist purge` puis `klist` côté Windows après correction d'un SPN — le
 cache de tickets doit être vidé, sinon l'ancien ticket erroné est réutilisé.
- **4.** `ss -tlnp | grep 9389` — le service écoute et tourne bien en root.
- **5.** `sudo journalctl -u samba-adws -f` pendant la reproduction — chercher la
 présence ou l'absence de `[SECURITY] GSSAPI negotiation completed`.
- **6.** En dernier recours, observer les tokens du handshake — ils sont en clair
 jusqu'au `HandshakeDone` inclus. `ADWS_LOG_LEVEL=DEBUG` (`config.py:46`) **ne
 suffit pas** (voir ci-dessus) : il faut abaisser le niveau du logger racine, ou
 passer par `tools/work/proxy.py`.

## Diagramme de séquence complet de la phase de sécurité

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

Deux détails de ce diagramme sont souvent manqués et méritent d'être répétés.

- Le **`PreambleEndRecord` traverse le canal chiffré**, et il va du **client vers
 le serveur**. Contrairement à ce que son nom suggère, il n'appartient pas à la
 phase de préambule en clair : il arrive **après** le handshake, donc scellé.
 `protocol.py:133-138` le traite dans `handle_messages` (la « phase 3 » du
 code), pas dans `handle_preamble`, et y répond par un `PreambleAckRecord`
 (`0x0b`, `nmf.py:344-345`). Le client de référence vendoré confirme l'ordre :
 `src/nettcp/stream/nmf.py:37` installe `GSSAPIStream`, puis `:39` écrit
 `PreambleEndRecord` et `:41` attend l'acquittement ;
 `tools/work/proxy.py:144-148` fait la même chose côté proxy, en accepteur
 cette fois.
- Le **`0x0A UpgradeResponseRecord` est le dernier octet en clair** émis par le
 serveur. Tout ce qui suit est soit un message de handshake MS-NNS (dont
 l'`AuthPayload` est un token SPNEGO, lisible mais non exploitable), soit une
 trame de données scellée.

> **Troisième écart avec la documentation du dépôt.** Le schéma de
> `documentation/03-protocole.md:50-55` dessine
> `client ◄─── PreambleEndRecord (0x0c) ───── serveur`, c'est-à-dire une émission
> par le serveur, présentée comme le signal « sécurité OK ». Le sens est
> inversé : c'est le client qui émet `0x0c` une fois le canal établi, et c'est le
> serveur qui répond `0x0b` (`protocol.py:133-137`). Le signal « sécurité OK »
> côté client, c'est le `HandshakeDone` (`0x14`), pas le `PreambleEndRecord`.

## Défauts latents identifiés dans la pile de sécurité

Ces points sont vérifiés dans le code et non encore corrigés. Ils sont listés
ici parce qu'ils déterminent le comportement observable en cas d'anomalie.

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
`connection.py:39` pose `settimeout(10)`, mais chaque `SocketStream.read` avec un
compte appelle `setblocking(1)` (`socket.py:32`), équivalent documenté de
`settimeout(None)` : le délai disparaît avant même la lecture du premier octet du
préambule. `protocol.py:162-166` tente ensuite de le ramener à 2 secondes après
la première réponse, via `self.stream._socket.settimeout(2)` — mais à ce stade
`self.stream` est un `GENSECStream`, qui n'expose ni `_socket` ni `__getattr__`
(le socket réel est deux niveaux plus bas, dans le `SocketStream` enveloppé par
`NegotiateStream`). L'`AttributeError` est avalée par le `except Exception: pass`
de `protocol.py:165-166`. Résultat net : aucun des deux délais n'est jamais actif
après la phase 1, et le `except socket_timeout` de `protocol.py:115` est du code
mort.

Le troisième mérite une note : `GENSECStream.write` et `GENSECStream.read`
appellent `self.negotiate` si `client_ctx` est nul, mais `GENSECStream` ne
définit que `negotiate_server`. Ce chemin est mort en pratique
(`protocol.py:96-97` appelle toujours `negotiate_server` immédiatement après
l'instanciation), mais c'est un vestige de copie depuis `GSSAPIStream`, qui lui
possède bien `negotiate` (`gssapi.py:33`).

Enfin, un point de gouvernance de code : `src/nettcp/` et `src/wcf/` sont des
bibliothèques vendorées, explicitement exclues des normes du projet dans
`pyproject.toml` (`extend-exclude = ["tools", "src/nettcp", "src/wcf"]`, ligne 11,
et `exclude = '^src/(nettcp|wcf)/'` pour mypy, ligne 31). C'est ce qui explique
que `gssapi.py` héberge deux classes dans un même fichier, du code commenté et
des fonctions dépassant vingt lignes, en contradiction apparente avec le §6.1 du
`CLAUDE.md`. Toute réécriture de cette couche devrait, elle, s'y conformer.
